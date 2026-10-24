/*
 * panel/views/Accounts.vue.js —— 账号治理
 *
 * 页面边界（§2.2）：每个渠道一块，块内只渲染该渠道自己的出口与账号；
 * 出口跟随顶栏切换的全局偏好（store.realm）——切换到哪个出口就只显示
 * 哪个出口的账号，绝不把不同出口的账号拼进同一页；
 * 操作按钮只对「该渠道注册了该能力」的账号渲染——
 *   签到/领取 → 渠道声明 checkin 且账号 canCheckin（文案按渠道元数据）
 *   每日活跃 → 渠道声明 daily_chat 且账号 canDailyChat
 *   代理槽 → 渠道声明 proxy_slot
 *   登录   → 渠道声明 accounts
 * 未注册渠道整块不出现，不留死入口。
 */
import { h, ref, computed, onMounted, onUnmounted, watch, nextTick } from "/vendor/vue.mjs";
import { useStore, ensureBootstrap, rawState, currentRealm as realmOf } from "../store/index.js";
import { channelsApi } from "../api/channels.js";
import { accountsApi, proxySlotApi } from "../api/accounts.js";
import { ui, ElMessage, ElMessageBox } from "../components/ui.js";
import { num, duration, ago, nowUnix } from "../components/format.js";
import PageHead from "../components/PageHead.js";
import EmptyState from "../components/EmptyState.js";
import StateBadge from "../components/StateBadge.js";
import WbTable, { actionRow, actionWidth } from "../components/WbTable.js";
import { cardHead, errorAlert, badge, channelMeta, channelSection, confirmAction, copyText } from "../components/kit.js";
import { createPoller } from "../composables/poll.js";

const ACCOUNT_CAPS = new Set(["accounts"]);
const MONO_FONT = 'ui-monospace, "Cascadia Mono", Consolas, monospace';

/** 账号行状态：护栏判定全用后端已给的字段，页面不猜。 */
function accountState(row) {
  if (!row.enabled) return { status: "disabled", text: "已停用" };
  if (row.isExpired) return { status: "expired", text: "已过期" };
  if (row.balanceFor > 0) return { status: "parked", text: "余额不足停车" };
  if (row.breakerFor > 0) return { status: "error", text: `熔断 ${duration(row.breakerFor)}` };
  if (row.degradeFor > 0) return { status: "warn", text: `降级 ${duration(row.degradeFor)}` };
  if (row.inCooldown) return { status: "cooling", text: `冷却 ${duration(row.cooldownFor)}` };
  if (row.unavailable) return { status: "warn", text: row.unavailable };
  return { status: "ready", text: "可用" };
}

/** 账号行显示名：登录身份（邮箱/手机号）优先，昵称只在没有身份时兜底。 */
function accountLabel(row) {
  return row.loginAccount || row.nickname || (row.uid || "").slice(0, 8) || "?";
}

/** 签到/领取/打卡徽标：签到类看 lastCheckin（文案由渠道元数据下发），
 *  国际版看每日活跃打卡（lastDailyChat）。
 *  本地记录是「YYYY-MM-DD HH:MM:SS」，按本地日历日比对，落在今天就算完成
 *  （与原版面板同口径）；两类都不适用的账号不出。 */
function dailyBadge(row, channel) {
  const today = new Date().toLocaleDateString("sv-SE");
  if (row.canCheckin) {
    const labels = channelsApi.checkinLabels(channel);
    return String(row.lastCheckin || "").slice(0, 10) === today
      ? { label: labels.done, tone: "ok", title: labels.doneTitle + row.lastCheckin }
      : { label: labels.pending, tone: "off", title: labels.pendingTitle };
  }
  if (row.canDailyChat) {
    return row.lastDailyChat && String(row.lastDailyChat).slice(0, 10) === today
      ? { label: "已打卡", tone: "ok", title: "今日已打卡：" + row.lastDailyChat }
      : { label: "未打卡", tone: "off", title: "今日尚未打卡（任务与福利页可手动执行或等定时巡检）" };
  }
  return null;
}

/** 会员档位胶囊：直接显示计费摘要里的套餐名（Free / 体验版 / 付费包名），
 *  悬停给出读取时刻。没查过摘要就不画——不猜档位，也不把「没查过」画成免费。 */
function tierBadge(tier) {
  if (!tier || typeof tier !== "object") return null;
  const name = String(tier.package || "").trim() || (tier.paid ? "付费" : "Free");
  const when = tier.checked_at
    ? new Date(tier.checked_at * 1000).toLocaleString() : "";
  return badge(name, tier.paid ? "ok" : "off",
    `会员档位读自计费摘要${when ? `（${when}）` : ""}`);
}

