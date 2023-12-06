import asyncio
import logging
from datetime import datetime

from hypercorn.asyncio import serve
from hypercorn.config import Config

from app.core.settings import settings
from app.core.state import state
from app.discord.client import soundbot_client
from app.models.sounds import Sound, Stats
from app.web.logger import HypercornLogger
from app.web.routes.db import old_db
from app.web.web import get_web

logger = logging.getLogger(__name__)


async def init():
    # Migrate existing db.json
    db = await old_db()

    for sound in db.sounds:
        state.sounds[sound.name] = Sound(
            filename=sound.filename or f"{sound.name}.mp3",
            original_filename=f"{sound.name}-original.mp3",
            created=datetime.now(),
            modified=datetime.now(),
            discord=Stats(plays=sound.count),
        )

    for key, value in db.entrances.items():
        state.entrances[key] = value

    for key, value in db.exits.items():
        state.exits[key] = value

    state.save()


async def run():
    try:
        await init()
        await asyncio.gather(run_web(), run_bot())

    finally:
        state.save()


async def run_web():
    try:
        config = Config()
        config.bind = [":8080"]
        config.use_reloader = True
        config.logger_class = HypercornLogger

        await serve(get_web(), config)
    except Exception as exc:
        logger.error(f"Could not start web server: {str(exc)}")


async def run_bot():
    try:
        await soundbot_client.start(settings.token)
    except Exception as exc:
        logger.error(f"Could not start bot: {str(exc)}")
