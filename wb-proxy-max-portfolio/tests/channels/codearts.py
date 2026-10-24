# -*- coding: utf-8 -*-
"""Codearts 渠道检查（从 test_smoke.py 拆出；入口仍是 tests/test_smoke.py）。"""
import json
import time
import urllib.parse

from tests.harness import check, request
from auth import accounts as accounts_mod
from tests.upstreams.codearts import (
    CODEARTS_FAIL_MODE, CODEARTS_STATE, verify_codearts_es256,
)


def run(env):
    ctx = env.ctx
    base = env.base
    key_headers = env.key_headers
    panel_headers = env.panel_headers
    # ---- 32b. CodeArts：签名、三源目录、对话、双账、福利、登录 ----
    from integrations import codearts as codearts_mod
    check("codearts signer canonical vectors",
          codearts_mod._canonical_uri(b"/api/v2/chat/completions")
          == "/api/v2/chat/completions/"
          and codearts_mod._canonical_query("b=2&a=1&a=0") == "a=0&a=1&b=2"
          and codearts_mod._encode_component(b"!'()*") == "!'()*",
          "%s | %s" % (codearts_mod._canonical_uri(b"/x"),
                       codearts_mod._canonical_query("b=2&a=1")))
    ca_pair = codearts_mod.generate_dpop_key_pair()
    ca_proof = codearts_mod.dpop_proof(ca_pair, "POST", codearts_mod.TOKEN_URL)
    ca_h, ca_p, ca_sig = ca_proof.split(".")
    ca_header = json.loads(codearts_mod._b64url_decode(ca_h))
    ca_payload = json.loads(codearts_mod._b64url_decode(ca_p))
    check("codearts dpop proof verifies",
          ca_header.get("alg") == "ES256"
          and ca_payload.get("htm") == "POST"
          and ca_payload.get("htu") == codearts_mod.TOKEN_URL
          and verify_codearts_es256(
              ca_header.get("jwk") or {},
              ("%s.%s" % (ca_h, ca_p)).encode("ascii"),
              codearts_mod._b64url_decode(ca_sig)),
          ca_payload.get("htu", ""))

    CODEARTS_STATE["welfare_items"] = [{
        "campaignId": 1, "type": "USER_LOGIN",
        "title": "每日签到领积分", "benefitAmount": 1000,
        "benefitUnit": "CREDIT", "status": None, "claimable": True}]
    codearts_mod.reset_caches()
    status, body = request(base, "GET", "/v1/models?realm=codearts",
                           headers=key_headers)
    ca_models = json.loads(body) if status == 200 else {"data": []}
    ca_ids = [item["id"] for item in ca_models.get("data") or []]
    check("codearts catalog merges three sources",
          status == 200 and {"GLM-5.2", "DeepSeek-V4", "Benefit-Qwen"}
          <= set(ca_ids), body[:240])
    ca_meta = dict(codearts_mod.live_models("codearts", ctx=ctx))
    check("codearts catalog source tags",
          (ca_meta.get("GLM-5.2") or {}).get("source") == "agent"
          and (ca_meta.get("DeepSeek-V4") or {}).get("source") == "builtin"
          and (ca_meta.get("Benefit-Qwen") or {}).get("source") == "benefit"
          and (ca_meta.get("DeepSeek-V4") or {}).get("supportsImages") is True,
          json.dumps({k: v.get("source") for k, v in ca_meta.items()},
                     ensure_ascii=False)[:240])
    ca_credit_map = {item.get("id"): item.get("credits")
                     for item in ca_models.get("data") or []}
    check("codearts model credit ratios surfaced",
          ca_credit_map.get("GLM-5.2") == "0.62x"
          and ca_credit_map.get("DeepSeek-V4") == "0.18x",
          json.dumps(ca_credit_map, ensure_ascii=False)[:240])
    check("codearts builtin sends PromptCenter agent type",
          CODEARTS_STATE["builtin_agent_type"] == "PromptCenter",
          CODEARTS_STATE["builtin_agent_type"])
    check("codearts agent list uses AgentCenter and inline models",
          CODEARTS_STATE["agent_agent_type"] == "AgentCenter"
          and CODEARTS_STATE["agent_calls"] >= 1
          and CODEARTS_STATE["detail_calls"] == 0,
          "agent_type=%s calls=%s detail=%s" % (
              CODEARTS_STATE["agent_agent_type"],
              CODEARTS_STATE["agent_calls"],
              CODEARTS_STATE["detail_calls"]))
    ca_owner = next((item.get("owned_by") for item in
                     ca_models.get("data") or []), "")
    check("codearts models owned_by codearts", ca_owner == "codearts", ca_owner)

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/glm-5.2", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("codearts prefixed chat stream",
          status == 200 and "你好，CodeArts" in body and "[DONE]" in body,
          body[:200])
    ca_headers = CODEARTS_STATE.get("last_headers") or {}
    ca_signed = str(ca_headers.get("authorization") or "")
    check("codearts request signed with model headers",
          ca_signed.startswith("SDK-HMAC-SHA256 Access=AK-seed")
          and "model-id" in ca_signed and "x-model-id" in ca_signed
          and ca_headers.get("model-id") == "GLM-5.2"
          and ca_headers.get("x-security-token") == "STS-seed"
          and ca_headers.get("x-domain-id") == "dom-seed",
          ca_signed[:160])
    check("codearts resolves model case to true name",
          (CODEARTS_STATE.get("last_payload") or {}).get("model") == "GLM-5.2",
          str((CODEARTS_STATE.get("last_payload") or {}).get("model")))

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/DeepSeek-V4",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    ca_chat = json.loads(body) if status == 200 else {}
    ca_message = ((ca_chat.get("choices") or [{}])[0].get("message") or {})
    check("codearts non-stream aggregated",
          status == 200 and ca_message.get("content") == "你好，CodeArts",
          body[:200])
    status, body = request(base, "POST", "/v1/responses", {
        "model": "codearts/GLM-5.2", "input": "hi"}, key_headers)
    ca_resp = json.loads(body) if status == 200 else {}
    check("codearts responses translated",
          status == 200 and ca_resp.get("output_text") == "你好，CodeArts",
          body[:200])

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/Benefit-Qwen",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    ca_headers = CODEARTS_STATE.get("last_headers") or {}
    check("codearts benefit model sends maas_type",
          status == 200 and ca_headers.get("maas_type") == "benefit"
          and ca_headers.get("x-model-id") == "Benefit-Qwen",
          body[:160])

    status, body = request(
        base, "GET", "/accounts/credits?realm=codearts&refresh=1",
        headers=panel_headers)
    ca_credit_payload = json.loads(body) if status == 200 else {}
    ca_view = next((item for item in ca_credit_payload.get("accounts") or []
                    if item.get("uid") == "dom-seed-user-seed"), {})
    ca_credits = ca_view.get("credits") or {}
    ca_wallets = ca_credits.get("wallets") or []
    ca_pkg_names = [item.get("name") for item in
                    ca_credits.get("packages") or []]
    ca_credit = next((item for item in ca_wallets
                      if item.get("type") == "credits"), {})
    ca_benefit = next((item for item in ca_wallets
                       if item.get("displayName") == "福利 Token 池"), {})
    ca_basic = next((item for item in ca_credits.get("packages") or []
                     if item.get("name") == "套餐积分"), {})
    ca_bonus = next((item for item in ca_credits.get("packages") or []
                     if item.get("name") == "赠送积分"), {})
    check("codearts balance uses credit ledger not token sentinel",
          status == 200 and "套餐积分" in ca_pkg_names
          and "赠送积分" in ca_pkg_names
          and "福利 Token 池" in ca_pkg_names
          and ca_credit.get("balance") == 5250
          and ca_credit.get("unit") == "积分"
          and ca_basic.get("remain") == 250
          and ca_basic.get("size") == 500
          and ca_bonus.get("remain") == 5000
          and ca_bonus.get("size") == 5000
          and ca_benefit.get("balance") == 321
          and ca_credits.get("remain") == 5250
          and ca_credits.get("used") == 250
          and ca_credits.get("size") == 5500
          and CODEARTS_STATE["balance_calls"] >= 1,
          json.dumps(ca_credits, ensure_ascii=False)[:400])

    ca_acc = ctx.pool.get("dom-seed-user-seed")
    status, body = request(base, "POST", "/accounts/action", {
        "uid": "dom-seed-user-seed", "action": "checkin"}, panel_headers)
    ca_claim = json.loads(body) if status == 200 else {}
    ca_last_claim = CODEARTS_STATE.get("last_claim") or {}
    ca_last_confirm = CODEARTS_STATE.get("last_confirm") or {}
    check("codearts checkin claims daily campaign via ops api",
          status == 200 and ca_claim.get("ok") is True
          and "签到成功" in str(ca_claim.get("message") or "")
          and "每日签到积分 1000 积分" in str(ca_claim.get("message") or "")
          and CODEARTS_STATE["claims"] == 1
          and CODEARTS_STATE["confirms"] == 1
          and CODEARTS_STATE["delivery_reads"] >= 2
          and ca_last_claim.get("campaignId") == 1
          and ca_last_claim.get("channel") == "DESKTOP"
          and bool(ca_last_claim.get("idempotentKey"))
          and ca_last_confirm.get("campaignId") == 1
          and int(ca_last_confirm.get("userBenefitId") or 0) == 9001
          and CODEARTS_STATE["welfare_items"][0]["status"] == "CONFIRMED",
          body[:300])
    check("codearts checkin marks last_checkin after claim",
          ca_acc is not None
          and str(ca_acc.last_checkin or "")[:10] == time.strftime("%Y-%m-%d"),
          str(getattr(ca_acc, "last_checkin", "")))
    status, body = request(base, "POST", "/accounts/action", {
        "uid": "dom-seed-user-seed", "action": "checkin"}, panel_headers)
    ca_claim2 = json.loads(body) if status == 200 else {}
    check("codearts checkin write-rate-limited",
          ca_claim2.get("ok") is False
          and "操作太频繁" in str(ca_claim2.get("message") or ""),
          body[:200])

    # ---- 32c. 新用户注册积分只领一次；每日已签时仍标记今日完成 ----
    ca_acc.last_checkin = None
    CODEARTS_STATE["welfare_items"] = [
        {"campaignId": 4, "type": "NEW_USER_REGISTER",
         "title": "新用户注册送 4000 积分", "benefitAmount": 4000,
         "benefitUnit": "CREDIT", "status": None, "claimable": True},
        {"campaignId": 1, "type": "USER_LOGIN",
         "title": "每日签到领积分", "benefitAmount": 1000,
         "benefitUnit": "CREDIT", "status": "CONFIRMED", "claimable": False},
    ]
    ledger = dict(ca_acc.meta.get("welfareLedger") or {})
    ledger["lastAttemptAt"] = 0
    codearts_mod._write_ledger(ca_acc, ledger)
    claims_before = CODEARTS_STATE["claims"]
    result = codearts_mod.checkin_for_account(ca_acc, trigger="manual")
    check("codearts checkin claims new user bonus once",
          result.get("ok") is True and result.get("claimed") == 1
          and result.get("verified") == 1
          and result.get("dailyDone") is True
          and "新用户注册积分 4000 积分" in str(result.get("message") or "")
          and CODEARTS_STATE["claims"] == claims_before + 1
          and (CODEARTS_STATE.get("last_claim") or {}).get("campaignId") == 4
          and CODEARTS_STATE["welfare_items"][0]["status"] == "CONFIRMED"
          and str(ca_acc.last_checkin or "").startswith(
              time.strftime("%Y-%m-%d")),
          json.dumps(result, ensure_ascii=False))

    ledger = dict(ca_acc.meta.get("welfareLedger") or {})
    ledger["lastAttemptAt"] = 0
    codearts_mod._write_ledger(ca_acc, ledger)
    claims_before = CODEARTS_STATE["claims"]
    result = codearts_mod.checkin_for_account(ca_acc, trigger="manual")
    check("codearts new user bonus is not claimed twice",
          result.get("ok") is True and result.get("claimed") == 0
          and result.get("dailyDone") is True
          and CODEARTS_STATE["claims"] == claims_before
          and str(ca_acc.last_checkin or "").startswith(
              time.strftime("%Y-%m-%d")),
          json.dumps(result, ensure_ascii=False))

    # ---- 32d. confirm 被上游拒绝时，claim 已到账仍算签到成功 ----
    CODEARTS_STATE["welfare_items"] = [
        {"campaignId": 1, "type": "USER_LOGIN",
         "title": "每日签到领积分", "benefitAmount": 1000,
         "benefitUnit": "CREDIT", "status": None, "claimable": True},
    ]
    CODEARTS_STATE["confirm_mode"] = "reject"
    ledger = dict(ca_acc.meta.get("welfareLedger") or {})
    ledger["lastAttemptAt"] = 0
    codearts_mod._write_ledger(ca_acc, ledger)
    claims_before = CODEARTS_STATE["claims"]
    confirms_before = CODEARTS_STATE["confirms"]
    result = codearts_mod.checkin_for_account(ca_acc, trigger="manual")
    check("codearts claim succeeds when confirm is rejected",
          result.get("ok") is True and result.get("claimed") == 1
          and result.get("dailyDone") is True
          and CODEARTS_STATE["claims"] == claims_before + 1
          and CODEARTS_STATE["confirms"] == confirms_before + 1
          and CODEARTS_STATE["welfare_items"][0]["status"] == "CLAIMED",
          json.dumps(result, ensure_ascii=False))
    CODEARTS_STATE["confirm_mode"] = ""

    ca_pre_cred = codearts_mod._credential_from(ca_acc)
    ca_pre_cred["expires_at"] = int(time.time() + 300)
    codearts_mod._apply_credential(ca_acc, ca_pre_cred)
    ca_refresh_before = CODEARTS_STATE["refreshes"]
    ca_fresh = codearts_mod.ensure_fresh(ca_acc)
    check("codearts refreshes 15 minutes before expiry",
          ca_fresh.get("ok") is True and ca_fresh.get("refreshed") is True
          and CODEARTS_STATE["refreshes"] == ca_refresh_before + 1
          and ca_acc.expires_at > time.time() + 1800,
          "refreshes=%d expires_in=%s" % (
              CODEARTS_STATE["refreshes"],
              int(ca_acc.expires_at - time.time())))

    CODEARTS_FAIL_MODE["mode"] = "401_once"
    CODEARTS_STATE["chat_calls"] = 0
    ca_refreshes = CODEARTS_STATE["refreshes"]
    ca_old_token = ca_acc.access_token
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/GLM-5.2",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("codearts 401 refreshes and retries same account",
          status == 200 and "你好，CodeArts" in body
          and CODEARTS_STATE["refreshes"] == ca_refreshes + 1
          and ca_acc.access_token != ca_old_token,
          "refreshes=%d %s" % (CODEARTS_STATE["refreshes"], body[:160]))
    CODEARTS_FAIL_MODE["mode"] = ""

    CODEARTS_FAIL_MODE["mode"] = "429"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/GLM-5.2",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("codearts 429 surfaced as 429",
          status == 429 and ca_acc.cooldown_until > time.time(), body[:200])
    ca_acc.clear_error()
    CODEARTS_FAIL_MODE["mode"] = ""

    CODEARTS_FAIL_MODE["mode"] = "quota_sse"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/GLM-5.2",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("codearts in-stream quota parked account",
          status == 403 and ca_acc.balance_until > 0, body[:200])
    ca_acc.balance_until = 0.0
    ca_acc.clear_error()
    CODEARTS_FAIL_MODE["mode"] = ""

    CODEARTS_FAIL_MODE["mode"] = "empty"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "codearts/GLM-5.2",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("codearts empty answer surfaced as failure",
          status == 502, body[:200])
    ca_acc.clear_error()
    CODEARTS_FAIL_MODE["mode"] = ""

    gate_account = accounts_mod.Account({
        "uid": "codearts-gate-test", "realm": "codearts",
        "accessToken": "x", "enabled": True})
    g1 = codearts_mod.acquire_session(gate_account, {})
    g2 = codearts_mod.acquire_session(gate_account, {})
    g3 = codearts_mod.acquire_session(gate_account, {})
    g4 = codearts_mod.acquire_session(gate_account, {})
    check("codearts session gate caps at 3",
          g1.get("acquired") and g2.get("acquired") and g3.get("acquired")
          and not g4.get("acquired"),
          "limit=%s" % g4.get("limit"))
    g1["release"]()
    g5 = codearts_mod.acquire_session(gate_account, {})
    check("codearts session gate releases slot", g5.get("acquired") is True)
    for permit in (g2, g3, g5):
        permit["release"]()

    status, body = request(base, "POST", "/accounts/login/start", {
        "realm": "codearts"}, panel_headers)
    ca_login = json.loads(body) if status == 200 else {}
    ca_auth_url = str(ca_login.get("authUrl") or "")
    check("codearts oauth start exposes PKCE SHA-256",
          status == 200 and ca_login.get("ok") is True
          and "/portal/authorize?" in ca_auth_url
          and "client_id=vscode-codebot" in ca_auth_url
          and "code_challenge_method=SHA-256" in ca_auth_url
          and "ticket_id=" in ca_auth_url
          and "auth_callback_url=" in ca_auth_url
          and ca_login.get("paste") is True,
          body[:240])
    ca_query = urllib.parse.parse_qs(
        urllib.parse.urlsplit(ca_auth_url).query)
    ca_redirect = (ca_query.get("auth_callback_url") or [""])[0]
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", ca_login.get("port"),
                                      timeout=5)
    conn.request("GET", "/oauth/callback?secret=probe&redirect="
                 + urllib.parse.quote("https://codearts.huaweicloud.com/done",
                                      safe=""))
    first = conn.getresponse()
    first_status = first.status
    first_location = first.getheader("Location")
    first.read()
    conn.close()
    check("codearts portal first callback redirects to trusted host",
          first_status == 307
          and first_location == "https://codearts.huaweicloud.com/done",
          "%s %s" % (first_status, first_location))
    conn = http.client.HTTPConnection("127.0.0.1", ca_login.get("port"),
                                      timeout=5)
    conn.request("GET", "/oauth/callback?secret=probe&redirect="
                 + urllib.parse.quote("https://evil.example/done", safe=""))
    bad = conn.getresponse()
    bad_status = bad.status
    bad.read()
    conn.close()
    check("codearts portal rejects untrusted redirect", bad_status == 400,
          str(bad_status))
    # 门户会用自己的 state 回传，不是本次发起的内部 state。
    status, body = request(base, "POST", "/accounts/login/submit", {
        "state": ca_login.get("state"),
        "callback": ca_redirect + "?code=login-code&state=portal-state"},
        panel_headers)
    ca_submit = json.loads(body) if status == 200 else {}
    check("codearts oauth paste callback exchanges code",
          status == 200 and ca_submit.get("ok") is True
          and ca_submit.get("message"), body[:240])
    status, body = request(base, "GET",
                           "/accounts/login/poll?state="
                           + str(ca_login.get("state")),
                           headers=panel_headers)
    ca_poll = json.loads(body) if status == 200 else {}
    check("codearts oauth poll reports success",
          status == 200 and ca_poll.get("status") == "ok", body[:200])
    ca_login_acc = ctx.pool.get("dom-1-user-login")
    check("codearts oauth account joined pool",
          ca_login_acc is not None
          and ca_login_acc.realm == "codearts"
          and codearts_mod._credential_from(ca_login_acc)["access_key_id"]
          == "AK-login",
          str(getattr(ca_login_acc, "uid", "")))
    check("codearts oauth keeps top-level refresh token",
          bool(codearts_mod._credential_from(ca_login_acc).get("refresh_token")),
          "refresh token missing")

    status, body = request(base, "POST", "/accounts/login/start", {
        "realm": "codearts"}, panel_headers)
    ca_login = json.loads(body) if status == 200 else {}
    conn = http.client.HTTPConnection("127.0.0.1", ca_login.get("port"),
                                      timeout=5)
    conn.request("GET", "/oauth/callback?code=login-code&state=portal-state")
    page = conn.getresponse()
    page_status = page.status
    page_body = page.read().decode("utf-8", "replace")
    conn.close()
    check("codearts loopback callback accepts portal state",
          page_status == 200 and "登录成功" in page_body, page_body[:200])
    status, body = request(base, "GET",
                           "/accounts/login/poll?state="
                           + str(ca_login.get("state")),
                           headers=panel_headers)
    ca_poll = json.loads(body) if status == 200 else {}
    check("codearts loopback callback completes login",
          status == 200 and ca_poll.get("status") == "ok", body[:200])

