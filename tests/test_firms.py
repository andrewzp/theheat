"""Tests for NASA FIRMS fire detection data."""

from datetime import date
from unittest.mock import patch

import responses

from src.data.firms import (
    FireEvent,
    fetch_fires,
    reverse_geocode_simple,
    _lat_lon_to_region,
    _lat_lon_to_country,
)

FIRMS_CSV_HEADER = "latitude,longitude,confidence,frp\n"


class TestFetchFires:
    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_happy_path_returns_filtered_fires(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,90,350.0\n"
            + "40.71,-74.01,85,500.0\n"
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires()
        assert len(fires) == 2
        assert all(isinstance(f, FireEvent) for f in fires)
        assert fires[0].confidence == 90
        assert fires[1].frp == 500.0

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_confidence_below_threshold_excluded(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,50,150.0\n"  # confidence too low
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires(confidence_min=80)
        assert len(fires) == 0

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_frp_below_threshold_excluded(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,90,10.0\n"  # frp too low
            + "40.71,-74.01,90,200.0\n"   # also below new 250 default
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        # Default frp_min is 250 MW (Apr 2026: raised from 100 to cut noise).
        assert fetch_fires() == []
        # Explicit low threshold still honors the older behavior.
        assert len(fetch_fires(frp_min=100.0)) == 1

    def test_no_api_key_returns_empty(self):
        with patch("src.data.firms.FIRMS_API_KEY", ""):
            fires = fetch_fires()
            assert fires == []

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_api_error_returns_empty(self):
        for _ in range(3):
            responses.add(
                responses.GET,
                "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
                status=500,
            )
        fires = fetch_fires()
        assert fires == []

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_transient_5xx_retries_then_returns_fires(self):
        csv_body = FIRMS_CSV_HEADER + "34.05,-118.25,90,350.0\n"
        url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1"
        responses.add(responses.GET, url, status=502)
        responses.add(responses.GET, url, body=csv_body, status=200)

        fires = fetch_fires()

        assert len(fires) == 1
        assert len(responses.calls) == 2

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_viirs_letter_confidence_parsed(self):
        """VIIRS_SNPP_NRT uses categorical l/n/h confidence, not percentages.

        The old parser did int("h") and silently dropped every VIIRS row,
        which is why production fire detection returned 0 all day. Regression
        guard: make sure 'h' survives the confidence gate and 'l' does not.
        """
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,h,400.0\n"   # high confidence → maps to 95
            + "40.71,-74.01,n,350.0\n"    # nominal → 70, below 80 default
            + "1.0,1.0,l,600.0\n"          # low → 30
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires()
        assert len(fires) == 1
        assert fires[0].confidence == 95

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_malformed_csv_rows_skipped(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,NOT_A_NUMBER,400.0\n"  # malformed confidence
            + "40.71,-74.01,85,350.0\n"  # valid row
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires()
        assert len(fires) == 1
        assert fires[0].confidence == 85

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_fire_event_id_format(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,90,350.0\n"
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires()
        assert len(fires) == 1
        assert fires[0].event_id.startswith("fire_34.05_-118.25_")


class TestReverseGeocodeSimple:
    """The replacement for the old continent-only labels — produces
    specific region names so Gemini doesn't have to guess (or make up)
    a fire's location. Regression target: no more 'somewhere in Asia,
    Unknown.'"""

    def test_los_angeles_is_california(self):
        region, country = reverse_geocode_simple(34.05, -118.25)
        assert region == "California"
        assert country == "US"

    def test_seattle_is_pacific_northwest(self):
        region, country = reverse_geocode_simple(47.6, -122.3)
        assert region == "the Pacific Northwest"
        assert country == "US"

    def test_phoenix_is_us_southwest(self):
        region, country = reverse_geocode_simple(33.45, -112.07)
        assert region == "the US Southwest"
        assert country == "US"

    def test_sydney_is_new_south_wales(self):
        region, country = reverse_geocode_simple(-33.87, 151.21)
        assert region == "New South Wales"
        assert country == "Australia"

    def test_paris_is_france(self):
        region, country = reverse_geocode_simple(48.86, 2.35)
        assert region == "France"
        assert country == "France"

    def test_deep_ocean_falls_back_to_coords(self):
        region, country = reverse_geocode_simple(-60.0, -30.0)
        assert "S" in region  # fallback coordinate format
        assert country == "Unknown"

    # Previously "somewhere in Asia" — the whole point of the fix.
    def test_siberia_specific_label(self):
        region, country = reverse_geocode_simple(62.0, 129.0)
        assert region == "eastern Siberia"
        assert country == "Russia"

    def test_kazakhstan_steppe_specific(self):
        region, country = reverse_geocode_simple(48.0, 68.0)
        assert region == "the Kazakhstan steppe"
        assert country == "Kazakhstan"

    def test_amazon_basin_specific(self):
        region, country = reverse_geocode_simple(-3.1, -60.0)
        assert region == "the Amazon Basin"
        assert country == "Brazil"

    def test_congo_basin_specific(self):
        region, country = reverse_geocode_simple(-2.0, 22.0)
        assert region == "the Congo Basin"
        assert country == "DR Congo"

    def test_central_india(self):
        region, country = reverse_geocode_simple(22.0, 78.0)
        assert region == "India"
        assert country == "India"

    def test_iberia_is_iberian_peninsula(self):
        region, country = reverse_geocode_simple(40.0, -4.0)
        assert region == "the Iberian Peninsula"
        assert country == "Spain"

    def test_patagonia_specific(self):
        region, country = reverse_geocode_simple(-50.0, -70.0)
        assert region == "Patagonia"
        assert country == "Argentina"


class TestLatLonToRegion:
    """Region lookups against the bounding-box table. Values moved to
    more specific labels as part of the Apr 24 geocoder overhaul."""

    def test_northeastern_us(self):
        assert _lat_lon_to_region(42.0, -72.0) == "the Northeastern US"

    def test_southeastern_us(self):
        assert _lat_lon_to_region(33.0, -82.0) == "the Southeastern US"

    def test_california_specific(self):
        assert _lat_lon_to_region(37.7, -122.4) == "California"

    def test_florida_specific(self):
        assert _lat_lon_to_region(27.0, -81.0) == "Florida"

    def test_canadian_prairies_specific(self):
        assert _lat_lon_to_region(55.0, -100.0) == "the Canadian Prairies"

    def test_mexico_not_latin_america(self):
        assert _lat_lon_to_region(20.0, -100.0) == "Mexico"

    def test_central_europe_specific(self):
        assert _lat_lon_to_region(50.0, 10.0) == "Central Europe"

    def test_levant_specific(self):
        assert _lat_lon_to_region(33.0, 44.0) == "the Levant"

    def test_congo_basin(self):
        assert _lat_lon_to_region(0.0, 20.0) == "the Congo Basin"

    def test_china_specific(self):
        assert _lat_lon_to_region(35.0, 105.0) == "China"

    def test_central_australia(self):
        assert _lat_lon_to_region(-25.0, 135.0) == "the Northern Territory"

    def test_fallback_coordinate_format(self):
        result = _lat_lon_to_region(-60.0, -30.0)
        assert "60" in result
        assert "S" in result


class TestLatLonToCountry:
    def test_us(self):
        assert _lat_lon_to_country(34.0, -118.0) == "US"

    def test_canada(self):
        assert _lat_lon_to_country(55.0, -100.0) == "Canada"

    def test_mexico(self):
        assert _lat_lon_to_country(20.0, -100.0) == "Mexico"

    def test_brazil(self):
        assert _lat_lon_to_country(-15.0, -47.0) == "Brazil"

    def test_australia(self):
        assert _lat_lon_to_country(-25.0, 135.0) == "Australia"

    def test_russia(self):
        assert _lat_lon_to_country(62.0, 129.0) == "Russia"

    def test_kazakhstan(self):
        assert _lat_lon_to_country(48.0, 68.0) == "Kazakhstan"

    def test_unknown_deep_ocean(self):
        # South Atlantic deep ocean, far from any of our boxes.
        assert _lat_lon_to_country(-55.0, -45.0) == "Unknown"


from pathlib import Path  # noqa: E402

from src.two_bot.intern import build_fire_bundle  # noqa: E402

HMS_URL_BASE = "https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Text"
FIRMS_PRIMARY_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1"
)
HMS_HEADER = "        Lon,        Lat, YearDay, Time, Satellite, Method, Ecosystem, FRP\n"


def _hms_url(today=None):
    today = today or date.today()
    return f"{HMS_URL_BASE}/{today:%Y}/{today:%m}/hms_fire{today:%Y%m%d}.txt"


class TestNoaaHmsWitness:
    """R-02: NOAA HMS independent fire witness for firms.

    HMS fires ONLY when the primary FIRMS fetch fails (with_witness). It is an
    independent host + instrument, N. America only, graded observed_alt_host.
    """

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_firms_primary_healthy_skips_hms(self):
        # HMS URL intentionally NOT registered: if the witness fired, `responses`
        # would raise on the unregistered URL. Healthy primary -> no source_leg.
        responses.add(
            responses.GET, FIRMS_PRIMARY_URL,
            body=FIRMS_CSV_HEADER + "34.05,-118.25,90,350.0\n", status=200,
        )
        fires = fetch_fires()
        assert len(fires) == 1
        assert fires[0].source_leg is None

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_firms_hms_parses_fixture(self):
        for _ in range(3):
            responses.add(responses.GET, FIRMS_PRIMARY_URL, status=503)
        fixture = (Path(__file__).parent / "fixtures" / "hms_fire_sample.txt").read_text()
        responses.add(responses.GET, _hms_url(), body=fixture, status=200)
        fires = fetch_fires()  # default frp_min=250
        # Fixture has 2 N.America rows >=250 MW; one <250, one -999, one outside NA.
        assert len(fires) == 2
        assert all(f.source_leg == "noaa_hms" for f in fires)
        assert all(f.confidence == 80 for f in fires)
        assert {round(f.frp) for f in fires} == {389, 520}

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_firms_hms_empty_outside_north_america(self):
        for _ in range(3):
            responses.add(responses.GET, FIRMS_PRIMARY_URL, status=503)
        body = HMS_HEADER + " 130.000000, -25.000000, 2026164, 0203, HIMAWARI, NGFS, 15, 600.000\n"
        responses.add(responses.GET, _hms_url(), body=body, status=200)
        # High FRP but in Australia -> HMS has no coverage there -> nothing.
        assert fetch_fires() == []

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_firms_frp_negative_treated_missing(self):
        for _ in range(3):
            responses.add(responses.GET, FIRMS_PRIMARY_URL, status=503)
        body = (
            HMS_HEADER
            + "-100.000000, 40.000000, 2026164, 0202, GOES-EAST, NGFS, 10, -999.000\n"
            + "-118.250000, 34.050000, 2026164, 0201, GOES-WEST, NGFS, 22, 400.000\n"
        )
        responses.add(responses.GET, _hms_url(), body=body, status=200)
        fires = fetch_fires()
        assert len(fires) == 1  # -999 row dropped as missing, not treated as 0
        assert round(fires[0].frp) == 400

    def test_firms_hms_observed_alt_host_grade(self):
        fire = FireEvent(
            lat=34.05, lon=-118.25, confidence=80, frp=520.0,
            nearest_city="California", country="US", event_id="fire_x",
            source_leg="noaa_hms",
        )
        bundle = build_fire_bundle(fire)
        grades = [f for f in bundle.current_facts if f.get("label") == "evidence_grade"]
        assert grades == [{"label": "evidence_grade", "value": "observed_alt_host"}]

    def test_firms_primary_fire_has_no_grade(self):
        fire = FireEvent(
            lat=34.05, lon=-118.25, confidence=90, frp=520.0,
            nearest_city="California", country="US", event_id="fire_y",
        )
        bundle = build_fire_bundle(fire)
        assert not any(f.get("label") == "evidence_grade" for f in bundle.current_facts)
