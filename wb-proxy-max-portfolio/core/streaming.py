# -*- coding: utf-8 -*-
"""core/streaming.py —— 流式聚合与 Responses 流式翻译（代码自二开迁移）

- `aggregate_stream`：把 chat.completion 的 SSE 流折叠成单个非流式对象；
- `stream_responses_events`：把 chat 流实时翻译成 Responses API 事件流；
- 流清洗与记账兜底（strip_data_prefix / clean_chunk / usage 估算）。

纯标准库。
"""
import json
import threading
import time
import uuid

from core.protocol import (_responses_usage, _unwrap_custom_input,
                           apply_namespace_to_calls, reasoning_only_response,
                           stamp_namespace)
from core.tools_compat import _new_id, parse_dsml_tool_calls, ANTH_CALLS_RE, DSML_CALLS_RE
from core import web_tools

#: 上游网关在 delta 里补的空噪声字段，透传前删掉
NOISE_KEYS = ("extra_fields", "refusal", "reasoning_content")


def strip_data_prefix(line):
    line = line.strip()
    # SSE comment / heartbeat / keepalive / empty line
    if not line or line.startswith(":"):
        return ""
    while line.startswith("data:"):
        line = line[5:].strip()
    # Handle possible "data: : heartbeat"
    if not line or line.startswith(":"):
        return ""
    return line


def iter_sse_chunks(raw_iter, with_done=False):
    """SSE 行迭代器：剥 data: 前缀、跳过注释行，产出 (data, obj)。

    obj 为 None 表示该行不是合法 JSON（消费方自行决定丢弃或透传）。
    with_done=True 时把 [DONE] 作为 ("[DONE]", None) 产出——截断判定需要
    知道上游是否真的把流收完（对齐上游 v1.7.14 的 saw_done）。
    """
    for line in raw_iter:
        data = strip_data_prefix(line.decode("utf-8", "replace"))
        if not data:
            continue
        if data == "[DONE]":
            if with_done:
                yield data, None
            continue
        try:
            obj = json.loads(data)
        except Exception:
            obj = None
        yield data, obj


def is_truncated_arguments(raw):
    """非空但无法解析的 tool arguments 视为断流截断。

    空/空白是合法的无参调用；任何能解析的 JSON（含 null/标量/数组）都是
    模型自己的输出，交给客户端校验——只有非空且解析失败才算截断。
    """
    if not isinstance(raw, str):
        return False
    trimmed = raw.strip()
    if not trimmed:
        return False
    try:
        json.loads(trimmed)
        return False
    except Exception:
        return True


def estimate_tokens(text):
    """按字符近似估算一段文本的 token 数（对齐上游 v1.4.5 断流兜底）。

    CJK 字符约 1 字 1 token，其他按 3.6 字符 1 token 粗算——只在
    上游没给 usage 时用于兜底记账，精确度要求不高。
    """
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')
    other = len(text) - cjk
    return cjk + max(1, int(other / 3.6))


def usage_outgrew(old, new):
    """新帧的用量是否比已记帧更大（对齐上游 v1.4.5 流式记账）。

    上游偶尔在流中间发全 0 占位帧；只认 total_tokens 单调增长的帧，
    最后一个非空 usage 不再无条件覆盖更早的真实帧。
    """
    if not isinstance(new, dict):
        return False
    if not isinstance(old, dict):
        return True
    return (new.get("total_tokens") or 0) >= (old.get("total_tokens") or 0)


def estimated_usage_from_text(streamed_text):
    """断流兜底：按已流出的文本合成一份近似 usage（对齐上游 v1.4.5）。

    上游断流时最终 usage 帧到不了，按已流出内容估算输入输出——账面
    略有出入也比整行丢掉好（请求次数、成功率、日限额折算都在用这行）。
    """
    full = "".join(streamed_text)
    if not full:
        return None
    comp = estimate_tokens(full)
    prompt = max(1, comp // 2)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": comp,
        "total_tokens": prompt + comp,
        "completion_tokens_details": {"reasoning_tokens": 0},
        "prompt_tokens_details": {"cached_tokens": 0},
    }


def record_stream_usage(ctx, model, usage, *, t_start, first_ms=None, fp=None,
                        account=None, realm="", stream=True):
    """统一的用量落账：算墙钟与生成耗时后调 ctx.usage.record（全站唯一记账口径）。"""
    wall = int((time.time() - t_start) * 1000)
    ctx.usage.record(model, usage, stream=stream, elapsed_ms=wall,
                     ttft_ms=first_ms,
                     gen_ms=(wall - first_ms) if first_ms is not None else None,
                     fp=fp, account=account, realm=realm)


