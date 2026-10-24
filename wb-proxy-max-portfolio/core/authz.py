# -*- coding: utf-8 -*-
"""core/authz.py —— 请求鉴权（API Key 与面板会话，自二开迁移）

两条独立凭证：
- API Key：客户端调 /v1/* 用，按 Key 绑定出口与模型白名单；
- 面板会话：浏览器登录后拿到的令牌，同时解锁管理接口（这样浏览器不必把
  API Key 存进 localStorage）。

规则（与二开一致）：
- 面板里一旦配了 Key，那些 Key 就是唯一接受的凭证（启动参数里的 Key 不再
  静默放行）；
- `auth_disabled` 打开时完全不校验 Key（自用直连场景）。
"""
from infra import settings

#: 由入口在启动时注入（启动参数里的 Key 与「是否由面板管理」）
_ctx = {"ctx": None, "launcher_key": "", "key_from_panel": False}


def configure(ctx=None, launcher_key=None, key_from_panel=False):
    if ctx is not None:
        _ctx["ctx"] = ctx
    if launcher_key is not None:
        _ctx["launcher_key"] = launcher_key or ""
    _ctx["key_from_panel"] = bool(key_from_panel)


def configured_keys(ctx):
    """面板管理的 Key 列表（每次现读，面板改动立即生效）。"""
    try:
        return settings.api_keys(ctx.accounts_dir)
    except Exception:
        return []


def auth_required(ctx):
    """是否必须出示 Key。"""
    if settings.auth_disabled(ctx.accounts_dir):
        return False
    if any(entry.get("enabled") for entry in configured_keys(ctx)):
        return True
    return bool(_ctx.get("launcher_key"))


def identify_key(ctx, supplied):
    """返回调用方使用的 Key 条目（带 source），没有匹配返回 None。"""
    extra = () if configured_keys(ctx) else (_ctx.get("launcher_key"),)
    return settings.match_api_key(ctx.accounts_dir, supplied, extra_keys=extra)


def authorize(handler):
    """一次请求是否被放行；命中时把 Key 条目挂到 handler.key_entry 上。"""
    ctx = handler.ctx
    if ctx is None:
        return False
    if handler.panel_ok():
        handler.key_entry = None
        return True
    entry = identify_key(ctx, handler.supplied_key())
    handler.key_entry = entry
    if entry:
        return True
    return not auth_required(ctx)


def key_realm(handler):
    return ((handler.key_entry or {}).get("realm") or "")


def key_model_error(handler, model):
    """该 Key 的模型白名单不允许这个模型时返回人话报错；否则空串。"""
    entry = getattr(handler, "key_entry", None)
    if not entry:
        return ""
    if settings.key_allows_model(entry, model):
        return ""
    name = entry.get("name") or "未命名"
    allowed = "、".join(entry.get("models") or []) or "-"
    asked = str(model or "").strip() or "(未指定模型)"
    return ("API Key「%s」的模型限制不允许 %s。该 Key 目前允许：%s。"
            "请调整这个 Key 的模型限制，或改用允许该模型的 Key。"
            % (name, asked, allowed))


def mask_key(raw):
    """面板展示用的 Key 掩码：留头尾各 4 位、中间 6 个星号；过短则全部掩掉。

    与原面板路由内的实现逐字一致：长度 <= 8（含空串）返回等长全星号。
    """
    raw = str(raw or "")
    return (raw[:4] + "*" * 6 + raw[-4:]) if len(raw) > 8 else "*" * len(raw)


def merge_api_key_entries(current, raw):
    """面板提交的 Key 条目与现存条目合并（原 settings_save 内联规则原样下沉）。

    current: {id: entry} 现配置字典；raw: 非空的提交 list（类型校验由调用方做）。
    规则：未填 key 沿用原值；name/realm/models 未提交时沿用原值；返回清洗后的
    list（缺 key 的条目丢弃，id 缺省为 None）。
    掩码防污染：提交的 key 命中该条目自己的掩码形态（浏览器密码管理器会把
    show-password 输入框当密码框回填 placeholder）时视为「未修改」，沿用原值
    ——否则掩码串会被当成真 Key 存进去，原 Key 静默报废。
    """
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        ident = str(entry.get("id") or "")
        identity = dict(current.get(ident) or {})
        key = str(entry.get("key") or "").strip() or identity.get("key") or ""
        if ident and key == mask_key(identity.get("key")) and identity.get("key"):
            key = identity["key"]
        if not key:
            continue
        cleaned.append({
            "id": ident or None,
            "name": entry.get("name") or identity.get("name") or "未命名",
            "key": key,
            "realm": entry.get("realm") if "realm" in entry else identity.get("realm"),
            "models": entry.get("models") if "models" in entry else identity.get("models"),
            "enabled": entry.get("enabled", identity.get("enabled", True)),
        })
    return cleaned


def request_realm(handler, explicit=None):
    """本次请求的出口：显式参数 > Key 绑定 > X-Realm 头 > ?realm=，否则 None。"""
    if explicit:
        return explicit
    bound = key_realm(handler)
    if bound:
        return bound
    header = handler.headers.get("X-Realm")
    if header:
        return header
    return (handler.query().get("realm") or [None])[0]
