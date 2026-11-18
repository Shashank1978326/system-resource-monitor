import { useCallback, useEffect, useState } from "react";
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import LiveChart from "../components/charts/LiveChart";
import { errorMessage, getGpuInfo, getGpuUsage } from "../services/api";
import { formatBytes } from "../utils/format";

const GPU_REFRESH_INTERVAL_MS = 3000;
const MAX_GPU_GRAPH_POINTS = 60;

const statusLabels = {
  available: "Multi-GPU monitoring available",
  partial: "Multi-GPU monitoring active (partial sensor telemetry)",
  unsupported: "GPU Monitoring Not Supported",
  monitoring_unsupported: "GPU Monitoring Not Supported",
  library_unavailable: "GPU Monitoring Not Supported",
  initialization_error: "GPU Monitoring Not Supported",
  device_info_unavailable: "GPU Data Unavailable",
  detection_error: "GPU Data Unavailable",
  no_gpu: "GPU Not Available",
};

const unavailableDetails = {
  no_gpu: {
    title: "GPU Not Available",
    message: "No GPU was detected on this computer.",
  },
  monitoring_unsupported: {
    title: "GPU Monitoring Not Supported",
    message: "A GPU was detected, but no compatible monitoring provider is available.",
  },
  unsupported: {
    title: "GPU Monitoring Not Supported",
    message: "A GPU was detected, but no compatible monitoring provider is available.",
  },
  detection_error: {
    title: "GPU Data Unavailable",
    message: "The operating system could not determine GPU hardware information.",
  },
  device_info_unavailable: {
    title: "GPU Data Unavailable",
    message: "GPU hardware was detected, but its details could not be retrieved.",
  },
};

function formatMegabytes(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} MB`
    : "Unavailable";
}

function formatWatts(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} W`
    : "Unavailable";
}

