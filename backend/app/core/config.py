"""Application configuration loaded from environment variables."""

import os
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MIN_MONITORING_INTERVAL_SECONDS = 0.25
MIN_WEBSOCKET_PUBLISH_INTERVAL_SECONDS = 0.1
DEFAULT_CPU_ALERT_WARNING_THRESHOLD_PERCENT = 80.0
DEFAULT_CPU_ALERT_CRITICAL_THRESHOLD_PERCENT = 90.0
DEFAULT_RAM_ALERT_WARNING_THRESHOLD_PERCENT = 80.0
DEFAULT_RAM_ALERT_CRITICAL_THRESHOLD_PERCENT = 90.0
DEFAULT_DISK_ALERT_WARNING_THRESHOLD_PERCENT = 80.0
DEFAULT_DISK_ALERT_CRITICAL_THRESHOLD_PERCENT = 90.0
DEFAULT_TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS = 80.0
DEFAULT_TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS = 90.0
DEFAULT_BATTERY_ALERT_WARNING_THRESHOLD_PERCENT = 20.0
DEFAULT_BATTERY_ALERT_CRITICAL_THRESHOLD_PERCENT = 10.0
DEFAULT_ANOMALY_DETECTION_ENABLED = True
DEFAULT_ANOMALY_MIN_SAMPLES = 20
DEFAULT_ANOMALY_Z_SCORE_THRESHOLD = 3.0
DEFAULT_ANOMALY_WINDOW_SIZE = 60


def _application_data_directory() -> Path:
    """Choose a dedicated, platform-appropriate directory for application data."""
    configured_directory = os.getenv("APP_DATA_DIR")
    if configured_directory:
        return Path(configured_directory).expanduser().resolve()

    if os.name == "nt":
        base_directory = os.getenv("LOCALAPPDATA")
        if base_directory:
            return (Path(base_directory) / "SystemResourceMonitor").resolve()
        return (Path.home() / "AppData" / "Local" / "SystemResourceMonitor").resolve()

    base_directory = os.getenv("XDG_DATA_HOME")
    if base_directory:
        return (Path(base_directory) / "system-resource-monitor").resolve()
    return (Path.home() / ".local" / "share" / "system-resource-monitor").resolve()


def _monitoring_interval_from_environment() -> float:
    """Read and validate the background sampling interval."""
    raw_value = os.getenv("MONITORING_INTERVAL_SECONDS", "1")
    try:
        interval = float(raw_value)
    except ValueError as exc:
        raise ValueError("MONITORING_INTERVAL_SECONDS must be a number") from exc
    if not math.isfinite(interval) or interval < MIN_MONITORING_INTERVAL_SECONDS:
        raise ValueError(
            "MONITORING_INTERVAL_SECONDS must be finite and at least "
            f"{MIN_MONITORING_INTERVAL_SECONDS}"
        )
    return interval


def _websocket_publish_interval_from_environment() -> float:
    """Read and validate the WebSocket snapshot publishing interval."""
    raw_value = os.getenv("WEBSOCKET_PUBLISH_INTERVAL_SECONDS", "1")
    try:
        interval = float(raw_value)
    except ValueError as exc:
        raise ValueError(
            "WEBSOCKET_PUBLISH_INTERVAL_SECONDS must be a number"
        ) from exc
    if not math.isfinite(interval) or interval < MIN_WEBSOCKET_PUBLISH_INTERVAL_SECONDS:
        raise ValueError(
            "WEBSOCKET_PUBLISH_INTERVAL_SECONDS must be finite and at least "
            f"{MIN_WEBSOCKET_PUBLISH_INTERVAL_SECONDS}"
        )
    return interval


def _history_retention_days_from_environment() -> int:
    """Read and validate the historical record retention period."""
    raw_value = os.getenv("HISTORY_RETENTION_DAYS", "30")
    try:
        retention_days = int(raw_value)
    except ValueError as exc:
        raise ValueError("HISTORY_RETENTION_DAYS must be a positive integer") from exc
    if retention_days <= 0:
        raise ValueError("HISTORY_RETENTION_DAYS must be a positive integer")
    return retention_days


def _alert_thresholds_from_environment(
    resource: str,
    default_warning: float,
    default_critical: float,
) -> tuple[float, float]:
    """Read one resource's alert levels and ensure warning precedes critical."""
    resource_name = resource.upper()
    warning_value = os.getenv(
        f"{resource_name}_ALERT_WARNING_THRESHOLD_PERCENT",
        str(default_warning),
    )
    critical_value = os.getenv(
        f"{resource_name}_ALERT_CRITICAL_THRESHOLD_PERCENT",
        str(default_critical),
    )
    try:
        warning = float(warning_value)
        critical = float(critical_value)
    except ValueError as exc:
        raise ValueError(f"{resource_name} alert thresholds must be numbers") from exc
    if not (
        math.isfinite(warning)
        and math.isfinite(critical)
        and 1 <= warning < critical <= 100
    ):
        raise ValueError(
            f"{resource_name} alert thresholds must satisfy "
            "1 <= warning < critical <= 100"
        )
    return warning, critical


