# -*- coding: utf-8 -*-
"""intel/catalog.py —— 模型目录与规格标注（静态表自二开，标注链自上游）

三层结构，回答「这个模型叫什么、多大上下文、能不能看图/工具、输出上限多少」：

1. 静态目录（intel/catalog_static.py，二开 53 id 超集，原样搬入）；
2. 实时目录（渠道适配器注入的 live provider 回调：桌面缓存 / 远端产品配置）；
3. 标注链：models.dev 四级查找 + 输出钳制探测，只做注记不改规格值。

渠道无关：本模块不认识任何具体上游端点。实时目录经 `set_live_provider()`
由渠道适配器注入，fn(realm) 返回 [(id, meta), ...]。

明确不引入（拍板砍掉）：定价/人民币估算。目录里的 credits 字符串仅原样
透传给客户端展示，不做任何价格换算。
"""
import threading
import time

from intel import catalog_static
from intel import modelsdev
from intel import probes

# ---------------------------------------------------------------------------
# 实时目录注入点与缓存
# ---------------------------------------------------------------------------
_live_provider = None
_force_provider = None
_live_lock = threading.Lock()
_models_cache = {}
_models_source = {}
_dirs = {"account": None, "probe": None}


def set_dirs(accounts_dir=None, probes_dir=None):
    """数据目录注入（models.dev 缓存与探测结果的落盘位置）。"""
    if accounts_dir:
        _dirs["account"] = accounts_dir
    _dirs["probe"] = probes_dir or _dirs["probe"] or accounts_dir


def set_live_provider(fn):
    """渠道适配器注入实时目录回调：fn(realm) -> [(id, meta_dict), ...]。"""
    global _live_provider
    with _live_lock:
        _live_provider = fn


def set_force_provider(fn):
    """注入「强制刷新」回调：fn(realm) -> [(id, meta), ...] 或 None（拿不到）。

    与 _live_provider 的差别：强制刷新只认上游 API，不读桌面缓存、不走窄端点
    ——面板手动刷新要的是「这次真的从上游取到了」的如实反馈（上游 v1.7.12
    refresh_catalog 的同款约定）。
    """
    global _force_provider
    with _live_lock:
        _force_provider = fn


# ---------------------------------------------------------------------------
# 模型分类与展示顺序（自二开迁移）
# ---------------------------------------------------------------------------
VIRTUAL_ALIAS_MODELS = {
    "default-model", "fast-model", "balanced-model", "primary-model",
    "deep-model", "auto",
}
NON_CHAT_MODELS = {"lite"} | VIRTUAL_ALIAS_MODELS
NON_CHAT_PREFIXES = ("codewise-", "completion-")
NON_CHAT_SUFFIXES = ("-image-alpha", "-image-alpha-edit", "-taco-completion")

CN_UI_ORDER = [
    "hy4-preview-f", "hy3", "deepseek-v4.1-flash", "glm-5.3", "glm-5.3-flash",
    "glm-5.2", "glm-5.1", "glm-5v-turbo", "minimax-m3", "kimi-k3-1",
    "kimi-k2.8-preview", "kimi-k2.7", "kimi-k2.6", "deepseek-v4-pro",
]
INTL_UI_ORDER = [
    "hy4-preview-f", "hy3", "deepseek-v4.1-flash", "gpt-6-astra", "gpt-5.6-sol",
    "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4", "grok-4.7",
    "gemini-3.5-flash", "glm-5.3-flash", "glm-5.3", "glm-5.2", "kimi-k3",
    "kimi-k2.6", "kimi-k2.8-preview",
]

#: 只在单一出口提供的模型（跨出口调用时给人话报错）
INTL_EXCLUSIVE_PREFIXES = ("gpt-", "gemini-")
#: `minimax-` 不是 CN 独占前缀：国际出口也提供 minimax-m3.1-flash，宽通配会把
#: 它能用的请求在本地 400 掉。只保留确定的独占项（deepseek-v4-pro* 与显式
#: minimax-m3），同族其它模型按出口的实际目录判断（对齐上游 v1.7.31 #618）。
CN_EXCLUSIVE_PREFIXES = ("deepseek-v4-pro",)
INTL_EXCLUSIVE = {
    "gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "gemini-3.5-flash", "grok-4.7",
}
CN_EXCLUSIVE = {
    "deepseek-v4-pro", "glm-5.1", "glm-5v-turbo", "kimi-k3-1", "kimi-k2.7",
    "minimax-m3", "hy3-x", "hy4-preview-dev", "hy4-preview-x",
}


