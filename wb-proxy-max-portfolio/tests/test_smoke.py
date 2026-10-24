# -*- coding: utf-8 -*-
"""tests/test_smoke.py —— 网关冒烟总入口

按渠道拆分后的结构：
- 共享启动 / 请求 / 断言：tests/harness.py
- 假上游：tests/upstreams/<channel>.py
- 渠道专属检查：tests/channels/<channel>.py
- 本文件：装配、核心 / WorkBuddy 检查、跨渠道面板清单检查与总汇总

    python tests/test_smoke.py
"""
import base64
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.channels import codearts, loomy, qoder, trae, zcode
from tests.harness import (
    SmokeEnv, build_gateway, check, failures, parse_sse, request,
    start_upstreams,
)
from tests.upstreams.workbuddy import (CHECKIN_STATE, CUT_STATE, FAIL_MODE,
                                        STREAK_STATE)


def _unsigned_jwt(claims):
    """测试用的无签名 JWT：只用于验证声明读取，不参与上游校验。"""
    def enc(value):
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return "%s.%s.sig" % (enc({"alg": "none"}), enc(claims))


def _trigger_and_settle(ctx, task_id, deadline=8.0):
    """触发一个调度任务并等它真的跑完；返回 (触发返回, 是否在窗口内收尾)。

    任务在后台串行执行、点击即返回，所以「排队成功」不等于「这一步已经结束」。
    不等收尾就断言，迟到的落盘会污染后面的用例：签到任务收尾时写回的
    `last_checkin` 恰好会落在下面「pending 不该写标记」的断言里，看起来就像
    产品把处理中的回执记成了已签。任务跑完会把 last_results[task_id] 换成
    新的一份，按对象身份判断，同一秒内的两次触发也不会看错。
    """
    handle = ctx.scheduler.last_results.get(task_id)
    result = ctx.scheduler.trigger_now(task_id)
    deadline_at = time.time() + deadline
    while time.time() < deadline_at:
        if ctx.scheduler.last_results.get(task_id) is not handle:
            return result, True
        time.sleep(0.2)
    return result, False


