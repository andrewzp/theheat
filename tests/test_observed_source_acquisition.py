"""Observed scope excludes forecast acquisition; existing GHCN qualification stays real."""
from copy import deepcopy

import pytest

from src.data import ghcn
from src.orchestrator import caps
from src.orchestrator.sources import open_meteo as source
from src.state import DEFAULT_STATE
from tests.test_ghcn_scientific_supply import supply_inputs as supply_inputs


@pytest.mark.parametrize("provider,expected_count", [("both", 0), ("both_global", 2)])
@pytest.mark.parametrize("observed_only", [False, True])
def test_qualified_station_artifacts_survive_while_excluded_world_requests_do_not(
    monkeypatch, supply_inputs, provider, expected_count, observed_only,
):
    for station in supply_inputs["stations"]:
        station.update(country_code="FR", country_name="France", state="")
    calls = []
    qualify = ghcn.check_extreme_signals_for_stations
    def stations(**kwargs):
        calls.append("station")
        return qualify(**supply_inputs, metrics_out=kwargs["metrics_out"])
    def world(cities, metrics, *, bot_state):
        calls.append("world")
        assert not observed_only, "excluded forecast or warming request"
        assert cities == [{"country": "FR"}]
        metrics.update(status="success", world_total=1)
        return [], []
    monkeypatch.setattr(ghcn, "check_extreme_signals_for_stations", stations)
    monkeypatch.setattr(source, "_run_world_cached_half", world)
    monkeypatch.setattr(source, "_should_draft", lambda *_a, **_kw: True)
    monkeypatch.setattr(caps, "GHCN_INDIVIDUALS_PER_COUNTRY", 2)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", provider)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1" if observed_only else "0")
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")
    monkeypatch.setenv("THEHEAT_RECORDS_CLUSTER_ENABLED", "0")
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-observed-acquisition", "sources": []}
    source.run_extreme_signals(state, run, [{"country": "US"}, {"country": "FR"}], {}, {})
    assert calls == (["station"] if observed_only else ["station", "world"])
    candidates = [c for c in state.get("_triage_queue", []) if c.legacy_type == "all_time_high"]
    assert len(candidates) == expected_count
    for c in candidates:
        assert c.bundle.raw_signal_dump["country"] == "France"
        assert c.bundle.raw_signal_dump["evidence"]["evidence_type"] == "observed"
        assert c.bundle.headline_metric["label"] == "observed_high_c"
    if observed_only:
        details = run["sources"][0]["details"]
        assert details["open_meteo_pipeline_metrics"]["status"] == "skipped"
        assert details["open_meteo_pipeline_metrics"]["reason"] == "observed_weather_only"
        assert details["ghcn_pipeline_metrics"]["stations_checked"] > 0


@pytest.mark.parametrize("provider", ["both", "both_global"])
@pytest.mark.parametrize("status", ["success", "degraded", "failed"])
def test_intentional_world_skip_preserves_actual_station_leg_outcome(monkeypatch, provider, status):
    calls = []
    def stations(state, metrics, **_kwargs):
        calls.append("station")
        metrics.update(status=status, threshold_verification="failed" if status == "failed" else "success")
        return [], []
    def forbidden(*_a, **_kw):
        pytest.fail("no forecast, archive warm or fallback provider is permitted")
    monkeypatch.setattr(source, "_verified_ghcn_signals", stations)
    monkeypatch.setattr(source, "_run_world_cached_half", forbidden)
    monkeypatch.setattr(source, "_check_city_extreme_signals", forbidden)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", provider)
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    state = deepcopy(DEFAULT_STATE)
    run = {"sources": []}
    source.run_extreme_signals(state, run, [], {}, {})
    assert calls == ["station"]
    row = run["sources"][0]
    assert row["status"] == status
    assert row["details"]["selected_acquisition_provider"] == "ghcn"
    assert "world[skipped:observed_weather_only]" in row["note"]


def test_explicit_forecast_only_provider_skips_without_inventing_a_station_fallback(monkeypatch):
    def forbidden(*_a, **_kw):
        pytest.fail("an editorial skip grants no source/fallback/model authority")
    for name in ["_verified_ghcn_signals", "_run_world_cached_half", "_check_city_extreme_signals"]:
        monkeypatch.setattr(source, name, forbidden)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    state = deepcopy(DEFAULT_STATE)
    before = deepcopy(state)
    run = {"sources": []}
    source.run_extreme_signals(state, run, [], {}, {})
    row = run["sources"][0]
    assert row["status"] == "skipped" and row["observed"] == row["promoted"] == 0
    assert row["details"]["provider"] == "open_meteo"
    assert row["details"]["reason"] == "observed_weather_only"
    assert state.get("data_source_failures") == before.get("data_source_failures")
    assert not state.get("_triage_queue")


def test_ghcn_only_configuration_uses_its_existing_source_call(monkeypatch):
    calls = []
    def stations(state, metrics, **kwargs):
        calls.append("station")
        metrics.update(status="success", threshold_verification="success")
        return [], []
    monkeypatch.setattr(source, "_verified_ghcn_signals", stations)
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "ghcn")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    run = {"sources": []}
    source.run_extreme_signals(deepcopy(DEFAULT_STATE), run, [], {}, {})
    assert calls == ["station"] and run["sources"][0]["status"] == "success"
