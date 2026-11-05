import { useCallback, useEffect, useState } from "react";
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import LiveChart from "../components/charts/LiveChart";
import { errorMessage, getGpuInfo, getGpuUsage } from "../services/api";
import { formatBytes } from "../utils/format";

const GPU_REFRESH_INTERVAL_MS = 3000;
const MAX_GPU_GRAPH_POINTS = 60;

const statusLabels = {
  available: "GPU monitoring available",
  partial: "Partial GPU monitoring available",
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

function UsageProgress({ label, value, variant }) {
  const available =
    typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 100;
  return (
    <div className={`gpu-progress-row ${variant === "memory" ? "gpu-progress-memory" : ""}`}>
      <div>
        <span>{label}</span>
        <strong>{available ? `${value.toFixed(1)}%` : "Unavailable"}</strong>
      </div>
      {available && (
        <div
          className="gpu-progress-track"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={value}
        >
          <span style={{ width: `${value}%` }} />
        </div>
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
          for (const device of result.devices) {
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
            title="GPU detection"
            subtitle="Hardware detection and available monitoring providers"
            action={action}
          >
            <div className="gpu-detection-summary">
              <span
                className={`gpu-status-indicator ${gpuInfo.supported_gpu_detected ? "gpu-status-available" : ""}`}
                aria-hidden="true"
              />
              <div>
                <strong>{statusLabels[gpuInfo.status] || "GPU detection status"}</strong>
                <p>{gpuInfo.message || "GPU hardware was detected and monitoring is available."}</p>
              </div>
            </div>
            <div className="gpu-info-meta">
              <div className="info-field">
                <span>GPU monitoring</span>
                <strong>
                  {gpuInfo.monitoring_available
                    ? "Available"
                    : gpuInfo.status === "no_gpu"
                      ? "No GPU detected"
                      : "Not supported"}
                </strong>
              </div>
              <div className="info-field">
                <span>Detected devices</span>
                <strong>{gpuInfo.devices.length}</strong>
              </div>
            </div>
          </Panel>
          <Panel
            title="Live GPU usage"
            subtitle={`Updates every ${GPU_REFRESH_INTERVAL_MS / 1000} seconds · Last sample: ${sampleTime}`}
          >
            {usageError && (
              <ErrorBanner
                message={
                  gpuUsage
                    ? `${usageError} Showing the last successful readings.`
                    : usageError
                }
              />
            )}
            {usageLoading && !gpuUsage ? (
              <div className="gpu-device-grid">
                <Skeleton className="info-skeleton" />
              </div>
            ) : !gpuUsage || gpuUsage.devices.length === 0 ? (
              <EmptyState
                title={
                  gpuUsage?.status === "unsupported"
                    || gpuUsage?.status === "no_gpu"
                    ? "GPU Not Available"
                    : gpuUsage?.status === "monitoring_unsupported"
                      ? "GPU Monitoring Not Supported"
                      : "GPU Data Unavailable"
                }
                message={gpuUsage?.message || "Waiting for a GPU measurement."}
              />
            ) : (
              <div className="gpu-device-grid">
                {gpuUsage.devices.map((device) => {
                  const history = gpuHistory[device.device_index] || [];
                  const hasGpuHistory = history.some((point) => typeof point.gpu === "number");
                  const hasMemoryHistory = history.some((point) => typeof point.memory === "number");
                  return (
                    <section className="gpu-usage-card" key={device.device_index}>
                      <div className="gpu-usage-heading">
                        <div>
                          <h3>{device.name || `${device.manufacturer || "GPU"} device ${device.device_index}`}</h3>
                          <span>{device.manufacturer || "Unknown manufacturer"} · Device {device.device_index}</span>
                        </div>
                        <span
                          className={`gpu-usage-status gpu-usage-status-${device.status}`}
                        >
                          {device.status === "available"
                            ? "Available"
                            : device.status === "unsupported"
                              ? "Monitoring unsupported"
                              : device.status === "partial"
                              ? "Partial readings"
                              : "Unavailable"}
                        </span>
                      </div>
                      {!device.monitoring_supported ? (
                        <EmptyState
                          title="GPU Monitoring Not Supported"
                          message="The adapter is detected, but no compatible metrics provider is available."
                        />
                      ) : !device.available ? (
                        <EmptyState
                          title="GPU Data Unavailable"
                          message="The GPU was detected, but its measurements could not be collected."
                        />
                      ) : (
                        <>
                          <UsageProgress
                            label="GPU utilization"
                            value={device.gpu_utilization_percent}
                          />
                          <UsageProgress
                            label="VRAM utilization"
                            value={device.memory_utilization_percent}
                            variant="memory"
                          />
                          <div className="gpu-memory-values">
                            {[
                              ["Memory used", formatMegabytes(device.memory_used_mb)],
                              ["Memory free", formatMegabytes(device.memory_free_mb)],
                              ["Memory total", formatMegabytes(device.memory_total_mb)],
                              [
                                "Temperature",
                                typeof device.temperature_celsius === "number"
                                  ? `${device.temperature_celsius.toFixed(1)} °C`
                                  : "Unavailable",
                              ],
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
                                  <span className="gpu-chart-title">GPU utilization</span>
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
                                  <span className="gpu-chart-title">VRAM utilization</span>
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
                        </>
                      )}
                    </section>
                  );
                })}
              </div>
            )}
          </Panel>
          {gpuInfo.devices.length ? (
            <div className="gpu-device-grid">
              {gpuInfo.devices.map((device) => (
                <Panel
                  key={device.device_index}
                  title={device.model || `${device.manufacturer} GPU`}
                  subtitle={`${device.manufacturer} · Device ${device.device_index}`}
                >
                  <div className="info-grid">
                    <div className="info-field">
                      <span>Manufacturer</span>
                      <strong>{device.manufacturer || "Unavailable"}</strong>
                    </div>
                    {typeof device.total_memory_bytes === "number" && (
                      <div className="info-field">
                        <span>Total GPU memory</span>
                        <strong>{formatBytes(device.total_memory_bytes)}</strong>
                      </div>
                    )}
                    {device.driver_version && (
                      <div className="info-field">
                        <span>Driver version</span>
                        <strong>{device.driver_version}</strong>
                      </div>
                    )}
                  </div>
                </Panel>
              ))}
            </div>
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
