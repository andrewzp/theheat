"""Exact local PostgreSQL candidate checks; no executor, settlement or approval.

The authority owns the core row lock and transaction. Adapter receipts describe
trusted local execution, not independently verified provider or scientific truth.
"""
from __future__ import annotations

import json

from src.commands import batch_journal as b, check_journal as checks, spend_journal as s
from src.commands import postgres_batch as batch, postgres_batch_results as results, postgres_spending as spend
from src.commands import batch_result_journal as r, batch_worker_journal as w
from src.commands.schema import canonical_json
from src.editorial.revisions import fingerprint, text_hash
from src.storage import postgres_projection as p

SCHEMA = "theheat_checks"
MIGRATION = p.MIGRATION.with_name("007_candidate_checks.sql")
MAX_PACKET_BYTES = 7_000_000
_ARTIFACTS = {"packet_artifacts": MAX_PACKET_BYTES, "request_artifacts": checks.MAX_INPUT_BYTES,
              "binding_artifacts": 8192, "receipt_artifacts": checks.MAX_RECEIPT_BYTES}
_PACKET_FIELDS = {"schema_version", "job_id", "custom_id", "candidate_id", "candidate", "text_sha256",
                  "plan_sha256", "current_context", "useful_until", "policy", "bundle", "memory",
                  "required_stages", "checker_state", "checker_state_sha256", "check_date"}


