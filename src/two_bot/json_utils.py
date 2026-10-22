"""Shared JSON boundary helpers for model responses and state payloads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Any


def model_response_diagnostic(raw: Any) -> str:
    """A bounded correlation token safe for public workflow logs."""
    if not isinstance(raw, str):
        return f"response_type={type(raw).__name__}"
    encoded = raw.encode("utf-8", errors="backslashreplace")
    return f"response_chars={len(raw)} response_sha256={hashlib.sha256(encoded).hexdigest()}"


def json_default(obj: Any):
    """Serialize common non-JSON-native values without hiding unknown types."""

    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")


def strip_markdown_fences(raw: str) -> str:
    text = (raw or "").strip()
    text = _FENCE_OPEN_RE.sub("", text, count=1)
    text = _FENCE_CLOSE_RE.sub("", text, count=1)
    return text.strip()


def _strip_json_comments(text: str) -> str:
    """Remove // and /* */ comments outside quoted strings."""

    out: list[str] = []
    i = 0
    in_string = False
    quote = ""
    escaped = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                in_string = False
            i += 1
            continue
        if ch in {'"', "'"}:
            in_string = True
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] that appear OUTSIDE quoted strings.

    Uses a character walker that tracks quoted-string state and escape
    sequences so that ,} or ,] inside a string value is never touched.
    """
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
                out.append(ch)
                i += 1
                continue
            if ch == "\\":
                escaped = True
                out.append(ch)
                i += 1
                continue
            if ch == '"':
                in_string = False
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue
        # Outside a string
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            # Look ahead past optional whitespace to find } or ]
            j = i + 1
            while j < len(text) and text[j] in " \t\r\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                # Skip this comma (and keep the whitespace we consumed)
                i = i + 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _quoted_string_end(text: str, start: int) -> int:
    quote = text[start]
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == quote:
            return i + 1
        else:
            i += 1
    return len(text)


def _comment_end(text: str, start: int) -> int:
    if text.startswith("//", start):
        i = start + 2
        while i < len(text) and text[i] not in "\r\n":
            i += 1
        return i
    if text.startswith("/*", start):
        end = text.find("*/", start + 2)
        return len(text) if end == -1 else end + 2
    return start


def _matching_json_span(text: str, start: int) -> tuple[int, int] | None:
    open_char = text[start]
    if open_char not in "{[":
        return None
    close_for = {"{": "}", "[": "]"}
    stack = [close_for[open_char]]
    i = start + 1
    while i < len(text):
        ch = text[i]
        if ch in {'"', "'"}:
            i = _quoted_string_end(text, i)
            continue
        comment_end = _comment_end(text, i)
        if comment_end != i:
            i = comment_end
            continue
        if ch in "{[":
            stack.append(close_for[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                return start, i + 1
        i += 1
    return None


def _iter_json_spans(text: str, expected: str = "any"):
    """Yield disjoint top-level spans, ignoring strings and comments.

    Spans are yielded in left-to-right order.  The caller decides whether
    the text slice actually parses as valid JSON.
    """
    starts = "{[" if expected == "any" else ("{" if expected == "object" else "[")
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i = _quoted_string_end(text, i)
            continue
        comment_end = _comment_end(text, i)
        if comment_end != i:
            i = comment_end
            continue
        if ch in "{[":
            span = _matching_json_span(text, i)
            if span is not None:
                if ch in starts:
                    yield span
                i = span[1]  # resume scanning after this span
                continue
        i += 1


def extract_json_payload(raw: str, *, expected: str = "any") -> str:
    """Extract a top-level JSON object/array from fenced or prefaced text.

    Returns the first balanced span.  Does NOT guarantee the span parses —
    callers that need a valid parse should use ``loads_model_json`` which
    tries each span in turn.
    """
    text = strip_markdown_fences(raw)
    for span in _iter_json_spans(text, expected):
        return text[span[0]:span[1]]
    return text


class ModelJSONIntegrityError(ValueError):
    """Ambiguous/nonfinite JSON is terminal, never a recoverable preamble."""


class ModelOutputContractError(ValueError):
    """Decoded output violates a known contract; do not buy a repair pass."""


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelJSONIntegrityError(f"Duplicate model JSON field: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value):
    raise ModelJSONIntegrityError(f"Nonfinite model JSON value: {value}")


def _strict_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ModelJSONIntegrityError("Nonfinite model JSON number")
    return number


def _try_parse_span(span_text: str) -> Any:
    """Try to parse span_text, applying comment/comma cleanup on first failure.

    Raises json.JSONDecodeError if still invalid after cleanup.
    """
    try:
        return json.loads(span_text, object_pairs_hook=_strict_pairs, parse_constant=_reject_nonfinite, parse_float=_strict_float)
    except json.JSONDecodeError:
        cleaned = _strip_json_comments(span_text)
        cleaned = _strip_trailing_commas(cleaned)
        return json.loads(cleaned, object_pairs_hook=_strict_pairs, parse_constant=_reject_nonfinite, parse_float=_strict_float)  # let this raise if still broken


def loads_model_json(raw: str, *, expected: str = "any") -> Any:
    """Parse model JSON despite common fences, preambles, comments, and commas.

    Inspect every disjoint object/array before accepting one result. Multiple
    parseable documents are terminal, including documents of an unexpected
    type. Malformed preamble spans remain recoverable; integrity errors do not.
    """
    if not isinstance(raw, str):
        raise ValueError("Model response must be text")
    text = strip_markdown_fences(raw)
    parsed = False
    result: Any = None
    selected = False
    starts = "{[" if expected == "any" else ("{" if expected == "object" else "[")
    last_exc: Exception | None = None
    for span in _iter_json_spans(text):
        candidate = text[span[0]:span[1]]
        try:
            value = _try_parse_span(candidate)
        except ModelJSONIntegrityError:
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            continue
        if parsed:
            raise ModelJSONIntegrityError("Multiple top-level model JSON documents")
        parsed = True
        result = value
        selected = candidate[0] in starts

    if parsed and selected:
        return result

    # Preserve whole-text fallback for clean responses, including scalar JSON
    # and a sole document whose type differs from the expected span selector.
    try:
        return _try_parse_span(text)
    except ModelJSONIntegrityError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        last_exc = exc

    raise ValueError(f"invalid JSON in model response: {last_exc}") from last_exc
