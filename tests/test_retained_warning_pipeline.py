"""Real queue, pipeline and admission; explicit offline model boundaries only."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock
from typing import Any

import pytest

from src.editorial.official_warning import WarningHold
from src.editorial.scoring import EditorialScore
from src.editorial.warning_runtime import (
    SuppliedWarning, WarningSource, current_warning_source, guard_warning_story, warning_source_scope,
)
from src.orchestrator import common
from src.orchestrator.sources.official_warning import run_official_warning
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.intern.warnings import build_warning_bundle
from src.two_bot.types import CriticResult, FactCheckResult, WriterResult
from tests.two_bot.conftest import configured_pipeline_providers as configured_pipeline_providers
from tests.warning_helpers import NOW, encode, nomination, packet

pytestmark = pytest.mark.usefixtures("configured_pipeline_providers")
COPY = "Invented Warning Agency warns: dangerous winds are possible tonight on Example Island."


@pytest.fixture
def case(monkeypatch):
    metadata, raw = packet()
    encoded = encode(metadata)
    selected: dict[str, Any] = {"input": SuppliedWarning(encoded, raw, nomination(encoded, raw)), "now": NOW}
    source = WarningSource(lambda: selected["input"], clock=lambda: selected["now"])
    bundle = build_warning_bundle(encoded, raw, nomination=selected["input"].nomination, now=NOW)
    score = EditorialScore("official_warning", 80, 80, 80, 80, 80, 0, 80, 60,
                           ["Invented explicit editorial nomination, not a provider-impact estimate."])
    writer = Mock(return_value=WriterResult(COPY, None, "warning_consequence", None, None,
                                           "Invented offline writer response."))
    safety = Mock(return_value=(True, None))
    fact = Mock(return_value=FactCheckResult(True, [], "offline fixture"))
    critic = Mock(return_value=CriticResult(True, None, "offline fixture"))
    monkeypatch.setattr(pipeline.writer, "write_tweet", writer)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", fact)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    return dict(selected=selected, source=source, bundle=bundle, score=score,
                state=deepcopy(DEFAULT_STATE), writer=writer, safety=safety, fact=fact, critic=critic)


def counts(case):
    return [case[key].call_count for key in ("writer", "safety", "fact", "critic")]


def draft(case):
    result: dict[str, Any] = {}
    saved = _try_two_bot_draft(case["bundle"], case["state"], case["score"],
        legacy_type="official_warning", event_id=case["bundle"].event_id,
        review_context={"source": "Invented Warning Agency"}, result_out=result)
    return saved, result


def test_real_dispatch_pipeline_and_admission_make_one_pending_manual_draft(case):
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert saved
    assert counts(case) == [1, 1, 1, 1]
    saved = case["state"]["drafts"][0]
    assert saved["text"] == COPY and saved["type"] == "official_warning"
    assert saved["status"] == "pending" and saved["approval_mode"] == "manual"
    assert saved["approval_policy"]["can_auto_approve"] is False
    assert saved["approval_policy"]["mode"] == "manual_only"
    assert "approval_binding" not in saved and "auto_approve_at" not in saved
    retained = saved["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["official_warning"]
    assert retained["metadata_utf8"].encode() == case["selected"]["input"].metadata_bytes
    assert retained["source_utf8"].encode() == case["selected"]["input"].source_bytes
    assert result["stage_outcomes"]["writer"] == "pass"


def test_current_scope_is_required_and_cleanup_does_not_leave_authority(case):
    saved, result = draft(case)
    assert not saved and counts(case) == [0, 0, 0, 0]
    assert result["kill_reason"] == "warning_current_source_unavailable"
    with warning_source_scope(case["source"]):
        guard_warning_story(case["bundle"])
    with pytest.raises(WarningHold, match="warning_current_source_unavailable"):
        guard_warning_story(case["bundle"])


@pytest.mark.parametrize("change", ["expired", "revision", "missing", "paused"])
def test_cheap_current_source_failures_make_zero_model_calls(case, monkeypatch, change):
    if change == "expired":
        case["selected"]["now"] += timedelta(days=1)
    elif change == "revision":
        value = case["selected"]["input"]
        case["selected"]["input"] = replace(value, nomination=replace(value.nomination, revision="r2"))
    elif change == "missing":
        case["selected"]["input"] = None
    else:
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    with warning_source_scope(case["source"]):
        saved, _ = draft(case)
    assert not saved and counts(case) == [0, 0, 0, 0]
    assert case["state"]["drafts"] == []


@pytest.mark.parametrize("stage,expected", [("writer", [1, 0, 0, 0]),
    ("safety", [1, 1, 0, 0]), ("fact", [1, 1, 1, 0]), ("critic", [1, 1, 1, 1])])
def test_source_expiry_during_each_model_stage_cannot_reach_next_stage_or_save(case, stage, expected):
    model = case[stage]
    output = model.return_value
    def expire(*args, **kwargs):
        case["selected"]["now"] += timedelta(days=1)
        return output
    model.side_effect = expire
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert not saved and counts(case) == expected
    assert case["state"]["drafts"] == []
    assert result["kill_reason"] == "warning_expired"


@pytest.mark.parametrize("text,reason", [
    ("Dangerous winds are possible tonight on Example Island.", "warning_copy_attribution_missing"),
    ("Invented Warning Agency warns of dangerous winds tonight.", "warning_copy_place_missing"),
    ("Invented Warning Agency: dangerous winds on Example Island.", "warning_copy_modality_missing"),
])
def test_missing_essential_copy_bindings_stop_before_paid_checks(case, text, reason):
    case["writer"].return_value = replace(case["writer"].return_value, tweet=text)
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert not saved and counts(case) == [1, 0, 0, 0]
    assert result["kill_reason"] == reason


@pytest.mark.parametrize("flag,value", [("THEHEAT_WRITER_SAMPLES", "3"),
    ("THEHEAT_CRITIC_REVISE_ENABLED", "1"), ("THEHEAT_CRITIC_ENABLED", "0")])
def test_warning_does_not_expand_samples_revise_or_skip_required_critic(case, monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert not saved and counts(case) == [0, 0, 0, 0]
    assert result["kill_stage"] == "warning_source"
    assert result["kill_reason"] == "warning_requires_one_sample_no_revise_and_required_critic"


def test_source_revision_change_after_writer_is_not_a_second_writer_attempt(case):
    def change(*args, **kwargs):
        metadata, raw = packet()
        metadata["revision"] = "r2"
        encoded = encode(metadata)
        case["selected"]["input"] = SuppliedWarning(encoded, raw, nomination(encoded, raw))
        return case["writer"].return_value
    case["writer"].side_effect = change
    with warning_source_scope(case["source"]):
        saved, result = draft(case)
    assert not saved and counts(case) == [1, 0, 0, 0]
    assert result["kill_reason"] == "warning_current_source_changed"


@pytest.mark.parametrize("stage", ["safety", "fact", "critic"])
def test_required_check_failures_cannot_save_a_warning(case, stage):
    case[stage].return_value = {"safety": (False, "offline fixture refusal"),
        "fact": FactCheckResult(False, ["unsupported"], "offline fixture"),
        "critic": CriticResult(False, "unsupported", "offline fixture")}[stage]
    with warning_source_scope(case["source"]):
        saved, _ = draft(case)
    assert not saved and case["state"]["drafts"] == []


def test_absent_producer_is_byte_compatible_and_does_not_call_a_source(case):
    before = deepcopy(case["state"])
    assert run_official_warning(case["state"], None) == {"status": "absent", "promoted": 0}
    assert case["state"] == before and counts(case) == [0, 0, 0, 0]


def test_supplied_producer_queues_once_and_existing_drain_runs_full_pipeline(case, monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    assert run_official_warning(case["state"], None, source=case["source"], score=case["score"])["promoted"] == 1
    assert run_official_warning(case["state"], None, source=case["source"], score=case["score"])["status"] == "reused"
    assert counts(case) == [0, 0, 0, 0]
    with warning_source_scope(case["source"]):
        assert _drain_and_write_triage_queue(case["state"], None) == 1
    assert counts(case) == [1, 1, 1, 1] and len(case["state"]["drafts"]) == 1


def test_old_queue_input_expiring_before_drain_spends_zero(case, monkeypatch):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    run_official_warning(case["state"], None, source=case["source"], score=case["score"])
    case["selected"]["now"] += timedelta(days=1)
    with warning_source_scope(case["source"]):
        assert _drain_and_write_triage_queue(case["state"], None) == 0
    assert counts(case) == [0, 0, 0, 0]


def test_expiry_during_admission_planning_leaves_no_saved_draft(case, monkeypatch):
    from src.editorial import draft_admission
    original = draft_admission.plan_draft_admission
    def expire(*args, **kwargs):
        value = original(*args, **kwargs)
        case["selected"]["now"] += timedelta(days=1)
        return value
    monkeypatch.setattr(draft_admission, "plan_draft_admission", expire)
    with warning_source_scope(case["source"]):
        saved, _ = draft(case)
    assert not saved and case["state"]["drafts"] == []
    assert counts(case) == [1, 1, 1, 1]


def test_correctable_text_edit_does_not_become_permanent_source_change(case):
    from src.editorial.revisions import invalidate_text, record_human_review, review_is_current
    with warning_source_scope(case["source"]):
        assert draft(case)[0]
    saved = case["state"]["drafts"][0]
    invalidate_text(saved, "Dangerous winds are possible tonight on Example Island.")
    before = deepcopy(saved)
    result = run_official_warning(case["state"], None, source=case["source"], score=case["score"])
    assert result["status"] == "reused"
    assert saved == before
    assert "official_warning_source_hold" not in saved["review_context"]
    invalidate_text(saved, COPY)
    record_human_review(saved)
    assert review_is_current(saved)
    with warning_source_scope(case["source"]):
        assert current_warning_source(saved) is None
    assert counts(case) == [1, 1, 1, 1]


@pytest.mark.parametrize("field,value", [("total", "80"), ("total", 101), ("threshold", -1), ("severity", True)])
def test_invalid_editorial_nomination_is_held_before_queue_or_writer(case, field, value):
    score = replace(case["score"], **{field: value})
    result = run_official_warning(case["state"], None, source=case["source"], score=score)
    assert result["status"] == "held" and result["reason"] == "warning_editorial_nomination_required"
    assert not case["state"].get("_triage_queue") and counts(case) == [0, 0, 0, 0]


@pytest.mark.parametrize("triage,refill", [("0", "0"), ("1", "0"), ("1", "1")])
def test_all_existing_drain_modes_preserve_one_warning_writer_and_manual_save(case, monkeypatch, triage, refill):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", triage)
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", refill)
    assert run_official_warning(case["state"], None, source=case["source"], score=case["score"])["promoted"] == 1
    with warning_source_scope(case["source"]):
        assert _drain_and_write_triage_queue(case["state"], None) == 1
    assert counts(case) == [1, 1, 1, 1]
    assert case["state"]["drafts"][0]["approval_policy"]["can_auto_approve"] is False


def test_conflicting_same_report_revisions_remove_both_live_queue_choices(case):
    assert run_official_warning(case["state"], None, source=case["source"], score=case["score"])["promoted"] == 1
    metadata, raw = packet()
    metadata["revision"] = "r2"
    encoded = encode(metadata)
    case["selected"]["input"] = SuppliedWarning(encoded, raw, nomination(encoded, raw))
    result = run_official_warning(case["state"], None, source=case["source"], score=case["score"])
    assert result["reason"] == "warning_current_revision_conflict"
    assert case["state"]["_triage_queue"] == [] and counts(case) == [0, 0, 0, 0]


def test_known_source_correction_revokes_old_review_and_cannot_be_cleared_by_reverting_text(case):
    from src.editorial.revisions import record_human_review, review_is_current
    with warning_source_scope(case["source"]):
        assert draft(case)[0]
    saved = case["state"]["drafts"][0]
    record_human_review(saved)
    metadata, raw = packet()
    metadata["revision"] = "r2"
    encoded = encode(metadata)
    original = case["selected"]["input"]
    case["selected"]["input"] = SuppliedWarning(encoded, raw, nomination(encoded, raw))
    assert run_official_warning(case["state"], None, source=case["source"], score=case["score"])["status"] == "held"
    assert not review_is_current(saved)
    case["selected"]["input"] = original
    with warning_source_scope(case["source"]):
        assert current_warning_source(saved) == "warning_saved_source_held"
