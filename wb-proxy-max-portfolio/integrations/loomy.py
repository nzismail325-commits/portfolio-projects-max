# -*- coding: utf-8 -*-
"""integrations/loomy.py —— Loomy（讯飞）反代渠道

协议事实来自 AgentHub v1.82.2 的 loomy 适配器（Copyright (c) 2026 沐晖
(HUIdada1)，MIT + 附加使用条款；本文件为独立 Python 实现，仅移植行为口径，
不复制其源码结构。上游版权与附加条款见 AgentHub LICENSE，仅限自用）：

- 登录：手机号 + 短信验证码两跳（账号域 CAccount，HMAC-SHA1 签名）。登录
  返回的 session 有效期 14 天，上游没有续期接口，过期只能重新短信登录；
- 转发：集成网关 OpenAI 兼容（/api/v1/models 与 /chat/completions），请求
  同时带 `token` 与 `Authorization: Bearer` 双头；chat 用 SSE，无状态；
- 目录：只认上游 /models，不编造静态兜底；拉不到就如实报错并保留旧清单；
- 余额：/api/v2/points/records 的摘要字段里同时带永久积分与每日赠送积分，
  两个钱包分开记账；
- 每日福利：POST /api/v1/points/first-login 把每日赠送积分刷回 5000（上游
  按天幂等，没有独立签到查询接口）；
- 图片：客户端 0.9.39 全包未使用 <image_base64>，视觉链路发 image_url data
  URL；真实 A/B 验证标准 image_url 可用，AgentHub 的 deepseek 标记改写已删除。

本模块只依赖核心设施；核心不引用任何 loomy 字样。
"""
import base64
import copy
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import threading
import time
import urllib.error
import uuid
import urllib.parse
import urllib.request
from email.utils import formatdate

from auth import accounts as accounts_mod
from core import net
from core import ratelimit
from core import upstream_body
from core import upstream_pool
from integrations import registry

REALM = "loomy"
LABEL = "Loomy（讯飞）"
SHORT = "Loomy"
BADGE = "Loomy"
DOMAIN = "loomyad.xunfei.cn"

MODEL_CACHE_TTL = 600.0
CREDITS_TTL = 60.0
LOGIN_TTL = 900.0
SESSION_DAYS = 14
REQUEST_TIMEOUT = 20

SUCCESS_CODE = "000000"
AUTH_ERROR_CODES = {"020002", "100002"}

CLIENT_UA = "Loomy|Desktop|Electron|macOS"
CLIENT_VERSION = "1.0.0"  # 登录 base 信封字段，客户端 _makeBase 固定值
APP_VERSION = "0.9.39"    # 聊天 loomy-version 头，可被环境变量覆盖
CHAT_PURPOSE = "chat.message"
WEB_MODEL_ID = "Web"
WEB_DEVICE_ID = "web"


def _env(name, default):
    value = str(os.environ.get(name) or "").strip().rstrip("/")
    return value or default


APP_VERSION = _env("LOOMY_APP_VERSION", APP_VERSION)

CFG = {
    "xfyunBase": _env("LOOMY_XFYUN_BASE_URL", "https://account.xfinfr.com"),
    "integrationBase": _env("LOOMY_POINTS_BASE_URL",
                            "https://loomyad.xunfei.cn"),
    "accessKeyId": _env("LOOMY_XFYUN_ACCESS_KEY_ID", "2thryby66wxi53sk"),
    "accessKeySecret": _env("LOOMY_XFYUN_ACCESS_KEY_SECRET",
                            "zsak6eadrbawz683wf5r3m2snrwj868r"),
    "appId": _env("LOOMY_XFYUN_APP_ID", "GM3LOOMY"),
}

_MODEL_CACHE = {"at": 0.0, "models": []}
_MODEL_LOCK = threading.Lock()
_CREDITS_CACHE = {}
_CREDITS_LOCK = threading.Lock()
_LOGIN = {}
_LOGIN_LOCK = threading.Lock()


class LoomyError(RuntimeError):
    """上游/业务错误（已翻译成 HTTP 语义与用户可读文案）。"""

    def __init__(self, status, message, code="", auth=False):
        super().__init__(message)
        self.status = int(status or 502)
        self.message = str(message or "")
        self.code = str(code or "")
        self.auth = bool(auth)


def _log(message, ctx=None):
    line = "loomy: %s" % message
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


def _session(account):
    return str(getattr(account, "access_token", "") or "")


def _compact_json(body):
    return json.dumps(body, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _business_code(payload):
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("code") or "").strip()


def _is_auth_code(code):
    return str(code or "").strip() in AUTH_ERROR_CODES


def _upstream_message(payload):
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("desc") or payload.get("message")
               or payload.get("msg") or "").strip()


def _error_text(status, payload, detail=""):
    message = _upstream_message(payload)
    if message:
        return message
    if detail:
        try:
            blob = json.loads(detail)
            message = _upstream_message(blob)
        except Exception:
            message = ""
        if message:
            return message
    return "HTTP %s" % status


# --------------------------------------------------------------- 签名（账号域）
#: 客户端 encodeURIComponent 后再转义 !'()*，最终等价 RFC3986 unreserved
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                  "0123456789-_.~")


def _escape_segment(segment):
    out = []
    for ch in segment:
        if ch in _UNRESERVED:
            out.append(ch)
        else:
            for byte in ch.encode("utf-8"):
                out.append("%%%02X" % byte)
    return "".join(out)


def build_escaped_path(path):
    """前导 /、去尾斜杠、逐段转义、以 / 连接（与客户端同口径）。"""
    clean = str(path or "")
    if not clean.startswith("/"):
        clean = "/" + clean
    if len(clean) > 1 and clean.endswith("/"):
        clean = clean[:-1]
    return "/".join(_escape_segment(part) for part in clean.split("/"))


