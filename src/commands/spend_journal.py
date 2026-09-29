"""Experimental local spending holds, not production billing or a provider client."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3

from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint

MAX_AMOUNT = 10**12
MAX_INTENTS = 100_000
_TABLES = {
    "spend_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "spend_limits": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), limits_json TEXT NOT NULL, recorded_at TEXT NOT NULL",
    "spend_intents": "intent_id TEXT PRIMARY KEY, intent_sha256 TEXT NOT NULL, intent_json TEXT NOT NULL, recorded_at TEXT NOT NULL",
    "spend_events": "sequence INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL REFERENCES spend_intents(intent_id), kind TEXT NOT NULL CHECK(kind IN ('dispatched','uncertain','released','settled')), recorded_at TEXT NOT NULL, amount_micro_usd INTEGER, evidence_sha256 TEXT, UNIQUE(intent_id,kind)",
}
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,159}")
_SHA = re.compile(r"[0-9a-f]{64}")
_LIMITS = {"daily_micro_usd", "monthly_micro_usd", "per_job_micro_usd", "authorization_sha256"}
_INTENT = {
    "intent_id",
    "job_id",
    "request_sha256",
    "provider",
    "model",
    "role",
    "estimate_sha256",
    "reserve_micro_usd",
}


class SpendError(ValueError):
    """Bounded error code, never a provider response or unpublished request."""


def _require(condition, code):
    if not condition:
        raise SpendError(code)


def _objects():
    result = {}
    for table, columns in _TABLES.items():
        result[table] = f"CREATE TABLE {table} ({columns})"
        for action in ("UPDATE", "DELETE"):
            name = f"{table}_no_{action.lower()}"
            result[name] = (
                f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable spending journal'); END"
            )
        key = (
            "singleton=NEW.singleton"
            if table in ("spend_schema", "spend_limits")
            else "intent_id=NEW.intent_id"
        )
        if table == "spend_events":
            key = "sequence=NEW.sequence OR (intent_id=NEW.intent_id AND kind=NEW.kind)"
        name = f"{table}_no_replace"
        result[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}) BEGIN SELECT RAISE(ABORT, 'immutable spending journal'); END"
        )
    return result


SCHEMA_SHA256 = hashlib.sha256(canonical_json(_objects()).encode()).hexdigest()


def validate(connection):
    _require(connection.in_transaction, "spending_requires_transaction")
    try:
        row = connection.execute("SELECT * FROM spend_schema WHERE singleton=1").fetchone()
        _require(row is not None and row["schema_sha256"] == SCHEMA_SHA256, "changed_spend_schema")
        for name, sql in _objects().items():
            actual = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            _require(actual is not None and actual["sql"] == sql, "changed_spend_schema")
    except sqlite3.DatabaseError:
        raise SpendError("spend_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "spending_requires_transaction")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='spend_schema'").fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO spend_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _shape(value, keys):
    _require(isinstance(value, dict) and set(value) == keys, "invalid_spend_fields")


def _id(value):
    _require(
        isinstance(value, str) and _ID.fullmatch(value) is not None, "invalid_spend_identifier"
    )


def _sha(value):
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None, "invalid_spend_sha")


def _amount(value, *, positive=False):
    _require(
        type(value) is int and int(positive) <= value <= MAX_AMOUNT, "invalid_micro_usd_amount"
    )


def _intent(value):
    _shape(value, _INTENT)
    for key in ("intent_id", "job_id", "model"):
        _id(value[key])
    for key in ("request_sha256", "estimate_sha256"):
        _sha(value[key])
    _require(value["provider"] in ("anthropic", "google"), "unknown_provider")
    _require(
        value["role"] in ("writer", "safety", "fact_check", "critic", "news", "repair"),
        "unknown_role",
    )
    _amount(value["reserve_micro_usd"], positive=True)


def _records(connection):
    _require(
        connection.execute("SELECT COUNT(*) FROM spend_intents").fetchone()[0] <= MAX_INTENTS,
        "spend_capacity_exceeded",
    )
    rows = connection.execute("""SELECT i.*, e.kind, e.recorded_at AS last_at,
        e.amount_micro_usd, e.evidence_sha256
        FROM spend_intents i LEFT JOIN spend_events e ON e.sequence=
        (SELECT MAX(sequence) FROM spend_events WHERE intent_id=i.intent_id)""").fetchall()
    _require(len(rows) <= MAX_INTENTS, "spend_capacity_exceeded")
    result = {}
    for row in rows:
        intent = json.loads(row["intent_json"])
        _intent(intent)
        _require(
            fingerprint(intent) == row["intent_sha256"] and intent["intent_id"] == row["intent_id"],
            "changed_spend_intent",
        )
        result[row["intent_id"]] = {
            "intent": intent,
            "state": row["kind"] or "reserved",
            "reserved_at": row["recorded_at"],
            "last_at": row["last_at"] or row["recorded_at"],
            "settled_micro_usd": row["amount_micro_usd"],
            "evidence_sha256": row["evidence_sha256"],
        }
    return result


def _totals(records, now, job_id=None):
    totals = {
        "daily_micro_usd": 0,
        "monthly_micro_usd": 0,
        "job_micro_usd": 0,
        "held_micro_usd": 0,
        "overrun_count": 0,
    }
    for record in records.values():
        state, intent = record["state"], record["intent"]
        if state == "released":
            continue
        held = state != "settled"
        amount = intent["reserve_micro_usd"] if held else record["settled_micro_usd"]
        _amount(amount)
        if held:
            totals["held_micro_usd"] += amount
        elif amount > intent["reserve_micro_usd"]:
            totals["overrun_count"] += 1
        if held or now[:10] in (record["reserved_at"][:10], record["last_at"][:10]):
            totals["daily_micro_usd"] += amount
        if held or now[:7] in (record["reserved_at"][:7], record["last_at"][:7]):
            totals["monthly_micro_usd"] += amount
        if job_id == intent["job_id"]:
            totals["job_micro_usd"] += amount
    return totals


def _event(connection, intent_id, kind, now, amount=None, evidence=None):
    connection.execute(
        "INSERT INTO spend_events(intent_id,kind,recorded_at,amount_micro_usd,evidence_sha256) VALUES(?,?,?,?,?)",
        (intent_id, kind, now, amount, evidence),
    )


def apply(connection, action, payload, *, now):
    """Apply within the authority's write transaction; caller commits or rolls back."""
    validate(connection)
    # Fixed-width microseconds make SQL MAX chronological even at subsecond
    # precision; variable-width ISO strings sort whole seconds incorrectly.
    now = utc_datetime(now).isoformat(timespec="microseconds").replace("+00:00", "Z")
    encoded = canonical_json(payload)
    _require(len(encoded.encode()) <= 4096, "oversized_spend_payload")
    fingerprint(payload)
    latest = connection.execute("""SELECT MAX(recorded_at) FROM (
        SELECT recorded_at FROM spend_limits UNION ALL SELECT recorded_at FROM spend_intents
        UNION ALL SELECT recorded_at FROM spend_events)""").fetchone()[0]
    _require(
        latest is None or utc_datetime(now) >= utc_datetime(latest), "spending_clock_went_backwards"
    )
    existing = connection.execute(
        "SELECT limits_json FROM spend_limits WHERE singleton=1"
    ).fetchone()
    if action == "configure":
        _shape(payload, _LIMITS)
        _sha(payload["authorization_sha256"])
        for key in _LIMITS - {"authorization_sha256"}:
            _amount(payload[key])
        if existing:
            _require(existing[0] == encoded, "spend_limits_immutable")
        else:
            connection.execute("INSERT INTO spend_limits VALUES(1,?,?)", (encoded, now))
        return {"configured": True, "limits": payload, "authorization_verified": False}
    _require(existing is not None, "spend_limits_not_configured")
    limits = json.loads(existing[0])
    _shape(limits, _LIMITS)
    _sha(limits["authorization_sha256"])
    for key in _LIMITS - {"authorization_sha256"}:
        _amount(limits[key])
    records = _records(connection)
    if action == "status":
        _require(
            isinstance(payload, dict) and set(payload) <= {"intent_id"}, "invalid_spend_fields"
        )
        identity = payload.get("intent_id")
        if identity is not None:
            _id(identity)
            _require(identity in records, "spend_intent_not_found")
        record = records.get(identity)
        return {
            "limits": limits,
            "totals": _totals(records, now, record["intent"]["job_id"] if record else None),
            "intent": record,
            "intent_count": len(records),
            "accounting_complete": False,
            "production_enforcement": False,
        }
    if action == "reserve":
        _intent(payload)
        identity = payload["intent_id"]
        if identity in records:
            _require(records[identity]["intent"] == payload, "spend_intent_id_reused")
            return {"intent": records[identity], "reused": True, "dispatch_granted": False}
        _require(len(records) < MAX_INTENTS, "spend_capacity_exceeded")
        totals = _totals(records, now, payload["job_id"])
        _require(totals["overrun_count"] == 0, "spending_overrun_requires_resolution")
        amount = payload["reserve_micro_usd"]
        for total, limit in (
            ("daily_micro_usd", "daily_micro_usd"),
            ("monthly_micro_usd", "monthly_micro_usd"),
            ("job_micro_usd", "per_job_micro_usd"),
        ):
            _require(totals[total] + amount <= limits[limit], "spending_allowance_exhausted")
        connection.execute(
            "INSERT INTO spend_intents VALUES(?,?,?,?)",
            (identity, fingerprint(payload), encoded, now),
        )
        return {
            "intent": {
                "intent": payload,
                "state": "reserved",
                "reserved_at": now,
                "last_at": now,
                "settled_micro_usd": None,
                "evidence_sha256": None,
            },
            "reused": False,
            "dispatch_granted": False,
        }
    _require(action in ("dispatch", "uncertain", "release", "settle"), "unknown_spending_action")
    fields = (
        {"intent_id", "amount_micro_usd", "evidence_sha256"}
        if action == "settle"
        else {"intent_id"}
    )
    _shape(payload, fields)
    identity = payload["intent_id"]
    _id(identity)
    _require(identity in records, "spend_intent_not_found")
    record = records[identity]
    state = record["state"]
    granted = False
    if action == "dispatch":
        if state == "reserved":
            totals = _totals(records, now, record["intent"]["job_id"])
            _require(totals["overrun_count"] == 0, "spending_overrun_requires_resolution")
            _event(connection, identity, "dispatched", now)
            granted = True
    elif action == "uncertain":
        _require(state in ("dispatched", "uncertain"), "spend_not_dispatched")
        if state == "dispatched":
            _event(connection, identity, "uncertain", now)
    elif action == "release":
        _require(state in ("reserved", "released"), "cannot_release_dispatched_spend")
        if state == "reserved":
            _event(connection, identity, "released", now)
    else:
        _amount(payload["amount_micro_usd"])
        _sha(payload["evidence_sha256"])
        _require(state in ("dispatched", "uncertain", "settled"), "spend_not_dispatched")
        if state == "settled":
            _require(
                record["settled_micro_usd"] == payload["amount_micro_usd"]
                and record["evidence_sha256"] == payload["evidence_sha256"],
                "conflicting_spend_settlement",
            )
        else:
            _event(
                connection,
                identity,
                "settled",
                now,
                payload["amount_micro_usd"],
                payload["evidence_sha256"],
            )
    updated = _records(connection)
    return {
        "intent": updated[identity],
        "dispatch_granted": granted,
        "totals": _totals(updated, now, record["intent"]["job_id"]),
    }
