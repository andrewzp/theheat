"""Invented operator intent through the actual drain and workflow mode script."""
import os
from pathlib import Path
import subprocess

from freezegun import freeze_time
import pytest
import yaml

from src.orchestrator import funnel, nws_publication, triage_queue
from src.orchestrator.candidate_budget import CandidateBudget
from tests import test_nws_prewriter_expiry as expiry
from tests import test_scheduled_automatic_preflight as scheduled

FLAG = "THEHEAT_AUTOMATIC_SELECTION_ONLY"
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def world(monkeypatch):
    with freeze_time(expiry.NOW):
        spy = scheduled.world.__wrapped__(monkeypatch)
        monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
        monkeypatch.setenv(FLAG, "1")
        monkeypatch.setattr(nws_publication, "_clock", lambda: expiry.NOW)
        yield spy


@pytest.mark.parametrize("mode", ["triage", "legacy", "refill"])
def test_explicit_automatic_intent_keeps_only_eligible_writer(world, monkeypatch, mode):
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0" if mode == "legacy" else "1")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1" if mode == "refill" else "0")
    state, manual = scheduled.manual_slate()
    eligible = scheduled.enqueue_automatic(state, world, monkeypatch)
    record, sink, budget = scheduled.run(), funnel.new_funnel(), CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget, funnel_sink=sink) == 1
    assert world.writer_events() == [eligible]
    assert [stage for stage, _ in world.calls] == ["writer", "safety", "fact_check", "critic"]
    assert not budget.seen("event:" + manual) and budget.attempts == 1
    assert sink["_slate_terminal"][manual] == "automatic_policy"
    assert state["drafts"][0]["approval_mode"] == "auto"  # Existing complete check/save path.


def test_all_manual_intent_refuses_before_writer_and_reservation(world):
    state, manual = scheduled.manual_slate()
    budget, record = CandidateBudget("invented", 1), scheduled.run()
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == 0 and not budget.seen("event:" + manual)
    assert state["drafts"] == []
    report = next(r for r in record["sources"] if r["source"] == "automatic_selection")
    assert report["observed"] == report["promoted"] == 0


@pytest.mark.parametrize("condition", ["expired", "exact", "event_short"])
def test_explicit_intent_reuses_nws_currentness_before_ranking(world, monkeypatch, condition):
    monkeypatch.setenv("THEHEAT_NWS_WARNING_AUTO_TEXT", "1")
    state, _ = scheduled.manual_slate()
    warning = expiry.add_warning(state, condition)
    eligible = scheduled.enqueue_automatic(state, world, monkeypatch)
    budget = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=budget) == 1
    assert world.writer_events() == [eligible] and not budget.seen("event:" + warning)


@pytest.mark.parametrize("change", ["invalid_flag", "branch", "event", "mode", "no_run", "pause", "publication_off",
                                     "autoship_off", "bad_epoch", "retired", "policy_unavailable"])
def test_refused_explicit_intent_never_falls_back_to_manual_writing(world, monkeypatch, change):
    state, _ = scheduled.manual_slate()
    record = scheduled.run()
    if change == "invalid_flag":
        monkeypatch.setenv(FLAG, "invented-invalid")
    elif change == "branch":
        monkeypatch.setenv("GITHUB_REF", "refs/heads/invented")
    elif change == "event":
        monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    elif change == "mode":
        record["mode"] = "leaderboard"
    elif change == "no_run":
        record = None
    elif change == "pause":
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    elif change == "publication_off":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    elif change == "autoship_off":
        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0")
    elif change == "bad_epoch":
        monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "bad")
    elif change == "retired":
        state["publication_control"] = {"retired_epochs": ["invented-release-20261105"]}
    else:
        def unavailable(*args):
            raise RuntimeError("invented-private-context")
        monkeypatch.setattr("src.editorial.publication.automatic_publication_policy", unavailable)
    budget = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, record, candidate_budget=budget) == 0
    assert world.calls == [] and budget.attempts == 0 and state["drafts"] == []


@pytest.mark.parametrize("flag", [None, "0"])
def test_default_operator_intent_keeps_manual_drafting(world, monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv(FLAG)
    else:
        monkeypatch.setenv(FLAG, flag)
    state, manual = scheduled.manual_slate()
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(),
        candidate_budget=CandidateBudget("invented", 1)) == 1
    assert world.writer_events() == [manual] and state["drafts"][0]["approval_mode"] == "manual"


def test_input_is_optional_and_wired_to_selector_and_bot():
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    field = workflow["on"]["workflow_dispatch"]["inputs"]["automatic_only"]
    assert field["type"] == "boolean" and field["default"] == "false"
    steps = {s.get("name"): s for s in workflow["jobs"]["run"]["steps"]}
    for name in ("Determine mode", "Run bot"):
        value = steps[name]["env"][FLAG]
        assert "inputs.automatic_only" in value and "workflow_dispatch" in value
        assert "vars." not in value  # Per-request intent, not standing activation.


def test_runtime_inventory_records_intent_without_granting_an_approval(world, monkeypatch):
    from src.runtime_inventory import collect_runtime_inventory

    snapshot = collect_runtime_inventory("alerts")
    assert snapshot["flags"]["automatic_only_requested"] is True
    monkeypatch.setenv(FLAG, "0")
    assert collect_runtime_inventory("alerts")["flags"]["automatic_only_requested"] is False
    assert world.calls == []


@pytest.mark.parametrize("mode,only,branch,expected", [
    ("alerts", "1", "main", 0), ("both", "1", "main", 0),
    ("manual_tweet", "1", "main", 2), ("auto_publish_due", "1", "main", 2),
    ("leaderboard", "1", "main", 2), ("alerts", "1", "invented", 2),
    ("alerts", "0", "invented", 0), ("leaderboard", "0", "main", 0),
])
def test_actual_mode_script_refuses_incompatible_intent(tmp_path, mode, only, branch, expected):
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(s for s in workflow["jobs"]["run"]["steps"] if s.get("name") == "Determine mode")
    script = step["run"]
    for key, value in {"github.event_name": "workflow_dispatch", "github.event.inputs.mode": mode,
                       "github.event.schedule": ""}.items():
        script = script.replace("${{ " + key + " }}", value)
    path, output = tmp_path / "mode.sh", tmp_path / "output"
    path.write_text(script)
    output.touch()
    env = {"PATH": os.defpath, "GITHUB_EVENT_NAME": "workflow_dispatch",
           "GITHUB_REF": "refs/heads/" + branch, "GITHUB_OUTPUT": str(output),
           "REQUESTED_MODE": mode, FLAG: only, "THEHEAT_SCHEDULED_ALERTS_CATCHUP": "0"}
    result = subprocess.run(["/bin/bash", "-e", str(path)], env=env, capture_output=True, text=True, timeout=5)
    assert result.returncode == expected, result.stderr
    assert output.read_text() == (f"mode={mode}\n" if expected == 0 else "")


def test_preflight_does_not_turn_a_later_check_rejection_into_an_approval(world, monkeypatch):
    state, _ = scheduled.manual_slate()
    eligible = scheduled.enqueue_automatic(state, world, monkeypatch)
    world.critic_kill.add(eligible)
    budget = CandidateBudget("invented", 1)
    assert triage_queue._drain_and_write_triage_queue(state, scheduled.run(), candidate_budget=budget) == 0
    assert world.writer_events() == [eligible] and budget.attempts == 1 and state["drafts"] == []
