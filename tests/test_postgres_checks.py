"""Actual PostgreSQL mandatory checks, atomic spending and retained uncertainty."""
from contextlib import closing
from copy import deepcopy
import json
import multiprocessing
from uuid import uuid4

import pytest

from src.commands import check_journal as checks, postgres_checks as pg
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.sqlite_authority import SQLiteAuthority
from src.storage import postgres_projection as p
from tests import test_check_journal as legacy, test_postgres_batch_results as results
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_command_authority import table_counts
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_worker import no_provider as no_provider, spend_call
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_batch_worker_journal import NOW, digest, later
from tests.test_spend_journal import LIMITS

# Reuse behavioral assertions; database-specific failure/restore tests below use
# real PostgreSQL operations, never a translated SQLite connection.
from tests.test_check_journal import (
    test_idempotent_intake_and_repeated_reads_do_not_consume_review_capacity,
    test_changed_supplied_inputs_refused_without_mutation,
    test_changed_context_invalidates_completed_checks_and_blocks_more_work,
    test_predecessors_are_required_before_any_paid_dispatch,
    test_nonpass_is_durable_terminal_and_never_unblocks_next_stage,
    test_unknown_grant_and_missing_completion_do_not_pass,
    test_exact_completion_replay_is_idempotent_and_conflict_refused,
    test_malformed_receipts_cannot_complete_a_check,
    test_policy_change_blocks_even_when_caller_replays_old_context,
    test_expired_deadline_and_lease_never_reuse_passed_checks,
    test_late_receipt_retained_but_cannot_pass_or_trigger_repurchase,
    test_result_conflict_invalidates_old_pass_without_discarding_receipts,
    test_reservation_must_match_exact_check_request_and_role,
    test_deadline_equality_blocks_even_with_new_valid_lease,
    test_disabled_required_stage_cannot_be_omitted_from_intake,
    test_invalid_or_unknown_intake_item_never_creates_another_set,
    test_equivalent_result_bytes_reuse_one_exact_candidate,
    test_malformed_complete_receipt_does_not_hide_good_candidate,
    test_paid_allowance_exhaustion_rolls_back_without_consuming_stage,
    test_explicit_resource_bounds,
    test_stale_completion_replay_reports_history_but_cannot_restore_readiness,
    test_changed_request_cannot_take_over_an_existing_grant,
    test_pending_drafts_and_reuse_state_invalidate_existing_checks,
    test_late_completion_with_changed_checker_state_is_retained_as_stale,
    test_utc_rollover_changes_critic_comparison_window_before_usefulness_expiry,
    test_missing_checker_state_never_implies_empty_history,
)

case = legacy.case


@pytest.fixture
def store(worker_store, core):
    core[2].initialize_batch_results()
    core[2].initialize_candidate_checks()
    return worker_store


def snapshot(params):
    return results.snapshot(params) | {
        (pg.SCHEMA, table): admin(params, f"SELECT * FROM {pg.SCHEMA}.{table} ORDER BY 1,2")
        for table in ("metadata", *pg._ARTIFACTS, "sets", "attempts", "receipts")}


def request_for(case, stage):
    request = json.dumps(dict(identity=case["identity"]["check_set_id"], stage=stage)).encode()
    reservation = None if stage == "deterministic" else dict(
        intent_id="check-" + stage, job_id=case["payload"]["job_id"], request_sha256=digest(request),
        provider="google", role=stage, model=case["policy"]["models"][stage],
        estimate_sha256="d" * 64, reserve_micro_usd=5,
    )
    payload = dict(case["identity"], stage=stage, reservation=reservation)
    return request, payload


def start(case, stage="deterministic", *, at=NOW, **changes):
    request, payload = request_for(case, stage)
    payload.update(changes)
    grant = case["store"].candidate_checks("begin", payload, request=request, now=at)
    return grant, request, payload


finish, status, passed = legacy.finish, legacy.status, legacy.passed


@pytest.fixture(autouse=True)
def actual_postgres_helpers(monkeypatch, core):
    # The legacy helper always passes SQLite's before_commit=None. The adapter's
    # public contract has no injection hook; supply identical bytes without it.
    monkeypatch.setattr(legacy, "start", start)
    original = legacy.workers.snapshot
    monkeypatch.setattr(legacy.workers, "snapshot", lambda store:
                        snapshot(core[3]) if isinstance(store, PostgresCommandAuthority) else original(store))


