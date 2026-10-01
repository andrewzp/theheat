"""Real local PostgreSQL checker execution using SDK HTTP fixtures only."""
from copy import deepcopy
import json
import multiprocessing
import os
from uuid import uuid4

import httpx
import pytest

from src.commands import check_journal as checks, postgres_checks
from src.commands.postgres_authority import PostgresCommandAuthority
from src.storage import postgres_projection as p
from src.two_bot import check_executor as executor, check_requests, check_transport
from tests import test_check_executor as legacy
from tests import test_postgres_check_observations as observations
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, wrap_connections
from tests.test_postgres_command_authority import core as core, make_authority as make_authority, options
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_batch_worker_journal import NOW, later

case, run, saved, provider, envelope = legacy.case, legacy.run, legacy.saved, legacy.provider, legacy.envelope

# These exercise the same real executor and SDK fixture, now through PostgreSQL.
# Keep SQLite's original assertions. SQL/commit/process tests below use PG itself.
from tests.test_check_executor import (
    test_disabled_performs_zero_io,
    test_exact_shared_requests_and_explicit_batch_only_output_bound,
    test_failures_never_retry_or_advance_and_keep_unknown_spend,
    test_retained_response_recovers_after_parser_crash_without_second_post,
    test_lost_commit_ack_never_rebuys,
    test_current_context_changes_block_without_post,
    test_reservation_failure_and_missing_key_do_not_dispatch,
    test_local_gates_reject_before_paid_checks,
    test_experimental_checks_share_event_identity_gate,
    test_scientific_rejection_keeps_material_inventory_gate,
    test_roundtrip_drift_refused,
    test_incomplete_or_unsupported_envelopes_are_never_passes,
    test_contradictory_provider_envelopes_cannot_pass,
    test_short_lease_prevents_purchase_even_when_previous_stage_passed,
    test_time_lost_during_grant_cannot_start_a_late_request,
    test_request_from_another_adapter_cannot_be_certified_by_recovery,
    test_recovered_observation_under_new_lease_is_stale,
    test_executor_refuses_mismatched_scoped_observation,
)


