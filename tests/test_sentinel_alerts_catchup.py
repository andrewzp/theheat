"""The sentinel's alerts catch-up job: one ordinary alerts dispatch when the lane is stale.

GitHub drops many scheduled runs, so the sentinel (which already reads the
retained state) asks for an alerts run when the bot's own catch-up rule says
the lane is stale. These tests pin its narrow permissions and run the real
step script against the real staleness check with a fake ``gh``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/source-health-sentinel.yml"
STEP = "Dispatch one alerts run when the lane is stale"


@pytest.fixture
def workflow():
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def _job(workflow):
    return workflow["jobs"]["alerts-catchup"]


def test_only_the_catchup_job_can_start_workflows(workflow):
    assert workflow["permissions"] == {"contents": "read", "issues": "write", "actions": "read"}
    assert "permissions" not in workflow["jobs"]["sentinel"]
    job = _job(workflow)
    assert job["permissions"] == {"contents": "read", "actions": "write"}
    assert job["if"] == "vars.THEHEAT_PRODUCTION_PAUSED != '1' && github.ref == 'refs/heads/main'"
    assert "needs" not in job  # a sentinel failure must not hold the catch-up
    step = next(s for s in job["steps"] if s.get("name") == STEP)
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "gh workflow run bot.yml --repo \"$GITHUB_REPOSITORY\" --ref main -f mode=alerts" in step["run"]
    assert step["run"].count("gh workflow run") == 1


def _state(tmp_path: Path, age: timedelta | None) -> Path:
    history = []
    if age is not None:
        started = datetime.now(timezone.utc) - age
        history.append({"mode": "alerts", "started_at": started.isoformat()})
    history.append({"mode": "auto_publish_due", "started_at": datetime.now(timezone.utc).isoformat()})
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"run_history": history}))
    return path


def _run_step(workflow, tmp_path: Path, state: Path, *, active: str = "0", list_exit: int = 0):
    step = next(s for s in _job(workflow)["steps"] if s.get("name") == STEP)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "python").symlink_to(sys.executable)
    calls = tmp_path / "gh-calls"
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$*" >> "$GH_CALLS"\n'
        'if [[ "$1 $2" == "run list" ]]; then\n'
        '  [[ "$GH_LIST_EXIT" == 0 ]] || exit "$GH_LIST_EXIT"\n'
        '  printf "%s\\n" "$GH_ACTIVE"\n'
        "fi\n"
    )
    gh.chmod(0o755)
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    (runner_temp / "state.json").write_text(state.read_text())
    result = subprocess.run(
        ["/bin/bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env={
            "PATH": f"{bindir}:{os.environ.get('PATH', '')}",
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_REPOSITORY": "andrewzp/theheat",
            "GH_CALLS": str(calls),
            "GH_ACTIVE": active,
            "GH_LIST_EXIT": str(list_exit),
        },
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    return calls.read_text().splitlines() if calls.exists() else []


def test_stale_lane_with_no_active_bot_run_dispatches_one_alerts_run(workflow, tmp_path):
    calls = _run_step(workflow, tmp_path, _state(tmp_path, timedelta(hours=9)))
    assert len(calls) == 2 and calls[0].startswith("run list ")
    assert calls[1] == "workflow run bot.yml --repo andrewzp/theheat --ref main -f mode=alerts"


@pytest.mark.parametrize("age", [timedelta(hours=1), timedelta(minutes=280)])
def test_recent_lane_dispatches_nothing(workflow, tmp_path, age):
    assert _run_step(workflow, tmp_path, _state(tmp_path, age)) == []


def test_unreadable_or_missing_alerts_evidence_dispatches_nothing(workflow, tmp_path):
    assert _run_step(workflow, tmp_path, _state(tmp_path, None)) == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    other = tmp_path / "other"
    other.mkdir()
    assert _run_step(workflow, other, bad) == []


def test_active_bot_run_holds_the_dispatch(workflow, tmp_path):
    calls = _run_step(workflow, tmp_path, _state(tmp_path, timedelta(hours=9)), active="1")
    assert len(calls) == 1 and calls[0].startswith("run list ")


def test_unknown_bot_activity_holds_the_dispatch(workflow, tmp_path):
    calls = _run_step(workflow, tmp_path, _state(tmp_path, timedelta(hours=9)), list_exit=1)
    assert len(calls) == 1 and calls[0].startswith("run list ")
