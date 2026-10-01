"""Real PostgreSQL raw-result retention, fenced review and recovery."""
from copy import deepcopy
import json
import multiprocessing
from uuid import uuid4

import pytest

from src.commands import batch_result_journal as r, batch_worker_journal as w
from src.commands import postgres_batch_results as pg, postgres_spending as spend
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.sqlite_authority import SQLiteAuthority
from src.storage import postgres_projection as p
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_command_authority import options, table_counts
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_worker import no_provider as no_provider
from tests import test_postgres_batch_worker as workers
from tests.test_postgres_batch_worker import spend_call
from tests.test_batch_worker_journal import NOW, later, acquire, begin, observe, ack, digest
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.two_bot import test_batch_contract as contract
from tests.test_batch_result_journal import started, metadata, rows, retain, review
from tests.test_spend_journal import LIMITS

# Exercise the unchanged behavioral assertions directly against the new adapter.
from tests.test_batch_result_journal import (
    test_partial_file_followed_by_complete_file_can_recover_without_rebuying,
    test_mixed_terminal_outcomes_preserve_charge_uncertainty,
    test_invalid_writer_content_keeps_reported_usage_without_candidate,
    test_current_context_changes_withhold_stale_text_without_losing_usage,
    test_exact_deadline_withholds_output_even_for_new_current_owner,
    test_late_worker_can_retain_but_only_current_fence_can_review,
    test_conflicting_complete_results_invalidate_review_of_prior_good_receipt,
    test_later_provider_id_conflict_changes_review_revision_and_withholds_prior_text,
    test_unadopted_submission_preserves_result_usage_without_becoming_authoritative,
)

worker_store = workers.store


@pytest.fixture
def store(worker_store, core):
    core[2].initialize_batch_results()
    return worker_store


def snapshot(params):
    return workers.snapshot(params) | {
        (pg.SCHEMA, table): admin(params, f"SELECT * FROM {pg.SCHEMA}.{table} ORDER BY 1,2")
        for table in ("metadata", *pg._ARTIFACTS, "receipts", "choices", "reviews")}


def artifact(params, table, sha):
    return admin(params, f"SELECT payload FROM theheat_batch_results.{table} WHERE sha=%s", (sha,))[0][0]


def ready_result(store, inputs, *, complete=True):
    pair, grant = started(store, inputs)
    raw = contract.raw_rows(rows(pair))
    receipt = retain(store, grant, raw, complete=complete)
    return pair, grant, raw, receipt


def test_complete_report_identity_parity_and_unchanged_core(store, core, inputs, tmp_path, monkeypatch):
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize(core[1])
    spend_call(sqlite, "configure", LIMITS)
    before = counts(core[3]), table_counts(core[3]), store.read(), store.journal()
    pair, grant = started(store, inputs, 3)
    assert started(sqlite, inputs, 3) == (pair, grant)
    values = rows(pair)
    def compare(operation):
        left, right = operation(store), operation(sqlite)
        assert left == right
        return left
    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("loaded draft projection"))
        partial = compare(lambda s: retain(s, grant, contract.raw_rows(values[:2]), meta=metadata(3)))
        assert not compare(lambda s: review(s, pair, partial))["report"]["complete"]
        first = compare(lambda s: retain(s, grant, contract.raw_rows(values), meta=metadata(3), at=later(1)))
        initial = compare(lambda s: review(s, pair, first, at=later(1)))
        reordered = b"\n".join(json.dumps(item, separators=(",", ":")).encode() for item in reversed(values))
        second = compare(lambda s: retain(s, grant, reordered, meta=metadata(3), at=later(2)))
        updated = compare(lambda s: review(s, pair, second, at=later(2)))
        assert updated["semantic_sha256"] == initial["semantic_sha256"]
        assert [x["candidate_id"] for x in updated["report"]["rows"]] == [x["candidate_id"] for x in initial["report"]["rows"]]
        compare(lambda s: s.batch_results_status("job-fixture", now=later(2)))
        saved = artifact(core[3], "report_artifacts", updated["report_sha256"])
        assert saved == sqlite.read_artifact(updated["report_sha256"])
        before_repeat = snapshot(core[3])
        assert compare(lambda s: review(s, pair, second, at=later(2)))["reused"]
        assert snapshot(core[3]) == before_repeat
        for target in (store, sqlite):
            observe(target, grant, ack("msgbatch_conflicting", request_counts=dict(
                processing=3, succeeded=0, errored=0, expired=0, canceled=0)), at=later(3))
        blocked = compare(lambda s: review(s, pair, first, at=later(3)))
        assert all(row["candidate"] is None for row in blocked["report"]["rows"])
        assert not blocked["report"]["required_checks_completed"] and not blocked["publication_approved"]
        assert blocked["report"]["cost_usd"] is None and not blocked["report"]["accounting_complete"]
    assert (counts(core[3]), table_counts(core[3]), store.read(), store.journal()) == before
    assert spend_call(store, "status", {}, later(3)) == spend_call(sqlite, "status", {}, later(3))
    retained = snapshot(core[3])
    core[2].initialize(core[1], runtime_role="projection_runtime")
    core[2].initialize_spending()
    core[2].initialize_batches()
    core[2].initialize_batch_workers()
    core[2].initialize_batch_results()
    assert snapshot(core[3]) == retained