def is_chat_model(mid):
    if not mid:
        return False
    if mid in NON_CHAT_MODELS:
        return False
    if mid.startswith(NON_CHAT_PREFIXES):
        return False
    if mid.endswith(NON_CHAT_SUFFIXES):
        return False
    return True


def detect_model_realm(model_id, default="intl"):
    """按模型名判定出口；判不出的返回 default。"""
    if not model_id:
        return default
    m = str(model_id).lower()
    if m in INTL_EXCLUSIVE or m.startswith(INTL_EXCLUSIVE_PREFIXES):
        return "intl"
    if m in CN_EXCLUSIVE or m.startswith(CN_EXCLUSIVE_PREFIXES):
        return "cn"
    return default


def exclusive_realm(model_id):
    """只在该出口提供的模型返回该出口，否则空串。"""
    if not model_id:
        return ""
    m = str(model_id).lower()
    if m in INTL_EXCLUSIVE or m.startswith(INTL_EXCLUSIVE_PREFIXES):
        return "intl"
    if m in CN_EXCLUSIVE or m.startswith(CN_EXCLUSIVE_PREFIXES):
        return "cn"
    return ""


def static_models(realm=None):
    if realm in ("intl", "cn"):
        if realm == "cn":
            return list(catalog_static.STATIC_CN_MODELS or catalog_static.STATIC_MODELS)
        return list(catalog_static.STATIC_INTL_MODELS or catalog_static.STATIC_MODELS)
    return []


def _realm_adapter(realm):
    """认领某出口的渠道适配器（注册表裁决；intel 层不认识具体渠道）。"""
    try:
        from integrations import registry as registry_mod
    except Exception:
        return None
    return registry_mod.REGISTRY.find_realm_owner(realm)


# ---------------------------------------------------------------------------
# 目录构建
# ---------------------------------------------------------------------------
def merge_catalog(primary, realm=None, extras=False):
    """静态目录 + 实时目录合并，按展示顺序排列。

    intl/cn 走注入静态表与 UI 顺序；其他出口的目录完全由渠道适配器的
    live provider 提供（未注册适配器的出口只有它给得出来的条目）。
    """
    r = "cn" if realm == "cn" else ("intl" if realm == "intl" else str(realm or ""))
    merged = {}
    if r in ("intl", "cn"):
        for item in static_models(r):
            mid = item.get("id")
            if mid and is_chat_model(mid):
                merged[mid] = dict(item)
    for mid, meta in primary or []:
        if not is_chat_model(mid):
            continue
        if meta:
            base = merged.get(mid) or {}
            base.update(meta)
            merged[mid] = base
        elif mid not in merged:
            merged[mid] = {}
    order = CN_UI_ORDER if r == "cn" else INTL_UI_ORDER
    out = []
    for mid in order:
        if mid in merged:
            out.append((mid, merged[mid]))
    # 其余出口没有固定展示顺序：保持上游给的原序（extras 恒视为开）
    if r not in ("intl", "cn") or extras:
        seen = {mid for mid, _ in out}
        for mid, _meta in primary or []:
            if mid in merged and mid not in seen:
                seen.add(mid)
                out.append((mid, merged[mid]))
    return out


#: 正在后台重建目录的出口（stale-while-revalidate 防重入）
_bg_refresh = set()


def _build_entries(r, log):
    """调实时目录回调、合并静态表并写缓存，返回条目（调用方持锁或后台线程）。"""
    primary, source = None, "static"
    provider = _live_provider
    if provider is not None:
        try:
            live = provider(r)
            if live:
                primary = [(mid, meta or {}) for mid, meta in live]
                source = "live"
        except Exception as exc:
            if log:
                log("model discovery for realm '%s' failed: %s" % (r, exc))
    entries = merge_catalog(primary or [], realm=r, extras=bool(primary))
    _models_cache[r] = {"at": time.time(), "data": entries}
    _models_source[r] = {"source": source, "at": time.time(), "count": len(entries)}
    return entries


