"""Exact check lifecycle with real transactions; model outcomes are offline fixtures."""

from contextlib import closing
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import check_journal as checks, domain_journal
from src.commands.sqlite_authority import SQLiteAuthority
from src.commands.spend_journal import SpendError
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.voice import safety
from tests import test_batch_result_journal as batches
from tests import test_batch_worker_journal as workers

store, inputs, NOW = batches.store, batches.inputs, batches.NOW


@pytest.fixture
def case(store, inputs, monkeypatch):
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    inputs["policy"] = current_editorial_policy()
    pair, grant = batches.started(store, inputs)
    receipt = batches.retain(store, grant, batches.contract.raw_rows(batches.rows(pair)))
    payload = dict(
        job_id=pair[1]["job_id"],
        owner="worker-one",
        fence=1,
        receipt_id=receipt["receipt_id"],
        current_context=batches.contract.context(pair[0]),
        custom_id=json.loads(pair[0])["requests"][0]["custom_id"],
        bundle=inputs["bundle"].to_dict(),
        memory=inputs["memory"].to_dict(),
        checker_state=deepcopy(store.read()[1]),
    )
    result = store.candidate_checks("intake", payload, now=NOW)
    identity = dict(
        check_set_id=result["check_set_id"],
        owner="worker-one",
        fence=1,
        current_context=payload["current_context"],
        checker_state_sha256=fingerprint(payload["checker_state"]),
    )
    return dict(
        store=store,
        pair=pair,
        grant=grant,
        receipt=receipt,
        payload=payload,
        identity=identity,
        result=result,
        policy=inputs["policy"],
    )


def start(case, stage="deterministic", *, at=NOW, before_commit=None, **changes):
    request = json.dumps(dict(identity=case["identity"]["check_set_id"], stage=stage)).encode()
    reservation = (
        None
        if stage == "deterministic"
        else dict(
            intent_id="check-" + stage,
            job_id=case["payload"]["job_id"],
            request_sha256=hashlib.sha256(request).hexdigest(),
            provider="google",
            role=stage,
            model=case["policy"]["models"][stage],
            estimate_sha256="d" * 64,
            reserve_micro_usd=5,
        )
    )
    payload = dict(case["identity"], stage=stage, reservation=reservation)
    payload.update(changes)
    grant = case["store"].candidate_checks(
        "begin", payload, request=request, now=at, before_commit=before_commit
    )
    return grant, request, payload


def finish(case, started, *, at=NOW, execution="completed", verdict="pass", **changes):
    grant, request, payload = started
    receipt = dict(
        grant_id=grant["grant_id"],
        request_sha256=hashlib.sha256(request).hexdigest(),
        execution_status=execution,
        verdict=verdict,
        result={"fixture_only": True},
        usage=None,
    )
    receipt.update(changes)
    identity = {k: payload[k] for k in checks._BASE}
    return case["store"].candidate_checks(
        "complete",
        dict(identity, stage=payload["stage"], grant_id=grant["grant_id"]),
        receipt=receipt,
        now=at,
    )


def status(case, *, at=NOW, **changes):
    return case["store"].candidate_checks("status", dict(case["identity"], **changes), now=at)


def passed(case):
    for stage in checks.STAGES:
        finish(case, start(case, stage))


def test_full_check_sequence_retains_exact_inputs_without_draft_approval_or_settlement(case):
    store = case["store"]
    before = store.read()
    assert not case["result"]["required_checks_completed"]
    assert status(case)["stages"] == dict.fromkeys(checks.STAGES, "pending")
    with closing(store._connect()) as connection:
        connection.execute("BEGIN")
        packet = checks._packet(connection, case["identity"]["check_set_id"])
    assert packet["bundle"] == case["payload"]["bundle"]
    assert packet["memory"] == case["payload"]["memory"]
    assert packet["candidate"]["tweet"] == "Synthetic station: 42 C."
    passed(case)
    result = status(case)
    assert result["required_checks_completed"]
    assert not result["publication_approved"] and not result["accounting_complete"]
    assert result["cost_usd"] is None and store.read() == before
    money = store.spending("status", {}, now=NOW)
    assert money["intent_count"] == 4 and money["totals"]["held_micro_usd"] == 75


