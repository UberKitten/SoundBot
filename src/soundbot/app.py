import asyncio
import logging
from pathlib import Path

from hypercorn.asyncio import serve
from hypercorn.config import Config

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.discord.client import soundbot_client
from soundbot.services.clips import backfill_clips
from soundbot.services.ytdlp import ytdlp_service
from soundbot.web.logger import HypercornLogger
from soundbot.web.web import get_web

logger = logging.getLogger(__name__)

# How often to check for yt-dlp updates (in hours)
YTDLP_UPDATE_INTERVAL_HOURS = 24


async def init():
    """Initialize the application."""
    # Ensure sounds directory exists
    from pathlib import Path

    Path(settings.sounds_folder).mkdir(parents=True, exist_ok=True)

    # Load state
    logger.info("Loading state...")
    # State is loaded at import time, just log it
    logger.info(f"Loaded {len(state.sounds)} sounds")

    # Register Discord webhook notifications for sound add/delete
    from soundbot.services.webhook import register_webhook_notifications

    register_webhook_notifications()


async def backfill_clips_task():
    """One-time (per boot) self-heal: ensure browser clips exist for all
    sounds with video. Cheap once clips exist (mtime checks only).

    Guarded so it can never take the app down.
    """
    try:
        await backfill_clips(Path(settings.sounds_folder))
    except Exception as e:
        logger.error(f"Clip backfill task failed: {e}")


async def update_ytdlp_periodically():
    """Background task to update yt-dlp periodically."""
    while True:
        try:
            logger.info("Checking for yt-dlp updates...")
            _ = await ytdlp_service.update_ytdlp()
        except Exception as e:
            logger.error(f"Error updating yt-dlp: {e}")

        # Wait for next update check
        await asyncio.sleep(YTDLP_UPDATE_INTERVAL_HOURS * 3600)


async def run():
    """Run the application."""
    try:
        await init()

        # Start all services concurrently. The clip backfill runs as a
        # background task alongside — it never blocks web/bot startup.
        _ = await asyncio.gather(
            run_web(),
            run_bot(),
            update_ytdlp_periodically(),
            backfill_clips_task(),
        )
    finally:
        _ = state.save()


async def run_web():
    """Run the web server."""
    try:
        config = Config()
        config.bind = [":8080"]
        config.use_reloader = False  # Don't use reloader with asyncio.gather
        config.logger_class = HypercornLogger

        logger.info("Starting web server on :8080")
        await serve(get_web(), config)  # pyright: ignore[reportArgumentType]
    except Exception as exc:
        logger.error(f"Could not start web server: {str(exc)}")


async def run_bot():
    """Run the Discord bot."""
    try:
        logger.info("Starting Discord bot...")
        await soundbot_client.start(settings.token)
    except Exception as exc:
        logger.error(f"Could not start bot: {str(exc)}")
