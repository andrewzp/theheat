"""Stage 3: senior-editor fire writer."""

from __future__ import annotations

import json
import os

from src.config import WRITER_MODEL as _DEFAULT_WRITER_MODEL
from src.two_bot.prompts.writer_prompt import (
    IMPACT_GUIDANCE,
    MULTISIGNAL_GUIDANCE,
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

# Editorial scope. @theheat is a climate-data account — its voice frames
# climate / weather / ocean / atmosphere / cryosphere signals. Purely
# geophysical events with no climate mechanism (earthquakes) are out of
# editorial scope: the writer must decline them. The live model already
# reaches this conclusion on its own, but *non-deterministically* — that whim
# flaked the daily voice-regression workflow for days (it published an
# earthquake on some samplings and killed it on others). Pinning the decision
# here makes it deterministic AND saves a paid model call per out-of-scope
# candidate. Keep this set narrow: only signal_kinds with no climate framing
# belong here. Floods, storm surge, cyclones, severe weather, etc. stay in
# scope and are NOT listed.
OUT_OF_SCOPE_SIGNAL_KINDS = frozenset({"usgs_earthquake"})

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
# Economics P2.2: on the Anthropic path this lane is now a residual safety
# net — structured outputs (WRITER_OUTPUT_SCHEMA below) constrain decoding
# to schema-valid JSON, so the lane fires only on refusal-shaped responses
# and on the Gemini fallback provider (which has no schema enforcement).
JSON_PARSE_RETRY_BUDGET = 1

# Economics P2.2: machine enforcement of the prompt's `# OUTPUT` contract
# (writer_prompt.py). Passed as `output_config.format` (GA on the pinned
# claude-sonnet-4-6; verified live 2026-07-13 in PLAN-ECONOMICS-MASTER-v3)
# so the JSON-parse retry lane stops burning paid calls on non-JSON output.
# Field-for-field this MUST stay in lockstep with _parse_writer_json and the
# prompt's OUTPUT section: same six base fields, plus `cited_impact`, which
# IMPACT_GUIDANCE asks for when a bundle carries human_impact — with
# additionalProperties:false, omitting it here would make strict decoding
# reject every impact-lane draft (Bet A A1). Required-with-null keeps the
# key always present; the parser already maps null → None.
# `maxLength` is deliberately absent: unsupported server-side, so the
# 280-char cap remains the length-retry lane's job (semantic, not schema).
WRITER_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tweet": {"type": ["string", "null"]},
        "kill_reason": {"type": ["string", "null"]},
        "angle_chosen": {"type": "string"},
        "era_anchor_used": {"type": ["string", "null"]},
        "peer_comparison_used": {"type": ["string", "null"]},
        "reasoning": {"type": "string"},
        "cited_impact": {"type": ["boolean", "null"]},
    },
    "required": [
        "tweet",
        "kill_reason",
        "angle_chosen",
        "era_anchor_used",
        "peer_comparison_used",
        "reasoning",
        "cited_impact",
    ],
    "additionalProperties": False,
}


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
    cited_impact = parsed.get("cited_impact")
    try:
        return WriterResult(
            tweet=parsed.get("tweet"),
            kill_reason=parsed.get("kill_reason"),
            angle_chosen=parsed.get("angle_chosen") or "",
            era_anchor_used=parsed.get("era_anchor_used"),
            peer_comparison_used=parsed.get("peer_comparison_used"),
            reasoning=parsed.get("reasoning") or "",
            cited_impact=cited_impact if isinstance(cited_impact, bool) else None,
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
    # max_retries=0: call_with_retries (3 attempts, billing-aware) is the
    # single transport-retry owner. The SDK default (2) stacked a second
    # transport layer under it — 3 SDK attempts inside each of the 3
    # call_with_retries attempts, up to 9 transport calls per sample before
    # the JSON/length retry lanes even started (economics P0, 2026-07-13).
    client = anthropic.Anthropic(api_key=api_key, timeout=180.0, max_retries=0)
    # The writer system prompt is large (~15.1k tokens, measured 2026-07-13
    # — an earlier "~5,700" note here was 2.6× stale) and byte-identical
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
            # Economics P2.2: constrained decoding to the writer contract.
            # On a safety refusal the output may not match the schema — the
            # existing _parse_writer_json ValueError path + JSON-retry lane
            # stay in place as the net for exactly that case.
            output_config={
                "format": {"type": "json_schema", "schema": WRITER_OUTPUT_SCHEMA}
            },
        ),
    )
    # Economics P0.6: every paid call lands in the usage ledger. The WHOLE
    # extraction sits inside the fail-open boundary (codex P2): a response
    # whose usage attribute is a raising property must never convert an
    # already-successful paid call into a pipeline failure.
    try:
        usage = getattr(response, "usage", None)
        if usage is not None:
            from src.two_bot import usage_ledger

            usage_ledger.record_usage(
                "writer",
                WRITER_MODEL,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            )
    except Exception as exc:  # noqa: BLE001 — accounting never breaks the call
        print(f"[usage_ledger] anthropic usage extraction error (ignored): {exc!r}")
    # Refusal / empty-content route (codex r1 P1): a safety refusal is a
    # SUCCESSFUL HTTP 200 whose content may be EMPTY (and, with structured
    # outputs, need not match the schema). Indexing content[0] here raised
    # IndexError → pipeline_error, bypassing the JSON-retry → clean-KILL net
    # this path advertises. Returning "" routes it into exactly that net:
    # _parse_writer_json("") raises ValueError, the parse lane retries once,
    # and an unresolved refusal becomes a clean writer KILL with a reason —
    # the same contract as the 2026-05-12 empty-output incident this lane
    # was built for.
    if getattr(response, "stop_reason", None) == "refusal" or not response.content:
        print(
            f"[two_bot.writer] Anthropic returned "
            f"{'refusal' if getattr(response, 'stop_reason', None) == 'refusal' else 'empty content'}"
            f" (stop_reason={getattr(response, 'stop_reason', None)!r})"
        )
        return ""
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
    # Economics P0.6: mirror the Anthropic capture, same fail-open boundary
    # (codex P2). Gemini token fields live on usage_metadata; unknown models
    # price at $0 in the ledger (this path is a never-used-live fallback).
    try:
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta is not None:
            from src.two_bot import usage_ledger

            usage_ledger.record_usage(
                "writer",
                WRITER_MODEL,
                input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
                cache_read_tokens=getattr(usage_meta, "cached_content_token_count", 0) or 0,
            )
    except Exception as exc:  # noqa: BLE001 — accounting never breaks the call
        print(f"[usage_ledger] gemini usage extraction error (ignored): {exc!r}")
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

    # Editorial-scope guard. Out-of-scope signals (earthquakes) are killed
    # deterministically here, before any model call — the same decision the
    # live model reaches on its own, but reliable and free. See
    # OUT_OF_SCOPE_SIGNAL_KINDS.
    if bundle.signal_kind in OUT_OF_SCOPE_SIGNAL_KINDS:
        return WriterResult(
            tweet=None,
            kill_reason=(
                f"signal_kind {bundle.signal_kind!r} is outside @theheat's "
                f"climate-data editorial scope (no climate mechanism to frame)"
            ),
            angle_chosen="",
            era_anchor_used=None,
            peer_comparison_used=None,
            reasoning=(
                "out-of-scope geophysical signal; @theheat publishes climate, "
                "weather, ocean, atmosphere, and cryosphere signals only"
            ),
        )

    if WRITER_PROVIDER == "unsupported_openai":
        raise NotImplementedError("OpenAI writer provider is not implemented")

    base_user_prompt = WRITER_USER_PROMPT_TEMPLATE.format(
        bundle_json=_bundle_json(bundle),
        memory_json=_memory_json(memory),
    )
    # Phase D: cross-signal guidance rides the USER prompt (cache-safe) only when
    # this bundle actually carries related_signals.
    if getattr(bundle, "related_signals", None):
        base_user_prompt = f"{base_user_prompt}\n\n{MULTISIGNAL_GUIDANCE}"
    # Bet A (A1): sourced-impact guidance rides the USER prompt (cache-safe)
    # only when this bundle actually carries human_impact facts.
    if getattr(bundle, "human_impact", None):
        base_user_prompt = f"{base_user_prompt}\n\n{IMPACT_GUIDANCE}"
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
