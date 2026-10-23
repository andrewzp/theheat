"""Real audit/enqueue boundary for staged GDACS candidates; invented data only."""
from copy import deepcopy
import gc
import json
import threading
import time
from unittest.mock import patch

import pytest

from src.data import gdacs_intake
from src.editorial.scoring import score_global_disaster
from src.orchestrator import triage_queue
from src.orchestrator.triage_queue import _enqueue_story_candidate
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.disasters import build_global_disaster_bundle
from tests.test_gdacs_intake_contract import capture, items
from tests.test_gdacs_publication_freshness import NS


def staged(*event_ids, rows=None):
    events, _, selection = capture(rows or items(*event_ids))
    return gdacs_intake.staged_order(events), selection["capture_sha256"]


def admit(state, event, capture_sha, *, bundle=None, out=None):
    out = {} if out is None else out
    admitted = _enqueue_story_candidate(
        state, bundle=bundle or build_global_disaster_bundle(event),
        score=score_global_disaster(event.severity, event.disaster_type), source="gdacs",
        legacy_type="global_disaster", event_id=event.event_id, review_context={"source": "GDACS"},
        intake_identity=gdacs_intake.intake_identity(event, capture_sha) if capture_sha else None,
        admission_out=out)
    return admitted, out


def queue(state):
    return state.get("_triage_queue", [])


def test_exact_repeat_from_one_capture_queues_once_without_inflating_observations():
    state = deepcopy(DEFAULT_STATE)
    events, capture_sha = staged("intake-control", "intake-shared-1")
    first = [admit(state, event, capture_sha) for event in events]
    log = deepcopy(state["candidates_log"])
    with patch.object(triage_queue, "_record_downstream_suppression") as suppression:
        repeat = [admit(state, event, capture_sha) for event in events]
    assert [a for a, _ in first] == [True, True] and [o["disposition"] for _, o in first] == ["new", "new"]
    assert [a for a, _ in repeat] == [False, False] and [o["disposition"] for _, o in repeat] == ["reused", "reused"]
    assert len(queue(state)) == 2 and state["candidates_log"] == log and not suppression.called
    # A repeated capture after the drain is a new queue unit, not a stale witness.
    state.pop("_triage_queue")
    assert admit(state, events[0], capture_sha)[1]["disposition"] == "new"


def test_changed_later_capture_is_not_an_exact_repeat_witness():
    state = deepcopy(DEFAULT_STATE)
    events, capture_sha = staged("intake-control")
    assert admit(state, events[0], capture_sha)[1] == {"disposition": "new", "pending_disagreements": 0}
    # Byte-identical candidate from a different returned capture: existing rules, no merge.
    other_rows = items("intake-control", "intake-shared-1")
    other_events, other_sha = staged(rows=other_rows)
    same = next(e for e in other_events if e.source_event_id == "intake-control")
    assert gdacs_intake.projection_sha256(same) == gdacs_intake.projection_sha256(events[0])
    assert admit(state, same, other_sha)[1] == {"disposition": "new", "pending_disagreements": 0}
    # A later capture that changes the candidate is exposed as a pending disagreement.
    changed = items("intake-control")
    changed[0].find("description").text = "Invented later wording."
    changed_events, changed_sha = staged(rows=changed)
    assert admit(state, changed_events[0], changed_sha)[1] == {"disposition": "new", "pending_disagreements": 2}
    assert len(queue(state)) == 3  # Downstream event rules, unchanged, decide between them.


def test_unidentified_and_non_gdacs_callers_keep_existing_append_semantics():
    state = deepcopy(DEFAULT_STATE)
    events, _ = staged("intake-control")
    assert [admit(state, events[0], None)[0] for _ in range(2)] == [True, True]
    assert len(queue(state)) == 2 and not triage_queue._GDACS_INTAKE.keys() & {id(row) for row in queue(state)}


class YieldingOut(dict):
    """Switches threads between the admission decision and the append."""

    def __setitem__(self, key, value):
        if key == "pending_disagreements":
            time.sleep(0.005)
        super().__setitem__(key, value)


def test_admission_decision_is_atomic_with_its_append_under_the_existing_lock():
    state = deepcopy(DEFAULT_STATE)
    events, capture_sha = staged("intake-control")
    barrier, results = threading.Barrier(16), []

    def worker():
        barrier.wait()
        results.append(admit(state, events[0], capture_sha, out=YieldingOut())[1]["disposition"])

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()  # No nested acquisition of the non-reentrant lock.
    assert sorted(results) == ["new"] + ["reused"] * 15 and len(queue(state)) == 1
    assert not triage_queue._TRIAGE_QUEUE_LOCK.locked()


