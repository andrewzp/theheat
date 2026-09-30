"""Atomic local batch registration. No leases, provider calls or production use."""

from __future__ import annotations

import hashlib
import sqlite3

from src.commands import domain_journal, spend_journal
from src.commands.schema import canonical_json, utc_datetime

MAX_JOBS = 100_000
_TABLES = {
    "batch_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "batch_jobs": "job_id TEXT PRIMARY KEY, plan_sha256 TEXT NOT NULL UNIQUE REFERENCES domain_artifacts(sha256), intent_id TEXT NOT NULL UNIQUE REFERENCES spend_intents(intent_id), registered_at TEXT NOT NULL",
}


class BatchJournalError(ValueError):
    """Bounded error without request text or account information."""


def _require(condition, code):
    if not condition:
        raise BatchJournalError(code)


def _objects():
    objects = {}
    for name, columns in _TABLES.items():
        objects[name] = f"CREATE TABLE {name} ({columns})"
        for action in ("UPDATE", "DELETE"):
            trigger = f"{name}_no_{action.lower()}"
            objects[trigger] = (
                f"CREATE TRIGGER {trigger} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable batch registration'); END"
            )
        key = (
            "singleton=NEW.singleton" if name == "batch_schema"
            else "job_id=NEW.job_id OR plan_sha256=NEW.plan_sha256 OR intent_id=NEW.intent_id"
        )
        trigger = f"{name}_no_replace"
        objects[trigger] = (
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON {name} WHEN EXISTS(SELECT 1 FROM {name} WHERE {key}) BEGIN SELECT RAISE(ABORT, 'immutable batch registration'); END"
        )
    return objects


SCHEMA_SHA256 = hashlib.sha256(canonical_json(_objects()).encode()).hexdigest()


def validate(connection):
    _require(connection.in_transaction, "batch_requires_transaction")
    domain_journal.validate_schema(connection)
    spend_journal.validate(connection)
    try:
        row = connection.execute("SELECT * FROM batch_schema WHERE singleton=1").fetchone()
        _require(row is not None and row["schema_sha256"] == SCHEMA_SHA256, "changed_batch_schema")
        for name, sql in _objects().items():
            actual = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            _require(actual is not None and actual["sql"] == sql, "changed_batch_schema")
    except sqlite3.DatabaseError:
        raise BatchJournalError("batch_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "batch_requires_transaction")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='batch_schema'").fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO batch_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _plan(raw, sha):
    # Loading a writer contract is confined to explicit batch operations, not
    # ordinary authority initialization or command consumption.
    from src.two_bot.batch_contract import validated_batch_plan

    return validated_batch_plan(raw, expected_plan_sha256=sha)


def _join(plan, sha, reservation):
    spend_journal._intent(reservation)
    _require(
        reservation["job_id"] == plan["job_id"]
        and reservation["request_sha256"] == sha
        and reservation["model"] == plan["policy"]["models"]["writer"]
        and reservation["provider"] == "anthropic"
        and reservation["role"] == "writer",
        "batch_reservation_binding_mismatch",
    )


def read(connection, job_id):
    validate(connection)
    spend_journal._id(job_id)
    row = connection.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
    _require(row is not None, "batch_job_not_found")
    raw = domain_journal.read_artifact(connection, row["plan_sha256"])
    plan = _plan(raw, row["plan_sha256"])
    intent = spend_journal._records(connection).get(row["intent_id"])
    _require(intent is not None and plan["job_id"] == job_id, "changed_batch_binding")
    _join(plan, row["plan_sha256"], intent["intent"])
    stamp = utc_datetime(row["registered_at"])
    _require(
        stamp >= utc_datetime(plan["created_at"])
        and (utc_datetime(plan["useful_until"]) - stamp).total_seconds() > plan["minimum_window_seconds"],
        "invalid_batch_registration_time",
    )
    return {
        "job_id": job_id,
        "plan_sha256": row["plan_sha256"],
        "intent_id": row["intent_id"],
        "registered_at": row["registered_at"],
        "useful_until": plan["useful_until"],
        "reservation_state": intent["state"],
        "dispatch_granted": False,
        "publication_approved": False,
    }


def register(connection, plan_bytes, *, expected_plan_sha256, reservation, now):
    validate(connection)
    stamp = utc_datetime(now)
    at = stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")
    plan = _plan(plan_bytes, expected_plan_sha256)
    _join(plan, expected_plan_sha256, reservation)
    existing = connection.execute("SELECT * FROM batch_jobs WHERE job_id=?", (plan["job_id"],)).fetchone()
    if existing:
        _require(
            existing["plan_sha256"] == expected_plan_sha256
            and existing["intent_id"] == reservation["intent_id"],
            "batch_job_id_reused",
        )
        saved = spend_journal._records(connection).get(existing["intent_id"])
        _require(saved is not None and saved["intent"] == reservation, "batch_reservation_changed")
        return dict(read(connection, plan["job_id"]), reused=True)
    _require(
        stamp >= utc_datetime(plan["created_at"])
        and (utc_datetime(plan["useful_until"]) - stamp).total_seconds() > plan["minimum_window_seconds"],
        "batch_registration_outside_window",
    )
    _require(connection.execute("SELECT COUNT(*) FROM batch_jobs").fetchone()[0] < MAX_JOBS, "batch_capacity_exceeded")
    _require(
        connection.execute("SELECT 1 FROM batch_jobs WHERE plan_sha256=? OR intent_id=?",
            (expected_plan_sha256, reservation["intent_id"])).fetchone() is None,
        "batch_identity_reused",
    )
    # All writes belong to the caller's single transaction. A failed job insert,
    # byte verification or commit rolls back a newly created hold as well.
    hold = spend_journal.apply(connection, "reserve", reservation, now=at)
    _require(hold["intent"]["state"] == "reserved", "batch_attempt_already_used")
    domain_journal._artifact(connection, plan_bytes)
    connection.execute("INSERT INTO batch_jobs VALUES(?,?,?,?)",
        (plan["job_id"], expected_plan_sha256, reservation["intent_id"], at))
    return dict(read(connection, plan["job_id"]), reused=False)
