"""Offline queue-policy contract checks, not a GitHub expression interpreter.

Exact-head PR CI establishes GitHub syntax acceptance. These tests recognize only
the deliberately narrow approved expression shape and exercise its partitioning;
they do not claim to reproduce GitHub scheduling or cancellation behavior.
"""
from pathlib import Path
import json
import os
import re
import select
import subprocess
import sys
from types import SimpleNamespace

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
        "41 * * * *", "11 12 * * *", "11 0,4,8,16,20 * * *",
    }
    # No schedule or mode enters the expression: all use the same literal group.
    assert _queue_policy(workflow, "schedule") == ("theheat-bot", False)


def test_sentinel_keeps_its_hourly_cadence_in_a_separate_slot(workflow):
    sentinel_path = WORKFLOW.with_name("source-health-sentinel.yml")
    sentinel = yaml.load(sentinel_path.read_text(), Loader=yaml.BaseLoader)
    assert [entry["cron"] for entry in sentinel["on"]["schedule"]] == ["23 * * * *"]
    assert "23" not in {entry["cron"].split()[0] for entry in workflow["on"]["schedule"]}


@pytest.mark.parametrize(
    "event,schedule,manual,expected",
    [
        ("schedule", "41 * * * *", "", "auto_publish_due"),
        ("schedule", "11 12 * * *", "", "both"),
        ("schedule", "11 0,4,8,16,20 * * *", "", "alerts"),
        ("workflow_dispatch", "", "leaderboard", "leaderboard"),
        ("workflow_dispatch", "", "manual_tweet", "manual_tweet"),
        ("workflow_dispatch", "", "observed_report", "observed_report"),
    ],
)
def test_real_mode_selector_preserves_scheduled_and_manual_roles(workflow, tmp_path, event, schedule, manual, expected):
    step = next(step for step in workflow["jobs"]["run"]["steps"] if step.get("id") == "mode")
    script = step["run"].replace("${{ github.event.schedule }}", schedule)
    output = tmp_path / "github-output"
    env = {"GITHUB_OUTPUT": str(output), "GITHUB_EVENT_NAME": event}
    env.update({key: manual for key, expression in step["env"].items() if expression == "${{ inputs.mode }}"})
    subprocess.run(["/bin/bash", "-e", "-c", script], env=env, check=True, timeout=5)
    assert output.read_text() == f"mode={expected}\n"


