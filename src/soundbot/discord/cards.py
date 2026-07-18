"""Discord embeds ("cards") and clip posting for sound play commands.

Play paths post two separate messages: a bare signed clip URL (so Discord
renders the native inline video player — an explicit embed on the same
message would suppress the unfurl) followed by an info card embed.
"""

import logging
from datetime import datetime
from typing import Awaitable, Optional, Protocol

import discord

from soundbot.core.settings import settings
from soundbot.models.sounds import Sound
from soundbot.services.sounds import sound_service

logger = logging.getLogger(__name__)


class Sender(Protocol):
    """Keyword-call shape shared by Messageable.send and Webhook.send."""

    def __call__(
        self,
        content: str = ...,
        *,
        embed: discord.Embed = ...,
    ) -> Awaitable[object]: ...


def _format_duration(seconds: Optional[float]) -> str:
    """Format seconds into a human-readable duration string."""
    if seconds is None:
        return "unknown"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    if mins > 0:
        return f"{mins}:{secs:02d}"
    return f"{secs}s"


def _trimmed_duration_text(sound: Sound) -> Optional[str]:
    """Duration of the playable clip, noting the original when trimmed."""
    if sound.source_duration is None:
        return None
    trim_start = sound.timestamps.start or 0.0
    trim_end = sound.timestamps.end or sound.source_duration
    trimmed = trim_end - trim_start
    if sound.timestamps.start or sound.timestamps.end:
        return (
            f"{_format_duration(trimmed)} "
            f"(trimmed from {_format_duration(sound.source_duration)})"
        )
    return _format_duration(trimmed)


def build_play_card(name: str, sound: Sound) -> discord.Embed:
    """Lean info card posted alongside a play — Sound fields only, no file I/O."""
    embed = discord.Embed(title=f"🔊 {name}", color=discord.Color.blue())

    if sound.source_title:
        _ = embed.add_field(name="Title", value=sound.source_title, inline=False)
    if sound.source_url:
        _ = embed.add_field(name="Source", value=sound.source_url, inline=False)

    duration_text = _trimmed_duration_text(sound)
    if duration_text is not None:
        _ = embed.add_field(name="Duration", value=duration_text, inline=True)

    _ = embed.add_field(name="Plays", value=str(sound.discord.plays), inline=True)

    return embed


def build_info_card(
    name: str, sound: Sound, metadata: Optional[dict[str, object]]
) -> discord.Embed:
    """Rich card for /info — Sound fields plus yt-dlp metadata when available.

    Degrades to the classic /info layout when metadata is None (uploaded
    sounds, missing/corrupt metadata.json).
    """
    md: dict[str, object] = metadata or {}

    embed = discord.Embed(title=f"🔊 {name}", color=discord.Color.blue())
    if sound.source_url:
        embed.url = sound.source_url

    thumbnail = md.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("http"):
        _ = embed.set_thumbnail(url=thumbnail)

    if sound.source_title:
        _ = embed.add_field(name="Title", value=sound.source_title, inline=False)
    if sound.source_url:
        _ = embed.add_field(name="Source", value=sound.source_url, inline=False)

    # Channel/uploader, linked when a URL is available
    channel = md.get("channel") or md.get("uploader")
    if isinstance(channel, str) and channel:
        channel_url = md.get("channel_url") or md.get("uploader_url")
        if isinstance(channel_url, str) and channel_url.startswith("http"):
            channel = f"[{channel}]({channel_url})"
        _ = embed.add_field(name="Channel", value=channel, inline=True)

    upload_date = md.get("upload_date")
    if isinstance(upload_date, str):
        try:
            uploaded = datetime.strptime(upload_date, "%Y%m%d").strftime("%Y-%m-%d")
            _ = embed.add_field(name="Uploaded", value=uploaded, inline=True)
        except ValueError:
            pass

    view_count = md.get("view_count")
    if isinstance(view_count, int):
        _ = embed.add_field(name="Views", value=f"{view_count:,}", inline=True)

    if sound.source_duration:
        _ = embed.add_field(
            name="Original Duration",
            value=f"{sound.source_duration:.1f}s",
            inline=True,
        )

    ts = sound.timestamps
    if ts.start or ts.end:
        ts_str = f"{ts.start or 0:.1f}s - {ts.end or 'end'}s"
        _ = embed.add_field(name="Trim", value=ts_str, inline=True)

    _ = embed.add_field(name="Volume", value=sound.volume_display, inline=True)
    _ = embed.add_field(
        name="Discord Plays", value=str(sound.discord.plays), inline=True
    )

    if sound.aliases:
        _ = embed.add_field(
            name="Aliases", value=", ".join(sound.aliases), inline=False
        )

    footer = f"Created: {sound.created.strftime('%Y-%m-%d')}"
    domain = md.get("webpage_url_domain")
    if isinstance(domain, str) and domain:
        footer += f" • via {domain}"
    _ = embed.set_footer(text=footer)

    return embed


async def post_clip_and_card(
    send: Sender,
    name: str,
    sound: Sound,
    *,
    status_text: Optional[str] = None,
) -> None:
    """Post a sound's clip (own message, auto-embedded) then its info card.

    Clip posting is best-effort: no video, unset SESSION_SECRET, or a
    transcode failure all fall through to posting the card alone.
    """
    # Import here (like /clip does) to keep the web helpers out of the
    # discord module import graph at import time.
    from soundbot.services.clips import ClipError, ensure_clip
    from soundbot.web.clipsign import build_clip_share_url

    clip_available = False
    if not settings.session_secret:
        logger.debug("Skipping play clip: SESSION_SECRET is unset")
    else:
        try:
            result = await ensure_clip(sound, sound_service.sounds_dir)
            clip_available = result is not None
        except ClipError as e:
            logger.error(f"Play-clip generation failed for '{name}': {e}")

    if clip_available:
        # A direct .mp4 link as message content is what makes Discord render
        # the native inline video player — no embed on this message. Masked
        # markdown links (bot-only) still unfurl, so the long signed URL
        # hides behind a short label.
        _ = await send(f"[▶ {name}]({build_clip_share_url(name)})")

    card = build_play_card(name, sound)
    if status_text is not None:
        _ = await send(status_text, embed=card)
    else:
        _ = await send(embed=card)
