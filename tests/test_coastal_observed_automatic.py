"""Invented NOAA bytes → actual checks/arming/Gist sender; no live model or X."""
from copy import deepcopy
from datetime import timedelta
import json
from urllib.parse import parse_qs, urlsplit

from freezegun import freeze_time
import pytest

from src.data import coastal_observed as source
from src.data import water_levels as wl
from src.orchestrator import posting
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.sources import co_ops
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.two_bot import pipeline
from src.voice import safety
from tests import live_content_harness as h
from tests.nhc_advisory_pipeline_helpers import stage_fakes
from tests.test_coastal_observed_provenance import NOW, STATION, payloads

COPY = "Invented Gauge stood 2.1 m above the predicted tide at 07:24 UTC on 13 Nov, NOAA’s preliminary reading shows."


class Transport(h.Transport):
    """Real query/HTTP/parser seams; the supplied bytes are explicitly invented."""

    def __init__(self):
        super().__init__()
        self.observed, self.predicted = payloads()
        self.coastal_calls = []
        self.failure = None
        self.before_reply = None
        self.intents_at_send = []

    def send(self, adapter, request, **options):
        parts = urlsplit(request.url)
        if f"{parts.scheme}://{parts.netloc}{parts.path}" != wl.COOPS_URL:
            if request.url == h.X_CREATE:
                saved = json.loads(self.gist["state.json"])
                self.intents_at_send.append(deepcopy(saved["publish_ledger"]))
            return super().send(adapter, request, **options)
        assert request.method == "GET"
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.coastal_calls.append(query)
        assert query["station"] == STATION[0]
        assert (query["datum"], query["time_zone"], query["units"]) == ("MLLW", "gmt", "metric")
        if self.before_reply:
            self.before_reply()
        if self.failure:
            return h._reply(request, self.failure, b'{"error":"invented source outage"}')
        key, payload = (("data", self.observed) if query["product"] == "water_level"
                        else ("predictions", self.predicted))
        body = deepcopy(payload)
        lo, hi = query["begin_date"], query["end_date"]
        body[key] = [row for row in body[key] if lo <= row["t"].replace("-", "") <= hi]
        return h._reply(request, 200, json.dumps(body).encode())


