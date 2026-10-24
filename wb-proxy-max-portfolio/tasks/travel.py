# -*- coding: utf-8 -*-
"""tasks/travel.py —— 猫猫旅行（二开随机地点 + 兜底咖啡馆）

端点链：status / config / depart / claim，location_id 走 JSON body。
要点：
- 派出必须带 location_id（空 body 会被新版接口拒绝：HTTP 400）；
- 地点列表随机挑一个，拉取失败兜底咖啡馆（id=1）；
- 状态里的 buddy_id 在 idle 时恒为 0，不能拿来判断有没有 Buddy；
  以 depart 的 "no active buddy" 为准，确实缺才补 first_buddy 后重试一次。
"""
import json
import random
import urllib.error

from tasks import growth

TRAVEL_STATUS = "/activity/growth/buddy/travel/status"
TRAVEL_CONFIG = "/activity/growth/buddy/travel/config"
TRAVEL_DEPART = "/activity/growth/buddy/travel/depart"
TRAVEL_CLAIM = "/activity/growth/buddy/travel/claim"
FALLBACK_LOCATION = 1          # 咖啡馆
FALLBACK_LOCATION_NAME = "咖啡馆"


def _get(account, path, timeout=10):
    # HTTP 实现统一收口在 growth._get/_post（tasks 层唯一实现源）；
    # 本模块只保留原函数签名与默认 timeout，调用点零改动。
    return growth._get(account, path, timeout=timeout)


def _post(account, path, body=None, timeout=10):
    # 原实现 body=None 时发 b"{}"（growth 默认 b""），委托时补回该差异保住线上字节。
    return growth._post(account, path, body if body is not None else {},
                        timeout=timeout)


def fetch_config(account):
    """可去地点列表（新版接口）。失败返回空列表。"""
    try:
        data = _get(account, TRAVEL_CONFIG)
        return (data.get("data") or {}).get("locations") or []
    except Exception:
        return []


def _depart(account, location_id):
    """派出旅行；返回 (data, err)。成功 data 为响应 data，失败 err 为上游 msg。"""
    try:
        res = _post(account, TRAVEL_DEPART, {"location_id": location_id})
        if res.get("code") == 0:
            return res.get("data") or {}, None
        return None, res.get("msg") or ("code=%s" % res.get("code"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", "replace")
        except Exception:
            pass
        try:
            msg = json.loads(detail).get("msg") or ("HTTP %s" % exc.code)
        except Exception:
            msg = "HTTP %s%s" % (exc.code, (": " + detail[:120]) if detail else "")
        return None, msg
    except Exception as exc:
        return None, str(exc)


def ensure_buddy(account, gap=1.0):
    """确保账号已领到 Buddy 实例：没有则完成并领取 first_buddy。"""
    tasks = growth.fetch_growth_tasks(account)
    buddy = next((t for t in tasks if t["task_code"] == "first_buddy"), None)
    if buddy is None:
        return False
    if buddy["status"] == "claimed":
        return True
    if growth._progress_one(account, buddy, [], gap):
        tasks = growth.fetch_growth_tasks(account)
        buddy = next((t for t in tasks if t["task_code"] == "first_buddy"), None)
    return bool(buddy and buddy["status"] == "claimed")


def run(account):
    """检查并执行猫猫旅行（领奖 / 派出）。

    返回 {"ok", "action", "msg", "credit"}；action 取 claim / depart /
    traveling / idle / skip。
    """
    try:
        st = (_get(account, TRAVEL_STATUS).get("data") or {})
    except Exception as exc:
        return {"ok": False, "action": "fail", "msg": "查询旅行状态失败: %s" % exc}

    state = st.get("state")
    if state == "arrived":
        try:
            res = _post(account, TRAVEL_CLAIM, {})
            credit = (res.get("data") or {}).get("reward_credit", 0)
            account.fetch_credits()
            return {"ok": True, "action": "claim", "credit": credit,
                    "msg": "旅行归来领奖成功！获得 %s 积分" % credit}
        except Exception as exc:
            return {"ok": False, "action": "fail", "msg": "领奖失败: %s" % exc}

    if state == "idle":
        if st.get("daily_limit_reached"):
            return {"ok": True, "action": "idle",
                    "msg": "猫猫今日已完成旅行，明日 00:00 刷新"}
        locations = fetch_config(account)
        if locations:
            loc = random.choice(locations)
            location_id = loc.get("id")
        else:
            location_id = FALLBACK_LOCATION
            loc = {"name": FALLBACK_LOCATION_NAME}
        data, err = _depart(account, location_id)
        if data is None and "no active buddy" in (err or "").lower():
            if ensure_buddy(account):
                data, err = _depart(account, location_id)
            else:
                return {"ok": False, "action": "fail",
                        "msg": "还没有 Buddy：需先完成并领取「领取一只 Buddy」任务"
                               "（新建任务并发起对话）"}
        if data is not None:
            name = (data.get("location") or {}).get("name") or loc.get("name") or ""
            return {"ok": True, "action": "depart",
                    "msg": "猫猫已出发前往「%s」，预计数小时后归来！" % name}
        return {"ok": False, "action": "fail", "msg": "派出旅行失败: %s" % err}

    if state == "traveling":
        return {"ok": True, "action": "traveling",
                "msg": "猫猫正在旅行途中，请稍后再来查看！"}

    return {"ok": True, "action": "skip", "msg": "当前状态: %s" % state}


def classify(account, result):
    """旅行结果分类 -> (status, message)。"""
    result = result or {}
    action = result.get("action")
    if result.get("ok") and action in ("claim", "depart"):
        return "ok", result.get("msg")
    if result.get("ok"):
        return "skip", result.get("msg")
    return "error", result.get("msg") or "旅行处理失败"
