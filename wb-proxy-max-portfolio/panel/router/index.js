/*
 * panel/router/index.js —— 页面路由表与登录守卫
 *
 * 路由与页面一一对应；每个页面只服务自己声明的渠道范围。未登录一律回 Login，
 * 登录后回跳原目标。路由实现见 hash.js（不依赖 vue-router）。
 */
import { createRouter } from "./hash.js";
import { rawState, loadBootstrap } from "../store/index.js";
import { setToken, consumeSessionExpiryNotice } from "../api/client.js";
import { ElMessage } from "../components/ui.js";

import Login from "../views/Login.vue.js";
import Dashboard from "../views/Dashboard.vue.js";
import Accounts from "../views/Accounts.vue.js";
import Tasks from "../views/Tasks.vue.js";
import Logs from "../views/Logs.vue.js";
import Models from "../views/Models.vue.js";
import Theme from "../views/Theme.vue.js";
import Settings from "../views/Settings.vue.js";

const routes = [
  { path: "/", redirect: "/accounts" },
  { path: "/login", name: "login", component: Login, meta: { public: true, title: "登录" } },
  { path: "/dashboard", name: "dashboard", component: Dashboard, meta: { title: "数据看板" } },
  { path: "/accounts", name: "accounts", component: Accounts, meta: { title: "账号治理" } },
  { path: "/tasks", name: "tasks", component: Tasks, meta: { title: "任务与福利" } },
  { path: "/logs", name: "logs", component: Logs, meta: { title: "日志与流水" } },
  { path: "/models", name: "models", component: Models, meta: { title: "模型清单" } },
  { path: "/theme", name: "theme", component: Theme, meta: { title: "主题外观" } },
  { path: "/settings", name: "settings", component: Settings, meta: { title: "设置" } },
];

export const router = createRouter({ routes });

router.beforeEach(async (to) => {
  if (!rawState().ready) {
    await loadBootstrap();
  }
  if (!to.meta?.public && !rawState().authenticated) {
    // B8：无有效会话访问业务页——清掉可能残留的本地令牌、整页回登录，
    // 并给一次性提示（应用启动直链业务页 / 会话过期都走这里）
    setToken("");
    if (consumeSessionExpiryNotice()) {
      ElMessage.warning("会话已过期，请重新登录");
    }
    location.hash = "/login";
    return false;
  }
  if (to.name === "login" && rawState().authenticated) {
    location.hash = "/accounts";
    return false;
  }
  return true;
});

// B8：守卫注册完成后再发起首次导航（根因修复：初始导航不再绕过守卫）
router.start();

export default router;
