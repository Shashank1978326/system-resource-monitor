import { useEffect, useRef, useState } from "react";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import {
  acknowledgeAlert,
  clearAlertHistory,
  deleteAlert,
  errorMessage,
  getAlertHistory,
  getAlerts,
} from "../../services/api";
import { formatBytes } from "../../utils/format";

const REFRESH_INTERVAL_MS = 2_000;
const HISTORY_PAGE_SIZE = 10;
const NOTIFICATION_PREFERENCE_KEY = "resourceMonitor.alertNotifications";

function formatPercent(value) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "Unavailable";
}

function formatCelsius(value) {
  return typeof value === "number" ? `${value.toFixed(1)} °C` : "Unavailable";
}

function formatTimestamp(value) {
  if (!value) return "Not yet measured";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function statusClass(status) {
  return ["Normal", "Warning", "Critical"].includes(status)
    ? status.toLowerCase()
    : "unavailable";
}

function readNotificationPreference() {
  try {
    return window.localStorage.getItem(NOTIFICATION_PREFERENCE_KEY) === "true";
  } catch {
    return false;
  }
}

function AlertReading({ label, status, value, warningThreshold, criticalThreshold }) {
  const className = statusClass(status);
  return (
    <div className={`resource-alert-card cpu-alert-${className}`}>
      <div className="resource-alert-card-heading">
        <strong>{label}</strong>
        <span className={`cpu-alert-state cpu-alert-${className}`}>
          <span className="cpu-alert-indicator" />
          {status || "Unavailable"}
        </span>
      </div>
      <strong className="resource-alert-value">{formatPercent(value)}</strong>
      <small>
        Warning {formatPercent(warningThreshold)} · Critical{" "}
        {formatPercent(criticalThreshold)}
      </small>
    </div>
  );
}

export default function CpuAlerts() {
  const [alerts, setAlerts] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryKey, setRetryKey] = useState(0);
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");
  const [severityFilter, setSeverityFilter] = useState("");
  const [page, setPage] = useState(0);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    readNotificationPreference,
  );
  const [notificationMessage, setNotificationMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyEventId, setBusyEventId] = useState(null);
  const [clearing, setClearing] = useState(false);
  const seenEventIds = useRef(null);

  useEffect(() => {
    let active = true;
    let timeout;
    let controller;

    const refresh = async () => {
      controller = new AbortController();
      try {
        const [current, eventPage] = await Promise.all([
          getAlerts({ signal: controller.signal }),
          getAlertHistory({ limit: 50, signal: controller.signal }),
        ]);
        if (active) {
          setAlerts(current);
          setError("");
          const events = eventPage.events || [];
          if (seenEventIds.current === null) {
            seenEventIds.current = new Set(events.map((event) => event.id));
          } else {
            for (const event of events) {
              if (!seenEventIds.current.has(event.id)) {
                seenEventIds.current.add(event.id);
                if (
                  notificationsEnabled &&
                  ["Warning", "Critical"].includes(event.severity) &&
                  "Notification" in window &&
                  window.Notification.permission === "granted"
                ) {
                  new window.Notification(`${event.resource.toUpperCase()} ${event.severity}`, {
                    body: event.message,
                    tag: `resource-alert-${event.id}`,
                  });
                }
              }
            }
          }
        }
      } catch (requestError) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(requestError));
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
  }, [retryKey, notificationsEnabled]);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setHistoryLoading(true);
    setHistoryError("");
    getAlertHistory({
      resource: resourceFilter || undefined,
      severity: severityFilter || undefined,
      limit: HISTORY_PAGE_SIZE,
      offset: page * HISTORY_PAGE_SIZE,
      signal: controller.signal,
    })
      .then((result) => {
        if (active) setHistory(result);
      })
      .catch((requestError) => {
        if (active && !controller.signal.aborted) {
          setHistoryError(errorMessage(requestError));
        }
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [resourceFilter, severityFilter, page, historyRefreshKey]);

  const cpu = alerts?.status;
  const ram = alerts?.ram?.status;
  const disk = alerts?.disk?.status;
  const temperature = alerts?.temperature;
  const battery = alerts?.battery?.status;
  const temperatureSensors = temperature?.sensors || [];
  const partitions = disk?.partitions || [];
  const highestPartition = partitions.reduce(
    (highest, partition) =>
      !highest || partition.usage_percent > highest.usage_percent ? partition : highest,
    null,
  );
  const statuses = [
    cpu?.status,
    ram?.status,
    disk?.status,
    battery?.status,
    ...temperatureSensors.map((sensor) => sensor.status),
  ].map(statusClass);
  const panelStatus = statuses.includes("critical")
    ? "critical"
    : statuses.includes("warning")
      ? "warning"
      : "normal";
  const currentEvents = [
    ...(alerts?.recent_events || []),
    ...(alerts?.ram?.recent_events || []),
    ...(alerts?.disk?.recent_events || []),
    ...(temperature?.recent_events || []),
    ...(alerts?.battery?.recent_events || []),
  ]
    .sort((left, right) => new Date(right.timestamp) - new Date(left.timestamp))
    .slice(0, 8);

  async function toggleNotifications(enable) {
    setNotificationMessage("");
    if (!enable) {
      setNotificationsEnabled(false);
      try {
        window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEY, "false");
      } catch {
        setNotificationMessage("This browser could not save the notification preference.");
      }
      return;
    }

    if (!("Notification" in window)) {
      setNotificationMessage("Browser notifications are not supported here.");
      return;
    }
    let permission = window.Notification.permission;
    if (permission === "default") {
      permission = await window.Notification.requestPermission();
    }
    if (permission !== "granted") {
      setNotificationsEnabled(false);
      setNotificationMessage(
        permission === "denied"
          ? "Notifications are blocked in this browser's site settings."
          : "Notification permission was not granted.",
      );
      try {
        window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEY, "false");
      } catch {
        setNotificationMessage(
          "Notifications are unavailable and this browser could not save the preference.",
        );
      }
      return;
    }
    setNotificationsEnabled(true);
    try {
      window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEY, "true");
      setNotificationMessage("Browser notifications are enabled.");
    } catch {
      setNotificationMessage("Enabled for this session; browser storage is unavailable.");
    }
  }

  async function runEventAction(eventId, action) {
    setActionError("");
    setBusyEventId(eventId);
    try {
      await action(eventId);
      setHistoryRefreshKey((key) => key + 1);
      setRetryKey((key) => key + 1);
    } catch (requestError) {
      setActionError(errorMessage(requestError));
    } finally {
      setBusyEventId(null);
    }
  }

  async function handleClearHistory() {
    setActionError("");
    setClearing(true);
    try {
      await clearAlertHistory();
      seenEventIds.current = new Set();
      setPage(0);
      setHistoryRefreshKey((key) => key + 1);
      setRetryKey((key) => key + 1);
    } catch (requestError) {
      setActionError(errorMessage(requestError));
    } finally {
      setClearing(false);
    }
  }

  const totalPages = Math.ceil((history?.total || 0) / HISTORY_PAGE_SIZE);

  return (
    <Panel
      title="Resource Alerts"
      subtitle="Alert states and persistent history from CPU, RAM, disk, and available temperature sensors"
      className={`cpu-alert-panel cpu-alert-${panelStatus}`}
    >
      <ErrorBanner
        message={error}
        onRetry={() => {
          setLoading(true);
          setRetryKey((key) => key + 1);
        }}
      />
      {loading && alerts === null ? (
        <div className="cpu-alert-skeleton">
          <Skeleton />
          <Skeleton />
        </div>
      ) : (
        <>
          <div className="resource-alert-grid">
            <AlertReading label="CPU" status={cpu?.status} value={cpu?.cpu_usage_percent}
              warningThreshold={cpu?.warning_threshold_percent} criticalThreshold={cpu?.critical_threshold_percent} />
            <AlertReading label="RAM" status={ram?.status} value={ram?.usage_percent}
              warningThreshold={ram?.warning_threshold_percent} criticalThreshold={ram?.critical_threshold_percent} />
            <AlertReading label="Disk" status={disk?.status} value={highestPartition?.usage_percent}
              warningThreshold={disk?.warning_threshold_percent} criticalThreshold={disk?.critical_threshold_percent} />
            {temperatureSensors.map((sensor) => (
              <div
                className={`resource-alert-card cpu-alert-${statusClass(sensor.status)}`}
                key={sensor.sensor_id}
              >
                <div className="resource-alert-card-heading">
                  <strong>{sensor.sensor_name}{sensor.label ? ` · ${sensor.label}` : ""}</strong>
                  <span className={`cpu-alert-state cpu-alert-${statusClass(sensor.status)}`}>
                    <span className="cpu-alert-indicator" />
                    {sensor.status}
                  </span>
                </div>
                <strong className="resource-alert-value">
                  {formatCelsius(sensor.current_celsius)}
                </strong>
                <small>
                  Warning {formatCelsius(sensor.warning_threshold_celsius)} · Critical{" "}
                  {formatCelsius(sensor.critical_threshold_celsius)}
                </small>
                <small>Sample: {formatTimestamp(sensor.timestamp)}</small>
              </div>
            ))}
            {battery?.availability === "available" ? (
              <div
                className={`resource-alert-card cpu-alert-${statusClass(battery.status)}`}
              >
                <div className="resource-alert-card-heading">
                  <strong>Battery</strong>
                  <span className={`cpu-alert-state cpu-alert-${statusClass(battery.status)}`}>
                    <span className="cpu-alert-indicator" />
                    {battery.status || "Unavailable"}
                  </span>
                </div>
                <strong className="resource-alert-value">
                  {formatPercent(battery.percentage)}
                </strong>
                <small>
                  Warning {formatPercent(battery.warning_threshold_percent)} · Critical{" "}
                  {formatPercent(battery.critical_threshold_percent)}
                </small>
                <small>
                  Status: {battery.charging_state ? (battery.charging_state.charAt(0).toUpperCase() + battery.charging_state.slice(1)) : "Unknown"}
                  {battery.power_plugged !== null && battery.power_plugged !== undefined ? ` · ${battery.power_plugged ? "Plugged in" : "On battery"}` : ""}
                </small>
                <small>Sample: {formatTimestamp(battery.timestamp)}</small>
              </div>
            ) : null}
          </div>
          <div className="cpu-alert-updated">
            CPU sample: {formatTimestamp(cpu?.timestamp)} · RAM sample:{" "}
            {formatTimestamp(ram?.timestamp)} · Disk sample:{" "}
            {formatTimestamp(disk?.timestamp)}
            {battery?.timestamp ? ` · Battery sample: ${formatTimestamp(battery?.timestamp)}` : ""}
          </div>
          {temperature?.availability !== "available" ? (
            <EmptyState
              title={
                temperature?.availability === "unsupported"
                  ? "Temperature alerts not supported"
                  : "Temperature alerts unavailable"
              }
              message={
                temperature?.message ||
                "Temperature alerting starts only when valid hardware sensor readings are available."
              }
            />
          ) : temperatureSensors.length === 0 ? (
            <EmptyState
              title="No valid temperature readings"
              message="Temperature alerts are configured but inactive until sensors report actual readings."
            />
          ) : null}
          {battery && battery.availability !== "available" ? (
            <EmptyState
              title={
                battery.availability === "unsupported"
                  ? "Battery alerts not supported"
                  : "Battery alerts unavailable"
              }
              message={
                battery.message ||
                "Battery alerts cannot currently be generated because battery hardware was not detected."
              }
            />
          ) : null}

          <div className="disk-alert-partitions">
            <div className="cpu-alert-events-heading">
              <h3>Disk partitions</h3>
              <span>{highestPartition ? `Highest usage: ${highestPartition.mountpoint}` : "No accessible partitions"}</span>
            </div>
            {partitions.length ? (
              <ul>
                {partitions.map((partition) => (
                  <li className={`cpu-alert-event cpu-alert-event-${statusClass(partition.status)}`}
                    key={`${partition.device}:${partition.mountpoint}`}>
                    <span className="cpu-alert-event-indicator" />
                    <span className="cpu-alert-event-copy">
                      <strong>{partition.mountpoint}</strong>
                      <small>{partition.device} · {formatBytes(partition.used_bytes)} used of{" "}
                        {formatBytes(partition.total_bytes)} · {formatBytes(partition.free_bytes)} free</small>
                    </span>
                    <span className="cpu-alert-event-severity">{formatPercent(partition.usage_percent)} · {partition.status}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No disk partition data"
                message="Accessible partition usage will appear after a valid monitoring sample." />
            )}
          </div>

          <div className="cpu-alert-events">
            <div className="cpu-alert-events-heading"><h3>Recent resource alert events</h3></div>
            {currentEvents.length ? (
              <ul>
                {currentEvents.map((event, index) => (
                  <li className={`cpu-alert-event cpu-alert-event-${statusClass(event.severity)}`}
                    key={`${event.resource}-${event.id || event.timestamp}-${index}`}>
                    <span className="cpu-alert-event-indicator" />
                    <span className="cpu-alert-event-copy">
                      <strong>{event.message}</strong>
                      <small>{formatTimestamp(event.timestamp)} · {event.resource.toUpperCase()}
                        {event.mountpoint ? ` · ${event.mountpoint}` : ""} ·
                        {" "}{formatPercent(event.cpu_usage_percent ?? event.usage_percent ?? event.percentage)}
                      </small>
                    </span>
                    <span className="cpu-alert-event-severity">{event.severity}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No resource alerts yet"
                message="Warning, critical, and recovery transitions will appear here." />
            )}
          </div>

          <div className="alert-management">
            <div className="alert-history-heading">
              <div>
                <h3>Alert history</h3>
                <p>Acknowledgement and deletion apply to stored alert events only.</p>
              </div>
              <div className="alert-history-controls">
                <label>
                  <span>Resource</span>
                  <select value={resourceFilter} onChange={(event) => { setResourceFilter(event.target.value); setPage(0); }}>
                    <option value="">All resources</option>
                    <option value="cpu">CPU</option>
                    <option value="ram">RAM</option>
                    <option value="disk">Disk</option>
                    <option value="temperature">Temperature</option>
                    <option value="battery">Battery</option>
                  </select>
                </label>
                <label>
                  <span>Severity</span>
                  <select value={severityFilter} onChange={(event) => { setSeverityFilter(event.target.value); setPage(0); }}>
                    <option value="">All severities</option>
                    <option value="Warning">Warning</option>
                    <option value="Critical">Critical</option>
                    <option value="Normal">Recovery</option>
                  </select>
                </label>
                <button className="alert-danger-button" type="button" disabled={clearing || !history?.total}
                  onClick={handleClearHistory}>{clearing ? "Clearing…" : "Clear history"}</button>
              </div>
            </div>
            <label className="notification-preference">
              <input type="checkbox" checked={notificationsEnabled}
                onChange={(event) => toggleNotifications(event.target.checked)} />
              <span><strong>Browser notifications</strong>
                <small>Show new Warning and Critical events. Permission is requested only when enabled.</small></span>
            </label>
            {notificationMessage && <p className="setting-note" role="status">{notificationMessage}</p>}
            <ErrorBanner message={historyError || actionError} />
            <div className="alert-history-table-wrap">
              <table className="alert-history-table">
                <thead><tr>
                  <th>Time</th><th>Resource</th><th>Severity</th><th>Event</th>
                  <th>Usage</th><th>Acknowledgement</th><th>Actions</th>
                </tr></thead>
                <tbody>
                  {history?.events?.map((event) => (
                    <tr key={event.id}>
                      <td><time dateTime={event.timestamp}>{formatTimestamp(event.timestamp)}</time></td>
                      <td>{event.resource.toUpperCase()}{event.mountpoint ? ` · ${event.mountpoint}` : ""}</td>
                      <td><span className={`history-severity history-severity-${statusClass(event.severity)}`}>{event.severity}</span></td>
                      <td>{event.message}</td>
                      <td>{event.resource === "temperature"
                        ? `${formatCelsius(event.temperature_celsius)} · threshold ${formatCelsius(event.configured_threshold_celsius)}`
                        : event.resource === "battery"
                          ? `${formatPercent(event.utilization_percent)} · threshold ${formatPercent(event.configured_threshold_percent)}`
                          : formatPercent(event.utilization_percent)}</td>
                      <td>{event.acknowledged ? `Acknowledged${event.acknowledged_at ? ` · ${formatTimestamp(event.acknowledged_at)}` : ""}` : "Pending"}</td>
                      <td className="alert-history-actions">
                        <button type="button" disabled={event.acknowledged || busyEventId === event.id}
                          onClick={() => runEventAction(event.id, acknowledgeAlert)}>Acknowledge</button>
                        <button type="button" disabled={busyEventId === event.id}
                          onClick={() => runEventAction(event.id, deleteAlert)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {historyLoading && <p className="setting-note">Loading alert history…</p>}
              {!historyLoading && !history?.events?.length && (
                <EmptyState title="No matching alert events" message="New resource state transitions will appear here." />
              )}
            </div>
            <div className="alert-history-pagination">
              <span>{history?.total || 0} events · Page {totalPages ? page + 1 : 0} of {totalPages}</span>
              <div>
                <button type="button" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
                <button type="button" disabled={!totalPages || page + 1 >= totalPages}
                  onClick={() => setPage((value) => value + 1)}>Next</button>
              </div>
            </div>
          </div>
        </>
      )}
    </Panel>
  );
}
