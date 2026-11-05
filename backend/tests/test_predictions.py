"""Comprehensive unit and integration tests for Feature 9A: Resource Prediction Engine."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database.connection import database, initialize_database
from app.database.models import HistoricalMetrics
from app.main import app
from app.schemas.predictions import PredictionResponse, ResourcePrediction
from app.services.prediction_service import (
    SUPPORTED_HORIZONS,
    PredictionService,
    PredictionStorageError,
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
        session.query(HistoricalMetrics).delete()
    yield
    with database.session_factory.begin() as session:
        session.query(HistoricalMetrics).delete()
    database.dispose()


def _insert_sample(
    timestamp: datetime,
    cpu: float | None = None,
    memory: float | None = None,
    disk: float | None = None,
    net_down: float | None = None,
    net_up: float | None = None,
) -> None:
    """Helper to insert controlled historical metrics record."""
    with database.session_factory.begin() as session:
        record = HistoricalMetrics(
            timestamp=timestamp,
            cpu_utilization_percent=cpu,
            ram_utilization_percent=memory,
            disk_utilization_percent=disk,
            network_download_speed=net_down,
            network_upload_speed=net_up,
        )
        session.add(record)


# ---------------------------------------------------------------------------
# 1. CPU Prediction
# ---------------------------------------------------------------------------
def test_cpu_prediction(client: TestClient) -> None:
    """Predict future CPU utilization percentage using controlled historical records."""
    now = datetime.now(timezone.utc)
    # Controlled upward trend: 20%, 22%, 24%, 26%, 28%, 30% over 10 minutes
    for i, val in enumerate([20.0, 22.0, 24.0, 26.0, 28.0, 30.0]):
        _insert_sample(
            timestamp=now - timedelta(minutes=10 - (i * 2)),
            cpu=val,
        )

    res = client.get("/api/predictions?resource=cpu&horizon=15m")
    assert res.status_code == 200
    data = res.json()

    assert data["horizon"] == "15m"
    assert data["horizon_seconds"] == 900
    assert len(data["predictions"]) == 1

    cpu_pred = data["predictions"][0]
    assert cpu_pred["resource"] == "cpu"
    assert cpu_pred["metric"] == "cpu_utilization"
    assert cpu_pred["unit"] == "percent"
    assert cpu_pred["status"] == "available"
    assert cpu_pred["current_value"] == 30.0
    # With upward trend, predicted value should exceed current value
    assert cpu_pred["predicted_value"] > 30.0
    assert cpu_pred["trend"] == "increasing"
    assert cpu_pred["confidence_score"] is not None
    assert 0.0 < cpu_pred["confidence_score"] <= 1.0
    assert cpu_pred["lower_bound"] <= cpu_pred["predicted_value"] <= cpu_pred["upper_bound"]


# ---------------------------------------------------------------------------
# 2. Memory Prediction
# ---------------------------------------------------------------------------
def test_memory_prediction(client: TestClient) -> None:
    """Predict future memory utilization percentage with controlled downward trend."""
    now = datetime.now(timezone.utc)
    # Controlled downward trend: 65%, 63%, 61%, 59%, 57%, 55%
    for i, val in enumerate([65.0, 63.0, 61.0, 59.0, 57.0, 55.0]):
        _insert_sample(
            timestamp=now - timedelta(minutes=10 - (i * 2)),
            memory=val,
        )

    res = client.get("/api/predictions?resource=memory&horizon=10m")
    assert res.status_code == 200
    data = res.json()

    mem_pred = data["predictions"][0]
    assert mem_pred["resource"] == "memory"
    assert mem_pred["metric"] == "memory_utilization"
    assert mem_pred["status"] == "available"
    assert mem_pred["current_value"] == 55.0
    assert mem_pred["predicted_value"] < 55.0
    assert mem_pred["trend"] == "decreasing"


# ---------------------------------------------------------------------------
# 3. Disk Utilization Prediction (Capacity Utilization)
# ---------------------------------------------------------------------------
def test_disk_utilization_prediction(client: TestClient) -> None:
    """Predict future disk capacity utilization percentage distinguishing from I/O throughput."""
    now = datetime.now(timezone.utc)
    # Steady state: 48.5% capacity across all samples
    for i in range(6):
        _insert_sample(
            timestamp=now - timedelta(minutes=12 - (i * 2)),
            disk=48.5,
        )

    res = client.get("/api/predictions?resource=disk&horizon=5m")
    assert res.status_code == 200
    data = res.json()

    disk_pred = data["predictions"][0]
    assert disk_pred["resource"] == "disk"
    assert disk_pred["metric"] == "disk_utilization"
    assert disk_pred["unit"] == "percent"
    assert disk_pred["status"] == "available"
    assert disk_pred["current_value"] == 48.5
    assert disk_pred["predicted_value"] == 48.5
    assert disk_pred["trend"] == "stable"


# ---------------------------------------------------------------------------
# 4. Network Download Prediction
# ---------------------------------------------------------------------------
def test_network_download_prediction(client: TestClient) -> None:
    """Predict future network download throughput in bytes per second."""
    now = datetime.now(timezone.utc)
    # Increasing download rate: 1 MB/s, 2 MB/s, 3 MB/s, 4 MB/s, 5 MB/s, 6 MB/s
    for i, val in enumerate([1e6, 2e6, 3e6, 4e6, 5e6, 6e6]):
        _insert_sample(
            timestamp=now - timedelta(minutes=10 - (i * 2)),
            net_down=val,
        )

    res = client.get("/api/predictions?resource=network_download&horizon=5m")
    assert res.status_code == 200
    data = res.json()

    net_pred = data["predictions"][0]
    assert net_pred["resource"] == "network"
    assert net_pred["metric"] == "network_download"
    assert net_pred["unit"] == "bytes_per_second"
    assert net_pred["status"] == "available"
    assert net_pred["current_value"] == 6_000_000.0
    assert net_pred["predicted_value"] > 6_000_000.0
    assert net_pred["trend"] == "increasing"


# ---------------------------------------------------------------------------
# 5. Network Upload Prediction
# ---------------------------------------------------------------------------
def test_network_upload_prediction(client: TestClient) -> None:
    """Predict future network upload throughput in bytes per second."""
    now = datetime.now(timezone.utc)
    for i in range(6):
        _insert_sample(
            timestamp=now - timedelta(minutes=10 - (i * 2)),
            net_up=250_000.0,
        )

    res = client.get("/api/predictions?resource=network_upload&horizon=15m")
    assert res.status_code == 200
    data = res.json()

    net_pred = data["predictions"][0]
    assert net_pred["resource"] == "network"
    assert net_pred["metric"] == "network_upload"
    assert net_pred["unit"] == "bytes_per_second"
    assert net_pred["status"] == "available"
    assert net_pred["predicted_value"] == 250_000.0


# ---------------------------------------------------------------------------
# 6. Insufficient Historical Data
# ---------------------------------------------------------------------------
def test_insufficient_historical_data(client: TestClient) -> None:
    """Handle insufficient historical records gracefully with clear status and no fabrication."""
    now = datetime.now(timezone.utc)
    # Only 2 samples (minimum required is 5)
    _insert_sample(now - timedelta(minutes=2), cpu=25.0)
    _insert_sample(now, cpu=30.0)

    res = client.get("/api/predictions?resource=cpu")
    assert res.status_code == 200
    data = res.json()

    pred = data["predictions"][0]
    assert pred["status"] == "insufficient_data"
    assert pred["predicted_value"] is None
    assert pred["confidence_score"] is None
    assert pred["sample_count"] == 2
    assert "Insufficient historical data" in pred["message"]


# ---------------------------------------------------------------------------
# 7. Missing Values (NULL Handling)
# ---------------------------------------------------------------------------
def test_missing_values_handled_safely(client: TestClient) -> None:
    """Ignore records with NULL values and compute forecast from valid samples."""
    now = datetime.now(timezone.utc)
    # Insert 10 records, but CPU is None in 4 of them (6 valid samples)
    for i in range(10):
        cpu_val = 20.0 + i if i % 2 == 0 else None
        _insert_sample(
            timestamp=now - timedelta(minutes=10 - i),
            cpu=cpu_val,
        )

    res = client.get("/api/predictions?resource=cpu")
    assert res.status_code == 200
    data = res.json()

    pred = data["predictions"][0]
    assert pred["status"] == "available"
    assert pred["sample_count"] == 5
    assert pred["predicted_value"] is not None


# ---------------------------------------------------------------------------
# 8. Invalid Prediction Horizons
# ---------------------------------------------------------------------------
def test_invalid_prediction_horizons(client: TestClient) -> None:
    """Reject invalid prediction horizons with 400 Bad Request."""
    res1 = client.get("/api/predictions?horizon=2h")
    assert res1.status_code == 400
    assert "Invalid prediction horizon" in res1.json()["detail"]

    res2 = client.get("/api/predictions?horizon=invalid")
    assert res2.status_code == 400
    assert "Supported horizons: 5m, 10m, 15m, 30m" in res2.json()["detail"]


# ---------------------------------------------------------------------------
# 9. Negative Prediction Prevention
# ---------------------------------------------------------------------------
def test_negative_prediction_prevention(client: TestClient) -> None:
    """Ensure throughput predictions are clamped to >= 0.0 even under steep downward trend."""
    now = datetime.now(timezone.utc)
    # Steep drop from 100 KB/s down to 5 KB/s
    for i, val in enumerate([100_000.0, 70_000.0, 40_000.0, 20_000.0, 5_000.0]):
        _insert_sample(
            timestamp=now - timedelta(minutes=5 - i),
            net_down=val,
        )

    # 30m horizon extrapolation would linearly go deeply negative
    res = client.get("/api/predictions?resource=network_download&horizon=30m")
    assert res.status_code == 200
    data = res.json()

    pred = data["predictions"][0]
    assert pred["predicted_value"] >= 0.0
    assert pred["lower_bound"] >= 0.0


# ---------------------------------------------------------------------------
# 10. CPU, Memory, and Disk Prediction Boundaries (0–100%)
# ---------------------------------------------------------------------------
def test_prediction_boundary_enforcement(client: TestClient) -> None:
    """Enforce strict 0-100% boundary limits for CPU, memory, and disk utilization."""
    now = datetime.now(timezone.utc)
    # Steep CPU surge: 70%, 80%, 90%, 95%, 98%
    for i, val in enumerate([70.0, 80.0, 90.0, 95.0, 98.0]):
        _insert_sample(
            timestamp=now - timedelta(minutes=5 - i),
            cpu=val,
        )

    res_upper = client.get("/api/predictions?resource=cpu&horizon=30m")
    assert res_upper.status_code == 200
    cpu_pred = res_upper.json()["predictions"][0]
    assert cpu_pred["predicted_value"] <= 100.0
    assert cpu_pred["upper_bound"] <= 100.0

    # Clear for memory test
    with database.session_factory.begin() as session:
        session.query(HistoricalMetrics).delete()

    # Steep Memory drop towards 0: 25%, 18%, 10%, 5%, 1%
    for i, val in enumerate([25.0, 18.0, 10.0, 5.0, 1.0]):
        _insert_sample(
            timestamp=now - timedelta(minutes=5 - i),
            memory=val,
        )

    res_lower = client.get("/api/predictions?resource=memory&horizon=30m")
    assert res_lower.status_code == 200
    mem_pred = res_lower.json()["predictions"][0]
    assert mem_pred["predicted_value"] >= 0.0
    assert mem_pred["lower_bound"] >= 0.0


# ---------------------------------------------------------------------------
# 11. API Response Validation & Resource Filtering
# ---------------------------------------------------------------------------
def test_api_response_validation_and_filters(client: TestClient) -> None:
    """Validate full multi-resource predictions and individual resource filters."""
    now = datetime.now(timezone.utc)
    for i in range(6):
        _insert_sample(
            timestamp=now - timedelta(minutes=6 - i),
            cpu=25.0 + i,
            memory=40.0 + i,
            disk=50.0,
            net_down=1e6 + (i * 1e5),
            net_up=2e5,
        )

    # 1. No filter -> Returns all 5 predictions
    res_all = client.get("/api/predictions?horizon=15m")
    assert res_all.status_code == 200
    data_all = res_all.json()
    assert len(data_all["predictions"]) == 5
    metrics = [p["metric"] for p in data_all["predictions"]]
    assert metrics == [
        "cpu_utilization",
        "memory_utilization",
        "disk_utilization",
        "network_download",
        "network_upload",
    ]

    # 2. Resource filter: network -> Returns 2 predictions
    res_net = client.get("/api/predictions?resource=network")
    assert res_net.status_code == 200
    data_net = res_net.json()
    assert len(data_net["predictions"]) == 2
    assert {p["metric"] for p in data_net["predictions"]} == {
        "network_download",
        "network_upload",
    }

    # 3. Invalid resource filter -> 400 Bad Request
    res_invalid = client.get("/api/predictions?resource=unknown_resource")
    assert res_invalid.status_code == 400
    assert "Unsupported resource" in res_invalid.json()["detail"]


# ---------------------------------------------------------------------------
# 12. Database Error Handling
# ---------------------------------------------------------------------------
def test_database_error_handling(client: TestClient) -> None:
    """Gracefully handle database failure and return 503 Service Unavailable."""
    with patch.object(
        prediction_service,
        "_get_records",
        side_effect=PredictionStorageError("Database failure simulated"),
    ):
        res = client.get("/api/predictions")
        assert res.status_code == 503
        assert "Prediction historical storage is temporarily unavailable" in res.json()["detail"]
