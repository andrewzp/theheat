"""Observed calendar comparators through existing automatic selection and save.

All weather bytes and SDK replies are invented; real source/audit/review/arming
code runs. No model quality, actual NOAA availability or X outcome is asserted.
"""
from copy import deepcopy
from datetime import UTC, datetime
import socket
from types import SimpleNamespace

from freezegun import freeze_time
import pytest

from src.editorial.scoring import score_record_event, score_record_low_event
from src.editorial.revisions import approval_is_current, fingerprint, review_is_current
from src.orchestrator import common, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
from src.state import DEFAULT_STATE
from src.two_bot.ghcn_claim_contract import json_tree
from tests import ghcn_graphic_helpers as sources
from tests.test_observed_copy_guard_journey import _models

NOW = datetime(2026, 9, 9, 10, tzinfo=UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Calendar automatic fixtures forbid real network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    # An explicit earlier retrieval permits the unchanged 90-minute review
    # window inside the existing 36-hour framing ceiling. No bound is relaxed.
    monkeypatch.setattr(sources, "AS_OF", "2026-09-09T08:00:00Z")
    # "Graphic Fixture" intentionally hits the unchanged text-only media guard.
    # Give this distinct invented station its name before the real builders run.
    monkeypatch.setattr(sources, "STATION", {**sources.STATION, "name": "CALENDAR FIXTURE",
                                           "country_name": "United States"})


@pytest.fixture(params=["high", "low"])
def record(request):
    bundle = sources.graphic_bundles(direction=request.param, tier="calendar")[-1]
    return bundle, "record" if request.param == "high" else "record_low"


def candidate(bundle, kind):
    return SimpleNamespace(bundle=bundle, legacy_type=kind, event_id=bundle.event_id,
                           tweet_date="2026-09-08")


def copy_for(kind):
    reading = "reached 42.2°C" if kind == "record" else "fell to -22.2°C"
    return (f"Calendar Fixture {reading} on 8 September, a record for 8 September "
            "in the available GHCN archive through 2026-09-07.")


def test_qualified_calendar_comparator_can_contend_for_automatic_selection(monkeypatch, record):
    bundle, kind = record
    _models(monkeypatch, copy=copy_for(kind))
    with freeze_time(NOW):
        assert triage_queue._automatic_source_hold(candidate(bundle, kind)) is None
        assert triage_queue._automatic_type_may_arm(kind, 90)


def test_actual_required_sdk_checks_save_a_delayed_automatic_calendar_draft(monkeypatch, record):
    bundle, kind = record
    text = copy_for(kind)
    models = _models(monkeypatch, copy=text)
    state, result = deepcopy(DEFAULT_STATE), {}
    with freeze_time(NOW, tick=True):
        raw = bundle.raw_signal_dump
        scorer = score_record_event if kind == "record" else score_record_low_event
        score = scorer(raw["new_temp_c"], raw["old_record_c"], raw["old_record_year"])
        assert score.passes
        saved = _try_two_bot_draft(bundle, state, score,
            legacy_type=kind, event_id=bundle.event_id, city="Calendar Fixture",
            tweet_date="2026-09-08", review_context={}, result_out=result)
    assert saved, result
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["text"] == text and draft["status"] == "pending"
    assert draft["approval_mode"] == "auto", (draft.get("automatic_text_hold"), draft.get("automatic_source_hold"))
    assert review_is_current(draft) and approval_is_current(draft, "auto")
    assert draft["autoship_on_critic_pass"] is True
    assert draft["approval_policy"]["recommended_delay_minutes"] == 90
    assert draft["approval_binding"]["mode"] == "auto"
    assert draft.get("auto_approve_at") and not draft.get("tweet_id")
    assert not state.get("publish_ledger")


@pytest.mark.parametrize("change", ["missing_evidence", "foreign_product", "wrong_comparator", "wrong_event",
                                   "unresolved_compact", "future_retrieval", "thin_calendar"])
def test_calendar_automatic_preflight_requires_positive_original_source(monkeypatch, record, change):
    bundle, kind = record
    _models(monkeypatch, copy=copy_for(kind))
    bundle = deepcopy(bundle)
    if change == "missing_evidence":
        bundle.raw_signal_dump.pop("evidence")
    elif change == "foreign_product":
        bundle.raw_signal_dump["evidence"]["source_product"] = "invented-other-product"
    elif change == "wrong_comparator":
        bundle.raw_signal_dump["old_record_c"] += 1
    elif change == "wrong_event":
        bundle.event_id += "_changed"
    elif change == "unresolved_compact":
        bundle.raw_signal_dump["ghcn_claim_view"] = {}
    elif change == "future_retrieval":
        bundle.raw_signal_dump["evidence"]["retrieved_at"] = "2099-01-01T00:00:00Z"
    else:
        bundle.raw_signal_dump["evidence"]["baseline"]["variables"][
            "temperature_2m_max" if kind == "record" else "temperature_2m_min"]["calendar_years"]["09-08"] = 0
    original = deepcopy(bundle.to_dict())
    with freeze_time(NOW):
        assert triage_queue._automatic_source_hold(candidate(bundle, kind)) is not None
    assert bundle.to_dict() == original


@pytest.mark.parametrize("flag", ["THEHEAT_OBSERVED_WEATHER_ONLY", "THEHEAT_AUTOSHIP_ON_CRITIC_PASS",
                                  "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED"])
def test_required_flag_off_keeps_the_checked_calendar_draft_manual(monkeypatch, record, flag):
    bundle, kind = record
    models = _models(monkeypatch, copy=copy_for(kind))
    monkeypatch.setenv(flag, "0")
    state, result = deepcopy(DEFAULT_STATE), {}
    with freeze_time(NOW, tick=True):
        raw = bundle.raw_signal_dump
        scorer = score_record_event if kind == "record" else score_record_low_event
        score = scorer(raw["new_temp_c"], raw["old_record_c"], raw["old_record_year"])
        assert _try_two_bot_draft(bundle, state, score, legacy_type=kind, event_id=bundle.event_id,
            review_context={}, city="Calendar Fixture", tweet_date="2026-09-08", result_out=result), result
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["approval_mode"] == "manual"
    assert not draft.get("auto_approve_at") and not draft.get("approval_binding")


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_required_check_failure_never_saves_or_arms_calendar_copy(monkeypatch, record, stage):
    bundle, kind = record
    script = {"safety": {"safety": "YES"}, "fact_check": {"fact_passed": False},
              "critic": {"critic": {"verdict": "KILL", "kill_reason": "invented rejection",
                                    "revise_instruction": None, "selected_index": None}}}[stage]
    models = _models(monkeypatch, copy=copy_for(kind), **script)
    state, result = deepcopy(DEFAULT_STATE), {}
    with freeze_time(NOW, tick=True):
        raw = bundle.raw_signal_dump
        scorer = score_record_event if kind == "record" else score_record_low_event
        score = scorer(raw["new_temp_c"], raw["old_record_c"], raw["old_record_year"])
        assert not _try_two_bot_draft(bundle, state, score, legacy_type=kind, event_id=bundle.event_id,
            review_context={}, city="Calendar Fixture", tweet_date="2026-09-08", result_out=result)
    expected = ["writer", "safety", "fact_check", "critic"]
    assert models.stages() == expected[:expected.index(stage) + 1]
    assert state["drafts"] == [] and not state.get("publish_ledger")


def test_direct_save_cannot_arm_foreign_calendar_evidence_with_mocked_passing_checks(monkeypatch, record):
    from tests.revision_helpers import model_review_context

    bundle, kind = record
    text = copy_for(kind)
    _models(monkeypatch, copy=text)
    payload = json_tree(bundle.to_dict())
    payload["raw_signal_dump"]["evidence"]["source_product"] = "invented-other-source"
    context = model_review_context(text)
    context["two_bot"]["bundle"] = payload
    context["two_bot"]["reviewed_bundle_sha256"] = fingerprint(payload)
    state = deepcopy(DEFAULT_STATE)
    with freeze_time(NOW):
        assert common.save_draft(text, state, kind, bundle.event_id, review_context=context)
    [draft] = state["drafts"]
    assert draft["approval_mode"] == "manual" and draft.get("automatic_source_hold")
    assert not draft.get("auto_approve_at") and not draft.get("approval_binding")


def test_calendar_preflight_keeps_existing_source_age_ceiling(monkeypatch, record):
    bundle, kind = record
    _models(monkeypatch, copy=copy_for(kind))
    with freeze_time("2026-09-09T13:00:00Z"):
        assert triage_queue._automatic_source_hold(candidate(bundle, kind)) == "autoship_source_stale"


def test_real_source_admission_and_single_candidate_drain_arm_the_checked_calendar_story(monkeypatch, record):
    bundle, kind = record
    models = _models(monkeypatch, copy=copy_for(kind))
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "2")
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-calendar-run", "mode": "alerts", "sources": []}
    budget = CandidateBudget("invented-calendar", 1)
    with freeze_time(NOW, tick=True):
        raw = bundle.raw_signal_dump
        scorer = score_record_event if kind == "record" else score_record_low_event
        score = scorer(raw["new_temp_c"], raw["old_record_c"], raw["old_record_year"])
        assert triage_queue._enqueue_story_candidate(state, bundle=bundle, score=score,
            source="open_meteo_extreme_signals", legacy_type=kind, event_id=bundle.event_id,
            review_context={}, city="Calendar Fixture", tweet_date="2026-09-08")
        assert triage_queue._drain_and_write_triage_queue(state, run, candidate_budget=budget) == 1
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert budget.attempts == 1
    [draft] = state["drafts"]
    assert draft["approval_mode"] == "auto" and approval_is_current(draft, "auto")
    trace = next(s for s in run["sources"] if s["source"] == "automatic_selection")
    assert trace["details"]["potential_type_count"] == 1
    assert trace["details"]["held_manual_types"] == 0


def test_calendar_actual_writer_request_receives_existing_200_scalar_budget(monkeypatch, record):
    from src.two_bot import pipeline

    bundle, kind = record
    models = _models(monkeypatch, copy=copy_for(kind))
    with freeze_time(NOW, tick=True):
        assert pipeline.generate_draft(bundle, deepcopy(DEFAULT_STATE)) is not None
    request = next(request for stage, request in models.requests if stage == "writer")
    messages = str(request["messages"])
    assert '"final_max_scalars": 200' in messages
    assert '"body_max_scalars": 200' in messages
