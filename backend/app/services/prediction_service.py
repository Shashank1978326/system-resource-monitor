"""Resource utilization forecasting engine using weighted linear regression with historical tracking and accuracy evaluation."""

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database.connection import database
from app.database.models import HistoricalMetrics, HistoricalPrediction
from app.database.prediction_repository import PredictionRepository, PredictionStorageError
from app.database.repository import HistoryRepository
from app.schemas.predictions import (
    AccuracyMetricItem,
    GroupedAccuracyItem,
    HorizonAccuracyItem,
    PredictionAccuracyResponse,
    PredictionAnalyticsResponse,
    PredictionHistoryResponse,
    PredictionRecordResponse,
    PredictionResponse,
    PredictionTrendPoint,
    ResourceAccuracyItem,
    ResourcePrediction,
)
from app.services.history_service import HistoryService, HistoryStorageError

logger = logging.getLogger(__name__)

SUPPORTED_HORIZONS: dict[str, int] = {
    "5m": 5 * 60,
    "10m": 10 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
}

TIME_RANGES_SECONDS: dict[str, int] = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}

DEFAULT_MIN_SAMPLES = 5
DEFAULT_HISTORY_SAMPLE_LIMIT = 120
_HALF_LIFE_SECONDS = 600.0  # 10 minutes exponential decay
_DAMPING_TIMESCALE_SECONDS = 900.0  # 15 minutes trend saturation timescale

METRIC_CONFIGS = [
    {
        "resource": "cpu",
        "metric": "cpu_utilization",
        "unit": "percent",
        "attribute": "cpu_utilization_percent",
        "is_percent": True,
    },
    {
        "resource": "memory",
        "metric": "memory_utilization",
        "unit": "percent",
        "attribute": "ram_utilization_percent",
        "is_percent": True,
    },
    {
        "resource": "disk",
        "metric": "disk_utilization",
        "unit": "percent",
        "attribute": "disk_utilization_percent",
        "is_percent": True,
    },
    {
        "resource": "network",
        "metric": "network_download",
        "unit": "bytes_per_second",
        "attribute": "network_download_speed",
        "is_percent": False,
    },
    {
        "resource": "network",
        "metric": "network_upload",
        "unit": "bytes_per_second",
        "attribute": "network_upload_speed",
        "is_percent": False,
    },
]

METRIC_ATTRIBUTES: dict[str, str] = {
    "cpu_utilization": "cpu_utilization_percent",
    "memory_utilization": "ram_utilization_percent",
    "disk_utilization": "disk_utilization_percent",
    "network_download": "network_download_speed",
    "network_upload": "network_upload_speed",
}


def _calculate_weighted_regression(
    samples: list[tuple[datetime, float]],
    horizon_seconds: int,
    is_percent: bool,
) -> tuple[float, float, float, float, float]:
    """Calculate exponentially weighted linear regression forecast and confidence intervals.

    Returns:
        (predicted_value, lower_bound, upper_bound, confidence_score, r_squared)
    """
    n = len(samples)
    t_last = samples[-1][0]
    decay_rate = math.log(2.0) / _HALF_LIFE_SECONDS

    weights: list[float] = []
    x_values: list[float] = []
    y_values: list[float] = []

    for t, y in samples:
        dt = (t - t_last).total_seconds()
        w = math.exp(decay_rate * dt)  # dt <= 0, so w in (0, 1]
        weights.append(w)
        x_values.append(dt)
        y_values.append(y)

    total_w = sum(weights)
    if total_w <= 0.0:
        total_w = 1.0

    x_mean = sum(w * x for w, x in zip(weights, x_values, strict=False)) / total_w
    y_mean = sum(w * y for w, y in zip(weights, y_values, strict=False)) / total_w

    var_x = sum(w * (x - x_mean) ** 2 for w, x in zip(weights, x_values, strict=False))
    cov_xy = sum(
        w * (x - x_mean) * (y - y_mean)
        for w, x, y in zip(weights, x_values, y_values, strict=False)
    )
    var_y = sum(w * (y - y_mean) ** 2 for w, y in zip(weights, y_values, strict=False))

    if var_x < 1e-9 or var_y < 1e-9:
        slope = 0.0
        intercept = y_mean
        r_squared = 1.0
        std_err = 0.0
    else:
        slope = cov_xy / var_x
        intercept = y_mean - slope * x_mean
        ss_res = sum(
            w * (y - (slope * x + intercept)) ** 2
            for w, x, y in zip(weights, x_values, y_values, strict=False)
        )
        r_squared = max(0.0, min(1.0, 1.0 - (ss_res / var_y)))
        std_err = math.sqrt(ss_res / total_w)

    # Trend damping over horizon
    h_eff = _DAMPING_TIMESCALE_SECONDS * (
        1.0 - math.exp(-horizon_seconds / _DAMPING_TIMESCALE_SECONDS)
    )
    raw_pred = intercept + slope * h_eff

    # Horizon uncertainty expansion
    h_uncertainty = std_err * math.sqrt(1.0 + (horizon_seconds / 600.0))
    raw_lower = raw_pred - 1.96 * h_uncertainty
    raw_upper = raw_pred + 1.96 * h_uncertainty

    # Boundary clamping
    if is_percent:
        pred_clamped = round(max(0.0, min(100.0, raw_pred)), 2)
        lower_clamped = round(max(0.0, min(100.0, raw_lower)), 2)
        upper_clamped = round(max(0.0, min(100.0, raw_upper)), 2)
    else:
        pred_clamped = round(max(0.0, raw_pred), 2)
        lower_clamped = round(max(0.0, raw_lower), 2)
        upper_clamped = round(max(0.0, raw_upper), 2)

    if lower_clamped > upper_clamped:
        lower_clamped, upper_clamped = upper_clamped, lower_clamped

    # Statistical confidence score
    sample_factor = min(1.0, n / 20.0)
    horizon_factor = math.exp(-horizon_seconds / 3600.0)
    confidence = round(
        max(0.05, min(1.0, r_squared * sample_factor * horizon_factor)), 2
    )

    return pred_clamped, lower_clamped, upper_clamped, confidence, r_squared


