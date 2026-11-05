import { useState } from "react";
import HistoricalChart from "./HistoricalChart";
import Panel from "../common/Panel";
import { intervals, isOverLimit, ranges } from "./historyOptions";

const diskThroughputGroups = [
  {
    title: "Disk Read Throughput History",
    unit: "disk_rate",
    series: [{ metric: "disk_read_speed", label: "Read", color: "#2b9c84" }],
  },
  {
    title: "Disk Write Throughput History",
    unit: "disk_rate",
    series: [{ metric: "disk_write_speed", label: "Write", color: "#9b6bdf" }],
  },
];

export default function DiskIoHistory() {
  const [range, setRange] = useState("1h");
  const [selectedInterval, setSelectedInterval] = useState("1m");
  const interval = isOverLimit(range, selectedInterval) ? "5m" : selectedInterval;

  return (
    <section className="disk-history-section">
      <div className="history-filters disk-history-filters">
        <label>
          <span>Throughput time range</span>
          <select value={range} onChange={(event) => setRange(event.target.value)}>
            {ranges.map(([value, label]) => (
              <option value={value} key={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Aggregation interval</span>
          <select
            value={interval}
            onChange={(event) => setSelectedInterval(event.target.value)}
          >
            {intervals.map(([value, label]) => (
              <option value={value} key={value} disabled={isOverLimit(range, value)}>
                {label}{isOverLimit(range, value) ? " — exceeds point limit" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="history-chart-grid">
        {diskThroughputGroups.map((group) => (
          <HistoricalChart
            key={group.title}
            group={group}
            range={range}
            interval={interval}
          />
        ))}
      </div>
    </section>
  );
}
