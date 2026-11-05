
"""SQLite engine, UTC timestamp handling, and session lifecycle."""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Engine, create_engine, event, inspect
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""


class UTCDateTime(TypeDecorator[datetime]):
    """Store UTC datetimes consistently and return timezone-aware values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


class Database:
    """Own a SQLite engine and the session factory used by repositories."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                pass
        self.engine: Engine = create_engine(
            URL.create("sqlite+pysqlite", database=str(self.path)),
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        event.listen(self.engine, "connect", self._configure_connection)

    @staticmethod
    def _configure_connection(connection: Any, _: Any) -> None:
        """Enable SQLite settings appropriate for concurrent monitor/API access."""
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
        finally:
            cursor.close()

    def initialize(self) -> None:
        """Create missing tables and add compatible columns to existing databases."""
        from app.database import models  # noqa: F401

        Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("historical_metrics")
            }
            if "disk_read_speed" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE historical_metrics ADD COLUMN disk_read_speed FLOAT"
                )
            if "disk_write_speed" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE historical_metrics ADD COLUMN disk_write_speed FLOAT"
                )
            battery_columns = {
                "battery_availability": "VARCHAR(16)",
                "battery_percentage": "FLOAT",
                "battery_charging_state": "VARCHAR(16)",
                "battery_power_plugged": "BOOLEAN",
            }
            for name, definition in battery_columns.items():
                if name not in columns:
                    connection.exec_driver_sql(
                        f"ALTER TABLE historical_metrics ADD COLUMN {name} {definition}"
                    )
            table_names = set(inspect(connection).get_table_names())
            table_columns = {
                table: {
                    column["name"]
                    for column in inspect(connection).get_columns(table)
                }
                for table in (
                    "alert_events",
                    "alert_current_states",
                    "alert_threshold_settings",
                    "historical_predictions",
                )
                if table in table_names
            }
            additions = {
                "alert_events": {
                    "sensor_id": "VARCHAR(512)",
                    "sensor_name": "VARCHAR(256)",
                    "sensor_label": "VARCHAR(256)",
                    "temperature_celsius": "FLOAT",
                    "configured_threshold_celsius": "FLOAT",
                },
                "alert_current_states": {
                    "sensor_id": "VARCHAR(512)",
                    "sensor_name": "VARCHAR(256)",
                    "sensor_label": "VARCHAR(256)",
                },
                "alert_threshold_settings": {
                    "temperature_warning_celsius": "FLOAT NOT NULL DEFAULT 80",
                    "temperature_critical_celsius": "FLOAT NOT NULL DEFAULT 90",
                    "battery_warning_percent": "FLOAT NOT NULL DEFAULT 20",
                    "battery_critical_percent": "FLOAT NOT NULL DEFAULT 10",
                },
                "historical_predictions": {
                    "prediction_id": "VARCHAR(64)",
                    "resource": "VARCHAR(32)",
                    "metric": "VARCHAR(64)",
                    "unit": "VARCHAR(32)",
                    "horizon": "VARCHAR(16)",
                    "horizon_seconds": "INTEGER",
                    "generated_at": "DATETIME",
                    "target_timestamp": "DATETIME",
                    "current_value": "FLOAT",
                    "predicted_value": "FLOAT",
                    "lower_bound": "FLOAT",
                    "upper_bound": "FLOAT",
                    "confidence_score": "FLOAT",
                    "model": "VARCHAR(64)",
                    "actual_value": "FLOAT",
                    "absolute_error": "FLOAT",
                    "percentage_error": "FLOAT",
                    "evaluation_status": "VARCHAR(32)",
                    "evaluated_at": "DATETIME",
                },
            }
            for table, fields in additions.items():
                if table in table_columns:
                    for name, definition in fields.items():
                        if name not in table_columns[table]:
                            connection.exec_driver_sql(
                                f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                            )

    def dispose(self) -> None:
        """Close all pooled database connections."""
        self.engine.dispose()


database = Database(settings.database_path)


def initialize_database() -> None:
    """Initialize the application database."""
    database.initialize()


def dispose_database() -> None:
    """Dispose application database connections during shutdown."""
    database.dispose()
