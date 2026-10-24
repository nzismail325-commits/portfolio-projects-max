// Qoder 签名桥：Python 网关 ↔ 本机 Qoder 客户端 wasm 的最小 RPC
//
// 协议：stdin/stdout 每行一个 JSON
//   请求  {"id": <int>, "op": "...", ...args}
//   响应  {"id": <int>, "ok": true, "result": {...}}
//         {"id": <int>, "ok": false, "error": "...", "signerDown": bool}
// stderr 只写诊断日志，stdout 绝不混入非 JSON。
//
// 操作：
//   status           定位客户端与签名器（不加载 wasm）
//   read_credentials 解密本机 auth.v1.dat（供面板扫描/导入）
//   ensure_machine_id 读取或生成 ~/.qoder{,-cn}/.auth/machine_id
//   catalog          解密本机 catalog-v6 并返回原始 JSON
//   sign             为一次推理请求生成签名 URL/头/Encode=1 包体
//   ping             健康检查
"use strict";
const readline = require("node:readline");
const auth = require("./auth.cjs");
const signer = require("./signer.cjs");

const MAX_SESSIONS = 12;
const sessions = new Map(); // `${product}|uid|machineId|token` -> { session, at }

function log(msg) {
  try {
    process.stderr.write(`[qoder-bridge] ${msg}\n`);
  } catch {
    /* 忽略 */
  }
}

async function acquireSession(product, token, uid, machineId) {
  const key = `${product}|${uid}|${machineId}|${token}`;
  const hit = sessions.get(key);
  if (hit) {
    hit.at = Date.now();
    return hit.session;
  }
  let session;
  try {
    session = await signer.createSession({ product, token, uid, machineId });
  } catch (e) {
    const err = new Error(`Qoder 签名器不可用：${String((e && e.message) || e).slice(0, 240)}`);
    err.signerDown = true;
    throw err;
  }
  sessions.set(key, { session, at: Date.now() });
  while (sessions.size > MAX_SESSIONS) {
    let evictKey = null;
    let oldest = Infinity;
    for (const [k, v] of sessions) {
      if (v.at < oldest) {
        oldest = v.at;
        evictKey = k;
      }
    }
    if (!evictKey) break;
    const ev = sessions.get(evictKey);
    sessions.delete(evictKey);
    try {
      ev.session.free && ev.session.free();
    } catch {
      /* 已释放 */
    }
  }
  return session;
}

function parseProduct(v) {
  const p = String(v || "qoder");
  if (!auth.PRODUCTS[p]) throw new Error(`未知 Qoder 产品：${p}`);
  return p;
}

async function handle(req) {
  const op = String(req.op || "");
  if (op === "ping") return { pong: true };
  if (op === "status") {
    const product = parseProduct(req.product);
    const loc = signer.describe(product);
    let detected = false;
    try {
      detected = !!auth.detect(product);
    } catch {
      detected = false;
    }
    return { ...loc, detected };
  }
  if (op === "read_credentials") {
    const product = parseProduct(req.product);
    return auth.readCredentials(product);
  }
  if (op === "ensure_machine_id") {
    const product = parseProduct(req.product);
    return { machineId: auth.ensureMachineId(product) };
  }
  if (op === "catalog") {
    const product = parseProduct(req.product);
    const uid = String(req.uid || "");
    const token = String(req.token || "");
    const machineId = String(req.machineId || "");
    if (!uid) throw new Error("缺少 uid");
    if (!token) throw new Error("缺少 token");
    const blob = auth.readCatalogBlob(product, uid);
    if (!blob) return { available: false, reason: "本机无模型目录缓存（该客户端尚未登录使用过）" };
    const session = await acquireSession(product, token, uid, machineId);
    let json;
    try {
      json = JSON.parse(session.modelCacheDecrypt(blob, uid));
    } catch (e) {
      throw new Error(`目录解密失败：${String((e && e.message) || e).slice(0, 160)}`);
    }
    return { available: true, catalog: json };
  }
  if (op === "sign") {
    const product = parseProduct(req.product);
    const uid = String(req.uid || "");
    const token = String(req.token || "");
    const machineId = String(req.machineId || "");
    const origin = String(req.origin || "");
    const body = String(req.body || "");
    const model = String(req.model || "");
    if (!token) throw new Error("缺少 token");
    if (!origin) throw new Error("缺少 origin");
    if (!model) throw new Error("缺少 model");
    const session = await acquireSession(product, token, uid, machineId);
    const signed = session.prepareInferRequest(origin, body, model, req.source || "system");
    return {
      url: signed.url,
      headers: signed.headers,
      bodyB64: signed.body.toString("base64"),
    };
  }
  throw new Error(`未知操作：${op}`);
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let chain = Promise.resolve();

rl.on("line", (line) => {
  if (!line.trim()) return;
  chain = chain.then(async () => {
    let req;
    try {
      req = JSON.parse(line);
    } catch (e) {
      process.stdout.write(JSON.stringify({ id: null, ok: false, error: "bad json" }) + "\n");
      return;
    }
    const id = req.id;
    try {
      const result = await handle(req);
      process.stdout.write(JSON.stringify({ id, ok: true, result }) + "\n");
    } catch (e) {
      const signerDown = !!(e && (e.signerDown || req.op === "sign" || req.op === "catalog"));
      process.stdout.write(JSON.stringify({
        id,
        ok: false,
        error: String((e && e.message) || e).slice(0, 400),
        signerDown,
      }) + "\n");
    }
  }).catch((e) => {
    log(`handler failure: ${String((e && e.message) || e)}`);
  });
});

rl.on("close", () => {
  for (const [, v] of sessions) {
    try {
      v.session.free && v.session.free();
    } catch {
      /* 忽略 */
    }
  }
  sessions.clear();
  process.exit(0);
});

log("ready");
