"""Bounded GDACS GeoRSS recovery from source-explicit unknown cyclone country."""
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import responses

from src.data import gdacs
from src.data._freshness import assert_freshness
from src.data.source_status import SourceFetchError
from src.orchestrator.sources.gdacs import run_gdacs
from src.state import DEFAULT_STATE

SOURCE = Path(__file__).parent / "fixtures/gdacs_georss_unknown_country.xml"
LEVELS = {"Green": 0, "Orange": 1, "Red": 2}


@pytest.fixture(autouse=True)
def fixed_publication_clock(monkeypatch):
    # Source/fixture date screens use an explicit clock, not a production pass.
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: datetime(2026, 9, 9, tzinfo=UTC))


def parsed(text=None, level=2):
    diagnostics = {}
    events, newest = gdacs._events_from_georss(text or SOURCE.read_text(), min_level=level,
                                             severity_order=LEVELS, diagnostics=diagnostics)
    return events, newest, diagnostics


def changed(field, value):
    root = ET.fromstring(SOURCE.read_text())
    item = root.find("channel/item")
    node = item.find(field, gdacs._GEORSS_NS)
    if value is None:
        item.remove(node)
    else:
        node.text = value
    return ET.tostring(root, encoding="unicode")


def test_explicit_unknown_country_in_green_cyclone_does_not_block_red_alert():
    events, newest, diagnostics = parsed()
    assert len(events) == 1 and events[0].name == "Engineered Red flood alert"
    assert events[0].source_leg == gdacs.GDACS_GEORSS_LEG
    assert str(newest) == "2026-09-09"
    assert diagnostics == {"source_leg": "georss", "feed_items_validated": 2,
        "alert_counts": {"Green": 1, "Orange": 0, "Red": 1}, "selected_alerts": 1,
        "episode_alert_counts": {"Green": 1, "Orange": 0, "Red": 1, "unknown": 0},
        "current_flag_counts": {"true": 2, "false": 0, "unknown": 0},
        "current_candidates_examined": 1, "withheld_current_alerts": 0,
        "withheld_current_by_reason": {"not_current": 0, "unverified_current": 0,
            "unverified_episode": 0, "episode_below_threshold": 0, "inconsistent_alert_levels": 0},
        "unknown_country_items": 1, "status": "valid_alerts",
        "feed_items_total": 2, "quarantined_items": 0,
        "rejected_by_field": {"event_type": 0, "alert_level": 0, "event_id": 0,
            "country": 0, "from_date": 0, "description": 0, "name": 0, "coordinates": 0},
        "rejected_selected_alerts": 0, "rejected_unknown_alert_level": 0,
        "selected_before_freshness": 1, "withheld_selected_alerts": 0,
        "withheld_by_reason": {"missing": 0, "invalid": 0, "future": 0, "stale": 0},
        "publication_time": "2026-09-09T00:00:00Z", "publication_clock": "channel_pubDate"}
    all_events, _, _ = parsed(level=0)
    assert all_events[0].name == "TWENTYTHREE-26" and all_events[0].country == ""


@pytest.mark.parametrize("field,value,diagnostic", [
    ("gdacs:country", None, "country"),
    ("gdacs:eventtype", "FL", "country"),
    ("gdacs:eventtype", "NOT_A_TYPE", "event_type"),
    ("gdacs:alertlevel", "", "alert_level"),
    ("gdacs:alertlevel", "BLUE", "alert_level"),
    ("gdacs:eventid", "", "event_id"),
    ("gdacs:fromdate", "not a date", "from_date"),
    ("georss:point", "not coordinates", "coordinates"),
    ("georss:point", "NaN 133.8", "coordinates"),
    ("georss:point", "28.5 181", "coordinates"),
])
def test_unknown_country_exception_does_not_skip_core_validation(field, value, diagnostic):
    # The malformed cyclone remains ineligible; its valid flood peer survives.
    events, _, diagnostics = parsed(changed(field, value), level=0)
    assert [event.source_event_id for event in events] == ["fixture-red"]
    assert diagnostics["quarantined_items"] == 1
    assert diagnostics["rejected_by_field"][diagnostic] == 1
    assert diagnostics["status"] == "partial_feed"
    root = ET.fromstring(changed(field, value))
    channel = root.find("channel")
    channel.remove(channel.findall("item")[1])
    with pytest.raises(SourceFetchError, match=diagnostic):
        parsed(ET.tostring(root, encoding="unicode"))


