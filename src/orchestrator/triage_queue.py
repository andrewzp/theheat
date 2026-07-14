"""Triage queue helpers for source-runner candidates."""

from __future__ import annotations

import os
import threading
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from src.orchestrator.common import _utc_now_iso
from src.orchestrator.suppression import (
    _current_suppression_ctx,
    _record_billing_cycle_abort_suppression,
    _record_downstream_suppression,
    _record_triage_error_suppression,
)
from src.orchestrator.telemetry import _bump_run_drafted, _bump_source_field_in_run
from src.state_schema import BotState

if TYPE_CHECKING:
    from src.two_bot.types import TriageCandidateBundle

_TRIAGE_QUEUE_LOCK = threading.Lock()


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
) -> bool:
    """Audit and enqueue one writer candidate.

    This is the source-runner boundary. Sources collect facts, build a
    StoryBundle, and submit it here. Only the drain step may later call the
    writer pipeline for triage survivors.
    """
    from src.two_bot.evidence_contract import audit_story_bundle
    from src.two_bot.types import TriageCandidateBundle

    audit = audit_story_bundle(bundle)
    error_codes = [issue.code for issue in audit.issues if issue.severity == "error"]
    if error_codes:
        ctx = _current_suppression_ctx() or {}
        _record_downstream_suppression(
            bot_state=bot_state,
            source=source,
            run_id=ctx.get("run_id"),
            event_id=event_id,
            score=score,
            kill_stage="evidence_contract",
            kill_reason="; ".join(error_codes),
            summary=getattr(bundle, "where", None) or city or None,
        )
        return False

    _enqueue_candidate(
        bot_state,
        TriageCandidateBundle(
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
        ),
    )
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


def _refill_drain(
    bot_state: BotState,
    current_run: dict | None,
    queue: list,
    *,
    defer_callbacks: list | None = None,
    funnel_sink: dict | None = None,
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

    try:
        ranked = _triage.select_survivors(bot_state, queue, refill=True)
    except Exception as exc:  # noqa: BLE001
        err_text = str(exc)[:200]
        print(f"[triage] refill ranking error: {exc!r} — falling back to queue order")
        from src import state as _state

        _record_triage_error_suppression(bot_state, err_text)
        _state.record_source_health(bot_state, "triage", "degraded", err_text)
        ranked = list(queue)

    target = _caps.drafts_target_per_cycle()
    max_attempts = _caps.refill_max_attempts(target)
    per_cat_cap = _triage._per_category_cap()
    pending_cap = _triage._pending_type_cap()
    country_cap = _triage._per_country_cap()

    success_by_category: dict[str, int] = {}
    success_by_country: dict[str, int] = {}
    pending_by_type: dict[str, int] = {}
    attempted_event_ids: set[str] = set()

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
        if sink_active:
            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, stage)

    def _cut(candidate: "TriageCandidateBundle", reason: str) -> None:
        _triage._record_triage_suppression(
            bot_state, candidate, cap=per_cat_cap, global_cap=target, reason=reason,
        )
        if sink_active:
            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")

    drafted_count = 0
    attempts = 0
    for idx, candidate in enumerate(ranked):
        if drafted_count >= target or attempts >= max_attempts:
            _cut(candidate, "global_cap")
            continue

        # Distinct candidates only: never spend a 2nd writer call on an event_id we
        # already attempted this cycle (the first attempt may have critic-killed, so
        # can_draft_candidate wouldn't catch it). (codex)
        if candidate.event_id and candidate.event_id in attempted_event_ids:
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

        _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
        _bump_source_field_in_run(current_run, candidate.source, "writer_attempted")
        attempts += 1
        if candidate.event_id:
            attempted_event_ids.add(candidate.event_id)

        draft_kwargs = _draft_kwargs_for(candidate)
        # Always request result_out — the billing circuit breaker below reads
        # kill_stage even when funnel telemetry is off.
        cand_result: dict = {}
        draft_kwargs["result_out"] = cand_result
        drafted = _common._try_two_bot_draft(
            candidate.bundle, bot_state, candidate.score, **draft_kwargs,
        )
        if sink_active:
            _funnel.record_candidate_passes(funnel_sink, cand_result.get("stage_outcomes"))
            if drafted:
                terminal = "drafted"
            elif cand_result.get("kill_stage"):
                terminal = cand_result["kill_stage"]
            else:
                terminal = "save_rejected"
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

        if cand_result.get("kill_stage") == "budget_exhausted":
            _abort_cycle_on_billing(
                bot_state, current_run, funnel_sink,
                ranked[idx + 1 :], candidate.event_id,
                bump_triaged_out=True,  # refill counts triaged_out per attempt
            )
            break

    return drafted_count


