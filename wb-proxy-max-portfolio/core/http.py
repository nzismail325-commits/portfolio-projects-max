# -*- coding: utf-8 -*-
"""core/http.py —— HTTP 服务装配与通用工具（本地自研，上游无对应）

只做三件事：
1. `BaseHandler`：JSON/SSE 响应、鉴权（API Key / 面板会话）、CORS、错误形状；
2. 路由表：按路径前缀把请求交给各路由组（`ROUTES` 由各模块注册）；
3. `serve()`：线程池 HTTP 服务 + 并发槽。

路由组不自建服务：每个模块（core/proxy_api、panel/routes、integrations/*）
提供一个 handler 对象，声明自己负责的前缀与处理函数。这样加一条路由不用改
入口，而入口也永远只有「装配」这一件事。
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from infra import privacy

#: 对话类请求的并发上限（默认按可用账号数自动，下限 128）
_CHAT_SLOTS_ENV = os.environ.get("WB_MAX_CONCURRENT_CHAT", "auto").strip().lower()
CHAT_SLOTS_AUTO = _CHAT_SLOTS_ENV in ("auto", "pool", "dynamic")
CHAT_SLOTS_FLOOR = 128
try:
    MAX_CONCURRENT_CHAT = CHAT_SLOTS_FLOOR if CHAT_SLOTS_AUTO else int(_CHAT_SLOTS_ENV)
except ValueError:
    MAX_CONCURRENT_CHAT = CHAT_SLOTS_FLOOR
#: 排队等待上限：等不到槽位就回 503，避免无限堆积
CHAT_SLOT_WAIT_SECONDS = float(os.environ.get("WB_CHAT_SLOT_WAIT", "30"))


class _CountingGate(object):
    """计数闸门：BoundedSemaphore 的等价物，但容量可以安全放大。

    threading.BoundedSemaphore 无法在持有中放大额度——重建对象会丢掉所有
    正在等待的调用者，还会让新旧对象各自计数（在途请求释放到旧对象上，
    计数虚增）。这里用条件变量 + 计数器：acquire 超时返回 False，release
    唤醒等待者，grow_to 只增不减并唤醒全部等待者。
    """

    def __init__(self, capacity):
        self._cond = threading.Condition()
        self._capacity = max(1, int(capacity))
        self._held = 0

    def acquire(self, timeout=None):
        with self._cond:
            if not self._cond.wait_for(lambda: self._held < self._capacity,
                                       timeout):
                return False
            self._held += 1
            return True

    def release(self):
        with self._cond:
            self._held = max(0, self._held - 1)
            self._cond.notify_all()

    def grow_to(self, capacity):
        """只增不减地放大容量（在途请求的额度永不被收回）；返回生效容量。"""
        with self._cond:
            if capacity > self._capacity:
                self._capacity = capacity
                self._cond.notify_all()
            return self._capacity


_chat_slots = _CountingGate(MAX_CONCURRENT_CHAT)

#: 允许跨域读取的 API 前缀（管理接口一律不发 CORS 头）
CORS_PATH_PREFIXES = ("/v1", "/chat", "/completions", "/models", "/responses")
MANAGEMENT_PATH_PREFIXES = ("/v1/usage", "/usage", "/accounts", "/settings",
                            "/tasks", "/scheduler", "/panel", "/logs")


def cors_allowed(path):
    path = (path or "").split("?")[0]
    if path.startswith(MANAGEMENT_PATH_PREFIXES):
        return False
    return path.startswith(CORS_PATH_PREFIXES)


def resize_chat_slots(ready_accounts):
    """按可用账号数放大并发槽（只增不减，避免在途请求的额度被收回）。"""
    global MAX_CONCURRENT_CHAT
    if not CHAT_SLOTS_AUTO:
        return MAX_CONCURRENT_CHAT
    try:
        wanted = max(CHAT_SLOTS_FLOOR, int(ready_accounts or 0))
    except (TypeError, ValueError):
        return MAX_CONCURRENT_CHAT
    MAX_CONCURRENT_CHAT = _chat_slots.grow_to(wanted)
    return MAX_CONCURRENT_CHAT


def acquire_chat_slot(timeout=None):
    """取一个对话并发槽；超时返回 False（调用方回 503）。"""
    timeout = CHAT_SLOT_WAIT_SECONDS if timeout is None else timeout
    return _chat_slots.acquire(timeout=timeout)


def release_chat_slot():
    _chat_slots.release()


class Route(object):
    """一条路由：method + 前缀 + 处理函数。"""

    __slots__ = ("method", "prefix", "func", "needs_auth", "needs_panel",
                 "exact")

    def __init__(self, method, prefix, func, needs_auth=True, needs_panel=False,
                 exact=False):
        self.method = method.upper()
        self.prefix = prefix
        self.func = func
        self.needs_auth = needs_auth
        self.needs_panel = needs_panel
        self.exact = exact

    def matches(self, method, path):
        if self.method not in ("*", method):
            return False
        if self.exact:
            return path == self.prefix
        return path.startswith(self.prefix)


class Router(object):
    """路由表：按注册顺序取第一条命中的路由。"""

    def __init__(self):
        self._routes = []
        self._lock = threading.Lock()

    def add(self, method, prefix, func, needs_auth=True, needs_panel=False,
            exact=False):
        with self._lock:
            self._routes.append(Route(method, prefix, func, needs_auth,
                                      needs_panel, exact))

    def resolve(self, method, path):
        with self._lock:
            for route in self._routes:
                if route.matches(method, path):
                    return route
        return None

    def routes(self):
        with self._lock:
            return list(self._routes)


ROUTER = Router()


class BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wb-proxy-max/1.0"
    #: 读下一请求（含请求体）的空闲上限（秒）：HTTP/1.1 keep-alive 下，客户端
    #: 断开或挂起时线程能按期回收，不会每个空闲连接永久占一个线程。SSE 只写
    #: 不读、正常请求远快于此，均不受影响。
    timeout = 75
    #: 由入口注入的 AppContext
    ctx = None

    # ------------------------------------------------------------ 生命周期
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def finish(self):
        try:
            super().finish()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            pass

    def log_message(self, fmt, *args):
        """访问日志：只作为控制台/文件噪声输出，不进运行日志环与落库。

        BaseHTTPRequestHandler 会对每个请求调用这里；若走 ctx.log()，面板
        日志会被 GET /health 这类心跳刷满，真正的运行事件反而看不见。
        """
        writer = getattr(self.ctx, "access_log", None) if self.ctx else None
        if writer is None:
            return
        try:
            writer(fmt % args)
        except Exception:
            pass

    # ------------------------------------------------------------ 响应
    def _cors(self):
        if cors_allowed(self.path):
            self.send_header("Access-Control-Allow-Origin", "*")

    def json(self, code, obj):
        # 面板载荷统一脱敏手机号（copy-on-write，无命中零拷贝）
        if self.panel_ok():
            obj = privacy.redact(obj)
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def error(self, code, message, err_type="server_error", extra=None):
        payload = {"error": {"message": message, "type": err_type, "code": code}}
        if extra:
            payload["error"].update(extra)
        self.json(code, payload)

    def rate_limited(self, exc):
        """429 + Retry-After：让客户端退避而不是 hammer。"""
        wait = max(1, int(getattr(exc, "wait", 60) or 60))
        detail = getattr(exc, "detail", "") or ""
        # 渠道给了人类可读说明（如连坐保护的整池暂停提示）时优先透传它，
        # 不再用笼统的限流话术盖掉。
        custom = getattr(exc, "message", "") or ""
        if custom:
            message = custom
        else:
            message = "upstream rate limit reached for this model; retry in %ds" % wait
            if detail:
                message += " - " + detail[:200]
        body = json.dumps({
            "error": {"message": message, "type": "rate_limit_error",
                      "code": 429, "retry_after": wait}
        }, ensure_ascii=False).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Retry-After", str(wait))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._cors()
        self.end_headers()

    def send_bytes(self, code, body, content_type, extra_headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------ 请求
    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except Exception:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw or "{}")
            self._body_drained = True
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def query(self):
        try:
            return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        except Exception:
            return {}

    def supplied_key(self):
        """调用方出示的 API Key：Authorization / x-api-key / ?key=。"""
        supplied = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if supplied:
            return supplied
        try:
            for name, value in self.headers.items():
                if name.lower() == "x-api-key" and str(value or "").strip():
                    return str(value).strip()
        except Exception:
            pass
        return (self.query().get("key") or [""])[0].strip()

    def panel_token(self):
        token = (self.headers.get("X-Panel-Token") or "").strip()
        if token:
            return token
        return (self.query().get("panel") or [""])[0].strip()

    def panel_ok(self):
        return bool(self.ctx and self.ctx.panel_ok(self.panel_token()))

    def peer_ip(self):
        try:
            return self.client_address[0]
        except Exception:
            return ""

    # ------------------------------------------------------------ 分发
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        # 预检结果让浏览器缓存一天，跨域客户端不必每个请求都先发 OPTIONS
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):
        self._dispatch("PUT")

    def _dispatch(self, method):
        path = urllib.parse.urlparse(self.path).path
        route = ROUTER.resolve(method, path)
        if route is None:
            return self.error(404, "not found", "invalid_request_error")
        if route.needs_panel and not self.panel_ok():
            return self.error(401, "panel password required", "invalid_request_error")
        if route.needs_auth:
            from core import authz
            if not authz.authorize(self):
                return self.error(401, "invalid api key", "invalid_request_error")
        try:
            # 同一 keep-alive 连接的多个请求共用本实例，标记必须逐请求重置
            self._body_drained = False
            result = route.func(self, path)
            # POST 带请求体而路由没读时，残留字节会污染 keep-alive 连接：
            # 下一请求被拼进请求行 → 501 Unsupported method（登录页 T-26 的根因）。
            # 在分发层统一排空兜底，路由不必各自记得读。
            if method == "POST" and self.headers.get("Content-Length"):
                try:
                    if int(self.headers.get("Content-Length")) \
                            and not self._body_drained:
                        self.rfile.read(int(self.headers.get("Content-Length")))
                except (ValueError, OSError):
                    pass
            return result
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as exc:
            if self.ctx is not None:
                try:
                    self.ctx.log("unhandled error on %s %s: %s" % (method, path, exc))
                except Exception:
                    pass
            try:
                return self.error(500, "internal error: %s" % str(exc)[:200])
            except Exception:
                return


class GatewayHTTPServer(ThreadingHTTPServer):
    """线程化 HTTP 服务（每请求一线程），仅覆盖监听积压队列。

    socketserver 默认 request_queue_size=5：并发突刺时来不及 accept 的连接
    被内核直接拒绝，外在表现就是「网关无法联通」。抬到 128 吃住百级并发。
    """

    request_queue_size = 128


def make_server(host, port, handler, ctx):
    handler.ctx = ctx
    return GatewayHTTPServer((host, port), handler)


def local_ip_addresses():
    """本机所有非回环 IPv4 地址（LAN 模式打印用）。"""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except Exception:
        pass
    return found
