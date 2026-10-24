# -*- coding: utf-8 -*-
"""integrations/codearts.py —— CodeArts（华为云码道）反代渠道

协议事实来自 AgentHub v1.82.2 的 codearts 适配器（Copyright (c) 2026 沐晖
(HUIdada1)，MIT + 附加使用条款；本文件为独立 Python 实现，仅移植行为口径，
不复制其源码结构。上游版权与附加条款见 AgentHub LICENSE，仅限自用）：

- 登录：OAuth 授权码 + PKCE（portal 只认 challenge 方法名 "SHA-256"）+ DPoP；
  令牌端点要求 refresh token 与**首次登录的 code_verifier、DPoP 私钥**一起
  出示，所以凭据是一整块，不能只存 AK/SK/STS；
- 请求：SDK-HMAC-SHA256 签名；签名覆盖全部出站头（含 X-Security-Token /
  X-Domain-Id 与三个模型头），canonicalURI 必须带尾斜杠；
- 会话：每账号上游最多 3 路并发；满员回 409，不冷却账号；
- 目录：agent / builtin / benefit 三源合并，trial 账号为空时不兜底；
- 余额：套餐计量表（积分账本优先，token 账本兜底）+ 福利 Token 池两份账；
- 福利：客户端活动中心 delivery → claim → confirm → 回读（/v1/ops/*）；
  新用户注册积分只领一次，每日签到积分按上游状态每天领一次；
- 对话：上游是 OpenAI 兼容 SSE，但仍需首包门（空回答当失败）与流内错误
  信封判定（错误可能藏在 HTTP 200 里）。

本模块只依赖核心设施；核心不引用任何 codearts 字样。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from auth import accounts as accounts_mod
from core import net
from core import ratelimit
from core import upstream_body
from core import upstream_pool
from integrations import registry
from integrations import upstream_errors

REALM = "codearts"
LABEL = "CodeArts（华为云码道）"
SHORT = "CodeArts"
BADGE = "CodeArts"
DOMAIN = "codearts.huaweicloud.com"

#: 测试与私有部署可覆盖；生产默认值来自上游实测（区域必须同为 cn-north-4）
BASE = os.environ.get("CODEARTS_BASE") or \
    "https://snap-access.cn-north-4.myhuaweicloud.com"
#: 福利模型网关（官方客户端 product.json 的 benefitApiUrl）
BENEFIT_BASE = os.environ.get("CODEARTS_BENEFIT_BASE") or \
    "https://opengw.developer.huaweicloud.com"
TOKEN_URL = os.environ.get("CODEARTS_TOKEN_URL") or \
    "https://sts.cn-north-4.myhuaweicloud.com/v1/oauth2/tokens"
WEB_LOGIN_BASE = os.environ.get("CODEARTS_WEB_LOGIN_BASE") or \
    "https://codearts.huaweicloud.com"
CLIENT_ID = "vscode-codebot"
CALLBACK_PATH = "/oauth/callback"
PKCE_METHOD = "SHA-256"
CHAT_PATH = "/api/v2/chat/completions"

PLUGIN_NAME = "snap_vscode"
PLUGIN_VERSION = "26.9.101"
LANGUAGE = "en-us"
OPS_LANGUAGE = "zh-cn"
OPS_CHANNEL = "DESKTOP"

#: 活动中心状态：三者都代表这笔积分已经领到（CLAIMED 只差确认，额度已入账）
CLAIMED_WELFARE_STATUSES = frozenset(("CLAIMED", "CONFIRMED", "CONSUMED"))

#: 签到按钮只自动领这两类：新用户注册（一次）与每日签到（每天一次）
WELFARE_KINDS = {
    "NEW_USER_REGISTER": "new_user",
    "NEW_USER": "new_user",
    "REGISTER": "new_user",
    "USER_LOGIN": "daily",
    "DAILY_CLAIM": "daily",
    "DAILY_SIGNIN": "daily",
    "SIGN_IN": "daily",
}
WELFARE_LABELS = {
    "new_user": "新用户注册积分",
    "daily": "每日签到积分",
}

DEFAULT_SESSION_LIMIT = 3
REFRESH_MARGIN_SECONDS = 15 * 60
TOKEN_TIMEOUT = 30
SIGNED_TIMEOUT = 30
CATALOG_TTL = 5 * 60
LOGIN_TIMEOUT = 10 * 60

LEDGER_VERSION = 2
MAX_CLAIM_ATTEMPTS_PER_DAY = 12
#: 只防脚本双击；签到是否完成以上游活动状态为准，不再用 10 分钟闸挡住补签
MIN_CLAIM_INTERVAL = 60

EMPTY_BODY_SHA256 = ("e3b0c44298fc1c149afbf4c8996fb924"
                     "27ae41e4649b934ca495991b7852b855")

_MODEL_CACHE = {}          # realm -> {"at": ts, "data": [(id, meta)]}
_MODEL_LOCK = threading.RLock()
_CREDITS_CACHE = {}        # (realm, uid) -> (at, result)
_CREDITS_LOCK = threading.Lock()
_LOGIN_SESSIONS = {}
_LOGIN_LOCK = threading.Lock()
_REFRESH_LOCKS = {}
_REFRESH_GUARD = threading.Lock()
_SESSION_GUARD = threading.Lock()
_SESSION_GATE = {}


def _log(message, ctx=None):
    line = "codearts: %s" % message
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


# ===========================================================================
# P-256 / ECDSA（DPoP 用；纯标准库，避免引入第三方加密依赖）
# ===========================================================================
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_A = _P - 3
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _point_double(point):
    if point is None:
        return None
    x, y = point
    if y == 0:
        return None
    slope = ((3 * x * x + _A) * pow(2 * y, _P - 2, _P)) % _P
    nx = (slope * slope - 2 * x) % _P
    return nx, (slope * (x - nx) - y) % _P


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        return _point_double(p1) if (y1 + y2) % _P else None
    slope = ((y2 - y1) * pow(x2 - x1, _P - 2, _P)) % _P
    nx = (slope * slope - x1 - x2) % _P
    return nx, (slope * (x1 - nx) - y1) % _P


def _scalar_mult(scalar, point):
    result = None
    addend = point
    while scalar:
        if scalar & 1:
            result = _point_add(result, addend)
        addend = _point_double(addend)
        scalar >>= 1
    return result


def _ecdsa_sign(scalar, digest):
    z = int.from_bytes(digest, "big")
    while True:
        k = secrets.randbelow(_N - 1) + 1
        point = _scalar_mult(k, _G)
        if point is None:
            continue
        r = point[0] % _N
        if r == 0:
            continue
        s = (pow(k, _N - 2, _N) * (z + r * scalar)) % _N
        if s == 0:
            continue
        return r, s


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text):
    raw = str(text or "").strip()
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def generate_dpop_key_pair():
    """生成 DPoP 用的 P-256 密钥对（JWK 形态，可整块落盘）。"""
    scalar = secrets.randbelow(_N - 1) + 1
    point = _scalar_mult(scalar, _G)
    x = point[0].to_bytes(32, "big")
    y = point[1].to_bytes(32, "big")
    public = {"kty": "EC", "crv": "P-256",
              "x": _b64url(x), "y": _b64url(y)}
    private = dict(public, d=_b64url(scalar.to_bytes(32, "big")))
    return {"privateKeyJwk": private, "publicKeyJwk": public}


def _dpop_key(pair):
    """由持久化的密钥对恢复签名标量；公私钥不一致时拒绝签名。"""
    private = (pair or {}).get("privateKeyJwk") or {}
    if private.get("kty") != "EC" or private.get("crv") != "P-256":
        raise ValueError("CodeArts DPoP 私钥不完整（需要 EC / P-256）")
    scalar = int.from_bytes(_b64url_decode(private.get("d")), "big")
    if not 0 < scalar < _N:
        raise ValueError("CodeArts DPoP 私钥标量非法")
    point = _scalar_mult(scalar, _G)
    if point is None:
        raise ValueError("CodeArts DPoP 私钥无法推导公钥")
    derived_x = _b64url(point[0].to_bytes(32, "big"))
    derived_y = _b64url(point[1].to_bytes(32, "big"))
    recorded = (pair or {}).get("publicKeyJwk") or {}
    if recorded:
        if recorded.get("x") != derived_x or recorded.get("y") != derived_y:
            raise ValueError("CodeArts DPoP 公私钥不一致，请重新登录")
    return scalar, {"kty": "EC", "crv": "P-256",
                    "x": derived_x, "y": derived_y}


def dpop_proof(pair, method, endpoint):
    """现签一份 DPoP proof；htm/htu 必须与本次请求逐字一致。"""
    scalar, public_jwk = _dpop_key(pair)
    header = {"alg": "ES256", "typ": "dpop+jwt", "jwk": public_jwk}
    payload = {
        "htm": str(method or "POST").upper(),
        "htu": str(endpoint or ""),
        "iat": int(time.time()),
        "jti": secrets.token_hex(32),
    }
    encoded_header = _b64url(json.dumps(
        header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url(json.dumps(
        payload, separators=(",", ":")).encode("utf-8"))
    signing_input = (encoded_header + "." + encoded_payload).encode("ascii")
    r, s = _ecdsa_sign(scalar, hashlib.sha256(signing_input).digest())
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return encoded_header + "." + encoded_payload + "." + _b64url(signature)


def pkce_pair():
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ===========================================================================
# SDK-HMAC-SHA256 签名（按 Go net/url 语义实现，见上游 signer.cjs）
# ===========================================================================
def _unreserved(byte):
    return ((0x30 <= byte <= 0x39) or (0x41 <= byte <= 0x5a)
            or (0x61 <= byte <= 0x7a) or byte in (
                0x2d, 0x5f, 0x2e, 0x21, 0x7e, 0x2a, 0x27, 0x28, 0x29))


def _encode_component(data):
    out = []
    for byte in data:
        if _unreserved(byte):
            out.append(chr(byte))
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def _unhex(byte):
    if 0x30 <= byte <= 0x39:
        return byte - 0x30
    if 0x61 <= byte <= 0x66:
        return byte - 0x61 + 10
    if 0x41 <= byte <= 0x46:
        return byte - 0x41 + 10
    return -1


def _unescape(raw, plus_as_space):
    data = raw.encode("latin-1", "replace") if isinstance(raw, str) else raw
    out = bytearray()
    idx = 0
    while idx < len(data):
        byte = data[idx]
        if byte == 0x25:
            if idx + 2 >= len(data):
                return None
            high = _unhex(data[idx + 1])
            low = _unhex(data[idx + 2])
            if high < 0 or low < 0:
                return None
            out.append((high << 4) | low)
            idx += 3
        elif byte == 0x2b and plus_as_space:
            out.append(0x20)
            idx += 1
        else:
            out.append(byte)
            idx += 1
    return bytes(out)


def _parse_url(url):
    scheme_idx = url.find("://")
    if scheme_idx < 0:
        raise ValueError("上游地址缺少 scheme：%s" % url)
    rest = url[scheme_idx + 3:]
    cut = len(rest)
    for char in "/?#":
        idx = rest.find(char)
        if 0 <= idx < cut:
            cut = idx
    authority = rest[:cut]
    tail = rest[cut:].split("#", 1)[0]
    if not authority:
        raise ValueError("上游地址缺少主机名：%s" % url)
    q_idx = tail.find("?")
    raw_path = tail if q_idx < 0 else tail[:q_idx]
    raw_query = "" if q_idx < 0 else tail[q_idx + 1:]
    path = _unescape(raw_path, plus_as_space=False)
    if path is None:
        raise ValueError("上游地址路径转义非法：%s" % raw_path)
    return authority, path, raw_query


def _canonical_uri(path):
    if not path:
        return "/"
    segments = [ _encode_component(part) for part in path.split(b"/") ]
    escaped = "/".join(segments)
    return escaped if escaped.endswith("/") else escaped + "/"


def _query_pairs(raw_query):
    pairs = []
    for part in str(raw_query or "").split("&"):
        if not part or ";" in part:
            continue
        key_text, _, value_text = part.partition("=")
        key = _unescape(key_text, plus_as_space=True)
        value = _unescape(value_text, plus_as_space=True)
        if key is None or value is None:
            continue
        pairs.append((key, value))
    return pairs


def _canonical_query(raw_query):
    encoded = [(_encode_component(key), _encode_component(value))
               for key, value in _query_pairs(raw_query)]
    encoded.sort()
    return "&".join("%s=%s" % pair for pair in encoded)


def _set_header(items, name, value):
    lowered = name.lower()
    for idx, (key, _old) in enumerate(items):
        if key.lower() == lowered:
            items[idx] = (key, str(value))
            return items
    items.append((name, str(value)))
    return items


def _get_header(items, name):
    lowered = name.lower()
    for key, value in items:
        if key.lower() == lowered:
            return value
    return None


def sdk_date_now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sign_headers(method, url, headers, body, credential, include_host=False):
    """返回可发送的有序头集合（入参头 + 注入项 + Authorization）。"""
    if not credential or not credential.get("access_key_id") \
            or not credential.get("secret_access_key"):
        raise ValueError("凭据不完整：access key 与 secret key 都得有")
    authority, path, raw_query = _parse_url(url)
    items = [(str(name), str(value)) for name, value in (headers or [])]
    if credential.get("security_token"):
        _set_header(items, "X-Security-Token", credential["security_token"])
    if credential.get("domain_id"):
        _set_header(items, "X-Domain-Id", credential["domain_id"])
    if _get_header(items, "X-Sdk-Date") is None:
        _set_header(items, "X-Sdk-Date", sdk_date_now())
    if include_host and _get_header(items, "Host") is None:
        _set_header(items, "Host", authority)
    date = _get_header(items, "X-Sdk-Date") or ""

    canonical = sorted(((name.lower(), value.strip()) for name, value in items),
                       key=lambda pair: pair[0])
    canonical_headers = "".join("%s:%s\n" % pair for pair in canonical)
    signed_headers = ";".join(name for name, _value in canonical)

    payload_hash = hashlib.sha256(body or b"").hexdigest()
    override = _get_header(items, "X-Sdk-Content-Sha256")
    if override:
        payload_hash = override
    elif str(method).upper() not in ("PUT", "PATCH", "POST"):
        payload_hash = EMPTY_BODY_SHA256

    canonical_request = "\n".join((
        str(method).upper(),
        _canonical_uri(path),
        _canonical_query(raw_query),
        canonical_headers,
        signed_headers,
        payload_hash,
    ))
    string_to_sign = "\n".join((
        "SDK-HMAC-SHA256",
        date,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ))
    signature = hmac.new(
        credential["secret_access_key"].encode("utf-8"),
        string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    _set_header(items, "Authorization",
                "SDK-HMAC-SHA256 Access=%s, SignedHeaders=%s, Signature=%s"
                % (credential["access_key_id"], signed_headers, signature))
    return items


# ===========================================================================
# 凭据：整块保存、临期续期（单飞）、身份继承
# ===========================================================================
class CodeArtsError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = int(status or 502)


def _redact(text, secrets_list):
    out = str(text or "")
    for value in secrets_list or ():
        value = str(value or "")
        if len(value) >= 6:
            out = out.replace(value, "<redacted>")
    return out


def _parse_expiry(value):
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        number = float(value)
        return int(number / 1000.0 if number > 1e11 else number)
    text = str(value).strip()
    try:
        number = float(text)
        return int(number / 1000.0 if number > 1e11 else number)
    except ValueError:
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except ValueError:
        return 0


def _jwt_payload(token):
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return {}
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _identity_from_refresh_token(refresh_token):
    payload = _jwt_payload(refresh_token)
    if not payload:
        return {}
    return {
        "domain_id": str(payload.get("domain_id") or ""),
        "user_id": str(payload.get("user_id") or payload.get("uid") or ""),
        "user_name": str(payload.get("user_name") or payload.get("name") or ""),
    }


def _login_account_from_token(account):
    """CodeArts 访问令牌的 user_profile 带 account_name（登录账号）。"""
    payload = _jwt_payload(getattr(account, "access_token", ""))
    profile = payload.get("user_profile")
    if isinstance(profile, str) and profile:
        try:
            profile = json.loads(_b64url_decode(profile).decode("utf-8"))
        except Exception:
            profile = {}
    if isinstance(profile, dict):
        for key in ("account_name", "email", "phone"):
            value = str(profile.get(key) or "").strip()
            if value:
                return value
    meta = account.meta if isinstance(account.meta, dict) else {}
    return str(meta.get("userName") or "").strip()


def _token_request(form_pairs, oauth_context, previous_refresh="", proxy=""):
    if not oauth_context or not oauth_context.get("dpop_key_pair"):
        raise CodeArtsError(400, "CodeArts 凭据缺少 OAuth 上下文（DPoP 密钥），请重新登录")
    proof = dpop_proof(oauth_context["dpop_key_pair"], "POST", TOKEN_URL)
    body = urllib.parse.urlencode(list(form_pairs)).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "DPoP": proof,
    }
    request = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                     headers=headers)
    try:
        with net.urlopen(request, timeout=TOKEN_TIMEOUT, proxy=proxy) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = net.read_http_error(exc, 1000).decode("utf-8", "replace")
        detail = _redact(detail[:300], [previous_refresh,
                                        (oauth_context or {}).get("code_verifier")])
        status = exc.code if 400 <= exc.code < 500 else 502
        raise CodeArtsError(
            status, "CodeArts 令牌请求被拒（HTTP %d）：%s" % (exc.code, detail))
    except Exception as exc:
        status = 504 if "timed out" in str(exc).lower() else 502
        raise CodeArtsError(status, "CodeArts 令牌请求失败：%s" % exc)
    try:
        payload = json.loads(text)
    except Exception:
        payload = None
    creds = payload.get("credentials") if isinstance(payload, dict) \
        and isinstance(payload.get("credentials"), dict) else payload
    if not isinstance(creds, dict) or not creds.get("access_key_id") \
            or not creds.get("secret_access_key") \
            or not creds.get("security_token"):
        raise CodeArtsError(
            502, "CodeArts 令牌响应缺少 access_key_id / secret_access_key / "
                 "security_token")
    # 官方扩展从响应顶层读 refresh_token（credentials 内通常没有）。
    refresh_token = creds.get("refresh_token")
    if not refresh_token and isinstance(payload, dict):
        refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise CodeArtsError(
            502, "CodeArts 令牌响应没有 refresh token，该凭据无法续期，"
                 "请重新登录")
    return {
        "access_key_id": str(creds["access_key_id"]),
        "secret_access_key": str(creds["secret_access_key"]),
        "security_token": str(creds["security_token"]),
        "refresh_token": str(refresh_token),
        "expires_at": _parse_expiry(creds.get("expiration")),
        "domain_id": "",
        "user_id": "",
        "user_name": "",
        "login_type": "WEB",
        "oauth_context": oauth_context,
    }


def _credential_from(account):
    raw = str(getattr(account, "access_token", "") or "")
    packed = {}
    if raw.startswith("{"):
        try:
            packed = json.loads(raw)
        except Exception:
            packed = {}
    if not isinstance(packed, dict):
        packed = {}
    meta = dict(getattr(account, "meta", None) or {})
    context = packed.get("oauthContext") or meta.get("oauthContext")
    return {
        "access_key_id": str(packed.get("accessKeyId") or "").strip(),
        "secret_access_key": str(packed.get("secretAccessKey") or "").strip(),
        "security_token": str(packed.get("securityToken") or "").strip(),
        "refresh_token": str(packed.get("refreshToken")
                             or getattr(account, "refresh_token", "") or "").strip(),
        "expires_at": int(packed.get("expiresAt")
                          or getattr(account, "expires_at", 0) or 0),
        "domain_id": str(meta.get("domainId") or "").strip(),
        "user_id": str(meta.get("userId") or "").strip(),
        "user_name": str(meta.get("userName") or "").strip(),
        "login_type": str(meta.get("loginType") or "WEB"),
        "oauth_context": context if isinstance(context, dict) else None,
    }


def _credential_valid(credential):
    return bool(credential and credential.get("access_key_id")
                and credential.get("secret_access_key")
                and credential.get("security_token"))


def _credential_expiring(credential):
    expires_at = int((credential or {}).get("expires_at") or 0)
    if not expires_at:
        return True
    return expires_at - time.time() <= REFRESH_MARGIN_SECONDS


def _apply_credential(account, credential):
    packed = {
        "accessKeyId": credential["access_key_id"],
        "secretAccessKey": credential["secret_access_key"],
        "securityToken": credential["security_token"],
        "refreshToken": credential["refresh_token"],
        "expiresAt": credential["expires_at"],
        "oauthContext": credential.get("oauth_context"),
    }
    account.access_token = json.dumps(packed, ensure_ascii=False,
                                      separators=(",", ":"))
    account.refresh_token = credential["refresh_token"]
    account.expires_at = credential["expires_at"]
    account.token_expired = False
    account.last_error = ""
    account.session_dead_count = 0
    meta = dict(getattr(account, "meta", None) or {})
    for camel, key in (("domainId", "domain_id"), ("userId", "user_id"),
                       ("userName", "user_name"), ("loginType", "login_type")):
        if credential.get(key):
            meta[camel] = credential[key]
    account.meta = meta
    if getattr(account, "accounts_dir", ""):
        try:
            account.save(account.accounts_dir)
        except Exception:
            pass


def _refresh_lock_for(uid):
    with _REFRESH_GUARD:
        return _REFRESH_LOCKS.setdefault(str(uid or "anon"), threading.Lock())


def ensure_fresh(account, force=False):
    """取可用临时凭据；临期 15 分钟主动续期，同一账号并发只刷一次。"""
    credential = _credential_from(account)
    if not _credential_valid(credential):
        return {"ok": False, "status": 503,
                "message": "CodeArts 账号缺少可用的临时凭据，请重新登录"}
    if not force and not _credential_expiring(credential):
        return {"ok": True, "credential": credential, "refreshed": False}
    with _refresh_lock_for(getattr(account, "uid", "")):
        credential = _credential_from(account)
        if not force and not _credential_expiring(credential):
            return {"ok": True, "credential": credential, "refreshed": False}
        context = credential.get("oauth_context") or {}
        if not credential.get("refresh_token") or not context:
            return {"ok": False, "status": 400,
                    "message": "CodeArts 凭据缺少 refresh token / OAuth 上下文，"
                               "无法续期，请重新登录"}
        try:
            fresh = _token_request([
                ("client_id", CLIENT_ID),
                ("code_verifier", context.get("code_verifier") or ""),
                ("grant_type", "refresh_token"),
                ("refresh_token", credential["refresh_token"]),
            ], context, credential["refresh_token"],
                proxy=getattr(account, "proxy", "") or "")
        except CodeArtsError as exc:
            if exc.status in (400, 401):
                account.token_expired = True
            account.last_error = str(exc)[:200]
            return {"ok": False, "status": exc.status, "message": str(exc)}
        except Exception as exc:
            account.last_error = str(exc)[:200]
            return {"ok": False, "status": 502, "message": str(exc)}
        identity = _identity_from_refresh_token(fresh.get("refresh_token") or "")
        fresh["domain_id"] = credential.get("domain_id") or identity.get("domain_id") or ""
        fresh["user_id"] = credential.get("user_id") or identity.get("user_id") or ""
        fresh["user_name"] = credential.get("user_name") or identity.get("user_name") or ""
        fresh["login_type"] = credential.get("login_type") or "WEB"
        fresh["oauth_context"] = context
        _apply_credential(account, fresh)
        return {"ok": True, "credential": fresh, "refreshed": True}


def _signed_json(credential, method, path, body=None, headers=None,
                 base=None, timeout=SIGNED_TIMEOUT, proxy=""):
    """签名后打一次 JSON 接口；网络失败也返回结构化结果，不抛。"""
    url = str(base or BASE).rstrip("/") + path
    data = None if body is None else json.dumps(
        body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    items = list(headers or [("Content-Type", "application/json")])
    if _get_header(items, "Content-Type") is None:
        _set_header(items, "Content-Type", "application/json")
    signed = sign_headers(method, url, items, data, credential, False)
    request = urllib.request.Request(url, data=data, method=method,
                                     headers=dict(signed))
    try:
        with net.urlopen(request, timeout=timeout, proxy=proxy) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = net.read_http_error(exc, 4000)
    except Exception as exc:
        return {"ok": False, "status": 0, "data": None, "message": str(exc)}
    text = raw.decode("utf-8", "replace")
    try:
        data_obj = json.loads(text) if text else None
    except Exception:
        data_obj = None
    return {"ok": 200 <= status < 300, "status": status, "data": data_obj,
            "raw": text[:1000]}


# ===========================================================================
# OAuth 登录（回环回调 + 粘贴兜底）
# ===========================================================================
def _page_waiting():
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录回调</title>
</head><body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;
place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:480px;padding:24px">
<h2 style="font-size:18px">正在等待授权结果…</h2>
<p style="font-size:13.5px;line-height:1.9;color:#97a1ac">请回到华为云授权页完成登录，
本页会自动完成回调；若一直停在本页，请把地址栏整段链接粘回面板。</p></div></body></html>"""


