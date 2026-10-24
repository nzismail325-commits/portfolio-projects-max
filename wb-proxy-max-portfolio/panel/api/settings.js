/*
 * panel/api/settings.js —— 设置接口（含 API Key、自动化、提示词、日志落库、更新检查）
 */
import { api, qs } from "./client.js";

export const settingsApi = {
  get: () => api.get("/settings"),
  save: (patch) => api.post("/settings/save", patch),
  revealKey: (id) => api.get(`/settings/reveal${qs({ id })}`),
  updates: () => api.get("/updates"),
  checkUpdates: () => api.post("/updates"),
  logs: (params = {}) => api.get(`/logs${qs(params)}`),
};
