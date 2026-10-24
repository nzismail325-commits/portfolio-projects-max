/*
 * panel/views/Dashboard.vue.js —— 数据看板
 *
 * 渠道范围（§2.2）：看板只为「已注册且声明了模型/对话能力」的渠道展示用量。
 * 每个渠道一块，数据全部按该渠道的出口（realm）过滤后取回，不把不同渠道
 * 的数字拼成一行；出口跟随顶栏切换的全局偏好（store.realm），页面内不再
 * 放第二套出口切换页签。
 *
 * 页面禁止出现价格字段：接口本身已经没有，这里也不构造。
 */
import { h, ref, computed, onMounted, onUnmounted, watch } from "/vendor/vue.mjs";
import { useStore, ensureBootstrap, rawState, loadPref, savePref, currentRealm as realmOf, realmMeta } from "../store/index.js";
import { usageApi } from "../api/usage.js";
import { panelApi } from "../api/panel.js";
import { ui, ElMessage } from "../components/ui.js";
import { compact, num, pct, ms, fmtK, time, catalogSourceLabel, isoShort } from "../components/format.js";
import MetricCard from "../components/MetricCard.js";
import PageHead from "../components/PageHead.js";
import EmptyState from "../components/EmptyState.js";
import StateBadge from "../components/StateBadge.js";
import WbTable from "../components/WbTable.js";
import { cardHead, errorAlert, badge, rangeButtons, shortChannelLabel, realmBadges, channelSection, refreshAction } from "../components/kit.js";
import { ico } from "../components/icons.js";
import { createPoller } from "../composables/poll.js";

const DASHBOARD_CAPS = new Set(["chat", "models", "responses"]);
const POLL_MS = 30000;

/** 时序补零：后端只返回有流量的日期，面积图需要完整时间窗——
 *  以序列最后一个日期为终点、向前补满 days 天（缺的日期记 0）。 */
