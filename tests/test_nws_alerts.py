"""Tests for NWS severe weather alerts."""

import responses
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

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
                "event": "Tornado Warning",
                "status": "Actual", "category": "Met", "messageType": "Alert",
                "severity": "Extreme",
                "areaDesc": "Montgomery County, TX",
                "headline": "Flash Flood Emergency for Montgomery County",
                "description": "Life-threatening flash flooding. Move to higher ground immediately.",
                "senderName": "NWS Houston TX",
                "id": "urn:oid:2.49.0.1.840.0.abc123",
                "parameters": {"tornadoDamageThreat": ["CATASTROPHIC"], "tornadoDetection": ["OBSERVED"]},
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
        assert "Tornado Emergency" not in TRACKED_EVENTS
        assert "Flash Flood Emergency" not in TRACKED_EVENTS
        assert "Hurricane Warning" in TRACKED_EVENTS
        assert "Typhoon Warning" in TRACKED_EVENTS
        assert "Extreme Wind Warning" in TRACKED_EVENTS
        assert "Storm Surge Warning" in TRACKED_EVENTS
        # Rare winter/heat extremes added April 2026
        assert "Blizzard Warning" in TRACKED_EVENTS
        assert "Ice Storm Warning" in TRACKED_EVENTS
        assert "Extreme Cold Warning" in TRACKED_EVENTS
        assert "Extreme Heat Warning" in TRACKED_EVENTS

        # Routine stuff NOT tracked
        assert "Tornado Warning" not in TRACKED_EVENTS
        assert "Severe Thunderstorm Warning" not in TRACKED_EVENTS
        assert "Flash Flood Warning" not in TRACKED_EVENTS
        assert "Tropical Storm Warning" not in TRACKED_EVENTS
        assert "Winter Storm Warning" not in TRACKED_EVENTS
        assert "Heat Advisory" not in TRACKED_EVENTS


class TestFetchAlerts:
    @responses.activate
    def test_only_emergency_and_hurricane_events_returned(self):
        """Of 6 alerts in response, only 2 (Hurricane Warning + catastrophic Tornado Warning) pass."""
        responses.add(
            responses.GET,
            "https://api.weather.gov/alerts/active",
            json=SAMPLE_RESPONSE,
            status=200,
        )
        alerts = fetch_alerts()
        assert len(alerts) == 2
        types = {a.event_type for a in alerts}
        assert types == {"Hurricane Warning", "Tornado Warning"}

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


def _typhoon_feature(identity="invented-warning", message_type="Alert", refs=None):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    issued, expires = (now-timedelta(minutes=20)).isoformat(), (now+timedelta(hours=2)).isoformat()
    return {"type": "Feature", "geometry": None, "properties": {
        "id": identity, "event": "Typhoon Warning", "category": "Met", "status": "Actual",
        "messageType": message_type, "severity": "Extreme", "areaDesc": "Invented island",
        "headline": "Invented cyclone warning", "description": "Typhoon conditions are expected.",
        "sent": issued, "effective": issued, "onset": issued, "expires": expires, "ends": None,
        "references": refs if refs is not None else [], "parameters": {}}}


@pytest.mark.parametrize("message_type", ["Alert", "Update"])
@responses.activate
def test_actual_typhoon_designation_and_complete_update_references_survive(message_type):
    refs = [{"identifier": "invented-prior-warning"}] if message_type == "Update" else []
    feature = _typhoon_feature(message_type=message_type, refs=refs)
    original = deepcopy(feature)
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": [feature]})
    selected = fetch_alerts(strict=True)
    assert len(selected) == 1
    assert selected[0].event_type == "Typhoon Warning"
    assert selected[0].event_id == "nws_invented-warning"
    assert selected[0].source_evidence["feature"] == original
    assert selected[0].source_evidence["feature"]["properties"]["references"] == refs
    assert "expected" in selected[0].description


@pytest.mark.parametrize("field,value", [
    ("messageType", "Cancel"), ("messageType", "Test"), ("messageType", "Ack"), ("messageType", "update"),
    ("messageType", None), ("category", "Safety"), ("category", None),
    ("status", "Test"), ("status", "Exercise"), ("status", None), ("id", ""), ("id", None),
    ("areaDesc", ""), ("areaDesc", None),
    ("event", "Typhoon Watch"), ("event", "Tropical Storm Warning"),
])
@responses.activate
def test_typhoon_admission_does_not_broaden_routine_or_nonactual_products(field, value):
    feature = _typhoon_feature()
    feature["properties"][field] = value
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": [feature]})
    assert fetch_alerts(strict=True) == []


@pytest.mark.parametrize("refs", [None, [], {}, [{}], [{"identifier": ""}], [{"identifier": "invented-warning"}]])
@responses.activate
def test_typhoon_update_requires_unambiguous_cap_reference_identifiers(refs):
    feature = _typhoon_feature(message_type="Update")
    feature["properties"]["references"] = refs
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": [feature]})
    assert fetch_alerts(strict=True) == []


@pytest.mark.parametrize("reverse", [False, True])
@responses.activate
def test_explicit_reference_supersedes_old_typhoon_independently_of_feed_order(reverse):
    old = _typhoon_feature("invented-old")
    current = _typhoon_feature("invented-current", "Update", [{"identifier": "invented-old"}])
    features = [old, current] if not reverse else [current, old]
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": features})
    selected = fetch_alerts(strict=True)
    assert [a.event_id for a in selected] == ["nws_invented-current"]


@responses.activate
def test_unlinked_typhoon_products_for_same_area_are_held_instead_of_order_selected():
    features = [_typhoon_feature("invented-one"), _typhoon_feature("invented-two")]
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": features})
    assert fetch_alerts(strict=True) == []


@responses.activate
def test_ordinary_hurricane_update_keeps_its_prior_exclusion():
    feature = _typhoon_feature(message_type="Update", refs=[{"identifier": "invented-old"}])
    feature["properties"]["event"] = "Hurricane Warning"
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": [feature]})
    assert fetch_alerts(strict=True) == []


@pytest.mark.parametrize("conflicting", [False, True])
@responses.activate
def test_identical_typhoon_repeats_do_not_hide_a_warning_but_conflicting_same_id_is_held(conflicting):
    first = _typhoon_feature()
    repeated = deepcopy(first)
    if conflicting:
        repeated["properties"]["headline"] = "Conflicting invented warning content"
    responses.add(responses.GET, "https://api.weather.gov/alerts/active", json={"features": [first, repeated]})
    selected = fetch_alerts(strict=True)
    assert len(selected) == (0 if conflicting else 1)
