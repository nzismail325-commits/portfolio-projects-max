# -*- coding: utf-8 -*-
"""core/proxy_api.py —— OpenAI 兼容接口（chat / completions / models / responses / messages）

本模块是「客户端协议 ↔ 上游流」的翻译与记账层，路由组形式挂进入口：
- GET  /v1/models、/models
- POST /v1/chat/completions、/v1/completions
- POST /v1/responses
- GET  /health

每条路径都遵循同一套流程：
  鉴权与 Key 限制 → 选出口 → 渠道适配器开流 → 透传/翻译 → 记账。

渠道选择：模型名判定（intel/catalog）→ 注册表找声明了该出口的适配器 →
适配器自己负责选号与治理。因此本模块对 WorkBuddy 无任何了解。
"""
import hashlib
import json
import os
import time
import urllib.error
import uuid

from core import authz
from core import http as http_mod
from core import net
from core import protocol
from core import ratelimit
from core import streaming
from core import upstream_body
from core import upstream_pool
from core import web_tools
from infra import egress
from infra import settings
from integrations import registry
from intel import catalog
from intel import tiers

#: 请求体缺省模型（与二开一致：国内版默认模型）
DEFAULT_CHAT_MODEL = "hy4-preview"


def _resolve_channel(handler, model, realm_hint=None):
    """按出口找渠道适配器；返回 (adapter, realm) 或 (None, realm)。

    判定次序：显式出站前缀（trae/xxx 直达，压过 Key 绑定——客户端点名了
    渠道就是它的意思）> 显式出口参数/Key 绑定 > 模型名判定 > 当前出口。
    """
    ctx = handler.ctx
    prefix_realm, stripped = registry.REGISTRY.detect_prefix_realm(model)
    if prefix_realm:
        adapter = registry.REGISTRY.find_realm_owner(prefix_realm)
        if adapter is not None:
            return adapter, prefix_realm
        # 前缀没人认领：按普通模型名继续走原判定
    explicit = realm_hint or authz.request_realm(handler)
    realm = explicit or _detect_realm(handler, stripped) or ctx.current_realm
    adapter = registry.REGISTRY.find_realm_owner(realm)
    if adapter is None:
        # 出口没有渠道认领：回落到模型名判定，再不行用当前出口
        realm = catalog.detect_model_realm(stripped, default=ctx.current_realm)
        adapter = registry.REGISTRY.find_realm_owner(realm)
    return adapter, realm


def _detect_realm(handler, model):
    """模型名 → 出口；出站前缀（如 oc/xxx）由各渠道自己声明。"""
    return catalog.detect_model_realm(model, default="") or ""


def _cross_realm_error(handler, model, realm):
    """模型与出口不匹配时给人话报错，而不是让上游回一个看不懂的 403。"""
    if not realm or not model:
        return ""
    owner = catalog.exclusive_realm(model)
    if not owner or owner == realm:
        return ""
    name = (getattr(handler, "key_entry", None) or {}).get("name") or "当前 Key"
    served = "国内版" if owner == "cn" else "国际版"
    used = "国内版" if realm == "cn" else "国际版"
    return ("模型 %s 只在%s提供，但「%s」绑定的是%s出口。"
            "请改用对应出口的 Key，或把该 Key 的出口改为「跟随面板切换」。"
            % (model, served, name, used))


def _elapsed_ms(t_start):
    """t_start 起的墙钟毫秒（记账与 TTFT 共用同一口径）。"""
    return int((time.time() - t_start) * 1000)


def _record_error(ctx, model, status, message, t_start, realm=None, account=None):
    ctx.usage.record_error(model, status, message,
                           elapsed_ms=_elapsed_ms(t_start),
                           realm=realm, account=account)


def _stream_error_response(handler, exc, model, realm=""):
    """聚合路径吃到流中错误时把治理语义透传（Trae 等渠道的错误发生在流中：
    HTTPError 带 402/429 等真实状态码，账号罚则已在流内执行完毕）。"""
    if isinstance(exc, urllib.error.HTTPError):
        raw = net.read_http_error(exc, 600)
        detail = raw.decode("utf-8", "replace") if raw else ""
        return handler.error(exc.code, detail or str(exc))
    return handler.error(502, "upstream stream error: %s" % exc)


