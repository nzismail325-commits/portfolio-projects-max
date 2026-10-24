/*
 * panel/views/Models.vue.js —— 模型清单
 *
 * 页面范围（§2.2）：网关当前出口的模型目录，独立于数据看板——看板管用量，
 * 这里管「有哪些模型、规格如何、名单从哪来」。出口跟随顶栏切换的全局偏好。
 *
 * 名单主体来自实时链路（远端产品配置 → 桌面缓存 → 窄端点，300s 自动刷新），
 * 内置快照只兜底；页头「刷新模型清单」强制从上游 API 拉一次（服务端 30s 冷却）。
 * 上下文/输出上限的标注来源（官方目录 / models.dev / 本地缓存 / 实测钳制）
 * 逐模型如实标注，页面不做任何二次推断。
 */
import { h, ref, computed, onMounted, watch } from "/vendor/vue.mjs";
import { useStore, ensureBootstrap, rawState, currentRealmId, realmMeta } from "../store/index.js";
import { panelApi } from "../api/panel.js";
import { ui, ElMessage } from "../components/ui.js";
import { compact, time, catalogSourceLabel, limitSourceLabel } from "../components/format.js";
import PageHead from "../components/PageHead.js";
import EmptyState from "../components/EmptyState.js";
import WbTable from "../components/WbTable.js";
import { cardHead, errorAlert, badge, rangeButtons, refreshAction } from "../components/kit.js";

const CAP_FILTERS = [
  { value: "all", label: "全部" },
  { value: "vision", label: "视觉" },
  { value: "tools", label: "工具" },
  { value: "reasoning", label: "推理" },
  { value: "free", label: "限免" },
];

/** 目录里 0 倍率即官方标记的限免模型；creditBadges 与筛选项共用同一判定。 */
function isFreeRow(row) {
  const value = String(row.credits || "").trim().toLowerCase().replace("x", "");
  return value === "0" || value === "0.00";
}

function matchesFilter(row, filter) {
  if (filter === "all") return true;
  if (filter === "free") return isFreeRow(row);
  const caps = row.capabilities || {};
  return Boolean(caps[filter === "tools" ? "tool_calls" : filter]);
}

