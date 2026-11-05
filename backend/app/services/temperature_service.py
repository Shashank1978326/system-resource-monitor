"""Optional hardware temperature readings from psutil-supported sensors."""

import logging
import math
import platform
from collections.abc import Mapping

import psutil

from app.schemas.monitoring import (
    TemperatureResponse,
    TemperatureSensorReadingResponse,
)

logger = logging.getLogger(__name__)


def _read_sensor_temperatures():
    reader = getattr(psutil, "sensors_temperatures", None)
    if reader is None:
        raise NotImplementedError
    return reader()


def _temperature_value(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def get_temperature_info() -> TemperatureResponse:
    """Read available temperatures, without estimating or filling missing values."""
    host_platform = platform.system()
    try:
        sensor_groups = _read_sensor_temperatures()
    except NotImplementedError:
        return TemperatureResponse(
            availability="unsupported",
            platform=host_platform,
            sensors=[],
            message="Temperature sensor readings are not supported on this platform.",
        )
    except (OSError, psutil.Error) as exc:
        logger.info("Temperature sensor readings are unavailable: %s", type(exc).__name__)
        return TemperatureResponse(
            availability="unavailable",
            platform=host_platform,
            sensors=[],
            message="Temperature sensors could not be accessed.",
        )

    sensors: list[TemperatureSensorReadingResponse] = []
    if isinstance(sensor_groups, Mapping):
        for sensor_name, readings in sensor_groups.items():
            if not isinstance(sensor_name, str) or not sensor_name:
                continue
            if not isinstance(readings, (list, tuple)):
                continue
            for reading_index, reading in enumerate(readings):
                try:
                    label = getattr(reading, "label", None)
                    if not isinstance(label, str) or not label.strip():
                        label = None
                    sensors.append(
                        TemperatureSensorReadingResponse(
                            sensor_name=sensor_name,
                            label=label.strip() if label else None,
                            sensor_id=f"{sensor_name}:{reading_index}",
                            reading_index=reading_index,
                            current_celsius=_temperature_value(
                                getattr(reading, "current", None)
                            ),
                            high_celsius=_temperature_value(
                                getattr(reading, "high", None)
                            ),
                            critical_celsius=_temperature_value(
                                getattr(reading, "critical", None)
                            ),
                            # psutil exposes a sensor group, not a dependable device model.
                            device=None,
                        )
                    )
                except (OSError, psutil.Error, AttributeError) as exc:
                    logger.info(
                        "A temperature reading could not be accessed: %s",
                        type(exc).__name__,
                    )

    if sensors:
        return TemperatureResponse(
            availability="available",
            platform=host_platform,
            sensors=sensors,
            message=None,
        )

    if host_platform not in {"Linux", "FreeBSD"}:
        return TemperatureResponse(
            availability="unsupported",
            platform=host_platform,
            sensors=[],
            message=(
                "This platform does not expose usable temperature readings through "
                "psutil. No estimated readings are provided."
            ),
        )

    return TemperatureResponse(
        availability="unavailable",
        platform=host_platform,
        sensors=[],
        message="No accessible hardware temperature sensors were found.",
    )
