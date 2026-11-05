"""Pydantic schemas for resource prediction API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourcePrediction(BaseModel):
    """Forecasted future resource utilization for a single metric."""

    model_config = ConfigDict(extra="forbid")

    resource: str = Field(description="Resource category (cpu, memory, disk, network)")
    metric: str = Field(description="Resource metric identifier")
    unit: str = Field(description="Unit of measurement (percent, bytes_per_second)")
    horizon: str = Field(description="Prediction horizon (5m, 10m, 15m, 30m)")
    horizon_seconds: int = Field(description="Prediction horizon duration in seconds")
    current_value: float | None = Field(default=None, description="Most recent actual measurement")
    predicted_value: float | None = Field(default=None, description="Forecasted future value")
    prediction_timestamp: str = Field(description="Target forecast timestamp in ISO format")
    status: Literal["available", "insufficient_data", "error"] = Field(
        description="Reliability and availability status of the prediction"
    )
    model: str = Field(description="Statistical forecasting model used")
    sample_count: int = Field(description="Number of historical samples used for training")
    confidence_score: float | None = Field(
        default=None,
        description="Statistical confidence score between 0.0 and 1.0",
    )
    lower_bound: float | None = Field(
        default=None,
        description="Estimated lower bound of forecast interval",
    )
    upper_bound: float | None = Field(
        default=None,
        description="Estimated upper bound of forecast interval",
    )
    trend: Literal["increasing", "decreasing", "stable"] | None = Field(
        default=None,
        description="Predicted directional trend",
    )
    message: str = Field(description="Status description or explanation")


class PredictionResponse(BaseModel):
    """Response payload for GET /api/predictions containing multiple resource forecasts."""

    model_config = ConfigDict(extra="forbid")

    horizon: str = Field(description="Selected prediction horizon (5m, 10m, 15m, 30m)")
    horizon_seconds: int = Field(description="Horizon length in seconds")
    generated_at: str = Field(description="Timestamp when the forecast was computed")
    predictions: list[ResourcePrediction] = Field(description="Resource utilization forecasts")


# ---------------------------------------------------------------------------
# Feature 9C: Prediction Analytics and Accuracy Evaluation Schemas
# ---------------------------------------------------------------------------


class PredictionRecordResponse(BaseModel):
    """One persisted prediction record with optional evaluation telemetry."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(description="Database row ID")
    prediction_id: str = Field(description="Unique prediction UUID")
    resource: str = Field(description="Resource type (cpu, memory, disk, network)")
    metric: str = Field(description="Metric identifier")
    unit: str = Field(description="Measurement unit (percent, bytes_per_second)")
    horizon: str = Field(description="Forecast horizon (5m, 10m, 15m, 30m)")
    horizon_seconds: int = Field(description="Horizon duration in seconds")
    generated_at: str = Field(description="Forecast generation timestamp (ISO UTC)")
    target_timestamp: str = Field(description="Forecast target timestamp (ISO UTC)")
    current_value: float | None = Field(default=None, description="Measured value at generation time")
    predicted_value: float = Field(description="Predicted target value")
    lower_bound: float | None = Field(default=None, description="Lower prediction bound")
    upper_bound: float | None = Field(default=None, description="Upper prediction bound")
    confidence_score: float | None = Field(default=None, description="Statistical confidence score")
    model: str = Field(description="Forecasting model used")
    actual_value: float | None = Field(default=None, description="Actual measured value once target time has passed")
    absolute_error: float | None = Field(default=None, description="Absolute error |actual - predicted|")
    percentage_error: float | None = Field(default=None, description="Percentage error (|actual - predicted| / |actual|) * 100")
    evaluation_status: Literal["pending", "evaluated", "missing_actual"] = Field(
        description="Evaluation status"
    )
    evaluated_at: str | None = Field(default=None, description="Evaluation timestamp (ISO UTC)")


class PredictionHistoryResponse(BaseModel):
    """Paginated list of historical predictions."""

    model_config = ConfigDict(extra="forbid")

    items: list[PredictionRecordResponse] = Field(description="Historical prediction records")
    total: int = Field(description="Total matching prediction records")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total available pages")


class AccuracyMetricItem(BaseModel):
    """Accuracy metrics for a set of predictions."""

    model_config = ConfigDict(extra="forbid")

    mae: float | None = Field(default=None, description="Mean Absolute Error")
    rmse: float | None = Field(default=None, description="Root Mean Squared Error")
    mape: float | None = Field(default=None, description="Mean Absolute Percentage Error (%)")
    evaluated_count: int = Field(description="Number of evaluated predictions")
    pending_count: int = Field(description="Number of pending predictions")
    average_confidence: float | None = Field(default=None, description="Average statistical confidence score")


class ResourceAccuracyItem(AccuracyMetricItem):
    """Accuracy metrics grouped by resource category."""

    resource: str = Field(description="Resource category (cpu, memory, disk, network)")


class HorizonAccuracyItem(AccuracyMetricItem):
    """Accuracy metrics grouped by forecast horizon."""

    horizon: str = Field(description="Prediction horizon (5m, 10m, 15m, 30m)")
    horizon_seconds: int = Field(description="Horizon length in seconds")


class GroupedAccuracyItem(AccuracyMetricItem):
    """Accuracy metrics grouped by resource and horizon."""

    resource: str = Field(description="Resource category")
    metric: str = Field(description="Metric identifier")
    horizon: str = Field(description="Prediction horizon")


class PredictionAccuracyResponse(BaseModel):
    """Aggregated prediction accuracy response."""

    model_config = ConfigDict(extra="forbid")

    range: str = Field(description="Evaluation time range")
    overall: AccuracyMetricItem = Field(description="Overall accuracy summary")
    by_resource: list[ResourceAccuracyItem] = Field(description="Accuracy metrics grouped by resource")
    by_horizon: list[HorizonAccuracyItem] = Field(description="Accuracy metrics grouped by horizon")
    grouped: list[GroupedAccuracyItem] = Field(description="Accuracy metrics grouped by resource and horizon")


class PredictionTrendPoint(BaseModel):
    """Data point representing a forecast vs actual measurement over time."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(description="Target forecast timestamp (ISO UTC)")
    resource: str = Field(description="Resource category")
    metric: str = Field(description="Metric identifier")
    unit: str = Field(description="Measurement unit")
    horizon: str = Field(description="Prediction horizon")
    predicted_value: float = Field(description="Predicted value")
    actual_value: float | None = Field(default=None, description="Actual measured value")
    absolute_error: float | None = Field(default=None, description="Absolute error")
    percentage_error: float | None = Field(default=None, description="Percentage error")
    evaluation_status: str = Field(description="Evaluation status")


class PredictionAnalyticsResponse(BaseModel):
    """Comprehensive prediction analytics response for dashboard visualization."""

    model_config = ConfigDict(extra="forbid")

    range: str = Field(description="Selected evaluation time range")
    resource: str | None = Field(default=None, description="Resource filter if applied")
    metric: str | None = Field(default=None, description="Metric filter if applied")
    horizon: str | None = Field(default=None, description="Horizon filter if applied")
    summary: AccuracyMetricItem = Field(description="Overall accuracy summary for filter criteria")
    by_resource: list[ResourceAccuracyItem] = Field(description="Resource accuracy breakdown")
    by_horizon: list[HorizonAccuracyItem] = Field(description="Horizon accuracy breakdown")
    trend: list[PredictionTrendPoint] = Field(description="Chronological forecast vs actual comparison data")


