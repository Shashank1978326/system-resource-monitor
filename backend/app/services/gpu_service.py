"""Cross-platform multi-GPU detection with NVIDIA NVML and OS telemetry providers."""

import ctypes
from ctypes import wintypes
import importlib
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.monitoring import (
    GpuDeviceInfoResponse,
    GpuInfoResponse,
    GpuListResponse,
    GpuSummaryItem,
    GpuUsageDeviceResponse,
    GpuUsageResponse,
)

logger = logging.getLogger(__name__)
_NVML_LOCK = threading.RLock()
_GPU_USAGE_CACHE_SECONDS = 2.0
_GPU_DETECTION_CACHE_SECONDS = 30.0
_gpu_usage_cache: tuple[float, GpuUsageResponse] | None = None
_gpu_detection_cache: tuple[
    float, list[GpuDeviceInfoResponse], bool
] | None = None

_PCI_VENDOR_NAMES = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
}

_DXGI_VENDOR_NAMES = {
    0x10DE: "NVIDIA",
    0x1002: "AMD",
    0x8086: "Intel",
}


def _manufacturer(value: object, hardware_id: object = None) -> str:
    """Normalize vendor names and PCI identifiers without guessing unknowns."""
    identifier = str(hardware_id or "").lower()
    pci_match = re.search(r"(?:ven_|0x)(10de|1002|8086)", identifier)
    if pci_match:
        return {
            "10de": "NVIDIA",
            "1002": "AMD",
            "8086": "Intel",
        }[pci_match.group(1)]
    name = str(value or "").lower()
    for token, label in (
        ("nvidia", "NVIDIA"),
        ("geforce", "NVIDIA"),
        ("quadro", "NVIDIA"),
        ("amd", "AMD"),
        ("radeon", "AMD"),
        ("advanced micro", "AMD"),
        ("intel", "Intel"),
        ("uhd graphics", "Intel"),
        ("iris", "Intel"),
    ):
        if token in name:
            return label
    if re.search(r"\bati\b", name):
        return "AMD"
    return "Unknown"


def _gpu_type(manufacturer: str | None, model: str | None) -> str:
    """Distinguish Integrated vs Dedicated GPUs from vendor and hardware name."""
    man = (manufacturer or "").lower()
    mod = (model or "").lower()
    if man == "intel":
        if "arc" in mod or "discrete" in mod:
            return "Dedicated"
        return "Integrated"
    if man == "nvidia":
        return "Dedicated"
    if man == "amd":
        if any(
            token in mod
            for token in (
                "integrated",
                "radeon(tm) graphics",
                "vega 3",
                "vega 6",
                "vega 7",
                "vega 8",
                "vega 10",
                "vega 11",
                "780m",
                "680m",
            )
        ):
            return "Integrated"
        return "Dedicated"
    if any(token in mod for token in ("integrated", "uhd", "iris", "hd graphics")):
        return "Integrated"
    return "Unknown"


def _activity_status(
    utilization_percent: float | None,
    available: bool,
) -> str:
    """Derive Active / Idle / Unavailable state strictly from hardware telemetry."""
    if utilization_percent is not None:
        return "Active" if utilization_percent >= 1.0 else "Idle"
    if available:
        return "Idle"
    return "Unavailable"


def _windows_gpu_devices() -> tuple[list[GpuDeviceInfoResponse], bool]:
    """Detect Windows display adapters through built-in CIM, without a package."""
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        return [], False
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterCompatibility,PNPDeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            check=False,
            text=True,
            timeout=4,
        )
        if result.returncode != 0:
            logger.info("Windows GPU enumeration failed (exit %s)", result.returncode)
            return [], False
        raw = json.loads(result.stdout) if result.stdout.strip() else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.info("Windows GPU enumeration unavailable: %s", type(exc).__name__)
        return [], False
    adapters = raw if isinstance(raw, list) else [raw]
    devices = []
    for index, adapter in enumerate(adapters):
        if not isinstance(adapter, dict):
            continue
        model = adapter.get("Name")
        if not isinstance(model, str) or not model.strip():
            continue
        vendor_name = adapter.get("AdapterCompatibility")
        manufacturer = _manufacturer(vendor_name, adapter.get("PNPDeviceID"))
        if manufacturer == "Unknown":
            manufacturer = _manufacturer(model, adapter.get("PNPDeviceID"))
        devices.append(
            GpuDeviceInfoResponse(
                device_index=index,
                manufacturer=manufacturer,
                model=model.strip(),
            )
        )
    return devices, True


def _windows_registry_gpu_devices() -> list[dict]:
    """Enumerate all physical display adapters from Windows Registry (including idle dGPUs)."""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    gpus: list[dict] = []
    class_guid = (
        r"SYSTEM\CurrentControlSet\Control\Class"
        r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
    )
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_guid) as key:
            subkey_count, _, _ = winreg.QueryInfoKey(key)
            for idx in range(subkey_count):
                subkey_name = winreg.EnumKey(key, idx)
                if not subkey_name.isdigit():
                    continue
                try:
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        def _read_reg(name: str):
                            try:
                                return winreg.QueryValueEx(subkey, name)[0]
                            except OSError:
                                return None

                        desc = _read_reg("DriverDesc")
                        provider = _read_reg("ProviderName")
                        matching_id = _read_reg("MatchingDeviceId")
                        driver_ver = _read_reg("DriverVersion")
                        mem_size = _read_reg("HardwareInformation.qwMemorySize")
                        if not desc or not isinstance(desc, str):
                            continue
                        if "microsoft basic" in desc.lower():
                            continue
                        manufacturer = _manufacturer(provider, matching_id)
                        if manufacturer == "Unknown":
                            manufacturer = _manufacturer(desc, matching_id)
                        total_mem = None
                        if isinstance(mem_size, int) and mem_size > 0:
                            total_mem = mem_size
                        gpus.append(
                            {
                                "model": desc.strip(),
                                "manufacturer": manufacturer,
                                "driver_version": (
                                    str(driver_ver).strip() if driver_ver else None
                                ),
                                "total_memory_bytes": total_mem,
                                "gpu_type": _gpu_type(manufacturer, desc),
                            }
                        )
                except OSError:
                    continue
    except OSError as exc:
        logger.debug("Windows Registry GPU enumeration unavailable: %s", exc)
    return gpus


