"""Real PostgreSQL command transactions and paired reducer behavior; no providers."""
from copy import deepcopy
from datetime import timedelta
import multiprocessing
import os
from uuid import uuid4

import pytest

from src.commands.postgres_authority import PostgresCommandAuthority, SCHEMA, NAMESPACE
from src.commands.reducer import AutomaticPolicy
from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_text
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from tests.test_command_authority import EDITOR, PUBLISHER, NOW, story, command, resolver, request
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, wrap_connections


def options(params, user="projection_runtime"):
    return dict(socket_directory=params["host"], port=params["port"], database=params["dbname"], user=user)


@pytest.fixture
def make_authority(database):
    _, _, params = database
    owner = PostgresCommandAuthority(**options(params, params["user"]))
    runtime = PostgresCommandAuthority(**options(params))
    def make(initial):
        owner.initialize(initial, runtime_role="projection_runtime")
        return runtime
    return make, owner, params


@pytest.fixture
def core(make_authority):
    make, owner, params = make_authority
    initial = {"drafts": [story()], "unknown": {"empty": [], "text": "synthetic\u0000☀"}}
    store = make(initial)
    return store, initial, owner, params


def table_counts(params):
    return {table: admin(params, f"SELECT count(*) FROM {SCHEMA}.{table}")[0][0]
            for table in ("intents", "results", "events")}


def test_initialize_idempotent_never_replaces(core):
    store, initial, owner, params = core
    assert store.read() == (0, initial)
    owner.initialize(initial, runtime_role="projection_runtime")
    with pytest.raises(p.ProjectionError, match="already_initialized"):
        owner.initialize({"drafts": []}, runtime_role="projection_runtime")
    assert store.read() == (0, initial)
    assert store.consume(resolver, now=NOW) is None
    assert store.result(str(uuid4())) is None
    assert store.journal() == []
    with pytest.raises(p.ProjectionError, match="non_owner_runtime_role_required"):
        owner.read()


@pytest.mark.parametrize("action", ["edit_revision", "select_candidate", "record_review", "approve_revision",
                                     "schedule_revision", "cancel_approval", "reject_revision", "bulk_reject"])
def test_paired_sqlite_postgres_transitions(make_authority, tmp_path, action):
    make, _, _ = make_authority
    drafts = [story("one"), story("two")]
    candidate = {"rank": 1, "text": "A shorter synthetic candidate.", "score": 80}
    drafts[0]["candidates"] = [candidate]
    initial = {"drafts": drafts, "source_health": {"fixture": {"retained": True}}, "publish_ledger": {}}
    payloads = {
        "edit_revision": {"text": "A concise synthetic edit."},
        "select_candidate": {"candidate_rank": 1, "candidate_sha256": fingerprint(candidate)},
        "record_review": {"confirmed": True, "reason": "Synthetic evidence review", "expected_policy_sha256": fingerprint(current_editorial_policy())},
        "approve_revision": {"reason": "Synthetic approval"},
        "schedule_revision": {"delay_minutes": 30, "publication_epoch": "release-fixture", "reason": "Synthetic schedule"},
        "cancel_approval": {"reason": "Cancel synthetic approval"},
        "reject_revision": {"reason": "Synthetic rejection"},
        "bulk_reject": {"reason": "Synthetic bulk rejection"},
    }
    cmd = command(drafts if action == "bulk_reject" else drafts[0], action, payloads[action], principal=PUBLISHER)
    postgres = make(initial)
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(initial)
    receipts, results, states = [], [], []
    for store in (sqlite, postgres):
        receipts.append(store.accept(cmd, PUBLISHER, now=NOW))
        results.append(store.consume(resolver, now=NOW, policy=AutomaticPolicy(True, "release-fixture")))
        states.append(store.read())
    assert receipts[0] == receipts[1]
    assert results[0] == results[1]
    assert states[0] == states[1]
    assert states[0][0] == 1
    assert [r["data"] for r in sqlite.journal()] == [r["data"] for r in postgres.journal()]


