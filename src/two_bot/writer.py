"""Stage 3: senior-editor fire writer."""

from __future__ import annotations

import datetime
import json
import os
import re

from src.config import WRITER_MODEL as _DEFAULT_WRITER_MODEL
from src.two_bot.prompts.writer_prompt import (
    WRITER_SYSTEM_PROMPT,
    WRITER_USER_PROMPT_TEMPLATE,
)
from src.two_bot.types import MemorySlice, StoryBundle, WriterResult


def _json_default(obj):
    """Serialize types json.dumps doesn't handle natively.

    Bundles built from GHCN events carry a ``signal_date`` field
    (date object) inside ``raw_signal_dump`` — added in PR #32. Without
    this hook, json.dumps raises ``TypeError: Object of type date is
    not JSON serializable`` and the entire two-bot pipeline aborts via
    the catch-all in pipeline.py, killing every GHCN draft silently.

    Coerce date/datetime to ISO 8601 strings (which is what the writer
    LLM expects to see anyway). Raise loudly on truly unknown types so
    we don't silently coerce future surprises via str().
    """
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )

WRITER_MODEL = os.environ.get("THEHEAT_WRITER_MODEL", _DEFAULT_WRITER_MODEL)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

_SUPPORTED_PREFIXES = {
    "claude-": "anthropic",
    "gemini-": "google",
}
_UNSUPPORTED_BUT_ALLOWED = ("gpt-", "o")


def _resolve_provider(model: str) -> str:
    for prefix, provider in _SUPPORTED_PREFIXES.items():
        if model.startswith(prefix):
            return provider
    if any(model.startswith(p) for p in _UNSUPPORTED_BUT_ALLOWED):
        return "unsupported_openai"
    raise RuntimeError(
        f"THEHEAT_WRITER_MODEL={model!r} does not match any supported "
        f"prefix ({', '.join(_SUPPORTED_PREFIXES)}). "
        "Set the env var to a supported model id."
    )


WRITER_PROVIDER = _resolve_provider(WRITER_MODEL)


def _bundle_json(bundle: StoryBundle) -> str:
    return json.dumps(bundle.to_dict(), sort_keys=True, default=_json_default)


def _memory_json(memory: MemorySlice) -> str:
    return json.dumps(memory.to_dict(), sort_keys=True, default=_json_default)


_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")


def _strip_markdown_fences(raw: str) -> str:
    """Strip ```json ... ``` wrappers some models emit. Kept as a
    public-ish helper so callers can compose with other cleanup.
    """
    text = raw.strip()
    text = _FENCE_OPEN_RE.sub("", text, count=1)
    text = _FENCE_CLOSE_RE.sub("", text, count=1)
    return text.strip()


def _extract_json_payload(raw: str) -> str:
    """Best-effort JSON-object extraction from a writer response.

    Sonnet 4.6 ignores the prompt's "No markdown. No code fences. No
    prose outside the JSON." instruction in two distinct ways:

    1. Wrapping in ```json ... ``` fences (run 25525862349)
    2. Emitting a chain-of-thought preamble like "Let me think about
       this carefully." or "Here's my analysis:" *before* the JSON
       object (run 25526974586)

    Strict prompting alone doesn't fix this. Defensive parsing does.

    Strategy:
    - Strip leading/trailing markdown fences first
    - Locate the first '{' and the last '}'
    - Return the substring between them (inclusive)

    The writer response is a flat object — no top-level array, no
    multiple objects — so first-{ to last-} is unambiguous even with
    nested raw_signal_dump-style dicts inside.

    If no balanced object is found, returns the cleaned text so
    json.loads fails with a clear error message that includes the
    raw response for debugging.
    """
    text = _strip_markdown_fences(raw)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last <= first:
        return text
    return text[first : last + 1]


def _parse_writer_json(raw: str) -> WriterResult:
    cleaned = _extract_json_payload(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        print(f"[two_bot.writer] Invalid JSON response: {raw}")
        raise ValueError("Writer returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Writer response must be a JSON object")
    try:
        return WriterResult(
            tweet=parsed.get("tweet"),
            kill_reason=parsed.get("kill_reason"),
            angle_chosen=parsed.get("angle_chosen") or "",
            era_anchor_used=parsed.get("era_anchor_used"),
            peer_comparison_used=parsed.get("peer_comparison_used"),
            reasoning=parsed.get("reasoning") or "",
        )
    except TypeError as exc:
        raise ValueError("Writer response is missing required fields") from exc


def _call_anthropic(user_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is required for the Anthropic writer")
    import anthropic

    # 180s (was 90s). Observed 2026-05-07 in run 25526974586:
    # every monthly_low + 1 fire bundle hit ReadTimeout under the 90s
    # cap. Sonnet 4.6's variance under load is wider than 90s; 180s is
    # well-tolerated by GitHub Actions cron headroom and prevents the
    # "drafts vanish on slow API days" failure mode.
    client = anthropic.Anthropic(api_key=api_key, timeout=180.0)
    response = client.messages.create(
        model=WRITER_MODEL,
        max_tokens=1024,
        system=WRITER_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text


def _call_google(user_prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the Gemini writer")
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=90))
    response = client.models.generate_content(
        model=WRITER_MODEL,
        contents=f"{WRITER_SYSTEM_PROMPT}\n\n{user_prompt}",
    )
    return response.text


def write_tweet(bundle: StoryBundle, memory: MemorySlice) -> WriterResult:
    """Call the configured writer model and parse a WriterResult.

    Signal-agnostic. The bundle's ``signal_kind`` and ``historical_context``
    fields tell the writer what kind of story to compose.
    """

    if WRITER_PROVIDER == "unsupported_openai":
        raise NotImplementedError("OpenAI writer provider is not implemented")

    user_prompt = WRITER_USER_PROMPT_TEMPLATE.format(
        bundle_json=_bundle_json(bundle),
        memory_json=_memory_json(memory),
    )
    if WRITER_PROVIDER == "anthropic":
        raw = _call_anthropic(user_prompt)
    elif WRITER_PROVIDER == "google":
        raw = _call_google(user_prompt)
    else:
        raise RuntimeError(f"Unsupported writer provider: {WRITER_PROVIDER}")
    return _parse_writer_json(raw)


# Backwards-compat alias. The writer is signal-agnostic; legacy callers
# reference ``write_fire_tweet``.
write_fire_tweet = write_tweet

