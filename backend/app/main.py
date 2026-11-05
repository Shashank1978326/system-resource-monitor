"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.cpu import router as cpu_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.anomalies import router as anomalies_router
from app.api.routes.disk import router as disk_router
from app.api.routes.history import router as history_router
from app.api.routes.gpu import router as gpu_router
from app.api.routes.memory import router as memory_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.network import router as network_router
from app.api.routes.predictions import router as predictions_router
from app.api.routes.processes import router as processes_router
from app.api.routes.reports import router as reports_router
from app.api.routes.system import router as system_router
from app.api.routes.websocket import connection_manager, router as websocket_router
from app.core.config import settings
from app.database.connection import dispose_database, initialize_database
from app.services.history_service import (
    HistoryService,
    HistoryStorageError,
    history_service,
)
from app.services.alert_service import cpu_alert_service
from app.services.anomaly_service import anomaly_service
from app.services.monitoring_service import monitoring_service

logger = logging.getLogger(__name__)


async def _publish_monitoring_updates() -> None:
    """Publish safe fields from the collector's existing latest snapshot."""
    while True:
        await asyncio.sleep(settings.websocket_publish_interval_seconds)
        snapshot = monitoring_service.get_snapshot()
        if snapshot is None:
            continue

        collected_at = datetime.fromisoformat(snapshot.timestamp.replace("Z", "+00:00"))
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)
        collected_at = collected_at.astimezone(timezone.utc)
        await connection_manager.broadcast(
            {
                "type": "resource_update",
                "timestamp": collected_at.isoformat().replace("+00:00", "Z"),
                "data": {
                    "cpu_percent": snapshot.cpu.cpu_usage_percent,
                    "memory_percent": snapshot.memory.usage_percent,
                    "disk_percent": HistoryService._disk_utilization(snapshot),
                    "network_download_bytes_per_sec": (
                        snapshot.network.download_speed_bytes_per_sec
                    ),
                    "network_upload_bytes_per_sec": (
                        snapshot.network.upload_speed_bytes_per_sec
                    ),
                },
            }
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize storage, then start and stop the single background collector."""
    publisher_task: asyncio.Task[None] | None = None
    try:
        initialize_database()
        await asyncio.to_thread(cpu_alert_service.restore_persisted_state)
        await asyncio.to_thread(anomaly_service.restore_persisted_state)
        try:
            await asyncio.to_thread(history_service.cleanup_expired)
        except HistoryStorageError:
            logger.exception("Unable to run startup history retention cleanup")
        await monitoring_service.start()
        publisher_task = asyncio.create_task(
            _publish_monitoring_updates(),
            name="system-resource-monitor-websocket-publisher",
        )
        yield
    finally:
        if publisher_task is not None:
            publisher_task.cancel()
            await asyncio.gather(publisher_task, return_exceptions=True)
        try:
            await monitoring_service.stop()
        finally:
            dispose_database()

app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
    lifespan=lifespan,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    """Attach standard defensive HTTP security headers to all responses."""
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["X-XSS-Protection"] = "0"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """Sanitize unexpected server errors and prevent internal trace disclosure."""
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    logger.exception("Unhandled server error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.include_router(system_router)
app.include_router(gpu_router)
app.include_router(cpu_router)
app.include_router(alerts_router)
app.include_router(anomalies_router)
app.include_router(memory_router)
app.include_router(disk_router)
app.include_router(network_router)
app.include_router(processes_router)
app.include_router(monitoring_router)
app.include_router(history_router)
app.include_router(predictions_router)
app.include_router(reports_router)
app.include_router(websocket_router)
