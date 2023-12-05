import asyncio
import logging

from hypercorn.asyncio import serve
from hypercorn.config import Config

from app.core.settings import settings
from app.core.state import state
from app.discord.client import soundbot_client
from app.web.logger import HypercornLogger
from app.web.web import get_web

logger = logging.getLogger(__name__)


async def init():
    ...


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
