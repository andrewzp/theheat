"""Optional supplied warning -> the existing queue, not another writer lane."""
from __future__ import annotations

import os
import time
from typing import cast

from src.editorial.official_warning import WarningHold
from src.editorial.scoring import EditorialScore
from src.editorial.warning_runtime import (
    WarningSource, current_warning_bundle, guard_warning_story, warning_source_scope,
)
from src.editorial.revisions import has_unresolved_publish, revoke_approval
from src.orchestrator.common import _record_source_run, _should_draft
from src.orchestrator.triage_queue import _TRIAGE_QUEUE_LOCK, _enqueue_story_candidate
from src.state_schema import BotState
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.types import StoryBundle


def run_official_warning(bot_state: BotState, current_run: dict | None, *,
                         source: WarningSource | None = None, score: EditorialScore | None = None) -> dict:
    """One independently nominated packet. Absent means no work or state change.

    Score is an existing editorial nomination from the trusted owner, not a
    provider severity inferred from warning wording or an impact estimate.
    No source is selected by environment/path/URL, and nothing is enabled here.
    """
    if source is None:
        return {"status": "absent", "promoted": 0}
    start = time.perf_counter()
    try:
        if os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1":
            raise WarningHold("warning_generation_paused")
        if type(score) is not EditorialScore or any(
            type(getattr(score, name)) is not int or not 0 <= getattr(score, name) <= 100
            for name in ("severity", "novelty", "timeliness", "confidence", "shareability", "sensitivity", "total", "threshold")
        ):
            raise WarningHold("warning_editorial_nomination_required")
        with warning_source_scope(source):
            bundle = current_warning_bundle()
        if not _should_draft(score, bundle.event_id):
            return {"status": "below_threshold", "promoted": 0}
        for prior in bot_state.get("drafts", []):
            if prior.get("event_id") != bundle.event_id:
                continue
            if prior.get("status") in {"pending", "approved"} and not has_unresolved_publish(prior, bot_state):
                try:
                    with warning_source_scope(source):
                        old = prior.get("review_context", {}).get("two_bot", {}).get("bundle")
                        # Reuse compares the retained source only. A temporary
                        # copy edit must remain correctable through normal review.
                        guard_warning_story(StoryBundle(**old))
                except (WarningHold, TypeError, ValueError, AttributeError):
                    revoke_approval(prior)
                    prior["status"] = "pending"
                    prior.setdefault("review_context", {})["official_warning_source_hold"] = "warning_current_source_changed"
                    prior["post_error"] = "The supplied warning changed; fresh source review is required."
                    raise WarningHold("warning_current_source_changed") from None
            return {"status": "reused", "promoted": 0}
        if bundle.event_id in bot_state.get("posted_events", []):
            return {"status": "reused", "promoted": 0}
        context = {"source": bundle.raw_signal_dump["source_name"], "source_key": "official_warning",
            "headline": f"Official warning for {bundle.where}", "facts": bundle.current_facts}
        # One nominated packet, including exact repeats in the same live queue.
        with _TRIAGE_QUEUE_LOCK:
            queue = cast(dict, bot_state).get("_triage_queue", [])
            duplicates = [row for row in queue if getattr(row, "event_id", None) == bundle.event_id]
            if duplicates:
                if all(capture_bundle(row.bundle) == capture_bundle(bundle) for row in duplicates):
                    return {"status": "reused", "promoted": 0}
                queue[:] = [row for row in queue if getattr(row, "event_id", None) != bundle.event_id]
                raise WarningHold("warning_current_revision_conflict")
        promoted = _enqueue_story_candidate(bot_state, bundle=bundle, score=score,
            source="official_warning", legacy_type="official_warning", event_id=bundle.event_id,
            review_context=context)
        _record_source_run(current_run, bot_state, "official_warning", start,
                           status="success", observed=1, promoted=int(promoted), drafted=0)
        return {"status": "queued" if promoted else "held", "promoted": int(promoted)}
    except WarningHold as exc:
        _record_source_run(current_run, bot_state, "official_warning", start,
            status="degraded", observed=1, promoted=0, note=exc.code)
        return {"status": "held", "reason": exc.code, "promoted": 0}
