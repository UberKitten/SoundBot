"""Offline management commands using the same services as Discord and the web UI.

Keep service imports out of parser setup: --help must not load settings or take
production's exclusive state lock. Actual commands deliberately take that lock.
"""

import argparse
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soundbot.models.sounds import Sound
    from soundbot.services.sounds import OperationResult


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    add = subparsers.add_parser("add", help="Download and add a full-length source URL")
    _ = add.add_argument("name")
    _ = add.add_argument("url")

    local = subparsers.add_parser(
        "import-file", help="Copy an already-downloaded full source into retained storage"
    )
    _ = local.add_argument("name")
    _ = local.add_argument("file", type=Path)
    _ = local.add_argument("--source-url")
    _ = local.add_argument("--source-title")

    trim = subparsers.add_parser(
        "trim", help="Set an existing sound's cut from its retained original; no download"
    )
    _ = trim.add_argument("name")
    _ = trim.add_argument("start", help="HH:MM:SS, MM:SS, or seconds")
    _ = trim.add_argument("end", help="HH:MM:SS, MM:SS, or seconds")

    info = subparsers.add_parser("info", help="Print one exact sound or alias as JSON")
    _ = info.add_argument("name")
    _ = subparsers.add_parser("list", help="Print sounds, source provenance and groups as JSON")

    delete = subparsers.add_parser(
        "delete", help="Permanently delete a sound and its retained files (not group members)"
    )
    _ = delete.add_argument("name")
    _ = delete.add_argument("--yes", action="store_true", help="Confirm permanent deletion")

    group = subparsers.add_parser("group", help="Manage sound groups")
    actions = group.add_subparsers(dest="action", required=True)
    for action in ("create", "delete"):
        child = actions.add_parser(action)
        _ = child.add_argument("name")
    for action in ("add", "remove"):
        child = actions.add_parser(action)
        _ = child.add_argument("name", help="Group name")
        _ = child.add_argument("sound", help="Exact sound name or alias")
    listing = actions.add_parser("list")
    _ = listing.add_argument("name", nargs="?", help="Omit to list all groups")


def _emit(data: dict[str, object], exit_code: int = 0) -> int:
    print(json.dumps(data, ensure_ascii=False))
    return exit_code


def _failure(message: str) -> int:
    return _emit({"success": False, "message": message}, 1)


def _result(result: "OperationResult", **data: object) -> int:
    return _emit(
        {
            "success": result.success,
            "message": result.message,
            "timings": result.timings,
            **data,
        },
        0 if result.success else 1,
    )


def _sound_info(name: str, sound: "Sound") -> dict[str, object]:
    from soundbot.services.sounds import sound_service

    directory = sound_service.sounds_dir / sound.directory
    paths = {
        "original": directory / sound.files.original,
        "audio": directory / sound.files.trimmed_audio,
        "clip": directory / f"{sound.directory}_clip.mp4",
    }
    if sound.files.trimmed_video:
        paths["video"] = directory / sound.files.trimmed_video
    return {
        "name": name,
        **sound.model_dump(mode="json"),
        "paths": {
            role: {"path": str(path.resolve()), "exists": path.is_file()}
            for role, path in paths.items()
        },
        "groups": [
            group_name
            for group_name, group in sound_service.list_groups().items()
            if name in group.members
        ],
    }


async def run(args: argparse.Namespace) -> int:
    # These imports enforce the existing exclusive state lock. Do not start a
    # second state-owning process or substitute a different lock for live data.
    from soundbot.cli.clip import parse_timestamp
    from soundbot.services.sounds import sound_service

    command = args.command
    if command == "list":
        return _emit(
            {
                "sounds": [
                    _sound_info(name, sound)
                    for name, sound in sorted(sound_service.list_sounds().items())
                ],
                "groups": {
                    name: group.model_dump(mode="json")
                    for name, group in sorted(sound_service.list_groups().items())
                },
            }
        )

    if command == "group" and args.action == "list" and args.name is None:
        return _emit(
            {
                "groups": {
                    name: group.model_dump(mode="json")
                    for name, group in sorted(sound_service.list_groups().items())
                }
            }
        )

    name = args.name.strip()
    if not name:
        return _failure("Name must not be empty")

    if command == "group":
        if args.action == "list":
            groups = sound_service.list_groups()
            if name.lower() not in groups:
                return _failure(f"Group '{name}' not found")
            return _emit({"name": name.lower(), **groups[name.lower()].model_dump(mode="json")})
        if args.action == "create":
            return _result(sound_service.create_group(name))
        if args.action == "delete":
            return _result(sound_service.delete_group(name))
        # Resolve before add_to_group, which otherwise creates a group even
        # when the requested sound is absent. Never act on a fuzzy match.
        resolved = sound_service.resolve_sound_name(args.sound.strip())
        if not resolved:
            return _failure(f"Sound '{args.sound}' not found")
        if args.action == "add":
            return _result(sound_service.add_to_group(name, resolved[0]))
        return _result(sound_service.remove_from_group(name, resolved[0]))

    if command == "add":
        result = await sound_service.add_sound(name, args.url)
    elif command == "import-file":
        result = await sound_service.add_sound_from_local_file(
            name,
            args.file.expanduser(),
            source_url=args.source_url,
            source_title=args.source_title,
        )
    else:
        resolved = sound_service.resolve_sound_name(name)
        if not resolved:
            return _failure(f"Sound '{name}' not found")
        canonical, sound = resolved
        if command == "info":
            return _emit(_sound_info(canonical, sound))
        if command == "delete":
            if not args.yes:
                return _failure("Deletion removes retained originals permanently; pass --yes")
            groups = [
                group_name
                for group_name, group in sound_service.list_groups().items()
                if canonical in group.members
            ]
            if groups:
                return _failure("Remove group memberships before deleting: " + ", ".join(groups))
            return _result(await sound_service.delete_sound(canonical))
        try:
            start = parse_timestamp(args.start)
            end = parse_timestamp(args.end)
        except ValueError:
            return _failure("Invalid timestamps; use HH:MM:SS, MM:SS, or seconds")
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            return _failure("Trim requires finite timestamps with 0 <= start < end")
        result = await sound_service.edit_timestamps(canonical, start=start, end=end)

    resolved = sound_service.resolve_sound_name(name)
    return _result(
        result,
        **({"sound": _sound_info(*resolved)} if result.success and resolved else {}),
    )
