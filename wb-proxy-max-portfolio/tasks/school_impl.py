"""tasks/school_impl.py —— 国内版小程序「开学季活动」自动化（school_open_day_2026）

完整移植自上游 workbuddy2api 容器内的 scripts/school_open_day_2026.py（纯
标准库 Python），适配为本项目的账号对象与任务记录体系：

1. 任务中心：viewed 接取 -> 完成判据（share-complete / 事件上报）-> claim 领奖
   - share_invite:   share-complete HTTP 端点点亮
   - chat_3_times:   小程序 chat_request_send 事件 ×3（必须带 activityId）
   - desktop_chat_1_time: 桌面 6 连事件链一次（走 copilot 域上报）
   - expert_use:     开学季专家（BackToSchool 分类）expert_actual_use 事件
   - task_student_verify: 学生认证属人工环节，不碰、不伪造
2. 幸运大转盘：领奖发放抽奖次数，抽到余额为 0 为止（40900 = no chance 安全停；
   余额不递减 3 次判定服务端异常提前停）。
3. 活动非进行期（in_period=false）整段跳过不算失败；未知任务码保守跳过。

积分收益主要来自转盘抽奖（6/66 积分），领奖本身发抽奖机会。
写动作间隔默认 1.5 秒（最小 1.0），与上游脚本一致。
"""
import hashlib
import json
import time
import urllib.error
import urllib.request
import uuid

from auth import identity as wb_identity

# --------------------------------------------------------------------------
# 端点与常量（与上游脚本一致；域名单源自 tasks.growth，避免散抄）
# --------------------------------------------------------------------------
from tasks.growth import BILL_BASE as CLOUD_AGENT  # 小程序 / 专家 / report 域
from tasks.growth import CHAT_BASE as COPILOT      # 桌面事件上报域
SCHOOL = CLOUD_AGENT + "/portal/activity/school"

ACTIVITY_ID = "school_open_day_2026"              # 事件 activityId 字段值

MP_UA = ("Mozilla/5.0 (Linux; Android 14; MicroMessenger/8.0.49 WeChat/0.8.0 "
         "MiniProgramEnv/android; wkbrowser xweb)")
#: 本模块只跑国内版，桌面端 UA 与 wb_identity 同一来源。
DESKTOP_UA = wb_identity.DESKTOP_UA_CN

# task_code -> 处理方式。manual=人工环节跳过；share=端点点亮；report=事件上报点亮。
# 未在表内（服务端新增任务）保守按 unknown 跳过。
KNOWN_TASKS = {
    "task_student_verify": {"mode": "manual", "note": "微信学生认证（人工，不碰）"},
    "share_invite": {"mode": "share", "report_kind": None},
    "chat_3_times": {"mode": "report", "report_kind": "mini_chat"},
    "desktop_chat_1_time": {"mode": "report", "report_kind": "desktop_seq"},
    "expert_use": {"mode": "report", "report_kind": "expert"},
}

# 转盘奖品映射（未知 prize_code 显示原码，不编造）
LOTTERY_PRIZE_LABELS = {
    "school_credit_6": {"label": "6积分", "type": "credit"},
    "school_credit_66": {"label": "66积分", "type": "credit"},
    "school_voucher_luckin": {"label": "瑞幸咖啡15元券", "type": "voucher"},
    "school_voucher_kfc_ok": {"label": "肯德基OK餐券", "type": "voucher"},
    "school_voucher_kfc_ice": {"label": "肯德基冰淇淋券", "type": "voucher"},
    "school_voucher_kugou": {"label": "酷狗会员月卡券", "type": "voucher"},
}

SCHOOL_EXPERT_CATEGORY = "16-BackToSchool"
SCHOOL_EXPERT_FALLBACK = {
    "ex_jB0dyFIQJEWa": {"name": "论小舟", "title": "论文写作导师"},
    "ex_lQjkerakvIex": {"name": "英语学习教练", "title": "大学英语学习教练"},
}


class AuthError(RuntimeError):
    """鉴权 / 未绑定微信类硬错误（不重试）。"""


class TransientError(RuntimeError):
    """网络 / 5xx 可重试错误。"""


def derive_id(auth, salt):
    """由 uid 稳定派生设备标识（事件 machineId 用，与上游脚本一致）。"""
    return hashlib.md5(("%s:%s" % (salt, auth["uid"])).encode()).hexdigest()[:36]