def test_idempotent_intake_and_repeated_reads_do_not_consume_review_capacity(case):
    store = case["store"]
    before = workers.snapshot(store)
    assert store.candidate_checks("intake", case["payload"], now=NOW)["reused"]
    for _ in range(70):
        assert not status(case)["required_checks_completed"]
    assert workers.snapshot(store) == before


@pytest.mark.parametrize("field", ["bundle", "memory"])
def test_changed_supplied_inputs_refused_without_mutation(case, field):
    payload = deepcopy(case["payload"])
    payload[field]["extra"] = "changed"
    before = workers.snapshot(case["store"])
    with pytest.raises(checks.CheckJournalError, match="changed_check_input"):
        case["store"].candidate_checks("intake", payload, now=NOW)
    assert workers.snapshot(case["store"]) == before


@pytest.mark.parametrize("field", sorted(workers.worker._CONTEXT))
def test_changed_context_invalidates_completed_checks_and_blocks_more_work(case, field):
    passed(case)
    context = dict(case["identity"]["current_context"], **{field: "b" * 64})
    result = status(case, current_context=context)
    assert not result["required_checks_completed"] and result["blocked_reason"]
    with pytest.raises(checks.CheckJournalError, match="changed_check_context"):
        start(case, current_context=context)


@pytest.mark.parametrize("stage", ["safety", "fact_check", "critic"])
def test_predecessors_are_required_before_any_paid_dispatch(case, stage):
    before = workers.snapshot(case["store"])
    with pytest.raises(checks.CheckJournalError, match="predecessor"):
        start(case, stage)
    assert workers.snapshot(case["store"]) == before


@pytest.mark.parametrize(
    "execution,verdict,outcome",
    [
        ("completed", "reject", "rejected"),
        ("error", None, "error"),
        ("unavailable", None, "unavailable"),
    ],
)
def test_nonpass_is_durable_terminal_and_never_unblocks_next_stage(
    case, execution, verdict, outcome
):
    started = start(case)
    assert finish(case, started, execution=execution, verdict=verdict)["disposition"] == outcome
    assert status(case)["stages"]["deterministic"] == outcome
    assert not start(case)[0]["dispatch_granted"]
    with pytest.raises(checks.CheckJournalError, match="predecessor"):
        start(case, "safety")


def test_unknown_grant_and_missing_completion_do_not_pass(case):
    started = start(case)
    assert status(case)["stages"]["deterministic"] == "unresolved"
    changed = (dict(started[0], grant_id="e" * 64), *started[1:])
    with pytest.raises(checks.CheckJournalError, match="unknown_check_grant"):
        finish(case, changed)
    assert not status(case)["required_checks_completed"]


def test_exact_completion_replay_is_idempotent_and_conflict_refused(case):
    started = start(case)
    finish(case, started)
    before = workers.snapshot(case["store"])
    assert finish(case, started)["reused"]
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_completion"):
        finish(case, started, verdict="reject")
    assert workers.snapshot(case["store"]) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"request_sha256": "f" * 64},
        {"execution_status": "pending"},
        {"execution_status": "error", "verdict": "pass"},
        {"verdict": True},
        {"result": []},
        {"usage": 0},
        {"extra": True},
    ],
)
def test_malformed_receipts_cannot_complete_a_check(case, changes):
    started = start(case)
    with pytest.raises(checks.CheckJournalError):
        finish(case, started, **changes)
    assert status(case)["stages"]["deterministic"] == "unresolved"


def test_policy_change_blocks_even_when_caller_replays_old_context(case, monkeypatch):
    passed(case)
    policy = deepcopy(case["policy"])
    policy["models"]["critic"] = "different-model"
    monkeypatch.setattr(checks, "current_editorial_policy", lambda: policy)
    assert not status(case)["required_checks_completed"]
    with pytest.raises(checks.CheckJournalError, match="policy_unavailable"):
        start(case)


def test_expired_deadline_and_lease_never_reuse_passed_checks(case):
    passed(case)
    assert not status(case, at="2026-09-30T12:00:00Z")["required_checks_completed"]
    assert not status(case, at=workers.later(300))["required_checks_completed"]


def test_late_receipt_retained_but_cannot_pass_or_trigger_repurchase(case):
    finish(case, start(case))
    attempt = start(case, "safety")
    assert finish(case, attempt, at=workers.later(300))["disposition"] == "stale"
    workers.acquire(case["store"], owner="worker-two", at=workers.later(300))
    case["identity"].update(owner="worker-two", fence=2)
    assert status(case, at=workers.later(300))["stages"]["safety"] == "stale"
    assert not start(case, "safety", at=workers.later(300))[0]["dispatch_granted"]
    assert (
        case["store"].spending("status", {}, now=workers.later(300))["totals"]["held_micro_usd"]
        == 65
    )


