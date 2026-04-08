"""Tests for NWS severe weather alerts."""

import responses

from src.data.nws_alerts import SevereWeatherAlert, fetch_alerts, _simplify_area

SAMPLE_RESPONSE = {
    "features": [
        {
            "properties": {
                "event": "Tornado Warning",
                "severity": "Extreme",
                "areaDesc": "Tulsa, OK; Rogers, OK; Creek, OK; Osage, OK",
                "headline": "Tornado Warning for Tulsa County",
                "id": "urn:oid:2.49.0.1.840.0.abc123",
            }
        },
        {
            "properties": {
                "event": "Hurricane Warning",
                "severity": "Extreme",
                "areaDesc": "Miami-Dade, FL",
                "headline": "Hurricane Warning for Miami-Dade",
                "id": "urn:oid:2.49.0.1.840.0.def456",
            }
        },
        {
            "properties": {
                "event": "Special Weather Statement",
                "severity": "Minor",
                "areaDesc": "Denver, CO",
                "headline": "Special Weather Statement",
                "id": "urn:oid:2.49.0.1.840.0.ghi789",
            }
        },
    ]
}


class TestFetchAlerts:
    @responses.activate
    def test_happy_path_filters_tracked_events(self):
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        alerts = fetch_alerts()
        assert len(alerts) == 2
        assert all(isinstance(a, SevereWeatherAlert) for a in alerts)
        types = [a.event_type for a in alerts]
        assert "Tornado Warning" in types
        assert "Hurricane Warning" in types
        assert "Special Weather Statement" not in types

    @responses.activate
    def test_deduplicates_same_event_and_area(self):
        duped = {
            "features": [
                {
                    "properties": {
                        "event": "Tornado Warning",
                        "severity": "Extreme",
                        "areaDesc": "Tulsa, OK",
                        "headline": "Tornado Warning 1",
                        "id": "id1",
                    }
                },
                {
                    "properties": {
                        "event": "Tornado Warning",
                        "severity": "Extreme",
                        "areaDesc": "Tulsa, OK",
                        "headline": "Tornado Warning 2",
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
        # Uses NWS-provided ID for stable dedup
        assert alerts[0].event_id == "nws_urn:oid:2.49.0.1.840.0.abc123"


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
