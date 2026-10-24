# -*- coding: utf-8 -*-
"""Qoder 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import json
import time
from http.server import BaseHTTPRequestHandler


QODER_FAIL_MODE = {"mode": ""}
QODER_CAMPAIGN_MODE = {"mode": ""}
QODER_STATE = {"claims": 0, "chat_calls": 0}


def _campaign_list():
    mode = QODER_CAMPAIGN_MODE["mode"]
    now = int(time.time())
    if mode == "empty":
        return []
    if mode == "history_claimed":
        return [{"campaignId": "old", "actionType": "CLAIM_BENEFIT",
                 "claimStatus": "CLAIMED",
                 "startAt": now - 3 * 86400, "endAt": now - 2 * 86400,
                 "benefit": {"kind": "CREDITS", "amount": 100}}]
    if mode == "active_claimed":
        return [{"campaignId": "c1", "actionType": "CLAIM_BENEFIT",
                 "claimStatus": "CLAIMED",
                 "startAt": now - 3600, "endAt": now + 3600,
                 "benefit": {"kind": "CREDITS", "amount": 100}}]
    if mode == "expired_claimable":
        return [{"campaignId": "c1", "actionType": "CLAIM_BENEFIT",
                 "claimStatus": "CLAIMABLE",
                 "startAt": now - 7200, "endAt": now - 3600,
                 "benefit": {"kind": "CREDITS", "amount": 100}}]
    return [{"campaignId": "c1", "actionType": "CLAIM_BENEFIT",
             "claimStatus": "CLAIMABLE",
             "startAt": now - 3600, "endAt": now + 3600,
             "benefit": {"kind": "CREDITS", "amount": 100}}]

class FakeQoderUpstream(BaseHTTPRequestHandler):
    """Qoder 假上游：签名后的 SSE 信封 / 额度 / 每日领取。"""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _envelope(self, body, status="OK"):
        return {"statusCode": status, "headers": {},
                "body": body if isinstance(body, str)
                else json.dumps(body, ensure_ascii=False)}

    def _sse(self, envelopes):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for envelope in envelopes:
            self.wfile.write(("data: %s\n\n" % json.dumps(
                envelope, ensure_ascii=False)).encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        if "/algo/api/v2/service/pro/sse/agent_chat_generation" in self.path:
            mode = QODER_FAIL_MODE["mode"]
            QODER_STATE["chat_calls"] += 1
            if mode == "116_once" and QODER_STATE["chat_calls"] == 1:
                return self._sse([self._envelope(
                    {"code": 116, "message": "quota exceeded"}, "ERROR")])
            if mode == "116":
                return self._sse([self._envelope(
                    {"code": 116, "message": "quota exceeded"}, "ERROR")])
            if mode == "10605":
                return self._sse([self._envelope(
                    {"code": 10605, "message": "模型排队中",
                     "retryAfterSeconds": 9}, "ERROR")])
            if mode == "101":
                return self._sse([self._envelope(
                    {"code": 101, "message": "Signature invalid"}, "ERROR")])
            # Intl 网关的真实行为：缺 agent_id 时落到 agent_router 并 400
            if payload.get("agent_id") != "agent_common":
                return self._sse([self._envelope(
                    {"code": 400, "message": "[FAIL]node:agent_router msg:None "
                     "flow nodes found for router agent_router"}, "BAD_REQUEST")])
            model = str((payload.get("model_config") or {}).get("key") or "auto")
            first = {"id": "chatcmpl-q", "model": model,
                     "choices": [{"index": 0, "delta": {
                         "role": "assistant", "content": "你好，Qoder"}}]}
            last = {"id": "chatcmpl-q", "model": model,
                    "choices": [{"index": 0, "delta": {"content": "！"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3,
                              "total_tokens": 8}}
            return self._sse([self._envelope(first), self._envelope(last),
                              self._envelope("[DONE]")])
        if "/sash/api/v1/me/campaigns/" in self.path \
                and self.path.endswith("/claim"):
            QODER_STATE["claims"] += 1
            return self._send_json(200, {
                "grantId": "g1", "status": "CLAIMED",
                "benefit": {"kind": "CREDITS", "amount": 100}})
        if "/api/v1/deviceToken/refresh" in self.path:
            return self._send_json(200, {
                "device_token": "dt-new", "refresh_token": "drt-new",
                "expires_at": int((time.time() + 7 * 86400) * 1000),
                "refresh_token_expires_at": int((time.time() + 30 * 86400) * 1000)})
        return self._send_json(404, {})

    def do_GET(self):
        if "/api/v1/userinfo" in self.path:
            auth = str(self.headers.get("Authorization") or "")
            if "dt-test-2" in auth:
                return self._send_json(200, {
                    "id": "qoder-uid-2", "name": "Qoder轮询号",
                    "username": "qoder2@example.com"})
            return self._send_json(200, {
                "id": "qoder-uid-1", "name": "Qoder测试号",
                "username": "qoder@example.com"})
        if "/api/v2/quota/usage" in self.path:
            return self._send_json(200, {
                "userQuota": {"total": 300, "used": 39, "remaining": 261},
                "addOnQuota": {"total": 100, "used": 0, "remaining": 100},
                "expiresAt": int((time.time() + 30 * 86400) * 1000)})
        if "/sash/api/v1/me/campaigns" in self.path:
            return self._send_json(200, {"campaigns": _campaign_list()})
        return self._send_json(404, {})