def test_full_sequence_exact_sqlite_receipt_and_artifact_parity(case, core, inputs, tmp_path, monkeypatch):
    store = case["store"]
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(core[1])
    spend_call(sqlite, "configure", LIMITS)
    paired = legacy.case.__wrapped__(sqlite, deepcopy(inputs), monkeypatch)
    assert paired["result"] == case["result"] and paired["identity"] == case["identity"]
    before = counts(core[3]), table_counts(core[3]), store.read(), store.journal()
    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("loaded draft projection"))
        for stage in checks.STAGES:
            assert status(case) == status(paired)
            current, other = start(case, stage), start(paired, stage)
            assert current == other
            assert finish(case, current) == finish(paired, other)
            assert start(case, stage) == start(paired, stage)
        assert status(case) == status(paired)
        assert status(case)["required_checks_completed"] and not status(case)["publication_approved"]
        assert not status(case)["accounting_complete"] and status(case)["cost_usd"] is None
    assert (counts(core[3]), table_counts(core[3]), store.read(), store.journal()) == before
    assert spend_call(store, "status", {}) == spend_call(sqlite, "status", {})
    assert spend_call(store, "status", {})["totals"]["held_micro_usd"] == 75
    with store.projections._connection() as c, closing(sqlite._connect()) as old:
        packet, _ = pg._packet(c, case["identity"]["check_set_id"], "local")
        assert packet == checks._packet(old, case["identity"]["check_set_id"])
        for table in pg._ARTIFACTS:
            for sha, raw in c.execute(f"SELECT sha,payload FROM {pg.SCHEMA}.{table}"):
                assert sqlite.read_artifact(sha) == raw
    retained = snapshot(core[3])
    core[2].initialize(core[1], runtime_role="projection_runtime")
    for method in ("initialize_spending", "initialize_batches", "initialize_batch_workers", "initialize_batch_results", "initialize_candidate_checks"):
        getattr(core[2], method)()
    assert snapshot(core[3]) == retained


@pytest.mark.parametrize("operation", ["intake", "begin", "complete"])
def test_rollback_after_every_write_and_before_commit(store, core, inputs, monkeypatch, operation):
    case = legacy.case.__wrapped__(store, inputs, monkeypatch)
    if operation == "intake":
        # Recreate only the new immutable check schema; keep retained batch data.
        admin(core[3], "DROP SCHEMA theheat_checks CASCADE")
        core[2].initialize_candidate_checks()
        # A fresh result review/choice must also be rolled back with failed intake.
        admin(core[3], "SET session_replication_role=replica; DELETE FROM theheat_batch_results.choices; DELETE FROM theheat_batch_results.reviews; DELETE FROM theheat_batch_results.report_artifacts")
        def run():
            return store.candidate_checks("intake", case["payload"], now=NOW)
    else:
        finish(case, start(case))
        if operation == "begin":
            def run():
                return start(case, "safety")
        else:
            started = start(case, "safety")
            def run():
                return finish(case, started)
    original = snapshot(core[3])
    seen = []
    def trace(query, c):
        if query.startswith("INSERT INTO"):
            seen.append(query)
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=trace,
                         before_commit=lambda c: (_ for _ in ()).throw(RuntimeError("before commit")))
        with pytest.raises(RuntimeError, match="before commit"):
            run()
    assert snapshot(core[3]) == original and seen
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
                run()
        assert snapshot(core[3]) == original
    run()


@pytest.mark.parametrize("action", ["intake", "begin", "complete"])
def test_lost_commit_ack_recovers_without_another_grant(case, core, monkeypatch, action):
    store = case["store"]
    original_state = store.read()
    if action == "intake":
        admin(core[3], "DROP SCHEMA theheat_checks CASCADE")
        core[2].initialize_candidate_checks()
        def run():
            return case["store"].candidate_checks("intake", case["payload"], now=NOW)
    else:
        finish(case, start(case))
        if action == "begin":
            def run():
                return start(case, "safety")[0]
        else:
            started = start(case, "safety")
            def run():
                return finish(case, started)
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            run()
    after = snapshot(core[3])
    case["store"] = PostgresCommandAuthority(**results.options(core[3], "projection_runtime"))
    recovered = run()
    assert not recovered.get("dispatch_granted", False)
    assert snapshot(core[3]) == after
    assert store.read() == original_state


