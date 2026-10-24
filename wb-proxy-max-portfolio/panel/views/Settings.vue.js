/*
 * panel/views/Settings.vue.js —— 设置
 *
 * 设置页没有「渠道运营数据」，只有网关级配置：因此这里不画渠道分块，也不
 * 出现渠道运营按钮（§2.2）。自动化排程卡是全局调度配置——总开关打开时按
 * 后端注册表下发的反代分组，维护各任务的整点执行时间；渠道任务的启停仍
 * 属于任务页。
 *
 * 每个分区独立保存（只提交自己那几项），避免一处改动覆盖另一处。
 */
import { h, ref, computed, onMounted, onUnmounted, nextTick } from "/vendor/vue.mjs";
import { settingsApi } from "../api/settings.js";
import { panelApi } from "../api/panel.js";
import { useStore, loadBootstrap, ensureBootstrap, realmMeta } from "../store/index.js";
import { ui, ElMessage, ElMessageBox } from "../components/ui.js";
import PageHead from "../components/PageHead.js";
import StateBadge from "../components/StateBadge.js";
import WbTable from "../components/WbTable.js";
import { cardHead, errorAlert, confirmAction, refreshAction, badge } from "../components/kit.js";

function blankKey() {
  return { id: "", name: "", key: "", realm: "", models: "", enabled: true };
}

//: 任务时间只支持整点（0-23），面板统一用 24 小时制的两位显示
const HOUR_OPTIONS = Array.from({ length: 24 }, (_, hour) => ({
  value: hour,
  label: `${String(hour).padStart(2, "0")}:00`,
}));

/** 设置页分区锚点：跳转到每组第一张卡，长页不必从头滚到底。 */
const SETTINGS_NAV = [
  { id: "set-access", label: "访问与安全" },
  { id: "set-behavior", label: "网关行为" },
  { id: "set-identity", label: "身份与模型目录" },
  { id: "set-automation", label: "自动化排程" },
  { id: "set-logs", label: "日志与更新" },
  { id: "set-paths", label: "数据位置" },
];

