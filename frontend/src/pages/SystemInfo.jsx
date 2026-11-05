import Panel from "../components/common/Panel";
import { EmptyState, ErrorBanner, Skeleton } from "../components/common/StateMessage";
import BatterySection from "../components/system/BatterySection";
import BatteryHistory from "../components/history/BatteryHistory";
import TemperatureSection from "../components/system/TemperatureSection";
import TemperatureHistory from "../components/history/TemperatureHistory";
import useMonitoring from "../hooks/useMonitoring";
import { formatDateTime } from "../utils/format";

const systemFields = [
  ["Operating system", "operating_system"],
  ["OS version", "os_version"],
  ["OS release", "os_release"],
  ["Hostname", "hostname"],
  ["Machine name", "machine_name"],
  ["CPU architecture", "cpu_architecture"],
  ["Application architecture", "architecture"],
  ["Processor", "processor"],
  ["Physical cores", "physical_cores"],
  ["Logical cores", "logical_cores"],
  ["Python version", "python_version"],
  ["Application platform", "application_platform"],
];

export default function SystemInfo() {
  const { systemInfo, systemInfoError, connectionError } = useMonitoring();
  return (
    <>
      <ErrorBanner message={connectionError} />
      {!systemInfo ? (
        systemInfoError || connectionError ? (
          <EmptyState title="System information unavailable" message={systemInfoError || connectionError} />
        ) : (
          <div className="system-info-grid">
            {[1, 2, 3].map((item) => <Skeleton className="info-skeleton" key={item} />)}
          </div>
        )
      ) : (
        <div className="system-info-grid">
          <Panel title="Host details" subtitle="Operating system and processor">
            <div className="info-grid">
              {systemFields.map(([label, key]) => (
                <div className="info-field" key={key}>
                  <span>{label}</span>
                  <strong>{systemInfo[key] ?? "Unavailable"}</strong>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="System uptime" subtitle="Time since the last system boot">
            <div className="uptime-card">
              <span className="uptime-symbol">◷</span>
              <strong>{systemInfo.uptime_readable || "Unavailable"}</strong>
              <span>Current uptime</span>
            </div>
            <div className="breakdown-row"><span>Boot time</span><strong>{formatDateTime(systemInfo.boot_time)}</strong></div>
            <div className="breakdown-row"><span>Uptime (seconds)</span><strong>{typeof systemInfo.uptime_seconds === "number" ? Math.floor(systemInfo.uptime_seconds).toLocaleString() : "Unavailable"}</strong></div>
          </Panel>
        </div>
      )}
      <BatterySection />
      <BatteryHistory />
      <TemperatureSection />
      <TemperatureHistory />
    </>
  );
}
