/*
 * panel/components/LogList.js —— 运行日志列表（本地自研，上游无对应）
 *
 * 行结构与 /logs 返回一致：{ id, ts, time, level, tag, msg }。
 * 级别着色由行内 level 决定；筛选与加载是页面的事。
 */
import { h } from "/vendor/vue.mjs";

export default {
  name: "LogList",
  props: {
    rows: { type: Array, default: () => [] },
    emptyText: { type: String, default: "暂无日志" },
  },
  render() {
    if (!this.rows.length) {
      return h("div", { class: "empty" }, this.emptyText);
    }
    return h("div", { class: "log-list" },
      this.rows.map((row) => {
        const level = String(row.level || "").toLowerCase();
        const tone = level === "error" ? "err"
          : level === "warn" ? "warn"
            : level === "skip" ? "skip"
              : level === "ok" ? "ok" : "";
        return h("div", { class: ["row", tone], key: row.id ?? `${row.ts}-${row.msg}` }, [
          h("span", { class: "muted" }, `${row.time || row.ts || ""} `),
          h("span", { class: "muted" }, `[${row.tag || "system"}] `),
          h("span", null, row.msg || ""),
        ]);
      }));
  },
};
