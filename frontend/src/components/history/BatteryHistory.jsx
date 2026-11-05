import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getBatteryInfo, getHistoryGraph } from "../../services/api";
import { intervals, isOverLimit, ranges } from "./historyOptions";

const chargingLabels = {
  charging: "Charging",
  discharging: "Discharging",
  not_charging: "Not charging",
  unknown: "Charging status unknown",
};

function BatteryTooltip({ active, payload }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{new Date(point.timestamp).toLocaleString()}</span>
      <strong>
        Battery: {typeof point.value === "number" ? `${point.value.toFixed(2)}%` : "Unavailable"}
      </strong>
      <strong>
        {chargingLabels[point.charging_state] || "Charging status unavailable"}
      </strong>
      <strong>
        Power: {point.power_plugged === true
          ? "Connected"
          : point.power_plugged === false
            ? "Disconnected"
            : "Unknown"}
      </strong>
    </div>
  );
}

function statusEvents(points) {
  const events = [];
  let previousState = null;
  for (const point of points) {
    const state = [
      point.battery_availability,
      point.charging_state,
      point.power_plugged,
    ].join(":");
    if (state === previousState) continue;
    previousState = state;
    events.push(point);
  }
  return events;
}

function batteryStatus(point) {
  if (point.battery_availability === "unsupported") {
    return "Battery monitoring unsupported";
  }
  if (point.battery_availability === "unavailable") {
    return "Battery unavailable";
  }
  return chargingLabels[point.charging_state] || "Charging status unknown";
}

function powerStatus(value) {
  return value === true ? "Connected" : value === false ? "Disconnected" : "Unknown";
}

export default function BatteryHistory({
  range: suppliedRange,
  interval: suppliedInterval,
}) {
  const [data, setData] = useState([]);
  const [availability, setAvailability] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [localRange, setLocalRange] = useState("1h");
  const [localInterval, setLocalInterval] = useState("1m");
  const range = suppliedRange ?? localRange;
  const requestedInterval = suppliedInterval ?? localInterval;
  const interval = isOverLimit(range, requestedInterval)
    ? "5m"
    : requestedInterval;
  const query = useMemo(() => ({ range, interval }), [range, interval]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError("");

    Promise.allSettled([
      getHistoryGraph("battery", query.range, query.interval, {
        signal: controller.signal,
      }),
      getBatteryInfo({ signal: controller.signal }),
    ]).then(([historyResult, liveResult]) => {
      if (!active) return;
      if (historyResult.status === "fulfilled") {
        setData(historyResult.value.data_points);
      } else {
        setData([]);
        setError(errorMessage(historyResult.reason));
      }
      if (liveResult.status === "fulfilled") {
        setAvailability(liveResult.value);
      }
      setLoading(false);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [query, reloadKey]);

  const events = useMemo(() => statusEvents(data), [data]);
  const hasPercentage = data.some((point) => typeof point.value === "number");
  const batteryUnavailable =
    availability && availability.availability !== "available";

  return (
    <section className="battery-history-section">
      <Panel
        title="Battery history"
        subtitle="Battery percentage averages and recorded charging and power states"
      >
        {error && (
          <ErrorBanner
            message={error}
            onRetry={() => {
              setReloadKey((key) => key + 1);
            }}
          />
        )}
        {suppliedRange === undefined && (
          <div className="history-filters battery-history-filters">
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
        {loading && data.length === 0 ? (
          <Skeleton className="battery-history-skeleton" />
        ) : (data.length === 0 && batteryUnavailable) ||
          (batteryUnavailable &&
            !data.some((point) => point.battery_availability === "available")) ? (
          <EmptyState
            title="Battery history unavailable"
            message={availability?.message || "No battery is available on this system."}
          />
        ) : data.length === 0 ? (
          <EmptyState
            title={error ? "Couldn’t load battery history" : "No battery history for this period"}
            message={error || "Battery history will appear after the existing monitor records its next sample."}
          />
        ) : (
          <>
            {hasPercentage ? (
              <div className="battery-history-chart">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data}
                    margin={{ top: 8, right: 12, left: -20, bottom: 0 }}
                  >
                    <CartesianGrid
                      vertical={false}
                      stroke="var(--chart-grid)"
                      strokeDasharray="3 5"
                    />
                    <XAxis
                      dataKey="timestamp"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                      minTickGap={30}
                      tickFormatter={(value) =>
                        new Date(value).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })
                      }
                    />
                    <YAxis
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                      domain={[0, 100]}
                      tickFormatter={(value) => `${value}%`}
                      width={48}
                    />
                    <Tooltip content={<BatteryTooltip />} />
                    <Line
                      type="monotone"
                      dataKey="value"
                      name="Battery"
                      stroke="#2b9c84"
                      strokeWidth={2}
                      dot={data.length === 1 ? { r: 3 } : false}
                      activeDot={{ r: 4, strokeWidth: 0 }}
                      connectNulls={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                title="Battery percentage unavailable"
                message="Battery status was recorded, but no percentage readings are available in this period."
              />
            )}
            <div className="battery-history-status-heading">
              <h3>Charging and power history</h3>
              <span>{events.length} recorded state {events.length === 1 ? "change" : "changes"}</span>
            </div>
            {events.length === 0 ? (
              <p className="battery-history-no-states">
                No battery state readings were recorded in this period.
              </p>
            ) : (
              <ol className="battery-history-events">
                {events.map((point) => (
                  <li
                    key={`${point.status_timestamp || point.timestamp}-${point.battery_availability}-${point.charging_state}-${point.power_plugged}`}
                  >
                    <time dateTime={point.status_timestamp || point.timestamp}>
                      {new Date(
                        point.status_timestamp || point.timestamp,
                      ).toLocaleString()}
                    </time>
                    <strong>{batteryStatus(point)}</strong>
                    <span>
                      Power{" "}
                      {point.battery_availability === "available"
                        ? powerStatus(point.power_plugged)
                        : "Unavailable"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </Panel>
    </section>
  );
}
