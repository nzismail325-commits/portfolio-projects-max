# -*- coding: utf-8 -*-
"""integrations/qoder.py —— Qoder 反代渠道（国内版 / 国际版）

协议事实来自 AgentHub v1.77.0 的 qoder 适配器（见 qoder_bridge/NOTICE.md）：
- 上行：POST {gateway}/algo/api/v2/service/pro/sse/agent_chat_generation，
  每请求由客户端 wasm 签名并做 Encode=1 编码（本模块经 signatures 桥完成）；
- 下行：SSE 信封 {statusCode, body}，body 是标准 OpenAI chat chunk，
  收尾帧 body="[DONE]"；
- 额度：GET {quotaBase}/api/v2/quota/usage；每日领取走 sash campaigns；
- 登录：PKCE 设备码轮询（浏览器授权，不占回环端口）；
- 本机导入：读客户端 auth.v1.dat（DPAPI + AES-256-GCM），machineId 随账号落库。

架构约束（AGENTS.md §3.3）：
- 核心不引用本模块；两个出口各注册一个适配器，共享同一份实现；
- 业务规则只在本文件与 qoder_signer 内；面板按注册表渲染。
"""
import base64
import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from auth import accounts as accounts_mod
from core import net
from core import upstream_body
from integrations import qoder_signer
from integrations import registry

# ---------------------------------------------------------------------------
# 渠道常量
# ---------------------------------------------------------------------------
INFER_PATH = "/algo/api/v2/service/pro/sse/agent_chat_generation"
QUOTA_PATH = "/api/v2/quota/usage"
REFRESH_PATH = "/api/v1/deviceToken/refresh"
USER_AGENT = "qoder/0.4.3"
# 活动接口与客户端同源：UA/版本跟随已安装客户端，避免版本漂移
CLIENT_USER_AGENT = "Qoder"
CLIENT_VERSION_FALLBACK = "0.4.8"
LOGIN_TIMEOUT = 180.0
RISK_CACHE_TTL = 600.0
MODEL_CACHE_TTL = 300.0
CREDITS_TTL = 60.0
REFRESH_SKEW = 24 * 3600
#: 登录身份同步失败后的重试间隔：Qoder 令牌是 opaque，userinfo 是唯一来源。
IDENTITY_SYNC_RETRY = 24 * 3600

#: CN 静态兜底（AgentHub 表 + 本机 0.4.8 目录实测多出的 fast）
STATIC_MODELS_CN = [
    {"id": "auto", "name": "Auto"},
    {"id": "fast", "name": "Fast"},
    {"id": "qmodel_38max", "name": "Qwen3.8-Max"},
    {"id": "qfmodel", "name": "Qwen3.8-Flash"},
    {"id": "qmodel_latest", "name": "Qwen3.7-Max"},
    {"id": "qmodel", "name": "Qwen3.7-Plus"},
    {"id": "q37fmodel", "name": "Qwen3.7-Flash"},
    {"id": "dmodel", "name": "DeepSeek-V4-Pro"},
    {"id": "dfmodel", "name": "DeepSeek-Flash"},
    {"id": "gmodel", "name": "GLM-5.3"},
    {"id": "gfmodel", "name": "GLM-5.3-Flash"},
    {"id": "gm51model", "name": "GLM-5.2"},
    {"id": "kmodel_latest", "name": "Kimi-K3"},
    {"id": "kmodel", "name": "Kimi-K2.8-Preview"},
    {"id": "mmodel", "name": "MiniMax-M2.7"},
]

PRODUCTS = {
    "qoder": {
        "label": "Qoder 国内版",
        "short": "Qoder CN",
        "badge": "Qoder CN",
        "domain": "qoder.com.cn",
        "gateway": "https://gateway.qoder.com.cn",
        "openApi": "https://openapi.qoder.com.cn",
        "quotaBase": "https://gateway.qoder.com.cn",
        "authBase": "https://qoder.cn",
        "clientId": "732aef47-9cf2-46a2-95fe-4cebb5d0d1fa",
        "probeModel": "auto",
        "staticModels": STATIC_MODELS_CN,
    },
    "qoder_intl": {
        "label": "Qoder 国际版",
        "short": "Qoder Intl",
        "badge": "Qoder Intl",
        "domain": "qoder.sh",
        "gateway": "https://api2.qoder.sh",
        "openApi": "https://openapi.qoder.sh",
        "quotaBase": "https://openapi.qoder.sh",
        "authBase": "https://qoder.com",
        "clientId": "732aef47-9cf2-46a2-95fe-4cebb5d0d1fa",
        "probeModel": "auto",
        "staticModels": [],
    },
}

_MODEL_CACHE = {}      # realm -> {"at": ts, "models": [(id, meta)]}
_MODEL_LOCKS = {}
_CREDITS_CACHE = {}    # (realm, uid) -> (at, result)
_CREDITS_LOCK = threading.Lock()
_RISK_CACHE = {}       # product -> (at, value)
_RISK_LOCK = threading.Lock()
_TOKEN_LOCKS = {}
_TOKEN_LOCKS_GUARD = threading.Lock()
_CLIENT_STATUS = {}    # product -> (at, {"runtimeInfo": path, "version": ver})


class _TokenError(RuntimeError):
    """账号凭证不可用（不是上游故障，不按连接错误冷却）。"""


def _product(realm):
    return realm if realm in PRODUCTS else "qoder"


def _log(msg, ctx=None):
    line = "qoder: %s" % msg
    fn = getattr(ctx, "log", None) if ctx is not None else None
    if callable(fn):
        try:
            fn(line)
            return
        except Exception:
            pass
    try:
        import sys
        sys.stderr.write("[wb-proxy-max] %s\n" % line)
    except Exception:
        pass


def _token_lock(account):
    key = (str(getattr(account, "realm", "") or ""), str(getattr(account, "uid", "") or ""))
    with _TOKEN_LOCKS_GUARD:
        lock = _TOKEN_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _TOKEN_LOCKS[key] = lock
        return lock


def _save(account):
    if account is None:
        return
    directory = getattr(account, "accounts_dir", "") or ""
    if directory:
        try:
            account.save(directory)
        except Exception:
            pass


def _epoch_seconds(value):
    """毫秒/秒/ISO 字符串 → epoch 秒；解析不出返回 0。"""
    if value is None or value == "":
        return 0
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        try:
            number = float(text)
        except ValueError:
            return 0
        if number > 1e11:
            number /= 1000.0
        if number < 1e9:
            return 0
        return int(number)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        return 0


def _json_request(method, url, headers=None, body=None, timeout=30, proxy=""):
    """返回 (status, parsed)。网络异常返回 (0, {"_error": ...})。"""
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=headers or {})
    if headers:
        req.wb_exact_headers = list(headers.items())
    try:
        with net.urlopen(req, timeout=timeout, proxy=proxy) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read(1000).decode("utf-8", "replace")
            try:
                return exc.code, json.loads(raw)
            except Exception:
                return exc.code, {"message": raw[:300]}
        except Exception:
            return exc.code, None
    except Exception as exc:
        return 0, {"_error": str(exc)[:200]}


def _error_text(data):
    if isinstance(data, dict):
        return str(data.get("message") or data.get("msg") or data.get("error")
                   or data.get("_error") or "").strip()
    return ""


def _error_code(data):
    if isinstance(data, dict):
        return data.get("code") or data.get("errorCode") or data.get("statusCode")
    return None


def parse_queue_advice(inner, message=""):
    """10605 排队正文里的建议等待时长（秒）；没有就返回空 dict，绝不猜值。

    正文常是多层嵌套的 JSON 字符串；顺着 message/body/data 钻几层再取。
    对齐 AgentHub v1.79.0（qoderAdapter.parseQueueAdvice）。
    """
    advice = {}
    current = inner
    text = str(message or "")
    for _ in range(5):
        node = current
        if node is None and text:
            try:
                node = json.loads(text)
            except Exception:
                break
        if not isinstance(node, dict):
            break
        raw = (node.get("retryAfterSeconds") or node.get("retry_after_seconds")
               or node.get("waitTime") or node.get("wait_time"))
        try:
            secs = float(raw)
        except (TypeError, ValueError):
            secs = 0
        if secs > 0 and not advice.get("retryAfterSecs"):
            advice["retryAfterSecs"] = secs
        if not advice.get("queueType") and isinstance(node.get("queueType"), str):
            advice["queueType"] = node["queueType"]
        nxt = node.get("message") or node.get("body") or node.get("data")
        if isinstance(nxt, str) and nxt.strip():
            text = nxt
            current = None
            continue
        if isinstance(nxt, dict):
            current = nxt
            continue
        break
    return advice


