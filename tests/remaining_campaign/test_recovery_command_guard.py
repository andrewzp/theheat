"""Real authority/HTTP methods with invented journal and SQL transports only.

No database, listening socket or provider is opened. Disposable database cases
live in test_postgres_recovery_command_guard.py and are reserved for CI.
"""
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.commands import domain_journal, postgres_sourced_generation, preview_ingress, recovery_provenance
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_text
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from tests.live_content_harness import trap_network
from tests.remaining_campaign.w14_provenance_child import Connection, OPERATOR, ORIGIN, PORT, operators_file
from tests.test_command_authority import story, target

JOURNAL = "/invented/retained-recovery.sqlite3"
ACTOR = Principal(OPERATOR["subject"], OPERATOR["role"], preview_ingress.AUTH_CONTEXT)


@pytest.fixture(autouse=True)
def no_external_transport(monkeypatch):
    trap_network(monkeypatch.setattr)
    def no_database(*_args, **_kwargs):
        raise AssertionError("a real database is forbidden in this test module")
    monkeypatch.setattr("sqlite3.connect", no_database)
    monkeypatch.setattr("src.storage.postgres_projection._driver", no_database)


def body(drafts, action="edit_revision"):
    now = datetime.now(UTC)
    payload: dict[str, Any] = {"text": "Invented Bracken Vale reached 41 C."} if action == "edit_revision" else {"reason": "Invented operator check"}
    if action == "record_review":
        payload.update(confirmed=True, expected_policy_sha256=fingerprint(current_editorial_policy()))
    if action == "prepare_media_revision":
        payload = {"expected_policy_sha256": fingerprint(current_editorial_policy()),
                   "expected_renderer_profile_sha256": "2" * 64}
    return {"command_id": str(uuid4()), "action": action, "requested_at": utc_text(now),
            "expires_at": utc_text(now + timedelta(hours=1)), "targets": [target(d) for d in drafts], "payload": payload}


def command(drafts, action="edit_revision"):
    return Command.from_request(body(drafts, action), ACTOR, environment="local", now=datetime.now(UTC))


def journal(monkeypatch, packets):
    """The actual provenance reader consumes invented retained packet bytes."""
    retained = {"packets": deepcopy(packets), "unavailable": False, "reads": 0}
    class ReadOnlyJournal:
        def execute(self, sql, _params):
            assert "domain_snapshots" in sql and "origin='import'" in sql
            rows = []
            for index, packet in enumerate(retained["packets"]):
                digest = hashlib.sha256(canonical_json(packet).encode()).hexdigest()
                rows.append({"origin_id": f"invented-import-{index}", "source_sha256": "1" * 64, "packet_sha256": digest})
            return SimpleNamespace(fetchall=lambda: rows)
        def close(self):
            pass
    def connect(_path, _environment):
        retained["reads"] += 1
        if retained["unavailable"]:
            raise recovery_provenance.ProvenanceUnavailable("invented journal unavailable")
        return ReadOnlyJournal()
    def artifact(_connection, digest):
        return next(canonical_json(p).encode() for p in retained["packets"]
                    if hashlib.sha256(canonical_json(p).encode()).hexdigest() == digest)
    monkeypatch.setattr(recovery_provenance, "_connect", connect)
    monkeypatch.setattr(domain_journal, "read_artifact", artifact)
    return retained


