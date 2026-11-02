"""ROUTE repairs for the independent review through REAL processes and the REAL inbox fetch:

* P2-2 inbox provenance: only artifacts of a ``gist-commands.yml`` ``workflow_dispatch`` run of this
  repository (not a fork) on the default branch are fetched; everything else is refused or left
  unverified and reported, never trusted.
* P2-1 route-control authentication parity: root's Python CLI signs (HMAC-SHA256, stdlib ``hmac``),
  the Node consumer verifies; admission accepts only the configured control kid.
* P3-1 admission accepts only the configured seal kid (unset = refuse every sealed command).
* P3-2 a results-capacity skip makes the REAL consumer CLI exit non-zero (never silent).

OFFLINE FIXTURES, explicitly: injected ``gh api`` runner, file-backed Gist, invented data and
invented test keys. Red baselines: receipts/red-review-*.txt.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

from scripts import gist_command_inbox as inbox
from src.commands import gist_commands
from tests.real_closure import route_harness as h

ROOT = Path(__file__).resolve().parents[2]
REPO = "invented/theheat"
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
STAMP = (NOW - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
GENUINE_RUN = {"path": ".github/workflows/gist-commands.yml", "event": "workflow_dispatch", "head_branch": "main",
               "repository": {"id": 7}, "head_repository": {"id": 7}}


def _zip(command_id: str) -> bytes:
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        archive.writestr("command.json", "{}")
        archive.writestr("admission.json", json.dumps({"command_id": command_id}))
    return blob.getvalue()


def _row(artifact_id: int, run_id: int | None, *, head_repo: int = 7, branch: str = "main") -> dict:
    row = {"id": artifact_id, "name": f"theheat-command-{artifact_id:08d}-2222-4333-8444-555555555555", "expired": False, "created_at": STAMP}
    if run_id is not None:
        row["workflow_run"] = {"id": run_id, "repository_id": 7, "head_repository_id": head_repo, "head_branch": branch}
    return row


def _runner(rows: list[dict], runs: dict[int, dict | Exception]):
    calls: list[str] = []

    def run(args: list[str]) -> bytes:
        calls.append(args[0])
        if args[0].endswith("/zip"):
            artifact = next(row for row in rows if row["id"] == int(args[0].split("/")[-2]))
            return _zip(artifact["name"][len("theheat-command-"):])
        if "/actions/runs/" in args[0]:
            detail = runs[int(args[0].split("/")[-1])]
            if isinstance(detail, Exception):
                raise detail
            return json.dumps(detail).encode()
        return json.dumps({"artifacts": rows}).encode()
    return run, calls


def test_inbox_fetches_only_gist_commands_workflow_dispatch_artifacts_of_this_repository_on_main(tmp_path):
    rows = [
        _row(1, 101),                    # genuine
        _row(2, 102, head_repo=999),     # fork pull_request run: refused from the listing alone
        _row(3, 103),                    # this repository, another workflow
        _row(4, 104),                    # this repository, gist-commands.yml but not workflow_dispatch
        _row(5, 105, branch="feature"),  # dispatched on another branch
        _row(6, None),                   # no producing run in the listing
        _row(7, 107),                    # run lookup fails: unverifiable
        _row(8, 101),                    # second artifact of the genuine run (cached lookup)
    ]
    runs: dict[int, dict | Exception] = {
        101: GENUINE_RUN,
        103: {**GENUINE_RUN, "path": ".github/workflows/bot.yml"},
        104: {**GENUINE_RUN, "event": "pull_request"},
        107: inbox.InboxError("github_request_failed"),
    }
    run, calls = _runner(rows, runs)
    result = inbox.fetch(REPO, tmp_path, run, now=NOW)
    fetched = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert fetched == [f"{1:08d}-2222-4333-8444-555555555555-1", f"{8:08d}-2222-4333-8444-555555555555-8"]
    assert result["provenance_refused"] == {"provenance_fork": 1, "provenance_workflow": 1, "provenance_event": 1,
                                            "provenance_branch": 1, "provenance_unknown": 1}
    assert result["unverified"] == 1
    lookups = [c for c in calls if "/actions/runs/" in c]
    assert sorted(lookups) == [f"repos/{REPO}/actions/runs/{n}" for n in (101, 103, 104, 107)], "fork/branch/unknown need no request; one per run"
    scan = json.loads((tmp_path / "scan.json").read_text())
    assert scan["provenance_refused"] == result["provenance_refused"] and scan["unverified"] == 1


def test_provenance_lookups_are_bounded_and_the_overflow_is_deferred_not_trusted():
    rows = [_row(i, 1000 + i) for i in range(1, inbox.MAX_RUN_LOOKUPS + 11)]
    run, calls = _runner(rows, {1000 + i: GENUINE_RUN for i in range(1, inbox.MAX_RUN_LOOKUPS + 11)})
    proven = inbox.verify_provenance(REPO, rows, run)
    assert len(proven["artifacts"]) == inbox.MAX_RUN_LOOKUPS and proven["unverified"] == 10
    assert len([c for c in calls if "/actions/runs/" in c]) == inbox.MAX_RUN_LOOKUPS


def test_route_control_is_signed_by_root_python_and_verified_by_the_node_consumer(tmp_path):
    built = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "activate_route",
                            "--generation", "1", "--actor", "root ünïcode"], cwd=ROOT, env=h.root_env(), capture_output=True, text=True, check=True)
    raw = built.stdout.strip()
    command = json.loads(raw)
    assert set(command["auth"]) == {"alg", "kid", "mac"} and command["auth"]["kid"] == "k-ctl-test"
    unsigned = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "route-command", "--action", "activate_route",
                               "--generation", "1", "--actor", "root"], cwd=ROOT, env=h.base_env(), capture_output=True, text=True)
    assert unsigned.returncode == 2 and unsigned.stdout == "" and json.loads(unsigned.stderr)["code"] == "route_control_key_invalid"
    tampered = json.dumps({**command, "actor_subject": "someone"}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    script = ("import('./lib/gist-route-control.js').then(m => { const key = m.controlKey(process.env); const out = [];"
              " for (const raw of process.argv.slice(1)) { try { out.push(m.verifyRouteControl(JSON.parse(raw), key)) } catch (e) { out.push(e.code) } }"
              " process.stdout.write(JSON.stringify(out)) })")
    node = subprocess.run([h.NODE, "-e", script, raw, tampered], cwd=h.DASHBOARD, env=h.base_env() | {"THEHEAT_ROUTE_CONTROL_KEY": h.TEST_CONTROL_KEY},
                          capture_output=True, text=True, check=True)
    assert json.loads(node.stdout) == [True, "route_control_invalid"]
    # Admission checks shape and the CONFIGURED kid only (it holds no key).
    assert gist_commands.admit(raw, tmp_path / "a", now=datetime.now(UTC), control_kid="k-ctl-test")["admitted"] is True
    assert gist_commands.admit(raw, tmp_path / "b", now=datetime.now(UTC), control_kid="")["code"] == "route_control_unconfigured"
    assert gist_commands.admit(raw, tmp_path / "c", now=datetime.now(UTC), control_kid="k-other")["code"] == "route_control_kid_unknown"
    plain = json.dumps({k: v for k, v in command.items() if k != "auth"}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert gist_commands.admit(plain, tmp_path / "d", now=datetime.now(UTC), control_kid="k-ctl-test")["code"] == "route_control_unauthenticated"


def test_admission_accepts_only_the_configured_seal_kid(tmp_path):
    script = ("import('./lib/gist-command-seal.js').then(m => { const at = new Date(Math.floor(Date.now() / 1000) * 1000);"
              " const z = d => d.toISOString().replace(/\\.\\d{3}Z$/, 'Z');"
              " process.stdout.write(m.sealEnvelope({schema_version: 2, command_id: process.argv[1], action: 'post_feedback', operation: 'post_feedback',"
              " requested_at: z(at), expires_at: z(new Date(at.getTime() + 600000)), producer: {kind: 'post_feedback', generation: '1'},"
              " actor_subject: 'dashboard-operator', route_activation: process.argv[1]}, {targets: [], payload: {}}, {kid: 'k-test', key: Buffer.alloc(32, 7)})) })")
    raw = subprocess.run([h.NODE, "-e", script, str(uuid.uuid4())], cwd=h.DASHBOARD, env=h.base_env(), capture_output=True, text=True, check=True).stdout
    now = datetime.now(UTC)
    assert gist_commands.admit(raw, tmp_path / "a", now=now, seal_kid="k-test")["admitted"] is True
    assert gist_commands.admit(raw, tmp_path / "b", now=now, seal_kid="k-rotated")["code"] == "command_seal_kid_unknown"
    assert gist_commands.admit(raw, tmp_path / "c", now=now, seal_kid="")["code"] == "command_seal_unconfigured", "unset = default-off"


def test_a_results_capacity_skip_fails_the_real_consumer_cli_visibly(tmp_path):
    root = h.make_root(tmp_path)
    seed = h.fixture_state(1)
    expires = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    filler = {str(uuid.uuid4()): {"digest": "0" * 64, "status": "refused", "code": "x", "expires_at": expires} for _ in range(2000)}
    h.seed_gist(root, h.STATE_GIST, {"state.json": json.dumps(seed["state"]), "gist-write-route.json": h.route_record(),
                                     "gist-command-results.json": json.dumps({"schema_version": 1, "results": filler})})
    h.seed_gist(root, h.FEEDBACK_GIST, {})
    response = h.finish(h.start_client("app/api/drafts/route.js", {"action": "reject", "draftId": "draft_route_1",
                        "expectedRevision": seed["identities"]["draft_route_1"]}, h.client_env(root, route="serialized")))
    assert response["status"] == 202
    h.admit_all(root)
    report = h.run_consumer(root, h.consumer_env(root, run_id="5101"), root / "report.json", expect=3)
    assert report is not None
    assert report["skipped"] == [{"command_id": response["body"]["command_id"], "code": "command_results_capacity"}]
    assert h.command_status(root, response["body"]["command_id"])["status"] == "pending", "left for a later drain, never terminal"


def test_run_path_accepts_exactly_the_file_and_its_main_ref_forms(tmp_path):
    """Review 2: a genuine run's ``path`` may carry an @<ref> suffix; only the file itself, ``@main`` and
    ``@refs/heads/main`` are accepted. head_branch and repository checks are unchanged."""
    accepted = [".github/workflows/gist-commands.yml", ".github/workflows/gist-commands.yml@main",
                ".github/workflows/gist-commands.yml@refs/heads/main"]
    refused = [".github/workflows/gist-commands.yml@feature", ".github/workflows/gist-commands.yml@refs/heads/main2",
               ".github/workflows/gist-commands.yml@refs/tags/main", ".github/workflows/bot.yml@main",
               ".github/workflows/gist-commands.yml@", "x/.github/workflows/gist-commands.yml@main",
               ".github/workflows/gist-commands.yml@main@main", ".github/workflows/gist-commands.yml@refs/heads/main/x"]
    assert inbox.workflow_paths() == frozenset(accepted)
    rows = [_row(index + 1, 2000 + index) for index in range(len(accepted) + len(refused))]
    paths = accepted + refused
    run, _ = _runner(rows, {2000 + index: {**GENUINE_RUN, "path": path} for index, path in enumerate(paths)})
    result = inbox.fetch(REPO, tmp_path, run, now=NOW)
    fetched = sorted(int(p.name.rsplit("-", 1)[1]) for p in tmp_path.iterdir() if p.is_dir())
    assert fetched == [1, 2, 3]
    assert result["provenance_refused"] == {"provenance_workflow": len(refused)}
    # The separate branch and repository checks still apply to an accepted path form.
    wrong_branch = [_row(50, 3050, branch="feature"), _row(51, 3051)]
    run, _ = _runner(wrong_branch, {3050: {**GENUINE_RUN, "path": accepted[1]},
                                    3051: {**GENUINE_RUN, "path": accepted[2], "head_branch": "feature"}})
    proven = inbox.verify_provenance(REPO, wrong_branch, run)
    assert proven["artifacts"] == [] and proven["provenance_refused"] == {"provenance_branch": 2}