def _page_ok():
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录成功</title>
</head><body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;
place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:480px;padding:24px">
<h2 style="font-size:18px;color:#44e07f">登录成功</h2>
<p style="font-size:13.5px;line-height:1.9;color:#97a1ac">CodeArts 账号已加入账号池，
可以关闭本页回到面板。</p></div></body></html>"""


def _page_error(message):
    safe = (str(message or "未知错误").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录失败</title>
</head><body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;
place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:520px;padding:24px">
<h2 style="font-size:18px;color:#f26d6d">登录失败</h2>
<p style="font-size:13.5px;line-height:1.9;color:#97a1ac">%s</p></div></body></html>""" % safe


def _trusted_redirect(raw):
    try:
        parsed = urllib.parse.urlsplit(str(raw or ""))
    except Exception:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return host == "huaweicloud.com" or host.endswith(".huaweicloud.com")


def _build_auth_url(port, ticket_id, challenge):
    """官方 VSCode 扩展当前的网页授权入口（旧 /login 已被下线）。

    /portal/authorize 的首跳由门户转给华为云 IAM，登录后回到本机回调；
    ticket_id 只用于本次授权的关联（扩展端用本地 UUID），不是服务端票据。
    """
    callback = "http://127.0.0.1:%d%s" % (port, CALLBACK_PATH)
    query = urllib.parse.urlencode({
        "theme": "",
        "locale": "zh-cn",
        "uri_scheme": CLIENT_ID,
        "client_id": CLIENT_ID,
        "port": str(port),
        "code_challenge": challenge,
        "code_challenge_method": PKCE_METHOD,
        "ticket_id": ticket_id,
        "auth_callback_url": callback,
        "plugin-name": PLUGIN_NAME,
        "plugin-version": PLUGIN_VERSION,
    })
    return "%s/portal/authorize?%s" % (WEB_LOGIN_BASE.rstrip("/"), query)


