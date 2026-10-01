"""Immutable raw check observations, retained before provider output is parsed.

Separate additive schema: existing candidate/check grants are unchanged. Nothing
here interprets a provider verdict, releases a spending hold or approves posting.
"""

from __future__ import annotations

import json
import sqlite3

from src.commands import check_journal as checks, domain_journal, spend_journal
from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint

MAX_RESPONSE_BYTES = 131_072
MAX_PACKET_BYTES = 3 * checks.MAX_INPUT_BYTES + checks.MAX_RECEIPT_BYTES
_TABLES = {
    "check_execution_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "check_observations": "grant_id TEXT PRIMARY KEY REFERENCES check_attempts(grant_id), metadata_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), raw_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), recorded_at TEXT NOT NULL",
}


def _objects():
    objects = {}
    for name, columns in _TABLES.items():
        objects[name] = f"CREATE TABLE {name} ({columns})"
        for action in ("UPDATE", "DELETE"):
            key = f"{name}_no_{action.lower()}"
            objects[key] = (
                f"CREATE TRIGGER {key} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable check observation'); END"
            )
        key = f"{name}_no_replace"
        match = (
            "singleton=NEW.singleton"
            if name == "check_execution_schema"
            else "grant_id=NEW.grant_id"
        )
        objects[key] = (
            f"CREATE TRIGGER {key} BEFORE INSERT ON {name} WHEN EXISTS(SELECT 1 FROM {name} WHERE {match}) BEGIN SELECT RAISE(ABORT, 'immutable check observation'); END"
        )
    return objects


SCHEMA_SHA256 = fingerprint(_objects())


def validate(connection):
    checks.validate(connection)
    try:
        row = connection.execute(
            "SELECT schema_sha256 FROM check_execution_schema WHERE singleton=1"
        ).fetchone()
        checks._require(
            row is not None and row[0] == SCHEMA_SHA256, "changed_check_execution_schema"
        )
        for name, sql in _objects().items():
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            checks._require(row is not None and row[0] == sql, "changed_check_execution_schema")
    except sqlite3.DatabaseError:
        raise checks.CheckJournalError("check_execution_migration_required") from None


def install(connection):
    checks.validate(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name='check_execution_schema'"
    ).fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO check_execution_schema VALUES(1,?)", (SCHEMA_SHA256,))


def observation(connection, grant_id):
    row = connection.execute(
        "SELECT * FROM check_observations WHERE grant_id=?", (grant_id,)
    ).fetchone()
    if row is None:
        return None
    data = json.loads(domain_journal.read_artifact(connection, row["metadata_sha256"]))
    checks._require(
        data["grant_id"] == grant_id and data["raw_sha256"] == row["raw_sha256"],
        "changed_check_observation",
    )
    return data


def read(connection, payload):
    validate(connection)
    checks._shape(payload, {"check_set_id"})
    packet = checks._packet(connection, payload["check_set_id"])
    attempts = {}
    for stage in checks.STAGES:
        attempt = checks._attempt(connection, payload["check_set_id"], stage)
        if attempt:
            attempts[stage] = dict(
                attempt, observation=observation(connection, attempt["grant_id"])
            )
    return dict(packet=packet, attempts=attempts, publication_approved=False)


def _bounded_artifact(connection, digest, low, high):
    spend_journal._sha(digest)
    size = connection.execute(
        "SELECT byte_count,length(payload),typeof(payload) FROM domain_artifacts WHERE sha256=?", (digest,)
    ).fetchone()
    checks._require(size is not None and type(size[0]) is int and size[2] == "blob"
                    and low <= size[0] == size[1] <= high, "invalid_scoped_check_artifact_size")
    raw = domain_journal.read_artifact(connection, digest)
    checks._require(type(raw) is bytes and len(raw) == size[0], "invalid_scoped_check_artifact_bytes")
    return raw


def _scoped_attempt(connection, identity, stage, grant_id):
    validate(connection)
    spend_journal._sha(identity)
    spend_journal._sha(grant_id)
    checks._require(stage in checks.STAGES, "unknown_required_check")
    row = connection.execute("SELECT packet_sha256 FROM check_sets WHERE check_set_id=?", (identity,)).fetchone()
    checks._require(row is not None, "check_set_not_found")
    packet_raw = _bounded_artifact(connection, row[0], 1, MAX_PACKET_BYTES)
    packet = checks._packet(connection, identity)
    checks._require(checks._encoded(packet, MAX_PACKET_BYTES) == packet_raw, "changed_check_set")
    row = connection.execute("SELECT binding_sha256 FROM check_attempts WHERE check_set_id=? AND stage=?", (identity, stage)).fetchone()
    checks._require(row is not None, "unknown_check_grant")
    binding_raw = _bounded_artifact(connection, row[0], 1, 8192)
    attempt = checks._attempt(connection, identity, stage)
    checks._require(attempt is not None and attempt["grant_id"] == grant_id, "unknown_check_grant")
    binding = attempt["binding"]
    checks._shape(binding, {"check_set_id", "stage", "request_sha256", "reservation", "owner", "fence", "begun_at"})
    checks._require(checks._encoded(binding, 8192) == binding_raw
                    and type(binding["fence"]) is int and binding["begun_at"] == attempt["recorded_at"], "changed_check_attempt")
    utc_datetime(attempt["recorded_at"])
    return attempt


