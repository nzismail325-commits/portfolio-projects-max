// Qoder 客户端安装定位（qoder / qoder_intl 双区共用）
//
// 移植自 AgentHub v1.77.0 electron/backend/proxy/qoderInstall.cjs（MIT + 附加条款，
// 仅限本项目的非商业自用场景；上游出处与条款见同目录 NOTICE.md）。
// 差异：环境变量改用 WB_QODER* 前缀（保留 AGENTHUB_* 兼容），并新增 clientExePath
// 供 Python 侧在系统 Node 缺失时以 ELECTRON_RUN_AS_NODE 启动签名桥。
"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const EXE_LABELS = { qoder: "Qoder CN", qoder_intl: "Qoder" };
const EXE_FILES = { qoder: "Qoder CN.exe", qoder_intl: "Qoder.exe" };
const ENV_KEYS = {
  qoder: ["WB_QODER_RESOURCES", "AGENTHUB_QODER_RESOURCES"],
  qoder_intl: ["WB_QODER_INTL_RESOURCES", "AGENTHUB_QODER_INTL_RESOURCES"],
};

const cache = new Map();

function localAppData() {
  return process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
}

function readLauncherIni(file) {
  let text = "";
  try {
    const buf = fs.readFileSync(file);
    const isUtf16 = (buf[0] === 0xff && buf[1] === 0xfe) ||
      (buf.length > 3 && buf[1] === 0x00 && buf[3] === 0x00);
    text = buf.toString(isUtf16 ? "utf16le" : "utf8");
  } catch {
    return null;
  }
  const pick = (k) => {
    const m = text.match(new RegExp(`^\\s*${k}\\s*=\\s*(.+?)\\s*$`, "m"));
    return m ? m[1].trim() : "";
  };
  const installDir = pick("installDir");
  if (!installDir) return null;
  return { installDir, appExecutable: pick("appExecutable") };
}

function sameProductDir(dirName, exeLabel) {
  if (!/qoder/i.test(dirName)) return false;
  const wantCn = /\bCN\b/i.test(exeLabel);
  const isCn = /\bCN\b/i.test(dirName) || /中国/i.test(dirName);
  return wantCn === isCn;
}

function launcherResources(exeLabel) {
  const local = localAppData();
  const out = [];
  let subs = [];
  try {
    subs = fs.readdirSync(local);
  } catch {
    return out;
  }
  for (const sub of subs) {
    if (!sameProductDir(sub, exeLabel)) continue;
    const base = path.join(local, sub);
    let inners = [];
    try {
      inners = fs.readdirSync(base);
    } catch {
      continue;
    }
    for (const inner of inners) {
      if (!/launcher/i.test(inner)) continue;
      const dir = path.join(base, inner);
      const st = readLauncherIni(path.join(dir, "state.ini")) ||
        readLauncherIni(path.join(dir, "install.ini"));
      if (!st) continue;
      const appDir = st.appExecutable
        ? path.join(st.installDir, path.dirname(st.appExecutable))
        : st.installDir;
      out.push(path.join(appDir, "resources"));
      if (appDir !== st.installDir) out.push(path.join(st.installDir, "resources"));
    }
  }
  return out;
}

let regBlocks = null;
function queryRegBlocks() {
  if (regBlocks) return regBlocks;
  const roots = [
    "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
    "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
    "HKLM\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall",
  ];
  const blocks = [];
  for (const root of roots) {
    let txt = "";
    try {
      txt = execFileSync("reg.exe", ["query", root, "/s", "/f", "Qoder", "/d"], {
        encoding: "utf8",
        windowsHide: true,
        timeout: 10000,
        maxBuffer: 1 << 20,
      });
    } catch {
      continue;
    }
    for (const block of txt.split(/\r?\n\r?\n/)) {
      const name = (block.match(/DisplayName\s+REG_SZ\s+(.+)/i) || [])[1] || "";
      if (!/qoder/i.test(name)) continue;
      const icon = (block.match(/DisplayIcon\s+REG_SZ\s+(.+)/i) || [])[1] || "";
      const loc = (block.match(/InstallLocation\s+REG_SZ\s+(.+)/i) || [])[1] || "";
      const iconDir = icon
        ? path.dirname(icon.replace(/,+\d+$/, "").replace(/^"|"$/g, ""))
        : "";
      blocks.push({ name, iconDir, loc });
    }
  }
  regBlocks = blocks;
  return blocks;
}

function registryResources(exeLabel) {
  const wantCn = /\bCN\b/i.test(exeLabel);
  const out = [];
  for (const b of queryRegBlocks()) {
    const isCn = /\bCN\b/i.test(b.name) || /中国/i.test(b.name);
    if (wantCn !== isCn) continue;
    if (b.loc) out.push(path.join(b.loc, "resources"));
    if (b.iconDir) out.push(path.join(b.iconDir, "resources"));
  }
  return out;
}

function fastCandidates(product) {
  const exeLabel = EXE_LABELS[product];
  if (!exeLabel) return [];
  const local = localAppData();
  const out = [];
  for (const key of ENV_KEYS[product] || []) {
    const env = process.env[key];
    if (env) out.push(env);
  }
  out.push(path.join(local, "Programs", exeLabel, "resources"));
  out.push(path.join(local, exeLabel, "resources"));
  out.push(...launcherResources(exeLabel));
  return [...new Set(out.filter(Boolean))];
}

function registryCandidates(product) {
  const exeLabel = EXE_LABELS[product];
  if (!exeLabel) return [];
  return [...new Set(registryResources(exeLabel).filter(Boolean))];
}

function firstHit(product, list) {
  for (const c of list) {
    try {
      if (fs.existsSync(c) && fs.existsSync(path.join(c, "app.asar.unpacked"))) {
        cache.set(product, c);
        return c;
      }
    } catch {
      /* 单个候选异常不阻断后续 */
    }
  }
  return null;
}

function findResources(product) {
  const hit = cache.get(product);
  if (hit && fs.existsSync(hit)) return hit;
  return firstHit(product, fastCandidates(product)) ||
    firstHit(product, registryCandidates(product));
}

function runtimeInfoPath(product) {
  const res = findResources(product);
  return res ? path.join(res, "umid", "runtime-info.exe") : "";
}

/** 客户端可执行文件（系统 Node 缺失时以 ELECTRON_RUN_AS_NODE 当 Node 用） */
function clientExePath(product) {
  const res = findResources(product);
  if (!res) return "";
  const file = path.join(path.dirname(res), EXE_FILES[product] || "");
  try {
    return fs.existsSync(file) ? file : "";
  } catch {
    return "";
  }
}

function clearCache() {
  cache.clear();
  regBlocks = null;
}

module.exports = {
  EXE_LABELS,
  EXE_FILES,
  ENV_KEYS,
  findResources,
  runtimeInfoPath,
  clientExePath,
  clearCache,
  readLauncherIni,
  sameProductDir,
  queryRegBlocks,
  localAppData,
};
