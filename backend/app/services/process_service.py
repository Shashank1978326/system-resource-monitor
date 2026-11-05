"""On-demand collection of non-sensitive process information."""

import logging
import threading
from datetime import datetime, timezone

import psutil

from app.schemas.monitoring import (
    ProcessDetailResponse,
    ProcessInfoResponse,
    ProcessListResponse,
)

logger = logging.getLogger(__name__)
_sampling_lock = threading.Lock()
_sampled_cpu_processes: set[tuple[int, float | None]] = set()
_BYTES_PER_MEGABYTE = 1024 * 1024


def get_processes(
    search: str | None = None,
    status: str | None = None,
    limit: int = 100,
    sort_by: str = "pid",
    sort_order: str = "asc",
) -> ProcessListResponse:
    """Return one non-blocking sample of process resource usage."""
    global _sampled_cpu_processes

    search_term = search.casefold() if search else None
    status_filter = status.casefold() if status else None
    matching_processes: list[ProcessInfoResponse] = []
    all_processes: list[ProcessInfoResponse] = []

    with _sampling_lock:
        previously_sampled = _sampled_cpu_processes
        successfully_sampled: set[tuple[int, float | None]] = set()
        try:
            memory_total = psutil.virtual_memory().total
        except (psutil.Error, OSError):
            logger.exception("Unable to read total system memory")
            memory_total = None

        try:
            for process in psutil.process_iter(
                attrs=("pid", "name", "status", "create_time"),
                ad_value=None,
            ):
                try:
                    details = process.info
                    pid = details.get("pid")
                    if not isinstance(pid, int):
                        continue

                    name = details.get("name")
                    create_time = details.get("create_time")
                    identity = (
                        pid,
                        float(create_time) if isinstance(create_time, (int, float)) else None,
                    )

                    try:
                        cpu_reading = process.cpu_percent(interval=None)
                    except psutil.AccessDenied:
                        cpu_percent = None
                    else:
                        cpu_percent = (
                            float(cpu_reading)
                            if identity in previously_sampled
                            else None
                        )
                        successfully_sampled.add(identity)

                    memory_bytes: int | None = None
                    try:
                        memory_info = process.memory_info()
                        memory_bytes = memory_info.rss
                        memory_mb = memory_bytes / _BYTES_PER_MEGABYTE
                    except psutil.AccessDenied:
                        memory_mb = None

                    try:
                        process_status = details.get("status")
                    except psutil.AccessDenied:
                        process_status = None

                    memory_percent = (
                        memory_bytes / memory_total * 100
                        if memory_mb is not None
                        and memory_bytes is not None
                        and memory_total is not None
                        and memory_total > 0
                        else None
                    )

                    process_info = ProcessInfoResponse(
                        pid=pid,
                        name=name if isinstance(name, str) else None,
                        status=(
                            process_status
                            if isinstance(process_status, str)
                            else None
                        ),
                        cpu_percent=cpu_percent,
                        memory_mb=memory_mb,
                        memory_percent=memory_percent,
                    )
                    all_processes.append(process_info)
                    if (search_term is None or (
                        isinstance(name, str) and search_term in name.casefold()
                    )) and (
                        status_filter is None
                        or (
                            isinstance(process_status, str)
                            and process_status.casefold() == status_filter
                        )
                    ):
                        matching_processes.append(process_info)
                except (
                    psutil.AccessDenied,
                    psutil.NoSuchProcess,
                    psutil.ZombieProcess,
                ):
                    logger.debug("Skipping an inaccessible or transient process")
        except (psutil.Error, OSError):
            logger.exception("Unable to enumerate system processes")
            raise

        _sampled_cpu_processes = successfully_sampled

    def sorted_by_resource(
        processes: list[ProcessInfoResponse],
        attribute: str,
        descending: bool,
    ) -> list[ProcessInfoResponse]:
        values = [process for process in processes if getattr(process, attribute) is not None]
        unavailable = [
            process for process in processes if getattr(process, attribute) is None
        ]
        values.sort(
            key=lambda process: (getattr(process, attribute), process.pid),
            reverse=descending,
        )
        unavailable.sort(key=lambda process: process.pid)
        return values + unavailable

    if sort_by == "cpu":
        matching_processes = sorted_by_resource(
            matching_processes, "cpu_percent", sort_order == "desc"
        )
    elif sort_by == "ram":
        matching_processes = sorted_by_resource(
            matching_processes, "memory_mb", sort_order == "desc"
        )
    else:
        matching_processes.sort(key=lambda process: process.pid, reverse=sort_order == "desc")

    top_cpu_processes = sorted_by_resource(
        [
            process
            for process in all_processes
            if process.pid != 0 and process.cpu_percent is not None
        ],
        "cpu_percent",
        True,
    )[:5]
    top_ram_processes = sorted_by_resource(
        [process for process in all_processes if process.memory_mb is not None],
        "memory_mb",
        True,
    )[:5]

    return ProcessListResponse(
        total_processes=len(matching_processes),
        processes=matching_processes[:limit],
        total_process_count=len(all_processes),
        top_cpu_processes=top_cpu_processes,
        top_ram_processes=top_ram_processes,
    )


def _read_process_value(
    process: psutil.Process,
    attribute: str,
) -> object | None:
    try:
        return getattr(process, attribute)()
    except psutil.AccessDenied:
        return None


def get_process_detail(pid: int) -> ProcessDetailResponse:
    """Read current metrics for one process without exposing command data."""
    global _sampled_cpu_processes

    with _sampling_lock:
        process = psutil.Process(pid)
        create_time = _read_process_value(process, "create_time")
        identity = (
            pid,
            float(create_time) if isinstance(create_time, (int, float)) else None,
        )

        cpu_reading = _read_process_value(process, "cpu_percent")
        cpu_percent = (
            float(cpu_reading)
            if isinstance(cpu_reading, (int, float))
            and identity in _sampled_cpu_processes
            else None
        )
        if cpu_reading is not None:
            _sampled_cpu_processes.add(identity)

        memory_info = _read_process_value(process, "memory_info")
        memory_bytes = getattr(memory_info, "rss", None)
        memory_mb = (
            memory_bytes / _BYTES_PER_MEGABYTE
            if isinstance(memory_bytes, (int, float))
            else None
        )
        try:
            total_memory = psutil.virtual_memory().total
        except (psutil.Error, OSError):
            logger.exception("Unable to read total system memory")
            total_memory = None
        memory_percent = (
            memory_bytes / total_memory * 100
            if isinstance(memory_bytes, (int, float))
            and isinstance(total_memory, (int, float))
            and total_memory > 0
            else None
        )

        process_status = _read_process_value(process, "status")
        thread_count = _read_process_value(process, "num_threads")
        username = _read_process_value(process, "username")

        timestamp = (
            datetime.fromtimestamp(create_time, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
            if isinstance(create_time, (int, float))
            else None
        )
        return ProcessDetailResponse(
            pid=pid,
            name=_read_process_value(process, "name"),
            status=process_status if isinstance(process_status, str) else None,
            cpu_percent=cpu_percent,
            memory_mb=memory_mb,
            memory_percent=memory_percent,
            thread_count=thread_count if isinstance(thread_count, int) else None,
            create_time=timestamp,
            username=username if isinstance(username, str) else None,
        )
