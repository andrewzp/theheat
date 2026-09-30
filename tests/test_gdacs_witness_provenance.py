"""Synthetic source outage -> real runner/state -> dashboard health contract."""
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest
import requests
import responses

from src import state
from src.data import gdacs
from src.data.cyclones import CycloneAdvisory
from src.data.source_status import SourceFetchError, SourceSkipped
from src.data.usgs_quakes import SignificantEarthquakeEvent
from src.orchestrator.sources.gdacs import run_gdacs

NAMES = ("usgs_quakes", "nhc", "jtwc")
ROOT = Path(__file__).resolve().parents[1]


def feed_mocks(monkeypatch, failed=(), *, records=None, error=None):
    records = records or {}
    mocks = {}
    for name in NAMES:
        mock = Mock(side_effect=(error or requests.Timeout("synthetic unavailable leg")) if name in failed else None,
                    return_value=records.get(name, []))
        module = getattr(gdacs, name)
        method = "fetch_significant_earthquakes" if name == "usgs_quakes" else "fetch_active_cyclones"
        monkeypatch.setattr(module, method, mock)
        mocks[name] = mock
    return mocks


def outage():
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, status=504)


def persist_and_project(monkeypatch, bot_state, run):
    """Exercise production Gist serialization/merge with synthetic HTTP only."""
    state.finalize_run(bot_state, run)
    persisted = deepcopy(state.DEFAULT_STATE)
    monkeypatch.setattr(state, "_configured_backend", lambda: "gist")
    monkeypatch.setattr(state, "GIST_ID", "synthetic-witness-state")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "offline-placeholder")
    url = "https://api.github.com/gists/synthetic-witness-state"

    def read_callback(_request):
        body = {"files": {"state.json": {"content": json.dumps(persisted)}}}
        return 200, {"Content-Type": "application/json"}, json.dumps(body)

    def write_callback(request):
        nonlocal persisted
        persisted = json.loads(json.loads(request.body)["files"]["state.json"]["content"])
        return 200, {}, "{}"

    responses.add_callback(responses.GET, url, callback=read_callback)
    responses.add_callback(responses.PATCH, url, callback=write_callback)
    assert state.write_state(bot_state)
    restored = state.read_state()
    assert restored["run_history"][0]["sources"] == run["sources"]
    js = """
      import {buildSourceHealthPayload} from './dashboard/lib/source-health.js';
      let input=''; for await (const chunk of process.stdin) input+=chunk;
      const s=JSON.parse(input);
      console.log(JSON.stringify([buildSourceHealthPayload(s),
        buildSourceHealthPayload({...s,source_health:{}})]));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT,
                            input=json.dumps(restored), text=True, capture_output=True, check=True)
    return restored, json.loads(result.stdout)


@responses.activate
@pytest.mark.parametrize("failed", [(), ("usgs_quakes",), ("nhc",), ("jtwc",),
                                    ("usgs_quakes", "nhc"), ("usgs_quakes", "jtwc"), ("nhc", "jtwc")])
def test_empty_witness_remains_degraded_through_persistence_and_dashboard(monkeypatch, failed, capsys):
    outage()
    mocks = feed_mocks(monkeypatch, failed)
    bot_state = deepcopy(state.DEFAULT_STATE)
    run = state.init_run("alerts")
    run_gdacs(bot_state, run)
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == 0
    assert row["promoted"] == row["drafted"] == 0
    assert bot_state.get("_triage_queue", []) == []
    details = row["details"]["feed_diagnostics"]
    assert details["source_leg"] == "subtype_witnesses"
    assert details["configured_product"] == "gdacs-subtype-witnesses"
    assert details["primary_product"] == "gdacs-georss" and details["primary_status"] == "unavailable"
    assert details["scope"] == ["Earthquake", "Tropical Cyclone"]
    assert details["status"] == ("partial_witness_failure" if failed else "witnesses_completed")
    assert details["selected_alerts"] == 0
    assert details["legs"] == {name: {"status": "failed" if name in failed else "success",
        "records_received": None if name in failed else 0,
        "records_selected": None if name in failed else 0} for name in NAMES}
    for mock in mocks.values():
        mock.assert_called_once_with(strict=True)
    assert len(responses.calls) == 3  # Existing primary retry bound; no extra request.
    restored, projections = persist_and_project(monkeypatch, bot_state, run)
    health = restored["source_health"]["gdacs"]
    assert health["success"] == 0 and health["degraded"] == 1
    assert health["last_error"] == row["note"]
    for payload in projections:
        source = payload["sources"][0]
        assert source["health"] == source["last_run_status"] == "degraded"
        assert source["served_via"] == "subtype_witnesses"
        assert source["total_observed"] == 0 and source["successes"] == 0
        assert f"successful_legs:{3 - len(failed)}" in source["last_error"]
        assert f"failed_legs:{','.join(failed) or 'none'}" in source["last_error"]
        assert payload["stats"]["healthy_count"] == 0
    assert "synthetic unavailable leg" not in capsys.readouterr().out


def quake(alert="red"):
    return SignificantEarthquakeEvent(event_id="synthetic-quake", usgs_id="synthetic-id",
        title="Synthetic quake", place="Test location", magnitude=6.0, alert=alert,
        time="2026-09-30T01:00:00Z", updated="2026-09-30T01:05:00Z",
        url="https://example.invalid/quake")


def cyclone(source="nhc", wind=120):
    return CycloneAdvisory(source=source, storm_id="synthetic-storm", storm_name="Synthetic storm",
        basin="Test basin", advisory_number="2", issued_at="2026-09-30T01:00:00Z",
        wind_kt=wind, public_advisory_url="https://example.invalid/cyclone", source_leg="synthetic-advisory")


@responses.activate
@pytest.mark.parametrize("minimum,expected", [("Red", 1), ("Orange", 2), ("Green", 3)])
def test_leg_counts_distinguish_received_from_severity_selected(monkeypatch, minimum, expected):
    outage()
    feed_mocks(monkeypatch, records={"usgs_quakes": [quake("green"), quake("orange"), quake("red")]})
    events = gdacs.fetch_disasters(min_severity=minimum, strict=True)
    assert len(events) == expected
    assert events.source_diagnostics["legs"]["usgs_quakes"] == {
        "status": "success", "records_received": 3, "records_selected": expected}


@responses.activate
def test_nonempty_fallback_preserves_identity_and_does_not_duplicate_drafting(monkeypatch):
    outage()
    records = {"usgs_quakes": [quake()], "nhc": [cyclone()], "jtwc": [cyclone("jtwc")]}
    feed_mocks(monkeypatch, records=records)
    events = gdacs.fetch_disasters(strict=True)
    expected = [gdacs._quake_to_gdacs_event(records["usgs_quakes"][0]),
                gdacs._cyclone_to_gdacs_event(records["nhc"][0]),
                gdacs._cyclone_to_gdacs_event(records["jtwc"][0])]
    for actual, original in zip(events, expected, strict=True):
        original.source_leg = "subtype_witnesses"
        assert asdict(actual) == asdict(original)
    assert events.source_diagnostics["selected_alerts"] == 3  # Not three unique global events.
    bot_state = deepcopy(state.DEFAULT_STATE)
    run = state.init_run("alerts")
    run_gdacs(bot_state, run)  # Real fetch and runner; no second draft of subtype events.
    assert run["sources"][0]["observed"] == 3
    assert run["sources"][0]["promoted"] == 0 and bot_state.get("_triage_queue", []) == []
    restored, projections = persist_and_project(monkeypatch, bot_state, run)
    assert restored["run_history"][0]["sources"][0]["details"]["feed_diagnostics"] == events.source_diagnostics
    assert all(p["sources"][0]["served_via"] == "subtype_witnesses" for p in projections)


@responses.activate
def test_all_legs_failed_remains_failed(monkeypatch):
    outage()
    mocks = feed_mocks(monkeypatch, NAMES)
    with pytest.raises(SourceFetchError, match="GDACS subtype witnesses failed"):
        gdacs.fetch_disasters(strict=True)
    assert all(m.call_count == 1 for m in mocks.values())
    bot_state = deepcopy(state.DEFAULT_STATE)
    run = state.init_run("alerts")
    run_gdacs(bot_state, run)
    assert run["sources"][0]["status"] == "failed"
    assert "feed_diagnostics" not in run["sources"][0].get("details", {})


@responses.activate
def test_skipped_witness_still_propagates_and_stops_later_legs(monkeypatch):
    outage()
    mocks = feed_mocks(monkeypatch, ("usgs_quakes",), error=SourceSkipped("synthetic skip"))
    with pytest.raises(SourceSkipped):
        gdacs.fetch_disasters(strict=True)
    mocks["usgs_quakes"].assert_called_once_with(strict=True)
    mocks["nhc"].assert_not_called()
    mocks["jtwc"].assert_not_called()


@responses.activate
@pytest.mark.parametrize("kind", ["auth", "schema", "clock", "valid_empty"])
def test_non_outage_primary_results_do_not_buy_witness_calls(monkeypatch, kind):
    mocks = feed_mocks(monkeypatch)
    fixture = (ROOT / "tests/fixtures/gdacs_georss_unknown_country.xml").read_text()
    fixture = fixture.replace("<gdacs:alertlevel>Red</gdacs:alertlevel>", "<gdacs:alertlevel>Orange</gdacs:alertlevel>")
    fixture = fixture.replace("<gdacs:episodealertlevel>Red</gdacs:episodealertlevel>", "<gdacs:episodealertlevel>Orange</gdacs:episodealertlevel>")
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: datetime(2026, 9, 9, tzinfo=UTC))
    if kind == "clock":
        # Explicitly remove every publication clock rather than replacing an
        # assumed fixture literal that might stop matching.
        tree = ET.fromstring(fixture)
        for node in list(tree.find("channel")):
            if node.tag in {"pubDate", "lastBuildDate"}:
                tree.find("channel").remove(node)
        for item in tree.findall("channel/item"):
            for node in list(item):
                if node.tag in {"pubDate", "{http://purl.org/dc/elements/1.1/}date"}:
                    item.remove(node)
        fixture = ET.tostring(tree, encoding="unicode")
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, status=401 if kind == "auth" else 200,
                  body="<rss><channel />" if kind == "schema" else fixture)
    if kind == "valid_empty":
        events = gdacs.fetch_disasters(strict=True)
        assert not events and events.source_diagnostics["configured_product"] == "gdacs-georss"
    else:
        with pytest.raises(SourceFetchError):
            gdacs.fetch_disasters(strict=True)
    for mock in mocks.values():
        mock.assert_not_called()
    assert len(responses.calls) == 1


@responses.activate
def test_nonstrict_outage_keeps_existing_empty_result_without_witness(monkeypatch):
    outage()
    mocks = feed_mocks(monkeypatch)
    assert gdacs.fetch_disasters(strict=False) == []
    assert len(responses.calls) == 3
    for mock in mocks.values():
        mock.assert_not_called()


@responses.activate
def test_stale_provider_fallback_preserves_existing_eligibility_without_using_stale_events(monkeypatch):
    fixture = (ROOT / "tests/fixtures/gdacs_georss_unknown_country.xml").read_text()
    responses.add(responses.GET, gdacs.GDACS_GEORSS_URL, body=fixture)
    monkeypatch.setattr(gdacs, "_publication_clock", lambda: datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(gdacs.GDACSPublicationError, match="stale data"):
        gdacs._fetch_disasters_primary(strict=True)
    mocks = feed_mocks(monkeypatch)
    events = gdacs.fetch_disasters(strict=True)
    assert not events and events.source_diagnostics["primary_status"] == "unavailable"
    assert events.source_diagnostics["source_leg"] == "subtype_witnesses"
    for mock in mocks.values():
        mock.assert_called_once_with(strict=True)


@responses.activate
def test_all_records_below_threshold_preserve_empty_witness_identity(monkeypatch):
    outage()
    feed_mocks(monkeypatch, records={"usgs_quakes": [quake("green")], "nhc": [cyclone(wind=40)]})
    bot_state = deepcopy(state.DEFAULT_STATE)
    run = state.init_run("alerts")
    run_gdacs(bot_state, run)
    row = run["sources"][0]
    assert row["status"] == "degraded" and row["observed"] == 0
    legs = row["details"]["feed_diagnostics"]["legs"]
    assert legs["usgs_quakes"] == legs["nhc"] == {
        "status": "success", "records_received": 1, "records_selected": 0}
    _, projections = persist_and_project(monkeypatch, bot_state, run)
    assert all(p["sources"][0]["health"] == "degraded" for p in projections)


@responses.activate
def test_successful_nonempty_leg_keeps_unavailable_peer_counts_unknown(monkeypatch):
    outage()
    feed_mocks(monkeypatch, ("nhc", "jtwc"), records={"usgs_quakes": [quake()]})
    events = gdacs.fetch_disasters(strict=True)
    assert len(events) == 1
    d = events.source_diagnostics
    assert d["status"] == "partial_witness_failure"
    assert d["legs"]["usgs_quakes"]["records_selected"] == 1
    assert d["legs"]["nhc"]["records_received"] is None
    assert d["legs"]["jtwc"]["records_selected"] is None
