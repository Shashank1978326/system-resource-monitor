"""Real-time statistical anomaly detection engine for system resource metrics."""

import logging
import math
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.core.config import settings
from app.database.anomaly_repository import AnomalyRepository, AnomalyStorageError
from app.database.connection import database
from app.schemas.monitoring import (
    AnomalyAnalyticsResponse,
    AnomalyEventResponse,
    AnomalyHistoryResponse,
    AnomalyMetricAnalysis,
    AnomalyOverviewResponse,
    AnomalyResourceDistribution,
    AnomalySettingsResponse,
    AnomalySettingsUpdateRequest,
    AnomalyStatusResponse,
    AnomalyTimelinePoint,
    MonitoringSnapshotResponse,
)

_logger = logging.getLogger(__name__)

DEFAULT_ANOMALY_DETECTION_ENABLED = settings.anomaly_detection_enabled
DEFAULT_ANOMALY_MIN_SAMPLES = settings.anomaly_min_samples
DEFAULT_ANOMALY_Z_SCORE_THRESHOLD = settings.anomaly_z_score_threshold
DEFAULT_ANOMALY_WINDOW_SIZE = settings.anomaly_window_size
_RECENT_EVENT_LIMIT = 50


def _normalize_severity(value: str | None) -> Literal["Warning", "Critical"]:
    if not value:
        return "Warning"
    cleaned = str(value).strip().capitalize()
    if cleaned in ("Warning", "Critical"):
        return cleaned  # type: ignore[return-value]
    return "Warning"

MONITORED_METRICS: tuple[tuple[str, str], ...] = (
    ("cpu", "cpu_utilization"),
    ("memory", "memory_utilization"),
    ("disk", "disk_read_throughput"),
    ("disk", "disk_write_throughput"),
    ("network", "network_download_throughput"),
    ("network", "network_upload_throughput"),
)

ANOMALY_TIME_RANGES_SECONDS: dict[str, int] = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
}

ANOMALY_DEFAULT_INTERVALS_SECONDS: dict[str, int] = {
    "1h": 120,
    "6h": 900,
    "24h": 3600,
    "7d": 21600,
    "30d": 86400,
}

METRIC_LABELS: dict[str, str] = {
    "cpu_utilization": "CPU Utilization",
    "memory_utilization": "Memory Utilization",
    "disk_read_throughput": "Disk Read Throughput",
    "disk_write_throughput": "Disk Write Throughput",
    "network_download_throughput": "Network Download",
    "network_upload_throughput": "Network Upload",
}


def _validate_anomaly_settings(
    enabled: bool,
    min_samples: int,
    z_score_threshold: float,
    window_size: int,
) -> tuple[bool, int, float, int]:
    """Validate anomaly configuration values and relationships."""
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    if isinstance(min_samples, bool) or not isinstance(min_samples, int):
        raise ValueError("min_samples must be an integer")
    if isinstance(z_score_threshold, bool) or not isinstance(
        z_score_threshold, (int, float)
    ):
        raise ValueError("z_score_threshold must be a number")
    if isinstance(window_size, bool) or not isinstance(window_size, int):
        raise ValueError("window_size must be an integer")

    z_score = float(z_score_threshold)
    if not math.isfinite(z_score) or z_score <= 0:
        raise ValueError("z_score_threshold must be a positive finite number")
    if min_samples < 2:
        raise ValueError("min_samples must be at least 2")
    if window_size < min_samples:
        raise ValueError("window_size must be greater than or equal to min_samples")
    if window_size > 10000:
        raise ValueError("window_size must not exceed 10000")
    return enabled, min_samples, z_score, window_size


def _calculate_mean_and_stdev(samples: list[float]) -> tuple[float, float]:
    """Calculate sample mean and sample standard deviation safely."""
    n = len(samples)
    if n < 2:
        return (samples[0] if n == 1 else 0.0), 0.0
    mean = sum(samples) / n
    variance = sum((x - mean) ** 2 for x in samples) / (n - 1)
    if variance < 0.0:
        variance = 0.0
    stdev = math.sqrt(variance)
    return mean, stdev


def _format_rate(bytes_per_sec: float) -> str:
    """Format throughput into human-readable transfer rate."""
    if bytes_per_sec >= 1024 * 1024 * 1024:
        return f"{bytes_per_sec / (1024**3):.2f} GB/s"
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024**2):.2f} MB/s"
    if bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.2f} KB/s"
    return f"{bytes_per_sec:.1f} B/s"


