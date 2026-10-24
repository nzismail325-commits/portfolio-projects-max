# -*- coding: utf-8 -*-
"""wb_updates.py — 更新发现（只发现，不安装）。

这个模块回答一个问题：**每个已融合的上游开源仓库**有没有比当前融合基线更新的
稳定版？重构版同时采纳多个开源上游（见《AGENTS.md》上游清单），所以检查按
UPSTREAM_SOURCES 注册表**逐源全部执行**，面板按源展示结论。

它**只做发现**：每个源按「直连 → 本地 Clash 代理 → 镜像源」的通道链拉一次
GitHub 的 releases 元数据（每条通道内 API 主路径、网页端点兜底）、比较版本号、
把结论交给面板。不下载、不解包、不替换文件、不重启进程。

三条硬约束：

1. **默认关闭**。每日检查是 operator 显式打开的偏好；缺键、false 都是关闭，
   关闭时后台一个请求都不发。
2. **失败不致命**。某个源网络超时、HTTP 错误、JSON 坏了只记该源的一行短原因，
   其它源照常检查，网关照常服务；后台检查永远不挡请求路径。
3. **只留安全运维字段**。落盘的只有按源分开的「上次尝试时间 / 上次成功时间 /
   见过的版本号」；URL、请求头、响应体一律不落。

纯标准库，Python 3.9 兼容。
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from infra import settings as wb_settings

# ---------------------------------------------------------------------------
# 上游源注册表：采纳新的开源上游时在这里追加一行（repo + 融合基线）。
# baseline 是本项目已经融合到的那一版上游——「有更新」的判定基准；
# 它不是网关自身的运行版本号（那是 1.0.0-max，两者语义不同）。
# ---------------------------------------------------------------------------
UPSTREAM_SOURCES = [
    {
        "id": "workbuddy2api-hub",
        "label": "workbuddy2api-hub（主上游）",
        "repo": "ardeyouxipianyi/workbuddy2api-hub",
        "baseline": "1.7.33",
    },
    {
        "id": "agenthub",
        "label": "AgentHub（参考上游）",
        "repo": "HUIdada1/AgentHub",
        "baseline": "1.86.0",
    },
]


def _api_url(repo):
    """releases 接口——主路径。走 API 不抓 HTML：页面结构变了不该让检查失效。"""
    return "https://api.github.com/repos/%s/releases" % repo


def _latest_url(repo):
    """网页端点：releases/latest 会 302 到 /releases/tag/<tag>，按网页计流量，
    不受 API 那 60 次/小时/出口 IP 的匿名配额限制，也不需要凭据。"""
    return "https://github.com/%s/releases/latest" % repo


# /releases/tag/<tag> 的提取：URL 与页面内容共用；内容里有引号和锚文本，
# 字符类必须同时排除引号、尖括号与空白，否则会吞进 HTML 残渣。
TAG_RE = re.compile(r'/releases/tag/([^/?#"><\s]+)')
# 可选凭据：认证请求的配额是 5000 次/小时。只从环境变量读，绝不落盘
# （模块头第 3 条）。
TOKEN_ENV = "GITHUB_TOKEN"
USER_AGENT = "wb2api-hub-update-check"
REQUEST_TIMEOUT = 5
# 一份 releases 文档几十 KB；给足余量但设上限，坏响应不能把内存拉满。
MAX_BODY = 2 * 1024 * 1024

# 每日检查的节流窗口。约 24 小时：重启不会让检查变得频繁，也不会因为一次
# 失败就整天不再试。
SCHEDULED_INTERVAL_SECONDS = 24 * 3600
# 启动后先等一会儿再花掉这个请求，让监听端口和账号池先就绪。
FIRST_DELAY_SECONDS = 30
# 后台线程醒来的间隔。真正的节流靠 due() 判断，这里只决定「多久看一眼」。
POLL_SECONDS = 300

# 只认 vX.Y.Z 这种能排序的稳定版本号。带后缀的（-rc1）、日期 tag、移动分支名
# 一律跳过：猜一个顺序比不报更糟。
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def parse_version(text):
    """vX.Y.Z / X.Y.Z -> (major, minor, patch)；其它一律 None。"""
    match = VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer(candidate, current):
    """candidate 是否严格新于 current；任一边不可解析就是 False。"""
    left, right = parse_version(candidate), parse_version(current)
    return bool(left and right and left > right)


def safe_url(value):
    """发布页链接，或 ""。

    这个值来自远端文档，会被面板原样显示：只放行 GitHub 的 https 发布页这一种
    形状，别的一律丢掉。
    """
    text = str(value or "").strip()
    if not text.startswith("https://github.com/"):
        return ""
    return text[:300]


def pick_latest(releases, current_version):
    """从一份 releases 文档里挑出最新的稳定版，没有就返回 None。

    草稿与预发布跳过；tag 不是纯 vX.Y.Z 的跳过；取版本号最大的那个而不是列表
    里第一个——重新发布的旧 tag 不能靠排序取胜。
    """
    best = None
    for entry in releases if isinstance(releases, list) else []:
        if not isinstance(entry, dict):
            continue
        if entry.get("draft") or entry.get("prerelease"):
            continue
        version = parse_version(entry.get("tag_name"))
        if version is None:
            continue
        if best is None or version > best[0]:
            best = (version, entry)
    if best is None:
        return None
    version, entry = best
    text = "%d.%d.%d" % version
    return {
        "version": text,
        "tag": str(entry.get("tag_name") or "").strip()[:64],
        "url": safe_url(entry.get("html_url")),
        "published_at": str(entry.get("published_at") or "").strip()[:32],
        "newer": is_newer(text, current_version),
    }


def describe_failure(exc):
    """一行能安全外发的失败原因。

    urllib 的异常消息里可能带着完整 URL 和响应体，两者都不该进 settings.json
    或日志，所以这里只取异常类型和 HTTP 状态码。
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return "HTTP %d" % code
    if isinstance(exc, json.JSONDecodeError):
        return "invalid JSON"
    if isinstance(exc, ValueError):
        return "unexpected release document"
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return "network error: %s" % type(exc).__name__
    return type(exc).__name__


