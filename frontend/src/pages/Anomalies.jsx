import { useEffect, useRef, useState } from "react";
import AnomalyAnalytics from "../components/anomalies/AnomalyAnalytics";
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import {
  clearAnomalyHistory,
  deleteAnomalyEvent,
  errorMessage,
  getAnomalies,
  getAnomalyHistory,
} from "../services/api";
import { formatDateTime, formatPercent, formatRate } from "../utils/format";

const REFRESH_INTERVAL_MS = 3_000;
const HISTORY_PAGE_SIZE = 10;

const METRIC_DEFINITIONS = [
  { resource: "cpu", metric: "cpu_utilization", label: "CPU Utilization", isPercent: true },
  { resource: "memory", metric: "memory_utilization", label: "Memory Utilization", isPercent: true },
  { resource: "disk", metric: "disk_read_throughput", label: "Disk Read Throughput", isRate: true },
  { resource: "disk", metric: "disk_write_throughput", label: "Disk Write Throughput", isRate: true },
  { resource: "network", metric: "network_download_throughput", label: "Network Download", isRate: true },
  { resource: "network", metric: "network_upload_throughput", label: "Network Upload", isRate: true },
];

function statusClass(severity) {
  if (severity === "Critical") return "critical";
  if (severity === "Warning") return "warning";
  return "normal";
}

function formatMetricValue(metric, value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  if (metric.includes("utilization")) {
    return formatPercent(value);
  }
  return formatRate(value);
}