def test_idempotency_stale_conflict_fifo_and_noop(core):
    store, initial, _, _ = core
    draft = initial["drafts"][0]
    first = command(draft)
    second = command(draft, payload={"text": "Different synthetic edit."})
    receipt = store.accept(first, EDITOR, now=NOW)
    assert store.accept(first, EDITOR, now=NOW + timedelta(hours=2)) == receipt
    store.accept(second, EDITOR, now=NOW)
    with pytest.raises(CommandError) as pending:
        store.consume(resolver, command_id=second.command_id, now=NOW)
    assert pending.value.code == "command_pending"
    result = store.consume(resolver, now=NOW)
    assert result["status"] == "applied"
    assert store.consume(lambda _: None, command_id=first.command_id, now=NOW + timedelta(days=2)) == result
    assert store.result(first.command_id) == result
    assert store.consume(resolver, now=NOW)["code"] == "revision_conflict"
    current = store.read()[1]["drafts"][0]
    unchanged = command(current, payload={"text": current["text"]})
    store.accept(unchanged, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["status"] == "unchanged"
    assert store.read()[0] == 1
    conflict = command(draft, command_id=first.command_id, payload={"text": "Conflicting identity"})
    with pytest.raises(CommandError) as reused:
        store.accept(conflict, EDITOR, now=NOW)
    assert reused.value.code == "command_id_reused"
    with pytest.raises(CommandError) as absent:
        store.consume(resolver, command_id=str(uuid4()), now=NOW)
    assert absent.value.code == "command_not_found"


@pytest.mark.parametrize("mode", ["revoked", "viewer", "wrong-subject", "expired", "source-drift", "decision-drift", "missing-checks", "unknown-outcome", "policy-drift", "retired-epoch", "paused"])
def test_rejections_preserve_state(make_authority, mode):
    make, _, _ = make_authority
    draft = story()
    cmd = command(draft)
    initial = {"drafts": [draft]}
    resolve = resolver
    now = NOW
    actor = EDITOR
    policy = AutomaticPolicy(True, "release-fixture")
    expected = "forbidden"
    if mode == "revoked":
        def resolve(_):
            return None
    elif mode == "viewer":
        def resolve(_):
            return Principal(EDITOR.subject, "viewer", "refreshed")
    elif mode == "wrong-subject":
        def resolve(_):
            return PUBLISHER
    elif mode == "expired":
        now += timedelta(hours=2)
        expected = "command_expired"
    elif mode == "source-drift":
        draft["review_context"]["two_bot"]["bundle"]["value"] = 99
        expected = "revision_conflict"
    elif mode == "decision-drift":
        draft["decision_revision"] += 1
        expected = "revision_conflict"
    elif mode == "unknown-outcome":
        initial["publish_ledger"] = {draft["event_id"]: {"phase": "unknown"}}
        expected = "publication_unresolved"
    elif mode == "missing-checks":
        draft["review_context"]["two_bot"].pop("fact_check", None)
        cmd = command(draft, "approve_revision", {"reason": "Synthetic"}, principal=PUBLISHER)
        actor, expected = PUBLISHER, "review_required"
    elif mode == "policy-drift":
        cmd = command(draft, "record_review", {"confirmed": True, "reason": "Synthetic", "expected_policy_sha256": "0" * 64})
        expected = "editorial_policy_changed"
    else:
        cmd = command(draft, "schedule_revision", {"delay_minutes": 30, "publication_epoch": "release-fixture", "reason": "Synthetic"}, principal=PUBLISHER)
        actor, expected = PUBLISHER, "automatic_publication_paused"
        if mode == "retired-epoch":
            initial["publication_control"] = {"retired_epochs": ["release-fixture"]}
        else:
            policy = AutomaticPolicy()
    store = make(initial)
    store.accept(cmd, actor, now=NOW)
    result = store.consume(resolve, now=now, policy=policy)
    assert result["status"] == "rejected" and result["code"] == expected
    assert store.read() == (0, initial)
    assert store.result(cmd.command_id) == result


def test_acceptance_role_environment_time_and_mutated_dataclass(core):
    store, initial, _, params = core
    draft = initial["drafts"][0]
    cmd = command(draft)
    for actor in (PUBLISHER, Principal(EDITOR.subject, "viewer", EDITOR.authentication_context),
                  Principal(EDITOR.subject, "editor", "different ingress")):
        with pytest.raises(CommandError):
            store.accept(cmd, actor, now=NOW)
    with pytest.raises(CommandError) as expired:
        store.accept(cmd, EDITOR, now=NOW + timedelta(days=1))
    assert expired.value.code == "command_expired"
    with pytest.raises(CommandError) as future:
        store.accept(cmd, EDITOR, now=NOW - timedelta(hours=1))
    assert future.value.code == "invalid_time"
    prod = Command.from_request(request(draft), EDITOR, environment="production", now=NOW)
    with pytest.raises(CommandError):
        store.accept(prod, EDITOR, now=NOW)
    forged = deepcopy(cmd)
    object.__setattr__(forged, "schema_version", 2)
    with pytest.raises(CommandError):
        store.accept(forged, EDITOR, now=NOW)
    assert table_counts(params) == {"intents": 0, "results": 0, "events": 0}


def test_resolver_exception_is_not_a_terminal_rejection(core):
    store, initial, _, _ = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    def fail(_):
        raise ValueError("private system lookup detail")
    with pytest.raises(CommandError, match="^Current operator authorization is unavailable$") as error:
        store.consume(fail, now=NOW)
    assert error.value.code == "authorization_unavailable"
    assert store.result(cmd.command_id) is None and store.read() == (0, initial)
    assert store.consume(resolver, now=NOW)["status"] == "applied"


@pytest.mark.parametrize("stage", ["theheat_projection.versions", "theheat_projection.artifacts", "theheat_projection.fields", "theheat_commands.state", "theheat_commands.results", "theheat_commands.events"])
def test_partial_consume_is_one_transaction(core, monkeypatch, stage):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    def fail(query, _):
        if query.startswith((f"INSERT INTO {stage}", f"UPDATE {stage}")):
            raise RuntimeError("synthetic crash stage")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic crash stage"):
            store.consume(resolver, now=NOW)
    assert store.read() == (0, initial)
    assert table_counts(params) == {"intents": 1, "results": 0, "events": 1}
    assert admin(params, "SELECT count(*) FROM theheat_projection.versions")[0][0] == 1
    assert store.consume(resolver, now=NOW)["status"] == "applied"


@pytest.mark.parametrize("stage", ["intents", "events"])
def test_acceptance_partial_rollback(core, monkeypatch, stage):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    def fail(query, _):
        if query.startswith(f"INSERT INTO {SCHEMA}.{stage}"):
            raise RuntimeError("synthetic acceptance crash")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic acceptance crash"):
            store.accept(cmd, EDITOR, now=NOW)
    assert table_counts(params) == {"intents": 0, "results": 0, "events": 0}
    # A rolled-back identity sequence may leave a harmless gap.
    store.accept(cmd, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["status"] == "applied"


@pytest.mark.parametrize("stage", ["accept", "consume"])
def test_lost_commit_acknowledgment_reconciles(core, monkeypatch, stage):
    import psycopg
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    if stage == "consume":
        store.accept(cmd, EDITOR, now=NOW)
    connect = psycopg.connect
    seen = []
    def before_commit(_):
        with connect(**params) as other:
            seen.append(other.execute("SELECT version FROM theheat_commands.state").fetchone()[0])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=before_commit, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="^write_outcome_unknown$"):
            if stage == "accept":
                store.accept(cmd, EDITOR, now=NOW)
            else:
                store.consume(resolver, now=NOW)
    assert seen == [0]
    receipt = store.accept(cmd, EDITOR, now=NOW + timedelta(days=1))
    assert receipt["command_id"] == cmd.command_id
    result = store.consume(resolver, command_id=cmd.command_id, now=NOW)
    assert result["status"] == "applied"
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW + timedelta(days=1)) == result
    assert store.read()[0] == 1 and table_counts(params) == {"intents": 1, "results": 1, "events": 2}


