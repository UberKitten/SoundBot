"""Tests for alias and group management (pure state logic, no ffmpeg/fs)."""

from soundbot.core.state import state
from soundbot.services.sounds import sound_service

from .conftest import make_sound


class TestAliases:
    def test_add_alias(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        result = sound_service.add_alias("airhorn", "horn")
        assert result.success
        assert "horn" in state.sounds["airhorn"].aliases

    def test_add_alias_lowercased(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        _ = sound_service.add_alias("airhorn", "HORN")
        assert "horn" in state.sounds["airhorn"].aliases

    def test_add_alias_unknown_sound_fails(self) -> None:
        result = sound_service.add_alias("nope", "horn")
        assert not result.success

    def test_add_alias_conflict_with_sound_name(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        state.sounds["boing"] = make_sound("boing")
        result = sound_service.add_alias("airhorn", "boing")
        assert not result.success

    def test_add_duplicate_alias_fails(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        result = sound_service.add_alias("airhorn", "horn")
        assert not result.success

    def test_add_alias_conflict_with_other_sound_alias(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        state.sounds["boing"] = make_sound("boing")
        result = sound_service.add_alias("boing", "horn")
        assert not result.success

    def test_remove_alias(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        result = sound_service.remove_alias("airhorn", "horn")
        assert result.success
        assert "horn" not in state.sounds["airhorn"].aliases

    def test_remove_alias_not_present_fails(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        result = sound_service.remove_alias("airhorn", "horn")
        assert not result.success


class TestGroups:
    def test_create_group(self) -> None:
        result = sound_service.create_group("grp")
        assert result.success
        assert "grp" in state.groups

    def test_create_duplicate_group_fails(self) -> None:
        _ = sound_service.create_group("grp")
        result = sound_service.create_group("grp")
        assert not result.success

    def test_create_group_conflict_with_sound_fails(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn")
        result = sound_service.create_group("airhorn")
        assert not result.success

    def test_add_to_group_autocreates(self) -> None:
        state.sounds["a"] = make_sound("a")
        result = sound_service.add_to_group("grp", "a")
        assert result.success
        assert "grp" in state.groups
        assert "a" in state.groups["grp"].members

    def test_add_to_group_unknown_sound_fails(self) -> None:
        result = sound_service.add_to_group("grp", "nope")
        assert not result.success

    def test_add_duplicate_member_fails(self) -> None:
        state.sounds["a"] = make_sound("a")
        _ = sound_service.add_to_group("grp", "a")
        result = sound_service.add_to_group("grp", "a")
        assert not result.success

    def test_add_to_group_resolves_alias_to_canonical(self) -> None:
        state.sounds["airhorn"] = make_sound("airhorn", aliases=["horn"])
        result = sound_service.add_to_group("grp", "horn")
        assert result.success
        assert state.groups["grp"].members == ["airhorn"]

    def test_remove_from_group(self) -> None:
        state.sounds["a"] = make_sound("a")
        _ = sound_service.add_to_group("grp", "a")
        result = sound_service.remove_from_group("grp", "a")
        assert result.success
        assert "a" not in state.groups["grp"].members

    def test_remove_from_unknown_group_fails(self) -> None:
        result = sound_service.remove_from_group("nope", "a")
        assert not result.success

    def test_remove_member_not_in_group_fails(self) -> None:
        state.sounds["a"] = make_sound("a")
        _ = sound_service.create_group("grp")
        result = sound_service.remove_from_group("grp", "a")
        assert not result.success

    def test_delete_group(self) -> None:
        _ = sound_service.create_group("grp")
        result = sound_service.delete_group("grp")
        assert result.success
        assert "grp" not in state.groups

    def test_delete_unknown_group_fails(self) -> None:
        result = sound_service.delete_group("nope")
        assert not result.success


class TestGroupRandomMode:
    def test_default_is_together(self) -> None:
        _ = sound_service.create_group("grp")
        assert state.groups["grp"].random_mode == "together"

    def test_set_separate(self) -> None:
        _ = sound_service.create_group("grp")
        result = sound_service.set_group_random_mode("grp", "separate")
        assert result.success
        assert state.groups["grp"].random_mode == "separate"

    def test_set_same_mode_fails(self) -> None:
        _ = sound_service.create_group("grp")
        result = sound_service.set_group_random_mode("grp", "together")
        assert not result.success

    def test_set_mode_unknown_group_fails(self) -> None:
        result = sound_service.set_group_random_mode("nope", "separate")
        assert not result.success
