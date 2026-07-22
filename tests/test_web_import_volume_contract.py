from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.ffmpeg import ProbeResult, ProcessResult, ffmpeg_service
from soundbot.services.sounds import OperationResult, SoundService
from soundbot.web.dependencies import AdminUser
from soundbot.web.routes import admin, drafts


@pytest.fixture
def admin_user() -> AdminUser:
    return AdminUser(id="123", username="tester", avatar=None)


def test_web_import_and_trim_models_do_not_declare_volume_adjust() -> None:
    assert "volume_adjust" not in admin.AddSoundBody.model_fields
    assert "volume_adjust" not in admin.TrimBody.model_fields
    assert "volume_adjust" not in drafts.CommitDraftBody.model_fields

    # Existing explicit sound-volume mutations remain part of the admin API.
    assert "volume_adjust" in admin.PatchBody.model_fields


async def test_legacy_admin_add_uses_service_default_volume(
    monkeypatch: pytest.MonkeyPatch, admin_user: AdminUser
) -> None:
    add_sound = AsyncMock(return_value=OperationResult(success=True, message="ok"))
    monkeypatch.setattr(admin.sound_service, "add_sound", add_sound)

    result = await admin.add_sound(
        admin.AddSoundBody(name="Air Horn", url="https://example.test/audio", start=1.25, end=3.5),
        admin_user,
    )

    assert result == {"name": "air horn"}
    add_sound.assert_awaited_once_with(
        name="Air Horn",
        url="https://example.test/audio",
        start=1.25,
        end=3.5,
        added_by="tester",
    )


async def test_draft_commit_uses_local_import_default_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin_user: AdminUser
) -> None:
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    source = draft_dir / "source.mkv"
    _ = source.write_bytes(b"draft media")
    info = drafts.DraftInfo(
        url="https://example.test/source",
        title="Source title",
        duration=10.0,
        created=datetime.now(),
        original_filename=source.name,
        has_video=False,
    )

    monkeypatch.setattr(drafts, "gc_old_drafts", lambda: None)
    monkeypatch.setattr(drafts, "_draft_dir", lambda _draft_id: draft_dir)
    monkeypatch.setattr(drafts, "_load_draft_info", lambda _draft_dir: info)
    add_local = AsyncMock(return_value=OperationResult(success=True, message="ok"))
    monkeypatch.setattr(drafts.sound_service, "add_sound_from_local_file", add_local)

    result = await drafts.commit_draft(
        drafts.CommitDraftBody(name="Air Horn", start=0.125, end=3.875),
        "draft-id",
        admin_user,
    )

    assert result == {"name": "air horn"}
    add_local.assert_awaited_once_with(
        name="Air Horn",
        source_path=source,
        original_filename="source.mkv",
        source_url="https://example.test/source",
        source_title="Source title",
        start=0.125,
        end=3.875,
        added_by="tester",
    )
    assert not draft_dir.exists()


async def test_trim_ignores_stale_volume_input_and_only_edits_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sound = SimpleNamespace(
        timestamps=SimpleNamespace(start=1.25, end=3.5),
        volume_adjust=2,
    )
    edit_timestamps = AsyncMock(
        return_value=OperationResult(success=True, message="ok")
    )
    monkeypatch.setattr(admin.sound_service, "get_sound", lambda _name: sound)
    monkeypatch.setattr(
        admin.sound_service,
        "resolve_sound_name",
        lambda _name: ("airhorn", sound),
    )
    monkeypatch.setattr(admin.sound_service, "edit_timestamps", edit_timestamps)

    body = admin.TrimBody.model_validate(
        {"start": 1.25, "end": 3.5, "volume_adjust": -5}
    )
    result = await admin.trim_sound("airhorn", body)

    edit_timestamps.assert_awaited_once_with("airhorn", start=1.25, end=3.5)
    assert sound.volume_adjust == 2
    assert result == {"start": 1.25, "end": 3.5, "volume_adjust": 2}


async def test_default_draft_import_still_uses_ffmpeg_loudness_normalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "sounds_folder", str(tmp_path / "sounds"))
    source = tmp_path / "source.mkv"
    _ = source.write_bytes(b"media")

    probe = AsyncMock(
        return_value=ProbeResult(duration=9.0, has_audio=True, has_video=False)
    )
    normalize = AsyncMock(return_value=ProcessResult(success=True))
    monkeypatch.setattr(ffmpeg_service, "probe", probe)
    monkeypatch.setattr(ffmpeg_service, "extract_and_normalize_audio", normalize)

    service = SoundService()
    monkeypatch.setattr(service, "_generate_clip", AsyncMock())

    result = await service.add_sound_from_local_file(
        name="Air Horn",
        source_path=source,
        start=0.125,
        end=3.875,
        added_by="tester",
    )

    assert result.success
    sound_dir = tmp_path / "sounds" / "air_horn"
    normalize.assert_awaited_once_with(
        sound_dir / "air_horn_original.mkv",
        sound_dir / "air_horn.ogg",
        start=0.125,
        end=3.875,
        volume_db=0.0,
    )
    assert state.sounds["air horn"].volume_adjust == 0
