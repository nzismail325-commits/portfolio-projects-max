/*
 * panel/api/accounts.js —— 账号治理接口（列表、启停、权重、禁用模型、备注、凭据导入）
 */
import { api, qs } from "./client.js";

export const accountsApi = {
  list: (realm) => api.get(`/accounts${qs({ realm })}`),
  action: (uid, action, extra = {}) =>
    api.post("/accounts/action", { uid, action, ...extra }),
  setEnabled: (uid, enabled) =>
    api.post("/accounts/action", { uid, action: "enable", enabled }),
  setWeight: (uid, weight) =>
    api.post("/accounts/action", { uid, action: "weight", weight }),
  setDisabledModels: (uid, models) =>
    api.post("/accounts/action", { uid, action: "disabled_models", models }),
  setNote: (uid, note) =>
    api.post("/accounts/action", { uid, action: "note", note }),
  remove: (uid) => api.post("/accounts/action", { uid, action: "delete" }),
  checkin: (uid) => api.post("/accounts/action", { uid, action: "checkin" }),
  refresh: (uid) => api.post("/accounts/action", { uid, action: "refresh" }),
  clearError: (uid) => api.post("/accounts/action", { uid, action: "clear_error" }),
  syncNickname: (uid) =>
    api.post("/accounts/action", { uid, action: "sync_nickname" }),
  credits: (realm, refresh = false) =>
    api.get(`/accounts/credits${qs({ realm, refresh: refresh ? 1 : "" })}`),
  creditsDetail: (uid, refresh = false) =>
    api.get(`/accounts/credits/detail${qs({ uid, refresh: refresh ? 1 : "" })}`),
  loginStart: (realm, platform = "CLI") =>
    api.post("/accounts/login/start", { realm, platform }),
  loginPoll: (state) => api.get(`/accounts/login/poll${qs({ state })}`),
  loginSubmit: (state, callback) =>
    api.post("/accounts/login/submit", { state, callback }),
  loginAction: (state, action, values) =>
    api.post("/accounts/login/action", { state, action, values }),
  loginCancel: (state) => api.post("/accounts/login/cancel", { state }),
  syncIdentity: (uid) => api.post("/accounts/identity/sync", { uid }),
  scanDesktop: () => api.get("/accounts/import-desktop"),
  importDesktop: (payload) => api.post("/accounts/import-desktop", payload),
};

export const proxySlotApi = {
  list: (realm) => api.get(`/proxy-slots${qs({ realm })}`),
  save: (realm, slots) => api.post("/proxy-slots/save", { realm: realm || "", slots }),
  probe: (url) => api.post("/proxy-slots/probe", { url }),
  discover: () => api.post("/proxy-slots/discover", {}),
};
