import { useEffect, useState } from "react";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getBatteryInfo } from "../../services/api";

const REFRESH_INTERVAL_MS = 30_000;

const chargingLabels = {
  charging: "Charging",
  discharging: "Discharging",
  not_charging: "Not charging",
  unknown: "Charging status unknown",
};

export default function BatterySection() {
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
        const response = await getBatteryInfo({ signal: controller.signal });
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

  const percentage =
    typeof result?.percentage === "number" &&
    Number.isFinite(result.percentage)
      ? result.percentage
      : null;

  return (
    <Panel
      title="Battery information"
      subtitle="Battery status · refreshes every 30 seconds"
      className="battery-panel"
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
        <Skeleton className="battery-skeleton" />
      ) : result === null ? (
        <EmptyState
          title="Battery information unavailable"
          message={error || "The battery endpoint could not be loaded."}
        />
      ) : result.availability !== "available" ? (
        <div
          className={`battery-status battery-status-${result.availability}`}
          role="status"
        >
          <strong>
            {result.availability === "unsupported"
              ? "Battery monitoring not supported"
              : "Battery unavailable"}
          </strong>
          <p>{result.message}</p>
          <span>Platform: {result.platform}</span>
        </div>
      ) : (
        <div className="battery-details">
          <div
            className={`battery-indicator battery-indicator-${result.charging_state}${percentage === null ? " battery-indicator-unknown" : ""}`}
            role="progressbar"
            aria-label="Battery level"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuetext={
              percentage === null ? "Battery level unavailable" : `${percentage}%`
            }
            {...(percentage === null ? {} : { "aria-valuenow": percentage })}
          >
            <span className="battery-indicator-body">
              {percentage !== null && (
                <span
                  className="battery-indicator-fill"
                  style={{ width: `${percentage}%` }}
                />
              )}
              {result.charging_state === "charging" && (
                <span className="battery-indicator-charge" aria-hidden="true">
                  ⚡
                </span>
              )}
            </span>
            <span className="battery-indicator-cap" />
          </div>
          <div className="battery-summary">
            <div className="battery-primary-reading">
              <strong>{percentage === null ? "Unavailable" : `${percentage}%`}</strong>
              <span>Battery level</span>
            </div>
            <span
              className={`battery-charge-state battery-charge-state-${result.charging_state}`}
              role="status"
            >
              {result.charging_state === "charging" && (
                <span aria-hidden="true">⚡ </span>
              )}
              {chargingLabels[result.charging_state] || chargingLabels.unknown}
            </span>
            <div className="battery-detail-row">
              <span>Power connection</span>
              <strong>
                {result.power_plugged === true
                  ? "Connected"
                  : result.power_plugged === false
                    ? "Disconnected"
                    : "Unknown"}
              </strong>
            </div>
            <div className="battery-detail-row">
              <span>Estimated remaining time</span>
              <strong>{result.remaining_time || "Unavailable"}</strong>
            </div>
          </div>
          <p className="battery-message">{result.message}</p>
        </div>
      )}
    </Panel>
  );
}
