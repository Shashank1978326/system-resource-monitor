import LiveChart from "../components/charts/LiveChart";
import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner } from "../components/common/StateMessage";
import NetworkInterfaceList from "../components/network/NetworkInterfaceList";
import NetworkInterfaceHistory from "../components/history/NetworkInterfaceHistory";
import useMonitoring from "../hooks/useMonitoring";
import { diskTotals, formatBytes, formatFrequency, formatPercent, formatRate } from "../utils/format";

const pageConfig = {
  cpu: {
    title: "Processor utilization",
    description: "Current CPU utilization and processor capacity.",
    value: (snapshot) => formatPercent(snapshot.cpu.cpu_usage_percent),
    detail: (snapshot) => `${snapshot.cpu.physical_cores ?? "—"} physical · ${snapshot.cpu.logical_cores ?? "—"} logical cores`,
    frequency: (snapshot) => formatFrequency(snapshot.cpu.frequency_mhz),
    chartMetric: "cpu",
  },
  memory: {
    title: "Memory utilization",
    description: "Physical memory capacity and current use.",
    value: (snapshot) => formatPercent(snapshot.memory.usage_percent),
    detail: (snapshot) => `${formatBytes(snapshot.memory.used_bytes)} of ${formatBytes(snapshot.memory.total_bytes)}`,
    frequency: (snapshot) => `${formatBytes(snapshot.memory.available_bytes)} available`,
    chartMetric: "memory",
  },
  disk: {
    title: "Storage utilization",
    description: "Mounted volumes and cumulative disk I/O counters.",
    value: (snapshot) => formatPercent(snapshot.liveDiskPercent ?? diskTotals(snapshot.disk).percent),
    detail: (snapshot) => `${formatBytes(diskTotals(snapshot.disk).used)} used of ${formatBytes(diskTotals(snapshot.disk).total)}`,
    frequency: (snapshot) => `${formatBytes(diskTotals(snapshot.disk).free)} free`,
    chartMetric: "disk",
  },
  network: {
    title: "Network bandwidth",
    description: "Current transfer speeds and cumulative interface counters.",
    value: (snapshot) => formatRate(snapshot.network.download_speed_bytes_per_sec),
    detail: (snapshot) => `${formatBytes(snapshot.network.bytes_received)} received`,
    frequency: (snapshot) => `${formatBytes(snapshot.network.bytes_sent)} sent`,
    chartMetric: "download",
  },
};

