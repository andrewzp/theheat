"""Tests for USGS river gauge / flood stage data."""

from unittest.mock import patch

import pytest
import responses

from src.data.source_status import SourceFetchError
from src.data.river_gauges import (
    RiverReading,
    FloodEvent,
    fetch_river_levels,
    detect_floods,
    _fetch_flood_stages,
    USGS_URL,
    FLOOD_URL,
)

TEST_STATIONS = [
    ("07010000", "Mississippi River", "St. Louis, MO"),
    ("07374000", "Mississippi River", "Baton Rouge, LA"),
]

SAMPLE_USGS_RESPONSE = {
    "value": {
        "timeSeries": [
            {
                "sourceInfo": {
                    "siteCode": [{"value": "07010000"}],
                },
                "values": [
                    {
                        "value": [
                            {"value": "35.5", "dateTime": "2026-04-08T12:00:00"},
                        ]
                    }
                ],
            },
            {
                "sourceInfo": {
                    "siteCode": [{"value": "07374000"}],
                },
                "values": [
                    {
                        "value": [
                            {"value": "22.1", "dateTime": "2026-04-08T12:00:00"},
                        ]
                    }
                ],
            },
        ]
    }
}

def _nwps_gauge(stage: float | None) -> dict:
    minor = {"stage": stage} if stage is not None else None
    return {"flood": {"categories": {"minor": minor}}}


def _add_nwps_stage(site_id: str, stage: float, *, status: int = 200) -> None:
    responses.add(
        responses.GET,
        FLOOD_URL.format(site_id=site_id),
        json=_nwps_gauge(stage),
        status=status,
    )


class TestFetchFloodStages:
    @responses.activate
    def test_parses_flood_stages(self):
        _add_nwps_stage("07010000", 30.0)
        _add_nwps_stage("07374000", 35.0)
        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS):
            stages = _fetch_flood_stages()
        assert stages["07010000"] == 30.0
        assert stages["07374000"] == 35.0

    @responses.activate
    def test_api_error_returns_empty(self):
        for _ in range(3):
            responses.add(
                responses.GET,
                FLOOD_URL.format(site_id="07010000"),
                status=500,
            )
        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS[:1]):
            assert _fetch_flood_stages() == {}

    @responses.activate
    def test_strict_schema_drift_raises(self):
        responses.add(
            responses.GET,
            FLOOD_URL.format(site_id="07010000"),
            json={"status": {}},
            status=200,
        )
        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS[:1]):
            with pytest.raises(SourceFetchError, match="schema drift"):
                _fetch_flood_stages(strict=True)


class TestFetchRiverLevels:
    @responses.activate
    def test_happy_path(self):
        responses.add(responses.GET, USGS_URL, json=SAMPLE_USGS_RESPONSE, status=200)
        _add_nwps_stage("07010000", 30.0)
        _add_nwps_stage("07374000", 35.0)
        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS):
            readings = fetch_river_levels()
        assert len(readings) == 2
        assert all(isinstance(r, RiverReading) for r in readings)
        # St. Louis at 35.5ft, flood stage 30.0 -> above flood
        stl = [r for r in readings if "St. Louis" in r.location][0]
        assert stl.gauge_height_ft == 35.5
        assert stl.flood_stage_ft == 30.0
        assert stl.above_flood is True
        # Baton Rouge at 22.1ft, flood stage 35.0 -> not above flood
        br = [r for r in readings if "Baton Rouge" in r.location][0]
        assert br.above_flood is False

    @responses.activate
    @patch("src.data._http.time.sleep")
    def test_api_error_returns_empty(self, _sleep):
        # The USGS call is routed through fetch_with_retry, so a persistent 5xx
        # is retried (3 attempts) before fetch_river_levels gives up.
        for _ in range(3):
            responses.add(responses.GET, USGS_URL, status=500)
        assert fetch_river_levels() == []
        usgs_calls = [c for c in responses.calls if c.request.url.startswith(USGS_URL)]
        assert len(usgs_calls) == 3


class TestDetectFloods:
    def test_detects_floods(self):
        readings = [
            RiverReading("Mississippi", "St. Louis, MO", "07010000", 35.5, 30.0, True, "2026-04-08", "r1"),
            RiverReading("Mississippi", "Baton Rouge, LA", "07374000", 22.1, 35.0, False, "2026-04-08", "r2"),
        ]
        events = detect_floods(readings)
        assert len(events) == 1
        assert isinstance(events[0], FloodEvent)
        assert events[0].river == "Mississippi"
        assert events[0].above_by_ft == 5.5

    def test_no_floods(self):
        readings = [
            RiverReading("Test", "Test, TX", "123", 10.0, 30.0, False, "2026-04-08", "r1"),
        ]
        assert detect_floods(readings) == []

    def test_empty_readings(self):
        assert detect_floods([]) == []

    def test_event_id_format(self):
        readings = [
            RiverReading("Mississippi", "St. Louis, MO", "07010000", 35.5, 30.0, True, "2026-04-08", "r1"),
        ]
        events = detect_floods(readings)
        assert events[0].event_id == "flood_07010000_2026-04-08"