def test_actual_executor_all_stages_and_scoped_bytes(case, core, monkeypatch):
    before = case["store"].read()
    sent, clients = provider(monkeypatch, [envelope("NO"), envelope(legacy.FACT_PASS), envelope(legacy.CRITIC_PASS)])
    for stage in checks.STAGES:
        result = run(case, stage)
        assert result["outcome"] == "completed" and result["checks"]["stages"][stage] == "passed", result
        assert not result["publication_approved"] and result["cost_usd"] is None
        view = saved(case)
        attempt = view["attempts"][stage]
        request = case["store"].read_check_request(case["identity"], stage, attempt["grant_id"])
        assert request == legacy.canonical_json(check_requests.prepare_request(view["packet"], stage)).encode()
        response = case["store"].read_check_response(case["identity"], stage, attempt["grant_id"])
        assert legacy.hashlib.sha256(response).hexdigest() == attempt["observation"]["raw_sha256"]
    assert result["required_checks_completed"]
    assert len(sent) == 3 and all(c._http.is_closed for c in clients)
    assert case["store"].read() == before
    money = case["store"].spending("status", {}, now=NOW)
    assert money["intent_count"] == 4 and money["totals"]["held_micro_usd"] == 75
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts") == [(4,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.receipts") == [(4,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_check_executions.observations") == [(4,)]
    assert run(case)["outcome"] == "checks_completed" and len(sent) == 3


def test_scoped_requests_exist_without_observation_and_read_historical_grants(case, core, monkeypatch):
    view = saved(case)
    stage = "deterministic"
    request = legacy.canonical_json(check_requests.prepare_request(view["packet"], stage)).encode()
    identity = dict(check_set_id=case["identity"], owner="worker-one", fence=1,
        current_context=case["payload"]["current_context"], checker_state_sha256=view["packet"]["checker_state_sha256"])
    grant = case["store"].candidate_checks("begin", dict(identity, stage=stage, reservation=None), request=request, now=NOW)
    before = observations.snapshot(core[3])
    assert case["store"].read_check_request(case["identity"], stage, grant["grant_id"]) == request
    with pytest.raises(checks.CheckJournalError, match="not_found"):
        case["store"].read_check_response(case["identity"], stage, grant["grant_id"])
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "0")
    assert case["store"].read_check_request(case["identity"], stage, grant["grant_id"]) == request
    for key, bad in (("check_set_id", "f" * 64), ("stage", "safety"), ("grant_id", "f" * 64)):
        args = dict(check_set_id=case["identity"], stage=stage, grant_id=grant["grant_id"])
        args[key] = bad
        with pytest.raises(ValueError):
            case["store"].read_check_request(**args)
    assert observations.snapshot(core[3]) == before


@pytest.mark.parametrize("layer", ["begin", "observe", "complete"])
@pytest.mark.parametrize("fault", ["before_commit", "killed", "lost_ack"])
def test_actual_transaction_faults_never_repurchase(case, core, monkeypatch, layer, fault):
    sent, _ = provider(monkeypatch, [envelope("NO")])
    assert run(case)["outcome"] == "completed"
    table = {"begin": "theheat_checks.attempts", "observe": "theheat_check_executions.observations", "complete": "theheat_checks.receipts"}[layer]
    fired = False
    def affected(c):
        rows = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return rows == 2
    def fail(c):
        nonlocal fired
        if not fired and affected(c):
            fired = True
            if fault == "killed":
                c.execute("SELECT pg_terminate_backend(pg_backend_pid())")
            else:
                raise RuntimeError("fixture before commit")
    if fault == "lost_ack":
        # Preserve actual commit handling, then make the acknowledgment unknown
        # only on the specific transaction, after the server has committed it.
        original = p.PostgresProjectionRepository._connection
        from contextlib import contextmanager
        @contextmanager
        def connection(self, *, writing=False):
            nonlocal fired
            target = False
            with original(self, writing=writing) as c:
                yield c
                target = writing and not fired and affected(c)
            if target:
                fired = True
                raise p.ProjectionError("write_outcome_unknown")
        monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", connection)
    else:
        wrap_connections(monkeypatch, before_commit=fail)
    result = run(case, "safety")
    assert fired and result["outcome"] == "reconciliation_required", result
    before_calls = len(sent)
    case["store"] = PostgresCommandAuthority(**options(core[3]))
    recovered = run(case, "safety")
    if layer == "begin" and fault != "lost_ack":
        assert before_calls == 0 and len(sent) == 1  # No grant ever committed before retry.
    else:
        assert len(sent) == before_calls == (0 if layer == "begin" else 1)
    assert not recovered["publication_approved"] and recovered["cost_usd"] is None
    if layer == "begin" and fault == "lost_ack" or layer == "observe" and fault != "lost_ack":
        assert recovered["reason"] == "check_response_not_retained"
    if layer == "observe" and fault == "lost_ack" or layer == "complete" and fault != "lost_ack":
        assert recovered["checks"]["stages"]["safety"] == "passed"
    assert case["store"].spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 65
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE stage='safety'") == [(1,)]


def test_late_return_retains_usage_and_does_not_pass(case, core, monkeypatch):
    run(case)
    at = [NOW]
    def handle(request):
        at[0] = later(301)
        return httpx.Response(200, request=request, stream=httpx.ByteStream(envelope("NO")))
    monkeypatch.setattr(executor, "GoogleCheckTransport", lambda **kw: check_transport.GoogleCheckTransport(**kw, http_transport=httpx.MockTransport(handle)))
    result = run(case, "safety", clock=lambda: at[0])
    assert result["checks"]["stages"]["safety"] == "stale" and not result["required_checks_completed"]
    raw = admin(core[3], "SELECT payload FROM theheat_checks.receipt_artifacts JOIN theheat_checks.receipts ON sha=receipt_sha256 JOIN theheat_checks.attempts USING(grant_id) WHERE stage='safety'")[0][0]
    assert json.loads(raw)["usage"]["promptTokenCount"] == 19


def test_eight_schema_restore_resumes_retained_response_without_http(case, core, cluster, monkeypatch):
    import psycopg
    run(case)
    sent, _ = provider(monkeypatch, [envelope("NO")])
    interpreter = check_requests.interpret_observation
    monkeypatch.setattr(check_requests, "interpret_observation", lambda *a: (_ for _ in ()).throw(RuntimeError("crash before parse")))
    assert run(case, "safety")["outcome"] == "reconciliation_required" and len(sent) == 1
    monkeypatch.setattr(check_requests, "interpret_observation", interpreter)
    original = case["store"].read()
    params, command, directory = cluster
    common = ("-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-w")
    dump = directory / ("executor-" + uuid4().hex + ".dump")
    command("pg_dump", *common, "-Fc", "-f", str(dump), core[3]["dbname"])
    name = "restore_" + uuid4().hex
    admin(params, psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))
    try:
        command("pg_restore", *common, "--single-transaction", "-d", name, str(dump))
        case["store"] = PostgresCommandAuthority(**options({**core[3], "dbname": name}))
        recovered = run(case, "safety")
        assert recovered["checks"]["stages"]["safety"] == "passed" and len(sent) == 1
        assert not recovered["publication_approved"] and not recovered["accounting_complete"]
        assert case["store"].spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 65
        assert case["store"].read() == original
    finally:
        admin(params, psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))


