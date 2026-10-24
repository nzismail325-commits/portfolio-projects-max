# -*- coding: utf-8 -*-
"""ZCode 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import hashlib
import json
import os
import time
from http.server import BaseHTTPRequestHandler


ZCODE_FAIL_MODE = {"mode": "", "balance": "", "account": ""}
ZCODE_STATE = {"last": {}, "flows": 0, "balance_calls": 0}

def fake_zcode_jwt(uid):
    import base64 as b64
    header = b64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = b64.urlsafe_b64encode(json.dumps(
        {"user_id": uid, "sub": uid}).encode()).rstrip(b"=").decode()
    return "%s.%s.sig" % (header, payload)


def zcode_encrypt(value):
    """按 zcode enc:v1 格式加密（与 auth.atrest 的纯 Python GCM 同源）。"""
    from auth import atrest
    import base64 as b64
    import hashlib
    from integrations import zcode_local
    key = hashlib.sha256(zcode_local.default_secret().encode()).digest()
    nonce = os.urandom(12)
    aes = atrest._AES256(key)
    h = int.from_bytes(aes.encrypt_block(b"\x00" * 16), "big")
    j0 = nonce + b"\x00\x00\x00\x01"
    cipher = atrest._gctr(aes, j0, str(value).encode("utf-8"))
    tag = (int.from_bytes(aes.encrypt_block(j0), "big")
           ^ atrest._ghash(h, b"", cipher)).to_bytes(16, "big")
    enc = lambda raw: b64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return "enc:v1:%s.%s.%s" % (enc(nonce), enc(tag), enc(cipher))

class FakeZcodeUpstream(BaseHTTPRequestHandler):
    """ZCode 假上游：Anthropic Messages SSE / 额度 / OAuth。"""
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

    def _sse(self, events):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for name, data in events:
            if name:
                self.wfile.write(("event: %s\n" % name).encode())
            self.wfile.write(("data: %s\n\n" % json.dumps(
                data, ensure_ascii=False)).encode("utf-8"))
        self.wfile.flush()
        self.close_connection = True

    @staticmethod
    def _normal_events():
        return [
            ("message_start", {"type": "message_start", "message": {
                "usage": {"input_tokens": 0}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "text_delta",
                                               "text": "你好，ZCode！"}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": "end_turn"},
                               "usage": {"input_tokens": 5, "output_tokens": 6,
                                         "cache_read_input_tokens": 2}}),
            ("message_stop", {"type": "message_stop"}),
        ]

    @staticmethod
    def _tool_events():
        return [
            ("message_start", {"type": "message_start", "message": {
                "usage": {"input_tokens": 5}}}),
            ("content_block_start", {"type": "content_block_start", "index": 0,
                                     "content_block": {"type": "tool_use", "id": "call_z1",
                                                       "name": "web_search"}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": '{"query":'}}),
            ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                     "delta": {"type": "input_json_delta",
                                               "partial_json": ' "zcode"}'}}),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": "tool_use"},
                               "usage": {"input_tokens": 5, "output_tokens": 6}}),
            ("message_stop", {"type": "message_stop"}),
        ]

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        ZCODE_STATE["last"] = {
            "path": self.path,
            "payload": payload,
            "headers": {key.lower(): value for key, value in self.headers.items()},
        }
        mode = ZCODE_FAIL_MODE["mode"]
        if "/v1/oauth/cli/init" in self.path:
            ZCODE_STATE["flows"] += 1
            return self._send_json(200, {"code": 0, "data": {
                "flow_id": "flow-z%d" % ZCODE_STATE["flows"],
                "authorize_url": "https://zcode.test/authorize?x=1",
                "poll_interval_sec": 1,
                "expires_at": int(time.time() + 180)}})
        if "/v1/oauth/token" in self.path:
            return self._send_json(200, {"code": 0, "data": {
                "token": fake_zcode_jwt("zcode-oauth-2"),
                "user": {"user_id": "zcode-oauth-2", "name": "ZCode OAuth 回调号"},
                "zai": {"access_token": "at-oauth-2", "refresh_token": "rt-oauth-2"}}})
        if "/api/auth/z/login" in self.path:
            return self._send_json(200, {"access_token": "biz-token"})
        if "/v1/messages" in self.path:
            start_plan = "/api/v1/zcode-plan/anthropic/" in self.path
            coding_plan = "/api/anthropic/" in self.path or "/bigmodel-anthropic/" in self.path
            wanted = ZCODE_FAIL_MODE.get("account") or ""
            auth = str(self.headers.get("Authorization") or "")
            if wanted and auth != "Bearer " + fake_zcode_jwt(wanted):
                mode = ""
            if mode == "quota_sse":
                return self._sse([("error", {"type": "error", "error": {
                    "code": 1113, "message": "Insufficient balance"}})])
            if start_plan:
                system = payload.get("system") or ""
                if isinstance(system, list):
                    system = "".join(str((block or {}).get("text") or "")
                                     for block in system)
                if not str(system).startswith("You are ZCode, an interactive coding agent"):
                    return self._send_json(405, {"code": 3012,
                                                 "message": "unusual activity"})
            if mode == "429":
                return self._send_json(429, {"code": 3008, "message": "rate limited"})
            if mode in ("coding_402", "plan_402") and coding_plan:
                return self._send_json(402, {"code": 1113,
                                             "message": "Insufficient balance"})
            if mode == "3007":
                return self._sse([("error", {"type": "error", "error": {
                    "code": 3007, "message": "captcha verify required"}})])
            if mode == "4001":
                return self._sse([("error", {"type": "error", "error": {
                    "code": 4001, "message": "model config is empty"}})])
            if mode == "empty":
                return self._sse([
                    ("message_start", {"type": "message_start", "message": {
                        "usage": {"input_tokens": 5}}}),
                    ("message_delta", {"type": "message_delta",
                                       "delta": {"stop_reason": "end_turn"},
                                       "usage": {"input_tokens": 5, "output_tokens": 0}}),
                    ("message_stop", {"type": "message_stop"})])
            if mode == "tool":
                return self._sse(self._tool_events())
            return self._sse(self._normal_events())
        return self._send_json(404, {})

    def do_GET(self):
        ZCODE_STATE["last_get"] = {
            "path": self.path,
            "headers": {key.lower(): value for key, value in self.headers.items()},
        }
        if "/billing/balance" in self.path:
            mode = ZCODE_FAIL_MODE.get("balance") or ""
            if mode:
                ZCODE_STATE["balance_calls"] = ZCODE_STATE.get(
                    "balance_calls", 0) + 1
                calls = ZCODE_STATE["balance_calls"]
                if (mode == "401_always"
                        or (mode == "401_final" and calls <= 4)
                        or (mode == "401_ladder" and calls <= 1)):
                    return self._send_json(401, {"code": 401,
                                                 "message": "unauthorized"})
            expires = int((time.time() + 30 * 86400) * 1000)
            return self._send_json(200, {"code": 0, "data": {
                "balances": [
                    {"plan_id": "plan1", "show_name": "Pro 套餐",
                     "total_units": 300, "used_units": 124,
                     "remaining_units": 176, "expires_at": expires,
                     "capabilities": ["model:GLM-5.3", "model:GLM-5.3-Flash"]},
                    {"plan_id": "plan2", "show_name": "加油包",
                     "total_units": 100, "used_units": 0,
                     "remaining_units": 100, "expires_at": 0,
                     "capabilities": ["model:GLM-5.2"]},
                ],
                "plans": [{"plan_id": "plan1", "name": "Pro 套餐"}]}})
        if "/billing/current" in self.path:
            return self._send_json(200, {"code": 0, "data": {
                "plans": [{"plan_id": "plan1", "name": "Pro 套餐"}]}})
        if "/monitor/usage/quota/limit" in self.path:
            return self._send_json(200, {"data": {
                "level": "pro", "limits": [{
                    "remaining": 100, "total": 100,
                    "nextResetTime": int((time.time() + 7 * 86400) * 1000)}]}})
        if "/api/biz/customer/getCustomerInfo" in self.path:
            return self._send_json(200, {"code": 0, "data": {
                "organizations": [{
                    "organizationId": "org1", "organizationName": "默认机构",
                    "projects": [{"projectId": "proj1",
                                  "projectName": "默认项目"}]}]}})
        if "/api/biz/v1/organization/org1/projects/proj1/api_keys" in self.path:
            if "/copy/" in self.path:
                return self._send_json(200, {"code": 0, "data": {
                    "secretKey": "secret456"}})
            return self._send_json(200, {"code": 0, "data": [
                {"name": "zcode-api-key", "apiKey": "key123"}]})
        if "/oauth/cli/poll/" in self.path:
            return self._send_json(200, {"code": 0, "data": {
                "status": "ready",
                "token": fake_zcode_jwt("zcode-oauth-1"),
                "user": {"user_id": "zcode-oauth-1", "name": "ZCode OAuth 轮询号"},
                "zai": {"access_token": "at-oauth-1", "refresh_token": "rt-oauth-1"}}})
        return self._send_json(404, {})


