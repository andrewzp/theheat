"""Optional NHC public advisory -> the ordinary queue, writer/check chain and admission.

Default off. Only THEHEAT_NHC_ADVISORY_ACQUISITION=1 together with an explicit
THEHEAT_NHC_ADVISORY_NOMINATION (one storm/bin/advisory/hazard/place scope) does
anything; otherwise nothing is read, recorded or queued. The nomination never
carries a URL: the fixed NHC products are derived from it. This is not a
generic source uploader, an alternate writer or a publication path.
"""
from __future__ import annotations

import json
import os
import time
from typing import cast

from src.editorial.nhc_advisory import AdvisoryHold, AdvisoryNomination, nomination
from src.editorial.official_warning import WarningHold
from src.editorial.revisions import has_unresolved_publish, revoke_approval
from src.editorial.scoring import EditorialScore
from src.orchestrator.common import _record_source_run, _should_draft
from src.orchestrator.triage_queue import _TRIAGE_QUEUE_LOCK, _enqueue_story_candidate
from src.state_schema import BotState
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.types import StoryBundle

ENABLE_ENV = "THEHEAT_NHC_ADVISORY_ACQUISITION"
NOMINATION_ENV = "THEHEAT_NHC_ADVISORY_NOMINATION"
# The operator's explicit editorial nomination of this one advisory, not a
# provider severity inferred from advisory wording or an impact estimate.
NOMINATION_SCORE = EditorialScore("nhc_advisory", 75, 70, 80, 80, 70, 0, 76, 60,
                                  ["Explicit operator nomination of one NHC public advisory."])


def configured(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(ENABLE_ENV, "") == "1"


def configured_nomination(environ=None) -> AdvisoryNomination:
    env = os.environ if environ is None else environ
    raw = env.get(NOMINATION_ENV, "")
    if type(raw) is not str or not raw.strip() or len(raw) > 2048:
        raise AdvisoryHold("nhc_advisory_nomination_invalid")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AdvisoryHold("nhc_advisory_nomination_invalid")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise AdvisoryHold("nhc_advisory_nomination_invalid") from None
    return nomination(value)


def run_nhc_advisory_source(bot_state: BotState, current_run: dict | None) -> None:
    """The ordinary source-runner contract; the result keeps its disposition."""
    run_nhc_advisory(bot_state, current_run)


def run_nhc_advisory(bot_state: BotState, current_run: dict | None, environ=None) -> dict:
    """One explicitly nominated advisory per command. Absent configuration: no work."""
    if not configured(environ):
        return {"status": "absent", "promoted": 0}
    from src.data.nhc_advisory import current_budget, current_evidence
    from src.editorial.nhc_advisory_runtime import current_owner, guard_advisory_story
    from src.two_bot.intern.nhc_advisory import build_nhc_advisory_bundle
    start = time.perf_counter()
    budget = current_budget()
    used_before = budget.used if budget is not None else 0
    details: dict = {"requests_used": 0}
    try:
        if os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
            raise AdvisoryHold("nhc_advisory_generation_paused")
        selected = configured_nomination(environ)
        details.update(storm_id=selected.storm_id, advisory=selected.advisory, hazard=selected.hazard)
        owner = current_owner()
        bundle = build_nhc_advisory_bundle(current_evidence(selected, clock=owner.clock))
        if not _should_draft(NOMINATION_SCORE, bundle.event_id):
            return {"status": "below_threshold", "promoted": 0}
        for prior in bot_state.get("drafts", []):
            if prior.get("event_id") != bundle.event_id:
                continue
            if prior.get("status") in {"pending", "approved"} and not has_unresolved_publish(prior, bot_state):
                try:
                    old = prior.get("review_context", {}).get("two_bot", {}).get("bundle")
                    # Same evidence identity only; copy edits stay with ordinary review.
                    guard_advisory_story(StoryBundle(**old), generating=False)
                    if capture_bundle(StoryBundle(**old)).payload()["raw_signal_dump"]["nhc_advisory"][
                            "bulletin_sha256"] != bundle.raw_signal_dump["nhc_advisory"]["bulletin_sha256"]:
                        raise AdvisoryHold("nhc_advisory_current_source_changed")
                except (WarningHold, TypeError, ValueError, AttributeError, KeyError):
                    revoke_approval(prior)
                    prior["status"] = "pending"
                    prior.setdefault("review_context", {})["nhc_advisory_source_hold"] = (
                        "nhc_advisory_current_source_changed")
                    prior["post_error"] = "The NHC advisory changed; fresh source review is required."
                    raise AdvisoryHold("nhc_advisory_current_source_changed") from None
            return {"status": "reused", "promoted": 0}
        if bundle.event_id in bot_state.get("posted_events", []):
            return {"status": "reused", "promoted": 0}
        from src.editorial import warning_automatic
        payload = capture_bundle(bundle).payload()
        # Same storm/hazard/place episode: an unknown earlier delivery or an unchanged
        # published statement (a tier/category-only update) buys no writer.
        fence = warning_automatic.runner_fence("nhc_advisory", payload, bot_state)
        if fence is not None:
            raise AdvisoryHold(fence)
        context = {"source": "NHC", "source_key": "nhc_advisory",
                   "headline": f"NHC forecast for {bundle.where}", "facts": bundle.current_facts,
                   "warning_consequence_brief": warning_automatic.consequence_brief("nhc_advisory", payload)}
        with _TRIAGE_QUEUE_LOCK:
            queue = cast(dict, bot_state).get("_triage_queue", [])
            duplicates = [row for row in queue if getattr(row, "event_id", None) == bundle.event_id]
            if duplicates:
                if all(capture_bundle(row.bundle) == capture_bundle(bundle) for row in duplicates):
                    return {"status": "reused", "promoted": 0}
                queue[:] = [row for row in queue if getattr(row, "event_id", None) != bundle.event_id]
                raise AdvisoryHold("nhc_advisory_current_revision_conflict")
        promoted = _enqueue_story_candidate(bot_state, bundle=bundle, score=NOMINATION_SCORE,
                                            source="nhc_advisory", legacy_type="nhc_advisory",
                                            event_id=bundle.event_id, review_context=context)
        details["requests_used"] = (budget.used if budget is not None else 0) - used_before
        _record_source_run(current_run, bot_state, "nhc_advisory", start, status="success", observed=1,
                           promoted=int(promoted), drafted=0, details=details)
        return {"status": "queued" if promoted else "held", "promoted": int(promoted)}
    except WarningHold as exc:
        details["requests_used"] = (budget.used if budget is not None else 0) - used_before
        _record_source_run(current_run, bot_state, "nhc_advisory", start, status="degraded", observed=1,
                           promoted=0, note=exc.code, details=details)
        return {"status": "held", "reason": exc.code, "promoted": 0}