def test_all_manual_modes_share_that_same_non_cancelling_lock(workflow):
    modes = workflow["on"]["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert set(modes) == {"alerts", "leaderboard", "both", "observed_report", "manual_tweet", "auto_publish_due"}
    assert "inputs" not in workflow["concurrency"]["group"]
    assert _queue_policy(workflow, "workflow_dispatch") == ("theheat-bot", False)


@pytest.mark.parametrize(
    "event,mode,enabled,attempt,ref,sender_exit,expected",
    [
        ("schedule", "alerts", "1", "1", "refs/heads/main", 0, ["auto_publish_due", "alerts"]),
        ("schedule", "both", "1", "1", "refs/heads/main", 0, ["auto_publish_due", "both"]),
        ("schedule", "auto_publish_due", "1", "1", "refs/heads/main", 0, ["auto_publish_due"]),
        ("schedule", "alerts", "0", "1", "refs/heads/main", 0, ["alerts"]),
        ("schedule", "alerts", "1", "2", "refs/heads/main", 0, ["alerts"]),
        ("schedule", "alerts", "1", "1", "refs/heads/feature", 0, ["alerts"]),
        ("workflow_dispatch", "alerts", "1", "1", "refs/heads/main", 0, ["alerts"]),
        ("workflow_dispatch", "both", "1", "1", "refs/heads/main", 0, ["both"]),
        ("workflow_dispatch", "manual_tweet", "1", "1", "refs/heads/main", 0, ["manual_tweet"]),
        ("schedule", "alerts", "1", "1", "refs/heads/main", 1, ["auto_publish_due"]),
    ],
)
def test_bot_step_runs_existing_sender_only_before_enabled_scheduled_collection(
    workflow, tmp_path, event, mode, enabled, attempt, ref, sender_exit, expected,
):
    step = next(step for step in workflow["jobs"]["run"]["steps"] if step.get("name") == "Run bot")
    script = (step["run"].replace("${{ steps.mode.outputs.mode }}", mode)
              .replace("${{ steps.mode.outputs.catchup }}", ""))
    python = tmp_path / "python"
    python.write_text(
        '#!/bin/bash\n'
        '[[ "$1" == -m && "$2" == src.main ]] || exit 99\n'
        'printf "%s\\n" "$3"\n'
        'if [[ "$3" == auto_publish_due ]]; then exit "$SENDER_EXIT"; fi\n'
    )
    python.chmod(0o755)
    result = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        env={
            "PATH": str(tmp_path),
            "GITHUB_EVENT_NAME": event,
            "GITHUB_RUN_ATTEMPT": attempt,
            "GITHUB_REF": ref,
            "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": enabled,
            "SENDER_EXIT": str(sender_exit),
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.stdout.splitlines() == expected
    assert result.returncode == sender_exit


@pytest.mark.parametrize("event", ["push", "repository_dispatch", "future_event"])
def test_non_pr_fallback_never_splits_or_cancels_producers(workflow, event):
    assert _queue_policy(workflow, event) == ("theheat-bot", False)


def test_pr_and_display_branch_job_exclusions_remain_explicit(workflow):
    test, run = workflow["jobs"]["test-partition"], workflow["jobs"]["run"]
    assert test["if"] == "github.event_name == 'pull_request' && github.head_ref != 'daily-plan-current'"
    assert workflow["jobs"]["test-dashboard"]["if"] == test["if"]
    assert " ".join(run["if"].split()) == (
        "always() && github.event_name != 'pull_request'"
        " && (vars.THEHEAT_PRODUCTION_PAUSED != '1'"
        " || (github.event_name == 'workflow_dispatch'"
        " && github.event.inputs.mode == 'manual_tweet'))"
    )
    # P00c: the default-off route drain job precedes the run inside the same group; it is
    # skipped unless THEHEAT_GIST_WRITE_ROUTE == 'serialized', and run's always() still applies.
    assert run["needs"] == ["test", "commands-before"]
    # PR-specific groups depend only on the PR number, including forks and the
    # display-only branch; no branch-controlled string can select production.
    assert "head_ref" not in workflow["concurrency"]["group"]


def test_required_offline_suite_and_own_production_smoke_gate_remain(workflow):
    test, run = workflow["jobs"]["test-partition"], workflow["jobs"]["run"]
    suite = next(step for step in test["steps"] if step.get("run", "").startswith("python -m pytest tests/ -v "))
    assert suite["run"] == 'python -m pytest tests/ -v -m "not voice_replay" --ci-partition=${{ matrix.partition }} --ci-postgres-shard=${{ matrix.postgres-shard }} --ci-critical-first --maxfail=1 --durations=20 -o faulthandler_timeout=${{ matrix.partition == \'postgres\' && (matrix.postgres-shard == \'2\' || matrix.postgres-shard == \'8\') && \'0\' || \'300\' }}'
    assert suite["env"]["THEHEAT_CI_SAFE_DIAGNOSTIC"] == "${{ matrix.partition == 'postgres' && matrix.postgres-shard == '8' && '1' || '0' }}"
    assert suite["env"]["THEHEAT_TEST_POSTGRES"] == "1"
    assert any(step.get("name") == "SQLite backend smoke" for step in test["steps"])
    assert any(step.get("name") == "Smoke gate" for step in run["steps"])
    assert test["timeout-minutes"] == "45"
    assert run["timeout-minutes"] == "20"


def test_native_capture_smoke_is_early_media_only_and_does_not_replace_full_suite(workflow):
    steps = workflow["jobs"]["test-partition"]["steps"]
    smoke, = [step for step in steps if step.get("name") == "Verify native graphics dependency capture"]
    assert smoke["if"] == "matrix.partition == 'media'"
    assert smoke["timeout-minutes"] == "2"
    assert smoke["run"] == ('python -m pytest tests/test_postgres_media_native_profile.py::'
        'test_actual_capture_and_verification_never_inspects_loaders_under_lock '
        '-q -m "not voice_replay" --ci-partition=media -o faulthandler_timeout=90')
    assert "continue-on-error" not in smoke and "env" not in smoke
    packages = next(s for s in steps if s.get("name") == "Install PostgreSQL 17 contract-test binaries")
    suite = next(s for s in steps if s.get("run", "").startswith("python -m pytest tests/ -v "))
    assert steps.index(packages) < steps.index(smoke) < steps.index(suite)
    assert "if" not in suite and "continue-on-error" not in suite


def test_required_check_fails_for_unsuccessful_or_skipped_partition(workflow):
    gate = workflow["jobs"]["test"]
    assert gate["needs"] == ["test-partition", "test-dashboard"]
    assert gate["if"] == (
        "always() && github.event_name == 'pull_request' && github.head_ref != 'daily-plan-current'"
    )
    step, = gate["steps"]
    assert step["env"] == {
        "PARTITION_RESULT": "${{ needs.test-partition.result }}",
        "DASHBOARD_RESULT": "${{ needs.test-dashboard.result }}",
    }
    assert step["run"] == 'test "$PARTITION_RESULT" = success && test "$DASHBOARD_RESULT" = success'
    # Exercise the actual gate, including GitHub's skipped dependency outcome.
    import subprocess
    results = ("success", "failure", "cancelled", "skipped", "")
    for partition_result in results:
        for dashboard_result in results:
            completed = subprocess.run(["sh", "-c", step["run"]], env={
                "PARTITION_RESULT": partition_result, "DASHBOARD_RESULT": dashboard_result,
            })
            assert (completed.returncode == 0) == (partition_result == dashboard_result == "success")


def test_partitions_preserve_every_check_without_repeating_dashboard(workflow):
    worker = workflow["jobs"]["test-partition"]
    assert worker["strategy"] == {
        "fail-fast": "false", "matrix": {"include": [
            {"partition":"core", "postgres-shard":"all"},
            {"partition":"media", "postgres-shard":"all"},
            *({"partition":"postgres", "postgres-shard":str(shard)} for shard in range(12)),
        ]},
    }
    for step in worker["steps"]:
        assert step.get("name") not in {"Test dashboard", "Build dashboard"}
        if step.get("name") == "SQLite backend smoke":
            assert step["if"] == "matrix.partition == 'core'"
    suite = next(s for s in worker["steps"] if s.get("run", "").startswith("python -m pytest tests/ -v "))
    assert "if" not in suite and "continue-on-error" not in worker


def test_dashboard_checks_have_a_separate_bounded_offline_job(workflow):
    dashboard = workflow["jobs"]["test-dashboard"]
    assert dashboard["timeout-minutes"] == "10"
    assert "env" not in dashboard and "continue-on-error" not in dashboard
    steps = dashboard["steps"]
    assert [step.get("run") for step in steps if "run" in step] == [
        "pip install -r requirements.txt -r requirements-postgres.txt -r requirements-graphics.txt",
        "npm ci",
        "npm test -- --test-concurrency=4",
        "npm run build",
    ]
    assert all(step.get("working-directory") == "dashboard" for step in steps[-3:])
    assert all("if" not in step and "continue-on-error" not in step and "env" not in step for step in steps)


def test_postgres_ingress_has_node_and_dashboard_dependencies(workflow):
    steps = workflow["jobs"]["test-partition"]["steps"]
    node, = [step for step in steps if step.get("uses") == "actions/setup-node@v6"]
    dependencies, = [step for step in steps if step.get("name") == "Install dashboard dependencies"]
    assert node["if"] == dependencies["if"] == "matrix.partition != 'media'"
    assert node["with"]["node-version"] == "24"
    assert node["with"]["cache-dependency-path"] == "dashboard/package-lock.json"
    assert dependencies["working-directory"] == "dashboard"
    assert dependencies["run"] == "npm ci"


@pytest.mark.parametrize("partition", ["all", "core", "postgres", "media"])
def test_actual_collection_hook_keeps_preview_ingress_in_postgres(partition):
    from tests.conftest import pytest_collection_modifyitems

    # Exercise the real hook with the database-backed ingress module, including
    # its separate Next/HTTP/PG test; no assertion in that module is skipped.
    paths = {
        "core": Path(__file__),
        "postgres": Path(__file__).with_name("test_postgres_preview_command_ingress.py"),
        "media": Path(__file__).with_name("test_postgres_media_commands.py"),
    }
    assert all(path.is_file() for path in paths.values())
    items = [SimpleNamespace(path=path) for path in paths.values()]
    original = list(items)
    deselected = []
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition":partition, "--ci-postgres-shard":"all",
                                "--ci-critical-first":False}[name],
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    pytest_collection_modifyitems(config, items)
    expected = list(paths.values()) if partition == "all" else [paths[partition]]
    assert [item.path for item in items] == expected
    assert {id(item) for item in items}.isdisjoint(id(item) for item in deselected)
    assert {id(item) for item in items + deselected} == {id(item) for item in original}


def _database_setup(workflow):
    steps = workflow["jobs"]["test-partition"]["steps"]
    names = (
        "Configure signed PostgreSQL test repository",
        "Refresh PostgreSQL test package metadata",
        "Install PostgreSQL 17 contract-test binaries",
    )
    selected = [step for step in steps if step.get("name") in names]
    assert [step["name"] for step in selected] == list(names)
    assert [step["timeout-minutes"] for step in selected] == ["3", "4", "5"]
    assert all(step["if"] == "matrix.partition != 'core'" for step in selected)
    assert all("continue-on-error" not in step for step in selected)
    return selected


def test_only_database_partitions_install_binaries_with_bounded_steps(workflow):
    setup = _database_setup(workflow)
    steps = workflow["jobs"]["test-partition"]["steps"]
    # Every system dependency command must live behind the same non-core guard.
    assert [step for step in steps if "sudo " in step.get("run", "")] == setup
    python_packages = next(step for step in steps if step.get("run", "").startswith("pip install"))
    assert "requirements-postgres.txt" in python_packages["run"]
    assert "if" not in python_packages and "continue-on-error" not in python_packages
    suite = next(step for step in steps if step.get("run", "").startswith("python -m pytest tests/ -v "))
    assert suite["env"] == {
        "THEHEAT_TEST_POSTGRES": "1", "THEHEAT_POSTGRES_BINDIR": "/usr/lib/postgresql/17/bin",
        "THEHEAT_CI_SAFE_DIAGNOSTIC": "${{ matrix.partition == 'postgres' && matrix.postgres-shard == '8' && '1' || '0' }}",
    }
    assert "if" not in suite and "continue-on-error" not in suite


@pytest.mark.parametrize("failure", [None, "directories", "key", "repository", "cluster", "metadata", "packages"])
@pytest.mark.parametrize("install_gdb", ["0", "1"])
def test_dependency_shell_steps_fail_closed_without_system_access(workflow, tmp_path, failure, install_gdb):
    stub = Path(__file__).parent / "fixtures/ci_dependency_stub.py"
    binary = tmp_path / "bin/sudo"
    binary.parent.mkdir()
    binary.write_text(f"#!{sys.executable}\n" + stub.read_text())
    binary.chmod(0o700)
    # No inherited BASH_ENV, credentials, network client or real sudo in PATH.
    env = {"PATH": str(binary.parent), "THEHEAT_CI_STUB_ROOT": str(tmp_path),
           "THEHEAT_CI_INSTALL_GDB": install_gdb}
    if failure:
        env["THEHEAT_CI_STUB_FAIL"] = failure
    completed_steps = []
    for step in _database_setup(workflow):
        # GitHub's unspecified Linux shell uses bash -e. The stub never invokes
        # any real package manager or downloader, even on its success path.
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-e", "-c", step["run"]],
            env=env, cwd=tmp_path, capture_output=True, text=True, timeout=10,
        )
        completed_steps.append(result.returncode)
        if result.returncode:
            break
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    phases = ["directories", "key", "repository", "cluster", "metadata", "packages"]
    if failure:
        # The injected command failure propagates, and no subsequent command
        # (even within the same shell step) or default success artifact appears.
        assert completed_steps[-1] == 47, result.stderr
        assert all(code == 0 for code in completed_steps[:-1])
        assert [call["phase"] for call in calls] == phases[:phases.index(failure) + 1]
        assert not (tmp_path / "packages.json").exists()
    else:
        assert completed_steps == [0, 0, 0], result.stderr
        assert [call["phase"] for call in calls] == phases
        expected_packages = ["postgresql-17", "postgresql-client-17", "poppler-utils"]
        if install_gdb == "1":
            expected_packages.append("gdb")
        assert json.loads((tmp_path / "packages.json").read_text()) == expected_packages


