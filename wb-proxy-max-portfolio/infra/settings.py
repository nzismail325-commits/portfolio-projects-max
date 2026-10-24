"""Runtime settings for the gateway: panel password and API key override.

Everything lives in `accounts/settings.json` so a change made from the web
panel survives a restart without editing the launcher .bat files. The panel
password is never stored in clear text - only a PBKDF2-SHA256 digest.

Only the Python standard library is required.
"""

import copy
import fnmatch
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

from core import fsutil

DEFAULT_PANEL_PASSWORD = "admin"
PBKDF2_ROUNDS = 120_000
SESSION_TTL = 7 * 24 * 3600

_lock = threading.RLock()

#: settings.json 的进程内缓存：path -> ((mtime_ns, size), 解析结果)。
#: load 在热路径上（每个对话请求、每个面板请求都要读设置），按文件指纹判定
#: 是否重读盘；命中时返回深拷贝，调用方改动不会污染缓存。save 走原子写会
#: 更新 mtime，缓存随之自然失效，无需显式挂钩。
_load_cache = {}


def settings_path(accounts_dir):
    return os.path.join(accounts_dir, "settings.json")


def _digest(password, salt_hex, rounds=PBKDF2_ROUNDS):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), rounds
    ).hex()


def load(accounts_dir):
    """Return the persisted settings, or an empty dict on a fresh install."""
    path = settings_path(accounts_dir)
    try:
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        _load_cache.pop(path, None)
        return {}
    cached = _load_cache.get(path)
    if cached and cached[0] == stamp:
        return copy.deepcopy(cached[1])
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _load_cache[path] = (stamp, copy.deepcopy(data))
            return data
    except Exception:
        pass
    return {}


def save(accounts_dir, data):
    """Atomic write so a crash cannot leave a half-written settings file."""
    with _lock:
        result = fsutil.atomic_write_json(settings_path(accounts_dir), data)
        # 原子替换可能落在同一个 mtime 刻度、且文件大小不变（例如 2→3），
        # 只靠 (mtime_ns, size) 指纹会继续命中旧缓存。保存后直接失效，
        # 下一次 load 重新读盘。
        _load_cache.pop(settings_path(accounts_dir), None)
        return result


def _mutate(accounts_dir, fn):
    """设置变更的唯一入口：锁内 load → fn(data) 原地改 → save。"""
    with _lock:
        data = load(accounts_dir)
        fn(data)
        save(accounts_dir, data)


def panel_password_is_default(accounts_dir):
    data = load(accounts_dir)
    if not data.get("panel_password_hash"):
        return True
    return data.get("panel_password_default") is True


def verify_panel_password(accounts_dir, password):
    """True when `password` opens the web panel."""
    password = password or ""
    data = load(accounts_dir)
    stored = data.get("panel_password_hash")
    if not stored:
        return password == DEFAULT_PANEL_PASSWORD
    if data.get("panel_password_default") is True:
        return password == DEFAULT_PANEL_PASSWORD
    salt = data.get("panel_password_salt")
    if not salt:
        return False
    rounds = int(data.get("panel_password_rounds") or PBKDF2_ROUNDS)
    try:
        given = _digest(password, salt, rounds)
    except Exception:
        return False
    return hmac.compare_digest(given, stored)


def set_panel_password(accounts_dir, password):
    if len(str(password or "")) < 4:
        raise ValueError("新密码至少 4 位")

    def _apply(data):
        if password == DEFAULT_PANEL_PASSWORD:
            data.pop("panel_password_salt", None)
            data.pop("panel_password_rounds", None)
            data["panel_password_hash"] = ""
            data["panel_password_default"] = True
        else:
            salt = secrets.token_hex(16)
            data["panel_password_salt"] = salt
            data["panel_password_rounds"] = PBKDF2_ROUNDS
            data["panel_password_hash"] = _digest(password, salt)
            data["panel_password_default"] = False

    _mutate(accounts_dir, _apply)


def api_key_override(accounts_dir):
    """Return (key, is_set). `is_set` means the panel manages the key."""
    data = load(accounts_dir)
    if not data.get("api_key_set"):
        return None, False
    return str(data.get("api_key") or ""), True


def set_api_key(accounts_dir, key):
    _mutate(accounts_dir,
            lambda data: data.update({"api_key": key or "", "api_key_set": True}))


# --------------------------------------------------------------- API keys
# Each key can be bound to one upstream realm, so several clients can hit
# different exits at the same time instead of sharing the global switch.
# workbuddy intl/cn 之外，免登上游（oc 等）由 wb_upstreams 注册表动态提供，
# 这里不再手写第三份白名单——读取注册表即可保持同步。

def _all_realms():
    """出口白名单由渠道注册表决定（settings 不硬编码渠道）。"""
    try:
        from integrations import registry
        return tuple(registry.all_realms())
    except Exception:
        return ("", "intl", "cn")


