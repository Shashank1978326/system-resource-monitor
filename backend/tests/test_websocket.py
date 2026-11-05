"""Tests for live updates using only the existing monitoring snapshot."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main_module
from app.api.routes.websocket import connection_manager
from app.schemas.monitoring import (
    CpuResponse,
    DiskIoResponse,
    DiskPartitionResponse,
    DiskResponse,
    MemoryResponse,
    MonitoringSnapshotResponse,
    NetworkResponse,
)


def _snapshot() -> MonitoringSnapshotResponse:
    return MonitoringSnapshotResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        cpu=CpuResponse(
            cpu_usage_percent=35.5,
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
            used_bytes=624,
            available_bytes=376,
            free_bytes=300,
            usage_percent=62.4,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        ),
        disk=DiskResponse(
            partitions=[
                DiskPartitionResponse(
                    device="disk",
                    mountpoint="mount",
                    filesystem="test",
                    total_bytes=100,
                    used_bytes=45,
                    free_bytes=55,
                    usage_percent=45.0,
                )
            ],
            io=DiskIoResponse(
                read_bytes=1000,
                write_bytes=2000,
                read_count=1,
                write_count=2,
            ),
        ),
        network=NetworkResponse(
            bytes_received=1000,
            bytes_sent=2000,
            packets_received=1,
            packets_sent=2,
            download_speed_bytes_per_sec=102400,
            upload_speed_bytes_per_sec=51200,
            download_speed_mbps=None,
            upload_speed_mbps=None,
            interfaces=[],
        ),
        collection_status="healthy",
        metric_errors={},
    )


class SnapshotProvider:
    def __init__(self, snapshots: list[MonitoringSnapshotResponse | None]) -> None:
        self.snapshots = snapshots
        self.stopped = False

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        self.stopped = True

    def get_snapshot(self) -> MonitoringSnapshotResponse | None:
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0] if self.snapshots else None


@pytest.fixture
def snapshot_provider(monkeypatch: pytest.MonkeyPatch):
    provider = SnapshotProvider([_snapshot()])
    monkeypatch.setattr(main_module, "monitoring_service", provider)
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(websocket_publish_interval_seconds=0.01),
    )
    assert connection_manager.client_count == 0
    yield provider
    assert connection_manager.client_count == 0


def _receive_update(websocket) -> dict:
    message = websocket.receive_json()
    assert message["type"] == "resource_update"
    assert set(message["data"]) == {
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "network_download_bytes_per_sec",
        "network_upload_bytes_per_sec",
    }
    return message


def test_websocket_sends_latest_safe_snapshot(snapshot_provider) -> None:
    snapshot = snapshot_provider.snapshots[0]
    with TestClient(main_module.app) as client:
        with client.websocket_connect(
            "/ws/monitoring",
            headers={"origin": "http://127.0.0.1:5173"},
        ) as websocket:
            message = _receive_update(websocket)
    assert message["timestamp"].endswith("Z")
    assert message["data"] == {
        "cpu_percent": 35.5,
        "memory_percent": 62.4,
        "disk_percent": 45.0,
        "network_download_bytes_per_sec": 102400.0,
        "network_upload_bytes_per_sec": 51200.0,
    }
    assert message["timestamp"] == snapshot.timestamp.replace("+00:00", "Z")
    assert snapshot_provider.stopped


def test_websocket_broadcasts_to_multiple_clients(snapshot_provider) -> None:
    with TestClient(main_module.app) as client:
        with client.websocket_connect(
            "/ws/monitoring",
            headers={"origin": "http://127.0.0.1:5173"},
        ) as first:
            with client.websocket_connect(
                "/ws/monitoring",
                headers={"origin": "http://localhost:5173"},
            ) as second:
                first_message = _receive_update(first)
                second_message = _receive_update(second)
    assert first_message == second_message


def test_websocket_removes_disconnected_clients(snapshot_provider) -> None:
    with TestClient(main_module.app) as client:
        with client.websocket_connect(
            "/ws/monitoring",
            headers={"origin": "http://127.0.0.1:5173"},
        ) as websocket:
            _receive_update(websocket)
            assert connection_manager.client_count == 1
    assert connection_manager.client_count == 0


def test_websocket_waits_for_an_initial_snapshot(snapshot_provider, monkeypatch) -> None:
    snapshot = _snapshot()
    snapshot_provider.snapshots = [None, snapshot]
    with TestClient(main_module.app) as client:
        with client.websocket_connect(
            "/ws/monitoring",
            headers={"origin": "http://127.0.0.1:5173"},
        ) as websocket:
            message = _receive_update(websocket)
    assert message["timestamp"] == snapshot.timestamp.replace("+00:00", "Z")


def test_websocket_publisher_stops_during_application_shutdown(
    snapshot_provider,
) -> None:
    with TestClient(main_module.app):
        pass
    assert snapshot_provider.stopped


def test_websocket_rejects_untrusted_origins(snapshot_provider) -> None:
    with TestClient(main_module.app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect(
                "/ws/monitoring",
                headers={"origin": "https://untrusted.example"},
            ):
                pytest.fail("An untrusted origin must not connect")
    assert rejected.value.code == 1008
    assert connection_manager.client_count == 0


def test_websocket_rejects_connections_without_an_origin(snapshot_provider) -> None:
    with TestClient(main_module.app) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/ws/monitoring"):
                pytest.fail("A connection without Origin must not be accepted")
    assert rejected.value.code == 1008
