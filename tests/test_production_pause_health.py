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
GUARDED = [
    ("theheat-bot", "bot.yml"),
    ("voice-regression", "voice-regression.yml"),
    ("refresh-thresholds", "refresh-thresholds.yml"),
]


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
@pytest.mark.parametrize("name,file", GUARDED)
def test_paused_workflow_does_not_enter_recovered_workflows(conclusion, name, file):
    inputs = {name: info(file, conclusion)}
    original = deepcopy(inputs)
    report = workflow.run_workflow_health(inputs, now=NOW, production_paused=True)
    assert report["healthy"] == report["failing"] == []
    paused, = report["paused"]
    assert paused["workflow"] == name
    assert paused["reason"] == "production_pause_configured"
    if conclusion == "success":
        assert paused["conclusion"] == "success"
        assert paused["run_url"] == "https://example.test/run/1"
    recovered = {r["workflow"] for r in report["healthy"]}
    assert workflow.plan_workflow_issue_actions({}, recovered, {name: 999}) == []
    assert inputs == original


@pytest.mark.parametrize("conclusion", sorted(workflow.FAILING_CONCLUSIONS))
def test_pause_never_masks_bot_failures_other_workflows_or_healer_errors(conclusion):
    report = workflow.run_workflow_health({
        "theheat-bot": info(conclusion=conclusion),
        "voice-regression": info("voice-regression.yml", "failure"),
        "refresh-thresholds": info("refresh-thresholds.yml", "failure"),
        "time-travel-canary": info("time-travel-canary.yml", "success"),
    }, now=NOW, production_paused=True,
        beacon={"outcome": "error", "run_at": "2026-11-03T11:00:00Z"})
    assert report["paused"] == []
    assert {r["workflow"] for r in report["failing"]} == {
        "theheat-bot", "voice-regression", "refresh-thresholds", workflow.SELFHEAL_SOURCE,
    }
    assert [r["workflow"] for r in report["healthy"]] == ["time-travel-canary"]


@pytest.mark.parametrize("name,file", [
    (name, file)
    for name in [*(name for name, _ in GUARDED), "other"]
    for file in [*(file for _, file in GUARDED), "other.yml"]
    if (name, file) not in GUARDED
])
def test_pause_requires_both_exact_workflow_identifiers(name, file):
    report = workflow.run_workflow_health({name: info(file)}, now=NOW, production_paused=True)
    assert report["paused"] == []
    assert [r["workflow"] for r in report["healthy"]] == [name]


@pytest.mark.parametrize("not_paused", [False, None, "1", "true", 1])
@pytest.mark.parametrize("name,file", GUARDED)
def test_non_boolean_pause_preserves_observed_workflow_success(not_paused, name, file):
    report = workflow.run_workflow_health({name: info(file)}, now=NOW, production_paused=not_paused)
    assert report["paused"] == []
    assert [r["workflow"] for r in report["healthy"]] == [name]


