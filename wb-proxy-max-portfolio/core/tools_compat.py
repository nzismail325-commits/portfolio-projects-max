# -*- coding: utf-8 -*-
"""core/tools_compat.py —— 工具调用与提示词兼容层（代码自二开迁移，上游同源）

职责：
- 角色名归一（developer → system）；
- 指纹清洗（x-anthropic-billing-hdr / cc_* / OmO junior 等已确认会触发上游
  内容审核的整串特征），只清 system/user 侧文本，不改变语义；
- reasoning_content 回填（DeepSeek 多轮思考链）；
- 工具声明归一（tool_choice / tools 形态）；
- DSML / Anthropic 文本工具调用解析（模型把调用写进正文时兜底转结构化）；
- 出站前修复工具调用配对（相邻调用合并 / 结果重排 / 孤儿调用清理）。

纯标准库。本文件不依赖任何渠道或账号模块。
"""
import json
import os
import re
import uuid


def _new_id(prefix):
    # 工具调用 id 生成（自 protocol.py 移入：本模块两个标记解析器也要用它）
    return prefix + uuid.uuid4().hex


def preserve_request_contract_enabled():
    """Responses 请求契约保真开关（对齐上游 v1.7.14）。

    只保真字段与工具数据：不开时不改任何既有行为；开了也只跳过工具参数
    与工具结果的指纹替换，不校验输出、不保证上游执行 JSON Schema。
    """
    return os.environ.get("WB_PRESERVE_REQUEST_CONTRACT", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Fingerprint Sanitization (immunizes against Codex / Claude Code WAF patterns)
# ---------------------------------------------------------------------------
SANITIZE_FEATURES = (
    "x-anthropic-billing-header",
    "cc_entrypoint=",
    "You are Claude Code",
    "Main branch (",
    "You are a coding agent running in the Codex CLI",
    "github.com/anthropics/",
    "11128",
)

SANITIZE_REWRITES = (
    ("You are Claude Code, Anthropic's official CLI for Claude",
     "You are Claude Code, Anthropic's official CLI tool for Claude."),
    ("Main branch (you will usually use this for PRs)",
     "Default branch (you will usually use this for PRs)"),
    ("You are a coding agent running in the Codex CLI, a terminal-based coding assistant.",
     "You are a coding agent running in the Codex CLI tool, a terminal-based coding assistant."),
    ("To give feedback, users should report the issue at https://github.com/anthropics/claude-code/issues",
     "To provide feedback, users should report the issue at https://github.com/anthropics/claude-code/issues"),
    ("11128", "11-128"),
)

SANITIZE_HDR_RE = re.compile(r"(?i)x-anthropic-billing-header:[^;\r\n]*;?\s*")
SANITIZE_BARE_HDR_RE = re.compile(r"(?i)x-anthropic-billing-header")
SANITIZE_KV_RE = re.compile(r"(?i)\bcc_[a-z0-9_]+=[^;\r\n]*;?\s*")
# 上游对这个 OmO 身份指纹整串命中返回 11128（大小写不敏感、前后带别的内容也认）；
# 只替换这一条确认过的指纹，单独的词上游并不拦（对齐上游 v1.5.9）。
SANITIZE_OMO_JUNIOR_RE = re.compile(
    r"Sisyphus-Junior - Focused executor from OhMyOpenCode", re.IGNORECASE
)
# 上游 WAF 把「客户端自我介绍句式 + 品牌」当成非官方渠道（主上游 #533/#537/#539）：
#   You are an AI agent powered by DeepSeek Harness.
#   You are a coding agent powered by the deepseek-v4.1-flash model.
#   You are an AI assistant built on DeepSeek.
# 同一类经纬句还有 built by / created by / developed by / made by / trained by
# 等变体，以及省掉名词的 "You are powered by ..."（主上游 v1.7.19 #550）。
# 整句换成中性句，不依赖具体品牌；作用于 system / developer / assistant，
# user / tool 数据保持原样。
SANITIZE_IDENTITY_VERBS = (
    "powered by", "built on", "built by", "created by",
    "developed by", "made by", "trained by",
)
SANITIZE_IDENTITY_RE = re.compile(
    r"You are\s+"
    r"(?:an?\s+|the\s+)?(?:[\w.-]+\s+){0,3}?"
    r"(?:agent|assistant|model|AI|LLM)?[\s,]*"
    r"(?:powered by|built on|built by|created by|developed by|made by|trained by)"
    r"[^\n]*?(?:\.(?=\s|$)|(?=\n|$))",
    re.IGNORECASE)
SANITIZE_IDENTITY_REPLACEMENT = "You are a helpful AI assistant."
SANITIZE_IDENTITY_LOWER = SANITIZE_IDENTITY_VERBS


def has_fingerprint(text, identity=True):
    if not isinstance(text, str) or not text:
        return False
    for f in SANITIZE_FEATURES:
        if f in text:
            return True
    if SANITIZE_BARE_HDR_RE.search(text) or SANITIZE_OMO_JUNIOR_RE.search(text):
        return True
    if not identity:
        return False
    low = text.lower()
    # 动词短语只是廉价前置筛：真命中与否交给正则判定，避免 "You are free to
    # use tools built by ..." 这类分词修饰宾语的句子被误改写。
    if not any(needle in low for needle in SANITIZE_IDENTITY_LOWER):
        return False
    return SANITIZE_IDENTITY_RE.search(text) is not None


def sanitize_text(text, identity=True):
    if not isinstance(text, str) or not text:
        return text
    if not has_fingerprint(text, identity=identity):
        return text
    text = SANITIZE_OMO_JUNIOR_RE.sub("Sisyphus-Junior - Focused executor", text)
    if identity:
        text = SANITIZE_IDENTITY_RE.sub(SANITIZE_IDENTITY_REPLACEMENT, text)
    for old, new in SANITIZE_REWRITES:
        text = text.replace(old, new)
    text = SANITIZE_HDR_RE.sub("", text)
    if "cc_" in text:
        prev = ""
        while prev != text:
            prev = text
            text = SANITIZE_KV_RE.sub("", text)
    # 兜底：裸键名/大小写混写（如反引号引用）也规范化，避免漏网
    text = SANITIZE_BARE_HDR_RE.sub("x-anthropic-billing-hdr", text)
    return text.strip()


def sanitize_content(content, identity=True):
    if isinstance(content, str):
        return sanitize_text(content, identity=identity)
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                p = dict(part)
                p["text"] = sanitize_text(p["text"], identity=identity)
                out.append(p)
            else:
                out.append(part)
        return out
    return content


def sanitize_tool_calls(tool_calls):
    """深递归净化工具参数：历史工具参数每轮重发，必须同样脱敏。

    arguments 是序列化的应用数据、不是客户端指纹，但**非字符串值仍必须**
    转成 JSON 字符串：上游的 Go 结构体声明 arguments 为 string，客户端传
    dict/list/int 会直接 400（code 11101，cannot unmarshal into field of
    type string）。None 按「无参调用」规范成 "{}"。
    """
    if not isinstance(tool_calls, list):
        return tool_calls
    preserve = preserve_request_contract_enabled()
    out = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            item = dict(tc)
            fn = item.get("function")
            if isinstance(fn, dict):
                fn = dict(fn)
                raw_args = fn.get("arguments")
                if isinstance(raw_args, str):
                    fn["arguments"] = (raw_args if preserve
                                       else sanitize_text(raw_args, identity=False))
                elif raw_args is None:
                    fn["arguments"] = "{}"
                else:
                    try:
                        fn["arguments"] = json.dumps(raw_args, ensure_ascii=False)
                    except Exception:
                        fn["arguments"] = str(raw_args)
                item["function"] = fn
            out.append(item)
        else:
            out.append(tc)
    return out


def sanitize_messages(messages):
    out = []
    for m in messages or []:
        if isinstance(m, dict):
            item = dict(m)
            # 工具结果是应用数据，保真开关打开时不改写其中的业务数字。
            preserve_result = (preserve_request_contract_enabled()
                               and item.get("role") in ("tool", "function"))
            identity = item.get("role") in ("system", "developer", "assistant")
            if "content" in item and not preserve_result:
                item["content"] = sanitize_content(item["content"],
                                                   identity=identity)
            if isinstance(item.get("reasoning_content"), str):
                item["reasoning_content"] = sanitize_text(
                    item["reasoning_content"], identity=False)
            if "tool_calls" in item:
                item["tool_calls"] = sanitize_tool_calls(item["tool_calls"])
            out.append(item)
        else:
            out.append(m)
    return out


# ---------------------------------------------------------------------------
# DeepSeek Multi-turn Consistency: reasoning_content backfill
# ---------------------------------------------------------------------------
def backfill_reasoning_content(messages, model):
    if not model or not str(model).lower().startswith("deepseek"):
        return messages
    has_trace = False
    for m in messages:
        if isinstance(m, dict):
            if m.get("reasoning") or "reasoning_content" in m:
                has_trace = True
                break
    if not has_trace:
        return messages
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant":
            item = dict(m)
            if "reasoning_content" not in item:
                if item.get("reasoning"):
                    item["reasoning_content"] = str(item["reasoning"])
                else:
                    item["reasoning_content"] = ""
            out.append(item)
        else:
            out.append(m)
    return out



# ---------------------------------------------------------------------------
# Tool & Tool Choice Normalization (avoids code 11101 on object tool_choice)
# ---------------------------------------------------------------------------
def normalize_tool_choice(obj):
    if "tool_choice" not in obj:
        return
    tc = obj["tool_choice"]
    if isinstance(tc, str):
        val = tc.strip().lower()
        if val == "none":
            # 曾经在这里连 tools/functions 一起删，那正是 Agent 死循环的成因：
            # 声明没了，模型只能把调用降级成伪 JSON 文本，客户端解析不到再追问，
            # 上下文每轮膨胀。「none」的语义由字段本身表达，保留声明走正常
            # tool_calls 通道（对齐上游 v1.5.7）。
            obj["tool_choice"] = "none"
        return
    if isinstance(tc, dict):
        typ = (tc.get("type") or "").strip().lower()
        if typ == "none":
            # 同上：保留 tools 声明；上游只认字符串，对象形式必须降级（否则 11101）
            obj["tool_choice"] = "none"
        elif typ in ("auto", "required"):
            obj["tool_choice"] = typ
        elif typ == "function":
            name = (tc.get("function") or {}).get("name") or tc.get("name") or ""
            obj["tool_choice"] = name.strip() or "auto"
        else:
            obj.pop("tool_choice", None)
    else:
        obj.pop("tool_choice", None)


# ---------------------------------------------------------------------------
# Tool Schema Parameters Normalization (avoids code 11129)
# ---------------------------------------------------------------------------
_SCHEMA_TYPE_MAP = {
    "str": "string",
    "text": "string",
    "int": "integer",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
    "float": "number",
}
_SCHEMA_VALID_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}