@pytest.fixture
def world(monkeypatch, fresh_state):
    for key, value in {
        "ANTHROPIC_API_KEY": "invented-no-access", "GEMINI_API_KEY": "invented-no-access",
        "THEHEAT_OBSERVED_WEATHER_ONLY": "1", "THEHEAT_CRITIC_ENABLED": "1",
        "THEHEAT_CRITIC_REVISE_ENABLED": "0", "THEHEAT_WRITER_SAMPLES": "1",
        "THEHEAT_TRIAGE_ENABLED": "0", "THEHEAT_REFILL_ENABLED": "0",
        "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS": "1",
        "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH": "invented-observed-epoch",
        "THEHEAT_PRODUCTION_PAUSED": "0", "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(wl, "STATIONS", [STATION])
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
    run = {"id": "invented-coastal-auto", "mode": "alerts", "sources": []}
    return transport, fresh_state, run, called, stages


def collect(world):
    transport, state, run, called, stages = world
    with freeze_time(NOW):
        co_ops.run_water_levels(state, run)
    return state["_triage_queue"][0].bundle


def drain(world):
    _, state, run, _, _ = world
    budget = CandidateBudget(operation="alerts", limit=1)
    with freeze_time(NOW, tick=True):
        _drain_and_write_triage_queue(state, run, candidate_budget=budget)
    return budget


def sender(monkeypatch, world, *, at=NOW + timedelta(minutes=2)):
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


def test_actual_observation_pipeline_arms_sends_once_and_retains_exact_source(monkeypatch, world):
    transport, state, run, called, _ = world
    bundle = collect(world)
    assert bundle.signal_kind == source.KIND and bundle.when == "2026-11-13T07:24:00Z"
    assert run["sources"][0]["promoted"] == 1
    assert len(transport.coastal_calls) == 4  # discovery pair, then exact-point pair
    before = deepcopy(bundle.to_dict())
    drain(world)
    assert called == ["writer", "safety", "fact_check", "critic"], state.get("suppressions")
    assert len(state["drafts"]) == 1
    draft = state["drafts"][0]
    assert len(draft["text"]) <= 200 and draft["text"] == COPY + "\n" + source.citation(STATION[0])
    assert draft["review_binding"]["kind"] == "model"
    assert draft["approval_binding"]["mode"] == "auto" and draft["auto_approve_at"]
    assert draft["review_context"]["two_bot"]["bundle"] == before
    assert len(transport.coastal_calls) == 8  # before writer and before admission
    sender(monkeypatch, world)
    assert transport.x_posts == [draft["text"]]
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    assert transport.gist_patches == 1  # The normal caller saves the final outcome later.
    assert transport.intents_at_send[0][draft["event_id"]]["phase"] == "submitted"
    sender(monkeypatch, world, at=NOW + timedelta(minutes=4))
    assert len(transport.x_posts) == 1
    with freeze_time(NOW + timedelta(minutes=4)):
        co_ops.run_water_levels(state, run)
    assert not state.get("_triage_queue") and len(called) == 5  # one final safety check only


@pytest.mark.parametrize("change", ["changed-value", "404", "qc", "wrong-station", "newer-sample"])
def test_source_change_before_writer_never_buys_a_draft(world, change):
    transport, state, _, called, _ = world
    collect(world)
    if change == "changed-value":
        transport.observed["data"][-1]["v"] = "3.2"
    elif change == "404":
        transport.failure = 404
    elif change == "qc":
        transport.observed["data"][-1]["f"] = "0,1,0,0"
    elif change == "wrong-station":
        transport.observed["metadata"]["id"] = "wrong"
    else:
        # Original point disappears. A newer observation cannot replace its proof.
        transport.observed["data"][-1]["t"] = "2026-11-13 07:30"
    drain(world)
    assert called == [] and state["drafts"] == []


def test_correction_after_checks_blocks_admission_without_rerunning_models(monkeypatch, world):
    transport, state, _, called, stages = world
    collect(world)
    def critic(*args, **kwargs):
        result = stages[3](*args, **kwargs)
        transport.observed["data"][-1]["v"] = "3.2"
        return result
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    drain(world)
    assert called == ["writer", "safety", "fact_check", "critic"]
    assert state["drafts"] == [] and transport.x_posts == []


@pytest.mark.parametrize("change", ["corrected", "404", "expired", "mode-off", "pause", "epoch"])
def test_changed_or_ineligible_queued_draft_does_not_buy_final_safety_or_send(monkeypatch, world, change):
    transport, state, _, called, _ = world
    collect(world)
    drain(world)
    assert len(state["drafts"]) == 1
    at = NOW + timedelta(minutes=2)
    if change == "corrected":
        transport.observed["data"][-1]["v"] = "3.2"
    elif change == "404":
        transport.failure = 404
    elif change == "expired":
        at = NOW + timedelta(hours=6)
    else:
        monkeypatch.setenv({"mode-off": "THEHEAT_OBSERVED_WEATHER_ONLY",
                            "pause": "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED",
                            "epoch": "THEHEAT_AUTOMATIC_PUBLICATION_EPOCH"}[change],
                           "different-epoch" if change == "epoch" else "0")
    sender(monkeypatch, world, at=at)
    assert transport.x_posts == [] and len(called) == 4
    assert state["drafts"][0]["status"] != "posted"


def test_unknown_x_delivery_is_never_resent(monkeypatch, world):
    transport, state, _, _, _ = world
    collect(world)
    drain(world)
    transport.x_failure = "create_lost"
    sender(monkeypatch, world)
    assert len(transport.x_posts) == 1 and state["drafts"][0]["status"] != "posted"
    transport.x_failure = None
    sender(monkeypatch, world, at=NOW + timedelta(minutes=4))
    assert len(transport.x_posts) == 1


@pytest.mark.parametrize("kind", ["draft", "posted", "unknown"])
def test_legacy_station_day_identity_blocks_new_automatic_nomination(world, kind):
    transport, state, run, called, _ = world
    old = "surge_major_8518750_2026-11-13"
    if kind == "draft":
        state["drafts"].append({"event_id": old, "status": "pending"})
    elif kind == "posted":
        state["posted_events"].append(old)
    else:
        state["publish_ledger"][old] = {"phase": "unknown"}
    with freeze_time(NOW):
        co_ops.run_water_levels(state, run)
    assert not state.get("_triage_queue") and called == []
    assert len(transport.coastal_calls) == 2  # aliases held before new source acquisition


@pytest.mark.parametrize("change,reason", [
    ("preliminary", "coastal_preliminary_label_missing"),
    ("clock", "coastal_clock_label_missing"), ("date", "coastal_date_label_missing"),
    ("station", "coastal_station_label_missing"), ("flood", "coastal_unsupported_impact_or_record"),
    ("comparison", "coastal_comparison_label_missing"),
])
def test_unsupported_copy_cannot_reuse_checked_source(world, change, reason):
    bundle = collect(world)
    text = COPY.replace({"preliminary": "preliminary ", "clock": "07:24 UTC", "date": "13 Nov",
                         "station": "Invented Gauge", "comparison": "predicted tide", "flood": "stood"}[change],
                        "flooded" if change == "flood" else "removed")
    with freeze_time(NOW):
        assert source.claim_failures(text, bundle) == [reason]


def test_static_expiry_holds_before_source_refresh_and_paid_selection(world):
    transport, state, run, called, _ = world
    collect(world)
    count = len(transport.coastal_calls)
    with freeze_time(NOW + timedelta(hours=6)):
        _drain_and_write_triage_queue(state, run, candidate_budget=CandidateBudget(operation="alerts", limit=1))
    assert called == [] and state["drafts"] == [] and len(transport.coastal_calls) == count
    assert any(row.get("stage") == "coastal_source" for row in state.get("suppressions", []))


def test_failed_critic_never_gains_automatic_authority(monkeypatch, world):
    from src.two_bot.types import CriticResult
    _, state, _, called, _ = world
    collect(world)
    monkeypatch.setattr(pipeline.critic, "critic_review", lambda *_a, **_kw: CriticResult(False, "held", "offline refusal"))
    drain(world)
    assert not state["drafts"] or not state["drafts"][0].get("auto_approve_at")
    assert called[:3] == ["writer", "safety", "fact_check"]


def test_faithful_overlong_copy_is_never_shortened_into_automatic_authority(monkeypatch, world):
    from src.two_bot.types import WriterResult
    _, state, _, _, _ = world
    collect(world)
    overlong = COPY + " This is an explicitly invented additional sentence that must not buy an automatic length waiver."
    monkeypatch.setattr(pipeline.writer, "write_tweet", lambda *_a, **_kw: WriterResult(
        overlong, None, "observed_comparison", None, None, "offline length case"))
    drain(world)
    assert not state["drafts"] or not state["drafts"][0].get("auto_approve_at")
    if state["drafts"]:
        assert overlong in state["drafts"][0]["text"]


@pytest.mark.parametrize("change", ["kind", "identity", "metric", "url", "query", "hash"])
def test_retained_contract_tampering_never_reaches_paid_selection(world, change):
    transport, state, _, called, _ = world
    bundle = collect(world)
    if change == "kind":
        bundle.signal_kind = "absolute_extreme"
    elif change == "identity":
        bundle.event_id = "coastal_report_0000000_2026-11-13"
    elif change == "metric":
        bundle.headline_metric["value"] = 50
    elif change == "url":
        next(f for f in bundle.current_facts if f["label"] == "public_source_url")["value"] = "https://example.test"
    elif change == "query":
        bundle.raw_signal_dump["evidence"]["source_requests"]["observation_query"] += "&station=0000000"
    else:
        bundle.raw_signal_dump["evidence"]["observed_response_sha256"] = "not-a-hash"
    before = len(transport.coastal_calls)
    drain(world)
    assert called == [] and state["drafts"] == []
    assert len(transport.coastal_calls) == before


def test_expiry_during_actual_source_read_cannot_reuse_entry_clock(world):
    transport, _, _, _, _ = world
    bundle = collect(world)
    with freeze_time(NOW) as clock:
        transport.before_reply = lambda: clock.tick(timedelta(hours=3))
        assert source.current_bundle_hold(bundle, live=True) is not None


def test_source_change_after_durable_intent_still_prevents_x(monkeypatch, world):
    transport, state, _, called, _ = world
    collect(world)
    drain(world)
    def correct_after_intent():
        if transport.gist_patches:
            transport.observed["data"][-1]["v"] = "3.2"
    transport.before_reply = correct_after_intent
    sender(monkeypatch, world)
    assert transport.x_posts == [] and len(called) == 5
    draft = state["drafts"][0]
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "not_sent"


def test_autoship_off_cannot_fall_through_to_policy_only_sending(monkeypatch, world):
    transport, state, _, _, _ = world
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    collect(world)
    drain(world)
    assert len(state["drafts"]) == 1
    assert not state["drafts"][0].get("auto_approve_at")
    sender(monkeypatch, world)
    assert transport.x_posts == []


@pytest.mark.parametrize("boundary", ["admission", "queued", "after-intent"])
@pytest.mark.parametrize("evidence", ["posted", "unknown", "pending"])
def test_legacy_station_day_arrival_at_each_boundary_prevents_send(monkeypatch, world, boundary, evidence):
    transport, state, _, called, stages = world
    collect(world)
    def arrive():
        old = "surge_major_8518750_2026-11-13"
        if evidence == "posted":
            state["posted_events"].append(old)
        elif evidence == "unknown":
            state["publish_ledger"][old] = {"phase": "unknown", "at": "invented"}
        else:
            state["drafts"].append({"event_id": old, "status": "pending"})
    if boundary == "admission":
        def critic(*args, **kwargs):
            result = stages[3](*args, **kwargs)
            arrive()
            return result
        monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    drain(world)
    if boundary == "admission":
        assert not any(d.get("type") == source.KIND for d in state["drafts"])
    else:
        assert len(state["drafts"]) == 1
        if boundary == "queued":
            arrive()
        else:
            transport.before_reply = lambda: arrive() if transport.gist_patches else None
        sender(monkeypatch, world)
        assert len(called) == (4 if boundary == "queued" else 5)
    assert transport.x_posts == []


def test_new_family_always_uses_one_sample_and_disables_revision(monkeypatch, world):
    _, _, _, called, stages = world
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "1")
    requested = []
    original = pipeline._writer_sample_slate
    def slate(bundle, memory, samples):
        requested.append(samples)
        assert samples == 1, "the offline trial must not enter an unbudgeted slate"
        return original(bundle, memory, samples)
    monkeypatch.setattr(pipeline, "_writer_sample_slate", slate)
    collect(world)
    drain(world)
    assert called == ["writer", "safety", "fact_check", "critic"]
    assert requested == [1]
    assert stages[3].call_args.kwargs["allow_revise"] is False
