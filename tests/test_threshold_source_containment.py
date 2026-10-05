"""Offline source isolation: no database, provider, writer or public post access."""

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from src.data.open_meteo import AbsoluteExtremeEvent, ExtremeSignalBundle
from src.orchestrator.sources import open_meteo as runner
from src.state import _fresh_state


def world_bundle(country="Spain"):
    event = AbsoluteExtremeEvent(
        city="Synthetic city", country=country, today_temp_c=48,
        band_label="Desert", threshold_c=46, kind="hot", lat=37, lon=-6,
        event_id=f"synthetic-extreme-{country}", signal_date=date.today(),
    )
    return ExtremeSignalBundle(
        city=event.city, country=country, absolute_extreme=event,
        signal_date=date.today(),
    )


@pytest.mark.parametrize("outcome", [None, "", "failure", "skipped", "cancelled", "SUCCESS", "private arbitrary error"])
@pytest.mark.parametrize("provider", ["ghcn", "both"])
def test_unverified_ghcn_never_runs_and_world_remains_partitioned(monkeypatch, outcome, provider):
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", provider)
    if outcome is None:
        monkeypatch.delenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", outcome)
    ghcn = Mock(side_effect=AssertionError("unverified database must never be read"))
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", ghcn)
    cities = [{"city": "Synthetic city", "country": "Spain"}, {"city": "US city", "country": "United States"}]
    world_calls = []

    def world(candidates, metrics, **kwargs):
        world_calls.append(candidates)
        metrics.update(status="success", world_total=1, forecast_attempted=1, coverage_ratio=1)
        # A stray US bundle must still be excluded by the existing partition.
        return [world_bundle(), world_bundle("United States")], []

    monkeypatch.setattr(runner, "_run_world_cached_half", world)
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    bot = _fresh_state()
    old = (date.today() - timedelta(days=10)).isoformat()
    bot["record_streaks"]["synthetic-US-station"] = {"last_date": old}
    run = {"sources": []}
    runner.run_extreme_signals(bot, run, cities, {}, {})
    ghcn.assert_not_called()
    assert bot["record_streaks"]["synthetic-US-station"] == {"last_date": old}
    source = run["sources"][0]
    assert source["status"] == ("degraded" if provider == "both" else "failed")
    key = "ghcn_pipeline_metrics" if provider == "both" else "pipeline_metrics"
    metrics = source["details"][key]
    assert metrics["status"] == "failed"
    assert metrics["error"] == "threshold_baseline_unavailable"
    assert metrics["threshold_verification"] in {"failure", "skipped", "cancelled", "unknown"}
    assert "private arbitrary" not in str(source)
    health = bot["source_health"]["open_meteo_extreme_signals"]
    assert health[source["status"]] == 1 and health.get("success", 0) == 0
    if provider == "both":
        assert world_calls == [[cities[0]]]
        assert [c.event_id for c in bot["_triage_queue"]] == ["synthetic-extreme-Spain"]
    else:
        assert world_calls == [] and not bot.get("_triage_queue")


@pytest.mark.parametrize("failure", ["exception", "missing_diff", "none"])
def test_verified_source_preserves_results_and_reports_ghcn_health(monkeypatch, failure):
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "both")
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "success")

    def ghcn(*, metrics_out, **kwargs):
        if failure == "exception":
            raise RuntimeError("private provider body")
        if failure == "missing_diff":
            metrics_out.update(diff_dates_missing=1, diff_dates_fetched=0)
        return [world_bundle("United States")], []

    source_call = Mock(side_effect=ghcn)
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", source_call)
    monkeypatch.setattr(runner, "_run_world_cached_half", lambda *a, **k: ([world_bundle()], []))
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    bot, run = _fresh_state(), {"sources": []}
    runner.run_extreme_signals(bot, run, [], {}, {})
    source_call.assert_called_once()
    ids = {c.event_id for c in bot["_triage_queue"]}
    assert "synthetic-extreme-Spain" in ids
    assert ("synthetic-extreme-United States" in ids) == (failure != "exception")
    assert run["sources"][0]["status"] == ("success" if failure == "none" else "degraded")
    assert "private provider body" not in str(run)


def test_open_meteo_only_does_not_require_ghcn_verification(monkeypatch):
    monkeypatch.setenv("THEHEAT_SIGNALS_PROVIDER", "open_meteo")
    monkeypatch.setenv("THEHEAT_GHCN_THRESHOLD_VERIFICATION", "failure")
    ghcn = Mock()
    monkeypatch.setattr(runner.ghcn, "check_extreme_signals_for_stations", ghcn)
    city = Mock(return_value=([], []))
    monkeypatch.setattr(runner, "_check_city_extreme_signals", city)
    run = {"sources": []}
    runner.run_extreme_signals(_fresh_state(), run, [], {}, {})
    city.assert_called_once()
    ghcn.assert_not_called()
    assert run["sources"][0]["status"] == "success"


def test_workflow_contains_failure_but_never_caches_an_unverified_database():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/bot.yml"
    steps = yaml.safe_load(path.read_text())["jobs"]["run"]["steps"]
    verify = next(s for s in steps if s.get("id") == "thresholds-verify")
    restore = next(s for s in steps if s.get("id") == "thresholds-cache")
    save = next(s for s in steps if s.get("uses") == "actions/cache/save@v4")
    bot = next(s for s in steps if s.get("name") == "Run bot")
    assert verify["continue-on-error"] is True and verify["timeout-minutes"] == 5
    assert "scripts.threshold_artifacts ensure" in verify["run"]
    assert restore["uses"] == "actions/cache/restore@v4"
    assert restore["continue-on-error"] is True and save["continue-on-error"] is True
    assert save["if"] == "steps.thresholds-verify.outcome == 'success' && steps.thresholds-cache.outputs.cache-hit != 'true'"
    assert save["with"] == restore["with"] and "restore-keys" not in restore["with"]
    assert bot["env"]["THEHEAT_GHCN_THRESHOLD_VERIFICATION"] == "${{ steps.thresholds-verify.outcome || 'unknown' }}"
    assert steps.index(restore) < steps.index(verify) < steps.index(save) < steps.index(bot)
