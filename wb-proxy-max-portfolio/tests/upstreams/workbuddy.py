# -*- coding: utf-8 -*-
"""WorkBuddy 渠道假上游（从 test_smoke.py 拆出，状态由渠道检查模块导入）。"""
import json
import time
from http.server import BaseHTTPRequestHandler


FAIL_MODE = {"mode": ""}

STREAK_STATE = {"makeup_used": 0, "gift_claimed": False, "lottery_drawn": False}
# 断流重开：第一次请求只发响应头不发正文，第二次走正常流
CUT_STATE = {"calls": 0}
CHECKIN_STATE = {"calls": 0}
#: 签到回执开关：默认签成；"pending" / "already" / "failed" 切换成对应回执，
#: 用来验证「只有真签成才写 last_checkin」这条语义。
CHECKIN_REPLY = {"mode": ""}
#: 网页会话状态：active 是当前活跃会话清单，stopped / deleted 记录收尾动作，
#: full 模拟「活跃会话已满」——建会话一律回 429 + 10105。
CONVERSATION_STATE = {"active": [], "stopped": [], "deleted": [], "full": False,
                      "created": 0}


class FakeUpstream(BaseHTTPRequestHandler):
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

    def _sse(self, chunks, done=True):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(("data: %s\n\n" % json.dumps(
                chunk, ensure_ascii=False)).encode("utf-8"))
        if done:
            self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path.startswith("/v3/config"):
            return self._send_json(200, {"data": {
                "agents": [
                    {"name": "cli", "models": ["deepseek-v4.1-flash", "glm-5.3"]}],
                "modelTiers": [
                    {"requiredUserType": "standard", "modelIds": ["grok-4.7"]}],
            }})
        if self.path.startswith("/activity/growth/buddy/travel/status"):
            return self._send_json(200, {"data": {"state": "idle",
                                                  "daily_limit_reached": True}})
        if self.path.startswith("/v2/activity/growth/tasks"):
            return self._send_json(200, {"data": {"tasks": []}})
        if self.path.startswith("/activity/growth/heatmap"):
            # 首轮：昨日漏签（score=0）；补签执行后：当日已签（score=1）
            signed = 1 if STREAK_STATE["makeup_used"] else 0
            return self._send_json(200, {"data": {"cells": [
                {"date": time.strftime("%Y-%m-%d",
                                       time.localtime(time.time() - 86400)),
                 "score": signed}]}})
        if self.path.startswith("/activity/growth/streak"):
            return self._send_json(200, {"data": {
                "makeup_cards": {"balance": 2 if not STREAK_STATE["makeup_used"] else 0},
                "redemption_status": {"tiers": [{"tier": "7d"}],
                                      "tier_7d_status": "available"}}})
        if self.path.startswith("/activity/growth/lottery/summary"):
            # 首轮 2 次抽奖机会，抽完归零（独立于礼包标记）
            chances = 0 if STREAK_STATE["lottery_drawn"] else 2
            return self._send_json(200, {"data": {"chances": chances}})
        if self.path.startswith("/console/account"):
            return self._send_json(200, {"data": {"uid": "u1", "nickname": "测试号"}})
        if self.path.startswith("/console/as/conversations"):
            # 活跃会话列表：用于验证「撞上限时清理最旧的本网关会话」
            if "/session" in self.path:
                return self._send_json(200, {"code": 0, "data": {
                    "link": "http://127.0.0.1:1/sandbox",
                    "token": "sandbox-token", "cwd": "/workspace"}})
            return self._send_json(200, {"data": {
                "conversations": list(CONVERSATION_STATE["active"])}})
        return self._send_json(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = {}
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            payload = {}
        mode = FAIL_MODE["mode"]
        if mode == "daily_empty" and "/chat/completions" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        if mode == "daily_error_frame" and "/chat/completions" in self.path:
            return self._sse([{"code": 11158, "msg": "model not allowed"}])
        if mode == "stream_cut_once" and "/chat/completions" in self.path:
            CUT_STATE["calls"] += 1
            if CUT_STATE["calls"] == 1:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", "200")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                return
        if mode == "stream_stall_mid" and "/chat/completions" in self.path:
            # One real chunk, then silence longer than the configured idle
            # timeout: the client gets output followed by a genuine read
            # failure (not a clean EOF), which is the "died mid-body" case the
            # gateway must not end with a normal [DONE].
            abort_model = payload.get("model") or "m"
            chunk = json.dumps({
                "id": "chatcmpl-abort", "model": abort_model,
                "choices": [{"index": 0, "delta": {"content": "半截"}}],
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"data: " + chunk + b"\n\n")
            self.wfile.flush()
            time.sleep(2.5)
            self.close_connection = True
            return
        if mode == "429":
            return self._send_json(429, {"code": 14003,
                                         "msg": "usage exceeds frequency limit"})
        if mode == "402":
            return self._send_json(402, {"code": 402, "msg": "insufficient credits"})
        if mode == "500":
            return self._send_json(500, {"code": 500, "msg": "boom"})
        if mode == "model_scoped":
            return self._send_json(502, {"code": 11134,
                                         "msg": "model provider temporarily unavailable"})
        if mode == "entitlement_11158":
            return self._send_json(502, {
                "code": 11158,
                "msg": "model deepseek-v4.1-flash is not allowed for user type "
                       "[personal_free_user]"})
        if self.path.startswith("/billing/meter/get-user-resource-summary"):
            # 计费摘要（付费标记 + 套餐名）：面板账号行的会员档位胶囊读它
            return self._send_json(200, {"code": 0, "data": {
                "IsPaidUser": False, "SubscriptionPackageName": "Free",
                "SubscriptionPackageCode": "", "IsProtectedPriceUser": False,
                "ProTrialStatus": 0}})
        if self.path.startswith("/v2/billing/meter/get-user-resource"):
            remain = 100 + (20 if STREAK_STATE["lottery_drawn"] else 0)
            return self._send_json(200, {"code": 0, "data": {"Response": {"Data": {
                "Accounts": [{"PackageName": "Free", "CapacityRemain": remain,
                              "CapacityUsed": 0, "CapacitySize": remain + 100}]}}}})
        if self.path.startswith("/console/as/conversations"):
            rest = self.path[len("/console/as/conversations"):].strip("/")
            if not rest:
                # 建会话：full 时回 429 + 10105，模拟活跃会话已满
                if CONVERSATION_STATE["full"]:
                    return self._send_json(429, {
                        "code": 10105,
                        "msg": "CreateConversation: 10105:you have reached the "
                               "maximum number of active conversations(10)"})
                CONVERSATION_STATE["created"] += 1
                conv_id = "conv-%d" % CONVERSATION_STATE["created"]
                CONVERSATION_STATE["active"].append({
                    "id": conv_id, "name": (payload or {}).get("prompt") or "",
                    "status": "working", "createdAt": "2026-10-23T00:00:00Z"})
                return self._send_json(200, {"code": 0, "data": {"id": conv_id}})
            conv_id, _, action = rest.partition("/")
            if action == "stop":
                CONVERSATION_STATE["stopped"].append(conv_id)
                for row in CONVERSATION_STATE["active"]:
                    if row.get("id") == conv_id:
                        row["status"] = "completed"
                return self._send_json(200, {"code": 0})
            if action == "delete":
                CONVERSATION_STATE["deleted"].append(conv_id)
                CONVERSATION_STATE["active"] = [
                    row for row in CONVERSATION_STATE["active"]
                    if row.get("id") != conv_id]
                return self._send_json(200, {"code": 0})
            if action == "session":
                return self._send_json(200, {"code": 0, "data": {
                    "link": "http://127.0.0.1:1/sandbox",
                    "token": "sandbox-token", "cwd": "/workspace"}})
            return self._send_json(404, {})
        if self.path.startswith("/v2/billing/meter/daily-checkin"):
            CHECKIN_STATE["calls"] += 1
            mode = CHECKIN_REPLY["mode"]
            if mode == "pending":
                return self._send_json(200, {"code": 10001,
                                             "msg": "请求处理中，请勿重复操作"})
            if mode == "already":
                return self._send_json(200, {"code": 10001, "msg": "今日已签到"})
            if mode == "failed":
                return self._send_json(200, {"code": 0, "msg": "签到失败，已签到天数不足 7 天"})
            return self._send_json(200, {"code": 0, "msg": "ok"})
        if self.path.startswith("/activity/growth/makeup-cards/use"):
            STREAK_STATE["makeup_used"] += 1
            return self._send_json(200, {"code": 0, "data": {}})
        if self.path.startswith("/activity/growth/redeem"):
            return self._send_json(200, {"code": 0, "data": {}})
        if self.path.startswith("/activity/growth/lottery/draw"):
            STREAK_STATE["lottery_drawn"] = True
            return self._send_json(200, {"code": 0,
                                         "data": {"credit": 10}})
        if self.path.startswith("/billing/meter/claim-gift") or \
                self.path.startswith("/billing/meter/claim-compensation"):
            if STREAK_STATE["gift_claimed"]:
                return self._send_json(200, {"code": 31001, "msg": "already claimed"})
            STREAK_STATE["gift_claimed"] = True
            return self._send_json(200, {"code": 0, "data": {"credit": 50}})
        # 本地网络工具代跑：上游在「工具清单里有 web_search」时要求调用它一次，
        # 第二轮（工具结果已喂回）才给正常文本——用来验证网关的多轮代跑。
        tool_names = []
        for tool in payload.get("tools") or []:
            fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            tool_names.append(fn.get("name") or "")
        has_tool_result = any(
            isinstance(m, dict) and m.get("role") == "tool"
            for m in payload.get("messages") or [])
        model = payload.get("model", "m")
        if mode == "usage_on_choice":
            return self._sse([
                {"id": "chatcmpl-uc", "model": model,
                 "choices": [{"index": 0, "delta": {"content": "你好"}}],
                 "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                           "total_tokens": 5}},
                {"id": "chatcmpl-uc", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "stop"}]},
            ])
        if mode == "reasoning_only":
            return self._sse([
                {"id": "chatcmpl-ro", "model": model,
                 "choices": [{"index": 0,
                              "delta": {"reasoning_content": "think only"}}]},
                {"id": "chatcmpl-ro", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 5, "completion_tokens": 3,
                           "total_tokens": 8}},
            ])
        if mode == "reasoning_tool":
            return self._sse([
                {"id": "chatcmpl-rt", "model": model,
                 "choices": [{"index": 0, "delta": {"reasoning_content": "think "}}]},
                {"id": "chatcmpl-rt", "model": model,
                 "choices": [{"index": 0, "delta": {"content": "answer"}}]},
                {"id": "chatcmpl-rt", "model": model,
                 "choices": [{"index": 0, "delta": {"tool_calls": [{
                     "index": 0, "id": "call_rt", "type": "function",
                     "function": {"name": "get_time", "arguments": ""}}]}}]},
                {"id": "chatcmpl-rt", "model": model,
                 "choices": [{"index": 0, "delta": {"tool_calls": [{
                     "index": 0, "function": {"arguments": '{"tz":"UTC"}'}}]}}]},
                {"id": "chatcmpl-rt", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "tool_calls"}],
                 "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                           "total_tokens": 18,
                           "completion_tokens_details": {"reasoning_tokens": 2}}},
            ])
        if mode == "truncated_tool":
            return self._sse([
                {"id": "chatcmpl-cut", "model": model,
                 "choices": [{"index": 0, "delta": {"tool_calls": [{
                     "index": 0, "id": "call_cut", "type": "function",
                     "function": {"name": "get_time", "arguments": '{"tz":'}}]}}]},
                {"id": "chatcmpl-cut", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "length"}],
                 "usage": {"prompt_tokens": 9, "completion_tokens": 3,
                           "total_tokens": 12}},
            ])
        if mode == "no_usage":
            return self._sse([
                {"id": "chatcmpl-nu", "model": model,
                 "choices": [{"index": 0, "delta": {"content": "有答案"}}]},
                {"id": "chatcmpl-nu", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "stop"}]},
            ])
        if mode == "stream_error":
            return self._sse([{"error": {"message": "boom",
                                         "code": 500, "type": "server_error"}}])
        if "exec" in tool_names and not has_tool_result:
            return self._sse([
                {"id": "chatcmpl-exec", "model": model,
                 "choices": [{"index": 0, "delta": {"tool_calls": [{
                     "index": 0, "id": "call_exec", "type": "function",
                     "function": {"name": "exec", "arguments": ""}}]}}]},
                {"id": "chatcmpl-exec", "model": model,
                 "choices": [{"index": 0, "delta": {"tool_calls": [{
                     "index": 0,
                     "function": {"arguments": '{"input":"pwd"}'}}]}}]},
                {"id": "chatcmpl-exec", "model": model,
                 "choices": [{"index": 0, "delta": {},
                              "finish_reason": "tool_calls"}]},
            ])
        if "web_search" in tool_names and not has_tool_result:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            call = {"id": "chatcmpl-1", "model": payload.get("model", "m"),
                    "choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": 0, "id": "call_1", "type": "function",
                         "function": {"name": "web_search",
                                      "arguments": '{"query":"gateway test"}'}}]},
                        "finish_reason": "tool_calls"}]}
            self.wfile.write(("data: %s\n\n" % json.dumps(call)).encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        # 默认当对话端点：回 SSE 流
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        model = payload.get("model", "m")
        for piece in ("你好", "，", "世界"):
            chunk = {"id": "chatcmpl-1", "model": model,
                     "choices": [{"index": 0, "delta": {"content": piece}}]}
            self.wfile.write(("data: %s\n\n" % json.dumps(chunk, ensure_ascii=False)).encode())
            self.wfile.flush()
        final = {"id": "chatcmpl-1", "model": model,
                 "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                           "total_tokens": 18}}
        self.wfile.write(("data: %s\n\n" % json.dumps(final)).encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


