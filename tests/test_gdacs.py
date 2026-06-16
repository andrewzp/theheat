"""Tests for GDACS global disaster events."""

from copy import deepcopy
from pathlib import Path

import pytest
import responses

from src.data.gdacs import GDACS_GEORSS_URL, GDACS_URL, GlobalDisasterEvent, fetch_disasters, _intensity_tier
from src.data.cyclones import CycloneAdvisory
from src.data.source_status import SourceFetchError
from src.state import DEFAULT_STATE
from src.data.usgs_quakes import SignificantEarthquakeEvent
from src.orchestrator.sources.gdacs import run_gdacs
from src.two_bot.intern import build_global_disaster_bundle

SAMPLE_RESPONSE = {
    "features": [
        {
            "properties": {
                "eventtype": "TC",
                "alertlevel": "Red",
                "name": "Cyclone Freddy",
                "country": "Mozambique",
                "description": "Category 4 tropical cyclone",
                "eventid": "1001",
                "alertscore": 3.5,
                "population": 450000,
                "severitydata": {
                    "severity": 230.0,
                    "severityunit": "km/h",
                },
            }
        },
        {
            "properties": {
                "eventtype": "EQ",
                "alertlevel": "Orange",
                "name": "Turkey Earthquake",
                "country": "Turkey",
                "description": "6.7 magnitude earthquake",
                "eventid": "1002",
                "alertscore": 2.1,
                "population": 120000,
                "severitydata": {
                    "severity": 6.7,
                    "severityunit": "M",
                },
            }
        },
        {
            "properties": {
                "eventtype": "FL",
                "alertlevel": "Green",
                "name": "Minor Flood",
                "country": "India",
                "description": "Minor flooding",
                "eventid": "1003",
            }
        },
    ]
}


class TestFetchDisasters:
    @responses.activate
    def test_default_filters_to_red_only(self):
        """Default is Red-only — Orange isn't extraordinary."""
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters()
        assert len(events) == 1
        assert events[0].name == "Cyclone Freddy"
        assert events[0].severity == "Red"

    @responses.activate
    def test_explicit_orange_still_works(self):
        """Can still pass Orange explicitly if needed."""
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters(min_severity="Orange")
        assert len(events) == 2
        severities = [e.severity for e in events]
        assert "Green" not in severities

    @responses.activate
    def test_maps_event_type_codes(self):
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters(min_severity="Orange")
        types = [e.disaster_type for e in events]
        assert "Tropical Cyclone" in types
        assert "Earthquake" in types

    @responses.activate
    def test_cyclone_event_id_uses_intensity_tier(self):
        """Cyclone event_id includes tier, not date — so strengthening storms get re-drafted."""
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters()
        # 230 km/h = Cat 4 tier (tier 4)
        assert events[0].event_id == "gdacs_TC_1001_tier4"

    @responses.activate
    def test_earthquake_event_id_uses_date(self):
        """Non-evolving events still use date-based dedup."""
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters(min_severity="Orange")
        eq = next(e for e in events if e.disaster_type == "Earthquake")
        # Earthquake uses date, not tier
        assert "gdacs_EQ_1002_" in eq.event_id
        assert "tier" not in eq.event_id

    @responses.activate
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            status=500,
        )
        assert fetch_disasters() == []

    @responses.activate
    def test_green_severity_included_when_min_green(self):
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters(min_severity="Green")
        assert len(events) == 3

    @responses.activate
    def test_gdacs_falls_back_to_georss_on_json_failure(self, capsys):
        responses.add(responses.GET, GDACS_URL, status=500, body="down")
        responses.add(
            responses.GET,
            GDACS_GEORSS_URL,
            body=Path("tests/fixtures/gdacs_georss_sample.xml").read_text(),
            status=200,
        )

        events = fetch_disasters(min_severity="Orange")

        assert "[gdacs] served by georss fallback" in capsys.readouterr().out
        assert [event.name for event in events] == ["Cyclone Freddy", "Orange earthquake alert in Turkey"]
        cyclone = events[0]
        assert cyclone.disaster_type == "Tropical Cyclone"
        assert cyclone.country == "Mozambique"
        assert cyclone.severity == "Red"
        assert cyclone.event_id == "gdacs_TC_1001_tier4"
        assert cyclone.alert_score == 3.5
        assert cyclone.severity_value == 230.0
        assert cyclone.severity_unit == "km/h"
        assert cyclone.population_affected == 450000

    @responses.activate
    def test_gdacs_georss_insufficient_fields_raises(self):
        responses.add(responses.GET, GDACS_URL, status=500, body="down")
        responses.add(
            responses.GET,
            GDACS_GEORSS_URL,
            body="""<?xml version="1.0"?><rss><channel><item><title>Broken</title></item></channel></rss>""",
            status=200,
        )

        with pytest.raises(SourceFetchError, match="insufficient GeoRSS fields"):
            fetch_disasters(strict=True)

    @responses.activate
    def test_gdacs_primary_outage_uses_usgs_and_cyclone_subtype_witnesses(self, monkeypatch, capsys):
        responses.add(responses.GET, GDACS_URL, status=500, body="down")
        responses.add(responses.GET, GDACS_GEORSS_URL, status=504, body="timeout")
        monkeypatch.setattr(
            "src.data.gdacs.usgs_quakes.fetch_significant_earthquakes",
            lambda strict=False: [
                SignificantEarthquakeEvent(
                    event_id="usgs_eq_us7000abcd",
                    usgs_id="us7000abcd",
                    title="M 7.8 - 10 km S of Testville",
                    place="10 km S of Testville",
                    magnitude=7.8,
                    time="2026-06-16T01:02:03Z",
                    updated="2026-06-16T01:12:03Z",
                    url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                    alert="red",
                    significance=1200,
                    tsunami=True,
                )
            ],
        )
        monkeypatch.setattr(
            "src.data.gdacs.nhc.fetch_active_cyclones",
            lambda strict=False: [
                CycloneAdvisory(
                    source="nhc",
                    storm_id="AL0126",
                    storm_name="Alex",
                    basin="Atlantic",
                    advisory_number="12",
                    issued_at="2026-06-16T00:00:00Z",
                    wind_kt=120,
                    pressure_mb=930,
                    lat=18.5,
                    lon=-62.1,
                    public_advisory_url="https://www.nhc.noaa.gov/",
                )
            ],
        )
        monkeypatch.setattr("src.data.gdacs.jtwc.fetch_active_cyclones", lambda strict=False: [])

        events = fetch_disasters(strict=True)

        assert "[gdacs] served by subtype_witnesses" in capsys.readouterr().out
        assert [event.disaster_type for event in events] == ["Earthquake", "Tropical Cyclone"]
        assert all(event.source_leg == "subtype_witnesses" for event in events)
        assert events[0].severity == "Red"
        assert events[0].severity_value == pytest.approx(7.8)
        assert events[1].severity_value == pytest.approx(222.24)

    def test_gdacs_subtype_witness_marks_observed_alt_host_grade(self):
        event = GlobalDisasterEvent(
            disaster_type="Earthquake",
            name="M 7.8 - Testville",
            country="10 km S of Testville",
            severity="Red",
            description="USGS significant earthquake alert",
            event_id="gdacs_EQ_usgs_us7000abcd_2026-06-16",
            severity_value=7.8,
            severity_unit="M",
            source_leg="subtype_witnesses",
        )

        bundle = build_global_disaster_bundle(event)

        assert {"label": "evidence_grade", "value": "observed_alt_host"} in bundle.current_facts

    def test_gdacs_runner_counts_subtype_witness_without_duplicate_story(self, monkeypatch):
        event = GlobalDisasterEvent(
            disaster_type="Earthquake",
            name="M 7.8 - Testville",
            country="10 km S of Testville",
            severity="Red",
            description="USGS significant earthquake alert",
            event_id="gdacs_EQ_usgs_us7000abcd_2026-06-16",
            severity_value=7.8,
            severity_unit="M",
            source_leg="subtype_witnesses",
        )
        monkeypatch.setattr(
            "src.orchestrator.sources.gdacs.gdacs.fetch_disasters",
            lambda *args, **kwargs: [event],
        )
        bot_state = deepcopy(DEFAULT_STATE)
        current_run = {"sources": []}

        run_gdacs(bot_state, current_run)

        assert bot_state.get("_triage_queue", []) == []
        source = next(item for item in current_run["sources"] if item["source"] == "gdacs")
        assert source["status"] == "degraded"
        assert source["observed"] == 1
        assert source["promoted"] == 0
        assert source["note"] == "served via subtype_witnesses"

