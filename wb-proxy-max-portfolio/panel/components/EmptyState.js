/*
 * panel/components/EmptyState.js —— 空态（本地自研，上游无对应）
 *
 * 只用于「页面本身有渠道、但暂时没有数据」的说明；如果页面一个渠道都没
 * 注册，应当整块不渲染，而不是显示这里的占位（§2.2：不留死入口）。
 */
import { h } from "/vendor/vue.mjs";
import { ico } from "./icons.js";

export default {
  name: "EmptyState",
  props: {
    text: { type: String, default: "暂无数据" },
    hint: { type: String, default: "" },
    icon: { type: String, default: "layers" },
    compact: { type: Boolean, default: false },
  },
  render() {
    return h("div", { class: ["empty", this.compact ? "compact" : ""] }, [
      h("span", { class: "empty-ico", innerHTML: ico(this.icon) }),
      h("div", null, this.text),
      this.hint ? h("div", { class: "muted" }, this.hint) : null,
    ]);
  },
};
