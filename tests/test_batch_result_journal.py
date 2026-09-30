"""Retained result bytes, current fenced review and conflicting-result containment."""

from contextlib import closing
from copy import deepcopy
import json
import multiprocessing
import os
import sqlite3

import pytest

from src.commands import batch_result_journal as results
from src.commands.batch_worker_journal import BatchWorkerError
from src.commands.sqlite_authority import SQLiteAuthority
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contract

store = workers.store
inputs = workers.inputs
NOW = workers.NOW


def started(store, inputs, samples=1, *, adopted=True):
    inputs = deepcopy(inputs)
    if samples != 1:
        inputs.update(samples=samples, experiment_id="fixture-experiment")
        inputs["policy"]["flags"]["writer_samples"] = samples
    pair = workers.ready(store, inputs)
    workers.acquire(store)
    grant = workers.begin(store, pair)
    counts = dict(processing=samples, succeeded=0, errored=0, expired=0, canceled=0)
    ack = workers.ack(request_counts=counts)
    workers.observe(store, grant, ack)
    if adopted:
        workers.adopt(store, ack)
    return pair, grant


def metadata(samples=1, **changes):
    return workers.ack(
        processing_status="ended",
        request_counts=dict(processing=0, succeeded=samples, errored=0, expired=0, canceled=0),
        **changes,
    )


def rows(pair):
    return [contract.result(pair[0], i) for i in range(json.loads(pair[0])["samples"])]


def retain(store, grant, raw, *, meta=None, complete=True, at=NOW, **kwargs):
    meta = metadata() if meta is None else meta
    payload = dict(
        job_id=grant["job_id"],
        grant_id=grant["grant_id"],
        metadata_sha256=workers.digest(meta),
        results_sha256=workers.digest(raw),
        complete=complete,
    )
    return store.record_batch_results(payload, metadata=meta, results=raw, now=at, **kwargs)


def review(store, pair, receipt, *, at=NOW, owner="worker-one", fence=1, context=None, **kwargs):
    payload = dict(
        job_id=pair[1]["job_id"],
        owner=owner,
        fence=fence,
        receipt_id=receipt["receipt_id"],
        current_context=contract.context(pair[0]) if context is None else context,
    )
    return store.review_batch_results(payload, now=at, **kwargs)


def test_exact_raw_retention_then_review_does_not_create_draft_or_release_charge(store, inputs):
    pair, grant = started(store, inputs)
    before_state = store.read()
    raw = contract.raw_rows(rows(pair))
    receipt = retain(store, grant, raw)
    assert store.read_artifact(workers.digest(raw)) == raw
    assert receipt["raw_retained"] and not receipt["publication_approved"]
    report = review(store, pair, receipt)
    assert report["report"]["rows"][0]["eligible_for_checks"]
    assert report["report"]["rows"][0]["candidate_id"]
    assert not report["report"]["required_checks_completed"] and not report["publication_approved"]
    assert not report["report"]["accounting_complete"] and report["report"]["cost_usd"] is None
    assert report["report"]["rows"][0]["usage"]["input_tokens"] == 17
    saved = json.loads(store.read_artifact(report["report_sha256"]))
    assert saved["binding"] == report["binding"]
    assert store.read() == before_state
    assert store.spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 60


def test_identical_receipt_and_review_are_exactly_idempotent(store, inputs):
    pair, grant = started(store, inputs)
    raw = contract.raw_rows(rows(pair))
    receipt = retain(store, grant, raw)
    original = review(store, pair, receipt)
    before = workers.snapshot(store)
    assert retain(store, grant, raw)["reused"]
    repeated = review(store, pair, receipt)
    assert repeated["reused"] and repeated["report_sha256"] == original["report_sha256"]
    assert workers.snapshot(store) == before


def test_out_of_order_and_whitespace_equivalent_files_have_stable_item_ids(store, inputs):
    pair, grant = started(store, inputs, 3)
    values = rows(pair)
    first = retain(store, grant, contract.raw_rows(values), meta=metadata(3))
    initial = review(store, pair, first)
    reordered = b"\n".join(
        json.dumps(item, separators=(",", ":")).encode() for item in reversed(values)
    )
    second = retain(store, grant, reordered, meta=metadata(3))
    updated = review(store, pair, second)
    assert updated["semantic_sha256"] == initial["semantic_sha256"]
    assert [r["candidate_id"] for r in updated["report"]["rows"]] == [
        r["candidate_id"] for r in initial["report"]["rows"]
    ]
    assert updated["binding"]["receipt_set_sha256"] != initial["binding"]["receipt_set_sha256"]
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM batch_result_choices").fetchone()[0] == 1