@pytest.mark.parametrize("kind", ["request-missing", "raw-missing", "binding-time", "observation-time", "set", "request", "boolean", "canonical"])
def test_scoped_accessors_refuse_damaged_restore(case, core, kind):
    import psycopg
    run(case)
    attempt = saved(case)["attempts"]["deterministic"]
    args = (case["identity"], "deterministic", attempt["grant_id"])
    with psycopg.connect(**core[3]) as c:
        # Simulate a damaged restore while preserving the exact schema and its
        # normal runtime protections. Valid-hash metadata must also be refused.
        c.execute("SET session_replication_role=replica")
        if kind == "request-missing":
            c.execute("DELETE FROM theheat_checks.request_artifacts")
        elif kind == "raw-missing":
            c.execute("DELETE FROM theheat_check_executions.raw_artifacts")
        elif kind.endswith("time"):
            table = "theheat_checks.attempts" if kind == "binding-time" else "theheat_check_executions.observations"
            c.execute(f"UPDATE {table} SET recorded_at='2026-09-28T00:00:00.000000Z'")
        else:
            data = deepcopy(attempt["observation"])
            if kind == "set":
                data["check_set_id"] = "f" * 64
            elif kind == "request":
                data["request_sha256"] = "f" * 64
            elif kind == "boolean":
                data["complete"] = 1
            raw = (json.dumps(data, indent=2) if kind == "canonical" else legacy.canonical_json(data)).encode()
            sha = legacy.hashlib.sha256(raw).hexdigest()
            c.execute("INSERT INTO theheat_check_executions.metadata_artifacts VALUES(%s,%s,%s)", (sha, raw, len(raw)))
            c.execute("UPDATE theheat_check_executions.observations SET metadata_sha256=%s", (sha,))
    for reader in (case["store"].read_check_request, case["store"].read_check_response):
        with pytest.raises(ValueError):
            reader(*args)


@pytest.mark.parametrize("table", ["request_artifacts", "metadata_artifacts", "raw_artifacts"])
def test_scoped_accessors_preflight_before_fetching_payload(case, core, monkeypatch, table):
    run(case)
    attempt = saved(case)["attempts"]["deterministic"]
    pg = postgres_checks if table == "request_artifacts" else observations.pg
    monkeypatch.setitem(pg._ARTIFACTS, table, 0 if table == "request_artifacts" else (0, 0))
    def guard(query, c):
        assert not query.startswith(f"SELECT payload FROM {pg.SCHEMA}.{table}"), "blob fetched before bound check"
    wrap_connections(monkeypatch, after_execute=guard)
    for reader in (case["store"].read_check_request, case["store"].read_check_response):
        with pytest.raises(checks.CheckJournalError, match="size"):
            reader(case["identity"], "deterministic", attempt["grant_id"])


@pytest.mark.parametrize("sql", [
    "GRANT UPDATE(payload) ON theheat_check_executions.raw_artifacts TO projection_runtime",
    "ALTER TABLE theheat_checks.attempts DISABLE TRIGGER attempts_immutable",
    "ALTER TABLE theheat_check_executions.observations ADD COLUMN unexpected integer",
])
def test_scoped_accessors_refuse_changed_schema_and_privileges(case, core, sql):
    run(case)
    grant = saved(case)["attempts"]["deterministic"]["grant_id"]
    admin(core[3], sql)
    for reader in (case["store"].read_check_request, case["store"].read_check_response):
        with pytest.raises(checks.CheckJournalError, match="changed_check"):
            reader(case["identity"], "deterministic", grant)


