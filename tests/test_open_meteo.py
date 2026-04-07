"""Tests for Open-Meteo data fetching and anomaly calculation."""

import responses
from src.data.open_meteo import (
    CityTemp,
    compute_anomalies,
    rank_hot10,
    fetch_city_temp,
)


class TestComputeAnomalies:
    def test_positive_anomaly(self):
        temps = [CityTemp("Phoenix", "US", 33.45, -112.07, 45.0)]
        normals = {"Phoenix": {4: 30.0}}  # April normal
        result = compute_anomalies(temps, normals)
        assert len(result) == 1
        assert result[0].anomaly_c == 15.0

    def test_negative_anomaly(self):
        temps = [CityTemp("Phoenix", "US", 33.45, -112.07, 25.0)]
        normals = {"Phoenix": {4: 30.0}}
        result = compute_anomalies(temps, normals)
        assert len(result) == 1
        assert result[0].anomaly_c == -5.0

    def test_missing_normal_excluded(self):
        temps = [CityTemp("Unknown City", "XX", 0.0, 0.0, 30.0)]
        normals = {}
        result = compute_anomalies(temps, normals)
        assert len(result) == 0

    def test_extreme_anomaly_filtered(self):
        temps = [CityTemp("Broken", "XX", 0.0, 0.0, 80.0)]
        normals = {"Broken": {4: 20.0}}  # 60C anomaly = data error
        result = compute_anomalies(temps, normals, max_anomaly_c=30.0)
        assert len(result) == 0

    def test_boundary_anomaly_passes(self):
        temps = [CityTemp("Hot", "XX", 0.0, 0.0, 50.0)]
        normals = {"Hot": {4: 20.0}}  # 30C anomaly = exactly at boundary
        result = compute_anomalies(temps, normals, max_anomaly_c=30.0)
        assert len(result) == 1


class TestRankHot10:
    def test_returns_top_10(self):
        temps = [
            CityTemp(f"City{i}", "XX", 0.0, 0.0, 0.0, 0.0, anomaly_c=float(i))
            for i in range(15)
        ]
        result = rank_hot10(temps)
        assert len(result) == 10
        assert result[0].anomaly_c == 14.0  # Highest anomaly first

    def test_empty_input(self):
        assert rank_hot10([]) == []

    def test_fewer_than_10(self):
        temps = [CityTemp("A", "XX", 0, 0, 0, 0, anomaly_c=5.0)]
        result = rank_hot10(temps)
        assert len(result) == 1

    def test_tiebreaker_is_deterministic(self):
        temps = [
            CityTemp("A", "XX", 0, 0, 0, 0, anomaly_c=10.0),
            CityTemp("B", "XX", 0, 0, 0, 0, anomaly_c=10.0),
        ]
        result = rank_hot10(temps)
        assert len(result) == 2


class TestFetchCityTemp:
    @responses.activate
    def test_successful_fetch(self):
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={
                "daily": {
                    "time": ["2026-04-07"],
                    "temperature_2m_max": [42.5],
                }
            },
            status=200,
        )
        result = fetch_city_temp(33.45, -112.07)
        assert result == 42.5

    @responses.activate
    def test_api_failure_returns_none(self):
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            status=500,
        )
        result = fetch_city_temp(33.45, -112.07)
        assert result is None

    @responses.activate
    def test_null_temp_returns_none(self):
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json={"daily": {"temperature_2m_max": [None]}},
            status=200,
        )
        result = fetch_city_temp(33.45, -112.07)
        assert result is None
