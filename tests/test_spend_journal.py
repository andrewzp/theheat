"""Local money bounds at real SQLite transaction/process boundaries, no paid calls."""

from contextlib import closing
from copy import deepcopy
import multiprocessing
import os
import sqlite3

import pytest

from src.commands.schema import CommandError
from src.commands.domain_journal import DomainJournalError
from src.commands.sqlite_authority import SQLiteAuthority
from src.commands.spend_journal import SpendError
from tests.test_command_authority import story

NOW = "2026-09-29T12:00:00Z"
LATER = "2026-10-01T12:00:00Z"
LIMITS = {
    "daily_micro_usd": 100,
    "monthly_micro_usd": 150,
    "per_job_micro_usd": 90,
    "authorization_sha256": "a" * 64,
}


def intent(identity="attempt-1", amount=60, job="job-1", role="writer"):
    return {
        "intent_id": identity,
        "job_id": job,
        "request_sha256": "b" * 64,
        "provider": "anthropic",
        "model": "claude-synthetic",
        "role": role,
        "estimate_sha256": "c" * 64,
        "reserve_micro_usd": amount,
    }


@pytest.fixture
def store(tmp_path):
    value = SQLiteAuthority(tmp_path / "authority.sqlite")
    value.initialize({"drafts": [story()]})
    value.spending("configure", LIMITS, now=NOW)
    return value


def call(store, action, value=None, *, at=NOW):
    return store.spending(action, {"intent_id": "attempt-1"} if value is None else value, now=at)


def settle(store, amount=40, *, at=NOW, identity="attempt-1", evidence="d" * 64):
    return call(
        store,
        "settle",
        {"intent_id": identity, "amount_micro_usd": amount, "evidence_sha256": evidence},
        at=at,
    )


def worker(path, action, payload, barrier, results):
    try:
        barrier.wait(timeout=15)
        results.put(SQLiteAuthority(path).spending(action, payload, now=NOW))
    except SpendError as error:
        results.put({"denied": str(error)})
    except BaseException as error:
        results.put({"worker_error": repr(error)})


def parallel(store, action, payloads):
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(len(payloads)), ctx.Queue()
    children = [
        ctx.Process(target=worker, args=(store.path, action, p, barrier, results)) for p in payloads
    ]
    for child in children:
        child.start()
    values = [results.get(timeout=30) for _ in children]
    for child in children:
        child.join(timeout=15)
        assert not child.is_alive() and child.exitcode == 0
    assert not [value for value in values if "worker_error" in value]
    return values


def die_before_commit(path):
    SQLiteAuthority(path).spending("reserve", intent(), now=NOW, before_commit=lambda: os._exit(23))


def test_concurrent_reservers_share_one_real_allowance(store):
    results = parallel(store, "reserve", [intent(), intent("attempt-2", job="other-job")])
    assert sum("denied" in row for row in results) == 1
    assert call(store, "status", {})["totals"]["held_micro_usd"] == 60


def test_only_one_dispatch_grant_survives_concurrency_and_restart(store):
    call(store, "reserve", intent())
    results = parallel(store, "dispatch", [{"intent_id": "attempt-1"}] * 2)
    assert sum(row["dispatch_granted"] for row in results) == 1
    reopened = SQLiteAuthority(store.path)
    assert not call(reopened, "dispatch")["dispatch_granted"]
    assert call(reopened, "status")["totals"]["held_micro_usd"] == 60


def test_reservation_replay_and_changed_intent_conflict(store):
    first = call(store, "reserve", intent())
    replay = call(store, "reserve", intent())
    assert not first["reused"] and replay["reused"] and not replay["dispatch_granted"]
    changed = intent(amount=61)
    with pytest.raises(SpendError, match="id_reused"):
        call(store, "reserve", changed)
    assert call(store, "status")["totals"]["held_micro_usd"] == 60


@pytest.mark.parametrize("role", ["writer", "safety", "fact_check", "critic", "news", "repair"])
def test_all_supported_roles_share_daily_and_per_job_allowances(store, role):
    call(store, "reserve", intent(amount=60))
    with pytest.raises(SpendError, match="allowance"):
        call(store, "reserve", intent("attempt-2", amount=41, job="other", role=role))
    with pytest.raises(SpendError, match="allowance"):
        call(store, "reserve", intent("attempt-2", amount=31, role=role))
    call(store, "reserve", intent("attempt-2", amount=30, role=role))


