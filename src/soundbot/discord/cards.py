"""Discord embeds ("cards") and clip posting for sound play commands.

Play paths post two separate messages: a bare signed clip URL (so Discord
renders the native inline video player — an explicit embed on the same
message would suppress the unfurl) followed by an info card embed.
"""

import logging
from datetime import datetime
from typing import Awaitable, Optional, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

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


def _trimmed_duration_text(sound: Sound) -> str:
    """Measured playable duration, with optional original-source provenance."""
    playable = _format_duration(sound.duration)
    if (
        sound.source_duration is not None
        and (sound.timestamps.start is not None or sound.timestamps.end is not None)
    ):
        return f"{playable} (trimmed from {_format_duration(sound.source_duration)})"
    return playable


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def timestamped_source_url(sound: Sound) -> Optional[str]:
    """The sound's source URL, deep-linked to the trim start when possible.

    Currently YouTube-only (t=<seconds>); other hosts return the URL as-is.
    """
    url = sound.source_url
    if not url:
        return None
    start = sound.timestamps.start
    if not start or start < 1:
        return url
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    if parts.netloc.lower() not in _YOUTUBE_HOSTS:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "t"]
    query.append(("t", f"{int(start)}s"))
    return urlunparse(parts._replace(query=urlencode(query)))


def build_play_card(name: str, sound: Sound) -> discord.Embed:
    """Lean info card posted alongside a play — Sound fields only, no file I/O."""
    embed = discord.Embed(title=f"🔊 {name}", color=discord.Color.blue())

    if sound.source_title:
        _ = embed.add_field(name="Title", value=sound.source_title, inline=False)
    if sound.source_url:
        _ = embed.add_field(name="Source", value=sound.source_url, inline=False)

    _ = embed.add_field(
        name="Duration", value=_trimmed_duration_text(sound), inline=True
    )

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
    source_url = timestamped_source_url(sound)
    if source_url:
        embed.url = source_url

    thumbnail = md.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("http"):
        _ = embed.set_thumbnail(url=thumbnail)

    if sound.source_title:
        _ = embed.add_field(name="Title", value=sound.source_title, inline=False)
    if source_url:
        _ = embed.add_field(name="Source", value=source_url, inline=False)

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
    if sound.discord_clips.plays:
        _ = embed.add_field(
            name="Clips", value=str(sound.discord_clips.plays), inline=True
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
    emoji: str = "🎵",
) -> None:
    """Post one compact line for a played sound:

        🎵 [name](clip url)   🔗 [Source Title](<source url>)

    The masked clip link still unfurls into the inline video player
    (bot-only behavior); the source link is wrapped in <> to suppress
    its unfurl. No embed — an embed would suppress the clip unfurl.

    Clip linking is best-effort: no video, unset SESSION_SECRET, or a
    transcode failure fall back to a plain bold name.
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
        line = f"{emoji} [{name}]({build_clip_share_url(name)})"
    else:
        line = f"{emoji} **{name}**"

    source_url = timestamped_source_url(sound)
    if source_url:
        source_label = sound.source_title or "source"
        # Wide spacing so the two links read as separate things at a glance
        # (Discord preserves regular spaces in message content).
        line += f"   🔗 [{source_label}](<{source_url}>)"

    _ = await send(line)
