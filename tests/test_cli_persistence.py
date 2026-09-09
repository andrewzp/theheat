"""CLI final persistence, using real finalization and no external providers."""
from copy import deepcopy

import pytest
import requests

from src import state
from src.orchestrator import cli


def prepare(monkeypatch, outcomes, *, source_status="skipped"):
    initial = {"drafts": [], "run_history": [], "publish_ledger": {"old": {"tweet_id": "receipt-fixture"}}}
    monkeypatch.setattr("sys.argv", ["theheat", "auto_publish_due"])
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "paused-test-fixture")
    monkeypatch.setattr(state, "read_state", lambda: deepcopy(initial))
    monkeypatch.setattr(cli.runtime_inventory, "collect_runtime_inventory", lambda *args, **kwargs: {"git_sha": "fixture-sha", "mode": "auto_publish_due"})
    monkeypatch.setattr(cli.credentials, "collect_credential_expiry", lambda: {})
    monkeypatch.setattr(cli.usage_ledger, "drain_into_state", lambda value: 0)
    monkeypatch.setattr(cli.budget, "record_budget_health", lambda value: {"mtd_usd": 0, "pct_of_budget": 0, "budget_usd": 14, "projected_usd": 0, "level": "ok"})
    attempts = []
    results = iter(outcomes)

    def write(value):
        attempts.append(deepcopy(value))
        return next(results)

    def dispatch(value, *, current_run):
        # Returning a replacement state must not lose the terminal report.
        updated = deepcopy(value)
        updated["drafts"] = [{"id": "offline-draft", "status": "pending", "text": "Synthetic retained text."}]
        current_run["sources"].append({"source": "offline", "status": source_status, "drafted": 1})
        return updated

    monkeypatch.setattr(state, "write_state", write)
    return {"auto_publish_due": dispatch}, attempts


@pytest.mark.parametrize("source_status,expected_status", [("skipped", "success"), ("partial_failure", "partial_failure")])
def test_one_final_write_contains_data_and_terminal_runtime(monkeypatch, source_status, expected_status):
    dispatchers, attempts = prepare(monkeypatch, [True], source_status=source_status)
    cli.main(dispatchers)
    assert len(attempts) == 1
    saved = attempts[0]
    assert saved["drafts"][0]["text"] == "Synthetic retained text."
    assert saved["publish_ledger"] == {"old": {"tweet_id": "receipt-fixture"}}
    assert saved["publication_control"]["enabled"] is False
    run = saved["run_history"][0]
    assert run["runtime_inventory"]["git_sha"] == "fixture-sha"
    assert run["status"] == expected_status and run["ended_at"]
    assert run["drafted_count"] == 1


def test_retry_uses_same_completed_report_without_duplicate_runs(monkeypatch, capsys):
    dispatchers, attempts = prepare(monkeypatch, [False, True])
    cli.main(dispatchers)
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert len(attempts[1]["run_history"]) == 1
    output = capsys.readouterr().out
    assert "retrying" in output and "State and run report saved" in output


def test_repeated_persistence_failure_cannot_report_workflow_success(monkeypatch, capsys):
    dispatchers, attempts = prepare(monkeypatch, [False, False])
    with pytest.raises(SystemExit) as error:
        cli.main(dispatchers)
    assert error.value.code == 1
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    output = capsys.readouterr().out
    assert "could not be confirmed saved" in output
    assert "Done" not in output and "State and run report saved" not in output


def test_gist_write_failure_diagnostic_excludes_sensitive_error_text(monkeypatch, capsys):
    monkeypatch.setattr(state, "GIST_ID", "fixture")
    monkeypatch.setattr(state, "GITHUB_TOKEN", "fixture-credential-not-for-output")
    response = requests.Response()
    response.status_code = 503

    def fail(*args, **kwargs):
        raise requests.HTTPError("private-draft-content and fixture-credential-not-for-output", response=response)

    monkeypatch.setattr(state.requests, "patch", fail)
    assert state._write_gist_state({}) is False
    output = capsys.readouterr().out
    assert "Gist write failed (HTTPError, HTTP 503)" in output
    assert "private-draft-content" not in output and "fixture-credential" not in output
