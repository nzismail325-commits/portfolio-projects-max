# -*- coding: utf-8 -*-
"""integrations/trae.py —— Trae 国内版（TRAE SOLO CN）渠道适配器（P5）

协议事实与账号模型移植自二开 wb-proxy/wb_trae.py（其源头为 AgentHub
https://github.com/HUIdada1/AgentHub electron/backend/proxy/adapters.cjs 的
trae 适配器，逆向实证抓包口径）；治理语义并入重构版共享账号池
（auth.accounts：402 停车 / 限流冷却 / 熔断 / 权重 / 禁用模型 / 代理槽），
账号落共享池（realm="trae" 的账号 JSON 文件），不再是渠道私有表。

账号制上游（refreshToken 换发型）：
  - 每条账号 = refreshToken + uid（uid 可从 accessToken JWT 解出，缺省换发后回填）
  - accessToken 不落盘，用 refreshToken 调 ExchangeToken 现场换，
    单飞（single-flight）合并并发刷新，防止 refreshToken 轮换互踩
  - 401：刷新一次后换号重试；刷新失败连续 3 次才停用（网络抖动不判死）
  - 1005 积分不足 → 402 语义，停车到下一个本地 04:00（额度夜间重置）
  - 4008 / 6004 限流 → 429 语义，冷却该号换下一把
  - 4001 模型配置问题 → 不罚号；11102 该号不支持此模型 → 账号×模型负缓存
  - 空流（HTTP 200 但无事件 / 只有 metadata 帧无可用增量）→ 502 语义

对外接入：wb_proxy._register_channels 里 `trae.install(ctx)` 一行；
模型目录经注册表 live_models 注入（intel/catalog 对非 intl/cn 出口现问）；
签到 / 额度 / 探测 / 令牌续期经 realm 配置的注入回调接管（auth.accounts）。

Only the Python standard library is required.
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import auth.accounts as accounts_mod
from auth import fingerprint as _fp_mod
from core import net
from core import upstream_body
from integrations import registry
from integrations import upstream_errors

# ---------------------------------------------------------------------------
# 协议常量（AgentHub rules.cjs headers.json trae 段实证值）
# ---------------------------------------------------------------------------
CHAT_URL = "https://trae-api-cn.mchost.guru/api/agent/v3/llm_utils_chat"
MODELS_URL = "https://trae-api-cn.mchost.guru/api/ide/v1/get_detail_param"
# api.trae.cn 只服务 /trae/api/v2/...（ug/pay 域），打 /api/agent/... 会吃 TLB 404，
# 故镜像域默认留空；官方镜像可用时填完整 URL 即自动启用故障转移
MIRROR_CHAT_URL = ""
MIRROR_MODELS_URL = ""

EXCHANGE_URLS = [
    "https://api.trae.cn/cloudide/api/v3/trae/oauth/ExchangeToken",
    "https://api.trae.com.cn/cloudide/api/v3/trae/oauth/ExchangeToken",
]
CREDITS_PATHS = [
    "/trae/api/v2/pay/ide_user_ent_usage",   # CN 现行口径
    "/trae/api/v1/pay/ide_user_ent_usage",   # 老接口兜底
]
CREDITS_BASES = ["https://api.trae.cn", "https://api.trae.com.cn"]

CLIENT_ID = "en1oxy7wnw8j9n"
APP_ID = "6eefa01c-1036-4c7e-9ca5-d891f63bfcd8"
IDE_VERSION = "0.1.50"
IDE_VERSION_CODE = "20260811"
USER_AGENT = "TraeClient/TTNet"
DEVICE_BRAND = "CREFG-XX"
OS_VERSION = "Windows 11 Home China"
WORKSPACE_ID = "e04cdd"

ROUTE_PREFIX = "trae"
LABEL = "Trae 国内版 (TRAE SOLO CN)"
BADGE = "Trae"
DOMAIN = "trae-api-cn.mchost.guru"

# 39 个 config_name（AgentHub rules.cjs catalog.json trae 段 2026-09 实证拉取）
STATIC_TRAE_MODELS = [
    "Doubao-Seed-Evolving", "Doubao-Seed-2.1-Pro", "seed-code-pro-0430",
    "Doubao-Seed-2.1-Turbo", "computer_use_subagent", "Doubao-Seed-2.0-Code",
    "browser_use_subagent",
    "glm-5.3", "glm-5.2", "glm-5-turbo", "glm-5",
    "DeepSeek-V4-Flash-Official", "DeepSeek-V4-Flash",
    "DeepSeek-V4-Pro-Official", "DeepSeek-V4-Pro",
    "kimi-k3", "kimi-k2.7-code", "kimi-k2.6", "minimax-m3",
    "qwen3.8-max", "qwen-3.7-plus", "sagitta", "aquila",
    "custom_model_gemini", "custom_model_placeholder", "custom_model_1M_text",
    "custom_model_1M", "custom_model_doubao_1M", "custom_model_doubao_256k",
    "custom_model_kimi", "custom_model_claude", "custom_model_gpt-5",
    "custom_model_no-fc", "custom_model_deepseek_chat",
    "custom_model_deepseek_reasoner", "custom_model_deepseek_v4",
    "file_search_agent", "explore_sub_agent_v2", "summary",
]

# ---------------------------------------------------------------------------
# 官方授权页登录（AgentHub discovery.cjs beginTraeOAuth 同流程，纯标准库移植）
# PKCE(S256) + 本地回环回调 + 授权码换令牌（EC P-256 设备公钥）。
# 回调地址官方页只认 http://127.0.0.1:<port>/authorize 一种形状（换 localhost、
# 换路径、换公网地址都会被页面判「网络错误」直接拒登，2026-10-17 实证）。
# 服务器部署时浏览器回跳不到服务器本机：把地址栏整段复制回面板「粘贴回调」。
# ---------------------------------------------------------------------------
LOGIN_GUIDANCE_URLS = [
    "https://api.trae.cn/cloudide/api/v3/trae/GetLoginGuidance",
    "https://api.trae.com.cn/cloudide/api/v3/trae/GetLoginGuidance",
    "https://www.trae.cn/cloudide/api/v3/trae/GetLoginGuidance",
]
LOGIN_FALLBACK_HOST = "https://www.trae.cn"
AUTH_APP_VERSION = "3.5.66"
OAUTH_PORT = 17388          # 首选回环端口；被占退随机端口（授权地址带实际端口）
OAUTH_TIMEOUT = 180.0       # 登录会话超时（秒）

# 换令牌 DevicePublicKey 的内置兜底（EC P-256 SPKI PEM；官方只验格式，
# AgentHub 生成后即丢弃私钥——不需要我们持有配对私钥）
FALLBACK_DEVICE_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEKrN9wrh8FBvhP74vacsyv4qkPnYC\n"
    "KkRILzsWVk3s09BgooXUZ33Smgl5AWVfgAlhfIYjY44KRnhO7zfelrnHpA==\n"
    "-----END PUBLIC KEY-----\n"
)

# 回调凭据字段（官方页登录成功后回传；官方部分回流形态把参数放在 #hash 里）
_OAUTH_CRED_KEYS = (
    "accessToken", "access_token", "refreshToken", "refresh_token",
    "userJwt", "user_jwt", "UserJwt", "userInfo", "user_info",
    "authCode", "auth_code", "authCodeInfo", "auth_code_info", "code", "token",
)

# 显示名/常用别名 → (config_name, 内部 model_name)；宽松归一化后未命中原样透传
MODEL_MAP = {
    "deepseek-v4-flash": ("DeepSeek-V4-Flash", "deepseek_v4_flash__dev"),
    "deepseek-v4": ("DeepSeek-V4", "deepseek_v4__dev"),
    "glm-4.6": ("GLM-4.6", "glm_4_6__dev"),
    "kimi-k2": ("Kimi-K2", "kimi_k2__dev"),
    "doubao-seed-1.6": ("Doubao-Seed-1.6", "doubao_seed_1_6__dev"),
    "qwen3-coder": ("Qwen3-Coder", "qwen3_coder__dev"),
    "minimax-m2": ("MiniMax-M2", "minimax_m2__dev"),
}

# function 字段按模型分发（TraeWorkAssistant models_sync.rs 实证：
# 部分模型仅在 solo_agent 下可用；未命中默认 solo_work_lite）
FUNCTION_MAP = {
    "doubao-seed-code": "solo_agent",
    "glm-5.3-flash": "solo_agent",
    "qwen3.8-flash": "solo_agent",
}
# 目录发现的 function 档全集（2026-10-16 实测：solo_work_lite 46 个、
# solo_agent 66 个，qwen3.8-flash / kimi-k2.8-preview / glm-4.6 等 30 个
# 只在 agent 档目录出现——只拉 lite 档会漏掉半个官方客户端可见目录）
DISCOVERY_FUNCTIONS = ("solo_work_lite", "solo_agent")

MODELS_TTL = 3600
DISCOVERY_TIMEOUT = 15
DISCOVER_FAIL_QUIET = 60
TRANSIENT_COOLDOWN = 60
RETRY_AFTER_CAP = 300
REFRESH_DEAD_LIMIT = 3          # 刷新连续失败 3 次才停用账号
MODEL_BLOCKED_HOURS = 6         # 11102 账号×模型负缓存时长
# 上游业务错误码（SSE error 事件 / 包体 code 字段）
CODE_CREDIT_EXHAUSTED = 1005    # 积分不足 → 402 语义
CODE_RATE_LIMITED = 4008        # 限流 → 429 语义
CODE_MODEL_CONFIG = 4001        # 模型配置问题 → 不罚号
CODE_MODEL_RATE = 6004          # 模型级限流 → 只冷却该账号×该模型
CODE_MODEL_BLOCKED = 11102      # 该号不支持此模型 → 账号×模型负缓存

PROBE_MODEL = "glm-5.3"         # 面板「测试」探测专用均衡模型

_lock = threading.RLock()

# ---------------------------------------------------------------------------
# 设备指纹与身份（AgentHub adapters.cjs deviceIds 实证算法）
# ---------------------------------------------------------------------------
def device_ids(seed):
    """device_id（15 位数字，首位 1-9，避免 3 连 0）/ machine_id（sha256 hex）。

    同账号多次请求保持一致，多账号之间天然隔离，防风控关联。
    """
    seed = str(seed or "anon")
    h = hashlib.sha256(("agenthub:device:" + seed).encode("utf-8")).digest()
    digits = str((h[0] % 9) + 1)
    zero_count = 0
    for i in range(1, 15):
        d = h[i] % 10
        if d == 0:
            zero_count += 1
            if zero_count >= 3:
                d = (h[i] % 9) + 1
                zero_count = 0
        else:
            zero_count = 0
        digits += str(d)
    machine_id = hashlib.sha256(
        ("agenthub:machine:" + seed).encode("utf-8")).hexdigest()
    return digits, machine_id


def _trace_id():
    """W3C trace 形态：00-<hex32>-<hex32>-01。"""
    return "00-%s-%s-01" % (uuid.uuid4().hex, uuid.uuid4().hex)


def _req_id():
    return "req_" + uuid.uuid4().hex


def jwt_claims(token):
    try:
        seg = str(token).split(".")[1]
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))
    except Exception:
        return {}


def jwt_uid(token):
    c = jwt_claims(token)
    return str(c.get("uid") or c.get("sub") or c.get("user_id") or "")


def _norm(s):
    return str(s or "").strip().lower().replace("_", "-")


def map_model(model):
    """模型名宽松归一化映射（小写 + _↔- 互换）；未命中原样透传。"""
    want = _norm(model)
    for k, v in MODEL_MAP.items():
        if _norm(k) == want:
            return v
    return (str(model or "").strip(), str(model or "").strip())


def function_for_model(model):
    want = _norm(model)
    for k, v in FUNCTION_MAP.items():
        if _norm(k) == want:
            return v
    return "solo_work_lite"


def _norm_config(model):
    """config_name 只取映射后的第一列（上游认裸 config_name）。"""
    return map_model(model)[0]


def _log(msg, ctx=None):
    logger = getattr(ctx, "log", None) if ctx is not None else None
    if logger:
        try:
            logger(msg)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 令牌换发（ExchangeToken；每账号一把锁串行化，防 refreshToken 轮换互踩）
# ---------------------------------------------------------------------------
_token_cache = {}       # uid -> (accessToken, exp)
_refresh_fails = {}     # uid -> 连续换发失败次数
_refresh_locks = {}
_refresh_locks_guard = threading.Lock()


def _refresh_lock(uid):
    with _refresh_locks_guard:
        lk = _refresh_locks.get(uid)
        if lk is None:
            lk = threading.Lock()
            _refresh_locks[uid] = lk
        return lk


def _http_json(url, body, headers, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST", headers=headers)
    try:
        with net.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(600).decode("utf-8", "replace")
        except Exception:
            detail = ""
        try:
            return exc.code, json.loads(detail)
        except Exception:
            return exc.code, {"message": detail[:300]}


def exchange_token(refresh_token):
    """refreshToken → (accessToken, newRefreshToken)；失败抛 RuntimeError。"""
    headers = {"Content-Type": "application/json", "user-agent": USER_AGENT,
               "x-cloudide-token": ""}
    body = {"ClientID": CLIENT_ID, "RefreshToken": str(refresh_token),
            "ClientSecret": "-", "UserID": ""}
    last = ""
    for base in EXCHANGE_URLS:
        status, data = _http_json(base, body, headers)
        d = data.get("Result") or data.get("result") or data.get("data") or data
        raw = None
        if isinstance(d, dict):
            raw = d.get("Token") or d.get("access_token") or d.get("accessToken")
        if status == 200 and raw:
            token = str(raw).replace("Cloud-IDE-JWT", "").strip()
            new_refresh = ""
            if isinstance(d, dict):
                new_refresh = str(d.get("RefreshToken")
                                  or d.get("refresh_token")
                                  or d.get("refreshToken") or "")
            return token, (new_refresh or str(refresh_token))
        msg = ""
        if isinstance(data, dict):
            rm = data.get("ResponseMetadata") or {}
            if isinstance(rm, dict):
                msg = str((rm.get("Error") or {}).get("Message") or "")
            msg = msg or str(data.get("message") or data.get("msg") or "")
        last = msg or ("HTTP %s" % status)
    raise RuntimeError("令牌换发失败：%s" % last)


def ensure_token(account):
    """取账号可用 accessToken：缓存有效直接用，否则串行化换发。

    成功后轮换的新 refreshToken 落盘、uid 缺失时从 JWT 回填。返回
    (token, "")；失败返回 (None, 错误信息)。换发连续失败计数达到
    REFRESH_DEAD_LIMIT 时停用账号（网络抖动不判死）。
    """
    uid = str(account.uid or "")
    cached = _token_cache.get(uid)
    if cached and cached[1] and cached[1] > time.time() + 120:
        return cached[0], ""
    with _refresh_lock(uid):
        cached = _token_cache.get(uid)
        if cached and cached[1] and cached[1] > time.time() + 120:
            return cached[0], ""
        if not account.refresh_token:
            return None, "无 refreshToken，请重新登录"
        try:
            token, new_rt = exchange_token(account.refresh_token)
        except Exception as exc:
            fails = int(_refresh_fails.get(uid) or 0) + 1
            _refresh_fails[uid] = fails
            message = "令牌换发失败：%s（连续第 %d/%d 次）" % (
                exc, fails, REFRESH_DEAD_LIMIT)
            if fails >= REFRESH_DEAD_LIMIT and account.enabled:
                account.enabled = False
                account.last_error = ("%s，已自动停用；重新登录后可再启用" % message)
                if account.accounts_dir:
                    try:
                        account.save(account.accounts_dir)
                    except Exception:
                        pass
            return None, message
        _refresh_fails[uid] = 0
        exp = int(jwt_claims(token).get("exp") or 0)
        _token_cache[uid] = (token, exp)
        account.access_token = token
        if exp:
            account.expires_at = exp
        if new_rt and new_rt != account.refresh_token:
            account.refresh_token = new_rt      # 官方轮换语义：旧值即刻作废
        if not uid:
            backfill = jwt_uid(token)
            if backfill:
                account.uid = backfill
        if account.accounts_dir:
            try:
                account.save(account.accounts_dir)
            except Exception:
                pass
        return token, ""


# ---------------------------------------------------------------------------
# 请求头指纹（AgentHub adapters.cjs headers() 逐字段对齐，缺项可能被风控）
# ---------------------------------------------------------------------------
def build_headers(account, token, url):
    uid = str(getattr(account, "uid", "") or "")
    device_id, machine_id = device_ids(uid or "anon")
    tid = _trace_id()
    h = {
        "content-type": "application/json",
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "user-agent": USER_AGENT,
        "authorization": "Cloud-IDE-JWT " + token,
        "x-ide-token": token,
        "x-cloudide-token": token,
        "x-app-id": APP_ID,
        "x-app-version": "default",
        "x-app-version-code": IDE_VERSION_CODE,
        "x-ide-version": IDE_VERSION,
        "x-ide-version-code": IDE_VERSION_CODE,
        "x-ide-version-type": "stable",
        "x-device-type": "windows",
        "x-device-brand": DEVICE_BRAND,
        "x-device-cpu": "Intel",
        "x-device-id": device_id,
        "x-machine-id": machine_id,
        "x-os-version": OS_VERSION,
        "request-traffic-type": "prod",
        "package-type": "stable_cn",
        "x-lgw-req-sdk-type": "3",
        "x-lscbd-aid": "787976",
        "x-lscbd-platform": "windows",
        "x-ss-dp": "787976",
        "app-version": IDE_VERSION,
        "x-custom-trace-id": tid[3:19],
        "x-tt-trace-id": tid,
        "x-flow-traceparent": "04-%s-%s-01" % (tid[3:35], uuid.uuid4().hex),
        "x-request-id": _req_id(),
        # referer 与实际请求 URL 同源（同源伪装）
        "referer": url,
    }
    if uid:
        h["x-uid"] = uid
    return h


# ---------------------------------------------------------------------------
# OpenAI body → llm_utils_chat 改写（AgentHub rewriteBody 对齐）
# ---------------------------------------------------------------------------
def rewrite_body(model, body, account):
    """核心出站体（提示词改写/工具修复已完成）之上做 Trae 特定改写。"""
    config_name = _norm_config(model)
    out = dict(body)
    out.pop("stream_options", None)     # OpenAI 特有字段，上游不认识
    msgs = []
    for m in (out.get("messages") or []):
        msg = dict(m)
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = [{"type": "text", "text": content}]
        # assistant tool_calls：function 形态 → function_call 形态，空 name 剔除
        if msg.get("role") == "assistant" and isinstance(msg.get("tool_calls"), list):
            calls = []
            for tc in msg["tool_calls"]:
                fn = (tc or {}).get("function") or {}
                if not fn.get("name"):
                    continue
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args or {}, ensure_ascii=False)
                calls.append({"id": tc.get("id"), "type": "function",
                              "function_call": {"name": fn["name"],
                                                "arguments": args}})
            if calls:
                msg["tool_calls"] = calls
            else:
                msg.pop("tool_calls", None)
        msgs.append(msg)
    out["messages"] = msgs
    # tools[].function.parameters 对象 → JSON 字符串
    if isinstance(out.get("tools"), list):
        tools = []
        for t in out["tools"]:
            fn = (t or {}).get("function") or {}
            params = fn.get("parameters")
            if isinstance(params, dict):
                t = dict(t)
                t["function"] = dict(fn, parameters=json.dumps(params, ensure_ascii=False))
            tools.append(t)
        out["tools"] = tools
    # tool_choice 归一化："none" → 删 tools/functions/tool_choice；
    # {type:function} → name 字符串；{type:auto/required} → 字符串
    tc = out.get("tool_choice")
    tc_type = tc if isinstance(tc, str) else (tc or {}).get("type") if isinstance(tc, dict) else ""
    if tc_type == "none":
        out.pop("tools", None)
        out.pop("functions", None)
        out.pop("tool_choice", None)
    elif isinstance(tc, dict):
        out["tool_choice"] = (tc.get("function") or {}).get("name") or tc_type or "auto"
    device_id, machine_id = device_ids(str(account.uid or "") or "anon")
    out["config_name"] = config_name
    out["model"] = config_name
    out["stream"] = True
    out["function"] = function_for_model(model)
    try:
        mt = int(body.get("max_tokens") or body.get("max_completion_tokens") or 0)
    except (TypeError, ValueError):
        mt = 0
    out["max_tokens"] = mt if mt > 0 else 4096
    out["conversation_id"] = str(uuid.uuid4())
    out["user_id"] = str(account.uid or "")
    out["session_id"] = str(uuid.uuid4())
    out["device_id"] = device_id
    out["machine_id"] = machine_id
    out["project_id"] = str(uuid.uuid4())
    out["workspace_id"] = WORKSPACE_ID
    try:
        pmt = int(body.get("prompt_max_tokens") or body.get("context_length") or 0)
    except (TypeError, ValueError):
        pmt = 0
    out["prompt_max_tokens"] = pmt if pmt > 0 else 168000
    out["mode"] = "FunctionCall"
    out["ide_version"] = IDE_VERSION
    out["ide_version_code"] = IDE_VERSION_CODE
    out["app_id"] = APP_ID
    out["package_type"] = "stable_cn"
    return out


# ---------------------------------------------------------------------------
# SSE 翻译 wrapper：Trae event JSON 流 → OpenAI chat SSE 字节行迭代器
# ---------------------------------------------------------------------------


class TraeChatStream(object):
    """把 Trae 的 event JSON 流翻译成 "data: {chat chunk}\\n\\n" 字节行。

    核心消费面（core/proxy_api + core/streaming）会 for line in upstream +
    clean_chunk + aggregate_stream，还会 with upstream: 关连接，本 wrapper
    完整实现 __iter__ / read / __enter__ / __exit__。
    - output/thought 事件 → delta.content / delta.reasoning_content
    - tool_calls 差量在 function_call 里（剥 namespace/partial_arguments，
      name 只在首个 index 分片带，键缺失比空串安全）
    - token_usage → 末尾聚合一个带 usage 的 chunk
    - done/turn_completion → finish_reason=stop + [DONE]
    - error 事件 → 先按码治理账号（1005 停车 / 4008 冷却 / 11102 负缓存 /
      4001 短冷却不罚号），吐一条 OpenAI 错误帧后再抛 HTTPError
      （1005→402 / 4008→429 / 4001→400 / 其余 502；流式客户端从错误帧
      看到失败原因，非流式聚合路径靠异常把状态码传给网关）
    - 空流（HTTP 200 无事件 / 只有 metadata 帧无可用增量）→ 502 语义
    """

    def __init__(self, resp, model, account, log=None):
        self._resp = resp
        self._model = model
        self._account = account
        self._log = log
        self._buf = b""
        self._done = False
        self._closed = False
        self._pending = []           # 收尾阶段待吐的 chunk/错误帧队列
        self._error = None           # 待抛异常（先吐完 pending 再抛）
        # 翻译状态
        self._chat_id = "chatcmpl-trae-" + uuid.uuid4().hex[:12]
        self._created = int(time.time())
        self._tool_seen = set()      # 已带过 name 的 index
        self._usage = None
        self._finish = None
        self._produced = False       # 是否产出过可用增量（空流判定）
        self._saw_error = False      # 上游是否已给出 error 事件

    # ---- 底层读取：SSE 帧 -> (event_name, data_bytes) ----
    def _read_sse_event(self):
        """读一个 SSE 事件（多行 data 拼接）；EOF 返回 None。"""
        event_name = ""
        data_lines = []
        while True:
            line = self._read_raw_line()
            if line is None:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text == "":
                if event_name or data_lines:
                    break                  # 空行 = 事件边界
                continue
            if text.startswith(":"):
                continue
            if text.startswith("event:"):
                event_name = text[6:].strip()
                continue
            if text.startswith("data:"):
                data_lines.append(text[5:].strip())
        if not data_lines:
            return None if (not event_name) else (event_name, b"")
        return (event_name, "\n".join(data_lines).encode("utf-8"))

    def _read_raw_line(self):
        """从上游响应读一行（含换行符）；EOF 返回 None。"""
        while b"\n" not in self._buf:
            if self._closed:
                return None
            try:
                chunk = self._resp.read(8192)
            except Exception:
                return None
            if not chunk:
                return None
            self._buf += chunk
        idx = self._buf.index(b"\n")
        line = self._buf[:idx + 1]
        self._buf = self._buf[idx + 1:]
        return line

    def _fail_account(self, code, message):
        """错误事件 → 账号治理 + 待抛异常（与流外错误同一套分类）。"""
        account = self._account
        if code != CODE_CREDIT_EXHAUSTED and upstream_errors.is_input_too_large(message):
            # 同一份超大 body 换任何号都必败，零动作透传
            text = "Trae 输入过大：%s" % message
            account.last_error = text
            status = 413
        elif code == CODE_CREDIT_EXHAUSTED:
            account.note_balance_cooled("积分不足（code 1005），停车到次日 04:00")
            text = "Trae 上游错误 code=%s：%s" % (code, message)
            status = 402
        elif code in (CODE_RATE_LIMITED, CODE_MODEL_RATE):
            wait = RETRY_AFTER_CAP if code == CODE_RATE_LIMITED else TRANSIENT_COOLDOWN
            if code == CODE_MODEL_RATE:
                account.note_error("模型限流（code 6004）", model=self._model,
                                   cooldown=TRANSIENT_COOLDOWN)
            else:
                account.note_error("限流（code 4008）", cooldown=wait)
            text = "Trae 上游错误 code=%s：%s" % (code, message)
            status = 429
        elif code == CODE_MODEL_BLOCKED:
            account.note_error("该号不支持此模型（code 11102）", model=self._model,
                               cooldown=MODEL_BLOCKED_HOURS * 3600)
            text = "Trae 上游错误 code=%s：%s" % (code, message)
            status = 404
        elif code == CODE_MODEL_CONFIG:
            # 模型在当前通道不可用，不是服务故障：报 404，账号不罚
            account.last_error = "模型配置问题（code 4001，不罚号）"
            text = "Trae 模型不可用（code 4001）：%s" % message
            status = 404
        else:
            account.note_failure("上游错误 code=%s" % code)
            text = "Trae 上游错误 code=%s：%s" % (code, message)
            status = 502
        self._saw_error = True
        self._done = True
        self._pending.append({"error": {
            "message": text, "type": "upstream_error", "code": status}})
        self._error = urllib.error.HTTPError(CHAT_URL, status, text, None, None)

    @property
    def error(self):
        return self._error

    def prime(self):
        """读到首个可用增量（或确认失败）后再交出流：未出内容时还能换号。"""
        return registry.prime_stream(self)

    # ---- Trae 事件 → OpenAI chunk ----
    def _next_chunk(self):
        """产出下一个 OpenAI chunk dict；流收尾后返回 None；错误先吐错误帧再抛。"""
        while True:
            if self._error is not None:
                if self._pending:
                    return self._pending.pop(0)
                raise self._error
            if self._pending:
                return self._pending.pop(0)
            if self._done:
                return None
            ev = self._read_sse_event()
            if ev is None:
                # EOF：空流判定（AgentHub chatOnce 同构）
                if not self._produced and not self._saw_error:
                    self._done = True
                    self._account.note_failure("空流（HTTP 200 无可用内容）")
                    self._error = urllib.error.HTTPError(
                        CHAT_URL, 502,
                        "Trae 上游返回了流但没有任何可用内容"
                        "（空响应，通常为余额耗尽/账号被限）", None, None)
                    continue
                self._done = True
                if self._usage is not None:
                    self._pending.append(self._chunk({"usage": self._usage}))
                self._pending.append(self._chunk({}, finish=self._finish or "stop"))
                continue
            event_name, data = ev
            if not data:
                continue
            try:
                payload = json.loads(data.decode("utf-8", "replace"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            kind = event_name or payload.get("event") or payload.get("type") or ""
            if kind in ("output", "thought"):
                delta = {}
                if isinstance(payload.get("response"), str):
                    delta["content"] = payload["response"]
                elif isinstance(payload.get("content"), str):
                    delta["content"] = payload["content"]
                if isinstance(payload.get("reasoning_content"), str):
                    delta["reasoning_content"] = payload["reasoning_content"]
                tcs = payload.get("tool_calls")
                if isinstance(tcs, list) and tcs:
                    out_calls = []
                    for i, tc in enumerate(tcs):
                        if not isinstance(tc, dict):
                            continue
                        fc = tc.get("function_call") or tc.get("function") or {}
                        if not isinstance(fc, dict):
                            fc = {}
                        args = fc.get("partial_arguments")
                        if not isinstance(args, str):
                            args = fc.get("arguments")
                        if not isinstance(args, str):
                            args = ""
                        idx = tc.get("index")
                        if idx is None:
                            idx = i
                        fn = {"arguments": args}
                        if str(idx) not in self._tool_seen:
                            self._tool_seen.add(str(idx))
                            name = fc.get("name") or ""
                            # 剥 namespace（"ns.name" 只留尾段）
                            if "." in name:
                                name = name.rsplit(".", 1)[-1]
                            fn["name"] = name
                        out_calls.append({"index": idx, "id": tc.get("id"),
                                          "type": "function", "function": fn})
                    if out_calls:
                        delta["tool_calls"] = out_calls
                if not delta:
                    continue
                self._produced = True
                return self._chunk(delta)
            if kind == "token_usage":
                usage = {
                    "prompt_tokens": int(payload.get("prompt_tokens")
                                         or payload.get("prompt") or 0) or 0,
                    "completion_tokens": int(payload.get("completion_tokens")
                                             or payload.get("completion") or 0) or 0,
                    "total_tokens": int(payload.get("total_tokens")
                                        or payload.get("total") or 0) or 0,
                }
                for k, v in payload.items():
                    if isinstance(v, (int, float)) and k not in usage:
                        usage[k] = v
                if not usage["total_tokens"]:
                    usage["total_tokens"] = (usage["prompt_tokens"]
                                             + usage["completion_tokens"])
                self._usage = usage
                continue
            if kind in ("done", "turn_completion"):
                fr = payload.get("finish_reason") or payload.get("finishReason")
                if fr:
                    self._finish = str(fr)
                continue
            if kind == "error":
                try:
                    code = int(payload.get("code") or 0)
                except (TypeError, ValueError):
                    code = 0
                message = str(payload.get("message") or payload.get("msg")
                              or ("上游错误 %s" % code))
                self._fail_account(code, message)
                continue
            # metadata / timing_cost / extra_info 忽略

    def _chunk(self, delta, finish=None):
        choice = {"index": 0, "delta": delta, "finish_reason": finish}
        return {"id": self._chat_id, "object": "chat.completion.chunk",
                "created": self._created, "model": self._model,
                "choices": [choice]}

    # ---- 对外接口：核心通用分支消费面 ----
    def __iter__(self):
        return self

    def __next__(self):
        if self._closed:
            raise StopIteration
        chunk = self._next_chunk()
        if chunk is None:
            raise StopIteration
        return ("data: " + json.dumps(chunk, ensure_ascii=False)
                + "\n\n").encode("utf-8")

    def read(self, n=-1):
        """非流聚合路径：读完整个流拼成一份 SSE 文本。"""
        if self._closed:
            return b""
        parts = []
        total = 0
        try:
            for line in self:
                parts.append(line)
                total += len(line)
                if n is not None and n > 0 and total >= n:
                    break
        except StopIteration:
            pass
        return b"".join(parts)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._resp.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# ---------------------------------------------------------------------------
# 出站流：轮换主循环（401 换发重试一次，随后换号）
# ---------------------------------------------------------------------------
def classify_upstream_error(exc):
    """(kind, status)；kind 决定账号治理动作。"""
    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        if code == 401:
            return "relogin", 401
        if code == 402:
            return "credit", 402
        if code == 429:
            return "rate", 429
        if code == 404:
            # 多半是"该号不支持此模型"或域失效：短冷却换号
            return "not_found", 404
        if code == 400:
            return "fatal", 400
        if code >= 500:
            return "server", 502
        return "server", code
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError,
                        OSError)):
        return "server", 502
    text = str(exc)
    if "1005" in text:
        return "credit", 402
    if "4008" in text:
        return "rate", 429
    if "11102" in text or "service info not found" in text.lower():
        return "model_blocked", 404
    if "4001" in text or "model config" in text.lower():
        return "model_config", 502
    return "server", 502


def _retry_after(headers):
    try:
        return min(RETRY_AFTER_CAP, max(1.0, float(headers.get("Retry-After") or 0)))
    except Exception:
        return TRANSIENT_COOLDOWN


def open_stream(ctx, payload, session_key=None, realm=None):
    """按账号池开出一条 Trae 上游流。返回 (响应对象, 归属信息 dict)。

    治理链与 workbuddy.open_stream 同构：
      - 429/5xx/断连：冷却该号换下一把重试；
      - 401：先换发一次重试，仍 401 换下一把；换发连续失败 3 次停用；
      - 402/积分不足（1005）：停车到次日 04:00 换下一把；
      - 11102：账号×模型负缓存换下一把；
      - 400/4001：请求本身问题直接抛（4001 不罚号只短冷却）。
    抛出的异常类型与核心翻译面约定一致：
      - ratelimit.RateLimited：模型级限流（429），带 Retry-After；
      - 其他 HTTPError/URLError：最后一次失败原样抛出；
      - RuntimeError("no usable account...")：池子空了（核心翻 503）。
    """
    pool = ctx.pool
    realm = realm or "trae"
    model = str(payload.get("model") or "").strip()
    if model.lower().startswith(ROUTE_PREFIX + "/"):
        model = model[len(ROUTE_PREFIX) + 1:].strip()
    model = _norm_config(model)
    if not model:
        raise RuntimeError("trae: empty model")
    body = dict(payload)
    body["model"] = model
    forwarded = upstream_body.build_upstream_body(body, ctx.system_prompt)
    header_timeout, idle_timeout = ctx.upstream_timeouts()
    total = max(1, pool.count_ready(realm, model=model)) if pool else 1
    attempts, deadline = net.request_budget(total)
    connect_timeout = ctx.upstream_connect_timeout()
    tried = set()
    last_error = None
    last_429 = None
    last_429_detail = ""

    for _ in range(attempts):
        if time.monotonic() >= deadline:
            break
        account = pool.pick_for_session(realm=realm, session_key=session_key,
                                        exclude=tried, model=model) if pool else None
        if account is None:
            break
        if account.realm != realm:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            continue
        tried.add(account.uid)
        token, err = ensure_token(account)
        if token is None:
            _log("trae account %s: %s, rotating" % (account.uid[:8], err), ctx)
            account.last_error = err
            last_error = RuntimeError("Trae 账号 %s %s" % (account.uid[:8], err))
            continue
        url = CHAT_URL
        req_body = json.dumps(rewrite_body(model, forwarded, account),
                              ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, method="POST",
                                     headers=build_headers(account, token, url))
        try:
            resp = net.urlopen(req, timeout=header_timeout, proxy=account.proxy,
                               connect_timeout=connect_timeout)
            net.set_stream_idle_timeout(resp, idle_timeout)
        except urllib.error.HTTPError as exc:
            raw = net.read_http_error(exc, 600)
            detail = raw.decode("utf-8", "replace") if raw else ""
            code_txt = detail
            blob = None
            try:
                blob = json.loads(detail)
                if isinstance(blob, dict):
                    code_txt = str(blob.get("code") or blob.get("message")
                                   or detail[:300])
            except Exception:
                pass
            if upstream_errors.is_input_too_large(detail):
                # 请求本身超限：换号必白撞，零动作透传
                raise urllib.error.HTTPError(
                    url, 413, "Trae 输入过大（不罚号）：%s" % detail[:300],
                    exc.headers, None)
            kind, _status = classify_upstream_error(exc)
            try:
                body_code = int(blob.get("code")) if isinstance(blob, dict) else None
            except (TypeError, ValueError):
                body_code = None
            if body_code == CODE_MODEL_CONFIG \
                    and kind not in ("relogin", "credit", "rate", "not_found"):
                kind = "model_config"
            if kind == "relogin":
                # 流外 401：换 token 重试一次；仍 401 换号
                token2, err2 = ensure_token(account)
                if token2 is not None:
                    retry = urllib.request.Request(
                        url, data=req_body, method="POST",
                        headers=build_headers(account, token2, url))
                    try:
                        resp2 = net.urlopen(retry, timeout=header_timeout,
                                            proxy=account.proxy,
                                            connect_timeout=connect_timeout)
                        net.set_stream_idle_timeout(resp2, idle_timeout)
                        account.note_success(model=model)
                        return (TraeChatStream(resp2, model, account, ctx.log),
                                {"account": account.uid, "realm": realm,
                                 "account_obj": account})
                    except urllib.error.HTTPError as exc2:
                        exc = exc2
                    except Exception as exc2:
                        account.note_failure("连接异常：%s" % str(exc2)[:120])
                        last_error = exc2
                        continue
                _log("trae account %s: %s, rotating" % (account.uid[:8], err2), ctx)
                account.last_error = err2 or "凭证失效（401）"
                last_error = urllib.error.HTTPError(
                    url, 401, "Trae 账号 %s 凭证失效，已自动换号重试"
                    % account.uid[:8], exc.headers, None)
                continue
            if kind == "credit":
                msg = ("积分不足（code 1005）" if "1005" in code_txt
                       else (code_txt[:150] or "HTTP 402"))
                account.note_balance_cooled(msg)
                _log("trae account %s out of credits, parked until 04:00"
                     % account.uid[:8], ctx)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = urllib.error.HTTPError(
                    url, 402, "Trae 账号 %s %s，已自动换号"
                    % (account.uid[:8], msg), exc.headers, None)
                continue
            if kind == "rate":
                wait = _retry_after(exc.headers)
                account.note_error("限流（HTTP 429，冷却 %ds）" % int(wait),
                                   cooldown=wait, detail=detail)
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error, last_429, last_429_detail = exc, exc, detail
                continue
            if kind == "not_found":
                if "11102" in code_txt or "service info" in code_txt.lower():
                    account.note_error("该号不支持此模型（11102）", model=model,
                                       cooldown=MODEL_BLOCKED_HOURS * 3600)
                else:
                    account.note_failure("HTTP 404：%s" % code_txt[:120])
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = exc
                continue
            if kind == "model_config":
                # 模型在当前通道不可用：不罚号，换下一把（不同账号权限可能不同）
                account.last_error = "模型配置问题（code 4001，不罚号）"
                if session_key and pool:
                    pool.affinity.unbind(session_key)
                last_error = exc
                continue
            if kind == "fatal":
                account.last_error = "Trae 上游拒绝请求（400）：%s" % code_txt[:200]
                raise urllib.error.HTTPError(
                    url, 400, "Trae 上游拒绝请求（400）：%s" % code_txt[:300],
                    exc.headers, None)
            # server / other
            account.note_failure("HTTP %s：%s" % (exc.code, code_txt[:120]))
            if session_key and pool:
                pool.affinity.unbind(session_key)
            last_error = exc
            continue
        except Exception as exc:
            if session_key and pool:
                pool.affinity.unbind(session_key)
            if net.looks_like_local_network(exc):
                _log("trae account %s: local network failure (%s), no penalty"
                     % (account.uid[:8], type(exc).__name__), ctx)
                last_error = exc
                continue
            if net.is_transient(exc):
                account.note_unknown_failure("connection: %s" % type(exc).__name__)
                _log("trae account %s: upstream connection hiccup (%s), rotating"
                     % (account.uid[:8], type(exc).__name__), ctx)
            else:
                account.note_unknown_failure(str(exc)[:120])
                account.note_error(str(exc)[:120], cooldown=60)
            last_error = exc
            continue
        stream = TraeChatStream(resp, model, account, ctx.log)
        try:
            verdict = stream.prime()
        except Exception as exc:
            stream.close()
            if session_key and pool:
                pool.affinity.unbind(session_key)
            account.note_unknown_failure(str(exc)[:120])
            last_error = exc
            _log("trae account %s: stream prime failed (%s), rotating"
                 % (account.uid[:8], type(exc).__name__), ctx)
            continue
        if verdict != "ready":
            # 未出内容就失败（流内 1005/4008/11102、空流）：罚则已由流内完成，
            # 换下一把重开；400/403 是请求或渠道级问题，换号无用
            stream.close()
            error = stream.error
            status = int(getattr(error, "code", 0) or 502)
            message = str(error) if error is not None else "上游没有返回可用内容"
            if status in (400, 403, 413):
                raise error or urllib.error.HTTPError(
                    CHAT_URL, status, message, None, None)
            if status == 429:
                last_error, last_429 = error, error
                last_429_detail = message
            else:
                last_error = urllib.error.HTTPError(
                    CHAT_URL, status, "Trae 账号 %s：%s（已自动换号）"
                    % (account.uid[:8], message), None, None)
            if session_key and pool:
                pool.affinity.unbind(session_key)
            _log("trae account %s failed before content: HTTP %s %s"
                 % (account.uid[:8], status, message[:120]), ctx)
            continue
        account.note_success(model=model)
        return (stream,
                {"account": account.uid, "realm": realm, "account_obj": account})

    if last_error is not None:
        if last_429 is not None:
            from core import ratelimit
            exc = ratelimit.RateLimited(last_429, last_429_detail,
                                        wait=RETRY_AFTER_CAP)
            exc.account_uid = None
            raise exc
        raise last_error
    raise RuntimeError("no usable account for realm '%s': all are disabled, "
                       "cooling down, or do not support this model" % realm)


# ---------------------------------------------------------------------------
# 模型目录（get_detail_param 双档发现；AgentHub fetchModels 对齐）
# ---------------------------------------------------------------------------
def _parse_contact_config(item):
    """display_contact_config（内嵌 JSON 字符串）→ 消费倍率/会员折扣/多模态/推理。

    字段结构实证自 2026-10-15 抓包：consumption_rate.rate 是倍率，
    discount.data 里的 member_discount（折扣百分比）+ consumption_rate 是
    会员折后价，multimodal.enable/reasoning.enable 是能力开关。
    """
    raw = item.get("display_contact_config")
    if isinstance(raw, str):
        try:
            cfg = json.loads(raw)
        except Exception:
            cfg = {}
    elif isinstance(raw, dict):
        cfg = raw
    else:
        cfg = {}
    rate = ""
    member_rate = ""
    try:
        cr = ((cfg.get("consumption_rate") or {}).get("data") or {}).get("rate")
        if isinstance(cr, (int, float)) and cr > 0:
            rate = ("%g" % cr) + "x"
        disc = ((cfg.get("discount") or {}).get("data") or {})
        mr = disc.get("consumption_rate")
        if isinstance(mr, (int, float)) and mr > 0:
            member_rate = ("%g" % mr) + "x"
    except Exception:
        pass
    try:
        multimodal = bool(((cfg.get("multimodal") or {}).get("enable")))
    except Exception:
        multimodal = False
    try:
        reasoning = bool(((cfg.get("reasoning") or {}).get("enable")))
    except Exception:
        reasoning = False
    return rate, member_rate, multimodal, reasoning


def _meta_richness(meta):
    """目录条目数据丰富度打分（同名孪生条目择优用）。

    倍率/窗口/输出/能力各有其分；shadow 条目（无 contact 配置的残缺孪生）
    天然低分被淘汰。分数无绝对意义，只用于比较。
    """
    if not isinstance(meta, dict):
        return 0
    score = 0
    if meta.get("credits"):
        score += 4
    if meta.get("context_length"):
        score += 3
    if meta.get("max_output_tokens"):
        score += 1
    if meta.get("supportsReasoning"):
        score += 1
    if meta.get("supportsImages"):
        score += 1
    if meta.get("fee_level"):
        score += 1
    return score


def _model_meta_from_item(it):
    """官方目录条目 → /v1/models meta 字典（字段实证自 2026-10-15 抓包）。

      context_window_tokens: {dev: 256000, max: ...}  上下文窗口（按环境分档，取最大）
      model_detail_list[].max_tokens                  输出上限（每档一个条目，取最大）
      display_config: display_name / model_capability
                      (reasoning_model) / multimodal / fee_model_level
    多档位取最大值，与 AgentHub traeLimits 口径一致，避免少报。
    """
    if not isinstance(it, dict):
        return None
    mid = str(it.get("config_name") or it.get("configName") or "").strip()
    if not mid:
        return None
    dc = it.get("display_config") if isinstance(it.get("display_config"), dict) else {}
    display_name = str(dc.get("display_name") or dc.get("displayName")
                       or dc.get("name") or "").strip()
    # 对齐 AgentHub v1.79.0：空显示名是租户自定义模型的占位模板，
    # config_switch=false 是已下线条目，二者都不是可选项。
    # is_invisible_to_user 不在此列——本地实测那批老模型仍可调用，
    # 沿用上面的「两档全收」策略。
    if not display_name:
        return None
    if it.get("config_switch") is False or it.get("configSwitch") is False:
        return None
    meta = {"name": mid}
    if display_name != mid:
        meta["display_name"] = display_name
        meta["name"] = display_name
    meta["fee_level"] = int(dc.get("fee_model_level") or 0)
    if dc.get("is_beta"):
        meta["is_beta"] = True
    if dc.get("is_new"):
        meta["is_new"] = True

    # 上下文窗口：分档字典取最大；输出上限：model_detail_list 各档 max_tokens 取最大
    ctx = 0
    cw = it.get("context_window_tokens")
    if isinstance(cw, dict) and not isinstance(cw, list):
        for v in cw.values():
            try:
                n = int(v)
                if n > ctx:
                    ctx = n
            except (TypeError, ValueError):
                continue
    elif cw is not None:
        try:
            ctx = int(cw)
        except (TypeError, ValueError):
            ctx = 0
    max_out = 0
    details = it.get("model_detail_list")
    if isinstance(details, list):
        for det in details:
            if isinstance(det, dict):
                try:
                    n = int(det.get("max_tokens") or 0)
                    if n > max_out:
                        max_out = n
                except (TypeError, ValueError):
                    continue
    if ctx > 0:
        meta["context_length"] = ctx
        meta["maxInputTokens"] = ctx       # 核心标注链读法
    if max_out > 0:
        meta["max_output_tokens"] = max_out
        meta["maxOutputTokens"] = max_out

    # 能力：官方 multimodal / model_capability 优先，内嵌 contact_config 兜底
    rate, member_rate, cc_multi, cc_reason = _parse_contact_config(it)
    vision = bool(dc.get("multimodal")) or cc_multi
    thinks = str(dc.get("model_capability") or "") == "reasoning_model" or cc_reason
    if vision:
        meta["supportsImages"] = True
    if thinks:
        meta["supportsReasoning"] = True
    try:
        extra = json.loads(it.get("extra_config") or "{}")
        if isinstance(extra, dict) and extra.get("native_function_call"):
            meta["supportsToolCall"] = True
    except Exception:
        pass
    if rate:
        meta["credits"] = rate
    if member_rate and member_rate != rate:
        meta["member_credits"] = member_rate
    return meta


_discovered = {"at": 0.0, "catalog": {}}
_discover_fail_at = [0.0]
_discover_lock = threading.Lock()


def _token_for_discovery(ctx=None):
    """目录拉取用的一个启用账号；没有可用账号返回 None。

    必须返回完整账号对象（build_headers 要带 uid 的 x-uid 头——AgentHub
    实证注释「官方客户端恒带，缺了是风控识别点」，缺它目录接口直接 401）。
    """
    pool = getattr(ctx, "pool", None)
    candidates = [a for a in (pool.accounts if pool else [])
                  if a.realm == "trae" and a.enabled and a.refresh_token]
    for account in candidates:
        token, _err = ensure_token(account)
        if token is not None:
            return account
    return None


def _discover_ids(timeout, ctx=None, log=None):
    """get_detail_param 拉官方目录 → {config_name: meta}（带完整模型元数据）。

    solo_work_lite 与 solo_agent 两个档都拉并合并：lite 档是默认对话目录，
    agent 档多出 qwen3.8-flash / kimi-k2.8-preview / glm-4.6 等 30 个
    （官方客户端模型选择器可见）。两档同名条目以数据丰富度择优。
    同时回填 FUNCTION_MAP：仅在 agent 档出现的可对话模型自动标记为
    agent 档调用，免去手维护映射表。
    """
    headers = {"Content-Type": "application/json", "accept": "*/*",
               "user-agent": USER_AGENT, "referer": MODELS_URL}
    account = _token_for_discovery(ctx)
    if account is not None:
        token, _err = ensure_token(account)
        if token is not None:
            headers = build_headers(account, token, MODELS_URL)

    def _fetch(fn):
        body = json.dumps({"function": fn, "config_names": None,
                           "need_prompt": False, "current_config_info": None,
                           "poly_prompt": True}).encode("utf-8")
        last = None
        for url in [MODELS_URL, MIRROR_MODELS_URL]:
            if not url:
                continue
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers=headers)
            try:
                with net.urlopen(req, timeout=timeout) as resp:
                    blob = json.loads(resp.read().decode("utf-8", "replace"))
            except Exception as exc:
                last = exc
                continue
            items = None
            for key in ("config_info_list", "configInfoList"):
                v = blob.get(key) if isinstance(blob, dict) else None
                if isinstance(v, list) and v:
                    items = v
                    break
            if items is None and isinstance(blob, dict):
                data = blob.get("data")
                if isinstance(data, dict):
                    for key in ("config_info_list", "configInfoList"):
                        v = data.get(key)
                        if isinstance(v, list) and v:
                            items = v
                            break
            if items is not None:
                return items
            last = RuntimeError("empty model list")
        raise last or RuntimeError("unreachable")

    catalog = {}
    agent_only_ids = set()
    for i, fn in enumerate(DISCOVERY_FUNCTIONS):
        try:
            items = _fetch(fn)
        except Exception as exc:
            if log:
                log("trae catalog '%s' failed: %s" % (fn, exc))
            if catalog:
                continue           # 已有至少一档成功，缺档不致命
            raise
        for it in items or []:
            meta = _model_meta_from_item(it)
            if not meta:
                continue
            mid = str(it.get("config_name")).strip()
            # 官方「选择器可见性」由 access.identity_list 决定（含 0 = 普通用户
            # 可见；invisible_to_user 只是桌面端 UI 藏旧模型的开关，接口层
            # 照常可调）。策略：两档条目全收——老客户端对 invisible 模型实测
            # 可正常调用（glm-4.6/minimax-m2/kimi-k2-0905 等），只剔除
            # 内部功能条目与 -auto 派生档（官方 agent 自动路由的影子条目）。
            lower = str(mid).lower()
            if lower.endswith(("-auto", "_auto")) or "for-auto" in lower \
                    or lower in ("title_generation", "input_optimization",
                                 "search_agent_qwen_fast",
                                 "search_agent_qwen_fast-0710"):
                continue
            # 同名条目择优保留：官方目录存在配置残缺的孪生条目（如
            # glm-5.3-flash 有两条——优质条目带倍率/窗口/思考，阴影条目
            # 无倍率无窗口），按数据丰富度打分，高分者留，低分者不覆盖。
            existing = catalog.get(mid)
            if existing is not None:
                if _meta_richness(meta) > _meta_richness(existing):
                    catalog[mid] = meta
                continue
            catalog[mid] = meta
            if i > 0 and mid not in agent_only_ids:
                agent_only_ids.add(mid)
    # agent 档独有的可对话模型自动挂 agent 档调用标记
    for mid in agent_only_ids:
        want = _norm(mid)
        if not any(_norm(k) == want for k in FUNCTION_MAP) \
                and not str(mid).startswith(("custom_model", "title_", "input_")):
            FUNCTION_MAP[mid] = "solo_agent"
    if catalog:
        return catalog
    raise RuntimeError("empty model list")


def static_models():
    """静态兜底（官方目录不可达时）。

    静态表只有裸名没有官方倍率——按「无倍率不展示」的口径这里恒为空列表，
    即官方目录拉不到时 Trae 出口如实显示「暂无模型」，不拿无倍率名单充数。
    """
    return []


def live_models(realm, force=False, ctx=None, log=None):
    """[(id, meta)]：动态目录优先（带完整元数据），失败回退缓存/静态兜底。

    force=True（面板手动刷新）：只认上游 API，拿不到返回 []。
    """
    if realm not in ("trae", None):
        return []
    if not force:
        with _discover_lock:
            cached_ok = _discovered["catalog"] \
                and time.time() - _discovered["at"] < MODELS_TTL
            catalog = dict(_discovered["catalog"])
        if cached_ok:
            return _sorted_catalog(catalog)
        if time.time() - _discover_fail_at[0] < DISCOVER_FAIL_QUIET:
            return _sorted_catalog(catalog)
    try:
        catalog = _discover_ids(DISCOVERY_TIMEOUT, ctx=ctx, log=log)
    except Exception as exc:
        with _discover_lock:
            _discover_fail_at[0] = time.time()
        if log:
            log("trae model discovery failed: %s" % exc)
        if force:
            return []
        with _discover_lock:
            cached = dict(_discovered["catalog"])
        return _sorted_catalog(cached) or static_models()
    with _discover_lock:
        _discovered["at"] = time.time()
        _discovered["catalog"] = dict(catalog)
    return _sorted_catalog(catalog)


def _sorted_catalog(catalog):
    # 官方没给消费倍率的条目整条不展示（用户口径 2026-10-18：无倍率 = 无法
    # 折算积分扣减，列出来只会误导选用）；内部功能条目（subagent/summary 等）
    # 本来就不带倍率，一并被挡掉。
    # 与原二开同口径：动态目录保持官方应答的条目顺序，不按字母重排。
    return [(mid, dict(meta or {"name": mid}))
            for mid, meta in catalog.items() if (meta or {}).get("credits")]


# ---------------------------------------------------------------------------
# 探测（面板「测试」按钮；经 realm 配置注入 auth.accounts）
# ---------------------------------------------------------------------------
def probe_account(account, timeout=20):
    """真发一条最小流式对话验证连通性；只做诊断，不触碰账号治理状态。"""
    if not account.refresh_token:
        return {"ok": False, "message": "该账号没有 refreshToken，请重新登录"}
    token, err = ensure_token(account)
    if token is None:
        return {"ok": False, "message": err}
    url = CHAT_URL
    body = {"model": PROBE_MODEL,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8, "stream": False}
    payload = json.dumps(rewrite_body(PROBE_MODEL, body, account),
                         ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers=build_headers(account, token, url))
    started = time.time()
    try:
        with net.urlopen(req, timeout=timeout, proxy=account.proxy) as resp:
            raw = resp.read(256)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(300).decode("utf-8", "replace")
        except Exception:
            detail = ""
        return {"ok": False, "message": "上游 HTTP %s：%s"
                % (exc.code, detail[:150] or "无详情")}
    except Exception as exc:
        return {"ok": False, "message": "请求异常: %s" % exc}
    if not raw:
        return {"ok": False, "message": "上游未返回任何数据"}
    elapsed = int((time.time() - started) * 1000)
    return {"ok": True, "model": PROBE_MODEL, "latencyMs": elapsed,
            "message": "Trae 账号连通正常（%s，%d ms）" % (PROBE_MODEL, elapsed)}


# ---------------------------------------------------------------------------
# 额度查询（v2 现行 + v1 兜底；401+code1001 = 积分服务未开放，不是凭证失效）
# ---------------------------------------------------------------------------
_CREDITS_TTL = 120
_credits_cache = {}     # uid -> (at, result)


def _dig(obj, pattern):
    """深度递归找第一个匹配 key 的值（AgentHub util.dig 同语义）。

    官方响应里 credits_limit 藏在 entitlement_base_info.quota 子对象，
    包顶层没有——只扫顶层的实现会全部落空（2026-10-15 实测踩坑）。
    """
    import re
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.match(pattern, str(k)):
                return v
        for v in obj.values():
            hit = _dig(v, pattern)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for it in obj:
            hit = _dig(it, pattern)
            if hit is not None:
                return hit
    return None


def _parse_credit_packs(packs):
    """订阅包 → (总剩余, 最近到期 ts)。

    对照 AgentHub traeCredits：三条过滤在 entitlement_base_info 层直接读
    （隐藏包 is_hide / 已取消 status=3 / 兑换码包 product_type=3，不做全域
    dig 以免误吃别处的 status）；credits_limit=0 的包不属于该号（如免费档
    只给功能开关位）；limit<0 是不限量哨兵；消耗 usage.credits_amount 只在
    部分包上出现；到期取 expire_time/end_time。
    """
    total = 0.0
    unlimited = False
    expires = []
    now = time.time()
    for p in packs or []:
        if not isinstance(p, dict):
            continue
        base = p.get("entitlement_base_info")
        base = base if isinstance(base, dict) else None
        if base is not None:
            if base.get("is_hide") is True or p.get("is_hide") is True:
                continue
            try:
                status = int(base.get("ent_status") or base.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
            if status == 3:
                continue
            try:
                ptype = int(base.get("product_type") or 0)
            except (TypeError, ValueError):
                ptype = 0
            if ptype == 3:
                continue
        limit = _dig(p, r"^credits_limit$")
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            limit = 0.0
        if limit == 0:
            continue                       # 无面值 = 这份包不属于该号
        used = _dig(p, r"^credits_amount$")
        try:
            used = float(used or 0)
        except (TypeError, ValueError):
            used = 0.0
        if limit < 0:
            unlimited = True               # 不限量哨兵，不参与求和
            continue
        total += max(0.0, limit - used)
        exp = _dig(p, r"^expire_time$|^end_time$")
        try:
            exp = float(exp or 0)
        except (TypeError, ValueError):
            exp = 0.0
        if exp > now:
            expires.append(exp)
    return (-1 if unlimited else round(total, 2),
            min(expires) if expires else 0)


def get_credits(account, force=False):
    """余额 = user_entitlement_pack_list 全部包 (credits_limit - usage) 求和。

    不限量（limit<0）返回 -1 哨兵；积分服务未开放（401+code1001）返回
    ok+unavailable，不算失败更不罚号。
    """
    uid = str(account.uid or "")
    now = time.time()
    hit = _credits_cache.get(uid)
    if hit and not force and now - hit[0] <= _CREDITS_TTL:
        out = dict(hit[1])
        out["cached"] = True
        return out
    token, err = ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    url_base = CREDITS_BASES[0] + CREDITS_PATHS[0]
    headers = build_headers(account, token, url_base)
    headers["x-user-region"] = "CN"
    body = b"{}"
    last = ""
    for base in CREDITS_BASES:
        for path in CREDITS_PATHS:
            req = urllib.request.Request(base + path, data=body, method="POST",
                                         headers=headers)
            try:
                with net.urlopen(req, timeout=30, proxy=account.proxy) as resp:
                    blob = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                try:
                    detail = exc.read(400).decode("utf-8", "replace")
                except Exception:
                    detail = ""
                try:
                    blob = json.loads(detail)
                except Exception:
                    blob = {}
                code = int((blob or {}).get("code") or 0)
                if exc.code in (401, 403) and code == 1001:
                    out = {"ok": True, "unavailable": True,
                           "message": "积分服务未对该账号开放（code 1001）",
                           "cached": False}
                    _credits_cache[uid] = (now, dict(out))
                    return out
                if exc.code == 401:
                    return {"ok": False, "authError": True,
                            "error": "凭证失效（HTTP 401）"}
                last = "HTTP %s %s" % (exc.code, detail[:120])
                continue
            except Exception as exc:
                last = str(exc)[:200]
                continue
            packs = None
            if isinstance(blob, dict):
                data = blob.get("data") if isinstance(blob.get("data"), dict) else blob
                for key in ("user_entitlement_pack_list", "userEntitlementPackList"):
                    v = data.get(key)
                    if isinstance(v, list):
                        packs = v
                        break
            credits, expires_at = _parse_credit_packs(packs)
            if credits != 0 or expires_at:
                out = {"ok": True, "credits": credits,
                       "expiresAt": int(expires_at), "cached": False}
                _credits_cache[uid] = (now, dict(out))
                return out
            last = "上游未返回可用订阅包（%s）" % ("空列表" if packs is not None else "缺字段")
    return {"ok": False, "error": last or "额度接口不可达"}


def credits_for_account(account, force=False):
    """auth.accounts 注入的 credits_fn：查余额并落到 account.credits。

    形状与共享池余额视图对齐（remain/size/packages），remain=-1 表示不限量；
    积分服务未开放时不覆盖已有余额视图（面板显示「未开放」由 unavailable 标记）。
    """
    res = get_credits(account, force=force)
    if res.get("unavailable"):
        return {"ok": True, "unavailable": True,
                "message": res.get("message") or "积分服务未开放"}
    if not res.get("ok"):
        return res
    credits = -1 if res.get("credits") == -1 else float(res.get("credits") or 0)
    account.credits = {
        "remain": credits,
        "unlimited": credits == -1,
        "size": None,
        "packages": [],
        "expiresAt": res.get("expiresAt") or 0,
        "updated_at": time.time(),
        "updated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if account.accounts_dir:
        try:
            account.save(account.accounts_dir)
        except Exception:
            pass
    return {"ok": True, "credits": account.credits}


# ---------------------------------------------------------------------------
# 每日签到（checkin_credits；AgentHub trae.checkinStatus/checkin 同款移植）
# 状态查询：GET+did（Bearer token）为主，POST+Cloud-IDE-JWT 兜底；领取固定
# POST+Cloud-IDE-JWT。官方 code 1001 = 签到服务未对该账号开放（unavailable，
# 不算失败更不罚号）；「已签到」文案 = 幂等成功。本组函数零惩罚不碰账号状态。
# 是否已签以本地台账（usage/trae_checkins.json）为准。
# ---------------------------------------------------------------------------
CHECKIN_BASES = ["https://api.trae.cn", "https://api.trae.com.cn"]

# 本地签到台账：{"YYYY-MM-DD": {uid: {"ts":…, "credits":…}}}，保留 60 天。
# 官方 status 对部分账号永远报未开放（1001），拿不到真实「已签」状态——
# 是否已签以本地台账为准（手动一键与调度器共用）。台账放明细目录（usage/）：
# 删明细 = 台账清零，重签直接按成功处理（二开用户口径 2026-10-16）。
CHECKIN_LEDGER_FILENAME = "trae_checkins.json"
_checkin_ledger = None
_LEDGER_DIR = [""]


def init_ledger_dir(usage_dir):
    _LEDGER_DIR[0] = usage_dir or ""


def _ledger_path():
    return os.path.join(_LEDGER_DIR[0] or ".", CHECKIN_LEDGER_FILENAME)


def _ledger_load():
    global _checkin_ledger
    with _lock:
        if _checkin_ledger is not None:
            return _checkin_ledger
        try:
            with open(_ledger_path(), encoding="utf-8") as fh:
                blob = json.load(fh)
            _checkin_ledger = blob if isinstance(blob, dict) else {}
        except Exception:
            _checkin_ledger = {}
        return _checkin_ledger


def _ledger_save():
    path = _ledger_path()
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_checkin_ledger or {}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _business_day(ts=None):
    """Trae 业务日：客户端按 UTC+8 日期切日（serverTime + 8h），与宿主时区无关。"""
    ts = time.time() if ts is None else ts
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(float(ts) + 8 * 3600))
    except (TypeError, ValueError):
        return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))


def _ledger_mark(uid, credits=None):
    """记「今天已签」。credits 为官方回查到的累计积分（可空）。"""
    ledger = _ledger_load()
    today = _business_day()
    with _lock:
        day = ledger.setdefault(today, {})
        entry = {"ts": time.time()}
        if credits is not None:
            entry["credits"] = credits
        day[str(uid)] = entry
        # 只留近 60 天，防文件无限长大
        if len(ledger) > 60:
            for k in sorted(ledger.keys())[:-60]:
                ledger.pop(k, None)
        try:
            _ledger_save()
        except Exception:
            pass


def _ledger_clear(uid):
    ledger = _ledger_load()
    today = _business_day()
    with _lock:
        day = ledger.get(today)
        if not isinstance(day, dict) or str(uid) not in day:
            return
        day.pop(str(uid), None)
        if not day:
            ledger.pop(today, None)
        try:
            _ledger_save()
        except Exception:
            pass


def ledger_today(uid):
    ledger = _ledger_load()
    day = ledger.get(_business_day()) or {}
    hit = day.get(str(uid))
    return dict(hit) if isinstance(hit, dict) else None


def _checkin_fields(blob):
    """签到响应字段：顶层与 data 嵌套都认（官方两种壳都出现过）。"""
    if not isinstance(blob, dict):
        return {}
    out = {k: v for k, v in blob.items() if k != "data"}
    d = blob.get("data")
    if isinstance(d, dict):
        for k, v in d.items():
            out.setdefault(k, v)
    return out


def _checkin_int(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _checkin_auth_headers(token, did, bearer=False):
    h = {
        "content-type": "application/json",
        "accept": "application/json",
        "authorization": ("Bearer " if bearer else "Cloud-IDE-JWT ") + token,
        "x-user-region": "CN",
        "x-device-id": did,
        "origin": "https://www.trae.cn",
        "referer": "https://www.trae.cn/",
    }
    if bearer:
        h["x-app-type"] = "trae"
    return h


def checkin_status(account, timeout=30, use_ledger=True):
    """签到状态查询（零副作用，可随便调）。

    返回 {ok, checkedIn, unavailable, ...}：checkedIn=True 今日已签；
    unavailable=True 官方签到服务未对该账号开放（code 1001，不算错误）。
    官方拿不到状态时用本地签到台账兜底（台账记着今天签过 = 已签）。
    use_ledger=False 用于校验台账本身：只信官方状态，不让台账自我证明。
    """
    token, err = ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    did, _mid = device_ids(str(account.uid or "") or "anon")
    last = ""
    for base in CHECKIN_BASES:
        tries = [
            # 主：GET + did（cockpit 现行口径，Bearer token）
            ("GET", base + "/trae/api/v2/ug/checkin_credits/status?did=" + did,
             _checkin_auth_headers(token, did, bearer=True), None),
            # 兜底：POST（Cloud-IDE-JWT，不带 x-app-type/origin）
            ("POST", base + "/trae/api/v2/ug/checkin_credits/status",
             {"content-type": "application/json", "accept": "application/json",
              "authorization": "Cloud-IDE-JWT " + token,
              "x-user-region": "CN", "x-device-id": did}, b"{}"),
        ]
        for method, url, headers, body in tries:
            req = urllib.request.Request(url, data=body, method=method,
                                         headers=headers)
            try:
                with net.urlopen(req, timeout=timeout, proxy=account.proxy) as resp:
                    blob = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                try:
                    blob = json.loads(exc.read(600).decode("utf-8", "replace"))
                except Exception:
                    blob = {}
                if not isinstance(blob, dict) or not blob:
                    last = "HTTP %s" % exc.code
                    continue
            except Exception as exc:
                last = str(exc)[:200]
                continue
            code = int((blob.get("code") or 0))
            if code == 1001:
                # 官方说未开放 = 官方口径拿不到已签状态；本地台账记着今天
                # 签过就按已签回答（否则面板徽标每天都被 1001 打回「未开放」）
                local = ledger_today(account.uid) if use_ledger else None
                if local:
                    return {"ok": True, "checkedIn": True, "local": True,
                            "credits": _checkin_int(local.get("credits")),
                            "message": "今日已签到（本地记录）"}
                return {"ok": True, "unavailable": True, "checkedIn": False,
                        "message": "签到服务未对该账号开放（官方接口 code 1001）"}
            if code not in (0, 200):
                last = str(blob.get("message") or ("HTTP code %s" % code))
                continue
            f = _checkin_fields(blob)
            checked = bool(f.get("checked_in") or f.get("checkedIn"))
            return {
                "ok": True,
                "checkedIn": checked,
                "enable": bool(f.get("enable")),
                "credits": _checkin_int(f.get("credits") or f.get("total_credits")),
                "consecutiveDays": _checkin_int(
                    f.get("consecutive_days") or f.get("consecutiveDays")),
                "creditsEarnedToday": _checkin_int(
                    f.get("credits_earned_today") or f.get("creditsEarnedToday")),
                "checkinDate": str(f.get("checkin_date") or f.get("checkinDate") or ""),
                "message": ("今日已签到" if checked else "今日未签到"),
            }
    return {"ok": False, "error": last or "查询签到状态失败"}


def checkin_claim(account, timeout=30):
    """签到领取：POST claim（Cloud-IDE-JWT + x-app-type: trae）。

    是否已签以本地台账为准（官方 status 对部分账号永远报 1001 拿不到）：
    台账记着今天签过 → 直接返回 ok+already，不再打官方接口。code 1001 →
    服务未开放（ok+unavailable）；「已签到」文案 → 幂等成功（ok+already）。
    领取成功/已签后记台账并回查一次状态拿积分明细，回查失败不影响签到结果。
    """
    uid = str(account.uid or "")
    hit = ledger_today(uid)
    if hit:
        # 台账只作缓存：官方状态可查时必须与台账互相印证，避免一次误记
        # 把当天锁死（面板显示已签到、客户端其实还能签）。
        st = checkin_status(account, use_ledger=False)
        confirmed = st.get("ok") and not st.get("unavailable")
        if not confirmed:
            return {"ok": True, "already": True, "local": True,
                    "message": "今日已签到过" + (
                        " · 共 %s 积分" % hit["credits"] if hit.get("credits") else ""),
                    "status": None}
        if st.get("checkedIn"):
            return {"ok": True, "already": True, "local": True,
                    "message": "今日已签到过" + (
                        " · 共 %s 积分" % hit["credits"] if hit.get("credits") else ""),
                    "status": st}
        _ledger_clear(uid)
    token, err = ensure_token(account)
    if token is None:
        return {"ok": False, "error": err}
    did, _mid = device_ids(uid or "anon")
    last = ""
    for base in CHECKIN_BASES:
        req = urllib.request.Request(
            base + "/trae/api/v2/ug/checkin_credits/claim", data=b"{}",
            method="POST", headers=_checkin_auth_headers(token, did))
        try:
            with net.urlopen(req, timeout=timeout, proxy=account.proxy) as resp:
                blob = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                blob = json.loads(exc.read(600).decode("utf-8", "replace"))
            except Exception:
                blob = {}
            if not isinstance(blob, dict) or not blob:
                last = "HTTP %s" % exc.code
                continue
        except Exception as exc:
            last = str(exc)[:200]
            continue
        code = int((blob.get("code") or 0))
        msg = str(blob.get("message") or "")
        if code == 1001:
            return {"ok": True, "unavailable": True,
                    "message": "签到服务未对该账号开放（官方接口 code 1001）"}
        if code not in (0, 200):
            if ("已签到" in msg or "已经签到" in msg or "already" in msg.lower()):
                st = checkin_status(account, use_ledger=False)
                verified = st.get("ok") and not st.get("unavailable")
                if verified and not st.get("checkedIn"):
                    return {"ok": False,
                            "error": "上游返回已签到，但状态查询仍未签到"}
                _ledger_mark(uid, credits=(st.get("credits") if st.get("ok") else None))
                return {"ok": True, "already": True,
                        "message": msg or "今日已签到",
                        "status": st if st.get("ok") else None}
            # 业务码失败不打到备用域（对齐 AgentHub：换域只救网络不通）
            return {"ok": False, "error": msg or ("签到失败（code %s）" % code)}
        st = checkin_status(account, use_ledger=False)
        verified = st.get("ok") and not st.get("unavailable")
        if verified and not st.get("checkedIn"):
            # 领取接口说成功、状态接口说没签：不记台账，留给下一次补签
            return {"ok": False, "error": "签到未生效（上游状态仍未签到）"}
        _ledger_mark(uid, credits=(st.get("credits") if st.get("ok") else None))
        return {"ok": True, "already": False, "message": msg or "签到成功",
                "status": st if st.get("ok") else None}
    return {"ok": False, "error": last or "签到失败"}


def checkin_for_account(account, trigger="unknown"):
    """auth.accounts 注入的 checkin_fn：签到 + 更新账号本地签到戳。"""
    res = checkin_claim(account)
    if res.get("ok") and (res.get("already") or not res.get("unavailable")):
        account.last_checkin = time.strftime("%Y-%m-%d %H:%M:%S")
        if account.accounts_dir:
            try:
                account.save(account.accounts_dir)
            except Exception:
                pass
        try:
            from infra import activity
            activity.record_attempt(account, "checkin", trigger, res)
        except Exception:
            pass
        # 签到带积分入账：立即强制拉一次余额落进账号视图，面板积分列即时
        # 更新（force 越过 60s 缓存；签到服务未开放时不刷——没有入账）
        if not res.get("unavailable"):
            try:
                account.fetch_credits(force=True)
            except Exception:
                pass
    return res


# ---------------------------------------------------------------------------
# 官方授权页登录（PKCE + 本地回环回调；AgentHub beginTraeOAuth 同款流程）
# ---------------------------------------------------------------------------
_login_state = {}       # state -> session dict（同一时刻允许多个标签页各开一次）
_login_state_guard = threading.Lock()


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _pkce_pair():
    verifier = _b64url(os.urandom(48))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def _device_fingerprint(seed):
    """15 位纯数字 deviceId + 64 hex machineId（AgentHub deviceFingerprint 同款）。

    与 device_ids 同思路但算法独立——OAuth 会话的设备指纹只服务
    授权握手，对话请求仍用账号池里的稳定指纹，互不影响。
    """
    h = hashlib.sha256(str(seed or "").encode("utf-8")).hexdigest()
    digits = "".join(c for c in h if c.isdigit())[:15].ljust(15, "0")
    return digits, h


def _login_guidance_host():
    """GetLoginGuidance 下发登录主机（各账号/区域可能不同），失败用兜底域。"""
    body = json.dumps({"loginTraceID": "", "login_trace_id": ""}).encode("utf-8")
    for url in LOGIN_GUIDANCE_URLS:
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"content-type": "application/json",
                     "user-agent": USER_AGENT})
        try:
            with net.urlopen(req, timeout=10) as resp:
                blob = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            continue
        found = [""]

        def _dig(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, str) and \
                            k.lower() in ("loginhost", "login_host",
                                          "loginurl", "login_url", "host"):
                        found[0] = v
                        return True
                    if _dig(v):
                        return True
            elif isinstance(obj, list):
                for it in obj:
                    if _dig(it):
                        return True
            return False

        _dig(blob)
        host = found[0].strip()
        if host:
            if not host.startswith("http"):
                host = "https://" + host.lstrip("/")
            return host.rstrip("/")
    return LOGIN_FALLBACK_HOST


def _build_auth_url(host, callback_url, trace_id, state, challenge,
                    device_id, machine_id):
    """构造官方授权地址（AgentHub buildTraeAuthUrl 逐参数对齐——缺一个都可能被风控）。"""
    q = urllib.parse.urlencode({
        "login_version": "1",
        "auth_from": "solo",
        "login_channel": "native_ide",
        "plugin_version": "local",
        "auth_type": "local",
        "client_id": CLIENT_ID,
        "redirect": "0",
        "login_trace_id": trace_id,
        "state": state,
        "auth_callback_url": callback_url,
        "machine_id": machine_id,
        "device_id": device_id,
        "x_device_id": device_id,
        "x_machine_id": machine_id,
        "x_device_brand": DEVICE_BRAND,
        "x_device_type": "windows",
        "x_os_version": OS_VERSION,
        "x_env": "prod",
        "x_app_version": AUTH_APP_VERSION,
        "x_app_type": "stable",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "hide_saas_login": "true",
    })
    return "%s/authorization?%s" % (host, q)


# 官方授权页登录前会先空参探测回调地址可达性：回 200 挂起页继续等待，
# 绝不能按失败结束会话（「登录后无法回调」就是这么来的）
_PAGE_WAIT = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录回调</title></head>
<body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:460px;padding:24px"><h2 style="font-size:18px">正在等待授权结果…</h2>
<p id="hint" style="font-size:13.5px;line-height:1.9;color:#97a1ac">请回到官方授权页完成登录，本页将自动完成回调</p>
<script>(function(){if(window.location.hash&&window.location.hash.length>1){var h=window.location.hash.slice(1);window.location.replace(window.location.origin+window.location.pathname+'?'+h);return;}document.getElementById('hint').textContent='未检测到授权参数：请回到官方授权页完成登录；若已登录仍停在本页，请复制地址栏整段链接粘回面板。';})();</script>
</div></body></html>"""

