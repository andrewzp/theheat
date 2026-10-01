"""Real PostgreSQL response retention and crash recovery; no paid transport."""
from copy import deepcopy
import json
import multiprocessing
from uuid import uuid4

import pytest

from src.commands import check_journal as checks, postgres_check_observations as pg
from src.commands import postgres_checks
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from tests import test_postgres_checks as prior, test_check_executor as execution
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_command_authority import options, table_counts
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_worker import no_provider as no_provider, spend_call
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_batch_worker_journal import NOW, digest, later
from tests.test_spend_journal import LIMITS

base_store = prior.store
case = prior.case


@pytest.fixture
def store(base_store, core):
    core[2].initialize_check_executions()
    return base_store


def saved(case, *, at=NOW):
    return case["store"].check_execution("read", {"check_set_id": case["identity"]["check_set_id"]}, now=at)


def snapshot(params):
    return prior.snapshot(params) | {
        (pg.SCHEMA, table): admin(params, f"SELECT * FROM {pg.SCHEMA}.{table} ORDER BY 1,2")
        for table in ("metadata", *pg._ARTIFACTS, "observations")}


def observation(case, started, raw, **changes):
    grant, request, payload = started
    stage = payload["stage"]
    return dict(check_set_id=case["identity"]["check_set_id"], stage=stage,
        grant_id=grant["grant_id"], request_sha256=digest(request), raw_sha256=digest(raw),
        http_status=None if stage == "deterministic" else 200, complete=True,
        reason="local" if stage == "deterministic" else "received", **changes)


def record(case, meta, raw, at=NOW):
    return case["store"].check_execution("observe", meta, raw=raw, now=at)


def response(case, meta):
    return case["store"].read_check_response(meta["check_set_id"], meta["stage"], meta["grant_id"])


def test_exact_sqlite_parity_all_stages_with_prior_state_unchanged(case, core, inputs, tmp_path, monkeypatch):
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(core[1])
    spend_call(sqlite, "configure", LIMITS)
    paired = prior.legacy.case.__wrapped__(sqlite, deepcopy(inputs), monkeypatch)
    assert saved(case) == saved(paired)
    baseline = counts(core[3]), table_counts(core[3]), case["store"].read(), case["store"].journal()
    for stage, raw in zip(checks.STAGES, (b"", b"not JSON", b'{"passed":true,"passed":false}', b'\xff'), strict=True):
        started, other = prior.start(case, stage), prior.start(paired, stage)
        assert started == other
        meta = observation(case, started, raw)
        prior_state = prior.snapshot(core[3])
        assert record(case, meta, raw) == record(paired, meta, raw)
        assert prior.snapshot(core[3]) == prior_state
        assert response(case, meta) == sqlite.read_artifact(meta["raw_sha256"]) == raw
        assert saved(case) == saved(paired)
        assert prior.status(case)["stages"][stage] == "unresolved"
        assert record(case, meta, raw) == record(paired, meta, raw) == dict(reused=True, raw_retained=True, publication_approved=False)
        # Explicit synthetic outcome only: retaining even HTTP200 bytes did not
        # complete the stage. Real interpretation is separately exercised below.
        assert prior.finish(case, started) == prior.finish(paired, other)
    assert prior.status(case) == prior.status(paired)
    assert spend_call(case["store"], "status", {})["totals"]["held_micro_usd"] == 75
    assert (counts(core[3]), table_counts(core[3]), case["store"].read(), case["store"].journal()) == baseline
    retained = snapshot(core[3])
    core[2].initialize_check_executions()
    assert snapshot(core[3]) == retained


