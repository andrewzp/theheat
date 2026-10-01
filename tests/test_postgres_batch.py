"""Real PostgreSQL atomic batch registration; synthetic plans, no provider I/O."""
from copy import deepcopy
import json
import multiprocessing
import sys
from uuid import uuid4

import pytest

from src.commands import batch_journal as b, postgres_batch as pg, postgres_spending as spending
from src.commands.spend_journal import SpendError
from src.commands.sqlite_authority import SQLiteAuthority
from src.storage import postgres_projection as p
from src.two_bot.batch_contract import BatchContractError
from tests.test_batch_journal import NOW, LATER, packet, register, digest
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import make_authority as make_authority, core as core
from tests.test_postgres_command_authority import options, table_counts
from tests.test_spend_journal import LIMITS, call
from tests.two_bot.test_batch_contract import inputs as inputs
from src.commands.postgres_authority import PostgresCommandAuthority


@pytest.fixture
def spend_store(core):
    value, _, owner, _ = core
    owner.initialize_spending()
    call(value, "configure", LIMITS)
    return value


@pytest.fixture
def store(spend_store, core):
    core[2].initialize_batches()
    return spend_store


def snapshot(params):
    tables = (
        ("theheat_batches", ("metadata", "plans", "registrations")),
        ("theheat_spending", ("metadata", "limits", "intents", "events")),
        ("theheat_commands", ("metadata", "state", "intents", "results", "events")),
        ("theheat_projection", ("metadata", "versions", "artifacts", "fields")),
    )
    return {(schema, table): admin(params, f"SELECT * FROM {schema}.{table} ORDER BY 1,2")
            for schema, names in tables for table in names}


def test_exact_atomic_output_and_bytes_match_sqlite(store, core, inputs, tmp_path, monkeypatch):
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(core[1])
    call(sqlite, "configure", LIMITS)
    pair = packet(inputs)
    params = core[3]
    before = counts(params), table_counts(params), store.read(), store.journal()
    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("batch loaded current projection"))
        row = register(store, pair)
        assert store.batch_status(inputs["job_id"]) == {k: v for k, v in row.items() if k != "reused"}
    assert row == register(sqlite, pair)
    assert admin(params, "SELECT payload FROM theheat_batches.plans WHERE sha=%s", (digest(pair[0]),)) == [(pair[0],)]
    assert (counts(params), table_counts(params), store.read(), store.journal()) == before
    assert call(store, "status", {}) == call(sqlite, "status", {})
    assert register(store, pair) == register(sqlite, pair)
    assert set(row) == {"job_id", "plan_sha256", "intent_id", "registered_at", "useful_until",
                        "reservation_state", "dispatch_granted", "publication_approved", "reused"}


@pytest.mark.parametrize("state", ["reserved", "dispatched", "uncertain", "settled", "released"])
def test_exact_replay_after_expiry_reports_actual_state_without_writes(store, core, inputs, state):
    pair = packet(inputs)
    register(store, pair)
    identity = {"intent_id": "attempt-1"}
    if state in ("dispatched", "uncertain", "settled"):
        call(store, "dispatch", identity)
    if state in ("uncertain", "released"):
        call(store, "uncertain" if state == "uncertain" else "release", identity)
    if state == "settled":
        call(store, "settle", {**identity, "amount_micro_usd": 40, "evidence_sha256": "a" * 64})
    before = snapshot(core[3])
    reopened = PostgresCommandAuthority(**options(core[3]))
    for at in (LATER, "2026-01-01T00:00:00Z"):
        row = register(reopened, pair, at=at)
        assert row["reused"] and row["reservation_state"] == state
        assert row["dispatch_granted"] is False and row["publication_approved"] is False
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("field,value", [
    ("job_id", "other-job"), ("request_sha256", "b" * 64), ("provider", "google"),
    ("role", "critic"), ("model", "claude-other"), ("reserve_micro_usd", True),
    ("reserve_micro_usd", 0), ("estimate_sha256", ""), ("intent_id", []),
])
def test_invalid_reservation_never_writes(store, core, inputs, field, value):
    raw, reservation = packet(inputs)
    reservation[field] = value
    before = snapshot(core[3])
    with pytest.raises((b.BatchJournalError, SpendError)):
        register(store, (raw, reservation))
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("field,value", [("reserve_micro_usd", 61), ("estimate_sha256", "a" * 64), ("intent_id", "other")])
def test_registered_reservation_cannot_change(store, core, inputs, field, value):
    raw, reservation = packet(inputs)
    register(store, (raw, reservation))
    reservation[field] = value
    before = snapshot(core[3])
    with pytest.raises(b.BatchJournalError):
        register(store, (raw, reservation))
    assert snapshot(core[3]) == before


