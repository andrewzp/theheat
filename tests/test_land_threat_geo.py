"""Tests for nearest-landmass resolution (#375 geo half)."""

from __future__ import annotations

from src.data.land_threat_geo import NearestLandmass, nearest_landmass

_CITIES = [
    {"city": "Taipei", "country": "Taiwan", "lat": "25.03", "lon": "121.57", "elevation_m": "9"},
    {"city": "Manila", "country": "Philippines", "lat": "14.60", "lon": "120.98", "elevation_m": "16"},
]


def test_nearest_landmass_picks_the_closest_city_and_converts_to_nm():
    # A point ~1 degree east of Taipei (~59 NM at this latitude).
    result = nearest_landmass(25.03, 122.57, _CITIES)
    assert result is not None
    assert result.country == "Taiwan"
    assert result.city == "Taipei"
    assert 50 < result.distance_nm < 60


def test_nearest_landmass_none_on_empty_cities():
    assert nearest_landmass(25.0, 122.0, []) is None


def test_nearest_landmass_skips_malformed_rows():
    rows = [{"city": "Broken", "country": "Nowhere", "lat": "not-a-number", "lon": ""}] + _CITIES
    result = nearest_landmass(14.60, 121.98, rows)
    assert result is not None
    assert result.city == "Manila"


def test_nearest_landmass_is_frozen_value_object():
    lm = NearestLandmass(country="Taiwan", city="Taipei", distance_nm=25.0)
    assert lm.distance_nm == 25.0
