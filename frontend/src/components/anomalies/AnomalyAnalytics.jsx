import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getAnomalyAnalytics } from "../../services/api";

const TIME_RANGES = [
  { value: "1h", label: "1 hour" },
  { value: "6h", label: "6 hours" },
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

const RESOURCE_OPTIONS = [
  { value: "", label: "All resources" },
  { value: "cpu", label: "CPU" },
  { value: "memory", label: "Memory" },
  { value: "disk", label: "Disk" },
  { value: "network", label: "Network" },
];

const METRIC_OPTIONS = [
  { value: "", label: "All metrics" },
  { value: "cpu_utilization", label: "CPU utilization" },
  { value: "memory_utilization", label: "Memory utilization" },
  { value: "disk_read_throughput", label: "Disk read throughput" },
  { value: "disk_write_throughput", label: "Disk write throughput" },
  { value: "network_download_throughput", label: "Network download" },
  { value: "network_upload_throughput", label: "Network upload" },
];

const SEVERITY_OPTIONS = [
  { value: "", label: "All severities" },
  { value: "Warning", label: "Warning only" },
  { value: "Critical", label: "Critical only" },
];

const RESOURCE_LABELS = {
  cpu: "CPU",
  memory: "Memory",
  disk: "Disk",
  network: "Network",
};

const METRIC_SHORT_LABELS = {
  cpu_utilization: "CPU Util",
  memory_utilization: "Mem Util",
  disk_read_throughput: "Disk Read",
  disk_write_throughput: "Disk Write",
  network_download_throughput: "Net Down",
  network_upload_throughput: "Net Up",
};

function formatTimelineLabel(isoString, range) {
  if (!isoString) return "";
  const d = new Date(isoString);
  if (range === "1h" || range === "6h" || range === "24h") {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function TimelineTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{new Date(point.timestamp).toLocaleString()}</span>
      <strong style={{ color: "#ef4444" }}>
        Critical: {point.critical_count}
      </strong>
      <strong style={{ color: "#f59e0b" }}>
        Warning: {point.warning_count}
      </strong>
      <span style={{ borderTop: "1px solid var(--border)", paddingTop: "4px", marginTop: "2px", display: "block" }}>
        Total Events: <strong>{point.total_count}</strong>
      </span>
    </div>
  );
}

function DistributionTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{item.label || RESOURCE_LABELS[item.resource] || item.resource}</span>
      <strong style={{ color: "#ef4444" }}>
        Critical: {item.critical_count}
      </strong>
      <strong style={{ color: "#f59e0b" }}>
        Warning: {item.warning_count}
      </strong>
      <span style={{ borderTop: "1px solid var(--border)", paddingTop: "4px", marginTop: "2px", display: "block" }}>
        Total: <strong>{item.total_count}</strong> ({item.percentage.toFixed(1)}%)
      </span>
    </div>
  );
}