def _open_stream(handler, adapter, payload, realm, session_key=None):
    """调用渠道适配器开流；把三类治理异常翻译成 HTTP 响应并返回 None。"""
    ctx = handler.ctx
    try:
        return adapter.open_stream(ctx, payload, session_key=session_key, realm=realm)
    except ratelimit.RateLimited as exc:
        _record_error(ctx, payload.get("model"), 429, exc.detail[:200],
                      time.time(), realm=realm,
                      account=getattr(exc, "account_uid", None))
        handler.rate_limited(exc)
        return None
    except ratelimit.ContentRejected as exc:
        _record_error(ctx, payload.get("model"), 403, exc.detail[:200],
                      time.time(), realm=realm, account=exc.account_uid)
        handler.error(403, str(exc))
        return None
    except urllib.error.HTTPError as exc:
        raw = net.read_http_error(exc, 600)
        detail = raw.decode("utf-8", "replace") if raw else ""
        _record_error(ctx, payload.get("model"), exc.code, detail or str(exc),
                      time.time(), realm=realm,
                      account=getattr(exc, "account_uid", None))
        handler.error(exc.code, "upstream %d: %s" % (exc.code, detail or exc))
        return None
    except Exception as exc:
        status = getattr(exc, "status", None) or 502
        message = str(exc)
        _record_error(ctx, payload.get("model"), status, message, time.time(),
                      realm=realm, account=getattr(exc, "account_uid", None))
        if status == 403:
            handler.error(403, message)
        elif message.startswith("no usable account"):
            handler.error(503, message + " - add or enable one at the dashboard (/)")
        else:
            handler.error(502, "upstream unreachable: %s" % exc)
        return None


#: 会话亲和的消息数上限（超过则让池子轮换，避免大请求钉死一个账号）
AFFINITY_MAX_MSGS = int(os.environ.get("WB_AFFINITY_MAX_MSGS", "400") or 0)


def _session_key(handler, payload):
    """会话标识：客户端给的对话/会话 id（各家客户端写法不同，全收）。

    一个 id 都没给时，只有「更稳的会话粘滞键」开着才按对话前缀派生；关着就返回
    None——没有粘滞键、由池子轮询，与改动前一字不差。
    """
    key = (
        handler.headers.get("X-Conversation-Id")
        or handler.headers.get("Conversation-Id")
        or handler.headers.get("X-Session-Id")
        or handler.headers.get("Session-Id")
        or payload.get("conversation_id")
        or payload.get("session_id")
        or (payload.get("metadata") or {}).get("conversation_id")
    )
    if key:
        return str(key).strip() or None
    return _prefix_session_key(handler, payload)


def _prefix_session_key(handler, payload):
    """客户端没带会话 id 时按对话前缀派生粘滞键（开关默认关）。

    上游的 prompt cache 是账号级的：同一段对话的每一轮都落到同一个账号，第 2 轮
    起才吃得到缓存；而不少客户端根本不发会话 id。取前三条消息而不是前两条——
    两段开场白相同的对话用前两条会算出同一个键、每轮互相覆盖，把首条 assistant
    回复算进去之后，它们从第二轮起各走各的账号。
    """
    try:
        if not settings.affinity_stable_key_enabled(handler.ctx.accounts_dir):
            return None
        messages = payload.get("messages") or []
        if not messages:
            return None
        head = messages[:3] if len(messages) > 2 else messages[:2]
        blob = json.dumps(head, ensure_ascii=False, sort_keys=True)
        return "pfx-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _affinity_gate(handler, payload, session_key):
    """超长对话解除会话亲和（钉住的账号每轮都收大请求，让池子轮换）。"""
    if AFFINITY_MAX_MSGS <= 0:
        return session_key
    try:
        over = len(payload.get("messages") or []) > AFFINITY_MAX_MSGS
    except TypeError:
        over = False
    if session_key and over:
        if handler.ctx.pool:
            handler.ctx.pool.affinity.unbind(session_key)
        return None
    return session_key


