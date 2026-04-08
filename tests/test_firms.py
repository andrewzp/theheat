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
            + "34.05,-118.25,90,150.0\n"
            + "40.71,-74.01,85,200.0\n"
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
        assert fires[1].frp == 200.0

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
        )
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            body=csv_body,
            status=200,
        )
        fires = fetch_fires(frp_min=100.0)
        assert len(fires) == 0

    def test_no_api_key_returns_empty(self):
        with patch("src.data.firms.FIRMS_API_KEY", ""):
            fires = fetch_fires()
            assert fires == []

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_api_error_returns_empty(self):
        responses.add(
            responses.GET,
            "https://firms.modaps.eosdis.nasa.gov/api/area/csv/test_key/VIIRS_SNPP_NRT/world/1",
            status=500,
        )
        fires = fetch_fires()
        assert fires == []

    @responses.activate
    @patch("src.data.firms.FIRMS_API_KEY", "test_key")
    def test_malformed_csv_rows_skipped(self):
        csv_body = (
            FIRMS_CSV_HEADER
            + "34.05,-118.25,NOT_A_NUMBER,150.0\n"  # malformed confidence
            + "40.71,-74.01,85,200.0\n"  # valid row
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
            + "34.05,-118.25,90,150.0\n"
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
    def test_us_coordinates(self):
        region, country = reverse_geocode_simple(34.05, -118.25)
        assert "US" in region
        assert country == "US"

    def test_australia_coordinates(self):
        region, country = reverse_geocode_simple(-33.87, 151.21)
        assert region == "Australia"
        assert country == "Australia"

    def test_europe_coordinates(self):
        region, country = reverse_geocode_simple(48.86, 2.35)
        assert region == "Europe"
        assert country == "Western Europe"

    def test_unknown_coordinates(self):
        # Deep ocean (south Atlantic)
        region, country = reverse_geocode_simple(-60.0, -30.0)
        assert "S" in region  # fallback coordinate format
        assert country == "Unknown"


class TestLatLonToRegion:
    def test_northeastern_us(self):
        assert _lat_lon_to_region(42.0, -72.0) == "Northeastern US"

    def test_southeastern_us(self):
        assert _lat_lon_to_region(30.0, -85.0) == "Southeastern US"

    def test_northwestern_us(self):
        assert _lat_lon_to_region(47.0, -122.0) == "Northwestern US"

    def test_southwestern_us(self):
        assert _lat_lon_to_region(33.0, -112.0) == "Southwestern US"

    def test_canada(self):
        assert _lat_lon_to_region(55.0, -100.0) == "Canada"

    def test_latin_america(self):
        assert _lat_lon_to_region(20.0, -100.0) == "Latin America"

    def test_europe(self):
        assert _lat_lon_to_region(50.0, 10.0) == "Europe"

    def test_middle_east(self):
        assert _lat_lon_to_region(30.0, 45.0) == "Middle East"

    def test_africa(self):
        assert _lat_lon_to_region(5.0, 20.0) == "Africa"

    def test_asia(self):
        assert _lat_lon_to_region(35.0, 100.0) == "Asia"

    def test_australia(self):
        assert _lat_lon_to_region(-25.0, 135.0) == "Australia"

    def test_fallback_coordinate_format(self):
        result = _lat_lon_to_region(-60.0, -30.0)
        assert "60S" in result
        assert "30W" in result


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

    def test_unknown(self):
        assert _lat_lon_to_country(70.0, 70.0) == "Unknown"
