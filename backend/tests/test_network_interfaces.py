"""Tests for network-interface discovery and its public API."""

import socket
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
import psutil

from app.main import app


def _address(family: int, address: str, netmask: str | None = None):
    return SimpleNamespace(family=family, address=address, netmask=netmask)


def test_interfaces_endpoint_returns_multiple_interface_details() -> None:
    link_family = psutil.AF_LINK
    addresses = {
        "lo": [_address(socket.AF_INET, "127.0.0.1", "255.0.0.0")],
        "ethernet0": [
            _address(socket.AF_INET, "192.168.1.20", "255.255.255.0"),
            _address(socket.AF_INET6, "2001:db8::1", "64"),
            _address(link_family, "00:11:22:33:44:55"),
        ],
    }
    stats = {
        "lo": SimpleNamespace(isup=True, speed=0, mtu=65536),
        "ethernet0": SimpleNamespace(isup=True, speed=1000, mtu=1500),
        "offline": SimpleNamespace(isup=False, speed=100, mtu=1400),
    }
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value=addresses),
        patch("app.services.network_service.psutil.net_if_stats", return_value=stats),
        TestClient(app) as client,
    ):
        response = client.get("/api/network/interfaces")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {"interfaces"}
    assert [item["name"] for item in data["interfaces"]] == [
        "ethernet0",
        "lo",
        "offline",
    ]
    ethernet = data["interfaces"][0]
    assert ethernet == {
        "name": "ethernet0",
        "is_up": True,
        "mac_address": "00:11:22:33:44:55",
        "ipv4_address": "192.168.1.20",
        "ipv4_netmask": "255.255.255.0",
        "ipv6_address": "2001:db8::1",
        "ipv6_netmask": "64",
        "mtu": 1500,
        "speed_mbps": 1000.0,
        "is_loopback": False,
        "is_virtual": None,
    }
    assert data["interfaces"][1]["is_loopback"] is True
    assert data["interfaces"][2]["is_up"] is False
    assert data["interfaces"][2]["ipv4_address"] is None


def test_missing_addresses_and_statistics_are_returned_as_null() -> None:
    with (
        patch(
            "app.services.network_service.psutil.net_if_addrs",
            return_value={"unknown0": []},
        ),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
    ):
        from app.services.network_service import get_network_interfaces

        response = get_network_interfaces()

    assert [item.model_dump() for item in response.interfaces] == [
        {
            "name": "unknown0",
            "is_up": None,
            "mac_address": None,
            "ipv4_address": None,
            "ipv4_netmask": None,
            "ipv6_address": None,
            "ipv6_netmask": None,
            "mtu": None,
            "speed_mbps": None,
            "is_loopback": None,
            "is_virtual": None,
        }
    ]


def test_interface_addresses_remain_available_when_stats_are_inaccessible() -> None:
    with (
        patch(
            "app.services.network_service.psutil.net_if_addrs",
            return_value={
                "ethernet0": [_address(socket.AF_INET, "192.0.2.10", "255.255.255.0")]
            },
        ),
        patch(
            "app.services.network_service.psutil.net_if_stats",
            side_effect=PermissionError,
        ),
    ):
        from app.services.network_service import get_network_interfaces

        interfaces = get_network_interfaces().interfaces

    assert len(interfaces) == 1
    assert interfaces[0].ipv4_address == "192.0.2.10"
    assert interfaces[0].is_up is None
    assert interfaces[0].mtu is None


def test_permission_errors_return_valid_empty_interface_list() -> None:
    with (
        patch(
            "app.services.network_service.psutil.net_if_addrs",
            side_effect=PermissionError,
        ),
        patch(
            "app.services.network_service.psutil.net_if_stats",
            side_effect=PermissionError,
        ),
    ):
        from app.services.network_service import get_network_interfaces

        response = get_network_interfaces()

    assert response.interfaces == []


def test_empty_interface_mappings_return_empty_list() -> None:
    with (
        patch("app.services.network_service.psutil.net_if_addrs", return_value={}),
        patch("app.services.network_service.psutil.net_if_stats", return_value={}),
    ):
        from app.services.network_service import get_network_interfaces

        response = get_network_interfaces()

    assert response.interfaces == []
