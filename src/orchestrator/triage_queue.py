"""Triage queue helpers for source-runner candidates.

Negative-cache queue partition/refill handling reused from PR #464,
2b70565a44faaecef4c2c818ca5f89a1841e799f; narrowed P08 disposition below.
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from src.orchestrator.candidate_budget import CandidateBudget, writer_started
from src.orchestrator.common import _utc_now_iso
from src.orchestrator.suppression import (
    _current_suppression_ctx,
    _record_billing_cycle_abort_suppression,
    _record_downstream_suppression,
    _record_triage_error_suppression,
)
from src.orchestrator.telemetry import _bump_run_drafted, _bump_source_field_in_run, _record_source_run
from src.state_schema import BotState

if TYPE_CHECKING:
    from src.two_bot.types import TriageCandidateBundle

_TRIAGE_QUEUE_LOCK = threading.Lock()
# GDACS-only exact-repeat admission: live queued candidate -> internal intake
# identity (capture, exact source key, projection). Process-local and transient;
# an entry dies with its candidate and never reaches a bundle, review context,
# prompt or stored state. Guarded by _TRIAGE_QUEUE_LOCK.
_GDACS_INTAKE: dict[int, tuple[str, str, str]] = {}


def _triage_enabled() -> bool:
    """Return True when THEHEAT_TRIAGE_ENABLED=1.

    Default is OFF (returns False) for the first PR so behaviour on land
    is ZERO change. Flip to ON after first source migration.
    """
    return os.environ.get("THEHEAT_TRIAGE_ENABLED", "0") == "1"


def _enqueue_candidate(bot_state: BotState, candidate: "TriageCandidateBundle") -> None:
    """Append a TriageCandidateBundle to the per-cycle triage queue.

    Source runners call this instead of _try_two_bot_draft() once migrated.
    The queue lives at bot_state['_triage_queue'] and is drained at end of
    cycle by _drain_and_write_triage_queue().

    The '_' prefix is NOT a transient convention in this codebase — the
    queue must be explicitly excluded from sqlite persistence (see
    sqlite_store._METADATA_JSON_KEYS) and popped at entry of run_alerts.
    """
    # Cast to plain dict: _triage_queue is a transient key not declared in
    # BotState TypedDict (it's excluded from sqlite persistence intentionally).
    with _TRIAGE_QUEUE_LOCK:
        state_dict: dict = cast(dict, bot_state)
        queue = state_dict.setdefault("_triage_queue", [])
        queue.append(candidate)


def _enqueue_story_candidate(
    bot_state: BotState,
    *,
    bundle,
    score,
    source: str,
    legacy_type: str,
    event_id: str,
    review_context: dict,
    city: str = "",
    tweet_date: str = "",
    cooldown_exempt: bool = False,
    draft_metadata: dict | None = None,
    on_draft_success: Callable[[], None] | None = None,
    annual_cap_check: Callable[[], bool] | None = None,
    intake_identity: tuple[str, str, str] | None = None,
    admission_out: dict | None = None,
) -> bool:
    """Audit and enqueue one writer candidate.

    This is the source-runner boundary. Sources collect facts, build a
    StoryBundle, and submit it here. Only the drain step may later call the
    writer pipeline for triage survivors.

    GDACS alone passes ``intake_identity``: an exact repeat of a pending row
    from the same returned capture is reused, not queued again. Returns True
    only for a new queue row; ``admission_out`` records the disposition.
    """
    from src.two_bot.evidence_contract import audit_story_bundle, evidence_rejection_details
    from src.two_bot.types import TriageCandidateBundle

    out = admission_out if admission_out is not None else {}
    from src.data.fire_identity import legacy_history_reason
    fire_hold = legacy_history_reason(bot_state, event_id)
    if fire_hold:
        print(f"[triage] Fire history hold: {fire_hold}")
        out["disposition"] = "refused_history"
        return False
    audit = audit_story_bundle(bundle)
    error_codes = [issue.code for issue in audit.issues if issue.severity == "error"]
    if error_codes:
        out["disposition"] = "refused_evidence"
        ctx = _current_suppression_ctx() or {}
        _record_downstream_suppression(
            bot_state=bot_state,
            source=source,
            run_id=ctx.get("run_id"),
            event_id=event_id,
            score=score,
            kill_stage="evidence_contract",
            kill_reason="; ".join(f"{issue.code} ({issue.field}): {issue.message}" for issue in audit.issues if issue.severity == "error"),
            summary=getattr(bundle, "where", None) or city or None,
            evidence_readiness=evidence_rejection_details(bundle, audit),
        )
        return False

    candidate = TriageCandidateBundle(
        bundle=bundle,
        score=score,
        event_id=event_id,
        source=source,
        review_context=review_context,
        city=city,
        tweet_date=tweet_date,
        cooldown_exempt=cooldown_exempt,
        legacy_type=legacy_type,
        created_at=_utc_now_iso(),
        draft_metadata=draft_metadata,
        on_draft_success=on_draft_success,
        annual_cap_check=annual_cap_check,
    )
    if intake_identity is None:
        _enqueue_candidate(bot_state, candidate)
    elif not _admit_gdacs_intake(bot_state, candidate, intake_identity, out):
        return False
    out["disposition"] = "new"
    # Rolling registry of everything the bot detected, for the news-gap watch
    # ("the world reported X — did our sensors even see it?"). Never raises.
    from src import state as _state

    _state.record_candidate_observation(
        bot_state,
        event_id=event_id,
        category=str(getattr(bundle, "signal_kind", "") or ""),
        legacy_type=legacy_type,
        city=city,
        where=str(getattr(bundle, "where", "") or ""),
    )
    return True


def _admit_gdacs_intake(bot_state: BotState, candidate: "TriageCandidateBundle",
                        identity: tuple[str, str, str], out: dict) -> bool:
    """Decide and append in one hold of the existing queue lock.

    Only an identical (capture, source key, projection) still pending in this
    state's queue is an exact repeat. A pending row for the same source key
    from a different projection is counted, not merged: existing event rules
    decide between them downstream.
    """
    with _TRIAGE_QUEUE_LOCK:
        queue = cast(dict, bot_state).setdefault("_triage_queue", [])
        pending = [_GDACS_INTAKE[id(row)] for row in queue if id(row) in _GDACS_INTAKE]
        if identity in pending:
            out["disposition"] = "reused"
            return False
        out["pending_disagreements"] = sum(
            1 for other in pending if other[1] == identity[1] and other[2] != identity[2])
        queue.append(candidate)
        _GDACS_INTAKE[id(candidate)] = identity
    weakref.finalize(candidate, _GDACS_INTAKE.pop, id(candidate), None)
    return True


def _draft_kwargs_for(candidate: "TriageCandidateBundle") -> dict:
    kwargs: dict = {
        "legacy_type": candidate.legacy_type,
        "event_id": candidate.event_id,
        "review_context": candidate.review_context,
    }
    if candidate.city:
        kwargs["city"] = candidate.city
    if candidate.tweet_date:
        kwargs["tweet_date"] = candidate.tweet_date
    if candidate.cooldown_exempt:
        kwargs["cooldown_exempt"] = candidate.cooldown_exempt
    if candidate.draft_metadata:
        kwargs["draft_metadata"] = candidate.draft_metadata
    return kwargs


def _abort_cycle_on_billing(
    bot_state: BotState,
    current_run: dict | None,
    funnel_sink: dict | None,
    remaining: list,
    aborted_event_id: str,
    *,
    bump_triaged_out: bool,
) -> None:
    """Cycle-level billing circuit breaker (economics P0).

    The per-call breaker (``retry.py``) stops retrying ONE candidate the
    moment the provider says the balance is empty; this stops the CYCLE.
    On 2026-07-13T21:02Z the drain fired six paid attempts (six distinct
    request_ids) after the first "credit balance is too low" error because
    each queued candidate independently re-discovered the same dead balance.
    Records one stage-level suppression; when funnel telemetry is on, the
    never-attempted remainder is marked ``billing_abort`` so the slate view
    explains why those candidates have no writer outcome.

    ``bump_triaged_out`` keeps ``triage_cut = triaged_in - triaged_out``
    exact in both drains (codex r4 P2): a billing-skipped candidate exited
    triage via billing, not an editorial cut, so it must be counted in
    ``triaged_out`` — but the legacy loop already counted every survivor
    there up front, so only the refill loop (which counts per attempt)
    passes True.
    """
    print(
        f"[triage] billing circuit breaker: budget exhausted on "
        f"{aborted_event_id or 'unknown'}; aborting cycle "
        f"({len(remaining)} queued candidate(s) skipped)"
    )
    # Trip the cycle-scoped latch (codex r2 P1): later drains in this SAME
    # cli run (leaderboard after alerts in `both` mode) skip their slates
    # instead of re-probing the dead balance at one paid call each. A
    # transient '_' key: _merge_state drops non-MERGE_SPEC keys on write and
    # sqlite persists only listed keys, so the latch lives exactly one
    # process — the next cron re-probes with a single attempt by design.
    cast(dict, bot_state)["_billing_exhausted_latch"] = True
    _record_billing_cycle_abort_suppression(
        bot_state,
        aborted_event_id=aborted_event_id,
        skipped=len(remaining),
    )
    # A green workflow must not read as a healthy application run: the existing
    # run/source-health fields carry the billing hold (fixed code, no provider text).
    _record_generation_hold(
        bot_state, current_run, code="provider_billing_exhausted", error_class="provider_billing",
        held=len(remaining), details={"aborted_event_id": aborted_event_id or None},
    )
    # Volume telemetry (codex r3/r4 P2): billing-skipped candidates are
    # visible as billing_aborted and — where not already counted — leave the
    # triage_cut denominator via triaged_out, so an outage never reads as an
    # editorial cap and real editorial cuts stay visible.
    for skipped_candidate in remaining:
        _bump_source_field_in_run(current_run, skipped_candidate.source, "billing_aborted")
        if bump_triaged_out:
            _bump_source_field_in_run(current_run, skipped_candidate.source, "triaged_out")
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        for skipped_candidate in remaining:
            # Never overwrite a resolved terminal (codex P1): duplicate
            # event_ids are expected in the ranked queue, and a candidate
            # that already drafted / killed must keep its true outcome.
            if skipped_candidate.event_id in funnel_sink.get("_slate_terminal", {}):
                continue
            _funnel.record_slate_terminal(
                funnel_sink, skipped_candidate.event_id, "billing_abort"
            )


def _record_generation_hold(bot_state: BotState, current_run: dict | None, *, code: str,
                            error_class: str, held: int, details: dict) -> None:
    """One partial ``generation`` run row for an operation-level provider hold."""
    _record_source_run(
        current_run, bot_state, "generation", time.perf_counter(), status="partial_failure",
        error=code, error_class=error_class, note=f"{code}: {held} queued candidate(s) held",
        details={"code": code, "held": held, **details},
    )


def _hold_on_provider_access(
    bot_state: BotState,
    current_run: dict | None,
    funnel_sink: dict | None,
    remaining: list,
    budget: CandidateBudget,
    preflight: object,
    *,
    bump_triaged_out: bool,
) -> None:
    """Stop the operation after a deterministic prerequisite refusal.

    Provider prerequisites are process-wide: every later candidate in this
    operation would fail the same preflight. Hold them instead of re-running
    generation for each; record only stage names and fixed reason codes.
    """
    rows = preflight.get("blocked_stages") if isinstance(preflight, dict) else None
    blocked = [{"stage": str(row.get("stage")), "reason": str(row.get("reason"))}
               for row in (rows if isinstance(rows, list) else []) if isinstance(row, dict)][:8]
    print(f"[triage] missing required provider access; holding {len(remaining)} candidate(s) with no further attempts")
    for candidate in remaining:
        if bump_triaged_out:
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        for candidate in remaining:
            if candidate.event_id not in funnel_sink.get("_slate_terminal", {}):
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "provider_preflight")
    budget.hold(len(remaining))
    _record_generation_hold(
        bot_state, current_run, code="provider_access_missing", error_class="provider_prerequisite",
        held=len(remaining), details={"blocked_stages": blocked, **budget.summary()},
    )


class _SelectionInvalid(ValueError):
    """A selector result the drain cannot trust; a fixed code, never candidate text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _validated_selection(selected, pool: list, *, cap: int | None) -> list:
    """Accept only rows the drain itself queued, at most as often as queued, within the cap.

    Anything else holds the selection: a selector cannot nominate an equal-looking
    copy, a foreign object, a row more often than it was queued, or more rows than
    its cap allows.
    """
    if type(selected) is not list:
        raise _SelectionInvalid("selector_result_not_list")
    # A queue may hold repeated copies of one row; a selection may not exceed them.
    available = Counter(id(candidate) for candidate in pool)
    for candidate in selected:
        if id(candidate) not in available:
            raise _SelectionInvalid("selector_out_of_slate")
        if available[id(candidate)] == 0:
            raise _SelectionInvalid("selector_duplicate_candidate")
        available[id(candidate)] -= 1
    if cap is not None and len(selected) > cap:
        raise _SelectionInvalid("selector_over_cap")
    return selected


