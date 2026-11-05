"""Tests for SQLite history, APIs, retention, and collector persistence."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import _history_retention_days_from_environment
from app.database.connection import Database
from app.database.models import HistoricalNetworkInterfaceMetrics
from app.database.repository import HistoryRepository
from app.main import app
from app.schemas.monitoring import (
    BatteryResponse,
    CpuResponse,
    DiskIoResponse,
    DiskPartitionResponse,
    DiskResponse,
    MemoryResponse,
    MonitoringSnapshotResponse,
    NetworkResponse,
)
from app.services.history_service import HistoryService, HistoryStorageError
from app.services.monitoring_service import MonitoringService


@pytest.fixture
def history_store(tmp_path: Path):
    database = Database(tmp_path / "history.sqlite3")
    database.initialize()
    repository = HistoryRepository(database.session_factory, database.path)
    service = HistoryService(repository, retention_days=30)
    yield database, repository, service
    database.dispose()


def make_snapshot(
    timestamp: datetime,
    *,
    cpu: float | None = 10.0,
    ram: float | None = 20.0,
    ram_used: int | None = 200,
    ram_available: int | None = 800,
    download: float | None = 100.0,
    upload: float | None = 50.0,
    disk_read_speed: float | None = None,
    disk_write_speed: float | None = None,
    interfaces: list | None = None,
) -> MonitoringSnapshotResponse:
    return MonitoringSnapshotResponse(
        timestamp=timestamp.isoformat(),
        cpu=CpuResponse(
            cpu_usage_percent=cpu,
            per_core_usage=None,
            physical_cores=2,
            logical_cores=4,
            frequency_mhz=None,
            min_frequency_mhz=None,
            max_frequency_mhz=None,
            usage_status=None,
        ),
        memory=MemoryResponse(
            total_bytes=1000,
            used_bytes=ram_used,
            available_bytes=ram_available,
            free_bytes=500,
            usage_percent=ram,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        ),
        disk=DiskResponse(
            partitions=[
                DiskPartitionResponse(
                    device="disk-a",
                    mountpoint="mount-a",
                    filesystem="test",
                    total_bytes=100,
                    used_bytes=90,
                    free_bytes=10,
                    usage_percent=90,
                ),
                DiskPartitionResponse(
                    device="disk-b",
                    mountpoint="mount-b",
                    filesystem="test",
                    total_bytes=300,
                    used_bytes=30,
                    free_bytes=270,
                    usage_percent=10,
                ),
            ],
            io=DiskIoResponse(
                read_bytes=1000,
                write_bytes=2000,
                read_count=10,
                write_count=20,
                read_speed_bytes_per_sec=disk_read_speed,
                write_speed_bytes_per_sec=disk_write_speed,
                read_speed_status=(
                    "available" if disk_read_speed is not None else "unavailable"
                ),
                write_speed_status=(
                    "available" if disk_write_speed is not None else "unavailable"
                ),
            ),
        ),
        network=NetworkResponse(
            bytes_received=3000,
            bytes_sent=4000,
            packets_received=30,
            packets_sent=40,
            download_speed_bytes_per_sec=download,
            upload_speed_bytes_per_sec=upload,
            download_speed_mbps=None,
            upload_speed_mbps=None,
            interfaces=interfaces or [],
        ),
        collection_status="healthy",
        metric_errors={},
    )


def make_battery(
    *,
    availability: str = "available",
    percentage: float | None = 75.0,
    charging_state: str = "discharging",
    power_plugged: bool | None = False,
) -> BatteryResponse:
    return BatteryResponse(
        availability=availability,
        platform="TestOS",
        percentage=percentage,
        charging_state=charging_state,
        power_plugged=power_plugged,
        remaining_seconds=None,
        remaining_time=None,
        message="Test battery reading",
    )


def test_database_initialization_creates_table_and_timestamp_index(
    history_store,
) -> None:
    database, _, _ = history_store

    assert database.path.is_absolute()
    inspector = inspect(database.engine)
    assert "historical_metrics" in inspector.get_table_names()
    indexes = inspector.get_indexes("historical_metrics")
    assert any(index["column_names"] == ["timestamp"] for index in indexes)


def test_metric_insertion_persists_across_database_reconnection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reconnect.sqlite3"
    first_database = Database(path)
    first_database.initialize()
    first_service = HistoryService(
        HistoryRepository(first_database.session_factory, path), retention_days=30
    )
    timestamp = datetime(2026, 11, 1, 21, 14, tzinfo=timezone.utc)
    first_service.record_snapshot(make_snapshot(timestamp))
    first_database.dispose()

    reopened_database = Database(path)
    reopened_database.initialize()
    reopened_repository = HistoryRepository(
        reopened_database.session_factory, reopened_database.path
    )
    records = reopened_repository.get_records(None, None, limit=10, offset=0)

    assert len(records) == 1
    assert records[0].timestamp == timestamp
    assert records[0].timestamp.tzinfo == timezone.utc
    assert records[0].cpu_utilization_percent == 10.0
    reopened_database.dispose()


def test_timestamps_are_normalized_to_utc(history_store) -> None:
    _, repository, service = history_store
    local_timestamp = datetime.fromisoformat("2026-11-02T08:00:00+05:30")

    service.record_snapshot(make_snapshot(local_timestamp))
    record = repository.get_records(None, None, limit=1, offset=0)[0]

    assert record.timestamp == datetime(2026, 11, 2, 2, 30, tzinfo=timezone.utc)


def test_disk_utilization_uses_capacity_weighted_partition_aggregate(
    history_store,
) -> None:
    _, repository, service = history_store

    service.record_snapshot(make_snapshot(datetime.now(timezone.utc)))
    record = repository.get_records(None, None, limit=1, offset=0)[0]

    assert record.disk_utilization_percent == 30.0


def test_disk_throughput_persists_actual_values_nulls_and_genuine_zero(history_store):
    _, repository, service = history_store
    start = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    service.record_snapshot(
        make_snapshot(
            start,
            disk_read_speed=1024.5,
            disk_write_speed=2048.25,
        )
    )
    service.record_snapshot(
        make_snapshot(
            start + timedelta(seconds=1),
            disk_read_speed=0,
            disk_write_speed=None,
        )
    )

    records = repository.get_records(None, None, limit=10, offset=0)

    assert records[0].timestamp == start
    assert records[0].disk_read_speed == 1024.5
    assert records[0].disk_write_speed == 2048.25
    assert records[1].timestamp == start + timedelta(seconds=1)
    assert records[1].disk_read_speed == 0
    assert records[1].disk_write_speed is None


def test_battery_history_persists_zero_charging_and_power_state(history_store):
    _, repository, service = history_store
    timestamp = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    service.record_snapshot(
        make_snapshot(timestamp),
        battery_info=make_battery(
            percentage=0,
            charging_state="charging",
            power_plugged=True,
        ),
    )

    record = repository.get_records(None, None, limit=1, offset=0)[0]
    assert record.timestamp == timestamp
    assert record.battery_availability == "available"
    assert record.battery_percentage == 0
    assert record.battery_charging_state == "charging"
    assert record.battery_power_plugged is True


def test_battery_history_persists_discharging_and_unplugged_state(history_store):
    _, repository, service = history_store
    timestamp = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    service.record_snapshot(
        make_snapshot(timestamp),
        battery_info=make_battery(
            percentage=42.5,
            charging_state="discharging",
            power_plugged=False,
        ),
    )

    record = repository.get_records(None, None, limit=1, offset=0)[0]
    assert record.battery_percentage == 42.5
    assert record.battery_charging_state == "discharging"
    assert record.battery_power_plugged is False


def test_fully_charged_battery_history_is_not_marked_charging(history_store):
    _, repository, service = history_store
    timestamp = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    service.record_snapshot(
        make_snapshot(timestamp),
        battery_info=make_battery(
            percentage=100,
            charging_state="not_charging",
            power_plugged=True,
        ),
    )

    record = repository.get_records(None, None, limit=1, offset=0)[0]
    assert record.battery_percentage == 100
    assert record.battery_charging_state == "not_charging"
    assert record.battery_power_plugged is True


def test_missing_battery_persists_availability_and_null_readings(history_store):
    _, repository, service = history_store
    timestamp = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    service.record_snapshot(
        make_snapshot(timestamp),
        battery_info=make_battery(
            availability="unavailable",
            percentage=None,
            charging_state="unknown",
            power_plugged=None,
        ),
    )

    record = repository.get_records(None, None, limit=1, offset=0)[0]
    assert record.battery_availability == "unavailable"
    assert record.battery_percentage is None
    assert record.battery_charging_state is None
    assert record.battery_power_plugged is None


def test_old_history_database_migration_preserves_existing_rows(tmp_path: Path):
    path = tmp_path / "legacy-history.sqlite3"
    database = Database(path)
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
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
        connection.exec_driver_sql(
            """
            INSERT INTO historical_metrics
                (id, timestamp, cpu_utilization_percent, disk_read_bytes)
            VALUES (17, '2026-11-02 12:00:00.000000', 55.5, 987654)
            """
        )

    database.initialize()
    database.initialize()
    inspector = inspect(database.engine)
    columns = {column["name"] for column in inspector.get_columns("historical_metrics")}
    assert {
        "disk_read_speed",
        "disk_write_speed",
        "battery_availability",
        "battery_percentage",
        "battery_charging_state",
        "battery_power_plugged",
    } <= columns
    assert "historical_temperature_metrics" in inspector.get_table_names()

    records = HistoryRepository(
        database.session_factory, path
    ).get_records(None, None, limit=10, offset=0)
    assert len(records) == 1
    assert records[0].id == 17
    assert records[0].cpu_utilization_percent == 55.5
    assert records[0].disk_read_bytes == 987654
    assert records[0].disk_read_speed is None
    assert records[0].disk_write_speed is None
    assert records[0].battery_availability is None
    assert records[0].battery_percentage is None
    assert records[0].battery_charging_state is None
    assert records[0].battery_power_plugged is None
    assert "historical_network_interface_metrics" in inspector.get_table_names()
    database.dispose()


def test_per_interface_throughput_persists_values_nulls_and_timestamps(history_store):
    database, _, service = history_store
    start = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    service.record_snapshot(
        make_snapshot(
            start,
            interfaces=[
                {
                    "name": "Wi-Fi",
                    "is_up": True,
                    "speed_mbps": 100.0,
                    "mtu": 1500,
                    "addresses": [],
                    "bytes_received": 1000,
                    "bytes_sent": 2000,
                    "packets_received": 10,
                    "packets_sent": 20,
                    "download_speed_bytes_per_sec": 512.5,
                    "download_speed_mb_per_sec": 512.5 / 1024**2,
                    "download_available": True,
                    "download_status": "available",
                    "upload_speed_bytes_per_sec": 0,
                    "upload_speed_mb_per_sec": 0,
                    "upload_available": True,
                    "upload_status": "available",
                },
                {
                    "name": "Ethernet",
                    "is_up": False,
                    "speed_mbps": None,
                    "mtu": None,
                    "addresses": [],
                    "bytes_received": None,
                    "bytes_sent": None,
                    "packets_received": None,
                    "packets_sent": None,
                    "download_speed_bytes_per_sec": None,
                    "download_speed_mb_per_sec": None,
                    "download_available": False,
                    "download_status": "unavailable",
                    "upload_speed_bytes_per_sec": None,
                    "upload_speed_mb_per_sec": None,
                    "upload_available": False,
                    "upload_status": "unavailable",
                },
            ],
        )
    )
    service.record_snapshot(
        make_snapshot(
            start + timedelta(seconds=1),
            interfaces=[
                {
                    "name": "Wi-Fi",
                    "is_up": True,
                    "speed_mbps": 100.0,
                    "mtu": 1500,
                    "addresses": [],
                    "bytes_received": 1000,
                    "bytes_sent": 2000,
                    "packets_received": 10,
                    "packets_sent": 20,
                    "download_speed_bytes_per_sec": 0,
                    "download_speed_mb_per_sec": 0,
                    "download_available": True,
                    "download_status": "available",
                    "upload_speed_bytes_per_sec": None,
                    "upload_speed_mb_per_sec": None,
                    "upload_available": False,
                    "upload_status": "unavailable",
                },
                {
                    "name": "VPN Adapter",
                    "is_up": True,
                    "speed_mbps": None,
                    "mtu": 1500,
                    "addresses": [],
                    "bytes_received": 50,
                    "bytes_sent": 75,
                    "packets_received": 1,
                    "packets_sent": 1,
                    "download_speed_bytes_per_sec": 25,
                    "download_speed_mb_per_sec": 25 / 1024**2,
                    "download_available": True,
                    "download_status": "available",
                    "upload_speed_bytes_per_sec": 30,
                    "upload_speed_mb_per_sec": 30 / 1024**2,
                    "upload_available": True,
                    "upload_status": "available",
                },
            ],
        )
    )
    with database.session_factory() as session:
        rows = list(
            session.scalars(
                select(HistoricalNetworkInterfaceMetrics).order_by(
                    HistoricalNetworkInterfaceMetrics.timestamp,
                    HistoricalNetworkInterfaceMetrics.interface_name,
                )
            )
        )

    assert [(row.timestamp, row.interface_name) for row in rows] == [
        (start, "Ethernet"),
        (start, "Wi-Fi"),
        (start + timedelta(seconds=1), "VPN Adapter"),
        (start + timedelta(seconds=1), "Wi-Fi"),
    ]
    assert rows[0].download_speed is None
    assert rows[0].upload_speed is None
    assert rows[1].download_speed == 512.5
    assert rows[1].upload_speed == 0
    assert rows[3].download_speed == 0
    assert rows[3].upload_speed is None


def test_retention_removes_expired_interface_samples(history_store):
    database, _, service = history_store
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    expired = now - timedelta(days=31)
    retained = now - timedelta(days=1)
    interface = {
        "name": "eth0",
        "is_up": True,
        "speed_mbps": None,
        "mtu": None,
        "addresses": [],
        "bytes_received": 1,
        "bytes_sent": 1,
        "packets_received": 1,
        "packets_sent": 1,
        "download_speed_bytes_per_sec": 0,
        "download_speed_mb_per_sec": 0,
        "download_available": True,
        "download_status": "available",
        "upload_speed_bytes_per_sec": None,
        "upload_speed_mb_per_sec": None,
        "upload_available": False,
        "upload_status": "unavailable",
    }
    service.record_snapshot(make_snapshot(expired, interfaces=[interface]))
    service.record_snapshot(make_snapshot(retained, interfaces=[interface]))

    service.cleanup_expired(now)

    with database.session_factory() as session:
        rows = list(session.scalars(select(HistoricalNetworkInterfaceMetrics)))
    assert len(rows) == 1
    assert rows[0].timestamp == retained


def test_duplicate_collection_timestamp_is_rejected_without_second_record(
    history_store,
) -> None:
    _, repository, service = history_store
    timestamp = datetime.now(timezone.utc)
    snapshot = make_snapshot(timestamp)
    service.record_snapshot(snapshot)

    with pytest.raises(HistoryStorageError):
        service.record_snapshot(snapshot)

    assert len(repository.get_records(None, None, limit=10, offset=0)) == 1


def test_history_endpoints_filter_paginate_sort_and_aggregate(
    history_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, service = history_store
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    for index in range(3):
        service.record_snapshot(
            make_snapshot(
                start + timedelta(minutes=index),
                cpu=10.0 * (index + 1),
                ram=20.0 * (index + 1),
                download=100.0 * (index + 1),
                upload=200.0 * (index + 1),
            )
        )
    monkeypatch.setattr("app.api.routes.history.history_service", service)

    with TestClient(app) as client:
        records_response = client.get("/api/history")
        filtered_response = client.get(
            "/api/history",
            params={
                "start_time": (start + timedelta(minutes=1)).isoformat(),
                "end_time": (start + timedelta(minutes=1)).isoformat(),
            },
        )
        page_response = client.get("/api/history?limit=1&offset=1")
        summary_response = client.get("/api/history/summary")
        filtered_summary_response = client.get(
            "/api/history/summary",
            params={
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(minutes=1)).isoformat(),
            },
        )
        stats_response = client.get("/api/history/stats")
        invalid_range_response = client.get(
            "/api/history",
            params={
                "start_time": (start + timedelta(minutes=2)).isoformat(),
                "end_time": start.isoformat(),
            },
        )
        invalid_limit_response = client.get("/api/history?limit=1001")

    records = records_response.json()
    assert records_response.status_code == 200
    assert len(records) == 3
    assert [record["timestamp"] for record in records] == sorted(
        record["timestamp"] for record in records
    )
    assert filtered_response.status_code == 200
    assert len(filtered_response.json()) == 1
    assert page_response.json()[0]["cpu_utilization_percent"] == 20.0
    assert invalid_range_response.status_code == 422
    assert invalid_limit_response.status_code == 422

    summary = summary_response.json()
    assert summary == {
        "average_cpu_utilization_percent": 20.0,
        "maximum_cpu_utilization_percent": 30.0,
        "average_ram_utilization_percent": 40.0,
        "maximum_ram_utilization_percent": 60.0,
        "average_download_speed": 200.0,
        "maximum_download_speed": 300.0,
        "average_upload_speed": 400.0,
        "maximum_upload_speed": 600.0,
        "total_record_count": 3,
        "earliest_timestamp": "2026-11-01T00:00:00Z",
        "latest_timestamp": "2026-11-01T00:02:00Z",
    }
    assert filtered_summary_response.json()["total_record_count"] == 2
    stats = stats_response.json()
    assert stats["total_historical_records"] == 3
    assert stats["retention_period_days"] == 30
    assert stats["database_file_size_bytes"] > 0
    assert stats["earliest_timestamp"] == "2026-11-01T00:00:00Z"


def test_history_endpoints_return_empty_results_when_database_has_no_records(
    history_store, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, service = history_store
    monkeypatch.setattr("app.api.routes.history.history_service", service)

    with TestClient(app) as client:
        records = client.get("/api/history")
        summary = client.get("/api/history/summary")

    assert records.status_code == 200
    assert records.json() == []
    assert summary.json()["total_record_count"] == 0
    assert summary.json()["average_cpu_utilization_percent"] is None


def test_retention_deletes_expired_and_preserves_recent_records(history_store) -> None:
    _, repository, service = history_store
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    service.record_snapshot(make_snapshot(now - timedelta(days=31)))
    service.record_snapshot(make_snapshot(now - timedelta(days=29)))

    deleted_count = service.cleanup_expired(now)
    remaining = repository.get_records(None, None, limit=10, offset=0)

    assert deleted_count == 1
    assert len(remaining) == 1
    assert remaining[0].timestamp == now - timedelta(days=29)


def test_retention_configuration_accepts_positive_days_and_rejects_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HISTORY_RETENTION_DAYS", "7")
    assert _history_retention_days_from_environment() == 7

    for invalid_value in ("0", "-1", "1.5", "invalid"):
        monkeypatch.setenv("HISTORY_RETENTION_DAYS", invalid_value)
        with pytest.raises(ValueError):
            _history_retention_days_from_environment()


def test_history_stats_reports_custom_retention_period(history_store) -> None:
    _, repository, _ = history_store
    seven_day_service = HistoryService(repository, retention_days=7)

    statistics = seven_day_service.get_stats()

    assert statistics["retention_days"] == 7


def test_background_collector_persists_each_completed_snapshot(history_store) -> None:
    database, repository, service = history_store

    async def collect_one_cycle() -> MonitoringSnapshotResponse:
        monitor = MonitoringService(interval_seconds=0.25, history_storage=service)
        await monitor.start()
        deadline = asyncio.get_running_loop().time() + 5
        try:
            while not repository.get_records(None, None, limit=1, offset=0):
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("Monitoring cycle was not persisted")
                await asyncio.sleep(0.01)
            snapshot = monitor.get_snapshot()
            assert snapshot is not None
            return snapshot
        finally:
            await monitor.stop()

    snapshot = asyncio.run(collect_one_cycle())
    records = repository.get_records(None, None, limit=10, offset=0)

    assert len(records) == 1
    assert records[0].timestamp == datetime.fromisoformat(snapshot.timestamp)
    database.dispose()


def test_database_write_failure_does_not_stop_monitor_or_clear_snapshot(
    history_store, caplog: pytest.LogCaptureFixture
) -> None:
    _, repository, service = history_store

    def fail_insert_snapshot(
        record, interface_records, temperature_records=None
    ) -> None:
        raise OperationalError("insert", {}, RuntimeError("database unavailable"))

    with patch.object(repository, "insert_snapshot", side_effect=fail_insert_snapshot):
        async def collect_after_write_failure() -> tuple[
            MonitoringService, object, object
        ]:
            monitor = MonitoringService(interval_seconds=0.25, history_storage=service)
            await monitor.start()
            deadline = asyncio.get_running_loop().time() + 5
            try:
                while monitor.get_snapshot() is None:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise AssertionError("Monitoring snapshot was not produced")
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0.05)
                return monitor, monitor.get_snapshot(), monitor.get_status()
            finally:
                await monitor.stop()

        monitor, snapshot, status = asyncio.run(collect_after_write_failure())

    assert snapshot is not None
    assert status.running is True
    assert monitor.get_snapshot() is not None
    assert "Unable to insert monitoring record" in caplog.text
    assert repository.get_records(None, None, limit=10, offset=0) == []
