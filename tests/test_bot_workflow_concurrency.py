"""Offline queue-policy contract checks, not a GitHub expression interpreter.

Exact-head PR CI establishes GitHub syntax acceptance. These tests recognize only
the deliberately narrow approved expression shape and exercise its partitioning;
they do not claim to reproduce GitHub scheduling or cancellation behavior.
"""
from pathlib import Path
import os
import re
import select
import subprocess
import sys

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/bot.yml"


@pytest.fixture
def workflow():
    # BaseLoader keeps the YAML 1.2 workflow key "on" as text, unlike PyYAML's
    # default YAML 1.1 boolean interpretation. All assertions below use strings.
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def _queue_policy(workflow, event, *, pr_number=None):
    concurrency = workflow["concurrency"]
    match = re.fullmatch(
        r"\$\{\{ github\.event_name == 'pull_request' && "
        r"format\('([^']+)\{0\}', github\.event\.pull_request\.number\) "
        r"\|\| '([^']+)' \}\}",
        concurrency["group"],
    )
    assert match, "Queue expression changed; review its production/PR partition"
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    if event == "pull_request":
        assert type(pr_number) is int and pr_number > 0
        return match[1] + str(pr_number), True
    return match[2], False


@pytest.mark.parametrize("pr_number", [1, 207, 582])
def test_prs_use_separate_queues_that_can_cancel_only_their_old_heads(workflow, pr_number):
    first = _queue_policy(workflow, "pull_request", pr_number=pr_number)
    replacement = _queue_policy(workflow, "pull_request", pr_number=pr_number)
    other_pr = _queue_policy(workflow, "pull_request", pr_number=pr_number + 1)
    assert first == replacement == (f"theheat-ci-{pr_number}", True)
    assert other_pr[0] != first[0]
    assert first[0] != _queue_policy(workflow, "schedule")[0]


def test_every_existing_schedule_keeps_the_production_lock(workflow):
    assert {s["cron"] for s in workflow["on"]["schedule"]} == {
        "30 * * * *", "0 12 * * *", "0 0,4,8,16,20 * * *",
    }
    # No schedule or mode enters the expression: all use the same literal group.
    assert _queue_policy(workflow, "schedule") == ("theheat-bot", False)


def test_all_manual_modes_share_that_same_non_cancelling_lock(workflow):
    modes = workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert set(modes) == {"alerts", "leaderboard", "both", "manual_tweet", "auto_publish_due"}
    assert "inputs" not in workflow["concurrency"]["group"]
    assert _queue_policy(workflow, "workflow_dispatch") == ("theheat-bot", False)


@pytest.mark.parametrize("event", ["push", "repository_dispatch", "future_event"])
def test_non_pr_fallback_never_splits_or_cancels_producers(workflow, event):
    assert _queue_policy(workflow, event) == ("theheat-bot", False)


def test_pr_and_display_branch_job_exclusions_remain_explicit(workflow):
    test, run = workflow["jobs"]["test-partition"], workflow["jobs"]["run"]
    assert test["if"] == "github.event_name == 'pull_request' && github.head_ref != 'daily-plan-current'"
    assert " ".join(run["if"].split()) == "always() && github.event_name != 'pull_request'"
    assert run["needs"] == "test"
    # PR-specific groups depend only on the PR number, including forks and the
    # display-only branch; no branch-controlled string can select production.
    assert "head_ref" not in workflow["concurrency"]["group"]


def test_required_offline_suite_and_own_production_smoke_gate_remain(workflow):
    test, run = workflow["jobs"]["test-partition"], workflow["jobs"]["run"]
    suite = next(step for step in test["steps"] if step.get("run", "").startswith("python -m pytest tests/"))
    assert suite["run"] == 'python -m pytest tests/ -v -m "not voice_replay" --ci-partition=${{ matrix.partition }} --durations=20 -o faulthandler_timeout=120'
    assert suite["env"]["THEHEAT_TEST_POSTGRES"] == "1"
    assert {step.get("name") for step in test["steps"]} >= {
        "SQLite backend smoke", "Test dashboard", "Build dashboard",
    }
    assert any(step.get("name") == "Smoke gate" for step in run["steps"])
    assert test["timeout-minutes"] == "35"
    assert run["timeout-minutes"] == "20"


