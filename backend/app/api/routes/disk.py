"""Disk resource endpoint."""

from fastapi import APIRouter, HTTPException

from app.schemas.monitoring import DiskIoSpeedResponse, DiskResponse
from app.services.monitoring_service import monitoring_service

router = APIRouter(prefix="/api", tags=["resources"])


@router.get("/disk", response_model=DiskResponse, summary="Disk capacity and I/O")
def read_disk() -> DiskResponse:
    """Return disk metrics from the latest completed background snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")
    return snapshot.disk


@router.get(
    "/disk/io",
    response_model=DiskIoSpeedResponse,
    summary="Current disk read/write speeds and cumulative I/O counters",
)
def read_disk_io() -> DiskIoSpeedResponse:
    """Return I/O speed measurements from the latest background snapshot."""
    snapshot = monitoring_service.get_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=503, detail="Monitoring is initializing")

    io = snapshot.disk.io
    status = io.read_speed_status
    messages = {
        "initializing": "Waiting for a second disk counter sample.",
        "unavailable": "Disk read counters are unavailable.",
    }
    write_status = io.write_speed_status
    write_messages = {
        "initializing": "Waiting for a second disk counter sample.",
        "unavailable": "Disk write counters are unavailable.",
    }
    return DiskIoSpeedResponse(
        timestamp=snapshot.timestamp,
        total_bytes_read=io.read_bytes,
        read_operations=io.read_count,
        read_speed_bytes_per_sec=io.read_speed_bytes_per_sec,
        read_speed_mb_per_sec=io.read_speed_mb_per_sec,
        available=status == "available",
        status=status,
        message=messages.get(status),
        total_bytes_written=io.write_bytes,
        write_operations=io.write_count,
        write_speed_bytes_per_sec=io.write_speed_bytes_per_sec,
        write_speed_mb_per_sec=io.write_speed_mb_per_sec,
        write_available=write_status == "available",
        write_status=write_status,
        write_message=write_messages.get(write_status),
    )