_PAGE_OK = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录成功</title></head>
<body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:460px;padding:24px"><h2 style="font-size:18px;color:#44e07f">✓ 登录成功</h2>
<p style="font-size:13.5px;line-height:1.9;color:#97a1ac">账号已加入 Trae 账号池，可以关闭本页回到面板。</p></div></body></html>"""


def _page_err(msg):
    safe = (str(msg or "未知错误").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))
    return ("""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录失败</title></head>
<body style="font-family:system-ui,'Microsoft YaHei UI',sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#0b0d0f;color:#dfe5ea">
<div style="text-align:center;max-width:520px;padding:24px"><h2 style="font-size:18px;color:#f26d6d">✕ 登录失败</h2>
<p style="font-size:13.5px;line-height:1.9;color:#97a1ac">%s</p></div></body></html>""" % safe)


def _parse_callback_params(raw):
    """解析粘贴的回调内容：完整 URL / 裸查询串 / #hash 形态。

    必须至少带一个凭据字段才算成功，否则整段 URL 会被当成一个参数名。
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    candidates = []
    if "://" in raw:
        parts = urllib.parse.urlsplit(raw)
        candidates = [parts.query, parts.fragment]
    else:
        candidates = [raw]
        q = raw.find("?")
        if q >= 0:
            candidates.append(raw[q + 1:])
        h = raw.find("#")
        if h >= 0:
            candidates.append(raw[h + 1:])
    for qs in candidates:
        q = urllib.parse.parse_qs(qs, keep_blank_values=False)
        if any(q.get(k) for k in _OAUTH_CRED_KEYS):
            return q
    return None


