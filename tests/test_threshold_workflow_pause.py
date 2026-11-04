"""The real collection job must stop before any source or release side effect.

This recognizes the exact approved predicate, not a general GitHub expression
interpreter. Platform CI and existing scheduled runs are separate evidence.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_threshold_pause_is_a_job_guard_for_both_existing_entry_points():
    workflow = yaml.load(
        (ROOT / ".github/workflows/refresh-thresholds.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["on"]["schedule"] == [{"cron": "0 2 * * 0"}]
    assert workflow["on"]["workflow_dispatch"]["inputs"]["days"] == {
        "description": "Days to look back in superghcnd_diff",
        "required": "false", "default": "12", "type": "string",
    }
    assert set(workflow["jobs"]) == {"refresh"}
    job = workflow["jobs"]["refresh"]
    assert job["if"] == "vars.THEHEAT_PRODUCTION_PAUSED != '1' && github.ref == 'refs/heads/main'"
    assert job["environment"] == "threshold-maintenance"
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    assert workflow["concurrency"] == {
        "group": "refresh-thresholds", "cancel-in-progress": "false",
    }
    # Job eligibility gates checkout as well as all later network/write steps.
    assert job["steps"][0] == {"uses": "actions/checkout@v6"}
    assert all("THEHEAT_PRODUCTION_PAUSED" not in str(step) for step in job["steps"])
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    for operation in (
        "scripts.threshold_artifacts ensure",
        "scripts.refresh_station_inventory",
        "scripts.update_thresholds_incremental",
        "scripts.threshold_artifacts publish",
        "git push origin HEAD:main",
    ):
        assert operation in commands


def test_threshold_resume_uploads_only_sealed_timeout_progress():
    workflow = yaml.load((ROOT / ".github/workflows/refresh-thresholds.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["refresh"]["steps"]
    update = next(step for step in steps if step.get("id") == "update")
    seal = next(step for step in steps if step.get("id") == "seal")
    retain = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v7")
    publish = next(step for step in steps if step.get("name") == "Publish verified immutable threshold artifact")
    assert 'timeout 900' in update["run"] and '"$code" == 124' in update["run"]
    assert 'exit "$code"' in update["run"]
    assert seal["if"] == "${{ !cancelled() && steps.update.outputs.timed_out == 'true' }}"
    assert retain["if"] == "${{ !cancelled() && steps.seal.outcome == 'success' }}"
    assert retain["with"]["path"] == "${{ runner.temp }}/checkpoint.aead"
    assert retain["with"]["retention-days"] == "2"
    assert "if" not in publish and "continue-on-error" not in update
    assert not any("THEHEAT_THRESHOLD_CHECKPOINT_KEY" in step.get("env", {})
                   for step in (update, retain, publish))


@pytest.mark.parametrize("enabled,exit_code", [("", 124), ("true", 124), ("true", 1), ("true", 0)])
def test_update_shell_preserves_status_and_only_marks_checkpoint_timeout(tmp_path, enabled, exit_code):
    workflow = yaml.load((ROOT / ".github/workflows/refresh-thresholds.yml").read_text(), Loader=yaml.BaseLoader)
    update = next(step for step in workflow["jobs"]["refresh"]["steps"] if step.get("id") == "update")
    timeout = tmp_path / "timeout"
    timeout.write_text('#!/bin/bash\n[[ "$1" == 900 ]] || exit 99\nshift\nprintf "%s\\n" "$@"\nexit "$FIXTURE_EXIT"\n')
    timeout.chmod(0o700)
    output = tmp_path / "output"
    result = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", update["run"]],
        env={"PATH": str(tmp_path), "RUNNER_TEMP": str(tmp_path), "GITHUB_OUTPUT": str(output),
             "THRESHOLD_DAYS": "12", "CHECKPOINT_ENABLED": enabled, "FIXTURE_EXIT": str(exit_code)},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == exit_code
    assert ("--resume-dir" in result.stdout.splitlines()) == bool(enabled)
    if enabled and exit_code == 124:
        assert output.read_text() == "timed_out=true\n"
    else:
        assert not output.exists()


@pytest.mark.parametrize("path", [
    ".github/workflows/refresh-thresholds.yml",
    ".github/workflows/refresh-thresholds.yml@refs/heads/main",
    ".github/workflows/bot.yml",
])
@pytest.mark.parametrize("conclusion", ["failure", "success"])
def test_resume_origin_script_requires_the_interrupted_maintenance_run(tmp_path, path, conclusion):
    workflow = yaml.load((ROOT / ".github/workflows/refresh-thresholds.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["refresh"]["steps"]
    verify = next(step for step in steps if step.get("name") == "Verify the selected interrupted run")
    assert "THEHEAT_THRESHOLD_CHECKPOINT_KEY" not in verify["env"]
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/bash\n[[ "$1" == api && "$2" == repos/example/repo/actions/runs/123 ]] || exit 99\n'
        'printf "%s\\n" "$FIXTURE_RUN"\n'
    )
    gh.chmod(0o700)
    jq = shutil.which("jq")
    assert jq is not None, "The refresh runner and this workflow contract test require jq"
    result = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", verify["run"]],
        env={"PATH": os.pathsep.join((str(tmp_path), str(Path(jq).parent))), "GITHUB_REPOSITORY": "example/repo",
             "THRESHOLD_RESUME_RUN": "123", "FIXTURE_RUN": json.dumps(
                 {"path": path, "head_repository": {"full_name": "example/repo"}, "head_branch": "main",
                  "event": "schedule", "run_attempt": 1, "status": "completed", "conclusion": conclusion})},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert (result.returncode == 0) == (path.startswith(".github/workflows/refresh-thresholds.yml")
                                        and conclusion == "failure")