def _identity_uid(identity, access_key_id="", refresh_token=""):
    domain = str((identity or {}).get("domain_id") or "").strip()
    user = str((identity or {}).get("user_id") or "").strip()
    if domain and user:
        # 账号 uid 同时是凭据文件名：Windows 不接受冒号等字符
        raw = "%s-%s" % (domain, user)
        safe = "".join(char if (char.isalnum() or char in "._-") else "_"
                       for char in raw)
        return safe[:100]
    seed = str(access_key_id or refresh_token or "")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _save_oauth_account(ctx, credential):
    identity = _identity_from_refresh_token(credential.get("refresh_token") or "")
    if identity:
        credential["domain_id"] = credential.get("domain_id") \
            or identity.get("domain_id") or ""
        credential["user_id"] = credential.get("user_id") \
            or identity.get("user_id") or ""
        credential["user_name"] = credential.get("user_name") \
            or identity.get("user_name") or ""
    uid = _identity_uid(
        {"domain_id": credential.get("domain_id"),
         "user_id": credential.get("user_id")},
        credential.get("access_key_id"), credential.get("refresh_token"))
    name = str(credential.get("user_name") or "").strip() \
        or ("CodeArts %s" % uid[-6:])
    pool = getattr(ctx, "pool", None)
    existing = pool.get(uid) if pool is not None else None
    if existing is not None and existing.realm == REALM:
        if not existing.nickname:
            existing.nickname = name
        existing.enabled = True
        existing.clear_error()
        _apply_credential(existing, credential)
        return {"account": existing, "uid": uid, "name": existing.nickname,
                "merged": True}
    account = accounts_mod.Account({
        "uid": uid,
        "nickname": name,
        "realm": REALM,
        "domain": DOMAIN,
        "platform": "CLI",
        "source": "oauth",
        "enabled": True,
        "expiresAt": credential.get("expires_at") or 0,
        "meta": {
            "domainId": credential.get("domain_id") or "",
            "userId": credential.get("user_id") or "",
            "userName": credential.get("user_name") or "",
            "loginType": "WEB",
        },
    })
    _apply_credential(account, credential)
    if pool is not None:
        pool.add(account)
    else:
        account.save(ctx.accounts_dir)
    return {"account": account, "uid": uid, "name": account.nickname,
            "merged": False}


def _settle_login(ctx, session, params):
    code = str((params.get("code") or [""])[0]).strip()
    if not code:
        return {"ok": False, "message": "回调没有携带授权码"}
    # 门户回传的是它自己的 state（官方扩展同样忽略）。本次授权由随机回环
    # 端口和 PKCE code_verifier 绑定：换令牌时必须提供本次生成的 verifier，
    # 注入的授权码无法兑换。
    try:
        credential = _token_request([
            ("client_id", CLIENT_ID),
            ("code", code),
            ("code_verifier", session.get("verifier") or ""),
            ("grant_type", "authorization_code"),
            ("redirect_uri", session.get("redirect_uri") or ""),
        ], session.get("oauth_context"), "", proxy="")
    except CodeArtsError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}
    try:
        saved = _save_oauth_account(ctx, credential)
    except Exception as exc:
        return {"ok": False, "message": "账号入库失败：%s" % exc}
    session["status"] = "ok"
    session["message"] = ("登录成功，凭据已更新" if saved["merged"]
                          else "登录成功，账号已加入 CodeArts 账号池")
    session["account"] = {"uid": saved["uid"], "name": saved["name"]}
    return {"ok": True, "message": session["message"]}


def _close_login_session(state, keep_result=False):
    with _LOGIN_LOCK:
        session = _LOGIN_SESSIONS.pop(state, None)
    if session is None:
        return
    server = session.pop("server", None)
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
    if keep_result:
        with _LOGIN_LOCK:
            _LOGIN_SESSIONS[state] = session


