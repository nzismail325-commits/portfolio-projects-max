# -*- coding: utf-8 -*-
"""integrations/zcode_anthropic.py —— ZCode 上游 Anthropic Messages 协议翻译

zcode 上游（coding-plan 与 start-plan 统一）是 Anthropic Messages 协议：
POST {base}/v1/messages + anthropic-version: 2023-06-01，SSE 事件流。

本模块只做纯函数/纯状态机翻译，不发请求：
- to_anthropic()      OpenAI 请求体 → Anthropic 请求体
- create_sse_bridge() Anthropic SSE 事件 → 统一 emit 事件
  （delta / usage / finish / error，由 zcode.py 的流对象转成 OpenAI chunk）
"""
import json


def _to_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    out = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            out.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            image = part.get("image_url") or {}
            url = str(image.get("url") or "") if isinstance(image, dict) else ""
            if not url:
                continue
            match = None
            if url.startswith("data:"):
                head, _, payload = url.partition(",")
                match = (head[5:].replace(";base64", ""), payload) \
                    if head.endswith(";base64") else None
            if match:
                out.append({"type": "image", "source": {
                    "type": "base64", "media_type": match[0], "data": match[1]}})
            else:
                out.append({"type": "image", "source": {"type": "url", "url": url}})
    return out


def _tool_result_block(message):
    return {
        "type": "tool_result",
        "tool_use_id": str(message.get("tool_call_id") or message.get("toolCallId") or ""),
        "content": _to_blocks(message.get("content")),
    }