# ---------------------------------------------------------------------------
# 账号：machineId / 续期
# ---------------------------------------------------------------------------
def _machine_id(account):
    meta = getattr(account, "meta", None)
    mid = str((meta or {}).get("machineId") or "")
    if mid:
        return mid
    product = _product(getattr(account, "realm", ""))
    try:
        mid = qoder_signer.ensure_machine_id(product)
    except Exception:
        mid = ""
    if mid:
        if not isinstance(account.meta, dict):
            account.meta = {}
        account.meta["machineId"] = mid
        account.meta["product"] = product
        _save(account)
    return mid


def _refresh_account(account):
    """auth.accounts 注入的 refresh_fn：Qoder 设备令牌轮换。"""
    product = _product(account.realm)
    cfg = PRODUCTS[product]
    refresh_token = str(getattr(account, "refresh_token", "") or "")
    if not refresh_token:
        account.token_expired = True
        account.last_error = "没有 refreshToken，请重新登录"
        return False
    body = {"refresh_token": refresh_token}
    machine = _machine_id(account)
    if machine:
        body["machine_id"] = machine
    status, data = _json_request(
        "POST", cfg["openApi"] + REFRESH_PATH,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        body=json.dumps(body).encode("utf-8"), timeout=30,
        proxy=getattr(account, "proxy", ""))
    token = (data or {}).get("device_token") if isinstance(data, dict) else None
    if status == 200 and token:
        account.access_token = str(token)
        account.refresh_token = str((data or {}).get("refresh_token") or refresh_token)
        expires = _epoch_seconds((data or {}).get("expires_at"))
        if expires:
            account.expires_at = expires
        if not isinstance(account.meta, dict):
            account.meta = {}
        account.meta["product"] = product
        account.meta["refreshTokenExpiresAt"] = _epoch_seconds(
            (data or {}).get("refresh_token_expires_at"))
        account.token_expired = False
        account.last_error = ""
        account.cooldown_until = 0
        _save(account)
        return True
    if status in (400, 401, 403):
        account.token_expired = True
        account.last_error = "Qoder 登录已过期（HTTP %s），请重新登录" % status
    else:
        account.last_error = "Qoder 续期失败（HTTP %s）：%s" % (
            status, _error_text(data)[:120])
    return False


def _ensure_token(account, force=False):
    """返回 (token, error)。Qoder 的 dt-/drt- 不是 JWT，到期只能看落库字段。"""
    lock = _token_lock(account)
    with lock:
        now = time.time()
        expires = float(getattr(account, "expires_at", 0) or 0)
        token = str(getattr(account, "access_token", "") or "")
        if (token and not force and not getattr(account, "token_expired", False)
                and (not expires or expires - now > REFRESH_SKEW)):
            return token, ""
        if not getattr(account, "refresh_token", ""):
            return None, "该账号没有 refreshToken，请重新登录"
        try:
            if account.refresh() and account.access_token:
                return str(account.access_token), ""
        except Exception as exc:
            return None, "续期异常：%s" % str(exc)[:160]
        return None, account.last_error or "Qoder 令牌续期失败"


# ---------------------------------------------------------------------------
# 请求改写（OpenAI → QoderInferRequest）
# ---------------------------------------------------------------------------
def _to_qoder_messages(messages):
    out = []
    system_heads = []
    for message in messages if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        if role == "developer":
            role = "system"
        if role not in ("system", "user", "assistant", "tool"):
            continue
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        elif isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text" and isinstance(part.get("text"), str):
                    parts.append({"type": "text", "text": part["text"]})
                elif part.get("type") == "image_url":
                    parts.append({"type": "image_url", "image_url": part.get("image_url")})
            content = parts
        else:
            content = []
        item = {"role": role, "content": content}
        if isinstance(message.get("tool_calls"), list) and message["tool_calls"]:
            item["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            item["tool_call_id"] = message["tool_call_id"]
        if message.get("name"):
            item["name"] = message["name"]
        has_content = bool(content)
        has_tools = bool(item.get("tool_calls"))
        if not has_content and not has_tools:
            continue
        if role == "system":
            system_heads.append(item)
        else:
            out.append(item)
    return system_heads + out


def _to_qoder_tools(tools):
    if not isinstance(tools, list):
        return []
    out = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict) \
                and tool["function"].get("name"):
            out.append({"type": "function", "function": tool["function"]})
    return out


def _static_models(product):
    return [(item["id"], {"name": item["name"], "supportsToolCall": True})
            for item in PRODUCTS[product].get("staticModels") or []]


def _model_meta_for_chat(product, model):
    cache = _MODEL_CACHE.get(product)
    if cache:
        for mid, meta in cache.get("models") or []:
            if mid.lower() == model.lower():
                return meta or {}
    for mid, meta in _static_models(product):
        if mid.lower() == model.lower():
            return meta or {}
    return {}


def _build_infer_body(account, model, body):
    product = _product(account.realm)
    meta = _model_meta_for_chat(product, model)
    display = str(meta.get("name") or model)
    context = int(meta.get("context_length") or meta.get("maxInputTokens") or 180000)
    request_id = str(uuid.uuid4())
    req = {
        "session_id": str(uuid.uuid4()),
        "source_session_id": "",
        "request_id": request_id,
        "request_set_id": request_id,
        # 官方客户端恒带 agent_id/task_id；Intl 网关缺 agent_id 时落到
        # agent_router 并报 "None flow nodes found"（CN 缺省可容忍）。
        "agent_id": "agent_common",
        "task_id": "common",
        "model_config": {
            "key": model.lower(),
            "display_name": display,
            "model": "",
            "format": "openai",
            "is_vl": bool(meta.get("supportsImages")),
            "is_reasoning": bool(meta.get("supportsReasoning")),
            "api_key": "",
            "url": "",
            "source": "system",
            "max_input_tokens": context,
        },
        "messages": _to_qoder_messages(body.get("messages")),
        "tools": _to_qoder_tools(body.get("tools")),
        "business": {},
    }
    for key in ("temperature", "max_tokens", "stop", "reasoning_effort"):
        value = body.get(key)
        if value is not None:
            req[key] = value
    return req


def _sign_request(account, token, model, req):
    product = _product(account.realm)
    cfg = PRODUCTS[product]
    body_json = json.dumps(req, ensure_ascii=False, separators=(",", ":"))
    signed = qoder_signer.sign(product, str(account.uid or ""), _machine_id(account),
                               token, cfg["gateway"], body_json, model.lower())
    try:
        raw = base64.b64decode(signed.get("bodyB64") or "")
    except Exception:
        raw = b""
    return signed.get("url") or "", signed.get("headers") or {}, raw


