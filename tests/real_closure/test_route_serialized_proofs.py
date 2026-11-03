"""P00c proofs through the REAL route: independently started dashboard processes (the real Next
handlers in route mode) -> the REAL admission CLI -> concurrently started REAL consumer CLIs.

OFFLINE FIXTURES, explicitly: the Gist is a file-backed whole-file GET/PATCH model with no
server merge and an interleaving barrier; ``workflow_dispatch`` is a file queue; the
``theheat-bot`` concurrency group is an ``fcntl.flock`` that only consumers take. A control
run of the same consumers WITHOUT that boundary loses an update, so the boundary is what
serializes -- not a stub.

v2 (ROUTE-CONTRACT-v2): ordinary commands are sealed (invented test key) and are submitted/applied
only while the route is ACTIVE (variable AND record), so the seeded state Gist carries an active route
record; route control remains the only plaintext form.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.real_closure import route_harness as h

ROOT = Path(__file__).resolve().parents[2]


def _seed(root: Path, count: int = 2, *, record: bool = True) -> dict:
    seed = h.fixture_state(count)
    h.seed_gist(root, h.STATE_GIST, {"state.json": json.dumps(seed["state"]), **({"gist-write-route.json": h.route_record()} if record else {})})
    h.seed_gist(root, h.FEEDBACK_GIST, {})
    return seed


def _reject(seed: dict, draft_id: str) -> dict:
    return {"action": "reject", "draftId": draft_id, "expectedRevision": seed["identities"][draft_id]}


def _clients(root: Path, bodies: list[dict], **env) -> list[dict]:
    barrier = f"{root / 'barrier-clients'}|{len(bodies)}|10000|1"
    processes = [h.start_client("app/api/drafts/route.js", body, h.client_env(root, route="serialized", barrier=barrier, **env))
                 for body in bodies]
    return [h.finish(process) for process in processes]


def _consumers(root: Path, inboxes: list[Path], *, group: bool = True, **env) -> list[subprocess.CompletedProcess]:
    barrier = f"{root / 'barrier-consumers'}|{len(inboxes)}|1500|1"
    processes = [h.start_consumer(root, h.consumer_env(root, run_id=str(900 + index), ROUTE_FIXTURE_BARRIER=barrier, **env),
                                  root / f"report-{index}.json", inbox=inbox, group=group)
                 for index, inbox in enumerate(inboxes)]
    done = []
    for process in processes:
        out, err = process.communicate(timeout=120)
        done.append(subprocess.CompletedProcess(process.args, process.returncode, out, err))
    return done


def _statuses(root: Path) -> dict[str, str]:
    return {draft["id"]: draft["status"] for draft in h.gist_state(root)["drafts"]}


def _consumer_trace(root: Path) -> list[tuple[int, str]]:
    return [(e["pid"], e["event"]) for e in h.events(root) if e["role"] == "consumer" and e["event"] in {"get", "patch"}]


def test_two_independent_clients_and_two_concurrent_consumers_lose_no_update(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    responses = _clients(root, [_reject(seed, "draft_route_1"), _reject(seed, "draft_route_2")])
    assert [r["status"] for r in responses] == [202, 202] and all(r["body"]["status"] == "pending" for r in responses)
    assert _statuses(root) == {"draft_route_1": "pending", "draft_route_2": "pending"}, "clients never PATCH"
    inboxes = [root / "inbox-a", root / "inbox-b"]
    assert [r["admitted"] for r in h.admit_all(root, inboxes=inboxes)] == [True, True]
    done = _consumers(root, inboxes)
    assert [d.returncode for d in done] == [0, 0], [d.stderr for d in done]
    assert _statuses(root) == {"draft_route_1": "rejected", "draft_route_2": "rejected"}
    results = h.results(root)
    assert {r["body"]["command_id"] for r in responses} == set(results)
    assert {row["status"] for row in results.values()} == {"applied"}
    trace = _consumer_trace(root)
    # Serialized: each consumer's GET is followed by its own PATCH before the other reads.
    assert [event for _, event in trace] == ["get", "patch", "get", "patch"] and trace[0][0] == trace[1][0] != trace[2][0]
    assert any(e["event"] == "barrier_timeout" for e in h.events(root) if e["role"] == "consumer"), \
        "the interleaving hook tried to overlap the consumers and was held off by the group"


def test_control_the_same_consumers_without_the_group_boundary_lose_an_update(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    _clients(root, [_reject(seed, "draft_route_1"), _reject(seed, "draft_route_2")])
    inboxes = [root / "inbox-a", root / "inbox-b"]
    h.admit_all(root, inboxes=inboxes)
    done = _consumers(root, inboxes, group=False)
    assert [d.returncode for d in done] == [0, 0]
    assert sorted(_statuses(root).values()) == ["pending", "rejected"], "control: last whole-file PATCH wins"
    assert len(h.results(root)) == 1, "control: one consumer's result file overwrote the other's"


def test_conflicting_decisions_from_independent_clients_apply_once_and_refuse_once(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    edit = {"action": "edit", "draftId": "draft_route_1", "expectedRevision": seed["identities"]["draft_route_1"],
            "editedText": "Invented City 1 reached 41°C today."}
    responses = _clients(root, [_reject(seed, "draft_route_1"), edit])
    inboxes = [root / "inbox-a", root / "inbox-b"]
    h.admit_all(root, inboxes=inboxes)
    assert [d.returncode for d in _consumers(root, inboxes)] == [0, 0]
    results = h.results(root)
    outcomes = sorted((row["status"], row["code"]) for row in results.values())
    assert outcomes == [("applied", None), ("refused", "revision_conflict")]
    winner = next(cid for cid, row in results.items() if row["status"] == "applied")
    draft = next(d for d in h.gist_state(root)["drafts"] if d["id"] == "draft_route_1")
    if winner == responses[0]["body"]["command_id"]:
        assert draft["status"] == "rejected" and draft["text"].endswith("40°C today.")
    else:
        assert draft["status"] == "pending" and draft["text"].endswith("41°C today.")


def test_lost_dispatch_response_then_resubmit_applies_once(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    lost, = _clients(root, [_reject(seed, "draft_route_1")], ROUTE_FIXTURE_LOSE_DISPATCH_RESPONSE="1")
    assert lost["status"] == 503 and lost["body"]["code"] == "command_submission_uncertain"
    command_id, retained = lost["body"]["command_id"], lost["body"]["command"]
    assert h.command_status(root, command_id)["status"] == "unknown"
    resubmitted = h.finish(h.start_client("app/api/commands/route.js", {"command": retained}, h.client_env(root, route="serialized")))
    assert resubmitted["status"] == 202 and resubmitted["body"]["command_id"] == command_id
    queued = [item["body"]["inputs"]["command"] for item in h.dispatches(root)]
    assert queued == [retained, retained], "both dispatches carry the same bytes"
    assert [r["admitted"] for r in h.admit_all(root)] == [True, True]
    assert h.command_status(root, command_id)["status"] == "pending"
    report = h.run_consumer(root, h.consumer_env(root, run_id="901"), root / "report.json")
    assert report is not None
    assert [row["command_id"] for row in report["applied"]] == [command_id] and report["duplicates"] == [command_id]
    assert h.command_status(root, command_id)["status"] == "applied"
    draft = next(d for d in h.gist_state(root)["drafts"] if d["id"] == "draft_route_1")
    assert draft["decision_revision"] == seed["identities"]["draft_route_1"]["decision_revision"] + 1


def test_unknown_delivery_crash_before_patch_applies_nothing_then_the_next_drain_applies(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    response, = _clients(root, [_reject(seed, "draft_route_1")])
    h.admit_all(root)
    before = h.gist_files(root)
    assert h.run_consumer(root, h.consumer_env(root, run_id="902", ROUTE_FIXTURE_EXIT_BEFORE_PATCH="1"),
                          root / "crash.json", expect=96) is None
    assert h.gist_files(root) == before
    assert h.command_status(root, response["body"]["command_id"])["status"] == "pending"
    h.run_consumer(root, h.consumer_env(root, run_id="903"), root / "report.json")
    assert h.command_status(root, response["body"]["command_id"])["status"] == "applied"


def test_consumer_restart_after_patch_before_reporting_never_double_applies(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    response, = _clients(root, [_reject(seed, "draft_route_1")])
    h.admit_all(root)
    assert h.run_consumer(root, h.consumer_env(root, run_id="904", ROUTE_FIXTURE_EXIT_AFTER_PATCH="1"),
                          root / "crash.json", expect=97) is None
    after_crash = h.gist_files(root)
    assert h.results(root)[response["body"]["command_id"]]["status"] == "applied"
    report = h.run_consumer(root, h.consumer_env(root, run_id="905"), root / "report.json")
    assert report is not None
    assert report["applied"] == [] and report["duplicates"] == [response["body"]["command_id"]]
    assert report["state_patches"] == 0 and h.gist_files(root) == after_crash
    draft = next(d for d in h.gist_state(root)["drafts"] if d["id"] == "draft_route_1")
    assert draft["decision_revision"] == seed["identities"]["draft_route_1"]["decision_revision"] + 1


def test_stale_revision_from_an_intervening_group_write_is_refused(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    response, = _clients(root, [_reject(seed, "draft_route_1")])
    h.admit_all(root)
    files = h.gist_files(root)
    changed = json.loads(files["state.json"])
    changed["drafts"][0]["score"] = {"total": 99}  # e.g. a bot run inside the group re-scored it
    h.seed_gist(root, h.STATE_GIST, {**files, "state.json": json.dumps(changed)})
    report = h.run_consumer(root, h.consumer_env(root, run_id="906"), root / "report.json")
    assert report is not None
    assert report["refused"] == [{"command_id": response["body"]["command_id"], "code": "revision_conflict"}]
    assert _statuses(root)["draft_route_1"] == "pending"


def test_activation_switches_new_code_by_record_and_rollback_restores_legacy(tmp_path):
    root = h.make_root(tmp_path)
    seed = _seed(root, record=False)
    build = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "activate_route",
                            "--generation", "1", "--actor", "root"], cwd=ROOT, env=h.root_env(), capture_output=True, text=True, check=True)
    (root / "dispatches").mkdir()
    (root / "dispatches" / "0001.json").write_text(json.dumps({"workflow": "gist-commands.yml",
                                                                "body": {"inputs": {"command": build.stdout.strip()}}}))
    h.admit_all(root)
    report = h.run_consumer(root, h.consumer_env(root, run_id="907", route="legacy"), root / "r0.json")
    assert report is not None
    assert report["refused"][0]["code"] == "route_variable_not_serialized"
    shutil_inbox = root / "inbox"
    for path in shutil_inbox.iterdir():
        for item in path.iterdir():
            item.unlink()
        path.rmdir()
    (root / "dispatches" / "0002.json").write_text(json.dumps({"workflow": "gist-commands.yml", "body": {"inputs": {"command": subprocess.run(
        [sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "activate_route", "--generation", "1",
         "--actor", "root"], cwd=ROOT, env=h.root_env(), capture_output=True, text=True, check=True).stdout.strip()}}}))
    h.admit_all(root)
    h.run_consumer(root, h.consumer_env(root, run_id="908", route="serialized"), root / "r1.json")
    assert json.loads(h.gist_files(root)["gist-write-route.json"])["mode"] == "serialized"
    # v2: a dashboard whose variable was never set sees the record alone -- the fail-closed window:
    # it neither PATCHes nor submits (route_not_active) until its variable mirror is serialized too.
    unset = h.finish(h.start_client("app/api/drafts/route.js", _reject(seed, "draft_route_1"), h.client_env(root)))
    assert unset["status"] == 409 and unset["body"]["code"] == "route_not_active" and _statuses(root)["draft_route_1"] == "pending"
    active = h.finish(h.start_client("app/api/drafts/route.js", _reject(seed, "draft_route_1"), h.client_env(root, route="serialized")))
    assert active["status"] == 202 and _statuses(root)["draft_route_1"] == "pending"
    # Rollback: root sets the variable back to legacy, then deactivate_route runs in the group.
    for path in (root / "inbox").iterdir():
        for item in path.iterdir():
            item.unlink()
        path.rmdir()
    for path in (root / "dispatches").iterdir():
        path.unlink()
    (root / "dispatches" / "0003.json").write_text(json.dumps({"workflow": "gist-commands.yml", "body": {"inputs": {"command": subprocess.run(
        [sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "deactivate_route", "--generation", "1",
         "--actor", "root"], cwd=ROOT, env=h.root_env(), capture_output=True, text=True, check=True).stdout.strip()}}}))
    h.admit_all(root)
    h.run_consumer(root, h.consumer_env(root, run_id="909", route="legacy"), root / "r2.json")
    assert json.loads(h.gist_files(root)["gist-write-route.json"])["mode"] == "legacy"
    legacy = h.finish(h.start_client("app/api/drafts/route.js", _reject(seed, "draft_route_2"), h.client_env(root)))
    assert legacy["status"] == 200 and _statuses(root)["draft_route_2"] == "rejected", "legacy direct path restored"
    assert "gist-command-results.json" in h.gist_files(root), "results remain readable after rollback"


@pytest.mark.parametrize("mutate,code", [
    (lambda c: {**c, "producer": {"kind": "dashboard_editor", "generation": "0"}}, "retired_writer_generation_refused"),
    (lambda c: {**c, "producer": {"kind": "dashboard_editor", "generation": "2"}}, "unauthorized_writer_generation_refused"),
    (lambda c: {**c, "producer": {"kind": "invented_writer", "generation": "1"}}, "unauthorized_writer_generation_refused"),
    (lambda c: {**c, "producer": {"kind": "gist_route_control", "generation": "1"}}, "unauthorized_writer_generation_refused"),
    (lambda c: {**c, "expires_at": "2026-01-01T00:00:01Z", "requested_at": "2026-01-01T00:00:00Z"}, "expired"),
    (lambda c: {**c, "operation": "post_feedback"}, "invalid_operation"),
    (lambda c: {k: v for k, v in c.items() if k != "seal"}, "invalid_envelope"),
], ids=["retired", "future", "unknown-kind", "kind-action-mismatch", "expired", "operation-not-for-action", "seal-missing"])
def test_real_admission_refuses_stale_unauthorized_or_malformed_producers(tmp_path, mutate, code):
    root = h.make_root(tmp_path)
    seed = _seed(root)
    response, = _clients(root, [_reject(seed, "draft_route_1")])
    command = mutate(json.loads(response["body"]["command"]))
    raw = json.dumps(command, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    done = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "admit", "--out", str(root / "out")], cwd=ROOT,
                          env=h.base_env() | {"THEHEAT_COMMAND_INPUT": raw}, capture_output=True, text=True, check=True)
    result = json.loads(done.stdout)
    assert result == {"admitted": False, "code": code, "command_id": command["command_id"]}
    assert not (root / "out").exists()


@pytest.mark.parametrize("raw,code", [
    ('{"a":1,"a":2}', "duplicate_key"),
    ('{"b":1, "a":2}', "non_canonical_command"),
    ('{"a":1.5}', "unsafe_number"),
    ("x" * 65536, "command_too_large"),
], ids=["duplicate-key", "non-canonical", "float", "oversize"])
def test_real_admission_refuses_noncanonical_bytes(tmp_path, raw, code):
    done = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "admit", "--out", str(tmp_path / "out")], cwd=ROOT,
                          env=h.base_env() | {"THEHEAT_COMMAND_INPUT": raw}, capture_output=True, text=True, check=True)
    assert json.loads(done.stdout)["code"] == code


def test_python_and_node_agree_on_canonical_bytes_and_digest(tmp_path):
    build = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "activate_route",
                            "--generation", "1", "--actor", "root ünïcode"], cwd=ROOT, env=h.root_env(),
                           capture_output=True, text=True, check=True)
    raw = build.stdout.strip()
    script = ("import('./lib/gist-write-route.js').then(m => { const v = m.validateCommandRaw(process.argv[1]);"
              " process.stdout.write(JSON.stringify({digest: v.digest, code: m.CODE_GENERATION})) })")
    node = subprocess.run([h.NODE, "-e", script, raw], cwd=h.DASHBOARD, env=h.base_env(), capture_output=True, text=True, check=True)
    import hashlib
    from src.commands import gist_route
    assert json.loads(node.stdout) == {"digest": hashlib.sha256(raw.encode()).hexdigest(), "code": gist_route.CODE_GENERATION}
