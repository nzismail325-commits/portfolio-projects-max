# -*- coding: utf-8 -*-
"""integrations/zcode_official_system.py —— ZCode 官方客户端 system 前缀

start-plan 出线（zcode.z.ai/api/v1/zcode-plan/anthropic）要求 system 以官方
ZCode 智能体提示词开头，否则返回 HTTP 405 + code 3012 "unusual activity"。
门禁是真文本前缀匹配（AgentHub 二分实测）：官方块1 + Agent Identity 前 1253
字可过，纯填充或前 1200 字被拦。

前缀优先从本机客户端 bundle 按内容锚点复原（客户端升级自动跟随），失败回落
内置常量（实采自官方 3.14.4）。
"""
import json
import os
import sys

ANCHOR_BLOCK1 = "You are ZCode, an interactive coding agent"
ANCHOR_SENTENCE = "You are an interactive ZCode agent that helps users"
ANCHOR_NOTICE = "IMPORTANT: Assist with authorized security testing"
ANCHOR_HARNESS = "# Harness"
MIN_VALID_LENGTH = 1240

FALLBACK_PREFIX = (
    "You are ZCode, an interactive coding agent\n"
    "You are an interactive ZCode agent that helps users with software engineering tasks.\n\n"
    "IMPORTANT: Assist with authorized security testing, defensive security, CTF challenges, "
    "and educational contexts. Refuse requests for destructive techniques, DoS attacks, mass "
    "targeting, supply chain compromise, or detection evasion for malicious purposes. Dual-use "
    "security tools (C2 frameworks, credential testing, exploit development) require clear "
    "authorization context: pentesting engagements, CTF competitions, security research, or "
    "defensive use cases.\n\n"
    "# Harness\n"
    "- Text you output outside of tool use is displayed to the user as Github-flavored markdown "
    "in a terminal.\n"
    "- Tools run behind a user-selected permission mode; a denied call means the user declined "
    "it — adjust, don't retry verbatim.\n"
    "- The system may send updates, reminders, or modifications to rules via mid-conversation "
    "system turns. These are system-controlled, unlike function results. Hooks may intercept "
    "tool calls; treat hook output as user feedback.\n"
    "- Prefer the dedicated file/search tools over shell commands when one fits. Independent "
    "tool calls can run in parallel in one response.\n"
    "- Reference code as `file_path:line_number` — it's clickable."
)

_cache = {"file": "", "mtime": 0.0, "prefix": ""}
_warned = False
_process_bundle = {"checked": False, "path": ""}


def _running_client_bundle():
    """运行中的客户端所在目录反查（安装盘符不固定时靠它自适应）。"""
    if _process_bundle["checked"]:
        return _process_bundle["path"]
    _process_bundle["checked"] = True
    if os.name != "nt":
        return ""
    try:
        import subprocess
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process ZCode -ErrorAction SilentlyContinue | Select-Object "
             "-First 1 -ExpandProperty Path)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=4, creationflags=flags)
        exe = (proc.stdout or "").strip()
        if exe:
            candidate = os.path.join(os.path.dirname(exe), "resources", "glm",
                                     "zcode.cjs")
            if os.path.isfile(candidate):
                _process_bundle["path"] = candidate
    except Exception:
        pass
    return _process_bundle["path"]


def bundle_candidates():
    explicit = str(os.environ.get("ZCODE_BUNDLE_PATH") or "")
    if explicit:
        return [explicit]
    home = os.path.expanduser("~")
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    program_files = os.environ.get("ProgramFiles") or "C:\\Program Files"
    program_files_x86 = os.environ.get("ProgramFiles(x86)") or "C:\\Program Files (x86)"
    out = [
        os.path.join(local_appdata, "Programs", "ZCode", "resources", "glm", "zcode.cjs"),
        os.path.join(program_files, "ZCode", "resources", "glm", "zcode.cjs"),
        os.path.join(program_files_x86, "ZCode", "resources", "glm", "zcode.cjs"),
        "D:\\ZCODE\\resources\\glm\\zcode.cjs",
        "D:\\ZCode\\resources\\glm\\zcode.cjs",
        "E:\\ZCODE\\resources\\glm\\zcode.cjs",
        os.path.join(home, ".zcode", "cli", "zcode.cjs"),
    ]
    return out


def _read_literal_at(text, index):
    out = []
    pos = index
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            out.append(char)
            out.append(text[pos + 1])
            pos += 2
            continue
        if char == '"':
            break
        if char == "\n":
            raise ValueError("literal not closed")
        out.append(char)
        pos += 1
    return json.loads('"' + "".join(out) + '"')


