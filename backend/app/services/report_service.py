"""Backend PDF report generation engine using ReportLab and Matplotlib."""

import io
import logging
import math
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

# Configure headless Matplotlib with a dedicated writable cache directory before importing matplotlib/pyplot
_mpl_cache_directory = os.path.join(tempfile.gettempdir(), "system-resource-monitor-mpl-cache")
try:
    os.makedirs(_mpl_cache_directory, exist_ok=True)
except OSError:
    pass
os.environ.setdefault("MPLCONFIGDIR", _mpl_cache_directory)
import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import reportlab.rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter

reportlab.rl_config.pageCompression = 0
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import database
from app.database.models import (
    AlertEvent,
    AnomalyEvent,
    HistoricalMetrics,
    HistoricalPrediction,
)
from app.services.alert_service import cpu_alert_service
from app.services.anomaly_service import anomaly_service
from app.services.battery_service import get_battery_info
from app.services.cpu_service import get_cpu_info
from app.services.disk_service import get_disk_info
from app.services.gpu_service import get_gpu_info
from app.services.memory_service import get_memory_info
from app.services.network_service import get_network_info
from app.services.prediction_service import prediction_service
from app.services.process_service import get_processes
from app.services.system_service import get_system_info
from app.services.temperature_service import get_temperature_info

logger = logging.getLogger(__name__)

SUPPORTED_REPORT_RANGES: dict[str, int] = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}

RANGE_LABELS: dict[str, str] = {
    "1h": "Last 1 Hour",
    "6h": "Last 6 Hours",
    "24h": "Last 24 Hours",
    "7d": "Last 7 Days",
    "30d": "Last 30 Days",
}

SUPPORTED_REPORT_TYPES: dict[str, str] = {
    "all": "Complete System Report",
    "cpu_memory": "CPU and Memory Report",
    "disk_network": "Disk and Network Report",
    "process_resource": "Process and Resource Report",
    "alerts_anomaly": "Alerts and Anomaly Report",
    "prediction_accuracy": "Prediction and Accuracy Report",
}


class ReportGenerationError(Exception):
    """Failure during PDF document compilation."""


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print 'Page X of Y' headers and footers."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["pageCompression"] = 0
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))

        # Running header (pages > 1)
        if self._pageNumber > 1:
            self.drawString(
                40, 756, "System Resource Monitor — Diagnostic & Performance Report"
            )
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(40, 750, 572, 750)

        # Running footer (all pages)
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(572, 28, page_str)
        self.drawString(
            40,
            28,
            "Confidential & Automated Diagnostics — System Resource Monitor",
        )
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(40, 38, 572, 38)
        self.restoreState()


def _format_bytes(value: int | float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    val = float(value)
    if val < 0:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if val < 1024.0 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} PB"


