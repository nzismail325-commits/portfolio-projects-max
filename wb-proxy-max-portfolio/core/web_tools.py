# -*- coding: utf-8 -*-
"""core/web_tools.py —— 本地网路工具代跑的对话链路桥（自上游 v1.7.12 移植）

infra/webtools.py 只负责「怎么搜、怎么抓」；本模块负责把它接进 Responses
链路：客户端宣告 web_search / web_fetch 时，把那份伺服器端宣告换成网关自己
的 function，模型呼叫后由网关执行、把结果喂回去再跑一轮，客户端只看到一次
连续回应。

开关（settings.local_web_tools，默认关）在每个请求上现读：面板一拨，下一个
请求即生效。关着时宣告原样透传，客户端自己的同名工具不受影响——是否拦截只
认请求体上的 `_web_tools` 标记（由本模块在替换宣告时打上）。

回合上限 MAX_WEB_ROUNDS（WB_MAX_WEB_ROUNDS，最多 8，默认 3）；最后一轮把
工具收回，让模型用现有结果收尾，不合成假的完成事件。
"""
import re

from infra import settings
from infra import webtools

#: 请求体内部标记：本请求的工具宣告已被网关替换
WEB_TOOLS_MARKER = "_web_tools"

#: 上游工具名与参数读取：只转出 webtools 的公开入口，调用方不必再 import 它
WEB_SEARCH_NAME = webtools.WEB_SEARCH_NAME
WEB_FETCH_NAME = webtools.WEB_FETCH_NAME
url_arg = webtools.url_arg
query_args = webtools.query_args


def enabled(ctx):
    try:
        return settings.local_web_tools(ctx.accounts_dir) is True
    except Exception:
        return False


def active(body):
    """本请求的网路工具是否由网关代跑（只看标记，不重读开关）。"""
    return isinstance(body, dict) and body.get(WEB_TOOLS_MARKER) is True


def install(chat_body, declared_tools=None):
    """客户端宣告了网路工具时，把它换成网关自己的 function。

    返回 True 表示已接管（调用方给请求体打上标记）。没有任何声明时不改动。
    """
    raw_tools = declared_tools if declared_tools is not None else chat_body.get("tools")
    wants = webtools.client_wants_web(raw_tools)
    if not wants["search"] and not wants["fetch"]:
        return False
    chat_body["tools"] = webtools.install_tool_defs(chat_body.get("tools") or [], wants)
    chat_body[WEB_TOOLS_MARKER] = True
    return True


def is_internal(name):
    return webtools.is_internal_tool(name)


def strip_internal(tools):
    """把网关自己的网路工具定义从工具清单里拿掉（收尾轮）。"""
    kept = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            kept.append(tool)
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        if is_internal(fn.get("name")) or is_internal(tool.get("name")):
            continue
        kept.append(tool)
    return kept


def internal_calls_from_chat(chat_obj, own_web_tools=False):
    """聚合结果里由网关代跑的调用：[(name, arguments)]。"""
    if not own_web_tools:
        return []
    message = ((chat_obj.get("choices") or [{}])[0] or {}).get("message") or {}
    out = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        name = str(fn.get("name") or "")
        if is_internal(name):
            out.append({"name": name, "arguments": fn.get("arguments") or "{}"})
    return out


def execute_calls(calls, web_sources):
    """执行一批内部调用并返回 (tool_calls 消息, tool 结果消息)。"""
    tool_calls, results = [], []
    for index, call in enumerate(calls or []):
        name = str(call.get("name") or "")
        arguments = call.get("arguments") or "{}"
        call_id = call.get("id") or "call_web_%d" % index
        tool_calls.append({"id": call_id, "type": "function",
                           "function": {"name": name, "arguments": arguments}})
        output = webtools.execute(name, arguments)
        found = webtools.sources_from_result(output)
        if found and web_sources is not None:
            for source in found:
                if source not in web_sources:
                    web_sources.append(source)
        results.append({"role": "tool", "tool_call_id": call_id,
                        "name": name, "content": output})
    return tool_calls, results


def follow_up_body(chat_body, calls, web_sources, drop_tools=False):
    """构造喂回结果的下一轮请求体（不改动入参）。"""
    body = dict(chat_body)
    convo = list(body.get("messages") or [])
    tool_calls, results = execute_calls(calls, web_sources)
    convo.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
    convo.extend(results)
    if drop_tools:
        body["tools"] = strip_internal(body.get("tools"))
        convo.append({
            "role": "system",
            "content": ("The web tools are no longer available. Answer the user now "
                        "with what you already have. Do not say that you are "
                        "searching again."),
        })
    body["messages"] = convo
    body["stream"] = True
    return body


def max_rounds():
    return webtools.MAX_WEB_ROUNDS


def sum_usage(total, part):
    """多轮代跑的 token 用量累加（每一轮都是真实花掉的）。"""
    if not isinstance(part, dict):
        return total
    if not isinstance(total, dict):
        total = {}
    for key, value in part.items():
        if isinstance(value, dict):
            total[key] = sum_usage(total.get(key), value)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            total[key] = (total.get(key) or 0) + value
        elif key not in total:
            total[key] = value
    return total


_CITATION_MD_RE = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^)\s]+)\)")


def build_citations(text, sources):
    """模型实际引用到的来源 → url_citation annotations（编造的链接不算）。"""
    text = str(text or "")
    if not text or not sources:
        return []
    by_url = {}
    for source in sources or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        by_url.setdefault(url, source)
        by_url.setdefault(url.rstrip("/"), source)

    annotations, seen = [], set()

    def add(url, title, start, end):
        key = (url, start, end)
        if key in seen or start < 0 or end <= start:
            return
        seen.add(key)
        annotations.append({
            "type": "url_citation",
            "url": url,
            "title": title or url,
            "start_index": start,
            "end_index": end,
        })

    markdown_spans = []
    for match in _CITATION_MD_RE.finditer(text):
        url = match.group(2)
        source = by_url.get(url) or by_url.get(url.rstrip("/"))
        if not source:
            continue
        markdown_spans.append((match.start(0), match.end(0)))
        add(url, source.get("title") or match.group(1),
            match.start(0), match.end(0))

    for match in re.finditer(r"https?://[^\s<>()\[\]]+", text):
        if any(match.start(0) >= start and match.end(0) <= end
               for start, end in markdown_spans):
            continue
        url = match.group(0).rstrip(".,;:!?")
        source = by_url.get(url) or by_url.get(url.rstrip("/"))
        if not source:
            continue
        add(url, source.get("title"), match.start(0), match.start(0) + len(url))

    annotations.sort(key=lambda item: (item["start_index"], item["end_index"]))
    return annotations
