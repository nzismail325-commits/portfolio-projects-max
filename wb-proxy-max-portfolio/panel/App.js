/*
 * panel/App.js —— 应用外壳（本地自研，上游无对应）
 *
 * 结构：登录页独占整屏；登录后是「侧栏导航 + 顶栏 + 当前路由组件」。
 * 顶栏只承载出口切换（选项来自后端注册表下发的全部 realm）；
 * 运行状态落在侧栏底部，退出登录作为设置之后的导航项。
 * 主题外观只在「主题外观」页切换——顶栏不放明暗快切，避免同一设置两处
 * 入口、行为还不一致（快切会把画作主题静默打回默认）。
 *
 * 路由组件由 router.getRoutes() 按当前路由名解析——router/hash.js 只维护
 * 路由状态，不提供 RouterView 组件。
 */
import { h, computed, onMounted, onUnmounted, watch } from "/vendor/vue.mjs";
import { router } from "./router/index.js";
import {
  useStore, loadBootstrap, refreshHealth, markLoggedOut, applyTheme,
  setRealm, realmMeta,
} from "./store/index.js";
import { panelApi } from "./api/panel.js";
import { setToken, getToken, resetSessionExpiryNotice } from "./api/client.js";
import { ElMessage } from "./components/ui.js";
import { BRAND_SVG, ico } from "./components/icons.js";
import { confirmAction } from "./components/kit.js";
import { createPoller } from "./composables/poll.js";
import Seg from "./components/seg.js";

const NAV = [
  { path: "/accounts", label: "账号治理", icon: "pool" },
  { path: "/models", label: "模型清单", icon: "layers" },
  { path: "/tasks", label: "任务与福利", icon: "tasks" },
  { path: "/dashboard", label: "数据看板", icon: "chart" },
  { path: "/logs", label: "日志与流水", icon: "logs" },
  { path: "/theme", label: "主题外观", icon: "palette" },
  { path: "/settings", label: "设置", icon: "settings" },
];

const HEALTH_INTERVAL_MS = 30000;

/** 出口页签只属于跟出口有关的页面；其余页面点它本就无效，直接不渲染（T-04）。 */
const REALM_AWARE_ROUTES = new Set(["dashboard", "accounts", "tasks", "models"]);

/** 侧栏导航项图标：16px 线性图标（尺寸与 .nav-item svg 规则对齐）。 */
function navIcon(name) {
  return h("span", { class: "ico", innerHTML: ico(name),
                     style: "display:inline-flex;width:16px;height:16px" });
}

/* KPI 卡鼠标跟随高光：pointermove 委托只写 --mx/--my 两个 CSS 变量（纯装饰）。
   数据表卡与设置卡面积大，不再参与，避免无谓重绘。 */
function onCardPointerMove(event) {
  const target = event.target && event.target.closest
    ? event.target.closest(".card.kpi") : null;
  if (!target) return;
  const rect = target.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  target.style.setProperty("--mx", ((event.clientX - rect.left) / rect.width * 100).toFixed(1) + "%");
  target.style.setProperty("--my", ((event.clientY - rect.top) / rect.height * 100).toFixed(1) + "%");
}

