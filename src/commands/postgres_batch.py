"""Exact batch registration in the caller's locked local PostgreSQL transaction.

No lease, provider client, dispatch grant, candidate or publication approval.
"""
from __future__ import annotations

from src.commands import batch_journal as b, postgres_spending as spend, spend_journal as s
from src.commands.schema import utc_datetime
from src.storage import postgres_projection as p

SCHEMA = "theheat_batches"
MIGRATION = p.MIGRATION.with_name("004_batch_registration.sql")
MAX_PLAN_BYTES = 2_000_000


def validate(c, environment):
    spend.validate(c, environment)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise b.BatchJournalError("batch_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    b._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_batch_schema")
    b._require(row[2] == p._catalog(c, SCHEMA), "changed_batch_schema")
    b._require(row[3] == environment, "batch_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    b._require(tuple(row[4:]) == roles, "batch_role_mismatch")


def install(c, environment):
    """Explicit owner wrapper validates core and holds its singleton row lock."""
    spend.validate(c, environment)
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
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {SCHEMA}.plans,{SCHEMA}.registrations TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _plan_bytes(c, digest):
    row = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.plans WHERE sha=%s", (digest,)).fetchone()
    b._require(row is not None and type(row[0]) is int and 2 <= row[0] == row[1] <= MAX_PLAN_BYTES,
               "missing_or_invalid_batch_plan")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.plans WHERE sha=%s", (digest,)).fetchone()[0]
    b._require(type(raw) is bytes and len(raw) == row[0] and p._sha(raw) == digest,
               "changed_batch_plan_identity")
    return raw


def _window(plan, stamp):
    return (stamp >= utc_datetime(plan["created_at"])
            and (utc_datetime(plan["useful_until"]) - stamp).total_seconds() > plan["minimum_window_seconds"])


def read(c, job_id, *, environment):
    validate(c, environment)
    s._id(job_id)
    row = c.execute(f"SELECT plan_sha,intent_id,registered_at FROM {SCHEMA}.registrations WHERE job_id=%s", (job_id,)).fetchone()
    b._require(row is not None, "batch_job_not_found")
    raw = _plan_bytes(c, row[0])
    plan = b._plan(raw, row[0])
    hold = spend._record(c, row[1])
    b._require(hold is not None and plan["job_id"] == job_id, "changed_batch_binding")
    b._join(plan, row[0], hold["intent"])
    b._require(spend._time(row[2]) == row[2] and _window(plan, utc_datetime(row[2])),
               "invalid_batch_registration_time")
    return dict(job_id=job_id, plan_sha256=row[0], intent_id=row[1], registered_at=row[2],
                useful_until=plan["useful_until"], reservation_state=hold["state"],
                dispatch_granted=False, publication_approved=False)


def register(c, plan_bytes, *, expected_plan_sha256, reservation, now, environment):
    """One provisional receipt; the outer owner must commit before returning it."""
    validate(c, environment)
    stamp = utc_datetime(now)
    at = spend._time(now)
    plan = b._plan(plan_bytes, expected_plan_sha256)
    # Detach the caller's mutable dict before multiple SQL operations reuse it.
    body = spend._body(reservation)
    reservation = spend._decode(body, p._sha(body))
    b._join(plan, expected_plan_sha256, reservation)
    row = c.execute(f"SELECT plan_sha,intent_id FROM {SCHEMA}.registrations WHERE job_id=%s", (plan["job_id"],)).fetchone()
    if row:
        b._require(row == (expected_plan_sha256, reservation["intent_id"]), "batch_job_id_reused")
        saved = spend._record(c, row[1])
        b._require(saved is not None and saved["intent"] == reservation, "batch_reservation_changed")
        # Historical readback may follow expiry. No new hold or dispatch is made.
        return dict(read(c, plan["job_id"], environment=environment), reused=True)
    b._require(_window(plan, stamp), "batch_registration_outside_window")
    b._require(c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.registrations").fetchone()[0] < b.MAX_JOBS,
               "batch_capacity_exceeded")
    b._require(c.execute(f"SELECT 1 FROM {SCHEMA}.registrations WHERE plan_sha=%s OR intent_id=%s",
                        (expected_plan_sha256, reservation["intent_id"])).fetchone() is None, "batch_identity_reused")
    hold = spend.apply(c, "reserve", reservation, now=at, environment=environment)
    b._require(hold["intent"]["state"] == "reserved", "batch_attempt_already_used")
    c.execute(f"INSERT INTO {SCHEMA}.plans VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING",
              (expected_plan_sha256, plan_bytes, len(plan_bytes)))
    b._require(_plan_bytes(c, expected_plan_sha256) == plan_bytes, "changed_batch_plan_identity")
    c.execute(f"INSERT INTO {SCHEMA}.registrations VALUES(%s,%s,%s,%s)",
              (plan["job_id"], expected_plan_sha256, reservation["intent_id"], at))
    return dict(read(c, plan["job_id"], environment=environment), reused=False)
