"""Tests for statistical real-time resource anomaly detection."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database.anomaly_repository import AnomalyRepository
from app.database.connection import Database, database, initialize_database
from app.main import app
from app.schemas.monitoring import (
    AnomalySettingsUpdateRequest,
    CpuResponse,
    DiskIoResponse,
    DiskPartitionResponse,
    DiskResponse,
    MemoryResponse,
    MonitoringSnapshotResponse,
    NetworkResponse,
)
from app.services.anomaly_service import (
    AnomalyService,
    _calculate_mean_and_stdev,
    anomaly_repository,
    anomaly_service,
)

_TIMESTAMP = "2026-11-03T00:00:00+00:00"


def _make_snapshot(
    cpu_percent: float | None = 20.0,
    ram_percent: float | None = 40.0,
    disk_read: float | None = 1_000_000.0,
    disk_write: float | None = 500_000.0,
    net_download: float | None = 200_000.0,
    net_upload: float | None = 100_000.0,
    timestamp: str = _TIMESTAMP,
) -> MonitoringSnapshotResponse:
    return MonitoringSnapshotResponse(
        timestamp=timestamp,
        cpu=CpuResponse(
            cpu_usage_percent=cpu_percent,
            per_core_usage=[cpu_percent] if cpu_percent else [],
            physical_cores=4,
            logical_cores=8,
            frequency_mhz=2500.0,
            min_frequency_mhz=1000.0,
            max_frequency_mhz=3500.0,
            usage_status="Normal",
        ),
        memory=MemoryResponse(
            total_bytes=16_000_000_000,
            used_bytes=int(16_000_000_000 * ((ram_percent or 0) / 100)),
            available_bytes=int(16_000_000_000 * (1 - (ram_percent or 0) / 100)),
            free_bytes=int(16_000_000_000 * (1 - (ram_percent or 0) / 100)),
            usage_percent=ram_percent,
            cached_bytes=1_000_000_000,
            swap_total_bytes=0,
            swap_used_bytes=0,
            swap_percent=0.0,
        ),
        disk=DiskResponse(
            partitions=[],
            io=DiskIoResponse(
                read_bytes=100_000_000,
                write_bytes=50_000_000,
                read_count=1000,
                write_count=500,
                read_speed_bytes_per_sec=disk_read,
                write_speed_bytes_per_sec=disk_write,
            ),
        ),
        network=NetworkResponse(
            bytes_received=10_000_000,
            bytes_sent=5_000_000,
            packets_received=1000,
            packets_sent=500,
            download_speed_bytes_per_sec=net_download,
            upload_speed_bytes_per_sec=net_upload,
            download_speed_mbps=(net_download * 8 / 1_000_000) if net_download else None,
            upload_speed_mbps=(net_upload * 8 / 1_000_000) if net_upload else None,
            interfaces=[],
        ),
        collection_status="healthy",
        metric_errors={},
    )


@pytest.fixture(autouse=True)
def reset_services():
    initialize_database()
    anomaly_repository.clear_events()
    anomaly_service.reset()
    yield
    anomaly_repository.clear_events()
    anomaly_service.reset()
    database.dispose()


@pytest.fixture
def client():
    return TestClient(app)


def test_z_score_calculation_accuracy() -> None:
    # Deterministic dataset: [10, 12, 14, 16, 18]
    # Mean = 14.0
    # Variance = ((16 + 4 + 0 + 4 + 16) / 4) = 40 / 4 = 10.0
    # Stdev = sqrt(10.0) ≈ 3.16227766
    samples = [10.0, 12.0, 14.0, 16.0, 18.0]
    mean, stdev = _calculate_mean_and_stdev(samples)
    assert round(mean, 4) == 14.0
    assert round(stdev, 4) == 3.1623

    # For x = 23.4868, z = (23.4868 - 14.0) / 3.16227766 ≈ 3.0
    z = (23.48683 - mean) / stdev
    assert math.isclose(z, 3.0, rel_tol=1e-3)


def test_normal_readings_do_not_trigger_anomalies() -> None:
    # Feed 25 baseline samples with mean 20% and minor variation (18-22%)
    for i in range(25):
        val = 20.0 + (1.0 if i % 2 == 0 else -1.0)
        event = anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", val, f"2026-11-03T00:00:{i:02d}+00:00"
        )
        assert event is None

    # Normal sample within baseline variance
    normal_event = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 21.0, "2026-11-03T00:01:00+00:00"
    )
    assert normal_event is None
    assert len(anomaly_service.get_overview().recent_events) == 0


def test_cpu_anomaly_detection() -> None:
    # 20 samples around 20.0 (stdev ≈ 1.0)
    for i in range(20):
        val = 20.0 + (1.0 if i % 2 == 0 else -1.0)
        anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", val, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Spike CPU to 85% (Z-score >> 3.0)
    event = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 85.0, "2026-11-03T00:01:00+00:00"
    )
    assert event is not None
    assert event.resource == "cpu"
    assert event.metric == "cpu_utilization"
    assert event.actual_value == 85.0
    assert event.z_score >= 3.0
    assert event.severity in ("Warning", "Critical")
    assert "anomaly detected in CPU" in event.message


def test_memory_anomaly_detection() -> None:
    # 20 samples around 40.0%
    for i in range(20):
        val = 40.0 + (0.5 if i % 2 == 0 else -0.5)
        anomaly_service.process_metric_sample(
            "memory", "memory_utilization", val, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Sudden jump to 98%
    event = anomaly_service.process_metric_sample(
        "memory", "memory_utilization", 98.0, "2026-11-03T00:01:00+00:00"
    )
    assert event is not None
    assert event.resource == "memory"
    assert event.metric == "memory_utilization"
    assert event.actual_value == 98.0
    assert event.z_score >= 3.0


def test_disk_read_and_write_anomalies() -> None:
    # Baseline for read and write
    for i in range(20):
        read_val = 1_000_000.0 + (50_000.0 if i % 2 == 0 else -50_000.0)
        write_val = 500_000.0 + (25_000.0 if i % 2 == 0 else -25_000.0)
        anomaly_service.process_metric_sample(
            "disk", "disk_read_throughput", read_val, f"2026-11-03T00:00:{i:02d}+00:00"
        )
        anomaly_service.process_metric_sample(
            "disk", "disk_write_throughput", write_val, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Spike in disk read
    event_read = anomaly_service.process_metric_sample(
        "disk", "disk_read_throughput", 50_000_000.0, "2026-11-03T00:01:00+00:00"
    )
    assert event_read is not None
    assert event_read.resource == "disk"
    assert event_read.metric == "disk_read_throughput"
    assert event_read.actual_value == 50_000_000.0

    # Spike in disk write
    event_write = anomaly_service.process_metric_sample(
        "disk", "disk_write_throughput", 30_000_000.0, "2026-11-03T00:01:01+00:00"
    )
    assert event_write is not None
    assert event_write.resource == "disk"
    assert event_write.metric == "disk_write_throughput"
    assert event_write.actual_value == 30_000_000.0


def test_network_download_and_upload_anomalies() -> None:
    # Baseline
    for i in range(20):
        down_val = 100_000.0 + (5000.0 if i % 2 == 0 else -5000.0)
        up_val = 50_000.0 + (2500.0 if i % 2 == 0 else -2500.0)
        anomaly_service.process_metric_sample(
            "network", "network_download_throughput", down_val, f"2026-11-03T00:00:{i:02d}+00:00"
        )
        anomaly_service.process_metric_sample(
            "network", "network_upload_throughput", up_val, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Spike download
    event_down = anomaly_service.process_metric_sample(
        "network", "network_download_throughput", 10_000_000.0, "2026-11-03T00:01:00+00:00"
    )
    assert event_down is not None
    assert event_down.resource == "network"
    assert event_down.metric == "network_download_throughput"

    # Spike upload
    event_up = anomaly_service.process_metric_sample(
        "network", "network_upload_throughput", 5_000_000.0, "2026-11-03T00:01:01+00:00"
    )
    assert event_up is not None
    assert event_up.resource == "network"
    assert event_up.metric == "network_upload_throughput"


def test_independent_metric_baselines() -> None:
    # 20 samples where CPU is fluctuating normally around 50%
    # and Memory is fluctuating normally around 10%
    for i in range(20):
        anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", 50.0 + (i % 3), f"2026-11-03T00:00:{i:02d}+00:00"
        )
        anomaly_service.process_metric_sample(
            "memory", "memory_utilization", 10.0 + (i % 2), f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Spike CPU only
    cpu_event = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 95.0, "2026-11-03T00:01:00+00:00"
    )
    # Memory remains normal
    mem_event = anomaly_service.process_metric_sample(
        "memory", "memory_utilization", 10.5, "2026-11-03T00:01:00+00:00"
    )

    assert cpu_event is not None
    assert mem_event is None


def test_insufficient_sample_count_does_not_trigger_anomalies() -> None:
    # Requirement: min_samples=20.
    # Provide only 5 samples and then a spike
    for i in range(5):
        anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", 20.0, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Spike before reaching min_samples
    spike_event = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 99.0, "2026-11-03T00:01:00+00:00"
    )
    assert spike_event is None
    assert len(anomaly_service.get_overview().recent_events) == 0


def test_zero_standard_deviation_handled_safely() -> None:
    # 20 identical samples -> stdev is 0.0
    for i in range(20):
        event = anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", 15.0, f"2026-11-03T00:00:{i:02d}+00:00"
        )
        assert event is None

    # Normal sample identical to mean
    same_event = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 15.0, "2026-11-03T00:01:00+00:00"
    )
    assert same_event is None


def test_missing_and_null_measurements_handled_safely() -> None:
    # Missing / None / NaN / bool / negative
    assert anomaly_service.process_metric_sample("cpu", "cpu_utilization", None, _TIMESTAMP) is None
    assert anomaly_service.process_metric_sample("cpu", "cpu_utilization", True, _TIMESTAMP) is None
    assert anomaly_service.process_metric_sample("cpu", "cpu_utilization", -5.0, _TIMESTAMP) is None
    assert anomaly_service.process_metric_sample("cpu", "cpu_utilization", float("nan"), _TIMESTAMP) is None
    assert anomaly_service.process_metric_sample("cpu", "cpu_utilization", float("inf"), _TIMESTAMP) is None


def test_duplicate_prevention_during_ongoing_anomaly() -> None:
    for i in range(20):
        val = 20.0 + (1.0 if i % 2 == 0 else -1.0)
        anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", val, f"2026-11-03T00:00:{i:02d}+00:00"
        )

    # Cycle 1: Spike to 23.6% (z ≈ 3.5, between 3.0 and 4.5) -> Warning anomaly
    event_1 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 23.6, "2026-11-03T00:01:00+00:00"
    )
    assert event_1 is not None
    assert event_1.severity == "Warning"

    # Cycle 2: Remains anomalous at 23.8% -> Duplicate suppressed!
    event_2 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 23.8, "2026-11-03T00:01:01+00:00"
    )
    assert event_2 is None

    # Cycle 3: Escalates to 90% (z >> 4.5) -> Critical escalation event emitted
    event_3 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 90.0, "2026-11-03T00:01:02+00:00"
    )
    assert event_3 is not None
    assert event_3.severity == "Critical"

    # Cycle 4: Remains at 91% -> Duplicate suppressed!
    event_4 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 91.0, "2026-11-03T00:01:03+00:00"
    )
    assert event_4 is None

    # Cycle 5: Returns to normal (20%)
    event_5 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 20.0, "2026-11-03T00:01:04+00:00"
    )
    assert event_5 is None

    # Cycle 6: New spike to 80% -> New anomaly event emitted!
    event_6 = anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 80.0, "2026-11-03T00:01:05+00:00"
    )
    assert event_6 is not None


def test_configuration_validation_and_endpoints(client: TestClient) -> None:
    # GET /api/anomalies/settings
    res = client.get("/api/anomalies/settings")
    assert res.status_code == 200
    config = res.json()
    assert config["enabled"] is True
    assert config["min_samples"] == 20
    assert config["z_score_threshold"] == 3.0
    assert config["window_size"] == 60

    # Valid PUT update
    update_payload = {
        "enabled": True,
        "min_samples": 15,
        "z_score_threshold": 2.5,
        "window_size": 50,
    }
    put_res = client.put("/api/anomalies/settings", json=update_payload)
    assert put_res.status_code == 200
    assert put_res.json() == update_payload
    assert anomaly_service.min_samples == 15
    assert anomaly_service.z_score_threshold == 2.5
    assert anomaly_service.window_size == 50

    # Invalid PUT: window_size < min_samples
    assert client.put(
        "/api/anomalies/settings",
        json={**update_payload, "window_size": 10, "min_samples": 15},
    ).status_code == 422

    # Invalid PUT: non-positive z_score_threshold
    assert client.put(
        "/api/anomalies/settings",
        json={**update_payload, "z_score_threshold": 0},
    ).status_code == 422
    assert client.put(
        "/api/anomalies/settings",
        json={**update_payload, "z_score_threshold": -1.5},
    ).status_code == 422


def test_configuration_persistence_across_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "anomalies_persist.sqlite3"
    db_one = Database(db_file)
    db_one.initialize()
    repo_one = AnomalyRepository(db_one.session_factory)
    svc_one = AnomalyService(repository=repo_one)

    # Update settings
    svc_one.update_settings(
        AnomalySettingsUpdateRequest(
            enabled=False,
            min_samples=25,
            z_score_threshold=4.0,
            window_size=80,
        )
    )

    db_one.dispose()

    # Reopen database with fresh service
    db_two = Database(db_file)
    db_two.initialize()
    repo_two = AnomalyRepository(db_two.session_factory)
    svc_two = AnomalyService(repository=repo_two)
    svc_two.restore_persisted_state()

    settings_two = svc_two.get_settings()
    assert settings_two.enabled is False
    assert settings_two.min_samples == 25
    assert settings_two.z_score_threshold == 4.0
    assert settings_two.window_size == 80

    db_two.dispose()


def test_anomaly_event_persistence_and_management(client: TestClient) -> None:
    # Produce an anomaly
    for i in range(20):
        val = 20.0 + (1.0 if i % 2 == 0 else -1.0)
        anomaly_service.process_metric_sample(
            "cpu", "cpu_utilization", val, f"2026-11-03T00:00:{i:02d}+00:00"
        )
    anomaly_service.process_metric_sample(
        "cpu", "cpu_utilization", 90.0, "2026-11-03T00:01:00+00:00"
    )

    # Verify GET /api/anomalies
    overview_res = client.get("/api/anomalies")
    assert overview_res.status_code == 200
    overview = overview_res.json()
    assert overview["status"]["enabled"] is True
    assert len(overview["recent_events"]) == 1
    event = overview["recent_events"][0]
    assert event["resource"] == "cpu"
    assert event["metric"] == "cpu_utilization"
    assert event["actual_value"] == 90.0
    event_id = event["id"]

    # Verify GET /api/anomalies/history
    history_res = client.get("/api/anomalies/history")
    assert history_res.status_code == 200
    assert history_res.json()["total"] == 1

    # Filter history by resource
    assert client.get("/api/anomalies/history?resource=cpu").json()["total"] == 1
    assert client.get("/api/anomalies/history?resource=memory").json()["total"] == 0

    # Delete single event
    del_res = client.delete(f"/api/anomalies/{event_id}")
    assert del_res.status_code == 204
    assert client.get("/api/anomalies/history").json()["total"] == 0
    assert len(client.get("/api/anomalies").json()["recent_events"]) == 0


def test_process_snapshot_integration_with_monitoring() -> None:
    # Process 20 snapshots through process_snapshot
    for i in range(20):
        snapshot = _make_snapshot(
            cpu_percent=20.0 + (1.0 if i % 2 == 0 else -1.0),
            timestamp=f"2026-11-03T00:00:{i:02d}+00:00",
        )
        events = anomaly_service.process_snapshot(snapshot)
        assert len(events) == 0

    # Process 21st snapshot with an anomaly on network download
    spike_snapshot = _make_snapshot(
        net_download=50_000_000.0,  # 50 MB/s vs baseline 200 KB/s
        timestamp="2026-11-03T00:01:00+00:00",
    )
    spike_events = anomaly_service.process_snapshot(spike_snapshot)
    assert len(spike_events) == 1
    assert spike_events[0].resource == "network"
    assert spike_events[0].metric == "network_download_throughput"
