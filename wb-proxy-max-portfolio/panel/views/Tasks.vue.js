/*
 * panel/views/Tasks.vue.js —— 任务与福利
 *
 * 页面边界（§2.2）：只呈现「声明了 tasks / scheduler 能力」的渠道。调度任务
 * 清单由后端 /channels 下发（含渠道归属），页面不硬编码任何任务 id；只有
 * 声明了该能力的渠道才渲染「立即执行」按钮。
 *
 * 出口跟随顶栏切换的全局偏好（store.realm），页面内不放第二套出口切换；
 * 成长任务进度来自 /tasks（后端按账号标记 channel），页面按渠道出口过滤展示。
 */
import { h, ref, computed, onMounted, onUnmounted, watch } from "/vendor/vue.mjs";
import { useStore, ensureBootstrap, rawState, loadPref, savePref, currentRealm as storeCurrentRealm, realmMeta } from "../store/index.js";
import { channelsApi } from "../api/channels.js";
import { tasksApi } from "../api/tasks.js";
import { settingsApi } from "../api/settings.js";
import { ui, ElMessage } from "../components/ui.js";
import { num, taskTime, time, isoShort } from "../components/format.js";
import PageHead from "../components/PageHead.js";
import EmptyState from "../components/EmptyState.js";
import StateBadge from "../components/StateBadge.js";
import WbTable from "../components/WbTable.js";
import { cardHead, errorAlert, badge, rangeButtons, shortChannelLabel, realmBadges, channelSection, confirmAction, refreshAction } from "../components/kit.js";
import { ico } from "../components/icons.js";
import { createPoller } from "../composables/poll.js";

const TASK_CAPS = new Set(["tasks", "scheduler"]);
const POLL_MS = 2000;

const TASK_ICONS = {
  checkin: "calendar", travel: "send", activity: "radio", nightcat: "moon",
  streak: "gem", school: "cap", dailychat: "bolt", keepalive: "refresh",
  trae_checkin: "calendar",
};