def test_false_completeness_keeps_usage_and_cannot_choose(store, core, inputs):
    pair, _, _, receipt = ready_result(store, inputs, complete=False)
    report = review(store, pair, receipt)["report"]
    assert "incomplete_result_download" in report["context_blocked_reasons"]
    assert report["rows"][0]["candidate"] is None and report["rows"][0]["usage"]
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.choices") == [(0,)]


@pytest.mark.parametrize("meta", [b"", b"{", b"null", metadata(id="msgbatch_wrong"), ack(), metadata(2)])
def test_invalid_or_nonterminal_metadata_retains_usage_without_candidate(store, core, inputs, meta):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)), meta=meta)
    report = review(store, pair, receipt)["report"]
    assert report["context_blocked_reasons"] and report["rows"][0]["candidate"] is None
    assert report["rows"][0]["usage"]["output_tokens"] == 9
    assert artifact(core[3], "metadata_artifacts", digest(meta)) == meta


@pytest.mark.parametrize("kind", ["empty", "malformed", "utf8", "duplicate-key", "null", "unknown-id", "duplicate-id", "missing-id"])
def test_result_protocol_failures_retain_exact_bytes(store, core, inputs, kind):
    pair, grant = started(store, inputs)
    values = rows(pair)
    raw = {"empty": b"", "malformed": b"{", "utf8": b"\xff", "duplicate-key": b'{"custom_id":"x","custom_id":"y"}', "null": b"null"}.get(kind)
    if raw is None:
        if kind == "unknown-id":
            values[0]["custom_id"] = "unknown"
        elif kind == "duplicate-id":
            values += deepcopy(values)
        elif kind == "missing-id":
            values[0].pop("custom_id")
        raw = contract.raw_rows(values)
    receipt = retain(store, grant, raw)
    report = review(store, pair, receipt)["report"]
    assert report["context_blocked_reasons"] and not any(x["eligible_for_checks"] for x in report["rows"])
    assert report["cost_usd"] is None and not report["accounting_complete"]
    assert artifact(core[3], "result_artifacts", digest(raw)) == raw