def fake_pg(monkeypatch, state, cmd):
    """Run real accept/consume against a strict, recorded in-memory SQL stand-in."""
    memory = SimpleNamespace(state=deepcopy(state), accepted=False, result=None, writes=[], events=[], locked=False, allow_read=False)
    connection = Mock()
    def execute(sql, params=()):
        if sql.startswith("SELECT i.command_id"):
            row = (cmd.command_id,) if memory.accepted and memory.result is None else None
        elif sql.startswith("INSERT INTO theheat_commands.intents"):
            memory.writes.append(sql)
            memory.accepted = True
            row = (1,)
        elif sql.startswith("INSERT INTO theheat_commands.results"):
            memory.writes.append(sql)
            memory.result = json.loads(params[1])
            row = None
        elif sql.startswith("UPDATE theheat_commands.state"):
            memory.writes.append(sql)
            row = None
        else:
            raise AssertionError(f"unexpected fake SQL: {sql}")
        return SimpleNamespace(fetchone=lambda: row)
    connection.execute.side_effect = execute
    @contextmanager
    def connected(*, writing=False):
        assert writing or memory.allow_read
        try:
            yield connection
        finally:
            memory.locked = False
    authority: Any = PostgresCommandAuthority.__new__(PostgresCommandAuthority)
    authority.environment = "local"
    def locked(_connection, *, lock=False):
        assert lock
        memory.locked = True
        return 0, deepcopy(memory.state)
    authority._state = locked
    authority._validate = lambda _connection: None
    authority._intent = lambda _connection, _id: (cmd, {"command_id": cmd.command_id}) if memory.accepted else None
    authority._result = lambda _connection, _id: memory.result
    authority._event = lambda _connection, _id, event, _at, value: memory.events.append((event, deepcopy(value)))
    def record(_connection, _namespace, _version, encoded, _fields):
        memory.state = json.loads(encoded)
    authority.projections = SimpleNamespace(_connection=connected, _record=record)
    authority.read = lambda: (int(memory.result is not None and memory.result["status"] == "applied"), deepcopy(memory.state))
    authority.generated_candidate_inputs = lambda: ()
    authority.candidate_projection = lambda *_args, **_kwargs: []
    authority.local_cost_projection = lambda **_kwargs: {}
    monkeypatch.setattr(postgres_sourced_generation, "prepare_ghcn_command", lambda *_args: None)
    return authority, memory


def fake_sqlite(monkeypatch, state, cmd):
    """Actual SQLite authority methods; sqlite3.connect remains forbidden."""
    memory = SimpleNamespace(state=deepcopy(state), accepted=False, result=None, writes=[], events=[], locked=False)
    connection = Mock()
    def execute(sql, params=()):
        row = None
        if sql == "BEGIN IMMEDIATE":
            memory.locked = True
        elif sql.startswith("SELECT version,state_json"):
            row = {"version": 0, "state_json": canonical_json(memory.state)}
        elif sql.startswith("SELECT sequence,digest,accepted_at"):
            assert not memory.accepted
        elif sql.startswith("SELECT result_json"):
            row = {"result_json": canonical_json(memory.result)} if memory.result else None
        elif sql.startswith("SELECT * FROM command_intents") or sql.startswith("SELECT i.*"):
            row = {"command_json": canonical_json(cmd.as_dict()), "digest": cmd.digest} if memory.accepted else None
        elif sql.startswith("SELECT i.command_id"):
            row = {"command_id": cmd.command_id} if memory.accepted else None
        elif sql.startswith("INSERT INTO command_intents"):
            memory.accepted = True
            memory.writes.append(sql)
        elif sql.startswith("UPDATE authority_state"):
            memory.state = json.loads(params[1])
            memory.writes.append(sql)
        elif sql.startswith("INSERT INTO command_results"):
            memory.result = json.loads(params[1])
            memory.writes.append(sql)
        elif sql.startswith("INSERT INTO command_events"):
            memory.events.append(sql)
        else:
            raise AssertionError(f"unexpected fake SQL: {sql}")
        return SimpleNamespace(fetchone=lambda: row, lastrowid=1)
    connection.execute.side_effect = execute
    connection.commit.side_effect = lambda: setattr(memory, "locked", False)
    connection.rollback.side_effect = lambda: setattr(memory, "locked", False)
    authority: Any = SQLiteAuthority("/invented/authority.sqlite3")
    authority._connect = lambda: connection
    authority._check_environment = lambda _connection: None
    monkeypatch.setattr(domain_journal, "validate_schema", lambda _connection: None)
    monkeypatch.setattr(domain_journal, "record_snapshot", lambda *_args, **_kwargs: None)
    return authority, memory