def fetch_releases(source, timeout=REQUEST_TIMEOUT):
    """一个上游源的 releases 文档原始 JSON 文本；全链路失败才抛异常。

    访问链顺次尝试（国内直连 GitHub 时好时坏，任何一条通道拿到结论就用它）：
      1. 直连：API 主路径 → releases/latest 网页端点兜底；
      2. 本地代理：普通 Clash 的默认混合端口（7890），同样 API → 网页；
      3. 镜像源：前缀式 GitHub 镜像，只代理网页端点（api.github.com 没有可靠
         的公开镜像）；镜像可能原样跟随重定向，也可能直接回内容页，所以 tag
         既从最终 URL 里找、也从返回的页面内容里找。
    成功通道记入模块级 _LAST_CHANNEL（面板 status 的 via 字段），后续源优先
    复用上一次成功的通道；全部通道失败时抛直连 API 的原因（主路径）。
    """
    last_error = None
    channels = _channels()
    for label, proxy in channels:
        for kind in ("api", "web"):
            try:
                text = _fetch_via(source, kind, proxy, timeout)
                _note_channel(source["repo"], label)
                _prefer_channel(label, proxy)
                return text
            except Exception as exc:
                last_error = last_error or exc
    for mirror in _mirrors():
        label = "镜像 " + mirror.rstrip("/")
        try:
            text = _fetch_web(source, timeout, mirror=mirror)
            _note_channel(source["repo"], label)
            return text
        except Exception as exc:
            last_error = last_error or exc
    raise last_error


# ---------------------------------------------------------------------------
# 访问链实现
# ---------------------------------------------------------------------------
#: 本地代理：普通 Clash 的默认混合端口；WB_UPDATE_PROXY 可覆盖，设为 "off" 跳过。
CLASH_PROXY = "http://127.0.0.1:7890"
#: 前缀式镜像源；WB_UPDATE_MIRRORS（逗号分隔）可覆盖。
DEFAULT_MIRRORS = ("https://ghfast.top/", "https://gh-proxy.com/", "https://ghproxy.net/")
#: 进程内记住的上一次成功通道（repo -> 展示名），后续源优先复用。
_LAST_CHANNEL = {}
_PREFERRED = {"label": "", "proxy": ""}


def _mirrors():
    raw = os.environ.get("WB_UPDATE_MIRRORS")
    if raw is None:
        return DEFAULT_MIRRORS
    items = [item.strip().rstrip("/") + "/" for item in raw.split(",") if item.strip()]
    return tuple(items) or DEFAULT_MIRRORS


def _proxy_env():
    value = os.environ.get("WB_UPDATE_PROXY")
    if value is None:
        return CLASH_PROXY
    value = value.strip()
    return "" if value.lower() in ("off", "none", "disabled") else value


def _channels():
    """有序通道清单 [(展示名, proxy)]；上一次成功的通道排最前。"""
    out = [("直连", "")]
    proxy = _proxy_env()
    if proxy:
        out.append(("本地代理 " + proxy, proxy))
    if _PREFERRED["label"]:
        out.sort(key=lambda item: item[0] != _PREFERRED["label"])
    return out


def _prefer_channel(label, proxy):
    _PREFERRED["label"], _PREFERRED["proxy"] = label, proxy


def _note_channel(repo, label):
    _LAST_CHANNEL[repo] = label[:64]


