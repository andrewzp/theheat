"""Real PostgreSQL spending transactions, paired local policy, no provider calls."""
import multiprocessing
import time
from uuid import uuid4

import pytest

from src.commands import postgres_spending as pg, spend_journal as s
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.schema import CommandError
from src.commands.sqlite_authority import SQLiteAuthority
from src.storage import postgres_projection as p
from tests.test_command_authority import story, command, EDITOR, resolver, NOW as COMMAND_NOW
from tests.test_postgres_projection import cluster as cluster, database as database
from tests.test_postgres_projection import admin, counts, wrap_connections
from tests.test_postgres_command_authority import make_authority as make_authority, core as core
from tests.test_postgres_command_authority import options, table_counts
from tests.test_spend_journal import NOW, LATER, LIMITS, intent, call, settle
# The identical existing policy assertions also run against the PG store fixture.
from tests.test_spend_journal import (
    test_reservation_replay_and_changed_intent_conflict as test_reservation_replay_and_changed_intent_conflict,
    test_all_supported_roles_share_daily_and_per_job_allowances as test_all_supported_roles_share_daily_and_per_job_allowances,
    test_uncertain_holds_carry_across_day_and_month_indefinitely as test_uncertain_holds_carry_across_day_and_month_indefinitely,
    test_only_never_dispatched_reservations_can_be_released as test_only_never_dispatched_reservations_can_be_released,
    test_settlement_is_idempotent_but_not_an_unknown_charge_as_zero as test_settlement_is_idempotent_but_not_an_unknown_charge_as_zero,
    test_monthly_and_job_limits_do_not_reset_on_new_day as test_monthly_and_job_limits_do_not_reset_on_new_day,
    test_settlement_counts_conservatively_in_its_new_window as test_settlement_counts_conservatively_in_its_new_window,
    test_overrun_is_recorded_and_blocks_new_reservations_and_old_dispatches as test_overrun_is_recorded_and_blocks_new_reservations_and_old_dispatches,
    test_reservation_amounts_are_strict_positive_micro_usd as test_reservation_amounts_are_strict_positive_micro_usd,
    test_unknown_or_unbound_intents_refused as test_unknown_or_unbound_intents_refused,
    test_clock_is_monotonic_at_subsecond_precision as test_clock_is_monotonic_at_subsecond_precision,
)


@pytest.fixture
def store(core):
    value, _, owner, _ = core
    owner.initialize_spending()
    call(value, "configure", LIMITS)
    return value


def _worker(params, action, payload, barrier, results):
    try:
        barrier.wait(timeout=15)
        value = PostgresCommandAuthority(**options(params))
        results.put(value.spending(action, payload, now=NOW))
    except s.SpendError as exc:
        results.put({"denied": str(exc)})
    except BaseException as exc:
        results.put({"worker_error": repr(exc)})


def parallel(params, action, payloads):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(len(payloads)), ctx.Queue()
    children = [ctx.Process(target=_worker, args=(params, action, payload, barrier, results)) for payload in payloads]
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


def test_competing_reservations_share_cap(store, core):
    values = parallel(core[3], "reserve", [intent(), intent("two", job="other")])
    assert sum("denied" in value for value in values) == 1
    assert call(store, "status", {})["totals"]["held_micro_usd"] == 60


def test_exact_request_concurrency_and_one_dispatch_after_restart(store, core):
    values = parallel(core[3], "reserve", [intent()] * 2)
    assert sum(value["reused"] for value in values) == 1
    values = parallel(core[3], "dispatch", [{"intent_id": "attempt-1"}] * 2)
    assert sum(value["dispatch_granted"] for value in values) == 1
    reopened = PostgresCommandAuthority(**options(core[3]))
    assert not call(reopened, "dispatch")["dispatch_granted"]
    assert call(reopened, "status")["totals"]["held_micro_usd"] == 60


def _queued_worker(params, action, payload, ready, results):
    try:
        store = PostgresCommandAuthority(**options(params))
        ready.set()
        if action == "consume":
            results.put(store.consume(resolver, now=COMMAND_NOW))
        else:
            results.put(call(store, action, payload))
    except BaseException as exc:
        results.put({"worker_error": repr(exc)})