def test_immediate_python_output_is_scoped_to_bot_invocations(workflow):
    assert "PYTHONUNBUFFERED" not in workflow.get("env", {})
    locations = []
    for job_name, job in workflow["jobs"].items():
        assert "PYTHONUNBUFFERED" not in job.get("env", {})
        for step in job["steps"]:
            if "PYTHONUNBUFFERED" in step.get("env", {}):
                locations.append((job_name, step["name"], step["env"]["PYTHONUNBUFFERED"]))
    assert locations == [("run", "Service hourly sender before catch-up", "1"), ("run", "Run bot", "1")]


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
        assert child.stdout is not None and child.stderr is not None
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


def test_source_inventory_gate_fails_before_full_suite_without_waiving_tests(workflow):
    steps = workflow["jobs"]["test-partition"]["steps"]
    inventory, = [s for s in steps if s.get("run") == "python scripts/gen_source_registry.py --check"]
    assert inventory["if"] == "matrix.partition == 'core'"
    assert set(inventory) == {"name", "if", "run"}  # No ignored failure or credential context.
    policy = next(s for s in steps if s.get("run") == "python scripts/gen_editorial_policy.py --check")
    runtime = next(s for s in steps if s.get("run") == "python scripts/gen_dashboard_graphic_runtime.py --check")
    suite = next(s for s in steps if s.get("run", "").startswith("python -m pytest tests/ -v "))
    assert steps.index(inventory) < steps.index(policy) < steps.index(runtime) < steps.index(suite)
    assert "if" not in suite and "continue-on-error" not in suite
