"""Tests for the basic application endpoints."""

import os
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.monitoring import SystemInfoResponse

client = TestClient(app)


def test_root_returns_api_message() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": app.title}


def test_health_returns_healthy_status() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_frontend_origin_is_allowed_for_api_requests() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_frontend_origin_can_use_alert_management_methods() -> None:
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        response = client.options(
            "/api/alerts/thresholds",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": method,
            },
        )
        assert response.status_code == 200
        assert method in response.headers["access-control-allow-methods"]


def test_cors_post_preflight_for_frontend_origins() -> None:
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
        response = client.options(
            "/api/reports/generate",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        assert "POST" in response.headers["access-control-allow-methods"]


def test_matplotlib_cache_dir_configuration() -> None:
    import matplotlib

    mpl_dir = os.environ.get("MPLCONFIGDIR")
    assert mpl_dir is not None
    assert os.path.isdir(mpl_dir)
    assert os.access(mpl_dir, os.W_OK)
    assert os.path.samefile(matplotlib.get_configdir(), mpl_dir)
    assert matplotlib.get_backend().lower() == "agg"


def test_system_info_returns_expected_schema() -> None:
    response = client.get("/api/system/info")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "hostname",
        "machine_name",
        "operating_system",
        "os_version",
        "os_release",
        "architecture",
        "processor",
        "cpu_architecture",
        "physical_cores",
        "logical_cores",
        "cpu_frequency",
        "boot_time",
        "uptime_seconds",
        "uptime_readable",
        "python_version",
        "application_platform",
    }
    assert set(data["cpu_frequency"]) == {"current_mhz", "min_mhz", "max_mhz"}
    SystemInfoResponse.model_validate(data)


def test_system_info_contains_valid_host_values() -> None:
    data = client.get("/api/system/info").json()

    assert data["hostname"].strip()
    assert data["machine_name"].strip()
    assert data["operating_system"].strip()
    assert data["os_version"].strip()
    assert data["os_release"].strip()
    assert data["architecture"] in {"32bit", "64bit"}
    assert data["cpu_architecture"].strip()
    assert data["python_version"].strip()
    assert data["uptime_seconds"] is None or data["uptime_seconds"] >= 0
    for core_count in (data["physical_cores"], data["logical_cores"]):
        assert core_count is None or core_count > 0
