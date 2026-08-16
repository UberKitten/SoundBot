import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from soundbot.core.settings import settings
from soundbot.cli import regenerate_audio
from soundbot.core.state import state
from soundbot.models.sounds import Sound, SoundFiles
from soundbot.services.ffmpeg import (
    FFmpegService,
    ProbeResult,
    ProcessResult,
    ffmpeg_service,
)
from soundbot.services.sounds import SoundService
import soundbot.services.ffmpeg as ffmpeg_module
from soundbot.services.ytdlp import DownloadResult, ytdlp_service
from soundbot.web.routes.sounds import get_sounds


@pytest.mark.parametrize("duration", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_sound_rejects_missing_or_invalid_playable_duration(
    duration: float | None,
) -> None:
    data: dict[str, object] = {
        "directory": "clip",
        "files": SoundFiles(original="source.ogg", trimmed_audio="clip.ogg"),
    }
    if duration is not None:
        data["duration"] = duration
    with pytest.raises(ValidationError):
        Sound.model_validate(data)


@pytest.mark.parametrize(
    ("measured", "has_audio"),
    [
        (None, False),
        (0.0, True),
        (-1.0, True),
        (float("nan"), True),
        (float("inf"), True),
        (3.0, False),
    ],
)
async def test_final_ogg_probe_failure_rejects_atomic_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    measured: float | None,
    has_audio: bool,
) -> None:
    class SuccessfulProcess:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b""

    async def create_process(*_args: str, **_kwargs: object) -> SuccessfulProcess:
        return SuccessfulProcess()

    service = FFmpegService()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(
        service,
        "probe",
        AsyncMock(
            return_value=None
            if measured is None
            else ProbeResult(duration=measured, has_audio=has_audio)
        ),
    )
    output = tmp_path / "clip.ogg"

    result = await service.extract_and_normalize_audio(tmp_path / "source", output)

    assert not result.success
    assert "Failed to verify playable OGG" in (result.error or "")
    assert not output.exists()
    assert list(tmp_path.glob(".*.ogg")) == []


@pytest.fixture
def duration_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SoundService, AsyncMock, AsyncMock]:
    monkeypatch.setattr(settings, "sounds_folder", str(tmp_path / "sounds"))
    source_probe = AsyncMock(
        return_value=ProbeResult(duration=99.0, has_audio=True, has_video=False)
    )
    normalize = AsyncMock(
        return_value=ProcessResult(success=True, media_duration_seconds=3.25)
    )
    monkeypatch.setattr(ffmpeg_service, "probe", source_probe)
    monkeypatch.setattr(ffmpeg_service, "extract_and_normalize_audio", normalize)
    service = SoundService()
    monkeypatch.setattr(service, "_generate_clip", AsyncMock())
    return service, source_probe, normalize


async def test_url_download_persists_measured_final_ogg_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, source_probe, _ = duration_service

    async def download(_url: str, sound_dir: Path, safe_name: str) -> DownloadResult:
        sound_dir.mkdir(parents=True)
        original = sound_dir / f"{safe_name}_original.webm"
        original.write_bytes(b"source")
        return DownloadResult(
            success=True,
            original_file=original,
            title="Original",
            duration=None,
        )

    monkeypatch.setattr(ytdlp_service, "download", download)

    result = await service.add_sound("URL", "https://example.test/audio", start=2, end=5)

    assert result.success
    assert state.sounds["url"].duration == 3.25
    assert state.sounds["url"].source_duration is None
    assert source_probe.await_count == 1


