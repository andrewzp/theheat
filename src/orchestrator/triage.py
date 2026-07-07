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
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.orchestrator.finalize import MAX_DRAFTS_PER_CYCLE
from src.state import MAX_SUPPRESSIONS

if TYPE_CHECKING:
    from src.two_bot.types import TriageCandidateBundle

PER_CATEGORY_TRIAGE_CAP_DEFAULT = 2
# Pending-queue diversity gate. The triage per-category cap bounds INPUT per
# cycle but the pending queue can still drift to monoculture over many cycles
# when one source produces continuously and others produce intermittently
# (the May 2026 coral_bleaching pile-up). This cap is the structural fix —
# no more than N drafts of any one `legacy_type` may sit in pending at once.
PENDING_TYPE_CAP_DEFAULT = 3
# Pending-queue TTL — drafts older than this auto-reject so the queue self-
# cleans rather than accumulating stale signals indefinitely. The default is
# the window for FAST point-in-time signals (a single day's record), where
# posting weeks late would falsely imply recency.
PENDING_TTL_DAYS_DEFAULT = 7
# Slow continuous signals (coral/DHW) stay editorially current for the duration
# of the heat-stress event — commonly weeks. A flat 7-day TTL was discarding
# still-valid coral drafts (it swept 3 good ones while the grading routine was
# down for 12 days in May 2026), so these types get a longer window. The
# per-type pending cap (PENDING_TYPE_CAP_DEFAULT) still bounds the queue, so the
# longer window can't reintroduce a monoculture pile-up. Earlier revisions set a
# flat 7d on the (wrong) assumption it matched the DHW window; the grading
# corpus showed it doesn't.
SLOW_PENDING_TYPES = frozenset({"coral_bleaching"})
PENDING_TTL_DAYS_SLOW_DEFAULT = 21


def _per_category_cap() -> int:
    """Read per-category cap from env, falling back to default."""
    raw = os.environ.get("THEHEAT_PER_CATEGORY_CAP", "")
    try:
        v = int(raw) if raw else PER_CATEGORY_TRIAGE_CAP_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PER_CATEGORY_TRIAGE_CAP_DEFAULT


def _pending_type_cap() -> int:
    """Read pending-queue per-type cap from env, falling back to default."""
    raw = os.environ.get("THEHEAT_PENDING_TYPE_CAP", "")
    try:
        v = int(raw) if raw else PENDING_TYPE_CAP_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PENDING_TYPE_CAP_DEFAULT


def _pending_ttl_days() -> int:
    """Read pending-queue TTL (in days) from env, falling back to default."""
    raw = os.environ.get("THEHEAT_PENDING_TTL_DAYS", "")
    try:
        v = int(raw) if raw else PENDING_TTL_DAYS_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PENDING_TTL_DAYS_DEFAULT


def _pending_ttl_days_slow() -> int:
    """TTL (in days) for slow continuous signals; env-tunable, default 21."""
    raw = os.environ.get("THEHEAT_PENDING_TTL_DAYS_SLOW", "")
    try:
        v = int(raw) if raw else PENDING_TTL_DAYS_SLOW_DEFAULT
        return max(v, 1)
    except (TypeError, ValueError):
        return PENDING_TTL_DAYS_SLOW_DEFAULT


def _pending_ttl_days_for(draft_type: str) -> int:
    """Per-type TTL: slow continuous signals (coral/DHW) get the longer window,
    every other type the default. Keyed on the draft's ``type`` field."""
    if draft_type in SLOW_PENDING_TYPES:
        return _pending_ttl_days_slow()
    return _pending_ttl_days()


def _pending_count_for_type(bot_state: Any, draft_type: str) -> int:
    """Count drafts with status='pending' and matching legacy_type."""
    drafts = bot_state.get("drafts", []) or []
    return sum(
        1
        for d in drafts
        if isinstance(d, dict)
        and d.get("status") == "pending"
        and d.get("type") == draft_type
    )


