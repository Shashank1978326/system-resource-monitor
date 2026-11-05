"""CPU resource endpoint."""

from fastapi import APIRouter, HTTPException

from app.schemas.monitoring import CpuResponse
from app.services.monitoring_service import monitoring_service

router = APIRouter(prefix="/api", tags=["resources"])


@router.get("/cpu", response_model=CpuResponse, summary="CPU utilization")
def read_cpu() -> CpuResponse:
    """Return CPU metrics from the latest completed background snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")
    return snapshot.cpu
