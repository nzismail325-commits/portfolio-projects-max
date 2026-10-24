# -*- coding: utf-8 -*-
"""core/timeutil.py —— 本地时间工具（本地自研，上游无对应）

「下一个本地整点」在账号停车（次日 04:00）、任务排程（配置小时）、活动归零
（当日零点）三处都需要，口径必须一致：今天的该整点已过就顺延到明天。
"""
import time


def local_hour_epoch(hour, now=None, roll=True):
    """本地 hour:00 的 epoch（hour 取 0-23）。

    roll=True（默认）是「下一个」：今天的该整点已过就顺延到明天（账号停车
    next_local_4am 的口径）；roll=False 取 now 所在日的该整点，哪怕已经过去
    （活动历史「今日」下界要的是今天零点本身，不是下一个零点）。
    夏令时归属交给 time.mktime（tm_isdst=-1）按那个本地时刻的平台规则判断，
    不按调用时刻生效的 UTC 偏移换算。
    """
    now = time.time() if now is None else now
    lt = time.localtime(now)
    stamp = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, int(hour), 0, 0, 0, 0, -1))
    if roll and stamp <= now:
        stamp += 86400
    return stamp
