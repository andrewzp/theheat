"""Actual maintenance CLI -> loopback HTTP -> separate PostgreSQL consumer."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from src.commands import bulk_rejection_client as client
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.preview_ingress import Operators, PreviewHandler, PreviewServer
from src.commands.schema import canonical_json, utc_text
from tests.test_command_authority import story
from tests.test_spend_journal import intent
from tests.test_postgres_command_authority import options, table_counts
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_preview_command_ingress import ORIGIN, ROWS, body, clean_environment, http, operator_file

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def maintenance(database, tmp_path, monkeypatch, request):
    for key in tuple(os.environ):
        if key not in clean_environment() and ("TOKEN" in key or "SECRET" in key or "PASSWORD" in key or "API_KEY" in key or key.startswith("PG")):
            monkeypatch.delenv(key)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("THEHEAT_ENVIRONMENT", raising=False)
    _, _, params = database
    drafts = [story("first"), story("second"), dict(story("posted"), status="posted")]
    drafts[1]["media_attachment"] = {"fixture": "invented retained graphic", "sha256": "a" * 64}
    initial = {"drafts": drafts, "publish_ledger": {}, "source_health": {"fixture": {"status": "unverified"}},
               "retained_cost_evidence": {"all_in_cost": None, "unknown": True}}
    if getattr(request, "param", None) == "unknown_publication":
        drafts[1].update(publish_outcome="unknown", last_publish_attempt_at=utc_text(datetime.now(UTC)))
        initial["publish_ledger"][drafts[1]["event_id"]] = {"phase": "unknown", "intent_id": "unconfirmed", "text": drafts[1]["text"]}
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    owner.initialize(initial, runtime_role="projection_runtime")
    owner.initialize_spending()
    authority = PostgresCommandAuthority(**options(params))
    retained = {"source": {"bytes": "invented source"}, "checks": {"status": "fixture"}, "media": {"pixels": "invented"}, "usage": {"priced": False}}
    authority.projections.record("maintenance-fixture", "retained", retained)
    operators = operator_file(tmp_path / "operators.json")
    server = PreviewServer(authority, Operators(operators), port=0, origin=ORIGIN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bulk = client.BulkRejectionClient(f"http://127.0.0.1:{server.server_port}", ORIGIN,
        operators, "local-editor", tmp_path / "request.json")
    arguments = ["--socket-directory", params["host"], "--database", params["dbname"],
                 "--database-port", str(params["port"]), "--user", "projection_runtime", "--operators", str(operators)]

    def consume(command_id):
        completed = subprocess.run([sys.executable, "-m", "src.commands.preview_worker", *arguments, "--command-id", command_id],
            cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=20)
        return completed.returncode, json.loads(completed.stdout)

    def cli():
        completed = subprocess.run([sys.executable, "scripts/reject_all_drafts.py", "--command-endpoint", bulk.endpoint,
            "--command-origin", bulk.origin, "--operators", str(operators), "--subject", bulk.subject,
            "--request-file", str(bulk.request_file)], cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=20)
        assert completed.stderr == ""
        assert "invented-editor" not in completed.stdout and "Example City" not in completed.stdout
        return completed.returncode, json.loads(completed.stdout)

    try:
        yield bulk, authority, initial, consume, cli, params
        assert authority.projections.read("maintenance-fixture", "retained")[1] == retained
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def spending_rows(params):
    tables = admin(params, "SELECT tablename FROM pg_tables WHERE schemaname='theheat_spending' ORDER BY tablename")
    assert tables
    return {table: admin(params, f'SELECT to_jsonb(t)::text FROM theheat_spending."{table}" t ORDER BY 1') for (table,) in tables}


def test_actual_cli_lost_ack_restart_and_completed_readback(maintenance, monkeypatch):
    bulk, authority, initial, consume, cli, params = maintenance
    at = utc_text(datetime.now(UTC))
    authority.spending("configure", {"daily_micro_usd": 100, "monthly_micro_usd": 150,
        "per_job_micro_usd": 90, "authorization_sha256": "a" * 64}, now=at)
    held = authority.spending("reserve", intent("held-bulk-fixture", amount=20, job="held-fixture"), now=at)
    authority.spending("reserve", intent("unknown-bulk-fixture", amount=30, job="unknown-fixture"), now=at)
    # Record an uncertain dispatch in the real journal; never call a provider.
    assert authority.spending("dispatch", {"intent_id": "unknown-bulk-fixture"}, now=at)["dispatch_granted"]
    unknown = authority.spending("uncertain", {"intent_id": "unknown-bulk-fixture"}, now=at)
    assert held["intent"]["state"] == "reserved" and held["intent"]["settled_micro_usd"] is None
    assert unknown["intent"]["state"] == "uncertain" and unknown["intent"]["settled_micro_usd"] is None
    assert unknown["totals"]["held_micro_usd"] == 50
    before_spend = spending_rows(params)
    assert len(before_spend["intents"]) == 2 and len(before_spend["events"]) == 2
    reply = PreviewHandler.reply
    dropped = []
    def drop_once(handler, status, value):
        if status == 202 and not dropped:
            dropped.append(value["receipt"]["command_id"])
            handler.close_connection = True
            return
        reply(handler, status, value)
    monkeypatch.setattr(PreviewHandler, "reply", drop_once)
    code, uncertain = cli()
    assert code == 3 and uncertain["status"] == "unknown" and dropped == [uncertain["command_id"]]
    original = bulk.request_file.read_bytes()
    envelope = bulk.load()
    assert [row["draft_id"] for row in envelope["request"]["targets"]] == ["first", "second"]
    assert authority.read() == (0, initial)
    assert table_counts(params) == {"intents": 1, "results": 0, "events": 1}
    code, pending = cli()  # New process, same request, no reselection or repost.
    assert code == 2 and pending["status"] == "pending" and "rejected_count" not in pending
    assert consume(uncertain["command_id"])[1]["result"]["status"] == "applied"
    code, applied = cli()
    assert code == 0 and applied["status"] == "applied" and applied["rejected_count"] == 2
    assert applied["changed_ids"] == ["first", "second"]
    assert cli()[1] == applied and bulk.request_file.read_bytes() == original
    assert table_counts(params) == {"intents": 1, "results": 1, "events": 2}
    version, state = authority.read()
    assert version == 1 and state["drafts"][2] == initial["drafts"][2]
    for old, saved in zip(initial["drafts"][:2], state["drafts"][:2], strict=True):
        changed = {key for key in old.keys() | saved.keys() if old.get(key) != saved.get(key)}
        assert changed <= {"status", "rejected_reason", "post_error", "decision_revision", "approval_mode", "updated_at"}
        assert saved["status"] == "rejected" and saved["decision_revision"] == old["decision_revision"] + 1
        assert saved["review_context"] == old["review_context"]
        assert saved["updated_at"] == authority.result(uncertain["command_id"])["completed_at"]
    assert state["drafts"][1]["media_attachment"] == initial["drafts"][1]["media_attachment"]
    assert {key: value for key, value in state.items() if key != "drafts"} == {key: value for key, value in initial.items() if key != "drafts"}
    assert spending_rows(params) == before_spend


@pytest.mark.parametrize("action", ["edit_revision", "approve_revision"])
def test_snapshot_then_concurrent_decision_refuses_entire_set(maintenance, action):
    bulk, authority, initial, consume, _, params = maintenance
    status, snapshot = bulk.http("/state")
    assert status == 200
    original = bulk.retain(bulk.select(snapshot))
    draft = initial["drafts"][0]
    change = body(draft, action, {"reason": "Invented approval"} if action == "approve_revision" else None)
    assert http(int(bulk.endpoint.rsplit(":", 1)[1]), "/commands", method="POST", value=change, role="publisher")[0] == 202
    assert consume(change["command_id"])[1]["result"]["status"] == "applied"
    before = authority.read()
    pending = bulk.run()
    assert pending["status"] == "pending" and pending["command_id"] == original["request"]["command_id"]
    assert consume(pending["command_id"])[1]["result"]["code"] == "revision_conflict"
    assert bulk.run()["status"] == "rejected" and authority.read() == before
    assert authority.read()[1]["drafts"][1] == initial["drafts"][1]


@pytest.mark.parametrize("maintenance", ["unknown_publication"], indirect=True)
def test_unknown_publication_preserves_entire_set_and_ledger(maintenance):
    bulk, authority, initial, consume, _, _ = maintenance
    accepted = bulk.run()
    assert accepted["status"] == "pending"
    assert consume(accepted["command_id"])[1]["result"]["code"] == "publication_unresolved"
    assert bulk.run()["code"] == "publication_unresolved" and authority.read() == (0, initial)


@pytest.mark.parametrize("mode", ["revoked", "unavailable"])
def test_current_authorization_at_separate_consumer(maintenance, mode):
    bulk, authority, initial, consume, _, _ = maintenance
    accepted = bulk.run()
    assert accepted["status"] == "pending"
    if mode == "revoked":
        operator_file(bulk.operators, [row for row in ROWS if row["role"] != "editor"])
    else:
        bulk.operators.unlink()
    code, result = consume(accepted["command_id"])
    assert authority.read() == (0, initial)
    if mode == "unavailable":
        assert code == 1 and authority.result(accepted["command_id"]) is None
        operator_file(bulk.operators)
        assert consume(accepted["command_id"])[1]["result"]["status"] == "applied"
    else:
        assert code == 0 and result["result"]["code"] == "forbidden"


def test_real_clock_expiry_after_acceptance_never_renews(maintenance):
    bulk, authority, initial, consume, _, _ = maintenance
    status, snapshot = bulk.http("/state")
    assert status == 200
    envelope = bulk.select(snapshot)
    # Preserve the production five-minute window; create an already-aged
    # request and let the real wall clock cross its unchanged deadline.
    requested = datetime.now(UTC) - timedelta(minutes=4, seconds=58)
    envelope["request"].update(requested_at=utc_text(requested), expires_at=utc_text(requested + timedelta(minutes=5)))
    envelope["request_sha256"] = hashlib.sha256(canonical_json(envelope["request"]).encode()).hexdigest()
    bulk.retain(envelope)
    accepted = bulk.run()
    assert accepted["status"] == "pending"
    time.sleep(2.1)
    assert consume(accepted["command_id"])[1]["result"]["code"] == "command_expired"
    assert bulk.run()["code"] == "command_expired" and authority.read() == (0, initial)
    assert bulk.load() == envelope
