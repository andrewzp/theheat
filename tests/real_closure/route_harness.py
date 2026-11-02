"""OFFLINE FIXTURE HARNESS for the P00c serialized Gist route proofs.

Everything here is an explicit offline stand-in, never production transport:

* the Gist is a file-backed model of GitHub's whole-file GET/PATCH semantics with no
  server merge (``dashboard/tests/helpers/route-fixture-fetch.mjs``);
* ``workflow_dispatch`` is a file queue; the ``admit`` job is the REAL admission
  module run on each queued input; the artifact store is a directory;
* the ``theheat-bot`` concurrency group is an exclusive ``fcntl.flock`` that only
  consumer processes take (``group_lock_runner.py``); the consumer itself is the
  REAL Node consumer CLI.

No network, credentials, GitHub or Gist is touched. v2 (ROUTE-CONTRACT-v2): clients seal with an
invented test key, ordinary commands need the route ACTIVE (variable AND record), and consumers
run with the route-era credential flags (new writer name, no legacy names) unless a test says otherwise.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "dashboard"
STATE_GIST = "fixturestategist0001"
FEEDBACK_GIST = "fixturefeedbackgist01"
SHIM = "./tests/helpers/route-fixture-fetch.mjs"
NODE = shutil.which("node") or "node"
# Invented, test-only seal key (32 bytes of 0x07), identical to dashboard/tests/helpers/route-memory-gist.js.
TEST_SEAL_KEY = "k-test:" + base64.b64encode(bytes([7]) * 32).decode("ascii")
# Invented, test-only ROOT route-control key (32 bytes of 0x0b); root's CLI signs, consumers verify.
TEST_CONTROL_KEY = "k-ctl-test:" + base64.b64encode(bytes([11]) * 32).decode("ascii")
# Non-secret repository variables of the admit job: the configured key ids.
ADMISSION_KIDS = {"THEHEAT_COMMAND_SEAL_KID": "k-test", "THEHEAT_ROUTE_CONTROL_KID": "k-ctl-test"}
ACTIVATION = "00000000-0000-4000-8000-000000000001"


def route_record(mode: str = "serialized", command_id: str = ACTIVATION) -> str:
    return json.dumps({"schema_version": 1, "mode": mode, "generation": 1, "changed_at": "2026-10-30T12:00:00Z",
                       "changed_by_run": "77:consume", "command_id": command_id})


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    (root / "gists").mkdir(parents=True)
    (root / "inbox").mkdir()
    (root / "artifacts").mkdir()
    return root


def seed_gist(root: Path, gist_id: str, files: dict[str, str]) -> None:
    (root / "gists" / f"{gist_id}.json").write_text(json.dumps(
        {"version": 1, "files": {name: {"content": content} for name, content in files.items()}}))


def gist_files(root: Path, gist_id: str = STATE_GIST) -> dict[str, str]:
    data = json.loads((root / "gists" / f"{gist_id}.json").read_text())
    return {name: file["content"] for name, file in data["files"].items()}


def gist_state(root: Path) -> dict:
    return json.loads(gist_files(root)["state.json"])


def events(root: Path) -> list[dict]:
    path = root / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def fixture_state(count: int = 2) -> dict:
    out = subprocess.run([NODE, "tests/helpers/route-fixture-state.mjs", str(count)], cwd=DASHBOARD,
                         capture_output=True, text=True, timeout=60, check=True, env=base_env())
    return json.loads(out.stdout)


def base_env() -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/tmp"),
            "LC_ALL": "C", "TZ": "UTC", **ADMISSION_KIDS}


def root_env() -> dict[str, str]:
    """Root's shell for ``route-command`` (holds the route-control key; never the dashboard)."""
    return base_env() | {"THEHEAT_ROUTE_CONTROL_KEY": TEST_CONTROL_KEY}


def client_env(root: Path, *, route: str | None = None, barrier: str | None = None, **extra: str) -> dict[str, str]:
    env = base_env() | {
        "ROUTE_FIXTURE_ROOT": str(root), "ROUTE_FIXTURE_ROLE": "client", "NODE_ENV": "production",
        "DASHBOARD_USERNAME": "reviewer", "DASHBOARD_PASSWORD": "invented-pass", "THEHEAT_STATE_BACKEND": "gist",
        "GIST_ID": STATE_GIST, "GITHUB_TOKEN": "invented-not-a-credential", "THEHEAT_FEEDBACK_GIST_ID": FEEDBACK_GIST,
        "THEHEAT_COMMAND_SEAL_KEY": TEST_SEAL_KEY,
    }
    if route is not None:
        env["THEHEAT_GIST_WRITE_ROUTE"] = route
    if barrier is not None:
        env["ROUTE_FIXTURE_BARRIER"] = barrier
    env.update(extra)
    return env


