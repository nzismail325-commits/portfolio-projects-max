# -*- coding: utf-8 -*-
"""panel/routes.py —— 面板接口路由组（本地自研，上游无对应）

所有面板数据经这里出：接口按渠道（realm）过滤并携带渠道标记返回，
前端不猜数据属于谁（§2.1/§2.2 归属控制）。

路由组：
  /panel/status  /panel/login  /panel/logout  /panel/password
  /channels                渠道清单（前端据此渲染页签与按钮）
  /accounts                账号治理（列表 / 启停 / 权重 / 禁用模型 / 备注）
  /accounts/credits        余额刷新
  /models/source           目录来源
  /usage  /usage/recent  /usage/perf  /usage/by-account  /usage/timeseries
  /usage/analytics
  /tasks  /tasks/job       成长任务进度与一键作业
  /scheduler  /scheduler/records
  /settings  /settings/save
  /logs                    运行时日志（落库开关打开时读库）
  /updates                 更新检查状态
  /activity/history        签到/打卡历史
"""
import json
import re
import time

from core import authz
from core import http as http_mod
from infra import activity
from infra import logstore as logstore_mod
from infra import panel_auth
from infra import settings
from integrations import registry
from tasks import growth
from tasks import taskstore


def _query_first(query, name, default=None):
    """多值 query dict 取首值；缺省回 default。"""
    return (query.get(name) or [default])[0]


def _query_bool(query, name, default=False):
    """开关参数："1"/"true"/"yes" 为真；缺省回 default。"""
    values = query.get(name)
    if not values:
        return bool(default)
    return values[0] in ("1", "true", "yes")


def _query_int(query, name, default, lo=None, hi=None):
    """整型参数：非法/缺省回 default；给边界时钳到 [lo, hi]。"""
    try:
        value = int((query.get(name) or [default])[0])
    except (TypeError, ValueError):
        value = default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _require_capability(handler, realm, cap, message):
    """出口归属渠道未声明该能力时写好错误响应并返回它；否则返回 None。"""
    adapter = registry.REGISTRY.find_realm_owner(realm)
    if adapter is None or cap not in adapter.capabilities:
        return handler.error(400, message, "invalid_request_error")
    return None


def _realm(handler, default=None):
    """查询参数里的 realm；未给时返回 None（= 全渠道汇总，由调用方标注）。"""
    value = _query_first(handler.query(), "realm")
    if value in ("", None):
        return default
    return value


def _channels(handler):
    ctx = handler.ctx
    return registry.panel_channels(ctx)


# ---------------------------------------------------------------- 登录
def panel_status(handler, path):
    ctx = handler.ctx
    return handler.json(200, {
        "panel_password_required": True,
        "panel_password_is_default": settings.panel_password_is_default(ctx.accounts_dir),
        "authenticated": handler.panel_ok(),
        "version": ctx.version(),
        "default_realm": ctx.current_realm,
        "channels": _channels(handler),
    })


def panel_login(handler, path):
    """面板密码登录：每真实来源 5 次失败 / 60 秒。"""
    ctx = handler.ctx
    payload = handler.read_json()
    password = str(payload.get("password") or "")
    key = panel_auth.login_rate_limit_key(handler.peer_ip(), handler.headers)
    if not panel_auth.login_allowed(key):
        wait = panel_auth.login_retry_after(key)
        return handler.error(429, "尝试过于频繁，请 %d 秒后再试" % wait,
                             "rate_limit_error", extra={"retry_after": wait})
    if not settings.verify_panel_password(ctx.accounts_dir, password):
        panel_auth.note_login_failure(key)
        return handler.error(401, "密码不正确", "invalid_request_error")
    panel_auth.note_login_success(key)
    token = ctx.panel_sessions.create(ctx.accounts_dir)
    return handler.json(200, {"ok": True, "token": token})


def panel_logout(handler, path):
    token = handler.panel_token()
    if token:
        handler.ctx.panel_sessions.revoke(token, handler.ctx.accounts_dir)
    return handler.json(200, {"ok": True})


def panel_password(handler, path):
    """改面板密码：需要已登录会话；改完吊销全部旧令牌。"""
    ctx = handler.ctx
    payload = handler.read_json()
    current = str(payload.get("current") or "")
    new_password = str(payload.get("password") or "")
    if not settings.verify_panel_password(ctx.accounts_dir, current):
        return handler.error(401, "当前密码不正确", "invalid_request_error")
    try:
        settings.set_panel_password(ctx.accounts_dir, new_password)
    except ValueError as exc:
        return handler.error(400, str(exc), "invalid_request_error")
    ctx.panel_sessions.revoke_all(ctx.accounts_dir)
    return handler.json(200, {"ok": True})