def _deep_normalize_schema(s):
    """递归清洗并规整 JSON Schema（上游 Go 校验器比 OpenAPI 严格）。"""
    if not isinstance(s, dict):
        return s

    # 1. 元数据字段为 null 时剔除（上游严格拒绝 null description/title）
    for k in list(s.keys()):
        if s[k] is None and k in ("description", "title", "format", "pattern", "items", "default"):
            s.pop(k, None)

    # 2. 规整 type 声明（别名转换 / 非法类型按形态兜底或剔除）
    if "type" in s:
        typ = s["type"]
        if isinstance(typ, str):
            typ_lower = typ.strip().lower()
            if typ_lower in _SCHEMA_TYPE_MAP:
                s["type"] = _SCHEMA_TYPE_MAP[typ_lower]
            elif typ_lower not in _SCHEMA_VALID_TYPES:
                if "properties" in s:
                    s["type"] = "object"
                elif "items" in s:
                    s["type"] = "array"
                else:
                    s.pop("type", None)
            else:
                s["type"] = typ_lower
        elif isinstance(typ, list):
            s["type"] = [_SCHEMA_TYPE_MAP.get(str(t).lower(), str(t).lower()) for t in typ if t]

    # 3. object 类型必须带 properties 字典
    if s.get("type") == "object" or ("properties" in s and s.get("type") is None):
        if s.get("type") is None:
            s["type"] = "object"
        if "properties" not in s or not isinstance(s.get("properties"), dict):
            s["properties"] = {}

    # 4. required 清洗：去 None、空串，保证是字符串列表
    if "required" in s:
        req = s["required"]
        if isinstance(req, list):
            cleaned_req = [str(x) for x in req if x is not None and str(x).strip()]
            if cleaned_req:
                s["required"] = cleaned_req
            else:
                s.pop("required", None)
        elif isinstance(req, str) and req.strip():
            s["required"] = [req.strip()]
        else:
            s.pop("required", None)

    # 5. array items：tuple 形态解包成 dict，递归规整
    if "items" in s:
        items = s["items"]
        if isinstance(items, list):
            first_dict = next((it for it in items if isinstance(it, dict)), None)
            s["items"] = _deep_normalize_schema(dict(first_dict)) if first_dict is not None else {"type": "string"}
        elif isinstance(items, dict):
            _deep_normalize_schema(items)
        elif items is None:
            s.pop("items", None)

    # 6. 递归规整 properties
    if "properties" in s and isinstance(s["properties"], dict):
        for prop_name, prop_val in list(s["properties"].items()):
            if isinstance(prop_val, dict):
                _deep_normalize_schema(prop_val)

    # 7. 递归规整 definitions / $defs
    for def_key in ("$defs", "definitions"):
        if def_key in s and isinstance(s[def_key], dict):
            for d_name, d_val in list(s[def_key].items()):
                if isinstance(d_val, dict):
                    _deep_normalize_schema(d_val)

    # 8. 递归规整组合关键字（anyOf / oneOf / allOf）
    for comb_key in ("anyOf", "oneOf", "allOf"):
        if comb_key in s and isinstance(s[comb_key], list):
            for sub in s[comb_key]:
                if isinstance(sub, dict):
                    _deep_normalize_schema(sub)

    return s


