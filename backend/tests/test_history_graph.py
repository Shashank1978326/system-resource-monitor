"""Tests for the bounded historical graph API."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database.connection import Database
from app.database.models import HistoricalMetrics, HistoricalNetworkInterfaceMetrics
from app.database.repository import HistoryRepository
from app.main import app
from app.services.history_service import HistoryService

_METRIC_VALUES = {
    "cpu": ("cpu_utilization_percent", 12.5, "percent"),
    "memory": ("ram_utilization_percent", 32.5, "percent"),
    "disk": ("disk_utilization_percent", 42.5, "percent"),
    "network_download": ("network_download_speed", 1024.0, "bytes_per_second"),
    "network_upload": ("network_upload_speed", 512.0, "bytes_per_second"),
    "disk_read": ("disk_read_bytes", 2048, "bytes"),
    "disk_write": ("disk_write_bytes", 4096, "bytes"),
    "disk_read_speed": ("disk_read_speed", 2048.0, "bytes_per_second"),
    "disk_write_speed": ("disk_write_speed", 4096.0, "bytes_per_second"),
    "battery": ("battery_percentage", 0.0, "percent"),
}
_TIME_RANGES = ("5m", "15m", "30m", "1h", "6h", "12h", "24h", "7d")
_INTERVALS = ("1m", "5m", "15m", "1h")


@pytest.fixture
def graph_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = Database(tmp_path / "graph-history.sqlite3")
    database.initialize()
    repository = HistoryRepository(database.session_factory, database.path)
    service = HistoryService(repository, retention_days=30)
    monkeypatch.setattr("app.api.routes.history.history_service", service)
    yield repository, service
    database.dispose()


def _insert_record(
    repository: HistoryRepository,
    timestamp: datetime,
    **metric_values: float | int | None,
) -> None:
    values = {column: None for column, _, _ in _METRIC_VALUES.values()}
    values.update(metric_values)
    repository.insert(HistoricalMetrics(timestamp=timestamp, **values))


def _insert_interface_record(
    repository: HistoryRepository,
    timestamp: datetime,
    interface_name: str,
    download_speed: float | None,
    upload_speed: float | None,
) -> None:
    interface_record = HistoricalNetworkInterfaceMetrics(
        timestamp=timestamp,
        interface_name=interface_name,
        download_speed=download_speed,
        upload_speed=upload_speed,
    )
    repository.insert_snapshot(
        HistoricalMetrics(timestamp=timestamp),
        [interface_record],
    )


def test_graph_supports_every_metric_and_returns_units(graph_service) -> None:
    repository, _ = graph_service
    now = datetime.now(timezone.utc)
    metric_fields = {
        column: value for column, value, _ in _METRIC_VALUES.values()
    }
    _insert_record(repository, now, **metric_fields)

    with TestClient(app) as client:
        for metric, (column, value, unit) in _METRIC_VALUES.items():
            response = client.get(
                "/api/history/graph",
                params={"metric": metric, "range": "1h", "interval": "1m"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["metric"] == metric
            assert body["unit"] == unit
            assert body["data_points"][-1]["value"] == value
            assert body["data_points"][-1]["timestamp"].endswith("Z")


def test_graph_accepts_all_supported_ranges_and_intervals(graph_service) -> None:
    with TestClient(app) as client:
        for time_range in _TIME_RANGES:
            response = client.get(
                "/api/history/graph",
                params={"metric": "cpu", "range": time_range, "interval": "1h"},
            )
            assert response.status_code == 200
            assert response.json()["time_range"] == time_range

        for interval in _INTERVALS:
            response = client.get(
                "/api/history/graph",
                params={"metric": "cpu", "range": "1h", "interval": interval},
            )
            assert response.status_code == 200
            assert response.json()["interval"] == interval


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("metric", "processor"),
        ("range", "10m"),
        ("interval", "30s"),
    ],
)
def test_graph_rejects_unsupported_query_values(
    graph_service, parameter: str, value: str
) -> None:
    params = {"metric": "cpu", "range": "1h", "interval": "1m"}
    params[parameter] = value
    with TestClient(app) as client:
        response = client.get("/api/history/graph", params=params)
    assert response.status_code == 422


def test_graph_returns_empty_array_for_empty_history(graph_service) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "cpu", "range": "1h", "interval": "1m"},
        )
    assert response.status_code == 200
    assert response.json()["data_points"] == []


def test_graph_preserves_null_values_and_averages_each_bucket(graph_service) -> None:
    repository, _ = graph_service
    current_minute = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    first_bucket = current_minute - timedelta(minutes=3)
    _insert_record(
        repository,
        first_bucket + timedelta(seconds=5),
        cpu_utilization_percent=20.0,
    )
    _insert_record(
        repository,
        first_bucket + timedelta(seconds=30),
        cpu_utilization_percent=40.0,
    )
    _insert_record(
        repository,
        first_bucket + timedelta(minutes=1, seconds=10),
        cpu_utilization_percent=None,
    )
    _insert_record(
        repository,
        first_bucket + timedelta(minutes=2, seconds=10),
        cpu_utilization_percent=60.0,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "cpu", "range": "1h", "interval": "1m"},
        )

    points = response.json()["data_points"]
    assert response.status_code == 200
    assert [point["value"] for point in points] == [30.0, None, 60.0]
    assert [point["timestamp"] for point in points] == sorted(
        point["timestamp"] for point in points
    )
    assert points[0]["timestamp"] == first_bucket.isoformat().replace("+00:00", "Z")


def test_battery_graph_averages_percentage_and_keeps_latest_states(graph_service):
    repository, _ = graph_service
    bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
        minutes=2
    )
    first_sample = bucket + timedelta(seconds=5)
    latest_sample = bucket + timedelta(seconds=45)
    _insert_record(
        repository,
        first_sample,
        battery_availability="available",
        battery_percentage=0.0,
        battery_charging_state="charging",
        battery_power_plugged=True,
    )
    _insert_record(
        repository,
        latest_sample,
        battery_availability="available",
        battery_percentage=100.0,
        battery_charging_state="discharging",
        battery_power_plugged=False,
    )
    _insert_record(
        repository,
        bucket + timedelta(minutes=1, seconds=5),
        battery_availability="unavailable",
        battery_percentage=None,
        battery_charging_state=None,
        battery_power_plugged=None,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "1h", "interval": "1m"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["unit"] == "percent"
    assert [point["value"] for point in body["data_points"]] == [50.0, None]
    latest = body["data_points"][0]
    assert latest["charging_state"] == "discharging"
    assert latest["power_plugged"] is False
    assert latest["battery_availability"] == "available"
    assert latest["status_timestamp"] == latest_sample.isoformat().replace(
        "+00:00", "Z"
    )
    unavailable = body["data_points"][1]
    assert unavailable["battery_availability"] == "unavailable"
    assert unavailable["charging_state"] is None
    assert unavailable["power_plugged"] is None
    assert unavailable["value"] is None


def test_battery_graph_filters_outside_time_range(graph_service):
    repository, _ = graph_service
    old = datetime.now(timezone.utc) - timedelta(days=8)
    _insert_record(
        repository,
        old,
        battery_availability="available",
        battery_percentage=42.0,
        battery_charging_state="discharging",
        battery_power_plugged=False,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "battery", "range": "7d", "interval": "1h"},
        )

    assert response.status_code == 200
    assert response.json()["data_points"] == []


@pytest.mark.parametrize(
    ("metric", "column"),
    [
        ("disk_read_speed", "disk_read_speed"),
        ("disk_write_speed", "disk_write_speed"),
    ],
)
def test_disk_throughput_graph_averages_samples_and_preserves_null_and_zero(
    graph_service, metric: str, column: str
) -> None:
    repository, _ = graph_service
    bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
        minutes=2
    )
    _insert_record(repository, bucket + timedelta(seconds=5), **{column: 0.0})
    _insert_record(repository, bucket + timedelta(seconds=30), **{column: 4_194_304.0})
    _insert_record(
        repository,
        bucket + timedelta(minutes=1, seconds=5),
        **{column: None},
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": metric, "range": "1h", "interval": "1m"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["unit"] == "bytes_per_second"
    assert [point["value"] for point in body["data_points"]] == [
        2_097_152.0,
        None,
    ]
    assert [point["timestamp"] for point in body["data_points"]] == sorted(
        point["timestamp"] for point in body["data_points"]
    )


def test_disk_throughput_graph_filters_outside_time_range(graph_service) -> None:
    repository, _ = graph_service
    old = datetime.now(timezone.utc) - timedelta(days=8)
    _insert_record(repository, old, disk_read_speed=1000.0, disk_write_speed=2000.0)

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={
                "metric": "disk_read_speed",
                "range": "7d",
                "interval": "1h",
            },
        )

    assert response.status_code == 200
    assert response.json()["data_points"] == []


def test_graph_rejects_a_query_that_exceeds_the_point_limit(graph_service) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={"metric": "cpu", "range": "7d", "interval": "1m"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("metric", "field"),
    [
        ("network_interface_download", "download_speed"),
        ("network_interface_upload", "upload_speed"),
    ],
)
def test_per_interface_graph_filters_and_aggregates_null_and_zero(
    graph_service, metric: str, field: str
) -> None:
    repository, _ = graph_service
    bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
        minutes=2
    )
    _insert_interface_record(
        repository, bucket + timedelta(seconds=5), "Wi-Fi", 0.0, None
    )
    _insert_interface_record(
        repository, bucket + timedelta(seconds=30), "Wi-Fi", 4_194_304.0, 2_097_152.0
    )
    _insert_interface_record(
        repository, bucket + timedelta(minutes=1, seconds=5), "Wi-Fi", None, 0.0
    )
    _insert_interface_record(
        repository, bucket + timedelta(seconds=20), "Ethernet", 90_000.0, 90_000.0
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={
                "metric": metric,
                "range": "1h",
                "interval": "1m",
                "interface": "Wi-Fi",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["unit"] == "bytes_per_second"
    expected = [2_097_152.0, None] if field == "download_speed" else [
        2_097_152.0,
        0.0,
    ]
    assert [point["value"] for point in body["data_points"]] == expected
    assert [point["timestamp"] for point in body["data_points"]] == sorted(
        point["timestamp"] for point in body["data_points"]
    )


def test_historical_interfaces_endpoint_lists_sorted_recorded_names(graph_service):
    repository, _ = graph_service
    now = datetime.now(timezone.utc)
    _insert_interface_record(repository, now, "Wi-Fi", 1.0, 2.0)
    _insert_interface_record(
        repository, now + timedelta(seconds=1), "Ethernet", 3.0, 4.0
    )

    with TestClient(app) as client:
        response = client.get("/api/history/interfaces")

    assert response.status_code == 200
    assert response.json() == {"interfaces": ["Ethernet", "Wi-Fi"]}


def test_per_interface_graph_validates_selection(graph_service):
    with TestClient(app) as client:
        missing = client.get(
            "/api/history/graph",
            params={
                "metric": "network_interface_download",
                "range": "1h",
                "interval": "1m",
            },
        )
        unknown = client.get(
            "/api/history/graph",
            params={
                "metric": "network_interface_upload",
                "range": "1h",
                "interval": "1m",
                "interface": "not-recorded",
            },
        )
        invalid_combination = client.get(
            "/api/history/graph",
            params={
                "metric": "cpu",
                "range": "1h",
                "interval": "1m",
                "interface": "Wi-Fi",
            },
        )

    assert missing.status_code == 422
    assert unknown.status_code == 404
    assert invalid_combination.status_code == 422


def test_per_interface_graph_applies_time_range(graph_service):
    repository, _ = graph_service
    _insert_interface_record(
        repository,
        datetime.now(timezone.utc) - timedelta(days=8),
        "eth0",
        1000.0,
        2000.0,
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/history/graph",
            params={
                "metric": "network_interface_download",
                "range": "7d",
                "interval": "1h",
                "interface": "eth0",
            },
        )

    assert response.status_code == 200
    assert response.json()["data_points"] == []