def start_login(ctx):
    state = secrets.token_hex(16)
    ticket_id = str(uuid.uuid4())
    verifier, challenge = pkce_pair()
    oauth_context = {"dpop_key_pair": generate_dpop_key_pair(),
                     "code_verifier": verifier}
    session = {
        "state": state, "verifier": verifier,
        "oauth_context": oauth_context,
        "started": time.time(), "status": "waiting", "message": "",
        "account": None, "server": None, "port": 0, "redirect_uri": "",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code, html, extra_headers=None):
            body = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (extra_headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _handle(self, params):
            code = str((params.get("code") or [""])[0]).strip()
            secret_param = str((params.get("secret") or [""])[0]).strip()
            if not code and secret_param:
                redirect = str((params.get("redirect") or [""])[0]).strip()
                if not redirect:
                    self._reply(400, _page_error(
                        "登录失败：请把浏览器地址栏里带 code 的回调链接整段粘贴回面板"))
                    return
                if not _trusted_redirect(redirect):
                    self._reply(400, _page_error(
                        "登录失败：回调要求跳转的地址不是华为云站点，已拒绝"))
                    return
                self.send_response(307)
                self.send_header("Location", redirect)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if not code:
                self._reply(200, _page_waiting())
                return
            result = _settle_login(ctx, session, params)
            if result.get("ok"):
                _close_login_session(state, keep_result=True)
                self._reply(200, _page_ok())
            else:
                session["status"] = "error"
                session["message"] = result.get("message") or "登录失败"
                _close_login_session(state, keep_result=True)
                self._reply(200, _page_error(session["message"]))

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != CALLBACK_PATH:
                self._reply(404, _page_error("not found"))
                return
            self._handle(urllib.parse.parse_qs(
                parsed.query, keep_blank_values=True))

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", "replace") \
                if length else ""
            params = urllib.parse.parse_qs(raw, keep_blank_values=True)
            if not params:
                tail = raw.split("?", 1)[1] if "?" in raw else ""
                params = urllib.parse.parse_qs(tail, keep_blank_values=True)
            self._handle(params)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True,
                         name="codearts-oauth").start()
        session["server"] = server
        session["port"] = server.server_address[1]
        session["redirect_uri"] = "http://127.0.0.1:%d%s" % (
            session["port"], CALLBACK_PATH)
    except Exception as exc:
        return {"ok": False, "realm": REALM,
                "message": "CodeArts 回环端口监听失败：%s" % exc}
    auth_url = _build_auth_url(session["port"], ticket_id, challenge)
    with _LOGIN_LOCK:
        _LOGIN_SESSIONS[state] = session
    now = time.time()
    for key in list(_LOGIN_SESSIONS.keys()):
        old = _LOGIN_SESSIONS.get(key)
        if old is not None and now - old.get("started", 0) > LOGIN_TIMEOUT + 60:
            _close_login_session(key)
    return {
        "ok": True, "authUrl": auth_url, "state": state,
        "port": session["port"], "paste": True, "realm": REALM,
        "hint": "浏览器会先回调一次并跳转回华为云；停在「等待授权结果」属正常，"
                "完成登录后自动入池。若一直无回调，可把地址栏整段粘回面板。",
    }


def login_poll(ctx, state):
    with _LOGIN_LOCK:
        session = _LOGIN_SESSIONS.get(state)
    if session is None:
        return {"status": "expired",
                "message": "登录会话已结束（成功入池或已超时）"}
    if session.get("status") == "waiting" \
            and time.time() - session.get("started", 0) > LOGIN_TIMEOUT:
        session["status"] = "expired"
        session["message"] = "登录超时（10 分钟），请重新发起"
        _close_login_session(state)
    return {"status": session.get("status"),
            "message": session.get("message") or "等待授权回调…",
            "port": session.get("port")}


def login_submit(ctx, state, raw_callback):
    with _LOGIN_LOCK:
        session = _LOGIN_SESSIONS.get(state)
    if session is None:
        return None
    if session.get("status") in ("ok", "error", "expired"):
        return {"ok": False, "message": session.get("message") or "登录会话已结束"}
    raw = str(raw_callback or "").strip()
    if not raw:
        return {"ok": False, "message": "回调内容为空"}
    candidates = []
    if "://" in raw:
        parsed = urllib.parse.urlsplit(raw)
        candidates = [parsed.query, parsed.fragment]
    else:
        candidates = [raw]
        if "?" in raw:
            candidates.append(raw.split("?", 1)[1])
    params = None
    for candidate in candidates:
        parsed = urllib.parse.parse_qs(candidate or "", keep_blank_values=True)
        if parsed.get("code"):
            params = parsed
            break
    if params is None:
        return {"ok": False,
                "message": "无法解析回调内容：请整段复制浏览器地址栏（需包含 code）"}
    result = _settle_login(ctx, session, params)
    if result.get("ok"):
        _close_login_session(state, keep_result=True)
    else:
        session["status"] = "error"
        session["message"] = result.get("message") or "登录失败"
    return result


def login_cancel(state):
    with _LOGIN_LOCK:
        known = state in _LOGIN_SESSIONS
    if not known:
        return None
    _close_login_session(state)
    return {"ok": True}


# ===========================================================================
# 模型目录：agent / builtin / benefit 三源合并
# ===========================================================================
def _normalize_model(model_id, source, extra=None):
    extra = extra or {}
    mid = str(model_id or "").strip()
    if not mid:
        return None
    name = str(extra.get("name") or mid).strip()
    entry = {
        "id": mid,
        "name": name,
        "supportsImages": bool(extra.get("images")),
        "supportsToolCall": True,
        "supportsReasoning": bool(extra.get("reasoning")),
        "context_length": int(extra.get("contextLength") or 0) or 0,
        "max_output_tokens": int(extra.get("maxOutputTokens") or 0) or 0,
        "source": source,
        "vendor": "CodeArts",
    }
    credits = str(extra.get("credits") or "").strip()
    if credits:
        entry["credits"] = credits
    return entry


def merge_catalog(agent_models, builtin_models, benefit_models):
    out = []
    seen = set()
    for models_list, source in ((agent_models, "agent"),
                                (builtin_models, "builtin"),
                                (benefit_models, "benefit")):
        for item in models_list or []:
            mid = str((item or {}).get("id") or "").strip()
            if not mid or mid.lower() in seen:
                continue
            seen.add(mid.lower())
            entry = _normalize_model(mid, source, item)
            if entry:
                out.append(entry)
    return out


def _list_field(body, *keys):
    """从顶层或 data/result 包装里取数组字段（上游三种信封都用过）。"""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return []
    for key in keys:
        value = body.get(key)
        if isinstance(value, list):
            return value
    for wrapper in ("data", "result"):
        inner = body.get(wrapper)
        if isinstance(inner, dict):
            for key in keys:
                value = inner.get(key)
                if isinstance(value, list):
                    return value
    return []


def _flag_field(body, key):
    if not isinstance(body, dict):
        return None
    if key in body:
        return body.get(key)
    for wrapper in ("data", "result"):
        inner = body.get(wrapper)
        if isinstance(inner, dict) and key in inner:
            return inner.get(key)
    return None


def _as_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return int(value)
        text = str(value).strip()
        return int(float(text)) if text else None
    except (TypeError, ValueError):
        return None


