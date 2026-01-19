"""Regenerate audio files for all non-legacy sounds.

Use this when changing the global audio_file_volume setting in settings.
"""

import asyncio
import logging
from pathlib import Path

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sanitize_name

logger = logging.getLogger(__name__)


async def regenerate_audio_files(dry_run: bool = False, sound_name: str | None = None) -> None:
    """
    Regenerate all trimmed audio files for non-legacy sounds.

    This re-extracts and normalizes audio from original files using current settings,
    including the global audio_file_volume setting.

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
    processed = 0
    skipped = 0
    failed = 0

    print(f"🔊 Global audio_file_volume: {settings.audio_file_volume}")
    print(f"📁 Processing {total} sounds...\n")

    for name, sound in sounds_to_process:
        # Skip legacy sounds (no directory or files)
        if sound.is_legacy or not sound.directory or not sound.files:
            if sound_name:  # Only show skip message for specific sound requests
                print(f"⏭️  {name}: Legacy sound, cannot regenerate")
            skipped += 1
            continue

        # Get paths
        sound_dir = sounds_dir / sound.directory
        original_file = sound_dir / sound.files.original
        safe_name = sanitize_name(name)
        audio_file = sound_dir / f"{safe_name}.ogg"

        # Check if original exists
        if not original_file.exists():
            print(f"❌ {name}: Original file not found ({sound.files.original})")
            failed += 1
            continue

        effective_volume = sound.volume * settings.audio_file_volume
        volume_info = f"volume={sound.volume} × {settings.audio_file_volume} = {effective_volume:.2f}"

        if dry_run:
            print(f"🔄 {name}: Would regenerate ({volume_info})")
            processed += 1
            continue

        # Regenerate audio
        print(f"🔄 {name}: Regenerating... ({volume_info})")
        result = await ffmpeg_service.extract_and_normalize_audio(
            original_file,
            audio_file,
            start=sound.timestamps.start,
            end=sound.timestamps.end,
            volume=sound.volume,
        )

        if result.success:
            time_info = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""
            print(f"✅ {name}: Done{time_info}")
            processed += 1
        else:
            print(f"❌ {name}: Failed - {result.error}")
            failed += 1

    print(f"\n📊 Summary:")
    print(f"   ✅ Processed: {processed}")
    print(f"   ⏭️  Skipped (legacy): {skipped}")
    print(f"   ❌ Failed: {failed}")
