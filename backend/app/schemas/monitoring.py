"""Pydantic response schemas for system monitoring APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CpuFrequencyResponse(BaseModel):
    """CPU clock frequency values in megahertz when available."""

    model_config = ConfigDict(extra="forbid")

    current_mhz: float | None
    min_mhz: float | None
    max_mhz: float | None


class SystemInfoResponse(BaseModel):
    """Host operating system, processor, and uptime information."""

    model_config = ConfigDict(extra="forbid")

    hostname: str
    machine_name: str
    operating_system: str
    os_version: str
    os_release: str
    architecture: str
    processor: str | None
    cpu_architecture: str
    physical_cores: int | None
    logical_cores: int | None
    cpu_frequency: CpuFrequencyResponse
    boot_time: str | None
    uptime_seconds: float | None
    uptime_readable: str | None
    python_version: str
    application_platform: str


class TemperatureSensorReadingResponse(BaseModel):
    """One hardware temperature sensor reading and optional thresholds."""

    model_config = ConfigDict(extra="forbid")

    sensor_name: str
    label: str | None
    sensor_id: str
    reading_index: int
    current_celsius: float | None
    high_celsius: float | None
    critical_celsius: float | None
    device: str | None = None


class TemperatureResponse(BaseModel):
    """Platform temperature-sensor availability and real readings."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable", "unsupported"]
    platform: str
    sensors: list[TemperatureSensorReadingResponse]
    message: str | None


class BatteryResponse(BaseModel):
    """Platform battery availability and real battery readings."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable", "unsupported"]
    platform: str
    percentage: float | None
    charging_state: Literal["charging", "discharging", "not_charging", "unknown"]
    power_plugged: bool | None
    remaining_seconds: int | None
    remaining_time: str | None
    message: str


class GpuDeviceInfoResponse(BaseModel):
    """Public hardware identity and optional monitoring capability."""

    model_config = ConfigDict(extra="forbid")

    device_index: int
    manufacturer: str
    model: str | None
    total_memory_bytes: int | None = None
    driver_version: str | None = None
    monitoring_supported: bool = False


class GpuInfoResponse(BaseModel):
    """GPU hardware detection result without utilization telemetry."""

    model_config = ConfigDict(extra="forbid")

    supported_gpu_detected: bool
    devices: list[GpuDeviceInfoResponse]
    monitoring_available: bool
    status: Literal[
        "available",
        "unsupported",
        "library_unavailable",
        "initialization_error",
        "device_info_unavailable",
        "partial",
        "no_gpu",
        "monitoring_unsupported",
        "detection_error",
    ]
    message: str | None


class GpuUsageDeviceResponse(BaseModel):
    """One GPU's latest provider measurements, when available."""

    model_config = ConfigDict(extra="forbid")

    device_index: int
    name: str | None
    manufacturer: str | None = None
    available: bool
    status: Literal["available", "partial", "device_error", "unsupported"]
    monitoring_supported: bool = True
    gpu_utilization_percent: float | None
    temperature_celsius: float | None = None
    power_usage_watts: float | None = None
    power_limit_watts: float | None = None
    memory_used_mb: float | None
    memory_free_mb: float | None
    memory_total_mb: float | None
    memory_utilization_percent: float | None