@pytest.mark.parametrize("change", ["metadata-size", "result-size", "bool", "grant", "meta-sha", "result-sha", "extra", "payload-size"])
def test_invalid_intake_writes_no_orphan_bytes(store, core, inputs, change):
    pair, grant = started(store, inputs)
    meta = b"x" * 65537 if change == "metadata-size" else metadata()
    raw = b"x" * 3_000_001 if change == "result-size" else contract.raw_rows(rows(pair))
    payload = dict(job_id="job-fixture", grant_id=grant["grant_id"], metadata_sha256=digest(meta), results_sha256=digest(raw), complete=True)
    if change == "bool":
        payload["complete"] = 1
    elif change == "grant":
        payload["grant_id"] = "f" * 64
    elif change in ("meta-sha", "result-sha"):
        payload["metadata_sha256" if change == "meta-sha" else "results_sha256"] = "f" * 64
    elif change == "extra":
        payload["unexpected"] = "field"
    elif change == "payload-size":
        payload["job_id"] = "x" * 4096
    before = snapshot(core[3])
    with pytest.raises(r.BatchResultError):
        store.record_batch_results(payload, metadata=meta, results=raw, now=NOW)
    assert snapshot(core[3]) == before


def test_upper_raw_bounds_are_retained_without_parsing_on_intake(store, core, inputs, monkeypatch):
    _, grant = started(store, inputs)
    raw, meta = b"x" * 3_000_000, b"x" * 65536
    with monkeypatch.context() as patch:
        patch.setattr(r, "_decode", lambda *a: pytest.fail("result parsed during intake"))
        receipt = retain(store, grant, raw, meta=meta)
    assert receipt["raw_retained"] and artifact(core[3], "result_artifacts", digest(raw)) == raw
    assert artifact(core[3], "metadata_artifacts", digest(meta)) == meta


def test_current_context_is_detached_before_reuse(store, core, inputs, monkeypatch):
    pair, _, _, receipt = ready_result(store, inputs)
    context = contract.context(pair[0])
    def mutate(query, c):
        if query.startswith("SELECT MAX(recorded_at) FROM (SELECT MAX(recorded_at) AS recorded_at FROM theheat_batch_results"):
            context["publication_epoch"] = "changed-after-validation"
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=mutate)
        result = review(store, pair, receipt, context=context)
    assert result["binding"]["current_context"] == contract.context(pair[0])
    result["binding"]["current_context"]["publication_epoch"] = "mutated-return"
    saved = json.loads(artifact(core[3], "report_artifacts", result["report_sha256"]))
    assert saved["binding"]["current_context"] == contract.context(pair[0])


def test_index_and_evaluation_are_read_only_and_do_not_advance_clock(store, core, inputs):
    pair, grant, raw, receipt = ready_result(store, inputs)
    before = snapshot(core[3])
    payload = dict(job_id="job-fixture", owner="worker-one", fence=1, receipt_id=receipt["receipt_id"], current_context=contract.context(pair[0]))
    with store.projections._connection() as c:
        store._validate(c)
        store._pointer(c, lock=True)
        assert pg.evaluate(c, payload, now=later(20), environment="local")["report"]["rows"][0]["eligible_for_checks"]
    store.batch_results_status("job-fixture", now=later(100))
    assert snapshot(core[3]) == before
    assert retain(store, grant, raw, at=later(1))["reused"]
    review(store, pair, receipt, at=later(2))
    with pytest.raises(r.BatchResultError, match="clock"):
        retain(store, grant, raw, at=later(1))
    with pytest.raises(r.BatchResultError, match="clock"):
        store.batch_results_status("job-fixture", now=later(1))


def test_worker_clock_and_expired_fence_block_review(store, core, inputs):
    pair, grant, raw, receipt = ready_result(store, inputs)
    observe(store, grant, ack(extra="later"), at=later(10))
    with pytest.raises(w.BatchWorkerError, match="clock"):
        review(store, pair, receipt, at=later(9))
    with pytest.raises(w.BatchWorkerError, match="expired"):
        review(store, pair, receipt, at=later(300))
    assert retain(store, grant, raw, at=later(300))["reused"]