# ---------------------------------------------------------------------------
# 下行流：Qoder SSE 信封 → OpenAI SSE
# ---------------------------------------------------------------------------
class QoderChatStream(object):
    """把外层信封 {statusCode, body} 解包成 OpenAI chunk 字节流。

    信封层错误（HTTP 200 + statusCode≠OK）按 AgentHub 口径治理：
    101/签名失效 → 403（渠道级，不罚号）；116/额度 → 402 停车；
    10605/排队 → 429 冷却；UNAUTHORIZED → 401；其余 → 502。
    已出正文后不再换号（与 Trae 流内治理同构）。
    """

    def __init__(self, resp, model, account, log=None):
        self._resp = resp
        self._model = model
        self._account = account
        self._log = log
        self._buf = b""
        self._closed = False
        self._done = False
        self._sent_done = False
        self._pending = []
        self._error = None
        self._retry_after = None
        self._produced = False
        self._chat_id = "chatcmpl-qoder-" + uuid.uuid4().hex[:12]
        self._created = int(time.time())
        self._finish = ""
        self._finish_sent = False
        self._usage = None
        self._usage_sent = False

    def _read_raw_line(self):
        while b"\n" not in self._buf:
            if self._closed:
                return None
            try:
                chunk = self._resp.read(8192)
            except Exception:
                return None
            if not chunk:
                return None
            self._buf += chunk
        index = self._buf.index(b"\n")
        line = self._buf[:index + 1]
        self._buf = self._buf[index + 1:]
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
            if text.startswith(":"):
                continue
            if text.startswith("event:"):
                continue
            if text.startswith("data:"):
                data_lines.append(text[5:].strip())
        if not data_lines:
            return None
        return "\n".join(data_lines)

    def _fail(self, code, message, detail=None):
        account = self._account
        code_text = str(code or "")
        lower = str(message or "").lower()
        if code_text == "101" or "signature invalid" in lower:
            status = 403
            text = "Qoder 签名被拒（客户端版本可能已变更，请更新签名桥）：%s" % message
        elif code_text == "116" or "quota exceeded" in lower:
            account.note_balance_cooled("Qoder 积分不足（code 116），停车到次日 04:00")
            status = 402
            text = "Qoder 积分不足：%s" % message
        elif code_text == "10605" or "排队" in str(message):
            advice = parse_queue_advice(detail, message)
            wait = 60.0
            if advice.get("retryAfterSecs"):
                wait = min(max(1.0, advice["retryAfterSecs"]), 600.0)
            account.note_error("Qoder 模型排队（code 10605，冷却 %ds）" % int(wait),
                               cooldown=wait, detail=str(message)[:200])
            self._retry_after = wait
            status = 429
            suffix = ("（上游建议 %ss 后重试）" % advice["retryAfterSecs"]
                      if advice.get("retryAfterSecs") else "")
            text = "Qoder 模型排队中%s：%s" % (suffix, message)
        elif (code_text in ("UNAUTHORIZED", "401") or "token" in lower
              or "unauthor" in lower):
            account.token_expired = True
            account.last_error = "Qoder 凭证失效（流内 401）"
            status = 401
            text = "Qoder 凭证失效：%s" % message
        else:
            account.note_failure("Qoder 流内错误 code=%s：%s" % (code, message))
            status = 502
            text = "Qoder 上游错误 code=%s：%s" % (code, message)
        self._done = True
        self._pending.append({"error": {
            "message": text, "type": "upstream_error", "code": status}})
        self._error = urllib.error.HTTPError(
            PRODUCTS[_product(account.realm)]["gateway"], status, text, None, None)
        if self._retry_after:
            try:
                self._error.wb_retry_after = self._retry_after
            except Exception:
                pass

    @property
    def error(self):
        return self._error

    def prime(self):
        """读到首个可用增量（或确认失败）后再交出流：未出内容时还能换号。"""
        return registry.prime_stream(self)

    @staticmethod
    def _has_consumable(delta):
        if not isinstance(delta, dict):
            return False
        if isinstance(delta.get("content"), str) and delta["content"]:
            return True
        if isinstance(delta.get("reasoning_content"), str) and delta["reasoning_content"]:
            return True
        calls = delta.get("tool_calls")
        return isinstance(calls, list) and bool(calls)

    def _queue_tail(self):
        if self._usage is not None and not self._usage_sent:
            self._pending.append(self._chunk(usage=self._usage))
            self._usage_sent = True
        if not self._finish_sent:
            self._finish_sent = True
            self._pending.append(self._chunk(
                choices=[{"index": 0, "delta": {},
                          "finish_reason": self._finish or "stop"}]))

    def _chunk(self, choices=None, usage=None):
        out = {
            "id": self._chat_id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self._model,
            "choices": choices or [],
        }
        if usage is not None:
            out["usage"] = usage
        return out

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
                if not self._produced and self._usage is None:
                    self._account.note_failure("Qoder 空流（HTTP 200 无可用内容）")
                    self._error = urllib.error.HTTPError(
                        PRODUCTS[_product(self._account.realm)]["gateway"], 502,
                        "Qoder 上游返回了流但没有任何可用内容", None, None)
                    self._pending.append({"error": {
                        "message": "Qoder 上游返回了流但没有任何可用内容",
                        "type": "upstream_error", "code": 502}})
                    continue
                self._queue_tail()
                continue
            try:
                envelope = json.loads(event)
            except Exception:
                continue
            if not isinstance(envelope, dict):
                continue
            status_code = str(envelope.get("statusCode") or "")
            if status_code and status_code != "OK":
                inner = envelope.get("body")
                if isinstance(inner, str):
                    try:
                        inner = json.loads(inner)
                    except Exception:
                        inner = None
                code = _error_code(inner) if isinstance(inner, dict) else None
                message = (_error_text(inner) if isinstance(inner, dict) else "")
                self._fail(code or status_code, message or status_code,
                           detail=inner)
                continue
            body = envelope.get("body")
            if isinstance(body, dict):
                chunk = body
            elif isinstance(body, str):
                text = body.strip()
                if text == "[DONE]":
                    self._queue_tail()
                    self._done = True
                    continue
                if text in ("", "null", "None"):
                    continue
                try:
                    chunk = json.loads(text)
                except Exception:
                    continue
            else:
                continue
            if not isinstance(chunk, dict):
                continue
            choices = chunk.get("choices")
            if not isinstance(choices, list):
                choices = []
            consumable = False
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if self._has_consumable(delta):
                    consumable = True
                if choice.get("finish_reason"):
                    self._finish = str(choice["finish_reason"])
                    self._finish_sent = True
            if consumable:
                self._produced = True
            usage = chunk.get("usage")
            if usage is not None:
                self._usage = usage
            if not choices and usage is None:
                continue
            if usage is not None:
                self._usage_sent = True
            return self._chunk(choices=choices, usage=usage)

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


# ---------------------------------------------------------------------------
# 开流与账号轮换
# ---------------------------------------------------------------------------
def _http_detail(exc):
    try:
        return exc.read(1000).decode("utf-8", "replace")
    except Exception:
        return ""


def _classify_http(status, detail):
    lower = (detail or "").lower()
    if status == 401:
        return "relogin"
    if status == 402:
        return "credit"
    if status == 429:
        return "rate"
    if status == 403 and ("signature invalid" in lower or '"code":101' in lower
                          or '"code": 101' in lower):
        return "signature"
    if status == 404:
        return "not_found"
    if status == 400:
        return "fatal"
    if status >= 500:
        return "server"
    return "server"


def _retry_after(headers):
    try:
        return min(60.0, max(1.0, float((headers or {}).get("Retry-After") or 0)))
    except Exception:
        return 30.0


def _open_once(account, model, forwarded, ctx):
    token, err = _ensure_token(account)
    if token is None:
        raise _TokenError(err)
    req_body = _build_infer_body(account, model, forwarded)
    url, headers, payload = _sign_request(account, token, model, req_body)
    if not url or not payload:
        raise urllib.error.HTTPError(url or "qoder", 503,
                                     "Qoder 签名桥返回空请求", None, None)
    request = urllib.request.Request(url, data=payload, method="POST",
                                     headers=headers)
    request.wb_exact_headers = list(headers.items())
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    connect_timeout = ctx.upstream_connect_timeout()
    resp = net.urlopen(request, timeout=header_timeout,
                       proxy=getattr(account, "proxy", ""),
                       connect_timeout=connect_timeout)
    net.set_stream_idle_timeout(resp, idle_timeout)
    return resp


