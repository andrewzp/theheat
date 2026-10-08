"""Offline HTTP/sleep fixtures exercise actual bounded source recovery."""
from datetime import UTC, datetime
import math
from unittest.mock import Mock

import pytest

from src.data import air_quality as source
from src.data.source_status import SourceFetchError
from tests.test_air_quality import _city, _http_error, _payload, _response

DATE = "Tue, 09 Jun 2026 17:44:00 GMT"


@pytest.mark.parametrize("value,expected", [("0", 0), ("17", 17), (" 17 ", 17),
    ("00017", 17), ("63", 63), ("64", None), ("86400", None), ("9" * 256, None),
    ("9" * 257, None), ("invalid" * 100, None)])
def test_bounded_integer_or_defer(value, expected):
    assert source._rate_limit_wait_seconds_for_headers(DATE, value) == expected


@pytest.mark.parametrize("value", [None, "", "inf", "Infinity", "NaN", "-5", "+5",
    "1.5", "1e9", "１２", "5, 17", "not a date", "Tue, 09 Jun 2026 17:44:17",
    "Tue, 99 Jun 2026 17:44:17 GMT"])
def test_malformed_header_uses_bounded_date_fallback(value):
    wait = source._rate_limit_wait_seconds_for_headers(DATE, value)
    assert wait == 62 and math.isfinite(wait)


@pytest.mark.parametrize("value,expected", [
    ("Tue, 09 Jun 2026 17:44:17 GMT", 17),
    ("Tue, 09 Jun 2026 17:45:03 GMT", 63),
    ("Tue, 09 Jun 2026 17:45:04 GMT", None),
    ("Wed, 10 Jun 2026 17:44:00 GMT", None),
    ("Tue, 09 Jun 2026 17:43:59 GMT", 0),
])
def test_http_date_uses_same_response_reference(value, expected):
    assert source._rate_limit_wait_seconds_for_headers(DATE, value) == expected


@pytest.mark.parametrize("reference", [None, "bad", "Tue, 09 Jun 2026 17:44:00", "x" * 257])
def test_bad_reference_uses_aware_local_receipt_clock(monkeypatch, reference):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return cls(2026, 6, 9, 17, 44, tzinfo=UTC)
    monkeypatch.setattr(source, "datetime", Clock)
    assert source._rate_limit_wait_seconds_for_headers(
        reference, "Tue, 09 Jun 2026 17:44:17 GMT") == 17
    assert source._rate_limit_wait_seconds_for_headers(reference, "bad") == 62


def transport(monkeypatch, responses):
    fetch, sleep, pace = Mock(side_effect=responses), Mock(), Mock()
    monkeypatch.setattr(source, "fetch_with_retry", fetch)
    monkeypatch.setattr(source.time, "sleep", sleep)
    monkeypatch.setattr(source, "_chunk_pacing_sleep", pace)
    return fetch, sleep, pace


@pytest.mark.parametrize("headers,expected", [
    ([{"retry_after": "40"}, {"retry_after": "2"}], 40),
    ([{"retry_after": "2"}, {"retry_after": "40"}], 40),
    ([{"retry_after": "40"}, {}], 62),
    ([{"date": "Tue, 09 Jun 2026 17:44:57 GMT"}, {"retry_after": "2"}], 5),
    ([{"date": DATE, "retry_after": "Tue, 09 Jun 2026 17:44:40 GMT"},
      {"date": "Tue, 09 Jun 2026 17:44:38 GMT", "retry_after": "2"}], 40),
])
def test_failed_chunks_keep_longest_paired_delay(monkeypatch, headers, expected):
    fetch, sleep, _ = transport(monkeypatch, [
        *[_http_error(429, **h) for h in headers],
        _response(_payload()), _response(_payload()),
    ])
    results = source.fetch_batch_air_quality([_city(), _city(city="Second")], chunk_size=1)
    assert all(r is not None for r in results)
    assert fetch.call_count == 4
    sleep.assert_called_once_with(float(expected))


