# -*- coding: utf-8 -*-
"""integrations/workbuddy.py —— WorkBuddy 网关渠道适配器

本文件是重构后的 WorkBuddy 渠道边界：所有 WorkBuddy 私有事实集中在这里，
核心（core / auth / infra / tasks / intel）不认识任何 WorkBuddy 端点。

职责：
1. 两个出口（国际版 intl / 国内版 cn）的端点、UA、身分来源，注册进 auth；
2. 实时模型目录（远端产品配置 → 桌面缓存 → 窄目录端点 → 静态表兜底）；
3. 出站流：选号、治理（429/402/403/5xx）、产品切换、连接池、提示词降级；
4. 渠道任务：签到、旅行、夜猫、开学季、连登、活跃上报（调度器按注册表执行）；
5. 面板板块元信息与账号治理接口。

协议事实来源：上游 v1.7.12 与二开 wb-proxy（同源），治理口径见重构方案 §3/§4。
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import auth.accounts as accounts_mod
from auth import identity
from core import net
from core import ratelimit
from core import upstream_body
from core import upstream_pool
from infra import egress, settings
from integrations import registry, workbuddy_prompts
from intel import tiers

# ── 端点常量（WorkBuddy 私有）────────────────────────────────
CHAT_PATH = "/v2/chat/completions"
MODELS_PATH = "/v2/enterprises/personal/models"
REMOTE_CONFIG_PATH = "/v3/config"
REFRESH_PATH = "/v2/auth/token/refresh"
AUTH_STATE_PATH = "/v2/plugin/auth/state"
AUTH_TOKEN_PATH = "/v2/plugin/auth/token"
LOGIN_ACCOUNT_PATH = "/v2/plugin/login/account"
CHECKIN_PATH = "/v2/billing/meter/daily-checkin"
GET_RESOURCE_PATH = "/v2/billing/meter/get-user-resource"
RESOURCE_SUMMARY_PATH = "/billing/meter/get-user-resource-summary"
ENTERPRISE_USAGE_PATH = "/billing/meter/get-enterprise-user-usage"
PROFILE_PATH = "/console/account"

#: 地区构建（-sg）与实验构建（-x）是目录里已有名字的付费变体，面板只展示裸名
VARIANT_SUFFIXES = ("-sg", "-x")

#: 国际版每日活跃打卡的网页通道常量
WEB_CONVERSATIONS_PATH = "/console/as/conversations/"

#: 上游 body 里表明「模型/服务不可用」而非凭证问题的业务码（主上游 #499）
MODEL_SCOPED_ERROR_CODES = frozenset((11102, 11129, 11134, 11150, 11158))


def _model_scoped_errors_penalize_account():
    """逃生口：恢复「任何 5xx 都给账号记失败」的旧行为。"""
    raw = os.environ.get("WB_MODEL_SCOPED_ERRORS_PENALIZE", "")
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _upstream_error_code(detail):
    try:
        payload = json.loads(detail or "")
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return int(payload.get("code"))
    except (TypeError, ValueError):
        return None
WEB_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0")
DAILY_CHAT_MODEL = "deepseek-v4.1-flash"
#: 自动候选序列的免费兜底（面板未配置 daily_chat_models 时使用）。
DAILY_CHAT_FALLBACKS_INTL = ("hy3", "hy4-preview-f", "hy4-preview",
                             "glm-5.3-flash")
DAILY_CHAT_FALLBACKS_CN = ("hy3", "hy4-preview-f", "hy4-preview")
PROBE_MODEL = "glm-5.2"  # 两个区都在线的均衡模型，账号「测试」探测专用最小请求
DAILY_CHAT_WEB_PROMPT = "Hi"
WEB_TURN_TIMEOUT = int(os.environ.get("WB_WEB_TURN_TIMEOUT") or "120")

#: 桌面客户端缓存的产品配置（含官方模型选择器的完整清单）
PRODUCT_CONFIG_CACHE = {
    "intl": os.path.join(os.path.expanduser("~"), ".workbuddy-ai", "cache",
                         "acc-product-config-v3.json"),
    "cn": os.path.join(os.path.expanduser("~"), ".workbuddy", "cache",
                       "acc-product-config-v3.json"),
}

REALM_LABELS = {"intl": "国际版 (Global)", "cn": "国内版 (China)"}

_session_lock = threading.Lock()
_switch_ctx = threading.local()


# --- 风控连坐保护（自上游 v1.7.16 移植，WorkBuddy 渠道私有） ----------------
# 看到上游风控 403（code 11140「账号存在异常行为，已被限制使用」）立即停手，
# 解封前严禁换号继续打同一台设备——设备指纹会连坐。四个开关的默认值按
# 「宁可少服务一会儿，也别把账号送走」取：
#   WB_RESTRICTED_403_ROTATE_MAX  一次请求最多再换几个号（默认 0 = 不换）
#   WB_RESTRICTION_WAVE_MIN       窗口内几个号被限制就整池暂停（默认 2）
#   WB_RESTRICTION_WAVE_WINDOW    连坐判定的时间窗，秒（默认 900）
#   WB_RESTRICTION_HOLD_SECONDS   整池暂停时长，秒（默认 1800；0 = 关闭暂停）
RESTRICTED_403_COOLDOWN = accounts_mod.RESTRICTED_ACCOUNT_COOLDOWN


def _env_number(name, default, cast=float):
    try:
        return max(0, cast(os.environ.get(name) or default))
    except (TypeError, ValueError):
        return default


RESTRICTED_403_ROTATE_MAX = int(_env_number("WB_RESTRICTED_403_ROTATE_MAX", 0, int))
RESTRICTION_WAVE_MIN = max(1, int(_env_number("WB_RESTRICTION_WAVE_MIN", 2, int)))
RESTRICTION_WAVE_WINDOW = _env_number("WB_RESTRICTION_WAVE_WINDOW", 900.0)
RESTRICTION_HOLD_SECONDS = _env_number("WB_RESTRICTION_HOLD_SECONDS", 1800.0)

_RESTRICTION_LOCK = threading.Lock()
_RESTRICTION_EVENTS = {}   # realm -> {uid: epoch}（窗口内被限制的账号）
_RESTRICTION_HOLD = {}     # realm -> 暂停到哪个 epoch


def reset_restriction_state():
    """清空连坐保护状态（测试，以及人工确认「已申诉、可以恢复派发」时用）。"""
    with _RESTRICTION_LOCK:
        _RESTRICTION_EVENTS.clear()
        _RESTRICTION_HOLD.clear()


def restriction_hold_remaining(realm, now=None):
    """该区域整池暂停还剩多少秒（0 = 没有暂停）。"""
    now = time.time() if now is None else now
    with _RESTRICTION_LOCK:
        return max(0.0, _RESTRICTION_HOLD.get(realm, 0.0) - now)


def restriction_hold_message(realm, remaining):
    """整池暂停期间交给客户端的说明。"""
    return ("上游风控已限制本区域账号（403 / code 11140，账号存在异常行为）。"
            "网关已暂停派发 %d 秒，避免继续换号重试导致同设备账号连坐被封。"
            "请勿换号或高频重试；按官方渠道申诉（通常 1-3 个工作日自动解除），"
            "解封后再恢复。 Upstream restricted the account(s); "
            "dispatch paused %ds to avoid further bans."
            % (int(remaining), int(remaining)))


def note_account_restriction(realm, uid="", now=None, ctx=None):
    """记一次账号级风控限制；返回整池暂停的到期 epoch（0 = 尚未触发）。

    同一窗口内达到 RESTRICTION_WAVE_MIN 个**不同**账号被限制，就认为上游在
    按设备 / 出口做连坐清扫：把整个区域暂停 RESTRICTION_HOLD_SECONDS，期间
    不再向上游发任何请求（open_stream 直接快速失败），等人工确认或时间到
    再恢复。按 uid 去重，所以同一个号被反复探测 / 测试不会把暂停骗出来。
    """
    now = time.time() if now is None else now
    uid = str(uid or "").strip() or "-"
    with _RESTRICTION_LOCK:
        events = {key: at for key, at in _RESTRICTION_EVENTS.get(realm, {}).items()
                  if now - at <= RESTRICTION_WAVE_WINDOW}
        events[uid] = now
        _RESTRICTION_EVENTS[realm] = events
        if len(events) < RESTRICTION_WAVE_MIN or RESTRICTION_HOLD_SECONDS <= 0:
            return 0.0
        until = max(_RESTRICTION_HOLD.get(realm, 0.0),
                    now + RESTRICTION_HOLD_SECONDS)
        _RESTRICTION_HOLD[realm] = until
    _log("upstream restriction wave on %s: %d account(s) restricted within %.0fs; "
         "pausing dispatch for %.0fs to avoid cross-account bans (uid %s)"
         % (realm, len(events), RESTRICTION_WAVE_WINDOW,
            RESTRICTION_HOLD_SECONDS, uid[:8]), ctx)
    return until


def _persist_restriction(account, ctx=None):
    """把 restrictedUntil 落盘；失败只记日志，不影响请求路径。"""
    try:
        path = getattr(account, "path", "") or ""
        if path:
            account.save(os.path.dirname(path))
    except Exception as exc:
        _log("account %s: restriction not persisted: %s"
             % ((getattr(account, "uid", "") or "?")[:8], exc), ctx)


#: 识别风控限制 403 的正文特征。内容审核的 403 走降级提示词那条路，二者必须
#: 分开：对被限制的账号换提示词没有意义。code 匹配用正则（requestId 是 hex，
#: 裸字符串 "11140" 可能撞上），措辞只收实测的限制用语，不猜。
_RESTRICTED_403_CODE_RE = re.compile(r'"code"\s*:\s*"?11140"?')
_RESTRICTION_403_MARKERS = ("unusual activity", "账号存在异常行为", "已被限制")


def restriction_is_account_level(detail):
    """True when a 403 body says the ACCOUNT is restricted, not the content.

    实测正文：{"code":11140,"msg":"request illegal",...,"displayMsg":{"en":
    "Your account has been restricted due to unusual activity","zh":"账号存在
    异常行为，已被限制使用"}}。en 在前 zh 在后，短截断也保得住 code 与 en；
    拿不全的正文宁可漏判回内容审核路径，也不误判。
    """
    if not detail:
        return False
    if _RESTRICTED_403_CODE_RE.search(detail):
        return True
    lowered = detail.lower()
    return any(marker in lowered for marker in _RESTRICTION_403_MARKERS)


def _log(msg, ctx=None):
    logger = getattr(ctx, "log", None) if ctx is not None else None
    if logger:
        try:
            logger(msg)
        except Exception:
            pass


# ---------------------------------------------------------------- realm 配置
def _login_account_from_token(account):
    """从 WorkBuddy JWT 里取登录账号：国际版 email，国内版 preferred_username（手机号）。"""
    claims = accounts_mod.jwt_claims(getattr(account, "access_token", ""))
    for key in ("email", "preferred_username"):
        value = str(claims.get(key) or "").strip()
        if accounts_mod.looks_like_login_account(value):
            return value
    return ""


def realm_configs():
    """两个出口的端点/身分配置（供 auth.accounts 注入）。"""
    return {
        "intl": {
            "name": REALM_LABELS["intl"],
            "chat_upstream": "https://www.workbuddy.ai",
            "billing_upstream": "https://www.workbuddy.ai",
            "origin": "https://www.workbuddy.ai",
            "domain": "www.workbuddy.ai",
            "chat_ua": identity.DESKTOP_UA_INTL,
            "billing_ua": "WorkBuddy/%s" % identity.DESKTOP_VERSION_INTL,
            "web_origin": "https://www.workbuddy.ai",
            "web_ua": WEB_USER_AGENT,
            "info_filename": "workbuddy-desktop-ai.info",
            "chat_path": CHAT_PATH,
            "refresh_path": REFRESH_PATH,
            "auth_state_path": AUTH_STATE_PATH,
            "auth_token_path": AUTH_TOKEN_PATH,
            "login_account_path": LOGIN_ACCOUNT_PATH,
            "checkin_path": CHECKIN_PATH,
            "credits_path": GET_RESOURCE_PATH,
            "resource_summary_path": RESOURCE_SUMMARY_PATH,
            "enterprise_usage_path": ENTERPRISE_USAGE_PATH,
            "profile_path": PROFILE_PATH,
            "web_conversations_url": "https://www.workbuddy.ai" + WEB_CONVERSATIONS_PATH,
            "daily_chat_model": DAILY_CHAT_MODEL,
            "daily_chat_fallback_models": DAILY_CHAT_FALLBACKS_INTL,
            "probe_model": PROBE_MODEL,
            "daily_chat_prompt": DAILY_CHAT_WEB_PROMPT,
            "daily_chat_prompts_fn": workbuddy_prompts.builtin_prompts,
            "web_turn_timeout": WEB_TURN_TIMEOUT,
            "login_account_fn": _login_account_from_token,
            "has_checkin": False,
            "has_daily_chat": True,
        },
        "cn": {
            "name": REALM_LABELS["cn"],
            "chat_upstream": identity.CN_CHAT_BASE,
            "billing_upstream": "https://www.codebuddy.cn",
            "origin": "https://www.codebuddy.cn",
            "domain": "copilot.tencent.com",
            "chat_ua": identity.DESKTOP_UA_CN,
            "billing_ua": "WorkBuddy/%s" % identity.DESKTOP_VERSION_CN,
            "web_origin": "https://www.workbuddy.cn",
            "web_ua": WEB_USER_AGENT,
            "info_filename": "workbuddy-desktop.info",
            "chat_path": CHAT_PATH,
            "refresh_path": REFRESH_PATH,
            "auth_state_path": AUTH_STATE_PATH,
            "auth_token_path": AUTH_TOKEN_PATH,
            "login_account_path": LOGIN_ACCOUNT_PATH,
            "checkin_path": CHECKIN_PATH,
            "credits_path": GET_RESOURCE_PATH,
            "resource_summary_path": RESOURCE_SUMMARY_PATH,
            "enterprise_usage_path": ENTERPRISE_USAGE_PATH,
            "profile_path": PROFILE_PATH,
            "web_conversations_url": "https://www.workbuddy.cn" + WEB_CONVERSATIONS_PATH,
            "daily_chat_model": DAILY_CHAT_MODEL,
            "daily_chat_fallback_models": DAILY_CHAT_FALLBACKS_CN,
            "probe_model": PROBE_MODEL,
            "daily_chat_prompt": DAILY_CHAT_WEB_PROMPT,
            "daily_chat_prompts_fn": workbuddy_prompts.builtin_prompts,
            "web_turn_timeout": WEB_TURN_TIMEOUT,
            "login_account_fn": _login_account_from_token,
            "has_checkin": True,
            "has_daily_chat": False,
        },
    }


# ---------------------------------------------------------------- 实时目录
def _remote_config_headers(account, realm, ua=None):
    cfg = accounts_mod.get_realm_config(realm)
    return {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": ua or cfg["chat_ua"],
        "Origin": cfg["origin"],
        "Referer": cfg["origin"] + "/",
        "Authorization": "Bearer " + account.access_token,
        "X-User-Id": account.uid,
    }


def _agent_model_lists(payload):
    """每个 agent 的裸模型 id 列表，名为 cli 的 agent 优先。"""
    roots = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        roots.append(data)
    cli, other = [], []
    for root in roots:
        agents = root.get("agents")
        if isinstance(agents, dict):
            entries = list(agents.items())
        elif isinstance(agents, list):
            entries = [((entry.get("name") if isinstance(entry, dict) else None), entry)
                       for entry in agents]
        else:
            continue
        for name, entry in entries:
            if not isinstance(entry, dict):
                continue
            models = entry.get("models")
            if not (isinstance(models, list) and models
                    and isinstance(models[0], str)):
                continue
            ids = [str(m).strip() for m in models if isinstance(m, str)]
            ids = [m for m in ids if m]
            if not ids:
                continue
            (cli if str(name or "").strip().lower() == "cli" else other).append(ids)
    return cli, other


def parse_remote_catalog(payload):
    """从 /v3/config 应答解析 (ids, meta)；没有可用列表返回 None。"""
    if not isinstance(payload, dict):
        return None
    cli_lists, other_lists = _agent_model_lists(payload)
    pool = cli_lists or other_lists
    best = max(pool, key=len) if pool else None
    ids, seen = [], set()
    for mid in best or []:
        if mid not in seen:
            seen.add(mid)
            ids.append(mid)
    if not ids:
        return None
    meta = {}

    def walk(node):
        if isinstance(node, dict):
            models = node.get("models")
            if (isinstance(models, list) and models
                    and isinstance(models[0], dict) and models[0].get("id")):
                for item in models:
                    mid = str(item.get("id") or "").strip()
                    if mid:
                        meta.setdefault(mid, item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return ids, meta


def curate_remote_catalog(ids, meta=None):
    """裁掉虚拟别名、付费变体与免费同族的付费项；其余保持上游顺序。"""
    from intel import catalog
    credits = catalog.snapshot_credits() if hasattr(catalog, "snapshot_credits") else {}
    for mid, item in (meta or {}).items():
        if isinstance(item, dict):
            credits[mid] = str(item.get("credits") or "").strip().lower()
    known = set(ids) | set(credits) | set(catalog.CN_UI_ORDER) | set(catalog.INTL_UI_ORDER)

    def free(mid):
        token = (credits.get(mid) or "").split()
        return bool(token) and token[0] in ("x0.00", "x0", "0", "0.00")

    out = []
    for mid in ids:
        if not catalog.is_chat_model(mid):
            continue
        if mid.endswith(VARIANT_SUFFIXES):
            continue
        if mid.endswith("-f"):
            base = mid[:-2]
            if base in known and free(base) and not free(mid):
                continue
        elif (mid + "-f") in known and free(mid + "-f") and not free(mid):
            continue
        out.append(mid)
    return out


def fetch_remote_product_config(ctx, realm):
    """从该出口自己的产品配置接口取 (ids, meta)，失败返回 None。"""
    if realm not in ("intl", "cn"):
        return None
    pool = ctx.pool
    account = pool.representative(realm=realm) if pool else None
    if account is None or not account.access_token:
        _log("remote catalog: no usable %s account, skipping" % realm, ctx)
        return None
    cfg = accounts_mod.get_realm_config(realm)
    url = cfg["chat_upstream"] + REMOTE_CONFIG_PATH
    uas = [cfg["chat_ua"]]
    if cfg.get("billing_ua") and cfg["billing_ua"] != cfg["chat_ua"]:
        uas.append(cfg["billing_ua"])
    last = None
    for ua in uas:
        req = urllib.request.Request(url, headers=_remote_config_headers(account, realm, ua),
                                     method="GET")
        try:
            with net.urlopen(req, timeout=10, proxy=account.proxy) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            last = exc
            continue
        # 层级表与模型目录来自同一份产品配置；先记下，免费号才不会在
        # 目录/选号里拿到 PRO 专属模型。
        tiers.ingest(realm, payload)
        parsed = parse_remote_catalog(payload)
        if parsed:
            return parsed
        last = "empty catalogue"
    _log("remote catalog: %s fetch failed (%s)" % (realm, last), ctx)
    return None


def read_product_config_models(realm):
    """读桌面客户端缓存的产品配置：[(id, meta), ...]。"""
    path = PRODUCT_CONFIG_CACHE.get("cn" if realm == "cn" else "intl")
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        return []
    tiers.ingest(realm, cfg)

    def find(node):
        if isinstance(node, dict):
            models = node.get("models")
            if (isinstance(models, list) and models
                    and isinstance(models[0], dict) and models[0].get("id")):
                return models
            for value in node.values():
                hit = find(value)
                if hit:
                    return hit
        return None

    out = []
    for item in find(cfg) or []:
        mid = item.get("id")
        if isinstance(mid, str) and mid:
            out.append((mid, item))
    return out


def fetch_endpoint_models(ctx, realm):
    """窄目录端点（CLI 面向）的模型 id 列表。"""
    pool = ctx.pool
    account = pool.pick(realm=realm) if pool else None
    if account is None:
        return []
    cfg = accounts_mod.get_realm_config(realm)
    req = urllib.request.Request(cfg["chat_upstream"] + MODELS_PATH, method="GET",
                                 headers=account.headers("chat"))
    try:
        with net.urlopen(req, timeout=30, proxy=account.proxy) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        _log("model discovery failed: %s" % exc, ctx)
        return []
    tiers.ingest(realm, payload)
    ids, seen = [], set()
    for agent in (payload.get("data") or {}).get("agents") or []:
        for mid in agent.get("models") or []:
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)
    return ids


def live_models(ctx, realm, force=False):
    """实时目录：远端产品配置优先 → 桌面缓存 → 窄端点 → 空（静态表兜底）。

    force=True（面板手动刷新 / 每日兜底）：只认上游 API，不读桌面缓存、
    不走窄端点——拿不到返回 None，让调用方如实报「未取到」（上游 v1.7.12
    手动刷新的同款语义）。
    """
    parsed = fetch_remote_product_config(ctx, realm)
    if parsed:
        ids, meta = parsed
        return [(mid, meta.get(mid) or {})
                for mid in curate_remote_catalog(ids, meta)]
    if force:
        return None
    cached = read_product_config_models(realm)
    if cached:
        return cached
    if realm == "intl":
        return [(mid, {}) for mid in fetch_endpoint_models(ctx, realm)]
    return []


# ---------------------------------------------------------------- 出站流
def _extract_affinity_key(headers, payload):
    key = (
        headers.get("X-Conversation-Id")
        or headers.get("Conversation-Id")
        or headers.get("X-Session-Id")
        or headers.get("Session-Id")
        or payload.get("conversation_id")
        or payload.get("session_id")
        or (payload.get("metadata") or {}).get("conversation_id")
    )
    return str(key).strip() if key else None


AFFINITY_MAX_MSGS = int(os.environ.get("WB_AFFINITY_MAX_MSGS", "400") or 0)


def _affinity_over_length(payload):
    if AFFINITY_MAX_MSGS <= 0:
        return False
    try:
        return len(payload.get("messages") or []) > AFFINITY_MAX_MSGS
    except TypeError:
        return False


def open_stream(ctx, payload, session_key=None, realm=None):
    """按账号池开出一条上游流。返回 (响应对象, 归属信息 dict)。

    这是治理链的主循环：每个候选账号试一次，按响应码分别处理并决定是换号、
    退避、还是把错误抛给调用方。抛出的异常类型：
      - RateLimited：模型级限流（429），带 Retry-After；
      - ContentRejected：内容审核 403（已做过降级重试）；
      - RuntimeError("no usable account...")：池子空了（503）；
      - 其他 HTTPError/URLError：最后一次失败原样抛出。

    开销上限：最多试 WB_UPSTREAM_MAX_ATTEMPTS（默认 6）个账号或
    WB_UPSTREAM_DEADLINE_SECONDS（默认 300）秒，先到为准——死出口每步吃满
    读超时也不能把客户端无限拖下去。
    """
    pool = ctx.pool
    realm = realm or ctx.current_realm
    model = str(payload.get("model") or "")
    # 连坐保护：同一区域刚有账号被上游风控限制，整池暂停派发。这里直接快速
    # 失败、一个上游请求都不发——继续打只会把同一台设备上的其他账号也送走。
    hold = restriction_hold_remaining(realm)
    if hold > 0:
        raise ratelimit.RateLimited(
            None, "upstream account restriction in effect",
            wait=int(hold) + 1,
            message=restriction_hold_message(realm, hold))
    body_dict = upstream_body.build_upstream_body(payload, ctx.system_prompt)
    body_rebuilt = False
    total = max(1, pool.count_ready(realm, model=model)) if pool else 1
    # +1：401 换发后重试同号要多占一个尝试位，不能挤掉换号轮换的名额。
    attempts, deadline = net.request_budget(total + 1)
    connect_timeout = ctx.upstream_connect_timeout()
    tried = set()
    last_error = None
    last_uid = None
    last_429 = None
    last_429_detail = ""
    last_403_detail = ""
    transient_hits = 0
    retry_rounds = 0
    # 这一轮请求已经换发过令牌的账号：401 可能只是访问令牌先于 JWT 时钟过期，
    # 每账号每请求至多换发一次，换发成功就重试同一个号，而不是默默换走一个
    # 本可挽救的凭据。
    refreshed = set()
    refresh_uid = None
    # 一次请求里因为 11140 换过的号数：默认 0，即第一个号被限制就停手。
    restricted_rotations = 0
    # 官方 VSCode 扩展的 X-Conversation-ID 是 32hex、会话稳定；网关没有会话
    # 映射，至少保证同一次 open_stream（含换号重试）里是同一个 id。
    vscode_conversation_id = identity.new_message_id()
    # 一轮 user send 的 request id：官方 CLI 在这一轮的所有请求（含重试/换号）
    # 复用同一个 X-Conversation-Request-ID，只有 message id 每请求新生成。
    # 生成在重试循环外，循环里只把它传给身份构造；桌面端 / VSCode 分支不消费它。
    turn_request_id = identity.new_turn_request_id()
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    egress_wait = getattr(_switch_ctx, "egress_wait", None) or (lambda _key: 0)

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        if refresh_uid is not None:
            account = pool.get(refresh_uid) if pool else None
            refresh_uid = None
        else:
            account = pool.pick_for_session(realm=realm, session_key=session_key,
                                            exclude=tried, model=model) if pool else None
        if account is None:
            if transient_hits and last_error is not None and retry_rounds < 2:
                retry_rounds += 1
                tried.clear()
                time.sleep(min(1.5 * transient_hits, 3.0))
                continue
            break
        if account.realm != realm:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        last_uid = account.uid
        cfg = accounts_mod.get_realm_config(realm)
        chat_url = account.chat_base_url() + cfg["chat_path"]
        # 官方 CLI 的 chat 请求体：gzip（RequestBodyGzip=true，带
        # Content-Encoding: gzip）+ 注入 cache_retention=long、去掉客户端
        # metadata 等内部键；VSCode 官方主 chat 也默认 gzip。紧凑 JSON：官方
        # 客户端（Node JSON.stringify）不带分隔符后的空格，默认 json.dumps 的
        # (", ", ": ") 会让 body 字节与 Content-Length 都成一处机器特征。
        attempt_body = body_dict
        cli_identity = account.is_cli_identity()
        vscode_identity = account.product == identity.PRODUCT_VSCODE
        if cli_identity:
            attempt_body = {k: v for k, v in attempt_body.items()
                            if k not in identity.CLI_BODY_DROP_FIELDS}
            attempt_body["cache_retention"] = identity.CLI_CACHE_RETENTION
        attempt_data = upstream_body.encode_upstream_body(attempt_body)
        if cli_identity or vscode_identity:
            attempt_data = identity.gzip_body(attempt_data)
        # 会话头族：VSCode 按官方 32hex 形态（同一次 open_stream 内稳定）并带
        # X-Model-ID；桌面端 / CLI 按 (账号, 会话键) 稳定派生，客户端没给会话键
        # 时保持每请求新生成。跨账号重试时按账号各自派生，不会把两个号串到
        # 同一个会话上；重试换号时 session_key / turn_request_id 都不变。
        if account.product == identity.PRODUCT_VSCODE:
            conv_id = vscode_conversation_id
        elif session_key:
            conv_id = identity.conversation_id_for(account.uid, session_key)
        else:
            conv_id = None
        req_headers = account.headers(
            purpose="chat", session_key=session_key,
            turn_request_id=turn_request_id, model=model,
            conversation_id=conv_id)
        if cli_identity or vscode_identity:
            req_headers["Content-Encoding"] = identity.REQUEST_CONTENT_ENCODING
        req = urllib.request.Request(chat_url, data=attempt_data, method="POST",
                                     headers=req_headers)
        # 头名原样上线（Request.add_header 会先 capitalize，有序原名单独挂在
        # 请求上给连接池路径用）。
        req.wb_exact_headers = list(req_headers.items())
        try:
            resp = net.urlopen(req, timeout=header_timeout, proxy=account.proxy,
                               connect_timeout=connect_timeout)
            _apply_stream_idle_timeout(resp, idle_timeout)
            account.note_success(model=model)
            ratelimit.reset_switch_counter(account, model)
            # 出口成功记账挪到流读完（core 按 egress_key 结算）：
            # 中途断流的请求不能算这条出口成功。
            return resp, {"account": account.uid, "realm": realm,
                          "account_obj": account,
                          "egress_key": upstream_pool.egress_key(
                              chat_url, account.proxy)}
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raw = net.read_http_error(exc, 600)
                detail = raw.decode("utf-8", "replace") if raw else ""
                reset_at = ratelimit.parse_reset(detail)
                if ratelimit.is_account_level(detail, reset_at):
                    wait = account.note_soft_rate("HTTP 429 (账号级限流)")
                    _log("account %s soft-rate limited (%r), cooling %.0fs (streak %d)"
                         % (account.uid[:8],
                            ratelimit.credential_scope_phrase(detail) or "account scope",
                            wait, account.soft_streak), ctx)
                    if session_key and pool:
                        pool.affinity.unbind(session_key)
                    last_error, last_429, last_429_detail = exc, exc, detail
                    continue
                wait = max(1.0, reset_at - time.time()) if reset_at else 60.0
                if reset_at is None and ratelimit.is_soft_shape(detail):
                    wait = account.note_unscoped_rate(model)
                    _log("account %s: unscoped 429, parking '%s' for %.0fs "
                         "(unscoped streak %d)"
                         % (account.uid[:8], model, wait, account.unscoped_streak), ctx)
                account.note_error("HTTP 429 (model throttled)", model=model,
                                   until=reset_at, cooldown=wait, detail=detail)
                if ctx.auto_switch_product() and ratelimit.try_switch_product(account, model):
                    tried.discard(account.uid)
                    try:
                        account.clear_error(model=model)
                    except Exception:
                        pass
                    if session_key and pool:
                        pool.affinity.unbind(session_key)
                    _log("account %s: %s 被限流，自动切换出站身分后重试"
                         % (account.uid[:8], model), ctx)
                    continue
                _log("account %s throttled on '%s' (429), retry in %ds"
                     % (account.uid[:8], model, int(wait)), ctx)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error, last_429, last_429_detail = exc, exc, detail
                continue
            if exc.code == 403:
                raw = net.read_http_error(exc, 600)
                detail = raw.decode("utf-8", "replace") if raw else ""
                # 先分流：上游风控限制（code 11140「账号存在异常行为，已被限制
                # 使用」）是账号级的坏，降级提示词救不了。处置按红线走：冷却这个
                # 账号（持久化）、记一次连坐事件，然后停手——不再把同一条请求
                # 换到下一个号上继续打（默认，见 RESTRICTED_403_ROTATE_MAX）。
                if restriction_is_account_level(detail):
                    account.note_restricted(detail=detail,
                                            cooldown=RESTRICTED_403_COOLDOWN)
                    _persist_restriction(account, ctx)
                    _log("account %s restricted by upstream (403 11140), "
                         "cooling %.0fs (persisted)"
                         % (account.uid[:8], RESTRICTED_403_COOLDOWN), ctx)
                    if session_key and pool:
                        pool.affinity.unbind(session_key)
                    last_error = exc
                    last_403_detail = detail
                    note_account_restriction(realm, account.uid, ctx=ctx)
                    # 红线：解封前不换号继续打同一台设备。默认把原因交给客户端
                    # 就停手，下一次请求自然会落到别的账号；需要旧行为（透明
                    # 换号）时把 WB_RESTRICTED_403_ROTATE_MAX 调大即可。
                    if restricted_rotations >= RESTRICTED_403_ROTATE_MAX:
                        break
                    restricted_rotations += 1
                    continue
                # 内容审核 403 在 passthrough/append 下多半是 system 指纹误杀：
                # 触发降级窗口并用降级后的 body 重试一次；custom 是显式选择，
                # 不降级。（二开口径：降级后仍轮换其他账号，不在这里停手。）
                mode = upstream_body.prompt_mode_config().get("mode")
                if not body_rebuilt and mode in ("passthrough", "append"):
                    upstream_body.trigger_degrade()
                    body_rebuilt = True
                    body_dict = upstream_body.build_upstream_body(payload, ctx.system_prompt)
                    tried.discard(account.uid)
                    _log("upstream 403 (content review) -> degraded prompt retry", ctx)
                    continue
                _log("upstream 403 for '%s' (content review), rotating" % model, ctx)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error, last_403_detail = exc, detail
                continue
            if exc.code == 402:
                raw = net.read_http_error(exc, 400)
                detail = raw.decode("utf-8", "replace") if raw else ""
                account.note_balance_cooled(detail or "HTTP 402 (余额不足)")
                _log("account %s out of credits (402), parked until 04:00"
                     % account.uid[:8], ctx)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = exc
                continue
            if exc.code == 401:
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                # 401 可能只是访问令牌先于 JWT 时钟过期：先换发一次再重试同一个
                # 号，别把可挽救的凭据默默轮换掉（每账号每请求至多一次）。
                if account.uid not in refreshed:
                    refreshed.add(account.uid)
                    try:
                        refreshed_ok = account.refresh()
                    except Exception as refresh_exc:
                        refreshed_ok = False
                        _log("account %s: token refresh after 401 failed: %s"
                             % (account.uid[:8], refresh_exc), ctx)
                    if refreshed_ok:
                        _log("account %s: HTTP 401, token refreshed; "
                             "retrying the same account" % account.uid[:8], ctx)
                        tried.discard(account.uid)
                        refresh_uid = account.uid
                        last_error = exc
                        continue
                _log("account %s rejected (HTTP 401), rotating" % account.uid[:8], ctx)
                account.note_error("HTTP 401", cooldown=60, single_account=(total <= 1))
                last_error = exc
                continue
            if exc.code >= 500:
                # 先看 body 里的业务码：11102/11129/11134/11150/11158 是模型或
                # 服务级问题，不是账号故障。照常罚号会让一个坏模型名把整池打熔断。
                detail = net.http_error_detail(exc)
                code = _upstream_error_code(detail)
                if (code in MODEL_SCOPED_ERROR_CODES
                        and not _model_scoped_errors_penalize_account()):
                    _log("upstream %s for '%s' (code %s, model-scoped); "
                         "not charging the account"
                         % (exc.code, model, code), ctx)
                    last_error = exc
                    break
                if exc.code in (500, 502, 503, 504):
                    transient_hits += 1
                    account.note_failure("HTTP %d" % exc.code)
                    _log("upstream %s for '%s' (code %s), retrying (fails=%d)"
                         % (exc.code, model,
                            code if code is not None else "-", account.fails), ctx)
                    if session_key and pool:
                        pool.affinity.unbind(session_key)
                    last_error = exc
                    continue
            if exc.code == 400:
                # 400 原样透传。11158（该用户类型不允许此模型）过去在这里记
                # 标记给目录用；现在目录 tier 表同时驱动调度器与那个标注，
                # 被门控的模型在本地就被拒，请求根本走不到这一步。
                raise
        except Exception as exc:
            if net.is_tls_verify_error(exc):
                # 证书链本机不信任：一次就够，换账号也换不掉同一条链，重试只会
                # 成倍增加失败的握手。按配置错误抛出带修复指引的错误。
                last_error = exc
                break
            if session_key and pool:
                pool.affinity.unbind(session_key)
            if net.looks_like_local_network(exc):
                _log("account %s: local network failure (%s), no penalty"
                     % (account.uid[:8], type(exc).__name__), ctx)
                last_error = exc
                continue
            if net.is_transient(exc):
                transient_hits += 1
                account.note_unknown_failure("connection: %s" % type(exc).__name__)
                key = upstream_pool.egress_key(chat_url, account.proxy)
                wait = egress.note_transient(key)
                _log("account %s: upstream connection hiccup for '%s' (%s), "
                     "retrying (degrade=%d, egress backoff %.1fs)"
                     % (account.uid[:8], model, type(exc).__name__,
                        account.degrade_count, wait), ctx)
                last_error = exc
                time.sleep(min(max(wait, 0.6 * transient_hits), 3.0))
                continue
            account.note_unknown_failure(str(exc)[:120])
            account.note_error(str(exc)[:120], cooldown=60, single_account=(total <= 1))
            last_error = exc
            continue

    if last_error is not None:
        try:
            last_error.account_uid = last_uid
        except Exception:
            pass
        if net.is_tls_verify_error(last_error):
            exc = net.TLSVerifyError(net.tls_verify_hint(last_error))
            exc.account_uid = last_uid
            raise exc
        if last_429 is not None:
            exc = ratelimit.RateLimited(
                last_429, last_429_detail,
                wait=ratelimit.retry_after_seconds(pool, realm, model))
            exc.account_uid = last_uid
            raise exc
        if last_403_detail:
            raise ratelimit.ContentRejected(last_403_detail, account_uid=last_uid)
        raise last_error
    throttled, wait = ratelimit.realm_model_throttled(pool, realm, model)
    if throttled:
        raise ratelimit.RateLimited(None, "usage exceeds frequency limit", wait=wait)
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or expired" % realm)


def _apply_stream_idle_timeout(response, seconds):
    """流式 idle 超时的共享实现（core/net），此处保留薄别名便于差量对照。"""
    net.set_stream_idle_timeout(response, seconds)


# ---------------------------------------------------------------- 渠道任务
def _cn_ready(account):
    return (getattr(account, "realm", "") == "cn"
            and getattr(account, "enabled", False)
            and bool(getattr(account, "access_token", "")))


def _intl_ready(account):
    return (getattr(account, "realm", "") == "intl"
            and getattr(account, "enabled", False)
            and bool(getattr(account, "access_token", "")))


def scheduler_tasks(ctx):
    """本渠道注入调度器的任务清单：[(task_id, label, handler, defaults)]。

    调度器只遍历注册表执行，不硬编码任何任务 id。
    """
    from tasks import travel, nightcat, streak, school, growth

    def checkin(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="checkin", source=source, ready=_cn_ready,
            action=lambda acc: _do_checkin(acc, source))

    def travel_task(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="travel", source=source, ready=_cn_ready,
            classify=travel.classify, action=lambda acc: travel.run(acc))

    def activity(reason, source="auto"):
        cfg = ctx.automation_config().get("activity") or {}
        count = cfg.get("count") or 1
        return ctx.run_task_over_accounts(
            kind="activity", source=source, ready=_cn_ready,
            classify=growth.classify_activity,
            action=lambda acc: growth.run_activity_report(acc, count=count))

    def nightcat_task(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="nightcat", source=source, ready=_cn_ready,
            classify=nightcat.classify, action=lambda acc: nightcat.run(acc))

    def streak_task(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="streak", source=source, ready=_cn_ready,
            classify=streak.classify, action=lambda acc: streak.run(acc))

    def school_task(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="school", source=source, ready=_cn_ready,
            classify=school.classify,
            action=lambda acc: school.run(acc))

    def dailychat(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="dailychat", source=source, ready=_intl_ready,
            guest_action=lambda acc: ("already" if not acc.can_daily_chat() else None),
            action=lambda acc: _do_dailychat(ctx, acc, source),
            concurrency=settings.daily_chat_web_concurrency(ctx.accounts_dir))

    def keepalive(reason, source="auto"):
        return ctx.run_task_over_accounts(
            kind="keepalive", source=source,
            ready=lambda acc: (getattr(acc, "realm", "") in ("intl", "cn")
                               and getattr(acc, "enabled", False)
                               and bool(getattr(acc, "access_token", ""))),
            classify=classify_keepalive,
            action=lambda acc: _do_keepalive(acc, source),
            interval=0.5)

    return [
        # realm：任务适用的出口范围（注册表裁决，前端按当前出口过滤展示）
        ("checkin", "自动签到", checkin, {"enabled": True, "hours": [9, 21], "realm": "cn"}),
        ("travel", "猫猫旅行", travel_task, {"enabled": True, "hours": [9, 21], "realm": "cn"}),
        ("activity", "活跃上报", activity,
         {"enabled": True, "hours": [10], "count": 1, "realm": "cn"}),
        ("nightcat", "夜猫任务", nightcat_task, {"enabled": True, "hours": [1], "realm": "cn"}),
        ("streak", "连登管家", streak_task, {"enabled": True, "hours": [21], "realm": "cn"}),
        ("school", "开学季任务", school_task, {"enabled": True, "hours": [12], "realm": "cn"}),
        ("dailychat", "国际版每日活跃", dailychat,
         {"enabled": True, "hours": [9, 21], "realm": "intl", "startup": True}),
        ("keepalive", "令牌保活", keepalive, {"enabled": True, "hours": [22]}),
    ]


def _do_checkin(account, source):
    res = account.checkin(trigger="scheduler" if source == "auto" else "manual")
    # 余额补拉已在 account.checkin 内统一完成，这里只做任务流水状态归并
    code = res.get("code")
    state = res.get("state")
    if res.get("ok") and res.get("already"):
        return {"status": "already", "code": code, "message": "今日已签到（上游幂等）"}
    if res.get("ok"):
        return {"status": "ok", "code": code, "message": "签到成功"}
    if state == "pending":
        # 「请求处理中，请勿重复操作」：这轮没签成，但账号没坏。归为跳过，
        # 让 9 点/21 点两轮继续尝试（不写 last_checkin，见 checkin_state）。
        return {"status": "skip", "code": code,
                "message": "签到未完成: %s" % (res.get("msg") or "上游处理中")}
    return {"status": "error", "code": code,
            "message": "签到失败: %s" % (res.get("error")
                                        or accounts_mod.explain_code(code, res.get("msg") or "未知原因"))}


#: 批次余量：单账号预算之外再给等待/收尾留一点时间。
DAILY_CHAT_BATCH_SLACK = 60
#: 被放弃的工作线程上限：它们通常几十秒内自己结束，病态情况下也不能无限堆。
DAILY_CHAT_ABANDONED_MAX = 8
_DAILY_CHAT_ABANDONED = []
_DAILY_CHAT_ABANDONED_LOCK = threading.Lock()


def _prune_daily_chat_workers():
    """去掉已经结束的「被放弃线程」，返回还活着的数量。"""
    with _DAILY_CHAT_ABANDONED_LOCK:
        _DAILY_CHAT_ABANDONED[:] = [t for t in _DAILY_CHAT_ABANDONED
                                     if t.is_alive()]
        return len(_DAILY_CHAT_ABANDONED)


def _do_dailychat(ctx, account, source, wait=None):
    """跑一个账号的每日活跃；卡在网络上时按预算放弃并代收会话。

    预算只在代码回到 Python 时才起作用，DNS 卡住或上游一直滴数据会让它失效。
    所以真正的等待跑在单独线程里，到点就不再等；先由本线程替它收尾网页会话，
    再把线程记入有上限的放弃列表。
    """
    alive = _prune_daily_chat_workers()
    if alive >= DAILY_CHAT_ABANDONED_MAX:
        uid8 = account.uid[:8] if account.uid else "?"
        log = getattr(ctx, "log", None)
        if callable(log):
            log("账号 [%s] 本轮跳过：还有 %d 条上几轮的工作线程没退出"
                % (uid8, alive))
        return {"status": "skip",
                "message": "上几轮的工作线程仍未退出，留到下一个时段"}

    budget = account.daily_chat_budget()
    if wait is None:
        wait = (budget + DAILY_CHAT_BATCH_SLACK) if budget > 0 else 0
    outcome = {}
    done = threading.Event()

    def work():
        try:
            outcome["res"] = account.daily_chat(
                trigger="scheduler" if source in ("auto", "startup") else "manual")
        except Exception as exc:          # noqa: BLE001 - 交给下面统一处理
            outcome["exc"] = exc
        finally:
            done.set()

    worker = threading.Thread(
        target=work, name="dailychat-%s" % (account.uid[:8] or "?"), daemon=True)
    worker.start()
    finished = done.wait(wait) if wait else done.wait()
    if not finished:
        reclaimed = 0
        try:
            reclaimed = account.web_conversation_reclaim(0)
        except Exception:
            pass
        uid8 = account.uid[:8] if account.uid else "?"
        log = getattr(ctx, "log", None)
        if callable(log):
            log("账号 [%s] 超过 %ds 仍未返回（线程卡在网络上），已代为收尾 %d 条网页会话"
                % (uid8, int(wait), reclaimed))
        with _DAILY_CHAT_ABANDONED_LOCK:
            _DAILY_CHAT_ABANDONED.append(worker)
        return {"status": "error", "phase": "hang",
                "message": "执行超过 %ds 仍未返回（线程卡在网络上），已代为收尾 %d 条网页会话"
                           % (int(wait), reclaimed)}
    exc = outcome.get("exc")
    if exc is not None:
        return {"status": "error", "message": "每日活跃对话异常: %s" % exc}
    res = outcome.get("res") or {}
    if res.get("ok"):
        try:
            account.fetch_credits()
        except Exception:
            pass
        return {"status": "ok", "message": res.get("msg") or "每日活跃打卡成功"}
    return {"status": "error",
            "message": "每日活跃打卡失败: %s" % (res.get("error")
                                              or res.get("msg") or "未知原因")}


#: 保活提前量必须大于巡检间隔：巡检默认每天 22:00 一次（24 小时），
#: 提前量若只有 2 小时，约 92% 的到期时刻要等过期之后才被发现，期间该号的
#: 上游请求全是 401。默认 48 小时可用 WB_KEEPALIVE_LEAD_HOURS 覆盖
#: （对齐上游 v1.7.30 #600）。
KEEPALIVE_LEAD_DEFAULT_HOURS = 48.0
KEEPALIVE_LEAD_MIN_HOURS = 1.0
KEEPALIVE_LEAD_MAX_HOURS = 24.0 * 30


def keepalive_lead_seconds():
    """保活提前量（秒）。非法或越界的 WB_KEEPALIVE_LEAD_HOURS 回落默认值。"""
    raw = os.environ.get("WB_KEEPALIVE_LEAD_HOURS")
    if raw is None or not str(raw).strip():
        return KEEPALIVE_LEAD_DEFAULT_HOURS * 3600
    try:
        hours = float(str(raw).strip())
    except (TypeError, ValueError):
        return KEEPALIVE_LEAD_DEFAULT_HOURS * 3600
    if not (KEEPALIVE_LEAD_MIN_HOURS <= hours <= KEEPALIVE_LEAD_MAX_HOURS):
        return KEEPALIVE_LEAD_DEFAULT_HOURS * 3600
    return hours * 3600


def classify_keepalive(account, result):
    """保活结果分类：refreshed / notneeded / error。"""
    status = (result or {}).get("status")
    if status == "refreshed":
        return "ok", result.get("message")
    if status == "notneeded":
        return "notneeded", result.get("message")
    return "error", result.get("message")


def _do_keepalive(account, source):
    # 拿不到到期时间（opaque token / 上游回执没有 expiresAt）就无法判断剩余
    # 寿命，按「该续」处理——这正是保活存在的意义。旧逻辑把它当作「有效期
    # 充足」，这类账号因此永远不被续期（对齐上游 v1.7.30 #600）。
    exp = getattr(account, "expires_at", 0) or 0
    if exp and exp - time.time() >= keepalive_lead_seconds():
        return {"status": "notneeded", "message": "有效期充足，无需刷新"}
    if not getattr(account, "refresh_token", ""):
        # 没有换发凭据就没有「续」这回事：refresh() 会把账号标成凭证失效并
        # 踢出可用池，保活不能造成这种破坏。这类号由请求路径按需换发。
        return {"status": "notneeded", "message": "无换发凭据，交由请求路径处理"}
    if account.refresh():
        return {"status": "refreshed",
                "message": "保活刷新成功，有效期至 %s" % time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(account.expires_at))}
    # 保活失败不罚号：一次续期失败不等于凭证坏了（上游只记日志，v1.7.30 #600）。
    # 这里若施加冷却，会把整池可用账号一起打冷——到期时间未知的号每轮巡检都会
    # 走到这条路径，惩罚会连坐整个出口。真正的失败由请求路径按需判定。
    return {"status": "error",
            "message": "保活刷新失败：%s" % (getattr(account, "last_error", "")
                                          or "未知原因")}


# ---------------------------------------------------------------- 账号治理
def account_views(ctx, realm=None):
    pool = ctx.pool
    if not pool:
        return []
    return pool.list_public(realm=realm)


# ---------------------------------------------------------------- 适配器
class WorkBuddyAdapter(registry.ChannelAdapter):
    id = "workbuddy"
    label = "WorkBuddy"
    realms = ("intl", "cn")
    capabilities = frozenset({
        registry.CAP_CHAT, registry.CAP_RESPONSES, registry.CAP_MODELS,
        registry.CAP_ACCOUNTS, registry.CAP_CHECKIN, registry.CAP_DAILY_CHAT,
        registry.CAP_TASKS, registry.CAP_SCHEDULER, registry.CAP_PROXY_SLOT,
    })

    def register(self, ctx):
        for realm, cfg in realm_configs().items():
            accounts_mod.register_realm_config(realm, cfg)
        from intel import catalog
        catalog.set_live_provider(lambda realm: live_models(ctx, realm))
        catalog.set_force_provider(lambda realm: live_models(ctx, realm, force=True))
        catalog.set_dirs(accounts_dir=ctx.accounts_dir, probes_dir=ctx.accounts_dir)
        catalog.start_catalog_daily(log=getattr(ctx, "log", None))

    def account_views(self, realm=None, ctx=None):
        return account_views(ctx, realm=realm)

    def scheduler_tasks(self, ctx):
        return scheduler_tasks(ctx)

    def open_stream(self, ctx, payload, session_key=None, realm=None):
        return open_stream(ctx, payload, session_key=session_key, realm=realm)

    def live_models(self, realm):
        return []

    def panel_meta(self, ctx):
        pool = getattr(ctx, "pool", None)
        return {
            "id": self.id,
            "label": self.label,
            "realms": [
                {"id": "intl", "label": REALM_LABELS["intl"],
                 "badge": "国际版", "domain": "www.workbuddy.ai",
                 "accounts": pool.count_ready(realm="intl") if pool else 0,
                 "desktop_import": True,
                 "capabilities": sorted(self.capabilities)},
                {"id": "cn", "label": REALM_LABELS["cn"],
                 "badge": "国内版", "domain": "copilot.tencent.com",
                 "accounts": pool.count_ready(realm="cn") if pool else 0,
                 "desktop_import": True,
                 "capabilities": sorted(self.capabilities)},
            ],
            "capabilities": sorted(self.capabilities),
            "frontend": "workbuddy",
            "enabled": True,
        }


def install(ctx):
    """注册本渠道（入口调用；新增渠道照此一行接入）。"""
    registry.register(WorkBuddyAdapter(), ctx)
