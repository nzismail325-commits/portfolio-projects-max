# -*- coding: utf-8 -*-
"""tasks/growth.py —— 国内版成长任务引擎（二开骨架 + 上游两处优化）

流程（自上而下，与二开一致）：
  0. auto 类任务（first_buddy）先点亮领奖——它是其他任务与猫猫旅行的前置；
  1. 批量接取未接任务（上游优化：chunk=20 分批），复核补接一次；
  2. `_wait_accepted` 确认接取生效（二开独有，不能被上游"复核补接"替代）；
  3. 逐任务点亮上报 → 落账等待 → 领奖。

两处以上游 v1.7.12 为准：
  - 落账等待改为"进度在涨才多等"的动态策略（最多 6 轮）；
  - 接取按 20 个一批。

TASK_SPECS 数值以上游 v1.7.12 为准（含公众号 unforgeable 任务）；夜猫与
旅行由各自模块负责，主循环排除 black_cat，也不顺手跑旅行。

企业号：整个成长体系对它不存在，入口与各接口都直接跳过（上游防御性做法）。
"""
import json
import threading
import time
import urllib.error
import urllib.request

from auth import identity
from core import net
from tasks.scheduler import TaskRunner

CHAT_BASE = identity.CN_CHAT_BASE
BILL_BASE = "https://www.codebuddy.cn"
WEB_BASE = "https://www.workbuddy.cn"

#: 成长任务中心的适用出口（国内版专属）：进度查询、一键作业、卡片渲染都以它为准
GROWTH_REALM = "cn"
DESKTOP_UA = identity.DESKTOP_UA_CN
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

#: 单次接取的最大任务数（上游 v1.7.12：大批量接取分批复核更稳）
ACCEPT_CHUNK = 20

TASK_SPECS = {
    "create_canvas": {"kind": "canvas", "target": 1, "reward": 300, "name": "创建设计任务"},
    "template_5": {"kind": "template", "target": 5, "reward": 200, "name": "模板创建任务"},
    "expert_5": {"kind": "expert", "target": 5, "reward": 200, "name": "使用专家助手"},
    "Expert_team_use_3": {"kind": "team", "target": 3, "reward": 150, "name": "使用专家团队"},
    "skill_1": {"kind": "skill", "target": 1, "reward": 100, "name": "体验技能"},
    "automation_1": {"kind": "automation", "target": 1, "reward": 100, "name": "创建自动化任务"},
    "playbook_prompt": {"kind": "playbook", "target": 1, "reward": 100, "name": "灵感案例使用"},
    "Expert_lighthouse": {"kind": "lighthouse", "target": 1, "reward": 100, "name": "轻量云专家使用"},
    "Buddy_App": {"kind": "buddy5", "target": 1, "reward": 100, "name": "进入 Buddy 应用"},
    "Buddy_App_QQ": {"kind": "buddy5", "target": 1, "reward": 100, "name": "企鹅教师助手"},
    "Hp_Appearance": {"kind": "skin", "target": 1, "reward": 100, "name": "应用主题外观"},
    "chat_5": {"kind": "chat", "target": 5, "reward": 100, "name": "发起 5 次对话"},
    "Model_chat_GLM5.2": {"kind": "glmchat", "target": 1, "reward": 100, "name": "体验 GLM-5.2"},
    "black_cat": {"kind": "cat", "target": 3, "reward": 100,
                  "name": "夜猫子任务 (23:00-08:00)"},
    "RichMeow_Chat": {"kind": "richmeow", "target": 1, "reward": 100, "name": "桌面对话事件链"},
    "Library_read": {"kind": "library", "target": 1, "reward": 100, "name": "浏览资料库"},
    # first_buddy 是 auto 类（不接受接取），完成后领奖才发放 Buddy 实例；
    # 它是所有 single 任务与猫猫旅行的前置
    "first_buddy": {"kind": "chat", "target": 1, "reward": 300, "name": "领取一只 Buddy"},
    "wb_wechat_oa_subscribe_task": {
        "unforgeable": True, "reward": 100,
        "reason": "需在微信关注「腾讯 WorkBuddy」公众号满 24 小时",
        "name": "关注官方公众号"},
    "Expert_Philanthropy": {"unforgeable": True, "reason": "真实捐款动作",
                            "reward": 0, "name": "公益爱心捐赠"},
}