def process_execute(params, identity, payload, count, output, mode, barrier=None, release=None):
    """A fresh interpreter, real DB transactions, and only explicit SDK fixtures."""
    import socket
    from src.two_bot import writer
    from src.voice import safety
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(writer, "WRITER_PROVIDER", "anthropic")
        patch.setattr(writer, "WRITER_MODEL", "claude-synthetic")
        patch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
        patch.setenv("GEMINI_API_KEY", "offline-fixture-key")
        patch.setenv("THEHEAT_CRITIC_ENABLED", "1")
        def forbid(*args, **kwargs):
            raise AssertionError("real provider network prohibited")
        patch.setattr(socket, "create_connection", forbid)
        patch.setattr(socket.socket, "connect", forbid)
        store = PostgresCommandAuthority(**options(params))
        if mode == "before_commit":
            def die(c):
                if c.execute("SELECT count(*) FROM theheat_check_executions.observations").fetchone()[0] == 2:
                    os._exit(31)
            wrap_connections(patch, before_commit=die)
        elif mode == "after_commit":
            original = store.check_execution
            def die_after(action, *args, **kwargs):
                result = original(action, *args, **kwargs)
                if action == "observe":
                    os._exit(31)
                return result
            patch.setattr(store, "check_execution", die_after)
        def handle(request):
            with count.get_lock():
                count.value += 1
            if release is not None:
                assert release.wait(30), "competing process did not finish"
            return httpx.Response(200, request=request, stream=httpx.ByteStream(envelope("NO")))
        patch.setattr(executor, "GoogleCheckTransport", lambda **kw: check_transport.GoogleCheckTransport(**kw, http_transport=httpx.MockTransport(handle)))
        if barrier is not None:
            barrier.wait(timeout=30)
        output.put(run(dict(store=store, identity=identity, payload=payload), "safety"))


@pytest.mark.parametrize("mode", ["before_commit", "after_commit"])
def test_fresh_process_death_never_repeats_provider_request(case, core, monkeypatch, mode):
    assert run(case)["outcome"] == "completed"
    ctx = multiprocessing.get_context("spawn")
    count, output = ctx.Value("i", 0), ctx.Queue()
    child = ctx.Process(target=process_execute, args=(core[3], case["identity"], case["payload"], count, output, mode))
    try:
        child.start()
        child.join(timeout=30)
        assert not child.is_alive() and child.exitcode == 31
        case["store"] = PostgresCommandAuthority(**options(core[3]))
        sent, _ = provider(monkeypatch, [envelope("NO")])
        result = run(case, "safety")
        assert count.value == 1 and not sent
        if mode == "before_commit":
            assert result["reason"] == "check_response_not_retained"
        else:
            assert result["checks"]["stages"]["safety"] == "passed"
        assert not result["publication_approved"] and not result["accounting_complete"]
        assert case["store"].spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 65
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        output.close()


def test_independent_workers_competing_for_same_stage_purchase_once(case, core, monkeypatch):
    run(case)
    ctx = multiprocessing.get_context("spawn")
    count, output, barrier, release = ctx.Value("i", 0), ctx.Queue(), ctx.Barrier(2), ctx.Event()
    children = [ctx.Process(target=process_execute, args=(core[3], case["identity"], case["payload"], count, output, "race", barrier, release)) for _ in range(2)]
    try:
        for child in children:
            child.start()
        first = output.get(timeout=40)  # The loser returns while the winner holds the response.
        assert first["outcome"] in ("not_dispatched", "reconciliation_required"), first
        release.set()
        second = output.get(timeout=40)
        assert second["checks"]["stages"]["safety"] == "passed", second
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert count.value == 1
        for table in ("attempts", "receipts"):
            assert admin(core[3], f"SELECT count(*) FROM theheat_checks.{table}") == [(2,)]
        assert admin(core[3], "SELECT count(*) FROM theheat_check_executions.observations") == [(2,)]
        sent, _ = provider(monkeypatch, [envelope(legacy.FACT_PASS)])
        # A subsequent invocation may advance to the next required stage only
        # with its own exact reservation; it never purchases safety again.
        result = run(case, "safety")
        assert not sent and not result["publication_approved"]
        assert case["store"].spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 65
    finally:
        release.set()
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        output.close()