@pytest.mark.parametrize("body", ["<rss><channel /></rss>", "<rss />", "<html><body>maintenance</body></html>"])
def test_empty_or_non_feed_document_is_not_success(body):
    with pytest.raises(SourceFetchError, match="item collection"):
        parsed(body)


def test_malformed_xml_and_parser_bounds_are_not_empty_success(monkeypatch):
    with pytest.raises(ET.ParseError):
        parsed("<rss><channel>")
    monkeypatch.setattr(gdacs, "MAX_GEORSS_BYTES", 20)
    with pytest.raises(SourceFetchError, match="byte bound"):
        parsed()
    monkeypatch.setattr(gdacs, "MAX_GEORSS_BYTES", 2_000_000)
    monkeypatch.setattr(gdacs, "MAX_GEORSS_ITEMS", 1)
    with pytest.raises(SourceFetchError, match="item collection"):
        parsed()


@responses.activate
@pytest.mark.parametrize("json_payload", [{}, [], {"features": []}, {"features": [{}]}, {"features": [{"properties": {}}]}])
def test_unqualified_map_payload_is_never_requested_when_rss_is_available(json_payload, monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_URL, json=json_payload)
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=SOURCE.read_text())
    events = gdacs.fetch_disasters(strict=True)
    assert len(events) == 1
    assert "primary_error_class" not in events.source_diagnostics
    assert events.source_diagnostics["configured_product"] == "gdacs-georss"
    assert events.source_diagnostics["map_status"] == "withdrawn_unqualified"
    assert [call.request.url for call in responses.calls] == [gdacs.GDACS_GEORSS_URL]
    assert events.source_diagnostics["feed_items_validated"] == 2


@responses.activate
@pytest.mark.parametrize("rss", ["<rss><channel /></rss>", "<rss><channel>"])
def test_malformed_or_empty_fallback_does_not_invoke_unrelated_witnesses(rss, monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=rss)
    def forbidden(*args, **kwargs):
        raise AssertionError("Schema failure must not trigger more source calls")
    monkeypatch.setattr(gdacs, "_fetch_subtype_witnesses", forbidden)
    with pytest.raises(SourceFetchError, match="schema drift"):
        gdacs.fetch_disasters(strict=True)


@responses.activate
def test_zero_selected_alerts_keeps_validated_feed_and_fallback_telemetry(monkeypatch):
    body = SOURCE.read_text().replace("<gdacs:alertlevel>Red</gdacs:alertlevel>", "<gdacs:alertlevel>Orange</gdacs:alertlevel>")
    body = body.replace("<gdacs:episodealertlevel>Red</gdacs:episodealertlevel>", "<gdacs:episodealertlevel>Orange</gdacs:episodealertlevel>")
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=body)
    state = deepcopy(DEFAULT_STATE)
    run = {"sources": []}
    run_gdacs(state, run)
    source = run["sources"][0]
    assert source["status"] == "degraded" and source["observed"] == 0
    assert "validated_feed_items:2 selected_alerts:0" in source["note"]
    details = source["details"]["feed_diagnostics"]
    assert details["status"] == "valid_no_qualifying_alerts"
    assert details["alert_counts"] == {"Green": 1, "Orange": 1, "Red": 0}
    assert state.get("_triage_queue", []) == []


@responses.activate
def test_stale_valid_fallback_still_fails_freshness(monkeypatch):
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=SOURCE.read_text())
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(SourceFetchError, match="stale data"):
        gdacs._fetch_disasters_primary(strict=True)


