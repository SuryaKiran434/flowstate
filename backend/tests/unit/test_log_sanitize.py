"""
Unit tests for scrub_for_log — the choke point that keeps untrusted values from
forging or breaking log records.

Covers:
- CR and LF removed, so a value cannot split one record into two
- the whole C0 range plus DEL removed (NUL, ESC, BEL, VT, ...)
- ordinary text, including non-ASCII, passes through untouched
- over-length input truncated to max_length with the marker appended
- input exactly at the limit left alone (off-by-one at the boundary)
- custom max_length honoured
- non-string inputs rendered via str() before scrubbing
"""

import pytest

from app.core.log_sanitize import _MAX_LENGTH, _TRUNCATION_MARKER, scrub_for_log


class TestControlCharacters:
    def test_newlines_removed(self):
        assert scrub_for_log("real\nforged") == "realforged"

    def test_carriage_return_removed(self):
        assert scrub_for_log("real\r\nforged") == "realforged"

    def test_forged_record_cannot_be_injected(self):
        hostile = "alice\n2026-08-30 ERROR admin deleted everything"
        assert "\n" not in scrub_for_log(hostile)

    @pytest.mark.parametrize("code", list(range(0x00, 0x20)) + [0x7F])
    def test_every_control_character_removed(self, code):
        assert scrub_for_log(f"a{chr(code)}b") == "ab"

    def test_printable_text_untouched(self):
        assert scrub_for_log("user-42 searched 'jazz'") == "user-42 searched 'jazz'"

    def test_non_ascii_preserved(self):
        assert scrub_for_log("Björk — Jóga") == "Björk — Jóga"


class TestTruncation:
    def test_long_value_truncated_to_max_length(self):
        out = scrub_for_log("x" * 1000)
        assert len(out) == _MAX_LENGTH
        assert out.endswith(_TRUNCATION_MARKER)

    def test_value_at_the_limit_is_not_truncated(self):
        exact = "x" * _MAX_LENGTH
        assert scrub_for_log(exact) == exact

    def test_one_over_the_limit_is_truncated(self):
        out = scrub_for_log("x" * (_MAX_LENGTH + 1))
        assert len(out) == _MAX_LENGTH
        assert out.endswith(_TRUNCATION_MARKER)

    def test_custom_max_length_honoured(self):
        out = scrub_for_log("y" * 100, max_length=40)
        assert len(out) == 40
        assert out.endswith(_TRUNCATION_MARKER)

    def test_control_characters_stripped_before_length_check(self):
        # 300 newlines carry no length once stripped, so nothing is truncated.
        assert scrub_for_log("\n" * 300 + "short") == "short"


class TestNonStringInput:
    @pytest.mark.parametrize(
        "value,expected",
        [(42, "42"), (None, "None"), (3.5, "3.5"), (True, "True"), ([1, 2], "[1, 2]")],
    )
    def test_rendered_via_str(self, value, expected):
        assert scrub_for_log(value) == expected

    def test_object_repr_is_also_scrubbed(self):
        class Hostile:
            def __str__(self):
                return "ok\nFORGED"

        assert scrub_for_log(Hostile()) == "okFORGED"
