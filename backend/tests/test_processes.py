"""Tests for process resource monitoring."""

from types import SimpleNamespace
from unittest.mock import patch

import psutil
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.monitoring import ProcessInfoResponse, ProcessListResponse
from app.services import process_service

_SYSTEM_MEMORY_BYTES = 8 * 1024 * 1024 * 1024


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


class FakeProcess:
    def __init__(
        self,
        pid: int,
        name: str,
        cpu_percent: float | Exception = 0.0,
        memory_bytes: int | Exception = 0,
        status: str = "running",
        create_time: float | None = None,
        thread_count: int | Exception = 1,
        username: str | Exception | None = "test-user",
        name_error: Exception | None = None,
    ) -> None:
        self.info = {
            "pid": pid,
            "name": name,
            "status": status,
            "create_time": create_time if create_time is not None else float(pid),
        }
        self._cpu_percent = cpu_percent
        self._memory_bytes = memory_bytes
        self._thread_count = thread_count
        self._username = username
        self._name_error = name_error

    def cpu_percent(self, interval: float | None = None) -> float:
        if isinstance(self._cpu_percent, Exception):
            raise self._cpu_percent
        return self._cpu_percent

    def memory_info(self) -> SimpleNamespace:
        if isinstance(self._memory_bytes, Exception):
            raise self._memory_bytes
        return SimpleNamespace(rss=self._memory_bytes)

    def name(self) -> str:
        if self._name_error is not None:
            raise self._name_error
        return str(self.info["name"])

    def status(self) -> str:
        return str(self.info["status"])

    def create_time(self) -> float:
        return float(self.info["create_time"])

    def num_threads(self) -> int:
        if isinstance(self._thread_count, Exception):
            raise self._thread_count
        return self._thread_count

    def username(self) -> str | None:
        if isinstance(self._username, Exception):
            raise self._username
        return self._username


def _process(
    pid: int,
    name: str,
    cpu_percent: float = 0.0,
    memory_mb: float = 0.0,
    status: str = "running",
) -> FakeProcess:
    return FakeProcess(
        pid,
        name,
        cpu_percent=cpu_percent,
        memory_bytes=int(memory_mb * 1024 * 1024),
        status=status,
    )


def _sample_processes(processes: list[FakeProcess], **kwargs) -> ProcessListResponse:
    with (
        patch(
            "app.services.process_service.psutil.process_iter",
            return_value=processes,
        ),
        patch(
            "app.services.process_service.psutil.virtual_memory",
            return_value=SimpleNamespace(total=_SYSTEM_MEMORY_BYTES),
        ),
    ):
        return process_service.get_processes(**kwargs)


def test_process_endpoint_returns_extended_structured_processes(
    client: TestClient,
) -> None:
    processes = ProcessListResponse(
        total_processes=1,
        processes=[
            ProcessInfoResponse(
                pid=123,
                name="example",
                status="running",
                cpu_percent=None,
                memory_mb=12.5,
                memory_percent=0.15,
            ),
        ],
        total_process_count=1,
        top_cpu_processes=[],
        top_ram_processes=[],
    )
    with patch("app.api.routes.processes.get_processes", return_value=processes) as get:
        response = client.get("/api/processes")

    assert response.status_code == 200
    assert response.json() == {
        "total_processes": 1,
        "processes": [
            {
                "pid": 123,
                "name": "example",
                "status": "running",
                "cpu_percent": None,
                "memory_mb": 12.5,
                "memory_percent": 0.15,
            }
        ],
        "total_process_count": 1,
        "top_cpu_processes": [],
        "top_ram_processes": [],
    }
    get.assert_called_once_with(
        search=None,
        status=None,
        limit=100,
        sort_by="pid",
        sort_order="asc",
    )


def test_process_endpoint_returns_empty_list(client: TestClient) -> None:
    with patch(
        "app.api.routes.processes.get_processes",
        return_value=ProcessListResponse(
            total_processes=0,
            processes=[],
            total_process_count=0,
            top_cpu_processes=[],
            top_ram_processes=[],
        ),
    ):
        response = client.get("/api/processes")

    assert response.status_code == 200
    assert response.json() == {
        "total_processes": 0,
        "processes": [],
        "total_process_count": 0,
        "top_cpu_processes": [],
        "top_ram_processes": [],
    }