def test_spend_and_command_consumers_wait_for_the_same_database_lock(store, core):
    import psycopg
    params = core[3]
    cmd = command(core[1]["drafts"][0])
    store.accept(cmd, EDITOR, now=COMMAND_NOW)
    ctx = multiprocessing.get_context("spawn")
    results = ctx.Queue()
    events = [ctx.Event(), ctx.Event()]
    children = [ctx.Process(target=_queued_worker, args=(params, action, payload, event, results))
                for (action, payload), event in zip((("reserve", intent()), ("consume", None)), events, strict=True)]
    try:
        with psycopg.connect(**{**params, "autocommit": False}) as c:
            c.execute("SELECT version FROM theheat_commands.state WHERE singleton=1 FOR UPDATE")
            for child in children:
                child.start()
            assert all(event.wait(15) for event in events)
            deadline = time.monotonic() + 15
            waiting = 0
            while waiting < 2 and time.monotonic() < deadline:
                waiting = admin(params, "SELECT count(*) FROM pg_stat_activity WHERE datname=%s AND wait_event_type='Lock' AND query LIKE 'SELECT version,namespace,snapshot_id%%FOR UPDATE'", (params["dbname"],))[0][0]
                if waiting < 2:
                    time.sleep(0.02)
            assert waiting == 2
            assert admin(params, "SELECT count(*) FROM theheat_spending.intents") == [(0,)]
            assert table_counts(params)["results"] == 0
        values = [results.get(timeout=30) for child in children]
        assert not any("worker_error" in value for value in values)
        assert sum(value.get("status") == "applied" for value in values) == 1
        assert call(store, "status")["totals"]["held_micro_usd"] == 60
        assert store.read()[0] == 1
    finally:
        for child in children:
            if child.pid:
                child.join(timeout=10)
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=10)


def test_connection_composition_rolls_back_as_one_outer_transaction(store, core):
    import psycopg
    params = core[3]
    with psycopg.connect(**params) as c:
        with pytest.raises(s.SpendError, match="spending_requires_transaction"):
            pg.apply(c, "reserve", intent(), now=NOW, environment="local")
    with pytest.raises(RuntimeError, match="synthetic job registration"):
        with store.projections._connection(writing=True) as c:
            store._validate(c)
            store._pointer(c, lock=True)
            pg.apply(c, "reserve", intent(), now=NOW, environment="local")
            assert pg.apply(c, "dispatch", {"intent_id": "attempt-1"}, now=NOW, environment="local")["dispatch_granted"]
            # The provisional grant must not leave the caller's failed transaction.
            raise RuntimeError("synthetic job registration")
    assert call(store, "status", {})["intent_count"] == 0
    call(store, "reserve", intent())
    assert call(store, "dispatch")["dispatch_granted"]


def test_full_outputs_match_sqlite(store, tmp_path):
    sqlite = SQLiteAuthority(tmp_path / "paired.sqlite")
    sqlite.initialize({})
    assert call(sqlite, "configure", LIMITS) == call(store, "configure", LIMITS)
    for action, payload in [
        ("status", {}), ("reserve", intent()), ("reserve", intent()),
        ("dispatch", {"intent_id": "attempt-1"}), ("dispatch", {"intent_id": "attempt-1"}),
        ("uncertain", {"intent_id": "attempt-1"}), ("status", {"intent_id": "attempt-1"}),
        ("settle", {"intent_id": "attempt-1", "amount_micro_usd": 40, "evidence_sha256": "d" * 64}),
        ("reserve", intent("two", 20, "other")), ("release", {"intent_id": "two"}),
        ("dispatch", {"intent_id": "two"}), ("status", {}),
    ]:
        assert call(store, action, payload) == call(sqlite, action, payload)
    for value in (store, sqlite):
        with pytest.raises(s.SpendError, match="conflicting_spend_settlement"):
            settle(value, 41)
        assert call(value, "status", {}, at=LATER)["totals"]["daily_micro_usd"] == 0


