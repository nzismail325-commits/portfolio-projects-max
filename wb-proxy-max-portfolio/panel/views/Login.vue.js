/*
 * panel/views/Login.vue.js —— 面板密码登录
 *
 * 只做一件事：提交密码、拿会话令牌、加载引导数据、跳看板。登录失败时把
 * 后端的人话错误原样显示；默认密码提示由 /panel/status 下发。
 */
import { h, ref, onMounted } from "/vendor/vue.mjs";
import { panelApi } from "../api/panel.js";
import { setToken, resetSessionExpiryNotice } from "../api/client.js";
import { loadBootstrap, markAuthenticated, useStore } from "../store/index.js";
import { BRAND_SVG } from "../components/icons.js";

export default {
  name: "LoginView",
  setup() {
    const store = useStore();
    const password = ref("");
    const busy = ref(false);
    const error = ref("");

    async function submit() {
      if (!password.value || busy.value) return;
      busy.value = true;
      error.value = "";
      try {
        const result = await panelApi.login(password.value);
        setToken(result.token || "");
        resetSessionExpiryNotice(); // B8：新会话建立，复位过期提示节流
        markAuthenticated(true);
        await loadBootstrap(true);
        window.location.hash = "/accounts";
      } catch (err) {
        error.value = err.message || "登录失败";
      } finally {
        busy.value = false;
      }
    }

    onMounted(() => {
      // 未登录时 store 可能还没拉过状态；登录页也需要默认密码提示
      if (!store.ready) loadBootstrap();
    });

    return { store, password, busy, error, submit };
  },
  render() {
    const store = this.store;
    const self = this;
    return h("div", { class: "gate" }, [
      h("form", {
        class: "gate-card",
        onSubmit: (event) => {
          event.preventDefault();
          self.submit();
        },
      }, [
        h("div", { class: "gate-brand" }, [
          h("div", { class: "brand-mark", innerHTML: BRAND_SVG }),
          h("div", { class: "gt" }, "Gateway 反代控制台"),
          h("div", { class: "gs" }, "请输入面板访问密码以继续"),
        ]),
        // B5：视觉隐藏的输入框标签（可读屏可达）
        h("label", { class: "sr-only", for: "gate-password" }, "面板密码"),
        h("input", {
          id: "gate-password",
          type: "password",
          class: "gate-input",
          placeholder: "面板密码",
          autocomplete: "current-password",
          disabled: self.busy,
          value: self.password,
          onInput: (event) => { self.password = event.target.value; },
          onKeyup: (event) => {
            if (event.key === "Enter") self.submit();
          },
        }),
        h("div", { class: "gate-msg", role: "status", "aria-live": "polite" },
          self.error || ""),
        h("button", {
          type: "submit",
          class: "gate-go",
          disabled: self.busy || !self.password,
        }, self.busy ? "验证中…" : "进入面板"),
        store.passwordIsDefault
          ? h("div", { class: "gate-hint" },
              "当前仍在使用默认密码 admin，登录后请到「设置」修改。")
          : null,
      ]),
      // B5：底部居中等宽版本徽标
      h("div", { class: "gate-ver" },
        `GATEWAY CONSOLE · v${store.version || "1.0.0-max"}`),
    ]);
  },
};
