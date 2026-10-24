# -*- coding: utf-8 -*-
"""core/upstream_body.py —— 出站请求体组装（代码自二开迁移）

把客户端请求体改写成上游能接受的形状：

1. 提示词模式（passthrough / custom / append）与审核误杀降级门；
2. 指纹清洗、reasoning_content 回填；
3. 缺 system 时补默认 system（上游要求必须有）；
4. 工具调用配对修复（相邻调用合并 / 结果重排 / 孤儿清理）；
5. max_completion_tokens 别名搬运、tool_choice / tools 归一；
6. DeepSeek 思考档位缺省补齐；
7. 强制 stream=true + usage 回传（上游不认非流式）。

纯函数式：所有输入显式传入，不读全局状态（除降级门的进程内窗口）。
"""
import json
import threading
import time

from core import prompt as prompt_mod
from core import tools_compat

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant."

#: 审核 403 后的降级窗口（进程内存，触发后到次日 00:00 北京时间）
DEGRADE = prompt_mod.DegradeGate()

#: 提示词配置读取器：由入口在启动时注入（读 settings.json）。
#: 返回 {"mode": ..., "file": ...}；未注入时一律 passthrough。
_prompt_config_reader = None
_config_lock = threading.Lock()


def set_prompt_config_reader(fn):
    global _prompt_config_reader
    with _config_lock:
        _prompt_config_reader = fn


def prompt_mode_config():
    reader = _prompt_config_reader
    if reader is None:
        return {"mode": "passthrough", "file": ""}
    try:
        cfg = reader()
    except Exception:
        cfg = None
    if not isinstance(cfg, dict):
        cfg = {"mode": "passthrough", "file": ""}
    return cfg


def apply_prompt_mode(messages):
    """把配置的提示词模式套到一次请求的 messages 上（出站前）。

    passthrough 是原有行为；custom/append 是显式开启的。降级窗口激活时
    passthrough/append 切到最小中性提示词；custom 永不降级。提示词文件
    读不了时 fail open 到透传，绝不因此拦人。
    """
    cfg = prompt_mode_config()
    mode = cfg.get("mode") or "passthrough"
    degraded = DEGRADE.active()
    if mode in ("custom", "append"):
        try:
            text = prompt_mod.load_prompt(mode, cfg.get("file"))
        except Exception:
            text = ""
        if text:
            return prompt_mod.apply_mode(messages, mode, text, degraded=degraded)
        return messages
    if degraded:
        return prompt_mod.apply_mode(messages, mode, "", degraded=True)
    return messages


def encode_upstream_body(body):
    """序列化 chat 请求体：JSON.stringify 的紧凑形态（无空格分隔符）。

    官方客户端（Node JSON.stringify）不带分隔符后的空格，默认的
    json.dumps(separators=(", ", ": ")) 会让 body 字节与 Content-Length 都成
    一处机器特征。上游解析等价，只影响线上字节。
    """
    return json.dumps(body, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def build_upstream_body(payload, system_prompt=DEFAULT_SYSTEM_PROMPT):
    model = payload.get("model") or ""
    messages = tools_compat.normalize_roles(payload.get("messages") or [])
    # 提示词模式在 sanitize/backfill 之前跑：改写后的网关提示词才是上游看到的
    # system（客户端的指纹句已按模式处理）。
    messages = apply_prompt_mode(messages)
    messages = tools_compat.sanitize_messages(messages)
    messages = tools_compat.backfill_reasoning_content(messages, model)
    if not messages or (messages[0].get("role") != "system"):
        messages = [{"role": "system", "content": system_prompt}] + messages
    body = dict(payload)
    # 下划线开头的键是链路内部标记（如 _web_tools / _namespace_map），绝不能
    # 出站；模型看到会当成未知字段直接 400（对齐上游 v1.7.12 的清洗）。
    for marker in [key for key in body if str(key).startswith("_")]:
        body.pop(marker, None)
    body["messages"] = messages
    # 出站前修好工具调用配对：没有结果的调用、被插队消息隔开的结果、被拆成
    # 相邻 assistant 消息的并行批次，都会让上游拒绝该会话的后续每一轮。
    # 顺序有讲究：先合并拆散的声明，重排才能看到完整批次。
    repaired, _merged = tools_compat.merge_adjacent_tool_calls(body["messages"])
    repaired, _repacked = tools_compat.repack_tool_result_blocks(repaired)
    repaired, _cleaned = tools_compat.cleanup_orphan_tool_calls(repaired)
    body["messages"] = repaired
    tools_compat.translate_max_completion_tokens(body)
    tools_compat.normalize_tool_choice(body)
    tools_compat.normalize_tools(body)

    # Thinking injection for DeepSeek models：开了思考但没带 effort 档位时，
    # 上游会整段丢掉 reasoning。客户端显式关掉的不动。
    if str(model).lower().startswith("deepseek"):
        thinking = body.get("thinking")
        opted_out = isinstance(thinking, dict) and \
            str(thinking.get("type") or "").strip().lower() == "disabled"
        effort = body.get("reasoning_effort") or body.get("reasoningEffort")
        if not opted_out and str(effort or "").strip().lower() != "none":
            if "thinking" not in body:
                body["thinking"] = {"type": "enabled"}
            if not effort:
                body["reasoning_effort"] = tools_compat.model_default_effort(model) or "high"

    body["stream"] = True
    if "stream_options" not in body:
        body["stream_options"] = {"include_usage": True}
    return body


def trigger_degrade():
    """记录一次内容审核 403：到次日 00:00 前改用中性提示词。"""
    DEGRADE.trigger()


def degrade_active():
    return DEGRADE.active()


def prompt_fingerprint(messages):
    """Privacy-safe fingerprint of the outgoing prompt（不存文本，只存哈希）。"""
    import hashlib
    import json

    try:
        def h(obj):
            blob = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
            return hashlib.sha256(blob).hexdigest()[:12]

        msgs = messages or []
        out = {"msgs_sha": h(msgs), "n_msgs": len(msgs)}
        if msgs:
            out["system_sha"] = h(msgs[0]) if msgs[0].get("role") == "system" else ""
            out["prefix_sha"] = h(msgs[:-1]) if len(msgs) > 1 else ""
        return out
    except Exception:
        return {}