def test_partial_file_followed_by_complete_file_can_recover_without_rebuying(store, inputs):
    pair, grant = started(store, inputs, 3)
    values = rows(pair)
    partial = retain(store, grant, contract.raw_rows(values[:2]), meta=metadata(3))
    report = review(store, pair, partial)["report"]
    assert not report["complete"] and len(report["rows"]) == 2
    assert all(not row["eligible_for_checks"] and row["usage"] for row in report["rows"])
    full = retain(store, grant, contract.raw_rows(values), meta=metadata(3))
    assert all(row["eligible_for_checks"] for row in review(store, pair, full)["report"]["rows"])
    assert store.spending("status", {}, now=NOW)["intent_count"] == 1


def test_truncated_download_flag_blocks_even_when_visible_rows_look_complete(store, inputs):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)), complete=False)
    report = review(store, pair, receipt)["report"]
    assert "incomplete_result_download" in report["context_blocked_reasons"]
    assert not report["rows"][0]["eligible_for_checks"] and report["rows"][0]["usage"]
    with closing(store._connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM batch_result_choices").fetchone()[0] == 0


def test_mixed_terminal_outcomes_preserve_charge_uncertainty(store, inputs):
    pair, grant = started(store, inputs, 3)
    values = rows(pair)
    values[1]["result"] = {"type": "canceled"}
    values[2]["result"] = {"type": "errored", "error": {"type": "invalid_request_error"}}
    meta = workers.ack(
        processing_status="ended",
        request_counts=dict(processing=0, succeeded=1, canceled=1, errored=1, expired=0),
    )
    receipt = retain(store, grant, contract.raw_rows(values), meta=meta)
    report = review(store, pair, receipt)["report"]
    assert [row["provider_status"] for row in report["rows"]] == [
        "succeeded",
        "canceled",
        "errored",
    ]
    assert [row["eligible_for_checks"] for row in report["rows"]] == [True, False, False]
    assert all(row["cost_usd"] is None for row in report["rows"])


@pytest.mark.parametrize(
    "meta", [b"{", b"null", metadata(id="msgbatch_wrong"), workers.ack(), metadata(2)]
)
def test_wrong_or_nonterminal_metadata_withholds_text_but_retains_usage(store, inputs, meta):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)), meta=meta)
    report = review(store, pair, receipt)["report"]
    assert report["context_blocked_reasons"] and not report["rows"][0]["eligible_for_checks"]
    assert report["rows"][0]["usage"]["output_tokens"] == 9
    assert store.read_artifact(workers.digest(meta)) == meta


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"custom_id":"x","custom_id":"y"}', b"null"])
def test_malformed_protocol_keeps_raw_evidence_and_unknown_cost(store, inputs, raw):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, raw)
    report = review(store, pair, receipt)["report"]
    assert "invalid_results_protocol" in report["context_blocked_reasons"]
    assert report["rows"] == [] and report["cost_usd"] is None and not report["accounting_complete"]
    assert store.read_artifact(workers.digest(raw)) == raw


def test_invalid_writer_content_keeps_reported_usage_without_candidate(store, inputs):
    pair, grant = started(store, inputs)
    values = rows(pair)
    values[0]["result"]["message"]["content"][0]["text"] = "not the required JSON"
    receipt = retain(store, grant, contract.raw_rows(values))
    row = review(store, pair, receipt)["report"]["rows"][0]
    assert row["candidate"] is None and row["usage"]["input_tokens"] == 17


@pytest.mark.parametrize(
    "key", ["bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"]
)
def test_current_context_changes_withhold_stale_text_without_losing_usage(store, inputs, key):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    context = contract.context(pair[0])
    context[key] = "changed-epoch" if key == "publication_epoch" else "f" * 64
    report = review(store, pair, receipt, context=context)["report"]
    assert "changed_" + key in report["context_blocked_reasons"]
    assert report["rows"][0]["candidate"] is None and report["rows"][0]["usage"]


