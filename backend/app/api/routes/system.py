"""Basic system-level API endpoints."""

from fastapi import APIRouter

from app.core.config import settings
from app.schemas.monitoring import BatteryResponse, SystemInfoResponse, TemperatureResponse
from app.services.battery_service import get_battery_info
from app.services.system_service import get_system_info
from app.services.temperature_service import get_temperature_info

router = APIRouter(tags=["system"])


@router.get("/", summary="API welcome")
def read_root() -> dict[str, str]:
    """Return a short message confirming that the API is available."""
    return {"message": settings.app_title}


@router.get("/api/health", summary="Health check")
def read_health() -> dict[str, str]:
    """Report that the API process is responsive."""
    return {"status": "healthy"}


@router.get(
    "/api/system/info",
    response_model=SystemInfoResponse,
    summary="System information",
)
def read_system_info() -> SystemInfoResponse:
    """Return operating system, processor, and uptime information."""
    return get_system_info()


@router.get(
    "/api/temperature",
    response_model=TemperatureResponse,
    summary="Hardware temperature sensors",
)
def read_temperature() -> TemperatureResponse:
    """Return real temperature readings when supported by the host."""
    return get_temperature_info()


@router.get(
    "/api/battery",
    response_model=BatteryResponse,
    summary="Battery status",
)
def read_battery() -> BatteryResponse:
    """Return real battery readings when supported by the host."""
    return get_battery_info()
