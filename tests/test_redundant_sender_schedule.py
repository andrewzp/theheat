"""Real workflow selection with invented state; no workflow dispatch or network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess

import pytest
import yaml

from tests.test_alerts_lane_catchup import _mode_step, _now_state, _select, _state

ROOT = Path(__file__).resolve().parents[1]
HOURLY = "41 * * * *"
AUXILIARY = "11 1,2,3,5,6,7,9,10,11,13,14,15,17,18,19,21,22,23 * * *"
SOURCE = {"11 12 * * *", "11 0,4,8,16,20 * * *"}


def minutes(cron):
    minute, hours, *days = cron.split()
    assert days == ["*", "*", "*"]
    values = range(24) if hours == "*" else [int(h) for h in hours.split(",")]
    return {int(h) * 60 + int(minute) for h in values}


def test_exact_old_roles_and_eighteen_non_source_hour_checks_share_one_grid():
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    entries = [r["cron"] for r in workflow["on"]["schedule"]]
    assert len(entries) == len(set(entries)) == 4
    assert set(entries) == SOURCE | {HOURLY, AUXILIARY}
    old = set().union(*(minutes(s) for s in SOURCE | {HOURLY}))
    auxiliary = minutes(AUXILIARY)
    all_slots = set().union(*(minutes(s) for s in entries))
    assert len(old) == 30 and len(auxiliary) == 18 and not old & auxiliary
    assert len(all_slots) == sum(len(minutes(s)) for s in entries) == 48
    assert set().union(*(minutes(s) for s in SOURCE)) == {h * 60 + 11 for h in range(0, 24, 4)}
    ordered = sorted(all_slots)
    gaps = [(ordered[(i + 1) % len(ordered)] - value) % 1440 for i, value in enumerate(ordered)]
    assert set(gaps) == {30}
    assert int(workflow["jobs"]["run"]["timeout-minutes"]) == 20
    assert min(gaps) > int(workflow["jobs"]["run"]["timeout-minutes"])


@pytest.mark.parametrize("schedule", [HOURLY, AUXILIARY])
def test_both_sender_schedules_preserve_fresh_and_failed_collection_clocks(tmp_path, schedule):
    history = _state(("alerts", datetime.now(timezone.utc) - timedelta(hours=1), "failed"))
    assert _select(tmp_path, schedule=schedule, state=history) == "mode=auto_publish_due\n"
    assert (tmp_path / "gist-queried").is_file()


def test_auxiliary_schedule_uses_the_existing_stale_guard_and_marks_catchup(tmp_path):
    assert _select(tmp_path, schedule=AUXILIARY, state=_now_state(12)) == "catchup=1\nmode=alerts\n"
    assert (tmp_path / "gist-queried").is_file()


@pytest.mark.parametrize("context", [
    {"enabled": "0"}, {"enabled": ""}, {"attempt": "2"}, {"attempt": ""},
    {"ref": "refs/tags/main"}, {"ref": "refs/heads/other"}, {"gist_id": ""},
    {"event": "pull_request"}, {"event": "repository_dispatch"},
])
def test_auxiliary_invalid_context_never_reads_state_or_escalates(tmp_path, context):
    assert _select(tmp_path, schedule=AUXILIARY, state=_now_state(12),
                   **context) == "mode=auto_publish_due\n"
    assert not (tmp_path / "gist-queried").exists()


@pytest.mark.parametrize("case", ["gh_fails", "timeout", "unreadable", "no_alert_history"])
def test_auxiliary_unknown_history_keeps_sender_role(tmp_path, case):
    kwargs = {"gh_fails": {"gh_fails": True}, "timeout": {"gist_timeout": True},
              "unreadable": {"state": ["invented", "invalid"]},
              "no_alert_history": {"state": {"run_history": []}}}[case]
    assert _select(tmp_path, schedule=AUXILIARY, **kwargs) == "mode=auto_publish_due\n"


def test_dispatch_remains_its_explicit_role_without_the_auxiliary_state_read(tmp_path):
    assert _select(tmp_path, schedule=AUXILIARY, event="workflow_dispatch",
                   state=_now_state(12)) == "mode=alerts\n"
    assert not (tmp_path / "gist-queried").exists()


@pytest.mark.parametrize("schedule", [
    "11 1-3,5-7,9-11,13-15,17-19,21-23 * * *",
    "41 0-23 * * *", "11 0,4,8,16,21 * * *", "",
])
def test_unrecognized_schedule_cannot_fall_through_to_unconditional_collection(tmp_path, schedule):
    with pytest.raises(subprocess.CalledProcessError) as error:
        _select(tmp_path, schedule=schedule, state=_now_state(1))
    assert error.value.returncode == 2
    assert not (tmp_path / "gist-queried").exists()
    assert not (tmp_path / "github-output").exists()


def test_exact_credential_expression_preserves_all_existing_context_and_route_guards():
    # Recognize the reviewed narrow GitHub expression shape; this is not a
    # general expression interpreter or proof of GitHub's scheduling delivery.
    env = _mode_step()["env"]
    common = ("${{ github.event_name == 'schedule' && "
              f"(github.event.schedule == '{HOURLY}' || github.event.schedule == '{AUXILIARY}') "
              "&& github.ref == 'refs/heads/main' && github.run_attempt == '1' "
              "&& vars.THEHEAT_SCHEDULED_ALERTS_CATCHUP == '1' ")
    expected = {
        "GIST_ID": common + "&& secrets.GIST_ID || '' }}",
        "GH_TOKEN": common + "&& ((steps.route-mode.outputs.mode == 'serialized' && secrets.THEHEAT_GIST_WRITER_TOKEN) "
                    "|| (steps.route-mode.outputs.mode == 'legacy' && secrets.GH_GIST_TOKEN) || '') || '' }}",
    }
    for key, expression in expected.items():
        assert " ".join(env[key].split()) == expression
