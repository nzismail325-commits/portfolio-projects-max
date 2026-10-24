/*
 * panel/components/StateBadge.js —— 状态徽标（本地自研，上游无对应）
 *
 * 页面只传「后端已判定的状态词」，这里决定配色与中文文案；
 * 不认识的词原样显示、走中性配色，不猜业务含义。
 * B6：状态词变化时打一次 150ms 的 soft 色脉冲（样式见 styles.css .badge.pulse），
 * 系统开启减弱动态效果时静默。
 */
import { h, ref, watch, onUnmounted } from "/vendor/vue.mjs";
import { prefersReducedMotion } from "./ui.js";

const LABELS = {
  ready: "可用",
  ok: "成功",
  enabled: "已启用",
  disabled: "已停用",
  expired: "已过期",
  cooling: "冷却中",
  parked: "已停车",
  degraded: "降级中",
  error: "失败",
  warn: "警告",
  failed: "失败",
  skip: "跳过",
  credit: "积分",
  running: "进行中",
  finished: "已完成",
  pending: "等待中",
  idle: "空闲",
  claimed: "已领取",
  accepted: "已接取",
  not_accepted: "未接取",
  unknown: "未知",
};

const TONES = {
  ok: ["ready", "ok", "enabled", "finished", "claimed"],
  warn: ["warn", "cooling", "degraded", "running", "pending", "accepted"],
  bad: ["error", "failed", "expired", "parked"],
  info: ["info", "idle"],
  s: ["credit"],
  off: ["skip", "not_accepted", "disabled"],
};

function toneOf(status) {
  const key = String(status || "").toLowerCase();
  for (const [tone, values] of Object.entries(TONES)) {
    if (values.includes(key)) return tone;
  }
  return "";
}

const PULSE_MS = 220; /* 动画 .15s + 一点余量 */

export default {
  name: "StateBadge",
  props: {
    status: { type: String, default: "" },
    label: { type: String, default: "" },
  },
  setup(props) {
    const pulsing = ref(false);
    let timer = 0;
    let raf = 0;

    watch(() => `${props.status}|${props.label}`, () => {
      if (prefersReducedMotion()) return;
      // 先摘掉类再下一帧加回：连续变化时也能重启动画
      pulsing.value = false;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        pulsing.value = true;
        clearTimeout(timer);
        timer = setTimeout(() => { pulsing.value = false; }, PULSE_MS);
      });
    });
    onUnmounted(() => { clearTimeout(timer); cancelAnimationFrame(raf); });

    return { pulsing };
  },
  computed: {
    text() {
      if (this.label) return this.label;
      const key = String(this.status || "");
      return LABELS[key.toLowerCase()] || key || "—";
    },
    tone() {
      return toneOf(this.status);
    },
  },
  render() {
    return h("span", { class: ["badge", this.tone, this.pulsing ? "pulse" : ""] }, this.text);
  },
};
