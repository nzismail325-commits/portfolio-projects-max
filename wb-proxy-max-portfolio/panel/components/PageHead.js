/*
 * panel/components/PageHead.js —— 页头（图标 + 标题 + 上下文徽标 + 描述 + 右侧操作区）
 */
import { h } from "/vendor/vue.mjs";
import { ico } from "./icons.js";

export default {
  name: "PageHead",
  props: {
    title: { type: String, required: true },
    desc: { type: String, default: "" },
    icon: { type: String, default: "" },
    meta: { type: Array, default: () => [] },
  },
  render() {
    return h("div", { class: "page-head" }, [
      h("div", { class: "page-head-main" }, [
        this.icon
          ? h("span", { class: "page-head-ico", innerHTML: ico(this.icon), "aria-hidden": "true" })
          : null,
        h("div", { class: "page-head-body" }, [
          h("div", { class: "page-head-title" }, [
            h("h1", null, this.title),
            this.meta.length ? h("div", { class: "page-head-meta" }, this.meta) : null,
          ]),
          this.desc ? h("span", { class: "desc" }, this.desc) : null,
        ]),
      ]),
      h("div", { class: "right" }, this.$slots.actions ? this.$slots.actions() : null),
    ]);
  },
};