def _format_anomaly_message(
    resource: str,
    metric: str,
    actual: float,
    expected: float,
    stdev: float,
    z_score: float,
    severity: str,
) -> str:
    """Generate human-readable anomaly notification copy."""
    metric_label = metric.replace("_", " ").capitalize()
    if "utilization" in metric:
        return (
            f"{severity} anomaly detected in {resource.upper()} {metric_label}: "
            f"measured {actual:.1f}% (baseline {expected:.1f}% ± {stdev:.1f}%, z-score {z_score:.2f})."
        )
    return (
        f"{severity} anomaly detected in {resource.upper()} {metric_label}: "
        f"measured {_format_rate(actual)} (baseline {_format_rate(expected)} ± {_format_rate(stdev)}, z-score {z_score:.2f})."
    )


def _parse_timestamp(value: str) -> datetime:
    """Parse ISO timestamp to UTC datetime."""
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


class AnomalyService:
    """In-memory rolling statistical anomaly detection engine."""

    def __init__(
        self,
        enabled: bool = DEFAULT_ANOMALY_DETECTION_ENABLED,
        min_samples: int = DEFAULT_ANOMALY_MIN_SAMPLES,
        z_score_threshold: float = DEFAULT_ANOMALY_Z_SCORE_THRESHOLD,
        window_size: int = DEFAULT_ANOMALY_WINDOW_SIZE,
        repository: AnomalyRepository | None = None,
    ) -> None:
        enabled, min_samples, z_score_threshold, window_size = (
            _validate_anomaly_settings(
                enabled, min_samples, z_score_threshold, window_size
            )
        )
        self.enabled = enabled
        self.min_samples = min_samples
        self.z_score_threshold = z_score_threshold
        self.window_size = window_size
        self._repository = repository
        self._lock = threading.RLock()
        self._baselines: dict[str, deque[float]] = {
            metric: deque(maxlen=self.window_size)
            for _, metric in MONITORED_METRICS
        }
        self._is_anomalous: dict[str, bool] = {
            metric: False for _, metric in MONITORED_METRICS
        }
        self._current_severity: dict[str, str | None] = {
            metric: None for _, metric in MONITORED_METRICS
        }
        self._recent_events: deque[AnomalyEventResponse] = deque(
            maxlen=_RECENT_EVENT_LIMIT
        )

    def process_snapshot(
        self, snapshot: MonitoringSnapshotResponse
    ) -> list[AnomalyEventResponse]:
        """Evaluate real measurements across all monitored metrics from one snapshot."""
        with self._lock:
            if not self.enabled:
                return []

        timestamp = snapshot.timestamp
        events: list[AnomalyEventResponse] = []
        metrics_data = [
            ("cpu", "cpu_utilization", snapshot.cpu.cpu_usage_percent),
            ("memory", "memory_utilization", snapshot.memory.usage_percent),
            (
                "disk",
                "disk_read_throughput",
                snapshot.disk.io.read_speed_bytes_per_sec,
            ),
            (
                "disk",
                "disk_write_throughput",
                snapshot.disk.io.write_speed_bytes_per_sec,
            ),
            (
                "network",
                "network_download_throughput",
                snapshot.network.download_speed_bytes_per_sec,
            ),
            (
                "network",
                "network_upload_throughput",
                snapshot.network.upload_speed_bytes_per_sec,
            ),
        ]
        for resource, metric, value in metrics_data:
            event = self.process_metric_sample(resource, metric, value, timestamp)
            if event is not None:
                events.append(event)
        return events

    def process_metric_sample(
        self,
        resource: str,
        metric: str,
        value: float | None,
        timestamp: str,
    ) -> AnomalyEventResponse | None:
        """Process one metric sample: update baseline and detect statistical anomaly."""
        if value is None or isinstance(value, bool):
            return None
        try:
            val = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(val) or val < 0:
            return None

        with self._lock:
            if not self.enabled:
                return None

            baseline = self._baselines.setdefault(
                metric, deque(maxlen=self.window_size)
            )

            # Insufficient samples: collect baseline data without triggering false alarms
            if len(baseline) < self.min_samples:
                baseline.append(val)
                return None

            mean, stdev = _calculate_mean_and_stdev(list(baseline))

            # Handle zero or near-zero standard deviation safely while avoiding false alarms on tiny fluctuations
            min_stdev = 1.0 if "utilization" in metric else 1024.0
            effective_stdev = max(stdev, min_stdev)
            z_score = (val - mean) / effective_stdev

            # Check if reading exceeds z-score threshold
            if z_score >= self.z_score_threshold:
                severity: str = (
                    "Critical"
                    if z_score >= self.z_score_threshold * 1.5
                    else "Warning"
                )

                # Duplicate prevention:
                # Do not emit duplicate events while remaining in same anomaly severity
                prev_anomalous = self._is_anomalous.get(metric, False)
                prev_severity = self._current_severity.get(metric)

                if prev_anomalous and prev_severity == severity:
                    return None
                if prev_anomalous and prev_severity == "Critical":
                    return None

                self._is_anomalous[metric] = True
                self._current_severity[metric] = severity

                message = _format_anomaly_message(
                    resource, metric, val, mean, stdev, z_score, severity
                )

                event = AnomalyEventResponse(
                    resource=resource,
                    metric=metric,
                    actual_value=round(val, 4),
                    expected_value=round(mean, 4),
                    standard_deviation=round(stdev, 4),
                    z_score=round(z_score, 4),
                    severity=severity,
                    message=message,
                    timestamp=timestamp,
                )

                if self._repository is not None:
                    try:
                        stored = self._repository.insert_event(
                            resource=resource,
                            metric=metric,
                            actual_value=val,
                            expected_value=mean,
                            standard_deviation=stdev,
                            z_score=z_score,
                            severity=severity,
                            message=message,
                            timestamp=_parse_timestamp(timestamp),
                        )
                        event.id = stored.id
                    except AnomalyStorageError:
                        _logger.exception(
                            "Could not persist anomaly event for %s", metric
                        )

                self._recent_events.append(event)
                return event
            else:
                # Reading returned within normal statistical distribution; update rolling baseline
                baseline.append(val)
                self._is_anomalous[metric] = False
                self._current_severity[metric] = None
                return None

    def get_status(self) -> AnomalyStatusResponse:
        """Return engine operational status and sample baseline counts."""
        with self._lock:
            return AnomalyStatusResponse(
                enabled=self.enabled,
                monitored_metrics=[m for _, m in MONITORED_METRICS],
                sample_counts={m: len(b) for m, b in self._baselines.items()},
                window_size=self.window_size,
                min_samples=self.min_samples,
                z_score_threshold=self.z_score_threshold,
            )

    def get_settings(self) -> AnomalySettingsResponse:
        """Return active anomaly detection configuration."""
        with self._lock:
            return AnomalySettingsResponse(
                enabled=self.enabled,
                min_samples=self.min_samples,
                z_score_threshold=self.z_score_threshold,
                window_size=self.window_size,
            )

    def update_settings(
        self, new_settings: AnomalySettingsUpdateRequest
    ) -> AnomalySettingsResponse:
        """Validate, persist, and apply updated anomaly detection settings."""
        enabled, min_samples, z_score_threshold, window_size = (
            _validate_anomaly_settings(
                new_settings.enabled,
                new_settings.min_samples,
                new_settings.z_score_threshold,
                new_settings.window_size,
            )
        )
        with self._lock:
            self.enabled = enabled
            self.min_samples = min_samples
            self.z_score_threshold = z_score_threshold
            self.window_size = window_size
            for metric in self._baselines:
                cur = list(self._baselines[metric])
                self._baselines[metric] = deque(cur, maxlen=window_size)

            if self._repository is not None:
                try:
                    self._repository.save_settings(
                        {
                            "enabled": enabled,
                            "min_samples": min_samples,
                            "z_score_threshold": z_score_threshold,
                            "window_size": window_size,
                        }
                    )
                except AnomalyStorageError:
                    _logger.exception("Could not persist anomaly settings")
        return self.get_settings()

    def get_overview(self) -> AnomalyOverviewResponse:
        """Return status, active settings, and recent anomaly events."""
        with self._lock:
            return AnomalyOverviewResponse(
                status=self.get_status(),
                configuration=self.get_settings(),
                recent_events=[e.model_copy(deep=True) for e in self._recent_events],
            )

    def get_history(
        self,
        *,
        resource: str | None = None,
        metric: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AnomalyHistoryResponse:
        """Read paginated anomaly history from the database."""
        if self._repository is None:
            with self._lock:
                events = list(self._recent_events)
                return AnomalyHistoryResponse(
                    total=len(events),
                    limit=limit,
                    offset=offset,
                    events=events[offset : offset + limit],
                )
        events, total = self._repository.get_events(
            resource=resource,
            metric=metric,
            severity=severity,
            limit=limit,
            offset=offset,
        )
        return AnomalyHistoryResponse(
            total=total,
            limit=limit,
            offset=offset,
            events=[
                AnomalyEventResponse(
                    id=e.id,
                    resource=e.resource,
                    metric=e.metric,
                    actual_value=round(e.actual_value, 4),
                    expected_value=round(e.expected_value, 4),
                    standard_deviation=round(e.standard_deviation, 4),
                    z_score=round(e.z_score, 4),
                    severity=_normalize_severity(e.severity),
                    message=e.message,
                    timestamp=e.timestamp.isoformat(),
                )
                for e in events
            ],
        )

    def delete_event(self, event_id: int) -> bool:
        """Delete one persisted anomaly event."""
        deleted = False
        if self._repository is not None:
            deleted = self._repository.delete_event(event_id)
        with self._lock:
            self._recent_events = deque(
                (e for e in self._recent_events if e.id != event_id),
                maxlen=_RECENT_EVENT_LIMIT,
            )
        return deleted

    def get_analytics(
        self,
        *,
        range_key: str = "24h",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        interval_seconds: int | None = None,
        resource: str | None = None,
        metric: str | None = None,
        severity: str | None = None,
    ) -> AnomalyAnalyticsResponse:
        """Calculate statistical anomaly analytics: timeline, resource distribution, and metric analysis."""
        now = datetime.now(timezone.utc)
        if start_time is not None and end_time is not None:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            if start_time > end_time:
                raise ValueError("start_time must be earlier than or equal to end_time")
            duration_seconds = max(1.0, (end_time - start_time).total_seconds())
        else:
            duration_seconds = ANOMALY_TIME_RANGES_SECONDS.get(range_key, 24 * 3600)
            end_time = now
            start_time = end_time - timedelta(seconds=duration_seconds)

        if interval_seconds is None or interval_seconds <= 0:
            interval_seconds = ANOMALY_DEFAULT_INTERVALS_SECONDS.get(
                range_key, max(60, int(duration_seconds / 24))
            )

        interval_seconds = max(10, min(86400, interval_seconds))

        if self._repository is not None:
            events = self._repository.get_events_in_range(
                start_time=start_time,
                end_time=end_time,
                resource=resource,
                metric=metric,
                severity=severity,
            )
        else:
            with self._lock:
                events = [
                    e
                    for e in self._recent_events
                    if (
                        (start_time <= datetime.fromisoformat(e.timestamp) <= end_time)
                        and (resource is None or e.resource == resource)
                        and (metric is None or e.metric == metric)
                        and (severity is None or e.severity == severity)
                    )
                ]

        total_anomalies = len(events)
        warning_count = sum(1 for e in events if e.severity == "Warning")
        critical_count = sum(1 for e in events if e.severity == "Critical")

        num_buckets = max(1, min(1000, math.ceil(duration_seconds / interval_seconds)))
        timeline: list[AnomalyTimelinePoint] = []
        t0 = start_time
        bucket_events: list[list[Any]] = [[] for _ in range(num_buckets)]

        for evt in events:
            evt_dt = (
                evt.timestamp
                if isinstance(evt.timestamp, datetime)
                else datetime.fromisoformat(evt.timestamp)
            )
            if evt_dt.tzinfo is None:
                evt_dt = evt_dt.replace(tzinfo=timezone.utc)
            offset_sec = (evt_dt - t0).total_seconds()
            idx = int(offset_sec // interval_seconds)
            idx = max(0, min(num_buckets - 1, idx))
            bucket_events[idx].append(evt)

        for i in range(num_buckets):
            b_time = t0 + timedelta(seconds=i * interval_seconds)
            b_evts = bucket_events[i]
            w_c = sum(1 for e in b_evts if e.severity == "Warning")
            c_c = sum(1 for e in b_evts if e.severity == "Critical")
            timeline.append(
                AnomalyTimelinePoint(
                    timestamp=b_time.isoformat(),
                    warning_count=w_c,
                    critical_count=c_c,
                    total_count=w_c + c_c,
                )
            )

        resources = ["cpu", "memory", "disk", "network"]
        by_resource: list[AnomalyResourceDistribution] = []
        for res in resources:
            res_evts = [e for e in events if e.resource == res]
            w_c = sum(1 for e in res_evts if e.severity == "Warning")
            c_c = sum(1 for e in res_evts if e.severity == "Critical")
            tot = len(res_evts)
            pct = round((tot / total_anomalies * 100), 2) if total_anomalies > 0 else 0.0
            by_resource.append(
                AnomalyResourceDistribution(
                    resource=res,
                    total_count=tot,
                    warning_count=w_c,
                    critical_count=c_c,
                    percentage=pct,
                )
            )

        by_metric: list[AnomalyMetricAnalysis] = []
        for res, met in MONITORED_METRICS:
            met_evts = [e for e in events if e.metric == met]
            w_c = sum(1 for e in met_evts if e.severity == "Warning")
            c_c = sum(1 for e in met_evts if e.severity == "Critical")
            tot = len(met_evts)
            pct = round((tot / total_anomalies * 100), 2) if total_anomalies > 0 else 0.0
            by_metric.append(
                AnomalyMetricAnalysis(
                    resource=res,
                    metric=met,
                    label=METRIC_LABELS.get(met, met),
                    total_count=tot,
                    warning_count=w_c,
                    critical_count=c_c,
                    percentage=pct,
                )
            )

        return AnomalyAnalyticsResponse(
            range=range_key,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            interval_seconds=interval_seconds,
            total_anomalies=total_anomalies,
            warning_count=warning_count,
            critical_count=critical_count,
            timeline=timeline,
            by_resource=by_resource,
            by_metric=by_metric,
        )

    def clear_events(self) -> int:
        """Remove all persisted anomaly events from storage and in-memory caches."""
        deleted = 0
        if self._repository is not None:
            deleted = self._repository.clear_events()
        with self._lock:
            self._recent_events.clear()
        return deleted

    def restore_persisted_state(self) -> None:
        """Load saved anomaly configuration and recent events from database."""
        if self._repository is None:
            return
        saved = self._repository.get_settings()
        if saved is not None:
            with self._lock:
                self.enabled = saved.enabled
                self.min_samples = saved.min_samples
                self.z_score_threshold = saved.z_score_threshold
                self.window_size = saved.window_size
                for metric in self._baselines:
                    self._baselines[metric] = deque(maxlen=self.window_size)

        recent = self._repository.get_recent_events(_RECENT_EVENT_LIMIT)
        with self._lock:
            self._recent_events.clear()
            for record in reversed(recent):
                self._recent_events.append(
                    AnomalyEventResponse(
                        id=record.id,
                        resource=record.resource,
                        metric=record.metric,
                        actual_value=round(record.actual_value, 4),
                        expected_value=round(record.expected_value, 4),
                        standard_deviation=round(record.standard_deviation, 4),
                        z_score=round(record.z_score, 4),
                        severity=_normalize_severity(record.severity),
                        message=record.message,
                        timestamp=record.timestamp.isoformat(),
                    )
                )

    def reset(self) -> None:
        """Reset baselines and state machine for test isolation."""
        with self._lock:
            self.enabled = DEFAULT_ANOMALY_DETECTION_ENABLED
            self.min_samples = DEFAULT_ANOMALY_MIN_SAMPLES
            self.z_score_threshold = DEFAULT_ANOMALY_Z_SCORE_THRESHOLD
            self.window_size = DEFAULT_ANOMALY_WINDOW_SIZE
            self._baselines = {
                metric: deque(maxlen=self.window_size)
                for _, metric in MONITORED_METRICS
            }
            self._is_anomalous = {metric: False for _, metric in MONITORED_METRICS}
            self._current_severity = {
                metric: None for _, metric in MONITORED_METRICS
            }
            self._recent_events.clear()


anomaly_repository = AnomalyRepository(database.session_factory)
anomaly_service = AnomalyService(repository=anomaly_repository)
