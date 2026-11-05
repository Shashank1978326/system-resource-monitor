"""Database queries for monitoring history."""

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Integer, case, cast, delete, distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import (
    HistoricalMetrics,
    HistoricalNetworkInterfaceMetrics,
    HistoricalTemperatureMetrics,
)


class HistoryRepository:
    """Perform bounded history reads, aggregates, writes, and retention cleanup."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        database_path: str | Path,
    ) -> None:
        self._session_factory = session_factory
        self.database_path = Path(database_path)

    @staticmethod
    def _time_conditions(
        start_time: datetime | None, end_time: datetime | None
    ) -> list[Any]:
        conditions = []
        if start_time is not None:
            conditions.append(HistoricalMetrics.timestamp >= start_time)
        if end_time is not None:
            conditions.append(HistoricalMetrics.timestamp <= end_time)
        return conditions

    def insert(self, record: HistoricalMetrics) -> HistoricalMetrics:
        """Insert one monitoring cycle and commit it atomically."""
        with self._session_factory.begin() as session:
            session.add(record)
            session.flush()
        return record

    def insert_snapshot(
        self,
        record: HistoricalMetrics,
        interface_records: list[HistoricalNetworkInterfaceMetrics],
        temperature_records: list[HistoricalTemperatureMetrics] | None = None,
    ) -> HistoricalMetrics:
        """Persist a snapshot with its interface and temperature samples atomically."""
        with self._session_factory.begin() as session:
            session.add(record)
            session.add_all(interface_records)
            session.add_all(temperature_records or [])
            session.flush()
        return record

    def get_records(
        self,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
        offset: int,
    ) -> list[HistoricalMetrics]:
        """Return a chronological page of records matching the time range."""
        statement = (
            select(HistoricalMetrics)
            .where(*self._time_conditions(start_time, end_time))
            .order_by(HistoricalMetrics.timestamp.asc())
            .limit(limit)
            .offset(offset)
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get_recent_records(self, limit: int = 120) -> list[HistoricalMetrics]:
        """Return the most recent historical metrics records in ascending chronological order."""
        statement = (
            select(HistoricalMetrics)
            .order_by(HistoricalMetrics.timestamp.desc())
            .limit(limit)
        )
        with self._session_factory() as session:
            records = list(session.scalars(statement))
            records.reverse()
            return records

    def get_metric_averages(
        self,
        metric_column: Any,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        """Return SQL-averaged values grouped into UTC epoch-aligned buckets."""
        epoch_seconds = cast(
            func.strftime("%s", HistoricalMetrics.timestamp), Integer
        )
        bucket_timestamp = (
            cast(epoch_seconds / interval_seconds, Integer) * interval_seconds
        )
        statement = (
            select(
                bucket_timestamp.label("bucket_timestamp"),
                func.avg(metric_column).label("average_value"),
            )
            .where(*self._time_conditions(start_time, end_time))
            .group_by(bucket_timestamp)
            .order_by(bucket_timestamp.asc())
        )
        with self._session_factory() as session:
            return [
                (int(bucket_timestamp), average_value)
                for bucket_timestamp, average_value in session.execute(statement)
            ]

    def get_battery_averages(
        self,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None, str | None, bool | None, str | None, datetime]]:
        """Average battery percentage and retain the latest state per UTC bucket."""
        epoch_seconds = cast(
            func.strftime("%s", HistoricalMetrics.timestamp), Integer
        )
        bucket_timestamp = (
            cast(epoch_seconds / interval_seconds, Integer) * interval_seconds
        )
        bucketed = (
            select(
                bucket_timestamp.label("bucket_timestamp"),
                HistoricalMetrics.timestamp.label("sample_timestamp"),
                HistoricalMetrics.battery_percentage.label("percentage"),
                HistoricalMetrics.battery_charging_state.label("charging_state"),
                HistoricalMetrics.battery_power_plugged.label("power_plugged"),
                HistoricalMetrics.battery_availability.label("availability"),
                func.row_number()
                .over(
                    partition_by=bucket_timestamp,
                    order_by=HistoricalMetrics.timestamp.desc(),
                )
                .label("sample_rank"),
            )
            .where(
                HistoricalMetrics.timestamp >= start_time,
                HistoricalMetrics.timestamp <= end_time,
            )
            .cte("battery_bucketed")
        )
        def latest_value(column: Any) -> Any:
            return func.max(
                case((bucketed.c.sample_rank == 1, column), else_=None)
            )

        statement = (
            select(
                bucketed.c.bucket_timestamp,
                func.avg(bucketed.c.percentage).label("average_percentage"),
                latest_value(bucketed.c.charging_state).label("charging_state"),
                latest_value(bucketed.c.power_plugged).label("power_plugged"),
                latest_value(bucketed.c.availability).label("availability"),
                latest_value(bucketed.c.sample_timestamp).label("status_timestamp"),
            )
            .group_by(bucketed.c.bucket_timestamp)
            .order_by(bucketed.c.bucket_timestamp.asc())
        )
        with self._session_factory() as session:
            return [
                (
                    int(bucket_timestamp),
                    average_percentage,
                    charging_state,
                    bool(power_plugged) if power_plugged is not None else None,
                    availability,
                    status_timestamp,
                )
                for (
                    bucket_timestamp,
                    average_percentage,
                    charging_state,
                    power_plugged,
                    availability,
                    status_timestamp,
                ) in session.execute(statement)
            ]

    def get_network_interface_names(self) -> list[str]:
        """Return interface names with retained historical samples."""
        statement = (
            select(distinct(HistoricalNetworkInterfaceMetrics.interface_name))
            .order_by(HistoricalNetworkInterfaceMetrics.interface_name.asc())
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get_network_interface_metric_averages(
        self,
        interface_name: str,
        metric_column: Any,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        """Aggregate one interface metric into bounded UTC-aligned buckets."""
        epoch_seconds = cast(
            func.strftime("%s", HistoricalNetworkInterfaceMetrics.timestamp), Integer
        )
        bucket_timestamp = (
            cast(epoch_seconds / interval_seconds, Integer) * interval_seconds
        )
        statement = (
            select(
                bucket_timestamp.label("bucket_timestamp"),
                func.avg(metric_column).label("average_value"),
            )
            .where(
                HistoricalNetworkInterfaceMetrics.interface_name == interface_name,
                HistoricalNetworkInterfaceMetrics.timestamp >= start_time,
                HistoricalNetworkInterfaceMetrics.timestamp <= end_time,
            )
            .group_by(bucket_timestamp)
            .order_by(bucket_timestamp.asc())
        )
        with self._session_factory() as session:
            return [
                (int(bucket_timestamp), average_value)
                for bucket_timestamp, average_value in session.execute(statement)
            ]

    def get_temperature_sensors(self) -> list[tuple[str, str, str | None]]:
        """Return distinct sensor identities and labels in retained history."""
        statement = (
            select(
                HistoricalTemperatureMetrics.sensor_id,
                HistoricalTemperatureMetrics.sensor_name,
                HistoricalTemperatureMetrics.sensor_label,
            )
            .distinct()
            .order_by(
                HistoricalTemperatureMetrics.sensor_name.asc(),
                HistoricalTemperatureMetrics.reading_index.asc(),
            )
        )
        with self._session_factory() as session:
            return [
                (sensor_id, sensor_name, label)
                for sensor_id, sensor_name, label in session.execute(statement)
            ]

    def get_temperature_averages(
        self,
        sensor_id: str,
        start_time: datetime,
        end_time: datetime,
        interval_seconds: int,
    ) -> list[tuple[int, float | None]]:
        """Average one sensor's readings into UTC-aligned buckets."""
        epoch_seconds = cast(
            func.strftime("%s", HistoricalTemperatureMetrics.timestamp), Integer
        )
        bucket_timestamp = (
            cast(epoch_seconds / interval_seconds, Integer) * interval_seconds
        )
        statement = (
            select(
                bucket_timestamp.label("bucket_timestamp"),
                func.avg(HistoricalTemperatureMetrics.temperature_celsius).label(
                    "average_value"
                ),
            )
            .where(
                HistoricalTemperatureMetrics.sensor_id == sensor_id,
                HistoricalTemperatureMetrics.timestamp >= start_time,
                HistoricalTemperatureMetrics.timestamp <= end_time,
            )
            .group_by(bucket_timestamp)
            .order_by(bucket_timestamp.asc())
        )
        with self._session_factory() as session:
            return [
                (int(bucket_timestamp), average_value)
                for bucket_timestamp, average_value in session.execute(statement)
            ]

    def get_summary(
        self, start_time: datetime | None, end_time: datetime | None
    ) -> dict[str, Any]:
        """Calculate summary statistics in SQLite rather than loading records."""
        statement = (
            select(
                func.count(HistoricalMetrics.id).label("total_record_count"),
                func.avg(HistoricalMetrics.cpu_utilization_percent).label("average_cpu"),
                func.max(HistoricalMetrics.cpu_utilization_percent).label("maximum_cpu"),
                func.avg(HistoricalMetrics.ram_utilization_percent).label("average_ram"),
                func.max(HistoricalMetrics.ram_utilization_percent).label("maximum_ram"),
                func.avg(HistoricalMetrics.network_download_speed).label(
                    "average_download"
                ),
                func.max(HistoricalMetrics.network_download_speed).label(
                    "maximum_download"
                ),
                func.avg(HistoricalMetrics.network_upload_speed).label("average_upload"),
                func.max(HistoricalMetrics.network_upload_speed).label(
                    "maximum_upload"
                ),
                func.min(HistoricalMetrics.timestamp).label("earliest_timestamp"),
                func.max(HistoricalMetrics.timestamp).label("latest_timestamp"),
            )
            .where(*self._time_conditions(start_time, end_time))
        )
        with self._session_factory() as session:
            return dict(session.execute(statement).one()._mapping)

    def get_stats(self) -> dict[str, Any]:
        """Return total row count and the timestamp span of retained data."""
        statement = select(
            func.count(HistoricalMetrics.id).label("total_records"),
            func.min(HistoricalMetrics.timestamp).label("earliest_timestamp"),
            func.max(HistoricalMetrics.timestamp).label("latest_timestamp"),
        )
        with self._session_factory() as session:
            statistics = dict(session.execute(statement).one()._mapping)
        try:
            statistics["database_size_bytes"] = self.database_path.stat().st_size
        except FileNotFoundError:
            statistics["database_size_bytes"] = 0
        return statistics

    def delete_before(self, cutoff: datetime) -> int:
        """Delete both resource and per-interface samples older than retention."""
        statement = delete(HistoricalMetrics).where(
            HistoricalMetrics.timestamp < cutoff
        )
        interface_statement = delete(HistoricalNetworkInterfaceMetrics).where(
            HistoricalNetworkInterfaceMetrics.timestamp < cutoff
        )
        temperature_statement = delete(HistoricalTemperatureMetrics).where(
            HistoricalTemperatureMetrics.timestamp < cutoff
        )
        with self._session_factory.begin() as session:
            result = session.execute(statement)
            session.execute(interface_statement)
            session.execute(temperature_statement)
            return result.rowcount or 0
