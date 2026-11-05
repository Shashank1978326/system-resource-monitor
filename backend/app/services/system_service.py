"""Collect host system information using Python and psutil."""

import os
import platform
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from app.schemas.monitoring import CpuFrequencyResponse, SystemInfoResponse


def _processor_name() -> str | None:
    """Return a processor model name when the host exposes one."""
    processor = platform.processor().strip()
    if processor:
        return processor

    if platform.system() == "Windows":
        processor = os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
        return processor or None

    if platform.system() == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip().lower() in {"model name", "hardware"}:
                    value = value.strip()
                    if value:
                        return value
        except OSError:
            return None

    return None


def _cpu_frequency() -> CpuFrequencyResponse:
    """Return CPU frequency in MHz, leaving unsupported values null."""
    try:
        frequency = psutil.cpu_freq()
    except (OSError, psutil.Error):
        frequency = None

    if frequency is None:
        return CpuFrequencyResponse(
            current_mhz=None,
            min_mhz=None,
            max_mhz=None,
        )

    return CpuFrequencyResponse(
        current_mhz=frequency.current or None,
        min_mhz=frequency.min or None,
        max_mhz=frequency.max or None,
    )


def _uptime_readable(seconds: float) -> str:
    """Format uptime as non-zero days, hours, and minutes."""
    total_minutes = int(seconds // 60)
    days, remaining_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining_minutes, 60)

    units = (("day", days), ("hour", hours), ("minute", minutes))
    parts = [f"{value} {unit}{'' if value == 1 else 's'}" for unit, value in units if value]
    return ", ".join(parts) if parts else "0 minutes"


def get_system_info() -> SystemInfoResponse:
    """Collect current host identity, processor, and uptime information."""
    boot_timestamp: float | None
    try:
        boot_timestamp = psutil.boot_time()
    except (OSError, psutil.Error):
        boot_timestamp = None

    if boot_timestamp is None:
        boot_time = None
        uptime_seconds = None
        uptime_readable = None
    else:
        boot_time = datetime.fromtimestamp(
            boot_timestamp, tz=timezone.utc
        ).isoformat()
        uptime_seconds = max(0.0, time.time() - boot_timestamp)
        uptime_readable = _uptime_readable(uptime_seconds)

    operating_system = platform.system()
    if operating_system == "Linux":
        try:
            release_info = platform.freedesktop_os_release()
        except (OSError, AttributeError):
            release_info = {}
        operating_system = release_info.get("NAME", operating_system)

    try:
        physical_cores = psutil.cpu_count(logical=False)
    except (OSError, psutil.Error):
        physical_cores = None

    try:
        logical_cores = psutil.cpu_count(logical=True)
    except (OSError, psutil.Error):
        logical_cores = None

    hostname = socket.gethostname()
    return SystemInfoResponse(
        hostname=hostname,
        machine_name=platform.node() or hostname,
        operating_system=operating_system,
        os_version=platform.version(),
        os_release=platform.release(),
        architecture=platform.architecture()[0],
        processor=_processor_name(),
        cpu_architecture=platform.machine(),
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        cpu_frequency=_cpu_frequency(),
        boot_time=boot_time,
        uptime_seconds=uptime_seconds,
        uptime_readable=uptime_readable,
        python_version=platform.python_version(),
        application_platform=f"{platform.system()} {platform.machine()}",
    )
