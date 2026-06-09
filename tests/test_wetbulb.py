"""Tests for Open-Meteo wet-bulb extreme signals."""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
import responses

import src.data.open_meteo as open_meteo_module
from src.data.open_meteo import (
    ExtremeSignalBundle,
    WetBulbEvent,
    check_extreme_signals_for_cities,
    detect_extreme_signals,
)
from src.editorial.approval import recommend_approval_policy
from src.editorial.scoring import score_wet_bulb_extreme
from src.editorial.thresholds import get_threshold


class FixedDate(date):
    @classmethod
    def today(cls) -> date:
        return date(2026, 7, 12)


def _forecast_daily(
    tw_value: float | None,
    *,
    include_tw_key: bool = True,
) -> dict:
    daily = {
        "time": [FixedDate.today().isoformat()],
        "temperature_2m_max": [38.0],
        "temperature_2m_min": [28.0],
    }
    if include_tw_key:
        daily["wet_bulb_temperature_2m_max"] = [tw_value]
    return daily


def _archive_daily(
    *,
    tw_values: list[float | None] | None = None,
    include_tw_key: bool = True,
) -> dict:
    daily = {
        "time": ["2023-07-12", "2024-07-12", "2025-07-12"],
        "temperature_2m_max": [45.0, 44.0, 43.0],
        "temperature_2m_min": [24.0, 25.0, 26.0],
    }
    if include_tw_key:
        daily["wet_bulb_temperature_2m_max"] = (
            [34.8, 33.0, None] if tw_values is None else tw_values
        )
    return daily


def _mock_detect_responses(
    tw_value: float | None,
    *,
    archive_tw_values: list[float | None] | None = None,
    include_forecast_tw_key: bool = True,
    include_archive_tw_key: bool = True,
) -> None:
    responses.add(
        responses.GET,
        "https://api.open-meteo.com/v1/forecast",
        json={"daily": _forecast_daily(tw_value, include_tw_key=include_forecast_tw_key)},
    )
    responses.add(
        responses.GET,
        "https://archive-api.open-meteo.com/v1/archive",
        json={
            "daily": _archive_daily(
                tw_values=archive_tw_values,
                include_tw_key=include_archive_tw_key,
            )
        },
    )


@responses.activate
def test_tier3_wet_bulb_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(35.5)

    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    assert bundle is not None
    assert bundle.wet_bulb_extreme is not None
    assert bundle.wet_bulb_extreme.tier == 3
    assert bundle.wet_bulb_extreme.tier_label == "tier_3"
    assert bundle.wet_bulb_extreme.daily_max_tw_c == 35.5
    assert bundle.wet_bulb_extreme.archive_max_tw_c == 34.8
    assert bundle.wet_bulb_extreme.archive_max_year == 2023
    assert bundle.wet_bulb_extreme.event_id == "wetbulb_Jacobabad_2026-07-12_tier3"


@responses.activate
def test_forecast_and_archive_requests_include_wet_bulb_daily_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(35.5)

    detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    forecast_daily = parse_qs(urlparse(responses.calls[0].request.url).query)["daily"][0]
    archive_daily = parse_qs(urlparse(responses.calls[1].request.url).query)["daily"][0]
    assert forecast_daily == "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max"
    assert archive_daily == "temperature_2m_max,temperature_2m_min,wet_bulb_temperature_2m_max"


@responses.activate
def test_tier2_wet_bulb_fires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(33.2)

    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    assert bundle is not None
    assert bundle.wet_bulb_extreme is not None
    assert bundle.wet_bulb_extreme.tier == 2
    assert bundle.wet_bulb_extreme.tier_threshold_c == 33.0


@pytest.mark.parametrize("tw_value", [31.0, 32.9, None])
@responses.activate
def test_tier1_and_below_floor_are_not_emitted(
    monkeypatch: pytest.MonkeyPatch,
    tw_value: float | None,
) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(tw_value)

    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    assert bundle is not None
    assert bundle.wet_bulb_extreme is None


@responses.activate
def test_missing_wet_bulb_key_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(35.5, include_forecast_tw_key=False)

    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    assert bundle is not None
    assert bundle.wet_bulb_extreme is None


@responses.activate
def test_event_still_fires_when_archive_wet_bulb_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(open_meteo_module, "date", FixedDate)
    _mock_detect_responses(35.5, include_archive_tw_key=False)

    bundle = detect_extreme_signals(24.0, 68.0, "Jacobabad", "Pakistan", archive_years=3)

    assert bundle is not None
    assert bundle.wet_bulb_extreme is not None
    assert bundle.wet_bulb_extreme.archive_max_tw_c is None
    assert bundle.wet_bulb_extreme.archive_max_year is None


def test_wet_bulb_only_bundle_survives_open_meteo_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = WetBulbEvent(
        city="Jacobabad",
        country="Pakistan",
        daily_max_tw_c=35.5,
        tier=3,
        tier_label="tier_3",
        tier_threshold_c=35.0,
        event_id="wetbulb_Jacobabad_2026-07-12_tier3",
    )
    only_wet_bulb = ExtremeSignalBundle(
        city="Jacobabad",
        country="Pakistan",
        wet_bulb_extreme=event,
    )
    monkeypatch.setattr(open_meteo_module, "detect_extreme_signals", lambda **kwargs: only_wet_bulb)

    bundles, country_records = check_extreme_signals_for_cities(
        [{"city": "Jacobabad", "country": "Pakistan", "lat": "24.0", "lon": "68.0"}],
        max_checks=1,
    )

    assert bundles == [only_wet_bulb]
    assert country_records == []


def test_wet_bulb_scores_pass_thresholds() -> None:
    tier3 = score_wet_bulb_extreme(35.0, tier=3)
    tier2 = score_wet_bulb_extreme(33.0, tier=2)

    assert tier3.category == "wet_bulb_extreme"
    assert tier3.threshold == 78
    assert tier3.passes
    assert tier2.passes
    assert tier3.total > tier2.total


def test_wet_bulb_tier1_score_stays_below_gate() -> None:
    score = score_wet_bulb_extreme(31.0, tier=1)

    assert not score.passes
    assert score.sensitivity == 10


def test_wet_bulb_threshold_and_approval_policy() -> None:
    assert get_threshold("wet_bulb_extreme") == 78

    policy = recommend_approval_policy(
        "wet_bulb_extreme",
        signal_total=88,
        candidate_score={"total": 84},
    )
    assert policy.mode == "manual_only"
    assert policy.can_auto_approve is False
