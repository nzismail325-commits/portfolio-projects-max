# -*- coding: utf-8 -*-
"""panel/static.py —— 面板静态资源路由（本地自研，上游无对应）

把 `panel/` 目录按需暴露给浏览器：index.html、main.js、各目录下的 .js/.vue 源
（浏览器端用原生 ES module + Vue 全局构建，不需要打包器）、vendor 资源与主题图。

安全：只发送 panel/ 目录内的文件；路径穿越（..）一律 404。
"""
import mimetypes
import os

from core import http as http_mod

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

#: 明确的内容类型（避免 Windows 注册表把 .js 认成别的）
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def resolve(path):
    """面板路径 -> 磁盘绝对路径；越界或不存在返回 None。"""
    rel = path.lstrip("/")
    if rel in ("", "index.html", "dashboard", "ui"):
        rel = "index.html"
    target = os.path.normpath(os.path.join(PANEL_DIR, rel))
    if not target.startswith(PANEL_DIR + os.sep) and target != os.path.join(
            PANEL_DIR, "index.html"):
        return None
    if not os.path.isfile(target):
        return None
    return target


def serve(handler, path):
    target = resolve(path)
    if target is None:
        return handler.error(404, "not found", "invalid_request_error")
    try:
        stat = os.stat(target)
    except OSError as exc:
        return handler.error(404, "panel asset unavailable: %s" % exc)
    # 协商缓存：内容没变就 304 免回传。no-cache 保证浏览器每次仍来核对，
    # 文件一改 ETag 立刻失效，不会出现改了面板要强刷的问题。
    etag = 'W/"%x-%x"' % (stat.st_mtime_ns, stat.st_size)
    if (handler.headers.get("If-None-Match") or "").strip() == etag:
        handler.send_response(304)
        handler.send_header("ETag", etag)
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        return
    try:
        with open(target, "rb") as fh:
            body = fh.read()
    except Exception as exc:
        return handler.error(404, "panel asset unavailable: %s" % exc)
    ext = os.path.splitext(target)[1].lower()
    content_type = CONTENT_TYPES.get(ext) or mimetypes.guess_type(target)[0] \
        or "application/octet-stream"
    handler.send_bytes(200, body, content_type,
                       {"Cache-Control": "no-cache", "ETag": etag})


def install(router, ctx=None):
    router = router or http_mod.ROUTER
    # 根路径与面板静态资源：不需要 API Key（面板自己有密码登录）
    router.add("GET", "/", serve, needs_auth=False, exact=True)
    router.add("GET", "/index.html", serve, needs_auth=False, exact=True)
    router.add("GET", "/styles.css", serve, needs_auth=False, exact=True)
    router.add("GET", "/locale.js", serve, needs_auth=False, exact=True)
    router.add("GET", "/App.js", serve, needs_auth=False, exact=True)
    for prefix in ("/main.js", "/router/", "/api/", "/store/", "/views/",
                   "/components/", "/composables/", "/channels/", "/vendor/",
                   "/themes/"):
        router.add("GET", prefix, serve, needs_auth=False)
