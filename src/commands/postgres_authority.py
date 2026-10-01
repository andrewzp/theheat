"""Isolated PostgreSQL command/spending core; no production ingress or providers.

Principal/resolver/policy are trusted local adapter inputs, not authentication.
The current pointer, immutable projection and terminal result commit together.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from src.commands import postgres_batch, postgres_batch_results, postgres_batch_worker, postgres_spending
from src.commands import postgres_check_observations, postgres_checks, postgres_media
from src.commands.reducer import AutomaticPolicy, reduce_command
from src.commands.schema import Command, CommandError, Principal, authorize, canonical_json, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.storage import postgres_projection as p

SCHEMA = "theheat_commands"
NAMESPACE = "command-core-v1"
MIGRATION = p.MIGRATION.with_name("002_command_core.sql")
MAX_BODY = 1024 * 1024
MAX_JOURNAL_BYTES = 8 * MAX_BODY


def _id(value: str) -> str:
    try:
        valid = type(value) is str and len(value) == 36 and str(UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    p._require(valid, "invalid_command_id")
    return value


def _clock(now: datetime | None) -> datetime:
    if now is not None and not isinstance(now, datetime):
        raise CommandError("invalid_time", "An aware execution clock is required")
    return utc_datetime(utc_text(now if now is not None else datetime.now(UTC)))


def _body(value: dict) -> bytes:
    encoded = p._canonical(value)
    p._require(len(encoded) <= MAX_BODY, "command_record_bound")
    return encoded


def _decode(raw: bytes, digest: str) -> dict:
    p._require(type(raw) is bytes and len(raw) <= MAX_BODY and p._sha(raw) == digest,
               "corrupt_command_record")
    value = p._decode(raw)
    p._require(type(value) is dict and _body(value) == raw, "corrupt_command_record")
    return value


def _command(raw: bytes, digest: str) -> Command:
    value = _decode(raw, digest)
    try:
        command = Command.from_stored(canonical_json(value))
        p._require(command.digest == digest, "corrupt_command_intent")
        return command
    except CommandError:
        raise p.ProjectionError("corrupt_command_intent") from None


class PostgresCommandAuthority:
    def __init__(self, *, socket_directory: str | Path, database: str, user: str,
                 port: int = 5432, environment: str = "local"):
        self.projections = p.PostgresProjectionRepository(
            socket_directory=socket_directory, database=database, user=user,
            port=port, environment=environment,
        )
        self.environment = environment

    def _validate(self, c, *, runtime: bool = True) -> None:
        self.projections._validate(c, runtime=runtime)
        row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
        p._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()),
                   "unsupported_command_schema")
        p._require(row[2] == p._catalog(c, SCHEMA), "changed_command_schema")
        p._require(row[3] == self.environment, "command_environment_mismatch")
        roles = c.execute(f"SELECT owner_role,runtime_role FROM {p.SCHEMA}.metadata WHERE singleton=1").fetchone()
        p._require(tuple(row[4:]) == roles, "command_role_mismatch")
        if not runtime:
            p._require(row[4] == self.projections.user, "migration_owner_required")

    @staticmethod
    def _pointer(c, *, lock: bool = False) -> tuple[int, str, str]:
        row = c.execute(f"SELECT version,namespace,snapshot_id FROM {SCHEMA}.state WHERE singleton=1" + (" FOR UPDATE" if lock else "")).fetchone()
        p._require(row is not None and row[1] == NAMESPACE and row[2] == str(row[0]),
                   "corrupt_authority_pointer")
        return row

    @staticmethod
    def _state(c, *, lock: bool = False) -> tuple[int, dict]:
        row = PostgresCommandAuthority._pointer(c, lock=lock)
        _, state = p.PostgresProjectionRepository._read(c, row[1], row[2])
        return row[0], state

    def initialize_media_staging(self) -> None:
        """Explicit owner migration; no attachment or production activation."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_media.install(c, self.environment)

    def stage_media_proposal(self, draft_id: str, request: dict, principal: Principal, *,
                             assets: dict, resolve_principal: Callable[[str], Principal | None],
                             now: datetime) -> dict:
        """Trusted local ingress; a Principal object is not web authentication."""
        request, assets = postgres_media.prepare(request, assets)
        if not isinstance(principal, Principal):
            raise CommandError("forbidden", "An authenticated local principal is required")
        principal = Principal(principal.subject, principal.role, principal.authentication_context)
        authorize(principal, "stage_media_proposal")
        if not isinstance(now, datetime):
            raise CommandError("invalid_time", "An explicit aware staging clock is required")
        clock = _clock(now)
        with self.projections._connection(writing=True) as c:
            self._validate(c)
            version, state = self._state(c, lock=True)
            try:
                current = resolve_principal(principal.subject)
                if current is not None:
                    if not isinstance(current, Principal):
                        raise TypeError("invalid resolved principal")
                    current = Principal(current.subject, current.role, current.authentication_context)
            except Exception:
                raise CommandError("authorization_unavailable", "Current operator authorization is unavailable") from None
            if current is None or current.subject != principal.subject:
                raise CommandError("forbidden", "Operator authorization is unavailable")
            authorize(current, "stage_media_proposal")
            actor = Principal(principal.subject, current.role, principal.authentication_context)
            result = postgres_media.stage(c, draft_id, request, assets=assets, principal=actor,
                state=state, authority_version=version, policy=current_editorial_policy(),
                now=clock, environment=self.environment)
        return result

    def read_media_proposal(self, proposal_sha256: str) -> dict:
        """Trusted local historical read; no public asset-serving endpoint."""
        with self.projections._connection() as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_media.read(c, proposal_sha256, self.environment)
        return result

    def initialize_check_executions(self) -> None:
        """Explicit owner install for immutable raw check observations."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_check_observations.install(c, self.environment)

    def check_execution(self, action: str, payload: dict, *, now: str,
                        raw: bytes | None = None) -> dict:
        with self.projections._connection(writing=action != "read") as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_check_observations.apply(c, action, payload, now=now,
                                                       raw=raw, environment=self.environment)
        return result

    def read_check_request(self, check_set_id: str, stage: str, grant_id: str) -> bytes:
        """Exact request for one committed grant, even before a response exists."""
        with self.projections._connection() as c:
            self._validate(c)
            self._pointer(c, lock=True)
            raw = postgres_check_observations.read_request(c, check_set_id, stage, grant_id,
                                                           environment=self.environment)
        return raw

    def read_check_response(self, check_set_id: str, stage: str, grant_id: str) -> bytes:
        """Grant-bound retained bytes; does not interpret or approve the response."""
        with self.projections._connection() as c:
            self._validate(c)
            self._pointer(c, lock=True)
            raw = postgres_check_observations.read_response(c, check_set_id, stage, grant_id,
                                                            environment=self.environment)
        return raw

    def initialize_candidate_checks(self) -> None:
        """Explicit owner install; no provider execution or check pass is implied."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_checks.install(c, self.environment)

    def candidate_checks(self, action: str, payload: dict, *, now: str,
                         request: bytes | None = None, receipt: dict | None = None) -> dict:
        with self.projections._connection(writing=action != "status") as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_checks.apply(c, action, payload, now=now, environment=self.environment,
                                           request=request, receipt=receipt)
        # Do not expose a grant until commit acknowledgment succeeds.
        return result

    def initialize_batch_results(self) -> None:
        """Explicit owner install for raw results and immutable review evidence."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_batch_results.install(c, self.environment)

    def record_batch_results(self, payload: dict, *, metadata: bytes, results: bytes, now: str) -> dict:
        return self._batch_results_transaction("record", payload, metadata=metadata, results=results, now=now)

    def batch_results_status(self, job_id: str, *, now: str) -> dict:
        return self._batch_results_transaction("index", {"job_id": job_id}, now=now)

    def review_batch_results(self, payload: dict, *, now: str) -> dict:
        return self._batch_results_transaction("review", payload, now=now)

    def _batch_results_transaction(self, action: str, payload: dict, *, now: str,
                                   metadata: bytes | None = None, results: bytes | None = None) -> dict:
        with self.projections._connection(writing=action != "index") as c:
            self._validate(c)
            self._pointer(c, lock=True)
            if action == "record":
                receipt = postgres_batch_results.record(c, payload, metadata, results, now=now, environment=self.environment)
            elif action == "index":
                receipt = postgres_batch_results.index(c, payload, now=now, environment=self.environment)
            else:
                receipt = postgres_batch_results.review(c, payload, now=now, environment=self.environment)
        return receipt

    def initialize_batch_workers(self) -> None:
        """Explicit owner-only installation; no limits, jobs or grants selected."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_batch_worker.install(c, self.environment)

    def batch_work(self, action: str, payload: dict, *, now: str, raw: bytes | None = None) -> dict:
        with self.projections._connection(writing=action != "status") as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_batch_worker.apply(c, action, payload, now=now, raw=raw, environment=self.environment)
        # A lost commit acknowledgment never returns a provisional dispatch grant.
        return result

    def initialize_spending(self) -> None:
        """Explicit owner-only install; never selects limits or changes state."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_spending.install(c, self.environment)

    def spending(self, action: str, payload: dict, *, now: str) -> dict:
        """Trusted local operation; dispatch permission exists only after commit."""
        with self.projections._connection(writing=True) as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_spending.apply(c, action, payload, now=now, environment=self.environment)
        return result

    def initialize_batches(self) -> None:
        """Explicit owner-only registration schema install; no holds or jobs."""
        with self.projections._connection(writing=True) as c:
            self._validate(c, runtime=False)
            self._pointer(c, lock=True)
            postgres_batch.install(c, self.environment)

    def prepare_batch(self, plan_bytes: bytes, *, expected_plan_sha256: str,
                      reservation: dict, now: str) -> dict:
        with self.projections._connection(writing=True) as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_batch.register(c, plan_bytes,
                expected_plan_sha256=expected_plan_sha256, reservation=reservation,
                now=now, environment=self.environment)
        return result

    def batch_status(self, job_id: str) -> dict:
        with self.projections._connection() as c:
            self._validate(c)
            self._pointer(c, lock=True)
            result = postgres_batch.read(c, job_id, environment=self.environment)
        return result

    def initialize(self, initial_state: dict, *, runtime_role: str) -> None:
        encoded, fields = p._snapshot(initial_state)
        # Separate schema provisioning may commit first; no authority exists yet.
        self.projections.initialize(runtime_role=runtime_role)
        driver = p._driver()
        with self.projections._connection(writing=True) as c:
            c.execute("SELECT pg_advisory_xact_lock(724718,1102)")
            self.projections._validate(c, runtime=False)
            if c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
                self._validate(c, runtime=False)
                _, current = self._state(c, lock=True)
                p._require(p._canonical(current) == encoded, "already_initialized")
            else:
                c.execute(MIGRATION.read_text())
                role = driver.sql.Identifier(runtime_role)
                c.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM PUBLIC")
                c.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM PUBLIC")
                c.execute(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM PUBLIC")
                for statement in (
                    f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {{}}",
                    f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {{}}",
                    f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {{}}",
                    f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {SCHEMA} FROM {{}}",
                    f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                    f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                    f"GRANT INSERT ON {SCHEMA}.intents,{SCHEMA}.results,{SCHEMA}.events TO {{}}",
                    f"GRANT UPDATE(version,snapshot_id) ON {SCHEMA}.state TO {{}}",
                    f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {{}}",
                ):
                    c.execute(driver.sql.SQL(statement).format(role))
                c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,current_user,%s)",
                          (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), self.environment, runtime_role))
                self.projections._record(c, NAMESPACE, "0", encoded, fields)
                c.execute(f"INSERT INTO {SCHEMA}.state VALUES(1,0,%s,'0')", (NAMESPACE,))
                self._validate(c, runtime=False)
                self._state(c)

    @staticmethod
    def _intent(c, command_id: str) -> tuple[Command, dict] | None:
        row = c.execute(f"SELECT sequence,digest,command_bytes,accepted_at FROM {SCHEMA}.intents WHERE command_id=%s", (command_id,)).fetchone()
        if row is None:
            return None
        sequence, digest, raw, accepted_at = row
        command = _command(raw, digest)
        p._require(command.command_id == command_id, "corrupt_command_intent")
        utc_datetime(accepted_at)
        receipt = {"command_id": command_id, "sequence": sequence,
                   "accepted_at": accepted_at, "digest": digest}
        PostgresCommandAuthority._verify_event(c, command_id, "accepted", accepted_at, receipt)
        return command, receipt

    @staticmethod
    def _verify_event(c, command_id: str, event: str, at: str, value: dict) -> None:
        row = c.execute(f"SELECT recorded_at,data_bytes,digest FROM {SCHEMA}.events WHERE command_id=%s AND event=%s",
                        (command_id, event)).fetchone()
        p._require(row is not None and row[0] == at, "missing_command_event")
        p._require(_body(_decode(row[1], row[2])) == _body(value), "corrupt_command_event")

    @staticmethod
    def _event(c, command_id: str, event: str, at: str, data: dict) -> None:
        encoded = _body(data)
        c.execute(f"INSERT INTO {SCHEMA}.events(command_id,event,recorded_at,data_bytes,digest) VALUES(%s,%s,%s,%s,%s)",
                  (command_id, event, at, encoded, p._sha(encoded)))

    def _result(self, c, command_id: str) -> dict | None:
        row = c.execute(f"SELECT result_bytes,digest,state_version,namespace,snapshot_id FROM {SCHEMA}.results WHERE command_id=%s", (command_id,)).fetchone()
        if row is None:
            return None
        raw, digest, version, namespace, snapshot_id = row
        result = _decode(raw, digest)
        intent = self._intent(c, command_id)
        p._require(intent is not None and namespace == NAMESPACE and snapshot_id == str(version), "corrupt_command_result")
        assert intent is not None
        cmd, _ = intent
        p._require(result.get("command_id") == command_id and result.get("digest") == cmd.digest
                   and type(result.get("state_version")) is int and result["state_version"] == version
                   and result.get("actor_subject") == cmd.actor_subject
                   and type(result.get("status")) is str
                   and result["status"] in {"applied", "unchanged", "rejected"}, "corrupt_command_result")
        utc_datetime(result.get("completed_at"))
        self.projections._read(c, namespace, snapshot_id)
        self._verify_event(c, command_id, "completed", result["completed_at"], result)
        return result

    def accept(self, command: Command, principal: Principal, *, now: datetime | None = None) -> dict:
        if not isinstance(command, Command) or not isinstance(principal, Principal):
            raise CommandError("invalid_command", "A validated command and trusted principal are required")
        command = Command.from_stored(canonical_json(command.as_dict()))
        principal = Principal(principal.subject, principal.role, principal.authentication_context)
        if command.environment != self.environment:
            raise CommandError("environment_mismatch", "Command belongs to another authority environment")
        if command.actor_subject != principal.subject or command.authentication_context != principal.authentication_context:
            raise CommandError("forbidden", "Command identity does not match authenticated ingress")
        authorize(principal, command.action)
        raw = _body(command.as_dict())
        with self.projections._connection(writing=True) as c:
            self._validate(c)
            self._state(c, lock=True)
            clock = _clock(now)
            prior = self._intent(c, command.command_id)
            if prior:
                if prior[0].digest != command.digest:
                    raise CommandError("command_id_reused", "Command ID already belongs to another request")
                receipt = prior[1]
            else:
                if clock >= utc_datetime(command.expires_at):
                    raise CommandError("command_expired", "Command expired before durable acceptance")
                if utc_datetime(command.requested_at) > clock + timedelta(minutes=5):
                    raise CommandError("invalid_time", "Command was requested too far in the future")
                at = utc_text(clock)
                row = c.execute(f"INSERT INTO {SCHEMA}.intents(command_id,digest,command_bytes,accepted_at) VALUES(%s,%s,%s,%s) RETURNING sequence",
                                (command.command_id, command.digest, raw, at)).fetchone()
                receipt = {"command_id": command.command_id, "sequence": row[0], "accepted_at": at, "digest": command.digest}
                self._event(c, command.command_id, "accepted", at, receipt)
        return receipt

    def consume(self, resolve_principal: Callable[[str], Principal | None], *, command_id: str | None = None,
                now: datetime | None = None, policy: AutomaticPolicy = AutomaticPolicy()) -> dict | None:
        if command_id is not None:
            command_id = _id(command_id)
        with self.projections._connection(writing=True) as c:
            self._validate(c)
            version, state = self._state(c, lock=True)
            prior = self._result(c, command_id) if command_id is not None else None
            if prior is not None:
                result = prior
            else:
                oldest = c.execute(f"SELECT i.command_id FROM {SCHEMA}.intents i LEFT JOIN {SCHEMA}.results r USING(command_id) WHERE r.command_id IS NULL ORDER BY i.sequence LIMIT 1").fetchone()
                if command_id is not None:
                    if self._intent(c, command_id) is None:
                        raise CommandError("command_not_found", "No durable acceptance exists for this command")
                    if oldest is None or oldest[0] != command_id:
                        raise CommandError("command_pending", "An earlier accepted command must finish first")
                if oldest is None:
                    result = None
                else:
                    intent = self._intent(c, oldest[0])
                    p._require(intent is not None, "corrupt_command_intent")
                    assert intent is not None
                    command, _ = intent
                    p._require(command.environment == self.environment, "command_environment_mismatch")
                    clock = _clock(now)
                    # Resolver failures are infrastructure uncertainty, never a
                    # durable rejection. An explicit None is actual revocation.
                    try:
                        actor = resolve_principal(command.actor_subject)
                        if actor is not None:
                            p._require(isinstance(actor, Principal), "invalid_resolved_principal")
                            actor = Principal(actor.subject, actor.role, actor.authentication_context)
                    except Exception:
                        raise CommandError("authorization_unavailable", "Current operator authorization is unavailable") from None
                    editorial_policy = current_editorial_policy()
                    changed = None
                    try:
                        if actor is None:
                            raise CommandError("forbidden", "Operator authorization was revoked before execution")
                        reduction = reduce_command(state, command, actor, now=clock, policy=policy, editorial_policy=editorial_policy)
                        result = {"status": "applied" if reduction.changed_ids else "unchanged", "changed_ids": list(reduction.changed_ids),
                                  "identities": list(reduction.identities), "publish_intent_id": reduction.publish_intent_id}
                        if reduction.changed_ids:
                            changed = reduction.state
                    except CommandError as exc:
                        result = {"status": "rejected", "code": exc.code, "message": str(exc)}
                    except (ValueError, TypeError, UnicodeError, OverflowError):
                        result = {"status": "rejected", "code": "invalid_revision", "message": "Stored revision cannot be validated"}
                    # Storage work is deliberately outside reducer error handling.
                    if changed is not None:
                        encoded, fields = p._snapshot(changed)
                        p._require(version < p.MAX_INTEGER, "authority_version_exhausted")
                        version += 1
                        self.projections._record(c, NAMESPACE, str(version), encoded, fields)
                        c.execute(f"UPDATE {SCHEMA}.state SET version=%s,snapshot_id=%s WHERE singleton=1", (version, str(version)))
                    result.update(command_id=command.command_id, digest=command.digest, state_version=version,
                                  completed_at=utc_text(clock), actor_subject=command.actor_subject)
                    encoded_result = _body(result)
                    c.execute(f"INSERT INTO {SCHEMA}.results VALUES(%s,%s,%s,%s,%s,%s)",
                              (command.command_id, encoded_result, p._sha(encoded_result), version, NAMESPACE, str(version)))
                    self._event(c, command.command_id, "completed", utc_text(clock), result)
        return result

    def read(self) -> tuple[int, dict]:
        with self.projections._connection() as c:
            self._validate(c)
            result = self._state(c)
        return result

    def result(self, command_id: str) -> dict | None:
        command_id = _id(command_id)
        with self.projections._connection() as c:
            self._validate(c)
            result = self._result(c, command_id)
        return result

    def journal(self, *, after_sequence: int = 0, limit: int = 100) -> list[dict]:
        p._require(type(after_sequence) is int and 0 <= after_sequence <= p.MAX_INTEGER and type(limit) is int and 1 <= limit <= 100,
                   "invalid_journal_page")
        with self.projections._connection() as c:
            self._validate(c)
            rows = c.execute(f"SELECT sequence,command_id,event,recorded_at,octet_length(data_bytes) FROM {SCHEMA}.events WHERE sequence>%s ORDER BY sequence LIMIT %s",
                             (after_sequence, limit)).fetchall()
            p._require(sum(row[4] for row in rows) <= MAX_JOURNAL_BYTES, "journal_page_bound")
            events = []
            for sequence, command_id, event, at, _ in rows:
                raw, digest = c.execute(f"SELECT data_bytes,digest FROM {SCHEMA}.events WHERE sequence=%s", (sequence,)).fetchone()
                data = _decode(raw, digest)
                expected: dict | None
                if event == "accepted":
                    intent = self._intent(c, command_id)
                    p._require(intent is not None, "corrupt_command_event")
                    assert intent is not None
                    expected = intent[1]
                    expected_at = expected["accepted_at"]
                else:
                    expected = self._result(c, command_id)
                    p._require(expected is not None, "corrupt_command_event")
                    assert expected is not None
                    expected_at = expected["completed_at"]
                p._require(_body(data) == _body(expected) and at == expected_at, "corrupt_command_event")
                events.append({"sequence": sequence, "command_id": command_id, "event": event, "recorded_at": at, "data": data})
        return events