def clean_chunk(raw):
    """Drop the empty noise fields the WorkBuddy gateway pads deltas with."""
    try:
        obj = json.loads(raw)
    except Exception:
        return raw
    changed = False
    for choice in obj.get("choices") or []:
        # 上游偶发把中间分片的 finish_reason 写成空串；严格客户端（Rust/Go）
        # 会当成结束标记提前断流，规范化为 null（对齐上游 v1.7.2）。
        if isinstance(choice, dict) and choice.get("finish_reason") == "":
            choice["finish_reason"] = None
            changed = True
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        # 空占位是 {"name":"","arguments":""}：非空 dict 按真值判删不掉，
        # 改为显式检查 name（上游对 function_call:null 保留该键不删，照抄）。
        fc = delta.get("function_call")
        if fc is not None:
            fc_empty = False
            if isinstance(fc, dict):
                fc_empty = not fc.get("name")
            else:
                fc_empty = not fc
            if fc_empty:
                delta.pop("function_call", None)
                changed = True
        if isinstance(delta.get("tool_calls"), list) and not delta["tool_calls"]:
            delta.pop("tool_calls")
            changed = True
        for key in NOISE_KEYS:
            if key in delta and not delta.get(key):
                delta.pop(key)
                changed = True
        if not delta and not choice.get("finish_reason"):
            return ""
    return json.dumps(obj, ensure_ascii=False) if changed else raw


def _strip_empty_fc(obj):
    """递归剔除空 function_call 占位（Responses/chat 通用）：name 为空即删。"""
    changed = False
    if isinstance(obj, dict):
        fc = obj.get("function_call")
        if isinstance(fc, dict) and not fc.get("name"):
            obj.pop("function_call", None)
            changed = True
        tc = obj.get("tool_calls")
        if isinstance(tc, list) and not tc:
            obj.pop("tool_calls", None)
            changed = True
        for v in list(obj.values()):
            if _strip_empty_fc(v):
                changed = True
    elif isinstance(obj, list):
        for v in obj:
            if _strip_empty_fc(v):
                changed = True
    return changed


def clean_responses_frame(frame):
    """清洗 Responses SSE 帧（bytes）：只改写 data 行 JSON，event 行原样保留。

    解析失败原样返回，不破坏未知格式。
    """
    if not frame:
        return frame
    try:
        text = frame.decode("utf-8")
    except Exception:
        return frame
    out, changed = [], False
    for line in text.splitlines():
        st = line.strip()
        if st.startswith("data:"):
            payload = st[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    obj = json.loads(payload)
                    if _strip_empty_fc(obj):
                        line = "data: " + json.dumps(obj, ensure_ascii=False)
                        changed = True
                except Exception:
                    pass
        out.append(line)
    return ("\n".join(out) + "\n\n").encode("utf-8") if changed else frame


SSE_HEARTBEAT_SECONDS = 15.0


class SSEHeartbeat(object):
    """在上游静默期写 SSE 注释帧，让客户端知道连接还活着。

    只在「阻塞读之前」检查一次的心跳覆盖不到它要防的那段静默：读本身就在
    阻塞。这个守护线程与业务写入共用同一把锁，所以注释帧永远不会插进一个
    JSON/SSE 帧中间（对齐上游 v1.7.31 #578）。
    """

    def __init__(self, write, interval=SSE_HEARTBEAT_SECONDS):
        self._write = write
        self._interval = max(0.05, float(interval))
        self._lock = threading.RLock()
        self._last_write_at = time.monotonic()
        self._stop = threading.Event()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="wb-sse-heartbeat", daemon=True)
        self._thread.start()

    def write(self, data):
        if not data:
            return
        with self._lock:
            if self._closed:
                return
            self._write(data)
            self._last_write_at = time.monotonic()

    def _run(self):
        tick = min(0.1, self._interval / 4.0)
        while not self._stop.wait(tick):
            with self._lock:
                if self._closed:
                    return
                if time.monotonic() - self._last_write_at < self._interval:
                    continue
                try:
                    self._write(b": keepalive\n\n")
                    self._last_write_at = time.monotonic()
                except Exception:
                    self._closed = True
                    return

    def close(self):
        with self._lock:
            self._closed = True
        self._stop.set()
        self._thread.join(timeout=max(0.1, self._interval))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def chat_stream_error_frame(message, code="upstream_stream_error"):
    """Terminal SSE error frame for a chat stream that died mid-body.

    `data: [DONE]` means the turn finished normally; sending it after an
    upstream read error hides the truncation from every client that treats it
    as the end of the answer. Send an error object and close instead.
    """
    payload = {"error": {"message": str(message), "type": "upstream_error",
                         "param": None, "code": code}}
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