class GpuUsageResponse(BaseModel):
    """Latest request-driven GPU sampling result across detected adapters."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    monitoring_available: bool
    status: Literal[
        "available",
        "partial",
        "unsupported",
        "library_unavailable",
        "initialization_error",
        "device_error",
        "no_gpu",
        "monitoring_unsupported",
    ]
    devices: list[GpuUsageDeviceResponse]
    message: str | None


class CpuResponse(BaseModel):
    """Current CPU utilization and processor capacity."""

    model_config = ConfigDict(extra="forbid")

    cpu_usage_percent: float | None
    per_core_usage: list[float] | None
    physical_cores: int | None
    logical_cores: int | None
    frequency_mhz: float | None
    min_frequency_mhz: float | None
    max_frequency_mhz: float | None
    usage_status: str | None


class MemoryResponse(BaseModel):
    """Current physical and swap memory values in bytes."""

    model_config = ConfigDict(extra="forbid")

    total_bytes: int | None
    used_bytes: int | None
    available_bytes: int | None
    free_bytes: int | None
    usage_percent: float | None
    cached_bytes: int | None
    swap_total_bytes: int | None
    swap_used_bytes: int | None
    swap_percent: float | None


class DiskPartitionResponse(BaseModel):
    """Capacity information for one accessible mounted partition."""

    model_config = ConfigDict(extra="forbid")

    device: str
    mountpoint: str
    filesystem: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float


class DiskIoResponse(BaseModel):
    """Cumulative disk I/O counters and read throughput from the latest cycle."""

    model_config = ConfigDict(extra="forbid")

    read_bytes: int | None
    write_bytes: int | None
    read_count: int | None
    write_count: int | None
    read_speed_bytes_per_sec: float | None = None
    read_speed_mb_per_sec: float | None = None
    read_speed_status: Literal["available", "initializing", "unavailable"] = "unavailable"
    write_speed_bytes_per_sec: float | None = None
    write_speed_mb_per_sec: float | None = None
    write_speed_status: Literal["available", "initializing", "unavailable"] = "unavailable"


class DiskIoSpeedResponse(BaseModel):
    """Read/write counters and interval-based throughput from the latest snapshot."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    total_bytes_read: int | None
    read_operations: int | None
    read_speed_bytes_per_sec: float | None
    read_speed_mb_per_sec: float | None
    available: bool
    status: Literal["available", "initializing", "unavailable"]
    message: str | None
    total_bytes_written: int | None = None
    write_operations: int | None = None
    write_speed_bytes_per_sec: float | None = None
    write_speed_mb_per_sec: float | None = None
    write_available: bool = False
    write_status: Literal["available", "initializing", "unavailable"] = "unavailable"
    write_message: str | None = None


class DiskResponse(BaseModel):
    """Mounted partition capacities and cumulative disk I/O."""

    model_config = ConfigDict(extra="forbid")

    partitions: list[DiskPartitionResponse]
    io: DiskIoResponse


class NetworkInterfaceResponse(BaseModel):
    """Address, link, and cumulative counter information per interface."""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_up: bool | None
    speed_mbps: float | None
    mtu: int | None
    addresses: list[str]
    bytes_received: int | None
    bytes_sent: int | None
    packets_received: int | None
    packets_sent: int | None
    download_speed_bytes_per_sec: float | None = None
    download_speed_mb_per_sec: float | None = None
    download_available: bool = False
    download_status: Literal["available", "initializing", "unavailable"] = "unavailable"
    upload_speed_bytes_per_sec: float | None = None
    upload_speed_mb_per_sec: float | None = None
    upload_available: bool = False
    upload_status: Literal["available", "initializing", "unavailable"] = "unavailable"


class NetworkInterfaceTrafficResponse(BaseModel):
    """Per-interface counters and independently sampled transfer speeds."""

    model_config = ConfigDict(extra="forbid")

    name: str
    download_speed_bytes_per_sec: float | None
    download_speed_mb_per_sec: float | None
    upload_speed_bytes_per_sec: float | None
    upload_speed_mb_per_sec: float | None
    bytes_received: int | None
    bytes_sent: int | None
    packets_received: int | None
    packets_sent: int | None
    download_available: bool
    download_status: Literal["available", "initializing", "unavailable"]
    upload_available: bool
    upload_status: Literal["available", "initializing", "unavailable"]


class NetworkInterfaceTrafficListResponse(BaseModel):
    """Traffic sample for all interfaces from one collector cycle."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    interfaces: list[NetworkInterfaceTrafficResponse]


class NetworkInterfaceDetailsResponse(BaseModel):
    """Publicly useful addressing and link properties for one interface."""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_up: bool | None = None
    mac_address: str | None = None
    ipv4_address: str | None = None
    ipv4_netmask: str | None = None
    ipv6_address: str | None = None
    ipv6_netmask: str | None = None
    mtu: int | None = None
    speed_mbps: float | None = None
    is_loopback: bool | None = None
    is_virtual: bool | None = None


class NetworkInterfacesResponse(BaseModel):
    """Detected interfaces and the properties available for each."""

    model_config = ConfigDict(extra="forbid")

    interfaces: list[NetworkInterfaceDetailsResponse]


class NetworkResponse(BaseModel):
    """Aggregate network counters and interval-based transfer speeds."""

    model_config = ConfigDict(extra="forbid")

    bytes_received: int | None
    bytes_sent: int | None
    packets_received: int | None
    packets_sent: int | None
    download_speed_bytes_per_sec: float | None
    upload_speed_bytes_per_sec: float | None
    download_speed_mbps: float | None
    upload_speed_mbps: float | None
    interfaces: list[NetworkInterfaceResponse]


class MonitoringSnapshotResponse(BaseModel):
    """Latest combined metrics collected by the background monitor."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    cpu: CpuResponse
    memory: MemoryResponse
    disk: DiskResponse
    network: NetworkResponse
    collection_status: str
    metric_errors: dict[str, str]


