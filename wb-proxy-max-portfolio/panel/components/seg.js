/*
 * panel/components/seg.js —— 滑动页签（本地自研，上游无对应）
 *
 * 出口切换、区间选择共用的分段控件：选中项由滑动指示条跟随（CSS 过渡），
 * 位置由父级在挂载/更新后调 position() 重算（布局受字体与内容宽度影响）。
 */
import { h, nextTick } from "/vendor/vue.mjs";

/** 重算某容器内滑动指示条的位置（面板任意 .seg 都可复用）。 */
export function positionSeg(container) {
  if (!container) return;
  const ind = container.querySelector(":scope > .seg-ind");
  const btn = container.querySelector(":scope > .seg-btn.active");
  if (!ind || !btn) return;
  ind.style.width = btn.offsetWidth + "px";
  ind.style.transform = "translateX(" + btn.offsetLeft + "px)";
}

export default {
  name: "Seg",
  props: {
    options: { type: Array, required: true },   // [{id, label, disabled?, title?}]
    modelValue: { type: String, default: "" },
    ariaLabel: { type: String, default: "" },   // 分组用途的朗读标签（无则不加）
  },
  emits: ["update:modelValue"],
  watch: { modelValue: { handler() { this.reposition(); } } },
  mounted() { this.reposition(); },
  updated() { this.reposition(); },
  methods: {
    reposition() {
      nextTick(() => positionSeg(this.$el));
    },
  },
  render() {
    const buttons = this.options.map((opt) =>
      h("button", {
        key: opt.id,
        type: "button",
        class: ["seg-btn", this.modelValue === opt.id ? "active" : ""],
        disabled: Boolean(opt.disabled),
        title: opt.title || "",
        onClick: () => this.$emit("update:modelValue", opt.id),
      }, opt.label));
    return h("div", { class: "seg", role: "group", "aria-label": this.ariaLabel || undefined }, [
      h("span", { class: "seg-ind", "aria-hidden": "true" }),
      ...buttons,
    ]);
  },
};
