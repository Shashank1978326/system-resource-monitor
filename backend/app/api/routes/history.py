"""Historical monitoring data endpoints."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from app.schemas.monitoring import (
    HistoricalBatteryGraphPoint,
    HistoricalGraphPoint,
    HistoricalGraphResponse,
    HistoricalMetricsResponse,
    HistoricalNetworkInterfacesResponse,
    HistoricalTemperatureSensorResponse,
    HistoricalTemperatureSensorsResponse,
    HistoryStatsResponse,
    HistorySummaryResponse,
)
from app.services.history_service import HistoryStorageError, history_service

router = APIRouter(prefix="/api/history", tags=["history"])

_TIME_RANGES_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "6h": 6 * 60 * 60,
    "12h": 12 * 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
}
_INTERVALS_SECONDS = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
}
_METRIC_UNITS = {
    "cpu": "percent",
    "memory": "percent",
    "disk": "percent",
    "network_download": "bytes_per_second",
    "network_upload": "bytes_per_second",
    "disk_read": "bytes",
    "disk_write": "bytes",
    "disk_read_speed": "bytes_per_second",
    "disk_write_speed": "bytes_per_second",
    "network_interface_download": "bytes_per_second",
    "network_interface_upload": "bytes_per_second",
    "temperature": "celsius",
    "battery": "percent",
}
_MAX_GRAPH_DATA_POINTS = 10_000


def _validate_time_range(
    start_time: datetime | None, end_time: datetime | None
) -> None:
    if start_time is None or end_time is None:
        return
    normalized_start = (
        start_time.replace(tzinfo=None)
        if start_time.tzinfo is None
        else start_time.astimezone(timezone.utc).replace(tzinfo=None)
    )
    normalized_end = (
        end_time.replace(tzinfo=None)
        if end_time.tzinfo is None
        else end_time.astimezone(timezone.utc).replace(tzinfo=None)
    )
    if normalized_start > normalized_end:
        raise HTTPException(
            status_code=422, detail="start_time must be earlier than or equal to end_time"
        )


def _storage_error_response() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Historical data storage is temporarily unavailable",
    )


@router.get(
    "/graph",
    response_model=HistoricalGraphResponse,
    summary="Retrieve averaged historical metrics for graphing",
)
def read_history_graph(
    metric: str = Query(...),
    range: str = Query(...),
    interval: str = Query(...),
    interface: str | None = Query(default=None, min_length=1, max_length=512),
    sensor_id: str | None = Query(default=None, min_length=1, max_length=512),
) -> HistoricalGraphResponse:
    """Return bounded, chronologically ordered SQL-aggregated metric buckets."""
    if metric not in _METRIC_UNITS:
        raise HTTPException(
            status_code=422,
            detail=f"metric must be one of: {', '.join(_METRIC_UNITS)}",
        )
    if range not in _TIME_RANGES_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"range must be one of: {', '.join(_TIME_RANGES_SECONDS)}",
        )
    if interval not in _INTERVALS_SECONDS:
        raise HTTPException(
            status_code=422,
            detail=f"interval must be one of: {', '.join(_INTERVALS_SECONDS)}",
        )

    range_seconds = _TIME_RANGES_SECONDS[range]
    interval_seconds = _INTERVALS_SECONDS[interval]
    estimated_points = (range_seconds + interval_seconds - 1) // interval_seconds + 1
    if estimated_points > _MAX_GRAPH_DATA_POINTS:
        raise HTTPException(
            status_code=422,
            detail=(
                "The requested range and interval may return too many data points; "
                f"the maximum is {_MAX_GRAPH_DATA_POINTS}"
            ),
        )

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(seconds=range_seconds)
    try:
        if metric == "temperature":
            if interface is not None:
                raise HTTPException(
                    status_code=422,
                    detail="interface is only valid for per-interface network metrics",
                )
            if sensor_id is None:
                raise HTTPException(
                    status_code=422,
                    detail="sensor_id is required for temperature metrics",
                )
            sensors = history_service.get_temperature_sensors()
            if not any(item[0] == sensor_id for item in sensors):
                raise HTTPException(
                    status_code=404, detail="No historical data for this sensor"
                )
            averages = history_service.get_temperature_averages(
                sensor_id, start_time, end_time, interval_seconds
            )
        elif metric == "battery":
            if interface is not None or sensor_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail="interface and sensor_id are not valid for battery metrics",
                )
            battery_averages = history_service.get_battery_averages(
                start_time, end_time, interval_seconds
            )
            return HistoricalGraphResponse(
                metric=metric,
                time_range=range,
                interval=interval,
                unit=_METRIC_UNITS[metric],
                data_points=[
                    HistoricalBatteryGraphPoint(
                        timestamp=datetime.fromtimestamp(
                            bucket_timestamp, timezone.utc
                        ).isoformat().replace("+00:00", "Z"),
                        value=average_percentage,
                        battery_availability=availability,
                        charging_state=charging_state,
                        power_plugged=power_plugged,
                        status_timestamp=(
                            (
                                status_timestamp
                                if status_timestamp.tzinfo is not None
                                else status_timestamp.replace(tzinfo=timezone.utc)
                            )
                            .isoformat()
                            .replace("+00:00", "Z")
                            if status_timestamp is not None
                            else None
                        ),
                    )
                    for (
                        bucket_timestamp,
                        average_percentage,
                        charging_state,
                        power_plugged,
                        availability,
                        status_timestamp,
                    ) in battery_averages
                ],
            )
        elif metric in {"network_interface_download", "network_interface_upload"}:
            if sensor_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail="sensor_id is only valid for temperature metrics",
                )
            if interface is None:
                raise HTTPException(
                    status_code=422,
                    detail="interface is required for per-interface network metrics",
                )
            interface_names = history_service.get_network_interface_names()
            if interface not in interface_names:
                raise HTTPException(
                    status_code=404, detail="No historical data for this interface"
                )
            averages = history_service.get_network_interface_metric_averages(
                interface, metric, start_time, end_time, interval_seconds
            )
        else:
            if interface is not None or sensor_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail="interface and sensor_id are only valid for selected metrics",
                )
            averages = history_service.get_metric_averages(
                metric, start_time, end_time, interval_seconds
            )
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc

    return HistoricalGraphResponse(
        metric=metric,
        time_range=range,
        interval=interval,
        unit=_METRIC_UNITS[metric],
        data_points=[
            HistoricalGraphPoint(
                timestamp=datetime.fromtimestamp(
                    bucket_timestamp, timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                value=average_value,
            )
            for bucket_timestamp, average_value in averages
        ],
    )


@router.get(
    "/interfaces",
    response_model=HistoricalNetworkInterfacesResponse,
    summary="List interfaces with historical traffic",
)
def read_historical_network_interfaces() -> HistoricalNetworkInterfacesResponse:
    """Return names that can be selected for per-interface historical graphs."""
    try:
        interfaces = history_service.get_network_interface_names()
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc
    return HistoricalNetworkInterfacesResponse(interfaces=interfaces)


@router.get(
    "/temperature-sensors",
    response_model=HistoricalTemperatureSensorsResponse,
    summary="List sensors with historical temperature readings",
)
def read_historical_temperature_sensors() -> HistoricalTemperatureSensorsResponse:
    """Return distinct sensor readings available in retained history."""
    try:
        sensors = history_service.get_temperature_sensors()
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc
    return HistoricalTemperatureSensorsResponse(
        sensors=[
            HistoricalTemperatureSensorResponse(
                sensor_id=sensor_id,
                sensor_name=sensor_name,
                label=label,
            )
            for sensor_id, sensor_name, label in sensors
        ]
    )


@router.get(
    "",
    response_model=list[HistoricalMetricsResponse],
    summary="Retrieve historical monitoring records",
)
def read_history(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[HistoricalMetricsResponse]:
    """Return a chronologically ordered page of history records."""
    _validate_time_range(start_time, end_time)
    try:
        return history_service.get_records(start_time, end_time, limit, offset)
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc


@router.get(
    "/summary",
    response_model=HistorySummaryResponse,
    summary="Summarize historical monitoring data",
)
def read_history_summary(
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> HistorySummaryResponse:
    """Return SQL-aggregated statistics for retained history."""
    _validate_time_range(start_time, end_time)
    try:
        summary = history_service.get_summary(start_time, end_time)
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc
    return HistorySummaryResponse(
        average_cpu_utilization_percent=summary["average_cpu"],
        maximum_cpu_utilization_percent=summary["maximum_cpu"],
        average_ram_utilization_percent=summary["average_ram"],
        maximum_ram_utilization_percent=summary["maximum_ram"],
        average_download_speed=summary["average_download"],
        maximum_download_speed=summary["maximum_download"],
        average_upload_speed=summary["average_upload"],
        maximum_upload_speed=summary["maximum_upload"],
        total_record_count=summary["total_record_count"],
        earliest_timestamp=summary["earliest_timestamp"],
        latest_timestamp=summary["latest_timestamp"],
    )


@router.get(
    "/stats",
    response_model=HistoryStatsResponse,
    summary="Report historical database statistics",
)
def read_history_stats() -> HistoryStatsResponse:
    """Return retained record counts, timestamp range, and SQLite file size."""
    try:
        statistics = history_service.get_stats()
    except HistoryStorageError as exc:
        raise _storage_error_response() from exc
    return HistoryStatsResponse(
        total_historical_records=statistics["total_records"],
        earliest_timestamp=statistics["earliest_timestamp"],
        latest_timestamp=statistics["latest_timestamp"],
        retention_period_days=statistics["retention_days"],
        database_file_size_bytes=statistics["database_size_bytes"],
    )