def test_connection_killed_before_commit(core, monkeypatch):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            store.consume(resolver, now=NOW)
    assert store.read() == (0, initial) and store.result(cmd.command_id) is None
    assert store.consume(resolver, now=NOW)["status"] == "applied"


def worker(opts, operation, item, barrier, queue, clock):
    try:
        store = PostgresCommandAuthority(**opts)
        barrier.wait(timeout=20)
        if operation == "accept":
            value = store.accept(item, EDITOR, now=clock)
        else:
            value = store.consume(resolver, command_id=item, now=clock)
        queue.put(value)
    except BaseException as exc:
        queue.put({"error": type(exc).__name__, "code": getattr(exc, "code", str(exc))})


def parallel(params, operation, items, *, clock=NOW):
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(len(items)), ctx.Queue()
    children = [ctx.Process(target=worker, args=(options(params), operation, item, barrier, queue, clock)) for item in items]
    try:
        for child in children:
            child.start()
        results = [queue.get(timeout=45) for _ in children]
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
        assert not any(isinstance(row, dict) and "error" in row for row in results), results
        return results
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
        queue.close()


def test_independent_process_acceptance_idempotency(core):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    receipts = parallel(params, "accept", [cmd, cmd, cmd])
    assert receipts[0] == receipts[1] == receipts[2]
    assert table_counts(params) == {"intents": 1, "results": 0, "events": 1}
    results = parallel(params, "consume", [cmd.command_id] * 3)
    assert results[0] == results[1] == results[2]
    assert store.read()[0] == 1