class MonitoringStatusResponse(BaseModel):
    """Background collector state and cycle counters."""

    model_config = ConfigDict(extra="forbid")

    running: bool
    interval_seconds: float
    last_successful_collection: str | None
    successful_cycles: int
    failed_cycles: int
    started_at: str | None
    collector_status: str


class CpuAlertStatusResponse(BaseModel):
    """Current CPU alert level and the last valid CPU measurement."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    cpu_usage_percent: float | None
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str | None


class CpuAlertEventResponse(BaseModel):
    """A CPU alert state transition or recovery event."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["cpu"] = "cpu"
    previous_status: Literal["Normal", "Warning", "Critical"]
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    cpu_usage_percent: float
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str
    message: str
    id: int | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None


class ResourceAlertStatusResponse(BaseModel):
    """Current RAM alert level and the last valid measurement."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    usage_percent: float | None
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str | None


class RamAlertEventResponse(BaseModel):
    """A RAM alert state transition or recovery event."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["ram"] = "ram"
    previous_status: Literal["Normal", "Warning", "Critical"]
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    usage_percent: float
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str
    message: str
    id: int | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None


class DiskPartitionAlertStatusResponse(BaseModel):
    """Latest valid alert state and capacity for one mounted partition."""

    model_config = ConfigDict(extra="forbid")

    device: str
    mountpoint: str
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float
    timestamp: str


class DiskAlertStatusResponse(BaseModel):
    """Aggregate disk state and the last valid state of each partition."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str | None
    partitions: list[DiskPartitionAlertStatusResponse]


class DiskAlertEventResponse(BaseModel):
    """A disk partition alert transition or recovery event."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["disk"] = "disk"
    previous_status: Literal["Normal", "Warning", "Critical"]
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    device: str
    mountpoint: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    usage_percent: float
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str
    message: str
    id: int | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None


class TemperatureSensorAlertStatusResponse(BaseModel):
    """Current valid sensor reading and its independently tracked alert level."""

    model_config = ConfigDict(extra="forbid")

    sensor_id: str
    sensor_name: str
    label: str | None
    current_celsius: float
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    warning_threshold_celsius: float
    critical_threshold_celsius: float
    timestamp: str


class TemperatureAlertEventResponse(BaseModel):
    """A temperature sensor transition or recovery event."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["temperature"] = "temperature"
    sensor_id: str
    sensor_name: str
    sensor_label: str | None
    current_celsius: float
    configured_threshold_celsius: float
    warning_threshold_celsius: float
    critical_threshold_celsius: float
    previous_status: Literal["Normal", "Warning", "Critical"]
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    timestamp: str
    message: str
    id: int | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None


class TemperatureAlertsResponse(BaseModel):
    """Hardware sensor availability and live per-sensor alert state."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable", "unsupported"]
    platform: str
    message: str | None
    warning_threshold_celsius: float
    critical_threshold_celsius: float
    sensors: list[TemperatureSensorAlertStatusResponse]
    recent_events: list[TemperatureAlertEventResponse]


class BatteryAlertStatusResponse(BaseModel):
    """Platform battery availability, current level, and alert level."""

    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "unavailable", "unsupported"]
    platform: str
    message: str | None
    percentage: float | None
    charging_state: Literal["charging", "discharging", "not_charging", "unknown"] | None
    power_plugged: bool | None
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str | None