@pytest.mark.parametrize("retry_after", ["86400", "64", "9" * 300])
def test_large_wait_retains_good_packet_and_stops_remaining_source_work(monkeypatch, retry_after, capsys):
    payload = _payload()
    fetch, sleep, pace = transport(monkeypatch, [
        _response(payload), _http_error(429, retry_after=retry_after),
    ])
    results = source.fetch_batch_air_quality([_city(), _city(city="Second"), _city(city="Third")], chunk_size=1)
    assert results[0] is not None and results[1:] == [None, None]
    packet = results[0].forecast_window
    assert packet["series"]["pm2_5"]["values"] == payload["hourly"]["pm2_5"]
    assert source.window_contract.validate_window(packet)["pm2_5"] == 150
    assert fetch.call_count == 2 and pace.call_count == 1
    sleep.assert_not_called()
    output = capsys.readouterr().out
    assert "recovery deferred" in output and retry_after not in output


def test_large_wait_in_recovery_preserves_prior_successes(monkeypatch):
    fetch, sleep, _ = transport(monkeypatch, [
        _http_error(429, retry_after="17"), _response(_payload()),
        _http_error(429, retry_after="86400"),
    ])
    results = source.fetch_batch_air_quality([_city(), _city(city="Second")], chunk_size=1)
    assert results[0] is None and results[1] is not None
    sleep.assert_called_once_with(17.0)
    assert fetch.call_count == 3


@pytest.mark.parametrize("header", ["inf", "NaN", "-5", "1e100"])
def test_invalid_delay_never_reaches_sleep_or_adds_attempts(monkeypatch, header):
    fetch, sleep, _ = transport(monkeypatch, [_http_error(429, retry_after=header)] * 3)
    assert source.fetch_batch_air_quality([_city()], chunk_size=1) == [None]
    assert fetch.call_count == 3
    assert [c.args for c in sleep.call_args_list] == [(62.0,), (62.0,)]


def test_no_recovery_budget_never_sleeps(monkeypatch):
    fetch, sleep, _ = transport(monkeypatch, [_http_error(429, retry_after="17")])
    assert source.fetch_batch_air_quality([_city()], recovery_passes=0) == [None]
    assert fetch.call_count == 1
    sleep.assert_not_called()


def test_defer_does_not_turn_all_stale_evidence_into_quiet_weather(monkeypatch):
    stale = SourceFetchError("invented stale window")
    fetch = Mock(side_effect=[stale, ([None], False, None, "86400")])
    sleep = Mock()
    monkeypatch.setattr(source, "_fetch_chunk", fetch)
    monkeypatch.setattr(source, "_chunk_pacing_sleep", Mock())
    monkeypatch.setattr(source.time, "sleep", sleep)
    with pytest.raises(SourceFetchError) as raised:
        source.fetch_batch_air_quality([_city(), _city(city="Second")], chunk_size=1)
    assert raised.value is stale and fetch.call_count == 2
    sleep.assert_not_called()


def test_source_telemetry_keeps_missing_cities_distinct_from_quiet_valid_data(monkeypatch):
    from copy import deepcopy
    from src.orchestrator.sources.air_quality import run_air_quality
    from src.state import DEFAULT_STATE

    fetch, sleep, _ = transport(monkeypatch, [
        _response(_payload(pm25=[10.0] * 24, dust=[0.0] * 24)),
        _http_error(429, retry_after="86400"),
    ])
    original_fetch = source.fetch_batch_air_quality
    monkeypatch.setattr(source, "fetch_batch_air_quality",
                        lambda cities: original_fetch(cities, chunk_size=1))
    state, run = deepcopy(DEFAULT_STATE), {"sources": []}
    run_air_quality(state, run, [_city(), _city(city="Second"), _city(city="Third")])
    entry = run["sources"][0]
    assert entry["status"] == "degraded" and entry["observed"] == 1
    assert entry["details"]["failed_cities"] == 2
    assert entry["promoted"] == entry["drafted"] == 0
    assert not state.get("_triage_queue") and fetch.call_count == 2
    sleep.assert_not_called()