#: 上游只认桌面客户端的真实行为信号（jump_url 均为 workbuddy:// 深链）。
#: 伪造事件进度永远是 0/1，claim 必然 400 —— 诚实跳过并给出深链。
DESKTOP_ONLY_TASKS = {
    "RichMeow_Chat": "在桌面端发起 1 次对话",
    "Library_read": "在桌面端打开「资料库」并读完介绍文档",
    "Buddy_App": "在桌面端左上角「发现应用」进入任意一个 Buddy 应用",
    "Buddy_App_QQ": "在桌面端「发现应用」进入「企鹅教师助手」",
}

#: 夜猫子任务只在 23:00-08:00 上报才计数，每天 1 次、累计 3 天
NIGHT_TASK_CODES = {"black_cat"}

#: 专家/团队事件必须彼此不同：上游按 (eventCode, id) 去重
EXPERT_ID_POOL = [
    ("ex_PZw8Gu81HfN4", "运维工程师"), ("ex_ROsDtJbzADFV", "产品经理"),
    ("ex_SMUnl0nJbPix", "UI设计师"), ("ex_ZTR062oVBOCW", "数据分析师"),
    ("ex_a3sSSFBy8qaC", "后端架构师"), ("ex_aG1kvKbq8lPx", "文案策划"),
    ("ex_al1vxtUOYQ10", "测试专家"), ("ex_cZfiyuET9UQP", "安全顾问"),
    ("ex_eggOvQuVP0hq", "算法工程师"), ("ex_hSwsQjkSKnkX", "前端工程师"),
    ("ex_mMbwwmFA9n9P", "项目管理专家"), ("ex_uAQE5POfk7Zh", "增长运营专家"),
    ("ex_uZzSAScSy7FZ", "行业研究员"), ("ex_LHywGrZOtG7G", "数据分析师"),
    ("ex_NX5C8GBciVed", "测试架构师"), ("ex_DdCsaoq4AtcO", "云端运维专家"),
    ("ex_KzqKQguubrNQ", "内容创作专家"), ("ex_2cvvUZQhDyeJ", "腾讯轻量云专家"),
]
TEAM_ID_POOL = [
    ("CloudOpsTeam", "运维专家团队"), ("CloudContentTeam", "内容专家团队"),
    ("CloudDevTeam", "研发专家团队"), ("ProductStrategyTeam", "产品战略团队"),
    ("MarketingCampaignTeam", "营销活动团队"), ("SalesBattleTeam", "销售作战团队"),
    ("DesignEngineTeam", "设计引擎团队"), ("HrOperationsTeam", "人力运营团队"),
]


def _get(account, path, timeout=15):
    url = CHAT_BASE + path
    req = urllib.request.Request(url, headers=account.headers("chat"))
    with net.urlopen(req, timeout=timeout, proxy=account.proxy) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(account, path, body=None, headers=None, base=None, timeout=15):
    url = (base or CHAT_BASE) + path
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers=headers or account.headers("chat"))
    with net.urlopen(req, timeout=timeout, proxy=account.proxy) as resp:
        return json.loads(resp.read().decode("utf-8"))


def is_enterprise(account):
    try:
        return bool(account.is_enterprise())
    except Exception:
        return False


def fetch_growth_tasks(account):
    """查询成长任务列表及当前状态。企业号返回空（成长体系不适用）。"""
    if is_enterprise(account):
        return []
    try:
        data = _get(account, "/v2/activity/growth/tasks")
        tasks = []
        for t in (data.get("data") or {}).get("tasks") or []:
            code = t.get("task_code") or ""
            spec = TASK_SPECS.get(code, {})
            prog = t.get("progress") or {}
            tasks.append({
                "task_code": code,
                "name": t.get("title") or spec.get("name") or code,
                "description": t.get("description") or t.get("task_desc") or "",
                "jump_url": t.get("jump_url") or "",
                "status": t.get("accept_status") or "not_accepted",
                "task_type": t.get("task_type") or "",
                "current": prog.get("current", 0),
                "target": prog.get("target", spec.get("target", 1)),
                "reward_credit": t.get("reward_credit") or spec.get("reward", 0),
                "reward_energy": t.get("reward_energy", 0),
                "unforgeable": bool(spec.get("unforgeable")),
                "reason": spec.get("reason", ""),
            })
        return tasks
    except Exception:
        return []


