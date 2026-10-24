/*
 * panel/api/client.js —— 请求封装（前端唯一出口）
 *
 * 所有接口调用都必须经过这里：统一带上面板会话令牌、统一处理 401 跳登录、
 * 统一把后端返回的错误结构翻成人话。views 不直接 fetch。
 */
const TOKEN_KEY = "wbmax.panelToken";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(status, message, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

/** 401 时由 App 注册的回调（跳登录页）。 */
let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn || (() => {});
}

/* B8：会话过期提示的一次性节流——同一页面生命周期只提示一次，
   登录成功 / 主动登出后复位，之后的会话失效要重新提示。 */
let expiryNotified = false;
export function consumeSessionExpiryNotice() {
  if (expiryNotified) return false;
  expiryNotified = true;
  return true;
}
export function resetSessionExpiryNotice() {
  expiryNotified = false;
}

async function request(method, path, body) {
  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) headers["X-Panel-Token"] = token;
  let payload;
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch (err) {
    throw new ApiError(0, "网络不可达：网关是否在运行？", err);
  }
  let data = null;
  const type = response.headers.get("Content-Type") || "";
  if (type.includes("application/json")) {
    try { data = await response.json(); } catch (_) { data = null; }
  }
  if (response.status === 401) {
    setToken("");
    onUnauthorized();
    throw new ApiError(401, "登录已失效，请重新登录", data);
  }
  if (!response.ok) {
    const message = data?.error?.message || `请求失败（HTTP ${response.status}）`;
    throw new ApiError(response.status, message, data);
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  del: (path) => request("DELETE", path),
};

/** 查询串构造：跳过空值，数组用逗号连接（后端按第一个值取）。 */
export function qs(params) {
  const parts = [];
  for (const [key, value] of Object.entries(params || {})) {
    if (value === undefined || value === null || value === "") continue;
    const text = Array.isArray(value) ? value.join(",") : String(value);
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(text)}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}