export default {
  name: "ModelsView",
  components: { PageHead, EmptyState },
  setup() {
    const store = useStore();
    const loading = ref(false);
    const error = ref("");
    const models = ref([]);
    const source = ref({});
    const catalogBusy = ref(false);
    const query = ref("");
    const capFilter = ref("all");

    /** 模型清单的本地筛选：关键词命中 ID / 名称 / 简介，能力筛选与目录口径一致。 */
    const filteredModels = computed(() => {
      const keyword = query.value.trim().toLowerCase();
      return models.value.filter((row) => {
        if (!matchesFilter(row, capFilter.value)) return false;
        if (!keyword) return true;
        return [row.id, row.name, row.description]
          .some((value) => String(value || "").toLowerCase().includes(keyword));
      });
    });

    /** 当前出口 id：统一实现在 store（跟随顶栏全局偏好，回落全局第一个出口）。 */
    const realmId = computed(() => currentRealmId() || "intl");

    async function load() {
      const realm = realmId.value;
      loading.value = true;
      error.value = "";
      try {
        // 顺序请求：modelsList 会刷新渠道自有出口的来源记录，
        // 并行时 sources 可能先返回旧值，面板就会短暂显示「未加载」。
        const payload = await panelApi.modelsList(realm);
        models.value = payload.data || [];
        const sources = await panelApi.modelsSource();
        source.value = (sources.sources || {})[realm] || {};
      } catch (err) {
        error.value = err.message || "模型清单加载失败";
      } finally {
        loading.value = false;
      }
    }

    /** 手动强制刷新当前出口的模型清单（上游 API，服务端 30s 冷却）。 */
    async function refreshCatalog() {
      catalogBusy.value = true;
      try {
        const out = await panelApi.refreshModels(realmId.value);
        if (out.ok) {
          ElMessage.success(out.msg || "模型清单已更新");
        } else {
          ElMessage.warning(out.msg || "模型清单未更新");
        }
        await load();
      } catch (err) {
        ElMessage.error(err.message || "刷新失败");
      } finally {
        catalogBusy.value = false;
      }
    }

    onMounted(async () => {
      await ensureBootstrap();
      await load();
    });

    // 顶栏出口切换 → 模型清单跟随换目录
    watch(() => rawState().realm, () => {
      if (store.authenticated) load().catch(() => {});
    });

    return {
      store, loading, error, models, source, catalogBusy, realmId,
      query, capFilter, filteredModels,
      load, refreshCatalog, compact, time,
      catalogSourceLabel, limitSourceLabel,
    };
  },
  methods: {
    /** 能力徽标：视觉 / 工具 / 推理（数据来自 /v1/models 的 capabilities 注记）。 */
    abilityBadges(row) {
      const caps = row.capabilities || {};
      const out = [];
      if (caps.vision) out.push(["vision", "视觉"]);
      if (caps.tool_calls) out.push(["tools", "工具"]);
      if (caps.reasoning) out.push(["reasoning", "推理"]);
      return out;
    },
    /** 免费账号不可用（上游 11158 的实测信号）：没有标记不代表可用。 */
    entitlementBadges(row) {
      const ent = row.entitlement;
      if (!ent || Number(ent.code) !== 11158) return [];
      const who = ent.userType ? `user type ${ent.userType}` : "免费账号";
      const when = ent.checked_at ? this.time(ent.checked_at) : "";
      return [badge("免费账号不可用", "warn",
        `上游 ${ent.code} · ${who}${when ? " · " + when : ""} · 仅标记不可用，未标记不代表可用`)];
    },
    /** 官方倍率（与原版面板同口径）：限时免费绿标；会员折后价 ≠ 原价才显示。
     *  倍率一律跟随目录数据（远端目录/内置快照），不写死促销文案。 */
    creditBadges(row) {
      const raw = String(row.credits || "").trim();
      if (isFreeRow(row)) {
        return [badge("限时免费 0.00x", "ok", "官方目录标记为 0 倍率")];
      }
      if (!raw) return [];
      const out = [badge(raw.startsWith("x") ? raw.slice(1) + "x" : raw, "s",
                         "上游积分计价倍率（上游按倍率折算积分扣减）")];
      const member = String(row.member_credits || "").trim();
      if (member && member !== raw) {
        out.push(badge(`会员 ${member.startsWith("x") ? member.slice(1) + "x" : member}`,
                       "ok", "官方折扣数据给出的会员折后倍率"));
      }
      return out;
    },
  },
  render() {
    const page = h(PageHead, {
      title: "模型清单",
      desc: "当前出口可用的模型与规格标注；名单自动跟随上游，也可手动强制刷新",
      icon: "layers",
    }, {
      actions: () => [
        refreshAction({ onClick: this.refreshCatalog, loading: this.catalogBusy,
                        label: "刷新模型清单", primary: true,
                        title: "强制从上游 API 拉取一次（服务端 30 秒冷却）" }),
        h(ui.ElButton, { size: "small", onClick: this.load,
                         loading: this.loading }, "重读本地"),
      ],
    });

    if (this.error) {
      return h("div", null, [page, errorAlert(this.error)]);
    }

    const realm = this.realmId;
    const meta = realmMeta(realm);
    const source = this.source || {};

    const sourceCard = h("div", { class: "card" }, [
      cardHead("目录来源", "名单主体来自实时链路，内置快照只兜底；手动刷新只认上游 API",
        null, "db"),
      h("div", { class: "catalog-sum" }, [
        h("div", { class: "cs-item" }, [
          h("div", { class: "cs-time" }, [
            badge(meta?.badge || realm || "—"),
            meta?.domain ? h("span", { class: "muted", style: "margin-left:8px;font-size:12px" },
              meta.domain) : null,
          ]),
          h("div", { class: "cs-label" }, "当前出口"),
        ]),
        h("div", { class: "cs-item" }, [
          h("div", { class: "cs-num dim", style: "font-size:15px" },
            this.catalogSourceLabel(source.source)),
          h("div", { class: "cs-label" }, "名单来源"),
        ]),
        h("div", { class: "cs-item" }, [
          h("div", { class: "cs-time" }, source.at ? this.time(source.at) : "未加载"),
          h("div", { class: "cs-label" }, "最近更新"),
        ]),
      ]),
    ]);

    const rows = this.filteredModels;
    const table = rows.length
      ? h(WbTable, { rows, maxHeight: 560, stripe: true, columns: [
          { label: "模型", prop: "id", sortable: true, minWidth: 210, render: ({ row }) => h("div", null, [
              h("span", { class: "mono", style: "font-weight:650" }, row.id),
              row.name && row.name !== row.id
                ? h("div", { class: "muted", style: "font-size:11.5px" }, row.name)
                : null,
            ]) },
          { label: "简介", minWidth: 240, render: ({ row }) => h("span", {
              class: "muted", title: row.description || "",
            }, row.description || "—") },
          { label: "上下文上限", prop: "context_length", sortable: true,
            sortMethod: (a, b) => (a.context_length || 0) - (b.context_length || 0),
            width: 150, render: ({ row }) => {
              const src = (row.limit_sources || {}).context;
              return h("div", null, [
                h("b", { class: "num-strong" }, row.context_length ? compact(row.context_length) : "—"),
                h("div", { class: "muted", style: "font-size:11px" },
                  this.limitSourceLabel(src)),
              ]);
            } },
          { label: "最大输出", prop: "max_output_tokens", sortable: true,
            sortMethod: (a, b) => (a.max_output_tokens || 0) - (b.max_output_tokens || 0),
            width: 150, render: ({ row }) => {
              const src = (row.limit_sources || {}).output;
              return h("div", null, [
                h("b", { class: "num-strong" },
                  row.max_output_tokens ? compact(row.max_output_tokens) : "—"),
                h("div", { class: "muted", style: "font-size:11px" },
                  row.output_clamp
                    ? `实测钳制 ${compact(row.output_clamp)}`
                    : this.limitSourceLabel(src)),
              ]);
            } },
          { label: "能力", width: 210, render: ({ row }) => h("div", { style: "display:flex;gap:4px;flex-wrap:wrap" },
              [...this.abilityBadges(row).map(([key, label]) => badge(label)),
               ...this.entitlementBadges(row)]) },
          { label: "消费倍率 / 优惠", width: 160, render: ({ row }) => {
              const badges = this.creditBadges(row);
              return badges.length
                ? h("div", { style: "display:flex;gap:4px;flex-wrap:wrap" }, badges)
                : h("span", { class: "muted" }, "—");
            } },
        ] })
      : this.models.length
        ? h(EmptyState, {
            text: "没有匹配的模型",
            hint: "换一个关键词，或取消当前能力筛选",
            icon: "layers",
          })
        : h(EmptyState, {
            text: "当前出口暂无模型",
            hint: "点「刷新模型清单」从上游拉取，或确认该出口有可用账号",
            icon: "layers",
          });

    const filterBar = h("div", { class: "toolbar", style: "margin-bottom:12px" }, [
      h(ui.ElInput, {
        modelValue: this.query,
        "onUpdate:modelValue": (value) => { this.query = value; },
        clearable: true, placeholder: "搜索模型 ID / 名称 / 简介",
        style: "width:260px",
      }),
      ...rangeButtons(CAP_FILTERS, this.capFilter,
        (value) => { this.capFilter = value; }),
      h("span", { class: "hint", style: "margin-left:auto" },
        `显示 ${rows.length} / ${this.models.length} 个`),
    ]);

    return h("div", null, [
      page,
      sourceCard,
      h("div", { class: "card" }, [filterBar, table]),
    ]);
  },
};