def _kick_refresh(r, log):
    """后台重建目录（stale-while-revalidate）：旧数据先回，重建不挡请求。"""
    if r in _bg_refresh:
        return
    _bg_refresh.add(r)

    def _worker():
        try:
            with _catalog_lock:
                _build_entries(r, log)
        except Exception as exc:
            if log:
                log("model catalog background refresh for '%s' failed: %s" % (r, exc))
        finally:
            _bg_refresh.discard(r)

    threading.Thread(target=_worker, daemon=True, name="catalog-refresh").start()


def fetch_models(realm=None, ttl=300, log=None):
    """当前出口的模型清单 [(id, meta)]，带 TTL 缓存。

    intl/cn 经注入回调；其他出口直接问认领渠道的 live_models（无缓存——
    渠道自己有 TTL，经注册表现问，避免 intel 层替渠道管缓存）。

    intl/cn 缓存过期时不再锁着锁等上游：有过期数据就先回旧数据、后台重建
    （stale-while-revalidate）——上游变慢时 /v1/models 与对话选号不会被
    single-flight 串队；完全没有缓存才同步构建（保持原行为）。
    """
    r = "cn" if realm == "cn" else ("intl" if realm == "intl" else str(realm or ""))
    if r not in ("intl", "cn"):
        adapter = _realm_adapter(r)
        if adapter is None:
            return []
        try:
            live = [(mid, meta or {}) for mid, meta in (adapter.live_models(r) or [])]
        except Exception as exc:
            if log:
                log("model discovery for realm '%s' failed: %s" % (r, exc))
            return []
        if live:
            # 渠道自有出口的目录全由适配器提供：来源与时间是面板展示口径，
            # 与 intl/cn 的 _models_source 保持同一形状。
            _models_source[r] = {"source": "live", "at": time.time(),
                                 "count": len(live)}
        return live
    cached = _models_cache.get(r)
    if cached and time.time() - cached["at"] < ttl:
        return cached["data"]
    stale = cached["data"] if cached else None
    # 同一出口多个调用方同时 miss 只走一次上游（与上游 v1.7.12 同款互斥）
    with _catalog_lock:
        cached = _models_cache.get(r)
        if cached and time.time() - cached["at"] < ttl:
            return cached["data"]
        stale = cached["data"] if cached else stale
        if stale is not None:
            _kick_refresh(r, log)
            return stale
        return _build_entries(r, log)


def models_source():
    """面板用：各出口目录的来源与最近填充时间。"""
    return {r: dict(v) for r, v in _models_source.items()}


# ---------------------------------------------------------------------------
# 手动刷新与每日兜底（移植自上游 v1.7.12 refresh_catalog / catalog_daily_pass）
# ---------------------------------------------------------------------------
#: 面板「刷新模型清单」的服务端冷却：同一出口两次手动强制拉取的最短间隔。
#: 自动链本来就有 300s 缓存，这层冷却拦的是误连点——上游有 WAF，节制本身就是
#: 不触发风控的一部分。
CATALOG_REFRESH_COOLDOWN = 30.0
_catalog_refresh_at = {}
_catalog_lock = threading.RLock()

#: 每日兜底：距上次成功从上游 API 拿到目录 ≥ 24h 就再拉一轮（每小时看一眼）。
CATALOG_DAILY_INTERVAL = 24 * 3600
_catalog_last_remote = {}


def note_remote_catalog(realm, when=None):
    """记下该出口最近一次成功从上游 API 拿到目录的时刻。"""
    if realm not in ("intl", "cn"):
        return
    _catalog_last_remote[realm] = when if when is not None else time.time()


