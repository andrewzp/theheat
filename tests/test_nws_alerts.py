"""Tests for NWS severe weather alerts."""

import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import responses

from src.data.nws_alerts import (
    SevereWeatherAlert,
    fetch_alerts,
    _simplify_area,
    TRACKED_EVENTS,
)

_CAP_FIXTURE = Path(__file__).parent / "fixtures" / "nws_cap_missouri_2026_07_10.json"


def _cap_features(*names: str) -> list[dict]:
    """Real captured CAP payloads, timestamps rewritten today-relative."""
    raw = _CAP_FIXTURE.read_text()
    for offset, captured in ((-1, "2026-07-09"), (0, "2026-07-10"), (1, "2026-07-11")):
        raw = raw.replace(captured, (date.today() + timedelta(days=offset)).isoformat())
    alerts = json.loads(raw)["alerts"]
    return [deepcopy(alerts[name]) for name in names]


def _mock_nws(payload: dict) -> None:
    responses.add(
        responses.GET,
        "https://api.weather.gov/alerts/active",
        json=payload,
        status=200,
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


class TestEmergencyPromotion:
    """NWS never emits "Flash Flood Emergency"/"Tornado Emergency" as event
    values — emergencies ride ordinary Warning products via damage-threat
    parameters and emergency wording (verified against api.weather.gov,
    2026-07-10 Missouri flash flood; see the fixture's _note).
    """

    @responses.activate
    def test_catastrophic_flash_flood_warning_promoted(self):
        _mock_nws({"features": _cap_features("ff_emergency_initial_alert")})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.event_type == "Flash Flood Warning"
        assert alert.emergency_designation == "Flash Flood Emergency"
        assert "Iron" in alert.area

    @responses.activate
    def test_emergency_wording_alone_promotes(self):
        features = _cap_features("ff_emergency_initial_alert")
        features[0]["properties"]["parameters"].pop("flashFloodDamageThreat")
        _mock_nws({"features": features})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Flash Flood Emergency"

    @responses.activate
    def test_catastrophic_param_alone_promotes(self):
        features = _cap_features("ff_emergency_initial_alert")
        props = features[0]["properties"]
        for field in ("headline", "description"):
            props[field] = (props[field] or "").replace("FLASH FLOOD EMERGENCY", "FLOODING")
        _mock_nws({"features": features})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Flash Flood Emergency"

    @responses.activate
    def test_considerable_threat_not_promoted(self):
        _mock_nws({"features": _cap_features("ff_considerable_update")})
        assert fetch_alerts() == []

    @responses.activate
    def test_routine_flash_flood_warning_still_filtered(self):
        _mock_nws({"features": _cap_features("ff_routine_alert")})
        assert fetch_alerts() == []

    @responses.activate
    def test_routine_tornado_warning_still_filtered(self):
        _mock_nws({"features": _cap_features("tornado_routine_alert")})
        assert fetch_alerts() == []

    @responses.activate
    def test_catastrophic_tornado_warning_promoted(self):
        _mock_nws({"features": _cap_features("tornado_emergency_update_synthetic")})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].event_type == "Tornado Warning"
        assert alerts[0].emergency_designation == "Tornado Emergency"

    @responses.activate
    def test_pds_wording_promotes_with_pds_designation(self):
        _mock_nws({"features": _cap_features("tornado_pds_alert_synthetic")})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Particularly Dangerous Situation"

    @responses.activate
    def test_pds_wording_alone_does_not_promote(self):
        # A routine Flash Flood Warning can *mention* a PDS tornado watch in
        # its narrative; PDS promotes only alongside the event's own
        # damage-threat tag.
        features = _cap_features("ff_routine_alert")
        features[0]["properties"]["description"] += (
            "\n\nThis is a PARTICULARLY DANGEROUS SITUATION. Take cover now."
        )
        _mock_nws({"features": features})
        assert fetch_alerts() == []

    @responses.activate
    def test_pds_reference_to_other_product_not_promoted(self):
        # A CONSIDERABLE-tagged warning may reference a nearby PDS *watch*
        # in its narrative; only the product's own affirmative "THIS IS A
        # PARTICULARLY DANGEROUS SITUATION" declaration promotes.
        features = _cap_features("ff_considerable_update")
        features[0]["properties"]["description"] += (
            "\n\nA PARTICULARLY DANGEROUS SITUATION tornado watch remains in effect."
        )
        _mock_nws({"features": features})
        assert fetch_alerts() == []

    @responses.activate
    def test_emergency_phrase_in_narrative_alone_does_not_promote(self):
        # The narrative can say "The FLASH FLOOD EMERGENCY has ended" on a
        # downgrade, or reference a co-located product. Emergency wording
        # promotes only from the product's own headline surfaces, which NWS
        # rewrites on downgrade (the de-escalated 15:47 MO message's
        # NWSheadline reads "FLASH FLOOD WARNING REMAINS IN EFFECT...").
        features = _cap_features("ff_routine_alert")
        features[0]["properties"]["description"] += (
            "\n\nThe FLASH FLOOD EMERGENCY for Iron County has ended."
        )
        _mock_nws({"features": features})
        assert fetch_alerts() == []

    @responses.activate
    def test_emergency_phrase_in_nws_headline_promotes(self):
        # Wording-only promotion (no damage-threat tag) keys on the
        # product's own NWSheadline parameter — every real 2026-07-10 MO
        # emergency message carried "FLASH FLOOD EMERGENCY FOR..." there.
        features = _cap_features("ff_emergency_initial_alert")
        props = features[0]["properties"]
        props["parameters"].pop("flashFloodDamageThreat")
        props["description"] = "Flooding is occurring across the warned area."
        _mock_nws({"features": features})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Flash Flood Emergency"

    @responses.activate
    def test_cross_event_phrase_does_not_promote(self):
        # A Flash Flood Warning whose text references a co-located TORNADO
        # EMERGENCY (TORFF events) is not itself a tornado emergency.
        features = _cap_features("ff_routine_alert")
        features[0]["properties"]["description"] += "\n\nA TORNADO EMERGENCY is in effect nearby."
        _mock_nws({"features": features})
        assert fetch_alerts() == []

    @responses.activate
    def test_literal_emergency_event_still_tracked_and_designated(self):
        # Belt-and-suspenders: if NWS ever emits the literal event value.
        _mock_nws(SAMPLE_RESPONSE)
        alerts = fetch_alerts()
        ffe = next(a for a in alerts if a.event_type == "Flash Flood Emergency")
        assert ffe.emergency_designation == "Flash Flood Emergency"

    @responses.activate
    def test_tracked_events_carry_no_designation(self):
        _mock_nws(SAMPLE_RESPONSE)
        hurricane = next(a for a in fetch_alerts() if a.event_type == "Hurricane Warning")
        assert hurricane.emergency_designation == ""


