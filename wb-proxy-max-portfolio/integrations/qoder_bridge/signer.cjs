// Qoder 请求签名器（WASM 驱动）
//
// 移植自 AgentHub v1.77.0 electron/backend/proxy/qoderSigner.cjs（MIT + 附加条款，
// 仅限非商业自用；出处与条款见 NOTICE.md）。差异仅在于去除 AgentHub 的 config
// 依赖，补丁缓存目录由 WB_QODER_SIGNER_CACHE 指定（Python 侧传入 accounts 目录）。
//
// 为什么必须这样做：Qoder 的推理请求每请求签名（Cosy-* 头），请求体还要 Encode=1
// 自定义编码，二者都由 Qoder 客户端内置 wasm 完成，无法手工构造。本模块把 wasm 与
// wasm-bindgen 胶水从本机已安装客户端提取出来，在 Node 里独立驱动。
"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");
const { pathToFileURL } = require("node:url");
const install = require("./install.cjs");

const ENTRY_MARK = "SY(),Bir(";
const WASM_MAGIC = "AGFzbQEAAAA";
const REQUIRED_FEATURES = ["wasmVar", "glueVar", "initAsync"];
const CACHE_VERSION = 4;
const BOOTSTRAP_NEAR_EOF = 8192;

function pickByStructure(text) {
  const pick = (res) => {
    for (const re of Array.isArray(res) ? res : [res]) {
      const m = text.match(re);
      if (m) return m[1];
    }
    return "";
  };
  const names = {
    wasmVar: pick([
      /([A-Za-z_$][\w$]*)="AGFzbQEAAAA/,
      /([A-Za-z_$][\w$]*)='AGFzbQEAAAA/,
      /([A-Za-z_$][\w$]*)=`AGFzbQEAAAA/,
    ]),
    loaderWasm: pick([
      /,\s*([A-Za-z_$][\w$]*)=b\(\(\)=>\{[A-Za-z_$][\w$]*=["'`]AGFzbQEAAAA/,
      /,\s*([A-Za-z_$][\w$]*)=(?:async\s+)?(?:[\w$]+\s*)?\([^)]*\)\s*(?:=>)?\s*\{[A-Za-z_$][\w$]*=["'`]AGFzbQEAAAA/,
    ]),
    glueVar: pick([
      /er\(([A-Za-z_$][\w$]*),\s*\{[^{}]{0,800}?QoderContext:\(\)=>/,
      /er\(\s*([A-Za-z_$][\w$]*)\s*,\s*\{[\s\S]{0,3000}?QoderContext\s*:\s*\(\)\s*=>/,
    ]),
    profileEnc: pick(/ProfileEncryptor:\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)/),
    initSync: pick(/initSync:\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)/),
  };
  const erAt = text.search(/er\(\s*[A-Za-z_$][\w$]*\s*,\s*\{[\s\S]{0,3000}?QoderContext\s*:\s*\(\)\s*=>/);
  if (erAt >= 0) {
    const m = text.slice(erAt, erAt + 3000).match(/default:\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)/);
    if (m) names.initAsync = m[1];
  }
  if (names.profileEnc) {
    const at = text.indexOf(names.profileEnc + "=class");
    if (at > 0) {
      const before = text.slice(Math.max(0, at - 1200), at);
      const m = before.match(/,([A-Za-z_$][\w$]*)=b\(\(\)=>\{$/) ||
        before.match(/([A-Za-z_$][\w$]*)=b\(\(\)=>\{/) ||
        before.match(/([A-Za-z_$][\w$]*)=[^{}]{0,200}\{$/);
      if (m) names.loaderGlue = m[1];
    }
  }
  if (!names.loaderGlue && names.glueVar) {
    const at = text.search(new RegExp(`er\\(\\s*${names.glueVar.replace(/\$/g, "\\$")}\\s*,`));
    if (at > 0) {
      const before = text.slice(0, at);
      const idx = before.lastIndexOf("=b(()=>{");
      if (idx > 0) {
        const m = before.slice(0, idx).match(/([A-Za-z_$][\w$]*)$/);
        if (m) names.loaderGlue = m[1];
      }
    }
  }
  const peKeyAt = names.profileEnc
    ? text.indexOf("ProfileEncryptor:()=>" + names.profileEnc)
    : -1;
  const regCall = (() => {
    if (peKeyAt <= 0) return null;
    const m = text.slice(0, peKeyAt).match(/([A-Za-z_$][\w$]*)\(([A-Za-z_$][\w$]*),\s*\{$/);
    return m ? { fn: m[1], varName: m[2], at: peKeyAt - m[0].length } : null;
  })();
  const wasmDeclAt = (() => {
    const m = text.match(/([A-Za-z_$][\w$]*)=["'`]AGFzbQEAAAA/);
    return m ? m.index : -1;
  })();
  if (regCall) {
    const seg = text.slice(regCall.at, regCall.at + 8000);
    const isGlueSeg = /default:\s*\(\)\s*=>/.test(seg) &&
      new RegExp("initSync:\\s*\\(\\)\\s*=>").test(seg);
    if (!names.glueVar && isGlueSeg) names.glueVar = regCall.varName;
    if (!names.initAsync && isGlueSeg) {
      const m = seg.match(/default:\s*\(\)\s*=>\s*([A-Za-z_$][\w$]*)/);
      if (m) names.initAsync = m[1];
    }
    if (!names.loaderGlue) {
      const m = text.slice(0, regCall.at).match(/([A-Za-z_$][\w$]*)=[^{}]{0,200}\{$/);
      if (m) names.loaderGlue = m[1];
    }
  }
  if (!names.loaderWasm && wasmDeclAt > 0) {
    const m = text.slice(0, wasmDeclAt).match(/([A-Za-z_$][\w$]*)=[^{}]{0,200}\{$/);
    if (m) names.loaderWasm = m[1];
  }
  return names;
}

function findWorkerBootstrap(text) {
  const nearEof = (re) => {
    let m;
    let last = null;
    while ((m = re.exec(text))) {
      if (text.length - m.index <= BOOTSTRAP_NEAR_EOF) last = m.index;
    }
    return last;
  };
  const invocations = [
    ["async-call", /,\s*[A-Za-z_$][\w$]*\s*\(\s*async\s*\(\)\s*=>\s*\{/g],
    ["sites-ternary", /,\s*[^,;{}]{0,200}?===\s*process\.argv\[2\]\s*\?/g],
    ["argv-call", /,\s*[A-Za-z_$][\w$]*\s*\(\s*process\.argv/g],
  ];
  let best = null;
  for (const [anchor, re] of invocations) {
    const at = nearEof(re);
    if (at !== null && (!best || at > best.at)) best = { anchor, at, kind: "invocation" };
  }
  if (!best) {
    const at = nearEof(/process\.env\.QODERCLI_RUNTIME_PACKAGING\s*=\s*["']worker_mjs["']/g);
    if (at !== null) best = { anchor: "env", at, kind: "env" };
  }
  if (!best) return null;
  return { ...best, fromEnd: text.length - best.at };
}

function neutralizeWorkerBootstrap(text) {
  const hit = findWorkerBootstrap(text);
  if (!hit) return { text, bootstrap: null };
  return { text: `${text.slice(0, hit.at).trimEnd()}\n;\n`, bootstrap: hit };
}

function smokePatchedModule(file) {
  const code = [
    "try {",
    "  const m = await import(process.argv[1]);",
    "  await m.initGlue();",
    "  await new Promise((r) => setTimeout(r, 1200));",
    '  console.log("SIGNER-OK");',
    "  process.exit(0);",
    "} catch (e) {",
    '  console.error("SIGNER-ERR", e && (e.stack || e.message));',
    "  process.exit(8);",
    "}",
  ].join("\n");
  const r = spawnSync(process.execPath, ["--input-type=module", "-e", code, pathToFileURL(file).href], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" },
    timeout: 20000,
    encoding: "utf8",
    windowsHide: true,
  });
  if (r.error) throw new Error(`签名器补丁自检启动失败：${r.error.message}`);
  if (r.status !== 0 || !/SIGNER-OK/.test(String(r.stdout || ""))) {
    const detail = String(r.stderr || r.stdout || "").replace(/\s+/g, " ").slice(-500);
    throw new Error(`签名器补丁自检失败（exit=${r.status}${r.signal ? ` signal=${r.signal}` : ""}）：${detail || "无输出"}`);
  }
}

function patchText(text) {
  const cut = text.indexOf(ENTRY_MARK);
  if (cut >= 0) {
    return `${text.slice(0, cut)}\nexport{t9 as initGlue,Hm as glue};\n`;
  }
  const n = pickByStructure(text);
  const missing = REQUIRED_FEATURES.filter((k) => !n[k]);
  if (missing.length) {
    const err = new Error(`Qoder worker 结构变化：通用提取缺 ${missing.join("/")}（客户端版本可能大改，需重新适配）`);
    err.qoderDiag = {
      entryMarkHit: false,
      hasInlineWasm: text.includes(WASM_MAGIC),
      features: n,
      missing,
    };
    throw err;
  }
  const neutral = neutralizeWorkerBootstrap(text);
  const lines = [neutral.text, ""];
  if (n.loaderGlue) {
    lines.push(`try { ${n.loaderGlue}(); } catch (e) { /* 懒加载失败留给 initGlue 报错 */ }`);
  }
  if (n.loaderWasm) {
    lines.push(`try { ${n.loaderWasm}(); } catch (e) { /* 懒加载失败留给 initGlue 报错 */ }`);
  }
  lines.push(
    `export async function initGlue() { await ${n.initAsync}(Buffer.from(${n.wasmVar}, "base64")); }`,
    `export function glue() { return ${n.glueVar}; }`,
    "",
  );
  return lines.join("\n");
}

function cacheDir() {
  const d = process.env.WB_QODER_SIGNER_CACHE ||
    path.join(os.homedir(), ".wb-proxy-max", "qoder-signer");
  fs.mkdirSync(d, { recursive: true });
  return d;
}

function locate(product) {
  const res = install.findResources(product);
  if (!res) return null;
  for (const sdk of ["qoder-agent-sdk", "qoder-cn-agent-sdk"]) {
    const obf = path.join(res, "app.asar.unpacked", "node_modules", "@qoder-ai",
      sdk, "dist", "_worker", "qoder-worker-runtime.obf.mjs");
    if (!fs.existsSync(obf)) continue;
    let version = "0.4.3";
    try {
      const bm = JSON.parse(fs.readFileSync(path.join(res, "build-manifest.json"), "utf8"));
      if (bm && bm.productVersion) version = String(bm.productVersion);
    } catch {
      /* 缺失则用兜底版本号 */
    }
    return { obf, version, resources: res, sdk };
  }
  return null;
}

function buildPatchedModule(product, loc) {
  if (!loc || !loc.obf) throw new Error(`${product} 客户端未安装或结构不匹配，无法提取签名器`);
  const st = fs.statSync(loc.obf);
  const hash = crypto.createHash("sha256")
    .update(`${product}:${loc.sdk || ""}:${st.size}:${Math.floor(st.mtimeMs)}:v${CACHE_VERSION}`)
    .digest("hex").slice(0, 16);
  const out = path.join(cacheDir(), `worker-${product}-${hash}.mjs`);
  if (fs.existsSync(out)) return out;
  const text = fs.readFileSync(loc.obf, "utf8");
  let patched;
  try {
    patched = patchText(text);
  } catch (e) {
    if (e && e.qoderDiag) {
      const d = e.qoderDiag;
      const hit = Object.keys(d.features || {}).filter((k) => d.features[k]);
      e.message +=
        `｜客户端版本=${loc.version} sdk=${loc.sdk || "?"} obf=${st.size}B` +
        `｜入口标记${d.entryMarkHit ? "命中" : "未命中"}，内嵌 wasm ${d.hasInlineWasm ? "在" : "不在"}，已命中特征=${hit.join(",") || "无"}`;
    }
    throw e;
  }
  const tmp = `${out}.tmp.${process.pid}.mjs`;
  fs.writeFileSync(tmp, patched, "utf8");
  try {
    const leftover = findWorkerBootstrap(patched);
    if (leftover && leftover.kind === "invocation") {
      throw new Error(`补丁仍包含 worker 启动入口（锚点=${leftover.anchor}，距末尾 ${leftover.fromEnd}B）`);
    }
    smokePatchedModule(tmp);
    fs.renameSync(tmp, out);
  } catch (e) {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* 已删除 */
    }
    throw new Error(`Qoder 签名器补丁不可用：${(e && e.message) || e}`);
  }
  try {
    for (const f of fs.readdirSync(cacheDir())) {
      if (f.startsWith(`worker-${product}-`) && f !== path.basename(out) &&
        f.endsWith(".mjs") && !f.includes(".tmp.")) {
        fs.unlinkSync(path.join(cacheDir(), f));
      }
    }
  } catch {
    /* 清理失败不影响功能 */
  }
  return out;
}

const signerCache = new Map();

async function loadGlue(product) {
  if (signerCache.has(product)) return signerCache.get(product);
  const p = (async () => {
    const loc = locate(product);
    if (!loc) return null;
    const mod = await import(pathToFileURL(buildPatchedModule(product, loc)).href);
    await mod.initGlue();
    return { glue: mod.glue(), version: loc.version, resources: loc.resources, sdk: loc.sdk };
  })();
  p.then((v) => {
    if (!v) signerCache.delete(product);
  }).catch(() => {
    signerCache.delete(product);
  });
  signerCache.set(product, p);
  return p;
}

async function available(product) {
  try {
    return !!(await loadGlue(product));
  } catch {
    return false;
  }
}

async function createSession({ product, token, uid, machineId }) {
  const loaded = await loadGlue(product);
  if (!loaded) {
    throw new Error(`${product} 客户端未安装，无法签名（请先安装并登录对应版本）`);
  }
  const { glue, version } = loaded;
  const seed = JSON.stringify({
    uid,
    security_oauth_token: token,
    organization_id: "",
    organization_tags: [],
    data_policy_agreed: true,
  });
  const runtime = JSON.parse(glue.generate_runtime_auth_fields(seed));
  const userAuth = {
    uid,
    encrypt_user_info: runtime.encrypt_user_info,
    key: runtime.key,
    organization_id: "",
    organization_tags: [],
    data_policy_agreed: true,
  };
  const ctx = new glue.QoderContext(
    machineId || "00000000-0000-0000-0000-000000000000",
    version,
    JSON.stringify(userAuth),
    "{}");
  ctx.refreshAuthFields(JSON.stringify(userAuth));
  return {
    version,
    prepareInferRequest(origin, bodyJson, modelKey, source = "system") {
      const r = ctx.prepareInferRequest(origin, bodyJson, modelKey, source);
      const headers = {};
      const pairs = r.headers instanceof Map ? [...r.headers.entries()] : Object.entries(r.headers || {});
      for (const [k, v] of pairs) headers[k] = String(v);
      return { url: r.url, headers, body: Buffer.from(r.body.buffer ?? r.body) };
    },
    modelCacheDecrypt(text, ownerUid) {
      return glue.model_cache_decrypt(text, ownerUid);
    },
    free() {
      try {
        ctx.free && ctx.free();
      } catch {
        /* 忽略 */
      }
    },
  };
}

function describe(product) {
  const loc = locate(product);
  return {
    product,
    installed: !!loc,
    obf: loc ? loc.obf : null,
    version: loc ? loc.version : null,
    resources: loc ? loc.resources : null,
    sdk: loc ? loc.sdk : null,
    clientExe: install.clientExePath(product) || null,
    runtimeInfo: install.runtimeInfoPath(product) || null,
  };
}

module.exports = {
  locate,
  available,
  createSession,
  describe,
  installResources: install.findResources,
  buildPatchedModule,
  patchText,
  pickByStructure,
  findWorkerBootstrap,
};