def test_result_conflict_invalidates_old_pass_without_discarding_receipts(case):
    passed(case)
    other = batches.rows(case["pair"])
    other[0]["result"]["message"]["id"] = "msg_different"
    batches.retain(case["store"], case["grant"], batches.contract.raw_rows(other))
    result = status(case)
    assert all(v == "passed" for v in result["stages"].values())
    assert not result["required_checks_completed"]


def test_check_spend_is_reserved_and_dispatched_atomically_with_grant(case):
    finish(case, start(case))
    before = workers.snapshot(case["store"])

    def fail():
        raise RuntimeError("injected before commit")

    with pytest.raises(RuntimeError):
        start(case, "safety", before_commit=fail)
    assert workers.snapshot(case["store"]) == before
    first = start(case, "safety")[0]
    assert first["dispatch_granted"]
    second = start(case, "safety")[0]
    assert second["grant_id"] == first["grant_id"] and not second["dispatch_granted"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("role", "writer"),
        ("provider", "anthropic"),
        ("model", "wrong-model"),
        ("job_id", "other-job"),
        ("request_sha256", "e" * 64),
    ],
)
def test_reservation_must_match_exact_check_request_and_role(case, field, value):
    finish(case, start(case))
    request = json.dumps(dict(identity=case["identity"]["check_set_id"], stage="safety")).encode()
    reservation = dict(
        intent_id="bad",
        job_id=case["payload"]["job_id"],
        request_sha256=hashlib.sha256(request).hexdigest(),
        provider="google",
        role="safety",
        model=case["policy"]["models"]["safety"],
        estimate_sha256="d" * 64,
        reserve_micro_usd=5,
    )
    reservation[field] = value
    with pytest.raises(checks.CheckJournalError, match="reservation_mismatch"):
        start(case, "safety", reservation=reservation)


def test_backup_restore_retains_checks_and_refuses_second_dispatch(case, tmp_path):
    passed(case)
    backup = tmp_path / "restored.sqlite"
    with closing(case["store"]._connect()) as source, closing(sqlite3.connect(backup)) as dest:
        source.backup(dest)
    case["store"] = SQLiteAuthority(backup)
    assert status(case)["required_checks_completed"]
    assert not start(case, "critic")[0]["dispatch_granted"]


@pytest.mark.parametrize("table", checks._TABLES)
@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_sql_immutability_guards(case, table, operation):
    passed(case)
    with closing(case["store"]._connect()) as connection:
        fields = [r[1] for r in connection.execute(f"PRAGMA table_info({table})")]
        sql = (
            f"UPDATE {table} SET {fields[0]}={fields[0]}"
            if operation == "update"
            else f"DELETE FROM {table}"
            if operation == "delete"
            else f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}"
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable checks"):
            connection.execute(sql)


def test_schema_tampering_detected_before_action(case):
    with closing(case["store"]._connect()) as connection:
        connection.execute("DROP TRIGGER check_attempts_no_replace")
    with pytest.raises(checks.CheckJournalError, match="changed_check_schema"):
        start(case)


def _concurrent_start(case, barrier, output):
    barrier.wait(timeout=10)
    try:
        output.put(start(case, "safety")[0])
    except BaseException as exc:
        output.put({"error": type(exc).__name__})


def test_two_processes_can_obtain_only_one_paid_grant(case):
    finish(case, start(case))
    ctx = multiprocessing.get_context("fork")
    barrier, output = ctx.Barrier(2), ctx.Queue()
    children = [
        ctx.Process(target=_concurrent_start, args=(case, barrier, output)) for _ in range(2)
    ]
    for child in children:
        child.start()
    values = [output.get(timeout=20) for _ in children]
    for child in children:
        child.join(10)
        assert child.exitcode == 0
    assert not any("error" in row for row in values)
    assert sum(row["dispatch_granted"] for row in values) == 1


def _crash(case):
    start(case, "safety", before_commit=lambda: os._exit(23))


