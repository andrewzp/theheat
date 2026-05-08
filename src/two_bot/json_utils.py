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
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


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


def extract_json_payload(raw: str, *, expected: str = "any") -> str:
    """Extract a top-level JSON object/array from fenced or prefaced text."""

    text = strip_markdown_fences(raw)
    starts = "{[" if expected == "any" else ("{" if expected == "object" else "[")
    for idx, ch in enumerate(text):
        if ch not in starts:
            continue
        span = _matching_json_span(text, idx)
        if span is not None:
            return text[span[0]:span[1]]
    return text


def loads_model_json(raw: str, *, expected: str = "any"):
    """Parse model JSON despite common fences, preambles, comments, and commas."""

    payload = extract_json_payload(raw, expected=expected)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        cleaned = _strip_json_comments(payload)
        cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
        return json.loads(cleaned)