class TestUpdateMessages:
    """Emergency upgrades arrive as messageType=Update — the 2026-07-10 MO
    emergency was one initial Alert (04:16) then four Update re-issuances.
    A fetch filtered to message_type=alert never sees a mid-lifecycle
    upgrade, so Updates must be fetched and admitted via the emergency path
    (and only that path — tracked events already surfaced at issuance).
    """

    @responses.activate
    def test_fetch_requests_updates_too(self):
        _mock_nws({"features": []})
        fetch_alerts()
        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert query["message_type"] == ["alert,update,cancel"]

    @responses.activate
    def test_fetch_filters_events_server_side(self):
        # Fetching every nationwide Update would balloon the payload and
        # risk the collection limit during outbreaks — the API filters by
        # event name server-side (verified live 2026-07-13: 28 features vs
        # 333 unfiltered).
        _mock_nws({"features": []})
        fetch_alerts()
        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        requested = query["event"][0].split(",")
        assert "Flash Flood Warning" in requested
        assert "Tornado Warning" in requested
        assert "Hurricane Warning" in requested
        assert "Flash Flood Emergency" in requested
        assert requested == sorted(requested)

    @responses.activate
    def test_emergency_update_message_promoted(self):
        _mock_nws({"features": _cap_features("ff_emergency_update")})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Flash Flood Emergency"

    @responses.activate
    def test_tracked_event_update_not_reprocessed(self):
        hurricane_update = {
            "properties": {
                "event": "Hurricane Warning",
                "messageType": "Update",
                "severity": "Extreme",
                "areaDesc": "Miami-Dade, FL",
                "headline": "Hurricane Warning remains in effect",
                "id": "urn:oid:hurricane-update",
            }
        }
        _mock_nws({"features": [hurricane_update]})
        assert fetch_alerts() == []

    @responses.activate
    def test_emergency_event_id_stable_across_lifecycle(self):
        _mock_nws({"features": _cap_features("ff_emergency_initial_alert")})
        _mock_nws({"features": _cap_features("ff_emergency_update")})
        first = fetch_alerts()[0]
        second = fetch_alerts()[0]
        assert first.event_id == second.event_id
        # Office must stay in the key: ETNs are reused across offices
        # (the capture had both KLSX.FF.W.0050 and KEAX.FF.W.0050).
        assert "KLSX" in first.event_id
        assert "0050" in first.event_id

    @responses.activate
    def test_emergency_without_vtec_still_dedups_across_lifecycle(self):
        # FF.W/TO.W products carry VTEC in practice; if one arrives without
        # it, the fallback must still hold the lifecycle to ONE candidate —
        # per-message CAP ids would re-draft on every Update. (References
        # can't help: each CAP message links only its immediate
        # predecessor, verified on the 2026-07-10 MO thread.)
        alert_features = _cap_features("ff_emergency_initial_alert")
        alert_features[0]["properties"]["parameters"].pop("VTEC")
        update_features = _cap_features("ff_emergency_update")
        update_features[0]["properties"]["parameters"].pop("VTEC")
        _mock_nws({"features": alert_features})
        _mock_nws({"features": update_features})
        first = fetch_alerts()[0]
        second = fetch_alerts()[0]
        assert first.event_id == second.event_id
        assert first.event_id != "nws_" + alert_features[0]["properties"]["id"]

    @responses.activate
    def test_emergency_with_malformed_vtec_still_dedups_across_lifecycle(self):
        alert_features = _cap_features("ff_emergency_initial_alert")
        alert_features[0]["properties"]["parameters"]["VTEC"] = ["/O.BAD/"]
        update_features = _cap_features("ff_emergency_update")
        update_features[0]["properties"]["parameters"]["VTEC"] = ["/O.BAD/"]
        _mock_nws({"features": alert_features})
        _mock_nws({"features": update_features})
        first = fetch_alerts()[0]
        second = fetch_alerts()[0]
        assert first.event_id == second.event_id

    @responses.activate
    def test_emergency_upgrade_after_pds_gets_distinct_id(self):
        # A PDS draft must not block a later catastrophic upgrade — the
        # upgrade IS the news. Same warning (VTEC), higher tier → new id.
        pds = _cap_features("tornado_pds_alert_synthetic")
        emergency = _cap_features("tornado_pds_alert_synthetic")
        emergency[0]["properties"]["parameters"]["tornadoDamageThreat"] = ["CATASTROPHIC"]
        emergency[0]["properties"]["messageType"] = "Update"
        _mock_nws({"features": pds})
        _mock_nws({"features": emergency})
        first = fetch_alerts()[0]
        second = fetch_alerts()[0]
        assert first.emergency_designation == "Particularly Dangerous Situation"
        assert second.emergency_designation == "Tornado Emergency"
        assert first.event_id != second.event_id

    @responses.activate
    def test_two_distinct_emergencies_same_area_both_survive(self):
        # Within-fetch dedup for designated alerts keys on the warning
        # identity (VTEC), not (event, area) — two different emergencies
        # can cover the same counties.
        a, b = _cap_features("ff_emergency_initial_alert", "ff_emergency_initial_alert")
        b["properties"]["id"] += ".second"
        b["properties"]["parameters"]["VTEC"] = [
            "/O.NEW.KLSX.FF.W.0051.260710T0916Z-260710T1515Z/"
        ]
        _mock_nws({"features": [a, b]})
        assert len(fetch_alerts()) == 2

    @responses.activate
    def test_same_emergency_twice_in_one_payload_dedups(self):
        _mock_nws({"features": _cap_features("ff_emergency_initial_alert", "ff_emergency_update")})
        assert len(fetch_alerts()) == 1

    @responses.activate
    def test_same_tier_dedup_keeps_latest_message(self):
        # Payload order is not chronological — the freshest message's copy
        # must win regardless of API ordering.
        newest_first = _cap_features("ff_emergency_update", "ff_emergency_initial_alert")
        update_headline = newest_first[0]["properties"]["headline"]
        _mock_nws({"features": newest_first})
        _mock_nws({"features": _cap_features("ff_emergency_initial_alert", "ff_emergency_update")})
        assert fetch_alerts()[0].headline == update_headline
        assert fetch_alerts()[0].headline == update_headline

    @responses.activate
    def test_downgraded_lifecycle_is_not_promoted(self):
        # Superseded messages linger in /alerts/active (verified live:
        # 37 of 224 lifecycles appeared more than once). When the NEWEST
        # message of a warning's lifecycle carries no designation, NWS has
        # downgraded it — emitting the older catastrophic message would
        # post a present-tense emergency for a warning that has eased.
        # (Real thread: the 11:42 CATASTROPHIC update was followed by the
        # 15:47 CONSIDERABLE one.)
        _mock_nws({"features": _cap_features("ff_emergency_update", "ff_considerable_update")})
        _mock_nws({"features": _cap_features("ff_considerable_update", "ff_emergency_update")})
        assert fetch_alerts() == []
        assert fetch_alerts() == []

    @responses.activate
    def test_emergency_to_pds_downgrade_emits_pds(self):
        # The latest message decides the tier: an emergency→PDS downgrade
        # within one payload surfaces at the PDS tier (the orchestrator's
        # monotonic skip stops it re-drafting an already-surfaced
        # emergency).
        emergency = _cap_features("tornado_pds_alert_synthetic")[0]
        emergency["properties"]["parameters"]["tornadoDamageThreat"] = ["CATASTROPHIC"]
        pds_later = _cap_features("tornado_pds_alert_synthetic")[0]
        pds_later["properties"]["messageType"] = "Update"
        pds_later["properties"]["id"] += ".downgrade"
        pds_later["properties"]["sent"] = pds_later["properties"]["sent"].replace("20:27", "22:27")
        _mock_nws({"features": [emergency, pds_later]})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Particularly Dangerous Situation"
        assert alerts[0].event_id.endswith(":pds")

    @responses.activate
    def test_all_terminal_vtec_update_is_not_promoted(self):
        # An expiration/cancellation product (every VTEC action terminal)
        # announces the END of the warning — promoting one would post a
        # present-tense emergency for a warning NWS just closed.
        features = _cap_features("ff_emergency_update")
        params = features[0]["properties"]["parameters"]
        params["VTEC"] = [params["VTEC"][0].replace("/O.EXT.", "/O.CAN.")]
        _mock_nws({"features": features})
        assert fetch_alerts() == []

    @responses.activate
    def test_non_mapping_parameters_on_tracked_event_do_not_abort_the_fetch(self):
        # A schema-drifted TRACKED feature (no lifecycle identity at
        # stake) must not cost the cycle every valid alert in the payload.
        broken = _cap_features("ff_routine_alert")
        broken[0]["properties"]["event"] = "Extreme Heat Warning"
        broken[0]["properties"]["parameters"] = "not-a-mapping"
        good = _cap_features("ff_emergency_initial_alert")
        _mock_nws({"features": broken + good})
        alerts = fetch_alerts()
        assert len(alerts) == 2
        designations = {a.emergency_designation for a in alerts}
        assert "Flash Flood Emergency" in designations

    @responses.activate
    def test_lifecycle_participant_losing_identity_fails_closed(self):
        # A schema-drifted emergency-capable feature can't be keyed to its
        # lifecycle — degrading it to a fallback key would leave an older
        # emergency live under a different key. Fail the payload; the next
        # healthy fetch self-heals.
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_update", "ff_considerable_update")
        features[1]["properties"]["parameters"] = "not-a-mapping"
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_mixed_vtec_and_fallback_identity_fails_closed(self):
        # If one warning's messages split between a VTEC key and the
        # office/event/day fallback key (e.g. only the downgrade lost its
        # VTEC), the downgrade can no longer evict the emergency — a false
        # present-tense emergency. Fail the payload instead.
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_update", "ff_considerable_update")
        features[1]["properties"]["parameters"].pop("VTEC")
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_same_instant_conflicting_tiers_fail_closed(self):
        # NWS timestamps are minute-resolution: a same-instant pair with
        # different tiers is an ambiguous correction — (time, tier)
        # ranking would silently keep the emergency. Fail closed.
        import pytest

        from src.data.source_status import SourceFetchError

        emergency = _cap_features("ff_emergency_update")[0]
        downgrade = _cap_features("ff_considerable_update")[0]
        downgrade["properties"]["sent"] = emergency["properties"]["sent"]
        _mock_nws({"features": [emergency, downgrade]})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_same_payload_cancel_retires_erroneous_emergency(self):
        # NWS withdraws an alert issued in error with a CAP Cancel; in the
        # transient window both can share a payload. The Cancel (terminal
        # VTEC action, later instant) must retire the lifecycle.
        emergency = _cap_features("ff_emergency_initial_alert")[0]
        cancel = _cap_features("ff_emergency_update")[0]
        props = cancel["properties"]
        props["messageType"] = "Cancel"
        props["parameters"]["VTEC"] = [
            props["parameters"]["VTEC"][0].replace("/O.EXT.", "/O.CAN.")
        ]
        _mock_nws({"features": [emergency, cancel]})
        lifecycles: dict = {}
        assert fetch_alerts(lifecycle_out=lifecycles) == []
        assert list(lifecycles.values()) == [0]

    @responses.activate
    def test_identity_guard_survives_sender_name_drift(self):
        # A VTEC-less downgrade that ALSO drifted senderName must still
        # group with its warning — the WMO station (KLSX) is the stable
        # office identity.
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_update", "ff_considerable_update")
        props = features[1]["properties"]
        props["parameters"].pop("VTEC")
        props["senderName"] = "NWS Saint Louis"
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_vtec_less_without_any_office_identity_fails_closed(self):
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_initial_alert")
        props = features[0]["properties"]
        props["parameters"].pop("VTEC")
        props["parameters"].pop("WMOidentifier", None)
        props["senderName"] = ""
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_mixed_identity_across_midnight_fails_closed(self):
        # The identity-mix guard must not be partitioned by the fallback
        # key's day: a VTEC emergency at 23:59 and a VTEC-less downgrade
        # at 00:01 are one warning.
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_update", "ff_considerable_update")
        props = features[1]["properties"]
        props["parameters"].pop("VTEC")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for field in ("sent", "effective", "onset"):
            if props.get(field):
                props[field] = tomorrow + props[field][10:]
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_junk_pagination_values_do_not_mark_census_incomplete(self):
        from src.data.nws_alerts import CENSUS_INCOMPLETE_KEY

        for junk in ([], "", False):
            _mock_nws(
                {
                    "features": _cap_features("ff_emergency_initial_alert"),
                    "pagination": junk,
                }
            )
        for _ in range(3):
            lifecycles: dict = {}
            alerts = fetch_alerts(lifecycle_out=lifecycles)
            assert len(alerts) == 1
            assert CENSUS_INCOMPLETE_KEY not in lifecycles

    @responses.activate
    def test_falsy_non_mapping_parameters_on_lifecycle_fails_closed(self):
        # `or {}` must not launder falsy junk ([] / "") past the
        # identity guard on emergency-capable features.
        import pytest

        from src.data.source_status import SourceFetchError

        for junk in ([], ""):
            features = _cap_features("ff_emergency_update", "ff_considerable_update")
            features[1]["properties"]["parameters"] = junk
            _mock_nws({"features": features})
            with pytest.raises(SourceFetchError):
                fetch_alerts(strict=True)

    @responses.activate
    def test_lifecycle_ordering_without_timestamps_fails_closed(self):
        # Ordering decides evictions: with two messages of one warning and
        # an unparseable time, an older emergency could beat a newer
        # downgrade. (Single-message lifecycles make no ordering decision
        # and stay permissive — synthetic fixtures carry no timestamps.)
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_update", "ff_considerable_update")
        for field in ("sent", "effective", "onset"):
            features[1]["properties"].pop(field, None)
        _mock_nws({"features": features})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_non_object_json_body_is_normalized(self):
        import pytest

        from src.data.source_status import SourceFetchError

        _mock_nws([1, 2, 3])
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_pds_and_catastrophic_update_same_warning_coalesce_to_emergency(self):
        # One warning, PDS Alert + a LATER catastrophic Update in the same
        # payload: one candidate, at the emergency tier — never two writer
        # calls.
        pds = _cap_features("tornado_pds_alert_synthetic")[0]
        emergency = _cap_features("tornado_pds_alert_synthetic")[0]
        props = emergency["properties"]
        props["parameters"]["tornadoDamageThreat"] = ["CATASTROPHIC"]
        props["messageType"] = "Update"
        props["id"] += ".upgrade"
        props["sent"] = props["sent"].replace("20:27", "22:27")
        _mock_nws({"features": [pds, emergency]})
        alerts = fetch_alerts()
        assert len(alerts) == 1
        assert alerts[0].emergency_designation == "Tornado Emergency"
        assert not alerts[0].event_id.endswith(":pds")

    @responses.activate
    def test_missing_features_list_is_an_error_not_an_empty_census(self):
        # A 200 whose body lacks a features LIST is schema drift, not a
        # quiet day — treating it as an empty census would falsely retire
        # every pending emergency draft.
        import pytest

        from src.data.source_status import SourceFetchError

        _mock_nws({})
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True)

    @responses.activate
    def test_missing_features_list_nonstrict_returns_empty(self):
        _mock_nws({"features": None})
        assert fetch_alerts() == []

    @responses.activate
    def test_paginated_payload_marks_census_incomplete(self):
        # A truncated (paginated) payload is not a lifecycle census — an
        # active emergency on a later page must not read as expired.
        from src.data.nws_alerts import CENSUS_INCOMPLETE_KEY

        payload = {
            "features": _cap_features("ff_emergency_initial_alert"),
            "pagination": {"next": "https://api.weather.gov/alerts/active?cursor=abc"},
        }
        _mock_nws(payload)
        lifecycles: dict = {}
        alerts = fetch_alerts(lifecycle_out=lifecycles)
        assert len(alerts) == 1
        assert lifecycles.get(CENSUS_INCOMPLETE_KEY) == 1

    @responses.activate
    def test_stale_payload_leaves_lifecycle_out_untouched(self):
        import pytest

        from src.data.source_status import SourceFetchError

        features = _cap_features("ff_emergency_initial_alert")
        stale_day = (date.today() - timedelta(days=10)).isoformat()
        props = features[0]["properties"]
        for field in ("sent", "effective", "onset"):
            if props.get(field):
                props[field] = stale_day + props[field][10:]
        _mock_nws({"features": features})
        lifecycles: dict = {}
        with pytest.raises(SourceFetchError):
            fetch_alerts(strict=True, lifecycle_out=lifecycles)
        assert lifecycles == {}

    @responses.activate
    def test_lifecycle_out_reports_current_tiers(self):
        # The runner reconciles pending drafts against the CURRENT
        # lifecycle tiers: 2=emergency, 1=PDS, 0=retired (downgraded);
        # absence means cancelled/expired.
        _mock_nws(
            {"features": _cap_features("ff_emergency_update", "tornado_pds_alert_synthetic")}
        )
        lifecycles: dict = {}
        alerts = fetch_alerts(lifecycle_out=lifecycles)
        assert len(alerts) == 2
        tiers = {key.split(":")[1]: tier for key, tier in lifecycles.items()}
        assert tiers["KLSX.FF.W.0050"] == 2
        assert tiers["KSGF.TO.W.0074"] == 1

    @responses.activate
    def test_lifecycle_out_reports_downgraded_lifecycle_as_retired(self):
        _mock_nws(
            {"features": _cap_features("ff_emergency_update", "ff_considerable_update")}
        )
        lifecycles: dict = {}
        assert fetch_alerts(lifecycle_out=lifecycles) == []
        assert list(lifecycles.values()) == [0]

    @responses.activate
    def test_emergency_event_id_survives_memory_event_base(self):
        # two_bot.memory._event_base keeps only the first three
        # underscore-separated parts of an event_id when grouping
        # recent_tweets_same_event — an underscore-rich id would collapse
        # every emergency from one office into a single memory bucket.
        from src.two_bot.memory import _event_base

        _mock_nws({"features": _cap_features("ff_emergency_initial_alert")})
        event_id = fetch_alerts()[0].event_id
        assert _event_base(event_id) == event_id


