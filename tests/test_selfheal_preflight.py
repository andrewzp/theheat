"""Execute the actual workflow shell gate offline, with presence booleans only."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.workflow_health import selfheal_liveness_verdict

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/workflow-self-heal.yml"


@pytest.mark.parametrize(
    "red,enabled,pat,key,allowed,reason",
    [
        ("0", "1", "true", "true", "false", "no_red_workflows"),
        ("2", "0", "true", "true", "false", "repair_not_enabled"),
        ("2", "", "true", "true", "false", "repair_not_enabled"),
        ("2", "true", "true", "true", "false", "repair_not_enabled"),
        ("2", "1", "false", "true", "false", "missing_repair_pat"),
        ("2", "1", "true", "false", "false", "missing_model_key"),
        ("2", "1", "true", "true", "true", "none"),
        ("", "1", "true", "true", "false", "invalid_detection_result"),
        ("error", "1", "true", "true", "false", "invalid_detection_result"),
    ],
)
def test_actual_gate_requires_explicit_opt_in_and_both_credentials(
    tmp_path,
    red,
    enabled,
    pat,
    key,
    allowed,
    reason,
):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(s for s in workflow["jobs"]["gate"]["steps"] if s.get("id") == "repair_preflight")
    output, summary = tmp_path / "output", tmp_path / "summary"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            "PATH": os.defpath,
            "RED_COUNT": red,
            "REPAIR_ENABLED": enabled,
            "HAS_REPAIR_PAT": pat,
            "HAS_MODEL_KEY": key,
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text() == f"repair_allowed={allowed}\nblocked_reason={reason}\n"
    assert "does not prove funded access" in summary.read_text()
    assert (
        workflow["jobs"]["gate"]["outputs"]["repair_allowed"]
        == "${{ steps.repair_preflight.outputs.repair_allowed }}"
    )
    assert workflow["jobs"]["heal"]["if"] == "needs.gate.outputs.repair_allowed == 'true'"


def test_fresh_error_beacon_is_not_mistaken_for_recovery():
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    verdict = selfheal_liveness_verdict({"run_at": now.isoformat(), "outcome": "error"}, now=now)
    assert verdict["category"] == "failing" and verdict["conclusion"] == "repair_error"
    assert verdict["last_success_at"] is None
    assert selfheal_liveness_verdict({"run_at": now.isoformat(), "outcome": "ok"}, now=now) is None


@pytest.mark.parametrize(
    "red,allowed,reason,outcome",
    [
        ("0", "false", "no_red_workflows", "ok"),
        ("2", "false", "missing_repair_pat", "error"),
        ("2", "true", "none", "pending"),
    ],
)
def test_actual_beacon_reports_blocked_repair_immediately(tmp_path, red, allowed, reason, outcome):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(s for s in workflow["jobs"]["gate"]["steps"] if "heartbeat" in s.get("name", ""))
    # A stub executable captures the exact JSON. No GitHub command or token is used.
    gh = tmp_path / "gh"
    gh.write_text(
        '#!/bin/bash\n[ "$1" = "variable" ] || exit 99\n'
        'while [ "$#" -gt 1 ]; do\n'
        '  if [ "$1" = "--body" ]; then printf "%s" "$2" > "$BEACON"; exit 0; fi\n'
        "  shift\ndone\nexit 99\n"
    )
    gh.chmod(0o700)
    beacon = tmp_path / "beacon.json"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            "PATH": str(tmp_path) + os.pathsep + os.defpath,
            "RED_COUNT": red,
            "REPAIR_ALLOWED": allowed,
            "BLOCKED_REASON": reason,
            "REPO": "offline/fixture",
            "BEACON": str(beacon),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(beacon.read_text())
    assert body["outcome"] == outcome
    assert body["blocked_reason"] == reason
    assert body["failing"] == int(red)
    verdict = selfheal_liveness_verdict(body)
    assert (verdict is not None) == (outcome == "error")