# ---------------------------------------------------------------- 渠道
def channels(handler, path):
    """前端渲染入口：页面/页签/按钮只按这份清单来。"""
    ctx = handler.ctx
    realms = []
    for meta in _channels(handler):
        for realm in meta.get("realms") or []:
            if isinstance(realm, dict):
                realms.append(dict(realm, channel=meta.get("id")))
    defaults = ctx.task_defaults()
    labels = ctx.task_labels()
    scopes = {item["id"]: item for item in registry.REGISTRY.panel_task_scopes(ctx)}
    return handler.json(200, {
        "channels": _channels(handler),
        "realms": realms,
        "current_realm": ctx.current_realm,
        "scheduler_tasks": [
            {"id": tid, "label": labels.get(tid, tid),
             "defaults": defaults.get(tid, {}),
             "channel": (scopes.get(tid) or {}).get("channel", ""),
             "realms": (scopes.get(tid) or {}).get("realms", [])}
            for tid in defaults
        ],
    })


# ---------------------------------------------------------------- 账号
def accounts(handler, path):
    ctx = handler.ctx
    realm = _realm(handler)
    pool = ctx.pool
    views = []
    if pool:
        for account in pool.accounts:
            if realm and account.realm != realm:
                continue
            item = account.public()
            item["channel"] = _owner_channel(account.realm)
            adapter = registry.REGISTRY.find_realm_owner(account.realm)
            item["identityPending"] = bool(
                adapter is not None and adapter.login_account_pending(account))
            views.append(item)
    return handler.json(200, {
        "accounts": views,
        "storage": ctx.accounts_dir,
        "usable": pool.count_ready(realm=realm) if pool else 0,
        "realms": _known_realms(),
        "realm": realm or "",
    })


def _known_realms():
    out = []
    for meta in registry.panel_channels(None):
        for realm in meta.get("realms") or []:
            if isinstance(realm, dict) and realm.get("id"):
                out.append({"id": realm["id"], "label": realm.get("label"),
                            "channel": meta.get("id")})
    return out


def _owner_channel(realm):
    adapter = registry.REGISTRY.find_realm_owner(realm)
    return adapter.id if adapter else ""


def account_action(handler, path):
    """账号操作：enable / weight / disabled_models / note / delete / checkin /
    refresh / probe。"""
    ctx = handler.ctx
    payload = handler.read_json()
    uid = str(payload.get("uid") or "").strip()
    action = str(payload.get("action") or "").strip()
    pool = ctx.pool
    if not pool or not uid:
        return handler.error(400, "missing uid", "invalid_request_error")
    account = pool.get(uid)
    if account is None:
        return handler.error(404, "no such account", "invalid_request_error")

    if action == "enable":
        result = pool.set_enabled(uid, bool(payload.get("enabled", True)))
    elif action == "weight":
        result = pool.set_weight(uid, payload.get("weight"))
    elif action == "disabled_models":
        result = pool.set_disabled_models(uid, payload.get("models") or [])
    elif action == "note":
        result = pool.set_note(uid, payload.get("note") or "")
    elif action == "delete":
        pool.remove(uid)
        return handler.json(200, {"ok": True})
    elif action == "checkin":
        res = account.checkin(trigger="manual")
        return handler.json(200, {
            "ok": bool(res.get("ok")),
            "message": res.get("message") or res.get("error") or "",
            "result": res,
        })
    elif action == "refresh":
        res = account.refresh()
        return handler.json(200, {"ok": bool(res), "error": account.last_error})
    elif action == "probe":
        return handler.json(200, account.probe())
    elif action == "clear_error":
        account.clear_error()
        account.save(ctx.accounts_dir)
        result = account.public()
    elif action == "sync_nickname":
        try:
            nickname = account.sync_nickname()
            return handler.json(200, {"ok": True, "nickname": nickname})
        except Exception as exc:
            return handler.error(502, str(exc))
    else:
        return handler.error(400, "unknown action: %s" % action,
                             "invalid_request_error")
    if result is None:
        return handler.error(400, "action failed", "invalid_request_error")
    return handler.json(200, {"ok": True, "account": result})


def accounts_credits(handler, path):
    """刷新（或读缓存）各账号余额；有积分则顺带抬出 402 停车。"""
    from auth import accounts as accounts_mod
    ctx = handler.ctx
    realm = _realm(handler)
    force = _query_bool(handler.query(), "refresh")
    results = []
    pool = ctx.pool
    for account in (pool.accounts if pool else []):
        if realm and account.realm != realm:
            continue
        res = accounts_mod.fetch_credits_recovering(account, force=force)
        results.append({"uid": account.uid, "ok": res.get("ok", False),
                        "cached": res.get("cached", False),
                        "cacheAge": res.get("cacheAge"),
                        "error": res.get("error", ""),
                        "credits": account.credits})
    views = [dict(a.public(), channel=_owner_channel(a.realm))
             for a in (pool.accounts if pool else []) if not realm or a.realm == realm]
    return handler.json(200, {"results": results, "accounts": views, "realm": realm or ""})