def test_invalid_arguments_metadata_and_bytes_never_write(case, core):
    started = prior.start(case)
    raw = b"fixture"
    meta = observation(case, started, raw)
    before = snapshot(core[3])
    variants = [dict(meta, **{key: value}) for key, value in [
        ("check_set_id", "f" * 64), ("stage", "unknown"), ("stage", []),
        ("grant_id", "f" * 64), ("request_sha256", "f" * 64), ("raw_sha256", "f" * 64),
        ("complete", 1), ("complete", False), ("http_status", True), ("http_status", 99),
        ("http_status", 600), ("http_status", 200.0), ("http_status", 200),
        ("reason", "received"), ("reason", []), ("reason", "unknown"),
        ("reason", "x" * 4096), ("grant_id", float("nan")),
    ]]
    variants += [dict(meta, unexpected=True), {k: v for k, v in meta.items() if k != "complete"}]
    for invalid in variants:
        with pytest.raises(ValueError):
            record(case, invalid, raw)
        assert snapshot(core[3]) == before
    for invalid in (None, "fixture", bytearray(raw), b"x" * (pg.MAX_RESPONSE_BYTES + 1)):
        with pytest.raises(ValueError):
            record(case, meta, invalid)
        assert snapshot(core[3]) == before
    for action, payload, data in (("read", {"check_set_id": meta["check_set_id"]}, raw),
                                  ("unknown", meta, raw), ([], meta, None)):
        with pytest.raises(checks.CheckJournalError):
            case["store"].check_execution(action, payload, raw=data, now=NOW)
    with pytest.raises(ValueError):
        saved(case, at="2026-10-01")
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("reason,status,complete", [
    ("received", 200, True), ("received", 500, True),
    ("transport_unavailable", None, False), ("size_exceeded", 200, False),
    ("time_exceeded", 200, False), ("cleanup_failed", 200, False),
])
def test_provider_observations_retain_without_passing_or_settling(case, core, reason, status, complete):
    prior.finish(case, prior.start(case))
    started = prior.start(case, "safety")
    raw = b"" if status is None else b"x" * pg.MAX_RESPONSE_BYTES
    meta = dict(observation(case, started, raw), reason=reason, http_status=status, complete=complete)
    before = prior.snapshot(core[3])
    assert record(case, meta, raw)["raw_retained"] and response(case, meta) == raw
    assert prior.snapshot(core[3]) == before
    assert prior.status(case)["stages"]["safety"] == "unresolved"
    assert spend_call(case["store"], "status", {})["totals"]["held_micro_usd"] == 65
    for changes in ({"reason": "local"}, {"reason": "received", "http_status": None},
                    {"reason": "received", "complete": False}, {"reason": "time_exceeded", "complete": True}):
        with pytest.raises(checks.CheckJournalError):
            record(case, dict(meta, **changes), raw)


def test_clock_edges_historical_read_and_late_owner_evidence(case, core, monkeypatch):
    first = prior.start(case, at=later(5))
    raw = b"evidence"
    meta = observation(case, first, raw)
    before = snapshot(core[3])
    for when in (NOW, later(4)):
        with pytest.raises(checks.CheckJournalError, match="clock"):
            record(case, meta, raw, when)
    assert snapshot(core[3]) == before
    assert record(case, meta, raw, later(5))["raw_retained"]
    prior.finish(case, first, at=later(6))
    with pytest.raises(checks.CheckJournalError, match="check_clock"):
        record(case, meta, raw, later(5))
    second = prior.start(case, "safety", at=later(6))
    meta2 = observation(case, second, raw)
    assert record(case, meta2, raw, later(1000))["raw_retained"]  # Lease expired; evidence still useful.
    original = snapshot(core[3])
    with pytest.raises(checks.CheckJournalError, match="observation_clock"):
        record(case, meta2, raw, later(999))
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    assert saved(case, at=later(-10)) == saved(case, at=later(100000))
    assert response(case, meta2) == raw
    assert snapshot(core[3]) == original
    assert prior.finish(case, second, at=later(1000))["disposition"] == "stale"
    assert not prior.status(case, at=later(1000))["required_checks_completed"]
    assert spend_call(case["store"], "status", {}, at=later(1000))["totals"]["held_micro_usd"] == 65