def server(monkeypatch, authority, operators, *, configured=JOURNAL):
    def no_socket(value, _address, _handler):
        value.server_port = PORT
    monkeypatch.setattr(preview_ingress.HTTPServer, "__init__", no_socket)
    return preview_ingress.PreviewServer(authority, preview_ingress.Operators(operators), port=PORT, origin=ORIGIN,
                                         recovery_journal=configured)


def http(target, request_body=None):
    token = base64.b64encode(f"{OPERATOR['username']}:{OPERATOR['password']}".encode()).decode()
    raw = b"" if request_body is None else json.dumps(request_body).encode()
    method, path = ("GET", "/state") if request_body is None else ("POST", "/commands")
    headers = f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nOrigin: {ORIGIN}\r\nAuthorization: Basic {token}\r\n"
    if request_body is not None:
        headers += f"Content-Type: application/json\r\nContent-Length: {len(raw)}\r\n"
    transport = Connection(headers.encode() + b"\r\n" + raw)
    preview_ingress.PreviewHandler(cast(Any, transport), ("127.0.0.1", 49152), target)
    head, _, payload = bytes(transport.sent).partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), json.loads(payload)


@pytest.mark.parametrize("action", ["edit_revision", "record_review", "approve_revision", "bulk_reject"])
def test_authenticated_post_cannot_mutate_imported_targets(monkeypatch, tmp_path, action):
    imported, fresh = story("invented-imported"), story("invented-fresh")
    drafts = [fresh, imported] if action == "bulk_reject" else [imported]
    cmd = command(drafts, action)
    authority, memory = fake_pg(monkeypatch, {"drafts": [imported, fresh]}, cmd)
    journal(monkeypatch, [imported])
    target_server = server(monkeypatch, authority, operators_file(tmp_path))
    status, view = http(target_server)
    assert status == 200 and imported["id"] in view["recovery_provenance"]
    status, reply = http(target_server, {k: v for k, v in cmd.as_dict().items()
                                       if k in {"command_id", "action", "requested_at", "expires_at", "targets", "payload"}})
    assert status == 409 and reply["code"] == "imported_record_read_only"
    assert not memory.accepted and memory.writes == [] and memory.state["drafts"] == [imported, fresh]


@pytest.mark.parametrize("factory", [fake_pg, fake_sqlite], ids=["postgres", "sqlite"])
@pytest.mark.parametrize("bulk", [False, True])
def test_deferred_consumption_rechecks_fresh_provenance_under_the_existing_lock(monkeypatch, factory, bulk):
    imported, fresh = story("invented-imported"), story("invented-fresh")
    cmd = command([fresh, imported] if bulk else [imported], "bulk_reject" if bulk else "edit_revision")
    initial = {"drafts": [imported, fresh]}
    authority, memory = factory(monkeypatch, initial, cmd)
    retained = journal(monkeypatch, [])
    authority.recovery_journal = JOURNAL
    authority.accept(cmd, ACTOR)
    retained["packets"].append(imported)
    before_writes = list(memory.writes)
    original = recovery_provenance.provenance
    def inside_lock(*args, **kwargs):
        assert memory.locked, "provenance must be checked within the consuming transaction"
        return original(*args, **kwargs)
    monkeypatch.setattr(recovery_provenance, "provenance", inside_lock)
    result = authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "rejected" and result["code"] == "imported_record_read_only"
    assert result["state_version"] == 0 and memory.state == initial
    assert not any(sql.startswith("UPDATE") for sql in memory.writes[len(before_writes):])


@pytest.mark.parametrize("factory", [fake_pg, fake_sqlite], ids=["postgres", "sqlite"])
def test_unavailable_journal_during_consumption_leaves_the_command_pending(monkeypatch, factory):
    fresh = story("invented-fresh")
    cmd = command([fresh])
    authority, memory = factory(monkeypatch, {"drafts": [fresh]}, cmd)
    retained = journal(monkeypatch, [])
    authority.recovery_journal = JOURNAL
    authority.accept(cmd, ACTOR)
    retained["unavailable"] = True
    with pytest.raises(recovery_provenance.ProvenanceUnavailable):
        authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert memory.result is None and memory.state == {"drafts": [fresh]}


