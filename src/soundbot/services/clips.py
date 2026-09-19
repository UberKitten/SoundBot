"""Browser-clip management: ensure {safe}_clip.mp4 exists for sounds with video.

The clip is a browser/iOS/Discord-friendly faststart MP4 generated from the
sound's trimmed video (preferred) or its original (with the trim applied at
transcode time). Used by the admin video endpoint, the public signed
/clips/{name}.mp4 route, eager generation on sound mutations, and the
startup backfill.
"""

import asyncio
import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from soundbot.core.state import state
from soundbot.models.sounds import Sound
from soundbot.services.ffmpeg import (
    ProbeResult,
    ffmpeg_service,
    is_browser_video_compatible,
)

logger = logging.getLogger(__name__)

# Bounded concurrency for the startup backfill.
BACKFILL_CONCURRENCY = 4
BACKFILL_LOG_EVERY = 25

_probe_memo: dict[Path, tuple[tuple[int, int, int], ProbeResult]] = {}


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


def _clip_identity(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _remember_probe(path: Path, probe: ProbeResult) -> None:
    try:
        _probe_memo[path] = (_clip_identity(path), probe)
    except OSError:
        _probe_memo.pop(path, None)


async def _memoized_probe(path: Path) -> Optional[ProbeResult]:
    """Probe once per stable path/inode/size/mtime identity."""
    try:
        identity = _clip_identity(path)
    except OSError:
        return None
    memo = _probe_memo.get(path)
    if memo is not None and memo[0] == identity:
        return memo[1]
    probe = await ffmpeg_service.probe(path)
    if probe is None:
        return None
    try:
        if _clip_identity(path) != identity:
            return None
    except OSError:
        return None
    _probe_memo[path] = (identity, probe)
    return probe


async def _is_compatible_cached_clip(
    output: Path, *, require_audio: bool
) -> bool:
    """Check a fresh cache entry against the browser-video contract."""
    probe = await _memoized_probe(output)
    return probe is not None and is_browser_video_compatible(
        probe, require_audio=require_audio
    )


def _new_clip_candidate(output: Path) -> Path:
    """Reserve a unique same-directory MP4 path for atomic installation."""
    descriptor, candidate = tempfile.mkstemp(
        dir=output.parent,
        prefix=f".{output.stem}-",
        suffix=".mp4",
    )
    os.close(descriptor)
    return Path(candidate)


async def _install_verified_clip(
    candidate: Path, output: Path, *, require_audio: bool
) -> None:
    """Validate a completed candidate before atomically replacing the cache."""
    probe = await ffmpeg_service.probe(candidate)
    if probe is None or not is_browser_video_compatible(
        probe, require_audio=require_audio
    ):
        raise ClipError("Generated clip does not satisfy browser-video compatibility")
    try:
        output_mode = stat.S_IMODE(output.stat().st_mode)
    except FileNotFoundError:
        output_mode = 0o644
    candidate.chmod(output_mode)
    os.replace(candidate, output)
    _remember_probe(output, probe)


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
        probe = await _memoized_probe(original_path)
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
    clip_path = clip_path_for(sound, sounds_dir)

    source = await resolve_clip_source(sound, sound_dir)
    if source is None:
        # No video stream anywhere → waveform video from the playable audio,
        # so every sound gets an inline player.
        audio_path = sound_dir / sound.files.trimmed_audio
        if not audio_path.exists():
            return None
        probe = await _memoized_probe(audio_path)
        if probe is None or probe.duration is None or probe.duration <= 0:
            return None

        if (
            not force
            and not _needs_regenerate(clip_path, audio_path)
            and await _is_compatible_cached_clip(clip_path, require_audio=True)
        ):
            return ClipResult(path=clip_path, generated=False)

        candidate = _new_clip_candidate(clip_path)
        try:
            result = await ffmpeg_service.make_waveform_video(
                audio_path, candidate, duration=probe.duration
            )
            if not result.success:
                raise ClipError(result.error or "Unknown ffmpeg error")
            await _install_verified_clip(
                candidate, clip_path, require_audio=True
            )
        finally:
            candidate.unlink(missing_ok=True)
        return ClipResult(
            path=clip_path,
            generated=True,
            duration_seconds=result.duration_seconds,
        )

    source_path, trim_start, trim_end = source

    source_probe = await _memoized_probe(source_path)
    if source_probe is None or not source_probe.has_video:
        raise ClipError(f"Failed to probe video source: {source_path}")

    if not force and not _needs_regenerate(clip_path, source_path):
        if await _is_compatible_cached_clip(
            clip_path, require_audio=source_probe.has_audio
        ):
            return ClipResult(path=clip_path, generated=False)

    candidate = _new_clip_candidate(clip_path)
    try:
        result = await ffmpeg_service.make_browser_video(
            source_path,
            candidate,
            start=trim_start,
            end=trim_end,
        )
        if not result.success:
            raise ClipError(result.error or "Unknown ffmpeg error")
        await _install_verified_clip(
            candidate, clip_path, require_audio=source_probe.has_audio
        )
    finally:
        candidate.unlink(missing_ok=True)

    return ClipResult(
        path=clip_path,
        generated=True,
        remuxed=bool(result.remuxed),
        duration_seconds=result.duration_seconds,
    )


async def backfill_clips(sounds_dir: Path) -> None:
    """One-time self-heal: ensure clips exist for every sound with video.

    Runs with bounded concurrency; cheap on subsequent boots (mtime checks plus
    bounded compatibility probes). Never raises — failures are logged and counted.
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
