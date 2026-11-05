import { useEffect, useState } from "react";
import HistoricalChart from "./HistoricalChart";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { intervals, isOverLimit, ranges } from "./historyOptions";
import {
  errorMessage,
  getHistoricalTemperatureSensors,
  getTemperatureInfo,
} from "../../services/api";

const group = {
  title: "Historical Temperature",
  unit: "celsius",
  series: [{ metric: "temperature", label: "Temperature", color: "#e1a344" }],
};

export default function TemperatureHistory({
  range: suppliedRange,
  interval: suppliedInterval,
}) {
  const [sensors, setSensors] = useState(null);
  const [availability, setAvailability] = useState(null);
  const [error, setError] = useState("");
  const [selectedSensor, setSelectedSensor] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [localRange, setLocalRange] = useState("1h");
  const [localInterval, setLocalInterval] = useState("1m");
  const range = suppliedRange ?? localRange;
  const requestedInterval = suppliedInterval ?? localInterval;
  const interval = isOverLimit(range, requestedInterval)
    ? "5m"
    : requestedInterval;

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    Promise.allSettled([
      getHistoricalTemperatureSensors({ signal: controller.signal }),
      getTemperatureInfo({ signal: controller.signal }),
    ]).then(([historyResult, liveResult]) => {
      if (!active) return;
      if (historyResult.status === "fulfilled") {
        const availableSensors = historyResult.value.sensors;
        setSensors(availableSensors);
        setSelectedSensor((current) =>
          availableSensors.some((sensor) => sensor.sensor_id === current)
            ? current
            : availableSensors[0]?.sensor_id || "",
        );
      } else {
        setSensors([]);
        setError(errorMessage(historyResult.reason));
      }
      if (liveResult.status === "fulfilled") {
        setAvailability(liveResult.value);
      }
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, [reloadKey]);

  const unsupportedMessage =
    availability?.availability === "unsupported"
      ? `Temperature history is unavailable because sensor readings are unsupported on ${availability.platform}.`
      : availability?.availability === "unavailable"
        ? `Temperature history is unavailable: ${availability.message || "no sensors are accessible"}.`
        : "Temperature history will appear after at least one valid sensor reading is recorded.";

  return (
    <section className="network-history-section">
      <Panel
        title="Historical temperature"
        subtitle="Select an individual sensor reading to keep unrelated sensors separate"
      >
        {error && (
          <ErrorBanner
            message={error}
            onRetry={() => {
              setSensors(null);
              setReloadKey((key) => key + 1);
            }}
          />
        )}
        {suppliedRange === undefined && (
          <div className="history-filters network-history-filters">
            <label>
              <span>Time range</span>
              <select
                value={range}
                onChange={(event) => setLocalRange(event.target.value)}
              >
                {ranges.map(([value, label]) => (
                  <option value={value} key={value}>{label}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Aggregation interval</span>
              <select
                value={interval}
                onChange={(event) => setLocalInterval(event.target.value)}
              >
                {intervals.map(([value, label]) => (
                  <option
                    value={value}
                    key={value}
                    disabled={isOverLimit(range, value)}
                  >
                    {label}
                    {isOverLimit(range, value) ? " — exceeds point limit" : ""}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {sensors === null ? (
          <Skeleton className="network-history-skeleton" />
        ) : sensors.length === 0 ? (
          <EmptyState
            title={
              availability?.availability === "available"
                ? "No historical temperature readings"
                : "Temperature history unavailable"
            }
            message={unsupportedMessage}
          />
        ) : (
          <label className="network-interface-select">
            <span>Temperature sensor</span>
            <select
              aria-label="Historical temperature sensor"
              value={selectedSensor}
              onChange={(event) => setSelectedSensor(event.target.value)}
            >
              {sensors.map((sensor) => (
                <option key={sensor.sensor_id} value={sensor.sensor_id}>
                  {sensor.sensor_name}
                  {sensor.label ? ` · ${sensor.label}` : " · Unlabeled"}
                </option>
              ))}
            </select>
          </label>
        )}
      </Panel>
      {selectedSensor && (
        <div className="history-chart-grid">
          <HistoricalChart
            group={group}
            range={range}
            interval={interval}
            sensorId={selectedSensor}
          />
        </div>
      )}
    </section>
  );
}
