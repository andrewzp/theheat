"""Tests for NWS severe weather alerts."""

import responses

from src.data.nws_alerts import (
    SevereWeatherAlert,
    fetch_alerts,
    _simplify_area,
    TRACKED_EVENTS,
)

SAMPLE_RESPONSE = {
    "features": [
        {
            "properties": {
                "event": "Hurricane Warning",
                "severity": "Extreme",
                "areaDesc": "Miami-Dade, FL",
                "headline": "Hurricane Warning for Miami-Dade",
                "description": "A hurricane warning means hurricane conditions are expected within 36 hours.",
                "senderName": "NWS Miami FL",
                "id": "urn:oid:2.49.0.1.840.0.def456",
                "parameters": {
                    "maxWindGust": ["145 mph"],
                },
            }
        },
        {
            "properties": {
                "event": "Flash Flood Emergency",
                "severity": "Extreme",
                "areaDesc": "Montgomery County, TX",
                "headline": "Flash Flood Emergency for Montgomery County",
                "description": "Life-threatening flash flooding. Move to higher ground immediately.",
                "senderName": "NWS Houston TX",
                "id": "urn:oid:2.49.0.1.840.0.abc123",
                "parameters": {},
            }
        },
        # These should all be FILTERED OUT — routine severe weather
        {
            "properties": {
                "event": "Tornado Warning",
                "severity": "Extreme",
                "areaDesc": "Tulsa, OK",
                "headline": "Tornado Warning for Tulsa",
                "id": "urn:oid:routine1",
            }
        },
        {
            "properties": {
                "event": "Severe Thunderstorm Warning",
                "severity": "Severe",
                "areaDesc": "Buchanan, MO",
                "headline": "Severe Thunderstorm Warning",
                "id": "urn:oid:routine2",
            }
        },
        {
            "properties": {
                "event": "Flash Flood Warning",
                "severity": "Severe",
                "areaDesc": "Kauai, HI",
                "headline": "Flash Flood Warning for Kauai",
                "id": "urn:oid:routine3",
            }
        },
        {
            "properties": {
                "event": "Tropical Storm Warning",
                "severity": "Severe",
                "areaDesc": "Chuuk Coastal Waters",
                "headline": "Tropical Storm Warning",
                "id": "urn:oid:routine4",
            }
        },
    ]
}


class TestTrackedEvents:
    def test_only_emergency_tier_and_hurricanes_tracked(self):
        """Routine severe weather is filtered out at the source."""
        assert "Tornado Emergency" in TRACKED_EVENTS
        assert "Flash Flood Emergency" in TRACKED_EVENTS
        assert "Hurricane Warning" in TRACKED_EVENTS
        assert "Extreme Wind Warning" in TRACKED_EVENTS
        assert "Storm Surge Warning" in TRACKED_EVENTS

        # Routine stuff NOT tracked
        assert "Tornado Warning" not in TRACKED_EVENTS
        assert "Severe Thunderstorm Warning" not in TRACKED_EVENTS
        assert "Flash Flood Warning" not in TRACKED_EVENTS
        assert "Tropical Storm Warning" not in TRACKED_EVENTS


class TestFetchAlerts:
    @responses.activate
    def test_only_emergency_and_hurricane_events_returned(self):
        """Of 6 alerts in response, only 2 (Hurricane Warning + Flash Flood Emergency) pass."""
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        alerts = fetch_alerts()
        assert len(alerts) == 2
        types = {a.event_type for a in alerts}
        assert types == {"Hurricane Warning", "Flash Flood Emergency"}

    @responses.activate
    def test_rich_data_captured(self):
        """Parameters like maxWindGust should be pulled through."""
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        alerts = fetch_alerts()
        hurricane = next(a for a in alerts if a.event_type == "Hurricane Warning")
        assert hurricane.max_wind_gust == "145 mph"
        assert hurricane.sender_name == "NWS Miami FL"
        assert "hurricane conditions" in hurricane.description

    @responses.activate
    def test_deduplicates_same_event_and_area(self):
        duped = {
            "features": [
                {
                    "properties": {
                        "event": "Hurricane Warning",
                        "severity": "Extreme",
                        "areaDesc": "Miami, FL",
                        "headline": "Hurricane Warning 1",
                        "id": "id1",
                    }
                },
                {
                    "properties": {
                        "event": "Hurricane Warning",
                        "severity": "Extreme",
                        "areaDesc": "Miami, FL",
                        "headline": "Hurricane Warning 2",
                        "id": "id2",
                    }
                },
            ]
        }
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=duped,
            status=200,
        )
        alerts = fetch_alerts()
        assert len(alerts) == 1

    @responses.activate
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            status=500,
        )
        assert fetch_alerts() == []

    @responses.activate
    def test_event_id_uses_nws_id(self):
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        alerts = fetch_alerts()
        hurricane = next(a for a in alerts if a.event_type == "Hurricane Warning")
        assert hurricane.event_id == "nws_urn:oid:2.49.0.1.840.0.def456"


class TestSimplifyArea:
    def test_short_area_unchanged(self):
        assert _simplify_area("Miami-Dade, FL") == "Miami-Dade, FL"

    def test_two_areas_unchanged(self):
        assert _simplify_area("Tulsa, OK; Rogers, OK") == "Tulsa, OK; Rogers, OK"

    def test_many_areas_simplified(self):
        area = "Tulsa, OK; Rogers, OK; Creek, OK; Osage, OK"
        result = _simplify_area(area)
        assert "Tulsa, OK" in result
        assert "3 other areas" in result