@pytest.mark.parametrize("name,file", GUARDED)
def test_resume_uses_run_evidence_and_skip_does_not_hide_historical_failure(name, file):
    original = info(file, "failure")
    original["runs"].insert(0, {
        "id": 2, "conclusion": "skipped", "status": "completed",
        "created_at": "2026-11-03T11:45:00Z", "html_url": "https://example.test/run/2",
    })
    for paused in (True, False):
        report = workflow.run_workflow_health({name: original}, now=NOW, production_paused=paused)
        assert report["paused"] == report["healthy"] == []
        failed, = report["failing"]
        assert failed["run_url"] == "https://example.test/run/1"
        assert failed["conclusion"] == "failure" and failed["consecutive_failures"] == 1
    resumed = workflow.run_workflow_health({name: info(file)}, now=NOW, production_paused=False)
    assert workflow.plan_workflow_issue_actions(
        {}, {r["workflow"] for r in resumed["healthy"]}, {name: 999},
    ) == [{"action": "close", "workflow": name, "number": 999}]


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
@pytest.mark.parametrize("evaluation_value", [None, "0", "true", " 1", "1 ", "1"])
@pytest.mark.parametrize("name,file", GUARDED)
def test_workflow_main_holds_paused_issue_but_reports_real_failure(
    monkeypatch, capsys, value, evaluation_value, name, file,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    if value is None:
        monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", value)
    if evaluation_value is None:
        monkeypatch.delenv("THEHEAT_PAID_EVALUATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("THEHEAT_PAID_EVALUATION_ENABLED", evaluation_value)
    monkeypatch.setattr(workflow, "_run_gh", lambda *a, **kw: pytest.fail("unexpected GitHub request"))
    monkeypatch.setattr(workflow, "fetch_runs_by_workflow", lambda: {
        name: info(file), "time-travel-canary": info("time-travel-canary.yml", "failure"),
    })
    monkeypatch.setattr(workflow, "fetch_selfheal_beacon", lambda: None)
    monkeypatch.setattr(workflow, "_list_open_workflow_issues", lambda: {name: 999})
    monkeypatch.setattr(workflow, "_ensure_labels", lambda: None)
    actions = []
    monkeypatch.setattr(workflow, "_create_issue", lambda name, v: actions.append(("create", name)))
    monkeypatch.setattr(workflow, "_update_issue", lambda a: actions.append(("update", a["workflow"])))
    monkeypatch.setattr(workflow, "_close_issue", lambda n, name: actions.append(("close", name)))
    assert workflow.main([]) == 0
    assert ("create", "time-travel-canary") in actions
    evaluation_disabled = name == "voice-regression" and evaluation_value != "1"
    held = value == "1" or evaluation_disabled
    assert (("close", name) in actions) is (not held)
    stdout = capsys.readouterr().out
    assert ("PAUSED" in stdout) is held
    assert ("Collection pause configured" in stdout) is (value == "1")
    assert ("Paid evaluations disabled" in stdout) is (value != "1" and evaluation_disabled)


def test_sentinel_steps_receive_pause_intent_without_extra_permissions():
    content = yaml.safe_load(Path(".github/workflows/source-health-sentinel.yml").read_text())
    steps = {step["name"]: step for step in content["jobs"]["sentinel"]["steps"] if "name" in step}
    for name in ("Reconcile source-failure issues", "Reconcile workflow-health issues"):
        assert steps[name]["env"]["THEHEAT_PRODUCTION_PAUSED"] == "${{ vars.THEHEAT_PRODUCTION_PAUSED }}"
    assert steps["Reconcile workflow-health issues"]["env"]["THEHEAT_PAID_EVALUATION_ENABLED"] == "${{ vars.THEHEAT_PAID_EVALUATION_ENABLED }}"
    assert content["permissions"] == {"contents": "read", "issues": "write", "actions": "read"}


@pytest.mark.parametrize("conclusion", ["success", "skipped", None, "cancelled"])
def test_disabled_evaluation_holds_incident_and_preserves_run_evidence(conclusion):
    inputs = {"voice-regression": info("voice-regression.yml", conclusion)}
    original = deepcopy(inputs)
    observed = workflow.run_workflow_health(inputs, now=NOW)
    prior, = observed["healthy"] or observed["unknown"]
    report = workflow.run_workflow_health(inputs, now=NOW, paid_evaluation_enabled=False)
    assert report["healthy"] == report["failing"] == report["unknown"] == []
    paused, = report["paused"]
    assert paused == {**prior, "category": "paused", "reason": "paid_evaluation_disabled"}
    assert report["summary"]["paused"] == report["summary"]["total"] == 1
    if conclusion == "success":
        assert paused["conclusion"] == "success"
        assert paused["run_url"] == "https://example.test/run/1"
    assert workflow.plan_workflow_issue_actions(
        {}, {r["workflow"] for r in report["healthy"]}, {"voice-regression": 999},
    ) == []
    assert inputs == original


def test_disabled_evaluation_with_no_runs_is_not_a_recovery():
    report = workflow.run_workflow_health(
        {"voice-regression": {"file": "voice-regression.yml", "runs": []}},
        now=NOW, paid_evaluation_enabled=False,
    )
    assert report["healthy"] == report["failing"] == report["unknown"] == []
    paused, = report["paused"]
    assert paused["reason"] == "paid_evaluation_disabled"
    assert paused["run_url"] is None
    assert workflow.plan_workflow_issue_actions({}, set(), {"voice-regression": 999}) == []


@pytest.mark.parametrize("conclusion", sorted(workflow.FAILING_CONCLUSIONS))
@pytest.mark.parametrize("newer_skipped", [False, True])
def test_disabled_evaluation_preserves_current_and_historical_failures(conclusion, newer_skipped):
    inputs = {"voice-regression": info("voice-regression.yml", conclusion)}
    if newer_skipped:
        inputs["voice-regression"]["runs"].insert(0, {
            "id": 2, "conclusion": "skipped", "status": "completed",
            "created_at": "2026-11-03T11:45:00Z", "html_url": "https://example.test/run/2",
        })
    baseline = workflow.run_workflow_health(inputs, now=NOW)
    for paused in (False, True):
        report = workflow.run_workflow_health(
            inputs, now=NOW, production_paused=paused, paid_evaluation_enabled=False,
        )
        assert report == baseline
        failed, = report["failing"]
        assert failed["run_url"] == "https://example.test/run/1"
        assert failed["conclusion"] == conclusion and failed["consecutive_failures"] == 1
        assert report["healthy"] == report["paused"] == []
        actions = workflow.plan_workflow_issue_actions({"voice-regression": failed}, set(), {})
        assert [(action["action"], action["workflow"]) for action in actions] == [("create", "voice-regression")]


@pytest.mark.parametrize("name,file", [
    ("theheat-bot", "bot.yml"),
    ("refresh-thresholds", "refresh-thresholds.yml"),
    ("other", "voice-regression.yml"),
    ("voice-regression", "other.yml"),
    ("voice-regression", ".github/workflows/voice-regression.yml"),
    ("voice-regression-copy", "voice-regression.yml"),
])
def test_disabled_evaluation_requires_both_exact_identifiers(name, file):
    inputs = {name: info(file)}
    assert workflow.run_workflow_health(inputs, now=NOW, paid_evaluation_enabled=False) == workflow.run_workflow_health(inputs, now=NOW)


@pytest.mark.parametrize("enabled", [True, None, 0, 1, "false", "0", "1", "", [], {}])
@pytest.mark.parametrize("conclusion", ["success", "skipped", "failure"])
def test_only_exact_false_changes_evaluation_verdict(enabled, conclusion):
    inputs = {"voice-regression": info("voice-regression.yml", conclusion)}
    assert workflow.run_workflow_health(inputs, now=NOW, paid_evaluation_enabled=enabled) == workflow.run_workflow_health(inputs, now=NOW)


def test_production_pause_reason_takes_precedence_and_selfheal_stays_independent(capsys):
    inputs = {"voice-regression": info("voice-regression.yml")}
    beacon = {"outcome": "error", "run_at": "2026-11-03T11:00:00Z"}
    baseline = workflow.run_workflow_health(inputs, now=NOW, production_paused=True, beacon=beacon)
    report = workflow.run_workflow_health(
        inputs, now=NOW, production_paused=True, paid_evaluation_enabled=False, beacon=beacon,
    )
    assert report == baseline
    assert report["paused"][0]["reason"] == "production_pause_configured"
    assert [r["workflow"] for r in report["failing"]] == [workflow.SELFHEAL_SOURCE]
    workflow._print_report(report)
    stdout = capsys.readouterr().out
    assert "Collection pause configured" in stdout
    assert "Paid evaluations disabled" not in stdout
    assert "FAILING" in stdout


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
