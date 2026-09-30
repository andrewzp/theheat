"""Fenced local worker ownership, real crash/concurrency and late acknowledgment tests."""

from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import batch_worker_journal as worker
from src.commands.schema import utc_datetime
from src.commands.sqlite_authority import SQLiteAuthority
from tests import test_batch_journal as fixtures
from tests.two_bot.test_batch_contract import context

store = fixtures.store
inputs = fixtures.inputs
NOW = fixtures.NOW
packet, register, digest, snapshot = (
    fixtures.packet,
    fixtures.register,
    fixtures.digest,
    fixtures.snapshot,
)


def later(seconds):
    return (utc_datetime(NOW) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def call(store, action, job="job-fixture", *, at=NOW, raw=None, **fields):
    return store.batch_work(action, dict(job_id=job, **fields), now=at, raw=raw)


def ready(store, inputs, *, job=None, identity=None, amount=60):
    pair = packet(inputs, job=job, identity=identity, amount=amount)
    register(store, pair)
    return pair


def acquire(store, job="job-fixture", *, owner="worker-one", at=NOW, ttl=300):
    return call(store, "acquire", job, at=at, owner=owner, ttl_seconds=ttl)


def begin(store, pair, *, owner="worker-one", fence=1, at=NOW):
    return call(
        store,
        "begin",
        pair[1]["job_id"],
        at=at,
        owner=owner,
        fence=fence,
        current_context=context(pair[0]),
    )


def ack(identity="msgbatch_fixture", **changes):
    data = dict(
        id=identity,
        type="message_batch",
        processing_status="in_progress",
        request_counts=dict(processing=1, succeeded=0, canceled=0, expired=0, errored=0),
        results_url="https://untrusted.invalid/not-followed",
    )
    data.update(changes)
    return json.dumps(data).encode()


def observe(store, grant, raw=None, *, at=NOW):
    raw = ack() if raw is None else raw
    return call(
        store,
        "observe_ack",
        grant["job_id"],
        at=at,
        raw=raw,
        grant_id=grant["grant_id"],
        receipt_sha256=digest(raw),
    )


def adopt(store, raw=None, *, owner="worker-one", fence=1, at=NOW, job="job-fixture"):
    raw = ack() if raw is None else raw
    return call(store, "adopt", job, at=at, owner=owner, fence=fence, receipt_sha256=digest(raw))


def dispatch(store, inputs):
    pair = ready(store, inputs)
    acquire(store)
    return pair, begin(store, pair)


def process_call(path, action, payload, barrier, results):
    try:
        barrier.wait(timeout=15)
        results.put(SQLiteAuthority(path).batch_work(action, payload, now=NOW))
    except worker.BatchWorkerError as exc:
        results.put(dict(denied=str(exc)))
    except BaseException as exc:
        results.put(dict(worker_error=repr(exc)))


def parallel(store, action, payloads):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(len(payloads)), ctx.Queue()
    children = [
        ctx.Process(target=process_call, args=(store.path, action, p, barrier, results))
        for p in payloads
    ]
    for child in children:
        child.start()
    values = [results.get(timeout=30) for _ in children]
    for child in children:
        child.join(timeout=15)
        assert not child.is_alive() and child.exitcode == 0
    assert not [value for value in values if "worker_error" in value]
    return values


def die(path, payload, after_commit):
    callback = None if after_commit else lambda: os._exit(23)
    SQLiteAuthority(path).batch_work("begin", payload, now=NOW, before_commit=callback)
    os._exit(24)


def test_lease_then_single_dispatch_preserves_original_state_and_artifacts(store, inputs):
    pair = ready(store, inputs)
    state = store.read()
    domain = store.domain_status(verify=True)
    lease = acquire(store)
    assert lease["lease"]["fence"] == 1 and lease["lease_active"]
    assert lease["lease"]["expires_at"] == "2026-09-29T12:05:00.000000Z"
    assert not lease["dispatch_granted"] and not lease["collection_granted"]
    grant = begin(store, pair)
    assert grant["state"] == "submitting" and grant["dispatch_granted"]
    assert grant["reservation_state"] == "dispatched"
    again = begin(SQLiteAuthority(store.path), pair)
    assert again["grant_id"] == grant["grant_id"] and not again["dispatch_granted"]
    assert not call(store, "status")["dispatch_granted"]
    assert not grant["publication_approved"] and not grant["accounting_complete"]
    assert store.read() == state and store.domain_status(verify=True) == domain


def test_same_owner_reuses_active_lease_without_silent_extension(store, inputs):
    ready(store, inputs)
    first = acquire(store, ttl=60)
    again = acquire(store, ttl=300, at=later(20))
    assert again["lease"] == first["lease"] and again["reused"]
    with pytest.raises(worker.BatchWorkerError, match="busy"):
        acquire(store, owner="competitor", at=later(30))


def test_lease_expiry_equality_fences_stale_worker(store, inputs):
    pair = ready(store, inputs)
    acquire(store, ttl=60)
    with pytest.raises(worker.BatchWorkerError, match="expired"):
        begin(store, pair, at=later(60))
    assert acquire(store, owner="new-worker", at=later(60))["lease"]["fence"] == 2
    with pytest.raises(worker.BatchWorkerError, match="stale"):
        begin(store, pair, at=later(60))
    assert begin(store, pair, owner="new-worker", fence=2, at=later(60))["dispatch_granted"]


@pytest.mark.parametrize("ttl", [0, -1, 301, True, 1.2, None, "60"])
def test_invalid_lease_ttl_cannot_write(store, inputs, ttl):
    ready(store, inputs)
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="ttl"):
        acquire(store, ttl=ttl)
    assert snapshot(store) == before