def _normalize_tool_parameters(fn):
    """让 function.parameters 满足上游严格 schema（避免 code 11129）。

    上游的 Go schema 校验器要求 function parameters：
      - type: "object"
      - properties: {...}（字典，哪怕是空的）
      - required 是不带 null 的字符串列表
      - 合法 JSON schema 类型（'str'/'int'/'dict' 等别名转成标准名）
      - description/title 等元数据字段不带 null
    递归处理嵌套 parameters / properties / items / definitions。只修坏的
    类型与形态，不动合规字段、不剥任何语义参数。
    """
    if not isinstance(fn, dict):
        return
    params = fn.get("parameters")
    if params is None or not isinstance(params, dict):
        fn["parameters"] = {"type": "object", "properties": {}}
        return
    p = dict(params)
    if p.get("type") != "object":
        p["type"] = "object"
    if "properties" not in p or not isinstance(p.get("properties"), dict):
        p["properties"] = {}
    _deep_normalize_schema(p)
    fn["parameters"] = p


def normalize_tools(obj):
    tools = obj.get("tools")
    if not tools or not isinstance(tools, list):
        if "tools" in obj:
            obj.pop("tools", None)
        return
    norm = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        # Wrap top-level name tool definition into Chat Completions function schema
        if "name" in t and "function" not in t:
            fn = {
                "name": t.get("name") or "",
                "description": t.get("description") or "",
                "parameters": t.get("parameters") or {},
            }
            if "strict" in t:
                fn["strict"] = t["strict"]
            _normalize_tool_parameters(fn)
            norm.append({"type": "function", "function": fn})
        else:
            item = dict(t)
            if item.get("type") != "function":
                item["type"] = "function"
            if "function" in item and isinstance(item["function"], dict):
                fn = dict(item["function"])
                _normalize_tool_parameters(fn)
                item["function"] = fn
            norm.append(item)
    if norm:
        obj["tools"] = norm
    else:
        obj.pop("tools", None)


