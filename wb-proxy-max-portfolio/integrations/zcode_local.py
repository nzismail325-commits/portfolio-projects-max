# -*- coding: utf-8 -*-
"""integrations/zcode_local.py —— ZCode 本机登录态与客户端元数据

事实基线（AgentHub v1.77.0 zcodeLocal.cjs，本机客户端实测）：
- 登录态在 ~/.zcode/v2/credentials.json：平铺 map，值多为 enc:v1 密文；
  关键键 zcodejwttoken（start-plan 对话 + 控制面 Bearer）、
  oauth:{provider}:access_token/refresh_token/user_info、
  account-provider:coding-plan:account:{family}:account:{uid}:api-key（付费套餐凭据）；
- enc:v1 = AES-256-GCM，key = sha256(secret)，secret 优先取
  ZCODE_CREDENTIAL_SECRET，否则用官方回退公式（平台 + home + 用户名）；
- ~/.zcode/v2/account-profiles/profiles.json 是官方多账号档案，每份带
  cred_file 与明文 provider_api_keys；
- runtime/provider/<平台>/<版本>/endpoint-*/zcode-builtin.json 是官方客户端的
  模型能力表（输入模态 / 上下文 / 输出上限），按文件顺序逐属性覆盖。
"""
import base64
import hashlib
import json
import os
import platform as platform_mod
import re
import uuid

from auth import atrest

ENC_PREFIX = "enc:v1:"
CODING_KEY_RE = re.compile(
    r"^account-provider:coding-plan:account:([a-z0-9-]+-coding-plan):account:([0-9a-zA-Z-]+):api-key$")


# --------------------------------------------------------------- 路径与密钥
def _node_platform():
    if os.name == "nt":
        return "win32"
    if platform_mod.system().lower() == "darwin":
        return "darwin"
    return "linux"


