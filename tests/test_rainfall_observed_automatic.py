"""Invented NASA bytes → ordinary collection/checks/Gist/X fixture only."""
from copy import deepcopy
from datetime import timedelta
from importlib import import_module
import json

from freezegun import freeze_time
import pytest

from src.data import gpm_imerg as gpm, rainfall_observed as report
from src.orchestrator import posting
from src.two_bot import pipeline
from src.voice import safety
from tests import live_content_harness as h
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_gpm_imerg import _make_grid_bytes
from tests.test_rainfall_observed_report import NOW, TEXT


class Transport(h.Transport):
    def __init__(self, row):
        super().__init__()
        self.row = row
        self.rows = [row]
        self.amount = 180.5
        self.failure = None
        self.on_request = None
        self.calls = []
        self.intents_at_send = []

    def send(self, adapter, request, **options):
        if not request.url.startswith(gpm.DATAPOOL_BASE):
            if request.url == h.X_CREATE:
                self.intents_at_send.append(deepcopy(json.loads(self.gist["state.json"])["publish_ledger"]))
            return super().send(adapter, request, **options)
        assert request.method == "GET"
        assert request.url == gpm.DATAPOOL_BASE + "/" + gpm._imerg_relpath("late", NOW.date() - timedelta(days=1))
        self.calls.append(request.url)
        if self.on_request:
            self.on_request(len(self.calls))
        if self.failure:
            return h._reply(request, self.failure, b"invented unavailable NASA file")
        cells = {(0, gpm._lon_index(float(row["lon"])), gpm._lat_index(float(row["lat"]))): self.amount
                 for row in self.rows}
        return h._reply(request, 200, _make_grid_bytes(cells))


@pytest.fixture
def world(monkeypatch, fresh_state):
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access", "GEMINI_API_KEY": "invented-no-access",
        "EARTHDATA_TOKEN": "invented-no-access", report.ENABLE_FLAG: "1",
        "THEHEAT_GPM_SOURCE": "datapool", "THEHEAT_OBSERVED_WEATHER_ONLY": "1",
        "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_REFILL_ENABLED": "0",
        "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "0",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-rainfall-epoch", "THEHEAT_PRODUCTION_PAUSED": "0",
        "GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    row = next(x for x in gpm.load_cities() if x["city"] == "Paris" and x["country"] == "France")
    transport = Transport(row)
    transport.install(monkeypatch.setattr)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-no-access")
    called = []
    stages = stage_fakes(called, copy=TEXT.split("\n")[0])
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    module = import_module("src.orchestrator.run_alerts")
    kept = {"run_alerts", "run_gpm_imerg", "run_stage1_then_synthesis"}
    for name in vars(module):
        if name.startswith("run_") and name not in kept:
            monkeypatch.setattr(module, name, lambda *a, **kw: None)
    monkeypatch.setattr(module, "_process_cyclone_source", lambda *a, **kw: None)
    monkeypatch.setattr(module.open_meteo, "load_cities", lambda: transport.rows)
    return transport, fresh_state, {"id": "invented-ordinary-rainfall", "mode": "alerts", "sources": []}, called, stages, module


def collect(world):
    _, state, run, _, _, module = world
    with freeze_time(NOW, tick=True):
        return module.run_alerts(state, run)


def send(monkeypatch, world, at=NOW + timedelta(minutes=2)):
    from src.posting import twitter
    transport, state, _, _, _, _ = world
    transport.gist = {"state.json": json.dumps(state)}
    monkeypatch.setattr("src.state.GIST_ID", h.GIST_ID)
    monkeypatch.setattr("src.state.GITHUB_TOKEN", "invented-no-access")
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(twitter, key, "invented-no-access")
    monkeypatch.setattr(posting, "run_safety_pipeline", safety.run_safety_pipeline)
    with freeze_time(at, tick=True):
        posting.process_due_drafts(state, {"sources": []})


