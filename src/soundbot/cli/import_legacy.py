"""Import legacy sounds from parsed commands file."""

import json
import logging
from datetime import datetime
from pathlib import Path

from soundbot.core.state import state
from soundbot.services.sounds import sound_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def import_legacy_sounds(
    input_path: str,
    dry_run: bool = False,
    skip_existing: bool = True,
    sound_name: str | None = None,
) -> None:
    """
    Import legacy sounds from a parsed commands file.

    Args:
        input_path: Path to the parsed sounds JSON file.
        dry_run: If True, show what would be imported without actually importing.
        skip_existing: If True, skip sounds that already exist.
        sound_name: If provided, import only this specific sound.
    """
    input_file = Path(input_path)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    with input_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    sounds = data.get("sounds", [])
    logger.info(f"Found {len(sounds)} sounds to import")

    if sound_name:
        sounds = [s for s in sounds if s["name"].lower() == sound_name.lower()]
        if not sounds:
            logger.error(f"Sound '{sound_name}' not found in input file")
            return
        logger.info(f"Importing only: {sound_name}")

    # Load current state to check for existing sounds
    state.load()

    imported = 0
    skipped = 0
    failed = 0

    for sound in sounds:
        name = sound["name"]
        url = sound["url"]
        start = sound.get("start")
        end = sound.get("end")
        volume = sound.get("volume", 1.0)
        created_at_str = sound.get("created_at")
        added_by = sound.get("author")  # Original author from chat history

        # Parse the created_at timestamp from the export
        created_at = None
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                pass

        # Check if already exists
        existing = state.sounds.get(name.lower())
        if existing:
            if existing.is_legacy:
                # Legacy sound - we want to upgrade it
                logger.info(f"Upgrading legacy sound: {name}")
                overwrite = True
            elif skip_existing:
                logger.info(f"Skipping {name} (already exists as new format)")
                skipped += 1
                continue
            else:
                overwrite = True
        else:
            overwrite = False

        if dry_run:
            clip_info = ""
            if start or end:
                clip_info = f" clip={start or 0}-{end or 'end'}"
            vol_info = f" volume={volume}" if volume != 1.0 else ""
            upgrade_info = " [UPGRADE]" if existing and existing.is_legacy else ""
            print(f"Would import: {name} from {url}{clip_info}{vol_info}{upgrade_info}")
            continue

        logger.info(f"Importing {name} from {url}...")

        try:
            result = await sound_service.add_sound(
                name=name,
                url=url,
                start=start,
                end=end,
                volume=volume,
                overwrite=overwrite,
                created=created_at,
                added_by=added_by,
            )

            if result.success:
                logger.info(f"✓ {result.message}")
                imported += 1
            else:
                logger.error(f"✗ Failed to import {name}: {result.message}")
                failed += 1

        except Exception as e:
            logger.error(f"✗ Exception importing {name}: {e}")
            failed += 1

    if dry_run:
        print(f"\nDry run complete. {len(sounds)} sounds would be processed.")
    else:
        print(f"\nImport complete!")
        print(f"  Imported: {imported}")
        print(f"  Skipped:  {skipped}")
        print(f"  Failed:   {failed}")
