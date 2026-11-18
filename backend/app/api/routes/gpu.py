"""GPU hardware information and multi-GPU telemetry endpoints."""

from fastapi import APIRouter

from app.schemas.monitoring import GpuInfoResponse, GpuListResponse, GpuUsageResponse
from app.services.gpu_service import get_gpu_info, get_gpu_list, get_gpu_usage

router = APIRouter(tags=["gpu"])


@router.get(
    "/api/gpu/info",
    response_model=GpuInfoResponse,
    summary="GPU hardware detection and monitoring capability",
)
def read_gpu_info() -> GpuInfoResponse:
    """Return detected display adapters and supported monitoring capabilities."""
    return get_gpu_info()


@router.get(
    "/api/gpu/usage",
    response_model=GpuUsageResponse,
    summary="Available GPU utilization, memory, temperature, and power readings",
)
def read_gpu_usage() -> GpuUsageResponse:
    """Return current samples and per-metric availability for all detected GPUs."""
    return get_gpu_usage()


@router.get(
    "/api/gpu/list",
    response_model=GpuListResponse,
    summary="Structured list of all detected GPUs and real-time metrics",
)
def read_gpu_list() -> GpuListResponse:
    """Return normalized multi-GPU summary cards with vendor, type, and activity status."""
    return get_gpu_list()