def test_job_and_intent_cannot_rebind(store, core, inputs):
    register(store, packet(inputs))
    before = snapshot(core[3])
    changed = deepcopy(inputs)
    changed["publication_epoch"] = "other-paused-epoch"
    with pytest.raises(b.BatchJournalError, match="job_id_reused"):
        register(store, packet(changed))
    with pytest.raises(b.BatchJournalError, match="identity_reused"):
        register(store, packet(inputs, job="another-job"))
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("at", ["2026-09-29T11:59:59Z", "2026-09-30T11:00:00Z", "2026-09-30T12:00:00Z", LATER])
def test_window_boundaries_leave_no_orphans(store, core, inputs, at):
    before = snapshot(core[3])
    with pytest.raises(b.BatchJournalError, match="outside_window"):
        register(store, packet(inputs), at=at)
    assert snapshot(core[3]) == before


def test_one_microsecond_of_extra_window_is_accepted(store, inputs):
    assert register(store, packet(inputs), at="2026-09-30T10:59:59.999999Z")["reservation_state"] == "reserved"


@pytest.mark.parametrize("variant", ["hash", "oversized", "duplicate", "malformed", "nonbytes", "reencoded"])
def test_invalid_plan_cannot_reserve_or_retain(store, core, inputs, variant):
    raw, reservation = packet(inputs)
    expected = digest(raw)
    if variant == "hash":
        expected = "f" * 64
    elif variant == "oversized":
        raw = b" " * 2_000_001
    elif variant == "duplicate":
        raw = b'{"job_id":"one","job_id":"two"}'
    elif variant == "malformed":
        raw = b"\xff"
    elif variant == "nonbytes":
        raw = bytearray(raw)
    else:
        raw = json.dumps(json.loads(raw), indent=2).encode()
        expected = digest(raw)
    before = snapshot(core[3])
    with pytest.raises(BatchContractError):
        store.prepare_batch(raw, expected_plan_sha256=expected, reservation=reservation, now=NOW)
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("state", ["reserved", "dispatched", "uncertain", "settled", "released"])
def test_only_exact_unused_existing_hold_can_join(store, core, inputs, state):
    pair = packet(inputs)
    call(store, "reserve", pair[1])
    if state in ("dispatched", "uncertain", "settled"):
        call(store, "dispatch")
    if state in ("uncertain", "released"):
        call(store, "uncertain" if state == "uncertain" else "release")
    if state == "settled":
        call(store, "settle", dict(intent_id="attempt-1", amount_micro_usd=40, evidence_sha256="a" * 64))
    before = snapshot(core[3])
    if state == "reserved":
        assert register(store, pair)["reservation_state"] == "reserved"
        assert call(store, "status", {})["intent_count"] == 1
    else:
        with pytest.raises(b.BatchJournalError, match="already_used"):
            register(store, pair)
        assert snapshot(core[3]) == before


def test_changed_existing_hold_remains_intact(store, core, inputs):
    pair = packet(inputs)
    call(store, "reserve", {**pair[1], "reserve_micro_usd": 61})
    before = snapshot(core[3])
    with pytest.raises(SpendError, match="id_reused"):
        register(store, pair)
    assert snapshot(core[3]) == before


def _worker(params, pair, barrier, results):
    try:
        barrier.wait(timeout=15)
        results.put(register(PostgresCommandAuthority(**options(params)), pair))
    except (b.BatchJournalError, SpendError) as exc:
        results.put(dict(denied=str(exc)))
    except BaseException as exc:
        results.put(dict(worker_error=repr(exc)))


