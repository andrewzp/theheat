"""Invented source-shaped copy through ordinary staging/drain and actual SDK args.

No live source/model/platform call, sender, Gist write or synthetic fallback.
The model replies are explicit SDK-factory fixtures, not quality evidence.
"""
from datetime import UTC, datetime
import json

from freezegun import freeze_time
import pytest

from src.data import awc_observed as source
from src.orchestrator.candidate_budget import CandidateBudget
from src.orchestrator.scheduler import SourceRunner, run_stage1_sources
from src.orchestrator.sources.awc_observed import run_awc_observed
from src.orchestrator.suppression import _suppression_context
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.two_bot.types import StoryBundle
from tests.test_awc_observed import NOW, TARGET
from tests.test_awc_observed_automatic import Transport
from tests.test_observed_copy_guard_journey import _models

# Location identifiers (11/7, with slashes), countries (8/6), three values and
# clock/date preserve the retained case's measured shape, without its text/data.
def clock():
    return datetime.now(UTC)


SHORT = ("North/Kelda, Portugal: -20°C; S/Varda, Norway: 45°C—"
         "a 65°C airport gap at 12:00 UTC, 15 Nov.")


def ordinary(monkeypatch, fresh_state, *, triage="1", copy=SHORT, **script):
    models = _models(monkeypatch, copy=copy, **script)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", triage)
    transport = Transport()
    transport.stations[0].update(site="North/Kelda Arpt", country="PT", lat=40.2, lon=-8.0)
    transport.stations[1].update(site="S/Varda Arpt", country="NO", lat=60.0, lon=10.0)
    transport.rows[0][3:5] = ["40.2", "-8.0"]
    transport.rows[1][3:5] = ["60.0", "10.0"]
    transport.install(monkeypatch.setattr)
    run = {"id": "invented-ordinary-budget", "mode": "alerts", "sources": []}
    return transport, models, run, CandidateBudget.for_operation("alerts")


def stage_and_drain(state, run, budget):
    with _suppression_context(state, source="alerts", run_id=run["id"]):
        run_stage1_sources(state, run, serial_runners=[],
            concurrent_runners=[SourceRunner("awc_observed", run_awc_observed)], max_workers=1)
        assert len(state.get("_triage_queue", [])) == 1, run
        return _drain_and_write_triage_queue(state, run, candidate_budget=budget)


@pytest.mark.parametrize("triage", ["0", "1"], ids=["legacy", "production-triage"])
def test_current_ordinary_sdk_request_supplies_109_body_and_exact_citation(monkeypatch, fresh_state, triage):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, triage=triage)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 1
        [saved] = fresh_state["drafts"]
        packet = json.loads(json.dumps(saved["review_context"]["two_bot"]["bundle"], allow_nan=False))
        assert source.validate_bundle(StoryBundle(**packet), now=clock)["points"][0]["valid_time"] == TARGET
        assert source.claim_failures(saved["text"], packet, now=clock) == []
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [request] = [request for stage, request in models.requests if stage == "writer"]
    prompt = request["messages"][0]["content"]
    marker = "Automatic publication copy budget: "
    assert marker in prompt
    value = json.loads(prompt.split(marker, 1)[1].split("\n", 1)[0])
    citation = source.citation(["TAAA", "TBBB"], TARGET)
    assert len(citation) == 90
    assert value == {"final_max_scalars": 200, "citation": citation,
                     "citation_reserve_scalars": 91, "body_max_scalars": 109}
    assert len(SHORT) <= 109
    [draft] = fresh_state["drafts"]
    assert draft["text"] == SHORT + "\n" + citation
    assert draft["status"] == "pending" and "tweet_id" not in draft
    assert draft["approval_binding"]["mode"] == "auto"
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_source_change_after_critic_still_refuses_final_admission(monkeypatch, fresh_state):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state)
    answer = models.google_text

    def reply_then_correct_source(request):
        stage, text = answer(request)
        if stage == "critic":
            transport.rows[0][0] = transport.rows[0][0].replace("M20/M25", "M21/M25")
            transport.rows[0][5] = "-21"
        return stage, text

    # Only the explicit SDK reply boundary changes the invented HTTP bytes;
    # the command, check interpreters and final source admission stay real.
    monkeypatch.setattr(models, "google_text", reply_then_correct_source)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 0
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert fresh_state["drafts"] == []
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_airport_request_has_one_place_first_instruction_and_compact_syntax(monkeypatch, fresh_state):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 1
    [request] = [request for stage, request in models.requests if stage == "writer"]
    assert "Open with the place and that fact" in request["system"][0]["text"]
    user = request["messages"][0]["content"]
    assert "Lead with the observed Celsius gap" not in user
    assert "compact place-first comparison" in user
    assert "This is syntax, not evidence" in user
    assert "<reading>°C—a <gap>°C airport gap at HH:MM UTC, DD Mon" in user
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    assert transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("copy,reason", [
    (SHORT.replace("North/Kelda", "North"), "awc_airport_scope_missing"),
    (SHORT.replace("Portugal", ""), "awc_airport_scope_missing"),
    (SHORT.replace("airport ", ""), "awc_airport_scope_missing"),
    (SHORT.replace("-20°C", "-21°C"), "awc_observed_quantity_missing"),
    (SHORT.replace("45°C", "44°C"), "awc_observed_quantity_missing"),
    (SHORT.replace("65°C", "64°C"), "awc_observed_quantity_missing"),
    (SHORT.replace("12:00 UTC", "same hour"), "awc_time_label_missing"),
    (SHORT.replace("15 Nov", "16 Nov"), "awc_time_label_missing"),
])
def test_short_copy_cannot_save_by_omitting_a_required_fact(monkeypatch, fresh_state, copy, reason):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, copy=copy)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 0
    assert models.stages() == ["writer"]
    assert fresh_state["drafts"] == []
    assert reason in fresh_state["suppressions"][-1]["reasons"]
    assert transport.x_posts == [] and transport.gist_patches == 0


@pytest.mark.parametrize("script,stages", [
    ({"safety": "MAYBE"}, ["writer", "safety"]),
    ({"fact_passed": False}, ["writer", "safety", "fact_check"]),
    ({"critic": {"verdict": "KILL", "kill_reason": "weak_signal", "revise_instruction": None,
                 "selected_index": None}}, ["writer", "safety", "fact_check", "critic"]),
])
def test_short_body_still_requires_every_model_check(monkeypatch, fresh_state, script, stages):
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, **script)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 0
    assert models.stages() == stages
    assert fresh_state["drafts"] == []
    assert transport.x_posts == [] and transport.gist_patches == 0


def test_complete_over_budget_body_keeps_checks_and_stays_manual(monkeypatch, fresh_state):
    body = ("North/Kelda airport in Portugal recorded -20°C, while S/Varda airport in Norway "
            "recorded 45°C: a 65°C difference at 12:00 UTC, 15 Nov.")
    assert 109 < len(body) < 189
    transport, models, run, budget = ordinary(monkeypatch, fresh_state, copy=body)
    with freeze_time(NOW, tick=True):
        assert stage_and_drain(fresh_state, run, budget) == 1
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = fresh_state["drafts"]
    assert draft["text"] == body + "\n" + source.citation(["TAAA", "TBBB"], TARGET)
    assert len(draft["text"]) > 200 and draft["status"] == "pending"
    assert draft.get("approval_binding") is None
    assert "tweet_id" not in draft
    assert transport.x_posts == [] and transport.gist_patches == 0
