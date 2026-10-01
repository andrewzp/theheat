"""Immutable local check response evidence; no interpretation or provider calls.

The authority owns the core lock and commit. Retention grants neither a pass nor
another attempt, and never settles the unknown charge held by a check grant.
"""
from __future__ import annotations

import json

from src.commands import check_journal as checks, postgres_checks as pg
from src.commands import postgres_spending as spend, spend_journal as s
from src.storage import postgres_projection as p

SCHEMA = "theheat_check_executions"
MIGRATION = p.MIGRATION.with_name("008_check_observations.sql")
MAX_RESPONSE_BYTES = 131_072
_ARTIFACTS = {"raw_artifacts": (0, MAX_RESPONSE_BYTES), "metadata_artifacts": (1, 4096)}
_FIELDS = {"check_set_id", "stage", "grant_id", "request_sha256", "raw_sha256",
           "http_status", "complete", "reason"}


def validate(c, environment):
    pg.validate(c, environment)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise checks.CheckJournalError("check_execution_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    checks._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_check_execution_schema")
    checks._require(row[2] == p._catalog(c, SCHEMA), "changed_check_execution_schema")
    checks._require(row[3] == environment, "check_execution_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    checks._require(tuple(row[4:]) == roles, "check_execution_role_mismatch")


def install(c, environment):
    pg.validate(c, environment)
    if c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        validate(c, environment)
        return
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    driver = p._driver()
    c.execute(MIGRATION.read_text())
    role = driver.sql.Identifier(roles[1])
    for target in (f"SCHEMA {SCHEMA}", f"ALL TABLES IN SCHEMA {SCHEMA}", f"ALL FUNCTIONS IN SCHEMA {SCHEMA}"):
        c.execute(f"REVOKE ALL ON {target} FROM PUBLIC")
        c.execute(driver.sql.SQL(f"REVOKE ALL ON {target} FROM {{}}").format(role))
    tables = ",".join(f"{SCHEMA}.{t}" for t in (*_ARTIFACTS, "observations"))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {tables} TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _raw(c, table, digest):
    s._sha(digest)
    low, high = _ARTIFACTS[table]
    size = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()
    checks._require(size is not None and type(size[0]) is int and low <= size[0] == size[1] <= high, "invalid_check_observation_size")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()[0]
    checks._require(type(raw) is bytes and len(raw) == size[0] and p._sha(raw) == digest, "changed_check_observation_bytes")
    return raw


def _artifact(c, table, raw):
    low, high = _ARTIFACTS[table]
    checks._require(type(raw) is bytes and low <= len(raw) <= high, "invalid_check_observation_bytes")
    digest = p._sha(raw)
    c.execute(f"INSERT INTO {SCHEMA}.{table} VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (digest, raw, len(raw)))
    checks._require(_raw(c, table, digest) == raw, "changed_check_observation_bytes")
    return digest


def _metadata(value):
    checks._shape(value, _FIELDS)
    for key in ("check_set_id", "grant_id", "request_sha256", "raw_sha256"):
        s._sha(value[key])
    checks._require(value["stage"] in checks.STAGES, "unknown_required_check")
    checks._require(type(value["complete"]) is bool, "invalid_check_observation_completeness")
    status, reason = value["http_status"], value["reason"]
    checks._require(status is None or (type(status) is int and 100 <= status <= 599), "invalid_check_http_status")
    checks._require(reason in ("local", "received", "transport_unavailable", "size_exceeded", "time_exceeded", "cleanup_failed"), "invalid_check_observation_reason")
    checks._require((value["stage"] == "deterministic") == (reason == "local"), "invalid_local_check_observation")
    checks._require(value["complete"] == (reason in ("local", "received"))
                    and (status is None if reason == "local" else not value["complete"] or status is not None), "inconsistent_check_observation")


def _observation(c, identity, stage, attempt):
    row = c.execute(f"SELECT metadata_sha256,raw_sha256,recorded_at FROM {SCHEMA}.observations WHERE grant_id=%s", (attempt["grant_id"],)).fetchone()
    if row is None:
        return None
    meta_sha, raw_sha, at = row
    encoded = _raw(c, "metadata_artifacts", meta_sha)
    data = p._decode(encoded)
    _metadata(data)
    checks._require(checks._encoded(data, 4096) == encoded
                    and data["check_set_id"] == identity and data["stage"] == stage
                    and data["grant_id"] == attempt["grant_id"]
                    and data["request_sha256"] == attempt["binding"]["request_sha256"]
                    and data["raw_sha256"] == raw_sha, "changed_check_observation")
    checks._require(spend._time(at) == at and at >= attempt["recorded_at"], "invalid_check_observation_time")
    _raw(c, "raw_artifacts", raw_sha)
    return data


def _read(c, identity, environment):
    packet, enrolled = pg._packet(c, identity, environment)
    _, attempts = pg._stages(c, identity, packet, enrolled)
    return dict(packet=packet, attempts={
        stage: dict(attempt, check_set_id=identity, stage=stage,
                    binding_sha256=p._sha(checks._encoded(attempt["binding"], 8192)),
                    intent_id=(attempt["binding"]["reservation"]["intent_id"]
                               if attempt["binding"]["reservation"] is not None else None),
                    observation=_observation(c, identity, stage, attempt))
        for stage, attempt in attempts.items() if attempt is not None
    }, publication_approved=False)


def apply(c, action, payload, *, now, environment, raw=None):
    checks._require(isinstance(action, str) and action in ("read", "observe")
                    and (action != "read" or raw is None), "unknown_check_execution_action")
    checks._shape(payload, {"check_set_id"} if action == "read" else _FIELDS)
    # Detach before any SQL can reuse mutable caller-owned metadata.
    payload = json.loads(checks._encoded(payload, 4096))
    at = spend._time(now)
    validate(c, environment)
    if action == "read":
        return _read(c, payload["check_set_id"], environment)
    _metadata(payload)
    checks._require(type(raw) is bytes and len(raw) <= MAX_RESPONSE_BYTES, "invalid_check_observation_bytes")
    checks._require(p._sha(raw) == payload["raw_sha256"], "check_observation_digest_mismatch")
    packet, enrolled = pg._packet(c, payload["check_set_id"], environment)
    _, attempts = pg._stages(c, payload["check_set_id"], packet, enrolled)
    attempt = attempts[payload["stage"]]
    checks._require(attempt is not None and attempt["grant_id"] == payload["grant_id"], "unknown_check_grant")
    checks._require(attempt["binding"]["request_sha256"] == payload["request_sha256"], "check_observation_request_mismatch")
    pg._at(c, at)
    latest = c.execute(f"SELECT MAX(recorded_at) FROM {SCHEMA}.observations").fetchone()[0]
    checks._require(at >= attempt["recorded_at"] and (latest is None or at >= latest), "observation_clock_went_backwards")
    previous = _observation(c, payload["check_set_id"], payload["stage"], attempt)
    if previous is not None:
        checks._require(previous == payload and _raw(c, "raw_artifacts", payload["raw_sha256"]) == raw, "conflicting_check_observation")
        return dict(reused=True, raw_retained=True, publication_approved=False)
    _artifact(c, "raw_artifacts", raw)
    meta_sha = _artifact(c, "metadata_artifacts", checks._encoded(payload, 4096))
    c.execute(f"INSERT INTO {SCHEMA}.observations VALUES(%s,%s,%s,%s)",
              (payload["grant_id"], meta_sha, payload["raw_sha256"], at))
    return dict(reused=False, raw_retained=True, publication_approved=False)


def _scoped_attempt(c, identity, stage, grant_id, environment):
    s._sha(identity)
    s._sha(grant_id)
    checks._require(stage in checks.STAGES, "unknown_required_check")
    validate(c, environment)
    saved = _read(c, identity, environment)
    attempt = saved["attempts"].get(stage)
    checks._require(attempt is not None and attempt["grant_id"] == grant_id, "unknown_check_grant")
    return attempt


def read_request(c, identity, stage, grant_id, *, environment):
    attempt = _scoped_attempt(c, identity, stage, grant_id, environment)
    return pg._raw(c, "request_artifacts", attempt["binding"]["request_sha256"])


def read_response(c, identity, stage, grant_id, *, environment):
    attempt = _scoped_attempt(c, identity, stage, grant_id, environment)
    checks._require(attempt["observation"] is not None, "check_observation_not_found")
    return _raw(c, "raw_artifacts", attempt["observation"]["raw_sha256"])