def credits_detail(handler, path):
    from auth import accounts as accounts_mod
    ctx = handler.ctx
    query = handler.query()
    uid = _query_first(query, "uid", "")
    refresh = _query_bool(query, "refresh")
    account = ctx.pool.get(uid) if (ctx.pool and uid) else None
    if account is None:
        return handler.error(404, "no such account", "invalid_request_error")
    if refresh or not account.credits or not account.credits.get("packages"):
        accounts_mod.fetch_credits_cached(account, force=refresh)
    return handler.json(200, {
        "ok": True, "uid": account.uid, "nickname": account.nickname,
        "loginAccount": account.login_account(),
        "realm": account.realm, "channel": _owner_channel(account.realm),
        "credits": account.credits})


def accounts_login_start(handler, path):
    ctx = handler.ctx
    payload = handler.read_json()
    realm = str(payload.get("realm") or ctx.current_realm)
    gate = _require_capability(handler, realm, registry.CAP_ACCOUNTS,
                               "该出口不支持账号登录")
    if gate is not None:
        return gate
    adapter = registry.REGISTRY.find_realm_owner(realm)
    if adapter is not None:
        # 渠道自有登录流（refreshToken 换发型等）优先；返回 None 落回通用登录
        try:
            info = adapter.start_login(ctx, realm,
                                       platform=payload.get("platform") or "CLI")
        except Exception as exc:
            return handler.error(502, str(exc))
        if info is not None:
            return handler.json(200, info)
    try:
        info = ctx.pool.start_login(realm=realm,
                                    platform=payload.get("platform") or "CLI")
    except Exception as exc:
        return handler.error(502, str(exc))
    return handler.json(200, info)


def accounts_login_poll(handler, path):
    ctx = handler.ctx
    state = _query_first(handler.query(), "state", "")
    for adapter in registry.REGISTRY.all():
        try:
            result = adapter.poll_login(ctx, state)
        except Exception:
            result = None
        if result is not None:
            return handler.json(200, result)
    return handler.json(200, ctx.pool.poll_login(state))


def accounts_login_submit(handler, path):
    """手动粘贴回调地址（渠道声明 paste_token 能力时由渠道处理）。"""
    ctx = handler.ctx
    payload = handler.read_json()
    state = str(payload.get("state") or "")
    raw = str(payload.get("callback") or payload.get("url") or "")
    if not raw:
        return handler.error(400, "missing callback", "invalid_request_error")
    for adapter in registry.REGISTRY.all():
        result = None
        if registry.CAP_PASTE_TOKEN in (adapter.capabilities or ()):
            try:
                result = adapter.submit_login(ctx, state, raw)
            except Exception as exc:
                return handler.error(502, str(exc))
        if result is not None:
            return handler.json(200, result)
    return handler.error(400, "当前出口不支持粘贴回调登录", "invalid_request_error")


def accounts_login_action(handler, path):
    """表单类登录的附加动作（短信发码 / 提交验证码等，渠道自行解释）。"""
    ctx = handler.ctx
    payload = handler.read_json()
    state = str(payload.get("state") or "")
    action = str(payload.get("action") or "")
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    if not state or not action:
        return handler.error(400, "missing state or action",
                             "invalid_request_error")
    for adapter in registry.REGISTRY.all():
        try:
            result = adapter.login_action(ctx, state, action, values)
        except Exception as exc:
            return handler.error(502, str(exc))
        if result is not None:
            return handler.json(200, result)
    return handler.error(400, "登录会话不存在或已过期", "invalid_request_error")


def accounts_login_cancel(handler, path):
    """取消登录会话（渠道自有会话与池子通用会话都认）。"""
    ctx = handler.ctx
    payload = handler.read_json() if handler.command == "POST" else {}
    state = str(payload.get("state") or _query_first(handler.query(), "state", ""))
    for adapter in registry.REGISTRY.all():
        try:
            result = adapter.cancel_login(ctx, state)
        except Exception:
            result = None
        if result is not None:
            return handler.json(200, result)
    return handler.json(200, {"ok": ctx.pool.cancel_login(state)})


def accounts_identity_sync(handler, path):
    """补一次登录身份（面板账号列显示/复制邮箱或手机号）。"""
    ctx = handler.ctx
    payload = handler.read_json()
    uid = str(payload.get("uid") or "").strip()
    account = ctx.pool.get(uid) if (ctx.pool and uid) else None
    if account is None:
        return handler.error(404, "no such account", "invalid_request_error")
    adapter = registry.REGISTRY.find_realm_owner(account.realm)
    if adapter is None or not adapter.login_account_pending(account):
        return handler.json(200, {"ok": True, "skipped": True,
                                  "loginAccount": account.login_account()})
    try:
        identity = adapter.sync_login_account(ctx, account)
    except Exception as exc:
        return handler.error(502, str(exc))
    return handler.json(200, {
        "ok": bool(identity),
        "loginAccount": account.login_account(),
        "identityPending": adapter.login_account_pending(account),
    })