def prize_text(prize_code, credit_amount):
    info = LOTTERY_PRIZE_LABELS.get(prize_code)
    if not info:
        return str(prize_code)
    if info["type"] == "credit":
        return "%s（+%s Credit）" % (info["label"], credit_amount)
    return info["label"]


# --------------------------------------------------------------------------
# HTTP（与上游脚本相同的重试语义：网络错误与 5xx 重试，4xx 不重试）
# --------------------------------------------------------------------------
def _headers(token, extra=None):
    h = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": MP_UA,
    }
    if extra:
        h.update(extra)
    return h


def _request(token, method, url, body=None, headers=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(token, headers),
                                 method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                return r.status, {"raw": raw.decode("utf-8", "replace")[:300]}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return e.code, {}
    except urllib.error.URLError as e:
        raise TransientError(repr(e.reason))
    except Exception as e:
        raise TransientError(repr(e))


def request_retry(token, method, url, body=None, headers=None, retries=3, gap=1.0):
    last = None
    for i in range(1, retries + 1):
        try:
            return _request(token, method, url, body, headers)
        except TransientError as e:
            last = e
            if i < retries:
                time.sleep(gap * i)
    raise last


def interpret_failure(st, r):
    """把失败响应翻译成一句话；(msg, is_auth)。"""
    code = r.get("code") if isinstance(r, dict) else None
    msg = ""
    if isinstance(r, dict):
        msg = r.get("message") or r.get("msg") or r.get("raw") or ""
    if st == 401 or code in ("401", 401, "40100", 40100):
        return "未绑定微信或 token 失效", True
    if st == 403:
        return "403 forbidden", True
    if st == 404:
        return "404 路由不存在（活动可能已下线）", False
    if code in ("41000", 41000):
        return "活动未开始或已结束", False
    if code in ("40901", 40901):
        return "任务暂不可领取（未完成或已领）", False
    return "http=%s code=%s %s" % (st, code, str(msg)[:120]), False


def _ok(st, r):
    return st == 200 and isinstance(r, dict) and r.get("code") in (0,)


def _raise_for(st, r, what):
    msg, is_auth = interpret_failure(st, r)
    raise (AuthError if is_auth else RuntimeError)("%s %s" % (what, msg))


# --------------------------------------------------------------------------
# 活动端点
# --------------------------------------------------------------------------
def fetch_school_tasks(token):
    """GET /tasks -> (tasks, in_period)。"""
    st, r = request_retry(token, "GET", SCHOOL + "/tasks")
    if not _ok(st, r):
        _raise_for(st, r, "school/tasks")
    data = (r or {}).get("data") or {}
    return data.get("tasks") or [], bool(data.get("in_period"))


def post_viewed(token, code):
    """POST /tasks/{code}/viewed —— 接任务（pending -> in_progress）。"""
    st, r = request_retry(token, "POST", "%s/tasks/%s/viewed" % (SCHOOL, code))
    if not _ok(st, r):
        _raise_for(st, r, "viewed %s" % code)


def post_share_complete(token):
    """POST /tasks/share-complete —— share_invite 完成判据。"""
    st, r = request_retry(token, "POST", SCHOOL + "/tasks/share-complete",
                          {"channel": "wechat"})
    if not _ok(st, r):
        _raise_for(st, r, "share-complete")


def post_claim(token, code):
    """POST /tasks/{code}/claim —— 领奖（发抽奖机会）。"""
    st, r = request_retry(token, "POST", "%s/tasks/%s/claim" % (SCHOOL, code))
    if not _ok(st, r):
        _raise_for(st, r, "claim %s" % code)


def fetch_lottery_config(token):
    """GET /config -> (config, chance)。chance.balance 即抽奖次数余额。"""
    st, r = request_retry(token, "GET", SCHOOL + "/config")
    if not _ok(st, r):
        _raise_for(st, r, "config")
    data = (r or {}).get("data") or {}
    return data, (data.get("chance") or {})


def post_lottery_draw(token, draw_uuid):
    """POST /wheel/draw —— 抽一次。余额 0 时返回 HTTP 409 code=40900。"""
    return request_retry(token, "POST", SCHOOL + "/wheel/draw", {"draw_uuid": draw_uuid})


# --------------------------------------------------------------------------
# 事件构造（全部带 activityId，否则服务端不关联活动任务）
# --------------------------------------------------------------------------
def mini_chat_event(auth, conversation_id):
    now = int(time.time() * 1000)
    return {
        "eventCode": "chat_request_send", "timestamp": now, "reportDelay": 0,
        "source": "mini_program", "ideName": "wx_app_cloud", "ideType": "WorkBuddy_MP",
        "extName": "workbuddy-mp", "extVersion": "SaaS", "mode": "chat",
        "conversationId": conversation_id, "requestId": conversation_id,
        "inputLength": 12,
        "activityId": ACTIVITY_ID, "mentionContexts": [], "mentionContextCount": 0,
        "userId": auth["uid"],
    }


def desktop_fingerprint(auth):
    now = int(time.time() * 1000)
    return {
        "timezone": "Asia/Shanghai", "reportDelay": 2000,
        "userId": auth["uid"], "username": auth.get("nick", ""),
        "userNickname": auth.get("nick", ""),
        "product": "SaaS", "releaseDate": 1789036585355,
        "commit": "5f9692923c93033111c51ad7b003eb80204a9b75",
        "ideName": "WorkBuddy", "ideType": "WorkBuddy", "ideVersion": "5.5.6",
        "machineId": derive_id(auth, "machine"), "sessionId": derive_id(auth, "session"),
        "extName": "workbuddy-desktop", "extVersion": "5.5.6",
        "os": "win32", "arch": "x64", "osVersion": "10.0.26220",
        "cpuCores": 20, "memorySize": 24,
        "timestamp": now, "presentAt": now,
    }


def desktop_chat_sequence(auth, conversation_id, request_id, message_id):
    """桌面端成功对话 6 连事件链（一次 6 连 = 一次桌面对话）。"""
    now = int(time.time() * 1000)
    ev = []

    def mk(code, extra):
        e = {"eventCode": code}
        e.update(extra)
        ev.append(e)

    mk("agent_task_created", {
        "source": "LOCAL", "name": "working", "task_target": "local", "mode": "craft",
        "requestModelId": "fast-model", "requestModelName": "fast-model",
        "has_repo": False, "repo_type": "none", "workspace_type": "empty",
        "has_connector": False, "connector_types": [],
        "has_mention": False, "mention_types": [],
        "has_template": False, "action": "", "template_name": "",
        "has_expert": False, "expert_id": "", "expert_name": "", "expert_industry_id": "",
        "has_skill": False, "skill_names": [],
        "conversationId": conversation_id, "messageId": message_id,
        "buddyId": "", "buddyName": "",
    })
    mk("chat_message_send", {
        "messageId": message_id + "-assistant", "historyCount": 0,
        "isContextTruncated": False, "currentStepCount": 1,
        "traceId": request_id, "rootRequestId": request_id,
        "parentConversationId": conversation_id,
        "agentName": "cli", "agentType": "main",
    })
    mk("chat_request_send", {
        "inputLength": 24, "isPlan": False, "isAutoExecuteTerminal": False,
        "isAutoModify": False, "codebaseEnable": False, "maxToken": 0,
        "maxSteps": 500, "temperature": 0, "maxRetries": 0,
        "mentionContexts": [], "knowledgeId": [], "knowledgeName": [],
        "codebaseId": "", "mentionContextCount": 0, "command": "",
        "recommendId": "", "skillId": "", "skillCount": 0, "totalCount": 0,
        "traceId": request_id, "rootRequestId": request_id,
        "parentConversationId": conversation_id,
        "agentName": "cli", "agentType": "main",
        "codebuddy.session_id": conversation_id,
        "codebuddy.conversation_request_id": request_id,
    })
    mk("chat_message_response", {
        "messageId": message_id + "-assistant", "responseModelId": "fast-model",
        "inputToken": 120, "outputToken": 80, "totalToken": 200,
        "cachedTokens": 0, "cachedWriteTokens": 0, "cachedMissTokens": 0,
        "isSuccessful": True, "messageErrorCode": "", "finishReason": "stop",
        "firstTokenAt": now, "traceId": request_id,
        "conversationId": conversation_id,
        "rootRequestId": request_id, "parentConversationId": conversation_id,
        "agentName": "cli", "agentType": "main",
        "codebuddy.session_id": conversation_id,
        "codebuddy.conversation_request_id": request_id,
    })
    mk("chat_message_status", {
        "messageId": message_id + "-assistant", "messageErrorCode": "0",
        "traceId": request_id, "rootRequestId": request_id,
        "parentConversationId": conversation_id,
        "agentName": "cli", "agentType": "main",
    })
    mk("chat_request_response", {
        "mode": "craft", "toolCallCount": 0,
        "inputToken": 120, "outputToken": 80, "totalToken": 200,
        "cachedTokens": 0, "cachedWriteTokens": 0, "cachedMissTokens": 0,
        "isSuccessful": True, "messageErrorCode": "", "finishReason": "stop",
        "rootRequestId": request_id, "parentConversationId": conversation_id,
    })
    return ev


def fetch_school_expert(token):
    """拉一个 BackToSchool 分类专家；失败回落已知专家。"""
    body = {"edition_mode": "all,domestic", "page": 1, "page_size": 20,
            "sort_by": "use_count", "sort_order": "desc",
            "categories": [SCHOOL_EXPERT_CATEGORY], "expert_type": "agent"}
    try:
        st, r = request_retry(token, "POST",
                              CLOUD_AGENT + "/v2/operation-platform/market/expert/list", body)
        if _ok(st, r):
            for e in ((r.get("data") or {}).get("experts") or []):
                eid = e.get("expert_id")
                if not eid:
                    continue
                dn_raw = e.get("display_name_zh") or {}
                dn = (dn_raw.get("zh") if isinstance(dn_raw, dict) else dn_raw) or eid
                return eid, dn
    except (AuthError, RuntimeError):
        pass
    for eid, info in SCHOOL_EXPERT_FALLBACK.items():
        return eid, info["name"]
    raise RuntimeError("无可用开学季专家")


def make_report_events(auth, kind):
    """按任务 kind 构造上报事件数组。返回 (events, host, extra_headers)。"""
    now = int(time.time() * 1000)
    if kind == "mini_chat":
        return [mini_chat_event(auth, "wbmp-%d" % now)], CLOUD_AGENT, None
    if kind == "expert":
        eid, name = fetch_school_expert(auth["token"])
        conv = "wbexp-%d" % now
        event = {
            "eventCode": "expert_actual_use", "timestamp": now, "reportDelay": 0,
            "source": "mini_program", "ideName": "wx_app_cloud", "ideType": "WorkBuddy_MP",
            "extName": "workbuddy-mp", "extVersion": "SaaS",
            "machineId": derive_id(auth, "machine"), "os": "android", "osVersion": "14",
            "arch": "arm64", "timezone": "Asia/Shanghai",
            "userId": auth["uid"], "userNickname": auth.get("nick", ""),
            "id": eid, "name": eid, "expertTitle": name,
            "type": "send_message", "characterCount": 12, "expertType": "agent",
            "conversationId": conv,
            "activityId": ACTIVITY_ID,
        }
        return [event], CLOUD_AGENT, None
    if kind == "desktop_seq":
        conv = "wbdesk-%d" % now
        seq = desktop_chat_sequence(auth, conv, conv, conv)
        fp = desktop_fingerprint(auth)
        events = []
        for e in seq:
            m = dict(e)
            m.update(fp)
            m["activityId"] = ACTIVITY_ID
            events.append(m)
        # 桌面上报走 copilot 域；发 codebuddy.cn 域不点亮桌面任务
        return events, COPILOT, {"X-Product": "SaaS", "User-Agent": DESKTOP_UA}
    raise ValueError("未知 report_kind: %s" % kind)


def _report_events(token, events, host, extra_headers=None):
    st, r = request_retry(token, "POST", host + "/v2/report", events, headers=extra_headers)
    if not _ok(st, r):
        _raise_for(st, r, "report %d 事件" % len(events))


# --------------------------------------------------------------------------
# 单账号执行入口（调度器调用）
# --------------------------------------------------------------------------
def run_school_for_account(acc, gap=1.5):
    """逐账号执行开学季任务点亮 + 领奖 + 转盘抽空。

    返回 {"ok", "in_period", "claimed", "lottery", "msg", "error"}：
      claimed = 已领奖的任务码列表；lottery = {"draws", "credit", "prizes"}。
    活动非进行期返回 ok=True + in_period=False（跳过，不算失败）。
    """
    if gap < 1.0:
        gap = 1.0  # 写操作间隔 ≥1s（与上游脚本一致）
    auth = {"token": acc.access_token, "uid": acc.uid, "nick": acc.nickname or ""}
    out = {"ok": True, "in_period": False, "claimed": [],
           "lottery": {"draws": 0, "credit": 0, "prizes": []}, "msg": "", "error": ""}

    try:
        tasks, in_period = fetch_school_tasks(auth["token"])
    except AuthError as e:
        out["ok"] = False
        out["error"] = str(e)
        return out
    except RuntimeError as e:
        out["ok"] = False
        out["error"] = str(e)
        return out
    if not in_period:
        out["msg"] = "活动非进行期（in_period=false），跳过"
        return out
    out["in_period"] = True

    def refetch(code):
        try:
            ts, _ = fetch_school_tasks(auth["token"])
            return next((x for x in ts if x.get("task_code") == code), None)
        except (AuthError, RuntimeError):
            return None

    # ---- 任务循环 ----
    for t in tasks:
        code = t.get("task_code") or ""
        if not code:
            continue
        status = (t.get("status") or "?").lower()
        spec = KNOWN_TASKS.get(code, {})
        mode = spec.get("mode", "unknown")
        if status in ("completed", "claimed"):
            continue
        if mode in ("manual", "unknown"):
            continue  # 人工环节 / 未知任务：保守跳过
        try:
            if status == "pending":
                post_viewed(auth["token"], code)
                time.sleep(gap)
            cur_prog = t.get("progress") or 0
            if mode == "share":
                rounds = 1
            elif spec.get("report_kind") == "desktop_seq":
                rounds = 1  # 桌面 6 连一次 = 一次桌面对话
            else:
                rounds = max(1, (t.get("target_count") or 1) - cur_prog)
            progress_changed = False
            after = status
            for ri in range(rounds):
                if mode == "share":
                    post_share_complete(auth["token"])
                else:
                    events, host, extra_h = make_report_events(auth, spec.get("report_kind"))
                    _report_events(auth["token"], events, host, extra_h)
                time.sleep(gap)
                t2 = refetch(code)
                if not t2:
                    continue
                after_prog = t2.get("progress") or 0
                after = (t2.get("status") or "?").lower()
                if after_prog > cur_prog:
                    cur_prog = after_prog
                    progress_changed = True
                if after in ("completed", "claimed") or after_prog >= (t.get("target_count") or 1):
                    break
            t2 = refetch(code)
            after = (t2.get("status") or "?").lower() if t2 else after
            if after == "completed" or (progress_changed and after != "claimed"):
                if after == "completed":
                    post_claim(auth["token"], code)
                    out["claimed"].append(code)
                    time.sleep(gap)
        except AuthError as e:
            out["ok"] = False
            out["error"] = "%s: %s" % (code, e)
            return out
        except RuntimeError as e:
            # 单任务失败继续下一个任务
            out.setdefault("task_errors", []).append("%s: %s" % (code, e))

    # ---- 转盘抽奖：抽到余额为 0 为止 ----
    try:
        cfg, chance = fetch_lottery_config(auth["token"])
    except (AuthError, RuntimeError) as e:
        out["lottery"]["error"] = str(e)
        return out
    if not cfg.get("in_period"):
        return out
    bal = chance.get("balance") or 0
    prev_bal = bal
    stall = 0
    while bal > 0:
        try:
            st, r = post_lottery_draw(auth["token"], str(uuid.uuid4()))
        except (AuthError, RuntimeError) as e:
            out["lottery"]["error"] = str(e)
            break
        code = r.get("code") if isinstance(r, dict) else None
        if not _ok(st, r):
            if code == 40900:
                bal = 0  # 次数耗尽边界，正常结束
            else:
                out["lottery"]["error"] = interpret_failure(st, r)[0]
            break
        d = (r or {}).get("data") or {}
        prize_code = d.get("prize_code") or "?"
        credit = d.get("credit_amount") or 0
        bal = d.get("chance_balance", bal)
        if bal >= prev_bal:
            stall += 1
            if stall >= 3:  # 余额未递减：服务端异常，防死循环
                out["lottery"]["error"] = "抽奖余额未递减（服务端异常），提前停止"
                break
        else:
            stall = 0
        prev_bal = bal
        out["lottery"]["draws"] += 1
        out["lottery"]["credit"] += int(credit or 0)
        out["lottery"]["prizes"].append(prize_text(prize_code, credit))
        if bal > 0:
            time.sleep(gap)
    return out
