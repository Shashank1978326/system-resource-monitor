"""Tests for Feature 11D security remediations, headers, validation, and defensive protections."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main_module
from app.api.routes.websocket import (
    MAX_WEBSOCKET_CLIENTS,
    MAX_WEBSOCKET_MESSAGE_BYTES,
    connection_manager,
)
from app.schemas.monitoring import ProcessDetailResponse, ProcessInfoResponse
from app.services.report_service import report_service
from tests.test_websocket import SnapshotProvider, _snapshot

client = TestClient(main_module.app)


@pytest.fixture
def snapshot_provider(monkeypatch: pytest.MonkeyPatch):
    """Fixture providing a mock snapshot provider for WebSocket tests."""
    provider = SnapshotProvider([_snapshot()])
    monkeypatch.setattr(main_module, "monitoring_service", provider)
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(websocket_publish_interval_seconds=0.01),
    )
    assert connection_manager.client_count == 0
    yield provider
    assert connection_manager.client_count == 0


def test_security_headers_present_on_endpoints() -> None:
    """Verify standard defensive security headers are attached to HTTP responses."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert response.headers["X-XSS-Protection"] == "0"


def test_security_headers_present_on_root_endpoint() -> None:
    """Verify security headers are returned on root as well."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_unhandled_exception_returns_sanitized_500(monkeypatch) -> None:
    """Verify unhandled exceptions do not disclose internal stack traces or variables."""
    def crash():
        raise RuntimeError("SecretDatabasePasswordInTraceback: sensitive_value_12345")

    monkeypatch.setattr(main_module.monitoring_service, "get_snapshot", crash)

    unhandled_client = TestClient(main_module.app, raise_server_exceptions=False)
    response = unhandled_client.get("/api/cpu")
    assert response.status_code == 500
    data = response.json()
    assert data == {"detail": "Internal server error"}
    assert "SecretDatabasePasswordInTraceback" not in response.text
    assert "sensitive_value_12345" not in response.text


def test_websocket_rejects_oversized_messages(snapshot_provider) -> None:
    """Verify WebSocket terminates connections that attempt to send excessive payload sizes."""
    with TestClient(main_module.app) as test_client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with test_client.websocket_connect(
                "/ws/monitoring",
                headers={"origin": "http://127.0.0.1:5173"},
            ) as websocket:
                # Receive initial update
                websocket.receive_json()
                # Send an oversized message exceeding MAX_WEBSOCKET_MESSAGE_BYTES
                oversized_payload = "A" * (MAX_WEBSOCKET_MESSAGE_BYTES + 10)
                websocket.send_text(oversized_payload)
                # Next read should raise WebSocketDisconnect with 1009
                websocket.receive_text()
        assert rejected.value.code == 1009


def test_websocket_rejects_connections_exceeding_client_limit(snapshot_provider) -> None:
    """Verify WebSocket terminates connections when client limit is exceeded."""
    try:
        connection_manager._clients = set(range(MAX_WEBSOCKET_CLIENTS))

        with TestClient(main_module.app) as test_client:
            with pytest.raises(WebSocketDisconnect) as rejected:
                with test_client.websocket_connect(
                    "/ws/monitoring",
                    headers={"origin": "http://127.0.0.1:5173"},
                ):
                    pass
            assert rejected.value.code == 1013
    finally:
        connection_manager._clients.clear()


def test_process_schemas_strictly_exclude_sensitive_internals() -> None:
    """Verify that process schemas do not expose cmdline, environ, memory maps, or cwd."""
    info_fields = set(ProcessInfoResponse.model_fields.keys())
    detail_fields = set(ProcessDetailResponse.model_fields.keys())

    forbidden_fields = {"cmdline", "environ", "environment", "cwd", "exe", "open_files", "memory_maps"}
    assert not forbidden_fields.intersection(info_fields)
    assert not forbidden_fields.intersection(detail_fields)


def test_sql_injection_attempt_in_parameters_is_rejected() -> None:
    """Verify malicious SQL injection payloads in parameters are safely rejected or bounded."""
    injection_payload = "'; DROP TABLE historical_metrics; --"

    # In alert history resource filter
    response = client.get(f"/api/alerts/history?resource={injection_payload}")
    assert response.status_code == 422  # Pydantic Literal validation blocks injection

    # In prediction analytics resource filter
    response = client.get(f"/api/predictions/analytics?resource={injection_payload}")
    assert response.status_code == 400

    # In report range filter
    response = client.get(f"/api/reports/pdf?range={injection_payload}")
    assert response.status_code == 400


def test_path_traversal_in_report_parameters_is_rejected() -> None:
    """Verify path traversal characters are blocked in PDF report generation."""
    traversal_payload = "../../../etc/passwd"
    response = client.get(f"/api/reports/pdf?range={traversal_payload}")
    assert response.status_code == 400


def test_pdf_report_thread_lock_serialization() -> None:
    """Verify report service has a functional threading lock for serialized generation."""
    assert hasattr(report_service, "_lock")
    assert not report_service._lock.locked()