def test_required_check_fails_for_unsuccessful_or_skipped_partition(workflow):
    gate = workflow["jobs"]["test"]
    assert gate["needs"] == "test-partition"
    assert gate["if"] == (
        "always() && github.event_name == 'pull_request' && github.head_ref != 'daily-plan-current'"
    )
    step, = gate["steps"]
    assert step["env"] == {"PARTITION_RESULT": "${{ needs.test-partition.result }}"}
    assert step["run"] == 'test "$PARTITION_RESULT" = success'
    # Exercise the actual gate, including GitHub's skipped dependency outcome.
    import subprocess
    for result in ("success", "failure", "cancelled", "skipped", ""):
        completed = subprocess.run(["sh", "-c", step["run"]], env={"PARTITION_RESULT": result})
        assert (completed.returncode == 0) == (result == "success")


def test_partitions_preserve_every_check_without_repeating_dashboard(workflow):
    worker = workflow["jobs"]["test-partition"]
    assert worker["strategy"] == {
        "fail-fast": "false", "matrix": {"partition": ["core", "postgres", "media"]},
    }
    for step in worker["steps"]:
        if step.get("name") in {"SQLite backend smoke", "Test dashboard", "Build dashboard"}:
            assert step["if"] == "matrix.partition == 'core'"
    suite = next(s for s in worker["steps"] if s.get("run", "").startswith("python -m pytest"))
    assert "if" not in suite and "continue-on-error" not in worker


def test_immediate_python_output_is_scoped_to_the_bot_step(workflow):
    assert "PYTHONUNBUFFERED" not in workflow.get("env", {})
    locations = []
    for job_name, job in workflow["jobs"].items():
        assert "PYTHONUNBUFFERED" not in job.get("env", {})
        for step in job["steps"]:
            if "PYTHONUNBUFFERED" in step.get("env", {}):
                locations.append((job_name, step["name"], step["env"]["PYTHONUNBUFFERED"]))
    assert locations == [("run", "Run bot", "1")]


@pytest.mark.parametrize("use_workflow_setting", [True, False], ids=["unbuffered", "buffered-control"])
def test_written_output_survives_abrupt_exit_with_workflow_setting(workflow, use_workflow_setting):
    step = next(step for step in workflow["jobs"]["run"]["steps"] if step.get("name") == "Run bot")
    # Launch only a synthetic child, with no application, provider or secret env.
    env = {"PYTHONUNBUFFERED": step["env"]["PYTHONUNBUFFERED"]} if use_workflow_setting else {}
    child = subprocess.Popen(
        [sys.executable, "-c", (
            "import sys, time\n"
            "sys.stdout.write('synthetic output\\n')\n"
            "sys.stderr.write('ready\\n'); sys.stderr.flush()\n"
            "time.sleep(60)\n"
        )],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
    )
    try:
        assert select.select([child.stderr], [], [], 5)[0], "Child did not signal readiness"
        assert os.read(child.stderr.fileno(), 4096) == b"ready\n"
        readable = select.select([child.stdout], [], [], 1)[0]
        retained = os.read(child.stdout.fileno(), 4096) if readable else b""
    finally:
        if child.poll() is None:
            child.kill()
        remaining, _ = child.communicate(timeout=5)
    assert child.returncode != 0
    assert retained == (b"synthetic output\n" if use_workflow_setting else b"")
    # The buffered control loses its line on abrupt exit, rather than passing
    # because normal interpreter shutdown happened to flush it after the check.
    assert remaining == b""
