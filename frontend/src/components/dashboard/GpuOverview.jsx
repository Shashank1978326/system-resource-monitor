import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getGpuUsage } from "../../services/api";

const REFRESH_INTERVAL_MS = 4000;

function metric(value, suffix = "%") {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(1)}${suffix}`
    : "Unavailable";
}

function memoryMetric(value) {
  return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function stateMessage(status) {
  if (status === "no_gpu") return "GPU Not Available";
  if (status === "monitoring_unsupported" || status === "unsupported") {
    return "GPU Monitoring Not Supported";
  }
  return "GPU Data Unavailable";
}

function resolveActivity(device) {
  if (device.activity_status) return device.activity_status;
  if (
    typeof device.gpu_utilization_percent === "number" &&
    Number.isFinite(device.gpu_utilization_percent)
  ) {
    return device.gpu_utilization_percent >= 1 ? "Active" : "Idle";
  }
  return device.available ? "Idle" : "Unavailable";
}

function activityClass(activity) {
  const normalized = String(activity || "").toLowerCase();
  if (normalized === "active") return "gpu-activity-active";
  if (normalized === "idle") return "gpu-activity-idle";
  return "gpu-activity-unavailable";
}

export default function GpuOverview() {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer;
    const controller = new AbortController();

    const refresh = async () => {
      try {
        const result = await getGpuUsage({ signal: controller.signal });
        if (!active) return;
        setUsage(result);
        setError("");
      } catch (requestError) {
        if (
          active &&
          requestError.name !== "CanceledError" &&
          requestError.name !== "AbortError"
        ) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (active) {
          setLoading(false);
          timer = window.setTimeout(refresh, REFRESH_INTERVAL_MS);
        }
      }
    };

    refresh();
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, []);

  const hasAvailableDevice = usage?.devices?.some((device) => device.available);
  const unavailableTitle = error
    ? "GPU Data Unavailable"
    : stateMessage(usage?.status);
  const unavailableMessage = error || usage?.message || "GPU readings are not available.";

  return (
    <Panel
      title="Multi-GPU monitoring"
      subtitle="Simultaneous independent telemetry · refreshes every 4 seconds"
      action={<Link className="panel-link" to="/gpu">View GPUs ↗</Link>}
    >
      {error && <ErrorBanner message={error} />}
      {loading && !usage ? (
        <div className="gpu-overview-loading">
          <Skeleton className="skeleton-line" />
          <Skeleton className="skeleton-line" />
        </div>
      ) : !usage?.devices?.length ? (
        <EmptyState title={unavailableTitle} message={unavailableMessage} />
      ) : (
        <>
          {!hasAvailableDevice && (
            <p className="gpu-overview-status" role="status">
              {stateMessage(usage.status)}
            </p>
          )}
          <div className="gpu-overview-list">
            {usage.devices.map((device) => {
              const vendor = device.vendor || device.manufacturer || "Unknown";
              const gpuType = device.gpu_type || "Unknown";
              const isIntegrated = gpuType === "Integrated";
              const activity = resolveActivity(device);

              return (
                <div className="gpu-overview-device" key={device.device_index}>
                  <div className="gpu-overview-device-heading">
                    <div>
                      <strong>
                        {device.name || `${vendor} device ${device.device_index}`}
                      </strong>
                      <span>
                        {vendor} · {gpuType}
                      </span>
                    </div>
                    <span className={`gpu-activity-badge ${activityClass(activity)}`}>
                      <span className="gpu-activity-dot" aria-hidden="true" />
                      {activity}
                    </span>
                  </div>
                  {device.available ? (
                    <div className="gpu-overview-metrics">
                      <span>
                        Utilization <strong>{metric(device.gpu_utilization_percent)}</strong>
                      </span>
                      {(typeof device.memory_used_mb === "number" ||
                        typeof device.memory_total_mb === "number") && (
                        <span>
                          {isIntegrated ? "Shared RAM" : "VRAM"}
                          {typeof device.memory_used_mb === "number" && (
                            <strong> {memoryMetric(device.memory_used_mb)} MB</strong>
                          )}
                          {typeof device.memory_total_mb === "number" && (
                            <strong> / {memoryMetric(device.memory_total_mb)} MB</strong>
                          )}
                        </span>
                      )}
                      {typeof device.temperature_celsius === "number" && (
                        <span>
                          Temp{" "}
                          <strong>{metric(device.temperature_celsius, " °C")}</strong>
                        </span>
                      )}
                      {typeof device.power_usage_watts === "number" && (
                        <span>
                          Power <strong>{metric(device.power_usage_watts, " W")}</strong>
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="gpu-overview-unavailable">
                      {device.status === "unsupported"
                        ? "GPU Monitoring Not Supported"
                        : "GPU Data Unavailable"}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </Panel>
  );
}