def _get_dxgi_luids() -> dict[str, dict]:
    """Query DXGI adapters on Windows for LUID mapping and shared memory limits."""
    if sys.platform != "win32":
        return {}

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _DXGI_ADAPTER_DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", _LUID),
            ("Flags", wintypes.UINT),
        ]

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    results: dict[str, dict] = {}
    try:
        dxgi = ctypes.windll.dxgi
        iid_factory1 = _GUID(
            0x770AAE78,
            0xF26F,
            0x4DBA,
            (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
        )
        factory_ptr = ctypes.c_void_p()
        hr = dxgi.CreateDXGIFactory1(
            ctypes.byref(iid_factory1), ctypes.byref(factory_ptr)
        )
        if hr != 0 or not factory_ptr.value:
            return {}

        vtable = ctypes.cast(
            factory_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
        ).contents
        enum_adapters1 = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
        )(vtable[12])
        get_desc1_proto = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(_DXGI_ADAPTER_DESC1),
        )
        release_proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

        for index in range(16):
            adapter_ptr = ctypes.c_void_p()
            if enum_adapters1(factory_ptr, index, ctypes.byref(adapter_ptr)) != 0:
                break
            adapter_vtable = ctypes.cast(
                adapter_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
            ).contents
            desc = _DXGI_ADAPTER_DESC1()
            if get_desc1_proto(adapter_vtable[10])(
                adapter_ptr, ctypes.byref(desc)
            ) == 0:
                luid_hex = f"0x{desc.AdapterLuid.LowPart:08x}".lower()
                results[luid_hex] = {
                    "description": desc.Description,
                    "vendor_id": int(desc.VendorId),
                    "manufacturer": _DXGI_VENDOR_NAMES.get(
                        int(desc.VendorId), _manufacturer(desc.Description)
                    ),
                    "dedicated_vram_bytes": int(desc.DedicatedVideoMemory),
                    "shared_ram_bytes": int(desc.SharedSystemMemory),
                    "flags": int(desc.Flags),
                }
            release_proto(adapter_vtable[2])(adapter_ptr)
        release_proto(vtable[2])(factory_ptr)
    except Exception as exc:
        logger.debug("DXGI enumeration unavailable: %s", exc)
    return results


def _merge_windows_devices(
    cim_devices: list[GpuDeviceInfoResponse],
    registry_devices: list[dict],
    dxgi_luids: dict[str, dict],
) -> list[GpuDeviceInfoResponse]:
    """Combine Windows Registry, CIM, and DXGI info so idle discrete GPUs are never missed."""
    merged: list[GpuDeviceInfoResponse] = []
    seen_models: set[str] = set()

    # Look up DXGI shared memory budget by manufacturer
    dxgi_by_vendor: dict[str, dict] = {}
    for entry in dxgi_luids.values():
        vendor = entry.get("manufacturer", "Unknown")
        if vendor != "Unknown" and vendor not in dxgi_by_vendor:
            dxgi_by_vendor[vendor] = entry

    default_shared_bytes = next(
        (
            e["shared_ram_bytes"]
            for e in dxgi_luids.values()
            if e.get("shared_ram_bytes", 0) > 0
        ),
        None,
    )

    for reg in registry_devices:
        model = reg["model"]
        manufacturer = reg["manufacturer"]
        norm_key = f"{manufacturer.lower()}::{model.lower()}"
        if norm_key in seen_models:
            continue
        seen_models.add(norm_key)
        dxgi_info = dxgi_by_vendor.get(manufacturer)
        shared_bytes = (
            dxgi_info["shared_ram_bytes"]
            if dxgi_info and dxgi_info.get("shared_ram_bytes")
            else default_shared_bytes
        )
        merged.append(
            GpuDeviceInfoResponse(
                device_index=len(merged),
                manufacturer=manufacturer,
                model=model,
                vendor=manufacturer,
                gpu_type=reg.get("gpu_type") or _gpu_type(manufacturer, model),
                total_memory_bytes=reg.get("total_memory_bytes"),
                shared_memory_bytes=shared_bytes,
                driver_version=reg.get("driver_version"),
                monitoring_supported=True,
            )
        )

    for cim in cim_devices:
        model = (cim.model or "").strip()
        manufacturer = cim.manufacturer or "Unknown"
        norm_key = f"{manufacturer.lower()}::{model.lower()}"
        already_present = any(
            norm_key == existing
            or (
                manufacturer.lower() == existing.split("::")[0]
                and (
                    model.lower() in existing.split("::")[1]
                    or existing.split("::")[1] in model.lower()
                )
            )
            for existing in seen_models
        )
        if not already_present:
            seen_models.add(norm_key)
            merged.append(
                GpuDeviceInfoResponse(
                    device_index=len(merged),
                    manufacturer=manufacturer,
                    model=model or None,
                    vendor=manufacturer,
                    gpu_type=cim.gpu_type or _gpu_type(manufacturer, model),
                    total_memory_bytes=cim.total_memory_bytes,
                    shared_memory_bytes=default_shared_bytes,
                    driver_version=cim.driver_version,
                    monitoring_supported=True,
                )
            )

    if not merged:
        return cim_devices

    # Sort cleanly: Integrated (index 0) or stable order, re-index cleanly
    for idx, item in enumerate(merged):
        item.device_index = idx
    return merged


def _query_windows_perf_counters() -> dict[str, dict]:
    """Read live per-LUID GPU utilization and memory via Windows Performance Counters."""
    if sys.platform != "win32":
        return {}
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None:
        return {}
    script = (
        "$m = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory "
        "-ErrorAction SilentlyContinue | Select-Object Name,DedicatedUsage,SharedUsage,TotalCommitted; "
        "$e = Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine "
        "-ErrorAction SilentlyContinue | Where-Object { $_.UtilizationPercentage -gt 0 } | "
        "Select-Object Name,UtilizationPercentage; "
        "@{Memory=$m; Engines=$e} | ConvertTo-Json -Depth 3 -Compress"
    )
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            check=False,
            text=True,
            timeout=4,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        logger.debug("Windows GPU performance counters unavailable: %s", type(exc).__name__)
        return {}

    mem_list = data.get("Memory") or []
    if isinstance(mem_list, dict):
        mem_list = [mem_list]
    eng_list = data.get("Engines") or []
    if isinstance(eng_list, dict):
        eng_list = [eng_list]

    luid_data: dict[str, dict] = {}
    for entry in mem_list:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or "")
        match = re.search(r"luid_0x[0-9a-fA-F]+_(0x[0-9a-fA-F]+)", name, re.IGNORECASE)
        if not match:
            continue
        luid_hex = match.group(1).lower()
        luid_data[luid_hex] = {
            "dedicated_bytes": int(entry.get("DedicatedUsage") or 0),
            "shared_bytes": int(entry.get("SharedUsage") or 0),
            "committed_bytes": int(entry.get("TotalCommitted") or 0),
            "util_percent": 0.0,
        }

    for entry in eng_list:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("Name") or "")
        util = entry.get("UtilizationPercentage")
        match = re.search(r"luid_0x[0-9a-fA-F]+_(0x[0-9a-fA-F]+)", name, re.IGNORECASE)
        if not match:
            continue
        luid_hex = match.group(1).lower()
        if luid_hex not in luid_data:
            luid_data[luid_hex] = {
                "dedicated_bytes": 0,
                "shared_bytes": 0,
                "committed_bytes": 0,
                "util_percent": 0.0,
            }
        try:
            util_val = float(util or 0.0)
            if math.isfinite(util_val) and util_val >= 0:
                luid_data[luid_hex]["util_percent"] = min(
                    100.0, luid_data[luid_hex]["util_percent"] + util_val
                )
        except (TypeError, ValueError):
            continue

    return luid_data


