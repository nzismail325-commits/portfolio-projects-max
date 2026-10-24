/*
 * panel/components/MetricCard.js —— KPI 指标卡（本地自研，上游无对应）
 *
 * 一个标签 + 一个大数值 + 一行脚注 + 3px 语义色底线锚点（B3）；tone 决定图标、
 * 数值与底线的着色（accent / accent2 / ok / warn / bad，空串为中性）。
 * anchor 可显式指定底线颜色（如中性卡希望绿色锚点）；数值格式化由调用方处理。
 *
 * B6 count-up：数值变化时 400ms rAF 缓动到新值（保留前后缀与原格式的小数位）；
 * 任一侧解析不出数字（如「—」）或系统开启减弱动态效果时直接跳变。
 */
import { h, ref, watch, onUnmounted } from "/vendor/vue.mjs";
import { ico } from "./icons.js";
import { prefersReducedMotion } from "./ui.js";

const DURATION_MS = 400;

/** 拆出字符串里第一个数字（容忍千分位），连同前后缀与小数位。 */
function splitValue(text) {
  const raw = String(text ?? "");
  const m = raw.match(/-?\d[\d,]*(\.\d+)?/);
  if (!m) return null;
  const n = Number(m[0].replace(/,/g, ""));
  if (!Number.isFinite(n)) return null;
  const decimals = m[0].includes(".") ? m[0].split(".")[1].length : 0;
  return { n, decimals, prefix: raw.slice(0, m.index), suffix: raw.slice(m.index + m[0].length) };
}

function format(n, decimals) {
  return n.toLocaleString("zh-CN", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
}

export default {
  name: "MetricCard",
  props: {
    label: { type: String, required: true },
    value: { type: [String, Number], default: "—" },
    unit: { type: String, default: "" },
    foot: { type: String, default: "" },
    icon: { type: String, default: "" },
    tone: { type: String, default: "" },
    anchor: { type: String, default: "" },
  },
  setup(props) {
    const display = ref(String(props.value ?? "—"));
    let raf = 0;

    watch(() => props.value, (next, prev) => {
      const from = splitValue(prev);
      const to = splitValue(next);
      cancelAnimationFrame(raf);
      if (!from || !to || from.n === to.n || prefersReducedMotion()) {
        display.value = String(next ?? "—");
        return;
      }
      const start = performance.now();
      const step = (now) => {
        const t = Math.min(1, (now - start) / DURATION_MS);
        const eased = 1 - Math.pow(1 - t, 3); // ease-out cubic
        display.value = to.prefix + format(from.n + (to.n - from.n) * eased, to.decimals) + to.suffix;
        if (t < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    });
    onUnmounted(() => cancelAnimationFrame(raf));

    return { display };
  },
  render() {
    return h("div", { class: ["card", "kpi", this.tone ? "tone-" + this.tone : ""] }, [
      h("div", { class: "k" }, [
        h("span", null, this.label),
        this.icon
          ? h("span", { class: "k-ico push", innerHTML: ico(this.icon),
                        style: "margin-left:auto" })
          : null,
      ]),
      h("div", { class: "v" }, [
        String(this.display ?? "—"),
        this.unit ? h("span", { class: "unit" }, this.unit) : null,
      ]),
      this.foot ? h("div", { class: "s", innerHTML: this.foot }) : null,
      h("div", { class: "kpi-anchor", style: this.anchor ? `background:${this.anchor}` : null }),
    ]);
  },
};