class BatteryAlertEventResponse(BaseModel):
    """A battery alert state transition or recovery event."""

    model_config = ConfigDict(extra="forbid")

    resource: Literal["battery"] = "battery"
    previous_status: Literal["Normal", "Warning", "Critical"]
    status: Literal["Normal", "Warning", "Critical"]
    severity: Literal["Normal", "Warning", "Critical"]
    percentage: float
    configured_threshold_percent: float
    warning_threshold_percent: float
    critical_threshold_percent: float
    timestamp: str
    message: str
    id: int | None = None
    acknowledged: bool = False
    acknowledged_at: str | None = None


class BatteryAlertsResponse(BaseModel):
    """Current battery alert state and recent transitions."""

    model_config = ConfigDict(extra="forbid")

    status: BatteryAlertStatusResponse
    recent_events: list[BatteryAlertEventResponse]


class AlertThresholdsResponse(BaseModel):
    """CPU, RAM, disk, and temperature alert thresholds."""

    model_config = ConfigDict(extra="forbid")

    cpu_warning_threshold_percent: float
    cpu_critical_threshold_percent: float
    ram_warning_threshold_percent: float
    ram_critical_threshold_percent: float
    disk_warning_threshold_percent: float
    disk_critical_threshold_percent: float
    temperature_warning_threshold_celsius: float = Field(
        default=80.0, strict=True, ge=0, allow_inf_nan=False
    )
    temperature_critical_threshold_celsius: float = Field(
        default=90.0, strict=True, ge=0, allow_inf_nan=False
    )
    battery_warning_threshold_percent: float = Field(
        default=20.0, strict=True, ge=0, le=100, allow_inf_nan=False
    )
    battery_critical_threshold_percent: float = Field(
        default=10.0, strict=True, ge=0, le=100, allow_inf_nan=False
    )


class AlertThresholdsUpdateRequest(AlertThresholdsResponse):
    """Validated replacement thresholds for all monitored resources."""

    @model_validator(mode="after")
    def warning_must_precede_critical(self) -> "AlertThresholdsUpdateRequest":
        for resource in ("cpu", "ram", "disk"):
            warning = getattr(self, f"{resource}_warning_threshold_percent")
            critical = getattr(self, f"{resource}_critical_threshold_percent")
            if warning >= critical:
                raise ValueError(
                    f"{resource.upper()} warning threshold must be lower than critical"
                )
        warning = self.temperature_warning_threshold_celsius
        critical = self.temperature_critical_threshold_celsius
        if warning < 0 or critical < 0 or warning >= critical:
            raise ValueError(
                "Temperature warning threshold must be non-negative and lower "
                "than critical"
            )
        battery_warning = self.battery_warning_threshold_percent
        battery_critical = self.battery_critical_threshold_percent
        if (
            battery_warning < 0
            or battery_warning > 100
            or battery_critical < 0
            or battery_critical > 100
            or battery_critical >= battery_warning
        ):
            raise ValueError(
                "Battery critical threshold must be lower than warning threshold, "
                "and both must be between 0 and 100"
            )
        return self

    cpu_warning_threshold_percent: float = Field(ge=1, le=100)
    cpu_critical_threshold_percent: float = Field(ge=1, le=100)
    ram_warning_threshold_percent: float = Field(ge=1, le=100)
    ram_critical_threshold_percent: float = Field(ge=1, le=100)
    disk_warning_threshold_percent: float = Field(ge=1, le=100)
    disk_critical_threshold_percent: float = Field(ge=1, le=100)
    temperature_warning_threshold_celsius: float = Field(
        default=80, strict=True, ge=0, allow_inf_nan=False
    )
    temperature_critical_threshold_celsius: float = Field(
        default=90, strict=True, ge=0, allow_inf_nan=False
    )
    battery_warning_threshold_percent: float = Field(
        default=20, strict=True, ge=0, le=100, allow_inf_nan=False
    )
    battery_critical_threshold_percent: float = Field(
        default=10, strict=True, ge=0, le=100, allow_inf_nan=False
    )


class AlertHistoryEventResponse(BaseModel):
    """A persisted alert event including acknowledgement and disk details."""

    model_config = ConfigDict(extra="forbid")

    id: int
    resource: Literal["cpu", "ram", "disk", "temperature", "battery"]
    severity: Literal["Normal", "Warning", "Critical"]
    previous_severity: Literal["Normal", "Warning", "Critical"] | None
    message: str
    utilization_percent: float
    configured_threshold_percent: float
    device: str | None
    mountpoint: str | None
    total_bytes: int | None
    used_bytes: int | None
    free_bytes: int | None
    sensor_id: str | None = None
    sensor_name: str | None = None
    sensor_label: str | None = None
    temperature_celsius: float | None = None
    configured_threshold_celsius: float | None = None
    timestamp: str
    acknowledged: bool
    acknowledged_at: str | None