def test_conflict_cannot_overwrite_and_accessor_is_grant_bound(case, core):
    started = prior.start(case)
    raw = b"first"
    meta = observation(case, started, raw)
    with pytest.raises(checks.CheckJournalError, match="not_found"):
        response(case, meta)
    record(case, meta, raw)
    before = snapshot(core[3])
    for alternate in (b"", b"second"):
        with pytest.raises(checks.CheckJournalError, match="conflicting"):
            record(case, dict(meta, raw_sha256=digest(alternate)), alternate)
    for changes in ({"grant_id": "f" * 64}, {"stage": "safety"}, {"check_set_id": "f" * 64}):
        with pytest.raises(ValueError):
            response(case, dict(meta, **changes))
    assert snapshot(core[3]) == before and response(case, meta) == raw


def test_caller_metadata_detached_before_sql_reuse(case, core, monkeypatch):
    started = prior.start(case)
    raw = b"original"
    meta = observation(case, started, raw)
    original = deepcopy(meta)
    seen = False
    def mutate(query, c):
        nonlocal seen
        if not seen and query.startswith("SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM theheat_check_executions.metadata"):
            seen = True
            meta["reason"] = "caller changed"
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=mutate)
        record(case, meta, raw)
    assert seen and saved(case)["attempts"]["deterministic"]["observation"] == original


def test_every_write_and_precommit_failure_roll_back(case, core, monkeypatch):
    started = prior.start(case)
    raw = b"rollback"
    meta = observation(case, started, raw)
    before, seen = snapshot(core[3]), []
    def trace(query, c):
        if query.startswith("INSERT INTO"):
            seen.append(query)
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=trace, before_commit=lambda c: (_ for _ in ()).throw(RuntimeError("before commit")))
        with pytest.raises(RuntimeError, match="before commit"):
            record(case, meta, raw)
    assert len(seen) == 3 and snapshot(core[3]) == before
    for cutoff in range(1, len(seen) + 1):
        count = 0
        def fail(query, c):
            nonlocal count
            if query.startswith("INSERT INTO"):
                count += 1
                if count == cutoff:
                    raise RuntimeError("after write")
        with monkeypatch.context() as patch:
            wrap_connections(patch, after_execute=fail)
            with pytest.raises(RuntimeError, match="after write"):
                record(case, meta, raw)
        assert snapshot(core[3]) == before
    record(case, meta, raw)


@pytest.mark.parametrize("lost_ack", [False, True])
def test_connection_death_and_lost_ack_fresh_authority_recovery(case, core, monkeypatch, lost_ack):
    prior.finish(case, prior.start(case))
    started = prior.start(case, "safety")
    raw = b"retained or rolled back"
    meta = observation(case, started, raw)
    before = snapshot(core[3])
    with monkeypatch.context() as patch:
        kwargs = {"lost_ack": True} if lost_ack else {"before_commit": lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())")}
        wrap_connections(patch, **kwargs)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            record(case, meta, raw)
    after = snapshot(core[3])
    assert (after == before) is not lost_ack
    case["store"] = PostgresCommandAuthority(**options(core[3]))
    assert record(case, meta, raw)["reused"] is lost_ack
    assert response(case, meta) == raw
    assert not prior.start(case, "safety")[0]["dispatch_granted"]
    assert spend_call(case["store"], "status", {})["totals"]["held_micro_usd"] == 65


def process_observe(params, meta, raw, barrier, output):
    try:
        store = PostgresCommandAuthority(**options(params))
        barrier.wait(timeout=20)
        output.put(store.check_execution("observe", meta, raw=raw, now=NOW))
    except BaseException as exc:
        output.put({"error": type(exc).__name__, "code": str(exc)})


