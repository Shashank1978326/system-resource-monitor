"""Disk read-speed sampling and API tests using mocked psutil counters."""

from types import SimpleNamespace
from unittest.mock import patch

import psutil
from fastapi.testclient import TestClient

from app.api.routes import disk as disk_route
from app.main import app
from app.schemas.monitoring import DiskIoResponse, DiskIoSpeedResponse
from app.services import disk_service


def _counters(read_bytes=0, write_bytes=100, read_count=0, write_count=2):
    return SimpleNamespace(
        read_bytes=read_bytes,
        write_bytes=write_bytes,
        read_count=read_count,
        write_count=write_count,
    )


def test_disk_read_speed_initial_sample_sets_baseline_without_zero(monkeypatch):
    disk_service.reset_disk_sampler()
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(read_bytes=1024, read_count=4),
    )

    io = disk_service._disk_io()

    assert io.read_bytes == 1024
    assert io.read_count == 4
    assert io.read_speed_bytes_per_sec is None
    assert io.read_speed_mb_per_sec is None
    assert io.read_speed_status == "initializing"


def test_disk_read_speed_calculates_bytes_per_second_and_megabytes_per_second(
    monkeypatch,
):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 12.0))
    counters = iter(
        (
            _counters(read_bytes=1_000_000, read_count=10),
            _counters(read_bytes=5_194_304, read_count=21),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    io = disk_service._disk_io()

    assert io.read_bytes == 5_194_304
    assert io.read_count == 21
    assert io.read_speed_bytes_per_sec == 2_097_152
    assert io.read_speed_mb_per_sec == 2
    assert io.read_speed_status == "available"


def test_disk_write_speed_calculates_bytes_per_second_and_megabytes_per_second(
    monkeypatch,
):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 12.0))
    counters = iter(
        (
            _counters(read_bytes=100, write_bytes=1_000_000, read_count=1),
            _counters(read_bytes=100, write_bytes=5_194_304, read_count=1),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    io = disk_service._disk_io()

    assert io.write_bytes == 5_194_304
    assert io.write_count == 2
    assert io.write_speed_bytes_per_sec == 2_097_152
    assert io.write_speed_mb_per_sec == 2
    assert io.write_speed_status == "available"
    assert io.read_speed_bytes_per_sec == 0


def test_disk_write_initial_sample_has_no_fabricated_speed(monkeypatch):
    disk_service.reset_disk_sampler()
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(write_bytes=512, read_bytes=2048, read_count=5),
    )

    io = disk_service._disk_io()

    assert io.write_bytes == 512
    assert io.write_count == 2
    assert io.write_speed_bytes_per_sec is None
    assert io.write_speed_mb_per_sec is None
    assert io.write_speed_status == "initializing"


def test_disk_write_counter_reset_reestablishes_baseline(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0, 12.0))
    counters = iter(
        (
            _counters(write_bytes=1000),
            _counters(write_bytes=100),
            _counters(write_bytes=300),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    reset_sample = disk_service._disk_io()
    recovered = disk_service._disk_io()

    assert reset_sample.write_speed_bytes_per_sec is None
    assert reset_sample.write_speed_status == "initializing"
    assert recovered.write_speed_bytes_per_sec == 200
    assert recovered.write_speed_status == "available"


def test_disk_write_zero_elapsed_time_is_unavailable_for_that_sample(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 10.0, 11.0))
    counters = iter(
        (
            _counters(write_bytes=100),
            _counters(write_bytes=200),
            _counters(write_bytes=300),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    invalid_elapsed = disk_service._disk_io()
    next_sample = disk_service._disk_io()

    assert invalid_elapsed.write_speed_bytes_per_sec is None
    assert invalid_elapsed.write_speed_status == "initializing"
    assert next_sample.write_speed_bytes_per_sec == 100


def test_disk_write_zero_delta_returns_genuine_zero(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0))
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(write_bytes=500),
    )

    disk_service._disk_io()
    io = disk_service._disk_io()

    assert io.write_speed_bytes_per_sec == 0
    assert io.write_speed_mb_per_sec == 0
    assert io.write_speed_status == "available"


def test_missing_write_counter_does_not_disturb_read_speed_baseline(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0, 12.0))
    counters = iter(
        (
            _counters(read_bytes=100, write_bytes=100),
            SimpleNamespace(read_bytes=200, read_count=2),
            _counters(read_bytes=300, write_bytes=300),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    missing_write = disk_service._disk_io()
    new_write_baseline = disk_service._disk_io()

    assert missing_write.read_speed_bytes_per_sec == 100
    assert missing_write.write_speed_bytes_per_sec is None
    assert missing_write.write_speed_status == "unavailable"
    assert new_write_baseline.read_speed_bytes_per_sec == 100
    assert new_write_baseline.write_speed_bytes_per_sec is None
    assert new_write_baseline.write_speed_status == "initializing"


def test_disk_read_speed_reports_real_zero_counter_increment(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0))
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(read_bytes=500, read_count=2),
    )

    disk_service._disk_io()
    io = disk_service._disk_io()

    assert io.read_speed_bytes_per_sec == 0
    assert io.read_speed_mb_per_sec == 0
    assert io.read_speed_status == "available"


