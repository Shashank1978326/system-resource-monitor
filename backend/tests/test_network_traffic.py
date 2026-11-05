"""Tests for independently sampled per-interface network traffic."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.monitoring import NetworkInterfaceResponse, NetworkResponse
from app.services import network_service


def _counter(received: int, sent: int, packets_received: int = 0, packets_sent: int = 0):
    return SimpleNamespace(
        bytes_recv=received,
        bytes_sent=sent,
        packets_recv=packets_received,
        packets_sent=packets_sent,
    )


def test_multiple_interfaces_have_independent_directional_speeds() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"a": _counter(100, 500, 1, 5), "b": _counter(1_000, 50, 10, 1)},
                _counter(10_000, 20_000),
                {"a": _counter(300, 500, 3, 5), "b": _counter(1_000, 250, 10, 3)},
                _counter(10_200, 20_200),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[10.0, 12.0],
        ),
    ):
        network_service.get_network_info()
        response = network_service.get_network_info()

    interfaces = {item.name: item for item in response.interfaces}
    assert interfaces["a"].download_speed_bytes_per_sec == 100
    assert interfaces["a"].upload_speed_bytes_per_sec == 0
    assert interfaces["b"].download_speed_bytes_per_sec == 0
    assert interfaces["b"].upload_speed_bytes_per_sec == 100
    assert interfaces["a"].download_speed_mb_per_sec == 100 / 1024**2
    assert interfaces["a"].bytes_received == 300
    assert interfaces["b"].packets_sent == 3


def test_first_sample_has_initializing_status_and_null_speeds() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth0": _counter(100, 200)},
                _counter(100, 200),
            ],
        ),
        patch("app.services.network_service.time.monotonic", return_value=1.0),
    ):
        response = network_service.get_network_info()

    item = response.interfaces[0]
    assert item.download_speed_bytes_per_sec is None
    assert item.upload_speed_bytes_per_sec is None
    assert item.download_status == item.upload_status == "initializing"
    assert not item.download_available
    assert not item.upload_available


def test_counter_reset_invalidates_only_the_reset_direction() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth0": _counter(500, 100)},
                _counter(500, 100),
                {"eth0": _counter(20, 200)},
                _counter(20, 200),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 2.0],
        ),
    ):
        network_service.get_network_info()
        item = network_service.get_network_info().interfaces[0]

    assert item.download_speed_bytes_per_sec is None
    assert item.download_status == "initializing"
    assert item.upload_speed_bytes_per_sec == 100
    assert item.upload_status == "available"


def test_invalid_elapsed_time_keeps_rates_unavailable_until_valid_sample() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth0": _counter(10, 20)},
                _counter(10, 20),
                {"eth0": _counter(20, 30)},
                _counter(20, 30),
                {"eth0": _counter(40, 50)},
                _counter(40, 50),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 1.0, 2.0],
        ),
    ):
        network_service.get_network_info()
        invalid = network_service.get_network_info().interfaces[0]
        valid = network_service.get_network_info().interfaces[0]

    assert invalid.download_speed_bytes_per_sec is None
    assert invalid.upload_speed_bytes_per_sec is None
    assert invalid.download_status == invalid.upload_status == "initializing"
    assert valid.download_speed_bytes_per_sec == 20
    assert valid.upload_speed_bytes_per_sec == 20


def test_zero_counter_delta_is_available_zero_traffic() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth0": _counter(100, 200)},
                _counter(100, 200),
                {"eth0": _counter(100, 200)},
                _counter(100, 200),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 2.0],
        ),
    ):
        network_service.get_network_info()
        item = network_service.get_network_info().interfaces[0]

    assert item.download_speed_bytes_per_sec == 0
    assert item.upload_speed_bytes_per_sec == 0
    assert item.download_available and item.upload_available
    assert item.download_status == item.upload_status == "available"


def test_missing_interface_counters_are_unavailable_without_hiding_others() -> None:
    network_service.reset_network_sampler()
    addresses = {"missing": [], "present": []}
    with (
        patch(
            "app.services.network_service.psutil.net_if_addrs",
            return_value=addresses,
        ),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"present": _counter(100, 100)},
                _counter(100, 100),
                {"present": _counter(200, 300)},
                _counter(200, 300),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 2.0],
        ),
    ):
        network_service.get_network_info()
        response = network_service.get_network_info()

    interfaces = {item.name: item for item in response.interfaces}
    assert interfaces["missing"].download_status == "unavailable"
    assert interfaces["missing"].upload_status == "unavailable"
    assert interfaces["missing"].bytes_received is None
    assert interfaces["present"].download_speed_bytes_per_sec == 100
    assert interfaces["present"].upload_speed_bytes_per_sec == 200


def test_a_failing_interface_does_not_block_other_interfaces() -> None:
    class BrokenCounter:
        @property
        def bytes_recv(self):
            raise OSError("interface counters unavailable")

        bytes_sent = 10
        packets_recv = 0
        packets_sent = 0

    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"broken": BrokenCounter(), "healthy": _counter(100, 100)},
                _counter(200, 200),
                {"broken": BrokenCounter(), "healthy": _counter(200, 300)},
                _counter(300, 400),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 2.0],
        ),
    ):
        network_service.get_network_info()
        response = network_service.get_network_info()

    interfaces = {item.name: item for item in response.interfaces}
    assert interfaces["broken"].download_status == "unavailable"
    assert interfaces["broken"].upload_speed_bytes_per_sec == 0
    assert interfaces["healthy"].download_speed_bytes_per_sec == 100
    assert interfaces["healthy"].upload_speed_bytes_per_sec == 200


def test_per_interface_traffic_endpoint_response_structure() -> None:
    network = NetworkResponse(
        bytes_received=1000,
        bytes_sent=2000,
        packets_received=10,
        packets_sent=20,
        download_speed_bytes_per_sec=100,
        upload_speed_bytes_per_sec=200,
        download_speed_mbps=0.0008,
        upload_speed_mbps=0.0016,
        interfaces=[
            NetworkInterfaceResponse(
                name="eth0",
                is_up=True,
                speed_mbps=1000,
                mtu=1500,
                addresses=[],
                bytes_received=1000,
                bytes_sent=2000,
                packets_received=10,
                packets_sent=20,
                download_speed_bytes_per_sec=100,
                download_speed_mb_per_sec=100 / 1024**2,
                download_available=True,
                download_status="available",
                upload_speed_bytes_per_sec=200,
                upload_speed_mb_per_sec=200 / 1024**2,
                upload_available=True,
                upload_status="available",
            )
        ],
    )
    snapshot = SimpleNamespace(timestamp="2026-11-03T00:00:00+00:00", network=network)
    with (
        patch(
            "app.api.routes.network.monitoring_service.get_snapshot",
            return_value=snapshot,
        ),
        TestClient(app) as client,
    ):
        response = client.get("/api/network/interfaces/traffic")

    assert response.status_code == 200
    assert response.json() == {
        "timestamp": "2026-11-03T00:00:00+00:00",
        "interfaces": [
            {
                "name": "eth0",
                "download_speed_bytes_per_sec": 100.0,
                "download_speed_mb_per_sec": 100 / 1024**2,
                "upload_speed_bytes_per_sec": 200.0,
                "upload_speed_mb_per_sec": 200 / 1024**2,
                "bytes_received": 1000,
                "bytes_sent": 2000,
                "packets_received": 10,
                "packets_sent": 20,
                "download_available": True,
                "download_status": "available",
                "upload_available": True,
                "upload_status": "available",
            }
        ],
    }


def test_existing_aggregate_speed_calculation_remains_available() -> None:
    network_service.reset_network_sampler()
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
        patch(
            "app.services.network_service.psutil.net_io_counters",
            side_effect=[
                {"eth0": _counter(100, 200)},
                _counter(1000, 2000),
                {"eth0": _counter(300, 500)},
                _counter(1200, 2300),
            ],
        ),
        patch(
            "app.services.network_service.time.monotonic",
            side_effect=[1.0, 3.0],
        ),
    ):
        network_service.get_network_info()
        response = network_service.get_network_info()

    assert response.download_speed_bytes_per_sec == 100
    assert response.upload_speed_bytes_per_sec == 150