@pytest.mark.parametrize("conflicting", [False, True])
def test_independent_processes_retain_once(case, core, conflicting):
    started = prior.start(case)
    raw = b"first"
    meta = observation(case, started, raw)
    other_raw = b"second" if conflicting else raw
    other = dict(meta, raw_sha256=digest(other_raw))
    ctx = multiprocessing.get_context("spawn")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    children = [ctx.Process(target=process_observe, args=(core[3], m, r, barrier, output)) for m, r in ((meta, raw), (other, other_raw))]
    try:
        for child in children:
            child.start()
        values = [output.get(timeout=60) for _ in children]
        for child in children:
            child.join(timeout=20)
            assert child.exitcode == 0
        assert sum(v.get("reused") is False for v in values) == 1
        if conflicting:
            assert sum(v.get("code") == "conflicting_check_observation" for v in values) == 1
        else:
            assert sum(v.get("reused") is True for v in values) == 1
        assert admin(core[3], f"SELECT count(*) FROM {pg.SCHEMA}.observations") == [(1,)]
        assert response(case, meta) in (raw, other_raw)
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        output.close()


def test_owner_only_atomic_install_prerequisites_and_reinstall(base_store, core, monkeypatch):
    before = prior.snapshot(core[3])
    with pytest.raises(checks.CheckJournalError, match="migration_required"):
        base_store.check_execution("read", {"check_set_id": "a" * 64}, now=NOW)
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        base_store.initialize_check_executions()
    def fail(query, c):
        if query.startswith(f"INSERT INTO {pg.SCHEMA}.metadata"):
            raise RuntimeError("after schema write")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="after schema write"):
            core[2].initialize_check_executions()
    assert admin(core[3], f"SELECT to_regnamespace('{pg.SCHEMA}')") == [(None,)]
    assert prior.snapshot(core[3]) == before
    core[2].initialize_check_executions()
    core[2].initialize_check_executions()
    assert prior.snapshot(core[3]) == before
    admin(core[3], f"DROP SCHEMA {pg.SCHEMA} CASCADE; DROP SCHEMA theheat_checks CASCADE")
    with pytest.raises(checks.CheckJournalError, match="check_migration_required"):
        core[2].initialize_check_executions()
    assert admin(core[3], f"SELECT to_regnamespace('{pg.SCHEMA}')") == [(None,)]


def test_inherited_privileges_cleared_and_immutable_tables(base_store, core, inputs, monkeypatch):
    import psycopg
    params = core[3]
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    core[2].initialize_check_executions()
    case = prior.legacy.case.__wrapped__(base_store, inputs, monkeypatch)
    started = prior.start(case)
    record(case, observation(case, started, b"fixture"), b"fixture")
    assert admin(params, f"SELECT has_schema_privilege('projection_runtime','{pg.SCHEMA}','CREATE'),has_table_privilege('projection_runtime','{pg.SCHEMA}.metadata','INSERT'),has_function_privilege('projection_runtime','{pg.SCHEMA}.refuse_mutation()','EXECUTE')") == [(False, False, False)]
    for table in ("metadata", *pg._ARTIFACTS, "observations"):
        column = "version" if table == "metadata" else "byte_count" if table in pg._ARTIFACTS else "grant_id"
        for sql in (f"UPDATE {pg.SCHEMA}.{table} SET {column}={column}", f"DELETE FROM {pg.SCHEMA}.{table}", f"TRUNCATE {pg.SCHEMA}.{table} CASCADE"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin({**params, "user": "projection_runtime"}, sql)
            with pytest.raises(psycopg.errors.RaiseException, match="immutable check observation"):
                admin(params, sql)
        with pytest.raises(psycopg.errors.UniqueViolation):
            admin(params, f"INSERT INTO {pg.SCHEMA}.{table} SELECT * FROM {pg.SCHEMA}.{table}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": "projection_runtime"}, f"DROP TABLE {pg.SCHEMA}.observations")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(params, f"INSERT INTO {pg.SCHEMA}.observations SELECT repeat('f',64),metadata_sha256,raw_sha256,recorded_at FROM {pg.SCHEMA}.observations")


