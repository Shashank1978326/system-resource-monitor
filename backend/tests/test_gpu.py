"""GPU detection and monitoring tests do not depend on host GPU hardware."""

from types import SimpleNamespace
import json

import pytest
from fastapi.testclient import TestClient

from app.api.routes import gpu as gpu_route
from app.main import app
from app.schemas.monitoring import (
    GpuDeviceInfoResponse,
    GpuInfoResponse,
    GpuUsageResponse,
)
from app.services import gpu_service


class FakeNvml:
    def __init__(self, names=(), memory=None, driver=b"555.42"):
        self.names = names
        self.memory = memory or [8 * 1024**3] * len(names)
        self.driver = driver
        self.initialized = False
        self.shutdown = False

    def nvmlInit(self):
        self.initialized = True

    def nvmlShutdown(self):
        self.shutdown = True

    def nvmlDeviceGetCount(self):
        return len(self.names)

    def nvmlSystemGetDriverVersion(self):
        return self.driver

    def nvmlDeviceGetHandleByIndex(self, index):
        return index

    def nvmlDeviceGetName(self, handle):
        return self.names[handle]

    def nvmlDeviceGetMemoryInfo(self, handle):
        return SimpleNamespace(total=self.memory[handle])


def use_nvml(monkeypatch, nvml):
    monkeypatch.setattr(gpu_service.importlib, "import_module", lambda _: nvml)


class FakeUsageNvml:
    def __init__(
        self,
        names,
        utilizations,
        memories,
        failed_handles=(),
        failed_utilization=(),
        failed_memory=(),
        temperatures=None,
        failed_temperature=(),
        power_usages=None,
        power_limits=None,
        failed_power_usage=(),
        failed_power_limit=(),
    ):
        self.names = names
        self.utilizations = utilizations
        self.memories = memories
        self.failed_handles = set(failed_handles)
        self.failed_utilization = set(failed_utilization)
        self.failed_memory = set(failed_memory)
        self.temperatures = temperatures or [51] * len(names)
        self.failed_temperature = set(failed_temperature)
        self.power_usages = power_usages or [125_000] * len(names)
        self.power_limits = power_limits or [250_000] * len(names)
        self.failed_power_usage = set(failed_power_usage)
        self.failed_power_limit = set(failed_power_limit)
        self.shutdown = False
        self.NVML_TEMPERATURE_GPU = 0

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        self.shutdown = True

    def nvmlDeviceGetCount(self):
        return len(self.names)

    def nvmlDeviceGetHandleByIndex(self, index):
        if index in self.failed_handles:
            raise RuntimeError("device disappeared")
        return index

    def nvmlDeviceGetName(self, handle):
        return self.names[handle]

    def nvmlDeviceGetUtilizationRates(self, handle):
        if handle in self.failed_utilization:
            raise RuntimeError("utilization unavailable")
        return SimpleNamespace(gpu=self.utilizations[handle])

    def nvmlDeviceGetMemoryInfo(self, handle):
        if handle in self.failed_memory:
            raise RuntimeError("memory unavailable")
        return self.memories[handle]

    def nvmlDeviceGetTemperature(self, handle, _sensor):
        if handle in self.failed_temperature:
            raise RuntimeError("temperature unavailable")
        return self.temperatures[handle]

    def nvmlDeviceGetPowerUsage(self, handle):
        if handle in self.failed_power_usage:
            raise RuntimeError("power usage unavailable")
        return self.power_usages[handle]

    def nvmlDeviceGetPowerManagementLimit(self, handle):
        if handle in self.failed_power_limit:
            raise RuntimeError("power limit unavailable")
        return self.power_limits[handle]


@pytest.fixture(autouse=True)
def clear_gpu_sample_cache(monkeypatch):
    gpu_service.reset_gpu_usage_cache()
    monkeypatch.setattr(gpu_service, "_detect_system_gpus", lambda: ([], True))
    yield
    gpu_service.reset_gpu_usage_cache()


def use_detected_gpus(monkeypatch, *devices):
    detected = [
        GpuDeviceInfoResponse(
            device_index=index,
            manufacturer=manufacturer,
            model=model,
        )
        for index, (manufacturer, model) in enumerate(devices)
    ]
    monkeypatch.setattr(
        gpu_service,
        "_detect_system_gpus",
        lambda: (detected, True),
    )
    gpu_service.reset_gpu_usage_cache()


