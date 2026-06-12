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


# Twitter cap. Writer must produce tweets ≤ this many characters.
TWEET_MAX_LENGTH = 280

# Length-retry budget: 1 initial attempt + N retries. Tuned for ~3 attempts
# total. With per-call over-length probability p, P(all fail) = p^3, so even
# at p=0.2 the all-fail rate is ~0.8%. Each retry costs ~$0.07 (Sonnet
# writer call). 3-attempt cap keeps worst-case cost bounded.
LENGTH_RETRY_BUDGET = 2

# JSON-parse retry budget. Same shape as the length retry. If the model
# returns empty / non-JSON output (observed 2026-05-12 on the Nettles Is
# Florida calendar_date_low bundle three runs in a row), retry once with a
# stronger contract reminder. If that also fails, convert to a clean KILL
# in WriterResult so the dashboard records a kill_reason instead of the
# pipeline raising a ValueError. 1 retry is enough because the failure is
# typically stochastic refusal — a second sampling usually produces JSON.
JSON_PARSE_RETRY_BUDGET = 1


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
    # The writer system prompt is large (~5,700 tokens) and byte-identical
    # across every call in a cron. Marking it for ephemeral prompt caching
    # cuts input-token cost ~90% on the cached prefix for repeat calls
    # within the 5-minute TTL.
    response = call_with_retries(
        "anthropic writer",
        lambda: client.messages.create(
            model=WRITER_MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": WRITER_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_prompt}],
        ),
    )
    # response.content is a list of block types — narrow to TextBlock.
    # We don't request thinking / tool use, so the first block is always text;
    # the explicit check is for static type safety + future-proofing.
    from anthropic.types import TextBlock
    block = response.content[0]
    if not isinstance(block, TextBlock):
        raise RuntimeError(
            f"Unexpected Anthropic response block type: {type(block).__name__}"
        )
    return block.text


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
    # google-genai response.text is Optional — empty falls through to the
    # JSON parser as a parse error, which the caller handles.
    return response.text or ""


def _call_writer_provider(user_prompt: str) -> str:
    """Dispatch one writer call to the configured provider. Pure I/O — the
    retry / length-validation logic in ``write_tweet`` wraps this."""
    if WRITER_PROVIDER == "anthropic":
        return _call_anthropic(user_prompt)
    if WRITER_PROVIDER == "google":
        return _call_google(user_prompt)
    raise RuntimeError(f"Unsupported writer provider: {WRITER_PROVIDER}")


def write_tweet(
    bundle: StoryBundle,
    memory: MemorySlice,
    *,
    revision_constraint: str | None = None,
) -> WriterResult:
    """Call the configured writer model and parse a WriterResult.

    Signal-agnostic. The bundle's ``signal_kind`` and ``historical_context``
    fields tell the writer what kind of story to compose.

    **Length guarantee.** If the writer returns a tweet over
    ``TWEET_MAX_LENGTH`` (280) characters, retry up to
    ``LENGTH_RETRY_BUDGET`` times with explicit length feedback appended to
    the user prompt. If every retry still overshoots, return a KILL result
    (tweet=None) with a ``kill_reason`` describing the failure mode. This
    eliminates over-length drafts at the writer boundary — Twitter never
    sees a >280-char string from this pipeline, no matter how the model
    drifts on a given sampling.
    """

    if WRITER_PROVIDER == "unsupported_openai":
        raise NotImplementedError("OpenAI writer provider is not implemented")

    base_user_prompt = WRITER_USER_PROMPT_TEMPLATE.format(
        bundle_json=_bundle_json(bundle),
        memory_json=_memory_json(memory),
    )
    if revision_constraint:
        base_user_prompt = (
            f"{base_user_prompt}\n\n"
            f"[Revision context: {revision_constraint}]"
        )

    last_overlong_tweet: str | None = None
    last_parse_error: str | None = None
    for attempt in range(LENGTH_RETRY_BUDGET + 1):
        user_prompt = base_user_prompt
        if attempt > 0 and last_overlong_tweet is not None:
            # Declarative-only feedback — no imperative process steps that
            # could leak into strict-JSON output (see memory hook
            # feedback_prompt_json_contract).
            user_prompt = (
                f"{base_user_prompt}\n\n"
                f"[Length retry: a previous attempt produced "
                f"{len(last_overlong_tweet)} characters. The 280-character cap "
                f"is hard. Return a shorter tweet that fits, or set tweet=null "
                f"with kill_reason if no fitting version is possible.]"
            )

        # JSON-parse retry loop (inner): if the model returns empty / non-JSON,
        # retry once before bubbling up. Observed 2026-05-12 on the Nettles Is
        # Florida calendar_date_low bundle — three runs, same bundle, same
        # error, pipeline_error each time. A stochastic refusal usually
        # resolves on a second sampling.
        result: WriterResult | None = None
        for parse_attempt in range(JSON_PARSE_RETRY_BUDGET + 1):
            parse_prompt = user_prompt
            if parse_attempt > 0 and last_parse_error is not None:
                parse_prompt = (
                    f"{user_prompt}\n\n"
                    f"[JSON-output retry: the previous attempt did not return "
                    f"valid JSON. Return ONLY the JSON object specified by the "
                    f"system prompt's OUTPUT FORMAT section — no prose before "
                    f"or after, no markdown fences, no chain-of-thought. If "
                    f"there is no extraordinary angle, return tweet=null with "
                    f"a one-line kill_reason.]"
                )
            raw = _call_writer_provider(parse_prompt)
            try:
                result = _parse_writer_json(raw)
                break  # parse succeeded — exit inner loop
            except ValueError as exc:
                last_parse_error = str(exc)
                # Fall through to retry; if budget exhausted, return KILL.
        else:
            # Inner for-else: budget exhausted without break (no successful parse).
            return WriterResult(
                tweet=None,
                kill_reason=(
                    f"writer returned invalid JSON across "
                    f"{JSON_PARSE_RETRY_BUDGET + 1} attempts: {last_parse_error}"
                ),
                angle_chosen="",
                era_anchor_used=None,
                peer_comparison_used=None,
                reasoning=(
                    f"json-parse retry exhausted; last error: "
                    f"{last_parse_error or 'unknown'}"
                ),
            )

        assert result is not None  # mypy: the break above guarantees result is set

        # Kill or fits — return as-is.
        if result.tweet is None or len(result.tweet) <= TWEET_MAX_LENGTH:
            return result

        # Over-length — remember and retry.
        last_overlong_tweet = result.tweet

    # All attempts produced over-length tweets. Hard-kill with a clear
    # reason so the dashboard surfaces the failure mode rather than
    # shipping an over-length draft that Twitter would truncate.
    overlong_len = len(last_overlong_tweet) if last_overlong_tweet else 0
    return WriterResult(
        tweet=None,
        kill_reason=(
            f"writer produced over-{TWEET_MAX_LENGTH}-char tweets across "
            f"{LENGTH_RETRY_BUDGET + 1} attempts (last attempt: "
            f"{overlong_len} chars)"
        ),
        angle_chosen="",
        era_anchor_used=None,
        peer_comparison_used=None,
        reasoning=(
            f"length-cap retry exhausted; last draft started: "
            f"{last_overlong_tweet[:80]!r}..."
            if last_overlong_tweet
            else "length-cap retry exhausted"
        ),
    )


# Backwards-compat alias. The writer is signal-agnostic; legacy callers
# reference ``write_fire_tweet``.
write_fire_tweet = write_tweet
