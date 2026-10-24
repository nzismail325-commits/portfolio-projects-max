# -*- coding: utf-8 -*-
"""auth/accounts.py —— 账号模型与池治理（自二开迁移，按重构拍板裁剪）

职责：
- Account：一个上游凭据的完整运行时状态（令牌、出站身分、冷却、熔断、积分缓存）；
- AccountPool：账号文件加载、派发（会话亲和 + 人工权重加权轮询）、登录与桌面凭据导入。

治理口径（重构 §4.4）：
- 429 软限流：账号级 600s→2h 指数阶梯；无作用域 429 只锁单模型（60s→10min）；
- 402 余额不足：硬停车到次日本地 04:00，余额刷新显示有积分即抬出（只抬停车）；
- 5xx/传输失败：熔断（3 次起，30min→6h）；未知失败另有降级窗口（5 次起，10min→2h）；
- weight：人工调度权重（>1 的账号优先接单，彼此平滑加权轮询）；
- disabledModels：人工禁用名单，与自动冷却严格分开、随凭据持久化。

明确不带入（拍板砍掉的额度控制）：每日 token 上限、每日积分上限、单模型
上限、保留积分、临期积分窗口、剩余用量优先调度。

渠道无关：本模块不认识任何具体上游端点。realm 的端点/身分配置由渠道适配器
启动时经 `register_realm_config()` 注入（依赖方向 integrations → auth）。
"""
import base64
import datetime
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from auth import atrest as _atrest
from auth import identity
from auth.fingerprint import derive_id, generate_request_id, session_id
from core import fsutil
from core import net
from core import ratelimit
from core import timeutil
from core import upstream_body
from infra import settings

# ── 账号级失败治理参数 ─────────────────────────────────────────
SOFT_RATE_BASE = 600.0          # 首次确认的账号级 429：10 分钟
SOFT_RATE_MAX = 7200.0          # ……逐次翻倍，封顶 2 小时
SOFT_RATE_UNVERIFIED_BASE = 60.0
SOFT_RATE_UNVERIFIED_MAX = 600.0
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 1800.0
BREAKER_COOLDOWN_MAX = 21600.0
DEGRADE_THRESHOLD = 5
DEGRADE_COOLDOWN = 600.0
DEGRADE_COOLDOWN_MAX = 7200.0
#: 失败连击的时间窗：超过这个间隔的失败不再算「连续」。
FAIL_WINDOW = 15 * 60.0

#: 上游账号级风控限制（HTTP 403 / code 11140）的默认冷却。与其它冷却不同，
#: 这个期限是**持久化**的（见 note_restricted）。
RESTRICTED_ACCOUNT_COOLDOWN = 7200.0

LOGIN_PENDING = 11217
LOGIN_TTL_SECONDS = 600
SESSION_DEAD_CODE = 12153
SESSION_DEAD_LIMIT = 3

#: 上游常见业务码的人话解释
CODE_HINTS = {
    0: "成功",
    10001: "今日已签到",
    11101: "上游不接受非流式请求（协议问题，非账号问题）",
    "11-128": "请求未通过上游渠道校验（缺会话头族或客户端身分不被认可）",
    12153: "会话已失效，需重新登录",
    11102: "该线路不提供此模型，换个模型或账号即可",
    11140: "请求被上游风控拒绝（request illegal）",
    14017: "国际版试用未激活，需先完成地区注册",
}

#: 签到文案判据。10001 不是「签到成功」专属码：活动补偿的「您已领取过」
#: 与内容审核都用它，上游还会在 code=0 下回「签到失败…」。原先
#: `code in (0, 10001)` 一律当成功，把「请求处理中，请勿重复操作」这种明确
#: 没签成的回执也记成成功（对齐上游 v1.7.30 #596）。
CHECKIN_PENDING_HINTS = ("处理中", "请勿重复操作", "系统繁忙", "稍后再试")
CHECKIN_ALREADY_HINTS = ("已签到",)
CHECKIN_FAILURE_HINTS = ("失败",)

#: 上游对单账号活跃会话有硬上限（实测 10 条）：只建不收尾，攒满后建会话
#: 一律 429 / 10105。收尾语义见 web_conversation_release / prune。
WEB_CONVERSATION_ACTIVE_LIMIT = 10
#: 撞上限时清理到剩这么多条（留余量，避免下一轮立刻又撞）
WEB_CONVERSATION_PRUNE_KEEP = 8
#: 仍在占名额的会话状态
WEB_CONVERSATION_ACTIVE_STATUSES = ("working", "creating", "pending")

#: 还没跑到 turn 就失败（建会话 5xx、取沙箱失败）时的退避基数（秒）。那几轮
#: 只用掉几百毫秒、不消耗任何等待预算，背靠背重试等于把所有尝试挤进同一个
#: 上游故障窗口。0 = 关闭退避（旧行为）。
WEB_RETRY_BACKOFF = float(os.environ.get("WB_WEB_RETRY_BACKOFF") or "5")
#: 单次退避上限（秒）：指数增长到它就封顶，避免把整批巡检拖太久。
WEB_RETRY_BACKOFF_MAX = float(os.environ.get("WB_WEB_RETRY_BACKOFF_MAX") or "30")

#: 网页活跃至少跑两轮：第二轮留给「会话只是慢」（状态=working）。
WEB_MIN_ROUNDS = 2
#: 单账号总预算（秒）；0 = 不限制。每轮等待和建会话退避都从它里面扣。
WEB_BUDGET_DEFAULT = 600
#: 剩余预算低于这个值就不再开新的一轮。
WEB_BUDGET_MIN_ROUND = 30

#: 本进程登记着「已建未收尾」的网页会话。卡在 socket 上的线程走不到
#: finally，别的线程要能按这张表替它收尾。
WEB_LIVE_STALE_FACTOR = 2
WEB_ORPHAN_SWEEP_SECONDS = 1800
WEB_LIVE_REGISTRY_TTL = 24 * 3600
WEB_LIVE_REGISTRY_MAX = 128

_WEB_LIVE = {}
_WEB_LIVE_LOCK = threading.Lock()


def web_live_register(uid, conversation, model=""):
    """记下一条刚建出来、还没收尾的网页会话（供别的线程代收尾）。"""
    if not uid or not conversation:
        return
    now = time.time()
    with _WEB_LIVE_LOCK:
        for key, item in list(_WEB_LIVE.items()):
            if now - item.get("started", 0) > WEB_LIVE_REGISTRY_TTL:
                _WEB_LIVE.pop(key, None)
        while len(_WEB_LIVE) >= WEB_LIVE_REGISTRY_MAX:
            oldest = min(_WEB_LIVE, key=lambda key: _WEB_LIVE[key].get("started", 0))
            _WEB_LIVE.pop(oldest, None)
        _WEB_LIVE[(str(uid), str(conversation))] = {
            "uid": str(uid), "conversation": str(conversation),
            "model": model or "", "started": now,
        }


def web_live_unregister(uid, conversation):
    with _WEB_LIVE_LOCK:
        _WEB_LIVE.pop((str(uid), str(conversation)), None)


def web_live_snapshot(uid=None, min_age=0.0):
    """还记着的未收尾会话；给了 uid 只看这个账号，min_age 只挑跑过头的。"""
    now = time.time()
    with _WEB_LIVE_LOCK:
        items = [dict(item) for item in _WEB_LIVE.values()]
    out = []
    for item in items:
        if uid and item["uid"] != str(uid):
            continue
        if min_age and now - item["started"] < min_age:
            continue
        out.append(item)
    return out


def _clean_candidates(models):
    """保序去重；空 id 不会送到上游。"""
    seen = set()
    ordered = []
    for model in models or []:
        name = str(model or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def web_retry_backoff(round_index, base=None, cap=None):
    """第 round_index 轮（从 0 起）失败后要等多久，秒；0 表示不退避。

    基数默认取 WB_RETRY_BACKOFF（设置页可改），上限默认取
    WB_RETRY_BACKOFF_MAX，但不会小于基数——否则把基数调大后会被一个更小的
    上限悄悄压回去。
    """
    base = WEB_RETRY_BACKOFF if base is None else base
    cap = WEB_RETRY_BACKOFF_MAX if cap is None else cap
    if base <= 0:
        return 0.0
    return min(base * (2 ** round_index), max(cap, base))


def active_conversation_limit(status, detail):
    """上游这次拒绝是否表示「活跃会话已满」。

    控制台 API 回 HTTP 429 + code 10105，文案形如
    "you have reached the maximum number of active conversations(10)"。
    只匹配 code 就够，但也检查文案：改写响应体的代理仍能走到清理路径，
    而不是把一个裸 429 直接抛给用户。
    """
    if status != 429:
        return False
    text = str(detail or "").lower()
    return "10105" in text or "maximum number of active conversations" in text


def _parse_created_at(value):
    """上游 ISO 8601 createdAt -> epoch 秒；解析不出来返回 0.0。"""
    text = str(value or "").strip()
    if not text:
        return 0.0
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return stamp.timestamp()


def checkin_state(code, msg):
    """把签到回执归成 checked / already / pending / failed。

    只有 checked / already 能写 last_checkin：写早了（旧实现拿到 HTTP 200
    就先写盘）会让当天 can_checkin() 恒为 False，这次失败被永久放弃，
    9 点与 21 点两轮再也不会重试，面板还显示「今日已领」。
    """
    text = str(msg or "")
    if any(k in text for k in CHECKIN_PENDING_HINTS):
        return "pending"
    if code == 0:
        # 「失败」是唯一的硬词：更宽的口径会把「签到成功，距离 7 天奖励
        # 还不足」里的「不足」判成失败。
        return "failed" if any(k in text for k in CHECKIN_FAILURE_HINTS) else "checked"
    if code == 10001:
        return "already" if any(k in text for k in CHECKIN_ALREADY_HINTS) else "failed"
    return "failed"


#: realm -> 端点/身分配置。由渠道适配器注入，本模块不写死任何域名。
REALM_CONFIGS = {}
_REALM_LOCK = threading.Lock()

#: 余额缓存（uid -> (at, credits)），面板短时重复查询直接复用
_credits_cache = {}
_credits_lock = threading.Lock()
CREDITS_TTL = 60


def register_realm_config(realm, cfg):
    """渠道适配器启动时注入一个 realm 的端点与身分配置。

    除端点/身分字段外，cfg 还可携带四个可选注入回调，供令牌换发型等
    非默认形状的渠道接管账号级动作（不注入则走本模块的默认实现）：
      refresh_fn(account) -> bool          令牌续期
      credits_fn(account, force) -> dict   余额查询（返回 {"ok", ...}）
      checkin_fn(account, trigger) -> dict 签到/领取
      probe_fn(account, timeout) -> dict   连通性探测（返回 {"ok", ...}）
    """
    with _REALM_LOCK:
        REALM_CONFIGS[str(realm)] = dict(cfg)


def get_realm_config(realm):
    cfg = REALM_CONFIGS.get(str(realm or ""))
    if cfg is None:
        raise KeyError("realm '%s' is not configured by any channel adapter" % realm)
    return cfg


def _exponential_backoff(count, base, cap, offset):
    step = max(0, int(count) - int(offset))
    return net.exponential_backoff(step, base, cap)


def soft_backoff(streak):
    return _exponential_backoff(streak, SOFT_RATE_BASE, SOFT_RATE_MAX, 1)


def unverified_soft_backoff(streak):
    return _exponential_backoff(streak, SOFT_RATE_UNVERIFIED_BASE,
                                SOFT_RATE_UNVERIFIED_MAX, 1)


def breaker_backoff(fails):
    return _exponential_backoff(fails, BREAKER_COOLDOWN, BREAKER_COOLDOWN_MAX,
                                BREAKER_THRESHOLD)


def degrade_backoff(fails):
    return _exponential_backoff(fails, DEGRADE_COOLDOWN, DEGRADE_COOLDOWN_MAX,
                                DEGRADE_THRESHOLD)


def next_local_4am(now=None):
    """下一个本地 04:00 的 epoch（国内积分在夜里重置）。"""
    return timeutil.local_hour_epoch(4, now)


def _human_delta(seconds):
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _secs = divmod(rem, 60)
    if days:
        return "%dd %dh" % (days, hours)
    if hours:
        return "%dh %dm" % (hours, mins)
    if mins:
        return "%dm" % mins
    return "%ds" % seconds


def _jwt_claims(token):
    try:
        segment = str(token).split(".")[1]
        segment += "=" * (-len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(segment))
    except Exception:
        return {}


def jwt_claims(token):
    """公开的 JWT 声明读取：渠道适配器用它解析登录账号（邮箱/手机号）。"""
    claims = _jwt_claims(token)
    return claims if isinstance(claims, dict) else {}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\s().-]{5,}$")


