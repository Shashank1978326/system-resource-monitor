# System Resource Monitor Backend

## Requirements

- Python 3.10 or later (the audited Windows environment used Python 3.14).
- Node.js 18 or later and npm for the React dashboard.
- SQLite, provided through Python's standard-library `sqlite3` module.

## Install and run on Windows

Open two PowerShell windows from the project directory.

**Backend:**

```powershell
Set-Location .\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m uvicorn app.main:app --reload
```

If PowerShell prevents virtual-environment activation, allow it for the current
window with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then
activate the environment and continue.

**Frontend:**

```powershell
Set-Location .\frontend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The API and Swagger UI are at
`http://127.0.0.1:8000` and `http://127.0.0.1:8000/docs`.

## Install and run on Ubuntu

Open two terminal windows from the project directory. Install Python and
Node.js if needed; for example, on a current Ubuntu LTS release:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip nodejs npm
python3 --version
node --version
```

If the Ubuntu package repositories provide Node.js older than version 18,
install a supported Node.js LTS release from the official Node.js distribution
before running `npm install`.

**Backend:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. As on Windows, the backend and Swagger UI are at
`http://127.0.0.1:8000` and `http://127.0.0.1:8000/docs`. These are setup
instructions, not a claim that this release has been executed on Ubuntu.

To keep the API private to the local computer, leave Uvicorn bound to its
default loopback address (`127.0.0.1`). Do not bind to `0.0.0.0` unless remote
access is deliberately configured, firewalled, and protected by an authenticated
reverse proxy.

## Architecture

- `backend/app/api/routes` defines REST and WebSocket endpoints with strict Pydantic input validation.
- Defense-in-depth security middleware attaches standard security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) to all HTTP responses.
- WebSocket endpoint enforces strict browser origin checks, a maximum of 100 concurrent clients, and a 4KB inbound message ceiling to prevent connection exhaustion and memory abuse.
- `backend/app/services` collects resource snapshots, evaluates anomalies, predicts trends, and compiles diagnostic PDF reports with thread-safe serialization locks.
- `backend/app/database` owns the shared SQLAlchemy model, SQLite connection (WAL mode), and history repository.
- One background monitoring service gathers metrics, records history, and exposes the latest snapshot. The WebSocket publisher broadcasts that same snapshot without another collection loop or database writes.
- `frontend/src/services` contains REST calls; a shared monitoring context opens one WebSocket for the React app. Reusable pages and Recharts components render current and historical data.
- SQLite is the only database, configured in WAL mode with user-restricted permissions on POSIX systems.

## Configuration

Copy `.env.example` to `.env` before changing backend settings. Relevant
variables:

- `APP_DATA_DIR`: optional SQLite data directory.
- `MONITORING_INTERVAL_SECONDS`: collector interval, default `1`.
- `WEBSOCKET_PUBLISH_INTERVAL_SECONDS`: WebSocket publish interval, default
  `1`.
- `CPU_ALERT_WARNING_THRESHOLD_PERCENT` and
  `CPU_ALERT_CRITICAL_THRESHOLD_PERCENT`: CPU alert levels, default `80` and
  `90`. Warning must be lower than critical; both values must be within 1–100.
- `RAM_ALERT_WARNING_THRESHOLD_PERCENT` and
  `RAM_ALERT_CRITICAL_THRESHOLD_PERCENT`: RAM alert levels, default `80` and
  `90`. Warning must be lower than critical; both values must be within 1–100.
- `DISK_ALERT_WARNING_THRESHOLD_PERCENT` and
  `DISK_ALERT_CRITICAL_THRESHOLD_PERCENT`: per-partition disk alert levels,
  default `80` and `90`. Warning must be lower than critical; both values must
  be within 1–100.
- `HISTORY_RETENTION_DAYS`: history retention period, default `30`.
- `CORS_ALLOWED_ORIGINS`: comma-separated explicit browser origins; defaults
  to the two local Vite development origins. The WebSocket also checks its
  `Origin` against this allowlist.
- `VITE_API_BASE_URL`: frontend API URL, default `http://127.0.0.1:8000`.

## Live disk read speed

The existing background collector samples aggregate `psutil.disk_io_counters()`
once per monitoring cycle. It calculates read throughput from the difference
between successive total-byte-read counters divided by `time.monotonic()`
elapsed time. The first sample, counter resets, invalid elapsed times, and
unsupported counters return a null speed rather than a fabricated zero. The
sampler runs with the existing monitoring worker; it does not add another
collector or alter the SQLite history schema.

