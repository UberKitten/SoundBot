import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.core.settings import settings
from app.web.api.api import router as api

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

        web.include_router(api, prefix="/api")

        web.mount("/sounds", StaticFiles(directory=settings.sounds_root))

        static_path = Path(settings.static_ui_folder)
        if static_path.exists():
            web.mount(
                "/",
                StaticFiles(directory=static_path.absolute(), html=True),
                name="static",
            )
        else:
            logger.warn(f"Static files path {static_path.absolute()} does not exist")

    return web