def looks_like_login_account(value):
    """值本身是不是邮箱或手机号；昵称/账号名不做猜测。"""
    text = str(value or "").strip()
    if not text:
        return False
    if _EMAIL_RE.match(text):
        return True
    if not _PHONE_RE.match(text):
        return False
    digits = re.sub(r"\D", "", text)
    return 7 <= len(digits) <= 15


def jwt_exp(token):
    try:
        return int(_jwt_claims(token).get("exp") or 0)
    except (TypeError, ValueError):
        return 0


def jwt_iat(token):
    try:
        return int(_jwt_claims(token).get("iat") or 0)
    except (TypeError, ValueError):
        return 0


def jwt_uid(token):
    return str(_jwt_claims(token).get("sub") or "")


def jwt_issuer(token):
    return str(_jwt_claims(token).get("iss") or "")


def jwt_enterprise_id(token=None):
    return str(_jwt_claims(token or "").get("enterprise_id") or "")


def normalize_epoch(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number > 1e11:
        number /= 1000.0
    return int(number)


# 区域标记：国内出口换过域名，三个都认；国际认两个。
CN_REALM_MARKERS = ("copilot.tencent.com", "codebuddy.cn", "workbuddy.cn")
INTL_REALM_MARKERS = ("workbuddy.ai", "codebuddy.ai")


def realm_evidence(token, domain=None):
    """从 token / 域名里看区域，看不出返回 None（不瞎猜）。"""
    iss = jwt_issuer(token).lower()
    if any(marker in iss for marker in CN_REALM_MARKERS):
        return "cn"
    if any(marker in iss for marker in INTL_REALM_MARKERS):
        return "intl"
    dom = str(domain or "").lower()
    if any(marker in dom for marker in CN_REALM_MARKERS):
        return "cn"
    if any(marker in dom for marker in INTL_REALM_MARKERS):
        return "intl"
    return None


def detect_realm_from_token(token, domain=None):
    return realm_evidence(token, domain) or "intl"


def _requires_pro(model, realm):
    """模型是否被上游标成 PRO 专属；层级表缺失时一律放行。"""
    if not model:
        return False
    try:
        from intel import tiers
        return tiers.requires_pro(model, realm)
    except Exception:
        return False


def normalise_disabled_models(raw):
    """人工禁用模型名单归一：小写、去重、保持顺序；坏数据视为没配。"""
    out, seen = [], set()
    if not isinstance(raw, (list, tuple)):
        return out
    for mid in raw:
        if not isinstance(mid, str):
            continue
        name = mid.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def explain_code(code, msg=""):
    hint = CODE_HINTS.get(code)
    if hint:
        if msg and msg != hint:
            return "%s (%s)" % (msg, hint)
        return hint
    return msg or ("code=%s" % (code,))


def _auth_failure_text(text):
    """凭据形状的 401 文案判定。中间层代理返回的 HTML 401 页面不是令牌已死的
    证据——按它罚号会把健康凭据踢出轮换直到人工重新登录；只有失败文案本身
    点名鉴权（401 / unauthorized / token expired …）才标记令牌过期。
    """
    lower = str(text or "").lower()
    if "<html" in lower:
        return False
    return ("401" in lower or "unauthorized" in lower or "authorization" in lower
            or "token expired" in lower or "invalid_token" in lower)


def _auth_base_headers(cfg):
    """登录/刷新链路共用的 6 键基础头（start_login / poll_login / refresh 同族）。"""
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": cfg.get("billing_ua") or cfg.get("chat_ua"),
        "Origin": cfg.get("origin"),
        "Referer": (cfg.get("origin") or "") + "/",
    }


def _daily_chat_stream_ok(raw):
    """每日活跃对话：HTTP 200 不等于完成，必须看到有效事件。

    空流、只有 [DONE]、或带非零业务码/error 的帧都不算完成；否则面板会
    记成“已打卡”但上游其实没有计入当日活跃。
    """
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw or "")
    text = text.strip()
    if not text:
        return False
    frames = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        body = line[5:].strip() if line.startswith("data:") else line
        if not body or body == "[DONE]":
            continue
        try:
            frames.append(json.loads(body))
        except Exception:
            continue
    if not frames:
        try:
            frames = [json.loads(text)]
        except Exception:
            return False
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        if frame.get("error"):
            return False
        code = frame.get("code")
        if code is not None and str(code) not in ("0", "200", "000000"):
            return False
        choices = frame.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                return True
            payload = choice.get("delta") or choice.get("message") or {}
            if not isinstance(payload, dict):
                continue
            if (str(payload.get("content") or "").strip()
                    or str(payload.get("reasoning_content") or "").strip()
                    or payload.get("tool_calls")):
                return True
    return False


def tier_from_summary(data):
    """把一次计费摘要响应归一成档位记录（付费标记 + 套餐名）。

    两个出口都在 `/billing/meter/get-user-resource-summary` 上回这些字段；
    实测 SubscriptionPackageCode 一直是空的，所以展示用的是套餐**名**。
    没有 `IsPaidUser` 的响应返回 None —— 「没答」绝不能被记成「免费」。
    """
    if not isinstance(data, dict) or "IsPaidUser" not in data:
        return None
    try:
        trial = int(data.get("ProTrialStatus") or 0)
    except (TypeError, ValueError):
        trial = 0
    return {
        "paid": bool(data.get("IsPaidUser")),
        "package": str(data.get("SubscriptionPackageName") or ""),
        "package_code": str(data.get("SubscriptionPackageCode") or ""),
        "protected_price": bool(data.get("IsProtectedPriceUser")),
        "trial": trial,
        "checked_at": time.time(),
    }