def _first_int(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = _as_int(mapping.get(key))
        if value is not None:
            return value
    return None


def _common_headers(agent_type=""):
    items = [
        ("Content-Type", "application/json"),
        ("x-snap-traceid", str(uuid.uuid4())),
        ("x-auth-token", ""),
        ("X-Language", LANGUAGE),
    ]
    if agent_type:
        items.append(("Agent-Type", agent_type))
    return items


def _ops_headers(trace=False):
    """活动中心/福利网关的客户端头（与官方客户端 BenefitService 一致）。"""
    items = [
        ("Content-Type", "application/json"),
        ("Agent-Type", "PromptCenter"),
        ("X-Language", OPS_LANGUAGE),
    ]
    if trace:
        items.append(("x-snap-traceid", str(uuid.uuid4())))
    return items


def _benefit_json(credential, path, proxy=""):
    """福利模型网关与对话网关不同域；失败再回落到 BASE。"""
    bases = [BENEFIT_BASE]
    fallback = str(BASE or "").rstrip("/")
    if fallback and fallback != str(BENEFIT_BASE or "").rstrip("/"):
        bases.append(fallback)
    last = {"ok": False, "status": 0, "data": None}
    for base in bases:
        last = _signed_json(credential, "GET", path,
                            headers=_ops_headers(),
                            base=base, proxy=proxy)
        if last.get("ok") and isinstance(last.get("data"), dict):
            return last
        if last.get("status") in (401, 403):
            break
    return last


def _credit_display(credit):
    """官方客户端同口径：`credit.ratio_display`，缺失时回落到折前倍率。"""
    entry = credit[0] if isinstance(credit, list) and credit else credit
    if isinstance(entry, dict):
        raw = entry.get("ratio_display")
        if raw in (None, ""):
            raw = entry.get("before_display_ratio")
        if raw in (None, ""):
            raw = entry.get("ratio")
    else:
        raw = entry
    if isinstance(raw, (int, float)):
        return "0" if raw == 0 else "%gx" % raw
    text = str(raw or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.endswith("x") or lowered.startswith("x"):
        return text
    try:
        number = float(text)
    except ValueError:
        return text
    return "0" if number == 0 else "%gx" % number


def _model_item(item):
    if not isinstance(item, dict):
        return None
    params = item.get("model_parameters")
    if not isinstance(params, dict):
        params = {}
    mid = item.get("model_id") or item.get("modelId") or item.get("id") \
        or params.get("model_id") or params.get("modelId") or params.get("id")
    if not mid:
        return None
    credit = item.get("credit")
    if credit in (None, "", []):
        credit = item.get("credits")
    if credit in (None, "", []):
        credit = params.get("credit")
    return {
        "id": str(mid),
        "name": str(item.get("model_name") or item.get("name")
                    or item.get("display_name") or params.get("model_name")
                    or params.get("name") or mid),
        "images": item.get("multimodal") is True
        or item.get("supports_images") is True
        or item.get("supports_image") is True,
        "reasoning": item.get("reasoning") is True
        or item.get("supports_reasoning") is True,
        "contextLength": item.get("context_length")
        or item.get("context_window") or 0,
        "maxOutputTokens": item.get("max_tokens")
        or item.get("max_output_tokens") or 0,
        "credits": _credit_display(credit),
    }


def _agent_models(agent):
    out = []
    for key in ("models", "model"):
        values = (agent or {}).get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            entry = _model_item(item)
            if entry:
                out.append(entry)
    return out


def _fetch_models_for_account(account, credential, ctx=None):
    proxy = getattr(account, "proxy", "") or ""
    agent_models = []
    listing = _signed_json(
        credential, "GET",
        "/v1/agent-center/agents/useragents?offset=0&limit=100"
        "&is_primary_agent=true&supported_client=VSCODE"
        "&min_compatible_plugin_version=" + PLUGIN_VERSION,
        headers=_common_headers("AgentCenter"), proxy=proxy)
    agents = _list_field(listing.get("data"), "agents")
    for agent in agents[:100]:
        agent_id = str((agent or {}).get("agent_id") or "").strip()
        models = _agent_models(agent)
        if not models and agent_id:
            detail = _signed_json(
                credential, "GET",
                "/v1/agent-center/agents/detail?agent_id="
                + urllib.parse.quote(agent_id, safe=""),
                headers=_common_headers("AgentCenter"), proxy=proxy)
            body = detail.get("data")
            gpts = body.get("gpts") if isinstance(body, dict) else None
            if not isinstance(gpts, dict) and isinstance(body, dict):
                inner = body.get("data")
                gpts = inner.get("gpts") if isinstance(inner, dict) else None
            for item in _list_field(gpts, "models"):
                entry = _model_item(item)
                if entry:
                    models.append(entry)
        agent_models.extend(models)

    builtin_models = []
    builtin = _signed_json(
        credential, "GET", "/v1/model/builtin",
        headers=_common_headers("PromptCenter"), proxy=proxy)
    for item in _list_field(builtin.get("data"), "builtinModels", "models"):
        entry = _model_item(item)
        if entry:
            builtin_models.append(entry)

    benefit_models = []
    switch = _signed_json(
        credential, "GET", "/v1/benefit-gateway-config",
        headers=_ops_headers(), proxy=proxy)
    enabled = _flag_field(switch.get("data"), "enabled")
    if switch.get("ok") and enabled is not False:
        gateway = _benefit_json(credential, "/api/v1/gateway/config",
                                proxy=proxy)
        for item in _list_field(gateway.get("data"), "models"):
            entry = _model_item(item)
            if entry:
                benefit_models.append(entry)
    _log("catalog sources: agent=%d builtin=%d benefit=%d "
         "(status %s/%s/%s)" % (
             len(agent_models), len(builtin_models), len(benefit_models),
             listing.get("status"), builtin.get("status"),
             switch.get("status")), ctx)
    return merge_catalog(agent_models, builtin_models, benefit_models)


def fetch_catalog(ctx):
    """从可用账号拉一次目录；返回条目 dict 列表（失败返回空列表）。"""
    pool = getattr(ctx, "pool", None)
    accounts = list(pool.accounts) if pool is not None else []
    for account in accounts:
        if getattr(account, "realm", "") != REALM \
                or not getattr(account, "enabled", False):
            continue
        fresh = ensure_fresh(account)
        if not fresh.get("ok"):
            continue
        try:
            models_list = _fetch_models_for_account(
                account, fresh["credential"], ctx)
        except Exception as exc:
            _log("catalog fetch for %s failed: %s"
                 % (str(account.uid)[:8], exc), ctx)
            continue
        if models_list:
            with _MODEL_LOCK:
                _MODEL_CACHE[REALM] = {"at": time.time(), "data": models_list}
            _log("catalog: %d models from account %s"
                 % (len(models_list), str(account.uid)[:8]), ctx)
            return models_list
    return []


def _cached_entries():
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(REALM)
        return list(cached.get("data") or []) if cached else []


def _pairs(entries):
    return [(str(item.get("id") or ""), item) for item in entries or []
            if str(item.get("id") or "")]


def live_models(realm, force=False, ctx=None):
    if realm != REALM:
        return []
    with _MODEL_LOCK:
        cached = _MODEL_CACHE.get(REALM)
        if cached and not force \
                and time.time() - cached.get("at", 0) < CATALOG_TTL:
            return _pairs(cached.get("data"))
    models_list = fetch_catalog(ctx)
    if models_list:
        return _pairs(models_list)
    if cached and not force:
        return _pairs(cached.get("data"))
    return []


def resolve_model(model, models_pairs):
    """大小写无关解析上游真名；目录里没有返回 None。"""
    wanted = str(model or "").strip().lower()
    if not wanted:
        return None
    for model_id, meta in models_pairs or []:
        if str(model_id or "").lower() == wanted:
            return meta
    return None


def _is_benefit_model(entry):
    return str((entry or {}).get("source") or "") == "benefit"


def reset_caches():
    """测试与手动排障用：清空目录/余额缓存。"""
    with _MODEL_LOCK:
        _MODEL_CACHE.clear()
    with _CREDITS_LOCK:
        _CREDITS_CACHE.clear()


# ===========================================================================
# 会话并发闸（每账号默认 3 路；满员 409，不冷却账号）
# ===========================================================================
def _session_limit(account):
    try:
        value = int((getattr(account, "meta", None) or {}).get("maxConcurrent"))
        return value if value > 0 else DEFAULT_SESSION_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_SESSION_LIMIT


def _session_identity(account, credential):
    domain = str((credential or {}).get("domain_id") or "").strip()
    user = str((credential or {}).get("user_id") or "").strip()
    if domain and user:
        return "%s:%s" % (domain, user)
    return "account:%s" % str(getattr(account, "uid", "") or "anon")


def acquire_session(account, credential):
    key = _session_identity(account, credential)
    limit = _session_limit(account)
    with _SESSION_GUARD:
        current = _SESSION_GATE.get(key, 0)
        if current >= limit:
            return {"acquired": False, "limit": limit,
                    "message": "该账号已达并发上限（%d 路）" % limit}
        _SESSION_GATE[key] = current + 1
    released = {"done": False}

    def release():
        if released["done"]:
            return
        released["done"] = True
        with _SESSION_GUARD:
            current = _SESSION_GATE.get(key, 0)
            if current <= 1:
                _SESSION_GATE.pop(key, None)
            else:
                _SESSION_GATE[key] = current - 1

    return {"acquired": True, "limit": limit, "release": release}


# ===========================================================================
# 余额：积分账本优先（官方客户端口径）+ token 账本兜底 + 福利 Token 池
# ===========================================================================
CREDIT_METRIC_LABELS = {
    "usageTotalPackageCredit": "总积分",
    "usageBasicPackageCredit": "套餐积分",
    "usageOnDemandPackageCredit": "按需积分",
    "usageBonusPackageCredit": "赠送积分",
}


def _credit_row(metric):
    if not isinstance(metric, dict):
        return None
    name = str(metric.get("name") or "").strip()
    if not name:
        return None
    amount = _as_int(metric.get("package_credit_amount"))
    used = _as_int(metric.get("package_credit_used"))
    remain = _as_int(metric.get("package_credit_remain"))
    if amount is None and used is None and remain is None:
        return None
    if amount is None and remain is not None:
        amount = remain + (used or 0)
    return {"name": name, "amount": amount, "used": used, "remain": remain}


def _credit_packages(rows, total):
    packages = []
    for row in rows:
        if row is total:
            continue
        amount = row.get("amount")
        used = row.get("used") or 0
        remain = row.get("remain")
        if remain is None:
            remain = max(0, (amount or 0) - used) if amount is not None else None
        if not amount and not remain:
            continue
        packages.append({
            "package_code": row["name"],
            "name": CREDIT_METRIC_LABELS.get(row["name"], row["name"]),
            "remain": remain,
            "used": used,
            "size": amount,
            "unit": "积分",
            "usedPercent": int(round(used * 100.0 / amount))
            if amount and amount > 0 else None,
            "no_expiry": True,
            "is_expired": False,
        })
    if packages:
        return packages
    amount = total.get("amount")
    remain = total.get("remain")
    if remain is None:
        remain = max(0, (amount or 0) - (total.get("used") or 0))
    return [{
        "package_code": total["name"],
        "name": "积分",
        "remain": remain,
        "used": total.get("used") or 0,
        "size": amount,
        "unit": "积分",
        "usedPercent": None,
        "no_expiry": True,
        "is_expired": False,
    }]


def _benefit_wallet(credential, account):
    resp = _benefit_json(credential, "/api/v1/user/tokens/balance",
                         proxy=getattr(account, "proxy", "") or "")
    body = resp.get("data")
    auth_error = resp.get("status") in (401, 403)
    if not resp.get("ok") or not isinstance(body, dict):
        return None, auth_error
    code = str(body.get("error_code") or "")
    if code and code != "0000":
        return None, code in ("401", "403")
    result = body.get("result")
    if not isinstance(result, dict):
        result = body.get("data") if isinstance(body.get("data"), dict) else body
    # 官方客户端按 used_amount / total_quota 展示（教育渠道是 monthly_*）
    used = _first_int(result, "used_amount", "usage_token_num", "used")
    total = _first_int(result, "total_quota", "monthly_token_limit",
                       "model_quota_num")
    balance = _first_int(result, "balance", "remain", "remaining", "tokens")
    if balance is None and total is not None:
        balance = -1 if total < 0 else max(0, total - (used or 0))
    if balance is None:
        return None, False
    wallet = {
        "type": "benefit_tokens",
        "displayName": "福利 Token 池",
        "balance": balance,
        "unit": "Tokens",
        "size": total if total and total > 0 else None,
        "used": used or 0,
    }
    if total is not None and total > 0:
        wallet["usedPercent"] = int(round((used or 0) / total * 100))
    return wallet, False


def query_balance(account, credential):
    wallets = []
    packages = []
    auth_error = False
    metrics = []
    package = {}
    stats = _signed_json(credential, "GET",
                         "/snap-manager/v1/statistics/plugin",
                         headers=_common_headers(),
                         proxy=getattr(account, "proxy", "") or "")
    if stats.get("status") in (401, 403):
        auth_error = True
    body = stats.get("data")
    if stats.get("ok") and isinstance(body, dict):
        inner = body.get("result") if isinstance(body.get("result"), dict) \
            else body
        if not isinstance(inner.get("metrics"), list) \
                and isinstance(inner.get("data"), dict):
            inner = inner["data"]
        metrics = inner.get("metrics") \
            if isinstance(inner.get("metrics"), list) else []
        package = inner.get("package") \
            if isinstance(inner.get("package"), dict) else {}

    credit_rows = [row for row in (_credit_row(item) for item in metrics)
                   if row]
    credit_package = package.get("is_credit_package") is True
    # 积分账本优先：is_credit_package 或任一积分维度有真实数字时才用积分口径；
    # 否则退回 token 账本（usageTokenChatMessages 的 package_token_amount 在
    # 积分套餐里固定是 1，把它当余额就是面板显示 1 的来源）。
    if credit_rows and (credit_package or any(
            (row.get("amount") or 0) > 0 or (row.get("remain") or 0) > 0
            for row in credit_rows)):
        total = next((row for row in credit_rows
                      if row["name"] == "usageTotalPackageCredit"), None)
        if total is None:
            total = next((row for row in credit_rows if row.get("amount")),
                         credit_rows[0])
        amount = total.get("amount")
        used = total.get("used") or 0
        remain = total.get("remain")
        if remain is None:
            remain = max(0, (amount or 0) - used) if amount is not None else 0
        wallets.append({
            "type": "credits",
            "displayName": "积分",
            "balance": remain,
            "usedPercent": int(round(used * 100.0 / amount))
            if amount and amount > 0 else -1,
            "unit": "积分",
        })
        packages = _credit_packages(credit_rows, total)
        available = remain
        used_total = used
        size_total = amount if amount and amount > 0 else None
    else:
        target = next((meter for meter in metrics
                       if isinstance(meter, dict)
                       and meter.get("name") == "usageTokenChatMessages"), None)
        if target is None:
            target = next((meter for meter in metrics
                           if isinstance(meter, dict)
                           and ("usage_token_num" in meter
                                or "package_token_amount" in meter)), None)
        available, used_total, size_total = 0, 0, None
        if target is not None:
            used_total = _as_int(target.get("usage_token_num")) or 0
            size_total = _as_int(target.get("package_token_amount"))
            if size_total is not None and size_total > 0:
                remain = max(0, size_total - used_total)
                percent = int(round(used_total * 100.0 / size_total))
            elif size_total == -1:
                remain, percent = -1, -1
            else:
                remain, percent = 0, -1
            wallets.append({
                "type": "subscription",
                "displayName": "套餐 Tokens",
                "balance": remain,
                "usedPercent": percent,
                "unit": "Tokens",
            })
            packages.append({
                "package_code": "subscription",
                "name": "套餐 Tokens",
                "remain": remain,
                "used": used_total,
                "size": size_total if size_total and size_total > 0 else None,
                "unit": "Tokens",
                "usedPercent": percent,
                "no_expiry": True,
                "is_expired": False,
            })
            available = remain

    benefit, benefit_auth = _benefit_wallet(credential, account)
    auth_error = auth_error or benefit_auth
    if benefit is not None:
        wallets.append(benefit)
        packages.append({
            "package_code": "benefit_tokens",
            "name": benefit["displayName"],
            "remain": benefit["balance"],
            "used": benefit.get("used") or 0,
            "size": benefit.get("size"),
            "unit": benefit.get("unit") or "Tokens",
            "usedPercent": benefit.get("usedPercent"),
            "no_expiry": True,
            "is_expired": False,
        })
        if not wallets[:-1]:
            available = benefit["balance"]

    if auth_error and not wallets:
        return {"ok": False, "authError": True,
                "error": "CodeArts 凭证已失效，请重新登录"}
    unlimited = bool(wallets) and all(
        int(wallet.get("balance", 0)) < 0 for wallet in wallets)
    package_name = str(package.get("package_name_en") or "").strip()
    return {
        "ok": True,
        "wallets": wallets,
        "packages": packages,
        "available": -1 if unlimited else available,
        "used": used_total,
        "size": size_total,
        "is_paid_user": bool(wallets)
        and package_name.lower() not in ("", "trial", "free"),
    }


def credits_for_account(account, force=False):
    key = (REALM, str(getattr(account, "uid", "") or ""))
    now = time.time()
    with _CREDITS_LOCK:
        hit = _CREDITS_CACHE.get(key)
        if hit and not force and now - hit[0] <= 60:
            return {"ok": True, "credits": dict(hit[1]), "cached": True}
    fresh = ensure_fresh(account)
    if not fresh.get("ok"):
        return {"ok": False, "authError": True,
                "error": fresh.get("message") or "CodeArts 凭据不可用"}
    try:
        result = query_balance(account, fresh["credential"])
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}
    if not result.get("ok"):
        return result
    wallets = result.get("wallets") or []
    packages = list(result.get("packages") or [])
    if not packages:
        for wallet in wallets:
            packages.append({
                "package_code": wallet.get("type") or "",
                "name": wallet.get("displayName") or "额度",
                "remain": wallet.get("balance"),
                "size": wallet.get("size"),
                "unit": wallet.get("unit") or "",
                "usedPercent": wallet.get("usedPercent"),
                "no_expiry": True,
                "is_expired": False,
            })
    credits = {
        "remain": result.get("available", 0),
        "used": result.get("used", 0),
        "size": result.get("size"),
        "unlimited": bool(wallets) and result.get("available") == -1,
        "packages": packages,
        "wallets": wallets,
        "updated_at": time.time(),
        "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_paid_user": bool(result.get("is_paid_user")),
    }
    account.credits = credits
    if getattr(account, "accounts_dir", ""):
        try:
            account.save(account.accounts_dir)
        except Exception:
            pass
    with _CREDITS_LOCK:
        _CREDITS_CACHE[key] = (now, dict(credits))
    return {"ok": True, "credits": credits}


# ===========================================================================
# 每日签到：活动中心 delivery → claim → confirm → 回读 delivery
# ===========================================================================
def _today_key():
    return time.strftime("%Y%m%d")


def _read_ledger(account):
    ledger = (getattr(account, "meta", None) or {}).get("welfareLedger")
    if not isinstance(ledger, dict):
        return {"version": LEDGER_VERSION, "day": "", "attempts": 0,
                "lastAttemptAt": 0, "idempotencyKeys": []}
    return dict(ledger)


def _write_ledger(account, ledger):
    meta = dict(getattr(account, "meta", None) or {})
    meta["welfareLedger"] = ledger
    account.meta = meta
    if getattr(account, "accounts_dir", ""):
        try:
            account.save(account.accounts_dir)
        except Exception:
            pass


def _welfare_items(body):
    if not isinstance(body, dict):
        return []
    payload = body.get("data")
    items = payload.get("items") if isinstance(payload, dict) else body.get("items")
    return items if isinstance(items, list) else []


def _welfare_status(item):
    return str((item or {}).get("status") or "").strip().upper()


def _welfare_claimed(item):
    return _welfare_status(item) in CLAIMED_WELFARE_STATUSES


def _campaign_id(item):
    item = item or {}
    return _as_int(item.get("campaignId", item.get("campaign_id")))


def _welfare_kind(item):
    return WELFARE_KINDS.get(
        str((item or {}).get("type") or "").strip().upper(), "")


def _welfare_claimable(item):
    return bool(_campaign_id(item)) and bool(_welfare_kind(item)) \
        and (item or {}).get("claimable") is not False \
        and not _welfare_claimed(item)


def _welfare_accepted(resp):
    """claim/confirm 的 HTTP 200 只是受理；body 带 code 时还必须为 0/200。"""
    if not resp.get("ok"):
        return False
    body = resp.get("data")
    if not isinstance(body, dict):
        return True
    if str(body.get("error_code") or "") not in ("", "0", "0000"):
        return False
    if "code" in body:
        return str(body.get("code")) in ("0", "200")
    return True


def _claim_body(resp):
    body = resp.get("data")
    if not isinstance(body, dict):
        return {}
    payload = body.get("data")
    return payload if isinstance(payload, dict) else body


def _welfare_message(claimed_items):
    parts = []
    for item in claimed_items:
        label = WELFARE_LABELS.get(_welfare_kind(item), "签到积分")
        amount = _as_int(item.get("benefitAmount"))
        parts.append("%s%s" % (label, " %d 积分" % amount if amount else ""))
    return "、".join(parts)


def _delivery_items(credential, proxy):
    delivery = _signed_json(
        credential, "GET", "/v1/ops/delivery?channel=" + OPS_CHANNEL,
        headers=_ops_headers(trace=True), proxy=proxy)
    if not delivery.get("ok"):
        return None, delivery
    return _welfare_items(delivery.get("data")), delivery


def claim_welfare(account):
    fresh = ensure_fresh(account)
    if not fresh.get("ok"):
        return {"ok": False, "authError": True,
                "message": fresh.get("message") or "CodeArts 凭据不可用"}
    credential = fresh["credential"]
    proxy = getattr(account, "proxy", "") or ""
    now = time.time()
    ledger = _read_ledger(account)
    if ledger.get("version") != LEDGER_VERSION:
        return {"ok": False,
                "message": "福利台账版本不认识（!= 2），拒绝发送写请求（请重新登录刷新台账）"}
    if ledger.get("day") == _today_key() \
            and int(ledger.get("attempts") or 0) >= MAX_CLAIM_ATTEMPTS_PER_DAY:
        return {"ok": False, "already": True,
                "message": "今天签到次数已达上限（%d 次），请明天再试"
                           % MAX_CLAIM_ATTEMPTS_PER_DAY}
    last_attempt = float(ledger.get("lastAttemptAt") or 0)
    if last_attempt and now - last_attempt < MIN_CLAIM_INTERVAL:
        wait_sec = max(1, int(MIN_CLAIM_INTERVAL - (now - last_attempt) + 0.999))
        return {"ok": False, "already": True, "claimed": 0,
                "message": "操作太频繁，请 %d 秒后再试" % wait_sec}

    items, delivery = _delivery_items(credential, proxy)
    if items is None:
        return {"ok": False, "message": "签到活动读取失败（HTTP %s）"
                                       % delivery.get("status")}
    daily_item = next((item for item in items
                       if isinstance(item, dict)
                       and _welfare_kind(item) == "daily"), None)
    daily_done = bool(daily_item and _welfare_claimed(daily_item))
    daily_amount = _as_int((daily_item or {}).get("benefitAmount")) or 0
    candidates = [item for item in items
                  if isinstance(item, dict) and _welfare_claimable(item)]
    if not candidates:
        if daily_done:
            return {"ok": True, "already": True, "claimed": 0,
                    "verified": 0, "dailyDone": True,
                    "dailyAmount": daily_amount,
                    "message": "今日已签到%s（新用户积分已领过则不会重复领取）"
                               % ("，签到积分 %d" % daily_amount
                                  if daily_amount else "")}
        return {"ok": True, "already": True, "claimed": 0,
                "verified": 0, "dailyDone": False,
                "message": "当前没有可领取的签到积分（活动未开放或已领完）"}

    # 幂等键先落盘：请求已发出但响应没收到时，内存键丢失会导致重领
    idempotency_keys = [
        "%s-%s-%s" % (_today_key(), _campaign_id(item), secrets.token_hex(4))
        for item in candidates]
    ledger["idempotencyKeys"] = list(ledger.get("idempotencyKeys") or [])[-20:] \
        + idempotency_keys
    ledger["attempts"] = (int(ledger.get("attempts") or 0)
                          if ledger.get("day") == _today_key() else 0) + 1
    ledger["day"] = _today_key()
    ledger["lastAttemptAt"] = now
    ledger["version"] = LEDGER_VERSION
    _write_ledger(account, ledger)

    claimed_items = []
    claimed_ids = []
    failures = []
    for item, idempotency_key in zip(candidates, idempotency_keys):
        campaign_id = _campaign_id(item)
        claim = _signed_json(credential, "POST", "/v1/ops/claim", {
            "campaignId": campaign_id,
            "idempotentKey": idempotency_key,
            "channel": OPS_CHANNEL,
        }, headers=_ops_headers(), proxy=proxy)
        if not _welfare_accepted(claim):
            failures.append("%s：HTTP %s" % (
                WELFARE_LABELS.get(_welfare_kind(item), "签到"),
                claim.get("status") or "?"))
            continue
        payload = _claim_body(claim)
        user_benefit_id = str(payload.get("id")
                              or payload.get("userBenefitId")
                              or payload.get("user_benefit_id") or "").strip()
        if user_benefit_id:
            # 官方客户端 confirm 只传 userBenefitId，服务端会以「campaignId
            # 参数无效」拒绝；实测必须两件一起带。confirm 失败不否定已经
            # 到账的 claim（活动列表会保持 CLAIMED）。
            confirm = _signed_json(credential, "POST", "/v1/ops/confirm", {
                "campaignId": campaign_id,
                "userBenefitId": user_benefit_id,
            }, headers=_ops_headers(), proxy=proxy)
            if not _welfare_accepted(confirm):
                _log("welfare confirm rejected for campaign %s (HTTP %s)"
                     % (campaign_id, confirm.get("status")))
        claimed_items.append(item)
        claimed_ids.append(campaign_id)

    if not claimed_items:
        detail = "；".join(failures[:2])
        return {"ok": False, "already": False, "claimed": 0, "verified": 0,
                "dailyDone": daily_done,
                "message": "签到失败：%s" % (detail or "上游拒绝领取请求")}

    # 回读活动列表：CLAIMED / CONFIRMED / CONSUMED 都算到账（官方客户端同口径）
    verified_items, _verify = _delivery_items(credential, proxy)
    status_by_id = {}
    if verified_items is not None:
        for item in verified_items:
            if isinstance(item, dict):
                status_by_id[_campaign_id(item)] = _welfare_status(item)
    verified = sum(1 for campaign_id in claimed_ids
                   if status_by_id.get(campaign_id) in CLAIMED_WELFARE_STATUSES)
    if verified < len(claimed_ids):
        return {"ok": False, "already": False, "claimed": len(claimed_items),
                "verified": verified, "dailyDone": daily_done,
                "message": "领取请求已受理，但回读活动列表未确认全部到账"
                           "（%d/%d），请稍后刷新"
                           % (verified, len(claimed_ids))}
    daily_done = daily_done or any(
        _welfare_kind(item) == "daily" for item in claimed_items)
    gained = sum(_as_int(item.get("benefitAmount")) or 0
                 for item in claimed_items)
    return {
        "ok": True, "already": False, "claimed": len(claimed_items),
        "verified": verified, "dailyDone": daily_done,
        "creditTotal": gained,
        "message": "签到成功：%s%s"
                   % (_welfare_message(claimed_items),
                      "（共 %d 积分）" % gained if gained else ""),
    }


def checkin_for_account(account, trigger="unknown"):
    result = claim_welfare(account)
    # 签到是否完成以上游活动状态为准：今天已领时也要把本地标记补上，面板
    # 才会从「未签到」变成「已签到」；只有真正写入的新增才记活动历史。
    if result.get("ok") and (int(result.get("claimed") or 0) > 0
                             or result.get("dailyDone")):
        account.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
        if getattr(account, "accounts_dir", ""):
            try:
                account.save(account.accounts_dir)
            except Exception:
                pass
        if int(result.get("claimed") or 0) > 0:
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


# ===========================================================================
# 对话流：首包门 + 流内错误信封 + 空回答判定
# ===========================================================================
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


def _choices_have_content(choices):
    for choice in choices or []:
        if not isinstance(choice, dict):
            continue
        if _delta_has_content(choice.get("delta")) \
                or _delta_has_content(choice.get("message")):
            return True
        if str(choice.get("text") or "").strip():
            return True
    return False


def stream_frame_fault(frame):
    """判一帧是否为流内错误信封；带答案的帧绝不判故障。"""
    if not isinstance(frame, dict):
        return None
    answer = _choices_have_content(frame.get("choices")) \
        or _delta_has_content(frame.get("delta")) \
        or bool(str(frame.get("text") or "").strip())
    code = str(frame.get("error_code") or "").strip()
    error_obj = frame.get("error") if isinstance(frame.get("error"), dict) else None
    if code:
        if code.lower() in ("0", "0000", "success"):
            return None
        if answer:
            return None
        message = "上游报告 %s" % code
        error_msg = str(frame.get("error_msg") or "").strip()
        if error_msg:
            message += "：%s" % error_msg
        for item in frame.get("details") or []:
            if not isinstance(item, dict):
                continue
            detail = str(item.get("error_msg")
                         or item.get("error_code") or "").strip()
            if detail and detail not in message and ":" not in detail:
                message += "（%s）" % detail
                break
    elif error_obj is not None:
        if answer:
            return None
        message = str(error_obj.get("message") or error_obj.get("msg")
                      or "上游返回错误").strip()
        code = str(error_obj.get("code") or error_obj.get("type") or "").strip()
    else:
        return None
    if "benefit not found" in message.lower():
        message += ("（该账号还没有福利档案，余额查询会自动向官方注册，"
                    "稍等片刻重试即可）")
    lowered = message.lower()
    status = 502
    if "insufficient quota" in lowered or "quota exceeded" in lowered:
        status = 403
    elif code == "429" or "429" in code or "rate limit" in lowered \
            or "too many" in lowered:
        status = 429
    return {"code": code, "message": message, "status": status}


class CodeArtsStream(object):
    """把 CodeArts 的 OpenAI 兼容 SSE 包装成核心消费面。

    - 首包门：prime() 读到首个可用增量前不交出流（空回答可触发换号）；
    - 流内错误：HTTP 200 里的 error_code 信封先吐错误帧再抛 HTTPError；
    - 只有 reasoning 没有 content 也算有内容（max_tokens 很小时上游只吐推理）；
    - 会话槽在流结束/出错/close 时释放，且只释放一次。
    """

    def __init__(self, resp, model, account, release=None, log=None):
        self._resp = resp
        self._model = model
        self._account = account
        self._release = release or (lambda: None)
        self._released = False
        self._closed = False
        self._log = log
        self._buf = b""
        self._pending = []
        self._error = None
        self._done = False
        self._produced = False
        self._saw_answer = False
        self._finish_seen = False
        self._tool_seen = False
        self._usage = None
        self._chat_id = "chatcmpl-codearts-" + secrets.token_hex(8)
        self._created = int(time.time())

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
        idx = self._buf.index(b"\n")
        line = self._buf[:idx + 1]
        self._buf = self._buf[idx + 1:]
        return line

    def _read_event(self):
        data_lines = []
        while True:
            line = self._read_raw_line()
            if line is None:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if not text:
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

    def _release_once(self):
        if self._released:
            return
        self._released = True
        try:
            self._release()
        except Exception:
            pass

    def _finish_chunk(self):
        reason = "tool_calls" if self._tool_seen else "stop"
        return {
            "id": self._chat_id,
            "object": "chat.completion.chunk",
            "created": self._created,
            "model": self._model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
        }

    def _fail(self, fault):
        message = fault.get("message") or "CodeArts 上游错误"
        status = int(fault.get("status") or 502)
        account = self._account
        if status == 403:
            account.note_balance_cooled("CodeArts 额度不足（403）", detail=message)
        elif status == 429:
            account.note_error("CodeArts 限流（流内 429）", cooldown=60,
                               detail=message)
        else:
            account.note_failure("CodeArts 流内错误：%s" % message)
        url = str(BASE).rstrip("/") + CHAT_PATH
        # HTTPError.code 必须是 HTTP 状态码：核心与开流循环都用 int(code) 判定；
        # 上游业务码另挂属性，不覆盖状态码。
        error = urllib.error.HTTPError(url, status, message, None, None)
        error.upstream_code = fault.get("code") or ""
        self._error = error
        self._done = True
        self._release_once()
        self._pending.append({
            "error": {"message": message, "type": "upstream_error",
                      "code": status},
        })
        if self._log:
            try:
                self._log("codearts stream error: %s (%s)" % (message[:160], status))
            except Exception:
                pass

    def _normalize(self, frame):
        choices = frame.get("choices") if isinstance(frame, dict) else None
        if not isinstance(choices, list):
            choices = []
        usage = frame.get("usage") if isinstance(frame.get("usage"), dict) else None
        if not choices and usage is None:
            return None
        out = {
            "id": str(frame.get("id") or self._chat_id),
            "object": "chat.completion.chunk",
            "created": int(frame.get("created") or self._created),
            "model": self._model,
            "choices": choices,
        }
        if usage is not None:
            self._usage = usage
            out["usage"] = usage
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            if _delta_has_content(delta) \
                    or str(choice.get("text") or "").strip():
                self._saw_answer = True
                self._produced = True
            if delta.get("tool_calls"):
                self._tool_seen = True
            if choice.get("finish_reason"):
                self._finish_seen = True
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
            data = self._read_event()
            if data is None:
                if not self._saw_answer:
                    self._fail({
                        "status": 502,
                        "message": "CodeArts 上游返回了空回答"
                                   "（流结束但没有任何内容）",
                    })
                    continue
                self._done = True
                self._release_once()
                if not self._finish_seen:
                    self._pending.append(self._finish_chunk())
                continue
            if data.strip() == "[DONE]":
                if not self._saw_answer:
                    self._fail({
                        "status": 502,
                        "message": "CodeArts 上游返回了空回答"
                                   "（只有 [DONE]，没有任何内容）",
                    })
                    continue
                self._done = True
                self._release_once()
                if not self._finish_seen:
                    self._pending.append(self._finish_chunk())
                continue
            try:
                frame = json.loads(data)
            except Exception:
                continue
            if not isinstance(frame, dict):
                continue
            fault = stream_frame_fault(frame)
            if fault is not None:
                self._fail(fault)
                continue
            chunk = self._normalize(frame)
            if chunk is not None:
                return chunk

    @property
    def error(self):
        return self._error

    def prime(self):
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
        self._release_once()
        try:
            self._resp.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _chat_headers(upstream_model, benefit):
    headers = [
        ("Content-Type", "application/json"),
        ("Accept", "text/event-stream"),
        ("X-Plugin-Version", "Vscode_%s" % PLUGIN_VERSION),
        ("X-Language", LANGUAGE),
        ("plugin-name", PLUGIN_NAME),
        ("plugin-version", PLUGIN_VERSION),
        ("model-id", upstream_model),
        ("model-name", upstream_model),
        ("x-model-id", upstream_model),
    ]
    if benefit:
        headers.append(("maas_type", "benefit"))
    return headers


def _retry_after(headers):
    try:
        value = float((headers or {}).get("Retry-After") or 0)
        return min(300.0, max(1.0, value))
    except Exception:
        return 60.0


def _http_error(url, status, message):
    return urllib.error.HTTPError(url, int(status), str(message), None, None)


def _post_chat(account, credential, url, data, upstream_model, benefit,
               header_timeout, connect_timeout, idle_timeout):
    headers = sign_headers("POST", url,
                           _chat_headers(upstream_model, benefit),
                           data, credential, False)
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers=dict(headers))
    request.wb_exact_headers = list(headers)
    resp = net.urlopen(request, timeout=header_timeout,
                       proxy=getattr(account, "proxy", "") or "",
                       connect_timeout=connect_timeout)
    net.set_stream_idle_timeout(resp, idle_timeout)
    return resp


