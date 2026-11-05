"""Physical memory and swap collection."""

import psutil

from app.schemas.monitoring import MemoryResponse


def get_memory_info() -> MemoryResponse:
    """Return current physical memory and swap counters in bytes."""
    try:
        memory = psutil.virtual_memory()
    except (OSError, psutil.Error, RuntimeError):
        memory = None
    try:
        swap = psutil.swap_memory()
    except (OSError, psutil.Error, RuntimeError):
        swap = None

    cached = getattr(memory, "cached", None) if memory is not None else None
    return MemoryResponse(
        total_bytes=memory.total if memory is not None else None,
        used_bytes=memory.used if memory is not None else None,
        available_bytes=memory.available if memory is not None else None,
        free_bytes=memory.free if memory is not None else None,
        usage_percent=memory.percent if memory is not None else None,
        cached_bytes=cached,
        swap_total_bytes=swap.total if swap is not None else None,
        swap_used_bytes=swap.used if swap is not None else None,
        swap_percent=swap.percent if swap is not None else None,
    )