def process_call(params, action, payload, request, barrier, output):
    try:
        from src.voice import safety
        from src.two_bot import writer
        # Spawn starts a fresh interpreter; reproduce the explicit offline
        # fixture settings rather than weakening the current-policy check.
        safety.GEMINI_API_KEY = "offline-fixture-key"
        writer.WRITER_PROVIDER = "anthropic"
        writer.WRITER_MODEL = "claude-synthetic"
        store = PostgresCommandAuthority(**results.options(params))
        barrier.wait(timeout=20)
        output.put(store.candidate_checks(action, payload, request=request, now=NOW))
    except BaseException as exc:
        output.put({"error": type(exc).__name__, "code": str(exc)})


@pytest.mark.parametrize("action", ["intake", "begin"])
def test_independent_processes_obtain_one_intake_or_paid_grant(case, core, action):
    if action == "intake":
        admin(core[3], "DROP SCHEMA theheat_checks CASCADE")
        core[2].initialize_candidate_checks()
        payload, request = case["payload"], None
    else:
        finish(case, start(case))
        request, payload = request_for(case, "safety")
    ctx = multiprocessing.get_context("spawn")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    children = [ctx.Process(target=process_call, args=(core[3], action, payload, request, barrier, output)) for _ in range(2)]
    try:
        for child in children:
            child.start()
        received = [output.get(timeout=60) for child in children]
        for child in children:
            child.join(timeout=20)
            assert child.exitcode == 0
        assert all("error" not in value for value in received), received
        field = "reused" if action == "intake" else "dispatch_granted"
        assert sorted(value[field] for value in received) == [False, True]
        id_field = "check_set_id" if action == "intake" else "grant_id"
        assert received[0][id_field] == received[1][id_field]
        assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets") == [(1,)]
        if action == "begin":
            assert spend_call(case["store"], "status", {})["totals"]["held_micro_usd"] == 65
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        output.close()


@pytest.mark.parametrize("action", ["intake", "begin", "complete"])
def test_actual_connection_death_rolls_back_all_check_and_money_writes(case, core, monkeypatch, action):
    if action == "intake":
        admin(core[3], "DROP SCHEMA theheat_checks CASCADE")
        core[2].initialize_candidate_checks()
        def run():
            return case["store"].candidate_checks("intake", case["payload"], now=NOW)
    else:
        finish(case, start(case))
        if action == "begin":
            def run():
                return start(case, "safety")
        else:
            started = start(case, "safety")
            def run():
                return finish(case, started)
    before = snapshot(core[3])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            run()
    assert snapshot(core[3]) == before
    run()


