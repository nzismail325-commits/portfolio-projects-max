# -*- coding: utf-8 -*-
"""tasks/school.py —— 开学季活动（school_open_day_2026，二开完整保留）

上游 v1.7.12 已删除这个脚本，本项目为唯一蓝本（重构 §3-A）。本模块只做一层
薄封装：`run(account)` 调用二开的 `run_school_for_account`（school_impl），
`classify()` 把结果翻译成调度器统一的 (status, message, credits) 三元组。

活动结束后自然沉默（in_period=false 整段跳过，无副作用）；活动 ID 变化时
只改 school_impl 顶部的常量。
"""
from tasks import growth
from tasks import school_impl

#: 活动标识（活动更换时只改 school_impl.ACTIVITY_ID）
ACTIVITY_ID = school_impl.ACTIVITY_ID

#: 写操作最小间隔（与上游脚本一致：1.5s）
WRITE_GAP = 1.5


def run(account):
    """执行开学季一轮。返回二开原始结构：

    {"ok", "in_period", "claimed", "lottery", "msg", "error"}
    """
    if account.realm != "cn":
        return {"ok": True, "in_period": False, "claimed": [],
                "lottery": {"draws": 0, "credit": 0, "prizes": []},
                "msg": "国际版无开学季活动，跳过", "error": ""}
    if growth.is_enterprise(account):
        return {"ok": True, "in_period": False, "claimed": [],
                "lottery": {"draws": 0, "credit": 0, "prizes": []},
                "msg": "企业版账号无成长体系，跳过", "error": ""}
    return school_impl.run_school_for_account(account, gap=WRITE_GAP)


def classify(account, result):
    """开学季结果分类 -> (status, message, credits)。"""
    result = result or {}
    if not result.get("ok"):
        return "error", "开学季任务失败: %s" % (result.get("error") or "未知原因"), 0
    if not result.get("in_period"):
        return "skip", result.get("msg") or "活动非进行期，跳过", 0
    claimed = result.get("claimed") or []
    lottery = result.get("lottery") or {}
    parts = []
    if claimed:
        parts.append("领奖 %d 项（%s）" % (len(claimed), ",".join(claimed)))
    if lottery.get("draws"):
        parts.append("转盘 %d 抽 +%s 积分"
                     % (lottery.get("draws"), lottery.get("credit", 0)))
        prizes = lottery.get("prizes") or []
        if prizes:
            parts.append("奖品: " + "、".join(prizes))
    if lottery.get("error"):
        parts.append("抽奖中断: %s" % lottery["error"])
    if not parts:
        parts.append("任务均已完成，无可用抽奖次数")
    return "ok", "开学季: " + "；".join(parts), int(lottery.get("credit") or 0)