def test_detects_nvidia_gpu_and_reports_capacity(monkeypatch):
    nvml = FakeNvml(names=[b"NVIDIA Test GPU"])
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_info()

    assert result.supported_gpu_detected is True
    assert result.monitoring_available is True
    assert result.status == "available"
    assert result.devices == [
        GpuDeviceInfoResponse(
            device_index=0,
            manufacturer="NVIDIA",
            model="NVIDIA Test GPU",
            total_memory_bytes=8 * 1024**3,
            driver_version="555.42",
            monitoring_supported=True,
        )
    ]
    assert nvml.initialized is True
    assert nvml.shutdown is True


def test_detects_multiple_gpus(monkeypatch):
    nvml = FakeNvml(names=[b"GPU one", b"GPU two"], memory=[100, 200])
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_info()

    assert [device.device_index for device in result.devices] == [0, 1]
    assert [device.model for device in result.devices] == ["GPU one", "GPU two"]


def test_no_gpu_returns_structured_unavailable_result(monkeypatch):
    use_nvml(monkeypatch, FakeNvml())

    result = gpu_service.get_gpu_info()

    assert result.supported_gpu_detected is False
    assert result.monitoring_available is False
    assert result.status == "no_gpu"
    assert result.message == "GPU Not Available"
    assert result.devices == []


def test_windows_detection_identifies_nvidia_amd_and_integrated_intel(monkeypatch):
    adapters = [
        {
            "Name": "NVIDIA GeForce",
            "AdapterCompatibility": "NVIDIA",
            "PNPDeviceID": "PCI\\VEN_10DE&DEV_1234",
        },
        {
            "Name": "AMD Radeon",
            "AdapterCompatibility": "Advanced Micro Devices, Inc.",
            "PNPDeviceID": "PCI\\VEN_1002&DEV_1234",
        },
        {
            "Name": "Intel UHD Graphics",
            "AdapterCompatibility": "Intel Corporation",
            "PNPDeviceID": "PCI\\VEN_8086&DEV_1234",
        },
    ]
    monkeypatch.setattr(gpu_service.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(
        gpu_service.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(adapters),
        ),
    )

    detected, detection_available = gpu_service._windows_gpu_devices()

    assert detection_available is True
    assert [device.manufacturer for device in detected] == [
        "NVIDIA",
        "AMD",
        "Intel",
    ]
    assert detected[2].model == "Intel UHD Graphics"
    assert all(device.monitoring_supported is False for device in detected)


def test_windows_gpu_detection_reports_missing_enumeration_tool(monkeypatch):
    monkeypatch.setattr(gpu_service.shutil, "which", lambda _: None)

    detected, detection_available = gpu_service._windows_gpu_devices()

    assert detected == []
    assert detection_available is False


def test_linux_drm_detection_identifies_integrated_and_discrete_vendors(
    tmp_path,
    monkeypatch,
):
    drm_path = tmp_path / "drm"
    drm_path.mkdir()
    for index, vendor_id in enumerate(("0x8086", "0x1002", "0x10de")):
        device_path = drm_path / f"card{index}" / "device"
        device_path.mkdir(parents=True)
        (device_path / "vendor").write_text(vendor_id, encoding="ascii")
    monkeypatch.setattr(gpu_service.shutil, "which", lambda _: None)

    detected, detection_available = gpu_service._linux_gpu_devices(drm_path)

    assert detection_available is True
    assert [device.manufacturer for device in detected] == [
        "Intel",
        "AMD",
        "NVIDIA",
    ]
    assert all(device.model is None for device in detected)


def test_linux_drm_detection_preserves_unknown_display_adapter(tmp_path, monkeypatch):
    drm_path = tmp_path / "drm"
    device_path = drm_path / "card0" / "device"
    device_path.mkdir(parents=True)
    (device_path / "vendor").write_text("0x1234", encoding="ascii")
    (device_path / "class").write_text("0x030000", encoding="ascii")
    monkeypatch.setattr(gpu_service.shutil, "which", lambda _: None)

    detected, detection_available = gpu_service._linux_gpu_devices(drm_path)

    assert detection_available is True
    assert len(detected) == 1
    assert detected[0].manufacturer == "Unknown"
    assert detected[0].model is None


