"""Persistence operations for historical predictions and evaluation accuracy."""

import logging
import math
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import HistoricalPrediction

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class PredictionStorageError(Exception):
    """A prediction database operation failed."""


class PredictionRepository:
    """Store and evaluate predictions using the shared SQLite session factory."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _run(operation: str, callback: Callable[[], _T]) -> _T:
        try:
            return callback()
        except SQLAlchemyError as exc:
            logger.exception("Prediction database failure during %s", operation)
            raise PredictionStorageError(f"Unable to {operation}") from exc

    def insert_prediction(
        self,
        *,
        resource: str,
        metric: str,
        unit: str,
        horizon: str,
        horizon_seconds: int,
        generated_at: datetime,
        target_timestamp: datetime,
        current_value: float | None,
        predicted_value: float,
        lower_bound: float | None = None,
        upper_bound: float | None = None,
        confidence_score: float | None = None,
        model: str = "exponentially_weighted_linear_regression",
        prediction_id: str | None = None,
    ) -> HistoricalPrediction:
        """Store a new prediction record."""
        def insert() -> HistoricalPrediction:
            with self._session_factory.begin() as session:
                record = HistoricalPrediction(
                    prediction_id=prediction_id or str(uuid.uuid4()),
                    resource=resource,
                    metric=metric,
                    unit=unit,
                    horizon=horizon,
                    horizon_seconds=horizon_seconds,
                    generated_at=generated_at,
                    target_timestamp=target_timestamp,
                    current_value=current_value,
                    predicted_value=predicted_value,
                    lower_bound=lower_bound,
                    upper_bound=upper_bound,
                    confidence_score=confidence_score,
                    model=model,
                    evaluation_status="pending",
                )
                session.add(record)
                session.flush()
                return record

        return self._run("insert prediction", insert)

    def find_duplicate(
        self,
        metric: str,
        horizon: str,
        target_timestamp: datetime,
        window_seconds: int = 30,
    ) -> HistoricalPrediction | None:
        """Find an existing prediction for the metric/horizon within window_seconds of target_timestamp."""
        def query() -> HistoricalPrediction | None:
            with self._session_factory() as session:
                stmt = select(HistoricalPrediction).where(
                    HistoricalPrediction.metric == metric,
                    HistoricalPrediction.horizon == horizon,
                ).order_by(HistoricalPrediction.id.desc()).limit(10)
                candidates = list(session.scalars(stmt))
                for c in candidates:
                    target = c.target_timestamp
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=timezone.utc)
                    tt = target_timestamp
                    if tt.tzinfo is None:
                        tt = tt.replace(tzinfo=timezone.utc)
                    if abs((target - tt).total_seconds()) <= window_seconds:
                        return c
                return None

        return self._run("check prediction duplicate", query)

    def get_pending_predictions(
        self, before_timestamp: datetime | None = None
    ) -> list[HistoricalPrediction]:
        """Fetch predictions awaiting evaluation whose target timestamp has passed."""
        def query() -> list[HistoricalPrediction]:
            with self._session_factory() as session:
                stmt = select(HistoricalPrediction).where(
                    HistoricalPrediction.evaluation_status == "pending"
                )
                if before_timestamp is not None:
                    stmt = stmt.where(HistoricalPrediction.target_timestamp <= before_timestamp)
                stmt = stmt.order_by(HistoricalPrediction.target_timestamp.asc())
                return list(session.scalars(stmt))

        return self._run("query pending predictions", query)

    def update_evaluation(
        self,
        prediction_id: str,
        *,
        actual_value: float | None,
        absolute_error: float | None,
        percentage_error: float | None,
        evaluation_status: str,
        evaluated_at: datetime,
    ) -> None:
        """Update a prediction record with evaluation results."""
        def update() -> None:
            with self._session_factory.begin() as session:
                stmt = select(HistoricalPrediction).where(
                    HistoricalPrediction.prediction_id == prediction_id
                )
                pred = session.scalars(stmt).first()
                if pred is not None:
                    pred.actual_value = actual_value
                    pred.absolute_error = absolute_error
                    pred.percentage_error = percentage_error
                    pred.evaluation_status = evaluation_status
                    pred.evaluated_at = evaluated_at

        self._run("update prediction evaluation", update)

    def get_history(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        horizon: str | None = None,
        status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[HistoricalPrediction], int]:
        """Fetch paginated prediction records with total count."""
        def query() -> tuple[list[HistoricalPrediction], int]:
            with self._session_factory() as session:
                conditions = []
                if resource and resource != "all":
                    conditions.append(HistoricalPrediction.resource == resource)
                if metric and metric != "all":
                    conditions.append(HistoricalPrediction.metric == metric)
                if horizon and horizon != "all":
                    conditions.append(HistoricalPrediction.horizon == horizon)
                if status and status != "all":
                    conditions.append(HistoricalPrediction.evaluation_status == status)
                if start_time is not None:
                    conditions.append(HistoricalPrediction.target_timestamp >= start_time)
                if end_time is not None:
                    conditions.append(HistoricalPrediction.target_timestamp <= end_time)

                count_stmt = select(func.count(HistoricalPrediction.id)).where(*conditions)
                total = session.scalar(count_stmt) or 0

                offset = (page - 1) * page_size
                stmt = (
                    select(HistoricalPrediction)
                    .where(*conditions)
                    .order_by(HistoricalPrediction.target_timestamp.desc())
                    .limit(page_size)
                    .offset(offset)
                )
                items = list(session.scalars(stmt))
                return items, total

        return self._run("query prediction history", query)

    def get_evaluated_predictions(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        horizon: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[HistoricalPrediction]:
        """Fetch evaluated predictions for accuracy calculation."""
        def query() -> list[HistoricalPrediction]:
            with self._session_factory() as session:
                conditions = [HistoricalPrediction.evaluation_status == "evaluated"]
                if resource and resource != "all":
                    conditions.append(HistoricalPrediction.resource == resource)
                if metric and metric != "all":
                    conditions.append(HistoricalPrediction.metric == metric)
                if horizon and horizon != "all":
                    conditions.append(HistoricalPrediction.horizon == horizon)
                if start_time is not None:
                    conditions.append(HistoricalPrediction.target_timestamp >= start_time)
                if end_time is not None:
                    conditions.append(HistoricalPrediction.target_timestamp <= end_time)

                stmt = (
                    select(HistoricalPrediction)
                    .where(*conditions)
                    .order_by(HistoricalPrediction.target_timestamp.asc())
                )
                if limit is not None:
                    stmt = stmt.limit(limit)
                return list(session.scalars(stmt))

        return self._run("query evaluated predictions", query)

    def count_pending(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        horizon: str | None = None,
    ) -> int:
        """Count predictions currently in pending status."""
        def count() -> int:
            with self._session_factory() as session:
                conditions = [HistoricalPrediction.evaluation_status == "pending"]
                if resource and resource != "all":
                    conditions.append(HistoricalPrediction.resource == resource)
                if metric and metric != "all":
                    conditions.append(HistoricalPrediction.metric == metric)
                if horizon and horizon != "all":
                    conditions.append(HistoricalPrediction.horizon == horizon)
                stmt = select(func.count(HistoricalPrediction.id)).where(*conditions)
                return session.scalar(stmt) or 0

        return self._run("count pending predictions", count)

    def clear_predictions(self) -> None:
        """Delete all prediction records (used in tests)."""
        def clear() -> None:
            with self._session_factory.begin() as session:
                session.execute(delete(HistoricalPrediction))

        self._run("clear predictions", clear)

