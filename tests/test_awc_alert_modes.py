"""Ordinary production alert modes, with invented source/models/Gist/X only."""
from datetime import timedelta
from importlib import import_module

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from tests.test_awc_observed import NOW
from tests.test_awc_observed_automatic import COPY, sender
from tests.test_awc_observed_automatic import world as world


@pytest.fixture
def alerts(monkeypatch, world):
    module = import_module("src.orchestrator.run_alerts")
    # Leave the actual orchestrator, source owner, staged scheduler, queue,
    # writer/check/save gates and sender intact. No other provider is contacted.
    kept = {"run_alerts", "run_awc_observed", "run_stage1_then_synthesis"}
    for name in vars(module):
        if name.startswith("run_") and name not in kept:
            monkeypatch.setattr(module, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_process_cyclone_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.open_meteo, "load_cities", lambda: [])
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    # The workflow sets this nomination-only input to 0 on genuine schedules.
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    return module


@pytest.mark.parametrize("concurrent", [False, True], ids=["production-sequential", "concurrent"])
@pytest.mark.parametrize("triage", [False, True], ids=["legacy-drain", "production-triage"])
def test_ordinary_alerts_acquire_check_save_and_send_the_enabled_source_once(monkeypatch, world, alerts, concurrent, triage):
    transport, state, run, called, _ = world
    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1" if concurrent else "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    run.update(mode="alerts", id="invented-ordinary-airport-alerts")
    with freeze_time(NOW, tick=True):
        assert alerts.run_alerts(state, run) is state

    rows = [row for row in run["sources"] if row["source"] == "awc_observed"]
    assert len(rows) == 1, "Ordinary alerts must actually invoke the opted-in source in either mode"
    assert rows[0]["promoted"] == 1
    assert called == ["writer", "safety", "fact_check", "critic"]
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert draft["text"].startswith(COPY)
    assert draft["review_binding"]["kind"] == "model"
    assert draft["approval_binding"]["mode"] == "auto"
    assert len(transport.awc_calls) == 6
    sender(monkeypatch, world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    sender(monkeypatch, world, NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]


@pytest.mark.parametrize("concurrent", [False, True], ids=["production-sequential", "concurrent"])
@pytest.mark.parametrize("triage", [False, True], ids=["legacy-drain", "production-triage"])
def test_ordinary_alerts_keep_flag_off_without_source_or_model_calls(monkeypatch, world, alerts, concurrent, triage):
    transport, state, run, called, _ = world
    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1" if concurrent else "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    monkeypatch.setenv(source.ENABLE_FLAG, "0")
    run.update(mode="alerts", id="invented-disabled-airport-alerts")
    with freeze_time(NOW, tick=True):
        alerts.run_alerts(state, run)
    rows = [row for row in run["sources"] if row["source"] == "awc_observed"]
    assert len(rows) == 1 and rows[0]["status"] == "skipped"
    assert transport.awc_calls == [] and called == []
    assert state["drafts"] == [] and transport.x_posts == []
