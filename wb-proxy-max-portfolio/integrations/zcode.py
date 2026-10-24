# -*- coding: utf-8 -*-
"""integrations/zcode.py —— ZCode（智谱 GLM 编码套餐）反代渠道

协议事实来自 AgentHub v1.77.0 的 zcode 适配器（zcodeLocal / zcodeAnthropic /
zcodeOfficialSystem）：
- 上游统一是 Anthropic Messages 协议；对话先走 coding-plan（付费套餐 key），
  没有或欠费时回退 start-plan（zcodejwt）。start-plan 要求 system 以官方
  ZCode 提示词开头，否则 405 / code 3012；
- 一个账号是双凭据：zcodejwttoken（start-plan + 控制面）与
  account-provider coding-plan key（"{apiKey}.{secret}"）；
- 控制面：billing/balance、billing/current，账号级 X-Device-Mid 指纹
  （每号独立，防设备关联）；
- 登录：服务端中介 CLI 轮询（无回环端口），手动兜底粘贴 zcode:// 深链；
- 本机导入：~/.zcode/v2/credentials.json + account-profiles/profiles.json。

本模块只依赖核心设施；核心不引用任何 zcode 字样。
"""
import concurrent.futures
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from auth import accounts as accounts_mod
from core import net
from core import upstream_body
from integrations import registry
from integrations import zcode_anthropic
from integrations import zcode_local
from integrations import zcode_official_system

REALM = "zcode"
LABEL = "ZCode（智谱）"
SHORT = "ZCode"
BADGE = "ZCode"
DOMAIN = "zcode.z.ai"
MODEL_CACHE_TTL = 300.0
CREDITS_TTL = 60.0
LOGIN_TIMEOUT = 180.0
CAPTCHA_NOTE = ("上游要求人机校验（阿里云验证码），本网关不能自动过码；"
                "请先在官方 ZCode 客户端完成一次验证后重试")

CFG = {
    "appVersion": "4.1.10",
    "sourceTitle": "cli",
    "refererOrigin": "https://zcode.z.ai",
    "zaiAnthropicBase": "https://api.z.ai/api/anthropic",
    "bigmodelAnthropicBase": "https://open.bigmodel.cn/api/anthropic",
    "startPlanAnthropicBase": "https://zcode.z.ai/api/v1/zcode-plan/anthropic",
    "billingBase": "https://zcode.z.ai/api/v1/zcode-plan",
    "oauthInitUrl": "https://zcode.z.ai/api/v1/oauth/cli/init",
    "oauthPollBase": "https://zcode.z.ai/api/v1/oauth/cli/poll",
    "oauthTokenUrl": "https://zcode.z.ai/api/v1/oauth/token",
    "businessLoginUrl": "https://api.z.ai/api/auth/z/login",
    "zaiBizBase": "https://api.z.ai",
    "bigmodelBizBase": "https://bigmodel.cn",
    "monitorQuotaUrl": "https://open.bigmodel.cn/api/monitor/usage/quota/limit",
    "oauthProvider": "zai",
    "platform": "win32-x64",
    "timezone": "Asia/Shanghai",
}

#: pinned 静态兜底（客户端 zcode-builtin.json 可覆盖能力/上限）
STATIC_MODELS = [
    {"id": "GLM-5.3", "context": 1000000, "output": 128000, "images": False},
    {"id": "GLM-5.3-Flash", "context": 1000000, "output": 128000, "images": True},
    {"id": "GLM-5.2", "context": 1000000, "output": 128000, "images": False},
    {"id": "GLM-5.1", "context": 200000, "output": 64000, "images": False},
    {"id": "GLM-5-Turbo", "context": 200000, "output": 64000, "images": False},
    {"id": "GLM-4.7", "context": 200000, "output": 131072, "images": False},
    {"id": "GLM-4.6", "context": 200000, "output": 131072, "images": False},
    {"id": "GLM-4.5-Air", "context": 131072, "output": 98304, "images": False},
]
STATIC_BY_ID = {item["id"].lower(): item for item in STATIC_MODELS}

_MODEL_CACHE = {}       # realm -> {"at": ts, "models": [(id, meta)]}
_MODEL_LOCK = threading.Lock()
_CREDITS_CACHE = {}     # (realm, uid) -> (at, result)
_CREDITS_LOCK = threading.Lock()


class ZcodeError(RuntimeError):
    """上游错误（已按 zcode 业务码翻译成 HTTP 语义）。"""

    def __init__(self, status, message, code=0, plan_limit=False,
                 need_captcha=False, retry_after=None, detail="", plan="",
                 empty_stream=False):
        super().__init__(message)
        self.status = int(status or 502)
        self.message = str(message or "")
        self.zcode_code = int(code or 0)
        self.plan_limit = bool(plan_limit)
        self.need_captcha = bool(need_captcha)
        self.retry_after = retry_after
        self.detail = str(detail or "")
        self.plan = plan
        self.empty_stream = bool(empty_stream)


def _log(message, ctx=None):
    line = "zcode: %s" % message
    sink = getattr(ctx, "log", None) if ctx is not None else None
    if callable(sink):
        try:
            sink(line)
            return
        except Exception:
            pass
    try:
        import sys
        sys.stderr.write("[wb-proxy-max] %s\n" % line)
    except Exception:
        pass


def _save(account):
    directory = getattr(account, "accounts_dir", "") or ""
    if directory:
        try:
            account.save(directory)
        except Exception:
            pass


def _meta(account):
    meta = getattr(account, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _is_coding_mode(account):
    return str(_meta(account).get("credentialMode") or "") == "coding-plan"


def _jwt(account):
    if _is_coding_mode(account):
        return ""
    return str(getattr(account, "access_token", "") or "")


def _plan_key(account):
    token = str(getattr(account, "refresh_token", "") or "")
    if not token:
        return ""
    if _is_coding_mode(account):
        return token
    if token.count(".") == 1 and not token.startswith(("dt-", "drt-")):
        return token
    return ""


def _account_mid(account, ctx=None):
    mid = str(_meta(account).get("deviceMid") or "")
    if mid:
        return mid
    mid = zcode_local.resolve_device_mid(account, ctx)
    if mid:
        meta = dict(_meta(account))
        meta["deviceMid"] = mid
        account.meta = meta
        _save(account)
    return mid


# --------------------------------------------------------------- 网络与错误
def _json_request(method, url, headers=None, body=None, timeout=30, proxy=""):
    request = urllib.request.Request(url, data=body, method=method,
                                     headers=headers or {})
    if headers:
        request.wb_exact_headers = list(headers.items())
    try:
        with net.urlopen(request, timeout=timeout, proxy=proxy) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(4000).decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw)
            except Exception:
                return exc.code, {"message": raw[:500]}
        except Exception:
            return exc.code, None
    except Exception as exc:
        if net.is_tls_verify_error(exc):
            # 证书链不信任是配置问题（公司代理解密 / 私有 CA），不是网络抖动：
            # 直接把 WB_CA_BUNDLE 指引带回上游，各调用方的报错才能落到点上
            return 0, {"_error": net.tls_verify_hint(exc)}
        return 0, {"_error": str(exc)[:240]}


def _error_message(data, fallback=""):
    if isinstance(data, dict):
        message = data.get("message") or data.get("msg")
        if not message and isinstance(data.get("error"), dict):
            message = data["error"].get("message")
        if message:
            return str(message)
        if data.get("_error"):
            return str(data["_error"])
    return str(fallback or "")


def _error_code(data):
    if isinstance(data, dict):
        if data.get("code") is not None:
            return data.get("code")
        if isinstance(data.get("error"), dict):
            return data["error"].get("code")
    return None


def _map_error(status, data, text, plan=""):
    message = _error_message(data, text)
    bracket = re.match(r"^\[(\d{3,5})\]", message)
    try:
        code = int(_error_code(data) or (bracket.group(1) if bracket else 0) or 0)
    except (TypeError, ValueError):
        code = 0
    lower = message.lower()
    quota = (status == 402 or code in (1005, 1113)
             or any(marker in message for marker in ("余额不足", "额度"))
             or any(marker in lower for marker in
                    ("insufficient", "quota exhausted", "balance", "recharge")))
    if quota:
        return ZcodeError(402, message or "额度已用完", code=code,
                          plan_limit=True, detail=text, plan=plan)
    if status == 429 or code in (3002, 3008, 3009, 3010):
        return ZcodeError(429, message or "上游限流", code=code,
                          detail=text, plan=plan)
    captcha = code == 3007 or "captcha" in lower or "verify" in lower
    if captcha:
        return ZcodeError(502, CAPTCHA_NOTE, code=3007, need_captcha=True,
                          detail=text, plan=plan)
    if status in (401, 403) or code in (401, 1006, 3012):
        return ZcodeError(401, message or "凭证失效", code=code,
                          detail=text, plan=plan)
    if status == 400 or code in (3001, 3006, 3102):
        return ZcodeError(400, message or "参数错误", code=code,
                          detail=text, plan=plan)
    final = status if 400 <= status < 600 else 502
    return ZcodeError(final, message or ("上游错误 %s" % (status or code)),
                      code=code, detail=text, plan=plan)


