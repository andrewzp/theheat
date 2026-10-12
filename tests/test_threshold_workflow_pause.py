"""The real collection job must stop before any source or release side effect.

This recognizes the exact approved predicate, not a general GitHub expression
interpreter. Platform CI and existing scheduled runs are separate evidence.
"""
from pathlib import Path

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
    assert job["if"] == "vars.THEHEAT_PRODUCTION_PAUSED != '1'"
    assert job["permissions"] == {"contents": "write"}
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
