/*
 * panel/api/channels.js —— 渠道聚合（前端唯一渠道真相）
 *
 * 页面/页签/按钮只按后端注册表下发的清单渲染：渠道未注册或停用一律不出现，
 * 不留死入口。接入新渠道时这里不用改，新渠道会自然出现在清单里。
 */
import { api } from "./client.js";

const CAP_LABELS = {
  chat: "对话",
  responses: "Responses",
  messages: "Messages",
  models: "模型目录",
  accounts: "账号治理",
  checkin: "签到",
  daily_chat: "每日活跃",
  tasks: "任务福利",
  scheduler: "定时任务",
  proxy_slot: "代理槽",
  export: "账号导出",
};

/** 签到动作的默认文案；渠道可在 panel_meta.checkin_labels 覆盖。 */
const CHECKIN_LABELS = {
  action: "签到",
  pending: "未签到",
  done: "已签到",
  pendingTitle: "今日尚未签到（「签到」按钮或定时任务会补上）",
  doneTitle: "今日已签到：",
  submitted: "签到已提交",
};

export const channelsApi = {
  async load() {
    const data = await api.get("/channels");
    return {
      channels: data.channels || [],
      realms: data.realms || [],
      currentRealm: data.current_realm || "",
      schedulerTasks: data.scheduler_tasks || [],
    };
  },
  capLabel: (cap) => CAP_LABELS[cap] || cap,
  /** 签到/领取动作的渠道化文案：未声明时回退默认签到文案。 */
  checkinLabels(channel) {
    return { ...CHECKIN_LABELS, ...((channel && channel.checkin_labels) || {}) };
  },
  /** 某渠道是否声明了某能力（按钮/页签据此渲染）。 */
  supports(channel, cap) {
    return Boolean(channel && (channel.capabilities || []).includes(cap));
  },
  /** 按渠道自己声明的能力，给出该渠道下可用的出口列表。 */
  realmsOf(channel) {
    return (channel?.realms || [])
      .filter((item) => item && item.id)
      .map((item) => ({
        ...item,
        capabilities: item.capabilities || channel.capabilities || [],
      }));
  },
};
