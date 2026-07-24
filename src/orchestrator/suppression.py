"""Editorial suppression ledger helpers for orchestrator flows."""

from __future__ import annotations

import contextlib
import contextvars
import os
import secrets
import threading

from src.editorial.scoring import EditorialScore
from src.orchestrator.common import _utc_now_iso
from src.state import MAX_SUPPRESSIONS
from src.state_schema import BotState

# One lock for EVERY suppressions append+trim (codex r2 P2): source runners
# write from worker threads, and the cap trim REPLACES the list object — an
# unsynchronized appender still holding the old reference loses its row at
# MAX_SUPPRESSIONS. Shared by triage.py's cap-suppression writer too.
_SUPPRESSIONS_LOCK = threading.Lock()


_CURRENT_SUPPRESSION_CTX: dict | None = None
_SUPPRESSION_CTX_VAR: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "theheat_suppression_ctx",
    default=None,
)


def _previous_drafts_for_event(bot_state: BotState, event_base: str) -> list[str]:
    """Find text of previous drafts for the same base event.

    For evolving events (e.g. cyclones), the event_id changes with each
    intensity tier but shares a common base like "gdacs_TC_1001270".
    Returns up to 5 most recent draft texts to avoid repeating comparisons.
    """
    drafts = bot_state.get("drafts", [])
    matches = []
    for d in drafts:
        eid = d.get("event_id", "")
        if event_base and event_base in eid:
            text = d.get("text", "")
            if text:
                matches.append(text)
    return matches[-5:]


def _near_miss_gap() -> int:
    """Max (threshold - total) gap to record. Smaller = stricter."""
    try:
        return int(os.environ.get("SUPPRESSION_NEAR_MISS_GAP", "15"))
    except (TypeError, ValueError):
        return 15


@contextlib.contextmanager
def _suppression_context(bot_state: BotState, *, source: str, run_id: str | None = None):
    """Activate suppression capture for `_should_draft()` calls inside the block."""
    global _CURRENT_SUPPRESSION_CTX
    prev = _CURRENT_SUPPRESSION_CTX
    ctx = {"bot_state": bot_state, "source": source, "run_id": run_id}
    _CURRENT_SUPPRESSION_CTX = ctx
    token = _SUPPRESSION_CTX_VAR.set(ctx)
    try:
        yield
    finally:
        _SUPPRESSION_CTX_VAR.reset(token)
        _CURRENT_SUPPRESSION_CTX = prev


def _activate_suppression_ctx(bot_state: BotState, *, source: str, run_id: str | None = None) -> None:
    """Set the suppression context for the rest of the process.

    Used at the top of each top-level run function (run_alerts, run_leaderboard,
    etc.) so all `_should_draft()` calls during the run capture suppressions.
    No auto-cleanup — relies on the bot exiting after each invocation. Tests
    should call `_clear_suppression_ctx()` between cases.
    """
    global _CURRENT_SUPPRESSION_CTX
    ctx = {"bot_state": bot_state, "source": source, "run_id": run_id}
    _CURRENT_SUPPRESSION_CTX = ctx
    _SUPPRESSION_CTX_VAR.set(ctx)


def _clear_suppression_ctx() -> None:
    """Clear the current suppression context. Mainly for tests."""
    global _CURRENT_SUPPRESSION_CTX
    _CURRENT_SUPPRESSION_CTX = None
    _SUPPRESSION_CTX_VAR.set(None)


def _score_field(score, key: str, default=None):
    if isinstance(score, dict):
        return score.get(key, default)
    return getattr(score, key, default)