export default {
  name: "App",
  setup() {
    const store = useStore();
    const route = router.state;
    const isLogin = computed(() => route.name === "login");
    const online = computed(() => Boolean(store.health && store.health.ok));
    const navItems = computed(() => (store.authenticated ? NAV : []));

    let healthTimer = null;
    onMounted(async () => {
      applyTheme();
      document.addEventListener("pointermove", onCardPointerMove, { passive: true });
      // B8：启动兜底——本地无令牌且不在登录页时立即回登录（守卫之外的最后一道防线）
      if (!getToken() && route.name !== "login") {
        window.location.hash = "/login";
      }
      await loadBootstrap();
      if (store.authenticated) {
        refreshHealth();
        // guard 挡掉未登录轮次（登出后定时器随外壳卸载停止）
        healthTimer = createPoller(() => refreshHealth(), HEALTH_INTERVAL_MS,
          { guard: () => store.authenticated });
        healthTimer.start();
      }
    });
    onUnmounted(() => {
      if (healthTimer) healthTimer.stop();
      document.removeEventListener("pointermove", onCardPointerMove);
    });
    watch(() => store.authenticated, (value) => {
      if (value) refreshHealth();
    });

    async function logout() {
      try {
        await panelApi.logout();
      } catch (err) {
        // 会话可能已失效：本地状态照样清干净
      }
      setToken("");
      resetSessionExpiryNotice(); // B8：主动登出后复位，下次会话失效要重新提示
      markLoggedOut();
      ElMessage.success("已退出登录");
      window.location.hash = "/login";
    }

    /** B7：退出前轻确认——回车确认、Esc 取消；确认后走原有 logout() 流程。 */
    async function confirmLogout() {
      const ok = await confirmAction("确定退出当前会话？", "退出登录", {
        confirmButtonText: "退出",
        cancelButtonText: "取消",
      });
      if (!ok) return; // 取消 / Esc：什么都不做
      await logout();
    }

    return { store, route, isLogin, online, navItems, confirmLogout };
  },
  computed: {
    /** 当前路由对应的页面组件（未命中时什么都不渲染）。 */
    currentView() {
      const name = this.route.name;
      if (!name) return null;
      const found = (router.getRoutes() || []).find((item) => item.name === name);
      return found?.component || null;
    },
    realmOptions() {
      // 与出口无关的页面不渲染页签（REALM_AWARE_ROUTES 之外一概隐藏）
      if (!REALM_AWARE_ROUTES.has(this.route.name)) return [];
      return (this.store.realms || []).map((item) => ({
        id: item.id,
        label: item.badge || item.label || item.id,
        title: item.domain || "",
      }));
    },
    /** B1：顶栏左侧的运行状态（30s 随健康快照刷新）。 */
    statusLabel() {
      return this.online ? "运行中" : "服务异常";
    },
    /** 可用账号口径跟随当前出口：顶栏切到哪个出口，胶囊就报哪个出口的
        可用/总数，与账号治理等单出口页面的数字对得上；未选出口或快照缺
        分出口数据时回退全池口径，快照整个缺失（请求失败）时显示 —。 */
    realmHealth() {
      const health = this.store.health;
      if (!health) return { total: null, ready: null };
      const byRealm = health.by_realm || {};
      const realm = this.store.realm;
      if (realm && Object.keys(byRealm).length > 0) {
        // 该出口没有账号时记 0（不是回退全池——那正是要对上的那个错误口径）
        const scoped = byRealm[realm] || { accounts: 0, ready: 0 };
        return { total: Number(scoped.accounts) || 0, ready: Number(scoped.ready) || 0 };
      }
      return {
        total: Number(health.accounts) || 0,
        ready: Number(health.accounts_ready) || 0,
      };
    },
    statusTitle() {
      const meta = realmMeta(this.store.realm);
      const name = (meta && (meta.badge || meta.label)) || "";
      const base = "服务状态与可用账号（每 30 秒刷新）";
      return name ? `当前出口：${name} · ${base}` : base;
    },
    accountsPct() {
      const total = Number(this.realmHealth.total) || 0;
      const ready = Number(this.realmHealth.ready) || 0;
      return total > 0 ? Math.max(0, Math.min(100, Math.round(ready / total * 100))) : 0;
    },
    accountsTone() {
      const total = Number(this.realmHealth.total) || 0;
      if (!total) return "off";
      const pct = this.accountsPct;
      return pct >= 100 ? "ok" : pct > 0 ? "warn" : "bad";
    },
  },
  methods: {
    pickRealm(id) {
      // 只写全局偏好；各页面读 store.realm 决定自己渠道用哪个出口，
      // 数据刷新由页面自己处理（不做跨页事件广播）。
      setRealm(id);
    },
  },
  render() {
    const page = this.currentView ? h(this.currentView) : null;

    if (this.isLogin) {
      return h("div", { class: "login-shell" }, page);
    }

    return h("div", { class: "shell" }, [
      // 全宽全局顶栏：品牌（与侧栏同宽）｜居中出口切换。
      // 中间切换列按内容自适应、左右两列等宽，出口切换相对整条顶栏真居中；
      // 运行状态在侧栏底部，顶栏只保留导航与出口切换。
      h("header", { class: "topbar" }, [
        h("div", { class: "tb-brand" }, [
          h("div", { class: "brand-mark", innerHTML: BRAND_SVG }),
          h("div", { class: "tb-brand-text" }, [
            h("div", { class: "brand-name" }, "Gateway"),
            h("div", { class: "brand-sub" }, "反代控制台"),
          ]),
        ]),
        this.realmOptions.length > 1
          ? h("div", { class: "tb-center" }, [
              h(Seg, {
                options: this.realmOptions,
                modelValue: this.store.realm,
                "onUpdate:modelValue": (id) => this.pickRealm(id),
                ariaLabel: "出口切换",
              }),
            ])
          : null,
      ]),
      h("div", { class: "shell-body" }, [
        h("aside", { class: "side" }, [
          h("nav", { class: "side-nav", "aria-label": "主导航" }, [
            ...this.navItems.map((item) =>
              h("button", {
                key: item.path,
                type: "button",
                class: ["nav-item", this.route.path === item.path ? "active" : ""],
                onClick: () => { window.location.hash = item.path; },
              }, [
                navIcon(item.icon),
                h("span", null, item.label),
              ])),
            // 退出登录与导航项同一视觉语言，紧接「设置」之后；
            // 分隔线只做会话操作与页面导航的轻分组。
            h("span", { class: "nav-sep", "aria-hidden": "true" }),
            h("button", {
              type: "button",
              class: "nav-item nav-logout",
              title: "退出登录",
              onClick: () => this.confirmLogout(),
            }, [
              navIcon("logout"),
              h("span", null, "退出登录"),
            ]),
          ]),
          // 运行状态沉到侧栏底部：服务健康回到常驻导航区，
          // 账号可用量跟随当前出口。
          h("div", { class: "side-health", title: this.statusTitle }, [
            h("div", { class: "sh-top" }, [
              h("span", { class: ["dot", this.online ? "" : "err"], "aria-hidden": "true" }),
              h("span", { class: "sh-state" }, this.statusLabel),
              h("span", { class: "sh-meta" }, "可用账号"),
              h("span", { class: "sh-count" }, [
                String(this.realmHealth.ready ?? "—"),
                h("span", { class: "sh-total" }, `/${this.realmHealth.total ?? "—"}`),
              ]),
            ]),
            h("span", {
              class: ["sh-bar",
                this.accountsTone === "warn" ? "warn" : this.accountsTone === "bad" ? "bad" : ""]
                .filter(Boolean).join(" "),
            }, h("i", { style: { width: `${this.accountsPct}%` } })),
          ]),
        ]),
        h("div", { class: "main" }, [
          h("main", { class: "content" }, page),
          h("footer", { class: "content-foot" }, [
            h("span", null, "Gateway 反代控制台"),
            h("span", { class: "muted" }, `v${this.store.version || "—"}`),
          ]),
        ]),
      ]),
    ]);
  },
};