def test_independent_process_fifo_and_conflicting_edits(make_authority):
    make, _, params = make_authority
    drafts = [story("one"), story("two")]
    store = make({"drafts": drafts})
    commands = [command(drafts[0], payload={"text": "First synthetic edit."}),
                command(drafts[0], payload={"text": "Competing synthetic edit."}),
                command(drafts[1], payload={"text": "Unrelated synthetic edit."})]
    receipts = parallel(params, "accept", commands)
    order = [r["command_id"] for r in sorted(receipts, key=lambda r: r["sequence"])]
    results = parallel(params, "consume", [None] * 3)
    assert sorted(r["status"] for r in results) == ["applied", "applied", "rejected"]
    assert next(r for r in results if r["status"] == "rejected")["code"] == "revision_conflict"
    assert store.read()[0] == 2
    assert [r["command_id"] for r in store.journal() if r["event"] == "completed"] == order


@pytest.mark.parametrize("sql", [
    "GRANT UPDATE(namespace) ON theheat_commands.state TO projection_runtime",
    "GRANT UPDATE ON SEQUENCE theheat_commands.events_sequence_seq TO projection_runtime",
    "ALTER TABLE theheat_commands.state DISABLE TRIGGER state_progress",
    "CREATE TABLE theheat_commands.unexpected(value int)",
])
def test_schema_column_and_sequence_grant_changes_refused(core, sql):
    store, _, _, params = core
    admin(params, sql)
    with pytest.raises(p.ProjectionError, match="changed_command_schema"):
        store.read()


@pytest.mark.parametrize("sql", [
    "DELETE FROM theheat_commands.intents", "TRUNCATE theheat_commands.events CASCADE",
    "UPDATE theheat_commands.metadata SET version=2", "DROP TABLE theheat_commands.results",
    "UPDATE theheat_commands.state SET namespace='other'",
    "SELECT setval('theheat_commands.events_sequence_seq',900)",
])
def test_runtime_permissions(core, sql):
    import psycopg
    _, _, _, params = core
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": "projection_runtime"}, sql)


def test_pointer_cannot_skip_or_reference_incomplete_projection(core):
    import psycopg
    store, initial, _, params = core
    with pytest.raises(psycopg.errors.RaiseException, match="invalid authority progression"):
        admin({**params, "user": "projection_runtime"}, "UPDATE theheat_commands.state SET version=2,snapshot_id='2'")
    admin(params, "INSERT INTO theheat_projection.versions(namespace,snapshot_id,canonical_sha,byte_count,field_count) VALUES(%s,'1',%s,7,1)", (NAMESPACE, "0" * 64))
    with pytest.raises(psycopg.errors.RaiseException, match="incomplete authority projection"):
        admin({**params, "user": "projection_runtime"}, "UPDATE theheat_commands.state SET version=1,snapshot_id='1'")
    assert store.read() == (0, initial)


@pytest.mark.parametrize("event", ["accepted", "completed"])
def test_missing_history_refuses_receipt(core, event):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    store.consume(resolver, now=NOW)
    admin(params, "ALTER TABLE theheat_commands.events DISABLE TRIGGER events_immutable")
    admin(params, "DELETE FROM theheat_commands.events WHERE event=%s", (event,))
    admin(params, "ALTER TABLE theheat_commands.events ENABLE TRIGGER events_immutable")
    with pytest.raises(p.ProjectionError, match="missing_command_event"):
        store.result(cmd.command_id)


def test_journal_pages_and_read_purity(core):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    store.consume(resolver, now=NOW)
    before = table_counts(params)
    first = store.journal(limit=1)
    rest = store.journal(after_sequence=first[0]["sequence"])
    assert [r["event"] for r in first + rest] == ["accepted", "completed"]
    store.read()
    store.result(cmd.command_id)
    assert table_counts(params) == before
    with pytest.raises(p.ProjectionError, match="invalid_journal_page"):
        store.journal(limit=101)


