/*
 * panel/store/index.js —— 全局共享状态（登录态、主题、渠道清单、当前出口）
 *
 * 跨页面共享的可变状态只进这里：页面之间不互相 import 传状态；页面操作只
 * 作用于自己的渠道范围，联动结果由数据刷新自然体现（不做事件广播）。
 *
 * 主题（外观）是全面板唯一的本地偏好，与二开原版一致：
 *   default-dark  默认 · 深色（经典驾驶舱）
 *   default-light 默认 · 浅色（明亮办公风）
 *   midnight      午夜书房（画作背景 + 磨砂玻璃）
 *   sky           云海霞光（画作背景 + 磨砂玻璃）
 * 存 localStorage，由 App 外壳在挂载时应用到 <html data-theme>。
 */
import { reactive, readonly } from "/vendor/vue.mjs";
import { channelsApi } from "../api/channels.js";
import { panelApi } from "../api/panel.js";
import { prefersReducedMotion } from "../components/ui.js";

const THEME_KEY = "wbmax.panelTheme";
const REALM_KEY = "wbmax.panelRealm";
const THEME_IDS = ["default-dark", "default-light", "midnight", "sky"];
const THEME_BARS = {
  "default-dark": "#070b13",
  "default-light": "#eef1f7",
  midnight: "#13101c",
  sky: "#0b1220",
};

const state = reactive({
  ready: false,
  authenticated: false,
  passwordIsDefault: false,
  version: "",
  channels: [],
  realms: [],
  currentRealm: "",
  schedulerTasks: [],
  health: null,
  lastError: "",
  /** 出口偏好：未选择时为 ""（各页用自己渠道的第一个出口）。 */
  realm: "",
  /** 主题 id，见 THEME_IDS。 */
  theme: "default-dark",
});

try {
  const saved = localStorage.getItem(THEME_KEY);
  if (THEME_IDS.includes(saved)) state.theme = saved;
  // 出口偏好与主题一样只存本机（T-09）：刷新/重开浏览器不再回到默认出口
  const savedRealm = localStorage.getItem(REALM_KEY);
  if (savedRealm) state.realm = savedRealm;
} catch (err) { /* 隐私模式等场景读不到就算了 */ }

let loaded = false;

export function useStore() {
  return readonly(state);
}

export function rawState() {
  return state;
}

/** 把当前主题应用到 <html data-theme>（App 挂载与切换时调用）。 */
export function applyTheme() {
  document.documentElement.setAttribute("data-theme", state.theme);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", THEME_BARS[state.theme] || "#070b13");
}

export function setTheme(id) {
  if (!THEME_IDS.includes(id)) return;
  // B6：主题切换 250ms 透明度交叉淡入（画作主题放宽到 400ms，见 styles.css）；
  // 系统开启减弱动态效果时不加动画类，切换即时生效
  const body = document.body;
  if (!prefersReducedMotion() && !body.classList.contains("theme-fading")) {
    body.classList.add("theme-fading");
    window.setTimeout(() => body.classList.remove("theme-fading"), 420);
  }
  state.theme = id;
  try { localStorage.setItem(THEME_KEY, id); } catch (err) { /* 同上 */ }
  applyTheme();
}

/** 出口偏好（顶栏切换写入）：内存态 + localStorage 持久化。 */
export function setRealm(id) {
  state.realm = id;
  try { localStorage.setItem(REALM_KEY, id); } catch (err) { /* 同上 */ }
}

const PREFS_KEY = "wbmax.panelPrefs";

/**
 * 区间筛选等页面偏好（T-20）：一个 JSON blob 存本机，与主题/出口同一待遇。
 * 读不到或值不在允许名单时回退默认，blob 损坏不影响页面加载。
 */
export function loadPref(key, fallback, allowed = null) {
  try {
    const value = (JSON.parse(localStorage.getItem(PREFS_KEY) || "{}"))[key];
    if (allowed ? allowed.includes(value) : value != null && value !== "") return value;
  } catch (err) { /* 损坏即回退默认 */ }
  return fallback;
}

