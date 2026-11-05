"""Background monitoring status and latest-snapshot endpoints."""

from fastapi import APIRouter, HTTPException

from app.schemas.monitoring import (
    MonitoringSnapshotResponse,
    MonitoringStatusResponse,
)
from app.services.monitoring_service import monitoring_service

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


@router.get("/latest", response_model=MonitoringSnapshotResponse)
def read_latest_snapshot() -> MonitoringSnapshotResponse:
    """Return the latest combined metrics snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "initializing",
                "message": "The first monitoring collection has not completed",
            },
        )
    return snapshot


@router.get("/status", response_model=MonitoringStatusResponse)
def read_monitoring_status() -> MonitoringStatusResponse:
    """Return collector state and collection-cycle counters."""
    return monitoring_service.get_status()