export default {
  name: "TasksView",
  components: { PageHead, EmptyState, StateBadge },
  setup() {
    const store = useStore();
    const loading = ref(false);
    const error = ref("");
    const scheduler = ref(null);
    const progress = ref({ accounts: [], fetched_at: 0 });
    const records = ref([]);
    const recordStats = ref({ total: 0, total_credits: 0, by_kind: {} });
    // 流水筛选偏好记忆（T-20）：类型为后端下发的 kind id（空串=全部，不设白名单），天数限两档
    const recordKind = ref(loadPref("tasks.recordKind", ""));
    const recordDays = ref(loadPref("tasks.recordDays", 7, [7, 30]));
    const job = ref(null);
    const jobBusy = ref(false);
    /** 成长任务中心的适用出口（后端 /tasks 下发 growth_realm，前端不猜）。 */
    const growthRealm = ref("");
    /** 执行中一键作业归属的出口：进度与日志只渲染在发起它的出口块里。 */
    const jobRealm = ref("");
    /** 一键作业进度轮询（错误即停、完成即停，见 trackJob）。 */
    let jobPoller = null;

    const channels = computed(() =>
      (store.channels || []).filter((channel) =>
        (channel.capabilities || []).some((cap) => TASK_CAPS.has(cap))));

    /** 当前出口 id：统一实现在 store（跟随顶栏全局偏好，未命中回落第一个出口）。 */
    function realmOf(channel) {
      return storeCurrentRealm(channel)?.id || "";
    }

    /** 当前出口对象（渲染层要 badge / domain 等元信息时用）。 */
    function realmObject(channel) {
      return storeCurrentRealm(channel);
    }

    /** 任务清单：渠道归属 + 出口归属双重过滤（realms 由注册表下发，前端不猜）。 */
    function tasksOf(channel) {
      const realm = realmOf(channel);
      return (store.schedulerTasks || []).filter((task) =>
        task.channel === channel.id
        && (!task.realms || !task.realms.length || task.realms.includes(realm)));
    }

    /** 单任务启用/停用：整份回传当前排程，避免部分提交丢掉自定义时间。 */
    async function toggleTask(task, info) {
      const entry = {
        enabled: !(info && info.enabled),
        hours: (info && info.hours) || [],
      };
      if (info && info.count != null) entry.count = info.count;
      try {
        await settingsApi.save({ automation: { [task.id]: entry } });
        ElMessage.success(entry.enabled ? `「${task.label}」已启用` : `「${task.label}」已停用`);
        await refresh();
      } catch (err) {
        ElMessage.error(err.message || "保存失败");
      }
    }

    /** 全局排程暂停 / 恢复（对应原版「暂停排程」按钮）。 */
    async function toggleScheduler() {
      const enabled = (scheduler.value || {}).enabled === false;
      try {
        await settingsApi.save({ automation: { enabled } });
        ElMessage.success(enabled ? "排程已恢复" : "排程已暂停（手动执行不受影响）");
        await refresh();
      } catch (err) {
        ElMessage.error(err.message || "保存失败");
      }
    }

    /** 「全部执行」二次确认：一键触发全部启用任务同时打上游，误触成本高。 */
    async function triggerAll(channel) {
      const ok = await confirmAction(
        "将立即手动执行当前出口的全部启用任务（同时打上游，耗时与用量都会增加）。确定执行？",
        "全部执行", { type: "warning", confirmButtonText: "执行", cancelButtonText: "取消" });
      if (!ok) return;
      await trigger(channel, "all");
    }

    function progressOf(channel) {
      const realm = realmOf(channel);
      return (progress.value.accounts || []).filter((item) => item.realm === realm);
    }

    function recordsOf(channel) {
      const realm = realmOf(channel);
      return records.value.filter((row) => !realm || !row.realm || row.realm === realm);
    }

    async function loadRecords() {
      const payload = await tasksApi.records({
        kind: recordKind.value || undefined,
        days: recordDays.value,
        limit: 200,
        realm: rawState().realm || undefined,
      });
      records.value = payload.logs || [];
      recordStats.value = payload.stats || { total: 0, total_credits: 0, by_kind: {} };
    }

    async function refresh() {
      const [status, growth] = await Promise.all([
        tasksApi.scheduler(),
        tasksApi.progress(),
      ]);
      scheduler.value = status;
      progress.value = growth;
      growthRealm.value = growth.growth_realm || "cn";
      await loadRecords();
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        await refresh();
      } catch (err) {
        error.value = err.message || "任务数据加载失败";
      } finally {
        loading.value = false;
      }
    }

    async function trigger(channel, taskId) {
      try {
        const payload = await tasksApi.trigger(taskId);
        if (payload.ok === false) {
          ElMessage.warning(payload.msg || "已有任务在执行");
          return;
        }
        ElMessage.success(payload.msg || "已触发后台执行");
        watchTaskRun(taskId);
      } catch (err) {
        ElMessage.error(err.message || "触发失败");
      }
    }

    /** 手动触发后轮询调度状态，任务批次结束自动刷新一次（不等用户手点）。
     *  seen 记录已见过的 last.iso：轮询到它变化 = 这一批次跑完了（闭包内独立，
     *  多次触发互不干扰）；超过 40 轮（2 分钟）或查询失败则放弃等待。 */
    function watchTaskRun(taskId) {
      const seen = {};
      let ticks = 0;
      const poller = createPoller(async () => {
        ticks += 1;
        try {
          const status = await tasksApi.scheduler();
          const info = (status.tasks || {})[taskId] || {};
          const lastIso = (info.last || {}).iso || "";
          if (lastIso && lastIso !== seen[taskId]) {
            seen[taskId] = lastIso;
            poller.stop();
            await refresh().catch(() => {});
          } else if (ticks > 40) {
            poller.stop();
          }
        } catch (err) {
          poller.stop();
        }
      }, 3000);
      poller.start();
    }

    function trackJob(jobId) {
      if (jobPoller) jobPoller.stop();
      jobPoller = createPoller(async () => {
        try {
          const payload = await tasksApi.job(jobId);
          job.value = payload;
          if (payload.finished) {
            jobPoller.stop();
            jobBusy.value = false;
            ElMessage.success(payload.ok ? "成长任务已完成" : "成长任务已结束（部分失败）");
            await refresh();
          }
          return payload;
        } catch (err) {
          jobPoller.stop();
          jobBusy.value = false;
          return null;
        }
      }, POLL_MS, { until: (p) => Boolean(p && p.finished) });
    }

    async function startGrowth(channel) {
      if (jobBusy.value) return;
      const realm = realmOf(channel);
      if (growthRealm.value && realm !== growthRealm.value) {
        ElMessage.warning(`成长任务只适用于${realmBadge(growthRealm.value) || growthRealm.value}出口`);
        return;
      }
      try {
        const payload = await tasksApi.startGrowthJob(realm);
        if (payload.ok === false) {
          ElMessage.warning(payload.msg || "当前无法启动");
          return;
        }
        jobBusy.value = true;
        jobRealm.value = realm;
        job.value = { id: payload.job_id, finished: false, logs: [], done: 0, total: 0 };
        trackJob(payload.job_id);
      } catch (err) {
        ElMessage.error(err.message || "启动失败");
      }
    }

    function realmBadge(realmId) {
      return realmMeta(realmId)?.badge || "";
    }

    // 顶栏出口切换 → 任务页跟随刷新流水（进度/记录的出口过滤在渲染时生效）
    watch(() => rawState().realm, () => {
      if (store.authenticated) loadRecords().catch(() => {});
    });

    async function changeKind(value) {
      recordKind.value = value;
      savePref("tasks.recordKind", value);
      await loadRecords();
    }

    async function changeDays(value) {
      recordDays.value = value;
      savePref("tasks.recordDays", value);
      await loadRecords();
    }

    onMounted(async () => {
      await ensureBootstrap();
      await load();
    });
    onUnmounted(() => {
      if (jobPoller) jobPoller.stop();
    });

    return {
      store, loading, error, scheduler, progress, records, recordStats,
      recordKind, recordDays, job, jobBusy, jobRealm, growthRealm, channels,
      realmOf, realmObject, tasksOf, progressOf, recordsOf, toggleTask, toggleScheduler,
      load, refresh, trigger, triggerAll, startGrowth, changeKind, changeDays,
      num, taskTime, time, ico,
    };
  },
  methods: {
    taskIcon(taskId) {
      return TASK_ICONS[taskId] || "clock";
    },
    /** 今日执行次数与积分合计（scheduler.status 的 last_results 按任务聚合）。 */
    todayRuns(channel) {
      const status = this.scheduler || {};
      const byKind = status.by_kind || (status.stats || {}).by_kind || {};
      const tasks = this.tasksOf(channel);
      let runs = 0, credits = 0, active = 0;
      tasks.forEach((task) => {
        const bucket = byKind[task.id] || {};
        runs += bucket.count || 0;
        credits += bucket.credits || 0;
        const info = (status.tasks || {})[task.id] || {};
        if (info.enabled) active++;
      });
      return { runs, credits, active, total: tasks.length };
    },
    renderScheduleCard(channel) {
      if (!channelsApi.supports(channel, "scheduler")) return null;
      const tasks = this.tasksOf(channel);
      if (!tasks.length) return null;
      const status = this.scheduler || {};
      const lastOf = (taskId) => (status.tasks || {})[taskId] || {};
      const runs = this.todayRuns(channel);
      return h("div", { class: "card" }, [
        cardHead("自动化任务",
          (status.enabled === false ? "调度已暂停" : "调度运行中") + " · 执行时间在设置页修改",
          h("div", { class: "push", style: "display:flex;gap:8px;align-items:center" }, [
            h(ui.ElButton, {
              size: "small",
              onClick: () => this.toggleScheduler(),
            }, status.enabled === false ? "恢复排程" : "暂停排程"),
            h(ui.ElButton, {
              size: "small",
              onClick: () => this.triggerAll(channel),
            }, "全部执行"),
          ]), "tasks"),
        !tasks.length
          ? h(EmptyState, {
              text: "当前出口没有适用的自动化任务",
              hint: "任务的出口归属由后端注册表裁决；切换顶栏出口查看其它任务",
              icon: "tasks",
            })
          : h("div", { class: "auto-grid", style: "grid-template-columns:230px 1fr" }, [
          h("div", { class: "auto-left" }, [
            h("div", { class: "al-status" }, [
              h("span", { class: ["dot", status.enabled === false ? "off" : ""], "aria-hidden": "true" }),
              h("div", null, [
                h("div", { class: "al-big" }, status.enabled === false ? "已暂停" : "运行中"),
                h("div", { class: "al-sub" }, ["下次执行 ", h("b", null, status.next_run_time || "待调度")]),
              ]),
            ]),
            h("div", { class: "al-stats" }, [
              h("div", { class: "al-stat" }, [
                h("div", { class: "al-num" }, [String(runs.runs), h("span", { class: "unit" }, "次")]),
                h("div", { class: "al-label" }, "累计执行"),
              ]),
              h("div", { class: "al-stat" }, [
                h("div", { class: "al-num" }, [runs.credits ? "+" + runs.credits : "0",
                  h("span", { class: "unit" }, "分")]),
                h("div", { class: "al-label" }, "积分收益"),
              ]),
              h("div", { class: "al-stat" }, [
                h("div", { class: "al-num" }, [`${runs.active}/${runs.total}`]),
                h("div", { class: "al-label" }, "启用任务"),
              ]),
            ]),
            h("div", { class: "al-note" },
              "手动触发与定时执行走同一管道，结果自动落库；明细见下方「任务流水」。"),
          ]),
          h("div", { class: "auto-tasks" }, tasks.map((task) => {
            const info = lastOf(task.id);
            const last = info.last || null;
            return h("div", {
              key: task.id,
              class: ["auto-task-card", info.enabled ? "on" : "off"],
            }, [
              h("div", { class: "at-head" }, [
                h("span", { class: "at-ico", innerHTML: ico(this.taskIcon(task.id)) }),
                h("span", { class: "at-name", title: task.label || task.id }, task.label || task.id),
                h("button", {
                  type: "button",
                  class: ["at-toggle", info.enabled ? "on" : "off"],
                  // 文案是点击后的动作，不是当前状态：启用中的任务点它=停用
                  title: info.enabled ? "点击停用该任务（定时不再执行）" : "点击启用该任务",
                  onClick: () => this.toggleTask(task, info),
                }, info.enabled ? "停用" : "启用"),
              ]),
              h("div", { class: "at-hours" }, info.enabled
                ? (info.hours || []).map((hour) => `${hour}:00`).join(" · ") || "未排程"
                : "已停用"),
              h("div", { class: "at-last" }, last
                ? [last.level ? h(StateBadge, { status: last.level }) : null,
                   h("span", { class: "at-msg", title: last.msg || "" },
                     last.iso ? isoShort(last.iso, "") : (last.msg || ""))]
                : badge("尚未运行", "off", "", "mini")),
              h(ui.ElButton, {
                class: "at-run",
                size: "small",
                onClick: () => this.trigger(channel, task.id),
              }, "立即执行"),
            ]);
          })),
        ]),
      ]);
    },

    renderGrowthCard(channel) {
      if (!channelsApi.supports(channel, "tasks")) return null;
      // 成长任务中心只适用后端下发的出口（growth_realm）：其它出口整卡不渲染
      if (this.growthRealm && this.realmOf(channel) !== this.growthRealm) return null;
      const accounts = this.progressOf(channel);
      // 没有适用账号时不再渲染大空态和不可用的一键按钮，只留一行说明
      if (!accounts.length) {
        return h("div", { class: "card" }, [
          cardHead("成长任务进度", "当前出口暂无适用账号；成长任务仅支持国内版账号",
            null, "gem"),
        ]);
      }
      return h("div", { class: "card" }, [
        cardHead("成长任务进度",
          this.progress.fetched_at ? `采集于 ${this.time(this.progress.fetched_at)}` : "",
          h(ui.ElButton, {
            size: "small", type: "primary", class: "push",
            loading: this.jobBusy,
            onClick: () => this.startGrowth(channel),
          }, this.jobBusy ? "执行中…" : "一键做任务领积分"), "gem"),
        ...accounts.map((item) => h("div", { key: item.uid, style: "margin-bottom:16px" }, [
              h("div", { class: "channel-head" }, [
                h("span", { class: "name" }, item.nickname || String(item.uid).slice(0, 8)),
                h(StateBadge, { status: item.ok ? "ok" : "error",
                                label: item.ok ? "读取成功" : "读取失败" }),
                h("div", { class: "caps" }, [
                  badge(`连登 ${num(item.streak_days)} 天`, ""),
                  badge(`能量 ${num(item.energy)}`, ""),
                  item.travel_state
                    ? badge(`猫猫 ${item.travel_state === "traveling" ? "旅行中"
                        : item.travel_state === "arrived" ? "归来待领奖" : "家中待命"}`)
                    : null,
                ]),
              ]),
              item.ok
                ? h(WbTable, {
                    rows: item.tasks || [],
                    maxHeight: 320,
                    rowKey: "task_code",
                    columns: [
                      { label: "任务", minWidth: 170, render: ({ row }) => [
                          h("b", null, row.name || row.task_code || "—"),
                          row.task_code
                            ? h("div", { class: "muted mono", style: "font-size:10.5px" }, row.task_code)
                            : null,
                        ] },
                      { label: "状态", width: 100, render: ({ row }) => h(StateBadge, { status: row.status }) },
                      { label: "进度", width: 110, render: ({ row }) =>
                          (row.status === "claimed" || row.status === "completed")
                            ? "已完成"
                            : `${num(row.current)} / ${num(row.target)}` },
                      { label: "奖励", width: 110, render: ({ row }) => [
                          row.reward_credit
                            ? h("b", { style: "color:var(--accent-2)" }, `+${num(row.reward_credit)} 积分`)
                            : null,
                          row.reward_energy
                            ? h("span", { style: "color:var(--accent)" }, ` +${num(row.reward_energy)} 能量`)
                            : null,
                          (!row.reward_credit && !row.reward_energy)
                            ? h("span", { class: "muted" }, "—") : null,
                        ] },
                      { label: "说明", minWidth: 180, render: ({ row }) =>
                          row.reason || row.description
                            || h("span", { class: "muted" }, "—") },
                    ],
                  })
                : h(ui.ElAlert, { type: "warning", showIcon: true,
                                  description: item.error || "读取失败" }),
            ])),
        // 一键作业的进度与日志只挂在发起它的出口块里（jobRealm 归属）
        (this.job && (!this.jobRealm || this.jobRealm === this.realmOf(channel)))
          ? h("div", { style: "margin-top:14px" }, [
              h(ui.ElProgress, {
                percentage: this.job.total
                  ? Math.round((this.job.done || 0) * 100 / this.job.total) : 0,
                status: this.job.finished ? (this.job.ok ? "success" : "warning") : "",
              }),
              h("div", { class: "task-log" },
                (this.job.logs || []).slice(-60).map((line, index) =>
                  h("div", { key: index }, String(line || "")))),
            ]) : null,
      ]);
    },

    renderRecordsCard(channel) {
      const rows = this.recordsOf(channel);
      const stats = this.recordStats || {};
      const kinds = Object.entries(stats.by_kind || {});
      return h("div", { class: "card" }, [
        cardHead("任务流水",
          `共 ${num(stats.total)} 条 · 累计积分收益 ${num(stats.total_credits)}`,
          null, "logs"),
        h("div", { class: "toolbar" }, [
          ...rangeButtons(
            [{ value: "", label: "全部" },
             ...kinds.map(([kind, value]) => ({
               value: kind, label: `${TASK_LABELS[kind] || kind} ${value.count || 0}`,
             }))],
            this.recordKind, (value) => this.changeKind(value)),
          h("span", { style: "margin-left:auto;display:inline-flex;gap:4px" },
            rangeButtons([{ value: 7, label: "近 7 天" }, { value: 30, label: "近 30 天" }],
              this.recordDays, (value) => this.changeDays(value))),
        ]),
        rows.length
          ? h(WbTable, { rows, maxHeight: 460, stripe: true, columns: [
              { label: "时间", width: 130, render: ({ row }) =>
                  h("span", { class: "mono", style: "font-size:11.5px" }, taskTime(row.ts)) },
              { label: "类型", width: 110, render: ({ row }) => TASK_LABELS[row.kind] || row.kind || "—" },
              { label: "账号", minWidth: 130, render: ({ row }) => [
                  row.nickname || String(row.uid || "").slice(0, 8) || "—",
                  h("span", { class: "muted mono", style: "font-size:10.5px" },
                    ` ${String(row.uid || "").slice(0, 8)}`),
                ] },
              { label: "来源", width: 70, render: ({ row }) => row.source === "manual" ? "手动" : "自动" },
              { label: "结果", width: 90, render: ({ row }) =>
                  row.level ? h(StateBadge, { status: row.level }) : null },
              { label: "积分", width: 80, align: "right", render: ({ row }) => row.credits
                  ? h("b", { style: "color:var(--accent-2)" }, `+${num(row.credits)}`)
                  : h("span", { class: "muted" }, "—") },
              { prop: "message", label: "说明", minWidth: 220, render: ({ row }) =>
                  h("span", { class: "muted", title: row.message || "" }, row.message || "—") },
            ] })
          : h(EmptyState, { text: "所选区间没有任务记录",
              hint: "任务执行后这里会显示结果与积分收益", icon: "tasks" }),
      ]);
    },
  },
  render() {
    // 页头直接承载当前渠道/出口信息，渠道标题不再单独浮在页面上
    const activeChannel = this.channels.find((channel) => this.realmObject(channel));
    const activeRealm = activeChannel ? this.realmObject(activeChannel) : null;
    const meta = activeChannel
      ? [badge(shortChannelLabel(activeChannel.label || activeChannel.id), "info"),
         ...realmBadges(activeChannel, activeRealm)]
      : [];
    if (activeRealm?.domain) {
      meta.push(h("span", { class: "page-head-sub" }, activeRealm.domain));
    }
    const head = h(PageHead, {
      title: "任务与福利",
      desc: "定时任务与成长任务按渠道分块；任务清单由后端注册表下发",
      icon: "tasks",
      meta,
    }, {
      actions: () => [
        refreshAction({ onClick: () => this.refresh(), loading: this.loading }),
      ],
    });

    if (this.error) {
      return h("div", null, [head, errorAlert(this.error)]);
    }

    if (!this.channels.length) {
      return h("div", null, [
        head,
        h(EmptyState, {
          text: "没有声明任务能力的渠道",
          hint: "后端注册表未下发 tasks / scheduler 能力，页面不留入口",
        }),
      ]);
    }

    return h("div", null, [
      head,
      h("div", { class: "channel-sections" },
        this.channels.map((channel) => {
          const realmObj = this.realmObject(channel);
          const realmId = realmObj?.id || "";
          if (!realmId) return null; // 全局偏好指向其他渠道：本渠道整块不渲染（§2.2）
          return channelSection(channel.id, [
            this.renderScheduleCard(channel),
            this.renderGrowthCard(channel),
            this.renderRecordsCard(channel),
          ]);
        })),
    ]);
  },
};

const TASK_LABELS = {
  checkin: "自动签到",
  travel: "猫猫旅行",
  activity: "活跃上报",
  nightcat: "夜猫任务",
  streak: "连登管家",
  school: "开学季任务",
  dailychat: "国际版每日活跃",
  keepalive: "令牌保活",
  credit: "积分变动",
  summary: "轮次汇总",
};