def _hold_operation(
    bot_state: BotState,
    current_run: dict | None,
    funnel_sink: dict | None,
    held: list,
    budget: CandidateBudget,
    *,
    note: str,
    error: str,
    terminal: str = "triage_error",
) -> int:
    """Visible zero-writer hold for one failed selection or refused configuration.

    No other event is selected, no error is cleared and the limit is not raised.
    The existing ``triage_error`` suppression and ``source_health['triage']``
    remain; a ``triage`` run row with ``partial_failure`` keeps the application
    run partial even when the workflow itself exits green.
    """
    print(f"[triage] {note}: holding {len(held)} candidate(s) with zero writer attempts")
    _record_triage_error_suppression(bot_state, error)
    for candidate in held:
        # Held, not editorially cut: keep triage_cut = triaged_in - triaged_out exact.
        _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        for candidate in held:
            if candidate.event_id not in funnel_sink.get("_slate_terminal", {}):
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, terminal)
    budget.hold(len(held))
    _record_source_run(
        current_run, bot_state, "triage", time.perf_counter(), status="partial_failure",
        triaged_in=len(held), error=error, error_class="selection_hold",
        note=f"{note}: zero writer attempts; {len(held)} candidate(s) held",
        details={"code": note, "writer_attempts": 0, **budget.summary()},
    )
    return 0


