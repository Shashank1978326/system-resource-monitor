"""Tests for CPU alert transitions and REST responses."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database.alert_repository import AlertRepository
from app.database.connection import Database, database, initialize_database
from app.main import app
from app.schemas.monitoring import AlertThresholdsResponse, DiskPartitionResponse
from app.services.alert_service import (
    CpuAlertService,
    alert_repository,
    cpu_alert_service,
)

_TIMESTAMP = "2026-11-03T00:00:00+00:00"


@pytest.fixture(autouse=True)
def reset_alert_service():
    initialize_database()
    alert_repository.clear_events()
    alert_repository.clear_current_states()
    cpu_alert_service.reset()
    cpu_alert_service.update_thresholds(
        AlertThresholdsResponse(
            cpu_warning_threshold_percent=80,
            cpu_critical_threshold_percent=90,
            ram_warning_threshold_percent=80,
            ram_critical_threshold_percent=90,
            disk_warning_threshold_percent=80,
            disk_critical_threshold_percent=90,
        )
    )
    yield
    alert_repository.clear_events()
    alert_repository.clear_current_states()
    cpu_alert_service.reset()
    database.dispose()


@pytest.fixture
def client():
    return TestClient(app)


def test_cpu_below_warning_threshold_is_normal() -> None:
    service = CpuAlertService()
    service.process_sample(79.99, _TIMESTAMP)

    status = service.get_status()
    assert status.status == "Normal"
    assert status.cpu_usage_percent == 79.99
    assert status.warning_threshold_percent == 80
    assert status.critical_threshold_percent == 90
    assert service.get_alerts().recent_events == []


def test_cpu_at_warning_threshold_generates_warning() -> None:
    service = CpuAlertService()
    service.process_sample(80, _TIMESTAMP)

    alert = service.get_alerts()
    assert alert.status.status == "Warning"
    assert alert.status.cpu_usage_percent == 80
    assert len(alert.recent_events) == 1
    assert alert.recent_events[0].severity == "Warning"
    assert "80%" in alert.recent_events[0].message


def test_cpu_at_critical_threshold_generates_critical() -> None:
    service = CpuAlertService()
    service.process_sample(90, _TIMESTAMP)

    event = service.get_alerts().recent_events[0]
    assert event.status == "Critical"
    assert event.severity == "Critical"
    assert event.cpu_usage_percent == 90


def test_warning_to_critical_transition_generates_one_event_per_state() -> None:
    service = CpuAlertService()
    service.process_sample(82, _TIMESTAMP)
    service.process_sample(95, _TIMESTAMP)

    events = service.get_alerts().recent_events
    assert [(event.previous_status, event.status) for event in events] == [
        ("Normal", "Warning"),
        ("Warning", "Critical"),
    ]


def test_critical_to_warning_transition_is_reported() -> None:
    service = CpuAlertService()
    service.process_sample(92, _TIMESTAMP)
    service.process_sample(85, _TIMESTAMP)

    events = service.get_alerts().recent_events
    assert [(event.previous_status, event.status) for event in events] == [
        ("Normal", "Critical"),
        ("Critical", "Warning"),
    ]
    assert events[-1].severity == "Warning"


def test_recovery_to_normal_generates_recovery_event() -> None:
    service = CpuAlertService()
    service.process_sample(84, _TIMESTAMP)
    service.process_sample(60, _TIMESTAMP)

    event = service.get_alerts().recent_events[-1]
    assert event.previous_status == "Warning"
    assert event.status == "Normal"
    assert event.severity == "Normal"
    assert "returned to normal" in event.message


def test_repeated_samples_in_same_state_do_not_duplicate_events() -> None:
    service = CpuAlertService()
    for value in (81, 85, 89.99):
        service.process_sample(value, _TIMESTAMP)

    assert len(service.get_alerts().recent_events) == 1


@pytest.mark.parametrize(
    "value",
    [None, float("nan"), float("inf"), -1, 100.1, True, 10**1000],
)
def test_missing_or_invalid_cpu_samples_do_not_change_alert_state(value) -> None:
    service = CpuAlertService()
    service.process_sample(85, _TIMESTAMP)
    previous = service.get_status()

    service.process_sample(value, "2026-11-03T00:00:01+00:00")

    assert service.get_status() == previous
    assert len(service.get_alerts().recent_events) == 1


def test_custom_thresholds_must_be_ordered_and_finite() -> None:
    with pytest.raises(ValueError):
        CpuAlertService(warning_threshold_percent=90, critical_threshold_percent=90)
    with pytest.raises(ValueError):
        CpuAlertService(warning_threshold_percent=math.nan)


def test_ram_alert_transitions_and_duplicate_prevention() -> None:
    service = CpuAlertService()
    service.process_ram_sample(79.9, _TIMESTAMP)
    service.process_ram_sample(80, _TIMESTAMP)
    service.process_ram_sample(85, _TIMESTAMP)
    service.process_ram_sample(90, _TIMESTAMP)
    service.process_ram_sample(85, _TIMESTAMP)
    service.process_ram_sample(79, _TIMESTAMP)

    alerts = service.get_alerts().ram
    assert alerts.status.status == "Normal"
    assert alerts.status.usage_percent == 79
    assert [event.status for event in alerts.recent_events] == [
        "Warning",
        "Critical",
        "Warning",
        "Normal",
    ]
    assert [event.severity for event in alerts.recent_events] == [
        "Warning",
        "Critical",
        "Warning",
        "Normal",
    ]
    assert alerts.recent_events[0].resource == "ram"


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), -1, 100.1, True])
def test_invalid_ram_measurements_do_not_change_alert_state(value) -> None:
    service = CpuAlertService()
    service.process_ram_sample(85, _TIMESTAMP)
    previous = service.get_alerts().ram

    service.process_ram_sample(value, "2026-11-03T00:00:01+00:00")

    assert service.get_alerts().ram == previous


def _partition(
    mountpoint: str = "D:\\",
    usage: float = 95,
    total: int = 1000,
    used: int = 950,
    free: int = 50,
) -> DiskPartitionResponse:
    return DiskPartitionResponse(
        device="D:",
        mountpoint=mountpoint,
        filesystem="NTFS",
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        usage_percent=usage,
    )


def test_disk_partition_alerts_include_capacity_and_recovery() -> None:
    service = CpuAlertService()
    service.process_disk_sample([_partition(usage=79, used=790, free=210)], _TIMESTAMP)
    service.process_disk_sample([_partition(usage=80, used=800, free=200)], _TIMESTAMP)
    service.process_disk_sample([_partition(usage=85, used=850, free=150)], _TIMESTAMP)
    service.process_disk_sample([_partition(usage=90, used=900, free=100)], _TIMESTAMP)
    service.process_disk_sample([_partition(usage=79, used=790, free=210)], _TIMESTAMP)

    alerts = service.get_alerts().disk
    assert alerts.status.status == "Normal"
    assert len(alerts.status.partitions) == 1
    current = alerts.status.partitions[0]
    assert current.mountpoint == "D:\\"
    assert current.total_bytes == 1000
    assert current.used_bytes == 790
    assert current.free_bytes == 210
    assert current.usage_percent == 79
    assert [event.status for event in alerts.recent_events] == [
        "Warning",
        "Critical",
        "Normal",
    ]
    assert alerts.recent_events[0].mountpoint == "D:\\"
    assert alerts.recent_events[0].free_bytes == 200


def test_disk_alerts_are_independent_per_partition_and_skip_invalid_data() -> None:
    service = CpuAlertService()
    service.process_disk_sample(
        [
            _partition(mountpoint="D:\\", usage=95),
            _partition(mountpoint="E:\\", usage=30, used=300, free=700),
        ],
        _TIMESTAMP,
    )
    service.process_disk_sample(
        [
            _partition(mountpoint="D:\\", usage=95),
            _partition(
                mountpoint="E:\\",
                usage=float("nan"),
                used=300,
                free=700,
            ),
        ],
        "2026-11-03T00:00:01+00:00",
    )

    alerts = service.get_alerts().disk
    assert alerts.status.status == "Critical"
    assert [partition.status for partition in alerts.status.partitions] == [
        "Critical",
        "Normal",
    ]
    assert len(alerts.recent_events) == 1
    assert alerts.recent_events[0].mountpoint == "D:\\"


def test_alert_api_returns_current_status_and_recent_events(
    client: TestClient,
) -> None:
    cpu_alert_service.process_sample(93, _TIMESTAMP)

    response = client.get("/api/alerts")
    assert response.status_code == 200
    result = response.json()
    assert result["status"]["status"] == "Critical"
    assert result["status"]["cpu_usage_percent"] == 93
    assert result["recent_events"][0]["resource"] == "cpu"
    assert result["recent_events"][0]["severity"] == "Critical"
    assert result["recent_events"][0]["timestamp"] == _TIMESTAMP
    assert result["ram"]["status"]["status"] == "Normal"
    assert result["disk"]["status"]["status"] == "Normal"


def test_alert_status_endpoint_returns_current_state(client: TestClient) -> None:
    cpu_alert_service.process_sample(84, _TIMESTAMP)

    response = client.get("/api/alerts/status")
    assert response.status_code == 200
    assert response.json()["status"] == "Warning"
    assert response.json()["warning_threshold_percent"] == 80
    assert response.json()["ram"]["status"] == "Normal"
    assert response.json()["disk"]["status"] == "Normal"


def test_alert_api_includes_ram_and_disk_transitions(client: TestClient) -> None:
    cpu_alert_service.process_ram_sample(91, _TIMESTAMP)
    cpu_alert_service.process_disk_sample([_partition()], _TIMESTAMP)

    response = client.get("/api/alerts")

    assert response.status_code == 200
    result = response.json()
    assert result["ram"]["status"]["status"] == "Critical"
    assert result["ram"]["recent_events"][0]["resource"] == "ram"
    assert result["disk"]["status"]["status"] == "Critical"
    assert result["disk"]["status"]["partitions"][0]["mountpoint"] == "D:\\"
    assert result["disk"]["recent_events"][0]["free_bytes"] == 50
    status_result = client.get("/api/alerts/status").json()
    assert status_result["ram"]["status"] == "Critical"
    assert status_result["disk"]["status"] == "Critical"
    assert status_result["disk"]["partitions"][0]["used_bytes"] == 950


def test_alert_history_filtering_pagination_and_acknowledgement(
    client: TestClient,
) -> None:
    cpu_alert_service.process_sample(85, _TIMESTAMP)
    cpu_alert_service.process_ram_sample(95, _TIMESTAMP)
    cpu_alert_service.process_disk_sample([_partition()], _TIMESTAMP)

    response = client.get(
        "/api/alerts/history",
        params={"resource": "ram", "severity": "Critical", "limit": 1},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert result["events"][0]["resource"] == "ram"
    assert result["events"][0]["acknowledged"] is False

    alert_id = result["events"][0]["id"]
    acknowledged = client.patch(f"/api/alerts/{alert_id}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged"] is True
    assert acknowledged.json()["acknowledged_at"]
    assert client.patch(f"/api/alerts/{alert_id}/acknowledge").json()[
        "acknowledged_at"
    ] == acknowledged.json()["acknowledged_at"]

    page = client.get("/api/alerts/history", params={"limit": 1, "offset": 1})
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert len(page.json()["events"]) == 1


@pytest.mark.parametrize(
    "params",
    [
        {"resource": "gpu"},
        {"severity": "urgent"},
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"offset": 1_000_001},
    ],
)
def test_alert_history_rejects_invalid_filters_and_pagination(
    client: TestClient, params: dict[str, object]
) -> None:
    assert client.get("/api/alerts/history", params=params).status_code == 422


def test_alert_delete_clear_and_invalid_ids(client: TestClient) -> None:
    cpu_alert_service.process_sample(85, _TIMESTAMP)
    alert_id = client.get("/api/alerts/history").json()["events"][0]["id"]

    assert client.delete("/api/alerts/0").status_code == 400
    assert client.patch("/api/alerts/0/acknowledge").status_code == 400
    huge_id = 9_223_372_036_854_775_808
    assert client.delete(f"/api/alerts/{huge_id}").status_code == 400
    assert client.patch(f"/api/alerts/{huge_id}/acknowledge").status_code == 400
    assert client.delete("/api/alerts/999999").status_code == 404
    assert client.patch("/api/alerts/999999/acknowledge").status_code == 404
    assert client.delete(f"/api/alerts/{alert_id}").status_code == 204
    assert client.get("/api/alerts/history").json()["total"] == 0

    cpu_alert_service.process_sample(50, _TIMESTAMP)
    cpu_alert_service.process_sample(85, _TIMESTAMP)
    cleared = client.delete("/api/alerts/history")
    assert cleared.status_code == 200
    assert cleared.json()["deleted"] == 2
    assert client.get("/api/alerts/history").json()["total"] == 0


def test_threshold_api_validation_and_immediate_application(
    client: TestClient,
) -> None:
    updated = {
        "cpu_warning_threshold_percent": 70,
        "cpu_critical_threshold_percent": 88,
        "ram_warning_threshold_percent": 75,
        "ram_critical_threshold_percent": 92,
        "disk_warning_threshold_percent": 60,
        "disk_critical_threshold_percent": 95,
        "temperature_warning_threshold_celsius": 70,
        "temperature_critical_threshold_celsius": 88,
        "battery_warning_threshold_percent": 20,
        "battery_critical_threshold_percent": 10,
    }
    response = client.put("/api/alerts/thresholds", json=updated)
    assert response.status_code == 200
    assert response.json() == updated
    cpu_alert_service.process_sample(72, _TIMESTAMP)
    assert client.get("/api/alerts/status").json()["status"] == "Warning"

    assert client.put(
        "/api/alerts/thresholds",
        json={**updated, "cpu_warning_threshold_percent": 0},
    ).status_code == 422
    assert client.put(
        "/api/alerts/thresholds",
        json={**updated, "ram_warning_threshold_percent": 92},
    ).status_code == 422
    assert client.get("/api/alerts/thresholds").json() == updated


def test_alerts_and_thresholds_survive_database_restart(tmp_path: Path) -> None:
    database_one = Database(tmp_path / "alerts.sqlite3")
    database_one.initialize()
    repository_one = AlertRepository(database_one.session_factory)
    service_one = CpuAlertService(repository=repository_one)
    service_one.update_thresholds(
        AlertThresholdsResponse(
            cpu_warning_threshold_percent=75,
            cpu_critical_threshold_percent=90,
            ram_warning_threshold_percent=80,
            ram_critical_threshold_percent=90,
            disk_warning_threshold_percent=80,
            disk_critical_threshold_percent=90,
        )
    )
    service_one.process_sample(76, _TIMESTAMP)
    service_one.process_sample(77, _TIMESTAMP)
    assert len(
        repository_one.get_events(
            resource=None, severity=None, limit=20, offset=0
        )[0]
    ) == 1
    database_one.dispose()

    database_two = Database(tmp_path / "alerts.sqlite3")
    database_two.initialize()
    repository_two = AlertRepository(database_two.session_factory)
    service_two = CpuAlertService(repository=repository_two)
    service_two.restore_persisted_state()
    assert service_two.get_status().status == "Warning"
    assert service_two.get_status().warning_threshold_percent == 75
    assert len(service_two.get_alerts().recent_events) == 1
    assert service_two.get_alerts().recent_events[0].id == 1
    service_two.process_sample(78, _TIMESTAMP)
    assert len(
        repository_two.get_events(
            resource=None, severity=None, limit=20, offset=0
        )[0]
    ) == 1
    database_two.dispose()


def test_clearing_event_log_does_not_reset_persisted_alert_state(
    tmp_path: Path,
) -> None:
    first_database = Database(tmp_path / "cleared-alerts.sqlite3")
    first_database.initialize()
    first_repository = AlertRepository(first_database.session_factory)
    first_service = CpuAlertService(repository=first_repository)
    first_service.process_sample(85, _TIMESTAMP)
    assert first_repository.clear_events() == 1
    first_database.dispose()

    restarted_database = Database(tmp_path / "cleared-alerts.sqlite3")
    restarted_database.initialize()
    restarted_repository = AlertRepository(restarted_database.session_factory)
    restarted_service = CpuAlertService(repository=restarted_repository)
    restarted_service.restore_persisted_state()
    assert restarted_service.get_status().status == "Warning"
    restarted_service.process_sample(86, _TIMESTAMP)
    assert restarted_repository.get_events(
        resource=None, severity=None, limit=20, offset=0
    )[1] == 0
    restarted_database.dispose()