def _json_param(raw):
    """URL 编码 JSON 参数（userInfo / userJwt / authCodeInfo）宽容解析。"""
    if not raw:
        return None
    for val in (raw, urllib.parse.unquote(raw)):
        try:
            obj = json.loads(val)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def _auth_code_from_info(raw):
    info = _json_param(raw)
    if not info:
        return ""
    v = info.get("AuthCode") or info.get("authCode") or info.get("auth_code") \
        or info.get("code")
    if not v and isinstance(info.get("Result"), dict):
        r = info["Result"]
        v = r.get("AuthCode") or r.get("authCode") or r.get("auth_code")
    return str(v or "")


def _validate_callback(q, session):
    """校验只挡明确的外来请求；官方页从不回传 state，回传了却不一致=外来请求。"""
    state = (q.get("state") or [""])[0]
    if state and state != session.get("state"):
        return False
    return True


def _device_public_key():
    """EC P-256 SPKI PEM 设备公钥（官方客户端与 AgentHub 同款必带字段）。

    AgentHub 在 Node 里现生成一对（私钥即抛）；标准库没有 EC 密钥构造，
    先走 openssl 临时文件管道（Windows 下 stdin 管道不可用，实测会静默
    失败成空串——这正是换令牌 10101 无效参数的根因），失败回落内置
    静态公钥：官方只验格式与持有证明，静态公钥与其同效。
    """
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            kp = os.path.join(td, "k.pem")
            pp = os.path.join(td, "p.pem")
            subprocess.run(
                ["openssl", "ecparam", "-name", "prime256v1", "-genkey",
                 "-noout", "-out", kp], capture_output=True, timeout=10, check=True)
            subprocess.run(
                ["openssl", "ec", "-in", kp, "-pubout", "-out", pp],
                capture_output=True, timeout=10, check=True)
            with open(pp, encoding="utf-8") as fh:
                pem = fh.read().strip()
            if "BEGIN PUBLIC KEY" in pem:
                return pem
    except Exception:
        pass
    return FALLBACK_DEVICE_PUBLIC_KEY


