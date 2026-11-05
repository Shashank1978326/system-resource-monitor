"""Memory resource endpoint."""

from fastapi import APIRouter, HTTPException

from app.schemas.monitoring import MemoryResponse
from app.services.monitoring_service import monitoring_service

router = APIRouter(prefix="/api", tags=["resources"])


@router.get("/memory", response_model=MemoryResponse, summary="Memory usage")
def read_memory() -> MemoryResponse:
    """Return memory metrics from the latest completed background snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")
    return snapshot.memory