def test_receipt_and_review_capacity_keep_exact_retries(store, core, inputs, monkeypatch):
    pair, grant, raw, receipt = ready_result(store, inputs)
    original = review(store, pair, receipt)
    monkeypatch.setattr(r, "MAX_RECEIPTS", 1)
    monkeypatch.setattr(r, "MAX_REVIEWS", 1)
    before = snapshot(core[3])
    assert retain(store, grant, raw)["reused"]
    assert review(store, pair, receipt)["report_sha256"] == original["report_sha256"]
    with pytest.raises(r.BatchResultError, match="capacity"):
        retain(store, grant, raw, complete=False)
    with pytest.raises(r.BatchResultError, match="capacity"):
        review(store, pair, receipt, at=later(1))
    assert snapshot(core[3]) == before


@pytest.mark.parametrize("bound", ["capacity", "size"])
def test_choice_rolls_back_if_report_cannot_be_retained(store, core, inputs, monkeypatch, bound):
    pair, _, _, receipt = ready_result(store, inputs)
    if bound == "capacity":
        monkeypatch.setattr(r, "MAX_REVIEWS", 0)
    else:
        monkeypatch.setattr(pg, "MAX_REPORT_BYTES", 1)
    before = snapshot(core[3])
    with pytest.raises(r.BatchResultError, match="capacity|oversized"):
        review(store, pair, receipt)
    assert snapshot(core[3]) == before


def operation_for(store, inputs, action):
    pair, grant = started(store, inputs)
    raw = contract.raw_rows(rows(pair))
    if action == "record":
        return lambda target=store: retain(target, grant, raw)
    receipt = retain(store, grant, raw)
    return lambda target=store: review(target, pair, receipt)


@pytest.mark.parametrize("action,table", [
    ("record", "metadata_artifacts"), ("record", "result_artifacts"), ("record", "receipts"),
    ("review", "choices"), ("review", "report_artifacts"), ("review", "reviews"),
    ("record", "commit"), ("review", "commit")])
def test_each_partial_write_and_commit_roll_back(store, core, inputs, monkeypatch, action, table):
    operation = operation_for(store, inputs, action)
    before = snapshot(core[3])
    def after(query, c):
        if query.startswith("INSERT INTO theheat_batch_results." + table):
            raise RuntimeError("synthetic partial result write")
    def commit(c):
        if table == "commit":
            raise RuntimeError("synthetic partial result write")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=after, before_commit=commit)
        with pytest.raises(RuntimeError, match="synthetic partial"):
            operation()
    assert snapshot(core[3]) == before
    operation()


@pytest.mark.parametrize("action", ["record", "review"])
def test_real_connection_death_and_unknown_commit_reconcile_exactly(store, core, inputs, monkeypatch, action):
    operation = operation_for(store, inputs, action)
    before = snapshot(core[3])
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            operation()
    assert snapshot(core[3]) == before
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            operation()
    retained = snapshot(core[3])
    reopened = PostgresCommandAuthority(**options(core[3]))
    assert operation(reopened)["reused"]
    assert snapshot(core[3]) == retained
    assert spend_call(store, "status", {})["totals"]["held_micro_usd"] == 60


def process_call(params, action, values, barrier, queue):
    try:
        store = PostgresCommandAuthority(**options(params))
        barrier.wait(timeout=20)
        if action == "record":
            result = retain(store, *values)
        else:
            result = review(store, *values)
        queue.put(result)
    except BaseException as exc:
        queue.put({"error": type(exc).__name__})


def parallel(params, action, values):
    ctx = multiprocessing.get_context("spawn")
    barrier, queue = ctx.Barrier(len(values)), ctx.Queue()
    children = [ctx.Process(target=process_call, args=(params, action, value, barrier, queue)) for value in values]
    try:
        for child in children:
            child.start()
        result = [queue.get(timeout=45) for _ in children]
        for child in children:
            child.join(timeout=20)
            assert child.exitcode == 0
        assert all("error" not in row for row in result), result
        return result
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        queue.close()