def _score_int(score, key: str) -> int:
    try:
        return int(_score_field(score, key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _score_reasons(score) -> list[str]:
    raw = _score_field(score, "reasons", []) or []
    if not isinstance(raw, list):
        return [str(raw)]
    return [str(item) for item in raw]


def _record_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score: EditorialScore,
    summary: str | None,
) -> None:
    """Append an editorial-gate near-miss suppression record (stage=score_gate)."""
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    row = {
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": "score_gate",
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": _score_reasons(score),
        "summary": summary,
    }
    with _SUPPRESSIONS_LOCK:
        suppressions = bot_state.setdefault("suppressions", [])
        suppressions.append(row)
        if len(suppressions) > MAX_SUPPRESSIONS:
            bot_state["suppressions"] = suppressions[-MAX_SUPPRESSIONS:]
    from src.orchestrator import funnel as _funnel

    _funnel.record_kill(bot_state, "score_gate")


def _record_downstream_suppression(
    *,
    bot_state: BotState,
    source: str | None,
    run_id: str | None,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Append a downstream-kill suppression — a bundle that passed the
    editorial score gate but died in the two-bot pipeline (writer kill,
    fact-check rejection, or pipeline exception). Stage discriminates
    from score-gate near-misses; ``score_total`` is preserved so the
    dashboard can show "passing score 80, killed in writer".
    """
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    # Bet A A2: a rescued score's provenance must survive a downstream kill —
    # the ledger row should read "killed in <stage>; was news_boost=+8 per
    # NIFC (...)", or an operator can't tell a rescued near-miss from an
    # organically-passing signal when triaging kills.
    reasons = [kill_reason] if kill_reason else []
    # _score_reasons handles both EditorialScore objects and the serialized
    # dicts that cycle-cap/finalize kills pass in (codex A2-r2 P2).
    reasons.extend(
        r for r in _score_reasons(score) if r.startswith("news_boost=")
    )
    row = {
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": run_id,
        "source": source,
        "stage": kill_stage,  # "writer" | "safety" | "honesty_gate" | "evidence_contract" | "fact_check" | "critic" | "budget_exhausted" | "billing_cycle_abort" | "pipeline_error" | "triage_cap" | "triage_error" | "negative_cache" | "unknown"
        "event_id": event_id or None,
        "category": _score_field(score, "category"),
        "score_total": _score_int(score, "total"),
        "threshold": _score_int(score, "threshold"),
        "reasons": reasons,
        "summary": summary,
    }
    with _SUPPRESSIONS_LOCK:
        suppressions = bot_state.setdefault("suppressions", [])
        suppressions.append(row)
        if len(suppressions) > MAX_SUPPRESSIONS:
            bot_state["suppressions"] = suppressions[-MAX_SUPPRESSIONS:]
    from src.orchestrator import funnel as _funnel

    _funnel.record_kill(bot_state, kill_stage)


def _record_save_rejection(
    *,
    bot_state: BotState,
    event_id: str,
    score,
    kill_stage: str,
    kill_reason: str,
    summary: str | None,
) -> None:
    """Record a post-score draft-save gate as a suppression row."""
    if score is None:
        return
    ctx = _current_suppression_ctx()
    if ctx is None:
        return
    _record_downstream_suppression(
        bot_state=bot_state,
        source=ctx.get("source"),
        run_id=ctx.get("run_id"),
        event_id=event_id,
        score=score,
        kill_stage=kill_stage,
        kill_reason=kill_reason,
        summary=summary,
    )


def _record_triage_error_suppression(bot_state: BotState, err_text: str) -> None:
    """Append a `stage='triage_error'` row when the triage drain raises.

    Stage-level failure (not candidate-level), so there's no event_id /
    score / category. Pairs with a `source_health['triage']` update so both
    the suppression ledger and the source-health dashboard surface the
    failure.
    """
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    row = {
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": None,
        "source": "triage",
        "stage": "triage_error",
        "event_id": None,
        "category": None,
        "score_total": 0,
        "threshold": 0,
        "reasons": [err_text] if err_text else [],
        "summary": None,
    }
    with _SUPPRESSIONS_LOCK:
        suppressions = bot_state.setdefault("suppressions", [])
        suppressions.append(row)
        if len(suppressions) > MAX_SUPPRESSIONS:
            bot_state["suppressions"] = suppressions[-MAX_SUPPRESSIONS:]
    from src.orchestrator import funnel as _funnel

    _funnel.record_kill(bot_state, "triage_error")


def _record_billing_cycle_abort_suppression(
    bot_state: BotState,
    *,
    aborted_event_id: str,
    skipped: int,
) -> None:
    """Append ONE ``stage='billing_cycle_abort'`` row when the drain stops a
    cycle on its first budget_exhausted kill (economics P0 circuit breaker).

    Cycle-level, not candidate-level: the aborting candidate already has its
    own ``budget_exhausted`` row from ``_try_two_bot_draft``; rows for the
    never-attempted remainder would flood the ledger with the same fact. The
    motivating incident (2026-07-13T21:02Z) fired six paid attempts after the
    first "credit balance is too low" error because nothing owned the cycle.
    """
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    row = {
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": None,
        "source": "billing",
        "stage": "billing_cycle_abort",
        "event_id": aborted_event_id or None,
        "category": None,
        "score_total": 0,
        "threshold": 0,
        "reasons": [
            f"cycle aborted after budget_exhausted on "
            f"{aborted_event_id or 'unknown'}; "
            f"{skipped} queued candidate(s) skipped"
        ],
        "summary": None,
    }
    with _SUPPRESSIONS_LOCK:
        suppressions = bot_state.setdefault("suppressions", [])
        suppressions.append(row)
        if len(suppressions) > MAX_SUPPRESSIONS:
            bot_state["suppressions"] = suppressions[-MAX_SUPPRESSIONS:]
    from src.orchestrator import funnel as _funnel

    _funnel.record_kill(bot_state, "billing_cycle_abort")


def _should_draft(
    score: EditorialScore,
    event_id: str = "",
    *,
    summary: str | None = None,
) -> bool:
    """Decide whether an event is strong enough to enter the draft queue."""
    if score.passes:
        return True
    event_desc = f" {event_id}" if event_id else ""
    print(
        f"[score] Suppressed{event_desc}: {score.category} "
        f"{score.total} < {score.threshold} ({', '.join(score.reasons)})"
    )
    ctx = _current_suppression_ctx()
    if ctx is not None:
        gap = int(getattr(score, "threshold", 0) or 0) - int(getattr(score, "total", 0) or 0)
        if gap <= _near_miss_gap():
            _record_suppression(
                bot_state=ctx["bot_state"],
                source=ctx.get("source"),
                run_id=ctx.get("run_id"),
                event_id=event_id,
                score=score,
                summary=summary,
            )
    return False


def _current_suppression_ctx() -> dict | None:
    return _SUPPRESSION_CTX_VAR.get()


__all__ = [
    "_CURRENT_SUPPRESSION_CTX",
    "_activate_suppression_ctx",
    "_clear_suppression_ctx",
    "_current_suppression_ctx",
    "_near_miss_gap",
    "_previous_drafts_for_event",
    "_record_downstream_suppression",
    "_record_save_rejection",
    "_record_suppression",
    "_record_triage_error_suppression",
    "_score_field",
    "_score_int",
    "_score_reasons",
    "_should_draft",
    "_suppression_context",
]
