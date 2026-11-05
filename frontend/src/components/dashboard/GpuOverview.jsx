import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getGpuUsage } from "../../services/api";

const REFRESH_INTERVAL_MS = 5000;

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
      title="GPU monitoring"
      subtitle="Optional hardware readings · refreshes every 5 seconds"
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
            {usage.devices.map((device) => (
              <div className="gpu-overview-device" key={device.device_index}>
                <div className="gpu-overview-device-heading">
                  <strong>
                    {device.name || `${device.manufacturer || "GPU"} device ${device.device_index}`}
                  </strong>
                  <span>{device.manufacturer || "Unknown"}</span>
                </div>
                {device.available ? (
                  <div className="gpu-overview-metrics">
                    {typeof device.gpu_utilization_percent === "number" && (
                      <span>
                        Utilization <strong>{metric(device.gpu_utilization_percent)}</strong>
                      </span>
                    )}
                    {(typeof device.memory_used_mb === "number" ||
                      typeof device.memory_total_mb === "number") && (
                      <span>
                        VRAM
                        {typeof device.memory_used_mb === "number" && (
                          <strong> used {memoryMetric(device.memory_used_mb)} MB</strong>
                        )}
                        {typeof device.memory_total_mb === "number" && (
                          <strong> total {memoryMetric(device.memory_total_mb)} MB</strong>
                        )}
                      </span>
                    )}
                    {typeof device.temperature_celsius === "number" && (
                      <span>
                        Temperature{" "}
                        <strong>{metric(device.temperature_celsius, " °C")}</strong>
                      </span>
                    )}
                    <span>
                      Power <strong>{metric(device.power_usage_watts, " W")}</strong>
                    </span>
                    <span>
                      Power limit <strong>{metric(device.power_limit_watts, " W")}</strong>
                    </span>
                  </div>
                ) : (
                  <span className="gpu-overview-unavailable">
                    {device.status === "unsupported"
                      ? "GPU Monitoring Not Supported"
                      : "GPU Data Unavailable"}
                  </span>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}