# ---------------------------------------------------------------------------
# DeepSeek DSML Tool Calls Fallback Parser
# ---------------------------------------------------------------------------
TAG_START = r"<[^>]*DSML[^>]*"
DSML_CALLS_RE = re.compile(TAG_START + r"calls>(.*?)</[^>]*DSML[^>]*calls>", re.DOTALL)
DSML_INVOKE_RE = re.compile(TAG_START + r"invoke\s+name=[\x22\x27]([^\x22\x27]+)[\x22\x27]>(.*?)</[^>]*invoke>", re.DOTALL)
DSML_PARAM_RE = re.compile(TAG_START + r"parameter\s+name=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*>(.*?)</[^>]*parameter>", re.DOTALL)

# Anthropic 风格工具标记（Trae 部分模型不吐结构化 tool_calls，把调用写成
# <function_calls><invoke name=…><parameter …>… 文本混在正文里——chat 协议
# 客户端自己解析这种标记所以看不出问题，Responses 翻译层必须兜底转成
# 结构化 function_call，否则原始标记直接漏给客户端）。
ANTH_CALLS_RE = re.compile(r"<function_calls>(.*?)</function_calls>", re.DOTALL)
ANTH_INVOKE_RE = re.compile(r"<invoke\s+name=[\x22\x27]([^\x22\x27]+)[\x22\x27]\s*>(.*?)</invoke>", re.DOTALL)
ANTH_PARAM_RE = re.compile(r"<parameter\s+name=[\x22\x27]([^\x22\x27]+)[\x22\x27][^>]*>(.*?)</parameter>", re.DOTALL)