def _http_error(status, message, headers=None):
    return urllib.error.HTTPError(
        CFG["refererOrigin"], int(status or 502), str(message), headers, None)


def _retry_after(headers):
    try:
        return min(120.0, max(1.0, float((headers or {}).get("Retry-After") or 0)))
    except Exception:
        return 60.0


def _qs(version=""):
    return "app_version=%s&platform=%s" % (
        urllib.parse.quote(str(version or CFG["appVersion"])),
        urllib.parse.quote(str(CFG["platform"])))


# ------------------------------------------------------------------- 请求头
def _base_headers():
    return {
        "content-type": "application/json",
        "HTTP-Referer": CFG["refererOrigin"],
        "User-Agent": "ZCode/%s ai-sdk/anthropic/3.0.81" % CFG["appVersion"],
        "X-ZCode-App-Version": CFG["appVersion"],
        "X-Title": "Z Code@%s" % CFG["sourceTitle"],
        "X-Release-Channel": "stable",
        "X-Client-Language": "zh-CN",
        "X-Client-Timezone": CFG["timezone"],
        "X-Os-Category": "windows",
    }


def _llm_headers(account, plan, conversation_id):
    headers = _base_headers()
    headers.update({
        "X-ZCode-Agent": "glm",
        "X-Platform": CFG["platform"],
        "anthropic-version": "2023-06-01",
        "x-request-id": str(uuid.uuid4()),
        "x-zcode-trace-id": str(uuid.uuid4()),
        "x-zcode-session-type": "main",
    })
    clean = _clean_session_id(conversation_id)
    if plan == "coding-plan":
        key = _plan_key(account)
        headers["x-api-key"] = key
        headers["authorization"] = "Bearer " + key
        headers["x-query-id"] = str(uuid.uuid4())
        headers["x-session-id"] = clean or str(uuid.uuid4())
    else:
        headers["authorization"] = "Bearer " + _jwt(account)
    return headers


def _ctl_headers(token, account=None, ctx=None, with_local_mid=False, version=""):
    version = str(version or CFG["appVersion"])
    headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "User-Agent": "ZCode/%s" % version,
        "HTTP-Referer": CFG["refererOrigin"],
        "X-Title": "Z Code@%s" % CFG["sourceTitle"],
        "X-ZCode-App-Version": version,
        "X-Platform": CFG["platform"],
        "X-Release-Channel": "stable",
        "X-Client-Language": "zh-CN",
        "X-Client-Timezone": CFG["timezone"],
        "X-Os-Category": "windows",
    }
    if token:
        headers["authorization"] = "Bearer " + str(token)
    mid = _account_mid(account, ctx) if account is not None else (
        zcode_local.local_device_mid() if with_local_mid else "")
    if mid:
        headers["X-Device-Mid"] = mid
    return headers


def _body_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ 模型映射
def map_model(model):
    text = str(model or "").strip()
    if not re.match(r"^glm-", text, re.IGNORECASE):
        return text
    if text.startswith("GLM-"):
        return text
    parts = text.split("-")
    out = [parts[0].upper()]
    for part in parts[1:]:
        out.append(part[0].upper() + part[1:] if re.match(r"^[a-z]+$", part) else part)
    return "-".join(out)


def _static_meta(model_id):
    return dict(STATIC_BY_ID.get(str(model_id).lower()) or {})


def _model_meta(model_id):
    base = _static_meta(model_id)
    client = zcode_local.resolve_model_meta(model_id) or {}
    fmt = client.get("inputFormat") or {}
    images = fmt.get("supportsImage")
    if not isinstance(images, bool):
        images = bool(base.get("images"))
    context = client.get("contextWindow") or base.get("context") or 131072
    output = client.get("maxOutputTokens") or base.get("output") or 8192
    return {
        "name": str(model_id),
        "supportsToolCall": True,
        "supportsReasoning": True,
        "supportsImages": images,
        "context_length": int(context),
        "maxInputTokens": int(context),
        "maxOutputTokens": int(output),
    }


def _static_models():
    return [(item["id"], _model_meta(item["id"])) for item in STATIC_MODELS]


def _model_accounts(ctx):
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return []
    return [account for account in pool.accounts
            if getattr(account, "realm", "") == REALM
            and getattr(account, "enabled", False)
            and _jwt(account)]


def _models_from_balance(data):
    payload = data.get("data") if isinstance(data, dict) and isinstance(
        data.get("data"), dict) else data
    balances = payload.get("balances") if isinstance(payload, dict) else None
    ids = []
    for balance in balances if isinstance(balances, list) else []:
        capabilities = balance.get("capabilities") if isinstance(balance, dict) else None
        for capability in capabilities if isinstance(capabilities, list) else []:
            match = re.match(r"^model:(.+)$", str(capability or ""))
            if match and match.group(1) and match.group(1) not in ids:
                ids.append(match.group(1))
    return ids


def _fetch_live_models(ctx):
    for account in _model_accounts(ctx):
        jwt = _jwt(account)
        if not jwt:
            continue
        url = "%s/billing/balance?%s" % (CFG["billingBase"].rstrip("/"), _qs())
        status, data = _json_request(
            "GET", url, headers=_ctl_headers(jwt, account, ctx),
            timeout=20, proxy=getattr(account, "proxy", ""))
        if status != 200:
            continue
        ids = _models_from_balance(data)
        if ids:
            return [(model_id, _model_meta(model_id)) for model_id in ids]
    return []


def live_models(ctx, force=False):
    now = time.time()
    with _MODEL_LOCK:
        cache = _MODEL_CACHE.get(REALM)
        if cache and not force and now - cache["at"] <= MODEL_CACHE_TTL:
            return list(cache["models"])
    models = _fetch_live_models(ctx) if ctx is not None else []
    if models:
        with _MODEL_LOCK:
            _MODEL_CACHE[REALM] = {"at": now, "models": models}
        return list(models)
    if force:
        return []
    return _static_models()


# --------------------------------------------------------------------- 对话
def _stable_conv_id(messages):
    try:
        head = []
        for message in (messages or [])[:3]:
            content = message.get("content")
            text = content if isinstance(content, str) else json.dumps(
                content, ensure_ascii=False, separators=(",", ":"))
            head.append("%s:%s" % (message.get("role") or "", text))
        joined = "|".join(head)
        if not joined or joined == "||":
            return ""
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return ""


def _clean_session_id(value):
    return re.sub(r"^(sess_|subagent_agent_)", "", str(value or ""))


def _plan_base(plan, account):
    provider = str(_meta(account).get("provider") or "zai")
    if plan == "coding-plan":
        return (CFG["bigmodelAnthropicBase"] if provider == "bigmodel"
                else CFG["zaiAnthropicBase"])
    return CFG["startPlanAnthropicBase"]


def _build_request(account, model, forwarded, plan, conversation_id, ctx=None):
    upstream_model = map_model(model)
    meta = zcode_local.resolve_model_meta(upstream_model) or {}
    default_max = (meta.get("maxOutputTokens")
                   or _static_meta(upstream_model).get("output") or 8192)
    payload = zcode_anthropic.to_anthropic(
        upstream_model, forwarded, default_max_tokens=default_max)
    if plan == "start-plan":
        payload["system"] = zcode_official_system.inject_official_zcode_system(
            payload.get("system"))
    mid = _account_mid(account, ctx)
    session_id = _clean_session_id(conversation_id)
    user_id = {}
    if mid:
        user_id["device_id"] = mid
    user_id["account_uuid"] = ""
    user_id["session_id"] = session_id
    payload["metadata"] = {"user_id": json.dumps(
        user_id, ensure_ascii=False, separators=(",", ":"))}
    url = _plan_base(plan, account).rstrip("/") + "/v1/messages"
    return url, _llm_headers(account, plan, conversation_id), payload


