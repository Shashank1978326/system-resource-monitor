"""Tests for the live resource monitoring endpoints."""

from types import SimpleNamespace
import time
from unittest.mock import patch

import psutil
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import cpu_service, disk_service, memory_service, network_service


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        deadline = time.monotonic() + 5
        while (
            test_client.get("/api/monitoring/latest").status_code == 503
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        yield test_client


def test_cpu_endpoint_returns_valid_response(client: TestClient) -> None:
    response = client.get("/api/cpu")

    assert response.status_code == 200
    data = response.json()
    assert data["logical_cores"] is None or data["logical_cores"] > 0
    usage = data["cpu_usage_percent"]
    assert usage is None or 0 <= usage <= 100
    if data["per_core_usage"] is not None:
        assert all(0 <= value <= 100 for value in data["per_core_usage"])


def test_cpu_endpoint_handles_unsupported_frequency() -> None:
    with patch("app.services.cpu_service.psutil.cpu_freq", side_effect=psutil.Error):
        assert cpu_service._safe_cpu_frequency() == (None, None, None)


def test_memory_endpoint_returns_valid_response(client: TestClient) -> None:
    response = client.get("/api/memory")

    assert response.status_code == 200
    data = response.json()
    assert data["total_bytes"] > 0
    assert 0 <= data["usage_percent"] <= 100
    assert data["available_bytes"] >= 0
    assert data["swap_total_bytes"] >= 0


def test_memory_endpoint_handles_unavailable_memory_metrics() -> None:
    with patch(
        "app.services.memory_service.psutil.virtual_memory",
        side_effect=psutil.Error,
    ):
        response = memory_service.get_memory_info()

    assert response.total_bytes is None
    assert response.usage_percent is None


def test_disk_endpoint_returns_valid_partitions(client: TestClient) -> None:
    response = client.get("/api/disk")

    assert response.status_code == 200
    data = response.json()
    assert set(data["io"]) == {
        "read_bytes",
        "write_bytes",
        "read_count",
        "write_count",
        "read_speed_bytes_per_sec",
        "read_speed_mb_per_sec",
        "read_speed_status",
        "write_speed_bytes_per_sec",
        "write_speed_mb_per_sec",
        "write_speed_status",
    }
    for partition in data["partitions"]:
        assert set(partition) == {
            "device",
            "mountpoint",
            "filesystem",
            "total_bytes",
            "used_bytes",
            "free_bytes",
            "usage_percent",
        }
        assert partition["total_bytes"] >= 0
        assert partition["used_bytes"] >= 0
        assert partition["free_bytes"] >= 0


def test_disk_skips_inaccessible_partitions() -> None:
    partition = SimpleNamespace(
        device="device",
        mountpoint="mount",
        fstype="fstype",
    )
    with (
        patch("app.services.disk_service.psutil.disk_partitions", return_value=[partition]),
        patch("app.services.disk_service.psutil.disk_usage", side_effect=PermissionError),
    ):
        response = disk_service.get_disk_info()

    assert response.partitions == []


def test_network_endpoint_returns_nonnegative_counters_and_speeds(
    client: TestClient,
) -> None:
    response = client.get("/api/network")

    assert response.status_code == 200
    data = response.json()
    for key in ("bytes_received", "bytes_sent", "packets_received", "packets_sent"):
        assert data[key] is None or data[key] >= 0
    for key in (
        "download_speed_bytes_per_sec",
        "upload_speed_bytes_per_sec",
        "download_speed_mbps",
        "upload_speed_mbps",
    ):
        assert data[key] is None or data[key] >= 0


def test_network_speed_uses_nonnegative_counter_deltas() -> None:
    initial = SimpleNamespace(
        bytes_recv=100,
        bytes_sent=200,
        packets_recv=1,
        packets_sent=2,
    )
    increased = SimpleNamespace(
        bytes_recv=300,
        bytes_sent=500,
        packets_recv=3,
        packets_sent=5,
    )
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth-test": initial},
                initial,
                {"eth-test": increased},
                increased,
            ],
        ),
        patch("app.services.network_service.time.monotonic", side_effect=[10.0, 12.0]),
    ):
        with network_service._lock:
            network_service._baseline = None
        first = network_service.get_network_info()
        second = network_service.get_network_info()

    assert first.download_speed_bytes_per_sec is None
    assert second.download_speed_bytes_per_sec == 100
    assert second.upload_speed_bytes_per_sec == 150


def test_network_counter_reset_does_not_create_negative_speed() -> None:
    before_reset = SimpleNamespace(
        bytes_recv=500,
        bytes_sent=800,
        packets_recv=5,
        packets_sent=8,
    )
    after_reset = SimpleNamespace(
        bytes_recv=10,
        bytes_sent=20,
        packets_recv=1,
        packets_sent=2,
    )
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth-test": before_reset},
                before_reset,
                {"eth-test": after_reset},
                after_reset,
            ],
        ),
        patch("app.services.network_service.time.monotonic", side_effect=[20.0, 21.0]),
    ):
        with network_service._lock:
            network_service._baseline = None
        network_service.get_network_info()
        response = network_service.get_network_info()

    assert response.download_speed_bytes_per_sec == 0
    assert response.upload_speed_bytes_per_sec == 0


def test_existing_root_health_and_system_info_endpoints_remain_available(
    client: TestClient,
) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/system/info").status_code == 200


def test_latest_snapshot_and_monitoring_status(client: TestClient) -> None:
    snapshot_response = client.get("/api/monitoring/latest")
    status_response = client.get("/api/monitoring/status")

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert set(snapshot) == {
        "timestamp",
        "cpu",
        "memory",
        "disk",
        "network",
        "collection_status",
        "metric_errors",
    }
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["running"] is True
    assert status["interval_seconds"] > 0
    assert status["successful_cycles"] >= 1
    assert status["started_at"] is not None


def test_resource_routes_serve_same_snapshot(client: TestClient) -> None:
    snapshot = client.get("/api/monitoring/latest").json()

    assert client.get("/api/cpu").json() == snapshot["cpu"]
    assert client.get("/api/memory").json() == snapshot["memory"]
    assert client.get("/api/disk").json() == snapshot["disk"]
    assert client.get("/api/network").json() == snapshot["network"]


def test_latest_snapshot_reports_initialization_when_not_ready(
    client: TestClient,
) -> None:
    with patch(
        "app.api.routes.monitoring.monitoring_service.get_snapshot",
        return_value=None,
    ):
        response = client.get("/api/monitoring/latest")

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "initializing"


def test_collection_failure_does_not_prevent_other_metrics() -> None:
    from app.services.monitoring_service import MonitoringService

    with patch(
        "app.services.monitoring_service.get_cpu_info",
        side_effect=RuntimeError("test failure"),
    ):
        cpu, memory, disk, network, errors = MonitoringService._collect_metrics()

    assert "cpu" in errors
    assert cpu.cpu_usage_percent is None
    assert memory.total_bytes is not None
    assert disk.io is not None
    assert network.interfaces is not None
