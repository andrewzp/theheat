"""Durable local batch result evidence and fenced review; no drafts or transport."""

from __future__ import annotations

import hashlib
import json
import sqlite3

from src.commands import batch_journal, batch_worker_journal as worker, domain_journal
from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint

MAX_RESULT_BYTES = 3_000_000
MAX_RECEIPTS = 16
MAX_REVIEWS = 64
_TABLES = {
    "batch_result_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "batch_result_receipts": "receipt_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES batch_worker_submissions(job_id), metadata_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), results_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), binding_json TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(job_id,receipt_id)",
    "batch_result_choices": "job_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL, semantic_sha256 TEXT NOT NULL, FOREIGN KEY(job_id,receipt_id) REFERENCES batch_result_receipts(job_id,receipt_id)",
    "batch_result_reviews": "review_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, receipt_id TEXT NOT NULL, fence INTEGER NOT NULL, report_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), recorded_at TEXT NOT NULL, FOREIGN KEY(job_id,receipt_id) REFERENCES batch_result_receipts(job_id,receipt_id), FOREIGN KEY(job_id,fence) REFERENCES batch_worker_leases(job_id,fence)",
}
_BINDING = {"job_id", "grant_id", "metadata_sha256", "results_sha256", "complete"}


class BatchResultError(ValueError):
    """Bounded code; raw provider data belongs only in private artifacts."""


def _require(condition, code):
    if not condition:
        raise BatchResultError(code)


def _objects():
    objects = {}
    for table, columns in _TABLES.items():
        objects[table] = f"CREATE TABLE {table} ({columns})"
        for action in ("UPDATE", "DELETE"):
            name = f"{table}_no_{action.lower()}"
            objects[name] = (
                f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable batch results'); END"
            )
        key = (
            "singleton"
            if table == "batch_result_schema"
            else "job_id"
            if table == "batch_result_choices"
            else "review_id"
            if table == "batch_result_reviews"
            else "receipt_id"
        )
        name = f"{table}_no_replace"
        objects[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key}) BEGIN SELECT RAISE(ABORT, 'immutable batch results'); END"
        )
    return objects


SCHEMA_SHA256 = fingerprint(_objects())


def validate(connection):
    _require(connection.in_transaction, "batch_results_require_transaction")
    worker.validate(connection)
    try:
        row = connection.execute("SELECT * FROM batch_result_schema WHERE singleton=1").fetchone()
        _require(row is not None and row["schema_sha256"] == SCHEMA_SHA256, "changed_result_schema")
        for name, sql in _objects().items():
            actual = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            _require(actual is not None and actual["sql"] == sql, "changed_result_schema")
    except sqlite3.DatabaseError:
        raise BatchResultError("batch_result_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "batch_results_require_transaction")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='batch_result_schema'"
    ).fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO batch_result_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _at(connection, now):
    stamp = utc_datetime(now)
    latest = connection.execute(
        "SELECT MAX(recorded_at) FROM (SELECT recorded_at FROM batch_result_receipts UNION ALL SELECT recorded_at FROM batch_result_reviews)"
    ).fetchone()[0]
    _require(latest is None or stamp >= utc_datetime(latest), "result_clock_went_backwards")
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _raw(connection, sha, limit):
    size = connection.execute(
        "SELECT byte_count FROM domain_artifacts WHERE sha256=?", (sha,)
    ).fetchone()
    _require(size is not None and 0 <= size[0] <= limit, "invalid_result_artifact_size")
    return domain_journal.read_artifact(connection, sha)


def _binding(value):
    _require(isinstance(value, dict) and set(value) == _BINDING, "invalid_result_binding")
    worker.spend_journal._id(value["job_id"])
    for field in ("grant_id", "metadata_sha256", "results_sha256"):
        worker.spend_journal._sha(value[field])
    _require(type(value["complete"]) is bool, "invalid_result_completeness")


def _receipts(connection, job, grant):
    _require(
        connection.execute(
            "SELECT COUNT(*) FROM batch_result_receipts WHERE job_id=?", (job,)
        ).fetchone()[0]
        <= MAX_RECEIPTS,
        "result_receipt_capacity",
    )
    rows = connection.execute(
        "SELECT * FROM batch_result_receipts WHERE job_id=? ORDER BY receipt_id", (job,)
    ).fetchall()
    result = []
    for row in rows:
        binding = json.loads(row["binding_json"])
        _binding(binding)
        _require(
            fingerprint(binding) == row["receipt_id"]
            and binding["job_id"] == job
            and binding["grant_id"] == grant
            and all(binding[key] == row[key] for key in ("metadata_sha256", "results_sha256")),
            "changed_result_binding",
        )
        result.append(
            dict(
                row,
                binding=binding,
                metadata=_raw(connection, row["metadata_sha256"], worker.MAX_ACK_BYTES),
                results=_raw(connection, row["results_sha256"], MAX_RESULT_BYTES),
            )
        )
    return result


