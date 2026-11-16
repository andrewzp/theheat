"""Invented bytes through the real parser, writer gates, Gist intent and sender.

All four model responses and every HTTP reply are explicit offline fixtures.
This exercises integration and refusals, never live-model quality or X delivery.
"""
from copy import deepcopy
from datetime import timedelta
import gzip
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.orchestrator import posting
from src.orchestrator.metar_report import run_metar_report
from src.two_bot import pipeline
from src.voice import safety
from tests import live_content_harness as h
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_awc_observed import NOW, TARGET, catalog, csv_bytes, history_xml, reports

COPY = "At 12:00 UTC Nov 15, North Test airport, Norway, recorded −20°C; South Test airport, Chile, 45°C—a 65°C gap."


class Transport(h.Transport):
    def __init__(self):
        super().__init__()
        self.rows, self.stations = reports(), catalog()
        self.awc_calls = []
        self.failure = None
        self.on_reply = None
        self.intents_at_send = []

    def send(self, adapter, request, **options):
        parts = urlsplit(request.url)
        url = f"{parts.scheme}://{parts.netloc}{parts.path}"
        if url not in (source.METARS_URL, source.STATIONS_URL, source.HISTORY_URL):
            if request.url == h.X_CREATE:
                self.intents_at_send.append(deepcopy(json.loads(self.gist["state.json"])["publish_ledger"]))
            return super().send(adapter, request, **options)
        assert request.method == "GET" and options["stream"] is True
        query = {key: value[0] for key, value in parse_qs(parts.query).items()}
        if url == source.HISTORY_URL:
            assert query == {"ids": "TAAA,TBBB", "format": "xml", "taf": "false", "hours": "2", "date": TARGET}
        else:
            assert query == {}
        self.awc_calls.append((url, query))
        if self.on_reply:
            self.on_reply()
        if self.failure:
            return h._reply(request, self.failure, b"invented source unavailable")
        body = (gzip.compress(csv_bytes(self.rows), mtime=0) if url == source.METARS_URL else
                gzip.compress(json.dumps(self.stations).encode(), mtime=0) if url == source.STATIONS_URL
                else history_xml(self.rows))
        return h._reply(request, 200, body)


@pytest.fixture
def world(monkeypatch, fresh_state):
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access", "GEMINI_API_KEY": "invented-no-access",
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1", "THEHEAT_AWC_OBSERVED_CONTRAST": "1",
        "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
        "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_TRIAGE_ENABLED": "0", "THEHEAT_REFILL_ENABLED": "0",
        "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-airport-epoch", "THEHEAT_PRODUCTION_PAUSED": "0",
        "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-no-access")
    transport = Transport()
    transport.install(monkeypatch.setattr)
    called = []
    stages = stage_fakes(called, copy=COPY)
    monkeypatch.setattr(pipeline.writer, "write_tweet", stages[0])
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety.run_safety_pipeline)
    monkeypatch.setattr(safety, "check_llm", stages[1])
    monkeypatch.setattr(pipeline.fact_check, "fact_check", stages[2])
    monkeypatch.setattr(pipeline.critic, "critic_review", stages[3])
    return transport, fresh_state, {"id": "invented-airport-run", "mode": "metar_report", "sources": []}, called, stages


def generate(world):
    _, state, run, _, _ = world
    with freeze_time(NOW, tick=True):
        run_metar_report(state, run)


def sender(monkeypatch, world, at=NOW + timedelta(minutes=2)):
    from src.posting import twitter
    transport, state, _, _, _ = world
    transport.gist = {"state.json": json.dumps(state)}
    monkeypatch.setattr("src.state.GIST_ID", h.GIST_ID)
    monkeypatch.setattr("src.state.GITHUB_TOKEN", "invented-no-access")
    for key in ("API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_SECRET"):
        monkeypatch.setattr(twitter, key, "invented-no-access")
    monkeypatch.setattr(posting, "run_safety_pipeline", safety.run_safety_pipeline)
    with freeze_time(at, tick=True):
        posting.process_due_drafts(state, {"sources": []})


def test_fixed_http_transport_reaches_the_actual_parsers(world):
    transport, _, _, called, _ = world
    with freeze_time(NOW):
        evidence = source.nominate()
    assert evidence["difference_c"] == 65
    assert len(transport.awc_calls) == 2 and called == []


