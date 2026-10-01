"""Real PostgreSQL fenced workers, crash recovery and bounded ACK evidence."""
import multiprocessing
from contextlib import closing
from uuid import uuid4

import pytest

from src.commands import batch_journal as b, batch_worker_journal as w
from src.commands import postgres_batch_worker as pg, postgres_spending as spend
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.spend_journal import SpendError
from src.commands.sqlite_authority import SQLiteAuthority
from src.storage import postgres_projection as p
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import make_authority as make_authority, core as core
from tests.test_postgres_command_authority import options, table_counts
from tests.test_postgres_batch import spend_store as spend_store
from tests import test_postgres_batch as batches
from tests.test_batch_worker_journal import NOW, later, call, ready, acquire, begin, ack, observe, adopt, dispatch
from tests.test_batch_journal import packet, register, digest
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.two_bot.test_batch_contract import context
from tests.test_spend_journal import LIMITS


@pytest.fixture
def store(spend_store, core):
    core[2].initialize_batches()
    core[2].initialize_batch_workers()
    return spend_store


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    import httpx
    import httpx2
    import requests
    def refuse(*args, **kwargs):
        pytest.fail("worker authority attempted HTTP")
    monkeypatch.setattr(httpx.Client, "send", refuse)
    monkeypatch.setattr(httpx2.Client, "send", refuse)
    monkeypatch.setattr(requests.Session, "request", refuse)


def snapshot(params):
    return batches.snapshot(params) | {
        (pg.SCHEMA, table): admin(params, f"SELECT * FROM {pg.SCHEMA}.{table} ORDER BY 1,2")
        for table in ("metadata", *pg._COLUMNS, "ack_artifacts")}


def spend_call(store, action, payload, at=NOW):
    return store.spending(action, payload, now=at)


def raw_bytes(params, raw):
    return admin(params, "SELECT payload FROM theheat_batch_work.ack_artifacts WHERE sha=%s", (digest(raw),))[0][0]


def test_complete_reports_match_sqlite_and_core_stays_unchanged(store, core, inputs, tmp_path, monkeypatch):
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(core[1])
    spend_call(sqlite, "configure", LIMITS)
    pair = packet(inputs)
    before = counts(core[3]), table_counts(core[3]), store.read(), store.journal()
    for target in (store, sqlite):
        register(target, pair)
    def compare(operation):
        left, right = operation(store), operation(sqlite)
        assert left == right
        assert not left["publication_approved"] and not left["collection_granted"]
        return left
    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("loaded draft projection"))
        compare(lambda s: call(s, "status"))
        compare(lambda s: acquire(s, ttl=60))
        compare(lambda s: acquire(s, ttl=300, at=later(1)))  # no renewal
        grant = compare(lambda s: begin(s, pair, at=later(1)))
        assert grant["dispatch_granted"]
        assert not compare(lambda s: begin(s, pair, at=later(1)))["dispatch_granted"]
        compare(lambda s: acquire(s, owner="next", at=later(60)))
        compare(lambda s: observe(s, grant, b"", at=later(61)))
        compare(lambda s: observe(s, grant, at=later(61)))
        compare(lambda s: adopt(s, owner="next", fence=2, at=later(62)))
        compare(lambda s: adopt(s, owner="next", fence=2, at=later(62)))
        compare(lambda s: observe(s, grant, ack("msgbatch_conflicting"), at=later(63)))
        row = compare(lambda s: call(s, "status", at=later(64)))
        assert row["state"] == "acknowledgment_conflict" and row["provider_batch_id"] is None
    assert (counts(core[3]), table_counts(core[3]), store.read(), store.journal()) == before
    assert spend_call(store, "status", {}, later(64)) == spend_call(sqlite, "status", {}, later(64))
    assert raw_bytes(core[3], b"") == b""
    # Result-review identity binds the ordered ACK inventory in the existing
    # contract. Preserve that order as well as the public disposition report.
    with store.projections._connection() as c, closing(sqlite._connect()) as old:
        assert pg._receipts(c, "job-fixture", 1) == [dict(r) for r in w._receipts(old, "job-fixture", 1)]
    core[2].initialize(core[1], runtime_role="projection_runtime")
    core[2].initialize_spending()
    core[2].initialize_batches()
    retained = snapshot(core[3])
    core[2].initialize_batch_workers()
    assert snapshot(core[3]) == retained