@pytest.mark.parametrize("different", [False, True])
def test_independent_intake_and_review_serialize_choices(store, core, inputs, different):
    pair, grant = started(store, inputs)
    raw = contract.raw_rows(rows(pair))
    other = rows(pair)
    output = json.loads(other[0]["result"]["message"]["content"][0]["text"])
    output["tweet"] = "A different synthetic result."
    other[0]["result"]["message"]["content"][0]["text"] = json.dumps(output)
    values = [(grant, raw), (grant, contract.raw_rows(other) if different else raw)]
    receipts = parallel(core[3], "record", values)
    reviews = parallel(core[3], "review", [(pair, receipt) for receipt in receipts])
    if different:
        assert all("conflicting_complete_results" in report["report"]["context_blocked_reasons"] for report in reviews)
        assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.choices") == [(0,)]
    else:
        assert sorted(receipt["reused"] for receipt in receipts) == [False, True]
        assert sorted(report["reused"] for report in reviews) == [False, True]
        assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.choices") == [(1,)]


def test_explicit_owner_install_and_atomic_failure(worker_store, core, inputs, monkeypatch):
    store, initial, owner, params = core
    pair, grant = started(store, inputs)
    before = workers.snapshot(params)
    with pytest.raises(r.BatchResultError, match="migration_required"):
        retain(store, grant, contract.raw_rows(rows(pair)))
    with pytest.raises(r.BatchResultError, match="migration_required"):
        store.batch_results_status("job-fixture", now=NOW)
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        store.initialize_batch_results()
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_batch_results.metadata"):
            raise RuntimeError("synthetic migration failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic migration"):
            owner.initialize_batch_results()
    assert admin(params, "SELECT to_regnamespace('theheat_batch_results')") == [(None,)]
    assert workers.snapshot(params) == before
    owner.initialize_batch_results()
    assert workers.snapshot(params) == before
    for table in (*pg._ARTIFACTS, "receipts", "choices", "reviews"):
        assert admin(params, f"SELECT count(*) FROM theheat_batch_results.{table}") == [(0,)]
    owner.initialize_batch_results()


def test_prerequisite_worker_schema_required(spend_store, core):
    core[2].initialize_batches()
    with pytest.raises(w.BatchWorkerError, match="worker_migration_required"):
        core[2].initialize_batch_results()
    assert admin(core[3], "SELECT to_regnamespace('theheat_batch_results')") == [(None,)]


