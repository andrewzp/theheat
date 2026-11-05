"""Invented warnings through real admission, selection and provider-attempt spies."""
from dataclasses import replace
from copy import deepcopy
import json
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
import pytest

from src.commands.schema import utc_text
from src.data.nws_alerts import SevereWeatherAlert
from src.media.published_radar import source_envelope
from src.orchestrator import funnel, nws_publication, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.common import _review_context
from src.two_bot.intern import build_severe_weather_bundle
from tests import test_scheduled_automatic_preflight as scheduled
from tests.test_nws_alerts import _typhoon_feature

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch):
    with freeze_time(NOW):
        spy = scheduled.world.__wrapped__(monkeypatch)
        monkeypatch.setenv("THEHEAT_NWS_WARNING_AUTO_TEXT", "1")
        monkeypatch.setattr(nws_publication, "_clock", lambda: NOW)
        yield spy


def add_warning(state, condition):
    source = _typhoon_feature()
    props = source["properties"]
    end = {"expired": -1, "short": 29, "exact": 30, "valid": 120,
           "future": 120, "forecast_onset": 120, "just_enough": 30, "event_short": 120}[condition]
    props["expires"] = (NOW + timedelta(minutes=end, microseconds=1 if condition == "just_enough" else 0)).isoformat()
    if condition == "future":
        props["sent"] = props["effective"] = props["onset"] = (NOW + timedelta(minutes=1)).isoformat()
    elif condition == "forecast_onset":
        props["onset"] = (NOW + timedelta(hours=4)).isoformat()
    elif condition == "event_short":
        props["ends"] = (NOW + timedelta(minutes=29)).isoformat()
    event_id = "nws_" + props["id"]
    bundle = build_severe_weather_bundle(SevereWeatherAlert(
        props["event"], props["areaDesc"], props["severity"], props["headline"], event_id,
        description=props["description"], source_evidence=source_envelope(source, utc_text(NOW))))
    score = replace(state["_triage_queue"][0].score, category="severe_weather", total=100)
    out = {}
    assert triage_queue._enqueue_story_candidate(state, bundle=bundle, score=score, source="nws_alerts",
        legacy_type="severe_weather", event_id=event_id, admission_out=out,
        review_context=_review_context(source="NWS", source_key="nws_alerts", headline="Invented warning", facts=[])), out
    return event_id


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
@pytest.mark.parametrize("condition", ["expired", "short", "exact", "future", "event_short"])
def test_unusable_warning_cannot_take_only_writer_slot(world, monkeypatch, mode, condition):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0" if mode == "legacy" else "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
    state, _ = scheduled.manual_slate()
    warning = add_warning(state, condition)
    ready = scheduled.enqueue_automatic(state, world, monkeypatch)
    record = scheduled.run()
    record["sources"].append({"source": "nws_alerts", "triaged_in": 0, "triaged_out": 0,
                              "writer_attempted": 0, "drafted": 0})
    budget, sink = CandidateBudget("invented-expiry", 1), funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget, funnel_sink=sink) == 1
    assert world.writer_events() == [ready]
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]
    assert not budget.seen("event:" + warning) and budget.attempts == 1
    assert sink["_slate_terminal"][warning] == "nws_source"
    row = next(x for x in record["sources"] if x["source"] == "nws_alerts")
    assert row["triaged_in"] == row["triaged_out"] == 1
    assert row["writer_attempted"] == row["drafted"] == 0


def test_all_unusable_has_no_writer_or_reservation(world):
    state, _ = scheduled.manual_slate()
    add_warning(state, "short")
    budget = CandidateBudget("invented-expiry", 1)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == budget.held == 0 and state["drafts"] == []


@pytest.mark.parametrize("condition", ["valid", "forecast_onset", "just_enough"])
def test_current_warning_with_time_for_delay_stays_potential(world, monkeypatch, condition):
    state, _ = scheduled.manual_slate()
    warning = add_warning(state, condition)
    scheduled.enqueue_automatic(state, world, monkeypatch)
    triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=CandidateBudget("invented", 1))
    assert world.writer_events() == [warning]  # Not a source/model/approval pass.


