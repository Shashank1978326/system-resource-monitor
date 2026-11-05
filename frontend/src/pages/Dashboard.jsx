import { Link } from "react-router-dom";
import LiveChart from "../components/charts/LiveChart";
import MetricCard from "../components/dashboard/MetricCard";
import TopResourceConsumers from "../components/dashboard/TopResourceConsumers";
import CpuAlerts from "../components/dashboard/CpuAlerts";
import GpuOverview from "../components/dashboard/GpuOverview";
import Panel from "../components/common/Panel";
import Icon from "../components/layout/Icons";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import useMonitoring from "../hooks/useMonitoring";
import {
  diskTotals,
  formatBytes,
  formatFrequency,
  formatPercent,
  formatRate,
} from "../utils/format";

function ResourceSkeletons() {
  return (
    <div className="resource-grid">
      {Array.from({ length: 4 }, (_, index) => (
        <div className="metric-card metric-card-skeleton" key={index}>
          <Skeleton className="skeleton-line skeleton-title" />
          <Skeleton className="skeleton-line skeleton-value" />
          <Skeleton className="skeleton-chart" />
          <Skeleton className="skeleton-line" />
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { snapshot, history, connectionError, connection, systemInfo, monitoringStatus } =
    useMonitoring();
  const totals = diskTotals(snapshot?.disk);
  const snapshotDisk = snapshot?.liveDiskPercent ?? totals.percent;

  if (!snapshot) {
    return (
      <>
        <ErrorBanner message={connectionError} />
        {connection === "connecting" ? (
          <ResourceSkeletons />
        ) : (
          <EmptyState
            title="Monitoring data isn’t available yet"
            message="Start the backend API and its first collection cycle. The dashboard will connect automatically."
          />
        )}
        <div className="dashboard-cpu-alerts">
          <CpuAlerts />
        </div>
        <div className="dashboard-gpu-overview">
          <GpuOverview />
        </div>
      </>
    );
  }

  return (
    <>
      <ErrorBanner message={connectionError} />
      <div className="overview-strip">
        <div className="overview-copy">
          <span className="overview-status">
            <span className={`status-dot ${connection === "connected" ? "status-dot-live" : "status-dot-error"}`} />
            {connection === "connected" ? "Live monitoring active" : "Waiting for live connection"}
          </span>
          <h2>{systemInfo?.hostname || "Your system"}, at a glance.</h2>
          <p>Current resource utilization from the latest monitoring snapshot.</p>
        </div>
        <div className="overview-meta">
          <div className="meta-item">
            <span>Collector</span>
            <strong className="capitalize">{monitoringStatus?.collector_status || snapshot.collection_status}</strong>
          </div>
          <div className="meta-divider" />
          <div className="meta-item">
            <span>CPU cores</span>
            <strong>{snapshot.cpu.physical_cores ?? "—"} physical · {snapshot.cpu.logical_cores ?? "—"} logical</strong>
          </div>
        </div>
      </div>

      <div className="resource-grid">
        <MetricCard
          title="Processor"
          icon={<Icon name="cpu" size={15} strokeWidth={2} />}
          metric="cpu"
          to="/cpu"
          history={history}
          value={formatPercent(snapshot.cpu.cpu_usage_percent)}
          description="CPU utilization"
        >
          <span>{snapshot.cpu.physical_cores ?? "—"} physical cores</span>
          <span>{formatFrequency(snapshot.cpu.frequency_mhz)}</span>
        </MetricCard>
        <MetricCard
          title="Memory"
          icon={<Icon name="memory" size={15} strokeWidth={2} />}
          metric="memory"
          to="/memory"
          history={history}
          value={formatPercent(snapshot.memory.usage_percent)}
          description={`${formatBytes(snapshot.memory.used_bytes)} of ${formatBytes(snapshot.memory.total_bytes)}`}
        >
          <span>{formatBytes(snapshot.memory.available_bytes)} available</span>
          <span>RAM</span>
        </MetricCard>
        <MetricCard
          title="Storage"
          icon={<Icon name="disk" size={15} strokeWidth={2} />}
          metric="disk"
          to="/disk"
          history={history}
          value={formatPercent(snapshotDisk)}
          description={`${formatBytes(totals.used)} used of ${formatBytes(totals.total)}`}
        >
          <span>{formatBytes(totals.free)} free</span>
          <span>{snapshot.disk.partitions.length} volumes</span>
        </MetricCard>
        <MetricCard
          title="Network"
          icon={<Icon name="network" size={15} strokeWidth={2} />}
          metric="download"
          unit="B/s"
          to="/network"
          history={history}
          value={formatRate(snapshot.network.download_speed_bytes_per_sec)}
          description="Download speed"
        >
          <span>↑ {formatRate(snapshot.network.upload_speed_bytes_per_sec)}</span>
          <span>Upload</span>
        </MetricCard>
      </div>

      <div className="dashboard-gpu-overview">
        <GpuOverview />
      </div>

      <div className="dashboard-cpu-alerts">
        <CpuAlerts />
      </div>

      <div className="dashboard-process-consumers">
        <TopResourceConsumers />
      </div>

      <div className="dashboard-lower-grid">
        <Panel
          title="Live activity"
          subtitle="Recent samples from the monitoring stream"
          action={<span className="live-tag"><span className="status-dot status-dot-live" />LIVE</span>}
        >
          <div className="activity-chart">
            <LiveChart
              data={history}
              metric="cpu"
              metrics={[
                { key: "cpu", label: "CPU", color: "#5577ec" },
                { key: "memory", label: "Memory", color: "#9b6bdf" },
              ]}
              showAxis
              height={220}
            />
          </div>
          <div className="activity-legend">
            <span><i className="legend-dot legend-cpu" />CPU</span>
            <span><i className="legend-dot legend-memory" />Memory</span>
            <span className="legend-caption">Values update as new snapshots arrive</span>
          </div>
        </Panel>
        <Panel
          title="At a glance"
          subtitle="Additional system measurements"
          action={<Link className="panel-link" to="/history">View history ↗</Link>}
        >
          <div className="quick-stats">
            <div className="quick-stat">
              <span className="quick-stat-icon quick-stat-green">↓</span>
              <div><span>Network received</span><strong>{formatBytes(snapshot.network.bytes_received)}</strong></div>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-icon quick-stat-blue">↑</span>
              <div><span>Network sent</span><strong>{formatBytes(snapshot.network.bytes_sent)}</strong></div>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-icon quick-stat-amber">↙</span>
              <div><span>Disk read</span><strong>{formatBytes(snapshot.disk.io.read_bytes)}</strong></div>
            </div>
            <div className="quick-stat">
              <span className="quick-stat-icon quick-stat-purple">↗</span>
              <div><span>Disk written</span><strong>{formatBytes(snapshot.disk.io.write_bytes)}</strong></div>
            </div>
          </div>
          <Link className="system-link" to="/system">
            <span><strong>{systemInfo?.operating_system || "System information"}</strong><small>View host and processor details</small></span>
            <span aria-hidden="true">→</span>
          </Link>
        </Panel>
      </div>
    </>
  );
}
