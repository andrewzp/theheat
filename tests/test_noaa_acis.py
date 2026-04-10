"""Tests for NOAA ACIS helpers."""

from src.data.noaa_acis import get_state_code


class TestGetStateCode:
    def test_prefers_explicit_state_code(self):
        assert get_state_code("Washington DC", "MD") == "MD"

    def test_maps_washington_dc_correctly(self):
        assert get_state_code("Washington DC") == "DC"
