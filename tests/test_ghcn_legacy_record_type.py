"""Surviving legacy record types must not exempt malformed GHCN warrants."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.data.ghcn_publication import current_draft_hold
from src.editorial import revisions
from src.orchestrator import posting
from tests.test_ghcn_publication_currentness import archive_http as archive_http, variants as variants
from tests.test_ghcn_publication_posting import approved_record, run_sender, source_at_sender as source_at_sender
from tests.test_gist_temperature_posting import fake_transport as fake_transport, invented_clock as invented_clock, state_for


def erased_comparison(draft, hint):
    draft = deepcopy(draft)
    bundle = draft["review_context"]["two_bot"]["bundle"]
    raw = bundle["raw_signal_dump"]
    draft["event_id"] = bundle["event_id"] = raw["event_id"] = "invented-legacy-only-record"
    bundle["signal_kind"] = "temperature_anomaly"
    for key in ("new_temp_c", "old_record_c"):
        raw.pop(key, None)
    for key in ("prior_record_c", "prior_record_year"):
        bundle["historical_context"].pop(key, None)
    if hint == "facts_only":
        raw.pop("evidence")
        bundle["historical_context"].pop("baseline")
    elif hint in {"station_only", "product_only"}:
        bundle["current_facts"] = []
        bundle["headline_metric"]["label"] = "renamed"
        for row in (raw["evidence"], raw["evidence"]["baseline"], bundle["historical_context"]["baseline"]):
            row.pop("source_product" if hint == "station_only" else "station_id", None)
    return draft


@pytest.mark.parametrize("key", [(d, t) for d in ("high", "low") for t in ("all_time", "monthly", "calendar")])
@pytest.mark.parametrize("hint", ["full", "station_only", "product_only", "facts_only"])
def test_surviving_legacy_record_type_keeps_identified_ghcn_inside_source_validation(
    variants, archive_http, monkeypatch, key, hint,
):
    draft = erased_comparison(variants[key], hint)
    original = deepcopy(draft)
    clock = datetime(2026, 9, 9, 12, tzinfo=UTC)
    monkeypatch.setattr(posting, "_utc_now", lambda: clock)
    assert current_draft_hold(draft, live=True, now=clock) == "ghcn_retained_source_invalid"
    assert posting._current_nws_source(draft, live=True, bot_state={}) == "ghcn_retained_source_invalid"
    assert not archive_http["calls"]
    assert draft == original


@pytest.mark.usefixtures("automatic_publication_release", "invented_clock")
def test_erased_record_still_cannot_send_after_fresh_human_review(
    variants, fake_transport, source_at_sender, monkeypatch,
):
    changed = erased_comparison(variants[("high", "all_time")], "full")
    draft = approved_record({("high", "all_time"): changed}, "manual")
    state = state_for(draft)
    run_sender(draft, state, "manual", monkeypatch)
    assert not fake_transport.calls and not state["publish_ledger"]
    assert not source_at_sender["calls"]
    fake_transport.safety.assert_not_called()
    assert draft["publish_outcome"] == "not_sent" and not draft.get("approval_binding")
    assert not revisions.has_unresolved_publish(draft, state)
    revisions.invalidate_text(draft, "Another invented comparison for review.")
    assert draft["status"] == "pending" and not draft.get("review_binding")
    assert not revisions.has_unresolved_publish(draft, state)


@pytest.mark.parametrize("legacy", ["all_time_high", "all_time_low", "monthly_high", "monthly_low", "record", "record_low"])
def test_legacy_type_alone_does_not_claim_an_unrelated_grid_source(archive_http, legacy):
    draft = {"type": legacy, "event_id": "invented-grid", "review_context": {"two_bot": {"bundle": {
        "event_id": "invented-grid", "signal_kind": "open_meteo_archive_high",
        "raw_signal_dump": {"evidence": {"source_product": "openmeteo-era5-daily-v2"}},
    }}}}
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert not archive_http["calls"]


@pytest.mark.parametrize("legacy", [None, [], {}, False])
def test_malformed_legacy_type_never_crashes_a_recognized_full_record(variants, archive_http, legacy):
    draft = deepcopy(variants[("high", "all_time")])
    draft["type"] = legacy
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) == "ghcn_retained_source_invalid"
    assert not archive_http["calls"]


def test_non_record_ghcn_source_keeps_its_separate_contract(variants, archive_http):
    draft = erased_comparison(variants[("high", "all_time")], "full")
    draft["type"] = "anomaly_hot"
    assert current_draft_hold(draft, live=True, now=datetime(2026, 9, 9, 12, tzinfo=UTC)) is None
    assert not archive_http["calls"]