def source_events():
    from src.data.cyclones import CycloneAdvisory
    from src.data.usgs_quakes import SignificantEarthquakeEvent
    json_event = gdacs._events_from_features([{"properties": {
        "eventtype": "FL", "alertlevel": "Red", "eventid": "fixture-json",
        "name": "Engineered flood", "country": "India", "description": "Synthetic fixture",
    }}], min_level=2, severity_order=LEVELS)[0]
    rss_event = parsed()[0][0]
    quake = gdacs._quake_to_gdacs_event(SignificantEarthquakeEvent(
        event_id="quake-fixture", usgs_id="fixture-quake", title="Engineered earthquake",
        place="Test location", magnitude=7.5, time="2026-09-09T01:00:00Z",
        updated="2026-09-09T02:00:00Z", url="https://earthquake.usgs.gov/earthquakes/eventpage/fixture-quake",
    ))
    cyclone = gdacs._cyclone_to_gdacs_event(CycloneAdvisory(
        source="nhc", storm_id="fixture-cyclone", storm_name="Engineered cyclone", basin="Atlantic",
        advisory_number="12", issued_at="2026-09-09T00:00:00Z", wind_kt=120,
        public_advisory_url="https://www.nhc.noaa.gov/fixture-advisory.shtml",
        source_leg="nhc_rss",
    ))
    return json_event, rss_event, quake, cyclone


def test_each_served_adapter_preserves_actual_source_identity_through_intern():
    from src.two_bot.intern.disasters import build_global_disaster_bundle
    json_event, rss_event, quake, cyclone = source_events()
    expected = [
        (json_event, "gdacs-events-map", gdacs.GDACS_URL, "fixture-json"),
        (rss_event, "gdacs-georss", gdacs.GDACS_GEORSS_URL, "fixture-red"),
        (quake, "usgs-significant-earthquake", "https://earthquake.usgs.gov/earthquakes/eventpage/fixture-quake", "fixture-quake"),
        (cyclone, "nhc-cyclone-advisory", "https://www.nhc.noaa.gov/fixture-advisory.shtml", "fixture-cyclone"),
    ]
    for event, product, url, source_id in expected:
        bundle = build_global_disaster_bundle(event)
        assert bundle.raw_signal_dump["source_product"] == product
        assert bundle.raw_signal_dump["source_url"] == url
        assert bundle.raw_signal_dump["source_event_id"] == source_id
        assert {"label": "source_product", "value": product} in bundle.current_facts
    assert json_event.source_leg is None and rss_event.source_leg == "georss"
    assert cyclone.source_provenance["original_source_leg"] == "nhc_rss"
    assert not quake.source_url.startswith("https://www.gdacs.org")


def test_unknown_legacy_origin_is_not_invented_by_bundle_builder():
    from src.two_bot.intern.disasters import build_global_disaster_bundle
    legacy = gdacs.GlobalDisasterEvent("Flood", "Legacy event", "India", "Red", "Retained", "legacy-id")
    bundle = build_global_disaster_bundle(legacy)
    assert bundle.raw_signal_dump["source_product"] == bundle.raw_signal_dump["source_url"] == ""
    assert not any(row["label"] == "source_product" for row in bundle.current_facts)
    unknown_country = parsed(level=0)[0][0]
    unknown_bundle = build_global_disaster_bundle(unknown_country)
    assert unknown_bundle.raw_signal_dump["country"] == ""
    assert any(row["label"] == "claim_limit" and "do not infer" in row["value"] for row in unknown_bundle.current_facts)


def test_actual_adapter_provenance_passes_p05_minimum_contract_when_integrated():
    strict = pytest.importorskip("src.two_bot.strict_contract", reason="P05 is integrated by the release owner")
    from src.two_bot.intern.disasters import build_global_disaster_bundle
    for event in source_events():
        assert strict.bundle_schema_issues(build_global_disaster_bundle(event)) == []
