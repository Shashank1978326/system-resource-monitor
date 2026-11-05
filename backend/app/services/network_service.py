"""Network interface counters and interval-based speed sampling."""

import ipaddress
import socket
import threading
import time
from collections.abc import Callable, Mapping
from typing import NamedTuple

import psutil

from app.schemas.monitoring import (
    NetworkInterfaceDetailsResponse,
    NetworkInterfaceResponse,
    NetworkInterfaceTrafficListResponse,
    NetworkInterfaceTrafficResponse,
    NetworkInterfacesResponse,
    NetworkResponse,
)


class _NetworkBaseline(NamedTuple):
    timestamp: float
    counters: dict[str, tuple[int, int]]
    interface_counters: dict[str, tuple[int | None, int | None]]


_lock = threading.Lock()
_baseline: _NetworkBaseline | None = None


def reset_network_sampler() -> None:
    """Clear interface baselines when the background monitor restarts."""
    global _baseline
    with _lock:
        _baseline = None


def _safe_mapping(
    callable_metric: Callable[[], Mapping[str, object]],
) -> dict[str, object]:
    try:
        result = callable_metric()
    except (OSError, psutil.Error):
        return {}
    return dict(result) if isinstance(result, Mapping) else {}


def _counter_value(counters: object, key: str) -> int | None:
    try:
        value = getattr(counters, key, None)
    except (OSError, psutil.Error):
        return None
    return value if isinstance(value, int) and value >= 0 else None


def get_network_interfaces() -> NetworkInterfacesResponse:
    """Return available interface details without changing aggregate sampling."""
    addresses = _safe_mapping(psutil.net_if_addrs)
    stats = _safe_mapping(psutil.net_if_stats)
    link_families = {
        family
        for family in (
            getattr(psutil, "AF_LINK", None),
            getattr(socket, "AF_PACKET", None),
        )
        if family is not None
    }

    interfaces: list[NetworkInterfaceDetailsResponse] = []
    for name in sorted(set(addresses) | set(stats)):
        ipv4_address = ipv4_netmask = None
        ipv6_address = ipv6_netmask = None
        mac_address = None
        has_ip_address = False
        is_loopback = False

        for address in addresses.get(name, []):
            raw_address = getattr(address, "address", None)
            if not isinstance(raw_address, str) or not raw_address:
                continue
            family = getattr(address, "family", None)
            if family in link_families:
                mac_address = mac_address or raw_address
                continue

            try:
                parsed_address = ipaddress.ip_address(raw_address.split("%", 1)[0])
            except ValueError:
                continue

            has_ip_address = True
            is_loopback = is_loopback or parsed_address.is_loopback
            netmask = getattr(address, "netmask", None)
            if isinstance(parsed_address, ipaddress.IPv4Address):
                ipv4_address = ipv4_address or raw_address
                ipv4_netmask = ipv4_netmask or (
                    netmask if isinstance(netmask, str) else None
                )
            elif isinstance(parsed_address, ipaddress.IPv6Address):
                ipv6_address = ipv6_address or raw_address
                ipv6_netmask = ipv6_netmask or (
                    netmask if isinstance(netmask, str) else None
                )

        interface_stats = stats.get(name)
        is_up = getattr(interface_stats, "isup", None)
        if not isinstance(is_up, bool):
            is_up = None
        speed = getattr(interface_stats, "speed", None)
        if not isinstance(speed, (int, float)) or speed <= 0:
            speed = None
        mtu = getattr(interface_stats, "mtu", None)
        if not isinstance(mtu, int) or mtu <= 0:
            mtu = None

        interfaces.append(
            NetworkInterfaceDetailsResponse(
                name=name,
                is_up=is_up,
                mac_address=mac_address,
                ipv4_address=ipv4_address,
                ipv4_netmask=ipv4_netmask,
                ipv6_address=ipv6_address,
                ipv6_netmask=ipv6_netmask,
                mtu=mtu,
                speed_mbps=speed,
                is_loopback=is_loopback if has_ip_address else None,
                # psutil does not expose a portable virtual-interface flag.
                is_virtual=None,
            )
        )
    return NetworkInterfacesResponse(interfaces=interfaces)


