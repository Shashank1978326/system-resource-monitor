# System Resource Monitor

[![Tests](https://img.shields.io/badge/pytest-356%20passed-2b9c84?style=flat-square&logo=pytest)](https://github.com/Shashank1978326/system-resource-monitor)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19.0-61dafb?style=flat-square&logo=react)](https://react.dev)
[![Vite](https://img.shields.io/badge/Vite-6.4-646cff?style=flat-square&logo=vite)](https://vitejs.dev)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)
[![Author](https://img.shields.io/badge/Author-Shashank1978326-5577ec?style=flat-square&logo=github)](https://github.com/Shashank1978326)

A real-time, cross-platform diagnostic daemon, hardware analytics engine, and single-page dashboard designed for comprehensive system resource monitoring, statistical anomaly detection, predictive forecasting, automated PDF diagnostic reporting, and interactive portfolio presentation.

Developed as an academic **Operating Systems** engineering project and hardened for production workstation diagnostics.

---

## 🌟 Interactive Portfolio Showcase

In addition to the 13 live telemetry dashboard pages, this repository includes a dedicated, responsive **Portfolio Showcase Website**:
- **Showcase Route:** `/showcase`
- **Centralized Content:** Edit `frontend/src/data/portfolioData.js` to customize text, metrics, and cards without touching JSX.
- **Editing Guide:** Full instructions in [`EDITING_GUIDE.md`](./EDITING_GUIDE.md).

---

## 🚀 Key Features

1. **Multi-Core CPU Telemetry:** 1-second non-blocking sampling of per-core distribution, min/max/current frequencies, and processor topologies.
2. **Virtual Memory & Swap Paging:** Live RAM usage, page cache breakdown, available headroom, and swap memory saturation.
3. **Disk Space & Asynchronous I/O:** Per-partition storage allocation, read/write throughput speeds, and sector I/O counters.
4. **Network Socket & Bandwidth Analytics:** Live bidirectional upload/download transfer rates, interface traffic counters, and socket errors.
5. **Privacy-Hardened Process Inspector:** Searchable, sortable process table by PID, CPU, or RAM with environment variables and secrets stripped.
6. **Dedicated GPU Hardware Acceleration:** NVIDIA NVML hardware diagnostics (VRAM, clocks, temperature) with seamless integrated fallback.
7. **ACPI Thermal & Battery Monitoring:** Thermal zone sensors, package temperatures, AC line power status, and battery discharge rates.
8. **Multi-Resource Threshold Alerts:** Finite state machine tracking Normal, Warning, and Critical transitions with hysteresis anti-flapping.
9. **Historical Timeseries & Rollups:** B-tree indexed SQLite WAL queries (1h, 6h, 24h, 7d, 30d) executing in sub-2ms latency over 27,000+ snapshots.
10. **Statistical Anomaly Detection:** Rolling-window Welford z-score algorithm flagging unusual spikes exceeding $3.0\sigma$.
11. **Predictive Machine Learning:** Ordinary Least Squares (OLS) linear regression projecting resource trajectories over 5m, 10m, 15m, and 30m with continuous RMSE and MAE validation.
12. **Vector PDF Diagnostic Reports:** Automated ReportLab 4.x and Matplotlib PDF compilation across 6 specialized report types with automated blob cleanup.
13. **Full-Duplex WebSocket Streaming:** RFC 6455 1-second JSON telemetry broadcasts with DoS client connection ceilings.

---

## 🏗️ System Architecture

```
+-----------------------------------------------------------------------------------------+
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
                                      \                     /
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
+-----------------------------------------------------------------------------------------+
```

---

## 🔒 Security & Privacy Policy

This project strictly follows defensive engineering practices:
- **Zero Committed Secrets:** All credentials, API tokens, and local `.env` files are strictly excluded via `.gitignore`.
- **Protected Environment Templates:** Safe `backend/.env.example` and `frontend/.env.example` templates contain only non-confidential defaults.
- **Local Telemetry Isolation:** Historical databases (`history.sqlite3`) reside in the user's local application data directory (`%LOCALAPPDATA%`), completely outside the Git working tree.
- **Process Privacy Protection:** Process inspection routines strip command-line arguments and environment blocks to prevent credential leakage.
- Detailed security policies and vulnerability reporting procedures are documented in [`SECURITY.md`](./SECURITY.md).

---

## 🌐 Local Monitoring vs. Cloud Showcase Deployment

Understanding the deployment boundary is key for operating systems diagnostics:

| Feature / Capability | Local Workstation Execution | Cloud Hosting (Vercel / Netlify / Pages) |
| :--- | :--- | :--- |
| **Hardware Telemetry** (CPU, RAM, GPU, Fans) | **Full Access** (psutil & NVML query actual machine) | N/A (Serverless sandbox cannot read local PC) |
| **WebSocket Streaming** | **Live 1.0s Feed** (`ws://127.0.0.1:8000/ws`) | Disconnected / Mock Telemetry |
| **PDF Report Generation** | **Direct Download** via ReportLab 4.x | Available if backend deployed to container |
| **Showcase Website & Docs** | **Available** (`http://localhost:5173/showcase`) | **Ideal for Cloud** (Showcase portfolio for recruiters/professors) |

> [!TIP]
> To deploy the frontend as a public showcase website on **Vercel** or **Netlify**, set `VITE_LANDING_PAGE=showcase` in your build environment. The public URL will present the full showcase and documentation!

---

## 💻 Quickstart Guide

### Prerequisites
- Python 3.10+ (tested on Python 3.14)
- Node.js 18+ & npm
- Git

### 1. Clone & Configure Backend
```bash
git clone https://github.com/Shashank1978326/system-resource-monitor.git
cd system-resource-monitor/backend

# Create virtual environment
python -m venv .venv

# Activate environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
# On Linux / macOS: source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create local environment config
cp .env.example .env

# Launch FastAPI backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- REST API: `http://127.0.0.1:8000`
- Interactive Swagger Docs: `http://127.0.0.1:8000/docs`

### 2. Configure & Launch Frontend
```bash
cd ../frontend

# Install dependencies
npm install

# Start Vite dev server
npm run dev
```
- Open `http://localhost:5173` for the **Live Dashboard**.
- Open `http://localhost:5173/showcase` for the **Portfolio Showcase**.

---

## 🧪 Verification & Test Suites

The backend and frontend are tested for regressions and verified clean:

### Run Backend Tests (pytest)
```powershell
cd backend
pytest -q
```
*Current test suite status:* **356 passed, 0 failed, 0 skipped.**

### Run Frontend Production Build
```powershell
cd frontend
npm run build
```
*Status:* **0 errors, 0 warnings (Vite 6, bundle generated in ~3.2s).**

---

## 📚 Project Documentation

- [`FINAL_PROJECT_VERIFICATION_REPORT.md`](./FINAL_PROJECT_VERIFICATION_REPORT.md) — Exhaustive 14-section validation audit covering performance benchmarks, security guarantees, and multi-platform testing.
- [`DEVELOPMENT_GUIDE.md`](./DEVELOPMENT_GUIDE.md) — Architectural deep-dive, database schema reference, and step-by-step guides for adding, modifying, or removing features.
- [`SECURITY.md`](./SECURITY.md) — Secret management, environment variable policies, and vulnerability reporting.
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Team workflow, branching strategy, pull request rules, and commit message conventions.
- [`EDITING_GUIDE.md`](./EDITING_GUIDE.md) — Comprehensive guide for customizing website text, benchmarks, and technologies.

---

## 📄 License & Academic Integrity

This project is developed for academic purposes as an Operating Systems course project by **Shashank** ([@Shashank1978326](https://github.com/Shashank1978326)).  
Released under the [MIT License](LICENSE).
