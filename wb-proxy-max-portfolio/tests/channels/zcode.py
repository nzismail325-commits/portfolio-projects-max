# -*- coding: utf-8 -*-
"""Zcode 渠道检查（从 test_smoke.py 拆出；入口仍是 tests/test_smoke.py）。"""
import json
import time

from tests.harness import check, request
from tests.upstreams.zcode import ZCODE_STATE, ZCODE_FAIL_MODE


def run(env):
    ctx = env.ctx
    base = env.base
    key_headers = env.key_headers
    panel_headers = env.panel_headers
    # ---- 24. ZCode 渠道：start-plan 对话与官方 system 前缀 ----
    from integrations import zcode as zcode_mod
    zcode_acc1 = ctx.pool.get("zcode-uid-1")
    zcode_acc2 = ctx.pool.get("zcode-uid-2")
    zcode_acc3 = ctx.pool.get("zcode-uid-3")
    ctx.pool.set_enabled("zcode-uid-2", False)
    ctx.pool.set_enabled("zcode-uid-3", False)
    ZCODE_FAIL_MODE["mode"] = ""
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode prefixed chat stream",
          status == 200 and "你好，ZCode" in body and "[DONE]" in body,
          body[:200])
    zcode_last = ZCODE_STATE.get("last") or {}
    check("zcode start-plan route selected",
          "/api/v1/zcode-plan/anthropic/" in zcode_last.get("path", ""),
          zcode_last.get("path", ""))
    zcode_system = (zcode_last.get("payload") or {}).get("system") or ""
    check("zcode official system prefix injected",
          str(zcode_system).startswith(
              "You are ZCode, an interactive coding agent"),
          str(zcode_system)[:160])
    try:
        zcode_meta = json.loads((zcode_last.get("payload") or {}).get(
            "metadata", {}).get("user_id") or "{}")
    except Exception:
        zcode_meta = {}
    check("zcode metadata device/session",
          zcode_meta.get("device_id") == "dev-zcode-1"
          and bool(zcode_meta.get("session_id")),
          json.dumps(zcode_meta, ensure_ascii=False))
    check("zcode start-plan bearer header",
          (zcode_last.get("headers") or {}).get("authorization")
          == "Bearer " + zcode_acc1.access_token,
          str((zcode_last.get("headers") or {}).get("authorization", ""))[:40])
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    zchat = json.loads(body) if status == 200 else {}
    zmessage = ((zchat.get("choices") or [{}])[0].get("message") or {})
    check("zcode non-stream aggregated",
          status == 200 and zmessage.get("content") == "你好，ZCode！", body[:200])
    zusage = zchat.get("usage") or {}
    check("zcode usage folds cache tokens",
          zusage.get("prompt_tokens") == 7
          and zusage.get("completion_tokens") == 6
          and zusage.get("total_tokens") == 13
          and (zusage.get("prompt_tokens_details") or {}).get("cached_tokens") == 2,
          json.dumps(zusage, ensure_ascii=False)[:200])
    status, body = request(base, "POST", "/v1/responses", {
        "model": "zcode/GLM-5.3", "input": "hi"}, key_headers)
    zresp = json.loads(body) if status == 200 else {}
    check("zcode responses translated",
          status == 200 and zresp.get("output_text") == "你好，ZCode！",
          body[:200])

    # ---- 25. ZCode 工具调用翻译 ----
    ZCODE_FAIL_MODE["mode"] = "tool"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "search"}],
        "tools": [{"type": "function", "function": {
            "name": "web_search", "parameters": {"type": "object",
                                                 "properties": {}}}}]},
        key_headers)
    tool_chat = json.loads(body) if status == 200 else {}
    tool_msg = ((tool_chat.get("choices") or [{}])[0].get("message") or {})
    tool_calls = tool_msg.get("tool_calls") or []
    tool_args = {}
    try:
        tool_args = json.loads((tool_calls[0].get("function") or {}).get(
            "arguments") or "{}") if tool_calls else {}
    except Exception:
        tool_args = {}
    check("zcode tool calls translated",
          status == 200 and bool(tool_calls)
          and tool_calls[0].get("function", {}).get("name") == "web_search"
          and tool_args.get("query") == "zcode", body[:240])
    ZCODE_FAIL_MODE["mode"] = ""

    # ---- 26. ZCode coding-plan 选路与 402 回退 ----
    ctx.pool.set_enabled("zcode-uid-1", False)
    ctx.pool.set_enabled("zcode-uid-2", True)
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    zcode_last = ZCODE_STATE.get("last") or {}
    check("zcode coding-plan route selected",
          status == 200 and "/api/anthropic/" in zcode_last.get("path", ""),
          zcode_last.get("path", ""))
    check("zcode coding-plan key header",
          (zcode_last.get("headers") or {}).get("x-api-key")
          == "0123456789abcdef0123456789abcdef.test-secret",
          str((zcode_last.get("headers") or {}).get("x-api-key", ""))[:20])
    ZCODE_FAIL_MODE["mode"] = "coding_402"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    zcode_last = ZCODE_STATE.get("last") or {}
    check("zcode coding 402 falls back to start-plan",
          status == 200 and "ZCode" in body
          and "/api/v1/zcode-plan/anthropic/" in zcode_last.get("path", ""),
          body[:200])
    check("zcode fallback does not park account",
          zcode_acc2.balance_until == 0, zcode_acc2.unavailable_reason())
    ZCODE_FAIL_MODE["mode"] = ""

    # ---- 27. ZCode 额度耗尽治理（plan-only 账号） ----
    ctx.pool.set_enabled("zcode-uid-2", False)
    ctx.pool.set_enabled("zcode-uid-3", True)
    ZCODE_FAIL_MODE["mode"] = "plan_402"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode 402 surfaced", status == 402, body[:200])
    check("zcode 402 parked until 04:00",
          zcode_acc3.balance_until > 0
          and zcode_acc3.unavailable_reason().startswith("余额停车"),
          zcode_acc3.unavailable_reason())
    zcode_acc3.balance_until = 0.0
    zcode_acc3.clear_error()
    ZCODE_FAIL_MODE["mode"] = ""
    ctx.pool.set_enabled("zcode-uid-3", False)
    ctx.pool.set_enabled("zcode-uid-1", True)

    # ---- 28. ZCode 限流 / 人机校验 / 空流治理 ----
    ZCODE_FAIL_MODE["mode"] = "429"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode 429 surfaced", status == 429, body[:200])
    check("zcode 429 cooled account", zcode_acc1.cooldown_until > time.time(),
          str(zcode_acc1.cooldown_until))
    zcode_acc1.clear_error()

    ZCODE_FAIL_MODE["mode"] = "3007"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode captcha surfaced as 502",
          status == 502 and "人机校验" in body, body[:200])
    check("zcode captcha does not kill token",
          zcode_acc1.token_expired is False and zcode_acc1.cooldown_until > 0,
          zcode_acc1.unavailable_reason())
    zcode_acc1.clear_error()

    ZCODE_FAIL_MODE["mode"] = "4001"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode 4001 surfaced as 502", status == 502, body[:200])
    check("zcode 4001 does not punish account",
          zcode_acc1.cooldown_until == 0
          and "4001" in str(zcode_acc1.last_error),
          zcode_acc1.unavailable_reason())
    zcode_acc1.clear_error()

    ZCODE_FAIL_MODE["mode"] = "empty"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "zcode/GLM-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("zcode empty stream surfaced as 502",
          status == 502 and "没有任何可用内容" in body, body[:200])
    zcode_acc1.clear_error()
    zcode_acc1.fails = 0
    zcode_acc1.degrade_count = 0
    ZCODE_FAIL_MODE["mode"] = ""

    # ---- 28b. ZCode 未出内容即失败（流内 402 / 空流）自动换号 ----
    ctx.pool.set_enabled("zcode-uid-3", True)
    zcode_acc1.weight = 50
    try:
        ZCODE_FAIL_MODE["mode"] = "quota_sse"
        ZCODE_FAIL_MODE["account"] = "zcode-uid-1"
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "zcode/GLM-5.3",
            "messages": [{"role": "user", "content": "hi"}]}, key_headers)
        check("zcode in-stream quota rotates to next account",
              status == 200 and "你好，ZCode" in body, body[:200])
        check("zcode in-stream quota parks failed account",
              zcode_acc1.balance_until > time.time(),
              zcode_acc1.unavailable_reason())
        zcode_acc1.balance_until = 0.0
        zcode_acc1.clear_error()

        ZCODE_FAIL_MODE["mode"] = "empty"
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "zcode/GLM-5.3",
            "messages": [{"role": "user", "content": "hi"}]}, key_headers)
        check("zcode empty stream rotates to next account",
              status == 200 and "你好，ZCode" in body, body[:200])
        check("zcode empty stream recorded on failed account",
              "空流" in str(zcode_acc1.last_error), zcode_acc1.last_error)
    finally:
        ZCODE_FAIL_MODE["mode"] = ""
        ZCODE_FAIL_MODE["account"] = ""
        zcode_acc1.weight = 1
        zcode_acc1.fails = 0
        zcode_acc1.clear_error()
        ctx.pool.set_enabled("zcode-uid-3", False)

    # ---- 29. ZCode 目录 / 额度 / 出口隔离 ----
    status, body = request(base, "GET", "/v1/models?realm=zcode",
                           headers=key_headers)
    zmodels = json.loads(body) if status == 200 else {"data": []}
    zids = [item["id"] for item in zmodels.get("data") or []]
    check("zcode realm models listed",
          status == 200 and "GLM-5.3" in zids and "GLM-5.3-Flash" in zids
          and "GLM-5.2" in zids, body[:200])
    zsample = next((item for item in zmodels.get("data") or []
                    if item["id"] == "GLM-5.3"), {})
    check("zcode models owned_by zcode",
          zsample.get("owned_by") == "zcode", str(zsample.get("owned_by")))
    check("zcode models carry limits",
          zsample.get("context_length") == 1000000
          and zsample.get("max_output_tokens") == 128000,
          json.dumps(zsample, ensure_ascii=False)[:200])
    ctx.pool.set_enabled("zcode-uid-2", True)
    status, body = request(base, "GET", "/accounts/credits?realm=zcode&refresh=1",
                           headers=panel_headers)
    check("zcode credits merged (jwt + coding plan)",
          status == 200 and zcode_acc2.credits
          and zcode_acc2.credits.get("remain") == 376.0,
          json.dumps(zcode_acc2.credits, ensure_ascii=False)[:240]
          if zcode_acc2.credits else body[:200])
    check("zcode credit packages listed",
          bool(zcode_acc2.credits and len(zcode_acc2.credits.get("packages") or []) >= 3),
          json.dumps((zcode_acc2.credits or {}).get("packages") or [],
                     ensure_ascii=False)[:200])
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
        key_headers)
    check("bare glm-5.3 still goes to workbuddy after zcode",
          status == 200 and "你好，世界" in body, body[:150])
    ctx.pool.set_enabled("zcode-uid-2", False)

    # ---- 30. ZCode 额度查询退避（激活延迟 401） ----
    # 阶梯内恢复：首次 401、第二次即 200（新账号服务端激活延迟误报）
    ZCODE_FAIL_MODE["balance"] = "401_ladder"
    ZCODE_STATE["balance_calls"] = 0
    zcode_mod._CREDITS_CACHE.clear()
    ladder_result = zcode_mod.get_credits(zcode_acc1, force=True)
    check("zcode credits recover after transient 401",
          ladder_result.get("ok") is True
          and ladder_result.get("credits") == 276.0,
          json.dumps(ladder_result, ensure_ascii=False)[:200])
    # 终判补试：阶梯全程 401 后，再等 1.5s 补试一次成功即采用
    ZCODE_FAIL_MODE["balance"] = "401_final"
    ZCODE_STATE["balance_calls"] = 0
    zcode_mod._CREDITS_CACHE.clear()
    final_result = zcode_mod.get_credits(zcode_acc1, force=True)
    check("zcode credits recover on final-judgment retry",
          final_result.get("ok") is True
          and final_result.get("credits") == 276.0,
          json.dumps(final_result, ensure_ascii=False)[:200])
    # 补试仍 401 才终判凭证失效，不提前误停
    ZCODE_FAIL_MODE["balance"] = "401_always"
    ZCODE_STATE["balance_calls"] = 0
    zcode_mod._CREDITS_CACHE.clear()
    dead_result = zcode_mod.get_credits(zcode_acc1, force=True)
    check("zcode credits dead only after full retry ladder",
          not dead_result.get("ok")
          and dead_result.get("authError") is True,
          json.dumps(dead_result, ensure_ascii=False)[:200])
    ZCODE_FAIL_MODE["balance"] = ""
    ZCODE_STATE["balance_calls"] = 0
    zcode_mod._CREDITS_CACHE.clear()

    # ---- 31. ZCode 本机扫描 / 导入（enc:v1 解密） ----
    status, body = request(base, "GET", "/accounts/import-desktop",
                           headers=panel_headers)
    zcandidates = [item for item in (json.loads(body) if status == 200 else {}).get(
        "candidates") or [] if item.get("realm") == "zcode"]
    check("zcode desktop candidates listed",
          status == 200 and len(zcandidates) >= 2
          and any(item.get("path") == "credentials.json" for item in zcandidates)
          and any(item.get("path", "").startswith("account-profiles/")
                  for item in zcandidates), body[:240])
    live_candidate = next((item for item in zcandidates
                           if item.get("path") == "credentials.json"), {})
    check("zcode live candidate decoded",
          live_candidate.get("usable") is True
          and live_candidate.get("uid") == "zcode-live-1",
          json.dumps(live_candidate, ensure_ascii=False)[:200])
    status, body = request(base, "POST", "/accounts/import-desktop", {
        "import": True, "realm": "zcode", "path": "credentials.json"},
        panel_headers)
    live_account = ctx.pool.get("zcode-live-1")
    check("zcode live credential imported",
          status == 200 and live_account is not None
          and live_account.realm == "zcode"
          and (live_account.meta or {}).get("deviceMid") == "live-mid-1"
          and live_account.refresh_token.endswith(".live-secret"),
          body[:200])
    status, body = request(base, "POST", "/accounts/import-desktop", {
        "import": True, "realm": "zcode",
        "path": "account-profiles/p1.json"}, panel_headers)
    profile_account = ctx.pool.get("zcode-profile-1")
    check("zcode profile credential imported",
          status == 200 and profile_account is not None
          and profile_account.refresh_token.endswith(".profile-secret")
          and bool((profile_account.meta or {}).get("deviceMid"))
          and (profile_account.meta or {}).get("deviceMid") != "live-mid-1",
          body[:200])

    # ---- 32. ZCode OAuth（轮询入池 + 深链粘贴兜底） ----
    status, body = request(base, "POST", "/accounts/login/start",
                           {"realm": "zcode"}, panel_headers)
    zlogin = json.loads(body) if status == 200 else {}
    check("zcode oauth start",
          status == 200 and zlogin.get("ok") is True
          and "redirect_uri=" in str(zlogin.get("authUrl") or "")
          and str(zlogin.get("state") or "").startswith("flow-z"),
          body[:240])
    status, body = request(base, "GET", "/accounts/login/poll?state=%s"
                           % (zlogin.get("state") or ""), headers=panel_headers)
    zpoll = json.loads(body) if status == 200 else {}
    check("zcode oauth poll admitted",
          status == 200 and zpoll.get("status") == "ok"
          and ctx.pool.get("zcode-oauth-1") is not None, body[:240])
    status, body = request(base, "POST", "/accounts/login/start",
                           {"realm": "zcode"}, panel_headers)
    zlogin2 = json.loads(body) if status == 200 else {}
    status, body = request(base, "POST", "/accounts/login/submit", {
        "state": zlogin2.get("state") or "",
        "callback": "zcode://zai-auth/callback?code=abc&state=xyz"},
        panel_headers)
    zsubmit = json.loads(body) if status == 200 else {}
    check("zcode oauth paste callback admitted",
          status == 200 and zsubmit.get("ok") is True
          and ctx.pool.get("zcode-oauth-2") is not None, body[:240])
    zoauth = ctx.pool.get("zcode-oauth-1")
    check("zcode oauth account realm",
          getattr(zoauth, "realm", "") == "zcode",
          str(getattr(zoauth, "realm", "")))
    zoauth2 = ctx.pool.get("zcode-oauth-2")
    if zoauth2 is not None:
        zcode_mod._run_activation(ctx, zoauth2, "zai", "at-oauth-2")
    check("zcode oauth activation resolves coding-plan key",
          zoauth2 is not None
          and zoauth2.refresh_token == "key123.secret456"
          and (zoauth2.meta or {}).get("codingPlanResolved") is True,
          str(getattr(zoauth2, "refresh_token", ""))[:24])