def sign_headers(method, path, body_bytes):
    """客户端指纹复刻：CAccount 的 HMAC-SHA1 签名头。"""
    raw = body_bytes if isinstance(body_bytes, (bytes, bytearray)) else b""
    md5 = (base64.b64encode(hashlib.md5(raw).digest()).decode("ascii")
           if raw else "")
    date = formatdate(usegmt=True)
    nonce = str(uuid.uuid4())
    string_to_sign = "\n".join([
        str(method or "POST").upper(),
        build_escaped_path(path),
        "",
        md5,
        "application/json",
        date,
        nonce,
        "",
        "",
    ])
    digest = hmac.new(CFG["accessKeySecret"].encode("utf-8"),
                      string_to_sign.encode("utf-8"),
                      hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode("ascii")
    headers = {
        "Content-Type": "application/json",
        "Authorization": "account %s:%s" % (CFG["accessKeyId"], signature),
        "Date": date,
        "Nonce": nonce,
    }
    if md5:
        headers["Content-MD5"] = md5
    return headers


def _signed_post(path, body, what="请求", proxy="", timeout=REQUEST_TIMEOUT):
    """向账号域发一次签名 POST，返回 (status, payload)。"""
    data = _compact_json(body)
    headers = sign_headers("POST", path, data)
    request = urllib.request.Request(
        CFG["xfyunBase"].rstrip("/") + path, data=data, method="POST",
        headers=headers)
    request.wb_exact_headers = list(headers.items())
    try:
        with net.urlopen(request, timeout=timeout, proxy=proxy) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        raw = net.read_http_error(exc, 600).decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"message": raw[:500]}
    except Exception as exc:
        if net.is_tls_verify_error(exc):
            return 0, {"_error": net.tls_verify_hint(exc)}
        return 0, {"_error": "%s失败：%s" % (what, str(exc)[:240])}


def _token_request(method, path, session, body=None, what="请求",
                   proxy="", timeout=REQUEST_TIMEOUT, accept="application/json"):
    """向集成网关发一次 token 请求，返回 (status, payload)。

    目录/积分/每日福利在客户端只带 token；聊天才额外带 Bearer 和追踪头。
    """
    session = str(session or "").strip()
    if not session:
        return 401, {"message": "Loomy 账号缺少 session"}
    headers = {"Accept": accept, "token": session}
    if body is not None:
        headers["Content-Type"] = "application/json"
    data = _compact_json(body) if body is not None else None
    request = urllib.request.Request(
        CFG["integrationBase"].rstrip("/") + path, data=data,
        method=method or "GET", headers=headers)
    request.wb_exact_headers = list(headers.items())
    try:
        with net.urlopen(request, timeout=timeout, proxy=proxy) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return resp.status, None
    except urllib.error.HTTPError as exc:
        raw = net.read_http_error(exc, 600).decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"message": raw[:500]}
        if exc.code in (401, 403):
            payload = dict(payload or {})
            payload.setdefault("message", "%s：Loomy 登录态已失效，请重新登录"
                                          % what)
        return exc.code, payload
    except Exception as exc:
        if net.is_tls_verify_error(exc):
            return 0, {"_error": net.tls_verify_hint(exc)}
        return 0, {"_error": "%s失败：%s" % (what, str(exc)[:240])}


def _model_base():
    return CFG["integrationBase"].rstrip("/") + "/api/v1"


def _exit_proxy(ctx):
    """登录链按出口代理槽走：直连被 TLS 劫持时短信接口也会挂。"""
    try:
        from infra import settings
        for entry in settings.proxy_slots(ctx.accounts_dir, REALM):
            if entry.get("realm") and entry.get("enabled") is not False:
                return str(entry.get("url") or "")
    except Exception:
        pass
    return ""


# --------------------------------------------------------------- 登录
def _normalize_phone(raw):
    text = re.sub(r"[\s-]", "", str(raw or ""))
    if text.startswith("+86"):
        text = text[3:]
    if text.startswith("86") and len(text) == 13:
        text = text[2:]
    if (len(text) == 11 and text.startswith("1")
            and text[1] in "3456789" and text.isdigit()):
        return text
    raise LoomyError(400, "请填写 11 位中国大陆手机号")


def _normalize_code(raw):
    code = str(raw or "").strip()
    if len(code) == 6 and code.isdigit():
        return code
    raise LoomyError(400, "请填写 6 位数字验证码")


def _mask_phone(phone):
    text = str(phone or "")
    if len(text) >= 7:
        return "%s****%s" % (text[:3], text[-4:])
    return text


def _make_base():
    return {
        "appid": CFG["appId"],
        "modelid": WEB_MODEL_ID,
        "version": CLIENT_VERSION,
        "devid": WEB_DEVICE_ID,
        "ua": CLIENT_UA,
        "traceid": secrets.token_hex(16),
    }


def _extract_msgid(payload):
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else {}
    for value in (data.get("msgid"), data.get("msgId"),
                  inner.get("msgid"), inner.get("msgId")):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _send_code(phone, proxy=""):
    body = {"base": _make_base(),
            "param": {"ccode": "86", "phone": phone, "expire": 300}}
    status, payload = _signed_post("/login/phone/sendMsgCode", body,
                                   "发送验证码", proxy=proxy)
    payload = payload if isinstance(payload, dict) else {}
    if status == 0:
        raise LoomyError(502, (payload or {}).get("_error")
                         or "发送验证码失败：网络不通")
    code = _business_code(payload)
    if status != 200 or (code and code != SUCCESS_CODE):
        raise LoomyError(400, "发送验证码失败：%s"
                         % (_upstream_message(payload)
                            or ("上游 code=%s" % code if code else "HTTP %s" % status)),
                         code=code)
    msgid = _extract_msgid(payload)
    if not msgid:
        raise LoomyError(502, "验证码已发出但上游没有返回 msgid，请稍后重试")
    return msgid


def _login_with_code(phone, code, msgid, proxy=""):
    body = {
        "base": _make_base(),
        "param": {"ccode": "86", "phone": phone, "mcode": code,
                  "msgid": msgid, "expire": SESSION_DAYS * 24 * 3600},
    }
    status, payload = _signed_post("/login/phone/checkCode", body,
                                   "登录", proxy=proxy)
    payload = payload if isinstance(payload, dict) else {}
    if status == 0:
        raise LoomyError(502, (payload or {}).get("_error")
                         or "登录失败：网络不通")
    business = _business_code(payload)
    if status != 200 or (business and business != SUCCESS_CODE):
        raise LoomyError(400, "登录失败：%s"
                         % (_upstream_message(payload)
                            or ("上游 code=%s" % business
                                if business else "HTTP %s" % status)),
                         code=business)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    session = str(data.get("session") or data.get("token") or "").strip()
    if not session:
        raise LoomyError(502, "登录成功但上游没有返回 session")
    userid = str(data.get("userid") or data.get("userId") or "").strip()
    return session, userid


def _account_uid(userid, phone):
    raw = userid or ("phone-" + hashlib.sha256(phone.encode("utf-8")).hexdigest()[:12])
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in raw)
    return (safe or hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16])[:100]


def _login_account_from_account(account):
    meta = account.meta if isinstance(account.meta, dict) else {}
    value = str(meta.get("loginAccount") or "").strip()
    if value:
        return value
    uid = str(getattr(account, "uid", "") or "").strip()
    return uid if accounts_mod.looks_like_login_account(uid) else ""


