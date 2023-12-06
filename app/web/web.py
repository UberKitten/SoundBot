import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.core.settings import settings
from app.web.routes.router import router

logger = logging.getLogger(__name__)

web: FastAPI | None = None


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

        sounds_path = Path(settings.sounds_folder)
        if sounds_path.exists():
            web.mount(
                "/sounds", StaticFiles(directory=sounds_path.absolute()), name="sounds"
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