`GET /api/disk/io` returns the latest snapshot's total bytes read and written,
read and write operations, speeds in bytes/second and MB/s, measurement
timestamp, and independent availability statuses (`available`,
`initializing`, or `unavailable`). The existing `GET /api/disk` response
retains its capacity and cumulative I/O fields and also includes read/write
speed values and statuses. The Disk page polls the snapshot endpoint once per
second to display and compare read/write throughput.

## Optional GPU detection and monitoring

`GET /api/gpu/info` detects display adapters independently from the existing
CPU, memory, disk, network collector. Windows uses the built-in CIM display
adapter query; Linux checks DRM/sysfs and uses `lspci` when available to look
up model names. NVIDIA, AMD, and Intel adapters—including integrated graphics—
are identified where the OS exposes them. Unknown model/vendor details remain
unavailable instead of being guessed.

`GET /api/gpu/usage` returns only metrics available from a monitoring provider.
NVIDIA utilization, VRAM, temperature, current power consumption, and power
limit use NVML via the optional
`nvidia-ml-py` package and a working NVIDIA driver. AMD and Intel devices are
detected, but vendor-specific utilization/temperature providers are not
currently implemented; they are reported as detected with monitoring
unsupported. If no adapter is detected the API reports `GPU Not Available`;
detected but unsupported hardware reports `GPU Monitoring Not Supported`;
temporary sampling failures report `GPU Data Unavailable`. Missing readings
are `null`, never synthetic zeros. NVML power values are converted from
milliwatts to watts; devices or drivers that do not expose power readings
continue to return all other available metrics, with a partial availability
status.

The GPU page and Dashboard section refresh independently of the main resource
collector. Sampling runs in FastAPI's synchronous worker pool, with a
thread-safe two-second shared cache. The GPU page polls every three seconds,
and does not write GPU samples to SQLite or alter the WebSocket format.
Temperature and power are displayed only when NVML supplies them.

On Windows, SQLite defaults to `%LOCALAPPDATA%\SystemResourceMonitor`. On
Linux, it defaults to `$XDG_DATA_HOME/system-resource-monitor` or
`~/.local/share/system-resource-monitor`.

## Hardware temperature sensors

`GET /api/temperature` reads available hardware sensor values through
`psutil.sensors_temperatures()` and does not start another monitor. The response
includes an availability status (`available`, `unavailable`, or `unsupported`),
the host platform, and readings with sensor group/name, label, current °C,
optional high/critical thresholds, and an optional device association.
Unavailable values remain `null`; zero is shown only when the sensor reports
an actual zero.

Linux and FreeBSD use psutil's supported sensor interfaces. Windows is probed
through psutil, but if no usable readings are exposed the API reports
`unsupported`; it does not treat legacy WMI thermal-zone values as CPU
temperature. Other unsupported platforms are reported similarly. No drivers,
administrator access, or extra dependencies are required. The System
Information page polls this API every 30 seconds. Historical temperature
samples are taken during the existing history-persistence cycle and are stored
in the existing SQLite database. This does not add another monitoring loop or
change the main snapshot or WebSocket message format.

Temperature alerts reuse the shared Resource Alerts state machine and event
history. Warning and critical thresholds default to **80 °C** and **90 °C**.
They can be changed in Settings or configured with
`TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS` and
`TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS`; both values must be finite,
non-negative, and warning must be lower than critical. Alerts are generated
only from actual finite sensor readings. Each sensor transitions independently
and creates events only when severity changes, including recovery below the
warning level. Missing sensors or readings do not cause recovery events.
Temperature readings and thresholds are available under the shared
`GET /api/alerts` and `GET/PUT /api/alerts/thresholds` APIs; filter alert history
using `GET /api/alerts/history?resource=temperature`. Alert event and current
state tables are extended additively; legacy events and configured resource
thresholds are preserved.

## Battery status

`GET /api/battery` reads the battery returned by `psutil.sensors_battery()`.
The response includes availability, platform, percentage, power connection,
charging state, remaining time in seconds and a human-readable form, and a
status message. A desktop with no detected battery returns a valid
`unavailable` response; unsupported sensor APIs and access errors are reported
explicitly. Missing readings and psutil's unknown/unlimited remaining-time
sentinels remain `null`, and zero readings are preserved.

psutil exposes whether external power is connected, but not a separate
charging-current measurement. A battery below 100% while connected is reported
as charging; a full battery is reported as not charging. The System Information
page refreshes this endpoint every 30 seconds without adding a background
collector or changing the monitoring WebSocket.

