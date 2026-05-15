"""Tests for NHC tropical-cyclone ingestion and detection."""

import responses

from src.data import nhc
from src.data.cyclones import CycloneAdvisory, saffir_simpson_category


def _advisory(
    *,
    issued_at: str,
    wind_kt: int,
    advisory_number: str = "1",
    storm_id: str = "AL012026",
    text: str = "",
) -> CycloneAdvisory:
    return CycloneAdvisory(
        source="nhc",
        storm_id=storm_id,
        storm_name="Beryl",
        basin="Atlantic",
        advisory_number=advisory_number,
        issued_at=issued_at,
        wind_kt=wind_kt,
        pressure_mb=950,
        lat=15.0,
        lon=-75.0,
        public_advisory_url="https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
        advisory_text=text,
    )


class TestFetchActiveCyclones:
    @responses.activate
    def test_empty_active_storms_is_success(self):
        responses.add(
            responses.GET,
            nhc.NHC_CURRENT_STORMS_URL,
            json={"activeStorms": []},
            status=200,
        )

        assert nhc.fetch_active_cyclones() == []

    @responses.activate
    def test_maps_active_storm_fields_and_fetches_public_advisory(self):
        responses.add(
            responses.GET,
            nhc.NHC_CURRENT_STORMS_URL,
            json={
                "activeStorms": [
                    {
                        "id": "AL012026",
                        "name": "Beryl",
                        "basin": "Atlantic",
                        "advisoryNumber": "12",
                        "lastUpdate": "2026-07-01T12:00:00Z",
                        "intensity": "115",
                        "pressure": "950",
                        "latitudeNumeric": "15.0N",
                        "longitudeNumeric": "75.0W",
                        "publicAdvisory": "/text/MIATCPAT1.shtml",
                    }
                ]
            },
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml",
            body="Beryl made landfall near Example Coast.",
            status=200,
        )

        advisories = nhc.fetch_active_cyclones()

        assert len(advisories) == 1
        advisory = advisories[0]
        assert advisory.storm_id == "AL012026"
        assert advisory.wind_kt == 115
        assert advisory.pressure_mb == 950
        assert advisory.lat == 15.0
        assert advisory.lon == -75.0
        assert advisory.category == 4
        assert advisory.public_advisory_url == "https://www.nhc.noaa.gov/text/MIATCPAT1.shtml"
        assert "landfall" in advisory.advisory_text

    @responses.activate
    def test_api_error_returns_empty_non_strict(self):
        responses.add(responses.GET, nhc.NHC_CURRENT_STORMS_URL, status=500)
        assert nhc.fetch_active_cyclones() == []


class TestCycloneDetection:
    def test_saffir_simpson_category_boundaries(self):
        assert saffir_simpson_category(63) == 0
        assert saffir_simpson_category(64) == 1
        assert saffir_simpson_category(83) == 2
        assert saffir_simpson_category(96) == 3
        assert saffir_simpson_category(113) == 4
        assert saffir_simpson_category(137) == 5

    def test_rapid_intensification_detects_30kt_24h_jump(self):
        events = nhc.detect_rapid_intensification([
            _advisory(issued_at="2026-07-01T00:00:00Z", wind_kt=65, advisory_number="8"),
            _advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=100, advisory_number="12"),
        ])

        assert len(events) == 1
        event = events[0]
        assert event.delta_kt_24h == 35
        assert event.previous_category == 1
        assert event.current_category == 3
        assert event.event_id == "nhc_ri_al012026_12_100"

    def test_rapid_intensification_ignores_small_changes(self):
        events = nhc.detect_rapid_intensification([
            _advisory(issued_at="2026-07-01T00:00:00Z", wind_kt=65, advisory_number="8"),
            _advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=90, advisory_number="12"),
        ])

        assert events == []

    def test_tier_crossing_uses_prior_state(self):
        events = nhc.detect_tier_crossings(
            [_advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=115, advisory_number="12")],
            {"nhc:al012026": 2},
        )

        assert len(events) == 1
        assert events[0].from_category == 2
        assert events[0].to_category == 4
        assert events[0].event_id == "nhc_tier_al012026_12_cat4"

    def test_tier_crossing_dedupes_same_tier(self):
        events = nhc.detect_tier_crossings(
            [_advisory(issued_at="2026-07-02T00:00:00Z", wind_kt=115, advisory_number="12")],
            {"nhc:al012026": 4},
        )

        assert events == []

    def test_landfall_requires_major_hurricane_and_explicit_text(self):
        events = nhc.detect_landfalls([
            _advisory(
                issued_at="2026-07-02T00:00:00Z",
                wind_kt=100,
                advisory_number="12",
                text="Beryl made landfall near Cedar Key, Florida with sustained winds.",
            )
        ])

        assert len(events) == 1
        assert events[0].location == "Cedar Key, Florida"
        assert events[0].category == 3

    def test_landfall_ignores_sub_major_storm(self):
        events = nhc.detect_landfalls([
            _advisory(
                issued_at="2026-07-02T00:00:00Z",
                wind_kt=90,
                advisory_number="12",
                text="Beryl made landfall near Cedar Key, Florida.",
            )
        ])

        assert events == []

    def test_basin_record_helper_uses_supplied_archive_rule(self):
        events = nhc.detect_basin_records(
            [_advisory(issued_at="2026-06-15T00:00:00Z", wind_kt=115, advisory_number="9")],
            {
                "Atlantic": {
                    "earliest_cat4": {
                        "min_category": 4,
                        "label": "earliest Atlantic Category 4 on record",
                        "scope": "Atlantic best-track archive",
                    }
                }
            },
        )

        assert len(events) == 1
        assert events[0].record_label == "earliest Atlantic Category 4 on record"
        assert events[0].record_scope == "Atlantic best-track archive"