def get_network_info() -> NetworkResponse:
    """Return per-interface counters and speeds derived from elapsed time."""
    global _baseline

    addresses = _safe_mapping(psutil.net_if_addrs)
    stats = _safe_mapping(psutil.net_if_stats)
    per_interface = _safe_mapping(lambda: psutil.net_io_counters(pernic=True))
    now = time.monotonic()

    interfaces: list[NetworkInterfaceResponse] = []
    current_counters: dict[str, tuple[int, int]] = {}
    interface_counters: dict[str, tuple[int | None, int | None]] = {}
    names = set(addresses) | set(stats) | set(per_interface)
    for name in sorted(names):
        counter = per_interface.get(name)
        received = _counter_value(counter, "bytes_recv") if counter else None
        sent = _counter_value(counter, "bytes_sent") if counter else None
        interface_counters[name] = (received, sent)
        if received is not None and sent is not None:
            current_counters[name] = (received, sent)

        interface_stats = stats.get(name)
        interface_addresses = addresses.get(name, [])
        interfaces.append(
            NetworkInterfaceResponse(
                name=name,
                is_up=getattr(interface_stats, "isup", None),
                speed_mbps=getattr(interface_stats, "speed", None),
                mtu=getattr(interface_stats, "mtu", None),
                addresses=[
                    address.address
                    for address in interface_addresses
                    if getattr(address, "address", None)
                ],
                bytes_received=received,
                bytes_sent=sent,
                packets_received=_counter_value(counter, "packets_recv") if counter else None,
                packets_sent=_counter_value(counter, "packets_sent") if counter else None,
            )
        )

    aggregate = None
    try:
        aggregate = psutil.net_io_counters(pernic=False)
    except (OSError, psutil.Error):
        pass

    received_total = _counter_value(aggregate, "bytes_recv") if aggregate else None
    sent_total = _counter_value(aggregate, "bytes_sent") if aggregate else None
    packets_received = _counter_value(aggregate, "packets_recv") if aggregate else None
    packets_sent = _counter_value(aggregate, "packets_sent") if aggregate else None

    download_speed: float | None = None
    upload_speed: float | None = None
    interface_rates: dict[str, tuple[float | None, float | None, str, str]] = {}
    with _lock:
        previous = _baseline
        if previous is not None:
            elapsed = now - previous.timestamp
            if elapsed > 0:
                # Ignore new interfaces and reset counters; their baseline starts now.
                download_delta = sum(
                    current[0] - previous.counters[name][0]
                    for name, current in current_counters.items()
                    if name in previous.counters
                    and current[0] is not None
                    and previous.counters[name][0] is not None
                    and current[0] >= previous.counters[name][0]
                )
                upload_delta = sum(
                    current[1] - previous.counters[name][1]
                    for name, current in current_counters.items()
                    if name in previous.counters
                    and current[1] is not None
                    and previous.counters[name][1] is not None
                    and current[1] >= previous.counters[name][1]
                )
                download_speed = download_delta / elapsed
                upload_speed = upload_delta / elapsed

            for name, current in interface_counters.items():
                old = previous.interface_counters.get(name)
                if old is None:
                    continue
                received_now, sent_now = current
                received_before, sent_before = old
                download = (
                    (received_now - received_before) / elapsed
                    if elapsed > 0
                    and received_now is not None
                    and received_before is not None
                    and received_now >= received_before
                    else None
                )
                upload = (
                    (sent_now - sent_before) / elapsed
                    if elapsed > 0
                    and sent_now is not None
                    and sent_before is not None
                    and sent_now >= sent_before
                    else None
                )
                interface_rates[name] = (
                    download,
                    upload,
                    _rate_status(received_now, received_before, download, elapsed),
                    _rate_status(sent_now, sent_before, upload, elapsed),
                )

        for name, counters in interface_counters.items():
            if name not in interface_rates:
                interface_rates[name] = (
                    None,
                    None,
                    "initializing" if counters[0] is not None else "unavailable",
                    "initializing" if counters[1] is not None else "unavailable",
                )
        _baseline = _NetworkBaseline(now, current_counters, interface_counters)

    for item in interfaces:
        download, upload, download_status, upload_status = interface_rates[item.name]
        item.download_speed_bytes_per_sec = download
        item.download_speed_mb_per_sec = (
            download / 1024**2 if download is not None else None
        )
        item.download_available = download_status == "available"
        item.download_status = download_status
        item.upload_speed_bytes_per_sec = upload
        item.upload_speed_mb_per_sec = (
            upload / 1024**2 if upload is not None else None
        )
        item.upload_available = upload_status == "available"
        item.upload_status = upload_status

    return NetworkResponse(
        bytes_received=received_total,
        bytes_sent=sent_total,
        packets_received=packets_received,
        packets_sent=packets_sent,
        download_speed_bytes_per_sec=download_speed,
        upload_speed_bytes_per_sec=upload_speed,
        download_speed_mbps=download_speed * 8 / 1_000_000 if download_speed is not None else None,
        upload_speed_mbps=upload_speed * 8 / 1_000_000 if upload_speed is not None else None,
        interfaces=interfaces,
    )


def _rate_status(
    current: int | None,
    previous: int | None,
    rate: float | None,
    elapsed: float,
) -> str:
    if current is None:
        return "unavailable"
    if previous is None or elapsed <= 0 or rate is None:
        return "initializing"
    return "available"


def get_network_traffic(
    timestamp: str, network: NetworkResponse
) -> NetworkInterfaceTrafficListResponse:
    """Build the public per-interface traffic response from the latest sample."""
    return NetworkInterfaceTrafficListResponse(
        timestamp=timestamp,
        interfaces=[
            NetworkInterfaceTrafficResponse(
                name=item.name,
                download_speed_bytes_per_sec=item.download_speed_bytes_per_sec,
                download_speed_mb_per_sec=item.download_speed_mb_per_sec,
                upload_speed_bytes_per_sec=item.upload_speed_bytes_per_sec,
                upload_speed_mb_per_sec=item.upload_speed_mb_per_sec,
                bytes_received=item.bytes_received,
                bytes_sent=item.bytes_sent,
                packets_received=item.packets_received,
                packets_sent=item.packets_sent,
                download_available=item.download_available,
                download_status=item.download_status,
                upload_available=item.upload_available,
                upload_status=item.upload_status,
            )
            for item in network.interfaces
        ],
    )
