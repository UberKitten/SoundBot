"""Parse exported Discord history and extract legacy sound commands."""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class SoundCommand:
    """Represents a parsed sound command."""

    name: str
    url: str | None = None
    start: float | None = None
    end: float | None = None
    volume: float | None = None
    created_at: str | None = None
    author: str | None = None


@dataclass
class SoundHistory:
    """Tracks the full history of commands for a sound."""

    name: str
    add_command: SoundCommand | None = None
    modifications: list[dict] = field(default_factory=list)
    renamed_to: str | None = None
    removed: bool = False

    def get_final_state(self) -> dict | None:
        """Get the final state of the sound after all modifications."""
        if self.removed:
            return None
        if self.add_command is None:
            return None

        result = {
            "name": self.renamed_to or self.name,
            "original_name": self.name if self.renamed_to else None,
            "url": self.add_command.url,
            "start": self.add_command.start,
            "end": self.add_command.end,
            "volume": self.add_command.volume or 1.0,
            "created_at": self.add_command.created_at,
            "author": self.add_command.author,
        }

        # Apply modifications in order
        for mod in self.modifications:
            if mod["type"] == "clip":
                result["start"] = mod.get("start")
                result["end"] = mod.get("end")
            elif mod["type"] == "volume":
                result["volume"] = mod.get("volume", 1.0)

        return result