def _open_once(ctx, account, model, forwarded, plan, conversation_id):
    if plan == "coding-plan" and not _plan_key(account):
        raise ZcodeError(401, "该账号没有 coding-plan 凭据", plan=plan)
    if plan != "coding-plan" and not _jwt(account):
        raise ZcodeError(401, "该账号没有 zcodejwt 凭据", plan=plan)
    url, headers, payload = _build_request(
        account, model, forwarded, plan, conversation_id, ctx)
    request = urllib.request.Request(url, data=_body_bytes(payload), method="POST",
                                     headers=headers)
    request.wb_exact_headers = list(headers.items())
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    connect_timeout = ctx.upstream_connect_timeout()
    try:
        resp = net.urlopen(request, timeout=header_timeout,
                           proxy=getattr(account, "proxy", ""),
                           connect_timeout=connect_timeout)
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read(4000).decode("utf-8", "replace")
        except Exception:
            text = ""
        try:
            data = json.loads(text) if text else None
        except Exception:
            data = None
        mapped = _map_error(exc.code, data, text, plan=plan)
        mapped.retry_after = _retry_after(getattr(exc, "headers", None))
        raise mapped
    net.set_stream_idle_timeout(resp, idle_timeout)
    return resp


class ZCodeChatStream(object):
    """Anthropic SSE → OpenAI chat chunk 流。"""

    def __init__(self, resp, model, account, log=None, session_key=None, pool=None):
        self._resp = resp
        self._model = model
        self._account = account
        self._log = log
        self._session_key = session_key
        self._pool = pool
        self._buffer = b""
        self._closed = False
        self._done = False
        self._sent_done = False
        self._pending = []
        self._error = None
        self._upstream_error = None
        self._priming = False
        self._produced = False
        self._finish = "stop"
        self._finish_sent = False
        self._usage = None
        self._usage_sent = False
        self._structured = False
        self._chat_id = "chatcmpl-zcode-" + uuid.uuid4().hex[:12]
        self._created = int(time.time())
        self._bridge = zcode_anthropic.create_sse_bridge(self._emit)

    @staticmethod
    def _consumable(delta):
        if not isinstance(delta, dict):
            return False
        if isinstance(delta.get("content"), str) and delta["content"]:
            return True
        if isinstance(delta.get("reasoning_content"), str) and delta["reasoning_content"]:
            return True
        calls = delta.get("tool_calls")
        return isinstance(calls, list) and bool(calls)

    def _chunk(self, choices=None, usage=None):
        obj = {
            "id": self._chat_id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self._model,
            "choices": choices or [],
        }
        if usage is not None:
            obj["usage"] = usage
        return obj

    def _emit(self, event):
        kind = event.get("type")
        if kind == "delta":
            delta = event.get("delta") or {}
            if self._consumable(delta):
                self._produced = True
            self._pending.append(self._chunk(
                choices=[{"index": 0, "delta": delta}]))
            return
        if kind == "usage":
            self._usage = event.get("usage")
            self._pending.append(self._chunk(usage=self._usage))
            self._usage_sent = True
            return
        if kind == "finish":
            self._finish = str(event.get("reason") or "stop")
            self._pending.append(self._chunk(
                choices=[{"index": 0, "delta": {}, "finish_reason": self._finish}]))
            self._finish_sent = True
            return
        if kind == "error":
            self._fail(event)

    def _unbind_session(self):
        if self._session_key and self._pool is not None:
            self._pool.affinity.unbind(self._session_key)

    @property
    def error(self):
        return self._error

    @property
    def upstream_error(self):
        return self._upstream_error

    def _fail(self, event):
        status = int(event.get("status") or 502)
        code = int(event.get("code") or 0)
        message = str(event.get("message") or "上游错误")
        if status == 402:
            text = "ZCode 额度耗尽：%s" % message
        elif status == 429:
            text = "ZCode 上游限流：%s" % message
        elif status == 401:
            text = "ZCode 凭证失效：%s" % message
        elif code == 4001 or "model config is empty" in message.lower():
            text = "ZCode 模型配置为空：%s" % message
        elif code == 3007:
            text = "ZCode 触发人机校验：%s" % message
        else:
            text = "ZCode 上游错误 code=%s：%s" % (code, message)
        error = ZcodeError(status, text, code=code,
                           plan_limit=(status == 402),
                           need_captcha=(code == 3007), detail=message)
        self._upstream_error = error
        self._unbind_session()
        if not self._priming:
            # 预读阶段的错误由 open_stream 统一治理（可能先回退 start-plan）
            _handle_upstream_error(self._account, error, self._model,
                                   self._session_key, self._pool)
        self._structured = True
        self._done = True
        self._pending.append({"error": {"message": text, "type": "upstream_error",
                                        "code": status}})
        self._error = _http_error(status, text)

    def _queue_tail(self):
        if self._usage is not None and not self._usage_sent:
            self._pending.append(self._chunk(usage=self._usage))
            self._usage_sent = True
        if not self._finish_sent:
            self._pending.append(self._chunk(
                choices=[{"index": 0, "delta": {}, "finish_reason": self._finish}]))
            self._finish_sent = True

    def _read_raw_line(self):
        while b"\n" not in self._buffer:
            if self._closed:
                return None
            try:
                chunk = self._resp.read(8192)
            except Exception:
                return None
            if not chunk:
                return None
            self._buffer += chunk
        index = self._buffer.index(b"\n")
        line = self._buffer[:index + 1]
        self._buffer = self._buffer[index + 1:]
        return line

    def _read_sse_event(self):
        data_lines = []
        while True:
            line = self._read_raw_line()
            if line is None:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text == "":
                if data_lines:
                    break
                continue
            if text.startswith(":") or text.startswith("event:"):
                continue
            if text.startswith("data:"):
                data_lines.append(text[5:].strip())
        if not data_lines:
            return None
        return "\n".join(data_lines)

    def _note_empty(self):
        self._unbind_session()
        text = "ZCode 上游返回了流但没有任何可用内容（空响应，通常为余额耗尽/账号被限）"
        self._upstream_error = ZcodeError(502, text, empty_stream=True)
        if not self._priming:
            self._account.note_failure("ZCode 空流（HTTP 200 无可用内容）")
        self._pending.append({"error": {
            "message": text, "type": "upstream_error", "code": 502}})
        self._error = _http_error(502, text)

    def prime(self):
        """读到首个可用增量（或确认失败）后再交给客户端。

        上游常用 HTTP 200 + 流内 error / 空流表示额度耗尽或账号受限；
        响应头已收下时还能换号，一旦把流交给客户端就只能如实报错。
        预读不丢事件：已产生的事件仍在 _pending 里按序下发。
        """
        self._priming = True
        try:
            return registry.prime_stream(self)
        finally:
            self._priming = False

    def _next_chunk(self):
        while True:
            if self._error is not None:
                if self._pending:
                    return self._pending.pop(0)
                raise self._error
            if self._pending:
                return self._pending.pop(0)
            if self._done:
                return None
            event = self._read_sse_event()
            if event is None:
                self._done = True
                result = self._bridge.get("result") or {}
                if self._error is not None:
                    continue
                if not self._produced and not result.get("sawError"):
                    self._note_empty()
                    continue
                self._queue_tail()
                continue
            self._bridge["onEvent"]("", event)

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        chunk = self._next_chunk()
        if chunk is None:
            if not self._sent_done:
                self._sent_done = True
                return b"data: [DONE]\n\n"
            raise StopIteration
        return ("data: " + json.dumps(chunk, ensure_ascii=False)
                + "\n\n").encode("utf-8")

    def read(self, n=-1):
        if self._closed:
            return b""
        parts = []
        total = 0
        try:
            for line in self:
                parts.append(line)
                total += len(line)
                if n is not None and n > 0 and total >= n:
                    break
        except StopIteration:
            pass
        return b"".join(parts)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._resp.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _handle_upstream_error(account, exc, model, session_key, pool):
    if exc.status == 402 or exc.plan_limit:
        account.note_balance_cooled("ZCode 额度耗尽（code %s），停车到次日 04:00"
                                    % exc.zcode_code)
        if session_key and pool:
            pool.affinity.unbind(session_key)
    elif exc.status == 429:
        wait = exc.retry_after or 60
        account.note_error("ZCode 限流（HTTP 429，冷却 %ds）" % int(wait),
                           cooldown=wait, detail=exc.detail[:200])
        if session_key and pool:
            pool.affinity.unbind(session_key)
    elif exc.status == 401:
        account.token_expired = True
        account.last_error = "ZCode 凭证失效（HTTP 401），请重新登录或导入"
        account.note_error("ZCode 凭证失效（HTTP 401）", cooldown=600)
        if session_key and pool:
            pool.affinity.unbind(session_key)
    elif exc.status == 404:
        account.note_error("该号不支持此模型（%s）" % (exc.zcode_code or 404),
                           model=model, cooldown=6 * 3600)
        if session_key and pool:
            pool.affinity.unbind(session_key)
    elif exc.zcode_code == 4001 or "model config is empty" in exc.message.lower():
        # 模型/配置问题不是账号问题：不罚号，换号继续
        account.last_error = "ZCode 模型配置为空（code 4001）"
    elif getattr(exc, "empty_stream", False):
        account.note_failure("ZCode 空流（HTTP 200 无可用内容）")
    elif exc.status == 400:
        account.last_error = "ZCode 上游拒绝请求（400）：%s" % exc.message[:200]
    elif exc.need_captcha:
        account.note_error("ZCode 触发人机校验", cooldown=60, detail=exc.message[:200])
    else:
        account.note_failure("ZCode HTTP %s：%s" % (exc.status, exc.message[:160]))
    if session_key and pool and exc.status in (401, 402, 429, 404):
        pool.affinity.unbind(session_key)