def _compute_metrics(
    records: list[HistoricalPrediction], pending_count: int
) -> AccuracyMetricItem:
    """Compute MAE, RMSE, MAPE and average confidence over a set of evaluated records."""
    if not records:
        return AccuracyMetricItem(
            mae=None,
            rmse=None,
            mape=None,
            evaluated_count=0,
            pending_count=pending_count,
            average_confidence=None,
        )

    abs_errors = [r.absolute_error for r in records if r.absolute_error is not None]
    mae = round(sum(abs_errors) / len(abs_errors), 4) if abs_errors else None
    rmse = (
        round(math.sqrt(sum(e**2 for e in abs_errors) / len(abs_errors)), 4)
        if abs_errors
        else None
    )

    pct_errors = [r.percentage_error for r in records if r.percentage_error is not None]
    mape = round(sum(pct_errors) / len(pct_errors), 4) if pct_errors else None

    conf_scores = [r.confidence_score for r in records if r.confidence_score is not None]
    avg_conf = (
        round(sum(conf_scores) / len(conf_scores), 4) if conf_scores else None
    )

    return AccuracyMetricItem(
        mae=mae,
        rmse=rmse,
        mape=mape,
        evaluated_count=len(records),
        pending_count=pending_count,
        average_confidence=avg_conf,
    )