@pytest.mark.parametrize("ttl", [0, -1, 301, True, 1.2, None, "60"])
def test_ttl_is_explicit_integer(store, core, inputs, ttl):
    ready(store, inputs)
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="lease_ttl"):
        acquire(store, ttl=ttl)
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("fence", [0, -1, True, 1.0, "1"])
def test_fence_is_not_coerced(store, core, inputs, fence):
    pair = ready(store, inputs)
    acquire(store)
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="worker_fence"):
        begin(store, pair, fence=fence)
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("field", sorted(w._CONTEXT))
def test_all_current_context_fields_bind_before_dispatch(store, core, inputs, field):
    pair = ready(store, inputs)
    acquire(store)
    current = context(pair[0])
    current[field] = "changed" if field == "publication_epoch" else "f" * 64
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="changed_batch_context"):
        call(store, "begin", owner="worker-one", fence=1, current_context=current)
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("seconds", [23 * 3600, 24 * 3600, 25 * 3600])
def test_minimum_useful_window_equality_and_expiry_block_send(store, core, inputs, seconds):
    pair = ready(store, inputs)
    acquire(store, at=later(seconds))
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="outside_window"):
        begin(store, pair, at=later(seconds))
    assert snapshot(core[3]) == before


def test_expiry_equality_stale_owner_and_unchanged_reuse(store, core, inputs):
    pair = ready(store, inputs)
    initial = acquire(store, ttl=60)
    assert acquire(store, at=later(1))["lease"] == initial["lease"]
    with pytest.raises(w.BatchWorkerError, match="busy"):
        acquire(store, owner="second", at=later(1))
    with pytest.raises(w.BatchWorkerError, match="expired"):
        begin(store, pair, at=later(60))
    assert acquire(store, owner="second", at=later(60))["lease"]["fence"] == 2
    with pytest.raises(w.BatchWorkerError, match="stale"):
        begin(store, pair, at=later(60))
    assert begin(store, pair, owner="second", fence=2, at=later(60))["dispatch_granted"]


@pytest.mark.parametrize("external", ["dispatched", "released", "uncertain", "settled"])
def test_external_spending_cannot_become_a_batch_grant(store, core, inputs, external):
    pair = ready(store, inputs)
    identity = {"intent_id": pair[1]["intent_id"]}
    if external != "released":
        spend_call(store, "dispatch", identity)
    if external in ("released", "uncertain"):
        spend_call(store, "release" if external == "released" else "uncertain", identity)
    if external == "settled":
        spend_call(store, "settle", {**identity, "amount_micro_usd": 50, "evidence_sha256": "a" * 64})
    assert acquire(store)["state"] == "reservation_" + external
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="reservation_not_available"):
        begin(store, pair)
    assert snapshot(core[3]) == before


def test_unknown_hold_survives_restart_and_calendar_without_regrant(store, core, inputs):
    pair, grant = dispatch(store, inputs)
    reopened = PostgresCommandAuthority(**options(core[3]))
    row = acquire(reopened, owner="second", at=later(300))
    assert row["state"] == "submission_uncertain" and row["reservation_state"] == "uncertain"
    assert not begin(reopened, pair, owner="second", fence=2, at=later(300))["dispatch_granted"]
    row = observe(reopened, grant, at=later(301))
    assert row["provider_batch_id"] is None and row["state"] == "submission_uncertain"
    with pytest.raises(w.BatchWorkerError, match="stale"):
        adopt(reopened, at=later(301))
    assert adopt(reopened, owner="second", fence=2, at=later(301))["state"] == "submitted"
    assert spend_call(reopened, "status", {}, "2027-01-01T00:00:00Z")["totals"]["held_micro_usd"] == 60
    before = snapshot(core[3])
    assert call(reopened, "status", at="2027-01-01T00:00:00Z")["state"] == "submitted"
    assert snapshot(core[3]) == before


