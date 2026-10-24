/*
 * panel/api/panel.js —— 面板基础接口（登录态、渠道清单、运行时状态）
 */
import { api, qs } from "./client.js";

export const panelApi = {
  status: () => api.get("/panel/status"),
  login: (password) => api.post("/panel/login", { password }),
  logout: () => api.post("/panel/logout"),
  changePassword: (current, password) =>
    api.post("/panel/password", { current, password }),
  channels: () => api.get("/channels"),
  health: () => api.get("/health"),
  modelsSource: () => api.get("/models/source"),
  modelsList: (realm) => api.get(`/models/list${qs({ realm })}`),
  refreshModels: (realm) => api.post("/models/refresh", { realm }),
};
