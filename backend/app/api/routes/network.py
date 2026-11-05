"""Network resource endpoint."""

from fastapi import APIRouter, HTTPException

from app.schemas.monitoring import (
    NetworkInterfaceTrafficListResponse,
    NetworkInterfacesResponse,
    NetworkResponse,
)
from app.services.monitoring_service import monitoring_service
from app.services.network_service import get_network_interfaces, get_network_traffic

router = APIRouter(prefix="/api", tags=["resources"])


@router.get("/network", response_model=NetworkResponse, summary="Network traffic")
def read_network() -> NetworkResponse:
    """Return network metrics from the latest completed background snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")
    return snapshot.network


@router.get(
    "/network/interfaces",
    response_model=NetworkInterfacesResponse,
    summary="Network interfaces",
)
def read_network_interfaces() -> NetworkInterfacesResponse:
    """Return interface addressing and link properties when available."""
    return get_network_interfaces()


@router.get(
    "/network/interfaces/traffic",
    response_model=NetworkInterfaceTrafficListResponse,
    summary="Per-interface network traffic",
)
def read_network_interface_traffic() -> NetworkInterfaceTrafficListResponse:
    """Return the latest per-interface rates from the existing monitor cycle."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")
    return get_network_traffic(snapshot.timestamp, snapshot.network)
