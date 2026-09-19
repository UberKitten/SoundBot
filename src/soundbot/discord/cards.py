"""Discord embeds ("cards") and clip posting for sound play commands.

Video posts put a bounded, directory-addressed signed URL first so Discord can
render its native player, then add name/source text only within content limits.
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

DISCORD_EMBED_TITLE_MAX_UNITS = 256
DISCORD_EMBED_DESCRIPTION_MAX_UNITS = 4096
DISCORD_EMBED_FIELD_MAX_UNITS = 1024
DISCORD_MESSAGE_CONTENT_MAX_UNITS = 2000


def discord_utf16_units(value: str) -> int:
    """Conservatively count Discord text using UTF-16 code units."""
    return sum(2 if ord(character) > 0xFFFF else 1 for character in value)


def truncate_discord_text(value: str, max_units: int) -> str:
    """Truncate without splitting a Unicode code point, reserving an ellipsis."""
    if max_units <= 0:
        return ""
    if discord_utf16_units(value) <= max_units:
        return value

    ellipsis = "…"
    remaining = max_units - discord_utf16_units(ellipsis)
    if remaining < 0:
        return ""

    kept: list[str] = []
    used = 0
    for character in value:
        units = 2 if ord(character) > 0xFFFF else 1
        if used + units > remaining:
            break
        kept.append(character)
        used += units
    return "".join(kept) + ellipsis


def fit_discord_content(value: str) -> str:
    """Suppress mentions and fit ordinary content within Discord's limit."""
    return truncate_discord_text(
        discord.utils.escape_mentions(value), DISCORD_MESSAGE_CONTENT_MAX_UNITS
    )


def bounded_embed_title(prefix: str, value: str, suffix: str = "") -> str:
    """Keep fixed title context while bounding a potentially long value."""
    fixed_units = discord_utf16_units(prefix) + discord_utf16_units(suffix)
    if fixed_units >= DISCORD_EMBED_TITLE_MAX_UNITS:
        return truncate_discord_text(
            prefix + suffix, DISCORD_EMBED_TITLE_MAX_UNITS
        )
    return (
        prefix
        + truncate_discord_text(
            value, DISCORD_EMBED_TITLE_MAX_UNITS - fixed_units
        )
        + suffix
    )


def escape_discord_text(value: str) -> str:
    """Render user-controlled names literally and without mentions."""
    return discord.utils.escape_markdown(
        discord.utils.escape_mentions(value), ignore_links=False
    )


def paginate_discord_lines(
    values: list[str],
    *,
    limit: int = DISCORD_EMBED_DESCRIPTION_MAX_UNITS,
) -> list[str]:
    """Escape and pack complete display names into bounded description pages."""
    pages: list[str] = []
    lines: list[str] = []
    used = 0

    for value in values:
        line = truncate_discord_text(f"• {escape_discord_text(value)}", limit)
        separator_units = 1 if lines else 0
        line_units = discord_utf16_units(line)
        if lines and used + separator_units + line_units > limit:
            pages.append("\n".join(lines))
            lines = []
            used = 0
            separator_units = 0
        lines.append(line)
        used += separator_units + line_units

    if lines:
        pages.append("\n".join(lines))
    return pages

def _embed_name(name: str) -> tuple[str, Optional[str]]:
    display_name = escape_discord_text(name)
    full_title = f"🔊 {display_name}"
    title = bounded_embed_title("🔊 ", display_name)
    if title == full_title:
        return title, None
    description = truncate_discord_text(
        f"Full name: {display_name}",
        DISCORD_EMBED_DESCRIPTION_MAX_UNITS,
    )
    return title, description


def _field_value(value: object) -> str:
    return truncate_discord_text(str(value), DISCORD_EMBED_FIELD_MAX_UNITS)


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
    title, description = _embed_name(name)
    embed = discord.Embed(
        title=title, description=description, color=discord.Color.blue()
    )

    if sound.source_title:
        _ = embed.add_field(
            name="Title", value=_field_value(sound.source_title), inline=False
        )
    if sound.source_url:
        _ = embed.add_field(
            name="Source", value=_field_value(sound.source_url), inline=False
        )

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

    title, description = _embed_name(name)
    embed = discord.Embed(
        title=title, description=description, color=discord.Color.blue()
    )
    source_url = timestamped_source_url(sound)
    if source_url:
        embed.url = source_url

    thumbnail = md.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("http"):
        _ = embed.set_thumbnail(url=thumbnail)

    if sound.source_title:
        _ = embed.add_field(
            name="Title", value=_field_value(sound.source_title), inline=False
        )
    if source_url:
        _ = embed.add_field(
            name="Source", value=_field_value(source_url), inline=False
        )

    # Channel/uploader, linked when a URL is available
    channel = md.get("channel") or md.get("uploader")
    if isinstance(channel, str) and channel:
        channel_url = md.get("channel_url") or md.get("uploader_url")
        if isinstance(channel_url, str) and channel_url.startswith("http"):
            channel = f"[{channel}]({channel_url})"
        _ = embed.add_field(
            name="Channel", value=_field_value(channel), inline=True
        )

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
            name="Aliases",
            value=_field_value(", ".join(sound.aliases)),
            inline=False,
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
    """Post a playable clip URL followed by bounded identifying text.

    Clip linking is best-effort: no video, unset SESSION_SECRET, or a transcode
    failure falls back to a plain name. The direct URL stays first and is never
    truncated; optional source text is omitted if it cannot fit.
    """
    # Import here (like /clip does) to keep the web helpers out of the
    # discord module import graph at import time.
    from soundbot.services.clips import ClipError, ensure_clip
    from soundbot.web.clipsign import build_clip_directory_share_url

    clip_available = False
    if not settings.session_secret:
        logger.debug("Skipping play clip: SESSION_SECRET is unset")
    else:
        try:
            result = await ensure_clip(sound, sound_service.sounds_dir)
            clip_available = result is not None
        except ClipError as e:
            logger.error(f"Play-clip generation failed for '{name}': {e}")

    escaped_name = escape_discord_text(name)
    if clip_available:
        clip_url = build_clip_directory_share_url(sound.directory)
        if discord_utf16_units(clip_url) <= DISCORD_MESSAGE_CONTENT_MAX_UNITS:
            remaining = (
                DISCORD_MESSAGE_CONTENT_MAX_UNITS
                - discord_utf16_units(clip_url)
                - 1
            )
            name_line = truncate_discord_text(
                f"{emoji} {escaped_name}", remaining
            )
            line = clip_url + (f"\n{name_line}" if name_line else "")
        else:
            logger.error("Generated clip URL exceeds Discord's content limit")
            line = fit_discord_content(f"{emoji} {escaped_name}")
    else:
        line = fit_discord_content(f"{emoji} {escaped_name}")

    source_url = timestamped_source_url(sound)
    if (
        source_url
        and source_url.startswith(("http://", "https://"))
        and not any(character.isspace() or character in "<>" for character in source_url)
    ):
        source_link = f"<{source_url}>"
        separator = "\n"
        fixed_source = f"🔗 source: {source_link}"
        remaining = (
            DISCORD_MESSAGE_CONTENT_MAX_UNITS
            - discord_utf16_units(line)
            - discord_utf16_units(separator)
        )
        if discord_utf16_units(fixed_source) <= remaining:
            source_label = escape_discord_text(sound.source_title or "source")
            label_budget = (
                remaining
                - discord_utf16_units("🔗 : ")
                - discord_utf16_units(source_link)
            )
            label = truncate_discord_text(source_label, label_budget)
            line += f"{separator}🔗 {label}: {source_link}"

    _ = await send(line)