def _save_account(ctx, phone, session, userid):
    uid = _account_uid(userid, phone)
    pool = getattr(ctx, "pool", None)
    existing = pool.get(uid) if pool is not None else None
    if existing is not None and existing.realm != REALM:
        # uid 与别家渠道撞名：加渠道前缀再哈希，避免覆盖别人的账号文件
        uid = "loomy-" + hashlib.sha256(uid.encode("utf-8")).hexdigest()[:16]
        existing = pool.get(uid) if pool is not None else None
    expires = int(time.time()) + SESSION_DAYS * 24 * 3600
    tail = _mask_phone(phone)
    meta = dict(getattr(existing, "meta", None) or {}) if existing else {}
    meta.update({
        "phoneTail": tail,
        "loginAccount": phone,
        "userId": userid,
        "loginAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sessionExpiresAt": expires,
    })
    if existing is not None:
        existing.access_token = session
        existing.refresh_token = ""
        existing.expires_at = expires
        existing.enabled = True
        existing.token_expired = False
        existing.meta = meta
        if not existing.nickname:
            existing.nickname = "手机 %s" % tail
        existing.clear_error()
        _save(existing)
        return existing
    account = accounts_mod.Account({
        "uid": uid,
        "nickname": "Loomy %s" % tail,
        "realm": REALM,
        "domain": DOMAIN,
        "platform": "CLI",
        "accessToken": session,
        "refreshToken": "",
        "expiresAt": expires,
        "source": "oauth",
        "enabled": True,
        "meta": meta,
    })
    if pool is not None:
        pool.add(account)
    else:
        account.save(ctx.accounts_dir)
    return account


def start_login(ctx):
    """生成一次两跳短信登录会话；发送验证码/提交由 login_action 完成。"""
    state = secrets.token_hex(16)
    now = time.time()
    with _LOGIN_LOCK:
        _LOGIN[state] = {"state": state, "status": "waiting", "msgid": "",
                         "phone": "", "phoneTail": "", "created": now,
                         "proxy": _exit_proxy(ctx)}
        for key in list(_LOGIN):
            if now - _LOGIN[key].get("created", 0) > LOGIN_TTL + 120:
                _LOGIN.pop(key, None)
    return {
        "ok": True,
        "state": state,
        "realm": REALM,
        "paste": False,
        "hint": "输入手机号并获取验证码，验证后自动入池（登录态 14 天，"
                "上游没有续期接口，过期需重新短信登录）",
        "form": {
            "type": "sms",
            "title": "手机号验证码登录",
            "hint": "验证码由讯飞账号系统发送；登录态 14 天，上游无续期，"
                    "过期需重新短信登录。",
            "fields": [
                {"key": "phone", "label": "手机号",
                 "placeholder": "11 位中国大陆手机号",
                 "maxlength": 11, "inputmode": "tel",
                 "autocomplete": "tel"},
                {"key": "code", "label": "验证码",
                 "placeholder": "6 位数字",
                 "maxlength": 6, "inputmode": "numeric",
                 "autocomplete": "one-time-code"},
            ],
            "sendAction": "send_code",
            "sendLabel": "发送验证码",
            "submitAction": "submit",
            "submitLabel": "登录",
        },
    }


def _login_session(state):
    with _LOGIN_LOCK:
        return _LOGIN.get(str(state or ""))


def login_action(ctx, state, action, payload):
    session = _login_session(state)
    if session is None:
        return None
    payload = payload if isinstance(payload, dict) else {}
    if time.time() - session.get("created", 0) > LOGIN_TTL:
        session["status"] = "expired"
        return {"ok": False, "status": "expired",
                "message": "登录会话已超时（15 分钟），请重新点击「登录账号」"}
    action = str(action or "")

    if action == "send_code":
        try:
            phone = _normalize_phone(payload.get("phone"))
        except LoomyError as exc:
            return {"ok": False, "message": exc.message}
        try:
            msgid = _send_code(phone, proxy=session.get("proxy") or "")
        except LoomyError as exc:
            return {"ok": False, "message": exc.message}
        with _LOGIN_LOCK:
            session["phone"] = phone
            session["phoneTail"] = _mask_phone(phone)
            session["msgid"] = msgid
            session["status"] = "waiting"
        return {"ok": True, "sent": True,
                "message": "验证码已发送（尾号 %s），10 分钟内有效"
                           % _mask_phone(phone)}

    if action == "submit":
        phone_raw = payload.get("phone") or session.get("phone") or ""
        try:
            phone = _normalize_phone(phone_raw)
            code = _normalize_code(payload.get("code"))
        except LoomyError as exc:
            return {"ok": False, "message": exc.message}
        msgid = str(session.get("msgid") or "").strip()
        if not msgid:
            return {"ok": False, "message": "请先点击「发送验证码」获取本次登录的 msgid"}
        if session.get("phone") and phone != session.get("phone"):
            return {"ok": False, "message": "手机号与发送验证码时不一致，请重新发码"}
        try:
            session_token, userid = _login_with_code(
                phone, code, msgid, proxy=session.get("proxy") or "")
        except LoomyError as exc:
            return {"ok": False, "message": exc.message}
        try:
            account = _save_account(ctx, phone, session_token, userid)
        except Exception as exc:
            return {"ok": False, "message": "账号入池失败：%s" % str(exc)[:200]}
        refresh = refresh_daily(account, proxy=session.get("proxy") or "")
        if refresh.get("ok"):
            account.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
            _save(account)
            message = "Loomy 账号已登录并入池（%s），%s" % (
                account.nickname, refresh.get("message") or "每日赠送积分已刷新")
        else:
            message = "Loomy 账号已登录并入池（%s）；每日积分刷新暂未完成：%s" % (
                account.nickname, refresh.get("message") or refresh.get("error") or "未知原因")
        with _LOGIN_LOCK:
            session["status"] = "ok"
            session["message"] = message
            session["uid"] = account.uid
        return {"ok": True, "status": "ok", "uid": account.uid,
                "message": message}

    if action in ("cancel", "close"):
        login_cancel(ctx, state)
        return {"ok": True, "status": "cancelled", "message": "已取消登录"}

    return {"ok": False, "message": "不支持的登录动作：%s" % action}


def login_poll(ctx, state):
    session = _login_session(state)
    if session is None:
        return None
    status = session.get("status") or "waiting"
    if status == "ok":
        return {"status": "ok", "message": session.get("message") or "登录成功",
                "uid": session.get("uid") or ""}
    if time.time() - session.get("created", 0) > LOGIN_TTL:
        session["status"] = "expired"
        return {"status": "expired", "message": "登录会话已超时（15 分钟），请重新发起"}
    return {"status": "pending",
            "message": "等待输入手机号与验证码…"}