def test_observed_pair_through_all_required_checks_arms_and_sends_once(monkeypatch, world):
    transport, state, run, called, _ = world
    generate(world)
    assert called == ["writer", "safety", "fact_check", "critic"], {"run": run, "holds": state.get("suppressions")}
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert draft["text"] == COPY + "\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert len(draft["text"]) <= 200
    assert draft["review_binding"]["kind"] == "model" and draft["approval_binding"]["mode"] == "auto"
    assert len(transport.awc_calls) == 6  # nominate, before writer, before admission
    assert run["sources"][0]["promoted"] == 1
    sender(monkeypatch, world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert transport.intents_at_send[0][draft["event_id"]]["phase"] == "submitted"
    assert transport.x_posts == [draft["text"]]
    sender(monkeypatch, world, NOW + timedelta(minutes=4))
    assert len(transport.x_posts) == 1
    generate(world)
    assert len(state["drafts"]) == 1 and called == ["writer", "safety", "fact_check", "critic", "safety"]


@pytest.mark.parametrize("key,value", [
    (source.ENABLE_FLAG, "0"), ("THEHEAT_OBSERVED_WEATHER_ONLY", "0"),
    ("THEHEAT_CRITIC_ENABLED", "0"), ("THEHEAT_PRODUCTION_PAUSED", "1"),
    ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2"), ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "0"),
    ("THEHEAT_WRITER_SAMPLES", "3"), ("THEHEAT_REFILL_ENABLED", "1"),
    ("THEHEAT_CRITIC_REVISE_ENABLED", "1"), ("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0"),
    ("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REF", "refs/tags/main"),
    ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0"), ("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0"),
])
def test_invalid_nomination_settings_stop_before_source_and_models(monkeypatch, world, key, value):
    transport, state, _, called, _ = world
    monkeypatch.setenv(key, value)
    generate(world)
    assert transport.awc_calls == [] and called == [] and state["drafts"] == []


@pytest.mark.parametrize("boundary", ["before-writer", "after-checks", "before-sender"])
def test_source_correction_holds_at_every_live_boundary(monkeypatch, world, boundary):
    transport, state, _, called, stages = world
    def change():
        transport.rows[0][0] = transport.rows[0][0].replace("M20/M25", "M21/M25")
        transport.rows[0][5] = "-21"
    if boundary == "before-writer":
        def before_read():
            if len(transport.awc_calls) == 3:
                change()
        transport.on_reply = before_read
    elif boundary == "after-checks":
        def critic(*args, **kwargs):
            result = stages[3](*args, **kwargs)
            change()
            return result
        monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    generate(world)
    if boundary == "before-sender":
        assert len(state["drafts"]) == 1
        change()
        sender(monkeypatch, world)
        assert state["drafts"][0]["status"] != "posted"
    else:
        assert state["drafts"] == []
    assert called == ([] if boundary == "before-writer" else ["writer", "safety", "fact_check", "critic"])
    assert transport.x_posts == []


@pytest.mark.parametrize("change", ["text", "kind", "event", "flag", "checks", "expired", "unknown-send"])
def test_edited_expired_or_unapproved_target_cannot_send(monkeypatch, world, change):
    transport, state, _, _, _ = world
    generate(world)
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    at = NOW + timedelta(minutes=2)
    if change == "text":
        draft["text"] = draft["text"].replace("−20°C", "−30°C")
    elif change == "kind":
        draft["type"] = "all_time_high"
    elif change == "event":
        draft["event_id"] = "other"
    elif change == "flag":
        monkeypatch.setenv(source.ENABLE_FLAG, "0")
    elif change == "checks":
        draft.pop("review_binding")
    elif change == "expired":
        at = NOW + timedelta(hours=2)
    else:
        state["publish_ledger"][draft["event_id"]] = {"phase": "submitted", "submitted_at": NOW.isoformat()}
    sender(monkeypatch, world, at)
    assert transport.x_posts == [] and draft["status"] != "posted"


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_any_failed_required_model_check_keeps_the_output_unapproved(monkeypatch, world, stage):
    from src.two_bot.types import FactCheckResult, CriticResult
    transport, state, _, called, stages = world
    index = {"safety": 1, "fact_check": 2, "critic": 3}[stage]
    def refuse(*args, **kwargs):
        stages[index](*args, **kwargs)
        if stage == "safety":
            return False, "invented required-check refusal"
        if stage == "fact_check":
            return FactCheckResult(False, ["invented unsupported claim"], "offline fixture")
        return CriticResult(False, "weak_signal", "offline fixture")
    if stage == "safety":
        monkeypatch.setattr(safety, "check_llm", refuse)
    elif stage == "fact_check":
        monkeypatch.setattr(pipeline.fact_check, "fact_check", refuse)
    else:
        monkeypatch.setattr(pipeline.critic, "critic_review", refuse)
    generate(world)
    assert stage in called and state["drafts"] == [] and transport.x_posts == []
    assert called.count("writer") == 1


@pytest.mark.parametrize("flag", ["THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS"])
def test_nominated_automatic_intent_never_buys_manual_only_copy(monkeypatch, world, flag):
    transport, state, _, called, _ = world
    monkeypatch.setenv(flag, "0")
    generate(world)
    assert called == [] and state["drafts"] == [] and transport.x_posts == []
