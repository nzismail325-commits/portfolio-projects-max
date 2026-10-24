# -*- coding: utf-8 -*-
"""core/protocol.py —— Responses API 与 Chat Completions 的双向翻译（代码自二开迁移）

- `responses_to_chat`：把 /v1/responses 请求体翻译成 chat 请求体（含 Codex
  自由格式工具降级、reasoning 挂载、工具调用合并）；
- `chat_to_response`：把聚合后的 chat 对象折叠成 Responses 响应对象；
- `_responses_usage`：usage 字段口径转换。

纯标准库。
"""
import json
import time

from core.tools_compat import (_new_id, parse_dsml_tool_calls,
                               preserve_request_contract_enabled)


def _flatten_content(content):
    """Flatten Responses-style content into text, or OpenAI vision parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    texts, parts = [], []
    for piece in content:
        if isinstance(piece, str):
            texts.append(piece)
            parts.append({"type": "text", "text": piece})
            continue
        if not isinstance(piece, dict):
            continue
        ptype = piece.get("type") or ""
        if ptype in ("input_text", "output_text", "text", "summary_text"):
            t = piece.get("text") or ""
            texts.append(t)
            parts.append({"type": "text", "text": t})
        elif ptype in ("input_image", "image_url", "image") or "image_url" in piece:
            url = piece.get("image_url") or piece.get("url")
            if isinstance(url, dict):
                url = url.get("url")
            if not url and piece.get("data"):
                mime = piece.get("mimeType") or piece.get("mime_type") or "image/png"
                url = f"data:{mime};base64," + piece["data"]
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})

    if any(p.get("type") == "image_url" for p in parts):
        return parts          # multimodal: keep structured parts
    return chr(10).join(t for t in texts if t)



# ---------------------------------------------------------------------------
# Codex 自由格式工具（custom/freeform）双向转译：出站降级为上游兼容的
# {input: string} function 工具，入站再还原为 Responses 规范的 custom_tool_call
# ---------------------------------------------------------------------------
CUSTOM_TOOL_HINT = (
    "This is a freeform tool. Put the COMPLETE raw payload into the single "
    "'input' string parameter, verbatim. Do not wrap it in JSON, do not wrap "
    "it in markdown code fences, do not add commentary."
)


def _is_custom_tool(tool):
    return isinstance(tool, dict) and str(tool.get("type") or "").lower() == "custom"


NAMESPACE_MAX_DEPTH = 4
_NS_SEP = "__"


def custom_tool_names(tools, _depth=0):
    """Responses 请求里声明为自由格式（custom）的工具名集合。

    递归进 namespace：新版 Codex Desktop 把自由格式工具嵌在 functions 命名
    空间里。漏掉它的后果不是「少一个名字」，而是回程被判成 function_call，
    客户端按 (name, namespace, kind) 匹配不到执行器（对齐上游 v1.7.3）。
    """
    names = set()
    if _depth > NAMESPACE_MAX_DEPTH:
        return names
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        if _is_custom_tool(t) and t.get("name"):
            names.add(str(t["name"]))
        elif str(t.get("type") or "").lower() == "namespace":
            subs = t.get("tools")
            if not isinstance(subs, list):
                subs = t.get("children")
            if not isinstance(subs, list):
                subs = t.get("functions")
            names |= custom_tool_names(subs, _depth + 1)
    return names


def additional_tools_from_input(payload):
    """从 input 数组里收集 additional_tools 条目的 tools。

    新版 Codex Desktop 0.162+ 把工具放在 input 内的
    {"type": "additional_tools", "tools": [...]} 条目里，顶层 tools 是空的。
    出站与回程都必须走同一份合并清单（对齐上游 v1.7.2）。
    """
    collected = []
    for item in payload.get("input") or []:
        if isinstance(item, dict) and item.get("type") == "additional_tools":
            sub_tools = item.get("tools")
            if isinstance(sub_tools, list):
                collected.extend(sub_tools)
    return collected


def expand_namespace_tools(tools, _depth=0):
    """把 namespace 展开成 flat function 清单，其余工具原样保留。

    上游 Chat Completions 只认 flat function，而 Responses 客户端按
    (name, namespace) 找执行器；展开时记录 name -> namespace，回程再补回。
    子工具可能在 tools / children / functions 任一栏位；同名只留第一个。
    返回 (flat_tools, name_to_namespace)。
    """
    flat = []
    mapping = {}
    seen = set()
    max_depth = max(0, int(_depth) + NAMESPACE_MAX_DEPTH)

    def collect(entry, depth, ns_name):
        if not isinstance(entry, dict) or depth > max_depth:
            return
        etype = str(entry.get("type") or "").lower()
        if etype == "namespace":
            subs = entry.get("tools")
            if not isinstance(subs, list):
                subs = entry.get("children")
            if not isinstance(subs, list):
                subs = entry.get("functions")
            if not isinstance(subs, list):
                subs = []
            child_ns = str(entry.get("name") or ns_name or "")
            for sub in subs:
                collect(sub, depth + 1, child_ns)
            return
        if ns_name and etype in ("", "function"):
            fn = entry.get("function") if isinstance(entry.get("function"), dict) else None
            if fn is None:
                fn = {
                    "name": entry.get("name"),
                    "description": entry.get("description") or "",
                    "parameters": entry.get("parameters") or entry.get("input_schema")
                                  or {"type": "object", "properties": {}},
                }
                if preserve_request_contract_enabled() and "strict" in entry:
                    fn["strict"] = entry["strict"]
            name = str(fn.get("name") or "").strip()
            if not name or name in seen:
                return
            seen.add(name)
            mapping[name] = ns_name
            flat_fn = {
                "type": "function",
                "name": name,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
            }
            if "strict" in fn:
                flat_fn["strict"] = fn["strict"]
            flat.append(flat_fn)
            return
        fn = entry.get("function") if isinstance(entry.get("function"), dict) else {}
        name = str(entry.get("name") or fn.get("name") or "").strip()
        if name:
            if name in seen:
                return
            seen.add(name)
            if ns_name:
                mapping[name] = ns_name
        flat.append(entry)

    for entry in tools or []:
        collect(entry, 0, "")
    return flat, mapping


def resolve_namespaced_name(name, mapping):
    """把模型回传的名字解析回 (bare_name, namespace)。接受 js / ns__js / ns::js。"""
    if not name:
        return name, ""
    name = str(name)
    if name in mapping:
        return name, mapping[name]
    if "::" in name:
        idx = name.find("::")
        if idx > 0:
            tail = name[idx + 2:]
            head = name[:idx]
            if tail in mapping:
                return tail, mapping[tail]
            return tail, head
    # ns__tool 用精确比对，避免 namespace 内含 '__' 时切错
    for tool, ns in mapping.items():
        if name == ns + _NS_SEP + tool:
            return tool, ns
    return name, ""


def stamp_namespace(item, mapping):
    """把模型回传的扁平工具名还原成 (name, namespace)。"""
    if not mapping or not isinstance(item, dict):
        return item
    bare, ns = resolve_namespaced_name(item.get("name"), mapping)
    if ns:
        item["name"] = bare
        item["namespace"] = ns
    return item


def apply_namespace_to_calls(output_items, mapping):
    """替 Responses 的 function_call / custom_tool_call 补上 namespace。"""
    if not mapping or not isinstance(output_items, list):
        return output_items, 0
    fixed = 0
    for item in output_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in ("function_call", "custom_tool_call"):
            continue
        if item.get("namespace"):
            continue
        bare, ns = resolve_namespaced_name(item.get("name"), mapping)
        if ns:
            item["name"] = bare
            item["namespace"] = ns
            fixed += 1
    return output_items, fixed


def _downgrade_custom_tool(tool):
    """把 Responses custom 工具改写为 Chat function 工具（单 input 参数）。"""
    desc = tool.get("description") or ""
    fmt = tool.get("format") or {}
    extra = ""
    if isinstance(fmt, dict) and fmt.get("definition"):
        extra = chr(10) + chr(10) + "Grammar:" + chr(10) + str(fmt["definition"])
    return {
        "type": "function",
        "name": tool.get("name") or "",
        "description": (desc + chr(10) + chr(10) + CUSTOM_TOOL_HINT + extra).strip(),
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "Complete raw payload for this tool, verbatim.",
                }
            },
            "required": ["input"],
        },
    }


def _tools_for_chat(tools):
    """custom 工具降级，其余原样透传。"""
    out = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        out.append(_downgrade_custom_tool(t) if _is_custom_tool(t) else t)
    return out


def _unwrap_custom_input(args):
    """从 {"input": "..."} 参数包里取出自由格式原文。"""
    if not isinstance(args, str):
        return json.dumps(args or "", ensure_ascii=False)
    try:
        parsed = json.loads(args)
    except Exception:
        return args
    if isinstance(parsed, dict):
        val = parsed.get("input")
        if isinstance(val, str):
            return val
        if val is not None:
            return json.dumps(val, ensure_ascii=False)
    if isinstance(parsed, str):
        return parsed
    return args


def responses_to_chat(payload, log=None):
    """Translate a Responses API request body into a Chat Completions body."""
    messages = []

    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})

    inp = payload.get("input")
    pending_reasoning = ""
    if isinstance(inp, str):
        messages.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        for item in inp:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
                continue
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            if itype in (None, "message", "user"):
                body = _flatten_content(item.get("content"))
                if body:
                    role = item.get("role") or "user"
                    if role == "developer":
                        role = "system"
                    # If this is assistant text and the previous message is an assistant
                    # message (e.g. from an adjacent function_call), merge them so
                    # tool_calls and text stay in one message without breaking tool sequence.
                    if role == "assistant" and messages and messages[-1].get("role") == "assistant":
                        prev = messages[-1]
                        if prev.get("content"):
                            prev["content"] = str(prev["content"]) + chr(10) + str(body)
                        else:
                            prev["content"] = body
                        if pending_reasoning and "reasoning_content" not in prev:
                            prev["reasoning_content"] = pending_reasoning
                            pending_reasoning = ""
                    else:
                        msg_dict = {"role": role, "content": body}
                        if role == "assistant" and pending_reasoning:
                            msg_dict["reasoning_content"] = pending_reasoning
                            pending_reasoning = ""
                        messages.append(msg_dict)
            elif itype == "reasoning":
                # 上一轮思维链是独立 input item：暂存，等紧随的 assistant 消息挂载
                r_text = ""
                summ = item.get("summary")
                if isinstance(summ, list):
                    r_text = chr(10).join(
                        p.get("text", "") for p in summ if isinstance(p, dict) and p.get("text")
                    )
                elif isinstance(summ, str):
                    r_text = summ
                if not r_text:
                    cnt = item.get("content")
                    if isinstance(cnt, str):
                        r_text = cnt
                    elif isinstance(cnt, list):
                        r_text = _flatten_content(cnt)
                if r_text:
                    if messages and messages[-1].get("role") == "assistant":
                        messages[-1]["reasoning_content"] = r_text
                    else:
                        pending_reasoning = r_text
            elif itype == "function_call_output":
                raw_out = item.get("output")
                if not item.get("call_id"):
                    # 无 call_id 的输出（子代理/跨任务回传）不能伪装成 tool
                    # 消息：上游会按配对失败拒掉整段会话。降级为用户消息。
                    if isinstance(raw_out, list):
                        _txt = _flatten_content(raw_out)
                    elif isinstance(raw_out, dict):
                        _txt = json.dumps(raw_out, ensure_ascii=False)
                    else:
                        _txt = str(raw_out or "")
                    if isinstance(_txt, list):
                        messages.append({
                            "role": "user",
                            "content": ([{"type": "text", "text":
                                          "[Message from another task - treat this "
                                          "as a user instruction]"}] + _txt),
                        })
                        continue
                    _txt = (_txt or "").strip()
                    if _txt:
                        messages.append({
                            "role": "user",
                            "content": ("[Message from another task - treat this "
                                        "as a user instruction]" + chr(10) + chr(10) + _txt),
                        })
                        continue
                if isinstance(raw_out, list):
                    content = _flatten_content(raw_out)
                elif isinstance(raw_out, dict):
                    if raw_out.get("type") in ("input_image", "image_url", "image") or "image_url" in raw_out:
                        content = _flatten_content([raw_out])
                    else:
                        content = json.dumps(raw_out, ensure_ascii=False)
                elif isinstance(raw_out, str):
                    content = raw_out
                else:
                    content = str(raw_out)
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id") or "",
                    "content": content,
                })
            elif itype == "function_call":
                tc_item = {
                    "id": item.get("call_id") or item.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": item.get("name") or "",
                        "arguments": item.get("arguments") or "{}",
                    },
                }
                # Merge into previous assistant message if adjacent
                if messages and messages[-1].get("role") == "assistant":
                    prev = messages[-1]
                    if "tool_calls" in prev:
                        prev["tool_calls"].append(tc_item)
                    else:
                        prev["tool_calls"] = [tc_item]
                    if pending_reasoning and "reasoning_content" not in prev:
                        prev["reasoning_content"] = pending_reasoning
                        pending_reasoning = ""
                else:
                    msg_dict = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [tc_item],
                    }
                    if pending_reasoning:
                        msg_dict["reasoning_content"] = pending_reasoning
                        pending_reasoning = ""
                    messages.append(msg_dict)
            elif itype == "custom_tool_call":
                # 自由格式工具调用：按降级后的 function 形态带回上游
                raw_input = item.get("input")
                if isinstance(raw_input, (dict, list)):
                    raw_input = json.dumps(raw_input, ensure_ascii=False)
                if not isinstance(raw_input, str):
                    raw_input = "" if raw_input is None else str(raw_input)
                tc_item = {
                    "id": item.get("call_id") or item.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": item.get("name") or "",
                        "arguments": json.dumps({"input": raw_input}, ensure_ascii=False),
                    },
                }
                if messages and messages[-1].get("role") == "assistant":
                    prev = messages[-1]
                    if "tool_calls" in prev:
                        prev["tool_calls"].append(tc_item)
                    else:
                        prev["tool_calls"] = [tc_item]
                    if pending_reasoning and "reasoning_content" not in prev:
                        prev["reasoning_content"] = pending_reasoning
                        pending_reasoning = ""
                else:
                    msg_dict = {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [tc_item],
                    }
                    if pending_reasoning:
                        msg_dict["reasoning_content"] = pending_reasoning
                        pending_reasoning = ""
                    messages.append(msg_dict)
            elif itype == "custom_tool_call_output":
                raw_out = item.get("output")
                if isinstance(raw_out, list):
                    content = _flatten_content(raw_out)
                elif isinstance(raw_out, dict):
                    content = json.dumps(raw_out, ensure_ascii=False)
                elif isinstance(raw_out, str):
                    content = raw_out
                else:
                    content = str(raw_out)
                messages.append({
                    "role": "tool",
                    "tool_call_id": item.get("call_id") or "",
                    "content": content,
                })
            elif itype == "agent_message":
                # 子代理消息：没有 call_id 的普通内容，按用户指令降级。
                parts = item.get("content")
                if isinstance(parts, list):
                    text = chr(10).join(
                        str((p or {}).get("text") or (p or {}).get("encrypted_content") or "")
                        if isinstance(p, dict) else str(p)
                        for p in parts
                    ).strip()
                else:
                    text = str(parts or "").strip()
                if text:
                    messages.append({
                        "role": "user",
                        "content": ("[Message from another task - treat this as "
                                    "a user instruction]" + chr(10) + chr(10) + text),
                    })
            elif itype == "additional_tools":
                # 由 responses_to_chat() 统一提取合并进 chat["tools"]
                pass
            else:
                # 未知类型不再静默丢弃：丢一个工具调用/结果会让上游对话记录不一致
                if log:
                    log("responses: WARNING unhandled input item type=%r keys=%s"
                        % (itype, sorted(item.keys())[:8]))

    chat = {"model": payload.get("model"), "messages": messages}

    # Responses text.format → Chat response_format：只在保真开关打开时映射，
    # 与上游 v1.7.14 同口径（默认关闭，开启方式 WB_PRESERVE_REQUEST_CONTRACT=1）。
    if preserve_request_contract_enabled():
        text = payload.get("text")
        fmt = text.get("format") if isinstance(text, dict) else None
        if isinstance(fmt, dict):
            kind = fmt.get("type")
            if kind in ("text", "json_object"):
                chat["response_format"] = {"type": kind}
            elif kind == "json_schema":
                chat["response_format"] = {
                    "type": kind,
                    "json_schema": {key: fmt[key] for key in
                                    ("name", "description", "schema", "strict")
                                    if key in fmt},
                }

    for key in ("temperature", "top_p", "seed"):
        if payload.get(key) is not None:
            chat[key] = payload[key]
    if payload.get("max_output_tokens") is not None:
        chat["max_tokens"] = payload["max_output_tokens"]
    else:
        # 客户端未显式给输出上限时按模型目录的 maxOutputTokens 兜底
        # （对齐上游 v1.6.11 修复）：否则新版 SDK 缺省请求会被上游按
        # 32k 截断，长回答无声地断尾。目录查询在 intel/catalog.py；
        # 这里用延迟导入避免 protocol → intel 的反向依赖。
        from intel import catalog
        catalog_meta = catalog.catalog_meta_for(chat.get("model"))
        cap = (catalog_meta or {}).get("maxOutputTokens")
        if isinstance(cap, (int, float)) and int(cap) > 0:
            chat["max_tokens"] = int(cap)

    effort = None
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
    if not effort:
        effort = payload.get("reasoning_effort")
    if effort:
        chat["reasoning_effort"] = effort

    # 合并顶层 tools 与 input 里的 additional_tools（Codex Desktop 0.162+），
    # 再把 namespace 展开成上游认得的 flat function。回程需要的映射放在
    # _namespace_map，由路由层取走（出站前会被内部键清洗掉）。
    raw_tools = []
    if isinstance(payload.get("tools"), list):
        raw_tools.extend(payload["tools"])
    raw_tools.extend(additional_tools_from_input(payload))
    if raw_tools:
        flat_tools, ns_map = expand_namespace_tools(raw_tools)
        chat["tools"] = _tools_for_chat(flat_tools)
        chat["_namespace_map"] = ns_map
    if payload.get("tool_choice"):
        chat["tool_choice"] = payload["tool_choice"]
    if payload.get("parallel_tool_calls") is not None:
        chat["parallel_tool_calls"] = payload["parallel_tool_calls"]
    return chat


def _responses_usage(u):
    if not u:
        return None
    det = u.get("completion_tokens_details") or {}
    pdet = u.get("prompt_tokens_details") or {}
    return {
        "input_tokens": u.get("prompt_tokens") or 0,
        "input_tokens_details": {
            "cached_tokens": u.get("prompt_cache_hit_tokens")
            or det.get("cached_tokens") or pdet.get("cached_tokens") or 0,
        },
        "output_tokens": u.get("completion_tokens") or 0,
        "output_tokens_details": {"reasoning_tokens": det.get("reasoning_tokens") or 0},
        "total_tokens": u.get("total_tokens") or 0,
    }


def reasoning_only_response(result):
    """Responses 对象只有 reasoning、没有正文/工具调用时视为失败。

    DeepSeek 偶尔把整轮预算花在思考上、正文为空；标 completed 会让客户端
    以为回合正常结束（主上游 #508）。
    """
    obj = result or {}
    output = obj.get("output") or []
    text = obj.get("output_text") or ""
    has_calls = any(
        isinstance(item, dict)
        and item.get("type") in ("function_call", "custom_tool_call",
                                 "web_search_call")
        for item in output)
    has_reasoning = any(
        isinstance(item, dict) and item.get("type") == "reasoning"
        for item in output)
    return (not str(text).strip() and has_reasoning and not has_calls
            and obj.get("status") != "incomplete")


def chat_to_response(chat_obj, model, custom_names=None, request_meta=None,
                     namespace_map=None, sources=None):
    """Fold a Chat Completions object into a Responses API response object.

    custom_names 是客户端声明为自由格式（custom）的工具名：命中时把调用
    还原为 custom_tool_call，否则 Codex 这类客户端认不出工具调用。
    request_meta 回显客户端本轮声明的工具能力（tools / tool_choice /
    parallel_tool_calls），不能硬编码成客户端没要的值。
    namespace_map 把扁平工具名还原成 (name, namespace)。
    sources 是网关代跑网路工具时收集到的来源：只在正文真的引用了某个网址时
    才标注 url_citation（模型自己编的链接不算引用）。
    """
    custom_names = custom_names or set()
    choice = (chat_obj.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""

    output = []
    if reasoning:
        output.append({
            "id": _new_id("rs_"),
            "type": "reasoning",
            "status": "completed",
            "summary": [{"type": "summary_text", "text": reasoning}],
        })
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        call_id = tc.get("id") or _new_id("call_")
        name = fn.get("name") or ""
        if name and name in custom_names:
            output.append({
                "id": _new_id("ctc_"),
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "input": _unwrap_custom_input(fn.get("arguments") or ""),
            })
        else:
            output.append({
                "id": _new_id("fc_"),
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": name,
                "arguments": fn.get("arguments") or "{}",
            })
    # DeepSeek DSML tool calls fallback
    if not (msg.get("tool_calls")):
        dsml_calls, clean_t = parse_dsml_tool_calls(text)
        if dsml_calls:
            for dc in dsml_calls:
                output.append({
                    "id": _new_id("fc_"),
                    "type": "function_call",
                    "status": "completed",
                    "call_id": dc.get("id") or _new_id("call_"),
                    "name": dc.get("name") or "",
                    "arguments": dc.get("arguments") or "{}",
                })
            text = clean_t
    if text or not output:
        annotations = []
        if text and sources:
            # 延迟导入：protocol 是被 core.web_tools 依赖的底层模块
            from core import web_tools
            annotations = web_tools.build_citations(text, sources)
        output.append({
            "id": _new_id("msg_"),
            "type": "message",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text,
                         "annotations": annotations}] if text else [],
        })

    finish = choice.get("finish_reason") or "stop"
    if namespace_map:
        output, _fixed = apply_namespace_to_calls(output, namespace_map)
    meta = request_meta or {}
    obj = {
        "id": _new_id("resp_"),
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed" if finish != "length" else "incomplete",
        "model": model,
        "output": output,
        "output_text": text,
        "parallel_tool_calls": meta.get("parallel_tool_calls", True),
        "tool_choice": meta.get("tool_choice", "auto"),
        "tools": meta.get("tools") or [],
        "metadata": {},
    }
    u = _responses_usage(chat_obj.get("usage"))
    if u:
        obj["usage"] = u
    if finish == "length":
        obj["incomplete_details"] = {"reason": "max_output_tokens"}
    return obj