@pytest.mark.parametrize("configured", [None, JOURNAL])
@pytest.mark.parametrize("factory", [fake_pg, fake_sqlite], ids=["postgres", "sqlite"])
def test_unimported_target_keeps_ordinary_editing(monkeypatch, configured, factory):
    fresh = story("invented-fresh")
    cmd = command([fresh])
    authority, memory = factory(monkeypatch, {"drafts": [fresh]}, cmd)
    journal(monkeypatch, [story("invented-other-import")])
    authority.recovery_journal = configured
    authority.accept(cmd, ACTOR)
    result = authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "applied" and result["state_version"] == 1
    assert memory.state["drafts"][0]["text"] == cmd.payload["text"]


def test_changed_imported_identity_is_never_assumed_to_be_a_supported_current_transition(monkeypatch):
    imported = story("invented-imported")
    changed = deepcopy(imported)
    changed.update(text="Invented arbitrary replacement bytes.", content_revision=2, decision_revision=99)
    journal(monkeypatch, [imported])
    assert imported["id"] in recovery_provenance.provenance(JOURNAL, {"drafts": [changed]})


def test_server_installs_guard_on_its_authority_and_shared_worker_arguments(monkeypatch, tmp_path):
    import argparse
    imported = story("invented-imported")
    authority, _memory = fake_pg(monkeypatch, {"drafts": [imported]}, command([imported]))
    journal(monkeypatch, [imported])
    server(monkeypatch, authority, operators_file(tmp_path))
    assert authority.recovery_journal == JOURNAL
    parser = argparse.ArgumentParser()
    preview_ingress.arguments(parser)
    assert "--recovery-journal" in parser._option_string_actions


def test_worker_adapter_receives_the_same_explicit_optional_journal(monkeypatch, tmp_path):
    fresh = story("invented-fresh")
    authority, _memory = fake_pg(monkeypatch, {"drafts": [fresh]}, command([fresh]))
    journal(monkeypatch, [])
    monkeypatch.setattr(preview_ingress, "PostgresCommandAuthority", lambda **_kwargs: authority)
    adapted, _operators = preview_ingress.adapter(SimpleNamespace(operators=operators_file(tmp_path),
        socket_directory="/invented/socket", database="invented", user="invented", database_port=55473,
        recovery_journal=JOURNAL))
    assert adapted is authority and adapted.recovery_journal == JOURNAL


def test_authenticated_admission_refuses_unavailable_provenance_without_an_intent(monkeypatch, tmp_path):
    fresh = story("invented-fresh")
    request_body = body([fresh])
    cmd = Command.from_request(request_body, ACTOR, environment="local", now=datetime.now(UTC))
    authority, memory = fake_pg(monkeypatch, {"drafts": [fresh]}, cmd)
    retained = journal(monkeypatch, [])
    target_server = server(monkeypatch, authority, operators_file(tmp_path))
    retained["unavailable"] = True
    status, reply = http(target_server, request_body)
    assert status == 503 and reply["code"] == "authority_unavailable"
    assert not memory.accepted and memory.writes == []
    status, reply = http(target_server)
    assert status == 503 and "state" not in reply


@pytest.mark.parametrize("factory", [fake_pg, fake_sqlite], ids=["postgres", "sqlite"])
def test_direct_authority_admission_cannot_bypass_the_imported_target_hold(monkeypatch, factory):
    imported, fresh = story("invented-imported"), story("invented-fresh")
    cmd = command([fresh, imported], "bulk_reject")
    authority, memory = factory(monkeypatch, {"drafts": [imported, fresh]}, cmd)
    journal(monkeypatch, [imported])
    authority.recovery_journal = JOURNAL
    with pytest.raises(CommandError, match="Imported history") as refusal:
        authority.accept(cmd, ACTOR)
    assert refusal.value.code == "imported_record_read_only" and not memory.accepted and not memory.writes


@pytest.mark.parametrize("packet", [None, {}, [], {"id": ""}])
def test_unreadable_import_packets_never_grant_currentness(monkeypatch, packet):
    fresh = story("invented-fresh")
    journal(monkeypatch, [packet])
    with pytest.raises(recovery_provenance.ProvenanceUnavailable):
        recovery_provenance.provenance(JOURNAL, {"drafts": [fresh]})