function zeroFillSeries(list, days) {
  if (!list.length || !days) return list;
  const byDate = new Map(list.map((d) => [String(d.date || "").slice(0, 10), d]));
  const m = String(list[list.length - 1].date || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return list;
  const end = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(end.getTime() - i * 86400000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.push(byDate.get(key) || {
      date: key, requests: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, errors: 0,
    });
  }
  return out;
}

/** 近 N 日 Token 趋势：零依赖内联 SVG 渐变面积图（B3；悬停看当日明细）。
 *  返回 null = 无序列；{empty:true} = 整个区间全为 0（调用方显示引导空态）。 */
function trendSvg(series, days) {
  const list = zeroFillSeries(series || [], days);
  if (!list.length) return null;
  const sum = list.reduce((acc, d) => acc + (d.total_tokens || 0), 0);
  if (sum <= 0) return { empty: true };
  const W = 880, H = 220, PAD_L = 52, PAD_R = 12, PAD_T = 14, PAD_B = 26;
  const iw = W - PAD_L - PAD_R, ih = H - PAD_T - PAD_B;
  const slot = iw / list.length;
  const maxTok = Math.max(1, ...list.map((d) => d.total_tokens || 0));
  const baseY = PAD_T + ih;
  const px = (i) => PAD_L + i * slot + slot / 2;
  const py = (v) => baseY - (v / maxTok) * ih;
  // 网格、纵轴刻度与底线
  let grid = "";
  [0.5, 1].forEach((f) => {
    const y = baseY - Math.round(ih * f);
    grid += `<line x1="${PAD_L}" y1="${y}" x2="${W - PAD_R}" y2="${y}" class="trend-grid"/>` +
      `<text x="${PAD_L - 8}" y="${y + 3}" text-anchor="end" class="trend-y">${fmtK(Math.round(maxTok * f))}</text>`;
  });
  grid += `<line x1="${PAD_L}" y1="${baseY}" x2="${W - PAD_R}" y2="${baseY}" class="trend-grid"/>` +
    `<text x="${PAD_L - 8}" y="${baseY + 3}" text-anchor="end" class="trend-y">0</text>`;
  // 面积路径（渐变填充）+ 描线
  const pts = list.map((d, i) => `${px(i).toFixed(1)},${py(d.total_tokens || 0).toFixed(1)}`);
  const linePath = `M${pts.join(" L")}`;
  const areaPath = `${linePath} L${px(list.length - 1).toFixed(1)},${baseY} L${px(0).toFixed(1)},${baseY} Z`;
  // 虚线均值线 + 小号等宽标注
  const avg = sum / list.length;
  const avgY = py(avg);
  const avgLine =
    `<line x1="${PAD_L}" y1="${avgY.toFixed(1)}" x2="${W - PAD_R}" y2="${avgY.toFixed(1)}" class="trend-avg"/>` +
    `<text x="${W - PAD_R}" y="${(avgY - 6).toFixed(1)}" text-anchor="end" class="trend-avg-label">日均 ${fmtK(Math.round(avg))}</text>`;
  // 峰值点（实心 + 光环）
  let peakIdx = 0;
  list.forEach((d, i) => { if ((d.total_tokens || 0) > (list[peakIdx].total_tokens || 0)) peakIdx = i; });
  const dot =
    `<circle cx="${px(peakIdx).toFixed(1)}" cy="${py(list[peakIdx].total_tokens || 0).toFixed(1)}" r="7" class="trend-dot-halo"/>` +
    `<circle cx="${px(peakIdx).toFixed(1)}" cy="${py(list[peakIdx].total_tokens || 0).toFixed(1)}" r="3.5" class="trend-dot"/>`;
  // 悬停列（透明，承接当日明细 title）与 x 轴标注
  const labelEvery = list.length <= 10 ? 1 : Math.ceil(list.length / 10);
  let hovers = "";
  list.forEach((d, i) => {
    const value = d.total_tokens || 0;
    const tip = `${d.date}　总 ${num(value)} tok（输入 ${num(d.prompt_tokens)} / 输出 ${num(d.completion_tokens)}）　请求 ${num(d.requests)} 次` +
      (d.errors ? `　失败 ${num(d.errors)} 次` : "");
    hovers += `<rect x="${(PAD_L + i * slot).toFixed(1)}" y="${PAD_T}" width="${slot.toFixed(1)}" height="${ih}" class="trend-hover"><title>${tip.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</title></rect>`;
    if (i % labelEvery === 0 || i === list.length - 1) {
      hovers += `<text x="${px(i).toFixed(1)}" y="${H - 8}" text-anchor="middle" class="trend-x">${String(d.date || "").slice(5)}</text>`;
    }
  });
  // 四套主题各一条面积渐变（accent→accent2 垂直渐变，选择由 CSS data-theme 控制）
  const defs = `<defs>` +
    `<linearGradient id="wbTrendGrad" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="rgba(34,211,238,.34)"/><stop offset="1" stop-color="rgba(79,124,255,.03)"/></linearGradient>` +
    `<linearGradient id="wbTrendGradLight" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="rgba(14,165,233,.34)"/><stop offset="1" stop-color="rgba(79,124,255,.03)"/></linearGradient>` +
    `<linearGradient id="wbTrendGradMidnight" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="rgba(240,168,72,.34)"/><stop offset="1" stop-color="rgba(139,124,246,.03)"/></linearGradient>` +
    `<linearGradient id="wbTrendGradSky" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0" stop-color="rgba(242,166,94,.34)"/><stop offset="1" stop-color="rgba(240,138,160,.03)"/></linearGradient></defs>`;
  let total = 0, reqs = 0, errs = 0;
  list.forEach((d) => {
    total += d.total_tokens || 0;
    reqs += d.requests || 0;
    errs += d.errors || 0;
  });
  return {
    svg: `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" role="img" aria-label="近 ${list.length} 日 Token 用量趋势">` +
      `${defs}${grid}<path d="${areaPath}" class="trend-area"/><path d="${linePath}" class="trend-line"/>` +
      `${avgLine}${dot}${hovers}</svg>`,
    total: num(total), reqs: num(reqs), errs,
    avg: num(Math.round(avg)),
    peak: `${list[peakIdx].date} · ${num(list[peakIdx].total_tokens)}`,
    days: list.length,
  };
}

/** B3：日环比箭头数据（最近一天 vs 前一天）；缺前一天 / 双方全 0 / 持平时不可比。 */
function dayDelta(series, key) {
  const list = series || [];
  if (list.length < 2) return null;
  const cur = Number(list[list.length - 1]?.[key] || 0);
  const prev = Number(list[list.length - 2]?.[key] || 0);
  if (!Number.isFinite(cur) || !Number.isFinite(prev)) return null;
  if (prev === 0 || cur === prev) return null;
  return { up: cur > prev, diff: num(Math.abs(cur - prev)) };
}

export default {
  name: "DashboardView",
  components: { MetricCard, PageHead, EmptyState, StateBadge },
  setup() {
    const store = useStore();
    const loading = ref(false);
    const error = ref("");
    // 区间偏好记忆（T-20）：与出口/主题一样存本机，刷新不回落默认
    const days = ref(loadPref("dashboard.days", 14, [7, 14, 30]));
    /** channelId → {realm → {snapshot, perf, series, recent}} */
    const data = ref({});
    const analytics = ref(null);
    const modelsSource = ref({});

    // 看板 30s 轮询（load 自带 try/catch 不会抛）；页面隐藏或未登录时跳过该轮
    let poller = null;

    const channels = computed(() =>
      (store.channels || []).filter((channel) =>
        (channel.capabilities || []).some((cap) => DASHBOARD_CAPS.has(cap))));

    /** 渠道当前出口 id（统一实现在 store，页面只取 id 串做数据键）。 */
    function currentRealm(channel) {
      return realmOf(channel)?.id || "";
    }

    function channelData(channel) {
      const realm = currentRealm(channel);
      return (data.value[channel.id] || {})[realm] || null;
    }

    async function loadChannel(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      data.value[channel.id] = data.value[channel.id] || {};
      const [snapshot, perf, series, recent] = await Promise.all([
        usageApi.snapshot(realm),
        usageApi.perf(realm),
        usageApi.timeseries(realm, days.value),
        usageApi.recent(realm, 30),
      ]);
      data.value[channel.id][realm] = { snapshot, perf, series, recent };
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        await Promise.all(channels.value.map((channel) => loadChannel(channel)));
        const [analytic, sources] = await Promise.all([
          usageApi.analytics(),
          panelApi.modelsSource(),
        ]);
        analytics.value = analytic;
        modelsSource.value = sources.sources || {};
      } catch (err) {
        error.value = err.message || "看板数据加载失败";
      } finally {
        loading.value = false;
      }
    }

    // 顶栏出口切换 → 看板跟随重载各渠道当前出口的数据
    watch(() => rawState().realm, () => {
      if (!store.authenticated) return;
      channels.value.forEach((channel) => {
        loadChannel(channel).catch((err) => {
          ElMessage.error(err.message || "切换出口失败");
        });
      });
    });

    async function changeDays(value) {
      days.value = value;
      savePref("dashboard.days", value);
      await load();
    }

    onMounted(async () => {
      await ensureBootstrap();
      await load();
      poller = createPoller(() => load(), POLL_MS,
        { guard: () => !document.hidden && store.authenticated });
      poller.start();
    });
    onUnmounted(() => { if (poller) poller.stop(); });

    return {
      store, loading, error, days, analytics, modelsSource,
      channels, channelData, currentRealm, changeDays, load,
      compact, num, pct, ms, fmtK, time, ico,
    };
  },
  methods: {
    kpisOf(channel) {
      const payload = this.channelData(channel);
      if (!payload) return [];
      const { snapshot, perf } = payload;
      const seriesList = payload?.series?.series || [];
      // B3：日环比箭头（最近一天 vs 前一天），可比较时才显示；↑ 绿 / ↓ 红
      const cmp = (delta) => delta
        ? `较前日 <b style="color:${delta.up ? "var(--ok)" : "var(--bad)"}">${delta.up ? "↑" : "↓"} ${delta.diff}</b> · `
        : "";
      const reqDelta = dayDelta(seriesList, "requests");
      const tokDelta = dayDelta(seriesList, "total_tokens");
      // 零请求不伪造数字：成功率/延迟显示 —，foot 写"暂无请求"（T-12）
      const hasTraffic = (snapshot.requests || 0) > 0;
      const errSub = !hasTraffic ? "暂无请求"
        : perf.errors ? `${num(perf.errors)} 次异常拦截（被上游/网关拒绝，未消耗 Token）` : "服务运行平稳";
      return [
        { label: "网关调用量", value: num(snapshot.requests), unit: "次",
          // 与成功率卡同一口径（都含失败请求）；"失败"在 foot 里写清含义，避免两卡数字互斥（T-37）
          foot: hasTraffic
            ? `${cmp(reqDelta)}累计消耗 <b>${compact(snapshot.total_tokens)}</b> Token · 成功 ${num(snapshot.requests - (snapshot.errors || 0))}${snapshot.errors ? ` · 失败 ${num(snapshot.errors)}` : ""}`
            : "发出一次对话请求后开始统计",
          tone: "accent", icon: "pulse" },
        { label: "总 Token", value: hasTraffic ? compact(snapshot.total_tokens) : "—",
          foot: hasTraffic
            ? `${cmp(tokDelta)}输入 ${compact(snapshot.prompt_tokens)} · 输出 ${compact(snapshot.completion_tokens)}`
            : "发出一次对话请求后开始统计",
          tone: "accent2", icon: "db" },
        { label: "请求成功率", value: hasTraffic && perf.success_rate_pct != null
            ? pct(perf.success_rate_pct) : "—",
          foot: errSub, tone: !hasTraffic ? "" : perf.errors ? "warn" : "ok", icon: "shield" },
        { label: "首字延迟 P50", value: hasTraffic ? ms(perf.ttft_ms?.p50) : "—",
          foot: hasTraffic
            ? `P90 ${ms(perf.ttft_ms?.p90)} · 生成 ${ms(perf.generation_ms?.p50)}`
            : "暂无请求",
          tone: "", icon: "bolt", anchor: "var(--ok)" },
      ];
    },
    modelRows(channel) {
      const payload = this.channelData(channel);
      const byModel = payload?.snapshot?.by_model || {};
      return Object.entries(byModel)
        .sort((a, b) => (b[1].total_tokens || 0) - (a[1].total_tokens || 0))
        .map(([model, row]) => ({ model, ...row }));
    },
    trend(channel) {
      const payload = this.channelData(channel);
      return trendSvg(payload?.series?.series, this.days);
    },
    recentRows(channel) {
      const payload = this.channelData(channel);
      const rows = (payload?.recent || {}).rows || [];
      return rows.slice(0, 30);
    },
    sourceText(realm) {
      const info = (this.modelsSource || {})[realm];
      if (!info) return "";
      const label = catalogSourceLabel(info.source);
      const at = info.at ? ` · 更新于 ${time(info.at)}` : "";
      return label + (info.count != null ? ` · ${info.count} 个模型` : "") + at;
    },
    renderChannelMetrics(channel) {
      const payload = this.channelData(channel);
      if (!payload) {
        return h(EmptyState, { text: "该渠道暂无用量数据",
          hint: "发出一次对话请求后这里就会出现统计" });
      }
      const trend = this.trend(channel);
      return h("div", null, [
        h("div", { class: "cards" },
          this.kpisOf(channel).map((kpi, index) =>
            h(MetricCard, { key: kpi.label, ...kpi, class: "stagger",
                            style: { "--d": (index * 0.06) + "s" } }))),
        h("div", { class: "grid c2", style: "margin-top:2px" }, [
          h("div", { class: "card" }, [
            cardHead("模型分布", "按累计 Token 排序", null, "layers"),
            this.modelRows(channel).length
              ? h(WbTable, { rows: this.modelRows(channel), maxHeight: 300, columns: [
                  { prop: "model", label: "模型", minWidth: 170,
                    render: ({ row }) => h("span", { class: "mono" }, row.model) },
                  { label: "请求", width: 90, align: "right", render: ({ row }) => num(row.requests) },
                  { label: "Token", width: 110, align: "right",
                    render: ({ row }) => h("b", { class: "num-strong" }, compact(row.total_tokens)) },
                  { label: "输出", width: 110, align: "right", render: ({ row }) => compact(row.completion_tokens) },
                ] })
              : h(EmptyState, { text: "暂无模型用量", icon: "db" }),
          ]),
          h("div", { class: "card" }, [
            cardHead(`近 ${this.days} 日用量趋势`, "按天聚合 · 悬停查看当日明细", null, "chart"),
            trend && !trend.empty
              ? h("div", null, [
                  h("div", { class: "trend-wrap", innerHTML: trend.svg }),
                  h("div", { class: "trend-legend" }, [
                    h("span", null, [`期间累计 `, h("b", null, trend.total), " tok"]),
                    h("span", null, [`日均 `, h("b", null, trend.avg), " tok"]),
                    h("span", null, [`峰值 `, h("b", null, trend.peak)]),
                    h("span", null, [`请求 `, h("b", null, trend.reqs), " 次"]),
                    trend.errs ? h("span", { style: "color:var(--warn)" },
                      [`失败 `, h("b", null, String(trend.errs)), " 次"]) : null,
                  ]),
                ])
              : h(EmptyState, { text: "当前区间暂无调用", icon: "chart",
                  hint: "这段时间没有真实请求；发出一次对话后这里就会出现趋势" }),
          ]),
        ]),
        h("div", { class: "card" }, [
          cardHead("最近请求", "只列本渠道本出口", null, "pulse"),
          this.recentRows(channel).length
            ? h(WbTable, { rows: this.recentRows(channel), maxHeight: 360, columns: [
                { label: "时间", width: 110, render: ({ row }) => h("span", { class: "mono", title: row.iso },
                    isoShort(row.iso, "")) },
                { label: "模型 / 账号", minWidth: 200, render: ({ row }) => [
                    h("div", null, [
                      h("span", { class: "mono" }, row.model || "-"),
                      h("span", { style: "margin-left:6px" },
                        badge(row.stream ? "流式" : "非流式", row.stream ? "s" : "off")),
                    ]),
                    h("div", { class: "muted mono", style: "font-size:11px" },
                      (row.account || "—").slice(0, 12)),
                  ] },
                { label: "状态", width: 90, render: ({ row }) => h(StateBadge, {
                    status: row.error ? "error" : "ok",
                    label: row.error ? `HTTP ${row.status || ""}` : "成功",
                  }) },
                { label: "Token", width: 100, align: "right",
                  render: ({ row }) => h("b", { class: "num-strong" }, compact(row.total_tokens)) },
                { label: "耗时", width: 100, align: "right", render: ({ row }) => [
                    h("div", null, ms(row.elapsed_ms)),
                    row.ttft_ms != null
                      ? h("div", { class: "muted", style: "font-size:11px" }, `首字 ${ms(row.ttft_ms)}`)
                      : null,
                  ] },
              ] })
            : h(EmptyState, { text: "还没有请求记录", icon: "pulse" }),
        ]),
      ]);
    },
  },
  render() {
    // 渠道/出口/目录来源并入页头，去掉浮在内容上的渠道标题
    const activeChannel = this.channels.find((channel) => this.currentRealm(channel));
    const activeRealmId = activeChannel ? this.currentRealm(activeChannel) : "";
    const activeRealm = activeRealmId ? realmMeta(activeRealmId) : null;
    const pageMeta = activeChannel
      ? [badge(shortChannelLabel(activeChannel.label || activeChannel.id), "info"),
         ...realmBadges(activeChannel, activeRealm)]
      : [];
    if (activeRealm) {
      const source = this.sourceText(activeRealm.id);
      if (source) pageMeta.push(h("span", { class: "page-head-sub" }, source));
    }
    const head = h(PageHead, {
      title: "数据看板",
      desc: "按渠道分块统计代理链路用量与性能；模型清单在「模型清单」页维护",
      icon: "chart",
      meta: pageMeta,
    }, {
      actions: () => [
        ...rangeButtons([7, 14, 30].map((value) => ({ value, label: `${value} 天` })),
          this.days, (value) => this.changeDays(value)),
        refreshAction({ onClick: this.load, loading: this.loading }),
      ],
    });

    if (this.error) {
      return h("div", null, [head, errorAlert(this.error)]);
    }

    if (!this.channels.length) {
      return h("div", null, [
        head,
        h(EmptyState, {
          text: "没有可供看板的渠道",
          hint: "后端注册表没有下发声明了对话或模型目录能力的已启用渠道",
        }),
      ]);
    }

    return h("div", null, [
      head,
      h("div", { class: "channel-sections" },
        this.channels.map((channel) => {
          const realm = this.currentRealm(channel);
          if (!realm) return null; // 全局偏好指向其他渠道：本渠道整块不渲染（§2.2）
          return channelSection(channel.id, [
            this.renderChannelMetrics(channel),
          ]);
        })),
      this.analytics
        ? h("div", { class: "grid c2 page-block" }, [
            h("div", { class: "card" }, [
              cardHead("模型用量排行", "全部渠道汇总", null, "layers"),
              (this.analytics.by_model || []).length
                ? h(WbTable, { rows: (this.analytics.by_model || []).slice(0, 15), maxHeight: 340, columns: [
                    { prop: "model", label: "模型", minWidth: 170,
                      render: ({ row }) => h("span", { class: "mono" }, row.model) },
                    { label: "请求", width: 90, align: "right", render: ({ row }) => num(row.requests) },
                    { label: "Token", width: 110, align: "right",
                      render: ({ row }) => h("b", { class: "num-strong" }, compact(row.total_tokens)) },
                  ] })
                : h(EmptyState, { text: "暂无模型用量", icon: "db" }),
            ]),
            h("div", { class: "card" }, [
              // 这张卡统计的是真实代理请求（与渠道头"目录来源"是两套数据），标题写清楚避免与零流量空态自相矛盾
              cardHead("按出口汇总", "按真实代理请求聚合；目录来源标注同步展示", null, "db"),
              (this.analytics.by_realm || []).length
                ? h(WbTable, { rows: (this.analytics.by_realm || []).map((row) => ({
                    ...row, sourceText: this.sourceText(row.realm),
                  })), columns: [
                    { label: "出口", width: 110, render: ({ row }) => {
                        const meta = realmMeta(row.realm);
                        return badge(meta?.badge || row.realm || "—");
                      } },
                    { label: "请求", width: 90, align: "right", render: ({ row }) => num(row.requests) },
                    { label: "Token", width: 110, align: "right",
                      render: ({ row }) => h("b", { class: "num-strong" }, compact(row.total_tokens)) },
                    { label: "目录来源", minWidth: 180,
                      render: ({ row }) => h("span", { class: "muted" }, row.sourceText || "—") },
                  ] })
                : h(EmptyState, { text: "还没有真实的代理请求",
                    hint: "这里只统计真实对话请求；模型目录本身已在上方渠道块标注", icon: "layers" }),
            ]),
          ])
        : null,
    ]);
  },
};