def test_exact_deadline_withholds_output_even_for_new_current_owner(store, inputs):
    pair, grant = started(store, inputs)
    at = json.loads(pair[0])["useful_until"]
    workers.acquire(store, owner="new-worker", at=at)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)), at=at)
    report = review(store, pair, receipt, at=at, owner="new-worker", fence=2)["report"]
    assert (
        "expired" in report["context_blocked_reasons"]
        and not report["rows"][0]["eligible_for_checks"]
    )
    assert report["rows"][0]["usage"]


def test_late_worker_can_retain_but_only_current_fence_can_review(store, inputs):
    pair, grant = started(store, inputs)
    at = workers.later(300)
    workers.acquire(store, owner="new-worker", at=at)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)), at=at)
    with pytest.raises(BatchWorkerError, match="stale"):
        review(store, pair, receipt, at=at)
    assert review(store, pair, receipt, at=at, owner="new-worker", fence=2)["report"]["rows"][0][
        "eligible_for_checks"
    ]


def test_conflicting_complete_results_invalidate_review_of_prior_good_receipt(store, inputs):
    pair, grant = started(store, inputs)
    first = retain(store, grant, contract.raw_rows(rows(pair)))
    original = review(store, pair, first)
    different = rows(pair)
    output = json.loads(different[0]["result"]["message"]["content"][0]["text"])
    output["tweet"] = "A different synthetic result."
    different[0]["result"]["message"]["content"][0]["text"] = json.dumps(output)
    second = retain(store, grant, contract.raw_rows(different))
    for receipt in (first, second):
        changed = review(store, pair, receipt)
        assert "conflicting_complete_results" in changed["report"]["context_blocked_reasons"]
        assert changed["report"]["rows"][0]["candidate_id"] is None
        assert changed["binding"]["receipt_set_sha256"] != original["binding"]["receipt_set_sha256"]


def test_later_provider_id_conflict_changes_review_revision_and_withholds_prior_text(store, inputs):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    original = review(store, pair, receipt)
    workers.observe(store, grant, workers.ack("msgbatch_conflict"))
    blocked = review(store, pair, receipt)
    assert "submission_not_confirmed" in blocked["report"]["context_blocked_reasons"]
    assert not blocked["report"]["rows"][0]["eligible_for_checks"]
    assert (
        original["binding"]["submission_revision_sha256"]
        != blocked["binding"]["submission_revision_sha256"]
    )


def test_unadopted_submission_preserves_result_usage_without_becoming_authoritative(store, inputs):
    pair, grant = started(store, inputs, adopted=False)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    report = review(store, pair, receipt)["report"]
    assert "submission_not_confirmed" in report["context_blocked_reasons"]
    assert report["rows"][0]["usage"] and not report["rows"][0]["eligible_for_checks"]


@pytest.mark.parametrize("which", ["metadata", "results", "completeness", "grant"])
def test_unbounded_or_invalid_intake_is_refused_without_orphan_bytes(store, inputs, which):
    pair, grant = started(store, inputs)
    meta, raw, complete = metadata(), contract.raw_rows(rows(pair)), True
    if which == "metadata":
        meta = b"x" * 65537
    elif which == "results":
        raw = b"x" * 3_000_001
    elif which == "completeness":
        complete = 1
    else:
        grant = dict(grant, grant_id="f" * 64)
    before = workers.snapshot(store)
    with pytest.raises(results.BatchResultError):
        retain(store, grant, raw, meta=meta, complete=complete)
    assert workers.snapshot(store) == before


def test_raw_retention_and_review_faults_roll_back_atomically(store, inputs):
    pair, grant = started(store, inputs)

    def fail():
        raise RuntimeError("crash fixture")

    before = workers.snapshot(store)
    with pytest.raises(RuntimeError):
        retain(store, grant, contract.raw_rows(rows(pair)), before_commit=fail)
    assert workers.snapshot(store) == before
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    before = workers.snapshot(store)
    with pytest.raises(RuntimeError):
        review(store, pair, receipt, before_commit=fail)
    assert workers.snapshot(store) == before
    assert review(store, pair, receipt)["report"]["rows"][0]["eligible_for_checks"]