def _prepare_chat(handler, payload, capability, cap_error="出口 %s 不支持对话接口"):
    """三个对话入口共享的前置链：Key 模型白名单 → 渠道解析 → 能力 → 跨域 → 会话亲和。

    前置失败时已写出错误响应，返回 None；成功返回 (adapter, realm, session_key)。
    模型名带显式出站前缀（如 trae/xxx）时在解析出渠道后剥掉前缀——适配器只
    见裸名，与二开「网关剥前缀、适配器双保险」的分工一致。
    """
    model = payload.get("model") or DEFAULT_CHAT_MODEL
    blocked = authz.key_model_error(handler, model)
    if blocked:
        return handler.error(400, blocked, "invalid_request_error")
    adapter, realm = _resolve_channel(handler, model)
    if adapter is None:
        return handler.error(400, "没有渠道提供出口 %s 的对话能力" % realm,
                             "invalid_request_error")
    if capability not in (adapter.capabilities or ()):
        return handler.error(400, cap_error % realm, "invalid_request_error")
    _prefix_realm, stripped = registry.REGISTRY.detect_prefix_realm(model)
    if _prefix_realm and stripped != model:
        payload["model"] = stripped
        model = stripped
    blocked = _cross_realm_error(handler, model, realm)
    if blocked:
        return handler.error(400, blocked, "invalid_request_error")
    session_key = _affinity_gate(handler, payload, _session_key(handler, payload))
    return adapter, realm, session_key


def _acquire_chat_slot_or_busy(handler):
    """取对话并发槽；拿不到时写 503 并返回 False（三个对话入口共享）。"""
    if http_mod.acquire_chat_slot():
        return True
    handler.error(503, "gateway busy: too many in-flight chat requests",
                  "server_error")
    return False


def _release_request_slots(handler):
    """一次对话请求收尾：还回全局并发槽与本次占的账号级名额。

    账号级名额在这里归还，而流早已读完（`with upstream:` 退出）才走到这里，与
    「响应对象关闭时归还」等价；换号重试中途弃用的账号更早在 pick 里就还回了
    （见 AccountPool._release_excluded），所以不会漏。
    """
    http_mod.release_chat_slot()
    pool = getattr(handler.ctx, "pool", None)
    if pool is None:
        return
    try:
        pool.release_request_slots()
    except Exception:
        pass


# ---------------------------------------------------------------- chat
def chat_completions(handler, path):
    ctx = handler.ctx
    payload = handler.read_json()
    model = payload.get("model") or DEFAULT_CHAT_MODEL
    t_start = time.time()

    _prep = _prepare_chat(handler, payload, registry.CAP_CHAT)
    if _prep is None:
        return
    adapter, realm, session_key = _prep
    model = payload.get("model") or DEFAULT_CHAT_MODEL  # 前缀渠道已在 _prepare_chat 剥掉
    forwarded = upstream_body.build_upstream_body(payload, ctx.system_prompt)
    fp = upstream_body.prompt_fingerprint(forwarded.get("messages"))
    want_stream = bool(payload.get("stream"))

    if not _acquire_chat_slot_or_busy(handler):
        return
    try:
        opened = _open_stream(handler, adapter, payload, realm, session_key)
        if opened is None:
            return
        upstream, attribution = opened
        with upstream:
            if want_stream:
                def reopen():
                    """未给客户端任何字节时，同请求重开一次（换连接/换号）。"""
                    try:
                        return adapter.open_stream(
                            ctx, payload, session_key=session_key, realm=realm)
                    except Exception:
                        return None
                return _stream_chat(handler, upstream, model, realm, attribution,
                                    fp, t_start, reopen=reopen)
            return _aggregate_chat(handler, upstream, model, realm, attribution,
                                   fp, t_start)
    finally:
        _release_request_slots(handler)