def read_request(connection, identity, stage, grant_id):
    attempt = _scoped_attempt(connection, identity, stage, grant_id)
    return _bounded_artifact(connection, attempt["binding"]["request_sha256"], 1, checks.MAX_INPUT_BYTES)


def read_response(connection, identity, stage, grant_id):
    attempt = _scoped_attempt(connection, identity, stage, grant_id)
    row = connection.execute("SELECT metadata_sha256,raw_sha256,recorded_at FROM check_observations WHERE grant_id=?", (grant_id,)).fetchone()
    checks._require(row is not None, "check_observation_not_found")
    encoded = _bounded_artifact(connection, row[0], 1, 4096)
    data = json.loads(encoded)
    checks._shape(data, {"check_set_id", "stage", "grant_id", "request_sha256", "raw_sha256", "http_status", "complete", "reason"})
    checks._require(checks._encoded(data, 4096) == encoded and data["check_set_id"] == identity
                    and data["stage"] == stage and data["grant_id"] == grant_id
                    and data["request_sha256"] == attempt["binding"]["request_sha256"]
                    and data["raw_sha256"] == row[1], "changed_check_observation")
    status, reason = data["http_status"], data["reason"]
    checks._require(type(data["complete"]) is bool, "invalid_check_observation_completeness")
    checks._require(status is None or (type(status) is int and 100 <= status <= 599), "invalid_check_http_status")
    checks._require(reason in ("local", "received", "transport_unavailable", "size_exceeded", "time_exceeded", "cleanup_failed"), "invalid_check_observation_reason")
    checks._require((stage == "deterministic") == (reason == "local")
                    and data["complete"] == (reason in ("local", "received"))
                    and (status is None if reason == "local" else not data["complete"] or status is not None), "inconsistent_check_observation")
    stamp = utc_datetime(row[2])
    checks._require(stamp.isoformat(timespec="microseconds").replace("+00:00", "Z") == row[2]
                    and stamp >= utc_datetime(attempt["recorded_at"]), "invalid_check_observation_time")
    return _bounded_artifact(connection, row[1], 0, MAX_RESPONSE_BYTES)


def record(connection, payload, *, raw, now):
    validate(connection)
    checks._shape(
        payload,
        {
            "check_set_id",
            "stage",
            "grant_id",
            "request_sha256",
            "raw_sha256",
            "http_status",
            "complete",
            "reason",
        },
    )
    checks._require(payload["stage"] in checks.STAGES, "unknown_required_check")
    checks._packet(connection, payload["check_set_id"])
    attempt = checks._attempt(connection, payload["check_set_id"], payload["stage"])
    checks._require(
        attempt is not None and attempt["grant_id"] == payload["grant_id"], "unknown_check_grant"
    )
    checks._require(
        payload["request_sha256"] == attempt["binding"]["request_sha256"],
        "check_observation_request_mismatch",
    )
    checks._require(
        type(raw) is bytes and len(raw) <= MAX_RESPONSE_BYTES, "invalid_check_observation_bytes"
    )
    checks._require(
        domain_journal._digest(raw) == payload["raw_sha256"], "check_observation_digest_mismatch"
    )
    checks._require(type(payload["complete"]) is bool, "invalid_check_observation_completeness")
    status = payload["http_status"]
    checks._require(
        status is None or (type(status) is int and 100 <= status <= 599),
        "invalid_check_http_status",
    )
    checks._require(
        payload["reason"]
        in {
            "local",
            "received",
            "transport_unavailable",
            "size_exceeded",
            "time_exceeded",
            "cleanup_failed",
        },
        "invalid_check_observation_reason",
    )
    checks._require(
        (payload["stage"] == "deterministic") == (payload["reason"] == "local"),
        "invalid_local_check_observation",
    )
    checks._require(
        payload["complete"] == (payload["reason"] in {"received", "local"})
        and (
            status is None
            if payload["reason"] == "local"
            else not payload["complete"] or status is not None
        ),
        "inconsistent_check_observation",
    )
    at = checks._at(connection, now)
    latest = connection.execute("SELECT MAX(recorded_at) FROM check_observations").fetchone()[0]
    checks._require(
        utc_datetime(at) >= utc_datetime(attempt["recorded_at"])
        and (latest is None or at >= latest),
        "observation_clock_went_backwards",
    )
    previous = observation(connection, payload["grant_id"])
    if previous:
        checks._require(
            previous == payload
            and domain_journal.read_artifact(connection, payload["raw_sha256"]) == raw,
            "conflicting_check_observation",
        )
        return dict(reused=True, raw_retained=True, publication_approved=False)
    encoded = canonical_json(payload).encode()
    checks._require(len(encoded) <= 4096, "oversized_check_observation_metadata")
    domain_journal._artifact(connection, raw)
    sha = domain_journal._artifact(connection, encoded)
    connection.execute(
        "INSERT INTO check_observations VALUES(?,?,?,?)",
        (payload["grant_id"], sha, payload["raw_sha256"], at),
    )
    return dict(reused=False, raw_retained=True, publication_approved=False)