def open_stream(ctx, adapter, payload, session_key=None, realm=None):
    product = _product(realm or adapter.id)
    model = str(payload.get("model") or "").strip()
    prefix = product + "/"
    if model.lower().startswith(prefix):
        model = model[len(prefix):].strip()
    if not model:
        raise RuntimeError("qoder: empty model")
    body = dict(payload)
    body["model"] = model
    forwarded = upstream_body.build_upstream_body(body, ctx.system_prompt)
    forwarded["model"] = model

    pool = ctx.pool
    total = max(1, pool.count_ready(product, model=model)) if pool else 1
    attempts, deadline = net.request_budget(total)
    tried = set()
    last_error = None
    last_429 = None
    last_429_detail = ""

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        account = pool.pick_for_session(realm=product, session_key=session_key,
                                        exclude=tried, model=model) if pool else None
        if account is None:
            break
        if account.realm != product:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        try:
            resp = _open_once(account, model, forwarded, ctx)
        except qoder_signer.BridgeError as exc:
            # 签名桥/客户端级故障：换号无用，直接 503，不罚任何账号
            raise urllib.error.HTTPError(
                PRODUCTS[product]["gateway"], 503, str(exc), None, None)
        except _TokenError as exc:
            account.last_error = str(exc)
            last_error = urllib.error.HTTPError(
                PRODUCTS[product]["gateway"], 401,
                "Qoder 账号 %s 凭证不可用：%s" % (account.uid[:8], exc), None, None)
            continue
        except urllib.error.HTTPError as exc:
            detail = _http_detail(exc)
            kind = _classify_http(exc.code, detail)
            code = None
            try:
                blob = json.loads(detail)
                code = _error_code(blob)
            except Exception:
                pass
            if str(code) == "101" or "signature invalid" in detail.lower():
                kind = "signature"
            if kind == "relogin":
                token, err = _ensure_token(account, force=True)
                if token is not None:
                    try:
                        resp = _open_once(account, model, forwarded, ctx)
                        account.note_success(model=model)
                        return (QoderChatStream(resp, model, account, ctx.log),
                                {"account": account.uid, "realm": product,
                                 "account_obj": account})
                    except urllib.error.HTTPError as exc2:
                        exc = exc2
                        detail = _http_detail(exc)
                        kind = _classify_http(exc.code, detail)
                    except Exception as exc2:
                        account.note_failure("连接异常：%s" % str(exc2)[:120])
                        last_error = exc2
                        continue
                if err:
                    _log("account %s refresh failed: %s" % (account.uid[:8], err), ctx)
                account.last_error = err or "Qoder 凭证失效（401）"
                last_error = urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], 401,
                    "Qoder 账号 %s 凭证失效，已自动换号" % account.uid[:8],
                    exc.headers, None)
                continue
            if kind == "signature":
                # 客户端版本漂移：全渠道问题，立即上抛（零冷却、不罚号）
                raise urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], 403,
                    "Qoder 签名被拒（客户端版本可能已变更，请更新签名桥）：%s"
                    % (detail[:200] or code), exc.headers, None)
            if kind == "credit":
                msg = "积分不足（code %s）" % code if code else "HTTP 402"
                account.note_balance_cooled("Qoder %s，停车到次日 04:00" % msg)
                _log("account %s out of credits, parked until 04:00"
                     % account.uid[:8], ctx)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], 402,
                    "Qoder 账号 %s %s，已自动换号" % (account.uid[:8], msg),
                    exc.headers, None)
                continue
            if kind == "rate":
                wait = _retry_after(exc.headers)
                advice = parse_queue_advice(None, detail)
                if advice.get("retryAfterSecs"):
                    wait = min(max(1.0, advice["retryAfterSecs"]), 600.0)
                account.note_error("限流（HTTP 429，冷却 %ds）" % int(wait),
                                   cooldown=wait, detail=detail)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                try:
                    exc.wb_retry_after = wait
                except Exception:
                    pass
                last_error, last_429, last_429_detail = exc, exc, detail
                continue
            if kind == "not_found":
                account.note_error("该号不支持此模型（%s）" % (code or 404),
                                   model=model, cooldown=6 * 3600)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = exc
                continue
            if kind == "fatal":
                account.note_error("HTTP 400（不罚号）", cooldown=10, detail=detail)
                raise urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], 400,
                    "Qoder 上游拒绝请求（400）：%s" % (detail[:300] or code),
                    exc.headers, None)
            account.note_failure("HTTP %s：%s" % (exc.code, detail[:120]))
            if session_key and pool:
                pool.affinity.unbind(session_key)
            last_error = exc
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
                _log("account %s: connection hiccup (%s), rotating"
                     % (account.uid[:8], type(exc).__name__), ctx)
            else:
                account.note_unknown_failure(str(exc)[:120])
                account.note_error(str(exc)[:120], cooldown=60)
            last_error = exc
            continue
        stream = QoderChatStream(resp, model, account, ctx.log)
        try:
            verdict = stream.prime()
        except Exception as exc:
            stream.close()
            if session_key and pool:
                pool.affinity.unbind(session_key)
            account.note_unknown_failure(str(exc)[:120])
            last_error = exc
            _log("account %s: stream prime failed (%s), rotating"
                 % (account.uid[:8], type(exc).__name__), ctx)
            continue
        if verdict != "ready":
            # 未出内容就失败（流内 116/10605/空流）：罚则已由流内完成，换下一把；
            # 403 签名被拒是客户端版本问题，换号无用，直接透传
            stream.close()
            error = stream.error
            status = int(getattr(error, "code", 0) or 502)
            message = str(error) if error is not None else "上游没有返回可用内容"
            if status == 403:
                raise error or urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], 403, message, None, None)
            if status == 429:
                last_error, last_429 = error, error
                last_429_detail = message
            else:
                last_error = urllib.error.HTTPError(
                    PRODUCTS[product]["gateway"], status,
                    "Qoder 账号 %s：%s（已自动换号）"
                    % (account.uid[:8], message), None, None)
            if session_key and pool:
                pool.affinity.unbind(session_key)
            _log("account %s failed before content: HTTP %s %s"
                 % (account.uid[:8], status, message[:120]), ctx)
            continue
        account.note_success(model=model)
        return (stream,
                {"account": account.uid, "realm": product,
                 "account_obj": account})

    if last_error is not None:
        if last_429 is not None:
            from core import ratelimit
            wait = int(getattr(last_429, "wb_retry_after", 60) or 60)
            exc = ratelimit.RateLimited(last_429, last_429_detail, wait=wait)
            exc.account_uid = None
            raise exc
        raise last_error
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or do not support this model" % product)


# ---------------------------------------------------------------------------
# 模型目录
# ---------------------------------------------------------------------------
def _catalog_to_models(raw):
    if not isinstance(raw, dict):
        return []
    order = [key for key in ("assistant", "chat", "quest", "developer") if key in raw]
    order.extend(key for key in raw if key not in order)
    seen = {}
    for scene in order:
        entries = raw.get(scene)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key or key in seen or entry.get("enable") is False:
                continue
            context = 0
            config = entry.get("context_config")
            if isinstance(config, dict):
                for tier in config.values():
                    if isinstance(tier, dict):
                        try:
                            context = max(context, int(tier.get("token_count") or 0))
                        except (TypeError, ValueError):
                            continue
            if not context:
                try:
                    context = int(entry.get("max_input_tokens") or 0)
                except (TypeError, ValueError):
                    context = 0
            meta = {"name": str(entry.get("display_name") or key),
                    "supportsToolCall": True}
            if entry.get("is_vl"):
                meta["supportsImages"] = True
            if entry.get("is_reasoning"):
                meta["supportsReasoning"] = True
            if context:
                meta["context_length"] = context
                meta["maxInputTokens"] = context
            thinking = entry.get("thinking_config")
            if isinstance(thinking, dict):
                enabled = thinking.get("enabled")
                if isinstance(enabled, dict) and isinstance(enabled.get("efforts"), dict):
                    meta["reasoning"] = {"supportedEfforts": list(enabled["efforts"].keys())}
            factor = entry.get("price_factor")
            if factor is not None:
                try:
                    factor = float(factor)
                    meta["credits"] = "0" if factor == 0 else "x%g" % factor
                except (TypeError, ValueError):
                    pass
            seen[key] = meta
    return list(seen.items())


def _model_accounts(ctx, product):
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return []
    return [account for account in pool.accounts
            if account.realm == product and getattr(account, "enabled", False)
            and (getattr(account, "access_token", "")
                 or getattr(account, "refresh_token", ""))]


