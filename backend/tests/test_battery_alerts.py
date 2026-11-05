"""Tests for battery alerts: threshold validation, transitions, recovery, persistence, and APIs."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database.alert_repository import AlertRepository
from app.database.connection import Database, database, initialize_database
from app.main import app
from app.schemas.monitoring import (
    AlertThresholdsResponse,
    BatteryResponse,
    DiskPartitionResponse,
    TemperatureResponse,
)
from app.services.alert_service import (
    CpuAlertService,
    alert_repository,
    cpu_alert_service,
)

_TIMESTAMP = "2026-11-03T00:00:00+00:00"
_TIMESTAMP_2 = "2026-11-03T00:01:00+00:00"
_TIMESTAMP_3 = "2026-11-03T00:02:00+00:00"
_TIMESTAMP_4 = "2026-11-03T00:03:00+00:00"


def _make_battery(
    percentage: float | None = 50.0,
    charging_state: str = "discharging",
    power_plugged: bool | None = False,
    availability: str = "available",
    message: str = "Real battery detected",
) -> BatteryResponse:
    return BatteryResponse(
        availability=availability,
        platform="Windows",
        percentage=percentage,
        charging_state=charging_state,
        power_plugged=power_plugged,
        remaining_seconds=3600 if percentage else None,
        remaining_time="1 hour" if percentage else None,
        message=message,
    )


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
            temperature_warning_threshold_celsius=80,
            temperature_critical_threshold_celsius=90,
            battery_warning_threshold_percent=20,
            battery_critical_threshold_percent=10,
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


def test_battery_normal_when_discharging_above_warning() -> None:
    bat = _make_battery(percentage=50.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Normal"
    assert status.severity == "Normal"
    assert status.percentage == 50.0
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0


def test_battery_warning_threshold_transition() -> None:
    # 20% is exactly at the warning threshold (warning=20, critical=10)
    bat = _make_battery(percentage=20.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Warning"
    assert status.severity == "Warning"
    assert status.percentage == 20.0

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 1
    assert events[0].previous_status == "Normal"
    assert events[0].status == "Warning"
    assert events[0].severity == "Warning"
    assert events[0].percentage == 20.0
    assert events[0].configured_threshold_percent == 20.0
    assert "warning threshold" in events[0].message.lower()


def test_battery_critical_threshold_transition() -> None:
    # 10% or below triggers critical
    bat = _make_battery(percentage=8.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Critical"
    assert status.severity == "Critical"

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 1
    assert events[0].previous_status == "Normal"
    assert events[0].status == "Critical"
    assert events[0].severity == "Critical"
    assert events[0].percentage == 8.0
    assert events[0].configured_threshold_percent == 10.0
    assert "critical" in events[0].message.lower()


def test_battery_warning_to_critical_transition() -> None:
    # Cycle 1: 15% -> Warning
    bat1 = _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat1, _TIMESTAMP)
    assert cpu_alert_service.get_battery_status().status == "Warning"

    # Cycle 2: 8% -> Critical
    bat2 = _make_battery(percentage=8.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat2, _TIMESTAMP_2)
    assert cpu_alert_service.get_battery_status().status == "Critical"

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 2
    assert events[0].previous_status == "Normal"
    assert events[0].status == "Warning"
    assert events[1].previous_status == "Warning"
    assert events[1].status == "Critical"


def test_battery_recovery_when_external_power_connected() -> None:
    # First drop into warning
    bat1 = _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat1, _TIMESTAMP)
    assert cpu_alert_service.get_battery_status().status == "Warning"

    # Then connect power (charging_state="charging", power_plugged=True)
    bat2 = _make_battery(percentage=16.0, charging_state="charging", power_plugged=True)
    cpu_alert_service.process_battery_sample(bat2, _TIMESTAMP_2)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Normal"
    assert status.severity == "Normal"

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 2
    assert events[1].previous_status == "Warning"
    assert events[1].status == "Normal"
    assert "external power connected" in events[1].message.lower()


def test_battery_recovery_from_critical_when_external_power_connected() -> None:
    # First drop into critical
    bat1 = _make_battery(percentage=5.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat1, _TIMESTAMP)
    assert cpu_alert_service.get_battery_status().status == "Critical"

    # Then plug in (power_plugged=True)
    bat2 = _make_battery(percentage=6.0, charging_state="charging", power_plugged=True)
    cpu_alert_service.process_battery_sample(bat2, _TIMESTAMP_2)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Normal"

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 2
    assert events[1].previous_status == "Critical"
    assert events[1].status == "Normal"
    assert "external power connected" in events[1].message.lower()


def test_battery_recovery_when_percentage_rises_above_warning() -> None:
    # Drop to warning
    bat1 = _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat1, _TIMESTAMP)
    assert cpu_alert_service.get_battery_status().status == "Warning"

    # Rises above warning threshold while still on battery
    bat2 = _make_battery(percentage=25.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat2, _TIMESTAMP_2)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Normal"

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 2
    assert events[1].previous_status == "Warning"
    assert events[1].status == "Normal"
    assert "returned to normal" in events[1].message.lower()


def test_battery_duplicate_prevention_across_cycles() -> None:
    # Cycle 1: 15% (Warning) -> 1 event
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False),
        _TIMESTAMP,
    )
    # Cycle 2: 14% (still Warning) -> 0 new events
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=14.0, charging_state="discharging", power_plugged=False),
        _TIMESTAMP_2,
    )
    # Cycle 3: 12% (still Warning) -> 0 new events
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=12.0, charging_state="discharging", power_plugged=False),
        _TIMESTAMP_3,
    )

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 1
    assert cpu_alert_service.get_battery_status().percentage == 12.0

    # Cycle 4: 8% (Critical) -> 1 new event
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=8.0, charging_state="discharging", power_plugged=False),
        _TIMESTAMP_4,
    )
    # Cycle 5: 7% (still Critical) -> 0 new events
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=7.0, charging_state="discharging", power_plugged=False),
        "2026-11-03T00:04:00+00:00",
    )

    events = cpu_alert_service.get_battery_alerts().recent_events
    assert len(events) == 2


def test_battery_charging_state_suppresses_alerts() -> None:
    # 5% battery, but charging
    bat = _make_battery(percentage=5.0, charging_state="charging", power_plugged=True)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)

    status = cpu_alert_service.get_battery_status()
    assert status.status == "Normal"
    assert status.severity == "Normal"
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0


def test_missing_or_unavailable_battery_does_not_alert_or_falsely_recover() -> None:
    # When missing battery, should be Normal, no alerts
    missing_bat = _make_battery(
        percentage=None,
        charging_state="unknown",
        power_plugged=None,
        availability="unavailable",
        message="No battery detected",
    )
    cpu_alert_service.process_battery_sample(missing_bat, _TIMESTAMP)
    status = cpu_alert_service.get_battery_status()
    assert status.availability == "unavailable"
    assert status.percentage is None
    assert status.status == "Normal"
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0

    # None passed as battery
    cpu_alert_service.process_battery_sample(None, _TIMESTAMP_2)
    assert cpu_alert_service.get_battery_status().availability == "unavailable"
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0

    # Now transition to warning
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False),
        _TIMESTAMP_3,
    )
    assert cpu_alert_service.get_battery_status().status == "Warning"
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 1

    # Now sensor temporarily becomes unavailable -> Must NOT generate false recovery!
    cpu_alert_service.process_battery_sample(missing_bat, _TIMESTAMP_4)
    # Status retains "Warning" severity, percentage is None, no new recovery event
    assert cpu_alert_service.get_battery_status().status == "Warning"
    assert cpu_alert_service.get_battery_status().percentage is None
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 1

    # When battery returns at 15%, no duplicate alert event
    cpu_alert_service.process_battery_sample(
        _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False),
        "2026-11-03T00:04:00+00:00",
    )
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 1


def test_battery_null_or_invalid_percentage_handled_safely() -> None:
    bat = _make_battery(percentage=None, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)
    assert cpu_alert_service.get_battery_status().percentage is None
    assert cpu_alert_service.get_battery_status().status == "Normal"
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0


def test_battery_invalid_threshold_validation(client: TestClient) -> None:
    # Critical >= warning
    with pytest.raises(ValueError, match="0 <= critical < warning <= 100"):
        CpuAlertService._validate_battery_thresholds(20, 20)
    with pytest.raises(ValueError, match="0 <= critical < warning <= 100"):
        CpuAlertService._validate_battery_thresholds(10, 20)

    # Out of range (< 0 or > 100)
    with pytest.raises(ValueError, match="0 <= critical < warning <= 100"):
        CpuAlertService._validate_battery_thresholds(110, 10)
    with pytest.raises(ValueError, match="0 <= critical < warning <= 100"):
        CpuAlertService._validate_battery_thresholds(20, -5)

    # Non-numeric
    with pytest.raises(ValueError, match="must be numbers"):
        CpuAlertService._validate_battery_thresholds(True, 10)  # bool
    with pytest.raises(ValueError, match="must be numbers"):
        CpuAlertService._validate_battery_thresholds("abc", 10)

    # API PUT /api/alerts/thresholds with critical >= warning returns 422
    payload = {
        "cpu_warning_threshold_percent": 70,
        "cpu_critical_threshold_percent": 88,
        "ram_warning_threshold_percent": 75,
        "ram_critical_threshold_percent": 92,
        "disk_warning_threshold_percent": 60,
        "disk_critical_threshold_percent": 95,
        "temperature_warning_threshold_celsius": 70,
        "temperature_critical_threshold_celsius": 88,
        "battery_warning_threshold_percent": 15,
        "battery_critical_threshold_percent": 25,  # Invalid: critical > warning
    }
    assert client.put("/api/alerts/thresholds", json=payload).status_code == 422


def test_battery_threshold_persistence_across_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "battery_alerts.sqlite3"
    db_one = Database(db_file)
    db_one.initialize()
    repo_one = AlertRepository(db_one.session_factory)
    svc_one = CpuAlertService(repository=repo_one)

    # Update battery thresholds
    svc_one.update_thresholds(
        AlertThresholdsResponse(
            cpu_warning_threshold_percent=70,
            cpu_critical_threshold_percent=90,
            ram_warning_threshold_percent=70,
            ram_critical_threshold_percent=90,
            disk_warning_threshold_percent=70,
            disk_critical_threshold_percent=90,
            temperature_warning_threshold_celsius=70,
            temperature_critical_threshold_celsius=90,
            battery_warning_threshold_percent=25,
            battery_critical_threshold_percent=12,
        )
    )

    # Trigger a battery event
    bat = _make_battery(percentage=22.0, charging_state="discharging", power_plugged=False)
    svc_one.process_battery_sample(bat, _TIMESTAMP)
    assert svc_one.get_battery_status().status == "Warning"

    db_one.dispose()

    # Reopen database with fresh service
    db_two = Database(db_file)
    db_two.initialize()
    repo_two = AlertRepository(db_two.session_factory)
    svc_two = CpuAlertService(repository=repo_two)
    svc_two.restore_persisted_state()

    thresholds = svc_two.get_thresholds()
    assert thresholds.battery_warning_threshold_percent == 25.0
    assert thresholds.battery_critical_threshold_percent == 12.0
    assert svc_two.get_battery_status().status == "Warning"
    assert len(svc_two.get_battery_alerts().recent_events) == 1
    assert svc_two.get_battery_alerts().recent_events[0].resource == "battery"
    assert svc_two.get_battery_alerts().recent_events[0].percentage == 22.0

    db_two.dispose()


def test_battery_alert_history_persistence_and_management(client: TestClient) -> None:
    # Trigger a warning
    bat = _make_battery(percentage=18.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_battery_sample(bat, _TIMESTAMP)

    # Query history filtered by resource=battery
    history = client.get("/api/alerts/history?resource=battery").json()
    assert history["total"] == 1
    event = history["events"][0]
    assert event["resource"] == "battery"
    assert event["severity"] == "Warning"
    assert event["utilization_percent"] == 18.0
    assert event["configured_threshold_percent"] == 20.0
    assert event["acknowledged"] is False

    alert_id = event["id"]

    # Acknowledge the alert
    ack_res = client.patch(f"/api/alerts/{alert_id}/acknowledge")
    assert ack_res.status_code == 200
    assert ack_res.json()["acknowledged"] is True
    assert ack_res.json()["acknowledged_at"] is not None

    # Verify acknowledged status in recent events
    recent = cpu_alert_service.get_battery_alerts().recent_events
    assert recent[0].acknowledged is True

    # Delete alert
    del_res = client.delete(f"/api/alerts/{alert_id}")
    assert del_res.status_code == 204
    assert len(cpu_alert_service.get_battery_alerts().recent_events) == 0
    assert client.get("/api/alerts/history?resource=battery").json()["total"] == 0


def test_battery_in_api_endpoints(client: TestClient) -> None:
    # GET /api/alerts
    res = client.get("/api/alerts")
    assert res.status_code == 200
    data = res.json()
    assert "battery" in data
    assert data["battery"]["status"]["status"] == "Normal"
    assert isinstance(data["battery"]["recent_events"], list)

    # GET /api/alerts/status
    res_status = client.get("/api/alerts/status")
    assert res_status.status_code == 200
    status_data = res_status.json()
    assert "battery" in status_data
    assert status_data["battery"]["warning_threshold_percent"] == 20.0
    assert status_data["battery"]["critical_threshold_percent"] == 10.0

    # GET /api/alerts/thresholds
    res_thresh = client.get("/api/alerts/thresholds")
    assert res_thresh.status_code == 200
    thresh_data = res_thresh.json()
    assert thresh_data["battery_warning_threshold_percent"] == 20.0
    assert thresh_data["battery_critical_threshold_percent"] == 10.0


def test_process_snapshot_processes_all_resources_independently() -> None:
    bat = _make_battery(percentage=15.0, charging_state="discharging", power_plugged=False)
    cpu_alert_service.process_snapshot(
        cpu_usage_percent=95.0,
        ram_usage_percent=50.0,
        partitions=[],
        timestamp=_TIMESTAMP,
        temperature=None,
        battery=bat,
    )

    assert cpu_alert_service.get_status().status == "Critical"
    assert cpu_alert_service.get_ram_status().status == "Normal"
    assert cpu_alert_service.get_battery_status().status == "Warning"

    alerts = cpu_alert_service.get_alerts()
    assert len(alerts.recent_events) == 1  # CPU critical
    assert len(alerts.battery.recent_events) == 1  # Battery warning

