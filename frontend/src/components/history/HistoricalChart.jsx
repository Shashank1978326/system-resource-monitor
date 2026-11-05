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
import { EmptyState, ErrorBanner } from "../common/StateMessage";
import { errorMessage, getHistoryGraph } from "../../services/api";
import { formatBytes, formatRate } from "../../utils/format";

function GraphTooltip({ active, payload, label, unit }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{label}</span>
      {payload.map((point) => (
        <strong key={point.dataKey} style={{ color: point.color }}>
          {point.name}: {typeof point.value === "number"
            ? unit === "percent"
              ? `${point.value.toFixed(2)}%`
              : unit === "celsius"
                ? `${point.value.toFixed(1)} °C`
              : unit === "rate"
                ? formatRate(point.value)
                : unit === "disk_rate"
                  ? `${(point.value / 1024 ** 2).toFixed(3)} MB/s`
                    : unit === "interface_rate"
                      ? `${(point.value / 1024 ** 2).toFixed(3)} MB/s`
                    : formatBytes(point.value)
            : "Unavailable"}
        </strong>
      ))}
    </div>
  );
}

export default function HistoricalChart({
  group,
  range,
  interval,
  interfaceName,
  sensorId,
}) {
  const [data, setData] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const query = useMemo(() => ({ range, interval }), [range, interval]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const requests = group.series.map((series) =>
      getHistoryGraph(series.metric, query.range, query.interval, {
        interfaceName,
        sensorId,
      }),
    );
    Promise.allSettled(requests).then((results) => {
      if (!active) return;
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length) setError(errorMessage(failures[0].reason));
      const byTimestamp = new Map();
      results.forEach((result, index) => {
        if (result.status !== "fulfilled") return;
        const key = group.series[index].metric;
        for (const point of result.value.data_points) {
          const item = byTimestamp.get(point.timestamp) || {
            timestamp: point.timestamp,
            time: new Date(point.timestamp).toLocaleString(),
          };
          item[key] = point.value;
          byTimestamp.set(point.timestamp, item);
        }
      });
      setData(
        [...byTimestamp.values()].sort(
          (left, right) => new Date(left.timestamp) - new Date(right.timestamp),
        ),
      );
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [group, interfaceName, query, sensorId]);

  const subtitle = group.unit === "percent"
    ? "Average utilization by interval"
    : group.unit === "celsius"
      ? "Average sensor temperature by interval"
    : group.unit === "rate"
      ? "Average transfer speed by interval"
      : group.unit === "disk_rate"
        ? "Average disk throughput by interval"
        : group.unit === "interface_rate"
          ? "Average per-interface throughput by interval"
        : "Average cumulative counter by interval";

  return (
    <Panel title={group.title} subtitle={subtitle}>
      {error && <ErrorBanner message={error} />}
      {loading ? (
        <div className="chart-loading"><div className="skeleton skeleton-chart" /></div>
      ) : data.length === 0 ? (
        <EmptyState
          title={error ? "Couldn’t load this chart" : "No history for this period"}
          message={error || "No historical samples were recorded in the selected time range."}
        />
      ) : (
        <>
          <div className="historical-chart">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 8, right: 12, left: -20, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 5" />
                <XAxis
                  dataKey="time"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                  minTickGap={30}
                />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "var(--text-muted)", fontSize: 10 }}
                  domain={group.unit === "percent" ? [0, 100] : ["auto", "auto"]}
                  tickFormatter={(value) => (
                    group.unit === "percent"
                      ? `${value}%`
                      : group.unit === "celsius"
                        ? `${value}°`
                      : group.unit === "disk_rate"
                        ? `${(value / 1024 ** 2).toFixed(2)}`
                        : group.unit === "interface_rate"
                          ? `${(value / 1024 ** 2).toFixed(2)}`
                        : ""
                  )}
                  width={48}
                />
                <Tooltip content={<GraphTooltip unit={group.unit} />} />
                {group.series.map((series) => (
                  <Line
                    key={series.metric}
                    type="monotone"
                    dataKey={series.metric}
                    name={series.label}
                    stroke={series.color}
                    strokeWidth={2}
                    dot={
                      group.unit === "disk_rate" ||
                      group.unit === "interface_rate"
                        ? { r: 2 }
                        : false
                    }
                    activeDot={{ r: 4, strokeWidth: 0 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
          {(group.unit === "disk_rate" ||
            group.unit === "interface_rate") && (
            <p className="muted-copy">Y-axis and tooltips show MB/s; unavailable samples remain gaps, not zero throughput.</p>
          )}
          <div className="chart-series-legend">
            {group.series.map((series) => (
              <span key={series.metric}><i style={{ backgroundColor: series.color }} />{series.label}</span>
            ))}
            <small>{data.length} data {data.length === 1 ? "point" : "points"}</small>
          </div>
        </>
      )}
    </Panel>
  );
}
