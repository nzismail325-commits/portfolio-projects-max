/*
 * panel/api/usage.js —— 代理链路用量与性能接口（看板数据源）
 *
 * 全部按渠道（realm）过滤：调用方要么传具体出口，要么接受后端标注为空
 * （= 汇总）。看板不会把两个渠道的数据拼成一行。
 */
import { api, qs } from "./client.js";

export const usageApi = {
  snapshot: (realm) => api.get(`/usage${qs({ realm })}`),
  recent: (realm, limit = 100) => api.get(`/usage/recent${qs({ realm, limit })}`),
  perf: (realm, sample = 5000) => api.get(`/usage/perf${qs({ realm, sample })}`),
  byAccount: () => api.get("/usage/by-account"),
  timeseries: (realm, days = 14) =>
    api.get(`/usage/timeseries${qs({ realm, days })}`),
  analytics: () => api.get("/usage/analytics"),
};