def test_explicit_owner_only_atomic_install_and_prior_schema_preservation(worker_store, core, inputs, monkeypatch):
    owner, params = core[2:]
    owner.initialize_batch_results()
    before = results.snapshot(params)
    with pytest.raises(checks.CheckJournalError, match="migration_required"):
        worker_store.candidate_checks("status", dict.fromkeys(checks._BASE, "missing"), now=NOW)
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        worker_store.initialize_candidate_checks()
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_checks.metadata"):
            raise RuntimeError("migration failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="migration failure"):
            owner.initialize_candidate_checks()
    assert admin(params, "SELECT to_regnamespace('theheat_checks')") == [(None,)]
    assert results.snapshot(params) == before
    owner.initialize_candidate_checks()
    owner.initialize_candidate_checks()
    assert results.snapshot(params) == before


def test_results_schema_is_required_before_install(worker_store, core):
    with pytest.raises(results.r.BatchResultError, match="migration_required"):
        core[2].initialize_candidate_checks()
    assert admin(core[3], "SELECT to_regnamespace('theheat_checks')") == [(None,)]


def test_inherited_privileges_cleared_and_every_table_immutable(worker_store, core, inputs, monkeypatch):
    import psycopg
    params = core[3]
    core[2].initialize_batch_results()
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    core[2].initialize_candidate_checks()
    case = legacy.case.__wrapped__(worker_store, inputs, monkeypatch)
    passed(case)
    assert admin(params, "SELECT has_schema_privilege('projection_runtime','theheat_checks','CREATE'),has_table_privilege('projection_runtime','theheat_checks.metadata','INSERT'),has_function_privilege('projection_runtime','theheat_checks.refuse_mutation()','EXECUTE')") == [(False, False, False)]
    for table in ("metadata", *pg._ARTIFACTS, "sets", "attempts", "receipts"):
        column = "version" if table == "metadata" else "byte_count" if table in pg._ARTIFACTS else "check_set_id" if table == "sets" else "grant_id"
        for query in (f"UPDATE theheat_checks.{table} SET {column}={column}", f"DELETE FROM theheat_checks.{table}", f"TRUNCATE theheat_checks.{table} CASCADE"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin({**params, "user": "projection_runtime"}, query)
            with pytest.raises(psycopg.errors.RaiseException, match="immutable candidate checks"):
                admin(params, query)
        with pytest.raises(psycopg.errors.UniqueViolation):
            admin(params, f"INSERT INTO theheat_checks.{table} SELECT * FROM theheat_checks.{table}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": "projection_runtime"}, "DROP TABLE theheat_checks.sets")


@pytest.mark.parametrize("sql", [
    *[f"ALTER TABLE theheat_checks.{table} DISABLE TRIGGER {table}_immutable" for table in ("metadata", *pg._ARTIFACTS, "sets", "attempts", "receipts")],
    "GRANT UPDATE(payload) ON theheat_checks.packet_artifacts TO projection_runtime",
    "GRANT EXECUTE ON FUNCTION theheat_checks.refuse_mutation() TO PUBLIC",
    "ALTER TABLE theheat_checks.attempts ADD COLUMN unexpected integer",
])
def test_schema_or_permissions_drift_refuses_reuse_status_and_install(case, core, sql):
    admin(core[3], sql)
    for operation in (lambda: status(case), lambda: start(case), core[2].initialize_candidate_checks):
        with pytest.raises(checks.CheckJournalError, match="changed_check_schema"):
            operation()


@pytest.mark.parametrize("column,value,code", [
    ("version", 2, "unsupported_check_schema"), ("migration_sha", "bad", "unsupported_check_schema"),
    ("environment", "preview", "check_environment_mismatch"), ("runtime_role", "wrong", "check_role_mismatch"),
])
def test_metadata_drift_refuses_operations(case, core, column, value, code):
    import psycopg
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(psycopg.sql.SQL("UPDATE theheat_checks.metadata SET {}=%s").format(psycopg.sql.Identifier(column)), (value,))
    with pytest.raises(checks.CheckJournalError, match=code):
        status(case)


@pytest.mark.parametrize("sql,code", [
    ("UPDATE theheat_checks.sets SET custom_id='wrong'", "changed_check_set"),
    ("UPDATE theheat_checks.sets SET recorded_at='2026-09-28T00:00:00.000000Z'", "invalid_check_set_time"),
    ("DELETE FROM theheat_checks.packet_artifacts", "invalid_check_artifact_size"),
    ("DELETE FROM theheat_checks.request_artifacts", "invalid_check_artifact_size"),
    ("DELETE FROM theheat_checks.binding_artifacts", "invalid_check_artifact_size"),
    ("DELETE FROM theheat_checks.receipt_artifacts", "invalid_check_artifact_size"),
    ("UPDATE theheat_checks.attempts SET request_sha256=repeat('f',64)", "changed_check_attempt"),
    ("UPDATE theheat_checks.attempts SET intent_id=NULL WHERE stage='safety'", "changed_check_attempt"),
    ("UPDATE theheat_checks.attempts SET recorded_at='2026-09-28T00:00:00.000000Z'", "changed_check_attempt"),
    ("UPDATE theheat_checks.receipts SET disposition='error'", "changed_check_receipt"),
    ("UPDATE theheat_checks.receipts SET recorded_at='2026-09-28T00:00:00.000000Z'", "changed_check_receipt"),
    ("DELETE FROM theheat_checks.attempts WHERE stage='deterministic'", "changed_check_stage_order"),
])
def test_corrupt_stored_joins_and_dispositions_fail_closed(case, core, sql, code):
    passed(case)
    admin(core[3], "SET session_replication_role=replica; " + sql)
    with pytest.raises(checks.CheckJournalError, match=code):
        status(case)


@pytest.mark.parametrize("table", list(pg._ARTIFACTS))
def test_database_byte_count_hash_and_bounds(case, core, table):
    import psycopg
    for raw, sha, count in ((b"", digest(b""), 0), (b"x", "f" * 64, 1), (b"x", digest(b"x"), 0),
                            (b"x" * (pg._ARTIFACTS[table] + 1), None, pg._ARTIFACTS[table] + 1)):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(core[3], f"INSERT INTO theheat_checks.{table} VALUES(%s,%s,%s)", (sha or digest(raw), raw, count))


@pytest.mark.parametrize("table", list(pg._ARTIFACTS))
def test_size_preflight_precedes_reading_blob(case, core, monkeypatch, table):
    passed(case)
    monkeypatch.setitem(pg._ARTIFACTS, table, 0)
    def check(query, c):
        assert not query.startswith(f"SELECT payload FROM theheat_checks.{table}")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=check)
        with pytest.raises(checks.CheckJournalError, match="artifact_size"):
            status(case)