def refresh_catalog(realm):
    """手动刷新：立即向上游 API 拉一次该出口的目录并发布到 /v1/models。

    与自动链共用同一条合并管线（extras 开启：上游新增模型无需发版即可进
    清单）；与自动链的差别是不读桌面缓存、不走窄端点——拉不到就如实说拉
    不到，失败不清旧缓存（清单保持可用）。任何情况都不抛异常，返回面板
    可直接展示的 dict：{"ok", "realm", "source", "count", "cooldown"?,
    "retry_after"?, "msg"}。
    """
    if realm not in ("intl", "cn"):
        adapter = _realm_adapter(realm)
        if adapter is None:
            return {"ok": False, "realm": realm, "source": None, "count": 0,
                    "msg": "没有渠道提供出口 %s 的模型目录" % realm}
        try:
            live = adapter.live_models(realm, force=True) or []
        except Exception:
            live = []
        if not live:
            return {"ok": False, "realm": realm, "source": None, "count": 0,
                    "msg": "上游未返回可用目录（暂无可用账号或网络异常），已保留现有清单"}
        entries = [(mid, meta or {}) for mid, meta in live]
        _models_source[realm] = {"source": "live", "at": time.time(),
                                 "count": len(entries)}
        return {"ok": True, "realm": realm, "source": "remote",
                "count": len(entries),
                "msg": "已从上游 API 更新清单，共 %d 个模型" % len(entries)}
    now = time.time()
    with _catalog_lock:
        wait = CATALOG_REFRESH_COOLDOWN - (now - _catalog_refresh_at.get(realm, 0.0))
        if wait > 0:
            return {"ok": False, "realm": realm, "source": None, "count": 0,
                    "cooldown": True, "retry_after": round(wait, 1),
                    "msg": "刷新太频繁：约 %d 秒后可再试" % max(1, int(wait + 0.5))}
        # 先登记再拉取：失败也进冷却，连点的高频重试在这里就被拦住。
        _catalog_refresh_at[realm] = now
        live = None
        if _force_provider is not None:
            try:
                live = _force_provider(realm) or None
            except Exception:
                live = None
        if not live:
            return {"ok": False, "realm": realm, "source": None, "count": 0,
                    "msg": "上游未返回可用目录（暂无可用账号或网络异常），已保留现有清单"}
        entries = merge_catalog([(mid, meta or {}) for mid, meta in live],
                                realm=realm, extras=True)
        _models_cache[realm] = {"at": time.time(), "data": entries}
        _models_source[realm] = {"source": "live", "at": time.time(),
                                 "count": len(entries)}
        note_remote_catalog(realm)
    return {"ok": True, "realm": realm, "source": "remote", "count": len(entries),
            "msg": "已从上游 API 更新清单，共 %d 个模型" % len(entries)}


def catalog_daily_due(now=None):
    """到期的出口列表：距上次成功 API 获取 ≥ 24h（从未成功过也算到期）。"""
    now = now if now is not None else time.time()
    return [r for r in ("intl", "cn")
            if now - _catalog_last_remote.get(r, 0.0) >= CATALOG_DAILY_INTERVAL]


def catalog_daily_pass(now=None, log=None):
    """每日兜底的一轮：只为到期的出口各触发一次强制刷新（复用 30s 冷却）。"""
    done = []
    for realm in catalog_daily_due(now):
        out = refresh_catalog(realm)
        if log:
            log("catalog daily: %s -> %s" % (realm, out.get("msg")))
        done.append((realm, out))
    return done


def catalog_daily_loop(log=None):
    # 先等启动流程跑完（账号池、服务就位），之后每小时看一眼。
    time.sleep(60)
    while True:
        try:
            catalog_daily_pass(log=log)
        except Exception as exc:
            if log:
                log("catalog daily: pass failed (%s)" % exc)
        time.sleep(3600)


def start_catalog_daily(log=None):
    threading.Thread(target=catalog_daily_loop, kwargs={"log": log},
                     daemon=True, name="catalog-daily").start()


def invalidate_models(realm=None):
    if realm:
        _models_cache.pop("cn" if realm == "cn" else "intl", None)
    else:
        _models_cache.clear()


def catalog_meta_for(model_id, realm=None):
    """只读本地：模型元数据（已填充的目录缓存优先，静态表兜底，不发网络请求）。"""
    if not model_id:
        return {}
    if realm in ("cn", "intl"):
        r = realm
    else:
        r = detect_model_realm(model_id) or str(realm or "") or "intl"
    data = (_models_cache.get(r) or {}).get("data")
    if data:
        for mid, meta in data:
            if mid == model_id and isinstance(meta, dict):
                return meta
    for item in static_models(r):
        if isinstance(item, dict) and item.get("id") == model_id:
            return item
    return {}