def parallel(params, pairs):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(len(pairs)), ctx.Queue()
    children = [ctx.Process(target=_worker, args=(params, pair, barrier, results)) for pair in pairs]
    for child in children:
        child.start()
    try:
        values = [results.get(timeout=30) for child in children]
        for child in children:
            child.join(timeout=15)
            assert not child.is_alive() and child.exitcode == 0
        assert not [value for value in values if "worker_error" in value]
        return values
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)


@pytest.mark.parametrize("same", [True, False])
def test_real_workers_commit_one_affordable_complete_registration(store, core, inputs, same):
    pair = packet(inputs)
    other = pair if same else packet(inputs, job="second-job", identity="second-attempt")
    values = parallel(core[3], [pair, other])
    if same:
        assert sorted(row["reused"] for row in values) == [False, True]
    else:
        assert sum("denied" in row for row in values) == 1
    assert all(row["dispatch_granted"] is False for row in values if "denied" not in row)
    for table in ("plans", "registrations"):
        assert admin(core[3], f"SELECT count(*) FROM theheat_batches.{table}") == [(1,)]
    assert call(store, "status", {})["intent_count"] == 1
    winner = next(row for row in values if "denied" not in row)
    assert admin(core[3], "SELECT payload FROM theheat_batches.plans WHERE sha=%s", (winner["plan_sha256"],))[0][0] in (pair[0], other[0])


@pytest.mark.parametrize("stage", ["hold", "plan", "job", "commit"])
def test_each_partial_write_rolls_back(store, core, inputs, monkeypatch, stage):
    before = snapshot(core[3])
    names = {"hold": "theheat_spending.intents", "plan": "theheat_batches.plans", "job": "theheat_batches.registrations"}
    def after(query, c):
        if stage != "commit" and query.startswith("INSERT INTO " + names[stage]):
            raise RuntimeError("synthetic partial registration")
    def commit(c):
        if stage == "commit":
            raise RuntimeError("synthetic partial registration")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=after, before_commit=commit)
        with pytest.raises(RuntimeError, match="synthetic partial registration"):
            register(store, packet(inputs))
    assert snapshot(core[3]) == before
    assert not register(store, packet(inputs))["reused"]


def test_connection_death_and_lost_commit_ack_preserve_exact_identity(store, core, inputs, monkeypatch):
    pair = packet(inputs)
    before = snapshot(core[3])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            register(store, pair)
    assert snapshot(core[3]) == before
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            register(store, pair)
    after = snapshot(core[3])
    reopened = PostgresCommandAuthority(**options(core[3]))
    result = register(reopened, pair)
    assert result["reused"] and not result["dispatch_granted"]
    assert snapshot(core[3]) == after


def test_failed_registration_does_not_release_preexisting_hold(store, core, inputs, monkeypatch):
    pair = packet(inputs)
    call(store, "reserve", pair[1])
    before = snapshot(core[3])
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_batches.registrations"):
            raise RuntimeError("synthetic insert error")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic insert"):
            register(store, pair)
    assert snapshot(core[3]) == before


def test_capacity_blocks_new_job_but_not_exact_readback(store, core, inputs, monkeypatch):
    register(store, packet(inputs))
    monkeypatch.setattr(b, "MAX_JOBS", 1)
    before = snapshot(core[3])
    assert register(store, packet(inputs))["reused"]
    with pytest.raises(b.BatchJournalError, match="capacity"):
        register(store, packet(inputs, job="second", identity="second"))
    assert snapshot(core[3]) == before


def test_explicit_install_needs_core_spending_and_owner(core, inputs, monkeypatch):
    store, initial, owner, params = core
    before = counts(params), table_counts(params), store.read()
    with pytest.raises(SpendError, match="spend_migration_required"):
        owner.initialize_batches()
    assert admin(params, "SELECT to_regnamespace('theheat_batches')") == [(None,)]
    owner.initialize_spending()
    with pytest.raises(b.BatchJournalError, match="batch_migration_required"):
        register(store, packet(inputs))
    with pytest.raises(b.BatchJournalError, match="batch_migration_required"):
        store.batch_status(inputs["job_id"])
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        store.initialize_batches()
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_batches.metadata"):
            raise RuntimeError("synthetic migration failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic migration"):
            owner.initialize_batches()
    assert admin(params, "SELECT to_regnamespace('theheat_batches')") == [(None,)]
    owner.initialize_batches()
    with pytest.raises(SpendError, match="not_configured"):
        register(store, packet(inputs))
    call(store, "configure", LIMITS)
    owner.initialize_batches()
    owner.initialize_spending()
    owner.initialize(initial, runtime_role="projection_runtime")
    assert (counts(params), table_counts(params), store.read()) == before
    register(store, packet(inputs))
    snap = snapshot(params)
    owner.initialize_batches()
    assert snapshot(params) == snap


