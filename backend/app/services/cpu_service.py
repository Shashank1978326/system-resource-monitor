"""Non-blocking CPU utilization sampling."""

import threading
import time

import psutil

from app.schemas.monitoring import CpuResponse

_SAMPLE_INTERVAL_SECONDS = 1.0
_lock = threading.Lock()
_last_sample_time: float | None = None
_cached_response: CpuResponse | None = None


def reset_cpu_sampler() -> None:
    """Clear cached CPU readings so a restarted monitor establishes a new baseline."""
    global _cached_response, _last_sample_time
    with _lock:
        _cached_response = None
        _last_sample_time = None


def _safe_cpu_frequency() -> tuple[float | None, float | None, float | None]:
    try:
        frequency = psutil.cpu_freq()
    except (OSError, psutil.Error):
        return None, None, None
    if frequency is None:
        return None, None, None
    return frequency.current or None, frequency.min or None, frequency.max or None


def _safe_cpu_count(logical: bool) -> int | None:
    try:
        return psutil.cpu_count(logical=logical)
    except (OSError, psutil.Error):
        return None


def _safe_percent(per_cpu: bool = False) -> float | list[float] | None:
    try:
        return psutil.cpu_percent(interval=None, percpu=per_cpu)
    except (OSError, psutil.Error):
        return None


def _usage_status(usage: float | None) -> str | None:
    if usage is None:
        return None
    if usage < 60:
        return "normal"
    if usage < 85:
        return "elevated"
    return "high"


def get_cpu_info() -> CpuResponse:
    """Return a cached non-blocking CPU sample, updated at most once per second.

    psutil's first interval=None reading is a baseline rather than a meaningful
    utilization sample, so utilization remains null until a later sample.
    """
    global _cached_response, _last_sample_time

    now = time.monotonic()
    with _lock:
        if (
            _cached_response is not None
            and _last_sample_time is not None
            and now - _last_sample_time < _SAMPLE_INTERVAL_SECONDS
        ):
            return _cached_response.model_copy(deep=True)

        # Prime each psutil CPU counter once; its first result is intentionally ignored.
        if _last_sample_time is None:
            _safe_percent()
            _safe_percent(per_cpu=True)
            total_usage = None
            per_core_usage = None
        else:
            total_reading = _safe_percent()
            core_reading = _safe_percent(per_cpu=True)
            total_usage = (
                float(total_reading) if isinstance(total_reading, (int, float)) else None
            )
            per_core_usage = (
                [float(value) for value in core_reading]
                if isinstance(core_reading, list)
                else None
            )

        current_frequency, min_frequency, max_frequency = _safe_cpu_frequency()
        _cached_response = CpuResponse(
            cpu_usage_percent=total_usage,
            per_core_usage=per_core_usage,
            physical_cores=_safe_cpu_count(logical=False),
            logical_cores=_safe_cpu_count(logical=True),
            frequency_mhz=current_frequency,
            min_frequency_mhz=min_frequency,
            max_frequency_mhz=max_frequency,
            usage_status=_usage_status(total_usage),
        )
        _last_sample_time = now
        return _cached_response.model_copy(deep=True)
