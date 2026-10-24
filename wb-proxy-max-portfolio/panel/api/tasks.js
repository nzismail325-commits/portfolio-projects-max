/*
 * panel/api/tasks.js —— 任务与福利接口（成长进度、一键作业、调度状态、任务流水）
 */
import { api, qs } from "./client.js";

export const tasksApi = {
  progress: () => api.get("/tasks"),
  startGrowthJob: (realm) => api.post("/tasks/job", { realm }),
  job: (jobId) => api.get(`/tasks/job${qs({ job_id: jobId })}`),
  scheduler: () => api.get("/scheduler"),
  trigger: (task = "all") => api.post("/scheduler", { task }),
  records: (params = {}) => api.get(`/scheduler/records${qs(params)}`),
  activity: (params = {}) => api.get(`/activity/history${qs(params)}`),
};