def login_cancel(ctx, state):
    with _LOGIN_LOCK:
        if str(state or "") not in _LOGIN:
            return None
        _LOGIN.pop(str(state), None)
    return {"ok": True}


def reset_caches():
    with _MODEL_LOCK:
        _MODEL_CACHE["at"] = 0.0
        _MODEL_CACHE["models"] = []
    with _CREDITS_LOCK:
        _CREDITS_CACHE.clear()
    with _LOGIN_LOCK:
        _LOGIN.clear()


# --------------------------------------------------------------- 登录态
def _mark_session_dead(account, message=""):
    account.token_expired = True
    account.last_error = message or (
        "Loomy 登录态已失效（14 天到期或上游注销），请重新短信登录")


def _session_alive(account):
    """session 是否需要重新短信登录；无续期语义（上游没有 refresh 接口）。"""
    token = _session(account)
    if not token:
        return False
    if getattr(account, "token_expired", False):
        return False
    try:
        expires = float(getattr(account, "expires_at", 0) or 0)
    except (TypeError, ValueError):
        expires = 0.0
    if expires and expires <= time.time():
        _mark_session_dead(account, "Loomy 登录态已过期（14 天），请重新短信登录")
        return False
    return True


# --------------------------------------------------------------- 模型目录
def _split_rate_suffix(name):
    """展示名尾部 x3.0 / (x3.0) / （x12）→ (纯名称, "x3.0")；其余原样。"""
    text = str(name or "").rstrip()
    match = re.search(r"\s+[xX](\d+(?:\.\d+)?)\s*$", text)
    if match:
        return (text[:match.start()].rstrip() or text), "x" + match.group(1)
    if text.endswith(")") or text.endswith("）"):
        open_char = "(" if text.endswith(")") else "（"
        open_at = text.rfind(open_char)
        if open_at >= 0:
            body = text[:open_at].rstrip()
            inner = text[open_at + 1:-1].strip()
            if body and re.fullmatch(r"[xX]\d+(?:\.\d+)?", inner):
                return body, "x" + inner[1:]
    return text, ""


# 客户端 model-metadata 的上下文覆盖表（键为上游模型 id）。
MODEL_CONTEXT_OVERRIDES = {"spark-x": 262144}


