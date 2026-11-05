import { useEffect, useState } from "react";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getDiskIo } from "../../services/api";
import { formatBytes } from "../../utils/format";

const REFRESH_INTERVAL_MS = 1000;

function operations(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "Unavailable";
}

function formatSpeed(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(2)} MB/s`
    : "Unavailable";
}

function SpeedCard({ title, comparisonPercent, bytes, count, speed, status, message }) {
  const isAvailable = status === "available" && Number.isFinite(speed);
  const isInitializing = status === "initializing";
  return (
    <section className="disk-speed-card">
      <h3>{title}</h3>
      <div className="disk-read-speed-primary" aria-live="polite">
        <span>Current speed</span>
        <strong>{formatSpeed(speed)}</strong>
      </div>
      {!isAvailable && (
        <p className="disk-speed-state" role="status">
          {message || (isInitializing ? "Measuring disk activity…" : "Measurement unavailable")}
        </p>
      )}
      <div className="disk-read-speed-details">
        <div>
          <span>Total data {title.toLowerCase()}</span>
          <strong>{formatBytes(bytes)}</strong>
        </div>
        <div>
          <span>{title} operations</span>
          <strong>{operations(count)}</strong>
        </div>
      </div>
      <div className="disk-speed-indicator">
        <div className="disk-speed-indicator-label">
          <span>{title} activity</span>
          <strong>{isAvailable ? formatSpeed(speed) : "Unavailable"}</strong>
        </div>
        <div
          className="disk-speed-track"
          role="progressbar"
          aria-label={`${title} speed relative to current read/write maximum`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={isAvailable ? comparisonPercent : undefined}
        >
          {isAvailable && (
            <span
              className={`disk-speed-fill disk-speed-fill-${title.toLowerCase()}`}
              style={{ width: `${comparisonPercent}%` }}
            />
          )}
        </div>
      </div>
    </section>
  );
}

export default function DiskReadSpeed() {
  const [reading, setReading] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timer;
    const controller = new AbortController();

    const refresh = async () => {
      try {
        const result = await getDiskIo({ signal: controller.signal });
        if (!active) return;
        setReading(result);
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

  const readSpeed = reading?.read_speed_mb_per_sec;
  const writeSpeed = reading?.write_speed_mb_per_sec;
  const currentMaximum = Math.max(
    typeof readSpeed === "number" ? readSpeed : 0,
    typeof writeSpeed === "number" ? writeSpeed : 0,
  );
  const readPercent =
    reading?.available && currentMaximum > 0
      ? (readSpeed / currentMaximum) * 100
      : 0;
  const writePercent =
    reading?.write_available && currentMaximum > 0
      ? (writeSpeed / currentMaximum) * 100
      : 0;

  return (
    <Panel
      title="Live disk I/O speeds"
      subtitle="Aggregate read/write counters · refreshes every second"
    >
      {error && <ErrorBanner message={error} />}
      {loading && !reading ? (
        <div className="disk-read-speed-loading">
          <Skeleton className="skeleton-line" />
          <Skeleton className="skeleton-line" />
        </div>
      ) : (
        <>
          {!reading && (
            <EmptyState
              title="Disk I/O measurements unavailable"
              message="The API has not returned disk counter measurements yet."
            />
          )}
          {reading && (
            <div className="disk-read-speed">
              <SpeedCard
                title="Read"
                comparisonPercent={readPercent}
                bytes={reading.total_bytes_read}
                count={reading.read_operations}
                speed={readSpeed}
                status={reading.status}
                message={reading.message}
              />
              <SpeedCard
                title="Write"
                comparisonPercent={writePercent}
                bytes={reading.total_bytes_written}
                count={reading.write_operations}
                speed={writeSpeed}
                status={reading.write_status}
                message={reading.write_message}
              />
              <p className="disk-speed-comparison">
                Bar lengths compare current read and write throughput; each is
                scaled against the faster available direction.
              </p>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}