def test_capacity_keeps_exact_reuse_and_rolls_back_new_candidate(case, core, inputs, monkeypatch):
    monkeypatch.setattr(checks, "MAX_SETS", 1)
    store = case["store"]
    assert store.candidate_checks("intake", case["payload"], now=NOW)["reused"]
    # Changed checker state changes the immutable packet; it cannot replace a set.
    before = snapshot(core[3])
    changed = dict(case["payload"], checker_state={"different": True})
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_candidate"):
        store.candidate_checks("intake", changed, now=NOW)
    assert snapshot(core[3]) == before
    # Drop only the task's private check schema to exercise admission at zero.
    admin(core[3], "DROP SCHEMA theheat_checks CASCADE")
    core[2].initialize_candidate_checks()
    monkeypatch.setattr(checks, "MAX_SETS", 0)
    before = snapshot(core[3])
    with pytest.raises(checks.CheckJournalError, match="check_set_capacity"):
        store.candidate_checks("intake", case["payload"], now=NOW)
    assert snapshot(core[3]) == before


def test_read_does_not_advance_clock_and_global_write_clock_refuses_backwards(case, core):
    first = start(case, at=later(5))
    before = snapshot(core[3])
    status(case, at=later(500))
    assert snapshot(core[3]) == before
    with pytest.raises(checks.CheckJournalError, match="check_clock_went_backwards"):
        finish(case, first, at=later(4))
    assert snapshot(core[3]) == before
    assert finish(case, first, at=later(5))["disposition"] == "passed"


def test_spending_clock_and_previously_dispatched_intent_cannot_buy_a_check(case, core):
    finish(case, start(case))
    request, payload = request_for(case, "safety")
    store = case["store"]
    store.spending("reserve", payload["reservation"], now=later(5))
    before = snapshot(core[3])
    with pytest.raises(legacy.SpendError, match="clock"):
        start(case, "safety", at=later(4))
    assert snapshot(core[3]) == before
    store.spending("dispatch", {"intent_id": payload["reservation"]["intent_id"]}, now=later(5))
    before = snapshot(core[3])
    with pytest.raises(checks.CheckJournalError, match="check_spend_already_used"):
        start(case, "safety", at=later(5))
    assert snapshot(core[3]) == before and status(case, at=later(5))["stages"]["safety"] == "pending"


@pytest.mark.parametrize("action", ["status", "intake", "begin", "complete", "unknown"])
def test_wrong_action_arguments_do_not_write(case, core, action):
    before = snapshot(core[3])
    payload = case["payload"] if action == "intake" else case["identity"]
    if action == "begin":
        payload = dict(payload, stage="deterministic", reservation=None)
    elif action == "complete":
        payload = dict(payload, stage="deterministic", grant_id="a" * 64)
    with pytest.raises(checks.CheckJournalError):
        case["store"].candidate_checks(action, payload, now=NOW, request=b"invalid-extra", receipt={})
    assert snapshot(core[3]) == before


def test_seven_schema_backup_restore_preserves_exact_passes_and_unknown_holds(case, core, cluster):
    import psycopg
    passed(case)
    before = snapshot(core[3])
    params, run, directory = cluster
    dump = directory / ("checks-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = {**core[3], "dbname": name}
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**results.options(restored_params))
        paired = dict(case, store=restored)
        assert status(paired) == status(case)
        assert not start(paired, "critic")[0]["dispatch_granted"]
        assert spend_call(restored, "status", {})["totals"]["held_micro_usd"] == 75
        assert restored.read() == case["store"].read()
        owner = PostgresCommandAuthority(**results.options(restored_params, user="projection_owner"))
        owner.initialize(core[1], runtime_role="projection_runtime")
        for method in ("initialize_spending", "initialize_batches", "initialize_batch_workers", "initialize_batch_results", "initialize_candidate_checks"):
            getattr(owner, method)()
        assert snapshot(restored_params) == before
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


