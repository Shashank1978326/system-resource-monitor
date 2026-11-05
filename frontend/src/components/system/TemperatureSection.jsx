import { useEffect, useState } from "react";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getTemperatureInfo } from "../../services/api";

const REFRESH_INTERVAL_MS = 30_000;

function temperature(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(1)} °C`
    : "Unavailable";
}

export default function TemperatureSection() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    let controller;
    let timerId;

    const refresh = async () => {
      controller = new AbortController();
      try {
        const response = await getTemperatureInfo({
          signal: controller.signal,
        });
        if (active) {
          setResult(response);
          setError("");
        }
      } catch (requestError) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (active) {
          setLoading(false);
          timerId = window.setTimeout(refresh, REFRESH_INTERVAL_MS);
        }
      }
    };

    refresh();
    return () => {
      active = false;
      window.clearTimeout(timerId);
      controller?.abort();
    };
  }, [reloadKey]);

  return (
    <Panel
      title="Hardware temperatures"
      subtitle="Real sensor readings · refreshes every 30 seconds"
      className="temperature-panel"
    >
      {error && (
        <ErrorBanner
          message={error}
          onRetry={() => {
            setLoading(result === null);
            setReloadKey((key) => key + 1);
          }}
        />
      )}
      {loading && result === null ? (
        <Skeleton className="temperature-skeleton" />
      ) : result === null ? (
        <EmptyState
          title="Temperature information unavailable"
          message={error || "The temperature endpoint could not be loaded."}
        />
      ) : result.availability !== "available" ? (
        <div
          className={`temperature-status temperature-status-${result.availability}`}
          role="status"
        >
          <strong>
            {result.availability === "unsupported"
              ? "Temperature monitoring not supported"
              : "Temperature data unavailable"}
          </strong>
          <p>{result.message || "No sensor readings are currently available."}</p>
          <span>Platform: {result.platform}</span>
        </div>
      ) : result.sensors.length === 0 ? (
        <EmptyState
          title="No temperature sensors found"
          message="The platform reported no accessible hardware sensor readings."
        />
      ) : (
        <>
          <p className="temperature-platform">
            Sensor readings available · {result.platform}
          </p>
          <div className="temperature-grid">
            {result.sensors.map((sensor, index) => (
              <article
                className="temperature-card"
                key={`${sensor.sensor_name}-${sensor.label || "sensor"}-${index}`}
              >
                <div className="temperature-card-heading">
                  <div>
                    <strong>{sensor.sensor_name}</strong>
                    <span>{sensor.label || "Unlabeled sensor"}</span>
                  </div>
                  <strong className="temperature-reading">
                    {temperature(sensor.current_celsius)}
                  </strong>
                </div>
                <div className="temperature-thresholds">
                  <span>
                    High <strong>{temperature(sensor.high_celsius)}</strong>
                  </span>
                  <span>
                    Critical <strong>{temperature(sensor.critical_celsius)}</strong>
                  </span>
                  {sensor.device && (
                    <span>
                      Device <strong>{sensor.device}</strong>
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}
    </Panel>
  );
}