class AlertHistoryResponse(BaseModel):
    """Paginated alert events and total matching record count."""

    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    events: list[AlertHistoryEventResponse]


class RamAlertsResourceResponse(BaseModel):
    """Current RAM alert status and recent transitions."""

    model_config = ConfigDict(extra="forbid")

    status: ResourceAlertStatusResponse
    recent_events: list[RamAlertEventResponse]


class DiskAlertsResourceResponse(BaseModel):
    """Current per-partition disk state and recent transitions."""

    model_config = ConfigDict(extra="forbid")

    status: DiskAlertStatusResponse
    recent_events: list[DiskAlertEventResponse]


class CpuAlertsResponse(BaseModel):
    """CPU-compatible alert response extended with RAM, disk, temperature, and battery alerts."""

    model_config = ConfigDict(extra="forbid")

    status: CpuAlertStatusResponse
    recent_events: list[CpuAlertEventResponse]
    ram: RamAlertsResourceResponse
    disk: DiskAlertsResourceResponse
    temperature: TemperatureAlertsResponse
    battery: BatteryAlertsResponse | None = None


class AlertsStatusResponse(CpuAlertStatusResponse):
    """CPU-compatible status response with RAM, disk, temperature, and battery status added."""

    ram: ResourceAlertStatusResponse
    disk: DiskAlertStatusResponse
    temperature: TemperatureAlertsResponse
    battery: BatteryAlertStatusResponse | None = None


class ProcessInfoResponse(BaseModel):
    """Public, non-sensitive resource information about one process."""

    model_config = ConfigDict(extra="forbid")

    pid: int
    name: str | None
    status: str | None
    cpu_percent: float | None
    memory_mb: float | None
    memory_percent: float | None


class ProcessDetailResponse(ProcessInfoResponse):
    """Detailed process metrics that are only available for one process."""

    thread_count: int | None
    create_time: str | None
    username: str | None


class ProcessListResponse(BaseModel):
    """A bounded list of matching processes and the total matching count."""

    model_config = ConfigDict(extra="forbid")

    total_processes: int
    processes: list[ProcessInfoResponse]
    total_process_count: int
    top_cpu_processes: list[ProcessInfoResponse]
    top_ram_processes: list[ProcessInfoResponse]


class HistoricalMetricsResponse(BaseModel):
    """One persisted monitoring collection cycle."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    timestamp: datetime
    cpu_utilization_percent: float | None
    ram_utilization_percent: float | None
    ram_used_bytes: int | None
    ram_available_bytes: int | None
    disk_read_bytes: int | None
    disk_write_bytes: int | None
    disk_read_speed: float | None = None
    disk_write_speed: float | None = None
    disk_utilization_percent: float | None
    network_download_speed: float | None
    network_upload_speed: float | None
    network_bytes_received: int | None
    network_bytes_sent: int | None
    battery_availability: Literal["available", "unavailable", "unsupported"] | None = None
    battery_percentage: float | None = None
    battery_charging_state: Literal[
        "charging", "discharging", "not_charging", "unknown"
    ] | None = None
    battery_power_plugged: bool | None = None


class HistorySummaryResponse(BaseModel):
    """SQL-aggregated statistics for historical monitoring records."""

    model_config = ConfigDict(extra="forbid")

    average_cpu_utilization_percent: float | None
    maximum_cpu_utilization_percent: float | None
    average_ram_utilization_percent: float | None
    maximum_ram_utilization_percent: float | None
    average_download_speed: float | None
    maximum_download_speed: float | None
    average_upload_speed: float | None
    maximum_upload_speed: float | None
    total_record_count: int
    earliest_timestamp: datetime | None
    latest_timestamp: datetime | None


class HistoryStatsResponse(BaseModel):
    """Database size, retention, and timestamp coverage information."""

    model_config = ConfigDict(extra="forbid")

    total_historical_records: int
    earliest_timestamp: datetime | None
    latest_timestamp: datetime | None
    retention_period_days: int
    database_file_size_bytes: int


class HistoricalGraphPoint(BaseModel):
    """One UTC timestamped, aggregated value in a historical graph."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    value: float | None


