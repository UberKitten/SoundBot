"""Migrate legacy sounds to the new directory format."""

import logging
import shutil
from pathlib import Path

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ffmpeg_service
from soundbot.services.sounds import sanitize_name
from soundbot.models.sounds import Sound, SoundFiles, Timestamps

logger = logging.getLogger(__name__)


async def migrate_legacy_sounds(
    dry_run: bool = False,
    sound_name: str | None = None,
) -> None:
    """
    Migrate legacy sounds to the new directory format.

    This copies the legacy audio file to a new directory structure and
    processes it with the current normalization settings.

    Args:
        dry_run: If True, only show what would be migrated without doing it.
        sound_name: If provided, only migrate this specific sound.
    """
    sounds_dir = Path(settings.sounds_folder)

    state.load()

    # Get legacy sounds to process
    if sound_name:
        sound = state.sounds.get(sound_name.lower())
        if not sound:
            print(f"❌ Sound '{sound_name}' not found")
            return
        if not sound.is_legacy:
            print(f"❌ Sound '{sound_name}' is not a legacy sound")
            return
        sounds_to_process = [(sound_name.lower(), sound)]
    else:
        sounds_to_process = [
            (name, s) for name, s in state.sounds.items() if s.is_legacy
        ]

    total = len(sounds_to_process)
    if total == 0:
        print("✅ No legacy sounds to migrate!")
        return

    print(f"📁 Found {total} legacy sounds to migrate...\n")

    migrated = 0
    skipped = 0
    failed = 0

    for name, sound in sounds_to_process:
        if not sound.filename:
            print(f"❌ {name}: No filename set")
            failed += 1
            continue

        # Check if legacy file exists
        legacy_file = sounds_dir / sound.filename
        if not legacy_file.exists():
            print(f"❌ {name}: Legacy file not found ({sound.filename})")
            failed += 1
            continue

        safe_name = sanitize_name(name)
        new_dir = sounds_dir / safe_name

        if dry_run:
            print(f"🔄 {name}: Would migrate {sound.filename} -> {safe_name}/")
            migrated += 1
            continue

        # Check if new directory already exists
        if new_dir.exists():
            print(f"⚠️  {name}: Directory already exists, skipping")
            skipped += 1
            continue

        print(f"🔄 {name}: Migrating...")

        try:
            # Create new directory
            new_dir.mkdir(parents=True, exist_ok=True)

            # Copy original file
            ext = legacy_file.suffix.lower()
            original_file = new_dir / f"{safe_name}_original{ext}"
            shutil.copy2(legacy_file, original_file)

            # Probe the file
            probe = await ffmpeg_service.probe(original_file)
            if not probe or not probe.has_audio:
                print(f"❌ {name}: File has no audio")
                shutil.rmtree(new_dir)
                failed += 1
                continue

            # Process audio for Discord
            audio_file = new_dir / f"{safe_name}.ogg"
            result = await ffmpeg_service.extract_and_normalize_audio(
                original_file,
                audio_file,
                start=sound.timestamps.start,
                end=sound.timestamps.end,
                volume=sound.volume,
            )

            if not result.success:
                print(f"❌ {name}: Failed to process audio - {result.error}")
                shutil.rmtree(new_dir)
                failed += 1
                continue

            # Update sound entry to new format
            sound.directory = safe_name
            sound.files = SoundFiles(
                original=original_file.name,
                trimmed_video=None,
                trimmed_audio=audio_file.name,
                metadata=None,
                subtitles=None,
            )
            # Keep source_url if it was set via the legacy 'source' field
            if sound.source and not sound.source_url:
                sound.source_url = sound.source
            # Keep the old filename/original_filename for reference but the
            # is_legacy property will now return False since directory is set

            state.save()

            # Optionally delete old legacy files after successful migration
            # For safety, we'll keep them for now
            # legacy_file.unlink()
            # if sound.original_filename:
            #     orig_legacy = sounds_dir / sound.original_filename
            #     if orig_legacy.exists():
            #         orig_legacy.unlink()

            time_info = f" ({result.duration_seconds:.1f}s)" if result.duration_seconds else ""
            print(f"✅ {name}: Migrated{time_info}")
            migrated += 1

        except Exception as e:
            print(f"❌ {name}: Error - {e}")
            if new_dir.exists():
                shutil.rmtree(new_dir)
            failed += 1

    print(f"\n📊 Summary:")
    print(f"   ✅ Migrated: {migrated}")
    print(f"   ⏭️  Skipped: {skipped}")
    print(f"   ❌ Failed: {failed}")

    if not dry_run and migrated > 0:
        print(f"\n💡 Legacy files were preserved. After verifying migration, you can")
        print(f"   manually delete the old .mp3 files from {sounds_dir}/")
