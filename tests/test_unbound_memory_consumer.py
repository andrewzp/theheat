"""Invented legacy inputs: publication history never supplies episode authority."""
from copy import deepcopy
from datetime import UTC, datetime
import json

import pytest
import requests

from src.data import fire_footprint
from src.orchestrator.sources import nifc
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.disasters import build_severe_weather_bundle
from src.two_bot.intern.fire import build_fire_footprint_bundle
from src.two_bot.memory import (
    _story_bundle_from_metadata, build_memory_slice, bundle_memory_snapshot,
    record_published_draft, record_shipped,
)
from src.two_bot.types import ExtractedClaim, WriterResult
from src.two_bot.writer import anthropic_writer_request, build_writer_user_prompt
from tests.live_content_harness import trap_network
from tests import published_radar_fixtures as warning_fixture

TEXT = "Earlier invented complex report; no claim about current conditions."


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "0")


def perimeter_bundles(monkeypatch, *, separator="-"):
    """Real JSON decoder/parser and runner; only HTTP returns invented bytes."""
    stamp = int(datetime.now(UTC).timestamp() * 1000)
    payload = {"features": [{"attributes": {
        "UniqueFireIdentifier": f"invented-complex{separator}{suffix}",
        "IncidentName": f"Invented complex {suffix}", "POOState": "US-OR",
        "IncidentSize": 3_000_000, "ModifiedOnDateTime_dt": stamp,
        "IncidentTypeCategory": "WF", "ActiveFireCandidate": 1,
        "FireDiscoveryDateTime": stamp, "IsCpxChild": 0,
    }} for suffix in ("a", "b")]}
    response = requests.Response()
    response.status_code = 200
    response.url = fire_footprint.GWIS_URL
    response._content = json.dumps(payload).encode()
    calls = []

    def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return response

    monkeypatch.setattr(fire_footprint, "fetch_with_retry", fetch)
    parsed = fire_footprint.fetch_active_fire_perimeters(strict=True)
    assert len(parsed) == 2 and parsed[0].complex_id != parsed[1].complex_id
    bundles = [build_fire_footprint_bundle(row) for row in parsed]
    state = deepcopy(DEFAULT_STATE)
    run = {"sources": []}
    nifc.run_fire_footprint(state, run)
    assert len(calls) == 2 and all(url == fire_footprint.GWIS_URL for url, _ in calls)
    # The real parser now retains a source-bound incident-size report. This is
    # no physical episode, provider truth or model/publication acceptance.
    assert all(audit_story_bundle(b).prompt_ready for b in bundles)
    assert len(state.get("_triage_queue", [])) == 2
    assert run["sources"][-1]["observed"] == 2
    return bundles


def remember(state, bundle):
    record_shipped(state, bundle, WriterResult(TEXT, None, "invented_angle", None,
        None, "Explicit recorder fixture, never a model or actual publication."),
        [ExtractedClaim("Invented past comparison", "peer_comparison")])


def request_for(state, bundle):
    return anthropic_writer_request(build_writer_user_prompt(bundle, build_memory_slice(state, bundle)))


def test_real_perimeter_parser_runner_hold_and_unbound_memory_request(monkeypatch):
    first, current = perimeter_bundles(monkeypatch)
    assert first.where == current.where and first.event_id != current.event_id
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    memory = build_memory_slice(state, current)
    assert memory.ongoing_event is None
    assert memory.recent_tweets_same_event == []
    assert memory.shipped_tweet_texts == [TEXT]
    assert memory.recent_categories == ["fire"]
    assert memory.used_framings == ["invented_angle"]
    request = request_for(state, current)
    assert '"ongoing_event": null' in request["messages"][0]["content"]
    assert "days_running" not in request["messages"][0]["content"]


@pytest.mark.parametrize("same_id", [False, True])
def test_retained_ongoing_rows_never_become_unbound_physical_evidence(monkeypatch, same_id):
    first, current = perimeter_bundles(monkeypatch)
    legacy = {"event_id": current.event_id if same_id else first.event_id,
              "signal_kind": current.signal_kind, "region": current.where,
              "country": "US", "days_running": 90, "first_seen": "2000-01-01"}
    state = deepcopy(DEFAULT_STATE)
    state["memory"]["ongoing_events"] = [deepcopy(legacy)]
    assert build_memory_slice(state, current).ongoing_event is None
    assert state["memory"]["ongoing_events"] == [legacy]
    remember(state, current)
    assert state["memory"]["ongoing_events"] == [legacy]
    assert len(state["memory"]["shipped_tweets"]) == 1