def _open(request, timeout, proxy=""):
    """带可选代理的 urlopen；不依赖项目内连接池（GitHub 流量不入池统计）。"""
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler).open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _fetch_via(source, kind, proxy, timeout):
    """一条通道上的一次取数：kind="api" 走 releases 接口，kind="web" 走网页端点。"""
    if kind == "api":
        return _fetch_api(_api_url(source["repo"]), timeout, proxy=proxy)
    return _fetch_web(source, timeout, proxy=proxy)


def _fetch_api(url, timeout, proxy=""):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    }
    token = str(os.environ.get(TOKEN_ENV) or "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with _open(request, timeout, proxy) as response:
        return response.read(MAX_BODY).decode("utf-8", "replace")


def _fetch_web(source, timeout, proxy="", mirror=""):
    """releases/latest 上的最新稳定版，返回一条 releases 条目（JSON 文本）。

    tag 既从最终 URL 里取（直连/代理会 302 到 /releases/tag/<tag>），也从页面
    内容里找（镜像可能服务端跟随重定向后原样回内容页，最终 URL 停在镜像上）。
    发布日期这一跳给不出来，留空；html_url 一律构造成 GitHub 官方发布页，
    面板展示与 safe_url 白名单不受镜像影响。
    """
    target = _latest_url(source["repo"])
    if mirror:
        target = mirror + target
    request = urllib.request.Request(target, headers={"User-Agent": USER_AGENT})
    with _open(request, timeout, proxy) as response:
        final = response.geturl()
        body = response.read(256 * 1024).decode("utf-8", "replace")
    match = TAG_RE.search(final or "") or TAG_RE.search(body)
    if not match:
        raise ValueError("no release tag in the redirect target")
    tag = match.group(1)
    return json.dumps([{
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": "https://github.com/%s/releases/tag/%s" % (source["repo"], tag),
        "published_at": "",
    }])


def _stamp(value):
    if not value:
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


class UpdateChecker(threading.Thread):
    """后台的每日更新检查（逐上游源全部执行）+ 面板要的状态。

    daemon 线程：进程退出不需要等它，`stop()` 只是让循环尽快收工。
    """

    def __init__(self, current_version, settings_dir, fetcher=None, log=None,
                 first_delay=FIRST_DELAY_SECONDS, poll_seconds=POLL_SECONDS,
                 sources=None):
        super().__init__(daemon=True, name="update-check")
        self.current_version = str(current_version or "").strip()
        self.settings_dir = settings_dir
        #: 检测的上游源清单（缺省用模块注册表；测试可注入精简清单）
        self._sources = [dict(s) for s in (sources or UPSTREAM_SOURCES)]
        # 注入点：测试给一个假的 fetcher，就不必碰网络。
        self._fetch = fetcher or fetch_releases
        self._log = log
        self._first_delay = max(0.0, float(first_delay))
        self._poll_seconds = max(1.0, float(poll_seconds))
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._checking = False
        self._last_attempt = 0.0
        self._last_success = 0.0
        # 每个源各自的结论与记账：{sid: {latest, last_error, last_attempt, last_success}}
        self._state = {s["id"]: {"latest": None, "last_error": "",
                                 "last_attempt": 0.0, "last_success": 0.0}
                       for s in self._sources}
        self._load_state()

    # ---- 状态 -----------------------------------------------------------
    def _load_state(self):
        """把上次的按源记账读回来，重启后面板立刻有东西可看。"""
        try:
            stored = wb_settings.update_check_state(self.settings_dir)
        except Exception:
            return
        for sid, entry in (stored.get("sources") or {}).items():
            state = self._state.get(sid)
            if state is None:
                continue
            state["last_attempt"] = entry.get("last_attempt") or 0.0
            state["last_success"] = entry.get("last_success") or 0.0
            version = entry.get("latest_version") or ""
            if version:
                baseline = next((s["baseline"] for s in self._sources
                                 if s["id"] == sid), "")
                state["latest"] = {
                    "version": version, "tag": "", "url": "", "published_at": "",
                    "newer": is_newer(version, baseline),
                }
            if state["last_attempt"] and state["last_attempt"] > self._last_attempt:
                self._last_attempt = state["last_attempt"]
            if state["last_success"] and state["last_success"] > self._last_success:
                self._last_success = state["last_success"]

    def _remember(self, source_id, success, version=""):
        try:
            wb_settings.record_update_check(
                self.settings_dir, source_id, at=time.time(),
                success=success, latest_version=version)
        except Exception:
            # 记账失败不该影响一次已经完成的检查：内存里的结论照样能用。
            pass

    def enabled(self):
        """每日检查的偏好；缺键或 false 都是关闭。"""
        try:
            return wb_settings.update_check_enabled(self.settings_dir)
        except Exception:
            return False

    def due(self, now=None):
        """约 24 小时的节流窗口是否已经放行（整轮检查共用一个窗口）。"""
        now = time.time() if now is None else float(now)
        if not self._last_attempt:
            return True
        return (now - self._last_attempt) >= SCHEDULED_INTERVAL_SECONDS

    def status(self):
        sources = []
        any_newer = False
        any_pending = False
        for source in self._sources:
            state = self._state.get(source["id"]) or {}
            picked = state.get("latest") or {}
            latest = picked.get("version") or ""
            newer = is_newer(latest, source["baseline"])
            any_newer = any_newer or newer
            if not latest and not state.get("last_error"):
                any_pending = True
            sources.append({
                "id": source["id"],
                "label": source["label"],
                "repo": source["repo"],
                "baseline": source["baseline"],
                "latest_version": latest or None,
                "update_available": newer,
                "url": picked.get("url") or "",
                "published_at": picked.get("published_at") or "",
                "via": _LAST_CHANNEL.get(source["repo"], ""),
                "last_error": state.get("last_error") or "",
                "last_attempt": _stamp(state.get("last_attempt") or 0.0),
                "last_success": _stamp(state.get("last_success") or 0.0),
            })
        return {
            "current_version": self.current_version,
            "enabled": self.enabled(),
            "checking": self._checking,
            "last_attempt": _stamp(self._last_attempt),
            "last_success": _stamp(self._last_success),
            "update_available": any_newer,
            "pending": any_pending,
            "sources": sources,
        }

    def log(self, msg):
        if not self._log:
            return
        try:
            self._log(msg)
        except Exception:
            pass

    # ---- 检查 -----------------------------------------------------------
    def check(self, manual=False):
        """跑一轮发现（注册表里所有源各查一次），返回状态字典。

        `manual=True` 绕过开关和 24 小时窗口：操作员点了「立即检查」就必须真的
        去问一次。`manual=False` 是后台路径，关闭或没到点就直接返回，一个请求
        都不发。

        同步执行，耗时由 fetcher 的超时封顶（每源至多两次请求）；它不持有任何
        请求路径要等的锁。
        """
        status = self.status()
        if not manual:
            if not self.enabled():
                status["skipped"] = "disabled"
                return status
            if not self.due():
                status["skipped"] = "not due yet"
                return status
        with self._lock:
            if self._checking:
                status["skipped"] = "already running"
                return status
            self._checking = True
        try:
            self._run_check()
        finally:
            with self._lock:
                self._checking = False
        return self.status()

    def _run_check(self):
        self._last_attempt = time.time()
        for source in self._sources:
            sid = source["id"]
            state = self._state.setdefault(
                sid, {"latest": None, "last_error": "",
                      "last_attempt": 0.0, "last_success": 0.0})
            state["last_attempt"] = self._last_attempt
            state["last_error"] = ""
            try:
                document = json.loads(self._fetch(source, REQUEST_TIMEOUT))
                if not isinstance(document, list):
                    raise ValueError("releases document is not a list")
                picked = pick_latest(document, source["baseline"])
            except Exception as exc:
                # 契约上单源失败不致命：保留该源上一次的结论，只报一行短原因；
                # 其它源照常检查。
                state["last_error"] = describe_failure(exc)
                self._remember(sid, success=False)
                self.log("更新检查失败[%s]：%s" % (sid, state["last_error"]))
                continue
            state["latest"] = picked
            state["last_success"] = self._last_attempt
            version = (picked or {}).get("version") or ""
            self._remember(sid, success=True, version=version)
            if picked and picked.get("newer"):
                self.log("发现新版本[%s] %s（融合基线 %s）"
                         % (sid, picked["version"], source["baseline"]))
            elif picked:
                self.log("已是最新[%s]（融合基线 %s）" % (sid, source["baseline"]))
        if self._state:
            self._last_success = max(
                (s.get("last_success") or 0.0 for s in self._state.values()),
                default=0.0)

    # ---- 后台线程 -------------------------------------------------------
    def wake(self):
        """叫醒停着的循环——偏好刚从关拨到开时用。"""
        self._wake.set()

    def stop(self):
        """让循环尽快收工；daemon 线程本来也不会挡住进程退出。"""
        self._stop_event.set()
        self._wake.set()

    def _park(self, seconds):
        self._wake.wait(seconds)
        self._wake.clear()

    def run(self):
        # 先让监听端口和账号池就绪，再花掉第一个请求。
        if self._stop_event.wait(self._first_delay):
            return
        while not self._stop_event.is_set():
            try:
                self.check(manual=False)
            except Exception as exc:
                self.log("更新检查异常：%s" % describe_failure(exc))
            self._park(self._poll_seconds)
