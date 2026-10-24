# -*- coding: utf-8 -*-
"""CodeArts 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import hashlib
import json
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler


CODEARTS_FAIL_MODE = {"mode": ""}
CODEARTS_STATE = {"chat_calls": 0, "refreshes": 0, "exchanges": 0,
                  "claims": 0, "confirms": 0, "delivery_reads": 0,
                  "agent_calls": 0, "detail_calls": 0,
                  "balance_calls": 0, "gateway_calls": 0,
                  "last_headers": {}, "last_payload": {},
                  "last_claim": {}, "last_confirm": {},
                  "agent_agent_type": "", "builtin_agent_type": "",
                  "welfare_items": [], "confirm_mode": ""}

def fake_codearts_rt(user_id="user-seed", name="CodeArts 测试号",
                     domain_id="dom-seed"):
    import base64 as b64
    header = b64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload = b64.urlsafe_b64encode(json.dumps({
        "domain_id": domain_id, "user_id": user_id, "user_name": name,
        "exp": int(time.time()) + 30 * 86400,
    }).encode()).rstrip(b"=").decode()
    return "%s.%s.sig" % (header, payload)


def verify_codearts_es256(jwk, signing_input, signature):
    """独立验证 DPoP 的 ES256 签名（不复用生产签名路径）。"""
    import hashlib
    from integrations import codearts as codearts_mod
    try:
        x = int.from_bytes(codearts_mod._b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(codearts_mod._b64url_decode(jwk["y"]), "big")
        if not (1 <= x < codearts_mod._P and 1 <= y < codearts_mod._P):
            return False
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        n = codearts_mod._N
        if not (1 <= r < n and 1 <= s < n):
            return False
        digest = int.from_bytes(hashlib.sha256(signing_input).digest(), "big")
        w = pow(s, n - 2, n)
        point = codearts_mod._point_add(
            codearts_mod._scalar_mult((digest * w) % n, codearts_mod._G),
            codearts_mod._scalar_mult((r * w) % n, (x, y)))
        return point is not None and point[0] % n == r
    except Exception:
        return False



class FakeCodeArtsUpstream(BaseHTTPRequestHandler):
    """CodeArts 假上游：OAuth/DPoP、签名聊天、三源目录、双账余额、福利三段式。"""
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

    @staticmethod
    def _b64d(text):
        import base64 as b64
        raw = str(text or "")
        return b64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))

    def _verify_dpop(self):
        from integrations import codearts as codearts_mod
        proof = str(self.headers.get("DPoP") or "")
        try:
            header_b64, payload_b64, signature_b64 = proof.split(".")
            header = json.loads(self._b64d(header_b64).decode())
            payload = json.loads(self._b64d(payload_b64).decode())
            if payload.get("htm") != "POST":
                return False
            if payload.get("htu") != codearts_mod.TOKEN_URL:
                return False
            if header.get("alg") != "ES256" or header.get("typ") != "dpop+jwt":
                return False
            return verify_codearts_es256(
                header.get("jwk") or {},
                ("%s.%s" % (header_b64, payload_b64)).encode("ascii"),
                self._b64d(signature_b64))
        except Exception:
            return False

    def _credentials(self, refresh_token, suffix):
        from datetime import datetime, timedelta, timezone
        expires = (datetime.now(timezone.utc)
                   + timedelta(seconds=3600)).isoformat().replace("+00:00", "Z")
        # 真实响应：refresh_token 在顶层，credentials 内只有 AK/SK/STS。
        return {
            "credentials": {
                "access_key_id": "AK-%s" % suffix,
                "secret_access_key": "SK-%s" % suffix,
                "security_token": "STS-%s" % suffix,
                "expiration": expires,
            },
            "refresh_token": refresh_token,
        }

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.path == "/v1/oauth2/tokens":
            if not self._verify_dpop():
                return self._send_json(401, {"error": "invalid_dpop_proof"})
            form = urllib.parse.parse_qs(raw.decode("utf-8", "replace"))
            grant = (form.get("grant_type") or [""])[0]
            if grant == "authorization_code":
                CODEARTS_STATE["exchanges"] += 1
                if (form.get("code") or [""])[0] != "login-code":
                    return self._send_json(400, {"error": "invalid_grant"})
                return self._send_json(200, self._credentials(
                    fake_codearts_rt("user-login", "CodeArts 登录号", "dom-1"),
                    "login"))
            if grant == "refresh_token":
                CODEARTS_STATE["refreshes"] += 1
                old = (form.get("refresh_token") or ["rt"])[0]
                return self._send_json(200, self._credentials(
                    "%s-r%d" % (old, CODEARTS_STATE["refreshes"]),
                    "refresh%d" % CODEARTS_STATE["refreshes"]))
            return self._send_json(400, {"error": "unsupported_grant"})

        if self.path.startswith("/api/v2/chat/completions"):
            CODEARTS_STATE["chat_calls"] += 1
            CODEARTS_STATE["last_headers"] = {
                key.lower(): value for key, value in self.headers.items()}
            try:
                CODEARTS_STATE["last_payload"] = json.loads(raw or b"{}")
            except Exception:
                CODEARTS_STATE["last_payload"] = {}
            mode = CODEARTS_FAIL_MODE["mode"]
            if mode == "401_once" and CODEARTS_STATE["chat_calls"] == 1:
                return self._send_json(401, {"error": "token expired"})
            if mode == "429":
                self.send_response(429)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "5")
                body = b'{"error":"rate limited"}'
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if mode == "quota_sse":
                return self._sse([{
                    "error_code": "InferHub.4291.200",
                    "error_msg": "insufficient quota"}])
            if mode == "empty":
                return self._sse([{
                    "choices": [{"index": 0, "delta": {},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 0,
                              "total_tokens": 3}}])
            model = str(CODEARTS_STATE["last_payload"].get("model") or "GLM-5.2")
            return self._sse([
                {"id": "chatcmpl-ca", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0,
                              "delta": {"role": "assistant"}}]},
                {"id": "chatcmpl-ca", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0,
                              "delta": {"content": "你好，CodeArts"}}]},
                {"id": "chatcmpl-ca", "object": "chat.completion.chunk",
                 "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 3,
                           "total_tokens": 8}},
            ])

        if self.path == "/v1/ops/claim":
            CODEARTS_STATE["claims"] += 1
            try:
                payload = json.loads(raw or b"{}")
            except Exception:
                payload = {}
            CODEARTS_STATE["last_claim"] = payload
            if payload.get("channel") != "DESKTOP" \
                    or not payload.get("campaignId") \
                    or not payload.get("idempotentKey"):
                return self._send_json(400, {"code": 400,
                                             "message": "invalid claim"})
            for item in CODEARTS_STATE["welfare_items"]:
                if item.get("campaignId") == payload.get("campaignId"):
                    item["status"] = "CLAIMED"
                    item["claimable"] = False
                    return self._send_json(200, {
                        "code": 0, "message": "ok",
                        "data": {"id": 9000 + int(item["campaignId"])}})
            return self._send_json(404, {"code": 404, "message": "no campaign"})
        if self.path == "/v1/ops/confirm":
            CODEARTS_STATE["confirms"] += 1
            try:
                payload = json.loads(raw or b"{}")
            except Exception:
                payload = {}
            CODEARTS_STATE["last_confirm"] = payload
            # 真实上游要求 campaignId + userBenefitId；只传一个会 400。
            if not payload.get("campaignId") or not payload.get("userBenefitId"):
                return self._send_json(400, {
                    "error_code": "PROMPTCENTER.00000001",
                    "error_msg": "campaignId : 参数无效"})
            if CODEARTS_STATE.get("confirm_mode") == "reject":
                return self._send_json(400, {
                    "error_code": "PROMPTCENTER.00000001",
                    "error_msg": "campaignId : 参数无效"})
            if CODEARTS_STATE.get("confirm_mode") == "noop":
                return self._send_json(200, {"code": 0})
            for item in CODEARTS_STATE["welfare_items"]:
                if item.get("campaignId") == payload.get("campaignId"):
                    item["status"] = "CONFIRMED"
            return self._send_json(200, {"code": 0})
        return self._send_json(404, {})

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        if path.path == "/v1/agent-center/agents/useragents":
            CODEARTS_STATE["agent_calls"] += 1
            CODEARTS_STATE["agent_agent_type"] = \
                self.headers.get("Agent-Type") or ""
            return self._send_json(200, {"total": 1, "agents": [
                {"agent_id": "agent-1", "show_in_ide": True,
                 "models": [{"model_id": "GLM-5.2",
                             "model_name": "GLM-5.2",
                             "credit": [{"ratio_display": "0.62x"}]}]}]})
        if path.path == "/v1/agent-center/agents/detail":
            CODEARTS_STATE["detail_calls"] += 1
            return self._send_json(200, {"data": {"gpts": {"models": [
                {"model_id": "GLM-5.2", "model_name": "GLM-5.2"},
            ]}}})
        if path.path == "/v1/model/builtin":
            CODEARTS_STATE["builtin_agent_type"] = \
                self.headers.get("Agent-Type") or ""
            return self._send_json(200, {"count": 1, "builtinModels": [
                {"model_id": "DeepSeek-V4", "model_name": "DeepSeek V4",
                 "multimodal": True,
                 "credit": [{"ratio_display": "0.18x",
                             "before_display_ratio": None}]},
            ]})
        if path.path == "/v1/benefit-gateway-config":
            return self._send_json(200, {"enabled": True})
        if path.path == "/api/v1/gateway/config":
            CODEARTS_STATE["gateway_calls"] += 1
            return self._send_json(200, {
                "error_code": "0000",
                "result": {"models": [
                    {"model_id": "Benefit-Qwen",
                     "model_name": "Benefit Qwen"}]}})
        if path.path == "/snap-manager/v1/statistics/plugin":
            return self._send_json(200, {
                "metrics": [
                    {"name": "usageDataChatMessages", "value": -1,
                     "usage_token_num": 0, "package_token_amount": 0,
                     "show": False},
                    # 积分套餐里这个字段固定是 1；面板若拿它当余额就会显示 1
                    {"name": "usageTokenChatMessages", "value": 0,
                     "usage_token_num": 0, "package_token_amount": 1,
                     "show": True},
                    {"name": "usageTotalPackageCredit", "value": 0,
                     "usage_token_num": 0, "package_token_amount": 0,
                     "package_credit_amount": 5500.0,
                     "package_credit_used": 250.0,
                     "package_credit_remain": 5250.0,
                     "package_credit_expiring_amount": 0, "show": True},
                    {"name": "usageBasicPackageCredit", "value": 0,
                     "usage_token_num": 0, "package_token_amount": 0,
                     "package_credit_amount": 500.0,
                     "package_credit_used": 250.0,
                     "package_credit_remain": 250.0, "show": True},
                    {"name": "usageOnDemandPackageCredit", "value": 0,
                     "usage_token_num": 0, "package_token_amount": 0,
                     "package_credit_amount": 0.0,
                     "package_credit_used": 0.0,
                     "package_credit_remain": 0.0, "show": True},
                    {"name": "usageBonusPackageCredit", "value": 0,
                     "usage_token_num": 0, "package_token_amount": 0,
                     "package_credit_amount": 5000.0,
                     "package_credit_used": 0.0,
                     "package_credit_remain": 5000.0,
                     "package_credit_expiring_amount": 0, "show": True},
                ],
                "package": {"package_name_en": "Trial", "status": "normal",
                            "spec_code": "codearts.agent.individual.trial",
                            "is_token_package": False,
                            "is_credit_package": True},
                "model_metrics": [],
                "is_white_list": False,
                "show": {"metrics": True, "package": True},
            })
        if path.path == "/api/v1/user/tokens/balance":
            CODEARTS_STATE["balance_calls"] += 1
            return self._send_json(200, {
                "error_code": "0000",
                "result": {"used_amount": 679,
                           "total_quota": 1000}})
        if path.path == "/v1/ops/delivery":
            channels = urllib.parse.parse_qs(path.query).get("channel") or []
            if (channels or [""])[0] != "DESKTOP":
                return self._send_json(404, {})
            CODEARTS_STATE["delivery_reads"] += 1
            return self._send_json(200, {
                "code": 0, "message": "ok",
                "data": {"channel": "DESKTOP",
                         "items": CODEARTS_STATE["welfare_items"],
                         "endedCampaigns": []}})
        return self._send_json(404, {})


