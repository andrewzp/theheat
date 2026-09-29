"""Local fenced batch ownership and acknowledgment evidence. No provider transport."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import re
import sqlite3

from src.commands import batch_journal, domain_journal, spend_journal
from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint

MAX_LEASES = 1000
MAX_RECEIPTS = 16
MAX_ACK_BYTES = 65536
_CONTEXT = {"bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"}
_COUNTS = {"processing", "succeeded", "errored", "canceled", "expired"}
_PROVIDER_ID = re.compile(r"msgbatch_[A-Za-z0-9_-]{1,128}")
_TABLES = {
    "batch_worker_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "batch_worker_leases": "job_id TEXT NOT NULL REFERENCES batch_jobs(job_id), fence INTEGER NOT NULL CHECK(fence>0), owner TEXT NOT NULL, expires_at TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(job_id,fence)",
    "batch_worker_submissions": "job_id TEXT PRIMARY KEY REFERENCES batch_jobs(job_id), fence INTEGER NOT NULL, grant_id TEXT NOT NULL UNIQUE, recorded_at TEXT NOT NULL, FOREIGN KEY(job_id,fence) REFERENCES batch_worker_leases(job_id,fence)",
    "batch_worker_uncertainties": "job_id TEXT PRIMARY KEY REFERENCES batch_worker_submissions(job_id), recorded_at TEXT NOT NULL",
    "batch_worker_acks": "job_id TEXT NOT NULL REFERENCES batch_worker_submissions(job_id), receipt_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), provider_id TEXT, recorded_at TEXT NOT NULL, PRIMARY KEY(job_id,receipt_sha256)",
    "batch_worker_adoptions": "job_id TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL, provider_id TEXT NOT NULL UNIQUE, recorded_at TEXT NOT NULL, FOREIGN KEY(job_id,receipt_sha256) REFERENCES batch_worker_acks(job_id,receipt_sha256)",
}


class BatchWorkerError(ValueError):
    """Bounded diagnostics without request text, credentials or provider bodies."""


def _require(condition, code):
    if not condition:
        raise BatchWorkerError(code)


def _objects():
    objects = {}
    for table, columns in _TABLES.items():
        objects[table] = f"CREATE TABLE {table} ({columns})"
        for action in ("UPDATE", "DELETE"):
            name = f"{table}_no_{action.lower()}"
            objects[name] = (
                f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable batch worker journal'); END"
            )
        key = "job_id=NEW.job_id"
        if table == "batch_worker_schema":
            key = "singleton=NEW.singleton"
        elif table == "batch_worker_leases":
            key += " AND fence=NEW.fence"
        elif table == "batch_worker_acks":
            key += " AND receipt_sha256=NEW.receipt_sha256"
        elif table == "batch_worker_submissions":
            key += " OR grant_id=NEW.grant_id"
        elif table == "batch_worker_adoptions":
            key += " OR provider_id=NEW.provider_id"
        name = f"{table}_no_replace"
        objects[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}) BEGIN SELECT RAISE(ABORT, 'immutable batch worker journal'); END"
        )
    return objects


SCHEMA_SHA256 = fingerprint(_objects())


def validate(connection):
    _require(connection.in_transaction, "batch_worker_requires_transaction")
    batch_journal.validate(connection)
    try:
        row = connection.execute("SELECT * FROM batch_worker_schema WHERE singleton=1").fetchone()
        _require(row is not None and row["schema_sha256"] == SCHEMA_SHA256, "changed_worker_schema")
        for name, sql in _objects().items():
            actual = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            _require(actual is not None and actual["sql"] == sql, "changed_worker_schema")
    except sqlite3.DatabaseError:
        raise BatchWorkerError("batch_worker_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "batch_worker_requires_transaction")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='batch_worker_schema'"
    ).fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO batch_worker_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _shape(value, fields):
    _require(isinstance(value, dict) and set(value) == fields, "invalid_worker_fields")


def _one(connection, table, job):
    return connection.execute(f"SELECT * FROM {table} WHERE job_id=?", (job,)).fetchone()


def _lease(connection, job):
    lease = connection.execute(
        "SELECT * FROM batch_worker_leases WHERE job_id=? ORDER BY fence DESC LIMIT 1", (job,)
    ).fetchone()
    if lease:
        count = connection.execute(
            "SELECT COUNT(*) FROM batch_worker_leases WHERE job_id=?", (job,)
        ).fetchone()[0]
        spend_journal._id(lease["owner"])
        duration = (
            utc_datetime(lease["expires_at"]) - utc_datetime(lease["recorded_at"])
        ).total_seconds()
        _require(
            lease["fence"] == count <= MAX_LEASES and 1 <= duration <= 300, "changed_batch_lease"
        )
    return lease


def _grant(registration, lease, at):
    return fingerprint(
        {key: registration[key] for key in ("job_id", "plan_sha256", "intent_id")}
        | dict(owner=lease["owner"], fence=lease["fence"], granted_at=at)
    )


def _submission(connection, registration):
    row = _one(connection, "batch_worker_submissions", registration["job_id"])
    if row:
        lease = connection.execute(
            "SELECT * FROM batch_worker_leases WHERE job_id=? AND fence=?",
            (registration["job_id"], row["fence"]),
        ).fetchone()
        _require(
            lease is not None
            and row["grant_id"] == _grant(registration, lease, row["recorded_at"]),
            "changed_batch_grant",
        )
        _require(
            utc_datetime(lease["recorded_at"])
            <= utc_datetime(row["recorded_at"])
            < utc_datetime(lease["expires_at"]),
            "invalid_batch_grant_time",
        )
    return row


def _owner(lease, payload, stamp):
    _require(type(payload["fence"]) is int and payload["fence"] > 0, "invalid_worker_fence")
    spend_journal._id(payload["owner"])
    _require(
        lease is not None
        and lease["owner"] == payload["owner"]
        and lease["fence"] == payload["fence"],
        "stale_batch_owner",
    )
    _require(stamp < utc_datetime(lease["expires_at"]), "batch_lease_expired")


def _object(pairs):
    obj = {}
    for key, value in pairs:
        _require(key not in obj, "duplicate_ack_key")
        obj[key] = value
    return obj


def _ack_id(raw, samples):
    # Extra provider fields remain raw evidence. Only identifiers/counts are used;
    # even a valid results_url is never fetched by this journal.
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
        fingerprint(value)  # Reject nonfinite or otherwise non-JSON values.
        _require(
            isinstance(value, dict) and value.get("type") == "message_batch", "invalid_ack_type"
        )
        identity = value.get("id")
        _require(isinstance(identity, str) and _PROVIDER_ID.fullmatch(identity), "invalid_batch_id")
        _require(
            value.get("processing_status") in ("in_progress", "canceling", "ended"),
            "invalid_ack_status",
        )
        counts = value.get("request_counts")
        _require(isinstance(counts, dict) and set(counts) == _COUNTS, "invalid_ack_counts")
        _require(
            all(type(counts[k]) is int and 0 <= counts[k] <= samples for k in _COUNTS),
            "invalid_ack_counts",
        )
        _require(sum(counts.values()) == samples, "ack_request_count_mismatch")
        _require(
            value["processing_status"] != "ended" or counts["processing"] == 0, "invalid_ended_ack"
        )
        return identity
    except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError):
        return None


def _receipts(connection, job, samples):
    _require(
        connection.execute(
            "SELECT COUNT(*) FROM batch_worker_acks WHERE job_id=?", (job,)
        ).fetchone()[0]
        <= MAX_RECEIPTS,
        "batch_receipt_capacity",
    )
    rows = connection.execute(
        "SELECT * FROM batch_worker_acks WHERE job_id=? ORDER BY recorded_at,receipt_sha256", (job,)
    ).fetchall()
    for row in rows:
        size = connection.execute(
            "SELECT byte_count FROM domain_artifacts WHERE sha256=?", (row["receipt_sha256"],)
        ).fetchone()
        _require(size is not None and 0 <= size[0] <= MAX_ACK_BYTES, "invalid_ack_artifact_size")
        raw = domain_journal.read_artifact(connection, row["receipt_sha256"])
        _require(_ack_id(raw, samples) == row["provider_id"], "changed_ack_binding")
    return rows


def _conflict(connection, rows):
    ids = {r["provider_id"] for r in rows if r["provider_id"] is not None}
    if len(ids) > 1:
        return True
    return any(
        connection.execute(
            "SELECT COUNT(DISTINCT job_id) FROM batch_worker_acks WHERE provider_id=?", (identity,)
        ).fetchone()[0]
        > 1
        for identity in ids
    )


def _uncertain(connection, registration, now):
    job = registration["job_id"]
    if _one(connection, "batch_worker_uncertainties", job) is None:
        connection.execute("INSERT INTO batch_worker_uncertainties VALUES(?,?)", (job, now))
    if registration["reservation_state"] == "dispatched":
        spend_journal.apply(
            connection, "uncertain", {"intent_id": registration["intent_id"]}, now=now
        )


def _view(connection, registration, plan, stamp):
    job = registration["job_id"]
    lease = _lease(connection, job)
    submission = _submission(connection, registration)
    adoption = _one(connection, "batch_worker_adoptions", job)
    receipts = _receipts(connection, job, plan["samples"])
    conflict = _conflict(connection, receipts)
    state = "reserved"
    if submission is None:
        if registration["reservation_state"] != "reserved":
            state = "reservation_" + registration["reservation_state"]
    elif conflict:
        state = "acknowledgment_conflict"
    elif adoption:
        _require(
            any(
                r["receipt_sha256"] == adoption["receipt_sha256"]
                and r["provider_id"] == adoption["provider_id"]
                for r in receipts
            ),
            "changed_adoption_binding",
        )
        state = "submitted"
    elif (
        _one(connection, "batch_worker_uncertainties", job) is not None
        or lease is None
        or lease["fence"] != submission["fence"]
        or stamp >= utc_datetime(lease["expires_at"])
    ):
        state = "submission_uncertain"
    else:
        state = "submitting"
    return dict(
        registration,
        state=state,
        lease=dict(lease) if lease else None,
        lease_active=bool(lease and stamp < utc_datetime(lease["expires_at"])),
        grant_id=submission["grant_id"] if submission else None,
        provider_batch_id=adoption["provider_id"] if adoption and not conflict else None,
        receipt_count=len(receipts),
        invalid_receipt_count=sum(r["provider_id"] is None for r in receipts),
        useful=stamp < utc_datetime(plan["useful_until"]),
        accounting_complete=False,
        collection_granted=False,
    )


def apply(connection, action, payload, *, now, raw=None):
    validate(connection)
    fields = {
        "status": {"job_id"},
        "acquire": {"job_id", "owner", "ttl_seconds"},
        "begin": {"job_id", "owner", "fence", "current_context"},
        "uncertain": {"job_id", "owner", "fence"},
        "observe_ack": {"job_id", "grant_id", "receipt_sha256"},
        "adopt": {"job_id", "owner", "fence", "receipt_sha256"},
    }
    _require(action in fields, "unknown_worker_action")
    _shape(payload, fields[action])
    _require(len(canonical_json(payload).encode()) <= 4096, "oversized_worker_payload")
    fingerprint(payload)
    _require(raw is None or action == "observe_ack", "unexpected_worker_bytes")
    stamp = utc_datetime(now)
    at = stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")
    latest = connection.execute(
        "SELECT MAX(recorded_at) FROM ("
        + " UNION ALL ".join(
            f"SELECT recorded_at FROM {table}"
            for table in _TABLES
            if table != "batch_worker_schema"
        )
        + ")"
    ).fetchone()[0]
    _require(latest is None or stamp >= utc_datetime(latest), "worker_clock_went_backwards")
    job = payload["job_id"]
    registration = batch_journal.read(connection, job)
    _require(
        stamp >= utc_datetime(registration["registered_at"]), "worker_clock_before_registration"
    )
    plan = batch_journal._plan(
        domain_journal.read_artifact(connection, registration["plan_sha256"]),
        registration["plan_sha256"],
    )
    lease, submission = _lease(connection, job), _submission(connection, registration)
    granted = False
    reused = False
    if action == "acquire":
        spend_journal._id(payload["owner"])
        ttl = payload["ttl_seconds"]
        _require(type(ttl) is int and 1 <= ttl <= 300, "invalid_lease_ttl")
        if lease and stamp < utc_datetime(lease["expires_at"]):
            _require(lease["owner"] == payload["owner"], "batch_lease_busy")
            reused = True
        else:
            fence = 1 if lease is None else lease["fence"] + 1
            _require(fence <= MAX_LEASES, "batch_lease_capacity")
            if submission and _one(connection, "batch_worker_adoptions", job) is None:
                _uncertain(connection, registration, at)
            expires = (
                (stamp + timedelta(seconds=ttl))
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )
            connection.execute(
                "INSERT INTO batch_worker_leases VALUES(?,?,?,?,?)",
                (job, fence, payload["owner"], expires, at),
            )
    elif action == "begin":
        _owner(lease, payload, stamp)
        context = payload["current_context"]
        _shape(context, _CONTEXT)
        _require(all(context[key] == plan[key] for key in _CONTEXT), "changed_batch_context")
        _require(
            (utc_datetime(plan["useful_until"]) - stamp).total_seconds()
            > plan["minimum_window_seconds"],
            "batch_submission_outside_window",
        )
        if submission:
            reused = True
        else:
            _require(
                registration["reservation_state"] == "reserved", "batch_reservation_not_available"
            )
            grant = _grant(registration, lease, at)
            dispatch = spend_journal.apply(
                connection, "dispatch", {"intent_id": registration["intent_id"]}, now=at
            )
            _require(dispatch["dispatch_granted"], "batch_reservation_not_available")
            connection.execute(
                "INSERT INTO batch_worker_submissions VALUES(?,?,?,?)",
                (job, payload["fence"], grant, at),
            )
            granted = True
    elif action == "uncertain":
        _owner(lease, payload, stamp)
        _require(submission is not None, "batch_not_submitted")
        _require(_one(connection, "batch_worker_adoptions", job) is None, "batch_already_adopted")
        _uncertain(connection, registration, at)
    elif action == "observe_ack":
        spend_journal._sha(payload["grant_id"])
        spend_journal._sha(payload["receipt_sha256"])
        _require(
            submission is not None and submission["grant_id"] == payload["grant_id"],
            "unknown_batch_grant",
        )
        _require(type(raw) is bytes and len(raw) <= MAX_ACK_BYTES, "invalid_or_oversized_ack")
        _require(hashlib.sha256(raw).hexdigest() == payload["receipt_sha256"], "changed_ack_bytes")
        prior = connection.execute(
            "SELECT 1 FROM batch_worker_acks WHERE job_id=? AND receipt_sha256=?",
            (job, payload["receipt_sha256"]),
        ).fetchone()
        if prior:
            reused = True
        else:
            _require(
                connection.execute(
                    "SELECT COUNT(*) FROM batch_worker_acks WHERE job_id=?", (job,)
                ).fetchone()[0]
                < MAX_RECEIPTS,
                "batch_receipt_capacity",
            )
            # Preserve malformed raw bytes as evidence; parsing cannot discard a
            # potentially charged response or grant it authoritative status.
            domain_journal._artifact(connection, raw)
            identity = _ack_id(raw, plan["samples"])
            connection.execute(
                "INSERT INTO batch_worker_acks VALUES(?,?,?,?)",
                (job, payload["receipt_sha256"], identity, at),
            )
    elif action == "adopt":
        _owner(lease, payload, stamp)
        spend_journal._sha(payload["receipt_sha256"])
        receipts = _receipts(connection, job, plan["samples"])
        _require(not _conflict(connection, receipts), "conflicting_batch_acknowledgments")
        receipt = next(
            (r for r in receipts if r["receipt_sha256"] == payload["receipt_sha256"]), None
        )
        if receipt is None or receipt["provider_id"] is None:
            raise BatchWorkerError("invalid_or_missing_batch_ack")
        prior = _one(connection, "batch_worker_adoptions", job)
        if prior:
            _require(
                prior["provider_id"] == receipt["provider_id"], "batch_provider_identity_changed"
            )
            reused = True
        else:
            connection.execute(
                "INSERT INTO batch_worker_adoptions VALUES(?,?,?,?)",
                (job, receipt["receipt_sha256"], receipt["provider_id"], at),
            )
    report = _view(connection, batch_journal.read(connection, job), plan, stamp)
    return dict(report, reused=reused, dispatch_granted=granted)