def _stream_chat(handler, upstream, model, realm, attribution, fp, t_start,
                 reopen=None, headers_sent=False, retried=False):
    ctx = handler.ctx
    ctx.usage  # noqa: B018
    if not headers_sent:
        handler.start_sse()
    emitted = False
    last_usage = None
    streamed_text = []
    first_ms = None
    account = attribution.get("account")
    egress_key = attribution.get("egress_key")

    def try_reopen():
        """未出字节时同请求重开一次；成功接管后续输出并返回 True。"""
        if emitted or reopen is None or retried:
            return False
        try:
            upstream.close()
        except Exception:
            pass
        opened = None
        try:
            opened = reopen()
        except Exception:
            opened = None
        if opened is None:
            return False
        new_upstream, new_attribution = opened
        try:
            _stream_chat(handler, new_upstream, model, realm, new_attribution,
                         fp, t_start, reopen=None, headers_sent=True,
                         retried=True)
        finally:
            try:
                new_upstream.close()
            except Exception:
                pass
        return True

    # 一轮回复只带一个 chunk id，且必须是网关自己的那个：上游帧带上游 id，
    # 网关改写出来的文本/工具帧带 chatcmpl-wb-* 的 id，同一条回复会以两个
    # id 交错发出。按 id 管理流状态的客户端会把推理那半（上游 id、永远没有
    # finish_reason）和正文那半当成两条流，于是界面卡在「生成中」（上游
    # v1.7.30 #607）。
    stream_chunk_id = "chatcmpl-wb-" + uuid.uuid4().hex[:16]
    # 心跳覆盖「上游还在思考」的那段静默：只在读之前检查的保活跑不进阻塞读。
    # 它与下面的业务写入共用同一把锁，注释帧不会劈开任何一帧。
    heartbeat = streaming.SSEHeartbeat(
        lambda data: (handler.wfile.write(data), handler.wfile.flush()))
    try:
        for data, maybe in streaming.iter_sse_chunks(upstream):
            try:
                usage = maybe.get("usage")
                if usage and streaming.usage_outgrew(last_usage, usage):
                    last_usage = usage
                for choice in maybe.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        streamed_text.append(delta["content"])
                    if delta.get("reasoning_content"):
                        streamed_text.append(delta["reasoning_content"])
                if maybe.get("id"):
                    maybe["id"] = stream_chunk_id
                    # 改的是对象，交给 clean_chunk 的必须重新序列化后的文本，
                    # 否则归一过的 id 会被原始字符串盖回去。
                    data = json.dumps(maybe, ensure_ascii=False)
                if usage is not None:
                    # include_usage 契约：usage 必须走独立的 choices-less
                    # 尾帧；挂在正文帧上会被严格客户端/下游网关拒绝。
                    maybe.pop("usage", None)
                    if not maybe.get("choices"):
                        continue
                    data = json.dumps(maybe, ensure_ascii=False)
            except Exception:
                pass
            cleaned = streaming.clean_chunk(data)
            if not cleaned:
                continue
            if first_ms is None:
                first_ms = _elapsed_ms(t_start)
            emitted = True
            heartbeat.write(("data: %s\n\n" % cleaned).encode("utf-8"))
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        streaming.record_stream_usage(ctx, model, last_usage, t_start=t_start,
                                      first_ms=first_ms, fp=fp, account=account,
                                      realm=realm)
        return
    except Exception as exc:
        if egress_key:
            # 出口没读完，记一次瞬时失败（成功记账在完整读完后）
            egress.note_transient(egress_key)
        if try_reopen():
            return
        _record_error(ctx, model, 502, "stream aborted: %s" % exc, t_start,
                      realm=realm, account=account)
        streaming.record_stream_usage(ctx, model, last_usage, t_start=t_start,
                                      first_ms=first_ms, fp=fp, account=account,
                                      realm=realm)
        try:
            handler.wfile.write(streaming.chat_stream_error_frame(
                "upstream stream aborted: %s" % exc))
            handler.wfile.flush()
        except Exception:
            pass
        return
    finally:
        # 所有退出路径（正常结束、断流、重开）都经这里收尾，不留空转线程。
        heartbeat.close()
    if not emitted:
        if egress_key:
            egress.note_transient(egress_key)
        # 空流/静默截断也属于「没出内容就失败」，同样先尝试重开一次
        if try_reopen():
            return
        err = json.dumps({"error": {"message": "empty upstream stream",
                                    "type": "server_error"}})
        handler.wfile.write(("data: %s\n\n" % err).encode("utf-8"))
    elif last_usage is not None:
        usage_chunk = {
            "id": stream_chunk_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [],
            "usage": last_usage,
        }
        try:
            handler.wfile.write(("data: %s\n\n" % json.dumps(
                usage_chunk, ensure_ascii=False)).encode("utf-8"))
            handler.wfile.flush()
        except Exception:
            pass
    handler.wfile.write(b"data: [DONE]\n\n")
    handler.wfile.flush()
    # 完整读完才算这条出口成功；重试成功不抵消上一次断流信号
    if egress_key and emitted and not retried:
        egress.note_success(egress_key)
    # 断流兜底：没拿到真实 usage 时按已流出文本估算，请求行不至于整行丢失
    if last_usage is None or not (last_usage.get("total_tokens") or 0):
        fallback = streaming.estimated_usage_from_text(streamed_text)
        if fallback:
            last_usage = fallback
    streaming.record_stream_usage(ctx, model, last_usage, t_start=t_start,
                                  first_ms=first_ms, fp=fp, account=account,
                                  realm=realm)


