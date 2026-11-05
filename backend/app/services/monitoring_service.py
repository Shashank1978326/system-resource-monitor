"""Asynchronous background collection and latest-snapshot management."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from app.core.config import settings
from app.schemas.monitoring import (
    BatteryResponse,
    CpuResponse,
    DiskIoResponse,
    DiskResponse,
    MemoryResponse,
    MonitoringSnapshotResponse,
    MonitoringStatusResponse,
    NetworkResponse,
    TemperatureResponse,
)
from app.services.cpu_service import get_cpu_info, reset_cpu_sampler
from app.services.alert_service import cpu_alert_service
from app.services.anomaly_service import anomaly_service
from app.services.battery_service import get_battery_info
from app.services.disk_service import get_disk_info, reset_disk_sampler
from app.services.history_service import (
    HistoryService,
    HistoryStorageError,
    history_service,
)
from app.services.memory_service import get_memory_info
from app.services.network_service import get_network_info, reset_network_sampler
from app.services.temperature_service import get_temperature_info

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_RETENTION_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class MonitoringService:
    """Run a single collector loop and expose defensive snapshot copies."""

    def __init__(
        self,
        interval_seconds: float,
        history_storage: HistoryService | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self._history_service = history_storage or history_service
        self._task: asyncio.Task[None] | None = None
        self._snapshot: MonitoringSnapshotResponse | None = None
        self._snapshot_lock = threading.Lock()
        self._started_at: str | None = None
        self._last_successful_collection: str | None = None
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._collector_status = "stopped"
        self._next_retention_cleanup = 0.0

    async def start(self) -> None:
        """Start the collector if it is not already running."""
        if self._task is not None and not self._task.done():
            return
        reset_cpu_sampler()
        reset_disk_sampler()
        reset_network_sampler()
        with self._snapshot_lock:
            self._snapshot = None
        self._started_at = _iso_timestamp()
        self._last_successful_collection = None
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._collector_status = "starting"
        self._next_retention_cleanup = (
            time.monotonic() + _RETENTION_CLEANUP_INTERVAL_SECONDS
        )
        self._task = asyncio.create_task(
            self._run(), name="system-resource-monitor"
        )

    async def stop(self) -> None:
        """Cancel the collector and wait for an in-flight sample to finish."""
        task = self._task
        if task is None:
            self._collector_status = "stopped"
            return
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._task = None
        self._collector_status = "stopped"

    def get_snapshot(self) -> MonitoringSnapshotResponse | None:
        """Return a defensive copy of the latest completed collection."""
        with self._snapshot_lock:
            if self._snapshot is None:
                return None
            return self._snapshot.model_copy(deep=True)

    def get_status(self) -> MonitoringStatusResponse:
        """Return collector state and collection counters."""
        task = self._task
        running = task is not None and not task.done()
        return MonitoringStatusResponse(
            running=running,
            interval_seconds=self.interval_seconds,
            last_successful_collection=self._last_successful_collection,
            successful_cycles=self._successful_cycles,
            failed_cycles=self._failed_cycles,
            started_at=self._started_at,
            collector_status=self._collector_status,
        )

    @staticmethod
    def _collect_one(
        name: str,
        collector: Callable[[], _T],
        errors: dict[str, str],
    ) -> _T | None:
        try:
            return collector()
        except Exception as exc:
            logger.exception("Monitoring metric collection failed: %s", name)
            errors[name] = f"collection failed ({type(exc).__name__})"
            return None

    @classmethod
    def _collect_metrics(
        cls,
    ) -> tuple[CpuResponse, MemoryResponse, DiskResponse, NetworkResponse, dict[str, str]]:
        """Call each existing metric service independently, preserving partial data."""
        errors: dict[str, str] = {}
        cpu = cls._collect_one("cpu", get_cpu_info, errors) or CpuResponse(
            cpu_usage_percent=None,
            per_core_usage=None,
            physical_cores=None,
            logical_cores=None,
            frequency_mhz=None,
            min_frequency_mhz=None,
            max_frequency_mhz=None,
            usage_status=None,
        )
        memory = cls._collect_one("memory", get_memory_info, errors) or MemoryResponse(
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            free_bytes=None,
            usage_percent=None,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        )
        disk = cls._collect_one("disk", get_disk_info, errors) or DiskResponse(
            partitions=[],
            io=DiskIoResponse(
                read_bytes=None,
                write_bytes=None,
                read_count=None,
                write_count=None,
            ),
        )
        network = cls._collect_one(
            "network", get_network_info, errors
        ) or NetworkResponse(
            bytes_received=None,
            bytes_sent=None,
            packets_received=None,
            packets_sent=None,
            download_speed_bytes_per_sec=None,
            upload_speed_bytes_per_sec=None,
            download_speed_mbps=None,
            upload_speed_mbps=None,
            interfaces=[],
        )
        return cpu, memory, disk, network, errors

    async def _run(self) -> None:
        """Collect immediately, then follow the configured interval."""
        self._collector_status = "running"
        while True:
            cycle_started = time.monotonic()
            worker = asyncio.create_task(asyncio.to_thread(self._collect_metrics))
            try:
                cpu, memory, disk, network, errors = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await asyncio.shield(worker)
                raise
            except Exception:
                logger.exception("Unexpected monitoring collection-cycle failure")
                self._failed_cycles += 1
                self._collector_status = "degraded"
                errors = {"collection": "unexpected collection-cycle failure"}
                cpu, memory, disk, network, _ = self._empty_metrics()

            timestamp = _iso_timestamp()
            collection_status = "degraded" if errors else "healthy"
            snapshot = MonitoringSnapshotResponse(
                timestamp=timestamp,
                cpu=cpu,
                memory=memory,
                disk=disk,
                network=network,
                collection_status=collection_status,
                metric_errors=errors,
            )
            try:
                temperature_info = await asyncio.to_thread(get_temperature_info)
            except Exception:
                logger.exception("Temperature monitoring sample failed")
                temperature_info = None
            try:
                battery_info = await asyncio.to_thread(get_battery_info)
            except Exception:
                logger.exception("Battery monitoring sample failed")
                battery_info = None
            alert_worker = asyncio.create_task(
                asyncio.to_thread(
                    cpu_alert_service.process_snapshot,
                    snapshot.cpu.cpu_usage_percent,
                    snapshot.memory.usage_percent,
                    snapshot.disk.partitions,
                    snapshot.timestamp,
                    temperature_info,
                    battery_info,
                )
            )
            anomaly_worker = asyncio.create_task(
                asyncio.to_thread(
                    anomaly_service.process_snapshot,
                    snapshot,
                )
            )
            try:
                await asyncio.gather(alert_worker, anomaly_worker)
            except asyncio.CancelledError:
                await asyncio.gather(
                    alert_worker, anomaly_worker, return_exceptions=True
                )
                raise
            with self._snapshot_lock:
                self._snapshot = snapshot

            if errors:
                if "collection" not in errors:
                    self._failed_cycles += 1
                self._collector_status = "degraded"
            else:
                self._successful_cycles += 1
                self._last_successful_collection = timestamp
                self._collector_status = "running"

            persistence_worker = asyncio.create_task(
                asyncio.to_thread(
                    self._persist_snapshot, snapshot, temperature_info, battery_info
                )
            )
            try:
                await asyncio.shield(persistence_worker)
            except asyncio.CancelledError:
                await asyncio.shield(persistence_worker)
                raise

            if time.monotonic() >= self._next_retention_cleanup:
                cleanup_worker = asyncio.create_task(
                    asyncio.to_thread(self._cleanup_history)
                )
                try:
                    await asyncio.shield(cleanup_worker)
                except asyncio.CancelledError:
                    await asyncio.shield(cleanup_worker)
                    raise
                self._next_retention_cleanup = (
                    time.monotonic() + _RETENTION_CLEANUP_INTERVAL_SECONDS
                )

            elapsed = time.monotonic() - cycle_started
            await asyncio.sleep(max(0.0, self.interval_seconds - elapsed))

    def _persist_snapshot(
        self,
        snapshot: MonitoringSnapshotResponse,
        temperature_info: TemperatureResponse | None = None,
        battery_info: BatteryResponse | None = None,
    ) -> None:
        try:
            self._history_service.record_snapshot(
                snapshot,
                temperature_info,
                battery_info,
                temperature_sampled=True,
            )
        except HistoryStorageError:
            return
        except Exception:
            logger.exception("Unexpected failure while persisting monitoring metrics")

    def _cleanup_history(self) -> None:
        try:
            self._history_service.cleanup_expired()
        except HistoryStorageError:
            pass
        except Exception:
            logger.exception("Unexpected failure during history retention cleanup")

        try:
            from datetime import timedelta
            from app.services.anomaly_service import anomaly_repository
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=settings.history_retention_days
            )
            anomaly_repository.cleanup_expired(cutoff)
        except Exception:
            logger.exception("Unexpected failure during anomaly retention cleanup")

    @staticmethod
    def _empty_metrics() -> tuple[
        CpuResponse, MemoryResponse, DiskResponse, NetworkResponse, dict[str, str]
    ]:
        return (
            CpuResponse(
                cpu_usage_percent=None,
                per_core_usage=None,
                physical_cores=None,
                logical_cores=None,
                frequency_mhz=None,
                min_frequency_mhz=None,
                max_frequency_mhz=None,
                usage_status=None,
            ),
            MemoryResponse(
                total_bytes=None,
                used_bytes=None,
                available_bytes=None,
                free_bytes=None,
                usage_percent=None,
                cached_bytes=None,
                swap_total_bytes=None,
                swap_used_bytes=None,
                swap_percent=None,
            ),
            DiskResponse(
                partitions=[],
                io=DiskIoResponse(
                    read_bytes=None,
                    write_bytes=None,
                    read_count=None,
                    write_count=None,
                ),
            ),
            NetworkResponse(
                bytes_received=None,
                bytes_sent=None,
                packets_received=None,
                packets_sent=None,
                download_speed_bytes_per_sec=None,
                upload_speed_bytes_per_sec=None,
                download_speed_mbps=None,
                upload_speed_mbps=None,
                interfaces=[],
            ),
            {},
        )


monitoring_service = MonitoringService(
    interval_seconds=settings.monitoring_interval_seconds
)