export default function ResourcePage({ resource }) {
  const { snapshot, history, connectionError } = useMonitoring();
  const config = pageConfig[resource];
  if (!snapshot) {
    return (
      <>
        <ErrorBanner message={connectionError} />
        <EmptyState title="No live snapshot yet" message="The page will show metrics as soon as the backend has collected its first snapshot." />
      </>
    );
  }

  return (
    <>
      <ErrorBanner message={connectionError} />
      <div className={`resource-detail-hero resource-detail-${resource}`}>
        <div>
          <div className="eyebrow">CURRENT READING</div>
          <strong className="detail-value">{config.value(snapshot)}</strong>
          <p>{config.detail(snapshot)}</p>
        </div>
        <div className="detail-aside">
          <span>{resource === "cpu" ? "Current frequency" : resource === "network" ? "Upload speed" : resource === "disk" ? "Available space" : "Available memory"}</span>
          <strong>{resource === "network" ? formatRate(snapshot.network.upload_speed_bytes_per_sec) : config.frequency(snapshot)}</strong>
        </div>
      </div>
      <div className="detail-grid">
        <Panel title="Live utilization" subtitle={config.description}>
          <LiveChart data={history} metric={config.chartMetric} unit={resource === "network" ? "B/s" : "%"} height={320} showAxis />
        </Panel>
        {resource === "disk" ? (
          <Panel title="Mounted volumes" subtitle="Capacity reported by accessible partitions">
            <div className="volume-list">
              {snapshot.disk.partitions.map((partition) => (
                <div className="volume-row" key={`${partition.device}-${partition.mountpoint}`}>
                  <div className="volume-heading">
                    <strong>{partition.mountpoint}</strong>
                    <span>{formatPercent(partition.usage_percent)}</span>
                  </div>
                  <div className="progress-track"><span style={{ width: `${Math.min(partition.usage_percent, 100)}%` }} /></div>
                  <small>{partition.device} · {formatBytes(partition.used_bytes)} used of {formatBytes(partition.total_bytes)}</small>
                </div>
              ))}
              {snapshot.disk.partitions.length === 0 && (
                <EmptyState title="No volumes available" message="The backend did not report accessible disk partitions." />
              )}
            </div>
            <div className="io-summary">
              <div><span>Read</span><strong>{formatBytes(snapshot.disk.io.read_bytes)}</strong></div>
              <div><span>Written</span><strong>{formatBytes(snapshot.disk.io.write_bytes)}</strong></div>
            </div>
          </Panel>
        ) : resource === "network" ? (
          <Panel title="Transfer activity" subtitle="Live download and upload rates">
            <div className="network-rates">
              <div><span className="legend-dot legend-download" /><span>Download</span><strong>{formatRate(snapshot.network.download_speed_bytes_per_sec)}</strong></div>
              <div><span className="legend-dot legend-upload" /><span>Upload</span><strong>{formatRate(snapshot.network.upload_speed_bytes_per_sec)}</strong></div>
            </div>
            <LiveChart data={history} metric="upload" unit="B/s" height={150} />
          </Panel>
        ) : resource === "memory" ? (
          <Panel title="Memory breakdown" subtitle="Latest physical memory values">
            <div className="memory-breakdown">
              {[
                ["Total memory", snapshot.memory.total_bytes],
                ["In use", snapshot.memory.used_bytes],
                ["Available", snapshot.memory.available_bytes],
                ["Free", snapshot.memory.free_bytes],
                ["Cached", snapshot.memory.cached_bytes],
                ["Swap used", snapshot.memory.swap_used_bytes],
              ].map(([label, amount]) => (
                <div className="breakdown-row" key={label}><span>{label}</span><strong>{formatBytes(amount)}</strong></div>
              ))}
            </div>
            <div className="progress-track memory-progress"><span style={{ width: `${Math.min(snapshot.memory.usage_percent || 0, 100)}%` }} /></div>
            <p className="muted-copy">Swap utilization: {formatPercent(snapshot.memory.swap_percent)}</p>
          </Panel>
        ) : (
          <Panel title="Processor details" subtitle="Reported capacity and utilization">
            <div className="memory-breakdown">
              <div className="breakdown-row"><span>Physical cores</span><strong>{snapshot.cpu.physical_cores ?? "—"}</strong></div>
              <div className="breakdown-row"><span>Logical cores</span><strong>{snapshot.cpu.logical_cores ?? "—"}</strong></div>
              <div className="breakdown-row"><span>Current frequency</span><strong>{formatFrequency(snapshot.cpu.frequency_mhz)}</strong></div>
              <div className="breakdown-row"><span>Minimum frequency</span><strong>{formatFrequency(snapshot.cpu.min_frequency_mhz)}</strong></div>
              <div className="breakdown-row"><span>Maximum frequency</span><strong>{formatFrequency(snapshot.cpu.max_frequency_mhz)}</strong></div>
              <div className="breakdown-row"><span>Status</span><strong className="capitalize">{snapshot.cpu.usage_status || "—"}</strong></div>
            </div>
            {snapshot.cpu.per_core_usage?.length > 0 && (
              <div className="core-list">
                <h3>Per-core utilization</h3>
                {snapshot.cpu.per_core_usage.map((value, index) => (
                  <div className="core-row" key={index}><span>Core {index + 1}</span><div className="progress-track"><span style={{ width: `${Math.min(value, 100)}%` }} /></div><strong>{formatPercent(value)}</strong></div>
                ))}
              </div>
            )}
          </Panel>
        )}
      </div>
      {resource === "network" && <NetworkInterfaceList />}
      {resource === "network" && <NetworkInterfaceHistory />}
    </>
  );
}