def _exchange_auth_code(auth_code, verifier, device_id, machine_id, cb_host=""):
    """授权码换令牌：PKCE code_verifier + EC P-256 设备公钥（AgentHub 同款）。"""
    device_public_key = _device_public_key()

    body = json.dumps({
        "ClientID": CLIENT_ID,
        "AuthCode": auth_code,
        "CodeVerifier": verifier,
        "DeviceInfo": {
            "DeviceID": device_id,
            "MachineID": machine_id,
            "PlatformCode": "SOLO_PC",
            "DeviceType": "PC",
            "DeviceName": "PC",
            "DeviceModel": DEVICE_BRAND,
            "ClientVersion": AUTH_APP_VERSION,
            "DevicePublicKey": device_public_key,
            "DeviceBrand": "Microsoft",
            "DeviceCPU": "",
            "OSInfo": "windows",
            "OSVersion": OS_VERSION,
        },
        "IDEVersion": AUTH_APP_VERSION,
    }, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json", "user-agent": USER_AGENT,
               "x-cloudide-token": ""}

    origins = ["https://api.trae.cn", "https://api.trae.com.cn"]
    cb = ""
    if cb_host:
        cb = cb_host if cb_host.startswith("http") else "https://" + cb_host
        try:
            cb = urllib.parse.urlsplit(cb).scheme + "://" + urllib.parse.urlsplit(cb).netloc
        except Exception:
            cb = ""
    if cb:
        origins = [cb] + [o for o in origins if o != cb]
    paths = ["/trae/api/v3/oauth/ExchangeToken",
             "/cloudide/api/v3/trae/oauth/ExchangeToken"]
    last = ""
    for origin in origins:
        for p in paths:
            status, data = _http_json(origin + p, json.loads(body.decode("utf-8")),
                                      headers)
            d = data.get("Result") or data.get("result") or data.get("data") or data
            token = ""
            refresh = ""
            if isinstance(d, dict):
                token = str(d.get("AccessToken") or d.get("accessToken")
                            or d.get("Token") or d.get("token") or "")
                refresh = str(d.get("RefreshToken") or d.get("refreshToken")
                              or d.get("refresh_token") or "")
            if status == 200 and token:
                return (token.replace("Cloud-IDE-JWT", "").strip(),
                        refresh)
            msg = ""
            if isinstance(data, dict):
                rm = data.get("ResponseMetadata") or {}
                if isinstance(rm, dict):
                    msg = str((rm.get("Error") or {}).get("Message") or "")
                msg = msg or str(data.get("message") or data.get("msg") or "")
            last = msg or ("HTTP %s" % status)
    if "{__Message.field}" in last:
        last = "授权码已失效或已被消费（一次性），请重新发起登录"
    raise RuntimeError("授权码换取令牌失败：%s" % (last or "上游无响应"))


