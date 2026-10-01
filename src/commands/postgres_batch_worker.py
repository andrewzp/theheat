"""Fenced local PostgreSQL batch ownership; no provider I/O or publication.

Every helper uses the caller's validated, locked transaction. Dispatch receipts
are provisional until the authority wrapper acknowledges the outer commit.
"""
from __future__ import annotations

from datetime import timedelta
import json

from src.commands import batch_journal as b, batch_worker_journal as w
from src.commands import postgres_batch as batch, postgres_spending as spend, spend_journal as s
from src.commands.schema import canonical_json, utc_datetime
from src.storage import postgres_projection as p

SCHEMA = "theheat_batch_work"
MIGRATION = p.MIGRATION.with_name("005_batch_worker.sql")
_COLUMNS = {
    "leases": ("job_id", "fence", "owner", "expires_at", "recorded_at"),
    "submissions": ("job_id", "fence", "grant_id", "recorded_at"),
    "uncertainties": ("job_id", "recorded_at"),
    "acks": ("job_id", "receipt_sha256", "provider_id", "recorded_at"),
    "adoptions": ("job_id", "receipt_sha256", "provider_id", "recorded_at"),
}


def validate(c, environment):
    batch.validate(c, environment)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise w.BatchWorkerError("batch_worker_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    w._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_worker_schema")
    w._require(row[2] == p._catalog(c, SCHEMA), "changed_worker_schema")
    w._require(row[3] == environment, "worker_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    w._require(tuple(row[4:]) == roles, "worker_role_mismatch")


def install(c, environment):
    """The explicit owner wrapper holds the same core lock as all mutations."""
    batch.validate(c, environment)
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
    tables = ",".join(f"{SCHEMA}.{table}" for table in (*_COLUMNS, "ack_artifacts"))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {tables} TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _rows(c, table, job):
    columns = _COLUMNS[table]
    order = "recorded_at,receipt_sha256" if table == "acks" else "2"
    return [dict(zip(columns, row, strict=True)) for row in c.execute(
        f"SELECT {','.join(columns)} FROM {SCHEMA}.{table} WHERE job_id=%s ORDER BY {order}", (job,)).fetchall()]


def _one(c, table, job):
    rows = _rows(c, table, job)
    return rows[0] if rows else None


def _leases(c, job):
    count = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.leases WHERE job_id=%s", (job,)).fetchone()[0]
    w._require(count <= w.MAX_LEASES, "batch_lease_capacity")
    rows = _rows(c, "leases", job)
    previous_expiry = None
    for fence, row in enumerate(rows, 1):
        s._id(row["owner"])
        start, end = utc_datetime(row["recorded_at"]), utc_datetime(row["expires_at"])
        w._require(row["fence"] == fence and 1 <= (end - start).total_seconds() <= 300
                   and spend._time(row["recorded_at"]) == row["recorded_at"]
                   and spend._time(row["expires_at"]) == row["expires_at"]
                   and (previous_expiry is None or start >= previous_expiry), "changed_batch_lease")
        previous_expiry = end
    return rows


def _submission(c, registration, leases):
    row = _one(c, "submissions", registration["job_id"])
    if row:
        lease = next((item for item in leases if item["fence"] == row["fence"]), None)
        w._require(lease is not None and row["grant_id"] == w._grant(registration, lease, row["recorded_at"]), "changed_batch_grant")
        assert lease is not None
        w._require(spend._time(row["recorded_at"]) == row["recorded_at"]
                   and utc_datetime(lease["recorded_at"]) <= utc_datetime(row["recorded_at"]) < utc_datetime(lease["expires_at"]),
                   "invalid_batch_grant_time")
        w._require(registration["reservation_state"] in {"dispatched", "uncertain", "settled"}, "changed_submission_reservation")
    return row


def _ack_bytes(c, digest):
    row = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.ack_artifacts WHERE sha=%s", (digest,)).fetchone()
    w._require(row is not None and type(row[0]) is int and 0 <= row[0] == row[1] <= w.MAX_ACK_BYTES, "invalid_ack_artifact_size")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.ack_artifacts WHERE sha=%s", (digest,)).fetchone()[0]
    w._require(type(raw) is bytes and len(raw) == row[0] and p._sha(raw) == digest, "changed_ack_artifact")
    return raw


def _receipts(c, job, samples):
    count = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.acks WHERE job_id=%s", (job,)).fetchone()[0]
    w._require(count <= w.MAX_RECEIPTS, "batch_receipt_capacity")
    rows = _rows(c, "acks", job)
    for row in rows:
        w._require(w._ack_id(_ack_bytes(c, row["receipt_sha256"]), samples) == row["provider_id"], "changed_ack_binding")
    return rows


def _conflict(c, receipts):
    ids = {row["provider_id"] for row in receipts if row["provider_id"] is not None}
    return len(ids) > 1 or any(c.execute(
        f"SELECT COUNT(DISTINCT job_id) FROM {SCHEMA}.acks WHERE provider_id=%s", (identity,)).fetchone()[0] > 1 for identity in ids)


def _uncertain(c, registration, at, environment):
    if _one(c, "uncertainties", registration["job_id"]) is None:
        c.execute(f"INSERT INTO {SCHEMA}.uncertainties VALUES(%s,%s)", (registration["job_id"], at))
    if registration["reservation_state"] == "dispatched":
        spend.apply(c, "uncertain", {"intent_id": registration["intent_id"]}, now=at, environment=environment)


def _view(c, registration, plan, stamp):
    job = registration["job_id"]
    leases = _leases(c, job)
    lease = leases[-1] if leases else None
    submission = _submission(c, registration, leases)
    uncertainty, adoption = _one(c, "uncertainties", job), _one(c, "adoptions", job)
    receipts = _receipts(c, job, plan["samples"])
    w._require(submission is not None or not (uncertainty or adoption or receipts), "missing_batch_submission")
    for event in [*leases, *receipts, *([submission] if submission else []),
                  *([uncertainty] if uncertainty else []), *([adoption] if adoption else [])]:
        w._require(spend._time(event["recorded_at"]) == event["recorded_at"]
                   and registration["registered_at"] <= event["recorded_at"], "invalid_worker_event_time")
    if submission:
        w._require(all(event["recorded_at"] >= submission["recorded_at"] for event in
                       [*receipts, *([uncertainty] if uncertainty else []), *([adoption] if adoption else [])]),
                   "invalid_worker_event_time")
    if adoption:
        w._require(any(r["receipt_sha256"] == adoption["receipt_sha256"]
                       and r["provider_id"] == adoption["provider_id"]
                       and r["provider_id"] is not None
                       and r["recorded_at"] <= adoption["recorded_at"] for r in receipts), "changed_adoption_binding")
    conflict = _conflict(c, receipts)
    if submission is None:
        state = "reserved" if registration["reservation_state"] == "reserved" else "reservation_" + registration["reservation_state"]
    elif conflict:
        state = "acknowledgment_conflict"
    elif adoption:
        state = "submitted"
    elif uncertainty or lease is None or lease["fence"] != submission["fence"] or stamp >= utc_datetime(lease["expires_at"]):
        state = "submission_uncertain"
    else:
        state = "submitting"
    return dict(registration, state=state, lease=lease,
                lease_active=bool(lease and stamp < utc_datetime(lease["expires_at"])),
                grant_id=submission["grant_id"] if submission else None,
                provider_batch_id=adoption["provider_id"] if adoption and not conflict else None,
                receipt_count=len(receipts), invalid_receipt_count=sum(r["provider_id"] is None for r in receipts),
                useful=stamp < utc_datetime(plan["useful_until"]), accounting_complete=False, collection_granted=False)


def apply(c, action, payload, *, now, raw=None, environment):
    validate(c, environment)
    fields = {
        "status": {"job_id"}, "acquire": {"job_id", "owner", "ttl_seconds"},
        "begin": {"job_id", "owner", "fence", "current_context"},
        "uncertain": {"job_id", "owner", "fence"},
        "observe_ack": {"job_id", "grant_id", "receipt_sha256"},
        "adopt": {"job_id", "owner", "fence", "receipt_sha256"},
    }
    w._require(type(action) is str and action in fields, "unknown_worker_action")
    w._shape(payload, fields[action])
    encoded = canonical_json(payload).encode()
    w._require(len(encoded) <= 4096, "oversized_worker_payload")
    # Freeze nested mutable context before transaction-local reuse.
    payload = json.loads(encoded)
    w._require(raw is None or action == "observe_ack", "unexpected_worker_bytes")
    at = spend._time(now)
    stamp = utc_datetime(at)
    latest = c.execute("SELECT MAX(recorded_at) FROM (" + " UNION ALL ".join(
        f"SELECT MAX(recorded_at) AS recorded_at FROM {SCHEMA}.{table}" for table in _COLUMNS) + ") clocks").fetchone()[0]
    w._require(latest is None or at >= latest, "worker_clock_went_backwards")
    job = payload["job_id"]
    registration = batch.read(c, job, environment=environment)
    w._require(at >= registration["registered_at"], "worker_clock_before_registration")
    plan = b._plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    before = _view(c, registration, plan, stamp)
    lease, submitted = before["lease"], before["grant_id"] is not None
    granted = reused = False
    if action == "acquire":
        s._id(payload["owner"])
        ttl = payload["ttl_seconds"]
        w._require(type(ttl) is int and 1 <= ttl <= 300, "invalid_lease_ttl")
        if lease and stamp < utc_datetime(lease["expires_at"]):
            w._require(lease["owner"] == payload["owner"], "batch_lease_busy")
            reused = True
        else:
            fence = lease["fence"] + 1 if lease else 1
            w._require(fence <= w.MAX_LEASES, "batch_lease_capacity")
            if submitted and _one(c, "adoptions", job) is None:
                _uncertain(c, registration, at, environment)
            expires = (stamp + timedelta(seconds=ttl)).isoformat(timespec="microseconds").replace("+00:00", "Z")
            c.execute(f"INSERT INTO {SCHEMA}.leases VALUES(%s,%s,%s,%s,%s)", (job, fence, payload["owner"], expires, at))
    elif action == "begin":
        w._owner(lease, payload, stamp)
        context = payload["current_context"]
        w._shape(context, w._CONTEXT)
        w._require(all(context[key] == plan[key] for key in w._CONTEXT), "changed_batch_context")
        w._require((utc_datetime(plan["useful_until"]) - stamp).total_seconds() > plan["minimum_window_seconds"], "batch_submission_outside_window")
        if submitted:
            reused = True
        else:
            w._require(registration["reservation_state"] == "reserved", "batch_reservation_not_available")
            grant = w._grant(registration, lease, at)
            dispatch = spend.apply(c, "dispatch", {"intent_id": registration["intent_id"]}, now=at, environment=environment)
            w._require(dispatch["dispatch_granted"], "batch_reservation_not_available")
            c.execute(f"INSERT INTO {SCHEMA}.submissions VALUES(%s,%s,%s,%s)", (job, payload["fence"], grant, at))
            granted = True
    elif action == "uncertain":
        w._owner(lease, payload, stamp)
        w._require(submitted, "batch_not_submitted")
        w._require(_one(c, "adoptions", job) is None, "batch_already_adopted")
        _uncertain(c, registration, at, environment)
    elif action == "observe_ack":
        s._sha(payload["grant_id"])
        s._sha(payload["receipt_sha256"])
        w._require(submitted and before["grant_id"] == payload["grant_id"], "unknown_batch_grant")
        w._require(type(raw) is bytes and len(raw) <= w.MAX_ACK_BYTES, "invalid_or_oversized_ack")
        w._require(p._sha(raw) == payload["receipt_sha256"], "changed_ack_bytes")
        prior = c.execute(f"SELECT 1 FROM {SCHEMA}.acks WHERE job_id=%s AND receipt_sha256=%s", (job, payload["receipt_sha256"])).fetchone()
        if prior:
            reused = True
        else:
            w._require(before["receipt_count"] < w.MAX_RECEIPTS, "batch_receipt_capacity")
            # Store and verify exact bytes before attempting protocol parsing.
            c.execute(f"INSERT INTO {SCHEMA}.ack_artifacts VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (payload["receipt_sha256"], raw, len(raw)))
            w._require(_ack_bytes(c, payload["receipt_sha256"]) == raw, "changed_ack_artifact")
            identity = w._ack_id(raw, plan["samples"])
            c.execute(f"INSERT INTO {SCHEMA}.acks VALUES(%s,%s,%s,%s)", (job, payload["receipt_sha256"], identity, at))
    elif action == "adopt":
        w._owner(lease, payload, stamp)
        s._sha(payload["receipt_sha256"])
        receipts = _receipts(c, job, plan["samples"])
        w._require(not _conflict(c, receipts), "conflicting_batch_acknowledgments")
        receipt = next((r for r in receipts if r["receipt_sha256"] == payload["receipt_sha256"]), None)
        w._require(receipt is not None and receipt["provider_id"] is not None, "invalid_or_missing_batch_ack")
        assert receipt is not None
        prior = _one(c, "adoptions", job)
        if prior:
            w._require(prior["provider_id"] == receipt["provider_id"], "batch_provider_identity_changed")
            reused = True
        else:
            c.execute(f"INSERT INTO {SCHEMA}.adoptions VALUES(%s,%s,%s,%s)", (job, receipt["receipt_sha256"], receipt["provider_id"], at))
    return dict(_view(c, batch.read(c, job, environment=environment), plan, stamp), reused=reused, dispatch_granted=granted)