def open_stream(ctx, payload, session_key=None, realm=None):
    """选号 → 凭据续期 → 本地并发闸 → 签名发送 → 首包门 → 交出流。"""
    pool = getattr(ctx, "pool", None)
    realm = realm or REALM
    model = str(payload.get("model") or "").strip()
    if model.lower().startswith(REALM + "/"):
        model = model[len(REALM) + 1:].strip()
    if not model:
        raise RuntimeError("codearts: empty model")
    models_list = live_models(REALM, ctx=ctx)
    if not models_list:
        raise _http_error(
            BASE, 503,
            "CodeArts 模型目录还没拉取到：请先在模型页对该账号执行一次「刷新模型清单」")
    entry = resolve_model(model, models_list)
    if entry is None:
        raise _http_error(
            BASE, 404,
            "CodeArts 目录里没有模型「%s」（大小写已归一，仍匹配不到）" % model)
    upstream_model = entry["id"]
    benefit = _is_benefit_model(entry)

    body = upstream_body.build_upstream_body(dict(payload), ctx.system_prompt)
    body["model"] = upstream_model
    body["stream"] = True
    data = upstream_body.encode_upstream_body(body)
    url = str(BASE).rstrip("/") + CHAT_PATH
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    connect_timeout = ctx.upstream_connect_timeout()
    total = max(1, pool.count_ready(realm=REALM, model=model)) if pool else 1
    # +1：401 强制续期后重试同号要多占一个尝试位
    attempts, deadline = net.request_budget(total + 1)
    tried = set()
    last_error = None
    last_429 = None
    last_429_detail = ""
    last_busy = ""

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        account = pool.pick_for_session(
            realm=REALM, session_key=session_key, exclude=tried,
            model=model) if pool else None
        if account is None:
            break
        if account.realm != REALM:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        fresh = ensure_fresh(account)
        if not fresh.get("ok"):
            last_error = _http_error(
                url, fresh.get("status") or 503,
                "CodeArts 账号 %s：%s" % (str(account.uid)[:8],
                                       fresh.get("message") or "凭据不可用"))
            _log("account %s credential unavailable: %s"
                 % (str(account.uid)[:8], fresh.get("message")), ctx)
            continue
        permit = acquire_session(account, fresh["credential"])
        if not permit.get("acquired"):
            last_busy = permit.get("message") or "并发已满"
            last_error = _http_error(url, 409, "CodeArts %s" % last_busy)
            continue

        response = None
        current = fresh["credential"]
        try:
            response = _post_chat(
                account, current, url, data, upstream_model, benefit,
                header_timeout, connect_timeout, idle_timeout)
        except urllib.error.HTTPError as exc:
            permit["release"]()
            detail = net.read_http_error(exc, 600).decode("utf-8", "replace")
            if exc.code == 401:
                forced = ensure_fresh(account, force=True)
                if forced.get("ok"):
                    retry_permit = acquire_session(account, forced["credential"])
                    if retry_permit.get("acquired"):
                        current = forced["credential"]
                        permit = retry_permit
                        try:
                            response = _post_chat(
                                account, current, url, data, upstream_model,
                                benefit, header_timeout, connect_timeout,
                                idle_timeout)
                        except urllib.error.HTTPError as exc2:
                            permit["release"]()
                            exc = exc2
                            detail = net.read_http_error(
                                exc2, 600).decode("utf-8", "replace")
                        except Exception as exc2:
                            permit["release"]()
                            if net.looks_like_local_network(exc2):
                                last_error = exc2
                            else:
                                account.note_unknown_failure(str(exc2)[:120])
                                last_error = exc2
                            continue
                    else:
                        last_busy = retry_permit.get("message") or "并发已满"
                        last_error = _http_error(url, 409, "CodeArts %s" % last_busy)
                        continue
                else:
                    account.token_expired = True
                    account.last_error = forced.get("message") or "续期失败"
                    last_error = _http_error(
                        url, 401, "CodeArts 账号 %s 续期失败，请重新登录"
                                  % str(account.uid)[:8])
                    continue
            if response is None:
                if upstream_errors.is_input_too_large(detail):
                    raise _http_error(
                        url, 413,
                        "CodeArts 输入过大（不罚号）：%s" % detail[:300])
                if exc.code == 403:
                    account.note_balance_cooled(
                        "CodeArts 额度不足（HTTP 403）", detail=detail)
                    last_error = exc
                elif exc.code == 429:
                    wait = _retry_after(getattr(exc, "headers", None))
                    account.note_error(
                        "CodeArts 限流（HTTP 429）", cooldown=wait, detail=detail)
                    last_error, last_429 = exc, exc
                    last_429_detail = detail
                elif exc.code == 404:
                    account.note_error(
                        "CodeArts 模型不可用（HTTP 404）", model=model,
                        cooldown=3600, detail=detail)
                    last_error = exc
                elif exc.code == 401:
                    account.note_error("CodeArts 凭证失效（HTTP 401）",
                                       cooldown=60, detail=detail)
                    last_error = exc
                elif exc.code == 400:
                    account.last_error = "CodeArts 上游拒绝请求（400）：%s" % detail[:200]
                    raise _http_error(
                        url, 400,
                        "CodeArts 上游拒绝请求（400）：%s" % detail[:300])
                else:
                    account.note_failure("HTTP %s：%s" % (exc.code, detail[:120]))
                    last_error = exc
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                _log("account %s failed HTTP %s (%s), rotating"
                     % (str(account.uid)[:8], exc.code, detail[:100]), ctx)
                continue
        except Exception as exc:
            permit["release"]()
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

        stream = CodeArtsStream(response, model, account,
                                release=permit["release"], log=ctx.log)
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
                    url, status, "CodeArts 账号 %s：%s（已自动换号）"
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
    if last_busy:
        raise _http_error(url, 409, "CodeArts %s" % last_busy)
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or do not support this model" % REALM)


