"""Tests for latitude-banded absolute temperature extremes."""

from __future__ import annotations

from datetime import date

import pytest
import responses

import src.data.open_meteo as open_meteo_module
from src.data.ghcn import _detect_signals_for_station, _has_signal
from src.data.ghcn_format import DailyObs, StationThresholds
from src.data.open_meteo import (
    AbsoluteExtremeEvent,
    ExtremeSignalBundle,
    LATITUDE_BANDS,
    check_extreme_signals_for_cities,
    detect_absolute_extreme,
    detect_extreme_signals,
)
from src.editorial.approval import recommend_approval_policy
from src.editorial.scoring import score_absolute_extreme
from src.two_bot.intern import build_absolute_extreme_bundle


class FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return date(2026, 7, 15)


def _archive_daily(today: date) -> dict:
    dates = [
        f"{today.year - 1}-{today.month:02d}-01",
        f"{today.year - 1}-{today.month:02d}-{today.day:02d}",
        f"{today.year - 1}-01-01",
    ]
    return {
        "time": dates,
        "temperature_2m_max": [28.0, 29.0, 35.0],
        "temperature_2m_min": [14.0, 13.0, 10.0],
    }


@pytest.mark.parametrize(
    ("lat", "expected_band"),
    [
        (70.0, "Arctic"),
        (60.0, "Sub-Arctic"),
        (45.0, "N Mid-latitudes"),
        (30.0, "N Sub-tropical"),
        (0.0, "Tropics"),
        (-30.0, "S Sub-tropical"),
        (-50.0, "S Mid-latitudes"),
    ],
)
def test_latitude_band_classification(lat: float, expected_band: str) -> None:
    band = next((b for b in LATITUDE_BANDS if b[0] <= lat < b[1]), None)
    assert band is not None
    assert band[4] == expected_band


def test_latitude_band_table_covers_integer_lats_once() -> None:
    for lat in range(-90, 90):
        matches = [b for b in LATITUDE_BANDS if b[0] <= lat < b[1]]
        assert len(matches) == 1, f"lat={lat} matched {len(matches)} bands"


def test_southern_subtropics_are_not_collapsed_to_northern_thresholds() -> None:
    n_sub = next(b for b in LATITUDE_BANDS if b[4] == "N Sub-tropical")
    s_sub = next(b for b in LATITUDE_BANDS if b[4] == "S Sub-tropical")
    assert n_sub[2] == 47.0
    assert s_sub[2] == 48.0

    event = detect_absolute_extreme(
        -30.0,
        133.0,
        47.9,
        None,
        "Alice Springs",
        "Australia",
        signal_date=date(2026, 1, 15),
    )
    assert event is None


def test_detect_absolute_extreme_hot_and_cold_event_ids() -> None:
    hot = detect_absolute_extreme(
        70.0,
        25.0,
        31.5,
        None,
        "Tromso",
        "Norway",
        signal_date=date(2026, 7, 15),
    )
    assert hot is not None
    assert hot.band_label == "Arctic"
    assert hot.threshold_c == 30.0
    assert hot.kind == "hot"
    assert hot.event_id == "absextreme_Tromso_2026-07-15"

    cold = detect_absolute_extreme(
        72.0,
        129.0,
        None,
        -51.0,
        "Yakutsk",
        "Russia",
        signal_date=date(2026, 1, 10),
    )
    assert cold is not None
    assert cold.kind == "cold"
    assert cold.band_label == "Arctic"
    assert cold.event_id == "absextreme_cold_Yakutsk_2026-01-10"


def test_detect_absolute_extreme_does_not_fire_below_thresholds() -> None:
    assert detect_absolute_extreme(70.0, 25.0, 29.9, None, "Tromso", "Norway") is None
    assert detect_absolute_extreme(5.0, 32.0, 49.9, None, "Khartoum", "Sudan") is None


