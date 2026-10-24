# -*- coding: utf-8 -*-
"""core/net.py —— 出站网络层（本地自研，上游无对应）

统一所有出站 HTTP 的入口，两件事：

1. `urlopen(req, timeout, proxy)`：可选的连接复用池（core/upstream_pool.py，
   自上游移植）+ urllib 回退。账号配了代理时按代理串分流；池处理不了的请求
   （非 http(s)、非 HTTP 代理、需要跟随的 3xx）由 PoolBypass 回退到原路径，
   行为与未启用池时完全一致。
2. `http_json(...)`：urlopen + JSON 解码 + 对 TLS 抖动/5xx 做有限重试。

依赖方向：本模块只依赖 core/upstream_pool.py，不 import 任何渠道或账号模块。
"""

import base64
import errno
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from core import upstream_pool


class TLSVerifyError(RuntimeError):
    """The upstream certificate chain is not trusted by this process."""


TLS_VERIFY_HINT = (
    "TLS 证书校验失败：上游证书链里有本机不信任的证书。常见于公司代理、"
    "Clash/Surge 等 HTTPS 解密，或 macOS 上 Python 没读到系统钥匙串里的根证书。"
    "把签发该证书的根证书导出为 PEM，设置环境变量 "
    "WB_CA_BUNDLE=/path/to/ca.pem 后重启网关；也可以设置 SSL_CERT_FILE。"
)


def is_tls_verify_error(exc):
    """True for certificate/hostname verification failures.

    These are configuration errors, not transient network faults: retrying the
    same request produces the same result and hides the real cause behind a
    502. The check looks at URLError.reason as well, because urllib wraps the
    original SSLCertVerificationError there.
    """
    reason = getattr(exc, "reason", None)
    text = "%s %s %s" % (type(exc).__name__, exc, "" if reason is None else reason)
    lower = text.lower()
    return any(marker in lower for marker in (
        "certificate_verify_failed",
        "certificate verify failed",
        "self-signed certificate",
        "self signed certificate",
        "unable to get local issuer certificate",
        "unable to get issuer certificate",
        "certificate has expired",
        "hostname mismatch",
    ))


def tls_verify_hint(exc=None):
    if exc is None:
        return TLS_VERIFY_HINT
    return "%s 原始错误：%s" % (TLS_VERIFY_HINT, exc)


def retryable(exc):
    """Transient network faults worth another attempt (TLS resets, timeouts, 5xx)."""
    if is_tls_verify_error(exc):
        # 配置错误不是瞬时故障：重试结果一样，只会把真正的原因捂在 502 后面。
        return False
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500
    if isinstance(exc, urllib.error.URLError):
        return True
    if isinstance(exc, (TimeoutError, ConnectionResetError, ConnectionAbortedError, OSError)):
        return True
    return False


def _network_error_details(exc):
    """取被包了一层的系统错误码，不依赖本机错误文案的语言。"""
    errors = (exc, getattr(exc, "reason", None))
    text = " ".join("%s %s" % (type(error).__name__, error)
                    for error in errors if error is not None).lower()
    # HTTPError 也继承 OSError，但它的 errno/winerror 可能委托给已关闭的
    # response；HTTP 状态码不是 OS 错误码，因此不对它取这两个属性。
    codes = {getattr(error, attr, None) for error in errors
             if not isinstance(error, urllib.error.HTTPError)
             for attr in ("errno", "winerror")}
    # 只认完整的数字：旧的子串匹配 "errno 100" 会误中 Windows ECONNRESET(10054)
    codes.update(int(code) for code in re.findall(
        r"\b(?:errno|winerror)\s+(-?\d+)\b", text))
    return codes, text


#: 本机断网（DNS 解析失败 / 网卡未就绪 / 路由不可达）的文案兜底
LOCAL_NETWORK_MARKERS = (
    "gaierror", "getaddrinfo failed", "name or service not known",
    "nodename nor servname", "temporary failure in name resolution",
    "network is unreachable", "network is down", "no route to host",
)


