"""Experimental exact candidate checks; local adapter records never approve posting.

All transitions share the caller's SQLite write transaction. One grant per stage
prevents silent repurchase after a crash; receipts retain evidence and unknown cost.
"""

from __future__ import annotations

import json
import sqlite3

from src.commands import batch_journal, batch_result_journal as results
from src.commands import batch_worker_journal as worker, domain_journal, spend_journal
from src.commands.schema import canonical_json, utc_datetime
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, text_hash

STAGES = ("deterministic", "safety", "fact_check", "critic")
MAX_SETS = 100_000
MAX_INPUT_BYTES = 2_000_000
MAX_RECEIPT_BYTES = 1_000_000
_TABLES = {
    "check_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "check_sets": "check_set_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES batch_jobs(job_id), custom_id TEXT NOT NULL, packet_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), recorded_at TEXT NOT NULL, UNIQUE(job_id,custom_id)",
    "check_attempts": "grant_id TEXT PRIMARY KEY, check_set_id TEXT NOT NULL REFERENCES check_sets(check_set_id), stage TEXT NOT NULL CHECK(stage IN ('deterministic','safety','fact_check','critic')), binding_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), intent_id TEXT UNIQUE REFERENCES spend_intents(intent_id), recorded_at TEXT NOT NULL, UNIQUE(check_set_id,stage)",
    "check_receipts": "grant_id TEXT PRIMARY KEY REFERENCES check_attempts(grant_id), receipt_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), disposition TEXT NOT NULL CHECK(disposition IN ('passed','rejected','error','unavailable','stale')), recorded_at TEXT NOT NULL",
}
_BASE = {"check_set_id", "owner", "fence", "current_context"}
_REVIEW_FIELDS = {"job_id", "owner", "fence", "receipt_id", "current_context"}


class CheckJournalError(ValueError):
    """Bounded diagnostic codes only."""


def _require(condition, code):
    if not condition:
        raise CheckJournalError(code)


def _shape(value, keys):
    _require(isinstance(value, dict) and set(value) == keys, "invalid_check_fields")


def _objects():
    objects = {}
    for name, columns in _TABLES.items():
        objects[name] = f"CREATE TABLE {name} ({columns})"
        for action in ("UPDATE", "DELETE"):
            trigger = f"{name}_no_{action.lower()}"
            objects[trigger] = (
                f"CREATE TRIGGER {trigger} BEFORE {action} ON {name} BEGIN SELECT RAISE(ABORT, 'immutable checks'); END"
            )
        key = {
            "check_schema": "singleton=NEW.singleton",
            "check_sets": "check_set_id=NEW.check_set_id OR (job_id=NEW.job_id AND custom_id=NEW.custom_id)",
            "check_attempts": "grant_id=NEW.grant_id OR (check_set_id=NEW.check_set_id AND stage=NEW.stage) OR intent_id=NEW.intent_id",
            "check_receipts": "grant_id=NEW.grant_id",
        }[name]
        trigger = f"{name}_no_replace"
        objects[trigger] = (
            f"CREATE TRIGGER {trigger} BEFORE INSERT ON {name} WHEN EXISTS(SELECT 1 FROM {name} WHERE {key}) BEGIN SELECT RAISE(ABORT, 'immutable checks'); END"
        )
    return objects


SCHEMA_SHA256 = fingerprint(_objects())


def validate(connection):
    _require(connection.in_transaction, "checks_require_transaction")
    results.validate(connection)
    try:
        row = connection.execute(
            "SELECT schema_sha256 FROM check_schema WHERE singleton=1"
        ).fetchone()
        _require(row is not None and row[0] == SCHEMA_SHA256, "changed_check_schema")
        for name, sql in _objects().items():
            actual = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name=?", (name,)
            ).fetchone()
            _require(actual is not None and actual[0] == sql, "changed_check_schema")
    except sqlite3.DatabaseError:
        raise CheckJournalError("check_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "checks_require_transaction")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='check_schema'").fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO check_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _at(connection, now):
    stamp = utc_datetime(now)
    latest = connection.execute(
        "SELECT MAX(recorded_at) FROM (SELECT recorded_at FROM check_sets UNION ALL SELECT recorded_at FROM check_attempts UNION ALL SELECT recorded_at FROM check_receipts)"
    ).fetchone()[0]
    _require(latest is None or stamp >= utc_datetime(latest), "check_clock_went_backwards")
    return stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _encoded(value, bound):
    fingerprint(value)
    raw = canonical_json(value).encode()
    _require(len(raw) <= bound, "oversized_check_packet")
    return raw


