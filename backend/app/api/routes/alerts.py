"""Resource alert state, history, threshold, and management endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status

from app.database.alert_repository import AlertStorageError
from app.database.models import AlertEvent
from app.schemas.monitoring import (
    AlertHistoryEventResponse,
    AlertHistoryResponse,
    AlertsStatusResponse,
    AlertThresholdsResponse,
    AlertThresholdsUpdateRequest,
    CpuAlertsResponse,
)
from app.services.alert_service import alert_repository, cpu_alert_service

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get(
    "",
    response_model=CpuAlertsResponse,
    summary="Current resource alerts and recent events",
)
def read_alerts() -> CpuAlertsResponse:
    """Return CPU, RAM, and disk alert states and recent transitions."""
    return cpu_alert_service.get_alerts()


def _storage_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Alert storage is temporarily unavailable",
    )


def _history_response(record: AlertEvent) -> AlertHistoryEventResponse:
    return AlertHistoryEventResponse(
        id=record.id,
        resource=record.resource,
        severity=record.severity,
        previous_severity=record.previous_severity,
        message=record.message,
        utilization_percent=record.utilization_percent,
        configured_threshold_percent=record.configured_threshold_percent,
        device=record.device,
        mountpoint=record.mountpoint,
        total_bytes=record.total_bytes,
        used_bytes=record.used_bytes,
        free_bytes=record.free_bytes,
        sensor_id=record.sensor_id,
        sensor_name=record.sensor_name,
        sensor_label=record.sensor_label,
        temperature_celsius=record.temperature_celsius,
        configured_threshold_celsius=record.configured_threshold_celsius,
        timestamp=record.timestamp.isoformat(),
        acknowledged=record.acknowledged,
        acknowledged_at=(
            record.acknowledged_at.isoformat()
            if record.acknowledged_at
            else None
        ),
    )


@router.get("/thresholds", response_model=AlertThresholdsResponse)
def read_alert_thresholds() -> AlertThresholdsResponse:
    """Return currently active thresholds."""
    return cpu_alert_service.get_thresholds()


@router.put("/thresholds", response_model=AlertThresholdsResponse)
def update_alert_thresholds(
    thresholds: AlertThresholdsUpdateRequest,
) -> AlertThresholdsResponse:
    """Persist and apply validated thresholds without restarting monitoring."""
    try:
        return cpu_alert_service.update_thresholds(thresholds)
    except AlertStorageError as exc:
        raise _storage_error() from exc


@router.get("/history", response_model=AlertHistoryResponse)
def read_alert_history(
    resource: Literal["cpu", "ram", "disk", "temperature", "battery"] | None = None,
    severity: Literal["Normal", "Warning", "Critical"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> AlertHistoryResponse:
    """Return the requested bounded page of persisted alert events."""
    try:
        events, total = alert_repository.get_events(
            resource=resource,
            severity=severity,
            limit=limit,
            offset=offset,
        )
    except AlertStorageError as exc:
        raise _storage_error() from exc
    return AlertHistoryResponse(
        total=total,
        limit=limit,
        offset=offset,
        events=[_history_response(event) for event in events],
    )


@router.patch("/{alert_id}/acknowledge", response_model=AlertHistoryEventResponse)
def acknowledge_alert(alert_id: int) -> AlertHistoryEventResponse:
    """Acknowledge one alert event; repeated acknowledgement is idempotent."""
    if alert_id <= 0:
        raise HTTPException(status_code=400, detail="Alert ID must be positive")
    if alert_id > 9_223_372_036_854_775_807:
        raise HTTPException(status_code=400, detail="Alert ID is out of range")
    try:
        event = alert_repository.acknowledge(alert_id)
    except AlertStorageError as exc:
        raise _storage_error() from exc
    if event is None:
        raise HTTPException(status_code=404, detail="Alert event not found")
    if event.acknowledged_at is not None:
        cpu_alert_service.mark_acknowledged(alert_id, event.acknowledged_at)
    return _history_response(event)


@router.delete("/history")
def clear_alert_history() -> dict[str, int]:
    """Remove all persisted alert events without changing monitoring history."""
    try:
        deleted = alert_repository.clear_events()
    except AlertStorageError as exc:
        raise _storage_error() from exc
    cpu_alert_service.clear_events()
    return {"deleted": deleted}


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(alert_id: int) -> None:
    """Delete one persisted alert event."""
    if alert_id <= 0:
        raise HTTPException(status_code=400, detail="Alert ID must be positive")
    if alert_id > 9_223_372_036_854_775_807:
        raise HTTPException(status_code=400, detail="Alert ID is out of range")
    try:
        deleted = alert_repository.delete_event(alert_id)
    except AlertStorageError as exc:
        raise _storage_error() from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert event not found")
    cpu_alert_service.remove_event(alert_id)


@router.get("/status", response_model=AlertsStatusResponse, summary="Current resource alert status")
def read_alert_status() -> AlertsStatusResponse:
    """Return current resource alert states and temperature availability."""
    cpu_status = cpu_alert_service.get_status()
    return AlertsStatusResponse(
        **cpu_status.model_dump(),
        ram=cpu_alert_service.get_ram_status(),
        disk=cpu_alert_service.get_disk_status(),
        temperature=cpu_alert_service.get_temperature_alerts(),
        battery=cpu_alert_service.get_battery_status(),
    )
