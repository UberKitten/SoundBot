"""WebSocket manager for real-time updates to web clients."""

import logging
from datetime import datetime
from typing import Set

from fastapi import WebSocket
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SoundUpdateEvent(BaseModel):
    """Event sent when a sound is updated."""

    type: str = "sound_update"
    sound_name: str
    # New modified timestamp for cache busting
    modified: datetime
    # Action that caused the update: "add", "edit", "delete"
    action: str


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()

    @property
    def connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self._connections)

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self._connections.add(websocket)
        logger.debug(f"WebSocket connected. Total connections: {self.connection_count}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self._connections.discard(websocket)
        logger.debug(f"WebSocket disconnected. Total connections: {self.connection_count}")

    async def broadcast(self, message: str):
        """Broadcast a message to all connected clients."""
        if not self._connections:
            return

        # Send to all connections, removing any that fail
        disconnected: Set[WebSocket] = set()
        for websocket in self._connections:
            try:
                await websocket.send_text(message)
            except Exception:
                disconnected.add(websocket)

        # Clean up disconnected clients
        self._connections -= disconnected

    async def broadcast_sound_update(
        self, sound_name: str, modified: datetime, action: str = "edit"
    ):
        """Broadcast a sound update event to all clients."""
        event = SoundUpdateEvent(
            sound_name=sound_name,
            modified=modified,
            action=action,
        )
        await self.broadcast(event.model_dump_json())
        logger.debug(f"Broadcast sound update: {sound_name} ({action})")


# Global WebSocket manager instance
ws_manager = WebSocketManager()
