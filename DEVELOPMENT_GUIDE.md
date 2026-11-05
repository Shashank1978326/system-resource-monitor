# System Resource Monitor — Developer & Architecture Guide

This guide provides technical architectural documentation, design patterns, folder structures, and step-by-step procedures for extending, modifying, or removing features in the **System Resource Monitor** project without requiring complete application refactoring.

---

## 1. Project Architecture Overview

The system is organized into a modular three-tier architecture:

```
[ Host Operating System ] (psutil, platform, socket, OpenHardwareMonitor/ACPI, NVML)
            │
            ▼
[ Backend Core: FastAPI + SQLAlchemy 2.0 ]
  ├── Sampling Thread (MonitoringService: 1s cadence, latest snapshot lock)
  ├── Storage Engine (SQLite in WAL mode, automatic UTC datetime normalization)
  ├── Alert Engine (Finite state machine: Normal -> Warning -> Critical)
  ├── Statistical Anomaly Engine (Rolling window z-score: |z| >= 3.0)
  ├── Machine Learning Engine (Ordinary Least Squares regression: 5m, 10m, 15m, 30m)
  ├── PDF Diagnostic Engine (ReportLab 4.x + headless Matplotlib with thread lock)
  └── ASGI API Layer (Uvicorn + FastAPI with defensive headers & WebSocket broadcast)
            │
            ▼
[ Frontend Core: React 19 + Vite 6 ]
  ├── MonitoringContext (WebSocket subscription with reconnect & finite number validation)
  ├── ThemeContext (Dark & Light theme provider with WCAG 2.1 AA contrast compliance)
  ├── Recharts & Chart.js (Responsive high-performance timeseries visualizations)
  └── 13 Subsystem Pages + Dedicated Project Portfolio Showcase
```

---

## 2. Directory Structure

```
system-resource-monitor/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/             # REST API routers & WebSocket handler
│   │   │       ├── alerts.py       # Threshold configuration & alert history
│   │   │       ├── anomalies.py    # Anomaly settings, analytics, events
│   │   │       ├── cpu.py          # CPU utilization & frequency endpoints
│   │   │       ├── disk.py         # Disk partition & IO throughput endpoints
│   │   │       ├── gpu.py          # NVIDIA NVML GPU telemetry
│   │   │       ├── history.py      # Aggregated time-bucketed historical queries
│   │   │       ├── memory.py       # RAM & Swap allocation endpoints
│   │   │       ├── monitoring.py   # Raw collector snapshots & collector status
│   │   │       ├── network.py      # Network interfaces & bandwidth traffic
│   │   │       ├── predictions.py  # ML forecasts, accuracy metrics (MAE/RMSE)
│   │   │       ├── processes.py    # Non-sensitive process inspection
│   │   │       ├── reports.py      # Diagnostic PDF report generation
│   │   │       ├── system.py       # Host specs, uptime, health check
│   │   │       └── websocket.py    # Real-time WebSocket delivery
│   │   ├── core/
│   │   │   └── config.py           # Strongly typed environment configuration
│   │   ├── database/
│   │   │   ├── connection.py       # SQLite engine, WAL PRAGMAs, session factory
│   │   │   ├── models.py           # SQLAlchemy 2.0 declarative database models
│   │   │   ├── repository.py       # Timeseries metrics repository
│   │   │   ├── alert_repository.py # Alert events & current state repository
│   │   │   ├── anomaly_repository.py# Anomaly event logs repository
│   │   │   └── prediction_repository.py # ML forecast tracking repository
│   │   ├── schemas/
│   │   │   ├── monitoring.py       # Pydantic models for hardware & alerts
│   │   │   └── predictions.py      # Pydantic models for ML forecast analytics
│   │   ├── services/
│   │   │   ├── alert_service.py    # Alert state transition evaluator
│   │   │   ├── anomaly_service.py  # Rolling baseline z-score detector
│   │   │   ├── battery_service.py  # Cross-platform battery & power sampler
│   │   │   ├── cpu_service.py      # Non-blocking CPU sampler
│   │   │   ├── disk_service.py     # Partition & IO delta sampler
│   │   │   ├── gpu_service.py      # NVML GPU sampler
│   │   │   ├── history_service.py  # Historical retention & aggregation
│   │   │   ├── memory_service.py   # Virtual memory & swap sampler
│   │   │   ├── monitoring_service.py # Background collector daemon thread
│   │   │   ├── network_service.py  # Network rate & packet delta sampler
│   │   │   ├── prediction_service.py # OLS trend regression engine
│   │   │   ├── process_service.py  # Filtered safe process enumeration
│   │   │   ├── report_service.py   # ReportLab PDF compiler
│   │   │   ├── system_service.py   # OS architecture & uptime inspection
│   │   │   └── temperature_service.py # Thermal sensor sampler
│   │   └── main.py                 # FastAPI application factory & middleware
│   ├── tests/                      # 356 automated pytest test cases
│   ├── requirements.txt            # Python dependencies
│   ├── .env.example                # Safe environment template
│   └── README.md                   # Backend documentation
├── frontend/
│   ├── src/
│   │   ├── components/             # Reusable modular UI controls
│   │   │   ├── anomalies/          # Anomaly charts & analytics tables
│   │   │   ├── charts/             # Reusable LiveChart components
│   │   │   ├── common/             # Panel, StateMessage, Badge
│   │   │   ├── dashboard/          # MetricCard, CpuAlerts, TopConsumers
│   │   │   ├── disk/               # Disk speed gauges
│   │   │   ├── history/            # Historical timeseries graph controls
│   │   │   ├── layout/             # AppLayout, Sidebar, Topbar, Icons
│   │   │   ├── network/            # Interface bandwidth tables
│   │   │   ├── portfolio/          # Professional portfolio showcase components
│   │   │   ├── predictions/        # ML accuracy and forecast charts
│   │   │   └── system/             # BatterySection, TemperatureSection
│   │   ├── context/
│   │   │   ├── MonitoringContext.jsx # Live telemetry state & WebSocket client
│   │   │   └── ThemeContext.jsx    # Dark/Light theme state
│   │   ├── data/
│   │   │   └── portfolioData.js    # Centralized portfolio website content
│   │   ├── pages/                  # 13 Subsystem Pages + Portfolio Showcase
│   │   ├── services/
│   │   │   └── api.js              # Centralized Axios HTTP client
│   │   ├── utils/
│   │   │   └── format.js           # Byte formatting, rates, time utilities
│   │   ├── App.jsx                 # Client router configuration
│   │   ├── index.css               # Design tokens & responsive styles
│   │   └── main.jsx                # React root mount
│   ├── package.json                # React 19 dependencies & scripts
│   ├── vite.config.js              # Production build bundler configuration
│   └── .env.example                # Frontend environment template
├── .gitignore                      # Git exclusion rules
├── SECURITY.md                     # Security & private file policies
├── CONTRIBUTING.md                 # Team contribution guidelines
├── DEVELOPMENT_GUIDE.md            # This guide
├── EDITING_GUIDE.md                # Portfolio editing guide
├── FINAL_PROJECT_VERIFICATION_REPORT.md # 14-section audit verification
└── README.md                       # Root documentation
```

