"""E3/E4 — explicit reconciliation/restore snapshot origins, the v1->v2 journal
migration, restore idempotency and recovered-history holds, through the real
SQLite authority, importer, restore planner, preview HTTP handler and CLI.

Invented places, identifiers and receipts only; no Gist, X or network.
"""

from __future__ import annotations

import base64
from contextlib import closing, redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any, cast

import pytest

from src.commands import delivery_reconciliation as rec
from src.commands import domain_journal, import_plan, local_cli, preview_ingress, recovery_provenance, restore_plan
from src.commands.schema import CommandError, Principal, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "tests/fixtures/w14_delivery_reconciliation_vectors.json").read_text())
PUBLISHER = Principal("fc-publisher", "publisher", "local-fixture")
EDITOR = Principal("fc-editor", "editor", "local-fixture")
CONFIRM = VECTORS["cases"][0]["steps"][0]["request"]
CANCEL = next(c for c in VECTORS["cases"] if c["name"] == "cancel_unknown_keeps_evidence")["steps"][0]["request"]
# The released (0.9.109.50) v1 schema identity; the migration accepts exactly this.
RELEASED_V1_SCHEMA_SHA256 = "16cfa8b782d27b479164a90cf01fab2cacf41662efcf846de756582938532e53"


def snapshots(authority: SQLiteAuthority) -> list[dict]:
    with closing(authority._connect()) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM domain_snapshots ORDER BY snapshot_id")]


def reconciliation_store(tmp_path) -> SQLiteAuthority:
    authority = SQLiteAuthority(tmp_path / "fc-authority.sqlite3")
    authority.initialize(deepcopy(VECTORS["state"]))
    return authority


def v1_authority(tmp_path, monkeypatch) -> tuple[SQLiteAuthority, list[dict]]:
    """A local authority written with the released v1 domain schema."""
    with monkeypatch.context() as patch:
        patch.setattr(domain_journal, "VERSION", 1)
        patch.setattr(domain_journal, "SCHEMA_SHA256", domain_journal.V1_SCHEMA_SHA256)
        patch.setattr(domain_journal, "V1_SCHEMA_SHA256", "released-v1-is-current-here")
        authority = SQLiteAuthority(tmp_path / "fc-v1.sqlite3")
        authority.initialize(deepcopy(VECTORS["state"]))
        authority.import_snapshot(canonical_json({"drafts": [], "publish_ledger": {}}).encode(), import_id="fc-v1-import")
        before = snapshots(authority)
    return authority, before


def test_released_v1_schema_is_refused_until_the_explicit_migration_keeps_every_row(tmp_path, monkeypatch):
    assert domain_journal.V1_SCHEMA_SHA256 == RELEASED_V1_SCHEMA_SHA256
    authority, before = v1_authority(tmp_path, monkeypatch)
    assert [row["origin"] for row in before] and {row["origin"] for row in before} == {"bootstrap", "import"}
    with pytest.raises(domain_journal.DomainJournalError, match="explicit v2 migration"):
        authority.domain_status()
    with pytest.raises(domain_journal.DomainJournalError, match="explicit v2 migration"):
        authority.import_snapshot(b"{}", import_id="fc-refused", origin="restore")
    report = authority.migrate_domain()
    assert report == {"migrated": True, "from_version": 1, "schema_version": 2, "snapshots_retained": len(before)}
    assert snapshots(authority) == before  # Every retained row, byte for byte.
    assert authority.domain_status(verify=True)["counts"]["domain_snapshots"] == len(before)
    assert authority.migrate_domain() == {"migrated": False, "schema_version": 2}
    authority.import_snapshot(canonical_json({"drafts": []}).encode(), import_id="fc-restore", origin="restore")
    assert {row["origin"] for row in snapshots(authority)} == {"bootstrap", "import", "restore"}


def test_a_failed_migration_rolls_back_and_leaves_the_v1_journal_usable_by_migration(tmp_path, monkeypatch):
    authority, before = v1_authority(tmp_path, monkeypatch)
    real = domain_journal.validate_schema

    def fail_after_rebuild(connection, namespace=None):
        if connection.execute("SELECT version FROM domain_schema").fetchone()[0] == 2:
            raise domain_journal.DomainJournalError("invented interruption after rebuild")
        return real(connection, namespace)

    monkeypatch.setattr(domain_journal, "validate_schema", fail_after_rebuild)
    with pytest.raises(domain_journal.DomainJournalError, match="invented interruption"):
        authority.migrate_domain()
    monkeypatch.setattr(domain_journal, "validate_schema", real)
    with closing(authority._connect()) as connection:
        assert connection.execute("SELECT version,schema_sha256 FROM domain_schema").fetchone()[:] == (1, RELEASED_V1_SCHEMA_SHA256)
    assert snapshots(authority) == before
    assert authority.migrate_domain()["migrated"] is True


def test_cli_domain_migrate_is_explicit(tmp_path, monkeypatch):
    authority, before = v1_authority(tmp_path, monkeypatch)
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        assert local_cli.main(["--database", str(authority.path), "domain-migrate"]) == 0
    assert json.loads(out.getvalue())["migrated"] is True and snapshots(authority) == before


