import { useEffect, useState } from "react";
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import { errorMessage, getProcessDetail, getProcesses } from "../services/api";

const REFRESH_INTERVAL_MS = 10_000;
const COMMON_PROCESS_STATUSES = [
  "running",
  "sleeping",
  "disk-sleep",
  "stopped",
  "tracing-stop",
  "zombie",
  "dead",
  "wake-kill",
  "waking",
  "idle",
  "locked",
  "waiting",
  "parked",
];

function formatPercent(value) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "Unavailable";
}

function formatMemory(value) {
  return typeof value === "number" ? `${value.toFixed(1)} MB` : "Unavailable";
}

function consumptionClass(value, threshold) {
  if (typeof value !== "number") return "process-value-unavailable";
  return value >= threshold ? "process-value-high" : "process-value-normal";
}

function TopProcesses({ title, processes, metric }) {
  return (
    <Panel
      title={title}
      subtitle={
        metric === "cpu"
          ? "Highest measured usage; Windows idle capacity is excluded"
          : "Highest measured usage in the current sample"
      }
    >
      {processes?.length ? (
        <ol className="process-top-list">
          {processes.map((process) => {
            const value =
              metric === "cpu"
                ? formatPercent(process.cpu_percent)
                : formatMemory(process.memory_mb);
            return (
              <li key={process.pid}>
                <span className="process-top-name" title={process.name || "Unavailable"}>
                  <strong>{process.name || "Unavailable"}</strong>
                  <small>PID {process.pid}</small>
                </span>
                <span
                  className={`process-resource-value ${
                    metric === "cpu"
                      ? consumptionClass(process.cpu_percent, 50)
                      : consumptionClass(process.memory_mb, 512)
                  }`}
                >
                  {value}
                </span>
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState title="Usage unavailable" message="No current measurements are available." />
      )}
    </Panel>
  );
}

export default function Processes() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [processList, setProcessList] = useState(null);
  const [selectedPid, setSelectedPid] = useState(null);
  const [processDetail, setProcessDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [sortMode, setSortMode] = useState("pid_asc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sortBy, sortOrder] = sortMode.split("_");

  useEffect(() => {
    const timeout = window.setTimeout(
      () => setDebouncedSearch(search.trim()),
      300,
    );
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    let controller;

    const loadProcesses = async () => {
      if (inFlight) return;
      inFlight = true;
      const requestController = new AbortController();
      controller = requestController;
      setLoading(true);
      setError("");

      try {
        const result = await getProcesses({
          search: debouncedSearch,
          status: statusFilter,
          sortBy,
          sortOrder,
          signal: requestController.signal,
        });
        if (active) setProcessList(result);
      } catch (requestError) {
        if (active && !requestController.signal.aborted) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (active && !requestController.signal.aborted) {
          inFlight = false;
          setLoading(false);
        }
      }
    };

    loadProcesses();
    const refreshTimer = window.setInterval(
      loadProcesses,
      REFRESH_INTERVAL_MS,
    );
    return () => {
      active = false;
      window.clearInterval(refreshTimer);
      controller?.abort();
    };
  }, [debouncedSearch, refreshKey, sortBy, sortOrder, statusFilter]);

  useEffect(() => {
    if (selectedPid === null) {
      setProcessDetail(null);
      setDetailError("");
      return undefined;
    }

    let active = true;
    const controller = new AbortController();
    setProcessDetail(null);
    setDetailError("");
    setDetailLoading(true);

    getProcessDetail(selectedPid, { signal: controller.signal })
      .then((detail) => {
        if (active) setProcessDetail(detail);
      })
      .catch((requestError) => {
        if (active && !controller.signal.aborted) {
          setDetailError(errorMessage(requestError));
        }
      })
      .finally(() => {
        if (active && !controller.signal.aborted) setDetailLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [selectedPid]);

  const processes = processList?.processes ?? [];
  const statusOptions = [
    ...new Set([
      ...COMMON_PROCESS_STATUSES,
      ...processes.map((process) => process.status),
      statusFilter,
    ]),
  ]
    .filter(Boolean)
    .sort();

  return (
    <div className="process-page">
      <div className="process-summary">
        <div>
          <span className="process-summary-label">TOTAL PROCESS COUNT</span>
          <strong>{processList?.total_process_count ?? "—"}</strong>
          <span className="process-summary-caption">
            {search.trim()
              ? `${processList?.total_processes ?? 0} matching the current search`
              : "currently enumerated"}
          </span>
        </div>
        <button
          className="process-refresh"
          type="button"
          onClick={() => setRefreshKey((key) => key + 1)}
          disabled={loading}
        >
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <Panel
        title="Running processes"
        subtitle="Live per-process CPU and RAM usage. Command-line arguments and environment data are not collected."
      >
        <div className="process-toolbar">
          <label className="process-search">
            <span>Search process names</span>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name"
              maxLength={100}
            />
          </label>
          <label className="process-sort">
            <span>Filter by status</span>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="">All statuses</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status.replaceAll("-", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="process-sort">
            <span>Sort processes</span>
            <select
              value={sortMode}
              onChange={(event) => setSortMode(event.target.value)}
            >
              <option value="pid_asc">Process ID</option>
              <option value="cpu_desc">CPU usage: highest first</option>
              <option value="cpu_asc">CPU usage: lowest first</option>
              <option value="ram_desc">RAM usage: highest first</option>
              <option value="ram_asc">RAM usage: lowest first</option>
            </select>
          </label>
          <span className="process-count">
            Showing {processes.length} of {processList?.total_processes ?? "—"}
          </span>
        </div>

        <ErrorBanner
          message={error}
          onRetry={() => setRefreshKey((key) => key + 1)}
        />

        {selectedPid !== null && (
          <Panel
            title={`Process details · PID ${selectedPid}`}
            subtitle="Current process information; fields may be unavailable due to permissions or process changes."
            className="process-detail-panel"
            action={
              <button
                className="process-close"
                type="button"
                onClick={() => setSelectedPid(null)}
                aria-label="Close process details"
              >
                Close
              </button>
            }
          >
            <ErrorBanner message={detailError} />
            {detailLoading ? (
              <div className="process-loading" aria-label="Loading process details">
                <Skeleton />
                <Skeleton />
              </div>
            ) : processDetail ? (
              <dl className="process-detail-grid">
                <div><dt>PID</dt><dd>{processDetail.pid}</dd></div>
                <div><dt>Process name</dt><dd>{processDetail.name || "Unavailable"}</dd></div>
                <div><dt>Status</dt><dd>{processDetail.status || "Unavailable"}</dd></div>
                <div><dt>CPU utilization</dt><dd>{formatPercent(processDetail.cpu_percent)}</dd></div>
                <div><dt>RAM usage</dt><dd>{formatMemory(processDetail.memory_mb)}</dd></div>
                <div><dt>RAM utilization</dt><dd>{formatPercent(processDetail.memory_percent)}</dd></div>
                <div><dt>Thread count</dt><dd>{processDetail.thread_count ?? "Unavailable"}</dd></div>
                <div>
                  <dt>Process creation time</dt>
                  <dd>
                    {processDetail.create_time
                      ? new Date(processDetail.create_time).toLocaleString()
                      : "Unavailable"}
                  </dd>
                </div>
                {processDetail.username && (
                  <div><dt>Username</dt><dd>{processDetail.username}</dd></div>
                )}
              </dl>
            ) : null}
          </Panel>
        )}

        {loading && processList === null ? (
          <div className="process-loading" aria-label="Loading processes">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </div>
        ) : error && processList === null ? null : processes.length === 0 ? (
          <EmptyState
            title={search.trim() ? "No matching processes" : "No processes available"}
            message={
              search.trim()
                ? "Try another process name."
                : "The backend did not return any visible processes."
            }
          />
        ) : (
          <div className="process-table-wrap">
            <table className="process-table">
              <thead>
                <tr>
                  <th scope="col">PID</th>
                  <th scope="col">Process name</th>
                  <th scope="col">Status</th>
                  <th scope="col">CPU usage</th>
                  <th scope="col">RAM usage</th>
                  <th scope="col" className="col-hide-mobile">RAM usage %</th>
                </tr>
              </thead>
              <tbody>
                {processes.map((process) => (
                  <tr key={process.pid}>
                    <td className="process-pid">{process.pid}</td>
                    <td>
                      <button
                        className="process-row-select"
                        type="button"
                        aria-label={`View details for ${process.name || "process"} PID ${process.pid}`}
                        aria-pressed={selectedPid === process.pid}
                        disabled={process.pid === 0}
                        title={
                          process.pid === 0
                            ? "Windows System Idle Process does not provide individual process details."
                            : undefined
                        }
                        onClick={() => setSelectedPid(process.pid)}
                      >
                        {process.name || "Unavailable"}
                      </button>
                    </td>
                    <td>
                      <span className={`process-status process-status-${String(process.status || "unknown").replace(/[^a-z0-9-]/gi, "")}`}>
                        {process.status || "Unavailable"}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`process-resource-value ${
                          process.pid === 0
                            ? "process-value-idle"
                            : consumptionClass(process.cpu_percent, 50)
                        }`}
                        title={
                          process.pid === 0
                            ? "The Windows idle process reflects unused CPU capacity."
                            : undefined
                        }
                      >
                        {formatPercent(process.cpu_percent)}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`process-resource-value ${
                          typeof process.memory_mb !== "number"
                            ? "process-value-unavailable"
                            : process.memory_mb >= 512 ||
                                (process.memory_percent ?? 0) >= 10
                              ? "process-value-high"
                              : "process-value-normal"
                        }`}
                      >
                        {formatMemory(process.memory_mb)}
                      </span>
                    </td>
                    <td className="col-hide-mobile">{formatPercent(process.memory_percent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="process-top-grid">
        <TopProcesses
          title="Top 5 CPU-consuming processes"
          processes={processList?.top_cpu_processes}
          metric="cpu"
        />
        <TopProcesses
          title="Top 5 RAM-consuming processes"
          processes={processList?.top_ram_processes}
          metric="ram"
        />
      </div>
    </div>
  );
}