def parse_time(time_str: str) -> float | None:
    """
    Parse a time string into seconds.

    Supports formats:
    - Seconds: "23", "1.5"
    - MM:SS: "12:23"
    - HH:MM:SS: "1:23:45"
    - With milliseconds: "12:23.500"
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Try simple float first
    try:
        return float(time_str)
    except ValueError:
        pass

    # Try HH:MM:SS or MM:SS format
    parts = time_str.split(":")
    try:
        if len(parts) == 2:
            # MM:SS
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        elif len(parts) == 3:
            # HH:MM:SS
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        pass

    return None


# Command patterns
# !add <name> <url> [start] [end]
ADD_PATTERN = re.compile(
    r"^!add\s+(\S+)\s+(https?://\S+)(?:\s+(\S+))?(?:\s+(\S+))?",
    re.IGNORECASE,
)

# !modify <sound> clip <start> [end]
MODIFY_CLIP_PATTERN = re.compile(
    r"^!modify\s+(\S+)\s+clip\s+(\S+)(?:\s+(\S+))?",
    re.IGNORECASE,
)

# !modify <sound> volume <value>
MODIFY_VOLUME_PATTERN = re.compile(
    r"^!modify\s+(\S+)\s+volume\s+(\S+)",
    re.IGNORECASE,
)

# !rename <old> <new>
RENAME_PATTERN = re.compile(
    r"^!rename\s+(\S+)\s+(\S+)",
    re.IGNORECASE,
)

# !remove <sound>
REMOVE_PATTERN = re.compile(
    r"^!remove\s+(\S+)",
    re.IGNORECASE,
)

# Also check for !clip shorthand: !clip <sound> <start> [end]
CLIP_SHORTHAND_PATTERN = re.compile(
    r"^!clip\s+(\S+)\s+(\S+)(?:\s+(\S+))?",
    re.IGNORECASE,
)


def parse_legacy_commands(
    input_path: str,
    output_path: str,
) -> None:
    """
    Parse exported channel history and extract sound commands.

    Tracks the full history of each sound including adds, modifications,
    renames, and removes. Outputs the final state of each sound.

    Args:
        input_path: Path to the exported history JSON file.
        output_path: Path to save the parsed sounds JSON file.
    """
    input_file = Path(input_path)
    if not input_file.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    with input_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    logger.info(f"Parsing {len(messages)} messages from {data.get('channel_name', 'unknown')}")

    # Track sounds by name (lowercase)
    sounds: dict[str, SoundHistory] = {}

    # Track renames so we can follow the chain
    rename_map: dict[str, str] = {}  # old_name -> new_name

    def get_current_name(name: str) -> str:
        """Follow rename chain to get current name."""
        name_lower = name.lower()
        while name_lower in rename_map:
            name_lower = rename_map[name_lower]
        return name_lower

    for msg in messages:
        content = msg.get("content", "").strip()
        if not content.startswith("!"):
            continue

        author = msg.get("author", {}).get("name", "unknown")
        created_at = msg.get("created_at")

        # Parse !add command
        match = ADD_PATTERN.match(content)
        if match:
            name, url, start_str, end_str = match.groups()
            name_lower = name.lower()

            start = parse_time(start_str) if start_str else None
            end = parse_time(end_str) if end_str else None

            # Create new sound entry (overwrites if already exists)
            sounds[name_lower] = SoundHistory(
                name=name_lower,
                add_command=SoundCommand(
                    name=name_lower,
                    url=url,
                    start=start,
                    end=end,
                    created_at=created_at,
                    author=author,
                ),
            )
            logger.debug(f"Found !add {name_lower} {url}")
            continue

        # Parse !modify clip command
        match = MODIFY_CLIP_PATTERN.match(content)
        if match:
            name, start_str, end_str = match.groups()
            name_lower = get_current_name(name)

            if name_lower in sounds:
                start = parse_time(start_str)
                end = parse_time(end_str) if end_str else None
                sounds[name_lower].modifications.append({
                    "type": "clip",
                    "start": start,
                    "end": end,
                    "created_at": created_at,
                    "author": author,
                })
                logger.debug(f"Found !modify {name_lower} clip {start} {end}")
            continue

        # Parse !clip shorthand
        match = CLIP_SHORTHAND_PATTERN.match(content)
        if match:
            name, start_str, end_str = match.groups()
            name_lower = get_current_name(name)

            if name_lower in sounds:
                start = parse_time(start_str)
                end = parse_time(end_str) if end_str else None
                sounds[name_lower].modifications.append({
                    "type": "clip",
                    "start": start,
                    "end": end,
                    "created_at": created_at,
                    "author": author,
                })
                logger.debug(f"Found !clip {name_lower} {start} {end}")
            continue

        # Parse !modify volume command
        match = MODIFY_VOLUME_PATTERN.match(content)
        if match:
            name, volume_str = match.groups()
            name_lower = get_current_name(name)

            if name_lower in sounds:
                try:
                    volume = float(volume_str)
                    sounds[name_lower].modifications.append({
                        "type": "volume",
                        "volume": volume,
                        "created_at": created_at,
                        "author": author,
                    })
                    logger.debug(f"Found !modify {name_lower} volume {volume}")
                except ValueError:
                    pass
            continue

        # Parse !rename command
        match = RENAME_PATTERN.match(content)
        if match:
            old_name, new_name = match.groups()
            old_lower = get_current_name(old_name)
            new_lower = new_name.lower()

            if old_lower in sounds:
                sounds[old_lower].renamed_to = new_lower
                rename_map[old_lower] = new_lower
                # Move the sound to the new name
                sounds[new_lower] = sounds.pop(old_lower)
                sounds[new_lower].name = new_lower
                logger.debug(f"Found !rename {old_lower} -> {new_lower}")
            continue

        # Parse !remove command
        match = REMOVE_PATTERN.match(content)
        if match:
            name = match.group(1)
            name_lower = get_current_name(name)

            if name_lower in sounds:
                sounds[name_lower].removed = True
                logger.debug(f"Found !remove {name_lower}")
            continue

    # Build final output
    final_sounds = []
    removed_sounds = []

    for name, history in sounds.items():
        final_state = history.get_final_state()
        if final_state:
            final_sounds.append(final_state)
        elif history.removed:
            removed_sounds.append(name)

    # Sort by name
    final_sounds.sort(key=lambda s: s["name"])

    # Save output
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "total": len(final_sounds),
                "removed_count": len(removed_sounds),
                "sounds": final_sounds,
                "removed": removed_sounds,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    logger.info(f"Found {len(final_sounds)} active sounds, {len(removed_sounds)} removed")
    logger.info(f"Saved to {output_path}")

    # Print summary
    print(f"\n{'='*60}")
    print(f"Summary: {len(final_sounds)} sounds to import")
    print(f"{'='*60}")
    for sound in final_sounds[:10]:
        clip = ""
        if sound["start"] or sound["end"]:
            clip = f" [{sound['start'] or 0}s - {sound['end'] or 'end'}]"
        vol = f" (vol: {sound['volume']})" if sound["volume"] != 1.0 else ""
        print(f"  - {sound['name']}: {sound['url']}{clip}{vol}")

    if len(final_sounds) > 10:
        print(f"  ... and {len(final_sounds) - 10} more")
