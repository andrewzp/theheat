"""Operating-scope regressions; invented evidence, no provider or platform calls."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.editorial import observed_scope as scope


def observation():
    return {"signal_kind": "monthly_high", "event_id": "invented", "current_facts": [],
            "raw_signal_dump": {"evidence": {"evidence_type": "observed", "source_product": "ghcn-daily"}},
            "headline_metric": {"label": "observed_max_c", "value": 38}}


def cases():
    rows = [(observation(), False)]
    for kind in sorted(scope.FORECAST_KINDS):
        rows.append(({**observation(), "signal_kind": kind}, True))
    for slot in (None, "evidence", "forecast_window", "source_evidence", "rainfall_window"):
        for field, value in (("evidence_type", "forecast"), ("evidence_type", "model_forecast"),
                             ("source_product", "openmeteo-best-match-forecast-daily-v1"),
                             ("source_product", "open-meteo-cams-air-quality-auto"),
                             ("source_product", "Open-Meteo multi-model forecast precipitation"),
                             ("source_product", "openmeteo-marine-forecast")):
            row = observation()
            marker = {field: value}
            row["raw_signal_dump"] = marker if slot is None else {slot: marker}
            rows.append((row, True))
    row = observation()
    row["raw_signal_dump"]["evidence"]["source_product"] = "openmeteo-best-match-forecast-daily-v1"
    rows.append((row, True))  # An observed label cannot relabel a canonical forecast.
    row = observation()
    row["headline_metric"]["label"] = "forecast_max_c"
    rows.append((row, True))
    for field, value in (("evidence_type", "forecast"), ("source_product", "open-meteo-cams-air-quality-auto"),
                             ("source_product", "Open-Meteo multi-model forecast precipitation"),
                             ("source_product", "openmeteo-marine-forecast")):
        row = observation()
        row["current_facts"] = [{"label": field, "value": value}]
        rows.append((row, True))
    for kind, metric in (("wet_bulb_extreme", {"label": "daily_max_tw_c", "value": 34}),
                         ("extreme_wave", {"label": "wave_height_m", "value": 11}),
                         ("river_flood", {"label": "modeled_discharge_m3s", "value": 900}),
                         ("absolute_extreme", {"label": "max_c", "value": 42, "is_forecast": True})):
        row = observation()
        row["related_signals"] = [{"signal_kind": kind, "headline_metric": metric}]
        rows.append((row, True))
    for malformed in (None, [], {}, 123):
        row = observation()
        row["raw_signal_dump"]["evidence"] = {"evidence_type": malformed, "source_product": malformed}
        row["current_facts"] = [{"label": "evidence_type", "value": malformed}]
        rows.append((row, False))  # Scope does not grant scientific validity.
    row = observation()
    row["raw_signal_dump"]["notes"] = "Observed values, not forecasts; forecast wording appears in unrelated prose."
    rows.append((row, False))
    row = observation()
    row["raw_signal_dump"]["evidence"]["evidence_type"] = "reanalysis"
    row["raw_signal_dump"]["evidence"]["source_product"] = "openmeteo-era5-daily-v2"
    rows.append((row, False))
    for related in ({"signal_kind": "air_quality_hazard"},
                    {"signal_kind": "other", "air_quality_evidence": {"evidence_type": "model_forecast"}}):
        row = observation()
        row["related_signals"] = [related]
        rows.append((row, True))
    return rows


def real_builder_cases():
    from dataclasses import replace
    from src.data.river_gauges import FloodEvent
    from src.data.gpm_imerg import PrecipExtremeEvent
    from src.data.ocean import ExtremeWaveEvent
    from src.two_bot.intern.disasters import build_river_flood_bundle
    from src.two_bot.intern.precipitation import build_precipitation_bundle
    from src.two_bot.intern.marine import build_extreme_wave_bundle

    gauge = FloodEvent("Test River", "Invented Reach", 20, 16, 4, "2026-11-08", "invented-gauge")
    rain = PrecipExtremeEvent("multi_day_accumulation", "Invented Reach", "", "2026-11-08", 180, 3,
                             None, None, None, 0, 0, 1, ["Invented Reach"], "invented-rain")
    wave = ExtremeWaveEvent("Invented Coast", "Test Ocean", 11, "2026-11-08", "invented-wave")
    return [
        (build_river_flood_bundle(gauge).to_dict(), False),
        (build_river_flood_bundle(replace(gauge, source_leg="open_meteo_flood", discharge_m3s=900)).to_dict(), True),
        (build_precipitation_bundle(rain).to_dict(), False),
        (build_precipitation_bundle(replace(rain, source_leg="open_meteo")).to_dict(), True),
        (build_extreme_wave_bundle(wave).to_dict(), True),
    ]


@pytest.mark.parametrize("bundle,held", real_builder_cases())
def test_real_builders_forecast_fallbacks_preserve_observed_sources(bundle, held):
    assert scope.story_hold(bundle, observed_only=True) == (scope.HOLD if held else None)
    assert scope.story_hold({"review_context": {"two_bot": {"bundle": bundle}}}, observed_only=True) == (scope.HOLD if held else None)


@pytest.mark.parametrize("bundle,held", cases())
def test_structured_primary_evidence_not_prose(bundle, held):
    original = deepcopy(bundle)
    assert scope.story_hold(bundle, observed_only=True) == (scope.HOLD if held else None)
    assert bundle == original
    assert scope.story_hold(bundle, observed_only=False) is None
    retained = {"type": "other", "review_context": {"two_bot": {"bundle": bundle}}}
    assert scope.story_hold(retained, observed_only=True) == (scope.HOLD if held else None)


def test_javascript_and_python_hold_the_same_retained_and_live_evidence():
    root = Path(__file__).resolve().parents[1]
    payload = [value for value, _ in cases() + real_builder_cases()]
    values = payload + [{"type": "other", "review_context": {"two_bot": {"bundle": b}}} for b in payload]
    script = """import {observedWeatherHold} from './dashboard/lib/observed-weather.js';
    let raw=''; for await (const chunk of process.stdin) raw+=chunk;
    process.stdout.write(JSON.stringify(JSON.parse(raw).map(b=>observedWeatherHold(b,true))));"""
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=root,
                          input=json.dumps(values), text=True, capture_output=True, check=True, timeout=15)
    assert json.loads(done.stdout) == [scope.story_hold(row, observed_only=True) for row in values]


def test_scope_is_opt_in_and_has_no_hidden_fallback(monkeypatch):
    monkeypatch.delenv(scope.FLAG, raising=False)
    assert scope.story_hold({"type": "hot10"}) is None
    monkeypatch.setenv(scope.FLAG, "1")
    assert scope.story_hold({"type": "hot10"}) == scope.HOLD
    assert scope.story_hold(observation()) is None


def test_forecast_cannot_arm_even_when_legacy_forecast_opt_in_is_on(monkeypatch):
    from src.editorial.approval import recommend_approval_policy
    monkeypatch.setenv(scope.FLAG, "1")
    monkeypatch.setenv("THEHEAT_PM25_FORECAST_AUTO_TEXT", "1")
    for kind in scope.FORECAST_KINDS:
        policy = recommend_approval_policy(kind, signal_total=100, candidate_score={"total": 100})
        assert policy.mode == "manual_only" and not policy.can_auto_approve
    # Scope does not replace existing observed-record quality thresholds.
    assert recommend_approval_policy("monthly_high", signal_total=100,
                                     candidate_score={"total": 100}).can_auto_approve


def test_hot10_skips_before_fetch_or_writer_and_preserves_feedback(monkeypatch):
    from src.orchestrator import hot10
    monkeypatch.setenv(scope.FLAG, "1")
    def forbidden(*_a, **_kw):
        raise AssertionError("forecast acquisition or writer must not start")
    monkeypatch.setattr(hot10.open_meteo, "load_cities", forbidden)
    monkeypatch.setattr(hot10, "_enqueue_story_candidate", forbidden)
    calls = []
    monkeypatch.setattr(hot10, "_run_twitter_metrics", lambda *_: calls.append("metrics"))
    state, run = {"drafts": []}, {"id": "scope-test", "sources": []}
    assert hot10.run_leaderboard(state, run) is state
    assert state["drafts"] == [] and calls == ["metrics"]
    assert run["sources"][0]["status"] == "skipped"
    assert scope.HOLD in run["sources"][0]["note"]


def test_free_candidate_gate_does_not_spend_or_mark_an_event(monkeypatch):
    from src.orchestrator.draft_save import can_draft_candidate
    monkeypatch.setenv(scope.FLAG, "1")
    state = {"drafts": [], "writer_negative_cache": {"retained": "unchanged"}}
    before = deepcopy(state)
    candidate = SimpleNamespace(bundle={"signal_kind": "hot10"}, event_id="new")
    assert can_draft_candidate(state, candidate) == (False, "editorial_scope")
    assert state == before


def test_sender_refuses_forecast_and_preserves_unknown_delivery(monkeypatch):
    from src.orchestrator import posting
    monkeypatch.setenv(scope.FLAG, "1")
    monkeypatch.setattr(posting.state, "check_daily_cap", lambda *_: True)
    def forbidden(*_a, **_kw):
        raise AssertionError("no safety, source, upload or X call")
    monkeypatch.setattr(posting, "post_tweet", forbidden)
    draft = {"id": "invented", "type": "hot10", "text": "Invented forecast", "event_id": "invented",
             "approval_binding": {"mode": "auto"}, "status": "pending"}
    state = {"drafts": [draft], "publish_ledger": {"invented": {"phase": "unknown", "attempt": "retained"}}}
    before = deepcopy(state["publish_ledger"])
    assert posting.post_approved(draft, state) == "failed"
    assert scope.HOLD in draft["post_error"] and state["publish_ledger"] == before


@pytest.mark.parametrize("observed_only", [False, True])
def test_legacy_nhc_import_accepts_only_forecast_allowed_policy(observed_only):
    from scripts.nhc_advisory_import import validate_report, ImportRefused
    from tests.nhc_advisory_import_helpers import report, INVENTED_POLICY, CODE, SOURCE
    from tests.nhc_advisory_helpers import NOW
    policy = deepcopy(INVENTED_POLICY)
    policy["flags"]["observed_weather_only"] = observed_only
    raw = report(policy=policy)
    if observed_only:
        with pytest.raises(ImportRefused, match="policy_flags_changed"):
            validate_report(raw, NOW, CODE, SOURCE)
    else:
        assert validate_report(raw, NOW, CODE, SOURCE) == policy


def test_compact_related_object_retains_scope_markers():
    from src.two_bot.types import StoryBundle, RelatedSignal
    for kind, metric in (("wet_bulb_extreme", {"label": "daily_max_tw_c", "value": 34}),
                         ("extreme_wave", {"label": "wave_height_m", "value": 11}),
                         ("river_flood", {"label": "modeled_discharge_m3s", "value": 900}),
                         ("absolute_extreme", {"label": "max_c", "value": 42, "is_forecast": True})):
        bundle = StoryBundle(**{**observation(), "where": "Invented Reach", "when": "2026-11-08"})
        bundle.related_signals = [RelatedSignal("related", kind, "Invented Reach", "2026-11-08", metric)]
        assert scope.story_hold(bundle, observed_only=True) == scope.HOLD
        assert scope.story_hold(bundle.to_dict(), observed_only=True) == scope.HOLD
