"""Comprehensive unit and integration tests for Feature 9C: Prediction Analytics and Accuracy Evaluation."""

import math
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database.connection import database, initialize_database
from app.database.models import HistoricalMetrics, HistoricalPrediction
from app.database.prediction_repository import PredictionRepository, PredictionStorageError
from app.main import app
from app.schemas.predictions import ResourcePrediction
from app.services.prediction_service import (
    SUPPORTED_HORIZONS,
    prediction_service,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure a clean database state before and after each test."""
    initialize_database()
    with database.session_factory.begin() as session:
        session.query(HistoricalPrediction).delete()
        session.query(HistoricalMetrics).delete()
    yield
    with database.session_factory.begin() as session:
        session.query(HistoricalPrediction).delete()
        session.query(HistoricalMetrics).delete()
    database.dispose()


def _insert_metric(
    timestamp: datetime,
    cpu: float | None = None,
    memory: float | None = None,
    disk: float | None = None,
    net_down: float | None = None,
    net_up: float | None = None,
) -> None:
    with database.session_factory.begin() as session:
        session.add(
            HistoricalMetrics(
                timestamp=timestamp,
                cpu_utilization_percent=cpu,
                ram_utilization_percent=memory,
                disk_utilization_percent=disk,
                network_download_speed=net_down,
                network_upload_speed=net_up,
            )
        )


def _insert_prediction(
    resource: str = "cpu",
    metric: str = "cpu_utilization",
    unit: str = "percent",
    horizon: str = "15m",
    horizon_seconds: int = 900,
    generated_at: datetime | None = None,
    target_timestamp: datetime | None = None,
    current_value: float = 30.0,
    predicted_value: float = 40.0,
    confidence_score: float = 0.85,
    actual_value: float | None = None,
    absolute_error: float | None = None,
    percentage_error: float | None = None,
    evaluation_status: str = "pending",
    evaluated_at: datetime | None = None,
    prediction_id: str | None = None,
) -> HistoricalPrediction:
    now = datetime.now(timezone.utc)
    gen = generated_at or (now - timedelta(minutes=20))
    target = target_timestamp or (gen + timedelta(seconds=horizon_seconds))
    repo = PredictionRepository(database.session_factory)
    rec = repo.insert_prediction(
        resource=resource,
        metric=metric,
        unit=unit,
        horizon=horizon,
        horizon_seconds=horizon_seconds,
        generated_at=gen,
        target_timestamp=target,
        current_value=current_value,
        predicted_value=predicted_value,
        confidence_score=confidence_score,
        prediction_id=prediction_id,
    )
    if evaluation_status != "pending" or actual_value is not None:
        repo.update_evaluation(
            prediction_id=rec.prediction_id,
            actual_value=actual_value,
            absolute_error=absolute_error,
            percentage_error=percentage_error,
            evaluation_status=evaluation_status,
            evaluated_at=evaluated_at or now,
        )
    return rec


# ---------------------------------------------------------------------------
# 1. Prediction Record Storage
# ---------------------------------------------------------------------------
def test_prediction_record_storage() -> None:
    now = datetime.now(timezone.utc)
    target = now + timedelta(minutes=15)
    pred = ResourcePrediction(
        resource="cpu",
        metric="cpu_utilization",
        unit="percent",
        horizon="15m",
        horizon_seconds=900,
        current_value=45.0,
        predicted_value=52.5,
        prediction_timestamp=target.isoformat(),
        status="available",
        model="exponentially_weighted_linear_regression",
        sample_count=25,
        confidence_score=0.91,
        lower_bound=48.0,
        upper_bound=57.0,
        trend="increasing",
        message="Forecast ready",
    )

    rec = prediction_service.record_prediction(pred, horizon="15m", generated_at=now)
    assert rec is not None
    assert rec.resource == "cpu"
    assert rec.metric == "cpu_utilization"
    assert rec.unit == "percent"
    assert rec.horizon == "15m"
    assert rec.horizon_seconds == 900
    assert rec.current_value == 45.0
    assert rec.predicted_value == 52.5
    assert rec.confidence_score == 0.91
    assert rec.evaluation_status == "pending"
    assert rec.actual_value is None
    assert rec.absolute_error is None
    assert rec.percentage_error is None


# ---------------------------------------------------------------------------
# 2. Duplicate Prevention
# ---------------------------------------------------------------------------
def test_duplicate_prevention() -> None:
    now = datetime.now(timezone.utc)
    target = now + timedelta(minutes=15)
    pred = ResourcePrediction(
        resource="cpu",
        metric="cpu_utilization",
        unit="percent",
        horizon="15m",
        horizon_seconds=900,
        current_value=40.0,
        predicted_value=45.0,
        prediction_timestamp=target.isoformat(),
        status="available",
        model="exponentially_weighted_linear_regression",
        sample_count=20,
        confidence_score=0.88,
        lower_bound=42.0,
        upper_bound=48.0,
        trend="increasing",
        message="Forecast ready",
    )

    # First call stores
    first = prediction_service.record_prediction(pred, horizon="15m", generated_at=now)
    assert first is not None

    # Immediate second call within 30s window skips storing duplicate
    second = prediction_service.record_prediction(pred, horizon="15m", generated_at=now)
    assert second is not None
    assert second.id == first.id  # Same existing record returned

    # Verify database has exactly 1 record
    repo = PredictionRepository(database.session_factory)
    history, total = repo.get_history()
    assert total == 1


# ---------------------------------------------------------------------------
# 3. Actual Measurement Matching & 4. Correct Absolute Error
# ---------------------------------------------------------------------------
def test_actual_measurement_matching_and_absolute_error() -> None:
    now = datetime.now(timezone.utc)
    gen_time = now - timedelta(minutes=20)
    target_time = gen_time + timedelta(minutes=15)  # 5 minutes in the past

    # Insert historical prediction: predicted 50% CPU
    pred_rec = _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        generated_at=gen_time,
        target_timestamp=target_time,
        predicted_value=50.0,
    )

    # Insert matching historical metric at target_time: actual 54.2% CPU
    _insert_metric(timestamp=target_time, cpu=54.2)

    # Evaluate pending predictions
    evaluated_count = prediction_service.evaluate_pending_predictions(as_of_time=now)
    assert evaluated_count == 1

    repo = PredictionRepository(database.session_factory)
    items, _ = repo.get_history()
    evaluated = items[0]

    assert evaluated.evaluation_status == "evaluated"
    assert evaluated.actual_value == 54.2
    # Absolute error = |54.2 - 50.0| = 4.2
    assert evaluated.absolute_error == 4.2
    assert evaluated.evaluated_at is not None


# ---------------------------------------------------------------------------
# 5. Correct Percentage Error Calculation
# ---------------------------------------------------------------------------
def test_correct_percentage_error_calculation() -> None:
    now = datetime.now(timezone.utc)
    gen_time = now - timedelta(minutes=20)
    target_time = gen_time + timedelta(minutes=15)

    _insert_prediction(
        resource="memory",
        metric="memory_utilization",
        generated_at=gen_time,
        target_timestamp=target_time,
        predicted_value=60.0,
    )

    # Actual = 80.0
    # Absolute error = |80.0 - 60.0| = 20.0
    # Percentage error = (20.0 / 80.0) * 100 = 25.0%
    _insert_metric(timestamp=target_time, memory=80.0)

    prediction_service.evaluate_pending_predictions(as_of_time=now)

    repo = PredictionRepository(database.session_factory)
    items, _ = repo.get_history()
    evaluated = items[0]

    assert evaluated.absolute_error == 20.0
    assert evaluated.percentage_error == 25.0


# ---------------------------------------------------------------------------
# 6. Zero Actual Value Handling (No ZeroDivisionError)
# ---------------------------------------------------------------------------
def test_zero_actual_value_handling() -> None:
    now = datetime.now(timezone.utc)
    gen_time = now - timedelta(minutes=20)
    target_time = gen_time + timedelta(minutes=15)

    _insert_prediction(
        resource="network",
        metric="network_download",
        unit="bytes_per_second",
        generated_at=gen_time,
        target_timestamp=target_time,
        predicted_value=1024.0,
    )

    # Actual download throughput is 0.0 bytes/sec
    _insert_metric(timestamp=target_time, net_down=0.0)

    # Evaluation must not raise ZeroDivisionError
    evaluated_count = prediction_service.evaluate_pending_predictions(as_of_time=now)
    assert evaluated_count == 1

    repo = PredictionRepository(database.session_factory)
    items, _ = repo.get_history()
    evaluated = items[0]

    assert evaluated.actual_value == 0.0
    assert evaluated.absolute_error == 1024.0
    # Percentage error with zero actual value is handled safely as None
    assert evaluated.percentage_error is None


# ---------------------------------------------------------------------------
# 7. MAE, 8. RMSE, and 9. MAPE Calculations
# ---------------------------------------------------------------------------
def test_mae_rmse_mape_calculation() -> None:
    now = datetime.now(timezone.utc)
    # Insert 3 evaluated predictions:
    # 1: actual=100, pred=90  -> abs_err=10, pct_err=10.0%
    # 2: actual=50,  pred=60  -> abs_err=10, pct_err=20.0%
    # 3: actual=200, pred=220 -> abs_err=20, pct_err=10.0%
    # MAE = (10 + 10 + 20) / 3 = 40 / 3 = 13.3333
    # RMSE = sqrt((10^2 + 10^2 + 20^2) / 3) = sqrt((100 + 100 + 400) / 3) = sqrt(200) = 14.1421
    # MAPE = (10.0 + 20.0 + 10.0) / 3 = 40.0 / 3 = 13.3333%

    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        predicted_value=90.0,
        actual_value=100.0,
        absolute_error=10.0,
        percentage_error=10.0,
        evaluation_status="evaluated",
    )
    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        predicted_value=60.0,
        actual_value=50.0,
        absolute_error=10.0,
        percentage_error=20.0,
        evaluation_status="evaluated",
    )
    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        predicted_value=220.0,
        actual_value=200.0,
        absolute_error=20.0,
        percentage_error=10.0,
        evaluation_status="evaluated",
    )

    acc = prediction_service.get_accuracy(resource="cpu", time_range="24h")
    assert acc.overall.evaluated_count == 3
    assert acc.overall.mae == pytest.approx(13.3333, abs=0.001)
    assert acc.overall.rmse == pytest.approx(14.1421, abs=0.001)
    assert acc.overall.mape == pytest.approx(13.3333, abs=0.001)


# ---------------------------------------------------------------------------
# 10. Pending Prediction Handling
# ---------------------------------------------------------------------------
def test_pending_prediction_handling() -> None:
    now = datetime.now(timezone.utc)
    # Insert a future prediction: target is 10 minutes in the future
    target_future = now + timedelta(minutes=10)
    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        target_timestamp=target_future,
        predicted_value=35.0,
        evaluation_status="pending",
    )

    acc = prediction_service.get_accuracy(resource="cpu", time_range="24h")
    assert acc.overall.pending_count == 1
    assert acc.overall.evaluated_count == 0
    # No evaluated predictions -> accuracy metrics are None
    assert acc.overall.mae is None
    assert acc.overall.rmse is None
    assert acc.overall.mape is None


# ---------------------------------------------------------------------------
# 11. Boundary Enforcement: Not Evaluated Before Target Timestamps
# ---------------------------------------------------------------------------
def test_boundary_enforcement_never_evaluate_before_target() -> None:
    now = datetime.now(timezone.utc)
    target_future = now + timedelta(minutes=10)

    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        target_timestamp=target_future,
        predicted_value=45.0,
        evaluation_status="pending",
    )

    # Insert a metric now
    _insert_metric(timestamp=now, cpu=45.0)

    # Attempt evaluation as of 'now' (before target_timestamp)
    evaluated = prediction_service.evaluate_pending_predictions(as_of_time=now)
    assert evaluated == 0

    repo = PredictionRepository(database.session_factory)
    items, _ = repo.get_history()
    assert items[0].evaluation_status == "pending"
    assert items[0].actual_value is None


# ---------------------------------------------------------------------------
# 12. Resource and Horizon Filtering
# ---------------------------------------------------------------------------
def test_resource_and_horizon_filtering(client: TestClient) -> None:
    # Insert CPU 5m prediction
    _insert_prediction(
        resource="cpu",
        metric="cpu_utilization",
        horizon="5m",
        predicted_value=30.0,
        actual_value=32.0,
        absolute_error=2.0,
        percentage_error=6.25,
        evaluation_status="evaluated",
    )
    # Insert Memory 15m prediction
    _insert_prediction(
        resource="memory",
        metric="memory_utilization",
        horizon="15m",
        predicted_value=60.0,
        actual_value=65.0,
        absolute_error=5.0,
        percentage_error=7.69,
        evaluation_status="evaluated",
    )

    # Filter by resource=cpu
    res = client.get("/api/predictions/analytics?resource=cpu")
    assert res.status_code == 200
    data = res.json()
    assert data["resource"] == "cpu"
    assert data["summary"]["evaluated_count"] == 1
    assert data["summary"]["mae"] == 2.0

    # Filter by horizon=15m
    res = client.get("/api/predictions/analytics?horizon=15m")
    assert res.status_code == 200
    data = res.json()
    assert data["horizon"] == "15m"
    assert data["summary"]["evaluated_count"] == 1
    assert data["summary"]["mae"] == 5.0


# ---------------------------------------------------------------------------
# 13. Pagination in Prediction History
# ---------------------------------------------------------------------------
def test_prediction_history_pagination(client: TestClient) -> None:
    now = datetime.now(timezone.utc)
    # Insert 25 records
    for i in range(25):
        _insert_prediction(
            resource="cpu",
            metric="cpu_utilization",
            target_timestamp=now - timedelta(minutes=30 - i),
            predicted_value=float(20 + i),
            actual_value=float(22 + i),
            absolute_error=2.0,
            percentage_error=5.0,
            evaluation_status="evaluated",
        )

    # Page 1, page_size 10
    res1 = client.get("/api/predictions/history?page=1&page_size=10")
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["total"] == 25
    assert d1["page"] == 1
    assert d1["page_size"] == 10
    assert d1["total_pages"] == 3
    assert len(d1["items"]) == 10

    # Page 3, page_size 10 (remaining 5 items)
    res3 = client.get("/api/predictions/history?page=3&page_size=10")
    assert res3.status_code == 200
    d3 = res3.json()
    assert len(d3["items"]) == 5


# ---------------------------------------------------------------------------
# 14. Database Error Handling (HTTP 503)
# ---------------------------------------------------------------------------
def test_database_error_handling(client: TestClient) -> None:
    with patch.object(
        prediction_service,
        "get_analytics",
        side_effect=PredictionStorageError("Simulated DB failure"),
    ):
        res = client.get("/api/predictions/analytics")
        assert res.status_code == 503
        assert "temporarily unavailable" in res.json()["detail"]

    with patch.object(
        prediction_service,
        "get_history",
        side_effect=PredictionStorageError("Simulated DB failure"),
    ):
        res = client.get("/api/predictions/history")
        assert res.status_code == 503

    with patch.object(
        prediction_service,
        "get_accuracy",
        side_effect=PredictionStorageError("Simulated DB failure"),
    ):
        res = client.get("/api/predictions/accuracy")
        assert res.status_code == 503


# ---------------------------------------------------------------------------
# 15. API Response Validation
# ---------------------------------------------------------------------------
def test_api_response_validation(client: TestClient) -> None:
    _insert_prediction(
        resource="disk",
        metric="disk_utilization",
        predicted_value=45.0,
        actual_value=46.0,
        absolute_error=1.0,
        percentage_error=2.17,
        confidence_score=0.89,
        evaluation_status="evaluated",
    )

    # 1. Analytics endpoint
    res = client.get("/api/predictions/analytics?range=24h")
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "by_resource" in data
    assert "by_horizon" in data
    assert "trend" in data
    assert data["summary"]["evaluated_count"] == 1
    assert data["summary"]["mae"] == 1.0

    # 2. Accuracy endpoint
    res = client.get("/api/predictions/accuracy")
    assert res.status_code == 200
    data = res.json()
    assert "overall" in data
    assert "by_resource" in data
    assert "by_horizon" in data
    assert "grouped" in data

    # 3. History endpoint
    res = client.get("/api/predictions/history")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["resource"] == "disk"
    assert item["metric"] == "disk_utilization"
    assert item["evaluation_status"] == "evaluated"
    assert item["actual_value"] == 46.0
    assert item["absolute_error"] == 1.0

    # 4. Bad request handling
    bad_res = client.get("/api/predictions/analytics?resource=invalid_res")
    assert bad_res.status_code == 400

    bad_hor = client.get("/api/predictions/analytics?horizon=invalid_hor")
    assert bad_hor.status_code == 400

    bad_range = client.get("/api/predictions/analytics?range=invalid_range")
    assert bad_range.status_code == 400