class TestVtecEventId:
    def test_prefers_active_code_over_terminated(self):
        # Segment transitions can carry a CAN/UPG of an old ETN alongside
        # the NEW of the active one — key on the active warning.
        from src.data.nws_alerts import _vtec_event_id

        params = {
            "VTEC": [
                "/O.CAN.KLSX.FF.W.0049.000000T0000Z-260710T2115Z/",
                "/O.NEW.KLSX.FF.W.0050.260710T0916Z-260710T1515Z/",
            ]
        }
        event_id = _vtec_event_id(params, "2026-07-10T04:16:00-05:00")
        assert "0050" in event_id
        assert "0049" not in event_id

    def test_terminated_only_code_still_keys(self):
        from src.data.nws_alerts import _vtec_event_id

        params = {"VTEC": ["/O.CAN.KLSX.FF.W.0049.000000T0000Z-260710T2115Z/"]}
        event_id = _vtec_event_id(params, "2026-07-10T04:16:00-05:00")
        assert "0049" in event_id

    def test_newline_delimited_codes_in_one_value(self):
        # Real CAP can pack multiple VTEC codes into one newline-delimited
        # parameter value — a terminated code must not shadow the active one.
        from src.data.nws_alerts import _vtec_event_id

        for sep in ("\n", "\r\n"):
            params = {
                "VTEC": [
                    "/O.CAN.KLSX.FF.W.0049.000000T0000Z-260710T2115Z/" + sep
                    + "/O.NEW.KLSX.FF.W.0050.260710T0916Z-260710T1515Z/"
                ]
            }
            event_id = _vtec_event_id(params, "2026-07-10T04:16:00-05:00")
            assert "0050" in event_id
            assert "0049" not in event_id