def _resolve_credentials(q, session):
    """回调参数 → (accessToken, refreshToken, extra)；优先现成凭据，其次授权码。"""
    access = str((q.get("accessToken") or q.get("access_token")
                  or q.get("token") or [""])[0]).replace("Cloud-IDE-JWT", "").strip()
    refresh = str((q.get("refreshToken") or q.get("refresh_token") or [""])[0])
    user_info = _json_param((q.get("userInfo") or q.get("user_info") or [None])[0])
    user_jwt = _json_param((q.get("userJwt") or q.get("user_jwt")
                            or q.get("UserJwt") or [None])[0])
    if user_jwt and not refresh:
        refresh = str(user_jwt.get("RefreshToken") or user_jwt.get("refreshToken")
                      or user_jwt.get("refresh_token") or "")
    if user_jwt and not access:
        access = str(user_jwt.get("Token") or user_jwt.get("token")
                     or user_jwt.get("access_token") or "").replace("Cloud-IDE-JWT", "").strip()
    extra = {
        "uid": str((user_info or {}).get("UserID") or (user_info or {}).get("user_id")
                   or (user_info or {}).get("uid") or ""),
        "name": str((user_info or {}).get("ScreenName") or (user_info or {}).get("nickname")
                    or (user_info or {}).get("name") or ""),
    }
    if access:
        return access, refresh, extra
    if refresh:
        # refreshToken-only 回调（官方部分回流形态只回 refreshToken，或
        # 回调页 hash 里的凭据被脚本回捞后只剩它）：直接入池，请求时现场换发
        return "", refresh, extra
    auth_code = str((q.get("authCode") or q.get("auth_code") or q.get("code")
                     or [""])[0]) or _auth_code_from_info(
                        (q.get("authCodeInfo") or q.get("auth_code_info") or [""])[0])
    if auth_code:
        cb_host = str((q.get("loginHost") or q.get("login_host") or q.get("host")
                       or q.get("consoleHost") or [""])[0])
        token, new_refresh = _exchange_auth_code(
            auth_code, session.get("verifier") or "",
            session.get("device_id") or "", session.get("machine_id") or "",
            cb_host)
        return token, new_refresh or refresh, extra
    raise RuntimeError("回调未携带凭据（accessToken / refreshToken / authCode 都没有）")