def test_sql_aggregates_match_reference_for_varied_histories(core):
    store, _, owner, params = core
    owner.initialize_spending()
    call(store, "configure", {**LIMITS, "daily_micro_usd": s.MAX_AMOUNT,
                             "monthly_micro_usd": s.MAX_AMOUNT, "per_job_micro_usd": s.MAX_AMOUNT})
    records = {}
    for n in range(25):
        payload = intent(str(n), n + 1, f"job-{n % 3}", ["writer", "safety", "fact_check", "critic", "news", "repair"][n % 6])
        payload["provider"] = "anthropic" if n % 2 else "google"
        call(store, "reserve", payload)
        identity = {"intent_id": str(n)}
        if n % 5 == 1:
            call(store, "release", identity)
        elif n % 5 >= 2:
            call(store, "dispatch", identity)
            if n % 5 == 3:
                call(store, "uncertain", identity)
            elif n % 5 == 4:
                settle(store, n, identity=str(n))
        records[str(n)] = call(store, "status", identity)["intent"]
    for when in (NOW, LATER, "2027-10-01T12:00:00Z"):
        with store.projections._connection() as c:
            for job in (None, "job-0", "job-1", "job-2"):
                assert pg._totals(c, pg._time(when), job) == s._totals(records, when, job)
    with store.projections._connection() as c:
        # The schema has a real latest-event index, not a per-intent JSON cache.
        assert c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND indexname='events_latest'", (pg.SCHEMA,)).fetchone()
    assert admin(params, "SELECT count(*) FROM theheat_spending.intents") == [(25,)]


def test_install_explicit_idempotent_owner_only_and_preserves_current_core(core):
    store, initial, owner, params = core
    before = counts(params), table_counts(params)
    with pytest.raises(s.SpendError, match="spend_migration_required"):
        call(store, "status", {})
    with pytest.raises(p.ProjectionError, match="migration_owner_required"):
        store.initialize_spending()
    owner.initialize_spending()
    with pytest.raises(s.SpendError, match="not_configured"):
        call(store, "reserve", intent())
    limits = {**LIMITS, "daily_micro_usd": 0}
    call(store, "configure", limits)
    owner.initialize_spending()
    owner.initialize(initial, runtime_role="projection_runtime")
    call(store, "configure", limits)
    with pytest.raises(s.SpendError, match="immutable"):
        call(store, "configure", LIMITS)
    with pytest.raises(s.SpendError, match="allowance"):
        call(store, "reserve", intent(amount=1))
    assert store.read() == (0, initial)
    assert (counts(params), table_counts(params)) == before
    assert call(store, "status", {})["limits"] == limits


def test_install_rollback_and_defaults_removed(core, monkeypatch):
    store, _, owner, params = core
    admin(params, "ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO PUBLIC,projection_runtime; ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO projection_runtime; ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO projection_runtime")
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_spending.metadata"):
            raise RuntimeError("synthetic install failure")
    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="synthetic install"):
            owner.initialize_spending()
    assert admin(params, "SELECT to_regnamespace('theheat_spending')") == [(None,)]
    owner.initialize_spending()
    assert admin(params, "SELECT has_table_privilege('projection_runtime','theheat_spending.limits','UPDATE,DELETE,TRUNCATE'),has_sequence_privilege('projection_runtime','theheat_spending.events_sequence_seq','UPDATE'),has_function_privilege('projection_runtime','theheat_spending.check_event()','EXECUTE'),has_schema_privilege('projection_runtime','theheat_spending','CREATE')") == [(False, False, False, False)]
    call(store, "configure", LIMITS)
    call(store, "reserve", intent())
    assert call(store, "dispatch")["dispatch_granted"]


@pytest.mark.parametrize("action,payload", [
    ("configure", LIMITS), ("reserve", intent()),
    ("dispatch", {"intent_id": "attempt-1"}), ("uncertain", {"intent_id": "attempt-1"}),
    ("release", {"intent_id": "attempt-1"}),
    ("settle", {"intent_id": "attempt-1", "amount_micro_usd": 40, "evidence_sha256": "d" * 64}),
])
def test_insert_and_commit_failures_roll_back(core, monkeypatch, action, payload):
    store, _, owner, params = core
    owner.initialize_spending()
    if action != "configure":
        call(store, "configure", LIMITS)
    if action not in ("configure", "reserve"):
        call(store, "reserve", intent())
    if action in ("uncertain", "settle"):
        call(store, "dispatch")
    def size():
        return [admin(params, f"SELECT count(*) FROM theheat_spending.{table}")[0][0] for table in ("limits", "intents", "events")]
    before = size()
    def fail(query, c):
        if query.startswith("INSERT INTO theheat_spending."):
            raise RuntimeError("synthetic spending failure")
    def commit_fail(c):
        raise RuntimeError("synthetic spending failure")
    for boundary in ({"after_execute": fail}, {"before_commit": commit_fail}):
        with monkeypatch.context() as patch:
            wrap_connections(patch, **boundary)
            with pytest.raises(RuntimeError, match="synthetic spending failure"):
                call(store, action, payload)
        assert size() == before
    result = call(store, action, payload)
    if action == "dispatch":
        assert result["dispatch_granted"]


