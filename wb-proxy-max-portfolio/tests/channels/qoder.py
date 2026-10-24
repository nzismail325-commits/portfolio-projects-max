# -*- coding: utf-8 -*-
"""Qoder 渠道检查（从 test_smoke.py 拆出；入口仍是 tests/test_smoke.py）。"""
import json
import time

from tests.harness import check, request
from tests.upstreams.qoder import (QODER_STATE, QODER_FAIL_MODE,
                                   QODER_CAMPAIGN_MODE)


def run(env):
    ctx = env.ctx
    base = env.base
    key_headers = env.key_headers
    panel_headers = env.panel_headers
    # ---- 18. Qoder 渠道：签名代理链路（qoder/ 前缀直达） ----
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "qoder/auto", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("qoder prefixed chat stream",
          status == 200 and "你好，Qoder" in body and "[DONE]" in body,
          body[:200])
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "qoder/auto",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    chat = json.loads(body) if status == 200 else {}
    message = ((chat.get("choices") or [{}])[0].get("message") or {})
    check("qoder non-stream aggregated",
          status == 200 and message.get("content") == "你好，Qoder！", body[:200])
    status, body = request(base, "POST", "/v1/responses", {
        "model": "qoder/auto", "input": "hi"}, key_headers)
    response_obj = json.loads(body) if status == 200 else {}
    check("qoder responses translated",
          status == 200 and response_obj.get("output_text") == "你好，Qoder！",
          body[:200])

    # ---- 19. Qoder 目录 / 额度 / 出口隔离 ----
    status, body = request(base, "GET", "/v1/models?realm=qoder", headers=key_headers)
    qoder_models = json.loads(body) if status == 200 else {"data": []}
    qoder_ids = [item["id"] for item in qoder_models.get("data") or []]
    check("qoder realm models listed",
          status == 200 and "auto" in qoder_ids and "glm-5.3" in qoder_ids,
          body[:200])
    owner = next((item.get("owned_by") for item in qoder_models.get("data") or []), "")
    check("qoder models owned_by qoder", owner == "qoder", str(owner))
    qoder_acc = ctx.pool.get("qoder-uid-1")
    status, body = request(base, "GET", "/accounts/credits?realm=qoder&refresh=1",
                           headers=panel_headers)
    check("qoder credits fetched", status == 200 and qoder_acc.credits
          and qoder_acc.credits.get("remain") == 361.0,
          json.dumps(qoder_acc.credits, ensure_ascii=False)[:200]
          if qoder_acc and qoder_acc.credits else body[:200])
    status, body = request(base, "GET", "/accounts?realm=qoder", headers=panel_headers)
    qoder_view = json.loads(body) if status == 200 else {"accounts": []}
    qoder_row = next((a for a in qoder_view.get("accounts") or []
                      if a["uid"] == "qoder-uid-1"), {})
    check("panel qoder account listed",
          bool(qoder_row) and qoder_row.get("channel") == "qoder", body[:200])
    check("panel qoder machineId from meta",
          qoder_row.get("machineId") == "machine-test",
          str(qoder_row.get("machineId")))
    check("panel qoder identity pending",
          qoder_row.get("loginAccount") == "Qoder测试号"
          and qoder_row.get("identityPending") is True,
          json.dumps({k: qoder_row.get(k) for k in
                      ("loginAccount", "identityPending")}, ensure_ascii=False))
    status, body = request(base, "POST", "/accounts/identity/sync",
                           {"uid": "qoder-uid-1"}, panel_headers)
    synced = json.loads(body) if status == 200 else {}
    check("qoder login identity synced",
          status == 200 and synced.get("ok") is True
          and synced.get("loginAccount") == "qoder@example.com"
          and qoder_acc.meta.get("loginAccount") == "qoder@example.com",
          body[:200])
    status, body = request(base, "GET", "/accounts?realm=qoder", headers=panel_headers)
    qoder_view = json.loads(body) if status == 200 else {"accounts": []}
    qoder_row = next((a for a in qoder_view.get("accounts") or []
                      if a["uid"] == "qoder-uid-1"), {})
    check("panel qoder identity shown",
          qoder_row.get("loginAccount") == "qoder@example.com"
          and qoder_row.get("identityPending") is False, body[:200])
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
        key_headers)
    check("bare glm-5.3 still goes to workbuddy",
          status == 200 and "你好，世界" in body, body[:150])

    # ---- 20. Qoder 治理：116 停车 / 10605 冷却 / 101 签名不罚号 ----
    QODER_FAIL_MODE["mode"] = "116"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "qoder/auto",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("qoder 116 surfaced as 402", status == 402, body[:200])
    check("qoder 116 parked until 04:00", qoder_acc.balance_until > 0
          and qoder_acc.unavailable_reason().startswith("余额停车"),
          qoder_acc.unavailable_reason())
    qoder_acc.balance_until = 0.0
    qoder_acc.clear_error()
    QODER_FAIL_MODE["mode"] = ""

    QODER_FAIL_MODE["mode"] = "10605"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "qoder/auto",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("qoder 10605 surfaced as 429", status == 429, body[:200])
    check("qoder 10605 cooled account", qoder_acc.cooldown_until > time.time(),
          str(qoder_acc.cooldown_until))
    check("qoder 10605 honors upstream wait",
          qoder_acc.cooldown_until - time.time() <= 10.5,
          str(qoder_acc.cooldown_until - time.time()))
    qoder_acc.clear_error()
    QODER_FAIL_MODE["mode"] = ""

    QODER_FAIL_MODE["mode"] = "101"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "qoder/auto",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("qoder 101 surfaced as 403", status == 403, body[:200])
    check("qoder 101 does not punish account",
          qoder_acc.ready() and qoder_acc.cooldown_until == 0
          and qoder_acc.balance_until == 0,
          qoder_acc.unavailable_reason())
    QODER_FAIL_MODE["mode"] = ""

    # ---- 20b. Qoder 流内 116（未出内容）自动换号 ----
    ctx.pool.set_enabled("qoder-uid-2", True)
    qoder_acc.weight = 50
    QODER_STATE["chat_calls"] = 0
    QODER_FAIL_MODE["mode"] = "116_once"
    try:
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "qoder/auto",
            "messages": [{"role": "user", "content": "hi"}]}, key_headers)
        check("qoder in-stream 116 rotates to next account",
              status == 200 and "你好，Qoder" in body, body[:200])
        check("qoder in-stream 116 parks failed account",
              qoder_acc.balance_until > 0, qoder_acc.unavailable_reason())
    finally:
        QODER_FAIL_MODE["mode"] = ""
        qoder_acc.weight = 1
        qoder_acc.balance_until = 0.0
        qoder_acc.clear_error()
        ctx.pool.set_enabled("qoder-uid-2", False)

    # ---- 21. Qoder 每日领取（风控身份用测试替身） ----
    result = ctx.scheduler.trigger_now("qoder_checkin")
    check("qoder scheduler trigger accepted", result.get("ok") is True,
          json.dumps(result))
    records = []
    deadline = time.time() + 10
    while time.time() < deadline:
        records = __import__("tasks.taskstore", fromlist=["x"]).list_logs(
            kind="qoder_checkin", limit=10)
        if records:
            break
        time.sleep(0.5)
    check("qoder checkin task persisted",
          any(row["kind"] == "qoder_checkin" for row in records),
          json.dumps(records[:3], ensure_ascii=False)[:200])
    check("qoder checkin marked on account",
          str(qoder_acc.last_checkin or "").startswith(time.strftime("%Y-%m-%d")),
          str(qoder_acc.last_checkin))
    check("qoder claim reached upstream", QODER_STATE["claims"] >= 1,
          str(QODER_STATE["claims"]))

    # ---- 21b. Qoder 领取记账：只有当前窗口的积分活动才算已领取 ----
    import integrations.qoder as qoder_mod

    def run_checkin(mode):
        QODER_CAMPAIGN_MODE["mode"] = mode
        qoder_acc.last_checkin = None
        before = QODER_STATE["claims"]
        result = qoder_mod.checkin_for_account(qoder_acc, trigger="manual")
        return result, QODER_STATE["claims"] - before

    try:
        result, claims = run_checkin("empty")
        check("qoder empty campaign list is not recorded as claimed",
              result.get("ok") is False and qoder_acc.last_checkin is None
              and claims == 0,
              json.dumps(result, ensure_ascii=False) + " claims=%d" % claims)
        result, claims = run_checkin("history_claimed")
        check("qoder historical claimed campaign is not today's checkin",
              result.get("ok") is False and qoder_acc.last_checkin is None
              and claims == 0,
              json.dumps(result, ensure_ascii=False) + " claims=%d" % claims)
        result, claims = run_checkin("expired_claimable")
        check("qoder expired campaign is not claimed",
              result.get("ok") is False and qoder_acc.last_checkin is None
              and claims == 0,
              json.dumps(result, ensure_ascii=False) + " claims=%d" % claims)
        result, claims = run_checkin("active_claimed")
        check("qoder active claimed campaign marks checkin without claim",
              result.get("ok") is True and result.get("already") is True
              and str(qoder_acc.last_checkin or "").startswith(
                  time.strftime("%Y-%m-%d"))
              and claims == 0,
              json.dumps(result, ensure_ascii=False) + " claims=%d" % claims)
        qoder_acc.last_checkin = time.strftime("%Y-%m-%d 09:00:00")
        before = QODER_STATE["claims"]
        QODER_CAMPAIGN_MODE["mode"] = "empty"
        result = qoder_mod.checkin_for_account(qoder_acc, trigger="manual")
        check("qoder stale same-day checkin cleared without campaign",
              result.get("noCampaign") is True and qoder_acc.last_checkin is None
              and QODER_STATE["claims"] == before,
              json.dumps(result, ensure_ascii=False))
    finally:
        QODER_CAMPAIGN_MODE["mode"] = ""

    # ---- 22. Qoder 本机导入（面板路由按 realm 分发） ----
    status, body = request(base, "GET", "/accounts/import-desktop",
                           headers=panel_headers)
    candidates = (json.loads(body) if status == 200 else {}).get("candidates") or []
    qoder_candidate = next((c for c in candidates
                            if c.get("realm") == "qoder_intl"), None)
    check("qoder desktop candidate listed",
          status == 200 and bool(qoder_candidate)
          and qoder_candidate.get("usable") is True
          and qoder_candidate.get("realmLabel"), body[:200])
    status, body = request(base, "POST", "/accounts/import-desktop", {
        "import": True, "realm": "qoder_intl", "path": "auth.v1.dat"},
        panel_headers)
    imported = ctx.pool.get("qoder-intl-import")
    check("qoder_intl desktop import routed",
          status == 200 and imported is not None
          and imported.realm == "qoder_intl"
          and imported.meta.get("machineId") == "machine-import",
          body[:200])
    check("qoder desktop import keeps login identity",
          imported is not None
          and imported.meta.get("loginAccount") == "qoder-import@example.com"
          and imported.public().get("loginAccount") == "qoder-import@example.com",
          json.dumps(imported.meta if imported else {}, ensure_ascii=False)[:200])

    # ---- 23. 面板渠道清单下发 Qoder ----
    status, body = request(base, "GET", "/channels", headers=panel_headers)
    channels_payload = json.loads(body) if status == 200 else {}
    qoder_channel = next((c for c in channels_payload.get("channels") or []
                          if c.get("id") == "qoder"), None)
    qoder_realm = next((r for r in channels_payload.get("realms") or []
                        if r.get("id") == "qoder"), {})
    qoder_caps = (qoder_channel or {}).get("capabilities") or []
    check("panel channels include qoder",
          bool(qoder_channel) and "checkin" in qoder_caps
          and "desktop_import" in qoder_caps, body[:200])
    check("panel qoder realm metadata",
          qoder_realm.get("channel") == "qoder"
          and qoder_realm.get("desktop_import") is True
          and bool(qoder_realm.get("badge")), json.dumps(qoder_realm)[:200])

