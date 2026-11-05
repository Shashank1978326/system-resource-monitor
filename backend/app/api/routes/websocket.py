"""WebSocket delivery of the latest background monitoring snapshot."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["monitoring"])

MAX_WEBSOCKET_CLIENTS = 100
MAX_WEBSOCKET_MESSAGE_BYTES = 4096


class MonitoringConnectionManager:
    """Track connected clients and isolate failures while publishing updates."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, message: dict[str, object]) -> None:
        clients = tuple(self._clients)
        if not clients:
            return
        results = await asyncio.gather(
            *(client.send_json(message) for client in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                logger.warning(
                    "Removing a monitoring WebSocket after a send failure",
                    exc_info=result,
                )
                self.disconnect(client)


connection_manager = MonitoringConnectionManager()


@router.websocket("/ws/monitoring")
async def monitoring_updates(websocket: WebSocket) -> None:
    """Keep the connection open while the application publisher sends updates."""
    origin = websocket.headers.get("origin")
    if origin not in settings.cors_allowed_origins:
        logger.warning("Rejected monitoring WebSocket from untrusted origin %r", origin)
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    if connection_manager.client_count >= MAX_WEBSOCKET_CLIENTS:
        logger.warning(
            "Rejected monitoring WebSocket: maximum client limit (%d) reached",
            MAX_WEBSOCKET_CLIENTS,
        )
        await websocket.close(code=1013, reason="Maximum connection limit reached")
        return

    try:
        await connection_manager.connect(websocket)
        while True:
            payload = await websocket.receive_text()
            if len(payload) > MAX_WEBSOCKET_MESSAGE_BYTES:
                logger.warning(
                    "Closing monitoring WebSocket: received message exceeds %d bytes",
                    MAX_WEBSOCKET_MESSAGE_BYTES,
                )
                await websocket.close(code=1009, reason="Message too large")
                break
    except WebSocketDisconnect:
        pass
    except (OSError, RuntimeError):
        logger.debug("Monitoring WebSocket connection ended with an error", exc_info=True)
    finally:
        connection_manager.disconnect(websocket)
