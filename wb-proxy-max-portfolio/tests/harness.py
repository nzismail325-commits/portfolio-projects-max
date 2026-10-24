# -*- coding: utf-8 -*-
"""tests/harness.py —— 共享冒烟装置（假上游启动 / 网关装配 / 请求 / 断言）

渠道专属的假上游在 tests/upstreams/<id>.py，渠道专属检查在
tests/channels/<id>.py；本模块只放各渠道共用的启动与请求能力。
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests.upstreams import codearts, loomy, qoder, trae, workbuddy, zcode
from tests.upstreams.zcode import fake_zcode_jwt, zcode_encrypt

_FAILURES = []


def check(name, condition, detail=""):
    """记录一条断言；失败项汇总到 failures()，由总入口统一决定退出码。"""
    print("%s %s%s" % ("PASS" if condition else "FAIL", name,
                       ("  -> " + detail) if (detail and not condition) else ""))
    if not condition:
        _FAILURES.append(name)


def failures():
    return list(_FAILURES)


def start_upstreams():
    """启动所有渠道假上游，返回 {name: (server, base_url)}。"""
    specs = [
        ("workbuddy", workbuddy.FakeUpstream),
        ("trae", trae.FakeTraeUpstream),
        ("qoder", qoder.FakeQoderUpstream),
        ("zcode", zcode.FakeZcodeUpstream),
        ("codearts", codearts.FakeCodeArtsUpstream),
        ("loomy", loomy.FakeLoomyUpstream),
    ]
    out = {}
    for name, handler in specs:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        out[name] = (server,
                     "http://127.0.0.1:%d" % server.server_address[1])
    return out


class SmokeEnv(object):
    """渠道检查模块共享的运行时上下文。"""

    def __init__(self, ctx, gateway, base, key_headers, upstreams):
        self.ctx = ctx
        self.gateway = gateway
        self.base = base
        self.key_headers = key_headers
        self.upstreams = upstreams
        self.panel_headers = {}


def build_gateway(tmpdir, bases):
    base = bases["workbuddy"]
    trae_base = bases.get("trae")
    qoder_base = bases.get("qoder")
    zcode_base = bases.get("zcode")
    codearts_base = bases.get("codearts")
    loomy_base = bases.get("loomy")
    from auth import identity
    from core import authz
    from core import context as context_mod
    from core import http as http_mod
    from core import proxy_api
    from core import upstream_body
    from infra import settings
    from integrations import registry
    from integrations import trae as trae_mod
    from integrations import workbuddy
    from panel import routes as panel_routes
    from panel import static as panel_static
    from integrations import qoder as qoder_mod
    from integrations import qoder_signer
    from integrations import zcode as zcode_mod
    from integrations import codearts as codearts_mod
    from integrations import loomy as loomy_mod

    if loomy_base:
        loomy_mod.CFG["xfyunBase"] = loomy_base
        loomy_mod.CFG["integrationBase"] = loomy_base
        loomy_mod.reset_caches()

    if codearts_base:
        codearts_mod.BASE = codearts_base
        codearts_mod.BENEFIT_BASE = codearts_base
        codearts_mod.TOKEN_URL = codearts_base + "/v1/oauth2/tokens"
        codearts_mod.WEB_LOGIN_BASE = codearts_base
        codearts_mod.reset_caches()

    if trae_base:
        trae_mod.CHAT_URL = trae_base + "/api/agent/v3/llm_utils_chat"
        trae_mod.MODELS_URL = trae_base + "/api/ide/v1/get_detail_param"
        trae_mod.EXCHANGE_URLS = [trae_base + "/cloudide/api/v3/trae/oauth/ExchangeToken"]
        trae_mod.CREDITS_BASES = [trae_base]
        trae_mod.CHECKIN_BASES = [trae_base]
        trae_mod.LOGIN_GUIDANCE_URLS = []
        # 冒烟环境隔离：不迁移旧项目真实 Trae 账号（迁移源探测会摸到
        # ../wb-proxy/accounts/trae_keys.json）
        os.environ["WB_TRAE_LEGACY_KEYS"] = os.path.join(tmpdir, "no-legacy.json")

    if qoder_base:
        for product in ("qoder", "qoder_intl"):
            qoder_mod.PRODUCTS[product].update({
                "gateway": qoder_base, "openApi": qoder_base,
                "quotaBase": qoder_base, "authBase": qoder_base})
        qoder_mod._MODEL_CACHE.clear()
        qoder_mod._CREDITS_CACHE.clear()
        qoder_mod._RISK_CACHE.clear()
        import base64 as b64
        fake_catalog = {"assistant": [
            {"key": "auto", "display_name": "Auto", "enable": True,
             "is_vl": True, "is_reasoning": True, "price_factor": 1.0,
             "context_config": {"default": {"token_count": 200000}}},
            {"key": "glm-5.3", "display_name": "GLM-5.3", "enable": True,
             "context_config": {"default": {"token_count": 128000}}},
        ]}
        qoder_signer.status = lambda product: {
            "installed": True, "detected": True, "version": "test",
            "runtimeInfo": "", "clientExe": ""}
        qoder_signer.read_credentials = lambda product: {
            "token": "dt-import", "refreshToken": "drt-import",
            "expiresAt": int((time.time() + 7 * 86400) * 1000),
            "machineId": "machine-import",
            "user": {"id": "qoder-intl-import", "name": "Qoder导入号",
                     "email": "qoder-import@example.com"}}
        qoder_signer.ensure_machine_id = lambda product: "machine-test"
        qoder_signer.catalog = lambda product, uid, mid, token: {
            "available": True, "catalog": fake_catalog}

        def fake_qoder_sign(product, uid, machine_id, token, origin, body_json,
                            model, source="system"):
            return {"url": qoder_base + qoder_mod.INFER_PATH,
                    "headers": {"Content-Type": "application/json"},
                    "bodyB64": b64.b64encode(body_json.encode("utf-8")).decode()}

        qoder_signer.sign = fake_qoder_sign
        qoder_mod._risk_identity = lambda account: {
            "machineToken": "mt", "machineType": "1", "machineCode": "1"}

    if zcode_base:
        zcode_mod.CFG.update({
            "zaiAnthropicBase": zcode_base + "/api/anthropic",
            "bigmodelAnthropicBase": zcode_base + "/api/bigmodel-anthropic",
            "startPlanAnthropicBase": zcode_base + "/api/v1/zcode-plan/anthropic",
            "billingBase": zcode_base + "/api/v1/zcode-plan",
            "oauthInitUrl": zcode_base + "/api/v1/oauth/cli/init",
            "oauthPollBase": zcode_base + "/api/v1/oauth/cli/poll",
            "oauthTokenUrl": zcode_base + "/api/v1/oauth/token",
            "businessLoginUrl": zcode_base + "/api/auth/z/login",
            "zaiBizBase": zcode_base,
            "bigmodelBizBase": zcode_base,
            "monitorQuotaUrl": zcode_base + "/api/monitor/usage/quota/limit",
        })
        zcode_mod._MODEL_CACHE.clear()
        zcode_mod._CREDITS_CACHE.clear()
        zcode_mod._activate_account = lambda *args, **kwargs: None
        # 冒烟用临时本机目录与内置官方前缀，不触摸真实 ZCode 安装
        zcode_dir = os.path.join(tmpdir, ".zcode", "v2")
        os.makedirs(os.path.join(zcode_dir, "account-profiles"), exist_ok=True)
        os.environ["ZCODE_V2_DIR"] = zcode_dir
        os.environ["ZCODE_BUNDLE_PATH"] = os.path.join(tmpdir, "no-bundle.cjs")
        live_jwt = fake_zcode_jwt("zcode-live-1")
        with open(os.path.join(zcode_dir, "credentials.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({
                "zcodejwttoken": zcode_encrypt(live_jwt),
                "oauth:active_provider": "zai",
                "oauth:zai:access_token": zcode_encrypt("at-live"),
                "oauth:zai:user_info": zcode_encrypt(json.dumps({
                    "user_id": "zcode-live-1", "name": "本机登录号"})),
                "account-provider:coding-plan:account:zai-individual-coding-plan:"
                "account:zcode-live-1:api-key": zcode_encrypt(
                    "0123456789abcdef0123456789abcdef.live-secret"),
            }, fh)
        with open(os.path.join(zcode_dir, "telemetry-state.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"deviceMid": "live-mid-1"}, fh)
        with open(os.path.join(zcode_dir, "account-profiles", "p1.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"zcodejwttoken": fake_zcode_jwt("zcode-profile-1"),
                       "oauth:active_provider": "zai"}, fh)
        with open(os.path.join(zcode_dir, "account-profiles", "profiles.json"), "w",
                  encoding="utf-8") as fh:
            json.dump([{
                "id": "p1", "user_id": "zcode-profile-1", "name": "档案号",
                "email": "p1@example.com", "family": "zai", "cred_file": "p1.json",
                "provider_api_keys": {
                    "builtin:zai-coding-plan":
                    "0123456789abcdef0123456789abcdef.profile-secret"},
            }], fh)

    cfg = workbuddy.realm_configs()
    for realm in ("intl", "cn"):
        cfg[realm].update({            "chat_upstream": base, "billing_upstream": base, "origin": base,
            "web_origin": base, "web_conversations_url": base + "/console/as/conversations/",
            "refresh_path": "/v2/plugin/auth/token/refresh",
            "auth_state_path": "/v2/plugin/auth/state",
            "auth_token_path": "/v2/plugin/auth/token",
            "login_account_path": "/v2/plugin/login/account",
            "checkin_path": "/v2/billing/meter/daily-checkin",
            "credits_path": "/v2/billing/meter/get-user-resource",
            "enterprise_usage_path": "/billing/meter/get-enterprise-user-usage",
        })
    workbuddy.realm_configs = lambda: cfg
    identity._ENDPOINTS = {key: (base, "127.0.0.1") for key in identity._ENDPOINTS}

    # 任务链基址同样指向假上游（streak/growth 直连国内版端点，不经 realm 配置）
    from tasks import growth as growth_mod
    from tasks import streak as streak_mod
    growth_mod.CHAT_BASE = base
    growth_mod.BILL_BASE = base
    streak_mod.CHAT_BASE = base
    streak_mod.BILL_BASE = base

    def smoke_register_channels(ctx_ref):
        # 测试里渠道模块已被打上 fake 上游补丁，注册动作与入口一致
        registry.register(workbuddy.WorkBuddyAdapter(), ctx_ref)
        registry.register(trae_mod.TraeAdapter(), ctx_ref)
        if qoder_base:
            registry.register(qoder_mod.QoderAdapter("qoder"), ctx_ref)
            registry.register(qoder_mod.QoderAdapter("qoder_intl"), ctx_ref)
        if zcode_base:
            registry.register(zcode_mod.ZcodeAdapter(), ctx_ref)
        if codearts_base:
            registry.register(codearts_mod.CodeArtsAdapter(), ctx_ref)
        if loomy_base:
            registry.register(loomy_mod.LoomyAdapter(), ctx_ref)

    ctx = context_mod.AppContext(accounts_dir=os.path.join(tmpdir, "accounts"),
                                 usage_dir=os.path.join(tmpdir, "usage"),
                                 log=lambda msg: None)
    # 冒烟基线：排程显式暂停。真实安装的缺省是「开」，而自动排程一旦命中整点，
    # 就会把真实任务塞进单线程队列，把用例显式触发的任务挤出等待窗口（22 点的
    # 保活巡检曾把 zcode 触发堵出 10 秒窗口）。用例需要排程时自己显式打开，
    # test_smoke 首尾各有一条断言守着「跑完必须回到暂停」这个不变量。
    settings.set_automation(ctx.accounts_dir, {"enabled": False})
    upstream_body.set_prompt_config_reader(
        lambda: settings.prompt_config(ctx.accounts_dir))
    authz.configure(ctx, launcher_key="sk-test")
    ctx.boot(register_channels=smoke_register_channels)

    import auth.accounts as accounts_mod
    if qoder_base:
        # 冒烟不触摸本机 WorkBuddy 桌面凭据
        accounts_mod.scan_desktop_credentials = lambda: []
    account = accounts_mod.Account({
        "uid": "u1", "nickname": "测试号", "realm": "intl",
        "accessToken": "tok", "refreshToken": "r", "enabled": True})
    account.save(ctx.accounts_dir)
    # 国内版账号：连登管家等国内专属任务的测试载体
    account_cn = accounts_mod.Account({
        "uid": "u2", "nickname": "测试号CN", "realm": "cn",
        "accessToken": "tok", "refreshToken": "r", "enabled": True})
    account_cn.save(ctx.accounts_dir)
    # Trae 账号：refreshToken 换发型（uid 与假上游 fake_jwt 的 uid 对齐）
    account_trae = accounts_mod.Account({
        "uid": "trae-uid-1", "nickname": "Trae测试号", "realm": "trae",
        "domain": "trae-api-cn.mchost.guru", "refreshToken": "rt-seed",
        "enabled": True})
    account_trae.save(ctx.accounts_dir)
    accounts_mod.Account({
        "uid": "trae-uid-2", "nickname": "Trae轮询号", "realm": "trae",
        "domain": "trae-api-cn.mchost.guru", "refreshToken": "rt-seed-2",
        "enabled": False}).save(ctx.accounts_dir)
    if qoder_base:
        account_qoder = accounts_mod.Account({
            "uid": "qoder-uid-1", "nickname": "Qoder测试号", "realm": "qoder",
            "domain": "qoder.com.cn", "accessToken": "dt-test",
            "refreshToken": "drt-test",
            "expiresAt": int(time.time() + 7 * 86400), "enabled": True,
            "meta": {"product": "qoder", "machineId": "machine-test"}})
        account_qoder.save(ctx.accounts_dir)
        accounts_mod.Account({
            "uid": "qoder-uid-2", "nickname": "Qoder轮询号", "realm": "qoder",
            "domain": "qoder.com.cn", "accessToken": "dt-test-2",
            "refreshToken": "drt-test-2",
            "expiresAt": int(time.time() + 7 * 86400), "enabled": False,
            "meta": {"product": "qoder", "machineId": "machine-test-2"}}
        ).save(ctx.accounts_dir)
    if codearts_base:
        codearts_acc = accounts_mod.Account({
            "uid": "dom-seed-user-seed", "nickname": "CodeArts测试号",
            "realm": "codearts", "domain": "codearts.huaweicloud.com",
            "expiresAt": int(time.time() + 3600), "enabled": True,
            "meta": {"domainId": "dom-seed", "userId": "user-seed",
                     "userName": "CodeArts测试号", "loginType": "WEB"},
        })
        codearts_mod._apply_credential(codearts_acc, {
            "access_key_id": "AK-seed",
            "secret_access_key": "SK-seed",
            "security_token": "STS-seed",
            "refresh_token": "rt-seed",
            "expires_at": int(time.time() + 3600),
            "domain_id": "dom-seed",
            "user_id": "user-seed",
            "user_name": "CodeArts测试号",
            "login_type": "WEB",
            "oauth_context": {
                "dpop_key_pair": codearts_mod.generate_dpop_key_pair(),
                "code_verifier": "smoke-verifier",
            },
        })
        codearts_acc.save(ctx.accounts_dir)
    if zcode_base:
        plan_key = "0123456789abcdef0123456789abcdef.test-secret"
        accounts_mod.Account({
            "uid": "zcode-uid-1", "nickname": "ZCode JWT 号", "realm": "zcode",
            "domain": "zcode.z.ai", "accessToken": fake_zcode_jwt("zcode-uid-1"),
            "expiresAt": 0, "enabled": True,
            "meta": {"provider": "zai", "deviceMid": "dev-zcode-1"}},
        ).save(ctx.accounts_dir)
        accounts_mod.Account({
            "uid": "zcode-uid-2", "nickname": "ZCode 双凭据号", "realm": "zcode",
            "domain": "zcode.z.ai", "accessToken": fake_zcode_jwt("zcode-uid-2"),
            "refreshToken": plan_key, "expiresAt": 0, "enabled": True,
            "meta": {"provider": "zai", "deviceMid": "dev-zcode-2"}},
        ).save(ctx.accounts_dir)
        accounts_mod.Account({
            "uid": "zcode-uid-3", "nickname": "ZCode 套餐 key 号", "realm": "zcode",
            "domain": "zcode.z.ai", "accessToken": plan_key,
            "refreshToken": plan_key, "expiresAt": 0, "enabled": True,
            "meta": {"provider": "zai", "deviceMid": "dev-zcode-3",
                     "credentialMode": "coding-plan"}},
        ).save(ctx.accounts_dir)
    ctx.pool.load()

    http_mod.ROUTER._routes.clear()
    proxy_api.install(http_mod.ROUTER)
    panel_routes.install(http_mod.ROUTER)
    panel_static.install(http_mod.ROUTER, ctx)
    server = http_mod.make_server("127.0.0.1", 0, http_mod.BaseHandler, ctx)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return ctx, server, "http://127.0.0.1:%d" % server.server_address[1]




def request(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def parse_sse(text):
    """SSE 文本 → data 行 JSON 列表（跳过 [DONE] 与非 JSON）。"""
    out = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            out.append(json.loads(payload))
        except Exception:
            pass
    return out