# ---------------------------------------------------------------------------
# 额度
# ---------------------------------------------------------------------------
def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _expiry_text(seconds):
    if not seconds:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))
    except Exception:
        return ""


def _credit_packages(data, plan_expires):
    rows = []

    def push(code, name, quota, expires):
        if not isinstance(quota, dict):
            return
        has_total = quota.get("total") is not None or quota.get("cap") is not None
        total = -1 if not has_total else _num(
            quota.get("total") if quota.get("total") is not None else quota.get("cap"))
        remaining = max(0.0, _num(quota.get("remaining")))
        expires = _epoch_seconds(expires)
        rows.append({
            "package_code": str(code)[:128],
            "name": str(name)[:128],
            "remain": round(remaining, 2),
            "size": round(total, 2) if total > 0 else 0,
            "is_expired": bool(expires and expires <= time.time()),
            "no_expiry": not expires,
            "expire_time": _expiry_text(expires),
        })

    push("user", "套餐额度", data.get("userQuota"),
         plan_expires or data.get("expiresAt"))
    push("addon", "资源包", data.get("addOnQuota"), 0)
    push("org", "组织资源包", data.get("orgResourcePackage"), 0)
    dedicated = data.get("dedicatedResourcePackages")
    if isinstance(dedicated, list):
        for index, package in enumerate(dedicated):
            if not isinstance(package, dict) or package.get("available") is False:
                continue
            labels = package.get("displayLabels")
            title = "专用资源包"
            if isinstance(labels, list) and labels and isinstance(labels[0], dict):
                title = str(labels[0].get("title") or title)
            push(package.get("id") or ("dedicated%d" % index), title, package,
                 package.get("expiresAt"))
    return rows


def get_credits(account, force=False):
    cache_key = (str(account.realm or ""), str(account.uid or ""))
    now = time.time()
    with _CREDITS_LOCK:
        hit = _CREDITS_CACHE.get(cache_key)
        if hit and not force and now - hit[0] <= CREDITS_TTL:
            result = dict(hit[1])
            result["cached"] = True
            return result
    token, err = _ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    product = _product(account.realm)
    bases = [PRODUCTS[product]["quotaBase"], PRODUCTS[product]["gateway"],
             PRODUCTS[product]["openApi"]]
    bases = [b for i, b in enumerate(bases) if b and b not in bases[:i]]
    last = ""
    for base in bases:
        url = "%s%s?requestId=%s" % (
            base.rstrip("/"), QUOTA_PATH, uuid.uuid4())
        status, data = _json_request(
            "GET", url,
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json",
                     "User-Agent": USER_AGENT},
            timeout=30, proxy=getattr(account, "proxy", ""))
        if status == 401:
            return {"ok": False, "authError": True,
                    "error": "Qoder 凭证失效（HTTP 401）"}
        if status == 200 and isinstance(data, dict):
            user_quota = data.get("userQuota")
            addon = data.get("addOnQuota")
            if isinstance(user_quota, dict) or isinstance(addon, dict):
                remaining = _num((user_quota or {}).get("remaining")) + \
                    _num((addon or {}).get("remaining"))
                expires = _epoch_seconds(data.get("expiresAt"))
                result = {
                    "ok": True,
                    "credits": round(remaining, 2),
                    "expiresAt": expires,
                    "packages": _credit_packages(data, expires),
                    "userType": data.get("userType") or "",
                    "cached": False,
                }
                with _CREDITS_LOCK:
                    _CREDITS_CACHE[cache_key] = (now, dict(result))
                return result
            if data.get("credits") is not None:
                result = {"ok": True, "credits": _num(data.get("credits")),
                          "expiresAt": _epoch_seconds(data.get("expiresAt")),
                          "cached": False}
                with _CREDITS_LOCK:
                    _CREDITS_CACHE[cache_key] = (now, dict(result))
                return result
            last = "额度结构未识别"
            continue
        last = "HTTP %s %s" % (status, _error_text(data)[:100])
    return {"ok": False, "error": "额度查询失败：%s" % (last or "不可达")}


def credits_for_account(account, force=False):
    result = get_credits(account, force=force)
    if result.get("authError"):
        return result
    if not result.get("ok"):
        return result
    credits = float(result.get("credits") or 0)
    account.credits = {
        "remain": credits,
        "unlimited": False,
        "size": None,
        "packages": result.get("packages") or [],
        "expiresAt": result.get("expiresAt") or 0,
        "updated_at": time.time(),
        "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save(account)
    return {"ok": True, "credits": account.credits}


# ---------------------------------------------------------------------------
# 每日领取（sash campaigns）
# ---------------------------------------------------------------------------
def _client_status(product):
    now = time.time()
    with _RISK_LOCK:
        hit = _CLIENT_STATUS.get(product)
        if hit and now - hit[0] < RISK_CACHE_TTL:
            return hit[1]
    try:
        info = qoder_signer.status(product)
    except Exception:
        info = {}
    value = {
        "runtimeInfo": str(info.get("runtimeInfo") or ""),
        "version": str(info.get("version") or ""),
    }
    if value["runtimeInfo"]:
        with _RISK_LOCK:
            _CLIENT_STATUS[product] = (now, value)
    return value


def _risk_identity(account):
    product = _product(account.realm)
    now = time.time()
    with _RISK_LOCK:
        hit = _RISK_CACHE.get(product)
        if hit and now - hit[0] < RISK_CACHE_TTL:
            return hit[1]
    client = _client_status(product)
    path = client.get("runtimeInfo") or ""
    if not path or not os.path.exists(path):
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        proc = subprocess.run(
            [path, "--account-stdin"],
            input=json.dumps({"account": str(account.uid or "")}),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=flags)
        if proc.returncode != 0:
            return None
        data = json.loads((proc.stdout or "").strip() or "{}")
        if not data.get("machineToken"):
            return None
        value = {
            "machineToken": str(data["machineToken"]),
            "machineType": str(data.get("machineType") or ""),
            "machineCode": str(data.get("machineCode") or ""),
            "clientVersion": client.get("version") or "",
        }
        with _RISK_LOCK:
            _RISK_CACHE[product] = (now, value)
        return value
    except Exception:
        return None


def _cosy_headers(account, token, risk):
    hostname = socket.gethostname()
    try:
        hostname = hostname.encode("ascii", "ignore").decode("ascii") or "localhost"
    except Exception:
        hostname = "localhost"
    try:
        # 与客户端同源：Windows 上是内核版本（AgentHub 用 os.release()）
        os_version = (platform.version() if os.name == "nt"
                      else "%s-%s" % (platform.system(), platform.release()))
    except Exception:
        os_version = ""
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": CLIENT_USER_AGENT,
        "Cosy-ClientType": "10",
        "Cosy-Version": risk.get("clientVersion") or CLIENT_VERSION_FALLBACK,
        "Cosy-MachineId": _machine_id(account),
        "Cosy-MachineOS": os_version,
        "Cosy-MachineHostname": hostname,
        "Cosy-MachineToken": risk.get("machineToken") or "",
        "Cosy-MachineType": risk.get("machineType") or "",
        "Cosy-MachineCode": risk.get("machineCode") or "",
    }


def _campaigns(account, token, risk, timeout=30):
    product = _product(account.realm)
    url = (PRODUCTS[product]["openApi"].rstrip("/")
           + "/sash/api/v1/me/campaigns?forceRefresh=true")
    return _json_request("GET", url, headers=_cosy_headers(account, token, risk),
                         timeout=timeout, proxy=getattr(account, "proxy", ""))


def _campaign_active(campaign, now):
    start = _epoch_seconds(campaign.get("startAt"))
    end = _epoch_seconds(campaign.get("endAt"))
    if start and start > now:
        return False
    if end and end <= now:
        return False
    return True


def _benefit_campaigns(campaigns, now, status, credits_only=False):
    out = []
    for campaign in campaigns:
        if not isinstance(campaign, dict):
            continue
        if campaign.get("actionType") != "CLAIM_BENEFIT":
            continue
        if campaign.get("claimStatus") != status:
            continue
        if credits_only and (campaign.get("benefit") or {}).get("kind") != "CREDITS":
            continue
        if not _campaign_active(campaign, now):
            continue
        out.append(campaign)
    return out


