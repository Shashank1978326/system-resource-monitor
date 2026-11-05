"""Tests for Feature 7B: Historical Battery Monitoring."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database.connection import Database
from app.database.models import HistoricalMetrics
from app.database.repository import HistoryRepository
from app.main import app
from app.schemas.monitoring import (
    BatteryResponse,
    CpuResponse,
    DiskIoResponse,
    DiskPartitionResponse,
    DiskResponse,
    HistoricalGraphResponse,
    MemoryResponse,
    MonitoringSnapshotResponse,
    NetworkResponse,
)
from app.services.history_service import HistoryService


@pytest.fixture
def battery_history_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "battery-history.sqlite3"
    database = Database(database_path)
    database.initialize()
    repository = HistoryRepository(database.session_factory, database.path)
    service = HistoryService(repository, retention_days=30)
    monkeypatch.setattr("app.api.routes.history.history_service", service)
    yield database, repository, service
    database.dispose()


def make_snapshot(timestamp: datetime) -> MonitoringSnapshotResponse:
    return MonitoringSnapshotResponse(
        timestamp=timestamp.isoformat(),
        cpu=CpuResponse(
            cpu_usage_percent=15.0,
            per_core_usage=None,
            physical_cores=4,
            logical_cores=8,
            frequency_mhz=None,
            min_frequency_mhz=None,
            max_frequency_mhz=None,
            usage_status=None,
        ),
        memory=MemoryResponse(
            total_bytes=16000000000,
            used_bytes=8000000000,
            available_bytes=8000000000,
            free_bytes=4000000000,
            usage_percent=50.0,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        ),
        disk=DiskResponse(
            partitions=[
                DiskPartitionResponse(
                    device="C:",
                    mountpoint="C:\\",
                    filesystem="NTFS",
                    total_bytes=500000000000,
                    used_bytes=250000000000,
                    free_bytes=250000000000,
                    usage_percent=50.0,
                )
            ],
            io=DiskIoResponse(
                read_bytes=1000,
                write_bytes=2000,
                read_count=10,
                write_count=20,
                read_speed_bytes_per_sec=1024.0,
                write_speed_bytes_per_sec=2048.0,
                read_speed_status="available",
                write_speed_status="available",
            ),
        ),
        network=NetworkResponse(
            bytes_received=10000,
            bytes_sent=5000,
            packets_received=100,
            packets_sent=50,
            download_speed_bytes_per_sec=512.0,
            upload_speed_bytes_per_sec=256.0,
            download_speed_mbps=None,
            upload_speed_mbps=None,
            interfaces=[],
        ),
        collection_status="healthy",
        metric_errors={},
    )


def make_battery(
    *,
    availability: str = "available",
    percentage: float | None = 85.0,
    charging_state: str = "charging",
    power_plugged: bool | None = True,
) -> BatteryResponse:
    return BatteryResponse(
        availability=availability,
        platform="Windows",
        percentage=percentage,
        charging_state=charging_state,
        power_plugged=power_plugged,
        remaining_seconds=3600 if percentage is not None else None,
        remaining_time="1 hour" if percentage is not None else None,
        message="Battery status reading",
    )


def test_battery_history_persistence(battery_history_store):
    _, repository, service = battery_history_store
    now = datetime.now(timezone.utc)
    snapshot = make_snapshot(now)
    battery = make_battery(percentage=78.5, charging_state="charging", power_plugged=True)

    service.record_snapshot(snapshot, battery_info=battery)

    records = repository.get_records(None, None, limit=10, offset=0)
    assert len(records) == 1
    assert records[0].battery_availability == "available"
    assert records[0].battery_percentage == 78.5
    assert records[0].battery_charging_state == "charging"
    assert records[0].battery_power_plugged is True


def test_battery_history_zero_percent_preserved(battery_history_store):
    _, repository, service = battery_history_store
    now = datetime.now(timezone.utc)
    snapshot = make_snapshot(now)
    battery = make_battery(percentage=0.0, charging_state="discharging", power_plugged=False)

    service.record_snapshot(snapshot, battery_info=battery)

    records = repository.get_records(None, None, limit=10, offset=0)
    assert len(records) == 1
    assert records[0].battery_percentage == 0.0
    assert records[0].battery_percentage is not None
    assert records[0].battery_charging_state == "discharging"
    assert records[0].battery_power_plugged is False


def test_battery_history_charging_states_persistence(battery_history_store):
    _, repository, service = battery_history_store
    now = datetime.now(timezone.utc)

    states = [
        ("charging", 50.0, True),
        ("discharging", 49.0, False),
        ("not_charging", 100.0, True),
        ("unknown", None, None),
    ]

    for index, (state, pct, plugged) in enumerate(states):
        ts = now + timedelta(minutes=index)
        snapshot = make_snapshot(ts)
        battery = make_battery(
            percentage=pct,
            charging_state=state,
            power_plugged=plugged,
        )
        service.record_snapshot(snapshot, battery_info=battery)

    records = repository.get_records(None, None, limit=10, offset=0)
    assert len(records) == 4
    for record, (expected_state, expected_pct, expected_plugged) in zip(records, states):
        assert record.battery_charging_state == expected_state
        assert record.battery_percentage == expected_pct
        assert record.battery_power_plugged is expected_plugged


def test_battery_history_missing_battery_readings(battery_history_store):
    _, repository, service = battery_history_store
    now = datetime.now(timezone.utc)

    # 1. System without battery (unavailable)
    service.record_snapshot(
        make_snapshot(now),
        battery_info=make_battery(
            availability="unavailable",
            percentage=None,
            charging_state="unknown",
            power_plugged=None,
        ),
    )

    # 2. Unsupported platform
    service.record_snapshot(
        make_snapshot(now + timedelta(minutes=1)),
        battery_info=make_battery(
            availability="unsupported",
            percentage=None,
            charging_state="unknown",
            power_plugged=None,
        ),
    )

    # 3. None battery_info passed
    service.record_snapshot(
        make_snapshot(now + timedelta(minutes=2)),
        battery_info=None,
    )

    records = repository.get_records(None, None, limit=10, offset=0)
    assert len(records) == 3

    assert records[0].battery_availability == "unavailable"
    assert records[0].battery_percentage is None
    assert records[0].battery_charging_state is None
    assert records[0].battery_power_plugged is None

    assert records[1].battery_availability == "unsupported"
    assert records[1].battery_percentage is None
    assert records[1].battery_charging_state is None
    assert records[1].battery_power_plugged is None

    assert records[2].battery_availability is None
    assert records[2].battery_percentage is None
    assert records[2].battery_charging_state is None
    assert records[2].battery_power_plugged is None


def test_battery_historical_api_responses(battery_history_store):
    _, repository, _ = battery_history_store
    base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=5)

    # Insert two samples in one 1-minute bucket
    repository.insert(
        HistoricalMetrics(
            timestamp=base + timedelta(seconds=10),
            battery_availability="available",
            battery_percentage=20.0,
            battery_charging_state="charging",
            battery_power_plugged=True,
        )
    )
    repository.insert(
        HistoricalMetrics(
            timestamp=base + timedelta(seconds=50),
            battery_availability="available",
            battery_percentage=30.0,
            battery_charging_state="charging",
            battery_power_plugged=True,
        )
    )
    # Insert one sample in next bucket with NULL percentage
    repository.insert(
        HistoricalMetrics(
            timestamp=base + timedelta(minutes=1, seconds=10),
            battery_availability="unavailable",
            battery_percentage=None,
            battery_charging_state=None,
            battery_power_plugged=None,
        )
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "1h", "interval": "1m"},
        )

    assert response.status_code == 200
    body = response.json()

    # Validate response schema
    graph_model = HistoricalGraphResponse.model_validate(body)
    assert graph_model.metric == "battery"
    assert graph_model.unit == "percent"
    assert len(graph_model.data_points) == 2

    first_point = body["data_points"][0]
    assert first_point["value"] == 25.0  # Average of 20 and 30
    assert first_point["battery_availability"] == "available"
    assert first_point["charging_state"] == "charging"
    assert first_point["power_plugged"] is True
    assert first_point["status_timestamp"] is not None

    second_point = body["data_points"][1]
    assert second_point["value"] is None
    assert second_point["battery_availability"] == "unavailable"
    assert second_point["charging_state"] is None
    assert second_point["power_plugged"] is None


def test_battery_historical_api_invalid_query_params(battery_history_store):
    with TestClient(app) as client:
        # Rejects interface parameter for battery metric
        r1 = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "1h", "interval": "1m", "interface": "eth0"},
        )
        assert r1.status_code == 422
        assert "interface and sensor_id are not valid for battery metrics" in r1.json()["detail"]

        # Rejects sensor_id parameter for battery metric
        r2 = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "1h", "interval": "1m", "sensor_id": "core-0"},
        )
        assert r2.status_code == 422
        assert "interface and sensor_id are not valid for battery metrics" in r2.json()["detail"]


def test_battery_history_time_range_filtering(battery_history_store):
    _, repository, _ = battery_history_store
    now = datetime.now(timezone.utc)

    # Insert a sample from 2 days ago and another from 10 days ago
    repository.insert(
        HistoricalMetrics(
            timestamp=now - timedelta(days=2),
            battery_availability="available",
            battery_percentage=75.0,
            battery_charging_state="discharging",
            battery_power_plugged=False,
        )
    )
    repository.insert(
        HistoricalMetrics(
            timestamp=now - timedelta(days=10),
            battery_availability="available",
            battery_percentage=80.0,
            battery_charging_state="charging",
            battery_power_plugged=True,
        )
    )

    with TestClient(app) as client:
        # 1-day range should exclude both
        r_1d = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "24h", "interval": "1h"},
        )
        assert r_1d.status_code == 200
        assert len(r_1d.json()["data_points"]) == 0

        # 7-day range should include the 2-day-old point, but exclude the 10-day-old point
        r_7d = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "7d", "interval": "1h"},
        )
        assert r_7d.status_code == 200
        points = r_7d.json()["data_points"]
        assert len(points) == 1
        assert points[0]["value"] == 75.0


def test_battery_history_sqlite_migration(tmp_path: Path):
    path = tmp_path / "legacy.sqlite3"
    legacy_database = Database(path)
    with legacy_database.engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE historical_metrics (
                id INTEGER NOT NULL PRIMARY KEY,
                timestamp DATETIME NOT NULL UNIQUE,
                cpu_utilization_percent FLOAT,
                ram_utilization_percent FLOAT,
                ram_used_bytes BIGINT,
                ram_available_bytes BIGINT,
                disk_read_bytes BIGINT,
                disk_write_bytes BIGINT,
                disk_utilization_percent FLOAT,
                network_download_speed FLOAT,
                network_upload_speed FLOAT,
                network_bytes_received BIGINT,
                network_bytes_sent BIGINT
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO historical_metrics (id, timestamp, cpu_utilization_percent, disk_read_bytes)
            VALUES (1, '2026-11-01 10:00:00.000000', 45.0, 1024)
            """
        )

    # Run initialize() which executes the additive migrations
    legacy_database.initialize()
    legacy_database.initialize()

    inspector = inspect(legacy_database.engine)
    columns = {col["name"] for col in inspector.get_columns("historical_metrics")}

    assert "battery_availability" in columns
    assert "battery_percentage" in columns
    assert "battery_charging_state" in columns
    assert "battery_power_plugged" in columns

    # Verify existing data is preserved with NULL battery columns
    records = HistoryRepository(legacy_database.session_factory, path).get_records(
        None, None, limit=10, offset=0
    )
    assert len(records) == 1
    assert records[0].id == 1
    assert records[0].cpu_utilization_percent == 45.0
    assert records[0].disk_read_bytes == 1024
    assert records[0].battery_availability is None
    assert records[0].battery_percentage is None
    assert records[0].battery_charging_state is None
    assert records[0].battery_power_plugged is None

    # Verify new writes with battery data succeed
    service = HistoryService(HistoryRepository(legacy_database.session_factory, path), retention_days=30)
    service.record_snapshot(
        make_snapshot(datetime.now(timezone.utc)),
        battery_info=make_battery(percentage=90.0, charging_state="charging", power_plugged=True),
    )
    updated_records = HistoryRepository(legacy_database.session_factory, path).get_records(
        None, None, limit=10, offset=0
    )
    assert len(updated_records) == 2
    assert updated_records[1].battery_percentage == 90.0
    assert updated_records[1].battery_charging_state == "charging"
    assert updated_records[1].battery_power_plugged is True

    legacy_database.dispose()


