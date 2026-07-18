"""Tests for soundbot.core.utils.parse_timestamp (and format_timestamp)."""

from soundbot.core.utils import format_timestamp, parse_timestamp


class TestParseTimestamp:
    def test_plain_seconds(self) -> None:
        assert parse_timestamp("90") == 90.0

    def test_plain_seconds_float(self) -> None:
        assert parse_timestamp("90.5") == 90.5

    def test_zero(self) -> None:
        assert parse_timestamp("0") == 0.0

    def test_mm_ss(self) -> None:
        assert parse_timestamp("1:30") == 90.0

    def test_mm_ss_zero_padded(self) -> None:
        assert parse_timestamp("01:30") == 90.0

    def test_hh_mm_ss(self) -> None:
        assert parse_timestamp("1:30:00") == 5400.0

    def test_hh_mm_ss_full(self) -> None:
        # 1h 30m 15s
        assert parse_timestamp("1:30:15") == 5415.0

    def test_mm_ss_with_fraction(self) -> None:
        assert parse_timestamp("1:30.5") == 90.5

    def test_whitespace_stripped(self) -> None:
        assert parse_timestamp("  90  ") == 90.0

    def test_empty_string_returns_none(self) -> None:
        assert parse_timestamp("") is None

    def test_garbage_returns_none(self) -> None:
        assert parse_timestamp("abc") is None

    def test_malformed_colon_returns_none(self) -> None:
        assert parse_timestamp("1:2:3:4") is None

    def test_non_numeric_minutes_returns_none(self) -> None:
        assert parse_timestamp("aa:bb") is None


class TestFormatTimestamp:
    def test_none(self) -> None:
        assert format_timestamp(None) == "N/A"

    def test_under_hour(self) -> None:
        assert format_timestamp(90) == "1:30.00"

    def test_over_hour(self) -> None:
        assert format_timestamp(5415) == "1:30:15.00"
