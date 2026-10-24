/*
 * panel/components/ico.js —— 图标渲染组件
 *
 * 模板/render 里 <ico name="pool"/> 或 h(Ico, {name:"pool"})，
 * 内容由 icons.js 的线性图标库提供（v-html 注入，字符串为库内常量）。
 */
import { h } from "/vendor/vue.mjs";
import { ico } from "./icons.js";

export default {
  name: "Ico",
  props: {
    name: { type: String, required: true },
  },
  render() {
    return h("span", { class: "ico", innerHTML: ico(this.name) });
  },
};
