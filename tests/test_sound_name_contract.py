from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ProbeResult, ProcessResult, ffmpeg_service
from soundbot.models.sounds import (
    SOUND_NAME_MAX_CODE_POINTS,
    allocate_sound_directory,
)
from soundbot.services.sounds import SoundService
from soundbot.web.routes.sounds import get_sound_audio, router as sounds_router
from tests.conftest import make_sound


async def test_every_creation_path_rejects_501_code_points_before_io() -> None:
    service = SoundService()
    too_long = "😀" * (SOUND_NAME_MAX_CODE_POINTS + 1)

    results = [
        await service.add_sound(too_long, "https://example.test/source"),
        await service.add_sound_from_video_path(too_long, Path("missing-video.mkv")),
        await service.add_sound_from_file(too_long, b"media", "source.mkv"),
        await service.add_sound_from_local_file(too_long, Path("missing-local.mkv")),
    ]

    assert all(not result.success for result in results)
    assert all("500 Unicode code points" in result.message for result in results)
    assert state.sounds == {}


async def test_creation_accepts_500_supplementary_code_points(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sounds_dir = tmp_path / "sounds"
    source = tmp_path / "source.mkv"
    _ = source.write_bytes(b"source media")
    name = "😀" * SOUND_NAME_MAX_CODE_POINTS

    monkeypatch.setattr(settings, "sounds_folder", str(sounds_dir))
    monkeypatch.setattr(
        ffmpeg_service,
        "probe",
        AsyncMock(return_value=ProbeResult(duration=2.0, has_audio=True, has_video=False)),
    )
    monkeypatch.setattr(
        ffmpeg_service,
        "extract_and_normalize_audio",
        AsyncMock(return_value=ProcessResult(success=True, media_duration_seconds=2.0)),
    )
    service = SoundService()
    monkeypatch.setattr(service, "_generate_clip", AsyncMock())

    result = await service.add_sound_from_local_file(name, source)

    assert result.success
    assert name in state.sounds
    assert len(state.sounds[name].directory) == 50


def test_storage_slug_does_not_impose_an_alphabet_on_display_names() -> None:
    name = '<>:"/\\\\|?*'
    directory = allocate_sound_directory(name, [])

    assert directory.startswith("sound-")
    assert len(directory) <= 50


async def test_rename_accepts_500_and_rejects_501_without_rewriting_storage() -> None:
    service = SoundService()
    sound = make_sound(directory="stable-short-id")
    state.sounds["old"] = sound
    accepted = "𐐷" * SOUND_NAME_MAX_CODE_POINTS

    result = await service.rename_sound("old", accepted)

    assert result.success
    assert state.sounds[accepted] is sound
    assert sound.directory == "stable-short-id"

    rejected = accepted + "𐐷"
    rejected_result = await service.rename_sound(accepted, rejected)

    assert not rejected_result.success
    assert "500 Unicode code points" in rejected_result.message
    assert state.sounds[accepted] is sound
    assert rejected not in state.sounds


async def test_persisted_legacy_name_is_resolvable_and_unchanged_rename_is_allowed() -> None:
    legacy_name = "legacy" * 100
    sound = make_sound(directory="legacy-storage")
    state.sounds[legacy_name] = sound

    assert len(legacy_name) > SOUND_NAME_MAX_CODE_POINTS
    service = SoundService()
    assert service.resolve_sound_name(legacy_name) == (legacy_name, sound)

    unchanged = await service.rename_sound(legacy_name, legacy_name)
    assert unchanged.success
    assert state.sounds[legacy_name] is sound

    changed = await service.rename_sound(legacy_name, f"{legacy_name}x")
    assert not changed.success
    assert "500 Unicode code points" in changed.message
    assert state.sounds[legacy_name] is sound


def test_sound_info_route_supports_slashes_in_names() -> None:
    name = "folder/name"
    sound = make_sound(directory="slash-storage")
    state.sounds[name] = sound
    app = FastAPI()
    app.include_router(sounds_router)

    response = TestClient(app).get("/api/sounds/folder/name")

    assert response.status_code == 200
    assert response.json()["name"] == name


async def test_audio_download_filename_uses_rfc_safe_content_disposition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sounds_folder", str(tmp_path))
    name = 'quote"\r\n😀'
    sound = make_sound(directory="safe-storage")
    sound_dir = tmp_path / sound.directory
    sound_dir.mkdir()
    _ = (sound_dir / sound.files.trimmed_audio).write_bytes(b"ogg")
    state.sounds[name.lower()] = sound

    response = await get_sound_audio(name)
    disposition = response.headers["content-disposition"]

    assert "\r" not in disposition
    assert "\n" not in disposition
    assert 'quote"' not in disposition
    assert "filename*=utf-8''" in disposition
