// Qoder 凭据层（qoder / qoder_intl 双区共用）
//
// 移植自 AgentHub v1.77.0 electron/backend/proxy/qoderAuth.cjs（MIT + 附加条款，
// 仅限非商业自用；出处与条款见 NOTICE.md）。保留读取/设备标识/风控身份/目录读取；
// 写回客户端登录态（writeCredentials）未启用——本项目不接管桌面客户端切号。
"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { execFileSync } = require("node:child_process");
const qoderInstall = require("./install.cjs");

const PRODUCTS = {
  qoder: {
    label: "Qoder CN",
    appDir: "com.qodercn.app.stable",
    homeDir: ".qoder-cn",
    openApi: "https://openapi.qoder.com.cn",
    gateway: "https://gateway.qoder.com.cn",
    exeLabel: qoderInstall.EXE_LABELS.qoder,
    authBase: "https://qoder.cn",
    clientId: "732aef47-9cf2-46a2-95fe-4cebb5d0d1fa",
    authBizVariant: "qoder",
  },
  qoder_intl: {
    label: "Qoder International",
    appDir: "com.qoder.app.stable",
    homeDir: ".qoder",
    openApi: "https://openapi.qoder.sh",
    gateway: "https://api2.qoder.sh",
    exeLabel: qoderInstall.EXE_LABELS.qoder_intl,
    authBase: "https://qoder.com",
    clientId: "732aef47-9cf2-46a2-95fe-4cebb5d0d1fa",
    authBizVariant: "qoder",
  },
};

function roamingDir() {
  return process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
}

function homeDir() {
  return process.env.USERPROFILE || os.homedir();
}

function pathsOf(product) {
  const p = PRODUCTS[product];
  if (!p) return null;
  const appData = path.join(roamingDir(), p.appDir);
  const home = path.join(homeDir(), p.homeDir);
  return {
    appData,
    home,
    authFile: path.join(appData, "auth.v1.dat"),
    localState: path.join(appData, "Local State"),
    machineIdFile: path.join(home, ".auth", "machine_id"),
    catalogDir: path.join(home, ".models"),
    projectsDir: path.join(home, "projects"),
  };
}

function riskIdentityPath(product) {
  const p = PRODUCTS[product];
  if (!p || !p.exeLabel) return "";
  return qoderInstall.runtimeInfoPath(product);
}

function ensureMachineId(product) {
  const p = pathsOf(product);
  if (!p) return crypto.randomUUID();
  try {
    const cur = fs.readFileSync(p.machineIdFile, "utf8").trim();
    if (cur) return cur;
  } catch {
    /* 未登录/未安装 */
  }
  const id = crypto.randomUUID();
  try {
    fs.mkdirSync(path.dirname(p.machineIdFile), { recursive: true });
    fs.writeFileSync(p.machineIdFile, id, "utf8");
  } catch {
    /* 写不进去就只返回内存值 */
  }
  return id;
}

const RISK_CACHE_TTL_MS = 10 * 60 * 1000;
const riskCache = new Map();

function readRiskIdentity(product, uid) {
  const exe = riskIdentityPath(product);
  if (!exe || !fs.existsSync(exe)) return null;
  const hit = riskCache.get(product);
  if (hit && Date.now() - hit.at < RISK_CACHE_TTL_MS) return hit.value;
  try {
    const out = execFileSync(exe, ["--account-stdin"], {
      input: JSON.stringify({ account: String(uid || "") }),
      encoding: "utf8",
      timeout: 20000,
      windowsHide: true,
      maxBuffer: 1 << 20,
    }).trim();
    if (!out) return null;
    const j = JSON.parse(out);
    if (!j || typeof j.machineToken !== "string" || !j.machineToken) return null;
    const value = {
      machineToken: j.machineToken,
      machineType: j.machineType || "",
      machineCode: j.machineCode || "",
      vmInfo: j.vmInfo || null,
    };
    riskCache.set(product, { at: Date.now(), value });
    return value;
  } catch {
    return null;
  }
}

function clearRiskCache() {
  riskCache.clear();
}

function detect(product) {
  const p = pathsOf(product);
  if (!p) return null;
  return fs.existsSync(p.authFile) || fs.existsSync(p.appData) ? p : null;
}

function detectAll() {
  const out = {};
  for (const id of Object.keys(PRODUCTS)) out[id] = !!detect(id);
  return out;
}