def _aggregate_chat(handler, upstream, model, realm, attribution, fp, t_start):
    ctx = handler.ctx
    egress_key = attribution.get("egress_key")
    try:
        result = streaming.aggregate_stream(upstream, model, None)
    except Exception as exc:
        if egress_key:
            egress.note_transient(egress_key)
        return _stream_error_response(handler, exc, model, realm)
    if egress_key:
        egress.note_success(egress_key)
    first_at = result.get("first_chunk_at")
    first_ms = _elapsed_ms(first_at) if first_at else None
    streaming.record_stream_usage(ctx, model, result.get("usage"), t_start=t_start,
                                  first_ms=first_ms, fp=fp,
                                  account=attribution.get("account"), realm=realm,
                                  stream=False)
    result.pop("first_chunk_at", None)
    result.pop("elapsed_ms", None)
    return handler.json(200, result)


# ---------------------------------------------------------------- completions
def completions(handler, path):
    """旧版 /v1/completions：把 prompt 包成一条 user 消息走 chat。

    前置校验（Key 白名单 / 能力 / 跨域 / 会话亲和）与并发槽与 chat 同一条链；
    响应形状保持 text_completion：流式原样转发上游行，聚合折成单条 text。
    """
    payload = handler.read_json()
    prompt = payload.get("prompt")
    if isinstance(prompt, list):
        prompt = "\n".join(str(item) for item in prompt)
    messages = [{"role": "user", "content": str(prompt or "")}]
    chat_payload = dict(payload)
    chat_payload["messages"] = messages
    chat_payload.pop("prompt", None)
    chat_payload["stream"] = bool(payload.get("stream"))
    t_start = time.time()
    _prep = _prepare_chat(handler, chat_payload, registry.CAP_CHAT)
    if _prep is None:
        return
    adapter, realm, session_key = _prep
    chat_payload["model"] = chat_payload.get("model") or DEFAULT_CHAT_MODEL
    if not _acquire_chat_slot_or_busy(handler):
        return
    try:
        return _completion_via_chat(handler, chat_payload, adapter, realm,
                                    session_key, t_start)
    finally:
        _release_request_slots(handler)


def _completion_via_chat(handler, payload, adapter, realm, session_key, t_start):
    model = payload.get("model") or DEFAULT_CHAT_MODEL
    opened = _open_stream(handler, adapter, payload, realm, session_key)
    if opened is None:
        return
    upstream, attribution = opened
    want_stream = bool(payload.get("stream"))
    with upstream:
        if want_stream:
            handler.start_sse()
            try:
                for line in upstream:
                    handler.wfile.write(line)
                    handler.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return
            return
        try:
            result = streaming.aggregate_stream(upstream, model, None)
        except Exception as exc:
            return _stream_error_response(handler, exc, model, realm)
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        body = {
            "id": result.get("id") or "cmpl-wb",
            "object": "text_completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "text": text,
                         "finish_reason": choice.get("finish_reason") or "stop"}],
        }
        if result.get("usage"):
            body["usage"] = result["usage"]
        streaming.record_stream_usage(handler.ctx, model, result.get("usage"),
                                      t_start=t_start,
                                      account=attribution.get("account"),
                                      realm=realm, stream=False)
        return handler.json(200, body)