def test_uncertainty_is_idempotent_and_requires_unadopted_submission(store, core, inputs):
    pair = ready(store, inputs)
    acquire(store)
    with pytest.raises(w.BatchWorkerError, match="not_submitted"):
        call(store, "uncertain", owner="worker-one", fence=1)
    grant = begin(store, pair)
    first = call(store, "uncertain", owner="worker-one", fence=1)
    before = snapshot(core[3])
    assert call(store, "uncertain", owner="worker-one", fence=1) == first
    assert snapshot(core[3]) == before
    observe(store, grant)
    adopt(store)
    with pytest.raises(w.BatchWorkerError, match="already_adopted"):
        call(store, "uncertain", owner="worker-one", fence=1)


@pytest.mark.parametrize("raw", [b"", b"{", b"\xff", b"null", b'{"id":"x","id":"y"}',
    ack(type="other"), ack("https://untrusted.invalid"), ack(processing_status="complete"),
    ack(request_counts={}), ack(request_counts=dict(processing=True, succeeded=0, errored=0, canceled=0, expired=0)),
    ack(request_counts=dict(processing=2, succeeded=0, errored=0, canceled=0, expired=0)),
    ack(processing_status="ended"), ack(extra=float("nan")), b"x" * 65536],
    ids=["empty", "broken", "utf8", "null", "duplicate", "type", "id", "status", "counts", "bool", "sample-count", "ended", "nan", "max-bytes"])
def test_invalid_evidence_is_retained_exactly_but_never_adopted(store, core, inputs, raw):
    _, grant = dispatch(store, inputs)
    row = observe(store, grant, raw)
    assert row["invalid_receipt_count"] == 1 and row["provider_batch_id"] is None
    assert raw_bytes(core[3], raw) == raw
    before = snapshot(core[3])
    assert observe(store, grant, raw)["reused"]
    with pytest.raises(w.BatchWorkerError, match="invalid_or_missing"):
        adopt(store, raw)
    assert snapshot(core[3]) == before


def test_raw_is_inserted_before_parser(store, core, inputs, monkeypatch):
    _, grant = dispatch(store, inputs)
    parsed = w._ack_id
    state = {"inserted": False}
    def after(query, c):
        if query.startswith("INSERT INTO theheat_batch_work.ack_artifacts"):
            state["inserted"] = True
    def parse(raw, samples):
        assert state["inserted"]
        return parsed(raw, samples)
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=after)
        patch.setattr(w, "_ack_id", parse)
        observe(store, grant)


@pytest.mark.parametrize("change", ["grant", "sha", "oversize", "nonbytes"])
def test_invalid_ack_envelope_does_not_write(store, core, inputs, change):
    _, grant = dispatch(store, inputs)
    raw = b"x" * 65537 if change == "oversize" else ack()
    data = {"grant_id": "f" * 64 if change == "grant" else grant["grant_id"],
            "receipt_sha256": "f" * 64 if change == "sha" else digest(raw)}
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError):
        call(store, "observe_ack", raw="text" if change == "nonbytes" else raw, **data)
    assert snapshot(core[3]) == before


def test_cross_job_conflict_hides_both_ids_even_after_adoption(store, inputs):
    pairs = [ready(store, inputs, job=job, identity=job, amount=30) for job in ("one", "two")]
    for pair in pairs:
        job = pair[1]["job_id"]
        acquire(store, job)
        grant = begin(store, pair)
        observe(store, grant)
        if job == "one":
            assert adopt(store, job=job)["state"] == "submitted"
    for job in ("one", "two"):
        row = call(store, "status", job)
        assert row["state"] == "acknowledgment_conflict" and row["provider_batch_id"] is None
        with pytest.raises(w.BatchWorkerError, match="conflicting"):
            adopt(store, job=job)


def test_same_id_distinct_receipts_and_adoption_reuse(store, core, inputs):
    _, grant = dispatch(store, inputs)
    observe(store, grant)
    first = adopt(store)
    other = ack(extra="same provider")
    observe(store, grant, other)
    before = snapshot(core[3])
    row = adopt(store, other)
    assert row["reused"] and row["provider_batch_id"] == first["provider_batch_id"]
    assert snapshot(core[3]) == before