def test_process_endpoint_passes_search_limit_and_sort(client: TestClient) -> None:
    with patch(
        "app.api.routes.processes.get_processes",
        return_value=ProcessListResponse(
            total_processes=0,
            processes=[],
            total_process_count=0,
            top_cpu_processes=[],
            top_ram_processes=[],
        ),
    ) as get:
        response = client.get(
            "/api/processes?search=python&status=running&limit=2&sort_by=cpu&sort_order=desc"
        )

    assert response.status_code == 200
    get.assert_called_once_with(
        search="python",
        status="running",
        limit=2,
        sort_by="cpu",
        sort_order="desc",
    )


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=501",
        f"?search={'x' * 101}",
        "?sort_by=invalid",
        "?sort_order=invalid",
        f"?status={'x' * 33}",
    ],
)
def test_process_endpoint_validates_query_parameters(
    client: TestClient,
    query: str,
) -> None:
    assert client.get(f"/api/processes{query}").status_code == 422


def test_process_service_returns_actual_cpu_and_ram_measurements() -> None:
    process = _process(10, "measured", cpu_percent=27.5, memory_mb=64)
    identity = (10, 10.0)
    with patch.object(process_service, "_sampled_cpu_processes", {identity}):
        response = _sample_processes([process])

    measured = response.processes[0]
    assert measured.cpu_percent == 27.5
    assert measured.memory_mb == 64
    assert measured.memory_percent == pytest.approx(
        64 * 1024 * 1024 / _SYSTEM_MEMORY_BYTES * 100
    )


def test_cpu_is_unavailable_for_initial_psutil_sample() -> None:
    process = _process(10, "new-process", cpu_percent=0)
    with patch.object(process_service, "_sampled_cpu_processes", set()):
        first = _sample_processes([process])
    assert first.processes[0].cpu_percent is None
    assert first.top_cpu_processes == []

    with patch.object(process_service, "_sampled_cpu_processes", {(10, 10.0)}):
        second = _sample_processes([process])
    assert second.processes[0].cpu_percent == 0