# ---------------------------------------------------------------- models
def model_servable(ctx, model, realm):
    """池里是否至少有一个账号能服务该模型。

    PRO 专属模型需要付费账号；其余模型只需要该出口有一个启用且有凭据的
    账号。临时冷却/额度不参与判断——否则目录会随冷却频繁消失又出现。
    没有账号池时保持全量目录（新装环境行为不变）。
    """
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return True
    usable = [a for a in pool.accounts
              if getattr(a, "realm", "") == realm
              and getattr(a, "enabled", False)
              and (getattr(a, "access_token", "")
                   or getattr(a, "refresh_token", ""))]
    if not usable:
        return False
    if tiers.requires_pro(model, realm):
        return any(getattr(a, "is_paid_user", False) for a in usable)
    return True


def models(handler, path):
    ctx = handler.ctx
    realm = authz.request_realm(handler) or ctx.current_realm
    adapter, realm = _resolve_channel(handler, "", realm_hint=realm)
    if adapter is None:
        return handler.error(502, "没有渠道提供出口 %s 的模型目录" % realm)
    try:
        entries = catalog.fetch_models(realm=realm, log=ctx.log)
    except Exception as exc:
        return handler.error(502, str(exc))
    data = [catalog.model_entry(mid, meta, realm=realm) for mid, meta in entries]
    # 可选：只宣告当前 Key 能用的模型，自动发现型客户端不会选到必被拒的项
    key_entry = getattr(handler, "key_entry", None)
    if key_entry and settings.filter_models_by_key(ctx.accounts_dir):
        data = [entry for entry in data
                if settings.key_allows_model(key_entry, entry.get("id"))]
    if settings.models_only_available(ctx.accounts_dir):
        data = [entry for entry in data
                if model_servable(ctx, entry.get("id"), realm)]
    # 单向标注——只说「免费账号不可用」，从不宣称可用。数据源就是调度器拦人
    # 用的那份 tier 表（上游目录的 modelTiers），所以标注与实际拦截不可能互相
    # 矛盾：被门控的模型在本地就被拒，请求根本发不到上游。没有标注 = 未知，
    # 不等于可用（对齐上游 v1.7.30 #609）。
    gate_at = tiers.ingested_at(realm)
    for entry in data:
        if tiers.requires_pro(entry.get("id"), realm):
            entry["entitlement"] = {
                "source": "catalog",
                "required": "standard",
                "at": gate_at,
            }
    return handler.json(200, {"object": "list", "data": data, "realm": realm})


# ---------------------------------------------------------------- responses
def responses(handler, path):
    """Responses 协议：翻译成 chat 上游，再把结果折回 Responses 形状。"""
    payload = handler.read_json()
    # 网关不存 response 状态，无法回放上一轮；默默忽略会让续聊丢失上下文，
    # 客户端却收到一份看起来正常的回答。明确拒绝（对齐上游 v1.7.16）。
    if payload.get("previous_response_id"):
        return handler.error(
            400,
            "previous_response_id is not supported: this gateway does not "
            "store response state. Send the full conversation in 'input' "
            "instead, or use a stateless client.",
            "invalid_request_error")
    model = payload.get("model") or DEFAULT_CHAT_MODEL
    t_start = time.time()
    _prep = _prepare_chat(handler, payload, registry.CAP_RESPONSES,
                          cap_error="出口 %s 不支持 Responses 协议")
    if _prep is None:
        return
    adapter, realm, session_key = _prep
    model = payload.get("model") or DEFAULT_CHAT_MODEL  # 前缀渠道已在 _prepare_chat 剥掉
    # 工具可能在顶层，也可能整份在 input 的 additional_tools 条目里；出站、
    # 回程与 custom 判定必须看同一份合并清单（对齐上游 v1.7.2/v1.7.3）。
    all_tools = payload.get("tools")
    all_tools = list(all_tools) if isinstance(all_tools, list) else []
    all_tools.extend(protocol.additional_tools_from_input(payload))
    custom_names = protocol.custom_tool_names(all_tools)
    request_meta = {
        "tools": all_tools,
        "tool_choice": payload.get("tool_choice", "auto"),
        "parallel_tool_calls": payload.get("parallel_tool_calls", True),
    }
    want_stream = bool(payload.get("stream"))
    chat_payload = protocol.responses_to_chat(payload, log=handler.ctx.log)
    namespace_map = chat_payload.pop("_namespace_map", None)
    # 本地网络工具（默认关）：客户端宣告 web_search / web_fetch 时由网关代跑，
    # 把那份伺服器端宣告换成自己的 function。关着时原样透传，行为与从前一致。
    own_web_tools = False
    if web_tools.enabled(handler.ctx):
        own_web_tools = web_tools.install(chat_payload, all_tools)
    fp = upstream_body.prompt_fingerprint(chat_payload.get("messages"))

    if not _acquire_chat_slot_or_busy(handler):
        return
    try:
        opened = _open_stream(handler, adapter, chat_payload, realm, session_key)
        if opened is None:
            return
        upstream, attribution = opened
        try:
            if want_stream:
                return _stream_responses(handler, upstream, model, realm,
                                         attribution, fp, t_start, custom_names,
                                         adapter=adapter, chat_payload=chat_payload,
                                         session_key=session_key,
                                         own_web_tools=own_web_tools,
                                         request_meta=request_meta,
                                         namespace_map=namespace_map,
                                         input_text=str(payload.get("input") or ""))
            return _aggregate_responses(handler, upstream, model, realm,
                                        attribution, fp, t_start, custom_names,
                                        adapter=adapter, chat_payload=chat_payload,
                                        session_key=session_key,
                                        own_web_tools=own_web_tools,
                                        request_meta=request_meta,
                                        namespace_map=namespace_map)
        finally:
            # 代跑多轮时 upstream 会被换掉，最后一条在这里统一收掉
            try:
                upstream.close()
            except Exception:
                pass
    finally:
        _release_request_slots(handler)