def _pool_add(ctx, credential, name="", uid=""):
    """凭据入库（共享账号池）：同 uid 就地更新凭据，否则新建账号。

    credential 可为 refreshToken（推荐，长期换发）或整段 accessToken
    （自动识别；从 JWT 解 uid，但过期后需要重新登录）。启动装配阶段
    账号池尚未创建（boot 顺序：渠道注册 → 池加载），此时直接落盘，
    随后 pool.load() 会把文件收进池里。
    """
    raw = str(credential or "").replace("Cloud-IDE-JWT", "").strip()
    if not raw:
        raise ValueError("empty credential")
    token_uid = jwt_uid(raw) if raw.count(".") == 2 else ""
    want_uid = str(uid or "").strip() or token_uid
    name = str(name or "").strip()
    pool = getattr(ctx, "pool", None)
    if want_uid and pool is not None:
        existing = pool.get(want_uid)
        if existing is not None and existing.realm == "trae":
            existing.refresh_token = raw
            existing.enabled = True
            existing.clear_error()
            if name and not existing.nickname:
                existing.nickname = name
            if existing.accounts_dir:
                existing.save(existing.accounts_dir)
            _refresh_fails.pop(want_uid, None)
            _token_cache.pop(want_uid, None)
            return {"id": existing.uid, "uid": existing.uid,
                    "name": existing.nickname, "merged": True}
    account = accounts_mod.Account({
        "uid": want_uid,
        "nickname": name or (want_uid[:8] if want_uid else ""),
        "realm": "trae",
        "domain": DOMAIN,
        "platform": "CLI",
        "refreshToken": raw,
        "source": "oauth",
        "enabled": True,
    })
    if pool is not None:
        pool.add(account)
    else:
        account.save(ctx.accounts_dir)
    return {"id": account.uid, "uid": account.uid,
            "name": account.nickname, "merged": False}


