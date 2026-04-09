"""Tests for Open-Meteo Marine ocean wave data."""

import responses

from src.data.ocean import (
    OceanReading,
    ExtremeWaveEvent,
    fetch_ocean_conditions,
    detect_extreme_waves,
    LOCATION_THRESHOLDS_M,
    MARINE_URL,
)


def _mock_marine_response(wave_height: float):
    """Helper to generate a mock marine API response."""
    return {
        "daily": {
            "wave_height_max": [wave_height],
        }
    }


class TestFetchOceanConditions:
    @responses.activate
    def test_happy_path_returns_readings(self):
        # Mock all 16 ocean points
        for _ in range(16):
            responses.add(
                responses.GET,
                MARINE_URL,
                json=_mock_marine_response(5.0),
                status=200,
            )
        readings = fetch_ocean_conditions()
        assert len(readings) == 16
        assert all(isinstance(r, OceanReading) for r in readings)
        assert readings[0].wave_height_max_m == 5.0
        assert readings[0].sst_c is None

    @responses.activate
    def test_skips_failed_points(self):
        # First point succeeds, rest fail
        responses.add(responses.GET, MARINE_URL, json=_mock_marine_response(3.0), status=200)
        for _ in range(15):
            responses.add(responses.GET, MARINE_URL, status=500)
        readings = fetch_ocean_conditions()
        assert len(readings) == 1

    @responses.activate
    def test_skips_null_wave_height(self):
        responses.add(
            responses.GET,
            MARINE_URL,
            json={"daily": {"wave_height_max": [None]}},
            status=200,
        )
        for _ in range(15):
            responses.add(responses.GET, MARINE_URL, json=_mock_marine_response(3.0), status=200)
        readings = fetch_ocean_conditions()
        assert len(readings) == 15  # first one skipped

    @responses.activate
    def test_event_id_format(self):
        for _ in range(16):
            responses.add(responses.GET, MARINE_URL, json=_mock_marine_response(3.0), status=200)
        readings = fetch_ocean_conditions()
        assert readings[0].event_id.startswith("ocean_gulf_of_mexico_")


class TestDetectExtremeWaves:
    def test_detects_extreme_waves_calm_location(self):
        """12m in Gulf of Mexico is extreme (default threshold 10m)."""
        readings = [
            OceanReading("Gulf of Mexico", "Atlantic", 28.5, -88.0, 12.0, 25.0, "2026-04-08", "ocean_gom_1"),
        ]
        events = detect_extreme_waves(readings)
        assert len(events) == 1
        assert events[0].location == "Gulf of Mexico"

    def test_drake_passage_normal_waves_filtered(self):
        """11m in Drake Passage is normal — threshold is 15m there."""
        readings = [
            OceanReading("Drake Passage", "Southern", -60.0, -60.0, 11.0, None, "2026-04-08", "ocean_dp_1"),
        ]
        events = detect_extreme_waves(readings)
        assert len(events) == 0

    def test_drake_passage_truly_extreme(self):
        """16m in Drake Passage IS extreme — above the 15m local threshold."""
        readings = [
            OceanReading("Drake Passage", "Southern", -60.0, -60.0, 16.0, None, "2026-04-08", "ocean_dp_1"),
        ]
        events = detect_extreme_waves(readings)
        assert len(events) == 1

    def test_north_sea_needs_higher_threshold(self):
        """11m in North Sea filtered out — threshold is 12m there."""
        readings = [
            OceanReading("North Sea", "Atlantic", 58.0, -5.0, 11.0, 10.0, "2026-04-08", "ocean_ns_1"),
        ]
        events = detect_extreme_waves(readings)
        assert len(events) == 0

    def test_rough_locations_all_have_thresholds(self):
        """Every notoriously rough location has a raised threshold."""
        for loc in LOCATION_THRESHOLDS_M:
            assert LOCATION_THRESHOLDS_M[loc] > 10.0, f"{loc} threshold too low"

    def test_custom_threshold(self):
        readings = [
            OceanReading("Test", "Atlantic", 0, 0, 6.0, None, "2026-04-08", "t1"),
        ]
        assert len(detect_extreme_waves(readings, threshold_m=5.0)) == 1
        assert len(detect_extreme_waves(readings, threshold_m=7.0)) == 0

    def test_empty_readings(self):
        assert detect_extreme_waves([]) == []
