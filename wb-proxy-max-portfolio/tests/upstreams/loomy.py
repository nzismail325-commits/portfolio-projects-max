# -*- coding: utf-8 -*-
"""Loomy 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import hashlib
import hmac
import json
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler


LOOMY_FAIL_MODE = {"mode": ""}
LOOMY_STATE = {"send_codes": 0, "logins": 0, "chat_calls": 0,
               "model_calls": 0, "first_login_calls": 0, "points_calls": 0,
               "signatures": 0, "bad_signatures": 0,
               "last_headers": {}, "last_payload": {},
               "session": "loomy-session-1", "msgid": "loomy-msgid-1"}



class FakeLoomyUpstream(BaseHTTPRequestHandler):
    """Loomy 假上游：HMAC-SHA1 短信登录、token 目录/积分、追踪头聊天、双钱包。"""
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

    def _sse(self, frames):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for frame in frames:
            self.wfile.write(("data: %s\n\n" % json.dumps(
                frame, ensure_ascii=False)).encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _verify_signature(self, raw):
        import base64 as b64
        import hashlib
        import hmac
        from integrations import loomy as loomy_mod
        auth = str(self.headers.get("Authorization") or "")
        if not auth.startswith("account "):
            return False
        access_key, _, signature = auth[len("account "):].partition(":")
        if access_key != loomy_mod.CFG["accessKeyId"] or not signature:
            return False
        md5 = str(self.headers.get("Content-MD5") or "")
        expected_md5 = (b64.b64encode(hashlib.md5(raw).digest()).decode("ascii")
                        if raw else "")
        if md5 != expected_md5:
            return False
        string_to_sign = "\n".join([
            "POST", loomy_mod.build_escaped_path(self.path), "", md5,
            "application/json", str(self.headers.get("Date") or ""),
            str(self.headers.get("Nonce") or ""), "", "",
        ])
        expected = b64.b64encode(hmac.new(
            loomy_mod.CFG["accessKeySecret"].encode("utf-8"),
            string_to_sign.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")
        return hmac.compare_digest(expected, signature)

    def _token_header(self):
        headers = {key.lower(): value for key, value in self.headers.items()}
        LOOMY_STATE["last_headers"] = headers
        return bool(str(headers.get("token") or ""))

    def _chat_headers(self):
        if not self._token_header():
            return False
        headers = LOOMY_STATE["last_headers"]
        token = str(headers.get("token") or "")
        if str(headers.get("authorization") or "") != "Bearer " + token:
            return False
        trace = str(headers.get("traceparent") or "")
        if not re.match(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$", trace):
            return False
        if not str(headers.get("loomy-version") or ""):
            return False
        if str(headers.get("x-loomy-request-purpose") or "") != "chat.message":
            return False
        if str(headers.get("invokeorigin") or "") != "user":
            return False
        return all(str(headers.get(key) or "") for key in ("chatid", "msgid", "turnid"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        path = urllib.parse.urlsplit(self.path).path

        if path in ("/login/phone/sendMsgCode", "/login/phone/checkCode"):
            if not self._verify_signature(raw):
                LOOMY_STATE["bad_signatures"] += 1
                return self._send_json(401, {"code": "020002",
                                             "desc": "signature invalid"})
            LOOMY_STATE["signatures"] += 1
            payload = json.loads(raw or b"{}")
            param = payload.get("param") or {}
            if path.endswith("sendMsgCode"):
                LOOMY_STATE["send_codes"] += 1
                if str(param.get("phone") or "") != "13812345678":
                    return self._send_json(200, {"code": "100001",
                                                 "desc": "手机号不存在"})
                return self._send_json(200, {
                    "code": "000000", "desc": "success",
                    "data": {"msgid": LOOMY_STATE["msgid"]}})
            LOOMY_STATE["logins"] += 1
            if (str(param.get("mcode") or "") != "123456"
                    or str(param.get("msgid") or "") != LOOMY_STATE["msgid"]):
                return self._send_json(200, {"code": "100002",
                                             "desc": "验证码错误"})
            return self._send_json(200, {
                "code": "000000", "desc": "success",
                "data": {"session": LOOMY_STATE["session"],
                         "userid": "loomy-user-1"}})

        if path == "/api/v1/points/first-login":
            if not self._token_header():
                return self._send_json(401, {"code": "100002",
                                             "desc": "登录态已失效"})
            LOOMY_STATE["first_login_calls"] += 1
            return self._send_json(200, {
                "code": "000000", "desc": "success",
                "data": {"dailyBalance": 5000}})

        if path == "/api/v1/chat/completions":
            LOOMY_STATE["chat_calls"] += 1
            if not self._chat_headers():
                return self._send_json(401, {"code": "100002",
                                             "desc": "登录态已失效"})
            try:
                LOOMY_STATE["last_payload"] = json.loads(raw or b"{}")
            except Exception:
                LOOMY_STATE["last_payload"] = {}
            mode = LOOMY_FAIL_MODE["mode"]
            if mode == "401":
                return self._send_json(401, {"code": "020002",
                                             "desc": "登录态已失效"})
            if mode == "429":
                body = b'{"code":"100003","desc":"rate limited"}'
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "5")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if mode == "auth_sse":
                return self._sse([{"code": "020002",
                                   "desc": "登录态已失效"}])
            if mode == "auth_json":
                return self._send_json(200, {"code": "100002",
                                             "desc": "登录已失效"})
            if mode == "empty":
                return self._sse([{
                    "id": "chatcmpl-loomy", "object": "chat.completion.chunk",
                    "model": "spark-x",
                    "choices": [{"index": 0, "delta": {"role": "assistant"},
                                 "finish_reason": "stop"}]}])
            model = str(LOOMY_STATE["last_payload"].get("model") or "spark-x")
            return self._sse([
                {"id": "chatcmpl-loomy", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                {"id": "chatcmpl-loomy", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0,
                              "delta": {"content": "你好，Loomy"}}]},
                {"id": "chatcmpl-loomy", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 3,
                           "total_tokens": 8}},
            ])

        return self._send_json(404, {})

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path == "/api/v1/models":
            LOOMY_STATE["model_calls"] += 1
            if not self._token_header():
                return self._send_json(401, {"code": "100002",
                                             "desc": "登录态已失效"})
            return self._send_json(200, {"data": [
                {"id": "spark-x", "type": "chat",
                 "name": "Spark X (x3.0)", "protocol": "openai_chat",
                 "context_length": 131072, "max_output_tokens": 8192,
                 "capabilities": {"reasoning": True, "vision": False,
                                  "function_calling": True,
                                  "input_modalities": ["text"],
                                  "output_modalities": ["text"]}},
                {"id": "deepseek-v4", "type": "chat",
                 "displayName": "DeepSeek V4", "protocol": "openai_chat",
                 "context_length": 128000, "max_output_tokens": 8192,
                 "capabilities": {"reasoning": True, "vision": True,
                                  "function_calling": True,
                                  "input_modalities": ["text", "image"],
                                  "output_modalities": ["text"]}},
                {"id": "image-only", "type": "image",
                 "protocol": "openai_chat",
                 "capabilities": {"vision": True,
                                  "output_modalities": ["image"]}},
                {"id": "claude-sonnet", "type": "chat",
                 "displayName": "Claude Sonnet",
                 "protocol": "anthropic_messages",
                 "capabilities": {"function_calling": True}},
            ]})
        if path.path == "/api/v2/points/records":
            LOOMY_STATE["points_calls"] += 1
            if not self._token_header():
                return self._send_json(401, {"code": "100002",
                                             "desc": "登录态已失效"})
            return self._send_json(200, {
                "code": "000000", "desc": "success",
                "data": {"balance": 2000, "dailyBalance": 5000,
                         "dailyLimitPoints": 5000,
                         "dailyRemainingPoints": 3000}})
        return self._send_json(404, {})