def test_reconciliation_retains_an_explicit_snapshot_origin_for_its_state_version(tmp_path):
    authority = reconciliation_store(tmp_path)
    before = authority.read()

    def crash():
        raise RuntimeError("invented interruption before commit")

    with pytest.raises(RuntimeError):
        authority.delivery_reconciliation(CONFIRM, PUBLISHER, before_commit=crash)
    assert authority.read() == before and [r["origin"] for r in snapshots(authority)] == ["bootstrap"]
    applied = authority.delivery_reconciliation(CONFIRM, PUBLISHER)
    version, state = authority.read()
    assert applied["status"] == "applied" and applied["state_version"] == version == before[0] + 1
    [snapshot] = [r for r in snapshots(authority) if r["origin"] == "reconciliation"]
    assert snapshot["origin_id"] == CONFIRM["reconciliation_id"] and snapshot["authority_version"] == version
    assert json.loads(_artifact(authority, snapshot["artifact_sha256"])) == state
    assert authority.delivery_reconciliation(CONFIRM, PUBLISHER)["status"] == "unchanged"
    assert len([r for r in snapshots(authority) if r["origin"] == "reconciliation"]) == 1
    with pytest.raises(rec.ReconciliationError, match="forbidden"):
        authority.delivery_reconciliation(CANCEL, EDITOR)


def _artifact(authority, sha):
    with closing(authority._connect()) as connection:
        return domain_journal.read_artifact(connection, sha)


def test_restore_is_its_own_idempotent_origin_and_never_replaces_current_state(tmp_path):
    authority = SQLiteAuthority(tmp_path / "fc-restore.sqlite3")
    authority.initialize({"drafts": [], "publish_ledger": {}})
    draft = {key: value for key, value in VECTORS["state"]["drafts"][0].items() if key != "media_attachment"}
    backup = canonical_json({"drafts": [draft], "publish_ledger": {}}).encode()
    sha = hashlib.sha256(backup).hexdigest()
    now = "2026-10-30T12:00:00Z"
    planned = restore_plan.plan(authority, backup, expected_sha256=sha, restore_id="fc-restore-1", now=now)
    assert planned["executable"], planned["refusals"]
    assert planned["import_plan"]["origin"] == "restore" and planned["steps"][0]["origin"] == "restore"
    before = authority.read()
    first = restore_plan.execute(authority, planned, backup, expected_sha256=sha, now=now)
    again = restore_plan.execute(authority, planned, backup, expected_sha256=sha, now=now)
    assert [first["imported"]["items"][0]["status"], again["imported"]["items"][0]["status"]] == ["imported", "already_imported"]
    assert first["rollback"]["prior_state_unchanged"] and authority.read() == before
    restored = [r for r in snapshots(authority) if r["origin"] == "restore"]
    assert len(restored) == 1 and restored[0]["origin_id"] == "fc-restore-1"
    # The same identity in import history is a separate origin, never a collision.
    inputs = [("fc-restore-1", backup)]
    assert import_plan.execute(authority, import_plan.plan(inputs, authority=authority), inputs)["items"][0]["status"] == "imported"
    # A changed backup under the same restore identity is refused before any write.
    changed = canonical_json({"drafts": [], "publish_ledger": {}}).encode()
    refused = restore_plan.plan(authority, changed, expected_sha256=hashlib.sha256(changed).hexdigest(),
                                restore_id="fc-restore-1", now=now)
    assert {"code": "import_plan_not_executable"} in refused["refusals"]
    assert refused["import_plan"]["items"][0]["collision"] == "identity_collision_refused"


def test_an_older_reviewed_import_plan_keeps_its_exact_bytes_and_still_executes(tmp_path):
    authority = reconciliation_store(tmp_path)
    inputs = [("fc-old-plan", canonical_json({"drafts": []}).encode())]
    reviewed = import_plan.plan(inputs, authority=authority)
    assert "origin" not in reviewed
    assert import_plan.execute(authority, reviewed, inputs)["items"][0]["status"] == "imported"
    forged = {**reviewed, "origin": "reconciliation"}
    with pytest.raises(CommandError, match="altered|import or restore"):
        import_plan.execute(authority, forged, inputs)