def accounts_import_desktop(handler, path):
    """扫描 / 导入本机桌面凭据。"""
    from auth import accounts as accounts_mod
    ctx = handler.ctx
    payload = handler.read_json() if handler.command == "POST" else {}
    if payload.get("import"):
        realm = payload.get("realm") or ""
        owner = registry.REGISTRY.find_realm_owner(realm) if realm else None
        if owner is not None and registry.CAP_DESKTOP_IMPORT in (owner.capabilities or ()):
            try:
                imported = owner.import_desktop(ctx, payload)
            except Exception as exc:
                return handler.error(400, str(exc))
            if imported is not None:
                return handler.json(200, {"ok": True, "imported": [imported.public()]})
        imported = ctx.pool.import_desktop_credential(
            path=payload.get("path") or None, realm=payload.get("realm") or None)
        if isinstance(imported, list):
            return handler.json(200, {"ok": True, "imported": [a.public() for a in imported]})
        return handler.json(200, {"ok": True, "imported": [imported.public()]})
    candidates = accounts_mod.scan_desktop_credentials()
    for adapter in registry.all_channels():
        if registry.CAP_DESKTOP_IMPORT not in (adapter.capabilities or ()):
            continue
        try:
            candidates.extend(adapter.scan_desktop(ctx) or [])
        except Exception as exc:
            candidates.append({
                "realm": adapter.id, "file": adapter.label,
                "valid": False, "usable": False,
                "error": str(exc)[:160],
            })
    return handler.json(200, {"candidates": candidates})


# ---------------------------------------------------------------- 代理槽
def proxy_slots(handler, path):
    """代理槽列表；给 realm 时只返回该出口的槽（含未分配的旧版全局槽）。"""
    ctx = handler.ctx
    realm = _realm(handler)
    return handler.json(200, {"slots": settings.proxy_slots(ctx.accounts_dir, realm),
                              "realm": realm or ""})


def proxy_slots_save(handler, path):
    """保存代理槽。带 realm 时只替换该出口的槽，其余出口原样保留。"""
    ctx = handler.ctx
    payload = handler.read_json()
    slots = payload.get("slots")
    if not isinstance(slots, list):
        return handler.error(400, "slots must be a list", "invalid_request_error")
    realm = str(payload.get("realm") or "").strip() or None
    saved = settings.set_proxy_slots(ctx.accounts_dir, slots, realm)
    # 重解析必须拿全量槽：按出口保存后，别的出口已生效的代理不能因此丢失
    ctx.apply_proxy_slots()
    return handler.json(200, {"ok": True, "slots": saved, "realm": realm or ""})


def proxy_slots_probe(handler, path):
    ctx = handler.ctx
    payload = handler.read_json()
    url = str(payload.get("url") or "").strip()
    if not url:
        return handler.error(400, "missing url", "invalid_request_error")
    return handler.json(200, ctx.probe_proxy(url))


def proxy_slots_discover(handler, path):
    """批量探测 mihomo 槽位端口段，报告可达出口（自上游 v1.7.12 移植）。"""
    # POST 必须排空请求体：残留 body 会污染 keep-alive 连接上的下一个请求。
    handler.read_json()
    return handler.json(200, {"slots": handler.ctx.discover_proxy_slots()})


# ---------------------------------------------------------------- 用量
def usage(handler, path):
    realm = _realm(handler)
    return handler.json(200, handler.ctx.usage.snapshot(realm=realm))


def usage_recent(handler, path):
    query = handler.query()
    limit = _query_int(query, "limit", 100, lo=1, hi=1000)
    return handler.json(200, {"rows": handler.ctx.usage.recent(
        limit, realm=_realm(handler))})


def usage_perf(handler, path):
    query = handler.query()
    sample = _query_int(query, "sample", 5000, lo=10, hi=20000)
    return handler.json(200, handler.ctx.usage.perf(sample=sample,
                                                    realm=_realm(handler)))


def usage_by_account(handler, path):
    return handler.json(200, {"accounts": handler.ctx.usage.by_account()})


def usage_timeseries(handler, path):
    days = _query_int(handler.query(), "days", 14)
    return handler.json(200, handler.ctx.usage.timeseries(
        days=days, realm=_realm(handler)))


def usage_analytics(handler, path):
    return handler.json(200, handler.ctx.usage.analytics())


def models_source(handler, path):
    from intel import catalog
    return handler.json(200, {"sources": catalog.models_source()})


def models_list(handler, path):
    """模型清单页：当前出口的 /v1/models 富条目（含标注链注记）。

    与 /v1/models 共用同一套「只列出可用」判定，否则设置开关在面板上看不出
    任何效果。
    """
    from core import proxy_api
    from intel import catalog
    from intel import tiers
    ctx = handler.ctx
    realm = _realm(handler, default="intl")
    payload = catalog.models_payload(realm)
    data = payload.get("data") or []
    if settings.models_only_available(ctx.accounts_dir):
        data = [entry for entry in data
                if proxy_api.model_servable(ctx, entry.get("id"), realm)]
        payload["data"] = data
    # 与 /v1/models 同一口径：只按目录 tier 表标注「免费账号不可用」，
    # 不宣称可用；没有标注 = 未知（对齐上游 v1.7.30 #609）。
    gate_at = tiers.ingested_at(realm)
    for entry in data:
        if tiers.requires_pro(entry.get("id"), realm):
            entry["entitlement"] = {
                "source": "catalog",
                "required": "standard",
                "at": gate_at,
            }
    return handler.json(200, payload)