def fetch_task_progress(account, code):
    for t in fetch_growth_tasks(account):
        if t.get("task_code") == code:
            return t
    return None


def fetch_growth_summary(account):
    out = {"energy": 0, "streak_days": 0, "travel": {"state": "unknown"}}
    try:
        d = _get(account, "/v2/activity/growth/energy", timeout=10)
        out["energy"] = (d.get("data") or {}).get("balance", 0)
    except Exception:
        pass
    try:
        d = _get(account, "/activity/growth/streak", timeout=10)
        st = (d.get("data") or {}).get("streak") or {}
        out["streak_days"] = st.get("days", 0)
    except Exception:
        pass
    try:
        d = _get(account, "/activity/growth/buddy/travel/status", timeout=10)
        out["travel"] = d.get("data") or {}
    except Exception:
        pass
    return out


def accept_tasks(account, codes, chunk=ACCEPT_CHUNK):
    """批量接取任务，按 chunk 分批（上游 v1.7.12）。

    返回 {"ok", "accepted", "failed", "msg", "reasons"}。接取失败必须让上层
    看见：后续上报的事件作用在未接取任务上时进度永远 0。
    """
    out = {"ok": True, "accepted": [], "failed": [], "msg": "", "reasons": []}
    if not codes:
        return out
    size = max(1, int(chunk or ACCEPT_CHUNK))
    for start in range(0, len(codes), size):
        part = codes[start:start + size]
        try:
            d = _post(account, "/v2/activity/growth/tasks/accept",
                      {"task_codes": part})
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(300).decode("utf-8", "replace")
            except Exception:
                pass
            out["ok"] = False
            out["msg"] = "HTTP %s: %s" % (exc.code, detail[:200])
            out["failed"].extend(part)
            out["reasons"].append(out["msg"])
            continue
        except Exception as exc:
            out["ok"] = False
            out["msg"] = str(exc)[:200]
            out["failed"].extend(part)
            out["reasons"].append(out["msg"])
            continue
        if d.get("code") != 0:
            out["ok"] = False
            out["msg"] = d.get("msg") or ("code=%s" % d.get("code"))
            out["failed"].extend(part)
            out["reasons"].append(out["msg"])
            continue
        results = (d.get("data") or {}).get("results")
        if isinstance(results, list):
            for r in results:
                code = r.get("task_code") or ""
                if r.get("status") in ("accepted", "already_accepted"):
                    out["accepted"].append(code)
                else:
                    out["failed"].append(code)
            known = set(out["accepted"]) | set(out["failed"])
            out["accepted"].extend(c for c in part if c not in known)
        else:
            out["accepted"].extend(part)
    return out


def _wait_accepted(account, codes, timeout=30):
    """接取后确认生效：轮询任务清单，直到全部非待接取或超时。

    新号批量接取有服务端异步延迟，固定睡 1 秒不够——接取未生效就上报的事件
    会被直接作废。返回 (已确认列表, 未确认列表)。
    """
    wanted = list(dict.fromkeys(codes))
    deadline = time.time() + max(5, timeout)
    confirmed, remaining = [], list(wanted)
    while remaining and time.time() < deadline:
        time.sleep(2)
        try:
            states = {t.get("task_code"): t.get("status")
                      for t in fetch_growth_tasks(account)}
        except Exception:
            continue
        newly = [c for c in remaining
                 if states.get(c) not in (None, "not_accepted")]
        confirmed += newly
        remaining = [c for c in remaining if c not in confirmed]
    return confirmed, remaining