def _settle_attempt(budget: CandidateBudget, key: str, drafted: bool, result: dict,
                    current_run: dict | None, candidate: "TriageCandidateBundle", *, counted: bool) -> None:
    """Keep a started attempt's slot; return it only on an explicit pre-writer report.

    A cache hit or deterministic refusal inside the dispatch made no paid
    attempt: its slot and its ``writer_attempted`` count are returned, and the
    budget records it as ``refused_before_writer``.
    """
    started = writer_started(drafted, result)
    budget.settle(key, writer_started=started)
    if not started and counted:
        _bump_source_field_in_run(current_run, candidate.source, "writer_attempted", -1)


def _record_negcache_kill_if_eligible(
    bot_state: BotState, candidate: "TriageCandidateBundle", cand_result: dict
) -> None:
    """Record an explicit model evidence judgment once on either queue path.

    The pipeline owns the default-deny scope/code disposition. Generated-text,
    context, contract and infrastructure failures cannot arm this cache.
    Direct dispatch may already have recorded the verdict; the shared helper
    prevents counting the same attempt again.
    """
    from src.two_bot.negative_cache import record_result
    record_result(bot_state, candidate.event_id, candidate.bundle, cand_result)


def _refill_drain(
    bot_state: BotState,
    current_run: dict | None,
    queue: list,
    *,
    defer_callbacks: list | None = None,
    funnel_sink: dict | None = None,
    generation_client=None,
    candidate_budget: CandidateBudget | None = None,
) -> int:
    """Phase C generate-and-select loop (THEHEAT_REFILL_ENABLED=1).

    Ranks the whole queue, then walks it attempting DISTINCT candidates until it
    reaches the per-cycle target of SUCCESSFUL drafts (or the queue / attempt
    budget is exhausted). Deterministic cooldown/dedup runs as a $0 pre-writer
    predicate; the per-category / pending-type / annual caps are enforced
    SUCCESS-aware (codex must-fix #2) so failed writer attempts don't burn cap
    slots and the loop can reach deeper. Returns the number of drafts written.

    on_draft_success callbacks fire INLINE here (not deferred): the loop stops at
    the target and the prune cap equals the target, so no loop-produced draft is
    ever pruned — firing inline keeps annual counts live so a candidate's
    ``annual_cap_check`` reflects this-cycle successes (codex must-fix #3).
    ``defer_callbacks`` is accepted for signature parity but unused.
    """
    from src.orchestrator import caps as _caps
    from src.orchestrator import common as _common
    from src.orchestrator import funnel as _funnel
    from src.orchestrator import triage as _triage
    from src.orchestrator.draft_save import can_draft_candidate
    from src.two_bot import negative_cache as _negcache

    # Economics P1.3: sweep TTL-expired negative-cache entries once per drain
    # so the skip predicate below only ever consults live entries.
    _negcache.prune(bot_state)

    budget = candidate_budget if candidate_budget is not None else CandidateBudget.for_operation("drain")
    # A failed or untrustworthy ranking holds the slate with zero writer calls;
    # walking the raw queue order instead would buy events nobody ranked.
    try:
        ranked = _triage.select_survivors(bot_state, queue, refill=True)
    except Exception as exc:  # noqa: BLE001
        return _hold_operation(bot_state, current_run, funnel_sink, list(queue), budget,
                               note="selector_unavailable", error=str(exc)[:200])
    try:
        ranked = _validated_selection(ranked, queue, cap=len(queue))
    except _SelectionInvalid as exc:
        return _hold_operation(bot_state, current_run, funnel_sink, list(queue), budget,
                               note="selector_invalid", error=exc.code)

    target = _caps.drafts_target_per_cycle()
    max_attempts = _caps.refill_max_attempts(target)
    per_cat_cap = _triage._per_category_cap()
    pending_cap = _triage._pending_type_cap()
    country_cap = _triage._per_country_cap()

    success_by_category: dict[str, int] = {}
    success_by_country: dict[str, int] = {}
    pending_by_type: dict[str, int] = {}
    attempted_event_ids: set[str] = set()
    # Economics P1.3 (codex r10): a $0 cache skip must not consume the
    # event's paid slot for the cycle — a later same-event row with CHANGED
    # facts deserves its attempt (the changed-facts-reopening invariant).
    # Cache skips are therefore tracked per FINGERPRINT: an identical-facts
    # sibling falls to duplicate_draft; different facts continue down the
    # predicate chain (their own cache check misses on the new sha).
    negcache_skipped_sha: dict[str, str] = {}

    ctx = _current_suppression_ctx() or {}
    run_id = ctx.get("run_id")
    sink_active = funnel_sink is not None

    def _pre_writer_kill(candidate: "TriageCandidateBundle", stage: str, reason: str) -> None:
        # $0 LLM — show in the funnel as a pre-writer kill at the specific stage.
        _record_downstream_suppression(
            bot_state=bot_state,
            source=candidate.source,
            run_id=run_id,
            event_id=candidate.event_id,
            score=candidate.score,
            kill_stage=stage,
            kill_reason=reason,
            summary=getattr(candidate.bundle, "where", None) or candidate.city or None,
        )
        # First terminal wins (codex P1.3 r4 P2, mirroring the billing-abort
        # rule): record_slate_terminal is last-write-wins, so a duplicate
        # queue row's later kill (e.g. duplicate_draft after a
        # negative_cache skip) must not overwrite the event's true outcome.
        # The suppression row above still records every kill.
        if funnel_sink is not None and candidate.event_id not in funnel_sink.get(
            "_slate_terminal", {}
        ):
            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, stage)

    def _cut(candidate: "TriageCandidateBundle", reason: str) -> None:
        _triage._record_triage_suppression(
            bot_state, candidate, cap=per_cat_cap, global_cap=target, reason=reason,
        )
        # First terminal wins here too (codex P1.3 r5 P2): once the ceiling
        # is reached, a trailing duplicate of an event that already resolved
        # (e.g. negative_cache) must not have its terminal overwritten with
        # triage_cap.
        if funnel_sink is not None and candidate.event_id not in funnel_sink.get(
            "_slate_terminal", {}
        ):
            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")

    def _budget_cut(candidate: "TriageCandidateBundle") -> None:
        # The operation's candidate attempts are spent: refill cannot buy more.
        _triage._record_triage_suppression(
            bot_state, candidate, cap=per_cat_cap, global_cap=budget.limit or 0, reason="candidate_budget",
        )
        budget.hold()
        if funnel_sink is not None and candidate.event_id not in funnel_sink.get(
            "_slate_terminal", {}
        ):
            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")

    drafted_count = 0
    queued_count = 0
    attempts = 0
    for idx, candidate in enumerate(ranked):
        if generation_client is not None and (candidate.on_draft_success is not None or candidate.annual_cap_check is not None):
            _pre_writer_kill(candidate, "generation_start", "async source callbacks are not supported")
            continue
        if drafted_count + queued_count >= target or attempts >= max_attempts:
            _cut(candidate, "global_cap")
            continue
        if budget.exhausted():
            _budget_cut(candidate)
            continue

        # Distinct candidates only: never spend a 2nd writer call on an event_id we
        # already attempted this cycle (the first attempt may have critic-killed, so
        # can_draft_candidate wouldn't catch it). (codex)
        if candidate.event_id and candidate.event_id in attempted_event_ids:
            _pre_writer_kill(candidate, "duplicate_draft", "pre-writer: duplicate event in slate")
            continue
        budget_key = CandidateBudget.key_for(candidate)
        if budget.seen(budget_key):
            # An earlier drain of this same operation already handled the event.
            _pre_writer_kill(candidate, "duplicate_draft", "pre-writer: event already handled this operation")
            continue
        # A cache-skipped event blocks only IDENTICAL facts (codex r10):
        # same fingerprint → duplicate_draft (not a second savings-inflating
        # negative_cache row, codex r3); changed facts fall through — their
        # own cache check below misses on the new sha and the paid attempt
        # proceeds.
        if (
            candidate.event_id
            and candidate.event_id in negcache_skipped_sha
            and _negcache.bundle_fingerprint(candidate.bundle, bot_state)
            == negcache_skipped_sha[candidate.event_id]
        ):
            _pre_writer_kill(candidate, "duplicate_draft", "pre-writer: duplicate event in slate")
            continue

        category = getattr(getattr(candidate, "bundle", None), "signal_kind", "") or ""
        draft_type = getattr(candidate, "legacy_type", "") or ""

        # Diversity caps — counted against SUCCESSES, not selections.
        if success_by_category.get(category, 0) >= per_cat_cap:
            _cut(candidate, "per_category_cap")
            continue
        if draft_type:
            if draft_type not in pending_by_type:
                pending_by_type[draft_type] = _triage._pending_count_for_type(bot_state, draft_type)
            if pending_by_type[draft_type] >= pending_cap:
                _cut(candidate, "pending_type_cap")
                continue

        country = _triage._candidate_country_key(candidate) if country_cap > 0 else ""
        if country_cap > 0 and country and success_by_country.get(country, 0) >= country_cap:
            _cut(candidate, "per_country_cap")
            continue

        # Annual-cap re-check at admit time (codex must-fix #3) via the source's own
        # cap predicate against LIVE state. Prior successes' callbacks fired inline,
        # so this reflects this-cycle drafts and keys the cap correctly (event-date
        # year, per-index counter) where a static legacy_type map could not.
        if candidate.annual_cap_check is not None:
            try:
                capped = bool(candidate.annual_cap_check())
            except Exception as exc:  # noqa: BLE001 — a broken check must not crash the cron
                print(f"[triage] annual_cap_check error for {candidate.source}: {exc!r}")
                capped = False
            if capped:
                _pre_writer_kill(candidate, "annual_cap", "pre-writer: annual cap reached in-cycle")
                continue

        # Deterministic pre-writer predicate ($0 LLM) — cooldown / dedup / dup-event.
        can_draft, reason = can_draft_candidate(bot_state, candidate)
        if not can_draft:
            _pre_writer_kill(candidate, reason, f"pre-writer: {reason}")
            continue

        # Economics P1.3: LAST $0 predicate, immediately before the paid
        # boundary (codex r1 P2: checking earlier let cheaper deterministic
        # kills — caps, cooldowns, dup-events — be misattributed to the
        # cache, overstating its savings). An event killed at a paid stage
        # min_kills+ times on byte-identical facts under the current decision
        # epoch re-enters the queue every cycle; skip re-buying it until its
        # facts change, the epoch rotates, or the TTL lapses.
        negcache_reason = _negcache.should_skip(
            bot_state, candidate.event_id, candidate.bundle
        )
        if negcache_reason is not None:
            # Accounting parity with the billing-skip path (codex r3 P2):
            # the event leaves triage via the cache, not an editorial cut —
            # count triaged_out so triage_cut stays exact. The skip is
            # remembered per FINGERPRINT, not per event (codex r10): an
            # identical-facts sibling row records duplicate_draft instead
            # of a second savings-inflating negative_cache kill, while a
            # changed-facts sibling keeps its paid shot.
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
            if candidate.event_id:
                negcache_skipped_sha[candidate.event_id] = (
                    _negcache.bundle_fingerprint(candidate.bundle, bot_state)
                )
            _pre_writer_kill(candidate, "negative_cache", f"pre-writer: {negcache_reason}")
            continue

        # Reserve before the paid boundary; a rejected attempt keeps its slot.
        if not budget.reserve(budget_key):
            _budget_cut(candidate)
            continue
        _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
        if generation_client is None:
            _bump_source_field_in_run(current_run, candidate.source, "writer_attempted")
        attempts += 1
        if candidate.event_id:
            attempted_event_ids.add(candidate.event_id)

        draft_kwargs = _draft_kwargs_for(candidate)
        # Always request result_out — the billing circuit breaker below reads
        # kill_stage even when funnel telemetry is off.
        cand_result: dict = {}
        draft_kwargs["result_out"] = cand_result
        if generation_client is not None:
            draft_kwargs["generation_client"] = generation_client
        drafted = _common._try_two_bot_draft(
            candidate.bundle, bot_state, candidate.score, **draft_kwargs,
        )
        _settle_attempt(budget, budget_key, drafted, cand_result, current_run, candidate,
                        counted=generation_client is None)
        if cand_result.get("generation_status") in {"queued", "reused"}:
            queued_count += 1
            success_by_category[category] = success_by_category.get(category, 0) + 1
            if country:
                success_by_country[country] = success_by_country.get(country, 0) + 1
            if draft_type:
                pending_by_type[draft_type] = pending_by_type.get(draft_type, 0) + 1
            if funnel_sink is not None:
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "generation_queued")
            continue
        if sink_active:
            _funnel.record_candidate_passes(funnel_sink, cand_result.get("stage_outcomes"))
            if drafted:
                terminal = "drafted"
            elif cand_result.get("kill_stage"):
                terminal = cand_result["kill_stage"]
            else:
                terminal = "save_rejected"
            # First terminal wins across EVERY recording path (codex P1.3
            # r4–r6): duplicate event_ids with divergent category/gate
            # attributes can route one row through a pre-writer terminal and
            # a later row to the writer. Documented trade: the slate view
            # keeps the FIRST resolution; the suppression ledger and
            # stage_outcomes above still carry the paid attempt's full
            # history.
            if funnel_sink is not None and candidate.event_id not in funnel_sink.get(
                "_slate_terminal", {}
            ):
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, terminal)

        if drafted:
            drafted_count += 1
            success_by_category[category] = success_by_category.get(category, 0) + 1
            if country:
                success_by_country[country] = success_by_country.get(country, 0) + 1
            if draft_type:
                pending_by_type[draft_type] = pending_by_type.get(draft_type, 0) + 1
            _bump_run_drafted(current_run, candidate.source)
            # Fire inline (see docstring): keeps annual counts live for the next
            # candidate's annual_cap_check. Safe — no loop draft is ever pruned.
            if candidate.on_draft_success is not None:
                try:
                    candidate.on_draft_success()
                except Exception as cb_exc:  # noqa: BLE001
                    print(f"[triage] on_draft_success callback error for {candidate.source}: {cb_exc!r}")
        else:
            # Economics P1.3: remember eligible writer evidence judgments so later
            # cycles skip re-attempting this bundle while its material facts
            # are unchanged. Eligibility (r8 explicit disposition, r2
            # out-of-scope exclusion) lives in the shared helper — ONE rule
            # for both drain paths (codex r9).
            _record_negcache_kill_if_eligible(bot_state, candidate, cand_result)

        if cand_result.get("kill_stage") == "budget_exhausted":
            _abort_cycle_on_billing(
                bot_state, current_run, funnel_sink,
                ranked[idx + 1 :], candidate.event_id,
                bump_triaged_out=True,  # refill counts triaged_out per attempt
            )
            break
        if cand_result.get("kill_stage") == "provider_preflight":
            _hold_on_provider_access(
                bot_state, current_run, funnel_sink, ranked[idx + 1 :], budget,
                cand_result.get("provider_preflight"), bump_triaged_out=True,
            )
            break

    return drafted_count


