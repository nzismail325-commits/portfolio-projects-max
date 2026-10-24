/*
 * panel/main.js —— 装配入口
 *
 * 创建应用、挂 Element Plus（中文语言包）、全局注册通用组件、挂载路由。
 * 页面是 .vue.js 模块（用 render 函数写法，浏览器直接跑，不需要打包器）。
 *
 * 渲染异常兜底：任一页面 render 抛错时，Vue 只会把该子树留空（表现为白屏），
 * 排查时看不到任何线索。这里统一把错误显示成一条错误横幅，并打回控制台，
 * 保证「页面坏了」永远是可读的状态而不是空白。
 */
import { createApp } from "/vendor/vue.mjs";
import App from "./App.js";
import { router } from "./router/index.js";
import { setUnauthorizedHandler, consumeSessionExpiryNotice } from "./api/client.js";
import { markLoggedOut } from "./store/index.js";
import { ElMessage } from "./components/ui.js";

const app = createApp(App);

app.use(window.ElementPlus, { locale: window.ElementPlusLocale || undefined });
app.config.globalProperties.$router = router;

// 面板会话失效：清状态、回登录页，并给一次性提示（B8）
setUnauthorizedHandler(() => {
  markLoggedOut();
  if (consumeSessionExpiryNotice()) {
    ElMessage.warning("会话已过期，请重新登录");
  }
  if (!location.hash.startsWith("#/login")) {
    location.hash = "/login";
  }
});

// 渲染错误横幅：接管 #app 上方的独立节点，不参与业务组件树
const errorBanner = document.createElement("div");
errorBanner.style.cssText =
  "position:fixed;left:0;right:0;top:0;z-index:9999;display:none;" +
  "padding:10px 16px;background:#fee2e2;color:#991b1b;font:13px/1.5 " +
  "'Segoe UI','Microsoft YaHei',sans-serif;white-space:pre-wrap;";
document.body.appendChild(errorBanner);

function showFatal(message) {
  errorBanner.textContent = `页面渲染出错：${message}（打开浏览器控制台可看完整堆栈）`;
  errorBanner.style.display = "block";
}

app.config.errorHandler = (err, instance, info) => {
  const detail = err && err.stack ? err.stack : String(err);
  console.error("[panel] render error:", detail, "\nhook:", info);
  showFatal((err && err.message) || String(err));
};

app.mount("#app");