def main():
    upstreams = start_upstreams()
    bases = {name: base for name, (_server, base) in upstreams.items()}
    tmpdir = tempfile.mkdtemp(prefix="wbmax-smoke-")
    ctx, gateway, base = build_gateway(tmpdir, bases)
    key_headers = {"Authorization": "Bearer sk-test", "Content-Type": "application/json"}

    # ---- 1. 装配 ----
    status, body = request(base, "GET", "/health")
    health = json.loads(body) if status == 200 else {}
    check("health", status == 200 and health.get("ok") is True, body[:120])
    check("channel registered",
          health.get("channels") == ["workbuddy", "trae", "qoder", "qoder_intl",
                                     "zcode", "codearts", "loomy"],
          body[:120])
    check("scheduler 13 tasks", len(ctx.scheduler.task_specs()) == 13,
          str(len(ctx.scheduler.task_specs())))
    # 排程隔离不变量（首）：基线必须是暂停的，否则整点的真实排程会挤进单线程
    # 队列，把后面所有显式触发的等待窗口挤爆，失败还看不出是谁的锅。
    check("scheduler starts paused",
          ctx.automation_config().get("enabled") is False,
          json.dumps(ctx.automation_config().get("enabled")))

    # ---- 1b. 网络错误分类：OS 错误码优先于文案 ----
    import errno as errno_mod
    import socket as socket_mod
    from core import net as net_mod
    check("network reset is transient",
          net_mod.is_transient(urllib.error.URLError(
              OSError(errno_mod.ECONNRESET, "reset"))))
    check("local network outage is not an account fault",
          net_mod.looks_like_local_network(urllib.error.URLError(
              OSError(errno_mod.ENETUNREACH, "unreachable")))
          and net_mod.looks_like_local_network(
              urllib.error.URLError(socket_mod.gaierror(-2, "name")))
          and not net_mod.looks_like_local_network(urllib.error.URLError(
              OSError(errno_mod.ECONNREFUSED, "refused"))))

    # ---- 1c. 手机号脱敏：只认大陆手机号，不误伤订单号 ----
    from infra import privacy
    masked = privacy.mask_text("联系 13812345678 / 138-1234-5678，订单 23812345678")
    check("phone masked in text",
          masked == "联系 138****5678 / 138****5678，订单 23812345678", masked)
    source = {"nickname": "老王(13812345678)",
              "rows": [{"msg": "138 1234 5678"}]}
    redacted = privacy.redact(source)
    check("panel phone redaction copy-on-write",
          redacted is not source
          and redacted["nickname"] == "老王(138****5678)"
          and redacted["rows"][0]["msg"] == "138****5678"
          and source["nickname"] == "老王(13812345678)"
          and source["rows"][0]["msg"] == "138 1234 5678",
          json.dumps(redacted, ensure_ascii=False))
    uid_like_phone = "6ef20bf4-76fa-4085-b179-97517476cc1e"
    ident = privacy.redact({
        "uid": uid_like_phone, "accountId": uid_like_phone,
        "machineId": uid_like_phone, "nickname": "13812345678"})
    check("identifier keys keep uid untouched",
          ident["uid"] == uid_like_phone
          and ident["accountId"] == uid_like_phone
          and ident["machineId"] == uid_like_phone
          and ident["nickname"] == "138****5678",
          json.dumps(ident, ensure_ascii=False))
    check("identifier-adjacent digits are not masked",
          privacy.mask_text("id " + uid_like_phone) == "id " + uid_like_phone
          and privacy.mask_text("电话13812345678") == "电话138****5678",
          privacy.mask_text("id " + uid_like_phone))
    login_identity = privacy.redact({
        "loginAccount": "13812345678", "nickname": "13812345678"})
    check("login account stays copyable",
          login_identity["loginAccount"] == "13812345678"
          and login_identity["nickname"] == "138****5678",
          json.dumps(login_identity, ensure_ascii=False))

    # ---- 1d. 账号列登录身份：meta / 渠道令牌 / 昵称兜底 ----
    from auth import accounts as accounts_mod
    wb_intl = accounts_mod.Account({
        "uid": "identity-wb-intl", "nickname": "昵称", "realm": "intl",
        "accessToken": _unsigned_jwt({"email": "wb@example.com"})})
    wb_cn = accounts_mod.Account({
        "uid": "identity-wb-cn", "nickname": "昵称", "realm": "cn",
        "accessToken": _unsigned_jwt({"preferred_username": "13812345678"})})
    trae_identity = accounts_mod.Account({
        "uid": "identity-trae", "nickname": "昵称", "realm": "trae",
        "accessToken": _unsigned_jwt({"data": {"id": "13912345678"}})})
    ca_profile = base64.urlsafe_b64encode(json.dumps(
        {"account_name": "hw-login"}).encode("utf-8")).rstrip(b"=").decode("ascii")
    codearts_identity = accounts_mod.Account({
        "uid": "identity-ca", "nickname": "昵称", "realm": "codearts",
        "accessToken": _unsigned_jwt({"user_profile": ca_profile})})
    meta_identity = accounts_mod.Account({
        "uid": "identity-meta", "nickname": "昵称", "realm": "zcode",
        "meta": {"email": "zcode@example.com"}})
    qoder_identity = accounts_mod.Account({
        "uid": "identity-qoder", "nickname": "昵称", "realm": "qoder",
        "meta": {"loginAccount": "qoder@example.com"}})
    fallback_identity = accounts_mod.Account({
        "uid": "identity-fallback", "nickname": "普通昵称", "realm": "intl"})
    check("login identity from workbuddy token",
          wb_intl.public().get("loginAccount") == "wb@example.com"
          and wb_cn.public().get("loginAccount") == "13812345678",
          "%s / %s" % (wb_intl.public().get("loginAccount"),
                       wb_cn.public().get("loginAccount")))
    check("login identity from trae token",
          trae_identity.public().get("loginAccount") == "13912345678",
          str(trae_identity.public().get("loginAccount")))
    check("login identity from codearts token",
          codearts_identity.public().get("loginAccount") == "hw-login",
          str(codearts_identity.public().get("loginAccount")))
    check("login identity from persisted meta",
          meta_identity.public().get("loginAccount") == "zcode@example.com"
          and qoder_identity.public().get("loginAccount") == "qoder@example.com",
          "%s / %s" % (meta_identity.public().get("loginAccount"),
                       qoder_identity.public().get("loginAccount")))
    check("login identity falls back to nickname",
          fallback_identity.public().get("loginAccount") == "普通昵称",
          str(fallback_identity.public().get("loginAccount")))

    # ---- 2. 模型目录与标注 ----
    status, body = request(base, "GET", "/v1/models", headers=key_headers)
    models = json.loads(body) if status == 200 else {"data": []}
    ids = [item["id"] for item in models.get("data") or []]
    check("models list", status == 200 and "deepseek-v4.1-flash" in ids, body[:150])
    sample = next((item for item in models.get("data") or []
                   if item["id"] == "deepseek-v4.1-flash"), {})
    check("models limit annotation",
          bool(sample.get("context_length")) and sample.get("limit_sources") is not None,
          json.dumps(sample, ensure_ascii=False)[:200])
    # `minimax-` 不能当 CN 独占前缀：国际出口也提供 minimax-m3.1-flash，
    # 宽通配会把它能用的请求在本地 400 掉（上游 v1.7.31 #618）。
    from intel import catalog as catalog_mod
    check("cn gate keeps only confirmed cn-only models",
          catalog_mod.exclusive_realm("minimax-m3.1-flash") == ""
          and catalog_mod.exclusive_realm("minimax-m3") == "cn"
          and catalog_mod.exclusive_realm("deepseek-v4-pro-1") == "cn",
          "%r %r %r" % (catalog_mod.exclusive_realm("minimax-m3.1-flash"),
                        catalog_mod.exclusive_realm("minimax-m3"),
                        catalog_mod.exclusive_realm("deepseek-v4-pro-1")))

    # ---- 2b. 每日活跃重试/并发/随机提示词、只列出可用模型 ----
    from infra import settings as settings_mod
    from auth import accounts as accounts_mod
    from intel import tiers as tiers_mod
    from integrations import workbuddy_prompts
    check("new settings defaults",
          settings_mod.daily_chat_budget(ctx.accounts_dir) == 600
          and settings_mod.daily_chat_models(ctx.accounts_dir) == []
          and settings_mod.daily_chat_web_concurrency(ctx.accounts_dir) == 1
          and settings_mod.daily_chat_web_random_prompt(ctx.accounts_dir) is False
          and settings_mod.models_only_available(ctx.accounts_dir) is False)
    settings_mod.set_daily_chat_models(
        ctx.accounts_dir, [" alpha ", "beta", "alpha", ""])
    settings_mod.set_daily_chat_budget(ctx.accounts_dir, 300)
    settings_mod.set_daily_chat_web_concurrency(ctx.accounts_dir, 3)
    settings_mod.set_daily_chat_web_random_prompt(ctx.accounts_dir, True)
    settings_mod.set_daily_chat_web_prompts(
        ctx.accounts_dir, ["  第一条  ", "", "第二条"])
    check("new settings round-trip",
          settings_mod.daily_chat_models(ctx.accounts_dir) == ["alpha", "beta"]
          and settings_mod.daily_chat_budget(ctx.accounts_dir) == 300
          and settings_mod.daily_chat_web_concurrency(ctx.accounts_dir) == 3
          and settings_mod.daily_chat_web_random_prompt(ctx.accounts_dir) is True
          and settings_mod.daily_chat_web_prompts(ctx.accounts_dir)
          == ["第一条", "第二条"],
          json.dumps(settings_mod.load(ctx.accounts_dir),
                     ensure_ascii=False)[:300])
    check("builtin random prompt pool",
          len(workbuddy_prompts.builtin_prompts()) == 300,
          str(len(workbuddy_prompts.builtin_prompts())))

    # 一次真正成功的请求是凭据仍有效的直接证据：凭证停车必须随之解除。
    parked = accounts_mod.Account({
        "uid": "token-park", "realm": "intl", "accessToken": "t",
        "enabled": True})
    parked.note_error("HTTP 401")
    parked_was_blocked = not parked.ready()
    parked.note_success(model="deepseek-v4.1-flash")
    check("note_success clears the credential park",
          parked_was_blocked and parked.token_expired is False
          and parked.ready() and parked.public().get("tokenExpired") is False,
          "blocked=%r expired=%r view=%r"
          % (parked_was_blocked, parked.token_expired,
             parked.public().get("tokenExpired")))
    tokenless = accounts_mod.Account({"uid": "tokenless"})
    tokenless.token_expired = True
    tokenless.note_success()
    check("note_success cannot resurrect a tokenless account",
          tokenless.ready() is False
          and tokenless.public().get("tokenExpired") is True,
          repr(tokenless.public().get("tokenExpired")))

    retry_account = accounts_mod.Account({
        "uid": "dailychat-retry", "realm": "intl", "accessToken": "t",
        "enabled": True})
    retry_account.path = os.path.join(ctx.accounts_dir, "dailychat-retry.json")
    saved_prompt_fn = accounts_mod.get_realm_config("intl").get(
        "daily_chat_prompts_fn")
    accounts_mod.get_realm_config("intl")["daily_chat_prompts_fn"] = lambda: []
    try:
        settings_mod.set_daily_chat_web_prompts(ctx.accounts_dir, ["唯一一条"])
        check("random prompt uses custom pool",
              retry_account.daily_chat_web_prompt() == "唯一一条",
              retry_account.daily_chat_web_prompt())
        settings_mod.set_daily_chat_web_random_prompt(ctx.accounts_dir, False)
        check("random prompt off keeps Hi",
              retry_account.daily_chat_web_prompt() == "Hi",
              retry_account.daily_chat_web_prompt())
    finally:
        accounts_mod.get_realm_config("intl")["daily_chat_prompts_fn"] = saved_prompt_fn

    retry_account.web_conversation_reclaim = lambda max_age=0: 0
    retry_account.web_conversation_sweep_orphans = lambda: 0
    settings_mod.set_daily_chat_models(ctx.accounts_dir, ["alpha", "beta"])
    settings_mod.set_daily_chat_budget(ctx.accounts_dir, 600)
    retry_calls = []

    def flaky_once(prompt=None, wait_seconds=None, model=None):
        retry_calls.append((wait_seconds, model))
        if len(retry_calls) == 1:
            return {"ok": False, "retryable": True, "error": "timeout"}
        return {"ok": True, "chunks": 1}

    retry_account._daily_chat_web_once = flaky_once
    retry_res = retry_account._daily_chat_web_upstream()
    check("daily chat walks ordered model candidates",
          retry_res.get("ok") and retry_res.get("attempts") == 2
          and retry_calls == [(120, "alpha"), (120, "beta")]
          and retry_res.get("models_tried") == ["alpha", "beta"],
          json.dumps(retry_calls))
    retry_calls.clear()
    retry_account._daily_chat_web_once = (
        lambda prompt=None, wait_seconds=None, model=None: (
            retry_calls.append((wait_seconds, model))
            or {"ok": False, "retryable": False}))
    retry_res = retry_account._daily_chat_web_upstream()
    check("daily chat business rejection not retried",
          not retry_res.get("ok") and len(retry_calls) == 1, str(retry_calls))

    # 预算连一轮都放不下时必须给明确结论；轮数不再被旧的「尝试次数」放大。
    settings_mod.set_daily_chat_budget(ctx.accounts_dir, 10)
    retry_calls.clear()
    retry_account._daily_chat_web_once = (
        lambda prompt=None, wait_seconds=None, model=None: (
            retry_calls.append((wait_seconds, model))
            or {"ok": False, "retryable": True, "error": "slow"}))
    retry_res = retry_account._daily_chat_web_upstream()
    check("daily chat insufficient budget is explicit",
          not retry_res.get("ok") and retry_res.get("budget_exhausted") is True
          and retry_res.get("phase") == "budget" and retry_calls == []
          and "预算" in (retry_res.get("error") or ""),
          json.dumps(retry_res, ensure_ascii=False))

    # 桌面腿优先选没有冷却的候选；失败模型不再拖住整个打卡。
    retry_account.model_cooldowns["alpha"] = time.time() + 60
    check("daily chat desktop leg skips cooling candidate",
          retry_account.daily_chat_model() == "beta",
          retry_account.daily_chat_model())
    retry_account.model_cooldowns.clear()
    settings_mod.set_daily_chat_models(ctx.accounts_dir, [])
    settings_mod.set_daily_chat_budget(ctx.accounts_dir, 600)

    daily_initial = retry_account.last_daily_chat
    saved_fail_mode = FAIL_MODE["mode"]
    try:
        FAIL_MODE["mode"] = "daily_empty"
        empty_res = retry_account._daily_chat_upstream(web=False)
        check("daily chat empty stream is not a success",
              empty_res.get("ok") is False
              and retry_account.last_daily_chat == daily_initial,
              json.dumps(empty_res, ensure_ascii=False))
        FAIL_MODE["mode"] = "daily_error_frame"
        err_res = retry_account._daily_chat_upstream(web=False)
        check("daily chat error frame is not a success",
              err_res.get("ok") is False
              and retry_account.last_daily_chat == daily_initial,
              json.dumps(err_res, ensure_ascii=False))
    finally:
        FAIL_MODE["mode"] = saved_fail_mode
    ok_res = retry_account._daily_chat_upstream(web=False)
    check("daily chat valid stream marks activity",
          ok_res.get("ok") is True and bool(retry_account.last_daily_chat),
          json.dumps(ok_res, ensure_ascii=False))

    class _ConcurrentAccount(object):
        def __init__(self, uid):
            self.uid = uid
            self.nickname = uid
            self.realm = "intl"

    started = time.time()
    concurrent_result = ctx.task_runner().run(
        "dailychat", [_ConcurrentAccount("c%d" % i) for i in range(3)],
        ready=lambda acc: True,
        action=lambda acc: (time.sleep(0.3) or {"ok": True}),
        source="smoke", realm="intl", write_summary=False,
        concurrency=3, stagger=0.01)
    elapsed = time.time() - started
    check("task runner concurrency",
          concurrent_result.get("ok") == 3 and elapsed < 0.8,
          "ok=%s elapsed=%.2f" % (concurrent_result.get("ok"), elapsed))

    check("tier map ingested from product config",
          tiers_mod.snapshot("intl").get("grok-4.7") == "standard",
          json.dumps(tiers_mod.snapshot("intl"), ensure_ascii=False)[:200])
    tiers_mod.reset()
    tiers_mod.ingest("intl", {"data": {"modelTiers": [
        {"requiredUserType": "standard", "modelIds": ["grok-4.7"]},
        {"requiredUserType": "personal_free_user",
         "modelIds": ["deepseek-v4.1-flash"]},
    ]}})
    free_account = accounts_mod.Account({
        "uid": "tier-free", "realm": "intl", "accessToken": "t",
        "enabled": True, "credits": {"is_paid_user": False}})
    paid_account = accounts_mod.Account({
        "uid": "tier-paid", "realm": "intl", "accessToken": "t",
        "enabled": True, "credits": {"is_paid_user": True}})
    check("PRO gate blocks free account",
          not free_account.ready(model="grok-4.7")
          and free_account.ready(model="deepseek-v4.1-flash")
          and free_account.unavailable_reason(model="grok-4.7")
          == "该模型仅限 PRO 账号",
          free_account.unavailable_reason(model="grok-4.7"))
    check("PRO gate permits paid account",
          paid_account.ready(model="grok-4.7"))

    # 保活提前量必须大于巡检间隔（默认每天一次）：2 小时会让约 92% 的到期
    # 时刻在过期后才被补，期间请求全 401（上游 v1.7.30 #600）。
    from integrations import workbuddy as workbuddy_mod
    now = time.time()
    check("keepalive lead defaults beyond the daily sweep",
          workbuddy_mod.keepalive_lead_seconds() == 48 * 3600,
          str(workbuddy_mod.keepalive_lead_seconds()))
    saved_lead = os.environ.get("WB_KEEPALIVE_LEAD_HOURS")
    try:
        os.environ["WB_KEEPALIVE_LEAD_HOURS"] = "1"
        check("keepalive lead is configurable",
              workbuddy_mod.keepalive_lead_seconds() == 3600,
              str(workbuddy_mod.keepalive_lead_seconds()))
        os.environ["WB_KEEPALIVE_LEAD_HOURS"] = "not-a-number"
        check("keepalive lead falls back on invalid input",
              workbuddy_mod.keepalive_lead_seconds() == 48 * 3600,
              str(workbuddy_mod.keepalive_lead_seconds()))
        os.environ["WB_KEEPALIVE_LEAD_HOURS"] = "999999"
        check("keepalive lead falls back when out of range",
              workbuddy_mod.keepalive_lead_seconds() == 48 * 3600,
              str(workbuddy_mod.keepalive_lead_seconds()))
    finally:
        if saved_lead is None:
            os.environ.pop("WB_KEEPALIVE_LEAD_HOURS", None)
        else:
            os.environ["WB_KEEPALIVE_LEAD_HOURS"] = saved_lead
    # 有效期充足：不刷新；拿不到到期时间：按「该续」处理，不再被当成充足。
    # 两个桩都注入，避免保活测试真的打假上游（会把后续渠道断言的账号打进限流）。
    ample = accounts_mod.Account({
        "uid": "keepalive-ample", "realm": "intl", "accessToken": "t",
        "refreshToken": "r", "expiresAt": int(now + 10 * 86400), "enabled": True})
    ample_calls = []
    ample.refresh = lambda: ample_calls.append("called") or True
    check("keepalive skips an account with ample validity",
          workbuddy_mod._do_keepalive(ample, "smoke").get("status") == "notneeded"
          and ample_calls == [],
          "%r %r" % (ample_calls, workbuddy_mod._do_keepalive(ample, "smoke")))
    unknown_expiry = accounts_mod.Account({
        "uid": "keepalive-opaque", "realm": "intl", "accessToken": "t",
        "refreshToken": "r", "enabled": True})
    # 注入刷新桩：这里要验的是「到期时间未知也去续」这个判定，不是真实换发，
    # 不能让保活测试打假上游（会污染后续渠道断言的上游状态）。
    refresh_calls = []
    unknown_expiry.refresh = lambda: refresh_calls.append("called") or False
    renewed = workbuddy_mod._do_keepalive(unknown_expiry, "smoke")
    check("keepalive renews when expiry is unknown",
          refresh_calls == ["called"] and renewed.get("status") == "error",
          "%r %r" % (refresh_calls, renewed))
    # 没有换发凭据的号不能因为保活被标成凭证失效（那会把它踢出可用池）
    no_refresh = accounts_mod.Account({
        "uid": "keepalive-static", "realm": "intl", "accessToken": "t",
        "enabled": True})
    static_result = workbuddy_mod._do_keepalive(no_refresh, "smoke")
    check("keepalive leaves credential-less accounts untouched",
          static_result.get("status") == "notneeded"
          and getattr(no_refresh, "token_expired", False) is False,
          "%s token_expired=%r" % (static_result,
                                   getattr(no_refresh, "token_expired", None)))

    status, body = request(base, "GET", "/v1/models", headers=key_headers)
    before_ids = [item["id"] for item in
                  (json.loads(body).get("data") or [])]
    check("models list includes PRO model by default",
          "grok-4.7" in before_ids, str(before_ids[:8]))
    settings_mod.set_models_only_available(ctx.accounts_dir, True)
    try:
        status, body = request(base, "GET", "/v1/models", headers=key_headers)
        filtered_ids = [item["id"] for item in
                        (json.loads(body).get("data") or [])]
        check("models only available hides PRO without paid account",
              "grok-4.7" not in filtered_ids
              and "deepseek-v4.1-flash" in filtered_ids,
              str(filtered_ids[:8]))
        ctx.pool.add(paid_account)
        try:
            status, body = request(base, "GET", "/v1/models",
                                   headers=key_headers)
            paid_ids = [item["id"] for item in
                        (json.loads(body).get("data") or [])]
            check("models only available shows PRO with paid account",
                  "grok-4.7" in paid_ids, str(paid_ids[:8]))
        finally:
            ctx.pool.remove("tier-paid")
    finally:
        settings_mod.set_models_only_available(ctx.accounts_dir, False)
        settings_mod.set_daily_chat_models(ctx.accounts_dir, [])
        settings_mod.set_daily_chat_budget(ctx.accounts_dir, 600)
        settings_mod.set_daily_chat_web_concurrency(ctx.accounts_dir, 1)
        settings_mod.set_daily_chat_web_random_prompt(ctx.accounts_dir, False)
        settings_mod.set_daily_chat_web_prompts(ctx.accounts_dir, [])
        tiers_mod.reset()

    # ---- 3. 三接口 ----
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    chat = json.loads(body) if status == 200 else {}
    message = ((chat.get("choices") or [{}])[0].get("message") or {})
    check("chat non-stream", status == 200 and message.get("content") == "你好，世界",
          body[:200])
    status2, body2 = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    chat2 = json.loads(body2) if status2 == 200 else {}
    check("non-stream chat id is unique",
          bool(chat.get("id")) and bool(chat2.get("id"))
          and chat.get("id") != chat2.get("id"),
          "%r vs %r" % (chat.get("id"), chat2.get("id")))

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("chat stream", status == 200 and "[DONE]" in body and "你好" in body,
          body[:200])

    FAIL_MODE["mode"] = "usage_on_choice"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    rows = parse_sse(body)
    usage_rows = [row for row in rows if row.get("usage")]
    check("usage moved to a trailing choices-less frame",
          status == 200 and len(usage_rows) == 1
          and usage_rows[0].get("choices") == []
          and all(not row.get("usage") for row in rows
                  if row is not usage_rows[0]),
          json.dumps(rows, ensure_ascii=False)[:300])
    # 一轮回复只带一个 id，且是网关自己的：上游帧与网关改写帧若各带各的 id，
    # 按 id 管理流状态的客户端会卡在「生成中」（上游 v1.7.30 #607）。
    chunk_ids = {row.get("id") for row in rows if row.get("id")}
    check("stream chunk id present and consistent",
          bool(usage_rows) and len(chunk_ids) == 1
          and next(iter(chunk_ids)).startswith("chatcmpl-wb-"),
          "%r %s" % (chunk_ids, json.dumps(usage_rows, ensure_ascii=False)[:150]))
    FAIL_MODE["mode"] = ""

    # ---- 3c. 流式静默心跳 ----
    # 上游长时间不吐字节时，客户端会因空闲超时报 stream disconnected。心跳
    # 必须由后台线程发出（只在阻塞读之前检查的保活覆盖不到那段静默），且必须
    # 是合法注释帧、不能劈开业务帧（上游 v1.7.31 #578）。
    from core import streaming as streaming_mod
    beat_frames = []
    beat = streaming_mod.SSEHeartbeat(beat_frames.append, interval=0.05)
    time.sleep(0.16)
    beat.write(b"data: {\"ok\": true}\n\n")
    time.sleep(0.16)
    beat.close()
    beat_after_close = len(beat_frames)
    time.sleep(0.12)
    check("heartbeat emits a valid SSE comment frame",
          b": keepalive\n\n" in beat_frames
          and all(b"data:" not in f for f in beat_frames
                  if f == b": keepalive\n\n"),
          str(beat_frames[:4]))
    check("heartbeat stops writing after close",
          len(beat_frames) == beat_after_close,
          "%d %d" % (beat_after_close, len(beat_frames)))
    # 端到端：心跳帧不会混进业务数据，正常流仍然完整收尾
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("stream stays intact alongside heartbeat",
          status == 200 and "你好" in body and body.rstrip().endswith("[DONE]")
          and ": keepalive" not in body,
          body[:160])

    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "hi"}, key_headers)
    response_obj = json.loads(body) if status == 200 else {}
    check("responses non-stream",
          status == 200 and response_obj.get("object") == "response"
          and response_obj.get("output_text") == "你好，世界", body[:200])

    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "hi", "stream": True}, key_headers)
    check("responses stream",
          status == 200 and "response.completed" in body and "response.output_text.delta" in body,
          body[:200])

    # ---- 4. 工具调用翻译 ----
    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "call a tool",
        "tools": [{"type": "function", "name": "get_time",
                   "parameters": {"type": "object", "properties": {}}}]}, key_headers)
    check("responses with tools", status == 200, body[:200])

    # 本地网络工具默认关：客户端宣告的 web_search 原样透传，网关不接管
    from infra import settings as settings_mod
    check("web tools default off",
          settings_mod.local_web_tools(ctx.accounts_dir) is False)
    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "search something",
        "tools": [{"type": "web_search"}]}, key_headers)
    check("web tools pass through when off", status == 200, body[:200])

    # 打开开关后：网关接管 web_search 宣告、代跑一轮、把结果喂回后收尾
    settings_mod.set_local_web_tools(ctx.accounts_dir, True)
    # 冒烟不访问外网：把真正的搜索执行器换成确定性替身（只验证代跑链路本身）
    from infra import webtools as webtools_mod
    real_execute = webtools_mod.execute
    webtools_mod.execute = lambda name, args: (
        "Search results for gateway test:\n"
        "1. Example Doc\n   https://example.test/doc\n")
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "search something",
            "tools": [{"type": "web_search"}]}, key_headers)
        payload_obj = json.loads(body) if status == 200 else {}
        calls = [item for item in (payload_obj.get("output") or [])
                 if item.get("type") == "function_call"]
        check("web tools run internally when on",
              status == 200 and not calls
              and payload_obj.get("output_text") == "你好，世界", body[:240])
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "search something",
            "stream": True, "tools": [{"type": "web_search"}]}, key_headers)
        check("web tools stream search card",
              status == 200
              and "response.web_search_call.searching" in body
              and "response.web_search_call.completed" in body
              and "response.function_call_arguments.done" not in body
              and "response.completed" in body
              and body.count("event: response.created") == 1
              and body.count("event: response.completed") == 1, body[:240])
    finally:
        webtools_mod.execute = real_execute
        settings_mod.set_local_web_tools(ctx.accounts_dir, False)

    # ---- 4a. Responses 协议兼容（对齐主上游 v1.5.0 / v1.7.2 / v1.7.3 / v1.7.14） ----
    from core import protocol as protocol_mod
    from core import streaming as streaming_mod
    from core import tools_compat as tools_compat_mod

    # 网关没有 response 状态存储：静默忽略会让续聊丢上下文，必须明确拒绝
    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "hi",
        "previous_response_id": "resp_prev"}, key_headers)
    check("responses previous_response_id rejected",
          status == 400 and "previous_response_id is not supported" in body,
          body[:200])

    ns_tools = [{"type": "namespace", "name": "functions", "tools": [
        {"type": "custom", "name": "exec", "description": "run",
         "format": {"type": "grammar", "syntax": "lark",
                    "definition": "start: /.*/s"}},
        {"type": "function", "name": "wait",
         "parameters": {"type": "object", "properties": {}}},
    ]}]
    chat_req = protocol_mod.responses_to_chat({
        "model": "m", "input": [
            {"type": "additional_tools", "tools": ns_tools},
            {"role": "user", "content": "run"}]})
    tool_names = [((t.get("function") or {}).get("name") or t.get("name"))
                  for t in chat_req.get("tools") or []]
    check("responses additional_tools merged",
          "exec" in tool_names and "wait" in tool_names, tool_names)
    check("responses namespace tools flattened",
          chat_req.get("_namespace_map") == {"exec": "functions",
                                             "wait": "functions"},
          chat_req.get("_namespace_map"))
    check("responses custom tool downgraded",
          all(t.get("type") == "function" for t in chat_req.get("tools") or [])
          and any("freeform tool" in (t.get("description") or "")
                  for t in chat_req.get("tools") or []),
          chat_req.get("tools"))
    check("responses nested custom detected",
          protocol_mod.custom_tool_names(ns_tools) == {"exec"},
          protocol_mod.custom_tool_names(ns_tools))
    check("responses additional_tools not in messages",
          len(chat_req.get("messages") or []) == 1
          and chat_req["messages"][0]["role"] == "user",
          chat_req.get("messages"))

    orphan_msgs = protocol_mod.responses_to_chat({"model": "m", "input": [
        {"type": "function_call_output", "output": "orphan result"}]})["messages"]
    check("responses orphan function output degrades to user",
          len(orphan_msgs) == 1 and orphan_msgs[0]["role"] == "user"
          and "another task" in orphan_msgs[0]["content"], orphan_msgs)
    agent_msgs = protocol_mod.responses_to_chat({"model": "m", "input": [
        {"type": "agent_message",
         "content": [{"type": "text", "text": "sub agent update"}]}]})["messages"]
    check("responses agent_message becomes user message",
          len(agent_msgs) == 1 and agent_msgs[0]["role"] == "user"
          and "sub agent update" in agent_msgs[0]["content"], agent_msgs)

    fmt = {"type": "json_schema", "name": "fixture",
           "schema": {"type": "object"}, "strict": True}
    os.environ.pop("WB_PRESERVE_REQUEST_CONTRACT", None)
    plain = protocol_mod.responses_to_chat(
        {"model": "m", "input": "hi", "text": {"format": fmt}})
    check("responses text.format gated off by default",
          "response_format" not in plain, plain)
    os.environ["WB_PRESERVE_REQUEST_CONTRACT"] = "1"
    try:
        kept = protocol_mod.responses_to_chat(
            {"model": "m", "input": "hi", "text": {"format": fmt}})
        check("responses text.format mapped under contract flag",
              kept.get("response_format", {}).get("type") == "json_schema"
              and kept["response_format"]["json_schema"]["strict"] is True,
              kept.get("response_format"))
        strict_tools, _ = protocol_mod.expand_namespace_tools([{
            "type": "namespace", "name": "fixture", "tools": [{
                "type": "function", "name": "lookup", "strict": False,
                "parameters": {"type": "object", "properties": {}}}]}])
        check("responses namespace strict preserved",
              strict_tools[0].get("strict") is False, strict_tools)
        preserved = tools_compat_mod.sanitize_messages([{
            "role": "tool", "tool_call_id": "c1", "content": '{"code":11128}'}])
        check("responses tool result contract preserved",
              preserved[0]["content"] == '{"code":11128}', preserved)
    finally:
        os.environ.pop("WB_PRESERVE_REQUEST_CONTRACT", None)

    identity_msgs = tools_compat_mod.sanitize_messages([
        {"role": "system", "content":
            "You are an AI agent powered by DeepSeek Harness."},
        {"role": "developer", "content":
            "You are a coding agent powered by the deepseek-v4.1-flash model."},
        {"role": "user", "content":
            "You are an AI agent powered by DeepSeek Harness."},
        {"role": "assistant", "content":
            "You are an AI agent powered by DeepSeek Harness."},
        {"role": "assistant", "content": "",
         "reasoning_content":
             "You are an AI assistant built on DeepSeek."},
    ])
    check("identity sentence neutralized in system/developer/assistant",
          identity_msgs[0]["content"] == "You are a helpful AI assistant."
          and identity_msgs[1]["content"] == "You are a helpful AI assistant."
          and identity_msgs[3]["content"] == "You are a helpful AI assistant.",
          json.dumps(identity_msgs[:4], ensure_ascii=False))
    check("identity sentence kept in user/reasoning",
          identity_msgs[2]["content"]
          == "You are an AI agent powered by DeepSeek Harness."
          and identity_msgs[4]["reasoning_content"]
          == "You are an AI assistant built on DeepSeek.",
          json.dumps(identity_msgs[2:], ensure_ascii=False))

    identity_variants = tools_compat_mod.sanitize_messages([
        {"role": "system", "content": "You are DeepSeek Agent, built by Acme."},
        {"role": "system", "content": "You are created by Acme."},
        {"role": "system", "content": "You are an AI assistant developed by Acme."},
        {"role": "system", "content": "You are powered by DeepSeek."},
        {"role": "system", "content": "You are free to use tools built by Acme."},
    ])
    check("identity verb variants neutralized",
          all(item["content"] == "You are a helpful AI assistant."
              for item in identity_variants[:4]),
          json.dumps(identity_variants[:4], ensure_ascii=False))
    check("identity participle phrase kept",
          identity_variants[4]["content"]
          == "You are free to use tools built by Acme.",
          identity_variants[4]["content"])

    # 非流式回程：namespace + custom 还原、请求能力回显
    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "run", "tools": ns_tools,
        "parallel_tool_calls": False, "tool_choice": "auto"}, key_headers)
    obj = json.loads(body) if status == 200 else {}
    item = (obj.get("output") or [{}])[0]
    check("responses namespace custom round-trip",
          status == 200 and item.get("type") == "custom_tool_call"
          and item.get("name") == "exec"
          and item.get("namespace") == "functions"
          and item.get("input") == "pwd", body[:300])
    check("responses request meta echoed",
          obj.get("parallel_tool_calls") is False
          and obj.get("tool_choice") == "auto"
          and obj.get("tools") == ns_tools,
          json.dumps(obj, ensure_ascii=False)[:300])

    # 流式回程：added/done 都带 namespace，custom 走 input.delta/done
    status, body = request(base, "POST", "/v1/responses", {
        "model": "deepseek-v4.1-flash", "input": "run", "tools": ns_tools,
        "stream": True}, key_headers)
    events = parse_sse(body)
    custom_added = [e for e in events if e.get("type") == "response.output_item.added"
                    and (e.get("item") or {}).get("type") == "custom_tool_call"]
    custom_done = [e for e in events if e.get("type") == "response.output_item.done"
                   and (e.get("item") or {}).get("type") == "custom_tool_call"]
    check("responses namespace stamped in stream",
          status == 200 and custom_added and custom_done
          and custom_added[0]["item"].get("namespace") == "functions"
          and custom_done[-1]["item"].get("namespace") == "functions",
          body[:400])
    check("responses custom tool input lifecycle",
          "response.custom_tool_call_input.delta" in body
          and "response.custom_tool_call_input.done" in body
          and "response.function_call_arguments.done" not in body,
          body[:400])

    # 首个 tool_calls 分片可能已经带参数：它必须补发 delta，且只能累计一次。
    from core.streaming import stream_responses_events as _stream_responses
    def _arg_chunk(delta, finish=None):
        return ("data: " + json.dumps(
            {"choices": [{"index": 0, "delta": delta,
                          "finish_reason": finish}]}) + "\n\n").encode("utf-8")

    first_args_chunks = [
        _arg_chunk({"tool_calls": [{
            "index": 0, "id": "call_first", "type": "function",
            "function": {"name": "get_weather", "arguments": '{"city":"'}}]}),
        _arg_chunk({"tool_calls": [{
            "index": 0, "function": {"arguments": 'Beijing"}'}}]}),
        _arg_chunk({}, "tool_calls"),
        b"data: [DONE]\n\n",
    ]
    first_args_events = parse_sse(b"".join(_stream_responses(
        iter(first_args_chunks), "deepseek-v4.1-flash", {"usage": None})
        ).decode("utf-8", "replace"))
    first_deltas = [e for e in first_args_events
                    if e.get("type") == "response.function_call_arguments.delta"]
    first_done = [e for e in first_args_events
                  if e.get("type") == "response.function_call_arguments.done"]
    first_added = [i for i, e in enumerate(first_args_events)
                   if e.get("type") == "response.output_item.added"]
    check("responses first tool arguments are emitted exactly once",
          "".join(e.get("delta") or "" for e in first_deltas) == '{"city":"Beijing"}'
          and all(e.get("delta") for e in first_deltas)
          and first_done and first_done[-1].get("arguments") == '{"city":"Beijing"}'
          and first_added
          and all(i > first_added[0] for i, e in enumerate(first_args_events)
                  if e.get("type") == "response.function_call_arguments.delta"),
          json.dumps(first_deltas, ensure_ascii=False)[:300])

    # reasoning / tool_calls / usage / message 的完整生命周期
    FAIL_MODE["mode"] = "reasoning_tool"
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        events = parse_sse(body)
        args_delta = [e for e in events
                      if e.get("type") == "response.function_call_arguments.delta"]
        args_done = [e for e in events
                     if e.get("type") == "response.function_call_arguments.done"]
        completed = [e for e in events if e.get("type") == "response.completed"]
        final = (completed[-1].get("response") or {}) if completed else {}
        types = [o.get("type") for o in final.get("output") or []]
        check("responses reasoning lifecycle",
              "response.reasoning_summary_part.added" in body
              and "response.reasoning_summary_text.delta" in body
              and "response.reasoning_summary_text.done" in body,
              body[:400])
        check("responses tool events carry item_id",
              args_delta and args_done
              and all(e.get("item_id") for e in args_delta + args_done),
              (args_delta + args_done)[:2])
        # 流式输出顺序由事件到达顺序决定：先正文后工具调用，消息项先占位
        check("responses stream final output ordering",
              types == ["reasoning", "message", "function_call"], types)
        check("responses stream usage reasoning tokens",
              ((final.get("usage") or {}).get("output_tokens_details") or {}
               ).get("reasoning_tokens") == 2, final.get("usage"))
        # 同一轮里推理帧与正文/工具帧必须共用一个 id：各带各的 id 时，按 id
        # 管理流状态的客户端会把推理那半（无 finish_reason）当成没结束的流。
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "deepseek-v4.1-flash", "stream": True,
            "messages": [{"role": "user", "content": "hi"}]}, key_headers)
        chat_rows = parse_sse(body)
        chat_ids = {row.get("id") for row in chat_rows if row.get("id")}
        check("reasoning and answer frames share one chunk id",
              status == 200 and len(chat_ids) == 1
              and next(iter(chat_ids)).startswith("chatcmpl-wb-"),
              "%r" % (chat_ids,))

        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi"}, key_headers)
        obj = json.loads(body) if status == 200 else {}
        types = [o.get("type") for o in obj.get("output") or []]
        check("responses non-stream aggregation",
              status == 200 and types == ["reasoning", "function_call", "message"]
              and obj.get("status") == "completed"
              and ((obj.get("usage") or {}).get("input_tokens") == 11)
              and ((obj.get("usage") or {}).get("output_tokens") == 7),
              body[:300])
    finally:
        FAIL_MODE["mode"] = ""

    # 截断：半截参数不补 done，终态 incomplete + 原因
    FAIL_MODE["mode"] = "truncated_tool"
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        events = parse_sse(body)
        completed = [e for e in events if e.get("type") == "response.completed"]
        final = (completed[-1].get("response") or {}) if completed else {}
        check("responses truncated tool not completed in stream",
              status == 200
              and "response.function_call_arguments.done" not in body
              and final.get("status") == "incomplete"
              and (final.get("incomplete_details") or {}
                   ).get("reason") == "max_output_tokens", body[-400:])
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi"}, key_headers)
        obj = json.loads(body) if status == 200 else {}
        calls = [o for o in obj.get("output") or []
                 if o.get("type") == "function_call"]
        check("responses truncated tool dropped in aggregate",
              status == 200 and not calls and obj.get("status") == "incomplete",
              body[:300])
    finally:
        FAIL_MODE["mode"] = ""

    # 上游缺 usage 时按已流出文本估算，响应里必须有可用账目
    FAIL_MODE["mode"] = "no_usage"
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        completed = [e for e in parse_sse(body)
                     if e.get("type") == "response.completed"]
        usage = ((completed[-1].get("response") or {}).get("usage")
                 if completed else {}) or {}
        check("responses missing usage estimated",
              status == 200 and (usage.get("total_tokens") or 0) >= 1, usage)
    finally:
        FAIL_MODE["mode"] = ""

    # 流内错误：response.failed 收场；非流式给出 HTTP 错误
    FAIL_MODE["mode"] = "stream_error"
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        check("responses stream error emits response.failed",
              status == 200 and "event: response.failed" in body
              and "event: response.completed" not in body and "boom" in body,
              body[:300])
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi"}, key_headers)
        check("responses non-stream error surfaces 502",
              status == 502 and "boom" in body, body[:200])
    finally:
        FAIL_MODE["mode"] = ""

    # 流中读断：已流出内容后上游断连，必须发错误帧而不是 [DONE] 冒充正常结束
    from infra import settings as settings_mod
    header_saved, idle_saved = settings_mod.upstream_timeouts(ctx.accounts_dir)
    settings_mod.set_upstream_timeouts(ctx.accounts_dir, idle=1.0)
    FAIL_MODE["mode"] = "stream_stall_mid"
    try:
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True}, key_headers)
        check("chat mid-stream abort emits error frame without DONE",
              status == 200 and "半截" in body
              and '"code": "upstream_stream_error"' in body
              and "data: [DONE]" not in body, body[-400:])
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        check("responses mid-stream abort emits error event without DONE",
              status == 200 and "半截" in body
              and "event: error" in body
              and "upstream_stream_error" in body
              and "data: [DONE]" not in body, body[-400:])
    finally:
        FAIL_MODE["mode"] = ""
        settings_mod.set_upstream_timeouts(ctx.accounts_dir,
                                           header=header_saved, idle=idle_saved)

    # 只有 reasoning、正文为空：必须 failed，不能伪装成正常完成
    FAIL_MODE["mode"] = "reasoning_only"
    try:
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi", "stream": True},
            key_headers)
        check("responses reasoning-only stream fails",
              status == 200 and "event: response.failed" in body
              and "empty_reasoning_only" in body
              and "event: response.completed" not in body, body[-400:])
        status, body = request(base, "POST", "/v1/responses", {
            "model": "deepseek-v4.1-flash", "input": "hi"}, key_headers)
        check("responses reasoning-only non-stream 502",
              status == 502 and "reasoning" in body, body[:200])
    finally:
        FAIL_MODE["mode"] = ""

    cleaned = json.loads(streaming_mod.clean_chunk(
        '{"choices":[{"delta":{"content":"x"},"finish_reason":""}]}'))
    check("responses empty finish_reason normalized",
          cleaned["choices"][0]["finish_reason"] is None, cleaned)

    # ---- 5. 鉴权 ----
    check("no key rejected", request(base, "GET", "/v1/models")[0] == 401)
    check("bad key rejected",
          request(base, "GET", "/v1/models",
                  headers={"Authorization": "Bearer wrong"})[0] == 401)
    status, body = request(base, "POST", "/panel/login", {"password": "admin"})
    token = json.loads(body).get("token") if status == 200 else ""
    check("panel login", status == 200 and bool(token), body[:150])
    panel_headers = {"X-Panel-Token": token}
    status, body = request(base, "GET", "/accounts", headers=panel_headers)
    accounts = json.loads(body).get("accounts") if status == 200 else []
    check("panel accounts", status == 200
          and any(a["uid"] == "u1" for a in accounts)
          and all("loginAccount" in a for a in accounts),
          body[:150])
    ctx.pool.set_note("u1", "联系 13812345678")
    status, body = request(base, "GET", "/accounts", headers=panel_headers)
    check("panel account phone masked",
          status == 200 and "138****5678" in body and "13812345678" not in body,
          body[:200])
    ctx.pool.set_note("u1", "")
    for path in ("/channels", "/usage", "/settings", "/scheduler", "/tasks",
                 "/models/source", "/usage/perf", "/usage/analytics",
                 "/scheduler/records", "/proxy-slots", "/activity/history"):
        status, body = request(base, "GET", path, headers=panel_headers)
        check("panel GET %s" % path, status == 200, body[:150])
    check("management needs panel",
          request(base, "GET", "/accounts", headers=key_headers)[0] == 401)

    # ---- 5c. 身份声明与模型目录按 Key 过滤 ----
    from auth import identity as identity_mod
    from infra import settings as settings_mod
    cli_auto = identity_mod.build_identity_headers(
        product="cli", realm="intl", uid="u", token="t")
    cli_forced = identity_mod.build_identity_headers(
        product="cli", realm="intl", uid="u", token="t", private_data="true")
    check("private-data override only when explicit",
          cli_auto.get("X-Private-Data") == "false"
          and cli_forced.get("X-Private-Data") == "true",
          "%r / %r" % (cli_auto.get("X-Private-Data"),
                       cli_forced.get("X-Private-Data")))
    cn_desktop = identity_mod.build_identity_headers(
        product="workbuddy", realm="cn", uid="u", token="t")
    check("cn desktop identity version current",
          cn_desktop.get("X-IDE-Version") == "5.8.3"
          and "CLI/2.161.0" in (cn_desktop.get("User-Agent") or ""),
          "%r / %r" % (cn_desktop.get("X-IDE-Version"),
                       cn_desktop.get("User-Agent")))
    try:
        status, body = request(base, "POST", "/settings/save", {
            "identity": {"private_data": "false"}}, panel_headers)
        check("identity setting saved",
              status == 200 and "identity" in (json.loads(body).get("applied") or []),
              body[:200])
        status, body = request(base, "GET", "/settings", headers=panel_headers)
        settings_payload = json.loads(body) if status == 200 else {}
        check("identity setting exposed",
              (settings_payload.get("identity") or {}).get("private_data") == "false",
              json.dumps(settings_payload.get("identity"), ensure_ascii=False))
        check("daily chat and model filter settings exposed",
              settings_payload.get("daily_chat_budget") == 600
              and settings_payload.get("daily_chat_models") == []
              and settings_payload.get("daily_chat_web_concurrency") == 1
              and settings_payload.get("daily_chat_web_random_prompt") is False
              and settings_payload.get("models_only_available") is False
              and settings_payload.get("daily_chat_web_prompts") == [],
              json.dumps({key: settings_payload.get(key) for key in (
                  "daily_chat_budget", "daily_chat_models",
                  "daily_chat_web_concurrency",
                  "daily_chat_web_random_prompt", "models_only_available")},
                  ensure_ascii=False))
        status, body = request(base, "POST", "/settings/save", {
            "daily_chat_models": ["m1", "m2"],
            "daily_chat_budget": 900,
            "daily_chat_web_concurrency": 4,
            "daily_chat_web_random_prompt": True,
            "daily_chat_web_prompts": ["a", "b"],
            "models_only_available": True,
        }, panel_headers)
        applied = json.loads(body).get("applied") if status == 200 else []
        check("new settings saved via panel",
              status == 200 and all(key in (applied or []) for key in (
                  "daily_chat_models", "daily_chat_budget",
                  "daily_chat_web_concurrency",
                  "daily_chat_web_random_prompt", "daily_chat_web_prompts",
                  "models_only_available")), body[:240])
        tiers_mod.ingest("intl", {"data": {"modelTiers": [
            {"requiredUserType": "standard", "modelIds": ["grok-4.7"]}]}})
        status, body = request(base, "GET", "/models/list?realm=intl",
                               headers=panel_headers)
        panel_filtered_ids = [item.get("id") for item in
                              (json.loads(body).get("data") or [])]
        check("panel model list honors models-only-available",
              status == 200 and "grok-4.7" not in panel_filtered_ids
              and "deepseek-v4.1-flash" in panel_filtered_ids,
              str(panel_filtered_ids[:10]))
        tiers_mod.reset()
        request(base, "POST", "/settings/save", {
            "daily_chat_models": [],
            "daily_chat_budget": 600,
            "daily_chat_web_concurrency": 1,
            "daily_chat_web_random_prompt": False,
            "daily_chat_web_prompts": [],
            "models_only_available": False,
        }, panel_headers)
        account_u1 = ctx.pool.get("u1")
        status, body = request(base, "POST", "/settings/save", {
            "daily_chat_web_retry_backoff": 7,
        }, panel_headers)
        applied = json.loads(body).get("applied") if status == 200 else []
        check("daily-chat backoff saved via panel",
              status == 200 and "daily_chat_web_retry_backoff" in (applied or []),
              body[:200])
        status, body = request(base, "GET", "/settings", headers=panel_headers)
        check("daily-chat backoff exposed",
              json.loads(body).get("daily_chat_web_retry_backoff") == 7, body[:200])

        from auth import accounts as accounts_mod
        settings_mod.set_daily_chat_web_retry_backoff(ctx.accounts_dir, 0)
        check("create-phase pause honors the setting (0 = no backoff)",
              account_u1._web_retry_pause({"phase": "create"}, 0) == 0.0,
              str(settings_mod.daily_chat_web_retry_backoff(ctx.accounts_dir)))
        check("turn-phase failures are not backed off",
              account_u1._web_retry_pause({"phase": "turn"}, 0) == 0.0,
              "phase turn")
        backoff_base = accounts_mod.WEB_RETRY_BACKOFF
        check("web retry backoff grows exponentially and caps",
              accounts_mod.web_retry_backoff(0) == backoff_base
              and accounts_mod.web_retry_backoff(1) == backoff_base * 2
              and accounts_mod.web_retry_backoff(9) == max(
                  accounts_mod.WEB_RETRY_BACKOFF_MAX, backoff_base)
              and accounts_mod.web_retry_backoff(0, base=0) == 0.0,
              "%r %r %r" % (accounts_mod.web_retry_backoff(0),
                            accounts_mod.web_retry_backoff(9),
                            accounts_mod.web_retry_backoff(0, base=0)))
        stub = accounts_mod.Account({"uid": "backoff-stub", "realm": "intl",
                                     "accessToken": "t", "enabled": True}, "")
        calls, pauses = [], []
        stub.web_fallback_models = lambda: ["m1", "m2"]
        stub.web_conversation_reclaim = lambda max_age=0: 0
        stub.web_conversation_sweep_orphans = lambda: 0
        stub._daily_chat_web_once = lambda prompt=None, wait_seconds=None, model=None: (
            calls.append(wait_seconds) or {"ok": False, "error": "boom",
                                           "retryable": True, "phase": "create"})
        stub._web_retry_pause = lambda res, index, deadline=None: (
            pauses.append((res.get("phase"), index)) or 0.0)
        stub_result = stub._daily_chat_web_upstream("hi")
        check("create/session failures pause between attempts",
              len(calls) == 2 and pauses == [("create", 0)]
              and stub_result.get("attempts") == 2,
              "%r %r %r" % (calls, pauses, stub_result.get("attempts")))
        settings_mod.set_daily_chat_web_retry_backoff(ctx.accounts_dir, 5)
        status, body = request(base, "GET", "/settings", headers=panel_headers)
        check("daily-chat backoff back to default",
              json.loads(body).get("daily_chat_web_retry_backoff") == 5, body[:200])

        from core import proxy_api
        fake_handler = type("H", (), {"headers": {}, "ctx": ctx})()
        conv_head = [{"role": "system", "content": "sys"},
                     {"role": "user", "content": "同一段对话"}]
        payload_a = {"messages": conv_head + [{"role": "assistant", "content": "回复 A"}]}
        payload_b = {"messages": conv_head + [{"role": "assistant", "content": "回复 B"}]}
        check("prefix affinity is off by default",
              proxy_api._session_key(fake_handler, payload_a) is None,
              repr(proxy_api._session_key(fake_handler, payload_a)))
        status, body = request(base, "POST", "/settings/save", {
            "affinity_stable_key_enabled": True,
        }, panel_headers)
        applied = json.loads(body).get("applied") if status == 200 else []
        check("affinity key switch saved via panel",
              status == 200 and "affinity_stable_key_enabled" in (applied or []),
              body[:200])
        key_a = proxy_api._session_key(fake_handler, payload_a)
        key_b = proxy_api._session_key(fake_handler, payload_b)
        check("prefix affinity key is stable and separates the two conversations",
              bool(key_a) and key_a.startswith("pfx-") and key_a != key_b
              and key_a == proxy_api._session_key(fake_handler, payload_a),
              "%r %r" % (key_a, key_b))
        explicit = type("H", (), {"headers": {"X-Conversation-Id": "conv-1"},
                                  "ctx": ctx})()
        check("explicit conversation id still wins",
              proxy_api._session_key(explicit, payload_a) == "conv-1",
              repr(proxy_api._session_key(explicit, payload_a)))
        ctx.pool.affinity.unbind(key_a)
        picked = ctx.pool.pick_for_session(realm="intl", session_key=key_a)
        check("prefix key binds the conversation to one account",
              picked is not None and ctx.pool.affinity.get(key_a) == picked.uid,
              str(ctx.pool.affinity.get(key_a)))
        ctx.pool.affinity.unbind(key_a)
        status, body = request(base, "POST", "/settings/save", {
            "affinity_stable_key_enabled": False,
        }, panel_headers)
        check("affinity key switch turns off again",
              proxy_api._session_key(fake_handler, payload_a) is None, body[:200])

        from core import ratelimit as ratelimit_mod
        status, body = request(base, "POST", "/settings/save", {
            "account_max_concurrent": 3,
        }, panel_headers)
        applied = json.loads(body).get("applied") if status == 200 else []
        check("account concurrency cap saved via panel",
              status == 200 and "account_max_concurrent" in (applied or []),
              body[:200])
        status, body = request(base, "POST", "/settings/save", {
            "account_max_concurrent": 99,
        }, panel_headers)
        check("account concurrency cap rejects out-of-range",
              status == 400, body[:150])
        status, body = request(base, "GET", "/settings", headers=panel_headers)
        check("account concurrency cap exposed with its ceiling",
              json.loads(body).get("account_max_concurrent") == 3
              and json.loads(body).get("account_max_concurrent_max") == 10,
              body[:200])
        settings_mod.set_account_max_concurrent(ctx.accounts_dir, 1)
        capped = ctx.pool.get("u1")
        check("account concurrency cap reserves one slot per account",
              ctx.pool.reserve(capped) is True
              and ctx.pool.reserve(capped) is False
              and ctx.pool.inflight_snapshot() == {"u1": 1},
              json.dumps(ctx.pool.inflight_snapshot()))
        skipped = ctx.pool.pick(reserve=True)
        check("saturated account is skipped while another candidate is free",
              skipped is not None and skipped.uid != "u1",
              str(getattr(skipped, "uid", "")))
        ctx.pool.release_request_slots()
        check("request-end release clears the account slots",
              ctx.pool.inflight_snapshot() == {},
              json.dumps(ctx.pool.inflight_snapshot()))
        ctx.pool.reserve(capped)
        try:
            ctx.pool.pick(realm="intl", reserve=True)
            busy_error = None
        except ratelimit_mod.RateLimited as exc:
            busy_error = exc
        check("saturated realm reports a 429 naming the cap",
              busy_error is not None
              and "account_max_concurrent" in str(getattr(busy_error, "message", "")),
              str(getattr(busy_error, "message", ""))[:200])
        ctx.pool.release_request_slots()
        settings_mod.set_account_max_concurrent(ctx.accounts_dir, 0)
        check("cap off = no accounting",
              ctx.pool.reserve(capped) is True
              and ctx.pool.inflight_snapshot() == {},
              json.dumps(ctx.pool.inflight_snapshot()))
        ctx.pool.release_request_slots()

        settings_mod.set_account_max_concurrent(ctx.accounts_dir, 1)
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "deepseek-v4.1-flash",
            "messages": [{"role": "user", "content": "名额归还"}]}, key_headers)
        # 归还发生在服务端线程里，可能比客户端读到响应体晚几微秒：等一小会儿，
        # 真漏了就不会归零（照旧能抓出来）。
        slot_deadline = time.time() + 3
        slots = ctx.pool.inflight_snapshot()
        while slots and time.time() < slot_deadline:
            time.sleep(0.02)
            slots = ctx.pool.inflight_snapshot()
        check("a finished chat request returns its account slot",
              status == 200 and slots == {}, "%s %s" % (status, json.dumps(slots)))
        settings_mod.set_account_max_concurrent(ctx.accounts_dir, 0)

        parsed_tier = accounts_mod.tier_from_summary({
            "IsPaidUser": True, "SubscriptionPackageName": "体验版",
            "IsProtectedPriceUser": True, "ProTrialStatus": 2})
        check("billing summary parses into a tier record",
              bool(parsed_tier) and parsed_tier.get("package") == "体验版"
              and parsed_tier.get("paid") is True
              and parsed_tier.get("protected_price") is True
              and parsed_tier.get("trial") == 2 and bool(parsed_tier.get("checked_at")),
              json.dumps(parsed_tier, ensure_ascii=False))
        check("billing summary without IsPaidUser is not a tier",
              accounts_mod.tier_from_summary(
                  {"SubscriptionPackageName": "Pro"}) is None)
        account_u1.fetch_credits(force=True)
        status, body = request(base, "GET", "/accounts", headers=panel_headers)
        u1_public = [a for a in (json.loads(body).get("accounts") or [])
                     if a.get("uid") == "u1"]
        check("account row carries the membership capsule from the summary",
              status == 200 and bool(u1_public)
              and (u1_public[0].get("tier") or {}).get("package") == "Free"
              and (u1_public[0].get("credits") or {}).get("is_paid_user") is False,
              json.dumps(u1_public[0].get("tier") if u1_public else None,
                         ensure_ascii=False))
        check("account headers honor private-data setting",
              account_u1.headers(purpose="chat").get("X-Private-Data") == "false",
              str(account_u1.headers(purpose="chat").get("X-Private-Data")))
        status, body = request(base, "POST", "/settings/save", {
            "identity": {"private_data": "invalid"}}, panel_headers)
        check("identity setting rejects invalid value", status == 400, body[:150])
    finally:
        settings_mod.set_identity_private_data(ctx.accounts_dir, "auto")

    original_keys = settings_mod.api_keys(ctx.accounts_dir)
    try:
        status, body = request(base, "POST", "/settings/save", {
            "api_keys": [{"id": "k-filter", "name": "filter", "key": "sk-filter",
                          "realm": "", "models": ["glm-5.3"], "enabled": True}],
            "filter_models_by_key": True,
        }, panel_headers)
        check("models key filter setting saved", status == 200, body[:150])
        status, body = request(base, "GET", "/v1/models",
                               headers={"Authorization": "Bearer sk-filter"})
        filtered_payload = json.loads(body) if status == 200 else {"data": []}
        filtered_ids = [m["id"] for m in filtered_payload.get("data") or []]
        check("models filtered by key whitelist",
              status == 200 and "glm-5.3" in filtered_ids
              and "deepseek-v4.1-flash" not in filtered_ids,
              json.dumps(filtered_ids, ensure_ascii=False)[:200])
    finally:
        settings_mod.set_api_keys(ctx.accounts_dir, original_keys)
        settings_mod.set_filter_models_by_key(ctx.accounts_dir, False)
    status, body = request(base, "GET", "/v1/models", headers=key_headers)
    restored_payload = json.loads(body) if status == 200 else {"data": []}
    check("models unfiltered after key reset",
          status == 200 and any(m["id"] == "deepseek-v4.1-flash"
                                for m in restored_payload.get("data") or []),
          body[:150])

    # ---- 5b. 代理槽：按出口隔离，启用中的槽即该出口全部账号的统一代理 ----
    def slots_of(realm):
        status, body = request(base, "GET", "/proxy-slots%s" %
                               (("?realm=%s" % realm) if realm else ""),
                               headers=panel_headers)
        return json.loads(body).get("slots") or [] if status == 200 else None

    intl_url, cn_url = "http://127.0.0.1:17901", "http://127.0.0.1:17902"
    status, body = request(base, "POST", "/proxy-slots/save", {
        "realm": "intl", "slots": [{"name": "国际版代理", "url": intl_url}]},
        panel_headers)
    check("proxy slot save scoped to realm", status == 200, body[:200])
    intl_slot = (json.loads(body).get("slots") or [{}])[0]
    intl_slot_id = intl_slot.get("id") or ""
    check("scoped save stamps realm",
          intl_slot.get("realm") == "intl" and bool(intl_slot_id),
          json.dumps(intl_slot, ensure_ascii=False))
    check("proxy slot hidden from other realm",
          all(s["url"] != intl_url for s in slots_of("cn")), "")
    check("proxy slot visible in own realm",
          any(s["id"] == intl_slot_id for s in slots_of("intl")), "")
    check("enabled slot proxies all accounts of its realm",
          ctx.pool.get("u1").proxy == intl_url, ctx.pool.get("u1").proxy)
    check("other realms stay direct",
          ctx.pool.get("u2").proxy == "", ctx.pool.get("u2").proxy)

    # 另一个出口配自己的槽：互不覆盖，各自生效
    status, body = request(base, "POST", "/proxy-slots/save", {
        "realm": "cn", "slots": [{"name": "国内版代理", "url": cn_url}]},
        panel_headers)
    check("second realm save keeps first realm slot",
          status == 200 and any(s["url"] == intl_url for s in slots_of("intl")), "")
    check("second realm proxies its own accounts",
          ctx.pool.get("u2").proxy == cn_url
          and ctx.pool.get("u1").proxy == intl_url, "")

    # 同一条代理线可以同时配给多个出口：按（出口, URL）去重，不再全局唯一
    status, body = request(base, "POST", "/proxy-slots/save", {
        "realm": "cn", "slots": [{"name": "国内版代理", "url": cn_url},
                                  {"name": "共用线", "url": intl_url}]},
        panel_headers)
    check("same proxy url can serve a second realm",
          status == 200 and any(s["url"] == intl_url for s in slots_of("cn")), "")
    check("each realm resolves its own copy",
          ctx.pool.get("u1").proxy == intl_url
          and ctx.pool.get("u2").proxy == cn_url, "")

    # 停用该出口的槽 → 该出口回落直连，其他出口不受影响
    status, body = request(base, "POST", "/proxy-slots/save", {
        "realm": "intl",
        "slots": [{"id": intl_slot_id, "name": "国际版代理",
                   "url": intl_url, "enabled": False}]}, panel_headers)
    check("disabled slot falls back to direct",
          status == 200 and ctx.pool.get("u1").proxy == ""
          and ctx.pool.get("u2").proxy == cn_url, "")

    # 旧版全局槽（realm 为空）：每个出口都看得到，但不生效；保存即归属当前出口。
    # 全量保存是旧版设置路径的语义：整体替换，上面按出口存的槽会被清掉。
    status, body = request(base, "POST", "/proxy-slots/save", {
        "slots": [{"name": "legacy", "url": "http://127.0.0.1:17903"}]},
        panel_headers)
    check("legacy full replace still works",
          status == 200 and (json.loads(body).get("slots") or [{}])[0].get("realm") == "",
          body[:200])
    check("legacy slot visible in every realm",
          any(s["url"] == "http://127.0.0.1:17903" for s in slots_of("trae")), "")
    check("legacy slot is inert until claimed",
          ctx.pool.get("u1").proxy == "" and ctx.pool.get("u2").proxy == "", "")
    request(base, "POST", "/proxy-slots/save", {
        "realm": "trae", "slots": [{"name": "legacy", "url": "http://127.0.0.1:17903"}]},
        panel_headers)
    check("realm save claims legacy slot",
          all(s.get("realm") == "trae" for s in slots_of("trae")), "")
    check("claimed slot leaves other realms",
          not any(s["url"] == "http://127.0.0.1:17903" for s in slots_of("intl")), "")
    check("claimed slot proxies that realm",
          ctx.pool.get("trae-uid-1").proxy == "http://127.0.0.1:17903",
          ctx.pool.get("trae-uid-1").proxy)
    # 收尾：清掉 trae 的槽，复原其他出口的既有状态
    request(base, "POST", "/proxy-slots/save", {"realm": "trae", "slots": []},
            panel_headers)

    # ---- 5a. 自动化：每个任务自定义整点，渠道任务同样落盘 ----
    status, body = request(base, "POST", "/settings/save", {
        "automation": {"trae_checkin": {"enabled": True, "hours": [7, 18]}}},
        panel_headers)
    check("settings save channel task hours", status == 200, body[:200])
    status, body = request(base, "GET", "/settings", headers=panel_headers)
    automation = (json.loads(body) if status == 200 else {}).get("automation") or {}
    check("channel task hours persisted",
          (automation.get("trae_checkin") or {}).get("hours") == [7, 18],
          json.dumps(automation.get("trae_checkin"), ensure_ascii=False))
    check("missing tasks keep defaults",
          (automation.get("checkin") or {}).get("hours") == [9, 21],
          json.dumps(automation.get("checkin"), ensure_ascii=False))
    request(base, "POST", "/settings/save", {"automation": {"enabled": False}},
            panel_headers)
    status, body = request(base, "GET", "/settings", headers=panel_headers)
    automation = (json.loads(body) if status == 200 else {}).get("automation") or {}
    check("master switch keeps task hours",
          automation.get("enabled") is False
          and (automation.get("trae_checkin") or {}).get("hours") == [7, 18],
          json.dumps(automation, ensure_ascii=False)[:240])
    request(base, "POST", "/settings/save", {
        "automation": {"qoder_checkin": {"enabled": True, "hours": [11, 14]}}},
        panel_headers)
    status, body = request(base, "GET", "/settings", headers=panel_headers)
    automation = (json.loads(body) if status == 200 else {}).get("automation") or {}
    check("task-only save keeps scheduler paused",
          automation.get("enabled") is False,
          json.dumps(automation, ensure_ascii=False)[:240])
    request(base, "POST", "/settings/save", {"automation": {"enabled": True}},
            panel_headers)
    status, body = request(base, "GET", "/scheduler", headers=panel_headers)
    scheduler_payload = json.loads(body) if status == 200 else {}
    check("scheduler exposes channel task hours",
          ((scheduler_payload.get("tasks") or {}).get("trae_checkin") or {}).get("hours")
          == [7, 18],
          json.dumps((scheduler_payload.get("tasks") or {}).get("trae_checkin"),
                     ensure_ascii=False))
    # 上面的检查为了读 /scheduler 打开了自动调度：不关回去，跑到整点的真实
    # 排程就会挤进单线程队列，后面的渠道触发要排在它后面等（22 点的保活巡检
    # 曾把 zcode 触发堵出 10 秒等待窗口）。检查完立即恢复暂停，测试之间不串味。
    request(base, "POST", "/settings/save", {"automation": {"enabled": False}},
            panel_headers)

    # ---- 5b. 运行日志：落库关闭时读进程内日志环 ----
    ctx.log("smoke: 一条运行日志")
    status, body = request(base, "GET", "/logs?limit=20", headers=panel_headers)
    log_payload = json.loads(body) if status == 200 else {}
    check("logs readable from memory ring",
          status == 200 and log_payload.get("source") == "memory"
          and any("smoke:" in (row.get("msg") or "")
                  for row in log_payload.get("logs") or []), body[:200])
    ctx.log("smoke: 手机号 13812345678")
    status, body = request(base, "GET", "/logs?limit=20", headers=panel_headers)
    check("log ring masks phone numbers",
          status == 200 and "138****5678" in body and "13812345678" not in body,
          body[:200])

    # ---- 6. 治理：429 只锁模型 ----
    FAIL_MODE["mode"] = "429"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
        key_headers)
    check("429 surfaced", status == 429 and "rate_limit_error" in body, body[:200])
    account = ctx.pool.get("u1")
    check("429 model-scoped", "glm-5.3" in account.model_cooldowns
          and not account.cooldown_until, str(account.model_cooldowns))
    check("429 other model still usable", account.ready(model="deepseek-v4.1-flash"))

    # ---- 7. 治理：402 停车 ----
    FAIL_MODE["mode"] = "402"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("402 surfaced", status in (402, 503), body[:200])
    from auth.accounts import next_local_4am
    check("402 parked until 04:00",
          account.balance_until == next_local_4am(), str(account.balance_until))
    check("402 blocks all models", not account.ready())

    # ---- 8. 治理：余额恢复抬出停车 ----
    FAIL_MODE["mode"] = ""
    account.credits = {"remain": 100, "packages": []}
    revived = account.revive_balance_cooldown()
    check("revive lifts only the park", revived and account.balance_until == 0.0)
    check("revive keeps model cooldown", "glm-5.3" in account.model_cooldowns)

    # ---- 8b. 模型级 5xx 不罚号 / 11158 权益标记 ----
    FAIL_MODE["mode"] = "model_scoped"
    fails_before = account.fails
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("model-scoped 5xx surfaced",
          status == 502 and "11134" in body, body[:200])
    check("model-scoped 5xx does not charge account",
          account.fails == fails_before and account.breaker_until == 0,
          "fails=%d" % account.fails)

    # 11158 仍然原样透传（不再在网关里记「运行时标记」）：标注改由目录 tier 表
    # 驱动，被门控的模型在本地就被拒，根本走不到上游（上游 v1.7.30 #609）。
    FAIL_MODE["mode"] = "entitlement_11158"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("11158 surfaced", status == 502 and "11158" in body, body[:200])
    FAIL_MODE["mode"] = ""
    # 目录 tier 表把 grok-4.7 标成 standard。冒烟用的是静态目录、不走真实
    # 上游拉取，所以直接把这份 tier 表喂进来（正是生产里 ingest 的形状）。
    from intel import tiers as tiers_mod
    tiers_mod.ingest("intl", {"data": {"modelTiers": [
        {"requiredUserType": "standard", "modelIds": ["grok-4.7"]}]}})
    status, body = request(base, "GET", "/v1/models?realm=intl", headers=key_headers)
    models = json.loads(body) if status == 200 else {}
    pro_row = next((m for m in models.get("data") or []
                    if m.get("id") == "grok-4.7"), {})
    check("catalog tier drives the models entitlement label",
          status == 200
          and (pro_row.get("entitlement") or {}).get("source") == "catalog"
          and (pro_row.get("entitlement") or {}).get("required") == "standard"
          and bool((pro_row.get("entitlement") or {}).get("at")),
          json.dumps(pro_row.get("entitlement"), ensure_ascii=False))
    free_row = next((m for m in models.get("data") or []
                     if m.get("id") == "deepseek-v4.1-flash"), {})
    check("ungated models carry no entitlement label",
          "entitlement" not in free_row,
          json.dumps(free_row.get("entitlement"), ensure_ascii=False))
    status, body = request(base, "GET", "/models/list?realm=intl",
                           headers=panel_headers)
    panel_models = json.loads(body) if status == 200 else {}
    panel_ent = next((m.get("entitlement") for m in panel_models.get("data") or []
                      if m.get("id") == "grok-4.7"), {})
    check("panel models use the same catalog label",
          status == 200 and (panel_ent or {}).get("source") == "catalog",
          json.dumps(panel_ent, ensure_ascii=False))

    # ---- 9. 账号级限流后无号可用；到期/清错后成功请求清掉连击 ----
    wait = account.note_soft_rate("test")
    check("account-level 429 cools whole account", wait >= 600 and not account.ready(),
          str(wait))
    account.clear_error()
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("success clears soft streak", status == 200 and account.soft_streak == 0,
          body[:150])

    # ---- 9b. 流式断流：未出字节时同请求重开一次 ----
    FAIL_MODE["mode"] = "stream_cut_once"
    CUT_STATE["calls"] = 0
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "deepseek-v4.1-flash", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("stream cut before first byte reopened once",
          status == 200 and "你好" in body and "[DONE]" in body
          and CUT_STATE["calls"] == 2,
          "calls=%d %s" % (CUT_STATE["calls"], body[:160]))
    FAIL_MODE["mode"] = ""

    # ---- 10. 用量记账 ----
    snapshot = ctx.usage.snapshot()
    check("usage recorded", snapshot["requests"] >= 4
          and snapshot["total_tokens"] >= 18, json.dumps(snapshot)[:200])
    perf = ctx.usage.perf()
    check("usage perf", perf["sampled"] >= 4, json.dumps(perf)[:200])
    check("no pricing fields on dashboard",
          not any(key in json.dumps(snapshot) for key in ("cost", "price", "cny", "usd")))

    # ---- 11. 调度任务可手动触发（假上游能应答） ----
    result, settled = _trigger_and_settle(ctx, "checkin")
    check("scheduler trigger accepted", result.get("ok") is True, json.dumps(result))
    check("scheduler trigger settles before its assertions", settled,
          json.dumps(result, ensure_ascii=False))
    records = ctx.usage and __import__("tasks.taskstore", fromlist=["x"]).list_logs(limit=10)
    check("task results persisted", any(row["kind"] in ("checkin", "summary")
                                        for row in records),
          json.dumps(records[:3], ensure_ascii=False)[:200])

    # 启动补跑由渠道在任务默认值里声明，调度器只按通用字段执行。
    from integrations import workbuddy as wb_mod
    check("daily chat declares startup catchup",
          ctx.scheduler._config().get("dailychat", {}).get("startup") is True,
          str(ctx.scheduler._config().get("dailychat")))
    queued = []
    saved_specs = ctx.scheduler.task_specs
    saved_config = ctx.scheduler._config
    saved_enqueue = ctx.scheduler.enqueue
    ctx.scheduler.task_specs = lambda: [
        ("startup-probe", "启动探针", lambda *a, **k: None,
         {"enabled": True, "hours": [9], "startup": True})]
    ctx.scheduler._config = lambda: {
        "enabled": True,
        "startup-probe": {"enabled": True, "hours": [9], "startup": True}}
    ctx.scheduler.enqueue = lambda task_id, reason, source="manual": (
        queued.append((task_id, source)) or True)
    try:
        ctx.scheduler._enqueue_startup_tasks()
    finally:
        ctx.scheduler.task_specs = saved_specs
        ctx.scheduler._config = saved_config
        ctx.scheduler.enqueue = saved_enqueue
    check("startup tasks are enqueued once",
          queued == [("startup-probe", "startup")], str(queued))

    # 卡在网络上的一轮不能把整个队列拖住；放弃前先替它收会话。
    hang_release = threading.Event()
    logs = []

    class _HangAccount(object):
        uid = "hang-account-0001"

        def daily_chat_budget(self):
            return 1

        def daily_chat(self, trigger="unknown"):
            hang_release.wait(5)
            return {"ok": True, "msg": "late"}

        def web_conversation_reclaim(self, max_age=0):
            return 2

    fake_ctx = type("Ctx", (), {"log": lambda self, msg: logs.append(msg)})()
    with wb_mod._DAILY_CHAT_ABANDONED_LOCK:
        wb_mod._DAILY_CHAT_ABANDONED[:] = []
    try:
        hang_res = wb_mod._do_dailychat(fake_ctx, _HangAccount(), "auto", wait=0.2)
        check("hung daily chat is abandoned and reclaimed",
              hang_res.get("status") == "error"
              and hang_res.get("phase") == "hang"
              and "代为收尾 2 条" in hang_res.get("message", "")
              and any("仍未返回" in line for line in logs),
              json.dumps(hang_res, ensure_ascii=False))
        check("abandoned daily chat worker is counted",
              len(wb_mod._DAILY_CHAT_ABANDONED) == 1,
              str(len(wb_mod._DAILY_CHAT_ABANDONED)))
        class _Alive(object):
            def is_alive(self):
                return True
        with wb_mod._DAILY_CHAT_ABANDONED_LOCK:
            wb_mod._DAILY_CHAT_ABANDONED[:] = [
                _Alive() for _ in range(wb_mod.DAILY_CHAT_ABANDONED_MAX)]
        skip_res = wb_mod._do_dailychat(fake_ctx, _HangAccount(), "auto", wait=0.2)
        check("abandoned worker cap skips new daily chat",
              skip_res.get("status") == "skip", json.dumps(skip_res))
    finally:
        hang_release.set()
        with wb_mod._DAILY_CHAT_ABANDONED_LOCK:
            wb_mod._DAILY_CHAT_ABANDONED[:] = []

    # 当天已签到也不能被本地日期闸门跳过：上游每日签到幂等（10001），
    # 重跑才能覆盖非 UTC+8 服务器的跨日场景。
    cn_checkin_acc = ctx.pool.get("u2")
    cn_checkin_acc.last_checkin = time.strftime("%Y-%m-%d 09:00:00")
    cn_checkin_before = CHECKIN_STATE["calls"]
    result, _settled_again = _trigger_and_settle(ctx, "checkin")
    check("cn checkin re-runs despite same-day lastCheckin",
          result.get("ok") is True
          and CHECKIN_STATE["calls"] == cn_checkin_before + 1,
          json.dumps(result, ensure_ascii=False)
          + " calls=%d" % CHECKIN_STATE["calls"])

    # 签到回执必须按文案归类：10001 不是「签到成功」专属码，把「请求处理中」
    # 记成已签会让当天这次失败被永久放弃（上游 v1.7.30 #596）。
    from auth.accounts import checkin_state as _checkin_state
    check("checkin state classifies replies",
          _checkin_state(0, "ok") == "checked"
          and _checkin_state(0, "签到成功，距离 7 天奖励还不足") == "checked"
          and _checkin_state(0, "签到失败，已签到天数不足 7 天") == "failed"
          and _checkin_state(10001, "今日已签到") == "already"
          and _checkin_state(10001, "请求处理中，请勿重复操作") == "pending"
          and _checkin_state(-1, "whatever") == "failed",
          "%r %r %r" % (_checkin_state(0, "签到失败"),
                        _checkin_state(10001, "今日已签到"),
                        _checkin_state(10001, "请求处理中，请勿重复操作")))
    from tests.upstreams.workbuddy import CHECKIN_REPLY
    try:
        for reply, expect_ok, expect_state in (
                ("pending", False, "pending"),
                ("failed", False, "failed"),
                ("already", True, "already")):
            cn_checkin_acc.last_checkin = None
            CHECKIN_REPLY["mode"] = reply
            outcome = cn_checkin_acc.checkin(trigger="smoke")
            check("checkin %s reply maps to %s" % (reply, expect_state),
                  bool(outcome.get("ok")) is expect_ok
                  and outcome.get("state") == expect_state,
                  json.dumps(outcome, ensure_ascii=False)[:200])
            check("checkin %s reply leaves last_checkin %s"
                  % (reply, "unset" if not expect_ok else "set"),
                  bool(cn_checkin_acc.last_checkin) is expect_ok,
                  str(cn_checkin_acc.last_checkin))
    finally:
        CHECKIN_REPLY["mode"] = ""
        cn_checkin_acc.last_checkin = time.strftime("%Y-%m-%d 09:00:00")

    # ---- 11b. 每日活跃网页会话跑完即释放 ----
    # 上游对单账号活跃会话有 10 条硬上限：只建不收尾，攒满后建会话一律
    # 429 / 10105（上游 v1.7.30 #623）。这里用假上游验证三种收尾：
    # 成功 stop、失败 stop+delete、撞上限时清理最旧的本网关会话。
    from tests.upstreams.workbuddy import CONVERSATION_STATE
    from core import webagent as webagent_mod
    web_chat_acc = ctx.pool.get("u1")

    def _stub_run_turn(ok):
        def fake(link, token, session_id, cwd, prompt, user_agent, **kwargs):
            return {"ok": ok, "chunks": 1 if ok else 0,
                    "elapsed_ms": 1, "error": "" if ok else "sandbox failed"}
        return fake

    saved_run_turn = webagent_mod.run_turn
    try:
        CONVERSATION_STATE.update({"active": [], "stopped": [], "deleted": [],
                                   "full": False, "created": 0})
        webagent_mod.run_turn = _stub_run_turn(True)
        ok_result = web_chat_acc.daily_chat_web(trigger="smoke")
        check("daily chat releases a finished conversation",
              ok_result.get("ok") is True
              and CONVERSATION_STATE["stopped"] == ["conv-1"]
              and CONVERSATION_STATE["deleted"] == [],
              "%r %r" % (CONVERSATION_STATE["stopped"],
                         CONVERSATION_STATE["deleted"]))

        CONVERSATION_STATE.update({"active": [], "stopped": [], "deleted": [],
                                   "full": False, "created": 0})
        webagent_mod.run_turn = _stub_run_turn(False)
        fail_result = web_chat_acc.daily_chat_web(trigger="smoke")
        # 失败轮会按策略重试，每次重试建一条新会话；每一条都要 stop + delete，
        # 一条都不能留成活跃名额（这正是攒满十天上限的来源）。
        check("daily chat deletes every failed conversation",
              fail_result.get("ok") is False
              and bool(CONVERSATION_STATE["created"])
              and CONVERSATION_STATE["stopped"] == CONVERSATION_STATE["deleted"]
              and len(CONVERSATION_STATE["deleted"]) == CONVERSATION_STATE["created"],
              "created=%d stopped=%r deleted=%r"
              % (CONVERSATION_STATE["created"], CONVERSATION_STATE["stopped"],
                 CONVERSATION_STATE["deleted"]))

        # 撞上限：10 条活跃会话（旧版本漏下的），清理后仍能建出新的
        CONVERSATION_STATE.update({"active": [], "stopped": [], "deleted": [],
                                   "full": True, "created": 0})
        pool_names = web_chat_acc._daily_activity_prompt_pool()
        prompt = next(iter(n for n in pool_names if n), "Hi")
        for index in range(10):
            CONVERSATION_STATE["active"].append({
                "id": "old-%d" % index, "name": prompt, "status": "working",
                "createdAt": "2026-10-20T00:00:%02dZ" % index})
        CONVERSATION_STATE["active"].append({
            "id": "user-own", "name": "我自己写的对话", "status": "working",
            "createdAt": "2026-10-19T00:00:00Z"})
        freed = web_chat_acc.web_conversation_prune()
        check("conversation prune stops only our own old conversations",
              freed >= 1
              and "user-own" not in CONVERSATION_STATE["stopped"]
              and all(sid.startswith("old-") for sid in CONVERSATION_STATE["stopped"]),
              "freed=%d stopped=%r" % (freed, CONVERSATION_STATE["stopped"]))

        CONVERSATION_STATE["full"] = False
        webagent_mod.run_turn = _stub_run_turn(True)
        after_prune = web_chat_acc.daily_chat_web(trigger="smoke")
        check("daily chat succeeds after pruning at the active limit",
              after_prune.get("ok") is True,
              json.dumps(after_prune, ensure_ascii=False)[:200])

        # 卡在 socket 上的一轮走不到 finally：登记表让别的线程代收尾。
        CONVERSATION_STATE.update({"active": [], "stopped": [], "deleted": [],
                                   "full": False, "created": 0})
        accounts_mod.web_live_register(web_chat_acc.uid, "conv-stuck", "m1")
        try:
            reclaimed = web_chat_acc.web_conversation_reclaim(0)
            check("stuck web conversations can be reclaimed from the registry",
                  reclaimed == 1
                  and CONVERSATION_STATE["stopped"] == ["conv-stuck"]
                  and CONVERSATION_STATE["deleted"] == ["conv-stuck"]
                  and accounts_mod.web_live_snapshot(web_chat_acc.uid) == [],
                  "reclaimed=%r stopped=%r deleted=%r"
                  % (reclaimed, CONVERSATION_STATE["stopped"],
                     CONVERSATION_STATE["deleted"]))
        finally:
            accounts_mod.web_live_unregister(web_chat_acc.uid, "conv-stuck")

        # 进程重启后只剩上游会话列表：只停我们建的、够老的、仍在跑的。
        now = time.time()
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200))
        fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 30))
        prompt = next(iter(n for n in web_chat_acc._daily_activity_prompt_pool() if n),
                      "Hi")
        CONVERSATION_STATE.update({
            "active": [
                {"id": "old-mine", "name": prompt, "status": "working",
                 "createdAt": old},
                {"id": "fresh-mine", "name": prompt, "status": "working",
                 "createdAt": fresh},
                {"id": "old-user", "name": "我的季度报告", "status": "working",
                 "createdAt": old},
                {"id": "old-done", "name": prompt, "status": "completed",
                 "createdAt": old},
            ],
            "stopped": [], "deleted": [], "full": False, "created": 0})
        swept = web_chat_acc.web_conversation_sweep_orphans()
        check("orphan sweep only stops old gateway-owned active conversations",
              swept == 1 and CONVERSATION_STATE["stopped"] == ["old-mine"],
              "swept=%r stopped=%r" % (swept, CONVERSATION_STATE["stopped"]))

        saved_registry = dict(accounts_mod._WEB_LIVE)
        try:
            with accounts_mod._WEB_LIVE_LOCK:
                accounts_mod._WEB_LIVE.clear()
            for index in range(accounts_mod.WEB_LIVE_REGISTRY_MAX + 4):
                accounts_mod.web_live_register("bulk", "conv-%03d" % index)
            check("web conversation registry is bounded",
                  len(accounts_mod.web_live_snapshot())
                  <= accounts_mod.WEB_LIVE_REGISTRY_MAX,
                  str(len(accounts_mod.web_live_snapshot())))
        finally:
            with accounts_mod._WEB_LIVE_LOCK:
                accounts_mod._WEB_LIVE.clear()
                accounts_mod._WEB_LIVE.update(saved_registry)
    finally:
        webagent_mod.run_turn = saved_run_turn
        CONVERSATION_STATE.update({"active": [], "stopped": [], "deleted": [],
                                   "full": False, "created": 0})

    # ---- 12. 连登管家：首轮有收益，二跑幂等无重复收益 ----
    from tasks import streak as streak_mod
    account_cn = next(a for a in ctx.pool.accounts if a.realm == "cn")
    STREAK_STATE.update({"makeup_used": 0, "gift_claimed": False,
                         "lottery_drawn": False})
    first = streak_mod.run(account_cn)
    first_credit = int(first.get("credit") or 0)
    check("streak first run earns credit",
          first.get("ok") is True and first_credit > 0
          and STREAK_STATE["makeup_used"] == 1,
          json.dumps(first, ensure_ascii=False)[:300])
    second = streak_mod.run(account_cn)
    check("streak rerun idempotent",
          second.get("ok") is True and int(second.get("credit") or 0) == 0
          and STREAK_STATE["makeup_used"] == 1,
          json.dumps(second, ensure_ascii=False)[:300])


    env = SmokeEnv(ctx, gateway, base, key_headers, upstreams)
    env.panel_headers = panel_headers
    for module in (trae, qoder, zcode, codearts, loomy):
        module.run(env)

    # ---- 33. 面板渠道清单下发 ZCode ----
    status, body = request(base, "GET", "/channels", headers=panel_headers)
    channels_payload = json.loads(body) if status == 200 else {}
    zchannel = next((c for c in channels_payload.get("channels") or []
                     if c.get("id") == "zcode"), None)
    zrealm = next((r for r in channels_payload.get("realms") or []
                   if r.get("id") == "zcode"), {})
    zcaps = (zchannel or {}).get("capabilities") or []
    check("panel channels include zcode",
          bool(zchannel) and "checkin" not in zcaps and "scheduler" not in zcaps
          and "desktop_import" in zcaps and "paste_token" in zcaps, body[:240])
    check("panel zcode realm metadata",
          zrealm.get("channel") == "zcode"
          and zrealm.get("badge") == "ZCode"
          and zrealm.get("domain") == "zcode.z.ai"
          and zrealm.get("desktop_import") is True,
          json.dumps(zrealm, ensure_ascii=False)[:240])
    check("panel zcode has no claim labels",
          not (zchannel or {}).get("checkin_labels"),
          json.dumps((zchannel or {}).get("checkin_labels"), ensure_ascii=False)[:240])
    cchannel = next((c for c in channels_payload.get("channels") or []
                     if c.get("id") == "codearts"), None)
    crealm = next((r for r in channels_payload.get("realms") or []
                   if r.get("id") == "codearts"), {})
    ccaps = (cchannel or {}).get("capabilities") or []
    check("panel channels include codearts",
          bool(cchannel)
          and {"chat", "responses", "models", "accounts", "checkin",
               "scheduler", "proxy_slot", "paste_token"} <= set(ccaps),
          body[:240])
    check("panel codearts realm metadata",
          crealm.get("channel") == "codearts"
          and crealm.get("badge") == "CodeArts"
          and crealm.get("domain") == "codearts.huaweicloud.com"
          and crealm.get("desktop_import") is False,
          json.dumps(crealm, ensure_ascii=False)[:240])
    clabels = (cchannel or {}).get("checkin_labels") or {}
    check("panel codearts checkin labels use sign-in wording",
          clabels.get("action") == "签到"
          and clabels.get("pending") == "未签到"
          and clabels.get("done") == "已签到",
          json.dumps(clabels, ensure_ascii=False)[:240])
    lchannel = next((c for c in channels_payload.get("channels") or []
                     if c.get("id") == "loomy"), None)
    lrealm = next((r for r in channels_payload.get("realms") or []
                   if r.get("id") == "loomy"), {})
    lcaps = (lchannel or {}).get("capabilities") or []
    check("panel channels include loomy",
          bool(lchannel)
          and {"chat", "models", "accounts", "checkin", "scheduler",
               "proxy_slot"} <= set(lcaps)
          and "paste_token" not in lcaps
          and "desktop_import" not in lcaps, body[:240])
    check("panel loomy realm metadata",
          lrealm.get("channel") == "loomy"
          and lrealm.get("badge") == "Loomy"
          and lrealm.get("domain") == "loomyad.xunfei.cn"
          and lrealm.get("desktop_import") is False,
          json.dumps(lrealm, ensure_ascii=False)[:240])
    llabels = (lchannel or {}).get("checkin_labels") or {}
    check("panel loomy checkin labels use refresh wording",
          llabels.get("action") == "刷新积分"
          and llabels.get("pending") == "今日未刷新"
          and llabels.get("done") == "今日已刷新",
          json.dumps(llabels, ensure_ascii=False)[:240])
    overrides = sorted(c.get("id") for c in channels_payload.get("channels") or []
                       if c.get("checkin_labels"))
    check("only codearts and loomy override checkin labels",
          overrides == ["codearts", "loomy"], json.dumps(overrides))

    # 排程隔离不变量（尾）：用例可以临时打开自动排程（读 /scheduler 需要），
    # 但必须关回去 —— 整点残留的真实排程会挤进单线程队列，让下一个用例的
    # 触发等待窗口失效（这就是曾经 5 项 zcode 检查集体变红的根因）。
    automation_end = ctx.automation_config()
    check("scheduler left paused by the suite",
          automation_end.get("enabled") is False,
          json.dumps(automation_end.get("enabled")))

    gateway.shutdown()
    for server, _base in upstreams.values():
        server.shutdown()
    print()
    failed = failures()
    if failed:
        print("FAILED: %d check(s): %s" % (len(failed), ", ".join(failed)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