def _login_account_from_token(account):
    """Trae 令牌 data.id 是登录手机号；没有就回退常见邮箱/手机声明。"""
    claims = accounts_mod.jwt_claims(getattr(account, "access_token", ""))
    data = claims.get("data") if isinstance(claims.get("data"), dict) else {}
    for source in (data, claims):
        for key in ("id", "phone", "mobile", "email"):
            value = str(source.get(key) or "").strip()
            if accounts_mod.looks_like_login_account(value):
                return value
    return ""


def _login_session_close(state, keep_result=False):
    with _login_state_guard:
        session = _login_state.pop(state, None)
    if session is None:
        return
    srv = session.pop("server", None)
    if srv is not None:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
    if keep_result:
        with _login_state_guard:
            _login_state[state] = {k: v for k, v in session.items()
                                   if k != "server"}


def login_callback(ctx, q, state):
    """回环回调 / 手动粘贴的统一处理：返回 (html, http_code, 是否已完结)。"""
    with _login_state_guard:
        session = _login_state.get(state)
    if session is None:
        return _page_err("登录会话已结束或已超时，请回到面板重新发起"), 400, True
    if session.get("status") in ("ok", "error", "expired"):
        # 已完结会话不再收凭据：回环路径服务随会话关闭天然挡住，公网回调
        # 路由常驻，同一回调地址被重放会重复入池，这里显式挡掉
        return _page_err("登录会话已完结，请回到面板重新发起"), 400, True
    if time.time() - session.get("started", 0) > OAUTH_TIMEOUT:
        _login_session_close(state)
        return _page_err("登录会话已超时（3 分钟），请回到面板重新发起"), 400, True
    err_param = (q.get("error") or q.get("error_code") or q.get("errorCode")
                 or q.get("err") or [""])[0]
    if err_param:
        desc = (q.get("error_description") or q.get("message") or [""])[0]
        msg = "授权失败：%s%s" % (err_param, ("（%s）" % desc) if desc else "")
        session["status"] = "error"
        session["message"] = msg
        return _page_err(msg), 400, True
    has_cred = any(q.get(k) for k in _OAUTH_CRED_KEYS)
    if not has_cred:
        # 官方页登录前的空参可达性探测：回挂起页继续等待
        return _PAGE_WAIT, 200, False
    if not _validate_callback(q, session):
        return _page_err("state 校验不通过（非本次发起的授权会话）"), 400, False
    try:
        access, refresh, extra = _resolve_credentials(q, session)
        if refresh:
            item = _pool_add(ctx, refresh, name=extra.get("name") or "",
                             uid=extra.get("uid") or "")
            session["status"] = "ok"
            session["account"] = {"uid": item.get("uid"),
                                  "name": item.get("name") or extra.get("name") or ""}
            session["message"] = ("登录成功，该账号已在池中，凭据已更新"
                                  if item.get("merged") else
                                  "登录成功，账号已加入 Trae 账号池")
            _login_session_close(state, keep_result=True)
            return _PAGE_OK, 200, True
        if access:
            # 只有 accessToken：落池仍需 refreshToken 才能长期续期；
            # 官方 IDE 登录态导入走这个分支（能解 uid，不能自动续期）
            uid = jwt_uid(access)
            item = _pool_add(ctx, access, name=extra.get("name") or "", uid=uid)
            session["status"] = "ok"
            session["account"] = {"uid": item.get("uid"),
                                  "name": item.get("name") or extra.get("name") or ""}
            session["message"] = ("仅拿到 accessToken（无 refreshToken），"
                                  "已按临时凭据入池，过期后需要重新登录"
                                  if not item.get("merged") else
                                  "登录成功，该账号已在池中，凭据已更新")
            _login_session_close(state, keep_result=True)
            return _PAGE_OK, 200, True
        raise RuntimeError("回调未携带凭据")
    except Exception as exc:
        msg = str(exc)
        session["status"] = "error"
        session["message"] = msg
        return _page_err(msg), 200, True