---

## 3. Database Schema & Models

All database tables are defined using SQLAlchemy 2.0 in `backend/app/database/models.py`:

| Table Name | Model Class | Description | Key Indexes |
|---|---|---|---|
| `historical_metrics` | `HistoricalMetrics` | Timeseries hardware metrics (CPU, RAM, Disk, Net, Battery, Temp) | `timestamp` |
| `network_interface_metrics` | `HistoricalNetworkInterfaceMetrics` | Per-interface upload/download speeds | `historical_metric_id`, `interface_name` |
| `temperature_sensor_metrics` | `HistoricalTemperatureSensorMetrics` | Per-sensor temperature records | `historical_metric_id`, `sensor_id` |
| `alert_events` | `AlertEvent` | Immutable threshold breach transition log | `timestamp`, `resource`, `severity` |
| `alert_current_states` | `AlertCurrentState` | Latest alert severity per resource/device | Primary key (`resource`, `device_or_sensor`) |
| `alert_thresholds` | `AlertThreshold` | User-configured warning/critical threshold overrides | `resource` |
| `anomaly_events` | `AnomalyEvent` | Statistical anomaly event records ($Z \ge 3.0$) | `timestamp`, `resource`, `severity` |
| `anomaly_settings` | `AnomalySettings` | Runtime anomaly sensitivity configuration | `id` |
| `historical_predictions` | `HistoricalPrediction` | ML predictions with evaluated vs actual measurements | `timestamp`, `target_timestamp` |

---

## 4. How to Add a New Monitoring Feature

To add a new hardware or telemetry feature (e.g., Fan Speed Monitoring):

1. **Service Sampler:**
   - Create `backend/app/services/fan_service.py`.
   - Implement a safe sampler function `get_fan_info() -> FanResponse` returning current RPM or `None` on failure.
2. **Schema Definition:**
   - In `backend/app/schemas/monitoring.py`, define `FanResponse(BaseModel)`.
3. **Database Model (if persisted):**
   - In `backend/app/database/models.py`, add `fan_speed_rpm = Column(Float, nullable=True)` to `HistoricalMetrics`.
4. **Collector Registration:**
   - In `backend/app/services/monitoring_service.py`, invoke `get_fan_info()` in `_sample_all()` and include it in `MonitoringSnapshotResponse`.
5. **API Route:**
   - In `backend/app/api/routes/fan.py`, create a GET endpoint `/api/fan`.
   - Register the router in `backend/app/main.py`: `app.include_router(fan_router)`.
6. **Frontend API & Component:**
   - In `frontend/src/services/api.js`, export `getFanInfo()`.
   - Create `frontend/src/pages/Fan.jsx` or a sub-panel in `SystemInfo.jsx`.
   - Register route in `frontend/src/App.jsx` and add to `Sidebar.jsx`.
7. **Automated Tests:**
   - Create `backend/tests/test_fan.py` to verify responses and error resilience.

---

## 5. How to Modify Existing Algorithms

### Modifying Anomaly Detection Z-Score Logic
* **File:** `backend/app/services/anomaly_service.py`
* **Function:** `process_metric_sample(resource, metric, val, timestamp)`
* The z-score threshold is configured via `self.z_score_threshold` (default `3.0`).
* Standard deviation floor is set by `effective_stdev = max(stdev, min_stdev)`.
* Adjust window length via `ANOMALY_WINDOW_SIZE` or `/api/anomalies/settings`.

### Modifying Resource Prediction Regression Logic
* **File:** `backend/app/services/prediction_service.py`
* **Function:** `_fit_linear_regression(samples)`
* Uses Ordinary Least Squares (OLS) regression over recent history.
* Prediction horizons are governed by `SUPPORTED_HORIZONS` (`5m`, `10m`, `15m`, `30m`).

---

## 6. How to Run Verification Tests

Always execute backend tests and frontend production builds before committing:

```bash
# Backend pytest suite (356 tests)
cd backend
python -m pytest -q

# Frontend production build
cd ../frontend
npm run build
```

