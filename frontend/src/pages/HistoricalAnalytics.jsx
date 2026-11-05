import { useState } from "react";
import HistoricalChart from "../components/history/HistoricalChart";
import BatteryHistory from "../components/history/BatteryHistory";
import NetworkInterfaceHistory from "../components/history/NetworkInterfaceHistory";
import TemperatureHistory from "../components/history/TemperatureHistory";
import { intervals, isOverLimit, ranges } from "../components/history/historyOptions";

const chartGroups = [
  { title: "CPU utilization", unit: "percent", series: [{ metric: "cpu", label: "CPU", color: "#5577ec" }] },
  { title: "Memory utilization", unit: "percent", series: [{ metric: "memory", label: "Memory", color: "#9b6bdf" }] },
  { title: "Disk utilization", unit: "percent", series: [{ metric: "disk", label: "Disk", color: "#e1a344" }] },
  { title: "Network download", unit: "rate", series: [{ metric: "network_download", label: "Download", color: "#2b9c84" }] },
  { title: "Network upload", unit: "rate", series: [{ metric: "network_upload", label: "Upload", color: "#5478e8" }] },
  {
    title: "Disk I/O counters (cumulative)",
    unit: "bytes",
    series: [
      { metric: "disk_read", label: "Read", color: "#2b9c84" },
      { metric: "disk_write", label: "Write", color: "#e1a344" },
    ],
  },
  {
    title: "Disk Read Throughput",
    unit: "disk_rate",
    series: [{ metric: "disk_read_speed", label: "Read", color: "#2b9c84" }],
  },
  {
    title: "Disk Write Throughput",
    unit: "disk_rate",
    series: [{ metric: "disk_write_speed", label: "Write", color: "#9b6bdf" }],
  },
];

export default function HistoricalAnalytics() {
  const [range, setRange] = useState("1h");
  const [selectedInterval, setInterval] = useState("1m");
  const interval = isOverLimit(range, selectedInterval) ? "5m" : selectedInterval;

  return (
    <>
      <div className="history-intro">
        <div>
          <h2>Understand resource trends over time.</h2>
          <p>Historical averages are grouped into UTC-aligned buckets from recorded monitoring samples.</p>
        </div>
        <div className="history-filters">
          <label>
            <span>Time range</span>
            <select value={range} onChange={(event) => setRange(event.target.value)}>
              {ranges.map(([value, label]) => (
                <option value={value} key={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Aggregation interval</span>
            <select value={interval} onChange={(event) => setInterval(event.target.value)}>
              {intervals.map(([value, label]) => (
                <option value={value} key={value} disabled={isOverLimit(range, value)}>
                  {label}{isOverLimit(range, value) ? " — exceeds point limit" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="history-chart-grid">
        {chartGroups.map((group) => (
          <HistoricalChart
            key={group.title}
            group={group}
            range={range}
            interval={interval}
          />
        ))}
      </div>
      <NetworkInterfaceHistory range={range} interval={interval} />
      <BatteryHistory range={range} interval={interval} />
      <TemperatureHistory range={range} interval={interval} />
    </>
  );
}
