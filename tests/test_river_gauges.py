"""Tests for USGS river gauge / flood stage data."""

from datetime import date, timedelta
from unittest.mock import patch

import pytest
import responses

from src.data.source_status import SourceFetchError
from src.data.river_gauges import (
    RiverReading,
    FloodEvent,
    _OPEN_METEO_FLOOD_COORDS,
    OPEN_METEO_FLOOD_URL,
    fetch_river_levels,
    detect_floods,
    _fetch_flood_stages,
    _fetch_open_meteo_flood,
    USGS_URL,
    FLOOD_URL,
)
from src.two_bot.intern import build_river_flood_bundle
from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_SYSTEM_PROMPT

TEST_STATIONS = [
    ("07010000", "Mississippi River", "St. Louis, MO"),
    ("07374000", "Mississippi River", "Baton Rouge, LA"),
]

FRESH_DATETIME = f"{(date.today() - timedelta(days=1)).isoformat()}T12:00:00Z"

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
                            {"value": "35.5", "dateTime": FRESH_DATETIME},
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
                            {"value": "22.1", "dateTime": FRESH_DATETIME},
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

    @responses.activate
    def test_riverflood_primary_healthy_skips_witness(self):
        responses.add(responses.GET, USGS_URL, json=SAMPLE_USGS_RESPONSE, status=200)
        _add_nwps_stage("07010000", 30.0)
        _add_nwps_stage("07374000", 35.0)
        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS), \
             patch("src.data.river_gauges._fetch_open_meteo_flood") as witness_mock:
            readings = fetch_river_levels(strict=True)

        witness_mock.assert_not_called()
        assert readings and all(r.source_leg is None for r in readings)


class TestOpenMeteoFloodWitness:
    @responses.activate
    @patch("src.data._http.time.sleep")
    def test_riverflood_falls_back_on_primary_fetch_error(self, _sleep):
        for _ in range(3):
            responses.add(responses.GET, USGS_URL, status=500)
        responses.add(
            responses.GET,
            OPEN_METEO_FLOOD_URL,
            json={
                "daily": {
                    "time": ["2026-06-15"],
                    "river_discharge": [1200.0],
                    "river_discharge_mean": [1100.0],
                    "river_discharge_p75": [1000.0],
                }
            },
            status=200,
        )

        with patch("src.data.river_gauges.MAJOR_STATIONS", TEST_STATIONS[:1]):
            readings = fetch_river_levels()

        assert len(readings) == 1
        assert readings[0].source_leg == "open_meteo_flood"
        assert readings[0].gauge_height_ft is None
        assert readings[0].discharge_m3s == 1200.0

    def test_riverflood_only_known_coords(self, monkeypatch):
        calls = []

        def fake_station(site_id, river, location, coords):
            calls.append((site_id, river, location, coords))
            return None

        monkeypatch.setattr(
            "src.data.river_gauges._fetch_open_meteo_flood_station",
            fake_station,
        )
        stations = [
            ("07010000", "Mississippi River", "St. Louis, MO"),
            ("99999999", "Imaginary River", "Nowhere, ZZ"),
        ]
        with patch("src.data.river_gauges.MAJOR_STATIONS", stations):
            assert _fetch_open_meteo_flood() == []

        assert calls == [
            (
                "07010000",
                "Mississippi River",
                "St. Louis, MO",
                _OPEN_METEO_FLOOD_COORDS["07010000"],
            )
        ]

    def test_riverflood_witness_omits_gauge_ft_facts(self):
        event = FloodEvent(
            river="Mississippi River",
            location="St. Louis, MO",
            gauge_height_ft=None,
            flood_stage_ft=None,
            above_by_ft=None,
            date="2026-06-15",
            event_id="flood_model_07010000_2026-06-15",
            source_leg="open_meteo_flood",
            discharge_m3s=1800.0,
            discharge_threshold_m3s=1200.0,
            discharge_ratio=1.5,
        )

        bundle = build_river_flood_bundle(event)
        labels = {fact["label"] for fact in bundle.current_facts}

        assert "gauge_height_ft" not in labels
        assert "flood_stage_ft" not in labels
        assert "above_by_ft" not in labels
        assert bundle.headline_metric == {
            "label": "modeled_discharge_m3s",
            "value": 1800.0,
            "unit": "m3/s",
        }
        assert {"label": "modeled_discharge_m3s", "value": 1800.0, "unit": "m3/s"} in bundle.current_facts
        assert {"label": "model_threshold_m3s", "value": 1200.0, "unit": "m3/s"} in bundle.current_facts

    def test_riverflood_witness_model_fallback_grade(self):
        reading = RiverReading(
            river="Mississippi River",
            location="St. Louis, MO",
            site_id="07010000",
            gauge_height_ft=None,
            flood_stage_ft=None,
            above_flood=True,
            date="2026-06-15",
            event_id="river_model_07010000_2026-06-15",
            source_leg="open_meteo_flood",
            discharge_m3s=1800.0,
            discharge_threshold_m3s=1200.0,
            discharge_ratio=1.5,
        )

        events = detect_floods([reading])
        assert len(events) == 1
        assert events[0].source_leg == "open_meteo_flood"

        bundle = build_river_flood_bundle(events[0])
        assert {"label": "evidence_grade", "value": "model_fallback"} in bundle.current_facts

    def test_riverflood_model_fallback_claiming_gauge_reading_killed(self):
        event = FloodEvent(
            river="Mississippi River",
            location="St. Louis, MO",
            gauge_height_ft=None,
            flood_stage_ft=None,
            above_by_ft=None,
            date="2026-06-15",
            event_id="flood_model_07010000_2026-06-15",
            source_leg="open_meteo_flood",
            discharge_m3s=1800.0,
            discharge_threshold_m3s=1200.0,
            discharge_ratio=1.5,
        )

        bundle = build_river_flood_bundle(event)
        assert {"label": "evidence_grade", "value": "model_fallback"} in bundle.current_facts
        assert "model_fallback" in FACT_CHECK_SYSTEM_PROMPT
        assert "gauge" in FACT_CHECK_SYSTEM_PROMPT.lower()


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
