import axios from "axios";

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000"
).replace(/\/+$/, "");

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
  headers: { Accept: "application/json" },
});

export async function getInitialMonitoringData() {
  const [health, snapshot, status, systemInfo] = await Promise.allSettled([
    api.get("/api/health"),
    api.get("/api/monitoring/latest"),
    api.get("/api/monitoring/status"),
    api.get("/api/system/info"),
  ]);
  return {
    backendReachable: health.status === "fulfilled",
    snapshot: snapshot.status === "fulfilled" ? snapshot.value.data : null,
    status: status.status === "fulfilled" ? status.value.data : null,
    systemInfo: systemInfo.status === "fulfilled" ? systemInfo.value.data : null,
    systemInfoError:
      systemInfo.status === "rejected" ? errorMessage(systemInfo.reason) : null,
    error:
      health.status === "rejected"
        ? errorMessage(health.reason)
        : snapshot.status === "rejected"
          ? errorMessage(snapshot.reason)
          : null,
  };
}

export async function getGpuInfo({ signal } = {}) {
  const { data } = await api.get("/api/gpu/info", { signal });
  return data;
}

export async function getGpuUsage({ signal } = {}) {
  const { data } = await api.get("/api/gpu/usage", { signal });
  return data;
}

export async function getTemperatureInfo({ signal } = {}) {
  const { data } = await api.get("/api/temperature", { signal });
  return data;
}

export async function getBatteryInfo({ signal } = {}) {
  const { data } = await api.get("/api/battery", { signal });
  return data;
}

export async function getDiskIo({ signal } = {}) {
  const { data } = await api.get("/api/disk/io", { signal });
  return data;
}

export async function getNetworkInterfaces({ signal } = {}) {
  const { data } = await api.get("/api/network/interfaces", { signal });
  return data;
}

export async function getNetworkInterfaceTraffic({ signal } = {}) {
  const { data } = await api.get("/api/network/interfaces/traffic", { signal });
  return data;
}

export async function getHistoryGraph(
  metric,
  range,
  interval,
  { interfaceName, sensorId, signal } = {},
) {
  const { data } = await api.get("/api/history/graph", {
    params: {
      metric,
      range,
      interval,
      interface: interfaceName || undefined,
      sensor_id: sensorId || undefined,
    },
    signal,
  });
  return data;
}

export async function getHistoricalNetworkInterfaces({ signal } = {}) {
  const { data } = await api.get("/api/history/interfaces", { signal });
  return data;
}

export async function getHistoricalTemperatureSensors({ signal } = {}) {
  const { data } = await api.get("/api/history/temperature-sensors", { signal });
  return data;
}

export async function getProcesses({
  search = "",
  status = "",
  limit = 500,
  sortBy = "pid",
  sortOrder = "asc",
  signal,
} = {}) {
  const { data } = await api.get("/api/processes", {
    params: {
      search: search || undefined,
      status: status || undefined,
      limit,
      sort_by: sortBy,
      sort_order: sortOrder,
    },
    signal,
  });
  return data;
}

export async function getProcessDetail(pid, { signal } = {}) {
  const { data } = await api.get(`/api/processes/${pid}`, { signal });
  return data;
}

export async function getAlerts({ signal } = {}) {
  const { data } = await api.get("/api/alerts", { signal });
  return data;
}

export async function getAlertThresholds({ signal } = {}) {
  const { data } = await api.get("/api/alerts/thresholds", { signal });
  return data;
}

export async function updateAlertThresholds(thresholds) {
  const { data } = await api.put("/api/alerts/thresholds", thresholds);
  return data;
}

export async function getAlertHistory({
  resource,
  severity,
  limit = 20,
  offset = 0,
  signal,
} = {}) {
  const { data } = await api.get("/api/alerts/history", {
    params: {
      resource: resource || undefined,
      severity: severity || undefined,
      limit,
      offset,
    },
    signal,
  });
  return data;
}

export async function acknowledgeAlert(alertId) {
  const { data } = await api.patch(`/api/alerts/${alertId}/acknowledge`);
  return data;
}

export async function deleteAlert(alertId) {
  await api.delete(`/api/alerts/${alertId}`);
}

export async function clearAlertHistory() {
  const { data } = await api.delete("/api/alerts/history");
  return data;
}

export async function getAnomalies({ signal } = {}) {
  const { data } = await api.get("/api/anomalies", { signal });
  return data;
}

export async function getAnomalySettings({ signal } = {}) {
  const { data } = await api.get("/api/anomalies/settings", { signal });
  return data;
}

export async function updateAnomalySettings(settings) {
  const { data } = await api.put("/api/anomalies/settings", settings);
  return data;
}

export async function getAnomalyHistory({
  resource,
  metric,
  severity,
  limit = 50,
  offset = 0,
  signal,
} = {}) {
  const { data } = await api.get("/api/anomalies/history", {
    params: {
      resource: resource || undefined,
      metric: metric || undefined,
      severity: severity || undefined,
      limit,
      offset,
    },
    signal,
  });
  return data;
}

export async function deleteAnomalyEvent(eventId) {
  await api.delete(`/api/anomalies/${eventId}`);
}

export async function clearAnomalyHistory() {
  const { data } = await api.delete("/api/anomalies/history");
  return data;
}

export async function getAnomalyAnalytics({
  range = "24h",
  resource,
  metric,
  severity,
  interval,
  signal,
} = {}) {
  const { data } = await api.get("/api/anomalies/analytics", {
    params: {
      range,
      resource: resource || undefined,
      metric: metric || undefined,
      severity: severity || undefined,
      interval: interval || undefined,
    },
    signal,
  });
  return data;
}

export async function getPredictions({
  resource,
  horizon = "15m",
  signal,
} = {}) {
  const { data } = await api.get("/api/predictions", {
    params: {
      resource: resource || undefined,
      horizon,
    },
    signal,
  });
  return data;
}

export async function getPredictionAnalytics({
  resource,
  metric,
  horizon,
  range = "24h",
  signal,
} = {}) {
  const { data } = await api.get("/api/predictions/analytics", {
    params: {
      resource: resource || undefined,
      metric: metric || undefined,
      horizon: horizon || undefined,
      range: range || undefined,
    },
    signal,
  });
  return data;
}

export async function getPredictionAccuracy({
  resource,
  horizon,
  range = "24h",
  signal,
} = {}) {
  const { data } = await api.get("/api/predictions/accuracy", {
    params: {
      resource: resource || undefined,
      horizon: horizon || undefined,
      range: range || undefined,
    },
    signal,
  });
  return data;
}

export async function getPredictionHistory({
  resource,
  metric,
  horizon,
  status,
  page = 1,
  pageSize = 20,
  signal,
} = {}) {
  const { data } = await api.get("/api/predictions/history", {
    params: {
      resource: resource || undefined,
      metric: metric || undefined,
      horizon: horizon || undefined,
      status: status || undefined,
      page,
      page_size: pageSize,
    },
    signal,
  });
  return data;
}

export async function downloadPdfReport({
  range = "24h",
  type = "all",
  signal,
} = {}) {
  const response = await api.get("/api/reports/pdf", {
    params: { range, type },
    responseType: "blob",
    signal,
  });
  return response;
}

export function errorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail?.message) return detail.message;
  if (error?.code === "ECONNABORTED") {
    return "The backend took too long to respond. Try again.";
  }
  if (error?.message === "Network Error") {
    return "Cannot reach the backend. Check that the API is running.";
  }
  return error?.message || "Something went wrong while contacting the backend.";
}