def _policy(context):
    policy = current_editorial_policy()
    if policy is None or fingerprint(policy) != context.get("policy_sha256"):
        raise CheckJournalError("current_check_policy_unavailable")
    _require(
        policy["flags"]["critic_enabled"] and policy["flags"]["safety_llm_enabled"],
        "required_checks_disabled",
    )
    return policy


def _review(connection, payload, now):
    _policy(payload["current_context"])
    return results.evaluate(connection, payload, now=now)


def intake(connection, payload, *, now):
    validate(connection)
    _shape(payload, _REVIEW_FIELDS | {"custom_id", "bundle", "memory"})
    at = _at(connection, now)
    _require(isinstance(payload["current_context"], dict), "invalid_check_context")
    for key in ("bundle", "memory"):
        _require(isinstance(payload[key], dict), "missing_check_input")
        _encoded(payload[key], MAX_INPUT_BYTES)
        _require(
            fingerprint(payload[key]) == payload["current_context"].get(key + "_sha256"),
            "changed_check_input",
        )
    review_input = {k: payload[k] for k in _REVIEW_FIELDS}
    review = _review(connection, review_input, at)
    row = next(
        (r for r in review["report"]["rows"] if r["custom_id"] == payload["custom_id"]), None
    )
    if row is None or row["eligible_for_checks"] is not True:
        raise CheckJournalError("batch_candidate_ineligible")
    registration = batch_journal.read(connection, payload["job_id"])
    plan = batch_journal._plan(
        domain_journal.read_artifact(connection, registration["plan_sha256"]),
        registration["plan_sha256"],
    )
    packet = dict(
        schema_version=1,
        job_id=payload["job_id"],
        custom_id=payload["custom_id"],
        candidate_id=row["candidate_id"],
        candidate=row["candidate"],
        text_sha256=text_hash(row["candidate"]["tweet"]),
        plan_sha256=registration["plan_sha256"],
        current_context=payload["current_context"],
        useful_until=plan["useful_until"],
        policy=plan["policy"],
        bundle=payload["bundle"],
        memory=payload["memory"],
        required_stages=list(STAGES),
    )
    raw = _encoded(packet, 2 * MAX_INPUT_BYTES + MAX_RECEIPT_BYTES)
    identity = fingerprint(packet)
    prior = connection.execute(
        "SELECT * FROM check_sets WHERE job_id=? AND custom_id=?",
        (payload["job_id"], payload["custom_id"]),
    ).fetchone()
    if prior:
        _require(
            prior["check_set_id"] == identity
            and domain_journal.read_artifact(connection, prior["packet_sha256"]) == raw,
            "conflicting_check_candidate",
        )
    else:
        _require(
            connection.execute("SELECT COUNT(*) FROM check_sets").fetchone()[0] < MAX_SETS,
            "check_set_capacity",
        )
        results.review(connection, review_input, now=at)
        sha = domain_journal._artifact(connection, raw)
        connection.execute(
            "INSERT INTO check_sets VALUES(?,?,?,?,?)",
            (identity, payload["job_id"], payload["custom_id"], sha, at),
        )
    return dict(
        check_set_id=identity,
        reused=bool(prior),
        required_checks_completed=False,
        publication_approved=False,
        dispatch_granted=False,
    )


def _packet(connection, identity):
    spend_journal._sha(identity)
    row = connection.execute(
        "SELECT * FROM check_sets WHERE check_set_id=?", (identity,)
    ).fetchone()
    _require(row is not None, "check_set_not_found")
    packet = json.loads(domain_journal.read_artifact(connection, row["packet_sha256"]))
    _require(
        fingerprint(packet) == identity
        and packet["job_id"] == row["job_id"]
        and packet["custom_id"] == row["custom_id"],
        "changed_check_set",
    )
    return packet


