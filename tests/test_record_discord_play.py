"""Tests for SoundService.record_discord_play (the single Discord counting path)."""

from datetime import datetime

from soundbot.core.state import state
from soundbot.services.sounds import sound_service

from .conftest import make_sound


class TestRecordDiscordPlay:
    def test_bumps_play_count(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        assert state.sounds["airhorn"].discord.plays == 0
        sound_service.record_discord_play("airhorn")
        assert state.sounds["airhorn"].discord.plays == 1

    def test_increments_repeatedly(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        for _ in range(5):
            sound_service.record_discord_play("airhorn")
        assert state.sounds["airhorn"].discord.plays == 5

    def test_sets_last_played(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        assert state.sounds["airhorn"].discord.last_played is None
        before = datetime.now()
        sound_service.record_discord_play("airhorn")
        after = datetime.now()
        last = state.sounds["airhorn"].discord.last_played
        assert last is not None
        assert before <= last <= after

    def test_resolves_via_alias(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        sound_service.record_discord_play("horn")
        assert state.sounds["airhorn"].discord.plays == 1

    def test_noop_on_unknown_name(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        # Should not raise, should not touch existing counts.
        sound_service.record_discord_play("this-is-a-temp-quickplay-title")
        assert state.sounds["airhorn"].discord.plays == 0

    def test_saves_state(self, monkeypatch: object) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        calls: list[int] = []
        # Patch State.save at the class level (pydantic models reject
        # per-instance attribute assignment) to observe the save fires and
        # to avoid a real disk write.
        import soundbot.core.state as state_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            state_mod.State, "save", lambda self: calls.append(1)
        )
        sound_service.record_discord_play("airhorn")
        assert calls == [1]

    def test_noop_does_not_save(self, monkeypatch: object) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        calls: list[int] = []
        import soundbot.core.state as state_mod

        monkeypatch.setattr(  # type: ignore[attr-defined]
            state_mod.State, "save", lambda self: calls.append(1)
        )
        sound_service.record_discord_play("unknown-name")
        assert calls == []


class TestRecordDiscordClip:
    """clip_only=True — clip shown in chat, nobody in voice, no VC play."""

    def test_bumps_clip_count_not_plays(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        sound_service.record_discord_play("airhorn", clip_only=True)
        assert state.sounds["airhorn"].discord_clips.plays == 1
        assert state.sounds["airhorn"].discord.plays == 0

    def test_vc_play_does_not_bump_clip_count(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        sound_service.record_discord_play("airhorn")
        assert state.sounds["airhorn"].discord.plays == 1
        assert state.sounds["airhorn"].discord_clips.plays == 0

    def test_sets_clip_last_played(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        before = datetime.now()
        sound_service.record_discord_play("airhorn", clip_only=True)
        after = datetime.now()
        last = state.sounds["airhorn"].discord_clips.last_played
        assert last is not None
        assert before <= last <= after

    def test_noop_on_unknown_name(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        sound_service.record_discord_play("unknown-name", clip_only=True)
        assert state.sounds["airhorn"].discord_clips.plays == 0
