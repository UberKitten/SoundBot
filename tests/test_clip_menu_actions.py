from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.services.clips import ClipResult
from soundbot.web.clipsign import verify_clip_sig
from soundbot.web.dependencies import AdminUser, require_admin
from soundbot.web.routes import admin
from tests.conftest import make_sound


async def _allowed_viewer() -> AdminUser:
    return AdminUser(id="viewer", username="Viewer", avatar=None)


def _clip_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[FastAPI, Path, list[str]]:
    clip_path = tmp_path / "selected" / "selected_clip.mp4"
    clip_path.parent.mkdir()
    _ = clip_path.write_bytes(b"selected clip bytes")

    sound = make_sound(directory="selected")
    sound.files.trimmed_video = "selected_trimmed.mp4"
    sound.aliases = ["selection-alias"]
    state.sounds["selected"] = sound

    ensured_names: list[str] = []

    async def fake_ensure_clip(sound_arg: object, sounds_dir: Path) -> ClipResult:
        del sounds_dir
        ensured_names.append(getattr(sound_arg, "directory"))
        return ClipResult(path=clip_path)

    monkeypatch.setattr(admin, "ensure_clip", fake_ensure_clip)
    monkeypatch.setattr(settings, "session_secret", "test-clip-signing-secret")
    monkeypatch.setattr(settings, "oauth_redirect_base", "https://soundbot.example/")

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[require_admin] = _allowed_viewer
    return app, clip_path, ensured_names


def test_authenticated_download_uses_selected_clip_bytes_and_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app, clip_path, ensured_names = _clip_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        inline = client.get("/api/admin/sounds/selected/video")
        download = client.get("/api/admin/sounds/selected/video?download=true")

    assert inline.status_code == 200
    assert inline.content == clip_path.read_bytes()
    assert "content-disposition" not in inline.headers
    assert inline.headers["cache-control"] == "private, no-store"

    assert download.status_code == 200
    assert download.content == clip_path.read_bytes()
    assert download.headers["content-type"].startswith("video/mp4")
    assert download.headers["cache-control"] == "private, no-store"
    assert download.headers["content-disposition"] == (
        'attachment; filename="selected_clip.mp4"'
    )
    assert ensured_names == ["selected", "selected"]


def test_authenticated_embed_url_is_absolute_signed_and_canonical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app, _, ensured_names = _clip_app(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/admin/sounds/selection-alias/clip-url")

    assert response.status_code == 200
    url = response.json()["url"]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "soundbot.example"
    assert parsed.path == "/clips/selected.mp4"
    assert set(query) == {"exp", "sig"}
    assert verify_clip_sig("selected", int(query["exp"][0]), query["sig"][0])
    assert ensured_names == ["selected"]


@pytest.mark.parametrize("status_code", [401, 403])
@pytest.mark.parametrize(
    "path",
    [
        "/api/admin/sounds/selected/video?download=true",
        "/api/admin/sounds/selected/clip-url",
    ],
)
def test_clip_actions_do_not_bypass_view_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status_code: int,
    path: str,
) -> None:
    app, _, ensured_names = _clip_app(monkeypatch, tmp_path)

    async def reject_viewer() -> AdminUser:
        raise HTTPException(status_code=status_code, detail="not allowed")

    app.dependency_overrides[require_admin] = reject_viewer

    with TestClient(app) as client:
        response = client.get(path)

    assert response.status_code == status_code
    assert ensured_names == []