def test_detected_non_nvidia_gpu_is_reported_as_monitoring_unsupported(monkeypatch):
    use_detected_gpus(monkeypatch, ("Intel", "Intel UHD Graphics"))
    monkeypatch.setattr(
        gpu_service.importlib,
        "import_module",
        lambda _: pytest.fail("NVML should not be initialized for unsupported vendors"),
    )

    result = gpu_service.get_gpu_info()

    assert result.supported_gpu_detected is True
    assert result.monitoring_available is False
    assert result.status == "monitoring_unsupported"
    assert result.message == "GPU Monitoring Not Supported"
    assert result.devices[0].manufacturer == "Intel"


def test_intel_integrated_gpu_monitoring_is_unsupported_without_fake_metrics(
    monkeypatch,
):
    use_detected_gpus(monkeypatch, ("Intel", "Intel UHD Graphics"))
    monkeypatch.setattr(
        gpu_service.importlib,
        "import_module",
        lambda _: pytest.fail("No unsupported-provider NVML request expected"),
    )

    result = gpu_service.get_gpu_usage()

    assert result.status == "monitoring_unsupported"
    assert result.message == "GPU Monitoring Not Supported"
    assert result.devices[0].manufacturer == "Intel"
    assert result.devices[0].gpu_utilization_percent is None
    assert result.devices[0].temperature_celsius is None


def test_gpu_usage_reports_no_gpu_without_zero_metrics(monkeypatch):
    result = gpu_service.get_gpu_usage()

    assert result.status == "no_gpu"
    assert result.message == "GPU Not Available"
    assert result.devices == []


def test_missing_nvml_library_returns_structured_result(monkeypatch):
    use_detected_gpus(monkeypatch, ("NVIDIA", "Detected NVIDIA GPU"))
    def missing_module(_):
        raise ModuleNotFoundError("pynvml")

    monkeypatch.setattr(gpu_service.importlib, "import_module", missing_module)

    result = gpu_service.get_gpu_info()

    assert result.status == "monitoring_unsupported"
    assert result.devices[0].manufacturer == "NVIDIA"
    assert result.devices[0].monitoring_supported is False


def test_native_nvml_library_load_failure_returns_structured_result(monkeypatch):
    use_detected_gpus(monkeypatch, ("NVIDIA", "Detected NVIDIA GPU"))
    def missing_native_library(_):
        raise OSError("NVML shared library unavailable")

    monkeypatch.setattr(gpu_service.importlib, "import_module", missing_native_library)

    result = gpu_service.get_gpu_info()

    assert result.status == "monitoring_unsupported"
    assert result.devices[0].manufacturer == "NVIDIA"


def test_driver_initialization_failure_is_reported(monkeypatch):
    use_detected_gpus(monkeypatch, ("NVIDIA", "Detected NVIDIA GPU"))
    nvml = FakeNvml(names=[b"GPU"])

    def fail_initialization():
        raise RuntimeError("driver unavailable")

    nvml.nvmlInit = fail_initialization
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_info()

    assert result.status == "monitoring_unsupported"
    assert result.supported_gpu_detected is True
    assert nvml.shutdown is False


def test_invalid_or_unavailable_device_values_are_not_fabricated(monkeypatch):
    nvml = FakeNvml(names=[b"GPU one", None], memory=[0, 100])
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_info()

    assert result.supported_gpu_detected is True
    assert result.status == "device_info_unavailable"
    assert len(result.devices) == 1
    assert result.devices[0].total_memory_bytes is None


def test_invalid_device_count_returns_unavailable_result(monkeypatch):
    use_detected_gpus(monkeypatch, ("NVIDIA", "Detected NVIDIA GPU"))
    nvml = FakeNvml(names=[b"GPU"])
    nvml.nvmlDeviceGetCount = lambda: None
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_info()

    assert result.status == "monitoring_unsupported"
    assert result.devices[0].model == "Detected NVIDIA GPU"
    assert nvml.shutdown is True


