"""Fixed ordinary output bounds and complete textual Google responses.

No provider imports or authority: callers retain usage before applying this gate.
Token limits are not financial caps or limits on grounding charges.
"""
from __future__ import annotations

from typing import Any

CHECK_OUTPUT_TOKENS = 8192
NEWS_OUTPUT_TOKENS = 8192
WRITER_OUTPUT_TOKENS = 1024


class GoogleResponseUnavailable(RuntimeError):
    """Operational uncertainty, never a factual/editorial KILL or JSON retry."""


def _fields(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        result = dump(exclude_unset=True)
        if isinstance(result, dict):
            return result
    raise GoogleResponseUnavailable("google_response_invalid_metadata")


def complete_text(response: Any) -> str:
    """Require one completed, unblocked textual candidate; ignore thought text.

    The SDK's convenience text projection can hide function calls and does not
    imply a STOP finish reason. Apply this gate after retaining response usage.
    """
    candidates = getattr(response, "candidates", None)
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise GoogleResponseUnavailable("google_response_expected_one_candidate")
    candidate = candidates[0]
    index = getattr(candidate, "index", None)
    if (getattr(candidate, "finish_reason", None) != "STOP"
            or (index is not None and (type(index) is not int or index != 0))):
        raise GoogleResponseUnavailable("google_response_incomplete")
    feedback = getattr(response, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None) not in (
        None, "BLOCK_REASON_UNSPECIFIED",
    ):
        raise GoogleResponseUnavailable("google_response_blocked")
    ratings = getattr(candidate, "safety_ratings", None)
    if ratings is not None:
        if not isinstance(ratings, list):
            raise GoogleResponseUnavailable("google_response_blocked")
        for rating in ratings:
            values = _fields(rating)
            if "blocked" in values and values["blocked"] is not False:
                raise GoogleResponseUnavailable("google_response_blocked")
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None)
    if getattr(content, "role", None) != "model" or not isinstance(parts, list) or not parts:
        raise GoogleResponseUnavailable("google_response_invalid_content")
    text = ""
    for part in parts:
        values = _fields(part)
        if (set(values) - {"text", "thought", "thought_signature"}
                or not isinstance(values.get("text"), str)
                or ("thought" in values and type(values["thought"]) is not bool)):
            raise GoogleResponseUnavailable("google_response_unsupported_part")
        if values.get("thought") is not True:
            text += values["text"]
    try:
        valid = bool(text.strip()) and len(text.encode("utf-8")) <= 65_536
    except UnicodeError:
        valid = False
    if not valid:
        raise GoogleResponseUnavailable("google_response_invalid_text")
    return text
