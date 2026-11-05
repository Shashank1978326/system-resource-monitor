import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import {
  errorMessage,
  getPredictionAccuracy,
  getPredictionAnalytics,
  getPredictionHistory,
} from "../../services/api";
import { formatDateTime, formatPercent, formatRate } from "../../utils/format";

const RANGE_OPTIONS = [
  { value: "1h", label: "Last 1 hour" },
  { value: "6h", label: "Last 6 hours" },
  { value: "24h", label: "Last 24 hours" },
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "all", label: "All time" },
];

const HORIZON_OPTIONS = [
  { value: "", label: "All horizons" },
  { value: "5m", label: "5 minutes" },
  { value: "10m", label: "10 minutes" },
  { value: "15m", label: "15 minutes" },
  { value: "30m", label: "30 minutes" },
];

const RESOURCE_OPTIONS = [
  { value: "", label: "All resources" },
  { value: "cpu", label: "CPU" },
  { value: "memory", label: "Memory" },
  { value: "disk", label: "Disk" },
  { value: "network", label: "Network" },
];

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "evaluated", label: "Evaluated only" },
  { value: "pending", label: "Pending only" },
  { value: "missing_actual", label: "Missing telemetry" },
];

const METRIC_LABELS = {
  cpu_utilization: "CPU Utilization",
  memory_utilization: "Memory Utilization",
  disk_utilization: "Disk Capacity Utilization",
  network_download: "Network Download",
  network_upload: "Network Upload",
};

function formatMetricVal(metric, val) {
  if (val === null || val === undefined || !Number.isFinite(val)) return "—";
  if (metric && metric.includes("utilization")) {
    return formatPercent(val);
  }
  return formatRate(val);
}

function formatErrorVal(metric, val) {
  if (val === null || val === undefined || !Number.isFinite(val)) return "—";
  if (metric && metric.includes("utilization")) {
    return `${val.toFixed(2)}%`;
  }
  return formatRate(val);
}

function ActualVsPredictedTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  const isPercent = item.metric?.includes("utilization");
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{METRIC_LABELS[item.metric] || item.metric} ({item.horizon})</span>
      <small style={{ color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
        Target: {formatDateTime(item.timestamp)}
      </small>
      <strong style={{ color: "#10b981" }}>
        Actual: {formatMetricVal(item.metric, item.actual_value)}
      </strong>
      <strong style={{ color: "#9b6bdf" }}>
        Predicted: {formatMetricVal(item.metric, item.predicted_value)}
      </strong>
      {item.absolute_error !== null && (
        <span style={{ borderTop: "1px solid var(--border)", paddingTop: "4px", marginTop: "2px", display: "block" }}>
          Abs Error: {formatErrorVal(item.metric, item.absolute_error)}
          {item.percentage_error !== null && ` (${item.percentage_error.toFixed(1)}%)`}
        </span>
      )}
    </div>
  );
}

function ErrorTrendTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{METRIC_LABELS[item.metric] || item.metric}</span>
      <small style={{ color: "var(--text-muted)", display: "block", marginBottom: "4px" }}>
        Target: {formatDateTime(item.timestamp)}
      </small>
      <strong style={{ color: "#5577ec" }}>
        Absolute Error: {formatErrorVal(item.metric, item.absolute_error)}
      </strong>
      {item.percentage_error !== null && (
        <strong style={{ color: "#f59e0b" }}>
          Percentage Error: {item.percentage_error.toFixed(2)}%
        </strong>
      )}
    </div>
  );
}

