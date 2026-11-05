"""Temperature alerts reuse existing thresholds, transitions, and alert storage."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.database.alert_repository import AlertRepository
from app.database.connection import Database
from app.main import app
from app.schemas.monitoring import (
    AlertThresholdsResponse,
    TemperatureResponse,
    TemperatureSensorReadingResponse,
)
from app.services.alert_service import CpuAlertService

_TIMESTAMP = "2026-11-03T00:00:00+00:00"


@pytest.fixture
def temperature_alert_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database = Database(tmp_path / "temperature-alerts.sqlite3")
    database.initialize()
    repository = AlertRepository(database.session_factory)
    service = CpuAlertService(repository=repository)
    monkeypatch.setattr("app.api.routes.alerts.cpu_alert_service", service)
    monkeypatch.setattr("app.api.routes.alerts.alert_repository", repository)
    yield database, repository, service
    database.dispose()


def _reading(
    sensor_id: str,
    sensor_name: str,
    current: float | None,
    label: str | None = None,
) -> TemperatureSensorReadingResponse:
    return TemperatureSensorReadingResponse(
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        label=label,
        reading_index=0,
        current_celsius=current,
        high_celsius=None,
        critical_celsius=None,
        device=None,
    )


def _temperature(*readings, availability="available") -> TemperatureResponse:
    return TemperatureResponse(
        availability=availability,
        platform="TestOS",
        sensors=list(readings),
        message=None if availability == "available" else "No accessible sensors",
    )


def test_temperature_warning_critical_recovery_and_duplicate_prevention():
    service = CpuAlertService()
    for index in range(3):
        service.process_temperature_sample(
            _temperature(
                _reading("cpu:0", "coretemp", 82 + index, "Package"),
                _reading("gpu:0", "gpu", 92 + index, "GPU"),
            ),
            f"2026-11-03T00:00:0{index}+00:00",
        )
    service.process_temperature_sample(
        _temperature(
            _reading("cpu:0", "coretemp", 91, "Package"),
            _reading("gpu:0", "gpu", 87, "GPU"),
        ),
        "2026-11-03T00:00:03+00:00",
    )
    service.process_temperature_sample(
        _temperature(
            _reading("cpu:0", "coretemp", 70, "Package"),
            _reading("gpu:0", "gpu", 70, "GPU"),
        ),
        "2026-11-03T00:00:04+00:00",
    )

    events = service.get_temperature_alerts().recent_events
    assert [
        (event.sensor_id, event.previous_status, event.status) for event in events
    ] == [
        ("cpu:0", "Normal", "Warning"),
        ("gpu:0", "Normal", "Critical"),
        ("cpu:0", "Warning", "Critical"),
        ("gpu:0", "Critical", "Warning"),
        ("cpu:0", "Critical", "Normal"),
        ("gpu:0", "Warning", "Normal"),
    ]
    assert len(events) == 6
    assert events[0].current_celsius == 82
    assert events[0].configured_threshold_celsius == 80
    assert events[1].sensor_label == "GPU"


def test_null_unavailable_and_disappearing_sensors_do_not_recover():
    service = CpuAlertService()
    service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", 92)),
        _TIMESTAMP,
    )
    service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", None)),
        "2026-11-03T00:00:01+00:00",
    )
    service.process_temperature_sample(
        _temperature(availability="unsupported"),
        "2026-11-03T00:00:02+00:00",
    )
    service.process_temperature_sample(
        _temperature(_reading("other:0", "other", 50)),
        "2026-11-03T00:00:03+00:00",
    )

    assert [event.status for event in service.get_temperature_alerts().recent_events] == [
        "Critical"
    ]
    assert service.get_temperature_alerts().availability == "available"
    service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", 70)),
        "2026-11-03T00:00:04+00:00",
    )
    events = service.get_temperature_alerts().recent_events
    assert [(event.previous_status, event.status) for event in events] == [
        ("Normal", "Critical"),
        ("Critical", "Normal"),
    ]


@pytest.mark.parametrize("value", [math.nan, math.inf, True])
def test_invalid_temperature_values_are_not_used_for_alerts(value):
    reading = TemperatureSensorReadingResponse.model_construct(
        sensor_id="cpu:0",
        sensor_name="coretemp",
        label=None,
        reading_index=0,
        current_celsius=value,
        high_celsius=None,
        critical_celsius=None,
        device=None,
    )
    service = CpuAlertService()
    service.process_temperature_sample(_temperature(reading), _TIMESTAMP)
    assert service.get_temperature_alerts().sensors == []
    assert service.get_temperature_alerts().recent_events == []


def test_one_sensor_failure_does_not_interrupt_other_sensors():
    class BrokenReading:
        @property
        def sensor_id(self):
            raise RuntimeError("sensor unavailable")

    temperature = TemperatureResponse.model_construct(
        availability="available",
        platform="TestOS",
        sensors=[
            BrokenReading(),
            _reading("cpu:0", "coretemp", 91),
        ],
        message=None,
    )
    service = CpuAlertService()
    service.process_temperature_sample(temperature, _TIMESTAMP)
    events = service.get_temperature_alerts().recent_events
    assert len(events) == 1
    assert events[0].sensor_id == "cpu:0"


@pytest.mark.parametrize(
    ("warning", "critical"),
    [
        (-0.1, 90),
        (80, -1),
        (90, 90),
        (91, 90),
        (math.nan, 90),
        (80, math.inf),
        (True, 90),
    ],
)
def test_temperature_thresholds_reject_invalid_values(warning, critical):
    service = CpuAlertService()
    with pytest.raises((ValueError, TypeError)):
        service.update_thresholds(
            AlertThresholdsResponse(
                cpu_warning_threshold_percent=80,
                cpu_critical_threshold_percent=90,
                ram_warning_threshold_percent=80,
                ram_critical_threshold_percent=90,
                disk_warning_threshold_percent=80,
                disk_critical_threshold_percent=90,
                temperature_warning_threshold_celsius=warning,
                temperature_critical_threshold_celsius=critical,
            )
        )


def test_alert_api_thresholds_sensor_state_and_history(temperature_alert_store):
    _, repository, service = temperature_alert_store
    client = TestClient(app)
    response = client.get("/api/alerts/thresholds")
    assert response.status_code == 200
    assert response.json()["temperature_warning_threshold_celsius"] == 80
    assert response.json()["temperature_critical_threshold_celsius"] == 90

    updated = response.json() | {
        "temperature_warning_threshold_celsius": 75,
        "temperature_critical_threshold_celsius": 88,
    }
    saved = client.put("/api/alerts/thresholds", json=updated)
    assert saved.status_code == 200
    assert saved.json() == updated

    service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", 89, "Package")),
        _TIMESTAMP,
    )
    alerts = client.get("/api/alerts").json()["temperature"]
    assert alerts["availability"] == "available"
    assert alerts["sensors"][0]["sensor_id"] == "cpu:0"
    assert alerts["sensors"][0]["current_celsius"] == 89
    assert alerts["sensors"][0]["status"] == "Critical"
    assert alerts["recent_events"][0]["sensor_name"] == "coretemp"

    history = client.get("/api/alerts/history", params={"resource": "temperature"})
    assert history.status_code == 200
    event = history.json()["events"][0]
    assert event["resource"] == "temperature"
    assert event["temperature_celsius"] == 89
    assert event["configured_threshold_celsius"] == 88
    assert event["sensor_label"] == "Package"
    assert event["timestamp"] == _TIMESTAMP
    acknowledged = client.patch(f"/api/alerts/{event['id']}/acknowledge")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged"] is True
    assert repository.get_events(
        resource="temperature", severity="Critical", limit=20, offset=0
    )[1] == 1
    deleted = client.delete(f"/api/alerts/{event['id']}")
    assert deleted.status_code == 204
    assert service.get_temperature_alerts().recent_events == []


def test_unsupported_temperature_sensor_status_is_explicit(
    temperature_alert_store,
):
    _, _, service = temperature_alert_store
    service.process_temperature_sample(
        _temperature(availability="unsupported"),
        _TIMESTAMP,
    )
    result = TestClient(app).get("/api/alerts").json()["temperature"]
    assert result["availability"] == "unsupported"
    assert result["sensors"] == []
    assert result["recent_events"] == []
    assert "No accessible sensors" in result["message"]


def test_temperature_threshold_api_rejects_negative_equal_and_nonfinite(
    temperature_alert_store,
):
    client = TestClient(app)
    original = client.get("/api/alerts/thresholds").json()
    assert client.put(
        "/api/alerts/thresholds",
        json={
            **original,
            "temperature_warning_threshold_celsius": -1,
        },
    ).status_code == 422
    assert client.put(
        "/api/alerts/thresholds",
        json={
            **original,
            "temperature_warning_threshold_celsius": 90,
            "temperature_critical_threshold_celsius": 90,
        },
    ).status_code == 422
    assert client.put(
        "/api/alerts/thresholds",
        json={
            **original,
            "temperature_warning_threshold_celsius": "NaN",
        },
    ).status_code == 422


def test_temperature_thresholds_and_events_survive_restart(tmp_path: Path):
    path = tmp_path / "restart-temperature-alerts.sqlite3"
    first_database = Database(path)
    first_database.initialize()
    first_repository = AlertRepository(first_database.session_factory)
    first_service = CpuAlertService(repository=first_repository)
    first_service.update_thresholds(
        AlertThresholdsResponse(
            cpu_warning_threshold_percent=80,
            cpu_critical_threshold_percent=90,
            ram_warning_threshold_percent=80,
            ram_critical_threshold_percent=90,
            disk_warning_threshold_percent=80,
            disk_critical_threshold_percent=90,
            temperature_warning_threshold_celsius=72,
            temperature_critical_threshold_celsius=87,
        )
    )
    first_service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", 73, "Package")),
        _TIMESTAMP,
    )
    first_database.dispose()

    second_database = Database(path)
    second_database.initialize()
    second_repository = AlertRepository(second_database.session_factory)
    second_service = CpuAlertService(repository=second_repository)
    second_service.restore_persisted_state()
    assert second_service.get_thresholds().temperature_warning_threshold_celsius == 72
    assert second_service.get_temperature_alerts().recent_events[0].sensor_id == "cpu:0"
    second_service.process_temperature_sample(
        _temperature(_reading("cpu:0", "coretemp", 75, "Package")),
        "2026-11-03T00:00:01+00:00",
    )
    assert second_repository.get_events(
        resource="temperature", severity="Warning", limit=20, offset=0
    )[1] == 1
    second_database.dispose()


def test_additive_alert_migration_preserves_existing_events_and_thresholds(
    tmp_path: Path,
):
    database = Database(tmp_path / "legacy-alerts.sqlite3")
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE alert_threshold_settings (
                id INTEGER PRIMARY KEY,
                cpu_warning_percent FLOAT NOT NULL,
                cpu_critical_percent FLOAT NOT NULL,
                ram_warning_percent FLOAT NOT NULL,
                ram_critical_percent FLOAT NOT NULL,
                disk_warning_percent FLOAT NOT NULL,
                disk_critical_percent FLOAT NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO alert_threshold_settings
            VALUES (1, 80, 90, 80, 90, 80, 90)
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE alert_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                resource VARCHAR(16) NOT NULL,
                severity VARCHAR(16) NOT NULL,
                previous_severity VARCHAR(16),
                message VARCHAR(500) NOT NULL,
                utilization_percent FLOAT NOT NULL,
                configured_threshold_percent FLOAT NOT NULL,
                device VARCHAR(512),
                mountpoint VARCHAR(512),
                total_bytes BIGINT,
                used_bytes BIGINT,
                free_bytes BIGINT,
                timestamp DATETIME NOT NULL,
                acknowledged BOOLEAN NOT NULL DEFAULT 0,
                acknowledged_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO alert_events
            (id, resource, severity, previous_severity, message,
             utilization_percent, configured_threshold_percent, timestamp)
            VALUES (7, 'cpu', 'Warning', 'Normal', 'Existing CPU alert',
                    85, 80, '2026-11-03 00:00:00')
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE alert_current_states (
                state_key VARCHAR(600) PRIMARY KEY,
                resource VARCHAR(16) NOT NULL,
                severity VARCHAR(16) NOT NULL,
                utilization_percent FLOAT NOT NULL,
                device VARCHAR(512),
                mountpoint VARCHAR(512),
                total_bytes BIGINT,
                used_bytes BIGINT,
                free_bytes BIGINT,
                timestamp DATETIME NOT NULL
            )
            """
        )

    database.initialize()
    columns = {
        table: {column["name"] for column in inspect(database.engine).get_columns(table)}
        for table in (
            "alert_events",
            "alert_current_states",
            "alert_threshold_settings",
        )
    }
    assert {
        "temperature_warning_celsius",
        "temperature_critical_celsius",
    } <= columns["alert_threshold_settings"]
    assert {
        "sensor_id",
        "sensor_name",
        "sensor_label",
        "temperature_celsius",
        "configured_threshold_celsius",
    } <= columns["alert_events"]
    assert {"sensor_id", "sensor_name", "sensor_label"} <= columns[
        "alert_current_states"
    ]

    repository = AlertRepository(database.session_factory)
    events, total = repository.get_events(
        resource="cpu", severity="Warning", limit=20, offset=0
    )
    thresholds = repository.get_thresholds()
    assert total == 1
    assert events[0].id == 7
    assert events[0].message == "Existing CPU alert"
    assert thresholds is not None
    assert thresholds.temperature_warning_celsius == 80
    assert thresholds.temperature_critical_celsius == 90
    database.dispose()
