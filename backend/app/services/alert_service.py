"""In-memory resource alert state derived from monitoring snapshots."""

import math
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Literal

from app.core.config import settings
from app.database.alert_repository import AlertRepository, AlertStorageError
from app.database.connection import database
from app.database.models import AlertEvent
from app.schemas.monitoring import (
    AlertThresholdsResponse,
    BatteryAlertEventResponse,
    BatteryAlertStatusResponse,
    BatteryAlertsResponse,
    BatteryResponse,
    CpuAlertEventResponse,
    CpuAlertStatusResponse,
    CpuAlertsResponse,
    DiskAlertEventResponse,
    DiskAlertStatusResponse,
    DiskAlertsResourceResponse,
    DiskPartitionAlertStatusResponse,
    DiskPartitionResponse,
    RamAlertEventResponse,
    RamAlertsResourceResponse,
    ResourceAlertStatusResponse,
    TemperatureAlertEventResponse,
    TemperatureAlertsResponse,
    TemperatureResponse,
    TemperatureSensorAlertStatusResponse,
)

CPU_WARNING_THRESHOLD_PERCENT = settings.cpu_alert_warning_threshold_percent
CPU_CRITICAL_THRESHOLD_PERCENT = settings.cpu_alert_critical_threshold_percent
RAM_WARNING_THRESHOLD_PERCENT = settings.ram_alert_warning_threshold_percent
RAM_CRITICAL_THRESHOLD_PERCENT = settings.ram_alert_critical_threshold_percent
DISK_WARNING_THRESHOLD_PERCENT = settings.disk_alert_warning_threshold_percent
DISK_CRITICAL_THRESHOLD_PERCENT = settings.disk_alert_critical_threshold_percent
TEMPERATURE_WARNING_THRESHOLD_CELSIUS = (
    settings.temperature_alert_warning_threshold_celsius
)
TEMPERATURE_CRITICAL_THRESHOLD_CELSIUS = (
    settings.temperature_alert_critical_threshold_celsius
)
BATTERY_WARNING_THRESHOLD_PERCENT = settings.battery_alert_warning_threshold_percent
BATTERY_CRITICAL_THRESHOLD_PERCENT = settings.battery_alert_critical_threshold_percent
_RECENT_EVENT_LIMIT = 50
_STATUS_ORDER = {"Normal": 0, "Warning": 1, "Critical": 2}
_logger = logging.getLogger(__name__)


def _normalize_severity(value: str | None) -> Literal["Normal", "Warning", "Critical"]:
    if not value:
        return "Normal"
    cleaned = str(value).strip().capitalize()
    if cleaned in ("Normal", "Warning", "Critical"):
        return cleaned  # type: ignore[return-value]
    return "Normal"


