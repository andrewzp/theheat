from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.data.air_quality import (
    AQ_URL,
    WHO_24H_GUIDELINE,
    CityAirQuality,
    detect_dust_event,
    detect_pm25_hazard,
    fetch_batch_air_quality,
)


def _city(city: str = "Lahore", country: str = "Pakistan", lat: float = 31.5, lon: float = 74.3) -> dict:
    return {"city": city, "country": country, "lat": str(lat), "lon": str(lon)}


def _payload(
    *,
    day: str | None = None,
    pm25: list[float | None] | None = None,
    dust: list[float | None] | None = None,
    aod: list[float | None] | None = None,
    us_aqi: list[int | None] | None = None,
) -> dict:
    day = day or date.today().isoformat()
    return {
        "latitude": 31.5,
        "longitude": 74.3,
        "hourly": {
            "time": [f"{day}T{hour:02d}:00" for hour in range(24)],
            "pm2_5": pm25 if pm25 is not None else [150.0] * 24,
            "dust": dust if dust is not None else [0.0] * 24,
            "aerosol_optical_depth": aod if aod is not None else [0.2] * 24,
            "us_aqi": us_aqi if us_aqi is not None else [None] * 23 + [210],
        },
    }


def _response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _obs(
    *,
    city: str = "Lahore",
    country: str = "Pakistan",
    day: str = "2026-06-08",
    pm25: float | None = 150.0,
    dust: float | None = 500.0,
    aod: float | None = 0.6,
    us_aqi: int | None = 210,
) -> CityAirQuality:
    return CityAirQuality(
        city=city,
        country=country,
        lat=31.5,
        lon=74.3,
        date=day,
        pm25_24h_mean=pm25,
        dust_daily_max=dust,
        aod_daily_max=aod,
        us_aqi_daily_max=us_aqi,
    )


def test_fetch_24h_mean_pm25():
    """pm25_24h_mean is the arithmetic mean of non-None hourly PM2.5 values."""
    values = [100.0, None, 200.0] + [None] * 21

    with patch("src.data.air_quality.fetch_with_retry", return_value=_response([_payload(pm25=values)])):
        observations = fetch_batch_air_quality([_city()])

    assert observations[0] is not None
    assert observations[0].pm25_24h_mean == pytest.approx(150.0)


def test_fetch_dust_daily_max():
    """dust_daily_max is the max of non-None hourly dust values, not the mean."""
    values = [100.0, 500.0, 900.0] + [None] * 21

    with patch("src.data.air_quality.fetch_with_retry", return_value=_response([_payload(dust=values)])):
        observations = fetch_batch_air_quality([_city()])

    assert observations[0] is not None
    assert observations[0].dust_daily_max == pytest.approx(900.0)


def test_pm25_tier_1_fires_at_150():
    event = detect_pm25_hazard(_obs(pm25=150.0))

    assert event is not None
    assert event.tier == 1


def test_pm25_tier_2_fires_at_250():
    event = detect_pm25_hazard(_obs(pm25=250.0))

    assert event is not None
    assert event.tier == 2


def test_pm25_tier_3_fires_at_350():
    event = detect_pm25_hazard(_obs(pm25=350.0))

    assert event is not None
    assert event.tier == 3


def test_pm25_below_threshold_returns_none():
    assert detect_pm25_hazard(_obs(pm25=149.9)) is None


def test_pm25_none_returns_none():
    assert detect_pm25_hazard(_obs(pm25=None)) is None


def test_dust_tier_1_fires_at_500():
    event = detect_dust_event(_obs(dust=500.0))

    assert event is not None
    assert event.tier == 1


def test_dust_tier_2_fires_at_2000():
    event = detect_dust_event(_obs(city="Khartoum", country="Sudan", dust=2000.0))

    assert event is not None
    assert event.tier == 2


def test_dust_tier_3_fires_at_5000():
    event = detect_dust_event(_obs(city="Khartoum", country="Sudan", dust=5000.0))

    assert event is not None
    assert event.tier == 3


