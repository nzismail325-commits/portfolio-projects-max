/*
 * panel/components/kit.js —— 视图共用小件集（本地自研，上游无对应）
 *
 * 页面间反复出现的结构块统一在这里构造，页面只做声明式拼装，禁止各写各的：
 *   cardHead      卡片标题行（图标 + 标题 + 弱化提示 + 可选右侧内容）
 *   errorAlert    页面级加载失败横幅（与 PageHead 配对）
 *   badge         语义徽标（tone 见 styles.css 的 .badge.*）
 *   confirmAction 确认流（全站唯一实现）
 *   copyText      复制文本（Clipboard API + 非安全上下文回退）
 *   refreshAction 页头刷新件（图标胶囊，加载中图标自转；全站唯一实现）
 *   rangeButtons  筛选按钮组（.range-btn 胶囊组，Dashboard/Tasks/Logs/Theme 同款）
 *   channelMeta   渠道卡片内的行内元信息（渠道名 + 出口徽标 + 统计）
 *   channelSection 渠道分块外框（section[data-channel].page-block）
 */
import { h } from "/vendor/vue.mjs";
import { ui, ElMessageBox } from "./ui.js";
import { ico } from "./icons.js";

/** 卡片标题行：第四个参数是图标名（icons.js），trailing 传需要推到右侧的内容。 */
export function cardHead(title, hint = "", trailing = null, icon = "") {
  return h("h3", { class: "card-head" }, [
    icon ? h("span", { class: "card-head-ico", innerHTML: ico(icon), "aria-hidden": "true" }) : null,
    h("span", { class: "card-head-title" }, title),
    hint ? h("span", { class: "hint" }, hint) : null,
    trailing,
  ]);
}

/** 页面级加载失败横幅：h("div", null, [head, errorAlert(this.error)])。 */
export function errorAlert(message) {
  return h(ui.ElAlert, { type: "error", title: "加载失败", description: message, showIcon: true });
}

/** 语义徽标：tone = s / ok / warn / bad / info / off（空串走中性）；
 *  extra 追加附加类（如 "mini" 小号徽标）。 */
export function badge(text, tone = "s", title = "", extra = "") {
  return h("span", { class: ["badge", tone, extra].filter(Boolean), title }, text);
}

/** 确认流：弹出确认框，用户取消/Esc 返回 false；resolve 返回 true。 */
export async function confirmAction(message, title, options = {}) {
  try {
    await ElMessageBox.confirm(message, title, options);
    return true;
  } catch (err) {
    return false;
  }
}

/** 复制文本：优先 Clipboard API，非安全上下文回退到临时 textarea。 */
export async function copyText(text) {
  const value = String(text || "");
  if (!value) return false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (err) { /* 回退到 execCommand */ }
  try {
    const area = document.createElement("textarea");
    area.value = value;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    try {
      area.select();
      return document.execCommand("copy");
    } finally {
      area.remove();
    }
  } catch (err) {
    return false;
  }
}

/** 页头刷新件（全站唯一实现）：图标 + 文字的小胶囊，加载中图标自转、按钮
 *  禁用。页面只传 onClick 与 loading；重操作可改 label/title 并用 primary
 *  提为品牌底色（如「刷新模型清单」强制拉上游）。 */
export function refreshAction({ onClick, loading = false, label = "刷新",
                                title = "", primary = false }) {
  return h(ui.ElButton, {
    size: "small",
    class: "wb-refresh",
    type: primary ? "primary" : undefined,
    disabled: Boolean(loading),
    title: title || (loading ? "正在刷新…" : "重新拉取本页数据"),
    onClick,
  }, [
    h("span", {
      class: ["r-ico", loading ? "spin" : ""],
      innerHTML: ico("refresh"),
      "aria-hidden": "true",
    }),
    label,
  ]);
}

/** 筛选按钮组：options = [{ value, label, title? }]，current 为当前值，onPick(value)。 */
export function rangeButtons(options, current, onPick) {
  return options.map((opt) =>
    h("button", {
      key: opt.value,
      type: "button",
      class: ["range-btn", current === opt.value ? "active" : ""],
      title: opt.title || "",
      onClick: () => onPick(opt.value),
    }, opt.label));
}

/** 渠道名去掉括号里的长后缀（如 TRAE SOLO CN），用于页头/卡片行内标题。 */
export function shortChannelLabel(label) {
  return String(label || "").replace(/\s*[（(].*$/, "").trim();
}

/** 出口徽标：与渠道名重复时返回空数组，避免页头出现两个同义标签。 */
export function realmBadges(channel, realm) {
  const channelLabel = shortChannelLabel(channel?.label || channel?.id);
  const realmLabel = realm?.badge || realm?.label || realm?.id || "";
  const key = channelLabel.split(/\s+/)[0].toLowerCase();
  return realmLabel && !String(realmLabel).toLowerCase().includes(key)
    ? [badge(realmLabel, "s")]
    : [];
}

/** 渠道卡片内的行内元信息：渠道名 + 出口/统计徽标 + 说明，供表格工具条左侧使用。 */
export function channelMeta({ title, badges = [], hint = "" }) {
  return h("div", { class: "channel-meta" }, [
    title ? h("span", { class: "channel-meta-name" }, title) : null,
    ...badges,
    hint ? h("span", { class: "channel-meta-hint muted" }, hint) : null,
  ]);
}

/** 渠道分块外框：children 为该渠道的全部卡片。 */
export function channelSection(channelId, children) {
  return h("section", { key: channelId, "data-channel": channelId, class: "page-block" }, children);
}
