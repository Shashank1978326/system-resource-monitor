"""Persistence operations for anomaly events and anomaly detection configuration."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import AnomalyEvent, AnomalySettings

_T = TypeVar("_T")


class AnomalyStorageError(Exception):
    """An anomaly database operation failed."""


class AnomalyRepository:
    """Store anomaly events and settings using the shared SQLite session factory."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _run(operation: str, callback: Callable[[], _T]) -> _T:
        try:
            return callback()
        except SQLAlchemyError as exc:
            raise AnomalyStorageError(f"Unable to {operation}") from exc

    def insert_event(
        self,
        *,
        resource: str,
        metric: str,
        actual_value: float,
        expected_value: float,
        standard_deviation: float,
        z_score: float,
        severity: str,
        message: str,
        timestamp: datetime,
    ) -> AnomalyEvent:
        def insert() -> AnomalyEvent:
            with self._session_factory.begin() as session:
                event = AnomalyEvent(
                    resource=resource,
                    metric=metric,
                    actual_value=actual_value,
                    expected_value=expected_value,
                    standard_deviation=standard_deviation,
                    z_score=z_score,
                    severity=severity,
                    message=message,
                    timestamp=timestamp,
                )
                session.add(event)
                session.flush()
                session.expunge(event)
                return event

        return self._run("persist anomaly event", insert)

    def get_events(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        severity: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AnomalyEvent], int]:
        def get() -> tuple[list[AnomalyEvent], int]:
            conditions = []
            if resource is not None:
                conditions.append(AnomalyEvent.resource == resource)
            if metric is not None:
                conditions.append(AnomalyEvent.metric == metric)
            if severity is not None:
                conditions.append(AnomalyEvent.severity == severity)
            if start_time is not None:
                conditions.append(AnomalyEvent.timestamp >= start_time)
            if end_time is not None:
                conditions.append(AnomalyEvent.timestamp <= end_time)
            statement = (
                select(AnomalyEvent)
                .where(*conditions)
                .order_by(AnomalyEvent.timestamp.desc(), AnomalyEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
            count_statement = (
                select(func.count(AnomalyEvent.id)).where(*conditions)
            )
            with self._session_factory() as session:
                events = list(session.scalars(statement))
                total = session.scalar(count_statement) or 0
                return events, total

        return self._run("read anomaly history", get)

    def get_events_in_range(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        resource: str | None = None,
        metric: str | None = None,
        severity: str | None = None,
    ) -> list[AnomalyEvent]:
        def get() -> list[AnomalyEvent]:
            conditions = [
                AnomalyEvent.timestamp >= start_time,
                AnomalyEvent.timestamp <= end_time,
            ]
            if resource is not None:
                conditions.append(AnomalyEvent.resource == resource)
            if metric is not None:
                conditions.append(AnomalyEvent.metric == metric)
            if severity is not None:
                conditions.append(AnomalyEvent.severity == severity)
            statement = (
                select(AnomalyEvent)
                .where(*conditions)
                .order_by(AnomalyEvent.timestamp.asc(), AnomalyEvent.id.asc())
            )
            with self._session_factory() as session:
                return list(session.scalars(statement))

        return self._run("read anomaly events for analytics", get)

    def get_recent_events(self, limit: int = 50) -> list[AnomalyEvent]:
        def get() -> list[AnomalyEvent]:
            statement = (
                select(AnomalyEvent)
                .order_by(AnomalyEvent.timestamp.desc(), AnomalyEvent.id.desc())
                .limit(limit)
            )
            with self._session_factory() as session:
                return list(session.scalars(statement))

        return self._run("read recent anomaly events", get)

    def delete_event(self, event_id: int) -> bool:
        def remove() -> bool:
            with self._session_factory.begin() as session:
                event = session.get(AnomalyEvent, event_id)
                if event is None:
                    return False
                session.delete(event)
                return True

        return self._run("delete anomaly event", remove)

    def clear_events(self) -> int:
        def clear() -> int:
            with self._session_factory.begin() as session:
                result = session.execute(delete(AnomalyEvent))
                return result.rowcount or 0

        return self._run("clear anomaly history", clear)

    def cleanup_expired(self, cutoff: datetime) -> int:
        def cleanup() -> int:
            with self._session_factory.begin() as session:
                result = session.execute(
                    delete(AnomalyEvent).where(AnomalyEvent.timestamp < cutoff)
                )
                return result.rowcount or 0

        return self._run("clean up expired anomaly events", cleanup)

    def get_settings(self) -> AnomalySettings | None:
        def get() -> AnomalySettings | None:
            with self._session_factory() as session:
                return session.get(AnomalySettings, 1)

        return self._run("read anomaly settings", get)

    def save_settings(self, values: dict[str, Any]) -> AnomalySettings:
        def save() -> AnomalySettings:
            with self._session_factory.begin() as session:
                row = session.get(AnomalySettings, 1)
                if row is None:
                    row = AnomalySettings(id=1, **values)
                    session.add(row)
                else:
                    for field, value in values.items():
                        setattr(row, field, value)
                session.flush()
                session.expunge(row)
                return row

        return self._run("save anomaly settings", save)

