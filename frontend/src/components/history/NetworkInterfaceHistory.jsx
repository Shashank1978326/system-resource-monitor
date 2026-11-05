import { useEffect, useState } from "react";
import HistoricalChart from "./HistoricalChart";
import Panel from "../common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../common/StateMessage";
import { intervals, isOverLimit, ranges } from "./historyOptions";
import {
  errorMessage,
  getHistoricalNetworkInterfaces,
} from "../../services/api";

const groups = [
  {
    title: "Interface Download Throughput History",
    unit: "interface_rate",
    series: [
      {
        metric: "network_interface_download",
        label: "Download",
        color: "#2b9c84",
      },
    ],
  },
  {
    title: "Interface Upload Throughput History",
    unit: "interface_rate",
    series: [
      {
        metric: "network_interface_upload",
        label: "Upload",
        color: "#5577ec",
      },
    ],
  },
];

export default function NetworkInterfaceHistory({
  range: suppliedRange,
  interval: suppliedInterval,
}) {
  const [interfaces, setInterfaces] = useState(null);
  const [selectedInterface, setSelectedInterface] = useState("");
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [localRange, setLocalRange] = useState("1h");
  const [selectedLocalInterval, setSelectedLocalInterval] = useState("1m");
  const range = suppliedRange ?? localRange;
  const requestedInterval = suppliedInterval ?? selectedLocalInterval;
  const interval = isOverLimit(range, requestedInterval)
    ? "5m"
    : requestedInterval;

  useEffect(() => {
    const controller = new AbortController();
    getHistoricalNetworkInterfaces({ signal: controller.signal })
      .then((response) => {
        setInterfaces(response.interfaces);
        setSelectedInterface((current) =>
          response.interfaces.includes(current)
            ? current
            : response.interfaces[0] || "",
        );
        setError("");
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(errorMessage(requestError));
          setInterfaces([]);
        }
      });
    return () => controller.abort();
  }, [reloadKey]);

  return (
    <section className="network-history-section">
      <Panel
        title="Historical per-interface traffic"
        subtitle="Compare recorded download and upload throughput for one interface"
      >
        {error && (
          <ErrorBanner
            message={error}
            onRetry={() => {
              setInterfaces(null);
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
                  <option value={value} key={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Aggregation interval</span>
              <select
                value={interval}
                onChange={(event) =>
                  setSelectedLocalInterval(event.target.value)
                }
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
        {interfaces === null ? (
          <Skeleton className="network-history-skeleton" />
        ) : interfaces.length === 0 ? (
          <EmptyState
            title={error ? "Couldn’t load historical interfaces" : "No interface history"}
            message={
              error ||
              "Per-interface history will appear after the monitor records interface samples."
            }
          />
        ) : (
          <label className="network-interface-select">
            <span>Network interface</span>
            <select
              aria-label="Historical network interface"
              value={selectedInterface}
              onChange={(event) => setSelectedInterface(event.target.value)}
            >
              {interfaces.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
      </Panel>
      {selectedInterface && (
        <div className="history-chart-grid">
          {groups.map((group) => (
            <HistoricalChart
              key={group.title}
              group={group}
              range={range}
              interval={interval}
              interfaceName={selectedInterface}
            />
          ))}
        </div>
      )}
    </section>
  );
}