def model_catalog_meta(model, realm=None):
    """兼容旧名：模型的目录元数据，没有则 {}。"""
    return catalog_meta_for(model, realm=realm)


def model_reasoning_meta(model, realm=None):
    return catalog_meta_for(model, realm=realm).get("reasoning") or {}


def model_default_effort(model, realm=None):
    effort = model_reasoning_meta(model, realm=realm).get("defaultEffort")
    return effort.strip() if isinstance(effort, str) and effort.strip() else None


# ---------------------------------------------------------------------------
# 标注链：上下文/输出上限
# ---------------------------------------------------------------------------
def annotate_limits(model_id, meta=None, realm=None):
    """算出一个模型的 (context, output, sources, clamp)，供 /v1/models 注记。

    分两种口径：
    - intl/cn（WorkBuddy 两出口）：四级查找（remote > 知识表 > 本地缓存 >
      默认），自上游 v1.7.12 吸收；知识表本就是为这批模型建的。
    - 渠道自有目录的出口（如 trae）：渠道 meta 是唯一权威——官方给多少
      标多少，官方没给的不编造（对齐二开 AgentHub traeLimits 口径：
      「绝不给编造的默认值」，编造的输出上限会引发下游误判）。

    探测到的钳制值只作额外注记（output_clamp），不覆盖规格值。
    """
    meta = meta or {}
    remote_context = (meta.get("maxInputTokens") or meta.get("context_length") or 0)
    remote_output = (meta.get("maxOutputTokens") or meta.get("max_output_tokens") or 0)
    if realm not in ("intl", "cn"):
        context = int(remote_context) if remote_context else None
        output = int(remote_output) if remote_output else None
        sources = {"context": "remote" if context else "unknown",
                   "output": "remote" if output else "unknown"}
        clamp = probes.clamp_for(_dirs["probe"] or _dirs["account"] or ".", model_id)
        return {"context": context, "output": output,
                "sources": sources, "output_clamp": clamp}
    context, output, sources = modelsdev.lookup(
        model_id, remote_context=remote_context, remote_output=remote_output,
        directory=_dirs["account"])
    clamp = probes.clamp_for(_dirs["probe"] or _dirs["account"] or ".", model_id)
    return {
        "context": context,
        "output": output,
        "sources": sources,
        "output_clamp": clamp,
    }