def is_transient(exc):
    """网络层抖动，值得重试而不是冷却账号（文案 + OS 错误码）。"""
    if is_tls_verify_error(exc):
        return False
    codes, text = _network_error_details(exc)
    # ECONNREFUSED(10061) 故意不在此列：通常是账号代理没起来，按账号故障
    # 记一次并冷却，池子才会换下一把，而不是反复重试同一个死出口。
    if codes.intersection((errno.EPIPE, errno.ECONNABORTED, errno.ECONNRESET,
                           errno.ETIMEDOUT, 10053, 10054, 10060)):
        return True
    markers = (
        "ssl", "unexpected_eof", "eof occurred", "remote end closed",
        "connection reset", "connection aborted", "connectionreseterror",
        "connectionabortederror", "timed out", "timeout", "temporarily unavailable",
        "bad gateway", "502", "503", "504", "incompleteread",
    )
    return any(m in text for m in markers)


def looks_like_local_network(exc):
    """本机没网：DNS 失败 / 网卡未就绪 / 路由不可达。

    这类失败账号连一个字节都没发出去，不能按账号故障罚号。
    """
    if isinstance(exc, socket.gaierror):
        return True
    codes, lower = _network_error_details(exc)
    if codes.intersection((errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH,
                           -2, -3, -5, 100, 101, 113,
                           10050, 10051, 10065, 11001)):
        return True
    return any(marker in lower for marker in LOCAL_NETWORK_MARKERS)


def http_error_detail(exc, limit=600):
    """读一次 HTTPError 响应体，并缓存回异常对象供后续读取。

    渠道要先看 body 里的业务 code 才能决定罚不罚号，而核心随后还要把同一
    份 body 交给客户端；不缓存的话第二次 read() 只能拿到空。
    """
    try:
        raw = exc.read(limit)
    except Exception:
        return ""
    try:
        exc.wb_body = raw
    except Exception:
        pass
    return raw.decode("utf-8", "replace")


def read_http_error(exc, limit=600):
    """取 http_error_detail 缓存的 body；没缓存过就现读一次。"""
    raw = getattr(exc, "wb_body", None)
    if raw is not None:
        return raw[:limit]
    try:
        return exc.read(limit)
    except Exception:
        return b""


# ---------------------------------------------------------------------------
# 代理串解析与退避（自 upstream_pool 移入公开，供连接池与各通道共用）
# ---------------------------------------------------------------------------

def parse_proxy(proxy_str):
    """拆分代理串 -> dict(scheme, user, password, host, port)，非 HTTP 代理返回 None。

    语义与 urllib.request._parse_proxy 对齐（支持 http://user:pass@host:port 与
    authority 形式 host:port），但只认 http 代理：socks5:// 之类的串返回 None，
    调用方回退到 urllib 原路径（那条路本来也不支持它们），不在这里发明新行为。
    """
    raw = str(proxy_str or "").strip()
    if not raw:
        return None
    if "://" in raw:
        scheme, _, rest = raw.partition("://")
        if scheme.strip().lower() != "http":
            return None
        authority = rest.split("/", 1)[0]
    else:
        authority = raw                      # authority 形式：host:port
    user = password = None
    if "@" in authority:
        userinfo, _, authority = authority.rpartition("@")
        user, _, password = userinfo.partition(":")
        user = urllib.parse.unquote(user)
        password = urllib.parse.unquote(password) if password else password
    hostport = urllib.parse.unquote(authority)
    if hostport.startswith("["):             # IPv6: [::1]:8080 / [::1]
        host, sep, rest = hostport[1:].partition("]")
        port = rest.lstrip(":") if sep else ""
    elif ":" in hostport:
        host, _, port = hostport.rpartition(":")
    else:
        host, port = hostport, ""
    if not host:
        return None
    if port and not port.isdigit():
        # 非数字端口：urllib 的 HTTPConnection 会抛 InvalidURL。这里当作「池处理
        # 不了」，回退原路径，错误形状与改动前完全一致。
        return None
    return {"scheme": "http", "user": user or "", "password": password or "",
            "host": host, "port": port}


def proxy_basic_auth(user, password):
    """HTTP 代理的 Basic 认证头值（user/password 任一为空返回空串）。

    与 urllib ProxyHandler.proxy_open 一致：user 与 password 都非空才发认证头；
    userinfo 的 URL 解码由 parse_proxy 负责，这里不再处理。
    """
    if not user or not password:
        return ""
    creds = "%s:%s" % (user, password)
    return "Basic " + base64.b64encode(creds.encode()).decode("ascii")


