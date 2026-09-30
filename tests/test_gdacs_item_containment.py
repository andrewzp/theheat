"""Synthetic malformed peers cannot discard valid alerts or certify freshness."""

from copy import deepcopy
from itertools import permutations
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest
import responses

from src.data import gdacs
from src.data.source_status import SourceFetchError
from src.orchestrator.sources.gdacs import run_gdacs
from src.state import DEFAULT_STATE
from tests.test_gdacs_publication_freshness import CURRENT, NOW, NS, feed, item, parse


def broken(*, level="Red", field=NS + "country", value=None):
    node = item(event_id="broken", level=level)
    field_node = node.find(field)
    if value is None:
        node.remove(field_node)
    else:
        field_node.text = value
    return node


@pytest.mark.parametrize("level", ["Green", "Red"])
@pytest.mark.parametrize("field,reason", [
    (NS + "eventtype", "event_type"), (NS + "alertlevel", "alert_level"),
    (NS + "eventid", "event_id"), (NS + "country", "country"),
    (NS + "fromdate", "from_date"), ("description", "description"),
    ("title", "name"), ("{http://www.georss.org/georss}point", "coordinates"),
])
def test_missing_required_field_quarantines_only_that_item(level, field, reason):
    events, _, diagnostics = parse(feed(broken(level=level, field=field), item(event_id="valid")))
    assert [e.source_event_id for e in events] == ["valid"]
    assert diagnostics["feed_items_total"] == 2 and diagnostics["feed_items_validated"] == 1
    assert diagnostics["alert_counts"] == {"Green": 0, "Orange": 0, "Red": 1}
    assert diagnostics["quarantined_items"] == 1
    assert diagnostics["rejected_by_field"][reason] == 1
    assert sum(diagnostics["rejected_by_field"].values()) == 1
    assert diagnostics["rejected_unknown_alert_level"] == int(reason == "alert_level")
    assert diagnostics["rejected_selected_alerts"] == int(level == "Red" and reason != "alert_level")
    assert diagnostics["status"] == "partial_feed"


def test_multiple_invalid_fields_count_one_item_and_each_failed_field():
    bad = broken(field=NS + "alertlevel", value="BLUE")
    bad.remove(bad.find(NS + "country"))
    events, _, diagnostics = parse(feed(bad, item(level="Green")))
    assert not events and diagnostics["quarantined_items"] == 1
    assert diagnostics["rejected_unknown_alert_level"] == 1
    assert diagnostics["rejected_selected_alerts"] == 0
    assert diagnostics["rejected_by_field"]["country"] == diagnostics["rejected_by_field"]["alert_level"] == 1


@pytest.mark.parametrize("updated", [CURRENT, "2026-10-02T00:00:00Z"])
def test_rejected_item_cannot_freshen_a_feed_without_channel_publication(updated):
    bad = broken()
    bad.find("pubDate").text = updated
    with pytest.raises(gdacs.GDACSPublicationError, match="stale data"):
        parse(feed(bad, item(published="2026-09-01T00:00:00Z"), published=None))


def test_rejected_item_cannot_supply_only_missing_feed_publication():
    with pytest.raises(gdacs.GDACSPublicationError, match="no usable"):
        parse(feed(broken(), item(published=None), published=None))


def test_mixed_quarantines_and_freshness_failures_are_order_independent():
    nodes = [broken(), item(event_id="stale", published="2026-09-01T00:00:00Z"),
             item(event_id="eligible")]
    expected = None
    for ordering in permutations(nodes):
        events, _, diagnostics = parse(feed(*ordering))
        assert [e.source_event_id for e in events] == ["eligible"]
        assert diagnostics["rejected_selected_alerts"] == diagnostics["withheld_selected_alerts"] == 1
        assert diagnostics["withheld_by_reason"]["stale"] == 1
        assert diagnostics["status"] == "partial_feed"
        if expected is not None:
            assert diagnostics == expected
        expected = diagnostics


@responses.activate
def test_all_invalid_items_fail_source_without_extra_witness_calls(monkeypatch):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: NOW)
    responses.add(responses.GET, gdacs.GDACS_URL, json={})
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=feed(broken(), broken(level="Green")))
    witness = Mock(side_effect=AssertionError("Schema failure cannot purchase more source calls"))
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", witness)
    with pytest.raises(SourceFetchError, match="all 2 items quarantined; invalid fields: country:2"):
        gdacs.fetch_disasters(strict=True)
    assert not witness.called and len(responses.calls) == 2


@responses.activate
@pytest.mark.parametrize("valid_level,expected_count", [("Green", 0), ("Red", 1)])
def test_runner_exposes_quarantine_and_only_enqueues_valid_peers(monkeypatch, valid_level, expected_count):
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: NOW)
    responses.add(responses.GET, gdacs.GDACS_URL, json={})
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL,
                  body=feed(broken(), item(event_id="valid", level=valid_level)))
    enqueue = Mock()
    monkeypatch.setattr("src.orchestrator.sources.gdacs._enqueue_story_candidate", enqueue)
    monkeypatch.setattr("src.orchestrator.sources.gdacs._should_draft", lambda *a: True)
    run = {"sources": []}
    run_gdacs(deepcopy(DEFAULT_STATE), run)
    assert enqueue.call_count == expected_count and len(responses.calls) == 2
    if expected_count:
        assert enqueue.call_args.kwargs["bundle"].raw_signal_dump["source_event_id"] == "valid"
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == row["promoted"] == expected_count
    assert "quarantined_items:1" in row["note"]
    assert row["details"]["feed_diagnostics"]["status"] == "partial_feed"
    assert row["details"]["feed_diagnostics"]["rejected_selected_alerts"] == 1