def test_actual_process_death_rolls_back_check_and_spend_together(case):
    finish(case, start(case))
    before = workers.snapshot(case["store"])
    child = multiprocessing.get_context("fork").Process(target=_crash, args=(case,))
    child.start()
    child.join(10)
    assert child.exitcode == 23
    assert workers.snapshot(case["store"]) == before
    assert start(case, "safety")[0]["dispatch_granted"]


def test_deadline_equality_blocks_even_with_new_valid_lease(case):
    passed(case)
    deadline = json.loads(case["pair"][0])["useful_until"]
    workers.acquire(case["store"], owner="new-owner", at=deadline)
    case["identity"].update(owner="new-owner", fence=2)
    assert not status(case, at=deadline)["required_checks_completed"]
    with pytest.raises(checks.CheckJournalError, match="no_longer_current"):
        start(case, at=deadline)


@pytest.mark.parametrize("flag", ["critic_enabled", "safety_llm_enabled"])
def test_disabled_required_stage_cannot_be_omitted_from_intake(store, inputs, monkeypatch, flag):
    # Explicit offline policy fixture; production resolves its actually loaded policy.
    inputs["policy"]["flags"][flag] = False
    monkeypatch.setattr(checks, "current_editorial_policy", lambda: inputs["policy"])
    pair, grant = batches.started(store, inputs)
    receipt = batches.retain(store, grant, batches.contract.raw_rows(batches.rows(pair)))
    payload = dict(
        job_id=pair[1]["job_id"],
        owner="worker-one",
        fence=1,
        receipt_id=receipt["receipt_id"],
        current_context=batches.contract.context(pair[0]),
        custom_id=json.loads(pair[0])["requests"][0]["custom_id"],
        bundle=inputs["bundle"].to_dict(),
        memory=inputs["memory"].to_dict(),
        checker_state=deepcopy(store.read()[1]),
    )
    with pytest.raises(checks.CheckJournalError, match="required_checks_disabled"):
        store.candidate_checks("intake", payload, now=NOW)


def test_invalid_or_unknown_intake_item_never_creates_another_set(case):
    before = workers.snapshot(case["store"])
    with pytest.raises(checks.CheckJournalError, match="ineligible"):
        case["store"].candidate_checks(
            "intake", dict(case["payload"], custom_id="unknown"), now=NOW
        )
    assert workers.snapshot(case["store"]) == before


def test_equivalent_result_bytes_reuse_one_exact_candidate(case):
    altered = b"\n".join(
        json.dumps(row, indent=None, separators=(",", ":")).encode()
        for row in batches.rows(case["pair"])
    )
    receipt = batches.retain(case["store"], case["grant"], altered)
    result = case["store"].candidate_checks(
        "intake", dict(case["payload"], receipt_id=receipt["receipt_id"]), now=NOW
    )
    assert result["reused"] and result["check_set_id"] == case["identity"]["check_set_id"]


def test_malformed_complete_receipt_does_not_hide_good_candidate(case):
    batches.retain(case["store"], case["grant"], b"malformed")
    assert status(case)["blocked_reason"] is None
    assert start(case)[0]["dispatch_granted"]


def test_paid_allowance_exhaustion_rolls_back_without_consuming_stage(case):
    finish(case, start(case))
    request = json.dumps(dict(identity=case["identity"]["check_set_id"], stage="safety")).encode()
    reservation = dict(
        intent_id="too-much",
        job_id=case["payload"]["job_id"],
        request_sha256=hashlib.sha256(request).hexdigest(),
        provider="google",
        role="safety",
        model=case["policy"]["models"]["safety"],
        estimate_sha256="d" * 64,
        reserve_micro_usd=31,
    )
    before = workers.snapshot(case["store"])
    with pytest.raises(SpendError, match="exhausted"):
        start(case, "safety", reservation=reservation)
    assert workers.snapshot(case["store"]) == before
    assert start(case, "safety")[0]["dispatch_granted"]


def test_recovery_after_committed_but_unobserved_grant_never_rebuys(case):
    finish(case, start(case))
    start(case, "safety")  # Simulate lost acknowledgment: do not retain its returned grant.
    case["store"] = SQLiteAuthority(case["store"].path)
    recovered = start(case, "safety")
    assert not recovered[0]["dispatch_granted"]
    assert status(case)["stages"]["safety"] == "unresolved"
    assert case["store"].spending("status", {}, now=NOW)["intent_count"] == 2