def _match_luid_for_device(
    device: GpuDeviceInfoResponse,
    dxgi_luids: dict[str, dict],
    perf_luids: dict[str, dict],
    assigned_luids: set[str],
) -> str | None:
    """Match a detected GPU adapter to its Windows DxgKrnl LUID."""
    man = (device.manufacturer or "").lower()
    mod = (device.model or "").lower()

    # 1. Exact vendor/description match in DXGI LUIDs that exist in perf_luids
    for luid_hex, info in dxgi_luids.items():
        if luid_hex in assigned_luids or luid_hex not in perf_luids:
            continue
        dxgi_man = (info.get("manufacturer") or "").lower()
        dxgi_desc = (info.get("description") or "").lower()
        if dxgi_man == man and man != "unknown":
            assigned_luids.add(luid_hex)
            return luid_hex
        if mod and dxgi_desc and (mod in dxgi_desc or dxgi_desc in mod):
            assigned_luids.add(luid_hex)
            return luid_hex

    # 2. Fallback: match remaining unassigned LUID (e.g. hybrid Optimus dGPU in D3Cold)
    for luid_hex in perf_luids:
        if luid_hex not in assigned_luids:
            assigned_luids.add(luid_hex)
            return luid_hex
    return None


def _linux_gpu_devices(
    drm_path: Path | None = None,
) -> tuple[list[GpuDeviceInfoResponse], bool]:
    """Detect DRM devices through sysfs; use lspci for optional model names."""
    drm_path = drm_path or Path("/sys/class/drm")
    if not drm_path.is_dir():
        return [], False
    pci_names: dict[str, str] = {}
    lspci = shutil.which("lspci")
    if lspci:
        try:
            result = subprocess.run(
                [lspci, "-D", "-nn"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    match = re.match(
                        r"^(\S+)\s+.*?:\s+(.+?)\s+\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]",
                        line,
                    )
                    if match:
                        pci_names[match.group(1).lower()] = match.group(2).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("Optional lspci model lookup failed: %s", type(exc).__name__)

    devices = []
    read_failures = False
    for entry in sorted(drm_path.iterdir(), key=lambda item: item.name):
        if not re.fullmatch(r"card\d+", entry.name):
            continue
        device_path = entry / "device"
        try:
            vendor_id = (device_path / "vendor").read_text(encoding="ascii").strip().lower()
        except (OSError, UnicodeError):
            read_failures = True
            continue
        manufacturer = _PCI_VENDOR_NAMES.get(vendor_id, "Unknown")
        if manufacturer == "Unknown":
            try:
                device_class = (
                    device_path / "class"
                ).read_text(encoding="ascii").strip().lower()
            except (OSError, UnicodeError):
                read_failures = True
                continue
            if not device_class.startswith("0x03"):
                continue
        if not vendor_id:
            continue
        try:
            pci_address = device_path.resolve().name.lower()
        except OSError:
            pci_address = ""
        model = pci_names.get(pci_address)
        devices.append(
            GpuDeviceInfoResponse(
                device_index=len(devices),
                manufacturer=manufacturer,
                model=model,
                vendor=manufacturer,
                gpu_type=_gpu_type(manufacturer, model),
            )
        )
    return devices, not read_failures


def _detect_system_gpus() -> tuple[list[GpuDeviceInfoResponse], bool]:
    """Return detected OS-level adapters and whether enumeration succeeded."""
    if sys.platform == "win32":
        cim_devices, cim_ok = _windows_gpu_devices()
        registry_devices = _windows_registry_gpu_devices()
        dxgi_luids = _get_dxgi_luids()
        merged = _merge_windows_devices(cim_devices, registry_devices, dxgi_luids)
        return merged, (cim_ok or bool(registry_devices))
    if sys.platform.startswith("linux"):
        return _linux_gpu_devices()
    logger.info("GPU adapter enumeration is unsupported on platform %s", sys.platform)
    return [], False


def _detected_gpus() -> tuple[list[GpuDeviceInfoResponse], bool]:
    """Cache OS hardware enumeration separately from the faster metrics cache."""
    global _gpu_detection_cache
    now = time.monotonic()
    if (
        _gpu_detection_cache is not None
        and now - _gpu_detection_cache[0] < _GPU_DETECTION_CACHE_SECONDS
    ):
        cached_devices = [
            item.model_copy(deep=True) for item in _gpu_detection_cache[1]
        ]
        return cached_devices, _gpu_detection_cache[2]
    try:
        devices, detection_available = _detect_system_gpus()
    except Exception:
        logger.exception("Unexpected OS GPU enumeration failure")
        devices, detection_available = [], False
    _gpu_detection_cache = (
        time.monotonic(),
        [item.model_copy(deep=True) for item in devices],
        detection_available,
    )
    return devices, detection_available


def _decode(value: bytes | str | None) -> str | None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return None


def _unavailable(status: str, message: str) -> GpuInfoResponse:
    return GpuInfoResponse(
        supported_gpu_detected=False,
        devices=[],
        monitoring_available=False,
        status=status,
        message=message,
        gpus=[],
    )


def _build_gpu_summary_from_info(
    devices: list[GpuDeviceInfoResponse],
) -> list[GpuSummaryItem]:
    items: list[GpuSummaryItem] = []
    for device in devices:
        vendor = device.vendor or device.manufacturer or "Unknown"
        name = device.model or f"{vendor} GPU"
        total_mb = (
            round(device.total_memory_bytes / (1024**2), 1)
            if isinstance(device.total_memory_bytes, int) and device.total_memory_bytes > 0
            else None
        )
        shared_mb = (
            round(device.shared_memory_bytes / (1024**2), 1)
            if isinstance(device.shared_memory_bytes, int) and device.shared_memory_bytes > 0
            else None
        )
        items.append(
            GpuSummaryItem(
                id=device.device_index,
                name=name,
                vendor=vendor,
                type=device.gpu_type or _gpu_type(vendor, name),
                activity_status="Idle" if device.monitoring_supported else "Unavailable",
                memory_total_mb=total_mb,
                shared_memory_total_mb=shared_mb,
                driver_version=device.driver_version,
                available=device.monitoring_supported,
                status="available" if device.monitoring_supported else "unsupported",
            )
        )
    return items


def _build_gpu_summary_from_usage(
    devices: list[GpuUsageDeviceResponse],
) -> list[GpuSummaryItem]:
    items: list[GpuSummaryItem] = []
    for device in devices:
        vendor = device.vendor or device.manufacturer or "Unknown"
        name = device.name or f"{vendor} GPU"
        activity = device.activity_status or _activity_status(
            device.gpu_utilization_percent, device.available
        )
        items.append(
            GpuSummaryItem(
                id=device.device_index,
                name=name,
                vendor=vendor,
                type=device.gpu_type or _gpu_type(vendor, name),
                activity_status=activity,
                utilization_percent=device.gpu_utilization_percent,
                memory_used_mb=device.memory_used_mb,
                memory_total_mb=device.memory_total_mb,
                shared_memory_used_mb=device.shared_memory_used_mb,
                shared_memory_total_mb=device.shared_memory_total_mb,
                temperature_c=device.temperature_celsius,
                clock_speed_mhz=device.clock_speed_mhz,
                power_usage_w=device.power_usage_watts,
                driver_version=device.driver_version,
                monitoring_method=device.monitoring_method,
                status=device.status,
                available=device.available,
            )
        )
    return items


def _get_gpu_info() -> GpuInfoResponse:
    """Detect NVIDIA GPUs when NVML and a working driver are available."""
    try:
        nvml = importlib.import_module("pynvml")
    except (ImportError, OSError):
        return _unavailable(
            "library_unavailable",
            "NVIDIA Management Library bindings are not installed.",
        )

    try:
        nvml.nvmlInit()
    except Exception as exc:
        logger.info("NVML initialization unavailable: %s", type(exc).__name__)
        return _unavailable(
            "initialization_error",
            "NVML could not initialize. Check NVIDIA driver installation and access.",
        )

    devices: list[GpuDeviceInfoResponse] = []
    device_failures = 0
    try:
        try:
            device_count = nvml.nvmlDeviceGetCount()
        except Exception as exc:
            logger.info("NVML device enumeration failed: %s", type(exc).__name__)
            return _unavailable(
                "device_info_unavailable",
                "NVML initialized, but GPU devices could not be enumerated.",
            )
        if (
            isinstance(device_count, bool)
            or not isinstance(device_count, int)
            or device_count < 0
        ):
            return _unavailable(
                "device_info_unavailable",
                "NVML returned an invalid GPU device count.",
            )

        try:
            driver_version = _decode(nvml.nvmlSystemGetDriverVersion())
        except Exception as exc:
            logger.info("NVML driver version unavailable: %s", type(exc).__name__)
            driver_version = None

        for index in range(device_count):
            try:
                handle = nvml.nvmlDeviceGetHandleByIndex(index)
                name = _decode(nvml.nvmlDeviceGetName(handle))
                if name is None:
                    device_failures += 1
                    continue
                try:
                    memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                    total_memory = memory.total
                    if (
                        isinstance(total_memory, bool)
                        or not isinstance(total_memory, int)
                        or total_memory <= 0
                    ):
                        total_memory = None
                except Exception as exc:
                    logger.info(
                        "NVML memory information unavailable for device %s: %s",
                        index,
                        type(exc).__name__,
                    )
                    total_memory = None
                devices.append(
                    GpuDeviceInfoResponse(
                        device_index=index,
                        manufacturer="NVIDIA",
                        model=name,
                        total_memory_bytes=total_memory,
                        driver_version=driver_version,
                        monitoring_supported=True,
                    )
                )
            except Exception as exc:
                device_failures += 1
                logger.info(
                    "NVML information unavailable for device %s: %s",
                    index,
                    type(exc).__name__,
                )
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception as exc:
            logger.debug("NVML shutdown did not complete cleanly: %s", type(exc).__name__)

    if devices:
        if device_failures:
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=devices,
                monitoring_available=True,
                status="device_info_unavailable",
                message="Some NVIDIA device information could not be retrieved.",
                gpus=_build_gpu_summary_from_info(devices),
            )
        return GpuInfoResponse(
            supported_gpu_detected=True,
            devices=devices,
            monitoring_available=True,
            status="available",
            message=None,
            gpus=_build_gpu_summary_from_info(devices),
        )

    if device_count == 0:
        return _unavailable(
            "unsupported",
            "No supported NVIDIA GPU was detected. Other GPU vendors are not queried.",
        )
    return _unavailable(
        "device_info_unavailable",
        "NVIDIA hardware was enumerated, but its device information is unavailable.",
    )


def get_gpu_info() -> GpuInfoResponse:
    """Combine OS multi-GPU adapter detection with NVML and OS monitoring providers."""
    with _NVML_LOCK:
        detected, detection_available = _detected_gpus()

        # Respect explicit non-NVIDIA adapters with monitoring_supported=False (e.g. unit tests)
        if (
            detected
            and not any(device.manufacturer == "NVIDIA" for device in detected)
            and not any(device.monitoring_supported for device in detected)
        ):
            devices_copy = [
                device.model_copy(
                    update={
                        "monitoring_supported": False,
                        "vendor": device.vendor or device.manufacturer,
                        "gpu_type": device.gpu_type
                        or _gpu_type(device.manufacturer, device.model),
                    },
                    deep=True,
                )
                for device in detected
            ]
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=devices_copy,
                monitoring_available=False,
                status="monitoring_unsupported",
                message="GPU Monitoring Not Supported",
                gpus=_build_gpu_summary_from_info(devices_copy),
            )

        has_nvidia_or_empty = not detected or any(
            device.manufacturer == "NVIDIA" for device in detected
        )
        nvml_result = _get_gpu_info() if has_nvidia_or_empty else _unavailable("unsupported", "")
        nvidia_nvml_devices = [
            device
            for device in nvml_result.devices
            if device.manufacturer == "NVIDIA"
        ]

        if nvidia_nvml_devices:
            for device in nvidia_nvml_devices:
                device.monitoring_supported = True
            other_devices = [
                device
                for device in detected
                if device.manufacturer != "NVIDIA"
            ]
            next_index = len(nvidia_nvml_devices)
            for offset, device in enumerate(other_devices):
                device.device_index = next_index + offset
                device.vendor = device.vendor or device.manufacturer
                device.gpu_type = device.gpu_type or _gpu_type(
                    device.manufacturer, device.model
                )
            devices = nvidia_nvml_devices + other_devices
            has_unsupported_devices = any(
                not item.monitoring_supported for item in other_devices
            )
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=devices,
                monitoring_available=True,
                status=(
                    "device_info_unavailable"
                    if nvml_result.status == "device_info_unavailable"
                    else "partial" if has_unsupported_devices else "available"
                ),
                message=(
                    nvml_result.message
                    if nvml_result.status == "device_info_unavailable"
                    else "GPU Monitoring Not Supported for some detected adapters."
                    if has_unsupported_devices
                    else None
                ),
                gpus=_build_gpu_summary_from_info(devices),
            )

        # If OS detected GPUs (e.g. dual-GPU Intel + NVIDIA where NVML is restricted by permissions)
        if detected:
            os_supported = any(device.monitoring_supported for device in detected)
            if os_supported:
                devices_copy = [
                    device.model_copy(
                        update={
                            "vendor": device.vendor or device.manufacturer,
                            "gpu_type": device.gpu_type
                            or _gpu_type(device.manufacturer, device.model),
                        },
                        deep=True,
                    )
                    for device in detected
                ]
                return GpuInfoResponse(
                    supported_gpu_detected=True,
                    devices=devices_copy,
                    monitoring_available=True,
                    status="available",
                    message=None,
                    gpus=_build_gpu_summary_from_info(devices_copy),
                )
            devices_copy = [
                device.model_copy(
                    update={
                        "monitoring_supported": False,
                        "vendor": device.vendor or device.manufacturer,
                        "gpu_type": device.gpu_type
                        or _gpu_type(device.manufacturer, device.model),
                    },
                    deep=True,
                )
                for device in detected
            ]
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=devices_copy,
                monitoring_available=False,
                status="monitoring_unsupported",
                message="GPU Monitoring Not Supported",
                gpus=_build_gpu_summary_from_info(devices_copy),
            )

        if detection_available:
            if nvml_result.status in {
                "library_unavailable",
                "initialization_error",
                "device_info_unavailable",
            }:
                return nvml_result
            return GpuInfoResponse(
                supported_gpu_detected=False,
                devices=[],
                monitoring_available=False,
                status="no_gpu",
                message="GPU Not Available",
                gpus=[],
            )
        return GpuInfoResponse(
            supported_gpu_detected=False,
            devices=[],
            monitoring_available=False,
            status="detection_error",
            message="GPU Data Unavailable",
            gpus=[],
        )


