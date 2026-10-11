"""A configured pause is neither a new collection outage nor proof of recovery."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
import yaml

from scripts import source_health_sentinel as source
from scripts import workflow_health as workflow

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
STALE = [{"mode": "alerts", "started_at": "2026-11-02T12:00:00Z"}]
FRESH = [{"mode": "both", "started_at": "2026-11-03T11:00:00Z"}]


def info(file="bot.yml", conclusion="success"):
    return {"file": file, "runs": [{
        "id": 1, "conclusion": conclusion, "status": "completed",
        "created_at": "2026-11-03T11:30:00Z",
        "html_url": "https://example.test/run/1",
    }]}


@pytest.mark.parametrize("history", [None, [], FRESH, STALE])
def test_paused_source_liveness_holds_incident_without_claiming_recovery(history):
    original = deepcopy(history)
    report = source.run_sentinel({}, now=NOW, run_history=history, production_paused=True)
    assert report["has_failures"] is False
    assert report["failing"] == report["healthy"] == []
    assert report["summary"]["paused"] == report["summary"]["total"] == 1
    paused, = report["paused"]
    assert paused["source"] == source.LIVENESS_SOURCE
    assert paused["reason"] == "production_pause_configured"
    assert paused["issue_resolution_unknown"] is True
    assert "last_success_ts" not in paused
    assert paused["last_alert_at"] == (history[0]["started_at"] if history else None)
    assert source.plan_health_issue_actions(report, {source.LIVENESS_SOURCE: 999}) == []
    assert source.plan_health_issue_actions(report, {}) == []
    assert history == original


def test_real_source_failure_survives_pause_and_existing_liveness_incident_is_held():
    health = {"invented_source": {
        "failed": 5, "runs": [{"status": "failed"}] * 5,
        "last_error": "401 Unauthorized", "last_success_ts": None,
    }}
    report = source.run_sentinel(health, now=NOW, run_history=STALE, production_paused=True)
    assert report["has_failures"] is True
    assert [r["source"] for r in report["failing"]] == ["invented_source"]
    actions = source.plan_health_issue_actions(report, {source.LIVENESS_SOURCE: 999})
    assert [(r["action"], r["source"]) for r in actions] == [("create", "invented_source")]


@pytest.mark.parametrize("not_paused", [False, None, "1", "true", 1])
def test_non_boolean_pause_inputs_do_not_suppress_source_staleness(not_paused):
    report = source.run_sentinel({}, now=NOW, run_history=STALE, production_paused=not_paused)
    assert report["paused"] == []
    assert [r["source"] for r in report["failing"]] == [source.LIVENESS_SOURCE]


def test_resume_requires_normal_freshness_instead_of_treating_flag_clear_as_recovery():
    stale = source.run_sentinel({}, now=NOW, run_history=STALE, production_paused=False)
    assert source.plan_health_issue_actions(stale, {source.LIVENESS_SOURCE: 999})[0]["action"] == "update"
    fresh = source.run_sentinel({}, now=NOW, run_history=FRESH, production_paused=False)
    assert source.plan_health_issue_actions(fresh, {source.LIVENESS_SOURCE: 999}) == [
        {"action": "close", "source": source.LIVENESS_SOURCE, "number": 999},
    ]


@pytest.mark.parametrize("conclusion", ["success", "skipped", None])
def test_paused_bot_does_not_enter_recovered_workflows(conclusion):
    inputs = {"theheat-bot": info(conclusion=conclusion)}
    original = deepcopy(inputs)
    report = workflow.run_workflow_health(inputs, now=NOW, production_paused=True)
    assert report["healthy"] == report["failing"] == []
    paused, = report["paused"]
    assert paused["workflow"] == "theheat-bot"
    assert paused["reason"] == "production_pause_configured"
    if conclusion == "success":
        assert paused["conclusion"] == "success"
        assert paused["run_url"] == "https://example.test/run/1"
    recovered = {r["workflow"] for r in report["healthy"]}
    assert workflow.plan_workflow_issue_actions({}, recovered, {"theheat-bot": 999}) == []
    assert inputs == original


@pytest.mark.parametrize("conclusion", sorted(workflow.FAILING_CONCLUSIONS))
def test_pause_never_masks_bot_failures_other_workflows_or_healer_errors(conclusion):
    report = workflow.run_workflow_health({
        "theheat-bot": info(conclusion=conclusion),
        "voice-regression": info("voice-regression.yml", "failure"),
        "time-travel-canary": info("time-travel-canary.yml", "success"),
    }, now=NOW, production_paused=True,
        beacon={"outcome": "error", "run_at": "2026-11-03T11:00:00Z"})
    assert report["paused"] == []
    assert {r["workflow"] for r in report["failing"]} == {
        "theheat-bot", "voice-regression", workflow.SELFHEAL_SOURCE,
    }
    assert [r["workflow"] for r in report["healthy"]] == ["time-travel-canary"]


@pytest.mark.parametrize("name,file", [("theheat-bot", "other.yml"), ("other", "bot.yml")])
def test_pause_requires_both_exact_bot_identifiers(name, file):
    report = workflow.run_workflow_health({name: info(file)}, now=NOW, production_paused=True)
    assert report["paused"] == []
    assert [r["workflow"] for r in report["healthy"]] == [name]


@pytest.mark.parametrize("value", [None, "0", "false", "true", " 1", "1 ", "1"])
def test_source_main_uses_exact_configuration_and_performs_no_github_calls(tmp_path, monkeypatch, capsys, value):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    if value is None:
        monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", value)
    monkeypatch.setattr(source, "_run_gh", lambda *a, **kw: pytest.fail("unexpected GitHub request"))
    path = tmp_path / "invented-state.json"
    path.write_text(json.dumps({"source_health": {}, "run_history": []}))
    assert source.main([str(path)]) == 0
    stdout = capsys.readouterr().out
    if value == "1":
        assert "PAUSED" in stdout and "freshness and recovery are not established" in stdout
        assert "FAILING" not in stdout
    else:
        assert "FAILING" in stdout and "PAUSED" not in stdout


@pytest.mark.parametrize("value", [None, "0", "true", "1"])
def test_workflow_main_holds_paused_bot_issue_but_reports_real_failure(monkeypatch, capsys, value):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    if value is None:
        monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", value)
    monkeypatch.setattr(workflow, "_run_gh", lambda *a, **kw: pytest.fail("unexpected GitHub request"))
    monkeypatch.setattr(workflow, "fetch_runs_by_workflow", lambda: {
        "theheat-bot": info(), "voice-regression": info("voice-regression.yml", "failure"),
    })
    monkeypatch.setattr(workflow, "fetch_selfheal_beacon", lambda: None)
    monkeypatch.setattr(workflow, "_list_open_workflow_issues", lambda: {"theheat-bot": 999})
    monkeypatch.setattr(workflow, "_ensure_labels", lambda: None)
    actions = []
    monkeypatch.setattr(workflow, "_create_issue", lambda name, v: actions.append(("create", name)))
    monkeypatch.setattr(workflow, "_update_issue", lambda a: actions.append(("update", a["workflow"])))
    monkeypatch.setattr(workflow, "_close_issue", lambda n, name: actions.append(("close", name)))
    assert workflow.main([]) == 0
    assert ("create", "voice-regression") in actions
    assert (("close", "theheat-bot") in actions) is (value != "1")
    assert ("PAUSED" in capsys.readouterr().out) is (value == "1")


def test_sentinel_steps_receive_pause_intent_without_extra_permissions():
    content = yaml.safe_load(Path(".github/workflows/source-health-sentinel.yml").read_text())
    steps = {step["name"]: step for step in content["jobs"]["sentinel"]["steps"] if "name" in step}
    for name in ("Reconcile source-failure issues", "Reconcile workflow-health issues"):
        assert steps[name]["env"]["THEHEAT_PRODUCTION_PAUSED"] == "${{ vars.THEHEAT_PRODUCTION_PAUSED }}"
    assert content["permissions"] == {"contents": "read", "issues": "write", "actions": "read"}


def test_source_apply_holds_liveness_issue_without_stopping_real_failure_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    path = tmp_path / "invented-state.json"
    path.write_text(json.dumps({"run_history": [], "source_health": {"invented_source": {
        "failed": 5, "runs": [{"status": "failed"}] * 5, "last_error": "401 Unauthorized",
    }}}))
    labels = []

    def only_labels(args, **kwargs):
        assert args[:2] == ["label", "create"], "unexpected external issue request"
        labels.append(args[2])

    monkeypatch.setattr(source, "_run_gh", only_labels)
    monkeypatch.setattr(source, "_list_open_sentinel_issues", lambda: {source.LIVENESS_SOURCE: 999})
    for name in ("yield_watch", "coverage_watch", "writer_watch", "queue_watch", "editor_brief", "news_gap"):
        monkeypatch.setattr(source, f"_open_{name}_issue", lambda: None)
    actions = []
    monkeypatch.setattr(source, "_create_issue", lambda v: actions.append(("create", v["source"])))
    monkeypatch.setattr(source, "_update_issue", lambda a: actions.append(("update", a["source"])))
    monkeypatch.setattr(source, "_close_issue", lambda n, name: actions.append(("close", name)))
    assert source.main([str(path)]) == 0
    assert actions == [("create", "invented_source")]
    assert labels == [source.LABEL, "ours", "external", "unknown"]