def test_connection_death_and_lost_dispatch_ack(store, core, monkeypatch):
    with monkeypatch.context() as patch:
        wrap_connections(patch, before_commit=lambda c: c.execute("SELECT pg_terminate_backend(pg_backend_pid())"))
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            call(store, "reserve", intent())
    assert call(store, "status", {})["intent_count"] == 0
    call(store, "reserve", intent())
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
            call(store, "dispatch")
    reopened = PostgresCommandAuthority(**options(core[3]))
    assert call(reopened, "status")["intent"]["state"] == "dispatched"
    assert not call(reopened, "dispatch")["dispatch_granted"]
    with pytest.raises(s.SpendError, match="cannot_release"):
        call(reopened, "release")


def test_spending_and_status_preserve_every_core_row(store, core, monkeypatch):
    _, initial, _, params = core
    before = counts(params), table_counts(params), store.read(), store.journal()
    # Spending locks only the pointer: never fetch the possibly large projection.
    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_read", lambda *a: pytest.fail("spending loaded draft projection"))
        call(store, "reserve", intent())
        call(store, "dispatch")
        call(store, "uncertain")
        settle(store)
        size = admin(params, "SELECT count(*) FROM theheat_spending.events")
        call(store, "status")
        call(store, "status", {})
        assert admin(params, "SELECT count(*) FROM theheat_spending.events") == size
    assert (counts(params), table_counts(params), store.read(), store.journal()) == before
    cmd = command(initial["drafts"][0])
    store.accept(cmd, EDITOR, now=COMMAND_NOW)
    assert store.consume(resolver, now=COMMAND_NOW)["status"] == "applied"


@pytest.mark.parametrize("sql", [
    "ALTER TABLE theheat_spending.events DISABLE TRIGGER events_progress",
    "DROP INDEX theheat_spending.events_latest",
    "GRANT UPDATE(payload) ON theheat_spending.intents TO projection_runtime",
    "GRANT UPDATE ON SEQUENCE theheat_spending.events_sequence_seq TO projection_runtime",
])
def test_schema_and_permissions_drift_refuses(store, core, sql):
    admin(core[3], sql)
    with pytest.raises(s.SpendError, match="changed_spend_schema"):
        call(store, "status", {})


@pytest.mark.parametrize("sql", [
    "UPDATE theheat_spending.limits SET recorded_at=recorded_at",
    "DELETE FROM theheat_spending.intents",
    "TRUNCATE theheat_spending.events",
])
def test_append_only_guards_for_runtime_and_ordinary_owner(store, core, sql):
    import psycopg
    params = core[3]
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        admin({**params, "user": "projection_runtime"}, sql)
    with pytest.raises(psycopg.errors.RaiseException, match="immutable spending journal"):
        admin(params, sql)


def test_database_duplicate_columns_and_event_digest_are_enforced(store, core):
    import psycopg
    params = core[3]
    payload = intent()
    raw = pg._body(payload)
    for job, amount, body, digest in (("wrong", 60, raw, p._sha(raw)), ("job-1", 61, raw, p._sha(raw)),
                                      ("job-1", 60, raw, "0" * 64), ("job-1", 60, b'[]', p._sha(b'[]'))):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin(params, "INSERT INTO theheat_spending.intents VALUES(%s,%s,%s,%s,%s,%s)",
                  ("attempt-1", job, amount, body, digest, pg._time(NOW)))
    call(store, "reserve", intent())
    # A digest-valid event still cannot claim a different indexed intent/amount.
    raw = pg._body(dict(intent_id="wrong", kind="dispatched", recorded_at=pg._time(NOW), amount_micro_usd=None, evidence_sha256=None))
    with pytest.raises(psycopg.errors.CheckViolation):
        admin(params, "INSERT INTO theheat_spending.events(intent_id,kind,recorded_at,payload,digest) VALUES('attempt-1','dispatched',%s,%s,%s)", (pg._time(NOW), raw, p._sha(raw)))
    assert call(store, "status")["intent"]["state"] == "reserved"