def _open_primed(ctx, account, model, forwarded, plan, conversation_id,
                 session_key=None, pool=None):
    """开流并预读到首个可用增量：未出内容的失败按上游错误抛出，交给换号链。"""
    resp = _open_once(ctx, account, model, forwarded, plan, conversation_id)
    stream = ZCodeChatStream(resp, model, account, ctx.log,
                             session_key=session_key, pool=pool)
    if stream.prime() != "ready":
        stream.close()
        if stream.upstream_error is not None:
            raise stream.upstream_error
        raise ZcodeError(502, "ZCode 上游没有返回可用内容")
    return stream


def open_stream(ctx, adapter, payload, session_key=None, realm=None):
    model = str(payload.get("model") or "").strip()
    if model.lower().startswith(REALM + "/"):
        model = model[len(REALM) + 1:].strip()
    if not model:
        raise RuntimeError("zcode: empty model")
    body = dict(payload)
    body["model"] = model
    forwarded = upstream_body.build_upstream_body(body, ctx.system_prompt)
    forwarded["model"] = model
    conversation_id = str(session_key or "") or _stable_conv_id(body.get("messages"))

    pool = ctx.pool
    total = max(1, pool.count_ready(REALM, model=model)) if pool else 1
    attempts, deadline = net.request_budget(total)
    tried = set()
    last_error = None
    last_429 = None
    last_429_detail = ""

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        account = (pool.pick_for_session(realm=REALM, session_key=session_key,
                                        exclude=tried, model=model)
                   if pool else None)
        if account is None:
            break
        if getattr(account, "realm", "") != REALM:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        jwt = _jwt(account)
        plan_key = _plan_key(account)
        if not jwt and not plan_key:
            account.last_error = "该账号没有可用 ZCode 凭据"
            last_error = _http_error(401, "ZCode 账号 %s 没有可用凭据，已自动换号"
                                     % account.uid[:8])
            continue
        try:
            if plan_key:
                try:
                    stream = _open_primed(ctx, account, model, forwarded,
                                          "coding-plan", conversation_id,
                                          session_key, pool)
                except ZcodeError as exc:
                    # 付费套餐欠费/额度尽（含流内 402）：若该号还有 jwt，
                    # 带 jwt 就地回退 start-plan 一次
                    if exc.status == 402 and jwt:
                        stream = _open_primed(ctx, account, model, forwarded,
                                              "start-plan", conversation_id,
                                              session_key, pool)
                    else:
                        raise
            else:
                stream = _open_primed(ctx, account, model, forwarded,
                                      "start-plan", conversation_id,
                                      session_key, pool)
        except ZcodeError as exc:
            _handle_upstream_error(account, exc, model, session_key, pool)
            if exc.status == 400:
                raise _http_error(400, "ZCode 上游拒绝请求（400）：%s"
                                  % (exc.message[:300] or exc.zcode_code))
            if exc.status == 429:
                last_error, last_429 = exc, exc
                last_429_detail = exc.detail
            else:
                last_error = _http_error(
                    exc.status, "ZCode 账号 %s：%s（已自动换号）"
                    % (account.uid[:8], exc.message[:200]))
            _log("account %s failed: HTTP %s code %s %s"
                 % (account.uid[:8], exc.status, exc.zcode_code,
                    exc.message[:120]), ctx)
            continue
        except Exception as exc:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            if net.looks_like_local_network(exc):
                _log("account %s: local network failure (%s), no penalty"
                     % (account.uid[:8], type(exc).__name__), ctx)
                last_error = exc
                continue
            if net.is_transient(exc):
                account.note_unknown_failure("connection: %s" % type(exc).__name__)
            else:
                account.note_unknown_failure(str(exc)[:120])
                account.note_error(str(exc)[:120], cooldown=60)
            last_error = exc
            _log("account %s connection error: %s"
                 % (account.uid[:8], type(exc).__name__), ctx)
            continue
        if session_key and pool:
            # 回退重试时 _fail 已解绑过会话亲和，成功后重新钉住这个号
            pool.affinity.bind(session_key, account.uid)
        account.note_success(model=model)
        return (stream,
                {"account": account.uid, "realm": REALM,
                 "account_obj": account})

    if last_error is not None:
        if last_429 is not None:
            from core import ratelimit
            exc = ratelimit.RateLimited(last_429, last_429_detail, wait=60)
            exc.account_uid = None
            raise exc
        if isinstance(last_error, urllib.error.HTTPError):
            raise last_error
        raise last_error
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or do not support this model" % REALM)


# --------------------------------------------------------------------- 额度
def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_ms(value):
    if value is None or value == "":
        return 0
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        try:
            number = float(text)
        except ValueError:
            return 0
        if number < 1e11:
            number *= 1000
        return int(number)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return 0


def _expiry_text(seconds):
    if not seconds:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))


def _packages(balances, plans):
    names = {}
    for plan in plans if isinstance(plans, list) else []:
        plan_id = str(plan.get("plan_id") or plan.get("planId") or "")
        if plan_id:
            names[plan_id] = str(plan.get("name") or plan_id)
    rows = []
    for index, balance in enumerate(balances if isinstance(balances, list) else []):
        if not isinstance(balance, dict):
            continue
        total = _num(balance.get("total_units"))
        used = _num(balance.get("used_units"))
        raw = balance.get("remaining_units")
        if raw is None:
            raw = balance.get("available_units")
        remaining = _num(raw) if raw is not None else (
            total - used if total or used else 0.0)
        plan_id = str(balance.get("plan_id") or balance.get("planId")
                      or balance.get("entitlement_id") or "")
        expires = _to_ms(balance.get("expires_at") or balance.get("expiresAt")) // 1000
        rows.append({
            "package_code": (plan_id or "pack%d" % index)[:128],
            "name": str(balance.get("show_name") or balance.get("name")
                        or names.get(plan_id) or plan_id or "套餐额度")[:128],
            "remain": round(max(0.0, remaining), 2),
            "size": round(total, 2) if total > 0 else 0,
            "is_expired": bool(expires and expires <= time.time()),
            "no_expiry": not expires,
            "expire_time": _expiry_text(expires),
        })
    return rows