def test_uncertain_holds_carry_across_day_and_month_indefinitely(store):
    call(store, "reserve", intent())
    call(store, "dispatch")
    call(store, "uncertain")
    call(store, "uncertain", at=LATER)
    for at in (LATER, "2027-10-01T12:00:00Z"):
        assert call(store, "status", at=at)["totals"]["held_micro_usd"] == 60
        with pytest.raises(SpendError, match="allowance"):
            call(store, "reserve", intent("another", 41, "another"), at=at)
        with pytest.raises(SpendError, match="cannot_release"):
            call(store, "release", at=at)


def test_only_never_dispatched_reservations_can_be_released(store):
    call(store, "reserve", intent())
    call(store, "release")
    assert call(store, "release")["intent"]["state"] == "released"
    assert call(store, "status")["totals"]["held_micro_usd"] == 0
    assert not call(store, "dispatch")["dispatch_granted"]
    assert call(store, "reserve", intent())["reused"]
    call(store, "reserve", intent("second"))
    assert call(store, "dispatch", {"intent_id": "second"})["dispatch_granted"]
    with pytest.raises(SpendError, match="cannot_release"):
        call(store, "release", {"intent_id": "second"})


def test_settlement_is_idempotent_but_not_an_unknown_charge_as_zero(store):
    call(store, "reserve", intent())
    with pytest.raises(SpendError, match="not_dispatched"):
        settle(store)
    call(store, "dispatch")
    with pytest.raises(SpendError, match="invalid_micro"):
        settle(store, None)
    assert call(store, "status")["totals"]["held_micro_usd"] == 60
    assert settle(store)["intent"]["settled_micro_usd"] == 40
    settle(store)
    with pytest.raises(SpendError, match="conflicting"):
        settle(store, 41)
    assert call(store, "status")["totals"]["daily_micro_usd"] == 40
    assert call(store, "status")["totals"]["held_micro_usd"] == 0


def test_monthly_and_job_limits_do_not_reset_on_new_day(store):
    call(store, "reserve", intent(amount=90))
    call(store, "dispatch")
    settle(store, 90)
    tomorrow = "2026-09-30T12:00:00Z"
    with pytest.raises(SpendError, match="allowance"):
        call(store, "reserve", intent("other", amount=61, job="other"), at=tomorrow)
    with pytest.raises(SpendError, match="allowance"):
        call(store, "reserve", intent("other", amount=1), at=tomorrow)
    call(store, "reserve", intent("other", amount=60, job="other"), at=tomorrow)


def test_settlement_counts_conservatively_in_its_new_window(store):
    call(store, "reserve", intent())
    call(store, "dispatch")
    settle(store, at=LATER)
    totals = call(store, "status", at=LATER)["totals"]
    assert totals["daily_micro_usd"] == totals["monthly_micro_usd"] == 40
    assert totals["held_micro_usd"] == 0


def test_overrun_is_recorded_and_blocks_new_reservations_and_old_dispatches(store):
    call(store, "reserve", intent(amount=40))
    call(store, "reserve", intent("other", 30, "other"))
    call(store, "dispatch")
    result = settle(store, 101)
    assert result["intent"]["settled_micro_usd"] == 101
    assert result["totals"]["overrun_count"] == 1
    with pytest.raises(SpendError, match="overrun"):
        call(store, "reserve", intent("third", 1, "third"))
    with pytest.raises(SpendError, match="overrun"):
        call(store, "dispatch", {"intent_id": "other"})


@pytest.mark.parametrize("amount", [True, False, None, -1, 0, 1.5, 10**12 + 1, "60"])
def test_reservation_amounts_are_strict_positive_micro_usd(store, amount):
    with pytest.raises(SpendError):
        call(store, "reserve", intent(amount=amount))