def _aggregate_responses(handler, upstream, model, realm, attribution, fp, t_start,
                         custom_names, adapter=None, chat_payload=None,
                         session_key=None, own_web_tools=False,
                         request_meta=None, namespace_map=None):
    """非流式 Responses：内部网路工具呼叫由网关代跑后重跑，客户端只见终态。"""
    ctx = handler.ctx
    web_sources = []
    rounds = 0
    while True:
        try:
            result = streaming.aggregate_stream(upstream, model, None)
        except Exception as exc:
            egress_key = attribution.get("egress_key")
            if egress_key:
                egress.note_transient(egress_key)
            return _stream_error_response(handler, exc, model, realm)
        egress_key = attribution.get("egress_key")
        if egress_key:
            egress.note_success(egress_key)
        if result.get("error"):
            err = result["error"]
            message = err.get("message") or str(err)
            _record_error(ctx, model, 502, message, t_start, realm=realm,
                          account=attribution.get("account"))
            return handler.error(502, "upstream stream error: %s" % message)
        calls = web_tools.internal_calls_from_chat(result, own_web_tools=own_web_tools)
        if not calls:
            break
        rounds += 1
        give_up = rounds > web_tools.max_rounds()
        try:
            upstream.close()
        except Exception:
            pass
        body = web_tools.follow_up_body(chat_payload, calls, web_sources,
                                        drop_tools=give_up)
        opened = _open_stream(handler, adapter, body, realm, session_key)
        if opened is None:
            return
        upstream, attribution = opened

    first_at = result.get("first_chunk_at")
    first_ms = _elapsed_ms(first_at) if first_at else None
    streaming.record_stream_usage(ctx, model, result.get("usage"), t_start=t_start,
                                  first_ms=first_ms, fp=fp,
                                  account=attribution.get("account"), realm=realm,
                                  stream=False)
    response_obj = protocol.chat_to_response(
        result, model, custom_names, request_meta=request_meta,
        namespace_map=namespace_map, sources=web_sources)
    if protocol.reasoning_only_response(response_obj):
        message = "upstream returned reasoning without output text; retry"
        _record_error(ctx, model, 502, message, t_start, realm=realm,
                      account=attribution.get("account"))
        return handler.error(502, message)
    return handler.json(200, response_obj)