def _claimable_campaigns(campaigns, now=None):
    now = time.time() if now is None else now
    return [c for c in _benefit_campaigns(campaigns, now, "CLAIMABLE")
            if c.get("campaignId")]


def _claimed_credit_campaigns(campaigns, now=None):
    now = time.time() if now is None else now
    return _benefit_campaigns(campaigns, now, "CLAIMED", credits_only=True)


def checkin_status(account):
    token, err = _ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    risk = _risk_identity(account)
    if risk is None:
        return {"ok": True, "unavailable": True,
                "message": "需安装 Qoder 客户端（领取接口要求其风控身份 runtime-info.exe）"}
    status, data = _campaigns(account, token, risk)
    if status in (401, 403):
        return {"ok": False, "authError": True, "error": "Qoder 凭证失效（活动接口）"}
    if status != 200 or not isinstance(data, dict):
        return {"ok": True, "unavailable": True,
                "message": "活动列表 HTTP %s" % status}
    campaigns = data.get("campaigns") if isinstance(data.get("campaigns"), list) else []
    now = time.time()
    claimable = _claimable_campaigns(campaigns, now)
    if claimable:
        return {"ok": True, "checkedIn": False, "claimable": len(claimable),
                "message": "有 %d 个活动可领取" % len(claimable)}
    claimed = _claimed_credit_campaigns(campaigns, now)
    return {"ok": True, "checkedIn": bool(claimed), "claimable": 0,
            "message": "今日已领取" if claimed else "当前无可领取活动"}


def checkin_claim(account):
    token, err = _ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    risk = _risk_identity(account)
    if risk is None:
        return {"ok": True, "unavailable": True,
                "message": "需安装 Qoder 客户端（领取接口要求其风控身份 runtime-info.exe）"}
    status, data = _campaigns(account, token, risk)
    if status in (401, 403):
        return {"ok": False, "authError": True, "error": "Qoder 凭证失效（活动接口）"}
    if status != 200 or not isinstance(data, dict):
        return {"ok": False, "error": "活动列表 HTTP %s" % status}
    campaigns = data.get("campaigns") if isinstance(data.get("campaigns"), list) else []
    now = time.time()
    claimable = _claimable_campaigns(campaigns, now)
    already_credit = bool(_claimed_credit_campaigns(campaigns, now))
    if not claimable:
        if already_credit:
            return {"ok": True, "already": True, "message": "今日已领取"}
        # 没有当前窗口内的活动：不能当作已领取落 last_checkin，否则面板会
        # 显示已领取而客户端仍可领（活动尚未下发 / 列表只含历史活动）。
        return {"ok": False, "unavailable": True, "noCampaign": True,
                "message": "当前没有可领取的活动"}
    claimed_any = 0
    replayed_any = 0
    claimed_credit = 0
    replayed_credit = 0
    last = ""
    last_credit = ""
    base = PRODUCTS[_product(account.realm)]["openApi"].rstrip("/")
    headers = _cosy_headers(account, token, risk)
    headers["Content-Type"] = "application/json"
    for campaign in claimable:
        is_credit = (campaign.get("benefit") or {}).get("kind") == "CREDITS"
        url = "%s/sash/api/v1/me/campaigns/%s/claim" % (
            base, urllib.parse.quote(str(campaign.get("campaignId")), safe=""))
        status, data = _json_request("POST", url, headers=headers,
                                     body=b"{}", timeout=30,
                                     proxy=getattr(account, "proxy", ""))
        if status in (401, 403):
            return {"ok": False, "authError": True, "error": "Qoder 凭证失效"}
        if status == 409 and isinstance(data, dict) \
                and data.get("result") == "ALREADY_CLAIMED":
            replayed_any += 1
            replayed_credit += 1 if is_credit else 0
            last = "今日已领取"
            if is_credit:
                last_credit = last
            continue
        if status != 200 or not isinstance(data, dict):
            code = _error_code(data) if isinstance(data, dict) else None
            last = ("活动尚未就绪（%s）" % code if code == "GRANT_NOT_FOUND"
                    else "领取失败 HTTP %s" % status)
            if is_credit:
                last_credit = last
            continue
        if data.get("replayed") is True:
            replayed_any += 1
            replayed_credit += 1 if is_credit else 0
            last = "今日已领取"
            if is_credit:
                last_credit = last
            continue
        if data.get("status") == "CLAIMED":
            claimed_any += 1
            amount = (data.get("benefit") or {}).get("amount")
            last = ("领取成功 +%s Credits" % amount
                    if amount is not None else "领取成功")
            if is_credit:
                claimed_credit += 1
                last_credit = last
        else:
            last = "领取未生效（status=%s）" % (data.get("status") or "unknown")
            if is_credit:
                last_credit = last
    if claimed_credit > 0:
        return {"ok": True, "already": False,
                "message": last_credit or "领取成功"}
    if replayed_credit > 0 or already_credit:
        return {"ok": True, "already": True, "message": last_credit or "今日已领取"}
    if claimed_any > 0 or replayed_any > 0:
        return {"ok": False, "unavailable": True,
                "message": "已领取非积分活动，积分活动暂不可领取"}
    return {"ok": False, "error": last_credit or last or "领取失败"}


def checkin_for_account(account, trigger="unknown"):
    result = checkin_claim(account)
    if result.get("noCampaign") and account.checked_in_today():
        # 旧逻辑曾把“无活动”记成今日已领取；以当前活动列表为准纠正当天标记
        account.last_checkin = None
        _save(account)
    if result.get("ok") and not result.get("unavailable"):
        account.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
        _save(account)
        try:
            from infra import activity
            activity.record_attempt(account, "checkin", trigger, result)
        except Exception:
            pass
        try:
            account.fetch_credits(force=True)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# 连通性探测
