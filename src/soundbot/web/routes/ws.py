"""WebSocket route for real-time updates."""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from soundbot.web.websocket import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time sound updates.

    Clients connect here to receive notifications when sounds are
    added, modified, or deleted. This enables cache busting without
    requiring polling.
    """
    await ws_manager.connect(websocket)
    try:
        # Keep connection open, just wait for disconnect
        while True:
            # We don't expect messages from clients, but we need to
            # receive to detect disconnection
            _ = await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket)