Battery history is recorded in the existing `historical_metrics` row written
by the monitoring collector. Nullable battery columns are added to existing
SQLite databases at startup without replacing tables or modifying prior
records. The `battery` metric on `GET /api/history/graph` returns the average
percentage and the latest recorded availability, charging state, and power
connection for each UTC-aligned bucket. `status_timestamp` identifies the
sample used for the status fields. Battery history uses the existing time
ranges, intervals, and retention cleanup.

Example available response:

```json
{
  "availability": "available",
  "platform": "Windows",
  "percentage": 75.0,
  "charging_state": "discharging",
  "power_plugged": false,
  "remaining_seconds": 7200,
  "remaining_time": "2 hours",
  "message": "Battery is discharging."
}
```

## Historical SQLite data

Samples are stored in `history.sqlite3` inside the platform's application data
directory. On Windows the default is
`%LOCALAPPDATA%\SystemResourceMonitor`; on Linux and macOS it is
`$XDG_DATA_HOME/system-resource-monitor` or `~/.local/share/system-resource-monitor`.
Set `APP_DATA_DIR` to use a different dedicated application data directory.

`HISTORY_RETENTION_DAYS` controls how many days of history are retained. It
defaults to `30` and must be a positive integer. Expired records are cleaned up
at startup and once per day while monitoring is running.

Capacity planning: a temporary Windows run storing 297 real snapshots occupied
about 60 KiB after a SQLite checkpoint. A straight-line estimate at the default
one sample per second is roughly 0.5 GB per 30 days; actual size varies with
SQLite page allocation and platform data. Retention is the built-in size
control—there is no separate database-size cap.

The history endpoints are `GET /api/history`, `GET /api/history/summary`, and
`GET /api/history/stats`. Disk utilization history is calculated as the
capacity-weighted percentage used across accessible mounted partitions:
summed used bytes divided by summed total bytes. Unavailable metrics remain
null rather than being replaced with synthetic values.

## Historical graph API

`GET /api/history/graph` returns average values grouped into UTC, epoch-aligned
time buckets. All three query parameters are required:

| Parameter | Supported values |
| --- | --- |
| `metric` | `cpu`, `memory`, `disk`, `network_download`, `network_upload`, `disk_read`, `disk_write`, `disk_read_speed`, `disk_write_speed`, `network_interface_download`, `network_interface_upload`, `temperature` |
| `range` | `5m`, `15m`, `30m`, `1h`, `6h`, `12h`, `24h`, `7d` |
| `interval` | `1m`, `5m`, `15m`, `1h` |
| `interface` | Required for per-interface metrics; use a name returned by `GET /api/history/interfaces` |
| `sensor_id` | Required for temperature metrics; use an ID returned by `GET /api/history/temperature-sensors` |

Units are `percent` for CPU, memory, and disk utilization; `bytes_per_second`
for network download/upload and disk read/write throughput; and `bytes` for
the cumulative disk read/write counters. Disk throughput fields are stored
from the existing monotonic-time-based sampler, not derived from cumulative
counter averages. Missing values are returned as JSON `null`; when no
historical rows match the requested range, `data_points` is an empty array.
Per-interface metrics use the same units and aggregation behavior, with rates
filtered to the exact selected interface name.
The `temperature` metric is measured in `celsius`; its averages are calculated
for one selected sensor at a time so unrelated hardware readings are never
combined.

Disk throughput is recorded in the existing `historical_metrics` table as
bytes per second. Startup safely adds nullable `disk_read_speed` and
`disk_write_speed` columns to existing databases using additive SQLite
`ALTER TABLE` statements; existing records are preserved and naturally have
null throughput for periods before this feature.
Queries that could produce more than 10,000 points are rejected with HTTP 422.
Per-interface rates are stored in the additive
`historical_network_interface_metrics` table in the same SQLite database. Each
sample stores the interface name, UTC timestamp, download B/s, and upload B/s.
The existing collector snapshot is persisted atomically with its interface
samples; unavailable directions remain null and genuine zero rates remain zero.
This table is created automatically for existing databases without modifying
or deleting earlier history and is cleaned using the existing retention policy.
`GET /api/history/interfaces` lists interface names present in retained history.
An unknown interface in a graph request returns HTTP 404; omitting the
`interface` parameter for an interface metric returns HTTP 422.

Temperature samples are stored in the additive
`historical_temperature_metrics` table alongside the existing history in the
same SQLite database. Each row represents one valid sensor reading and stores
its sensor ID, group name, optional label, reading index, Celsius value, and
UTC timestamp. Sensors with unavailable readings do not produce a sample, and
real zero-degree readings remain zero. Samples are retained and removed using
the existing history-retention policy. The table is created for existing
databases without replacing or deleting earlier records; past temperatures
cannot be backfilled.
`GET /api/history/temperature-sensors` lists sensor identities present in
retained temperature history. The `sensor_id` parameter is required for a
temperature graph; an unknown ID returns HTTP 404. Sensor IDs are formed from
the psutil sensor group and reading index.