def test_owner_defaults_removed_and_sql_guards_restrict_runtime(spend_store, core, inputs):
    import psycopg
    _, _, owner, params = core
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    owner.initialize_batches()
    register(spend_store, packet(inputs))
    assert admin(params, "SELECT has_schema_privilege('projection_runtime','theheat_batches','CREATE'),has_table_privilege('projection_runtime','theheat_batches.metadata','INSERT'),has_table_privilege('projection_runtime','theheat_batches.plans','UPDATE,DELETE,TRUNCATE'),has_function_privilege('projection_runtime','theheat_batches.refuse_mutation()','EXECUTE')") == [(False, False, False, False)]
    for statement in ("UPDATE theheat_batches.plans SET byte_count=byte_count", "DELETE FROM theheat_batches.registrations",
                      "TRUNCATE theheat_batches.plans CASCADE", "UPDATE theheat_batches.metadata SET version=version"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin({**params, "user": "projection_runtime"}, statement)
        with pytest.raises(psycopg.errors.RaiseException, match="immutable batch registration"):
            admin(params, statement)


@pytest.mark.parametrize("sql", [
    "ALTER TABLE theheat_batches.plans DISABLE TRIGGER plans_immutable",
    "ALTER TABLE theheat_batches.registrations ADD COLUMN unexpected integer",
    "GRANT UPDATE(payload) ON theheat_batches.plans TO projection_runtime",
    "GRANT EXECUTE ON FUNCTION theheat_batches.refuse_mutation() TO PUBLIC",
])
def test_schema_or_grant_drift_fails_closed(store, core, inputs, sql):
    register(store, packet(inputs))
    admin(core[3], sql)
    for operation in (lambda: register(store, packet(inputs)), lambda: store.batch_status(inputs["job_id"])):
        with pytest.raises(b.BatchJournalError, match="changed_batch_schema"):
            operation()


def test_hash_length_foreign_keys_and_unique_bindings(store, core, inputs):
    import psycopg
    pair = packet(inputs)
    params = core[3]
    for raw, expected, size in ((pair[0], "a" * 64, len(pair[0])), (pair[0], digest(pair[0]), 2),
                                 (b"x" * 2_000_001, digest(b"x" * 2_000_001), 2_000_001)):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(params, "INSERT INTO theheat_batches.plans VALUES(%s,%s,%s)", (expected, raw, size))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(params, "INSERT INTO theheat_batches.registrations VALUES('absent',%s,'absent',%s)", ("a" * 64, spending._time(NOW)))
    register(store, pair)
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(params, "INSERT INTO theheat_batches.registrations VALUES('different',%s,'attempt-1',%s)", (digest(pair[0]), spending._time(NOW)))


@pytest.mark.parametrize("corruption,code", [
    ("DELETE FROM theheat_batches.plans", "missing_or_invalid_batch_plan"),
    ("DELETE FROM theheat_spending.intents", "changed_batch_binding"),
    ("UPDATE theheat_batches.registrations SET registered_at='2026-09-30T11:00:00.000000Z'", "invalid_batch_registration_time"),
])
def test_missing_or_changed_join_is_not_a_receipt(store, core, inputs, corruption, code):
    register(store, packet(inputs))
    # An explicit owner bypass models missing retained rows. Normal runtime cannot
    # do this; validate that readback still refuses rather than inventing success.
    admin(core[3], "SET session_replication_role=replica; " + corruption)
    with pytest.raises(b.BatchJournalError, match=code):
        store.batch_status(inputs["job_id"])


def test_changed_join_to_other_valid_hold_refuses(store, core, inputs):
    register(store, packet(inputs))
    other = packet(inputs, job="other", identity="other", amount=10)[1]
    call(store, "reserve", other)
    admin(core[3], "SET session_replication_role=replica; UPDATE theheat_batches.registrations SET intent_id='other'")
    with pytest.raises(b.BatchJournalError, match="binding_mismatch"):
        store.batch_status(inputs["job_id"])


@pytest.mark.parametrize("malformed", [True, False])
def test_valid_storage_digest_does_not_bypass_plan_or_job_checks(store, core, inputs, malformed):
    register(store, packet(inputs))
    raw = b"{}" if malformed else packet(inputs, job="wrong-job")[0]
    admin(core[3], "INSERT INTO theheat_batches.plans VALUES(%s,%s,%s)", (digest(raw), raw, len(raw)))
    import psycopg
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute("UPDATE theheat_batches.registrations SET plan_sha=%s", (digest(raw),))
    with pytest.raises(BatchContractError if malformed else b.BatchJournalError,
                       match="invalid_or_changed_batch_plan" if malformed else "changed_batch_binding"):
        store.batch_status(inputs["job_id"])


@pytest.mark.parametrize("column,value,code", [
    ("version", 2, "unsupported_batch_schema"),
    ("environment", "preview", "batch_environment_mismatch"),
    ("runtime_role", "other", "batch_role_mismatch"),
])
def test_metadata_mismatch_is_not_accepted(store, core, inputs, column, value, code):
    import psycopg
    register(store, packet(inputs))
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(psycopg.sql.SQL("UPDATE theheat_batches.metadata SET {}=%s").format(psycopg.sql.Identifier(column)), (value,))
    with pytest.raises(b.BatchJournalError, match=code):
        store.batch_status(inputs["job_id"])


def test_wrong_environment_and_absent_status(store, core, inputs):
    wrong = PostgresCommandAuthority(**options(core[3]), environment="preview")
    with pytest.raises(p.ProjectionError, match="environment_mismatch"):
        register(wrong, packet(inputs))
    with pytest.raises(b.BatchJournalError, match="batch_job_not_found"):
        store.batch_status("absent")


def test_no_provider_or_state_read_and_detached_reservation(store, core, inputs, monkeypatch):
    import httpx
    import httpx2
    import requests
    from src.two_bot import writer
    pair = packet(inputs)
    original = deepcopy(pair[1])
    def observe(query, c):
        if query.startswith("SELECT plan_sha,intent_id FROM theheat_batches.registrations"):
            pair[1]["reserve_micro_usd"] = 99
    with monkeypatch.context() as patch:
        def no_network(*a, **kw):
            pytest.fail("batch registration attempted HTTP")
        patch.setattr(httpx.Client, "send", no_network)
        patch.setattr(httpx2.Client, "send", no_network)
        patch.setattr(requests.Session, "request", no_network)
        patch.setattr(writer, "anthropic_writer_request", lambda *a: pytest.fail("rebuilt writer request"))
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("loaded draft projection"))
        wrap_connections(patch, after_execute=observe)
        result = register(store, pair)
    assert not result["dispatch_granted"]
    assert call(store, "status")["intent"]["intent"] == original


def test_initialize_does_not_import_writer_contract(make_authority, monkeypatch):
    # Guard the lazy explicit-batch boundary without modifying runtime imports.
    _, owner, _ = make_authority
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "src.two_bot.batch_contract", None)
        owner.initialize({}, runtime_role="projection_runtime")
        owner.initialize_spending()
        owner.initialize_batches()


def test_backup_restore_all_four_schemas(store, core, cluster, inputs):
    import psycopg
    params = core[3]
    pair = packet(inputs)
    register(store, pair)
    call(store, "dispatch")
    call(store, "uncertain")
    args, run, root = cluster
    dump = root / "batch-registration.dump"
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    run("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    name = "restore_" + uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, dump)
        target = {**params, "dbname": name}
        restored = PostgresCommandAuthority(**options(target))
        assert snapshot(target) == snapshot(params)
        before = snapshot(target)
        row = register(restored, pair, at=LATER)
        assert row["reused"] and row["reservation_state"] == "uncertain" and not row["dispatch_granted"]
        assert admin(target, "SELECT payload FROM theheat_batches.plans") == [(pair[0],)]
        assert restored.read() == store.read()
        assert snapshot(target) == before
        assert not call(restored, "dispatch")["dispatch_granted"]
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
