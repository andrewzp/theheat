"""Real loopback HTTP and isolated PostgreSQL commands; invented data only."""
from datetime import UTC, datetime, timedelta
import base64
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import pytest

from src.commands.preview_ingress import Operators, PreviewServer, safe_environment, strict_json
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import utc_text
from src.editorial.revisions import fingerprint
from src.editorial.policy import current_editorial_policy
from tests.test_command_authority import story, target
from tests.test_postgres_command_authority import options
from tests.test_postgres_projection import cluster as cluster, database as database

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:3035"
ROWS = [{"username": role, "password": f"invented-{role}", "subject": f"local-{role}", "role": role}
        for role in ("editor", "publisher", "viewer")]


def clean_environment():
    return {"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT), "no_proxy": "*"}


def operator_file(path, rows=ROWS):
    path.write_text(json.dumps({"operators": rows}))
    path.chmod(0o600)
    return path


def body(draft, action="edit_revision", payload=None):
    now = datetime.now(UTC)
    return {"command_id": str(uuid4()), "action": action, "requested_at": utc_text(now),
            "expires_at": utc_text(now + timedelta(hours=1)), "targets": [target(draft)],
            "payload": payload or {"text": "Invented City reached 41°C in the synthetic observation."}}


def http(port, path="/state", *, method="GET", value=None, raw=None, role="editor", headers=None):
    connection = HTTPConnection("127.0.0.1", port, timeout=10)
    auth = base64.b64encode(f"{role}:invented-{role}".encode()).decode()
    request_headers = {"Authorization": f"Basic {auth}", "Origin": ORIGIN, "Content-Type": "application/json"}
    request_headers.update(headers or {})
    data = raw if raw is not None else json.dumps(value).encode() if value is not None else None
    connection.request(method, path, body=data, headers=request_headers)
    response = connection.getresponse()
    result = response.status, json.loads(response.read()), dict(response.getheaders())
    connection.close()
    return result


@pytest.fixture
def preview(database, tmp_path, monkeypatch):
    # No ambient credential is inherited by the real local child process.
    for key in tuple(os.environ):
        if key not in clean_environment() and ("TOKEN" in key or "SECRET" in key or "PASSWORD" in key or "API_KEY" in key or key.startswith("PG")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)
    _, _, params = database
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    initial = {"drafts": [story()], "publish_ledger": {}}
    owner.initialize(initial, runtime_role="projection_runtime")
    authority = PostgresCommandAuthority(**options(params))
    operators = operator_file(tmp_path / "operators.json")
    server = PreviewServer(authority, Operators(operators), port=0, origin=ORIGIN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    arguments = ["--socket-directory", params["host"], "--database", params["dbname"],
                 "--database-port", str(params["port"]), "--user", "projection_runtime", "--operators", str(operators)]

    def consume(command_id=None):
        result = subprocess.run([sys.executable, "-m", "src.commands.preview_worker", *arguments,
                                 *(["--command-id", command_id] if command_id else [])],
                                cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=20)
        return result.returncode, json.loads(result.stdout)

    yield server.server_port, authority, initial, operators, consume, arguments, params
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_http_edit_review_parked_approval_restart_and_conflict(preview):
    port, authority, initial, _, consume, _, _ = preview
    status, state, headers = http(port)
    assert status == 200 and state["state"] == initial and headers["Cache-Control"] == "private, no-store"
    first = body(initial["drafts"][0])
    second = body(initial["drafts"][0], payload={"text": "A competing invented edit remains unsaved."})
    accepted = http(port, "/commands", method="POST", value=first)
    assert accepted[0] == 202
    assert http(port, "/commands", method="POST", value=first)[1] == accepted[1]
    assert http(port, "/commands", method="POST", value=second)[0] == 202
    assert authority.read()[0] == 0  # HTTP never consumes.
    assert http(port, f"/commands/{first['command_id']}")[1]["status"] == "pending"
    code, applied = consume(first["command_id"])
    assert code == 0 and applied["result"]["status"] == "applied"
    assert consume(first["command_id"])[1] == applied
    assert consume(second["command_id"])[1]["result"]["code"] == "revision_conflict"
    saved = http(port)[1]["state"]["drafts"][0]
    assert saved["text"] == first["payload"]["text"] and saved["content_revision"] == 2
    assert "review_binding" not in saved and "publish_intent_id" not in saved
    review = body(saved, "record_review", {"confirmed": True, "reason": "Invented evidence checked",
                 "expected_policy_sha256": fingerprint(current_editorial_policy())})
    assert http(port, "/commands", method="POST", value=review)[0] == 202
    assert consume()[1]["result"]["status"] == "applied"
    saved = http(port)[1]["state"]["drafts"][0]
    approval = body(saved, "approve_revision", {"reason": "Park invented intent"})
    assert http(port, "/commands", method="POST", value=approval)[0] == 403
    assert http(port, "/commands", method="POST", value=approval, role="publisher")[0] == 202
    result = consume()[1]["result"]
    assert result["status"] == "applied" and result["publish_intent_id"]
    assert consume(approval["command_id"])[1]["result"] == result
    assert http(port, f"/commands/{approval['command_id']}")[1]["result"] == result
    version, state = authority.read()
    assert version == 3 and state["publish_ledger"] == {} and state["drafts"][0]["status"] == "approved"


@pytest.mark.parametrize("mode", ["revoked", "role", "unavailable"])
def test_role_rechecked_by_separate_worker(preview, mode):
    port, authority, initial, operators, consume, _, _ = preview
    command = body(initial["drafts"][0])
    assert http(port, "/commands", method="POST", value=command)[0] == 202
    if mode == "revoked":
        operator_file(operators, [row for row in ROWS if row["role"] != "editor"])
    elif mode == "role":
        operator_file(operators, [{**row, "role": "viewer"} if row["username"] == "editor" else row for row in ROWS])
    else:
        operators.unlink()
    code, result = consume()
    if mode == "unavailable":
        assert code == 1 and authority.result(command["command_id"]) is None
        operator_file(operators)
        assert consume()[1]["result"]["status"] == "applied"
    else:
        assert code == 0 and result["result"]["code"] == "forbidden" and authority.read()[0] == 0


def test_lost_http_receipt_retries_same_durable_acceptance(preview):
    port, authority, initial, _, consume, _, _ = preview
    command = body(initial["drafts"][0])
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("POST", "/commands", body=json.dumps(command).encode(), headers={
        "Authorization": "Basic " + base64.b64encode(b"editor:invented-editor").decode(),
        "Origin": ORIGIN, "Content-Type": "application/json",
    })
    # Drop the HTTP connection without reading its response or receipt.
    connection.close()
    for _ in range(50):
        if authority.journal():
            break
        time.sleep(0.01)
    events = authority.journal()
    assert len(events) == 1
    accepted = http(port, "/commands", method="POST", value=command)
    assert accepted[0] == 202 and accepted[1]["receipt"] == events[0]["data"]
    assert consume()[1]["result"]["status"] == "applied"
    assert authority.read()[0] == 1


def test_unknown_http_method_is_private_and_header_deadline_is_absolute(preview):
    port = preview[0]
    status, result, headers = http(port, "/private-request-target", method="BREW")
    assert status == 501 and headers["Cache-Control"] == "private, no-store"
    assert result == {"error": "Invalid or unsupported local HTTP request", "code": "http_request_refused"}
    connection = socket.create_connection(("127.0.0.1", port), timeout=7)
    started = time.monotonic()
    try:
        connection.sendall(b"GET /state HTTP/1.1\r\nHost: ")
        # A partial header leaves the parser waiting. The absolute deadline
        # must release this single-connection server even without a terminator.
        response = connection.recv(4096)
        assert time.monotonic() - started < 6.5
        assert b"HTTP/1.0 403" in response
    finally:
        connection.close()
    assert http(port)[0] == 200


@pytest.mark.parametrize("mode", ["auth", "origin", "host", "type", "large", "duplicate", "actor", "viewer", "expired", "reused"])
def test_http_boundary_refusals_do_not_mutate(preview, mode):
    port, authority, initial, _, _, _, _ = preview
    command = body(initial["drafts"][0])
    headers = {}
    role = "editor"
    raw = None
    if mode == "auth":
        headers["Authorization"] = "Basic aW52YWxpZA=="
    if mode == "origin":
        headers["Origin"] = "http://evil.invalid"
    if mode == "host":
        headers["Host"] = "evil.invalid"
    if mode == "type":
        headers["Content-Type"] = "text/plain"
    if mode == "large":
        raw = b"x" * (128 * 1024 + 1)
    if mode == "duplicate":
        raw = json.dumps(command).replace('"action":', '"action":"approve_revision","action":').encode()
    if mode == "actor":
        command["actor_subject"] = "local-publisher"
    if mode == "viewer":
        role = "viewer"
    if mode == "expired":
        command["requested_at"] = utc_text(datetime.now(UTC) - timedelta(hours=2))
        command["expires_at"] = utc_text(datetime.now(UTC) - timedelta(hours=1))
    if mode == "reused":
        assert http(port, "/commands", method="POST", value=command)[0] == 202
        command["payload"]["text"] = "Different payload under the same identity."
    assert http(port, "/commands", method="POST", value=command, raw=raw, role=role, headers=headers)[0] >= 400
    assert authority.read() == (0, initial)
    if mode != "reused":
        assert authority.journal() == []
    assert http(port, headers={"Authorization": "invalid"})[0] == 401


def test_http_accept_survives_worker_death_before_and_after_commit(preview):
    port, authority, initial, _, consume, arguments, _ = preview
    command = body(initial["drafts"][0])
    assert http(port, "/commands", method="POST", value=command)[0] == 202
    script = '''
import os, sys
from contextlib import contextmanager
from src.commands.preview_ingress import adapter, arguments
import argparse
p=argparse.ArgumentParser(); arguments(p); a,o=adapter(p.parse_args())
original=a.projections._connection
@contextmanager
def die(**kwargs):
    with original(**kwargs) as c:
        yield c
        os._exit(23)
a.projections._connection=die
a.consume(o.resolve)
'''
    died = subprocess.run([sys.executable, "-c", script, *arguments], cwd=ROOT,
                          env=clean_environment(), capture_output=True, timeout=20)
    assert died.returncode == 23
    assert authority.read() == (0, initial) and authority.result(command["command_id"]) is None
    after_commit = '''
import os
from src.commands.preview_ingress import adapter, arguments
import argparse
p=argparse.ArgumentParser(); arguments(p); a,o=adapter(p.parse_args())
a.consume(o.resolve)
os._exit(24)
'''
    died = subprocess.run([sys.executable, "-c", after_commit, *arguments], cwd=ROOT,
                          env=clean_environment(), capture_output=True, timeout=20)
    assert died.returncode == 24
    result = authority.result(command["command_id"])
    assert result["status"] == "applied"
    assert consume(command["command_id"])[1]["result"] == result
    assert authority.read()[0] == 1


def test_http_pending_and_completed_survive_dump_restore_to_fresh_cluster(preview, cluster):
    import psycopg

    port, authority, initial, _, consume, _, params = preview
    _, tool, _ = cluster
    completed = body(initial["drafts"][0])
    assert http(port, "/commands", method="POST", value=completed)[0] == 202
    result = consume()[1]["result"]
    original_version, original_state = authority.read()
    pending = body(original_state["drafts"][0], payload={"text": "Invented restored edit."})
    assert http(port, "/commands", method="POST", value=pending)[0] == 202
    with tempfile.TemporaryDirectory(prefix="theheat-preview-restore-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket = root / "socket"
        socket.mkdir(mode=0o700)
        data = root / "data"
        dump = root / "synthetic.dump"
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"],
             "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", root / "server.log", "-o",
                 f"-c listen_addresses='' -k {socket} -p 55474", "-w", "start")
            with psycopg.connect(host=str(socket), port=55474, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_preview TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55474", "-U", "projection_owner", "-d", "restored_preview",
                 "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55474, database="restored_preview", user="projection_runtime")
            assert restored.read() == (original_version, original_state)
            assert restored.result(completed["command_id"]) == result
            assert restored.result(pending["command_id"]) is None
            operators = Operators(preview[3])
            applied = restored.consume(operators.resolve)
            assert applied["status"] == "applied"
            assert restored.consume(operators.resolve, command_id=pending["command_id"]) == applied
            assert restored.read()[0] == original_version + 1
            assert len(restored.journal()) == 4  # All retained intent/result hashes validate.
            assert authority.read() == (original_version, original_state)
        finally:
            if (data / "postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


def test_actual_next_handlers_over_http_into_postgres(preview, tmp_path):
    port, _, _, _, _, arguments, _ = preview
    config = tmp_path / "node-integration.json"
    config.write_text(json.dumps({"endpoint": f"http://127.0.0.1:{port}", "origin": ORIGIN, "python": sys.executable,
                                  "workerArguments": arguments, "root": str(ROOT)}))
    config.chmod(0o600)
    result = subprocess.run(["node", "--test", "tests/draft-command-api.test.js"], cwd=ROOT / "dashboard",
                            env={**clean_environment(), "THEHEAT_PREVIEW_TEST_CONFIG": str(config)},
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_local_guards_and_strict_json(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        strict_json(b'{"x":1,"x":2}')
    with pytest.raises(ValueError):
        strict_json(b'{"x":NaN}')
    path = operator_file(tmp_path / "operators.json")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        Operators(path)
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        Operators(link)
    monkeypatch.setenv("NODE_ENV", "production")
    with pytest.raises(ValueError, match="production"):
        safe_environment()
    monkeypatch.delenv("NODE_ENV")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-refused")
    with pytest.raises(ValueError, match="credentials"):
        safe_environment()