@pytest.mark.parametrize("action", ["intake", "begin", "complete"])
def test_caller_inputs_detach_before_sql_reuses_them(case, core, monkeypatch, action):
    store = case["store"]
    request = receipt = None
    if action == "intake":
        payload = deepcopy(case["payload"])
        target = payload["checker_state"]
    elif action == "begin":
        finish(case, start(case))
        request, payload = request_for(case, "safety")
        target = payload["reservation"]
    else:
        grant, request_bytes, original = start(case)
        payload = dict(case["identity"], stage="deterministic", grant_id=grant["grant_id"])
        receipt = dict(grant_id=grant["grant_id"], request_sha256=digest(request_bytes),
                       execution_status="completed", verdict="pass", result={"fixture_only": True}, usage=None)
        target = receipt["result"]
    observed = False
    def mutate(query, c):
        nonlocal observed
        if not observed and query.startswith("SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM theheat_checks.metadata"):
            observed = True
            target["caller_mutated_after_detach"] = True
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=mutate)
        outcome = store.candidate_checks(action, payload, now=NOW, request=request, receipt=receipt)
    assert observed
    assert not outcome["publication_approved"]
    if action == "intake":
        assert outcome["reused"]
    for table in pg._ARTIFACTS:
        assert all(b"caller_mutated_after_detach" not in raw for (raw,) in
                   admin(core[3], f"SELECT payload FROM theheat_checks.{table}"))


@pytest.mark.parametrize("layer", ["worker", "result"])
def test_later_worker_or_result_write_blocks_earlier_check_grant(case, core, layer):
    if layer == "worker":
        legacy.workers.observe(case["store"], case["grant"], legacy.workers.ack(extra="later"), at=later(10))
    else:
        legacy.batches.review(case["store"], case["pair"], case["receipt"], at=later(10))
    before = snapshot(core[3])
    with pytest.raises((pg.r.BatchResultError, pg.w.BatchWorkerError), match="clock"):
        start(case, at=later(9))
    assert status(case, at=later(9))["blocked_reason"] == "check_context_not_current"
    assert snapshot(core[3]) == before


def test_recorded_overrun_prevents_paid_stage_without_consuming_it(case, core):
    from tests.test_spend_journal import settle
    finish(case, start(case))
    started = start(case, "safety")
    finish(case, started)
    settle(case["store"], 101, identity="check-safety")
    before = snapshot(core[3])
    with pytest.raises(legacy.SpendError, match="overrun"):
        start(case, "fact_check")
    assert snapshot(core[3]) == before
    assert status(case)["stages"]["fact_check"] == "pending"


@pytest.mark.parametrize("change", [{"owner": "other"}, {"fence": 2}, {"fence": True}])
def test_only_original_owner_and_exact_integer_fence_may_complete(case, core, change):
    grant, request, payload = start(case)
    before = snapshot(core[3])
    with pytest.raises(checks.CheckJournalError, match="owner_mismatch"):
        finish(case, (grant, request, dict(payload, **change)))
    assert snapshot(core[3]) == before
    assert finish(case, (grant, request, payload))["disposition"] == "passed"


@pytest.mark.parametrize("kind", ["packet", "binding", "receipt"])
def test_valid_byte_hash_cannot_hide_changed_semantic_binding(case, core, kind):
    import psycopg
    passed(case)
    table, column, where = {
        "packet": ("sets", "packet_sha256", ""),
        "binding": ("attempts", "binding_sha256", "WHERE stage='deterministic'"),
        "receipt": ("receipts", "receipt_sha256", "WHERE grant_id=(SELECT grant_id FROM theheat_checks.attempts WHERE stage='deterministic')"),
    }[kind]
    sha = admin(core[3], f"SELECT {column} FROM theheat_checks.{table} {where}")[0][0]
    doc = json.loads(admin(core[3], f"SELECT payload FROM theheat_checks.{kind}_artifacts WHERE sha=%s", (sha,))[0][0])
    if kind == "packet":
        # The semantic fingerprint normalizes 1 and 1.0, but policy bytes must
        # still equal the exact retained plan. A storage hash alone is insufficient.
        doc["policy"]["flags"]["writer_samples"] = 1.0
    elif kind == "binding":
        doc["owner"] = "changed-owner"
    else:
        doc["verdict"] = "reject"
    raw = pg.canonical_json(doc).encode()
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(f"INSERT INTO theheat_checks.{kind}_artifacts VALUES(%s,%s,%s)", (digest(raw), raw, len(raw)))
        c.execute(f"UPDATE theheat_checks.{table} SET {column}=%s {where}", (digest(raw),))
    with pytest.raises(checks.CheckJournalError, match="changed_check_"):
        status(case)