async def test_external_video_path_persists_measured_final_ogg_duration(
    tmp_path: Path,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, source_probe, _ = duration_service
    source = tmp_path / "external.mkv"
    source.write_bytes(b"source")

    result = await service.add_sound_from_video_path("Video", source, start=2, end=5)

    assert result.success
    assert state.sounds["video"].duration == 3.25
    assert state.sounds["video"].source_duration == 99.0
    assert source_probe.await_count == 1


async def test_direct_ogg_upload_persists_measured_final_ogg_duration(
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, source_probe, _ = duration_service

    result = await service.add_sound_from_file(
        "Upload", b"already ogg", "direct.ogg", start=2, end=5
    )

    assert result.success
    assert state.sounds["upload"].duration == 3.25
    assert state.sounds["upload"].source_duration == 99.0
    assert source_probe.await_count == 1


async def test_draft_import_persists_measured_final_ogg_duration(
    tmp_path: Path,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, source_probe, _ = duration_service
    source = tmp_path / "draft.mkv"
    source.write_bytes(b"source")

    result = await service.add_sound_from_local_file(
        "Draft", source, start=2, end=5
    )

    assert result.success
    assert state.sounds["draft"].duration == 3.25
    assert state.sounds["draft"].source_duration == 99.0
    assert source_probe.await_count == 1


@pytest.mark.parametrize("mutation", ["timestamps", "volume"])
async def test_existing_ogg_mutations_persist_the_new_measured_duration(
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
    mutation: str,
) -> None:
    service, _, normalize = duration_service
    sound_dir = Path(settings.sounds_folder) / "mutate"
    sound_dir.mkdir(parents=True)
    (sound_dir / "source.mkv").write_bytes(b"source")
    state.sounds["mutate"] = Sound(
        directory="mutate",
        files=SoundFiles(original="source.mkv", trimmed_audio="mutate.ogg"),
        duration=1.0,
        source_duration=99.0,
    )

    if mutation == "timestamps":
        result = await service.edit_timestamps("mutate", start=1.0, end=4.0)
    else:
        result = await service.set_volume("mutate", 2)

    assert result.success
    assert state.sounds["mutate"].duration == 3.25
    assert normalize.await_count == 1


async def test_redownload_persists_the_new_measured_duration(
    monkeypatch: pytest.MonkeyPatch,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, _, _ = duration_service
    sound_dir = Path(settings.sounds_folder) / "redownload"
    sound_dir.mkdir(parents=True)
    (sound_dir / "old.ogg").write_bytes(b"old")
    state.sounds["redownload"] = Sound(
        directory="redownload",
        files=SoundFiles(original="old.webm", trimmed_audio="old.ogg"),
        source_url="https://example.test/source",
        source_duration=10.0,
        duration=1.0,
    )

    async def download(_url: str, temp_dir: Path, safe_name: str) -> DownloadResult:
        original = temp_dir / f"{safe_name}_original.webm"
        original.write_bytes(b"new source")
        return DownloadResult(
            success=True,
            original_file=original,
            title="New source",
            duration=20.0,
        )

    monkeypatch.setattr(ytdlp_service, "download", download)

    result = await service.redownload_sound("redownload")

    assert result.success
    assert state.sounds["redownload"].duration == 3.25
    assert state.sounds["redownload"].source_duration == 20.0


async def test_bulk_regeneration_persists_each_verified_duration(
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, _, _ = duration_service
    sound_dir = Path(settings.sounds_folder) / "regen"
    sound_dir.mkdir(parents=True)
    (sound_dir / "source.webm").write_bytes(b"source")
    state.sounds["regen"] = Sound(
        directory="regen",
        files=SoundFiles(original="source.webm", trimmed_audio="regen.ogg"),
        duration=1.0,
    )

    success, failure, failed = await service.regenerate_all_audio()

    assert (success, failure, failed) == (1, 0, [])
    assert state.sounds["regen"].duration == 3.25


@pytest.mark.parametrize("mutation", ["timestamps", "volume"])
async def test_renamed_sound_mutations_rewrite_the_served_canonical_ogg(
    monkeypatch: pytest.MonkeyPatch,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
    mutation: str,
) -> None:
    service, _, _ = duration_service
    sound_dir = Path(settings.sounds_folder) / "original"
    sound_dir.mkdir(parents=True)
    (sound_dir / "source.mkv").write_bytes(b"source")
    canonical_audio = sound_dir / "original.ogg"
    canonical_audio.write_bytes(b"old playable audio")
    state.sounds["renamed"] = Sound(
        directory="original",
        files=SoundFiles(original="source.mkv", trimmed_audio="original.ogg"),
        duration=1.0,
        source_duration=10.0,
    )

    async def normalize(
        _input: Path, output: Path, **_kwargs: object
    ) -> ProcessResult:
        output.write_bytes(b"new playable audio")
        return ProcessResult(success=True, media_duration_seconds=4.5)

    monkeypatch.setattr(ffmpeg_service, "extract_and_normalize_audio", normalize)

    if mutation == "timestamps":
        result = await service.edit_timestamps("renamed", start=1.0, end=5.0)
    else:
        result = await service.set_volume("renamed", 1)

    assert result.success
    assert service.get_audio_path("renamed") == canonical_audio
    assert canonical_audio.read_bytes() == b"new playable audio"
    assert not (sound_dir / "renamed.ogg").exists()
    assert state.sounds["renamed"].duration == 4.5


async def test_cli_regeneration_rewrites_the_served_canonical_ogg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sound_dir = tmp_path / "original"
    sound_dir.mkdir()
    (sound_dir / "source.mkv").write_bytes(b"source")
    canonical_audio = sound_dir / "original.ogg"
    canonical_audio.write_bytes(b"old playable audio")
    sound = Sound(
        directory="original",
        files=SoundFiles(original="source.mkv", trimmed_audio="original.ogg"),
        duration=1.0,
    )

    async def normalize(
        _input: Path, output: Path, **_kwargs: object
    ) -> ProcessResult:
        output.write_bytes(b"new playable audio")
        return ProcessResult(success=True, media_duration_seconds=6.25)

    monkeypatch.setattr(ffmpeg_service, "extract_and_normalize_audio", normalize)

    result = await regenerate_audio._process_sound(
        "renamed", sound, tmp_path, False, asyncio.Semaphore(1)
    )

    assert result.success
    assert canonical_audio.read_bytes() == b"new playable audio"
    assert not (sound_dir / "renamed.ogg").exists()
    assert sound.duration == 6.25


async def test_colliding_sanitized_names_allocate_unique_playable_storage(
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, _, _ = duration_service
    first = "x" * 50 + "a"
    second = "x" * 50 + "b"

    first_result = await service.add_sound_from_file(first, b"one", "one.ogg")
    second_result = await service.add_sound_from_file(second, b"two", "two.ogg")

    assert first_result.success
    assert second_result.success
    first_sound = state.sounds[first]
    second_sound = state.sounds[second]
    assert first_sound.directory != second_sound.directory
    assert (
        first_sound.directory,
        first_sound.files.trimmed_audio,
    ) != (
        second_sound.directory,
        second_sound.files.trimmed_audio,
    )


async def test_output_setup_failure_leaves_no_partial_sound_or_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, _, _ = duration_service

    def fail_tempfile(**_kwargs: object) -> object:
        raise OSError("no temporary space")

    monkeypatch.setattr(ffmpeg_module.tempfile, "NamedTemporaryFile", fail_tempfile)
    real_ffmpeg = FFmpegService()
    monkeypatch.setattr(
        ffmpeg_service,
        "extract_and_normalize_audio",
        real_ffmpeg.extract_and_normalize_audio,
    )

    result = await service.add_sound_from_file("Setup Failure", b"media", "clip.ogg")

    assert not result.success
    assert "no temporary space" in result.message
    assert "setup failure" not in state.sounds
    assert not (tmp_path / "sounds" / "setup_failure").exists()


async def test_failed_final_measurement_leaves_no_new_sound_or_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    duration_service: tuple[SoundService, AsyncMock, AsyncMock],
) -> None:
    service, _, _ = duration_service
    monkeypatch.setattr(
        ffmpeg_service,
        "extract_and_normalize_audio",
        AsyncMock(
            return_value=ProcessResult(
                success=False,
                error="Failed to verify playable OGG duration",
            )
        ),
    )

    result = await service.add_sound_from_file("Broken", b"media", "broken.ogg")

    assert not result.success
    assert "duration" in result.message
    assert "broken" not in state.sounds
    assert not (tmp_path / "sounds" / "broken").exists()


async def test_api_serializes_required_playable_duration() -> None:
    state.sounds["clip"] = Sound(
        directory="clip",
        files=SoundFiles(original="source.ogg", trimmed_audio="clip.ogg"),
        duration=2.75,
        source_duration=None,
    )

    response = await get_sounds()

    assert response.sounds[0].duration == 2.75
    assert response.sounds[0].source_duration is None