export default {
  name: "SettingsView",
  components: { PageHead, StateBadge },
  setup() {
    const store = useStore();
    const loading = ref(false);
    const error = ref("");
    const data = ref(null);
    /** 设置目录当前高亮的分区：随内容滚动更新，点击目录时先行切换。 */
    const activeSection = ref(SETTINGS_NAV[0].id);
    let scrollHost = null;
    let scrollRaf = 0;

    function syncActiveSection() {
      if (!scrollHost) return;
      // 最后一节很短，可能永远到不了阈值：用户已滚动且到底时直接归它。
      // scrollTop 为 0 时不走这条，避免页面首次挂载（内容还没渲染完）误判到底部。
      if (scrollHost.scrollTop > 0
          && scrollHost.scrollTop + scrollHost.clientHeight >= scrollHost.scrollHeight - 4) {
        activeSection.value = SETTINGS_NAV[SETTINGS_NAV.length - 1].id;
        return;
      }
      const threshold = scrollHost.getBoundingClientRect().top + 96;
      let current = SETTINGS_NAV[0].id;
      SETTINGS_NAV.forEach((item) => {
        const el = document.getElementById(item.id);
        if (el && el.getBoundingClientRect().top <= threshold) current = item.id;
      });
      activeSection.value = current;
    }

    function onSettingsScroll() {
      if (scrollRaf) return;
      scrollRaf = requestAnimationFrame(() => {
        scrollRaf = 0;
        syncActiveSection();
      });
    }

    // 面板密码
    const passwordForm = ref({ current: "", password: "", confirm: "" });
    const passwordBusy = ref(false);

    // API Key 编辑（页面内部把 models 数组换成逗号串，提交时再拆回数组）
    const keyRows = ref([]);
    const keysBusy = ref(false);

    // 网关行为
    const behavior = ref({
      egress_backoff: true,
      local_web_tools: false,
      auto_switch_product: false,
      daily_chat_web: true,
      daily_chat_budget: 600,
      daily_chat_web_concurrency: 1,
      daily_chat_web_retry_backoff: 5,
      daily_chat_web_random_prompt: false,
      affinity_stable_key_enabled: false,
      account_max_concurrent: 0,
      auth_disabled: false,
    });
    const dailyChatPrompts = ref("");
    const dailyChatModels = ref("");
    const behaviorBusy = ref(false);

    // 身份声明与模型目录
    const identitySettings = ref({
      private_data: "auto",
      filter_models_by_key: false,
      models_only_available: false,
    });
    const identityBusy = ref(false);

    // 超时
    const timeouts = ref({ header: 120, idle: 300 });
    const timeoutsBusy = ref(false);

    // 提示词
    const prompt = ref({ mode: "passthrough", file: "" });
    const promptBusy = ref(false);

    // 日志落库
    const logDb = ref({ enabled: false, max_rows: null, max_days: 7, max_bytes: null });
    const logDbBusy = ref(false);

    // 更新检查
    const updateBusy = ref(false);

    // Key 表的强制重渲染标记：每次设置重载换一个值。浏览器会把早期密码框
    // 时期的内容按站点凭据自动回填进 Key 输入框（只在被存过的行出现），
    // 整表重建是原二开「保存后 loadSettings() 重载」的等价物——DOM 换新，
    // 回填值不残留。
    const keyTableEpoch = ref(0);

    // 自动化排程（全局）
    const automation = ref({ enabled: true });
    const automationBusy = ref(false);

    // 任务时间编辑：渠道与任务清单全部来自后端注册表（/channels），
    // 页面不硬编码渠道 id；只改整点，分钟不参与排程。
    const autoChannel = ref("");
    const autoDirty = ref(false);
    const autoExpanded = ref("");
    const taskHoursBusy = ref(false);

    /** 分类器上的短名：单出口渠道用出口徽标（Trae / Qoder CN…），
        多出口渠道用渠道名（WorkBuddy 同时覆盖国际版与国内版）。 */
    function tabLabelOf(channel) {
      const realms = channel.realms || [];
      if (realms.length === 1 && realms[0].badge) return realms[0].badge;
      return channel.label || channel.id;
    }

    const autoChannels = computed(() => {
      const tasks = store.schedulerTasks || [];
      return (store.channels || [])
        .map((channel) => ({
          id: channel.id,
          label: channel.label || channel.id,
          tabLabel: tabLabelOf(channel),
          count: tasks.filter((task) => task.channel === channel.id).length,
        }))
        .filter((channel) => channel.count > 0);
    });

    /** 当前选中反代；未选择或已消失时回落到第一个有任务的渠道。 */
    const autoChannelId = computed(() => {
      const ids = autoChannels.value.map((channel) => channel.id);
      return ids.includes(autoChannel.value) ? autoChannel.value : (ids[0] || "");
    });

    const autoTasks = computed(() => {
      const tasks = store.schedulerTasks || [];
      return tasks.filter((task) => task.channel === autoChannelId.value);
    });

    function cleanHours(raw) {
      return [...new Set((Array.isArray(raw) ? raw : [])
        .map((hour) => Number(hour))
        .filter((hour) => Number.isInteger(hour) && hour >= 0 && hour <= 23))]
        .sort((a, b) => a - b);
    }

    /** 任务的当前整点：已保存值优先，缺项回落适配器声明的默认值。 */
    function hoursOf(task) {
      const saved = (automation.value || {})[task.id] || {};
      const raw = Array.isArray(saved.hours) && saved.hours.length
        ? saved.hours : ((task.defaults || {}).hours || []);
      return cleanHours(raw);
    }

    function taskEnabled(task) {
      const saved = (automation.value || {})[task.id];
      if (saved && saved.enabled !== undefined) return saved.enabled !== false;
      return (task.defaults || {}).enabled !== false;
    }

    function taskRealmBadges(task) {
      return (task.realms || []).map((id) => ({
        id,
        label: realmMeta(id)?.badge || realmMeta(id)?.label || id,
      }));
    }

    function defaultHoursOf(task) {
      return cleanHours((task.defaults || {}).hours || []);
    }

    function setTaskHours(task, value) {
      automation.value = {
        ...automation.value,
        [task.id]: {
          ...((automation.value || {})[task.id] || {}),
          hours: cleanHours(value),
        },
      };
      autoDirty.value = true;
    }

    function toggleTaskHour(task, hour) {
      const hours = hoursOf(task);
      setTaskHours(task,
        hours.includes(hour) ? hours.filter((item) => item !== hour) : [...hours, hour]);
    }

    function resetTaskHours(task) {
      setTaskHours(task, defaultHoursOf(task));
    }

    function pickAutoChannel(id) {
      autoChannel.value = id;
      autoExpanded.value = "";
    }

    function toggleTaskEditor(taskId) {
      autoExpanded.value = autoExpanded.value === taskId ? "" : taskId;
    }

    function hourLabel(hour) {
      return `${String(hour).padStart(2, "0")}:00`;
    }

    /** 保存全部任务的整点配置（含未选中的反代，避免漏提交已改项）。 */
    async function saveTaskHours() {
      const tasks = store.schedulerTasks || [];
      const missing = tasks.filter((task) => !hoursOf(task).length);
      if (missing.length) {
        ElMessage.warning(`每个任务至少选择一个整点：${
          missing.map((task) => task.label || task.id).join("、")}`);
        return;
      }
      const payload = { enabled: automation.value.enabled !== false };
      tasks.forEach((task) => {
        payload[task.id] = { enabled: taskEnabled(task), hours: hoursOf(task) };
      });
      taskHoursBusy.value = true;
      try {
        await settingsApi.save({ automation: payload });
        autoDirty.value = false;
        ElMessage.success("任务时间已保存");
        await load();
      } catch (err) {
        ElMessage.error(err.message || "保存失败");
      } finally {
        taskHoursBusy.value = false;
      }
    }

    const updates = computed(() => data.value?.update_check || {});

    function apply(payload) {
      data.value = payload;
      behavior.value = {
        egress_backoff: payload.egress_backoff !== false,
        local_web_tools: payload.local_web_tools === true,
        auto_switch_product: payload.auto_switch_product === true,
        daily_chat_web: payload.daily_chat_web !== false,
        daily_chat_budget: payload.daily_chat_budget ?? 600,
        daily_chat_web_concurrency: payload.daily_chat_web_concurrency ?? 1,
        daily_chat_web_retry_backoff: payload.daily_chat_web_retry_backoff ?? 5,
        daily_chat_web_random_prompt: payload.daily_chat_web_random_prompt === true,
        affinity_stable_key_enabled: payload.affinity_stable_key_enabled === true,
        account_max_concurrent: payload.account_max_concurrent ?? 0,
        auth_disabled: payload.auth_disabled === true,
      };
      dailyChatPrompts.value = (payload.daily_chat_web_prompts || []).join("\n");
      dailyChatModels.value = (payload.daily_chat_models || []).join("\n");
      identitySettings.value = {
        private_data: payload.identity?.private_data || "auto",
        filter_models_by_key: payload.filter_models_by_key === true,
        models_only_available: payload.models_only_available === true,
      };
      timeouts.value = {
        header: payload.upstream_timeouts?.header ?? 120,
        idle: payload.upstream_timeouts?.idle ?? 300,
      };
      prompt.value = {
        mode: payload.prompt?.mode || "passthrough",
        file: payload.prompt?.file || "",
      };
      logDb.value = {
        enabled: payload.log_db?.enabled === true,
        max_rows: payload.log_db?.max_rows ?? null,
        max_days: payload.log_db?.max_days ?? 7,
        max_bytes: payload.log_db?.max_bytes ?? null,
      };
      keyRows.value = (payload.api_keys || []).map((entry) => ({
        id: entry.id,
        name: entry.name,
        key: "",
        hasSaved: Boolean(entry.id),   // 该行已有存储值（Key 不可观测，不显示形态）
        realm: entry.realm || "",
        models: (entry.models || []).join(","),
        enabled: entry.enabled !== false,
      }));
      keyTableEpoch.value += 1;   // 整表重建：浏览器自动回填的值不残留
      automation.value = { ...(payload.automation || { enabled: true }) };
      autoDirty.value = false;
    }

    async function load() {
      loading.value = true;
      error.value = "";
      try {
        apply(await settingsApi.get());
      } catch (err) {
        error.value = err.message || "设置加载失败";
      } finally {
        loading.value = false;
      }
    }

    async function savePassword() {
      const form = passwordForm.value;
      if (!form.current || !form.password) {
        ElMessage.warning("请填写当前密码与新密码");
        return;
      }
      if (form.password !== form.confirm) {
        ElMessage.warning("两次输入的新密码不一致");
        return;
      }
      passwordBusy.value = true;
      try {
        await panelApi.changePassword(form.current, form.password);
        passwordForm.value = { current: "", password: "", confirm: "" };
        ElMessage.success("面板密码已修改，其它会话已失效");
        await loadBootstrap(true);
      } catch (err) {
        ElMessage.error(err.message || "修改失败");
      } finally {
        passwordBusy.value = false;
      }
    }

    async function saveKeys() {
      // 从"有 Key"变成"零 Key"= 一键交出全部校验（保存后面板接管 /v1 鉴权），
      // 这种自断后路的操作必须二次确认（T-08）
      const hadKeys = (data.value?.api_keys || []).length > 0;
      if (hadKeys && !keyRows.value.length) {
        const ok = await confirmAction(
          "保存空列表将清空全部 Key：/v1 接口会对所有请求返回 401（除非已在启动参数配置 Key）。",
          "清空全部 Key", { type: "warning", confirmButtonText: "清空", cancelButtonText: "取消" });
        if (!ok) return;
      }
      keysBusy.value = true;
      try {
        const payload = keyRows.value.map((row) => ({
          id: row.id || undefined,
          name: row.name,
          // 留空表示沿用现有 Key（服务端按 id 取原值）
          key: row.key || undefined,
          realm: row.realm || "",
          models: String(row.models || "").split(",")
            .map((item) => item.trim()).filter(Boolean),
          enabled: row.enabled !== false,
        }));
        await settingsApi.save({ api_keys: payload });
        ElMessage.success("API Key 已保存");
        // 保存后 Key 立即从界面消失（用户拍板：不可观测），整表重建顺便
        // 清掉浏览器可能回填的残留值
        await load();
      } catch (err) {
        ElMessage.error(err.message || "保存失败");
      } finally {
        keysBusy.value = false;
      }
    }

    async function revealKey(row) {
      if (!row.id) {
        ElMessage.info("新 Key 直接填在输入框里即可");
        return;
      }
      try {
        const payload = await settingsApi.revealKey(row.id);
        await ElMessageBox.alert(payload.key || "", "明文 Key", { type: "warning" });
      } catch (err) {
        ElMessage.error(err.message || "读取失败");
      }
    }

    function addKey() {
      keyRows.value = [...keyRows.value, blankKey()];
    }

    function removeKey(index) {
      keyRows.value = keyRows.value.filter((_, i) => i !== index);
    }

    /** 分区保存的统一脚手架：busy 置位 → 保存 → 成功提示 → 重载；失败提示人话。 */
    async function saveSection(busy, payload, successMsg) {
      busy.value = true;
      try {
        await settingsApi.save(typeof payload === "function" ? payload() : payload);
        ElMessage.success(successMsg);
        await load();
      } catch (err) {
        ElMessage.error(err.message || "保存失败");
      } finally {
        busy.value = false;
      }
    }

    async function saveBehavior() {
      await saveSection(behaviorBusy, {
        egress_backoff: behavior.value.egress_backoff,
        local_web_tools: behavior.value.local_web_tools,
        auto_switch_product: behavior.value.auto_switch_product,
        daily_chat_web: behavior.value.daily_chat_web,
        daily_chat_budget: Number(behavior.value.daily_chat_budget),
        daily_chat_web_concurrency: Number(behavior.value.daily_chat_web_concurrency),
        daily_chat_web_retry_backoff:
          Number(behavior.value.daily_chat_web_retry_backoff),
        daily_chat_web_random_prompt: behavior.value.daily_chat_web_random_prompt,
        affinity_stable_key_enabled: behavior.value.affinity_stable_key_enabled,
        account_max_concurrent: Number(behavior.value.account_max_concurrent),
        daily_chat_models: String(dailyChatModels.value || "")
          .split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
        daily_chat_web_prompts: String(dailyChatPrompts.value || "")
          .split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
        auth_disabled: behavior.value.auth_disabled,
      }, "网关行为已保存");
    }

    async function saveIdentitySettings() {
      await saveSection(identityBusy, {
        identity: { private_data: identitySettings.value.private_data },
        filter_models_by_key: identitySettings.value.filter_models_by_key,
        models_only_available: identitySettings.value.models_only_available,
      }, "身份与模型目录设置已保存");
    }

    async function saveTimeouts() {
      await saveSection(timeoutsBusy, {
        upstream_timeouts: {
          header: Number(timeouts.value.header),
          idle: Number(timeouts.value.idle),
        },
      }, "超时设置已保存");
    }

    async function savePrompt() {
      await saveSection(promptBusy, {
        prompt: { mode: prompt.value.mode, file: prompt.value.file },
      }, "提示词设置已保存");
    }

    async function saveLogDb() {
      await saveSection(logDbBusy, {
        log_db: {
          enabled: logDb.value.enabled,
          max_rows: logDb.value.max_rows === "" ? null : logDb.value.max_rows,
          max_days: logDb.value.max_days === "" ? null : logDb.value.max_days,
          max_bytes: logDb.value.max_bytes === "" ? null : logDb.value.max_bytes,
        },
      }, "日志落库设置已保存");
    }

    async function toggleUpdateCheck(enabled) {
      await saveSection(updateBusy, { update_check_enabled: enabled },
        enabled ? "更新检查已开启" : "更新检查已关闭");
    }

    async function checkUpdates() {
      updateBusy.value = true;
      try {
        const result = await settingsApi.checkUpdates();
        const sources = result.sources || [];
        const newer = sources.filter((item) => item.update_available);
        const failed = sources.filter((item) => item.last_error);
        if (newer.length) {
          ElMessage.success(
            `发现新版本：${newer.map((item) => `${item.id} ${item.latest_version}`).join("、")}`);
        } else if (failed.length === sources.length && sources.length) {
          ElMessage.warning("检查失败：所有上游源都未能访问");
        } else if (failed.length) {
          ElMessage.warning(`部分源检查失败（${failed.map((item) => item.id).join("、")}），其余已是最新`);
        } else {
          ElMessage.info("全部上游均为最新");
        }
        await load();
      } catch (err) {
        ElMessage.error(err.message || "检查失败");
      } finally {
        updateBusy.value = false;
      }
    }

    /** 自动化总开关：与任务页「暂停排程」同一配置，这里即时生效（不再要"保存"），
        避免两处入口一个要保存一个即时的分裂体验（T-10）。 */
    async function toggleAutomation(enabled) {
      await saveSection(automationBusy, { automation: { enabled } },
        enabled ? "自动化已开启" : "自动化已暂停（手动触发仍可用）");
    }

    onMounted(async () => {
      // 任务时间卡依赖 /channels 下发的渠道与任务归属，先等全局清单就绪
      await ensureBootstrap();
      await load();
      await nextTick();
      syncActiveSection();
    });

    onMounted(() => {
      scrollHost = document.querySelector(".content");
      if (scrollHost) scrollHost.addEventListener("scroll", onSettingsScroll, { passive: true });
      syncActiveSection();
    });

    onUnmounted(() => {
      if (scrollHost) scrollHost.removeEventListener("scroll", onSettingsScroll);
      if (scrollRaf) cancelAnimationFrame(scrollRaf);
    });

    return {
      store, loading, error, data, updates, activeSection,
      passwordForm, passwordBusy, keyRows, keysBusy, keyTableEpoch,
      behavior, behaviorBusy, dailyChatPrompts, dailyChatModels,
      identitySettings, identityBusy, timeouts, timeoutsBusy,
      prompt, promptBusy, logDb, logDbBusy, updateBusy,
      automation, automationBusy,
      autoChannel, autoChannelId, autoChannels, autoTasks, autoDirty,
      autoExpanded, taskHoursBusy, hoursOf, taskEnabled, taskRealmBadges,
      setTaskHours, toggleTaskHour, resetTaskHours, pickAutoChannel,
      toggleTaskEditor, hourLabel, defaultHoursOf, saveTaskHours,
      load, savePassword, saveKeys, revealKey, addKey, removeKey,
      saveBehavior, saveIdentitySettings, saveTimeouts, savePrompt, saveLogDb,
      toggleUpdateCheck, checkUpdates, toggleAutomation,
    };
  },
  methods: {
    jumpTo(id) {
      this.activeSection = id;
      const target = document.getElementById(id);
      if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    switchRow(label, hint, checked, onChange, disabled = false) {
      return h("div", { class: "setting-row" }, [
        h("div", { class: "setting-text" }, [
          h("div", { class: "setting-label" }, label),
          hint ? h("div", { class: "setting-hint" }, hint) : null,
        ]),
        h(ui.ElSwitch, {
          modelValue: checked,
          "onUpdate:modelValue": onChange,
          disabled,
        }),
      ]);
    },
  },
  render() {
    const head = h(PageHead, {
      title: "设置",
      desc: "网关级配置；自动化任务时间在这里按反代统一维护",
      icon: "settings",
    }, {
      actions: () => [
        refreshAction({ onClick: this.load, loading: this.loading }),
      ],
    });

    if (this.error) {
      return h("div", null, [head, errorAlert(this.error)]);
    }

    if (!this.data) {
      return h("div", null, [head, h(ui.ElSkeleton, { rows: 6, animated: true })]);
    }

    const panelCard = h("div", { class: "card", id: "set-access" }, [
      cardHead("面板访问", "", this.store.passwordIsDefault
        ? h(StateBadge, { status: "warn", label: "仍在使用默认密码" })
        : h(StateBadge, { status: "ok", label: "已修改默认密码" }), "shield"),
      h("div", { class: "grid c3" }, [
        h(ui.ElInput, {
          modelValue: this.passwordForm.current,
          "onUpdate:modelValue": (value) => { this.passwordForm = { ...this.passwordForm, current: value }; },
          type: "password", showPassword: true, placeholder: "当前密码",
        }),
        h(ui.ElInput, {
          modelValue: this.passwordForm.password,
          "onUpdate:modelValue": (value) => { this.passwordForm = { ...this.passwordForm, password: value }; },
          type: "password", showPassword: true, placeholder: "新密码（至少 4 位）",
        }),
        h(ui.ElInput, {
          modelValue: this.passwordForm.confirm,
          "onUpdate:modelValue": (value) => { this.passwordForm = { ...this.passwordForm, confirm: value }; },
          type: "password", showPassword: true, placeholder: "再次输入新密码",
        }),
      ]),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { type: "primary", loading: this.passwordBusy,
                         onClick: this.savePassword }, "修改密码"),
        h("span", { class: "muted" }, "修改后所有已登录会话都会失效，需要重新登录。"),
      ]),
    ]);

    const keyCard = h("div", { class: "card", id: "set-keys" }, [
      cardHead("API Key",
        this.data.auth_required ? "当前 /v1 需要 Key" : "当前 /v1 不校验 Key",
        h(ui.ElButton, {
          size: "small", style: "margin-left:auto", onClick: this.addKey,
        }, "新增 Key"), "key"),
      this.keyRows.length
        ? h(WbTable, { key: "key-rows-" + this.keyTableEpoch,
                       rows: this.keyRows, columns: [
            { label: "名称", width: 150, render: ({ row }) => h(ui.ElInput, {
                modelValue: row.name,
                "onUpdate:modelValue": (value) => { row.name = value; },
                size: "small", placeholder: "便于识别的名字",
              }) },
            { label: "Key", minWidth: 260, render: ({ row }) =>
                // 保存后 Key 完全不可观测（用户拍板 2026-10-19，对齐原二开
                // 「保存完直接消失」）：输入框恒空、固定占位、不显示掩码值——
                // 部分掩码形如 guon******iban 会被当成损坏值；要看走「查看」。
                h(ui.ElInput, {
                  modelValue: row.key,
                  "onUpdate:modelValue": (value) => { row.key = value; },
                  size: "small",
                  placeholder: row.hasSaved ? "已保存（留空表示不改）" : "粘贴新的 Key",
                }) },
            { label: "绑定出口", width: 140, render: ({ row }) => h(ui.ElSelect, {
                modelValue: row.realm,
                "onUpdate:modelValue": (value) => { row.realm = value; },
                size: "small", placeholder: "跟随面板",
              }, { default: () => [
                h(ui.ElOption, { label: "跟随面板", value: "" }),
                ...(this.data.realms || []).map((realm) =>
                  h(ui.ElOption, { key: realm.id, label: realm.label || realm.id, value: realm.id })),
              ] }) },
            { label: "模型白名单", minWidth: 180, render: ({ row }) => h(ui.ElInput, {
                modelValue: row.models,
                "onUpdate:modelValue": (value) => { row.models = value; },
                size: "small", placeholder: "逗号分隔，留空为不限制",
              }) },
            { label: "启用", width: 70, render: ({ row }) => h(ui.ElSwitch, {
                modelValue: row.enabled,
                "onUpdate:modelValue": (value) => { row.enabled = value; },
                size: "small",
              }) },
            { label: "操作", width: 130, render: ({ row, $index }) => [
                h(ui.ElButton, { size: "small", text: true,
                                 onClick: () => this.revealKey(row) }, "查看"),
                h(ui.ElButton, { size: "small", text: true, type: "danger",
                                 onClick: () => this.removeKey($index) }, "移除"),
              ] },
          ] })
        : h(ui.ElAlert, {
            type: "info", showIcon: true,
            description: "尚未配置 Key。启动参数里的 Key 仍然有效；一旦在面板配置，面板接管校验。",
          }),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.keysBusy,
                         onClick: this.saveKeys }, "保存 Key 列表"),
        h("span", { class: "muted" }, "Key 输入框留空表示沿用该行原有 Key。"),
      ]),
    ]);

    const behaviorCard = h("div", { class: "card", id: "set-behavior" }, [
      cardHead("网关行为", "", null, "settings"),
      this.switchRow("出口级退避", "链路抖动时对单个出口做秒级退避，不熔断整批账号",
        this.behavior.egress_backoff,
        (value) => { this.behavior = { ...this.behavior, egress_backoff: value }; }),
      this.switchRow("本地网络工具", "由网关代跑 web_search / web_fetch（默认关；开启后网关会自己访问外部网址）",
        this.behavior.local_web_tools,
        (value) => { this.behavior = { ...this.behavior, local_web_tools: value }; }),
      this.switchRow("产品自动切换", "429 时在主产品与备用产品之间自动切换（二开行为）",
        this.behavior.auto_switch_product,
        (value) => { this.behavior = { ...this.behavior, auto_switch_product: value }; }),
      this.switchRow("国际版每日活跃走网页通道", "桌面身分的轻量对话不计入官方每日活跃",
        this.behavior.daily_chat_web,
        (value) => { this.behavior = { ...this.behavior, daily_chat_web: value }; }),
      this.switchRow("按对话前缀做会话粘滞",
        "客户端不带会话 id 时，按对话前缀认出同一段对话并钉在同一个账号上（吃账号级 prompt cache）；关闭时只认客户端显式 id",
        this.behavior.affinity_stable_key_enabled,
        (value) => {
          this.behavior = { ...this.behavior, affinity_stable_key_enabled: value };
        }),
      h("div", { class: "grid c2", style: "margin-top:4px" }, [
        h("div", null, [
          h("div", { class: "setting-label" }, "网页活跃单账号预算"),
          h(ui.ElInputNumber, {
            modelValue: this.behavior.daily_chat_budget,
            "onUpdate:modelValue": (value) => {
              this.behavior = { ...this.behavior, daily_chat_budget: value };
            },
            min: 0, max: 7200, step: 30, style: "width:100%",
          }),
          h("div", { class: "setting-hint" },
            "秒；0 = 不限制。每轮等待与建会话退避都从总预算里扣，用完必给结论"),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "网页活跃并发数"),
          h(ui.ElInputNumber, {
            modelValue: this.behavior.daily_chat_web_concurrency,
            "onUpdate:modelValue": (value) => {
              this.behavior = { ...this.behavior, daily_chat_web_concurrency: value };
            },
            min: 1, max: 10, step: 1, style: "width:100%",
          }),
          h("div", { class: "setting-hint" },
            "1 = 逐号执行；账号较多时可调高"),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "建会话失败退避"),
          h(ui.ElInputNumber, {
            modelValue: this.behavior.daily_chat_web_retry_backoff,
            "onUpdate:modelValue": (value) => {
              this.behavior = { ...this.behavior, daily_chat_web_retry_backoff: value };
            },
            min: 0, max: 30, step: 1, style: "width:100%",
          }),
          h("div", { class: "setting-hint" },
            "秒；0 = 不退避。建会话 / 取沙箱失败后按 5→10→20 递增、30 秒封顶"),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "单账号并发上限"),
          h(ui.ElInputNumber, {
            modelValue: this.behavior.account_max_concurrent,
            "onUpdate:modelValue": (value) => {
              this.behavior = { ...this.behavior, account_max_concurrent: value };
            },
            min: 0, max: 10, step: 1, style: "width:100%",
          }),
          h("div", { class: "setting-hint" },
            "0 = 不限；开启后单个账号最多同时接 N 个对话请求，占满的账号会被跳过，全满时回 429"),
        ]),
      ]),
      h("div", { class: "setting-label", style: "margin-top:8px" },
        "网页活跃候选模型（每行一个，按顺序尝试）"),
      h(ui.ElInput, {
        modelValue: this.dailyChatModels,
        "onUpdate:modelValue": (value) => { this.dailyChatModels = value; },
        type: "textarea",
        rows: 3,
        placeholder: "留空 = 自动：首选模型 + 该渠道免费兜底",
        style: "width:100%",
      }),
      h("div", { class: "setting-hint" },
        "第一个是首选，失败后按顺序换下一个；最多 8 个，留空保持自动模式"),
      this.switchRow("网页活跃随机提示词",
        "开启后从内置 300 条与下方自定义提示词中随机抽取；关闭时仍只发 Hi",
        this.behavior.daily_chat_web_random_prompt,
        (value) => {
          this.behavior = { ...this.behavior, daily_chat_web_random_prompt: value };
        }),
      h("div", { class: "setting-label", style: "margin-top:8px" },
        "自定义提示词（每行一条，最多 200 条）"),
      h(ui.ElInput, {
        modelValue: this.dailyChatPrompts,
        "onUpdate:modelValue": (value) => { this.dailyChatPrompts = value; },
        type: "textarea",
        rows: 4,
        placeholder: "例如：今天适合做什么简单的晚餐？",
        style: "width:100%",
      }),
      this.switchRow("关闭 API Key 校验", "仅限本机/可信内网；对外暴露时不要关闭",
        this.behavior.auth_disabled,
        (value) => { this.behavior = { ...this.behavior, auth_disabled: value }; }),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.behaviorBusy,
                         onClick: this.saveBehavior }, "保存行为设置"),
      ]),
    ]);

    const identityCard = h("div", { class: "card", id: "set-identity" }, [
      cardHead("身份与模型目录", "影响出站身份声明与模型清单的可见范围", null, "settings"),
      h("div", { class: "grid c2" }, [
        h("div", null, [
          h("div", { class: "setting-label" }, "X-Private-Data（数据用途声明）"),
          h(ui.ElSelect, {
            modelValue: this.identitySettings.private_data,
            "onUpdate:modelValue": (value) => {
              this.identitySettings = { ...this.identitySettings, private_data: value };
            },
          }, { default: () => [
            h(ui.ElOption, { label: "跟随身份默认", value: "auto" }),
            h(ui.ElOption, { label: "允许参与模型优化（true）", value: "true" }),
            h(ui.ElOption, { label: "不参与模型优化（false）", value: "false" }),
          ] }),
          h("div", { class: "setting-hint" },
            "auto 保持桌面端 / VSCode / CLI 各自的原值；显式值覆盖全部身份"),
        ]),
      ]),
      this.switchRow("模型清单按 Key 过滤",
        "打开后，配了模型白名单的 Key 只会看到自己可用的模型（默认关）",
        this.identitySettings.filter_models_by_key,
        (value) => {
          this.identitySettings = { ...this.identitySettings, filter_models_by_key: value };
        }),
      this.switchRow("只列出可用模型",
        "打开后，/v1/models 与面板模型清单只显示池里至少有一个账号能服务的模型；PRO 专属模型需要付费账号（默认关）",
        this.identitySettings.models_only_available,
        (value) => {
          this.identitySettings = { ...this.identitySettings, models_only_available: value };
        }),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.identityBusy,
                         onClick: this.saveIdentitySettings }, "保存身份与目录设置"),
      ]),
    ]);

    const timeoutCard = h("div", { class: "card", id: "set-timeout" }, [
      cardHead("上游超时", "两段读超时，秒", null, "clock"),
      h("div", { class: "grid c2" }, [
        h("div", null, [
          h("div", { class: "setting-label" }, "响应头超时"),
          h(ui.ElInputNumber, {
            modelValue: this.timeouts.header,
            "onUpdate:modelValue": (value) => { this.timeouts = { ...this.timeouts, header: value }; },
            min: 5, max: 600, step: 5, style: "width:100%",
          }),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "流式空闲超时"),
          h(ui.ElInputNumber, {
            modelValue: this.timeouts.idle,
            "onUpdate:modelValue": (value) => { this.timeouts = { ...this.timeouts, idle: value }; },
            min: 10, max: 1800, step: 10, style: "width:100%",
          }),
        ]),
      ]),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.timeoutsBusy,
                         onClick: this.saveTimeouts }, "保存超时"),
      ]),
    ]);

    const promptCard = h("div", { class: "card", id: "set-prompt" }, [
      cardHead("系统提示词", "passthrough 为原样透传", null, "send"),
      h("div", { class: "grid c2" }, [
        h(ui.ElSelect, {
          modelValue: this.prompt.mode,
          "onUpdate:modelValue": (value) => { this.prompt = { ...this.prompt, mode: value }; },
        }, { default: () => [
          h(ui.ElOption, { label: "原样透传", value: "passthrough" }),
          h(ui.ElOption, { label: "替换为自定义提示词", value: "custom" }),
          h(ui.ElOption, { label: "在客户端提示词后追加", value: "append" }),
        ] }),
        h(ui.ElInput, {
          modelValue: this.prompt.file,
          "onUpdate:modelValue": (value) => { this.prompt = { ...this.prompt, file: value }; },
          placeholder: "提示词文件路径（custom / append 时使用）",
        }),
      ]),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.promptBusy,
                         onClick: this.savePrompt }, "保存提示词设置"),
        h("span", { class: "muted" }, "内容审核误杀时会自动降级为中性提示词。"),
      ]),
    ]);

    const automationCard = h("div", { class: "card", id: "set-automation" }, [
      cardHead("自动化排程", "与任务页「暂停排程」同一开关，切换即时生效", null, "calendar"),
      this.switchRow("启用自动化总开关", "关闭后所有定时任务不再自动执行，手动触发仍可用",
        this.automation.enabled !== false,
        (value) => this.toggleAutomation(value),
        this.automationBusy),
      this.automation.enabled === false
        ? h(ui.ElAlert, {
            type: "info", showIcon: true, style: "margin-top:12px",
            description: "自动化已暂停：开启总开关后，可按反代修改各任务的执行时间。",
          })
        : !this.autoChannels.length
          ? h(ui.ElAlert, {
              type: "warning", showIcon: true, style: "margin-top:12px",
              description: "后端注册表没有下发可排程的自动化任务。",
            })
          : h("div", { class: "auto-config" }, [
              h("div", { class: "auto-config-head" }, [
                h("div", { class: "auto-config-intro" }, [
                  h("div", { class: "setting-label" }, "任务执行时间"),
                  h("div", { class: "setting-hint" },
                    "先选反代，再点任务右侧「调整」；整点可多选，分钟不参与排程。"),
                ]),
                h("div", { class: "auto-channel-tabs", role: "tablist" },
                  this.autoChannels.map((channel) => h("button", {
                    key: channel.id,
                    type: "button",
                    role: "tab",
                    title: channel.label,
                    "aria-selected": channel.id === this.autoChannelId ? "true" : "false",
                    class: ["auto-channel-tab",
                      channel.id === this.autoChannelId ? "active" : ""],
                    onClick: () => this.pickAutoChannel(channel.id),
                  }, [
                    h("span", { class: "name" }, channel.tabLabel),
                    h("span", { class: "count" }, String(channel.count)),
                  ]))),
              ]),
              h("div", { class: "auto-task-list" }, this.autoTasks.map((task) => {
                const expanded = this.autoExpanded === task.id;
                const enabled = this.taskEnabled(task);
                const hours = this.hoursOf(task);
                return h("div", {
                  key: task.id,
                  class: ["auto-task-row", expanded ? "expanded" : "",
                          enabled ? "" : "is-off"],
                }, [
                  h("div", { class: "auto-task-main" }, [
                    h("div", { class: "auto-task-name" }, task.label || task.id),
                    h("div", { class: "auto-task-meta" }, [
                      h("span", {
                        class: ["dot", "auto-task-dot", enabled ? "" : "off"],
                        "aria-hidden": "true",
                      }),
                      h("span", { class: "auto-task-state" },
                        enabled ? "已启用" : "已停用"),
                      h("span", { class: "mono" }, task.id),
                      ...this.taskRealmBadges(task).map((item) =>
                        badge(item.label, "info", item.id, "mini")),
                    ]),
                  ]),
                  h("div", { class: "auto-task-side" }, [
                    h("div", { class: "auto-task-hours" }, hours.length
                      ? hours.map((hour) =>
                          h("span", { key: hour, class: "auto-hour-chip" },
                            this.hourLabel(hour)))
                      : h("span", { class: "muted" }, "未排程")),
                    h("button", {
                      type: "button",
                      class: ["auto-task-edit", expanded ? "active" : ""],
                      onClick: () => this.toggleTaskEditor(task.id),
                    }, expanded ? "收起" : "调整"),
                  ]),
                  expanded
                    ? h("div", { class: "auto-hour-editor" }, [
                        h("div", { class: "auto-hour-grid" }, HOUR_OPTIONS.map((opt) =>
                          h("button", {
                            key: opt.value,
                            type: "button",
                            class: ["auto-hour-cell",
                              hours.includes(opt.value) ? "active" : ""],
                            onClick: () => this.toggleTaskHour(task, opt.value),
                          }, opt.label))),
                        h("div", { class: "auto-hour-actions" }, [
                          h(ui.ElButton, {
                            size: "small", text: true,
                            onClick: () => this.resetTaskHours(task),
                          }, "恢复默认"),
                          h("span", { class: "muted" }, "默认 " + (
                            this.defaultHoursOf(task).map((hour) => this.hourLabel(hour))
                              .join(" · ") || "—")),
                        ]),
                      ])
                    : null,
                ]);
              })),
              h("div", { class: "auto-config-foot" }, [
                h(ui.ElButton, { loading: this.taskHoursBusy,
                                 onClick: this.saveTaskHours }, "保存任务时间"),
                h("span", { class: "muted" },
                  this.autoDirty ? "有未保存的修改" : "整点执行；每个任务至少保留一个时间点"),
              ]),
            ]),
    ]);

    const logDbCard = h("div", { class: "card", id: "set-logs" }, [
      cardHead("运行日志落库", "默认关；开启后重启也能查历史", null, "db"),
      this.switchRow("启用日志落库", "日志写入本地数据库，受下面三项上限约束",
        this.logDb.enabled,
        (value) => { this.logDb = { ...this.logDb, enabled: value }; }),
      h("div", { class: "grid c3", style: "margin-top:10px" }, [
        h("div", null, [
          h("div", { class: "setting-label" }, "最多行数"),
          h(ui.ElInputNumber, {
            modelValue: this.logDb.max_rows,
            "onUpdate:modelValue": (value) => { this.logDb = { ...this.logDb, max_rows: value }; },
            min: 1000, step: 1000, style: "width:100%", placeholder: "留空不限",
          }),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "保留天数"),
          h(ui.ElInputNumber, {
            modelValue: this.logDb.max_days,
            "onUpdate:modelValue": (value) => { this.logDb = { ...this.logDb, max_days: value }; },
            min: 1, max: 3650, style: "width:100%", placeholder: "留空不限",
          }),
        ]),
        h("div", null, [
          h("div", { class: "setting-label" }, "最大字节数"),
          h(ui.ElInputNumber, {
            modelValue: this.logDb.max_bytes,
            "onUpdate:modelValue": (value) => { this.logDb = { ...this.logDb, max_bytes: value }; },
            min: 1048576, step: 1048576, style: "width:100%", placeholder: "留空不限",
          }),
        ]),
      ]),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.logDbBusy,
                         onClick: this.saveLogDb }, "保存日志设置"),
      ]),
    ]);

    const updateCard = h("div", { class: "card", id: "set-update" }, [
      cardHead("更新检查", "同时检测全部已融合的上游源；只发现不安装，默认关", null, "refresh"),
      this.switchRow("每日检查上游更新", "开启后网关每天把注册表里的每个上游源都查一次；关闭时不发任何请求",
        this.updates.enabled === true,
        (value) => this.toggleUpdateCheck(value),
        this.updateBusy),
      h("div", { class: "toolbar", style: "margin-top:12px;margin-bottom:0" }, [
        h(ui.ElButton, { loading: this.updateBusy, onClick: this.checkUpdates }, "立即检查全部上游"),
        h("span", { class: "muted" },
          this.updates.last_success ? `上次成功：${this.updates.last_success}` : "尚未成功检查过"),
        this.updates.update_available
          ? h(StateBadge, { status: "warn", label: "有上游发布了新版本" })
          : null,
      ]),
      h(WbTable, {
        rows: this.updates.sources || [],
        style: "margin-top:10px",
        columns: [
          { label: "上游源", minWidth: 220, render: ({ row }) => h("div", null, [
              h("b", null, row.label || row.id),
              h("div", { class: "muted mono", style: "font-size:11px" }, row.repo || ""),
            ]) },
          { label: "融合基线", width: 110, render: ({ row }) =>
              h("span", { class: "mono" }, row.baseline || "—") },
          { label: "上游最新版", width: 120, render: ({ row }) =>
              h("span", { class: "mono" }, row.latest_version || "—") },
          { label: "通道", width: 150, render: ({ row }) =>
              h("span", { class: "muted", style: "font-size:11.5px" }, row.via || "—") },
          { label: "状态", minWidth: 180, render: ({ row }) => {
              if (row.update_available) {
                return h(StateBadge, { status: "warn",
                  label: `有新版本 ${row.latest_version}（基线 ${row.baseline}）` });
              }
              if (row.last_error) {
                return h(StateBadge, { status: "error", label: row.last_error });
              }
              if (row.latest_version) {
                return h(StateBadge, { status: "ok", label: "已是最新" });
              }
              return h("span", { class: "muted" }, "尚未检查");
            } },
          { label: "发布页", width: 90, render: ({ row }) => row.url
              ? h("a", { href: row.url, target: "_blank", rel: "noopener" }, "打开")
              : h("span", { class: "muted" }, "—") },
        ],
      }),
    ]);

    const pathCard = h("div", { class: "card", id: "set-paths" }, [
      cardHead("数据位置", "", null, "db"),
      h("div", { class: "setting-row" }, [
        h("div", { class: "setting-text" }, [
          h("div", { class: "setting-label" }, "账号目录"),
          h("div", { class: "setting-hint mono" }, this.data.accounts_dir || "—"),
        ]),
        h("div", { class: "setting-text" }, [
          h("div", { class: "setting-label" }, "用量与日志目录"),
          h("div", { class: "setting-hint mono" }, this.data.usage_dir || "—"),
        ]),
        h("div", { class: "setting-text" }, [
          h("div", { class: "setting-label" }, "版本"),
          h("div", { class: "setting-hint mono" }, this.data.version || "—"),
        ]),
      ]),
    ]);

    const menu = h("aside", { class: "settings-menu" }, [
      h("div", { class: "settings-menu-title" }, "设置目录"),
      ...SETTINGS_NAV.map((item) => h("button", {
        key: item.id,
        type: "button",
        class: ["settings-menu-item", this.activeSection === item.id ? "active" : ""],
        "aria-current": this.activeSection === item.id ? "true" : undefined,
        onClick: () => this.jumpTo(item.id),
      }, item.label)),
    ]);

    const body = h("div", { class: "settings-body" }, [
      panelCard,
      keyCard,
      behaviorCard,
      identityCard,
      h("div", { class: "grid c2" }, [timeoutCard, promptCard]),
      automationCard,
      logDbCard,
      updateCard,
      pathCard,
    ]);

    return h("div", null, [
      head,
      h("div", { class: "settings-layout" }, [menu, body]),
    ]);
  },
};