def models_refresh(handler, path):
    """面板「刷新模型清单」：强制从上游 API 拉一次指定出口的目录。"""
    from intel import catalog
    payload = handler.read_json() if handler.command == "POST" else {}
    realm = str((payload or {}).get("realm") or "").strip().lower()
    return handler.json(200, catalog.refresh_catalog(realm))


# ---------------------------------------------------------------- 任务
def tasks(handler, path):
    ctx = handler.ctx
    data = growth.progress_all(ctx.pool)
    for item in data.get("accounts") or []:
        item["channel"] = _owner_channel(item.get("realm"))
    # 成长任务中心的适用出口由后端裁决下发（现仅国内版有成长体系），
    # 前端按它决定成长任务卡在哪个出口渲染，不自己猜。
    return handler.json(200, dict(data, msg="" if data.get("accounts")
                                  else "未找到可用账号",
                                  growth_realm=growth.GROWTH_REALM))


def tasks_job(handler, path):
    ctx = handler.ctx
    if handler.command == "POST":
        payload = handler.read_json()
        realm = str(payload.get("realm") or ctx.current_realm)
        gate = _require_capability(handler, realm, registry.CAP_TASKS,
                                   "该出口不支持成长任务")
        if gate is not None:
            return gate
        return handler.json(200, growth.start_growth_job(ctx.pool, realm=realm))
    job_id = _query_first(handler.query(), "job_id", "")
    job = growth.growth_job_get(job_id)
    if job is None:
        return handler.error(404, "no such job", "invalid_request_error")
    return handler.json(200, job)


def scheduler(handler, path):
    ctx = handler.ctx
    if handler.command == "POST":
        payload = handler.read_json()
        task_id = str(payload.get("task") or "all")
        return handler.json(200, ctx.scheduler.trigger_now(task_id))
    return handler.json(200, ctx.scheduler.status() if ctx.scheduler
                        else {"enabled": False, "msg": "未运行"})


def scheduler_records(handler, path):
    query = handler.query()
    kind = _query_first(query, "kind") or None
    uid = _query_first(query, "uid") or None
    realm = _query_first(query, "realm") or None
    days_raw = _query_first(query, "days")
    try:
        days = int(days_raw) if days_raw else None
    except (TypeError, ValueError):
        days = None
    logs = taskstore.list_logs(kind=kind, uid=uid, days=days, realm=realm,
                               limit=_query_int(query, "limit", 100, 1, 500),
                               offset=_query_int(query, "offset", 0, 0, 1000000))
    # 统计与计数与表格同口径：带出口时只统计该出口（T-05）
    return handler.json(200, {
        "logs": logs,
        "total": taskstore.count_logs(kind=kind, uid=uid, days=days, realm=realm),
        "stats": taskstore.stats(days=days, realm=realm),
        "kinds": taskstore.KIND_LABELS,
        "levels": taskstore.LEVEL_LABELS,
        "realm": realm or "",
    })