# ---------------------------------------------------------------------------
def probe_account(account, timeout=20):
    token, err = _ensure_token(account)
    if token is None:
        return {"ok": False, "message": err}
    product = _product(account.realm)
    model = PRODUCTS[product]["probeModel"]
    body = {"model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1, "stream": True}
    forwarded = upstream_body.build_upstream_body(body)
    forwarded["model"] = model
    try:
        req_body = _build_infer_body(account, model, forwarded)
        url, headers, payload = _sign_request(account, token, model, req_body)
        request = urllib.request.Request(url, data=payload, method="POST",
                                         headers=headers)
        request.wb_exact_headers = list(headers.items())
        started = time.time()
        with net.urlopen(request, timeout=timeout,
                         proxy=getattr(account, "proxy", "")) as resp:
            raw = resp.read(256)
        if not raw:
            return {"ok": False, "message": "Qoder 上游未返回任何数据"}
        elapsed = int((time.time() - started) * 1000)
        return {"ok": True, "model": model, "latencyMs": elapsed,
                "message": "Qoder 账号连通正常（%s，%d ms）" % (model, elapsed)}
    except qoder_signer.BridgeError as exc:
        return {"ok": False, "message": str(exc)}
    except urllib.error.HTTPError as exc:
        detail = _http_detail(exc)
        return {"ok": False, "message": "Qoder 上游 HTTP %s：%s"
                % (exc.code, detail[:150] or "无详情")}
    except Exception as exc:
        return {"ok": False, "message": "请求异常: %s" % exc}


# ---------------------------------------------------------------------------
# 本机凭据导入 / OAuth 登录
# ---------------------------------------------------------------------------
def _find_account(ctx, uid, realm):
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return None
    for account in pool.accounts:
        if account.uid == uid and account.realm == realm:
            return account
    return None


def _login_identity(user):
    """从 Qoder userinfo 里取登录账号；实测没有独立 email 时邮箱会在 name 里。"""
    user = user if isinstance(user, dict) else {}
    for key in ("email", "username", "preferred_username", "login"):
        value = str(user.get(key) or "").strip()
        if accounts_mod.looks_like_login_account(value):
            return value
    name = str(user.get("name") or user.get("nickname") or "").strip()
    return name if accounts_mod.looks_like_login_account(name) else ""


def _upsert_account(ctx, product, uid, name, token, refresh_token,
                    expires_at, machine_id, source, meta_extra=None):
    cfg = PRODUCTS[product]
    extra = {key: value for key, value in (meta_extra or {}).items() if value}
    pool = getattr(ctx, "pool", None)
    existing = _find_account(ctx, uid, product)
    if existing is None and pool is not None:
        other = pool.get(uid)
        if other is not None and other.realm != product:
            raise RuntimeError("账号 uid 与已有渠道账号冲突（%s），无法导入" % other.realm)
    if existing is not None:
        existing.access_token = token or existing.access_token
        existing.refresh_token = refresh_token or existing.refresh_token
        if expires_at:
            existing.expires_at = expires_at
        meta = dict(getattr(existing, "meta", None) or {})
        meta["product"] = product
        # machineId 旧值优先（同一客户端文件只代表当前登录账号，不能覆盖其他账号）
        meta["machineId"] = str(meta.get("machineId") or machine_id or "")
        meta.update(extra)
        existing.meta = meta
        existing.enabled = True
        existing.token_expired = False
        existing.clear_error()
        _save(existing)
        return existing
    account = accounts_mod.Account({
        "uid": uid,
        "nickname": name or uid[:8],
        "realm": product,
        "domain": cfg["domain"],
        "platform": "CLI",
        "accessToken": token,
        "refreshToken": refresh_token,
        "expiresAt": accounts_mod.normalize_epoch(expires_at or 0),
        "source": source,
        "enabled": True,
        "meta": {"product": product, "machineId": machine_id, **extra},
    })
    if pool is not None:
        pool.add(account)
    else:
        account.save(ctx.accounts_dir)
    return account


def _scan_one(ctx, product):
    cfg = PRODUCTS[product]
    label = cfg["label"]
    try:
        info = qoder_signer.status(product)
        if not info.get("detected"):
            return []
        cred = qoder_signer.read_credentials(product)
    except Exception as exc:
        reason = str(exc)[:100]
        return [{
            "path": "auth.v1.dat",
            "file": "auth.v1.dat（%s）：%s" % (label, reason),
            "realm": product,
            "realmLabel": label,
            "domain": cfg["domain"],
            "nickname": "读取失败：%s" % reason,
            "encrypted": False,
            "valid": False,
            "usable": False,
            "error": reason,
        }]
    user = cred.get("user") or {}
    uid = str(user.get("id") or "").strip()
    name = str(user.get("name") or user.get("email") or "").strip()
    login_account = _login_identity(user)
    usable = bool(uid and (cred.get("token") or cred.get("refreshToken")))
    return [{
        "path": "auth.v1.dat",
        "file": "auth.v1.dat（%s）" % label,
        "realm": product,
        "realmLabel": label,
        "domain": cfg["domain"],
        "uid": uid,
        "nickname": name,
        "loginAccount": login_account,
        # 客户端文件本身是加密信封，但网关可解密导入；面板的 encrypted
        # 标记语义是「解不开、只能换 OAuth」，这里不要误报。
        "encrypted": False,
        "valid": usable,
        "usable": usable,
        "source": "scan",
    }]


def import_from_desktop(ctx, product):
    try:
        cred = qoder_signer.read_credentials(product)
    except Exception as exc:
        raise RuntimeError("读取 Qoder 本机凭据失败：%s" % exc)
    user = cred.get("user") or {}
    uid = str(user.get("id") or "").strip()
    if not uid:
        raise RuntimeError("Qoder 本机凭据缺少账号 uid，请确认客户端已登录")
    name = str(user.get("name") or user.get("email") or "").strip()
    login_account = _login_identity(user)
    expires = accounts_mod.normalize_epoch(cred.get("expiresAt") or 0)
    return _upsert_account(
        ctx, product, uid, name, str(cred.get("token") or ""),
        str(cred.get("refreshToken") or ""), expires,
        str(cred.get("machineId") or ""), "desktop-app",
        meta_extra={"loginAccount": login_account})


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode("ascii")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _refresh_credentials(product, token, refresh_token, machine_id):
    cfg = PRODUCTS[product]
    body = {"refresh_token": refresh_token}
    if machine_id:
        body["machine_id"] = machine_id
    status, data = _json_request(
        "POST", cfg["openApi"] + REFRESH_PATH,
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
        body=json.dumps(body).encode("utf-8"), timeout=30)
    return status, data


class QoderAdapter(registry.ChannelAdapter):
    def __init__(self, product):
        self.id = product
        self.realm = product
        self.label = PRODUCTS[product]["label"]
        self.realms = (product,)
        self.route_prefixes = (product,)
        self.capabilities = frozenset({
            registry.CAP_CHAT, registry.CAP_RESPONSES, registry.CAP_MODELS,
            registry.CAP_ACCOUNTS, registry.CAP_CHECKIN,
            registry.CAP_SCHEDULER, registry.CAP_PROXY_SLOT,
            registry.CAP_DESKTOP_IMPORT,
        })
        self._ctx = None
        self._login = {}
        self._login_lock = threading.Lock()
        self._model_lock = _MODEL_LOCKS.setdefault(product, threading.Lock())

    # ------------------------------------------------------------ 注册
    def register(self, ctx):
        self._ctx = ctx
        product = self.id
        accounts_mod.register_realm_config(product, {
            "name": self.label,
            "domain": PRODUCTS[product]["domain"],
            "has_checkin": True,
            "has_daily_chat": False,
            "refresh_fn": _refresh_account,
            "credits_fn": credits_for_account,
            "checkin_fn": checkin_for_account,
            "probe_fn": probe_account,
        })

    # ------------------------------------------------------------ 登录
    def start_login(self, ctx, realm, platform="CLI"):
        if realm != self.id:
            return None
        product = self.id
        cfg = PRODUCTS[product]
        verifier, challenge = _pkce_pair()
        nonce = str(uuid.uuid4())
        try:
            machine_id = qoder_signer.ensure_machine_id(product)
        except Exception as exc:
            return {"ok": False,
                    "message": "无法准备 Qoder 登录（需本机安装并登录客户端）：%s" % exc}
        select_url = cfg["authBase"].rstrip("/") + "/device/selectAccounts?" + \
            urllib.parse.urlencode({
                "challenge": challenge, "challenge_method": "S256",
                "nonce": nonce, "machine_id": machine_id,
                "client_id": cfg["clientId"]})
        login_url = cfg["authBase"].rstrip("/") + "/users/sign-in?" + \
            urllib.parse.urlencode({"biz_variant": "qoder",
                                    "oauth_callback": select_url})
        poll_url = cfg["openApi"].rstrip("/") + "/api/v1/deviceToken/poll?" + \
            urllib.parse.urlencode({"nonce": nonce, "verifier": verifier,
                                    "challenge_method": "S256"})
        session = {
            "state": nonce, "product": product, "verifier": verifier,
            "poll_url": poll_url, "machine_id": machine_id,
            "started": time.time(), "status": "waiting", "message": "",
        }
        with self._login_lock:
            self._login[nonce] = session
            now = time.time()
            for key in list(self._login):
                old = self._login[key]
                if now - old.get("started", 0) > LOGIN_TIMEOUT + 60:
                    self._login.pop(key, None)
        return {"ok": True, "authUrl": login_url, "state": nonce,
                "realm": product,
                "hint": "在浏览器完成 Qoder 登录后会自动入池（3 分钟内有效）"}

    def poll_login(self, ctx, state):
        session = self._login.get(state)
        if session is None:
            # 不认识这个 state：交给其它渠道的登录会话，不冒充「已过期」
            return None
        if session.get("status") != "waiting":
            return {"status": session.get("status"),
                    "message": session.get("message") or ""}
        if time.time() - session.get("started", 0) > LOGIN_TIMEOUT:
            session["status"] = "expired"
            session["message"] = "登录超时（3 分钟），请重新发起"
            return {"status": "expired", "message": session["message"]}
        status, data = _json_request(
            "GET", session["poll_url"],
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=20)
        if status == 200 and isinstance(data, dict) \
                and data.get("token") and data.get("refresh_token"):
            try:
                account = self._save_oauth_account(
                    ctx, session["product"], str(data["token"]),
                    str(data["refresh_token"]), session.get("machine_id") or "")
                session["status"] = "ok"
                session["message"] = "Qoder 账号已登录并入池（%s）" % account.nickname
                return {"status": "ok", "message": session["message"],
                        "uid": account.uid}
            except Exception as exc:
                session["status"] = "error"
                session["message"] = str(exc)[:200]
                return {"status": "error", "message": session["message"]}
        if status in (404, 408, 429, 0) or status >= 500:
            return {"status": "pending", "message": "等待浏览器完成授权…"}
        if 400 <= status < 500:
            session["status"] = "error"
            session["message"] = "登录轮询失败（HTTP %s）：%s" % (
                status, _error_text(data)[:120])
            return {"status": "error", "message": session["message"]}
        return {"status": "pending", "message": "等待浏览器完成授权…"}

    def cancel_login(self, ctx, state):
        with self._login_lock:
            if state not in self._login:
                return None
            self._login.pop(state, None)
        return {"ok": True}

    def _save_oauth_account(self, ctx, product, token, refresh_token, machine_id):
        cfg = PRODUCTS[product]
        status, data = _json_request(
            "GET", cfg["openApi"].rstrip("/") + "/api/v1/userinfo",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/json", "User-Agent": "Qoder"},
            timeout=20)
        user = {}
        if status == 200 and isinstance(data, dict):
            user = data.get("user") or data.get("data") or data
            if not isinstance(user, dict):
                user = {}
        uid = str(user.get("id") or user.get("user_id") or user.get("uid") or "").strip()
        if not uid:
            raise RuntimeError("登录成功但取不到账号 uid（userinfo 不可用），"
                               "请改用「导入本机凭据」")
        name = str(user.get("name") or user.get("nickname")
                   or user.get("email") or "").strip()
        login_account = _login_identity(user)
        expires = 0
        status, refreshed = _refresh_credentials(product, token, refresh_token,
                                                 machine_id)
        if status == 200 and isinstance(refreshed, dict) \
                and refreshed.get("device_token"):
            token = str(refreshed["device_token"])
            refresh_token = str(refreshed.get("refresh_token") or refresh_token)
            expires = _epoch_seconds(refreshed.get("expires_at"))
        return _upsert_account(ctx, product, uid, name, token, refresh_token,
                               expires, machine_id, "oauth",
                               meta_extra={"loginAccount": login_account})

    # ------------------------------------------------------------ 本机导入
    def scan_desktop(self, ctx):
        return _scan_one(ctx, self.id)

    def import_desktop(self, ctx, candidate):
        return import_from_desktop(ctx, self.id)

    # ------------------------------------------------------------ 登录身份
    def login_account_pending(self, account):
        """老账号没有 meta 身份时，面板可来同步一次 userinfo。"""
        if account.realm not in PRODUCTS:
            return False
        if account.login_account_source() not in ("nickname", "uid"):
            return False
        if accounts_mod.looks_like_login_account(account.login_account()):
            return False
        meta = account.meta if isinstance(account.meta, dict) else {}
        try:
            last = int(meta.get("identitySyncAt") or 0)
        except (TypeError, ValueError):
            last = 0
        return time.time() - last >= IDENTITY_SYNC_RETRY

    def sync_login_account(self, ctx, account):
        """从 /api/v1/userinfo 取邮箱/手机号并落 meta；失败也记时间避免空转。"""
        if account.realm not in PRODUCTS:
            return ""
        identity = ""
        token, _err = _ensure_token(account)
        if token:
            cfg = PRODUCTS[_product(account.realm)]
            status, data = _json_request(
                "GET", cfg["openApi"].rstrip("/") + "/api/v1/userinfo",
                headers={"Authorization": "Bearer " + token,
                         "Accept": "application/json", "User-Agent": "Qoder"},
                timeout=20, proxy=getattr(account, "proxy", ""))
            user = {}
            if status == 200 and isinstance(data, dict):
                user = data.get("user") or data.get("data") or data
                if not isinstance(user, dict):
                    user = {}
            identity = _login_identity(user)
        meta = dict(account.meta or {})
        meta["identitySyncAt"] = int(time.time())
        if identity:
            meta["loginAccount"] = identity
        account.meta = meta
        _save(account)
        return identity

    # ------------------------------------------------------------ 代理链路
    def open_stream(self, ctx, payload, session_key=None, realm=None):
        return open_stream(ctx, self, payload, session_key=session_key,
                           realm=realm or self.id)

    def live_models(self, realm, force=False):
        product = self.id
        now = time.time()
        with self._model_lock:
            cache = _MODEL_CACHE.get(product)
            if cache and not force and now - cache["at"] <= MODEL_CACHE_TTL:
                return list(cache["models"])
            ctx = self._ctx
            accounts = _model_accounts(ctx, product)
            if not accounts:
                fallback = [] if force else _static_models(product)
                if not force:
                    _MODEL_CACHE[product] = {"at": now, "models": fallback}
                return list(fallback)
            # 目录缓存按账号 uid 落盘：某个账号没有本机 catalog 时换下一个，
            # 不能因为池里第一个账号没装对应客户端就宣告整个出口无目录。
            for account in accounts:
                token, err = _ensure_token(account)
                if token is None:
                    continue
                try:
                    result = qoder_signer.catalog(
                        product, str(account.uid or ""), _machine_id(account), token)
                except Exception as exc:
                    _log("model catalog failed for %s: %s"
                         % (account.uid[:8], exc), ctx)
                    continue
                if not result.get("available"):
                    continue
                models = _catalog_to_models(result.get("catalog") or {})
                if models:
                    _MODEL_CACHE[product] = {"at": now, "models": models}
                    return list(models)
            fallback = [] if force else _static_models(product)
            return list(fallback)

    def scheduler_tasks(self, ctx):
        task_id = "%s_checkin" % self.id
        product = self.id

        def run(reason, source="auto"):
            def eligible(account):
                return (getattr(account, "realm", "") == product
                        and getattr(account, "enabled", False)
                        and bool(getattr(account, "access_token", "")
                                 or getattr(account, "refresh_token", "")))

            def action(account):
                result = checkin_for_account(
                    account, trigger="scheduler" if source == "auto" else "manual")
                if result.get("ok") and result.get("already"):
                    return {"status": "already",
                            "message": result.get("message") or "今日已领取"}
                if result.get("ok"):
                    return {"status": "ok",
                            "message": result.get("message") or "领取成功"}
                if result.get("unavailable"):
                    return {"status": "skip",
                            "message": result.get("message") or "领取服务未开放"}
                return {"status": "error",
                        "message": result.get("error") or result.get("message")
                        or "领取失败"}

            return ctx.run_task_over_accounts(
                kind=task_id, source=source, ready=eligible,
                action=action, realm=product)

        # 领取窗口每日 10:00（UTC+8）重置；11 点与 14 点各跑一次，避开整点边界
        return [(task_id, "%s 每日领取" % self.label, run,
                 {"enabled": True, "hours": [11, 14], "realm": product})]

    def panel_meta(self, ctx):
        pool = getattr(ctx, "pool", None)
        cfg = PRODUCTS[self.id]
        return {
            "id": self.id,
            "label": self.label,
            "realms": [{
                "id": self.id,
                "label": cfg["short"],
                "badge": cfg["badge"],
                "domain": cfg["domain"],
                "accounts": pool.count_ready(realm=self.id) if pool else 0,
                "capabilities": sorted(self.capabilities),
                "desktop_import": True,
            }],
            "capabilities": sorted(self.capabilities),
            "frontend": self.id,
            "enabled": True,
        }


def install(ctx):
    qoder_signer.configure(ctx.accounts_dir, log=lambda msg: _log(msg, ctx))
    import atexit
    atexit.register(qoder_signer.shutdown_all)
    registry.register(QoderAdapter("qoder"), ctx)
    registry.register(QoderAdapter("qoder_intl"), ctx)
