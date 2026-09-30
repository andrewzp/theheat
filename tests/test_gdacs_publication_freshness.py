"""Synthetic timestamps distinguish source publication from event validity windows."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest
import responses

from src.data import gdacs
from src.data.source_status import SourceFetchError
from src.orchestrator.sources.gdacs import run_gdacs
from src.state import DEFAULT_STATE
from src.two_bot.intern.disasters import build_global_disaster_bundle

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
CURRENT = "2026-09-30T12:00:00Z"
NS = "{http://www.gdacs.org}"
LEVELS = {"Green": 0, "Orange": 1, "Red": 2}


def item(*, event_id="synthetic", level="Red", published=CURRENT, modified=None,
         start="2026-09-01T00:00:00Z", end="2026-10-02T00:00:00Z", country="India"):
    node = ET.Element("item")
    for name, value in {
        "title": "Synthetic event alert", "description": "Synthetic timing fixture.",
        "pubDate": published, NS + "eventtype": "FL", NS + "alertlevel": level,
        NS + "eventid": event_id, NS + "country": country, NS + "fromdate": start,
        NS + "todate": end, NS + "datemodified": modified,
        "{http://www.georss.org/georss}point": "20 77",
    }.items():
        if value is not None:
            ET.SubElement(node, name).text = value
    return node


def feed(*items, published=CURRENT):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    if published is not None:
        ET.SubElement(channel, "pubDate").text = published
    for node in items or [item()]:
        channel.append(node)
    return ET.tostring(root, encoding="unicode")


def parse(body, *, now=NOW):
    diagnostics = {}
    events, date = gdacs._events_from_georss(body, min_level=2, severity_order=LEVELS,
                                          diagnostics=diagnostics, now=now)
    return events, date, diagnostics


def test_past_start_and_recent_modification_keep_ongoing_alert_eligible():
    events, date, diagnostics = parse(feed(item(published="2026-09-01T00:00:00Z", modified=CURRENT)))
    assert len(events) == 1 and date.isoformat() == "2026-09-30"
    provenance = events[0].source_provenance
    assert provenance["fromdate"] == "2026-09-01T00:00:00Z"
    assert provenance["todate"] == "2026-10-02T00:00:00Z"
    assert provenance["source_update_kind"] == "datemodified" and provenance["source_updated_at"] == CURRENT
    assert diagnostics["withheld_selected_alerts"] == 0
    bundle = build_global_disaster_bundle(events[0])
    assert {"label": "source_updated_at", "value": CURRENT} in bundle.current_facts
    assert any(f["label"] == "claim_limit" and "does not establish observed intensity" in f["value"] for f in bundle.current_facts)


def test_future_event_start_never_freshens_stale_feed():
    with pytest.raises(SourceFetchError, match="stale data"):
        parse(feed(item(start="2026-10-05T00:00:00Z", published="2026-09-10T00:00:00Z"),
                   published="2026-09-10T00:00:00Z"))


def test_recent_channel_or_green_event_cannot_revive_stale_red():
    events, _, diagnostics = parse(feed(
        item(published="2026-09-10T00:00:00Z"), item(level="Green", start="2026-10-05T00:00:00Z"),
    ))
    assert events == [] and diagnostics["selected_before_freshness"] == 1
    assert diagnostics["withheld_by_reason"]["stale"] == 1
    assert diagnostics["status"] == "withheld_selected_alerts"


@pytest.mark.parametrize("modified,published,reason", [
    (None, None, "missing"), ("bad", CURRENT, "invalid"),
    ("2026-09-30", CURRENT, "invalid"), ("2026-09-30T12:00:00", CURRENT, "invalid"),
    ("2026-09-30T12:05:01Z", CURRENT, "future"),
    ("2026-09-26T23:59:59Z", CURRENT, "stale"),
    (None, "Wed, 30 Sep 2026 12:00:00 -0000", "invalid"),
])
def test_unusable_preferred_update_withheld_without_falling_back(modified, published, reason):
    events, _, diagnostics = parse(feed(item(modified=modified, published=published)))
    assert events == [] and diagnostics["withheld_by_reason"][reason] == 1


@pytest.mark.parametrize("published,accepted", [
    ("2026-09-30T12:05:00Z", True), ("2026-09-30T12:05:01Z", False),
    ("2026-09-27T00:00:00Z", True), ("2026-09-26T23:59:59Z", False),
    ("2026-09-27T00:30:00+01:00", False), ("2026-09-26T23:30:00-01:00", True),
])
def test_clock_skew_day_age_and_offset_midnight_boundaries(published, accepted):
    events, _, _ = parse(feed(item(published=published)))
    assert bool(events) is accepted


def test_absent_channel_uses_item_update_with_timezone_normalization():
    events, newest, diagnostics = parse(feed(item(modified="2026-09-30T14:00:00+02:00"), published=None))
    assert len(events) == 1 and str(newest) == "2026-09-30"
    assert diagnostics["publication_clock"] == "item_update" and diagnostics["publication_time"] == CURRENT


@pytest.mark.parametrize("published", ["bad", "", "2026-09-30", "2026-10-05T00:00:00Z"])
def test_explicit_invalid_channel_publication_is_not_hidden_by_current_item(published):
    with pytest.raises(gdacs.GDACSPublicationError, match="channel publication"):
        parse(feed(item(), published=published))


def test_no_source_clock_cannot_use_retrieval_or_event_start():
    with pytest.raises(gdacs.GDACSPublicationError, match="no usable"):
        parse(feed(item(published=None, start=CURRENT), published=None))


def test_independently_fresh_selected_alert_survives_an_unverifiable_peer():
    events, _, diagnostics = parse(feed(item(event_id="bad", published=None), item(event_id="good")))
    assert [e.source_event_id for e in events] == ["good"]
    assert diagnostics["selected_before_freshness"] == 2 and diagnostics["selected_alerts"] == 1
    assert diagnostics["withheld_selected_alerts"] == 1


def test_no_red_alerts_is_distinct_from_all_red_alerts_withheld():
    no_red = parse(feed(item(level="Green")))[2]
    withheld = parse(feed(item(published=None)))[2]
    assert no_red["status"] == "valid_no_qualifying_alerts"
    assert withheld["status"] == "withheld_selected_alerts"


@responses.activate
def test_runner_exposes_withholding_without_drafting_or_extra_source_calls(monkeypatch):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: NOW)
    responses.add(responses.GET, gdacs.GDACS_URL, json={})
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=feed(item(published=None)))
    enqueue = Mock(side_effect=AssertionError("withheld alerts must not reach drafting"))
    monkeypatch.setattr("src.orchestrator.sources.gdacs._enqueue_story_candidate", enqueue)
    state = deepcopy(DEFAULT_STATE)
    run = {"sources": []}
    run_gdacs(state, run)
    enqueue.assert_not_called()
    assert len(responses.calls) == 2
    source = run["sources"][0]
    assert source["status"] == "degraded" and source["observed"] == source["promoted"] == 0
    assert "withheld_selected_alerts:1" in source["note"]
    assert source["details"]["feed_diagnostics"]["withheld_by_reason"]["missing"] == 1


@pytest.mark.parametrize("now", [0, "today", datetime(2026, 9, 30)])
def test_invalid_or_naive_check_clock_refused(now):
    with pytest.raises(gdacs.GDACSPublicationError, match="aware"):
        parse(feed(), now=now)