def _max_tokens(body, default):
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        try:
            value = float(body.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return int(value)
    try:
        value = int(default)
        return value if value > 0 else 8192
    except (TypeError, ValueError):
        return 8192


def to_anthropic(model, body, default_max_tokens=8192):
    """OpenAI body → Anthropic body（system 抽出、tool 配对、thinking 归并）。"""
    body = body or {}
    out = {"model": str(model or ""), "messages": [], "stream": True}
    systems = []
    for message in body.get("messages") if isinstance(body.get("messages"), list) else []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        if role in ("system", "developer"):
            if isinstance(message.get("content"), str):
                text = message["content"]
            else:
                text = "\n".join(block["text"] for block in _to_blocks(message.get("content"))
                                 if block.get("type") == "text")
            if text:
                systems.append(text)
            continue
        if role == "tool":
            block = _tool_result_block(message)
            last = out["messages"][-1] if out["messages"] else None
            if last and last.get("role") == "user" and isinstance(last.get("content"), list):
                last["content"].append(block)
            else:
                out["messages"].append({"role": "user", "content": [block]})
            continue
        if role == "assistant":
            blocks = _to_blocks(message.get("content"))
            reasoning = message.get("reasoning_content")
            merged = []
            if isinstance(reasoning, str) and reasoning:
                merged.append({"type": "thinking", "thinking": reasoning, "signature": ""})
            merged.extend(blocks)
            calls = message.get("tool_calls")
            for call in calls if isinstance(calls, list) else []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except Exception:
                    args = {}
                merged.append({"type": "tool_use", "id": str(call.get("id") or ""),
                               "name": str(function.get("name") or ""), "input": args})
            out["messages"].append({"role": "assistant",
                                    "content": merged or [{"type": "text", "text": ""}]})
            continue
        if role == "user":
            blocks = _to_blocks(message.get("content"))
            out["messages"].append({"role": "user",
                                    "content": blocks or [{"type": "text", "text": ""}]})
    # Anthropic 会话必须以 user 开头：客户端裁剪过的会话可能首条是 assistant
    if out["messages"] and out["messages"][0].get("role") != "user":
        out["messages"].insert(0, {"role": "user", "content": [{"type": "text",
                                                               "text": "(continue)"}]})
    if systems:
        out["system"] = "\n\n".join(systems)
    out["max_tokens"] = _max_tokens(body, default_max_tokens)
    if isinstance(body.get("temperature"), (int, float)):
        out["temperature"] = body["temperature"]
    if isinstance(body.get("top_p"), (int, float)):
        out["top_p"] = body["top_p"]
    stop = body.get("stop")
    if isinstance(stop, str) and stop:
        out["stop_sequences"] = [stop]
    elif isinstance(stop, list) and stop:
        out["stop_sequences"] = [str(item) for item in stop if item][:8]
    tools = []
    for tool in body.get("tools") if isinstance(body.get("tools"), list) else []:
        function = (tool.get("function") if isinstance(tool, dict)
                    and tool.get("type") == "function"
                    and isinstance(tool.get("function"), dict) else tool)
        if not isinstance(function, dict) or not isinstance(function.get("name"), str) \
                or not function["name"]:
            continue
        parameters = function.get("parameters")
        tools.append({
            "name": function["name"],
            "description": function.get("description") if isinstance(
                function.get("description"), str) else "",
            "input_schema": parameters if isinstance(parameters, dict)
            else {"type": "object", "properties": {}},
        })
    if tools:
        out["tools"] = tools
    choice = body.get("tool_choice")
    if choice is not None and out.get("tools"):
        if choice in ("auto", "none"):
            out["tool_choice"] = {"type": choice}
        elif choice == "required":
            out["tool_choice"] = {"type": "any"}
        elif isinstance(choice, dict) and (choice.get("function") or {}).get("name"):
            out["tool_choice"] = {"type": "tool",
                                  "name": str(choice["function"]["name"])}
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        if thinking.get("type") == "enabled":
            out["thinking"] = {"type": "enabled", "budget_tokens": int(
                thinking.get("budget_tokens") or thinking.get("budgetTokens") or 2048)}
        elif thinking.get("type") == "disabled":
            # GLM-5.3 对 disabled/none/minimal 必 400 code 1210：折叠成最低档
            out["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    elif body.get("reasoning_effort") == "off":
        out["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    elif isinstance(body.get("reasoning_effort"), str) and body["reasoning_effort"]:
        budget = {"minimal": 1024, "low": 2048, "medium": 4096,
                  "high": 8192, "xhigh": 16384, "max": 24576}
        out["thinking"] = {"type": "enabled",
                           "budget_tokens": budget.get(body["reasoning_effort"], 4096)}
    if out.get("thinking"):
        # 扩展思考与采样参数并存会被上游拒绝
        out.pop("temperature", None)
        out.pop("top_p", None)
    return out


def _finish_reason(reason):
    text = str(reason or "")
    if text in ("end_turn", "stop_sequence"):
        return "stop"
    if text == "max_tokens":
        return "length"
    if text == "tool_use":
        return "tool_calls"
    return text or "stop"


def create_sse_bridge(emit):
    """Anthropic SSE → emit(delta/usage/finish/error)；result 收集 planLimit/sawError。"""
    tool_acc = {}
    next_tool_index = [0]
    state = {
        "input": 0, "output": 0, "cache_read": 0, "cache_creation": 0,
        "usage_extra": {}, "stop_reason": "", "planLimit": False, "sawError": False,
    }
    base_keys = {"input_tokens", "output_tokens", "prompt_tokens",
                 "completion_tokens", "total_tokens"}

    def emit_tool_head(index):
        acc = tool_acc.get(index)
        if not acc or acc.get("emitted"):
            return
        acc["emitted"] = True
        call = {"index": acc["toolIndex"], "type": "function",
                "function": {"name": acc["name"], "arguments": ""}}
        if acc["id"]:
            call["id"] = acc["id"]
        emit({"type": "delta", "delta": {"tool_calls": [call]}})

    def on_event(event, raw):
        try:
            data = json.loads(raw)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        kind = str(data.get("type") or event or "")
        if kind == "message_start":
            usage = (data.get("message") or {}).get("usage") or {}
            if isinstance(usage, dict):
                state["input"] = int(usage.get("input_tokens")
                                     or usage.get("prompt_tokens") or state["input"])
                for key, value in usage.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool) \
                            and key not in base_keys:
                        state["usage_extra"][key] = value
                state["cache_read"] = int(usage.get("cache_read_input_tokens")
                                          or state["cache_read"])
                state["cache_creation"] = int(usage.get("cache_creation_input_tokens")
                                              or state["cache_creation"])
            return
        if kind == "content_block_start":
            index = int(data.get("index") or 0)
            block = data.get("content_block") or {}
            if block.get("type") == "tool_use":
                tool_index = next_tool_index[0]
                next_tool_index[0] += 1
                tool_acc[index] = {
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "emitted": False, "toolIndex": tool_index,
                }
            return
        if kind == "content_block_delta":
            index = int(data.get("index") or 0)
            delta = data.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                emit({"type": "delta", "delta": {"content": delta["text"]}})
            elif delta.get("type") == "thinking_delta" and delta.get("thinking"):
                emit({"type": "delta",
                      "delta": {"reasoning_content": delta["thinking"]}})
            elif delta.get("type") == "input_json_delta" and delta.get("partial_json"):
                acc = tool_acc.get(index)
                if acc:
                    emit_tool_head(index)
                    emit({"type": "delta", "delta": {"tool_calls": [{
                        "index": acc["toolIndex"],
                        "function": {"arguments": delta["partial_json"]},
                    }]}})
            return
        if kind == "content_block_stop":
            acc = tool_acc.get(int(data.get("index") or 0))
            if acc and not acc.get("emitted"):
                # 无参数工具也必须让客户端看到调用头
                emit_tool_head(int(data.get("index") or 0))
            return
        if kind == "message_delta":
            usage = data.get("usage") or {}
            if isinstance(usage, dict):
                state["output"] = int(usage.get("output_tokens")
                                      or usage.get("completion_tokens")
                                      or state["output"])
                state["input"] = int(usage.get("input_tokens")
                                     or usage.get("prompt_tokens") or state["input"])
                for key, value in usage.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool) \
                            and key not in base_keys:
                        state["usage_extra"][key] = value
                state["cache_read"] = int(usage.get("cache_read_input_tokens")
                                          or state["cache_read"])
                state["cache_creation"] = int(
                    usage.get("cache_creation_input_tokens") or state["cache_creation"])
            stop = (data.get("delta") or {}).get("stop_reason")
            if stop:
                state["stop_reason"] = stop
            return
        if kind == "message_stop":
            if state["input"] or state["output"] or state["cache_read"]:
                prompt = state["input"] + state["cache_read"] + state["cache_creation"]
                usage = dict(state["usage_extra"])
                usage.update({
                    "prompt_tokens": prompt,
                    "completion_tokens": state["output"],
                    "total_tokens": prompt + state["output"],
                })
                if state["cache_read"] or state["cache_creation"]:
                    usage["prompt_tokens_details"] = {
                        "cached_tokens": state["cache_read"]}
                    usage["cache_read_input_tokens"] = state["cache_read"]
                    usage["cache_creation_input_tokens"] = state["cache_creation"]
                emit({"type": "usage", "usage": usage})
            emit({"type": "finish", "reason": _finish_reason(state["stop_reason"])})
            return
        if kind == "error":
            error = data.get("error") or {}
            message = str(error.get("message") or data.get("message") or "上游错误")
            try:
                code = int(error.get("code") or data.get("code") or 0)
            except (TypeError, ValueError):
                code = 0
            quota = (code in (1005, 1113)
                     or any(marker in message.lower() for marker in
                            ("insufficient", "quota", "balance", "余额", "额度", "recharge")))
            status = 402 if quota else (502 if code == 3007 else
                                        (429 if 3002 <= code <= 3010 else 502))
            if quota:
                state["planLimit"] = True
            state["sawError"] = True
            emit({"type": "error", "status": status, "code": code, "message": message})

    return {"onEvent": on_event, "result": state}
