import asyncio
import logging
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import override

from fastapi import FastAPI, HTTPException
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import Scope

from soundbot.core.settings import settings
from soundbot.models.sounds import SoundGroupData
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

    @override
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Cache for 1 year, immutable means don't even check for updates
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


# Raw source video must not be publicly downloadable — admins get a
# transcoded clip via the authed /api/admin/sounds/{name}/video endpoint.
VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".webm", ".mov", ".m4v", ".avi"}
)


class SoundStaticFiles(CachedStaticFiles):
    """Static serving for /sounds with raw video + dot-paths blocked.

    Rejects (with a 404, to avoid leaking file existence):
    - any file with a video extension (raw originals/trims stay private)
    - any path with a segment starting with "." (blocks .drafts/, dotfiles)

    Audio (.ogg, .mp3) and metadata remain public — the soundboard and the
    waveform editor rely on them.
    """

    @override
    async def get_response(self, path: str, scope: Scope) -> Response:
        segments = PurePosixPath(path).parts
        if any(segment.startswith(".") for segment in segments):
            raise HTTPException(status_code=404)
        if PurePosixPath(path).suffix.lower() in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


def _on_sound_update(name: str, modified: datetime, action: str):
    """Bridge callback to async WebSocket broadcast."""
    try:
        loop = asyncio.get_running_loop()
        _ = loop.create_task(ws_manager.broadcast_sound_update(name, modified, action))
    except RuntimeError:
        # No running loop, skip broadcast
        pass


def _on_group_update(name: str, group_data: SoundGroupData, action: str):
    """Bridge callback to async WebSocket broadcast."""
    try:
        loop = asyncio.get_running_loop()
        _ = loop.create_task(
            ws_manager.broadcast_group_update(
                name,
                group_data.members,
                action,
                created=group_data.created,
                random_mode=group_data.random_mode,
                discord_plays=group_data.discord.plays,
                twitch_plays=group_data.twitch.plays,
                web_plays=group_data.web.plays,
            )
        )
    except RuntimeError:
        pass


def get_web():
    global web

    if not web:
        web = FastAPI(
            title=settings.app_title,
            docs_url="/api/docs",
            default_response_class=ORJSONResponse,
        )

        web.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            # credentials + wildcard origin is spec-invalid; the frontend is
            # same-origin so cookies are unaffected by CORS regardless.
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        web.include_router(router)

        # Register WebSocket callbacks for real-time updates
        sound_service.on_sound_update(_on_sound_update)
        sound_service.on_group_update(_on_group_update)

        sounds_path = Path(settings.sounds_folder)
        if sounds_path.exists():
            web.mount(
                "/sounds",
                SoundStaticFiles(directory=sounds_path.absolute()),
                name="sounds",
            )
        else:
            logger.warning(f"Sounds folder {sounds_path.absolute()} does not exist")

        static_path = Path(settings.static_folder)
        if static_path.exists():
            web.mount(
                "/",
                StaticFiles(directory=static_path.absolute(), html=True),
                name="static",
            )
        else:
            logger.warning(f"Static folder {static_path.absolute()} does not exist")

    return web
