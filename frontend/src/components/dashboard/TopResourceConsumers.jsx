import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { errorMessage, getProcesses } from "../../services/api";

const REFRESH_INTERVAL_MS = 30_000;

function ConsumerList({ title, processes, metric }) {
  return (
    <section className="consumer-list">
      <h3>{title}</h3>
      {processes?.length ? (
        <ol className="process-top-list">
          {processes.map((process) => {
            const value =
              metric === "cpu"
                ? typeof process.cpu_percent === "number"
                  ? `${process.cpu_percent.toFixed(1)}%`
                  : "Unavailable"
                : typeof process.memory_mb === "number"
                  ? `${process.memory_mb.toFixed(1)} MB`
                  : "Unavailable";
            return (
              <li key={process.pid}>
                <span className="process-top-name" title={process.name || "Unavailable"}>
                  <strong>{process.name || "Unavailable"}</strong>
                  <small>PID {process.pid}</small>
                </span>
                <span className="process-consumer-value">{value}</span>
              </li>
            );
          })}
        </ol>
      ) : (
        <EmptyState
          title="No measurements available"
          message="Resource usage will appear after a process sample is available."
        />
      )}
    </section>
  );
}

export default function TopResourceConsumers() {
  const [processes, setProcesses] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let timeout;
    let controller;

    const loadConsumers = async () => {
      controller = new AbortController();
      try {
        const result = await getProcesses({ limit: 1, signal: controller.signal });
        if (active) {
          setProcesses({
            cpu: result.top_cpu_processes,
            ram: result.top_ram_processes,
          });
          setError("");
        }
      } catch (requestError) {
        if (active && !controller.signal.aborted) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (active) timeout = window.setTimeout(loadConsumers, REFRESH_INTERVAL_MS);
      }
    };

    loadConsumers();
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller?.abort();
    };
  }, []);

  return (
    <Panel
      title="Top Resource Consumers"
      subtitle="Highest process CPU and RAM usage from the latest process sample"
      action={<Link className="panel-link" to="/processes">View all processes ↗</Link>}
    >
      <ErrorBanner message={error} />
      {processes === null && !error ? (
        <div className="consumer-grid" aria-label="Loading top resource consumers">
          <div className="process-loading"><Skeleton /><Skeleton /><Skeleton /></div>
          <div className="process-loading"><Skeleton /><Skeleton /><Skeleton /></div>
        </div>
      ) : (
        <div className="consumer-grid">
          <ConsumerList title="Top 5 CPU" processes={processes?.cpu} metric="cpu" />
          <ConsumerList title="Top 5 RAM" processes={processes?.ram} metric="ram" />
        </div>
      )}
    </Panel>
  );
}