def test_capacity_allows_exact_reuse_but_no_new_evidence_or_lease(store, core, inputs, monkeypatch):
    _, grant = dispatch(store, inputs)
    monkeypatch.setattr(w, "MAX_RECEIPTS", 1)
    monkeypatch.setattr(w, "MAX_LEASES", 1)
    observe(store, grant)
    before = snapshot(core[3])
    assert observe(store, grant)["reused"] and acquire(store)["reused"]
    with pytest.raises(w.BatchWorkerError, match="capacity"):
        observe(store, grant, ack("msgbatch_other"))
    with pytest.raises(w.BatchWorkerError, match="capacity"):
        acquire(store, at=later(300))
    assert snapshot(core[3]) == before


def test_worker_clock_is_global_and_status_does_not_advance_it(store, core, inputs):
    ready(store, inputs, job="one", identity="one", amount=30)
    ready(store, inputs, job="two", identity="two", amount=30)
    acquire(store, "one", at=later(30))
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError, match="clock"):
        acquire(store, "two", at=later(29))
    call(store, "status", "two", at=later(900))
    assert snapshot(core[3]) == before
    assert acquire(store, "two", at=later(30))["lease"]["fence"] == 1


def test_clock_before_registration_and_global_spending_clock(store, core, inputs):
    pair = ready(store, inputs)
    with pytest.raises(w.BatchWorkerError, match="before_registration"):
        call(store, "status", at=later(-1))
    acquire(store)
    other = packet(inputs, job="other", identity="other", amount=10)[1]
    spend_call(store, "reserve", other, later(5))
    before = snapshot(core[3])
    with pytest.raises(SpendError, match="clock"):
        begin(store, pair, at=later(4))
    assert snapshot(core[3]) == before


def test_overrun_blocks_preexisting_worker_hold(store, core, inputs):
    pair = ready(store, inputs)
    acquire(store)
    other = packet(inputs, job="other", identity="other", amount=30)[1]
    spend_call(store, "reserve", other)
    spend_call(store, "dispatch", {"intent_id": "other"})
    spend_call(store, "settle", dict(intent_id="other", amount_micro_usd=40, evidence_sha256="a" * 64))
    before = snapshot(core[3])
    with pytest.raises(SpendError, match="overrun"):
        begin(store, pair)
    assert snapshot(core[3]) == before


def process_call(params, action, payload, barrier, results):
    try:
        barrier.wait(timeout=20)
        results.put(PostgresCommandAuthority(**options(params)).batch_work(action, payload, now=NOW))
    except w.BatchWorkerError as exc:
        results.put(dict(denied=str(exc)))
    except BaseException as exc:
        results.put(dict(worker_error=type(exc).__name__))


def parallel(params, action, payloads):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(len(payloads)), ctx.Queue()
    children = [ctx.Process(target=process_call, args=(params, action, body, barrier, results)) for body in payloads]
    try:
        for child in children:
            child.start()
        rows = [results.get(timeout=40) for _ in children]
        for child in children:
            child.join(timeout=15)
            assert child.exitcode == 0
        assert not any("worker_error" in row for row in rows)
        return rows
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        results.close()


def test_independent_workers_compete_for_lease_and_single_grant(store, core, inputs):
    pair = ready(store, inputs)
    rows = parallel(core[3], "acquire", [dict(job_id="job-fixture", owner=o, ttl_seconds=300) for o in ("one", "two")])
    assert sum("denied" in row for row in rows) == 1
    owner = next(row["lease"]["owner"] for row in rows if "lease" in row)
    payload = dict(job_id="job-fixture", owner=owner, fence=1, current_context=context(pair[0]))
    rows = parallel(core[3], "begin", [payload, payload])
    assert sum(row["dispatch_granted"] for row in rows) == 1
    assert spend_call(store, "status", {})["intent_count"] == 1