def _drain_and_write_triage_queue(
    bot_state: BotState,
    current_run: dict | None,
    *,
    defer_callbacks: list | None = None,
    funnel_sink: dict | None = None,
) -> int:
    """Drain the triage queue and call _try_two_bot_draft() for each survivor.

    Called at the END of run_alerts(), after all source runners have completed.

    In BOTH modes, certain rejections (pending/posted duplicates, dead
    cooldowns — ``can_draft_candidate``) and same-cycle duplicate event_ids
    are filtered out before anything else: they would spend a writer call
    only to be rejected by ``save_draft``, and under triage they would
    consume capped survivor slots.

    When triage is ENABLED (THEHEAT_TRIAGE_ENABLED=1):
        - Calls triage.select_survivors() to rank + cap
        - Only survivors reach _try_two_bot_draft()

    When triage is DISABLED (default / kill-switch OFF):
        - Writes the remaining queue in order (legacy behaviour)

    If triage raises, logs the error and falls through to legacy (writes
    everything). Triage MUST NOT take down the whole cron.

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
    from src import state as _state
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

    # Certain rejections are filtered BEFORE the billing latch and survivor
    # selection: they are free deterministic gates (pending/posted
    # duplicates, dead cooldowns, same-cycle duplicate event_ids), so a
    # latched cycle must not mislabel them as billing impact, and under
    # triage they must not consume capped survivor slots (a few persistent-
    # lifecycle duplicates would otherwise starve every fresh candidate at
    # the global cap). The in-loop recheck below stays — an earlier
    # survivor drafting can make a later duplicate certain mid-drain.
    from src.orchestrator.draft_save import can_draft_candidate

    ctx = _current_suppression_ctx() or {}
    run_id = ctx.get("run_id")

    def _pre_writer_reject(
        candidate: "TriageCandidateBundle", reason: str, *, record_terminal: bool = True
    ) -> None:
        # $0 LLM — record at the specific certain-rejection stage.
        _record_downstream_suppression(
            bot_state=bot_state,
            source=candidate.source,
            run_id=run_id,
            event_id=candidate.event_id,
            score=candidate.score,
            kill_stage=reason,
            kill_reason=f"pre-writer: {reason}",
            summary=getattr(candidate.bundle, "where", None) or candidate.city or None,
        )
        if record_terminal and funnel_sink is not None:
            from src.orchestrator import funnel as _funnel

            _funnel.record_slate_terminal(funnel_sink, candidate.event_id, reason)

    # Same-cycle duplicate ids: keep the copy triage would rank highest —
    # keeping the first-encountered low-score copy could cost the event
    # its capped slot entirely.
    best_duplicate: dict[str, "TriageCandidateBundle"] = {}
    for candidate in queue:
        if not candidate.event_id:
            continue
        best = best_duplicate.get(candidate.event_id)
        if best is None or (candidate.score.total, candidate.created_at or "") > (
            best.score.total,
            best.created_at or "",
        ):
            best_duplicate[candidate.event_id] = candidate

    admissible = []
    for candidate in queue:
        if candidate.event_id and best_duplicate.get(candidate.event_id) is not candidate:
            # A discarded copy is not a distinct slate event: recording a
            # terminal under the shared id would mask the kept copy's real
            # outcome (the billing abort path is first-write-wins).
            _pre_writer_reject(candidate, "duplicate_draft", record_terminal=False)
            continue
        can_draft, reason = can_draft_candidate(bot_state, candidate)
        if can_draft:
            admissible.append(candidate)
        else:
            _pre_writer_reject(candidate, reason)
    queue = admissible

    # Cycle-scoped billing latch (codex r2 P1): an earlier drain this run
    # proved the balance dead; every remaining candidate would re-discover
    # it at one paid call each. Skip the rest of the slate — the first
    # abort row already tells the story, so no duplicate suppression is
    # recorded.
    if state_dict.get("_billing_exhausted_latch"):
        print(
            f"[triage] billing latch tripped earlier this run; skipping "
            f"drain of {len(queue)} candidate(s)"
        )
        for candidate in queue:
            _bump_source_field_in_run(current_run, candidate.source, "billing_aborted")
            # Never selected/attempted: pair triaged_in with triaged_out so
            # the skip doesn't read as a triage cut. (Self-paired here —
            # the regular triaged_in count below is never reached.)
            _bump_source_field_in_run(current_run, candidate.source, "triaged_in")
            _bump_source_field_in_run(current_run, candidate.source, "triaged_out")
        if funnel_sink is not None:
            from src.orchestrator import funnel as _funnel

            for candidate in queue:
                if candidate.event_id in funnel_sink.get("_slate_terminal", {}):
                    continue
                _funnel.record_slate_terminal(
                    funnel_sink, candidate.event_id, "billing_abort"
                )
        return 0

    # Counted AFTER the pre-filter: rejected candidates never entered the
    # triage stage, and the funnel derives triage_cap_rate from
    # triaged_in - triaged_out — counting them would report cap cuts that
    # never happened.
    queued_by_source = Counter(candidate.source for candidate in queue)
    for source, count in queued_by_source.items():
        _bump_source_field_in_run(current_run, source, "triaged_in", count)

    # Phase C: generate-and-select refill loop (flag default OFF). Owns its own
    # ranking, success-aware caps, pre-writer predicate and stop condition.
    if refill_enabled:
        return _refill_drain(
            bot_state, current_run, queue,
            defer_callbacks=defer_callbacks, funnel_sink=funnel_sink,
        )

    survivors = queue  # default: legacy passthrough
    if triage_enabled:
        try:
            survivors = _triage.select_survivors(bot_state, queue)
        except Exception as exc:
            # Legacy passthrough preserves draft production (the cycle still
            # produces drafts even if the triage stage breaks). But we MUST
            # surface the failure to the dashboard — silent broken triage is
            # worse than loud broken triage.
            err_text = str(exc)[:200]
            print(f"[triage] error: {exc!r} — falling through to legacy (writing all {len(queue)} candidates)")
            _record_triage_error_suppression(bot_state, err_text)
            _state.record_source_health(bot_state, "triage", "degraded", err_text)
            survivors = queue

    survivor_by_source = Counter(candidate.source for candidate in survivors)
    for source, survivor_count in survivor_by_source.items():
        _bump_source_field_in_run(current_run, source, "triaged_out", survivor_count)

    # Phase A: mark slate candidates the triage cap cut (drain-observed, not from
    # the truncatable suppression ledger — triage_cap rows carry run_id=None).
    if funnel_sink is not None:
        from src.orchestrator import funnel as _funnel

        survivor_ids = {candidate.event_id for candidate in survivors}
        for candidate in queue:
            if candidate.event_id not in survivor_ids:
                _funnel.record_slate_terminal(funnel_sink, candidate.event_id, "triage_cap")

    drafted_count = 0
    for idx, candidate in enumerate(survivors):
        # Recheck the pre-writer predicate ($0 LLM): an earlier survivor
        # drafting the same event mid-drain makes this one a certain
        # duplicate that save_draft would reject after the writer ran.
        can_draft, reason = can_draft_candidate(bot_state, candidate)
        if not can_draft:
            _pre_writer_reject(candidate, reason)
            continue

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
        drafted = _common._try_two_bot_draft(
            candidate.bundle,
            bot_state,
            candidate.score,
            **draft_kwargs,
        )
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

        if cand_result.get("kill_stage") == "budget_exhausted":
            _abort_cycle_on_billing(
                bot_state, current_run, funnel_sink,
                survivors[idx + 1 :], candidate.event_id,
                # Legacy pre-counts every survivor in triaged_out — bumping
                # again would hide real editorial cuts (codex r4 P2).
                bump_triaged_out=False,
            )
            break

    return drafted_count


__all__ = [
    "_drain_and_write_triage_queue",
    "_enqueue_candidate",
    "_enqueue_story_candidate",
    "_triage_enabled",
]