export default function PredictionAnalytics() {
  const [range, setRange] = useState("24h");
  const [resource, setResource] = useState("");
  const [horizon, setHorizon] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 15;

  const [analyticsData, setAnalyticsData] = useState(null);
  const [accuracyData, setAccuracyData] = useState(null);
  const [historyData, setHistoryData] = useState(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Fetch analytics, accuracy breakdown, and history table
  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    const fetchData = async () => {
      setLoading(true);
      setError("");
      try {
        const [analytics, accuracy, history] = await Promise.all([
          getPredictionAnalytics({
            range,
            resource: resource || undefined,
            horizon: horizon || undefined,
            signal: controller.signal,
          }),
          getPredictionAccuracy({
            range,
            resource: resource || undefined,
            horizon: horizon || undefined,
            signal: controller.signal,
          }),
          getPredictionHistory({
            resource: resource || undefined,
            horizon: horizon || undefined,
            status: statusFilter || undefined,
            page,
            pageSize,
            signal: controller.signal,
          }),
        ]);

        if (active) {
          setAnalyticsData(analytics);
          setAccuracyData(accuracy);
          setHistoryData(history);
        }
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(err));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    fetchData();

    return () => {
      active = false;
      controller.abort();
    };
  }, [range, resource, horizon, statusFilter, page, refreshTrigger]);

  const summary = analyticsData?.summary || {
    mae: null,
    rmse: null,
    mape: null,
    evaluated_count: 0,
    pending_count: 0,
    average_confidence: null,
  };

  const trendPoints = analyticsData?.trend || [];
  const evaluatedPoints = useMemo(
    () => trendPoints.filter((p) => p.evaluation_status === "evaluated" && p.actual_value !== null),
    [trendPoints]
  );

  // Prepare Horizon comparison data
  const horizonChartData = useMemo(() => {
    const list = accuracyData?.by_horizon || [];
    return list.map((h) => ({
      name: h.horizon,
      mae: h.mae !== null ? Number(h.mae.toFixed(2)) : 0,
      rmse: h.rmse !== null ? Number(h.rmse.toFixed(2)) : 0,
      mape: h.mape !== null ? Number(h.mape.toFixed(2)) : 0,
      count: h.evaluated_count,
    }));
  }, [accuracyData]);

  const historyItems = historyData?.items || [];
  const totalItems = historyData?.total || 0;
  const totalPages = historyData?.total_pages || 1;

  return (
    <div className="prediction-analytics-container">
      {/* Analytics Controls */}
      <div className="history-intro" style={{ marginBottom: "16px" }}>
        <div>
          <h3 style={{ margin: "0 0 4px 0", fontSize: "14px", fontWeight: "600" }}>
            Prediction Accuracy & Historical Evaluation
          </h3>
          <p style={{ margin: 0, fontSize: "12px", color: "var(--text-muted)" }}>
            Evaluate historical forecasts against actual telemetry once the forecast horizon elapses.
          </p>
        </div>

        <div className="history-filters">
          <label>
            <span>Time range</span>
            <select value={range} onChange={(e) => { setRange(e.target.value); setPage(1); }}>
              {RANGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Resource</span>
            <select value={resource} onChange={(e) => { setResource(e.target.value); setPage(1); }}>
              {RESOURCE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <label>
            <span>Horizon</span>
            <select value={horizon} onChange={(e) => { setHorizon(e.target.value); setPage(1); }}>
              {HORIZON_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>

          <button
            className="text-button"
            type="button"
            style={{
              alignSelf: "flex-end",
              padding: "8px 12px",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              background: "var(--surface)",
              cursor: "pointer",
            }}
            onClick={() => setRefreshTrigger((k) => k + 1)}
          >
            Refresh
          </button>
        </div>
      </div>

      <ErrorBanner
        message={error}
        onRetry={() => setRefreshTrigger((k) => k + 1)}
      />

      {loading && !analyticsData ? (
        <div className="cpu-alert-skeleton">
          <Skeleton />
          <Skeleton />
        </div>
      ) : (
        <>
          {/* Section A: Accuracy Summary Cards */}
          <div className="analytics-summary-grid" style={{ marginBottom: "24px" }}>
            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Mean Absolute Error (MAE)</span>
              <strong className="analytics-metric-value" style={{ color: "var(--text)" }}>
                {summary.mae !== null ? summary.mae.toFixed(2) : "—"}
              </strong>
              <small className="analytics-metric-subtext">
                Average absolute difference |actual - predicted|
              </small>
            </div>

            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Root Mean Squared Error (RMSE)</span>
              <strong className="analytics-metric-value" style={{ color: "var(--accent)" }}>
                {summary.rmse !== null ? summary.rmse.toFixed(2) : "—"}
              </strong>
              <small className="analytics-metric-subtext">
                Square root of mean squared prediction errors
              </small>
            </div>

            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Mean Abs Percentage Error (MAPE)</span>
              <strong className="analytics-metric-value" style={{ color: "var(--warning)" }}>
                {summary.mape !== null ? `${summary.mape.toFixed(2)}%` : "—"}
              </strong>
              <small className="analytics-metric-subtext">
                Average percentage error (excludes zero actuals)
              </small>
            </div>

            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Evaluated Forecasts</span>
              <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
                <strong className="analytics-metric-value" style={{ color: "var(--green)" }}>
                  {summary.evaluated_count}
                </strong>
                <span className="cpu-alert-state cpu-alert-normal" style={{ fontSize: "10px" }}>
                  Evaluated
                </span>
              </div>
              <small className="analytics-metric-subtext">
                Forecasts compared against actual telemetry
              </small>
            </div>

            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Pending Forecasts</span>
              <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
                <strong className="analytics-metric-value" style={{ color: "var(--warning)" }}>
                  {summary.pending_count}
                </strong>
                <span className="cpu-alert-state cpu-alert-warning" style={{ fontSize: "10px" }}>
                  Awaiting Target Time
                </span>
              </div>
              <small className="analytics-metric-subtext">
                Target timestamps have not yet elapsed
              </small>
            </div>

            <div className="analytics-summary-card">
              <span className="analytics-metric-label">Average Confidence Score</span>
              <strong className="analytics-metric-value" style={{ color: "var(--text-muted)" }}>
                {summary.average_confidence !== null
                  ? `${Math.round(summary.average_confidence * 100)}%`
                  : "—"}
              </strong>
              <small className="analytics-metric-subtext">
                Model goodness-of-fit ($R^2$); distinct from accuracy
              </small>
            </div>
          </div>

          {/* Section B & C: Actual vs Predicted & Error Trend Charts */}
          {evaluatedPoints.length > 0 ? (
            <div className="history-chart-grid" style={{ marginBottom: "28px" }}>
              {/* Actual vs Predicted Series Chart */}
              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <h3>Actual vs Predicted Telemetry</h3>
                    <p>Comparison of historical forecast targets vs recorded actual telemetry.</p>
                  </div>
                </div>

                <div style={{ width: "100%", height: "260px", marginTop: "12px" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={evaluatedPoints} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                      <XAxis
                        dataKey="timestamp"
                        stroke="var(--text-muted)"
                        fontSize={10}
                        tickFormatter={(v) => {
                          const d = new Date(v);
                          return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                        }}
                        tickLine={false}
                      />
                      <YAxis stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                      <Tooltip content={<ActualVsPredictedTooltip />} />
                      <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                      <Line
                        type="monotone"
                        dataKey="actual_value"
                        name="Actual Measured"
                        stroke="#10b981"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#10b981" }}
                      />
                      <Line
                        type="monotone"
                        dataKey="predicted_value"
                        name="Predicted Target"
                        stroke="#9b6bdf"
                        strokeWidth={2}
                        strokeDasharray="4 4"
                        dot={{ r: 3, fill: "#9b6bdf" }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Prediction Error Trend Chart */}
              <div className="panel">
                <div className="panel-heading">
                  <div>
                    <h3>Prediction Error Trend Over Time</h3>
                    <p>Chronological trajectory of absolute forecast error.</p>
                  </div>
                </div>

                <div style={{ width: "100%", height: "260px", marginTop: "12px" }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={evaluatedPoints} margin={{ top: 10, right: 15, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                      <XAxis
                        dataKey="timestamp"
                        stroke="var(--text-muted)"
                        fontSize={10}
                        tickFormatter={(v) => {
                          const d = new Date(v);
                          return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
                        }}
                        tickLine={false}
                      />
                      <YAxis stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                      <Tooltip content={<ErrorTrendTooltip />} />
                      <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                      <Line
                        type="monotone"
                        dataKey="absolute_error"
                        name="Absolute Error (|actual - pred|)"
                        stroke="#5577ec"
                        strokeWidth={2}
                        dot={{ r: 3, fill: "#5577ec" }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ marginBottom: "24px" }}>
              <EmptyState
                title="Awaiting Evaluated Predictions"
                message="Predictions are evaluated once their future target horizon has elapsed and actual system telemetry is recorded. Currently pending forecasts will be evaluated automatically."
              />
            </div>
          )}

          {/* Section D: Horizon Performance Comparison Chart */}
          {horizonChartData.some((h) => h.count > 0) && (
            <div className="panel" style={{ marginBottom: "28px" }}>
              <div className="panel-heading">
                <div>
                  <h3>Performance Across Forecast Horizons</h3>
                  <p>Comparing Mean Absolute Error (MAE) and Root Mean Squared Error (RMSE) across 5m, 10m, 15m, and 30m.</p>
                </div>
              </div>

              <div style={{ width: "100%", height: "220px", marginTop: "12px" }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={horizonChartData} margin={{ top: 10, right: 15, left: -15, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                    <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11} tickLine={false} />
                    <YAxis stroke="var(--text-muted)" fontSize={10} tickLine={false} />
                    <Tooltip
                      formatter={(val, name) => [val, name]}
                      labelFormatter={(label) => `Horizon: ${label}`}
                    />
                    <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                    <Bar dataKey="mae" name="MAE (Mean Absolute Error)" fill="#5577ec" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="rmse" name="RMSE (Root Mean Squared Error)" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Section E: Historical Prediction Records Table */}
          <div className="panel">
            <div className="panel-heading" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <h3>Historical Forecast Records</h3>
                <p>Individual prediction records with actual matched telemetry and error evaluation.</p>
              </div>

              <div style={{ display: "flex", gap: "10px" }}>
                <label style={{ fontSize: "12px" }}>
                  <select
                    value={statusFilter}
                    onChange={(e) => {
                      setStatusFilter(e.target.value);
                      setPage(1);
                    }}
                    style={{
                      padding: "4px 8px",
                      borderRadius: "4px",
                      border: "1px solid var(--border)",
                      background: "var(--surface)",
                      color: "var(--text)",
                    }}
                  >
                    {STATUS_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="prediction-table-wrapper" style={{ overflowX: "auto", marginTop: "12px" }}>
              <table className="prediction-history-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "12px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left", color: "var(--text-muted)" }}>
                    <th style={{ padding: "8px" }}>Metric / Resource</th>
                    <th style={{ padding: "8px" }}>Horizon</th>
                    <th style={{ padding: "8px" }}>Target Time</th>
                    <th style={{ padding: "8px" }}>Predicted</th>
                    <th style={{ padding: "8px" }}>Actual</th>
                    <th style={{ padding: "8px" }}>Abs Error</th>
                    <th style={{ padding: "8px" }}>% Error</th>
                    <th style={{ padding: "8px" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {historyItems.map((item) => (
                    <tr key={item.prediction_id} style={{ borderBottom: "1px solid var(--border-soft, #222)" }}>
                      <td style={{ padding: "8px" }}>
                        <strong>{METRIC_LABELS[item.metric] || item.metric}</strong>
                        <small style={{ color: "var(--text-muted)", display: "block" }}>
                          {item.resource.toUpperCase()}
                        </small>
                      </td>
                      <td style={{ padding: "8px" }}>
                        <code>{item.horizon}</code>
                      </td>
                      <td style={{ padding: "8px" }}>
                        {formatDateTime(item.target_timestamp)}
                      </td>
                      <td style={{ padding: "8px", fontWeight: "600", color: "var(--accent)" }}>
                        {formatMetricVal(item.metric, item.predicted_value)}
                      </td>
                      <td style={{ padding: "8px" }}>
                        {formatMetricVal(item.metric, item.actual_value)}
                      </td>
                      <td style={{ padding: "8px" }}>
                        {formatErrorVal(item.metric, item.absolute_error)}
                      </td>
                      <td style={{ padding: "8px" }}>
                        {item.percentage_error !== null ? `${item.percentage_error.toFixed(1)}%` : "—"}
                      </td>
                      <td style={{ padding: "8px" }}>
                        {item.evaluation_status === "evaluated" ? (
                          <span className="cpu-alert-state cpu-alert-normal" style={{ fontSize: "10px" }}>
                            Evaluated
                          </span>
                        ) : item.evaluation_status === "pending" ? (
                          <span className="cpu-alert-state cpu-alert-warning" style={{ fontSize: "10px" }}>
                            Pending
                          </span>
                        ) : (
                          <span className="cpu-alert-state cpu-alert-muted" style={{ fontSize: "10px" }}>
                            No Telemetry
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {historyItems.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: "center", padding: "20px", color: "var(--text-muted)" }}>
                        No prediction records found matching the current filters.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginTop: "14px",
                  paddingTop: "10px",
                  borderTop: "1px solid var(--border)",
                  fontSize: "12px",
                }}
              >
                <span style={{ color: "var(--text-muted)" }}>
                  Showing page <strong>{page}</strong> of <strong>{totalPages}</strong> ({totalItems} records)
                </span>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="button"
                    className="text-button"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    style={{
                      padding: "6px 12px",
                      borderRadius: "4px",
                      border: "1px solid var(--border)",
                      background: "var(--surface)",
                      cursor: page > 1 ? "pointer" : "default",
                      opacity: page > 1 ? 1 : 0.5,
                    }}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    style={{
                      padding: "6px 12px",
                      borderRadius: "4px",
                      border: "1px solid var(--border)",
                      background: "var(--surface)",
                      cursor: page < totalPages ? "pointer" : "default",
                      opacity: page < totalPages ? 1 : 0.5,
                    }}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