export default function Anomalies() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);

  // History state
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [metricFilter, setMetricFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [page, setPage] = useState(0);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [busyEventId, setBusyEventId] = useState(null);
  const [actionError, setActionError] = useState("");
  const [clearing, setClearing] = useState(false);

  // Auto-refresh for overview
  useEffect(() => {
    let active = true;
    let timeout;
    let controller;

    const refresh = async () => {
      controller = new AbortController();
      try {
        const result = await getAnomalies({ signal: controller.signal });
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
          timeout = window.setTimeout(refresh, REFRESH_INTERVAL_MS);
        }
      }
    };

    refresh();
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller?.abort();
    };
  }, [retryKey]);

  // History pagination & filters
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setHistoryLoading(true);
    setHistoryError("");

    getAnomalyHistory({
      resource: resourceFilter || undefined,
      metric: metricFilter || undefined,
      severity: severityFilter || undefined,
      limit: HISTORY_PAGE_SIZE,
      offset: page * HISTORY_PAGE_SIZE,
      signal: controller.signal,
    })
      .then((res) => {
        if (active) setHistory(res);
      })
      .catch((err) => {
        if (active && !controller.signal.aborted) {
          setHistoryError(errorMessage(err));
        }
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [resourceFilter, metricFilter, severityFilter, page, historyRefreshKey]);

  async function handleDeleteEvent(eventId) {
    setActionError("");
    setBusyEventId(eventId);
    try {
      await deleteAnomalyEvent(eventId);
      setHistoryRefreshKey((k) => k + 1);
      setRetryKey((k) => k + 1);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusyEventId(null);
    }
  }

  async function handleClearHistory() {
    if (
      !window.confirm(
        "Are you sure you want to clear all anomaly history? This cannot be undone.",
      )
    ) {
      return;
    }
    setActionError("");
    setClearing(true);
    try {
      await clearAnomalyHistory();
      setPage(0);
      setHistoryRefreshKey((k) => k + 1);
      setRetryKey((k) => k + 1);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setClearing(false);
    }
  }

  const isEnabled = data?.status?.enabled ?? data?.configuration?.enabled ?? true;
  const sampleCounts = data?.status?.sample_counts || {};
  const minSamples = data?.status?.min_samples || 20;
  const recentEvents = data?.recent_events || [];

  // Group latest event by metric
  const latestByMetric = {};
  for (const event of recentEvents) {
    if (!latestByMetric[event.metric]) {
      latestByMetric[event.metric] = event;
    }
  }

  // Statistics
  const warningCount = recentEvents.filter((e) => e.severity === "Warning").length;
  const criticalCount = recentEvents.filter((e) => e.severity === "Critical").length;
  const activeAnomaliesCount = Object.values(latestByMetric).filter(
    (e) => e.severity === "Warning" || e.severity === "Critical",
  ).length;
  const lastEvent = recentEvents[0];
  const lastDetectedTimestamp = lastEvent ? formatDateTime(lastEvent.timestamp) : "None detected";
  const totalStoredEvents = history?.total ?? recentEvents.length;
  const totalPages = Math.ceil((history?.total || 0) / HISTORY_PAGE_SIZE);

  return (
    <div className="anomalies-page">
      <Panel
        title="Real-Time Resource Anomaly Detection"
        subtitle="Z-score statistical anomaly monitoring across CPU, memory, disk, and network transfer rates"
      >
        <ErrorBanner
          message={error}
          onRetry={() => {
            setLoading(true);
            setRetryKey((k) => k + 1);
          }}
        />

        {!isEnabled && (
          <div className="empty-state" style={{ marginBottom: "16px", borderColor: "var(--warning)" }}>
            <h3>Anomaly Detection Engine Disabled</h3>
            <p>
              Statistical anomaly detection is currently switched off. You can enable it in the{" "}
              <strong>Settings</strong> page.
            </p>
          </div>
        )}

        {loading && data === null ? (
          <div className="cpu-alert-skeleton">
            <Skeleton />
            <Skeleton />
          </div>
        ) : (
          <>
            {/* Overview Metric Summary */}
            <div className="anomaly-summary-grid">
              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">ENGINE STATUS</span>
                <div className="anomaly-summary-value-wrap">
                  <span className={`cpu-alert-state cpu-alert-${isEnabled ? "normal" : "warning"}`}>
                    <span className="cpu-alert-indicator" />
                    {isEnabled ? "Active & Monitoring" : "Disabled"}
                  </span>
                </div>
                <small>Sensitivity threshold: Z ≥ {data?.status?.z_score_threshold ?? 3.0}</small>
              </div>

              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">ACTIVE ANOMALIES</span>
                <strong className="anomaly-summary-value" style={{ color: activeAnomaliesCount > 0 ? "var(--danger, #ef4444)" : "inherit" }}>
                  {activeAnomaliesCount}
                </strong>
                <small>Across 6 monitored resource metrics</small>
              </div>

              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">RECENT WARNINGS</span>
                <strong className="anomaly-summary-value" style={{ color: warningCount > 0 ? "var(--warning, #f59e0b)" : "inherit" }}>
                  {warningCount}
                </strong>
                <small>Z-score: 3.0 ≤ Z &lt; 4.5</small>
              </div>

              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">RECENT CRITICAL</span>
                <strong className="anomaly-summary-value" style={{ color: criticalCount > 0 ? "var(--danger, #ef4444)" : "inherit" }}>
                  {criticalCount}
                </strong>
                <small>Z-score: Z ≥ 4.5</small>
              </div>

              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">TOTAL STORED EVENTS</span>
                <strong className="anomaly-summary-value">{totalStoredEvents}</strong>
                <small>Persisted in SQLite database</small>
              </div>

              <div className="anomaly-summary-card">
                <span className="anomaly-summary-label">LAST DETECTED ANOMALY</span>
                <strong className="anomaly-summary-value" style={{ fontSize: "14px" }}>
                  {lastDetectedTimestamp}
                </strong>
                <small>{lastEvent ? `${lastEvent.resource.toUpperCase()} (${lastEvent.severity})` : "System stable"}</small>
              </div>
            </div>

            {/* 6 Monitored Resource Cards */}
            <div className="cpu-alert-events-heading" style={{ marginTop: "24px" }}>
              <h3>Monitored Resource Metrics</h3>
              <span>Rolling baseline window: {data?.status?.window_size || 60} samples</span>
            </div>

            <div className="resource-alert-grid">
              {METRIC_DEFINITIONS.map(({ resource, metric, label }) => {
                const event = latestByMetric[metric];
                const samples = sampleCounts[metric] || 0;
                const isReady = samples >= minSamples;
                const severity = event ? event.severity : "Normal";
                const className = statusClass(severity);

                return (
                  <div
                    key={metric}
                    className={`resource-alert-card cpu-alert-${className}`}
                  >
                    <div className="resource-alert-card-heading">
                      <strong>{label}</strong>
                      <span className={`cpu-alert-state cpu-alert-${className}`}>
                        <span className="cpu-alert-indicator" />
                        {event ? event.severity : isReady ? "Normal" : "Warming up"}
                      </span>
                    </div>

                    {event ? (
                      <>
                        <strong className="resource-alert-value">
                          {formatMetricValue(metric, event.actual_value)}
                        </strong>
                        <small>
                          Baseline: {formatMetricValue(metric, event.expected_value)} ±{" "}
                          {formatMetricValue(metric, event.standard_deviation)}
                        </small>
                        <small>
                          Z-score: <strong>{event.z_score.toFixed(2)}</strong> · Threshold:{" "}
                          {data?.status?.z_score_threshold ?? 3.0}
                        </small>
                        <small>Detected: {formatDateTime(event.timestamp)}</small>
                        <p className="anomaly-card-desc">{event.message}</p>
                      </>
                    ) : (
                      <>
                        <strong className="resource-alert-value" style={{ fontSize: "15px", color: "var(--text-muted)" }}>
                          {isReady ? "No anomalies detected" : `Collecting samples… (${samples}/${minSamples})`}
                        </strong>
                        <small>
                          Resource: <strong>{resource.toUpperCase()}</strong> · Metric: <code>{metric}</code>
                        </small>
                        <small>
                          Baseline readiness: {samples} / {data?.status?.window_size || 60} samples stored
                        </small>
                      </>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Recent Anomaly Events */}
            <div className="cpu-alert-events" style={{ marginTop: "24px" }}>
              <div className="cpu-alert-events-heading">
                <h3>Recent Anomaly Events</h3>
                <span>{recentEvents.length} recent event(s)</span>
              </div>

              {recentEvents.length ? (
                <ul>
                  {recentEvents.slice(0, 6).map((evt, idx) => (
                    <li
                      key={`${evt.id || evt.timestamp}-${idx}`}
                      className={`cpu-alert-event cpu-alert-event-${statusClass(evt.severity)}`}
                    >
                      <span className="cpu-alert-event-indicator" />
                      <span className="cpu-alert-event-copy">
                        <strong>{evt.message}</strong>
                        <small>
                          {formatDateTime(evt.timestamp)} · {evt.resource.toUpperCase()} ·{" "}
                          <code>{evt.metric}</code> · Z-score: <strong>{evt.z_score.toFixed(2)}</strong>
                        </small>
                      </span>
                      <span className="cpu-alert-event-severity">{evt.severity}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title="No anomalies detected yet"
                  message="When metric deviations exceed the statistical threshold (Z ≥ 3.0), they will appear here in real time."
                />
              )}
            </div>

            {/* Anomaly Trend Analytics (Feature 8C) */}
            <AnomalyAnalytics />

            {/* Historical Anomaly Events Table */}
            <div className="alert-management" style={{ marginTop: "28px" }}>
              <div className="alert-history-heading">
                <div>
                  <h3>Anomaly Event History</h3>
                  <p>Browse, filter, and manage persisted anomaly events recorded in SQLite.</p>
                </div>
                <div className="alert-history-controls">
                  <label>
                    <span>Resource</span>
                    <select
                      value={resourceFilter}
                      onChange={(e) => {
                        setResourceFilter(e.target.value);
                        setPage(0);
                      }}
                    >
                      <option value="">All resources</option>
                      <option value="cpu">CPU</option>
                      <option value="memory">Memory</option>
                      <option value="disk">Disk</option>
                      <option value="network">Network</option>
                    </select>
                  </label>

                  <label>
                    <span>Metric</span>
                    <select
                      value={metricFilter}
                      onChange={(e) => {
                        setMetricFilter(e.target.value);
                        setPage(0);
                      }}
                    >
                      <option value="">All metrics</option>
                      <option value="cpu_utilization">CPU utilization</option>
                      <option value="memory_utilization">Memory utilization</option>
                      <option value="disk_read_throughput">Disk read throughput</option>
                      <option value="disk_write_throughput">Disk write throughput</option>
                      <option value="network_download_throughput">Network download</option>
                      <option value="network_upload_throughput">Network upload</option>
                    </select>
                  </label>

                  <label>
                    <span>Severity</span>
                    <select
                      value={severityFilter}
                      onChange={(e) => {
                        setSeverityFilter(e.target.value);
                        setPage(0);
                      }}
                    >
                      <option value="">All severities</option>
                      <option value="Warning">Warning</option>
                      <option value="Critical">Critical</option>
                    </select>
                  </label>

                  <button
                    className="alert-danger-button"
                    type="button"
                    disabled={clearing || !history?.total}
                    onClick={handleClearHistory}
                  >
                    {clearing ? "Clearing…" : "Clear history"}
                  </button>
                </div>
              </div>

              <ErrorBanner message={historyError || actionError} />

              <div className="alert-history-table-wrap">
                <table className="alert-history-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Resource</th>
                      <th className="col-hide-mobile">Metric</th>
                      <th>Severity</th>
                      <th>Measured</th>
                      <th className="col-hide-mobile">Baseline (Mean ± SD)</th>
                      <th>Z-Score</th>
                      <th className="col-hide-mobile">Description</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history?.events?.map((ev) => (
                      <tr key={ev.id}>
                        <td>
                          <time dateTime={ev.timestamp}>{formatDateTime(ev.timestamp)}</time>
                        </td>
                        <td>
                          <strong>{ev.resource.toUpperCase()}</strong>
                        </td>
                        <td className="col-hide-mobile">
                          <code>{ev.metric}</code>
                        </td>
                        <td>
                          <span className={`history-severity history-severity-${statusClass(ev.severity)}`}>
                            {ev.severity}
                          </span>
                        </td>
                        <td>
                          <strong>{formatMetricValue(ev.metric, ev.actual_value)}</strong>
                        </td>
                        <td className="col-hide-mobile">
                          {formatMetricValue(ev.metric, ev.expected_value)} ±{" "}
                          {formatMetricValue(ev.metric, ev.standard_deviation)}
                        </td>
                        <td>
                          <strong>{ev.z_score.toFixed(2)}</strong>
                        </td>
                        <td className="col-hide-mobile">{ev.message}</td>
                        <td className="alert-history-actions">
                          <button
                            type="button"
                            disabled={busyEventId === ev.id}
                            onClick={() => handleDeleteEvent(ev.id)}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {historyLoading && <p className="setting-note">Loading anomaly history…</p>}
                {!historyLoading && !history?.events?.length && (
                  <EmptyState
                    title="No matching anomaly events"
                    message="Statistical anomaly transitions matching your filter criteria will appear here."
                  />
                )}
              </div>

              <div className="alert-history-pagination">
                <span>
                  {history?.total || 0} events · Page {totalPages ? page + 1 : 0} of {totalPages}
                </span>
                <div>
                  <button
                    type="button"
                    disabled={page === 0}
                    onClick={() => setPage((v) => Math.max(0, v - 1))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    disabled={!totalPages || page + 1 >= totalPages}
                    onClick={() => setPage((v) => v + 1)}
                  >
                    Next
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </Panel>
    </div>
  );
}