def responses_stream_error_frame(message, code="upstream_stream_error"):
    """The Responses-API spelling of the same terminal error event."""
    payload = {"type": "error", "code": code, "message": str(message),
               "param": None, "sequence_number": 0}
    return ("event: error\ndata: " + json.dumps(payload, ensure_ascii=False)
            + "\n\n").encode("utf-8")


def aggregate_stream(raw_iter, model, resp_id):
    """Fold an SSE stream into one non-streaming chat.completion object."""
    content, reasoning, finish = [], [], "stop"
    tool_calls_map = {}
    usage = None
    error = None
    saw_done = False
    started = time.time()
    first_chunk_at = None
    for data, chunk in iter_sse_chunks(raw_iter, with_done=True):
        if data == "[DONE]":
            saw_done = True
            continue
        if chunk is None:
            continue
        if isinstance(chunk.get("error"), dict):
            # 渠道适配器会先吐错误帧、随后抛 HTTPError 做治理；这里只记下
            # 错误内容，继续迭代让那个异常照常抛出，不能把状态码吞掉。
            error = chunk["error"]
            continue
        if first_chunk_at is None:
            first_chunk_at = time.time()
        # 响应 id 由网关生成：上游 id 可能跨响应复用，对客户端只是不透明标识
        if chunk.get("model"):
            model = chunk["model"]
        if chunk.get("usage") and usage_outgrew(usage, chunk["usage"]):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
            if delta.get("reasoning_content"):
                reasoning.append(delta["reasoning_content"])
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index")
                if idx is None:
                    idx = len(tool_calls_map)
                fn = tc.get("function") or {}
                call_id = tc.get("id")
                fn_name = fn.get("name") or ""
                fn_args = fn.get("arguments") or ""
                if idx not in tool_calls_map:
                    tool_calls_map[idx] = {
                        "id": call_id or _new_id("call_"),
                        "type": tc.get("type") or "function",
                        "function": {
                            "name": fn_name,
                            "arguments": fn_args,
                        }
                    }
                else:
                    entry = tool_calls_map[idx]
                    if call_id:
                        entry["id"] = call_id
                    if fn_name:
                        entry["function"]["name"] = (entry["function"]["name"] or "") + fn_name
                    if fn_args:
                        entry["function"]["arguments"] = (entry["function"]["arguments"] or "") + fn_args
            fc = delta.get("function_call")
            # 上游会在流末尾发 function_call:{"name":"","arguments":""} 占位，
            # 空 dict 按真值判会删不掉，凭空造出 tool_call 并把 finish 改成
            # tool_calls，导致严格客户端死等。故 name 为空即视为占位跳过。
            fc_is_empty = (not isinstance(fc, dict)) or (not fc.get("name"))
            if fc and isinstance(fc, dict) and not fc_is_empty:
                idx = 0
                if idx not in tool_calls_map:
                    tool_calls_map[idx] = {
                        "id": _new_id("call_"),
                        "type": "function",
                        "function": {
                            "name": fc.get("name") or "",
                            "arguments": fc.get("arguments") or "",
                        }
                    }
                else:
                    entry = tool_calls_map[idx]
                    if fc.get("name") and not entry["function"]["name"]:
                        entry["function"]["name"] = fc["name"]
                    if fc.get("arguments"):
                        entry["function"]["arguments"] += fc["arguments"]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
    message = {"role": "assistant", "content": "".join(content)}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    # 二次防御：剔除无函数名的空 tool_call（上游以数组形式发空占位也不泄漏）。
    if tool_calls_map:
        tool_calls_map = {
            k: v for k, v in tool_calls_map.items()
            if (v.get("function") or {}).get("name")
        }
    # max_tokens 或断连会把最后一个调用的参数写成半截 JSON；不能原样交给
    # 客户端（解析必失败）。只丢非空且不可解析的，无参调用照常保留。
    if tool_calls_map and (finish == "length" or not saw_done):
        tool_calls_map = {
            k: v for k, v in tool_calls_map.items()
            if not is_truncated_arguments((v.get("function") or {}).get("arguments"))
        }
    if tool_calls_map:
        ordered_tcs = [tool_calls_map[k] for k in sorted(tool_calls_map.keys())]
        message["tool_calls"] = ordered_tcs
        if finish in ("stop", None):
            finish = "tool_calls"
    elif finish == "tool_calls":
        # 占位被全部过滤掉，无实际工具调用，降级为正常结束，防止客户端无限挂起等待
        finish = "stop"
    out = {
        "id": resp_id or ("chatcmpl-wb-" + uuid.uuid4().hex[:16]),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }
    if usage:
        out["usage"] = usage
    if error:
        out["error"] = error
    out["elapsed_ms"] = int((time.time() - started) * 1000)
    out["first_chunk_at"] = first_chunk_at
    return out