def apply_pending_ttl_sweep(
    bot_state: Any,
    *,
    now: datetime | None = None,
) -> int:
    """Reject pending drafts older than the configured TTL.

    Old drafts become structurally stale — their underlying data has drifted,
    the queue stops reflecting current reality, and they crowd out fresh
    signals via the per-type cap. Auto-rejecting them keeps the queue
    actionable. Operator can re-approve from the rejected pile if a signal
    still applies.

    Mutates ``bot_state["drafts"]`` in place. Returns the count of drafts
    newly rejected this call.
    """
    if now is None:
        now = datetime.now(UTC)
    now_iso = now.isoformat().replace("+00:00", "Z")
    drafts = bot_state.get("drafts", []) or []
    rejected_count = 0
    for d in drafts:
        if not isinstance(d, dict):
            continue
        if d.get("status") != "pending":
            continue
        created_at = d.get("created_at")
        if not isinstance(created_at, str) or not created_at:
            continue
        # Per-type TTL: slow continuous signals (coral/DHW) get a longer window
        # than fast point-in-time records, so the cutoff is computed per draft.
        ttl_days = _pending_ttl_days_for(d.get("type") or "")
        cutoff_iso = (now - timedelta(days=ttl_days)).isoformat().replace("+00:00", "Z")
        # ISO-8601 strings (with trailing Z) sort lexicographically =
        # chronologically. Safer than datetime parsing — no failure mode
        # if the field has unexpected formatting.
        if created_at >= cutoff_iso:
            continue
        d["status"] = "rejected"
        d["rejected_reason"] = f"staleness_ttl_{ttl_days}d"
        d["rejected_at"] = now_iso
        rejected_count += 1
    return rejected_count


# Forecast-tense signal types: the tweet's claim is anchored to a FUTURE
# date (Open-Meteo forecast paths). Once that date has fully elapsed,
# posting would misstate an already-passed forecast as current — the exact
# class the daily-plan grader has flagged since 2026-07-01 (Basrah/Doha)
# but could never reject (no gist write path from its environment).
# Observed-record types are deliberately NOT here: a GHCN record's
# tweet_date is an observation date and may legitimately age in review.
FORECAST_TENSE_TYPES = frozenset({"absolute_extreme", "wet_bulb_extreme"})
# absolute_extreme is forecast-tense ONLY on the forecast path: GHCN emits
# an OBSERVED absolute_extreme (data_source="ghcn") whose tweet_date is an
# observation date that may legitimately age in review. The provenance
# marker has ridden review_context facts since the type shipped (#195):
# {"label": "Data source", "value": "forecast" | "ghcn"}. Types here sweep
# only on a POSITIVE forecast marker; unknown provenance never sweeps
# (fail-safe — the created_at TTL sweep still bounds those drafts at 7d).
# wet_bulb_extreme has no observed variant, so it sweeps on type alone.
PROVENANCE_CHECKED_TYPES = frozenset({"absolute_extreme"})
FORECAST_ELAPSED_GRACE_DAYS_DEFAULT = 1


def _forecast_elapsed_grace_days() -> int:
    raw = os.environ.get("THEHEAT_FORECAST_ELAPSED_GRACE_DAYS", "")
    try:
        return max(0, int(raw)) if raw else FORECAST_ELAPSED_GRACE_DAYS_DEFAULT
    except ValueError:
        return FORECAST_ELAPSED_GRACE_DAYS_DEFAULT


def _draft_has_forecast_provenance(d: dict) -> bool:
    """True when the draft's review_context positively marks the forecast path."""
    ctx = d.get("review_context")
    facts = ctx.get("facts") if isinstance(ctx, dict) else None
    if not isinstance(facts, list):
        return False
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if str(fact.get("label", "")).strip().lower() == "data source":
            return str(fact.get("value", "")).strip().lower() == "forecast"
    return False


def apply_forecast_elapsed_sweep(
    bot_state: Any,
    *,
    now: datetime | None = None,
) -> int:
    """Reject pending forecast-tense drafts whose forecast date has elapsed.

    Sibling of apply_pending_ttl_sweep: that sweep keys on created_at (age);
    this one keys on tweet_date (the claim's anchor). Provenance-aware for
    types with an observed variant (see PROVENANCE_CHECKED_TYPES).
    Recoverable — the operator can re-approve from the rejected pile.
    Mutates in place; returns the count newly rejected.
    """
    if now is None:
        now = datetime.now(UTC)
    grace = _forecast_elapsed_grace_days()
    cutoff = (now - timedelta(days=grace)).date().isoformat()
    now_iso = now.isoformat().replace("+00:00", "Z")
    rejected = 0
    for d in bot_state.get("drafts", []) or []:
        if not isinstance(d, dict) or d.get("status") != "pending":
            continue
        dtype = str(d.get("type") or "")
        if dtype not in FORECAST_TENSE_TYPES:
            continue
        if dtype in PROVENANCE_CHECKED_TYPES and not _draft_has_forecast_provenance(d):
            continue
        tweet_date = d.get("tweet_date")
        if not isinstance(tweet_date, str) or not tweet_date:
            continue
        # ISO dates compare lexicographically; strictly BEFORE the cutoff
        # date means the grace day has fully passed.
        if tweet_date >= cutoff:
            continue
        d["status"] = "rejected"
        d["rejected_reason"] = f"forecast_elapsed_{tweet_date}"
        d["rejected_at"] = now_iso
        rejected += 1
    return rejected


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _record_triage_suppression(
    bot_state: Any,
    candidate: "TriageCandidateBundle",
    *,
    cap: int,
    global_cap: int,
    reason: str,
) -> None:
    """Record a triage-cap suppression in the bot_state suppression ledger.

    Sets kill_stage="triage_cap". ``reason`` distinguishes which gate spilled
    the candidate ("per_category_cap" vs "global_cap") so dashboard
    attribution can tell apart "more coral than we promote per cron" from
    "more total signals than MAX_DRAFTS_PER_CYCLE allows". Both pin the
    relevant numeric limit into the reasons string for at-a-glance triage.
    """
    suppressions = bot_state.setdefault("suppressions", [])
    ts = _utc_now_iso()
    rand = secrets.token_hex(4)
    score = candidate.score
    score_total = int(getattr(score, "total", 0) or 0)
    category = getattr(getattr(candidate, "bundle", None), "signal_kind", None) or ""
    threshold = int(getattr(score, "threshold", 0) or 0)

    if reason == "global_cap":
        reasons_field = [f"global_cap={global_cap}"]
    elif reason == "pending_type_cap":
        reasons_field = [f"pending_type_cap={_pending_type_cap()}"]
    else:
        reasons_field = [f"per_category_cap={cap}"]

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
        "reasons": reasons_field,
        "summary": getattr(getattr(candidate, "bundle", None), "where", None) or candidate.city or None,
    })
    if len(suppressions) > MAX_SUPPRESSIONS:
        bot_state["suppressions"] = suppressions[-MAX_SUPPRESSIONS:]
    from src.orchestrator import funnel as _funnel

    _funnel.record_kill(bot_state, "triage_cap")