# tool_call 家族（实测第二形态，比 Anthropic 风格更偷工减料）：
#   <tool_call> <function=Read> <parameter=file_path> 路径 </parameter> </tool_call>
# function 用等号属性、parameter 可能不带闭合、整块可能没有 </function>——
# 全按宽松正则收，闭合缺失时吃到 </tool_call> 或文本末尾。
TOOLCALL_BLOCK_RE = re.compile(r"<tool_call[^>]*>(.*?)(?:</tool_call>|$)", re.DOTALL)
TOOLCALL_FUNC_RE = re.compile(r"<function\s*=\s*[\x22\x27]?([^\x22\x27>\s]+)[\x22\x27]?\s*>", re.IGNORECASE)
TOOLCALL_PARAM_RE = re.compile(
    r"<parameter\s*=\s*[\x22\x27]?([^\x22\x27>\s]+)[\x22\x27]?\s*>"
    r"(.*?)(?=<parameter\s*=|</function|</tool_call|$)", re.DOTALL | re.IGNORECASE)

def _in_code_fence(text, pos):
    """pos 之前未闭合的反引号代码块数（奇数 = pos 在代码块内）。"""
    before = text[:pos]
    fences = before.count("```")
    return fences % 2 == 1


def _parse_toolcall_family(text):
    """<tool_call> 家族解析：一个块内可有多条 <function=…> 调用。

    反引号代码块内的标记不解析（模型在正文里讲解标签格式时不误伤）。
    """
    if not text or "<tool_call" not in text:
        return None, text
    probe = TOOLCALL_BLOCK_RE.search(text)
    if probe and _in_code_fence(text, probe.start()):
        return None, text
    calls = []
    clean_parts = []
    last = 0
    for m in TOOLCALL_BLOCK_RE.finditer(text):
        clean_parts.append(text[last:m.start()])
        last = m.end()
        body = m.group(1)
        # 每条 function 调用的参数范围：到下一个 <function= 或块尾
        fn_spans = list(TOOLCALL_FUNC_RE.finditer(body))
        for i, fm in enumerate(fn_spans):
            seg_end = fn_spans[i + 1].start() if i + 1 < len(fn_spans) else len(body)
            seg = body[fm.end():seg_end]
            params = {}
            for pm in TOOLCALL_PARAM_RE.finditer(seg):
                params[pm.group(1)] = pm.group(2).strip()
            calls.append({
                "id": _new_id("call_"),
                "name": fm.group(1),
                "arguments": json.dumps(params, ensure_ascii=False),
            })
    clean_parts.append(text[last:])
    clean = " ".join(p.strip() for p in clean_parts if p.strip())
    return (calls or None), clean

def _parse_marker_tool_calls(text, calls_re, invoke_re, param_re, guard):
    """通用标记解析：guard(text) 为 False 直接放行（不扣文本）。"""
    if not text or not guard(text):
        return None, text
    match = calls_re.search(text)
    if not match:
        return None, text
    calls_block = match.group(1)
    tool_calls = []
    for inv_match in invoke_re.finditer(calls_block):
        func_name = inv_match.group(1)
        params_block = inv_match.group(2)
        params = {}
        for p_match in param_re.finditer(params_block):
            p_name = p_match.group(1)
            p_val = p_match.group(2).strip()
            params[p_name] = p_val
        tool_calls.append({
            "id": _new_id("call_"),
            "name": func_name,
            "arguments": json.dumps(params, ensure_ascii=False),
        })
    clean = (text[:match.start()].strip() + " " + text[match.end():].strip()).strip()
    return tool_calls, clean


