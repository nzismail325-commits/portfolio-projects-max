/*
 * panel/views/Logs.vue.js —— 日志与流水
 *
 * 两块内容，各自数据源完全不同、不混排：
 *   1. 运行日志（/logs）：网关自身的运行日志。落库关闭时后端读进程内日志环，
 *      打开时读数据库——返回结构一致，页面不区分。
 *   2. 活动历史（/activity/history）：签到与每日活跃的逐次结果。
 *
 * 页面不出现渠道筛选器：运行日志是进程级、活动历史自带 realm 字段，
 * 混用会把两个渠道的数据拼在一起（§2.2 禁止）。
 */
import { h, ref, computed, onMounted, onUnmounted } from "/vendor/vue.mjs";
import { settingsApi } from "../api/settings.js";
import { tasksApi } from "../api/tasks.js";
import { useStore, loadPref, savePref } from "../store/index.js";
import { ui } from "../components/ui.js";
import { num, isoStamp } from "../components/format.js";
import PageHead from "../components/PageHead.js";
import EmptyState from "../components/EmptyState.js";
import LogList from "../components/LogList.js";
import WbTable from "../components/WbTable.js";
import { cardHead, badge, rangeButtons, refreshAction } from "../components/kit.js";
import { realmMeta } from "../store/index.js";
import { createPoller } from "../composables/poll.js";

const LEVELS = [
  { value: "INFO", label: "信息" },
  { value: "WARN", label: "警告" },
  { value: "ERROR", label: "错误" },
];

const RANGES = [
  { value: "today", label: "今天" },
  { value: "7d", label: "近 7 天" },
  { value: "30d", label: "近 30 天" },
  { value: "all", label: "全部" },
];

const AUTO_REFRESH_MS = 5000;

