# -*- coding: utf-8 -*-
"""core/ratelimit.py —— 429/402 形态判定与产品自动切换（代码自二开迁移）

把「上游回了一个限流/欠费响应」翻译成「该惩罚谁、罚多久」：

- 429 包体形态判定：`is_soft_shape` / `credential_scope_phrase` /
  `parse_reset`（中英两种措辞都认）；判定为账号级还是模型级；
- 402：欠费停车（到次日本地 04:00），由账号层记录；
- 产品自动切换：429 时换一条出站身分的配额线重试，每模型每轮上限 4 次。

纯判定逻辑：不 import 账号或渠道模块，调用方传入账号对象并按返回值记录惩罚。
"""
import json
import re
import threading
import time

# ── 429 包体形态 ──────────────────────────────────────────────
SOFT_LIMIT_MARKERS = ("usage exceeds frequency limit", "too many requests",
                      "请求过于频繁")
SOFT_LIMIT_CODES = (14003,)     # 国际版实测过的 429 code

# 把 429 归到凭据本身的措辞。只按整词或完整短语匹配，绝不裸子串：429 包体
# 里带着 accountId / credentialId 这类元数据字段名，子串匹配会把字段名读成
# 作用域声明。有意保守：宁可往窄的单模型窗口方向失败。
ACCOUNT_SCOPE_PHRASES = (
    "account-level", "account level", "account-wide", "account scope",
    "account quota", "account rate limit", "account limit",
    "per account", "per-account", "this account", "your account",
    "the account", "an account",
    "credential-level", "credential level", "credential scope",
    "credential limit", "per credential", "this credential",
    "the credential", "your credential",
    "账号级", "账户级", "该账号", "此账号", "该账户", "此账户",
    "账号限流", "账户限流", "凭证级", "该凭证",
)

#: 同一请求内最多切换几次出站身分
MAX_PRODUCT_SWITCHES = 4


