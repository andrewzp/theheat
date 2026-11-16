"""Observed-only rainfall never requests a forecast fallback; offline boundaries."""
from datetime import date, timedelta
from urllib.parse import urlparse

import pytest
import requests
import responses

from src.data import gpm_imerg as gpm
from src.data.source_status import SourceFetchError, SourceSkipped
from tests.test_rainfall_opportunity import DAY, Transport, population


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("flag", ["1", "0", "true", ""])
@pytest.mark.parametrize("failure", ["outage", "timeout", "auth", "parse", "skip"])
def test_primary_failure_keeps_its_authority_and_only_allowed_witness(monkeypatch, strict, flag, failure):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", flag)
    error = {
        "outage": SourceFetchError("HTTP 503 from invented primary"),
        "timeout": requests.Timeout("invented primary timeout"),
        "auth": SourceFetchError("EARTHDATA_TOKEN credential refused"),
        "parse": SourceFetchError("could not parse invented primary"),
        "skip": SourceSkipped("invented deliberate source skip"),
    }[failure]
    calls = []
    fallback = []

    def primary(*args, **kwargs):
        calls.append(("primary", kwargs))
        raise error

    def witness(*args, **kwargs):
        calls.append(("witness", kwargs))
        return fallback

    monkeypatch.setattr(gpm, "_fetch_daily_precip_primary", primary)
    monkeypatch.setattr(gpm, "_fetch_precip_open_meteo", witness)
    trace = gpm.RainfallOpportunityTrace(run_id="invented-observed-only")
    allowed = flag != "1" and failure in {"outage", "timeout"}
    if failure == "skip":
        with pytest.raises(SourceSkipped) as caught:
            gpm.fetch_daily_precip([], strict=strict, today=date(2026, 6, 5), trace=trace)
        assert caught.value is error
    elif strict and not allowed:
        with pytest.raises(SourceFetchError) as caught:
            gpm.fetch_daily_precip([], strict=strict, today=date(2026, 6, 5), trace=trace)
        assert caught.value.__cause__ is error
    else:
        assert gpm.fetch_daily_precip([], strict=strict, today=date(2026, 6, 5), trace=trace) == []
    assert [name for name, _ in calls] == (["primary", "witness"] if allowed else ["primary"])
    assert calls[0][1]["strict"] is strict
    saved = trace.export()
    assert saved["outcome"] == ("skipped" if failure == "skip" else "empty" if allowed else "failed")
    assert saved["request_counts"]["witness_point_calls"] == 0


@pytest.mark.parametrize("flag", ["1", "0"])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_primary_success_is_unchanged_and_never_uses_witness(monkeypatch, flag, strict, empty):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", flag)
    rows = [] if empty else [gpm.CityPrecipReading(
        "Invented point", "Testland", 0, 0, "2026-06-04", 40.0, "late",
        "gpm_imerg_invented_2026-06-04",
    )]
    monkeypatch.setattr(gpm, "_fetch_daily_precip_primary", lambda *a, **kw: rows)
    monkeypatch.setattr(gpm, "_fetch_precip_open_meteo", lambda *a, **kw: pytest.fail("unexpected witness request"))
    trace = gpm.RainfallOpportunityTrace(run_id="invented-primary-success")
    assert gpm.fetch_daily_precip([], strict=strict, today=date(2026, 6, 5), trace=trace) is rows
    assert trace.export()["outcome"] == ("empty" if empty else "primary_served")


@responses.activate
@pytest.mark.parametrize("flag", ["1", "0"])
def test_actual_failed_observation_requests_and_runner_telemetry(monkeypatch, flag):
    from src.orchestrator.sources import gpm_imerg as runner
    from src.state import _fresh_state, init_run

    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", flag)
    monkeypatch.setenv("EARTHDATA_TOKEN", "invented-not-a-credential")
    monkeypatch.setenv("THEHEAT_GPM_SOURCE", "datapool")
    monkeypatch.setenv("GPM_IMERG_MAX_CITIES", "6")
    monkeypatch.setenv("GPM_IMERG_MAX_WORKERS", "1")
    monkeypatch.setenv("GPM_IMERG_RETRY_BACKOFF_S", "0")
    monkeypatch.setattr(gpm, "_default_start_date", lambda: DAY - timedelta(days=1))
    # Fix the source clock as well as its walkback without replacing any reader.
    class Clock:
        @staticmethod
        def now(tz):
            from datetime import datetime
            return datetime(2026, 6, 5, 12, tzinfo=tz)

    monkeypatch.setattr(gpm, "datetime", Clock)
    rows = population(6)
    Transport(rows, grid_status=503, probe_published=[DAY - timedelta(days=1)],
              point={i: "fail" for i in range(6)}).install()
    run = init_run("alerts")
    runner.run_gpm_imerg(_fresh_state(), run, rows)
    (saved,) = run["sources"]
    trace = saved["details"]["rainfall_opportunity"]
    hosts = [urlparse(call.request.url).hostname for call in responses.calls]
    assert "data.gesdisc.earthdata.nasa.gov" in hosts
    assert "gpm1.gesdisc.eosdis.nasa.gov" in hosts
    forecast_hosts = {"api.open-meteo.com", "ensemble-api.open-meteo.com"}
    if flag == "1":
        assert forecast_hosts.isdisjoint(hosts)
        assert saved["status"] == "failed"
        assert saved["observed"] == saved["promoted"] == saved["drafted"] == 0
        assert trace["outcome"] == "failed"
        assert trace["serving_leg"] is None
        assert trace["request_counts"]["witness_point_calls"] == 0
        assert all(leg["leg"] != "open_meteo_witness" for leg in trace["legs"])
    else:
        assert forecast_hosts <= set(hosts)
        assert saved["status"] == "degraded"
        assert trace["outcome"] == "witness_served"
        assert trace["serving_leg"] == "open_meteo_witness"
        assert trace["request_counts"]["witness_point_calls"] == 6