def test_unsupported_origins_are_refused(tmp_path):
    authority = reconciliation_store(tmp_path)
    with pytest.raises(domain_journal.DomainJournalError, match="origin"):
        authority.import_snapshot(b"{}", import_id="fc-x", origin="command")
    with closing(authority._connect()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(domain_journal.DomainJournalError, match="Unsupported snapshot origin"):
            domain_journal.record_snapshot(connection, {}, origin="invented", origin_id="x", recorded_at="2026-10-30T12:00:00Z")
        connection.rollback()


def _restored_journal(tmp_path, drafts) -> SQLiteAuthority:
    journal = SQLiteAuthority(tmp_path / "fc-recovery.sqlite3")
    journal.initialize({"drafts": [], "publish_ledger": {}})
    backup = canonical_json({"drafts": drafts, "publish_ledger": {}}).encode()
    sha = hashlib.sha256(backup).hexdigest()
    planned = restore_plan.plan(journal, backup, expected_sha256=sha, restore_id="fc-restored", now="2026-10-30T12:00:00Z")
    restore_plan.execute(journal, planned, backup, expected_sha256=sha, now="2026-10-30T12:00:00Z")
    return journal


def test_restored_history_is_read_only_for_reconciliation_and_reported_as_restored(tmp_path):
    authority = reconciliation_store(tmp_path)
    target = next(d for d in VECTORS["state"]["drafts"] if d["event_id"] == CONFIRM["event_id"])
    journal = _restored_journal(tmp_path, [deepcopy(target)])
    view = recovery_provenance.provenance(journal.path, authority.read()[1])
    assert view[target["id"]]["origin"] == "restore" and view[target["id"]]["import_id"] == "fc-restored"
    recovery_provenance.configure(authority, journal.path)
    before = authority.read()
    with pytest.raises(rec.ReconciliationError, match="imported_record_read_only"):
        authority.delivery_reconciliation(CONFIRM, PUBLISHER)
    assert authority.read() == before
    os.rename(journal.path, str(journal.path) + ".unavailable")
    with pytest.raises(recovery_provenance.ProvenanceUnavailable):
        authority.delivery_reconciliation(CONFIRM, PUBLISHER)  # Fail closed; nothing commits.
    assert authority.read() == before


PORT, ORIGIN = 3998, "http://127.0.0.1:3998"
USERS = [{"username": "fc-publisher", "password": "invented-fc-publisher", "subject": "fc-publisher", "role": "publisher"},
         {"username": "fc-editor", "password": "invented-fc-editor", "subject": "fc-editor", "role": "editor"}]


class _Socket:
    def __init__(self, raw: bytes):
        self._reader, self.sent = io.BytesIO(raw), bytearray()

    def makefile(self, mode, *_args, **_kwargs):
        if "r" in mode:
            return self._reader
        outer = self

        class Writer(io.RawIOBase):
            def writable(self):
                return True

            def write(self, data):
                outer.sent.extend(data)
                return len(data)
        return Writer()

    def settimeout(self, _value):
        pass

    def sendall(self, data):
        self.sent.extend(data)


def _http(server, user, body=None, *, origin=ORIGIN):
    token = base64.b64encode(f"{user['username']}:{user['password']}".encode()).decode()
    raw = b"" if body is None else json.dumps(body).encode()
    method = "GET" if body is None else "POST"
    head = f"{method} /delivery-reconciliation HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nOrigin: {origin}\r\nAuthorization: Basic {token}\r\n"
    if body is not None:
        head += f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
    transport = _Socket(head.encode() + b"\r\n" + raw)
    preview_ingress.PreviewHandler(cast(Any, transport), ("127.0.0.1", 49152), server)
    status, _, payload = bytes(transport.sent).partition(b"\r\n\r\n")
    return int(status.split(b" ", 2)[1]), json.loads(payload)


def preview(monkeypatch, tmp_path, authority):
    operators = tmp_path / "fc-operators.json"
    descriptor = os.open(operators, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"operators": USERS}, stream)

    def no_socket(value, _address, _handler):
        value.server_port = PORT
    monkeypatch.setattr(preview_ingress.HTTPServer, "__init__", no_socket)
    return preview_ingress.PreviewServer(authority, preview_ingress.Operators(operators), port=PORT, origin=ORIGIN)


def test_preview_ingress_reconciliation_route_through_the_real_handler(monkeypatch, tmp_path):
    authority = reconciliation_store(tmp_path)
    server = preview(monkeypatch, tmp_path, authority)
    status, view = _http(server, USERS[1])
    assert status == 200 and view["publication_enabled"] is False
    assert {row["event_id"]: row["actions"] for row in view["rows"]}["w14-ev-unknown"] == ["confirm", "cancel"]
    before = authority.read()
    assert _http(server, USERS[1], CONFIRM) == (403, {"error": "Reconciliation refused; nothing changed", "code": "forbidden"})
    assert _http(server, USERS[0], CONFIRM, origin="http://127.0.0.1:1")[0] == 403
    stale = next(c for c in VECTORS["cases"] if c["name"] == "stale_decision_revision")["steps"][0]
    assert _http(server, USERS[0], stale["request"])[1]["code"] == stale["expect"]["code"]
    assert authority.read() == before
    status, applied = _http(server, USERS[0], CONFIRM)
    assert status == 200 and applied["status"] == "applied" and applied["state_version"] == before[0] + 1
    assert _http(server, USERS[0], CONFIRM)[1]["status"] == "unchanged"
    reused = {**CONFIRM, "reason": "invented different reason"}
    assert _http(server, USERS[0], reused) == (409, {"error": "Reconciliation refused; nothing changed",
                                                      "code": "reconciliation_id_reused"})