def model_entry(mid, meta, realm=None):
    """构造 /v1/models 的富条目（多客户端能力字段 + 标注链注记）。"""
    meta = meta or {}
    r = "cn" if realm == "cn" else ("intl" if realm == "intl" else str(realm or ""))
    limits = annotate_limits(mid, meta, realm=r)
    item = {
        "id": mid,
        "object": "model",
        "created": int(time.time()),
        # 按出口标注归属渠道（intl/cn 是 WorkBuddy 两个出口；其他出口归认领渠道）
        "owned_by": _realm_adapter(r).id if (r not in ("intl", "cn")
                                             and _realm_adapter(r)) else "workbuddy",
    }
    name = meta.get("name")
    if name:
        item["name"] = name
    desc = meta.get("descriptionZh") or meta.get("descriptionEn")
    if desc:
        item["description"] = desc

    vision = bool(meta.get("supportsImages")) and not meta.get("disabledMultimodal")
    tools = bool(meta.get("supportsToolCall"))
    thinks = bool(meta.get("supportsReasoning"))
    inputs = ["text"] + (["image"] if vision else [])

    # 能力字段按各家客户端的读法同时给出多种拼写
    item["capabilities"] = {"vision": vision, "tool_calls": tools, "reasoning": thinks}
    item["supports_vision"] = vision
    item["supports_images"] = vision
    item["supports_tool_calls"] = tools
    item["supports_reasoning"] = thinks
    item["vision"] = vision
    item["multimodal"] = vision
    item["abilities"] = {"vision": vision, "functionCall": tools,
                         "function_call": tools, "reasoning": thinks}
    item["input_modalities"] = inputs
    item["output_modalities"] = ["text"]
    item["modalities"] = {"input": inputs, "output": ["text"]}
    item["architecture"] = {
        "input_modalities": inputs,
        "output_modalities": ["text"],
        "modality": "+".join(inputs) + "->text",
    }

    # ---- 上下文档位：标注链结果优先，目录原始值兜底 ----
    if limits["context"]:
        item["context_length"] = limits["context"]
        item["max_input_tokens"] = limits["context"]
    if limits["output"]:
        item["max_output_tokens"] = limits["output"]
        item["max_completion_tokens"] = limits["output"]
    item["limit_sources"] = limits["sources"]
    if limits["output_clamp"]:
        # 实测上游会把超长 max_tokens 钳到这个值：只标注，不改规格字段
        item["output_clamp"] = limits["output_clamp"]
        item["max_output_tokens_clamped"] = limits["output_clamp"]
    ctx = (meta.get("contextWindow") or {}).get("supportedLengths")
    if ctx:
        item["context_windows"] = ctx

    reasoning = meta.get("reasoning") or {}
    efforts = reasoning.get("supportedEfforts")
    if efforts:
        item["reasoning_efforts"] = efforts
    if reasoning.get("effort"):
        item["reasoning_fixed_effort"] = reasoning["effort"]
    if reasoning.get("defaultEffort"):
        item["reasoning_default_effort"] = reasoning["defaultEffort"]
    if reasoning.get("canDisableThinking") is not None:
        item["reasoning_can_disable"] = reasoning["canDisableThinking"]
    if mid == "deepseek-v4.1-flash":
        item["reasoning_efforts"] = ["low", "high", "max"]
        item["reasoning_default_effort"] = "high"
        item.pop("reasoning_fixed_effort", None)
    if meta.get("onlyReasoning") is not None:
        item["always_reasoning"] = bool(meta.get("onlyReasoning"))

    if meta.get("credits"):
        # 仅原样透传官方倍率字符串（x0.59 credits 之类），不做人民币换算
        item["credits"] = meta["credits"]
    if meta.get("member_credits"):
        # 渠道官方折扣数据（如 trae 会员折后倍率）：折后价 ≠ 原价才由面板显示
        item["member_credits"] = meta["member_credits"]
    if meta.get("vendor"):
        item["vendor"] = meta["vendor"]
    if meta.get("temperature") is not None:
        item["temperature"] = meta["temperature"]
    if meta.get("top_p") is not None:
        item["top_p"] = meta["top_p"]
    if meta.get("isDefault"):
        item["is_default"] = True
    tags = [t for t in (meta.get("tags") or [])
            if isinstance(t, str) and not t.startswith("badge:")]
    if tags:
        item["tags"] = tags
    return item


def models_payload(realm=None, log=None):
    """GET /v1/models 的响应体（应用共享）。"""
    r = "cn" if realm == "cn" else ("intl" if realm == "intl" else str(realm or ""))
    entries = fetch_models(realm=r, log=log)
    return {
        "object": "list",
        "data": [model_entry(mid, meta, realm=r) for mid, meta in entries],
        "realm": r,
    }


def known_realms(ctx=None):
    """全站出口清单：intl/cn 恒在，其余来自注册表里各渠道声明的出口。"""
    realms = ["intl", "cn"]
    if ctx is not None:
        try:
            from integrations import registry as registry_mod
            for realm in registry_mod.REGISTRY.all_realms():
                if realm and realm not in realms:
                    realms.append(realm)
        except Exception:
            pass
    return realms


def warm_modelsdev(log=None):
    """后台预热 models.dev 索引（失败静默）。"""
    return modelsdev.refresh_async(_dirs["account"] or ".", log=log)


def probe_model(base_url, api_key, model, **kwargs):
    """跑一次输出钳制探测并落盘（探测脚本与面板共用）。"""
    result = probes.probe_model(base_url, api_key, model, **kwargs)
    if not result.get("dry_run"):
        probes.save_probe(_dirs["probe"] or _dirs["account"] or ".", model, result)
    return result