Example request:

```text
GET /api/history/graph?metric=cpu&range=1h&interval=1m
```

Per-interface example:

```text
GET /api/history/graph?metric=network_interface_download&interface=Wi-Fi&range=1h&interval=1m
```

List names available for selection:

```text
GET /api/history/interfaces
```

Temperature history example:

```text
GET /api/history/temperature-sensors
GET /api/history/graph?metric=temperature&sensor_id=coretemp%3A0&range=1h&interval=1m
```

Example response:

```json
{
  "metric": "cpu",
  "time_range": "1h",
  "interval": "1m",
  "unit": "percent",
  "data_points": [
    { "timestamp": "2026-11-02T10:00:00Z", "value": 35.5 },
    { "timestamp": "2026-11-02T10:01:00Z", "value": 42.3 }
  ]
}
```

Temperature graph example:

```json
{
  "metric": "temperature",
  "time_range": "1h",
  "interval": "1m",
  "unit": "celsius",
  "data_points": [
    { "timestamp": "2026-11-02T10:00:00Z", "value": 55.2 }
  ]
}
```

## Real-time WebSocket

Connect to `ws://localhost:8000/ws/monitoring`. The server publishes the latest
snapshot produced by the existing background monitor; the WebSocket does not
start another system-resource collection loop or write additional history.
Until the first snapshot is available, the connection remains open and waits
for an update. Each update contains only the resource percentages and network
speeds intended for the monitoring display:

```json
{
  "type": "resource_update",
  "timestamp": "2026-11-02T10:00:00Z",
  "data": {
    "cpu_percent": 35.5,
    "memory_percent": 62.4,
    "disk_percent": 45.2,
    "network_download_bytes_per_sec": 102400,
    "network_upload_bytes_per_sec": 51200
  }
}
```

`WEBSOCKET_PUBLISH_INTERVAL_SECONDS` sets the publishing interval in seconds.
It defaults to `1` and must be finite and at least `0.1`. The independent
`MONITORING_INTERVAL_SECONDS` setting controls how often the background
collector samples system resources.

## Tests and interactive API docs

Run the complete backend test suite from `backend`:

```text
python -m pytest -q
```

Build the frontend from `frontend`:

```text
npm run build
```

Start the API and open `http://127.0.0.1:8000/docs` to explore its endpoints
in Swagger UI. In a browser developer console on an allowed frontend origin,
you can inspect WebSocket updates with:

```javascript
const socket = new WebSocket("ws://127.0.0.1:8000/ws/monitoring");
socket.onmessage = (event) => console.log(JSON.parse(event.data));
```

## Frontend dashboard

The React/Vite dashboard lives in `../frontend` and uses the API fields defined
by the backend schemas. It provides live CPU, memory, disk, and network cards;
resource detail pages; system information; historical charts; and saved
appearance/display preferences. The dashboard reads one initial monitoring
snapshot and then uses the existing WebSocket stream for live updates rather
than polling resource endpoints.

From the frontend directory, install packages and start the development server:

```powershell
npm install
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run dev
```

`VITE_API_BASE_URL` defaults to `http://127.0.0.1:8000`. The backend allows
browser requests from `http://localhost:5173` and `http://127.0.0.1:5173` by
default; set `CORS_ALLOWED_ORIGINS` to a comma-separated list of explicit
origins if the frontend is served elsewhere. The WebSocket uses the same base
URL, switching to `wss` when the API URL uses HTTPS.

For production frontend assets, use `npm run build` and serve `frontend/dist`
with a static file server. Configure `VITE_API_BASE_URL` at build time and add
the frontend's exact origin to `CORS_ALLOWED_ORIGINS` before serving it.

## Process monitoring

The Process monitor page is available at `/processes` in the dashboard. It
displays process IDs, names, statuses, and individual CPU/RAM usage. It supports
case-insensitive name search and refreshes every 10 seconds. The API enumerates
processes only when requested; it does not add another background collector.

`GET /api/processes` returns at most 100 records by default. `search` filters
process names, and `limit` can be set from 1 through 500. `total_processes`
is the matching count before the result limit; `total_process_count` is the
count across the unfiltered list. `status` filters by the process status string
and can be combined with `search`. `sort_by` accepts `pid`, `cpu`, or `ram`;
`sort_order` accepts `asc` or `desc`. The default is PID ascending. CPU and RAM
sorting put unavailable readings last.