def test_gpu_info_endpoint_uses_response_schema(monkeypatch):
    expected = GpuInfoResponse(
        supported_gpu_detected=False,
        devices=[],
        monitoring_available=False,
        status="no_gpu",
        message="GPU Not Available",
    )
    monkeypatch.setattr(gpu_route, "get_gpu_info", lambda: expected)

    response = TestClient(app).get("/api/gpu/info")

    assert response.status_code == 200
    assert response.json() == expected.model_dump()


def test_gpu_usage_reads_utilization_and_calculates_vram_percent(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[42],
        memories=[SimpleNamespace(used=4 * 1024**2, free=6 * 1024**2, total=10 * 1024**2)],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    result = gpu_service.get_gpu_usage()
    device = result.devices[0]

    assert result.status == "available"
    assert result.monitoring_available is True
    assert device.gpu_utilization_percent == 42
    assert device.memory_used_mb == 4
    assert device.memory_free_mb == 6
    assert device.memory_total_mb == 10
    assert device.memory_utilization_percent == 40
    assert device.temperature_celsius == 51
    assert device.power_usage_watts == 125
    assert device.power_limit_watts == 250
    assert device.name == "NVIDIA Test GPU"
    assert nvml.shutdown is True
    assert result.timestamp.endswith("+00:00")


def test_gpu_usage_reports_temperature_when_nvml_supports_it(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
        temperatures=[64],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.temperature_celsius == 64


def test_gpu_usage_temperature_is_null_when_nvml_cannot_read_it(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
        failed_temperature={0},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.temperature_celsius is None


def test_gpu_usage_supports_multiple_devices(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU one", b"GPU two"],
        utilizations=[12, 88],
        memories=[
            SimpleNamespace(used=1, free=3, total=4),
            SimpleNamespace(used=3, free=1, total=4),
        ],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(
        monkeypatch,
        ("NVIDIA", "GPU one"),
        ("NVIDIA", "GPU two"),
    )

    result = gpu_service.get_gpu_usage()

    assert [device.device_index for device in result.devices] == [0, 1]
    assert [device.gpu_utilization_percent for device in result.devices] == [12, 88]
    assert [device.memory_utilization_percent for device in result.devices] == [25, 75]
    assert [device.power_usage_watts for device in result.devices] == [125, 125]
    assert [device.power_limit_watts for device in result.devices] == [250, 250]


def test_gpu_usage_reads_power_and_power_limit_in_watts(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
        power_usages=[178_500],
        power_limits=[300_000],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.power_usage_watts == 178.5
    assert device.power_limit_watts == 300


def test_gpu_usage_keeps_missing_power_metrics_null(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
        failed_power_usage={0},
        failed_power_limit={0},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    result = gpu_service.get_gpu_usage()
    device = result.devices[0]

    assert result.status == "partial"
    assert device.available is True
    assert device.power_usage_watts is None
    assert device.power_limit_watts is None
    assert device.gpu_utilization_percent == 31


def test_gpu_usage_handles_unsupported_power_functions(monkeypatch):
    monkeypatch.delattr(FakeUsageNvml, "nvmlDeviceGetPowerUsage")
    monkeypatch.delattr(FakeUsageNvml, "nvmlDeviceGetPowerManagementLimit")
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.gpu_utilization_percent == 31
    assert device.memory_utilization_percent == 30
    assert device.power_usage_watts is None
    assert device.power_limit_watts is None


@pytest.mark.parametrize("invalid", [None, -1, float("nan"), float("inf"), True])
def test_gpu_usage_rejects_invalid_power_values(monkeypatch, invalid):
    nvml = FakeUsageNvml(
        names=[b"NVIDIA Test GPU"],
        utilizations=[31],
        memories=[SimpleNamespace(used=3, free=7, total=10)],
        power_usages=[invalid],
        power_limits=[invalid],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "NVIDIA Test GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.power_usage_watts is None
    assert device.power_limit_watts is None


def test_gpu_usage_keeps_missing_measurements_null(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU"],
        utilizations=[None],
        memories=[None],
        failed_utilization={0},
        failed_memory={0},
        failed_temperature={0},
        failed_power_usage={0},
        failed_power_limit={0},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    result = gpu_service.get_gpu_usage()
    device = result.devices[0]

    assert result.status == "device_error"
    assert device.available is False
    assert device.gpu_utilization_percent is None
    assert device.memory_used_mb is None
    assert device.memory_free_mb is None
    assert device.memory_total_mb is None
    assert device.memory_utilization_percent is None


def test_gpu_usage_preserves_available_metrics_when_vram_read_fails(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU"],
        utilizations=[38],
        memories=[None],
        failed_memory={0},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    result = gpu_service.get_gpu_usage()
    device = result.devices[0]

    assert result.status == "partial"
    assert device.available is True
    assert device.gpu_utilization_percent == 38
    assert device.memory_used_mb is None
    assert device.memory_utilization_percent is None


def test_gpu_usage_preserves_vram_when_utilization_read_fails(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU"],
        utilizations=[None],
        memories=[SimpleNamespace(used=2, free=8, total=10)],
        failed_utilization={0},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    result = gpu_service.get_gpu_usage()
    device = result.devices[0]

    assert result.status == "partial"
    assert result.monitoring_available is True
    assert device.available is True
    assert device.gpu_utilization_percent is None
    assert device.memory_utilization_percent == 20


def test_gpu_usage_handles_individual_device_failure(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU one", b"GPU two"],
        utilizations=[50, 0],
        memories=[
            SimpleNamespace(used=5, free=5, total=10),
            SimpleNamespace(used=0, free=0, total=0),
        ],
        failed_handles={1},
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    result = gpu_service.get_gpu_usage()

    assert result.status == "partial"
    assert result.devices[0].available is True
    assert result.devices[1].status == "device_error"
    assert result.devices[1].name is None
    assert result.devices[1].gpu_utilization_percent is None


def test_gpu_usage_handles_invalid_measurements_without_defaults(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU"],
        utilizations=[125],
        memories=[SimpleNamespace(used=11, free=1, total=10)],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    device = gpu_service.get_gpu_usage().devices[0]

    assert device.gpu_utilization_percent is None
    assert device.memory_used_mb is None
    assert device.memory_free_mb == pytest.approx(1 / 1024**2)
    assert device.memory_total_mb == pytest.approx(10 / 1024**2)
    assert device.memory_utilization_percent is None


def test_gpu_usage_nvml_initialization_failure_is_graceful(monkeypatch):
    use_detected_gpus(monkeypatch, ("NVIDIA", "Detected GPU"))
    nvml = FakeUsageNvml([], [], [])

    def fail_initialization():
        raise RuntimeError("driver unavailable")

    nvml.nvmlInit = fail_initialization
    use_nvml(monkeypatch, nvml)

    result = gpu_service.get_gpu_usage()

    assert result.status == "monitoring_unsupported"
    assert result.monitoring_available is False
    assert result.devices[0].name == "Detected GPU"


def test_gpu_usage_missing_nvml_returns_structured_response(monkeypatch):
    use_detected_gpus(monkeypatch, ("AMD", "Radeon iGPU"))
    def missing_module(_):
        raise ModuleNotFoundError("pynvml")

    monkeypatch.setattr(gpu_service.importlib, "import_module", missing_module)

    result = gpu_service.get_gpu_usage()

    assert result.status == "monitoring_unsupported"
    assert result.message == "GPU Monitoring Not Supported"
    assert result.devices[0].manufacturer == "AMD"
    assert result.devices[0].gpu_utilization_percent is None


def test_gpu_usage_cache_avoids_excessive_nvml_calls(monkeypatch):
    nvml = FakeUsageNvml(
        names=[b"GPU"],
        utilizations=[40],
        memories=[SimpleNamespace(used=4, free=6, total=10)],
    )
    use_nvml(monkeypatch, nvml)
    use_detected_gpus(monkeypatch, ("NVIDIA", "GPU"))

    first = gpu_service.get_gpu_usage()
    second = gpu_service.get_gpu_usage()

    assert first.timestamp == second.timestamp
    assert len(second.devices) == 1


def test_gpu_usage_endpoint_uses_response_schema(monkeypatch):
    expected = GpuUsageResponse(
        timestamp="2026-11-03T00:00:00+00:00",
        monitoring_available=False,
        status="no_gpu",
        devices=[],
        message="GPU Not Available",
    )
    monkeypatch.setattr(gpu_route, "get_gpu_usage", lambda: expected)

    response = TestClient(app).get("/api/gpu/usage")

    assert response.status_code == 200
    assert response.json() == expected.model_dump()
