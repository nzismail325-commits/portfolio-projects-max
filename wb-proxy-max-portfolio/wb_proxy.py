#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wb_proxy.py —— 入口与 HTTP 服务装配

本文件只做三件事：解析启动参数、装配 AppContext、挂载各路由组并启动服务。
任何业务逻辑都不在这里——路由组在各模块同文件，渠道在 integrations/。

    python wb_proxy.py                    # 127.0.0.1:8788，面板 + /v1
    python wb_proxy.py --lan              # 监听全部网卡（强制 API Key）
    python wb_proxy.py --port 9000 --quiet
"""
import argparse
import json
import os
import sys
import threading
import urllib.request

#: 路由组与渠道都要以仓库根为包根
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import authz  # noqa: E402
from core import context as context_mod  # noqa: E402
from core import http as http_mod  # noqa: E402
from core import proxy_api  # noqa: E402
from core import upstream_body  # noqa: E402
from auth import identity  # noqa: E402
from infra import logring  # noqa: E402
from infra import privacy  # noqa: E402
from infra import settings  # noqa: E402
from infra import webtools  # noqa: E402
from integrations import registry  # noqa: E402
from panel import routes as panel_routes  # noqa: E402

QUIET_MODE = False
LOG_FILE = None
LOG_FILE_MAX_LINES = 2000
#: 进程内日志环：面板 /logs 在落库关闭时读它；落库打开时同一行再进队列
LOG_RING = logring.RING
_log_lock = threading.Lock()


def _trim_file_log():
    """日志文件是有界环：只保留最新 N 行。"""
    if not LOG_FILE or not os.path.exists(LOG_FILE):
        return
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        if len(lines) > LOG_FILE_MAX_LINES:
            with open(LOG_FILE, "w", encoding="utf-8", errors="replace") as fh:
                fh.writelines(lines[-LOG_FILE_MAX_LINES:])
    except Exception:
        pass


def log(msg, level=None, tag=None):
    """控制台/文件输出（日志环与落库由 AppContext 统一记录，避免重复写）。"""
    line = "[wb-proxy-max] %s %s" % (time_stamp(), privacy.mask_text(str(msg)))
    if QUIET_MODE and LOG_FILE:
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with _log_lock:
                with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as fh:
                    fh.write(line + "\n")
            _trim_file_log()
        except Exception:
            pass
        return
    try:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def access_log(msg):
    """访问日志（每请求一行）：只写控制台/文件，不进日志环与落库。"""
    if not QUIET_MODE:
        try:
            sys.stderr.write(privacy.mask_text(str(msg)) + "\n")
            sys.stderr.flush()
        except Exception:
            pass


def time_stamp():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


def install_console_close_handler():
    """控制台窗口被关闭时释放端口（Windows 不会自动杀掉子进程）。"""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def _handler(event):
            if event in (2, 5, 6):      # CLOSE / LOGOFF / SHUTDOWN
                os._exit(0)
            return False

        handler = handler_type(_handler)
        if not ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True):
            return None
        return handler
    except Exception:
        return None


def _already_running(host, port):
    """端口上是否已经跑着本服务（只认自己人：ok + accounts 键）。"""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    try:
        with urllib.request.urlopen("http://%s:%s/health" % (probe_host, port),
                                    timeout=2) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("ok") is True and "accounts" in payload
    except Exception:
        return False


def _warm(ctx):
    """启动后台预热：积分、模型目录（失败只记日志，不挡服务）。"""
    try:
        from auth import accounts as accounts_mod
        for account in (ctx.pool.accounts if ctx.pool else []):
            if account.realm not in accounts_mod.REALM_CONFIGS:
                continue
            try:
                accounts_mod.fetch_credits_cached(account)
            except Exception as exc:
                log("warmup credits %s failed: %s" % (account.uid[:8], exc))
        from intel import catalog
        realms = [r for r in catalog.known_realms(ctx)]
        for realm in realms:
            try:
                catalog.fetch_models(realm=realm, log=log)
            except Exception as exc:
                log("warmup models %s failed: %s" % (realm, exc))
        log("warmup done")
    except Exception as exc:
        log("warmup failed: %s" % exc)


def main():
    global QUIET_MODE, LOG_FILE

    parser = argparse.ArgumentParser(
        description="WorkBuddy -> OpenAI-compatible gateway (refactored)")
    parser.add_argument("--host", default=os.environ.get("HOST") or "127.0.0.1")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("PORT") or "8788"))
    parser.add_argument("--lan", action="store_true",
                        help="listen on every interface (implies --host 0.0.0.0 "
                             "and forces an api key)")
    parser.add_argument("--api-key",
                        default=os.environ.get("API_KEY")
                        or os.environ.get("WB_PROXY_KEY") or None,
                        help="require this bearer token on /v1/* (optional)")
    parser.add_argument("--system-prompt", default=None,
                        help="system message injected when the request has none")
    parser.add_argument("--usage-dir", default=None,
                        help="where usage.jsonl / logs.databases live (default ./usage)")
    parser.add_argument("--accounts-dir", default=os.environ.get("ACCOUNTS_DIR") or None,
                        help="where per-account credential files live (default ./accounts)")
    parser.add_argument("--panel-password", default=None,
                        help="set the web panel password on startup (default: admin)")
    parser.add_argument("--import-desktop", action="store_true",
                        help="import the desktop app credentials, then exit")
    parser.add_argument("--quiet", action="store_true",
                        help="run headless: log to usage/wb-proxy.log only")
    args = parser.parse_args()

    if args.lan:
        if args.host == "127.0.0.1":
            args.host = "0.0.0.0"
        if not args.api_key:
            args.api_key = "qwer.1234"

    if args.quiet or os.environ.get("WB_PROXY_QUIET") == "1":
        QUIET_MODE = True

    ctx = context_mod.AppContext(accounts_dir=args.accounts_dir,
                                 usage_dir=args.usage_dir, log=log)
    LOG_FILE = os.path.join(ctx.usage_dir, "wb-proxy.log")
    # 访问日志单独走控制台/文件，不污染运行日志环与落库
    ctx.access_log = access_log

    if _already_running(args.host, args.port):
        log("already running on port %s - not starting a second copy" % args.port)
        return

    if args.import_desktop:
        ctx.boot(register_channels=_register_channels)
        imported = ctx.pool.import_desktop_credential()
        for account in (imported if isinstance(imported, list) else [imported]):
            print("  %s  %s  %s" % (account.uid[:8], account.nickname, account.domain))
        return

    if args.panel_password:
        try:
            settings.set_panel_password(ctx.accounts_dir, args.panel_password)
        except ValueError as exc:
            log("panel      : %s" % exc)
            return
        log("panel      : password set from --panel-password")
    elif settings.panel_password_is_default(ctx.accounts_dir):
        log("panel      : password is still the default 'admin' - change it in the panel")

    if args.system_prompt:
        ctx.system_prompt = args.system_prompt
    # 环与日志库在 ctx 里绑定（AppContext 构造时已挂好），启动参数设的日志文件
    # 只影响静默模式的落盘位置。

    # 提示词配置读取器：核心组装出站请求体时按 settings 现读
    upstream_body.set_prompt_config_reader(
        lambda: settings.prompt_config(ctx.accounts_dir))
    # 本地网络工具的多引擎轮换、冷却与失败分类写进运行日志（tag=webtools）
    webtools.set_logger(log)

    # 启动参数里的 Key 只在面板未接管时生效
    saved_key, key_from_panel = settings.api_key_override(ctx.accounts_dir)
    launcher_key = args.api_key or ""
    if key_from_panel and not launcher_key:
        launcher_key = saved_key or ""
    authz.configure(ctx, launcher_key=launcher_key, key_from_panel=key_from_panel)

    ctx.boot(register_channels=_register_channels)

    # 路由组：核心 API + 面板 + 静态资源
    proxy_api.install(http_mod.ROUTER)
    panel_routes.install(http_mod.ROUTER)
    from panel import static as panel_static
    panel_static.install(http_mod.ROUTER, ctx)

    if not ctx.pool.accounts:
        detected = [item for item in _scan_desktop()
                    if item.get("usable")]
        if detected:
            log("no accounts yet - detected %d desktop credential(s), NOT importing"
                % len(detected))
        else:
            log("no accounts yet - open the dashboard and log in an account")

    http_mod.resize_chat_slots(ctx.pool.count_ready())
    rep = ctx.pool.representative()
    log("accounts   : %d total, %d usable"
        % (len(ctx.pool.accounts), ctx.pool.count_ready()))
    if rep is not None:
        log("account    : %s @ %s" % (rep.uid[:8], rep.domain))
    log("realm      : %s" % ctx.current_realm)
    log("channels   : %s" % ", ".join(
        meta.get("id") for meta in registry.panel_channels(ctx)))
    log("store      : %s" % ctx.accounts_dir)
    if identity.CN_CHAT_BASE_IGNORED:
        log("config     : WB_CN_CHAT_UPSTREAM=%s 被忽略（不是合法的 http(s) 地址），"
            "国内版对话上游仍用 %s"
            % (identity.CN_CHAT_BASE_IGNORED, identity.CN_CHAT_BASE))
    log("listening  : http://%s:%s/v1  (api key: %s)"
        % (args.host, args.port, "on" if launcher_key else "off"))
    log("dashboard  : http://%s:%s/" % (args.host, args.port))

    if args.host == "0.0.0.0":
        for ip in http_mod.local_ip_addresses() or ["<this-pc-ip>"]:
            log("lan       : API http://%s:%s/v1   Dashboard http://%s:%s/"
                % (ip, args.port, ip, args.port))

    if ctx.pool.accounts:
        threading.Thread(target=_warm, args=(ctx,), name="wb-warmup",
                         daemon=True).start()

    server = http_mod.make_server(args.host, args.port, http_mod.BaseHandler, ctx)
    _ctrl_handler = install_console_close_handler()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("bye")
    finally:
        try:
            server.server_close()
        except Exception:
            pass


def _register_channels(ctx):
    """渠道装配：入口层唯一认识具体渠道的地方（新增渠道在此加一行）。"""
    from integrations import workbuddy
    workbuddy.install(ctx)
    from integrations import trae
    trae.install(ctx)
    from integrations import qoder
    qoder.install(ctx)
    from integrations import zcode
    zcode.install(ctx)
    from integrations import codearts
    codearts.install(ctx)
    from integrations import loomy
    loomy.install(ctx)


def _scan_desktop():
    from auth import accounts as accounts_mod
    try:
        return accounts_mod.scan_desktop_credentials()
    except Exception:
        return []


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    main()