def _current(connection, packet, payload, at):
    _require(isinstance(payload["current_context"], dict), "invalid_check_context")
    _require(payload["current_context"] == packet["current_context"], "changed_check_context")
    index = results.index(connection, {"job_id": packet["job_id"]}, now=at)
    _require(index["chosen_receipt_id"] is not None, "check_result_unavailable")
    review = _review(
        connection,
        dict(
            job_id=packet["job_id"],
            owner=payload["owner"],
            fence=payload["fence"],
            receipt_id=index["chosen_receipt_id"],
            current_context=payload["current_context"],
        ),
        at,
    )
    row = next((r for r in review["report"]["rows"] if r["custom_id"] == packet["custom_id"]), None)
    _require(
        row is not None
        and row["eligible_for_checks"]
        and row["candidate_id"] == packet["candidate_id"],
        "check_candidate_no_longer_current",
    )


def _attempt(connection, identity, stage):
    row = connection.execute(
        "SELECT * FROM check_attempts WHERE check_set_id=? AND stage=?", (identity, stage)
    ).fetchone()
    if row is None:
        return None
    binding = json.loads(domain_journal.read_artifact(connection, row["binding_sha256"]))
    _require(
        fingerprint(binding) == row["grant_id"]
        and binding["check_set_id"] == identity
        and binding["stage"] == stage,
        "changed_check_attempt",
    )
    return dict(row, binding=binding)


def _stage_status(connection, attempt):
    if attempt is None:
        return "pending"
    receipt = connection.execute(
        "SELECT * FROM check_receipts WHERE grant_id=?", (attempt["grant_id"],)
    ).fetchone()
    if receipt is None:
        return "unresolved"
    doc = json.loads(domain_journal.read_artifact(connection, receipt["receipt_sha256"]))
    _require(doc["grant_id"] == attempt["grant_id"], "changed_check_receipt")
    return receipt["disposition"]


def status(connection, payload, *, now):
    validate(connection)
    _shape(payload, _BASE)
    at = _at(connection, now)
    packet = _packet(connection, payload["check_set_id"])
    reason = None
    try:
        _current(connection, packet, payload, at)
    except (CheckJournalError, results.BatchResultError, worker.BatchWorkerError):
        reason = "check_context_not_current"
    stages = {
        stage: _stage_status(connection, _attempt(connection, payload["check_set_id"], stage))
        for stage in STAGES
    }
    return dict(
        check_set_id=payload["check_set_id"],
        stages=stages,
        blocked_reason=reason,
        required_checks_completed=reason is None and all(v == "passed" for v in stages.values()),
        publication_approved=False,
        dispatch_granted=False,
        accounting_complete=False,
        cost_usd=None,
    )