@pytest.mark.parametrize("same_id", [False, True])
def test_exact_complete_perimeter_id_alone_selects_candidate_history(monkeypatch, same_id):
    first, other = perimeter_bundles(monkeypatch)
    current = first if same_id else other
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    memory = build_memory_slice(json.loads(json.dumps(state)), current)
    assert memory.recent_tweets_same_event == ([TEXT] if same_id else [])
    assert memory.ongoing_event is None
    assert memory.used_peer_comparisons == ["invented past comparison"]


def test_source_ids_sharing_a_legacy_prefix_never_share_candidate_history(monkeypatch):
    first, current = perimeter_bundles(monkeypatch, separator="_")
    assert first.event_id != current.event_id
    assert first.event_id.split("_")[:3] == current.event_id.split("_")[:3]
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    assert build_memory_slice(state, current).recent_tweets_same_event == []
    assert build_memory_slice(state, current).ongoing_event is None


@pytest.mark.parametrize("same_id", [False, True])
def test_actual_warning_parser_preserves_exact_history_not_area_continuity(monkeypatch, same_id):
    first = build_severe_weather_bundle(warning_fixture.parsed(monkeypatch)[0])
    item = warning_fixture.feature()
    item["id"] += "-other"
    item["properties"]["id"] += "-other"
    current = first if same_id else build_severe_weather_bundle(warning_fixture.parsed(monkeypatch, item)[0])
    assert first.where == current.where
    state = deepcopy(DEFAULT_STATE)
    remember(state, first)
    memory = build_memory_slice(state, current)
    assert memory.recent_tweets_same_event == ([TEXT] if same_id else [])
    assert memory.ongoing_event is None
    assert memory.source_report_series is None


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("marker", ["ordinary", "missing-kind", "unknown-kind", "foreign-source-hint"])
def test_full_compact_json_restore_cannot_create_unbound_episode_rows(monkeypatch, compact, marker):
    first, _ = perimeter_bundles(monkeypatch)
    snapshot = bundle_memory_snapshot(first) if compact else first.to_dict()
    if marker == "missing-kind":
        snapshot.pop("signal_kind")
    elif marker == "unknown-kind":
        snapshot["signal_kind"] = "invented_unknown_kind"
    elif marker == "foreign-source-hint":
        snapshot["source_event_identity"] = {"schema": "gdacs-source-memory/v1",
            "issuer": "gdacs-georss", "event_type": "FL", "source_event_id": "unrelated"}
    metadata = {"signal_kind": first.signal_kind, "bundle": json.loads(json.dumps(snapshot))}
    restored = _story_bundle_from_metadata(metadata, {})
    assert restored is not None
    state = deepcopy(DEFAULT_STATE)
    remember(state, restored)
    assert state["memory"]["ongoing_events"] == []
    assert build_memory_slice(state, restored).ongoing_event is None
    assert len(state["memory"]["shipped_tweets"]) == 1


def test_persisted_unbound_publication_records_once_without_an_episode(monkeypatch):
    first, _ = perimeter_bundles(monkeypatch)
    state = deepcopy(DEFAULT_STATE)
    draft = {"text": TEXT, "status": "posted", "tweet_id": "invented-offline-id",
             "event_id": first.event_id, "review_context": {"two_bot": {
                 "signal_kind": first.signal_kind, "bundle": bundle_memory_snapshot(first)}}}
    assert record_published_draft(state, draft)
    assert not record_published_draft(state, draft)
    assert len(state["memory"]["shipped_tweets"]) == 1
    assert state["memory"]["ongoing_events"] == []


def test_explicit_resolved_physical_binding_has_precedence():
    from src.storage.physical_events import EpisodeContext
    from src.storage.postgres_projection import _canonical
    from tests.test_physical_event_consumers import bound_bundle
    bundle = bound_bundle()
    binding = bundle.raw_signal_dump["physical_episode"]
    context = EpisodeContext(_canonical(binding), _canonical([binding]))
    row = {"event_id": "a-different-source-revision", "physical_episode": deepcopy(binding),
           "tweet_text": TEXT, "days_running": 2}
    state = {"memory": {"ongoing_events": [row], "shipped_tweets": [row]}}
    memory = build_memory_slice(state, bundle, episode_context=context)
    assert memory.ongoing_event == row and memory.recent_tweets_same_event == [TEXT]
    prompt = build_writer_user_prompt(bundle, memory, episode_context=context)
    assert TEXT in prompt
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_memory_slice(state, bundle)
