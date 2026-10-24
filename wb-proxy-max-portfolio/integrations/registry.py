# -*- coding: utf-8 -*-
"""integrations/registry.py —— 渠道注册表与适配器接口（P0 定型）

这是「接入新反代 = 一个适配器模块 + 面板板块 + 注册表一行」的那一行所在。
核心（core/auth/infra/tasks/intel）**禁止** import 任何具体渠道模块；渠道
模块只能向下依赖核心设施，依赖方向永远单向。

适配器接口（ChannelAdapter 的子类，只需实现自己支持的部分）：

    id                 渠道唯一标识（同时是 realm 名，如 "workbuddy"）
    label              面板显示名
    capabilities       能力集合（见 CAP_*），页面/按钮按它渲染
    register(ctx)      可选：注册 realm 配置、账号池、面板板块、调度任务

    # 账号治理
    load_accounts(dir)               -> 账号对象列表（核心只按接口使用）
    account_views(realm)             -> 面板视图字典列表
    # 代理链路
    realm_config(realm)              -> auth.accounts 用的端点/身分配置
    live_models(realm)               -> [(id, meta)] 实时目录
    open_stream(payload, ...)        -> (响应对象, 归属标签)
    # 任务
    scheduler_tasks()                -> [(task_id, label, handler, defaults)]

核心只通过注册表读写这些能力，因此新增渠道不需要改动 core/auth/infra/tasks
里的任何文件；未注册或未启用的渠道，其入口一律不渲染（§2.2 归属控制）。
"""
import threading
import urllib.error

#: 能力常量：页面上出现哪些入口，由渠道声明了哪些能力决定
CAP_CHAT = "chat"                 # OpenAI 兼容对话链路
CAP_RESPONSES = "responses"       # Responses 协议
CAP_MESSAGES = "messages"         # Anthropic Messages 协议
CAP_MODELS = "models"             # 模型目录
CAP_ACCOUNTS = "accounts"         # 账号池治理
CAP_CHECKIN = "checkin"           # 每日签到
CAP_DAILY_CHAT = "daily_chat"     # 每日活跃打卡
CAP_TASKS = "tasks"               # 成长任务 / 福利任务
CAP_SCHEDULER = "scheduler"       # 调度任务注入
CAP_PROXY_SLOT = "proxy_slot"     # 账号代理槽
CAP_PASTE_TOKEN = "paste_token"   # 手动粘贴凭据入库（refreshToken 换发型渠道）
CAP_DESKTOP_IMPORT = "desktop_import"  # 可从本机客户端登录态扫描并导入账号

ALL_CAPABILITIES = (CAP_CHAT, CAP_RESPONSES, CAP_MESSAGES, CAP_MODELS,
                    CAP_ACCOUNTS, CAP_CHECKIN, CAP_DAILY_CHAT, CAP_TASKS,
                    CAP_SCHEDULER, CAP_PROXY_SLOT, CAP_PASTE_TOKEN,
                    CAP_DESKTOP_IMPORT)


