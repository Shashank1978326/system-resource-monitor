"""SQLAlchemy models for persisted monitoring history."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.connection import Base, UTCDateTime


class HistoricalMetrics(Base):
    """One combined resource sample from a monitoring collection cycle."""

    __tablename__ = "historical_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, unique=True, index=True
    )
    cpu_utilization_percent: Mapped[float | None] = mapped_column(Float)
    ram_utilization_percent: Mapped[float | None] = mapped_column(Float)
    ram_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    ram_available_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_read_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_write_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_read_speed: Mapped[float | None] = mapped_column(Float)
    disk_write_speed: Mapped[float | None] = mapped_column(Float)
    disk_utilization_percent: Mapped[float | None] = mapped_column(Float)
    network_download_speed: Mapped[float | None] = mapped_column(Float)
    network_upload_speed: Mapped[float | None] = mapped_column(Float)
    network_bytes_received: Mapped[int | None] = mapped_column(BigInteger)
    network_bytes_sent: Mapped[int | None] = mapped_column(BigInteger)
    battery_availability: Mapped[str | None] = mapped_column(String(16))
    battery_percentage: Mapped[float | None] = mapped_column(Float)
    battery_charging_state: Mapped[str | None] = mapped_column(String(16))
    battery_power_plugged: Mapped[bool | None] = mapped_column(Boolean)


class HistoricalNetworkInterfaceMetrics(Base):
    """One interface's real throughput sample from a monitoring cycle."""

    __tablename__ = "historical_network_interface_metrics"
    __table_args__ = (
        UniqueConstraint(
            "timestamp", "interface_name", name="uq_history_interface_timestamp"
        ),
        Index(
            "ix_history_interface_name_timestamp", "interface_name", "timestamp"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    interface_name: Mapped[str] = mapped_column(String(512), nullable=False)
    download_speed: Mapped[float | None] = mapped_column(Float)
    upload_speed: Mapped[float | None] = mapped_column(Float)


class HistoricalTemperatureMetrics(Base):
    """One real sensor/reading temperature sample from a monitor cycle."""

    __tablename__ = "historical_temperature_metrics"
    __table_args__ = (
        UniqueConstraint("timestamp", "sensor_id", name="uq_history_temperature_sensor"),
        Index("ix_history_temperature_sensor_timestamp", "sensor_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sensor_id: Mapped[str] = mapped_column(String(512), nullable=False)
    sensor_name: Mapped[str] = mapped_column(String(256), nullable=False)
    sensor_label: Mapped[str | None] = mapped_column(String(256))
    reading_index: Mapped[int] = mapped_column(Integer, nullable=False)
    temperature_celsius: Mapped[float] = mapped_column(Float, nullable=False)


class AlertEvent(Base):
    """One persisted alert-state transition."""

    __tablename__ = "alert_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    previous_severity: Mapped[str | None] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    utilization_percent: Mapped[float] = mapped_column(Float, nullable=False)
    configured_threshold_percent: Mapped[float] = mapped_column(Float, nullable=False)
    device: Mapped[str | None] = mapped_column(String(512))
    mountpoint: Mapped[str | None] = mapped_column(String(512))
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sensor_id: Mapped[str | None] = mapped_column(String(512))
    sensor_name: Mapped[str | None] = mapped_column(String(256))
    sensor_label: Mapped[str | None] = mapped_column(String(256))
    temperature_celsius: Mapped[float | None] = mapped_column(Float)
    configured_threshold_celsius: Mapped[float | None] = mapped_column(Float)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertThresholdSettings(Base):
    """Persisted resource thresholds; row ID 1 is the application setting."""

    __tablename__ = "alert_threshold_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    cpu_warning_percent: Mapped[float] = mapped_column(Float, nullable=False)
    cpu_critical_percent: Mapped[float] = mapped_column(Float, nullable=False)
    ram_warning_percent: Mapped[float] = mapped_column(Float, nullable=False)
    ram_critical_percent: Mapped[float] = mapped_column(Float, nullable=False)
    disk_warning_percent: Mapped[float] = mapped_column(Float, nullable=False)
    disk_critical_percent: Mapped[float] = mapped_column(Float, nullable=False)
    temperature_warning_celsius: Mapped[float] = mapped_column(
        Float, nullable=False, default=80.0
    )
    temperature_critical_celsius: Mapped[float] = mapped_column(
        Float, nullable=False, default=90.0
    )
    battery_warning_percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=20.0
    )
    battery_critical_percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )


class AlertCurrentState(Base):
    """Latest alert state, independent of whether history events are cleared."""

    __tablename__ = "alert_current_states"

    state_key: Mapped[str] = mapped_column(String(600), primary_key=True)
    resource: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    utilization_percent: Mapped[float] = mapped_column(Float, nullable=False)
    device: Mapped[str | None] = mapped_column(String(512))
    mountpoint: Mapped[str | None] = mapped_column(String(512))
    total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    free_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sensor_id: Mapped[str | None] = mapped_column(String(512))
    sensor_name: Mapped[str | None] = mapped_column(String(256))
    sensor_label: Mapped[str | None] = mapped_column(String(256))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class AnomalySettings(Base):
    """Persisted anomaly detection configuration; row ID 1 is the active configuration."""

    __tablename__ = "anomaly_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    min_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    z_score_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False, default=60)


class AnomalyEvent(Base):
    """Persisted resource anomaly event."""

    __tablename__ = "anomaly_events"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    resource: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, nullable=False)
    standard_deviation: Mapped[float] = mapped_column(Float, nullable=False)
    z_score: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, index=True
    )


class HistoricalPrediction(Base):
    """Persisted forecast for historical comparison against actual telemetry."""

    __tablename__ = "historical_predictions"
    __table_args__ = (
        Index("ix_predictions_metric_horizon_target", "metric", "horizon", "target_timestamp"),
        Index("ix_predictions_status_target", "evaluation_status", "target_timestamp"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    prediction_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    resource: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    horizon_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    target_timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    current_value: Mapped[float | None] = mapped_column(Float)
    predicted_value: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[float | None] = mapped_column(Float)
    upper_bound: Mapped[float | None] = mapped_column(Float)
    confidence_score: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str] = mapped_column(
        String(64), nullable=False, default="exponentially_weighted_linear_regression"
    )
    actual_value: Mapped[float | None] = mapped_column(Float)
    absolute_error: Mapped[float | None] = mapped_column(Float)
    percentage_error: Mapped[float | None] = mapped_column(Float)
    evaluation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

