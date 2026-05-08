"""Shared JSON boundary helpers for model responses and state payloads."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
import json
import re
from typing import Any


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


def _matching_json_span(text: str, start: int) -> tuple[int, int] | None:
    open_char = text[start]
    if open_char not in "{[":
        return None
    close_for = {"{": "}", "[": "]"}
    stack = [close_for[open_char]]
    in_string = False
    quote = ""
    escaped = False
    i = start + 1
    while i < len(text):
        ch = text[i]
        if in_string:
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
            i += 1
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
    """Yield (start, end) for each balanced {…} or […] span in *text*.

    Spans are yielded in left-to-right order.  The caller decides whether
    the text slice actually parses as valid JSON.
    """
    starts = "{[" if expected == "any" else ("{" if expected == "object" else "[")
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in starts:
            span = _matching_json_span(text, i)
            if span is not None:
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


def _try_parse_span(span_text: str) -> Any:
    """Try to parse span_text, applying comment/comma cleanup on first failure.

    Raises json.JSONDecodeError if still invalid after cleanup.
    """
    try:
        return json.loads(span_text)
    except json.JSONDecodeError:
        cleaned = _strip_json_comments(span_text)
        cleaned = _strip_trailing_commas(cleaned)
        return json.loads(cleaned)  # let this raise if still broken


def loads_model_json(raw: str, *, expected: str = "any") -> Any:
    """Parse model JSON despite common fences, preambles, comments, and commas.

    Tries each balanced span left-to-right; the first one that parses
    (after optional comment/comma cleanup) is returned.  Raises on total
    failure so callers always see an error instead of silent None.
    """
    text = strip_markdown_fences(raw)
    spans = list(_iter_json_spans(text, expected))

    last_exc: Exception | None = None
    for span in spans:
        candidate = text[span[0]:span[1]]
        try:
            return _try_parse_span(candidate)
        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            continue

    # No span parsed — try the whole (fence-stripped) text as last resort
    # so that clean responses with no unusual preamble still work.
    try:
        return _try_parse_span(text)
    except (json.JSONDecodeError, ValueError) as exc:
        last_exc = exc

    raise ValueError(f"invalid JSON in model response: {last_exc}") from last_exc
