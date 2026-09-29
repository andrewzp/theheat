"""Actual SQLite atomicity for local immutable batch requests and spending holds."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import batch_journal, domain_journal
from src.commands.batch_journal import BatchJournalError
from src.commands.schema import CommandError
from src.commands.spend_journal import SpendError
from src.commands.sqlite_authority import SQLiteAuthority
from src.two_bot.batch_contract import BatchContractError, prepare_batch_plan, validated_batch_plan
from tests import test_spend_journal as spend_fixtures
from tests.two_bot import test_batch_contract as batch_fixtures

NOW, LATER = spend_fixtures.NOW, spend_fixtures.LATER
store = spend_fixtures.store
inputs = batch_fixtures.inputs


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def packet(inputs, *, job=None, identity=None, amount=60):
    value = deepcopy(inputs)
    if job:
        value['job_id'] = job
    raw = prepare_batch_plan(**value)
    reservation = dict(intent_id=identity or 'attempt-1', job_id=value['job_id'],
        request_sha256=digest(raw), provider='anthropic', role='writer', model='claude-synthetic',
        estimate_sha256='d' * 64, reserve_micro_usd=amount)
    return raw, reservation


def register(store, pair, *, at=NOW, **kwargs):
    raw, reservation = pair
    return store.prepare_batch(raw, expected_plan_sha256=digest(raw), reservation=reservation, now=at, **kwargs)


def snapshot(store):
    with closing(store._connect()) as connection:
        return tuple(connection.iterdump())


def worker(path, pair, barrier, results):
    try:
        barrier.wait(timeout=15)
        results.put(register(SQLiteAuthority(path), pair))
    except (BatchJournalError, SpendError) as exc:
        results.put(dict(denied=str(exc)))
    except BaseException as exc:
        results.put(dict(worker_error=repr(exc)))


def parallel(store, pairs):
    ctx = multiprocessing.get_context('spawn')
    barrier, results = ctx.Barrier(len(pairs)), ctx.Queue()
    children = [ctx.Process(target=worker, args=(store.path, pair, barrier, results)) for pair in pairs]
    for child in children:
        child.start()
    values = [results.get(timeout=30) for _ in children]
    for child in children:
        child.join(timeout=15)
        assert not child.is_alive() and child.exitcode == 0
    assert not [value for value in values if 'worker_error' in value]
    return values


def die_before_commit(path, pair):
    register(SQLiteAuthority(path), pair, before_commit=lambda: os._exit(23))


def test_exact_plan_job_hold_commit_without_state_mutation(store, inputs):
    pair = packet(inputs)
    state = store.read()
    before = store.domain_status(verify=True)
    row = register(store, pair)
    assert row == dict(job_id=inputs['job_id'], plan_sha256=digest(pair[0]), intent_id='attempt-1',
        registered_at='2026-09-29T12:00:00.000000Z', useful_until=inputs['useful_until'],
        reservation_state='reserved', dispatch_granted=False, publication_approved=False, reused=False)
    assert store.read_artifact(row['plan_sha256']) == pair[0]
    assert store.read() == state
    assert store.domain_status(verify=True)['counts']['domain_artifacts'] == before['counts']['domain_artifacts'] + 1
    assert store.spending('status', {}, now=NOW)['totals']['held_micro_usd'] == 60
    # Status contains no request prompt, evidence or model output.
    assert set(store.batch_status(inputs['job_id'])) == set(row) - {'reused'}


def test_validated_reader_returns_detached_complete_plan(inputs):
    raw, _ = packet(inputs)
    plan = validated_batch_plan(raw, expected_plan_sha256=digest(raw))
    plan['requests'][0]['params'].clear()
    assert validated_batch_plan(raw, expected_plan_sha256=digest(raw))['requests'][0]['params']


def test_exact_replay_after_expiry_retains_actual_reservation_disposition(store, inputs):
    pair = packet(inputs)
    register(store, pair)
    store.spending('dispatch', {'intent_id': 'attempt-1'}, now=NOW)
    store.spending('uncertain', {'intent_id': 'attempt-1'}, now=NOW)
    before = snapshot(store)
    row = register(SQLiteAuthority(store.path), pair, at=LATER)
    assert row['reused'] and row['reservation_state'] == 'uncertain'
    assert row['dispatch_granted'] is False and snapshot(store) == before


@pytest.mark.parametrize('field,value', [
    ('job_id', 'other-job'), ('request_sha256', 'b' * 64), ('provider', 'google'),
    ('role', 'critic'), ('model', 'claude-other'), ('reserve_micro_usd', True),
    ('reserve_micro_usd', 0), ('estimate_sha256', ''), ('intent_id', []),
])
def test_mismatched_or_invalid_reservation_cannot_write(store, inputs, field, value):
    raw, reservation = packet(inputs)
    reservation[field] = value
    before = snapshot(store)
    with pytest.raises((BatchJournalError, SpendError)):
        register(store, (raw, reservation))
    assert snapshot(store) == before


@pytest.mark.parametrize('field,value', [('reserve_micro_usd', 61), ('estimate_sha256', 'a' * 64), ('intent_id', 'attempt-other')])
def test_existing_registration_cannot_change_reservation(store, inputs, field, value):
    raw, reservation = packet(inputs)
    register(store, (raw, reservation))
    reservation[field] = value
    before = snapshot(store)
    with pytest.raises(BatchJournalError):
        register(store, (raw, reservation))
    assert snapshot(store) == before


def test_same_job_cannot_replace_plan_even_with_new_valid_hash(store, inputs):
    register(store, packet(inputs))
    inputs['publication_epoch'] = 'another-paused-epoch'
    before = snapshot(store)
    with pytest.raises(BatchJournalError, match='job_id_reused'):
        register(store, packet(inputs))
    assert snapshot(store) == before


def test_registered_intent_cannot_bind_another_job(store, inputs):
    register(store, packet(inputs))
    before = snapshot(store)
    with pytest.raises(BatchJournalError, match='identity_reused'):
        register(store, packet(inputs, job='other-job'))
    assert snapshot(store) == before


@pytest.mark.parametrize('at', ['2026-09-29T11:59:59Z', '2026-09-30T11:00:00Z', '2026-09-30T12:00:00Z', LATER])
def test_expired_or_insufficient_window_leaves_no_orphans(store, inputs, at):
    before = snapshot(store)
    with pytest.raises(BatchJournalError, match='outside_window'):
        register(store, packet(inputs), at=at)
    assert snapshot(store) == before


def test_one_microsecond_more_than_required_window_is_valid(store, inputs):
    assert register(store, packet(inputs), at='2026-09-30T10:59:59.999999Z')['reservation_state'] == 'reserved'


@pytest.mark.parametrize('variant', ['hash', 'oversized', 'duplicate', 'malformed', 'nonbytes', 'reencoded'])
def test_invalid_plan_refuses_before_writes(store, inputs, variant):
    raw, reservation = packet(inputs)
    expected = digest(raw)
    if variant == 'hash':
        expected = 'f' * 64
    elif variant == 'oversized':
        raw = b' ' * 2_000_001
    elif variant == 'duplicate':
        raw = b'{"job_id":"one","job_id":"two"}'
    elif variant == 'malformed':
        raw = b'\xff'
    elif variant == 'nonbytes':
        raw = bytearray(raw)
    else:
        raw = json.dumps(json.loads(raw), indent=2).encode()
        expected = digest(raw)
    before = snapshot(store)
    with pytest.raises(BatchContractError):
        store.prepare_batch(raw, expected_plan_sha256=expected, reservation=reservation, now=NOW)
    assert snapshot(store) == before


@pytest.mark.parametrize('state', ['reserved', 'dispatched', 'uncertain', 'settled', 'released'])
def test_only_exact_unused_external_reservation_can_join(store, inputs, state):
    pair = packet(inputs)
    store.spending('reserve', pair[1], now=NOW)
    if state in ('dispatched', 'uncertain', 'settled'):
        store.spending('dispatch', {'intent_id': 'attempt-1'}, now=NOW)
    if state == 'uncertain':
        store.spending('uncertain', {'intent_id': 'attempt-1'}, now=NOW)
    if state == 'settled':
        store.spending('settle', dict(intent_id='attempt-1', amount_micro_usd=40, evidence_sha256='a' * 64), now=NOW)
    if state == 'released':
        store.spending('release', {'intent_id': 'attempt-1'}, now=NOW)
    before = snapshot(store)
    if state == 'reserved':
        assert register(store, pair)['reservation_state'] == 'reserved'
        assert store.spending('status', {}, now=NOW)['intent_count'] == 1
    else:
        with pytest.raises(BatchJournalError, match='already_used'):
            register(store, pair)
        assert snapshot(store) == before


def test_changed_external_reservation_stays_intact(store, inputs):
    raw, reservation = packet(inputs)
    changed = dict(reservation, reserve_micro_usd=61)
    store.spending('reserve', changed, now=NOW)
    before = snapshot(store)
    with pytest.raises(SpendError, match='id_reused'):
        register(store, (raw, reservation))
    assert snapshot(store) == before


def test_failed_insert_rolls_back_new_hold_and_artifact(store, inputs):
    with closing(store._connect()) as connection:
        connection.execute("CREATE TRIGGER reject_job BEFORE INSERT ON batch_jobs BEGIN SELECT RAISE(ABORT,'fault fixture'); END")
    before = snapshot(store)
    with pytest.raises(sqlite3.IntegrityError, match='fault fixture'):
        register(store, packet(inputs))
    assert snapshot(store) == before


def test_exception_before_commit_rolls_back_all_three_writes(store, inputs):
    before = snapshot(store)
    def fail():
        raise RuntimeError('injected crash')
    with pytest.raises(RuntimeError, match='injected crash'):
        register(store, packet(inputs), before_commit=fail)
    assert snapshot(store) == before
    assert register(store, packet(inputs))['reservation_state'] == 'reserved'


def test_process_death_releases_transaction_without_orphans(store, inputs):
    before = snapshot(store)
    ctx = multiprocessing.get_context('spawn')
    child = ctx.Process(target=die_before_commit, args=(store.path, packet(inputs)))
    child.start()
    child.join(timeout=20)
    assert not child.is_alive() and child.exitcode == 23
    assert snapshot(SQLiteAuthority(store.path)) == before
    assert not register(store, packet(inputs))['reused']


def test_concurrent_identical_workers_commit_one_job_and_hold(store, inputs):
    values = parallel(store, [packet(inputs)] * 2)
    assert sorted(row['reused'] for row in values) == [False, True]
    assert all(not row['dispatch_granted'] for row in values)
    assert store.spending('status', {}, now=NOW)['intent_count'] == 1
    with closing(store._connect()) as connection:
        assert connection.execute('SELECT COUNT(*) FROM batch_jobs').fetchone()[0] == 1


def test_concurrent_jobs_near_cap_have_no_orphan_plan_or_hold(store, inputs):
    before = store.domain_status(verify=True)['counts']['domain_artifacts']
    pairs = [packet(inputs), packet(inputs, job='second-job', identity='second-attempt')]
    values = parallel(store, pairs)
    assert sum('denied' in row for row in values) == 1
    assert store.domain_status(verify=True)['counts']['domain_artifacts'] == before + 1
    assert store.spending('status', {}, now=NOW)['intent_count'] == 1
    winner = next(row for row in values if 'denied' not in row)
    assert store.read_artifact(winner['plan_sha256']) in [pair[0] for pair in pairs]


def test_capacity_refusal_does_not_prevent_existing_exact_retry(store, inputs, monkeypatch):
    register(store, packet(inputs))
    monkeypatch.setattr(batch_journal, 'MAX_JOBS', 1)
    assert register(store, packet(inputs))['reused']
    before = snapshot(store)
    with pytest.raises(BatchJournalError, match='capacity'):
        register(store, packet(inputs, job='second', identity='second'))
    assert snapshot(store) == before


def test_backup_restore_preserves_plan_hold_and_idempotency(store, inputs, tmp_path):
    pair = packet(inputs)
    register(store, pair)
    backup = tmp_path / 'backup.sqlite'
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    assert restored.batch_status(inputs['job_id']) == store.batch_status(inputs['job_id'])
    assert restored.read_artifact(digest(pair[0])) == pair[0]
    assert restored.read() == store.read()
    assert register(restored, pair)['reused']
    assert restored.spending('status', {}, now=NOW)['intent_count'] == 1


def test_registration_refuses_wrong_environment(store, inputs):
    before = snapshot(store)
    with pytest.raises(CommandError, match='environment'):
        register(SQLiteAuthority(store.path, environment='preview'), packet(inputs))
    assert snapshot(store) == before


@pytest.mark.parametrize('trigger', ['batch_jobs_no_update', 'batch_jobs_no_delete', 'batch_jobs_no_replace'])
def test_changed_schema_guards_fail_closed(store, inputs, trigger):
    with closing(store._connect()) as connection:
        connection.execute('DROP TRIGGER ' + trigger)
    before = snapshot(store)
    with pytest.raises(BatchJournalError, match='schema'):
        register(store, packet(inputs))
    assert snapshot(store) == before


def test_explicit_reinitialize_migrates_old_local_store_without_replacing_data(store, inputs):
    with closing(store._connect()) as connection:
        connection.execute('DROP TABLE batch_jobs')
        connection.execute('DROP TABLE batch_schema')
    state = store.read()
    domain = store.domain_status(verify=True)
    with pytest.raises(BatchJournalError, match='migration_required'):
        register(store, packet(inputs))
    store.initialize(state[1], source_namespace='local-fixtures')
    assert store.read() == state and store.domain_status(verify=True) == domain
    assert register(store, packet(inputs))['reservation_state'] == 'reserved'


def test_status_refuses_changed_plan_even_when_guard_is_restored(store, inputs):
    pair = packet(inputs)
    register(store, pair)
    with closing(store._connect()) as connection:
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='domain_artifacts_no_update'").fetchone()[0]
        connection.execute('DROP TRIGGER domain_artifacts_no_update')
        connection.execute('UPDATE domain_artifacts SET payload=?,byte_count=7 WHERE sha256=?', (b'changed', digest(pair[0])))
        connection.execute(sql)
    with pytest.raises(domain_journal.DomainJournalError, match='identity'):
        store.batch_status(inputs['job_id'])


def test_status_refuses_changed_join_even_when_guard_is_restored(store, inputs):
    pair = packet(inputs)
    register(store, pair)
    other = packet(inputs, job='other', identity='other')[1]
    other['reserve_micro_usd'] = 10
    store.spending('reserve', other, now=NOW)
    with closing(store._connect()) as connection:
        sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='batch_jobs_no_update'").fetchone()[0]
        connection.execute('DROP TRIGGER batch_jobs_no_update')
        connection.execute("UPDATE batch_jobs SET intent_id='other'")
        connection.execute(sql)
    with pytest.raises(BatchJournalError, match='binding_mismatch'):
        store.batch_status(inputs['job_id'])


@pytest.mark.parametrize('statement', [
    "UPDATE batch_jobs SET job_id='changed'", "DELETE FROM batch_jobs",
    "INSERT OR REPLACE INTO batch_jobs SELECT * FROM batch_jobs",
    "UPDATE batch_schema SET schema_sha256='changed'", "DELETE FROM batch_schema",
    "INSERT OR REPLACE INTO batch_schema SELECT * FROM batch_schema",
])
def test_sql_append_only_guards_prevent_overwrite(store, inputs, statement):
    register(store, packet(inputs))
    with closing(store._connect()) as connection, pytest.raises(sqlite3.IntegrityError, match='immutable'):
        connection.execute(statement)