def record(connection, payload, metadata, results, *, now):
    validate(connection)
    at = _at(connection, now)
    _binding(payload)
    for raw, key, bound in (
        (metadata, "metadata_sha256", worker.MAX_ACK_BYTES),
        (results, "results_sha256", MAX_RESULT_BYTES),
    ):
        _require(type(raw) is bytes and len(raw) <= bound, "invalid_or_oversized_result_bytes")
        _require(hashlib.sha256(raw).hexdigest() == payload[key], "changed_result_bytes")
    status = worker.apply(connection, "status", {"job_id": payload["job_id"]}, now=at)
    _require(status["grant_id"] == payload["grant_id"], "unknown_result_grant")
    receipt_id = fingerprint(payload)
    prior = connection.execute(
        "SELECT 1 FROM batch_result_receipts WHERE receipt_id=?", (receipt_id,)
    ).fetchone()
    if not prior:
        _require(
            connection.execute(
                "SELECT COUNT(*) FROM batch_result_receipts WHERE job_id=?", (payload["job_id"],)
            ).fetchone()[0]
            < MAX_RECEIPTS,
            "result_receipt_capacity",
        )
        # Byte retention precedes any provider/result protocol interpretation.
        domain_journal._artifact(connection, metadata)
        domain_journal._artifact(connection, results)
        connection.execute(
            "INSERT INTO batch_result_receipts VALUES(?,?,?,?,?,?)",
            (
                receipt_id,
                payload["job_id"],
                payload["metadata_sha256"],
                payload["results_sha256"],
                canonical_json(payload),
                at,
            ),
        )
    _receipts(connection, payload["job_id"], payload["grant_id"])
    return dict(
        job_id=payload["job_id"],
        receipt_id=receipt_id,
        reused=bool(prior),
        raw_retained=True,
        publication_approved=False,
        dispatch_granted=False,
    )


def _withhold(report, reasons):
    for reason in reasons:
        if reason not in report["context_blocked_reasons"]:
            report["context_blocked_reasons"].append(reason)
        for row in report["rows"]:
            if reason not in row["blocked_reasons"]:
                row["blocked_reasons"].append(reason)
            row["candidate"] = None
            row["eligible_for_checks"] = False


def index(connection, payload, *, now):
    """Validated evidence inventory, never a cached eligibility decision."""
    validate(connection)
    _require(isinstance(payload, dict) and set(payload) == {"job_id"}, "invalid_result_index")
    at = _at(connection, now)
    job = payload["job_id"]
    status = worker.apply(connection, "status", payload, now=at)
    receipts = _receipts(connection, job, status["grant_id"])
    choice = connection.execute(
        "SELECT * FROM batch_result_choices WHERE job_id=?", (job,)
    ).fetchone()
    _require(
        choice is None or any(r["receipt_id"] == choice["receipt_id"] for r in receipts),
        "changed_result_choice",
    )
    return dict(
        submission=status,
        chosen_receipt_id=choice["receipt_id"] if choice else None,
        receipts=[
            dict(receipt_id=r["receipt_id"], complete=r["binding"]["complete"],
                 recorded_at=r["recorded_at"])
            for r in receipts
        ],
        capacity_remaining=MAX_RECEIPTS - len(receipts),
        publication_approved=False,
    )


def _decode(plan_raw, plan, receipt, context, at, provider_id):
    from src.two_bot import batch_contract as contract

    reasons = []
    try:
        report = contract.collect_batch_results(
            plan_raw,
            receipt["results"],
            expected_plan_sha256=hashlib.sha256(plan_raw).hexdigest(),
            current_context=context,
            now=at,
        )
    except contract.BatchContractError:
        report = dict(
            schema_version=1,
            plan_sha256=hashlib.sha256(plan_raw).hexdigest(),
            results_sha256=receipt["results_sha256"],
            complete=False,
            missing_custom_ids=[],
            rows=[],
            context_blocked_reasons=["invalid_results_protocol"],
            required_checks_completed=False,
            publication_approved=False,
            cost_usd=None,
            accounting_complete=False,
        )
    semantic = None
    items = {}
    if not receipt["binding"]["complete"]:
        reasons.append("incomplete_result_download")
    identity = worker._ack_id(receipt["metadata"], plan["samples"])
    if identity is None or provider_id is None or identity != provider_id:
        reasons.append("result_metadata_identity_mismatch")
    else:
        metadata = json.loads(receipt["metadata"])
        if (
            metadata["processing_status"] != "ended"
            or metadata["request_counts"]["processing"] != 0
        ):
            reasons.append("provider_results_not_terminal")
        counts = {
            key: sum(row["provider_status"] == key for row in report["rows"])
            for key in ("succeeded", "errored", "expired", "canceled")
        }
        if any(metadata["request_counts"][key] != value for key, value in counts.items()):
            reasons.append("metadata_result_counts_mismatch")
    if report["complete"] and not reasons:
        # The strict parser already validated every line/ID. Normalize whitespace
        # and row ordering for identity, while exact raw bytes remain retained.
        items = {
            item["custom_id"]: item
            for item in (json.loads(line) for line in receipt["results"].splitlines())
        }
        semantic = fingerprint(items)
    _withhold(report, reasons)
    return report, semantic, items