def begin(connection, payload, *, request, now):
    validate(connection)
    _shape(payload, _BASE | {"stage", "reservation"})
    at = _at(connection, now)
    packet = _packet(connection, payload["check_set_id"])
    _current(connection, packet, payload, at)
    stage = payload["stage"]
    _require(stage in STAGES, "unknown_required_check")
    _require(
        type(request) is bytes and 0 < len(request) <= MAX_INPUT_BYTES, "invalid_check_request"
    )
    request_sha = domain_journal._digest(request)
    prior = _attempt(connection, payload["check_set_id"], stage)
    if prior:
        _require(
            prior["binding"]["request_sha256"] == request_sha
            and prior["binding"]["reservation"] == payload["reservation"],
            "conflicting_check_attempt",
        )
        return dict(grant_id=prior["grant_id"], dispatch_granted=False, publication_approved=False)
    for prerequisite in STAGES[: STAGES.index(stage)]:
        _require(
            _stage_status(connection, _attempt(connection, payload["check_set_id"], prerequisite))
            == "passed",
            "required_predecessor_not_passed",
        )
    reservation = payload["reservation"]
    intent_id = None
    if stage == "deterministic":
        _require(reservation is None, "local_check_cannot_spend")
    else:
        spend_journal._intent(reservation)
        _require(
            reservation["job_id"] == packet["job_id"]
            and reservation["role"] == stage
            and reservation["request_sha256"] == request_sha
            and reservation["provider"] == "google"
            and reservation["model"] == packet["policy"]["models"][stage],
            "check_reservation_mismatch",
        )
        intent_id = reservation["intent_id"]
        existing = spend_journal._records(connection).get(intent_id)
        _require(existing is None or existing["state"] == "reserved", "check_spend_already_used")
        spend_journal.apply(connection, "reserve", reservation, now=at)
        grant = spend_journal.apply(connection, "dispatch", {"intent_id": intent_id}, now=at)
        _require(grant["dispatch_granted"], "check_spend_not_granted")
    binding = dict(
        check_set_id=payload["check_set_id"],
        stage=stage,
        request_sha256=request_sha,
        reservation=reservation,
        owner=payload["owner"],
        fence=payload["fence"],
        begun_at=at,
    )
    grant_id = fingerprint(binding)
    domain_journal._artifact(connection, request)
    sha = domain_journal._artifact(connection, _encoded(binding, 8192))
    connection.execute(
        "INSERT INTO check_attempts VALUES(?,?,?,?,?,?)",
        (grant_id, payload["check_set_id"], stage, sha, intent_id, at),
    )
    return dict(grant_id=grant_id, dispatch_granted=True, publication_approved=False)


def complete(connection, payload, *, receipt, now):
    """Retain trusted adapter output, including late outcomes, without retry/settle.

    execution_status describes actual execution, independently of verdict. Raw
    provider self-reported success must be interpreted by the real check adapter.
    """
    validate(connection)
    _shape(payload, _BASE | {"stage", "grant_id"})
    at = _at(connection, now)
    packet = _packet(connection, payload["check_set_id"])
    _require(payload["stage"] in STAGES, "unknown_required_check")
    attempt = _attempt(connection, payload["check_set_id"], payload["stage"])
    _require(
        attempt is not None and attempt["grant_id"] == payload["grant_id"], "unknown_check_grant"
    )
    binding = attempt["binding"]
    _require(
        type(payload["fence"]) is int
        and payload["owner"] == binding["owner"]
        and payload["fence"] == binding["fence"],
        "check_receipt_owner_mismatch",
    )
    _shape(
        receipt, {"grant_id", "request_sha256", "execution_status", "verdict", "result", "usage"}
    )
    _require(
        receipt["grant_id"] == attempt["grant_id"]
        and receipt["request_sha256"] == binding["request_sha256"],
        "check_receipt_binding_mismatch",
    )
    execution, verdict = receipt["execution_status"], receipt["verdict"]
    _require(execution in ("completed", "error", "unavailable"), "invalid_check_execution")
    _require(
        verdict in ("pass", "reject") if execution == "completed" else verdict is None,
        "invalid_check_verdict",
    )
    _require(
        isinstance(receipt["result"], dict)
        and (receipt["usage"] is None or isinstance(receipt["usage"], dict)),
        "invalid_check_result",
    )
    raw = _encoded(receipt, MAX_RECEIPT_BYTES)
    sha = domain_journal._digest(raw)
    prior = connection.execute(
        "SELECT * FROM check_receipts WHERE grant_id=?", (attempt["grant_id"],)
    ).fetchone()
    if prior:
        _require(
            prior["receipt_sha256"] == sha and domain_journal.read_artifact(connection, sha) == raw,
            "conflicting_check_completion",
        )
        return dict(reused=True, disposition=prior["disposition"], publication_approved=False)
    disposition = (
        ("passed" if verdict == "pass" else "rejected") if execution == "completed" else execution
    )
    try:
        _current(connection, packet, payload, at)
    except (CheckJournalError, results.BatchResultError, worker.BatchWorkerError):
        disposition = "stale"
    domain_journal._artifact(connection, raw)
    connection.execute(
        "INSERT INTO check_receipts VALUES(?,?,?,?)", (attempt["grant_id"], sha, disposition, at)
    )
    return dict(reused=False, disposition=disposition, publication_approved=False)