def claim_task(account, code):
    """领取任务奖励；copilot 域 400 时降级到 web 域重试一次。"""
    try:
        d = _post(account, "/activity/growth/tasks/%s/claim" % code)
        if d.get("code") == 0:
            data = d.get("data") or {}
            return {"ok": True, "credit": data.get("credit", 0),
                    "energy": data.get("energy", 0)}
    except urllib.error.HTTPError as exc:
        if exc.code == 400:
            web_hdrs = {
                "Authorization": "Bearer " + account.access_token,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": WEB_BASE,
                "Referer": WEB_BASE + "/profile/growth-center",
                "x-client-platform": "web",
                "User-Agent": WEB_UA,
                "X-User-Id": account.uid,
                "X-Domain": WEB_BASE,
            }
            try:
                d = _post(account, "/activity/growth/tasks/%s/claim" % code,
                          headers=web_hdrs, base=WEB_BASE)
                if d.get("code") == 0:
                    data = d.get("data") or {}
                    return {"ok": True, "credit": data.get("credit", 0),
                            "energy": data.get("energy", 0)}
            except Exception:
                pass
    except Exception:
        pass
    return {"ok": False, "credit": 0, "energy": 0, "msg": "领奖请求失败"}


def build_event(account, kind, idx=0, expert=None):
    """构造指定类型的真实规范事件数据。

    expert: (expert_id, expert_name)——专家/团队类事件必须每次使用不同 id。
    """
    now = int(time.time() * 1000)
    cid = "wb-task-%d-%d" % (now, idx)
    rid = cid + "-req"
    uid = account.uid

    if kind == "canvas":
        return {"eventCode": "wbx_design_canvas_task_create", "timestamp": now,
                "reportDelay": 0, "conversationId": cid, "requestId": rid,
                "source": "summon_keyword", "isCustomModel": False, "name": "",
                "inputLength": 12, "id": "wbx-canvas-%d" % now, "cost": 0,
                "isSuccessful": True, "userId": uid}
    if kind == "template":
        return {"eventCode": "agent_task_created_with_template", "timestamp": now,
                "reportDelay": 0, "isCustomModel": True, "id": str(idx),
                "name": "幻灯片", "requestId": rid, "conversationId": cid, "userId": uid}
    if kind in ("expert", "team", "lighthouse"):
        etype = "team" if kind == "team" else "agent"
        if expert:
            ex_id, name = expert
        elif kind == "lighthouse":
            ex_id, name = "ex_2cvvUZQhDyeJ", "腾讯轻量云专家"
        elif kind == "team":
            ex_id, name = "CloudOpsTeam", "运维专家团队"
        else:
            ex_id, name = "ContentCreator", "内容创作专家"
        return {"eventCode": "expert_actual_use", "timestamp": now, "reportDelay": 0,
                "mode": "CLOUD", "id": ex_id, "name": name, "expertTitle": name,
                "type": "02-Engineering", "expertType": etype, "source": "builtin",
                "version": "1.0.2", "cost": 0, "characterCount": 12,
                "conversationId": cid, "requestId": rid, "messageId": rid,
                "requestModelId": "deepseek-v4-flash",
                "requestModelName": "DeepSeek V4 Flash", "userId": uid}
    if kind == "skill":
        return {"eventCode": "skill_info", "timestamp": now, "reportDelay": 0,
                "skillId": "skill_2096525080079265792", "name": "pptx", "userId": uid}
    if kind == "automation":
        return {"eventCode": "automated_task_create_suc", "timestamp": now,
                "reportDelay": 0, "name": "每周工作整理", "type": "cron",
                "source": "manually", "modelId": "deepseek-v4-flash",
                "modelIsThinking": False, "conversationId": cid, "requestId": rid,
                "schedule": {"type": "recurring",
                             "rrule": "FREQ=WEEKLY;BYDAY=FR;BYHOUR=9;BYMINUTE=0"},
                "prompt": "每周五自动整理本周工作", "userId": uid}
    if kind == "playbook":
        return {"eventCode": "playbook_prompt_send", "timestamp": now, "reportDelay": 0,
                "id": "worker-ledger-freedom-dashboard", "name": "打工人小账本",
                "type": "other", "promptLength": 10, "isOfficial": 1,
                "source": "discover", "conversationId": cid, "requestId": rid,
                "userId": uid}
    if kind == "skin":
        return {"eventCode": "appearance_skin_apply", "timestamp": now, "reportDelay": 0,
                "action": "apply", "source": "settings_close", "id": "theme-tkmw7j",
                "vipLevel": "free", "series": "craft", "type": "unknown",
                "name": "和平精英激战金秋", "userId": uid}
    if kind in ("chat", "glmchat", "cat"):
        m_id = "glm-5.2" if kind in ("glmchat", "cat") else "deepseek-v4-flash"
        m_nm = "GLM-5.2" if kind in ("glmchat", "cat") else "DeepSeek V4 Flash"
        mode = "night" if kind == "cat" else "craft"
        return {"eventCode": "chat_request_send", "timestamp": now, "reportDelay": 0,
                "mode": mode, "conversationId": cid, "requestId": rid,
                "inputLength": 12, "requestModelId": m_id, "requestModelName": m_nm,
                "isPlan": False, "agentName": "default", "agentType": "conversation",
                "userId": uid}
    return {"eventCode": "heartbeat", "timestamp": now, "userId": uid}