@pytest.mark.parametrize("mutation", ["request", "receipt", "intake"])
def test_explicit_resource_bounds(case, mutation):
    before = workers.snapshot(case["store"])
    if mutation == "request":
        with pytest.raises(checks.CheckJournalError, match="invalid_check_request"):
            case["store"].candidate_checks(
                "begin",
                dict(case["identity"], stage="deterministic", reservation=None),
                request=b"x" * (checks.MAX_INPUT_BYTES + 1),
                now=NOW,
            )
    elif mutation == "intake":
        payload = deepcopy(case["payload"])
        payload["bundle"]["oversized"] = "x" * checks.MAX_INPUT_BYTES
        with pytest.raises(checks.CheckJournalError, match="oversized_check_packet"):
            case["store"].candidate_checks("intake", payload, now=NOW)
    else:
        started = start(case)
        before = workers.snapshot(case["store"])
        with pytest.raises(checks.CheckJournalError, match="oversized_check_packet"):
            finish(case, started, result={"oversized": "x" * checks.MAX_RECEIPT_BYTES})
    assert workers.snapshot(case["store"]) == before


def test_additive_migration_retains_existing_authority_and_foreign_keys(case):
    store = case["store"]
    before = store.read()
    with closing(store._connect()) as connection:
        for table in reversed(checks._TABLES):
            connection.execute(f"DROP TABLE {table}")
    with pytest.raises(checks.CheckJournalError, match="migration_required"):
        status(case)
    store.initialize(before[1])
    assert store.read() == before
    recreated = store.candidate_checks("intake", case["payload"], now=NOW)
    assert recreated["check_set_id"] == case["identity"]["check_set_id"]
    with closing(store._connect()) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_changed_check_schema_refuses_reinitialization(case):
    with closing(case["store"]._connect()) as connection:
        connection.execute("DROP TRIGGER check_sets_no_update")
    with pytest.raises(checks.CheckJournalError, match="changed_check_schema"):
        case["store"].initialize(case["store"].read()[1])


def test_stale_completion_replay_reports_history_but_cannot_restore_readiness(case):
    started = start(case)
    finish(case, started)
    assert finish(case, started, at=workers.later(300))["disposition"] == "passed"
    assert not status(case, at=workers.later(300))["required_checks_completed"]


def test_changed_request_cannot_take_over_an_existing_grant(case):
    start(case)
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_attempt"):
        case["store"].candidate_checks(
            "begin",
            dict(case["identity"], stage="deterministic", reservation=None),
            request=b"different request",
            now=NOW,
        )


@pytest.mark.parametrize("field", ["drafts", "memory"])
def test_pending_drafts_and_reuse_state_invalidate_existing_checks(case, field):
    passed(case)
    changed = deepcopy(case["payload"]["checker_state"])
    changed[field] = {"changed": True}
    digest = fingerprint(changed)
    assert not status(case, checker_state_sha256=digest)["required_checks_completed"]
    with pytest.raises(checks.CheckJournalError, match="changed_checker_state"):
        start(case, checker_state_sha256=digest)
    with pytest.raises(checks.CheckJournalError, match="conflicting_check_candidate"):
        case["store"].candidate_checks(
            "intake", dict(case["payload"], checker_state=changed), now=NOW
        )


def test_late_completion_with_changed_checker_state_is_retained_as_stale(case):
    started = start(case)
    changed = (started[0], started[1], dict(started[2], checker_state_sha256="b" * 64))
    assert finish(case, changed)["disposition"] == "stale"
    assert status(case)["stages"]["deterministic"] == "stale"


def test_utc_rollover_changes_critic_comparison_window_before_usefulness_expiry(case):
    passed(case)
    at = "2026-09-30T00:00:00Z"  # Twelve hours before the plan's deadline.
    workers.acquire(case["store"], owner="new-owner", at=at)
    case["identity"].update(owner="new-owner", fence=2)
    assert not status(case, at=at)["required_checks_completed"]
    with pytest.raises(checks.CheckJournalError, match="changed_checker_calendar_day"):
        start(case, at=at)


def test_missing_checker_state_never_implies_empty_history(case):
    payload = dict(case["payload"])
    del payload["checker_state"]
    with pytest.raises(checks.CheckJournalError, match="invalid_check_fields"):
        case["store"].candidate_checks("intake", payload, now=NOW)
