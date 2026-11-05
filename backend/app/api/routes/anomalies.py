"""Anomaly detection status, configuration, and event history endpoints."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.database.anomaly_repository import AnomalyStorageError
from app.schemas.monitoring import (
    AnomalyAnalyticsResponse,
    AnomalyHistoryResponse,
    AnomalyOverviewResponse,
    AnomalySettingsResponse,
    AnomalySettingsUpdateRequest,
)

_INTERVALS_SECONDS: dict[str, int] = {
    "1m": 60,
    "2m": 120,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}
from app.services.anomaly_service import anomaly_service

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"])


def _storage_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Anomaly storage is temporarily unavailable",
    )


@router.get(
    "",
    response_model=AnomalyOverviewResponse,
    summary="Current anomaly detection status, configuration, and recent events",
)
def read_anomalies() -> AnomalyOverviewResponse:
    """Return live anomaly status, settings, and recent statistical anomalies."""
    return anomaly_service.get_overview()


@router.get(
    "/settings",
    response_model=AnomalySettingsResponse,
    summary="Current anomaly detection settings",
)
def read_anomaly_settings() -> AnomalySettingsResponse:
    """Return active statistical baseline window, minimum samples, and sensitivity threshold."""
    return anomaly_service.get_settings()


@router.put(
    "/settings",
    response_model=AnomalySettingsResponse,
    summary="Update anomaly detection settings",
)
def update_anomaly_settings(
    settings_update: AnomalySettingsUpdateRequest,
) -> AnomalySettingsResponse:
    """Validate, persist, and apply updated anomaly detection settings."""
    try:
        return anomaly_service.update_settings(settings_update)
    except AnomalyStorageError as exc:
        raise _storage_error() from exc


@router.get(
    "/analytics",
    response_model=AnomalyAnalyticsResponse,
    summary="Statistical anomaly trend analytics",
)
def read_anomaly_analytics(
    range: str = Query(default="24h", description="Time range: 1h, 6h, 24h, 7d, 30d"),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    interval: str | None = None,
    resource: str | None = None,
    metric: str | None = None,
    severity: Literal["Warning", "Critical"] | None = None,
) -> AnomalyAnalyticsResponse:
    """Return historical anomaly frequency over time, resource distribution, and metric analysis."""
    interval_sec = _INTERVALS_SECONDS.get(interval) if interval else None
    try:
        return anomaly_service.get_analytics(
            range_key=range,
            start_time=start_time,
            end_time=end_time,
            interval_seconds=interval_sec,
            resource=resource,
            metric=metric,
            severity=severity,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except AnomalyStorageError as exc:
        raise _storage_error() from exc


@router.get(
    "/history",
    response_model=AnomalyHistoryResponse,
    summary="Persisted anomaly history",
)
def read_anomaly_history(
    resource: str | None = None,
    metric: str | None = None,
    severity: Literal["Warning", "Critical"] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> AnomalyHistoryResponse:
    """Return paginated historical anomaly events with optional resource, severity, and time filters."""
    try:
        return anomaly_service.get_history(
            resource=resource,
            metric=metric,
            severity=severity,
            limit=limit,
            offset=offset,
        )
    except AnomalyStorageError as exc:
        raise _storage_error() from exc


@router.delete(
    "/history",
    summary="Clear anomaly event history",
)
def clear_anomaly_history() -> dict[str, int]:
    """Remove all persisted anomaly events without modifying historical metrics."""
    try:
        deleted = anomaly_service.clear_events()
    except AnomalyStorageError as exc:
        raise _storage_error() from exc
    return {"deleted": deleted}


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one anomaly event",
)
def delete_anomaly_event(event_id: int) -> None:
    """Delete one persisted anomaly event."""
    if event_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Event ID must be positive",
        )
    try:
        deleted = anomaly_service.delete_event(event_id)
    except AnomalyStorageError as exc:
        raise _storage_error() from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anomaly event not found",
        )