def exponential_backoff(step, base, cap):
    """指数退避：step 从 0 起每步翻倍，封顶 cap；步数钳到 20 防溢出。"""
    return min(float(base) * (2 ** min(max(0, int(step)), 20)), float(cap))


_OPENER_CACHE = {}
_OPENER_LOCK = threading.Lock()


def opener_for_proxy(proxy):
    """构建（并缓存）绑定到单个出口代理的 urllib opener；空串返回 None。"""
    proxy = str(proxy or "").strip()
    if not proxy:
        return None
    with _OPENER_LOCK:
        opener = _OPENER_CACHE.get(proxy)
        if opener is None:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            _OPENER_CACHE[proxy] = opener
        return opener


def urlopen(req, timeout=30, proxy="", connect_timeout=None):
    """尊重单账号代理的 urlopen，默认走连接复用池。

    池返回的错误语义与 urllib 对齐：HTTP >= 400 抛 HTTPError（body 已读好），
    发送阶段 OSError 抛 URLError。池不可用的请求回退 urllib 原路径。
    connect_timeout 只在池路径生效（TCP/TLS 建连的独立时限，与读超时分离）；
    urllib 回退路径无法分离建连与读，仍按 timeout 一档。
    """
    if upstream_pool.enabled():
        try:
            return upstream_pool.urlopen(req, timeout=timeout, proxy=proxy,
                                         connect_timeout=connect_timeout)
        except upstream_pool.PoolBypass:
            pass
    opener = opener_for_proxy(proxy)
    if opener is None:
        return urllib.request.urlopen(req, timeout=timeout)
    return opener.open(req, timeout=timeout)


def request_budget(candidates):
    """账号轮换的开销上限，返回 (尝试次数, 总期限 monotonic 时刻)。

    逐账号重试原本只受候选数约束、没有总时限——一个每步都吃满读超时的
    死出口能把客户端拖到分钟级（网关「页面网络错误」的来源之一）。默认
    最多试 6 个账号或 300 秒，先到为准；环境变量可调，下限保底防误配。
    """
    candidates = max(1, int(candidates or 1))
    try:
        cap = int(os.environ.get("WB_UPSTREAM_MAX_ATTEMPTS") or "6")
    except ValueError:
        cap = 6
    cap = min(max(1, cap), candidates)
    try:
        seconds = float(os.environ.get("WB_UPSTREAM_DEADLINE_SECONDS") or "300")
    except ValueError:
        seconds = 300.0
    return cap, time.monotonic() + max(30.0, seconds)


def http_json(url, data=None, method=None, headers=None, timeout=30,
              retries=3, backoff=1.0, log=None, proxy=""):
    """urlopen + JSON 解码，对瞬时网络错误有限重试。

    国内网络与 CDN 边缘经常在 TLS 握手阶段断流（SSL: UNEXPECTED_EOF_WHILE_
    READING），重试一次几乎都能成功，因此所有上游调用统一走这里。
    """
    attempts = max(1, int(retries or 1))
    last = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            data=data,
            method=method or ("POST" if data is not None else "GET"),
            headers=headers or {},
        )
        try:
            with urlopen(req, timeout=timeout, proxy=proxy) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            last = exc
            if attempt >= attempts or not retryable(exc):
                break
            if log:
                log("network retry %d/%d after %s" % (attempt, attempts, exc))
            time.sleep(backoff * attempt)
    if last is not None and is_tls_verify_error(last):
        raise TLSVerifyError(tls_verify_hint(last)) from last
    raise last


def set_stream_idle_timeout(response, seconds):
    """把流式阶段的 socket 超时切成 idle 档（有数据就续命）。

    响应头超时与流内 idle 超时是两档：header 档兜「连上但不回话」，
    idle 档兜「流到一半卡死」。各渠道开流成功后统一调这里。
    """
    try:
        if seconds and seconds > 0:
            response.fp.raw._sock.settimeout(seconds)
    except Exception:
        try:
            sock = getattr(getattr(response, "fp", None), "raw", None)
            sock = getattr(sock, "_sock", None)
            if sock is not None:
                sock.settimeout(seconds)
        except Exception:
            pass