def parse_dsml_tool_calls(text):
    """DSML / Anthropic / tool_call 三家族标记统一入口：谁命中用谁。

    返回 (tool_calls | None, 剩余文本)。所有家族都不认时原样放行，
    各自正则互不干扰（DSML 带 DSML 字样；function_calls 是客户端通行的
    Anthropic 约定；tool_call 家族是实测的偷工减料变体）。
    """
    if text and "DSML" in text:
        calls, clean = _parse_marker_tool_calls(
            text, DSML_CALLS_RE, DSML_INVOKE_RE, DSML_PARAM_RE,
            lambda t: "DSML" in t)
        if calls:
            return calls, clean
    calls, clean = _parse_marker_tool_calls(
        text, ANTH_CALLS_RE, ANTH_INVOKE_RE, ANTH_PARAM_RE,
        lambda t: "<function_calls>" in t or "<invoke" in t)
    if calls:
        return calls, clean
    return _parse_toolcall_family(text)



def translate_max_completion_tokens(obj):
    """新版 SDK 只发 max_completion_tokens：搬运为上游认的 max_tokens。

    已有 max_tokens 时不覆盖，值非法则忽略。
    """
    alias = obj.pop("max_completion_tokens", None)
    if alias is None:
        return
    if "max_tokens" in obj:
        return
    try:
        val = int(alias)
        if val > 0:
            obj["max_tokens"] = val
    except (TypeError, ValueError):
        pass


def _empty_content(value):
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def _merge_reasoning_content(dst, src):
    """把 src 的 reasoning_content 并进 dst，两边都有时换行拼接。"""
    rc = src.get("reasoning_content")
    if not isinstance(rc, str) or not rc:
        return
    prev = dst.get("reasoning_content")
    if isinstance(prev, str) and prev:
        dst["reasoning_content"] = prev + "\n" + rc
    else:
        dst["reasoning_content"] = rc



def merge_adjacent_tool_calls(messages):
    """把相邻的 assistant tool_calls 消息合并成一条。

    有些 OpenAI 兼容的 Agent 客户端会把一个并行批次回放成多条相邻的
    assistant 消息，每条带一个 tool_call。DeepSeek 系上游对这种形状直接
    400 / code 11148（tool_call_sequence_broken）并判会话死刑——每次重试
    回放同一份历史都没用，换账号也救不了。合并声明恢复上游接受的形状。

    条件刻意严格，不发明语义：
      - 两条消息必须相邻；
      - 后一条的 content 必须为空（None/""/[]）；
      - 前一条必须是已带 tool_calls 的 assistant。

    第二种形状把纯文本 assistant 的 content 折进前面没有 content 的
    tool_calls assistant（同一批拆分回放的另一种顺序）。两种都保留
    reasoning_content——DeepSeek 多轮思考要靠它回填。
    """
    if not isinstance(messages, list) or len(messages) < 2:
        return messages, False
    out = []
    changed = False
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        if m.get("role") == "assistant" and out:
            prev = out[-1] if isinstance(out[-1], dict) else None
            if prev is not None and prev.get("role") == "assistant":
                tcs = m.get("tool_calls")
                prev_calls = prev.get("tool_calls")
                # 形状一：本条声明了工具调用且没有 content
                if (isinstance(tcs, list) and tcs
                        and _empty_content(m.get("content"))
                        and isinstance(prev_calls, list) and prev_calls):
                    prev["tool_calls"] = prev_calls + tcs
                    _merge_reasoning_content(prev, m)
                    changed = True
                    continue
                # 形状二：纯文本 content 折进前面没有 content 的 tool_calls assistant
                if ("tool_calls" not in m
                        and isinstance(m.get("content"), str) and m["content"]
                        and isinstance(prev_calls, list) and prev_calls
                        and _empty_content(prev.get("content"))):
                    prev["content"] = m["content"]
                    _merge_reasoning_content(prev, m)
                    changed = True
                    continue
        out.append(m)
    if not changed:
        return messages, False
    return out, True