class ChannelAdapter(object):
    """渠道适配器基类：所有方法默认返回「不支持」，子类按需覆盖。"""

    id = ""
    label = ""
    #: 该渠道覆盖的 realm 列表（通常就是 [id]，多出口渠道可给多个）
    realms = ()
    #: 该渠道认领的显式出站前缀（如 "trae" → 客户端模型名 "trae/xxx" 直达本
    #: 渠道且剥掉前缀）。不声明就没有前缀路由；裸模型名绝不因此被劫持。
    route_prefixes = ()
    capabilities = frozenset()

    def register(self, ctx):
        """渠道自注册钩子（ctx 是 AppContext）。默认无操作。"""

    # ---- 账号治理 ----
    def account_pool(self, ctx):
        return None

    def account_views(self, realm=None):
        return []

    # ---- 渠道自有登录流（refreshToken 换发型等；返回 None 落回账号池通用登录）
    def start_login(self, ctx, realm, platform="CLI"):
        """发起登录；渠道没有自有流程时返回 None（调用方回落池子通用登录）。"""
        return None

    def poll_login(self, ctx, state):
        """轮询登录结果；不认识该 state 时返回 None。"""
        return None

    def submit_login(self, ctx, state, raw_callback):
        """手动粘贴回调地址；渠道不支持时返回 None。"""
        return None

    # start_login 返回 {"form": {...}} 时，面板按声明渲染通用表单；
    # login_action 负责表单里的发码/提交等动作（见下）。
    def login_action(self, ctx, state, action, payload):
        """表单类登录的附加动作（如短信发码）；渠道不认识时返回 None。

        start_login 可返回 {"form": {...}} 让面板渲染通用表单，动作名与
        字段由适配器声明，面板不写死任何渠道的登录协议。
        """
        return None

    def cancel_login(self, ctx, state):
        """取消登录会话；渠道不支持时返回 None。"""
        return None

    # ---- 登录身份（面板账号列展示/复制用）----
    def login_account_pending(self, account):
        """账号缺少可持久化登录身份、且渠道能补齐时返回 True。"""
        return False

    def sync_login_account(self, ctx, account):
        """尽力补一次登录身份并落账号 meta；拿不到返回空串。"""
        return ""

    # ---- 本机客户端凭据（声明 CAP_DESKTOP_IMPORT 的渠道实现）----
    def scan_desktop(self, ctx):
        """只读扫描本机客户端登录态，返回与 accounts_mod 扫描结果同形的候选列表。"""
        return []

    def import_desktop(self, ctx, candidate):
        """把一条本机候选导入账号池，返回 Account；失败抛异常。"""
        return None

    # ---- 代理链路 ----
    def realm_config(self, realm):
        return {}

    def live_models(self, realm, force=False):
        """该出口的模型目录 [(id, meta)]：live → cache → static 的完整兜底链。

        force=True 时只认上游 API（面板手动刷新语义），拿不到返回空列表。
        """
        return []

    def open_stream(self, ctx, payload, session_key=None, realm=None):
        raise NotImplementedError

    # ---- 任务 ----
    def scheduler_tasks(self, ctx):
        return []

    # ---- 面板 ----
    def panel_meta(self, ctx):
        """面板板块元信息：{"id", "label", "capabilities", "frontend", "enabled"}。"""
        return {
            "id": self.id,
            "label": self.label,
            "realms": list(self.realms or ([self.id] if self.id else [])),
            "capabilities": sorted(self.capabilities),
            "frontend": self.id,
            "enabled": True,
        }


def prime_stream(stream):
    """预读渠道流，直到首个可用增量或确认失败——「没出内容前还能换号」的判据。

    渠道流只需提供四个内部约定：_next_chunk()（收尾返回 None，失败抛
    HTTPError）、_pending、_produced、_error。返回 ready/error；账号罚则
    仍由各渠道流自己的错误处理完成，调用方只负责挑下一把账号。
    """
    buffered = []
    while True:
        if stream._error is not None:
            stream._pending[:0] = buffered
            return "error"
        if stream._produced:
            stream._pending[:0] = buffered
            return "ready"
        try:
            chunk = stream._next_chunk()
        except urllib.error.HTTPError:
            stream._pending[:0] = buffered
            return "error"
        if chunk is None:
            stream._pending[:0] = buffered
            return "ready"
        buffered.append(chunk)


