"""The hourly slot collects alerts when GitHub skipped the alert slots, and only then.

Exercises scripts/alerts_lane_catchup.py directly and through the real bot.yml mode step
(bash, with an offline stand-in for `gh gist view` serving an invented state copy).
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import alerts_lane_catchup as catchup  # noqa: E402

NOW = datetime(2026, 11, 4, 15, 41, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _state(*runs: tuple[str, datetime, str]) -> dict:
    return {"run_history": [{"mode": mode, "started_at": _iso(at), "status": status} for mode, at, status in runs]}


def _run(state, tmp_path, *, max_age=None):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state) if not isinstance(state, str) else state)
    argv = [str(path)] + ([f"--max-age-minutes={max_age}"] if max_age is not None else [])
    return catchup.main(argv, now=NOW)


def test_stale_lane_after_skipped_slots_collects(tmp_path):
    # 4 November: last alerts run 04:00, then only hourly sender runs fired.
    state = _state(("auto_publish_due", NOW - timedelta(minutes=5), "success"),
                   ("auto_publish_due", NOW - timedelta(hours=9), "partial_failure"),
                   ("alerts", NOW - timedelta(hours=11, minutes=41), "partial_failure"))
    assert _run(state, tmp_path) == 0


def test_fresh_lane_keeps_the_hourly_role(tmp_path):
    state = _state(("alerts", NOW - timedelta(minutes=30), "success"))
    assert _run(state, tmp_path) == 1


def test_window_boundary_and_delayed_slot_tolerance(tmp_path):
    # Exactly at the window: fresh. One minute past: collect. The default window exceeds the
    # 4 h cadence by 45 min, so a slot delayed ~30 min does not also trigger a catch-up.
    assert _run(_state(("alerts", NOW - timedelta(minutes=285), "success")), tmp_path) == 1
    assert _run(_state(("alerts", NOW - timedelta(minutes=286), "success")), tmp_path) == 0
    assert _run(_state(("alerts", NOW - timedelta(hours=4, minutes=30), "success")), tmp_path) == 1


def test_both_mode_and_failed_collection_runs_still_reset_the_clock(tmp_path):
    # Measured from the newest STARTED alerts/both run whatever its outcome: a failing source
    # run cannot make every hourly slot a collection run (no cost runaway).
    assert _run(_state(("both", NOW - timedelta(hours=1), "success")), tmp_path) == 1
    assert _run(_state(("alerts", NOW - timedelta(hours=1), "failed")), tmp_path) == 1
    assert _run(_state(("leaderboard", NOW - timedelta(hours=1), "success")), tmp_path) == 2


def test_no_collection_history_keeps_sender_role(tmp_path):
    assert _run({"run_history": []}, tmp_path) == 2


@pytest.mark.parametrize("bad", ["not json", "[]", json.dumps({"drafts": []}),
                                 json.dumps({"run_history": "oops"})])
def test_unreadable_state_never_escalates(tmp_path, bad):
    assert _run(bad, tmp_path) == 2


def test_missing_file_and_invalid_window_never_escalate(tmp_path):
    assert catchup.main([str(tmp_path / "absent.json")], now=NOW) == 2
    assert _run(_state(), tmp_path, max_age=0) == 2


@pytest.mark.parametrize("row", ["x", {"mode": "alrets"}, {"mode": "alerts", "started_at": "garbage"},
                                {"mode": "both", "started_at": "2026-11-03T14:00:00"},
                                {"mode": "alerts", "started_at": "2026-11-04T16:00:00Z"}])
def test_unknown_history_keeps_sender_even_with_older_valid_alert(tmp_path, row):
    state = _state(("alerts", NOW - timedelta(hours=12), "success"))
    state["run_history"].append(row)
    assert _run(state, tmp_path) == 2


# --- through the real bot.yml mode step ------------------------------------------------------

def _mode_step():
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    return next(step for step in workflow["jobs"]["run"]["steps"] if step.get("id") == "mode")


def _select(tmp_path, *, schedule, gist_id="invented-gist", state=None, gh_fails=False,
            enabled="1", attempt="1", ref="refs/heads/main", event="schedule", gist_timeout=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    served = tmp_path / "served-state.json"
    if state is not None:
        served.write_text(json.dumps(state))
    gh = bin_dir / "gh"
    # Offline stand-in: only `gh gist view <id> -f state.json` is answered.
    gh.write_text("#!/bin/bash\ntouch \"$RUNNER_TEMP/gist-queried\"\n"
                  + ("exit 1\n" if gh_fails else
                     f'[ "$1 $2 $3 $4 $5" = "gist view {gist_id} -f state.json" ] || exit 9\ncat "{served}"\n'))
    gh.chmod(0o755)
    timeout = bin_dir / "timeout"
    timeout.write_text('#!/bin/bash\n[[ "$1 $2 $3" == "-k 1s 8s" ]] || exit 99\n'
                       '[[ "${FIXTURE_TIMEOUT:-0}" != 1 ]] || exit 124\nshift 3\nexec "$@"\n')
    timeout.chmod(0o755)
    (bin_dir / "python").unlink(missing_ok=True)
    (bin_dir / "python").symlink_to(sys.executable)
    script = (_mode_step()["run"].replace("${{ github.event_name }}", event)
              .replace("${{ github.event.schedule }}", schedule)
              .replace("${{ github.event.inputs.mode }}", "alerts"))
    output = tmp_path / "github-output"
    output.unlink(missing_ok=True)
    env = {"GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin",
           "GITHUB_EVENT_NAME": event, "GITHUB_RUN_ATTEMPT": attempt, "GITHUB_REF": ref,
           "THEHEAT_SCHEDULED_ALERTS_CATCHUP": enabled, "FIXTURE_TIMEOUT": "1" if gist_timeout else "0"}
    if gist_id:
        env["GIST_ID"] = gist_id
    subprocess.run(["/bin/bash", "-e", "-c", script], env=env, cwd=ROOT, check=True, timeout=30)
    assert not list(tmp_path.glob("theheat-alerts-state.*"))
    return output.read_text()


def _now_state(hours_since_alerts):
    now = datetime.now(timezone.utc)
    return _state(("alerts", now - timedelta(hours=hours_since_alerts), "success"))


def test_real_step_hourly_slot_collects_when_the_lane_is_stale(tmp_path):
    assert _select(tmp_path, schedule="41 * * * *", state=_now_state(11.7)) == "catchup=1\nmode=alerts\n"
    assert (tmp_path / "gist-queried").is_file()


def test_real_step_hourly_slot_stays_sender_when_fresh(tmp_path):
    assert _select(tmp_path, schedule="41 * * * *", state=_now_state(1)) == "mode=auto_publish_due\n"


@pytest.mark.parametrize("context", [{"enabled": "0"}, {"enabled": ""}, {"attempt": "2"},
                                    {"attempt": ""}, {"ref": "refs/tags/main"}, {"ref": "refs/heads/other"}])
def test_real_step_unsafe_hourly_context_keeps_sender_without_gist_read(tmp_path, context):
    assert _select(tmp_path, schedule="41 * * * *", state=_now_state(12), **context) == "mode=auto_publish_due\n"
    assert not (tmp_path / "gist-queried").exists()


def test_real_step_manual_input_keeps_original_mode_without_gist_read(tmp_path):
    assert _select(tmp_path, schedule="41 * * * *", event="workflow_dispatch", state=_now_state(12)) == "mode=alerts\n"
    assert not (tmp_path / "gist-queried").exists()


@pytest.mark.parametrize("case", ["no_gist_id", "gh_fails", "bad_state", "timeout"])
def test_real_step_any_read_failure_keeps_the_sender_role(tmp_path, case):
    kwargs = {"no_gist_id": {"gist_id": "", "state": _now_state(20)},
              "gh_fails": {"gh_fails": True},
              "bad_state": {"state": ["not", "a", "state"]},
              "timeout": {"gist_timeout": True, "state": _now_state(20)}}[case]
    assert _select(tmp_path, schedule="41 * * * *", **kwargs) == "mode=auto_publish_due\n"


@pytest.mark.parametrize("schedule,expected", [("11 12 * * *", "both"), ("11 0,4,8,16,20 * * *", "alerts")])
def test_real_step_other_slots_never_read_state(tmp_path, schedule, expected):
    # The stand-in gh would fail; the alert/leaderboard slots must not consult it at all.
    assert _select(tmp_path, schedule=schedule, gh_fails=True) == f"mode={expected}\n"
    assert not (tmp_path / "gist-queried").exists()


def test_step_exposes_state_credentials_only_on_eligible_hourly_schedules():
    env = _mode_step()["env"]
    assert env["THEHEAT_SCHEDULED_ALERTS_CATCHUP"] == "${{ vars.THEHEAT_SCHEDULED_ALERTS_CATCHUP || '0' }}"
    for name in ("GIST_ID", "GH_TOKEN"):
        assert env[name].startswith("${{ github.event_name == 'schedule' && github.event.schedule == '41 * * * *'")
        assert "github.ref == 'refs/heads/main' && github.run_attempt == '1'" in env[name]
        assert "vars.THEHEAT_SCHEDULED_ALERTS_CATCHUP == '1'" in env[name]
    assert os.path.exists(ROOT / "scripts/alerts_lane_catchup.py")
