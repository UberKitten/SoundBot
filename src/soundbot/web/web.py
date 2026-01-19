import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from soundbot.core.settings import settings
from soundbot.services.sounds import sound_service
from soundbot.web.routes.router import router
from soundbot.web.websocket import ws_manager

logger = logging.getLogger(__name__)

web: FastAPI | None = None


class CachedStaticFiles(StaticFiles):
    """StaticFiles with aggressive caching headers.
    
    Since we use cache-busting query params (?v=timestamp), we can
    tell browsers to cache forever without revalidation.
    """

    async def get_response(self, path: str, scope) -> Response:
        response = await super().get_response(path, scope)
        # Cache for 1 year, immutable means don't even check for updates
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _on_sound_update(name: str, modified: datetime, action: str):
    """Bridge callback to async WebSocket broadcast."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(ws_manager.broadcast_sound_update(name, modified, action))
    except RuntimeError:
        # No running loop, skip broadcast
        pass


def get_web():
    global web

    if not web:
        web = FastAPI(
            title="SoundBot",
            docs_url="/api/docs",
            default_response_class=ORJSONResponse,
        )

        web.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        web.include_router(router)

        # Register WebSocket callback for sound updates
        sound_service.on_sound_update(_on_sound_update)

        sounds_path = Path(settings.sounds_folder)
        if sounds_path.exists():
            web.mount(
                "/sounds", CachedStaticFiles(directory=sounds_path.absolute()), name="sounds"
            )
        else:
            logger.warn(f"Sounds folder {sounds_path.absolute()} does not exist")

        static_path = Path(settings.static_folder)
        if static_path.exists():
            web.mount(
                "/",
                StaticFiles(directory=static_path.absolute(), html=True),
                name="static",
            )
        else:
            logger.warn(f"Static folder {static_path.absolute()} does not exist")

    return web