export default function AnomalyAnalytics() {
  const [range, setRange] = useState("24h");
  const [resource, setResource] = useState("");
  const [metric, setMetric] = useState("");
  const [severity, setSeverity] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError("");

    getAnomalyAnalytics(
      {
        range,
        resource: resource || undefined,
        metric: metric || undefined,
        severity: severity || undefined,
      },
      { signal: controller.signal },
    )
      .then((res) => {
        if (active) setData(res);
      })
      .catch((err) => {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(err));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [range, resource, metric, severity, retryKey]);

  // Formatted timeline for recharts
  const timelineData = useMemo(() => {
    if (!data?.timeline) return [];
    return data.timeline.map((point) => ({
      ...point,
      formattedTime: formatTimelineLabel(point.timestamp, range),
    }));
  }, [data, range]);

  // Formatted resource distribution
  const resourceData = useMemo(() => {
    if (!data?.by_resource) return [];
    return data.by_resource.map((r) => ({
      ...r,
      displayName: RESOURCE_LABELS[r.resource] || r.resource.toUpperCase(),
    }));
  }, [data]);

  // Formatted metric analysis
  const metricData = useMemo(() => {
    if (!data?.by_metric) return [];
    return data.by_metric.map((m) => ({
      ...m,
      shortLabel: METRIC_SHORT_LABELS[m.metric] || m.label,
    }));
  }, [data]);

  const hasEvents = (data?.total_anomalies || 0) > 0;

  return (
    <div className="anomaly-analytics-section" style={{ marginTop: "32px" }}>
      {/* Analytics Section Header */}
      <div className="history-intro">
        <div>
          <h2 style={{ margin: "0 0 4px 0", fontSize: "16px", fontWeight: "600" }}>
            Anomaly Trend Analytics
          </h2>
          <p style={{ margin: 0, fontSize: "12px", color: "var(--text-muted)" }}>
            Historical anomaly frequency over time, resource distribution, and metric severity breakdowns.
          </p>
        </div>

        {/* Global Trend Filters */}
        <div className="history-filters">
          <label>
            <span>Time range</span>
            <select value={range} onChange={(e) => setRange(e.target.value)}>
              {TIME_RANGES.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Resource</span>
            <select
              value={resource}
              onChange={(e) => {
                setResource(e.target.value);
                setMetric("");
              }}
            >
              {RESOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Metric</span>
            <select value={metric} onChange={(e) => setMetric(e.target.value)}>
              {METRIC_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Severity</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
              {SEVERITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <ErrorBanner
        message={error}
        onRetry={() => {
          setLoading(true);
          setRetryKey((k) => k + 1);
        }}
      />

      {loading && data === null ? (
        <div className="cpu-alert-skeleton" style={{ marginTop: "16px" }}>
          <Skeleton />
          <Skeleton />
        </div>
      ) : (
        <>
          {/* Summary Strip */}
          <div className="anomaly-summary-grid" style={{ marginTop: "16px" }}>
            <div className="anomaly-summary-card">
              <span className="anomaly-summary-label">PERIOD TOTAL</span>
              <strong className="anomaly-summary-value">
                {data?.total_anomalies ?? 0}
              </strong>
              <small>
                {data?.range} window · interval: {data ? Math.round(data.interval_seconds / 60) : 0}m
              </small>
            </div>

            <div className="anomaly-summary-card">
              <span className="anomaly-summary-label">PERIOD WARNINGS</span>
              <strong
                className="anomaly-summary-value"
                style={{ color: (data?.warning_count ?? 0) > 0 ? "var(--warning, #f59e0b)" : "inherit" }}
              >
                {data?.warning_count ?? 0}
              </strong>
              <small>Z-score: 3.0 ≤ Z &lt; 4.5</small>
            </div>

            <div className="anomaly-summary-card">
              <span className="anomaly-summary-label">PERIOD CRITICAL</span>
              <strong
                className="anomaly-summary-value"
                style={{ color: (data?.critical_count ?? 0) > 0 ? "var(--danger, #ef4444)" : "inherit" }}
              >
                {data?.critical_count ?? 0}
              </strong>
              <small>Z-score: Z ≥ 4.5</small>
            </div>
          </div>

          {!hasEvents && !loading && (
            <div style={{ marginTop: "16px" }}>
              <EmptyState
                title="No anomalies detected in selected period"
                message="No statistical anomaly spikes matched the selected time range and filters. The charts below display the continuous zero baseline."
              />
            </div>
          )}

          {/* Part 1: Anomaly Frequency Over Time */}
          <div className="panel" style={{ marginTop: "20px" }}>
            <div className="panel-heading">
              <div>
                <h3>Anomaly Frequency Over Time</h3>
                <p>Recorded Warning and Critical anomaly event counts grouped by interval.</p>
              </div>
            </div>

            <div style={{ width: "100%", height: "260px", marginTop: "12px" }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={timelineData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                  <XAxis
                    dataKey="formattedTime"
                    stroke="var(--text-muted)"
                    fontSize={11}
                    tickLine={false}
                  />
                  <YAxis
                    stroke="var(--text-muted)"
                    fontSize={11}
                    allowDecimals={false}
                    tickLine={false}
                  />
                  <Tooltip content={<TimelineTooltip />} />
                  <Legend
                    verticalAlign="top"
                    align="right"
                    wrapperStyle={{ paddingBottom: "10px", fontSize: "12px" }}
                  />
                  <Bar dataKey="warning_count" name="Warning" fill="#f59e0b" stackId="freq" radius={[0, 0, 0, 0]} />
                  <Bar dataKey="critical_count" name="Critical" fill="#ef4444" stackId="freq" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Part 2 & Part 3: Dual Grid for Resource Distribution and Metric Breakdown */}
          <div className="history-chart-grid" style={{ marginTop: "20px" }}>
            {/* Part 2: Resource-wise Anomaly Distribution */}
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <h3>Resource Distribution</h3>
                  <p>Proportional contribution and severity split across CPU, Memory, Disk, and Network.</p>
                </div>
              </div>

              <div style={{ width: "100%", height: "200px", marginTop: "12px" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={resourceData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                    <XAxis dataKey="displayName" stroke="var(--text-muted)" fontSize={11} tickLine={false} />
                    <YAxis stroke="var(--text-muted)" fontSize={11} allowDecimals={false} tickLine={false} />
                    <Tooltip content={<DistributionTooltip />} />
                    <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                    <Bar dataKey="warning_count" name="Warning" fill="#f59e0b" stackId="res" />
                    <Bar dataKey="critical_count" name="Critical" fill="#ef4444" stackId="res" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Resource Contribution Cards */}
              <div className="anomaly-resource-cards">
                {resourceData.map((res) => (
                  <div
                    key={res.resource}
                    style={{
                      padding: "10px 12px",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      background: "var(--surface-soft)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                      <strong style={{ fontSize: "12px" }}>{res.displayName}</strong>
                      <span
                        style={{
                          fontSize: "11px",
                          fontWeight: "600",
                          color: res.percentage > 0 ? "var(--accent)" : "var(--text-muted)",
                        }}
                      >
                        {res.percentage.toFixed(1)}%
                      </span>
                    </div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "4px" }}>
                      Total: <strong>{res.total_count}</strong> (
                      <span style={{ color: "#f59e0b" }}>{res.warning_count}W</span> ·{" "}
                      <span style={{ color: "#ef4444" }}>{res.critical_count}C</span>)
                    </div>
                    {/* Visual Progress Bar */}
                    <div
                      style={{
                        height: "4px",
                        background: "var(--border)",
                        borderRadius: "2px",
                        marginTop: "6px",
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          width: `${Math.min(100, res.percentage)}%`,
                          height: "100%",
                          background: res.critical_count > 0 ? "#ef4444" : "#f59e0b",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Part 3: Metric-wise Anomaly Analysis */}
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <h3>Metric Analysis</h3>
                  <p>Individual monitored metrics producing statistical anomalies.</p>
                </div>
              </div>

              <div style={{ width: "100%", height: "200px", marginTop: "12px" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={metricData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                    <XAxis dataKey="shortLabel" stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                    <YAxis stroke="var(--text-muted)" fontSize={11} allowDecimals={false} tickLine={false} />
                    <Tooltip content={<DistributionTooltip />} />
                    <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                    <Bar dataKey="warning_count" name="Warning" fill="#f59e0b" stackId="met" />
                    <Bar dataKey="critical_count" name="Critical" fill="#ef4444" stackId="met" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Metric Breakdown Table */}
              <div style={{ marginTop: "16px", overflowX: "auto" }}>
                <table className="alert-history-table" style={{ fontSize: "11px" }}>
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Resource</th>
                      <th>Total</th>
                      <th>Severity</th>
                      <th>Contribution</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metricData.map((m) => (
                      <tr key={m.metric}>
                        <td>
                          <strong>{m.label}</strong>
                        </td>
                        <td>
                          <span style={{ textTransform: "uppercase", fontSize: "10px", color: "var(--text-muted)" }}>
                            {m.resource}
                          </span>
                        </td>
                        <td>
                          <strong>{m.total_count}</strong>
                        </td>
                        <td>
                          <span style={{ color: "#f59e0b", marginRight: "6px" }}>{m.warning_count} Warning</span>
                          <span style={{ color: "#ef4444" }}>{m.critical_count} Critical</span>
                        </td>
                        <td>
                          <strong>{m.percentage.toFixed(1)}%</strong>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