def _valid_percent(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
    ):
        return None
    return float(value)


def _valid_bytes(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        return None
    return value


def _valid_power_watts(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None
    return float(value) / 1000


def _read_gpu_usage() -> GpuUsageResponse:
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        nvml = importlib.import_module("pynvml")
    except (ImportError, OSError):
        return GpuUsageResponse(
            timestamp=timestamp,
            monitoring_available=False,
            status="library_unavailable",
            devices=[],
            message="NVIDIA Management Library bindings are not available.",
            gpus=[],
        )

    try:
        nvml.nvmlInit()
    except Exception as exc:
        logger.info("NVML initialization unavailable for usage sampling: %s", type(exc).__name__)
        return GpuUsageResponse(
            timestamp=timestamp,
            monitoring_available=False,
            status="initialization_error",
            devices=[],
            message="NVML could not initialize. Check NVIDIA driver installation and access.",
            gpus=[],
        )

    devices: list[GpuUsageDeviceResponse] = []
    driver_version: str | None = None
    try:
        try:
            device_count = nvml.nvmlDeviceGetCount()
        except Exception as exc:
            logger.info("NVML device enumeration failed for usage sampling: %s", type(exc).__name__)
            return GpuUsageResponse(
                timestamp=timestamp,
                monitoring_available=False,
                status="device_error",
                devices=[],
                message="NVML initialized, but GPU devices could not be enumerated.",
                gpus=[],
            )
        if (
            isinstance(device_count, bool)
            or not isinstance(device_count, int)
            or device_count < 0
        ):
            return GpuUsageResponse(
                timestamp=timestamp,
                monitoring_available=False,
                status="device_error",
                devices=[],
                message="NVML returned an invalid GPU device count.",
                gpus=[],
            )
        if device_count == 0:
            return GpuUsageResponse(
                timestamp=timestamp,
                monitoring_available=False,
                status="unsupported",
                devices=[],
                message="No supported NVIDIA GPU was detected.",
                gpus=[],
            )

        try:
            driver_version = _decode(nvml.nvmlSystemGetDriverVersion())
        except Exception:
            driver_version = None

        for index in range(device_count):
            name: str | None = None
            gpu_percent: float | None = None
            temperature: float | None = None
            clock_speed_mhz: float | None = None
            power_usage: float | None = None
            power_limit: float | None = None
            memory_used_mb: float | None = None
            memory_free_mb: float | None = None
            memory_total_mb: float | None = None
            memory_percent: float | None = None
            try:
                handle = nvml.nvmlDeviceGetHandleByIndex(index)
            except Exception as exc:
                logger.info("NVML handle unavailable for GPU %s: %s", index, type(exc).__name__)
                devices.append(
                    GpuUsageDeviceResponse(
                        device_index=index,
                        name=None,
                        manufacturer="NVIDIA",
                        vendor="NVIDIA",
                        gpu_type="Dedicated",
                        available=False,
                        status="device_error",
                        activity_status="Unavailable",
                        monitoring_supported=True,
                        gpu_utilization_percent=None,
                        temperature_celsius=None,
                        memory_used_mb=None,
                        memory_free_mb=None,
                        memory_total_mb=None,
                        memory_utilization_percent=None,
                        monitoring_method="NVIDIA NVML",
                        driver_version=driver_version,
                    )
                )
                continue

            try:
                name = _decode(nvml.nvmlDeviceGetName(handle))
            except Exception as exc:
                logger.info("NVML name unavailable for GPU %s: %s", index, type(exc).__name__)

            try:
                utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_percent = _valid_percent(utilization.gpu)
            except Exception as exc:
                logger.info("NVML utilization unavailable for GPU %s: %s", index, type(exc).__name__)

            try:
                temperature_reader = getattr(nvml, "nvmlDeviceGetTemperature")
                temperature = temperature_reader(
                    handle,
                    getattr(nvml, "NVML_TEMPERATURE_GPU", 0),
                )
                if (
                    isinstance(temperature, bool)
                    or not isinstance(temperature, (int, float))
                    or not math.isfinite(temperature)
                    or temperature < 0
                    or temperature > 200
                ):
                    temperature = None
                else:
                    temperature = float(temperature)
            except Exception as exc:
                logger.debug(
                    "NVML temperature unavailable for GPU %s: %s",
                    index,
                    type(exc).__name__,
                )

            try:
                clock_reader = getattr(nvml, "nvmlDeviceGetClockInfo")
                clock_val = clock_reader(
                    handle,
                    getattr(nvml, "NVML_CLOCK_GRAPHICS", 0),
                )
                if (
                    not isinstance(clock_val, bool)
                    and isinstance(clock_val, (int, float))
                    and math.isfinite(clock_val)
                    and clock_val >= 0
                ):
                    clock_speed_mhz = float(clock_val)
            except Exception as exc:
                logger.debug(
                    "NVML clock speed unavailable for GPU %s: %s",
                    index,
                    type(exc).__name__,
                )

            try:
                power_reader = getattr(nvml, "nvmlDeviceGetPowerUsage")
                power_usage = _valid_power_watts(power_reader(handle))
            except Exception as exc:
                logger.debug(
                    "NVML power usage unavailable for GPU %s: %s",
                    index,
                    type(exc).__name__,
                )

            try:
                power_limit_reader = getattr(
                    nvml,
                    "nvmlDeviceGetPowerManagementLimit",
                )
                power_limit = _valid_power_watts(power_limit_reader(handle))
            except Exception as exc:
                logger.debug(
                    "NVML power limit unavailable for GPU %s: %s",
                    index,
                    type(exc).__name__,
                )

            try:
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                used = _valid_bytes(memory.used)
                free = _valid_bytes(memory.free)
                total = _valid_bytes(memory.total)
                if total is not None and total > 0:
                    memory_total_mb = total / 1024**2
                    if free is not None and free <= total:
                        memory_free_mb = free / 1024**2
                    if used is not None and used <= total:
                        memory_used_mb = used / 1024**2
                        memory_percent = _valid_percent(used / total * 100)
                else:
                    if used is not None:
                        memory_used_mb = used / 1024**2
                    if free is not None:
                        memory_free_mb = free / 1024**2
            except Exception as exc:
                logger.info("NVML memory unavailable for GPU %s: %s", index, type(exc).__name__)

            available = any(
                value is not None
                for value in (
                    gpu_percent,
                    temperature,
                    power_usage,
                    power_limit,
                    memory_used_mb,
                    memory_free_mb,
                    memory_total_mb,
                    memory_percent,
                )
            )
            complete = (
                gpu_percent is not None
                and memory_used_mb is not None
                and memory_free_mb is not None
                and memory_total_mb is not None
                and memory_percent is not None
                and power_usage is not None
                and power_limit is not None
            )
            devices.append(
                GpuUsageDeviceResponse(
                    device_index=index,
                    name=name,
                    manufacturer="NVIDIA",
                    vendor="NVIDIA",
                    gpu_type="Dedicated",
                    available=available,
                    status="available" if complete else "partial" if available else "device_error",
                    activity_status=_activity_status(gpu_percent, available),
                    monitoring_supported=True,
                    gpu_utilization_percent=gpu_percent,
                    temperature_celsius=temperature,
                    clock_speed_mhz=clock_speed_mhz,
                    power_usage_watts=power_usage,
                    power_limit_watts=power_limit,
                    memory_used_mb=memory_used_mb,
                    memory_free_mb=memory_free_mb,
                    memory_total_mb=memory_total_mb,
                    memory_utilization_percent=memory_percent,
                    monitoring_method="NVIDIA NVML",
                    driver_version=driver_version,
                )
            )
    finally:
        try:
            nvml.nvmlShutdown()
        except Exception as exc:
            logger.debug("NVML shutdown did not complete cleanly: %s", type(exc).__name__)

    available_devices = [device for device in devices if device.available]
    if available_devices:
        status = (
            "available"
            if len(available_devices) == len(devices)
            and all(device.status == "available" for device in devices)
            else "partial"
        )
        message = None if status == "available" else "Some GPU measurements are unavailable."
        return GpuUsageResponse(
            timestamp=timestamp,
            monitoring_available=True,
            status=status,
            devices=devices,
            message=message,
            gpus=_build_gpu_summary_from_usage(devices),
        )
    return GpuUsageResponse(
        timestamp=timestamp,
        monitoring_available=False,
        status="device_error",
        devices=devices,
        message="No GPU measurements could be retrieved.",
        gpus=_build_gpu_summary_from_usage(devices),
    )


def _sample_os_device(
    device: GpuDeviceInfoResponse,
    device_index: int,
    dxgi_luids: dict[str, dict],
    perf_luids: dict[str, dict],
    assigned_luids: set[str],
) -> GpuUsageDeviceResponse:
    """Sample one GPU independently via Windows Performance Counters / DXGI."""
    vendor = device.vendor or device.manufacturer or "Unknown"
    gpu_type = device.gpu_type or _gpu_type(vendor, device.model)
    luid_hex = _match_luid_for_device(device, dxgi_luids, perf_luids, assigned_luids)
    perf = perf_luids.get(luid_hex) if luid_hex else None
    dxgi = dxgi_luids.get(luid_hex) if luid_hex else None

    util_percent: float | None = None
    mem_used_mb: float | None = None
    mem_free_mb: float | None = None
    mem_total_mb: float | None = None
    mem_percent: float | None = None
    shared_used_mb: float | None = None
    shared_free_mb: float | None = None
    shared_total_mb: float | None = None

    if isinstance(device.total_memory_bytes, int) and device.total_memory_bytes > 0:
        mem_total_mb = round(device.total_memory_bytes / (1024**2), 1)
    elif dxgi and dxgi.get("dedicated_vram_bytes", 0) > 0 and gpu_type == "Dedicated":
        mem_total_mb = round(dxgi["dedicated_vram_bytes"] / (1024**2), 1)

    if isinstance(device.shared_memory_bytes, int) and device.shared_memory_bytes > 0:
        shared_total_mb = round(device.shared_memory_bytes / (1024**2), 1)
    elif dxgi and dxgi.get("shared_ram_bytes", 0) > 0:
        shared_total_mb = round(dxgi["shared_ram_bytes"] / (1024**2), 1)

    if perf is not None:
        util_percent = _valid_percent(perf.get("util_percent"))
        dedicated_bytes = perf.get("dedicated_bytes")
        shared_bytes = perf.get("shared_bytes")

        if isinstance(shared_bytes, int) and shared_bytes >= 0:
            shared_used_mb = round(shared_bytes / (1024**2), 1)
            if shared_total_mb is not None and shared_total_mb >= shared_used_mb:
                shared_free_mb = round(shared_total_mb - shared_used_mb, 1)

        if gpu_type == "Dedicated" and mem_total_mb is not None:
            if isinstance(dedicated_bytes, int) and dedicated_bytes >= 0:
                mem_used_mb = round(dedicated_bytes / (1024**2), 1)
                if mem_total_mb >= mem_used_mb:
                    mem_free_mb = round(mem_total_mb - mem_used_mb, 1)
                    mem_percent = _valid_percent((mem_used_mb / mem_total_mb) * 100.0)
        elif gpu_type == "Integrated":
            # For integrated GPUs, expose shared system RAM as active memory pool
            if shared_used_mb is not None:
                mem_used_mb = shared_used_mb
            if shared_total_mb is not None:
                mem_total_mb = shared_total_mb
            if shared_free_mb is not None:
                mem_free_mb = shared_free_mb
            if (
                shared_used_mb is not None
                and shared_total_mb is not None
                and shared_total_mb > 0
            ):
                mem_percent = _valid_percent((shared_used_mb / shared_total_mb) * 100.0)

    has_live_telemetry = util_percent is not None or (
        perf is not None and (mem_used_mb is not None or shared_used_mb is not None)
    )
    has_any_info = has_live_telemetry or mem_total_mb is not None or shared_total_mb is not None

    method = (
        "Windows Performance Counters"
        if perf is not None
        else "Windows Display Adapter Registry"
        if has_any_info
        else None
    )

    return GpuUsageDeviceResponse(
        device_index=device_index,
        name=device.model,
        manufacturer=device.manufacturer,
        vendor=vendor,
        gpu_type=gpu_type,
        available=has_any_info,
        status="partial" if has_any_info else "unsupported",
        activity_status=_activity_status(util_percent, has_live_telemetry),
        monitoring_supported=device.monitoring_supported,
        gpu_utilization_percent=util_percent,
        temperature_celsius=None,
        clock_speed_mhz=None,
        power_usage_watts=None,
        power_limit_watts=None,
        memory_used_mb=mem_used_mb,
        memory_free_mb=mem_free_mb,
        memory_total_mb=mem_total_mb,
        memory_utilization_percent=mem_percent,
        shared_memory_used_mb=shared_used_mb,
        shared_memory_free_mb=shared_free_mb,
        shared_memory_total_mb=shared_total_mb,
        monitoring_method=method,
        driver_version=device.driver_version,
    )


def get_gpu_usage() -> GpuUsageResponse:
    """Independently monitor all detected GPUs simultaneously without hiding idle adapters."""
    global _gpu_usage_cache
    with _NVML_LOCK:
        now = time.monotonic()
        if (
            _gpu_usage_cache is not None
            and now - _gpu_usage_cache[0] < _GPU_USAGE_CACHE_SECONDS
        ):
            return _gpu_usage_cache[1].model_copy(deep=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        detected, detection_available = _detected_gpus()

        if not detected and detection_available:
            result = GpuUsageResponse(
                timestamp=timestamp,
                monitoring_available=False,
                status="no_gpu",
                devices=[],
                message="GPU Not Available",
                gpus=[],
            )
        else:
            nvidia_detected = [
                device for device in detected if device.manufacturer == "NVIDIA"
            ]
            other_detected = [
                device for device in detected if device.manufacturer != "NVIDIA"
            ]
            os_monitoring_enabled = any(
                device.monitoring_supported for device in detected
            )

            # Purely non-NVIDIA with monitoring_supported=False (unit tests / unsupported Linux GPU)
            if not nvidia_detected and detected and not os_monitoring_enabled:
                result = _unsupported_usage(other_detected)
            else:
                # Query Windows performance counters once if OS monitoring is enabled on Windows
                perf_luids = (
                    _query_windows_perf_counters()
                    if sys.platform == "win32" and os_monitoring_enabled
                    else {}
                )
                dxgi_luids = (
                    _get_dxgi_luids()
                    if sys.platform == "win32" and os_monitoring_enabled
                    else {}
                )
                assigned_luids: set[str] = set()

                # Try NVML when NVIDIA is detected or when detected is empty (NVML-only tests)
                sampled = (
                    _read_gpu_usage()
                    if (nvidia_detected or not detected)
                    else GpuUsageResponse(
                        timestamp=timestamp,
                        monitoring_available=False,
                        status="unsupported",
                        devices=[],
                        message=None,
                        gpus=[],
                    )
                )

                nvml_succeeded = sampled.status in {"available", "partial"} and any(
                    d.manufacturer == "NVIDIA" for d in sampled.devices
                )

                if os_monitoring_enabled and detected:
                    # Simultaneous multi-GPU assembly preserving every detected adapter
                    all_samples: list[GpuUsageDeviceResponse] = []
                    nvml_by_index = {
                        sample.device_index: sample
                        for sample in sampled.devices
                        if sample.manufacturer == "NVIDIA"
                    }
                    nvml_cursor = 0
                    for idx, device in enumerate(detected):
                        if device.manufacturer == "NVIDIA" and nvml_succeeded:
                            nvml_sample = nvml_by_index.get(nvml_cursor)
                            nvml_cursor += 1
                            if nvml_sample is not None:
                                enriched = nvml_sample.model_copy(
                                    update={
                                        "device_index": idx,
                                        "name": nvml_sample.name or device.model,
                                        "vendor": "NVIDIA",
                                        "gpu_type": device.gpu_type or "Dedicated",
                                        "driver_version": (
                                            nvml_sample.driver_version
                                            or device.driver_version
                                        ),
                                    }
                                )
                                all_samples.append(enriched)
                                # Reserve its LUID if present so other GPUs don't claim it
                                _match_luid_for_device(
                                    device, dxgi_luids, perf_luids, assigned_luids
                                )
                                continue
                        # Monitor independently via Windows Performance Counters / Registry
                        all_samples.append(
                            _sample_os_device(
                                device,
                                idx,
                                dxgi_luids,
                                perf_luids,
                                assigned_luids,
                            )
                        )

                    any_available = any(item.available for item in all_samples)
                    all_complete = all(
                        item.status == "available" for item in all_samples
                    )
                    overall_status = (
                        "available"
                        if any_available and all_complete
                        else "partial"
                        if any_available
                        else "monitoring_unsupported"
                    )
                    result = GpuUsageResponse(
                        timestamp=timestamp,
                        monitoring_available=any_available,
                        status=overall_status,
                        devices=all_samples,
                        message=(
                            None
                            if overall_status == "available"
                            else "Monitoring all detected GPUs. Some hardware sensors (such as temperature or clock speed) require elevated NVML permissions or vendor support."
                            if any_available
                            else "GPU Monitoring Not Supported"
                        ),
                        gpus=_build_gpu_summary_from_usage(all_samples),
                    )
                elif sampled.status in {"library_unavailable", "initialization_error"}:
                    if nvidia_detected:
                        result = _unsupported_usage(nvidia_detected + other_detected)
                    else:
                        result = sampled.model_copy(
                            update={"message": "GPU Data Unavailable"}
                        )
                elif sampled.status == "unsupported" and nvidia_detected:
                    result = _unsupported_usage(nvidia_detected + other_detected)
                elif sampled.status == "device_error" and not sampled.devices:
                    if nvidia_detected:
                        result = _unavailable_metrics(nvidia_detected + other_detected)
                    else:
                        result = sampled.model_copy(
                            update={"message": "GPU Data Unavailable"}
                        )
                elif sampled.status == "device_error" and not any(
                    device.available for device in sampled.devices
                ):
                    result = _unavailable_metrics(
                        nvidia_detected + other_detected
                        or [
                            GpuDeviceInfoResponse(
                                device_index=device.device_index,
                                manufacturer=device.manufacturer or "NVIDIA",
                                model=device.name,
                            )
                            for device in sampled.devices
                        ]
                    )
                else:
                    nvidia_samples = [
                        sample
                        for sample in sampled.devices
                        if sample.manufacturer == "NVIDIA"
                    ]
                    nvidia_names = {
                        device.device_index: device.model
                        for device in nvidia_detected
                    }
                    for sample in nvidia_samples:
                        if not sample.name:
                            sample.name = nvidia_names.get(sample.device_index)
                    unsupported_samples = _unsupported_usage_devices(
                        other_detected,
                        start_index=(
                            max(
                                (item.device_index for item in nvidia_samples),
                                default=-1,
                            )
                            + 1
                        ),
                    )
                    all_samples = nvidia_samples + unsupported_samples
                    if sampled.status == "device_error" and not nvidia_samples:
                        result = _unavailable_metrics(detected)
                    elif unsupported_samples:
                        result = GpuUsageResponse(
                            timestamp=sampled.timestamp,
                            monitoring_available=bool(nvidia_samples),
                            status="partial",
                            devices=all_samples,
                            message="GPU Monitoring Not Supported for some detected adapters.",
                            gpus=_build_gpu_summary_from_usage(all_samples),
                        )
                    else:
                        result = sampled

        if not detection_available and not result.devices:
            result = result.model_copy(
                update={
                    "status": "device_error",
                    "message": "GPU Data Unavailable",
                }
            )
        if result.gpus is None:
            result = result.model_copy(
                update={"gpus": _build_gpu_summary_from_usage(result.devices)}
            )
        _gpu_usage_cache = (time.monotonic(), result)
        return result.model_copy(deep=True)


def get_gpu_list() -> GpuListResponse:
    """Return the normalized multi-GPU summary list for /api/gpu/list."""
    usage = get_gpu_usage()
    items = usage.gpus if usage.gpus is not None else _build_gpu_summary_from_usage(usage.devices)
    return GpuListResponse(gpus=items)


def _unsupported_usage_devices(
    devices: list[GpuDeviceInfoResponse],
    *,
    start_index: int = 0,
) -> list[GpuUsageDeviceResponse]:
    return [
        GpuUsageDeviceResponse(
            device_index=start_index + offset,
            name=device.model,
            manufacturer=device.manufacturer,
            vendor=device.vendor or device.manufacturer,
            gpu_type=device.gpu_type or _gpu_type(device.manufacturer, device.model),
            available=False,
            status="unsupported",
            activity_status="Unavailable",
            monitoring_supported=False,
            gpu_utilization_percent=None,
            temperature_celsius=None,
            memory_used_mb=None,
            memory_free_mb=None,
            memory_total_mb=None,
            memory_utilization_percent=None,
        )
        for offset, device in enumerate(devices)
    ]


def _unsupported_usage(
    devices: list[GpuDeviceInfoResponse],
) -> GpuUsageResponse:
    usage_devices = _unsupported_usage_devices(devices)
    return GpuUsageResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        monitoring_available=False,
        status="monitoring_unsupported",
        devices=usage_devices,
        message="GPU Monitoring Not Supported",
        gpus=_build_gpu_summary_from_usage(usage_devices),
    )


def _unavailable_metrics(
    devices: list[GpuDeviceInfoResponse],
) -> GpuUsageResponse:
    usage_devices = [
        GpuUsageDeviceResponse(
            device_index=device.device_index,
            name=device.model,
            manufacturer=device.manufacturer,
            vendor=device.vendor or device.manufacturer,
            gpu_type=device.gpu_type or _gpu_type(device.manufacturer, device.model),
            available=False,
            status="device_error",
            activity_status="Unavailable",
            monitoring_supported=device.manufacturer == "NVIDIA",
            gpu_utilization_percent=None,
            temperature_celsius=None,
            memory_used_mb=None,
            memory_free_mb=None,
            memory_total_mb=None,
            memory_utilization_percent=None,
        )
        for device in devices
    ]
    return GpuUsageResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        monitoring_available=False,
        status="device_error",
        devices=usage_devices,
        message="GPU Data Unavailable",
        gpus=_build_gpu_summary_from_usage(usage_devices),
    )


def reset_gpu_usage_cache() -> None:
    """Clear the sample cache for deterministic tests."""
    global _gpu_usage_cache, _gpu_detection_cache
    with _NVML_LOCK:
        _gpu_usage_cache = None
        _gpu_detection_cache = None
