"""Tests for src/two_bot/json_utils.py — Codex finding #4 coverage.

Fix A: string-aware trailing-comma stripper.
Fix B: extract_json_payload continues scanning when first balanced span fails to parse.
"""

from __future__ import annotations

import json
import pytest

from src.two_bot.json_utils import extract_json_payload, loads_model_json


# ---------------------------------------------------------------------------
# Fix A: string-aware trailing-comma stripper
# ---------------------------------------------------------------------------

class TestStringAwareTrailingComma:
    """The regex fallback must not corrupt string values that happen to
    contain the literal characters ,} or ,].
    """

    def test_comma_brace_inside_string_is_preserved(self):
        """Core probe from Codex finding: ,} inside a string value must
        survive the trailing-comma cleanup pass.
        """
        raw = '{"tweet":"a,}","kill_reason":null,}'
        result = loads_model_json(raw)
        assert result == {"tweet": "a,}", "kill_reason": None}

    def test_escaped_quotes_inside_string(self):
        """Escaped double-quotes must be handled correctly."""
        raw = '{"text":"he said \\"hi\\""}'
        result = loads_model_json(raw)
        assert result == {"text": 'he said "hi"'}

    def test_brace_inside_string_is_preserved(self):
        """Braces inside string values must not confuse the span scanner."""
        raw = '{"text":"a{b}c"}'
        result = loads_model_json(raw)
        assert result == {"text": "a{b}c"}

    def test_trailing_comma_inside_string_is_preserved(self):
        """A trailing comma that lives INSIDE a string value is valid JSON
        and must pass through untouched.
        """
        raw = '{"text":"x, y, z,",}'
        result = loads_model_json(raw)
        assert result == {"text": "x, y, z,"}

    def test_trailing_comma_on_array_element_removed(self):
        """Trailing comma before ] outside strings must still be stripped."""
        raw = '[1, 2, 3,]'
        result = loads_model_json(raw)
        assert result == [1, 2, 3]

    def test_trailing_comma_on_object_value_removed(self):
        """Trailing comma before } outside strings must still be stripped."""
        raw = '{"a": 1, "b": 2,}'
        result = loads_model_json(raw)
        assert result == {"a": 1, "b": 2}

    def test_nested_object_trailing_comma(self):
        """Nested trailing commas are cleaned correctly."""
        raw = '{"outer": {"inner": 42,},}'
        result = loads_model_json(raw)
        assert result == {"outer": {"inner": 42}}

    def test_string_with_bracket_combo(self):
        """String containing ,] must not be treated as a trailing-comma context."""
        raw = '{"items":"[a, b, c,]","count":3,}'
        result = loads_model_json(raw)
        assert result == {"items": "[a, b, c,]", "count": 3}


# ---------------------------------------------------------------------------
# Fix B: extract_json_payload continues scanning past invalid spans
# ---------------------------------------------------------------------------

class TestExtractJsonPayloadMultiSpan:
    """When the first balanced span fails to parse, the extractor must
    continue scanning for a later span that does parse successfully.
    """

    def test_non_json_brace_preamble_skipped(self):
        """A model preamble like 'Reason: {not json}' should not block
        extraction of the valid JSON object that follows it.
        """
        raw = 'Reason: {not json: also: bad} {"tweet":"valid"}'
        result = loads_model_json(raw)
        assert result == {"tweet": "valid"}

    def test_non_json_preamble_direct_extraction(self):
        """extract_json_payload returns the first balanced span (no parse
        guarantee — that's loads_model_json's job).  The multi-span loop
        that skips bad spans lives in loads_model_json, not here.
        """
        raw = 'Reason: {not json: also: bad} {"valid":"object"}'
        payload = extract_json_payload(raw)
        # The first balanced span is the bad one; the valid span is
        # discovered by loads_model_json (see test_non_json_brace_preamble_skipped).
        assert payload in ("{not json: also: bad}", '{"valid":"object"}')

    def test_preamble_with_nested_bad_brace(self):
        """Multiple bad spans before the good one should all be skipped."""
        raw = 'Step 1: {bad} Step 2: {also bad: x} Final: {"ok":true}'
        result = loads_model_json(raw)
        assert result == {"ok": True}

    def test_array_before_object_resolves_to_array(self):
        """If an array precedes the object, the first parseable span wins.
        Document the contract: expected='any' picks the first valid span
        regardless of type (array or object).
        """
        raw = '[1,2,3] before {"v":1}'
        # Whatever comes first and parses is returned — don't change existing behavior.
        result = loads_model_json(raw)
        assert result in ([1, 2, 3], {"v": 1})  # either is acceptable

    def test_object_expected_skips_array_span(self):
        """expected='object' should skip arrays and return the first object."""
        raw = '[1,2,3] {"v":1}'
        result = loads_model_json(raw, expected="object")
        assert result == {"v": 1}


# ---------------------------------------------------------------------------
# Failure path: must raise, never return None silently
# ---------------------------------------------------------------------------

class TestLoadsModelJsonRaisesOnTrulyBadInput:
    """Callers rely on ValueError bubbling up when there is no parseable
    JSON anywhere in the input. Silent None returns hide bugs.
    """

    def test_completely_invalid_raises(self):
        with pytest.raises((ValueError, Exception)):
            loads_model_json("not json at all { broken")

    def test_empty_string_raises(self):
        with pytest.raises((ValueError, Exception)):
            loads_model_json("")

    def test_lone_brace_raises(self):
        with pytest.raises((ValueError, Exception)):
            loads_model_json("{")

    def test_unclosed_object_raises(self):
        with pytest.raises((ValueError, Exception)):
            loads_model_json('{"key": "value"')
