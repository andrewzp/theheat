"""Bounded catch-up reservation on invented Gist transport and the real workflow shell."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
import requests
import yaml

from scripts import alerts_lane_catchup
from src import state
from src.commands import gist_route

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "invented/theheat"
GIST_ID = "123abc"
NOW = datetime(2026, 11, 4, 19, 41, tzinfo=UTC)
BUDGET = {"THEHEAT_TRIAGE_ENABLED": "1", "THEHEAT_MAX_DRAFTS_PER_CYCLE": "1", "THEHEAT_WRITER_SAMPLES": "1",
          "THEHEAT_REFILL_ENABLED": "0", "THEHEAT_CRITIC_REVISE_ENABLED": "0"}


def _receipt(run_id=None, reserved_at=None):
    return {
        "truncated": False,
        "content": json.dumps({"schema_version": 1, "repository": REPOSITORY, "run_id": run_id,
                               "reserved_at": reserved_at}, sort_keys=True, separators=(",", ":")),
    }


@pytest.fixture
def gist(monkeypatch):
    for name, value in {
        "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ID": "123", "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/main", "THEHEAT_STATE_BACKEND": "gist",
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/.github/workflows/bot.yml@refs/heads/main",
        "THEHEAT_SCHEDULED_ALERTS_CATCHUP": "1", gist_route.ROUTE_ENV: "", gist_route.MARKER_ENV: "",
        **BUDGET,
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(state, "GIST_ID", GIST_ID)
    monkeypatch.setattr(state, "GITHUB_TOKEN", "invented-token")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return NOW

    monkeypatch.setattr(state, "datetime", Clock)
    data = {"id": GIST_ID, "public": False, "files": {
        state.ALERTS_CATCHUP_FILENAME: _receipt(), state.STATE_FILENAME: {"content": "unchanged"},
    }}
    transport = SimpleNamespace(data=data, calls=[], lost_patch_response=False, stale_readback=False)

    def check_request(url, headers, timeout, allow_redirects):
        assert url == f"https://api.github.com/gists/{GIST_ID}"
        assert headers["Authorization"] == "token invented-token"
        assert timeout == 5 and allow_redirects is False

    def get(url, *, headers, timeout, allow_redirects):
        check_request(url, headers, timeout, allow_redirects)
        assert headers["Cache-Control"] == "no-cache"
        transport.calls.append("GET")
        snapshot = deepcopy(data)
        if transport.stale_readback and "PATCH" in transport.calls:
            snapshot["files"][state.ALERTS_CATCHUP_FILENAME] = _receipt()
        return SimpleNamespace(status_code=200, json=lambda: snapshot)

    def patch(url, *, headers, timeout, allow_redirects, json):
        check_request(url, headers, timeout, allow_redirects)
        assert set(json) == {"files"} and set(json["files"]) == {state.ALERTS_CATCHUP_FILENAME}
        transport.calls.append("PATCH")
        data["files"][state.ALERTS_CATCHUP_FILENAME] = {"truncated": False, **json["files"][state.ALERTS_CATCHUP_FILENAME]}
        if transport.lost_patch_response:
            raise requests.Timeout("invented response loss after persistence")
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(state.requests, "get", get)
    monkeypatch.setattr(state.requests, "patch", patch)
    return transport


def test_interrupted_collector_still_consumes_one_extra_slot(gist, monkeypatch):
    assert alerts_lane_catchup.main(["--reserve"]) == 0
    assert gist.calls == ["GET", "PATCH", "GET"]
    assert gist.data["files"][state.STATE_FILENAME] == {"content": "unchanged"}
    assert gist.data["files"][state.ALERTS_CATCHUP_FILENAME] == _receipt("123", NOW.isoformat())
    # The collector dies before saving a run history entry. The next run still holds.
    monkeypatch.setenv("GITHUB_RUN_ID", "124")
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls == ["GET", "PATCH", "GET", "GET"]


@pytest.mark.parametrize("failure", ["lost_patch_response", "stale_readback"])
def test_uncertain_reservation_never_permits_collection(gist, monkeypatch, failure):
    setattr(gist, failure, True)
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls.count("PATCH") == 1
    assert len(gist.calls) == (2 if failure == "lost_patch_response" else 3)
    setattr(gist, failure, False)
    monkeypatch.setenv("GITHUB_RUN_ID", "124")
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls.count("PATCH") == 1


@pytest.mark.parametrize("failure", ["missing", "public", "wrong_gist", "wrong_repo", "truncated", "truncated_gist",
                                     "duplicate", "future", "naive"])
def test_missing_or_unknown_reservation_refuses_without_writing(gist, failure):
    files = gist.data["files"]
    record = files[state.ALERTS_CATCHUP_FILENAME]
    if failure == "missing":
        files.pop(state.ALERTS_CATCHUP_FILENAME)
    elif failure == "public":
        gist.data["public"] = True
    elif failure == "wrong_gist":
        gist.data["id"] = "other"
    elif failure == "wrong_repo":
        record["content"] = record["content"].replace(REPOSITORY, "other/theheat")
    elif failure == "truncated":
        record["truncated"] = True
    elif failure == "truncated_gist":
        gist.data["truncated"] = True
    elif failure == "duplicate":
        record["content"] = record["content"].replace('"run_id":null', '"run_id":"777","run_id":null')
    elif failure == "future":
        files[state.ALERTS_CATCHUP_FILENAME] = _receipt("122", (NOW + timedelta(seconds=1)).isoformat())
    else:
        files[state.ALERTS_CATCHUP_FILENAME] = _receipt("122", NOW.replace(tzinfo=None).isoformat())
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls == ["GET"]


@pytest.mark.parametrize("name,value", [
    ("THEHEAT_SCHEDULED_ALERTS_CATCHUP", "0"), ("GITHUB_RUN_ATTEMPT", "2"),
    ("GITHUB_EVENT_NAME", "workflow_dispatch"), ("GITHUB_REF", "refs/tags/main"),
    ("GITHUB_WORKFLOW_REF", f"{REPOSITORY}/.github/workflows/other.yml@refs/heads/main"),
    ("THEHEAT_STATE_BACKEND", "sqlite"),
])
def test_wrong_run_context_never_contacts_gist(gist, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls == []


@pytest.mark.parametrize("setting", BUDGET)
def test_extra_collection_requires_the_single_candidate_budget(gist, monkeypatch, setting):
    monkeypatch.setenv(setting, "0" if BUDGET[setting] == "1" else "1")
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls == []


@pytest.mark.parametrize("run_id,age_seconds,expected", [("122", 17099, 2), ("122", 17100, 0), ("123", 17100, 2)])
def test_reservation_window_and_run_identity(gist, run_id, age_seconds, expected):
    gist.data["files"][state.ALERTS_CATCHUP_FILENAME] = _receipt(run_id, (NOW - timedelta(seconds=age_seconds)).isoformat())
    assert alerts_lane_catchup.main(["--reserve"]) == expected
    assert gist.calls == (["GET", "PATCH", "GET"] if expected == 0 else ["GET"])


def test_reservation_obeys_serialized_route_writer_fence(gist, monkeypatch):
    monkeypatch.setenv(gist_route.ROUTE_ENV, "serialized")
    assert alerts_lane_catchup.main(["--reserve"]) == 2
    assert gist.calls == ["GET"]
    monkeypatch.setenv(gist_route.MARKER_ENV, "123:run")
    assert alerts_lane_catchup.main(["--reserve"]) == 0
    assert gist.calls == ["GET", "GET", "PATCH", "GET"]


@pytest.mark.parametrize("sender,reservation,collector,expected,exit_code", [
    (0, 0, 0, ["auto_publish_due", "reserve", "alerts"], 0),
    (0, 2, 0, ["auto_publish_due", "reserve"], 0),
    (0, 124, 0, ["auto_publish_due", "reserve"], 0),
    (1, 0, 0, ["auto_publish_due"], 1),
    (0, 0, 1, ["auto_publish_due", "reserve", "alerts"], 1),
])
def test_real_run_step_sends_first_and_collects_only_after_reservation(tmp_path, sender, reservation, collector, expected, exit_code):
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["run"]["steps"]
    by_name = {item["name"]: item for item in steps if "name" in item}
    due = by_name["Service hourly sender before catch-up"]
    reserve = by_name["Reserve additional catch-up"]
    cache = by_name["Restore station thresholds cache"]
    verify = by_name["Validate or download checksum-bound station thresholds"]
    bot = by_name["Run bot"]
    indices = [steps.index(item) for item in (due, reserve, cache, verify, bot)]
    assert indices == sorted(indices) and len(set(indices)) == len(indices)
    assert due["env"] == bot["env"]
    assert all(reserve["env"][name] == bot["env"][name] for name in BUDGET)
    assert due["if"] == reserve["if"] == "steps.mode.outputs.catchup == '1'"
    gate = "steps.mode.outputs.catchup != '1' || steps.catchup-reservation.outputs.confirmed == '1'"
    assert all(gate in item["if"] for item in (cache, verify, bot))
    assert "continue-on-error" not in due and "continue-on-error" not in reserve
    bot_script = (bot["run"].replace("${{ steps.mode.outputs.mode }}", "alerts")
                  .replace("${{ steps.mode.outputs.catchup }}", "1"))
    script = due["run"] + "\n" + reserve["run"] + '\nif [[ "$(<"$GITHUB_OUTPUT")" == confirmed=1 ]]; then\n' + bot_script + "\nfi\n"
    python = tmp_path / "python"
    python.write_text('#!/bin/bash\ncase "$2 $3" in\n'
                      '  "src.main auto_publish_due") echo auto_publish_due; exit "$SENDER";;\n'
                      '  "scripts.alerts_lane_catchup --reserve") [[ "$THEHEAT_SCHEDULED_ALERTS_CATCHUP" == 1 ]] || exit 99; echo reserve; exit "$RESERVATION";;\n'
                      '  "src.main alerts") echo alerts; exit "$COLLECTOR";;\n'
                      '  *) exit 99;;\nesac\n')
    python.chmod(0o755)
    timeout = tmp_path / "timeout"
    timeout.write_text('#!/bin/bash\n[[ "$1 $2 $3" == "-k 1s 20s" ]] || exit 99\nshift 3\nexec "$@"\n')
    timeout.chmod(0o755)
    output = tmp_path / "output"
    output.touch()
    result = subprocess.run(["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                            env={"PATH": str(tmp_path), "SENDER": str(sender), "RESERVATION": str(reservation),
                                 "COLLECTOR": str(collector), "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "0",
                                 "THEHEAT_SCHEDULED_ALERTS_CATCHUP": "1", "GITHUB_OUTPUT": str(output)},
                            capture_output=True, text=True, timeout=5, check=False)
    assert result.stdout.splitlines() == expected and result.returncode == exit_code