def test_authenticated_nonimported_target_still_admits_an_ordinary_edit(monkeypatch, tmp_path):
    fresh = story("invented-fresh")
    request_body = body([fresh])
    cmd = Command.from_request(request_body, ACTOR, environment="local", now=datetime.now(UTC))
    authority, memory = fake_pg(monkeypatch, {"drafts": [fresh]}, cmd)
    journal(monkeypatch, [story("invented-other-import")])
    target_server = server(monkeypatch, authority, operators_file(tmp_path))
    assert http(target_server, request_body)[0] == 202 and memory.accepted
    assert http(target_server)[1]["recovery_provenance"] == {}


def test_exact_current_command_cannot_launder_changed_imported_bytes(monkeypatch, tmp_path):
    imported = story("invented-imported")
    changed = deepcopy(imported)
    changed.update(text="Invented arbitrary replacement bytes.", content_revision=2, decision_revision=99)
    request_body = body([changed])
    cmd = Command.from_request(request_body, ACTOR, environment="local", now=datetime.now(UTC))
    authority, memory = fake_pg(monkeypatch, {"drafts": [changed]}, cmd)
    journal(monkeypatch, [imported])
    target_server = server(monkeypatch, authority, operators_file(tmp_path))
    status, reply = http(target_server, request_body)
    assert status == 409 and reply["code"] == "imported_record_read_only"
    assert not memory.accepted and memory.state["drafts"] == [changed]


@pytest.mark.parametrize("imported", [False, True])
def test_deferred_native_command_checks_history_before_requesting_native_preparation(monkeypatch, imported):
    draft = story("invented-media")
    cmd = command([draft], "prepare_media_revision")
    authority, memory = fake_pg(monkeypatch, {"drafts": [draft]}, cmd)
    retained = journal(monkeypatch, [])
    authority.recovery_journal = JOURNAL
    authority.accept(cmd, ACTOR)
    if imported:
        retained["packets"].append(draft)
        result = authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
        assert result["status"] == "rejected" and result["code"] == "imported_record_read_only"
    else:
        with pytest.raises(CommandError) as pending:
            authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
        assert pending.value.code == "native_preparation_required" and memory.result is None
    assert memory.state == {"drafts": [draft]}


def test_direct_native_worker_refuses_before_inputs_or_render_and_rechecks_in_final_consume(monkeypatch):
    from src.commands import postgres_editor_media, preview_media_worker
    draft = story("invented-media")
    cmd = command([draft], "prepare_media_revision")
    authority, memory = fake_pg(monkeypatch, {"drafts": [draft]}, cmd)
    memory.allow_read = True
    retained = journal(monkeypatch, [])
    authority.recovery_journal = JOURNAL
    authority.accept(cmd, ACTOR)
    retained["packets"].append(draft)
    before_reads = retained["reads"]
    def forbidden(*_args, **_kwargs):
        raise AssertionError("imported history must not prepare inputs or launch native work")
    monkeypatch.setattr(postgres_editor_media, "command_inputs", forbidden)
    monkeypatch.setattr(preview_media_worker, "run_native", forbidden)
    result = preview_media_worker.consume_media_once(authority, lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "rejected" and result["code"] == "imported_record_read_only"
    assert memory.state == {"drafts": [draft]} and retained["reads"] >= before_reads + 2


def test_matching_retained_import_is_preferred_without_treating_other_bytes_as_current(monkeypatch):
    old = story("invented-imported")
    changed = deepcopy(old)
    changed.update(text="Invented replacement retained elsewhere.", content_revision=2)
    journal(monkeypatch, [old, changed])
    found = recovery_provenance.provenance(JOURNAL, {"drafts": [changed]})
    assert found[changed["id"]]["import_id"] == "invented-import-1"
    changed["text"] = "Invented unproven third revision."
    found = recovery_provenance.provenance(JOURNAL, {"drafts": [changed]})
    assert found[changed["id"]]["import_id"] == "invented-import-0"