def _clean_model_patterns(value):
    """把一个 Key 的模型白名单归一成小写模式列表（对齐上游 v1.6.7）。

    面板提交列表；手改 settings.json 常见逗号分隔串，两种形态都收。
    fnmatch 通配让精确名（gpt-6-astra）与通配（deepseek*）行为一致。
    空结果 = 「无限制」，没动过该字段的 Key 读回空，升级后行为不变。
    """
    if isinstance(value, str):
        raw = re.split(r"[,;\n；；]", value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return []
    out = []
    for item in raw:
        pattern = str(item or "").strip().lower()
        if pattern and pattern not in out:
            out.append(pattern)
    return out


def key_allows_model(entry, model):
    """Key 无模型限制、或模型命中白名单时为真（对齐上游 v1.6.7）。

    空白名单不拦人；受限 Key 连模型名都不带时拒绝——转发了也只会
    白白花掉一次尝试。
    """
    patterns = _clean_model_patterns((entry or {}).get("models"))
    if not patterns:
        return True
    name = str(model or "").strip().lower()
    if not name:
        return False
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def _clean_key_entry(entry):
    """Normalize one stored key entry; returns None when unusable."""
    if not isinstance(entry, dict):
        return None
    key = str(entry.get("key") or "").strip()
    if not key:
        return None
    realm = str(entry.get("realm") or "").strip().lower()
    if realm not in ("",) + tuple(_all_realms()):
        realm = ""
    return {
        "id": str(entry.get("id") or secrets.token_hex(6)),
        "name": str(entry.get("name") or "").strip() or "未命名",
        "key": key,
        "realm": realm,
        "models": _clean_model_patterns(entry.get("models")),
        "enabled": entry.get("enabled", True) is not False,
    }


def api_keys(accounts_dir):
    """Every configured key, newest shape first.

    A settings file written by an older build only has the single
    `api_key`/`api_key_set` pair; that is surfaced as one unbound entry so
    upgrades keep working without a migration step.
    """
    data = load(accounts_dir)
    stored = data.get("api_keys")
    if isinstance(stored, list):
        out = []
        seen = set()
        for raw in stored:
            entry = _clean_key_entry(raw)
            if entry and entry["key"] not in seen:
                seen.add(entry["key"])
                out.append(entry)
        return out

    if data.get("api_key_set"):
        legacy = str(data.get("api_key") or "").strip()
        if legacy:
            return [{
                "id": "legacy",
                "name": "默认（跟随面板切换）",
                "key": legacy,
                "realm": "",
                "enabled": True,
            }]
    return []


def set_api_keys(accounts_dir, keys):
    """Replace the whole key list. Returns the stored list."""
    cleaned = []
    seen = set()
    for raw in keys or []:
        entry = _clean_key_entry(raw)
        if entry and entry["key"] not in seen:
            seen.add(entry["key"])
            cleaned.append(entry)

    def _apply(data):
        data["api_keys"] = cleaned
        # The single-key fields are now derived; drop them so there is one
        # source of truth and the list survives a restart.
        data.pop("api_key", None)
        data.pop("api_key_set", None)

    _mutate(accounts_dir, _apply)
    return cleaned


def match_api_key(accounts_dir, supplied, extra_keys=()):
    """Find which configured key a request presented, if any.

    Returns a copy of the entry (with a `source` field) so the caller can read
    the bound realm, or None when nothing matches.
    """
    supplied = (supplied or "").strip()
    if not supplied:
        return None
    for entry in api_keys(accounts_dir):
        if entry["enabled"] and hmac.compare_digest(supplied, entry["key"]):
            out = dict(entry)
            out["source"] = "panel"
            return out
    for candidate in extra_keys:
        candidate = (candidate or "").strip()
        if candidate and hmac.compare_digest(supplied, candidate):
            return {
                "id": "launcher",
                "name": "启动参数",
                "key": candidate,
                "realm": "",
                "enabled": True,
                "source": "launcher",
            }
    return None


def auth_disabled(accounts_dir):
    """True when the operator switched API-key checking off entirely."""
    return load(accounts_dir).get("auth_disabled") is True


def set_auth_disabled(accounts_dir, disabled):
    _mutate(accounts_dir, lambda data: data.update({"auth_disabled": bool(disabled)}))


# --------------------------------------------------------------- automation
# 自动化任务配置：七类任务各自独立开关与整点数组（对齐 mana 的排程形态）。
# 自用部署，宽松容错：非法值一律回落默认，不报错不拦截，配置永远可用。

AUTOMATION_DEFAULTS = {
    "enabled": True,
    "checkin": {"enabled": True, "hours": [9, 21]},
    "travel": {"enabled": True, "hours": [9, 21]},
    "activity": {"enabled": True, "hours": [10], "count": 1},
    "nightcat": {"enabled": True, "hours": [1]},
    "school": {"enabled": True, "hours": [12]},
    # 国际版每日活跃打卡：官方只认网页端会话，桌面对话不计入；闸门是
    # 「今天是否已打卡」，9/21 两个整点里第二次会被幂等跳过
    "dailychat": {"enabled": True, "hours": [9, 21]},
    "keepalive": {"enabled": True, "hours": [22]},
    # 连登管家：补签 / 礼包 / 档位兑换 / 抽奖闭环，与签到同时窗（日级幂等）
    "streak": {"enabled": True, "hours": [21]},
}
#: 渠道任务（如 trae_checkin）不在此硬编码，由 integrations 注册表在运行时追加
AUTOMATION_TASKS = ("checkin", "travel", "activity", "nightcat", "streak",
                    "school", "dailychat", "keepalive")


def _clean_hours(raw, fallback):
    """整点数组清洗：只收 0-23 的整数，清完为空退回默认。"""
    hours = []
    if isinstance(raw, list):
        for h in raw:
            if isinstance(h, bool):
                continue
            try:
                v = int(h)
            except (TypeError, ValueError):
                continue
            if 0 <= v <= 23 and v not in hours:
                hours.append(v)
    return sorted(hours) or list(fallback)


def normalize_automation(raw, prev=None):
    """归一化自动化配置；缺省 / 非法字段回落默认值。

    `prev` 是文件里的现值：提交里整个缺失的任务键沿用现值而不是默认值——
    前端按分区提交（总开关、单个任务、任务时间）时只带自己那几项，回落
    默认值会把用户改过的开关与时间悄悄改回去。

    内置任务（AUTOMATION_TASKS）的默认值在本模块；渠道任务（如
    trae_checkin / qoder_checkin）由 integrations 注册表在运行时声明，
    这里不硬编码 id，只做形态清洗并保留提交/现值，默认值由
    AppContext.automation_config 合并适配器 defaults 补齐。
    """
    defaults = AUTOMATION_DEFAULTS
    raw = raw if isinstance(raw, dict) else {}
    prev = prev if isinstance(prev, dict) else {}
    # 总开关只在显式提交时改变：任务页单独开关某任务不该把暂停中的排程重新打开
    out = {"enabled": raw.get("enabled", prev.get("enabled", True)) is not False}
    for task in AUTOMATION_TASKS:
        d = defaults[task]
        base = prev.get(task) if isinstance(prev.get(task), dict) else {}
        source = raw.get(task) if isinstance(raw.get(task), dict) else {}
        entry = {"enabled": d["enabled"], "hours": list(d["hours"])}
        if base:
            entry["enabled"] = base.get("enabled", d["enabled"]) is not False
            entry["hours"] = _clean_hours(base.get("hours"), d["hours"])
        if source:
            entry["enabled"] = source.get("enabled", entry["enabled"]) is not False
            entry["hours"] = _clean_hours(source.get("hours", entry["hours"]),
                                          d["hours"])
        if task == "activity":
            count = d["count"]
            for candidate in (base, source):
                try:
                    count = int(candidate.get("count", count))
                except (TypeError, ValueError):
                    pass
            entry["count"] = min(50, max(1, count))
        out[task] = entry
    for task in list(dict.fromkeys(list(prev) + list(raw))):
        if (not isinstance(task, str) or task == "enabled"
                or task in AUTOMATION_TASKS):
            continue
        base = prev.get(task) if isinstance(prev.get(task), dict) else {}
        source = raw.get(task) if isinstance(raw.get(task), dict) else {}
        if not base and not source:
            continue
        merged = dict(base)
        merged.update(source)
        entry = {}
        if "enabled" in merged:
            entry["enabled"] = merged.get("enabled") is not False
        if isinstance(merged.get("hours"), list):
            hours = _clean_hours(merged.get("hours"), [])
            if hours:
                entry["hours"] = hours
        if entry:
            out[task] = entry
    return out


def automation_config(accounts_dir):
    """当前生效的自动化配置（文件里的值 + 缺省回落）。"""
    data = load(accounts_dir)
    return normalize_automation(data.get("automation"))


def set_automation(accounts_dir, cfg):
    """保存自动化配置（先归一化），返回保存后的生效值。"""
    normalized = {}

    def _apply(data):
        nonlocal normalized
        normalized = normalize_automation(cfg if isinstance(cfg, dict) else {},
                                          prev=data.get("automation"))
        data["automation"] = normalized

    _mutate(accounts_dir, _apply)
    return normalized


def daily_chat_web(accounts_dir):
    """国际版每日打卡是否附带一次网页通道会话。

    默认开：桌面身分的轻量对话不计入官方「每日活跃」，只有网页端
    （云 agent）跑完的会话才算（上游 issue #75/#59/#90 实测）。没动过
    这个开关的安装保持网页通道——那才是挣到积分的行为；关掉它只是为了
    回到「只发一条桌面对话」的老形态。
    """
    value = load(accounts_dir).get("daily_chat_web")
    return True if value is None else value is True


def set_daily_chat_web(accounts_dir, enabled):
    """持久化网页通道开关。返回存储的布尔值。"""
    enabled = bool(enabled)
    _mutate(accounts_dir, lambda data: data.update({"daily_chat_web": enabled}))
    return enabled


#: 网页活跃的有序候选模型：第一个是首选，其余按顺序回退；空 = 自动。
DAILY_CHAT_MODELS_MAX = 8
DAILY_CHAT_MODEL_MAX_LEN = 64
#: 单账号跑完网页活跃的总预算（秒）；0 = 不限制。
DAILY_CHAT_BUDGET_DEFAULT = 600
DAILY_CHAT_BUDGET_MAX = 7200
#: 网页活跃并发上限。
DAILY_CHAT_WEB_CONCURRENCY_DEFAULT = 1
DAILY_CHAT_WEB_CONCURRENCY_MAX = 10
#: 自定义随机提示词条数与单条长度上限。
DAILY_CHAT_WEB_PROMPTS_MAX = 200
DAILY_CHAT_WEB_PROMPT_MAX_LEN = 200


def _clean_daily_chat_models(value):
    """归一候选模型：列表或逗号/换行串，去空去重、保序、限条数与长度。"""
    if isinstance(value, str):
        raw = re.split(r"[,\r\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return []
    out = []
    for item in raw:
        model = str(item or "").strip()
        if not model or len(model) > DAILY_CHAT_MODEL_MAX_LEN or model in out:
            continue
        out.append(model)
        if len(out) >= DAILY_CHAT_MODELS_MAX:
            break
    return out


def daily_chat_models(accounts_dir):
    """网页活跃的有序候选模型；空列表表示自动模式。"""
    return _clean_daily_chat_models(
        load(accounts_dir).get("daily_chat_models"))


def set_daily_chat_models(accounts_dir, models):
    """持久化有序候选模型，返回归一后的列表；空值清掉该键。"""
    cleaned = _clean_daily_chat_models(models)
    def _apply(data):
        if cleaned:
            data["daily_chat_models"] = cleaned
        else:
            data.pop("daily_chat_models", None)
    _mutate(accounts_dir, _apply)
    return cleaned


def daily_chat_budget(accounts_dir, default=None):
    """单账号网页活跃总预算（秒）；0 = 不限制。"""
    fallback = (DAILY_CHAT_BUDGET_DEFAULT if default is None
                else int(default))
    value = load(accounts_dir).get("daily_chat_budget")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(DAILY_CHAT_BUDGET_MAX, max(0, number))


def set_daily_chat_budget(accounts_dir, seconds):
    """持久化单账号预算，返回落盘值。"""
    try:
        number = int(seconds)
    except (TypeError, ValueError):
        number = DAILY_CHAT_BUDGET_DEFAULT
    number = min(DAILY_CHAT_BUDGET_MAX, max(0, number))
    _mutate(accounts_dir,
            lambda data: data.update({"daily_chat_budget": number}))
    return number


def daily_chat_web_concurrency(accounts_dir):
    """网页活跃并发数，默认 1（顺序执行）。"""
    value = load(accounts_dir).get("daily_chat_web_concurrency")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return DAILY_CHAT_WEB_CONCURRENCY_DEFAULT
    return min(DAILY_CHAT_WEB_CONCURRENCY_MAX, max(1, number))


def set_daily_chat_web_concurrency(accounts_dir, concurrency):
    """持久化并发数，返回落盘值。"""
    try:
        number = int(concurrency)
    except (TypeError, ValueError):
        number = DAILY_CHAT_WEB_CONCURRENCY_DEFAULT
    number = min(DAILY_CHAT_WEB_CONCURRENCY_MAX, max(1, number))
    _mutate(accounts_dir,
            lambda data: data.update({"daily_chat_web_concurrency": number}))
    return number


#: 建会话 / 取沙箱失败后的退避基数（秒）；0 = 不退避（旧行为）。
DAILY_CHAT_WEB_RETRY_BACKOFF_DEFAULT = 5
DAILY_CHAT_WEB_RETRY_BACKOFF_MAX = 30


def daily_chat_web_retry_backoff(accounts_dir, default=None):
    """网页活跃在「还没跑到 turn」阶段失败后的退避基数（秒）。

    留空时用调用方给的 default（账号侧传内置默认，它吃
    WB_WEB_RETRY_BACKOFF 环境变量）；0 = 不退避。坏数据回退到 default，
    而不是回落到 0——没有这条设置的老安装应当保持内置默认的退避。
    """
    fallback = (DAILY_CHAT_WEB_RETRY_BACKOFF_DEFAULT if default is None
                else int(default))
    value = load(accounts_dir).get("daily_chat_web_retry_backoff")
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(DAILY_CHAT_WEB_RETRY_BACKOFF_MAX, max(0, number))


def set_daily_chat_web_retry_backoff(accounts_dir, backoff):
    """持久化退避基数，返回落盘值。"""
    try:
        number = int(backoff)
    except (TypeError, ValueError):
        number = DAILY_CHAT_WEB_RETRY_BACKOFF_DEFAULT
    number = min(DAILY_CHAT_WEB_RETRY_BACKOFF_MAX, max(0, number))
    _mutate(accounts_dir,
            lambda data: data.update({"daily_chat_web_retry_backoff": number}))
    return number


def daily_chat_web_random_prompt(accounts_dir):
    """网页活跃是否从提示词池随机抽一条（默认关）。"""
    return load(accounts_dir).get("daily_chat_web_random_prompt") is True


def set_daily_chat_web_random_prompt(accounts_dir, enabled):
    enabled = bool(enabled)
    _mutate(accounts_dir,
            lambda data: data.update({"daily_chat_web_random_prompt": enabled}))
    return enabled


def _clean_prompts(value):
    """归一自定义提示词：列表或换行/分号串，去空、去重、限长、限条数。"""
    if isinstance(value, str):
        raw = re.split(r"[\r\n;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        return []
    out = []
    for item in raw:
        text = str(item or "").strip()
        if not text:
            continue
        text = text[:DAILY_CHAT_WEB_PROMPT_MAX_LEN]
        if text not in out:
            out.append(text)
        if len(out) >= DAILY_CHAT_WEB_PROMPTS_MAX:
            break
    return out


def daily_chat_web_prompts(accounts_dir):
    """自定义随机提示词列表（不含内置池）。"""
    return _clean_prompts(load(accounts_dir).get("daily_chat_web_prompts"))


def set_daily_chat_web_prompts(accounts_dir, prompts):
    """持久化自定义提示词，返回落盘列表。"""
    cleaned = _clean_prompts(prompts)
    _mutate(accounts_dir,
            lambda data: data.update({"daily_chat_web_prompts": cleaned}))
    return cleaned


def models_only_available(accounts_dir):
    """`/v1/models` 是否只宣告池里至少有一个账号能服务的模型（默认关）。"""
    return load(accounts_dir).get("models_only_available") is True


def set_models_only_available(accounts_dir, enabled):
    enabled = bool(enabled)
    _mutate(accounts_dir,
            lambda data: data.update({"models_only_available": enabled}))
    return enabled


# --------------------------------------------------------------- 派发（选号）

#: 更稳的会话粘滞键（默认关）：客户端一个会话 id 都不带时，按对话前缀派生粘滞键，
#: 让同一段对话的每一轮落回同一个账号——上游的 prompt cache 是账号级的，换号就
#: 整段漏缓存。关闭时只认客户端显式给的 id，派发路径与改动前一字不差。
AFFINITY_STABLE_KEY_ENABLED_KEY = "affinity_stable_key_enabled"


def affinity_stable_key_enabled(accounts_dir):
    """客户端没带会话 id 时，是否按对话前缀派生粘滞键。"""
    return load(accounts_dir).get(AFFINITY_STABLE_KEY_ENABLED_KEY) is True


def set_affinity_stable_key_enabled(accounts_dir, enabled):
    """持久化粘滞键开关，返回落盘值。

    严格收布尔：``bool("false")`` 是真值，一个从调用方混进来的字符串会把开关
    悄悄打开，所以非布尔一律拒绝（面板给的就是 JSON 布尔）。
    """
    if not isinstance(enabled, bool):
        raise ValueError("affinity_stable_key_enabled must be true or false")
    _mutate(accounts_dir,
            lambda data: data.update({AFFINITY_STABLE_KEY_ENABLED_KEY: enabled}))
    return enabled


#: 账号级并发上限：单个上游账号同时接几个 chat 请求。0 = 不限（默认）。
ACCOUNT_MAX_CONCURRENT_KEY = "account_max_concurrent"
ACCOUNT_MAX_CONCURRENT_MAX = 10


def account_max_concurrent(accounts_dir):
    """单账号同时在途的 chat 请求上限；0 = 不限（默认）。

    坏数据（字符串、布尔、负数、越界）一律回退 0：手编 settings.json 写坏一个
    值，不该把一个本来能用的安装悄悄限流。
    """
    value = load(accounts_dir).get(ACCOUNT_MAX_CONCURRENT_KEY)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    if value < 0 or value > ACCOUNT_MAX_CONCURRENT_MAX:
        return 0
    return value


def set_account_max_concurrent(accounts_dir, value):
    """持久化账号级并发上限，返回落盘值。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("account_max_concurrent must be a whole number")
    if value < 0:
        raise ValueError("account_max_concurrent cannot be less than 0")
    if value > ACCOUNT_MAX_CONCURRENT_MAX:
        raise ValueError("account_max_concurrent cannot be more than %d"
                         % ACCOUNT_MAX_CONCURRENT_MAX)
    _mutate(accounts_dir,
            lambda data: data.update({ACCOUNT_MAX_CONCURRENT_KEY: value}))
    return value


# --------------------------------------------------------------- 身分轮换

def auto_switch_product(accounts_dir):
    """上游 429 是否可以轮换该账号的出站身分（面板开关，默认关）。

    默认关闭：轮换会消耗这一轮的重试额度，还会把账号留在一条没人选过的
    通道上，网关不替人做这个决定；没动过这个开关的安装行为与以前完全一致。
    """
    return load(accounts_dir).get("auto_switch_product") is True


def set_auto_switch_product(accounts_dir, enabled):
    """持久化 429 自动切换身分开关。返回存储的布尔值。"""
    enabled = bool(enabled)
    _mutate(accounts_dir,
            lambda data: data.update({"auto_switch_product": enabled}))
    return enabled


# ------------------------------------------------------------ 身份与模型目录

#: X-Private-Data 是官方客户端「数据是否可参与模型优化」的声明。auto 保持
#: 各身份的默认值；true/false 对所有身份统一覆盖（主上游 #516）。
IDENTITY_KEY = "identity"
IDENTITY_PRIVATE_DATA_VALUES = ("auto", "true", "false")


def identity_private_data(accounts_dir):
    raw = load(accounts_dir).get(IDENTITY_KEY)
    if not isinstance(raw, dict):
        return "auto"
    value = str(raw.get("private_data") or "auto").strip().lower()
    return value if value in IDENTITY_PRIVATE_DATA_VALUES else "auto"


def identity_config(accounts_dir):
    return {"private_data": identity_private_data(accounts_dir)}


def set_identity_private_data(accounts_dir, value):
    value = str(value or "auto").strip().lower()
    if value not in IDENTITY_PRIVATE_DATA_VALUES:
        raise ValueError("identity.private_data must be auto, true or false")

    def _apply(data):
        identity = data.get(IDENTITY_KEY)
        if not isinstance(identity, dict):
            identity = {}
        identity["private_data"] = value
        data[IDENTITY_KEY] = identity

    _mutate(accounts_dir, _apply)
    return value


def filter_models_by_key(accounts_dir):
    """`/v1/models` 是否只宣告当前 Key 可用的模型（默认关）。

    关闭时保持历史行为（全量目录）；打开后，配了模型白名单的 Key 不会再
    看到请求时必被本地 400 拒掉的模型。
    """
    return load(accounts_dir).get("filter_models_by_key") is True


def set_filter_models_by_key(accounts_dir, enabled):
    enabled = bool(enabled)
    _mutate(accounts_dir,
            lambda data: data.update({"filter_models_by_key": enabled}))
    return enabled


def upstream_timeouts(accounts_dir):
    """聊天上游的两段读超时 (header, idle) 秒数（对齐上游 v1.6.15）。

    header 覆盖 connect/TLS/首字节；idle 限制流式阶段每次读的间隔——
    有数据就续命，静默流按 idle 超时失败。没有总时长上限，与上游语义
    一致。读失败回落内置默认（120s / 300s）。
    """
    data = load(accounts_dir)
    header, idle = 120.0, 300.0
    for key, default in (("header_timeout_seconds", header),
                         ("idle_timeout_seconds", idle)):
        value = data.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number >= 1.0:
            if key == "header_timeout_seconds":
                header = number
            else:
                idle = number
    return header, idle


def set_upstream_timeouts(accounts_dir, header=None, idle=None):
    """持久化两段读超时；None 表示该项不动。返回 (header, idle)。"""

    def _apply(data):
        if header is not None:
            data["header_timeout_seconds"] = max(1.0, float(header))
        if idle is not None:
            data["idle_timeout_seconds"] = max(1.0, float(idle))

    _mutate(accounts_dir, _apply)
    return upstream_timeouts(accounts_dir)


def upstream_connect_timeout(accounts_dir):
    """出站连接（TCP+TLS 握手）的独立超时秒数（默认 10s，下限 1s）。

    与读超时（header 档）分离：死出口、被墙的代理要在秒级失败并换下一把
    账号，而不是吃满 header 档的 120s 把客户端拖死。
    """
    value = load(accounts_dir).get("connect_timeout_seconds")
    if value is None:
        return 10.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 10.0
    return number if number >= 1.0 else 10.0


def prompt_config(accounts_dir):
    """系统提示词模式设置 {"mode": ..., "file": ...}（对齐上游 v1.6.16）。

    未知模式回退 passthrough——保守默认，绝不意外改写客户端提示词。
    """
    data = load(accounts_dir)
    prompt = data.get("prompt")
    if not isinstance(prompt, dict):
        prompt = {}
    mode = str(prompt.get("mode") or "").strip().lower()
    if mode not in ("passthrough", "custom", "append"):
        mode = "passthrough"
    return {"mode": mode, "file": str(prompt.get("file") or "")}


def set_prompt_config(accounts_dir, mode=None, file=None):
    """持久化提示词模式；mode=None 表示不改模式。返回存储后的配置。"""

    def _apply(data):
        prompt = data.get("prompt")
        if not isinstance(prompt, dict):
            prompt = {}
        if mode is not None:
            clean = str(mode or "").strip().lower()
            if clean not in ("passthrough", "custom", "append"):
                clean = "passthrough"
            prompt["mode"] = clean
        if file is not None:
            prompt["file"] = str(file or "").strip()
        data["prompt"] = prompt

    _mutate(accounts_dir, _apply)
    return prompt_config(accounts_dir)

# ------------------------------------------------------------ 代理槽
# 账号的代理出口槽位：每个槽 = 一条代理 URL + 探测到的出口信息。
# 槽位按出口（realm）归属：每个出口只管理自己的槽，账号也只能绑定本出口的
# 槽——「国际版走代理、其他出口直连」这类需求靠归属隔离，不靠全局开关。
# realm 为空的槽是旧版全局槽：对所有出口可见（标「未分配」），在任一出口
# 保存后即归入该出口，不丢数据。
# 槽位 id 只增不复用——账号落盘的是 id，回收旧 id 会把老账号悄悄指到新出口。
_SLOT_ID_RE = re.compile(r"^slot-(\d+)$")


def _clean_slot_entry(raw):
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or "").strip()
    if not url:
        return None
    try:
        probed_at = int(raw.get("probed_at") or 0)
    except (TypeError, ValueError):
        probed_at = 0
    return {
        "id": str(raw.get("id") or "").strip(),
        "name": str(raw.get("name") or "").strip(),
        "realm": str(raw.get("realm") or "").strip(),
        "url": url,
        "enabled": raw.get("enabled", True) is not False,
        "ip": str(raw.get("ip") or raw.get("exit_ip") or "").strip(),
        "country": str(raw.get("country") or "").strip(),
        "country_code": str(raw.get("country_code") or "").strip().upper(),
        "ip_type": str(raw.get("ip_type") or "").strip().lower(),
        "isp": str(raw.get("isp") or "").strip(),
        "asn": str(raw.get("asn") or "").strip(),
        "probed_at": probed_at,
    }


def _next_slot_id(existing):
    highest = 0
    for entry in existing:
        match = _SLOT_ID_RE.match(str(entry.get("id") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return "slot-%d" % (highest + 1)


def proxy_slots(accounts_dir, realm=None):
    """代理槽列表。

    不给 realm：全部槽（旧行为，启动重解析与设置导出用）。
    给 realm：该出口自己的槽 + 未分配的旧版全局槽（realm 为空）——旧槽在
    任一出口保存后即被归属，不会再出现在别的出口。
    """
    data = load(accounts_dir)
    stored = data.get("proxy_slots")
    if not isinstance(stored, list):
        return []
    cleaned, seen = [], set()
    for raw in stored:
        entry = _clean_slot_entry(raw)
        if not entry:
            continue
        # 去重键是（出口, URL）：同一出口内同 URL 只保留一条；不同出口各配
        # 各的——同一条代理线（如本机 7897）可以同时给多个出口用。早先按
        # URL 全局去重是「全局一份槽位」时代的口径，会把第二个出口的同
        # URL 条目静默吞掉（保存后消失）。
        stamp = (entry["realm"], entry["url"])
        if stamp in seen:
            continue
        seen.add(stamp)
        if not entry["id"]:
            entry["id"] = _next_slot_id(cleaned)
        cleaned.append(entry)
    want = str(realm or "").strip()
    if not want:
        return cleaned
    return [entry for entry in cleaned if entry["realm"] in ("", want)]


def set_proxy_slots(accounts_dir, slots, realm=None):
    """保存代理槽；id 只增不复用。

    给 realm：只替换该出口（含未分配的旧版全局槽）的槽位，来槽统一打上
    该 realm 归属，其余出口的槽原样保留——面板按出口分卡保存，互不覆盖。
    不给 realm：整体替换（旧行为，设置页/API 全量保存用）。
    """
    cleaned = []

    def _apply(data):
        nonlocal cleaned
        stored = data.get("proxy_slots")
        stored = stored if isinstance(stored, list) else []
        try:
            seq = int(data.get("proxy_slot_seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        for entry in list(stored) + list(slots or []):
            if not isinstance(entry, dict):
                continue
            match = _SLOT_ID_RE.match(str(entry.get("id") or ""))
            if match:
                seq = max(seq, int(match.group(1)))
        seq = max(seq, len(stored))
        want = str(realm or "").strip()
        kept = []
        if want:
            for raw in stored:
                entry = _clean_slot_entry(raw)
                if entry and entry["realm"] not in ("", want):
                    kept.append(entry)
        seen = set()
        for raw in slots or []:
            entry = _clean_slot_entry(raw)
            if not entry or entry["url"] in seen:
                continue
            seen.add(entry["url"])
            if want:
                entry["realm"] = want
            if not entry["id"] or any(e["id"] == entry["id"]
                                      for e in kept + cleaned):
                seq += 1
                entry["id"] = "slot-%d" % seq
            cleaned.append(entry)
        data["proxy_slots"] = kept + cleaned
        data["proxy_slot_seq"] = seq

    _mutate(accounts_dir, _apply)
    return cleaned


def find_proxy_slot(accounts_dir, slot_id):
    slot_id = str(slot_id or "").strip()
    if not slot_id:
        return None
    for entry in proxy_slots(accounts_dir):
        if entry["id"] == slot_id:
            return entry
    return None


# ------------------------------------------------------------ 本地网络工具
LOCAL_WEB_TOOLS_KEY = "local_web_tools"


def local_web_tools(accounts_dir):
    """网关是否自己代跑 web_search / web_fetch（默认关）。

    关时客户端宣告的网路工具原样透传，由客户端自己执行；打开后网关把
    同名宣告换成自己的 function、自己执行并把结果喂回模型（上游语义）。
    """
    return load(accounts_dir).get(LOCAL_WEB_TOOLS_KEY) is True


def set_local_web_tools(accounts_dir, enabled):
    _mutate(accounts_dir,
            lambda data: data.update({LOCAL_WEB_TOOLS_KEY: bool(enabled)}))
    return bool(enabled)


# ------------------------------------------------------------ 出口退避
EGRESS_BACKOFF_KEY = "egress_backoff"


def egress_backoff_enabled(accounts_dir):
    """出口级秒级退避总开关（默认开：一次链路抖动不该熔断一批账号）。"""
    value = load(accounts_dir).get(EGRESS_BACKOFF_KEY)
    return True if value is None else value is True


def set_egress_backoff_enabled(accounts_dir, enabled):
    _mutate(accounts_dir,
            lambda data: data.update({EGRESS_BACKOFF_KEY: bool(enabled)}))
    return bool(enabled)


# ------------------------------------------------------------ 日志落库
LOG_DB_ENABLED_KEY = "log_db_enabled"
LOG_DB_MAX_ROWS_KEY = "log_db_max_rows"
LOG_DB_MAX_DAYS_KEY = "log_db_max_days"
LOG_DB_MAX_BYTES_KEY = "log_db_max_bytes"
DEFAULT_LOG_DB_MAX_DAYS = 7
MAX_LOG_DB_MAX_ROWS = 5000000
MAX_LOG_DB_MAX_DAYS = 3650
MAX_LOG_DB_MAX_BYTES = 4 * 1024 * 1024 * 1024


def log_db_enabled(accounts_dir):
    """是否把运行日志也落 usage/logs.sqlite3（默认关）。"""
    return load(accounts_dir).get(LOG_DB_ENABLED_KEY) is True


def set_log_db_enabled(accounts_dir, enabled):
    _mutate(accounts_dir,
            lambda data: data.update({LOG_DB_ENABLED_KEY: bool(enabled)}))
    return bool(enabled)


def _positive_cap(raw, fallback, hard_max):
    if isinstance(raw, bool):
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return fallback
    if value <= 0:
        return fallback
    return min(value, hard_max)


def _clearable_cap(value, hard_max):
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number <= 0:
        return None
    return min(number, hard_max)


def log_db_max_rows(accounts_dir):
    data = load(accounts_dir)
    if LOG_DB_MAX_ROWS_KEY not in data or data.get(LOG_DB_MAX_ROWS_KEY) is None:
        return None
    return _positive_cap(data.get(LOG_DB_MAX_ROWS_KEY), None, MAX_LOG_DB_MAX_ROWS)


def set_log_db_max_rows(accounts_dir, value):
    stored = _clearable_cap(value, MAX_LOG_DB_MAX_ROWS)
    _mutate(accounts_dir, lambda data: data.update({LOG_DB_MAX_ROWS_KEY: stored}))
    return stored


def log_db_max_days(accounts_dir):
    data = load(accounts_dir)
    if LOG_DB_MAX_DAYS_KEY not in data:
        return DEFAULT_LOG_DB_MAX_DAYS
    if data.get(LOG_DB_MAX_DAYS_KEY) is None:
        return None
    return _positive_cap(data.get(LOG_DB_MAX_DAYS_KEY), DEFAULT_LOG_DB_MAX_DAYS,
                         MAX_LOG_DB_MAX_DAYS)


def set_log_db_max_days(accounts_dir, value):
    stored = _clearable_cap(value, MAX_LOG_DB_MAX_DAYS)
    _mutate(accounts_dir, lambda data: data.update({LOG_DB_MAX_DAYS_KEY: stored}))
    return stored


def log_db_max_bytes(accounts_dir):
    data = load(accounts_dir)
    if LOG_DB_MAX_BYTES_KEY not in data or data.get(LOG_DB_MAX_BYTES_KEY) is None:
        return None
    return _positive_cap(data.get(LOG_DB_MAX_BYTES_KEY), None, MAX_LOG_DB_MAX_BYTES)


def set_log_db_max_bytes(accounts_dir, value):
    stored = _clearable_cap(value, MAX_LOG_DB_MAX_BYTES)
    _mutate(accounts_dir, lambda data: data.update({LOG_DB_MAX_BYTES_KEY: stored}))
    return stored


# ------------------------------------------------------------ 更新检查
UPDATE_CHECK_ENABLED_KEY = "update_check_enabled"
UPDATE_CHECK_STATE_KEY = "update_check_state"


def update_check_enabled(accounts_dir):
    """每日更新检查开关（默认关：缺键就是关，不主动访问 GitHub）。"""
    return load(accounts_dir).get(UPDATE_CHECK_ENABLED_KEY) is True


def set_update_check_enabled(accounts_dir, enabled):
    _mutate(accounts_dir,
            lambda data: data.update({UPDATE_CHECK_ENABLED_KEY: bool(enabled)}))
    return bool(enabled)


def update_check_state(accounts_dir):
    """按上游源记账：{"sources": {源id: {last_attempt, last_success, latest_version}}}。

    只留安全字段（时间与版本号）；旧版的扁平结构没有源归属，无法映射，直接丢弃。
    """
    stored = load(accounts_dir).get(UPDATE_CHECK_STATE_KEY)
    stored = stored if isinstance(stored, dict) else {}
    raw_sources = stored.get("sources")
    out = {}
    for sid, entry in (raw_sources.items() if isinstance(raw_sources, dict) else []):
        if not isinstance(entry, dict) or not isinstance(sid, str):
            continue
        item = {"last_attempt": 0.0, "last_success": 0.0, "latest_version": ""}
        for key in ("last_attempt", "last_success"):
            value = entry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
                item[key] = float(value)
        version = entry.get("latest_version")
        if isinstance(version, str):
            item["latest_version"] = version.strip()[:32]
        out[sid.strip()[:64]] = item
    return {"sources": out}


def record_update_check(accounts_dir, source_id, at=None, success=False,
                        latest_version=""):
    """记一个上游源的检查结果；没有源 id 不落盘（避免出现无归属的记录）。"""
    stamp = float(at if at is not None else time.time())
    sid = str(source_id or "").strip()[:64]
    if not sid:
        return update_check_state(accounts_dir)

    def _apply(data):
        state = data.get(UPDATE_CHECK_STATE_KEY)
        state = dict(state) if isinstance(state, dict) else {}
        sources = state.get("sources")
        sources = dict(sources) if isinstance(sources, dict) else {}
        entry = sources.get(sid)
        entry = dict(entry) if isinstance(entry, dict) else {}
        entry["last_attempt"] = stamp
        if success:
            entry["last_success"] = stamp
        version = str(latest_version or "").strip()[:32]
        if version:
            entry["latest_version"] = version
        sources[sid] = entry
        state["sources"] = sources
        data[UPDATE_CHECK_STATE_KEY] = state

    _mutate(accounts_dir, _apply)
    return update_check_state(accounts_dir)