Each process includes `cpu_percent`, `memory_mb`, and `memory_percent`. RAM MB
uses MiB-sized units (bytes divided by 1024²), and RAM percent is the process's
resident memory divided by total physical memory. CPU readings are non-blocking:
psutil's first sample establishes a baseline and is returned as `null`; later
samples report measured CPU percent and may exceed 100% on multi-core systems.
Unavailable per-process measurements are null. Processes that disappear or
become zombies mid-sample are skipped. The response also includes the
five highest measured CPU consumers and five highest RAM consumers in
`top_cpu_processes` and `top_ram_processes`. These lists are computed across
all enumerated processes, independent of the search and display limit.
Only processes with an available measurement are included; CPU consumers are
empty until psutil has collected a baseline and a subsequent sample.
Windows' special System Idle Process (PID 0) remains visible in the process
table but is excluded from the top CPU consumers because it represents idle
capacity rather than CPU consumption.
Command-line arguments and environment variables are never collected.

`GET /api/processes/{pid}` retrieves a single process's current details,
including thread count, UTC creation time, and username when available.
Non-positive PIDs are rejected with HTTP 422, processes that disappear during
lookup return HTTP 404, and inaccessible details return HTTP 403. Individual
fields that are unavailable due to permissions are null; username is omitted
from the UI when unavailable.

The Process monitor page includes a status filter and opens a details panel by
selecting a process name. The main dashboard also displays the top five CPU
and RAM consumers and links to the full process list. Its summary refreshes
every 30 seconds; the process page refreshes its list every 10 seconds.

Example request:

```text
GET /api/processes?search=python&limit=50&sort_by=cpu&sort_order=desc
```

```text
GET /api/processes?status=running&sort_by=ram&sort_order=desc
GET /api/processes/1234
```

Example response:

```json
{
  "total_processes": 1,
  "total_process_count": 335,
  "processes": [
    {
      "pid": 1234,
      "name": "python.exe",
      "status": "running",
      "cpu_percent": 12.5,
      "memory_mb": 64.0,
      "memory_percent": 0.8
    }
  ],
  "top_cpu_processes": [],
  "top_ram_processes": []
}
```

The details response adds `thread_count`, `create_time`, and `username` to
the standard process resource fields.

## CPU, RAM, and disk usage alerts

The existing background collector evaluates CPU, RAM, and each accessible
disk partition using its regular monitoring snapshot. No extra collection
loop is started. Warning thresholds default to 80%; values from 80% to below
90% are Warning, and 90% or higher is Critical. Values below 80% are Normal.
Configure each resource independently with its corresponding
`*_ALERT_WARNING_THRESHOLD_PERCENT` and `*_ALERT_CRITICAL_THRESHOLD_PERCENT`
variables in `.env`; these environment values are the initial defaults. The
Settings page saves overrides to SQLite. Each threshold must be within 1–100,
and warning must be lower than critical. Saved settings are applied without a
backend restart and take precedence over environment defaults on later starts.

`GET /api/alerts/status` returns the existing CPU status fields plus `ram` and
`disk` state. `GET /api/alerts` preserves its existing CPU `status` and
`recent_events` fields, and adds `ram` and `disk` objects, each with a current
status and up to 50 recent transitions. Disk state includes each partition's
device, mount point, capacity, used/free bytes, percentage, and last valid
sample time. Disk events identify the affected partition and include the same
capacity details.

Events are emitted only when a resource changes state, preventing duplicates
on each collection cycle. Recovery to Normal is included as a Normal-severity
event. Missing, inaccessible, non-finite, or out-of-range readings are
ignored; partitions that are inaccessible or disappear retain their last
valid state rather than generating a false recovery. Alert events, partition
details, acknowledgement state, and threshold overrides are saved in the
existing SQLite database. New tables are created additively; existing
monitoring history is preserved.

Alert management routes:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/alerts/history` | Paginated history; optional resource, severity, limit (1–200), and offset filters |
| `PATCH` | `/api/alerts/{alert_id}/acknowledge` | Acknowledge one alert (idempotent) |
| `DELETE` | `/api/alerts/{alert_id}` | Delete one alert event |
| `DELETE` | `/api/alerts/history` | Clear alert events without deleting monitoring history |
| `GET` | `/api/alerts/thresholds` | Read current thresholds |
| `PUT` | `/api/alerts/thresholds` | Validate, persist, and apply all six thresholds |

The dashboard's Resource Alerts panel polls current state and event history
independently, offers filters and acknowledgement/deletion controls, and shows
the alert history table. Browser notifications are opt-in; permission is
requested only after the user enables them, and only newly observed Warning
or Critical events trigger notifications.
