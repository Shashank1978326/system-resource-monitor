"""Tests for optional temperature sensor detection."""

import platform
from collections import namedtuple
from unittest.mock import patch

import psutil
from fastapi.testclient import TestClient

from app.main import app
from app.services import temperature_service

SensorReading = namedtuple(
    "SensorReading", ("label", "current", "high", "critical")
)


def test_temperature_service_returns_multiple_groups_and_readings() -> None:
    with patch(
        "app.services.temperature_service._read_sensor_temperatures",
        return_value={
            "coretemp": [
                SensorReading("Package id 0", 52.5, 85.0, 100.0),
                SensorReading("Core 0", 47.0, None, None),
            ],
            "nvme": [SensorReading("", 39.0, 70.0, None)],
        },
    ):
        response = temperature_service.get_temperature_info()

    assert response.availability == "available"
    assert response.platform == platform.system()
    assert len(response.sensors) == 3
    assert response.sensors[0].sensor_name == "coretemp"
    assert response.sensors[0].label == "Package id 0"
    assert response.sensors[0].current_celsius == 52.5
    assert response.sensors[0].high_celsius == 85.0
    assert response.sensors[0].critical_celsius == 100.0
    assert response.sensors[1].label == "Core 0"
    assert response.sensors[1].high_celsius is None
    assert response.sensors[1].critical_celsius is None
    assert response.sensors[2].label is None
    assert response.sensors[2].device is None


def test_zero_temperature_is_preserved_and_missing_current_is_null() -> None:
    with patch(
        "app.services.temperature_service._read_sensor_temperatures",
        return_value={
            "test": [
                SensorReading("zero", 0.0, None, None),
                SensorReading("missing", None, None, None),
            ]
        },
    ):
        response = temperature_service.get_temperature_info()

    assert response.sensors[0].current_celsius == 0.0
    assert response.sensors[1].current_celsius is None


def test_empty_linux_sensor_results_are_unavailable() -> None:
    with (
        patch("app.services.temperature_service.platform.system", return_value="Linux"),
        patch(
            "app.services.temperature_service._read_sensor_temperatures",
            return_value={},
        ),
    ):
        response = temperature_service.get_temperature_info()

    assert response.availability == "unavailable"
    assert response.sensors == []
    assert response.message


def test_permission_error_returns_valid_unavailable_response() -> None:
    with patch(
        "app.services.temperature_service._read_sensor_temperatures",
        side_effect=PermissionError,
    ):
        response = temperature_service.get_temperature_info()

    assert response.availability == "unavailable"
    assert response.sensors == []
    assert response.message == "Temperature sensors could not be accessed."


def test_unsupported_platform_returns_explicit_status() -> None:
    with (
        patch("app.services.temperature_service.platform.system", return_value="Windows"),
        patch(
            "app.services.temperature_service._read_sensor_temperatures",
            side_effect=NotImplementedError,
        ),
    ):
        response = temperature_service.get_temperature_info()

    assert response.availability == "unsupported"
    assert response.platform == "Windows"
    assert response.sensors == []
    assert response.message


def test_windows_without_usable_psutil_readings_is_not_estimated() -> None:
    with (
        patch("app.services.temperature_service.platform.system", return_value="Windows"),
        patch(
            "app.services.temperature_service._read_sensor_temperatures",
            return_value={},
        ),
    ):
        response = temperature_service.get_temperature_info()

    assert response.availability == "unsupported"
    assert response.sensors == []
    assert "No estimated readings" in response.message


def test_temperature_api_response_has_expected_shape() -> None:
    with (
        patch(
            "app.services.temperature_service._read_sensor_temperatures",
            return_value={
                "coretemp": [SensorReading("Package", 48.5, 80.0, 95.0)]
            },
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/temperature")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"availability", "platform", "sensors", "message"}
    assert body["availability"] == "available"
    assert body["sensors"] == [
        {
            "sensor_name": "coretemp",
            "label": "Package",
            "sensor_id": "coretemp:0",
            "reading_index": 0,
            "current_celsius": 48.5,
            "high_celsius": 80.0,
            "critical_celsius": 95.0,
            "device": None,
        }
    ]


def test_non_finite_sensor_values_are_null() -> None:
    with patch(
        "app.services.temperature_service._read_sensor_temperatures",
        return_value={"sensor": [SensorReading("test", float("nan"), float("inf"), -float("inf"))]},
    ):
        response = temperature_service.get_temperature_info()

    assert response.sensors[0].current_celsius is None
    assert response.sensors[0].high_celsius is None
    assert response.sensors[0].critical_celsius is None


def test_boolean_sensor_values_are_unavailable() -> None:
    with patch(
        "app.services.temperature_service._read_sensor_temperatures",
        return_value={"sensor": [SensorReading("test", True, False, None)]},
    ):
        response = temperature_service.get_temperature_info()

    assert response.sensors[0].current_celsius is None
    assert response.sensors[0].high_celsius is None
    assert response.sensors[0].critical_celsius is None