# ---------------------------------------------------------------- 设置
def runtime_settings(handler, path):
    ctx = handler.ctx
    keys = []
    for entry in authz.configured_keys(ctx):
        keys.append({
            "id": entry.get("id") or "",
            "name": entry.get("name") or "",
            "realm": entry.get("realm") or "",
            "enabled": entry.get("enabled", True) is not False,
            "models": entry.get("models") or [],
            # Key 完全不可观测（面板口径 2026-10-19）：不下发掩码——部分掩码
            # 形如 guon******iban 会被当成损坏值；要明文走 /settings/reveal。
        })
    header, idle = settings.upstream_timeouts(ctx.accounts_dir)
    return handler.json(200, {
        "version": ctx.version(),
        "panel_password_is_default": settings.panel_password_is_default(ctx.accounts_dir),
        "auth_required": authz.auth_required(ctx),
        "auth_disabled": settings.auth_disabled(ctx.accounts_dir),
        "api_keys": keys,
        "accounts_dir": ctx.accounts_dir,
        "usage_dir": ctx.usage_dir,
        "settings_file": settings.settings_path(ctx.accounts_dir),
        "automation": ctx.automation_config(),
        "daily_chat_web": settings.daily_chat_web(ctx.accounts_dir),
        "daily_chat_models": settings.daily_chat_models(ctx.accounts_dir),
        "daily_chat_models_max": settings.DAILY_CHAT_MODELS_MAX,
        "daily_chat_budget": settings.daily_chat_budget(ctx.accounts_dir),
        "daily_chat_budget_default": settings.DAILY_CHAT_BUDGET_DEFAULT,
        "daily_chat_budget_max": settings.DAILY_CHAT_BUDGET_MAX,
        "daily_chat_web_concurrency": settings.daily_chat_web_concurrency(ctx.accounts_dir),
        "daily_chat_web_concurrency_max": settings.DAILY_CHAT_WEB_CONCURRENCY_MAX,
        "daily_chat_web_retry_backoff": settings.daily_chat_web_retry_backoff(
            ctx.accounts_dir),
        "daily_chat_web_retry_backoff_default":
            settings.DAILY_CHAT_WEB_RETRY_BACKOFF_DEFAULT,
        "daily_chat_web_retry_backoff_max":
            settings.DAILY_CHAT_WEB_RETRY_BACKOFF_MAX,
        "daily_chat_web_random_prompt": settings.daily_chat_web_random_prompt(ctx.accounts_dir),
        "daily_chat_web_prompts": settings.daily_chat_web_prompts(ctx.accounts_dir),
        "daily_chat_web_prompts_max": settings.DAILY_CHAT_WEB_PROMPTS_MAX,
        "auto_switch_product": settings.auto_switch_product(ctx.accounts_dir),
        "identity": settings.identity_config(ctx.accounts_dir),
        "filter_models_by_key": settings.filter_models_by_key(ctx.accounts_dir),
        "models_only_available": settings.models_only_available(ctx.accounts_dir),
        "affinity_stable_key_enabled": settings.affinity_stable_key_enabled(
            ctx.accounts_dir),
        "account_max_concurrent": settings.account_max_concurrent(ctx.accounts_dir),
        "account_max_concurrent_max": settings.ACCOUNT_MAX_CONCURRENT_MAX,
        "upstream_timeouts": {"header": header, "idle": idle},
        "prompt": settings.prompt_config(ctx.accounts_dir),
        "proxy_slots": settings.proxy_slots(ctx.accounts_dir),
        "egress_backoff": settings.egress_backoff_enabled(ctx.accounts_dir),
        "local_web_tools": settings.local_web_tools(ctx.accounts_dir),
        "log_db": {
            "enabled": settings.log_db_enabled(ctx.accounts_dir),
            "max_rows": settings.log_db_max_rows(ctx.accounts_dir),
            "max_days": settings.log_db_max_days(ctx.accounts_dir),
            "max_bytes": settings.log_db_max_bytes(ctx.accounts_dir),
        },
        "update_check": dict(ctx.updates.status(), enabled=settings.update_check_enabled(ctx.accounts_dir)),
        "current_realm": ctx.current_realm,
        "realms": _known_realms(),
    })