def test_inherited_permissions_removed_and_every_table_immutable(worker_store, core, inputs):
    import psycopg
    params = core[3]
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    core[2].initialize_batch_results()
    pair, _, _, receipt = ready_result(worker_store, inputs)
    review(worker_store, pair, receipt)
    assert admin(params, "SELECT has_schema_privilege('projection_runtime','theheat_batch_results','CREATE'),has_table_privilege('projection_runtime','theheat_batch_results.metadata','INSERT'),has_function_privilege('projection_runtime','theheat_batch_results.refuse_mutation()','EXECUTE')") == [(False, False, False)]
    for table in ("metadata", *pg._ARTIFACTS, "receipts", "choices", "reviews"):
        column = "version" if table == "metadata" else "byte_count" if table in pg._ARTIFACTS else "job_id"
        for query in (f"UPDATE theheat_batch_results.{table} SET {column}={column}", f"DELETE FROM theheat_batch_results.{table}", f"TRUNCATE theheat_batch_results.{table} CASCADE"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                admin({**params, "user": "projection_runtime"}, query)
            with pytest.raises(psycopg.errors.RaiseException, match="immutable batch results"):
                admin(params, query)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": "projection_runtime"}, "DROP TABLE theheat_batch_results.reviews")


@pytest.mark.parametrize("sql", [
    *[f"ALTER TABLE theheat_batch_results.{table} DISABLE TRIGGER {table}_immutable" for table in ("metadata", *pg._ARTIFACTS, "receipts", "choices", "reviews")],
    "GRANT UPDATE(payload) ON theheat_batch_results.result_artifacts TO projection_runtime",
    "GRANT EXECUTE ON FUNCTION theheat_batch_results.refuse_mutation() TO PUBLIC",
    "ALTER TABLE theheat_batch_results.reviews ADD COLUMN unexpected integer",
])
def test_schema_and_grant_drift_block_operations(store, core, inputs, sql):
    pair, grant, raw, receipt = ready_result(store, inputs)
    admin(core[3], sql)
    for op in (lambda: retain(store, grant, raw), lambda: review(store, pair, receipt), lambda: store.batch_results_status("job-fixture", now=NOW)):
        with pytest.raises(r.BatchResultError, match="changed_result_schema"):
            op()


@pytest.mark.parametrize("column,value,code", [
    ("version", 2, "unsupported_result_schema"), ("migration_sha", "bad", "unsupported_result_schema"),
    ("environment", "preview", "result_environment_mismatch"), ("runtime_role", "wrong", "result_role_mismatch")])
def test_metadata_mismatch_blocks_use(store, core, inputs, column, value, code):
    import psycopg
    ready_result(store, inputs)
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute(psycopg.sql.SQL("UPDATE theheat_batch_results.metadata SET {}=%s").format(psycopg.sql.Identifier(column)), (value,))
    with pytest.raises(r.BatchResultError, match=code):
        store.batch_results_status("job-fixture", now=NOW)


@pytest.mark.parametrize("sql,code", [
    ("UPDATE theheat_batch_results.receipts SET grant_id=repeat('f',64)", "changed_result_binding"),
    ("UPDATE theheat_batch_results.receipts SET recorded_at='2026-09-28T00:00:00.000000Z'", "invalid_result_receipt_time"),
    ("DELETE FROM theheat_batch_results.metadata_artifacts", "invalid_result_artifact_size"),
    ("DELETE FROM theheat_batch_results.result_artifacts", "invalid_result_artifact_size"),
    ("DELETE FROM theheat_batch_results.report_artifacts", "invalid_result_artifact_size"),
    ("UPDATE theheat_batch_results.choices SET receipt_id=repeat('f',64)", "changed_result_choice"),
    ("UPDATE theheat_batch_results.choices SET semantic_sha256=repeat('f',64)", "changed_result_choice"),
    ("UPDATE theheat_batch_results.reviews SET fence=999", "changed_result_review"),
    ("UPDATE theheat_batch_results.reviews SET recorded_at='2026-09-28T00:00:00.000000Z'", "changed_result_review"),
])
def test_corrupt_retained_joins_fail_closed_after_owner_bypass(store, core, inputs, sql, code):
    pair, _, _, receipt = ready_result(store, inputs)
    review(store, pair, receipt)
    admin(core[3], "SET session_replication_role=replica; " + sql)
    with pytest.raises(r.BatchResultError, match=code):
        review(store, pair, receipt)


def test_changed_report_with_valid_storage_hash_is_not_reused(store, core, inputs):
    import psycopg
    pair, _, _, receipt = ready_result(store, inputs)
    original = review(store, pair, receipt)
    doc = json.loads(artifact(core[3], "report_artifacts", original["report_sha256"]))
    doc["report"]["publication_approved"] = True
    raw = pg.canonical_json(doc).encode()
    admin(core[3], "INSERT INTO theheat_batch_results.report_artifacts VALUES(%s,%s,%s)", (digest(raw), raw, len(raw)))
    with psycopg.connect(**core[3]) as c:
        c.execute("SET session_replication_role=replica")
        c.execute("UPDATE theheat_batch_results.reviews SET report_sha256=%s", (digest(raw),))
    with pytest.raises(r.BatchResultError, match="changed_result_review"):
        review(store, pair, receipt)


def test_size_preflight_does_not_fetch_disallowed_blob(store, core, inputs, monkeypatch):
    pair, _, raw, _ = ready_result(store, inputs)
    monkeypatch.setitem(pg._ARTIFACTS, "result_artifacts", len(raw) - 1)
    def check(query, c):
        assert not query.startswith("SELECT payload FROM theheat_batch_results.result_artifacts")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=check)
        with pytest.raises(r.BatchResultError, match="artifact_size"):
            store.batch_results_status("job-fixture", now=NOW)