def pending_operation(store, inputs, action):
    pair = ready(store, inputs)
    if action == "acquire":
        return lambda: acquire(store)
    acquire(store)
    if action == "begin":
        return lambda: begin(store, pair)
    grant = begin(store, pair)
    if action == "uncertain":
        return lambda: call(store, "uncertain", owner="worker-one", fence=1)
    if action == "reacquire":
        return lambda: acquire(store, owner="next", at=later(300))
    if action == "observe_ack":
        return lambda: observe(store, grant)
    observe(store, grant)
    return lambda: adopt(store)


@pytest.mark.parametrize("action,table", [
    ("acquire", "leases"), ("begin", "submissions"), ("uncertain", "uncertainties"),
    ("reacquire", "leases"), ("observe_ack", "ack_artifacts"), ("observe_ack", "acks"), ("adopt", "adoptions"),
    *[(a, "commit") for a in ("acquire", "begin", "uncertain", "reacquire", "observe_ack", "adopt")]])
def test_each_partial_write_and_commit_failure_roll_back_together(store, core, inputs, monkeypatch, action, table):
    operation = pending_operation(store, inputs, action)
    before = snapshot(core[3])
    def after(query, c):
        if query.startswith("INSERT INTO theheat_batch_work." + table):
            raise RuntimeError("synthetic partial worker write")
    def commit(c):
        if table == "commit":
            raise RuntimeError("synthetic partial worker write")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=after, before_commit=commit)
        with pytest.raises(RuntimeError, match="synthetic partial"):
            operation()
    assert snapshot(core[3]) == before
    operation()


@pytest.mark.parametrize("action", ["begin", "reacquire", "observe_ack", "adopt"])
def test_real_connection_death_rolls_back(store, core, inputs, monkeypatch, action):
    operation = pending_operation(store, inputs, action)
    before = snapshot(core[3])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            operation()
    assert snapshot(core[3]) == before


def test_lost_committed_begin_response_never_grants_again(store, core, inputs, monkeypatch):
    pair = ready(store, inputs)
    acquire(store)
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            begin(store, pair)
    reopened = PostgresCommandAuthority(**options(core[3]))
    retained = snapshot(core[3])
    assert not begin(reopened, pair)["dispatch_granted"]
    assert snapshot(core[3]) == retained
    acquire(reopened, owner="next", at=later(300))
    assert not begin(reopened, pair, owner="next", fence=2, at=later(300))["dispatch_granted"]
    assert spend_call(reopened, "status", {}, later(300))["totals"]["held_micro_usd"] == 60


def test_explicit_owner_install_requires_every_prerequisite_and_rolls_back(core, inputs, monkeypatch):
    value, initial, owner, params = core
    before = counts(params), table_counts(params), value.read()
    with pytest.raises(SpendError, match="spend_migration_required"):
        owner.initialize_batch_workers()
    owner.initialize_spending()
    with pytest.raises(b.BatchJournalError, match="batch_migration_required"):
        owner.initialize_batch_workers()
    owner.initialize_batches()
    with pytest.raises(w.BatchWorkerError, match="worker_migration_required"):
        call(value, "status")
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        value.initialize_batch_workers()
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_batch_work.metadata"):
            raise RuntimeError("synthetic migration failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic migration"):
            owner.initialize_batch_workers()
    assert admin(params, "SELECT to_regnamespace('theheat_batch_work')") == [(None,)]
    owner.initialize_batch_workers()
    owner.initialize_batch_workers()
    assert (counts(params), table_counts(params), value.read()) == before
    for table in (*pg._COLUMNS, "ack_artifacts"):
        assert admin(params, f"SELECT COUNT(*) FROM theheat_batch_work.{table}") == [(0,)]
    with pytest.raises(SpendError, match="not_configured"):
        register(value, packet(inputs))


