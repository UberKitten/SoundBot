"""Tests for SoundService name resolution and search logic."""

from soundbot.core.state import state
from soundbot.services.sounds import sound_service

from .conftest import make_sound


class TestResolveSoundName:
    def test_exact_canonical(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        resolved = sound_service.resolve_sound_name("airhorn")
        assert resolved is not None
        assert resolved[0] == "airhorn"

    def test_case_insensitive(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        resolved = sound_service.resolve_sound_name("AirHorn")
        assert resolved is not None
        assert resolved[0] == "airhorn"

    def test_alias(self) -> None:
        snd = make_sound("airhorn", aliases=["horn"])
        state.sounds["airhorn"] = snd
        resolved = sound_service.resolve_sound_name("horn")
        assert resolved is not None
        assert resolved[0] == "airhorn"
        assert resolved[1] is snd

    def test_alias_case_insensitive(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["Horn"])
        resolved = sound_service.resolve_sound_name("HORN")
        assert resolved is not None
        assert resolved[0] == "airhorn"

    def test_unknown_returns_none(self) -> None:
        assert sound_service.resolve_sound_name("nope") is None


class TestSearchSounds:
    def test_partial_name_match(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        state.sounds["airplane"] = make_sound("airplane")
        state.sounds["boing"] = make_sound("boing")
        results = sound_service.search_sounds("air")
        names = [n for n, _ in results]
        assert names == ["airhorn", "airplane"]  # sorted

    def test_alias_partial_match(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["loudhorn"])
        results = sound_service.search_sounds("loud")
        assert [n for n, _ in results] == ["airhorn"]

    def test_no_duplicate_when_name_and_alias_match(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["airthing"])
        results = sound_service.search_sounds("air")
        assert [n for n, _ in results] == ["airhorn"]

    def test_no_match_returns_empty(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        assert sound_service.search_sounds("zzz") == []


class TestResolvePlayable:
    """resolve_playable ordering: exact/alias -> group random -> single partial."""

    def test_exact_wins(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        result = sound_service.resolve_playable("airhorn")
        assert result is not None
        assert result[0] == "airhorn"

    def test_alias_resolves(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        result = sound_service.resolve_playable("horn")
        assert result is not None
        assert result[0] == "airhorn"

    def test_group_random_member(self) -> None:
        state.sounds["a"] = make_sound("a")
        state.sounds["b"] = make_sound("b")
        _ = sound_service.create_group("grp")
        _ = sound_service.add_to_group("grp", "a")
        _ = sound_service.add_to_group("grp", "b")
        result = sound_service.resolve_playable("grp")
        assert result is not None
        assert result[0] in {"a", "b"}

    def test_single_partial_match(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        result = sound_service.resolve_playable("airh")
        assert result is not None
        assert result[0] == "airhorn"

    def test_ambiguous_partial_returns_none(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        state.sounds["airplane"] = make_sound("airplane")
        # "air" matches two -> not a single partial, and not exact/alias/group
        assert sound_service.resolve_playable("air") is None

    def test_unknown_returns_none(self) -> None:
        assert sound_service.resolve_playable("nope") is None


class TestResolveGroup:
    def test_resolve_group_members(self) -> None:
        state.sounds["a"] = make_sound("a")
        _ = sound_service.create_group("grp")
        _ = sound_service.add_to_group("grp", "a")
        assert sound_service.resolve_group("grp") == ["a"]

    def test_resolve_group_unknown_none(self) -> None:
        assert sound_service.resolve_group("nope") is None

    def test_resolve_group_random_exhausts_bag(self) -> None:
        # Shuffle bag: no repeats until all members drawn.
        for n in ("a", "b", "c"):
            state.sounds[n] = make_sound(n)
        _ = sound_service.create_group("grp")
        for n in ("a", "b", "c"):
            _ = sound_service.add_to_group("grp", n)

        drawn: list[str] = []
        for _ in range(3):
            r = sound_service.resolve_group_random("grp")
            assert r is not None
            drawn.append(r[0])
        assert sorted(drawn) == ["a", "b", "c"]  # each exactly once

    def test_resolve_group_random_empty_group_none(self) -> None:
        _ = sound_service.create_group("empty")
        assert sound_service.resolve_group_random("empty") is None