def _username():
    for key in ("USERNAME", "USER", "LOGNAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return "unknown"


def default_secret():
    env = str(os.environ.get("ZCODE_CREDENTIAL_SECRET") or "")
    if env:
        return env
    home = os.path.expanduser("~")
    return "zcode-credential-fallback:%s:%s:%s" % (
        _node_platform(), home, _username())


def derive_key(secret=None):
    return hashlib.sha256(str(secret or default_secret()).encode("utf-8")).digest()


def is_enc(value):
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def enc_decrypt(value, secret=None):
    """解 enc:v1；非密文原样返回。格式错误或密钥不对抛异常。"""
    if not is_enc(value):
        return value
    parts = value[len(ENC_PREFIX):].split(".")
    if len(parts) != 3:
        raise ValueError("enc:v1 格式不正确（应为 nonce.tag.cipher 三段）")
    decode = lambda text: base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    nonce, tag, cipher = (decode(part) for part in parts)
    return atrest.gcm_open(derive_key(secret), nonce, cipher, tag).decode("utf-8")


def try_decrypt(value, secret=None):
    """宽容解密：单个键解不开按缺失处理，不拖垮整份文件。"""
    try:
        return enc_decrypt(value, secret)
    except Exception:
        return ""


def v2_dir():
    env = str(os.environ.get("ZCODE_V2_DIR") or "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), ".zcode", "v2")


def paths():
    root = v2_dir()
    return {
        "credentials": os.path.join(root, "credentials.json"),
        "telemetry": os.path.join(root, "telemetry-state.json"),
        "profilesJson": os.path.join(root, "account-profiles", "profiles.json"),
        "profilesDir": os.path.join(root, "account-profiles"),
    }


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def local_device_mid():
    telemetry = read_json(paths()["telemetry"]) or {}
    return str(telemetry.get("deviceMid") or "")


# --------------------------------------------------------------------- JWT
def jwt_payload(token):
    try:
        segment = str(token or "").split(".")[1]
        segment += "=" * (-len(segment) % 4)
        data = json.loads(base64.urlsafe_b64decode(segment).decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def uid_from_jwt(token):
    payload = jwt_payload(token)
    return str(payload.get("user_id") or payload.get("sub") or "")


# --------------------------------------------------------------- 凭据解析
def parse_coding_plan_key_name(key_name):
    match = CODING_KEY_RE.match(str(key_name or ""))
    return {"family": match.group(1), "uid": match.group(2)} if match else None


def parse_credentials(obj):
    out = {
        "provider": "", "jwt": "", "accessToken": "", "refreshToken": "",
        "userInfo": None, "userInfoRaw": "", "codingPlanKeys": [],
        "decryptOk": False,
    }
    if not isinstance(obj, dict):
        return out
    secret = default_secret()
    for key, value in obj.items():
        if key.startswith("web-remote-control:"):
            continue
        if key == "zcodejwttoken":
            out["jwt"] = try_decrypt(value, secret)
            if out["jwt"]:
                out["decryptOk"] = True
            continue
        if key == "oauth:active_provider":
            out["provider"] = try_decrypt(value, secret)
            continue
        match = re.match(r"^oauth:(zai|bigmodel):(access_token|refresh_token|user_info)$", key)
        if match:
            plain = try_decrypt(value, secret)
            field = match.group(2)
            if field == "access_token":
                out["accessToken"] = plain
            elif field == "refresh_token":
                out["refreshToken"] = plain
            else:
                out["userInfoRaw"] = plain
                try:
                    out["userInfo"] = json.loads(plain) if plain else None
                except Exception:
                    out["userInfo"] = None
            continue
        if key.startswith("account-provider:coding-plan:"):
            info = parse_coding_plan_key_name(key)
            plain = try_decrypt(value, secret)
            if info and plain:
                out["codingPlanKeys"].append({
                    "keyName": key, "family": info["family"],
                    "uid": info["uid"], "plain": plain})
    return out


def read_live():
    file_path = paths()["credentials"]
    raw = read_json(file_path)
    if raw is None:
        return None
    parsed = parse_credentials(raw)
    parsed["file"] = file_path
    parsed["raw"] = raw
    return parsed


def read_profiles():
    cfg = paths()
    try:
        with open(cfg["profilesJson"], "r", encoding="utf-8") as fh:
            items = json.load(fh)
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cred_file = str(item.get("cred_file") or "")
        cred = None
        if cred_file and re.match(r"^[\w.-]+$", cred_file):
            raw = read_json(os.path.join(cfg["profilesDir"], cred_file))
            if raw is not None:
                cred = parse_credentials(raw)
        api_keys = {}
        raw_keys = item.get("provider_api_keys")
        if isinstance(raw_keys, dict):
            for key, value in raw_keys.items():
                if isinstance(value, str) and value.strip():
                    api_keys[key] = value.strip()
        out.append({
            "profileId": str(item.get("id") or ""),
            "uid": str(item.get("user_id") or ""),
            "name": str(item.get("name") or ""),
            "email": str(item.get("email") or ""),
            "avatar": str(item.get("avatar") or ""),
            "family": str(item.get("family") or ""),
            "providerApiKeys": api_keys,
            "cred": cred,
            "file": cred_file,
        })
    return out


# ------------------------------------------------------------------ 账号组装
def pick_plan_key(coding_keys, profile_keys=None, expected_uid=""):
    """挑主 coding-plan 凭据：账号身份必须与凭据同源，绝不拿别的账号的 key。"""
    keys = list(coding_keys or [])
    if expected_uid:
        keys = [key for key in keys if key.get("uid") == expected_uid]

    def pick(marker):
        for item in keys:
            if marker in item.get("family", ""):
                return {"plain": item["plain"], "uid": item.get("uid", "")}
        return None

    hit = pick("zai-individual") or pick("zai-team")
    if hit:
        return hit
    if keys:
        return {"plain": keys[0]["plain"], "uid": keys[0].get("uid", "")}
    for slot in ("builtin:zai-coding-plan", "builtin:bigmodel-coding-plan"):
        plain = (profile_keys or {}).get(slot)
        if plain:
            return {"plain": plain, "uid": ""}
    return {"plain": "", "uid": ""}


def derived_device_mid(uid):
    digest = hashlib.sha256(("zcode-device:%s" % uid).encode("utf-8")).hexdigest()
    return "%s-%s-4%s-a%s-%s" % (
        digest[:8], digest[8:12], digest[13:16], digest[17:20], digest[20:32])


def _mid_held_by_other(ctx, uid, mid):
    pool = getattr(ctx, "pool", None)
    if pool is None:
        return False
    for account in getattr(pool, "accounts", []) or []:
        if str(getattr(account, "uid", "")) == str(uid):
            continue
        if str((getattr(account, "meta", None) or {}).get("deviceMid") or "") == mid:
            return True
    return False


def account_record(parsed, extra=None, ctx=None):
    """凭据集 → 号池账号字段（扫描导入与 OAuth 共用同一套 uid/名称/指纹口径）。"""
    extra = extra or {}
    parsed = parsed or {}
    jwt = str(parsed.get("jwt") or extra.get("jwtFallback") or "")
    info = parsed.get("userInfo") or {}
    expected_uid = (str(extra.get("uid") or "") or uid_from_jwt(jwt)
                    or str(info.get("user_id") or ""))
    plan = pick_plan_key(parsed.get("codingPlanKeys") or [],
                         extra.get("profileApiKeys") or {}, expected_uid)
    uid = expected_uid or plan.get("uid") or ""
    email = str(info.get("email") or extra.get("email") or "")
    name = str(extra.get("name") or info.get("name") or email
               or ("ZCode %s" % uid[:6] if uid else ""))
    mid = str(extra.get("deviceMid") or "")
    if not mid:
        live_mid = local_device_mid()
        live = read_live()
        live_uid = ""
        if live:
            live_uid = uid_from_jwt(live.get("jwt") or "")
            if not live_uid and live.get("codingPlanKeys"):
                live_uid = str(live["codingPlanKeys"][0].get("uid") or "")
        if live_mid and uid and live_uid and uid == live_uid \
                and not _mid_held_by_other(ctx, uid, live_mid):
            mid = live_mid
        elif uid:
            mid = derived_device_mid(uid)
        else:
            mid = live_mid or str(uuid.uuid4())
    return {
        "uid": uid,
        "name": name,
        "email": email,
        "avatar": str(info.get("avatar") or info.get("avatarUrl") or extra.get("avatar") or ""),
        "provider": str(parsed.get("provider") or extra.get("provider") or "zai"),
        "deviceMid": mid,
        "token": jwt,
        "refreshToken": str(plan.get("plain") or ""),
    }


def resolve_device_mid(account, ctx=None):
    """出站设备指纹：账号 meta 优先；本机当前登录号继承真实值；其余确定性派生。"""
    meta = getattr(account, "meta", None) or {}
    mid = str(meta.get("deviceMid") or "")
    if mid:
        return mid
    uid = str(getattr(account, "uid", "") or "")
    live_mid = local_device_mid()
    live = read_live()
    live_uid = ""
    if live:
        live_uid = uid_from_jwt(live.get("jwt") or "")
        if not live_uid and live.get("codingPlanKeys"):
            live_uid = str(live["codingPlanKeys"][0].get("uid") or "")
    if live_mid and uid and live_uid and uid == live_uid \
            and not _mid_held_by_other(ctx, uid, live_mid):
        return live_mid
    if uid:
        return derived_device_mid(uid)
    return live_mid or str(uuid.uuid4())


# ------------------------------------------------- 官方客户端模型能力表
_CAP_CACHE = {"file": "", "mtime": 0.0, "rules": []}


def find_client_builtin():
    root = os.path.join(v2_dir(), "runtime", "provider")
    hits = []

    def walk(directory, depth):
        if depth > 4:
            return
        try:
            entries = os.listdir(directory)
        except Exception:
            return
        for name in entries:
            path = os.path.join(directory, name)
            if os.path.isdir(path):
                walk(path, depth + 1)
            elif name == "zcode-builtin.json":
                try:
                    hits.append((path, os.path.getmtime(path)))
                except Exception:
                    pass

    walk(root, 0)
    hits.sort(key=lambda item: item[1], reverse=True)
    return hits[0] if hits else None


def read_client_model_rules():
    hit = find_client_builtin()
    if hit is None:
        return []
    path, mtime = hit
    if _CAP_CACHE["file"] == path and _CAP_CACHE["mtime"] == mtime:
        return _CAP_CACHE["rules"]
    rules = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = ((((data or {}).get("config") or {}).get("modelConfigRules") or {})
                 .get("modelRules") or [])
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            cfg = item.get("config") or {}
            props = cfg.get("properties") or {}
            opts = cfg.get("optionSpecs") or {}
            max_out = (opts.get("maxOutputTokens") or {}).get("max")
            pattern = str(item.get("modelMatch") or "")
            if not pattern:
                continue
            rules.append({
                "pattern": pattern,
                "inputFormat": props.get("inputFormat") if isinstance(
                    props.get("inputFormat"), dict) else None,
                "contextWindow": _positive_int(props.get("contextWindow")),
                "maxOutputTokens": _positive_int(max_out),
            })
    except Exception:
        rules = []
    _CAP_CACHE.update({"file": path, "mtime": mtime, "rules": rules})
    return rules


def _positive_int(value):
    try:
        number = int(value)
        return number if number > 0 else None
    except (TypeError, ValueError):
        return None


def resolve_model_meta(model_id):
    """逐属性取「最后一个定义了该属性」的规则；全无匹配返回 None。"""
    model = str(model_id or "")
    if not model:
        return None
    hit = None
    for rule in read_client_model_rules():
        try:
            match = re.match("^(?:%s)$" % rule["pattern"], model, re.IGNORECASE)
        except re.error:
            continue
        if not match:
            continue
        hit = {
            "inputFormat": rule["inputFormat"] or (hit or {}).get("inputFormat"),
            "contextWindow": (rule["contextWindow"] if rule["contextWindow"] is not None
                              else (hit or {}).get("contextWindow")),
            "maxOutputTokens": (rule["maxOutputTokens"]
                                if rule["maxOutputTokens"] is not None
                                else (hit or {}).get("maxOutputTokens")),
        }
    return hit
