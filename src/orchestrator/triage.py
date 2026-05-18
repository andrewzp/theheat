"""Deterministic triage stage — ranks and caps candidate bundles before any LLM call.

Architecture (spec § 3):
    Phase 1: SOURCES build candidate bundles → _enqueue_candidate()
    Phase 2: TRIAGE (this module) → select_survivors()
    Phase 3: WRITE — only survivors reach _try_two_bot_draft()

Kill-switch: THEHEAT_TRIAGE_ENABLED env var. Default OFF for first PR.
When OFF, the drain step in common.py writes everything in queue order
(legacy behaviour). When ON, select_survivors() applies the full algorithm.

Per-category cap: THEHEAT_PER_CATEGORY_CAP env var. Default 2.
Global cap: MAX_DRAFTS_PER_CYCLE (imported from finalize, currently 3).
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.orchestrator.finalize import MAX_DRAFTS_PER_CYCLE

if TYPE_CHECKING:
    from src.two_bot.types import TriageCandidateBundle

PER_CATEGORY_TRIAGE_CAP_DEFAULT = 2


def _per_category_cap() -> int:
    """Read per-category cap from env, falling back to default."""
    raw = os.environ.get("THEHEAT_PER_CATEGORY_CAP", "")
    try:
        v = int(raw) if raw else PER_CATEGORY_TRIAGE_CAP_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PER_CATEGORY_TRIAGE_CAP_DEFAULT


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_triage_suppression(
    bot_state: Any,
    candidate: "TriageCandidateBundle",
    *,
    cap: int,
) -> None:
    """Record a triage-cap suppression in the bot_state suppression ledger.

    Sets kill_stage="triage_cap". Stores the per-category cap and the
    candidate's score_total so the dashboard can render attribution:
    "9 coral_bleaching candidates this cycle, 2 promoted, 7 capped."
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    score = candidate.score
    score_total = int(getattr(score, "total", 0) or 0)
    category = getattr(getattr(candidate, "bundle", None), "signal_kind", None) or ""
    threshold = int(getattr(score, "threshold", 0) or 0)

    suppressions.append({
        "id": f"supp_{ts}_{rand}",
        "ts": ts,
        "run_id": None,
        "source": candidate.source,
        "stage": "triage_cap",  # "triage_cap" — candidate ranked out by per-category or global cap
        "event_id": candidate.event_id or None,
        "category": category,
        "score_total": score_total,
        "threshold": threshold,
        "per_category_cap": cap,
        "reasons": [f"per_category_cap={cap}"],
        "summary": getattr(getattr(candidate, "bundle", None), "where", None) or candidate.city or None,
    })
    if len(suppressions) > 200:
        bot_state["suppressions"] = suppressions[-200:]


def select_survivors(
    bot_state: Any,
    queue: "list[TriageCandidateBundle]",
    *,
    global_cap: int = MAX_DRAFTS_PER_CYCLE,
) -> "list[TriageCandidateBundle]":
    """Rank, apply per-category cap, apply global cap. Returns survivors
    in writer-call order. Records spilled candidates as kill_stage=
    'triage_cap' on bot_state.

    Ranking key: (score.total DESC, created_at DESC).
    Tiebreaker on created_at is intentionally DESC (more recent wins).

    cooldown_exempt=True is a city-cooldown bypass, NOT a triage-cap bypass.
    Elite signals can lose to even more elite signals.
    """
    if not queue:
        return []

    ranked = sorted(
        queue,
        key=lambda c: (
            int(getattr(c.score, "total", 0) or 0),
            c.created_at,  # ISO-8601 string sorts lexicographically = chronologically
        ),
        reverse=True,
    )

    cap = _per_category_cap()
    by_category: dict[str, int] = {}
    survivors: list["TriageCandidateBundle"] = []
    spilled: list["TriageCandidateBundle"] = []

    for i, candidate in enumerate(ranked):
        category = getattr(getattr(candidate, "bundle", None), "signal_kind", "") or ""
        used = by_category.get(category, 0)
        if used >= cap:
            spilled.append(candidate)
            continue
        if len(survivors) >= global_cap:
            # Global cap already hit — all remaining spill.
            spilled.extend(ranked[i:])
            break
        survivors.append(candidate)
        by_category[category] = used + 1

    for candidate in spilled:
        _record_triage_suppression(bot_state, candidate, cap=cap)

    return survivors
