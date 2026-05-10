"""Stage 3: senior-editor fire writer."""

from __future__ import annotations

import json
import os

from src.config import WRITER_MODEL as _DEFAULT_WRITER_MODEL
from src.two_bot.prompts.writer_prompt import (
    WRITER_SYSTEM_PROMPT,
    WRITER_USER_PROMPT_TEMPLATE,
)
from src.two_bot.types import MemorySlice, StoryBundle, WriterResult
from src.two_bot.json_utils import (
    extract_json_payload as _extract_json_payload,  # noqa: F401 — re-exported for tests
    json_default as _json_default,
    loads_model_json,
    strip_markdown_fences as _strip_markdown_fences,  # noqa: F401 — re-exported for tests
)
from src.two_bot.retry import call_with_retries


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


def _parse_writer_json(raw: str) -> WriterResult:
    try:
        parsed = loads_model_json(raw, expected="object")
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
    response = call_with_retries(
        "anthropic writer",
        lambda: client.messages.create(
            model=WRITER_MODEL,
            max_tokens=1024,
            system=WRITER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ),
    )
    return response.content[0].text


def _call_google(user_prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for the Gemini writer")
    from google import genai
    from google.genai import types as genai_types

    # google-genai HttpOptions.timeout is in MILLISECONDS — see fact_check.py.
    # 180000 = 180 seconds, matching the Anthropic writer timeout for parity
    # in case the writer ever falls through to the Gemini path.
    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=180000))
    response = call_with_retries(
        "gemini writer",
        lambda: client.models.generate_content(
            model=WRITER_MODEL,
            contents=f"{WRITER_SYSTEM_PROMPT}\n\n{user_prompt}",
        ),
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