def _positive_int(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(number) or number <= 0:
        return 0
    return int(number)


def _first_present(mapping, keys):
    for key in keys:
        if isinstance(mapping, dict) and key in mapping \
                and mapping[key] is not None:
            return mapping[key]
    return None


def _map_entry(row):
    """目录条目 → 归一形态；字段口径与客户端 model-metadata 对齐。"""
    if not isinstance(row, dict):
        return None
    model_id = str(row.get("id") or "").strip()
    if not model_id:
        return None
    protocol = str(row.get("protocol") or "").strip().lower()
    if protocol in ("anthropic", "anthropic_messages"):
        return None
    if str(row.get("type") or "").strip().lower() == "image":
        # 本代理只有 chat/completions，图片生成模型不可用
        return None
    raw_name = str(row.get("displayName") or row.get("name") or "").strip() \
        or model_id
    name, rate = _split_rate_suffix(raw_name)
    caps = row.get("capabilities") if isinstance(
        row.get("capabilities"), dict) else {}
    caps_out = caps.get("output_modalities") if isinstance(
        caps.get("output_modalities"), list) else []
    if caps_out and "text" not in {str(item).lower() for item in caps_out}:
        return None
    modalities = row.get("modalities") if isinstance(
        row.get("modalities"), dict) else {}
    # 客户端优先取 modalities.input，缺失时才看 capabilities.input_modalities
    modal_input = modalities.get("input") if isinstance(
        modalities.get("input"), list) else None
    if modal_input is None:
        modal_input = caps.get("input_modalities") if isinstance(
            caps.get("input_modalities"), list) else []
    modal_names = {str(item).lower() for item in modal_input}
    vision = bool(row.get("attachment") is True
                  or row.get("supports_image_in") is True
                  or row.get("supports_video_in") is True
                  or caps.get("vision") is True
                  or modal_names & {"image", "video", "pdf"})
    # 0.9.39 的真实目录没有顶层 reasoning，只带 capabilities.reasoning；
    # 客户端 normalizer 不读它，但代理目录需要把上游真实能力暴露给下游客户端。
    reasoning = bool(row.get("reasoning") is True
                     or row.get("supports_reasoning") is True
                     or caps.get("reasoning") is True)
    tools = bool(row.get("tool_call") is True
                 or caps.get("function_calling") is True)
    limit = row.get("limit") if isinstance(row.get("limit"), dict) else {}
    context = MODEL_CONTEXT_OVERRIDES.get(model_id)
    if context is None:
        context = _positive_int(_first_present(limit, ["context"])) or \
            _positive_int(_first_present(row, ["context_length", "contextWindow"]))
    output = _positive_int(_first_present(limit, ["output"])) or \
        _positive_int(_first_present(
            row, ["max_output_tokens", "max_completion_tokens"]))
    meta = {
        "name": name,
        "supportsImages": vision,
        "supportsToolCall": tools,
        "supportsReasoning": reasoning,
        "context_length": _positive_int(context),
        "max_output_tokens": output,
        "vendor": "Loomy",
        "source": "live",
    }
    if rate:
        meta["credits"] = rate
    return {"id": model_id, "meta": meta}


def _parse_models(payload):
    if isinstance(payload, dict):
        rows = payload.get("data")
    else:
        rows = payload
    if not isinstance(rows, list):
        return []
    entries = []
    seen = set()
    for row in rows:
        entry = _map_entry(row)
        if entry is None or entry["id"] in seen:
            continue
        seen.add(entry["id"])
        entries.append(entry)
    return entries


def _model_accounts(ctx):
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return []
    return [account for account in pool.accounts
            if account.realm == REALM and account.enabled
            and _session_alive(account)]


def fetch_models(ctx=None, force=False):
    """拉一次 /api/v1/models；force=True 只认上游（不返回旧缓存）。"""
    now = time.time()
    with _MODEL_LOCK:
        if (not force and _MODEL_CACHE["models"]
                and now - _MODEL_CACHE["at"] <= MODEL_CACHE_TTL):
            return list(_MODEL_CACHE["models"])
    last_message = ""
    for account in _model_accounts(ctx)[:3]:
        status, payload = _token_request(
            "GET", "/api/v1/models", _session(account), what="模型目录查询",
            proxy=getattr(account, "proxy", "") or "")
        payload = payload if isinstance(payload, (dict, list)) else {}
        code = _business_code(payload)
        if status in (401, 403) or _is_auth_code(code):
            _mark_session_dead(account)
            last_message = "Loomy 登录态已失效，请重新短信登录"
            continue
        if status == 0:
            last_message = (payload or {}).get("_error") or "网络不通"
            continue
        if status != 200:
            last_message = "模型目录返回 HTTP %s：%s" % (
                status, _error_text(status, payload))
            continue
        entries = _parse_models(payload)
        if not entries:
            last_message = "Loomy 模型目录为空或格式不认识（保留现有清单）"
            continue
        with _MODEL_LOCK:
            _MODEL_CACHE["at"] = now
            _MODEL_CACHE["models"] = entries
        return list(entries)
    if force:
        return []
    with _MODEL_LOCK:
        if _MODEL_CACHE["models"]:
            return list(_MODEL_CACHE["models"])
    if last_message:
        _log(last_message, ctx)
    return []


def live_models(realm, force=False, ctx=None):
    if str(realm or "") != REALM:
        return []
    return [(entry["id"], entry["meta"]) for entry in fetch_models(ctx, force)]


# --------------------------------------------------------------- 积分 / 福利
def _pick_points(data, key):
    value = data.get(key) if isinstance(data, dict) else None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip() != "":
        try:
            return float(value)
        except ValueError:
            return None
    return None


def query_balance(account, proxy=""):
    if not _session_alive(account):
        return {"ok": False, "authError": True,
                "message": "Loomy 登录态已过期，请重新短信登录"}
    status, payload = _token_request(
        "GET",
        "/api/v2/points/records?pageNo=1&pageSize=1&direction=debit"
        "&granularity=chat",
        _session(account), what="积分查询", proxy=proxy)
    payload = payload if isinstance(payload, dict) else {}
    code = _business_code(payload)
    if status in (401, 403) or _is_auth_code(code):
        _mark_session_dead(account, "Loomy 登录态已失效，无法查询积分"
                                   "（请重新短信登录）")
        return {"ok": False, "authError": True,
                "message": "Loomy 登录态已失效，无法查询积分（请重新短信登录）"}
    if status == 0:
        return {"ok": False, "error": (payload or {}).get("_error")
                or "积分查询失败：网络不通"}
    if status != 200:
        return {"ok": False, "error": "积分查询失败：HTTP %s %s"
                % (status, _error_text(status, payload))}
    if code and code != SUCCESS_CODE:
        return {"ok": False, "error": "积分查询失败：%s"
                % (_upstream_message(payload) or "上游 code=%s" % code)}
    outer = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data = outer.get("data") if isinstance(outer.get("data"), dict) else outer
    permanent = _pick_points(data, "balance") or 0
    daily = _pick_points(data, "dailyBalance") or 0
    daily_remaining = _pick_points(data, "dailyRemainingPoints")
    daily_limit = _pick_points(data, "dailyLimitPoints")
    wallets = [
        {"type": "permanent_points", "displayName": "永久积分",
         "balance": permanent, "unit": "积分"},
        {"type": "daily_points", "displayName": "每日赠送积分",
         "balance": daily, "unit": "积分"},
    ]
    if daily_remaining is not None and daily_limit is not None:
        wallets[1]["remaining"] = daily_remaining
        wallets[1]["limit"] = daily_limit
    packages = []
    for wallet in wallets:
        packages.append({
            "package_code": wallet["type"],
            "name": wallet["displayName"],
            "remain": wallet["balance"],
            "size": None,
            "unit": "积分",
            "no_expiry": True,
            "is_expired": False,
        })
    return {
        "ok": True,
        "available": permanent + daily,
        "unit": "积分",
        "wallets": wallets,
        "packages": packages,
        "credits": {
            "remain": permanent + daily,
            "size": None,
            "unlimited": False,
            "packages": packages,
            "wallets": wallets,
            "is_paid_user": False,
            "updated_at": time.time(),
            "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    }


def credits_for_account(account, force=False):
    key = (REALM, str(getattr(account, "uid", "") or ""))
    now = time.time()
    with _CREDITS_LOCK:
        hit = _CREDITS_CACHE.get(key)
        if hit and not force and now - hit[0] <= CREDITS_TTL:
            return {"ok": True, "credits": copy.deepcopy(hit[1]),
                    "cached": True}
    result = query_balance(account, proxy=getattr(account, "proxy", "") or "")
    if not result.get("ok"):
        return result
    credits = result["credits"]
    account.credits = credits
    _save(account)
    with _CREDITS_LOCK:
        _CREDITS_CACHE[key] = (now, copy.deepcopy(credits))
    return {"ok": True, "credits": credits}


def refresh_daily(account, proxy=""):
    """POST first-login：把每日赠送积分刷回 5000（上游按天幂等）。"""
    if not _session_alive(account):
        return {"ok": False, "authError": True,
                "message": "Loomy 登录态已过期，请重新短信登录"}
    status, payload = _token_request(
        "POST", "/api/v1/points/first-login", _session(account),
        body={}, what="每日积分刷新", proxy=proxy)
    payload = payload if isinstance(payload, dict) else {}
    code = _business_code(payload)
    if status in (401, 403) or _is_auth_code(code):
        _mark_session_dead(account, "Loomy 登录态已失效，无法刷新每日积分"
                                   "（请重新短信登录）")
        return {"ok": False, "authError": True,
                "message": "Loomy 登录态已失效，无法刷新每日积分（请重新短信登录）"}
    if status == 0:
        return {"ok": False, "message": (payload or {}).get("_error")
                or "每日积分刷新失败：网络不通"}
    if status != 200:
        return {"ok": False, "message": "每日积分刷新失败：HTTP %s %s"
                % (status, _error_text(status, payload))}
    if code != SUCCESS_CODE:
        return {"ok": False, "message": "每日积分刷新失败：%s"
                % (_upstream_message(payload)
                   or "上游 code=%s" % (code or "空"))}
    outer = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    inner = outer.get("data") if isinstance(outer.get("data"), dict) else outer
    daily = _pick_points(inner, "dailyBalance")
    message = ("每日赠送积分已刷新（当前 %s）" % int(daily)
               if daily is not None else "每日赠送积分已刷新")
    return {"ok": True, "message": message,
            "credit": daily if daily is not None else None}


def checkin_for_account(account, trigger="unknown"):
    result = refresh_daily(account, proxy=getattr(account, "proxy", "") or "")
    if not result.get("ok"):
        return result
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


def probe_account(account, timeout=20):
    if not _session_alive(account):
        return {"ok": False, "message": "Loomy 登录态已过期，请重新短信登录"}
    started = time.time()
    status, payload = _token_request(
        "GET", "/api/v1/models", _session(account), what="连通性探测",
        proxy=getattr(account, "proxy", "") or "", timeout=timeout)
    payload = payload if isinstance(payload, (dict, list)) else {}
    code = _business_code(payload)
    if status in (401, 403) or _is_auth_code(code):
        _mark_session_dead(account)
        return {"ok": False, "message": "Loomy 登录态已失效，请重新短信登录"}
    if status != 200:
        return {"ok": False, "code": status,
                "message": "连接探测失败：HTTP %s %s"
                           % (status, _error_text(status, payload))}
    count = len(_parse_models(payload))
    if not count:
        return {"ok": False, "message": "上游目录为空，无法确认账号可用"}
    elapsed = int((time.time() - started) * 1000)
    return {"ok": True, "latencyMs": elapsed, "models": count,
            "message": "Loomy 账号连通正常（%d 个模型，%d ms）" % (count, elapsed)}


# --------------------------------------------------------------- 对话
def _delta_has_content(delta):
    if not isinstance(delta, dict):
        return False
    content = delta.get("content")
    if isinstance(content, str) and content:
        return True
    if isinstance(content, list) and any(
            isinstance(part, dict) and str(part.get("text") or "")
            for part in content):
        return True
    if str(delta.get("reasoning_content") or ""):
        return True
    return bool(delta.get("tool_calls"))


def _frame_fault(frame):
    """流内错误信封：OpenAI error 对象 / 业务码 020002、100002。"""
    if not isinstance(frame, dict):
        return None
    error = frame.get("error")
    if isinstance(error, dict) and error:
        code = str(error.get("code") or error.get("error_code") or "")
        message = str(error.get("message") or error.get("msg")
                      or error.get("error_msg") or "上游返回错误")
        if _is_auth_code(code) or code in ("401", "403"):
            return {"status": 401, "message": message, "code": code}
        if code == "429":
            return {"status": 429, "message": message, "code": code}
        return {"status": 502, "message": message, "code": code}
    if isinstance(error, str) and error.strip():
        return {"status": 502, "message": error.strip(), "code": ""}
    code = _business_code(frame)
    if _is_auth_code(code):
        return {"status": 401,
                "message": _upstream_message(frame) or "Loomy 登录态已失效",
                "code": code}
    choices = frame.get("choices")
    if code and code != SUCCESS_CODE and not choices:
        return {"status": 502,
                "message": _upstream_message(frame) or "上游业务码 %s" % code,
                "code": code}
    return None


class LoomyStream(object):
    """OpenAI 兼容 SSE 透传 + 错误信封/空流判定 + 首包门。

    核心消费面（core/proxy_api + core/streaming）会 for line in upstream +
    clean_chunk + aggregate_stream，还会 with upstream: 关连接，本 wrapper
    完整实现 __iter__ / read / __enter__ / __exit__。
    """

    def __init__(self, resp, model, account, url, log=None):
        self._resp = resp
        self._model = model
        self._account = account
        self._url = url
        self._log = log
        self._buf = b""
        self._done = False
        self._closed = False
        self._pending = []
        self._error = None
        self._produced = False
        self._saw_answer = False
        self._finish_seen = False
        self._usage = None
        self._created = int(time.time())
        self._chat_id = "chatcmpl-loomy-" + secrets.token_hex(6)

    # ---- 底层读取 ----
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

    def _read_event(self):
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
            if text.startswith("data:"):
                data_lines.append(text[5:].strip())
        if not data_lines:
            return None
        return "\n".join(data_lines)

    def _finish_chunk(self):
        chunk = {
            "id": self._chat_id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self._model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        if self._usage is not None:
            chunk["usage"] = self._usage
        return chunk

    def _fail(self, fault):
        status = int(fault.get("status") or 502)
        message = str(fault.get("message") or "Loomy 上游返回错误")
        if status == 401:
            _mark_session_dead(
                self._account,
                "Loomy 登录态已失效（流内错误），请重新短信登录")
            text = "Loomy 登录态已失效：%s" % message
        elif status == 429:
            self._account.note_error("Loomy 限流（流内 429）", cooldown=60)
            text = "Loomy 上游限流：%s" % message
        else:
            self._account.note_failure("流内错误：%s" % message[:120])
            text = "Loomy 上游错误：%s" % message
        self._done = True
        self._pending.append({"error": {
            "message": text,
            "type": "authentication_error" if status == 401 else "upstream_error",
            "code": status,
        }})
        error = urllib.error.HTTPError(self._url, status, text, None, None)
        error.upstream_code = str(fault.get("code") or "")
        self._error = error

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
            data = self._read_event()
            if data is None:
                if not self._saw_answer:
                    self._fail({
                        "status": 502,
                        "message": "Loomy 上游返回了空回答（流结束但没有任何内容）",
                    })
                    continue
                self._done = True
                if not self._finish_seen:
                    self._pending.append(self._finish_chunk())
                continue
            if data.strip() == "[DONE]":
                if not self._saw_answer:
                    self._fail({
                        "status": 502,
                        "message": "Loomy 上游返回了空回答（只有 [DONE]，没有任何内容）",
                    })
                    continue
                self._done = True
                if not self._finish_seen:
                    self._pending.append(self._finish_chunk())
                continue
            try:
                frame = json.loads(data)
            except Exception:
                continue
            if not isinstance(frame, dict):
                continue
            fault = _frame_fault(frame)
            if fault is not None:
                self._fail(fault)
                continue
            if frame.get("usage") is not None:
                self._usage = frame.get("usage")
            for choice in frame.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta") if isinstance(
                    choice.get("delta"), dict) else {}
                if _delta_has_content(delta) \
                        or str(choice.get("text") or "").strip():
                    self._saw_answer = True
                    self._produced = True
                if choice.get("finish_reason"):
                    self._finish_seen = True
            return frame

    @property
    def error(self):
        return self._error

    def prime(self):
        """读到首个可用增量（或确认失败）后再交出流：未出内容时还能换号。"""
        return registry.prime_stream(self)

    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        chunk = self._next_chunk()
        if chunk is None:
            raise StopIteration
        return ("data: " + json.dumps(chunk, ensure_ascii=False)
                + "\n\n").encode("utf-8")

    def read(self, n=-1):
        if self._closed:
            return b""
        parts = []
        total = 0
        for line in self:
            parts.append(line)
            total += len(line)
            if n is not None and n > 0 and total >= n:
                break
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


def _retry_after(headers):
    try:
        value = float((headers or {}).get("Retry-After") or 0)
        return min(300.0, max(1.0, value))
    except Exception:
        return 60.0


def _http_error(url, status, message):
    return urllib.error.HTTPError(url, int(status), str(message), None, None)


def _classify_http(status, payload, detail=""):
    code = _business_code(payload)
    message = _error_text(status, payload, detail)
    if status in (401, 403) or _is_auth_code(code):
        return "auth", 401, message
    if status == 402:
        return "credit", 402, message
    if status == 429:
        return "rate", 429, message
    if status in (400, 413):
        return "fatal", status, message
    return "other", int(status or 502), message


def _traceparent():
    return "00-%s-%s-01" % (secrets.token_hex(16), secrets.token_hex(8))


def _chat_id(session_key):
    clean = re.sub(r"[^A-Za-z0-9_-]", "", str(session_key or ""))[:128]
    return clean or ("chat-" + uuid.uuid4().hex)


def _post_chat(account, url, data, header_timeout, connect_timeout, idle_timeout,
               chat_id="", msg_id="", turn_id=""):
    session = _session(account)
    headers = [
        ("Content-Type", "application/json"),
        ("Accept", "text/event-stream"),
        ("token", session),
        ("Authorization", "Bearer " + session),
        ("traceparent", _traceparent()),
        ("loomy-version", APP_VERSION),
        ("InvokeOrigin", "user"),
        ("X-Loomy-Request-Purpose", CHAT_PURPOSE),
    ]
    if chat_id:
        headers.append(("ChatId", chat_id))
    if msg_id:
        headers.append(("MsgId", msg_id))
    if msg_id or turn_id:
        headers.append(("TurnId", turn_id or msg_id))
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers=dict(headers))
    request.wb_exact_headers = headers
    resp = net.urlopen(request, timeout=header_timeout,
                       proxy=getattr(account, "proxy", "") or "",
                       connect_timeout=connect_timeout)
    net.set_stream_idle_timeout(resp, idle_timeout)
    return resp


def open_stream(ctx, payload, session_key=None, realm=None):
    """选号 → 目录解析 → 双头 SSE → 首包门 → 交出流。"""
    pool = getattr(ctx, "pool", None)
    realm = realm or REALM
    model = str(payload.get("model") or "").strip()
    if model.lower().startswith(REALM + "/"):
        model = model[len(REALM) + 1:].strip()
    if not model:
        raise RuntimeError("loomy: empty model")
    entries = fetch_models(ctx)
    if not entries:
        raise _http_error(
            _model_base() + "/chat/completions", 503,
            "Loomy 模型目录还没拉取到：请先在模型页对该账号执行一次"
            "「刷新模型清单」")
    entry = next((item for item in entries
                  if str(item.get("id") or "").lower() == model.lower()), None)
    if entry is None:
        raise _http_error(
            _model_base() + "/chat/completions", 404,
            "Loomy 目录里没有模型「%s」（大小写已归一，仍匹配不到）" % model)
    upstream_model = entry["id"]
    url = _model_base() + "/chat/completions"
    realm_accounts = [account for account in (pool.accounts if pool else [])
                      if account.realm == realm and account.enabled]
    if realm_accounts and not any(_session_alive(account)
                                  for account in realm_accounts):
        # 池子不会把「登录态已死」的号交给开流循环：这里直接把 401 说清楚，
        # 否则调用方只会看到「没有可用账号」的 503。
        raise _http_error(
            url, 401,
            "Loomy 账号登录态均已失效（14 天到期或上游注销），请重新短信登录")

    body = upstream_body.build_upstream_body(dict(payload), ctx.system_prompt)
    body["model"] = upstream_model
    body["stream"] = True
    data = upstream_body.encode_upstream_body(body)
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    connect_timeout = ctx.upstream_connect_timeout()
    total = max(1, pool.count_ready(realm=realm, model=model)) if pool else 1
    attempts, deadline = net.request_budget(total + 1)
    tried = set()
    last_error = None
    last_429 = None
    last_429_detail = ""
    chat_id = _chat_id(session_key)
    msg_id = "msg-" + uuid.uuid4().hex

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        account = pool.pick_for_session(
            realm=realm, session_key=session_key, exclude=tried,
            model=model) if pool else None
        if account is None:
            break
        if account.realm != realm:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        if not _session_alive(account):
            last_error = _http_error(
                url, 401,
                "Loomy 账号 %s 登录态已失效（14 天到期或上游注销），"
                "请重新短信登录" % str(account.uid)[:8])
            continue

        try:
            response = _post_chat(account, url, data, header_timeout,
                                  connect_timeout, idle_timeout,
                                  chat_id=chat_id, msg_id=msg_id,
                                  turn_id=msg_id)
        except urllib.error.HTTPError as exc:
            detail = net.read_http_error(exc, 600).decode("utf-8", "replace")
            try:
                blob = json.loads(detail)
            except Exception:
                blob = {}
            kind, status, message = _classify_http(exc.code, blob, detail)
            if kind == "auth":
                _mark_session_dead(
                    account, "Loomy 登录态已失效，请重新短信登录")
                last_error = _http_error(
                    url, 401,
                    "Loomy 账号 %s 登录态已失效，请重新短信登录" %
                    str(account.uid)[:8])
            elif kind == "credit":
                account.note_balance_cooled("Loomy 积分不足（HTTP 402）",
                                            detail=detail)
                last_error = exc
            elif kind == "rate":
                wait = _retry_after(getattr(exc, "headers", None))
                account.note_error("Loomy 限流（HTTP 429）", cooldown=wait,
                                   detail=detail)
                last_error, last_429 = exc, exc
                last_429_detail = detail
            elif kind == "fatal":
                raise _http_error(
                    url, status, "Loomy 上游拒绝请求（%s）：%s"
                                 % (status, message[:300]))
            else:
                account.note_failure("HTTP %s：%s" % (exc.code, message[:120]))
                last_error = exc
            if session_key and pool:
                pool.affinity.unbind(session_key)
            _log("account %s failed HTTP %s (%s), rotating"
                 % (str(account.uid)[:8], exc.code, message[:100]), ctx)
            continue
        except Exception as exc:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            if net.looks_like_local_network(exc):
                _log("account %s local network failure (%s), no penalty"
                     % (str(account.uid)[:8], type(exc).__name__), ctx)
            elif net.is_transient(exc):
                account.note_unknown_failure(
                    "connection: %s" % type(exc).__name__)
                _log("account %s upstream connection hiccup (%s), rotating"
                     % (str(account.uid)[:8], type(exc).__name__), ctx)
            else:
                account.note_unknown_failure(str(exc)[:120])
                account.note_error(str(exc)[:120], cooldown=60)
            last_error = exc
            continue

        content_type = str(getattr(response, "headers", {}).get("Content-Type")
                           or "").lower()
        if "application/json" in content_type:
            # 有的中间层会把错误信封塞进 HTTP 200 的 JSON 响应里（不是 SSE）
            try:
                raw = response.read(4000).decode("utf-8", "replace")
            except Exception:
                raw = ""
            try:
                response.close()
            except Exception:
                pass
            try:
                blob = json.loads(raw)
            except Exception:
                blob = {}
            kind, status, message = _classify_http(200, blob, raw)
            if kind == "auth":
                _mark_session_dead(
                    account, "Loomy 登录态已失效，请重新短信登录")
                last_error = _http_error(
                    url, 401, "Loomy 账号 %s 登录态已失效，请重新短信登录"
                    % str(account.uid)[:8])
            elif kind == "credit":
                account.note_balance_cooled("Loomy 积分不足", detail=raw)
                last_error = _http_error(url, 402, message)
            elif kind == "rate":
                account.note_error("Loomy 限流", cooldown=60, detail=raw)
                last_error = _http_error(url, 429, message)
            elif kind == "fatal":
                raise _http_error(url, status, message)
            else:
                account.note_failure("JSON 错误信封：%s" % message[:120])
                last_error = _http_error(url, 502, message)
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue

        stream = LoomyStream(response, model, account, url, log=ctx.log)
        try:
            verdict = stream.prime()
        except Exception as exc:
            stream.close()
            error = stream.error or exc
            status = int(getattr(error, "code", 0) or 502)
            if status in (400, 413):
                raise error
            last_error = error
            _log("account %s stream prime failed (%s), rotating"
                 % (str(account.uid)[:8], type(exc).__name__), ctx)
            continue
        if verdict != "ready":
            stream.close()
            error = stream.error
            status = int(getattr(error, "code", 0) or 502)
            message = str(error) if error is not None else "上游没有返回可用内容"
            if status in (400, 413):
                raise error or _http_error(url, status, message)
            if status == 429:
                last_error, last_429 = error, error
                last_429_detail = message
            else:
                last_error = _http_error(
                    url, status, "Loomy 账号 %s：%s（已自动换号）"
                                 % (str(account.uid)[:8], message))
            if session_key and pool:
                pool.affinity.unbind(session_key)
            _log("account %s failed before content: HTTP %s %s"
                 % (str(account.uid)[:8], status, message[:120]), ctx)
            continue
        account.note_success(model=model)
        return (stream, {
            "account": account.uid,
            "realm": REALM,
            "account_obj": account,
            "egress_key": upstream_pool.egress_key(
                url, getattr(account, "proxy", "") or ""),
        })

    if last_429 is not None:
        exc = ratelimit.RateLimited(
            last_429, last_429_detail,
            wait=int(_retry_after(getattr(last_429, "headers", None))))
        exc.account_uid = None
        raise exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or have expired sessions" % REALM)


# ===========================================================================
# 渠道适配器
# ===========================================================================
def _refresh_account(account):
    if _session_alive(account):
        return True
    account.token_expired = True
    account.last_error = ("Loomy 登录态 14 天有效、上游没有续期接口，"
                          "请重新短信登录")
    return False


def _run_daily(account, source):
    result = checkin_for_account(
        account, trigger="scheduler" if source == "auto" else "manual")
    if result.get("ok"):
        return {"status": "ok", "message": result.get("message")
                or "每日赠送积分已刷新"}
    return {"status": "error",
            "message": result.get("message") or result.get("error")
            or "每日积分刷新失败"}


def scheduler_tasks(ctx):
    def run(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="loomy_daily_points", source=source,
            ready=lambda acc: (acc.realm == REALM and acc.enabled
                               and _session_alive(acc)),
            action=lambda acc: _run_daily(acc, source), realm=REALM)

    return [("loomy_daily_points", "Loomy 每日积分刷新", run,
             {"enabled": True, "hours": [7, 12], "realm": REALM})]


class LoomyAdapter(registry.ChannelAdapter):
    id = REALM
    label = LABEL
    realms = (REALM,)
    route_prefixes = (REALM,)
    capabilities = frozenset({
        registry.CAP_CHAT, registry.CAP_MODELS, registry.CAP_ACCOUNTS,
        registry.CAP_CHECKIN, registry.CAP_SCHEDULER, registry.CAP_PROXY_SLOT,
    })

    def __init__(self):
        self._ctx = None

    def register(self, ctx):
        self._ctx = ctx
        accounts_mod.register_realm_config(REALM, {
            "name": LABEL,
            "domain": DOMAIN,
            "has_checkin": True,
            "has_daily_chat": False,
            "refresh_fn": _refresh_account,
            "credits_fn": credits_for_account,
            "checkin_fn": checkin_for_account,
            "probe_fn": probe_account,
            "login_account_fn": _login_account_from_account,
        })

    # ---- 短信登录（两跳：发码 → 验码）----
    def start_login(self, ctx, realm, platform="CLI"):
        if realm != REALM:
            return None
        return start_login(ctx)

    def login_action(self, ctx, state, action, payload):
        return login_action(ctx, state, action, payload)

    def poll_login(self, ctx, state):
        return login_poll(ctx, state)

    def cancel_login(self, ctx, state):
        return login_cancel(ctx, state)

    # ---- 代理链路 ----
    def open_stream(self, ctx, payload, session_key=None, realm=None):
        return open_stream(ctx, payload, session_key=session_key,
                           realm=realm or REALM)

    def live_models(self, realm, force=False):
        return live_models(realm, force=force, ctx=self._ctx)

    # ---- 任务 ----
    def scheduler_tasks(self, ctx):
        return scheduler_tasks(ctx)

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
                "desktop_import": False,
            }],
            "capabilities": sorted(self.capabilities),
            "frontend": REALM,
            "enabled": True,
            "checkin_labels": {
                "action": "刷新积分",
                "pending": "今日未刷新",
                "done": "今日已刷新",
                "pendingTitle": "今日尚未刷新每日赠送积分"
                               "（「刷新积分」按钮或定时任务会补上）",
                "doneTitle": "今日已刷新：",
                "submitted": "每日积分刷新已提交",
            },
        }


def install(ctx):
    """注册本渠道（入口调用；新增渠道照此一行接入）。"""
    registry.register(LoomyAdapter(), ctx)