def test_disk_counter_reset_reestablishes_baseline(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0, 12.0))
    counters = iter(
        (
            _counters(read_bytes=1000),
            _counters(read_bytes=100),
            _counters(read_bytes=300),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    reset_sample = disk_service._disk_io()
    recovered_sample = disk_service._disk_io()

    assert reset_sample.read_speed_bytes_per_sec is None
    assert reset_sample.read_speed_status == "initializing"
    assert recovered_sample.read_speed_bytes_per_sec == 200
    assert recovered_sample.read_speed_status == "available"


def test_zero_elapsed_time_does_not_create_speed_and_resets_baseline(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 10.0, 11.0))
    counters = iter(
        (
            _counters(read_bytes=100),
            _counters(read_bytes=200),
            _counters(read_bytes=300),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    zero_elapsed_sample = disk_service._disk_io()
    next_sample = disk_service._disk_io()

    assert zero_elapsed_sample.read_speed_bytes_per_sec is None
    assert zero_elapsed_sample.read_speed_status == "initializing"
    assert next_sample.read_speed_bytes_per_sec == 100


def test_missing_counters_make_speed_unavailable_and_clear_baseline(monkeypatch):
    disk_service.reset_disk_sampler()
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(read_bytes=100),
    )
    disk_service._disk_io()

    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: None,
    )
    unavailable = disk_service._disk_io()

    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: _counters(read_bytes=200),
    )
    baseline = disk_service._disk_io()

    assert unavailable.read_bytes is None
    assert unavailable.read_speed_bytes_per_sec is None
    assert unavailable.read_speed_status == "unavailable"
    assert baseline.read_speed_bytes_per_sec is None
    assert baseline.read_speed_status == "initializing"


def test_unsupported_disk_statistics_return_unavailable_metrics(monkeypatch):
    disk_service.reset_disk_sampler()
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: (_ for _ in ()).throw(NotImplementedError()),
    )

    io = disk_service._disk_io()

    assert io.read_bytes is None
    assert io.read_count is None
    assert io.read_speed_bytes_per_sec is None
    assert io.read_speed_status == "unavailable"


def test_psutil_error_returns_unavailable_metrics(monkeypatch):
    disk_service.reset_disk_sampler()
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: (_ for _ in ()).throw(psutil.Error()),
    )

    io = disk_service._disk_io()

    assert io.read_bytes is None
    assert io.read_speed_bytes_per_sec is None
    assert io.read_speed_status == "unavailable"


def test_invalid_read_counter_is_not_used_for_speed(monkeypatch):
    disk_service.reset_disk_sampler()
    times = iter((10.0, 11.0))
    counters = iter(
        (
            _counters(read_bytes=100),
            SimpleNamespace(read_bytes=-1, read_count=-1),
        )
    )
    monkeypatch.setattr(disk_service.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(
        disk_service.psutil,
        "disk_io_counters",
        lambda **_: next(counters),
    )

    disk_service._disk_io()
    io = disk_service._disk_io()

    assert io.read_bytes is None
    assert io.read_count is None
    assert io.read_speed_bytes_per_sec is None
    assert io.read_speed_status == "unavailable"


def test_disk_io_endpoint_returns_latest_snapshot(monkeypatch):
    io = DiskIoResponse(
        read_bytes=4096,
        write_bytes=2048,
        read_count=12,
        write_count=7,
        read_speed_bytes_per_sec=1024,
        read_speed_mb_per_sec=1 / 1024,
        read_speed_status="available",
        write_speed_bytes_per_sec=2048,
        write_speed_mb_per_sec=2 / 1024,
        write_speed_status="available",
    )
    monkeypatch.setattr(
        disk_route.monitoring_service,
        "get_snapshot",
        lambda: SimpleNamespace(
            timestamp="2026-11-03T00:00:00+00:00",
            disk=SimpleNamespace(io=io),
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/disk/io")

    assert response.status_code == 200
    assert response.json() == DiskIoSpeedResponse(
        timestamp="2026-11-03T00:00:00+00:00",
        total_bytes_read=4096,
        read_operations=12,
        read_speed_bytes_per_sec=1024,
        read_speed_mb_per_sec=1 / 1024,
        available=True,
        status="available",
        message=None,
        total_bytes_written=2048,
        write_operations=7,
        write_speed_bytes_per_sec=2048,
        write_speed_mb_per_sec=2 / 1024,
        write_available=True,
        write_status="available",
        write_message=None,
    ).model_dump()