@pytest.mark.parametrize("concurrent", [False, True])
@pytest.mark.parametrize("triage", [False, True])
def test_real_ordinary_modes_check_save_and_send_once(monkeypatch, world, concurrent, triage):
    transport, state, run, called, _, _ = world
    monkeypatch.setenv("THEHEAT_CONCURRENT_SOURCES", "1" if concurrent else "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    assert collect(world) is state
    assert called == ["writer", "safety", "fact_check", "critic"], json.dumps(state.get("suppressions"), ensure_ascii=False)
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert draft["text"] == TEXT and len(draft["text"]) <= 200
    assert draft["type"] == report.KIND
    assert draft["approval_binding"]["mode"] == "auto"
    assert draft["review_binding"]["kind"] == "model"
    assert len(transport.calls) == 3
    send(monkeypatch, world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert transport.intents_at_send[0][draft["event_id"]]["phase"] == "submitted"
    send(monkeypatch, world, NOW + timedelta(minutes=4))
    assert transport.x_posts == [TEXT]


@pytest.mark.parametrize("triage", [False, True])
def test_three_qualified_points_never_buy_a_replacement_after_paid_failure(monkeypatch, world, triage):
    transport, state, _, called, _, _ = world
    transport.rows = [next(row for row in gpm.load_cities() if row["city"] == name)
                      for name in ("Paris", "Tokyo", "London")]
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    # This explicit writer failure consumes the operation's single attempt.
    # The lower-level model fixture still goes through the provider boundary.
    original = pipeline.writer.write_tweet
    def failed(*args, **kwargs):
        from src.two_bot.types import WriterResult
        original(*args, **kwargs)
        return WriterResult(None, "invented style refusal", "", None, None, "offline fixture")
    monkeypatch.setattr(pipeline.writer, "write_tweet", failed)
    collect(world)
    assert called == ["writer"]
    assert state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("boundary", ["before-writer", "before-admission", "before-send"])
def test_actual_source_change_refuses_at_each_consequential_boundary(monkeypatch, world, boundary):
    transport, state, _, called, _, _ = world
    if boundary == "before-writer":
        transport.on_request = lambda n: setattr(transport, "amount", 181) if n == 2 else None
    elif boundary == "before-admission":
        transport.on_request = lambda n: setattr(transport, "amount", 181) if n == 3 else None
    collect(world)
    if boundary == "before-send":
        assert len(state["drafts"]) == 1
        transport.amount = 181
        send(monkeypatch, world)
        assert state["drafts"][0]["status"] != "posted"
    else:
        assert state["drafts"] == []
    assert called == ([] if boundary == "before-writer" else ["writer", "safety", "fact_check", "critic"])
    assert transport.x_posts == []


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_required_model_refusal_never_saves_or_sends(monkeypatch, world, stage):
    from src.two_bot.types import CriticResult, FactCheckResult
    transport, state, _, called, stages, _ = world
    index = {"safety": 1, "fact_check": 2, "critic": 3}[stage]
    def refuse(*args, **kwargs):
        stages[index](*args, **kwargs)
        return ((False, "invented required safety refusal") if stage == "safety" else
                FactCheckResult(False, ["invented unsupported claim"], "offline") if stage == "fact_check" else
                CriticResult(False, "weak_signal", "offline"))
    target, name = ((safety, "check_llm") if stage == "safety" else
                    (pipeline.fact_check, "fact_check") if stage == "fact_check" else
                    (pipeline.critic, "critic_review"))
    monkeypatch.setattr(target, name, refuse)
    collect(world)
    assert stage in called and called.count("writer") == 1
    assert state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("change", ["text", "kind", "event", "flag", "checks", "expired", "unknown-send"])
def test_stale_edited_or_unapproved_draft_never_sends(monkeypatch, world, change):
    transport, state, _, _, _, _ = world
    collect(world)
    draft, = state["drafts"]
    at = NOW + timedelta(minutes=2)
    if change == "text":
        draft["text"] = draft["text"].replace("180.5", "190")
    elif change == "kind":
        draft["type"] = "all_time_high"
    elif change == "event":
        draft["event_id"] = "foreign-rainfall-event"
    elif change == "flag":
        monkeypatch.setenv(report.ENABLE_FLAG, "0")
    elif change == "checks":
        draft.pop("review_binding")
    elif change == "expired":
        at = NOW + timedelta(hours=21)
    else:
        state["publish_ledger"][draft["event_id"]] = {"phase": "submitted", "submitted_at": NOW.isoformat()}
    send(monkeypatch, world, at)
    assert transport.x_posts == [] and draft["status"] != "posted"


def test_retired_release_epoch_stops_before_any_writer_attempt(world):
    transport, state, _, called, _, _ = world
    state["publication_control"] = {"retired_epochs": ["invented-rainfall-epoch"]}
    collect(world)
    assert called == [] and state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("boundary", ["before-writer", "before-admission"])
def test_retirement_after_nomination_never_buys_manual_copy_or_saves_it(monkeypatch, world, boundary):
    transport, state, _, called, stages, module = world
    def retire():
        state["publication_control"] = {"retired_epochs": ["invented-rainfall-epoch"]}
    if boundary == "before-writer":
        real = module._drain_and_write_triage_queue
        def drain(*args, **kwargs):
            retire()
            return real(*args, **kwargs)
        monkeypatch.setattr(module, "_drain_and_write_triage_queue", drain)
    else:
        def critic(*args, **kwargs):
            result = stages[3](*args, **kwargs)
            retire()
            return result
        monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    collect(world)
    assert called == ([] if boundary == "before-writer" else ["writer", "safety", "fact_check", "critic"])
    assert state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("flag", [report.ENABLE_FLAG, "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED",
                                 "THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "THEHEAT_CRITIC_ENABLED"])
def test_ordinary_disabled_profile_does_not_buy_manual_only_copy(monkeypatch, world, flag):
    transport, state, _, called, _, _ = world
    monkeypatch.setenv(flag, "0")
    collect(world)
    assert called == [] and state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("country_named", [False, True])
def test_country_context_is_real_before_automatic_admission(monkeypatch, world, country_named):
    transport, state, _, called, _, _ = world
    transport.rows = [next(row for row in gpm.load_cities() if row["city"] == "Ahmedabad")]
    place = "Ahmedabad, India" if country_named else "Ahmedabad"
    body = TEXT.split("\n")[0].replace("Paris, France", place)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stage_fakes(called, copy=body)[0])
    collect(world)
    if country_named:
        draft, = state["drafts"]
        assert called == ["writer", "safety", "fact_check", "critic"]
        assert draft["approval_binding"]["mode"] == "auto"
        assert draft["text"] == body + "\n" + report.SOURCE_URL
    else:
        assert called == ["writer"] and state["drafts"] == []
    assert transport.x_posts == []