def evaluate(connection, payload, *, now):
    """Fresh fenced evaluation without consuming review capacity or choosing a receipt."""
    from src.two_bot import batch_contract as contract

    validate(connection)
    _require(
        isinstance(payload, dict)
        and set(payload) == {"job_id", "owner", "fence", "receipt_id", "current_context"},
        "invalid_result_review_fields",
    )
    context = payload["current_context"]
    _require(
        isinstance(context, dict) and set(context) == contract._CONTEXT, "invalid_review_context"
    )
    context = dict(context)
    for field in contract._CONTEXT - {"publication_epoch"}:
        contract._sha(context[field])
    contract._id(context["publication_epoch"])
    at = _at(connection, now)
    job = payload["job_id"]
    status = worker.apply(connection, "status", {"job_id": job}, now=at)
    worker._owner(worker._lease(connection, job), payload, utc_datetime(at))
    worker.spend_journal._sha(payload["receipt_id"])
    receipts = _receipts(connection, job, status["grant_id"])
    selected = next((r for r in receipts if r["receipt_id"] == payload["receipt_id"]), None)
    _require(selected is not None, "batch_result_receipt_not_found")
    registration = batch_journal.read(connection, job)
    plan_raw = domain_journal.read_artifact(connection, registration["plan_sha256"])
    plan = batch_journal._plan(plan_raw, registration["plan_sha256"])
    decoded = {
        r["receipt_id"]: _decode(plan_raw, plan, r, context, at, status["provider_batch_id"])
        for r in receipts
    }
    report, semantic, items = decoded[payload["receipt_id"]]
    choices = {value[1] for value in decoded.values() if value[1] is not None}
    choice = connection.execute(
        "SELECT * FROM batch_result_choices WHERE job_id=?", (job,)
    ).fetchone()
    if choice:
        chosen = decoded.get(choice["receipt_id"])
        # A later provider-ID conflict can temporarily make every receipt
        # ineligible. It must not erase the retained earlier accounting choice.
        if status["provider_batch_id"] is not None:
            _require(
                chosen is not None and chosen[1] == choice["semantic_sha256"],
                "changed_result_choice",
            )
        choices.add(choice["semantic_sha256"])
    if len(choices) > 1:
        _withhold(report, ["conflicting_complete_results"])
    if status["state"] != "submitted":
        _withhold(report, ["submission_not_confirmed"])
    for row in report["rows"]:
        row["candidate_id"] = (
            fingerprint(
                dict(
                    plan_sha256=registration["plan_sha256"],
                    custom_id=row["custom_id"],
                    item=items[row["custom_id"]],
                )
            )
            if row["eligible_for_checks"]
            else None
        )
    binding = dict(
        job_id=job,
        receipt_id=payload["receipt_id"],
        plan_sha256=registration["plan_sha256"],
        receipt_set_sha256=fingerprint([r["receipt_id"] for r in receipts]),
        submission_revision_sha256=fingerprint(
            dict(
                grant_id=status["grant_id"],
                state=status["state"],
                provider_batch_id=status["provider_batch_id"],
                acknowledgments=[
                    dict(r) for r in worker._receipts(connection, job, plan["samples"])
                ],
            )
        ),
        current_context=context,
        reviewed_at=at,
        owner=payload["owner"],
        fence=payload["fence"],
    )
    review_id = fingerprint(binding)
    document = dict(binding=binding, report=report, review_id=review_id, semantic_sha256=semantic)
    return document


def review(connection, payload, *, now):
    document = evaluate(connection, payload, now=now)
    binding = document["binding"]
    job, at, review_id = binding["job_id"], binding["reviewed_at"], document["review_id"]
    semantic = document["semantic_sha256"]
    if (semantic and "conflicting_complete_results" not in document["report"]["context_blocked_reasons"]
            and not connection.execute(
                "SELECT 1 FROM batch_result_choices WHERE job_id=?", (job,)
            ).fetchone()):
        connection.execute(
            "INSERT INTO batch_result_choices VALUES(?,?,?)", (job, payload["receipt_id"], semantic)
        )
    encoded = canonical_json(document).encode()
    _require(len(encoded) <= 4_000_000, "oversized_result_review")
    sha = hashlib.sha256(encoded).hexdigest()
    prior = connection.execute(
        "SELECT report_sha256 FROM batch_result_reviews WHERE review_id=?", (review_id,)
    ).fetchone()
    if prior:
        _require(
            prior[0] == sha and domain_journal.read_artifact(connection, sha) == encoded,
            "changed_result_review",
        )
    else:
        _require(
            connection.execute(
                "SELECT COUNT(*) FROM batch_result_reviews WHERE job_id=?", (job,)
            ).fetchone()[0]
            < MAX_REVIEWS,
            "result_review_capacity",
        )
        domain_journal._artifact(connection, encoded)
        connection.execute(
            "INSERT INTO batch_result_reviews VALUES(?,?,?,?,?,?)",
            (review_id, job, payload["receipt_id"], payload["fence"], sha, at),
        )
    return dict(document, report_sha256=sha, reused=bool(prior), publication_approved=False)
