"""Invented retained AWC evidence; expiry frees capacity, never posting authority."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import socket

from freezegun import freeze_time
import pytest

from src.data import awc_observed as awc
from src.editorial.revisions import initialize_revision
from src.orchestrator import triage
from src.state import DEFAULT_STATE
from tests.test_awc_observed import NOW, catalog, install, reports
from tests.test_triage import _candidate


@pytest.fixture
def pending(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail("Expiry must not access a network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    install(monkeypatch)
    bundle = awc.build_bundle(awc.nominate(now=NOW), now=NOW).to_dict()
    monkeypatch.setattr(awc, "_read", no_network)
    draft = {
        "id": "invented-expiry-draft",
        "event_id": bundle["event_id"],
        "type": awc.KIND,
        "status": "pending",
        "text": "Invented retained copy.",
        "created_at": NOW.isoformat(),
        "review_context": {"two_bot": {"bundle": bundle}},
        "revision_history": [{"text": "Retain this historical copy."}],
    }
    initialize_revision(draft)
    # Markers are deliberately inert fixtures, not fabricated valid approvals.
    draft.update(
        approval_binding={"fixture": "obsolete"},
        approval_mode="auto",
        auto_approve_at=NOW.isoformat(),
        publish_intent_id="invented-unsent-intent",
        raw_model_output={"fixture": "retained"},
        review_binding={"fixture": "retained"},
    )
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    return state, draft


def sweep(state, *, now=NOW + timedelta(hours=3)):
    return triage.apply_awc_expired_pending_sweep(state, now=now)


def test_expiry_preserves_content_and_history_but_revokes_decision(pending):
    state, draft = pending
    before = deepcopy(draft)
    assert sweep(state) == 1
    expected = deepcopy(before)
    for key in ("approval_binding", "auto_approve_at", "publish_intent_id"):
        expected.pop(key)
    expected.update(
        approval_mode="manual",
        decision_revision=before["decision_revision"] + 1,
        status="rejected",
        rejected_reason="awc_source_window_elapsed",
        rejected_at=(NOW + timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
    )
    assert draft == expected
    after = deepcopy(state)
    assert sweep(state) == 0
    assert state == after


@pytest.mark.parametrize("seconds,expected", [(0, 0), (6599, 0), (6600, 0), (6601, 1)])
def test_existing_two_hour_window_is_strict_and_anchored_to_observation(pending, seconds, expected):
    state, _ = pending
    assert sweep(state, now=NOW + timedelta(seconds=seconds)) == expected


@pytest.mark.parametrize(
    "change",
    [
        "wrong_type",
        "wrong_event",
        "wrong_kind",
        "missing_bundle",
        "malformed_raw",
        "changed_capture",
        "scalar_capture",
        "changed_point",
        "future_capture",
        "posted",
        "rejected",
    ],
)
def test_unqualified_or_nonpending_items_are_untouched(pending, change):
    state, draft = pending
    bundle = draft["review_context"]["two_bot"]["bundle"]
    if change == "wrong_type":
        draft["type"] = "absolute_extreme"
    elif change == "wrong_event":
        draft["event_id"] = "another-event"
    elif change == "wrong_kind":
        bundle["signal_kind"] = "absolute_extreme"
    elif change == "missing_bundle":
        draft["review_context"] = {}
    elif change == "malformed_raw":
        bundle["raw_signal_dump"] = None
    elif change == "changed_capture":
        bundle["raw_signal_dump"]["evidence"]["retrieved_at"] = "bad"
    elif change == "scalar_capture":
        bundle["raw_signal_dump"]["evidence"]["retrieved_at"] = 1
    elif change == "changed_point":
        bundle["raw_signal_dump"]["evidence"]["points"][0]["temperature_c"] = 40
    elif change in ("posted", "rejected"):
        draft["status"] = change
    before = deepcopy(state)
    clock = NOW - timedelta(minutes=1) if change == "future_capture" else NOW + timedelta(hours=3)
    assert sweep(state, now=clock) == 0
    assert state == before


@pytest.mark.parametrize(
    "witness",
    [
        "unknown",
        "submitted",
        "confirmed",
        "not_sent",
        "attempted",
        "attempt_time",
        "ledger_null",
        "ledger_unknown",
        "ledger_not_sent",
        "ledger_receipt",
        "ledger_conflict",
        "ledger_by_draft",
        "malformed_ledger",
    ],
)
def test_any_send_evidence_stays_for_existing_resolution(pending, witness):
    state, draft = pending
    if witness in ("unknown", "submitted", "confirmed", "not_sent"):
        draft["publish_outcome"] = witness
    elif witness == "attempted":
        draft["autoship_attempted"] = True
    elif witness == "attempt_time":
        draft["last_publish_attempt_at"] = NOW.isoformat()
    elif witness == "malformed_ledger":
        state["publish_ledger"] = []
    else:
        row = {
            "ledger_null": None,
            "ledger_unknown": {"phase": "unknown"},
            "ledger_not_sent": {"phase": "not_sent"},
            "ledger_receipt": {"phase": "confirmed", "tweet_id": "invented"},
            "ledger_conflict": {"phase": "not_sent", "attempt_conflicts": [None]},
            "ledger_by_draft": {"phase": "submitted"},
        }[witness]
        key = draft["id"] if witness == "ledger_by_draft" else draft["event_id"]
        state["publish_ledger"] = {key: row}
    before = deepcopy(state)
    assert sweep(state) == 0
    assert state == before


@pytest.mark.parametrize(
    "field",
    [
        "tweet_id",
        "posted_at",
        "published_revision",
        "publication_observations",
        "attempt_conflicts",
        "revision_conflicts",
    ],
)
@pytest.mark.parametrize("value", [None, "invented receipt witness", {"tweet_id": "invented"}])
def test_retained_receipt_and_conflict_fields_never_prove_unattempted(pending, field, value):
    state, draft = pending
    draft[field] = value
    before = deepcopy(state)
    assert sweep(state) == 0
    assert state == before


def test_real_source_sweep_frees_type_cap_without_raising_it(pending):
    state, draft = pending
    state["drafts"] = [deepcopy(draft) for _ in range(3)]
    for index, row in enumerate(state["drafts"]):
        row["id"] += str(index)
    candidate = _candidate(signal_kind=awc.KIND, source="awc_observed", event_id="invented-next")
    assert triage.select_survivors(state, [candidate], global_cap=1) == []
    assert sweep(state) == 3
    assert triage.select_survivors(state, [candidate], global_cap=1) == [candidate]
    assert triage._pending_type_cap() == 3


@pytest.mark.parametrize(
    "triage_on,refill_on,expected", [("1", "0", 1), ("0", "1", 1), ("0", "0", 0)]
)
def test_actual_empty_drain_applies_only_existing_enabled_sweep_modes(
    monkeypatch, pending, triage_on, refill_on, expected
):
    from src.orchestrator.triage_queue import _drain_and_write_triage_queue

    state, _ = pending
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", triage_on)
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill_on)
    with freeze_time(NOW + timedelta(hours=3)):
        assert _drain_and_write_triage_queue(state, {"sources": []}) == 0
    assert sum(d["status"] == "rejected" for d in state["drafts"]) == expected


def test_actual_empty_drain_never_calls_writer(monkeypatch, pending):
    from src.orchestrator import common

    state, _ = pending
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setattr(
        common, "_try_two_bot_draft", lambda *a, **k: pytest.fail("No queued writer call")
    )
    with freeze_time(NOW + timedelta(hours=3)):
        assert common._drain_and_write_triage_queue(state, {"sources": []}) == 0
    assert state["drafts"][0]["rejected_reason"] == "awc_source_window_elapsed"


@pytest.mark.parametrize("refill", ["0", "1"])
@pytest.mark.parametrize("distinct_event", [True, False])
@pytest.mark.parametrize("cleanup_fails", [True, False])
def test_actual_drain_frees_capacity_before_real_selector_and_writer_boundary(
    monkeypatch, pending, refill, distinct_event, cleanup_fails
):
    from src.orchestrator import common

    state, draft = pending
    state["drafts"] = [deepcopy(draft) for _ in range(3)]
    for index, row in enumerate(state["drafts"]):
        row["id"] += str(index)
    current = NOW + timedelta(hours=3)
    rows = reports()
    stations = catalog()
    if distinct_event:
        for row, station, replacement in zip(rows, stations, ("TCCC", "TDDD")):
            row[0] = row[0].replace(row[1], replacement)
            row[1] = replacement
            station["icaoId"] = replacement
    for row in rows:
        row[0] = row[0].replace("151200Z", "151500Z")
        row[2] = "2026-11-15T15:00:00Z"
    install(monkeypatch, rows=rows, stations=stations)
    bundle = awc.build_bundle(awc.nominate(now=current), now=current)
    monkeypatch.setattr(awc, "_read", lambda *a, **k: pytest.fail("No new source request"))
    candidate = replace(
        _candidate(signal_kind=awc.KIND, source="awc_observed", event_id=bundle.event_id),
        bundle=bundle,
    )
    state["_triage_queue"] = [candidate]
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill)
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    if cleanup_fails:

        def unavailable(*args, **kwargs):
            raise RuntimeError("invented cleanup unavailable")

        monkeypatch.setattr(triage, "apply_awc_expired_pending_sweep", unavailable)
    calls = []

    def writer_boundary(*args, **kwargs):
        assert all(row["status"] == "rejected" for row in state["drafts"])
        assert args[0] == bundle
        calls.append(args[0].event_id)
        return False  # No model, required-check result or pending save is invented.

    monkeypatch.setattr(common, "_try_two_bot_draft", writer_boundary)
    with freeze_time(current):
        assert common._drain_and_write_triage_queue(state, {"sources": []}) == 0
    assert calls == ([bundle.event_id] if distinct_event and not cleanup_fails else [])
    assert len(state["drafts"]) == 3
    if cleanup_fails:
        assert all(row["status"] == "pending" for row in state["drafts"])
    assert triage._pending_type_cap() == 3


def test_malformed_decision_is_untouched_and_does_not_block_next_draft(pending):
    state, draft = pending
    malformed = deepcopy(draft)
    malformed["decision_revision"] = "unknown"
    before = deepcopy(malformed)
    state["drafts"].insert(0, malformed)
    assert sweep(state) == 1
    assert malformed == before


@pytest.mark.parametrize("clock", [NOW.replace(tzinfo=None), "unknown"])
def test_invalid_clock_cannot_mutate_state(pending, clock):
    state, _ = pending
    before = deepcopy(state)
    with pytest.raises(ValueError, match="aware UTC"):
        sweep(state, now=clock)
    assert state == before