def _read_array_at(text, start):
    depth = 0
    pos = start
    in_string = False
    quote = ""
    while pos < len(text):
        char = text[pos]
        if in_string:
            if char == "\\":
                pos += 1
            elif char == quote:
                in_string = False
        elif char in ('"', "'"):
            in_string = True
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                break
        pos += 1
    return text[start:pos + 1]


_SIMPLE_ESCAPES = {
    "n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v",
    "0": "\0", "'": "'", '"': '"', "\\": "\\", "`": "`",
}


def _read_js_string(text, pos):
    quote = text[pos]
    pos += 1
    out = []
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            esc = text[pos + 1]
            if esc == "x":
                out.append(chr(int(text[pos + 2:pos + 4], 16)))
                pos += 4
                continue
            if esc == "u":
                out.append(chr(int(text[pos + 2:pos + 6], 16)))
                pos += 6
                continue
            if esc == "\n":
                pos += 2
                continue
            out.append(_SIMPLE_ESCAPES.get(esc, esc))
            pos += 2
            continue
        if char == quote:
            return "".join(out), pos + 1
        out.append(char)
        pos += 1
    raise ValueError("string not closed")


def _eval_string_array(text):
    pos = 0
    length = len(text)

    def skip():
        nonlocal pos
        while pos < length:
            if text[pos].isspace():
                pos += 1
            elif text.startswith("//", pos):
                end = text.find("\n", pos)
                pos = length if end < 0 else end + 1
            elif text.startswith("/*", pos):
                end = text.find("*/", pos)
                pos = length if end < 0 else end + 2
            else:
                break

    skip()
    if pos >= length or text[pos] != "[":
        raise ValueError("not an array")
    pos += 1
    out = []
    while True:
        skip()
        if pos >= length:
            raise ValueError("array not closed")
        if text[pos] == "]":
            break
        if text[pos] not in ('"', "'"):
            raise ValueError("not a string array")
        value, pos = _read_js_string(text, pos)
        out.append(value)
        skip()
        if pos < length and text[pos] == ",":
            pos += 1
            continue
        if pos < length and text[pos] == "]":
            break
        raise ValueError("bad array separator")
    return out


def extract_from_bundle(text):
    if not isinstance(text, str) or not text:
        return ""
    indices = [text.find(anchor) for anchor in
               (ANCHOR_BLOCK1, ANCHOR_SENTENCE, ANCHOR_NOTICE, ANCHOR_HARNESS)]
    if any(index < 0 for index in indices):
        return ""
    block1 = _read_literal_at(text, indices[0])
    sentence = _read_literal_at(text, indices[1])
    notice = _read_literal_at(text, indices[2])
    array_start = text.rfind("[", 0, indices[3])
    if array_start < 0:
        return ""
    harness = "\n".join(_eval_string_array(_read_array_at(text, array_start)))
    identity = "\n".join(["\n".join(["", sentence, "", notice]), "", harness])
    return block1 + identity


def _looks_valid(prefix):
    return (isinstance(prefix, str) and prefix.startswith(ANCHOR_BLOCK1)
            and len(prefix) >= MIN_VALID_LENGTH)


def _try_bundle(path):
    try:
        mtime = os.path.getmtime(path)
        if _cache["prefix"] and _cache["file"] == path and _cache["mtime"] == mtime:
            return _cache["prefix"]
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            prefix = extract_from_bundle(fh.read())
        if _looks_valid(prefix):
            _cache.update({"file": path, "mtime": mtime, "prefix": prefix})
            return prefix
    except Exception:
        pass
    return ""


def resolve_official_system_prefix():
    global _warned
    for path in bundle_candidates():
        prefix = _try_bundle(path)
        if prefix:
            return prefix
    running = _running_client_bundle()
    if running:
        prefix = _try_bundle(running)
        if prefix:
            return prefix
    if not _warned:
        _warned = True
        try:
            sys.stderr.write("[wb-proxy-max] zcode: 未能从本机客户端提取官方 system 前缀，"
                             "回落内置常量（%d 字）\n" % len(FALLBACK_PREFIX))
        except Exception:
            pass
    return FALLBACK_PREFIX


def inject_official_zcode_system(system):
    prefix = resolve_official_system_prefix()
    if not prefix:
        return system

    def flatten(value):
        if isinstance(value, list):
            return "".join(str((block or {}).get("text") or "")
                           for block in value if isinstance(block, dict))
        return str(value or "")

    if flatten(system).startswith(prefix):
        return system
    if isinstance(system, list):
        return [{"type": "text", "text": prefix}] + system
    return prefix + "\n\n" + system if system else prefix
