"""Local transactional command authority, separate from the legacy SQLite store.

This is not a production backend switch. It never writes Gist, dispatches work,
loads provider credentials or publishes. Every process obtains a real SQLite
write transaction before reading state. No Python mutex simulates serialization.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from src.commands import batch_journal, batch_worker_journal, batch_result_journal, check_journal, check_execution_journal, domain_journal, spend_journal
from src.commands import media_journal
from src.commands.reducer import AutomaticPolicy, failure_result, reduce_command
from src.commands.schema import Command, CommandError, Principal, authorize, canonical_json, utc_datetime, utc_text

_SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_metadata (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), environment TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authority_state (
  singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL CHECK(version>=0), state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS command_intents (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id TEXT NOT NULL UNIQUE, digest TEXT NOT NULL, command_json TEXT NOT NULL, accepted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS command_results (
  command_id TEXT PRIMARY KEY REFERENCES command_intents(command_id), result_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS command_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  command_id TEXT NOT NULL REFERENCES command_intents(command_id), event TEXT NOT NULL CHECK(event IN ('accepted','completed')),
  recorded_at TEXT NOT NULL, data_json TEXT NOT NULL, UNIQUE(command_id,event)
);
"""


class SQLiteAuthority:
    def __init__(self, path: str | Path, *, environment: str = "local"):
        if environment not in {"local", "preview"}:
            raise CommandError("production_adapter_unavailable", "This experimental adapter cannot operate on production")
        self.path = str(path)
        self.environment = environment

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if create:
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        # Read/status/consume must not silently create an empty database.
        uri = Path(self.path).resolve().as_uri() + "?mode=rw"
        connection = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _check_environment(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT environment FROM authority_metadata WHERE singleton=1").fetchone()
        if row is None or row["environment"] != self.environment:
            raise CommandError("environment_mismatch", "Authority environment does not match this consumer")

    @staticmethod
    def _check_tables(connection: sqlite3.Connection) -> None:
        allowed = {"authority_metadata", "authority_state", "command_intents", "command_results", "command_events"}
        allowed.update(domain_journal._TABLES)
        allowed.update(spend_journal._TABLES)
        allowed.update(batch_journal._TABLES)
        allowed.update(batch_worker_journal._TABLES)
        allowed.update(batch_result_journal._TABLES)
        allowed.update(check_journal._TABLES)
        allowed.update(check_execution_journal._TABLES)
        allowed.update(media_journal._TABLES)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if tables - allowed:
            raise domain_journal.DomainJournalError("Refusing a database that is not the separate local command authority")

    def initialize(self, initial_state: dict, *, source_namespace: str = "local-fixtures",
                   raw: bytes | None = None) -> None:
        if not isinstance(initial_state, dict):
            raise CommandError("invalid_state", "Initial state must be an object")
        encoded = canonical_json(initial_state)
        with closing(self._connect(create=True)) as connection:
            self._check_tables(connection)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_tables(connection)
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                for table in ("authority_metadata", "command_intents", "command_results", "command_events"):
                    for action in ("UPDATE", "DELETE"):
                        connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'append-only journal'); END")
                # REPLACE implicitly deletes a conflicting row, and SQLite normally
                # does not run delete triggers for that operation. Block duplicate
                # inserts explicitly across every primary/unique journal key.
                duplicate_keys = {
                    "authority_metadata": "singleton=NEW.singleton",
                    "command_intents": "sequence=NEW.sequence OR command_id=NEW.command_id",
                    "command_results": "command_id=NEW.command_id",
                    "command_events": "sequence=NEW.sequence OR (command_id=NEW.command_id AND event=NEW.event)",
                }
                for table, predicate in duplicate_keys.items():
                    connection.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {predicate}) BEGIN SELECT RAISE(ABORT, 'append-only journal'); END")
                existing = connection.execute("SELECT version,state_json FROM authority_state WHERE singleton=1").fetchone()
                version = 0
                if existing is not None:
                    self._check_environment(connection)
                    if existing["state_json"] != encoded:
                        raise CommandError("already_initialized", "Initialization cannot replace existing authority state")
                    version = existing["version"]
                else:
                    connection.execute("INSERT INTO authority_metadata(singleton, environment) VALUES(1, ?)", (self.environment,))
                    connection.execute("INSERT INTO authority_state(singleton, version, state_json) VALUES(1, 0, ?)", (encoded,))
                installed = domain_journal.install(connection, source_namespace)
                spend_journal.install(connection)
                batch_journal.install(connection)
                batch_worker_journal.install(connection)
                batch_result_journal.install(connection)
                check_journal.install(connection)
                check_execution_journal.install(connection)
                media_journal.install(connection)
                if installed:
                    domain_journal.record_snapshot(connection, initial_state, origin="bootstrap",
                        origin_id=str(version), authority_version=version, raw=raw,
                        recorded_at=utc_text(datetime.now(UTC)))
                elif raw is not None and canonical_json(domain_journal.parse_snapshot(raw)) != encoded:
                    raise domain_journal.DomainJournalError("Initial bytes differ from current authority state")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def import_snapshot(self, raw: bytes, *, import_id: str, now: datetime | None = None) -> dict:
        """Passive evidence import; never replace current state or grant approval."""
        state = domain_journal.parse_snapshot(raw)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                report = domain_journal.record_snapshot(connection, state, origin="import",
                    origin_id=import_id, raw=raw, recorded_at=utc_text(now or datetime.now(UTC)))
                connection.commit()
                return report
            except BaseException:
                connection.rollback()
                raise

    def domain_status(self, *, verify: bool = False) -> dict:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            self._check_environment(connection)
            return domain_journal.inspect(connection, verify=verify)

    def read_artifact(self, sha: str) -> bytes:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            self._check_environment(connection)
            domain_journal.validate_schema(connection)
            return domain_journal.read_artifact(connection, sha)

    def accept(self, command: Command, principal: Principal, *, now: datetime | None = None) -> dict:
        # A caller cannot bypass schema/actor validation by directly constructing a dataclass.
        command = Command.from_stored(canonical_json(command.as_dict()))
        if command.environment != self.environment:
            raise CommandError("environment_mismatch", "Command belongs to another authority environment")
        if command.actor_subject != principal.subject or command.authentication_context != principal.authentication_context:
            raise CommandError("forbidden", "Command identity does not match authenticated ingress")
        authorize(principal, command.action)
        encoded = canonical_json(command.as_dict())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                clock = now or datetime.now(UTC)
                at = utc_text(clock)
                existing = connection.execute("SELECT sequence,digest,accepted_at FROM command_intents WHERE command_id=?", (command.command_id,)).fetchone()
                if existing is not None:
                    if existing["digest"] != command.digest:
                        raise CommandError("command_id_reused", "This command ID already belongs to a different immutable request")
                    receipt = {"command_id": command.command_id, "sequence": existing["sequence"], "accepted_at": existing["accepted_at"], "digest": existing["digest"]}
                else:
                    if clock >= utc_datetime(command.expires_at):
                        raise CommandError("command_expired", "Command expired before durable acceptance")
                    if utc_datetime(command.requested_at) > clock + timedelta(minutes=5):
                        raise CommandError("invalid_time", "Command was requested too far in the future")
                    cursor = connection.execute("INSERT INTO command_intents(command_id,digest,command_json,accepted_at) VALUES(?,?,?,?)", (command.command_id, command.digest, encoded, at))
                    receipt = {"command_id": command.command_id, "sequence": cursor.lastrowid, "accepted_at": at, "digest": command.digest}
                    connection.execute("INSERT INTO command_events(command_id,event,recorded_at,data_json) VALUES(?,'accepted',?,?)", (command.command_id, at, canonical_json(receipt)))
                connection.commit()
                return receipt
            except BaseException:
                connection.rollback()
                raise

    def consume(self, resolve_principal: Callable[[str], Principal | None], *, command_id: str | None = None,
                now: datetime | None = None, policy: AutomaticPolicy = AutomaticPolicy(),
                before_commit: Callable[[], None] | None = None) -> dict | None:
        """Commit one domain update with its terminal result, or roll back both.

        before_commit is a local fault-injection seam, never request data. A
        bounded trusted resolver rechecks the actor's current role. Hosted auth
        and policy resolution are unimplemented adapter requirements.
        """
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                clock = now or datetime.now(UTC)
                if command_id is not None:
                    prior = connection.execute("SELECT result_json FROM command_results WHERE command_id=?", (command_id,)).fetchone()
                    if prior:
                        connection.commit()
                        return json.loads(prior["result_json"])
                    intent = connection.execute("SELECT * FROM command_intents WHERE command_id=?", (command_id,)).fetchone()
                    if intent is None:
                        raise CommandError("command_not_found", "No durable acceptance exists for this command")
                    oldest = connection.execute("SELECT i.command_id FROM command_intents i LEFT JOIN command_results r USING(command_id) WHERE r.command_id IS NULL ORDER BY i.sequence LIMIT 1").fetchone()
                    if oldest is None or oldest["command_id"] != command_id:
                        raise CommandError("command_pending", "An earlier accepted command must finish first")
                else:
                    intent = connection.execute("SELECT i.* FROM command_intents i LEFT JOIN command_results r USING(command_id) WHERE r.command_id IS NULL ORDER BY i.sequence LIMIT 1").fetchone()
                    if intent is None:
                        connection.commit()
                        return None
                command = Command.from_stored(intent["command_json"])
                if command.digest != intent["digest"] or command.environment != self.environment:
                    raise CommandError("invalid_journal", "Command digest or environment no longer matches its acceptance")
                snapshot = connection.execute("SELECT version,state_json FROM authority_state WHERE singleton=1").fetchone()
                state = json.loads(snapshot["state_json"])
                version = snapshot["version"]
                pending_domain_state = None
                domain_journal.validate_schema(connection)
                try:
                    principal = resolve_principal(command.actor_subject)
                    if principal is None:
                        raise CommandError("forbidden", "Operator authorization was revoked before execution")
                    from src.editorial.policy import current_editorial_policy
                    reduction = reduce_command(state, command, principal, now=clock, policy=policy, editorial_policy=current_editorial_policy())
                    result = {"status": "applied" if reduction.changed_ids else "unchanged", "changed_ids": list(reduction.changed_ids),
                              "identities": list(reduction.identities), "publish_intent_id": reduction.publish_intent_id}
                    if reduction.changed_ids:
                        encoded_state = canonical_json(reduction.state)
                        version += 1
                        connection.execute("UPDATE authority_state SET version=?,state_json=? WHERE singleton=1", (version, encoded_state))
                        pending_domain_state = reduction.state
                except (CommandError, ValueError, TypeError, UnicodeError, OverflowError) as exc:
                    result = failure_result(exc)
                # Storage failures must roll back state and result together, not
                # become terminal reducer rejections after a successful edit.
                if pending_domain_state is not None:
                    domain_journal.record_snapshot(connection, pending_domain_state, origin="command",
                        origin_id=command.command_id, authority_version=version, command_id=command.command_id,
                        recorded_at=utc_text(clock))
                result.update(command_id=command.command_id, digest=command.digest, state_version=version,
                              completed_at=utc_text(clock), actor_subject=command.actor_subject)
                connection.execute("INSERT INTO command_results(command_id,result_json) VALUES(?,?)", (command.command_id, canonical_json(result)))
                connection.execute("INSERT INTO command_events(command_id,event,recorded_at,data_json) VALUES(?,'completed',?,?)", (command.command_id, utc_text(clock), canonical_json(result)))
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def spending(self, action: str, payload: dict, *, now: str,
                 before_commit: Callable[[], None] | None = None) -> dict:
        """Trusted local spending rehearsal; no provider or production mutation.

        Only a true dispatch_granted result permits the caller's one network
        attempt. A replay/unknown acknowledgment never grants another attempt.
        """
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                domain_journal.validate_schema(connection)
                result = spend_journal.apply(connection, action, payload, now=now)
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def prepare_batch(self, plan_bytes: bytes, *, expected_plan_sha256: str,
                      reservation: dict, now: str,
                      before_commit: Callable[[], None] | None = None) -> dict:
        """Atomically retain one local batch plan, job and spending hold; never send."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                result = batch_journal.register(connection, plan_bytes,
                    expected_plan_sha256=expected_plan_sha256, reservation=reservation, now=now)
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def batch_work(self, action: str, payload: dict, *, now: str, raw: bytes | None = None,
                   before_commit: Callable[[], None] | None = None) -> dict:
        """Local fenced lifecycle rehearsal. One committed grant, no provider I/O."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                result = batch_worker_journal.apply(connection, action, payload, now=now, raw=raw)
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def record_batch_results(self, payload: dict, *, metadata: bytes, results: bytes,
                             now: str, before_commit: Callable[[], None] | None = None) -> dict:
        return self._batch_results_transaction("record", payload, now=now,
            metadata=metadata, results=results, before_commit=before_commit)

    def batch_results_status(self, job_id: str, *, now: str) -> dict:
        return self._batch_results_transaction("index", {"job_id": job_id}, now=now)

    def review_batch_results(self, payload: dict, *, now: str,
                             before_commit: Callable[[], None] | None = None) -> dict:
        return self._batch_results_transaction("review", payload, now=now, before_commit=before_commit)

    def _batch_results_transaction(self, action: str, payload: dict, *, now: str,
                                   metadata: bytes | None = None, results: bytes | None = None,
                                   before_commit: Callable[[], None] | None = None) -> dict:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                if action == "record":
                    result = batch_result_journal.record(connection, payload, metadata, results, now=now)
                elif action == "index":
                    result = batch_result_journal.index(connection, payload, now=now)
                else:
                    result = batch_result_journal.review(connection, payload, now=now)
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def candidate_checks(self, action: str, payload: dict, *, now: str,
                         request: bytes | None = None, receipt: dict | None = None,
                         before_commit: Callable[[], None] | None = None) -> dict:
        """Trusted local check lifecycle. No provider call or publication grant."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                if action == "intake":
                    result = check_journal.intake(connection, payload, now=now)
                elif action == "begin":
                    result = check_journal.begin(connection, payload, request=request, now=now)
                elif action == "complete":
                    result = check_journal.complete(connection, payload, receipt=receipt, now=now)
                elif action == "status":
                    result = check_journal.status(connection, payload, now=now)
                else:
                    raise check_journal.CheckJournalError("unknown_check_action")
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def read_check_request(self, check_set_id: str, stage: str, grant_id: str) -> bytes:
        return self._read_check_artifact(check_set_id, stage, grant_id, response=False)

    def read_check_response(self, check_set_id: str, stage: str, grant_id: str) -> bytes:
        return self._read_check_artifact(check_set_id, stage, grant_id, response=True)

    def _read_check_artifact(self, check_set_id: str, stage: str, grant_id: str, *, response: bool) -> bytes:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                reader = check_execution_journal.read_response if response else check_execution_journal.read_request
                raw = reader(connection, check_set_id, stage, grant_id)
                connection.commit()
                return raw
            except BaseException:
                connection.rollback()
                raise

    def check_execution(self, action: str, payload: dict, *, now: str,
                        raw: bytes | None = None, before_commit: Callable[[], None] | None = None) -> dict:
        """Retain/read local raw observations; no parsing or paid side effects."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_environment(connection)
                if action == "read" and raw is None:
                    result = check_execution_journal.read(connection, payload)
                elif action == "observe":
                    result = check_execution_journal.record(connection, payload, raw=raw, now=now)
                else:
                    raise check_journal.CheckJournalError("unknown_check_execution_action")
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def retain_media_review(
        self, draft_id: str, request: dict, *, principal: Principal,
        resolve_principal: Callable[[str], Principal | None], assets: dict[str, bytes],
        now: datetime, before_commit: Callable[[], None] | None = None,
    ) -> dict:
        """Retain one exact private package, with role resolution under the lock.

        The caller authenticates ingress and supplies a bounded trusted resolver.
        Neither this local method nor constructing a Principal authenticates a
        person. Only evidence storage changes; no draft, approval or intent does.
        """
        if not isinstance(principal, Principal):
            raise CommandError("invalid_principal", "A trusted ingress principal is required")
        ingress = Principal(principal.subject, principal.role, principal.authentication_context)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._check_tables(connection)
                self._check_environment(connection)
                resolved = resolve_principal(ingress.subject)
                if not isinstance(resolved, Principal) or resolved.subject != ingress.subject:
                    raise CommandError("forbidden", "Reviewer identity is unavailable at retention")
                actor = Principal(ingress.subject, resolved.role, ingress.authentication_context)
                authorize(actor, "record_review")
                result = media_journal.retain(
                    connection, draft_id, request, principal=actor, assets=assets,
                    recorded_at=utc_text(now),
                )
                if before_commit is not None:
                    before_commit()
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def read_media_review(self, review_sha256: str) -> dict:
        """Read exact historical evidence only; current acceptance is not inferred."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            self._check_tables(connection)
            self._check_environment(connection)
            return media_journal.read(connection, review_sha256)

    def batch_status(self, job_id: str) -> dict:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            self._check_environment(connection)
            return batch_journal.read(connection, job_id)

    def read(self) -> tuple[int, dict]:
        with closing(self._connect()) as connection:
            self._check_environment(connection)
            row = connection.execute("SELECT version,state_json FROM authority_state WHERE singleton=1").fetchone()
            return row["version"], json.loads(row["state_json"])

    def result(self, command_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            self._check_environment(connection)
            row = connection.execute("SELECT result_json FROM command_results WHERE command_id=?", (command_id,)).fetchone()
            return json.loads(row["result_json"]) if row else None

    def journal(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            self._check_environment(connection)
            return [{**dict(row), "data": json.loads(row["data_json"])} for row in connection.execute("SELECT * FROM command_events ORDER BY sequence")]
