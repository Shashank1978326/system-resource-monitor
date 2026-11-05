"""Tests for background monitoring lifecycle and configuration."""

import asyncio

import pytest

from app.core.config import (
    _cpu_alert_thresholds_from_environment,
    _disk_alert_thresholds_from_environment,
    _monitoring_interval_from_environment,
    _ram_alert_thresholds_from_environment,
    _websocket_publish_interval_from_environment,
)
from app.schemas.monitoring import (
    BatteryResponse,
    CpuResponse,
    DiskIoResponse,
    DiskPartitionResponse,
    DiskResponse,
    MemoryResponse,
    NetworkResponse,
)
from app.services.alert_service import cpu_alert_service
from app.services.monitoring_service import MonitoringService


def test_monitoring_interval_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MONITORING_INTERVAL_SECONDS", "2.5")
    assert _monitoring_interval_from_environment() == 2.5

    for invalid_value in ("0", "-1", "nan", "inf", "not-a-number"):
        monkeypatch.setenv("MONITORING_INTERVAL_SECONDS", invalid_value)
        with pytest.raises(ValueError):
            _monitoring_interval_from_environment()


def test_websocket_publish_interval_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBSOCKET_PUBLISH_INTERVAL_SECONDS", "2.5")
    assert _websocket_publish_interval_from_environment() == 2.5

    for invalid_value in ("0", "0.05", "-1", "nan", "inf", "not-a-number"):
        monkeypatch.setenv("WEBSOCKET_PUBLISH_INTERVAL_SECONDS", invalid_value)
        with pytest.raises(ValueError):
            _websocket_publish_interval_from_environment()


def test_cpu_alert_threshold_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CPU_ALERT_WARNING_THRESHOLD_PERCENT", "75")
    monkeypatch.setenv("CPU_ALERT_CRITICAL_THRESHOLD_PERCENT", "92.5")
    assert _cpu_alert_thresholds_from_environment() == (75, 92.5)

    for warning, critical in (
        ("0", "90"),
        ("90", "90"),
        ("91", "90"),
        ("-1", "90"),
        ("80", "101"),
        ("nan", "90"),
        ("80", "inf"),
        ("bad", "90"),
    ):
        monkeypatch.setenv("CPU_ALERT_WARNING_THRESHOLD_PERCENT", warning)
        monkeypatch.setenv("CPU_ALERT_CRITICAL_THRESHOLD_PERCENT", critical)
        with pytest.raises(ValueError):
            _cpu_alert_thresholds_from_environment()


@pytest.mark.parametrize(
    ("prefix", "reader"),
    [
        ("RAM", _ram_alert_thresholds_from_environment),
        ("DISK", _disk_alert_thresholds_from_environment),
    ],
)
def test_ram_and_disk_alert_threshold_validation(
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    reader,
) -> None:
    monkeypatch.setenv(f"{prefix}_ALERT_WARNING_THRESHOLD_PERCENT", "75")
    monkeypatch.setenv(f"{prefix}_ALERT_CRITICAL_THRESHOLD_PERCENT", "92.5")
    assert reader() == (75, 92.5)

    for warning, critical in (
        ("0", "90"),
        ("90", "90"),
        ("91", "90"),
        ("-1", "90"),
        ("80", "101"),
        ("nan", "90"),
        ("80", "inf"),
        ("bad", "90"),
    ):
        monkeypatch.setenv(f"{prefix}_ALERT_WARNING_THRESHOLD_PERCENT", warning)
        monkeypatch.setenv(f"{prefix}_ALERT_CRITICAL_THRESHOLD_PERCENT", critical)
        with pytest.raises(ValueError):
            reader()


def test_monitoring_service_starts_once_and_stops_cleanly() -> None:
    async def exercise_lifecycle() -> None:
        service = MonitoringService(interval_seconds=0.25)
        await service.start()
        original_task = service._task
        await service.start()
        assert service._task is original_task

        deadline = asyncio.get_running_loop().time() + 5
        while service.get_snapshot() is None:
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("Monitoring did not complete its first cycle")
            await asyncio.sleep(0.01)

        await service.stop()
        assert service.get_status().running is False
        assert service.get_status().collector_status == "stopped"

    asyncio.run(exercise_lifecycle())


def test_monitoring_collector_updates_alert_service_from_cpu_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise_collector() -> None:
        cpu_alert_service.reset()
        cpu = CpuResponse(
            cpu_usage_percent=84,
            per_core_usage=None,
            physical_cores=4,
            logical_cores=8,
            frequency_mhz=None,
            min_frequency_mhz=None,
            max_frequency_mhz=None,
            usage_status="elevated",
        )
        memory = MemoryResponse(
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            free_bytes=None,
            usage_percent=94,
            cached_bytes=None,
            swap_total_bytes=None,
            swap_used_bytes=None,
            swap_percent=None,
        )
        disk = DiskResponse(
            partitions=[
                DiskPartitionResponse(
                    device="D:",
                    mountpoint="D:\\",
                    filesystem="NTFS",
                    total_bytes=1000,
                    used_bytes=950,
                    free_bytes=50,
                    usage_percent=95,
                )
            ],
            io=DiskIoResponse(
                read_bytes=None,
                write_bytes=None,
                read_count=None,
                write_count=None,
            ),
        )
        network = NetworkResponse(
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

        class InMemoryHistory:
            def __init__(self) -> None:
                self.battery_samples = []

            def record_snapshot(
                self,
                snapshot,
                temperature_info=None,
                battery_info=None,
                *,
                temperature_sampled=False,
            ) -> None:
                self.battery_samples.append(battery_info)

            def cleanup_expired(self) -> None:
                pass

        monkeypatch.setattr(
            MonitoringService,
            "_collect_metrics",
            staticmethod(lambda: (cpu, memory, disk, network, {})),
        )
        battery = BatteryResponse(
            availability="available",
            platform="TestOS",
            percentage=0,
            charging_state="charging",
            power_plugged=True,
            remaining_seconds=None,
            remaining_time=None,
            message="Battery is charging.",
        )
        monkeypatch.setattr(
            "app.services.monitoring_service.get_battery_info",
            lambda: battery,
        )
        history = InMemoryHistory()
        service = MonitoringService(
            interval_seconds=0.25,
            history_storage=history,
        )
        await service.start()
        try:
            deadline = asyncio.get_running_loop().time() + 5
            while cpu_alert_service.get_status().status != "Warning":
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError("CPU snapshot did not update alert state")
                await asyncio.sleep(0.01)
        finally:
            await service.stop()

        assert history.battery_samples
        assert history.battery_samples[0].percentage == 0
        assert history.battery_samples[0].charging_state == "charging"
        assert history.battery_samples[0].power_plugged is True

        alerts = cpu_alert_service.get_alerts()
        assert alerts.status.cpu_usage_percent == 84
        assert alerts.recent_events[0].timestamp.endswith("+00:00")
        assert alerts.ram.status.status == "Critical"
        assert alerts.ram.status.usage_percent == 94
        assert alerts.disk.status.status == "Critical"
        assert alerts.disk.status.partitions[0].mountpoint == "D:\\"
        assert alerts.disk.recent_events[0].total_bytes == 1000

    asyncio.run(exercise_collector())