def _validated_usage(value: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        usage = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(usage) or not 0 <= usage <= 100:
        return None
    return usage


def _validated_temperature(value: float | None) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        temperature = float(value)
    except (OverflowError, ValueError):
        return None
    return temperature if math.isfinite(temperature) else None


def _classify(
    usage: float,
    warning_threshold: float,
    critical_threshold: float,
) -> str:
    if usage >= critical_threshold:
        return "Critical"
    if usage >= warning_threshold:
        return "Warning"
    return "Normal"


def _transition_message(resource: str, previous_status: str, status: str, threshold: float) -> str:
    label = "RAM" if resource == "ram" else resource.upper()
    if resource == "cpu":
        if status == "Critical":
            return "CPU usage has reached a critical level."
        if status == "Warning":
            return (
                f"CPU usage has reached the "
                f"{threshold:g}% warning threshold."
            )
        return "CPU usage has returned to normal."
    if status == "Critical":
        return f"{label} usage has reached a critical level."
    if status == "Warning":
        return f"{label} usage has reached the {threshold:g}% warning threshold."
    return f"{label} usage has returned to normal from {previous_status}."


class CpuAlertService:
    """Track CPU, RAM, and per-partition disk transitions from one collector."""

    def __init__(
        self,
        warning_threshold_percent: float = CPU_WARNING_THRESHOLD_PERCENT,
        critical_threshold_percent: float = CPU_CRITICAL_THRESHOLD_PERCENT,
        ram_warning_threshold_percent: float = RAM_WARNING_THRESHOLD_PERCENT,
        ram_critical_threshold_percent: float = RAM_CRITICAL_THRESHOLD_PERCENT,
        disk_warning_threshold_percent: float = DISK_WARNING_THRESHOLD_PERCENT,
        disk_critical_threshold_percent: float = DISK_CRITICAL_THRESHOLD_PERCENT,
        temperature_warning_threshold_celsius: float = (
            TEMPERATURE_WARNING_THRESHOLD_CELSIUS
        ),
        temperature_critical_threshold_celsius: float = (
            TEMPERATURE_CRITICAL_THRESHOLD_CELSIUS
        ),
        battery_warning_threshold_percent: float = (
            BATTERY_WARNING_THRESHOLD_PERCENT
        ),
        battery_critical_threshold_percent: float = (
            BATTERY_CRITICAL_THRESHOLD_PERCENT
        ),
        repository: AlertRepository | None = None,
    ) -> None:
        warning_threshold_percent, critical_threshold_percent = self._validate_thresholds(
            "CPU", warning_threshold_percent, critical_threshold_percent
        )
        ram_warning_threshold_percent, ram_critical_threshold_percent = self._validate_thresholds(
            "RAM", ram_warning_threshold_percent, ram_critical_threshold_percent
        )
        disk_warning_threshold_percent, disk_critical_threshold_percent = self._validate_thresholds(
            "Disk", disk_warning_threshold_percent, disk_critical_threshold_percent
        )
        temperature_warning_threshold_celsius, temperature_critical_threshold_celsius = (
            self._validate_temperature_thresholds(
                temperature_warning_threshold_celsius,
                temperature_critical_threshold_celsius,
            )
        )
        (
            battery_warning_threshold_percent,
            battery_critical_threshold_percent,
        ) = self._validate_battery_thresholds(
            battery_warning_threshold_percent,
            battery_critical_threshold_percent,
        )
        self.warning_threshold_percent = warning_threshold_percent
        self.critical_threshold_percent = critical_threshold_percent
        self.ram_warning_threshold_percent = ram_warning_threshold_percent
        self.ram_critical_threshold_percent = ram_critical_threshold_percent
        self.disk_warning_threshold_percent = disk_warning_threshold_percent
        self.disk_critical_threshold_percent = disk_critical_threshold_percent
        self.temperature_warning_threshold_celsius = (
            temperature_warning_threshold_celsius
        )
        self.temperature_critical_threshold_celsius = (
            temperature_critical_threshold_celsius
        )
        self.battery_warning_threshold_percent = (
            battery_warning_threshold_percent
        )
        self.battery_critical_threshold_percent = (
            battery_critical_threshold_percent
        )
        self._repository = repository
        self._lock = threading.RLock()
        self._status = self._initial_cpu_status()
        self._ram_status = self._initial_ram_status()
        self._disk_partitions: dict[str, DiskPartitionAlertStatusResponse] = {}
        self._disk_timestamp: str | None = None
        self._cpu_events: deque[CpuAlertEventResponse] = deque(maxlen=_RECENT_EVENT_LIMIT)
        self._ram_events: deque[RamAlertEventResponse] = deque(maxlen=_RECENT_EVENT_LIMIT)
        self._disk_events: deque[DiskAlertEventResponse] = deque(maxlen=_RECENT_EVENT_LIMIT)
        self._temperature_last_severity: dict[str, str] = {}
        self._temperature_latest_sensors: dict[
            str, TemperatureSensorAlertStatusResponse
        ] = {}
        self._temperature_events: deque[TemperatureAlertEventResponse] = deque(
            maxlen=_RECENT_EVENT_LIMIT
        )
        self._temperature_availability = "unavailable"
        self._temperature_platform = "unknown"
        self._temperature_message = "Temperature sensors have not been sampled."
        self._battery_last_severity: str = "Normal"
        self._battery_status = self._initial_battery_status()
        self._battery_events: deque[BatteryAlertEventResponse] = deque(
            maxlen=_RECENT_EVENT_LIMIT
        )

    @staticmethod
    def _validate_temperature_thresholds(
        warning_threshold: float, critical_threshold: float
    ) -> tuple[float, float]:
        if isinstance(warning_threshold, bool) or isinstance(critical_threshold, bool):
            raise ValueError("Temperature alert thresholds must be numbers")
        try:
            warning_threshold = float(warning_threshold)
            critical_threshold = float(critical_threshold)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("Temperature alert thresholds must be numbers") from exc
        if not (
            math.isfinite(warning_threshold)
            and math.isfinite(critical_threshold)
            and 0 <= warning_threshold < critical_threshold
        ):
            raise ValueError(
                "Temperature alert thresholds must be finite and non-negative, "
                "with warning lower than critical"
            )
        return warning_threshold, critical_threshold

    @staticmethod
    def _validate_battery_thresholds(
        warning_threshold: float, critical_threshold: float
    ) -> tuple[float, float]:
        if isinstance(warning_threshold, bool) or isinstance(critical_threshold, bool):
            raise ValueError("Battery alert thresholds must be numbers")
        try:
            warning_threshold = float(warning_threshold)
            critical_threshold = float(critical_threshold)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("Battery alert thresholds must be numbers") from exc
        if not (
            math.isfinite(warning_threshold)
            and math.isfinite(critical_threshold)
            and 0 <= critical_threshold < warning_threshold <= 100
        ):
            raise ValueError(
                "Battery alert thresholds must satisfy 0 <= critical < warning <= 100"
            )
        return warning_threshold, critical_threshold

    @staticmethod
    def _validate_thresholds(
        resource: str, warning_threshold: float, critical_threshold: float
    ) -> tuple[float, float]:
        if isinstance(warning_threshold, bool) or isinstance(critical_threshold, bool):
            raise ValueError(f"{resource} alert thresholds must be numbers")
        try:
            warning_threshold = float(warning_threshold)
            critical_threshold = float(critical_threshold)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError(f"{resource} alert thresholds must be numbers") from exc
        if not (
            math.isfinite(warning_threshold)
            and math.isfinite(critical_threshold)
            and 1 <= warning_threshold < critical_threshold <= 100
        ):
            raise ValueError(
                f"{resource} alert thresholds must satisfy "
                "1 <= warning < critical <= 100"
            )
        return warning_threshold, critical_threshold

    def _initial_cpu_status(self) -> CpuAlertStatusResponse:
        return CpuAlertStatusResponse(
            status="Normal",
            severity="Normal",
            cpu_usage_percent=None,
            warning_threshold_percent=self.warning_threshold_percent,
            critical_threshold_percent=self.critical_threshold_percent,
            timestamp=None,
        )

    def _initial_ram_status(self) -> ResourceAlertStatusResponse:
        return ResourceAlertStatusResponse(
            status="Normal",
            severity="Normal",
            usage_percent=None,
            warning_threshold_percent=self.ram_warning_threshold_percent,
            critical_threshold_percent=self.ram_critical_threshold_percent,
            timestamp=None,
        )

    def _initial_battery_status(self) -> BatteryAlertStatusResponse:
        return BatteryAlertStatusResponse(
            availability="unavailable",
            platform="unknown",
            message="Battery has not been sampled.",
            percentage=None,
            charging_state=None,
            power_plugged=None,
            status="Normal",
            severity="Normal",
            warning_threshold_percent=self.battery_warning_threshold_percent,
            critical_threshold_percent=self.battery_critical_threshold_percent,
            timestamp=None,
        )

    def process_snapshot(
        self,
        cpu_usage_percent: float | None,
        ram_usage_percent: float | None,
        partitions: list[DiskPartitionResponse],
        timestamp: str,
        temperature: TemperatureResponse | None = None,
        battery: BatteryResponse | None = None,
    ) -> None:
        """Apply all resource readings together so API clients see one cycle."""
        with self._lock:
            self._retry_pending_events()
            self.process_sample(cpu_usage_percent, timestamp)
            self.process_ram_sample(ram_usage_percent, timestamp)
            self.process_disk_sample(partitions, timestamp)
            if temperature is not None:
                self.process_temperature_sample(temperature, timestamp)
            if battery is not None:
                self.process_battery_sample(battery, timestamp)

    def process_battery_sample(
        self, battery: BatteryResponse | None, timestamp: str
    ) -> None:
        """Track battery alert transitions from live battery measurements."""
        with self._lock:
            if battery is None or battery.availability != "available" or battery.percentage is None:
                self._battery_status = BatteryAlertStatusResponse(
                    availability=battery.availability if battery else "unavailable",
                    platform=battery.platform if battery else "unknown",
                    message=battery.message if battery else "Battery status unavailable",
                    percentage=None,
                    charging_state=battery.charging_state if battery else None,
                    power_plugged=battery.power_plugged if battery else None,
                    status=self._battery_last_severity,
                    severity=self._battery_last_severity,
                    warning_threshold_percent=self.battery_warning_threshold_percent,
                    critical_threshold_percent=self.battery_critical_threshold_percent,
                    timestamp=timestamp,
                )
                return

            usage = _validated_usage(battery.percentage)
            if usage is None:
                self._battery_status = BatteryAlertStatusResponse(
                    availability=battery.availability,
                    platform=battery.platform,
                    message=battery.message,
                    percentage=None,
                    charging_state=battery.charging_state,
                    power_plugged=battery.power_plugged,
                    status=self._battery_last_severity,
                    severity=self._battery_last_severity,
                    warning_threshold_percent=self.battery_warning_threshold_percent,
                    critical_threshold_percent=self.battery_critical_threshold_percent,
                    timestamp=timestamp,
                )
                return

            is_plugged_or_charging = (
                battery.power_plugged is True
                or battery.charging_state == "charging"
            )

            if is_plugged_or_charging:
                target_severity = "Normal"
            else:
                if usage <= self.battery_critical_threshold_percent:
                    target_severity = "Critical"
                elif usage <= self.battery_warning_threshold_percent:
                    target_severity = "Warning"
                else:
                    target_severity = "Normal"

            previous_status = self._battery_last_severity
            self._battery_status = BatteryAlertStatusResponse(
                availability=battery.availability,
                platform=battery.platform,
                message=battery.message,
                percentage=usage,
                charging_state=battery.charging_state,
                power_plugged=battery.power_plugged,
                status=target_severity,
                severity=target_severity,
                warning_threshold_percent=self.battery_warning_threshold_percent,
                critical_threshold_percent=self.battery_critical_threshold_percent,
                timestamp=timestamp,
            )

            if target_severity == previous_status:
                return

            self._battery_last_severity = target_severity
            threshold = (
                self.battery_critical_threshold_percent
                if target_severity == "Critical"
                else self.battery_warning_threshold_percent
            )

            if target_severity == "Critical":
                message = (
                    f"Battery level is critical at {usage:g}% "
                    f"(critical threshold {self.battery_critical_threshold_percent:g}%)."
                )
            elif target_severity == "Warning":
                message = (
                    f"Battery level is low at {usage:g}% "
                    f"(warning threshold {self.battery_warning_threshold_percent:g}%)."
                )
            else:
                if is_plugged_or_charging:
                    message = (
                        f"Battery alerts recovered: external power connected "
                        f"(battery at {usage:g}%)."
                    )
                else:
                    message = (
                        f"Battery level returned to normal at {usage:g}% "
                        f"from {previous_status}."
                    )

            event = BatteryAlertEventResponse(
                previous_status=previous_status,
                status=target_severity,
                severity=target_severity,
                percentage=usage,
                configured_threshold_percent=threshold,
                warning_threshold_percent=self.battery_warning_threshold_percent,
                critical_threshold_percent=self.battery_critical_threshold_percent,
                timestamp=timestamp,
                message=message,
            )
            self._battery_events.append(event)
            self._persist_memory_event(
                event,
                "battery",
                usage,
                threshold,
            )

    def process_temperature_sample(
        self, temperature: TemperatureResponse, timestamp: str
    ) -> None:
        """Track independent temperature transitions from actual sensor values."""
        with self._lock:
            self._temperature_availability = temperature.availability
            self._temperature_platform = temperature.platform
            self._temperature_message = temperature.message
            self._temperature_latest_sensors = {}
            if temperature.availability != "available":
                return

            for sensor in temperature.sensors:
                try:
                    sensor_id = sensor.sensor_id
                    sensor_name = sensor.sensor_name
                    value = _validated_temperature(sensor.current_celsius)
                    if not sensor_id or not sensor_name or value is None:
                        continue

                    severity = _classify(
                        value,
                        self.temperature_warning_threshold_celsius,
                        self.temperature_critical_threshold_celsius,
                    )
                    previous = self._temperature_last_severity.get(
                        sensor_id, "Normal"
                    )
                    status = TemperatureSensorAlertStatusResponse(
                        sensor_id=sensor_id,
                        sensor_name=sensor_name,
                        label=sensor.label,
                        current_celsius=value,
                        status=severity,
                        severity=severity,
                        warning_threshold_celsius=(
                            self.temperature_warning_threshold_celsius
                        ),
                        critical_threshold_celsius=(
                            self.temperature_critical_threshold_celsius
                        ),
                        timestamp=timestamp,
                    )
                    self._temperature_latest_sensors[sensor_id] = status
                    self._temperature_last_severity[sensor_id] = severity
                    if severity == previous:
                        continue

                    threshold = (
                        self.temperature_critical_threshold_celsius
                        if severity == "Critical"
                        else self.temperature_warning_threshold_celsius
                    )
                    if severity == "Normal":
                        message = (
                            f"Temperature for {sensor_name}"
                            f"{f' ({sensor.label})' if sensor.label else ''} "
                            f"returned to normal at {value:g} °C."
                        )
                    else:
                        message = (
                            f"Temperature for {sensor_name}"
                            f"{f' ({sensor.label})' if sensor.label else ''} "
                            f"reached {value:g} °C ({severity.lower()} threshold "
                            f"{threshold:g} °C)."
                        )
                    event = TemperatureAlertEventResponse(
                        sensor_id=sensor_id,
                        sensor_name=sensor_name,
                        sensor_label=sensor.label,
                        current_celsius=value,
                        configured_threshold_celsius=threshold,
                        warning_threshold_celsius=(
                            self.temperature_warning_threshold_celsius
                        ),
                        critical_threshold_celsius=(
                            self.temperature_critical_threshold_celsius
                        ),
                        previous_status=previous,
                        status=severity,
                        severity=severity,
                        timestamp=timestamp,
                        message=message,
                    )
                    self._temperature_events.append(event)
                    self._persist_memory_event(
                        event,
                        "temperature",
                        value,
                        threshold,
                    )
                except Exception:
                    _logger.exception("Could not process one temperature sensor reading")

    def process_sample(self, cpu_usage_percent: float | None, timestamp: str) -> None:
        """Update CPU state from one valid collector sample."""
        usage = _validated_usage(cpu_usage_percent)
        if usage is None:
            return

        new_status = _classify(
            usage, self.warning_threshold_percent, self.critical_threshold_percent
        )
        with self._lock:
            previous_status = self._status.status
            self._status = CpuAlertStatusResponse(
                status=new_status,
                severity=new_status,
                cpu_usage_percent=usage,
                warning_threshold_percent=self.warning_threshold_percent,
                critical_threshold_percent=self.critical_threshold_percent,
                timestamp=timestamp,
            )
            if new_status == previous_status:
                return

            self._cpu_events.append(
                CpuAlertEventResponse(
                    previous_status=previous_status,
                    status=new_status,
                    severity=new_status,
                    cpu_usage_percent=usage,
                    warning_threshold_percent=self.warning_threshold_percent,
                    critical_threshold_percent=self.critical_threshold_percent,
                    timestamp=timestamp,
                    message=_transition_message(
                        "cpu", previous_status, new_status, self.warning_threshold_percent
                    ),
                )
            )
            self._persist_memory_event(
                self._cpu_events[-1],
                "cpu",
                usage,
                self._threshold_for_status(
                    new_status,
                    self.warning_threshold_percent,
                    self.critical_threshold_percent,
                ),
            )

    def process_ram_sample(self, usage_percent: float | None, timestamp: str) -> None:
        """Update RAM state from the existing monitoring snapshot."""
        usage = _validated_usage(usage_percent)
        if usage is None:
            return

        new_status = _classify(
            usage, self.ram_warning_threshold_percent, self.ram_critical_threshold_percent
        )
        with self._lock:
            previous_status = self._ram_status.status
            self._ram_status = ResourceAlertStatusResponse(
                status=new_status,
                severity=new_status,
                usage_percent=usage,
                warning_threshold_percent=self.ram_warning_threshold_percent,
                critical_threshold_percent=self.ram_critical_threshold_percent,
                timestamp=timestamp,
            )
            if new_status == previous_status:
                return

            self._ram_events.append(
                RamAlertEventResponse(
                    previous_status=previous_status,
                    status=new_status,
                    severity=new_status,
                    usage_percent=usage,
                    warning_threshold_percent=self.ram_warning_threshold_percent,
                    critical_threshold_percent=self.ram_critical_threshold_percent,
                    timestamp=timestamp,
                    message=_transition_message(
                        "ram",
                        previous_status,
                        new_status,
                        self.ram_warning_threshold_percent,
                    ),
                )
            )
            self._persist_memory_event(
                self._ram_events[-1],
                "ram",
                usage,
                self._threshold_for_status(
                    new_status,
                    self.ram_warning_threshold_percent,
                    self.ram_critical_threshold_percent,
                ),
            )

    def process_disk_sample(
        self, partitions: list[DiskPartitionResponse], timestamp: str
    ) -> None:
        """Update each accessible partition without probing the filesystem again."""
        valid_partitions = [
            partition
            for partition in partitions
            if self._valid_partition(partition)
        ]
        if not valid_partitions:
            return

        with self._lock:
            for partition in valid_partitions:
                usage = float(partition.usage_percent)
                previous = self._disk_partitions.get(partition.mountpoint)
                previous_status = previous.status if previous else "Normal"
                new_status = _classify(
                    usage,
                    self.disk_warning_threshold_percent,
                    self.disk_critical_threshold_percent,
                )
                self._disk_partitions[partition.mountpoint] = (
                    DiskPartitionAlertStatusResponse(
                        device=partition.device,
                        mountpoint=partition.mountpoint,
                        status=new_status,
                        severity=new_status,
                        total_bytes=partition.total_bytes,
                        used_bytes=partition.used_bytes,
                        free_bytes=partition.free_bytes,
                        usage_percent=usage,
                        timestamp=timestamp,
                    )
                )
                if new_status == previous_status:
                    continue
                self._disk_events.append(
                    DiskAlertEventResponse(
                        previous_status=previous_status,
                        status=new_status,
                        severity=new_status,
                        device=partition.device,
                        mountpoint=partition.mountpoint,
                        total_bytes=partition.total_bytes,
                        used_bytes=partition.used_bytes,
                        free_bytes=partition.free_bytes,
                        usage_percent=usage,
                        warning_threshold_percent=self.disk_warning_threshold_percent,
                        critical_threshold_percent=self.disk_critical_threshold_percent,
                        timestamp=timestamp,
                        message=(
                            f"Disk usage on {partition.mountpoint} has "
                            f"{'returned to normal' if new_status == 'Normal' else 'reached a ' + new_status.lower() + ' level'}."
                        ),
                    )
                )
                self._persist_memory_event(
                    self._disk_events[-1],
                    "disk",
                    usage,
                    self._threshold_for_status(
                        new_status,
                        self.disk_warning_threshold_percent,
                        self.disk_critical_threshold_percent,
                    ),
                    partition,
                )
            if (
                self._disk_timestamp is None
                or self._parse_timestamp(timestamp)
                > self._parse_timestamp(self._disk_timestamp)
            ):
                self._disk_timestamp = timestamp

    @staticmethod
    def _threshold_for_status(
        status: str, warning_threshold: float, critical_threshold: float
    ) -> float:
        return critical_threshold if status == "Critical" else warning_threshold

    def _persist_memory_event(
        self,
        event: (
            CpuAlertEventResponse
            | RamAlertEventResponse
            | DiskAlertEventResponse
            | TemperatureAlertEventResponse
            | BatteryAlertEventResponse
        ),
        resource: str,
        usage: float,
        configured_threshold: float,
        partition: DiskPartitionResponse | None = None,
    ) -> None:
        if self._repository is None or event.id is not None:
            return
        disk_event = event if isinstance(event, DiskAlertEventResponse) else None
        temperature_event = (
            event if isinstance(event, TemperatureAlertEventResponse) else None
        )
        try:
            stored = self._repository.insert_event(
                resource=resource,
                severity=event.severity,
                previous_severity=event.previous_status,
                message=event.message,
                utilization_percent=usage,
                configured_threshold_percent=configured_threshold,
                timestamp=self._parse_timestamp(event.timestamp),
                device=(
                    partition.device if partition else disk_event.device
                    if disk_event else None
                ),
                mountpoint=(
                    partition.mountpoint if partition else disk_event.mountpoint
                    if disk_event else None
                ),
                total_bytes=(
                    partition.total_bytes if partition else disk_event.total_bytes
                    if disk_event else None
                ),
                used_bytes=(
                    partition.used_bytes if partition else disk_event.used_bytes
                    if disk_event else None
                ),
                free_bytes=(
                    partition.free_bytes if partition else disk_event.free_bytes
                    if disk_event else None
                ),
                sensor_id=(
                    temperature_event.sensor_id if temperature_event else None
                ),
                sensor_name=(
                    temperature_event.sensor_name if temperature_event else None
                ),
                sensor_label=(
                    temperature_event.sensor_label if temperature_event else None
                ),
                temperature_celsius=(
                    temperature_event.current_celsius
                    if temperature_event
                    else None
                ),
                configured_threshold_celsius=(
                    temperature_event.configured_threshold_celsius
                    if temperature_event
                    else None
                ),
            )
        except AlertStorageError:
            _logger.exception("Could not persist %s alert transition", resource)
            return
        event.id = stored.id

    def _retry_pending_events(self) -> None:
        if self._repository is None:
            return
        for resource, events in (
            ("cpu", self._cpu_events),
            ("ram", self._ram_events),
            ("disk", self._disk_events),
            ("temperature", self._temperature_events),
            ("battery", self._battery_events),
        ):
            for event in events:
                if event.id is None:
                    if isinstance(event, CpuAlertEventResponse):
                        usage = event.cpu_usage_percent
                        event_warning = event.warning_threshold_percent
                        event_critical = event.critical_threshold_percent
                    elif isinstance(event, TemperatureAlertEventResponse):
                        usage = event.current_celsius
                        event_warning = event.warning_threshold_celsius
                        event_critical = event.critical_threshold_celsius
                    elif isinstance(event, BatteryAlertEventResponse):
                        usage = event.percentage
                        event_warning = event.warning_threshold_percent
                        event_critical = event.critical_threshold_percent
                    else:
                        usage = event.usage_percent
                        event_warning = event.warning_threshold_percent
                        event_critical = event.critical_threshold_percent
                    self._persist_memory_event(
                        event,
                        resource,
                        usage,
                        self._threshold_for_status(
                            event.status, event_warning, event_critical
                        ),
                    )

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)

    def get_thresholds(self) -> AlertThresholdsResponse:
        with self._lock:
            return AlertThresholdsResponse(
                cpu_warning_threshold_percent=self.warning_threshold_percent,
                cpu_critical_threshold_percent=self.critical_threshold_percent,
                ram_warning_threshold_percent=self.ram_warning_threshold_percent,
                ram_critical_threshold_percent=self.ram_critical_threshold_percent,
                disk_warning_threshold_percent=self.disk_warning_threshold_percent,
                disk_critical_threshold_percent=self.disk_critical_threshold_percent,
                temperature_warning_threshold_celsius=(
                    self.temperature_warning_threshold_celsius
                ),
                temperature_critical_threshold_celsius=(
                    self.temperature_critical_threshold_celsius
                ),
                battery_warning_threshold_percent=(
                    self.battery_warning_threshold_percent
                ),
                battery_critical_threshold_percent=(
                    self.battery_critical_threshold_percent
                ),
            )

    def update_thresholds(
        self,
        thresholds: AlertThresholdsResponse,
    ) -> AlertThresholdsResponse:
        values = {
            "cpu_warning_percent": thresholds.cpu_warning_threshold_percent,
            "cpu_critical_percent": thresholds.cpu_critical_threshold_percent,
            "ram_warning_percent": thresholds.ram_warning_threshold_percent,
            "ram_critical_percent": thresholds.ram_critical_threshold_percent,
            "disk_warning_percent": thresholds.disk_warning_threshold_percent,
            "disk_critical_percent": thresholds.disk_critical_threshold_percent,
            "temperature_warning_celsius": (
                thresholds.temperature_warning_threshold_celsius
            ),
            "temperature_critical_celsius": (
                thresholds.temperature_critical_threshold_celsius
            ),
            "battery_warning_percent": (
                thresholds.battery_warning_threshold_percent
            ),
            "battery_critical_percent": (
                thresholds.battery_critical_threshold_percent
            ),
        }
        cpu = self._validate_thresholds(
            "CPU", values["cpu_warning_percent"], values["cpu_critical_percent"]
        )
        ram = self._validate_thresholds(
            "RAM", values["ram_warning_percent"], values["ram_critical_percent"]
        )
        disk = self._validate_thresholds(
            "Disk", values["disk_warning_percent"], values["disk_critical_percent"]
        )
        temperature = self._validate_temperature_thresholds(
            values["temperature_warning_celsius"],
            values["temperature_critical_celsius"],
        )
        battery = self._validate_battery_thresholds(
            values["battery_warning_percent"],
            values["battery_critical_percent"],
        )
        with self._lock:
            if self._repository is not None:
                self._repository.save_thresholds(values)
            (
                self.warning_threshold_percent,
                self.critical_threshold_percent,
            ) = cpu
            (
                self.ram_warning_threshold_percent,
                self.ram_critical_threshold_percent,
            ) = ram
            (
                self.disk_warning_threshold_percent,
                self.disk_critical_threshold_percent,
            ) = disk
            (
                self.temperature_warning_threshold_celsius,
                self.temperature_critical_threshold_celsius,
            ) = temperature
            (
                self.battery_warning_threshold_percent,
                self.battery_critical_threshold_percent,
            ) = battery
            self._status = self._status.model_copy(
                update={
                    "warning_threshold_percent": cpu[0],
                    "critical_threshold_percent": cpu[1],
                }
            )
            self._ram_status = self._ram_status.model_copy(
                update={
                    "warning_threshold_percent": ram[0],
                    "critical_threshold_percent": ram[1],
                }
            )
            self._status = self._status.model_copy(
                update={
                    "warning_threshold_percent": cpu[0],
                    "critical_threshold_percent": cpu[1],
                }
            )
            self._ram_status = self._ram_status.model_copy(
                update={
                    "warning_threshold_percent": ram[0],
                    "critical_threshold_percent": ram[1],
                }
            )
            for sensor in self._temperature_latest_sensors.values():
                sensor.warning_threshold_celsius = temperature[0]
                sensor.critical_threshold_celsius = temperature[1]
            self._battery_status = self._battery_status.model_copy(
                update={
                    "warning_threshold_percent": battery[0],
                    "critical_threshold_percent": battery[1],
                }
            )
        return self.get_thresholds()

    def restore_persisted_state(self) -> None:
        """Load saved thresholds and latest transitions after database startup."""
        if self._repository is None:
            return
        saved = self._repository.get_thresholds()
        if saved is not None:
            thresholds = AlertThresholdsResponse(
                cpu_warning_threshold_percent=saved.cpu_warning_percent,
                cpu_critical_threshold_percent=saved.cpu_critical_percent,
                ram_warning_threshold_percent=saved.ram_warning_percent,
                ram_critical_threshold_percent=saved.ram_critical_percent,
                disk_warning_threshold_percent=saved.disk_warning_percent,
                disk_critical_threshold_percent=saved.disk_critical_percent,
                temperature_warning_threshold_celsius=(
                    saved.temperature_warning_celsius
                ),
                temperature_critical_threshold_celsius=(
                    saved.temperature_critical_celsius
                ),
                battery_warning_threshold_percent=(
                    saved.battery_warning_percent
                    if saved.battery_warning_percent is not None
                    else BATTERY_WARNING_THRESHOLD_PERCENT
                ),
                battery_critical_threshold_percent=(
                    saved.battery_critical_percent
                    if saved.battery_critical_percent is not None
                    else BATTERY_CRITICAL_THRESHOLD_PERCENT
                ),
            )
            cpu = self._validate_thresholds(
                "CPU",
                thresholds.cpu_warning_threshold_percent,
                thresholds.cpu_critical_threshold_percent,
            )
            ram = self._validate_thresholds(
                "RAM",
                thresholds.ram_warning_threshold_percent,
                thresholds.ram_critical_threshold_percent,
            )
            disk = self._validate_thresholds(
                "Disk",
                thresholds.disk_warning_threshold_percent,
                thresholds.disk_critical_threshold_percent,
            )
            temperature = self._validate_temperature_thresholds(
                thresholds.temperature_warning_threshold_celsius,
                thresholds.temperature_critical_threshold_celsius,
            )
            battery = self._validate_battery_thresholds(
                thresholds.battery_warning_threshold_percent,
                thresholds.battery_critical_threshold_percent,
            )
            with self._lock:
                (
                    self.warning_threshold_percent,
                    self.critical_threshold_percent,
                ) = cpu
                (
                    self.ram_warning_threshold_percent,
                    self.ram_critical_threshold_percent,
                ) = ram
                (
                    self.disk_warning_threshold_percent,
                    self.disk_critical_threshold_percent,
                ) = disk
                (
                    self.temperature_warning_threshold_celsius,
                    self.temperature_critical_threshold_celsius,
                ) = temperature
                (
                    self.battery_warning_threshold_percent,
                    self.battery_critical_threshold_percent,
                ) = battery

        with self._lock:
            for record in self._repository.get_current_states():
                timestamp = record.timestamp.isoformat()
                norm_sev = _normalize_severity(record.severity)
                if record.resource == "cpu":
                    self._status = CpuAlertStatusResponse(
                        status=norm_sev,
                        severity=norm_sev,
                        cpu_usage_percent=record.utilization_percent,
                        warning_threshold_percent=self.warning_threshold_percent,
                        critical_threshold_percent=self.critical_threshold_percent,
                        timestamp=timestamp,
                    )
                elif record.resource == "ram":
                    self._ram_status = ResourceAlertStatusResponse(
                        status=norm_sev,
                        severity=norm_sev,
                        usage_percent=record.utilization_percent,
                        warning_threshold_percent=self.ram_warning_threshold_percent,
                        critical_threshold_percent=self.ram_critical_threshold_percent,
                        timestamp=timestamp,
                    )
                elif record.resource == "disk" and record.mountpoint is not None:
                    self._disk_partitions[record.mountpoint] = (
                        DiskPartitionAlertStatusResponse(
                            device=record.device or "",
                            mountpoint=record.mountpoint,
                            status=norm_sev,
                            severity=norm_sev,
                            total_bytes=record.total_bytes or 0,
                            used_bytes=record.used_bytes or 0,
                            free_bytes=record.free_bytes or 0,
                            usage_percent=record.utilization_percent,
                            timestamp=timestamp,
                        )
                    )
                    self._disk_timestamp = timestamp
                elif record.resource == "temperature" and record.sensor_id:
                    self._temperature_last_severity[record.sensor_id] = norm_sev
                elif record.resource == "battery":
                    self._battery_last_severity = norm_sev
                    self._battery_status = BatteryAlertStatusResponse(
                        availability="available",
                        platform="unknown",
                        message=None,
                        percentage=record.utilization_percent,
                        charging_state=None,
                        power_plugged=None,
                        status=norm_sev,
                        severity=norm_sev,
                        warning_threshold_percent=self.battery_warning_threshold_percent,
                        critical_threshold_percent=self.battery_critical_threshold_percent,
                        timestamp=timestamp,
                    )
            self._cpu_events.clear()
            self._ram_events.clear()
            self._disk_events.clear()
            self._temperature_events.clear()
            self._battery_events.clear()
            for record in reversed(self._repository.get_recent_events(_RECENT_EVENT_LIMIT)):
                self._append_restored_event(record)

    def _append_restored_event(self, record: AlertEvent) -> None:
        norm_status = _normalize_severity(record.severity)
        norm_prev = _normalize_severity(record.previous_severity)
        common = {
            "previous_status": norm_prev,
            "status": norm_status,
            "severity": norm_status,
            "timestamp": record.timestamp.isoformat(),
            "message": record.message,
            "id": record.id,
            "acknowledged": record.acknowledged,
            "acknowledged_at": (
                record.acknowledged_at.isoformat()
                if record.acknowledged_at
                else None
            ),
        }
        if record.resource == "cpu":
            self._cpu_events.append(
                CpuAlertEventResponse(
                    **common,
                    cpu_usage_percent=record.utilization_percent,
                    warning_threshold_percent=self.warning_threshold_percent,
                    critical_threshold_percent=self.critical_threshold_percent,
                )
            )
        elif record.resource == "ram":
            self._ram_events.append(
                RamAlertEventResponse(
                    **common,
                    usage_percent=record.utilization_percent,
                    warning_threshold_percent=self.ram_warning_threshold_percent,
                    critical_threshold_percent=self.ram_critical_threshold_percent,
                )
            )
        elif record.resource == "disk":
            self._disk_events.append(
                DiskAlertEventResponse(
                    **common,
                    device=record.device or "",
                    mountpoint=record.mountpoint or "",
                    total_bytes=record.total_bytes or 0,
                    used_bytes=record.used_bytes or 0,
                    free_bytes=record.free_bytes or 0,
                    usage_percent=record.utilization_percent,
                    warning_threshold_percent=self.disk_warning_threshold_percent,
                    critical_threshold_percent=self.disk_critical_threshold_percent,
                )
            )
        elif record.resource == "temperature" and record.sensor_id:
            self._temperature_events.append(
                TemperatureAlertEventResponse(
                    **common,
                    sensor_id=record.sensor_id,
                    sensor_name=record.sensor_name or record.sensor_id,
                    sensor_label=record.sensor_label,
                    current_celsius=(
                        record.temperature_celsius
                        if record.temperature_celsius is not None
                        else record.utilization_percent
                    ),
                    configured_threshold_celsius=(
                        record.configured_threshold_celsius
                        if record.configured_threshold_celsius is not None
                        else record.configured_threshold_percent
                    ),
                    warning_threshold_celsius=(
                        self.temperature_warning_threshold_celsius
                    ),
                    critical_threshold_celsius=(
                        self.temperature_critical_threshold_celsius
                    ),
                )
            )
        elif record.resource == "battery":
            self._battery_events.append(
                BatteryAlertEventResponse(
                    **common,
                    percentage=record.utilization_percent,
                    configured_threshold_percent=(
                        record.configured_threshold_percent
                    ),
                    warning_threshold_percent=self.battery_warning_threshold_percent,
                    critical_threshold_percent=self.battery_critical_threshold_percent,
                )
            )

    def remove_event(self, alert_id: int) -> None:
        with self._lock:
            self._cpu_events = deque(
                (event for event in self._cpu_events if event.id != alert_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )
            self._ram_events = deque(
                (event for event in self._ram_events if event.id != alert_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )
            self._disk_events = deque(
                (event for event in self._disk_events if event.id != alert_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )
            self._temperature_events = deque(
                (event for event in self._temperature_events if event.id != alert_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )
            self._battery_events = deque(
                (event for event in self._battery_events if event.id != alert_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )

    def mark_acknowledged(self, alert_id: int, acknowledged_at: datetime) -> None:
        with self._lock:
            for events in (
                self._cpu_events,
                self._ram_events,
                self._disk_events,
                self._temperature_events,
                self._battery_events,
            ):
                for event in events:
                    if event.id == alert_id:
                        event.acknowledged = True
                        event.acknowledged_at = acknowledged_at.isoformat()

    def clear_events(self) -> None:
        with self._lock:
            self._cpu_events.clear()
            self._ram_events.clear()
            self._disk_events.clear()
            self._temperature_events.clear()

    @staticmethod
    def _valid_partition(partition: DiskPartitionResponse) -> bool:
        usage = _validated_usage(partition.usage_percent)
        capacities = (partition.total_bytes, partition.used_bytes, partition.free_bytes)
        return (
            bool(partition.device)
            and bool(partition.mountpoint)
            and usage is not None
            and all(isinstance(value, int) and not isinstance(value, bool) for value in capacities)
            and partition.total_bytes > 0
            and 0 <= partition.used_bytes <= partition.total_bytes
            and 0 <= partition.free_bytes <= partition.total_bytes
        )

    def get_status(self) -> CpuAlertStatusResponse:
        """Return the most recently accepted CPU alert state."""
        with self._lock:
            return self._status.model_copy(deep=True)

    def get_ram_status(self) -> ResourceAlertStatusResponse:
        with self._lock:
            return self._ram_status.model_copy(deep=True)

    def get_disk_status(self) -> DiskAlertStatusResponse:
        with self._lock:
            partitions = [
                partition.model_copy(deep=True)
                for partition in self._disk_partitions.values()
            ]
            status = max(
                (partition.status for partition in partitions),
                key=lambda value: _STATUS_ORDER[value],
                default="Normal",
            )
            return DiskAlertStatusResponse(
                status=status,
                severity=status,
                warning_threshold_percent=self.disk_warning_threshold_percent,
                critical_threshold_percent=self.disk_critical_threshold_percent,
                timestamp=self._disk_timestamp,
                partitions=partitions,
            )

    def get_alerts(self) -> CpuAlertsResponse:
        """Return CPU-compatible fields plus RAM and disk state and events."""
        with self._lock:
            return CpuAlertsResponse(
                status=self._status.model_copy(deep=True),
                recent_events=[event.model_copy(deep=True) for event in self._cpu_events],
                ram=RamAlertsResourceResponse(
                    status=self._ram_status.model_copy(deep=True),
                    recent_events=[
                        event.model_copy(deep=True) for event in self._ram_events
                    ],
                ),
                disk=DiskAlertsResourceResponse(
                    status=self.get_disk_status(),
                    recent_events=[
                        event.model_copy(deep=True) for event in self._disk_events
                    ],
                ),
                temperature=self.get_temperature_alerts(),
                battery=self.get_battery_alerts(),
            )

    def get_temperature_alerts(self) -> TemperatureAlertsResponse:
        """Return live sensor availability, current states, and recent transitions."""
        with self._lock:
            return TemperatureAlertsResponse(
                availability=self._temperature_availability,
                platform=self._temperature_platform,
                message=self._temperature_message,
                warning_threshold_celsius=(
                    self.temperature_warning_threshold_celsius
                ),
                critical_threshold_celsius=(
                    self.temperature_critical_threshold_celsius
                ),
                sensors=[
                    sensor.model_copy(deep=True)
                    for sensor in self._temperature_latest_sensors.values()
                ],
                recent_events=[
                    event.model_copy(deep=True)
                    for event in self._temperature_events
                ],
            )

    def get_battery_alerts(self) -> BatteryAlertsResponse:
        """Return current battery state and recent battery transitions."""
        with self._lock:
            return BatteryAlertsResponse(
                status=self._battery_status.model_copy(deep=True),
                recent_events=[
                    event.model_copy(deep=True)
                    for event in self._battery_events
                ],
            )

    def get_battery_status(self) -> BatteryAlertStatusResponse:
        """Return current battery alert state."""
        with self._lock:
            return self._battery_status.model_copy(deep=True)

    def reset(self) -> None:
        """Reset all resource alert states and event histories for isolated tests."""
        with self._lock:
            self._status = self._initial_cpu_status()
            self._ram_status = self._initial_ram_status()
            self._disk_partitions.clear()
            self._disk_timestamp = None
            self._cpu_events.clear()
            self._ram_events.clear()
            self._disk_events.clear()
            self._temperature_last_severity.clear()
            self._temperature_latest_sensors.clear()
            self._temperature_events.clear()
            self._temperature_availability = "unavailable"
            self._temperature_platform = "unknown"
            self._temperature_message = "Temperature sensors have not been sampled."
            self._battery_last_severity = "Normal"
            self._battery_status = self._initial_battery_status()
            self._battery_events.clear()


alert_repository = AlertRepository(database.session_factory)
cpu_alert_service = CpuAlertService(repository=alert_repository)