# ===========================================================================
# 连通性探测（面板「测试连通性」）
# ===========================================================================
def probe_account(account, timeout=20):
    fresh = ensure_fresh(account)
    if not fresh.get("ok"):
        return {"ok": False, "message": fresh.get("message") or "凭据不可用"}
    entries = []
    try:
        entries = _fetch_models_for_account(account, fresh["credential"])
    except Exception:
        entries = []
    if not entries:
        entries = _cached_entries()
    disabled = set(getattr(account, "disabled_models", None) or [])
    entry = next((item for item in entries
                  if str(item.get("id") or "").lower() not in disabled), None)
    if entry is None:
        return {"ok": False, "message": "CodeArts 模型目录为空（trial 账号可能无模型）"}
    permit = acquire_session(account, fresh["credential"])
    if not permit.get("acquired"):
        return {"ok": False, "message": permit.get("message") or "并发已满"}
    try:
        body = {
            "model": entry["id"],
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": True,
        }
        data = upstream_body.encode_upstream_body(body)
        url = str(BASE).rstrip("/") + CHAT_PATH
        started = time.time()
        response = _post_chat(
            account, fresh["credential"], url, data, entry["id"],
            _is_benefit_model(entry), timeout, None, 0)
        try:
            raw = response.read(256)
        finally:
            try:
                response.close()
            except Exception:
                pass
        if not raw:
            return {"ok": False, "message": "上游未返回任何数据（流已关闭）"}
        elapsed = int((time.time() - started) * 1000)
        return {"ok": True, "model": entry["id"], "latencyMs": elapsed,
                "message": "连通正常（%s，%d ms）" % (entry["id"], elapsed)}
    except urllib.error.HTTPError as exc:
        detail = net.read_http_error(exc, 400).decode("utf-8", "replace")
        return {"ok": False, "code": exc.code,
                "message": "HTTP %s：%s" % (exc.code, detail[:200] or exc)}
    except Exception as exc:
        return {"ok": False, "message": "请求异常: %s" % exc}
    finally:
        permit["release"]()