def parse_reset(detail):
    """从 429 包体里抠 reset 时间（中英两种措辞），抠不到返回 None。"""
    if not detail:
        return None
    m = re.search(r"(?:reset at|将在)\s*"
                  r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", detail)
    if not m:
        return None
    stamp = m.group(1).replace("T", " ")
    tz = re.search(r"UTC([+-]\d{1,2})(?::?(\d{2}))?", detail)
    offset = 0
    if tz:
        hours = int(tz.group(1))
        minutes = int(tz.group(2) or 0)
        offset = hours * 3600 + (minutes * 60 if hours >= 0 else -minutes * 60)
    try:
        base = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")) - time.timezone
        return base - offset
    except Exception:
        return None


def credential_scope_phrase(detail):
    """包体使用的凭据作用域措辞；没提作用域返回 None。

    ASCII 短语按整词锚定（accountId 这类标识符满足不了）；中文短语是纯子串
    ——中文没有词边界可锚，也不可能出现在标识符里。
    """
    lowered = (detail or "").lower()
    for phrase in ACCOUNT_SCOPE_PHRASES:
        if phrase.isascii():
            if re.search(r"\b%s\b" % re.escape(phrase), lowered):
                return phrase
        elif phrase in lowered:
            return phrase
    return None


def limit_code(detail):
    """JSON 形态 429 包体里的 code 字段；不是 JSON 返回 None。"""
    try:
        obj = json.loads(detail)
    except Exception:
        return None
    return obj.get("code") if isinstance(obj, dict) else None


def is_soft_shape(detail):
    """是不是「软限流」形态（包体点名限流 / 已知软限流 code）。"""
    if not detail:
        return False
    lowered = detail.lower()
    if any(marker in lowered for marker in SOFT_LIMIT_MARKERS):
        return True
    # 中文措辞已 lower 无损；再查一次原文，防 Unicode 大小写边界问题
    if any(marker in detail for marker in SOFT_LIMIT_MARKERS):
        return True
    return limit_code(detail) in SOFT_LIMIT_CODES


def is_account_level(detail, reset_at=None):
    """包体明说限的是凭据本身（整账号）时为真。

    判定顺序：有 reset 时间 → 只锁模型；无 reset 且措辞点名凭证 → 账号级。
    """
    if reset_at is not None:
        return False
    return credential_scope_phrase(detail) is not None


# ── 产品（出站身分）自动切换 ──────────────────────────────────
_switch_log = {}
_switch_lock = threading.Lock()


def _switch_count(account, model):
    entry = _switch_log.get((account.uid, model))
    if not entry:
        return 0
    count, last = entry
    if time.time() - last > 60:
        return 0
    return count


def try_switch_product(account, model):
    """429 时换身分重试。返回 True 表示已切换、可以重试。

    同一请求内最多切 MAX_PRODUCT_SWITCHES 次（桌面 → VSCode → CLI → 桌面），
    都不行就放弃，让调用端回报真正的 429。
    """
    from auth import identity
    with _switch_lock:
        count = _switch_count(account, model)
        if count >= MAX_PRODUCT_SWITCHES:
            return False
        current = getattr(account, "product", identity.PRODUCT_DESKTOP)
        if current == identity.PRODUCT_DESKTOP:
            target = identity.PRODUCT_VSCODE
        elif current == identity.PRODUCT_VSCODE:
            target = identity.PRODUCT_CLI
        else:
            target = identity.PRODUCT_DESKTOP
        try:
            changed = account.set_product(target)
        except Exception:
            return False
        if not changed:
            return False
        _switch_log[(account.uid, model)] = (count + 1, time.time())
        if len(_switch_log) > 500:
            _switch_log.clear()
    return True


def reset_switch_counter(account, model):
    """成功之后归零，下一次请求重新享有完整的切换额度。"""
    with _switch_lock:
        _switch_log.pop((account.uid, model), None)


def reset_switches():
    """清空全部切换计数（测试用）。"""
    with _switch_lock:
        _switch_log.clear()


def _realm_waits(pool, realm, model):
    """该 realm 在册账号各自的模型冷却等待；pool 为 None 返回 None（调用方区分）。"""
    if pool is None:
        return None
    return [a.throttle_wait(model=model) for a in pool.accounts
            if a.realm == realm and a.enabled and a.access_token]


def realm_model_throttled(pool, realm, model):
    """账号都在但全在冷却该模型时返回 (True, 最短等待秒)。"""
    waits = _realm_waits(pool, realm, model)
    if not waits:
        return (False, 0)
    if all(w > 0 for w in waits):
        return (True, int(min(waits)))
    return (False, 0)


def retry_after_seconds(pool, realm, model):
    """该出口能再服务 model 的最短等待（相关账号冷却的最小交集）。"""
    waits = _realm_waits(pool, realm, model) or []
    active = [w for w in waits if w > 0]
    return int(min(active)) if active else 60


class RateLimited(Exception):
    """上游限了这个模型（429 / code 6004），不是账号死了。

    凭证没问题，只是该模型要冷却一会儿——客户端应拿到 429 + Retry-After。
    message 是可选的人类可读说明（如连坐保护的整池暂停提示），代理 API
    优先透传它；没给就用 detail。
    """

    def __init__(self, http_error=None, detail="", wait=60, message=None):
        self.http_error = http_error
        self.detail = detail or ""
        self.wait = max(1, int(wait or 60))
        self.message = message or ""
        super().__init__("upstream rate limit: %s" % (self.detail[:200] or "429"))


class ContentRejected(Exception):
    """上游内容审核拒绝（403）。响应体带出去，客户端能看到拒绝细节。"""

    def __init__(self, detail="", account_uid=None):
        self.detail = detail or ""
        self.status = 403
        self.account_uid = account_uid
        super().__init__("upstream rejected the request content (403): %s"
                         % self.detail[:200])
