"""P00c: every inventoried Python Gist writer refuses (or runs only as a serialized-group job)
in route mode, and is unchanged in legacy mode.

OFFLINE FIXTURE: an in-process whole-file Gist transport (no server merge). No network.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
import requests

from src import state
from src.commands import gist_route, writer_fencing
from src.orchestrator import cli, world_cache

ROOT = Path(__file__).resolve().parents[2]
ROUTE_ON = json.dumps({"schema_version": 1, "mode": "serialized", "generation": 1, "changed_at": "2026-10-30T12:00:00Z",
                       "changed_by_run": "77:consume", "command_id": "00000000-0000-4000-8000-000000000001"})


class FakeGist:
    """Whole-file GET/PATCH: a PATCH replaces each named file; nothing is merged server-side."""

    def __init__(self, files: dict[str, str]):
        self.files, self.gets = dict(files), 0
        self.patches: list = []

    def get(self, url, **_kwargs):
        self.gets += 1
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"files": {name: {"content": content, "truncated": False}
                                                  for name, content in self.files.items()}}).encode()
        return response

    def patch(self, url, json=None, **_kwargs):  # noqa: A002 - requests' keyword
        self.patches.append(sorted(json["files"]))
        for name, value in json["files"].items():
            self.files[name] = value["content"]
        response = requests.Response()
        response.status_code, response._content = 200, b"{}"
        return response


@pytest.fixture
def gist(monkeypatch):
    def install(files):
        fake = FakeGist(files)
        for module in (state, world_cache):
            monkeypatch.setattr(module, "GIST_ID", "invented-gist")
            monkeypatch.setattr(module, "GITHUB_TOKEN", "invented-not-a-credential")
        monkeypatch.setattr(requests, "get", fake.get)
        monkeypatch.setattr(requests, "patch", fake.patch)
        monkeypatch.setattr(state, "_configured_backend", lambda: "gist")
        return fake
    for key in (gist_route.ROUTE_ENV, gist_route.MARKER_ENV, "GITHUB_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    return install


def _state_files(route: str | None = None) -> dict[str, str]:
    files = {"state.json": json.dumps({"drafts": [{"id": "d1", "status": "pending", "text": "Invented."}]})}
    if route is not None:
        files[gist_route.ROUTE_FILENAME] = route
    return files


# ---- bot_state: src.state.write_state ---------------------------------------------------------

def test_bot_state_legacy_unchanged_and_route_mode_refuses_without_the_group_marker(gist, monkeypatch, capsys):
    legacy = gist(_state_files())
    assert state.write_state({"drafts": []}) is True
    assert legacy.patches == [["state.json"]] and legacy.gets == 1, "legacy: one GET, one state-only PATCH"
    monkeypatch.setenv(gist_route.ROUTE_ENV, "serialized")
    routed = gist(_state_files())
    assert state.write_state({"drafts": []}) is False
    assert routed.patches == []
    assert "bot_state write refused: direct_write_disabled_by_route" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setenv(gist_route.MARKER_ENV, "77:run")
    assert state.write_state({"drafts": []}) is True
    assert routed.patches == [["state.json"]], "the serialized group job writes; never the route/result files"


@pytest.mark.parametrize("files,env,code", [
    (_state_files(ROUTE_ON), {}, "direct_write_disabled_by_route"),  # Record alone switches new code.
    (_state_files(ROUTE_ON.replace('"generation": 1', '"generation": 2')), {"GITHUB_RUN_ID": "77", gist_route.MARKER_ENV: "77:run"},
     "stale_writer_generation"),
    (_state_files("{not json"), {}, "gist_write_route_unreadable"),
    (_state_files(), {gist_route.ROUTE_ENV: "on"}, "invalid_gist_write_route"),
    (_state_files(), {gist_route.ROUTE_ENV: "serialized", "GITHUB_RUN_ID": "77", gist_route.MARKER_ENV: "78:run"},
     "invalid_serialized_writer_marker"),
])
def test_bot_state_refusal_codes(gist, monkeypatch, capsys, files, env, code):
    fake = gist(files)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert state.write_state({"drafts": []}) is False
    assert fake.patches == []
    assert f"write refused: {code}" in capsys.readouterr().out


# ---- bot_run_final_save / draft_save / metrics / publish_intent -------------------------------

def test_bot_run_final_save_refuses_outside_the_group_and_exits_without_patch(gist, monkeypatch, capsys):
    fake = gist(_state_files())
    monkeypatch.setenv(gist_route.ROUTE_ENV, "serialized")
    monkeypatch.setattr("sys.argv", ["theheat", "auto_publish_due"])
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setattr(cli.runtime_inventory, "collect_runtime_inventory", lambda *a, **k: {"git_sha": "fixture", "mode": "auto_publish_due"})
    monkeypatch.setattr(cli.credentials, "collect_credential_expiry", lambda: {})
    monkeypatch.setattr(cli.usage_ledger, "drain_into_state", lambda value: 0)
    monkeypatch.setattr(cli.budget, "record_budget_health", lambda value: cli.budget.budget_status({}))
    with pytest.raises(SystemExit) as stop:
        cli.main({"auto_publish_due": lambda value, *, current_run: deepcopy(value)})
    assert stop.value.code == 1 and fake.patches == []
    assert "could not be confirmed saved" in capsys.readouterr().out


@pytest.mark.parametrize("module", ["src/orchestrator/draft_save.py", "src/orchestrator/hot10.py",
                                    "src/orchestrator/posting.py", "src/orchestrator/cli.py"])
def test_in_process_writers_persist_only_through_write_state(module):
    """draft_save, metrics, publish intents/results and the final save have no PATCH of their own:
    their only Gist write primitive is ``state.write_state`` (guarded above), run inside bot.yml."""
    tree = ast.parse((ROOT / module).read_text())
    calls = {ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not {name for name in calls if name.endswith(("requests.patch", "requests.put", "requests.post"))}
    assert "gists/" not in (ROOT / module).read_text()


def test_publish_intent_write_is_refused_in_route_mode_before_any_send(gist, monkeypatch):
    fake = gist(_state_files())
    monkeypatch.setenv(gist_route.ROUTE_ENV, "serialized")
    draft = {"id": "d1", "status": "pending", "text": "Invented."}
    assert state.write_state({"drafts": [draft]}, expected_draft=draft, expected_publish_ledger=None) is False
    assert fake.patches == []


# ---- world_threshold_cache --------------------------------------------------------------------

def test_world_threshold_cache_route_mode_refuses_and_legacy_unchanged(gist, monkeypatch, capsys):
    legacy = gist(_state_files())
    assert world_cache.write_cache({}) is True and legacy.patches == [[world_cache.WORLD_CACHE_FILENAME]]
    routed = gist(_state_files(ROUTE_ON))
    assert world_cache.write_cache({}) is False and routed.patches == []
    assert "world_threshold_cache write refused: direct_write_disabled_by_route" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    monkeypatch.setenv(gist_route.MARKER_ENV, "77:run")
    assert world_cache.write_cache({}) is True and routed.patches == [[world_cache.WORLD_CACHE_FILENAME]]


# ---- runtime_report ---------------------------------------------------------------------------

def test_runtime_report_route_mode_refuses_without_marker_and_legacy_makes_no_extra_request():
    from scripts import runtime_report as report
    calls = []

    def api(method, payload):
        calls.append(method)
        return {"content": ROUTE_ON, "truncated": False}

    report.route_guard(api, {})
    assert calls == [], "legacy: the existing GET/PATCH/GET sequence is untouched"
    with pytest.raises(report.ReportError, match="direct_write_disabled_by_route"):
        report.route_guard(api, {gist_route.ROUTE_ENV: "serialized"})
    report.route_guard(api, {gist_route.ROUTE_ENV: "serialized", "GITHUB_RUN_ID": "9", gist_route.MARKER_ENV: "9:run"})
    assert calls == ["ROUTE"]


def test_runtime_report_route_read_is_one_fixed_jq_query(monkeypatch):
    from scripts import runtime_report as report

    def command(args, **kwargs):
        assert args[args.index("--jq") + 1] == '{gist_write_route_file:(.files["gist-write-route.json"] // null)}'
        return subprocess.CompletedProcess(args, 0, stdout='{"gist_write_route_file":null}\n', stderr="")
    monkeypatch.setattr(report.subprocess, "run", command)
    assert report.github_api("b" * 32, {"GITHUB_TOKEN": "invented"})("ROUTE", None) is None


# ---- reject_all_drafts ------------------------------------------------------------------------

def test_reject_all_drafts_refuses_outside_the_group_before_reading(gist, monkeypatch):
    from scripts import reject_all_drafts as script
    fake = gist(_state_files())
    monkeypatch.setenv(gist_route.ROUTE_ENV, "serialized")
    with pytest.raises(SystemExit) as stop:
        script.reject_all_pending()
    assert stop.value.code == 2 and fake.gets == 0 and fake.patches == []
    monkeypatch.setenv("GITHUB_RUN_ID", "5")
    monkeypatch.setenv(gist_route.MARKER_ENV, "5:reject")
    assert script.reject_all_pending() == 1 and fake.patches == [["state.json"]]


def test_reject_all_drafts_legacy_unchanged(gist):
    from scripts import reject_all_drafts as script
    fake = gist(_state_files())
    assert script.reject_all_pending() == 1
    assert json.loads(fake.files["state.json"])["drafts"][0]["status"] == "rejected"


# ---- nhc_advisory_import ----------------------------------------------------------------------

def test_nhc_advisory_import_apply_refuses_in_route_mode_before_any_claim(monkeypatch):
    from scripts import nhc_advisory_import as m
    envelope = {"files": {"state.json": {"content": "{}", "truncated": False},
                          "runtime-inventory.json": {"content": "{}", "truncated": False},
                          gist_route.ROUTE_FILENAME: {"content": ROUTE_ON, "truncated": False}}}
    for key in (gist_route.ROUTE_ENV, gist_route.MARKER_ENV, "GITHUB_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    client = m.GitHub("a" * 32, "invented/theheat", writing=True)
    monkeypatch.setattr(client, "_api", lambda args, body=None: json.dumps(envelope if args == [f"gists/{'a' * 32}"] else {"variables": []}).encode())
    with pytest.raises(m.ImportRefused) as refused:
        client.read()
    assert refused.value.code == "direct_write_disabled_by_route"
    reader = m.GitHub("a" * 32, "invented/theheat")  # check (read-only) and legacy apply are unchanged
    monkeypatch.setattr(reader, "_api", client._api)
    files, flags = reader.read()
    assert set(files) == {"state.json", "runtime-inventory.json"} and flags == {}


# ---- inventory: every Gist writer has a disposition and a route test --------------------------

ROUTE_TESTS = {
    "scheduled_alerts_catchup": "tests/test_alerts_catchup_reservation.py::test_reservation_obeys_serialized_route_writer_fence",
    "bot_state": "tests/real_closure/test_route_writers.py::test_bot_state_legacy_unchanged_and_route_mode_refuses_without_the_group_marker",
    "draft_save": "tests/real_closure/test_route_writers.py::test_in_process_writers_persist_only_through_write_state",
    "metrics": "tests/real_closure/test_route_writers.py::test_in_process_writers_persist_only_through_write_state",
    "bot_run_final_save": "tests/real_closure/test_route_writers.py::test_bot_run_final_save_refuses_outside_the_group_and_exits_without_patch",
    "publish_intent": "tests/real_closure/test_route_writers.py::test_publish_intent_write_is_refused_in_route_mode_before_any_send",
    "world_threshold_cache": "tests/real_closure/test_route_writers.py::test_world_threshold_cache_route_mode_refuses_and_legacy_unchanged",
    "runtime_report": "tests/real_closure/test_route_writers.py::test_runtime_report_route_mode_refuses_without_marker_and_legacy_makes_no_extra_request",
    "reject_all_drafts": "tests/real_closure/test_route_writers.py::test_reject_all_drafts_refuses_outside_the_group_before_reading",
    "nhc_advisory_import": "tests/real_closure/test_route_writers.py::test_nhc_advisory_import_apply_refuses_in_route_mode_before_any_claim",
    "dashboard_editor": "dashboard/tests/real-closure-route-writers.test.js::dashboard_editor",
    "dashboard_state": "dashboard/tests/real-closure-route-writers.test.js::dashboard_state",
    "dashboard_reconciliation": "dashboard/tests/real-closure-route-writers.test.js::dashboard_reconciliation",
    "post_feedback": "dashboard/tests/real-closure-route-writers.test.js::post_feedback",
    "gist_command_consumer": "dashboard/tests/real-closure-route-writers.test.js::gist_command_consumer",
    "gist_route_control": "dashboard/tests/real-closure-route-writers.test.js::gist_route_control",
}


def test_every_inventoried_gist_writer_has_a_route_disposition_and_a_named_route_test():
    gist_writers = {w.name: w for w in writer_fencing.WRITERS if w.store in {"gist_state", "feedback_gist"}}
    assert set(ROUTE_TESTS) == set(gist_writers)
    for name, ref in ROUTE_TESTS.items():
        path, label = ref.split("::")
        text = (ROOT / path).read_text()
        assert (f"def {label}(" in text) if path.endswith(".py") else (f'test("{label}:' in text), (name, ref)
    readiness = writer_fencing.route_compatibility()
    assert readiness["code_ready"] and readiness["activation"] == "not_performed" and readiness["enforced"] is False
    assert readiness["gist_transactional"] is False
    assert all(row.fenced is False for row in gist_writers.values()), "fenced only when a durable fence is active"
    # Backend cutover truth is unchanged: Gist writers still block a command-authority cutover.
    blocked = {b["writer"] for b in writer_fencing.compatibility("command_authority_postgres")["blockers"]}
    assert set(gist_writers) <= blocked
