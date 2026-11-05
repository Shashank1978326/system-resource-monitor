"""Historical metrics business logic and storage error handling."""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.database.connection import database
from app.database.models import (
    HistoricalMetrics,
    HistoricalNetworkInterfaceMetrics,
    HistoricalTemperatureMetrics,
)
from app.database.repository import HistoryRepository
from app.schemas.monitoring import (
    BatteryResponse,
    MonitoringSnapshotResponse,
    TemperatureResponse,
)
from app.services.temperature_service import get_temperature_info

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")


class HistoryStorageError(Exception):
    """A historical storage operation failed."""


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class HistoryService:
    """Map collected snapshots to stored metrics and apply history policies."""

    def __init__(
        self,
        repository: HistoryRepository,
        retention_days: int,
    ) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be a positive integer")
        self.repository = repository
        self.retention_days = retention_days

    @staticmethod
    def _disk_utilization(snapshot: MonitoringSnapshotResponse) -> float | None:
        """Calculate capacity-weighted use across accessible mounted partitions."""
        partitions = snapshot.disk.partitions
        total_bytes = sum(partition.total_bytes for partition in partitions)
        if total_bytes <= 0:
            return None
        used_bytes = sum(partition.used_bytes for partition in partitions)
        return used_bytes / total_bytes * 100

    def record_snapshot(
        self,
        snapshot: MonitoringSnapshotResponse,
        temperature_info: TemperatureResponse | None = None,
        battery_info: BatteryResponse | None = None,
        *,
        temperature_sampled: bool = False,
    ) -> None:
        """Persist the collected values without inventing unsupported metrics."""
        record = HistoricalMetrics(
            timestamp=_utc_datetime(datetime.fromisoformat(snapshot.timestamp)),
            cpu_utilization_percent=snapshot.cpu.cpu_usage_percent,
            ram_utilization_percent=snapshot.memory.usage_percent,
            ram_used_bytes=snapshot.memory.used_bytes,
            ram_available_bytes=snapshot.memory.available_bytes,
            disk_read_bytes=snapshot.disk.io.read_bytes,
            disk_write_bytes=snapshot.disk.io.write_bytes,
            disk_read_speed=snapshot.disk.io.read_speed_bytes_per_sec,
            disk_write_speed=snapshot.disk.io.write_speed_bytes_per_sec,
            disk_utilization_percent=self._disk_utilization(snapshot),
            network_download_speed=snapshot.network.download_speed_bytes_per_sec,
            network_upload_speed=snapshot.network.upload_speed_bytes_per_sec,
            network_bytes_received=snapshot.network.bytes_received,
            network_bytes_sent=snapshot.network.bytes_sent,
            battery_availability=(
                battery_info.availability if battery_info is not None else None
            ),
            battery_percentage=(
                battery_info.percentage
                if battery_info is not None
                and battery_info.availability == "available"
                else None
            ),
            battery_charging_state=(
                battery_info.charging_state
                if battery_info is not None
                and battery_info.availability == "available"
                else None
            ),
            battery_power_plugged=(
                battery_info.power_plugged
                if battery_info is not None
                and battery_info.availability == "available"
                else None
            ),
        )
        interface_records = [
            HistoricalNetworkInterfaceMetrics(
                timestamp=record.timestamp,
                interface_name=interface.name,
                download_speed=interface.download_speed_bytes_per_sec,
                upload_speed=interface.upload_speed_bytes_per_sec,
            )
            for interface in snapshot.network.interfaces
            if interface.name
        ]
        temperature_records: list[HistoricalTemperatureMetrics] = []
        try:
            temperature = (
                temperature_info
                if temperature_sampled or temperature_info is not None
                else get_temperature_info()
            )
            if temperature is not None:
                temperature_records = [
                    HistoricalTemperatureMetrics(
                        timestamp=record.timestamp,
                        sensor_id=sensor.sensor_id,
                        sensor_name=sensor.sensor_name,
                        sensor_label=sensor.label,
                        reading_index=sensor.reading_index,
                        temperature_celsius=sensor.current_celsius,
                    )
                    for sensor in temperature.sensors
                    if sensor.current_celsius is not None
                ]
        except Exception:
            logger.exception(
                "Unable to sample hardware temperatures for historical storage"
            )
        self._run_storage_operation(
            "insert monitoring record",
            lambda: self.repository.insert_snapshot(
                record, interface_records, temperature_records
            ),
        )

    def get_records(
        self,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
        offset: int,
    ) -> list[HistoricalMetrics]:
        return self._run_storage_operation(
            "read monitoring records",
            lambda: self.repository.get_records(
                _utc_datetime(start_time) if start_time else None,
                _utc_datetime(end_time) if end_time else None,
                limit,
                offset,
            ),
        )

    def get_recent_records(self, limit: int = 120) -> list[HistoricalMetrics]:
        return self._run_storage_operation(
            "read recent monitoring records",
            lambda: self.repository.get_recent_records(limit),
        )

    def get_metric_averages(
        self,
        metric: str,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        """Read grouped metric averages using a fixed allowlist of model columns."""
        metric_columns = {
            "cpu": HistoricalMetrics.cpu_utilization_percent,
            "memory": HistoricalMetrics.ram_utilization_percent,
            "disk": HistoricalMetrics.disk_utilization_percent,
            "network_download": HistoricalMetrics.network_download_speed,
            "network_upload": HistoricalMetrics.network_upload_speed,
            "disk_read": HistoricalMetrics.disk_read_bytes,
            "disk_write": HistoricalMetrics.disk_write_bytes,
            "disk_read_speed": HistoricalMetrics.disk_read_speed,
            "disk_write_speed": HistoricalMetrics.disk_write_speed,
        }
        try:
            metric_column = metric_columns[metric]
        except KeyError as exc:
            raise ValueError(f"Unsupported historical metric: {metric}") from exc
        return self._run_storage_operation(
            "read grouped monitoring metrics",
            lambda: self.repository.get_metric_averages(
                metric_column,
                _utc_datetime(start_time),
                _utc_datetime(end_time),
                interval_seconds,
            ),
        )

    def get_battery_averages(
        self,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None, str | None, bool | None, str | None, datetime]]:
        return self._run_storage_operation(
            "read grouped historical battery readings",
            lambda: self.repository.get_battery_averages(
                _utc_datetime(start_time),
                _utc_datetime(end_time),
                interval_seconds,
            ),
        )

    def get_network_interface_names(self) -> list[str]:
        return self._run_storage_operation(
            "read historical network interfaces",
            self.repository.get_network_interface_names,
        )

    def get_network_interface_metric_averages(
        self,
        interface_name: str,
        metric: str,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        metric_columns = {
            "network_interface_download": (
                HistoricalNetworkInterfaceMetrics.download_speed
            ),
            "network_interface_upload": (
                HistoricalNetworkInterfaceMetrics.upload_speed
            ),
        }
        try:
            metric_column = metric_columns[metric]
        except KeyError as exc:
            raise ValueError(f"Unsupported historical metric: {metric}") from exc
        return self._run_storage_operation(
            "read grouped per-interface network metrics",
            lambda: self.repository.get_network_interface_metric_averages(
                interface_name,
                metric_column,
                _utc_datetime(start_time),
                _utc_datetime(end_time),
                interval_seconds,
            ),
        )

    def get_temperature_sensors(self) -> list[tuple[str, str, str | None]]:
        return self._run_storage_operation(
            "read historical temperature sensors",
            self.repository.get_temperature_sensors,
        )

    def get_temperature_averages(
        self,
        sensor_id: str,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        return self._run_storage_operation(
            "read grouped historical temperature readings",
            lambda: self.repository.get_temperature_averages(
                sensor_id,
                _utc_datetime(start_time),
                _utc_datetime(end_time),
                interval_seconds,
            ),
        )

    def get_summary(
        self, start_time: datetime | None, end_time: datetime | None
    ) -> dict[str, Any]:
        return self._run_storage_operation(
            "calculate history summary",
            lambda: self.repository.get_summary(
                _utc_datetime(start_time) if start_time else None,
                _utc_datetime(end_time) if end_time else None,
            ),
        )

    def get_stats(self) -> dict[str, Any]:
        statistics = self._run_storage_operation(
            "read history statistics", self.repository.get_stats
        )
        statistics["retention_days"] = self.retention_days
        return statistics

    def cleanup_expired(self, now: datetime | None = None) -> int:
        current_time = _utc_datetime(now or datetime.now(timezone.utc))
        cutoff = current_time - timedelta(days=self.retention_days)
        return self._run_storage_operation(
            "clean expired monitoring records",
            lambda: self.repository.delete_before(cutoff),
        )

    @staticmethod
    def _run_storage_operation(
        operation: str, callback: Callable[[], _Result]
    ) -> _Result:
        try:
            return callback()
        except (SQLAlchemyError, OSError) as exc:
            logger.exception("Unable to %s", operation)
            raise HistoryStorageError(f"Unable to {operation}") from exc


history_repository = HistoryRepository(database.session_factory, database.path)
history_service = HistoryService(
    history_repository,
    retention_days=settings.history_retention_days,
)