def test_default_privileges_removed_and_immutable_permissions_enforced(spend_store, core, inputs):
    import psycopg
    _, _, owner, params = core
    owner.initialize_batches()
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    owner.initialize_batch_workers()
    dispatch(spend_store, inputs)
    assert admin(params, "SELECT has_schema_privilege('projection_runtime','theheat_batch_work','CREATE'),has_table_privilege('projection_runtime','theheat_batch_work.metadata','INSERT'),has_function_privilege('projection_runtime','theheat_batch_work.refuse_mutation()','EXECUTE')") == [(False, False, False)]
    for table in ("metadata", *pg._COLUMNS, "ack_artifacts"):
        assert admin(params, "SELECT has_table_privilege('projection_runtime',%s,'UPDATE,DELETE,TRUNCATE')", (f"theheat_batch_work.{table}",)) == [(False,)]
        for statement in (f"UPDATE theheat_batch_work.{table} SET " + ("version=version" if table == "metadata" else "byte_count=byte_count" if table == "ack_artifacts" else "recorded_at=recorded_at"),
                          f"DELETE FROM theheat_batch_work.{table}", f"TRUNCATE theheat_batch_work.{table} CASCADE"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin({**params, "user": "projection_runtime"}, statement)
            with pytest.raises(psycopg.errors.RaiseException, match="immutable batch worker"):
                admin(params, statement)
    for statement in ("DROP TABLE theheat_batch_work.adoptions", "ALTER TABLE theheat_batch_work.leases ADD COLUMN bad integer"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            admin({**params, "user": "projection_runtime"}, statement)


@pytest.mark.parametrize("sql", [
    *[f"ALTER TABLE theheat_batch_work.{table} DISABLE TRIGGER {table}_immutable" for table in ("metadata", *pg._COLUMNS, "ack_artifacts")],
    "ALTER TABLE theheat_batch_work.leases ADD COLUMN unexpected integer",
    "GRANT UPDATE(payload) ON theheat_batch_work.ack_artifacts TO projection_runtime",
    "GRANT EXECUTE ON FUNCTION theheat_batch_work.refuse_mutation() TO PUBLIC",
    "DROP INDEX theheat_batch_work.acks_provider_id",
])
def test_schema_or_acl_drift_blocks_reads_and_writes(store, core, inputs, sql):
    ready(store, inputs)
    admin(core[3], sql)
    for operation in (lambda: call(store, "status"), lambda: acquire(store), core[2].initialize_batch_workers):
        with pytest.raises(w.BatchWorkerError, match="changed_worker_schema"):
            operation()


@pytest.mark.parametrize("column,value,code", [
    ("version", 2, "unsupported_worker_schema"), ("migration_sha", "bad", "unsupported_worker_schema"),
    ("environment", "preview", "worker_environment_mismatch"), ("runtime_role", "wrong", "worker_role_mismatch")])
def test_changed_metadata_refuses(store, core, inputs, column, value, code):
    import psycopg
    ready(store, inputs)
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(psycopg.sql.SQL("UPDATE theheat_batch_work.metadata SET {}=%s").format(psycopg.sql.Identifier(column)), (value,))
    with pytest.raises(w.BatchWorkerError, match=code):
        call(store, "status")


@pytest.mark.parametrize("sql,code", [
    ("UPDATE theheat_batch_work.submissions SET grant_id=repeat('f',64)", "changed_batch_grant"),
    ("DELETE FROM theheat_batch_work.leases WHERE fence=1", "changed_batch_lease"),
    ("DELETE FROM theheat_batch_work.submissions", "missing_batch_submission"),
    ("DELETE FROM theheat_batch_work.ack_artifacts", "invalid_ack_artifact_size"),
    ("UPDATE theheat_batch_work.acks SET provider_id='msgbatch_changed'", "changed_ack_binding"),
    ("UPDATE theheat_batch_work.adoptions SET provider_id='msgbatch_changed'", "changed_adoption_binding"),
    ("UPDATE theheat_batch_work.acks SET recorded_at='2026-09-28T00:00:00.000000Z'", "invalid_worker_event_time"),
    ("UPDATE theheat_batch_work.adoptions SET recorded_at='2026-09-29T12:00:00.000000Z'", "changed_adoption_binding"),
])
def test_corrupt_joins_are_not_accepted_after_owner_bypass(store, core, inputs, sql, code):
    _, grant = dispatch(store, inputs)
    acquire(store, owner="next", at=later(300))
    observe(store, grant, at=later(301))
    adopt(store, owner="next", fence=2, at=later(302))
    admin(core[3], "SET session_replication_role=replica; " + sql)
    with pytest.raises(w.BatchWorkerError, match=code):
        call(store, "status", at=later(302))


def test_sql_size_hash_duration_fence_and_foreign_keys(store, core, inputs):
    import psycopg
    ready(store, inputs)
    params = core[3]
    for raw, sha, size in ((b"", "a" * 64, 0), (b"x", digest(b"x"), 0), (b"x" * 65537, digest(b"x" * 65537), 65537)):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(params, "INSERT INTO theheat_batch_work.ack_artifacts VALUES(%s,%s,%s)", (sha, raw, size))
    for fence, duration in ((0, 1), (1001, 1), (1, 0), (1, 301)):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(params, "INSERT INTO theheat_batch_work.leases VALUES('job-fixture',%s,'worker',%s,%s)", (fence, spend._time(later(duration)), spend._time(NOW)))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(params, "INSERT INTO theheat_batch_work.submissions VALUES('job-fixture',1,%s,%s)", ("a" * 64, spend._time(NOW)))
    acquire(store)
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin(params, "INSERT INTO theheat_batch_work.leases VALUES('job-fixture',1,'worker',%s,%s)", (spend._time(later(300)), spend._time(NOW)))


@pytest.mark.parametrize("action,payload,raw", [
    ("other", {"job_id": "job-fixture"}, None),
    ("status", {"job_id": "job-fixture", "extra": True}, None),
    ("status", {"job_id": "job-fixture"}, b""),
    ("acquire", {"job_id": "job-fixture", "owner": "x" * 4096, "ttl_seconds": 30}, None),
    ("begin", {"job_id": "job-fixture", "owner": "worker-one", "fence": 1, "current_context": {}}, None),
])
def test_exact_bounded_payload_contract(store, core, inputs, action, payload, raw):
    ready(store, inputs)
    acquire(store)
    before = snapshot(core[3])
    with pytest.raises(w.BatchWorkerError):
        store.batch_work(action, payload, now=NOW, raw=raw)
    assert snapshot(core[3]) == before


def test_detaches_mutable_context_before_queries_reuse_it(store, core, inputs, monkeypatch):
    pair = ready(store, inputs)
    acquire(store)
    payload = dict(job_id="job-fixture", owner="worker-one", fence=1, current_context=context(pair[0]))
    def mutate(query, c):
        if query.startswith("SELECT MAX(recorded_at) FROM"):
            payload["current_context"]["publication_epoch"] = "changed-after-validation"
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=mutate)
        assert store.batch_work("begin", payload, now=NOW)["dispatch_granted"]
    assert payload["current_context"]["publication_epoch"] == "changed-after-validation"


def test_five_schema_dump_restore_preserves_uncertainty_fences_and_adoption(store, core, inputs, cluster):
    import psycopg
    pair, grant = dispatch(store, inputs)
    acquire(store, owner="next", at=later(300))
    observe(store, grant, b"", at=later(301))
    observe(store, grant, at=later(301))
    adopt(store, owner="next", fence=2, at=later(302))
    # A second job retains an unknown submission without adoption.
    second = packet(inputs, job="unknown", identity="unknown", amount=30)
    register(store, second, at=later(302))
    acquire(store, "unknown", at=later(302))
    begin(store, second, at=later(302))
    call(store, "uncertain", "unknown", owner="worker-one", fence=1, at=later(302))
    expected = [call(store, "status", job, at=later(302)) for job in ("job-fixture", "unknown")]
    before = snapshot(core[3])
    params, run, root = cluster
    dump = root / ("workers-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = {**core[3], "dbname": name}
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        assert [call(restored, "status", job, at=later(302)) for job in ("job-fixture", "unknown")] == expected
        assert snapshot(restored_params) == before
        assert not begin(restored, pair, owner="next", fence=2, at=later(302))["dispatch_granted"]
        assert not begin(restored, second, at=later(302))["dispatch_granted"]
        assert spend_call(restored, "status", {}, later(302))["totals"]["held_micro_usd"] == 90
        assert raw_bytes(restored_params, b"") == b"" and raw_bytes(restored_params, ack()) == ack()
        assert snapshot(restored_params) == before
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