@pytest.mark.parametrize("sql", [
    *[f"ALTER TABLE {pg.SCHEMA}.{t} DISABLE TRIGGER {t}_immutable" for t in ("metadata", *pg._ARTIFACTS, "observations")],
    f"GRANT UPDATE(payload) ON {pg.SCHEMA}.raw_artifacts TO projection_runtime",
    f"GRANT EXECUTE ON FUNCTION {pg.SCHEMA}.refuse_mutation() TO PUBLIC",
    f"ALTER TABLE {pg.SCHEMA}.observations ADD COLUMN unexpected integer",
])
def test_schema_or_permission_drift_blocks_every_entrypoint(case, core, sql):
    started = prior.start(case)
    meta = observation(case, started, b"original")
    record(case, meta, b"original")
    admin(core[3], sql)
    for operation in (lambda: saved(case), lambda: record(case, meta, b"original"), lambda: response(case, meta), core[2].initialize_check_executions):
        with pytest.raises(checks.CheckJournalError, match="changed_check_execution_schema"):
            operation()


@pytest.mark.parametrize("column,value,code", [
    ("version", 2, "unsupported_check_execution_schema"), ("migration_sha", "bad", "unsupported_check_execution_schema"),
    ("environment", "preview", "check_execution_environment_mismatch"), ("runtime_role", "wrong", "check_execution_role_mismatch"),
])
def test_metadata_drift_refuses_reads(case, core, column, value, code):
    import psycopg
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(psycopg.sql.SQL(f"UPDATE {pg.SCHEMA}.metadata SET {{}}=%s").format(psycopg.sql.Identifier(column)), (value,))
    with pytest.raises(checks.CheckJournalError, match=code):
        saved(case)


@pytest.mark.parametrize("table", list(pg._ARTIFACTS))
def test_database_bounds_hash_length_and_preflight(case, core, monkeypatch, table):
    import psycopg
    low, high = pg._ARTIFACTS[table]
    values = [(b"x", "f" * 64, 1), (b"x", digest(b"x"), 0), (b"x" * (high + 1), None, high + 1)]
    if low:
        values.append((b"", digest(b""), 0))
    for raw, sha, count in values:
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(core[3], f"INSERT INTO {pg.SCHEMA}.{table} VALUES(%s,%s,%s)", (sha or digest(raw), raw, count))
    started = prior.start(case)
    meta = observation(case, started, b"original")
    record(case, meta, b"original")
    monkeypatch.setitem(pg._ARTIFACTS, table, (low, 0))
    def check(query, c):
        assert not query.startswith(f"SELECT payload FROM {pg.SCHEMA}.{table}")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=check)
        with pytest.raises(checks.CheckJournalError, match="observation_size"):
            saved(case)


@pytest.mark.parametrize("kind", ["raw-missing", "metadata-missing", "time", "raw-join", "request", "stage", "set", "bool", "canonical"])
def test_corrupt_evidence_and_semantic_joins_refuse_even_with_valid_hash(case, core, kind):
    import psycopg
    started = prior.start(case)
    raw = b"original"
    meta = observation(case, started, raw)
    record(case, meta, raw)
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        if kind.endswith("-missing"):
            table = "raw_artifacts" if kind == "raw-missing" else "metadata_artifacts"
            c.execute(f"DELETE FROM {pg.SCHEMA}.{table}")
        elif kind == "time":
            c.execute(f"UPDATE {pg.SCHEMA}.observations SET recorded_at='2026-09-28T00:00:00.000000Z'")
        elif kind == "raw-join":
            c.execute(f"UPDATE {pg.SCHEMA}.observations SET raw_sha256=repeat('f',64)")
        else:
            changed = deepcopy(meta)
            if kind == "request":
                changed["request_sha256"] = "f" * 64
            elif kind == "stage":
                changed.update(stage="safety", reason="received", http_status=200)
            elif kind == "set":
                changed["check_set_id"] = "f" * 64
            elif kind == "bool":
                changed["complete"] = 1
            encoded = (json.dumps(changed, indent=2) if kind == "canonical" else canonical_json(changed)).encode()
            c.execute(f"INSERT INTO {pg.SCHEMA}.metadata_artifacts VALUES(%s,%s,%s)", (digest(encoded), encoded, len(encoded)))
            c.execute(f"UPDATE {pg.SCHEMA}.observations SET metadata_sha256=%s", (digest(encoded),))
    for operation in (lambda: saved(case), lambda: record(case, meta, raw), lambda: response(case, meta)):
        with pytest.raises(ValueError):
            operation()