@pytest.mark.parametrize(
    ("sort_by", "sort_order", "expected_pids"),
    [
        ("cpu", "desc", [2, 3, 1]),
        ("cpu", "asc", [1, 3, 2]),
        ("ram", "desc", [3, 1, 2]),
        ("ram", "asc", [2, 1, 3]),
    ],
)
def test_process_service_sorts_by_cpu_and_ram(
    sort_by: str,
    sort_order: str,
    expected_pids: list[int],
) -> None:
    processes = [
        _process(1, "one", cpu_percent=10, memory_mb=20),
        _process(2, "two", cpu_percent=30, memory_mb=10),
        _process(3, "three", cpu_percent=20, memory_mb=40),
    ]
    sampled = {(process.info["pid"], process.info["create_time"]) for process in processes}
    with patch.object(process_service, "_sampled_cpu_processes", sampled):
        response = _sample_processes(
            processes,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    assert [process.pid for process in response.processes] == expected_pids


def test_process_service_returns_top_five_and_total_count() -> None:
    processes = [
        _process(pid, f"process-{pid}", cpu_percent=pid, memory_mb=20 - pid)
        for pid in range(1, 8)
    ]
    sampled = {(process.info["pid"], process.info["create_time"]) for process in processes}
    with patch.object(process_service, "_sampled_cpu_processes", sampled):
        response = _sample_processes(processes, limit=2, sort_by="cpu", sort_order="asc")

    assert response.total_process_count == 7
    assert response.total_processes == 7
    assert len(response.processes) == 2
    assert [process.pid for process in response.top_cpu_processes] == [7, 6, 5, 4, 3]
    assert [process.pid for process in response.top_ram_processes] == [1, 2, 3, 4, 5]


def test_cpu_top_five_excludes_windows_idle_pseudo_process() -> None:
    processes = [
        _process(0, "System Idle Process", cpu_percent=800),
        _process(1, "worker", cpu_percent=12),
    ]
    with patch.object(process_service, "_sampled_cpu_processes", {(0, 0.0), (1, 1.0)}):
        response = _sample_processes(processes)

    assert [process.pid for process in response.top_cpu_processes] == [1]


def test_process_service_filters_case_insensitively_and_limits_results() -> None:
    with patch.object(process_service, "_sampled_cpu_processes", set()):
        response = _sample_processes(
            [_process(4, "Python"), _process(2, "pythonw"), _process(3, "other")],
            search="PYTHON",
            limit=1,
        )

    assert response.total_processes == 2
    assert [process.pid for process in response.processes] == [2]


def test_process_service_filters_by_name_and_status() -> None:
    processes = [
        _process(1, "Python", status="running"),
        _process(2, "Python Worker", status="sleeping"),
        _process(3, "Worker", status="running"),
    ]
    with patch.object(process_service, "_sampled_cpu_processes", set()):
        response = _sample_processes(processes, search="python", status="RUNNING")

    assert response.total_processes == 1
    assert [process.pid for process in response.processes] == [1]


def test_process_detail_endpoint_returns_runtime_metrics(client: TestClient) -> None:
    process = FakeProcess(
        123,
        "example",
        cpu_percent=18.5,
        memory_bytes=64 * 1024 * 1024,
        status="running",
        create_time=1_700_000_000,
        thread_count=6,
        username="alice",
    )
    with (
        patch.object(process_service, "_sampled_cpu_processes", {(123, 1_700_000_000.0)}),
        patch("app.services.process_service.psutil.Process", return_value=process),
        patch(
            "app.services.process_service.psutil.virtual_memory",
            return_value=SimpleNamespace(total=_SYSTEM_MEMORY_BYTES),
        ),
    ):
        response = client.get("/api/processes/123")

    assert response.status_code == 200
    detail = response.json()
    assert detail["pid"] == 123
    assert detail["name"] == "example"
    assert detail["status"] == "running"
    assert detail["cpu_percent"] == 18.5
    assert detail["memory_mb"] == 64
    assert detail["memory_percent"] == pytest.approx(0.78125)
    assert detail["thread_count"] == 6
    assert detail["create_time"] == "2023-11-14T22:13:20Z"
    assert detail["username"] == "alice"
    assert "cmdline" not in detail
    assert "environment" not in detail


def test_process_detail_reports_invalid_pid_as_validation_error(
    client: TestClient,
) -> None:
    assert client.get("/api/processes/0").status_code == 422


def test_process_detail_reports_access_denied(client: TestClient) -> None:
    with patch(
        "app.services.process_service.psutil.Process",
        side_effect=psutil.AccessDenied(pid=321),
    ):
        response = client.get("/api/processes/321")

    assert response.status_code == 403
    assert response.json()["detail"] == "Access to this process is denied"


def test_process_detail_reports_disappeared_process_as_not_found(
    client: TestClient,
) -> None:
    with patch(
        "app.services.process_service.psutil.Process",
        side_effect=psutil.NoSuchProcess(pid=987654),
    ):
        response = client.get("/api/processes/987654")

    assert response.status_code == 404
    assert response.json()["detail"] == "Process no longer exists"


def test_process_detail_handles_process_disappearing_during_lookup(
    client: TestClient,
) -> None:
    process = FakeProcess(
        654,
        "transient",
        name_error=psutil.NoSuchProcess(pid=654),
    )
    with (
        patch("app.services.process_service.psutil.Process", return_value=process),
        patch(
            "app.services.process_service.psutil.virtual_memory",
            return_value=SimpleNamespace(total=_SYSTEM_MEMORY_BYTES),
        ),
    ):
        response = client.get("/api/processes/654")

    assert response.status_code == 404


def test_process_detail_returns_unavailable_username_when_access_is_denied(
    client: TestClient,
) -> None:
    process = FakeProcess(
        321,
        "restricted",
        username=psutil.AccessDenied(pid=321),
    )
    with (
        patch.object(process_service, "_sampled_cpu_processes", set()),
        patch("app.services.process_service.psutil.Process", return_value=process),
        patch(
            "app.services.process_service.psutil.virtual_memory",
            return_value=SimpleNamespace(total=_SYSTEM_MEMORY_BYTES),
        ),
    ):
        response = client.get("/api/processes/321")

    assert response.status_code == 200
    assert response.json()["username"] is None


def test_process_service_skips_disappeared_access_denied_and_zombie_processes() -> None:
    processes = [
        _process(7, "available"),
        FakeProcess(8, "denied", cpu_percent=psutil.AccessDenied(pid=8)),
        FakeProcess(9, "disappeared", cpu_percent=psutil.NoSuchProcess(pid=9)),
        FakeProcess(10, "zombie", memory_bytes=psutil.ZombieProcess(pid=10)),
    ]
    with patch.object(process_service, "_sampled_cpu_processes", set()):
        response = _sample_processes(processes)

    assert response.total_process_count == 2
    assert {process.pid for process in response.processes} == {7, 8}
    denied = next(process for process in response.processes if process.pid == 8)
    assert denied.cpu_percent is None
    assert denied.memory_mb == 0


def test_process_service_keeps_process_when_ram_is_access_denied() -> None:
    process = FakeProcess(11, "restricted", cpu_percent=12, memory_bytes=psutil.AccessDenied())
    with patch.object(process_service, "_sampled_cpu_processes", {(11, 11.0)}):
        response = _sample_processes([process])

    assert len(response.processes) == 1
    assert response.processes[0].cpu_percent == 12
    assert response.processes[0].memory_mb is None
    assert response.processes[0].memory_percent is None


def test_process_endpoint_reports_collection_failure(client: TestClient) -> None:
    with patch(
        "app.api.routes.processes.get_processes",
        side_effect=psutil.Error("enumeration failed"),
    ):
        response = client.get("/api/processes")

    assert response.status_code == 503
    assert response.json()["detail"] == "Process information is temporarily unavailable"