function formatClock(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${Math.round(value).toLocaleString()} MHz`
    : "Unavailable";
}

function vendorClassName(vendor) {
  const normalized = String(vendor || "").toLowerCase();
  if (normalized.includes("nvidia")) return "gpu-badge-vendor-nvidia";
  if (normalized.includes("intel")) return "gpu-badge-vendor-intel";
  if (normalized.includes("amd")) return "gpu-badge-vendor-amd";
  return "";
}

function resolveActivityStatus(device) {
  if (device.activity_status) return device.activity_status;
  if (
    typeof device.gpu_utilization_percent === "number" &&
    Number.isFinite(device.gpu_utilization_percent)
  ) {
    return device.gpu_utilization_percent >= 1 ? "Active" : "Idle";
  }
  return device.available ? "Idle" : "Unavailable";
}

function activityClassName(activity) {
  const normalized = String(activity || "").toLowerCase();
  if (normalized === "active") return "gpu-activity-active";
  if (normalized === "idle") return "gpu-activity-idle";
  return "gpu-activity-unavailable";
}

function UsageProgress({ label, value, variant }) {
  const available =
    typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
  return (
    <div className={`gpu-progress-row ${variant === "memory" ? "gpu-progress-memory" : ""}`}>
      <div>
        <span>{label}</span>
        <strong>{available ? `${value.toFixed(1)}%` : "Unavailable"}</strong>
      </div>
      {available ? (
        <div
          className="gpu-progress-track"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={value}
        >
          <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
        </div>
      ) : (
        <div className="gpu-progress-track gpu-progress-unavailable" aria-hidden="true" />
      )}
    </div>
  );
}

export default function GpuInfo() {
  const [gpuInfo, setGpuInfo] = useState(null);
  const [gpuUsage, setGpuUsage] = useState(null);
  const [gpuHistory, setGpuHistory] = useState({});
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(true);
  const [error, setError] = useState("");
  const [usageError, setUsageError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const loadGpuInfo = useCallback(async (signal) => {
    setLoading(true);
    setError("");
    try {
      const result = await getGpuInfo({ signal });
      setGpuInfo(result);
    } catch (requestError) {
      if (requestError.name !== "CanceledError" && requestError.name !== "AbortError") {
        setError(errorMessage(requestError));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    loadGpuInfo(controller.signal);
    return () => controller.abort();
  }, [loadGpuInfo, refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    let timer;
    setUsageLoading(true);
    setUsageError("");

    const sample = async () => {
      try {
        const result = await getGpuUsage({ signal: controller.signal });
        if (!active) return;
        setGpuUsage(result);
        setUsageError("");
        const time = new Date(result.timestamp).toLocaleTimeString();
        setGpuHistory((current) => {
          const next = { ...current };
          for (const device of result.devices || []) {
            const points = current[device.device_index] || [];
            if (points.length && points[points.length - 1].timestamp === result.timestamp) {
              continue;
            }
            next[device.device_index] = [
              ...points,
              {
                timestamp: result.timestamp,
                time,
                gpu: device.gpu_utilization_percent,
                memory: device.memory_utilization_percent,
              },
            ].slice(-MAX_GPU_GRAPH_POINTS);
          }
          return next;
        });
      } catch (requestError) {
        if (
          active &&
          requestError.name !== "CanceledError" &&
          requestError.name !== "AbortError"
        ) {
          setUsageError(errorMessage(requestError));
        }
      } finally {
        if (active) {
          setUsageLoading(false);
          timer = window.setTimeout(sample, GPU_REFRESH_INTERVAL_MS);
        }
      }
    };

    sample();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [refreshKey]);

  const retry = () => setRefreshKey((current) => current + 1);
  const action = (
    <button className="process-refresh" type="button" onClick={retry} disabled={loading}>
      {loading ? "Checking..." : "Refresh"}
    </button>
  );
  const sampleTime = gpuUsage?.timestamp
    ? new Date(gpuUsage.timestamp).toLocaleTimeString()
    : "Waiting for first sample";

  const usageDevices = gpuUsage?.devices || [];
  const activeCount = usageDevices.filter(
    (device) => resolveActivityStatus(device) === "Active"
  ).length;
  const idleCount = usageDevices.filter(
    (device) => resolveActivityStatus(device) === "Idle"
  ).length;

  return (
    <div className="gpu-page">
      {error && <ErrorBanner message={error} onRetry={retry} />}
      {loading && !gpuInfo ? (
        <div className="system-info-grid">
          <Skeleton className="info-skeleton" />
          <Skeleton className="info-skeleton" />
        </div>
      ) : error && !gpuInfo ? (
        <Panel title="GPU detection" action={action}>
          <EmptyState title="GPU information unavailable" message={error} />
        </Panel>
      ) : gpuInfo ? (
        <>
          <Panel
            title="GPU hardware detection"
            subtitle="All installed display adapters are detected independently of current workload"
            action={action}
          >
            <div className="gpu-detection-summary">
              <span
                className={`gpu-status-indicator ${
                  gpuInfo.supported_gpu_detected ? "gpu-status-available" : ""
                }`}
                aria-hidden="true"
              />
              <div>
                <strong>{statusLabels[gpuInfo.status] || "GPU detection status"}</strong>
                <p>
                  {gpuInfo.message ||
                    "All detected GPU adapters are monitored independently in real time."}
                </p>
              </div>
            </div>
            <div className="gpu-info-meta">
              <div className="info-field">
                <span>Detected adapters</span>
                <strong>{gpuInfo.devices.length}</strong>
              </div>
              <div className="info-field">
                <span>Workload activity</span>
                <strong>
                  {usageDevices.length
                    ? `${activeCount} Active · ${idleCount} Idle`
                    : "Sampling..."}
                </strong>
              </div>
              <div className="info-field">
                <span>Monitoring status</span>
                <strong>
                  {gpuInfo.monitoring_available ? "Active" : "Unsupported"}
                </strong>
              </div>
              <div className="info-field">
                <span>Last telemetry sample</span>
                <strong>{sampleTime}</strong>
              </div>
            </div>
          </Panel>

          <Panel
            title="Simultaneous multi-GPU telemetry"
            subtitle={`Independent real-time monitoring for every installed GPU · refreshes every ${
              GPU_REFRESH_INTERVAL_MS / 1000
            }s`}
          >
            {usageError && <ErrorBanner message={usageError} onRetry={retry} />}
            {usageLoading && !gpuUsage ? (
              <div className="gpu-device-grid">
                <Skeleton className="info-skeleton" />
                <Skeleton className="info-skeleton" />
              </div>
            ) : !usageDevices.length ? (
              <EmptyState
                title={
                  unavailableDetails[gpuUsage?.status || gpuInfo.status]?.title ||
                  "GPU Data Unavailable"
                }
                message={
                  gpuUsage?.message ||
                  unavailableDetails[gpuUsage?.status || gpuInfo.status]?.message
                }
              />
            ) : (
              <div className="gpu-device-grid">
                {usageDevices.map((device) => {
                  const vendor = device.vendor || device.manufacturer || "Unknown";
                  const gpuType = device.gpu_type || "Unknown";
                  const isIntegrated = gpuType === "Integrated";
                  const activity = resolveActivityStatus(device);
                  const history = gpuHistory[device.device_index] || [];
                  const hasGpuHistory = history.some(
                    (point) => typeof point.gpu === "number" && Number.isFinite(point.gpu)
                  );
                  const hasMemoryHistory = history.some(
                    (point) =>
                      typeof point.memory === "number" && Number.isFinite(point.memory)
                  );

                  return (
                    <section className="gpu-usage-card" key={device.device_index}>
                      <div className="gpu-usage-heading">
                        <div>
                          <h3>
                            {device.name || `${vendor} GPU ${device.device_index}`}
                          </h3>
                          <div className="gpu-badge-row">
                            <span className={`gpu-badge ${vendorClassName(vendor)}`}>
                              {vendor}
                            </span>
                            <span className="gpu-badge">{gpuType}</span>
                            <span className="gpu-badge">GPU {device.device_index}</span>
                          </div>
                        </div>
                        <span
                          className={`gpu-activity-badge ${activityClassName(activity)}`}
                          title={`Hardware telemetry state: ${activity}`}
                        >
                          <span className="gpu-activity-dot" aria-hidden="true" />
                          {activity}
                        </span>
                      </div>

                      {device.status === "unsupported" && !device.available ? (
                        <EmptyState
                          title="GPU Monitoring Not Supported"
                          message="Hardware telemetry counters are unavailable for this adapter."
                        />
                      ) : (
                        <>
                          <UsageProgress
                            label="GPU utilization"
                            value={device.gpu_utilization_percent}
                          />
                          <UsageProgress
                            label={
                              isIntegrated
                                ? "Shared GPU memory utilization"
                                : "Dedicated VRAM utilization"
                            }
                            value={device.memory_utilization_percent}
                            variant="memory"
                          />
                          <div className="gpu-memory-values">
                            {[
                              [
                                isIntegrated ? "Shared memory used" : "Dedicated VRAM used",
                                formatMegabytes(device.memory_used_mb),
                              ],
                              [
                                isIntegrated ? "Shared memory free" : "Dedicated VRAM free",
                                formatMegabytes(device.memory_free_mb),
                              ],
                              [
                                isIntegrated ? "Shared memory total" : "Dedicated VRAM total",
                                formatMegabytes(device.memory_total_mb),
                              ],
                              ...(!isIntegrated &&
                              (typeof device.shared_memory_used_mb === "number" ||
                                typeof device.shared_memory_total_mb === "number")
                                ? [
                                    [
                                      "Shared memory",
                                      `${formatMegabytes(device.shared_memory_used_mb)} / ${formatMegabytes(
                                        device.shared_memory_total_mb
                                      )}`,
                                    ],
                                  ]
                                : []),
                              [
                                "Temperature",
                                typeof device.temperature_celsius === "number"
                                  ? `${device.temperature_celsius.toFixed(1)} °C`
                                  : "Unavailable",
                              ],
                              ["Clock speed", formatClock(device.clock_speed_mhz)],
                              ["Power consumption", formatWatts(device.power_usage_watts)],
                              ["Power limit", formatWatts(device.power_limit_watts)],
                            ].map(([label, value]) => (
                              <div key={label}>
                                <span>{label}</span>
                                <strong>{value}</strong>
                              </div>
                            ))}
                          </div>
                          {(hasGpuHistory || hasMemoryHistory) && (
                            <div className="gpu-chart-grid">
                              {hasGpuHistory && (
                                <div>
                                  <span className="gpu-chart-title">
                                    GPU utilization (%)
                                  </span>
                                  <LiveChart
                                    data={history}
                                    metric="gpu"
                                    unit="%"
                                    showAxis
                                    height={150}
                                  />
                                </div>
                              )}
                              {hasMemoryHistory && (
                                <div>
                                  <span className="gpu-chart-title">
                                    {isIntegrated
                                      ? "Shared memory (%)"
                                      : "Dedicated VRAM (%)"}
                                  </span>
                                  <LiveChart
                                    data={history}
                                    metric="memory"
                                    unit="%"
                                    showAxis
                                    height={150}
                                  />
                                </div>
                              )}
                            </div>
                          )}
                          <div className="gpu-method-note">
                            <span>
                              Provider: {device.monitoring_method || "System Detection"}
                            </span>
                            {device.driver_version && (
                              <span>Driver: {device.driver_version}</span>
                            )}
                          </div>
                        </>
                      )}
                    </section>
                  );
                })}
              </div>
            )}
          </Panel>

          {gpuInfo.devices.length ? (
            <Panel
              title="Installed GPU hardware inventory"
              subtitle="Physical graphics hardware specifications detected by the operating system"
            >
              <div className="gpu-device-grid">
                {gpuInfo.devices.map((device) => {
                  const vendor = device.vendor || device.manufacturer || "Unknown";
                  const gpuType = device.gpu_type || "Unknown";
                  return (
                    <section className="gpu-usage-card" key={`inv-${device.device_index}`}>
                      <div className="gpu-usage-heading">
                        <div>
                          <h3>{device.model || `${vendor} GPU`}</h3>
                          <div className="gpu-badge-row">
                            <span className={`gpu-badge ${vendorClassName(vendor)}`}>
                              {vendor}
                            </span>
                            <span className="gpu-badge">{gpuType}</span>
                          </div>
                        </div>
                      </div>
                      <div className="info-grid">
                        <div className="info-field">
                          <span>Vendor</span>
                          <strong>{vendor}</strong>
                        </div>
                        <div className="info-field">
                          <span>Architecture type</span>
                          <strong>{gpuType}</strong>
                        </div>
                        <div className="info-field">
                          <span>Dedicated VRAM</span>
                          <strong>
                            {typeof device.total_memory_bytes === "number"
                              ? formatBytes(device.total_memory_bytes)
                              : "Shared System RAM"}
                          </strong>
                        </div>
                        {typeof device.shared_memory_bytes === "number" && (
                          <div className="info-field">
                            <span>Shared system memory</span>
                            <strong>{formatBytes(device.shared_memory_bytes)}</strong>
                          </div>
                        )}
                        <div className="info-field">
                          <span>Driver version</span>
                          <strong>{device.driver_version || "Unavailable"}</strong>
                        </div>
                      </div>
                    </section>
                  );
                })}
              </div>
            </Panel>
          ) : (
            <Panel title="GPU devices">
              <EmptyState
                title={
                  unavailableDetails[gpuInfo.status]?.title ||
                  (gpuInfo.message ? "GPU Data Unavailable" : "GPU Not Available")
                }
                message={gpuInfo.message || unavailableDetails[gpuInfo.status]?.message}
              />
            </Panel>
          )}
        </>
      ) : null}
    </div>
  );
}