def report_events(account, events, base=None):
    """向上游上报事件数组（chat 侧会实时推进成长任务进度）。"""
    base = base or CHAT_BASE
    headers = account.headers("billing" if base == BILL_BASE else "chat")
    try:
        d = _post(account, "/v2/report", events, headers=headers, base=base)
        return d.get("code") == 0
    except Exception:
        return False


def _progress_one(account, task, logs, gap=1.0):
    """推进单个任务（点亮 → 等落账 → 领奖），返回本次到账积分。

    auto 类任务（first_buddy）不接受接取、事件直接点亮，必须先于其他任务完成。
    unforgeable 与桌面专属任务在这里诚实跳过。
    """
    code = task["task_code"]
    spec = TASK_SPECS.get(code)
    if not spec or spec.get("unforgeable"):
        if spec and spec.get("reason"):
            logs.append("⏭ 任务 [%s] 需真实操作完成: %s, 跳过"
                        % (spec.get("name") or code, spec["reason"]))
        return 0

    status = task["status"]
    cur = task.get("current", 0)
    tgt = task.get("target", 1)

    if status == "claimed":
        return 0

    # 已完成的任务先领奖——桌面端/夜间任务也可能被真实操作点亮
    if status == "completed" or cur >= tgt:
        res = claim_task(account, code)
        if res.get("ok"):
            credit = res.get("credit", 0)
            logs.append("✓ 任务 [%s] 领奖成功: +%s 积分" % (spec["name"], credit))
            time.sleep(gap)
            return credit
        logs.append("! 任务 [%s] 领奖失败: %s"
                    % (spec["name"], res.get("msg") or "未知原因"))
        time.sleep(gap)
        return 0

    # auto 类之外的任务未接取时上报不计进度
    if status == "not_accepted" and task.get("task_type") != "auto":
        logs.append("⏭ 任务 [%s] 仍未接取, 跳过 (先解决接取失败)" % spec["name"])
        return 0

    if code in DESKTOP_ONLY_TASKS:
        jump = task.get("jump_url") or "workbuddy://chat"
        logs.append("⏭ 任务 [%s] 需真实操作完成: %s (深链 %s), 跳过事件伪造"
                    % (spec["name"], DESKTOP_ONLY_TASKS[code], jump))
        return 0

    need = max(1, tgt - cur)
    kind = spec.get("kind")
    logs.append("正在点亮任务 [%s] (需上报 %d 次)..." % (spec["name"], need))
    report_ok = True
    id_pool = None
    if kind in ("expert", "team"):
        id_pool = TEAM_ID_POOL if kind == "team" else EXPERT_ID_POOL
    for i in range(need):
        expert = None
        if id_pool:
            pid, pnm = id_pool[(cur + i) % len(id_pool)]
            expert = (pid, pnm)
        ev = build_event(account, kind, idx=i, expert=expert)
        if not report_events(account, [ev]):
            report_ok = False
        if i < need - 1:
            time.sleep(gap)
    if not report_ok:
        logs.append("! 任务 [%s] 部分事件上报失败 (上游拒绝), 继续尝试领奖" % spec["name"])
    time.sleep(1.5)

    # 落账动态等待（上游 v1.7.12）：进度通常 1-3 秒可见，先快查；只有确实在动
    # 才继续等，免得每个卡住的任务都空等二十秒。
    prog = cur
    for attempt in range(6):
        fresh = next((x for x in fetch_growth_tasks(account)
                      if x["task_code"] == code), None)
        if fresh:
            prog = fresh.get("current", 0)
            if prog >= tgt or fresh.get("status") in ("completed", "claimed"):
                break
            if prog > cur:
                time.sleep(2.5)
                continue
        if attempt < 2:
            time.sleep(1.5)
        else:
            break
    if prog < tgt:
        logs.append("? 任务 [%s] 已上报但进度 %s/%s 未达成, 领奖顺延到下次运行"
                    % (spec["name"], prog, tgt))
        time.sleep(gap)
        return 0

    res = claim_task(account, code)
    if res.get("ok"):
        credit = res.get("credit", 0)
        logs.append("✓ 任务 [%s] 点亮并领奖成功: +%s 积分" % (spec["name"], credit))
        time.sleep(gap)
        return credit
    logs.append("! 任务 [%s] 进度已达 %s/%s 但领奖失败: %s"
                % (spec["name"], prog, tgt, res.get("msg") or "未知原因"))
    time.sleep(gap)
    return 0


