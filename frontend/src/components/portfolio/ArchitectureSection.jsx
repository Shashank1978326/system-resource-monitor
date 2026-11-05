import { portfolioData } from "../../data/portfolioData";

export default function ArchitectureSection() {
  const { architecture } = portfolioData;

  return (
    <section className="portfolio-section" id="architecture">
      <div className="portfolio-section-header">
        <span className="section-eyebrow">System Design & Engineering</span>
        <h2 className="section-title">{architecture.heading}</h2>
        <p className="section-subtitle">{architecture.subheading}</p>
      </div>

      <div className="architecture-diagram-panel">
        <div className="diagram-header">
          <span className="diagram-dot dot-red" />
          <span className="diagram-dot dot-yellow" />
          <span className="diagram-dot dot-green" />
          <span className="diagram-title">System Pipeline Flowchart</span>
        </div>
        <pre className="architecture-ascii" aria-label="Architecture Diagram">
{`+-----------------------------------------------------------------------------------------+
|                                1. HARDWARE & KERNEL LAYER                               |
|   psutil (CPU, RAM, Disk, Net, Temp)  <--->  NVML (GPU VRAM, Clocks)  <--->  ACPI Battery   |
+-----------------------------------------------------------------------------------------+
                                             |  (1.0s non-blocking interval)
                                             v
+-----------------------------------------------------------------------------------------+
|                               2. BACKGROUND TELEMETRY DAEMON                            |
|   asyncio Loop  --->  In-Memory Ring Buffer (120 snapshots)  --->  Thread-safe Locking  |
+-----------------------------------------------------------------------------------------+
                                      |                     |
                                      v                     v
+--------------------------------------------+    +---------------------------------------+
|        3. TIMESERIES PERSISTENCE           |    |     4. ANALYTICS & INFERENCE ENGINE   |
|   SQLite 3 with Write-Ahead Logging (WAL)  |    |   • Welford Online Z-Score Anomalies  |
|   B-Tree Indexed Timestamps                |    |   • Linear Regression Forecaster      |
|   Sub-2ms rollups (1h, 6h, 24h, 7d, 30d)   |    |   • Hysteresis State Machine Alerts   |
+--------------------------------------------+    +---------------------------------------+
                                      \\                     /
                                       v                   v
+-----------------------------------------------------------------------------------------+
|                                5. FASTAPI REST & WEBSOCKET GATEWAY                      |
|   ASGI Server (Uvicorn)  |  Starlette RFC-6455 WebSockets  |  ReportLab PDF Engine      |
|   Defensive Security Headers  |  Pydantic v2 Schema Validation  |  Path Traversal Block |
+-----------------------------------------------------------------------------------------+
                                             |  (Full-duplex WebSocket JSON broadcast)
                                             v
+-----------------------------------------------------------------------------------------+
|                                6. REACT 19 SPA PRESENTATION                             |
|   React 19 + Vite 6  |  Canvas Chart.js & Recharts  |  WCAG 2.1 AA Dark/Light Themes    |
|   13 Dedicated Diagnostic Views  |  Blob URL Safe Cleanup  |  Responsive Flex/Grid UI   |
+-----------------------------------------------------------------------------------------+`}
        </pre>
      </div>

      <div className="architecture-layers-grid">
        {architecture.layers.map((layer, idx) => (
          <div key={idx} className="architecture-layer-card">
            <div className="layer-card-top">
              <span className="layer-badge">{layer.badge}</span>
              <h3 className="layer-title">{layer.title}</h3>
            </div>
            <p className="layer-desc">{layer.desc}</p>
            <div className="layer-tech-tags">
              {layer.tech.map((t, i) => (
                <span key={i} className="layer-tech-tag">{t}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