def repack_tool_result_blocks(messages):
    """让 tool_calls 批次和它的结果保持相邻。

    上游要求 role:"tool" 的结果紧跟在发起调用的 assistant 消息之后、
    中间不能插别的东西。比如 Codex 的 image_resize_notice 会以 developer
    消息出现在工具输出之后；并行调用时它落在两条结果之间，配对读作断裂，
    上游整包拒绝（code 11148），会话死刑。这里只重排：结果不变、相对
    顺序不变，入侵者挪到批次后面。
    """
    if not isinstance(messages, list) or len(messages) < 3:
        return messages, False
    out = []
    changed = False
    i = 0
    while i < len(messages):
        m = messages[i]
        if not isinstance(m, dict) or m.get("role") != "assistant":
            out.append(m)
            i += 1
            continue
        calls = m.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            out.append(m)
            i += 1
            continue
        want = set()
        for tc in calls:
            if isinstance(tc, dict):
                tid = tc.get("id")
                if isinstance(tid, str) and tid:
                    want.add(tid)
        out.append(m)
        i += 1
        results = []
        between = []
        while i < len(messages):
            mm = messages[i]
            if not isinstance(mm, dict):
                break
            role = mm.get("role")
            if role == "tool":
                tid = mm.get("tool_call_id")
                if not (isinstance(tid, str) and tid in want):
                    break
                results.append(mm)
                i += 1
                continue
            # 任何 assistant 消息都结束这一批。不是结果的消息是入侵者：它可能
            # 落在首条结果之前（旧实现在这里放弃，配对保持断裂），也可能插在
            # 两条结果之间。无论哪种都挪到整批结果之后。
            if role == "assistant":
                break
            between.append(mm)
            i += 1
        if results:
            out.extend(results)
            out.extend(between)
            if between:
                changed = True
        else:
            out.extend(between)
    if not changed:
        return messages, False
    return out, True


def cleanup_orphan_tool_calls(messages):
    """删掉没有结果的调用、以及没有调用的结果。

    一次失败的工具调用（参数错、超时、未知工具）会在客户端留下一条永远
    等不到回答的 assistant tool_calls：结果消息不会再写，可这条记录会
    跟着历史参与后续每一轮，上游每轮都拒（code 11148）——一次失败的
    调用就能判整个会话死刑。两边按同一组 id 修剪，半配对留不下来。
    """
    if not isinstance(messages, list) or not messages:
        return messages, False
    call_ids = set()
    result_ids = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "tool":
            tid = m.get("tool_call_id")
            if isinstance(tid, str) and tid:
                result_ids.add(tid)
        elif role == "assistant":
            calls = m.get("tool_calls")
            if isinstance(calls, list):
                for tc in calls:
                    if isinstance(tc, dict):
                        tid = tc.get("id")
                        if isinstance(tid, str) and tid:
                            call_ids.add(tid)
    if not call_ids and not result_ids:
        return messages, False
    keep = call_ids & result_ids
    changed = False
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        calls = m.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            continue
        kept = [tc for tc in calls
                if isinstance(tc, dict) and isinstance(tc.get("id"), str)
                and tc["id"] in keep]
        if len(kept) == len(calls):
            continue
        changed = True
        if kept:
            m["tool_calls"] = kept
        else:
            m.pop("tool_calls", None)
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "tool":
            tid = m.get("tool_call_id")
            if not (isinstance(tid, str) and tid in keep):
                changed = True
                continue
        out.append(m)
    if not changed:
        return messages, False
    return out, True

def normalize_roles(messages):
    """Map role names the upstream rejects onto ones it accepts.

    WorkBuddy only knows system / user / assistant / tool. OpenAI's newer
    "developer" role (used by the Codex CLI and current SDKs) is the same thing
    as "system", but sending it verbatim fails with code 11-128.
    """
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            out.append(m)
            continue
        item = m
        if m.get("role") == "developer":
            item = dict(m)
            item["role"] = "system"
        out.append(item)
    return out


def model_default_effort(model):
    """客户端没指定 effort 时目录给的默认档，没有则 None。

    目录查询走 intel/catalog（延迟导入，避免 core → intel 的静态依赖）。
    """
    try:
        from intel import catalog
        meta = catalog.model_catalog_meta(model)
    except Exception:
        return None
    effort = (meta.get("reasoning") or {}).get("defaultEffort")
    return effort.strip() if isinstance(effort, str) and effort.strip() else None

