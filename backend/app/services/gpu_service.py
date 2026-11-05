"""Cross-platform GPU detection with optional NVIDIA NVML measurements."""

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
        ("amd", "AMD"),
        ("advanced micro", "AMD"),
        ("intel", "Intel"),
    ):
        if token in name:
            return label
    if re.search(r"\bati\b", name):
        return "AMD"
    return "Unknown"


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
            )
        )
    return devices, not read_failures


def _detect_system_gpus() -> tuple[list[GpuDeviceInfoResponse], bool]:
    """Return detected OS-level adapters and whether enumeration succeeded."""
    if sys.platform == "win32":
        return _windows_gpu_devices()
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
    )


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
            )
        return GpuInfoResponse(
            supported_gpu_detected=True,
            devices=devices,
            monitoring_available=True,
            status="available",
            message=None,
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
    """Combine OS adapter detection with optional NVIDIA NVML capability."""
    with _NVML_LOCK:
        detected, detection_available = _detected_gpus()
        if detected and not any(
            device.manufacturer == "NVIDIA" for device in detected
        ):
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=[
                    device.model_copy(
                        update={"monitoring_supported": False},
                        deep=True,
                    )
                    for device in detected
                ],
                monitoring_available=False,
                status="monitoring_unsupported",
                message="GPU Monitoring Not Supported",
            )
        nvml_result = _get_gpu_info()
        nvidia_devices = [
            device
            for device in nvml_result.devices
            if device.manufacturer == "NVIDIA"
        ]
        if nvidia_devices:
            for device in nvidia_devices:
                device.monitoring_supported = True
            other_devices = [
                device
                for device in detected
                if device.manufacturer != "NVIDIA"
            ]
            next_index = len(nvidia_devices)
            for offset, device in enumerate(other_devices):
                device.device_index = next_index + offset
                device.monitoring_supported = False
            devices = nvidia_devices + other_devices
            has_unsupported_devices = bool(other_devices)
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
            )

        if detected:
            return GpuInfoResponse(
                supported_gpu_detected=True,
                devices=[
                    device.model_copy(
                        update={"monitoring_supported": False},
                        deep=True,
                    )
                    for device in detected
                ],
                monitoring_available=False,
                status="monitoring_unsupported",
                message="GPU Monitoring Not Supported",
            )

        if detection_available:
            return GpuInfoResponse(
                supported_gpu_detected=False,
                devices=[],
                monitoring_available=False,
                status="no_gpu",
                message="GPU Not Available",
            )
        return GpuInfoResponse(
            supported_gpu_detected=False,
            devices=[],
            monitoring_available=False,
            status="detection_error",
            message="GPU Data Unavailable",
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
        )

    devices: list[GpuUsageDeviceResponse] = []
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
            )
        if device_count == 0:
            return GpuUsageResponse(
                timestamp=timestamp,
                monitoring_available=False,
                status="unsupported",
                devices=[],
                message="No supported NVIDIA GPU was detected.",
            )

        for index in range(device_count):
            name: str | None = None
            gpu_percent: float | None = None
            temperature: float | None = None
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
                        available=False,
                        status="device_error",
                        monitoring_supported=True,
                        gpu_utilization_percent=None,
                        temperature_celsius=None,
                        memory_used_mb=None,
                        memory_free_mb=None,
                        memory_total_mb=None,
                        memory_utilization_percent=None,
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
                    available=available,
                    status="available" if complete else "partial" if available else "device_error",
                    monitoring_supported=True,
                    gpu_utilization_percent=gpu_percent,
                    temperature_celsius=temperature,
                    power_usage_watts=power_usage,
                    power_limit_watts=power_limit,
                    memory_used_mb=memory_used_mb,
                    memory_free_mb=memory_free_mb,
                    memory_total_mb=memory_total_mb,
                    memory_utilization_percent=memory_percent,
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
        )
    return GpuUsageResponse(
        timestamp=timestamp,
        monitoring_available=False,
        status="device_error",
        devices=devices,
        message="No GPU measurements could be retrieved.",
    )


def get_gpu_usage() -> GpuUsageResponse:
    """Return measurements only for detected GPUs supported by an active provider."""
    global _gpu_usage_cache
    with _NVML_LOCK:
        now = time.monotonic()
        if (
            _gpu_usage_cache is not None
            and now - _gpu_usage_cache[0] < _GPU_USAGE_CACHE_SECONDS
        ):
            return _gpu_usage_cache[1].model_copy(deep=True)
        detected, detection_available = _detected_gpus()
        if not detected and detection_available:
            result = GpuUsageResponse(
                timestamp=datetime.now(timezone.utc).isoformat(),
                monitoring_available=False,
                status="no_gpu",
                devices=[],
                message="GPU Not Available",
            )
        else:
            nvidia_detected = [
                device for device in detected if device.manufacturer == "NVIDIA"
            ]
            other_detected = [
                device for device in detected if device.manufacturer != "NVIDIA"
            ]
            if not nvidia_detected and detected:
                result = _unsupported_usage(other_detected)
            else:
                sampled = _read_gpu_usage()
                if sampled.status in {"library_unavailable", "initialization_error"}:
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
        _gpu_usage_cache = (time.monotonic(), result)
        return result.model_copy(deep=True)


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
            available=False,
            status="unsupported",
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
    return GpuUsageResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        monitoring_available=False,
        status="monitoring_unsupported",
        devices=_unsupported_usage_devices(devices),
        message="GPU Monitoring Not Supported",
    )


def _unavailable_metrics(
    devices: list[GpuDeviceInfoResponse],
) -> GpuUsageResponse:
    return GpuUsageResponse(
        timestamp=datetime.now(timezone.utc).isoformat(),
        monitoring_available=False,
        status="device_error",
        devices=[
            GpuUsageDeviceResponse(
                device_index=device.device_index,
                name=device.model,
                manufacturer=device.manufacturer,
                available=False,
                status="device_error",
                monitoring_supported=device.manufacturer == "NVIDIA",
                gpu_utilization_percent=None,
                temperature_celsius=None,
                memory_used_mb=None,
                memory_free_mb=None,
                memory_total_mb=None,
                memory_utilization_percent=None,
            )
            for device in devices
        ],
        message="GPU Data Unavailable",
    )


def reset_gpu_usage_cache() -> None:
    """Clear the sample cache for deterministic tests."""
    global _gpu_usage_cache, _gpu_detection_cache
    with _NVML_LOCK:
        _gpu_usage_cache = None
        _gpu_detection_cache = None