def stream_responses_events(upstream, model, holder):
    """Yield Responses-API SSE frames translated from chat-completions chunks.

    holder 契约（与上游 v1.7.12 对齐）：
      custom_names       客户端声明为自由格式（custom）的工具名集合
      base_body          本轮请求体；带 `_web_tools` 标记时，同名的
                         web_search / web_fetch 呼叫由网关代跑、不转发
      web_sources        已代跑工具收集到的可引用来源
      suppress_lifecycle 第二轮起为 True：不再重发 response.created
      internal_calls     本轮捕获到的代跑呼叫 [{"name", "arguments"}]
      suppress_completion 本轮有代跑呼叫：不发 response.completed，
                         由调用方喂回结果后重跑
    """
    resp_id, msg_id, rs_id = _new_id("resp_"), _new_id("msg_"), _new_id("rs_")
    created = int(time.time())
    seq = 0
    text_parts, reason_parts = [], []
    outputs = []
    reason_index = None
    msg_index = None
    finish = "stop"
    usage = None
    tool_calls_map = {}
    # DSML 流式缓冲：疑似 DSML 标记先扣住不吐，杜绝原始标记提前泄露给客户端
    text_buffer = ""
    dsml_tool_calls = []
    saw_done = False
    stream_failed = False
    custom_names = set(holder.get("custom_names") or ())
    ns_map = holder.get("namespace_map") or {}
    #: 回显客户端本轮声明的工具能力，不能硬编码成它没要的值
    meta = holder.get("request_meta") or {}
    #: 本请求的网路工具是否由网关代跑（只看请求体标记，不重读开关）
    own_web_tools = web_tools.active(holder.get("base_body"))
    #: 捕获到的代跑呼叫：按工具调用 index 聚合参数分片
    internal_calls = {}

    def resp_obj(status):
        obj = {
            "id": resp_id,
            "object": "response",
            "created_at": created,
            "status": status,
            "model": model,
            "output": [o for o in outputs if o],
            "output_text": "".join(text_parts),
            "parallel_tool_calls": meta.get("parallel_tool_calls", True),
            "tool_choice": meta.get("tool_choice", "auto"),
            "tools": meta.get("tools") or [],
            "metadata": {},
        }
        u = _responses_usage(usage)
        if u:
            obj["usage"] = u
        if ns_map:
            obj["output"], _fixed = apply_namespace_to_calls(obj.get("output") or [], ns_map)
        return obj

    def ev(etype, payload):
        nonlocal seq
        seq += 1
        data = {"type": etype, "sequence_number": seq}
        data.update(payload)
        body = json.dumps(data, ensure_ascii=False)
        return ("event: " + etype + chr(10) + "data: " + body + chr(10) + chr(10)).encode("utf-8")

    def reason_item(status):
        return {
            "id": rs_id,
            "type": "reasoning",
            "status": status,
            "summary": [{"type": "summary_text", "text": "".join(reason_parts)}],
        }

    def msg_item(status):
        item = {"id": msg_id, "type": "message", "status": status,
                "role": "assistant", "content": []}
        if text_parts:
            item["content"] = [{"type": "output_text", "text": "".join(text_parts),
                              "annotations": _annotations()}]
        return item

    def _annotations():
        """引用来源：只认网关代跑的工具真的回传过的网址。"""
        try:
            return web_tools.build_citations("".join(text_parts),
                                             holder.get("web_sources") or [])
        except Exception:
            return []

    if not holder.get("suppress_lifecycle"):
        yield ev("response.created", {"response": resp_obj("in_progress")})
        yield ev("response.in_progress", {"response": resp_obj("in_progress")})

    for data, chunk in iter_sse_chunks(upstream, with_done=True):
        if data == "[DONE]":
            saw_done = True
            continue
        if chunk is None:
            continue
        if isinstance(chunk.get("error"), dict):
            # 上游把错误放在流内时，不能以 response.completed 收场——客户端
            # 会把它当成一次成功的空回答（Responses 规范用 response.failed）。
            # 发完继续迭代：渠道适配器随后抛出的 HTTPError 仍要走到治理层。
            if not stream_failed:
                err = chunk["error"]
                holder["error"] = err
                failed = resp_obj("failed")
                failed["error"] = err
                yield ev("response.failed", {"response": failed})
                stream_failed = True
            continue
        if chunk.get("usage") and usage_outgrew(usage, chunk["usage"]):
            usage = chunk["usage"]
            holder["usage"] = usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("reasoning_content")
            if piece:
                if reason_index is None:
                    reason_index = len(outputs)
                    outputs.append(None)
                    yield ev("response.output_item.added",
                             {"output_index": reason_index, "item": reason_item("in_progress")})
                    yield ev("response.reasoning_summary_part.added", {
                        "item_id": rs_id, "output_index": reason_index, "summary_index": 0,
                        "part": {"type": "summary_text", "text": ""},
                    })
                reason_parts.append(piece)
                yield ev("response.reasoning_summary_text.delta", {
                    "item_id": rs_id, "output_index": reason_index,
                    "summary_index": 0, "delta": piece,
                })
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                fn = tc.get("function") or {}
                fn_name = fn.get("name") or ""
                fn_args = fn.get("arguments") or ""
                call_id = tc.get("id") or ""
                # 网关自己代跑的网路工具：呼叫不转发给客户端，参数收集起来
                if idx in internal_calls or (
                        own_web_tools and fn_name
                        and web_tools.is_internal(fn_name)):
                    entry = internal_calls.setdefault(
                        idx, {"name": fn_name, "arguments": ""})
                    if fn_name:
                        entry["name"] = fn_name
                    if fn_args:
                        entry["arguments"] += fn_args
                    continue
                if idx not in tool_calls_map:
                    out_idx = len(outputs)
                    outputs.append(None)
                    c_id = call_id or _new_id("call_")
                    is_custom = bool(fn_name) and fn_name in custom_names
                    entry = {
                        "output_index": out_idx,
                        "id": c_id,
                        "name": fn_name,
                        "arguments": fn_args,
                        "custom": is_custom,
                        "item_id": _new_id("ctc_" if is_custom else "fc_"),
                    }
                    tool_calls_map[idx] = entry
                    item = {
                        "id": entry["item_id"],
                        "status": "in_progress",
                        "call_id": c_id,
                        "name": fn_name,
                    }
                    if is_custom:
                        item["type"] = "custom_tool_call"
                        item["input"] = ""
                    else:
                        item["type"] = "function_call"
                        item["arguments"] = ""
                    # namespace 必须在 output_item.added 就带上：客户端从 added
                    # 事件就开始匹配执行器，事后补 done 已经晚了。
                    stamp_namespace(item, ns_map)
                    yield ev("response.output_item.added", {
                        "output_index": out_idx,
                        "item": item,
                    })
                else:
                    entry = tool_calls_map[idx]
                    if fn_name and not entry["name"]:
                        entry["name"] = fn_name
                        if fn_name in custom_names:
                            entry["custom"] = True
                    if fn_args:
                        entry["arguments"] += fn_args
                # 首个分片也可能已经带参数：它已经记进 entry["arguments"]，
                # 这里只补发 delta，不能再累计一次，否则下游拼出的 JSON 会重复。
                if fn_args:
                    if entry.get("custom"):
                        yield ev("response.custom_tool_call_input.delta", {
                            "output_index": entry["output_index"],
                            "item_id": entry["item_id"],
                            "call_id": entry["id"],
                            "delta": fn_args,
                        })
                    else:
                        yield ev("response.function_call_arguments.delta", {
                            "output_index": entry["output_index"],
                            "item_id": entry["item_id"],
                            "call_id": entry["id"],
                            "delta": fn_args,
                        })

            piece = delta.get("content")
            if piece:
                if msg_index is None:
                    if reason_index is not None:
                        full_r = "".join(reason_parts)
                        yield ev("response.reasoning_summary_text.done", {
                            "item_id": rs_id, "output_index": reason_index,
                            "summary_index": 0, "text": full_r,
                        })
                        yield ev("response.reasoning_summary_part.done", {
                            "item_id": rs_id, "output_index": reason_index, "summary_index": 0,
                            "part": {"type": "summary_text", "text": full_r},
                        })
                        outputs[reason_index] = reason_item("completed")
                        yield ev("response.output_item.done",
                                 {"output_index": reason_index, "item": outputs[reason_index]})
                    msg_index = len(outputs)
                    outputs.append(None)
                    yield ev("response.output_item.added", {
                        "output_index": msg_index,
                        "item": {"id": msg_id, "type": "message", "status": "in_progress",
                                 "role": "assistant", "content": []},
                    })
                    yield ev("response.content_part.added", {
                        "item_id": msg_id, "output_index": msg_index, "content_index": 0,
                        "part": {"type": "output_text", "text": "", "annotations": _annotations()},
                    })
                # 工具调用标记缓冲：DSML 与 Anthropic 风格标记都不直接吐给客户端，先扣住判定
                text_buffer += piece
                while text_buffer:
                    idx = text_buffer.find("<")
                    if idx == -1:
                        text_parts.append(text_buffer)
                        yield ev("response.output_text.delta", {
                            "item_id": msg_id, "output_index": msg_index,
                            "content_index": 0, "delta": text_buffer,
                        })
                        text_buffer = ""
                        break
                    m = DSML_CALLS_RE.search(text_buffer)
                    m_anth = ANTH_CALLS_RE.search(text_buffer)
                    if m_anth and (not m or m_anth.start() < m.start()):
                        m = m_anth      # Anthropic 标记在更前面：优先按它解析
                    if m and m.start() == idx:
                        if idx > 0:
                            lead = text_buffer[:idx]
                            text_parts.append(lead)
                            yield ev("response.output_text.delta", {
                                "item_id": msg_id, "output_index": msg_index,
                                "content_index": 0, "delta": lead,
                            })
                        calls_found, _ = parse_dsml_tool_calls(m.group(0))
                        if calls_found:
                            dsml_tool_calls.extend(calls_found)
                        text_buffer = text_buffer[m.end():]
                        continue
                    cand = text_buffer[idx:idx+30]
                    is_cand = ("DSML" in cand) or cand.startswith("<function_calls>") \
                        or cand.startswith("<invoke ") or cand.startswith("<tool_call") \
                        or (len(cand) < 10 and not any(c in cand for c in (" ", "\t", "\n", ">")))
                    if is_cand:
                        lead = text_buffer[:idx]
                        text_parts.append(lead)
                        yield ev("response.output_text.delta", {
                            "item_id": msg_id, "output_index": msg_index,
                            "content_index": 0, "delta": lead,
                        })
                        text_buffer = text_buffer[idx:]
                        break
                    else:
                        next_lt = text_buffer[idx+1:].find("<")
                        if next_lt != -1:
                            flush_len = idx + 1 + next_lt
                            lead = text_buffer[:flush_len]
                            text_parts.append(lead)
                            yield ev("response.output_text.delta", {
                                "item_id": msg_id, "output_index": msg_index,
                                "content_index": 0, "delta": lead,
                            })
                            text_buffer = text_buffer[flush_len:]
                        else:
                            text_parts.append(text_buffer)
                            yield ev("response.output_text.delta", {
                                "item_id": msg_id, "output_index": msg_index,
                                "content_index": 0, "delta": text_buffer,
                            })
                            text_buffer = ""
                            break
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]

    if stream_failed:
        # 已经发过 response.failed；不再补 completed/incomplete。
        return

    # max_tokens / 断连留下的半截参数：不补 done 事件，标成 incomplete。
    # 已完整的调用照常收尾，不因同批一个坏调用全部作废。
    dropped_truncated = 0
    if tool_calls_map and (finish == "length" or not saw_done):
        for idx in sorted(list(tool_calls_map.keys())):
            entry = tool_calls_map[idx]
            if is_truncated_arguments(entry.get("arguments")):
                tool_calls_map.pop(idx, None)
                dropped_truncated += 1

    if reason_index is not None and outputs[reason_index] is None:
        full_r = "".join(reason_parts)
        yield ev("response.reasoning_summary_text.done", {
            "item_id": rs_id, "output_index": reason_index, "summary_index": 0, "text": full_r,
        })
        yield ev("response.reasoning_summary_part.done", {
            "item_id": rs_id, "output_index": reason_index, "summary_index": 0,
            "part": {"type": "summary_text", "text": full_r},
        })
        outputs[reason_index] = reason_item("completed")
        yield ev("response.output_item.done",
                 {"output_index": reason_index, "item": outputs[reason_index]})

    # 1. Emit completed structured tool calls
    for idx in sorted(tool_calls_map.keys()):
        entry = tool_calls_map[idx]
        if entry.get("custom"):
            yield ev("response.custom_tool_call_input.done", {
                "output_index": entry["output_index"],
                "item_id": entry["item_id"],
                "call_id": entry["id"],
                "input": _unwrap_custom_input(entry["arguments"]),
            })
            fc_item = {
                "id": entry["item_id"],
                "type": "custom_tool_call",
                "status": "completed",
                "call_id": entry["id"],
                "name": entry["name"],
                "input": _unwrap_custom_input(entry["arguments"]),
            }
        else:
            yield ev("response.function_call_arguments.done", {
                "output_index": entry["output_index"],
                "item_id": entry["item_id"],
                "call_id": entry["id"],
                "arguments": entry["arguments"],
            })
            fc_item = {
                "id": entry["item_id"],
                "type": "function_call",
                "status": "completed",
                "call_id": entry["id"],
                "name": entry["name"],
                "arguments": entry["arguments"],
            }
        stamp_namespace(fc_item, ns_map)
        outputs[entry["output_index"]] = fc_item
        yield ev("response.output_item.done", {
            "output_index": entry["output_index"],
            "item": fc_item,
        })

    # 收尾：把缓冲里残留的文本刷出去（残留 DSML 先解析成工具调用）
    if text_buffer:
        calls_rem, clean_rem = parse_dsml_tool_calls(text_buffer)
        if calls_rem:
            dsml_tool_calls.extend(calls_rem)
        if clean_rem:
            text_parts.append(clean_rem)
            if msg_index is not None:
                yield ev("response.output_text.delta", {
                    "item_id": msg_id, "output_index": msg_index,
                    "content_index": 0, "delta": clean_rem,
                })
        text_buffer = ""
    # 2. DSML fallback: 流中已解析的优先，否则对全文再解析一次
    full_text = "".join(text_parts)
    dsml_calls = dsml_tool_calls
    if not dsml_calls:
        extra_calls, clean_text = parse_dsml_tool_calls(full_text)
        if extra_calls:
            dsml_calls = extra_calls
            full_text = clean_text
    if dsml_calls and not tool_calls_map:
        for dc in dsml_calls:
            # DSML 形状的网路工具呼叫一样由网关代跑
            if own_web_tools and web_tools.is_internal(dc.get("name")):
                entry = internal_calls.setdefault(
                    dc.get("id") or _new_id("call_"),
                    {"name": dc.get("name"), "arguments": "{}"})
                entry["name"] = dc.get("name") or entry["name"]
                entry["arguments"] = dc.get("arguments") or entry.get("arguments") or "{}"
                continue
            out_idx = len(outputs)
            fc_item = {
                "id": _new_id("fc_"),
                "type": "function_call",
                "status": "completed",
                "call_id": dc.get("id") or _new_id("call_"),
                "name": dc.get("name") or "",
                "arguments": dc.get("arguments") or "{}",
            }
            stamp_namespace(fc_item, ns_map)
            outputs.append(fc_item)
            yield ev("response.output_item.added", {
                "output_index": out_idx,
                "item": dict(fc_item, status="in_progress", arguments=""),
            })
            yield ev("response.function_call_arguments.delta", {
                "output_index": out_idx,
                "item_id": fc_item["id"],
                "call_id": fc_item["call_id"],
                "delta": fc_item["arguments"],
            })
            yield ev("response.function_call_arguments.done", {
                "output_index": out_idx,
                "item_id": fc_item["id"],
                "call_id": fc_item["call_id"],
                "arguments": fc_item["arguments"],
            })
            yield ev("response.output_item.done", {
                "output_index": out_idx,
                "item": fc_item,
            })

    # 本轮有代跑呼叫时：把完成事件留给下一轮，否则客户端会以为整个回合已结束。
    # 同时补发 web_search_call 卡片事件，让客户端画出「已搜寻网路」的原生界面。
    if internal_calls:
        holder.setdefault("internal_calls", []).extend(
            {"name": value["name"], "arguments": value["arguments"]}
            for value in internal_calls.values()
        )
        holder["suppress_completion"] = True
        for value in internal_calls.values():
            name = str(value.get("name") or "")
            try:
                args = json.loads(value.get("arguments") or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            if name == web_tools.WEB_FETCH_NAME:
                action = {"type": "open_page", "url": web_tools.url_arg(args)}
            else:
                action = {"type": "search", "query": web_tools.query_args(args)}
            search_id = _new_id("ws_")
            search_index = len(outputs)
            outputs.append(None)
            yield ev("response.output_item.added", {
                "output_index": search_index,
                "item": {"id": search_id, "type": "web_search_call",
                         "status": "in_progress"},
            })
            yield ev("response.web_search_call.in_progress", {
                "output_index": search_index, "item_id": search_id,
            })
            yield ev("response.web_search_call.searching", {
                "output_index": search_index, "item_id": search_id,
            })
            search_item = {"id": search_id, "type": "web_search_call",
                           "status": "completed"}
            if action.get("query") or action.get("url"):
                search_item["action"] = action
            outputs[search_index] = search_item
            yield ev("response.output_item.done", {
                "output_index": search_index, "item": search_item,
            })
            yield ev("response.web_search_call.completed", {
                "output_index": search_index, "item_id": search_id,
            })

    # 3. Emit message item only if text was emitted OR no other output item exists
    has_other_items = any(o for o in outputs if o)
    if msg_index is not None or full_text or not has_other_items:
        if msg_index is None:
            msg_index = len(outputs)
            outputs.append(None)
            yield ev("response.output_item.added", {
                "output_index": msg_index,
                "item": {"id": msg_id, "type": "message", "status": "in_progress",
                         "role": "assistant", "content": []},
            })
            yield ev("response.content_part.added", {
                "item_id": msg_id, "output_index": msg_index, "content_index": 0,
                "part": {"type": "output_text", "text": "", "annotations": _annotations()},
            })
        yield ev("response.output_text.done", {
            "item_id": msg_id, "output_index": msg_index, "content_index": 0, "text": full_text,
        })
        yield ev("response.content_part.done", {
            "item_id": msg_id, "output_index": msg_index, "content_index": 0,
            "part": {"type": "output_text", "text": full_text,
                     "annotations": _annotations()},
        })
        outputs[msg_index] = msg_item("completed")
        yield ev("response.output_item.done", {"output_index": msg_index, "item": outputs[msg_index]})

    # 上游没给 usage（断流/占位帧）时按已流出内容估算，避免账目整行丢失。
    if usage is None or (usage.get("total_tokens") or 0) == 0:
        out_txt = "".join(text_parts)
        rs_txt = "".join(reason_parts)
        if out_txt or rs_txt:
            comp = estimate_tokens(out_txt) + estimate_tokens(rs_txt)
            prompt_est = max(1, estimate_tokens(str(holder.get("input_text") or "")))
            usage = {
                "prompt_tokens": prompt_est,
                "completion_tokens": comp,
                "total_tokens": prompt_est + comp,
                "completion_tokens_details": {"reasoning_tokens": estimate_tokens(rs_txt)},
                "prompt_tokens_details": {"cached_tokens": 0},
            }
            holder["usage"] = usage

    if finish == "error":
        err = {"code": "upstream_error",
               "message": "upstream stream finished with error"}
        holder["error"] = err
        failed = resp_obj("failed")
        failed["error"] = err
        yield ev("response.failed", {"response": failed})
        return

    if dropped_truncated:
        status = "incomplete"
    else:
        status = "completed" if finish != "length" else "incomplete"
    final = resp_obj(status)
    if finish == "length":
        final["incomplete_details"] = {"reason": "max_output_tokens"}
    # 整轮只有 reasoning、正文为空：标 completed 会让客户端误以为回合正常
    # 结束（主上游 #508）；发 response.failed 让它重试。
    if reasoning_only_response(final):
        err = {"code": "empty_reasoning_only",
               "message": "upstream returned reasoning without output text; retry"}
        holder["error"] = err
        failed = resp_obj("failed")
        failed["error"] = err
        yield ev("response.failed", {"response": failed})
        return
    # 这一轮的完成事件留给下一轮：代跑网路工具时客户端只应看到一次收尾。
    if not holder.get("suppress_completion"):
        yield ev("response.completed", {"response": final})


