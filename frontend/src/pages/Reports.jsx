import { useEffect, useRef, useState } from "react";
import Panel from "../components/common/Panel";
import Icon from "../components/layout/Icons";
import { downloadPdfReport, errorMessage } from "../services/api";

const PERIOD_OPTIONS = [
  { value: "1h", label: "Last 1 hour", description: "Immediate recent performance" },
  { value: "6h", label: "Last 6 hours", description: "Short-term operational shift" },
  { value: "24h", label: "Last 24 hours", description: "Daily baseline & trends (Default)" },
  { value: "7d", label: "Last 7 days", description: "Weekly cyclical workload patterns" },
  { value: "30d", label: "Last 30 days", description: "Long-term capacity & drift" },
];

const REPORT_TYPES = [
  {
    id: "all",
    title: "Complete System Report",
    badge: "Full Audit",
    description:
      "Comprehensive diagnostic audit covering all 13 subsystems, including executive summary, hardware, processes, ML forecasts, anomalies, and 10 embedded visual charts.",
    sections: [
      "Executive Summary & Health Status",
      "System & Kernel Architecture",
      "CPU & Memory Telemetry",
      "Storage Partitions & I/O Rates",
      "Network Interfaces & Throughput",
      "Top CPU & Memory Processes (Secure)",
      "Threshold Alerts & History",
      "GPU, Battery & Temperature Telemetry",
      "Statistical Z-Score Anomaly Engine",
      "ML Utilization Forecasts & Horizons",
      "Forecast Accuracy & Validation (MAE/RMSE)",
    ],
    charts: [
      "CPU Utilization Over Time",
      "Memory Utilization Over Time",
      "Disk Capacity Trend",
      "Disk I/O Throughput",
      "Network Traffic Speeds",
      "Alert Severity Distribution",
      "Anomaly Frequency Timeline",
      "Resource Anomaly Distribution",
      "Measured vs Forecasted Values",
      "Prediction Error by Horizon",
    ],
  },
  {
    id: "cpu_memory",
    title: "CPU and Memory Report",
    badge: "Compute & RAM",
    description:
      "Targeted analysis focusing on processor core utilization, RAM allocation patterns, paging overhead, top consuming processes, and compute-bound forecasts.",
    sections: [
      "Executive Compute Summary",
      "System Processor Architecture",
      "CPU Utilization & Core Samples",
      "Physical RAM & Swap Allocations",
      "Top Workload Processes",
      "Compute Alert & Anomaly History",
      "CPU & Memory Machine Learning Predictions",
    ],
    charts: [
      "CPU Utilization Over Time",
      "Memory Utilization Over Time",
      "Measured vs Forecasted Utilization",
    ],
  },
  {
    id: "disk_network",
    title: "Disk and Network Report",
    badge: "I/O & Network",
    description:
      "Storage and network audit examining partition capacities, read/write I/O throughput rates, network interface bandwidth, and I/O bottlenecks.",
    sections: [
      "Executive Storage & I/O Summary",
      "Mountpoints & Filesystem Capacities",
      "Storage Read / Write Speeds",
      "Network Interface Activity & Volume",
      "I/O Alerts & Traffic Anomalies",
      "Storage & Network Demand Predictions",
    ],
    charts: [
      "Disk Storage Capacity Trend",
      "Disk I/O Throughput (Read / Write)",
      "Network Interface Throughput",
    ],
  },
  {
    id: "process_resource",
    title: "Process and Resource Report",
    badge: "Workload Inventory",
    description:
      "Detailed process inventory highlighting top CPU and memory consumers, PID mappings, memory footprints, and resource impact without exposing secrets.",
    sections: [
      "Executive Workload Overview",
      "System Host Information",
      "Top 10 CPU Consuming Workloads",
      "Top 10 Memory Consuming Workloads",
      "Process Execution States & Threads",
      "Workload Overhead vs System Capacity",
    ],
    charts: [
      "CPU Utilization Over Time",
      "Memory Utilization Over Time",
    ],
  },
  {
    id: "alerts_anomaly",
    title: "Alerts and Anomaly Report",
    badge: "Stability & Incidents",
    description:
      "Reliability assessment covering configured threshold breaches, warning and critical alerts, statistical Z-score anomalies, and incident frequency over time.",
    sections: [
      "Executive Reliability Assessment",
      "Active Alert Threshold Settings",
      "Chronological Alert Incident Log",
      "Statistical Z-Score Anomaly Analysis",
      "Resource Incident Distribution",
      "Mitigation Recommendations",
    ],
    charts: [
      "Alert Severity Distribution",
      "Statistical Anomaly Frequency Timeline",
      "Anomaly Events by Resource",
    ],
  },
  {
    id: "prediction_accuracy",
    title: "Prediction and Accuracy Report",
    badge: "ML Analytics",
    description:
      "Machine learning forecast evaluation reporting future resource predictions, regression trend models, confidence scores, and historical accuracy (MAE, RMSE, MAPE).",
    sections: [
      "Executive Forecasting Overview",
      "Current Multi-Horizon Predictions (5m to 30m)",
      "Regression Confidence & Trend Slopes",
      "Accuracy Validation by Horizon",
      "Evaluation Pipeline Status (Evaluated vs Pending)",
      "Error Residual Breakdown",
    ],
    charts: [
      "Measured vs Forecasted Resource Utilization",
      "Prediction Error by Horizon (MAE & RMSE)",
    ],
  },
];

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let val = bytes;
  for (const u of units) {
    if (val < 1024 || u === "GB") return `${val.toFixed(1)} ${u}`;
    val /= 1024;
  }
  return `${val.toFixed(1)} TB`;
}

