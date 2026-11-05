"""Unit and integration tests for Feature 8C: Anomaly Trend Analytics."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database.connection import database, initialize_database
from app.main import app
from app.services.anomaly_service import anomaly_repository, anomaly_service


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_services():
    """Ensure a clean repository and cache state for each test."""
    initialize_database()
    anomaly_repository.clear_events()
    anomaly_service.reset()
    yield
    anomaly_repository.clear_events()
    anomaly_service.reset()
    database.dispose()


def test_anomaly_analytics_empty_database(client: TestClient) -> None:
    """Empty database returns zero counts and zero percentages across timeline, resources, and metrics."""
    response = client.get("/api/anomalies/analytics?range=24h")
    assert response.status_code == 200
    data = response.json()

    assert data["range"] == "24h"
    assert data["total_anomalies"] == 0
    assert data["warning_count"] == 0
    assert data["critical_count"] == 0

    # Timeline buckets must exist and all have zero counts
    assert len(data["timeline"]) > 0
    for point in data["timeline"]:
        assert point["total_count"] == 0
        assert point["warning_count"] == 0
        assert point["critical_count"] == 0

    # Resources must contain cpu, memory, disk, network
    res_names = {r["resource"] for r in data["by_resource"]}
    assert res_names == {"cpu", "memory", "disk", "network"}
    for r in data["by_resource"]:
        assert r["total_count"] == 0
        assert r["warning_count"] == 0
        assert r["critical_count"] == 0
        assert r["percentage"] == 0.0

    # Metrics must contain the 6 monitored metrics
    metric_names = {m["metric"] for m in data["by_metric"]}
    assert metric_names == {
        "cpu_utilization",
        "memory_utilization",
        "disk_read_throughput",
        "disk_write_throughput",
        "network_download_throughput",
        "network_upload_throughput",
    }
    for m in data["by_metric"]:
        assert m["total_count"] == 0
        assert m["percentage"] == 0.0


def test_anomaly_analytics_time_ranges(client: TestClient) -> None:
    """Events fall into appropriate time range filters (1h, 6h, 24h, 7d, 30d)."""
    now = datetime.now(timezone.utc)

    # 1. 30 minutes ago (in 1h, 6h, 24h, 7d, 30d)
    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=90.0,
        expected_value=20.0,
        standard_deviation=5.0,
        z_score=14.0,
        severity="Critical",
        message="CPU anomaly",
        timestamp=now - timedelta(minutes=30),
    )
    # 2. 3 hours ago (in 6h, 24h, 7d, 30d)
    anomaly_repository.insert_event(
        resource="memory",
        metric="memory_utilization",
        actual_value=85.0,
        expected_value=30.0,
        standard_deviation=5.0,
        z_score=11.0,
        severity="Warning",
        message="Memory anomaly",
        timestamp=now - timedelta(hours=3),
    )
    # 3. 18 hours ago (in 24h, 7d, 30d)
    anomaly_repository.insert_event(
        resource="disk",
        metric="disk_read_throughput",
        actual_value=50_000_000.0,
        expected_value=1_000_000.0,
        standard_deviation=100_000.0,
        z_score=49.0,
        severity="Warning",
        message="Disk read anomaly",
        timestamp=now - timedelta(hours=18),
    )
    # 4. 4 days ago (in 7d, 30d)
    anomaly_repository.insert_event(
        resource="network",
        metric="network_download_throughput",
        actual_value=20_000_000.0,
        expected_value=500_000.0,
        standard_deviation=50_000.0,
        z_score=39.0,
        severity="Critical",
        message="Network download anomaly",
        timestamp=now - timedelta(days=4),
    )
    # 5. 20 days ago (in 30d only)
    anomaly_repository.insert_event(
        resource="network",
        metric="network_upload_throughput",
        actual_value=10_000_000.0,
        expected_value=200_000.0,
        standard_deviation=20_000.0,
        z_score=49.0,
        severity="Warning",
        message="Network upload anomaly",
        timestamp=now - timedelta(days=20),
    )
    # 6. 40 days ago (older than 30d)
    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=99.0,
        expected_value=15.0,
        standard_deviation=5.0,
        z_score=16.8,
        severity="Critical",
        message="Old CPU anomaly",
        timestamp=now - timedelta(days=40),
    )

    # 1h: only 1 event
    res1h = client.get("/api/anomalies/analytics?range=1h").json()
    assert res1h["total_anomalies"] == 1
    assert res1h["critical_count"] == 1

    # 6h: 2 events
    res6h = client.get("/api/anomalies/analytics?range=6h").json()
    assert res6h["total_anomalies"] == 2
    assert res6h["warning_count"] == 1
    assert res6h["critical_count"] == 1

    # 24h: 3 events
    res24h = client.get("/api/anomalies/analytics?range=24h").json()
    assert res24h["total_anomalies"] == 3
    assert res24h["warning_count"] == 2
    assert res24h["critical_count"] == 1

    # 7d: 4 events
    res7d = client.get("/api/anomalies/analytics?range=7d").json()
    assert res7d["total_anomalies"] == 4
    assert res7d["warning_count"] == 2
    assert res7d["critical_count"] == 2

    # 30d: 5 events (excludes the 40 days old event)
    res30d = client.get("/api/anomalies/analytics?range=30d").json()
    assert res30d["total_anomalies"] == 5
    assert res30d["warning_count"] == 3
    assert res30d["critical_count"] == 2


def test_anomaly_analytics_resource_and_metric_breakdown(client: TestClient) -> None:
    """Resource-wise and metric-wise breakdowns calculate exact counts and percentages."""
    now = datetime.now(timezone.utc)

    # Insert:
    # 2 CPU events (1 Warning, 1 Critical)
    # 2 Memory events (2 Warning, 0 Critical)
    # 1 Disk event (0 Warning, 1 Critical)
    # Total = 5 events
    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=75.0,
        expected_value=25.0,
        standard_deviation=5.0,
        z_score=10.0,
        severity="Warning",
        message="CPU warning",
        timestamp=now - timedelta(minutes=10),
    )
    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=95.0,
        expected_value=25.0,
        standard_deviation=5.0,
        z_score=14.0,
        severity="Critical",
        message="CPU critical",
        timestamp=now - timedelta(minutes=8),
    )
    anomaly_repository.insert_event(
        resource="memory",
        metric="memory_utilization",
        actual_value=80.0,
        expected_value=30.0,
        standard_deviation=5.0,
        z_score=10.0,
        severity="Warning",
        message="Memory warning 1",
        timestamp=now - timedelta(minutes=6),
    )
    anomaly_repository.insert_event(
        resource="memory",
        metric="memory_utilization",
        actual_value=88.0,
        expected_value=30.0,
        standard_deviation=5.0,
        z_score=11.6,
        severity="Warning",
        message="Memory warning 2",
        timestamp=now - timedelta(minutes=4),
    )
    anomaly_repository.insert_event(
        resource="disk",
        metric="disk_write_throughput",
        actual_value=80_000_000.0,
        expected_value=1_000_000.0,
        standard_deviation=100_000.0,
        z_score=79.0,
        severity="Critical",
        message="Disk write critical",
        timestamp=now - timedelta(minutes=2),
    )

    res = client.get("/api/anomalies/analytics?range=1h").json()
    assert res["total_anomalies"] == 5
    assert res["warning_count"] == 3
    assert res["critical_count"] == 2

    # Check by_resource
    by_res = {r["resource"]: r for r in res["by_resource"]}
    assert by_res["cpu"]["total_count"] == 2
    assert by_res["cpu"]["warning_count"] == 1
    assert by_res["cpu"]["critical_count"] == 1
    assert by_res["cpu"]["percentage"] == 40.0

    assert by_res["memory"]["total_count"] == 2
    assert by_res["memory"]["warning_count"] == 2
    assert by_res["memory"]["critical_count"] == 0
    assert by_res["memory"]["percentage"] == 40.0

    assert by_res["disk"]["total_count"] == 1
    assert by_res["disk"]["warning_count"] == 0
    assert by_res["disk"]["critical_count"] == 1
    assert by_res["disk"]["percentage"] == 20.0

    assert by_res["network"]["total_count"] == 0
    assert by_res["network"]["percentage"] == 0.0

    # Check by_metric
    by_met = {m["metric"]: m for m in res["by_metric"]}
    assert by_met["cpu_utilization"]["total_count"] == 2
    assert by_met["cpu_utilization"]["percentage"] == 40.0
    assert by_met["memory_utilization"]["total_count"] == 2
    assert by_met["memory_utilization"]["percentage"] == 40.0
    assert by_met["disk_write_throughput"]["total_count"] == 1
    assert by_met["disk_write_throughput"]["critical_count"] == 1
    assert by_met["disk_write_throughput"]["percentage"] == 20.0
    assert by_met["disk_read_throughput"]["total_count"] == 0


def test_anomaly_analytics_filters(client: TestClient) -> None:
    """Filtering by resource, metric, or severity properly restricts analytics results."""
    now = datetime.now(timezone.utc)

    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=75.0,
        expected_value=25.0,
        standard_deviation=5.0,
        z_score=10.0,
        severity="Warning",
        message="CPU warning",
        timestamp=now - timedelta(minutes=15),
    )
    anomaly_repository.insert_event(
        resource="cpu",
        metric="cpu_utilization",
        actual_value=95.0,
        expected_value=25.0,
        standard_deviation=5.0,
        z_score=14.0,
        severity="Critical",
        message="CPU critical",
        timestamp=now - timedelta(minutes=10),
    )
    anomaly_repository.insert_event(
        resource="memory",
        metric="memory_utilization",
        actual_value=85.0,
        expected_value=30.0,
        standard_deviation=5.0,
        z_score=11.0,
        severity="Critical",
        message="Memory critical",
        timestamp=now - timedelta(minutes=5),
    )

    # Filter resource=cpu: 2 events
    cpu_res = client.get("/api/anomalies/analytics?range=1h&resource=cpu").json()
    assert cpu_res["total_anomalies"] == 2
    assert cpu_res["by_resource"][0]["percentage"] == 100.0

    # Filter severity=Critical: 2 events (1 CPU, 1 Memory)
    crit_res = client.get("/api/anomalies/analytics?range=1h&severity=Critical").json()
    assert crit_res["total_anomalies"] == 2
    assert crit_res["warning_count"] == 0
    assert crit_res["critical_count"] == 2

    # Filter metric=cpu_utilization: 2 events
    met_res = client.get(
        "/api/anomalies/analytics?range=1h&metric=cpu_utilization"
    ).json()
    assert met_res["total_anomalies"] == 2


def test_anomaly_analytics_validation_error(client: TestClient) -> None:
    """Invalid time range where start_time > end_time returns 400 Bad Request."""
    now = datetime.now(timezone.utc)
    start = (now + timedelta(hours=1)).isoformat()
    end = now.isoformat()
    response = client.get(
        "/api/anomalies/analytics",
        params={"start_time": start, "end_time": end},
    )
    assert response.status_code == 400
    assert "start_time must be earlier than" in response.json()["detail"]
