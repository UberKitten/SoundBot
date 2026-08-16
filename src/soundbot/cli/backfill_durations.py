"""Backfill required playable durations from the exact stored OGG files."""

import argparse
import asyncio
import copy
import hashlib
import fcntl
import shutil
from collections.abc import Awaitable, Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import orjson

from soundbot.core.settings import settings
from soundbot.models.sounds import (
    allocate_sound_directory,
    validate_playable_duration,
)
from soundbot.models.state import StateDocument, atomic_write_json
from soundbot.services.ffmpeg import ProbeResult, ffmpeg_service

MediaProbe = Callable[[Path], Awaitable[Optional[ProbeResult]]]


@dataclass(frozen=True)
class DuplicateRepair:
    sound_name: str
    source_directory: Path
    target_directory: Path


@dataclass(frozen=True)
class BackfillResult:
    proposed_state: dict[str, Any]
    durations: dict[str, float]
    repairs: tuple[DuplicateRepair, ...] = ()


def plan_duplicate_repairs(
    raw_state: object, sounds_dir: Path
) -> tuple[dict[str, Any], tuple[DuplicateRepair, ...]]:
    """Plan deterministic unique storage for every duplicate playable path."""
    if not isinstance(raw_state, dict):
        raise ValueError("State root must be a JSON object")
    proposed: dict[str, Any] = copy.deepcopy(raw_state)
    sounds = proposed.get("sounds")
    if not isinstance(sounds, dict):
        raise ValueError("State sounds must be a JSON object")

    used_directories: set[str] = set()
    for sound in sounds.values():
        if isinstance(sound, dict):
            directory = sound.get("directory")
            if isinstance(directory, str):
                used_directories.add(directory)
    owners: dict[str, str] = {}
    repairs: list[DuplicateRepair] = []
    for name in sorted(sounds):
        sound = sounds[name]
        if not isinstance(sound, dict):
            raise ValueError(f"Sound '{name}' must be a JSON object")
        files = sound.get("files")
        if not isinstance(files, dict):
            raise ValueError(f"Sound '{name}' has invalid files metadata")
        directory = sound.get("directory")
        trimmed_audio = files.get("trimmed_audio")
        if not isinstance(directory, str) or not isinstance(trimmed_audio, str):
            raise ValueError(f"Sound '{name}' has invalid playable OGG metadata")
        playable_path = str(Path(directory) / trimmed_audio)
        if playable_path not in owners:
            owners[playable_path] = name
            continue

        target_name = allocate_sound_directory(name, used_directories)
        used_directories.add(target_name)
        source_directory = sounds_dir / directory
        target_directory = sounds_dir / target_name
        sound["directory"] = target_name
        repairs.append(
            DuplicateRepair(
                sound_name=name,
                source_directory=source_directory,
                target_directory=target_directory,
            )
        )
    return proposed, tuple(repairs)


def directory_manifest(directory: Path) -> dict[str, str]:
    """Hash every stored entry so collision repair can prove an exact copy."""
    manifest: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        relative = str(path.relative_to(directory))
        if path.is_symlink():
            manifest[f"link:{relative}"] = str(path.readlink())
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            manifest[f"file:{relative}"] = digest.hexdigest()
    return manifest


async def build_backfilled_state(
    raw_state: object,
    sounds_dir: Path,
    probe_media: MediaProbe = ffmpeg_service.probe,
    *,
    audio_path_overrides: Optional[Mapping[str, Path]] = None,
    repairs: tuple[DuplicateRepair, ...] = (),
) -> BackfillResult:
    """Probe all OGGs and return a fully validated proposal without writing."""
    if not isinstance(raw_state, dict):
        raise ValueError("State root must be a JSON object")
    proposed: dict[str, Any] = copy.deepcopy(raw_state)
    sounds = proposed.get("sounds")
    if not isinstance(sounds, dict):
        raise ValueError("State sounds must be a JSON object")

    durations: dict[str, float] = {}
    for name in sorted(sounds):
        sound = sounds[name]
        if not isinstance(sound, dict):
            raise ValueError(f"Sound '{name}' must be a JSON object")
        files = sound.get("files")
        if not isinstance(files, dict):
            raise ValueError(f"Sound '{name}' has invalid files metadata")
        directory = sound.get("directory")
        trimmed_audio = files.get("trimmed_audio")
        if not isinstance(directory, str) or not isinstance(trimmed_audio, str):
            raise ValueError(f"Sound '{name}' has invalid playable OGG metadata")

        audio_path = (
            audio_path_overrides[name]
            if audio_path_overrides and name in audio_path_overrides
            else sounds_dir / directory / trimmed_audio
        )
        if not audio_path.is_file():
            raise ValueError(f"Sound '{name}' playable OGG is missing: {audio_path}")
        probe = await probe_media(audio_path)
        if not probe or not probe.has_audio:
            raise ValueError(
                f"Sound '{name}' playable OGG has no audio stream: {audio_path}"
            )
        try:
            duration = validate_playable_duration(
                probe.duration if probe.duration is not None else 0.0
            )
        except ValueError as e:
            raise ValueError(
                f"Sound '{name}' playable OGG duration is invalid: {audio_path}: {e}"
            ) from e
        sound["duration"] = duration
        durations[name] = duration

    _ = StateDocument.model_validate(copy.deepcopy(proposed))
    return BackfillResult(
        proposed_state=proposed, durations=durations, repairs=repairs
    )