def die_review(path, pair, receipt):
    review(SQLiteAuthority(path), pair, receipt, before_commit=lambda: os._exit(23))


def test_process_death_during_review_preserves_intake_and_money(store, inputs):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    before = workers.snapshot(store)
    child = multiprocessing.get_context("spawn").Process(
        target=die_review, args=(store.path, pair, receipt)
    )
    child.start()
    child.join(timeout=20)
    assert not child.is_alive() and child.exitcode == 23
    assert workers.snapshot(store) == before
    assert review(SQLiteAuthority(store.path), pair, receipt)["report"]["rows"][0][
        "eligible_for_checks"
    ]


def test_backup_restore_retains_bytes_review_and_semantic_choice(store, inputs, tmp_path):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    report = review(store, pair, receipt)
    backup = tmp_path / "backup.sqlite"
    with closing(store._connect()) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    restored = SQLiteAuthority(backup)
    again = review(restored, pair, receipt)
    assert again["reused"] and again["report_sha256"] == report["report_sha256"]
    assert restored.read_artifact(report["report_sha256"]) == store.read_artifact(
        report["report_sha256"]
    )
    assert restored.spending("status", {}, now=NOW)["totals"]["held_micro_usd"] == 60


def test_capacity_does_not_break_exact_retry(store, inputs, monkeypatch):
    pair, grant = started(store, inputs)
    raw = contract.raw_rows(rows(pair))
    receipt = retain(store, grant, raw)
    review(store, pair, receipt)
    monkeypatch.setattr(results, "MAX_RECEIPTS", 1)
    monkeypatch.setattr(results, "MAX_REVIEWS", 1)
    assert retain(store, grant, raw)["reused"] and review(store, pair, receipt)["reused"]
    with pytest.raises(results.BatchResultError, match="capacity"):
        retain(store, grant, raw, complete=False)
    with pytest.raises(results.BatchResultError, match="capacity"):
        review(store, pair, receipt, at=workers.later(1))


@pytest.mark.parametrize("table", results._TABLES)
def test_changed_guards_refuse_operations(store, inputs, table):
    pair, grant = started(store, inputs)
    with closing(store._connect()) as connection:
        connection.execute(f"DROP TRIGGER {table}_no_replace")
    before = workers.snapshot(store)
    with pytest.raises(results.BatchResultError, match="schema"):
        retain(store, grant, contract.raw_rows(rows(pair)))
    assert workers.snapshot(store) == before


def test_review_does_not_alias_callers_current_context(store, inputs):
    pair, grant = started(store, inputs)
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    context = contract.context(pair[0])
    report = review(store, pair, receipt, context=context)
    context["publication_epoch"] = "changed-after-return"
    saved = json.loads(store.read_artifact(report["report_sha256"]))
    assert report["binding"]["current_context"] == saved["binding"]["current_context"]


def test_wrong_independently_retained_hash_does_not_store_bytes(store, inputs):
    pair, grant = started(store, inputs)
    raw, meta = contract.raw_rows(rows(pair)), metadata()
    payload = dict(
        job_id=grant["job_id"],
        grant_id=grant["grant_id"],
        metadata_sha256=workers.digest(meta),
        results_sha256="f" * 64,
        complete=True,
    )
    before = workers.snapshot(store)
    with pytest.raises(results.BatchResultError, match="changed_result_bytes"):
        store.record_batch_results(payload, metadata=meta, results=raw, now=NOW)
    assert workers.snapshot(store) == before


def test_explicit_result_schema_migration_preserves_existing_submission(store, inputs):
    pair, grant = started(store, inputs)
    before_state = store.read()
    before_status = workers.call(store, "status")
    with closing(store._connect()) as connection:
        for table in reversed(results._TABLES):
            connection.execute("DROP TABLE " + table)
    with pytest.raises(results.BatchResultError, match="migration_required"):
        retain(store, grant, contract.raw_rows(rows(pair)))
    store.initialize(before_state[1])
    assert workers.call(store, "status") == before_status and store.read() == before_state
    receipt = retain(store, grant, contract.raw_rows(rows(pair)))
    assert review(store, pair, receipt)["report"]["rows"][0]["eligible_for_checks"]
