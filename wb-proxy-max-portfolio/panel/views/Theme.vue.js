/*
 * panel/views/Theme.vue.js —— 主题外观
 *
 * 移植自二开原版的「主题外观」页：三张主题卡（默认 / 午夜书房 / 云海霞光），
 * 点卡片即切换；「默认」主题自带深色 / 浅色两种模式，开关就在它的卡内，
 * 也是全面板唯一的明暗切换。选择保存在本机浏览器（localStorage）。
 *
 * 主题切换只改 <html data-theme>，与渠道 / 账号数据无关，本页无接口调用。
 */
import { h } from "/vendor/vue.mjs";
import { useStore, setTheme } from "../store/index.js";
import PageHead from "../components/PageHead.js";
import { rangeButtons, cardHead } from "../components/kit.js";

/** 主题注册表（与原版一致）：hasMode 的主题自带明暗，画作主题由画作定调。 */
const THEMES = [
  {
    storeId: "default-dark", name: "默认", tag: "经典驾驶舱 · 青蓝", hasMode: true,
    desc: "面板原有配色。深色像深夜驾驶舱，浅色是明亮的办公风；深色 / 浅色开关就在本卡内。",
  },
  {
    storeId: "midnight", name: "午夜书房", tag: "深夜蓝紫 · 暖台灯", img: "/themes/midnight.jpg",
    desc: "整页背景换成画作：蓝紫墙面、暖黄台灯与满墙海报的深夜房间。所有面板变成磨砂玻璃浮在画面上，点缀色取台灯的暖琥珀。",
  },
  {
    storeId: "sky", name: "云海霞光", tag: "破晓金粉 · 云浪", img: "/themes/sky.jpg",
    desc: "整页背景换成破晓云海的画：金粉与玫瑰色的光从云浪后透出来。面板同样是磨砂玻璃，点缀色取云缝里的金光与玫瑰光。",
  },
];

export default {
  name: "ThemeView",
  components: { PageHead },
  computed: {
    store() { return useStore(); },
    themeId() { return this.store.theme || "default-dark"; },
  },
  methods: {
    isDefault() { return this.themeId.startsWith("default"); },
    pickTheme(theme) {
      setTheme(theme.hasMode
        ? (this.isDefault() ? this.themeId : "default-dark")
        : theme.storeId);
    },
    pickMode(mode) {
      setTheme(mode === "light" ? "default-light" : "default-dark");
    },
    cardActive(theme) {
      return theme.hasMode ? this.isDefault() : this.themeId === theme.storeId;
    },
    cardModeLabel(theme) {
      if (!this.cardActive(theme)) return "未使用";
      return theme.hasMode
        ? (this.themeId === "default-light" ? "浅色" : "深色")
        : "画作";
    },
  },
  render() {
    const head = h(PageHead, {
      title: "主题外观",
      desc: "三套主题：「默认」是面板原有配色，深色 / 浅色开关就在它的卡片里；两张画作主题会把整页背景换成对应画作，所有面板变成磨砂玻璃浮在画上。点卡片即切换，自动保存在本机浏览器",
      icon: "palette",
    });

    const cards = THEMES.map((theme) => {
      const active = this.cardActive(theme);
      return h("div", {
        key: theme.storeId,
        class: ["theme-card", active ? "active" : ""],
        role: "button",
        tabindex: 0,
        "aria-pressed": String(active),
        title: active ? `当前主题：${theme.name}` : `切换到「${theme.name}」`,
        onClick: () => this.pickTheme(theme),
        onKeydown: (event) => {
          if (event.key === "Enter") this.pickTheme(theme);
        },
      }, [
        active ? h("span", { class: "theme-using" }, "使用中") : null,
        h("span", {
          class: ["theme-banner", theme.img ? "" : "prev-default"],
          style: theme.img ? `background-image:url(${theme.img})` : "",
        }),
        h("span", { class: "theme-body" }, [
          h("span", { class: "theme-name" }, [
            theme.name,
            h("span", { class: ["theme-state", active ? "on" : "off"] },
              this.cardModeLabel(theme)),
          ]),
          h("span", { class: "theme-tag" }, theme.tag),
          h("span", { class: "theme-desc" }, theme.desc),
          theme.hasMode
            ? h("span", { class: "theme-foot" },
                h("span", { class: "theme-modes", onClick: (event) => event.stopPropagation() },
                  rangeButtons([
                    { value: "default-dark", label: "深色", title: "默认主题 · 深色模式" },
                    { value: "default-light", label: "浅色", title: "默认主题 · 浅色模式" },
                  ], this.themeId === "default-dark" ? "default-dark" : "default-light",
                  (value) => this.pickMode(value === "default-dark" ? "dark" : "light"))))
            : h("span", { class: "theme-foot" },
                h("span", { class: "theme-art-note" }, "画作背景 · 磨砂玻璃面板")),
        ]),
      ]);
    });

    const current = THEMES.find((theme) => this.cardActive(theme));
    const modeText = this.isDefault()
      ? (this.themeId === "default-light" ? "浅色（明亮办公风）" : "深色（深夜驾驶舱）")
      : "由画作定调，不分明暗（明暗开关只属于「默认」主题）";

    const summary = h("div", { class: "card" }, [
      cardHead("当前外观",
        "「默认」主题的深色 / 浅色开关在它的卡片内；画作主题由画作本身定调",
        null, "palette"),
      h("table", { class: "kv-table" }, [
        h("tbody", null, [
          h("tr", null, [h("td", null, "正在使用"), h("td", null, h("b", null, current?.name || "—"))]),
          h("tr", null, [h("td", null, "明暗模式"), h("td", null, modeText)]),
          h("tr", null, [h("td", null, "保存方式"),
            h("td", null, "仅保存在本机浏览器，不上传、不同步；清除站点数据后恢复「默认 · 深色」")]),
        ]),
      ]),
    ]);

    return h("div", null, [
      head,
      h("div", { class: "theme-grid" }, cards),
      summary,
    ]);
  },
};
