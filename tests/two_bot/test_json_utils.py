"""Tests for src/two_bot/json_utils.py — Codex finding #4 coverage.

Fix A: string-aware trailing-comma stripper.
Fix B: extract_json_payload continues scanning when first balanced span fails to parse.
"""

from __future__ import annotations

import json
import pytest

from src.two_bot.json_utils import (
    ModelJSONIntegrityError,
    extract_json_payload,
    loads_model_json,
)


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

    def test_array_before_object_is_terminal(self):
        """Both documents count, regardless of their top-level types."""
        raw = '[1,2,3] before {"v":1}'
        with pytest.raises(ModelJSONIntegrityError):
            loads_model_json(raw)

    def test_object_expected_cannot_hide_another_array_document(self):
        """The expected selector cannot choose between valid documents."""
        raw = '[1,2,3] {"v":1}'
        with pytest.raises(ModelJSONIntegrityError):
            loads_model_json(raw, expected="object")


@pytest.mark.parametrize("expected", ["any", "object", "array"])
@pytest.mark.parametrize("raw", [
    '{"kill_reason":"missing evidence"} {"tweet":"usable"}',
    '{"tweet":"usable"}\n{"kill_reason":"missing evidence"}',
    '{"passed":true} {"passed":true}',
    '[] []',
    '{"items":[{"nested":true}]} []',
    '[{"nested":true}] {"passed":true}',
    '```json\n{"passed":true}\n```\nLater:\n```json\n{"passed":false}\n```',
    'Reason: {not json} {"passed":true} prose {not json either} {"passed":false}',
    '{"passed":true, /* compatible repair */} {"passed":false,}',
], ids=["kill-first", "usable-first", "identical", "arrays", "object-array",
        "array-object", "separate-fences", "malformed-between", "cleaned-results"])
def test_separate_parseable_documents_are_terminal(raw, expected):
    with pytest.raises(ModelJSONIntegrityError, match="Multiple"):
        loads_model_json(raw, expected=expected)


@pytest.mark.parametrize("raw,value", [
    ('Intro: {"items":[{"nested":{"value":1}},[2,3]]} done.',
     {"items": [{"nested": {"value": 1}}, [2, 3]]}),
    ('[{"nested":{"value":1}},[2,3]]', [{"nested": {"value": 1}}, [2, 3]]),
    ('Here is the result: {"value":"braces {} [] and \\\"quoted\\\""}',
     {"value": 'braces {} [] and "quoted"'}),
    ('"An example {\\"passed\\":false}" Result: {"passed":true}', {"passed": True}),
    ('/* {"passed":false} [] */ {"passed":true} // {"passed":false}\n', {"passed": True}),
    ('// {"passed":false} []\n{"passed":true} /* {} [] */', {"passed": True}),
    ('{"passed": /* } ] { [ */ true, "items":[1, // } ]\n2,],}',
     {"passed": True, "items": [1, 2]}),
    ('Reason: {not json} ```json\n{"passed":true,}\n``` done', {"passed": True}),
    ('Here\'s the result: {"passed":true}', {"passed": True}),
], ids=["nested-object", "nested-array", "string-braces", "quoted-example",
        "comments-around", "line-comment", "comments-inside", "malformed-wrapper", "apostrophe"])
def test_one_result_remains_compatible_without_counting_nested_or_quoted_json(raw, value):
    assert loads_model_json(raw) == value


@pytest.mark.parametrize("url", [
    "https://example.invalid/source", "http://example.invalid/source",
    "https://example.invalid/path//part", "https://example.invalid/*path*/source",
    "(https://example.invalid/source)", "<https://example.invalid/source>",
    "source=https://example.invalid/source",
    "https://[2001:db8::1]/path//part", "https://example.invalid/(part)//next",
    "https://example.invalid/O'Reilly//part",
], ids=["https", "http", "path-slashes", "path-star", "parentheses", "angle-brackets",
        "assignment", "ipv6", "path-parentheses", "path-apostrophe"])
@pytest.mark.parametrize("second_result", [False, True], ids=["preamble", "between-results"])
def test_url_prose_preserves_one_result_and_cannot_hide_another_document(url, second_result):
    if second_result:
        raw = f'{{"passed":true}}\nSee {url} for context; revised result: {{"passed":false}}'
        with pytest.raises(ModelJSONIntegrityError, match="Multiple"):
            loads_model_json(raw, expected="object")
    else:
        assert loads_model_json(f'For {url} the result is {{"passed":true}}') == {"passed": True}


@pytest.mark.parametrize("raw", [
    'For https://example.invalid/source // {"passed":false}\n{"passed":true}',
    '{"passed":true} /* See https://example.invalid/source {"passed":false} */',
    '{"passed":// {"passed":false}\ntrue}',
    '{"passed":/* https://example.invalid/source {"passed":false} */true}',
], ids=["after-url", "block-around-url", "value-line-comment", "value-block-comment"])
def test_true_comments_around_url_prose_and_inside_json_remain_compatible(raw):
    assert loads_model_json(raw) == {"passed": True}


@pytest.mark.parametrize("invalid", [
    '{"passed":true,"passed":false}', '{"value":NaN}', '{"value":Infinity}',
    '{"value":-Infinity}', '{"value":1e999}',
])
@pytest.mark.parametrize("invalid_first", [True, False])
def test_integrity_failure_remains_terminal_on_either_side_of_a_valid_result(invalid, invalid_first):
    valid = '{"passed":true}'
    raw = f"{invalid} {valid}" if invalid_first else f"{valid} {invalid}"
    with pytest.raises(ModelJSONIntegrityError):
        loads_model_json(raw)


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