def _balance_once(account, headers, proxy, qs):
    """单次 balance 探测（plans 缺失时拉 billing/current 兜底补套餐名）。

    返回 {"ok": True, ...}（balances 与 plans 全空时带 empty 标记、credits 为 0），
    或带标记的失败 dict：authError/retryable（401/403/429/空数据，可退避重试）、
    无标记（HTTP 非 200、业务码非 0，重试无效应直接失败）。
    """
    status, data = _json_request(
        "GET", "%s/billing/balance?%s" % (CFG["billingBase"].rstrip("/"), qs),
        headers=headers, timeout=25, proxy=proxy)
    if status in (401, 403):
        return {"authError": True, "retryable": True,
                "message": "ZCode 凭证失效（HTTP %s）" % status}
    if status == 429:
        return {"error": "额度接口限流（429），已退避重试", "retryable": True}
    payload = data.get("data") if isinstance(data, dict) and isinstance(
        data.get("data"), dict) else data
    if status != 200 or not isinstance(payload, dict):
        return {"error": "额度查询失败：HTTP %s %s"
                % (status, _error_message(data)[:100])}
    biz_code = payload.get("code")
    if biz_code not in (None, 0, 200, "0", "200"):
        return {"error": "额度查询失败：code %s %s"
                % (biz_code, _error_message(payload)[:100])}
    balances = payload.get("balances") if isinstance(payload.get("balances"), list) else []
    plans = payload.get("plans") if isinstance(payload.get("plans"), list) else []
    if not plans:
        status2, current = _json_request(
            "GET", "%s/billing/current?%s" % (CFG["billingBase"].rstrip("/"), qs),
            headers=headers, timeout=20, proxy=proxy)
        current = current.get("data") if isinstance(current, dict) and isinstance(
            current.get("data"), dict) else current
        if status2 == 200 and isinstance(current, dict) and isinstance(
                current.get("plans"), list):
            plans = current["plans"]
    if not balances and not plans:
        return {"ok": True, "empty": True, "credits": 0.0, "expiresAt": 0,
                "packages": [], "raw": {"balances": 0, "plans": 0}}
    credits = sum(_num(balance.get("remaining_units")
                       if balance.get("remaining_units") is not None
                       else balance.get("available_units"))
                  for balance in balances if isinstance(balance, dict))
    expiries = [_to_ms(balance.get("expires_at") or balance.get("expiresAt")) // 1000
                for balance in balances if isinstance(balance, dict)]
    expiries = [value for value in expiries if value > time.time()]
    return {
        "ok": True,
        "credits": round(max(0.0, credits), 2),
        "expiresAt": min(expiries) if expiries else 0,
        "packages": _packages(balances, plans),
        "raw": {"balances": len(balances), "plans": len(plans)},
    }


def _credits_by_jwt(account):
    jwt = _jwt(account)
    if not jwt:
        return {"authError": True, "message": "该账号无 zcodejwt 凭据"}
    headers = _ctl_headers(jwt, account, None)
    proxy = getattr(account, "proxy", "")
    qs = _qs()
    last = None
    # 退避阶梯与上游同口径 [0, 0.5, 1.5, 4]s：401/403（含新账号激活延迟误报）、
    # 429、空数据都退避重试；HTTP 非 200 / 业务码非 0 不重试直接失败。
    # 末次 Attempt 仍空数据时按上游口径以 0 额度成功返回，不当错误罚号。
    for index, delay in enumerate((0.0, 0.5, 1.5, 4.0)):
        if delay:
            time.sleep(delay)
        parsed = _balance_once(account, headers, proxy, qs)
        if parsed.get("ok"):
            if not parsed.get("empty") or index >= 3:
                return parsed
            last = {"error": "额度数据为空（新账号可能激活延迟）"}
            continue
        last = parsed
        if not parsed.get("retryable"):
            break
    # 终判补试（上游口径）：全程 401/403 时再等 1.5s 用同一 jwt 试一次——
    # 新账号服务端激活延迟会全程吃 401，补试成功即采用结果；仍 401/403
    # 才终判凭证失效，避免把延迟激活的新号误停用
    if last and last.get("authError"):
        time.sleep(1.5)
        retry = _balance_once(account, headers, proxy, qs)
        if retry.get("ok"):
            return retry
        if retry.get("authError"):
            return {"authError": True,
                    "message": retry.get("message") or "ZCode 凭证失效"}
        if retry.get("error"):
            last = retry
    if last and last.get("authError"):
        return {"authError": True,
                "message": last.get("message") or "ZCode 凭证失效"}
    return last or {"error": "额度查询失败"}


def _credits_by_api_key(account):
    key = _plan_key(account)
    if not key:
        return {"authError": True, "message": "该账号无 coding-plan 凭据"}
    status, data = _json_request(
        "GET", CFG["monitorQuotaUrl"],
        headers={"content-type": "application/json",
                 "accept": "application/json",
                 "authorization": "Bearer " + key},
        timeout=25, proxy=getattr(account, "proxy", ""))
    if status in (401, 403):
        return {"authError": True, "message": "coding-plan 凭据失效（HTTP %s）" % status}
    payload = data.get("data") if isinstance(data, dict) and isinstance(
        data.get("data"), dict) else data
    if status != 200 or not isinstance(payload, dict):
        return {"error": "额度查询失败：HTTP %s %s"
                % (status, _error_message(data)[:100])}
    code = data.get("code") if isinstance(data, dict) else None
    if code in (None, 0, 200, "0", "200"):
        code = payload.get("code")
    if code not in (None, 0, 200, "0", "200"):
        return {"error": "额度查询失败：code %s %s"
                % (code, _error_message(payload)[:100])}
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    credits = sum(_num(limit.get("remaining")) for limit in limits
                  if isinstance(limit, dict))
    expiries = [_to_ms(limit.get("nextResetTime")) // 1000 for limit in limits
                if isinstance(limit, dict)]
    expiries = [value for value in expiries if value > time.time()]
    rows = []
    for index, limit in enumerate(limits):
        if not isinstance(limit, dict):
            continue
        expires = _to_ms(limit.get("nextResetTime")) // 1000
        rows.append({
            "package_code": "limit%d" % index,
            "name": str(limit.get("level") or payload.get("level") or "套餐额度")[:128],
            "remain": round(max(0.0, _num(limit.get("remaining"))), 2),
            "size": round(max(0.0, _num(limit.get("total"))), 2),
            "is_expired": bool(expires and expires <= time.time()),
            "no_expiry": not expires,
            "expire_time": _expiry_text(expires),
        })
    return {"ok": True, "credits": round(max(0.0, credits), 2),
            "expiresAt": min(expiries) if expiries else 0,
            "packages": rows, "raw": {"level": payload.get("level") or ""}}


def get_credits(account, force=False):
    cache_key = (str(getattr(account, "realm", "") or ""), str(account.uid or ""))
    now = time.time()
    with _CREDITS_LOCK:
        hit = _CREDITS_CACHE.get(cache_key)
        if hit and not force and now - hit[0] <= CREDITS_TTL:
            result = dict(hit[1])
            result["cached"] = True
            return result
    jwt = _jwt(account)
    plan = _plan_key(account)
    if jwt and plan:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fj = pool.submit(_credits_by_jwt, account)
            fp = pool.submit(_credits_by_api_key, account)
            rj = fj.result()
            rp = fp.result()
        if rp.get("ok") and not rp.get("authError") and not rp.get("error"):
            jwt_ok = rj.get("ok") and not rj.get("authError") and not rj.get("error")
            result = {
                "ok": True,
                "credits": round(_num(rp.get("credits"))
                                 + (_num(rj.get("credits")) if jwt_ok else 0), 2),
                "expiresAt": min([value for value in
                                  (rp.get("expiresAt"),
                                   rj.get("expiresAt") if jwt_ok else 0)
                                  if value]) or 0,
                "packages": (rp.get("packages") or [])
                + ((rj.get("packages") or []) if jwt_ok else []),
                "raw": {"jwt": rj.get("raw"), "apiKey": rp.get("raw")},
            }
        elif rj.get("ok") and not rj.get("authError") and not rj.get("error"):
            result = rj
        elif rp.get("authError") and rj.get("authError"):
            return {"ok": False, "authError": True,
                    "error": "ZCode 凭证失效（JWT 与 API Key 均失效）"}
        else:
            return {"ok": False, "error": rp.get("error") or rj.get("error")
                    or "额度查询失败"}
    elif jwt:
        result = _credits_by_jwt(account)
    elif plan:
        result = _credits_by_api_key(account)
    else:
        return {"ok": False, "authError": True, "error": "该账号没有任何可用凭据"}
    if result.get("ok"):
        with _CREDITS_LOCK:
            _CREDITS_CACHE[cache_key] = (now, dict(result))
    return result