export function savePref(key, value) {
  try {
    const blob = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    blob[key] = value;
    localStorage.setItem(PREFS_KEY, JSON.stringify(blob));
  } catch (err) { /* 同上 */ }
}

/** 首次进入与登录成功后加载渠道清单（前端所有页签/按钮的唯一依据）。 */
export async function loadBootstrap(force = false) {
  if (loaded && !force) return state;
  try {
    const status = await panelApi.status();
    state.authenticated = Boolean(status.authenticated);
    state.passwordIsDefault = Boolean(status.panel_password_is_default);
    state.version = status.version || "";
    state.currentRealm = status.default_realm || "";
    if (state.authenticated) {
      const data = await channelsApi.load();
      state.channels = data.channels;
      state.realms = data.realms;
      state.schedulerTasks = data.schedulerTasks;
      state.currentRealm = data.currentRealm || state.currentRealm;
      if (!state.realm || !state.realms.some((item) => item.id === state.realm)) {
        state.realm = state.currentRealm || state.realms[0]?.id || "";
      }
    }
    state.ready = true;
    loaded = true;
    state.lastError = "";
  } catch (err) {
    state.lastError = err.message || String(err);
    state.ready = true;
  }
  return state;
}

export function markAuthenticated(value) {
  state.authenticated = Boolean(value);
  loaded = false;
}

/**
 * 页面级等待：确保 bootstrap 触发过且渠道清单已就绪。
 *
 * App 外壳与页面是并行挂载的，页面不能假设 store.channels 已经有值——直接
 * 按空渠道渲染会出现「首次进入空白、刷新才有内容」。所有按渠道渲染的页面
 * 在 onMounted 里先 await 它，再决定渲染什么。
 */
export async function ensureBootstrap() {
  if (!state.ready || !loaded) {
    await loadBootstrap();
  }
  return state;
}

export function markLoggedOut() {
  state.authenticated = false;
  state.channels = [];
  state.realms = [];
  state.schedulerTasks = [];
  loaded = false;
}

/** 刷新健康快照（侧栏与看板共用）。 */
export async function refreshHealth() {
  try {
    state.health = await panelApi.health();
  } catch (err) {
    state.health = null;
  }
  return state.health;
}

/** 找渠道对象（页面按 id 取，不做猜测）。 */
export function channelById(id) {
  return state.channels.find((item) => item.id === id) || null;
}

/** 找渠道下某出口的元信息（badge / domain 等，找不到返回 null）。 */
export function realmMeta(realmId) {
  for (const channel of state.channels) {
    for (const realm of channel.realms || []) {
      if (realm.id === realmId) return realm;
    }
  }
  return state.realms.find((item) => item.id === realmId) || null;
}

/**
 * 「偏好命中」的单一实现（内部）：全局出口偏好命中该出口列表时用它；
 * 偏好指向其他渠道的出口时返回 null——渠道块整体不渲染（§2.2：切到哪个
 * 出口就只显示哪个出口，宁可整块留白，不做跨渠道回落拼数据）；偏好为空
 * （从未选择过）时回落该渠道第一个出口。
 */
function preferredRealm(realms) {
  const preferred = state.realm;
  if (!preferred) {
    return realms[0] || null;
  }
  return realms.find((item) => item.id === preferred) || null;
}

/**
 * 渠道当前出口对象（全站唯一实现，页面不得各写各的）：
 * 跟随顶栏切换的全局偏好（state.realm），偏好未命中回落到该渠道第一个出口。
 * 需要出口 id 时取返回值的 .id。
 */
export function currentRealm(channel) {
  return preferredRealm(channelsApi.realmsOf(channel));
}

/** 无渠道上下文页面的当前出口 id：同样跟随全局偏好，未选偏好时回落全局第一个出口。 */
export function currentRealmId() {
  if (state.realm) return state.realm;
  return preferredRealm(state.realms)?.id || "";
}
