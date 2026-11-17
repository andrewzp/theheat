"""Invented airport observations through real intake and memory consumers."""
from copy import deepcopy
from datetime import timedelta
import gzip
import json

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.orchestrator.sources import awc_observed as runner
from src.state import DEFAULT_STATE
from src.two_bot.memory import (
    build_memory_slice, bundle_memory_snapshot, record_published_draft, record_shipped,
    _story_bundle_from_metadata,
)
from src.two_bot.types import WriterResult
from src.two_bot.writer import build_writer_user_prompt
from tests.live_content_harness import trap_network
from tests.test_awc_observed import NOW, catalog, csv_bytes, reports

TEXT = "Earlier invented airport comparison; no physical episode is asserted."


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    for key, value in {
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1", source.ENABLE_FLAG: "1",
        "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1",
        "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_REFILL_ENABLED": "0", "THEHEAT_PRODUCTION_PAUSED": "0",
    }.items():
        monkeypatch.setenv(key, value)


def nominate(monkeypatch, state, *, cold="TAAA", hot="TBBB", at=NOW, reverse=False):
    rows, stations = reports(), catalog()
    observed = at - timedelta(minutes=10)
    for row, station, station_id in zip(rows, stations, (cold, hot)):
        row[0] = row[0].replace(row[1], station_id).replace("151200Z", observed.strftime("%d%H%MZ"))
        row[1], row[2] = station_id, observed.isoformat().replace("+00:00", "Z")
        station["icaoId"] = station_id
    calls = []

    def read(url, *, params=None):
        assert params is None
        calls.append(url)
        if url == source.STATIONS_URL:
            return gzip.compress(json.dumps(stations).encode(), mtime=0)
        assert url == source.METARS_URL
        return gzip.compress(csv_bytes(rows[::-1] if reverse else rows), mtime=0)

    monkeypatch.setattr(source, "_read", read)
    run = {"id": "invented-memory-fixture", "sources": []}
    with freeze_time(at):
        runner.run_awc_observed(state, run)
    assert len(calls) == 2 and run["sources"][-1]["observed"] == 1
    assert run["sources"][-1]["promoted"] == 1, run
    candidate = state["_triage_queue"].pop(0)
    assert candidate.source == "awc_observed"
    return candidate.bundle


def remember(state, bundle):
    with freeze_time(NOW):
        record_shipped(state, bundle, WriterResult(TEXT, None, "airport_fixture", None, None,
            "Invented recorder input; no model or publication."), [], shipped_at=NOW.isoformat())


@pytest.mark.parametrize("cold,hot,day,reverse", [
    ("TAAA", "TCCC", 0, False), ("TDDD", "TBBB", 0, False),
    ("TAAA", "TBBB", 1, False), ("TAAA", "TBBB", 0, True),
])
def test_real_source_queue_and_writer_memory_do_not_invent_one_episode(monkeypatch, cold, hot, day, reverse):
    state = deepcopy(DEFAULT_STATE)
    first = nominate(monkeypatch, state)
    remember(state, first)
    current = nominate(monkeypatch, state, cold=cold, hot=hot, at=NOW + timedelta(days=day), reverse=reverse)
    memory = build_memory_slice(state, current, now=NOW + timedelta(days=day))
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert memory.shipped_tweet_texts == [TEXT] and memory.used_framings == ["airport_fixture"]
    assert state["memory"]["ongoing_events"] == []
    assert len(state["memory"]["shipped_tweets"]) == 1
    prompt = build_writer_user_prompt(current, memory)
    assert '"ongoing_event": null' in prompt and '"recent_tweets_same_event": []' in prompt
    assert "days_running" not in prompt


@pytest.mark.parametrize("same_id", [False, True])
def test_legacy_ongoing_rows_remain_intact_without_physical_authority(monkeypatch, same_id):
    state = deepcopy(DEFAULT_STATE)
    bundle = nominate(monkeypatch, state)
    legacy = {"event_id": bundle.event_id if same_id else "metar_pair_TAAA_TCCC_2026-11-14",
              "signal_kind": source.KIND, "country": "", "region": bundle.where,
              "first_seen": "2026-11-01", "last_seen": "2026-11-14", "days_running": 14}
    state["memory"]["ongoing_events"] = [deepcopy(legacy)]
    restored = json.loads(json.dumps(state))
    memory = build_memory_slice(restored, bundle, now=NOW)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert restored["memory"]["ongoing_events"] == [legacy]


@pytest.mark.parametrize("marker", ["kind", "id", "schema"])
def test_incomplete_legacy_family_markers_never_restore_display_name_fallback(monkeypatch, marker):
    state = deepcopy(DEFAULT_STATE)
    bundle = nominate(monkeypatch, state)
    if marker != "kind":
        bundle.signal_kind = "invented_legacy_kind"
    if marker != "id":
        bundle.event_id = "invented_legacy_id"
    if marker != "schema":
        bundle.raw_signal_dump = {}
    remember(state, bundle)
    assert state["memory"]["ongoing_events"] == []
    assert build_memory_slice(state, bundle, now=NOW).recent_tweets_same_event == []


@pytest.mark.parametrize("compact", [False, True])
@pytest.mark.parametrize("marker_only", [False, True])
def test_actual_publication_snapshot_restore_is_idempotent_without_episode(monkeypatch, compact, marker_only):
    state = deepcopy(DEFAULT_STATE)
    bundle = nominate(monkeypatch, state)
    if marker_only:
        bundle.signal_kind, bundle.event_id = "invented_legacy_kind", "invented_legacy_id"
    snapshot = json.loads(json.dumps(bundle_memory_snapshot(bundle) if compact else bundle.to_dict()))
    memory_only = _story_bundle_from_metadata({"bundle": snapshot}, {})
    assert source.is_family(memory_only)
    # A restrictive memory marker never reconstructs source evidence or grants
    # permission to generate/approve a fresh weather claim.
    with pytest.raises(source.ObservedHeld):
        source.validate_bundle(memory_only, now=NOW)
    draft = {"text": TEXT, "status": "posted", "tweet_id": "invented-offline-receipt",
             "event_id": bundle.event_id, "review_context": {"two_bot": {
                 "signal_kind": source.KIND, "bundle": snapshot, "angle_chosen": "airport_fixture"}}}
    assert record_published_draft(state, draft) and not record_published_draft(state, draft)
    assert len(state["memory"]["shipped_tweets"]) == 1
    assert state["memory"]["ongoing_events"] == []


def test_physical_binding_still_requires_resolved_context_first(monkeypatch):
    state = deepcopy(DEFAULT_STATE)
    bundle = nominate(monkeypatch, state)
    bundle.raw_signal_dump["physical_episode"] = {"invented": "unresolved"}
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_memory_slice(state, bundle, now=NOW)
    with pytest.raises(ValueError):
        remember(state, bundle)