def test_backup_restore_both_schemas(core, cluster):
    import psycopg
    store, initial, _, params = core
    args, run, root = cluster
    cmd = command(initial["drafts"][0])
    receipt = store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    dump = root / "authority.dump"
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    run("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    name = "restore_" + uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, dump)
        restored = PostgresCommandAuthority(**options({**params, "dbname": name}))
        assert restored.read() == store.read()
        assert restored.result(cmd.command_id) == result
        assert restored.accept(cmd, EDITOR, now=NOW) == receipt
        assert restored.consume(resolver, command_id=cmd.command_id, now=NOW) == result
        assert restored.journal() == store.journal()
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def test_failed_core_initialization_rolls_back_pointer_and_projection(make_authority, monkeypatch):
    _, owner, params = make_authority
    initial = {"drafts": [story()]}
    def fail(query, _):
        if query.startswith("INSERT INTO theheat_commands.state"):
            raise RuntimeError("synthetic initialization crash")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic initialization crash"):
            owner.initialize(initial, runtime_role="projection_runtime")
    assert admin(params, "SELECT to_regnamespace('theheat_commands')") == [(None,)]
    # Separately provisioned archive exists, with no partial initial version.
    assert admin(params, "SELECT count(*) FROM theheat_projection.versions") == [(0,)]
    owner.initialize(initial, runtime_role="projection_runtime")
    assert PostgresCommandAuthority(**options(params)).read() == (0, initial)


def test_read_committed_overrides_role_default(core, monkeypatch):
    store, initial, _, params = core
    seen = []
    def inspect(query, c):
        if query == "SET LOCAL search_path=pg_catalog":
            seen.append(c.execute("SHOW transaction_isolation").fetchone()[0])
    try:
        admin(params, "ALTER ROLE projection_runtime SET default_transaction_isolation='repeatable read'")
        with monkeypatch.context() as patch:
            wrap_connections(patch, after_execute=inspect)
            assert store.read() == (0, initial)
    finally:
        admin(params, "ALTER ROLE projection_runtime RESET default_transaction_isolation")
    assert seen == ["read committed"]


def test_production_and_unsupported_capabilities_absent(core):
    store, _, _, params = core
    with pytest.raises(p.ProjectionError, match="production_adapter_unavailable"):
        PostgresCommandAuthority(**options(params), environment="production")
    assert not any(hasattr(store, name) for name in ["dispatch", "publish", "import_snapshot", "retain_media_review"])
    from src.commands.spend_journal import SpendError
    with pytest.raises(SpendError, match="spend_migration_required"):
        store.spending("status", {}, now="2026-09-30T12:00:00Z")


def test_owner_default_privileges_removed_from_core(make_authority):
    make, _, params = make_authority
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    store = make({"drafts": [story()]})
    assert admin(params, "SELECT has_table_privilege('projection_runtime','theheat_commands.state','DELETE,TRUNCATE,INSERT'),has_column_privilege('projection_runtime','theheat_commands.state','namespace','UPDATE'),has_sequence_privilege('projection_runtime','theheat_commands.events_sequence_seq','UPDATE')") == [(False, False, False)]
    assert admin(params, "SELECT has_function_privilege('projection_runtime','theheat_commands.check_progress()','EXECUTE')") == [(False,)]
    cmd = command(store.read()[1]["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["status"] == "applied"


@pytest.mark.parametrize("change", [{"state_version": 99}, {"status": []}], ids=["identity", "status-type"])
def test_malformed_result_identity_not_accepted(core, change):
    store, initial, _, params = core
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    changed = {**result, **change}
    raw = p._canonical(changed)
    admin(params, "ALTER TABLE theheat_commands.results DISABLE TRIGGER results_immutable")
    admin(params, "UPDATE theheat_commands.results SET result_bytes=%s,digest=%s", (raw, p._sha(raw)))
    admin(params, "ALTER TABLE theheat_commands.results ENABLE TRIGGER results_immutable")
    with pytest.raises(p.ProjectionError, match="corrupt_command_result"):
        store.result(cmd.command_id)


def test_spawned_transactions_share_the_supplied_clock_not_child_import_time(core):
    store, initial, _, params = core
    clock = NOW - timedelta(hours=2)
    row = request(initial["drafts"][0])
    row.update(requested_at=utc_text(clock), expires_at=utc_text(clock + timedelta(hours=1)))
    cmd = Command.from_request(row, EDITOR, environment="local", now=clock)
    receipts = parallel(params, "accept", [cmd, cmd], clock=clock)
    assert receipts[0] == receipts[1]
    results = parallel(params, "consume", [cmd.command_id] * 2, clock=clock)
    assert results[0] == results[1] and results[0]["status"] == "applied"
    assert store.read()[0] == 1
    # The real expiry gate is still enforced at an explicitly later instant.
    expired = Command.from_request({**row, "command_id": str(uuid4())}, EDITOR, environment="local", now=clock)
    with pytest.raises(CommandError) as failure:
        store.accept(expired, EDITOR, now=clock + timedelta(hours=2))
    assert failure.value.code == "command_expired"
