/*
 * panel/components/format.js —— 展示层格式化（纯函数，无业务规则）
 *
 * 只做「数字与时间怎么显示」，不判断任何业务语义：状态判定留在后端，
 * 页面不在这里猜数据含义。
 */

/** 模型目录来源的人话标签（看板「目录来源」与模型清单页共用）。 */
export function catalogSourceLabel(source) {
  return ({
    live: "远端产品配置",
    remote: "远程同步（与官方桌面端同源）",
    cache: "桌面客户端缓存",
    endpoint: "接口兜底",
    static: "内置快照",
    unknown: "未知",
  }[source] || source || "未知");
}

/** 单个上限值的来源标签（/v1/models 的 limit_sources 注记）。 */
export function limitSourceLabel(source) {
  return ({
    remote: "官方目录",
    table: "models.dev 索引",
    cache: "本地缓存",
    probe: "实测钳制",
    default: "默认值",
    unknown: "未知",
  }[source] || source || "未知");
}

export function num(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return n.toLocaleString("zh-CN");
}

/** 大数缩写：1234567 → 1.2M / 12345 → 12.3K（Token 列惯用 K/M 口径）。 */
export function fmtK(value, fallback = "—") {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  const k = Math.round(n / 1000);
  if (Math.abs(k) >= 1000) return (k / 1000).toFixed(1) + "M";
  if (Math.abs(n) >= 1000) return k + "K";
  return String(n);
}

/** 万级缩写：12,345,678 → 1234.6 万（积分等人读数字）。 */
export function compact(value, fallback = "—") {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)} 万`;
  return n.toLocaleString("zh-CN");
}

export function pct(value, digits = 1, fallback = "—") {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return `${n.toFixed(digits)}%`;
}

export function ms(value, fallback = "—") {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  if (n >= 1000) return `${(n / 1000).toFixed(2)} 秒`;
  return `${Math.round(n)} ms`;
}

/** 秒数 → 「2 小时 5 分」这种能直接读的时长。 */
export function duration(seconds, fallback = "—") {
  const n = Math.round(Number(seconds));
  if (!Number.isFinite(n) || n <= 0) return fallback;
  if (n < 60) return `${n} 秒`;
  const minutes = Math.floor(n / 60);
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} 小时`;
  return `${Math.floor(hours / 24)} 天`;
}

/** Unix 秒 → 「x 秒 / 分钟 / 小时前」相对时间。 */
export function ago(unix, fallback = "") {
  if (!unix) return fallback;
  const s = Math.max(0, nowUnix() - Number(unix));
  if (!Number.isFinite(s)) return fallback;
  if (s < 60) return s + " 秒前";
  if (s < 3600) return Math.floor(s / 60) + " 分钟前";
  if (s < 86400) return Math.floor(s / 3600) + " 小时前";
  return Math.floor(s / 86400) + " 天前";
}

/** epoch 秒 / 毫秒 → 本地时间；0 与空值显示为空串。 */
export function time(unix, fallback = "") {
  if (!unix) return fallback;
  const n = Number(unix);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  const date = new Date(n > 1e11 ? n : n * 1000);
  if (Number.isNaN(date.getTime())) return fallback;
  const pad = (v) => String(v).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 「月-日 时:分:秒」紧凑格式（任务流水用）。 */
export function taskTime(unix, fallback = "—") {
  if (!unix) return fallback;
  const n = Number(unix);
  const date = new Date(n > 1e11 ? n : n * 1000);
  if (Number.isNaN(date.getTime())) return fallback;
  const pad = (v) => String(v).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function shortTime(unix, fallback = "") {
  const full = time(unix, fallback);
  return full ? full.slice(11) : full;
}

/** 已是字符串的时间戳（后端 iso / isoShort）原样返回，缺省给占位。 */
export function stamp(text, fallback = "—") {
  return text ? String(text) : fallback;
}

/** ISO 时间串 → 「月-日 时:分」（slice(5,16) 口径；T 换成空格更好读）。 */
export function isoShort(text, fallback = "—") {
  const s = String(text || "");
  return s ? s.replace("T", " ").slice(5, 16) : fallback;
}

/** ISO 时间串 → 完整到秒（slice(0,19) 口径；T 换成空格更好读）。 */
export function isoStamp(text, fallback = "—") {
  const s = String(text || "");
  return s ? s.replace("T", " ").slice(0, 19) : fallback;
}

/** 当前 Unix 秒（页面统一入口，不再各处手写 Date.now 换算）。 */
export function nowUnix() {
  return Math.floor(Date.now() / 1000);
}

export function truncate(text, limit = 12) {
  const value = String(text ?? "");
  if (value.length <= limit) return value;
  return value.slice(0, limit) + "…";
}
