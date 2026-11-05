"""Persistence operations for alert events and user-configured thresholds."""

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import AlertCurrentState, AlertEvent, AlertThresholdSettings
_T = TypeVar("_T")


class AlertStorageError(Exception):
    """An alert database operation failed."""


class AlertRepository:
    """Store alert events and thresholds using the shared SQLite session factory."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _run(operation: str, callback: Callable[[], _T]) -> _T:
        try:
            return callback()
        except SQLAlchemyError as exc:
            raise AlertStorageError(f"Unable to {operation}") from exc

    def insert_event(
        self,
        *,
        resource: str,
        severity: str,
        previous_severity: str,
        message: str,
        utilization_percent: float,
        configured_threshold_percent: float,
        timestamp: datetime,
        device: str | None = None,
        mountpoint: str | None = None,
        total_bytes: int | None = None,
        used_bytes: int | None = None,
        free_bytes: int | None = None,
        sensor_id: str | None = None,
        sensor_name: str | None = None,
        sensor_label: str | None = None,
        temperature_celsius: float | None = None,
        configured_threshold_celsius: float | None = None,
    ) -> AlertEvent:
        def insert() -> AlertEvent:
            with self._session_factory.begin() as session:
                event = AlertEvent(
                    resource=resource,
                    severity=severity,
                    previous_severity=previous_severity,
                    message=message,
                    utilization_percent=utilization_percent,
                    configured_threshold_percent=configured_threshold_percent,
                    timestamp=timestamp,
                    device=device,
                    mountpoint=mountpoint,
                    total_bytes=total_bytes,
                    used_bytes=used_bytes,
                    free_bytes=free_bytes,
                    sensor_id=sensor_id,
                    sensor_name=sensor_name,
                    sensor_label=sensor_label,
                    temperature_celsius=temperature_celsius,
                    configured_threshold_celsius=configured_threshold_celsius,
                )
                session.add(event)
                session.flush()
                state_key = (
                    f"disk:{mountpoint}"
                    if resource == "disk"
                    else f"temperature:{sensor_id}"
                    if resource == "temperature"
                    else resource
                )
                current = session.get(AlertCurrentState, state_key)
                state_values = {
                    "resource": resource,
                    "severity": severity,
                    "utilization_percent": utilization_percent,
                    "device": device,
                    "mountpoint": mountpoint,
                    "total_bytes": total_bytes,
                    "used_bytes": used_bytes,
                    "free_bytes": free_bytes,
                    "sensor_id": sensor_id,
                    "sensor_name": sensor_name,
                    "sensor_label": sensor_label,
                    "timestamp": timestamp,
                }
                if current is None:
                    session.add(
                        AlertCurrentState(state_key=state_key, **state_values)
                    )
                else:
                    for field, value in state_values.items():
                        setattr(current, field, value)
                session.expunge(event)
                return event

        return self._run("persist alert event", insert)

    def get_events(
        self,
        *,
        resource: str | None,
        severity: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AlertEvent], int]:
        def get() -> tuple[list[AlertEvent], int]:
            conditions = []
            if resource is not None:
                conditions.append(AlertEvent.resource == resource)
            if severity is not None:
                conditions.append(AlertEvent.severity == severity)
            statement = (
                select(AlertEvent)
                .where(*conditions)
                .order_by(AlertEvent.timestamp.desc(), AlertEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
            count_statement = (
                select(func.count(AlertEvent.id)).where(*conditions)
            )
            with self._session_factory() as session:
                events = list(session.scalars(statement))
                total = session.scalar(count_statement) or 0
                return events, total

        return self._run("read alert history", get)

    def get_current_states(self) -> list[AlertCurrentState]:
        def get() -> list[AlertCurrentState]:
            statement = select(AlertCurrentState)
            with self._session_factory() as session:
                return list(session.scalars(statement))

        return self._run("restore alert states", get)

    def get_recent_events(self, limit: int) -> list[AlertEvent]:
        def get() -> list[AlertEvent]:
            statement = (
                select(AlertEvent)
                .order_by(AlertEvent.timestamp.desc(), AlertEvent.id.desc())
                .limit(limit)
            )
            with self._session_factory() as session:
                return list(session.scalars(statement))

        return self._run("read recent alert events", get)

    def acknowledge(self, alert_id: int) -> AlertEvent | None:
        def update() -> AlertEvent | None:
            with self._session_factory.begin() as session:
                event = session.get(AlertEvent, alert_id)
                if event is None:
                    return None
                if not event.acknowledged:
                    event.acknowledged = True
                    event.acknowledged_at = datetime.now(timezone.utc)
                session.flush()
                session.expunge(event)
                return event

        return self._run("acknowledge alert", update)

    def delete_event(self, alert_id: int) -> bool:
        def remove() -> bool:
            with self._session_factory.begin() as session:
                event = session.get(AlertEvent, alert_id)
                if event is None:
                    return False
                session.delete(event)
                return True

        return self._run("delete alert", remove)

    def clear_events(self) -> int:
        def clear() -> int:
            with self._session_factory.begin() as session:
                result = session.execute(delete(AlertEvent))
                return result.rowcount or 0

        return self._run("clear alert history", clear)

    def clear_current_states(self) -> None:
        def clear() -> None:
            with self._session_factory.begin() as session:
                session.execute(delete(AlertCurrentState))

        self._run("reset current alert states", clear)

    def get_thresholds(self) -> AlertThresholdSettings | None:
        def get() -> AlertThresholdSettings | None:
            with self._session_factory() as session:
                return session.get(AlertThresholdSettings, 1)

        return self._run("read alert thresholds", get)

    def save_thresholds(
        self,
        values: dict[str, float],
    ) -> AlertThresholdSettings:
        def save() -> AlertThresholdSettings:
            with self._session_factory.begin() as session:
                row = session.get(AlertThresholdSettings, 1)
                if row is None:
                    row = AlertThresholdSettings(id=1, **values)
                    session.add(row)
                else:
                    for field, value in values.items():
                        setattr(row, field, value)
                session.flush()
                session.expunge(row)
                return row

        return self._run("save alert thresholds", save)
