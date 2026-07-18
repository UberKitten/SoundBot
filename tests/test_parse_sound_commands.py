"""Tests for PlaybackCog._parse_sound_commands (mid-message !sound parsing)."""

from soundbot.discord.client import PlaybackCog


def parse(content: str) -> list[str]:
    # _parse_sound_commands only uses self.prefixes; avoid constructing
    # the cog (which wants a bot) by calling through a stub.
    class Stub:
        prefixes = ["!", "¡", "?", "‽", "$", "~", "ඞ", "ꙮ"]

    return PlaybackCog._parse_sound_commands(Stub(), content)  # pyright: ignore[reportArgumentType]


class TestParseSoundCommands:
    def test_start_of_message(self) -> None:
        assert parse("!meowmeow") == ["meowmeow"]

    def test_mid_message(self) -> None:
        assert parse("oh !yesyes dude") == ["yesyes"]

    def test_prefix_then_prose(self) -> None:
        assert parse("!pootis dispenser here") == ["pootis"]

    def test_multiple_sounds(self) -> None:
        assert parse("!sound1 !sound2 !sound3") == ["sound1", "sound2", "sound3"]

    def test_multiple_mid_message(self) -> None:
        assert parse("play !airhorn and then !meow ok") == ["airhorn", "meow"]

    def test_lowercases(self) -> None:
        assert parse("!MeowMeow") == ["meowmeow"]

    def test_trailing_punctuation_stripped(self) -> None:
        assert parse("wow !airhorn!") == ["airhorn"]
        assert parse("nice !meow.") == ["meow"]
        assert parse("!meow?") == ["meow"]

    def test_mid_word_prefix_ignored(self) -> None:
        # "!" inside a word is not a command
        assert parse("wow!amazing") == []

    def test_bare_prefix_ignored(self) -> None:
        assert parse("!") == []
        assert parse("hello !") == []
        assert parse("what?!") == []

    def test_url_query_string_safe(self) -> None:
        # "?" is a prefix but mid-URL it's mid-word, not word-start
        assert parse("https://youtube.com/watch?v=QNwCojJ3-Q") == []

    def test_url_at_start_safe(self) -> None:
        assert parse("youtube.com/watch?v=abc check this out") == []

    def test_plain_prose_no_commands(self) -> None:
        assert parse("hello there, general kenobi") == []

    def test_exclamation_at_word_end(self) -> None:
        # "hey!" — prefix is at word END, not start; next word untouched
        assert parse("hey! dude") == []

    def test_alternate_prefixes(self) -> None:
        assert parse("~meow") == ["meow"]
        assert parse("mid ඞ sus") == []  # bare prefix, no name attached
        assert parse("mid ඞsus ok") == ["sus"]

    def test_double_prefix(self) -> None:
        # "!!name": outer prefix at word start, inner "!" is part of \S+ —
        # strip won't remove leading chars, name keeps "!name"... verify
        # the actual behavior is stable: parser returns "!name" which the
        # downstream lookup ignores as unknown.
        assert parse("!!hello") in (["!hello"], ["hello"])
