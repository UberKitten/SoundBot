import copy
import fcntl
from pathlib import Path

import orjson
import pytest

from soundbot.cli import backfill_durations as migration
from soundbot.services.ffmpeg import ProbeResult


def raw_sound(directory: str, *, source_duration: float | None) -> dict[str, object]:
    return {
        "directory": directory,
        "files": {
            "original": f"{directory}_original.webm",
            "trimmed_audio": f"{directory}.ogg",
            "metadata": None,
        },
        "source_url": None,
        "source_title": "provenance",
        "source_duration": source_duration,
        "timestamps": {"start": 1.25, "end": 4.5},
        "volume_adjust": -1,
        "created": "2025-01-02T03:04:05",
        "modified": "2025-02-03T04:05:06",
        "added_by": "tester",
        "aliases": [f"{directory}-alias"],
        "discord": {"plays": 7, "last_played": None},
        "twitch": {"plays": 8, "last_played": None},
        "web": {"plays": 9, "last_played": None},
        "discord_clips": {"plays": 2, "last_played": None},
    }


def raw_state() -> dict[str, object]:
    return {
        "entrances": {"user": "alpha"},
        "exits": {"user": "beta"},
        "groups": {
            "pair": {
                "members": ["alpha", "beta"],
                "created": "2024-01-01T00:00:00",
                "random_mode": "separate",
                "discord": {"plays": 3, "last_played": None},
                "twitch": {"plays": 4, "last_played": None},
                "web": {"plays": 5, "last_played": None},
            }
        },
        "sounds": {
            "alpha": raw_sound("alpha", source_duration=None),
            "beta": raw_sound("beta", source_duration=60.0),
        },
    }


def create_audio_files(root: Path, names: tuple[str, ...] = ("alpha", "beta")) -> None:
    for name in names:
        directory = root / name
        directory.mkdir(parents=True)
        (directory / f"{name}.ogg").write_bytes(f"audio-{name}".encode())


async def test_complete_backfill_measures_all_oggs_and_preserves_every_other_value(
    tmp_path: Path,
) -> None:
    sounds_dir = tmp_path / "sounds"
    create_audio_files(sounds_dir)
    original = raw_state()
    probe_order: list[Path] = []

    async def probe(path: Path) -> ProbeResult:
        probe_order.append(path)
        return ProbeResult(
            duration={"alpha.ogg": 3.25, "beta.ogg": 7.5}[path.name],
            has_audio=True,
        )

    result = await migration.build_backfilled_state(original, sounds_dir, probe)

    assert probe_order == [
        sounds_dir / "alpha" / "alpha.ogg",
        sounds_dir / "beta" / "beta.ogg",
    ]
    assert result.durations == {"alpha": 3.25, "beta": 7.5}
    assert "duration" not in original["sounds"]["alpha"]  # type: ignore[index]
    without_durations = copy.deepcopy(result.proposed_state)
    for sound in without_durations["sounds"].values():
        sound.pop("duration")
    assert without_durations == original


async def test_write_occurs_once_only_after_every_ogg_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sounds_dir = tmp_path / "sounds"
    create_audio_files(sounds_dir)
    state_file = tmp_path / "state.json"
    state_file.write_bytes(orjson.dumps(raw_state()))
    events: list[str] = []

    async def probe(path: Path) -> ProbeResult:
        events.append(f"probe:{path.name}")
        return ProbeResult(
            duration=2.0 if path.name == "alpha.ogg" else 4.0,
            has_audio=True,
        )

    real_atomic_write = migration.atomic_write_json

    def record_write(path: Path, document: object) -> None:
        events.append("write")
        real_atomic_write(path, document)

    monkeypatch.setattr(migration, "atomic_write_json", record_write)

    result = await migration.backfill_durations(
        state_file, sounds_dir, write=True, probe_media=probe
    )

    assert result.durations == {"alpha": 2.0, "beta": 4.0}
    assert events == ["probe:alpha.ogg", "probe:beta.ogg", "write"]
    persisted = orjson.loads(state_file.read_bytes())
    assert persisted["sounds"]["alpha"]["duration"] == 2.0
    assert persisted["sounds"]["beta"]["duration"] == 4.0


@pytest.mark.parametrize("failure", ["missing", "unprobeable", "video-only"])
async def test_missing_or_unprobeable_ogg_fails_closed_with_zero_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    sounds_dir = tmp_path / "sounds"
    create_audio_files(
        sounds_dir,
        names=("alpha",) if failure == "missing" else ("alpha", "beta"),
    )
    state_file = tmp_path / "state.json"
    original_bytes = orjson.dumps(raw_state())
    state_file.write_bytes(original_bytes)
    writes = 0

    async def probe(path: Path) -> ProbeResult | None:
        if failure == "unprobeable" and path.name == "beta.ogg":
            return None
        return ProbeResult(
            duration=2.0,
            has_audio=not (failure == "video-only" and path.name == "beta.ogg"),
        )

    def unexpected_write(_path: Path, _document: object) -> None:
        nonlocal writes
        writes += 1

    monkeypatch.setattr(migration, "atomic_write_json", unexpected_write)

    with pytest.raises(ValueError, match="beta"):
        await migration.backfill_durations(
            state_file, sounds_dir, write=True, probe_media=probe
        )

    assert writes == 0
    assert state_file.read_bytes() == original_bytes