def _temperature_alert_thresholds_from_environment() -> tuple[float, float]:
    warning_value = os.getenv(
        "TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS",
        str(DEFAULT_TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS),
    )
    critical_value = os.getenv(
        "TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS",
        str(DEFAULT_TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS),
    )
    try:
        warning = float(warning_value)
        critical = float(critical_value)
    except ValueError as exc:
        raise ValueError("Temperature alert thresholds must be numbers") from exc
    if not (
        math.isfinite(warning)
        and math.isfinite(critical)
        and 0 <= warning < critical
    ):
        raise ValueError(
            "Temperature alert thresholds must be finite, non-negative, "
            "and warning must be lower than critical"
        )
    return warning, critical


def _battery_alert_thresholds_from_environment() -> tuple[float, float]:
    warning_value = os.getenv(
        "BATTERY_ALERT_WARNING_THRESHOLD_PERCENT",
        str(DEFAULT_BATTERY_ALERT_WARNING_THRESHOLD_PERCENT),
    )
    critical_value = os.getenv(
        "BATTERY_ALERT_CRITICAL_THRESHOLD_PERCENT",
        str(DEFAULT_BATTERY_ALERT_CRITICAL_THRESHOLD_PERCENT),
    )
    try:
        warning = float(warning_value)
        critical = float(critical_value)
    except ValueError as exc:
        raise ValueError("Battery alert thresholds must be numbers") from exc
    if not (
        math.isfinite(warning)
        and math.isfinite(critical)
        and 0 <= critical < warning <= 100
    ):
        raise ValueError(
            "Battery alert thresholds must satisfy 0 <= critical < warning <= 100"
        )
    return warning, critical


def _cpu_alert_thresholds_from_environment() -> tuple[float, float]:
    """Read CPU alert levels and ensure warning precedes critical."""
    return _alert_thresholds_from_environment(
        "CPU",
        DEFAULT_CPU_ALERT_WARNING_THRESHOLD_PERCENT,
        DEFAULT_CPU_ALERT_CRITICAL_THRESHOLD_PERCENT,
    )


def _ram_alert_thresholds_from_environment() -> tuple[float, float]:
    """Read RAM alert levels and ensure warning precedes critical."""
    return _alert_thresholds_from_environment(
        "RAM",
        DEFAULT_RAM_ALERT_WARNING_THRESHOLD_PERCENT,
        DEFAULT_RAM_ALERT_CRITICAL_THRESHOLD_PERCENT,
    )


def _disk_alert_thresholds_from_environment() -> tuple[float, float]:
    """Read disk alert levels and ensure warning precedes critical."""
    return _alert_thresholds_from_environment(
        "DISK",
        DEFAULT_DISK_ALERT_WARNING_THRESHOLD_PERCENT,
        DEFAULT_DISK_ALERT_CRITICAL_THRESHOLD_PERCENT,
    )


def _anomaly_settings_from_environment() -> tuple[bool, int, float, int]:
    enabled_raw = os.getenv("ANOMALY_DETECTION_ENABLED", "true").lower()
    enabled = enabled_raw in ("true", "1", "yes")
    min_samples_raw = os.getenv(
        "ANOMALY_MIN_SAMPLES", str(DEFAULT_ANOMALY_MIN_SAMPLES)
    )
    try:
        min_samples = int(min_samples_raw)
    except ValueError as exc:
        raise ValueError("ANOMALY_MIN_SAMPLES must be an integer") from exc
    z_score_raw = os.getenv(
        "ANOMALY_Z_SCORE_THRESHOLD", str(DEFAULT_ANOMALY_Z_SCORE_THRESHOLD)
    )
    try:
        z_score = float(z_score_raw)
    except ValueError as exc:
        raise ValueError("ANOMALY_Z_SCORE_THRESHOLD must be a number") from exc
    window_size_raw = os.getenv(
        "ANOMALY_WINDOW_SIZE", str(DEFAULT_ANOMALY_WINDOW_SIZE)
    )
    try:
        window_size = int(window_size_raw)
    except ValueError as exc:
        raise ValueError("ANOMALY_WINDOW_SIZE must be an integer") from exc
    if not math.isfinite(z_score) or z_score <= 0:
        raise ValueError("ANOMALY_Z_SCORE_THRESHOLD must be finite and positive")
    if min_samples < 2:
        raise ValueError("ANOMALY_MIN_SAMPLES must be at least 2")
    if window_size < min_samples:
        raise ValueError(
            "ANOMALY_WINDOW_SIZE must be greater than or equal to ANOMALY_MIN_SAMPLES"
        )
    return enabled, min_samples, z_score, window_size