def start_client(route_path: str, body: dict[str, Any], env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen([NODE, "--import", SHIM, "tests/helpers/route-client.mjs", route_path, json.dumps(body)],
                            cwd=DASHBOARD, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(process: subprocess.Popen, timeout: int = 90) -> dict:
    out, err = process.communicate(timeout=timeout)
    assert process.returncode == 0, err
    return json.loads(out.strip().splitlines()[-1])


def dispatches(root: Path) -> list[dict]:
    folder = root / "dispatches"
    if not folder.exists():
        return []
    return [json.loads(path.read_text()) for path in sorted(folder.iterdir())]


def admit_all(root: Path, *, inboxes: list[Path] | None = None) -> list[dict]:
    """Run the REAL admission CLI once per queued dispatch (the ``admit`` job stand-in).

    ``inboxes`` (one per dispatch, in order) models artifacts that become visible to
    different consumer jobs; by default every artifact lands in ``root/inbox``.
    """
    results = []
    for index, item in enumerate(dispatches(root)):
        if item.get("admitted"):
            continue
        base = inboxes[index] if inboxes else root / "inbox"
        out_dir = base / f"run{index:04d}"
        env = base_env() | {"THEHEAT_COMMAND_INPUT": item["body"]["inputs"]["command"]}
        done = subprocess.run([sys.executable, "-m", "src.commands.gist_commands", "admit", "--out", str(out_dir)],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        result = json.loads(done.stdout)
        results.append(result)
        if result["admitted"]:
            (root / "artifacts" / f"run{index:04d}.json").write_text(json.dumps(
                {"id": index + 1, "name": f"theheat-command-{result['command_id']}", "expired": False,
                 "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    for path in sorted((root / "dispatches").iterdir()) if (root / "dispatches").exists() else []:
        data = json.loads(path.read_text())
        data["admitted"] = True
        path.write_text(json.dumps(data))
    return results


def consumer_env(root: Path, *, run_id: str, route: str = "serialized", **extra: str) -> dict[str, str]:
    env = base_env() | {
        "ROUTE_FIXTURE_ROOT": str(root), "ROUTE_FIXTURE_ROLE": "consumer", "GIST_ID": STATE_GIST,
        "GITHUB_TOKEN": "invented-not-a-credential", "THEHEAT_FEEDBACK_GIST_ID": FEEDBACK_GIST,
        "THEHEAT_GIST_WRITE_ROUTE": route, "GITHUB_RUN_ID": run_id,
        "THEHEAT_SERIALIZED_WRITER": f"{run_id}:consume", "GITHUB_REPOSITORY": "invented/theheat",
        "THEHEAT_COMMAND_SEAL_KEY": TEST_SEAL_KEY, "THEHEAT_GIST_CREDENTIAL": "route",
        "THEHEAT_LEGACY_CREDENTIALS_PRESENT": "false", "GH_DISPATCH_TOKEN": "invented-not-a-credential",
        "THEHEAT_ROUTE_CONTROL_KEY": TEST_CONTROL_KEY,
    }
    env.update(extra)
    return env


def start_consumer(root: Path, env: dict[str, str], report: Path, *, inbox: Path | None = None,
                   group: bool = True) -> subprocess.Popen:
    """One REAL consumer process inside the fcntl group stand-in (lock taken before any Gist read).

    ``group=False`` is the negative control only: the same consumer without the boundary.
    """
    consumer = [NODE, "--import", SHIM, "scripts/consume-gist-commands.mjs", "--inbox", str(inbox or root / "inbox"),
                "--report", str(report)]
    wrapper = [sys.executable, str(Path(__file__).with_name("group_lock_runner.py")), str(root / "theheat-bot.group.lock")]
    return subprocess.Popen((wrapper if group else []) + consumer, cwd=DASHBOARD, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def command_status(root: Path, command_id: str) -> dict:
    """GET /api/commands/<id> through the REAL handler in a separate process."""
    script = ("const m = await import('./app/api/commands/[id]/route.js');"
              "const id = process.argv[1];"
              "const r = await m.GET(new Request('http://localhost/api/commands/' + id, {headers: {authorization: "
              "'Basic ' + Buffer.from(process.env.DASHBOARD_USERNAME + ':' + process.env.DASHBOARD_PASSWORD).toString('base64')}}),"
              " {params: Promise.resolve({id})});"
              "process.stdout.write(JSON.stringify(await r.json()))")
    done = subprocess.run([NODE, "--import", SHIM, "--input-type=module", "-e", script, command_id], cwd=DASHBOARD,
                          env=client_env(root), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def run_consumer(root: Path, env: dict[str, str], report: Path, *, expect: int = 0, inbox: Path | None = None) -> dict | None:
    process = start_consumer(root, env, report, inbox=inbox)
    out, err = process.communicate(timeout=120)
    assert process.returncode == expect, (out, err)
    return json.loads(report.read_text()) if report.exists() else None


def results(root: Path, gist_id: str = STATE_GIST) -> dict:
    files = gist_files(root, gist_id)
    return json.loads(files["gist-command-results.json"])["results"] if "gist-command-results.json" in files else {}