@pytest.mark.parametrize("fence", [0, -1, True, 1.0, "1"])
def test_fence_types_are_not_coerced(store, inputs, fence):
    pair = ready(store, inputs)
    acquire(store)
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="fence"):
        begin(store, pair, fence=fence)
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "key", ["bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"]
)
def test_changed_authoritative_context_cannot_dispatch(store, inputs, key):
    pair = ready(store, inputs)
    acquire(store)
    changed = context(pair[0])
    changed[key] = "changed"
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="changed_batch_context"):
        call(store, "begin", owner="worker-one", fence=1, current_context=changed)
    assert snapshot(store) == before


@pytest.mark.parametrize("seconds", [23 * 3600, 24 * 3600, 25 * 3600])
def test_usefulness_window_equality_and_expiry_cannot_dispatch(store, inputs, seconds):
    pair = ready(store, inputs)
    acquire(store, at=later(seconds))
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="outside_window"):
        begin(store, pair, at=later(seconds))
    assert snapshot(store) == before


def test_external_spend_dispatch_cannot_become_batch_dispatch(store, inputs):
    pair = ready(store, inputs)
    store.spending("dispatch", dict(intent_id="attempt-1"), now=NOW)
    acquire(store)
    with pytest.raises(worker.BatchWorkerError, match="not_available"):
        begin(store, pair)
    assert call(store, "status")["state"] == "reservation_dispatched"


def test_reacquired_lost_response_never_grants_again_and_keeps_unknown_hold(store, inputs):
    pair, grant = dispatch(store, inputs)
    at = later(300)
    report = acquire(SQLiteAuthority(store.path), owner="replacement", at=at)
    assert report["state"] == "submission_uncertain" and report["reservation_state"] == "uncertain"
    replay = begin(store, pair, owner="replacement", fence=2, at=at)
    assert replay["grant_id"] == grant["grant_id"] and not replay["dispatch_granted"]
    assert (
        store.spending("status", {}, now="2027-01-01T00:00:00Z")["totals"]["held_micro_usd"] == 60
    )


def test_current_owner_can_mark_uncertainty_idempotently_without_releasing_money(store, inputs):
    dispatch(store, inputs)
    report = call(store, "uncertain", owner="worker-one", fence=1)
    before = snapshot(store)
    again = call(store, "uncertain", owner="worker-one", fence=1)
    assert report["state"] == again["state"] == "submission_uncertain"
    assert snapshot(store) == before
    assert store.spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 60


def test_late_ack_is_evidence_only_until_current_owner_adopts(store, inputs):
    _, grant = dispatch(store, inputs)
    acquire(store, owner="new-worker", at=later(300))
    report = observe(store, grant, at=later(301))
    assert report["state"] == "submission_uncertain" and report["provider_batch_id"] is None
    assert store.read_artifact(digest(ack())) == ack()
    with pytest.raises(worker.BatchWorkerError, match="stale"):
        adopt(store, at=later(301))
    accepted = adopt(store, owner="new-worker", fence=2, at=later(301))
    assert accepted["state"] == "submitted" and accepted["provider_batch_id"] == "msgbatch_fixture"
    assert accepted["reservation_state"] == "uncertain" and not accepted["dispatch_granted"]
    assert not accepted["publication_approved"] and not accepted["collection_granted"]