def test_operator_context_keeps_existing_generation(world, monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    state, _ = scheduled.manual_slate()
    warning = add_warning(state, "expired")
    scheduled.enqueue_automatic(state, world, monkeypatch)
    triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=CandidateBudget("invented", 1))
    assert world.writer_events() == [warning]


def test_post_admission_envelope_tamper_cannot_exclude_valid_candidate(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    warning = add_warning(state, "valid")
    state["_triage_queue"][-1].bundle.raw_signal_dump["source_evidence"]["feature_sha256"] = "0" * 64
    ready = scheduled.enqueue_automatic(state, world, monkeypatch)
    sink = funnel.new_funnel()
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(),
        candidate_budget=CandidateBudget("invented", 1), funnel_sink=sink) == 1
    assert world.writer_events() == [ready] and sink["_slate_terminal"][warning] == "nws_source"


@pytest.mark.parametrize("change", ["candidate_id", "unrecognizable_payload"])
def test_changed_warning_identity_is_held_before_ranking(world, monkeypatch, change):
    state, _ = scheduled.manual_slate()
    add_warning(state, "valid")
    candidate = state["_triage_queue"][-1]
    if change == "candidate_id":
        state["_triage_queue"][-1] = replace(candidate, event_id="nws_invented-other")
    else:
        candidate.bundle.signal_kind = "invented_changed_kind"
        candidate.bundle.event_id = "invented-changed-id"
        candidate.bundle.raw_signal_dump = {}
    ready = scheduled.enqueue_automatic(state, world, monkeypatch)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(),
        candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [ready]


def test_source_failure_is_fixed_code_without_private_exception_or_paid_fallback(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    add_warning(state, "valid")
    ready = scheduled.enqueue_automatic(state, world, monkeypatch)
    marker = "invented-private-source-path-and-secret"
    def unavailable(*args, **kwargs):
        raise RuntimeError(marker)
    monkeypatch.setattr(nws_publication, "nws_generation_hold", unavailable)
    record = scheduled.run()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [ready]
    row = next(r for r in record["sources"] if r["source"] == "automatic_selection")
    assert row["details"]["source_holds"] == {"nws_source_unverified": 1}
    assert marker not in json.dumps([state, record], default=str)


def test_source_diagnostics_do_not_inflate_source_observations(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    add_warning(state, "short")
    scheduled.enqueue_automatic(state, world, monkeypatch)
    record = scheduled.run()
    triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=CandidateBudget("invented", 1))
    row = next(r for r in record["sources"] if r["source"] == "automatic_selection")
    assert row["observed"] == row["promoted"] == 0
    assert row["details"] == {"policy_only": False, "candidate_count": 3, "potential_type_count": 2,
        "held_manual_types": 1, "held_types": {"fire": 1}, "source_ready_count": 1,
        "held_source_candidates": 1, "source_holds": {"nws_source_automatic_window_unavailable": 1}}


def test_non_nws_source_is_untouched(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    ready = scheduled.enqueue_automatic(state, world, monkeypatch)
    def unexpected(*args, **kwargs):
        pytest.fail("Non-NWS candidate reached NWS guard")
    monkeypatch.setattr(nws_publication, "nws_generation_hold", unexpected)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [ready]


def test_positive_preflight_grants_nothing_and_later_expiry_still_holds(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    add_warning(state, "valid")
    payload = state["_triage_queue"][-1].bundle.to_dict()
    original = deepcopy(payload)
    assert nws_publication.nws_generation_hold(payload, now=NOW, minimum_delay=timedelta(minutes=30)) is None
    assert payload == original and "approval_binding" not in payload
    prototype = {"type": payload["signal_kind"], "event_id": payload["event_id"],
                 "review_context": {"two_bot": {"bundle": payload}}}
    monkeypatch.setattr(nws_publication, "_clock", lambda: NOW + timedelta(hours=3))
    assert nws_publication.current_nws_source(prototype, live=False) == "nws_source_expired_or_future"