@responses.activate
def test_detect_extreme_signals_populates_absolute_extreme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    today = FixedDate.today()
    responses.add(
        responses.GET,
        "https://api.open-meteo.com/v1/forecast",
        json={"daily": {"temperature_2m_max": [31.5], "temperature_2m_min": [16.0]}},
    )
    responses.add(
        responses.GET,
        "https://archive-api.open-meteo.com/v1/archive",
        json={"daily": _archive_daily(today)},
    )

    bundle = detect_extreme_signals(70.0, 25.0, "Tromso", "Norway", archive_years=1)

    assert bundle is not None
    assert bundle.absolute_extreme is not None
    assert bundle.absolute_extreme.event_id == "absextreme_Tromso_2026-07-15"
    assert bundle.absolute_extreme.data_source == "forecast"


def test_absolute_extreme_only_bundle_survives_open_meteo_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ae = AbsoluteExtremeEvent(
        city="Alice Springs",
        country="Australia",
        today_temp_c=49.0,
        band_label="S Sub-tropical",
        threshold_c=48.0,
        kind="hot",
        lat=-23.7,
        lon=133.9,
        event_id="absextreme_Alice_Springs_2026-01-15",
    )
    only_absolute = ExtremeSignalBundle(
        city="Alice Springs",
        country="Australia",
        today_max_c=49.0,
        absolute_extreme=ae,
    )
    monkeypatch.setattr(open_meteo_module, "detect_extreme_signals", lambda **kwargs: only_absolute)

    bundles, country_records = check_extreme_signals_for_cities(
        [{"city": "Alice Springs", "country": "Australia", "lat": "-23.7", "lon": "133.9"}],
        max_checks=1,
    )

    assert bundles == [only_absolute]
    assert country_records == []


def test_score_absolute_extreme_clears_threshold() -> None:
    score = score_absolute_extreme(30.0, 70.0, "Arctic", 30.0, kind="hot")
    assert score.category == "absolute_extreme"
    assert score.threshold == 78
    assert score.passes


def test_build_absolute_extreme_bundle_surfaces_forecast_context() -> None:
    event = AbsoluteExtremeEvent(
        city="Tromso",
        country="Norway",
        today_temp_c=31.5,
        band_label="Arctic",
        threshold_c=30.0,
        kind="hot",
        lat=70.0,
        lon=25.0,
        event_id="absextreme_Tromso_2026-07-15",
        signal_date=date(2026, 7, 15),
        data_source="forecast",
    )

    bundle = build_absolute_extreme_bundle(event)

    assert bundle.signal_kind == "absolute_extreme_hot"
    assert bundle.headline_metric["value"] == 31.5
    assert bundle.headline_metric["is_forecast"] is True
    assert bundle.historical_context["scope"] == "latitude_band_absolute"
    assert any(f["label"] == "band_label" and f["value"] == "Arctic" for f in bundle.current_facts)


def test_absolute_extreme_requires_manual_approval() -> None:
    policy = recommend_approval_policy(
        "absolute_extreme",
        signal_total=86,
        candidate_score={"total": 84},
    )
    assert policy.mode == "manual_only"
    assert policy.can_auto_approve is False


def test_ghcn_observed_path_populates_absolute_extreme() -> None:
    thresholds = StationThresholds(station_id="POLAR0000000")
    thresholds.archive_years = 60
    thresholds.all_time_max_c = 40.0
    thresholds.all_time_max_year = 1985
    station = {
        "station_id": "POLAR0000000",
        "name": "POLAR TEST STATION",
        "country_code": "PL",
        "country_name": "Poland Test",
        "state": "",
        "lat": 70.0,
        "lon": 25.0,
        "archive_years": 60,
    }
    obs = DailyObs(
        station_id="POLAR0000000",
        obs_date=date(2026, 7, 15),
        element="TMAX",
        value_c=31.0,
    )

    bundle = _detect_signals_for_station(station, obs, thresholds)

    assert bundle is not None
    assert bundle.absolute_extreme is not None
    assert bundle.absolute_extreme.data_source == "ghcn"
    assert bundle.absolute_extreme.signal_date == date(2026, 7, 15)
    assert _has_signal(bundle)