def test_duplicate_ack_and_adoption_are_idempotent(store, inputs):
    _, grant = dispatch(store, inputs)
    observe(store, grant)
    adopt(store)
    before = snapshot(store)
    assert observe(store, grant)["reused"] and adopt(store)["reused"]
    assert snapshot(store) == before


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"\xff",
        b"null",
        b'{"id":1,"id":2}',
        ack(type="other"),
        ack(identity="https://untrusted.invalid/"),
        ack(processing_status="complete"),
        ack(request_counts={}),
        ack(request_counts=dict(processing=True, succeeded=0, canceled=0, expired=0, errored=0)),
        ack(request_counts=dict(processing=2, succeeded=0, canceled=0, expired=0, errored=0)),
        ack(processing_status="ended"),
        ack(extra=float("nan")),
    ],
)
def test_invalid_ack_is_retained_but_cannot_be_adopted(store, inputs, raw):
    _, grant = dispatch(store, inputs)
    observed = observe(store, grant, raw)
    assert observed["invalid_receipt_count"] == 1 and store.read_artifact(digest(raw)) == raw
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="invalid_or_missing"):
        adopt(store, raw)
    assert snapshot(store) == before and not observed["dispatch_granted"]


def test_conflicting_provider_ids_block_adoption_even_after_initial_acceptance(store, inputs):
    _, grant = dispatch(store, inputs)
    observe(store, grant)
    adopt(store)
    report = observe(store, grant, ack("msgbatch_conflict"))
    assert report["state"] == "acknowledgment_conflict" and report["provider_batch_id"] is None
    with pytest.raises(worker.BatchWorkerError, match="conflicting"):
        adopt(store)


def test_shared_provider_id_across_jobs_blocks_both(store, inputs):
    grants = []
    for job in ("one", "two"):
        pair = ready(store, inputs, job=job, identity=job, amount=30)
        acquire(store, job)
        grants.append(begin(store, pair))
    observe(store, grants[0])
    adopt(store, job="one")
    observe(store, grants[1])
    for job in ("one", "two"):
        assert call(store, "status", job)["state"] == "acknowledgment_conflict"
        with pytest.raises(worker.BatchWorkerError, match="conflicting"):
            adopt(store, job=job)


@pytest.mark.parametrize("bad", ["unknown_grant", "wrong_sha", "oversized", "nonbytes"])
def test_invalid_ack_envelope_cannot_add_artifact(store, inputs, bad):
    _, grant = dispatch(store, inputs)
    raw = ack()
    sha, identity = digest(raw), grant["grant_id"]
    if bad == "unknown_grant":
        identity = "f" * 64
    elif bad == "wrong_sha":
        sha = "f" * 64
    elif bad == "oversized":
        raw = b"a" * 65537
        sha = digest(raw)
    else:
        raw = bytearray(raw)
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError):
        call(store, "observe_ack", raw=raw, grant_id=identity, receipt_sha256=sha)
    assert snapshot(store) == before


def test_real_processes_compete_for_one_active_lease(store, inputs):
    ready(store, inputs)
    values = parallel(
        store,
        "acquire",
        [dict(job_id="job-fixture", owner=owner, ttl_seconds=300) for owner in ("one", "two")],
    )
    assert sum("denied" in row for row in values) == 1
    assert call(store, "status")["lease"]["fence"] == 1


def test_real_processes_get_only_one_dispatch_grant(store, inputs):
    pair = ready(store, inputs)
    acquire(store)
    payload = dict(
        job_id="job-fixture", owner="worker-one", fence=1, current_context=context(pair[0])
    )
    values = parallel(store, "begin", [payload] * 2)
    assert sum(row["dispatch_granted"] for row in values) == 1
    assert store.spending("status", {}, now=NOW)["intent_count"] == 1


@pytest.mark.parametrize("after_commit", [False, True])
def test_process_death_on_each_side_of_commit_never_duplicates_grant(store, inputs, after_commit):
    pair = ready(store, inputs)
    acquire(store)
    before = snapshot(store)
    payload = dict(
        job_id="job-fixture", owner="worker-one", fence=1, current_context=context(pair[0])
    )
    child = multiprocessing.get_context("spawn").Process(
        target=die, args=(store.path, payload, after_commit)
    )
    child.start()
    child.join(timeout=20)
    assert not child.is_alive() and child.exitcode == (24 if after_commit else 23)
    if not after_commit:
        assert snapshot(store) == before
    retry = begin(SQLiteAuthority(store.path), pair)
    assert retry["dispatch_granted"] is (not after_commit)