class TestMessageTime:
    def test_offset_change_orders_by_instant_not_string(self):
        # DST fallback: 01:30-04:00 (05:30Z) is EARLIER than 01:15-05:00
        # (06:15Z) even though it sorts later lexically.
        from src.data.nws_alerts import _message_dt

        earlier_instant = _message_dt({"sent": "2026-11-01T01:30:00-04:00"})
        later_instant = _message_dt({"sent": "2026-11-01T01:15:00-05:00"})
        assert earlier_instant < later_instant

    def test_unparseable_time_sorts_first(self):
        from src.data.nws_alerts import _message_dt

        assert _message_dt({"sent": "garbage"}) < _message_dt(
            {"sent": "2026-07-10T04:16:00-05:00"}
        )


class TestLifecycleReconciliation:
    """Every pending designated-tier draft must be re-attested by the
    current fetch at ITS tier: downgrades, upgrades, cancellations and
    expirations all mean the pending draft misstates the warning. The
    rejections are redraftable — the current-tier alert flows through the
    normal pipeline the same cycle."""

    def _reconcile(self, bot_state, lifecycles):
        from src.orchestrator.sources.nws_alerts import (
            _reconcile_pending_lifecycle_drafts,
        )

        return _reconcile_pending_lifecycle_drafts(bot_state, lifecycles)

    def test_pending_emergency_rejected_when_lifecycle_downgraded(self):
        bot_state = {
            "drafts": [{"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "pending"}]
        }
        assert self._reconcile(bot_state, {"nws_vtec:KLSX.FF.W.0050:2026": 0}) == 1
        draft = bot_state["drafts"][0]
        assert draft["status"] == "rejected"
        assert draft["rejected_reason"] == "nws_lifecycle_downgraded"

    def test_pending_emergency_rejected_when_lifecycle_absent(self):
        # Cancelled or expired: the warning vanished from /alerts/active.
        bot_state = {
            "drafts": [{"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "pending"}]
        }
        assert self._reconcile(bot_state, {}) == 1
        assert bot_state["drafts"][0]["status"] == "rejected"

    def test_pending_pds_rejected_when_lifecycle_retired(self):
        bot_state = {
            "drafts": [
                {"event_id": "nws_vtec:KSGF.TO.W.0074:2026:pds", "status": "pending"}
            ]
        }
        assert self._reconcile(bot_state, {"nws_vtec:KSGF.TO.W.0074:2026": 0}) == 1

    def test_pending_pds_rejected_when_lifecycle_upgraded(self):
        # Tier transitions are owned entirely by reconciliation: the stale
        # PDS frees its pending-type-cap slot BEFORE the emergency is
        # admitted (a post-save supersede could never free the slot its
        # own replacement needed). Transition rejections are redraftable,
        # so a killed emergency doesn't strand the lifecycle.
        bot_state = {
            "drafts": [
                {"event_id": "nws_vtec:KSGF.TO.W.0074:2026:pds", "status": "pending"}
            ]
        }
        assert self._reconcile(bot_state, {"nws_vtec:KSGF.TO.W.0074:2026": 2}) == 1
        draft = bot_state["drafts"][0]
        assert draft["status"] == "rejected"
        assert draft["rejected_reason"] == "superseded_by_emergency_upgrade"

    def test_pending_drafts_kept_while_tier_holds(self):
        bot_state = {
            "drafts": [
                {"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "pending"},
                {"event_id": "nws_vtec:KSGF.TO.W.0074:2026:pds", "status": "pending"},
            ]
        }
        lifecycles = {
            "nws_vtec:KLSX.FF.W.0050:2026": 2,
            "nws_vtec:KSGF.TO.W.0074:2026": 1,
        }
        assert self._reconcile(bot_state, lifecycles) == 0
        assert all(d["status"] == "pending" for d in bot_state["drafts"])

    def test_posted_and_rejected_drafts_untouched(self):
        bot_state = {
            "drafts": [
                {"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "posted"},
                {"event_id": "nws_vtec:KLSX.FF.W.0051:2026", "status": "rejected"},
            ]
        }
        assert self._reconcile(bot_state, {}) == 0

    def test_approved_unposted_draft_rejected_when_lifecycle_ends(self):
        # The dashboard's approval creates a publish intent the posting
        # worker honors later — an approved-but-unposted stale emergency
        # is still preventable and must be reconciled (posting requires
        # status == "approved", so the rejection invalidates the intent).
        bot_state = {
            "drafts": [
                {"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "approved"}
            ]
        }
        assert self._reconcile(bot_state, {}) == 1
        assert bot_state["drafts"][0]["status"] == "rejected"

    def test_rejection_stamps_updated_at_for_merge_recency(self):
        # _merge_drafts resolves same-id conflicts by recency: a rejection
        # that doesn't advance updated_at would lose the merge to a stale
        # pending copy coming back from the dashboard.
        from src.state import _merge_drafts

        local = {
            "id": "d1",
            "event_id": "nws_vtec:KLSX.FF.W.0050:2026",
            "status": "pending",
            "created_at": "2026-07-14T09:00:00Z",
            "updated_at": "2026-07-14T10:00:00Z",
        }
        dashboard_copy = dict(local, updated_at="2026-07-14T10:05:00Z")
        bot_state = {"drafts": [local]}

        assert self._reconcile(bot_state, {}) == 1
        assert local["updated_at"] == local["rejected_at"]

        merged = _merge_drafts([local], [dashboard_copy])
        assert merged[0]["status"] == "rejected"

    def test_non_lifecycle_ids_untouched(self):
        bot_state = {
            "drafts": [{"event_id": "nws_urn:oid:2.49.abc", "status": "pending"}]
        }
        assert self._reconcile(bot_state, {}) == 0
        assert bot_state["drafts"][0]["status"] == "pending"


class TestRunNwsAlertsWiring:
    def test_upgrade_frees_pending_slot_before_admission(self, monkeypatch):
        """The stale PDS is retired by reconciliation BEFORE the emergency
        is enqueued — a pending PDS would otherwise hold the pending-type
        cap slot its own replacement needs."""
        from src.orchestrator.sources import nws_alerts as runner

        emergency = SevereWeatherAlert(
            event_type="Tornado Warning",
            area="Webster, MO",
            severity="Extreme",
            headline="Tornado Warning",
            event_id="nws_vtec:KSGF.TO.W.0074:2026",
            emergency_designation="Tornado Emergency",
        )
        bot_state = {
            "posted_events": [],
            "drafts": [
                {"event_id": "nws_vtec:KSGF.TO.W.0074:2026:pds", "status": "pending"}
            ],
        }

        def fake_fetch(*, strict=False, lifecycle_out=None):
            if lifecycle_out is not None:
                lifecycle_out["nws_vtec:KSGF.TO.W.0074:2026"] = 2
            return [emergency]

        captured: dict = {}

        def fake_enqueue(bot_state_, **kwargs):
            # The PDS slot is already free when the emergency is enqueued.
            assert bot_state_["drafts"][0]["status"] == "rejected"
            captured.update(kwargs)
            return True

        monkeypatch.setattr(runner.nws_alerts, "fetch_alerts", fake_fetch)
        monkeypatch.setattr(runner, "_enqueue_story_candidate", fake_enqueue)
        monkeypatch.setattr(runner, "_should_draft", lambda score, event_id: True)

        runner.run_nws_alerts(bot_state, {"sources": []})

        assert captured["event_id"] == "nws_vtec:KSGF.TO.W.0074:2026"
        draft = bot_state["drafts"][0]
        assert draft["status"] == "rejected"
        assert draft["rejected_reason"] == "superseded_by_emergency_upgrade"

    def test_census_incomplete_skips_reconciliation(self, monkeypatch):
        """A paginated (truncated) payload is not a lifecycle census — an
        active emergency on a later page must not be retired."""
        from src.data.nws_alerts import CENSUS_INCOMPLETE_KEY
        from src.orchestrator.sources import nws_alerts as runner

        bot_state = {
            "posted_events": [],
            "drafts": [
                {"event_id": "nws_vtec:KLSX.FF.W.0050:2026", "status": "pending"}
            ],
        }

        def fake_fetch(*, strict=False, lifecycle_out=None):
            if lifecycle_out is not None:
                lifecycle_out[CENSUS_INCOMPLETE_KEY] = 1
            return []

        monkeypatch.setattr(runner.nws_alerts, "fetch_alerts", fake_fetch)

        runner.run_nws_alerts(bot_state, {"sources": []})

        assert bot_state["drafts"][0]["status"] == "pending"


class TestPdsDowngradeSkip:
    """A PDS-tier alert whose warning already surfaced at the emergency
    tier is a downgrade, not news — cross-cycle tier moves must be
    monotonic upward."""

    def _pds_alert(self) -> SevereWeatherAlert:
        return SevereWeatherAlert(
            event_type="Tornado Warning",
            area="Webster, MO",
            severity="Severe",
            headline="Tornado Warning",
            event_id="nws_vtec:KSGF.TO.W.0074:2026:pds",
            emergency_designation="Particularly Dangerous Situation",
        )

    def test_pds_after_posted_emergency_is_skipped(self):
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        bot_state = {"posted_events": ["nws_vtec:KSGF.TO.W.0074:2026"], "drafts": []}
        assert _pds_downgrade_of_known_emergency(bot_state, self._pds_alert())

    def test_pds_with_posted_emergency_draft_is_skipped(self):
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        bot_state = {
            "posted_events": [],
            "drafts": [{"event_id": "nws_vtec:KSGF.TO.W.0074:2026", "status": "posted"}],
        }
        assert _pds_downgrade_of_known_emergency(bot_state, self._pds_alert())

    def test_pds_with_only_pending_emergency_draft_is_not_skipped(self):
        # A merely-pending emergency is retired by lifecycle reconciliation
        # on the downgrade cycle — it must not block the honest PDS tier
        # (only a POSTED emergency, already on the public record, does).
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        bot_state = {
            "posted_events": [],
            "drafts": [{"event_id": "nws_vtec:KSGF.TO.W.0074:2026", "status": "pending"}],
        }
        assert not _pds_downgrade_of_known_emergency(bot_state, self._pds_alert())

    def test_pds_with_rejected_emergency_draft_is_not_skipped(self):
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        bot_state = {
            "posted_events": [],
            "drafts": [{"event_id": "nws_vtec:KSGF.TO.W.0074:2026", "status": "rejected"}],
        }
        assert not _pds_downgrade_of_known_emergency(bot_state, self._pds_alert())

    def test_fresh_pds_is_not_skipped(self):
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        bot_state = {"posted_events": [], "drafts": []}
        assert not _pds_downgrade_of_known_emergency(bot_state, self._pds_alert())

    def test_emergency_tier_is_never_skipped(self):
        from src.orchestrator.sources.nws_alerts import _pds_downgrade_of_known_emergency

        alert = SevereWeatherAlert(
            event_type="Tornado Warning",
            area="Webster, MO",
            severity="Extreme",
            headline="Tornado Warning",
            event_id="nws_vtec:KSGF.TO.W.0074:2026",
            emergency_designation="Tornado Emergency",
        )
        bot_state = {"posted_events": [], "drafts": []}
        assert not _pds_downgrade_of_known_emergency(bot_state, alert)
