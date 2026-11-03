"""Invented forecast disclaimers; negative wording never supplies a measurement."""
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from src.two_bot.scientific_claims import scientific_claim_failures
from tests import live_content_harness as h
from tests.two_bot.test_short_content_contract import _forecast_bundle


@pytest.mark.parametrize("text", [
    "Port Example is forecast to reach 47°C; not observed.",
    "Port Example is forecast to reach 47°C (forecast, not observed).",
    "Port Example is forecast to reach 47°C (not observed).",
    "Port Example's forecast high is 47°C, not observed.",
    "Port Example’s forecast high is 47°C; not observed",
])
def test_complete_immediate_denial_is_not_an_affirmative_observation(text):
    assert scientific_claim_failures(text, _forecast_bundle()) == []


@pytest.mark.parametrize("text", [
    "Port Example's forecast is 47°C. Observed at 47°C.",
    "Port Example's forecast is 47°C; not observed. It was measured at 47°C.",
    "Port Example's forecast is 47°C (not observed); a station recorded 47°C.",
    "Port Example's forecast is 47°C; not observed, but measured at 47°C.",
    "Port Example's forecast is 47°C; not observed until a station measured 47°C.",
    "Port Example's forecast is 47°C; not not observed.",
    "Port Example's forecast is 47°C; not (not observed).",
    "Port Example's forecast is 47°C; it is false (not observed).",
    "Port Example's forecast is 47°C; not (forecast, not observed).",
    "Port Example's forecast is 47°C ('not observed').",
    'Port Example is forecast to reach 47°C ("not observed").',
    "Port Example is forecast to reach 47°C (‘not observed’).",
    "Port Example's forecast is 47°C; (not observed) is false.",
    "Port Example is forecast to reach 47°C, (not observed) is a false label.",
    "Port Example is forecast to reach 47°C; not observed\nbut a station recorded 47°C.",
])
def test_denial_never_excuses_a_quote_or_affirmative_measurement_elsewhere(text):
    assert any(error.startswith("forecast_as_observation")
               for error in scientific_claim_failures(text, _forecast_bundle()))


@pytest.mark.parametrize("outcome", ["pass", "fact_failure", "safety_failure", "critic_failure", "missing_fact"])
def test_disclaimer_still_requires_every_pipeline_check(tmp_path, monkeypatch, outcome):
    from freezegun import freeze_time
    from src.orchestrator import hot10
    from src.state import DEFAULT_STATE

    h.trap_network(monkeypatch.setattr)
    text = ("Riyadh's forecast high is 39.2°C, 9.2°C above its October normal among 14 sampled cities "
            "(forecast, not observed).")
    world = h.install_hot10_world(tmp_path, monkeypatch, copy=text)
    if outcome == "fact_failure":
        world.script.fact_passed = False
    elif outcome == "safety_failure":
        world.script.safety = "YES"
    elif outcome == "critic_failure":
        world.script.critic = {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                               "selected_index": None}
    elif outcome == "missing_fact":
        original = world.script.google_text

        def missing(request):
            stage, response = original(request)
            if stage == "fact_check":
                raise RuntimeError("invented missing required response")
            return stage, response

        monkeypatch.setattr(world.script, "google_text", missing)
    state = deepcopy(DEFAULT_STATE)
    with freeze_time(datetime(2026, 10, 29, 9, tzinfo=UTC), tick=True):
        hot10.run_leaderboard(state, {"id": "invented-forecast-denial", "sources": []})
    if outcome == "pass":
        assert world.script.stages() == ["writer", "safety", "fact_check", "critic"]
        assert len(state["drafts"]) == 1 and state["drafts"][0]["status"] == "pending"
    else:
        assert state["drafts"] == []
    assert world.script.stages().count("writer") == 1
    assert len(world.settled) == 1 and world.settled[0][2] is True
    assert world.transport.x_posts == []