def run_growth_tasks(account, gap=1.0):
    """完整执行一批成长任务的点亮与领奖。"""
    if account.realm != "cn":
        return {"ok": False, "msg": "国际版不适用国内成长任务中心", "logs": []}
    if is_enterprise(account):
        return {"ok": True, "msg": "企业版账号无成长体系，跳过", "logs": []}

    logs = ["开始为账号 %s 运行成长任务自动化..."
            % (account.nickname or account.uid[:8])]
    tasks = fetch_growth_tasks(account)
    if not tasks:
        logs.append("未能获取到任务清单，请检查网络或账号状态")
        return {"ok": False, "logs": logs, "earned_credit": 0}

    total_earned = 0

    # 0. auto 类任务（first_buddy）不接受接取，且是其他任务与猫猫旅行的前置
    for task in tasks:
        if task.get("task_type") == "auto":
            total_earned += _progress_one(account, task, logs, gap)

    # 1. 批量接取未接任务（分批 chunk=20；夜猫子由夜间窗口专属卡片负责）
    def needs_accept(item):
        return (item["status"] == "not_accepted" and not item.get("unforgeable")
                and item.get("task_type") != "auto"
                and item["task_code"] not in NIGHT_TASK_CODES)

    unaccepted = [t["task_code"] for t in tasks if needs_accept(t)]
    pending_accept = set()
    if unaccepted:
        logs.append("发现 %d 个待接取任务，正在分批接取..." % len(unaccepted))
        result = accept_tasks(account, unaccepted)
        if result.get("failed"):
            reason = result.get("msg") or ("; ".join(result.get("reasons") or [])[:160])
            logs.append("! 接取未成功 %d 个%s"
                        % (len(result["failed"]),
                           ("（%s）" % reason) if reason else ""))
        if result.get("accepted"):
            logs.append("✓ 已接取 %d 个任务" % len(result["accepted"]))
        tasks = fetch_growth_tasks(account)
        # 复核一次：上游偶尔瞬时拒绝整个批次
        still = [t["task_code"] for t in tasks if needs_accept(t)]
        if still:
            logs.append("仍有 %d 个未接取，重试接取一次..." % len(still))
            retry = accept_tasks(account, still)
            if retry.get("accepted"):
                logs.append("✓ 重试接取成功 %d 个" % len(retry["accepted"]))
        confirmed, pending = _wait_accepted(account, unaccepted)
        if pending:
            pending_accept = set(pending)
            logs.append("其中 %d 个接取未生效，本轮跳过上报，下次自动重试" % len(pending))
        tasks = fetch_growth_tasks(account)

    stuck = []
    # 2. 处理每个任务（auto 已处理；夜猫与旅行各有专属卡片）
    for task in tasks:
        code = task["task_code"]
        spec = TASK_SPECS.get(code)
        if not spec or spec.get("unforgeable") or code in NIGHT_TASK_CODES:
            continue
        if code in pending_accept and task["status"] == "not_accepted":
            stuck.append(spec["name"])
            continue
        if task.get("task_type") == "auto":
            continue
        total_earned += _progress_one(account, task, logs, gap)

    account.fetch_credits()
    remain = (account.credits or {}).get("remain", 0)
    if stuck:
        logs.append("本次到账: +%d 积分，当前总剩余: %s 积分；%d 个任务暂未达标（%s），"
                    "待下次运行确认" % (total_earned, remain, len(stuck), "、".join(stuck)))
    else:
        logs.append("🎉 全部完成！本次累计新增到账: +%d 积分，当前总剩余: %s 积分"
                    % (total_earned, remain))
    return {"ok": True, "logs": logs, "earned_credit": total_earned,
            "stuck_tasks": stuck, "credits": account.credits}


