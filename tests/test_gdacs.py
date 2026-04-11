"""Tests for GDACS global disaster events."""

import responses

from src.data.gdacs import GlobalDisasterEvent, fetch_disasters

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
    def test_event_id_format(self):
        responses.add(
            responses.GET,
            "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        events = fetch_disasters(min_severity="Orange")
        assert events[0].event_id.startswith("gdacs_TC_1001_")

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