class Registry(object):
    def __init__(self):
        self._lock = threading.RLock()
        self._adapters = {}
        self._order = []

    def register(self, adapter, ctx=None):
        """注册一个渠道；同 id 重复注册时替换（便于热重载）。

        传入 ctx 时顺带跑一次适配器的 `register(ctx)` 自注册钩子（realm 配置、
        面板板块、调度任务的能力声明都在那里落地）。
        """
        cid = str(getattr(adapter, "id", "") or "").strip()
        if not cid:
            raise ValueError("adapter has no id")
        with self._lock:
            if cid not in self._adapters:
                self._order.append(cid)
            self._adapters[cid] = adapter
        if ctx is not None:
            adapter.register(ctx)
        return adapter

    def unregister(self, channel_id):
        with self._lock:
            self._adapters.pop(channel_id, None)
            if channel_id in self._order:
                self._order.remove(channel_id)

    def get(self, channel_id):
        with self._lock:
            return self._adapters.get(str(channel_id or ""))

    def all(self):
        with self._lock:
            return [self._adapters[cid] for cid in self._order]

    def ids(self):
        with self._lock:
            return list(self._order)

    def all_realms(self):
        """所有已注册渠道覆盖的 realm（含空串=未绑定）。"""
        out = [""]
        for adapter in self.all():
            for realm in (adapter.realms or ((adapter.id,) if adapter.id else ())):
                if realm not in out:
                    out.append(realm)
        return out

    def find_realm_owner(self, realm):
        """realm 属于哪个渠道（未找到返回 None）。"""
        realm = str(realm or "")
        for adapter in self.all():
            realms = adapter.realms or ((adapter.id,) if adapter.id else ())
            if realm in realms:
                return adapter
        return None

    def detect_prefix_realm(self, model):
        """显式出站前缀 → (realm, 剥掉前缀后的模型名)。

        形如 "trae/glm-5.3" 的模型名按注册表声明的前缀直达对应渠道；
        未命中返回 ("", model)。前缀必须整段命中（"trae/xxx" 不认 "tra"）。
        """
        raw = str(model or "").strip()
        if "/" not in raw:
            return "", raw
        head, _, rest = raw.partition("/")
        head = head.strip().lower()
        rest = rest.strip()
        if not head or not rest:
            return "", raw
        for adapter in self.all():
            for prefix in (adapter.route_prefixes or ()):
                if str(prefix or "").strip().lower() == head:
                    realms = adapter.realms or ((adapter.id,) if adapter.id else ())
                    return (realms[0] if realms else adapter.id), rest
        return "", raw

    def capable(self, capability, realm=None):
        """声明了该能力（且可限定渠道）的适配器列表。"""
        out = []
        for adapter in self.all():
            if capability not in (adapter.capabilities or ()):
                continue
            if realm:
                realms = adapter.realms or ((adapter.id,) if adapter.id else ())
                if realm not in realms:
                    continue
            out.append(adapter)
        return out

    def panel_channels(self, ctx=None, enabled_only=True):
        """面板下发的渠道列表：页面/按钮只按这份清单渲染，未注册或停用不出现。"""
        out = []
        for adapter in self.all():
            try:
                meta = adapter.panel_meta(ctx) or {}
            except Exception:
                continue
            meta.setdefault("id", adapter.id)
            meta.setdefault("label", adapter.label)
            meta.setdefault("realms", list(adapter.realms or [adapter.id]))
            meta.setdefault("capabilities", sorted(adapter.capabilities or ()))
            meta.setdefault("frontend", adapter.id)
            meta.setdefault("enabled", True)
            if enabled_only and not meta.get("enabled"):
                continue
            out.append(meta)
        return out

    def panel_task_scopes(self, ctx):
        """调度任务 → 渠道归属：[{"id", "label", "channel", "realm"}...]。

        任务本身由渠道声明，归属也由注册表裁决，前端不猜某个任务属于谁。
        """
        scopes = []
        seen = set()
        for adapter in self.all():
            try:
                specs = adapter.scheduler_tasks(ctx) or []
            except Exception:
                continue
            realms = list(adapter.realms or ([adapter.id] if adapter.id else []))
            for spec in specs:
                try:
                    task_id, label = spec[0], spec[1]
                except Exception:
                    continue
                if not task_id or task_id in seen:
                    continue
                seen.add(task_id)
                # 任务可用 opts["realm"] 收窄出口范围（如 workbuddy 的国内/国际专属任务）
                opts = spec[3] if len(spec) > 3 and isinstance(spec[3], dict) else {}
                hint = opts.get("realm")
                scope = [hint] if hint in realms else realms
                scopes.append({"id": task_id, "label": label,
                               "channel": adapter.id,
                               "realms": scope})
        return scopes

    def scheduler_tasks(self, ctx):
        """汇总所有渠道声明的调度任务：[(task_id, label, handler, defaults)]。"""
        out = []
        for adapter in self.all():
            try:
                out.extend(adapter.scheduler_tasks(ctx) or [])
            except Exception:
                continue
        return out


#: 进程级单例。入口在启动时把渠道适配器注册进来。
REGISTRY = Registry()


def register(adapter, ctx=None):
    return REGISTRY.register(adapter, ctx)


def unregister(channel_id):
    return REGISTRY.unregister(channel_id)


def all_realms():
    return REGISTRY.all_realms()


def get(channel_id):
    return REGISTRY.get(channel_id)


def all_channels():
    return REGISTRY.all()


def panel_channels(ctx=None, enabled_only=True):
    return REGISTRY.panel_channels(ctx, enabled_only=enabled_only)


def scheduler_tasks(ctx=None):
    return REGISTRY.scheduler_tasks(ctx)