export default function Reports() {
  const [selectedPeriod, setSelectedPeriod] = useState("24h");
  const [selectedType, setSelectedType] = useState("all");
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [error, setError] = useState(null);
  const [lastGenerated, setLastGenerated] = useState(null);
  const [sessionReports, setSessionReports] = useState([]);
  const sessionReportsRef = useRef(sessionReports);
  sessionReportsRef.current = sessionReports;

  useEffect(() => {
    return () => {
      sessionReportsRef.current.forEach((item) => {
        if (item?.blobUrl) {
          window.URL.revokeObjectURL(item.blobUrl);
        }
      });
    };
  }, []);

  const currentTypeMeta =
    REPORT_TYPES.find((t) => t.id === selectedType) || REPORT_TYPES[0];

  const handleGenerateReport = async () => {
    setLoading(true);
    setError(null);
    setStatusMessage("Connecting to telemetry database...");

    const statusTimer1 = setTimeout(() => {
      setStatusMessage("Aggregating historical telemetry & computing statistics...");
    }, 600);

    const statusTimer2 = setTimeout(() => {
      setStatusMessage("Rendering high-resolution analytics charts with Matplotlib...");
    }, 1400);

    const statusTimer3 = setTimeout(() => {
      setStatusMessage("Compiling publication-ready PDF document with ReportLab...");
    }, 2400);

    try {
      const response = await downloadPdfReport({
        range: selectedPeriod,
        type: selectedType,
      });

      clearTimeout(statusTimer1);
      clearTimeout(statusTimer2);
      clearTimeout(statusTimer3);

      // Extract filename from response headers
      const disposition = response.headers["content-disposition"] || "";
      let filename = `system_resource_report_${selectedPeriod}_${selectedType}.pdf`;
      const match = disposition.match(/filename=["']?([^"';]+)["']?/i);
      if (match && match[1]) {
        filename = match[1];
      }

      const blob = new Blob([response.data], { type: "application/pdf" });
      const downloadUrl = window.URL.createObjectURL(blob);

      // Trigger automatic browser download
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      const generatedInfo = {
        id: Date.now(),
        filename,
        type: selectedType,
        typeTitle: currentTypeMeta.title,
        period: selectedPeriod,
        periodLabel:
          PERIOD_OPTIONS.find((p) => p.value === selectedPeriod)?.label ||
          selectedPeriod,
        timestamp: new Date().toLocaleTimeString(),
        fullDate: new Date().toLocaleString(),
        size: response.data.size || blob.size,
        blobUrl: downloadUrl,
      };

      setLastGenerated(generatedInfo);
      setSessionReports((prev) => {
        const evicted = prev.slice(9);
        evicted.forEach((item) => {
          if (item?.blobUrl) {
            window.URL.revokeObjectURL(item.blobUrl);
          }
        });
        return [generatedInfo, ...prev.slice(0, 9)];
      });
      setStatusMessage("");
    } catch (err) {
      clearTimeout(statusTimer1);
      clearTimeout(statusTimer2);
      clearTimeout(statusTimer3);
      setError(errorMessage(err));
      setStatusMessage("");
    } finally {
      setLoading(false);
    }
  };

  const handleRedownload = (item) => {
    if (!item.blobUrl) return;
    const link = document.createElement("a");
    link.href = item.blobUrl;
    link.download = item.filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const handleKeyDownSelect = (e, callback) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      callback();
    }
  };

  return (
    <div className="reports-page-container">
      {/* Page Header */}
      <div className="reports-header">
        <h1 className="reports-title">
          System Diagnostic & Performance Reports
        </h1>
        <p className="reports-subtitle">
          Generate, customize, and export audit-ready PDF reports with historical
          telemetry, visual analytics charts, and machine learning predictions.
        </p>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="report-alert report-alert-error" role="alert">
          <div className="report-alert-content">
            <span className="report-error-icon">✕</span>
            <span className="report-error-message">{error}</span>
          </div>
          <button
            type="button"
            className="report-btn-retry"
            onClick={handleGenerateReport}
            disabled={loading}
          >
            Retry Generation
          </button>
        </div>
      )}

      {/* Success Notification Banner */}
      {lastGenerated && !loading && (
        <div className="report-alert report-alert-success" role="status">
          <div className="report-alert-content">
            <div className="report-alert-icon">
              <Icon name="check" size={18} strokeWidth={2.5} />
            </div>
            <div>
              <div className="report-alert-title">
                PDF Report Successfully Generated & Downloaded
              </div>
              <div className="report-alert-meta">
                <strong>{lastGenerated.filename}</strong> &nbsp;•&nbsp;{" "}
                {formatBytes(lastGenerated.size)} &nbsp;•&nbsp; Generated at{" "}
                {lastGenerated.timestamp}
              </div>
            </div>
          </div>
          <button
            type="button"
            className="report-btn-redownload"
            onClick={() => handleRedownload(lastGenerated)}
          >
            <Icon name="download" size={15} />
            Download PDF Again
          </button>
        </div>
      )}

      {/* Main Configuration Grid */}
      <div className="reports-config-grid">
        {/* Step 1: Reporting Period Card */}
        <Panel title="1. Select Reporting Window">
          <p className="reports-section-hint">
            Choose the time interval of historical measurements to aggregate and
            graph in the report:
          </p>
          <div className="report-selection-list">
            {PERIOD_OPTIONS.map((period) => {
              const isSelected = selectedPeriod === period.value;
              return (
                <button
                  type="button"
                  key={period.value}
                  className={`report-select-tile ${isSelected ? "selected" : ""}`}
                  onClick={() => setSelectedPeriod(period.value)}
                  onKeyDown={(e) =>
                    handleKeyDownSelect(e, () => setSelectedPeriod(period.value))
                  }
                  role="button"
                  aria-pressed={isSelected}
                  tabIndex={0}
                >
                  <div>
                    <div className="report-tile-label">{period.label}</div>
                    <div className="report-tile-desc">{period.description}</div>
                  </div>
                  <input
                    type="radio"
                    name="report_period"
                    checked={isSelected}
                    onChange={() => setSelectedPeriod(period.value)}
                    tabIndex={-1}
                    aria-hidden="true"
                    style={{ cursor: "pointer" }}
                  />
                </button>
              );
            })}
          </div>
        </Panel>

        {/* Step 2: Report Type Card */}
        <Panel title="2. Select Report Scope & Type">
          <p className="reports-section-hint">
            Choose the diagnostic domain or export a complete infrastructure
            audit:
          </p>
          <div className="report-selection-list report-selection-scroll">
            {REPORT_TYPES.map((type) => {
              const isSelected = selectedType === type.id;
              return (
                <button
                  type="button"
                  key={type.id}
                  className={`report-select-tile ${isSelected ? "selected" : ""}`}
                  onClick={() => setSelectedType(type.id)}
                  onKeyDown={(e) =>
                    handleKeyDownSelect(e, () => setSelectedType(type.id))
                  }
                  role="button"
                  aria-pressed={isSelected}
                  tabIndex={0}
                >
                  <div style={{ width: "100%" }}>
                    <div className="report-type-header">
                      <span className="report-tile-label">{type.title}</span>
                      <span className="report-badge">{type.badge}</span>
                    </div>
                    <div className="report-tile-desc">{type.description}</div>
                  </div>
                </button>
              );
            })}
          </div>
        </Panel>
      </div>

      {/* Step 3: Report Preview & Generation Action */}
      <Panel title="3. Content Preview & Generation Execution">
        <div className="report-preview-grid">
          {/* Included Sections Preview */}
          <div>
            <div className="report-preview-label">
              Included Diagnostic Sections ({currentTypeMeta.sections.length})
            </div>
            <ul className="report-preview-items">
              {currentTypeMeta.sections.map((sec, idx) => (
                <li key={idx}>{sec}</li>
              ))}
            </ul>
          </div>

          {/* Included Visual Graphs Preview */}
          <div>
            <div className="report-preview-label">
              Embedded Visual Charts ({currentTypeMeta.charts.length})
            </div>
            <div className="report-chart-tags">
              {currentTypeMeta.charts.map((ch, idx) => (
                <span key={idx} className="report-chart-pill">
                  📊 {ch}
                </span>
              ))}
            </div>

            <div className="report-info-callout">
              ℹ️ <strong>Publication Grade:</strong> Vector typography with
              ReportLab, two-pass dynamic page numbering, confidentiality
              footers, and in-memory chart generation.
            </div>
          </div>
        </div>

        {/* Generate Button & Progress State */}
        <div className="report-action-row">
          <div>
            {loading ? (
              <div className="report-status-spinner">
                <div className="report-spinner-circle" />
                <span>{statusMessage || "Generating PDF report..."}</span>
              </div>
            ) : (
              <span className="report-target-summary">
                Targeting: <strong>{currentTypeMeta.title}</strong> over{" "}
                <strong>
                  {PERIOD_OPTIONS.find((p) => p.value === selectedPeriod)?.label}
                </strong>
              </span>
            )}
          </div>

          <button
            type="button"
            className="report-generate-button"
            onClick={handleGenerateReport}
            disabled={loading}
          >
            <Icon name="reports" size={17} />
            {loading ? "Generating Report..." : "Generate PDF Report"}
          </button>
        </div>
      </Panel>

      {/* Session Reports History */}
      {sessionReports.length > 0 && (
        <div style={{ marginTop: "24px" }}>
          <Panel title="Recent Generated Reports (Current Session)">
            <div style={{ overflowX: "auto" }}>
              <table className="report-history-table">
                <thead>
                  <tr>
                    <th>Report Filename</th>
                    <th>Scope</th>
                    <th>Window</th>
                    <th>Generated</th>
                    <th>Size</th>
                    <th style={{ textAlign: "right" }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sessionReports.map((item) => (
                    <tr key={item.id}>
                      <td style={{ fontWeight: "600" }}>📄 {item.filename}</td>
                      <td>{item.typeTitle}</td>
                      <td>{item.periodLabel}</td>
                      <td className="report-table-meta">{item.timestamp}</td>
                      <td className="report-table-meta">
                        {formatBytes(item.size)}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="report-download-btn"
                          onClick={() => handleRedownload(item)}
                        >
                          <Icon name="download" size={13} />
                          Download
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