def validate(c, environment):
    results.validate(c, environment)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise checks.CheckJournalError("check_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    checks._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_check_schema")
    checks._require(row[2] == p._catalog(c, SCHEMA), "changed_check_schema")
    checks._require(row[3] == environment, "check_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    checks._require(tuple(row[4:]) == roles, "check_role_mismatch")


def install(c, environment):
    results.validate(c, environment)
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
    tables = ",".join(f"{SCHEMA}.{t}" for t in (*_ARTIFACTS, "sets", "attempts", "receipts"))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {tables} TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _at(c, now):
    at = spend._time(now)
    latest = c.execute(f"SELECT MAX(recorded_at) FROM (SELECT MAX(recorded_at) AS recorded_at FROM {SCHEMA}.sets UNION ALL SELECT MAX(recorded_at) FROM {SCHEMA}.attempts UNION ALL SELECT MAX(recorded_at) FROM {SCHEMA}.receipts) clocks").fetchone()[0]
    checks._require(latest is None or at >= latest, "check_clock_went_backwards")
    return at


def _raw(c, table, digest):
    s._sha(digest)
    size = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()
    checks._require(size is not None and type(size[0]) is int and 1 <= size[0] == size[1] <= _ARTIFACTS[table], "invalid_check_artifact_size")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()[0]
    checks._require(type(raw) is bytes and len(raw) == size[0] and p._sha(raw) == digest, "changed_check_artifact")
    return raw


def _artifact(c, table, raw):
    checks._require(type(raw) is bytes and 1 <= len(raw) <= _ARTIFACTS[table], "oversized_check_packet")
    digest = p._sha(raw)
    c.execute(f"INSERT INTO {SCHEMA}.{table} VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (digest, raw, len(raw)))
    checks._require(_raw(c, table, digest) == raw, "changed_check_artifact")
    return digest


def _document(c, table, digest):
    raw = _raw(c, table, digest)
    doc = p._decode(raw)
    checks._require(isinstance(doc, dict) and checks._encoded(doc, _ARTIFACTS[table]) == raw, "changed_check_document")
    return doc


def _review(c, payload, at, environment):
    checks._policy(payload["current_context"])
    return results.evaluate(c, payload, now=at, environment=environment)


def _packet(c, identity, environment):
    s._sha(identity)
    row = c.execute(f"SELECT job_id,custom_id,packet_sha256,recorded_at FROM {SCHEMA}.sets WHERE check_set_id=%s", (identity,)).fetchone()
    checks._require(row is not None, "check_set_not_found")
    job, custom, digest, at = row
    packet = _document(c, "packet_artifacts", digest)
    checks._shape(packet, _PACKET_FIELDS)
    checks._require(type(packet["schema_version"]) is int and packet["schema_version"] == 1
                    and fingerprint(packet) == identity and packet["job_id"] == job
                    and packet["custom_id"] == custom and packet["required_stages"] == list(checks.STAGES), "changed_check_set")
    registration = batch.read(c, job, environment=environment)
    plan = b._plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    from src.two_bot.batch_contract import _CONTEXT

    checks._require(packet["plan_sha256"] == registration["plan_sha256"]
                    and packet["useful_until"] == plan["useful_until"]
                    and canonical_json(packet["policy"]) == canonical_json(plan["policy"])
                    and packet["current_context"] == {key: plan[key] for key in _CONTEXT}
                    and any(item["custom_id"] == custom for item in plan["requests"]), "changed_check_set")
    for name in ("bundle", "memory", "checker_state"):
        checks._require(isinstance(packet[name], dict), "changed_check_set")
        checks._encoded(packet[name], checks.MAX_INPUT_BYTES)
        expected = packet["checker_state_sha256"] if name == "checker_state" else packet["current_context"][name + "_sha256"]
        checks._require(fingerprint(packet[name]) == expected, "changed_check_set")
    candidate = packet["candidate"]
    checks._require(isinstance(candidate, dict) and isinstance(candidate.get("tweet"), str)
                    and text_hash(candidate["tweet"]) == packet["text_sha256"], "changed_check_set")
    s._sha(packet["candidate_id"])
    checks._require(spend._time(at) == at and registration["registered_at"] <= at
                    and at < spend._time(packet["useful_until"]) and packet["check_date"] == at[:10], "invalid_check_set_time")
    return packet, at


def _current(c, packet, payload, at, environment):
    s._sha(payload["checker_state_sha256"])
    checks._require(payload["checker_state_sha256"] == packet["checker_state_sha256"], "changed_checker_state")
    checks._require(isinstance(payload["current_context"], dict), "invalid_check_context")
    checks._require(payload["current_context"] == packet["current_context"], "changed_check_context")
    index = results.index(c, {"job_id": packet["job_id"]}, now=at, environment=environment)
    checks._require(index["chosen_receipt_id"] is not None, "check_result_unavailable")
    review = _review(c, dict(job_id=packet["job_id"], owner=payload["owner"], fence=payload["fence"],
        receipt_id=index["chosen_receipt_id"], current_context=payload["current_context"]), at, environment)
    row = next((row for row in review["report"]["rows"] if row["custom_id"] == packet["custom_id"]), None)
    checks._require(row is not None and row["eligible_for_checks"] and row["candidate_id"] == packet["candidate_id"]
                    and fingerprint(row["candidate"]) == fingerprint(packet["candidate"]), "check_candidate_no_longer_current")
    checks._require(at[:10] == packet["check_date"], "changed_checker_calendar_day")


def _reservation(reservation, packet, stage, request_sha):
    s._intent(reservation)
    checks._require(reservation["job_id"] == packet["job_id"] and reservation["role"] == stage
                    and reservation["request_sha256"] == request_sha and reservation["provider"] == "google"
                    and reservation["model"] == packet["policy"]["models"][stage], "check_reservation_mismatch")


def _attempt(c, identity, stage, packet, enrolled_at):
    row = c.execute(f"SELECT grant_id,binding_sha256,request_sha256,intent_id,recorded_at FROM {SCHEMA}.attempts WHERE check_set_id=%s AND stage=%s", (identity, stage)).fetchone()
    if row is None:
        return None
    grant, sha, request_sha, intent, at = row
    binding = _document(c, "binding_artifacts", sha)
    checks._shape(binding, {"check_set_id", "stage", "request_sha256", "reservation", "owner", "fence", "begun_at"})
    checks._require(fingerprint(binding) == grant and binding["check_set_id"] == identity
                    and binding["stage"] == stage and binding["request_sha256"] == request_sha
                    and binding["begun_at"] == at and spend._time(at) == at
                    and enrolled_at <= at < spend._time(packet["useful_until"])
                    and at[:10] == packet["check_date"] and type(binding["fence"]) is int, "changed_check_attempt")
    _raw(c, "request_artifacts", request_sha)
    lease = c.execute("SELECT owner,recorded_at,expires_at FROM theheat_batch_work.leases WHERE job_id=%s AND fence=%s", (packet["job_id"], binding["fence"])).fetchone()
    checks._require(lease is not None and lease[0] == binding["owner"] and lease[1] <= at < lease[2], "changed_check_attempt")
    if stage == "deterministic":
        checks._require(intent is None and binding["reservation"] is None, "changed_check_attempt")
    else:
        _reservation(binding["reservation"], packet, stage, request_sha)
        hold = spend._record(c, intent)
        dispatch = c.execute("SELECT recorded_at FROM theheat_spending.events WHERE intent_id=%s AND kind='dispatched'", (intent,)).fetchone()
        checks._require(hold is not None and canonical_json(hold["intent"]) == canonical_json(binding["reservation"])
                        and hold["intent"]["intent_id"] == intent and dispatch == (at,), "changed_check_attempt")
    return dict(grant_id=grant, binding=binding, recorded_at=at)


def _receipt_doc(receipt, attempt):
    checks._shape(receipt, {"grant_id", "request_sha256", "execution_status", "verdict", "result", "usage"})
    checks._require(receipt["grant_id"] == attempt["grant_id"]
                    and receipt["request_sha256"] == attempt["binding"]["request_sha256"], "check_receipt_binding_mismatch")
    execution, verdict = receipt["execution_status"], receipt["verdict"]
    checks._require(execution in ("completed", "error", "unavailable"), "invalid_check_execution")
    checks._require(verdict in ("pass", "reject") if execution == "completed" else verdict is None, "invalid_check_verdict")
    checks._require(isinstance(receipt["result"], dict) and (receipt["usage"] is None or isinstance(receipt["usage"], dict)), "invalid_check_result")
    return ("passed" if verdict == "pass" else "rejected") if execution == "completed" else execution


def _terminal(c, attempt):
    row = c.execute(f"SELECT receipt_sha256,disposition,recorded_at FROM {SCHEMA}.receipts WHERE grant_id=%s", (attempt["grant_id"],)).fetchone()
    if row is None:
        return None
    digest, disposition, at = row
    doc = _document(c, "receipt_artifacts", digest)
    expected = _receipt_doc(doc, attempt)
    checks._require(disposition in (expected, "stale") and spend._time(at) == at
                    and at >= attempt["recorded_at"], "changed_check_receipt")
    return dict(sha256=digest, disposition=disposition, recorded_at=at, document=doc)


def _stages(c, identity, packet, enrolled_at):
    stages = {}
    attempts = {}
    previous_at = enrolled_at
    for stage in checks.STAGES:
        attempt = _attempt(c, identity, stage, packet, enrolled_at)
        attempts[stage] = attempt
        if attempt is None:
            stages[stage] = "pending"
            continue
        checks._require(all(value == "passed" for value in stages.values())
                        and attempt["recorded_at"] >= previous_at, "changed_check_stage_order")
        terminal = _terminal(c, attempt)
        stages[stage] = terminal["disposition"] if terminal else "unresolved"
        previous_at = terminal["recorded_at"] if terminal else attempt["recorded_at"]
    return stages, attempts


def _intake(c, payload, at, environment):
    checks._require(isinstance(payload["current_context"], dict), "invalid_check_context")
    for key in ("bundle", "memory"):
        checks._require(isinstance(payload[key], dict), "missing_check_input")
        checks._require(fingerprint(payload[key]) == payload["current_context"].get(key + "_sha256"), "changed_check_input")
    checks._require(isinstance(payload["checker_state"], dict), "missing_checker_state")
    review_input = {key: payload[key] for key in checks._REVIEW_FIELDS}
    review = _review(c, review_input, at, environment)
    row = next((row for row in review["report"]["rows"] if row["custom_id"] == payload["custom_id"]), None)
    checks._require(row is not None and row["eligible_for_checks"] is True, "batch_candidate_ineligible")
    assert row is not None
    registration = batch.read(c, payload["job_id"], environment=environment)
    plan = b._plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    packet = dict(schema_version=1, job_id=payload["job_id"], custom_id=payload["custom_id"],
        candidate_id=row["candidate_id"], candidate=row["candidate"], text_sha256=text_hash(row["candidate"]["tweet"]),
        plan_sha256=registration["plan_sha256"], current_context=payload["current_context"], useful_until=plan["useful_until"],
        policy=plan["policy"], bundle=payload["bundle"], memory=payload["memory"], required_stages=list(checks.STAGES),
        checker_state=payload["checker_state"], checker_state_sha256=fingerprint(payload["checker_state"]), check_date=at[:10])
    raw = checks._encoded(packet, MAX_PACKET_BYTES)
    identity = fingerprint(packet)
    prior = c.execute(f"SELECT check_set_id,packet_sha256 FROM {SCHEMA}.sets WHERE job_id=%s AND custom_id=%s", (packet["job_id"], packet["custom_id"])).fetchone()
    if prior:
        _packet(c, prior[0], environment)
        checks._require(prior[0] == identity and _raw(c, "packet_artifacts", prior[1]) == raw, "conflicting_check_candidate")
    else:
        checks._require(c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.sets").fetchone()[0] < checks.MAX_SETS, "check_set_capacity")
        results.review(c, review_input, now=at, environment=environment)
        digest = _artifact(c, "packet_artifacts", raw)
        c.execute(f"INSERT INTO {SCHEMA}.sets VALUES(%s,%s,%s,%s,%s)", (identity, packet["job_id"], packet["custom_id"], digest, at))
    return dict(check_set_id=identity, reused=bool(prior), required_checks_completed=False,
                publication_approved=False, dispatch_granted=False)


def apply(c, action, payload, *, now, environment, request=None, receipt=None):
    fields = {"intake": checks._REVIEW_FIELDS | {"custom_id", "bundle", "memory", "checker_state"},
              "status": checks._BASE, "begin": checks._BASE | {"stage", "reservation"},
              "complete": checks._BASE | {"stage", "grant_id"}}
    checks._require(isinstance(action, str) and action in fields, "unknown_check_action")
    checks._shape(payload, fields[action])
    checks._require((action == "begin" or request is None) and (action == "complete" or receipt is None), "invalid_check_arguments")
    # Detach every caller-owned object before repeated SQL operations reuse it.
    envelope = {key: value for key, value in payload.items() if action != "intake" or key not in {"bundle", "memory", "checker_state"}}
    detached = json.loads(checks._encoded(envelope, 8192))
    if action == "intake":
        detached.update({key: json.loads(checks._encoded(payload[key], checks.MAX_INPUT_BYTES)) for key in ("bundle", "memory", "checker_state")})
    payload = detached
    if action == "begin":
        checks._require(type(request) is bytes and 0 < len(request) <= checks.MAX_INPUT_BYTES, "invalid_check_request")
    if action == "complete":
        receipt = json.loads(checks._encoded(receipt, checks.MAX_RECEIPT_BYTES))
    validate(c, environment)
    at = _at(c, now)
    if action == "intake":
        return _intake(c, payload, at, environment)
    packet, enrolled_at = _packet(c, payload["check_set_id"], environment)
    stages, attempts = _stages(c, payload["check_set_id"], packet, enrolled_at)
    if action == "status":
        reason = None
        try:
            _current(c, packet, payload, at, environment)
        except (checks.CheckJournalError, r.BatchResultError, w.BatchWorkerError):
            reason = "check_context_not_current"
        return dict(check_set_id=payload["check_set_id"], stages=stages, blocked_reason=reason,
                    required_checks_completed=reason is None and all(v == "passed" for v in stages.values()),
                    publication_approved=False, dispatch_granted=False, accounting_complete=False, cost_usd=None)
    if action == "begin":
        _current(c, packet, payload, at, environment)
    stage = payload["stage"]
    checks._require(stage in checks.STAGES, "unknown_required_check")
    prior = attempts[stage]
    if action == "begin":
        request_sha = p._sha(request)
        if prior:
            checks._require(prior["binding"]["request_sha256"] == request_sha
                            and canonical_json(prior["binding"]["reservation"]) == canonical_json(payload["reservation"]), "conflicting_check_attempt")
            return dict(grant_id=prior["grant_id"], dispatch_granted=False, publication_approved=False)
        checks._require(all(stages[k] == "passed" for k in checks.STAGES[:checks.STAGES.index(stage)]), "required_predecessor_not_passed")
        reservation, intent_id = payload["reservation"], None
        if stage == "deterministic":
            checks._require(reservation is None, "local_check_cannot_spend")
        else:
            _reservation(reservation, packet, stage, request_sha)
            intent_id = reservation["intent_id"]
            existing = spend._record(c, intent_id)
            checks._require(existing is None or existing["state"] == "reserved", "check_spend_already_used")
            spend.apply(c, "reserve", reservation, now=at, environment=environment)
            grant = spend.apply(c, "dispatch", {"intent_id": intent_id}, now=at, environment=environment)
            checks._require(grant["dispatch_granted"], "check_spend_not_granted")
        binding = dict(check_set_id=payload["check_set_id"], stage=stage, request_sha256=request_sha,
                       reservation=reservation, owner=payload["owner"], fence=payload["fence"], begun_at=at)
        identity = fingerprint(binding)
        _artifact(c, "request_artifacts", request)
        digest = _artifact(c, "binding_artifacts", checks._encoded(binding, 8192))
        c.execute(f"INSERT INTO {SCHEMA}.attempts VALUES(%s,%s,%s,%s,%s,%s,%s)",
                  (identity, payload["check_set_id"], stage, digest, request_sha, intent_id, at))
        return dict(grant_id=identity, dispatch_granted=True, publication_approved=False)
    checks._require(prior is not None and prior["grant_id"] == payload["grant_id"], "unknown_check_grant")
    binding = prior["binding"]
    checks._require(type(payload["fence"]) is int and payload["owner"] == binding["owner"]
                    and payload["fence"] == binding["fence"], "check_receipt_owner_mismatch")
    disposition = _receipt_doc(receipt, prior)
    raw = checks._encoded(receipt, checks.MAX_RECEIPT_BYTES)
    terminal = _terminal(c, prior)
    if terminal:
        checks._require(terminal["sha256"] == p._sha(raw) and canonical_json(terminal["document"]).encode() == raw, "conflicting_check_completion")
        return dict(reused=True, disposition=terminal["disposition"], publication_approved=False)
    try:
        _current(c, packet, payload, at, environment)
    except (checks.CheckJournalError, r.BatchResultError, w.BatchWorkerError):
        disposition = "stale"
    digest = _artifact(c, "receipt_artifacts", raw)
    c.execute(f"INSERT INTO {SCHEMA}.receipts VALUES(%s,%s,%s,%s)", (prior["grant_id"], digest, disposition, at))
    return dict(reused=False, disposition=disposition, publication_approved=False)
