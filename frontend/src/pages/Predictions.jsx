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
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import PredictionAnalytics from "../components/predictions/PredictionAnalytics";
import { errorMessage, getPredictions } from "../services/api";
import { formatDateTime, formatPercent, formatRate } from "../utils/format";

const HORIZON_OPTIONS = [
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

const METRIC_TITLES = {
  cpu_utilization: "CPU Utilization",
  memory_utilization: "Memory Utilization",
  disk_utilization: "Disk Capacity Utilization",
  network_download: "Network Download Throughput",
  network_upload: "Network Upload Throughput",
};

function formatValue(metric, value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (metric.includes("utilization")) {
    return formatPercent(value);
  }
  return formatRate(value);
}

function formatDelta(metric, current, predicted) {
  if (
    current === null ||
    current === undefined ||
    predicted === null ||
    predicted === undefined ||
    !Number.isFinite(current) ||
    !Number.isFinite(predicted)
  ) {
    return null;
  }
  const diff = predicted - current;
  const isPercent = metric.includes("utilization");
  if (isPercent) {
    const sign = diff > 0 ? "+" : "";
    return `${sign}${diff.toFixed(1)}%`;
  }
  if (diff === 0) return "0 B/s";
  const sign = diff > 0 ? "+" : "-";
  return `${sign}${formatRate(Math.abs(diff))}`;
}

function trendColor(trend) {
  if (trend === "increasing") return "var(--warning, #f59e0b)";
  if (trend === "decreasing") return "var(--green, #10b981)";
  return "var(--text-muted)";
}

function trendSymbol(trend) {
  if (trend === "increasing") return "↗ Increasing";
  if (trend === "decreasing") return "↘ Decreasing";
  return "→ Stable";
}

function PredictionChartTooltip({ active, payload, unit }) {
  if (!active || !payload?.length) return null;
  const item = payload[0]?.payload;
  if (!item) return null;
  const isRate = unit === "bytes_per_second";
  return (
    <div className="chart-tooltip historical-tooltip">
      <span>{item.name}</span>
      <strong style={{ color: "#5577ec" }}>
        Current: {isRate ? formatRate(item.current) : formatPercent(item.current)}
      </strong>
      <strong style={{ color: "#9b6bdf" }}>
        Predicted: {isRate ? formatRate(item.predicted) : formatPercent(item.predicted)}
      </strong>
      {item.lower !== null && item.upper !== null && (
        <span style={{ borderTop: "1px solid var(--border)", paddingTop: "4px", marginTop: "2px", display: "block" }}>
          Bounds: {isRate ? `${formatRate(item.lower)} – ${formatRate(item.upper)}` : `${formatPercent(item.lower)} – ${formatPercent(item.upper)}`}
        </span>
      )}
    </div>
  );
}

export default function Predictions() {
  const [activeTab, setActiveTab] = useState("forecasts");
  const [horizon, setHorizon] = useState("15m");
  const [resourceFilter, setResourceFilter] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let active = true;
    let timeout;
    let controller;

    const fetchPredictions = async () => {
      controller = new AbortController();
      try {
        const result = await getPredictions({
          resource: resourceFilter || undefined,
          horizon,
          signal: controller.signal,
        });
        if (active) {
          setData(result);
          setError("");
        }
      } catch (err) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(err));
        }
      } finally {
        if (active) {
          setLoading(false);
          // Auto-refresh every 8 seconds
          timeout = window.setTimeout(fetchPredictions, 8_000);
        }
      }
    };

    setLoading(true);
    fetchPredictions();

    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller?.abort();
    };
  }, [horizon, resourceFilter, retryKey]);

  const predictions = data?.predictions || [];

  // Group data for comparative overview charts
  const utilizationChartData = useMemo(() => {
    return predictions
      .filter((p) => p.unit === "percent")
      .map((p) => ({
        name: p.resource.toUpperCase(),
        current: p.current_value,
        predicted: p.predicted_value,
        lower: p.lower_bound,
        upper: p.upper_bound,
      }));
  }, [predictions]);

  const throughputChartData = useMemo(() => {
    return predictions
      .filter((p) => p.unit === "bytes_per_second")
      .map((p) => ({
        name: p.metric === "network_download" ? "Download" : "Upload",
        current: p.current_value,
        predicted: p.predicted_value,
        lower: p.lower_bound,
        upper: p.upper_bound,
      }));
  }, [predictions]);

  return (
    <div className="predictions-page">
      <Panel
        title="Resource Utilization Predictions"
        subtitle="Time-series statistical forecasting across CPU, memory, disk capacity, and network throughput"
      >
        {/* Navigation Tabs */}
        <div
          className="prediction-tabs"
          style={{
            display: "flex",
            gap: "8px",
            marginBottom: "20px",
            borderBottom: "1px solid var(--border)",
            paddingBottom: "12px",
          }}
        >
          <button
            type="button"
            className={`prediction-tab-btn ${activeTab === "forecasts" ? "active" : ""}`}
            onClick={() => setActiveTab("forecasts")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: activeTab === "forecasts" ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: activeTab === "forecasts" ? "var(--accent-subtle, rgba(85, 119, 236, 0.15))" : "var(--surface)",
              color: activeTab === "forecasts" ? "var(--accent)" : "var(--text-muted)",
              fontWeight: "600",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Live Forecasts (5m – 30m)
          </button>
          <button
            type="button"
            className={`prediction-tab-btn ${activeTab === "analytics" ? "active" : ""}`}
            onClick={() => setActiveTab("analytics")}
            style={{
              padding: "8px 16px",
              borderRadius: "6px",
              border: activeTab === "analytics" ? "1px solid var(--accent)" : "1px solid var(--border)",
              background: activeTab === "analytics" ? "var(--accent-subtle, rgba(85, 119, 236, 0.15))" : "var(--surface)",
              color: activeTab === "analytics" ? "var(--accent)" : "var(--text-muted)",
              fontWeight: "600",
              fontSize: "13px",
              cursor: "pointer",
            }}
          >
            Prediction Accuracy & Historical Evaluation
          </button>
        </div>

        {activeTab === "analytics" ? (
          <PredictionAnalytics />
        ) : (
          <>
            {/* Controls Bar */}
            <div className="history-intro" style={{ marginBottom: "16px" }}>
          <div>
            <h3 style={{ margin: "0 0 4px 0", fontSize: "14px", fontWeight: "600" }}>
              Forecast Controls
            </h3>
            <p style={{ margin: 0, fontSize: "12px", color: "var(--text-muted)" }}>
              Select future prediction horizon and target resources.
            </p>
          </div>

          <div className="history-filters">
            <label>
              <span>Prediction horizon</span>
              <select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                {HORIZON_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>Resource</span>
              <select
                value={resourceFilter}
                onChange={(e) => setResourceFilter(e.target.value)}
              >
                {RESOURCE_OPTIONS.map((opt) => (
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
              onClick={() => {
                setLoading(true);
                setRetryKey((k) => k + 1);
              }}
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Statistical Advisory Notice */}
        <div
          style={{
            padding: "12px 14px",
            border: "1px solid var(--border)",
            borderRadius: "6px",
            background: "var(--surface-soft)",
            marginBottom: "20px",
            fontSize: "12px",
            color: "var(--text-muted)",
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
          <span style={{ fontSize: "16px" }}>ℹ️</span>
          <span>
            <strong>Statistical Forecast Notice:</strong> Predictions are estimates generated by
            exponentially weighted linear regression based on actual historical monitoring trends.
            They are intended for workload planning and capacity awareness, not guaranteed future measurements.
          </span>
        </div>

        <ErrorBanner
          message={error}
          onRetry={() => {
            setLoading(true);
            setRetryKey((k) => k + 1);
          }}
        />

        {loading && !data ? (
          <div className="cpu-alert-skeleton">
            <Skeleton />
            <Skeleton />
          </div>
        ) : (
          <>
            {/* The 5 Detailed Resource Prediction Cards */}
            <div className="prediction-grid">
              {predictions.map((pred) => {
                const title = METRIC_TITLES[pred.metric] || pred.metric;
                const isAvailable = pred.status === "available" && pred.predicted_value !== null;
                const delta = formatDelta(pred.metric, pred.current_value, pred.predicted_value);

                return (
                  <div
                    key={pred.metric}
                    className={`prediction-card ${isAvailable ? "prediction-card-available" : "prediction-card-insufficient"}`}
                  >
                    {/* Card Header */}
                    <div className="prediction-card-header">
                      <div>
                        <strong>{title}</strong>
                        <small>{pred.resource.toUpperCase()}</small>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                        {isAvailable && pred.trend && (
                          <span
                            className="prediction-trend-badge"
                            style={{
                              color: trendColor(pred.trend),
                              borderColor: trendColor(pred.trend),
                            }}
                          >
                            {trendSymbol(pred.trend)}
                          </span>
                        )}
                        <span
                          className={`cpu-alert-state cpu-alert-${isAvailable ? "normal" : "warning"}`}
                          style={{ fontSize: "10px" }}
                        >
                          <span className="cpu-alert-indicator" />
                          {isAvailable ? "Forecast Ready" : "Warming up"}
                        </span>
                      </div>
                    </div>

                    {/* Main Comparison Values */}
                    {isAvailable ? (
                      <div className="prediction-card-values">
                        <div className="prediction-val-box">
                          <span className="prediction-val-label">CURRENT</span>
                          <strong className="prediction-val-number">
                            {formatValue(pred.metric, pred.current_value)}
                          </strong>
                        </div>

                        <span className="prediction-val-arrow">→</span>

                        <div className="prediction-val-box">
                          <span className="prediction-val-label">
                            PREDICTED ({pred.horizon})
                          </span>
                          <strong
                            className="prediction-val-number"
                            style={{ color: "var(--accent)" }}
                          >
                            {formatValue(pred.metric, pred.predicted_value)}
                          </strong>
                        </div>

                        {delta && (
                          <div className="prediction-val-box" style={{ marginLeft: "auto" }}>
                            <span className="prediction-val-label">CHANGE (Δ)</span>
                            <span
                              className="prediction-delta-badge"
                              style={{ color: trendColor(pred.trend) }}
                            >
                              {delta}
                            </span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ margin: "14px 0" }}>
                        <p style={{ margin: "0 0 6px 0", fontSize: "13px", fontWeight: "600", color: "var(--warning)" }}>
                          Insufficient Historical Data
                        </p>
                        <p style={{ margin: 0, fontSize: "12px", color: "var(--text-muted)" }}>
                          {pred.message}
                        </p>
                      </div>
                    )}

                    {/* Prediction Range Interval (Lower — Upper Bounds) */}
                    {isAvailable && pred.lower_bound !== null && pred.upper_bound !== null && (
                      <div className="prediction-range-section">
                        <div className="prediction-range-labels">
                          <span>
                            Forecast Interval (95% CI):{" "}
                            <strong>
                              {formatValue(pred.metric, pred.lower_bound)} –{" "}
                              {formatValue(pred.metric, pred.upper_bound)}
                            </strong>
                          </span>
                          {pred.confidence_score !== null && (
                            <span>
                              Confidence:{" "}
                              <strong>{Math.round(pred.confidence_score * 100)}%</strong>
                            </span>
                          )}
                        </div>

                        {/* Visual Range Bar for Utilization */}
                        {pred.unit === "percent" && (
                          <div className="prediction-range-track">
                            <div
                              className="prediction-range-band"
                              style={{
                                left: `${Math.max(0, pred.lower_bound)}%`,
                                width: `${Math.max(1, pred.upper_bound - pred.lower_bound)}%`,
                              }}
                            />
                            <div
                              className="prediction-range-marker marker-current"
                              style={{ left: `${Math.max(0, Math.min(100, pred.current_value || 0))}%` }}
                              title={`Current: ${pred.current_value}%`}
                            />
                            <div
                              className="prediction-range-marker marker-predicted"
                              style={{ left: `${Math.max(0, Math.min(100, pred.predicted_value || 0))}%` }}
                              title={`Predicted: ${pred.predicted_value}%`}
                            />
                          </div>
                        )}
                      </div>
                    )}

                    {/* Card Footer Metadata */}
                    <div className="prediction-card-footer">
                      <small>
                        Target Time:{" "}
                        <strong>{formatDateTime(pred.prediction_timestamp)}</strong>
                      </small>
                      <small>
                        Trained on <strong>{pred.sample_count} samples</strong> ·{" "}
                        <code>WOLS Regression</code>
                      </small>
                    </div>
                  </div>
                );
              })}
            </div>

            {predictions.length === 0 && !loading && (
              <EmptyState
                title="No predictions match your filter"
                message="Try changing the resource filter to view forecasts for other system resources."
              />
            )}

            {/* Visual Forecast Overview Charts */}
            {predictions.some((p) => p.status === "available") && (
              <div className="history-chart-grid" style={{ marginTop: "28px" }}>
                {/* Utilization Chart */}
                {utilizationChartData.length > 0 && (
                  <div className="panel">
                    <div className="panel-heading">
                      <div>
                        <h3>Utilization Forecast (Current vs Predicted)</h3>
                        <p>Comparison of measured utilization against the {horizon} forecast.</p>
                      </div>
                    </div>

                    <div style={{ width: "100%", height: "220px", marginTop: "12px" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={utilizationChartData}
                          margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                          <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11} tickLine={false} />
                          <YAxis
                            stroke="var(--text-muted)"
                            fontSize={11}
                            unit="%"
                            domain={[0, 100]}
                            tickLine={false}
                          />
                          <Tooltip content={<PredictionChartTooltip unit="percent" />} />
                          <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                          <Bar dataKey="current" name="Current Measured" fill="#5577ec" radius={[3, 3, 0, 0]} />
                          <Bar dataKey="predicted" name={`Predicted (${horizon})`} fill="#9b6bdf" radius={[3, 3, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}

                {/* Network Throughput Chart */}
                {throughputChartData.length > 0 && (
                  <div className="panel">
                    <div className="panel-heading">
                      <div>
                        <h3>Network Throughput Forecast</h3>
                        <p>Incoming and outgoing transfer speeds over the {horizon} horizon.</p>
                      </div>
                    </div>

                    <div style={{ width: "100%", height: "220px", marginTop: "12px" }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart
                          data={throughputChartData}
                          margin={{ top: 10, right: 10, left: -15, bottom: 0 }}
                        >
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" opacity={0.6} />
                          <XAxis dataKey="name" stroke="var(--text-muted)" fontSize={11} tickLine={false} />
                          <YAxis
                            stroke="var(--text-muted)"
                            fontSize={10}
                            tickFormatter={(v) => formatRate(v)}
                            tickLine={false}
                          />
                          <Tooltip content={<PredictionChartTooltip unit="bytes_per_second" />} />
                          <Legend verticalAlign="top" align="right" wrapperStyle={{ paddingBottom: "6px", fontSize: "11px" }} />
                          <Bar dataKey="current" name="Current Speed" fill="#2b9c84" radius={[3, 3, 0, 0]} />
                          <Bar dataKey="predicted" name={`Predicted (${horizon})`} fill="#5478e8" radius={[3, 3, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )}
              </div>
            )}
          </>
        )}
          </>
        )}
      </Panel>
    </div>
  );
}