async def test_write_lock_conflict_fails_before_probe_or_write(tmp_path: Path) -> None:
    sounds_dir = tmp_path / "sounds"
    create_audio_files(sounds_dir)
    state_file = tmp_path / "state.json"
    original_bytes = orjson.dumps(raw_state())
    state_file.write_bytes(original_bytes)
    probe_count = 0
    lock_path = state_file.with_suffix(".lock")

    async def probe(_path: Path) -> ProbeResult:
        nonlocal probe_count
        probe_count += 1
        return ProbeResult(duration=2.0, has_audio=True)

    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(RuntimeError, match="state lock is held"):
                await migration.backfill_durations(
                    state_file, sounds_dir, write=True, probe_media=probe
                )
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)

    assert probe_count == 0
    assert state_file.read_bytes() == original_bytes


def duplicate_raw_state() -> dict[str, object]:
    document = raw_state()
    sounds = document["sounds"]
    assert isinstance(sounds, dict)
    beta = sounds["beta"]
    assert isinstance(beta, dict)
    beta["directory"] = "alpha"
    beta["files"] = {
        "original": "alpha_original.webm",
        "trimmed_audio": "alpha.ogg",
        "metadata": None,
    }
    return document


async def test_duplicate_playable_paths_fail_strict_preflight(tmp_path: Path) -> None:
    sounds_dir = tmp_path / "sounds"
    create_audio_files(sounds_dir, names=("alpha",))

    async def probe(_path: Path) -> ProbeResult:
        return ProbeResult(duration=2.5, has_audio=True)

    with pytest.raises(ValueError, match="share playable OGG path"):
        await migration.build_backfilled_state(
            duplicate_raw_state(), sounds_dir, probe
        )


async def test_duplicate_repair_copies_exact_storage_and_updates_only_one_record(
    tmp_path: Path,
) -> None:
    sounds_dir = tmp_path / "sounds"
    source_dir = sounds_dir / "alpha"
    source_dir.mkdir(parents=True)
    (source_dir / "alpha.ogg").write_bytes(b"exact playable bytes")
    (source_dir / "alpha_original.webm").write_bytes(b"exact original bytes")
    (source_dir / "metadata.json").write_bytes(b'{\"kept\":true}')
    before_manifest = migration.directory_manifest(source_dir)
    document = duplicate_raw_state()
    state_file = tmp_path / "state.json"
    state_file.write_bytes(orjson.dumps(document))

    async def probe(path: Path) -> ProbeResult:
        assert path.read_bytes() == b"exact playable bytes"
        return ProbeResult(duration=2.75, has_audio=True)

    result = await migration.backfill_durations(
        state_file,
        sounds_dir,
        write=True,
        repair_duplicates=True,
        probe_media=probe,
    )

    assert len(result.repairs) == 1
    repair = result.repairs[0]
    assert repair.sound_name == "beta"
    assert repair.source_directory == source_dir
    assert repair.target_directory != source_dir
    assert migration.directory_manifest(repair.target_directory) == before_manifest
    persisted = orjson.loads(state_file.read_bytes())
    assert persisted["sounds"]["alpha"]["directory"] == "alpha"
    assert persisted["sounds"]["beta"]["directory"] == repair.target_directory.name
    assert persisted["sounds"]["alpha"]["duration"] == 2.75
    assert persisted["sounds"]["beta"]["duration"] == 2.75
    preserved = copy.deepcopy(persisted)
    for sound in preserved["sounds"].values():
        sound.pop("duration")
    preserved["sounds"]["beta"]["directory"] = "alpha"
    assert preserved == document


async def test_duplicate_repair_failure_removes_copy_and_preserves_state(
    tmp_path: Path,
) -> None:
    sounds_dir = tmp_path / "sounds"
    source_dir = sounds_dir / "alpha"
    source_dir.mkdir(parents=True)
    (source_dir / "alpha.ogg").write_bytes(b"exact playable bytes")
    (source_dir / "alpha_original.webm").write_bytes(b"exact original bytes")
    state_file = tmp_path / "state.json"
    original_bytes = orjson.dumps(duplicate_raw_state())
    state_file.write_bytes(original_bytes)

    async def probe(path: Path) -> ProbeResult | None:
        if path.parent != source_dir:
            return None
        return ProbeResult(duration=2.75, has_audio=True)

    with pytest.raises(ValueError, match="has no audio stream"):
        await migration.backfill_durations(
            state_file,
            sounds_dir,
            write=True,
            repair_duplicates=True,
            probe_media=probe,
        )

    assert state_file.read_bytes() == original_bytes
    assert [path.name for path in sounds_dir.iterdir()] == ["alpha"]