class Account(object):
    def __init__(self, data, path=None):
        data = data or {}
        self.path = path
        self.accounts_dir = os.path.dirname(path) if path else ""
        token = str(data.get("accessToken") or "")
        self.uid = str(data.get("uid") or jwt_uid(token))
        raw_nickname = data.get("nickname")
        if isinstance(raw_nickname, str) and "$wbEncrypted" not in raw_nickname:
            self.nickname = raw_nickname.strip()
        else:
            self.nickname = ""
        self.domain = str(data.get("domain") or "")
        self.realm = str(data.get("realm") or detect_realm_from_token(token, self.domain))
        if not self.domain and REALM_CONFIGS.get(self.realm):
            self.domain = get_realm_config(self.realm).get("domain") or ""
        self.platform = str(data.get("platform") or "CLI")
        self.enterprise_id = str(data.get("enterpriseId") or "")
        if not self.enterprise_id:
            self.enterprise_id = jwt_enterprise_id(token)
        self.product = identity.normalize_product(data.get("product"))
        self.access_token = token
        self.refresh_token = str(data.get("refreshToken") or "")
        self.expires_at = normalize_epoch(data.get("expiresAt")) or jwt_exp(token)
        self.added_at = data.get("addedAt") or time.time()
        self.source = str(data.get("source") or "oauth")
        self.proxy_legacy = str(data.get("proxy") or "").strip()
        self.proxy = self.proxy_legacy          # 运行时解析值，由池按出口槽位重算
        self.enabled = data.get("enabled", True)
        # 人工调度权重（1 = 不干预）；随凭据持久化
        try:
            self.weight = max(1, min(100, int(data.get("weight") or 1)))
        except (TypeError, ValueError):
            self.weight = 1
        raw_note = data.get("note")
        self.note = (raw_note if isinstance(raw_note, str) else "").strip()[:200]
        # 渠道自定义持久化元数据（如 Qoder 签名/续期共用的 machineId）。
        # 核心不解释内容，只保证随凭据落盘并在导出/导入时保留。
        raw_meta = data.get("meta")
        self.meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
        # 人工禁用模型名单：与自动冷却严格分开，随凭据持久化
        self.disabled_models = normalise_disabled_models(data.get("disabledModels"))
        self.session_dead_count = int(data.get("sessionDeadCount") or 0)
        self.token_expired = bool(not self.access_token)
        self.credits = data.get("credits") or None
        # 会员档位（来自计费摘要的套餐名 + 付费标记）：面板账号行上的胶囊用它。
        # 没查过摘要就是 None——不猜档位，也不把「没查过」画成「免费」。
        self.tier = data.get("tier") if isinstance(data.get("tier"), dict) else None
        # 上游确认的付费身份：来自余额快照的 is_paid_user。没刷新过余额的
        # 账号按免费处理，避免把 PRO 专属模型派给免费号后才发现 11158。
        self.is_paid_user = bool(
            self.credits.get("is_paid_user")
            if isinstance(self.credits, dict) else False)
        self.last_checkin = data.get("lastCheckin") or None
        self.last_daily_chat = data.get("lastDailyChat") or None
        self.last_activity_report = data.get("lastActivityReport") or None
        # 上游风控限制（403 / code 11140）的冷却期限：**持久化**字段。它与普通
        # 冷却不同——限令在服务端，重启 / 换身分都不会解除；只有余额刷新等
        # 明确的恢复信号才抬出（见 note_success / revive 类路径）。不持久化的
        # 话重启就当无事发生，同一台设备上的账号会被一个个送进风控。
        try:
            self.restricted_until = max(0.0, float(data.get("restrictedUntil") or 0))
        except (TypeError, ValueError):
            self.restricted_until = 0.0

        # ---- 以下都是运行时状态，不落盘（重启拿干净一轮）----
        self.last_error = ""
        self.last_error_detail = ""
        self.cooldown_until = 0.0
        self.model_cooldowns = {}
        self.model_cooldowns_at = {}
        self.balance_until = 0.0
        self.soft_streak = 0
        self.unscoped_streak = 0
        self.fails = 0
        self.degrade_count = 0
        self.breaker_until = 0.0
        self.degrade_until = 0.0
        self.last_fail_at = 0.0
        self.last_soft_at = 0.0
        self._throttle_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._save_lock = threading.RLock()
        self._credits_lock = threading.Lock()

    # ------------------------------------------------------------ 序列化
    def to_dict(self):
        """完整视图（导出用，含运行时状态）。"""
        out = self._stored_dict()
        out.update({
            "lastError": self.last_error,
            "cooldownUntil": self.cooldown_until,
        })
        return out

    def _stored_dict(self):
        """只含持久化字段：凭据、人工设置、余额与任务闸门。"""
        return {
            "uid": self.uid,
            "nickname": self.nickname,
            "domain": self.domain,
            "realm": self.realm,
            "platform": self.platform,
            "product": self.product,
            "enterpriseId": self.enterprise_id,
            "accessToken": self.access_token,
            "refreshToken": self.refresh_token,
            "expiresAt": self.expires_at,
            "addedAt": self.added_at,
            "source": self.source,
            "proxy": self.proxy_legacy,
            "enabled": self.enabled,
            "weight": self.weight,
            "note": self.note,
            "meta": dict(self.meta or {}),
            "disabledModels": list(self.disabled_models),
            "sessionDeadCount": self.session_dead_count,
            # 风控限制是服务端的限令：持久化后重启才不会把受限账号当可用号
            # 重新入池（见 note_restricted）。导出的文档会带上它供查看，导入侧
            # 缺字段时 init 回 0，行为不变。
            "restrictedUntil": self.restricted_until,
            "credits": self.credits,
            "tier": self.tier,
            "lastCheckin": self.last_checkin,
            "lastDailyChat": self.last_daily_chat,
            "lastActivityReport": self.last_activity_report,
        }

    def _login_account_info(self):
        """返回 (登录身份, 来源)。

        优先级：账号持久化身份 → 渠道适配器从令牌/资料解析 → 邮箱/手机号
        形状的昵称 → uid。昵称本身不是登录账号，只在没有更强的信号时兜底。
        """
        meta = self.meta if isinstance(self.meta, dict) else {}
        for key in ("loginAccount", "email", "phone", "phoneNumber"):
            value = meta.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), "meta"
        cfg = REALM_CONFIGS.get(self.realm) or {}
        resolver = cfg.get("login_account_fn")
        if callable(resolver):
            try:
                value = resolver(self)
            except Exception:
                value = ""
            if isinstance(value, str) and value.strip():
                return value.strip(), "channel"
        nickname = str(self.nickname or "").strip()
        if nickname:
            return nickname, "nickname"
        return str(self.uid or "").strip(), "uid"

    def login_account(self):
        """面板展示/复制的登录账号（邮箱或手机号）。"""
        return self._login_account_info()[0]

    def login_account_source(self):
        """登录身份的来源：meta / channel / nickname / uid。"""
        return self._login_account_info()[1]

    def public(self):
        exp = self.expires_at or jwt_exp(self.access_token)
        iat = jwt_iat(self.access_token)
        ttl = (exp - iat) if iat and exp > iat else None
        now = time.time()
        is_token_expired = bool(
            getattr(self, "token_expired", False)
            or (exp and exp <= now) or not self.access_token)
        deadline = max(self.cooldown_until, self.balance_until,
                       self.breaker_until, self.degrade_until,
                       self.restricted_until)
        models = sorted(
            ({"model": mid, "expiresAt": int(until),
              "startedAt": int(self.model_cooldowns_at.get(mid) or 0)}
             for mid, until in self.model_cooldowns.items() if until > now),
            key=lambda item: item["expiresAt"])
        cfg = REALM_CONFIGS.get(self.realm) or {}
        return {
            "uid": self.uid,
            "nickname": self.nickname or (self.uid[:8] if self.uid else "?"),
            "loginAccount": self.login_account(),
            "domain": self.domain,
            "realm": self.realm,
            "platform": self.platform,
            "product": self.product,
            "enterpriseId": self.enterprise_id,
            "enabled": bool(self.enabled),
            "weight": int(self.weight),
            "note": self.note,
            "disabledModels": list(self.disabled_models),
            "source": self.source,
            "proxy": self.proxy,
            "expiresAt": exp,
            "expiresIn": "expired" if is_token_expired else (
                _human_delta(exp - now) if exp else None),
            "isExpired": bool(exp and exp <= now),
            "tokenExpired": is_token_expired,
            "needRelogin": is_token_expired,
            "issuedAt": iat or None,
            "ttlSeconds": ttl,
            "hasRefreshToken": bool(self.refresh_token),
            "lastError": self.last_error,
            "lastErrorDetail": self.last_error_detail or None,
            "inCooldown": deadline > now,
            "cooldownFor": round(max(0.0, deadline - now)) or None,
            "modelCooldowns": models,
            "softStreak": int(self.soft_streak),
            "unscopedStreak": int(self.unscoped_streak),
            "breakerFor": round(max(0.0, self.breaker_until - now)) or None,
            "degradeFor": round(max(0.0, self.degrade_until - now)) or None,
            "balanceFor": round(max(0.0, self.balance_until - now)) or None,
            "restrictedFor": round(max(0.0, self.restricted_until - now)) or None,
            "sessionDeadCount": self.session_dead_count,
            "addedAt": self.added_at,
            "file": os.path.basename(self.path) if self.path else None,
            "credits": self.credits,
            "tier": self.tier,
            "lastCheckin": self.last_checkin,
            "lastDailyChat": self.last_daily_chat,
            "lastActivityReport": self.last_activity_report,
            "canCheckin": (cfg.get("has_checkin") is True
                           and bool(self.access_token or self.refresh_token)),
            "canDailyChat": (self.realm == "intl" and bool(self.access_token)
                             and cfg.get("has_daily_chat") is True),
            # 渠道存了真实设备标识时优先透出（如 Qoder 必须与客户端同源），
            # 否则沿用历史派生值。
            "machineId": (str(self.meta.get("machineId") or "")
                          or derive_id(self.uid, "machine")),
            "sessionId": session_id(self.uid),
            "ready": self.ready(),
            "unavailable": self.unavailable_reason(),
        }

    def save(self, directory):
        os.makedirs(directory, exist_ok=True)
        name = (self.uid or uuid.uuid4().hex) + ".json"
        path = os.path.join(directory, name)
        with self._save_lock:
            fsutil.atomic_write_json(path, self._stored_dict())
            self.path = path
            self.accounts_dir = directory
        return path

    def delete(self):
        if self.path and os.path.exists(self.path):
            os.remove(self.path)

    # ------------------------------------------------------------ 可用性
    def model_is_banned(self, model):
        """人工禁用名单命中（小写精确匹配）。"""
        return bool(model) and str(model).lower() in self.disabled_models

    def unavailable_reason(self, model=None):
        """此刻为什么接不了单；可用时返回空串。顺序与 ready() 一致。"""
        if not self.enabled:
            return "已停用"
        if getattr(self, "token_expired", False) and not self.refresh_token:
            return "凭证已失效，需重新登录"
        if not self.access_token:
            if not self.refresh_token:
                return "无凭证"
            if not self.is_paid_user and _requires_pro(model, self.realm):
                return "该模型仅限 PRO 账号"
            return ""   # 令牌换发型账号：有 refreshToken 即视为有凭据
        now = time.time()
        penalties = [("上游风控限制", self.restricted_until),
                     ("熔断", self.breaker_until), ("降级窗口", self.degrade_until),
                     ("余额停车", self.balance_until), ("限流冷却", self.cooldown_until)]
        if model:
            penalties.append(("模型 %s 冷却" % model,
                              self.model_cooldowns.get(model, 0.0)))
        label, until = max(penalties, key=lambda item: item[1])
        if until > now:
            return "%s 剩余 %s" % (label, _human_delta(until - now) or "?")
        if self.model_is_banned(model):
            return "模型 %s 在该账号的人工禁用名单中" % model
        if not self.is_paid_user and _requires_pro(model, self.realm):
            return "该模型仅限 PRO 账号"
        exp = self.expires_at or jwt_exp(self.access_token)
        if exp and exp - now <= 120:
            return "凭证已过期"
        return ""

    def ready(self, model=None):
        if not self.enabled:
            return False
        if self.restricted_until > time.time():
            # 被上游风控限制：限令在服务端，换发了令牌也还在，等恢复信号。
            return False
        if getattr(self, "token_expired", False) and not self.refresh_token:
            # 令牌已判死且无换发凭据：只能重新登录。有 refreshToken 的账号
            # 仍放行到下面的现场换发（refresh 成功会清掉 token_expired）。
            return False
        # PRO 专属模型不派给免费号：上游会在请求花掉之后才回 11158。
        # 层级表没到 / 模型未知时 requires_pro 返回 False，行为与从前一致。
        # 这条排在 token 换发之前：换发型账号也不能绕过付费门控。
        if not self.is_paid_user and _requires_pro(model, self.realm):
            return False
        if not self.access_token:
            # 令牌换发型账号（如 ExchangeToken 语义）没有落盘 accessToken：
            # 有 refreshToken 就现场换发，换发成功即视为就绪
            if not self.refresh_token:
                return False
            return self.refresh()
        if self.throttle_wait(model=model) > 0:
            return False
        if self.model_is_banned(model):
            return False
        exp = self.expires_at or jwt_exp(self.access_token)
        if not exp:
            return True
        if exp - time.time() > 120:
            return True
        return self.refresh()

    # ------------------------------------------------------------ 出站
    def is_cli_identity(self):
        """出站身份是不是官方 CodeBuddy CLI（决定 chat 的 wire 形态）。"""
        return self.product == identity.PRODUCT_CLI

    def headers(self, purpose="chat", session_key=None, turn_request_id=None,
                model=None, conversation_id=None):
        """组出这一轮的出站标头（chat = 桌面/插件/CLI 身分；billing = 计费端点）。

        `model` / `conversation_id` / `session_key` / `turn_request_id` 只对 chat
        用途有意义：VSCode 身份在 model 请求上带 X-Model-ID、会话 id 按会话稳定；
        CLI 身份的会话 id 按 (uid, session_key) 稳定、X-Conversation-Request-ID
        一轮 user send 内复用；计费端点不吃这套身分，四个参数在 billing 路径被忽略。
        """
        cfg = get_realm_config(self.realm)
        if purpose != "chat":
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": cfg.get("billing_ua") or cfg.get("chat_ua"),
                "Origin": cfg.get("origin"),
                "Referer": (cfg.get("origin") or "") + "/",
                "Authorization": "Bearer " + self.access_token,
                "X-User-Id": self.uid,
                "X-Domain": self.domain or cfg.get("domain"),
                "X-CodeBuddy-Request": "1",
                "Accept-Language": "en-US" if self.realm == "intl" else "zh-CN",
                "X-Request-ID": generate_request_id(self.uid),
                "X-Machine-ID": derive_id(self.uid, "machine"),
                "X-Session-ID": session_id(self.uid),
            }
            if self.enterprise_id:
                headers["X-Enterprise-Id"] = self.enterprise_id
                headers["X-Tenant-Id"] = self.enterprise_id
            else:
                headers["X-No-Enterprise-Id"] = "1"
            if self.realm == "cn":
                headers["X-Product"] = "SaaS"
            return headers

        if self.is_cli_identity():
            # 官方 CLI 的 chat 请求由 OpenAI Node SDK 发出：浏览器头一个都没有
            # （X-Requested-With 也没有），Accept 就是 application/json。
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        else:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
                "Origin": cfg.get("origin"),
                "Referer": (cfg.get("origin") or "") + "/",
                "X-CodeBuddy-Request": "1",
                "Accept-Language": "en-US" if self.realm == "intl" else "zh-CN",
            }
        settings_dir = self.accounts_dir or (
            os.path.dirname(self.path) if self.path else "")
        headers.update(identity.build_identity_headers(
            product=self.product, realm=self.realm, uid=self.uid,
            token=self.access_token, enterprise_id=self.enterprise_id,
            tenant_id=self.enterprise_id, session_key=session_key,
            turn_request_id=turn_request_id, model=model,
            conversation_id=conversation_id,
            private_data=(settings.identity_private_data(settings_dir)
                          if settings_dir else "auto")))
        # 国内版客户端带真实 Turing Shield 设备 token；本机没有对应 SDK、生成不了
        # 真实 token，设备头整族跳过（宁缺毋伪造）。VSCode 非企业号按官方
        # token || error 的失败态发占位——「两者都不发」是官方不存在的状态。
        if self.product == identity.PRODUCT_VSCODE and not self.enterprise_id:
            headers["X-Device-Token-Error"] = "sdk_not_initialized"
        return headers

    def set_product(self, value):
        new = identity.normalize_product(value)
        if new == self.product:
            return False
        self.product = new
        try:
            self.domain = identity.endpoint_for(self.realm, new)[1]
        except Exception:
            pass
        if self.path:
            self.save(os.path.dirname(self.path) or ".")
        return True

    def chat_base_url(self):
        return identity.endpoint_for(self.realm, self.product)[0]

    def probe(self, model=None, timeout=20):
        """探测该账号的对话连通性：发一次最小流式对话。

        渠道注入了 probe_fn 时探测完全由渠道实现（Trae 等协议不同的上游）；
        默认实现走 WorkBuddy 形状：max_tokens=1 流式对话，首条 system，
        走账号自己的代理槽与出站身份，失败用错误码表翻译成人话；只做诊断，
        不触碰熔断/冷却等账号治理状态。返回 {ok, message[, code, latencyMs, model]}。
        """
        if not self.access_token:
            return {"ok": False, "message": "该账号没有可用的访问令牌"}
        cfg = get_realm_config(self.realm)
        injected = cfg.get("probe_fn")
        if callable(injected):
            try:
                return injected(self, timeout=timeout)
            except Exception as exc:
                return {"ok": False, "message": "请求异常: %s" % exc}
        mdl = model or cfg.get("probe_model") or cfg.get("daily_chat_model")
        url = self.chat_base_url() + cfg["chat_path"]
        probe_body = upstream_body.build_upstream_body({
            "model": mdl,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "ping"},
            ],
            "max_tokens": 1,
            "stream": True,
        })
        # 与代理 chat 路径同一条出站形态：CLI 身份 drop 内部键 + cache_retention；
        # CLI / VSCode 主 chat 默认 gzip；紧凑 JSON 统一编码。
        cli_identity = self.is_cli_identity()
        if cli_identity:
            probe_body = {k: v for k, v in probe_body.items()
                          if k not in identity.CLI_BODY_DROP_FIELDS}
            probe_body["cache_retention"] = identity.CLI_CACHE_RETENTION
        data = upstream_body.encode_upstream_body(probe_body)
        headers = self.headers(purpose="chat", model=mdl)
        if cli_identity or self.product == identity.PRODUCT_VSCODE:
            headers["Content-Encoding"] = identity.REQUEST_CONTENT_ENCODING
            data = identity.gzip_body(data)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        # 头名原样上线（Request.add_header 会先 capitalize，有序原名单独挂给池路径）。
        req.wb_exact_headers = list(headers.items())
        started = time.time()
        try:
            with net.urlopen(req, timeout=timeout, proxy=self.proxy) as resp:
                chunk = resp.read(256)
            if not chunk:
                return {"ok": False, "message": "上游未返回任何数据（流已关闭）"}
            elapsed = int((time.time() - started) * 1000)
            return {"ok": True, "model": mdl, "latencyMs": elapsed,
                    "message": "连通正常（%s，%d ms）" % (mdl, elapsed)}
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8", "replace") or "{}"
                env = json.loads(raw)
                code = env.get("code", exc.code)
                msg = str(env.get("msg") or env.get("message") or "")
            except Exception:
                code, msg = exc.code, ""
            return {"ok": False, "code": code, "message": explain_code(code, msg)}
        except Exception as exc:
            return {"ok": False, "message": "请求异常: %s" % exc}

    # ------------------------------------------------------------ 令牌
    def refresh(self):
        if not self.refresh_token:
            self.token_expired = True
            self.last_error = "no refresh token; sign in again"
            return False
        cfg = get_realm_config(self.realm)
        injected = cfg.get("refresh_fn")
        if callable(injected):
            # 令牌换发型渠道（如 ExchangeToken 语义）：续期完全由渠道实现
            try:
                return bool(injected(self))
            except Exception as exc:
                self.last_error = "refresh failed: %s" % exc
                return False
        with self._refresh_lock:
            token = self.access_token
            if token and (jwt_exp(token) or 0) - time.time() > 120:
                # 并发请求里有人先刷新成功了：直接用新令牌，别再打一次上游
                return True
            url = cfg["chat_upstream"] + cfg["refresh_path"]
            headers = _auth_base_headers(cfg)
            headers.update({
                "X-Refresh-Token": self.refresh_token,
                "X-Auth-Refresh-Source": "workbuddy" if self.realm == "cn" else "plugin",
                "X-User-Id": self.uid,
                "X-Domain": self.domain or cfg.get("domain"),
            })
            if self.enterprise_id:
                headers["X-Enterprise-Id"] = self.enterprise_id
            try:
                payload = net.http_json(url, data=b"{}", method="POST",
                                        headers=headers, timeout=30)
            except Exception as exc:
                if _auth_failure_text(str(exc)):
                    self.token_expired = True
                    self.last_error = "登录已过期 (HTTP 401)，请重新登录"
                else:
                    self.last_error = "refresh failed: %s" % exc
                return False
            data = payload.get("data") or {}
            data = data.get("data") or data
            new_token = data.get("accessToken")
            if not new_token:
                self.token_expired = True
                code = payload.get("code")
                if code == SESSION_DEAD_CODE:
                    self.session_dead_count = int(self.session_dead_count or 0) + 1
                    self.last_error = "会话已失效（%d），需重新登录（连续第 %d/%d 次）" % (
                        code, self.session_dead_count, SESSION_DEAD_LIMIT)
                    if self.session_dead_count >= SESSION_DEAD_LIMIT and self.enabled:
                        self.enabled = False
                        self.last_error = ("会话已失效（%d），连续 %d 次续期失败，已自动停用；"
                                           "重新登录后可再启用" % (code, self.session_dead_count))
                    if self.path and os.path.exists(os.path.dirname(self.path)):
                        self.save(os.path.dirname(self.path))
                else:
                    self.last_error = "refresh returned no token (%s)" % payload.get("msg")
                return False
            self.access_token = new_token
            self.refresh_token = data.get("refreshToken") or self.refresh_token
            self.expires_at = jwt_exp(new_token) or self.expires_at
            self.token_expired = False
            self.last_error = ""
            self.cooldown_until = 0
            self.session_dead_count = 0
            if self.path and os.path.exists(os.path.dirname(self.path)):
                self.save(os.path.dirname(self.path))
            return True

    # ------------------------------------------------------------ 签到 / 打卡
    def checked_in_today(self):
        if not self.last_checkin:
            return False
        return str(self.last_checkin)[:10] == time.strftime("%Y-%m-%d")

    def can_checkin(self):
        cfg = REALM_CONFIGS.get(self.realm) or {}
        if cfg.get("has_checkin") is not True:
            return False
        if not self.enabled:
            return False
        # 令牌换发型账号落盘时只有 refreshToken（accessToken 用时才换发），
        # 签到流程自己会换发——有任一凭据即可签，不等内存里出现 accessToken
        if not (self.access_token or self.refresh_token):
            return False
        return not self.checked_in_today()

    def checkin(self, trigger="unknown"):
        """每日签到。渠道未声明签到能力或注入了自己的签到实现时交由注入侧。"""
        cfg = get_realm_config(self.realm)
        if cfg.get("has_checkin") is not True:
            return {"ok": False, "error": "checkin is not available for realm '%s'" % self.realm}
        injected = cfg.get("checkin_fn")
        if callable(injected):
            try:
                return injected(self, trigger)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        if self.realm != "cn":
            return {"ok": False, "error": "checkin is only available for CN realm accounts"}
        res = self._checkin_upstream()
        _record_activity(self, "checkin", trigger, res)
        # 签到带积分入账：立即强制拉一次余额落进账号视图，面板积分列即时更新
        # （force 越过 60s 缓存；仅在签到成功/幂等成功时刷，失败没有入账）
        if res.get("ok"):
            try:
                self.fetch_credits(force=True)
            except Exception:
                pass
        return res

    def _checkin_upstream(self):
        cfg = get_realm_config(self.realm)
        url = cfg["billing_upstream"] + cfg["checkin_path"]
        headers = self.headers(purpose="billing")
        try:
            payload = net.http_json(url, data=b"{}", method="POST",
                                    headers=headers, timeout=15)
            code = payload.get("code", -1)
            msg = payload.get("msg") or "ok"
            state = checkin_state(code, msg)
            if state in ("checked", "already"):
                # 只有真签成/确认已签才写盘：写早了会把当天这次失败永久放弃
                self.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
                if self.path and os.path.exists(os.path.dirname(self.path)):
                    self.save(os.path.dirname(self.path))
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            if state == "already":
                return {"ok": True, "state": state, "code": code, "already": True,
                        "msg": data.get("msg") or msg or "今天已签到",
                        "data": payload.get("data")}
            if state == "checked":
                return {"ok": True, "state": state, "code": code, "msg": msg,
                        "data": payload.get("data")}
            return {"ok": False, "state": state, "code": code, "msg": msg,
                    "error": msg, "data": payload.get("data")}
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8") or "{}")
                code = body.get("code")
                msg = body.get("msg") or ("HTTP %d" % exc.code)
                # 上游在今日已签到时可能返回 HTTP 400 +「今天已签到」：
                # 这表示今日事实上已完成，按幂等成功处理并记录时间。
                state = checkin_state(code, msg)
                if state == "already":
                    self.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
                    if self.path and os.path.exists(os.path.dirname(self.path)):
                        self.save(os.path.dirname(self.path))
                    return {"ok": True, "state": state, "code": code,
                            "already": True, "msg": msg}
                return {"ok": False, "state": state, "code": code,
                        "msg": msg, "error": msg}
            except Exception:
                return {"ok": False, "error": "HTTP %d" % exc.code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def daily_chatted_today(self):
        if not self.last_daily_chat:
            return False
        return str(self.last_daily_chat)[:10] == time.strftime("%Y-%m-%d")

    def can_daily_chat(self):
        if self.realm != "intl" or not self.enabled or not self.access_token:
            return False
        return not self.daily_chatted_today()

    def web_headers(self):
        cfg = get_realm_config(self.realm)
        return {
            "Authorization": "Bearer " + self.access_token,
            "X-User-Id": self.uid,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": cfg.get("web_origin"),
            "Referer": (cfg.get("web_origin") or "") + "/app",
            "User-Agent": cfg.get("web_ua"),
        }

    def daily_chat(self, web=None, trigger="unknown"):
        """国际版每日活跃（桌面轻量对话 + 可选网页通道会话）。"""
        if self.realm != "intl":
            return {"ok": False, "error": "daily chat is only for international accounts"}
        res = self._daily_chat_upstream(web)
        _record_activity(self, "daily_chat", trigger, res)
        return res

    def _daily_chat_upstream(self, web=None):
        cfg = get_realm_config(self.realm)
        model = self.daily_chat_model() or cfg["daily_chat_model"]
        url = self.chat_base_url() + cfg["chat_path"]
        headers = self.headers(purpose="chat", model=model)
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": True,
            "max_tokens": 10,
            "reasoning_effort": "none",
        }
        req_body = upstream_body.build_upstream_body(body)
        # 官方 CLI 的 chat 请求体：drop 内部键 + cache_retention + gzip；桌面端 /
        # VSCode 维持原请求体（VSCode 的 RequestBodyGzip 有 feature 开关、主 chat
        # 是否压仍待抓包确认）。
        cli_identity = self.is_cli_identity()
        if cli_identity:
            req_body = {k: v for k, v in req_body.items()
                        if k not in identity.CLI_BODY_DROP_FIELDS}
            req_body["cache_retention"] = identity.CLI_CACHE_RETENTION
            headers["Content-Encoding"] = identity.REQUEST_CONTENT_ENCODING
        data = upstream_body.encode_upstream_body(req_body)
        if cli_identity:
            data = identity.gzip_body(data)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        # 与代理 chat 路径同口径：头名原样上线（Request.add_header 会先
        # capitalize，有序原名单独挂在请求上给池路径用）。
        req.wb_exact_headers = list(headers.items())
        try:
            with net.urlopen(req, timeout=20, proxy=self.proxy) as resp:
                raw = resp.read()
            if not _daily_chat_stream_ok(raw):
                return {"ok": False,
                        "error": "每日活跃对话未返回有效内容（空流或上游拒绝）"}
            self.last_daily_chat = time.strftime("%Y-%m-%d %H:%M:%S")
            if self.path and os.path.exists(os.path.dirname(self.path)):
                self.save(os.path.dirname(self.path))
            try:
                self.fetch_credits()
            except Exception:
                pass
            result = {"ok": True, "msg": "每日活跃对话成功完成"}
            if web is None:
                import infra.settings as settings
                web = bool(self.accounts_dir) and settings.daily_chat_web(self.accounts_dir)
            if web:
                res = self.daily_chat_web(trigger=None)
                result["web"] = res
                if res.get("ok"):
                    result["msg"] = ("每日活跃对话成功完成（网页通道 %s：%d 段输出，%d ms）"
                                     % (res.get("status") or "completed",
                                        res.get("chunks") or 0, res.get("elapsed_ms") or 0))
                else:
                    result["msg"] = ("每日活跃对话成功完成（网页通道失败：%s）"
                                     % res.get("error"))
            return result
        except urllib.error.HTTPError as exc:
            try:
                err = exc.read().decode("utf-8", "replace")
            except Exception:
                err = str(exc)
            return {"ok": False, "error": "HTTP %d: %s" % (exc.code, err[:100])}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def daily_chat_web_prompt(self):
        """网页通道本轮提示词；随机池开关关闭时仍只发 Hi。"""
        cfg = get_realm_config(self.realm)
        default = cfg.get("daily_chat_prompt") or "Hi"
        if not self.path:
            return default
        directory = os.path.dirname(self.path)
        if not settings.daily_chat_web_random_prompt(directory):
            return default
        pool = list(settings.daily_chat_web_prompts(directory))
        builtin_fn = cfg.get("daily_chat_prompts_fn")
        if callable(builtin_fn):
            try:
                pool = list(builtin_fn()) + pool
            except Exception:
                pass
        return random.choice(pool) if pool else default

    def web_fallback_models(self):
        """网页通道按顺序尝试的候选模型。

        面板显式配置优先并保留操作者顺序；未配置时用本渠道的首选模型加
        realm 注入的免费兜底，避免默认行为退化。自动模式同样保序去重。
        """
        configured = []
        if self.path:
            configured = settings.daily_chat_models(os.path.dirname(self.path))
        if configured:
            return _clean_candidates(configured)
        cfg = get_realm_config(self.realm)
        return _clean_candidates(
            [cfg.get("daily_chat_model")]
            + list(cfg.get("daily_chat_fallback_models") or ()))

    def daily_chat_model(self):
        """桌面腿本轮用哪个模型：候选里第一个没有冷却的。"""
        candidates = self.web_fallback_models()
        now = time.time()
        for model in candidates:
            if self.model_cooldowns.get(model, 0.0) <= now:
                return model
        return candidates[0] if candidates else ""

    def daily_chat_budget(self):
        """单账号跑完网页活跃的总预算（秒）；0 = 不限制。"""
        if not self.path:
            return WEB_BUDGET_DEFAULT
        return settings.daily_chat_budget(
            os.path.dirname(self.path), default=WEB_BUDGET_DEFAULT)

    def daily_chat_web_policy(self):
        """(单轮最长等待秒数, 轮数)。

        轮数由候选序列推出（至少两轮：第二轮留给「会话只是慢」）。总时长由
        单账号预算兜底，不再用「总尝试次数」和候选数量互相覆盖。
        """
        cfg = get_realm_config(self.realm)
        base = int(cfg.get("web_turn_timeout") or 120)
        return base, max(WEB_MIN_ROUNDS, len(self.web_fallback_models()))

    def _web_conversation_call(self, conversation, action):
        """对一条网页会话执行动作（stop / delete）；返回上游是否接受。"""
        if not conversation:
            return False
        cfg = get_realm_config(self.realm)
        url = (cfg["web_conversations_url"] + urllib.parse.quote(str(conversation))
               + "/" + action)
        req = urllib.request.Request(url, data=b"{}", headers=self.web_headers(),
                                     method="POST")
        try:
            with net.urlopen(req, timeout=20, proxy=self.proxy) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        return payload.get("code") in (0, None)

    def web_conversation_release(self, conversation, delete=False):
        """结束一条网页会话，释放它占的活跃名额。

        默认只 stop：会话留在网页端历史里，状态从 working 变成 completed，
        名额随即释放。delete=True 时再删掉它——失败轮次没有保留价值，删掉
        免得网页端历史里堆满提示词。
        """
        stopped = self._web_conversation_call(conversation, "stop")
        if delete:
            return self._web_conversation_call(conversation, "delete") or stopped
        return stopped

    def web_conversation_list(self, page_size=50):
        """读账号的网页会话列表（上游按创建时间倒序返回）。"""
        cfg = get_realm_config(self.realm)
        url = cfg["web_conversations_url"] + "?page=1&pageSize=%d" % max(1, int(page_size))
        req = urllib.request.Request(url, headers=self.web_headers(), method="GET")
        try:
            with net.urlopen(req, timeout=20, proxy=self.proxy) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except Exception:
            return []
        data = (payload if isinstance(payload, dict) else {}).get("data") or {}
        conversations = data.get("conversations")
        return conversations if isinstance(conversations, list) else []

    def _daily_activity_prompt_pool(self):
        """本网关可能用作会话名的提示词（内置池 + 操作者自定义）。"""
        cfg = get_realm_config(self.realm)
        pool = set()
        builtin_fn = cfg.get("daily_chat_prompts_fn")
        if callable(builtin_fn):
            try:
                pool.update(builtin_fn())
            except Exception:
                pass
        if self.path:
            try:
                pool.update(settings.daily_chat_web_prompts(
                    os.path.dirname(self.path)))
            except Exception:
                pass
        pool.add(cfg.get("daily_chat_prompt") or "")
        return pool

    def web_conversation_prune(self, keep=WEB_CONVERSATION_PRUNE_KEEP):
        """停掉最旧的活跃会话，把账号拉回上限以下；返回停掉的条数。

        只在撞到 10105 时调用，用来收拾老版本漏下的会话。按创建时间从旧到新
        停，且只动名字属于每日活跃提示词池的会话——用户自己在网页端的真实对话
        不碰。stop 不是删除：会话仍在网页端历史里，只是不再占活跃名额。
        """
        conversations = self.web_conversation_list()
        active = [c for c in conversations
                  if str((c or {}).get("status") or "").lower()
                  in WEB_CONVERSATION_ACTIVE_STATUSES]
        if len(active) < WEB_CONVERSATION_ACTIVE_LIMIT:
            return 0
        active.sort(key=lambda c: str((c or {}).get("createdAt") or ""))
        pool = self._daily_activity_prompt_pool()
        stopped = 0
        for conversation in active:
            if len(active) - stopped <= keep:
                break
            if str((conversation or {}).get("name") or "").strip() not in pool:
                continue
            if self._web_conversation_call(conversation.get("id"), "stop"):
                stopped += 1
        return stopped

    def web_conversation_reclaim(self, max_age=0.0):
        """替别的线程收尾它建出来、却还没注销的网页会话；返回收掉条数。

        正常路径靠 finally 注销；但 socket 层存在走不到 finally 的窗口
        （DNS 不吃 socket 超时、服务端可以一直滴数据）。这张进程内登记表让
        别的线程能在超时后替它收尾，不再永久占用上游活跃名额。
        """
        reclaimed = 0
        for item in web_live_snapshot(self.uid, min_age=max_age):
            conversation = item.get("conversation")
            if self.web_conversation_release(conversation, delete=True):
                # 收尾成功后才摘登记：失败时留着重试。
                web_live_unregister(self.uid, conversation)
                reclaimed += 1
        return reclaimed

    def web_conversation_sweep_orphans(self, older_than=WEB_ORPHAN_SWEEP_SECONDS):
        """清扫上一个进程留下的活跃会话；只停我们建的、够老的、仍在跑的。

        进程重启后登记表没了，只能按上游会话列表兜底。只 stop 不 delete，
        历史保留；用户自己的对话和另一个实例正在跑的较新会话都不碰。
        """
        try:
            conversations = self.web_conversation_list()
        except Exception:
            return 0
        cutoff = time.time() - max(0, older_than)
        pool = self._daily_activity_prompt_pool()
        stopped = 0
        for conversation in conversations:
            data = conversation or {}
            if str(data.get("status") or "").lower() not in WEB_CONVERSATION_ACTIVE_STATUSES:
                continue
            if str(data.get("name") or "").strip() not in pool:
                continue
            created = _parse_created_at(data.get("createdAt"))
            if not created or created > cutoff:
                continue
            if self._web_conversation_call(data.get("id"), "stop"):
                stopped += 1
        return stopped

    def daily_chat_web(self, prompt=None, trigger="unknown"):
        """网页通道的每日活跃会话（建会话 → 接沙箱 → 跑完一轮）。"""
        if self.realm != "intl":
            return {"ok": False, "error": "web daily chat is only for international accounts"}
        res = self._daily_chat_web_upstream(prompt)
        if trigger:
            _record_activity(self, "daily_chat", trigger, res)
        return res

    def _daily_chat_web_upstream(self, prompt=None):
        """按候选模型顺序重试网页通道；业务拒绝不重试。

        一次打卡 = 一个单账号预算 + 一个有序候选序列。每轮最多等「单轮上限」
        与「剩余预算」里较小的那个；建会话失败后的退避也从同一个预算里扣。
        轮数由候选数量推出（至少两轮），预算耗尽必定给出明确结论。
        业务拒绝（建会话返回非 0 code）换模型也是同样结果，直接返回；网络、
        超时、5xx、429、沙箱未就绪属于可重试。
        """
        models = self.web_fallback_models()
        if not models:
            models = [get_realm_config(self.realm)["daily_chat_model"]]
        turn_cap, rounds = self.daily_chat_web_policy()
        budget = self.daily_chat_budget()
        deadline = time.time() + budget if budget > 0 else None
        chosen_prompt = prompt or self.daily_chat_web_prompt()
        tried = []
        last = None
        budget_hit = False
        # 开跑前先收上一轮卡住留下的会话，别让活跃名额被一直占着。
        try:
            self.web_conversation_reclaim(max_age=turn_cap * WEB_LIVE_STALE_FACTOR)
            self.web_conversation_sweep_orphans()
        except Exception:
            pass
        for index in range(rounds):
            wait = turn_cap
            if deadline is not None:
                remaining = deadline - time.time()
                if remaining < WEB_BUDGET_MIN_ROUND:
                    budget_hit = True
                    break
                wait = min(turn_cap, int(remaining + 0.999))
            model = models[index % len(models)]
            res = self._daily_chat_web_once(
                chosen_prompt, wait_seconds=wait, model=model)
            res["attempts"] = index + 1
            res["models_tried"] = tried + [model]
            res["model"] = model
            if res.get("ok"):
                return res
            last = res
            if not res.get("retryable"):
                return res
            tried.append(model)
            if index + 1 >= rounds:
                break
            self._web_retry_pause(res, index, deadline=deadline)
            if deadline is not None and deadline - time.time() < WEB_BUDGET_MIN_ROUND:
                budget_hit = True
                break
        if last is None:
            return {"ok": False, "phase": "budget", "budget_exhausted": True,
                    "attempts": 0,
                    "error": "单账号预算 %ds 不足一轮（至少需要 %ds 秒）"
                             % (budget, WEB_BUDGET_MIN_ROUND)}
        if budget_hit:
            last = dict(last)
            last["phase"] = "budget"
            last["budget_exhausted"] = True
            last["error"] = ("单账号预算 %ds 用尽（尝试 %d 轮，最后状态 %s）：%s"
                             % (budget, len(tried), last.get("status") or "未知",
                                last.get("error") or "会话没有跑完"))
        return last

    def _web_retry_pause(self, res, round_index, deadline=None):
        """还没跑到 turn 就失败时补一段退避，返回实际等了多少秒。

        跑过 turn 的轮次已经把等待预算（wait_seconds）花掉了，再睡一次就是双重
        惩罚；而建会话 / 取沙箱失败只花掉几百毫秒，背靠背重试会把所有尝试挤进
        同一个上游故障窗口。phase 缺失时按「已跑到 turn」处理，旧调用方与测试
        桩返回的结果形状因此保持原样。给了 deadline 时退避不能睡过总预算。
        """
        if res.get("phase") not in ("create", "session"):
            return 0.0
        delay = web_retry_backoff(round_index,
                                  base=self.daily_chat_web_retry_backoff())
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.time()))
        if delay > 0:
            time.sleep(delay)
        return delay

    def daily_chat_web_retry_backoff(self):
        """建会话 / 取沙箱阶段失败后的退避基数（秒）。设置页改过就按设置页的来。

        没配过时用内置默认 WEB_RETRY_BACKOFF —— 它吃 WB_WEB_RETRY_BACKOFF
        环境变量，别让设置项把它悄悄顶掉。没配 settings 的账号（单测里手工
        构造的）同样按内置默认走。0 = 不退避（旧行为）。
        """
        if not self.path:
            return WEB_RETRY_BACKOFF
        return settings.daily_chat_web_retry_backoff(
            os.path.dirname(self.path), default=WEB_RETRY_BACKOFF)

    def _daily_chat_web_once(self, prompt=None, wait_seconds=None, model=None):
        """网页通道的一轮尝试；retryable 表示这次失败值不值得再试。"""
        cfg = get_realm_config(self.realm)
        chosen_prompt = prompt or self.daily_chat_web_prompt()
        model = model or self.daily_chat_model() or cfg["daily_chat_model"]
        body = {
            "prompt": chosen_prompt,
            "model": model,
            "conversationOrigin": "workbuddy-app",
            "plugins": [{"name": "weixinpay", "marketplace": "codebuddy-builtin"}],
        }
        conversation, failure = self._web_conversation_create(body)
        if failure and failure.get("limit"):
            # 账号攒满了活跃会话：旧实现每跑一次就漏一条、从不清尾，攒满十天后
            # 连建都建不出来。先停掉最旧的本网关会话腾名额再建一次；腾不出来
            # 就直接说明，不再拿重试次数去撞同一堵墙。
            freed = self.web_conversation_prune()
            if freed:
                conversation, failure = self._web_conversation_create(body)
            if failure:
                hint = ("已自动结束 %d 条旧会话" % freed) if freed \
                    else "没有可自动结束的旧会话"
                return {"ok": False,
                        "error": "活跃会话已达上限（%d）：%s；请到网页端结束或删除"
                                 "旧对话后重试" % (WEB_CONVERSATION_ACTIVE_LIMIT, hint),
                        "retryable": False, "phase": "create"}
        if failure:
            return {"ok": False, "error": failure.get("message") or "建会话失败",
                    "retryable": bool(failure.get("retryable")), "phase": "create"}
        keep = False
        # 建出来就先登记：万一这一轮卡在 socket 上走不到 finally，别的线程
        # 还能按这张表替它收尾。
        web_live_register(self.uid, conversation, model)
        try:
            try:
                session = (self._web_conversation_get(conversation, "/session") or {}).get("data") or {}
            except Exception as exc:
                return {"ok": False, "conversation": conversation,
                        "error": "session 查询失败: %s" % exc, "retryable": True,
                        "phase": "session"}
            link = session.get("link") or session.get("endpoint") or ""
            token = session.get("token") or ""
            session_id = session.get("sessionId") or session.get("session_id") or conversation
            cwd = session.get("cwd") or "/workspace"
            if not link or not token:
                return {"ok": False, "conversation": conversation,
                        "error": "沙箱未就绪（没有 link/token）", "retryable": True,
                        "phase": "session"}
            from core import webagent
            result = webagent.run_turn(
                link, token, session_id, cwd,
                chosen_prompt,
                cfg.get("web_ua"),
                poll_status=lambda: self._web_conversation_status(conversation),
                wait_seconds=int(wait_seconds or cfg.get("web_turn_timeout") or 120),
                proxy=self.proxy,
                model=model)
            result["conversation"] = conversation
            result["phase"] = "turn"
            if result.get("ok"):
                keep = True
                result["msg"] = "网页通道会话跑完：%d 段输出，%d ms" % (
                    result.get("chunks") or 0, result.get("elapsed_ms") or 0)
            else:
                result["retryable"] = True
            return result
        finally:
            # 收尾必须发生：不 stop 的话这条会话会一直占着上游的活跃名额，
            # 跑够十条这个账号就再也建不出会话（429 / 10105）。成功的一轮保留
            # 记录（stop 只把状态改成 completed），失败的一轮直接删掉，免得
            # 网页端历史里堆满提示词。
            try:
                self.web_conversation_release(conversation, delete=not keep)
            finally:
                web_live_unregister(self.uid, conversation)

    def _web_conversation_create(self, body):
        """建一条网页会话；返回 (会话 id, 失败信息)。

        失败信息是 {"message": ..., "retryable": bool, "limit": bool}，
        limit 表示「活跃会话已满」——调用方会先清理再重试一次。
        """
        cfg = get_realm_config(self.realm)
        req = urllib.request.Request(
            cfg["web_conversations_url"],
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self.web_headers(), method="POST")
        try:
            with net.urlopen(req, timeout=30, proxy=self.proxy) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                detail = str(exc)
            return None, {
                "message": "HTTP %d: %s" % (exc.code, detail[:120]),
                "retryable": exc.code >= 500 or exc.code in (408, 429),
                "limit": active_conversation_limit(exc.code, detail),
            }
        except Exception as exc:
            return None, {"message": str(exc), "retryable": True, "limit": False}
        if not isinstance(payload, dict):
            return None, {"message": "unexpected response", "retryable": True,
                          "limit": False}
        conversation = (payload.get("data") or {}).get("id")
        if payload.get("code") not in (0, None) or not conversation:
            detail = "code=%s msg=%s" % (payload.get("code"), payload.get("msg"))
            return None, {"message": detail, "retryable": False,
                          "limit": active_conversation_limit(429, detail)}
        return conversation, None

    def _web_conversation_get(self, conversation, suffix=""):
        cfg = get_realm_config(self.realm)
        url = cfg["web_conversations_url"] + urllib.parse.quote(str(conversation)) + suffix
        req = urllib.request.Request(url, headers=self.web_headers(), method="GET")
        with net.urlopen(req, timeout=30, proxy=self.proxy) as resp:
            return json.loads(resp.read().decode("utf-8", "replace") or "{}")

    def _web_conversation_status(self, conversation):
        try:
            payload = self._web_conversation_get(conversation)
        except Exception:
            return ""
        data = payload.get("data") if isinstance(payload, dict) else None
        return str((data or {}).get("status") or "")

    def sync_nickname(self):
        """手动同步网页控制台昵称（只取 uid 与昵称，uid 对不上直接报错）。"""
        cfg = get_realm_config(self.realm)
        if not cfg.get("profile_path"):
            return ""
        url = (cfg.get("chat_upstream") or "").rstrip("/") + cfg["profile_path"]
        headers = self.headers(purpose="billing")
        headers["X-Client-Platform"] = "web"
        payload = net.http_json(url, method="GET", headers=headers, timeout=15)
        data = payload.get("data") or payload
        uid = str(data.get("uid") or data.get("userId") or "")
        if uid and uid != self.uid:
            raise RuntimeError("昵称接口返回的 uid 与账号不一致，已放弃同步")
        nickname = str(data.get("nickname") or data.get("userNickname") or "")
        if nickname and nickname != self.nickname:
            self.nickname = nickname
            if self.accounts_dir:
                self.save(self.accounts_dir)
        return nickname

    # ------------------------------------------------------------ 余额
    def is_enterprise(self):
        return bool(self.enterprise_id or jwt_enterprise_id(self.access_token))

    def fetch_credits(self, force=False):
        """刷新余额；显示又有积分了 → 抬出 402 停车（不动限流冷却）。

        渠道注入 credits_fn 时余额查询完全由渠道实现（含把不限量哨兵 -1
        视为「有额度」的语义，见 revive_balance_cooldown）。
        """
        with self._credits_lock:
            cfg = get_realm_config(self.realm)
            injected = cfg.get("credits_fn")
            if callable(injected):
                try:
                    res = injected(self, force=force)
                except Exception as exc:
                    res = {"ok": False, "error": str(exc)}
            else:
                res = self._fetch_credits_raw()
            if isinstance(res, dict) and res.get("ok"):
                if self.revive_balance_cooldown():
                    res["revived"] = True
            return res

    def _fetch_credits_raw(self):
        cfg = get_realm_config(self.realm)
        try:
            res = self._fetch_credits_detailed(cfg)
            if res.get("ok") and not (self.credits or {}).get("size"):
                if self.is_enterprise():
                    ent = self._fetch_credits_enterprise(cfg)
                    if ent.get("ok"):
                        return ent
            if res.get("ok"):
                return res
        except Exception as exc:
            last = exc
        if self.is_enterprise():
            try:
                ent = self._fetch_credits_enterprise(cfg)
                if ent.get("ok"):
                    return ent
            except Exception:
                pass
        return {"ok": False, "error": "余额查询失败"}

    def _fetch_billing_summary(self, cfg):
        """读计费摘要（付费标记 + 套餐名）；接口缺失/失败返回 None。"""
        path = str(cfg.get("resource_summary_path") or "").strip()
        if not path:
            return None
        headers = self.headers(purpose="billing")
        headers["X-Client-Platform"] = "web"
        try:
            res = net.http_json(cfg["billing_upstream"] + path, data=b"{}",
                                method="POST", headers=headers, timeout=10)
        except Exception:
            return None
        return tier_from_summary(res.get("data") if isinstance(res, dict) else None)

    def _fetch_credits_detailed(self, cfg):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        body = {
            "PageNumber": 1,
            "PageSize": 100,
            "ProductCode": "p_tcaca",
            "Status": [0, 3],
            "PackageEndTimeRangeBegin": now,
            "PackageEndTimeRangeEnd": "2036-01-01 00:00:00",
        }
        url = cfg["billing_upstream"] + cfg["credits_path"]
        headers = self.headers(purpose="billing")
        res = net.http_json(url, data=json.dumps(body).encode(), method="POST",
                            headers=headers, timeout=30)
        data = res.get("data", {}).get("Response", {}).get("Data", {})
        accounts = data.get("Accounts") or []
        tot_remain = tot_used = tot_size = 0
        packages = []
        for a in accounts:
            pkg_name = a.get("PackageName") or "Package"
            pkg_code = a.get("PackageCode") or ""
            if a.get("CycleCapacitySize", 0) > 0:
                remain = a.get("CycleCapacityRemain", 0)
                size = a.get("CycleCapacitySize", 0)
                used = max(0, size - remain)
                if a.get("CycleCapacityUsed", 0) > used:
                    used = a["CycleCapacityUsed"]
                    remain = max(0, size - used)
            else:
                remain = a.get("CapacityRemain", 0)
                used = a.get("CapacityUsed", 0)
                size = a.get("CapacitySize", 0)
            tot_remain += remain
            tot_used += used
            tot_size += size
            # 到期认「抵扣截止时间」而不是周期结束时间：免费包/体验版的
            # CycleEndTime 只是每月计费周期边界，积分未必作废。730 天以上视为
            # 不会真到期，不参与到期倒计时。
            raw_end = a.get("DeductionEndTime") or a.get("CycleEndTime") \
                or a.get("ExpiredTime") or ""
            days_left, is_expired, no_expiry = None, False, False
            expire_time = ""
            if raw_end:
                try:
                    stamp = float(raw_end)
                    expire_time = time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(normalize_epoch(stamp)))
                except (TypeError, ValueError, OSError):
                    expire_time = str(raw_end)
                try:
                    end_ts = time.mktime(time.strptime(expire_time, "%Y-%m-%d %H:%M:%S"))
                    diff_sec = end_ts - time.time()
                    if diff_sec > 730 * 86400.0:
                        no_expiry = True
                    else:
                        days_left = round(diff_sec / 86400.0, 1)
                        is_expired = diff_sec < 0
                except Exception:
                    pass
            packages.append({"name": pkg_name, "package_code": pkg_code,
                             "remain": remain, "used": used, "size": size,
                             "expire_time": expire_time,
                             "days_left": days_left, "is_expired": is_expired,
                             "no_expiry": no_expiry})
        previous = self.credits if isinstance(self.credits, dict) else None
        prev_remain = previous.get("remain") if previous else None
        # 套餐接口本身不带付费标记；汇总接口才有 IsPaidUser 与套餐名。查不到就
        # 沿用上一次的快照，不能把已知的付费账号悄悄降成免费；档位记录同理——
        # 只有拿到新鲜摘要才覆盖（见 tier_from_summary / public 的 tier）。
        summary = self._fetch_billing_summary(cfg)
        if summary is not None:
            self.tier = summary
        paid = summary.get("paid") if summary else None
        if paid is None:
            paid = bool(previous.get("is_paid_user")) if previous else False
        self.credits = {
            "remain": tot_remain,
            "used": tot_used,
            "size": tot_size,
            "is_paid_user": bool(paid),
            "packages": packages,
            "updated_at": time.time(),
            "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.is_paid_user = bool(self.credits.get("is_paid_user"))
        with _credits_lock:
            _credits_cache[self.uid] = (time.time(), self.credits)
        if self.accounts_dir:
            self.save(self.accounts_dir)
        if isinstance(prev_remain, (int, float)):
            delta = int(tot_remain) - int(prev_remain)
            if 0 < delta <= 1000000:
                _record_credit_delta(self, delta, int(prev_remain), int(tot_remain))
        return {"ok": True, "credits": self.credits}

    def _fetch_credits_enterprise(self, cfg):
        url = cfg["billing_upstream"] + cfg["enterprise_usage_path"]
        headers = self.headers(purpose="billing")
        headers["X-Client-Platform"] = "web"
        res = net.http_json(url, data=b"{}", method="POST", headers=headers, timeout=15)
        data = res.get("data") or {}
        try:
            used = round(float(data.get("credit") or 0), 2)
        except (TypeError, ValueError):
            used = 0.0
        try:
            size = round(float(data.get("limitNum") or 0), 2)
        except (TypeError, ValueError):
            size = 0.0
        remain = round(max(0.0, size - used), 2) if size > 0 else 0.0
        previous = self.credits if isinstance(self.credits, dict) else None
        prev_remain = previous.get("remain") if previous else None
        self.credits = {
            "remain": remain,
            "used": used,
            "size": size,
            "is_paid_user": True,
            "is_enterprise": True,
            "packages": ([{
                "name": "企业周期额度" if size else "企业额度",
                "remain": remain, "used": used, "size": size,
                "cycle_start_time": str(data.get("cycleStartTime") or ""),
                "cycle_end_time": str(data.get("cycleEndTime")
                                      or data.get("cycleResetTime") or ""),
            }] if size > 0 else []),
            "updated_at": time.time(),
            "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.is_paid_user = bool(self.credits.get("is_paid_user"))
        with _credits_lock:
            _credits_cache[self.uid] = (time.time(), self.credits)
        if self.accounts_dir:
            self.save(self.accounts_dir)
        if isinstance(prev_remain, (int, float)):
            delta = int(remain) - int(prev_remain)
            if 0 < delta <= 1000000:
                _record_credit_delta(self, delta, int(prev_remain), int(remain))
        return {"ok": True, "credits": self.credits}

    # ------------------------------------------------------------ 惩罚记录
    def note_error(self, message, cooldown=60, single_account=False, model=None,
                   until=None, detail=None):
        with self._throttle_lock:
            self.last_error = str(message)[:200]
            self.last_error_detail = str(detail)[:2000] if detail else ""
            if _auth_failure_text(message):
                self.token_expired = True
            if model:
                wait = max(1.0, float(until) - time.time()) if until else (
                    3.0 if single_account else float(cooldown))
                now = time.time()
                self.model_cooldowns[model] = now + wait
                self.model_cooldowns_at[model] = now
                return
            actual = 3 if single_account else cooldown
            self.cooldown_until = time.time() + actual

    def note_balance_cooled(self, message="余额不足（402）", detail=None):
        until = next_local_4am()
        with self._throttle_lock:
            self.last_error = str(message)[:200]
            self.last_error_detail = str(detail)[:2000] if detail else ""
            self.balance_until = max(self.balance_until, until)
        return until

    def revive_balance_cooldown(self):
        """余额刷新显示又有积分了：只解除 402 停车，限流/模型冷却原样保留。

        remain = -1 是渠道上报的「不限量」哨兵，同样视为有额度。
        """
        if not self.balance_until:
            return False
        credits = self.credits if isinstance(self.credits, dict) else {}
        try:
            remain = int(credits.get("remain"))
        except (TypeError, ValueError):
            remain = None
        if remain is None or (remain <= 0 and remain != -1):
            return False
        with self._throttle_lock:
            self.balance_until = 0.0
            self.last_error = ""
            self.last_error_detail = ""
        return True

    def _decay_soft_streak(self):
        now = time.time()
        if self.last_soft_at and now - self.last_soft_at > FAIL_WINDOW:
            self.soft_streak = 0
            self.unscoped_streak = 0
        self.last_soft_at = now

    def note_soft_rate(self, message):
        """账号级限流：600s 起翻倍，封顶 2h。"""
        with self._throttle_lock:
            self._decay_soft_streak()
            self.soft_streak += 1
            wait = soft_backoff(self.soft_streak)
            self.last_error = str(message)[:200]
            self.cooldown_until = max(self.cooldown_until, time.time() + wait)
        return wait

    def note_unscoped_rate(self, model):
        """无作用域 429：独立计数，只锁单模型（60s 起封顶 10min）。"""
        with self._throttle_lock:
            self._decay_soft_streak()
            self.unscoped_streak += 1
            return unverified_soft_backoff(self.unscoped_streak)

    def note_failure(self, message):
        with self._throttle_lock:
            self.last_error = str(message)[:200]
            now = time.time()
            if self.last_fail_at and now - self.last_fail_at > FAIL_WINDOW:
                self.fails = 0
            self.last_fail_at = now
            self.fails += 1
            if self.fails >= BREAKER_THRESHOLD:
                self.breaker_until = max(self.breaker_until,
                                         now + breaker_backoff(self.fails))
        return self.breaker_until

    def note_unknown_failure(self, message):
        with self._throttle_lock:
            self.last_error = str(message)[:200]
            now = time.time()
            if self.last_fail_at and now - self.last_fail_at > FAIL_WINDOW:
                self.fails = 0
                self.degrade_count = 0
            self.last_fail_at = now
            self.degrade_count += 1
            self.fails += 1
            if self.degrade_count >= DEGRADE_THRESHOLD:
                self.degrade_until = max(self.degrade_until,
                                         now + degrade_backoff(self.degrade_count))
            if self.fails >= BREAKER_THRESHOLD:
                self.breaker_until = max(self.breaker_until,
                                         now + breaker_backoff(self.fails))
        return self.degrade_until

    def note_success(self, model=None):
        """成功服务一次：清掉账号级惩罚（402 停车除外，等余额刷新抬）。

        持久化的风控限制（restricted_until）也一并清：真正跑成功的一次请求就是
        「上游已解除限令」的唯一实证。正常调度不会挑受限账号，所以这里只会在
        手动测试时触发；令牌过期标记同样清除（exp 校验仍兜底真过期的令牌）。
        """
        with self._throttle_lock:
            if model:
                self.model_cooldowns.pop(model, None)
                self.model_cooldowns_at.pop(model, None)
            self.soft_streak = 0
            self.unscoped_streak = 0
            self.fails = 0
            self.degrade_count = 0
            self.breaker_until = 0.0
            self.degrade_until = 0.0
            self.restricted_until = 0.0
            self.token_expired = False
            self.last_error = ""
            self.last_error_detail = ""
            self.cooldown_until = 0.0

    def throttle_wait(self, model=None):
        if not self.enabled or not self.access_token:
            return 0.0
        now = time.time()
        with self._throttle_lock:
            wait = max(0.0, self.cooldown_until - now,
                       self.balance_until - now,
                       self.breaker_until - now,
                       self.degrade_until - now,
                       self.restricted_until - now)
            if model:
                wait = max(wait, max(0.0, self.model_cooldowns.get(model, 0.0) - now))
        return wait

    def note_restricted(self, detail="", cooldown=None):
        """记录一次上游风控限制（403 / code 11140），返回限制到期 epoch。

        - 冷却默认 RESTRICTED_ACCOUNT_COOLDOWN（与 wb 上游同款 2h 起步）；
        - last_error 写明受限（面板与 unavailable_reason 都能看到）；
        - 到期时间**只延不清**：反复探测不会把一次限制无限续期（restricted_
          until <= now 才重新起算）；
        - 持久化到凭据档（restrictedUntil）：重启 / 刷新 token / 换身分 /
          401 治理都不清它——限令在服务端，本地只有余额恢复类信号能抬出
          （见 note_success）。
        """
        wait = RESTRICTED_ACCOUNT_COOLDOWN if cooldown is None else float(cooldown)
        with self._throttle_lock:
            self.last_error = "HTTP 403 (account restricted)"
            self.last_error_detail = str(detail)[:2000] if detail else ""
            now = time.time()
            if self.restricted_until <= now:
                self.restricted_until = now + max(1.0, wait)
        return self.restricted_until

    def clear_error(self, model=None):
        if model:
            with self._throttle_lock:
                self.model_cooldowns.pop(model, None)
                self.model_cooldowns_at.pop(model, None)
            return
        with self._throttle_lock:
            self.model_cooldowns.clear()
            self.model_cooldowns_at.clear()
            self.last_error = ""
            self.last_error_detail = ""
            self.cooldown_until = 0.0
            self.balance_until = 0.0


def _record_credit_delta(account, delta, before, after):
    try:
        from tasks import taskstore
        taskstore.add_log(
            kind="credit", uid=account.uid, nickname=account.nickname,
            source="auto", realm=account.realm, level="credit", credits=delta,
            message="余额 +%d（%d → %d）" % (delta, before, after))
    except Exception:
        pass


def _record_activity(account, task, trigger, result):
    """写一条签到/打卡活动历史；活动模块不可用时静默跳过。"""
    try:
        from infra import activity
        activity.record_attempt(account, task, trigger, result)
    except Exception:
        pass


def fetch_credits_cached(account, force=False):
    """带短缓存的余额查询：面板 60 秒内重复查询直接复用。"""
    now = time.time()
    with _credits_lock:
        hit = _credits_cache.get(account.uid)
    if hit and not force and now - hit[0] < CREDITS_TTL:
        return {"ok": True, "credits": hit[1], "cached": True,
                "cacheAge": round(now - hit[0], 1)}
    return account.fetch_credits(force=force)


def fetch_credits_recovering(account, force=False):
    """面板余额刷新专用：取余额成功即视为余额恢复，解除 402 停车冷却。
    与 fetch_credits_cached 的区别仅在恢复语义——预热等只读场景勿用。"""
    res = fetch_credits_cached(account, force=force)
    if res.get("ok"):
        account.revive_balance_cooldown()
    return res


def has_realm_checkin(realm):
    """该出口的渠道是否声明了每日签到（面板/任务链共用判定）。"""
    cfg = REALM_CONFIGS.get(str(realm or "")) or {}
    return cfg.get("has_checkin") is True


class SessionAffinity(object):
    def __init__(self, ttl=7200, max_entries=5000):
        self.ttl = ttl
        self.max_entries = max_entries
        self.bindings = {}
        self._lock = threading.Lock()

    def get(self, key):
        if not key:
            return None
        with self._lock:
            entry = self.bindings.get(key)
            if not entry:
                return None
            uid, exp = entry
            if time.time() > exp:
                self.bindings.pop(key, None)
                return None
            self.bindings[key] = (uid, time.time() + self.ttl)
            return uid

    def bind(self, key, uid):
        if not key or not uid:
            return
        with self._lock:
            if len(self.bindings) >= self.max_entries:
                now = time.time()
                self.bindings = {k: v for k, v in self.bindings.items() if v[1] > now}
            self.bindings[key] = (uid, time.time() + self.ttl)

    def unbind(self, key):
        if not key:
            return
        with self._lock:
            self.bindings.pop(key, None)


class AccountPool(object):
    def __init__(self, directory, log=None):
        self.dir = directory
        self.log = log or (lambda msg: None)
        self.accounts = []
        self.logins = {}
        self._lock = threading.RLock()
        self._cursor = 0
        # 人工权重（>1）的平滑加权轮询状态：uid -> 累计权重
        self._manual_weights = {}
        self.affinity = SessionAffinity()
        # 账号级并发名额：uid -> 在途 chat 请求数。本线程占的名额另记在线程
        # 本地的账本里，请求收尾一次还清（见 reserve / release_request_slots）。
        self._inflight = {}
        self._inflight_lock = threading.Lock()
        self._local = threading.local()

    def load(self):
        with self._lock:
            self.accounts = []
            if not os.path.isdir(self.dir):
                return self.accounts
            for name in sorted(os.listdir(self.dir)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(self.dir, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        account = Account(json.load(fh), path)
                except Exception as exc:
                    self.log("account %s unreadable: %s" % (name, exc))
                    continue
                if account.uid:
                    self.accounts.append(account)
            return self.accounts

    def list_public(self, realm=None):
        with self._lock:
            accs = [a for a in self.accounts if not realm or a.realm == realm]
            return [a.public() for a in accs]

    def get(self, uid):
        with self._lock:
            for account in self.accounts:
                if account.uid == uid:
                    return account
        return None

    def add(self, account):
        with self._lock:
            existing = self.get(account.uid)
            if existing is not None:
                account.added_at = existing.added_at
                account.path = existing.path
                for field in ("credits", "last_checkin", "last_daily_chat",
                              "last_activity_report"):
                    if not getattr(account, field, None) and getattr(existing, field, None):
                        setattr(account, field, getattr(existing, field))
                self.accounts[self.accounts.index(existing)] = account
            else:
                self.accounts.append(account)
            account.save(account.accounts_dir or self.dir)
            return account

    def remove(self, uid):
        with self._lock:
            account = self.get(uid)
            if account is None:
                return False
            account.delete()
            self.accounts.remove(account)
            return True

    def set_enabled(self, uid, enabled):
        account = self.get(uid)
        if account is None:
            return None
        account.enabled = bool(enabled)
        if enabled:
            account.clear_error()
        account.save(self.dir)
        return account.public()

    def set_all_enabled(self, enabled, realm=None):
        with self._lock:
            for account in self.accounts:
                if realm and account.realm != realm:
                    continue
                account.enabled = bool(enabled)
                if enabled:
                    account.clear_error()
                account.save(self.dir)

    def set_weight(self, uid, weight):
        account = self.get(uid)
        if account is None:
            return None
        try:
            account.weight = max(1, min(100, int(weight)))
        except (TypeError, ValueError):
            return None
        account.save(self.dir)
        return account.public()

    def set_disabled_models(self, uid, models):
        account = self.get(uid)
        if account is None:
            return None
        account.disabled_models = normalise_disabled_models(models)
        account.save(self.dir)
        return account.public()

    def set_note(self, uid, note):
        account = self.get(uid)
        if account is None:
            return None
        account.note = (note if isinstance(note, str) else "").strip()[:200]
        account.save(self.dir)
        return account.public()

    def apply_proxy_slots(self, slots):
        """按出口解析代理：每个出口「启用中」的第一条槽，即该出口全部账号
        的统一代理；出口没有启用槽（或只有未分配的旧版全局槽）时走直连。

        代理是出口级配置——「国际版走代理、其他出口直连」靠槽的 realm 归属
        隔离，不按账号拆分；顶栏切换到没配槽的出口，那个出口的账号全部直连。
        """
        by_realm = {}
        for entry in slots or []:
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                continue
            realm = str(entry.get("realm") or "")
            if not realm or realm in by_realm:
                continue
            by_realm[realm] = str(entry.get("url") or "")
        with self._lock:
            for account in self.accounts:
                account.proxy = by_realm.get(account.realm, "") or account.proxy_legacy

    def count_ready(self, realm=None, model=None):
        with self._lock:
            snapshot = [a for a in self.accounts if not realm or a.realm == realm]
        return sum(1 for a in snapshot if a.ready(model=model))

    # ── 账号级并发名额（account_max_concurrent）────────────────────
    def slot_limit(self):
        """单账号同时在途的 chat 请求上限；0 = 不限（默认）。"""
        try:
            return settings.account_max_concurrent(self.dir)
        except Exception:
            return 0

    def reserve(self, account):
        """给这个账号占一个在途名额；上限关闭时恒真且不记账。

        名额按请求记账：本线程占的记在线程本地的账本里，请求收尾时由
        release_request_slots() 一次还清；换号重试中途弃用的账号在 pick 里按
        exclude 当场还回（见 _release_excluded）。
        """
        limit = self.slot_limit()
        if limit <= 0:
            return True
        uid = str(getattr(account, "uid", "") or "")
        if not uid:
            return True
        with self._inflight_lock:
            current = self._inflight.get(uid, 0)
            if current >= limit:
                return False
            self._inflight[uid] = current + 1
        held = self._thread_held()
        held[uid] = held.get(uid, 0) + 1
        return True

    def release_uid(self, uid):
        """还回本线程给这个账号占的名额；没占过就是空操作（绝不记成负数）。"""
        held = self._thread_held()
        if not held.get(uid):
            return False
        if held[uid] <= 1:
            held.pop(uid, None)
        else:
            held[uid] -= 1
        with self._inflight_lock:
            current = self._inflight.get(uid, 0)
            if current <= 1:
                self._inflight.pop(uid, None)
            else:
                self._inflight[uid] = current - 1
        return True

    def release_request_slots(self):
        """一次请求收尾：还回本线程占的全部名额（一个请求一条线程）。"""
        for uid in list(self._thread_held()):
            self.release_uid(uid)

    def inflight_snapshot(self):
        """此刻每个账号有几个在途请求；上限关闭时不记账，返回空。"""
        with self._inflight_lock:
            return dict(self._inflight)

    def _thread_held(self):
        held = getattr(self._local, "held", None)
        if held is None:
            held = {}
            self._local.held = held
        return held

    def _release_excluded(self, exclude):
        """调用方已判死的候选：把它们占的名额当场还回去。"""
        if not exclude:
            return
        for uid in list(self._thread_held()):
            if uid in exclude:
                self.release_uid(uid)

    def _slot_busy_error(self):
        """全部可用账号都满员：报 429，而不是「没有可用账号」。"""
        limit = self.slot_limit()
        reason = ("every usable account is already serving %d concurrent "
                  "request(s) (account_max_concurrent=%d); retry shortly or "
                  "raise the cap" % (limit, limit))
        return ratelimit.RateLimited(None, reason, wait=1, message=reason)

    def pick_for_session(self, realm=None, session_key=None, exclude=None, model=None):
        exclude = exclude or set()
        if session_key:
            bound_uid = self.affinity.get(session_key)
            if bound_uid and bound_uid not in exclude:
                account = self.get(bound_uid)
                if account and account.realm == realm and account.ready(model=model):
                    if self.reserve(account):
                        return account
                    # 名额满了：临时溢出到别的号，绑定留着 —— 下一轮还能回到它
                    return self.pick(realm=realm, exclude=exclude, model=model,
                                     reserve=True)
                self.affinity.unbind(session_key)
        account = self.pick(realm=realm, exclude=exclude, model=model, reserve=True)
        if account and session_key:
            self.affinity.bind(session_key, account.uid)
        return account

    def pick(self, realm=None, exclude=None, model=None, reserve=False):
        """挑一个账号；reserve=True 时同时占它的并发名额（派发路径用）。

        上限关着（默认 0）时 reserve 恒真且不记账，选号行为与改动前一字不差；
        全部可用账号都满员时报 429 —— 账号本身完全健康，只是每个都在跑别的
        请求，运营者要做的是等一两秒重发或把上限调大，而不是去看账号状态。
        """
        exclude = exclude or set()
        self._release_excluded(exclude)
        with self._lock:
            snapshot = [a for a in self.accounts if not realm or a.realm == realm]
            start = self._cursor
        total = len(snapshot)
        if total == 0:
            return None
        # 人工权重 > 1 的账号优先接单，彼此平滑加权轮询；都不可用时落回普通轮询
        account = self._pick_weighted_first(snapshot, exclude, model,
                                            reserve=reserve)
        if account is not None:
            return account
        busy = 0
        for offset in range(total):
            index = (start + offset) % total
            account = snapshot[index]
            if account.uid in exclude:
                continue
            if not account.ready(model=model):
                continue
            if reserve and not self.reserve(account):
                busy += 1
                continue
            with self._lock:
                self._cursor = (index + 1) % total
            return account
        if busy:
            raise self._slot_busy_error()
        return None

    def _pick_weighted_first(self, snapshot, exclude, model, reserve=False):
        limit = self.slot_limit() if reserve else 0
        ready = []
        for account in snapshot:
            if account.uid in exclude:
                continue
            weight = int(getattr(account, "weight", 1) or 1)
            if weight <= 1:
                continue
            if not account.ready(model=model):
                continue
            if limit > 0 and self.inflight_snapshot().get(account.uid, 0) >= limit:
                continue
            ready.append((account, account.uid, weight))
        if not ready:
            return None
        return self._smooth_weighted_pick(ready, "_manual_weights")

    def _smooth_weighted_pick(self, entries, state_name):
        """nginx 平滑加权轮询：每次各加权重，最大者胜出并扣掉总权重。"""
        keys = set(key for _account, key, _weight in entries)
        with self._lock:
            state = {k: v for k, v in getattr(self, state_name).items() if k in keys}
            total = 0
            for _account, key, weight in entries:
                state[key] = state.get(key, 0) + weight
                total += weight
            winner = max(entries, key=lambda item: state.get(item[1], 0))[0]
            state[winner.uid] -= total
            setattr(self, state_name, state)
        return winner

    def representative(self, realm=None):
        with self._lock:
            candidates = [a for a in self.accounts if not realm or a.realm == realm]
            for account in candidates:
                if account.access_token:
                    return account
            return candidates[0] if candidates else None

    # ------------------------------------------------------------ 登录
    def start_login(self, realm="intl", platform="CLI"):
        cfg = get_realm_config(realm)
        url = "%s%s?platform=%s" % (cfg["chat_upstream"], cfg["auth_state_path"],
                                    urllib.parse.quote(str(platform)))
        headers = _auth_base_headers(cfg)
        payload = net.http_json(url, data=b"{}", method="POST", headers=headers,
                                timeout=30, retries=3, log=self.log)
        data = payload.get("data") or {}
        state = data.get("state")
        auth_url = data.get("authUrl")
        if not state or not auth_url:
            raise RuntimeError("auth/state returned no state/authUrl: %s" % payload)
        with self._lock:
            self.logins[state] = {"created": time.time(), "platform": platform,
                                  "realm": realm}
        return {"state": state, "authUrl": auth_url, "realm": realm, "platform": platform}

    def poll_login(self, state):
        state = str(state or "").strip()
        with self._lock:
            info = self.logins.get(state)
        if not info:
            return {"status": "unknown",
                    "message": "state not recognised - start the login again"}
        if time.time() - info["created"] > LOGIN_TTL_SECONDS:
            with self._lock:
                self.logins.pop(state, None)
            return {"status": "expired", "message": "login window expired - start again"}
        realm = info.get("realm") or "intl"
        cfg = get_realm_config(realm)
        url = "%s%s?state=%s" % (cfg["chat_upstream"], cfg["auth_token_path"],
                                 urllib.parse.quote(state))
        headers = _auth_base_headers(cfg)
        try:
            payload = net.http_json(url, method="GET", headers=headers,
                                    timeout=30, retries=2)
        except Exception as exc:
            return {"status": "pending", "message": "poll error: %s" % exc}
        code = payload.get("code")
        if code == LOGIN_PENDING:
            return {"status": "pending",
                    "message": payload.get("msg") or "waiting for browser login"}
        if code != 0:
            return {"status": "error",
                    "message": "code=%s msg=%s" % (code, payload.get("msg"))}
        data = payload.get("data") or {}
        token = data.get("accessToken")
        if not token:
            return {"status": "pending", "message": "waiting for token"}
        uid = jwt_uid(token)
        nickname = ""
        try:
            acct_url = "%s%s?state=%s" % (cfg["chat_upstream"],
                                          cfg["login_account_path"],
                                          urllib.parse.quote(state))
            acct_headers = dict(headers)
            acct_headers["Authorization"] = "Bearer " + token
            req = urllib.request.Request(acct_url, method="GET", headers=acct_headers)
            with net.urlopen(req, timeout=15) as resp:
                profile = json.loads(resp.read().decode("utf-8"))
                profile_data = profile.get("data") or {}
                nickname = str(profile_data.get("nickname") or "")
        except Exception:
            pass
        account = Account({
            "uid": uid,
            "nickname": nickname or uid[:8],
            "domain": data.get("domain") or cfg["domain"],
            "realm": realm,
            "platform": info["platform"],
            "accessToken": token,
            "refreshToken": data.get("refreshToken") or "",
            "expiresAt": normalize_epoch(data.get("expiresAt")) or jwt_exp(token),
            "source": "oauth",
            "enabled": True,
        })
        self.add(account)
        if realm == "cn":
            try:
                account.checkin(trigger="account_add")
            except Exception:
                pass
        with self._lock:
            self.logins.pop(state, None)
        return {"status": "ok", "account": account.public()}

    def cancel_login(self, state):
        with self._lock:
            return self.logins.pop(state, None) is not None

    # ------------------------------------------------------------ 桌面凭据
    def import_desktop_credential(self, path=None, realm=None, source="desktop-app"):
        if not path:
            found = []
            for candidate, candidate_realm in desktop_credential_candidates():
                if realm and candidate_realm != realm:
                    continue
                try:
                    account = self.import_desktop_credential(
                        path=candidate, realm=candidate_realm or None, source=source)
                    if account:
                        found.append(account)
                except Exception:
                    pass
            return found
        with open(path, encoding="utf-8") as fh:
            blob = json.load(fh)
        auth = blob.get("auth") or {}
        profile = blob.get("account") or {}
        try:
            token, key = desktop_decrypt_tokens(auth, log=self.log)
        except _atrest.AtRestError as exc:
            raise RuntimeError(
                "桌面客户端令牌已加密，且无法从运行中的客户端回收密钥（%s）。"
                "请保持 WorkBuddy 桌面端已登录并处于运行状态后重试，或改用 OAuth 登录。"
                % exc)
        if not token:
            raise RuntimeError("no accessToken in %s" % path)
        detected_realm = realm or detect_realm_from_token(token, auth.get("domain"))
        cfg = get_realm_config(detected_realm)
        nickname = profile.get("nickname")
        if key is not None and _atrest.is_envelope(nickname):
            nickname = _atrest.decrypt_field(key, nickname) or ""
        account = Account({
            "uid": profile.get("uid") or jwt_uid(token),
            "nickname": nickname if isinstance(nickname, str) else "",
            "domain": auth.get("domain") or cfg["domain"],
            "realm": detected_realm,
            "platform": "CLI",
            "enterpriseId": profile.get("enterpriseId") or "",
            "accessToken": token,
            "refreshToken": desktop_refresh_token(auth, key),
            "expiresAt": normalize_epoch(auth.get("expiresAt")) or jwt_exp(token),
            "source": source,
            "enabled": True,
        })
        self.add(account)
        if detected_realm == "cn":
            try:
                account.checkin(trigger="account_import")
            except Exception:
                pass
        return account


# ---------------------------------------------------------------- 桌面凭据
def desktop_auth_dirs():
    """桌面客户端凭据目录（可由环境变量 WB_DESKTOP_AUTH_DIRS 覆盖，分号分隔）。"""
    raw = os.environ.get("WB_DESKTOP_AUTH_DIRS") or ""
    if raw:
        return [item for item in raw.split(os.pathsep) if item]
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        return [os.path.join(local, "CodeBuddyExtension", "Data", "Public", "auth")]
    return []


def desktop_credential_candidates():
    """[(path, realm)]：桌面端可导入的凭据文件（realm 可能为空，交加载时判定）。"""
    out = []
    for directory in desktop_auth_dirs():
        if not directory or not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".info"):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    blob = json.load(fh)
            except Exception:
                continue
            auth = blob.get("auth") or {}
            realm = realm_evidence(str(auth.get("accessToken") or ""),
                                   auth.get("domain")) or ""
            out.append((path, realm))
    return out


def desktop_decrypt_tokens(auth, log=None):
    """返回 (accessToken, at-rest key)；明文旧文件原样通过。"""
    token = auth.get("accessToken") or ""
    if not _atrest.is_envelope(token):
        return token, None
    key = _atrest.recover_key(log=log)
    return _atrest.decrypt_field(key, token), key


def desktop_refresh_token(auth, key):
    value = auth.get("refreshToken") or ""
    if key is not None and _atrest.is_envelope(value):
        return _atrest.decrypt_field(key, value) or ""
    return value


def scan_desktop_credentials():
    """只读扫描：列出本机桌面凭据（不导入）。"""
    out = []
    for path, realm in desktop_credential_candidates():
        try:
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
            auth = blob.get("auth") or {}
            profile = blob.get("account") or {}
            token = auth.get("accessToken") or ""
            encrypted = _atrest.is_envelope(token)
            out.append({
                "path": path,
                "file": os.path.basename(path),
                "realm": realm or "",
                "uid": str(profile.get("uid") or ""),
                "nickname": (profile.get("nickname")
                             if isinstance(profile.get("nickname"), str) else ""),
                "domain": str(auth.get("domain") or ""),
                "encrypted": encrypted,
                "valid": bool(token) and not encrypted,
                "usable": bool(token),
            })
        except Exception as exc:
            out.append({"path": path, "file": os.path.basename(path),
                        "valid": False, "error": str(exc)[:120]})
    return out