class PredictionService:
    """Predict future resource utilization and track accuracy over time."""

    def __init__(
        self,
        repository: HistoryRepository | None = None,
        prediction_repository: PredictionRepository | None = None,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> None:
        self._repository = repository
        self._prediction_repository = prediction_repository
        self.min_samples = min_samples

    def set_repository(self, repository: HistoryRepository | None) -> None:
        """Inject history repository for testing or initialization."""
        self._repository = repository

    def set_prediction_repository(
        self, prediction_repository: PredictionRepository | None
    ) -> None:
        """Inject prediction repository for testing or initialization."""
        self._prediction_repository = prediction_repository

    @property
    def prediction_repository(self) -> PredictionRepository:
        """Get or initialize the PredictionRepository."""
        if self._prediction_repository is None:
            self._prediction_repository = PredictionRepository(database.session_factory)
        return self._prediction_repository

    def _get_records(
        self, limit: int = DEFAULT_HISTORY_SAMPLE_LIMIT
    ) -> list[HistoricalMetrics]:
        """Fetch chronological historical records safely from repository or database."""
        repo = self._repository
        if repo is None:
            from app.services.history_service import history_service

            repo = getattr(history_service, "repository", None)
            if repo is None:
                repo = HistoryRepository(database.session_factory, database.path)
        try:
            return repo.get_recent_records(limit=limit)
        except (HistoryStorageError, SQLAlchemyError) as exc:
            logger.exception("Failed to read historical metrics for prediction")
            raise PredictionStorageError("Unable to access historical metrics") from exc

    def get_predictions(
        self,
        *,
        resource: str | None = None,
        horizon: str = "15m",
        auto_record: bool = True,
    ) -> PredictionResponse:
        """Forecast future utilization for requested resources over the given horizon."""
        if horizon not in SUPPORTED_HORIZONS:
            valid = ", ".join(SUPPORTED_HORIZONS.keys())
            raise ValueError(
                f"Invalid prediction horizon: '{horizon}'. Supported horizons: {valid}"
            )

        horizon_seconds = SUPPORTED_HORIZONS[horizon]
        now = datetime.now(timezone.utc)

        # Validate resource filter
        valid_resources = {
            "cpu",
            "memory",
            "disk",
            "network",
            "network_download",
            "network_upload",
            "all",
            None,
        }
        if resource not in valid_resources:
            raise ValueError(
                f"Unsupported resource: '{resource}'. "
                f"Supported resources: cpu, memory, disk, network, network_download, network_upload"
            )

        # Filter metric configurations
        selected_configs = []
        for cfg in METRIC_CONFIGS:
            if resource is None or resource == "all":
                selected_configs.append(cfg)
            elif resource == "network" and cfg["resource"] == "network":
                selected_configs.append(cfg)
            elif resource == cfg["resource"] and cfg["resource"] != "network":
                selected_configs.append(cfg)
            elif resource == cfg["metric"]:
                selected_configs.append(cfg)

        records = self._get_records()
        predictions: list[ResourcePrediction] = []

        for cfg in selected_configs:
            attr = cfg["attribute"]
            is_pct = cfg["is_percent"]

            # Filter non-null, finite samples
            samples: list[tuple[datetime, float]] = []
            for r in records:
                val = getattr(r, attr, None)
                if val is not None and math.isfinite(float(val)):
                    ts = r.timestamp
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    samples.append((ts, float(val)))

            # Sort chronologically just in case
            samples.sort(key=lambda s: s[0])
            sample_count = len(samples)

            if sample_count < self.min_samples:
                curr_val = round(samples[-1][1], 2) if samples else None
                pred_ts = (now + timedelta(seconds=horizon_seconds)).isoformat()
                predictions.append(
                    ResourcePrediction(
                        resource=cfg["resource"],
                        metric=cfg["metric"],
                        unit=cfg["unit"],
                        horizon=horizon,
                        horizon_seconds=horizon_seconds,
                        current_value=curr_val,
                        predicted_value=None,
                        prediction_timestamp=pred_ts,
                        status="insufficient_data",
                        model="exponentially_weighted_linear_regression",
                        sample_count=sample_count,
                        confidence_score=None,
                        lower_bound=None,
                        upper_bound=None,
                        trend=None,
                        message=(
                            f"Insufficient historical data: {sample_count} sample(s) available "
                            f"(minimum required: {self.min_samples})"
                        ),
                    )
                )
                continue

            curr_val = round(samples[-1][1], 2)
            t_last = samples[-1][0]
            pred_ts = (t_last + timedelta(seconds=horizon_seconds)).isoformat()

            pred_val, lower, upper, conf, _ = _calculate_weighted_regression(
                samples=samples,
                horizon_seconds=horizon_seconds,
                is_percent=is_pct,
            )

            diff = pred_val - curr_val
            threshold = 0.5 if is_pct else 1024.0
            if diff > threshold:
                trend = "increasing"
            elif diff < -threshold:
                trend = "decreasing"
            else:
                trend = "stable"

            predictions.append(
                ResourcePrediction(
                    resource=cfg["resource"],
                    metric=cfg["metric"],
                    unit=cfg["unit"],
                    horizon=horizon,
                    horizon_seconds=horizon_seconds,
                    current_value=curr_val,
                    predicted_value=pred_val,
                    prediction_timestamp=pred_ts,
                    status="available",
                    model="exponentially_weighted_linear_regression",
                    sample_count=sample_count,
                    confidence_score=conf,
                    lower_bound=lower,
                    upper_bound=upper,
                    trend=trend,
                    message=f"Forecast generated using {sample_count} historical samples",
                )
            )

        # Feature 9C: Automatic prediction tracking & background evaluation
        if auto_record:
            try:
                self.record_predictions(predictions, horizon, generated_at=now)
                self.evaluate_pending_predictions(as_of_time=now)
            except Exception:
                logger.exception("Non-fatal error during prediction recording or evaluation")

        return PredictionResponse(
            horizon=horizon,
            horizon_seconds=horizon_seconds,
            generated_at=now.isoformat(),
            predictions=predictions,
        )

    # -----------------------------------------------------------------------
    # Feature 9C: Tracking, Matching, and Accuracy Evaluation
    # -----------------------------------------------------------------------

    def record_prediction(
        self,
        pred: ResourcePrediction,
        horizon: str,
        generated_at: datetime | None = None,
        force: bool = False,
    ) -> HistoricalPrediction | None:
        """Store a single prediction with duplicate prevention."""
        if pred.status != "available" or pred.predicted_value is None:
            return None

        gen_at = generated_at or datetime.now(timezone.utc)
        target_ts = datetime.fromisoformat(pred.prediction_timestamp)
        if target_ts.tzinfo is None:
            target_ts = target_ts.replace(tzinfo=timezone.utc)

        repo = self.prediction_repository
        if not force:
            dup = repo.find_duplicate(
                metric=pred.metric,
                horizon=horizon,
                target_timestamp=target_ts,
                window_seconds=30,
            )
            if dup is not None:
                return dup

        return repo.insert_prediction(
            resource=pred.resource,
            metric=pred.metric,
            unit=pred.unit,
            horizon=horizon,
            horizon_seconds=pred.horizon_seconds,
            generated_at=gen_at,
            target_timestamp=target_ts,
            current_value=pred.current_value,
            predicted_value=pred.predicted_value,
            lower_bound=pred.lower_bound,
            upper_bound=pred.upper_bound,
            confidence_score=pred.confidence_score,
            model=pred.model,
        )

    def record_predictions(
        self,
        predictions: list[ResourcePrediction],
        horizon: str,
        generated_at: datetime | None = None,
        force: bool = False,
    ) -> list[HistoricalPrediction]:
        """Store a batch of predictions, skipping duplicates."""
        stored: list[HistoricalPrediction] = []
        for pred in predictions:
            rec = self.record_prediction(
                pred, horizon=horizon, generated_at=generated_at, force=force
            )
            if rec is not None:
                stored.append(rec)
        return stored

    def evaluate_pending_predictions(
        self,
        as_of_time: datetime | None = None,
        tolerance_seconds: int = 120,
    ) -> int:
        """Compare pending predictions with actual historical measurements.

        Boundary enforcement: Only evaluates predictions whose target_timestamp <= as_of_time.
        Returns the number of predictions evaluated.
        """
        now = as_of_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        repo = self.prediction_repository
        pending = repo.get_pending_predictions(before_timestamp=now)
        if not pending:
            return 0

        # Retrieve session factory for historical metric lookups
        session_factory = database.session_factory
        evaluated_count = 0

        for pred in pending:
            # Enforce target timestamp rule
            target_ts = pred.target_timestamp
            if target_ts.tzinfo is None:
                target_ts = target_ts.replace(tzinfo=timezone.utc)
            if target_ts > now:
                continue

            attr = METRIC_ATTRIBUTES.get(pred.metric)
            if not attr:
                continue

            # Query historical metrics in tolerance window [target_ts - tol, target_ts + tol]
            start_t = target_ts - timedelta(seconds=tolerance_seconds)
            end_t = target_ts + timedelta(seconds=tolerance_seconds)

            with session_factory() as session:
                stmt = (
                    select(HistoricalMetrics)
                    .where(
                        HistoricalMetrics.timestamp >= start_t,
                        HistoricalMetrics.timestamp <= end_t,
                    )
                    .order_by(HistoricalMetrics.timestamp.asc())
                )
                candidates = list(session.scalars(stmt))

            if candidates:
                # Find candidate closest to target_ts
                def _diff(c: HistoricalMetrics) -> float:
                    ts = c.timestamp
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    return abs((ts - target_ts).total_seconds())

                best = min(candidates, key=_diff)
                raw_val = getattr(best, attr, None)
                if raw_val is not None and math.isfinite(float(raw_val)):
                    actual_val = round(float(raw_val), 2)
                    abs_err = round(abs(actual_val - pred.predicted_value), 4)

                    # Percentage error: handle zero actual value safely
                    if abs(actual_val) > 1e-6:
                        pct_err = round((abs_err / abs(actual_val)) * 100.0, 4)
                    else:
                        pct_err = 0.0 if abs_err == 0.0 else None

                    repo.update_evaluation(
                        prediction_id=pred.prediction_id,
                        actual_value=actual_val,
                        absolute_error=abs_err,
                        percentage_error=pct_err,
                        evaluation_status="evaluated",
                        evaluated_at=now,
                    )
                    evaluated_count += 1
                    continue

            # If no actual sample is found and target is far in the past (> 2 * tolerance)
            if (now - target_ts).total_seconds() > tolerance_seconds * 2:
                repo.update_evaluation(
                    prediction_id=pred.prediction_id,
                    actual_value=None,
                    absolute_error=None,
                    percentage_error=None,
                    evaluation_status="missing_actual",
                    evaluated_at=now,
                )

        return evaluated_count

    def get_accuracy(
        self,
        *,
        resource: str | None = None,
        horizon: str | None = None,
        time_range: str = "24h",
    ) -> PredictionAccuracyResponse:
        """Calculate MAE, RMSE, MAPE, evaluated & pending counts grouped by resource and horizon."""
        now = datetime.now(timezone.utc)
        range_secs = TIME_RANGES_SECONDS.get(time_range, 24 * 3600)
        start_time = now - timedelta(seconds=range_secs) if time_range != "all" else None

        repo = self.prediction_repository
        evaluated = repo.get_evaluated_predictions(
            resource=resource,
            horizon=horizon,
            start_time=start_time,
        )
        pending_count = repo.count_pending(resource=resource, horizon=horizon)

        overall = _compute_metrics(evaluated, pending_count)

        # Group by resource
        by_resource: list[ResourceAccuracyItem] = []
        for res_name in ["cpu", "memory", "disk", "network"]:
            if resource and resource != "all" and resource != res_name:
                continue
            res_eval = [r for r in evaluated if r.resource == res_name]
            res_pend = repo.count_pending(resource=res_name, horizon=horizon)
            res_m = _compute_metrics(res_eval, res_pend)
            by_resource.append(
                ResourceAccuracyItem(
                    resource=res_name,
                    mae=res_m.mae,
                    rmse=res_m.rmse,
                    mape=res_m.mape,
                    evaluated_count=res_m.evaluated_count,
                    pending_count=res_m.pending_count,
                    average_confidence=res_m.average_confidence,
                )
            )

        # Group by horizon
        by_horizon: list[HorizonAccuracyItem] = []
        for h_name, h_secs in SUPPORTED_HORIZONS.items():
            if horizon and horizon != "all" and horizon != h_name:
                continue
            h_eval = [r for r in evaluated if r.horizon == h_name]
            h_pend = repo.count_pending(resource=resource, horizon=h_name)
            h_m = _compute_metrics(h_eval, h_pend)
            by_horizon.append(
                HorizonAccuracyItem(
                    horizon=h_name,
                    horizon_seconds=h_secs,
                    mae=h_m.mae,
                    rmse=h_m.rmse,
                    mape=h_m.mape,
                    evaluated_count=h_m.evaluated_count,
                    pending_count=h_m.pending_count,
                    average_confidence=h_m.average_confidence,
                )
            )

        # Group by (resource, metric, horizon)
        grouped_dict: dict[tuple[str, str, str], list[HistoricalPrediction]] = {}
        for r in evaluated:
            key = (r.resource, r.metric, r.horizon)
            grouped_dict.setdefault(key, []).append(r)

        grouped: list[GroupedAccuracyItem] = []
        for (res, met, hor), recs in grouped_dict.items():
            pend = repo.count_pending(resource=res, metric=met, horizon=hor)
            gm = _compute_metrics(recs, pend)
            grouped.append(
                GroupedAccuracyItem(
                    resource=res,
                    metric=met,
                    horizon=hor,
                    mae=gm.mae,
                    rmse=gm.rmse,
                    mape=gm.mape,
                    evaluated_count=gm.evaluated_count,
                    pending_count=gm.pending_count,
                    average_confidence=gm.average_confidence,
                )
            )

        return PredictionAccuracyResponse(
            range=time_range,
            overall=overall,
            by_resource=by_resource,
            by_horizon=by_horizon,
            grouped=grouped,
        )

    def get_analytics(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        horizon: str | None = None,
        time_range: str = "24h",
    ) -> PredictionAnalyticsResponse:
        """Fetch summary accuracy, breakdowns, and actual vs predicted trend time-series."""
        now = datetime.now(timezone.utc)
        range_secs = TIME_RANGES_SECONDS.get(time_range, 24 * 3600)
        start_time = now - timedelta(seconds=range_secs) if time_range != "all" else None

        # Trigger evaluation of mature predictions first
        self.evaluate_pending_predictions(as_of_time=now)

        repo = self.prediction_repository
        evaluated = repo.get_evaluated_predictions(
            resource=resource,
            metric=metric,
            horizon=horizon,
            start_time=start_time,
            limit=200,
        )
        pending_count = repo.count_pending(
            resource=resource, metric=metric, horizon=horizon
        )

        summary = _compute_metrics(evaluated, pending_count)

        # Resource breakdown
        by_resource: list[ResourceAccuracyItem] = []
        for res_name in ["cpu", "memory", "disk", "network"]:
            if resource and resource != "all" and resource != res_name:
                continue
            res_eval = [r for r in evaluated if r.resource == res_name]
            res_pend = repo.count_pending(resource=res_name, horizon=horizon)
            res_m = _compute_metrics(res_eval, res_pend)
            by_resource.append(
                ResourceAccuracyItem(
                    resource=res_name,
                    mae=res_m.mae,
                    rmse=res_m.rmse,
                    mape=res_m.mape,
                    evaluated_count=res_m.evaluated_count,
                    pending_count=res_m.pending_count,
                    average_confidence=res_m.average_confidence,
                )
            )

        # Horizon breakdown
        by_horizon: list[HorizonAccuracyItem] = []
        for h_name, h_secs in SUPPORTED_HORIZONS.items():
            if horizon and horizon != "all" and horizon != h_name:
                continue
            h_eval = [r for r in evaluated if r.horizon == h_name]
            h_pend = repo.count_pending(resource=resource, horizon=h_name)
            h_m = _compute_metrics(h_eval, h_pend)
            by_horizon.append(
                HorizonAccuracyItem(
                    horizon=h_name,
                    horizon_seconds=h_secs,
                    mae=h_m.mae,
                    rmse=h_m.rmse,
                    mape=h_m.mape,
                    evaluated_count=h_m.evaluated_count,
                    pending_count=h_m.pending_count,
                    average_confidence=h_m.average_confidence,
                )
            )

        # Trend points
        trend: list[PredictionTrendPoint] = []
        for r in evaluated:
            ts = r.target_timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            trend.append(
                PredictionTrendPoint(
                    timestamp=ts.isoformat(),
                    resource=r.resource,
                    metric=r.metric,
                    unit=r.unit,
                    horizon=r.horizon,
                    predicted_value=r.predicted_value,
                    actual_value=r.actual_value,
                    absolute_error=r.absolute_error,
                    percentage_error=r.percentage_error,
                    evaluation_status=r.evaluation_status,
                )
            )

        return PredictionAnalyticsResponse(
            range=time_range,
            resource=resource,
            metric=metric,
            horizon=horizon,
            summary=summary,
            by_resource=by_resource,
            by_horizon=by_horizon,
            trend=trend,
        )

    def get_history(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        horizon: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> PredictionHistoryResponse:
        """Fetch paginated historical predictions."""
        repo = self.prediction_repository
        records, total = repo.get_history(
            resource=resource,
            metric=metric,
            horizon=horizon,
            status=status,
            page=page,
            page_size=page_size,
        )

        total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1

        items: list[PredictionRecordResponse] = []
        for r in records:
            gen_ts = r.generated_at
            if gen_ts.tzinfo is None:
                gen_ts = gen_ts.replace(tzinfo=timezone.utc)
            target_ts = r.target_timestamp
            if target_ts.tzinfo is None:
                target_ts = target_ts.replace(tzinfo=timezone.utc)
            eval_ts = r.evaluated_at
            if eval_ts is not None and eval_ts.tzinfo is None:
                eval_ts = eval_ts.replace(tzinfo=timezone.utc)

            items.append(
                PredictionRecordResponse(
                    id=r.id,
                    prediction_id=r.prediction_id,
                    resource=r.resource,
                    metric=r.metric,
                    unit=r.unit,
                    horizon=r.horizon,
                    horizon_seconds=r.horizon_seconds,
                    generated_at=gen_ts.isoformat(),
                    target_timestamp=target_ts.isoformat(),
                    current_value=r.current_value,
                    predicted_value=r.predicted_value,
                    lower_bound=r.lower_bound,
                    upper_bound=r.upper_bound,
                    confidence_score=r.confidence_score,
                    model=r.model,
                    actual_value=r.actual_value,
                    absolute_error=r.absolute_error,
                    percentage_error=r.percentage_error,
                    evaluation_status=r.evaluation_status,
                    evaluated_at=eval_ts.isoformat() if eval_ts else None,
                )
            )

        return PredictionHistoryResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )


prediction_service = PredictionService()
