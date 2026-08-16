from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, cast

import pytest

from soundbot.core.state import state
from soundbot.discord import client
from soundbot.discord.client import SoundCommands
from tests.conftest import make_sound


class StubResponse:
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(
        self, content: str, *, ephemeral: bool = False, **_: object
    ) -> None:
        self.messages.append((content, ephemeral))

    async def defer(self, **_: object) -> None:
        self.deferred = True


class StubFollowup:
    async def send(self, *_: object, **__: object) -> None:
        pass


class StubGuild:
    def get_member(self, _: int) -> None:
        return None


class StubInteraction:
    def __init__(self) -> None:
        super().__init__()
        self.response = StubResponse()
        self.followup = StubFollowup()
        self.guild = StubGuild()
        self.user = SimpleNamespace(id=1)


async def run_random(
    monkeypatch: pytest.MonkeyPatch,
    *,
    group: Optional[str] = None,
    max_length: Optional[float] = None,
) -> tuple[StubInteraction, list[str]]:
    played: list[str] = []

    async def fake_play_sound(
        _: object,
        __: Path,
        name: str = "sound",
        user: object = None,
        duration: Optional[float] = None,
    ) -> tuple[bool, str]:
        del user, duration
        played.append(name)
        return True, f"Playing **{name}**"

    async def fake_post_clip_and_card(*_: object, **__: object) -> None:
        pass

    monkeypatch.setattr(client.voice_service, "play_sound", fake_play_sound)
    monkeypatch.setattr(client, "post_clip_and_card", fake_post_clip_and_card)
    monkeypatch.setattr(client.random, "randrange", lambda _: 0)
    monkeypatch.setattr(client.random, "choice", lambda values: values[0])

    interaction = StubInteraction()
    callback = cast(Any, SoundCommands.random_sound.callback)
    await callback(None, interaction, group, max_length)
    return interaction, played


@pytest.mark.asyncio
async def test_random_omission_keeps_120_second_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.sounds["at-default"] = make_sound(source_duration=120.0)
    state.sounds["over-default"] = make_sound(source_duration=120.001)

    interaction, played = await run_random(monkeypatch)

    assert played == ["at-default"]
    assert interaction.response.deferred
    assert interaction.response.messages == []


@pytest.mark.asyncio
async def test_random_custom_cap_excludes_longer_sounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.sounds["eligible"] = make_sound(source_duration=3.5)
    state.sounds["too-long"] = make_sound(source_duration=3.501)

    _, played = await run_random(monkeypatch, max_length=3.5)

    assert played == ["eligible"]


@pytest.mark.asyncio
async def test_random_custom_cap_is_inclusive_for_trimmed_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.sounds["trimmed-to-boundary"] = make_sound(
        source_duration=30.0,
        timestamps={"start": 2.0, "end": 7.0},
    )
    state.sounds["trimmed-over-boundary"] = make_sound(
        source_duration=30.0,
        timestamps={"start": 2.0, "end": 7.001},
    )

    _, played = await run_random(monkeypatch, max_length=5.0)

    assert played == ["trimmed-to-boundary"]


@pytest.mark.asyncio
async def test_random_custom_cap_reports_no_eligible_group_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.sounds["too-long"] = make_sound(source_duration=6.0)
    _ = client.sound_service.create_group("long-group")
    _ = client.sound_service.add_to_group("long-group", "too-long")

    interaction, played = await run_random(
        monkeypatch, group="long-group", max_length=5.0
    )

    assert played == []
    assert interaction.response.messages == [
        ("❌ No sounds at or under 5 seconds in group 'long-group'", True)
    ]
    assert not interaction.response.deferred


@pytest.mark.asyncio
@pytest.mark.parametrize("max_length", [0.0, -1.0])
async def test_random_rejects_non_positive_custom_cap(
    monkeypatch: pytest.MonkeyPatch, max_length: float
) -> None:
    state.sounds["sound"] = make_sound(source_duration=1.0)

    interaction, played = await run_random(monkeypatch, max_length=max_length)

    assert played == []
    assert interaction.response.messages == [
        ("❌ Maximum length must be greater than 0 seconds", True)
    ]
    assert not interaction.response.deferred
