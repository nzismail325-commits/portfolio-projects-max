# -*- coding: utf-8 -*-
"""integrations/upstream_errors.py —— 跨渠道共用的上游错误文案判定

移植自 AgentHub v1.79.0（util.cjs 的 INPUT_TOO_LARGE_MARKERS）。这类判定的
意义不是文案分类，而是「别冷却健康账号」：同一份超大 body 换任何账号都会被
上游拒绝，按账号故障处理会顺着换号链把整池逐个罚掉。
"""

#: 输入过大文案（大小写不敏感；中文原样匹配）。只加实测出现过的串：
#: 宽泛词（如单独的 "length"）会把参数错误一起吞进来。
INPUT_TOO_LARGE_MARKERS = (
    "too long",
    "too many tokens",
    "context length",
    "maximum context",
    "context window",
    "request entity too large",
    "input too large",
    "输入过长",
    "内容过长",
    "上下文过长",
    "上下文长度",
    "超出模型上限",
)


def is_input_too_large(message):
    lower = str(message or "").lower()
    if not lower:
        return False
    return any(marker.lower() in lower for marker in INPUT_TOO_LARGE_MARKERS)
