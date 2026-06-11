"""Tests for NOAA CO-OPS water level data."""

from unittest.mock import patch

import pytest
import requests

from src.data.source_status import SourceFetchError
from src.data.water_levels import (
    WaterLevelReading,
    StormSurgeEvent,
    detect_storm_surge,
    fetch_water_levels,
    SURGE_THRESHOLD_M,
    MAJOR_SURGE_THRESHOLD_M,
)


class TestDetectStormSurge:
    def test_detects_surge_above_threshold(self):
        readings = [
            WaterLevelReading("The Battery, NY", "NY", "8518750", 1.8, 1.1, 0.7, "2026-04-08", "w1"),
            WaterLevelReading("Boston, MA", "MA", "8443970", 1.2, 1.0, 0.2, "2026-04-08", "w2"),
        ]
        events = detect_storm_surge(readings)
        assert len(events) == 1
        assert isinstance(events[0], StormSurgeEvent)
        assert events[0].station_name == "The Battery, NY"
        assert events[0].anomaly_m == 0.7

    def test_major_surge_event_id_prefix(self):
        readings = [
            WaterLevelReading("Galveston, TX", "TX", "8771450", 2.5, 1.0, 1.5, "2026-04-08", "w1"),
        ]
        events = detect_storm_surge(readings)
        assert len(events) == 1
        assert events[0].event_id.startswith("surge_major_")

    def test_notable_surge_event_id_prefix(self):
        readings = [
            WaterLevelReading("Test", "CA", "123", 1.5, 1.0, 0.6, "2026-04-08", "w1"),
        ]
        events = detect_storm_surge(readings)
        assert events[0].event_id.startswith("surge_notable_")

    def test_no_surge_below_threshold(self):
        readings = [
            WaterLevelReading("Test", "CA", "123", 1.2, 1.1, 0.1, "2026-04-08", "w1"),
        ]
        assert detect_storm_surge(readings) == []

    def test_custom_threshold(self):
        readings = [
            WaterLevelReading("Test", "CA", "123", 1.3, 1.0, 0.3, "2026-04-08", "w1"),
        ]
        assert len(detect_storm_surge(readings, threshold_m=0.2)) == 1
        assert len(detect_storm_surge(readings, threshold_m=0.5)) == 0

    def test_empty_readings(self):
        assert detect_storm_surge([]) == []


def test_water_levels_fetch_failure_raises_clean():
    with patch(
        "src.data.water_levels.fetch_with_retry",
        side_effect=requests.RequestException("network down"),
    ):
        assert fetch_water_levels(strict=False) == []
        with pytest.raises(SourceFetchError, match="Water levels fetch failed"):
            fetch_water_levels(strict=True)
