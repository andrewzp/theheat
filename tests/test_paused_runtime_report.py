"""A configuration-only invocation cannot generate, post, or replace state.json."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from scripts import gen_runtime_report_workflow as workflow
from scripts import runtime_report as report

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, 19, tzinfo=UTC)


def packet():
    return {"schema_version": 1, "kind": "configuration_only", "id": "config-123-1", "run_attempt": 1,
            "started_at": NOW.isoformat(), "collection_paused": True, "runtime_inventory": {}}


def file(value):
    return {"content": report.encode(value)} if value is not None else None


def test_actual_collector_is_zero_network_and_keeps_only_loaded_presence(monkeypatch):
    # Fresh interpreter: real module constants are loaded from this invented profile.
    env = {**os.environ, "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "a" * 40,
           "EXPECTED_COMMIT_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
           "THEHEAT_PRODUCTION_PAUSED": "1", "THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "0",
           "THEHEAT_CRITIC_ENABLED": "1", "THEHEAT_WRITER_SAMPLES": "1", "THEHEAT_CRITIC_REVISE_ENABLED": "0",
           "THEHEAT_STATE_BACKEND": "gist", "GIST_ID": "b" * 32, "GITHUB_TOKEN": "invented-secret",
           "ANTHROPIC_API_KEY": "invented-secret", "GEMINI_API_KEY": "invented-secret"}
    code = '''
import json, os, socket, subprocess
import requests, httpx
from unittest.mock import patch
from datetime import datetime, UTC
from scripts.runtime_report import build_report

def blocked(*a, **kw): raise AssertionError("Unexpected external operation")
with patch.object(socket.socket, "connect", blocked), patch.object(socket, "create_connection", blocked), \
     patch.object(requests.sessions.Session, "request", blocked), patch.object(httpx.Client, "send", blocked), \
     patch.object(subprocess, "run", blocked), patch.object(subprocess, "Popen", blocked):
    print(json.dumps(build_report(dict(os.environ), now=datetime(2026,10,16,19,tzinfo=UTC))))
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    value = json.loads(result.stdout)
    snapshot = value["runtime_inventory"]
    assert value["id"] == "config-123-1" and snapshot["captured_at"] == value["started_at"]
    assert snapshot["mode"] == "runtime_report"
    assert snapshot["models"]["writer"] == "claude-sonnet-4-6"
    assert snapshot["editorial_policy"]["flags"]["writer_samples"] == 1
    assert set(snapshot["credentials_present"]) == {"anthropic", "gemini", "safety_gemini", "github_state"}
    assert all(snapshot["credentials_present"].values())
    assert snapshot["flags"] == {"writer_samples": 1, "critic_enabled": True,
                                 "critic_revise_enabled": False, "automatic_publication_enabled": False}
    assert "invented-secret" not in result.stdout


@pytest.mark.parametrize("change", [{"THEHEAT_PRODUCTION_PAUSED": "0"}, {"GITHUB_REF": "refs/heads/unreviewed"},
    {"THEHEAT_AUTOMATIC_PUBLICATION_ENABLED": "1"}, {"EXPECTED_COMMIT_SHA": "b" * 40}, {"GITHUB_RUN_ATTEMPT": "0"}])
def test_configuration_identity_and_pause_required(change):
    env = {"GITHUB_REF": "refs/heads/main", "THEHEAT_PRODUCTION_PAUSED": "1", "GITHUB_SHA": "a" * 40,
           "EXPECTED_COMMIT_SHA": "a" * 40, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", **change}
    with pytest.raises(report.ReportError):
        report.build_report(env, now=NOW)


@pytest.mark.parametrize("lost_ack", [False, True])
def test_single_file_patch_and_lost_ack_readback_do_not_resend(lost_ack):
    value, calls = packet(), []
    stored = None

    def api(method, payload):
        nonlocal stored
        calls.append((method, deepcopy(payload)))
        if method == "GET":
            return file(stored)
        assert set(payload["files"]) == {"runtime-inventory.json"}
        stored = json.loads(payload["files"]["runtime-inventory.json"]["content"])
        if lost_ack:
            raise TimeoutError("secret response body")
    result = report.publish_report(value, api)
    assert [method for method, _ in calls] == ["GET", "PATCH", "GET"]
    assert result["status"] == "confirmed" and result["state_json_written"] is False
    assert result["provider_calls"] == 0


def test_unconfirmed_write_stops_without_retry():
    calls = []

    def api(method, payload):
        calls.append(method)
        if method == "PATCH":
            raise TimeoutError("unknown")
        return None
    with pytest.raises(report.ReportError, match="write_unconfirmed"):
        report.publish_report(packet(), api)
    assert calls == ["GET", "PATCH", "GET"]


@pytest.mark.parametrize("case", ["same", "conflict", "newer", "truncated", "malformed"])
def test_existing_evidence_is_not_blindly_overwritten(case):
    value, current, calls = packet(), packet(), []
    if case == "conflict":
        current["collection_paused"] = False
    elif case == "newer":
        current.update(id="config-124-1", started_at=(NOW + timedelta(minutes=1)).isoformat())
    response = file(current)
    if case == "truncated":
        response["truncated"] = True
    if case == "malformed":
        response["content"] = "not json"

    def api(method, payload):
        calls.append(method)
        return response
    if case == "same":
        assert report.publish_report(value, api)["status"] == "already_confirmed"
    else:
        with pytest.raises((report.ReportError, ValueError)):
            report.publish_report(value, api)
    assert calls == ["GET"]


def test_new_source_controls_are_mirrored_without_activating_a_source_lane():
    controls = {"THEHEAT_PM25_FORECAST_AUTO_TEXT", "THEHEAT_DUST_FORECAST_AUTO_TEXT",
        "THEHEAT_NHC_ADVISORY_AUTO_TEXT", "THEHEAT_OFFICIAL_WARNING_AUTO_TEXT", "THEHEAT_NWS_WARNING_AUTO_TEXT",
        "THEHEAT_REGIONAL_OBSERVED", "THEHEAT_RAINFALL_WINDOW_PROVENANCE", "THEHEAT_HAZARD_EPISODES",
        "THEHEAT_PORTFOLIO_SELECTION", "THEHEAT_RAINFALL_REGIONAL_SCAN"}
    rendered = yaml.load(workflow.render(), Loader=yaml.BaseLoader)
    generated = rendered["jobs"]["report"]["steps"][-1]
    bot = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    normal = next(s["env"] for s in bot["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    assert controls <= generated["env"].keys()
    assert all(generated["env"][key] == normal[key] for key in controls)
    assert generated["run"] == "python scripts/runtime_report.py"


def test_workflow_profile_parity_and_no_posting_or_source_lane():
    generated = workflow.render()
    assert (ROOT / ".github/workflows/runtime-report.yml").read_text() == generated
    doc = yaml.load(generated, Loader=yaml.BaseLoader)
    assert set(doc["on"]) == {"workflow_dispatch"}
    assert set(doc["on"]["workflow_dispatch"]["inputs"]) == {"expected_commit_sha"}
    job = doc["jobs"]["report"]
    assert "refs/heads/main" in job["if"] and "THEHEAT_PRODUCTION_PAUSED == '1'" in job["if"]
    step = job["steps"][-1]
    assert step["run"] == "python scripts/runtime_report.py"
    assert set(step["env"]) <= workflow.PROFILE_KEYS | {"EXPECTED_COMMIT_SHA", "THEHEAT_PRODUCTION_PAUSED"}
    assert "TWITTER" not in generated and "BLUESKY" not in generated
    bot = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    normal = next(s["env"] for s in bot["jobs"]["run"]["steps"] if s.get("name") == "Run bot")
    for key in workflow.PROFILE_KEYS & normal.keys():
        assert step["env"][key] == normal[key]
    assert "src.main" not in generated and "finite_sample" not in generated


@pytest.mark.parametrize("payload", [{"files": {"state.json": {"content": "{}"}}},
    {"files": {report.FILENAME: {"filename": "state.json", "content": "{}"}}},
    {"files": {report.FILENAME: {"content": "x" * (report.MAX_BYTES + 1)}}}])
def test_transport_rejects_other_file_rename_or_oversize_before_network(monkeypatch, payload):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not run gh for a disallowed payload")
    monkeypatch.setattr(report.subprocess, "run", forbidden)
    api = report.github_api("b" * 32, {"GITHUB_TOKEN": "invented"})
    with pytest.raises(report.ReportError, match="disallowed_operation"):
        api("PATCH", payload)


def test_cli_null_is_wrapped_to_distinguish_a_missing_report_from_an_empty_response(monkeypatch):
    def command(args, **kwargs):
        # Real gh --jq emits nothing for a top-level null, reproduced live read-only.
        query = args[args.index('--jq') + 1]
        stdout = '{"runtime_report_file":null}\n' if query == '{runtime_report_file:(.files["runtime-inventory.json"] // null)}' else ''
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr='')
    monkeypatch.setattr(report.subprocess, 'run', command)
    assert report.github_api('b' * 32, {'GITHUB_TOKEN': 'invented'})('GET', None) is None


@pytest.mark.parametrize('stdout', ['', 'null', '{}', '[]', '{"unexpected":null}', '{"runtime_report_file":false}', 'broken'])
def test_unexpected_cli_envelope_never_becomes_a_missing_report(monkeypatch, stdout):
    monkeypatch.setattr(report.subprocess, 'run', lambda args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=stdout, stderr=''))
    with pytest.raises(report.ReportError, match='response_invalid'):
        report.github_api('b' * 32, {'GITHUB_TOKEN': 'invented'})('GET', None)


def test_first_file_publish_roundtrip_uses_wrapped_cli_reads_and_one_patch(monkeypatch):
    stored, calls = None, []
    def command(args, **kwargs):
        nonlocal stored
        if '--jq' in args:
            calls.append('GET')
            assert args[args.index('--jq') + 1] == '{runtime_report_file:(.files["runtime-inventory.json"] // null)}'
            stdout = json.dumps({'runtime_report_file': stored})
        else:
            calls.append('PATCH')
            assert args[args.index('--method') + 1] == 'PATCH'
            payload = json.loads(kwargs['input'])
            assert list(payload['files']) == [report.FILENAME]
            stored = payload['files'][report.FILENAME]
            stdout = ''
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr='')
    monkeypatch.setattr(report.subprocess, 'run', command)
    result = report.publish_report(packet(), report.github_api('b' * 32, {'GITHUB_TOKEN': 'invented'}))
    assert result['status'] == 'confirmed'
    assert calls == ['GET', 'PATCH', 'GET']
