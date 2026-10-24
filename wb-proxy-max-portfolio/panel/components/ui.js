/*
 * panel/components/ui.js —— 用 render 函数写页面时的 Element Plus 组件句柄
 *
 * 页面是 .vue.js 模块（render 函数写法，无模板编译），所以不能写 <el-table>。
 * 这里按需从全局 ElementPlus 取组件对象，页面用 ui.ElTable(...) 构造 vnode：
 *
 *   h(ui.ElTable, { data: rows }, { default: () => [...列...] })
 *
 * 取到的组件对象全部在模块加载时确定，运行期不再查表；ElementPlus 缺组件时
 * 返回一个显式的占位组件（而不是 undefined 导致整页白屏）。
 */
const El = window.ElementPlus || {};

function pick(names) {
  for (const name of names) {
    if (El[name]) return El[name];
  }
  return null;
}

const PLACEHOLDER = {
  name: "MissingElement",
  props: { name: { type: String, default: "" } },
  template: "<span class='muted'>[缺失组件]</span>",
};

function component(names) {
  return pick(names) || PLACEHOLDER;
}

export const ui = {
  ElButton: component(["ElButton"]),
  ElButtonGroup: component(["ElButtonGroup"]),
  ElInput: component(["ElInput"]),
  ElInputNumber: component(["ElInputNumber"]),
  ElSwitch: component(["ElSwitch"]),
  ElSelect: component(["ElSelect"]),
  ElOption: component(["ElOption"]),
  ElCheckbox: component(["ElCheckbox"]),
  ElRadioGroup: component(["ElRadioGroup"]),
  ElRadio: component(["ElRadio"]),
  ElRadioButton: component(["ElRadioButton"]),
  ElDialog: component(["ElDialog"]),
  ElDrawer: component(["ElDrawer"]),
  ElDropdown: component(["ElDropdown"]),
  ElDropdownMenu: component(["ElDropdownMenu"]),
  ElDropdownItem: component(["ElDropdownItem"]),
  ElPopup: component(["ElTooltip", "ElPopover"]),
  ElTag: component(["ElTag"]),
  ElTable: component(["ElTable"]),
  ElTableColumn: component(["ElTableColumn"]),
  ElForm: component(["ElForm"]),
  ElFormItem: component(["ElFormItem"]),
  ElAlert: component(["ElAlert"]),
  ElProgress: component(["ElProgress"]),
  ElDivider: component(["ElDivider"]),
  ElEmpty: component(["ElEmpty"]),
  ElCollapse: component(["ElCollapse"]),
  ElCollapseItem: component(["ElCollapseItem"]),
  ElDescriptions: component(["ElDescriptions"]),
  ElDescriptionsItem: component(["ElDescriptionsItem"]),
  ElSkeleton: component(["ElSkeleton"]),
  ElLoading: component(["ElLoading"]),
};

/** 全局轻提示（统一出口）：三秒自动消散、同文案自动合并、样式见 styles.css 的 .wb-toast。
 *  页面仍按 ElMessage.success/error/warning/info 调用，此处统一注入默认值。 */
const TOAST_DURATION = 3000;
function wrapMessage(raw) {
  if (!raw || typeof raw !== "function") {
    const log = (m) => console.log(m);
    log.success = log; log.warning = log; log.info = log;
    log.error = (m) => console.error(m);
    log.closeAll = () => {};
    return log;
  }
  const call = (options) => {
    const opts = typeof options === "string" ? { message: options } : { ...(options || {}) };
    return raw({
      duration: TOAST_DURATION, grouping: true, offset: 64, customClass: "wb-toast", ...opts,
    });
  };
  call.success = (o) => call(typeof o === "string" ? { message: o, type: "success" } : { type: "success", ...o });
  call.warning = (o) => call(typeof o === "string" ? { message: o, type: "warning" } : { type: "warning", ...o });
  call.error = (o) => call(typeof o === "string" ? { message: o, type: "error" } : { type: "error", ...o });
  call.info = (o) => call(typeof o === "string" ? { message: o, type: "info" } : { type: "info", ...o });
  call.closeAll = () => { if (typeof raw.closeAll === "function") raw.closeAll(); };
  return call;
}

/** 全站唯一「减弱动态效果」判定：系统开启减弱动态时，动画一律静默或直接跳变
 *  （MetricCard 数值缓动、StateBadge 状态脉冲、主题切换淡入共用这一处）。 */
export function prefersReducedMotion() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

export const ElMessage = wrapMessage(El.ElMessage);

export const ElMessageBox = El.ElMessageBox || {
  confirm: () => Promise.resolve(),
};

export default ui;