let dpapiCache = null;

function dpapiUnprotectKey(b64) {
  if (dpapiCache && dpapiCache.b64 === b64) return dpapiCache.key;
  const raw = Buffer.from(b64, "base64");
  const magic = raw.subarray(0, 5).toString("ascii");
  if (magic !== "DPAPI") throw new Error(`os_crypt 前缀异常：${magic}`);
  const wrapped = raw.subarray(5);
  const script = [
    "$ErrorActionPreference='Stop'",
    "Add-Type -AssemblyName System.Security | Out-Null",
    `$b=[Convert]::FromBase64String('${wrapped.toString("base64")}')`,
    "$k=[System.Security.Cryptography.ProtectedData]::Unprotect($b,$null,[System.Security.Cryptography.DataProtectionScope]::CurrentUser)",
    "[Convert]::ToBase64String($k)",
  ].join("; ");
  let out = "";
  try {
    out = execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      encoding: "utf8",
      windowsHide: true,
      timeout: 15000,
    }).trim();
  } catch (e) {
    throw new Error(
      `DPAPI 解密失败（需与 Qoder 客户端同一 Windows 用户）：${String((e && e.message) || e).slice(0, 120)}`);
  }
  const key = Buffer.from(out, "base64");
  if (key.length !== 32) throw new Error(`DPAPI 返回密钥长度异常：${key.length}`);
  dpapiCache = { b64, key };
  return key;
}

function decryptV10(blob, key) {
  if (blob.subarray(0, 3).toString("ascii") !== "v10") {
    throw new Error("auth.v1.dat 魔数异常（非 v10 信封）");
  }
  const nonce = blob.subarray(3, 15);
  const tag = blob.subarray(blob.length - 16);
  const ct = blob.subarray(15, blob.length - 16);
  const d = crypto.createDecipheriv("aes-256-gcm", key, nonce);
  d.setAuthTag(tag);
  return Buffer.concat([d.update(ct), d.final()]);
}

function parseTimestampMs(v) {
  if (v == null || v === "") return 0;
  const n = Number(v);
  if (Number.isFinite(n) && String(v).trim() !== "" && !/[^\d.]/.test(String(v).trim())) {
    return n > 0 ? Math.floor(n) : 0;
  }
  const t = Date.parse(String(v));
  return Number.isFinite(t) ? t : 0;
}

function readCredentials(product) {
  const p = pathsOf(product);
  if (!p) throw new Error(`未知渠道 ${product}`);
  if (!fs.existsSync(p.authFile)) {
    throw new Error(`${PRODUCTS[product].label} 未登录（找不到 auth.v1.dat）`);
  }
  const ls = JSON.parse(fs.readFileSync(p.localState, "utf8"));
  const encKey = ls && ls.os_crypt && ls.os_crypt.encrypted_key;
  if (!encKey) throw new Error("Local State 缺少 os_crypt.encrypted_key");
  const key = dpapiUnprotectKey(encKey);
  const store = JSON.parse(decryptV10(fs.readFileSync(p.authFile), key).toString("utf8"));
  let machineId = "";
  try {
    machineId = fs.readFileSync(p.machineIdFile, "utf8").trim();
  } catch {
    /* 缺失时由调用方生成 */
  }
  return {
    token: String(store.token || ""),
    refreshToken: String(store.refreshToken || ""),
    expiresAt: parseTimestampMs(store.expiresAt),
    refreshTokenExpiresAt: parseTimestampMs(store.refreshTokenExpiresAt),
    user: store.user || {},
    machineId,
    product,
  };
}

function catalogPath(product, uid) {
  const p = pathsOf(product);
  return p && uid ? path.join(p.catalogDir, uid, "catalog-v6") : null;
}

function readCatalogBlob(product, uid) {
  const f = catalogPath(product, uid);
  if (!f || !fs.existsSync(f)) return null;
  return fs.readFileSync(f, "utf8");
}

module.exports = {
  PRODUCTS,
  pathsOf,
  detect,
  detectAll,
  readCredentials,
  catalogPath,
  readCatalogBlob,
  riskIdentityPath,
  readRiskIdentity,
  clearRiskCache,
  ensureMachineId,
  parseTimestampMs,
  decryptV10,
  dpapiUnprotectKey,
};
