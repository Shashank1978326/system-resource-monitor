"""Process monitoring endpoint."""

import logging
from typing import Literal

import psutil
from fastapi import APIRouter, HTTPException, Path, Query

from app.schemas.monitoring import ProcessDetailResponse, ProcessListResponse
from app.services.process_service import get_process_detail, get_processes

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["processes"])


@router.get(
    "/processes",
    response_model=ProcessListResponse,
    summary="List running processes",
)
def read_processes(
    search: str | None = Query(default=None, max_length=100),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    sort_by: Literal["pid", "cpu", "ram"] = Query(default="pid"),
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
) -> ProcessListResponse:
    """Return a bounded process list filtered by process name when requested."""
    try:
        return get_processes(
            search=search,
            status=status,
            limit=limit,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except (psutil.Error, OSError) as exc:
        logger.exception("Process collection failed")
        raise HTTPException(
            status_code=503,
            detail="Process information is temporarily unavailable",
        ) from exc


@router.get(
    "/processes/{pid}",
    response_model=ProcessDetailResponse,
    summary="Get details for one process",
)
def read_process_detail(
    pid: int = Path(ge=1),
) -> ProcessDetailResponse:
    """Return safe resource and runtime details for one process."""
    try:
        return get_process_detail(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise HTTPException(
            status_code=404,
            detail="Process no longer exists",
        ) from exc
    except psutil.AccessDenied as exc:
        raise HTTPException(
            status_code=403,
            detail="Access to this process is denied",
        ) from exc
    except (psutil.Error, OSError) as exc:
        logger.exception("Process detail lookup failed for PID %s", pid)
        raise HTTPException(
            status_code=503,
            detail="Process details are temporarily unavailable",
        ) from exc