export default {
  name: "AccountsView",
  components: { PageHead, EmptyState, StateBadge },
  setup() {
    const store = useStore();
    const loading = ref(false);
    const error = ref("");
    /** "channelId|realm" → 账号数组（只缓存当前出口） */
    const accounts = ref({});
    /** "channelId|realm" → 该出口的代理槽（槽按出口归属，卡片只列本出口的） */
    const slotsByKey = ref({});
    /** "channelId|realm" → 自动保存状态：saving / saved / error */
    const slotSaveState = ref({});
    /** 正在探测的代理地址 */
    const slotProbing = ref({});
    const slotsLoading = ref(false);
    // 同一出口的保存串行执行；写盘期间的新改动合并到下一轮，只落最新快照
    const slotSaveChains = {};
    const slotSavePending = {};
    const slotSaveTimers = {};

    // 凭据导入对话框
    const importOpen = ref(false);
    const importCandidates = ref([]);
    const importBusy = ref(false);

    // 登录弹窗：OAuth 走 2.5s 轮询；表单类登录（如短信验证码）由渠道
    // 在 start_login 里声明 form，面板只按字段/动作渲染，不写死渠道协议。
    const loginDialog = ref({
      open: false, channelId: "", realm: "", state: "", authUrl: "",
      status: "", paste: false, callback: "", form: null, values: {},
      busy: false, busyAction: "",
    });
    let loginPoller = null;
    /** 每次发起/关闭登录递增；关闭后迟到的发起响应不得再把弹窗打开。 */
    let loginEpoch = 0;
    /** 身份同步同一时间只跑一轮，避免切换出口/刷新时叠加请求。 */
    let identitySyncRunning = false;

    // 额度明细弹窗
    const creditsOpen = ref(false);
    const creditsView = ref(null);

    const channels = computed(() =>
      (store.channels || []).filter((channel) =>
        (channel.capabilities || []).some((cap) => ACCOUNT_CAPS.has(cap))));

    function key(channelId, realm) {
      return `${channelId}|${realm}`;
    }

    /** 当前出口对象：统一实现在 store（跟随顶栏全局偏好，未命中回落第一个出口）。 */
    function currentRealm(channel) {
      return realmOf(channel);
    }

    function rowsOf(channelId, realm) {
      return accounts.value[key(channelId, realm)] || [];
    }

    function supports(channel, cap) {
      return channelsApi.supports(channel, cap);
    }

    async function loadChannel(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const payload = await accountsApi.list(realm.id);
      accounts.value = {
        ...accounts.value,
        [key(channel.id, realm.id)]: payload.accounts || [],
      };
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        await Promise.all(channels.value.map((channel) => loadChannel(channel)));
        await Promise.all(channels.value
          .filter((channel) => supports(channel, "proxy_slot"))
          .map((channel) => loadSlots(channel)));
      } catch (err) {
        error.value = err.message || "账号数据加载失败";
      } finally {
        loading.value = false;
      }
      if (!error.value) syncPendingIdentities();
    }

    /** 老账号只有昵称时，各渠道尽力补一次登录身份（邮箱/手机号）。 */
    async function syncPendingIdentities() {
      if (identitySyncRunning) return;
      identitySyncRunning = true;
      try {
        for (const channel of channels.value) {
          const realm = currentRealm(channel);
          if (!realm) continue;
          const rows = rowsOf(channel.id, realm.id)
            .filter((row) => row.identityPending);
          if (!rows.length) continue;
          let changed = false;
          for (const row of rows) {
            try {
              const payload = await accountsApi.syncIdentity(row.uid);
              if (payload && payload.ok && payload.loginAccount) changed = true;
            } catch (err) { /* 同步失败不打扰用户；下次加载再试 */ }
          }
          if (changed) await refreshChannel(channel);
        }
      } finally {
        identitySyncRunning = false;
      }
    }

    /** 拉取某渠道当前出口的代理槽（槽按出口归属，只加载本出口的）。 */
    async function loadSlots(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const k = key(channel.id, realm.id);
      // 自动保存进行中：等它回写，别拿写盘前的快照覆盖本地最新改动
      if (slotSavePending[k] || slotSaveState.value[k] === "saving") return;
      slotsLoading.value = true;
      try {
        const payload = await proxySlotApi.list(realm.id);
        // _probeUrl 记住探测信息对应的地址：地址改动后旧的出口信息不再展示
        slotsByKey.value = {
          ...slotsByKey.value,
          [k]: (payload.slots || []).map((slot) => ({
            ...slot,
            _probeUrl: slot.ip ? slot.url : "",
          })),
        };
      } finally {
        slotsLoading.value = false;
      }
    }

    function slotsOf(channelId, realm) {
      return slotsByKey.value[key(channelId, realm)] || [];
    }

    function slotSaveStateOf(channelId, realm) {
      return slotSaveState.value[key(channelId, realm)] || "";
    }

    /** 当前出口生效中的代理槽：已归属本出口且启用的第一条（与后端同口径，
     *  多条启用取第一条）；未分配的旧版全局槽不生效。 */
    function activeSlotOf(channelId, realm) {
      return slotsOf(channelId, realm).find(
        (slot) => slot.realm && slot.enabled !== false) || null;
    }

    async function refreshChannel(channel) {
      await loadChannel(channel);
    }

    async function runAction(channel, account, action, extra = {}, successText = "") {
      try {
        const payload = await accountsApi.action(account.uid, action, extra);
        if (payload && payload.ok === false) {
          ElMessage.warning(payload.msg || payload.message || payload.error || "操作未成功");
        } else {
          ElMessage.success(payload.message || successText || "已提交");
        }
        await refreshChannel(channel);
        return payload;
      } catch (err) {
        ElMessage.error(err.message || "操作失败");
        return null;
      }
    }

    async function toggleEnabled(channel, account) {
      await runAction(channel, account, "enable", { enabled: !account.enabled },
        account.enabled ? "已停用" : "已启用");
    }

    async function editWeight(channel, account) {
      try {
        const result = await ElMessageBox.prompt("数字越大越优先接单（1-100）", "调度权重", {
          inputValue: String(account.weight ?? 1),
          inputPattern: /^(100|[1-9][0-9]?)$/,
          inputErrorMessage: "请输入 1-100 的整数",
        });
        await runAction(channel, account, "weight", { weight: Number(result.value) }, "权重已更新");
      } catch (err) {
        if (err !== "cancel" && err !== "close") ElMessage.error(err.message || "操作失败");
      }
    }

    async function editModels(channel, account) {
      try {
        const result = await ElMessageBox.prompt(
          "模型名用逗号分隔；留空表示不禁用任何模型。人工名单与自动冷却互不影响。",
          "禁用模型名单", {
            inputValue: (account.disabledModels || []).join(","),
          });
        const models = String(result.value || "")
          .split(",").map((item) => item.trim()).filter(Boolean);
        await runAction(channel, account, "disabled_models", { models },
          models.length ? "禁用名单已保存" : "禁用名单已清空");
      } catch (err) {
        if (err !== "cancel" && err !== "close") ElMessage.error(err.message || "操作失败");
      }
    }

    async function removeAccount(channel, account) {
      const ok = await confirmAction(
        `确定删除账号 ${accountLabel(account)}？该账号的本地凭据文件会一并删除。`,
        "删除账号", { type: "warning" });
      if (!ok) return;
      await runAction(channel, account, "delete", {}, "账号已删除");
    }

    async function refreshCredits(realm) {
      try {
        ElMessage.info("正在刷新账号余额…");
        await accountsApi.credits(realm, true);
        ElMessage.success("余额已刷新");
        await load();
      } catch (err) {
        ElMessage.error(err.message || "刷新失败");
      }
    }

    /** 全部启用/停用（原版面板同款）：后端无批量接口，逐个调用现有启停接口，
     *  完成后统一刷新一次；全部停用会直接影响网关可用账号，需轻确认。 */
    async function setAllEnabled(channel, realm, enable) {
      const rows = rowsOf(channel.id, realm.id).filter((row) => row.enabled !== enable);
      if (!rows.length) {
        ElMessage.info(enable ? "当前出口的账号全部处于启用状态" : "当前出口没有已启用的账号");
        return;
      }
      if (!enable) {
        const ok = await confirmAction(
          `将停用当前共 ${rows.length} 个已启用账号，网关请求将只走剩余账号，确定全部停用？`,
          "全部停用",
          { confirmButtonText: "全部停用", cancelButtonText: "取消", type: "warning" });
        if (!ok) return; // 取消 / Esc
      }
      let done = 0;
      for (const row of rows) {
        try {
          const payload = await accountsApi.setEnabled(row.uid, enable);
          if (payload && payload.ok === false) {
            ElMessage.warning(payload.msg || payload.error || `${accountLabel(row)} 操作未成功`);
          } else {
            done += 1;
          }
        } catch (err) {
          ElMessage.error(`${accountLabel(row)}：${err.message || "操作失败"}`);
        }
      }
      ElMessage.success(enable ? `已启用 ${done} 个账号` : `已停用 ${done} 个账号`);
      await refreshChannel(channel);
    }

    async function showCredits(account) {
      try {
        const payload = await accountsApi.creditsDetail(account.uid, true);
        creditsView.value = payload || {};
        creditsOpen.value = true;
      } catch (err) {
        ElMessage.error(err.message || "额度读取失败");
      }
    }

    async function startLogin(channel, realm) {
      const epoch = ++loginEpoch;
      try {
        const info = await accountsApi.loginStart(realm);
        // 关闭弹窗（或另一次发起）后，迟到的响应不能再把窗口弹开
        if (epoch !== loginEpoch) return false;
        // 后端明确失败（如 ZCode 登录初始化失败）时直接报原因：不开没有
        // 授权链接的「等待授权」死对话框，也不静默吞掉 message
        if (info && info.ok === false) {
          ElMessage.error(info.message || "登录发起失败");
          return false;
        }
        const authUrl = (info && (info.authUrl || info.url)) || "";
        const form = info && info.form && typeof info.form === "object"
          ? info.form : null;
        if (!authUrl && !form) {
          ElMessage.error((info && info.message) || "登录发起失败：没有取到授权地址");
          return false;
        }
        loginDialog.value = {
          open: true, channelId: channel.id, realm,
          state: info.state || "", authUrl,
          status: form ? "" : (info.hint || "等待浏览器完成授权…"),
          // 粘贴回调入口由后端声明（渠道登录流携带 paste 标记），前端不猜
          paste: Boolean(info.paste), callback: "",
          form, values: {}, busy: false, busyAction: "",
        };
        if (loginPoller) {
          loginPoller.stop();
          loginPoller = null;
        }
        if (form) return true; // 表单类登录不需要轮询，动作结果由提交响应返回
        loginPoller = createPoller(() => pollLogin(channel, realm), 2500);
        loginPoller.start();
        window.open(authUrl, "_blank", "noopener");
        return true;
      } catch (err) {
        if (epoch === loginEpoch) ElMessage.error(err.message || "无法开始登录");
        return false;
      }
    }

    /** 表单类登录的统一动作入口：发码 / 提交都由适配器解释 action 名。 */
    async function runLoginAction(action) {
      const dialog = loginDialog.value;
      if (!dialog.form || !dialog.state || dialog.busy) return;
      loginDialog.value = { ...dialog, busy: true, busyAction: action };
      try {
        const result = await accountsApi.loginAction(
          dialog.state, action, { ...(dialog.values || {}) });
        if (action === dialog.form.sendAction) {
          loginDialog.value = {
            ...loginDialog.value, busy: false, busyAction: "",
            status: (result && result.message) || "验证码已发送",
          };
          if (result && result.ok === false) {
            ElMessage.error(result.message || "发送验证码失败");
          }
          return;
        }
        if (result && result.ok) {
          stopLogin(true);
          ElMessage.success(result.message || "账号已登录并加入账号池");
          const channel = store.channels.find((item) => item.id === dialog.channelId);
          await refreshChannel(channel);
          try {
            await accountsApi.credits(dialog.realm, true);
            await refreshChannel(channel);
          } catch (err) { /* 静默补齐失败不打扰 */ }
        } else {
          loginDialog.value = {
            ...loginDialog.value, busy: false, busyAction: "",
            status: (result && result.message) || "登录失败",
          };
        }
      } catch (err) {
        loginDialog.value = {
          ...loginDialog.value, busy: false, busyAction: "",
          status: err.message || "登录失败",
        };
      }
    }

    /** 关闭登录弹窗：取消后端会话，释放回环端口与轮询，并真正关闭弹窗。 */
    function closeLogin() {
      const dialog = loginDialog.value;
      loginEpoch += 1;
      if (dialog.state) {
        accountsApi.loginCancel(dialog.state).catch(() => {});
      }
      stopLogin(true);
    }

    /** 授权链接失效/超时后重新生成：先取消旧会话，再走一次登录发起。 */
    async function restartLogin() {
      const dialog = loginDialog.value;
      if (dialog.busy) return;
      const channel = store.channels.find((item) => item.id === dialog.channelId);
      if (!channel) return;
      loginDialog.value = {
        ...dialog, busy: true, authUrl: "", state: "", callback: "",
        status: "正在重新生成授权链接…",
      };
      if (dialog.state) {
        accountsApi.loginCancel(dialog.state).catch(() => {});
      }
      stopLogin(false);
      const ok = await startLogin(channel, dialog.realm);
      if (!ok) {
        loginDialog.value = {
          ...loginDialog.value, busy: false,
          status: "重新生成失败，请关闭后重试",
        };
      }
    }

    /** 手动粘贴回调地址（渠道声明 paste 能力时的兜底：服务器部署 / 回环端口打不通）。 */
    async function submitLoginCallback() {
      const dialog = loginDialog.value;
      if (!dialog.callback || !dialog.state) return;
      try {
        const result = await accountsApi.loginSubmit(dialog.state, dialog.callback);
        if (result && result.ok) {
          loginDialog.value = { ...dialog, status: result.message || "登录成功" };
          stopLogin(true);
          ElMessage.success(result.message || "账号已登录并加入账号池");
          // 与轮询路径同款收尾：重拉账号 + 静默补余额
          const channel = store.channels.find((item) => item.id === dialog.channelId);
          await refreshChannel(channel);
          try {
            await accountsApi.credits(dialog.realm, true);
            await refreshChannel(channel);
          } catch (err) { /* 静默补齐失败不打扰 */ }
        } else {
          loginDialog.value = { ...dialog, status: (result && result.message) || "回调内容未通过校验" };
        }
      } catch (err) {
        loginDialog.value = { ...dialog, status: err.message || "提交失败" };
      }
    }

    async function pollLogin(channel, realm) {
      const state = loginDialog.value.state;
      if (!state) return;
      try {
        const result = await accountsApi.loginPoll(state);
        const status = result.status || "";
        if (status === "ok") {
          stopLogin(true);
          ElMessage.success(result.message || "账号已登录并加入账号池");
          // 与原版面板同款收尾：重拉账号 + 静默补一次余额（换发型渠道顺带
          // 完成首次换发），表格徽标与「签到」按钮即时完整，不必手动刷新
          await refreshChannel(channel);
          try {
            await accountsApi.credits(realm, true);
            await refreshChannel(channel);
          } catch (err) { /* 静默补齐失败不打扰 */ }
        } else if (status === "error" || status === "expired" || status === "unknown") {
          loginDialog.value = { ...loginDialog.value, status: result.message || "登录失败" };
          stopLogin(false);
        } else {
          loginDialog.value = { ...loginDialog.value, status: result.message || "等待授权…" };
        }
      } catch (err) {
        loginDialog.value = { ...loginDialog.value, status: err.message || "轮询失败" };
      }
    }

    function stopLogin(done) {
      if (loginPoller) {
        loginPoller.stop();
        loginPoller = null;
      }
      if (done) loginDialog.value = { ...loginDialog.value, open: false };
    }

    async function openImport() {
      importBusy.value = true;
      try {
        const payload = await accountsApi.scanDesktop();
        importCandidates.value = payload.candidates || [];
        importOpen.value = true;
      } catch (err) {
        ElMessage.error(err.message || "扫描本机凭据失败");
      } finally {
        importBusy.value = false;
      }
    }

    async function importCandidate(candidate) {
      importBusy.value = true;
      try {
        await accountsApi.importDesktop({ import: true, path: candidate.path,
                                          realm: candidate.realm || null });
        ElMessage.success("已导入本机凭据");
        importOpen.value = false;
        await load();
      } catch (err) {
        ElMessage.error(err.message || "导入失败");
      } finally {
        importBusy.value = false;
      }
    }

    // ---- 代理槽（出口级：每张渠道卡只列自己当前出口的槽；改动即时保存）----
    function setSlotSaveState(k, state) {
      const next = { ...slotSaveState.value };
      if (state) next[k] = state; else delete next[k];
      slotSaveState.value = next;
    }

    function flashSlotSaved(k) {
      setSlotSaveState(k, "saved");
      clearTimeout(slotSaveTimers[k]);
      slotSaveTimers[k] = setTimeout(() => {
        delete slotSaveTimers[k];
        if (slotSaveState.value[k] === "saved") setSlotSaveState(k, "");
      }, 1800);
    }

    /** 把服务端回写的 id/归属并回本地行；不整体替换，避免打断另一行正在输入的内容。
     *  只并入 id/realm：保存期间的开关、地址改动以本地为准，不能被旧响应回滚。 */
    function mergeSavedSlots(k, saved) {
      const byUrl = new Map((saved || []).map(
        (entry) => [String(entry.url || "").trim(), entry]));
      slotsByKey.value = {
        ...slotsByKey.value,
        [k]: (slotsByKey.value[k] || []).map((row) => {
          const hit = byUrl.get(String(row.url || "").trim());
          return hit ? { ...row, id: hit.id, realm: hit.realm } : row;
        }),
      };
    }

    /** 自动保存：同出口串行写盘；写盘期间的新改动合并到下一轮，只落最新快照。
     *  realm 缺省取当前出口；异步操作应在发起时捕获出口并显式传入。 */
    function scheduleSlotSave(channel, realm = currentRealm(channel)) {
      if (!realm) return;
      const k = key(channel.id, realm.id);
      slotSavePending[k] = true;
      clearTimeout(slotSaveTimers[k]);
      delete slotSaveTimers[k];
      setSlotSaveState(k, "saving");
      slotSaveChains[k] = (slotSaveChains[k] || Promise.resolve()).then(async () => {
        if (!slotSavePending[k]) return;
        slotSavePending[k] = false;
        const snapshot = slotsOf(channel.id, realm.id)
          // 空地址是刚点「新增槽位」还没填的草稿：不落盘，填好地址后再保存
          .filter((slot) => String(slot.url || "").trim())
          .map(({ _probeUrl, _focus, ...slot }) => slot);
        try {
          const payload = await proxySlotApi.save(realm.id, snapshot);
          mergeSavedSlots(k, payload.slots || []);
          if (!slotSavePending[k]) flashSlotSaved(k);
        } catch (err) {
          // 保存期间又有新改动：留给下一轮重试，不拿旧响应覆盖
          if (slotSavePending[k]) return;
          setSlotSaveState(k, "error");
          ElMessage.error(`代理槽保存失败，已恢复服务器上的配置${err.message ? `：${err.message}` : ""}`);
          try { await loadSlots(channel); } catch (e) { /* 刷新失败时保留错误标记 */ }
        }
      });
    }

    /** 手动刷新：重读服务器状态，并清掉上一次自动保存的结果标记。 */
    async function refreshSlots(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      try {
        await loadSlots(channel);
        setSlotSaveState(key(channel.id, realm.id), "");
      } catch (err) {
        ElMessage.error(err.message || "代理槽加载失败");
      }
    }

    /** 新增槽位：先落一行空草稿并聚焦地址框，填好失焦/回车即自动保存。 */
    function addSlot(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const k = key(channel.id, realm.id);
      const rows = slotsOf(channel.id, realm.id);
      const empty = rows.find((row) => !String(row.url || "").trim());
      if (empty) {
        // 已有空草稿：不再加一行，把焦点送回地址框
        slotsByKey.value = { ...slotsByKey.value, [k]: rows.slice() };
      } else {
        const draft = { id: "", name: "", url: "", enabled: true };
        slotsByKey.value = {
          ...slotsByKey.value,
          [k]: [...rows, draft],
        };
      }
      nextTick(() => {
        const inputs = [...document.querySelectorAll(".slot-list .slot-url-input input")];
        const target = inputs.find((input) => !input.value.trim())
          || inputs[inputs.length - 1];
        if (target) target.focus();
      });
    }

    /** 空草稿离开焦点就收回：没填地址的行本来也不会落盘，不留在列表里占位。 */
    function abandonDraft(channel, row) {
      if (row.id || String(row.url || "").trim()) return;
      const realm = currentRealm(channel);
      if (!realm) return;
      const k = key(channel.id, realm.id);
      const rows = slotsOf(channel.id, realm.id);
      if (!rows.includes(row)) return;
      slotsByKey.value = {
        ...slotsByKey.value,
        [k]: rows.filter((item) => item !== row),
      };
    }

    /** 地址失焦/回车提交：校验后即时保存；地址变了，旧探测信息不再展示。 */
    async function commitSlotUrl(channel, row) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const rows = slotsOf(channel.id, realm.id);
      if (!rows.includes(row)) return;
      const url = String(row.url || "").trim();
      if (!url) {
        // 还没保存过的空草稿：收回即可，不必拿服务器状态覆盖整个列表
        if (!row.id) {
          const k = key(channel.id, realm.id);
          slotsByKey.value = {
            ...slotsByKey.value,
            [k]: rows.filter((item) => item !== row),
          };
          return;
        }
        ElMessage.warning("代理地址不能为空，已恢复原值");
        await refreshSlots(channel);
        return;
      }
      if (rows.some((other) => other !== row && String(other.url || "").trim() === url)) {
        ElMessage.warning("该代理地址已在槽位中，已恢复原值");
        await refreshSlots(channel);
        return;
      }
      row.url = url;
      // 地址换了，旧的出口识别和自动命名（国家 · IP）都不再对应当前地址
      row.name = "";
      row.ip = "";
      row.country = "";
      row.country_code = "";
      row.ip_type = "";
      row.isp = "";
      row.asn = "";
      row.probed_at = 0;
      row._probeUrl = "";
      scheduleSlotSave(channel, realm);
    }

    function toggleSlot(channel, row, value) {
      const realm = currentRealm(channel);
      if (!realm) return;
      row.enabled = value !== false;
      scheduleSlotSave(channel, realm);
    }

    async function probeSlot(channel, slot) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const url = String(slot.url || "").trim();
      if (!url) {
        ElMessage.warning("先填代理地址");
        return;
      }
      if (slotProbing.value[url]) return;
      slotProbing.value = { ...slotProbing.value, [url]: true };
      try {
        const result = await proxySlotApi.probe(url);
        // 探测期间切了出口或删了该行：结果不落到已不可见的槽上
        const stillHere = currentRealm(channel)?.id === realm.id
          && slotsOf(channel.id, realm.id).includes(slot);
        if (!stillHere) return;
        if (result.ok) {
          ElMessage.success(`出口 ${result.exit_ip || "?"} · ${result.country || "未知地区"} · ${result.latency_ms} ms`);
          slot.ip = result.exit_ip;
          slot.country = result.country;
          slot.country_code = result.country_code;
          slot.ip_type = result.ip_type;
          slot.isp = result.isp;
          slot.asn = result.asn;
          slot.probed_at = nowUnix();
          slot._probeUrl = url;
          scheduleSlotSave(channel, realm);
        } else {
          ElMessage.error(result.error || "探测失败");
        }
      } catch (err) {
        ElMessage.error(err.message || "探测失败");
      } finally {
        const next = { ...slotProbing.value };
        delete next[url];
        slotProbing.value = next;
      }
    }

    async function removeSlot(channel, row) {
      const realm = currentRealm(channel);
      if (!realm) return;
      const rows = slotsOf(channel.id, realm.id);
      if (!rows.includes(row)) return;
      if (activeSlotOf(channel.id, realm.id) === row) {
        const ok = await confirmAction(
          "该槽正在为本出口全部账号提供代理；删除后账号会改用下一条启用的槽，没有则直连。",
          "删除生效中的代理槽？",
          { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" });
        if (!ok) return;
      }
      const k = key(channel.id, realm.id);
      slotsByKey.value = {
        ...slotsByKey.value,
        [k]: rows.filter((item) => item !== row),
      };
      // 空草稿从未落盘，删除它不需要请求服务器
      if (String(row.url || "").trim()) scheduleSlotSave(channel, realm);
    }

    /** 批量探测本机 mihomo 槽位端口段，把可达出口并入当前出口并即时保存（去重）。 */
    async function discoverSlots(channel) {
      const realm = currentRealm(channel);
      if (!realm) return;
      try {
        ElMessage.info("正在探测本机 mihomo 槽位…");
        const payload = await proxySlotApi.discover();
        const found = (payload.slots || []).filter((item) => item.reachable);
        if (!found.length) {
          ElMessage.warning("没有发现可达的 mihomo 槽位出口");
          return;
        }
        const known = new Set(
          slotsOf(channel.id, realm.id).map((slot) => slot.url).filter(Boolean));
        const additions = found
          .filter((item) => !known.has(item.url))
          .map((item) => ({
            id: "", name: item.country ? `${item.country} · ${item.exit_ip || ""}` : "",
            url: item.url, enabled: true,
            ip: item.exit_ip, country: item.country, country_code: item.country_code,
            ip_type: item.ip_type, isp: item.isp, asn: item.asn,
            probed_at: nowUnix(), _probeUrl: item.url,
          }));
        if (!additions.length) {
          ElMessage.info(`发现 ${found.length} 个可达出口，均已在槽位中`);
          return;
        }
        const k = key(channel.id, realm.id);
        slotsByKey.value = {
          ...slotsByKey.value,
          [k]: [...slotsOf(channel.id, realm.id), ...additions],
        };
        scheduleSlotSave(channel, realm);
        ElMessage.success(`发现 ${found.length} 个可达出口，新增 ${additions.length} 个（已自动保存）`);
      } catch (err) {
        ElMessage.error(err.message || "发现槽位失败");
      }
    }

    onUnmounted(() => {
      if (loginPoller) loginPoller.stop(); // 离开页面不再空转轮询授权状态
      Object.values(slotSaveTimers).forEach((timer) => clearTimeout(timer));
    });

    onMounted(async () => {
      await ensureBootstrap();
      await load();
    });

    // 顶栏出口切换 → 账号页跟随刷新，只加载当前出口
    watch(() => rawState().realm, () => {
      if (store.authenticated) load();
    });

    return {
      store, loading, error, channels, slotsLoading,
      importOpen, importCandidates, importBusy, loginDialog,
      creditsOpen, creditsView,
      currentRealm, rowsOf, slotsOf, slotSaveStateOf, slotProbing,
      activeSlotOf,
      supports, load, loadSlots, refreshSlots,
      setAllEnabled, submitLoginCallback,
      runAction, toggleEnabled, editWeight, editModels, removeAccount, showCredits,
      refreshCredits, startLogin, stopLogin, runLoginAction, closeLogin,
      restartLogin,
      openImport, importCandidate,
      addSlot, commitSlotUrl, abandonDraft, toggleSlot, probeSlot, removeSlot, discoverSlots,
      num, duration, ago, accountState,
    };
  },
  methods: {
    /** 复制登录账号（邮箱/手机号），方便直接拿去登录。 */
    async copyAccount(row) {
      const value = accountLabel(row);
      if (!value) return;
      if (await copyText(value)) ElMessage.success("登录账号已复制");
      else ElMessage.warning("复制失败，请手动选择复制");
    },
    /** 额度条（明细弹窗与账号表格两处共用）：remain/size → [数字行, 进度条]。
     *  barWidth 控制条宽（弹窗 160 / 表格 120）；inDialog 表达两处既有差异——
     *  弹窗口径：span 数字行、分母恒显示、条恒渲染、条 margin-top 4px；
     *  表格口径：div 数字行 + num-strong、无 size 不画分母、ratio 为空不画条、
     *  条 margin-top 5px。参数只为保真还原两处原样，不做视觉统一。 */
    renderCreditBar(remain, size, barWidth, inDialog) {
      // remain = -1 是渠道上报的「不限量」哨兵：不画条，直接给徽标
      if (remain === -1 || remain === "-1") {
        return [h("span", null, badge("不限量", "ok", "该账号额度不限量"))];
      }
      const ratio = size > 0 ? remain / size : null;
      const ratioPct = ratio == null ? 0 : Math.max(2, Math.round(ratio * 100));
      const barBg = ratio != null && ratio <= 0.1 ? "var(--bad)"
        : ratio != null && ratio <= 0.3 ? "var(--warn)" : "var(--accent-grad)";
      const numRow = h(inDialog ? "span" : "div", null, [
        h("b", inDialog ? { style: "color:var(--accent-2)" }
                        : { class: "num-strong", style: "color:var(--accent-2)" }, num(remain)),
        (!inDialog && !size) ? null : h("span", { class: "muted" }, ` / ${num(size)}`),
      ]);
      const bar = (!inDialog && ratio == null) ? null
        : h("div", { class: "credit-bar", style: `width:${barWidth}px;margin-top:${inDialog ? 4 : 5}px` },
            h("div", { style: { width: ratioPct + "%", background: barBg } }));
      return [numRow, bar];
    },
    /** 额度明细：汇总块 + 额度包表格（超出部分表格内滚动，不撑破弹窗）。 */
    /** 通用表单登录：字段、按钮文案与动作名全部来自渠道声明。 */
    renderLoginForm() {
      const form = this.loginDialog.form || {};
      const values = this.loginDialog.values || {};
      const fields = form.fields || [];
      const busy = this.loginDialog.busy;
      const busyAction = this.loginDialog.busyAction || "";
      const setValue = (key, value) => {
        this.loginDialog = {
          ...this.loginDialog,
          values: { ...(this.loginDialog.values || {}), [key]: value },
        };
      };
      const phoneField = fields.find((field) => field.key === "phone");
      const phoneReady = !phoneField
        || String(values.phone || "").replace(/\D/g, "").length === 11;
      const allReady = fields.every(
        (field) => String(values[field.key] || "").trim());
      const submit = () => {
        if (allReady && !busy) {
          this.runLoginAction(form.submitAction);
        }
      };
      return [
        h("p", { class: "login-form-intro" },
          form.hint || "请输入登录信息"),
        h("div", { class: "login-form" },
          fields.map((field) => h("div", {
            class: "login-field", key: field.key,
          }, [
            h("label", {
              class: "login-field-label",
              for: "login-field-" + field.key,
            }, field.label || field.key),
            h(ui.ElInput, {
              id: "login-field-" + field.key,
              modelValue: values[field.key] || "",
              "onUpdate:modelValue": (value) => setValue(field.key, value),
              size: "large", clearable: true,
              placeholder: field.placeholder || "",
              maxlength: field.maxlength || undefined,
              inputmode: field.inputmode || undefined,
              autocomplete: field.autocomplete || undefined,
              onKeyup: (event) => {
                if (event.key === "Enter") submit();
              },
            }),
          ]))),
        h("div", { class: "login-actions" }, [
          form.sendAction
            ? h(ui.ElButton, {
                size: "large",
                loading: busy && busyAction === form.sendAction,
                disabled: !phoneReady || busy,
                onClick: () => this.runLoginAction(form.sendAction),
              }, form.sendLabel || "发送验证码")
            : null,
          form.submitAction
            ? h(ui.ElButton, {
                size: "large", type: "primary",
                loading: busy && busyAction === form.submitAction,
                disabled: !allReady || busy,
                onClick: submit,
              }, form.submitLabel || "登录")
            : null,
        ]),
        h("p", { class: "login-status", role: "status", "aria-live": "polite" },
          this.loginDialog.status || ""),
      ];
    },
    renderCreditsBody() {
      const view = this.creditsView;
      if (!view) return null;
      const credits = view.credits || {};
      const packages = credits.packages || [];
      const remain = Number(credits.remain || 0);
      const size = Number(credits.size || 0);
      if (remain === -1 || credits.unlimited) {
        // 渠道上报的不限量账号：没有分包明细可画，只给汇总徽标
        return h("div", null, [
          h("div", { class: "credits-sum" }, [
            h("div", { class: "cs-item" }, [
              h("div", { class: "cs-num" }, badge("不限量", "ok", "该账号额度不限量")),
              h("div", { class: "cs-label" }, "剩余额度"),
            ]),
            h("div", { class: "cs-item" }, [
              h("div", { class: "cs-time dim" }, credits.updated_iso || "未同步"),
              h("div", { class: "cs-label" }, "更新时间"),
            ]),
          ]),
        ]);
      }
      return h("div", null, [
        h("div", { class: "credits-sum" }, [
          h("div", { class: "cs-item" }, [
            h("div", { class: "cs-num" }, num(remain)),
            h("div", { class: "cs-label" }, "剩余积分"),
          ]),
          h("div", { class: "cs-item" }, [
            h("div", { class: "cs-num dim" }, size ? num(size) : "—"),
            h("div", { class: "cs-label" }, "总额度"),
          ]),
          h("div", { class: "cs-item" }, [
            h("div", { class: "cs-time" }, credits.updated_iso || "未同步"),
            h("div", { class: "cs-label" }, "更新时间"),
          ]),
        ]),
        packages.length
          ? h(WbTable, { rows: packages, maxHeight: 320, columns: [
              { label: "额度包", minWidth: 200, render: ({ row }) =>
                  h("span", { title: row.package_code || "" }, row.name || "额度包") },
              { label: "剩余 / 总量", width: 200, render: ({ row }) =>
                  h("div", null, this.renderCreditBar(row.remain, row.size, 160, true)) },
              { label: "有效期", width: 170, render: ({ row }) => h("span", {
                  style: row.is_expired ? "color:var(--bad)" : "",
                }, row.no_expiry ? "长期有效" : (row.expire_time || "—")) },
            ] })
          : h(EmptyState, {
              text: "该账号暂无可读额度信息",
              hint: "先在账号管理里点一次「刷新额度」再查看",
              icon: "coin",
            }),
      ]);
    },
    /** 「更多」菜单的单一分派入口：命令名只在菜单定义处出现一次。 */
    runRowCommand(channel, account, command) {
      if (command === "weight") return this.editWeight(channel, account);
      if (command === "models") return this.editModels(channel, account);
      if (command === "probe") return this.runAction(channel, account, "probe");
      if (command === "checkin") return this.runAction(
        channel, account, "checkin", {}, channelsApi.checkinLabels(channel).submitted);
      if (command === "delete") return this.removeAccount(channel, account);
      return null;
    },
    renderAccountTable(channel, realm) {
      const rows = this.rowsOf(channel.id, realm.id);
      if (!rows.length) {
        return h(EmptyState, {
          text: "该出口还没有账号",
          hint: this.supports(channel, "accounts")
            ? "可用「登录账号」或「导入本机凭据」加入账号池"
            : "",
          icon: "pool",
        });
      }
      const caps = new Set(channel.capabilities || []);
      // 操作列：高频动作外露，其余收进「更多」，避免 7 个文字按钮挤满行尾
      const actionCount = 3;
      const columns = [
        { label: "账号", minWidth: 250, render: ({ row }) => {
            const st = accountState(row);
            const task = dailyBadge(row, channel);
            const label = accountLabel(row);
            return [
              h("div", { class: "acct-name-row" }, [
                h("span", { class: "acct-id" }, [
                  h("span", { class: "acct-name", title: label }, label),
                  h(ui.ElButton, {
                    size: "small", text: true, class: "acct-copy",
                    title: "复制登录账号",
                    onClick: () => this.copyAccount(row),
                  }, "复制"),
                ]),
                h(StateBadge, { status: st.status, label: st.text }),
                task ? badge(task.label, task.tone, task.title) : null,
                tierBadge(row.tier),
              ]),
              h("div", { class: "muted mono ellipsis", style: "font-size:11px", title: row.uid }, [
                `${(row.uid || "").slice(0, 8)} · ${row.source || "—"}`,
                row.expiresIn ? ` · 到期 ${row.expiresIn}` : "",
                row.issuedAt ? ` · 续期 ${ago(row.issuedAt)}` : "",
              ]),
              row.lastError
                ? h("div", { class: "mono ellipsis", style: "font-size:11px;color:var(--warn);margin-top:2px",
                             title: row.lastError }, row.lastError)
                : null,
            ];
          } },
        { label: "权重", minWidth: 70, align: "center",
          render: ({ row }) => h("b", { class: "num-strong" }, String(row.weight ?? 1)) },
        { label: "积分额度", minWidth: 150, render: ({ row }) => {
            const cred = row.credits;
            if (!cred || typeof cred.remain !== "number") {
              return h("span", { class: "muted" }, "未查询");
            }
            return this.renderCreditBar(cred.remain, cred.size, 120, false);
          } },
        { label: "禁用模型", minWidth: 90, align: "center", render: ({ row }) =>
            (row.disabledModels || []).length
              ? badge(`${row.disabledModels.length} 个`, "warn", (row.disabledModels || []).join(", "))
              : h("span", { class: "muted" }, "—") },
        { label: "操作", minWidth: actionWidth(actionCount), fixed: "right", align: "right",
          render: ({ row }) => {
            const menu = [
              { command: "weight", label: "权重" },
              { command: "models", label: "禁用模型" },
              { command: "probe", label: "测试连通性" },
            ];
            if (caps.has("checkin") && row.canCheckin) {
              menu.push({ command: "checkin",
                          label: channelsApi.checkinLabels(channel).action });
            }
            menu.push({ command: "delete", label: "删除", danger: true });
            const buttons = [
              h(ui.ElButton, {
                size: "small", text: true,
                onClick: () => this.toggleEnabled(channel, row),
              }, row.enabled ? "停用" : "启用"),
              h(ui.ElButton, {
                size: "small", text: true,
                onClick: () => this.showCredits(row),
              }, "明细"),
              h(ui.ElDropdown, {
                trigger: "click",
                placement: "bottom-end",
                onCommand: (command) => this.runRowCommand(channel, row, command),
              }, {
                default: () => h(ui.ElButton, {
                  size: "small", text: true, title: "更多操作",
                }, "更多"),
                dropdown: () => h(ui.ElDropdownMenu, null, menu.map((item) => h(ui.ElDropdownItem, {
                  key: item.command,
                  command: item.command,
                  divided: item.command === "delete",
                  class: item.danger ? "danger-item" : "",
                }, item.label))),
              }),
            ];
            // 单行排布；actionRow 的 flex-wrap 仅作边界兜底（按钮文案变长时换行不裁剪）
            return actionRow(buttons);
          } },
      ];
      return h(WbTable, { rows, rowKey: "uid", maxHeight: 480, stripe: true, columns });
    },

    renderSlotCard(channel) {
      if (!this.supports(channel, "proxy_slot")) return null;
      const realm = this.currentRealm(channel);
      if (!realm) return null;
      const slotRows = this.slotsOf(channel.id, realm.id);
      const saveState = this.slotSaveStateOf(channel.id, realm.id);
      const active = this.activeSlotOf(channel.id, realm.id);
      const stateBadge = saveState === "saving" ? badge("保存中…", "info")
        : saveState === "saved" ? badge("已保存", "ok")
          : saveState === "error" ? badge("保存失败", "bad")
            : null;
      return h("div", { class: "card" }, [
        cardHead("账号代理槽",
          "改动即时保存；当前出口启用中的槽，即该出口全部账号的统一代理，未启用则直连",
          h("div", { class: "push slot-head-side" }, [
            stateBadge,
            h(ui.ElButton, {
              size: "small", title: "重新读取服务器上的槽位",
              onClick: () => this.refreshSlots(channel),
              loading: this.slotsLoading,
              disabled: saveState === "saving",
            }, "刷新"),
            h(ui.ElButton, {
              size: "small", title: "批量探测本机 mihomo 端口段，可达出口自动加入",
              onClick: () => this.discoverSlots(channel),
            }, "发现本机槽位"),
            h(ui.ElButton, {
              size: "small", title: "加一条空槽位，填好地址后失焦或回车即自动保存",
              onClick: () => this.addSlot(channel),
            }, "新增槽位"),
          ]), "shield"),
        slotRows.length
          ? h("div", { class: "slot-list" },
              slotRows.map((row, index) => this.renderSlotRow(channel, row, active, index)))
          : h(EmptyState, {
              text: "该出口还没有代理槽",
              hint: "点上方「新增槽位」或「发现本机槽位」加入，配置即自动保存；不配置时账号直连",
              icon: "shield", compact: true,
            }),
      ]);
    },

    /** 单个槽位行：地址与探测信息在左，启用开关与操作在右（改动即时保存）。 */
    renderSlotRow(channel, row, active, index) {
      const isDraft = !String(row.url || "").trim();
      const probed = Boolean(row._probeUrl) && row._probeUrl === row.url;
      const isActive = active === row;
      const probing = Boolean(this.slotProbing[row.url]);
      const meta = [];
      if (isActive) meta.push(badge("生效中", "ok", "该槽为本出口全部账号提供代理"));
      if (!isDraft && !row.realm) meta.push(badge("未归属", "warn", "旧版全局槽：改动后归入当前出口"));
      if (isDraft) {
        meta.push(h("span", { class: "muted" }, "填入代理地址，失焦或回车即自动保存"));
      } else if (probed) {
        meta.push(h("span", { class: "mono" }, `出口 ${row.ip}`));
        [row.country, row.ip_type, row.isp].filter(Boolean)
          .forEach((text) => meta.push(h("span", null, text)));
        if (row.probed_at) meta.push(h("span", { class: "muted" }, `探测于 ${ago(row.probed_at)}`));
      } else {
        meta.push(h("span", { class: "muted" }, "未探测"));
      }
      return h("div", { key: index, class: ["slot-row", isActive ? "active" : ""] }, [
        h("div", { class: "slot-row-main" }, [
          h(ui.ElInput, {
            modelValue: row.url,
            "onUpdate:modelValue": (value) => { row.url = value; },
            onChange: () => this.commitSlotUrl(channel, row),
            onBlur: () => this.abandonDraft(channel, row),
            size: "small",
            placeholder: "http://user:pass@host:port",
            class: "slot-url-input",
            inputStyle: { fontFamily: MONO_FONT, fontSize: "12px" },
            title: row.name ? `名称：${row.name}（失焦或回车即保存）` : "失焦或回车即保存",
          }),
          h("div", { class: "slot-row-meta" }, meta),
        ]),
        h("div", { class: "slot-row-actions" }, [
          h("span", { class: "slot-switch-label" }, row.enabled !== false ? "启用" : "停用"),
          h(ui.ElSwitch, {
            modelValue: row.enabled !== false,
            "onUpdate:modelValue": (value) => this.toggleSlot(channel, row, value),
            size: "small",
          }),
          h(ui.ElButton, {
            size: "small", text: true, loading: probing, disabled: probing,
            onClick: () => this.probeSlot(channel, row),
          }, probing ? "探测中" : "探测"),
          h(ui.ElButton, {
            size: "small", text: true, type: "danger",
            onClick: () => this.removeSlot(channel, row),
          }, "删除"),
        ]),
      ]);
    },
  },
  render() {
    // 页头不再放刷新按钮：账号数据随出口切换自动刷新、额度有「刷新额度」，
    // 槽位刷新归位到「账号代理槽」卡头（此前按钮悬在页头，与槽位卡相隔一屏）
    const page = h(PageHead, {
      title: "账号治理",
      desc: "跟随顶栏出口切换；多号按权重分流，全部账号不可用时自动换号",
      icon: "pool",
    });

    if (this.error) {
      return h("div", null, [page, errorAlert(this.error)]);
    }

    if (!this.channels.length) {
      return h("div", null, [
        page,
        h(EmptyState, {
          text: "没有声明账号治理能力的渠道",
          hint: "后端注册表未下发该能力，页面不留入口",
        }),
      ]);
    }

    const dialogs = [
      h(ui.ElDialog, {
        modelValue: this.importOpen,
        "onUpdate:modelValue": (value) => { this.importOpen = value; },
        title: "导入本机桌面凭据", width: "640px",
      }, {
        default: () => [
          this.importCandidates.length
            ? h(WbTable, { rows: this.importCandidates, columns: [
                { label: "账号", minWidth: 150, render: ({ row }) =>
                    row.loginAccount || row.nickname || row.uid || "—" },
                { prop: "realm", label: "出口", width: 100, render: ({ row }) =>
                    badge(row.realmLabel
                      || (row.realm === "cn" ? "国内版"
                        : row.realm === "intl" ? "国际版" : row.realm),
                      "s", row.domain || "") },
                { label: "状态", width: 110, render: ({ row }) => h(StateBadge, {
                    status: row.valid ? "ok" : (row.encrypted ? "warn" : "error"),
                    label: row.encrypted ? "已加密" : (row.valid ? "可导入" : "不可用"),
                  }) },
                { label: "操作", width: 100, align: "right", render: ({ row }) => h(ui.ElButton, {
                    size: "small", type: "primary",
                    disabled: !row.usable || this.importBusy,
                    onClick: () => this.importCandidate(row),
                  }, "导入") },
              ] })
            : h(EmptyState, {
                text: "本机没有可导入的桌面凭据",
                hint: "请确认目标客户端已登录，或改用「登录账号」",
              }),
        ],
      }),
      h(ui.ElDialog, {
        modelValue: this.loginDialog.open,
        "onUpdate:modelValue": (value) => {
          this.loginDialog = { ...this.loginDialog, open: value };
          if (!value) this.closeLogin();
        },
        title: this.loginDialog.form
          ? (this.loginDialog.form.title || "登录账号")
          : "登录账号（OAuth 授权）", width: "560px",
      }, {
        default: () => this.loginDialog.form ? this.renderLoginForm() : [
          h("div", { class: "step done" }, [
            h("div", { class: "n" }, "1"),
            h("div", { class: "t" }, "浏览器已打开官方授权页（若被拦截，点下方链接）"),
          ]),
          this.loginDialog.authUrl
            ? h("a", { class: "login-link", href: this.loginDialog.authUrl,
                       target: "_blank", rel: "noopener" }, this.loginDialog.authUrl)
            : null,
          h("div", { class: "step active" }, [
            h("div", { class: "n" }, "2"),
            h("div", { class: "t" }, "在浏览器里完成登录授权，本窗口会自动检测并完成入池"),
          ]),
          h("p", { class: "hint", role: "status", "aria-live": "polite" },
            this.loginDialog.status || "等待授权…"),
          // 粘贴回调兜底（后端声明 paste 的渠道才有此入口）：
          // 服务器部署 / 回环端口打不通时，把地址栏整段复制回来完成登录
          this.loginDialog.paste
            ? h("div", { class: "step", style: "margin-top:10px" }, [
                h("div", { class: "n" }, "3"),
                h("div", { class: "t" }, "浏览器停在等待页或无回调时，把地址栏整段粘贴到这里"),
                h("div", { style: "display:flex;gap:8px;margin-top:8px" }, [
                  h(ui.ElInput, {
                    modelValue: this.loginDialog.callback,
                    "onUpdate:modelValue": (value) => {
                      this.loginDialog = { ...this.loginDialog, callback: value };
                    },
                    size: "small", clearable: true,
                    placeholder: "http://127.0.0.1:.../authorize?refreshToken=... 或整段地址",
                  }),
                  h(ui.ElButton, {
                    size: "small", type: "primary",
                    disabled: !this.loginDialog.callback,
                    onClick: this.submitLoginCallback,
                  }, "提交"),
                ]),
              ])
            : null,
        ],
        footer: this.loginDialog.form ? undefined : () =>
          h("div", { class: "login-actions" }, [
            h(ui.ElButton, {
              size: "large", onClick: () => this.closeLogin(),
            }, "关闭"),
            h(ui.ElButton, {
              size: "large", type: "primary",
              loading: this.loginDialog.busy,
              onClick: () => this.restartLogin(),
            }, this.loginDialog.busy ? "生成中…" : "重新生成链接"),
          ]),
      }),
      h(ui.ElDialog, {
        modelValue: this.creditsOpen,
        "onUpdate:modelValue": (value) => { this.creditsOpen = value; },
        title: this.creditsView
          ? `额度 · ${this.creditsView.loginAccount || this.creditsView.nickname || ""}`
          : "额度明细",
        width: "620px",
      }, {
        default: () => this.renderCreditsBody(),
      }),
    ];

    return h("div", null, [
      page,
      h("div", { class: "channel-sections" },
        this.channels.map((channel) => {
          const realm = this.currentRealm(channel);
          if (!realm) return null; // 该渠道没有任何出口：整块不渲染
          const rows = this.rowsOf(channel.id, realm.id);
          const enabled = rows.filter((row) => row.enabled !== false).length;
          // 渠道名去掉括号里的长后缀；出口徽标与渠道名重复时不再重复展示
          const channelLabel = String(channel.label || channel.id)
            .replace(/\s*[（(].*$/, "").trim();
          const realmLabel = realm.badge || realm.label || realm.id;
          const channelKey = channelLabel.split(/\s+/)[0].toLowerCase();
          const showRealmBadge = realmLabel
            && !String(realmLabel).toLowerCase().includes(channelKey);
          // 出口级代理徽标：该出口有生效中的槽时才亮，别的出口不受影响
          const activeSlot = this.activeSlotOf(channel.id, realm.id);
          const headerBadges = [];
          if (showRealmBadge) {
            headerBadges.push(badge(realmLabel, "info", realm.domain || ""));
          }
          if (activeSlot) {
            headerBadges.push(badge(
              `代理 · ${activeSlot.name || activeSlot.url}`, "ok",
              `${activeSlot.url}${activeSlot.ip ? ` · 出口 ${activeSlot.ip}` : ""}`));
          }
          return channelSection(channel.id, [
            h("div", { class: "card" }, [
              // 渠道信息与操作合并为表头工具行：不再单独占一层区块标题
              h("div", { class: "toolbar" }, [
                channelMeta({
                  title: channelLabel,
                  badges: headerBadges,
                  hint: `共 ${rows.length} 个 · 启用 ${enabled} 个`,
                }),
                h("div", { class: "toolbar-actions" }, [
                  this.supports(channel, "accounts")
                    ? h(ui.ElButton, {
                        size: "small", type: "primary",
                        onClick: () => this.startLogin(channel, realm.id),
                      }, "+ 登录账号")
                    : null,
                  this.supports(channel, "accounts") && realm.desktop_import
                    ? h(ui.ElButton, {
                        size: "small", onClick: this.openImport,
                        loading: this.importBusy,
                        title: "扫描本机桌面端已登录的凭据，扫描结果里逐个确认导入",
                      }, this.importBusy ? "扫描中…" : "扫描客户端账号")
                    : null,
                  h(ui.ElButton, {
                    size: "small",
                    onClick: () => this.refreshCredits(realm.id),
                  }, "刷新额度"),
                  h(ui.ElButton, {
                    size: "small", title: "把当前出口全部账号切到启用",
                    onClick: () => this.setAllEnabled(channel, realm, true),
                  }, "全部启用"),
                  h(ui.ElButton, {
                    size: "small", title: "把当前出口全部账号切到停用（需确认）",
                    onClick: () => this.setAllEnabled(channel, realm, false),
                  }, "全部停用"),
                ]),
              ]),
              this.renderAccountTable(channel, realm),
            ]),
            this.renderSlotCard(channel),
          ]);
        })),
      ...dialogs,
    ]);
  },
};
