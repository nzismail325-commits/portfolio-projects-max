# -*- coding: utf-8 -*-
"""tasks/streak.py —— 连登管家（自上游 v1.7.12 移植，本项目新任务）

语义：昨日漏签查 heatmap → 有补签卡则补签 → 领新手礼包/活动补偿 →
7d/14d/28d 档位兑换（client_token 防重）→ lottery/summary 有次数则全抽完。

幂等安全：未解锁 / 已领 / 无次数 / 企业版一律静默跳过；单步失败只记一行，
不拖垮整轮，更不影响其他账号。收益（抽奖积分）计入 credits 流水。
"""
import time
import uuid

from tasks import growth

BILL_BASE = growth.BILL_BASE

STREAK_PATH = "/activity/growth/streak"
HEATMAP_PATH = "/activity/growth/heatmap"
MAKEUP_USE_PATH = "/activity/growth/makeup-cards/use"
REDEEM_PATH = "/activity/growth/redeem"
LOTTERY_SUMMARY_PATH = "/activity/growth/lottery/summary"
LOTTERY_DRAW_PATH = "/activity/growth/lottery/draw"
CLAIM_GIFT_PATH = "/billing/meter/claim-gift"
CLAIM_COMP_PATH = "/billing/meter/claim-compensation"

#: 档位兑换与抽奖都是写操作，两次之间至少间隔这么久
WRITE_GAP = 1.0


def _get(account, path, timeout=10):
    # HTTP 实现统一收口在 growth._get/_post（tasks 层唯一实现源）；
    # 本模块只保留原函数签名与默认 timeout，调用点零改动。
    return growth._get(account, path, timeout=timeout)


def _post(account, path, body, base=None, headers=None, timeout=10):
    # 原实现 body=None 时发 b"{}"（growth 默认 b""），委托时补回该差异保住线上字节。
    return growth._post(account, path, body if body is not None else {},
                        base=base, headers=headers, timeout=timeout)


def make_up_yesterday(account, logs):
    """昨日漏签且还有补签卡时补签一次。失败只记一行。"""
    try:
        heatmap = _get(account, HEATMAP_PATH)
        cells = (heatmap.get("data") or {}).get("cells", [])
        yesterday = time.strftime("%Y-%m-%d",
                                  time.localtime(time.time() - 86400))
        cell = next((c for c in cells if c.get("date") == yesterday), None)
        if not (cell and cell.get("score", 0) == 0):
            return False
        streak = _get(account, STREAK_PATH)
        cards = ((streak.get("data") or {}).get("makeup_cards") or {}).get("balance", 0)
        if cards <= 0:
            return False
        _post(account, MAKEUP_USE_PATH, {"target_date": yesterday})
        logs.append("已消耗 1 张补签卡补签昨日 (%s)" % yesterday)
        time.sleep(WRITE_GAP)
        return True
    except Exception as exc:
        logs.append("补签尝试失败: %s" % str(exc)[:120])
        return False


def claim_gifts(account, logs):
    """领新手礼包与活动补偿（每号一次；无则业务错误静默）。"""
    billing_headers = account.headers("billing")
    for path, name in ((CLAIM_GIFT_PATH, "新手礼包"),
                       (CLAIM_COMP_PATH, "活动补偿")):
        try:
            data = _post(account, path, {}, base=BILL_BASE, headers=billing_headers)
            if data.get("code") == 0:
                credit = (data.get("data") or {}).get("credit", 0)
                logs.append("领取%s +%s 积分" % (name, credit))
                time.sleep(WRITE_GAP)
        except Exception:
            pass


def redeem_tiers(account, logs):
    """7d/14d/28d 连登档位兑换（已解锁未领的才兑换，client_token 防重）。"""
    try:
        streak = _get(account, STREAK_PATH)
        redemption = (streak.get("data") or {}).get("redemption_status") or {}
        tiers = redemption.get("tiers", [])
        statuses = {
            "7d": redemption.get("tier_7d_status"),
            "14d": redemption.get("tier_14d_status"),
            "28d": redemption.get("tier_28d_status"),
        }
        for tier in tiers:
            name = tier.get("tier")
            if statuses.get(name) in ("locked", "claimed"):
                continue
            try:
                body = {"tier": name, "client_token": str(uuid.uuid4())}
                data = _post(account, REDEEM_PATH, body)
                if data.get("code") == 0:
                    logs.append("成功兑换连登 %s 档位" % name)
                    time.sleep(WRITE_GAP)
            except Exception as exc:
                logs.append("兑换 %s 档位失败: %s" % (name, str(exc)[:120]))
    except Exception as exc:
        logs.append("连登档位查询失败: %s" % str(exc)[:120])


def draw_lottery(account, logs):
    """有抽奖次数则全部抽完；返回抽奖次数。"""
    drawn = 0
    try:
        summary = _get(account, LOTTERY_SUMMARY_PATH)
        chances = (summary.get("data") or {}).get("chances", 0)
        for _ in range(int(chances or 0)):
            try:
                data = _post(account, LOTTERY_DRAW_PATH,
                             {"client_token": str(uuid.uuid4())})
                if data.get("code") == 0:
                    drawn += 1
            except Exception as exc:
                logs.append("抽奖失败: %s" % str(exc)[:120])
                break
            time.sleep(WRITE_GAP)
        if drawn:
            logs.append("完成成长抽奖 %d 次" % drawn)
    except Exception as exc:
        logs.append("抽奖次数查询失败: %s" % str(exc)[:120])
    return drawn


def run(account):
    """连登管家一轮。返回 {"ok", "status", "msg", "logs", "credit"}。"""
    if account.realm != "cn":
        return {"ok": False, "status": "skip", "msg": "连登管家仅限国内版账号",
                "logs": [], "credit": 0}
    if growth.is_enterprise(account):
        return {"ok": True, "status": "skip", "msg": "企业版账号无成长体系，跳过",
                "logs": [], "credit": 0}

    logs = []
    make_up_yesterday(account, logs)
    claim_gifts(account, logs)
    redeem_tiers(account, logs)
    drawn = draw_lottery(account, logs)

    credit = 0
    if drawn:
        try:
            before = (account.credits or {}).get("remain")
            account.fetch_credits()
            after = (account.credits or {}).get("remain")
            if isinstance(before, int) and isinstance(after, int) and after > before:
                credit = after - before
        except Exception:
            pass

    msg = "；".join(logs) if logs else "连登状态正常（无需兑换/无抽奖次数）"
    return {"ok": True, "status": "ok", "msg": msg, "logs": logs, "credit": credit}


def classify(account, result):
    """连登结果分类 -> (status, message, credits)。"""
    result = result or {}
    if result.get("status") == "skip":
        return "skip", result.get("msg"), 0
    if not result.get("ok"):
        return "error", result.get("msg") or "连登管家失败", 0
    return "ok", result.get("msg"), int(result.get("credit") or 0)
