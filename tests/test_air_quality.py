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


def _http_error(status: int, *, date: str | None = None, retry_after: str | None = None) -> requests.HTTPError:
    """Build an HTTPError like fetch_with_retry raises on a 4xx (e.g. a 429)."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {}
    if date:
        resp.headers["Date"] = date
    if retry_after:
        resp.headers["Retry-After"] = retry_after
    return requests.HTTPError(response=resp)


def _obs(
    *,
    city: str = "Lahore",
    country: str = "Pakistan",
    day: str = "2026-06-08",
    pm25: float | None = 150.0,
    dust: float | None = 500.0,
    aod: float | None = 0.6,
    us_aqi: int | None = 210,
    pm10_24h_mean: float | None = None,
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
        pm10_24h_mean=pm10_24h_mean,
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


def test_detect_dust_event_carries_pm10_anchor_when_available():
    """P_dust root cause: dust drafts had no WHO-scale anchor because the
    event carried none. The anchor is CO-MEASURED PM10 (a separate hourly
    variable from `dust`), 24h mean vs the WHO 2021 PM10 24h AQG (45)."""
    obs = _obs(dust=2400.0, pm10_24h_mean=900.0)
    event = detect_dust_event(obs)
    assert event is not None
    assert event.pm10_24h_mean == 900.0
    assert event.who_pm10_multiple == 20.0  # round(900/45, 1)


def test_detect_dust_event_is_none_safe_without_pm10():
    # A cycle where the pm10 series is missing must still mint the dust
    # event (tier logic unchanged) with the anchor fields None.
    obs = _obs(dust=2400.0, pm10_24h_mean=None)
    event = detect_dust_event(obs)
    assert event is not None
    assert event.pm10_24h_mean is None
    assert event.who_pm10_multiple is None


def test_batch_fetch_chunk_splits():
    """638 cities become multiple HTTP calls of at most chunk_size locations each."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with (
        patch("src.data.air_quality._pacing_sleep") as mock_pacing_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            _response([_payload() for _ in range(50)]),
            _response([_payload()]),
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50)

    assert len(observations) == 51
    assert mock_fetch.call_count == 2
    assert mock_pacing_sleep.call_count == 1
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
    """With recovery disabled, one chunk transport failure leaves that chunk None."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with (
        patch("src.data.air_quality._pacing_sleep"),
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            requests.RequestException("timeout"),
            _response([_payload(pm25=[250.0] * 24)]),
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50, recovery_passes=0)

    assert observations[:50] == [None] * 50
    assert observations[50] is not None
    assert observations[50].pm25_24h_mean == pytest.approx(250.0)


def test_batch_fetch_recovers_rate_limited_chunk_after_wait():
    """A 429'd chunk is retried after waiting out Open-Meteo's per-minute window."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with (
        patch("src.data.air_quality._pacing_sleep"),
        patch("src.data.air_quality.time.sleep") as mock_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            _http_error(429, date="Tue, 09 Jun 2026 17:44:57 GMT"),  # chunk 0, main pass
            _response([_payload()]),                                 # chunk 1, main pass
            _response([_payload() for _ in range(50)]),              # chunk 0, recovery
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50)

    assert observations[0] is not None  # recovered after the wait
    assert observations[49] is not None
    assert observations[50] is not None
    assert mock_sleep.call_count == 1


def test_chunks_are_paced():
    """Healthy chunk sweeps pause between chunk requests, but never after the last chunk."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(5)]

    with (
        patch("src.data.air_quality._pacing_sleep") as mock_pacing_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            _response([_payload() for _ in range(2)]),
            _response([_payload() for _ in range(2)]),
            _response([_payload()]),
        ]
        fetch_batch_air_quality(cities, chunk_size=2)

    assert mock_fetch.call_count == 3
    assert [call.args[0] for call in mock_pacing_sleep.call_args_list] == [8, 8]


def test_retry_after_header_honored():
    """Open-Meteo Retry-After is the pacing authority when a 429 includes it."""
    cities = [_city()]
    err = _http_error(429, date="Tue, 09 Jun 2026 17:44:30 GMT", retry_after="17")

    with (
        patch("src.data.air_quality.time.sleep") as mock_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            err,
            _response([_payload()]),
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=1)

    assert observations[0] is not None
    assert mock_sleep.call_args.args == (17.0,)


def test_batch_fetch_no_failures_does_not_recovery_sleep():
    """A fully successful sweep uses chunk pacing only, not recovery waits."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(51)]

    with (
        patch("src.data.air_quality._pacing_sleep") as mock_pacing_sleep,
        patch("src.data.air_quality.time.sleep") as mock_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            _response([_payload() for _ in range(50)]),
            _response([_payload()]),
        ]
        fetch_batch_air_quality(cities, chunk_size=50)

    assert mock_sleep.call_count == 0
    assert mock_pacing_sleep.call_count == 1


def test_batch_fetch_recovers_transport_failed_chunk():
    """A transient transport failure (not a 429) is also retried after a wait."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(50)]

    with (
        patch("src.data.air_quality.time.sleep") as mock_sleep,
        patch("src.data.air_quality.fetch_with_retry") as mock_fetch,
    ):
        mock_fetch.side_effect = [
            requests.RequestException("timeout"),         # main pass fails
            _response([_payload() for _ in range(50)]),   # recovery succeeds
        ]
        observations = fetch_batch_air_quality(cities, chunk_size=50)

    assert all(obs is not None for obs in observations)
    assert mock_sleep.call_count == 1


def test_batch_fetch_gives_up_after_recovery_passes():
    """A persistently rate-limited chunk is retried a bounded number of times, then left None."""
    cities = [_city(city=f"City {i}", lat=float(i), lon=float(i + 1)) for i in range(50)]
    err = _http_error(429, date="Tue, 09 Jun 2026 17:44:30 GMT")

    with (
        patch("src.data.air_quality.time.sleep") as mock_sleep,
        patch("src.data.air_quality.fetch_with_retry", side_effect=err) as mock_fetch,
    ):
        observations = fetch_batch_air_quality(cities, chunk_size=50, recovery_passes=2)

    assert observations == [None] * 50
    assert mock_sleep.call_count == 2   # two recovery passes
    assert mock_fetch.call_count == 3   # main pass + 2 retries


def test_rate_limit_wait_seconds_from_date_header():
    """Wait = seconds to the next clock-minute boundary plus a small buffer."""
    from src.data.air_quality import _rate_limit_wait_seconds

    # :57 into the minute -> 3s to the boundary + 2s buffer = 5s
    assert _rate_limit_wait_seconds("Tue, 09 Jun 2026 17:44:57 GMT") == pytest.approx(5.0)


def test_rate_limit_wait_seconds_default_without_date():
    """No server Date -> a safe blind wait that clears a full minute window."""
    from src.data.air_quality import _RATE_LIMIT_DEFAULT_WAIT_S, _rate_limit_wait_seconds

    assert _rate_limit_wait_seconds(None) == _RATE_LIMIT_DEFAULT_WAIT_S
    assert _RATE_LIMIT_DEFAULT_WAIT_S >= 60.0


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
