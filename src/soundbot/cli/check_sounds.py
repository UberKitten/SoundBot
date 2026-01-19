"""Check for and optionally remove broken sound entries."""

import logging
from pathlib import Path

from soundbot.core.settings import settings
from soundbot.core.state import state

logger = logging.getLogger(__name__)


def check_sounds(remove_broken: bool = False) -> None:
    """
    Check all sounds for missing audio files.

    Args:
        remove_broken: If True, remove entries with missing files from state.
    """
    sounds_dir = Path(settings.sounds_folder)

    state.load()

    missing = []
    valid = []

    for name, sound in state.sounds.items():
        # Check legacy sounds
        if sound.is_legacy:
            if sound.filename:
                path = sounds_dir / sound.filename
                if path.exists():
                    valid.append((name, "legacy", path))
                else:
                    missing.append((name, "legacy", sound.filename, sound.source_url or sound.source))
            else:
                missing.append((name, "legacy", "no filename", None))
        else:
            # New format
            if sound.directory and sound.files:
                path = sounds_dir / sound.directory / sound.files.trimmed_audio
                if path.exists():
                    valid.append((name, "new", path))
                else:
                    missing.append((name, "new", sound.files.trimmed_audio, sound.source_url))
            else:
                missing.append((name, "new", "no files", sound.source_url))

    print(f"📊 Sound Status:")
    print(f"   ✅ Valid: {len(valid)}")
    print(f"   ❌ Missing files: {len(missing)}")
    print()

    if missing:
        print("Missing sounds:")
        for name, fmt, filename, url in missing:
            url_info = f" - {url}" if url else ""
            print(f"   ❌ {name} ({fmt}): {filename}{url_info}")

        if remove_broken:
            print()
            print("Removing broken entries...")
            for name, _, _, _ in missing:
                del state.sounds[name]
                print(f"   🗑️  Removed: {name}")
            state.save()
            print(f"\n✅ Removed {len(missing)} broken entries from state.")
        else:
            print()
            print("Run with --remove to delete broken entries from state.")
            print("Note: This won't delete any files, just removes the state entries.")
