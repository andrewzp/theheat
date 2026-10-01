"""Exact local PostgreSQL batch results and fresh fenced review; no transport.

The caller owns the validated core lock and transaction. Parsed results never
complete required checks, create drafts, release spending holds or approve posts.
"""
from __future__ import annotations

import json

from src.commands import batch_journal as b, batch_result_journal as r, batch_worker_journal as w
from src.commands import postgres_batch as batch, postgres_batch_worker as worker, postgres_spending as spend
from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p

SCHEMA = "theheat_batch_results"
MIGRATION = p.MIGRATION.with_name("006_batch_results.sql")
MAX_REPORT_BYTES = 4_000_000
_ARTIFACTS = {"metadata_artifacts": w.MAX_ACK_BYTES,
              "result_artifacts": r.MAX_RESULT_BYTES, "report_artifacts": MAX_REPORT_BYTES}


def validate(c, environment):
    worker.validate(c, environment)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise r.BatchResultError("batch_result_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    r._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_result_schema")
    r._require(row[2] == p._catalog(c, SCHEMA), "changed_result_schema")
    r._require(row[3] == environment, "result_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    r._require(tuple(row[4:]) == roles, "result_role_mismatch")


def install(c, environment):
    worker.validate(c, environment)
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
    tables = ",".join(f"{SCHEMA}.{t}" for t in (*_ARTIFACTS, "receipts", "choices", "reviews"))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {tables} TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _body(payload):
    encoded = canonical_json(payload).encode()
    r._require(len(encoded) <= 4096, "oversized_result_payload")
    return encoded


def _at(c, now):
    at = spend._time(now)
    latest = c.execute(f"SELECT MAX(recorded_at) FROM (SELECT MAX(recorded_at) AS recorded_at FROM {SCHEMA}.receipts UNION ALL SELECT MAX(recorded_at) AS recorded_at FROM {SCHEMA}.reviews) clocks").fetchone()[0]
    r._require(latest is None or at >= latest, "result_clock_went_backwards")
    return at


def _raw(c, table, digest):
    limit = _ARTIFACTS[table]
    size = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()
    r._require(size is not None and type(size[0]) is int and 0 <= size[0] == size[1] <= limit, "invalid_result_artifact_size")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.{table} WHERE sha=%s", (digest,)).fetchone()[0]
    r._require(type(raw) is bytes and len(raw) == size[0] and p._sha(raw) == digest, "changed_result_artifact")
    return raw


def _artifact(c, table, raw):
    r._require(type(raw) is bytes and len(raw) <= _ARTIFACTS[table], "invalid_or_oversized_result_bytes")
    sha = p._sha(raw)
    c.execute(f"INSERT INTO {SCHEMA}.{table} VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (sha, raw, len(raw)))
    r._require(_raw(c, table, sha) == raw, "changed_result_artifact")
    return sha


def _receipts(c, job, grant):
    count = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.receipts WHERE job_id=%s", (job,)).fetchone()[0]
    r._require(count <= r.MAX_RECEIPTS, "result_receipt_capacity")
    # Binding is independently small even when its raw result artifact is large.
    sizes = c.execute(f"SELECT octet_length(binding) FROM {SCHEMA}.receipts WHERE job_id=%s", (job,)).fetchall()
    r._require(all(2 <= row[0] <= 4096 for row in sizes), "invalid_result_binding_size")
    rows = c.execute(f"SELECT receipt_id,job_id,grant_id,metadata_sha256,results_sha256,binding,binding_sha256,recorded_at FROM {SCHEMA}.receipts WHERE job_id=%s ORDER BY receipt_id", (job,)).fetchall()
    result = []
    submitted = c.execute("SELECT recorded_at FROM theheat_batch_work.submissions WHERE job_id=%s", (job,)).fetchone()
    for identity, job_id, grant_id, meta, raw_sha, encoded, binding_sha, at in rows:
        binding = p._decode(encoded)
        r._binding(binding)
        r._require(_body(binding) == encoded and p._sha(encoded) == binding_sha and fingerprint(binding) == identity
                   and binding == dict(job_id=job_id, grant_id=grant_id, metadata_sha256=meta,
                                       results_sha256=raw_sha, complete=binding["complete"])
                   and job_id == job and grant_id == grant, "changed_result_binding")
        r._require(submitted is not None and spend._time(at) == at and at >= submitted[0], "invalid_result_receipt_time")
        result.append(dict(receipt_id=identity, job_id=job, binding=binding, recorded_at=at,
                           metadata_sha256=meta, results_sha256=raw_sha,
                           metadata=_raw(c, "metadata_artifacts", meta), results=_raw(c, "result_artifacts", raw_sha)))
    return result


def _choice(c, job, receipts):
    row = c.execute(f"SELECT receipt_id,semantic_sha256 FROM {SCHEMA}.choices WHERE job_id=%s", (job,)).fetchone()
    if row:
        r._require(any(item["receipt_id"] == row[0] for item in receipts), "changed_result_choice")
        w.spend_journal._sha(row[1])
        return dict(receipt_id=row[0], semantic_sha256=row[1])
    return None


def record(c, payload, metadata, results, *, now, environment):
    validate(c, environment)
    at = _at(c, now)
    payload = json.loads(_body(payload))
    r._binding(payload)
    for raw, key, bound in ((metadata, "metadata_sha256", w.MAX_ACK_BYTES), (results, "results_sha256", r.MAX_RESULT_BYTES)):
        r._require(type(raw) is bytes and len(raw) <= bound, "invalid_or_oversized_result_bytes")
        r._require(p._sha(raw) == payload[key], "changed_result_bytes")
    status = worker.apply(c, "status", {"job_id": payload["job_id"]}, now=at, environment=environment)
    r._require(status["grant_id"] == payload["grant_id"], "unknown_result_grant")
    retained = _receipts(c, payload["job_id"], payload["grant_id"])
    identity = fingerprint(payload)
    prior = any(item["receipt_id"] == identity for item in retained)
    if not prior:
        r._require(len(retained) < r.MAX_RECEIPTS, "result_receipt_capacity")
        # Raw retention precedes any interpretation of these provider results.
        _artifact(c, "metadata_artifacts", metadata)
        _artifact(c, "result_artifacts", results)
        encoded = _body(payload)
        c.execute(f"INSERT INTO {SCHEMA}.receipts VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                  (identity, payload["job_id"], payload["grant_id"], payload["metadata_sha256"],
                   payload["results_sha256"], encoded, p._sha(encoded), at))
    _receipts(c, payload["job_id"], payload["grant_id"])
    return dict(job_id=payload["job_id"], receipt_id=identity, reused=prior, raw_retained=True,
                publication_approved=False, dispatch_granted=False)


def index(c, payload, *, now, environment):
    validate(c, environment)
    payload = json.loads(_body(payload))
    r._require(isinstance(payload, dict) and set(payload) == {"job_id"}, "invalid_result_index")
    at = _at(c, now)
    status = worker.apply(c, "status", payload, now=at, environment=environment)
    receipts = _receipts(c, payload["job_id"], status["grant_id"])
    choice = _choice(c, payload["job_id"], receipts)
    return dict(submission=status, chosen_receipt_id=choice["receipt_id"] if choice else None,
                receipts=[dict(receipt_id=item["receipt_id"], complete=item["binding"]["complete"],
                               recorded_at=item["recorded_at"]) for item in receipts],
                capacity_remaining=r.MAX_RECEIPTS - len(receipts), publication_approved=False)


def evaluate(c, payload, *, now, environment):
    """Fresh current-owner interpretation, without choosing a receipt or writing."""
    from src.two_bot import batch_contract as contract

    validate(c, environment)
    payload = json.loads(_body(payload))
    r._require(isinstance(payload, dict) and set(payload) == {"job_id", "owner", "fence", "receipt_id", "current_context"}, "invalid_result_review_fields")
    context = payload["current_context"]
    r._require(isinstance(context, dict) and set(context) == contract._CONTEXT, "invalid_review_context")
    for field in contract._CONTEXT - {"publication_epoch"}:
        contract._sha(context[field])
    contract._id(context["publication_epoch"])
    at = _at(c, now)
    job = payload["job_id"]
    status = worker.apply(c, "status", {"job_id": job}, now=at, environment=environment)
    w._owner(status["lease"], payload, utc_datetime(at))
    w.spend_journal._sha(payload["receipt_id"])
    receipts = _receipts(c, job, status["grant_id"])
    r._require(any(item["receipt_id"] == payload["receipt_id"] for item in receipts), "batch_result_receipt_not_found")
    plan_raw = batch._plan_bytes(c, status["plan_sha256"])
    plan = b._plan(plan_raw, status["plan_sha256"])
    decoded = {item["receipt_id"]: r._decode(plan_raw, plan, item, context, at, status["provider_batch_id"]) for item in receipts}
    report, semantic, items = decoded[payload["receipt_id"]]
    choices = {value[1] for value in decoded.values() if value[1] is not None}
    choice = _choice(c, job, receipts)
    if choice:
        if status["provider_batch_id"] is not None:
            chosen = decoded.get(choice["receipt_id"])
            r._require(chosen is not None and chosen[1] == choice["semantic_sha256"], "changed_result_choice")
        choices.add(choice["semantic_sha256"])
    if len(choices) > 1:
        r._withhold(report, ["conflicting_complete_results"])
    if status["state"] != "submitted":
        r._withhold(report, ["submission_not_confirmed"])
    for row in report["rows"]:
        row["candidate_id"] = (fingerprint(dict(plan_sha256=status["plan_sha256"],
            custom_id=row["custom_id"], item=items[row["custom_id"]])) if row["eligible_for_checks"] else None)
    binding = dict(job_id=job, receipt_id=payload["receipt_id"], plan_sha256=status["plan_sha256"],
                   receipt_set_sha256=fingerprint([item["receipt_id"] for item in receipts]),
                   submission_revision_sha256=fingerprint(dict(grant_id=status["grant_id"], state=status["state"],
                       provider_batch_id=status["provider_batch_id"], acknowledgments=worker._receipts(c, job, plan["samples"]))),
                   current_context=context, reviewed_at=at, owner=payload["owner"], fence=payload["fence"])
    return dict(binding=binding, report=report, review_id=fingerprint(binding), semantic_sha256=semantic)


def _review(c, review_id):
    row = c.execute(f"SELECT job_id,receipt_id,fence,report_sha256,recorded_at FROM {SCHEMA}.reviews WHERE review_id=%s", (review_id,)).fetchone()
    if row is None:
        return None
    job, receipt, fence, sha, at = row
    raw = _raw(c, "report_artifacts", sha)
    doc = p._decode(raw)
    r._require(isinstance(doc, dict) and set(doc) == {"binding", "report", "review_id", "semantic_sha256"}
               and canonical_json(doc).encode() == raw, "changed_result_review")
    binding = doc["binding"]
    r._require(isinstance(binding, dict) and set(binding) == {"job_id", "receipt_id", "plan_sha256", "receipt_set_sha256",
               "submission_revision_sha256", "current_context", "reviewed_at", "owner", "fence"}, "changed_result_review")
    r._require(fingerprint(binding) == doc["review_id"] == review_id
               and (binding["job_id"], binding["receipt_id"], binding["fence"], binding["reviewed_at"]) == (job, receipt, fence, at), "changed_result_review")
    lease = c.execute("SELECT owner,recorded_at,expires_at FROM theheat_batch_work.leases WHERE job_id=%s AND fence=%s", (job, fence)).fetchone()
    intake = c.execute(f"SELECT recorded_at FROM {SCHEMA}.receipts WHERE job_id=%s AND receipt_id=%s", (job, receipt)).fetchone()
    r._require(lease is not None and lease[0] == binding["owner"] and lease[1] <= at < lease[2]
               and spend._time(at) == at and intake is not None and intake[0] <= at, "changed_result_review")
    return sha, raw


def review(c, payload, *, now, environment):
    document = evaluate(c, payload, now=now, environment=environment)
    binding = document["binding"]
    job, at, identity = binding["job_id"], binding["reviewed_at"], document["review_id"]
    count = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.reviews WHERE job_id=%s", (job,)).fetchone()[0]
    r._require(count <= r.MAX_REVIEWS, "result_review_capacity")
    semantic = document["semantic_sha256"]
    if semantic and "conflicting_complete_results" not in document["report"]["context_blocked_reasons"] and not c.execute(f"SELECT 1 FROM {SCHEMA}.choices WHERE job_id=%s", (job,)).fetchone():
        c.execute(f"INSERT INTO {SCHEMA}.choices VALUES(%s,%s,%s)", (job, binding["receipt_id"], semantic))
    encoded = canonical_json(document).encode()
    r._require(len(encoded) <= MAX_REPORT_BYTES, "oversized_result_review")
    sha = p._sha(encoded)
    prior = _review(c, identity)
    if prior:
        r._require(prior == (sha, encoded), "changed_result_review")
    else:
        r._require(count < r.MAX_REVIEWS, "result_review_capacity")
        _artifact(c, "report_artifacts", encoded)
        c.execute(f"INSERT INTO {SCHEMA}.reviews VALUES(%s,%s,%s,%s,%s,%s)", (identity, job, binding["receipt_id"], binding["fence"], sha, at))
    return dict(document, report_sha256=sha, reused=bool(prior), publication_approved=False)