def login_session_start(ctx):
    """发起一次官方登录：起回环回调服务 + 生成授权地址。

    返回 {ok, authUrl, state, port, hint, paste}。回调地址官方页只认回环
    形状，浏览器与网关同机时登录成功即自动入池；服务器部署（不同机）时
    回跳打不进来，用 submit_login 粘贴回调地址完成登录。
    """
    state = secrets.token_hex(16)
    trace_id = str(uuid.uuid4())
    verifier, challenge = _pkce_pair()
    device_id, machine_id = _device_fingerprint("trae:oauth:" + state)
    host = _login_guidance_host()

    session = {"state": state, "trace_id": trace_id, "verifier": verifier,
               "device_id": device_id, "machine_id": machine_id,
               "host": host, "started": time.time(),
               "status": "waiting", "message": "", "account": None,
               "server": None, "port": 0}
    try:
        import http.server

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                if u.path != "/authorize":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                q = urllib.parse.parse_qs(u.query, keep_blank_values=False)
                html, code, done = login_callback(ctx, q, state)
                body = html.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except Exception:
                    pass

            def log_message(self, *args):
                pass

        try:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", OAUTH_PORT), _Handler)
        except OSError:
            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        session["server"] = srv
        session["port"] = srv.server_address[1]
    except Exception as exc:
        session["status"] = "manual-only"
        session["message"] = "回环端口监听失败，只能走粘贴回调：%s" % str(exc)[:120]
    callback_url = "http://127.0.0.1:%d/authorize" % session["port"]
    url = _build_auth_url(host, callback_url, trace_id, state, challenge,
                          device_id, machine_id)
    with _login_state_guard:
        _login_state[state] = session
    # 顺手清掉超时老会话：必须在锁外调用 _login_session_close——它内部要获取
    # 同一把非重入锁，持锁重入会死锁并永久卡住整条登录链路
    now = time.time()
    for k in list(_login_state.keys()):
        s = _login_state.get(k)
        if s is not None and now - s.get("started", 0) > OAUTH_TIMEOUT + 60:
            _login_session_close(k)
    if session["port"]:
        hint = ("浏览器会先空参探测回调地址——页面停在「等待授权结果」属正常，"
                "回官方页登录完成即可自动入池。")
    else:
        hint = "本机未开放回环端口，官方页登录完成后请把浏览器地址栏整段复制回面板粘贴。"
    return {"ok": True, "authUrl": url, "state": state,
            "port": session["port"], "host": host, "hint": hint,
            "paste": True, "realm": "trae"}


def login_session_poll(ctx, state):
    """面板轮询登录结果；手动粘贴回调场景在提交时已完结。"""
    with _login_state_guard:
        session = _login_state.get(state)
    if session is None:
        return {"status": "expired",
                "message": "登录会话已结束（成功入池或已超时）"}
    if time.time() - session.get("started", 0) > OAUTH_TIMEOUT \
            and session.get("status") == "waiting":
        session["status"] = "expired"
        session["message"] = "登录超时（3 分钟），请重新发起"
        _login_session_close(state)
    return {"status": session.get("status"),
            "message": session.get("message")
                       or "等待授权回调…若浏览器停在等待页，请回到官方授权页完成登录",
            "port": session.get("port"),
            "host": session.get("host")}


def login_submit(ctx, state, raw_callback):
    """手动粘贴回调地址（服务器部署 / 回环端口被占的兜底）。"""
    q = _parse_callback_params(raw_callback)
    if q is None:
        return {"ok": False,
                "message": "无法解析回调内容：请整段复制浏览器地址栏（需包含 refreshToken / authCode 等参数）"}
    login_callback(ctx, q, state)
    with _login_state_guard:
        session = _login_state.get(state)
    ok = bool(session and session.get("status") == "ok")
    msg = (session or {}).get("message") or "处理完成"
    return {"ok": ok, "message": msg}


def login_cancel(state):
    _login_session_close(state)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 旧版迁移（只读旧项目 accounts/trae_keys.json，防重入标记落本侧 accounts/）
# ---------------------------------------------------------------------------
MIGRATION_MARKER = "trae_migrated.json"


def migrate_from_legacy(ctx):
    """把二开 wb-proxy 的 Trae 账号并入共享账号池（一次性，启动时执行）。

    来源按顺序探测：环境变量 WB_TRAE_LEGACY_KEYS 指定文件，或
    <上级目录>/wb-proxy/accounts/trae_keys.json。uid 缺失且无法从凭据
    解出的条目跳过并记日志（共享池以 uid 为账号主键）。只读旧文件，
    旧项目目录不做任何改动。
    """
    accounts_dir = ctx.accounts_dir
    marker = os.path.join(accounts_dir, MIGRATION_MARKER)
    if os.path.exists(marker):
        return []
    legacy = os.environ.get("WB_TRAE_LEGACY_KEYS") or ""
    if not legacy:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        legacy = os.path.join(os.path.dirname(root), "wb-proxy", "accounts",
                              "trae_keys.json")
    items = []
    try:
        with open(legacy, encoding="utf-8") as fh:
            blob = json.load(fh)
        raw_items = blob.get("accounts")
        if raw_items is None and isinstance(blob.get("keys"), list):
            raw_items = blob.get("keys")
        items = [it for it in (raw_items or []) if isinstance(it, dict)]
    except Exception as exc:
        _log("trae migration: legacy keys unreadable (%s)" % exc, ctx)
        items = []
    imported = []
    for it in items:
        rt = str(it.get("refreshToken") or it.get("refresh_token") or "").strip()
        if not rt:
            continue
        uid = str(it.get("uid") or "").strip()
        name = str(it.get("name") or "").strip()
        if not uid:
            _log("trae migration: skip a legacy entry without uid "
                 "(its uid is backfilled after the first token exchange there; "
                 "re-login it here when needed)", ctx)
            continue
        try:
            item = _pool_add(ctx, rt, name=name, uid=uid)
            imported.append(item)
        except Exception as exc:
            _log("trae migration: import uid=%s failed: %s" % (uid[:8], exc), ctx)
    try:
        from core import fsutil
        fsutil.atomic_write_json(marker, {
            "migrated_at": time.time(),
            "migrated_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": legacy,
            "imported": len(imported),
        })
    except Exception:
        pass
    if imported:
        _log("trae migration: imported %d account(s) from legacy store"
             % len(imported), ctx)
    return imported


# ---------------------------------------------------------------------------
# 渠道适配器
# ---------------------------------------------------------------------------
class TraeAdapter(registry.ChannelAdapter):
    id = "trae"
    label = LABEL
    realms = ("trae",)
    route_prefixes = (ROUTE_PREFIX,)

    def __init__(self):
        # 注册时的 AppContext：目录发现等无 ctx 参数的回调链要用
        self._ctx = None
    capabilities = frozenset({
        registry.CAP_CHAT, registry.CAP_RESPONSES, registry.CAP_MODELS,
        registry.CAP_ACCOUNTS, registry.CAP_CHECKIN, registry.CAP_SCHEDULER,
        registry.CAP_PROXY_SLOT, registry.CAP_PASTE_TOKEN,
    })

    def register(self, ctx):
        self._ctx = ctx
        init_ledger_dir(ctx.usage_dir)
        accounts_mod.register_realm_config("trae", {
            "name": LABEL,
            "domain": DOMAIN,
            "has_checkin": True,
            "has_daily_chat": False,
            # 令牌换发型注入点：续期/余额/签到/探测都走本模块实现
            "refresh_fn": lambda account: self._refresh(account),
            "credits_fn": credits_for_account,
            "checkin_fn": checkin_for_account,
            "probe_fn": probe_account,
            "login_account_fn": _login_account_from_token,
        })
        # 旧版账号一次性并入共享池（必须在账号池 load 之前——boot 顺序保证）
        try:
            migrate_from_legacy(ctx)
        except Exception as exc:
            _log("trae migration failed: %s" % exc, ctx)

    @staticmethod
    def _refresh(account):
        """auth.accounts 注入的 refresh_fn：换发成功返回 True。"""
        token, err = ensure_token(account)
        if token is None:
            account.last_error = err
            return False
        return True

    def start_login(self, ctx, realm, platform="CLI"):
        if realm != "trae":
            return None
        return login_session_start(ctx)

    def poll_login(self, ctx, state):
        if not state:
            return None
        with _login_state_guard:
            known = state in _login_state
        if not known:
            return None
        return login_session_poll(ctx, state)

    def submit_login(self, ctx, state, raw_callback):
        with _login_state_guard:
            known = state in _login_state
        if not known:
            return None
        return login_submit(ctx, state, raw_callback)

    def cancel_login(self, ctx, state):
        with _login_state_guard:
            known = state in _login_state
        if not known:
            return None
        return login_cancel(state)

    def open_stream(self, ctx, payload, session_key=None, realm=None):
        return open_stream(ctx, payload, session_key=session_key, realm=realm)

    def live_models(self, realm, force=False):
        return live_models(realm, force=force, ctx=self._ctx)

    def scheduler_tasks(self, ctx):
        return [self._checkin_spec(ctx)]

    @staticmethod
    def _checkin_spec(ctx):
        def trae_checkin(reason, source="auto"):
            return ctx.run_task_over_accounts(
                kind="trae_checkin", source=source,
                ready=lambda acc: (getattr(acc, "realm", "") == "trae"
                                   and getattr(acc, "enabled", False)
                                   and bool(getattr(acc, "refresh_token", ""))),
                action=lambda acc: _do_checkin(acc, source))

        # 业务日按 UTC+8 切日；09:00 首跑，21:00 补跑（台账与上游状态互校）
        return ("trae_checkin", "Trae 签到", trae_checkin,
                {"enabled": True, "hours": [9, 21], "realm": "trae"})

    def panel_meta(self, ctx):
        pool = getattr(ctx, "pool", None)
        return {
            "id": self.id,
            "label": self.label,
            "realms": [{
                "id": "trae",
                "label": "国内版 (TRAE SOLO CN)",
                "badge": BADGE,
                "domain": DOMAIN,
                "accounts": pool.count_ready(realm="trae") if pool else 0,
                "capabilities": sorted(self.capabilities),
            }],
            "capabilities": sorted(self.capabilities),
            "frontend": "trae",
            "enabled": True,
        }

def _do_checkin(account, source):
    res = checkin_for_account(account, trigger="scheduler" if source == "auto"
                              else "manual")
    # 余额补拉已在 checkin_for_account 内统一完成，这里只做任务流水状态归并
    if res.get("ok") and res.get("already"):
        return {"status": "already", "message": res.get("message") or "今日已签到"}
    if res.get("ok"):
        return {"status": "ok", "message": res.get("message") or "签到成功"}
    if res.get("unavailable"):
        return {"status": "skip", "message": res.get("message") or "签到服务未开放"}
    return {"status": "error", "message": res.get("error")
            or res.get("message") or "签到失败"}


def install(ctx):
    """注册本渠道（入口调用；新增渠道照此一行接入）。"""
    registry.register(TraeAdapter(), ctx)
