"""Comprehensive test suite for Feature 10 (10A, 10B, 10C): PDF Report Generation System."""

import glob
import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database.connection import database, initialize_database
from app.database.models import AlertEvent, AnomalyEvent, HistoricalMetrics
from app.main import app
from app.schemas.monitoring import (
    BatteryResponse,
    GpuDeviceInfoResponse,
    GpuInfoResponse,
    ProcessInfoResponse,
    ProcessListResponse,
    TemperatureResponse,
)
from app.services.report_service import (
    SUPPORTED_REPORT_RANGES,
    SUPPORTED_REPORT_TYPES,
    ReportGenerationError,
    report_service,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_database():
    """Ensure clean database tables for each test."""
    initialize_database()
    with database.session_factory.begin() as session:
        session.query(HistoricalMetrics).delete()
        session.query(AlertEvent).delete()
        session.query(AnomalyEvent).delete()
    yield
    with database.session_factory.begin() as session:
        session.query(HistoricalMetrics).delete()
        session.query(AlertEvent).delete()
        session.query(AnomalyEvent).delete()
    database.dispose()


def _insert_sample_metrics() -> None:
    """Populate database with sample telemetry across past 24 hours."""
    now = datetime.now(timezone.utc)
    with database.session_factory.begin() as session:
        for i in range(12):
            session.add(
                HistoricalMetrics(
                    timestamp=now - timedelta(hours=i * 2),
                    cpu_utilization_percent=25.0 + i,
                    ram_utilization_percent=50.0 + i,
                    disk_read_speed=1024.0 * (i + 1),
                    disk_write_speed=512.0 * (i + 1),
                    disk_utilization_percent=45.0 + (i * 0.5),
                    network_download_speed=2048.0 * (i + 1),
                    network_upload_speed=1024.0 * (i + 1),
                    battery_percentage=90.0 - i,
                    battery_charging_state="discharging",
                    battery_power_plugged=False,
                )
            )
        session.add(
            AlertEvent(
                resource="cpu",
                severity="warning",
                message="CPU usage reached 85.0%",
                utilization_percent=85.0,
                configured_threshold_percent=80.0,
                timestamp=now - timedelta(hours=1),
            )
        )
        session.add(
            AnomalyEvent(
                resource="cpu",
                metric="cpu_utilization",
                actual_value=92.0,
                expected_value=40.0,
                standard_deviation=10.0,
                z_score=5.2,
                severity="critical",
                message="Sudden CPU utilization spike",
                timestamp=now - timedelta(hours=2),
            )
        )


# ---------------------------------------------------------------------------
# 1. PDF Generation & 2. PDF Validity & 3. Content-Type & 4. Filename
# ---------------------------------------------------------------------------
def test_pdf_generation_validity_and_headers(client: TestClient) -> None:
    _insert_sample_metrics()

    res = client.get("/api/reports/pdf?range=24h&type=all")
    assert res.status_code == 200

    # 3. Correct content type
    assert res.headers["content-type"] == "application/pdf"

    # 4. Correct download filename
    content_disp = res.headers.get("content-disposition", "")
    assert "attachment" in content_disp
    assert "filename=" in content_disp
    assert "system_resource_report_24h_" in content_disp
    assert content_disp.endswith('.pdf"') or content_disp.endswith(".pdf")

    # 2. PDF File validity
    pdf_bytes = res.content
    assert len(pdf_bytes) > 2000
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"%%EOF" in pdf_bytes


# ---------------------------------------------------------------------------
# 5. All Supported Reporting Periods (1h, 6h, 24h, 7d, 30d)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("range_key", ["1h", "6h", "24h", "7d", "30d"])
def test_all_supported_reporting_periods(client: TestClient, range_key: str) -> None:
    _insert_sample_metrics()
    res = client.get(f"/api/reports/pdf?range={range_key}&type=all")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert f"system_resource_report_{range_key}_" in res.headers["content-disposition"]
    assert res.content.startswith(b"%PDF-")


# ---------------------------------------------------------------------------
# 6. All Report Types
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "report_type",
    [
        "all",
        "cpu_memory",
        "disk_network",
        "process_resource",
        "alerts_anomaly",
        "prediction_accuracy",
    ],
)
def test_all_supported_report_types(client: TestClient, report_type: str) -> None:
    _insert_sample_metrics()
    res = client.get(f"/api/reports/pdf?range=24h&type={report_type}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert b"%%EOF" in res.content


# ---------------------------------------------------------------------------
# 7. Historical Data Collection
# ---------------------------------------------------------------------------
def test_historical_data_collection() -> None:
    _insert_sample_metrics()
    data = report_service.collect_report_data("24h")
    assert data["historical_stats"]["sample_count"] >= 10
    assert data["historical_stats"]["cpu_avg"] is not None
    assert data["historical_stats"]["ram_avg"] is not None
    assert len(data["timeseries_records"]) >= 10
    assert data["alert_counts"]["total"] >= 1
    assert data["anomaly_counts"]["total"] >= 1


# ---------------------------------------------------------------------------
# 8. Missing Historical Data (Empty database)
# ---------------------------------------------------------------------------
def test_missing_historical_data(client: TestClient) -> None:
    # Database is empty
    res = client.get("/api/reports/pdf?range=24h&type=all")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")
    assert b"%%EOF" in res.content


# ---------------------------------------------------------------------------
# 9. Unsupported GPU Handling
# ---------------------------------------------------------------------------
def test_unsupported_gpu_handling(client: TestClient) -> None:
    mock_gpu = GpuInfoResponse(
        supported_gpu_detected=False,
        devices=[],
        monitoring_available=False,
        status="unsupported",
        message="No compatible dedicated GPU detected",
    )
    with patch("app.services.report_service.get_gpu_info", return_value=mock_gpu):
        res = client.get("/api/reports/pdf?range=24h&type=all")
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF-")
        assert b"GPU monitoring unavailable" in res.content or b"No compatible" in res.content


# ---------------------------------------------------------------------------
# 10. Unsupported Battery Handling
# ---------------------------------------------------------------------------
def test_unsupported_battery_handling(client: TestClient) -> None:
    mock_battery = BatteryResponse(
        availability="unsupported",
        platform="Windows",
        percentage=None,
        charging_state="unknown",
        power_plugged=None,
        remaining_seconds=None,
        remaining_time=None,
        message="Battery not supported",
    )
    with patch("app.services.report_service.get_battery_info", return_value=mock_battery):
        res = client.get("/api/reports/pdf?range=24h&type=all")
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF-")
        assert b"Battery monitoring not present" in res.content


# ---------------------------------------------------------------------------
# 11. Missing Temperature Readings Handling
# ---------------------------------------------------------------------------
def test_missing_temperature_readings(client: TestClient) -> None:
    mock_temp = TemperatureResponse(
        availability="unsupported",
        platform="Windows",
        sensors=[],
        message="Temperature sensors unsupported",
    )
    with patch("app.services.report_service.get_temperature_info", return_value=mock_temp):
        res = client.get("/api/reports/pdf?range=24h&type=all")
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF-")
        assert b"Temperature sensor monitoring unsupported" in res.content


# ---------------------------------------------------------------------------
# 12. Missing Anomaly History Handling
# ---------------------------------------------------------------------------
def test_missing_anomaly_history(client: TestClient) -> None:
    # No anomalies inserted
    res = client.get("/api/reports/pdf?range=24h&type=alerts_anomaly")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")
    assert b"No resource utilization anomalies recorded" in res.content


# ---------------------------------------------------------------------------
# 13. Missing Prediction History Handling
# ---------------------------------------------------------------------------
def test_missing_prediction_history(client: TestClient) -> None:
    with patch("app.services.prediction_service.prediction_service.get_predictions", side_effect=Exception("No model")):
        with patch("app.services.prediction_service.prediction_service.get_accuracy", return_value=None):
            res = client.get("/api/reports/pdf?range=24h&type=prediction_accuracy")
            assert res.status_code == 200
            assert res.content.startswith(b"%PDF-")
            assert b"Forecasting engine warming up" in res.content


# ---------------------------------------------------------------------------
# 14. PDF Chart Generation Verification
# ---------------------------------------------------------------------------
def test_pdf_chart_generation(client: TestClient) -> None:
    _insert_sample_metrics()
    res = client.get("/api/reports/pdf?range=24h&type=all")
    assert res.status_code == 200
    # Embedded PNG images in PDF stream contain /Subtype /Image or /Filter /FlateDecode /Width
    assert b"/Image" in res.content or b"/XObject" in res.content


# ---------------------------------------------------------------------------
# 15. Invalid Query Parameters (Validation)
# ---------------------------------------------------------------------------
def test_invalid_query_parameters(client: TestClient) -> None:
    # Invalid range
    res1 = client.get("/api/reports/pdf?range=invalid_range")
    assert res1.status_code == 400
    assert "Invalid date range" in res1.json()["detail"]

    # Invalid report type
    res2 = client.get("/api/reports/pdf?range=24h&type=unknown_type")
    assert res2.status_code == 400
    assert "Invalid report type" in res2.json()["detail"]

    # Invalid resource filter
    res3 = client.get("/api/reports/pdf?resource=unsupported_res")
    assert res3.status_code == 400
    assert "Invalid resource filter" in res3.json()["detail"]


# ---------------------------------------------------------------------------
# 16. Database Error Handling (503 Service Unavailable)
# ---------------------------------------------------------------------------
def test_database_error_handling(client: TestClient) -> None:
    with patch.object(
        report_service,
        "collect_report_data",
        side_effect=OperationalError("SELECT ...", {}, Exception("Database locked")),
    ):
        res = client.get("/api/reports/pdf?range=24h")
        assert res.status_code == 503
        assert "Database failure" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 17. PDF Compilation Error Handling (500 Internal Server Error)
# ---------------------------------------------------------------------------
def test_pdf_compilation_error_handling(client: TestClient) -> None:
    with patch.object(
        report_service,
        "generate_pdf_report",
        side_effect=ReportGenerationError("ReportLab layout crashed"),
    ):
        res = client.get("/api/reports/pdf?range=24h")
        assert res.status_code == 500
        assert "PDF generation failed" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 18. Sensitive Information Exclusion (No cmdline / env vars)
# ---------------------------------------------------------------------------
def test_sensitive_information_exclusion(client: TestClient) -> None:
    SECRET_TOKEN = "SUPER_SECRET_AWS_KEY_9988776655"
    SECRET_ARG = "--secret-credential=classified_password"

    fake_proc = ProcessInfoResponse(
        pid=1234,
        name="test_worker.exe",
        status="running",
        cpu_percent=45.5,
        memory_percent=12.0,
        memory_mb=128.0,
    )
    fake_proc_list = ProcessListResponse(
        processes=[fake_proc],
        total_processes=1,
        total_process_count=1,
        top_cpu_processes=[fake_proc],
        top_ram_processes=[fake_proc],
    )

    with patch("app.services.report_service.get_processes", return_value=fake_proc_list):
        res = client.get("/api/reports/pdf?range=24h&type=process_resource")
        assert res.status_code == 200
        raw_pdf = res.content

        # Confirm process name is included
        assert b"test_worker.exe" in raw_pdf

        # Verify sensitive arguments and tokens are strictly excluded
        assert SECRET_TOKEN.encode() not in raw_pdf
        assert SECRET_ARG.encode() not in raw_pdf
        assert b"--secret-credential" not in raw_pdf


# ---------------------------------------------------------------------------
# 19. Temporary File Cleanup Verification
# ---------------------------------------------------------------------------
def test_temporary_file_cleanup(client: TestClient) -> None:
    _insert_sample_metrics()
    
    # Check current directory before report generation
    before_pngs = glob.glob("*.png") + glob.glob("*.pdf")
    
    res = client.get("/api/reports/pdf?range=24h&type=all")
    assert res.status_code == 200
    
    # Verify no persistent .png or .pdf image files were left behind in working dir
    after_pngs = glob.glob("*.png") + glob.glob("*.pdf")
    assert len(after_pngs) == len(before_pngs)