export default {
  name: "LogsView",
  components: { PageHead, EmptyState, LogList },
  setup() {
    const store = useStore();

    // ---- 运行日志 ----
    const logs = ref([]);
    const logTotal = ref(0);
    const logSource = ref("");
    const logLoading = ref(false);
    const logError = ref("");
    const level = ref("");
    const tag = ref("");
    const search = ref("");
    const autoRefresh = ref(true);
    // 运行日志 5s 轮询：自动刷新关着、上一轮还没回来或页面隐藏时跳过该轮
    let logPoller = null;

    // ---- 活动历史 ----
    const activity = ref({ rows: [], total: 0 });
    // 区间偏好记忆（T-20）
    const activityRange = ref(loadPref("logs.activityRange", "7d", ["today", "7d", "30d", "all"]));
    const activityLoading = ref(false);
    const activityError = ref("");

    const tags = computed(() => {
      const seen = new Set((logs.value || []).map((row) => row.tag).filter(Boolean));
      return Array.from(seen).sort();
    });

    async function loadLogs(silent = false) {
      if (!silent) logLoading.value = true;
      logError.value = "";
      try {
        const payload = await settingsApi.logs({
          limit: 300,
          level: level.value || undefined,
          tag: tag.value || undefined,
          search: search.value || undefined,
        });
        // 后端返回按时间升序，页面最新在上更好读
        logs.value = (payload.logs || []).slice().reverse();
        logTotal.value = payload.total || 0;
        logSource.value = payload.source || "";
      } catch (err) {
        logError.value = err.message || "运行日志加载失败";
      } finally {
        logLoading.value = false;
      }
    }

    async function loadActivity() {
      activityLoading.value = true;
      activityError.value = "";
      try {
        activity.value = await tasksApi.activity({ range: activityRange.value, limit: 200 });
      } catch (err) {
        activityError.value = err.message || "活动历史加载失败";
      } finally {
        activityLoading.value = false;
      }
    }

    function changeRange(value) {
      activityRange.value = value;
      savePref("logs.activityRange", value);
      loadActivity();
    }

    /** 活动行所属渠道：文案由渠道声明的 checkin_labels 决定，
     *  未声明时回退默认签到文案。 */
    function channelOfRealm(realmId) {
      return (store.channels || []).find((channel) =>
        (channel.realms || []).some((realm) => realm.id === realmId)) || null;
    }

    onMounted(() => {
      loadLogs();
      loadActivity();
      logPoller = createPoller(() => loadLogs(true), AUTO_REFRESH_MS, {
        guard: () => autoRefresh.value && !logLoading.value && !document.hidden,
      });
      logPoller.start();
    });
    onUnmounted(() => { if (logPoller) logPoller.stop(); });

    return {
      store, logs, logTotal, logSource, logLoading, logError,
      level, tag, search, autoRefresh, tags, LEVELS,
      activity, activityRange, activityLoading, activityError, RANGES,
      loadLogs, loadActivity, changeRange, channelOfRealm, num, realmMeta,
    };
  },
  render() {
    const head = h(PageHead, {
      title: "日志与流水",
      desc: "运行日志与活动历史分开呈现，互不混排",
      icon: "logs",
    }, {
      actions: () => [
        refreshAction({
          onClick: () => { this.loadLogs(); this.loadActivity(); },
          loading: this.logLoading || this.activityLoading,
        }),
      ],
    });

    const logCard = h("div", { class: "card" }, [
      cardHead("运行日志",
        this.logSource === "db"
          ? "来源：日志库（受保留上限约束）"
          : "来源：进程内日志环（本次运行，落库未开启）",
        h("span", { class: "hint push" },
          `共 ${this.num(this.logTotal)} 条 · 每 5 秒自动刷新`), "logs"),
      h("div", { class: "toolbar" }, [
        h(ui.ElSelect, {
          modelValue: this.level,
          "onUpdate:modelValue": (value) => { this.level = value; this.loadLogs(); },
          size: "small", style: "width:130px",
          clearable: true, placeholder: "全部级别",
        }, { default: () => this.LEVELS.map((item) =>
          h(ui.ElOption, { key: item.value, label: item.label, value: item.value })) }),
        h(ui.ElSelect, {
          modelValue: this.tag,
          "onUpdate:modelValue": (value) => { this.tag = value; this.loadLogs(); },
          size: "small", style: "width:150px", clearable: true, placeholder: "全部模块",
        }, { default: () => this.tags.map((name) =>
          h(ui.ElOption, { key: name, label: name, value: name })) }),
        h(ui.ElInput, {
          modelValue: this.search,
          "onUpdate:modelValue": (value) => { this.search = value; },
          size: "small", style: "width:220px",
          placeholder: "搜索内容 / 模块（回车执行）",
          clearable: true,
          onKeyup: (event) => { if (event.key === "Enter") this.loadLogs(); },
          onClear: () => this.loadLogs(),
        }),
        h(ui.ElSwitch, {
          modelValue: this.autoRefresh,
          "onUpdate:modelValue": (value) => { this.autoRefresh = value; },
          size: "small",
        }),
        h("span", { class: "muted", style: "font-size:12px" }, "自动刷新"),
      ]),
      this.logError
        ? h(ui.ElAlert, { type: "error", showIcon: true, description: this.logError })
        : h(LogList, { rows: this.logs, emptyText: "暂无运行日志" }),
    ]);

    const activityRows = (this.activity.rows || []).map((row) => {
      const channel = this.channelOfRealm(row.realm) || {};
      const labels = channel.checkin_labels;
      return {
        ...row,
        realmLabel: (this.realmMeta(row.realm) || {}).badge || row.realm || "—",
        actionLabel: row.task === "checkin"
          ? (labels ? labels.action : "每日签到")
          : "每日活跃",
      };
    });

    const activityCard = h("div", { class: "card" }, [
      cardHead("打卡活动历史",
        "签到与每日活跃的每次真实尝试（定时巡检与手动触发都记）",
        h("span", { class: "hint push" }, `共 ${this.num(this.activity.total)} 条`), "calendar"),
      h("div", { class: "toolbar" },
        rangeButtons(this.RANGES, this.activityRange, (value) => this.changeRange(value))),
      this.activityError
        ? h(ui.ElAlert, { type: "error", showIcon: true, description: this.activityError })
        : (activityRows.length
            ? h(WbTable, { rows: activityRows, maxHeight: 440, stripe: true, columns: [
                { label: "时间", width: 170, render: ({ row }) =>
                    h("span", { class: "mono", style: "font-size:11.5px" },
                      isoStamp(row.ts, "")) },
                { label: "账号", minWidth: 150, render: ({ row }) => [
                    row.nickname || String(row.uid || "").slice(0, 8) || "—",
                    h("span", { class: "muted mono", style: "font-size:10.5px" },
                      ` ${String(row.uid || "").slice(0, 8)}`),
                  ] },
                { label: "出口", width: 90, render: ({ row }) => badge(row.realmLabel) },
                { label: "动作", width: 110, render: ({ row }) =>
                    row.actionLabel },
                { label: "来源", width: 90, render: ({ row }) =>
                    ({ scheduler: "定时巡检", manual: "手动触发",
                       account_add: "添加账号", account_import: "导入账号",
                     }[row.trigger] || row.trigger || "未知") },
                { label: "结果", width: 80, render: ({ row }) =>
                    badge(row.ok ? "成功" : "失败", row.ok ? "ok" : "bad") },
                { label: "说明", minWidth: 240, render: ({ row }) =>
                    h("span", { class: "muted" }, row.message || "—") },
              ] })
            : h(EmptyState, { text: "所选区间没有活动记录",
                hint: "定时巡检或手动打卡后这里会显示结果", icon: "calendar" })),
    ]);

    return h("div", null, [head, logCard, activityCard]);
  },
};
