"""Stage 5: second-pass editorial critic.

Runs AFTER fact_check passes and acts as the final editorial gate before
a draft enters the human-approval queue. PASS/KILL only — no rewrite loop
in v1.

Architecturally distinct from the writer because:
- Different model family (Gemini 2.5 Pro vs Sonnet 4.6 writer) ⇒ different
  blindspots; Sonnet's voice failures aren't necessarily Sonnet's voice
  detection failures, but Gemini reading Sonnet output catches more.
- Sees CROSS-DRAFT context the writer doesn't: today's other pending
  drafts. Writer can self-check shipped tweets and 24h-category cooldown,
  but cannot see siblings produced in the same cron run. The critic can,
  which is how it catches template convergence.

Failure mode this prevents: 6 coral_bleaching drafts in one cron run all
opening "[Place]'s reefs have accumulated X.X°C-weeks of thermal stress
— past the Y°C-week threshold…" — each individual draft survives fact-
check, but the dashboard ends up with six tweets sharing the same shape.
The critic kills 5 of 6 and keeps the strongest one.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from src.config import CRITIC_MODEL
from src.state_schema import BotState
from src.two_bot.json_utils import json_default as _json_default, loads_model_json
from src.two_bot.prompts.critic_prompt import (
    CRITIC_SLATE_USER_PROMPT_TEMPLATE,
    CRITIC_SYSTEM_PROMPT,
    CRITIC_USER_PROMPT_TEMPLATE,
)
from src.two_bot.retry import call_with_retries
from src.two_bot.types import CriticResult, StoryBundle


# JSON-parse retry budget — mirrors the writer + fact_check constants. If
# Gemini 2.5 Pro returns empty / non-JSON / mid-truncation output, retry
# once with a stronger contract reminder before bubbling up. Without this,
# a single malformed response would surface as pipeline_error instead of
# a clean critic-stage kill. Fail-closed on exhaustion (the critic is a
# gate; block on uncertainty).
JSON_PARSE_RETRY_BUDGET = 1


def _collect_pending_today(state: BotState, *, exclude_event_id: str | None = None) -> list[dict]:
    """Pending drafts created since UTC midnight, freshest first.

    Used by the critic so it can detect template convergence inside a
    single cron run. The writer can't see its siblings; the critic can.

    ``exclude_event_id`` removes the in-flight draft's predecessor (if
    the same event re-fires within a day) from the comparison set — the
    critic should compare against OTHER events, not its own thread.
    """

    drafts = state.get("drafts", [])
    today = datetime.now(UTC).date().isoformat()
    pending_today: list[dict] = []
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        if draft.get("status") != "pending":
            continue
        created_at = draft.get("created_at", "")
        if not isinstance(created_at, str) or not created_at.startswith(today):
            continue
        if exclude_event_id and draft.get("event_id") == exclude_event_id:
            continue
        pending_today.append(draft)
    # Most recent first — the critic should see the freshest sibling
    # drafts at the top; pattern-matching gets easier when same-shape
    # entries are adjacent.
    pending_today.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return pending_today


def _format_pending_block(pending: list[dict], limit: int = 15) -> str:
    """Render pending drafts for the critic's user prompt.

    Compact one-line-per-draft form: ``[type | score N] first 160 chars``.
    Type + score tag lets the critic spot category convergence at a glance;
    truncating to 160 chars keeps prompt tokens bounded while preserving
    the shape signal (opener + first system clause is usually visible).
    """

    if not pending:
        return "(none)"
    lines: list[str] = []
    for draft in pending[:limit]:
        text = str(draft.get("text", "") or "")
        type_tag = str(draft.get("type", "") or "?")
        score = draft.get("score") or {}
        total = score.get("total") if isinstance(score, dict) else None
        score_tag = f" | score {total}" if isinstance(total, (int, float)) else ""
        preview = text[:160].replace("\n", " ").strip()
        lines.append(f"- [{type_tag}{score_tag}] {preview}")
    return "\n".join(lines)


def _format_shipped_block(shipped: list[str], limit: int = 10) -> str:
    """Render recently shipped tweets verbatim.

    Full text — not truncated — because the critic needs to detect
    distinctive phrasing recycling, and distinctive phrases can sit
    anywhere in the tweet. The volume cap (default 10) keeps the
    prompt bounded; if the bot ever ships more than 10 tweets per day
    that's a different problem (and we'd revisit the editorial bar).
    """

    if not shipped:
        return "(none)"
    return "\n".join(f"- {text}" for text in shipped[:limit] if text)


def _format_candidate_drafts_block(candidate_drafts: list[str]) -> str:
    if not candidate_drafts:
        return "(none)"
    lines: list[str] = []
    for index, draft in enumerate(candidate_drafts):
        preview = draft.replace("\n", " ").strip()
        lines.append(f"{index}. {preview}")
    return "\n".join(lines)


def _parse_critic_result(
    raw: str,
    *,
    allow_revise: bool = False,
    slate_size: int | None = None,
) -> CriticResult:
    """Parse the critic's JSON verdict into a CriticResult.

    Mirrors fact_check._parse_fact_check_json's strictness — invalid
    JSON or missing/wrong-type fields raise, and the caller (which sits
    inside pipeline.generate_draft's try/except) records the failure
    as a pipeline_error suppression so the dashboard can see it.
    """

    try:
        parsed = loads_model_json(raw, expected="object")
    except json.JSONDecodeError as exc:
        print(f"[two_bot.critic] Invalid JSON response: {raw}")
        raise ValueError("Critic returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Critic response must be a JSON object")
    if "verdict" not in parsed:
        if not isinstance(parsed.get("passed"), bool):
            raise ValueError("Critic response must include boolean passed")
        passed = parsed["passed"]
        kill_reason_raw = parsed.get("kill_reason")
        if passed:
            return CriticResult(passed=True, kill_reason=None, raw_response=raw)
        if not isinstance(kill_reason_raw, str) or not kill_reason_raw.strip():
            raise ValueError("Critic response with passed=false must include kill_reason")
        return CriticResult(
            passed=False,
            kill_reason=kill_reason_raw.strip(),
            raw_response=raw,
            verdict="KILL",
        )

    verdict_raw = parsed.get("verdict")
    if not isinstance(verdict_raw, str):
        raise ValueError("Critic response must include string verdict")
    verdict = verdict_raw.strip().upper()
    selected_index = parsed.get("selected_index")
    if selected_index is None:
        selected = None
    elif isinstance(selected_index, int):
        selected = selected_index
    else:
        raise ValueError("Critic response selected_index must be an integer or null")
    if slate_size is not None:
        if verdict == "PASS" and selected is None:
            raise ValueError("Critic slate PASS must include selected_index")
        if selected is not None and not 0 <= selected < slate_size:
            raise ValueError("Critic response selected_index out of bounds")

    if verdict == "PASS":
        return CriticResult(
            passed=True,
            kill_reason=None,
            raw_response=raw,
            verdict="PASS",
            selected_index=selected,
        )
    if verdict == "KILL":
        kill_reason_raw = parsed.get("kill_reason")
        if not isinstance(kill_reason_raw, str) or not kill_reason_raw.strip():
            raise ValueError("Critic KILL verdict must include kill_reason")
        return CriticResult(
            passed=False,
            kill_reason=kill_reason_raw.strip(),
            raw_response=raw,
            verdict="KILL",
        )
    if verdict == "REVISE":
        if not allow_revise:
            raise ValueError("REVISE not allowed for this critic call")
        instruction = parsed.get("revise_instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("Critic REVISE verdict must include revise_instruction")
        instruction = instruction.strip()
        if len(instruction) > 200:
            raise ValueError("Critic revise_instruction exceeds 200 chars")
        return CriticResult(
            passed=False,
            kill_reason=None,
            raw_response=raw,
            verdict="REVISE",
            revise_instruction=instruction,
        )
    raise ValueError("Critic response verdict must be PASS, KILL, or REVISE")


def _parse_critic_json(raw: str) -> tuple[bool, str | None]:
    """Legacy compatibility parser returning ``(passed, kill_reason)``."""

    result = _parse_critic_result(raw)
    if result.verdict == "REVISE":
        raise ValueError("Legacy critic parser does not accept REVISE")
    return result.passed, result.kill_reason


def _call_gemini(
    draft_text: str,
    bundle: StoryBundle,
    pending_today: list[dict],
    shipped_recent: list[str],
    *,
    retry_suffix: str = "",
    allow_revise: bool = False,
    candidate_drafts: list[str] | None = None,
) -> str:
    """Call Gemini 2.5 Pro with the critic prompt.

    Network-level retries handled by call_with_retries; JSON-parse retries
    handled by the caller (critic_review) via ``retry_suffix``, which
    appends a contract-reinforcement message to the user prompt on the
    second attempt.

    Mirrors fact_check._call_gemini's HttpOptions timeout posture exactly
    — timeout=90000 is MILLISECONDS (90s). The fact_check.py comment
    documents why a bare integer like 90 silently breaks the call in
    <300ms; this module replicates the safe value rather than re-import.
    """

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required for editorial critic")
    from google import genai
    from google.genai import types as genai_types

    # google-genai HttpOptions.timeout is MILLISECONDS — see fact_check.py
    # for the 4-day production outage that taught us this. 90000 = 90s.
    client = genai.Client(api_key=api_key, http_options=genai_types.HttpOptions(timeout=90000))

    if candidate_drafts is None:
        user_prompt = CRITIC_USER_PROMPT_TEMPLATE.format(
            draft_text=draft_text,
            bundle_json=json.dumps(bundle.to_dict(), sort_keys=True, default=_json_default),
            pending_count=len(pending_today),
            pending_drafts_block=_format_pending_block(pending_today),
            shipped_count=len(shipped_recent),
            shipped_tweets_block=_format_shipped_block(shipped_recent),
            revision_mode=(
                "REVISE is available for one narrow craft fix."
                if allow_revise
                else "REVISE is not available; only PASS or KILL."
            ),
        )
    else:
        user_prompt = CRITIC_SLATE_USER_PROMPT_TEMPLATE.format(
            candidate_count=len(candidate_drafts),
            candidate_drafts_block=_format_candidate_drafts_block(candidate_drafts),
            bundle_json=json.dumps(bundle.to_dict(), sort_keys=True, default=_json_default),
            pending_count=len(pending_today),
            pending_drafts_block=_format_pending_block(pending_today),
            shipped_count=len(shipped_recent),
            shipped_tweets_block=_format_shipped_block(shipped_recent),
        )
    if retry_suffix:
        user_prompt = f"{user_prompt}{retry_suffix}"
    response = call_with_retries(
        "gemini critic",
        lambda: client.models.generate_content(
            model=CRITIC_MODEL,
            contents=f"{CRITIC_SYSTEM_PROMPT}\n\n{user_prompt}",
        ),
    )
    return response.text or ""


def critic_review(
    draft_text: str,
    bundle: StoryBundle,
    state: BotState,
    *,
    shipped_recent: list[str] | None = None,
    allow_revise: bool = False,
) -> CriticResult:
    """Run the editorial critic against a fact-check-passed draft.

    Returns a CriticResult with PASS/KILL + reason. Caller is responsible
    for wrapping in a try/except — exceptions propagate so the existing
    pipeline_error suppression path surfaces critic failures in the
    dashboard rather than silently letting drafts through.

    ``shipped_recent`` is normally pulled from the same MemorySlice the
    writer saw (so the critic and writer judge against the same shipped
    library). Default ``None`` ⇒ falls back to state.memory.shipped_tweets,
    which is correct for the integration but optional for unit tests.
    """

    pending_today = _collect_pending_today(state, exclude_event_id=bundle.event_id)

    if shipped_recent is None:
        memory_block = state.get("memory") or {}
        shipped_rows = memory_block.get("shipped_tweets", []) if isinstance(memory_block, dict) else []
        shipped_recent = [
            str(row.get("tweet_text") or "")
            for row in shipped_rows[:10]
            if isinstance(row, dict)
        ]

    # JSON-parse retry loop — mirrors writer + fact_check. Gemini 2.5 Pro
    # is much more reliable than Flash on structured output, but stochastic
    # mid-truncation / refusal still happens (~1 in 50 calls observed in
    # 2026-05-15 production: Somalia coral_bleaching with "ValueError:
    # invalid JSON: Expecting ',' delimiter line 7 col 384"). Without
    # this retry the malformed response surfaces as pipeline_error;
    # with it, a second sampling usually unblocks.
    last_parse_error: str | None = None
    raw = ""
    for parse_attempt in range(JSON_PARSE_RETRY_BUDGET + 1):
        retry_suffix = ""
        if parse_attempt > 0 and last_parse_error is not None:
            revise_example = (
                ' or {"verdict": "REVISE", "kill_reason": null, '
                '"revise_instruction": "<declarative note under 200 chars>", '
                '"selected_index": null}'
                if allow_revise
                else ""
            )
            retry_suffix = (
                "\n\n[JSON-output retry: the previous attempt did not return "
                "valid JSON. Return ONLY the JSON object specified above — "
                "no prose before or after, no markdown fences, no chain-of-"
                'thought. Use {"verdict": "PASS", "kill_reason": null, '
                '"revise_instruction": null, "selected_index": null} or '
                '{"verdict": "KILL", "kill_reason": "<short reason>", '
                '"revise_instruction": null, "selected_index": null}'
                f"{revise_example}.]"
            )
        raw = _call_gemini(
            draft_text, bundle, pending_today, shipped_recent,
            retry_suffix=retry_suffix,
            allow_revise=allow_revise,
        )
        try:
            return _parse_critic_result(raw, allow_revise=allow_revise)
        except ValueError as exc:
            last_parse_error = str(exc)

    # Retry budget exhausted — fail-closed with a structured KILL so the
    # suppression dashboard categorizes this as a critic-stage kill (not
    # pipeline_error). The draft is blocked; the human-approval queue
    # never sees something the critic couldn't read.
    return CriticResult(
        passed=False,
        kill_reason=(
            f"critic returned invalid JSON across "
            f"{JSON_PARSE_RETRY_BUDGET + 1} attempts: {last_parse_error}"
        ),
        raw_response="(json-parse retry exhausted)",
    )


def critic_select_slate(
    candidate_drafts: list[str],
    bundle: StoryBundle,
    state: BotState,
    *,
    shipped_recent: list[str] | None = None,
) -> CriticResult:
    """Select the strongest writer sample or KILL the whole slate."""

    pending_today = _collect_pending_today(state, exclude_event_id=bundle.event_id)
    if shipped_recent is None:
        memory_block = state.get("memory") or {}
        shipped_rows = memory_block.get("shipped_tweets", []) if isinstance(memory_block, dict) else []
        shipped_recent = [
            str(row.get("tweet_text") or "")
            for row in shipped_rows[:10]
            if isinstance(row, dict)
        ]

    last_parse_error: str | None = None
    for parse_attempt in range(JSON_PARSE_RETRY_BUDGET + 1):
        retry_suffix = ""
        if parse_attempt > 0 and last_parse_error is not None:
            retry_suffix = (
                "\n\n[JSON-output retry: the previous attempt did not return "
                "valid JSON. Return ONLY the JSON object specified above — "
                "no prose before or after, no markdown fences.]"
            )
        raw = _call_gemini(
            "",
            bundle,
            pending_today,
            shipped_recent,
            retry_suffix=retry_suffix,
            candidate_drafts=candidate_drafts,
        )
        try:
            return _parse_critic_result(raw, slate_size=len(candidate_drafts))
        except ValueError as exc:
            last_parse_error = str(exc)

    return CriticResult(
        passed=False,
        kill_reason=(
            f"critic returned invalid JSON across "
            f"{JSON_PARSE_RETRY_BUDGET + 1} attempts: {last_parse_error}"
        ),
        raw_response="(json-parse retry exhausted)",
        verdict="KILL",
    )
