"""Persistence and graph tests for historical temperature sensor readings."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.database.connection import Database
from app.database.models import HistoricalMetrics, HistoricalTemperatureMetrics
from app.database.repository import HistoryRepository
from app.main import app
from app.schemas.monitoring import (
    TemperatureResponse,
    TemperatureSensorReadingResponse,
)
from app.services.history_service import HistoryService


@pytest.fixture
def temperature_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = Database(tmp_path / "temperature-history.sqlite3")
    database.initialize()
    repository = HistoryRepository(database.session_factory, database.path)
    service = HistoryService(repository, retention_days=30)
    monkeypatch.setattr("app.api.routes.history.history_service", service)
    yield database, repository, service
    database.dispose()


def _temperature_response(*readings: dict) -> TemperatureResponse:
    return TemperatureResponse(
        availability="available" if readings else "unavailable",
        platform="TestOS",
        sensors=[
            TemperatureSensorReadingResponse(**reading) for reading in readings
        ],
        message=None if readings else "No sensor readings",
    )


def _sample(
    sensor_id: str,
    sensor_name: str,
    label: str | None,
    reading_index: int,
    current: float | None,
) -> dict:
    return {
        "sensor_id": sensor_id,
        "sensor_name": sensor_name,
        "label": label,
        "reading_index": reading_index,
        "current_celsius": current,
        "high_celsius": None,
        "critical_celsius": None,
        "device": None,
    }


def _base_record(timestamp: datetime) -> HistoricalMetrics:
    return HistoricalMetrics(
        timestamp=timestamp,
        cpu_utilization_percent=None,
        ram_utilization_percent=None,
        disk_utilization_percent=None,
    )


def test_snapshot_persists_multiple_valid_sensors_zero_and_skips_missing(
    temperature_history,
):
    database, _, service = temperature_history
    first_time = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
    second_time = first_time + timedelta(seconds=1)
    with patch(
        "app.services.history_service.get_temperature_info",
        side_effect=[
            _temperature_response(
                _sample("coretemp:0", "coretemp", "Package id 0", 0, 0.0),
                _sample("coretemp:1", "coretemp", "Core 0", 1, 47.5),
                _sample("nvme:0", "nvme", None, 0, None),
            ),
            _temperature_response(
                _sample("coretemp:0", "coretemp", "Package id 0", 0, 50.25),
            ),
        ],
    ):
        service.record_snapshot(_minimal_snapshot(first_time))
        service.record_snapshot(_minimal_snapshot(second_time))

    with database.session_factory() as session:
        rows = list(
            session.query(HistoricalTemperatureMetrics)
            .order_by(HistoricalTemperatureMetrics.timestamp, HistoricalTemperatureMetrics.sensor_id)
            .all()
        )
    assert [(row.timestamp, row.sensor_id) for row in rows] == [
        (first_time, "coretemp:0"),
        (first_time, "coretemp:1"),
        (second_time, "coretemp:0"),
    ]
    assert [row.temperature_celsius for row in rows] == [0.0, 47.5, 50.25]


def test_history_service_persists_actual_temperature_samples(temperature_history):
    database, _, service = temperature_history
    timestamp = datetime(2026, 11, 3, 0, 1, tzinfo=timezone.utc)
    snapshot = _minimal_snapshot(timestamp)
    with patch(
        "app.services.history_service.get_temperature_info",
        return_value=_temperature_response(
            _sample("coretemp:0", "coretemp", "Package", 0, 0.0),
            _sample("coretemp:1", "coretemp", "Core 0", 1, 51.25),
            _sample("nvme:0", "nvme", None, 0, None),
        ),
    ):
        service.record_snapshot(snapshot)

    with database.session_factory() as session:
        rows = list(
            session.query(HistoricalTemperatureMetrics)
            .order_by(HistoricalTemperatureMetrics.sensor_id)
            .all()
        )
    assert [(row.sensor_id, row.sensor_name, row.sensor_label) for row in rows] == [
        ("coretemp:0", "coretemp", "Package"),
        ("coretemp:1", "coretemp", "Core 0"),
    ]
    assert [row.temperature_celsius for row in rows] == [0.0, 51.25]
    assert all(row.timestamp == timestamp for row in rows)


def test_cached_temperature_sample_avoids_a_second_sensor_probe(temperature_history):
    database, _, service = temperature_history
    timestamp = datetime(2026, 11, 3, 0, 2, tzinfo=timezone.utc)
    sample = _temperature_response(
        _sample("cpu:0", "coretemp", "Package", 0, 68.5)
    )
    with patch(
        "app.services.history_service.get_temperature_info",
        side_effect=AssertionError("collector sample should be reused"),
    ):
        service.record_snapshot(
            _minimal_snapshot(timestamp),
            sample,
            temperature_sampled=True,
        )

    with database.session_factory() as session:
        rows = session.query(HistoricalTemperatureMetrics).all()
    assert len(rows) == 1
    assert rows[0].temperature_celsius == 68.5


def _minimal_snapshot(timestamp: datetime):
    from app.schemas.monitoring import (
        CpuResponse,
        DiskIoResponse,
        DiskResponse,
        MemoryResponse,
        MonitoringSnapshotResponse,
        NetworkResponse,
    )

    return MonitoringSnapshotResponse(
        timestamp=timestamp.isoformat(),
        cpu=CpuResponse(
            cpu_usage_percent=None,
            per_core_usage=None,
            physical_cores=None,
            logical_cores=None,
            frequency_mhz=None,
            min_frequency_mhz=None,
            max_frequency_mhz=None,
            usage_status=None,
        ),
        memory=MemoryResponse(
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            free_bytes=None,
            usage_percent=None,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        ),
        disk=DiskResponse(
            partitions=[],
            io=DiskIoResponse(
                read_bytes=None,
                write_bytes=None,
                read_count=None,
                write_count=None,
            ),
        ),
        network=NetworkResponse(
            bytes_received=None,
            bytes_sent=None,
            packets_received=None,
            packets_sent=None,
            download_speed_bytes_per_sec=None,
            upload_speed_bytes_per_sec=None,
            download_speed_mbps=None,
            upload_speed_mbps=None,
            interfaces=[],
        ),
        collection_status="healthy",
        metric_errors={},
    )


def test_temperature_sensor_list_and_graph_average_selected_sensor(
    temperature_history,
):
    database, repository, _ = temperature_history
    bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
        minutes=2
    )
    repository.insert_snapshot(
        _base_record(bucket + timedelta(seconds=5)),
        [],
        [
            HistoricalTemperatureMetrics(
                timestamp=bucket + timedelta(seconds=5),
                sensor_id="cpu:0",
                sensor_name="coretemp",
                sensor_label="Package",
                reading_index=0,
                temperature_celsius=0,
            ),
            HistoricalTemperatureMetrics(
                timestamp=bucket + timedelta(seconds=5),
                sensor_id="cpu:1",
                sensor_name="coretemp",
                sensor_label="Core 0",
                reading_index=1,
                temperature_celsius=90,
            ),
        ],
    )
    repository.insert_snapshot(
        _base_record(bucket + timedelta(seconds=30)),
        [],
        [
            HistoricalTemperatureMetrics(
                timestamp=bucket + timedelta(seconds=30),
                sensor_id="cpu:0",
                sensor_name="coretemp",
                sensor_label="Package",
                reading_index=0,
                temperature_celsius=40,
            )
        ],
    )
    with TestClient(app) as client:
        sensors = client.get("/api/history/temperature-sensors")
        graph = client.get(
            "/api/history/graph",
            params={
                "metric": "temperature",
                "sensor_id": "cpu:0",
                "range": "1h",
                "interval": "1m",
            },
        )

    assert sensors.status_code == 200
    assert sensors.json()["sensors"] == [
        {
            "sensor_id": "cpu:0",
            "sensor_name": "coretemp",
            "label": "Package",
        },
        {
            "sensor_id": "cpu:1",
            "sensor_name": "coretemp",
            "label": "Core 0",
        },
    ]
    assert graph.status_code == 200
    body = graph.json()
    assert body["unit"] == "celsius"
    assert body["data_points"][0]["value"] == 20.0
    assert body["data_points"][0]["timestamp"] == bucket.isoformat().replace(
        "+00:00", "Z"
    )
    database.dispose()


def test_temperature_graph_validates_sensor_and_time_range(temperature_history):
    _, repository, _ = temperature_history
    now = datetime.now(timezone.utc)
    repository.insert_snapshot(
        _base_record(now - timedelta(days=1)),
        [],
        [
            HistoricalTemperatureMetrics(
                timestamp=now - timedelta(days=1),
                sensor_id="cpu:0",
                sensor_name="coretemp",
                sensor_label="Package",
                reading_index=0,
                temperature_celsius=55,
            )
        ],
    )
    with TestClient(app) as client:
        missing_sensor = client.get(
            "/api/history/graph",
            params={"metric": "temperature", "range": "1h", "interval": "1m"},
        )
        unknown_sensor = client.get(
            "/api/history/graph",
            params={
                "metric": "temperature",
                "sensor_id": "unknown",
                "range": "1h",
                "interval": "1m",
            },
        )
        outside_range = client.get(
            "/api/history/graph",
            params={
                "metric": "temperature",
                "sensor_id": "cpu:0",
                "range": "5m",
                "interval": "1m",
            },
        )
        unexpected_interface = client.get(
            "/api/history/graph",
            params={
                "metric": "temperature",
                "sensor_id": "cpu:0",
                "interface": "Wi-Fi",
                "range": "1h",
                "interval": "1m",
            },
        )

    assert missing_sensor.status_code == 422
    assert unknown_sensor.status_code == 404
    assert outside_range.status_code == 200
    assert outside_range.json()["data_points"] == []
    assert unexpected_interface.status_code == 422


def test_temperature_retention_uses_existing_history_policy(temperature_history):
    database, _, service = temperature_history
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    with patch(
        "app.services.history_service.get_temperature_info",
        return_value=_temperature_response(
            _sample("cpu:0", "coretemp", "Package", 0, 42.0)
        ),
    ):
        service.record_snapshot(_minimal_snapshot(now - timedelta(days=31)))
        service.record_snapshot(_minimal_snapshot(now - timedelta(days=29)))

    assert service.cleanup_expired(now) == 1
    with database.session_factory() as session:
        rows = list(session.query(HistoricalTemperatureMetrics).all())
    assert len(rows) == 1
    assert rows[0].timestamp == now - timedelta(days=29)


def test_existing_graph_metric_remains_compatible(temperature_history):
    _, repository, _ = temperature_history
    now = datetime.now(timezone.utc)
    repository.insert_snapshot(
        HistoricalMetrics(
            timestamp=now,
            cpu_utilization_percent=37.5,
        ),
        [],
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "cpu", "range": "1h", "interval": "1m"},
        )
    assert response.status_code == 200
    assert response.json()["unit"] == "percent"
    assert response.json()["data_points"][-1]["value"] == 37.5