def test_dust_below_threshold_returns_none():
    assert detect_dust_event(_obs(dust=499.9)) is None


def test_batch_fetch_chunk_splits():
    """638 cities become multiple HTTP calls of at most chunk_size locations each."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with patch("src.data.air_quality.fetch_with_retry") as mock_fetch:
        mock_fetch.side_effect = [
            _response([_payload() for _ in range(50)]),
            _response([_payload()]),
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50)

    assert len(observations) == 51
    assert mock_fetch.call_count == 2
    first_params = mock_fetch.call_args_list[0].kwargs["params"]
    second_params = mock_fetch.call_args_list[1].kwargs["params"]
    assert len(first_params["latitude"].split(",")) == 50
    assert len(second_params["latitude"].split(",")) == 1
    assert mock_fetch.call_args_list[0].args == (AQ_URL,)


def test_batch_fetch_list_response_parsed():
    """A list response maps each element back to the matching city in request order."""
    cities = [
        _city(city="Lahore", country="Pakistan", lat=31.5, lon=74.3),
        _city(city="Delhi", country="India", lat=28.6, lon=77.2),
    ]
    payload = [
        _payload(pm25=[150.0] * 24, dust=[100.0] * 24),
        _payload(pm25=[250.0] * 24, dust=[800.0] * 24),
    ]

    with patch("src.data.air_quality.fetch_with_retry", return_value=_response(payload)):
        observations = fetch_batch_air_quality(cities)

    assert [obs.city if obs else None for obs in observations] == ["Lahore", "Delhi"]
    assert observations[0] is not None
    assert observations[1] is not None
    assert observations[0].pm25_24h_mean == pytest.approx(150.0)
    assert observations[1].pm25_24h_mean == pytest.approx(250.0)
    assert observations[1].dust_daily_max == pytest.approx(800.0)


def test_batch_fetch_single_object_response_parsed_for_chunk_size_one():
    with patch("src.data.air_quality.fetch_with_retry", return_value=_response(_payload(pm25=[155.0] * 24))):
        observations = fetch_batch_air_quality([_city()], chunk_size=1)

    assert observations[0] is not None
    assert observations[0].pm25_24h_mean == pytest.approx(155.0)


def test_batch_fetch_partial_chunk_failure():
    """One chunk transport failure leaves that chunk None while later chunks parse."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with patch("src.data.air_quality.fetch_with_retry") as mock_fetch:
        mock_fetch.side_effect = [
            requests.RequestException("timeout"),
            _response([_payload(pm25=[250.0] * 24)]),
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50)

    assert observations[:50] == [None] * 50
    assert observations[50] is not None
    assert observations[50].pm25_24h_mean == pytest.approx(250.0)


def test_batch_fetch_all_null_pm25():
    with patch("src.data.air_quality.fetch_with_retry", return_value=_response([_payload(pm25=[None] * 24)])):
        observations = fetch_batch_air_quality([_city()])

    assert observations[0] is not None
    assert observations[0].pm25_24h_mean is None


def test_event_id_scheme_pm25():
    event = detect_pm25_hazard(_obs(city="Lahore", country="Pakistan", pm25=150.0))

    assert event is not None
    assert event.event_id == "pm25_lahore_2026-06-08_tier1"


def test_event_id_scheme_dust():
    event = detect_dust_event(_obs(city="Khartoum", country="Sudan", dust=2000.0))

    assert event is not None
    assert event.event_id == "dust_khartoum_2026-06-08_tier2"


def test_who_multiple_uses_15():
    assert WHO_24H_GUIDELINE == 15.0
    event = detect_pm25_hazard(_obs(pm25=150.0))

    assert event is not None
    assert event.who_multiple == pytest.approx(10.0)


def test_city_slug_special_chars_preserves_apostrophe_and_removes_comma():
    event = detect_dust_event(_obs(city="N'Djamena, Central", country="Chad", dust=500.0))

    assert event is not None
    assert event.event_id == "dust_n'djamena_central_2026-06-08_tier1"