@pytest.mark.parametrize(
    "field,value",
    [
        ("intent_id", ""),
        ("job_id", "x" * 161),
        ("model", "secret bad\nmodel"),
        ("provider", "other"),
        ("role", "free"),
        ("request_sha256", "bad"),
        ("estimate_sha256", "bad"),
    ],
)
def test_unknown_or_unbound_intents_refused(store, field, value):
    payload = intent()
    payload[field] = value
    with pytest.raises(SpendError):
        call(store, "reserve", payload)


def test_clock_is_monotonic_at_subsecond_precision(store):
    call(store, "reserve", intent(), at="2026-09-29T12:00:00.1Z")
    with pytest.raises(SpendError, match="backwards"):
        call(store, "dispatch", at="2026-09-29T12:00:00.05Z")
    assert call(store, "dispatch", at="2026-09-29T12:00:00.100001Z")["dispatch_granted"]


def test_limits_are_explicit_immutable_and_zero_disables(tmp_path):
    store = SQLiteAuthority(tmp_path / "authority.sqlite")
    store.initialize({})
    with pytest.raises(SpendError, match="not_configured"):
        call(store, "reserve", intent())
    limits = {**LIMITS, "daily_micro_usd": 0}
    call(store, "configure", limits)
    call(store, "configure", limits)
    with pytest.raises(SpendError, match="immutable"):
        call(store, "configure", LIMITS)
    with pytest.raises(SpendError, match="allowance"):
        call(store, "reserve", intent(amount=1))
    store.initialize({})
    assert store.spending("status", {}, now=NOW)["limits"] == limits


def test_spending_leaves_drafts_and_domain_evidence_unchanged(store):
    state, evidence = store.read(), store.domain_status(verify=True)
    call(store, "reserve", intent())
    call(store, "dispatch")
    call(store, "uncertain")
    settle(store)
    assert store.read() == state and store.domain_status(verify=True) == evidence


@pytest.mark.parametrize(
    "action,payload",
    [
        ("reserve", intent()),
        ("dispatch", {"intent_id": "attempt-1"}),
        ("settle", {"intent_id": "attempt-1", "amount_micro_usd": 40, "evidence_sha256": "d" * 64}),
    ],
)
def test_all_writes_roll_back_if_commit_boundary_fails(store, action, payload):
    if action != "reserve":
        call(store, "reserve", intent())
    if action == "settle":
        call(store, "dispatch")
    before = store.spending("status", {}, now=NOW)

    def fail():
        raise RuntimeError("fixture before commit")

    with pytest.raises(RuntimeError, match="fixture"):
        store.spending(action, payload, now=NOW, before_commit=fail)
    assert store.spending("status", {}, now=NOW) == before


def test_process_death_rolls_back_reservation(store):
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=die_before_commit, args=(store.path,))
    child.start()
    child.join(timeout=15)
    assert not child.is_alive() and child.exitcode == 23
    assert store.spending("status", {}, now=NOW)["intent_count"] == 0
    assert not call(store, "reserve", intent())["reused"]


def test_backup_restore_preserves_holds_and_dispatch_fence(store, tmp_path):
    call(store, "reserve", intent())
    call(store, "dispatch")
    call(store, "uncertain")
    backup = tmp_path / "backup.sqlite"
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    assert call(restored, "status") == call(store, "status")
    assert not call(restored, "dispatch")["dispatch_granted"]
    assert restored.domain_status(verify=True) == store.domain_status(verify=True)


def test_schema_guard_changes_refused(store):
    with closing(store._connect()) as connection:
        connection.execute("DROP TRIGGER spend_intents_no_delete")
    with pytest.raises(SpendError, match="changed_spend_schema"):
        call(store, "reserve", intent())


def test_immutable_journal_rejects_update_delete_and_replace(store):
    call(store, "reserve", intent())
    with closing(store._connect()) as connection:
        for sql in (
            "DELETE FROM spend_intents",
            "UPDATE spend_intents SET recorded_at='changed'",
            "INSERT OR REPLACE INTO spend_intents SELECT * FROM spend_intents",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)


def test_production_adapter_and_wrong_database_are_refused(tmp_path):
    with pytest.raises(CommandError):
        SQLiteAuthority(tmp_path / "prod.sqlite", environment="production")
    path = tmp_path / "wrong.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE unrelated(id)")
    with pytest.raises(DomainJournalError):
        SQLiteAuthority(path).initialize({})