def settings_save(handler, path):
    """面板设置保存：只接受白名单字段，未知字段忽略。"""
    ctx = handler.ctx
    payload = handler.read_json()
    applied = []

    if "api_keys" in payload:
        raw = payload.get("api_keys")
        if not isinstance(raw, list):
            return handler.error(400, "api_keys must be a list", "invalid_request_error")
        current = {entry["id"]: entry for entry in authz.configured_keys(ctx)}
        settings.set_api_keys(ctx.accounts_dir,
                              authz.merge_api_key_entries(current, raw))
        applied.append("api_keys")

    if "automation" in payload and isinstance(payload.get("automation"), dict):
        settings.set_automation(ctx.accounts_dir, payload["automation"])
        applied.append("automation")

    if "daily_chat_web" in payload:
        settings.set_daily_chat_web(ctx.accounts_dir, payload["daily_chat_web"])
        applied.append("daily_chat_web")

    if "daily_chat_models" in payload:
        raw = payload.get("daily_chat_models")
        if isinstance(raw, str):
            raw = [part for part in re.split(r"[,\r\n]+", raw) if part.strip()]
        if not isinstance(raw, (list, tuple)):
            return handler.error(400, "daily_chat_models must be a list",
                                 "invalid_request_error")
        if len(raw) > settings.DAILY_CHAT_MODELS_MAX:
            return handler.error(
                400, "daily_chat_models cannot hold more than %d models"
                     % settings.DAILY_CHAT_MODELS_MAX, "invalid_request_error")
        for item in raw:
            if (not isinstance(item, str) or len(item) > settings.DAILY_CHAT_MODEL_MAX_LEN
                    or (item and not re.match(r"^[A-Za-z0-9._:-]+$", item))):
                return handler.error(400, "daily_chat_models entries must be model ids",
                                     "invalid_request_error")
        settings.set_daily_chat_models(ctx.accounts_dir, raw)
        applied.append("daily_chat_models")

    if "daily_chat_budget" in payload:
        raw = payload.get("daily_chat_budget")
        if (isinstance(raw, bool) or not isinstance(raw, int)
                or raw < 0 or raw > settings.DAILY_CHAT_BUDGET_MAX):
            return handler.error(
                400, "daily_chat_budget must be 0..%d seconds"
                     % settings.DAILY_CHAT_BUDGET_MAX, "invalid_request_error")
        settings.set_daily_chat_budget(ctx.accounts_dir, raw)
        applied.append("daily_chat_budget")

    if "daily_chat_web_concurrency" in payload:
        settings.set_daily_chat_web_concurrency(
            ctx.accounts_dir, payload["daily_chat_web_concurrency"])
        applied.append("daily_chat_web_concurrency")

    if "daily_chat_web_retry_backoff" in payload:
        settings.set_daily_chat_web_retry_backoff(
            ctx.accounts_dir, payload["daily_chat_web_retry_backoff"])
        applied.append("daily_chat_web_retry_backoff")

    if "daily_chat_web_random_prompt" in payload:
        settings.set_daily_chat_web_random_prompt(
            ctx.accounts_dir, payload["daily_chat_web_random_prompt"])
        applied.append("daily_chat_web_random_prompt")

    if "daily_chat_web_prompts" in payload:
        settings.set_daily_chat_web_prompts(
            ctx.accounts_dir, payload["daily_chat_web_prompts"])
        applied.append("daily_chat_web_prompts")

    if "auto_switch_product" in payload:
        settings.set_auto_switch_product(ctx.accounts_dir, payload["auto_switch_product"])
        applied.append("auto_switch_product")

    if "identity" in payload and isinstance(payload["identity"], dict):
        value = payload["identity"].get("private_data")
        if value is not None:
            try:
                settings.set_identity_private_data(ctx.accounts_dir, value)
            except ValueError as exc:
                return handler.error(400, str(exc), "invalid_request_error")
            applied.append("identity")

    if "filter_models_by_key" in payload:
        settings.set_filter_models_by_key(ctx.accounts_dir,
                                          payload["filter_models_by_key"])
        applied.append("filter_models_by_key")

    if "models_only_available" in payload:
        settings.set_models_only_available(ctx.accounts_dir,
                                           payload["models_only_available"])
        applied.append("models_only_available")

    if "affinity_stable_key_enabled" in payload:
        try:
            settings.set_affinity_stable_key_enabled(
                ctx.accounts_dir, payload["affinity_stable_key_enabled"])
        except ValueError as exc:
            return handler.error(400, str(exc), "invalid_request_error")
        applied.append("affinity_stable_key_enabled")

    if "account_max_concurrent" in payload:
        try:
            settings.set_account_max_concurrent(
                ctx.accounts_dir, payload["account_max_concurrent"])
        except ValueError as exc:
            return handler.error(400, str(exc), "invalid_request_error")
        applied.append("account_max_concurrent")

    if "upstream_timeouts" in payload and isinstance(payload["upstream_timeouts"], dict):
        timeouts = payload["upstream_timeouts"]
        settings.set_upstream_timeouts(ctx.accounts_dir,
                                       header=timeouts.get("header"),
                                       idle=timeouts.get("idle"))
        applied.append("upstream_timeouts")

    if "prompt" in payload and isinstance(payload["prompt"], dict):
        prompt = payload["prompt"]
        settings.set_prompt_config(ctx.accounts_dir, prompt.get("mode"), prompt.get("file"))
        applied.append("prompt")

    if "auth_disabled" in payload:
        settings.set_auth_disabled(ctx.accounts_dir, payload["auth_disabled"])
        applied.append("auth_disabled")

    if "egress_backoff" in payload:
        settings.set_egress_backoff_enabled(ctx.accounts_dir, payload["egress_backoff"])
        applied.append("egress_backoff")

    if "local_web_tools" in payload:
        settings.set_local_web_tools(ctx.accounts_dir, payload["local_web_tools"])
        applied.append("local_web_tools")

    if "log_db" in payload and isinstance(payload["log_db"], dict):
        db = payload["log_db"]
        if "enabled" in db:
            settings.set_log_db_enabled(ctx.accounts_dir, db["enabled"])
        if "max_rows" in db:
            settings.set_log_db_max_rows(ctx.accounts_dir, db["max_rows"])
        if "max_days" in db:
            settings.set_log_db_max_days(ctx.accounts_dir, db["max_days"])
        if "max_bytes" in db:
            settings.set_log_db_max_bytes(ctx.accounts_dir, db["max_bytes"])
        ctx.configure_log_store()
        applied.append("log_db")

    if "update_check_enabled" in payload:
        settings.set_update_check_enabled(ctx.accounts_dir, payload["update_check_enabled"])
        applied.append("update_check_enabled")

    if "proxy_slots" in payload and isinstance(payload["proxy_slots"], list):
        settings.set_proxy_slots(ctx.accounts_dir, payload["proxy_slots"])
        ctx.apply_proxy_slots()
        applied.append("proxy_slots")

    if "current_realm" in payload:
        ctx.save_persisted_realm(str(payload["current_realm"]))
        applied.append("current_realm")

    return handler.json(200, {"ok": True, "applied": applied})


def settings_reveal(handler, path):
    """取明文 Key（只给已登录面板，且必须显式请求）。"""
    ctx = handler.ctx
    wanted = _query_first(handler.query(), "id", "")
    for entry in authz.configured_keys(ctx):
        if entry.get("id") == wanted:
            return handler.json(200, {"id": wanted, "key": entry.get("key") or ""})
    return handler.error(404, "no such key", "invalid_request_error")


