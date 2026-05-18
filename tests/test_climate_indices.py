"""Tests for NOAA climate-mode index sources."""

from copy import deepcopy
from datetime import date
from unittest.mock import MagicMock

import responses

import src.orchestrator.sources.climate_indices as climate_source
from src.data.climate_indices import (
    AO_URL,
    NAO_URL,
    PDO_URL,
    INDEX_NAMES,
    OscillationReading,
    detect_extreme_excursion,
    detect_nao_ao_alignment,
    detect_phase_transition,
    fetch_ao,
    fetch_nao,
    fetch_pdo,
)
from src.state import DEFAULT_STATE


NAO_SAMPLE = """1950    1    0.9200
1950    2    0.4000
2026    3   -0.3600
2026    4   -0.7300
"""

PDO_SAMPLE = """1854 2026
2025     0.050    -0.090     0.138     0.131    -0.064     0.005    -0.201    -0.849    -0.727    -1.597    -1.301    -1.582
2026    -0.501    -0.687    -0.314     0.000    -9.990    -9.990    -9.990    -9.990    -9.990    -9.990    -9.990    -9.990
"""


def _reading(index_name: str, year: int, month: int, value: float) -> OscillationReading:
    phase = "Positive" if value > 0 else "Negative" if value < 0 else "Neutral"
    return OscillationReading(
        index_name=index_name,
        full_name=INDEX_NAMES[index_name],
        year=year,
        month=month,
        value=value,
        phase=phase,
        event_id=f"{index_name.lower()}_{year}_{month:02d}",
    )


def _series(index_name: str, values: list[float]) -> list[OscillationReading]:
    readings = []
    for offset, value in enumerate(values):
        year = 2000 + offset // 12
        month = offset % 12 + 1
        readings.append(_reading(index_name, year, month, value))
    return readings


class TestFetchClimateIndices:
    @responses.activate
    def test_fetch_nao_parses_three_column_rows(self):
        responses.add(responses.GET, NAO_URL, body=NAO_SAMPLE, status=200)

        readings = fetch_nao(max_age_days=100000)

        assert len(readings) == 4
        assert readings[-1].index_name == "NAO"
        assert readings[-1].full_name == "North Atlantic Oscillation"
        assert readings[-1].phase == "Negative"
        assert readings[-1].event_id == "climate_index_nao_2026_04"

    @responses.activate
    def test_fetch_ao_returns_empty_on_non_strict_error(self):
        responses.add(responses.GET, AO_URL, status=404)

        assert fetch_ao(max_age_days=100000) == []

    @responses.activate
    def test_fetch_pdo_parses_wide_monthly_rows_and_skips_missing(self):
        responses.add(responses.GET, PDO_URL, body=PDO_SAMPLE, status=200)

        readings = fetch_pdo(max_age_days=100000)

        assert readings[0].date == "2025-01-01"
        assert readings[-1].date == "2026-04-01"
        assert all(reading.index_name == "PDO" for reading in readings)
        assert len(readings) == 16


class TestOscillationTransition:
    def test_detects_cross_zero_after_three_months_in_prior_phase(self):
        readings = [
            _reading("NAO", 2026, 1, -0.8),
            _reading("NAO", 2026, 2, -0.6),
            _reading("NAO", 2026, 3, -0.2),
            _reading("NAO", 2026, 4, 0.4),
        ]

        event = detect_phase_transition(readings)

        assert event is not None
        assert event.from_phase == "Negative"
        assert event.to_phase == "Positive"
        assert event.previous_duration_months == 3
        assert event.event_id == "oscillation_transition_nao_positive_2026_04"

    def test_ignores_short_prior_phase(self):
        readings = [
            _reading("AO", 2026, 1, -0.8),
            _reading("AO", 2026, 2, -0.6),
            _reading("AO", 2026, 3, 0.4),
        ]

        assert detect_phase_transition(readings) is None

    def test_ignores_current_neutral_phase(self):
        readings = [
            _reading("PDO", 2026, 1, -0.8),
            _reading("PDO", 2026, 2, -0.6),
            _reading("PDO", 2026, 3, -0.4),
            _reading("PDO", 2026, 4, 0.0),
        ]

        assert detect_phase_transition(readings) is None


class TestOscillationExtreme:
    def test_detects_two_sigma_latest_excursion(self):
        readings = _series("PDO", [0.4, -0.4] * 12 + [2.4])

        event = detect_extreme_excursion(readings)

        assert event is not None
        assert event.index_name == "PDO"
        assert event.sigma_excursion >= 2.0
        assert event.event_id == "oscillation_extreme_pdo_2002_01"

    def test_comparison_year_uses_latest_prior_at_least_as_extreme(self):
        values = [0.4, -0.4] * 12 + [2.7] + [0.1] * 11 + [2.5]
        readings = _series("NAO", values)

        event = detect_extreme_excursion(readings)

        assert event is not None
        assert event.comparison_year == 2002
        assert event.comparison_month == 1

    def test_no_extreme_below_two_sigma(self):
        readings = _series("AO", [0.4, -0.4] * 12 + [0.6])

        assert detect_extreme_excursion(readings) is None


class TestNaoAoAlignment:
    def test_detects_simultaneous_extreme_negative_alignment(self):
        nao = _series("NAO", [0.5, -0.5] * 12 + [-2.5])
        ao = _series("AO", [0.4, -0.4] * 12 + [-2.2])

        event = detect_nao_ao_alignment(nao, ao)

        assert event is not None
        assert event.nao_sigma_excursion >= 2.0
        assert event.ao_sigma_excursion >= 2.0
        assert event.event_id == "oscillation_alignment_nao_ao_2002_01"

    def test_alignment_requires_same_month(self):
        nao = _series("NAO", [0.5, -0.5] * 12 + [-2.5])
        ao = _series("AO", [0.4, -0.4] * 12 + [-2.2, -2.3])

        assert detect_nao_ao_alignment(nao, ao) is None


class TestClimateIndexRunner:
    def test_run_climate_indices_fetches_after_first_of_month(self, monkeypatch):
        class MidMonthDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 5, 17)

        fetch_nao = MagicMock(return_value=[])
        fetch_ao = MagicMock(return_value=[])
        fetch_pdo = MagicMock(return_value=[])
        monkeypatch.setattr(climate_source, "date", MidMonthDate)
        monkeypatch.setattr(climate_source.climate_indices, "fetch_nao", fetch_nao)
        monkeypatch.setattr(climate_source.climate_indices, "fetch_ao", fetch_ao)
        monkeypatch.setattr(climate_source.climate_indices, "fetch_pdo", fetch_pdo)
        monkeypatch.setattr(climate_source.climate_indices, "detect_phase_transition", lambda readings: None)
        monkeypatch.setattr(climate_source.climate_indices, "detect_extreme_excursion", lambda readings: None)
        monkeypatch.setattr(
            climate_source.climate_indices,
            "detect_nao_ao_alignment",
            lambda nao_readings, ao_readings: None,
        )
        bot_state = deepcopy(DEFAULT_STATE)
        current_run = {"id": "run_1", "sources": []}

        drafted = climate_source.run_climate_indices(bot_state, current_run)

        assert drafted == 0
        fetch_nao.assert_called_once()
        fetch_ao.assert_called_once()
        fetch_pdo.assert_called_once()
        statuses = {item["source"]: item["status"] for item in current_run["sources"]}
        assert statuses == {
            "nao": "success",
            "ao": "success",
            "pdo": "success",
            "nao_ao_alignment": "success",
        }
