"""Regenerate audio files for all sounds.

Use this when changing the audio_target_lufs setting.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sanitize_name

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """Result of processing a single sound."""

    name: str
    success: bool
    message: str
    skipped: bool = False


async def _process_sound(
    name: str,
    sound,
    sounds_dir: Path,
    dry_run: bool,
    semaphore: asyncio.Semaphore,
) -> ProcessResult:
    """Process a single sound file."""
    async with semaphore:
        # Get paths
        sound_dir = sounds_dir / sound.directory
        original_file = sound_dir / sound.files.original
        safe_name = sanitize_name(name)
        audio_file = sound_dir / f"{safe_name}.ogg"

        # Check if original exists
        if not original_file.exists():
            return ProcessResult(
                name=name,
                success=False,
                message=f"Original file not found ({sound.files.original})",
            )

        volume_info = f"volume={sound.volume_adjust}" if sound.volume_adjust != 0 else ""
        info = f" ({volume_info})" if volume_info else ""

        if dry_run:
            return ProcessResult(
                name=name,
                success=True,
                message=f"Would regenerate{info}",
                skipped=True,
            )

        # Regenerate audio
        result = await ffmpeg_service.extract_and_normalize_audio(
            original_file,
            audio_file,
            start=sound.timestamps.start,
            end=sound.timestamps.end,
            volume_db=sound.volume_db,
        )

        if result.success:
            time_info = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""
            return ProcessResult(
                name=name,
                success=True,
                message=f"Done{time_info}{info}",
            )
        else:
            return ProcessResult(
                name=name,
                success=False,
                message=f"Failed - {result.error}",
            )


async def regenerate_audio_files(dry_run: bool = False, sound_name: str | None = None) -> None:
    """
    Regenerate all trimmed audio files in parallel.

    This re-extracts and normalizes audio from original files using current settings,
    including the audio_target_lufs setting.

    Args:
        dry_run: If True, only show what would be regenerated without doing it.
        sound_name: If provided, only regenerate this specific sound.
    """
    sounds_dir = Path(settings.sounds_folder)

    # Get sounds to process
    if sound_name:
        sound = state.sounds.get(sound_name.lower())
        if not sound:
            print(f"❌ Sound '{sound_name}' not found")
            return
        sounds_to_process = [(sound_name.lower(), sound)]
    else:
        sounds_to_process = list(state.sounds.items())

    total = len(sounds_to_process)

    # Use CPU count for parallelism (ffmpeg is CPU-bound)
    max_workers = os.cpu_count() or 4
    semaphore = asyncio.Semaphore(max_workers)

    print(f"🔊 Target LUFS: {settings.audio_target_lufs}")
    print(f"🧵 Using {max_workers} parallel workers")
    print(f"📁 Processing {total} sounds...\n")

    # Create tasks for all sounds
    tasks = [
        _process_sound(name, sound, sounds_dir, dry_run, semaphore)
        for name, sound in sounds_to_process
    ]

    # Process all sounds in parallel and collect results as they complete
    processed = 0
    failed = 0

    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result.success:
            icon = "🔄" if result.skipped else "✅"
            print(f"{icon} {result.name}: {result.message}")
            processed += 1
        else:
            print(f"❌ {result.name}: {result.message}")
            failed += 1

    print(f"\n📊 Summary:")
    print(f"   ✅ Processed: {processed}")
    print(f"   ❌ Failed: {failed}")