# ---------------------------------------------------------------- 活跃上报
def run_activity_report(account, count=1, gap=1.0):
    """定时活跃上报：查连续打卡 → 上报 count 条对话事件 → 复查打卡。

    平台 2026-09 起要求真实对话才计入；纯事件上报连续天数不再推进时如实给
    warn，不谎报成功（二开自验证结论）。
    """
    if account.realm != "cn":
        return {"ok": False, "action": "skip", "code": -2,
                "msg": "国际版无国内成长中心活跃上报，已跳过", "warn": False}
    if is_enterprise(account):
        return {"ok": True, "action": "skip", "code": 0,
                "msg": "企业版账号无成长体系，跳过", "warn": False}
    try:
        n = max(1, min(50, int(count or 1)))
    except (TypeError, ValueError):
        n = 1

    before = fetch_growth_summary(account).get("streak_days", 0)
    sent = 0
    for i in range(n):
        ev = build_event(account, "chat", idx=i)
        if report_events(account, [ev]):
            sent += 1
        if i < n - 1:
            time.sleep(gap)
    time.sleep(1.5)

    after = fetch_growth_summary(account).get("streak_days", 0)
    if sent < n:
        return {"ok": False, "action": "report", "code": -7, "warn": False,
                "msg": "活跃上报部分失败（%d/%d 条成功）" % (sent, n)}
    if after == 0 and before == 0:
        return {"ok": True, "action": "report", "code": 0, "warn": True,
                "msg": "活跃上报完成（%d/%d），但连续天数仍为 0（疑似被静默丢弃）"
                       % (sent, n)}
    if after <= before:
        return {"ok": True, "action": "report", "code": 0, "warn": True,
                "msg": "活跃上报完成（%d/%d），但连续天数未推进（%s→%s 天），"
                       "可能当日已计入或上报未被采纳" % (sent, n, before, after)}
    return {"ok": True, "action": "report", "code": 0, "warn": False,
            "msg": "活跃上报完成（%d/%d），连续打卡 %s 天" % (sent, n, after)}


def classify_activity(account, result):
    """活跃上报结果分类 -> (status, message)。"""
    result = result or {}
    if result.get("ok"):
        return ("warn" if result.get("warn") else "ok"), result.get("msg")
    return "error", result.get("msg") or "活跃上报失败"


# ---------------------------------------------------------------- 面板进度
_progress_cache = {"ts": 0.0, "data": None}
_progress_lock = threading.Lock()


def progress_all(pool, ttl=60):
    """全部国内版账号各自的成长任务实时进度（带 TTL 缓存）。"""
    now = time.time()
    with _progress_lock:
        if _progress_cache["data"] is not None and now - _progress_cache["ts"] < ttl:
            return _progress_cache["data"]
    accounts = [a for a in (pool.accounts if pool else [])
                if getattr(a, "realm", "") == "cn"
                and getattr(a, "enabled", False)
                and bool(getattr(a, "access_token", ""))]
    result = {"accounts": [], "fetched_at": int(now)}
    for acc in accounts:
        item = {"uid": acc.uid, "nickname": acc.nickname or (acc.uid or "")[:8],
                "realm": acc.realm}
        try:
            item["tasks"] = fetch_growth_tasks(acc)
            summary = fetch_growth_summary(acc)
            item["streak_days"] = summary.get("streak_days", 0)
            item["energy"] = summary.get("energy", 0)
            travel = summary.get("travel") or {}
            item["travel_state"] = travel.get("state", "unknown")
            item["travel_credit"] = travel.get("reward_credit", 0)
            item["ok"] = True
        except Exception as exc:
            item["ok"] = False
            item["error"] = str(exc)[:200]
            item["tasks"] = []
        result["accounts"].append(item)
    with _progress_lock:
        _progress_cache["ts"] = now
        _progress_cache["data"] = result
    return result


