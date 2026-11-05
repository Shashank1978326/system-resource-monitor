"""Disk partition capacity and cumulative I/O collection."""

import os
import threading
import time

import psutil

from app.schemas.monitoring import DiskIoResponse, DiskPartitionResponse, DiskResponse

_io_lock = threading.Lock()
_read_baseline: tuple[float, int] | None = None
_write_baseline: tuple[float, int] | None = None


def reset_disk_sampler() -> None:
    """Clear the read counter baseline when the background monitor restarts."""
    global _read_baseline, _write_baseline
    with _io_lock:
        _read_baseline = None
        _write_baseline = None


def _counter_value(counters: object, key: str) -> int | None:
    value = getattr(counters, key, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _disk_io() -> DiskIoResponse:
    global _read_baseline, _write_baseline
    now = time.monotonic()
    try:
        counters = psutil.disk_io_counters(perdisk=False)
    except (OSError, psutil.Error, NotImplementedError):
        counters = None
    read_bytes = _counter_value(counters, "read_bytes") if counters else None
    write_bytes = _counter_value(counters, "write_bytes") if counters else None
    read_speed: float | None = None
    read_speed_status = "unavailable"
    write_speed: float | None = None
    write_speed_status = "unavailable"

    with _io_lock:
        if read_bytes is None:
            _read_baseline = None
        else:
            read_speed_status = "initializing"
            if _read_baseline is not None:
                elapsed = now - _read_baseline[0]
                delta = read_bytes - _read_baseline[1]
                if elapsed > 0 and delta >= 0:
                    read_speed = delta / elapsed
                    read_speed_status = "available"
            _read_baseline = (now, read_bytes)

        if write_bytes is None:
            _write_baseline = None
        else:
            write_speed_status = "initializing"
            if _write_baseline is not None:
                elapsed = now - _write_baseline[0]
                delta = write_bytes - _write_baseline[1]
                if elapsed > 0 and delta >= 0:
                    write_speed = delta / elapsed
                    write_speed_status = "available"
            _write_baseline = (now, write_bytes)

    return DiskIoResponse(
        read_bytes=read_bytes,
        write_bytes=write_bytes,
        read_count=_counter_value(counters, "read_count") if counters else None,
        write_count=_counter_value(counters, "write_count") if counters else None,
        read_speed_bytes_per_sec=read_speed,
        read_speed_mb_per_sec=read_speed / 1024**2 if read_speed is not None else None,
        read_speed_status=read_speed_status,
        write_speed_bytes_per_sec=write_speed,
        write_speed_mb_per_sec=(
            write_speed / 1024**2 if write_speed is not None else None
        ),
        write_speed_status=write_speed_status,
    )


def get_disk_info() -> DiskResponse:
    """Return accessible mounted partition capacity and disk I/O counters."""
    partitions: list[DiskPartitionResponse] = []
    seen_mountpoints: set[str] = set()

    try:
        system_partitions = psutil.disk_partitions(all=False)
    except (OSError, psutil.Error):
        system_partitions = []

    for partition in system_partitions:
        mountpoint = partition.mountpoint
        normalized_mount = os.path.normcase(os.path.normpath(mountpoint))
        if normalized_mount in seen_mountpoints:
            continue

        try:
            usage = psutil.disk_usage(mountpoint)
        except (PermissionError, OSError, psutil.Error):
            continue

        seen_mountpoints.add(normalized_mount)
        partitions.append(
            DiskPartitionResponse(
                device=partition.device,
                mountpoint=mountpoint,
                filesystem=partition.fstype or "unknown",
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                usage_percent=usage.percent,
            )
        )

    return DiskResponse(partitions=partitions, io=_disk_io())
