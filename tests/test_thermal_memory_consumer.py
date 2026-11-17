"""Invented thermal observations through real source and publication-memory consumers."""
from copy import deepcopy
import csv
from datetime import UTC, datetime, timedelta
import io
import json

import pytest

from src.data import firms
from src.data.fire_footprint import FireComplex
from src.data.fire_source_contract import FIRMS_PUBLIC_URL, HMS_BASE, HMS_PRODUCT
from src.editorial import hazard_episodes
from src.orchestrator.sources import firms as runner
from src.state import DEFAULT_STATE
from src.two_bot.intern.fire import build_fire_bundle, build_fire_footprint_bundle
from src.two_bot.memory import (
    build_memory_slice, bundle_memory_snapshot, record_published_draft, record_shipped,
)
from src.two_bot.types import WriterResult
from src.two_bot.writer import build_writer_user_prompt
from tests.fire_source_fixtures import firms_row, hms_row
from tests.live_content_harness import trap_network


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    monkeypatch.setenv(hazard_episodes.FLAG, "0")


def source_events(product="VIIRS_SNPP_NRT", *, points=None, when=None):
    instant = when or datetime.now(UTC)
    points = points or ([(35, -120), (40, -121)] if product == HMS_PRODUCT
                        else [(-25, 117), (-32, 126)])
    raw = []
    for lat, lon in points:
        row = hms_row(when=instant) if product == HMS_PRODUCT else firms_row(product, when=instant)
        row.update({"Lat" if product == HMS_PRODUCT else "latitude": str(lat),
                    "Lon" if product == HMS_PRODUCT else "longitude": str(lon)})
        raw.append(row)
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(raw[0]))
    writer.writeheader()
    writer.writerows(raw)
    rows = firms._qualified_rows(stream.getvalue(), product, instant)
    url = f"{HMS_BASE}/{instant:%Y/%m}/hms_fire{instant:%Y%m%d}.txt" if product == HMS_PRODUCT else FIRMS_PUBLIC_URL
    return [firms._event(row, url, leg="noaa_hms" if product == HMS_PRODUCT else None) for row in rows]


def remember(state, bundle):
    record_shipped(state, bundle, WriterResult(
        tweet="Earlier invented thermal observation; no current-incident authority.",
        kill_reason=None, angle_chosen="thermal_fixture", era_anchor_used=None,
        peer_comparison_used=None, reasoning="Explicit offline recorder input; no model or post."), [])


@pytest.mark.parametrize("enabled", ["0", "1"])
@pytest.mark.parametrize("product", ["VIIRS_SNPP_NRT", "MODIS_NRT", HMS_PRODUCT])
def test_distinct_qualified_cells_in_one_real_geocoder_region_do_not_share_incident_memory(
    monkeypatch, enabled, product,
):
    monkeypatch.setenv(hazard_episodes.FLAG, enabled)
    events = source_events(product)
    assert len(events) == 2 and events[0].event_id != events[1].event_id
    assert events[0].nearest_city == events[1].nearest_city
    assert events[0].country == events[1].country
    monkeypatch.setattr(runner, "_fetch_firms_with_attempts", lambda attempts: events)
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-thermal-memory-run", "sources": []}
    runner.run_firms(state, run)
    assert run["sources"][-1]["promoted"] == 2
    previous, current = state["_triage_queue"]
    remember(state, previous.bundle)
    memory = build_memory_slice(state, current.bundle)
    assert memory.ongoing_event is None
    assert memory.recent_tweets_same_event == []
    assert memory.source_report_series is None
    assert state["memory"]["ongoing_events"] == []
    assert memory.recent_tweets_same_country
    assert memory.shipped_tweet_texts == memory.recent_tweets_same_country
    assert memory.recent_categories == ["fire"]
    assert memory.used_framings == ["thermal_fixture"]
    prompt = build_writer_user_prompt(current.bundle, memory)
    assert '"ongoing_event": null' in prompt
    assert "days_running" not in prompt


@pytest.mark.parametrize("day_delta", [0, 1])
@pytest.mark.parametrize("product", ["VIIRS_SNPP_NRT", HMS_PRODUCT])
def test_exact_source_cell_or_next_day_does_not_prove_physical_continuity(day_delta, product):
    now = datetime.now(UTC)
    point = [(35, -120)] if product == HMS_PRODUCT else [(-25, 117)]
    before = build_fire_bundle(source_events(product, points=point, when=now - timedelta(days=day_delta))[0])
    current = build_fire_bundle(source_events(product, points=point, when=now)[0])
    state = deepcopy(DEFAULT_STATE)
    remember(state, before)
    memory = build_memory_slice(state, current, now=now)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert memory.recent_tweets_same_country and memory.recent_categories == ["fire"]
    assert state["memory"]["ongoing_events"] == []


@pytest.mark.parametrize("same_id", [False, True])
def test_legacy_ongoing_rows_are_preserved_but_not_promoted_by_region_or_exact_id(same_id):
    first, second = [build_fire_bundle(event) for event in source_events()]
    state = deepcopy(DEFAULT_STATE)
    legacy = {"event_id": second.event_id if same_id else first.event_id,
              "signal_kind": "fire", "country": "AU", "region": second.where,
              "first_seen": "2026-01-01", "last_seen": "2026-01-05", "days_running": 5}
    state["memory"]["ongoing_events"] = [deepcopy(legacy)]
    memory = build_memory_slice(state, second)
    assert memory.ongoing_event is None and memory.recent_tweets_same_event == []
    assert state["memory"]["ongoing_events"] == [legacy]


def test_actual_snapshot_json_restore_records_general_publication_without_physical_duration():
    bundle = build_fire_bundle(source_events()[0])
    snapshot = json.loads(json.dumps(bundle_memory_snapshot(bundle)))
    state = deepcopy(DEFAULT_STATE)
    draft = {"text": "Invented retained publication, never sent.", "status": "posted",
             "tweet_id": "invented-offline-receipt", "event_id": bundle.event_id,
             "review_context": {"two_bot": {"signal_kind": "fire", "bundle": snapshot,
                                             "angle_chosen": "thermal_fixture"}}}
    assert record_published_draft(state, draft)
    assert not record_published_draft(state, draft)
    assert len(state["memory"]["shipped_tweets"]) == 1
    assert state["memory"]["ongoing_events"] == []
    assert build_memory_slice(state, bundle).recent_tweets_same_country == [draft["text"]]


def test_unresolved_physical_binding_still_refuses_before_any_thermal_fallback():
    bundle = build_fire_bundle(source_events()[0])
    bundle.raw_signal_dump["physical_episode"] = {"invented": "not a resolved binding"}
    state = deepcopy(DEFAULT_STATE)
    with pytest.raises(ValueError, match="resolved_episode_context_required"):
        build_memory_slice(state, bundle)
    with pytest.raises(ValueError):
        remember(state, bundle)


def test_perimeter_bundle_memory_remains_outside_thermal_measurement_change():
    # A real perimeter builder, not a relabelled thermal packet. This is memory
    # compatibility only, not a qualified real perimeter or a physical truth claim.
    bundle = build_fire_footprint_bundle(FireComplex(
        complex_id="invented-perimeter", name="Invented perimeter", country="Canada",
        region="Alberta", hectares=12000, start_date=None, tier=0,
        event_id="fire_footprint_invented_1"))
    state = deepcopy(DEFAULT_STATE)
    remember(state, bundle)
    assert build_memory_slice(state, bundle).ongoing_event["event_id"] == bundle.event_id