def _cors_allowed_origins_from_environment() -> tuple[str, ...]:
    """Read explicit browser origins allowed to call the API."""
    raw_value = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    origins = tuple(origin.strip() for origin in raw_value.split(",") if origin.strip())
    if not origins or "*" in origins:
        raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit origins")
    return origins


(
    _CPU_ALERT_WARNING_THRESHOLD_PERCENT,
    _CPU_ALERT_CRITICAL_THRESHOLD_PERCENT,
) = _cpu_alert_thresholds_from_environment()
(
    _RAM_ALERT_WARNING_THRESHOLD_PERCENT,
    _RAM_ALERT_CRITICAL_THRESHOLD_PERCENT,
) = _ram_alert_thresholds_from_environment()
(
    _DISK_ALERT_WARNING_THRESHOLD_PERCENT,
    _DISK_ALERT_CRITICAL_THRESHOLD_PERCENT,
) = _disk_alert_thresholds_from_environment()
(
    _TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS,
    _TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS,
) = _temperature_alert_thresholds_from_environment()
(
    _BATTERY_ALERT_WARNING_THRESHOLD_PERCENT,
    _BATTERY_ALERT_CRITICAL_THRESHOLD_PERCENT,
) = _battery_alert_thresholds_from_environment()
(
    _ANOMALY_DETECTION_ENABLED,
    _ANOMALY_MIN_SAMPLES,
    _ANOMALY_Z_SCORE_THRESHOLD,
    _ANOMALY_WINDOW_SIZE,
) = _anomaly_settings_from_environment()


@dataclass(frozen=True)
class Settings:
    """Metadata settings used to configure the FastAPI application."""

    app_title: str = os.getenv("APP_TITLE") or "System Resource Monitor API"
    app_description: str = (
        os.getenv("APP_DESCRIPTION")
        or "Cross-platform system resource monitor backend API"
    )
    app_version: str = os.getenv("APP_VERSION") or "0.1.0"
    monitoring_interval_seconds: float = _monitoring_interval_from_environment()
    websocket_publish_interval_seconds: float = (
        _websocket_publish_interval_from_environment()
    )
    history_retention_days: int = _history_retention_days_from_environment()
    cpu_alert_warning_threshold_percent: float = _CPU_ALERT_WARNING_THRESHOLD_PERCENT
    cpu_alert_critical_threshold_percent: float = _CPU_ALERT_CRITICAL_THRESHOLD_PERCENT
    ram_alert_warning_threshold_percent: float = _RAM_ALERT_WARNING_THRESHOLD_PERCENT
    ram_alert_critical_threshold_percent: float = _RAM_ALERT_CRITICAL_THRESHOLD_PERCENT
    disk_alert_warning_threshold_percent: float = _DISK_ALERT_WARNING_THRESHOLD_PERCENT
    disk_alert_critical_threshold_percent: float = _DISK_ALERT_CRITICAL_THRESHOLD_PERCENT
    temperature_alert_warning_threshold_celsius: float = (
        _TEMPERATURE_ALERT_WARNING_THRESHOLD_CELSIUS
    )
    temperature_alert_critical_threshold_celsius: float = (
        _TEMPERATURE_ALERT_CRITICAL_THRESHOLD_CELSIUS
    )
    battery_alert_warning_threshold_percent: float = (
        _BATTERY_ALERT_WARNING_THRESHOLD_PERCENT
    )
    battery_alert_critical_threshold_percent: float = (
        _BATTERY_ALERT_CRITICAL_THRESHOLD_PERCENT
    )
    anomaly_detection_enabled: bool = _ANOMALY_DETECTION_ENABLED
    anomaly_min_samples: int = _ANOMALY_MIN_SAMPLES
    anomaly_z_score_threshold: float = _ANOMALY_Z_SCORE_THRESHOLD
    anomaly_window_size: int = _ANOMALY_WINDOW_SIZE
    cors_allowed_origins: tuple[str, ...] = _cors_allowed_origins_from_environment()
    app_data_dir: Path = _application_data_directory()

    @property
    def database_path(self) -> Path:
        """Absolute path to the persistent SQLite history database."""
        return self.app_data_dir / "history.sqlite3"


settings = Settings()