@pytest.mark.parametrize("value", [True, -1, 1.5, 10**12 + 1])
def test_limits_amounts_are_strict(core, value):
    store, _, owner, _ = core
    owner.initialize_spending()
    with pytest.raises(s.SpendError, match="invalid_micro"):
        call(store, "configure", {**LIMITS, "daily_micro_usd": value})


@pytest.mark.parametrize("value", ["2026-09-29", "2026-09-29T12:00:00+00:00", "2026-02-30T12:00:00Z", None])
def test_invalid_clock_refuses(store, value):
    with pytest.raises(CommandError, match="UTC|calendar"):
        call(store, "status", {}, at=value)


def test_payload_capacity_and_backward_replay_bounds(store, monkeypatch):
    with pytest.raises(s.SpendError, match="oversized"):
        call(store, "reserve", {**intent(), "model": "x" * 4096})
    call(store, "reserve", intent(), at=LATER)
    for action, payload in (("reserve", intent()), ("configure", LIMITS), ("status", {})):
        with pytest.raises(s.SpendError, match="backwards"):
            call(store, action, payload)
    with monkeypatch.context() as patch:
        patch.setattr(s, "MAX_INTENTS", 1)
        with pytest.raises(s.SpendError, match="capacity"):
            call(store, "reserve", intent("two", 1), at=LATER)


def test_missing_history_is_not_treated_as_an_undispatched_hold(store, core):
    call(store, "reserve", intent())
    call(store, "dispatch")
    call(store, "uncertain")
    params = core[3]
    admin(params, "ALTER TABLE theheat_spending.events DISABLE TRIGGER events_immutable; DELETE FROM theheat_spending.events WHERE kind='dispatched'; ALTER TABLE theheat_spending.events ENABLE TRIGGER events_immutable")
    with pytest.raises(s.SpendError, match="corrupt_spend_history"):
        call(store, "dispatch")


@pytest.mark.parametrize("action,payload,code", [
    ("new_action", {}, "unknown_spending_action"),
    ("status", {"extra": True}, "invalid_spend_fields"),
    ("status", {"intent_id": "absent"}, "spend_intent_not_found"),
    ("dispatch", {"intent_id": "absent"}, "spend_intent_not_found"),
    ("release", {}, "invalid_spend_fields"),
])
def test_bad_actions_have_bounded_errors(store, action, payload, code):
    with pytest.raises(s.SpendError, match=f"^{code}$"):
        call(store, action, payload)


def test_backup_restore_all_schemas_and_unknown_hold(store, core, cluster):
    import psycopg
    params = core[3]
    call(store, "reserve", intent())
    call(store, "dispatch")
    call(store, "uncertain")
    args, run, root = cluster
    dump = root / "spending.dump"
    common = ["-h", args["host"], "-p", args["port"], "-U", args["user"], "-w"]
    run("pg_dump", *common, "-Fc", "-f", dump, params["dbname"])
    name = "restore_" + uuid4().hex
    with psycopg.connect(**args) as c:
        c.execute(psycopg.sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(psycopg.sql.Identifier(name)))
    try:
        run("pg_restore", *common, "--single-transaction", "-d", name, dump)
        restored = PostgresCommandAuthority(**options({**params, "dbname": name}))
        assert restored.read() == store.read() and restored.journal() == store.journal()
        assert call(restored, "status") == call(store, "status")
        assert not call(restored, "dispatch")["dispatch_granted"]
        assert call(restored, "status", at=LATER)["totals"]["held_micro_usd"] == 60
        with pytest.raises(s.SpendError, match="cannot_release"):
            call(restored, "release", at=LATER)
    finally:
        with psycopg.connect(**args) as c:
            c.execute(psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(psycopg.sql.Identifier(name)))