@contextmanager
def exclusive_state_lock(state_file: Path):
    """Hold the runtime's nonblocking state lock for an offline write transaction."""
    lock_path = state_file.with_suffix(".lock")
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            raise RuntimeError(
                f"SoundBot state lock is held; refusing duration backfill: {lock_path}"
            ) from e
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


async def backfill_durations(
    state_file: Path,
    sounds_dir: Path,
    *,
    write: bool,
    repair_duplicates: bool = False,
    probe_media: MediaProbe = ffmpeg_service.probe,
) -> BackfillResult:
    """Validate raw pre-strict state and optionally commit one offline transaction."""

    async def prepare(raw_state: object) -> BackfillResult:
        if not repair_duplicates:
            return await build_backfilled_state(raw_state, sounds_dir, probe_media)
        proposed, repairs = plan_duplicate_repairs(raw_state, sounds_dir)
        proposed_sounds = proposed["sounds"]
        overrides = {
            repair.sound_name: repair.source_directory
            / proposed_sounds[repair.sound_name]["files"]["trimmed_audio"]
            for repair in repairs
        }
        return await build_backfilled_state(
            proposed,
            sounds_dir,
            probe_media,
            audio_path_overrides=overrides,
            repairs=repairs,
        )

    if not write:
        return await prepare(orjson.loads(state_file.read_bytes()))

    with exclusive_state_lock(state_file):
        initial = await prepare(orjson.loads(state_file.read_bytes()))
        if not initial.repairs:
            atomic_write_json(state_file, initial.proposed_state)
            return initial

        created_directories: list[Path] = []
        try:
            for repair in initial.repairs:
                if repair.target_directory.exists():
                    raise ValueError(
                        f"Duplicate repair target already exists: {repair.target_directory}"
                    )
                source_manifest = directory_manifest(repair.source_directory)
                _ = shutil.copytree(
                    repair.source_directory,
                    repair.target_directory,
                    copy_function=shutil.copy2,
                    symlinks=True,
                )
                created_directories.append(repair.target_directory)
                if directory_manifest(repair.target_directory) != source_manifest:
                    raise ValueError(
                        f"Duplicate repair copy verification failed: {repair.sound_name}"
                    )

            verified = await build_backfilled_state(
                initial.proposed_state,
                sounds_dir,
                probe_media,
                repairs=initial.repairs,
            )
            atomic_write_json(state_file, verified.proposed_state)
            return verified
        except Exception:
            for directory in reversed(created_directories):
                shutil.rmtree(directory, ignore_errors=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure final playable OGG durations for every persisted sound"
    )
    _ = parser.add_argument(
        "--state-file", type=Path, default=Path(settings.state_file)
    )
    _ = parser.add_argument(
        "--sounds-folder", type=Path, default=Path(settings.sounds_folder)
    )
    _ = parser.add_argument(
        "--write",
        action="store_true",
        help="Atomically replace state after every OGG and the complete proposal validate",
    )
    _ = parser.add_argument(
        "--repair-duplicates",
        action="store_true",
        help="Copy duplicate playable storage to deterministic unique directories",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(
            backfill_durations(
                args.state_file,
                args.sounds_folder,
                write=args.write,
                repair_duplicates=args.repair_duplicates,
            )
        )
    except Exception as e:
        print(f"Duration backfill failed: {e}")
        return 1

    action = "Backfilled" if args.write else "Validated"
    print(f"{action} {len(result.durations)} playable OGG durations")
    if result.repairs:
        print(f"Repaired {len(result.repairs)} duplicate playable paths")
    return 0
