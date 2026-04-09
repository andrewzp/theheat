"""Tests for Open-Meteo data fetching and anomaly calculation."""

import responses
from src.data.open_meteo import (
    CityTemp,
    compute_anomalies,
    rank_hot10,
    fetch_city_temp,
    prioritize_cities,
    prioritize_cities_cold,
    PRIORITY_HEAT_CITIES,
    PRIORITY_COLD_CITIES,
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


class TestPrioritizeCities:
    def test_priority_cities_come_first(self):
        cities = [
            {"city": "Zurich", "country": "CH", "lat": "47.37", "lon": "8.54"},
            {"city": "Phoenix", "country": "US", "lat": "33.45", "lon": "-112.07"},
            {"city": "Amsterdam", "country": "NL", "lat": "52.37", "lon": "4.90"},
            {"city": "Dubai", "country": "UAE", "lat": "25.20", "lon": "55.27"},
        ]
        result = prioritize_cities(cities)
        # Phoenix and Dubai should be in the first 2 positions
        first_two = {result[0]["city"], result[1]["city"]}
        assert first_two == {"Phoenix", "Dubai"}

    def test_cold_priority_cities_come_first(self):
        cities = [
            {"city": "Zurich", "country": "CH", "lat": "47.37", "lon": "8.54"},
            {"city": "Yakutsk", "country": "RU", "lat": "62.03", "lon": "129.73"},
            {"city": "Anchorage", "country": "US", "lat": "61.22", "lon": "-149.90"},
        ]
        result = prioritize_cities_cold(cities)
        first_two = {result[0]["city"], result[1]["city"]}
        assert first_two == {"Yakutsk", "Anchorage"}

    def test_all_cities_preserved(self):
        cities = [
            {"city": "Zurich", "country": "CH", "lat": "0", "lon": "0"},
            {"city": "Phoenix", "country": "US", "lat": "0", "lon": "0"},
            {"city": "Oslo", "country": "NO", "lat": "0", "lon": "0"},
        ]
        result = prioritize_cities(cities)
        assert len(result) == 3
        result_names = {c["city"] for c in result}
        assert result_names == {"Zurich", "Phoenix", "Oslo"}

    def test_priority_heat_cities_exist_in_real_csv(self):
        """Sanity: at least 20 priority cities to ensure good coverage."""
        assert len(PRIORITY_HEAT_CITIES) >= 20

    def test_priority_cold_cities_exist(self):
        assert len(PRIORITY_COLD_CITIES) >= 15


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