def select_survivors(
    bot_state: Any,
    queue: "list[TriageCandidateBundle]",
    *,
    global_cap: int = MAX_DRAFTS_PER_CYCLE,
    refill: bool = False,
) -> "list[TriageCandidateBundle]":
    """Rank, apply per-category cap, apply global cap. Returns survivors
    in writer-call order. Records spilled candidates as kill_stage=
    'triage_cap' on bot_state.

    Ranking key: (score.total DESC, created_at DESC).
    Tiebreaker on created_at is intentionally DESC (more recent wins).

    cooldown_exempt=True is a city-cooldown bypass, NOT a triage-cap bypass.
    Elite signals can lose to even more elite signals.

    ``refill=True`` (Phase C): return the FULL ranked list without applying the
    per-category / pending-type / global caps and without recording triage_cap.
    The drain's generate-and-select loop owns the stop condition and applies the
    caps SUCCESS-aware (codex must-fix #2 — caps spent on selection here would
    stop the loop reaching deeper after failed writer attempts).
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

    if refill:
        return ranked

    cap = _per_category_cap()
    pending_cap = _pending_type_cap()
    by_category: dict[str, int] = {}
    # Cache per-type pending counts so we don't re-scan bot_state.drafts
    # for every candidate. Incremented for each survivor we admit so the
    # next candidate of the same type sees the post-admit count.
    pending_counts: dict[str, int] = {}
    survivors: list["TriageCandidateBundle"] = []
    # (candidate, reason) — reason is "per_category_cap", "pending_type_cap",
    # or "global_cap".
    spilled: list[tuple["TriageCandidateBundle", str]] = []

    for i, candidate in enumerate(ranked):
        category = getattr(getattr(candidate, "bundle", None), "signal_kind", "") or ""
        used = by_category.get(category, 0)
        if used >= cap:
            spilled.append((candidate, "per_category_cap"))
            continue
        # Pending-queue diversity gate: if the pending queue already holds
        # `pending_cap` drafts of this `legacy_type`, refuse to promote
        # another one. The candidate gets logged as `pending_type_cap` so
        # the dashboard can attribute the kill to queue concentration vs
        # cycle-cap vs global-cap.
        draft_type = getattr(candidate, "legacy_type", "") or ""
        if draft_type:
            if draft_type not in pending_counts:
                pending_counts[draft_type] = _pending_count_for_type(
                    bot_state, draft_type
                )
            if pending_counts[draft_type] >= pending_cap:
                spilled.append((candidate, "pending_type_cap"))
                continue
        if len(survivors) >= global_cap:
            # Global cap already hit — all remaining spill via the global gate.
            for remaining in ranked[i:]:
                spilled.append((remaining, "global_cap"))
            break
        survivors.append(candidate)
        by_category[category] = used + 1
        if draft_type:
            # Account for the just-admitted survivor so consecutive same-type
            # candidates see the bumped count.
            pending_counts[draft_type] = pending_counts.get(draft_type, 0) + 1

    for candidate, reason in spilled:
        _record_triage_suppression(
            bot_state,
            candidate,
            cap=cap,
            global_cap=global_cap,
            reason=reason,
        )

    return survivors
