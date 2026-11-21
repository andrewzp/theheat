"""Real bounded metadata seam and sender completion, with invented HTTP only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
import yaml

from scripts import automatic_catchup_provenance as proof
from scripts import post_collection_sender as sender
from tests.test_post_collection_sender import environment, install
from tests.test_sentinel_alerts_catchup import ROOT, STEP, _run_step, _state

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def context():
    return {**environment(), "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_ACTOR": "github-actions[bot]",
        "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]", "GITHUB_SHA": SHA, "GH_TOKEN": "invented-reader",
        "REQUESTED_MODE": "alerts", "THEHEAT_AUTOMATIC_SELECTION_ONLY": "1",
        "THEHEAT_AUTOMATIC_CATCHUP_RUN_ID": "12344"}


def bodies():
    parent = {"id": 12344, "repository": {"full_name": proof.REPOSITORY},
        "head_repository": {"full_name": proof.REPOSITORY}, "head_branch": "main", "head_sha": SHA,
        "path": proof.PARENT_WORKFLOW, "event": "schedule", "run_attempt": 1,
        "created_at": "2026-11-21T15:55:00Z"}
    job = {"id": 300, "run_id": 12344, "head_sha": SHA, "name": "alerts-catchup",
        "status": "completed", "conclusion": "success", "started_at": "2026-11-21T15:56:00Z",
        "completed_at": "2026-11-21T15:58:00Z", "steps": [{"name": proof.DISPATCH_STEP,
            "status": "completed", "conclusion": "success", "started_at": "2026-11-21T15:57:00Z",
            "completed_at": "2026-11-21T15:57:30Z"}]}
    return [parent, {"total_count": 1, "jobs": [job]}]


def transport(monkeypatch, values=None, *, status=200, encoding="identity", content_type="application/json"):
    pending = list(values if values is not None else bodies())
    calls, reads, closed = [], [], []

    class Connection:
        def __init__(self, host, **kwargs):
            assert host == "api.github.com" and kwargs == {"timeout": 5}

        def request(self, method, path, *, headers):
            calls.append((method, path))
            assert method == "GET" and path.startswith("/repos/andrewzp/theheat/actions/runs/12344")
            assert headers["Authorization"] == "Bearer invented-reader"

        def getresponse(self):
            assert pending, "A third request or retry was attempted"
            value = pending.pop(0)
            if isinstance(value, Exception):
                raise value
            body = value if isinstance(value, bytes) else json.dumps(value).encode()

            def read(limit):
                reads.append(limit)
                return body[:limit]

            return SimpleNamespace(status=status, read=read,
                getheader=lambda name, default="": {"Content-Encoding": encoding,
                    "Content-Type": content_type}.get(name, default))

        def close(self):
            closed.append(True)

    monkeypatch.setattr(proof.http.client, "HTTPSConnection", Connection)
    return calls, reads, closed


def test_actual_bounded_http_seam_admits_only_matching_scheduled_dispatch(monkeypatch):
    calls, reads, closed = transport(monkeypatch)
    assert proof.verify(context(), now=NOW)
    assert calls == [("GET", "/repos/andrewzp/theheat/actions/runs/12344"),
        ("GET", "/repos/andrewzp/theheat/actions/runs/12344/attempts/1/jobs?per_page=100")]
    assert reads == [65537, 65537] and len(closed) == 2


@pytest.mark.parametrize("key,value", [
    ("GITHUB_EVENT_NAME", "schedule"), ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_ACTOR", "invented-person"), ("GITHUB_TRIGGERING_ACTOR", "invented-person"),
    ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_REF", "refs/tags/main"),
    ("GITHUB_REPOSITORY", "someone/theheat"), ("GITHUB_WORKFLOW_REF", "other"),
    ("GITHUB_SHA", "not-a-sha"), ("GITHUB_SHA", "A" * 40), ("GITHUB_RUN_ID", "12344"),
    ("THEHEAT_AUTOMATIC_CATCHUP_RUN_ID", "01"), ("THEHEAT_AUTOMATIC_CATCHUP_RUN_ID", "12344\n"),
    ("THEHEAT_AUTOMATIC_CATCHUP_RUN_ID", "12344/../other"), ("REQUESTED_MODE", "both"),
    ("REQUESTED_MODE", "manual_tweet"), ("THEHEAT_AUTOMATIC_SELECTION_ONLY", "0"), ("GH_TOKEN", ""),
])
def test_untrusted_context_performs_no_metadata_request(monkeypatch, key, value):
    env = context()
    env[key] = value
    calls, reads, closed = transport(monkeypatch)
    assert not proof.verify(env, now=NOW)
    assert not calls and not reads and not closed


@pytest.mark.parametrize("mutate", [
    lambda p, j: p.update(id=True), lambda p, j: p.update(id=12346),
    lambda p, j: p.update(repository={"full_name": "foreign/theheat"}),
    lambda p, j: p.update(head_repository=None), lambda p, j: p.update(head_branch="other"),
    lambda p, j: p.update(head_sha="b" * 40), lambda p, j: p.update(path="other.yml"),
    lambda p, j: p.update(event="workflow_dispatch"), lambda p, j: p.update(run_attempt=2),
    lambda p, j: p.update(run_attempt=True), lambda p, j: p.update(created_at="2026-11-21T16:00:01Z"),
    lambda p, j: p.update(created_at="2026-11-21T15:29:59Z"),
    lambda p, j: p.update(created_at="2026-02-30T15:55:00Z"),
    lambda p, j: p.update(created_at="2026-11-21T15:55:00"),
    lambda p, j: j.update(total_count=2), lambda p, j: j.update(total_count=True),
    lambda p, j: j.update(total_count=101), lambda p, j: j.update(jobs=[]),
    lambda p, j: j["jobs"].append(deepcopy(j["jobs"][0])),
    lambda p, j: j["jobs"][0].update(run_id=12346), lambda p, j: j["jobs"][0].update(head_sha="b" * 40),
    lambda p, j: j["jobs"][0].update(name="other"), lambda p, j: j["jobs"][0].update(status="in_progress"),
    lambda p, j: j["jobs"][0].update(conclusion="failure"),
    lambda p, j: j["jobs"][0].update(completed_at="2026-11-21T16:00:01Z"),
    lambda p, j: j["jobs"][0]["steps"][0].update(conclusion="failure"),
    lambda p, j: j["jobs"][0]["steps"][0].update(status="in_progress"),
    lambda p, j: j["jobs"][0]["steps"][0].update(name="other"),
    lambda p, j: j["jobs"][0]["steps"].append(deepcopy(j["jobs"][0]["steps"][0])),
    lambda p, j: j["jobs"][0]["steps"][0].update(started_at="2026-11-21T15:59:00Z"),
    lambda p, j: j["jobs"][0]["steps"].append(None),
])
def test_changed_or_incomplete_parent_evidence_holds(monkeypatch, mutate):
    values = bodies()
    mutate(*values)
    calls, _, closed = transport(monkeypatch, values)
    assert not proof.verify(context(), now=NOW)
    assert 1 <= len(calls) <= 2 and len(closed) == len(calls)


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"id":12344,"id":12344}',
    b'{"x":NaN}', b'{"x":1e9999}', b" " * 65537, b"\xff", OSError("invented private error")],
    ids=["broken", "list", "duplicate", "nan", "overflow", "oversize", "bad-utf8", "transport"])
def test_bad_response_is_not_retried_or_followed(monkeypatch, raw, capsys):
    calls, _, closed = transport(monkeypatch, [raw])
    assert not proof.verify(context(), now=NOW)
    assert len(calls) == len(closed) == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("options", [{"status": 302}, {"status": 401}, {"status": 429},
    {"status": 500}, {"encoding": "gzip"}, {"content_type": "text/html"}])
def test_nonidentity_json_success_is_required(monkeypatch, options):
    calls, reads, closed = transport(monkeypatch, **options)
    assert not proof.verify(context(), now=NOW)
    assert len(calls) == len(closed) == 1 and reads == []


def test_other_sentinel_job_failure_does_not_erase_the_successful_dispatch(monkeypatch):
    values = bodies()
    values[0].update(status="completed", conclusion="failure")
    values[1]["total_count"] = 2
    values[1]["jobs"].append({"id": 301, "name": "sentinel", "status": "completed", "conclusion": "failure"})
    transport(monkeypatch, values)
    assert proof.verify(context(), now=NOW)


def test_actual_dispatch_shell_metadata_reader_and_sender_complete_one_cycle(monkeypatch, tmp_path):
    workflow = yaml.load((ROOT / ".github/workflows/source-health-sentinel.yml").read_text(), Loader=yaml.BaseLoader)
    calls = _run_step(workflow, tmp_path, _state(tmp_path, timedelta(hours=9)))
    assert calls[-1] == ("workflow run bot.yml --repo andrewzp/theheat --ref main -f mode=alerts "
        "-f automatic_only=true -f automatic_catchup_run_id=12344")
    transport(monkeypatch)
    assert proof.verify(context(), now=NOW)
    events = install(monkeypatch, {**context(), "THEHEAT_VERIFIED_AUTOMATIC_CATCHUP": "true"})
    assert sender.main(["--mode", "alerts"]) == 0
    assert len(events) == 2 and events[0] == ("sleep", 65)
    assert events[1][1][-1] == "auto_publish_due"


def test_proof_job_has_no_funded_material_and_is_a_dependency_not_a_new_trigger():
    doc = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    job = doc["jobs"]["automatic-catchup-proof"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert job["timeout-minutes"] == "2"
    assert "secrets." not in json.dumps(job) and "environment" not in job
    assert job["steps"][-1]["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert "automatic-catchup-proof" in doc["jobs"]["run"]["needs"]
    assert set(doc["on"]) == {"schedule", "pull_request", "workflow_dispatch"}
    assert "github.actor == 'github-actions[bot]'" in job["if"]
    assert "github.triggering_actor == 'github-actions[bot]'" in job["if"]
    assert STEP == proof.DISPATCH_STEP