class HistoricalBatteryGraphPoint(HistoricalGraphPoint):
    """Battery percentage bucket with its latest recorded state."""

    battery_availability: Literal["available", "unavailable", "unsupported"] | None
    charging_state: Literal[
        "charging", "discharging", "not_charging", "unknown"
    ] | None
    power_plugged: bool | None
    status_timestamp: str | None


class HistoricalGraphResponse(BaseModel):
    """Aggregated history for one metric and a bounded time range."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    time_range: str
    interval: str
    unit: str
    data_points: list[HistoricalGraphPoint | HistoricalBatteryGraphPoint]


class HistoricalNetworkInterfacesResponse(BaseModel):
    """Interface names available in retained per-interface history."""

    model_config = ConfigDict(extra="forbid")

    interfaces: list[str]


class HistoricalTemperatureSensorResponse(BaseModel):
    """A distinct sensor reading identity available in history."""

    model_config = ConfigDict(extra="forbid")

    sensor_id: str
    sensor_name: str
    label: str | None


class HistoricalTemperatureSensorsResponse(BaseModel):
    """Sensor identities with retained historical temperature samples."""

    model_config = ConfigDict(extra="forbid")

    sensors: list[HistoricalTemperatureSensorResponse]


class AnomalySettingsResponse(BaseModel):
    """Configuration for statistical resource anomaly detection."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    min_samples: int = Field(default=20, ge=2, le=10000)
    z_score_threshold: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    window_size: int = Field(default=60, ge=2, le=10000)


class AnomalySettingsUpdateRequest(BaseModel):
    """Update payload for anomaly detection settings."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    min_samples: int = Field(default=20, ge=2, le=10000)
    z_score_threshold: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    window_size: int = Field(default=60, ge=2, le=10000)

    @model_validator(mode="after")
    def window_must_exceed_min_samples(self) -> "AnomalySettingsUpdateRequest":
        if self.window_size < self.min_samples:
            raise ValueError("window_size must be greater than or equal to min_samples")
        return self


class AnomalyEventResponse(BaseModel):
    """One detected resource anomaly event."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    resource: str
    metric: str
    actual_value: float
    expected_value: float
    standard_deviation: float
    z_score: float
    severity: Literal["Warning", "Critical"]
    message: str
    timestamp: str


class AnomalyStatusResponse(BaseModel):
    """Live status of the anomaly detection engine."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    monitored_metrics: list[str]
    sample_counts: dict[str, int]
    window_size: int
    min_samples: int
    z_score_threshold: float


class AnomalyOverviewResponse(BaseModel):
    """GET /api/anomalies response containing status, configuration, and recent events."""

    model_config = ConfigDict(extra="forbid")

    status: AnomalyStatusResponse
    configuration: AnomalySettingsResponse
    recent_events: list[AnomalyEventResponse]


class AnomalyHistoryResponse(BaseModel):
    """Paginated anomaly events."""

    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    events: list[AnomalyEventResponse]


class AnomalyTimelinePoint(BaseModel):
    """Aggregated anomaly counts for one time interval."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    warning_count: int
    critical_count: int
    total_count: int


class AnomalyResourceDistribution(BaseModel):
    """Anomaly counts and percentage contribution for one resource category."""

    model_config = ConfigDict(extra="forbid")

    resource: str
    total_count: int
    warning_count: int
    critical_count: int
    percentage: float


class AnomalyMetricAnalysis(BaseModel):
    """Anomaly counts and severity breakdown for one specific metric."""

    model_config = ConfigDict(extra="forbid")

    resource: str
    metric: str
    label: str
    total_count: int
    warning_count: int
    critical_count: int
    percentage: float


class AnomalyAnalyticsResponse(BaseModel):
    """Statistical anomaly analytics: timeline trend, resource distribution, and metric analysis."""

    model_config = ConfigDict(extra="forbid")

    range: str
    start_time: str
    end_time: str
    interval_seconds: int
    total_anomalies: int
    warning_count: int
    critical_count: int
    timeline: list[AnomalyTimelinePoint]
    by_resource: list[AnomalyResourceDistribution]
    by_metric: list[AnomalyMetricAnalysis]
