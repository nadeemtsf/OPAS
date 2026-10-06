import axios from "axios";

export const http = axios.create();
const started = new WeakMap<object, number>();

http.interceptors.request.use(config => {
  started.set(config, performance.now());
  console.info("[OPAS] Request started", { method: config.method, url: config.url, parameters: config.params });
  return config;
});
http.interceptors.response.use(response => {
  console.info("[OPAS] Request completed", {
    url: response.config.url, httpStatus: response.status,
    requestId: response.headers["x-request-id"],
    elapsedSeconds: (performance.now()-(started.get(response.config) ?? performance.now()))/1000,
    candidates: response.data.candidates_checked ?? response.data.count,
    result: response.data.status,
  });
  return response;
}, error => {
  console.error("[OPAS] Request failed", {
    url: error.config?.url, httpStatus: error.response?.status,
    requestId: error.response?.headers?.["x-request-id"], detail: error.response?.data?.detail ?? error.message,
  });
  return Promise.reject(error);
});
