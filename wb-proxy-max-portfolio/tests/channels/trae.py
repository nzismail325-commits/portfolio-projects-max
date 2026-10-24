# -*- coding: utf-8 -*-
"""Trae 渠道检查（从 test_smoke.py 拆出；入口仍是 tests/test_smoke.py）。"""
import json
import time

from tests.harness import check, request
from tests.upstreams.trae import (TRAE_STATE, TRAE_FAIL_MODE,
                                  TRAE_CHECKIN_MODE)


def run(env):
    ctx = env.ctx
    base = env.base
    key_headers = env.key_headers
    panel_headers = env.panel_headers
    # ---- 13. Trae 渠道：换发型对话链路（trae/ 前缀直达） ----
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3", "stream": True,
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae prefixed chat stream",
          status == 200 and "你好，Trae" in body and "[DONE]" in body
          and TRAE_STATE["exchanges"] >= 1, body[:200])
    trae_acc = ctx.pool.get("trae-uid-1")
    check("trae token exchanged and persisted",
          trae_acc is not None and trae_acc.access_token
          and trae_acc.refresh_token != "rt-seed", json.dumps({
              "token": bool(trae_acc.access_token),
              "rt": trae_acc.refresh_token[:12]}))
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    chat = json.loads(body) if status == 200 else {}
    message = ((chat.get("choices") or [{}])[0].get("message") or {})
    check("trae non-stream aggregated", status == 200
          and message.get("content") == "你好，Trae", body[:200])
    status, body = request(base, "POST", "/v1/responses", {
        "model": "trae/glm-5.3", "input": "hi"}, key_headers)
    response_obj = json.loads(body) if status == 200 else {}
    check("trae responses translated",
          status == 200 and response_obj.get("output_text") == "你好，Trae",
          body[:200])

    # ---- 14. Trae 治理：1005 停车 / 4008 限流 / 11102 模型负缓存 ----
    TRAE_FAIL_MODE["mode"] = "1005"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae 1005 surfaced as 402", status in (402, 503), body[:200])
    check("trae 1005 parked until 04:00", trae_acc.balance_until > 0
          and trae_acc.unavailable_reason().startswith("余额停车"),
          trae_acc.unavailable_reason())
    TRAE_FAIL_MODE["mode"] = ""
    # 不限量余额（-1 哨兵）也能抬出 402 停车
    trae_acc.credits = {"remain": -1, "unlimited": True}
    check("trae unlimited balance lifts park",
          trae_acc.revive_balance_cooldown() and trae_acc.balance_until == 0.0)

    TRAE_FAIL_MODE["mode"] = "4008"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae 4008 surfaced as 429", status == 429, body[:200])
    check("trae 4008 cooled account", trae_acc.cooldown_until > time.time(),
          str(trae_acc.cooldown_until))
    trae_acc.clear_error()

    TRAE_FAIL_MODE["mode"] = "11102"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae 11102 model-blocked only",
          trae_acc.ready() and "glm-5.3" in trae_acc.model_cooldowns,
          str(trae_acc.model_cooldowns))
    trae_acc.clear_error()

    TRAE_FAIL_MODE["mode"] = "4001_prompt"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae input too large surfaced as 413", status == 413, body[:200])
    check("trae input too large does not punish account",
          trae_acc.cooldown_until == 0 and trae_acc.fails == 0,
          trae_acc.unavailable_reason())
    trae_acc.clear_error()

    TRAE_FAIL_MODE["mode"] = "4001_model"
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "trae/glm-5.3",
        "messages": [{"role": "user", "content": "hi"}]}, key_headers)
    check("trae 4001 surfaced as 404", status == 404, body[:200])
    check("trae 4001 does not punish account",
          trae_acc.cooldown_until == 0 and trae_acc.fails == 0,
          trae_acc.unavailable_reason())
    trae_acc.clear_error()
    TRAE_FAIL_MODE["mode"] = ""

    # ---- 14b. Trae 流内 1005（未出内容）自动换号 ----
    ctx.pool.set_enabled("trae-uid-2", True)
    trae_acc.weight = 50
    TRAE_STATE["chat_calls"] = 0
    TRAE_FAIL_MODE["mode"] = "1005_once"
    try:
        status, body = request(base, "POST", "/v1/chat/completions", {
            "model": "trae/glm-5.3",
            "messages": [{"role": "user", "content": "hi"}]}, key_headers)
        check("trae in-stream 1005 rotates to next account",
              status == 200 and "你好，Trae" in body, body[:200])
        check("trae in-stream 1005 parks failed account",
              trae_acc.balance_until > 0, trae_acc.unavailable_reason())
    finally:
        TRAE_FAIL_MODE["mode"] = ""
        trae_acc.weight = 1
        trae_acc.balance_until = 0.0
        trae_acc.clear_error()
        ctx.pool.set_enabled("trae-uid-2", False)

    # ---- 15. Trae 出口隔离：裸模型不串到 Trae，trae 目录不进 intl ----
    status, body = request(base, "POST", "/v1/chat/completions", {
        "model": "glm-5.3", "messages": [{"role": "user", "content": "hi"}]},
        key_headers)
    check("bare model still goes to workbuddy",
          status == 200 and "你好，世界" in body, body[:150])
    status, body = request(base, "GET", "/v1/models?realm=trae", headers=key_headers)
    trae_models = json.loads(body) if status == 200 else {"data": []}
    trae_ids = [item["id"] for item in trae_models.get("data") or []]
    check("trae realm models listed", status == 200 and "glm-5.3" in trae_ids,
          body[:200])
    owner = next((item.get("owned_by") for item in trae_models.get("data") or []),
                 "")
    check("trae models owned_by trae", owner == "trae", str(owner))
    from integrations import trae as trae_mod
    check("trae catalog skips placeholders and switched-off entries",
          trae_mod._model_meta_from_item({
              "config_name": "placeholder", "display_config": {}}) is None
          and trae_mod._model_meta_from_item({
              "config_name": "off", "config_switch": False,
              "display_config": {"display_name": "Off"}}) is None
          and trae_mod._model_meta_from_item({
              "config_name": "ok",
              "display_config": {"display_name": "OK"}}) is not None,
          "catalog filter")

    # ---- 16. Trae 面板：账号块 / 额度（unavailable 语义）/ 签到任务 ----
    status, body = request(base, "GET", "/accounts?realm=trae", headers=panel_headers)
    trae_view = json.loads(body) if status == 200 else {"accounts": []}
    trae_row = next((a for a in trae_view.get("accounts") or []
                     if a["uid"] == "trae-uid-1"), {})
    check("panel trae account listed", bool(trae_row)
          and trae_row.get("channel") == "trae", body[:200])
    status, body = request(base, "GET", "/accounts/credits?realm=trae&refresh=1",
                           headers=panel_headers)
    credits_payload = json.loads(body) if status == 200 else {}
    check("trae credits fetched", status == 200
          and trae_acc.credits and trae_acc.credits.get("remain") == 38.0,
          json.dumps(trae_acc.credits, ensure_ascii=False)[:150] if trae_acc.credits else body[:150])
    result = ctx.scheduler.trigger_now("trae_checkin")
    check("trae scheduler trigger accepted", result.get("ok") is True,
          json.dumps(result))
    time.sleep(1.5)
    records = __import__("tasks.taskstore", fromlist=["x"]).list_logs(
        kind="trae_checkin", limit=10)
    check("trae checkin task persisted",
          any(row["kind"] == "trae_checkin" for row in records),
          json.dumps(records[:3], ensure_ascii=False)[:200])
    check("trae checkin marked on account",
          str(trae_acc.last_checkin or "").startswith(time.strftime("%Y-%m-%d")),
          str(trae_acc.last_checkin))

    # ---- 16b. Trae 签到台账：UTC+8 业务日 + 与上游状态互校 ----
    import calendar
    import integrations.trae as trae_mod

    ts = calendar.timegm((2026, 1, 1, 17, 0, 0))
    check("trae business day uses UTC+8",
          trae_mod._business_day(ts) == "2026-01-02",
          trae_mod._business_day(ts))
    try:
        TRAE_CHECKIN_MODE["mode"] = ""
        before = TRAE_STATE["checkin_claims"]
        result = trae_mod.checkin_for_account(trae_acc, trigger="manual")
        check("trae ledger confirmed by upstream status",
              result.get("ok") is True and result.get("already") is True
              and TRAE_STATE["checkin_claims"] == before,
              json.dumps(result, ensure_ascii=False))

        TRAE_CHECKIN_MODE["mode"] = "status_false"
        trae_mod._ledger_mark("trae-uid-1")
        trae_acc.last_checkin = None
        before = TRAE_STATE["checkin_claims"]
        result = trae_mod.checkin_for_account(trae_acc, trigger="manual")
        check("trae stale ledger cleared and re-claimed",
              result.get("ok") is False
              and TRAE_STATE["checkin_claims"] == before + 1
              and trae_mod.ledger_today("trae-uid-1") is None
              and trae_acc.last_checkin is None,
              json.dumps(result, ensure_ascii=False))

        TRAE_CHECKIN_MODE["mode"] = "already_false"
        before = TRAE_STATE["checkin_claims"]
        result = trae_mod.checkin_for_account(trae_acc, trigger="manual")
        check("trae already-message not trusted when status disagrees",
              result.get("ok") is False
              and TRAE_STATE["checkin_claims"] == before
              and trae_mod.ledger_today("trae-uid-1") is None
              and trae_acc.last_checkin is None,
              json.dumps(result, ensure_ascii=False))

        TRAE_CHECKIN_MODE["mode"] = "1001"
        before = TRAE_STATE["checkin_claims"]
        result = trae_mod.checkin_for_account(trae_acc, trigger="manual")
        check("trae unavailable service does not mark checkin",
              result.get("ok") is True and result.get("unavailable") is True
              and TRAE_STATE["checkin_claims"] == before
              and trae_acc.last_checkin is None,
              json.dumps(result, ensure_ascii=False))
    finally:
        TRAE_CHECKIN_MODE["mode"] = ""
        trae_mod._ledger_clear("trae-uid-1")

    # ---- 17. 面板渠道清单下发 Trae（页签/按钮唯一依据） ----
    status, body = request(base, "GET", "/channels", headers=panel_headers)
    channels_payload = json.loads(body) if status == 200 else {}
    trae_channel = next((c for c in channels_payload.get("channels") or []
                         if c.get("id") == "trae"), None)
    check("panel channels include trae",
          bool(trae_channel) and "checkin" in (trae_channel.get("capabilities") or []),
          body[:200])
    trae_realm = next((r for r in channels_payload.get("realms") or []
                       if r.get("id") == "trae"), {})
    check("panel realms carry channel marker",
          trae_realm.get("channel") == "trae", json.dumps(trae_realm)[:150])

