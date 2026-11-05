"""Resource prediction and accuracy evaluation endpoints."""

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.predictions import (
    PredictionAccuracyResponse,
    PredictionAnalyticsResponse,
    PredictionHistoryResponse,
    PredictionResponse,
)
from app.services.prediction_service import (
    SUPPORTED_HORIZONS,
    TIME_RANGES_SECONDS,
    PredictionStorageError,
    prediction_service,
)

router = APIRouter(prefix="/api/predictions", tags=["predictions"])

VALID_RESOURCES = {"cpu", "memory", "disk", "network", "all", None}
VALID_METRICS = {
    "cpu_utilization",
    "memory_utilization",
    "disk_utilization",
    "network_download",
    "network_upload",
    "all",
    None,
}
VALID_STATUSES = {"pending", "evaluated", "missing_actual", "all", None}


def _storage_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Prediction historical storage is temporarily unavailable",
    )


@router.get(
    "/analytics",
    response_model=PredictionAnalyticsResponse,
    summary="Prediction analytics, summary accuracy, and trend time-series",
)
def read_prediction_analytics(
    resource: str | None = Query(
        default=None,
        description="Optional resource filter: cpu, memory, disk, network, all",
    ),
    metric: str | None = Query(
        default=None,
        description="Optional metric filter: cpu_utilization, memory_utilization, disk_utilization, network_download, network_upload",
    ),
    horizon: str | None = Query(
        default=None,
        description="Optional horizon filter: 5m, 10m, 15m, 30m, all",
    ),
    range: str = Query(
        default="24h",
        description="Time window: 1h, 6h, 24h, 7d, 30d, all",
    ),
) -> PredictionAnalyticsResponse:
    """Return MAE, RMSE, MAPE, evaluated & pending counts, and forecast vs actual trend."""
    if resource not in VALID_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource filter: '{resource}'. Valid resources: cpu, memory, disk, network, all",
        )
    if metric not in VALID_METRICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metric filter: '{metric}'.",
        )
    if horizon not in {*SUPPORTED_HORIZONS.keys(), "all", None}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid horizon filter: '{horizon}'. Valid horizons: 5m, 10m, 15m, 30m, all",
        )
    if range not in {*TIME_RANGES_SECONDS.keys(), "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time range: '{range}'. Valid ranges: 1h, 6h, 24h, 7d, 30d, all",
        )

    try:
        return prediction_service.get_analytics(
            resource=resource,
            metric=metric,
            horizon=horizon,
            time_range=range,
        )
    except PredictionStorageError as exc:
        raise _storage_error() from exc


@router.get(
    "/history",
    response_model=PredictionHistoryResponse,
    summary="Paginated prediction history records",
)
def read_prediction_history(
    resource: str | None = Query(default=None, description="Filter by resource"),
    metric: str | None = Query(default=None, description="Filter by metric"),
    horizon: str | None = Query(default=None, description="Filter by horizon"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by evaluation status: pending, evaluated, missing_actual, all",
    ),
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(
        default=20, ge=1, le=100, description="Items per page (max 100)"
    ),
) -> PredictionHistoryResponse:
    """Return paginated historical forecast records with actual measurement comparisons."""
    if resource not in VALID_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource filter: '{resource}'.",
        )
    if metric not in VALID_METRICS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid metric filter: '{metric}'.",
        )
    if horizon not in {*SUPPORTED_HORIZONS.keys(), "all", None}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid horizon filter: '{horizon}'.",
        )
    if status_filter not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status filter: '{status_filter}'. Valid statuses: pending, evaluated, missing_actual, all",
        )

    try:
        return prediction_service.get_history(
            resource=resource,
            metric=metric,
            horizon=horizon,
            status=status_filter,
            page=page,
            page_size=page_size,
        )
    except PredictionStorageError as exc:
        raise _storage_error() from exc


@router.get(
    "/accuracy",
    response_model=PredictionAccuracyResponse,
    summary="Prediction accuracy metrics (MAE, RMSE, MAPE) grouped by resource and horizon",
)
def read_prediction_accuracy(
    resource: str | None = Query(default=None, description="Filter by resource"),
    horizon: str | None = Query(default=None, description="Filter by horizon"),
    range: str = Query(
        default="24h",
        description="Time range: 1h, 6h, 24h, 7d, 30d, all",
    ),
) -> PredictionAccuracyResponse:
    """Return overall, per-resource, and per-horizon MAE, RMSE, and MAPE metrics."""
    if resource not in VALID_RESOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid resource filter: '{resource}'.",
        )
    if horizon not in {*SUPPORTED_HORIZONS.keys(), "all", None}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid horizon filter: '{horizon}'.",
        )
    if range not in {*TIME_RANGES_SECONDS.keys(), "all"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid time range: '{range}'.",
        )

    try:
        return prediction_service.get_accuracy(
            resource=resource,
            horizon=horizon,
            time_range=range,
        )
    except PredictionStorageError as exc:
        raise _storage_error() from exc


@router.get(
    "",
    response_model=PredictionResponse,
    summary="Forecast future system resource utilization",
)
def read_predictions(
    resource: str | None = Query(
        default=None,
        description="Optional resource filter: cpu, memory, disk, network, network_download, network_upload",
    ),
    horizon: str = Query(
        default="15m",
        description="Forecast horizon: 5m, 10m, 15m, 30m",
    ),
) -> PredictionResponse:
    """Return future resource utilization forecasts for CPU, memory, disk, and network."""
    try:
        return prediction_service.get_predictions(
            resource=resource,
            horizon=horizon,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except PredictionStorageError as exc:
        raise _storage_error() from exc