@pytest.mark.parametrize("table", list(pg._ARTIFACTS))
def test_database_hash_size_and_count_constraints(store, core, table):
    import psycopg
    for raw, sha, size in ((b"", "f" * 64, 0), (b"x", digest(b"x"), 0),
                           (b"x" * (pg._ARTIFACTS[table] + 1), None, pg._ARTIFACTS[table] + 1)):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(core[3], f"INSERT INTO theheat_batch_results.{table} VALUES(%s,%s,%s)", (sha or digest(raw), raw, size))


def test_foreign_keys_bind_receipts_choices_reviews(store, core, inputs):
    import psycopg
    pair, _, _, receipt = ready_result(store, inputs)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(core[3], "INSERT INTO theheat_batch_results.choices VALUES('absent',%s,%s)", (receipt["receipt_id"], "a" * 64))
    doc = review(store, pair, receipt)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin(core[3], "INSERT INTO theheat_batch_results.reviews VALUES(%s,'job-fixture',%s,999,%s,%s)", ("a" * 64, receipt["receipt_id"], doc["report_sha256"], spend._time(NOW)))


def test_actual_capacity_boundaries_and_exact_retry(store, core, inputs):
    pair, grant, raw, receipt = ready_result(store, inputs)
    for n in range(1, 16):
        retain(store, grant, raw, meta=metadata(extra=n))
    for n in range(64):
        review(store, pair, receipt, at=later(n))
    before = snapshot(core[3])
    assert retain(store, grant, raw, at=later(63))["reused"]
    assert review(store, pair, receipt, at=later(63))["reused"]
    with pytest.raises(r.BatchResultError, match="receipt_capacity"):
        retain(store, grant, raw, meta=metadata(extra=16), at=later(63))
    with pytest.raises(r.BatchResultError, match="review_capacity"):
        review(store, pair, receipt, at=later(64))
    assert snapshot(core[3]) == before


def test_six_schema_restore_preserves_exact_bytes_reviews_and_unknown_hold(store, core, inputs, cluster):
    import psycopg
    pair, grant = started(store, inputs, adopted=False)
    workers.call(store, "uncertain", owner="worker-one", fence=1)
    workers.adopt(store, ack(request_counts=dict(processing=1, succeeded=0, errored=0, expired=0, canceled=0)))
    raw = contract.raw_rows(rows(pair))
    receipt = retain(store, grant, raw)
    # Neither adoption, lease takeover nor result review settles the unknown hold.
    acquire(store, owner="replacement", at=later(300))
    result = review(store, pair, receipt, at=later(301), owner="replacement", fence=2)
    expected = snapshot(core[3])
    params, run, directory = cluster
    dump = directory / ("results-" + uuid4().hex + ".dump")
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    run("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    restored_params = {**core[3], "dbname": name}
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        restored = PostgresCommandAuthority(**options(restored_params))
        assert restored.batch_results_status("job-fixture", now=later(301)) == store.batch_results_status("job-fixture", now=later(301))
        repeated = review(restored, pair, receipt, at=later(301), owner="replacement", fence=2)
        assert repeated["reused"] and repeated["report_sha256"] == result["report_sha256"]
        assert artifact(restored_params, "result_artifacts", digest(raw)) == raw
        assert artifact(restored_params, "report_artifacts", result["report_sha256"]) == artifact(core[3], "report_artifacts", result["report_sha256"])
        assert not begin(restored, pair, owner="replacement", fence=2, at=later(301))["dispatch_granted"]
        assert spend_call(restored, "status", {}, later(301))["totals"]["held_micro_usd"] == 60
        owner = PostgresCommandAuthority(**options(restored_params, user="projection_owner"))
        owner.initialize(core[1], runtime_role="projection_runtime")
        owner.initialize_spending()
        owner.initialize_batches()
        owner.initialize_batch_workers()
        owner.initialize_batch_results()
        assert snapshot(restored_params) == expected
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
