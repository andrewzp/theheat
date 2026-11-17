"""Invented source episodes through the real collector, queue and writer memory."""
from copy import deepcopy
from dataclasses import replace
import json
import re

import pytest

from src.editorial import hazard_episodes
from src.state import DEFAULT_STATE
from src.two_bot.memory import build_memory_slice, bundle_memory_snapshot, record_shipped, _story_bundle_from_metadata
from src.two_bot.types import WriterResult
from src.two_bot.intern.disasters import build_global_disaster_bundle
from src.two_bot.writer import build_writer_user_prompt
from tests.remaining_campaign.test_w07_episode_admission import (
    _queue,
    _run_gdacs,
    offline as offline,
)
from tests.test_gdacs_intake_contract import capture, items
from tests.test_gdacs_publication_freshness import NS


@pytest.mark.parametrize("enabled", ["0", "1"])
def test_admitted_distinct_source_episodes_do_not_share_ongoing_memory(offline, enabled):
    offline.setenv(hazard_episodes.FLAG, enabled)
    state = deepcopy(DEFAULT_STATE)
    rows = [items("intake-control")[0], items("intake-control")[0]]
    for row, identity in zip(rows, ("memory-first", "memory-second"), strict=True):
        row.find(NS + "eventtype").text = "FL"
        row.find(NS + "eventid").text = identity
        row.find(NS + "country").text = "India"
    events, _, _ = capture(rows, min_level=0)
    assert len(events) == 2 and all(event.disaster_type == "Flood" for event in events)
    first, second = events
    _run_gdacs(offline, state, first, second)
    previous, current = _queue(state)
    if enabled == "1":
        assert previous.review_context["physical_episode"]["episode_id"] != current.review_context["physical_episode"]["episode_id"]
    assert previous.bundle.where == current.bundle.where
    assert previous.bundle.signal_kind == current.bundle.signal_kind
    # Exercise the actual recorder too. The supplied writer output is an explicit
    # offline fixture: no model quality, source truth or real publication proof.
    record_shipped(state, previous.bundle, WriterResult(
        tweet="Other invented source episode; no current-event authority.",
        kill_reason=None, angle_chosen="observed_fixture", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Invented offline recorder input."), [])
    assert state["memory"]["ongoing_events"][0]["event_id"] == previous.bundle.event_id
    actual = build_memory_slice(state, current.bundle)
    assert actual.ongoing_event is None
    assert actual.recent_tweets_same_event == []
    assert actual.source_report_series["recent_published_texts"] == []
    # Country/feed history is explicitly general context, not this event's past.
    assert actual.recent_tweets_same_country
    prompt = build_writer_user_prompt(current.bundle, actual)
    assert re.search(r'"ongoing_event":\s*null', prompt)


def source_event(identity="series_one", *, kind="FL", country="India"):
    row = items("intake-control")[0]
    row.find(NS + "eventtype").text = kind
    row.find(NS + "eventid").text = identity
    row.find(NS + "country").text = country
    events, _, _ = capture([row], min_level=0)
    assert len(events) == 1
    return events[0]


def remember(state, bundle):
    record_shipped(state, bundle, WriterResult(
        tweet="Explicit invented history fixture.", kill_reason=None, angle_chosen="fixture",
        era_anchor_used=None, peer_comparison_used=None, reasoning="Offline input only."), [])


def test_same_issuer_event_continues_across_changed_ingest_id_and_border(offline):
    event = source_event()
    first = build_global_disaster_bundle(event)
    current = build_global_disaster_bundle(replace(event, country="Nepal", event_id=event.event_id + "_revision2"))
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    memory = build_memory_slice(state, current)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert memory.source_report_series["previous_report_context"]["event_id"] == first.event_id
    assert memory.source_report_series["recent_published_texts"] == ["Explicit invented history fixture."]
    assert "days_running" not in json.dumps(memory.source_report_series)
    remember(state, current)
    assert len(state["memory"]["ongoing_events"]) == 1
    assert state["memory"]["ongoing_events"][0]["region"] == "Nepal"
    assert state["memory"]["shipped_tweets"][0]["country"] == "IN"


@pytest.mark.parametrize("other_id,kind", [("series_two", "FL"), ("series_one", "TC"),
                                           ("series_one_extra", "FL")])
def test_exact_source_type_and_full_id_override_names_country_and_prefix(offline, other_id, kind):
    first = build_global_disaster_bundle(source_event())
    other = build_global_disaster_bundle(source_event(other_id, kind=kind))
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    memory = build_memory_slice(state, other)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert memory.recent_tweets_same_country


@pytest.mark.parametrize("change", ["missing-id", "changed-id", "changed-type", "wrong-leg", "wrong-url", "missing-fact", "duplicate-fact", "wrong-bundle-id"])
def test_missing_or_contradictory_current_identity_never_uses_legacy_fallback(offline, change):
    first = build_global_disaster_bundle(source_event())
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    current = deepcopy(first)
    if change == "missing-id":
        current.raw_signal_dump.pop("source_event_id")
    elif change == "changed-id":
        current.raw_signal_dump["source_event_id"] = "another"
    elif change == "changed-type":
        current.raw_signal_dump["source_provenance"]["eventtype"] = "TC"
    elif change == "wrong-leg":
        current.raw_signal_dump["source_leg"] = "subtype_witnesses"
    elif change == "wrong-url":
        current.raw_signal_dump["source_url"] = "https://example.invalid/"
    elif change == "missing-fact":
        current.current_facts = [f for f in current.current_facts if f["label"] != "source_event_id"]
    elif change == "duplicate-fact":
        current.current_facts.append({"label": "source_event_id", "value": "contradiction"})
    else:
        current.event_id += "_changed"
    memory = build_memory_slice(state, current)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    before = deepcopy(state["memory"]["ongoing_events"])
    remember(state, current)
    assert state["memory"]["ongoing_events"] == before


def test_legacy_rows_and_unscoped_consumers_cannot_promote_a_source_binding(offline):
    bundle = build_global_disaster_bundle(source_event())
    state = deepcopy(DEFAULT_STATE)
    remember(state, bundle)
    original = deepcopy(state)
    for row in state["memory"]["ongoing_events"] + state["memory"]["shipped_tweets"]:
        row.pop("source_event_identity")
    memory = build_memory_slice(state, bundle)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    unscoped = deepcopy(bundle)
    unscoped.event_id = "unscoped_report"
    unscoped.raw_signal_dump = {"country": "India"}
    memory = build_memory_slice(original, unscoped)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []


def test_snapshot_restore_preserves_source_identity_without_reacquisition(offline):
    bundle = build_global_disaster_bundle(source_event())
    snapshot = json.loads(json.dumps(bundle_memory_snapshot(bundle)))
    restored = _story_bundle_from_metadata({"bundle": snapshot}, {})
    assert restored is not None
    state = deepcopy(DEFAULT_STATE)
    remember(state, restored)
    memory = build_memory_slice(json.loads(json.dumps(state)), bundle)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert memory.source_report_series["identity"] == snapshot["source_event_identity"]
    assert memory.source_report_series["recent_published_texts"] == ["Explicit invented history fixture."]
    assert (state["memory"]["ongoing_events"][0]["source_event_identity"] is not
            state["memory"]["shipped_tweets"][0]["source_event_identity"])


@pytest.mark.parametrize("change", ["legacy", "wrong-id", "wrong-type", "unknown-schema"])
def test_snapshot_cannot_infer_or_relabel_the_saved_source_identity(offline, change):
    bundle = build_global_disaster_bundle(source_event())
    snapshot = bundle_memory_snapshot(bundle)
    if change == "legacy":
        snapshot.pop("source_event_identity")
    elif change == "wrong-id":
        snapshot["source_event_identity"]["source_event_id"] = "other"
    elif change == "wrong-type":
        snapshot["source_event_identity"]["event_type"] = "TC"
    else:
        snapshot["source_event_identity"]["schema"] = "unknown"
    restored = _story_bundle_from_metadata({"bundle": snapshot}, {})
    state = deepcopy(DEFAULT_STATE)
    remember(state, restored)
    assert state["memory"]["ongoing_events"] == []
    assert len(state["memory"]["shipped_tweets"]) == 1


def test_physical_episode_context_still_requires_the_existing_resolver(offline):
    bundle = build_global_disaster_bundle(source_event())
    bundle.raw_signal_dump["physical_episode"] = {}
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_memory_slice(deepcopy(DEFAULT_STATE), bundle)
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_writer_user_prompt(bundle, build_memory_slice(deepcopy(DEFAULT_STATE),
                                                          build_global_disaster_bundle(source_event())))
