"""Model tiers: which models only paid (PRO) accounts may use.

The upstream product-config response carries a `modelTiers[]` array next to the
model list. Keeping only the model names meant a free account could still be
offered PRO-only models and the upstream answered 11158 after the request was
spent. This registry keeps the tier map so account selection and `/v1/models`
can honour it.

Channel-agnostic: callers feed raw payloads in; no upstream endpoint or channel
module is imported here. A payload without `modelTiers` leaves the previous
map untouched, so an upstream that omits the array does not silently erase
tiers learned earlier.
"""
import threading
import time

#: User-type spellings the upstream uses for an unpaid account.
FREE_TYPES = frozenset((
    "free",
    "personal_free_user",
    "personal-free-user",
))

_lock = threading.Lock()
#: realm -> {model id: "free" | "standard"}
_tiers = {}
#: realm -> 上次成功摄入的 epoch 秒（对应那次目录刷新的时刻）
_ingested_at = {}


def _priority_only(entry):
    """True when the entry is only a scheduling preference, not a gate."""
    if str(entry.get("accessMode") or "").strip().lower() == "exclusive":
        return False
    badge = entry.get("badge")
    labels = []
    if isinstance(badge, dict):
        labels = [badge.get("label"), badge.get("labelEn")]
    elif isinstance(badge, str):
        labels = [badge]
    for label in labels:
        text = str(label or "").strip()
        if not text:
            continue
        if "订阅优先" in text:
            return True
        if text.lower() in ("priority", "subscription priority"):
            return True
    return False


def _tier_of(raw):
    """Normalize an upstream user type; unknown non-empty values mean paid."""
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if value in FREE_TYPES:
        return "free"
    return "standard"


def ingest(realm, payload):
    """Record the tier map carried by one product-config payload."""
    if not isinstance(payload, dict):
        return False
    root = payload
    data = payload.get("data")
    if isinstance(data, dict):
        root = data
    entries = root.get("modelTiers")
    if not isinstance(entries, list):
        return False
    out = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled") is False:
            continue
        if _priority_only(entry):
            continue
        tier = _tier_of(entry.get("requiredUserType") or entry.get("tier"))
        if tier is None:
            continue
        ids = entry.get("modelIds")
        if not isinstance(ids, list):
            continue
        for mid in ids:
            model = str(mid or "").strip()
            if model:
                out[model] = tier
    with _lock:
        _tiers[str(realm or "")] = out
        _ingested_at[str(realm or "")] = time.time()
    return True


def snapshot(realm=None):
    """A copy of the tier map for one realm, or the merged map."""
    with _lock:
        if realm:
            return dict(_tiers.get(realm) or {})
        merged = {}
        for mapping in _tiers.values():
            merged.update(mapping)
        return merged


def requires_pro(model, realm=None):
    """True when the model is gated to paid accounts.

    Unknown models and an empty map return False, so an install that never
    received `modelTiers` keeps its exact previous behaviour.
    """
    name = str(model or "").strip()
    if not name:
        return False
    with _lock:
        if realm and realm in _tiers:
            return _tiers[realm].get(name) == "standard"
        return any(mapping.get(name) == "standard"
                   for mapping in _tiers.values())


def ingested_at(realm=None):
    """该出口的 tier 表上次刷新时间；从未刷新过返回 None。

    tier 表只在内存里、每次目录刷新重建，所以「什么时候」是说明它有多新
    的唯一诚实方式——面板把这个时间跟着标注一起显示。
    """
    with _lock:
        if realm:
            return _ingested_at.get(str(realm))
        stamps = list(_ingested_at.values())
    return max(stamps) if stamps else None


def reset():
    """Drop every recorded tier map (tests only)."""
    with _lock:
        _tiers.clear()
        _ingested_at.clear()