def test_begin_transaction_rolls_back_dispatch_when_submission_insert_fails(store, inputs):
    pair = ready(store, inputs)
    acquire(store)
    with closing(store._connect()) as connection:
        connection.execute(
            "CREATE TRIGGER fail_submission BEFORE INSERT ON batch_worker_submissions BEGIN SELECT RAISE(ABORT,'fault fixture'); END"
        )
    before = snapshot(store)
    with pytest.raises(sqlite3.IntegrityError, match="fault fixture"):
        begin(store, pair)
    assert snapshot(store) == before


def test_backup_restore_preserves_fences_receipts_and_unknown_money(store, inputs, tmp_path):
    pair, grant = dispatch(store, inputs)
    call(store, "uncertain", owner="worker-one", fence=1)
    observe(store, grant)
    backup = tmp_path / "backup.sqlite"
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    assert call(restored, "status") == call(store, "status")
    assert restored.read_artifact(digest(ack())) == ack()
    assert not begin(restored, pair)["dispatch_granted"]
    assert adopt(restored)["state"] == "submitted"
    assert restored.spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 60


def test_worker_clock_regression_cannot_mutate(store, inputs):
    ready(store, inputs)
    acquire(store, at=later(30))
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="clock"):
        acquire(store, at=later(29))
    assert snapshot(store) == before


def test_receipt_and_lease_capacity_preserve_existing_reuse(store, inputs, monkeypatch):
    _, grant = dispatch(store, inputs)
    monkeypatch.setattr(worker, "MAX_RECEIPTS", 1)
    observe(store, grant)
    assert observe(store, grant)["reused"]
    with pytest.raises(worker.BatchWorkerError, match="capacity"):
        observe(store, grant, ack("msgbatch_second"))
    monkeypatch.setattr(worker, "MAX_LEASES", 1)
    assert acquire(store)["reused"]
    with pytest.raises(worker.BatchWorkerError, match="capacity"):
        acquire(store, at=later(300))


def test_changed_grant_refused_even_after_schema_guard_restored(store, inputs):
    dispatch(store, inputs)
    with closing(store._connect()) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='batch_worker_submissions_no_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER batch_worker_submissions_no_update")
        connection.execute("UPDATE batch_worker_submissions SET grant_id=?", ("f" * 64,))
        connection.execute(sql)
    with pytest.raises(worker.BatchWorkerError, match="changed_batch_grant"):
        call(store, "status")


@pytest.mark.parametrize("table", list(worker._TABLES))
def test_missing_immutable_guard_blocks_operations(store, inputs, table):
    ready(store, inputs)
    with closing(store._connect()) as connection:
        connection.execute(f"DROP TRIGGER {table}_no_replace")
    before = snapshot(store)
    with pytest.raises(worker.BatchWorkerError, match="schema"):
        acquire(store)
    assert snapshot(store) == before


def test_explicit_worker_schema_migration_preserves_registrations_and_holds(store, inputs):
    pair = ready(store, inputs)
    before_state, before_domain = store.read(), store.domain_status(verify=True)
    with closing(store._connect()) as connection:
        for table in reversed(worker._TABLES):
            connection.execute("DROP TABLE " + table)
    with pytest.raises(worker.BatchWorkerError, match="migration_required"):
        acquire(store)
    store.initialize(before_state[1])
    assert store.read() == before_state and store.domain_status(verify=True) == before_domain
    assert store.read_artifact(digest(pair[0])) == pair[0]
    assert acquire(store)["state"] == "reserved"


def test_reconciled_overrun_blocks_existing_worker_hold_before_dispatch(store, inputs):
    from src.commands.spend_journal import SpendError

    pair = ready(store, inputs)
    acquire(store)
    other = packet(inputs, job="other", identity="other", amount=30)[1]
    store.spending("reserve", other, now=NOW)
    store.spending("dispatch", {"intent_id": "other"}, now=NOW)
    store.spending(
        "settle", dict(intent_id="other", amount_micro_usd=40, evidence_sha256="a" * 64), now=NOW
    )
    before = snapshot(store)
    with pytest.raises(SpendError, match="overrun"):
        begin(store, pair)
    assert snapshot(store) == before
    assert call(store, "status")["grant_id"] is None
