from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from soundbot.core.settings import settings
from soundbot.core.state import state
from soundbot.discord import cards, client
from soundbot.services import clips as clip_service
from soundbot.services.clips import ClipResult
from soundbot.web.clipsign import (
    sign_clip_directory_url,
    sign_clip_url,
    verify_clip_directory_sig,
    verify_clip_sig,
)
from soundbot.web.routes import clips as clip_routes
from tests.conftest import make_sound


class SendCapture:
    def __init__(self) -> None:
        self.contents: list[str] = []
        self.embeds: list[object] = []

    async def send_message(self, content: str | None = None, *, embed=None, **_kwargs) -> None:
        if content is not None:
            self.contents.append(content)
        if embed is not None:
            self.embeds.append(embed)

    async def send(self, content: str | None = None, *, embed=None, **kwargs) -> None:
        await self.send_message(content, embed=embed, **kwargs)


class InteractionCapture:
    def __init__(self) -> None:
        self.response = SendCapture()
        self.followup = SendCapture()


def test_utf16_budgeting_does_not_undercount_supplementary_unicode() -> None:
    value = "😀" * 500

    assert cards.discord_utf16_units(value) == 1000
    truncated = cards.truncate_discord_text(value, 999)
    assert cards.discord_utf16_units(truncated) <= 999
    assert truncated.endswith("…")


def test_long_name_cards_preserve_full_identity_within_embed_limits() -> None:
    name = "😀" * 500
    sound = make_sound(directory="short-id")

    embeds = (
        cards.build_play_card(name, sound),
        cards.build_info_card(name, sound, None),
    )
    for embed in embeds:
        assert embed.title is not None
        assert cards.discord_utf16_units(embed.title) <= 256
        assert embed.description is not None
        assert name in embed.description
        assert cards.discord_utf16_units(embed.description) <= 4096


async def test_list_and_search_embeds_budget_500_code_point_names() -> None:
    names = [f"{chr(97 + index)}{'😀' * 499}" for index in range(10)]
    for index, name in enumerate(names):
        state.sounds[name] = make_sound(directory=f"sound-{index}")

    list_interaction = InteractionCapture()
    list_callback = getattr(client.SoundCommands.list_sounds, "callback")
    await list_callback(None, list_interaction)
    list_embeds = list_interaction.response.embeds + list_interaction.followup.embeds

    assert len(list_embeds) > 1
    assert all(
        cards.discord_utf16_units(embed.title or "") <= 256
        for embed in list_embeds
    )
    assert all(
        cards.discord_utf16_units(embed.description or "") <= 4096
        for embed in list_embeds
    )
    rendered = "\n".join(embed.description or "" for embed in list_embeds)
    assert all(name in rendered for name in names)

    query = names[0]
    search_interaction = InteractionCapture()
    search_callback = getattr(client.SoundCommands.search_sounds, "callback")
    await search_callback(None, search_interaction, query)
    search_embed = search_interaction.response.embeds[0]
    assert cards.discord_utf16_units(search_embed.title or "") <= 256
    assert cards.discord_utf16_units(search_embed.description or "") <= 4096
    assert query in (search_embed.description or "")


async def test_play_post_keeps_bounded_clip_url_first_and_content_under_2000(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "😀" * 500
    sound = make_sound(directory="界" * 50, source_url="https://example.test/source")
    sound.source_title = "](@everyone)" * 200
    sound.files.trimmed_video = "video.mkv"
    clip_path = tmp_path / "clip.mp4"
    _ = clip_path.write_bytes(b"clip")

    async def fake_ensure_clip(*_args, **_kwargs) -> ClipResult:
        return ClipResult(path=clip_path)

    monkeypatch.setattr(clip_service, "ensure_clip", fake_ensure_clip)
    monkeypatch.setattr(settings, "session_secret", "test-secret")
    monkeypatch.setattr(settings, "oauth_redirect_base", "https://soundbot.example/")
    sent: list[str] = []

    async def capture(content: str = "", **_kwargs) -> object:
        sent.append(content)
        return object()

    await cards.post_clip_and_card(capture, name, sound)

    assert len(sent) == 1
    assert sent[0].startswith("https://soundbot.example/clip-ids/")
    assert name in sent[0]
    assert cards.discord_utf16_units(sent[0]) <= 2000


def test_directory_clip_signature_is_domain_separated_from_legacy_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "session_secret", "test-secret")
    expires = 2_000_000_000
    directory = "short-id"
    directory_url = sign_clip_directory_url(directory, expires)
    legacy_url = sign_clip_url(directory, expires)
    directory_sig = parse_qs(urlparse(directory_url).query)["sig"][0]
    legacy_sig = parse_qs(urlparse(legacy_url).query)["sig"][0]

    assert verify_clip_directory_sig(directory, expires, directory_sig)
    assert verify_clip_sig(directory, expires, legacy_sig)
    assert not verify_clip_sig(directory, expires, directory_sig)
    assert not verify_clip_directory_sig(directory, expires, legacy_sig)


def test_bounded_clip_route_resolves_directory_and_legacy_name_route_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "session_secret", "test-secret")
    clip_path = tmp_path / "served.mp4"
    _ = clip_path.write_bytes(b"served clip")
    name = "folder/name"
    directory = "short-storage-id"
    sound = make_sound(directory=directory)
    sound.files.trimmed_video = "source.mkv"
    state.sounds[name] = sound

    async def fake_ensure_clip(*_args, **_kwargs) -> ClipResult:
        return ClipResult(path=clip_path)

    monkeypatch.setattr(clip_routes, "ensure_clip", fake_ensure_clip)
    app = FastAPI()
    app.include_router(clip_routes.router)
    expires = 2_000_000_000

    with TestClient(app) as test_client:
        by_id = test_client.get(sign_clip_directory_url(directory, expires))
        legacy = test_client.get(sign_clip_url(name, expires))

    assert by_id.status_code == 200
    assert by_id.content == b"served clip"
    assert legacy.status_code == 200
    assert legacy.content == b"served clip"
