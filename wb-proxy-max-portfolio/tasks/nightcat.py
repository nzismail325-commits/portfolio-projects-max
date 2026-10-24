# -*- coding: utf-8 -*-
"""tasks/nightcat.py —— 夜猫任务（二开五态拆卡）

事件链：GLM-5.2 night 模式上报 → 4 轮 × 4 秒确认落账 → 达标即领。
每天计 1 次、累计 3 天；只在 23:00-08:00 窗口内上报才计数，白天诚实跳过。

五态返回（供落库与卡片展示）：claim / already / skip / pending / fail。
接取后走 `_wait_accepted` 确认，未生效返回"明晚继续"而不是干等（二开增强）。
"""
import time

from tasks import growth

NIGHT_TASK_CODE = "black_cat"
NIGHT_WINDOW_START = 23
NIGHT_WINDOW_END = 8


def in_night_window(now=None):
    hour = (now or time.localtime()).tm_hour
    return hour >= NIGHT_WINDOW_START or hour < NIGHT_WINDOW_END


def run(account, gap=1.0):
    """执行夜猫任务一轮。

    返回 {"ok", "action", "code", "msg", "credit"}；action 取
    claim / already / skip / pending / fail。
    """
    if account.realm != "cn":
        return {"ok": False, "action": "skip", "code": -2,
                "msg": "国际版无夜猫任务，已跳过", "credit": 0}
    if growth.is_enterprise(account):
        return {"ok": True, "action": "skip", "code": 0,
                "msg": "企业版账号无成长体系，跳过", "credit": 0}
    if not in_night_window():
        return {"ok": False, "action": "skip", "code": -3,
                "msg": "当前不在夜猫时段（23:00-08:00），跳过", "credit": 0}

    tasks = growth.fetch_growth_tasks(account)
    spec = next((t for t in tasks if t.get("task_code") == NIGHT_TASK_CODE), None)
    if spec is None:
        return {"ok": False, "action": "skip", "code": -4,
                "msg": "账号任务列表中没有夜猫子任务，跳过", "credit": 0}
    if spec.get("status") == "claimed":
        return {"ok": True, "action": "already", "code": 10001,
                "msg": "今日夜猫任务已领奖（幂等跳过）", "credit": 0}

    if spec.get("status") == "not_accepted":
        result = growth.accept_tasks(account, [NIGHT_TASK_CODE])
        confirmed, _pending = growth._wait_accepted(
            account, [NIGHT_TASK_CODE], timeout=20)
        if NIGHT_TASK_CODE not in confirmed:
            return {"ok": True, "action": "pending", "code": 0,
                    "msg": "夜猫任务接取未生效%s，明晚继续"
                           % (("（%s）" % result.get("msg")) if result.get("msg") else ""),
                    "credit": 0}
        tasks = growth.fetch_growth_tasks(account)
        spec = next((t for t in tasks if t.get("task_code") == NIGHT_TASK_CODE), spec)

    current = spec.get("current", 0)
    target = spec.get("target", 3) or 3
    if spec.get("status") == "completed" or current >= target:
        result = growth.claim_task(account, NIGHT_TASK_CODE)
        if result.get("ok"):
            return {"ok": True, "action": "claim", "code": 0,
                    "msg": "夜猫任务领奖成功", "credit": result.get("credit", 0)}
        return {"ok": False, "action": "fail", "code": -5,
                "msg": "夜猫任务领奖失败", "credit": 0}

    # 每晚只报 1 次（每天计 1 次，连发多次不加速）
    event = growth.build_event(account, "cat", idx=0)
    growth.report_events(account, [event])
    new_current = current
    for _ in range(4):
        time.sleep(4)
        fresh = next((x for x in growth.fetch_growth_tasks(account)
                      if x["task_code"] == NIGHT_TASK_CODE), None)
        if fresh and fresh.get("current", 0) > current:
            new_current = fresh.get("current", 0)
            break
    if new_current >= target:
        result = growth.claim_task(account, NIGHT_TASK_CODE)
        if result.get("ok"):
            return {"ok": True, "action": "claim", "code": 0,
                    "msg": "夜猫任务完成 %s/%s，领奖成功" % (new_current, target),
                    "credit": result.get("credit", 0)}
        return {"ok": False, "action": "pending", "code": -6,
                "msg": "夜猫任务已达标 %s/%s，奖励结算稍后自动重试领取"
                       % (new_current, target), "credit": 0}
    if new_current > current:
        return {"ok": True, "action": "pending", "code": 0,
                "msg": "今晚 +1（%s/%s），明晚继续，累计 %s 天可领奖"
                       % (new_current, target, target), "credit": 0}
    return {"ok": False, "action": "pending", "code": -6,
            "msg": "已上报但进度暂未变化（%s/%s），明晚调度器会继续累计"
                   % (new_current, target), "credit": 0}


def classify(account, result):
    """夜猫结果分类 -> (status, message)。"""
    result = result or {}
    action = result.get("action")
    if result.get("ok") and action == "claim":
        return "ok", result.get("msg")
    if result.get("ok") and action == "already":
        return "already", result.get("msg")
    if action == "skip":
        return "skip", result.get("msg")
    if action == "pending":
        return "warn", result.get("msg")
    return "error", result.get("msg") or "夜猫任务失败"
