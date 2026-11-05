"""Tests for optional battery status detection."""

from collections import namedtuple
from unittest.mock import patch

import psutil
from fastapi.testclient import TestClient

from app.main import app
from app.services import battery_service

BatteryReading = namedtuple("BatteryReading", ("percent", "secsleft", "power_plugged"))


def read_battery(reading):
    return patch(
        "app.services.battery_service._read_battery",
        return_value=reading,
    )


def test_available_battery_reports_real_readings_and_time() -> None:
    with read_battery(BatteryReading(45.5, 5400, True)):
        response = battery_service.get_battery_info()

    assert response.availability == "available"
    assert response.percentage == 45.5
    assert response.charging_state == "charging"
    assert response.power_plugged is True
    assert response.remaining_seconds == 5400
    assert response.remaining_time == "1 hour, 30 minutes"


def test_missing_battery_returns_valid_unavailable_result() -> None:
    with read_battery(None):
        response = battery_service.get_battery_info()

    assert response.availability == "unavailable"
    assert response.percentage is None
    assert response.charging_state == "unknown"
    assert response.power_plugged is None
    assert response.remaining_seconds is None
    assert response.remaining_time is None
    assert "No battery" in response.message


def test_unplugged_battery_is_discharging() -> None:
    with read_battery(BatteryReading(67, 3600, False)):
        response = battery_service.get_battery_info()

    assert response.charging_state == "discharging"
    assert response.power_plugged is False


def test_fully_charged_battery_is_not_reported_as_charging() -> None:
    with read_battery(BatteryReading(100, psutil.POWER_TIME_UNLIMITED, True)):
        response = battery_service.get_battery_info()

    assert response.availability == "available"
    assert response.percentage == 100
    assert response.charging_state == "not_charging"
    assert response.power_plugged is True
    assert response.remaining_seconds is None
    assert response.remaining_time is None
    assert response.message == "Battery is fully charged."


def test_zero_battery_percentage_is_preserved() -> None:
    with read_battery(BatteryReading(0, 0, False)):
        response = battery_service.get_battery_info()

    assert response.percentage == 0
    assert response.remaining_seconds == 0
    assert response.remaining_time == "0 minutes"


def test_unknown_remaining_time_is_null() -> None:
    with read_battery(BatteryReading(35, psutil.POWER_TIME_UNKNOWN, False)):
        response = battery_service.get_battery_info()

    assert response.remaining_seconds is None
    assert response.remaining_time is None


def test_plugged_battery_with_unknown_percentage_has_unknown_charge_state() -> None:
    with read_battery(BatteryReading(None, psutil.POWER_TIME_UNKNOWN, True)):
        response = battery_service.get_battery_info()

    assert response.power_plugged is True
    assert response.percentage is None
    assert response.charging_state == "unknown"


def test_unavailable_power_status_is_not_treated_as_charging() -> None:
    with read_battery(BatteryReading(50, psutil.POWER_TIME_UNKNOWN, None)):
        response = battery_service.get_battery_info()

    assert response.power_plugged is None
    assert response.charging_state == "unknown"


def test_unsupported_battery_readings_return_structured_response() -> None:
    with (
        patch(
            "app.services.battery_service.platform.system",
            return_value="UnsupportedOS",
        ),
        patch(
            "app.services.battery_service._read_battery",
            side_effect=NotImplementedError,
        ),
    ):
        response = battery_service.get_battery_info()

    assert response.availability == "unsupported"
    assert response.platform == "UnsupportedOS"
    assert response.percentage is None
    assert response.charging_state == "unknown"
    assert "not supported" in response.message


def test_permission_error_returns_structured_unavailable_response() -> None:
    with patch(
        "app.services.battery_service._read_battery",
        side_effect=PermissionError,
    ):
        response = battery_service.get_battery_info()

    assert response.availability == "unavailable"
    assert response.percentage is None
    assert response.power_plugged is None
    assert response.message == "Battery sensors could not be accessed."


def test_api_returns_expected_battery_response_shape() -> None:
    with (
        read_battery(BatteryReading(75, 7200, False)),
        TestClient(app) as client,
    ):
        response = client.get("/api/battery")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "availability",
        "platform",
        "percentage",
        "charging_state",
        "power_plugged",
        "remaining_seconds",
        "remaining_time",
        "message",
    }
    assert body["availability"] == "available"
    assert body["percentage"] == 75
    assert body["charging_state"] == "discharging"
    assert body["power_plugged"] is False
    assert body["remaining_seconds"] == 7200
    assert body["remaining_time"] == "2 hours"


def test_invalid_battery_percentages_are_null() -> None:
    for value in (float("nan"), float("inf"), -1, 101, True):
        with read_battery(BatteryReading(value, psutil.POWER_TIME_UNKNOWN, False)):
            response = battery_service.get_battery_info()
        assert response.percentage is None
