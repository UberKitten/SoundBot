"""Browser-clip management: ensure {safe}_clip.mp4 exists for sounds with video.

The clip is a browser/iOS/Discord-friendly faststart MP4 generated from the
sound's trimmed video (preferred) or its original (with the trim applied at
transcode time). Used by the admin video endpoint, the public signed
/clips/{name}.mp4 route, eager generation on sound mutations, and the
startup backfill.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from soundbot.core.state import state
from soundbot.models.sounds import Sound
from soundbot.services.ffmpeg import ffmpeg_service

logger = logging.getLogger(__name__)

# Bounded concurrency for the startup backfill.
BACKFILL_CONCURRENCY = 4
BACKFILL_LOG_EVERY = 25


class ClipError(Exception):
    """Raised when clip generation fails (source exists but ffmpeg errored)."""


@dataclass
class ClipResult:
    """Result of ensuring a clip exists."""

    path: Path
    # True if the clip was (re)generated this call; False if it was fresh.
    generated: bool = False
    # True if generation used the stream-copy (remux) fast path.
    remuxed: bool = False
    # ffmpeg wall time when generated.
    duration_seconds: Optional[float] = None


def clip_path_for(sound: Sound, sounds_dir: Path) -> Path:
    """Path where the browser clip for a sound lives."""
    return sounds_dir / sound.directory / f"{sound.directory}_clip.mp4"


def _needs_regenerate(output: Path, source: Path) -> bool:
    """True if output is missing or older than the source (covers re-trim)."""
    if not output.exists():
        return True
    try:
        return output.stat().st_mtime < source.stat().st_mtime
    except OSError:
        return True


async def resolve_clip_source(
    sound: Sound, sound_dir: Path
) -> Optional[tuple[Path, Optional[float], Optional[float]]]:
    """Pick the source video for the clip.

    Prefer the already-trimmed video; fall back to the original (with the
    trim applied during transcode) if it has a video stream.

    Returns (source_path, trim_start, trim_end) or None when the sound has
    no usable video.
    """
    if sound.files.trimmed_video:
        candidate = sound_dir / sound.files.trimmed_video
        if candidate.exists():
            return (candidate, None, None)

    # files.original may be a bare filename or an absolute path
    # (external clips); pathlib's / preserves an absolute RHS.
    original_path = sound_dir / sound.files.original
    if original_path.exists():
        probe = await ffmpeg_service.probe(original_path)
        if probe and probe.has_video:
            return (original_path, sound.timestamps.start, sound.timestamps.end)

    return None


async def ensure_clip(
    sound: Sound, sounds_dir: Path, force: bool = False
) -> Optional[ClipResult]:
    """Make sure the sound's browser clip exists and is newer than its source.

    Returns a ClipResult on success, or None when the sound has no video.
    Raises ClipError when the sound has video but ffmpeg failed.

    force=True always regenerates — needed when the trim window changed but
    the clip's source file (an untrimmed original) has an unchanged mtime.
    """
    sound_dir = sounds_dir / sound.directory

    source = await resolve_clip_source(sound, sound_dir)
    if source is None:
        return None
    source_path, trim_start, trim_end = source

    clip_path = clip_path_for(sound, sounds_dir)

    if not force and not _needs_regenerate(clip_path, source_path):
        return ClipResult(path=clip_path, generated=False)

    result = await ffmpeg_service.make_browser_video(
        source_path,
        clip_path,
        start=trim_start,
        end=trim_end,
    )
    if not result.success:
        raise ClipError(result.error or "Unknown ffmpeg error")

    return ClipResult(
        path=clip_path,
        generated=True,
        remuxed=bool(result.remuxed),
        duration_seconds=result.duration_seconds,
    )


async def backfill_clips(sounds_dir: Path) -> None:
    """One-time self-heal: ensure clips exist for every sound with video.

    Runs with bounded concurrency; cheap on subsequent boots (mtime checks
    only). Never raises — each failure is logged and counted.
    """
    items = list(state.sounds.items())
    total = len(items)
    logger.info(f"Clip backfill: checking {total} sounds...")

    semaphore = asyncio.Semaphore(BACKFILL_CONCURRENCY)
    counts = {"generated": 0, "remuxed": 0, "skipped": 0, "no_video": 0, "failed": 0}
    done = 0
    lock = asyncio.Lock()

    async def process(name: str, sound: Sound) -> None:
        nonlocal done
        async with semaphore:
            try:
                result = await ensure_clip(sound, sounds_dir)
                if result is None:
                    key = "no_video"
                elif not result.generated:
                    key = "skipped"
                elif result.remuxed:
                    key = "remuxed"
                else:
                    key = "generated"
            except ClipError as e:
                key = "failed"
                logger.warning(f"Clip backfill: '{name}' failed: {e}")
            except Exception as e:
                key = "failed"
                logger.warning(f"Clip backfill: '{name}' unexpected error: {e}")

        async with lock:
            counts[key] += 1
            done += 1
            if done % BACKFILL_LOG_EVERY == 0:
                logger.info(f"Clip backfill: {done}/{total} sounds processed")

    _ = await asyncio.gather(*(process(name, sound) for name, sound in items))

    summary = ", ".join(
        [
            f"{counts['generated']} transcoded",
            f"{counts['remuxed']} remuxed",
            f"{counts['skipped']} fresh",
            f"{counts['no_video']} without video",
            f"{counts['failed']} failed",
        ]
    )
    logger.info(f"Clip backfill complete: {summary} (of {total} sounds)")