def _stream_responses(handler, upstream, model, realm, attribution, fp, t_start,
                      custom_names, adapter=None, chat_payload=None,
                      session_key=None, own_web_tools=False,
                      request_meta=None, namespace_map=None, input_text=""):
    ctx = handler.ctx
    handler.start_sse()
    holder = {"usage": None, "custom_names": custom_names,
              "base_body": chat_payload, "web_sources": [],
              "request_meta": request_meta or {},
              "namespace_map": namespace_map or {},
              "input_text": input_text}
    first_ms = None
    rounds = 0
    total_usage = None
    heartbeat = streaming.SSEHeartbeat(
        lambda data: (handler.wfile.write(data), handler.wfile.flush()))
    try:
        while True:
            holder.pop("internal_calls", None)
            holder.pop("suppress_completion", None)
            # 第二轮起不再发 response.created：同一则回应不能被开两次
            holder["suppress_lifecycle"] = rounds > 0
            for frame in streaming.stream_responses_events(upstream, model, holder):
                if first_ms is None:
                    first_ms = _elapsed_ms(t_start)
                heartbeat.write(streaming.clean_responses_frame(frame))
            egress_key = attribution.get("egress_key")
            if egress_key:
                egress.note_success(egress_key)
            # 代跑多轮时每一轮的 token 都是真花掉的，记帐要加总
            total_usage = web_tools.sum_usage(total_usage, holder.get("usage"))
            internal = holder.get("internal_calls") or []
            if not internal:
                break
            rounds += 1
            give_up = rounds > web_tools.max_rounds()
            try:
                upstream.close()
            except Exception:
                pass
            body = web_tools.follow_up_body(chat_payload, internal,
                                            holder.get("web_sources") or [],
                                            drop_tools=give_up)
            opened = _open_stream(handler, adapter, body, realm, session_key)
            if opened is None:
                return
            upstream, attribution = opened
        holder["usage"] = total_usage
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        streaming.record_stream_usage(ctx, model, holder.get("usage"),
                                      t_start=t_start, first_ms=first_ms, fp=fp,
                                      account=attribution.get("account"),
                                      realm=realm)
        return
    except Exception as exc:
        egress_key = attribution.get("egress_key")
        if egress_key:
            egress.note_transient(egress_key)
        _record_error(ctx, model, 502, "stream aborted: %s" % exc, t_start,
                      realm=realm)
        streaming.record_stream_usage(ctx, model, holder.get("usage"),
                                      t_start=t_start, first_ms=first_ms, fp=fp,
                                      account=attribution.get("account"),
                                      realm=realm)
        # 上游中途断掉时发 Responses 的 error 事件，不能补 chat 风格的 [DONE]
        try:
            handler.wfile.write(streaming.responses_stream_error_frame(
                "upstream stream aborted: %s" % exc))
            handler.wfile.flush()
        except Exception:
            pass
        return
    finally:
        # 心跳必须在这里收尾：正常结束、断流、以及 follow_up 重开失败那条
        # 直接 return 的路径都会经过它，不会留下空转的线程。
        heartbeat.close()
    streaming.record_stream_usage(ctx, model, holder.get("usage"), t_start=t_start,
                                  first_ms=first_ms, fp=fp,
                                  account=attribution.get("account"), realm=realm)


# ---------------------------------------------------------------- health
def health(handler, path):
    ctx = handler.ctx
    pool = ctx.pool
    info = {
        "ok": True,
        "realm": ctx.current_realm,
        "accounts": len(pool.accounts) if pool else 0,
        "accounts_ready": pool.count_ready() if pool else 0,
        # 分出口口径（侧栏按出口分示，避免与页面内单出口数字对不上）
        "by_realm": {
            realm: {
                "accounts": sum(1 for a in pool.accounts if a.realm == realm),
                "ready": pool.count_ready(realm=realm),
            } for realm in sorted({getattr(a, "realm", "") for a in pool.accounts})
        } if pool else {},
        "api_key_required": authz.auth_required(ctx),
        "version": ctx.version(),
        "channels": [meta.get("id") for meta in registry.panel_channels(ctx)],
        "pool": upstream_pool.stats(),
    }
    return handler.json(200, info)


def install(router=None):
    router = router or http_mod.ROUTER
    router.add("GET", "/v1/models", models, needs_auth=True, exact=True)
    router.add("GET", "/models", models, needs_auth=True, exact=True)
    router.add("POST", "/v1/chat/completions", chat_completions, exact=True)
    router.add("POST", "/chat/completions", chat_completions, exact=True)
    router.add("POST", "/v1/completions", completions, exact=True)
    router.add("POST", "/completions", completions, exact=True)
    router.add("POST", "/v1/responses", responses, exact=True)
    router.add("POST", "/responses", responses, exact=True)
    router.add("GET", "/health", health, needs_auth=False, exact=True)