def test_existing_historical_graph_compatibility(battery_history_store):
    _, repository, _ = battery_history_store
    now = datetime.now(timezone.utc)

    repository.insert(
        HistoricalMetrics(
            timestamp=now - timedelta(minutes=2),
            cpu_utilization_percent=55.5,
            ram_utilization_percent=66.6,
            disk_utilization_percent=77.7,
            network_download_speed=1024.0,
            network_upload_speed=512.0,
            disk_read_speed=2048.0,
            disk_write_speed=4096.0,
        )
    )

    with TestClient(app) as client:
        for metric, expected_unit in [
            ("cpu", "percent"),
            ("memory", "percent"),
            ("disk", "percent"),
            ("network_download", "bytes_per_second"),
            ("network_upload", "bytes_per_second"),
            ("disk_read_speed", "bytes_per_second"),
            ("disk_write_speed", "bytes_per_second"),
        ]:
            response = client.get(
                "/api/history/graph",
                params={"metric": metric, "range": "1h", "interval": "1m"},
            )
            assert response.status_code == 200, f"Failed for {metric}"
            body = response.json()
            assert body["metric"] == metric
            assert body["unit"] == expected_unit
            assert len(body["data_points"]) >= 1
            point = body["data_points"][0]
            assert "value" in point
            assert "timestamp" in point
            # Standard metrics should not have battery-specific fields
            assert "battery_availability" not in point
