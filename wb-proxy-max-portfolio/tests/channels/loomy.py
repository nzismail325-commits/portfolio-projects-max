# -*- coding: utf-8 -*-
"""Loomy 渠道检查（从 test_smoke.py 拆出；入口仍是 tests/test_smoke.py）。"""
import json
import time

from tests.harness import check, request
from tests.upstreams.loomy import LOOMY_STATE, LOOMY_FAIL_MODE
from auth import accounts as accounts_mod


def run(env):
    ctx = env.ctx
    base = env.base
    key_headers = env.key_headers
    panel_headers = env.panel_headers
    # ---- 32d. Loomy：短信登录、双头转发、双钱包、每日刷新 ----
    from integrations import loomy as loomy_mod
    check("loomy signer path escaping",
          loomy_mod.build_escaped_path("/a b/中文/")
          == "/a%20b/%E4%B8%AD%E6%96%87",
          loomy_mod.build_escaped_path("/a b/中文/"))
    check("loomy catalog accepts bare array",
          [entry["id"] for entry in loomy_mod._parse_models(
              [{"id": "bare-model", "name": "Bare"}])] == ["bare-model"],
          json.dumps(loomy_mod._parse_models(
              [{"id": "bare-model", "name": "Bare"}]), ensure_ascii=False)[:200])
    check("loomy rate suffix forms",
          loomy_mod._split_rate_suffix("Spark X x3.0")
          == ("Spark X", "x3.0")
          and loomy_mod._split_rate_suffix("Spark X (x3.0)")
          == ("Spark X", "x3.0"),
          "%s / %s" % (loomy_mod._split_rate_suffix("Spark X x3.0"),
                       loomy_mod._split_rate_suffix("Spark X (x3.0)")))
    caps_model = loomy_mod._map_entry({
        "id": "caps-model", "type": "chat", "protocol": "openai_chat",
        "capabilities": {"reasoning": True, "vision": True,
                         "function_calling": True,
                         "input_modalities": ["text"],
                         "output_modalities": ["text"]}})
    top_model = loomy_mod._map_entry({
        "id": "top-model", "reasoning": True, "supports_video_in": True,
        "tool_call": True})
    image_model = loomy_mod._map_entry({
        "id": "img", "type": "image",
        "capabilities": {"output_modalities": ["image"]}})
    deduped = loomy_mod._parse_models([{"id": "dup"}, {"id": "dup"}])
    check("loomy catalog capabilities and image filtering",
          caps_model["meta"]["supportsReasoning"] is True
          and caps_model["meta"]["supportsImages"] is True
          and caps_model["meta"]["supportsToolCall"] is True
          and top_model["meta"]["supportsReasoning"] is True
          and top_model["meta"]["supportsImages"] is True
          and top_model["meta"]["supportsToolCall"] is True
          and image_model is None and len(deduped) == 1,
          json.dumps([caps_model, top_model, image_model, deduped],
                     ensure_ascii=False)[:360])

    status, body = request(base, "POST", "/accounts/login/start", {
        "realm": "loomy"}, panel_headers)
    llogin = json.loads(body) if status == 200 else {}
    lform = llogin.get("form") or {}
    check("loomy sms login form declared",
          status == 200 and llogin.get("ok") is True
          and [field.get("key") for field in lform.get("fields") or []]
          == ["phone", "code"]
          and lform.get("sendAction") == "send_code"
          and lform.get("submitAction") == "submit"
          and not llogin.get("authUrl"), body[:260])
    status, body = request(base, "POST", "/accounts/login/action", {
        "state": llogin.get("state"), "action": "submit",
        "values": {"phone": "13812345678", "code": "123456"}},
        panel_headers)
    lpre = json.loads(body) if status == 200 else {}
    check("loomy submit before sending code rejected",
          status == 200 and lpre.get("ok") is False
          and "发送验证码" in str(lpre.get("message") or ""), body[:200])
    status, body = request(base, "POST", "/accounts/login/action", {
        "state": llogin.get("state"), "action": "send_code",
        "values": {"phone": "13812345678"}}, panel_headers)
    lsent = json.loads(body) if status == 200 else {}
    check("loomy sms code sent with hmac signature",
          status == 200 and lsent.get("ok") is True
          and LOOMY_STATE["signatures"] == 1
          and LOOMY_STATE["bad_signatures"] == 0
          and LOOMY_STATE["send_codes"] == 1,
          "%s sigs=%d bad=%d" % (
              body[:160], LOOMY_STATE["signatures"],
              LOOMY_STATE["bad_signatures"]))
    status, body = request(base, "POST", "/accounts/login/action", {
        "state": llogin.get("state"), "action": "submit",
        "values": {"phone": "13812345678", "code": "123456"}},
        panel_headers)
    llogin_result = json.loads(body) if status == 200 else {}
    loomy_acc = ctx.pool.get("loomy-user-1")
    check("loomy sms login joins pool",
          status == 200 and llogin_result.get("ok") is True
          and llogin_result.get("status") == "ok"
          and loomy_acc is not None and loomy_acc.realm == "loomy"
          and loomy_acc.access_token == LOOMY_STATE["session"]
          and (loomy_acc.meta or {}).get("phoneTail") == "138****5678"
          and (loomy_acc.meta or {}).get("loginAccount") == "13812345678"
          and loomy_acc.expires_at > time.time() + 13 * 86400,
          body[:240])
    status, body = request(base, "GET", "/accounts?realm=loomy",
                           headers=panel_headers)
    loomy_view = json.loads(body) if status == 200 else {"accounts": []}
    loomy_row = next((a for a in loomy_view.get("accounts") or []
                      if a.get("uid") == (loomy_acc.uid if loomy_acc else "")), {})
    check("panel loomy login account stays copyable",
          status == 200 and loomy_row.get("loginAccount") == "13812345678",
          body[:200])
    check("loomy login refreshes daily gift",
          LOOMY_STATE["first_login_calls"] == 1
          and str(loomy_acc.last_checkin or "")[:10]
          == time.strftime("%Y-%m-%d"),
          "first_login=%d last=%s" % (
              LOOMY_STATE["first_login_calls"],
              getattr(loomy_acc, "last_checkin", "")))

    status, body = request(base, "GET", "/v1/models?realm=loomy",
                           headers=key_headers)
    loomy_models = json.loads(body) if status == 200 else {"data": []}
    loomy_items = loomy_models.get("data") or []
    loomy_ids = [item.get("id") for item in loomy_items]
    spark = next((item for item in loomy_items
                  if item.get("id") == "spark-x"), {})
    deepseek = next((item for item in loomy_items
                     if item.get("id") == "deepseek-v4"), {})
    check("loomy catalog from upstream only",
          status == 200 and loomy_ids == ["spark-x", "deepseek-v4"]
          and spark.get("credits") == "x3.0"
          and spark.get("name") == "Spark X"
          and spark.get("supports_reasoning") is True
          and spark.get("context_length") == 262144
          and spark.get("max_output_tokens") == 8192
          and deepseek.get("context_length") == 128000
          and deepseek.get("max_output_tokens") == 8192
          and deepseek.get("supports_images") is True
          and deepseek.get("supports_tool_calls") is True
          and deepseek.get("supports_reasoning") is True
          and all(item.get("owned_by") == "loomy" for item in loomy_items),
          body[:340])
    from intel import catalog as catalog_mod
    check("loomy catalog source reported",
          (catalog_mod.models_source().get("loomy") or {}).get("source")
          == "live"
          and (catalog_mod.models_source().get("loomy") or {}).get("count") == 2,
          json.dumps(catalog_mod.models_source().get("loomy"),
                     ensure_ascii=False))

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    lheaders = LOOMY_STATE.get("last_headers") or {}
    check("loomy chat uses token+bearer dual headers",
          status == 200 and "你好，Loomy" in body
          and lheaders.get("token") == LOOMY_STATE["session"]
          and lheaders.get("authorization")
          == "Bearer " + LOOMY_STATE["session"]
          and (LOOMY_STATE.get("last_payload") or {}).get("model")
          == "spark-x",
          body[:200])
    tracking = LOOMY_STATE.get("last_headers") or {}
    check("loomy chat carries client tracing headers",
          bool(tracking.get("traceparent"))
          and bool(tracking.get("loomy-version"))
          and tracking.get("x-loomy-request-purpose") == "chat.message"
          and tracking.get("invokeorigin") == "user"
          and all(bool(tracking.get(key))
                  for key in ("chatid", "msgid", "turnid")),
          json.dumps({key: tracking.get(key) for key in
                      ("traceparent", "loomy-version", "chatid", "msgid",
                       "turnid", "x-loomy-request-purpose", "invokeorigin")},
                     ensure_ascii=False)[:320])

    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/deepseek-v4",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,AAAA"}}]}]},
        key_headers)
    lchat = json.loads(body) if status == 200 else {}
    lmessage = ((lchat.get("choices") or [{}])[0].get("message") or {})
    lparts = []
    for message in (LOOMY_STATE.get("last_payload") or {}).get("messages") or []:
        if isinstance(message, dict) and isinstance(message.get("content"), list):
            lparts.extend(message["content"])
    check("loomy images pass through as image_url",
          status == 200 and lmessage.get("content") == "你好，Loomy"
          and any(isinstance(part, dict)
                  and part.get("type") == "image_url"
                  and isinstance(part.get("image_url"), dict)
                  and part["image_url"].get("url")
                  == "data:image/png;base64,AAAA"
                  for part in lparts)
          and not any("<image_base64>" in json.dumps(part, ensure_ascii=False)
                      for part in lparts),
          body[:240])

    status, body = request(
        base, "GET", "/accounts/credits?realm=loomy&refresh=1",
        headers=panel_headers)
    lcredit_payload = json.loads(body) if status == 200 else {}
    lview = next((item for item in lcredit_payload.get("accounts") or []
                  if item.get("uid") == "loomy-user-1"), {})
    lcredits = lview.get("credits") or {}
    lwallets = lcredits.get("wallets") or []
    lpermanent = next((item for item in lwallets
                       if item.get("type") == "permanent_points"), {})
    ldaily = next((item for item in lwallets
                   if item.get("type") == "daily_points"), {})
    lpkg_names = [item.get("name") for item in lcredits.get("packages") or []]
    check("loomy balance keeps two wallets",
          status == 200 and lcredits.get("remain") == 7000
          and lpermanent.get("balance") == 2000
          and ldaily.get("balance") == 5000
          and ldaily.get("remaining") == 3000
          and ldaily.get("limit") == 5000
          and "永久积分" in lpkg_names and "每日赠送积分" in lpkg_names,
          json.dumps(lcredits, ensure_ascii=False)[:320])
    points_headers = LOOMY_STATE.get("last_headers") or {}
    check("loomy points uses token header only",
          points_headers.get("token") == LOOMY_STATE["session"]
          and "authorization" not in points_headers,
          json.dumps({key: points_headers.get(key) for key in
                      ("token", "authorization")}, ensure_ascii=False)[:200])

    loomy_acc.last_checkin = None
    lfirst_before = LOOMY_STATE["first_login_calls"]
    status, body = request(base, "POST", "/accounts/action", {
        "uid": "loomy-user-1", "action": "checkin"}, panel_headers)
    ldaily_res = json.loads(body) if status == 200 else {}
    check("loomy daily refresh via first-login",
          status == 200 and ldaily_res.get("ok") is True
          and LOOMY_STATE["first_login_calls"] == lfirst_before + 1
          and str(loomy_acc.last_checkin or "")[:10]
          == time.strftime("%Y-%m-%d"),
          body[:200])
    check("loomy scheduler task registered",
          "loomy_daily_points" in ctx.scheduler.task_ids(),
          json.dumps(ctx.scheduler.task_ids(), ensure_ascii=False)[:240])

    # 当天已刷新过（lastCheckin 是今天）也不能被本地日期闸门跳过；
    # first-login 幂等，重跑是安全的，可覆盖非 UTC+8 服务器的跨日场景。
    loomy_acc.last_checkin = time.strftime("%Y-%m-%d 07:00:00")
    lfirst_before = LOOMY_STATE["first_login_calls"]
    result = ctx.scheduler.trigger_now("loomy_daily_points")
    deadline = time.time() + 8
    while time.time() < deadline and \
            LOOMY_STATE["first_login_calls"] == lfirst_before:
        time.sleep(0.2)
    check("loomy scheduler re-runs first-login despite same-day checkin",
          result.get("ok") is True
          and LOOMY_STATE["first_login_calls"] == lfirst_before + 1,
          json.dumps(result, ensure_ascii=False)
          + " first_login=%d" % LOOMY_STATE["first_login_calls"])

    loomy_expired = accounts_mod.Account({
        "uid": "loomy-expired", "realm": "loomy",
        "accessToken": "old-session",
        "expiresAt": int(time.time()) - 10, "enabled": True})
    check("loomy no refresh after 14 days",
          loomy_mod._refresh_account(loomy_expired) is False
          and "短信登录" in str(loomy_expired.last_error),
          str(loomy_expired.last_error))

    def loomy_relogin():
        status, body = request(base, "POST", "/accounts/login/start", {
            "realm": "loomy"}, panel_headers)
        info = json.loads(body) if status == 200 else {}
        request(base, "POST", "/accounts/login/action", {
            "state": info.get("state"), "action": "send_code",
            "values": {"phone": "13812345678"}}, panel_headers)
        status, body = request(base, "POST", "/accounts/login/action", {
            "state": info.get("state"), "action": "submit",
            "values": {"phone": "13812345678", "code": "123456"}},
            panel_headers)
        return json.loads(body) if status == 200 else {}

    LOOMY_FAIL_MODE["mode"] = "401"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("loomy http 401 marks session expired",
          status == 401 and loomy_acc.token_expired is True, body[:240])
    lrelogin = loomy_relogin()
    check("loomy relogin clears expiry",
          lrelogin.get("ok") is True and loomy_acc.token_expired is False
          and loomy_acc.access_token == LOOMY_STATE["session"],
          json.dumps(lrelogin, ensure_ascii=False)[:200])
    LOOMY_FAIL_MODE["mode"] = "auth_sse"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("loomy in-stream auth code surfaced as 401",
          status == 401 and loomy_acc.token_expired is True, body[:240])
    loomy_relogin()
    LOOMY_FAIL_MODE["mode"] = "auth_json"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("loomy json auth marks session expired",
          status == 401 and loomy_acc.token_expired is True, body[:240])
    loomy_relogin()
    LOOMY_FAIL_MODE["mode"] = "429"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("loomy 429 surfaced as 429",
          status == 429 and loomy_acc.cooldown_until > time.time(), body[:200])
    loomy_acc.clear_error()
    LOOMY_FAIL_MODE["mode"] = ""
    LOOMY_FAIL_MODE["mode"] = "empty"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "loomy/spark-x",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("loomy empty answer surfaced as failure",
          status == 502, body[:200])
    loomy_acc.clear_error()
    LOOMY_FAIL_MODE["mode"] = ""