def test_eight_schema_backup_restore_exact_bytes_and_unknown_holds(case, core, cluster):
    import psycopg
    for stage in checks.STAGES:
        started = prior.start(case, stage)
        raw = stage.encode()
        record(case, observation(case, started, raw), raw)
        prior.finish(case, started)
    before, read = snapshot(core[3]), saved(case)
    params, run, directory = cluster
    dump = directory / ("observations-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = {**core[3], "dbname": name}
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        paired = dict(case, store=restored)
        assert saved(paired) == read
        for stage, attempt in read["attempts"].items():
            meta = attempt["observation"]
            assert response(paired, meta) == stage.encode()
            assert record(paired, meta, stage.encode())["reused"]
        assert spend_call(restored, "status", {})["totals"]["held_micro_usd"] == 75
        assert not prior.start(paired, "critic")[0]["dispatch_granted"]
        assert restored.read() == case["store"].read()
        owner = PostgresCommandAuthority(**options(restored_params, user="projection_owner"))
        owner.initialize(core[1], runtime_role="projection_runtime")
        for method in ("initialize_spending", "initialize_batches", "initialize_batch_workers", "initialize_batch_results", "initialize_candidate_checks", "initialize_check_executions"):
            getattr(owner, method)()
        assert snapshot(restored_params) == before
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


def execution_case(store, inputs, monkeypatch):
    example = execution.case.__wrapped__(store, inputs, monkeypatch)
    payload = example["payload"]
    example["identity"] = dict(check_set_id=example["identity"], owner=payload["owner"],
        fence=payload["fence"], current_context=payload["current_context"],
        checker_state_sha256=fingerprint(payload["checker_state"]))
    example["policy"] = saved(example)["packet"]["policy"]
    return example


def prepared_start(case, stage):
    from src.two_bot import check_requests
    raw = canonical_json(check_requests.prepare_request(saved(case)["packet"], stage)).encode()
    reservation = None if stage == "deterministic" else dict(intent_id="check-" + stage,
        job_id=case["payload"]["job_id"], request_sha256=digest(raw), provider="google", role=stage,
        model=case["policy"]["models"][stage], estimate_sha256="d" * 64, reserve_micro_usd=5)
    payload = dict(case["identity"], stage=stage, reservation=reservation)
    grant = case["store"].candidate_checks("begin", payload, request=raw, now=NOW)
    return grant, raw, payload


def interpret_retained(case, stage):
    """Offline rehearsal of a future adapter; never activates the executor."""
    from src.two_bot import check_requests
    store = case["store"]
    view = saved(case)
    attempt, packet = view["attempts"][stage], view["packet"]
    expected = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    # Recovery must verify exact original request bytes before using a parser.
    # The future production adapter still needs a dedicated request accessor.
    with store.projections._connection() as c:
        store._validate(c)
        store._pointer(c, lock=True)
        original = postgres_checks._raw(c, "request_artifacts", attempt["binding"]["request_sha256"])
    if digest(expected) != attempt["binding"]["request_sha256"] or original != expected:
        raise ValueError("retained_request_not_this_executor")
    raw = response(case, attempt["observation"])
    return check_requests.interpret_observation(packet, stage, attempt["observation"], raw)


def test_real_request_interpretation_recovery_and_explicit_completion(store, core, inputs, monkeypatch):
    from src.two_bot import check_requests
    case = execution_case(store, inputs, monkeypatch)
    before = store.read()
    raws = {
        "deterministic": canonical_json(check_requests.deterministic_result(saved(case)["packet"])).encode(),
        "safety": execution.envelope("NO"),
        "fact_check": execution.envelope(execution.FACT_PASS),
        "critic": execution.envelope(execution.CRITIC_PASS),
    }
    for stage in checks.STAGES:
        started = prepared_start(case, stage)
        meta = observation(case, started, raws[stage])
        record(case, meta, raws[stage])
        case["store"] = PostgresCommandAuthority(**options(core[3]))
        result = interpret_retained(case, stage)
        assert result["execution_status"] == "completed" and result["verdict"] == "pass"
        assert prior.status(case)["stages"][stage] == "unresolved"
        grant, request, _ = started
        receipt = dict(result, grant_id=grant["grant_id"], request_sha256=digest(request))
        case["store"].candidate_checks("complete", dict(case["identity"], stage=stage, grant_id=grant["grant_id"]), receipt=receipt, now=NOW)
        assert not prepared_start(case, stage)[0]["dispatch_granted"]
    assert prior.status(case)["required_checks_completed"] and not prior.status(case)["publication_approved"]
    assert not prior.status(case)["accounting_complete"] and prior.status(case)["cost_usd"] is None
    assert spend_call(store, "status", {})["totals"]["held_micro_usd"] == 75
    assert store.read() == before


@pytest.mark.parametrize("kind", ["empty", "invalid", "duplicate", "truncated", "blocked", "tool", "thought", "multiple", "http-error"])
def test_invalid_retained_provider_envelopes_never_pass(store, core, inputs, monkeypatch, kind):
    case = execution_case(store, inputs, monkeypatch)
    prior.finish(case, prepared_start(case, "deterministic"))  # Explicit offline precursor result.
    started = prepared_start(case, "safety")
    data = json.loads(execution.envelope("NO"))
    if kind == "truncated":
        data["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif kind == "blocked":
        data["promptFeedback"] = {"blockReason": "SAFETY"}
    elif kind == "tool":
        data["candidates"][0]["content"]["parts"] = [{"functionCall": {"name": "bypass"}}]
    elif kind == "thought":
        data["candidates"][0]["content"]["parts"][0]["thought"] = True
    elif kind == "multiple":
        data["candidates"] *= 2
    raw = {"empty": b"", "invalid": b"not JSON", "duplicate": b'{"candidates":[],"candidates":[]}'}.get(kind, json.dumps(data).encode())
    meta = dict(observation(case, started, raw), http_status=503 if kind == "http-error" else 200)
    record(case, meta, raw)
    result = interpret_retained(case, "safety")
    assert result["execution_status"] in ("error", "unavailable") and result["verdict"] is None
    assert prior.status(case)["stages"]["safety"] == "unresolved"
    assert spend_call(store, "status", {})["totals"]["held_micro_usd"] == 65
    assert response(case, meta) == raw


def test_retained_response_cannot_be_reinterpreted_under_other_request(case, monkeypatch):
    from src.two_bot import check_requests
    started = prior.start(case)  # Deliberately not the real executor's prepared request.
    raw = b'{"passed":true,"failures":[],"failure_count":0}'
    record(case, observation(case, started, raw), raw)
    monkeypatch.setattr(check_requests, "interpret_observation", lambda *a: pytest.fail("interpreted another request"))
    with pytest.raises(ValueError, match="retained_request_not_this_executor"):
        interpret_retained(case, "deterministic")


def test_old_owner_response_survives_lease_takeover_without_current_pass(case, core):
    from tests.test_batch_worker_journal import acquire
    prior.finish(case, prior.start(case))
    started = prior.start(case, "safety")
    grant = acquire(case["store"], owner="replacement", at=later(301))
    assert grant["lease"]["fence"] == 2
    raw = b"late response from original grant"
    meta = observation(case, started, raw)
    record(case, meta, raw, later(301))
    assert response(case, meta) == raw
    assert prior.finish(case, started, at=later(301))["disposition"] == "stale"
    assert not prior.status(case, at=later(301))["required_checks_completed"]
    assert spend_call(case["store"], "status", {}, at=later(301))["totals"]["held_micro_usd"] == 65