def invalidate_progress():
    with _progress_lock:
        _progress_cache["ts"] = 0.0


# ---------------------------------------------------------------- 手动任务作业
_jobs = {}
_jobs_lock = threading.Lock()
_run_lock = threading.Lock()


def growth_job_get(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _job_update(job_id, **fields):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            job.update(fields)


def _prune_jobs():
    with _jobs_lock:
        finished = sorted(jid for jid, job in _jobs.items() if job.get("finished"))
        for jid in finished[:-10]:
            _jobs.pop(jid, None)


def start_growth_job(pool, realm=GROWTH_REALM):
    """启动一次「一键完成成长任务」后台作业，返回 job_id 或错误。"""
    if realm != GROWTH_REALM:
        return {"ok": False, "msg": "成长任务只适用于国内版出口"}
    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "msg": "已有一轮成长任务在执行，请稍候再试"}
    accounts = [a for a in (pool.accounts if pool else [])
                if a.realm == realm and a.enabled and a.access_token]
    job_id = "growth-%d" % int(time.time() * 1000)
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "finished": False, "ok": None,
                         "logs": [], "done": 0, "total": len(accounts),
                         "current": "", "earned": 0, "ok_n": 0, "fail_n": 0}
    threading.Thread(target=_run_growth_job, args=(job_id, accounts),
                     daemon=True).start()
    return {"ok": True, "job_id": job_id}


def _run_growth_job(job_id, accounts):
    """后台线程：顺序执行全部账号，单账号异常只记失败并继续。

    跨账号执行骨架统一走 TaskRunner（与调度器同源）；本函数只保留成长任务
    自己的 job 进度回写与收尾。TaskRunner.run 不使用 ctx/log，传 None 即可。
    """
    from tasks import taskstore

    total = len(accounts)
    tally = {"ok": 0, "fail": 0, "earned": 0}
    all_logs = []

    def before_account(index, acc):
        _job_update(job_id, done=index, current=(acc.nickname or acc.uid or "")[:16])

    def action(acc):
        try:
            return run_growth_tasks(acc, gap=1.0) or {}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def classify_growth(acc, res):
        res = res or {}
        earned = int(res.get("earned_credit") or 0) if res.get("ok") else 0
        if res.get("ok"):
            return "ok", "[成长任务] 一键完成，收益 +%d 积分" % earned, earned
        return ("error", "[成长任务] 执行失败: %s"
                % (res.get("error") or res.get("msg") or "未知原因"), 0)

    def after_account(index, acc, res, status, earned, message):
        if status == "ok":
            tally["ok"] += 1
            tally["earned"] += earned
        else:
            tally["fail"] += 1
        all_logs.extend((res or {}).get("logs") or [])
        if index < total - 1:
            all_logs.append("")
        _job_update(job_id, done=index + 1, logs=list(all_logs),
                    ok_n=tally["ok"], fail_n=tally["fail"],
                    earned=tally["earned"])

    try:
        TaskRunner(None).run(
            kind="summary", accounts=accounts, ready=lambda acc: True,
            action=action, classify=classify_growth, source="manual", realm="cn",
            gap=lambda index: 1.0, before_account=before_account,
            after_account=after_account, write_summary=False)
        ok_n, fail_n, total_earned = tally["ok"], tally["fail"], tally["earned"]
        taskstore.add_log(
            kind="summary", source="manual", realm="cn",
            level="warn" if fail_n else "ok", credits=0,
            message="[成长任务] 共 %d 个账号顺序执行：成功 %d，失败 %d，合计 +%d 积分"
                    % (len(accounts), ok_n, fail_n, total_earned))
        invalidate_progress()
        all_logs.append("🎉 全部账号执行完毕：成功 %d / 失败 %d，合计新增 +%d 积分"
                        % (ok_n, fail_n, total_earned))
        _job_update(job_id, finished=True, ok=(fail_n == 0),
                    logs=all_logs, done=len(accounts), current="")
        _prune_jobs()
    finally:
        try:
            _run_lock.release()
        except RuntimeError:
            pass