def credits_for_account(account, force=False):
    result = get_credits(account, force=force)
    if not result.get("ok"):
        return result
    account.credits = {
        "remain": float(result.get("credits") or 0),
        "unlimited": False,
        "size": None,
        "packages": result.get("packages") or [],
        "expiresAt": result.get("expiresAt") or 0,
        "updated_at": time.time(),
        "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save(account)
    return {"ok": True, "credits": account.credits}


# ------------------------------------------------------------------- 连通性
def probe_account(account, timeout=20):
    jwt = _jwt(account)
    plan = _plan_key(account)
    if not jwt and not plan:
        return {"ok": False, "message": "该账号没有可用 ZCode 凭据"}
    model = STATIC_MODELS[0]["id"]
    body = {
        "model": model,
        "messages": [{"role": "system", "content": "You are a helpful assistant."},
                     {"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": True,
    }
    targets = ["coding-plan"] if plan else ["start-plan"]
    if plan and jwt:
        targets.append("start-plan")
    last = ""
    for target in targets:
        try:
            url, headers, payload = _build_request(
                account, model, body, target, "", None)
            request = urllib.request.Request(
                url, data=_body_bytes(payload), method="POST", headers=headers)
            request.wb_exact_headers = list(headers.items())
            started = time.time()
            with net.urlopen(request, timeout=timeout,
                             proxy=getattr(account, "proxy", "")) as resp:
                raw = resp.read(256)
            if not raw:
                last = "上游未返回任何数据"
                continue
            elapsed = int((time.time() - started) * 1000)
            return {"ok": True, "model": model, "latencyMs": elapsed,
                    "message": "ZCode 账号连通正常（%s，%d ms）" % (model, elapsed)}
        except ZcodeError as exc:
            last = "HTTP %s：%s" % (exc.status, exc.message[:150])
        except urllib.error.HTTPError as exc:
            try:
                text = exc.read(400).decode("utf-8", "replace")
            except Exception:
                text = ""
            mapped = _map_error(exc.code, None, text)
            last = "HTTP %s：%s" % (mapped.status, mapped.message[:150])
        except Exception as exc:
            last = "请求异常: %s" % exc
    return {"ok": False, "message": "ZCode 连接探测失败：%s" % (last or "无可用线路")}


# --------------------------------------------------------------- 本机导入
def _candidate(record, path, file_label, valid=True, error="", encrypted=False):
    usable = bool(valid and (record.get("uid") or record.get("token")
                             or record.get("refreshToken")))
    return {
        "path": path,
        "file": file_label,
        "realm": REALM,
        "realmLabel": SHORT,
        "domain": DOMAIN,
        "uid": str(record.get("uid") or ""),
        "nickname": str(record.get("name") or "") or "ZCode 账号",
        "encrypted": bool(encrypted),
        "valid": bool(valid and usable),
        "usable": bool(usable),
        "source": "scan",
        "error": error,
    }


def _live_record(live, ctx):
    return zcode_local.account_record(live, {}, ctx)


def _profile_record(profile, ctx):
    cred = profile.get("cred") or {}
    api_keys = profile.get("providerApiKeys") or {}
    jwt_fallback = (api_keys.get("builtin:zai-start-plan")
                    or api_keys.get("builtin:bigmodel-start-plan") or "")
    record = zcode_local.account_record(cred, {
        "profileApiKeys": api_keys,
        "jwtFallback": jwt_fallback,
        "uid": profile.get("uid") or "",
        "name": profile.get("name") or "",
        "email": profile.get("email") or "",
        "avatar": profile.get("avatar") or "",
        "provider": profile.get("family") or "",
    }, ctx)
    record["profileFile"] = profile.get("file") or profile.get("profileId") or ""
    return record


def scan_desktop(ctx):
    out = []
    seen = set()
    live = zcode_local.read_live()
    if live is not None:
        if live.get("jwt") or live.get("codingPlanKeys"):
            record = _live_record(live, ctx)
            if record.get("uid") or record.get("token") or record.get("refreshToken"):
                out.append(_candidate(record, "credentials.json",
                                      "credentials.json（当前登录）"))
                if record.get("uid"):
                    seen.add(record["uid"])
        elif live.get("raw"):
            out.append(_candidate({}, "credentials.json", "credentials.json",
                                  valid=False, encrypted=True,
                                  error="登录文件里的凭据解不开（官方可能更换了密钥派生式）"))
    for profile in zcode_local.read_profiles():
        if not profile.get("cred"):
            continue
        record = _profile_record(profile, ctx)
        if not (record.get("uid") or record.get("token") or record.get("refreshToken")):
            continue
        if record.get("uid") and record["uid"] in seen:
            continue
        if record.get("uid"):
            seen.add(record["uid"])
        file_name = profile.get("file") or profile.get("profileId") or "profile"
        out.append(_candidate(record, "account-profiles/" + file_name,
                              "account-profiles/" + file_name))
    return out


def _account_from_record(ctx, record, source):
    uid = str(record.get("uid") or "")
    token = str(record.get("token") or "")
    key = str(record.get("refreshToken") or "")
    if not uid:
        seed = token or key
        uid = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16] if seed else ""
    if not uid or not (token or key):
        raise RuntimeError("ZCode 凭据缺少账号标识或 token，无法导入")
    pool = getattr(ctx, "pool", None)
    existing = None
    if pool is not None:
        existing = next((account for account in pool.accounts
                         if account.uid == uid and account.realm == REALM), None)
        other = pool.get(uid)
        if existing is None and other is not None and other.realm != REALM:
            raise RuntimeError("账号 uid 与已有渠道账号冲突（%s），无法导入" % other.realm)
    meta = dict(getattr(existing, "meta", None) or {}) if existing is not None else {}
    meta["provider"] = str(record.get("provider") or meta.get("provider") or "zai")
    if record.get("email"):
        meta["email"] = str(record["email"])
    if record.get("avatar"):
        meta["avatar"] = str(record["avatar"])
    meta["deviceMid"] = str(meta.get("deviceMid") or record.get("deviceMid") or "")
    if not meta["deviceMid"]:
        meta["deviceMid"] = zcode_local.derived_device_mid(uid)
    if existing is not None:
        meta["codingPlanResolved"] = bool(key or meta.get("codingPlanResolved"))
    else:
        meta["codingPlanResolved"] = bool(key)
    plan_only = bool(not token and key)
    if existing is not None:
        if token:
            existing.access_token = token
            meta.pop("credentialMode", None)
        elif not existing.access_token:
            existing.access_token = key
            meta["credentialMode"] = "coding-plan"
        if key:
            existing.refresh_token = key
        existing.meta = meta
        existing.enabled = True
        existing.token_expired = False
        existing.clear_error()
        _save(existing)
        return existing
    account = accounts_mod.Account({
        "uid": uid,
        "nickname": str(record.get("name") or uid[:8]),
        "realm": REALM,
        "domain": DOMAIN,
        "platform": "CLI",
        "accessToken": token or key,
        "refreshToken": key,
        "expiresAt": 0,
        "source": source,
        "enabled": True,
        "meta": meta,
    })
    if plan_only:
        account.meta["credentialMode"] = "coding-plan"
        account.access_token = key
    if pool is not None:
        pool.add(account)
    else:
        account.save(ctx.accounts_dir)
    return account


def import_from_desktop(ctx, payload):
    payload = payload or {}
    selected = str(payload.get("path") or "")
    live = zcode_local.read_live()
    profiles = zcode_local.read_profiles()
    imported = []
    if selected.startswith("account-profiles/"):
        wanted = selected[len("account-profiles/"):]
        for profile in profiles:
            names = {str(profile.get("file") or ""),
                     str(profile.get("profileId") or "")}
            if wanted not in names:
                continue
            imported.append(_account_from_record(
                ctx, _profile_record(profile, ctx), "desktop-app"))
            break
    elif selected.startswith("credentials.json"):
        if live is not None:
            imported.append(_account_from_record(
                ctx, _live_record(live, ctx), "desktop-app"))
    else:
        if live is not None and (live.get("jwt") or live.get("codingPlanKeys")):
            imported.append(_account_from_record(
                ctx, _live_record(live, ctx), "desktop-app"))
        for profile in profiles:
            if not profile.get("cred"):
                continue
            try:
                imported.append(_account_from_record(
                    ctx, _profile_record(profile, ctx), "desktop-app"))
            except Exception:
                continue
    if not imported:
        raise RuntimeError("本机没有可导入的 ZCode 凭据（请确认客户端已登录一次）")
    return imported[0]


# ------------------------------------------------------------------- OAuth
def _interstitial():
    query = urllib.parse.urlencode({
        "redirect": "zcode://oauth/callback",
        "app_version": CFG["appVersion"],
    })
    return CFG["refererOrigin"].rstrip("/") + "/app/oauth/login?" + query


def _with_redirect(url, provider):
    try:
        parts = urllib.parse.urlsplit(url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        query["redirect_uri" if provider == "zai" else "redirect"] = _interstitial()
        return urllib.parse.urlunsplit((
            parts.scheme, parts.netloc, parts.path,
            urllib.parse.urlencode(query), parts.fragment))
    except Exception:
        return url


def _exit_proxy(ctx, realm):
    """当前出口生效中的代理槽 URL（出口级代理，与账号池解析同口径）。

    OAuth 登录时还没有账号，拿不到 account.proxy；而直连被 TLS 劫持时
    （证书链不被信任）整条登录链都会挂。登录/轮询/兑换统一按出口槽取
    代理——没配槽就返回空串走直连（维持原行为）。
    """
    try:
        from infra import settings
        for entry in settings.proxy_slots(ctx.accounts_dir, realm):
            if entry.get("realm") and entry.get("enabled") is not False:
                return str(entry.get("url") or "")
    except Exception:
        pass
    return ""


def _save_oauth_account(ctx, provider, jwt, access_token, refresh_token, user):
    user = user if isinstance(user, dict) else {}
    uid = str(user.get("user_id") or user.get("uid") or "") or zcode_local.uid_from_jwt(jwt)
    if not uid:
        raise RuntimeError("登录成功但取不到账号 uid，请改用「从本机软件导入」")
    email = str(user.get("email") or "")
    name = str(user.get("name") or user.get("nickname") or email
               or ("ZCode %s" % uid[:6]))
    record = {
        "uid": uid,
        "name": name,
        "email": email,
        "avatar": str(user.get("avatar") or user.get("avatar_url") or ""),
        "provider": provider,
        "deviceMid": str(uuid.uuid4()),
        "token": jwt,
        "refreshToken": "",
    }
    account = _account_from_record(ctx, record, "oauth")
    # 入池时池子不会重解析代理槽（要等下次 slot 保存/重启）：新账号若正处于
    # 直连被劫持的网络，紧随的激活链（api.z.ai）会证书报错，按出口槽补一次
    account.proxy = _exit_proxy(ctx, account.realm)
    meta = dict(_meta(account))
    meta.setdefault("codingPlanResolved", False)
    account.meta = meta
    if access_token:
        _activate_account(ctx, account, provider, access_token)
    return account


def _unwrap_response(status, data):
    if isinstance(data, list):
        if status < 200 or status >= 300:
            raise RuntimeError("业务接口 HTTP %s" % status)
        return data
    body = data if isinstance(data, dict) else {}
    code = body.get("code", body.get("status"))
    if status < 200 or status >= 300 or code not in (None, 0, 200, "0", "200"):
        raise RuntimeError(str(body.get("msg") or body.get("message")
                               or "业务接口 HTTP %s" % status))
    return body.get("data", body)


def _run_activation(ctx, account, provider, access_token):
    """登录后激活链：business login → 等 billing plan → 解析 coding-plan key。"""
    def run():
        try:
            biz_token = ""
            for delay in (0, 3, 10):
                if delay:
                    time.sleep(delay)
                status, data = _json_request(
                    "POST", CFG["businessLoginUrl"],
                    headers={"content-type": "application/json",
                             "accept": "application/json"},
                    body=_body_bytes({"token": access_token}), timeout=20)
                body = data if isinstance(data, dict) else {}
                inner = body.get("data") if isinstance(body.get("data"), dict) else {}
                biz_token = str(body.get("access_token") or body.get("accessToken")
                                or inner.get("access_token") or "")
                if status == 200 and (biz_token or body.get("code") in (0, 200)
                                      or body.get("success") is True):
                    break
            qs = _qs()
            for delay in (1, 3, 6, 15, 30, 60):
                time.sleep(delay)
                status, current = _json_request(
                    "GET", "%s/billing/current?%s" % (
                        CFG["billingBase"].rstrip("/"), qs),
                    headers=_ctl_headers(_jwt(account), account, ctx),
                    timeout=20)
                payload = current.get("data") if isinstance(current, dict) and isinstance(
                    current.get("data"), dict) else current
                if status == 200 and isinstance(payload, dict) and payload.get("plans"):
                    break
            if provider == "zai" and not biz_token:
                raise RuntimeError("business login 未取到 bizToken")
            biz_base = (CFG["bigmodelBizBase"] if provider == "bigmodel"
                        else CFG["zaiBizBase"]).rstrip("/")
            authorization = access_token if provider == "bigmodel" else "Bearer " + biz_token
            headers = {"content-type": "application/json", "authorization": authorization}
            status, info = _json_request(
                "GET", biz_base + "/api/biz/customer/getCustomerInfo",
                headers=headers, timeout=20)
            info = _unwrap_response(status, info)
            organizations = info.get("organizations") or info.get("orgs") or []
            if not organizations:
                raise RuntimeError("getCustomerInfo 返回无机构")
            org = next((item for item in organizations if "默认机构" in str(
                item.get("organizationName") or item.get("name") or "")),
                organizations[0])
            org_id = str(org.get("organizationId") or org.get("id")
                         or org.get("orgId") or "")
            projects = org.get("projects") if isinstance(org.get("projects"), list) else []
            project = next((item for item in projects if "默认项目" in str(
                item.get("projectName") or item.get("name") or "")),
                projects[0] if projects else {})
            project_id = str(project.get("projectId") or project.get("id") or "")
            if not org_id or not project_id:
                raise RuntimeError("默认机构/默认项目缺失")
            keys_url = "%s/api/biz/v1/organization/%s/projects/%s/api_keys" % (
                biz_base, org_id, project_id)
            api_key = ""
            try:
                status, listing = _json_request("GET", keys_url, headers=headers,
                                                timeout=20)
                listing = _unwrap_response(status, listing)
                if isinstance(listing, list):
                    found = next((item for item in listing
                                  if item.get("name") == "zcode-api-key"
                                  and item.get("apiKey")), None)
                    api_key = str((found or {}).get("apiKey") or "")
            except Exception:
                api_key = ""
            if not api_key:
                status, created = _json_request(
                    "POST", keys_url, headers=headers,
                    body=_body_bytes({"name": "zcode-api-key"}), timeout=20)
                created = _unwrap_response(status, created)
                api_key = str(created.get("apiKey") or "")
                if not api_key:
                    raise RuntimeError("API key 创建返回缺 apiKey 字段")
            status, copied = _json_request(
                "GET", keys_url + "/copy/" + urllib.parse.quote(api_key, safe=""),
                headers=headers, timeout=20)
            copied = _unwrap_response(status, copied)
            secret = str(copied.get("secretKey") or copied.get("secret_key") or "")
            if not secret:
                raise RuntimeError("API key copy 返回缺 secretKey")
            if ctx.pool is not None and ctx.pool.get(account.uid) is not account:
                return
            account.refresh_token = "%s.%s" % (api_key, secret)
            meta = dict(_meta(account))
            meta["codingPlanResolved"] = True
            meta.pop("codingPlanError", None)
            account.meta = meta
            _save(account)
            _log("account %s coding-plan key resolved" % account.uid[:8], ctx)
        except Exception as exc:
            try:
                meta = dict(_meta(account))
                meta["codingPlanResolved"] = False
                meta["codingPlanError"] = str(exc)[:200]
                account.meta = meta
                _save(account)
            except Exception:
                pass
            _log("account %s activation failed: %s" % (account.uid[:8], exc), ctx)

    return run()


def _activate_account(ctx, account, provider, access_token):
    thread = threading.Thread(target=_run_activation,
                              args=(ctx, account, provider, access_token),
                              daemon=True, name="zcode-activate")
    thread.start()
    return thread


class ZcodeAdapter(registry.ChannelAdapter):
    def __init__(self):
        self.id = REALM
        self.label = LABEL
        self.realms = (REALM,)
        self.route_prefixes = (REALM,)
        self.capabilities = frozenset({
            registry.CAP_CHAT, registry.CAP_RESPONSES, registry.CAP_MODELS,
            registry.CAP_ACCOUNTS, registry.CAP_PROXY_SLOT,
            registry.CAP_DESKTOP_IMPORT, registry.CAP_PASTE_TOKEN,
        })
        self._ctx = None
        self._login = {}
        self._login_lock = threading.Lock()

    def register(self, ctx):
        self._ctx = ctx
        accounts_mod.register_realm_config(REALM, {
            "name": self.label,
            "domain": DOMAIN,
            "has_daily_chat": False,
            "refresh_fn": _refresh_account,
            "credits_fn": credits_for_account,
            "probe_fn": probe_account,
        })

    # ------------------------------------------------------------ 登录
    def start_login(self, ctx, realm, platform="CLI"):
        if realm != REALM:
            return None
        provider = str(CFG["oauthProvider"] or "zai")
        poll_token = os.urandom(32).hex()
        # 登录链按出口槽走代理：直连被劫持时 init 就会证书报错
        exit_proxy = _exit_proxy(ctx, realm)
        status, data = _json_request(
            "POST", CFG["oauthInitUrl"],
            headers=_ctl_headers(poll_token, None, ctx, with_local_mid=True),
            body=_body_bytes({"provider": provider}), timeout=25,
            proxy=exit_proxy)
        payload = data.get("data") if isinstance(data, dict) and isinstance(
            data.get("data"), dict) else data
        flow_id = str((payload or {}).get("flow_id") or "")
        authorize = str((payload or {}).get("authorize_url") or "")
        if status != 200 or not flow_id or not authorize:
            reason = _error_message(data) or ("HTTP %s" % status)
            message = "ZCode 登录初始化失败：%s" % reason
            if "WB_CA_BUNDLE" in reason:
                # 证书链不被信任（直连被解密/劫持）：除私有 CA 外，出口级
                # 代理槽可让该出口全部出站走代理绕开，登录链同样生效
                message += "（或给 ZCode 出口配置代理槽后重试）"
            elif status == 0:
                message += "（网络不通：检查本机到 zcode.z.ai 的连接或代理出口）"
            # 落日志：前端会把 message 弹出来，但用户可能直接关掉，日志留痕
            # 便于回溯（面板「日志与流水」可见）
            _log(message, ctx)
            return {"ok": False, "message": message}
        try:
            interval = max(1.0, float((payload or {}).get("poll_interval_sec") or 1.5))
        except (TypeError, ValueError):
            interval = 1.5
        try:
            expires = float((payload or {}).get("expires_at") or 0)
        except (TypeError, ValueError):
            expires = 0
        deadline = time.time() + LOGIN_TIMEOUT
        if expires:
            deadline = min(deadline, expires)
        session = {
            "state": flow_id, "poll_token": poll_token, "provider": provider,
            "interval": interval, "deadline": deadline, "status": "waiting",
            "message": "", "started": time.time(),
            # 登录会话绑定发起时的出口代理：轮询/兑换与 init 同路，避免
            # 登录中途改槽把 flow 拆到两条网络上
            "proxy": exit_proxy,
        }
        with self._login_lock:
            self._login[flow_id] = session
            now = time.time()
            for key in list(self._login):
                if now - self._login[key].get("started", 0) > LOGIN_TIMEOUT + 120:
                    self._login.pop(key, None)
        return {
            "ok": True,
            "authUrl": _with_redirect(authorize, provider),
            "state": flow_id,
            "realm": REALM,
            "paste": True,
            "hint": "在浏览器完成 ZCode 登录后会自动入池（3 分钟内有效）；"
                    "若浏览器停在等待页，可把 zcode:// 回调整段粘贴回来",
        }

    def poll_login(self, ctx, state):
        session = self._login.get(state)
        if session is None:
            return None
        if session.get("status") != "waiting":
            return {"status": session.get("status"), "message": session.get("message") or ""}
        if time.time() > session.get("deadline", 0):
            session["status"] = "expired"
            session["message"] = "登录超时（3 分钟），请重新发起"
            return {"status": "expired", "message": session["message"]}
        status, data = _json_request(
            "GET", "%s/%s" % (CFG["oauthPollBase"].rstrip("/"),
                              urllib.parse.quote(state, safe="")),
            headers=_ctl_headers(session.get("poll_token") or "", None, ctx,
                                 with_local_mid=True),
            timeout=20, proxy=session.get("proxy") or "")
        if 400 <= status < 500 and status not in (408, 429):
            session["status"] = "error"
            session["message"] = "登录轮询失败（HTTP %s）" % status
            return {"status": "error", "message": session["message"]}
        if status == 200 and isinstance(data, dict):
            try:
                code = int(data.get("code") or 0)
            except (TypeError, ValueError):
                code = 0
            if code != 0:
                session["status"] = "error"
                session["message"] = "登录轮询失败（code %s）%s" % (
                    code, data.get("message") or data.get("msg") or "")
                return {"status": "error", "message": session["message"]}
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            state_name = str(payload.get("status") or "pending")
            if state_name == "ready":
                provider = session.get("provider") or "zai"
                provider_data = payload.get(provider) if isinstance(
                    payload.get(provider), dict) else {}
                jwt = str(payload.get("token") or "")
                access_token = str(provider_data.get("access_token")
                                   or payload.get("access_token") or "")
                if not jwt:
                    session["status"] = "error"
                    session["message"] = "登录返回缺少 zcodejwt"
                    return {"status": "error", "message": session["message"]}
                try:
                    account = _save_oauth_account(
                        ctx, provider, jwt, access_token,
                        str(provider_data.get("refresh_token") or ""),
                        payload.get("user") or {})
                except Exception as exc:
                    session["status"] = "error"
                    session["message"] = str(exc)[:200]
                    return {"status": "error", "message": session["message"]}
                session["status"] = "ok"
                session["message"] = "ZCode 账号已登录并入池（%s）" % account.nickname
                return {"status": "ok", "message": session["message"],
                        "uid": account.uid}
            if state_name == "failed":
                session["status"] = "error"
                session["message"] = "授权失败，请重新发起登录"
                return {"status": "error", "message": session["message"]}
        return {"status": "pending", "message": "等待浏览器完成授权…"}

    def submit_login(self, ctx, state, raw_callback):
        # 粘贴回调按 state 路由：不是本渠道发起的会话必须交还调用方
        with self._login_lock:
            if state not in self._login:
                return None
        text = str(raw_callback or "").strip()
        match = re.search(r"[?&]code=([^&#]+)", text)
        if not match:
            return {"ok": False,
                    "message": "无法从粘贴内容提取授权码：请复制形如 "
                               "zcode://zai-auth/callback?code=… 的整段链接"}
        state_value = (re.search(r"[?&]state=([^&#]+)", text) or [None, ""])[1]
        session = self._login.get(state)
        provider = (session or {}).get("provider") or str(CFG["oauthProvider"] or "zai")
        status, data = _json_request(
            "POST", CFG["oauthTokenUrl"],
            headers=_ctl_headers("", None, ctx, with_local_mid=True),
            body=_body_bytes({
                "provider": provider,
                "code": urllib.parse.unquote(match.group(1)),
                "redirect_uri": "zcode://zai-auth/callback",
                "state": urllib.parse.unquote(state_value or ""),
            }), timeout=25, proxy=(session or {}).get("proxy") or "")
        payload = data.get("data") if isinstance(data, dict) and isinstance(
            data.get("data"), dict) else data
        payload = payload if isinstance(payload, dict) else {}
        jwt = str(payload.get("token") or payload.get("zcode_token") or "")
        provider_data = payload.get(provider) if isinstance(
            payload.get(provider), dict) else payload
        access_token = str(provider_data.get("access_token")
                           or provider_data.get("accessToken") or "")
        if status != 200 or not jwt:
            return {"ok": False, "message": _error_message(data)
                    or "授权码兑换失败 HTTP %s" % status}
        try:
            account = _save_oauth_account(
                ctx, provider, jwt, access_token,
                str(provider_data.get("refresh_token")
                    or provider_data.get("refreshToken") or ""),
                payload.get("user") or {})
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:200]}
        if session is not None:
            session["status"] = "ok"
            session["message"] = "ZCode 账号已登录并入池（%s）" % account.nickname
        return {"ok": True, "uid": account.uid,
                "message": "ZCode 账号已登录并入池（%s）" % account.nickname}

    def cancel_login(self, ctx, state):
        with self._login_lock:
            if state not in self._login:
                return None
            self._login.pop(state, None)
        return {"ok": True}

    # ------------------------------------------------------------ 账号 / 导入
    def scan_desktop(self, ctx):
        return scan_desktop(ctx)

    def import_desktop(self, ctx, candidate):
        return import_from_desktop(ctx, candidate)

    # ------------------------------------------------------------ 代理链路
    def open_stream(self, ctx, payload, session_key=None, realm=None):
        return open_stream(ctx, self, payload, session_key=session_key,
                           realm=realm or REALM)

    def live_models(self, realm, force=False):
        return live_models(self._ctx, force=force)

    def panel_meta(self, ctx):
        pool = getattr(ctx, "pool", None)
        return {
            "id": REALM,
            "label": LABEL,
            "realms": [{
                "id": REALM,
                "label": SHORT,
                "badge": BADGE,
                "domain": DOMAIN,
                "accounts": pool.count_ready(realm=REALM) if pool else 0,
                "capabilities": sorted(self.capabilities),
                "desktop_import": True,
            }],
            "capabilities": sorted(self.capabilities),
            "frontend": REALM,
            "enabled": True,
        }


def _refresh_account(account):
    """zcode 无续期端点：凭据长期有效，只判断是否还有可用凭据。"""
    if _jwt(account) or _plan_key(account):
        return True
    account.token_expired = True
    account.last_error = ("ZCode 凭据长期有效（无自动刷新端点）；失效时请重新 OAuth "
                          "登录或从本机软件导入")
    return False


def install(ctx):
    registry.register(ZcodeAdapter(), ctx)