class TestIntensityTier:
    def test_tropical_storm(self):
        assert _intensity_tier("TC", 100.0) == "tier0"

    def test_cat1(self):
        assert _intensity_tier("TC", 130.0) == "tier1"

    def test_cat3(self):
        assert _intensity_tier("TC", 180.0) == "tier3"

    def test_cat4(self):
        assert _intensity_tier("TC", 230.0) == "tier4"

    def test_cat5(self):
        assert _intensity_tier("TC", 260.0) == "tier5"

    def test_strengthening_changes_tier(self):
        """A cyclone strengthening from Cat 1 to Cat 4 produces a different event_id."""
        tier_early = _intensity_tier("TC", 130.0)
        tier_late = _intensity_tier("TC", 230.0)
        assert tier_early != tier_late

    def test_same_tier_deduplicates(self):
        """Same intensity tier = same event_id = deduped."""
        assert _intensity_tier("TC", 220.0) == _intensity_tier("TC", 230.0)

    def test_earthquake_uses_date(self):
        """Non-cyclone events use date, not tier."""
        result = _intensity_tier("EQ", 6.7)
        assert "tier" not in result

    def test_flood_uses_date(self):
        result = _intensity_tier("FL", 0.0)
        assert "tier" not in result

    def test_cyclone_zero_wind_uses_date(self):
        """Cyclone with no wind data falls back to date."""
        result = _intensity_tier("TC", 0.0)
        assert "tier" not in result


class TestFetchDisastersRich:
    @responses.activate
    def test_rich_fields_captured_for_cyclone(self):
        """Cyclone should expose wind speed, alert score, population."""
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters()
        cyclone = events[0]
        assert cyclone.severity_value == 230.0
        assert cyclone.severity_unit == "km/h"
        assert cyclone.alert_score == 3.5
        assert cyclone.population_affected == 450000