def _drain_and_write_triage_queue(
    bot_state: BotState,
    current_run: dict | None,
    *,
    defer_callbacks: list | None = None,
    funnel_sink: dict | None = None,
    generation_client=None,
    candidate_budget: CandidateBudget | None = None,
) -> int:
    """Drain the triage queue and call _try_two_bot_draft() for each survivor.

    Called at the END of run_alerts(), after all source runners have completed.

    When triage is ENABLED (THEHEAT_TRIAGE_ENABLED=1):
        - Calls triage.select_survivors() to rank + cap
        - Only survivors reach _try_two_bot_draft()

    When triage is DISABLED (default / kill-switch OFF):
        - Writes everything in queue order (legacy behaviour)

    If triage raises, or returns anything other than distinct queued
    candidates within its cap, the selection is HELD: zero writer attempts, a
    triage_error suppression, degraded triage health and a partial_failure
    ``triage`` run row. (It formerly fell through to writing every candidate,
    which turned one selector fault into unbounded paid generation.) An unsafe
    configured maximum is refused the same way. Triage still never takes down
    the cron.

    ``candidate_budget`` is the calling operation's attempt budget; a drain
    without one is its own independent operation.

    In all cases (including exception), the queue is popped from bot_state
    before returning so a crashed cron doesn't re-process stale candidates
    next cycle.

    Returns the number of survivor drafts that were actually written.

    Per-source telemetry (spec § 9):
        - On successful draft: increments ``drafted`` on the source's run
          entry via ``_bump_run_drafted``.
        - Source runners record ``drafted=0`` at their own call site; the
          drain step credits the actual count once survivors are written.
    """
    from src.orchestrator import caps as _caps
    from src.orchestrator import common as _common
    from src.orchestrator import triage as _triage

    triage_enabled = _triage_enabled()
    refill_enabled = _caps.refill_enabled()
    if triage_enabled or refill_enabled:
        # Pending-queue TTL sweep — auto-reject stale drafts BEFORE triage so the
        # freshly-opened slots are immediately available to incoming candidates
        # via the pending-type cap. Errors here must NOT block the cycle: a
        # broken TTL only fails to GC stale drafts, the rest of the pipeline
        # still runs.
        try:
            ttl_rejected = _triage.apply_pending_ttl_sweep(bot_state)
            if ttl_rejected > 0:
                print(
                    f"[triage] pending TTL sweep rejected {ttl_rejected} stale draft(s)"
                )
        except Exception as exc:
            print(f"[triage] TTL sweep error (continuing): {exc!r}")
        # Forecast-elapsed sweep — sibling of the TTL sweep, keyed on the
        # claim's anchor date instead of draft age. Same isolation contract:
        # a sweep failure only fails to GC, never blocks the cycle.
        try:
            swept_forecast = _triage.apply_forecast_elapsed_sweep(bot_state)
            if swept_forecast > 0:
                print(
                    f"[triage] forecast-elapsed sweep rejected {swept_forecast} draft(s)"
                )
        except Exception as exc:
            print(f"[triage] forecast-elapsed sweep error (continuing): {exc!r}")

    # Cast to plain dict: _triage_queue is a transient key not declared in
    # BotState TypedDict (it's excluded from sqlite persistence intentionally).
    state_dict: dict = cast(dict, bot_state)
    queue = state_dict.pop("_triage_queue", [])
    if not queue:
        return 0

    # Phase D: attach optional verifiable cross-signal context (default OFF). Done
    # once here so both the legacy drain and the refill loop see enriched bundles.
    # Errors must never take down the cron — this is a writer enrichment, not a gate.
    from src.two_bot.multisignal import attach_related_signals, multisignal_context_enabled

    if multisignal_context_enabled():
        try:
            attach_related_signals(queue)
        except Exception as exc:  # noqa: BLE001
            print(f"[multisignal] attach_related_signals error (continuing): {exc!r}")

    # Bet A (A1, default OFF): match the retrieval lane's verified news events
    # to this cycle's candidates and attach sourced human_impact facts. Same
    # placement discipline as Phase D — once, before both drain paths; a
    # matcher error degrades to un-enriched drafting, never a dead cycle.
    from src.editorial import newsworthiness as _news

    if _news.news_enrich_enabled():
        try:
            enriched = _news.attach_human_impact(queue, bot_state.get("news_events"))
            if enriched:
                print(f"[news_enrich] attached human_impact to {enriched} candidate(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"[news_enrich] attach_human_impact error (continuing): {exc!r}")

    # Phase A funnel telemetry: snapshot the shadow slate from the FULL ranked
    # queue BEFORE draining (codex must-fix #3 — end-of-cycle is too late to
    # reconstruct it). No-ops when funnel_sink is None (flag OFF).
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        _funnel.capture_slate(funnel_sink, queue)

    queued_by_source = Counter(candidate.source for candidate in queue)
    for source, count in queued_by_source.items():
        _bump_source_field_in_run(current_run, source, "triaged_in", count)

    if generation_client is not None:
        eligible = []
        for candidate in queue:
            if candidate.on_draft_success is None and candidate.annual_cap_check is None:
                eligible.append(candidate)
                continue
            # These callbacks belong to synchronous draft success. Do not invoke
            # them or let unsupported candidates consume a generation slot.
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
            if funnel_sink is not None:
                from src.orchestrator import funnel as _funnel
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "generation_start")
        queue = eligible

    # Cycle-scoped billing latch (codex r2 P1): an earlier drain this run
    # proved the balance dead; every candidate here would re-discover it at
    # one paid call each. Skip the whole slate — the first abort row already
    # tells the story, so no duplicate suppression is recorded.
    if state_dict.get("_billing_exhausted_latch"):
        print(
            f"[triage] billing latch tripped earlier this run; skipping "
            f"drain of {len(queue)} candidate(s)"
        )
        for candidate in queue:
            _bump_source_field_in_run(current_run, candidate.source, "billing_aborted")
            # Counted in triaged_in above but never selected/attempted:
            # pair with triaged_out so the skip doesn't read as a triage cut.
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
        if funnel_sink is not None:
            from src.orchestrator import funnel as _funnel

            for candidate in queue:
                if candidate.event_id in funnel_sink.get("_slate_terminal", {}):
                    continue
                _funnel.record_slate_terminal(
                    funnel_sink, candidate.event_id, "billing_abort"
                )
        _record_generation_hold(bot_state, current_run, code="provider_billing_exhausted",
                                error_class="provider_billing", held=len(queue),
                                details={"aborted_event_id": None, "earlier_in_process": True})
        return 0

    budget = candidate_budget if candidate_budget is not None else CandidateBudget.for_operation("drain")
    if budget.refusal is not None:
        # An unsafe configured maximum is refused visibly, never defaulted or clamped.
        return _hold_operation(bot_state, current_run, funnel_sink, list(queue), budget,
                               note="candidate_budget_config_invalid", error=budget.refusal)

    # Phase C: generate-and-select refill loop (flag default OFF). Owns its own
    # ranking, success-aware caps, pre-writer predicate and stop condition.
    if refill_enabled:
        return _refill_drain(
            bot_state, current_run, queue,
            defer_callbacks=defer_callbacks, funnel_sink=funnel_sink, generation_client=generation_client,
            candidate_budget=budget,
        )

    # Economics P1.3 (codex r9–r11): the negative cache protects the legacy
    # path too, and a $0 cache skip must not consume a capped survivor slot
    # (codex r11 P1: caps ran BEFORE the cache check, so a cache-dead row
    # burned the slot a changed-facts sibling needed and the slot was never
    # backfilled). The cache therefore PARTITIONS the queue before cap
    # selection: cache-dead rows and their identical-facts duplicates
    # resolve here; only live candidates contend for cap slots.
    # Attribution trade, documented: a row that is BOTH cache-dead and
    # would have been cap-cut records negative_cache rather than triage_cap
    # on this path — the refill drain keeps exact last-$0-predicate
    # ordering; here the slot-backfill invariant wins.
    from src.two_bot import negative_cache as _negcache

    _negcache.prune(bot_state)
    negcache_run_id = (_current_suppression_ctx() or {}).get("run_id")

    def _legacy_pre_writer_row(
        candidate: "TriageCandidateBundle", stage: str, reason: str
    ) -> None:
        """$0 suppression row + first-terminal-wins funnel row (legacy)."""
        _record_downstream_suppression(
            bot_state=bot_state,
            source=candidate.source,
            run_id=negcache_run_id,
            event_id=candidate.event_id,
            score=candidate.score,
            kill_stage=stage,
            kill_reason=reason,
            summary=getattr(candidate.bundle, "where", None)
            or candidate.city
            or None,
        )
        if funnel_sink is not None and candidate.event_id not in funnel_sink.get(
            "_slate_terminal", {}
        ):
            from src.orchestrator import funnel as _funnel

            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, stage)

    # Partition rules (codex r10–r12), in order per row:
    #   1. The event already holds a LIVE row → duplicate_draft. One paid
    #      shot per event per cycle; a second same-event row (identical OR
    #      changed facts) must not burn a cap slot the attempted guard
    #      would only reclaim after selection (codex r12 P1).
    #   2. Identical facts to a cache-skipped row → duplicate_draft (never
    #      a second savings-inflating negative_cache row, codex r10).
    #   3. Cache-dead → negative_cache row + fingerprint skip memory.
    #   4. Otherwise live — the event's one contender for a cap slot.
    # Partition rows LEFT triage — bump triaged_out for them (codex r12
    # P2: funnel triage_cut = triaged_in - triaged_out; unbumped cache
    # resolutions read as editorial cap cuts, a cache-only slate showed
    # triage_cap_rate=1.0). writer_attempted is never bumped here — no
    # paid attempt happened.
    negcache_skipped_sha: dict[str, str] = {}
    live_event_ids: set[str] = set()
    live_queue: list = []
    for candidate in queue:
        if candidate.event_id and candidate.event_id in live_event_ids:
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
            _legacy_pre_writer_row(
                candidate, "duplicate_draft", "pre-writer: duplicate event in slate"
            )
            continue
        if (
            candidate.event_id
            and candidate.event_id in negcache_skipped_sha
            and _negcache.bundle_fingerprint(candidate.bundle, bot_state)
            == negcache_skipped_sha[candidate.event_id]
        ):
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
            _legacy_pre_writer_row(
                candidate, "duplicate_draft", "pre-writer: duplicate event in slate"
            )
            continue
        negcache_reason = _negcache.should_skip(
            bot_state, candidate.event_id, candidate.bundle
        )
        if negcache_reason is not None:
            if candidate.event_id:
                negcache_skipped_sha[candidate.event_id] = (
                    _negcache.bundle_fingerprint(candidate.bundle, bot_state)
                )
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
            _legacy_pre_writer_row(
                candidate, "negative_cache", f"pre-writer: {negcache_reason}"
            )
            continue
        if candidate.event_id:
            live_event_ids.add(candidate.event_id)
        live_queue.append(candidate)

    survivors = live_queue  # default: legacy passthrough
    if triage_enabled and live_queue:
        cap = budget.limit if budget.limit is not None else _triage.MAX_DRAFTS_PER_CYCLE
        try:
            selected = _triage.select_survivors(bot_state, live_queue, global_cap=cap)
        except Exception as exc:  # noqa: BLE001 — held loudly below, never written through
            return _hold_operation(bot_state, current_run, funnel_sink, live_queue, budget,
                                   note="selector_unavailable", error=str(exc)[:200])
        try:
            survivors = _validated_selection(selected, live_queue, cap=cap)
        except _SelectionInvalid as exc:
            return _hold_operation(bot_state, current_run, funnel_sink, live_queue, budget,
                                   note="selector_invalid", error=exc.code)

    survivor_by_source = Counter(candidate.source for candidate in survivors)
    for source, survivor_count in survivor_by_source.items():
        _bump_source_field_in_run(current_run, source, "triaged_out", survivor_count)

    # Phase A: mark slate candidates the triage cap cut (drain-observed, not
    # from the truncatable suppression ledger — triage_cap rows carry
    # run_id=None). LIVE candidates only: cache-partitioned rows already
    # carry their own terminal, and first-terminal-wins (codex r10/r11) —
    # a cap-cut changed-facts sibling of a skipped event must not overwrite
    # the event's negative_cache resolution with triage_cap.
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        survivor_ids = {candidate.event_id for candidate in survivors}
        for candidate in live_queue:
            if candidate.event_id not in survivor_ids and candidate.event_id not in funnel_sink.get(
                "_slate_terminal", {}
            ):
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")

    drafted_count = 0
    # One paid shot per event per cycle (codex r11 P2): the fingerprint
    # partition reopens changed facts, but a reopened event must not be
    # bought twice when the queue carries it twice — mirror the refill
    # drain's attempted guard beyond the paid boundary.
    attempted_event_ids: set[str] = set()
    for idx, candidate in enumerate(survivors):
        if candidate.event_id and candidate.event_id in attempted_event_ids:
            _legacy_pre_writer_row(
                candidate, "duplicate_draft", "pre-writer: duplicate event in slate"
            )
            continue
        budget_key = CandidateBudget.key_for(candidate)
        if budget.seen(budget_key):
            # An earlier drain of this same operation already handled the event.
            _legacy_pre_writer_row(
                candidate, "duplicate_draft", "pre-writer: event already handled this operation"
            )
            continue
        # Reserve before the paid boundary; a rejected attempt keeps its slot.
        if not budget.reserve(budget_key):
            _triage._record_triage_suppression(
                bot_state, candidate, cap=_triage._per_category_cap(), global_cap=budget.limit or 0,
                reason="candidate_budget",
            )
            budget.hold()
            if funnel_sink is not None and candidate.event_id not in funnel_sink.get("_slate_terminal", {}):
                from src.orchestrator import funnel as _funnel

                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")
            continue
        if candidate.event_id:
            attempted_event_ids.add(candidate.event_id)
        if generation_client is None:
            _bump_source_field_in_run(current_run, candidate.source, "writer_attempted")
        draft_kwargs = {
            "legacy_type": candidate.legacy_type,
            "event_id": candidate.event_id,
            "review_context": candidate.review_context,
        }
        if candidate.city:
            draft_kwargs["city"] = candidate.city
        if candidate.tweet_date:
            draft_kwargs["tweet_date"] = candidate.tweet_date
        if candidate.cooldown_exempt:
            draft_kwargs["cooldown_exempt"] = candidate.cooldown_exempt
        if candidate.draft_metadata:
            draft_kwargs["draft_metadata"] = candidate.draft_metadata
        # Always request result_out — the billing circuit breaker below reads
        # kill_stage even when funnel telemetry is off.
        cand_result: dict = {}
        draft_kwargs["result_out"] = cand_result
        if generation_client is not None:
            draft_kwargs["generation_client"] = generation_client
        drafted = _common._try_two_bot_draft(
            candidate.bundle,
            bot_state,
            candidate.score,
            **draft_kwargs,
        )
        _settle_attempt(budget, budget_key, drafted, cand_result, current_run, candidate,
                        counted=generation_client is None)
        if cand_result.get("generation_status") in {"queued", "reused"}:
            if funnel_sink is not None:
                from src.orchestrator import funnel as _funnel
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "generation_queued")
            continue
        if funnel_sink is not None:
            from src.orchestrator import funnel as _funnel

            _funnel.record_candidate_passes(funnel_sink, cand_result.get("stage_outcomes"))
            if drafted:
                terminal = "drafted"
            elif cand_result.get("kill_stage"):
                terminal = cand_result["kill_stage"]
            else:
                # generate_draft succeeded but save_draft refused (cooldown / dup /
                # superseded); the specific stage is in the kills counter + ledger.
                terminal = "save_rejected"
            # First terminal wins here too (codex r10 P2): with cached facts
            # A skipped pre-writer and changed facts B reaching the writer,
            # B's paid result must not overwrite the event's first
            # resolution — parity with the refill drain and the legacy
            # cache-hit path above.
            if candidate.event_id not in funnel_sink.get("_slate_terminal", {}):
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, terminal)
        if drafted:
            drafted_count += 1
            # Credit the originating source's run-telemetry entry (spec § 9 I2 fix).
            # Source runners write drafted=0 at their call site because candidates
            # are still queued then; the drain step is where drafts actually happen.
            _bump_run_drafted(current_run, candidate.source)
            # Fire source-specific post-success callback if provided (e.g.
            # incrementing an annual counter that should only tick on actual drafts).
            # When ``defer_callbacks`` is supplied, DON'T fire inline — collect for
            # the caller to fire AFTER the cycle-cap prune, so a draft that gets
            # pruned does not consume dedup/cap state (Codex #5). The hot10 path
            # (no prune) passes None and keeps firing inline.
            if candidate.on_draft_success is not None:
                if defer_callbacks is not None:
                    defer_callbacks.append((candidate.event_id, candidate.on_draft_success))
                else:
                    try:
                        candidate.on_draft_success()
                    except Exception as cb_exc:
                        print(f"[triage] on_draft_success callback error for {candidate.source}: {cb_exc!r}")
        else:
            # Economics P1.3 (codex r9): record eligible writer evidence judgments on
            # the legacy path too — same shared disposition as the refill
            # drain, so evidence accumulates regardless of the refill flag.
            _record_negcache_kill_if_eligible(bot_state, candidate, cand_result)

        if cand_result.get("kill_stage") == "budget_exhausted":
            _abort_cycle_on_billing(
                bot_state, current_run, funnel_sink,
                survivors[idx + 1 :], candidate.event_id,
                # Legacy pre-counts every survivor in triaged_out — bumping
                # again would hide real editorial cuts (codex r4 P2).
                bump_triaged_out=False,
            )
            break
        if cand_result.get("kill_stage") == "provider_preflight":
            _hold_on_provider_access(
                bot_state, current_run, funnel_sink, survivors[idx + 1 :], budget,
                cand_result.get("provider_preflight"), bump_triaged_out=False,
            )
            break

    return drafted_count


__all__ = [
    "_drain_and_write_triage_queue",
    "_enqueue_candidate",
    "_enqueue_story_candidate",
    "_triage_enabled",
]