def _format_rate(value: int | float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    val = float(value)
    if val < 0:
        return "0 B/s"
    for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
        if val < 1024.0 or unit == "GB/s":
            return f"{val:.1f} {unit}" if unit != "B/s" else f"{int(val)} B/s"
        val /= 1024.0
    return f"{val:.1f} TB/s"


def _format_percent(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.1f}%"


def _format_dt(dt: datetime | str | None) -> str:
    if not dt:
        return "—"
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class ReportChartGenerator:
    """Generates publication-quality charts for PDF inclusion using Matplotlib."""

    def __init__(self) -> None:
        self.buffers: list[io.BytesIO] = []

    def close(self) -> None:
        """Close and release all chart memory buffers."""
        for buf in self.buffers:
            try:
                buf.close()
            except Exception:
                pass
        self.buffers.clear()

    def _create_image(self, fig: plt.Figure, width: int = 500, height: int = 150) -> Image:
        """Save figure to in-memory PNG buffer and return ReportLab Image flowable."""
        buf = io.BytesIO()
        fig.savefig(
            buf,
            format="png",
            dpi=90,
            bbox_inches="tight",
            facecolor="#ffffff",
            edgecolor="none",
        )
        plt.close(fig)
        buf.seek(0)
        self.buffers.append(buf)
        img = Image(buf, width=width, height=height)
        img.hAlign = "CENTER"
        return img

    def _render_fallback(self, title: str, message: str) -> Image:
        """Render a clean placeholder card when real telemetry is unavailable or empty."""
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ax.set_facecolor("#f8fafc")
        fig.patch.set_facecolor("#ffffff")
        ax.text(
            0.5,
            0.45,
            message,
            horizontalalignment="center",
            verticalalignment="center",
            transform=ax.transAxes,
            fontsize=8.5,
            color="#64748b",
            style="italic",
        )
        ax.set_title(title, fontsize=9.5, fontweight="bold", color="#1e293b", pad=8)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#cbd5e1")
            spine.set_linestyle(":")
            spine.set_linewidth(0.8)
        fig.tight_layout()
        return self._create_image(fig, width=500, height=135)

    # 1. CPU utilization over time
    def chart_cpu_utilization(
        self, records: list[HistoricalMetrics], start_time: datetime, end_time: datetime
    ) -> Image:
        valid = [r for r in records if r.cpu_utilization_percent is not None]
        if len(valid) < 2:
            return self._render_fallback(
                "CPU Utilization Trend Over Time",
                "Insufficient historical CPU records for time series plot (minimum 2 samples required).",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ts = [r.timestamp for r in valid]
        vals = [r.cpu_utilization_percent for r in valid]
        ax.plot(ts, vals, color="#2563eb", linewidth=1.4, label="CPU Usage %")
        ax.fill_between(ts, vals, color="#3b82f6", alpha=0.15)
        ax.set_ylim(0, max(100.0, max(vals) * 1.1))
        ax.set_ylabel("Usage (%)", fontsize=7.5, color="#475569")
        ax.set_title("CPU Utilization Trend Over Time", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 2. Memory utilization over time
    def chart_memory_utilization(
        self, records: list[HistoricalMetrics], start_time: datetime, end_time: datetime
    ) -> Image:
        valid = [r for r in records if r.ram_utilization_percent is not None]
        if len(valid) < 2:
            return self._render_fallback(
                "Memory Utilization Trend Over Time",
                "Insufficient historical memory records for time series plot.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ts = [r.timestamp for r in valid]
        vals = [r.ram_utilization_percent for r in valid]
        ax.plot(ts, vals, color="#7c3aed", linewidth=1.4, label="RAM Usage %")
        ax.fill_between(ts, vals, color="#8b5cf6", alpha=0.15)
        ax.set_ylim(0, 100.0)
        ax.set_ylabel("Usage (%)", fontsize=7.5, color="#475569")
        ax.set_title("Memory (RAM) Utilization Trend Over Time", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 3. Disk utilization over time
    def chart_disk_utilization(
        self, records: list[HistoricalMetrics], start_time: datetime, end_time: datetime
    ) -> Image:
        valid = [r for r in records if r.disk_utilization_percent is not None]
        if len(valid) < 2:
            return self._render_fallback(
                "Disk Capacity Utilization Trend",
                "Insufficient historical disk capacity samples recorded.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ts = [r.timestamp for r in valid]
        vals = [r.disk_utilization_percent for r in valid]
        ax.plot(ts, vals, color="#0284c7", linewidth=1.4, label="Storage Used %")
        ax.fill_between(ts, vals, color="#38bdf8", alpha=0.15)
        ax.set_ylim(0, 100.0)
        ax.set_ylabel("Capacity (%)", fontsize=7.5, color="#475569")
        ax.set_title("Disk Storage Capacity Utilization Trend", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 4. Disk read/write throughput
    def chart_disk_io_throughput(
        self, records: list[HistoricalMetrics], start_time: datetime, end_time: datetime
    ) -> Image:
        valid = [r for r in records if r.disk_read_speed is not None and r.disk_write_speed is not None]
        if len(valid) < 2:
            return self._render_fallback(
                "Disk I/O Throughput (Read / Write)",
                "Insufficient historical disk throughput samples recorded.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ts = [r.timestamp for r in valid]
        # Convert to KB/s
        reads = [(r.disk_read_speed or 0.0) / 1024.0 for r in valid]
        writes = [(r.disk_write_speed or 0.0) / 1024.0 for r in valid]
        ax.plot(ts, reads, color="#059669", linewidth=1.2, label="Read (KB/s)")
        ax.plot(ts, writes, color="#d97706", linewidth=1.2, label="Write (KB/s)")
        ax.set_ylabel("Speed (KB/s)", fontsize=7.5, color="#475569")
        ax.set_title("Disk I/O Throughput Activity", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 5. Network download/upload throughput
    def chart_network_throughput(
        self, records: list[HistoricalMetrics], start_time: datetime, end_time: datetime
    ) -> Image:
        valid = [r for r in records if r.network_download_speed is not None and r.network_upload_speed is not None]
        if len(valid) < 2:
            return self._render_fallback(
                "Network Throughput (Download / Upload)",
                "Insufficient historical network traffic samples recorded.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        ts = [r.timestamp for r in valid]
        # Convert to KB/s
        downs = [(r.network_download_speed or 0.0) / 1024.0 for r in valid]
        ups = [(r.network_upload_speed or 0.0) / 1024.0 for r in valid]
        ax.plot(ts, downs, color="#2563eb", linewidth=1.2, label="Download (KB/s)")
        ax.plot(ts, ups, color="#9333ea", linewidth=1.2, label="Upload (KB/s)")
        ax.set_ylabel("Throughput (KB/s)", fontsize=7.5, color="#475569")
        ax.set_title("Network Interface Throughput", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 6. Resource alert history
    def chart_alert_history(self, alert_counts: dict[str, int], recent_alerts: list[AlertEvent]) -> Image:
        total = alert_counts.get("total", 0)
        if total == 0:
            return self._render_fallback(
                "Resource Alert Distribution",
                "No alert events triggered during this reporting window. All metrics within thresholds.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        categories = ["Warning Alerts", "Critical Alerts"]
        vals = [alert_counts.get("warning", 0), alert_counts.get("critical", 0)]
        colors_list = ["#f59e0b", "#ef4444"]
        bars = ax.barh(categories, vals, color=colors_list, height=0.45)
        for bar in bars:
            w = bar.get_width()
            ax.text(w + max(0.1, max(vals) * 0.02), bar.get_y() + bar.get_height() / 2, f"{int(w)}",
                    va="center", fontsize=8, fontweight="bold", color="#1e293b")
        ax.set_xlim(0, max(vals) * 1.25 + 1)
        ax.set_xlabel("Count", fontsize=7.5, color="#475569")
        ax.set_title("Resource Alerts Severity Summary", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(axis="x", linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.tick_params(labelsize=7.5, colors="#475569")
        fig.tight_layout()
        return self._create_image(fig)

    # 7. Anomaly frequency over time
    def chart_anomaly_frequency(self, anomaly_events: list[AnomalyEvent], start_time: datetime, end_time: datetime) -> Image:
        if not anomaly_events:
            return self._render_fallback(
                "Anomaly Event Frequency Over Time",
                "No statistical anomalies detected during this reporting window. Telemetry variance was nominal.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        warn_ts = [e.timestamp for e in anomaly_events if e.severity == "warning"]
        crit_ts = [e.timestamp for e in anomaly_events if e.severity == "critical"]
        
        bins = min(15, max(3, len(anomaly_events)))
        if warn_ts and crit_ts:
            ax.hist([warn_ts, crit_ts], bins=bins, color=["#f59e0b", "#ef4444"], label=["Warning", "Critical"], stacked=True)
        elif warn_ts:
            ax.hist(warn_ts, bins=bins, color="#f59e0b", label="Warning")
        else:
            ax.hist(crit_ts, bins=bins, color="#ef4444", label="Critical")

        ax.set_ylabel("Anomaly Count", fontsize=7.5, color="#475569")
        ax.set_title("Statistical Anomaly Frequency Timeline", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(True, linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end_time - start_time).total_seconds() <= 86400 else "%m-%d"))
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 8. Resource-wise anomaly distribution
    def chart_anomaly_distribution(self, anomaly_breakdown: list[dict[str, Any]]) -> Image:
        if not anomaly_breakdown:
            return self._render_fallback(
                "Resource-Wise Anomaly Distribution",
                "No anomalies to display. Telemetry distributions remained stable.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        res_names = [b["resource"].upper() for b in anomaly_breakdown]
        warn_counts = [b.get("warning", 0) for b in anomaly_breakdown]
        crit_counts = [b.get("critical", 0) for b in anomaly_breakdown]
        
        x = range(len(res_names))
        ax.bar(x, warn_counts, width=0.4, label="Warning", color="#f59e0b")
        ax.bar([i + 0.4 for i in x], crit_counts, width=0.4, label="Critical", color="#ef4444")
        ax.set_xticks([i + 0.2 for i in x])
        ax.set_xticklabels(res_names, fontsize=7.5, fontweight="bold", color="#1e293b")
        ax.set_ylabel("Events", fontsize=7.5, color="#475569")
        ax.set_title("Anomaly Events by Monitored Resource", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(axis="y", linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 9. Actual versus predicted resource utilization
    def chart_actual_vs_predicted(self, predictions: list[Any]) -> Image:
        pct_preds = [
            p for p in predictions
            if getattr(p, "unit", "") == "percent" and getattr(p, "predicted_value", None) is not None
        ]
        if not pct_preds:
            return self._render_fallback(
                "Actual vs. Predicted Utilization",
                "Forecasting engine actively warming up. Accumulating continuous historical telemetry.",
            )
        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        labels = [f"{getattr(p, 'resource', 'RES').upper()} ({getattr(p, 'horizon', '15m')})" for p in pct_preds[:5]]
        currents = [p.current_value if p.current_value is not None else 0.0 for p in pct_preds[:5]]
        forecasts = [p.predicted_value if p.predicted_value is not None else 0.0 for p in pct_preds[:5]]
        
        indices = range(len(labels))
        ax.bar(indices, currents, width=0.35, label="Measured Value", color="#3b82f6")
        ax.bar([i + 0.35 for i in indices], forecasts, width=0.35, label="Predicted Value", color="#8b5cf6")
        ax.set_xticks([i + 0.175 for i in indices])
        ax.set_xticklabels(labels, fontsize=7, color="#1e293b")
        ax.set_ylabel("Utilization (%)", fontsize=7.5, color="#475569")
        all_vals = forecasts + currents
        max_y = max(all_vals) if all_vals else 100.0
        ax.set_ylim(0, max(100.0, max_y * 1.15))
        ax.set_title("Measured vs Forecasted Resource Utilization", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(axis="y", linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)

    # 10. Prediction error and accuracy trends
    def chart_prediction_error_and_accuracy(self, accuracy_data: Any) -> Image:
        if not accuracy_data or not getattr(accuracy_data, "by_horizon", None):
            return self._render_fallback(
                "Prediction Error Metrics (MAE & RMSE)",
                "Forecast evaluation pending. Error metrics compute automatically as forecast target times elapse.",
            )
        by_h = accuracy_data.by_horizon
        evaluated_horizons = [h for h in by_h if getattr(h, "evaluated_count", 0) > 0]
        if not evaluated_horizons:
            # Check if any pending forecasts exist
            pending_total = sum(getattr(h, "pending_count", 0) for h in by_h)
            if pending_total == 0:
                return self._render_fallback(
                    "Prediction Error Metrics (MAE & RMSE)",
                    "Forecast evaluation pending. Error metrics compute automatically as forecast target times elapse.",
                )
            fig, ax = plt.subplots(figsize=(6.2, 1.8))
            hz_labels = [h.horizon for h in by_h]
            pending_vals = [getattr(h, "pending_count", 0) for h in by_h]
            bars = ax.bar(hz_labels, pending_vals, color="#0284c7", width=0.45)
            for bar in bars:
                h_val = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, h_val + 0.1, f"{int(h_val)}",
                        ha="center", fontsize=7.5, fontweight="bold", color="#1e293b")
            ax.set_ylabel("Pending Forecasts", fontsize=7.5, color="#475569")
            ax.set_title("Forecast Pipeline Status (Evaluations Awaiting Target Time)", fontsize=9, fontweight="bold", color="#1e293b")
            ax.grid(axis="y", linestyle="--", linewidth=0.5, color="#e2e8f0")
            ax.tick_params(labelsize=7.5, colors="#475569")
            fig.tight_layout()
            return self._create_image(fig)

        fig, ax = plt.subplots(figsize=(6.2, 1.8))
        hz_names = [h.horizon for h in evaluated_horizons]
        maes = [h.mae or 0.0 for h in evaluated_horizons]
        rmses = [h.rmse or 0.0 for h in evaluated_horizons]
        idx = range(len(hz_names))
        ax.bar(idx, maes, width=0.35, label="MAE", color="#0284c7")
        ax.bar([i + 0.35 for i in idx], rmses, width=0.35, label="RMSE", color="#dc2626")
        ax.set_xticks([i + 0.175 for i in idx])
        ax.set_xticklabels(hz_names, fontsize=7.5, fontweight="bold", color="#1e293b")
        ax.set_ylabel("Error Value", fontsize=7.5, color="#475569")
        ax.set_title("Prediction Error by Horizon (MAE & RMSE)", fontsize=9, fontweight="bold", color="#1e293b")
        ax.grid(axis="y", linestyle="--", linewidth=0.5, color="#e2e8f0")
        ax.tick_params(labelsize=7, colors="#475569")
        ax.legend(loc="upper right", fontsize=7, frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1")
        fig.tight_layout()
        return self._create_image(fig)


class ReportService:
    """Collects system telemetry and builds formatted PDF diagnostic reports."""

    def __init__(self) -> None:
        self.session_factory = database.session_factory
        self._lock = threading.Lock()

    def collect_historical_aggregates(
        self, start_time: datetime
    ) -> dict[str, Any]:
        """Aggregate CPU, memory, disk, and network historical statistics from SQLite."""
        try:
            with self.session_factory() as session:
                stmt = select(
                    func.count(HistoricalMetrics.id),
                    func.min(HistoricalMetrics.cpu_utilization_percent),
                    func.avg(HistoricalMetrics.cpu_utilization_percent),
                    func.max(HistoricalMetrics.cpu_utilization_percent),
                    func.min(HistoricalMetrics.ram_utilization_percent),
                    func.avg(HistoricalMetrics.ram_utilization_percent),
                    func.max(HistoricalMetrics.ram_utilization_percent),
                    func.avg(HistoricalMetrics.disk_read_speed),
                    func.max(HistoricalMetrics.disk_read_speed),
                    func.avg(HistoricalMetrics.disk_write_speed),
                    func.max(HistoricalMetrics.disk_write_speed),
                    func.avg(HistoricalMetrics.network_download_speed),
                    func.max(HistoricalMetrics.network_download_speed),
                    func.avg(HistoricalMetrics.network_upload_speed),
                    func.max(HistoricalMetrics.network_upload_speed),
                    func.avg(HistoricalMetrics.disk_utilization_percent),
                ).where(HistoricalMetrics.timestamp >= start_time)

                row = session.execute(stmt).one()

                count = row[0] or 0
                return {
                    "sample_count": count,
                    "cpu_min": round(row[1], 1) if row[1] is not None else None,
                    "cpu_avg": round(row[2], 1) if row[2] is not None else None,
                    "cpu_max": round(row[3], 1) if row[3] is not None else None,
                    "ram_min": round(row[4], 1) if row[4] is not None else None,
                    "ram_avg": round(row[5], 1) if row[5] is not None else None,
                    "ram_max": round(row[6], 1) if row[6] is not None else None,
                    "disk_read_avg": row[7],
                    "disk_read_max": row[8],
                    "disk_write_avg": row[9],
                    "disk_write_max": row[10],
                    "net_down_avg": row[11],
                    "net_down_max": row[12],
                    "net_up_avg": row[13],
                    "net_up_max": row[14],
                    "disk_util_avg": round(row[15], 1) if row[15] is not None else None,
                }
        except SQLAlchemyError as exc:
            logger.exception("Failed to query historical metrics aggregates")
            raise exc

    def collect_historical_records(
        self, start_time: datetime, max_points: int = 120
    ) -> list[HistoricalMetrics]:
        """Fetch sampled historical records for timeseries charts."""
        try:
            with self.session_factory() as session:
                stmt = (
                    select(HistoricalMetrics)
                    .where(HistoricalMetrics.timestamp >= start_time)
                    .order_by(HistoricalMetrics.timestamp.asc())
                )
                records = list(session.scalars(stmt))
                if len(records) > max_points:
                    step = max(1, len(records) // max_points)
                    records = records[::step]
                return records
        except SQLAlchemyError as exc:
            logger.exception("Failed to fetch timeseries historical metrics")
            raise exc

    def collect_alerts_data(
        self, start_time: datetime
    ) -> tuple[dict[str, int], list[AlertEvent]]:
        """Collect alert statistics and recent events for the time range."""
        try:
            with self.session_factory() as session:
                stmt = (
                    select(AlertEvent)
                    .where(AlertEvent.timestamp >= start_time)
                    .order_by(AlertEvent.timestamp.desc())
                    .limit(20)
                )
                events = list(session.scalars(stmt))

                count_stmt = (
                    select(AlertEvent.severity, func.count(AlertEvent.id))
                    .where(AlertEvent.timestamp >= start_time)
                    .group_by(AlertEvent.severity)
                )
                counts: dict[str, int] = {"warning": 0, "critical": 0, "total": 0}
                for sev, cnt in session.execute(count_stmt):
                    if sev == "warning":
                        counts["warning"] += cnt
                    elif sev == "critical":
                        counts["critical"] += cnt
                    counts["total"] += cnt

                return counts, events
        except SQLAlchemyError as exc:
            logger.exception("Failed to query alert events for report")
            raise exc

    def collect_anomaly_data(
        self, start_time: datetime
    ) -> tuple[dict[str, int], list[dict[str, Any]], list[AnomalyEvent]]:
        """Collect anomaly event metrics and breakdown for the report."""
        try:
            with self.session_factory() as session:
                counts: dict[str, int] = {"warning": 0, "critical": 0, "total": 0}
                count_stmt = (
                    select(AnomalyEvent.severity, func.count(AnomalyEvent.id))
                    .where(AnomalyEvent.timestamp >= start_time)
                    .group_by(AnomalyEvent.severity)
                )
                for sev, cnt in session.execute(count_stmt):
                    if sev == "warning":
                        counts["warning"] += cnt
                    elif sev == "critical":
                        counts["critical"] += cnt
                    counts["total"] += cnt

                breakdown_stmt = (
                    select(
                        AnomalyEvent.resource,
                        AnomalyEvent.severity,
                        func.count(AnomalyEvent.id),
                    )
                    .where(AnomalyEvent.timestamp >= start_time)
                    .group_by(AnomalyEvent.resource, AnomalyEvent.severity)
                )

                breakdown_dict: dict[str, dict[str, int]] = {}
                for res, sev, cnt in session.execute(breakdown_stmt):
                    if res not in breakdown_dict:
                        breakdown_dict[res] = {"total": 0, "warning": 0, "critical": 0}
                    if sev in breakdown_dict[res]:
                        breakdown_dict[res][sev] += cnt
                    breakdown_dict[res]["total"] += cnt

                breakdown_list = [
                    {"resource": r, **breakdown_dict[r]} for r in sorted(breakdown_dict.keys())
                ]

                # Recent anomaly events
                recent_stmt = (
                    select(AnomalyEvent)
                    .where(AnomalyEvent.timestamp >= start_time)
                    .order_by(AnomalyEvent.timestamp.desc())
                    .limit(20)
                )
                recent_anomalies = list(session.scalars(recent_stmt))

                return counts, breakdown_list, recent_anomalies
        except SQLAlchemyError as exc:
            logger.exception("Failed to query anomaly events for report")
            raise exc

    def collect_report_data(self, range_key: str = "24h") -> dict[str, Any]:
        """Aggregate all diagnostic telemetry sections safely."""
        range_seconds = SUPPORTED_REPORT_RANGES.get(range_key, 24 * 3600)
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(seconds=range_seconds)

        sys_info = get_system_info()
        cpu_curr = get_cpu_info()
        mem_curr = get_memory_info()
        disk_curr = get_disk_info()
        net_curr = get_network_info()
        hist_stats = self.collect_historical_aggregates(start_time)
        timeseries_records = self.collect_historical_records(start_time)

        # Process Monitoring (Security: only PID, Name, CPU, Mem, Status - NO CMDLINE / ENV)
        proc_resp = get_processes(limit=100)
        all_procs = getattr(proc_resp, "processes", [])
        top_cpu = getattr(proc_resp, "top_cpu_processes", [])[:5]
        if not top_cpu and all_procs:
            top_cpu = sorted(all_procs, key=lambda p: (p.cpu_percent or 0.0), reverse=True)[:5]
        top_mem = getattr(proc_resp, "top_ram_processes", [])[:5]
        if not top_mem and all_procs:
            top_mem = sorted(all_procs, key=lambda p: (p.memory_percent or 0.0), reverse=True)[:5]

        alert_counts, recent_alerts = self.collect_alerts_data(start_time)
        gpu_curr = get_gpu_info()
        battery_curr = get_battery_info()
        temperature_curr = get_temperature_info()
        anomaly_counts, anomaly_breakdown, recent_anomalies = self.collect_anomaly_data(start_time)

        # Predictions & Accuracy
        try:
            preds_15m = prediction_service.get_predictions(horizon="15m", auto_record=False)
            preds_list = preds_15m.predictions
        except Exception:
            logger.debug("Prediction retrieval fallback for report")
            preds_list = []

        try:
            accuracy_data = prediction_service.get_accuracy(time_range=range_key)
        except Exception:
            logger.debug("Accuracy retrieval fallback for report")
            accuracy_data = None

        return {
            "generated_at": now,
            "range_key": range_key,
            "range_seconds": range_seconds,
            "start_time": start_time,
            "system": sys_info,
            "cpu": cpu_curr,
            "memory": mem_curr,
            "disk": disk_curr,
            "network": net_curr,
            "historical_stats": hist_stats,
            "timeseries_records": timeseries_records,
            "top_cpu_processes": top_cpu,
            "top_mem_processes": top_mem,
            "alert_counts": alert_counts,
            "recent_alerts": recent_alerts,
            "gpu": gpu_curr,
            "battery": battery_curr,
            "temperature": temperature_curr,
            "anomaly_counts": anomaly_counts,
            "anomaly_breakdown": anomaly_breakdown,
            "recent_anomalies": recent_anomalies,
            "predictions": preds_list,
            "accuracy": accuracy_data,
        }

    def generate_pdf_report(
        self,
        range_key: str = "24h",
        report_type: str = "all",
        resource_filter: str | None = None,
    ) -> tuple[bytes, str]:
        """Compile complete or specialized PDF report with embedded charts and return (pdf_bytes, filename)."""
        with self._lock:
            return self._generate_pdf_report_locked(
                range_key=range_key,
                report_type=report_type,
                resource_filter=resource_filter,
            )

    def _generate_pdf_report_locked(
        self,
        range_key: str = "24h",
        report_type: str = "all",
        resource_filter: str | None = None,
    ) -> tuple[bytes, str]:
        if range_key not in SUPPORTED_REPORT_RANGES:
            raise ValueError(
                f"Invalid date range: '{range_key}'. "
                f"Supported ranges: {', '.join(SUPPORTED_REPORT_RANGES.keys())}"
            )

        # Handle backward-compatible resource_filter or map to report_type
        if resource_filter and resource_filter != "all" and report_type == "all":
            if resource_filter in ["cpu", "memory"]:
                report_type = "cpu_memory"
            elif resource_filter in ["disk", "network"]:
                report_type = "disk_network"

        if report_type not in SUPPORTED_REPORT_TYPES:
            raise ValueError(
                f"Invalid report type: '{report_type}'. "
                f"Supported types: {', '.join(SUPPORTED_REPORT_TYPES.keys())}"
            )

        data = self.collect_report_data(range_key)
        now_str = data["generated_at"].strftime("%Y%m%d_%H%M%S")
        
        # Maintain clear filename adhering to testing patterns
        if report_type == "all":
            filename = f"system_resource_report_{range_key}_{now_str}.pdf"
        else:
            filename = f"system_resource_report_{range_key}_{report_type}_{now_str}.pdf"

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=40,
            rightMargin=40,
            topMargin=46,
            bottomMargin=42,
            pageCompression=0,
        )

        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "DocSubTitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=8,
        )
        h1_style = ParagraphStyle(
            "SectionH1",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=15,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=10,
            spaceAfter=4,
            keepWithNext=True,
        )
        body_style = ParagraphStyle(
            "DocBody",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1e293b"),
        )
        bold_style = ParagraphStyle(
            "DocBold",
            parent=body_style,
            fontName="Helvetica-Bold",
        )
        muted_style = ParagraphStyle(
            "DocMuted",
            parent=body_style,
            textColor=colors.HexColor("#64748b"),
        )
        th_style = ParagraphStyle(
            "DocTH",
            parent=body_style,
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#ffffff"),
        )
        badge_style = ParagraphStyle(
            "BadgeStyle",
            parent=body_style,
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            alignment=1,  # Center
        )

        chart_gen = ReportChartGenerator()
        story: list[Any] = []

        try:
            # ---------------------------------------------------------------
            # Header & Document Title Banner
            # ---------------------------------------------------------------
            report_title_text = f"System Resource Monitor — {SUPPORTED_REPORT_TYPES[report_type]}"
            story.append(Paragraph(report_title_text, title_style))
            period_text = RANGE_LABELS.get(range_key, range_key)
            gen_text = _format_dt(data["generated_at"])
            sys_obj = data["system"]
            banner_sub = (
                f"<b>Reporting Window:</b> {period_text} &nbsp;|&nbsp; "
                f"<b>Generated:</b> {gen_text} &nbsp;|&nbsp; "
                f"<b>Host:</b> {sys_obj.hostname} ({sys_obj.operating_system})"
            )
            story.append(Paragraph(banner_sub, subtitle_style))
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=1,
                    color=colors.HexColor("#cbd5e1"),
                    spaceBefore=0,
                    spaceAfter=8,
                )
            )

            # ---------------------------------------------------------------
            # Executive Summary (Included at beginning of report)
            # ---------------------------------------------------------------
            story.append(Paragraph("Executive Summary", h1_style))
            
            # Determine overall health status
            alerts_cnt = data["alert_counts"]
            anom_cnt = data["anomaly_counts"]
            cpu_avg = data["historical_stats"]["cpu_avg"]
            ram_avg = data["historical_stats"]["ram_avg"]
            
            if alerts_cnt["critical"] > 0 or anom_cnt["critical"] > 0:
                health_status = "CRITICAL ATTENTION REQUIRED"
                status_color = "#b91c1c"
                status_bg = "#fee2e2"
                health_desc = (
                    f"System recorded {alerts_cnt['critical']} critical alerts and {anom_cnt['critical']} critical anomalies "
                    f"during this {period_text.lower()} window. Immediate administrator remediation is advised."
                )
            elif alerts_cnt["warning"] > 0 or anom_cnt["warning"] > 0 or (cpu_avg and cpu_avg > 75) or (ram_avg and ram_avg > 80):
                health_status = "WARNING — ELEVATED WORKLOAD"
                status_color = "#b45309"
                status_bg = "#fef3c7"
                health_desc = (
                    f"System recorded {alerts_cnt['warning']} warning alerts and {anom_cnt['warning']} warning anomalies. "
                    f"Workload demands were elevated but within survivable margins."
                )
            else:
                health_status = "OPTIMAL & HEALTHY"
                status_color = "#047857"
                status_bg = "#d1fae5"
                health_desc = (
                    f"All monitored subsystems operated stably without threshold violations or severe statistical anomalies "
                    f"across the {period_text.lower()} reporting window."
                )

            # Executive KPI Table
            io_avg_str = _format_rate(data["historical_stats"]["disk_read_avg"])
            net_avg_str = _format_rate(data["historical_stats"]["net_down_avg"])
            acc_obj = data["accuracy"]
            acc_summary_val = (
                f"MAE: {acc_obj.overall.mae:.2f}"
                if acc_obj and acc_obj.overall and acc_obj.overall.evaluated_count > 0 and acc_obj.overall.mae is not None
                else "Active / Awaiting Horizon"
            )

            summary_rows = [
                [
                    Paragraph(f"<b>Overall System Status:</b> <font color='{status_color}'><b>{health_status}</b></font>", body_style),
                    Paragraph(f"<b>Avg CPU Load:</b> {_format_percent(cpu_avg)}", body_style),
                    Paragraph(f"<b>Avg RAM Load:</b> {_format_percent(ram_avg)}", body_style),
                ],
                [
                    Paragraph(f"<b>Disk Read Avg:</b> {io_avg_str}", body_style),
                    Paragraph(f"<b>Network Down Avg:</b> {net_avg_str}", body_style),
                    Paragraph(f"<b>Forecast Evaluation:</b> {acc_summary_val}", body_style),
                ],
                [
                    Paragraph(f"<b>Total Alert Events:</b> {alerts_cnt['total']} ({alerts_cnt['critical']} crit, {alerts_cnt['warning']} warn)", body_style),
                    Paragraph(f"<b>Total Anomalies:</b> {anom_cnt['total']} ({anom_cnt['critical']} crit, {anom_cnt['warning']} warn)", body_style),
                    Paragraph(f"<b>Telemetry Samples:</b> {data['historical_stats']['sample_count']}", body_style),
                ],
            ]
            t_exec = Table(summary_rows, colWidths=[180, 176, 176])
            t_exec.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(t_exec)
            story.append(Paragraph(f"<font color='#64748b'><i>Summary Note: {health_desc}</i></font>", body_style))
            story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 1. System Information
            # ---------------------------------------------------------------
            story.append(Paragraph("1. System Information", h1_style))
            sys_rows = [
                [
                    Paragraph("<b>Operating System:</b>", body_style),
                    Paragraph(f"{sys_obj.operating_system} {sys_obj.os_release or ''}", body_style),
                    Paragraph("<b>Architecture:</b>", body_style),
                    Paragraph(f"{sys_obj.architecture} ({sys_obj.cpu_architecture})", body_style),
                ],
                [
                    Paragraph("<b>Hostname / Node:</b>", body_style),
                    Paragraph(f"{sys_obj.hostname}", body_style),
                    Paragraph("<b>System Uptime:</b>", body_style),
                    Paragraph(f"{sys_obj.uptime_readable or '—'}", body_style),
                ],
                [
                    Paragraph("<b>Processor:</b>", body_style),
                    Paragraph(f"{sys_obj.processor or 'Standard CPU'}", body_style),
                    Paragraph("<b>Cores:</b>", body_style),
                    Paragraph(f"{sys_obj.physical_cores or '—'} Physical, {sys_obj.logical_cores or '—'} Logical", body_style),
                ],
                [
                    Paragraph("<b>Total Memory:</b>", body_style),
                    Paragraph(f"{_format_bytes(data['memory'].total_bytes)}", body_style),
                    Paragraph("<b>Boot Timestamp:</b>", body_style),
                    Paragraph(f"{_format_dt(sys_obj.boot_time)}", body_style),
                ],
            ]
            t_sys = Table(sys_rows, colWidths=[100, 166, 100, 166])
            t_sys.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(t_sys)
            story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 2. CPU Monitoring
            # ---------------------------------------------------------------
            if report_type in ["all", "cpu_memory"]:
                story.append(Paragraph("2. CPU Monitoring & Utilization", h1_style))
                cpu_curr = data["cpu"]
                hist = data["historical_stats"]
                cpu_rows = [
                    [
                        Paragraph("Metric", th_style),
                        Paragraph("Current", th_style),
                        Paragraph("Historical Min", th_style),
                        Paragraph("Historical Average", th_style),
                        Paragraph("Historical Max", th_style),
                        Paragraph("Samples", th_style),
                    ],
                    [
                        Paragraph("CPU Utilization", bold_style),
                        Paragraph(_format_percent(cpu_curr.cpu_usage_percent), body_style),
                        Paragraph(_format_percent(hist["cpu_min"]), body_style),
                        Paragraph(_format_percent(hist["cpu_avg"]), body_style),
                        Paragraph(_format_percent(hist["cpu_max"]), body_style),
                        Paragraph(str(hist["sample_count"]), body_style),
                    ],
                ]
                t_cpu = Table(cpu_rows, colWidths=[120, 80, 80, 90, 80, 82])
                t_cpu.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(t_cpu)
                story.append(Spacer(1, 4))
                # CPU Chart
                cpu_chart = chart_gen.chart_cpu_utilization(
                    data["timeseries_records"], data["start_time"], data["generated_at"]
                )
                story.append(cpu_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 3. Memory Monitoring
            # ---------------------------------------------------------------
            if report_type in ["all", "cpu_memory"]:
                story.append(Paragraph("3. Memory Monitoring & Allocation", h1_style))
                mem = data["memory"]
                hist = data["historical_stats"]
                mem_rows = [
                    [
                        Paragraph("Total RAM", th_style),
                        Paragraph("Used RAM", th_style),
                        Paragraph("Available RAM", th_style),
                        Paragraph("Utilization", th_style),
                        Paragraph("Historical Min", th_style),
                        Paragraph("Historical Avg", th_style),
                        Paragraph("Historical Max", th_style),
                    ],
                    [
                        Paragraph(_format_bytes(mem.total_bytes), body_style),
                        Paragraph(_format_bytes(mem.used_bytes), body_style),
                        Paragraph(_format_bytes(mem.available_bytes), body_style),
                        Paragraph(_format_percent(mem.usage_percent), bold_style),
                        Paragraph(_format_percent(hist["ram_min"]), body_style),
                        Paragraph(_format_percent(hist["ram_avg"]), body_style),
                        Paragraph(_format_percent(hist["ram_max"]), body_style),
                    ],
                ]
                t_mem = Table(mem_rows, colWidths=[76, 76, 76, 76, 76, 76, 76])
                t_mem.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(t_mem)
                story.append(Spacer(1, 4))
                # Memory Chart
                mem_chart = chart_gen.chart_memory_utilization(
                    data["timeseries_records"], data["start_time"], data["generated_at"]
                )
                story.append(mem_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 4. Disk Monitoring
            # ---------------------------------------------------------------
            if report_type in ["all", "disk_network"]:
                story.append(Paragraph("4. Disk Storage & I/O Throughput", h1_style))
                disk_partitions = data["disk"].partitions or []
                disk_rows = [
                    [
                        Paragraph("Device", th_style),
                        Paragraph("Mountpoint", th_style),
                        Paragraph("Filesystem", th_style),
                        Paragraph("Total", th_style),
                        Paragraph("Used", th_style),
                        Paragraph("Free", th_style),
                        Paragraph("Usage %", th_style),
                    ]
                ]
                for part in disk_partitions[:5]:
                    fs = getattr(part, "filesystem", None) or getattr(part, "filesystem_type", "—")
                    disk_rows.append(
                        [
                            Paragraph(str(part.device or "—"), body_style),
                            Paragraph(str(part.mountpoint or "—"), body_style),
                            Paragraph(str(fs or "—"), body_style),
                            Paragraph(_format_bytes(part.total_bytes), body_style),
                            Paragraph(_format_bytes(part.used_bytes), body_style),
                            Paragraph(_format_bytes(part.free_bytes), body_style),
                            Paragraph(_format_percent(part.usage_percent), bold_style),
                        ]
                    )
                if len(disk_rows) == 1:
                    disk_rows.append([Paragraph("No disk partition telemetry available", muted_style)] + [Paragraph("—", body_style)] * 6)

                t_disk = Table(disk_rows, colWidths=[90, 82, 70, 75, 75, 75, 65])
                t_disk.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(t_disk)
                story.append(Spacer(1, 4))
                
                # Disk Charts: Utilization & I/O throughput
                disk_util_chart = chart_gen.chart_disk_utilization(
                    data["timeseries_records"], data["start_time"], data["generated_at"]
                )
                story.append(disk_util_chart)
                story.append(Spacer(1, 4))
                disk_io_chart = chart_gen.chart_disk_io_throughput(
                    data["timeseries_records"], data["start_time"], data["generated_at"]
                )
                story.append(disk_io_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 5. Network Monitoring
            # ---------------------------------------------------------------
            if report_type in ["all", "disk_network"]:
                story.append(Paragraph("5. Network Interfaces & Throughput", h1_style))
                net = data["network"]
                hist = data["historical_stats"]
                net_rows = [
                    [
                        Paragraph("Direction", th_style),
                        Paragraph("Current Speed", th_style),
                        Paragraph("Historical Average", th_style),
                        Paragraph("Peak Throughput", th_style),
                        Paragraph("Total Transferred", th_style),
                    ],
                    [
                        Paragraph("Download (Incoming)", bold_style),
                        Paragraph(_format_rate(net.download_speed_bytes_per_sec), body_style),
                        Paragraph(_format_rate(hist.get("net_down_avg")), body_style),
                        Paragraph(_format_rate(hist.get("net_down_max")), body_style),
                        Paragraph(_format_bytes(net.bytes_received), body_style),
                    ],
                    [
                        Paragraph("Upload (Outgoing)", bold_style),
                        Paragraph(_format_rate(net.upload_speed_bytes_per_sec), body_style),
                        Paragraph(_format_rate(hist.get("net_up_avg")), body_style),
                        Paragraph(_format_rate(hist.get("net_up_max")), body_style),
                        Paragraph(_format_bytes(net.bytes_sent), body_style),
                    ],
                ]
                t_net = Table(net_rows, colWidths=[130, 100, 105, 105, 92])
                t_net.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ]
                    )
                )
                story.append(t_net)
                story.append(Spacer(1, 4))
                # Network Chart
                net_chart = chart_gen.chart_network_throughput(
                    data["timeseries_records"], data["start_time"], data["generated_at"]
                )
                story.append(net_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 6. Process Monitoring (Strict Security: No CMDLINE / No ENV)
            # ---------------------------------------------------------------
            if report_type in ["all", "cpu_memory", "process_resource"]:
                story.append(Paragraph("6. Process Monitoring (Top Resource Consumers)", h1_style))
                proc_rows = [
                    [
                        Paragraph("Category", th_style),
                        Paragraph("PID", th_style),
                        Paragraph("Process Name", th_style),
                        Paragraph("Status", th_style),
                        Paragraph("CPU %", th_style),
                        Paragraph("Memory %", th_style),
                        Paragraph("Memory (MB)", th_style),
                    ]
                ]
                num_procs = 5 if report_type == "process_resource" else 3
                for p in data["top_cpu_processes"][:num_procs]:
                    mem_mb_str = f"{p.memory_mb:.1f}" if p.memory_mb is not None else "—"
                    proc_rows.append(
                        [
                            Paragraph("Top CPU", bold_style),
                            Paragraph(str(p.pid), body_style),
                            Paragraph(str(p.name or "—"), body_style),
                            Paragraph(str(p.status or "—"), body_style),
                            Paragraph(_format_percent(p.cpu_percent), bold_style),
                            Paragraph(_format_percent(p.memory_percent), body_style),
                            Paragraph(mem_mb_str, body_style),
                        ]
                    )
                for p in data["top_mem_processes"][:num_procs]:
                    mem_mb_str = f"{p.memory_mb:.1f}" if p.memory_mb is not None else "—"
                    proc_rows.append(
                        [
                            Paragraph("Top Memory", bold_style),
                            Paragraph(str(p.pid), body_style),
                            Paragraph(str(p.name or "—"), body_style),
                            Paragraph(str(p.status or "—"), body_style),
                            Paragraph(_format_percent(p.cpu_percent), body_style),
                            Paragraph(_format_percent(p.memory_percent), bold_style),
                            Paragraph(mem_mb_str, body_style),
                        ]
                    )
                if len(proc_rows) == 1:
                    proc_rows.append([Paragraph("No process telemetry available", muted_style)] + [Paragraph("—", body_style)] * 6)

                t_proc = Table(proc_rows, colWidths=[70, 45, 140, 65, 65, 70, 77])
                t_proc.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                        ]
                    )
                )
                story.append(t_proc)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 7. Resource Alerts
            # ---------------------------------------------------------------
            if report_type in ["all", "alerts_anomaly"]:
                story.append(Paragraph("7. Resource Alerts & Threshold Breaches", h1_style))
                ac = data["alert_counts"]
                recent_alerts = data["recent_alerts"]
                alert_summary_text = (
                    f"<b>Alert Summary:</b> Total Events: <b>{ac['total']}</b> &nbsp;|&nbsp; "
                    f"Warnings: <font color='#b45309'><b>{ac['warning']}</b></font> &nbsp;|&nbsp; "
                    f"Critical: <font color='#b91c1c'><b>{ac['critical']}</b></font>"
                )
                story.append(Paragraph(alert_summary_text, body_style))
                story.append(Spacer(1, 3))

                alert_rows = [
                    [
                        Paragraph("Timestamp", th_style),
                        Paragraph("Resource", th_style),
                        Paragraph("Severity", th_style),
                        Paragraph("Alert Message", th_style),
                    ]
                ]
                for a in recent_alerts[:5]:
                    sev_color = "#b91c1c" if a.severity == "critical" else "#b45309"
                    alert_rows.append(
                        [
                            Paragraph(_format_dt(a.timestamp), body_style),
                            Paragraph(a.resource.upper(), bold_style),
                            Paragraph(f"<font color='{sev_color}'><b>{a.severity.upper()}</b></font>", body_style),
                            Paragraph(a.message, body_style),
                        ]
                    )
                if len(alert_rows) == 1:
                    alert_rows.append(
                        [
                            Paragraph("No resource alerts triggered during this time period.", muted_style),
                            Paragraph("—", body_style),
                            Paragraph("—", body_style),
                            Paragraph("System operated within configured thresholds.", muted_style),
                        ]
                    )

                t_alerts = Table(alert_rows, colWidths=[110, 65, 65, 292])
                t_alerts.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                        ]
                    )
                )
                story.append(t_alerts)
                story.append(Spacer(1, 4))
                # Alert History Chart
                alert_chart = chart_gen.chart_alert_history(ac, recent_alerts)
                story.append(alert_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 8. GPU Monitoring (Only in Complete report)
            # ---------------------------------------------------------------
            if report_type == "all":
                story.append(Paragraph("8. GPU Hardware Telemetry", h1_style))
                gpu = data["gpu"]
                if gpu.supported_gpu_detected and gpu.devices:
                    gpu_rows = [
                        [
                            Paragraph("Device Index", th_style),
                            Paragraph("Manufacturer", th_style),
                            Paragraph("Model", th_style),
                            Paragraph("Driver", th_style),
                            Paragraph("Memory Total", th_style),
                            Paragraph("Capability", th_style),
                        ]
                    ]
                    for d in gpu.devices:
                        gpu_rows.append(
                            [
                                Paragraph(f"GPU {d.device_index}", bold_style),
                                Paragraph(str(d.manufacturer or "—"), body_style),
                                Paragraph(str(d.model or "Dedicated Adapter"), body_style),
                                Paragraph(str(d.driver_version or "—"), body_style),
                                Paragraph(_format_bytes(d.total_memory_bytes), body_style),
                                Paragraph("Telemetry Active" if d.monitoring_supported else "Detected", body_style),
                            ]
                        )
                    t_gpu = Table(gpu_rows, colWidths=[65, 85, 140, 80, 80, 82])
                    t_gpu.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                                ("TOPPADDING", (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ]
                        )
                    )
                    story.append(t_gpu)
                else:
                    story.append(
                        Paragraph(
                            "<font color='#64748b'><i>GPU monitoring unavailable: No compatible dedicated GPU detected or NVML telemetry unsupported on this host platform.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 9. Battery Monitoring (Only in Complete report)
            # ---------------------------------------------------------------
            if report_type == "all":
                story.append(Paragraph("9. Battery & Power Telemetry", h1_style))
                bat = data["battery"]
                if bat.availability == "available":
                    plugged_text = "Yes (AC Connected)" if bat.power_plugged else "No (On Battery)"
                    bat_text = (
                        f"<b>Battery Status:</b> Charge Level: <b>{_format_percent(bat.percentage)}</b> &nbsp;|&nbsp; "
                        f"State: <b>{str(bat.charging_state).capitalize()}</b> &nbsp;|&nbsp; "
                        f"External Power: <b>{plugged_text}</b>"
                    )
                    story.append(Paragraph(bat_text, body_style))
                else:
                    story.append(
                        Paragraph(
                            "<font color='#64748b'><i>Battery monitoring not present: Host system operates on stationary power or does not expose hardware battery telemetry.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 10. Temperature Monitoring (Only in Complete report)
            # ---------------------------------------------------------------
            if report_type == "all":
                story.append(Paragraph("10. Temperature Sensor Telemetry", h1_style))
                temp = data["temperature"]
                if temp.availability == "available" and temp.sensors:
                    temp_rows = [
                        [
                            Paragraph("Sensor ID", th_style),
                            Paragraph("Sensor Name", th_style),
                            Paragraph("Label", th_style),
                            Paragraph("Temperature (°C)", th_style),
                        ]
                    ]
                    for s in temp.sensors[:6]:
                        temp_rows.append(
                            [
                                Paragraph(str(s.sensor_id or "—"), body_style),
                                Paragraph(str(s.sensor_name or "—"), bold_style),
                                Paragraph(str(s.sensor_label or "Core"), body_style),
                                Paragraph(f"{s.current_celsius:.1f} °C" if s.current_celsius is not None else "—", bold_style),
                            ]
                        )
                    t_temp = Table(temp_rows, colWidths=[140, 140, 130, 122])
                    t_temp.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ]
                        )
                    )
                    story.append(t_temp)
                else:
                    story.append(
                        Paragraph(
                            "<font color='#64748b'><i>Temperature sensor monitoring unsupported or unavailable on this host platform.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 11. Anomaly Detection
            # ---------------------------------------------------------------
            if report_type in ["all", "alerts_anomaly"]:
                story.append(Paragraph("11. Anomaly Detection (Statistical Z-Score Analysis)", h1_style))
                anc = data["anomaly_counts"]
                story.append(
                    Paragraph(
                        f"<b>Anomaly Summary:</b> Total Events: <b>{anc['total']}</b> &nbsp;|&nbsp; "
                        f"Warnings: <font color='#b45309'><b>{anc['warning']}</b></font> &nbsp;|&nbsp; "
                        f"Critical: <font color='#b91c1c'><b>{anc['critical']}</b></font>",
                        body_style,
                    )
                )
                story.append(Spacer(1, 3))
                bd = data["anomaly_breakdown"]
                if bd:
                    anom_rows = [
                        [
                            Paragraph("Resource Category", th_style),
                            Paragraph("Total Anomalies", th_style),
                            Paragraph("Warnings", th_style),
                            Paragraph("Critical Events", th_style),
                        ]
                    ]
                    for row in bd:
                        anom_rows.append(
                            [
                                Paragraph(row["resource"].upper(), bold_style),
                                Paragraph(str(row["total"]), body_style),
                                Paragraph(str(row["warning"]), body_style),
                                Paragraph(str(row["critical"]), body_style),
                            ]
                        )
                    t_anom = Table(anom_rows, colWidths=[150, 120, 130, 132])
                    t_anom.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ]
                        )
                    )
                    story.append(t_anom)
                else:
                    story.append(
                        Paragraph(
                            "<font color='#64748b'><i>No resource utilization anomalies recorded within this reporting window. Telemetry exhibited normal variance.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 4))
                # Anomaly Charts: Frequency Timeline & Resource Distribution
                anom_freq_chart = chart_gen.chart_anomaly_frequency(
                    data["recent_anomalies"], data["start_time"], data["generated_at"]
                )
                story.append(anom_freq_chart)
                story.append(Spacer(1, 4))
                anom_dist_chart = chart_gen.chart_anomaly_distribution(bd)
                story.append(anom_dist_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 12. Resource Prediction
            # ---------------------------------------------------------------
            if report_type in ["all", "prediction_accuracy"]:
                story.append(Paragraph("12. Resource Utilization Prediction", h1_style))
                preds = data["predictions"]
                if preds:
                    pred_rows = [
                        [
                            Paragraph("Resource", th_style),
                            Paragraph("Metric", th_style),
                            Paragraph("Horizon", th_style),
                            Paragraph("Current", th_style),
                            Paragraph("Forecasted", th_style),
                            Paragraph("Trend", th_style),
                            Paragraph("Confidence (R²)", th_style),
                        ]
                    ]
                    for p in preds:
                        is_pct = p.unit == "percent"
                        curr_val = _format_percent(p.current_value) if is_pct else _format_rate(p.current_value)
                        pred_val = _format_percent(p.predicted_value) if is_pct else _format_rate(p.predicted_value)
                        conf_val = f"{int(p.confidence_score * 100)}%" if p.confidence_score is not None else "—"
                        pred_rows.append(
                            [
                                Paragraph(p.resource.upper(), bold_style),
                                Paragraph(p.metric, body_style),
                                Paragraph(p.horizon, body_style),
                                Paragraph(curr_val, body_style),
                                Paragraph(pred_val, bold_style),
                                Paragraph(str(p.trend or "—").capitalize(), body_style),
                                Paragraph(conf_val, body_style),
                            ]
                        )
                    t_pred = Table(pred_rows, colWidths=[65, 115, 50, 75, 75, 75, 77])
                    t_pred.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ]
                        )
                    )
                    story.append(t_pred)
                else:
                    story.append(
                        Paragraph(
                            "<font color='#64748b'><i>Forecasting engine warming up: Accumulating continuous monitoring telemetry for weighted linear regression.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 4))
                # Actual vs Predicted Chart
                pred_chart = chart_gen.chart_actual_vs_predicted(preds)
                story.append(pred_chart)
                story.append(Spacer(1, 6))

            # ---------------------------------------------------------------
            # 13. Prediction Accuracy
            # ---------------------------------------------------------------
            if report_type in ["all", "prediction_accuracy"]:
                story.append(Paragraph("13. Prediction Accuracy & Validation Metrics", h1_style))
                acc = data["accuracy"]
                if acc and acc.overall and acc.overall.evaluated_count > 0:
                    ov = acc.overall
                    mae_str = f"{ov.mae:.2f}" if ov.mae is not None else "—"
                    rmse_str = f"{ov.rmse:.2f}" if ov.rmse is not None else "—"
                    mape_str = f"{ov.mape:.2f}%" if ov.mape is not None else "—"
                    acc_summary_text = (
                        f"<b>Accuracy Summary:</b> Evaluated Forecasts: <b>{ov.evaluated_count}</b> &nbsp;|&nbsp; "
                        f"Pending: <b>{ov.pending_count}</b> &nbsp;|&nbsp; "
                        f"Mean Absolute Error (MAE): <b>{mae_str}</b> &nbsp;|&nbsp; "
                        f"Root Mean Squared Error (RMSE): <b>{rmse_str}</b> &nbsp;|&nbsp; "
                        f"MAPE: <b>{mape_str}</b>"
                    )
                    story.append(Paragraph(acc_summary_text, body_style))
                    story.append(Spacer(1, 3))

                    acc_rows = [
                        [
                            Paragraph("Horizon", th_style),
                            Paragraph("Evaluated", th_style),
                            Paragraph("Pending", th_style),
                            Paragraph("MAE", th_style),
                            Paragraph("RMSE", th_style),
                            Paragraph("MAPE", th_style),
                        ]
                    ]
                    for h in acc.by_horizon:
                        mae_v = f"{h.mae:.2f}" if h.mae is not None else "—"
                        rmse_v = f"{h.rmse:.2f}" if h.rmse is not None else "—"
                        mape_v = f"{h.mape:.2f}%" if h.mape is not None else "—"
                        acc_rows.append(
                            [
                                Paragraph(h.horizon, bold_style),
                                Paragraph(str(h.evaluated_count), body_style),
                                Paragraph(str(h.pending_count), body_style),
                                Paragraph(mae_v, body_style),
                                Paragraph(rmse_v, body_style),
                                Paragraph(mape_v, body_style),
                            ]
                        )
                    t_acc = Table(acc_rows, colWidths=[90, 85, 85, 90, 90, 92])
                    t_acc.setStyle(
                        TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                            ]
                        )
                    )
                    story.append(t_acc)
                else:
                    pending_cnt = acc.overall.pending_count if acc and acc.overall else 0
                    story.append(
                        Paragraph(
                            f"<font color='#64748b'><i>Awaiting evaluated predictions ({pending_cnt} currently pending). Forecast accuracy metrics are calculated once predicted target horizons elapse.</i></font>",
                            body_style,
                        )
                    )
                story.append(Spacer(1, 4))
                # Accuracy Trend Chart
                acc_chart = chart_gen.chart_prediction_error_and_accuracy(acc)
                story.append(acc_chart)

            # Build Document
            doc.build(story, canvasmaker=NumberedCanvas)

        except Exception as exc:
            logger.exception("ReportLab PDF document compilation failed")
            raise ReportGenerationError("PDF compilation failed") from exc
        finally:
            chart_gen.close()

        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes, filename


report_service = ReportService()
