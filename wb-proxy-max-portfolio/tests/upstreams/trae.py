# -*- coding: utf-8 -*-
"""Trae 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import json
import time
from http.server import BaseHTTPRequestHandler


TRAE_FAIL_MODE = {"mode": ""}

TRAE_STATE = {"exchanges": 0, "checkin_claims": 0, "chat_calls": 0}
TRAE_CHECKIN_MODE = {"mode": ""}


def _checkin_status_payload():
    mode = TRAE_CHECKIN_MODE["mode"]
    if mode == "1001":
        return {"code": 1001, "message": "checkin unavailable"}
    checked = TRAE_STATE["checkin_claims"] > 0 and mode not in (
        "status_false", "already_false")
    return {"code": 0, "data": {
        "checked_in": checked,
        "credits": 10 * TRAE_STATE["checkin_claims"]}}

class FakeTraeUpstream(BaseHTTPRequestHandler):
    """Trae 渠道假上游：ExchangeToken / llm_utils_chat SSE / 签到 / 额度 / 目录。"""
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
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
        for ev in events:
            name = ev.get("event")
            data = json.dumps(ev.get("data"), ensure_ascii=False)
            if name:
                self.wfile.write(("event: %s\n" % name).encode())
            self.wfile.write(("data: %s\n\n" % data).encode())
        self.wfile.flush()

    @staticmethod
    def _fake_jwt(uid="trae-uid-1", ttl=3600):
        import base64 as b64
        header = b64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
        payload = b64.urlsafe_b64encode(json.dumps({
            "uid": uid, "exp": int(time.time()) + ttl,
        }).encode()).rstrip(b"=").decode()
        return "%s.%s.sig" % (header, payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        if "ExchangeToken" in self.path:
            TRAE_STATE["exchanges"] += 1
            rt = str(payload.get("RefreshToken") or "")
            if not rt:
                return self._send_json(200, {"ResponseMetadata": {"Error": {"Message": "invalid"}}})
            return self._send_json(200, {"Result": {
                "Token": "Cloud-IDE-JWT " + self._fake_jwt(),
                "RefreshToken": rt + "-r%d" % TRAE_STATE["exchanges"]}})
        if "llm_utils_chat" in self.path:
            TRAE_STATE["chat_calls"] += 1
            if TRAE_FAIL_MODE["mode"] == "1005_once" \
                    and TRAE_STATE["chat_calls"] == 1:
                return self._sse([{"event": "error", "data": {
                    "code": 1005, "message": "积分不足"}}])
            if TRAE_FAIL_MODE["mode"] == "1005":
                return self._sse([{"event": "error", "data": {
                    "code": 1005, "message": "积分不足"}}])
            if TRAE_FAIL_MODE["mode"] == "4008":
                return self._sse([{"event": "error", "data": {
                    "code": 4008, "message": "rate limited"}}])
            if TRAE_FAIL_MODE["mode"] == "11102":
                return self._sse([{"event": "error", "data": {
                    "code": 11102, "message": "service info not found"}}])
            if TRAE_FAIL_MODE["mode"] == "4001_prompt":
                return self._sse([{"event": "error", "data": {
                    "code": 4001, "message": "prompt is too long"}}])
            if TRAE_FAIL_MODE["mode"] == "4001_model":
                return self._sse([{"event": "error", "data": {
                    "code": 4001, "message": "model config is empty"}}])
            cfg = str(payload.get("config_name") or "")
            events = [
                {"event": "output", "data": {"response": "你好，Trae"}},
                {"event": "token_usage", "data": {
                    "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}},
                {"event": "done", "data": {"finish_reason": "stop"}},
            ]
            return self._sse(events) if cfg else self._send_json(400, {"code": 4001})
        if "checkin_credits/claim" in self.path:
            mode = TRAE_CHECKIN_MODE["mode"]
            if mode == "already_false":
                return self._send_json(200, {"code": 400, "message": "今日已签到"})
            if mode == "1001":
                return self._send_json(200, {"code": 1001,
                                             "message": "checkin unavailable"})
            TRAE_STATE["checkin_claims"] += 1
            return self._send_json(200, {"code": 0, "message": "签到成功，+10 积分"})
        if "checkin_credits/status" in self.path:
            return self._send_json(200, _checkin_status_payload())
        if "ide_user_ent_usage" in self.path:
            return self._send_json(200, {"data": {"user_entitlement_pack_list": [
                {"entitlement_base_info": {"ent_status": 0},
                 "quota": {"credits_limit": 50.0},
                 "usage": {"credits_amount": 12.0}}]}})
        if "get_detail_param" in self.path:
            fn = str(payload.get("function") or "")
            names = ["glm-5.3"] if fn == "solo_work_lite" else ["qwen3.8-flash"]
            return self._send_json(200, {"config_info_list": [
                {"config_name": n, "context_window_tokens": {"dev": 128000, "max": 256000},
                 "model_detail_list": [{"max_tokens": 32000}],
                 "display_config": {"display_name": n.upper(), "fee_model_level": 1},
                 # 官方条目带消费倍率（display_contact_config 内嵌 JSON）；
                 # 无倍率条目按用户口径整条不展示，假上游须同构
                 "display_contact_config": json.dumps(
                     {"consumption_rate": {"data": {"rate": 0.5}}})}
                for n in names]})
        return self._send_json(404, {})

    def do_GET(self):
        if "checkin_credits/status" in self.path:
            return self._send_json(200, _checkin_status_payload())
        return self._send_json(404, {})