# ---------------------------------------------------------------- 日志
def logs(handler, path):
    """运行日志：落库打开时读数据库，关闭时读进程内环形缓冲。

    两条路径返回同一形状（total / logs / max_id），前端不必区分来源。
    刚打开落库开关的一瞬间库里可能还是空的（开关之前的历史只在内存环里），
    这时把内存环的结果一并返回，避免「一开落库反而看不到日志」。
    """
    ctx = handler.ctx
    query = handler.query()
    limit = _query_int(query, "limit", 200, lo=1, hi=2000)
    filters = {
        "limit": limit,
        "level": _query_first(query, "level", ""),
        "tag": _query_first(query, "tag", ""),
        "search": _query_first(query, "search", ""),
        "since_id": _query_int(query, "since_id", 0),
    }

    if settings.log_db_enabled(ctx.accounts_dir) and ctx.log_store is not None:
        try:
            stored = ctx.log_store.query(**filters)
        except Exception:
            stored = None
        if stored is not None:
            if stored.get("logs"):
                return handler.json(200, dict(stored, source="db"))
            # 库刚打开还没写入：退回内存环，别让面板瞬间空掉
            memory = ctx.log_ring.query(**filters)
            if memory.get("logs"):
                return handler.json(200, dict(memory, source="memory"))
            return handler.json(200, dict(stored, source="db"))

    result = ctx.log_ring.query(**filters)
    return handler.json(200, dict(result, source="memory"))


# ---------------------------------------------------------------- 更新
def updates(handler, path):
    ctx = handler.ctx
    if handler.command == "POST":
        # 必须把请求体读掉：keep-alive 连接上残留的 body 会让下一个请求
        # 解析错乱（服务器回 501），面板表现为「检查成功后整页加载失败」。
        handler.read_json()
        return handler.json(200, ctx.updates.check(manual=True))
    return handler.json(200, ctx.updates.status())


# ---------------------------------------------------------------- 活动历史
def activity_history(handler, path):
    query = handler.query()
    try:
        payload = activity.query(range_key=_query_first(query, "range", "") or None,
                                 uid=_query_first(query, "uid", ""),
                                 task=_query_first(query, "task", ""),
                                 result=_query_first(query, "result", ""),
                                 limit=_query_first(query, "limit", "") or None)
    except ValueError as exc:
        return handler.error(400, str(exc), "invalid_request_error")
    return handler.json(200, payload)


def install(router=None):
    router = router or http_mod.ROUTER
    # 登录相关：不需要 Key，也不需要已有会话
    router.add("GET", "/panel/status", panel_status, needs_auth=False, exact=True)
    router.add("POST", "/panel/login", panel_login, needs_auth=False, exact=True)
    router.add("POST", "/panel/logout", panel_logout, needs_auth=False, exact=True)
    router.add("POST", "/panel/password", panel_password, needs_auth=False,
               needs_panel=True, exact=True)

    # 面板数据：已登录会话即可
    for method, prefix, func in (
        ("GET", "/channels", channels),
        ("GET", "/accounts", accounts),
        ("GET", "/accounts/credits", accounts_credits),
        ("GET", "/accounts/credits/detail", credits_detail),
        ("GET", "/accounts/login/poll", accounts_login_poll),
        ("POST", "/accounts/login/start", accounts_login_start),
        ("POST", "/accounts/login/submit", accounts_login_submit),
        ("POST", "/accounts/login/action", accounts_login_action),
        ("POST", "/accounts/login/cancel", accounts_login_cancel),
        ("GET", "/accounts/login/cancel", accounts_login_cancel),
        ("POST", "/accounts/identity/sync", accounts_identity_sync),
        ("POST", "/accounts/import-desktop", accounts_import_desktop),
        ("GET", "/accounts/import-desktop", accounts_import_desktop),
        ("POST", "/accounts/action", account_action),
        ("GET", "/proxy-slots", proxy_slots),
        ("POST", "/proxy-slots/save", proxy_slots_save),
        ("POST", "/proxy-slots/probe", proxy_slots_probe),
        ("POST", "/proxy-slots/discover", proxy_slots_discover),
        ("GET", "/usage", usage),
        ("GET", "/usage/recent", usage_recent),
        ("GET", "/usage/perf", usage_perf),
        ("GET", "/usage/by-account", usage_by_account),
        ("GET", "/usage/timeseries", usage_timeseries),
        ("GET", "/usage/analytics", usage_analytics),
        ("GET", "/models/source", models_source),
        ("GET", "/models/list", models_list),
        ("POST", "/models/refresh", models_refresh),
        ("GET", "/tasks", tasks),
        ("GET", "/tasks/job", tasks_job),
        ("POST", "/tasks/job", tasks_job),
        ("GET", "/scheduler", scheduler),
        ("POST", "/scheduler", scheduler),
        ("GET", "/scheduler/records", scheduler_records),
        ("GET", "/settings", runtime_settings),
        ("POST", "/settings/save", settings_save),
        ("GET", "/settings/reveal", settings_reveal),
        ("GET", "/logs", logs),
        ("GET", "/updates", updates),
        ("POST", "/updates", updates),
        ("GET", "/activity/history", activity_history),
    ):
        router.add(method, prefix, func, needs_auth=False, needs_panel=True,
                   exact=True)
