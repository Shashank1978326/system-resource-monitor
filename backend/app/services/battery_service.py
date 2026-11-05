"""Optional battery readings from psutil-supported hardware."""

import logging
import math
import platform
from numbers import Real

import psutil

from app.schemas.monitoring import BatteryResponse

logger = logging.getLogger(__name__)


def _read_battery():
    reader = getattr(psutil, "sensors_battery", None)
    if not callable(reader):
        raise NotImplementedError
    return reader()


def _percentage(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or not 0 <= numeric <= 100:
        return None
    return numeric


def _remaining_seconds(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _format_remaining_time(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds == 0:
        return "0 minutes"

    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        return "Less than 1 minute"
    return ", ".join(parts)


def _unavailable_response(
    availability: str, host_platform: str, message: str
) -> BatteryResponse:
    return BatteryResponse(
        availability=availability,
        platform=host_platform,
        percentage=None,
        charging_state="unknown",
        power_plugged=None,
        remaining_seconds=None,
        remaining_time=None,
        message=message,
    )


def get_battery_info() -> BatteryResponse:
    """Return actual battery readings without estimating missing values."""
    host_platform = platform.system()
    try:
        battery = _read_battery()
    except NotImplementedError:
        return _unavailable_response(
            "unsupported",
            host_platform,
            "Battery readings are not supported on this platform.",
        )
    except (OSError, psutil.Error) as exc:
        logger.info("Battery readings are unavailable: %s", type(exc).__name__)
        return _unavailable_response(
            "unavailable", host_platform, "Battery sensors could not be accessed."
        )

    if battery is None:
        return _unavailable_response(
            "unavailable", host_platform, "No battery was detected on this system."
        )

    try:
        percentage = _percentage(getattr(battery, "percent", None))
        power_plugged = getattr(battery, "power_plugged", None)
        if not isinstance(power_plugged, bool):
            power_plugged = None
        remaining_seconds = _remaining_seconds(getattr(battery, "secsleft", None))
    except (OSError, psutil.Error, AttributeError) as exc:
        logger.info("Battery readings could not be accessed: %s", type(exc).__name__)
        return _unavailable_response(
            "unavailable", host_platform, "Battery sensors could not be accessed."
        )

    if percentage == 100:
        charging_state = "not_charging"
        message = "Battery is fully charged."
    elif power_plugged is False:
        charging_state = "discharging"
        message = "Battery is discharging."
    elif power_plugged is True and percentage is not None:
        charging_state = "charging"
        message = "Battery is charging."
    else:
        charging_state = "unknown"
        message = "Battery detected; charging status is unknown."

    return BatteryResponse(
        availability="available",
        platform=host_platform,
        percentage=percentage,
        charging_state=charging_state,
        power_plugged=power_plugged,
        remaining_seconds=remaining_seconds,
        remaining_time=_format_remaining_time(remaining_seconds),
        message=message,
    )