# ===========================================================================
# 渠道适配器
# ===========================================================================
def _refresh_account(account):
    fresh = ensure_fresh(account, force=True)
    if not fresh.get("ok"):
        account.last_error = fresh.get("message") or "CodeArts 续期失败"
        return False
    return True


def _do_welfare(account, source):
    result = checkin_for_account(
        account, trigger="scheduler" if source == "auto" else "manual")
    if result.get("ok") and int(result.get("claimed") or 0) > 0:
        return {"status": "ok", "message": result.get("message") or "签到成功"}
    if result.get("ok"):
        return {"status": "already",
                "message": result.get("message") or "今日已签到"}
    if result.get("authError"):
        return {"status": "error",
                "message": result.get("message") or "CodeArts 凭证失效"}
    return {"status": "error",
            "message": result.get("message") or result.get("error") or "签到失败"}


def scheduler_tasks(ctx):
    def run(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="codearts_welfare", source=source,
            ready=lambda acc: (getattr(acc, "realm", "") == REALM
                               and getattr(acc, "enabled", False)
                               and (getattr(acc, "access_token", "")
                                    or getattr(acc, "refresh_token", ""))),
            action=lambda acc: _do_welfare(acc, source))

    return [("codearts_welfare", "CodeArts 每日签到", run,
             {"enabled": True, "hours": [9, 15], "realm": REALM})]


class CodeArtsAdapter(registry.ChannelAdapter):
    id = REALM
    label = LABEL
    realms = (REALM,)
    route_prefixes = (REALM,)
    capabilities = frozenset({
        registry.CAP_CHAT, registry.CAP_RESPONSES, registry.CAP_MODELS,
        registry.CAP_ACCOUNTS, registry.CAP_CHECKIN, registry.CAP_SCHEDULER,
        registry.CAP_PROXY_SLOT, registry.CAP_PASTE_TOKEN,
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
            "login_account_fn": _login_account_from_token,
        })

    # ---- 登录 ----
    def start_login(self, ctx, realm, platform="CLI"):
        if realm != REALM:
            return None
        return start_login(ctx)

    def poll_login(self, ctx, state):
        if not state:
            return None
        with _LOGIN_LOCK:
            known = state in _LOGIN_SESSIONS
        if not known:
            return None
        return login_poll(ctx, state)

    def submit_login(self, ctx, state, raw_callback):
        with _LOGIN_LOCK:
            known = state in _LOGIN_SESSIONS
        if not known:
            return None
        return login_submit(ctx, state, raw_callback)

    def cancel_login(self, ctx, state):
        return login_cancel(state)

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
                "label": "华为云码道",
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
                "action": "签到",
                "pending": "未签到",
                "done": "已签到",
                "pendingTitle": "今日尚未签到（「签到」按钮会领取每日签到积分和新用户积分）",
                "doneTitle": "今日已签到：",
                "submitted": "签到已提交",
            },
        }


def install(ctx):
    """注册本渠道（入口调用；新增渠道照此一行接入）。"""
    registry.register(CodeArtsAdapter(), ctx)
