/**
 * ==============================================================================
 * System Resource Monitor - Centralized Portfolio Content Configuration
 * ==============================================================================
 * This file contains all text, feature cards, architecture highlights, tech stack
 * details, links, and benchmarks showcased on the Project Portfolio website.
 *
 * To edit the portfolio website without touching JSX code, update values here!
 * Refer to EDITING_GUIDE.md for complete instructions.
 */

export const portfolioData = {
  meta: {
    title: "System Resource Monitor",
    subtitle: "A Real-Time Operating System Resource Monitoring and Analytics Platform",
    tagline: "Academic Operating Systems Project & Production-Grade Workstation Diagnostic Suite",
    author: "Shashank",
    githubUsername: "Shashank1978326",
    githubRepoUrl: "https://github.com/Shashank1978326/system-resource-monitor",
    githubProfileUrl: "https://github.com/Shashank1978326",
    liveDashboardPath: "/dashboard",
    docsAnchor: "#documentation",
  },

  hero: {
    badge: "100% Tested & Verified • 356 Automated Tests Passed",
    headline: "Real-Time Hardware Telemetry, Statistical Anomaly Detection & ML Forecasting",
    description:
      "A complete full-stack diagnostic platform engineered to capture genuine system telemetry, store indexed timeseries in SQLite WAL mode, compute statistical deviations with z-score analysis, project future resource usage via linear regression, and compile boardroom-grade PDF diagnostic reports.",
    primaryCta: { label: "Explore Live Dashboard", path: "/dashboard" },
    secondaryCta: { label: "View on GitHub", url: "https://github.com/Shashank1978326/system-resource-monitor" },
    tertiaryCta: { label: "System Architecture", anchor: "#architecture" },
  },

  about: {
    heading: "About the Project",
    subheading: "Bridging Operating Systems Theory with Modern Full-Stack Diagnostics",
    purpose:
      "Developed as an advanced Operating Systems engineering project, the System Resource Monitor provides deep hardware visibility into multi-core CPU dynamics, virtual memory pages, disk IO throughput, network sockets, thermal boundaries, and process scheduling.",
    problemStatement:
      "Standard system task managers provide ephemeral, fleeting snapshots without long-term timeseries persistence, statistical anomaly classification, predictive trend extrapolation, or automated diagnostic report generation. This project addresses these limitations with an integrated telemetry daemon, SQLite timeseries storage, and a responsive React single-page interface.",
    osConcepts: [
      {
        title: "Process Scheduling & Isolation",
        desc: "Safe on-demand process sampling inspecting PIDs, thread counts, and memory allocations without disclosing sensitive user credentials or environment variables.",
      },
      {
        title: "Virtual Memory & Swap Pages",
        desc: "Monitoring resident set size (RSS), active cache, free pages, and virtual memory pagefile saturation.",
      },
      {
        title: "Asynchronous IO & Storage",
        desc: "Computing read/write transfer rates across physical disk sectors and filesystem mountpoints.",
      },
      {
        title: "Concurrency & Mutex Locks",
        desc: "Decoupled sampling threads, atomic in-memory snapshot exchanges, and thread-safe ReportLab/Matplotlib figure rendering.",
      },
      {
        title: "ACPI & Thermal Boundaries",
        desc: "Sampling ACPI thermal sensors, CPU core temperatures, and battery state transitions.",
      },
      {
        title: "Network Socket IO",
        desc: "Measuring per-interface bidirectional bandwidth, packet deltas, and network error counters.",
      },
    ],
  },

  technologies: [
    {
      category: "Backend Engine",
      items: [
        { name: "Python 3.14", desc: "Core language & native typing" },
        { name: "FastAPI", desc: "High-performance ASGI framework" },
        { name: "Uvicorn", desc: "Lightning-fast ASGI web server" },
        { name: "psutil 7.2", desc: "Cross-platform hardware samplers" },
        { name: "SQLAlchemy 2.0", desc: "ORM & type-safe query compiler" },
        { name: "ReportLab 4.x", desc: "Vector PDF document engine" },
        { name: "Matplotlib 3.10", desc: "Headless Agg visualization engine" },
        { name: "NVIDIA NVML", desc: "GPU hardware inspection" },
      ],
    },
    {
      category: "Frontend Application",
      items: [
        { name: "React 19", desc: "Modern concurrent UI library" },
        { name: "Vite 6", desc: "Ultra-fast frontend build tooling" },
        { name: "React Router DOM 7", desc: "Client-side routing engine" },
        { name: "Recharts & Chart.js", desc: "Responsive telemetry charting" },
        { name: "Axios 1.10", desc: "HTTP client with AbortSignal" },
        { name: "Custom CSS3 Tokens", desc: "WCAG 2.1 AA compliant Dark/Light theme" },
      ],
    },
    {
      category: "Storage & Security",
      items: [
        { name: "SQLite (WAL Mode)", desc: "Concurrent timeseries storage" },
        { name: "WebSockets (RFC 6455)", desc: "1-second real-time broadcast" },
        { name: "Defensive Security Headers", desc: "nosniff, DENY, strict-origin" },
        { name: "WebSocket Connection Caps", desc: "Max 100 clients & 4KB frame limits" },
      ],
    },
  ],

  features: [
    {
      id: "cpu",
      icon: "cpu",
      category: "Hardware",
      route: "/cpu",
      title: "CPU Multi-Core Telemetry",
      desc: "Per-core load distribution, clock frequencies (min/max/current), logical and physical core topologies.",
      details: "Samples psutil.cpu_percent(percpu=True) every second with non-blocking intervals to maintain UI responsiveness.",
    },
    {
      id: "memory",
      icon: "memory",
      category: "Hardware",
      route: "/memory",
      title: "Virtual Memory & Swap",
      desc: "Real-time RAM consumption, page cache breakdown, available headroom, and swap memory saturation.",
      details: "Queries virtual_memory() and swap_memory() structures for accurate physical vs swap page allocation.",
    },
    {
      id: "disk",
      icon: "disk",
      category: "Storage",
      route: "/disk",
      title: "Disk Space & IO Throughput",
      desc: "Per-partition storage allocation, read/write throughput speeds, and cumulative sector IO tracking.",
      details: "Tracks delta bytes read/written per second across physical drives and reports per-mountpoint free capacity.",
    },
    {
      id: "network",
      icon: "network",
      category: "Network",
      route: "/network",
      title: "Network Interfaces & Bandwidth",
      desc: "Live bidirectional upload/download transfer rates, interface traffic counters, and error monitoring.",
      details: "Aggregates net_io_counters() across all active adapters and computes smoothed transfer rates.",
    },
    {
      id: "processes",
      icon: "processes",
      category: "Operating System",
      route: "/processes",
      title: "Safe Process Inspection",
      desc: "Searchable, sortable process list by PID, CPU, or RAM with detailed thread and runtime diagnostics.",
      details: "Privacy-hardened process inspection stripping environment variables, tokens, and commandline secrets.",
    },
    {
      id: "gpu",
      icon: "gpu",
      category: "Hardware",
      route: "/gpu",
      title: "GPU Diagnostics (NVIDIA NVML)",
      desc: "Dedicated GPU detection, VRAM usage, core clock frequencies, and graceful integrated fallback.",
      details: "Direct C-types binding to NVIDIA Management Library (NVML) with seamless fallback when no GPU is present.",
    },
    {
      id: "temperature",
      icon: "system",
      category: "Hardware",
      route: "/system",
      title: "Thermal Sensor Feeds",
      desc: "ACPI hardware thermal zones, CPU package temperatures, and configurable overheating warnings.",
      details: "Reads platform sensors via sensors_temperatures() and WMI thermal zones on Windows.",
    },
    {
      id: "battery",
      icon: "dashboard",
      category: "Hardware",
      route: "/system",
      title: "Battery & AC Power State",
      desc: "Real-time battery percentage, charging status, power plugged detection, and runtime estimation.",
      details: "Monitors AC line power status and calculates remaining battery runtime using discharge curves.",
    },
    {
      id: "alerts",
      icon: "anomaly",
      category: "Analytics & Alerts",
      route: "/anomalies",
      title: "Multi-Resource Threshold Alerts",
      desc: "Finite state machine tracking Normal, Warning, and Critical transitions with acknowledgment tracking.",
      details: "Configurable alert thresholds for CPU, RAM, Disk, and Temperature with hysteresis anti-flapping.",
    },
    {
      id: "history",
      icon: "history",
      category: "Storage & Analytics",
      route: "/history",
      title: "Historical Timeseries Analytics",
      desc: "Aggregated SQL time-bucket queries spanning 1h, 6h, 24h, 7d, and 30d with automated retention purge.",
      details: "Indexed SQLite queries in WAL mode performing rollups in sub-2ms latency over 27,000+ snapshots.",
    },
    {
      id: "anomalies",
      icon: "anomaly",
      category: "Analytics & Alerts",
      route: "/anomalies",
      title: "Statistical Anomaly Detection",
      desc: "Rolling-window Welford z-score algorithm flagging unusual metric spikes exceeding 3.0 standard deviations.",
      details: "Computes online mean and variance in O(1) space to detect anomalies without batch recomputation.",
    },
    {
      id: "predictions",
      icon: "prediction",
      category: "Machine Learning",
      route: "/predictions",
      title: "Predictive ML Forecasting",
      desc: "Ordinary Least Squares regression projecting resource usage over 5m, 10m, 15m, and 30m with MAE/RMSE scoring.",
      details: "Generates trend forecasts, confidence bounds, and exhaustion estimates using timeseries regression.",
    },
    {
      id: "reports",
      icon: "reports",
      category: "Reporting & Export",
      route: "/reports",
      title: "PDF Diagnostic Report Engine",
      desc: "ReportLab vector document generation across 6 specialized report types and 5 historical time ranges.",
      details: "Compiles PDF executive summaries with Matplotlib charts, anomaly audits, and automated blob cleanup.",
    },
  ],

  architecture: {
    heading: "System Architecture & Data Pipeline",
    subheading: "End-to-End Decoupled Architecture from Hardware Kernel to Browser DOM",
    layers: [
      {
        title: "1. Hardware & OS Kernel Layer",
        badge: "Kernel / Driver",
        desc: "Low-level system calls via psutil and NVML querying CPU registers, page tables, disk sector counters, and network sockets.",
        tech: ["psutil 7.2", "NVIDIA NVML", "ACPI / WMI"],
      },
      {
        title: "2. Async Background Daemon",
        badge: "Async Threading",
        desc: "Autonomous collection loop running at 1-second cadence, buffering snapshots in memory and committing to SQLite WAL mode.",
        tech: ["Python asyncio", "Threading Event", "In-Memory Ring Buffer"],
      },
      {
        title: "3. SQLite Timeseries Storage",
        badge: "Persistence Layer",
        desc: "WAL (Write-Ahead Logging) storage with b-tree indexing on timestamps, enabling sub-2ms analytics queries without reader-writer locking.",
        tech: ["SQLite 3 (WAL)", "SQLAlchemy 2.0 ORM", "Time-bucket Rollups"],
      },
      {
        title: "4. Analytics & Inference Engine",
        badge: "Math & Statistical ML",
        desc: "Welford z-score anomaly detector and Ordinary Least Squares regression forecaster evaluating trends and alert triggers.",
        tech: ["Welford Algorithm", "Linear Regression", "RMSE / MAE Scoring"],
      },
      {
        title: "5. FastAPI REST & WebSocket Server",
        badge: "API Gateway",
        desc: "High-performance ASGI server streaming real-time JSON frames over WebSockets and serving REST endpoints with Pydantic v2 validation.",
        tech: ["FastAPI 0.115", "Starlette WebSockets", "Pydantic v2 Schema"],
      },
      {
        title: "6. React 19 Single Page Application",
        badge: "Client Presentation",
        desc: "Component-driven dashboard with Chart.js canvas rendering, theme provider (Dark/Light), route protection, and blob management.",
        tech: ["React 19", "Vite 6", "Chart.js / Recharts", "Custom CSS Variables"],
      },
    ],
  },

  benchmarks: [
    { label: "Backend Test Suite", value: "356 / 356 Passed", detail: "100% test pass rate" },
    { label: "Collector Cycle Time", value: "20.84 ms", detail: "< 2.2% of 1s sampling window" },
    { label: "SQLite 24h Query Latency", value: "1.76 ms", detail: "Over 8,640 records" },
    { label: "SQLite 30d Query Latency", value: "6.42 ms", detail: "Over 27,326 records" },
    { label: "WebSocket Frame Payload", value: "284 bytes", detail: "Lightweight JSON broadcast" },
    { label: "Frontend Build Time", value: "3.30 s", detail: "0 errors, 0 warnings (Vite 6)" },
  ],

  securityHighlights: [
    "Defensive HTTP Security Headers (X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy)",
    "Strict Browser Origin Whitelist (CORS wildcards explicitly disallowed at application startup)",
    "WebSocket DoS Hardening (Max 100 concurrent clients, max 4096-byte inbound message ceiling)",
    "SQL Injection Proof (100% SQLAlchemy 2.0 ORM expressions, zero raw SQL string concatenation)",
    "Process Privacy Protection (cmdline, environ, and file handles stripped to prevent credential leaks)",
    "Thread-Safe PDF Compilation (Serialized Matplotlib figure lock preventing concurrent memory spikes)",
    "Sanitized Error Disclosure (Global 500 handler suppressing internal stack traces and paths)",
  ],

  documentation: [
    {
      title: "Final Verification Report",
      path: "FINAL_PROJECT_VERIFICATION_REPORT.md",
      desc: "Comprehensive 14-section validation audit covering performance, security, and multi-platform support.",
    },
    {
      title: "Developer & Architecture Guide",
      path: "DEVELOPMENT_GUIDE.md",
      desc: "Step-by-step instructions for extending, modifying, or removing features in the codebase.",
    },
    {
      title: "Security & Private File Policy",
      path: "SECURITY.md",
      desc: "Strict secret exclusion rules, protected files list, and vulnerability reporting procedures.",
    },
    {
      title: "Contributing Guidelines",
      path: "CONTRIBUTING.md",
      desc: "Team branching workflows, coding conventions, and pull request testing requirements.",
    },
    {
      title: "Portfolio Editing Guide",
      path: "EDITING_GUIDE.md",
      desc: "How to edit text, feature cards, technologies, and links on this showcase website.",
    },
  ],
};
