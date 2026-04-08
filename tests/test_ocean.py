"""Tests for Open-Meteo Marine ocean wave data."""

import responses

from src.data.ocean import (
    OceanReading,
    ExtremeWaveEvent,
    fetch_ocean_conditions,
    detect_extreme_waves,
    MARINE_URL,
)


def _mock_marine_response(wave_height: float, sst: float = 22.0):
    """Helper to generate a mock marine API response."""
    return {
        "daily": {
            "wave_height_max": [wave_height],
            "sea_surface_temperature_max": [sst],
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
                json=_mock_marine_response(5.0, 22.0),
                status=200,
            )
        readings = fetch_ocean_conditions()
        assert len(readings) == 16
        assert all(isinstance(r, OceanReading) for r in readings)
        assert readings[0].wave_height_max_m == 5.0
        assert readings[0].sst_c == 22.0

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
            json={"daily": {"wave_height_max": [None], "sea_surface_temperature_max": [22.0]}},
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
    def test_detects_extreme_waves(self):
        readings = [
            OceanReading("Gulf of Mexico", "Atlantic", 28.5, -88.0, 12.0, 25.0, "2026-04-08", "ocean_gom_1"),
            OceanReading("North Sea", "Atlantic", 58.0, -5.0, 5.0, 10.0, "2026-04-08", "ocean_ns_1"),
        ]
        events = detect_extreme_waves(readings)
        assert len(events) == 1
        assert isinstance(events[0], ExtremeWaveEvent)
        assert events[0].location == "Gulf of Mexico"
        assert events[0].wave_height_m == 12.0

    def test_custom_threshold(self):
        readings = [
            OceanReading("Test", "Atlantic", 0, 0, 6.0, None, "2026-04-08", "t1"),
        ]
        assert len(detect_extreme_waves(readings, threshold_m=5.0)) == 1
        assert len(detect_extreme_waves(readings, threshold_m=7.0)) == 0

    def test_empty_readings(self):
        assert detect_extreme_waves([]) == []
