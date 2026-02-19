"""Discord webhook notifications for sound add/delete/rename events."""

import asyncio
import json
import logging
import os
import urllib.request
import urllib.error
import time
from datetime import datetime
from typing import Optional

from soundbot.core.settings import settings
from soundbot.core.state import state

logger = logging.getLogger(__name__)

# SoundBot brand color (matches the web UI accent)
SOUNDBOT_COLOR = 0x7C3AED  # Purple

WEBHOOK_ENV_VAR = "DISCORD_WEBHOOK_URL"


def _format_duration(seconds: Optional[float]) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None:
        return "unknown"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    if mins > 0:
        return f"{mins}:{secs:02d}"
    return f"{secs}s"


def _post_webhook(webhook_url: str, payload: dict, max_retries: int = 3) -> bool:
    """Post a payload to a Discord webhook with retry on rate limit."""
    data = json.dumps(payload).encode()

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "soundbot-webhook/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status in (200, 204):
                    return True
                logger.warning(f"Discord webhook returned {resp.status}")
                return False
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                try:
                    body = json.loads(e.read())
                    retry_after = body.get("retry_after", 5)
                except Exception:
                    retry_after = 5
                logger.info(f"Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after + 0.5)
                continue
            else:
                logger.error(f"Discord webhook error: {e.code}")
                return False
        except Exception as e:
            logger.error(f"Discord webhook failed: {e}")
            return False

    return False


def _build_add_embed(sound_name: str) -> Optional[dict]:
    """Build a Discord embed for a newly added sound."""
    sound = state.sounds.get(sound_name)
    if not sound:
        return None

    web_url = f"https://{settings.web_ui_url}"

    # Build description with metadata
    lines = []
    if sound.source_title:
        lines.append(f"**Source:** {sound.source_title}")
    if sound.source_url:
        lines.append(f"**URL:** {sound.source_url}")

    # Duration (trimmed)
    if sound.source_duration is not None:
        trim_start = sound.timestamps.start or 0.0
        trim_end = sound.timestamps.end or sound.source_duration
        trimmed = trim_end - trim_start
        if sound.timestamps.start or sound.timestamps.end:
            lines.append(
                f"**Duration:** {_format_duration(trimmed)} "
                f"(trimmed from {_format_duration(sound.source_duration)})"
            )
        else:
            lines.append(f"**Duration:** {_format_duration(trimmed)}")

    if sound.volume_adjust != 0:
        lines.append(f"**Volume:** {sound.volume_display}")

    if sound.added_by:
        lines.append(f"**Added by:** {sound.added_by}")

    embed = {
        "title": f"🔊 {sound_name}",
        "url": web_url,
        "description": "\n".join(lines) if lines else None,
        "color": SOUNDBOT_COLOR,
        "footer": {"text": "Sound added"},
        "timestamp": sound.created.isoformat(),
    }

    # Remove None values
    return {k: v for k, v in embed.items() if v is not None}


def _build_delete_embed(sound_name: str) -> dict:
    """Build a Discord embed for a deleted sound."""
    return {
        "title": f"🗑️ {sound_name}",
        "color": 0xEF4444,  # Red
        "footer": {"text": "Sound removed"},
        "timestamp": datetime.now().isoformat(),
    }


def _on_sound_update(sound_name: str, modified: datetime, action: str):
    """Callback for sound updates — posts to Discord webhook.

    Only posts for 'add' and 'delete' actions. Skips 'edit' to avoid spam.
    """
    # Skip edits (timestamps, volume changes, etc.)
    if action == "edit":
        return

    webhook_url = os.environ.get(WEBHOOK_ENV_VAR, "")
    if not webhook_url:
        return

    if action == "add":
        embed = _build_add_embed(sound_name)
        if not embed:
            return
    elif action == "delete":
        embed = _build_delete_embed(sound_name)
    else:
        logger.warning(f"Unknown sound update action: {action}")
        return

    payload = {
        "username": "SoundBot",
        "embeds": [embed],
    }

    # Post in background to avoid blocking the callback
    try:
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _post_webhook, webhook_url, payload)
    except RuntimeError:
        # No running loop, post synchronously
        _post_webhook(webhook_url, payload)


def register_webhook_notifications():
    """Register the webhook callback with the sound service."""
    from soundbot.services.sounds import sound_service

    webhook_url = os.environ.get(WEBHOOK_ENV_VAR, "")
    if webhook_url:
        sound_service.on_sound_update(_on_sound_update)
        logger.info("Discord webhook notifications enabled")
    else:
        logger.info(f"Discord webhook notifications disabled ({WEBHOOK_ENV_VAR} not set)")