def test_evidence_refusal_never_queues_or_counts_as_admission():
    state = deepcopy(DEFAULT_STATE)
    events, capture_sha = staged("intake-control")
    bundle = build_global_disaster_bundle(events[0])
    bundle.current_facts = []
    assert not audit_story_bundle(bundle).prompt_ready
    admitted, out = admit(state, events[0], capture_sha, bundle=bundle)
    assert admitted is False and out == {"disposition": "refused_evidence"}
    assert queue(state) == [] and not state.get("candidates_log")
    assert [row["stage"] for row in state["suppressions"]] == ["evidence_contract"]


def test_intake_registry_is_transient_and_scoped_to_live_queue_rows():
    events, capture_sha = staged("intake-control")
    first, second = deepcopy(DEFAULT_STATE), deepcopy(DEFAULT_STATE)
    assert admit(first, events[0], capture_sha)[1]["disposition"] == "new"
    assert admit(second, events[0], capture_sha)[1]["disposition"] == "new"  # Other state, own queue.
    rows = list(queue(first)) + list(queue(second))
    assert {id(row) for row in rows} <= triage_queue._GDACS_INTAKE.keys()
    first.pop("_triage_queue"), second.pop("_triage_queue")
    del rows
    gc.collect()
    assert not any(key[0] == capture_sha for key in triage_queue._GDACS_INTAKE.values())


def test_mutation_after_parse_build_and_admission_cannot_change_queued_evidence():
    state = deepcopy(DEFAULT_STATE)
    events, capture_sha = staged("intake-unknown-country")
    event = events[0]
    bundle = build_global_disaster_bundle(event)
    review_context = {"source": "GDACS"}
    snapshot = json.dumps(bundle.raw_signal_dump, sort_keys=True), deepcopy(bundle.current_facts)
    _enqueue_story_candidate(state, bundle=bundle, score=score_global_disaster(event.severity, event.disaster_type),
                             source="gdacs", legacy_type="global_disaster", event_id=event.event_id,
                             review_context=review_context,
                             intake_identity=gdacs_intake.intake_identity(event, capture_sha), admission_out={})
    identity = triage_queue._GDACS_INTAKE[id(queue(state)[0])]
    event.description = "Mutated after admission."
    event.source_provenance["episode_id"] = "mutated"
    event.source_provenance["coordinates"] = "0 0"
    queued = queue(state)[0]
    assert queued.bundle is bundle and queued.review_context == {"source": "GDACS"}
    assert (json.dumps(queued.bundle.raw_signal_dump, sort_keys=True), queued.bundle.current_facts) == snapshot
    assert triage_queue._GDACS_INTAKE[id(queued)] == identity


@pytest.mark.parametrize("event_id", ["intake-control", "intake-unknown-country", "intake-current-old"])
def test_detached_bundle_keeps_source_identity_time_and_existing_limits(event_id):
    events, capture_sha = staged(event_id)
    event = events[0]
    bundle = build_global_disaster_bundle(event)
    raw, provenance = bundle.raw_signal_dump, bundle.raw_signal_dump["source_provenance"]
    assert audit_story_bundle(bundle).prompt_ready
    assert (raw["source_product"], raw["source_leg"], raw["source_event_id"]) == ("gdacs-georss", "georss", event_id)
    assert raw["source_url"] == "https://www.gdacs.org/xml/rss.xml" and raw["description"] == event.description
    assert provenance["is_current"] is True and provenance["episode_id"] == event.source_provenance["episode_id"]
    assert provenance["overall_alert_level"] == provenance["episode_alert_level"] == "Red"
    assert (provenance["source_update_kind"], provenance["source_updated_at"]) == ("pubDate", "2026-09-30T12:00:00Z")
    assert (provenance["fromdate"], provenance["todate"]) == ("2026-09-01T00:00:00Z", "2026-10-02T00:00:00Z")
    assert provenance["coordinates"] and provenance["source_country_known"] is bool(raw["country"])
    # Unchanged compatible event identity and `when`; the source time is not an observation interval.
    assert bundle.event_id == event.event_id and bundle.event_id.startswith(f"gdacs_{provenance['eventtype']}_{event_id}_")
    limits = [row["value"] for row in bundle.current_facts if row["label"] == "claim_limit"]
    assert any("Source publication time and event window are different" in text for text in limits)
    assert capture_sha not in repr(bundle) and "\x1f" not in json.dumps(raw)
    assert raw["source_provenance"] is not event.source_provenance  # Detached evidence.


def test_explicit_old_episode_never_replaces_the_current_one():
    events, _ = staged("intake-current-old")
    assert [e.source_provenance["episode_id"] for e in events] == ["ep-E1"]
    old_only = items("intake-current-old")[1:]
    assert old_only[0].find(NS + "iscurrent").text == "false" and staged(rows=old_only)[0] == []
