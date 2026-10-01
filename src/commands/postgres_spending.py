"""Connection-composable, local PostgreSQL spending holds; no provider client.

Private callers own the validated core transaction AND its singleton row lock.
No result is a dispatch grant until that outer transaction acknowledges commit.
"""
from __future__ import annotations

from src.commands import spend_journal as s
from src.commands.schema import canonical_json, utc_datetime
from src.storage import postgres_projection as p

SCHEMA = "theheat_spending"
MIGRATION = p.MIGRATION.with_name("003_spending.sql")
MAX_PAYLOAD = 4096
_TRANSITIONS = {"reserved": ("dispatched", "released"), "dispatched": ("uncertain", "settled"),
                "uncertain": ("settled",), "released": (), "settled": ()}


def _time(value):
    return utc_datetime(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _body(value):
    raw = canonical_json(value).encode()
    s._require(len(raw) <= MAX_PAYLOAD, "oversized_spend_payload")
    return raw


def _decode(raw, digest):
    s._require(type(raw) is bytes and len(raw) <= MAX_PAYLOAD and p._sha(raw) == digest,
               "corrupt_spend_record")
    value = p._decode(raw)
    s._require(type(value) is dict and _body(value) == raw, "corrupt_spend_record")
    return value


def _transaction(c):
    s._require(c.info.transaction_status == p._driver().pq.TransactionStatus.INTRANS,
               "spending_requires_transaction")


def validate(c, environment):
    _transaction(c)
    if not c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        raise s.SpendError("spend_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    s._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_spend_schema")
    s._require(row[2] == p._catalog(c, SCHEMA), "changed_spend_schema")
    s._require(row[3] == environment, "spend_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    s._require(tuple(row[4:]) == roles, "spend_role_mismatch")


def install(c, environment):
    """Owner wrapper validates core and locks singleton before this operation."""
    _transaction(c)
    if c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        validate(c, environment)
        return
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    driver = p._driver()
    c.execute(MIGRATION.read_text())
    role = driver.sql.Identifier(roles[1])
    for target in (f"SCHEMA {SCHEMA}", f"ALL TABLES IN SCHEMA {SCHEMA}",
                   f"ALL SEQUENCES IN SCHEMA {SCHEMA}", f"ALL FUNCTIONS IN SCHEMA {SCHEMA}"):
        c.execute(f"REVOKE ALL ON {target} FROM PUBLIC")
        c.execute(driver.sql.SQL(f"REVOKE ALL ON {target} FROM {{}}").format(role))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT INSERT ON {SCHEMA}.limits,{SCHEMA}.intents,{SCHEMA}.events TO {{}}",
                      f"GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {{}}"):
        c.execute(driver.sql.SQL(statement).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _limits(value):
    s._shape(value, s._LIMITS)
    s._sha(value["authorization_sha256"])
    for key in s._LIMITS - {"authorization_sha256"}:
        s._amount(value[key])


def _record(c, identity):
    row = c.execute(f"SELECT payload,digest,recorded_at,job_id,reserve_micro_usd FROM {SCHEMA}.intents WHERE intent_id=%s", (identity,)).fetchone()
    if row is None:
        return None
    intent = _decode(row[0], row[1])
    s._intent(intent)
    s._require(intent["intent_id"] == identity and intent["job_id"] == row[3]
               and intent["reserve_micro_usd"] == row[4] and _time(row[2]) == row[2], "corrupt_spend_intent")
    record = dict(intent=intent, state="reserved", reserved_at=row[2], last_at=row[2],
                  settled_micro_usd=None, evidence_sha256=None)
    events = c.execute(f"SELECT kind,recorded_at,amount_micro_usd,evidence_sha256,payload,digest FROM {SCHEMA}.events WHERE intent_id=%s ORDER BY sequence LIMIT 4", (identity,)).fetchall()
    s._require(len(events) <= 3, "corrupt_spend_history")
    for kind, at, amount, evidence, raw, digest in events:
        event = _decode(raw, digest)
        s._require(_body(event) == _body(dict(intent_id=identity, kind=kind, recorded_at=at,
                                            amount_micro_usd=amount, evidence_sha256=evidence))
                   and kind in _TRANSITIONS[record["state"]] and _time(at) == at
                   and at >= record["last_at"], "corrupt_spend_history")
        if kind == "settled":
            s._amount(amount)
            s._sha(evidence)
        else:
            s._require(amount is None and evidence is None, "corrupt_spend_history")
        record.update(state=kind, last_at=at, settled_micro_usd=amount, evidence_sha256=evidence)
    return record


def _totals(c, now, job_id=None):
    # All money stays in exact SQL integers/numerics. Only these five aggregates
    # cross into Python; full intent JSON is never fetched for a totals query.
    row = c.execute(f"""WITH latest AS (
        SELECT i.job_id,i.reserve_micro_usd,i.recorded_at AS reserved_at,
          e.kind,e.recorded_at AS last_at,
          CASE WHEN e.kind='settled' THEN e.amount_micro_usd ELSE i.reserve_micro_usd END AS amount
        FROM {SCHEMA}.intents i LEFT JOIN LATERAL (
          SELECT kind,recorded_at,amount_micro_usd FROM {SCHEMA}.events
          WHERE intent_id=i.intent_id ORDER BY sequence DESC LIMIT 1) e ON true
        WHERE e.kind IS DISTINCT FROM 'released')
      SELECT COALESCE(SUM(amount) FILTER(WHERE kind IS DISTINCT FROM 'settled'
          OR left(reserved_at,10)=%s OR left(last_at,10)=%s),0),
        COALESCE(SUM(amount) FILTER(WHERE kind IS DISTINCT FROM 'settled'
          OR left(reserved_at,7)=%s OR left(last_at,7)=%s),0),
        COALESCE(SUM(amount) FILTER(WHERE job_id=%s),0),
        COALESCE(SUM(amount) FILTER(WHERE kind IS DISTINCT FROM 'settled'),0),
        COUNT(*) FILTER(WHERE kind='settled' AND amount>reserve_micro_usd)
      FROM latest""", (now[:10], now[:10], now[:7], now[:7], job_id)).fetchone()
    values = [int(value) for value in row]
    s._require(all(0 <= value <= s.MAX_AMOUNT * s.MAX_INTENTS for value in values), "invalid_spend_totals")
    return dict(zip(("daily_micro_usd", "monthly_micro_usd", "job_micro_usd", "held_micro_usd", "overrun_count"), values, strict=True))


def _event(c, identity, kind, now, amount=None, evidence=None):
    raw = _body(dict(intent_id=identity, kind=kind, recorded_at=now,
                     amount_micro_usd=amount, evidence_sha256=evidence))
    c.execute(f"INSERT INTO {SCHEMA}.events(intent_id,kind,recorded_at,amount_micro_usd,evidence_sha256,payload,digest) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (identity, kind, now, amount, evidence, raw, p._sha(raw)))


def apply(c, action, payload, *, now, environment):
    """Caller owns validated core connection/lock/transaction and commit."""
    validate(c, environment)
    now = _time(now)
    raw = _body(payload)
    latest = c.execute(f"""SELECT MAX(recorded_at) FROM (
        SELECT MAX(recorded_at) AS recorded_at FROM {SCHEMA}.limits UNION ALL
        SELECT MAX(recorded_at) FROM {SCHEMA}.intents UNION ALL
        SELECT MAX(recorded_at) FROM {SCHEMA}.events) t""").fetchone()[0]
    s._require(latest is None or now >= latest, "spending_clock_went_backwards")
    existing = c.execute(f"SELECT payload,digest FROM {SCHEMA}.limits WHERE singleton=1").fetchone()
    limits = _decode(*existing) if existing else None
    if limits is not None:
        _limits(limits)
    if action == "configure":
        _limits(payload)
        if existing:
            s._require(existing[0] == raw, "spend_limits_immutable")
        else:
            c.execute(f"INSERT INTO {SCHEMA}.limits VALUES(1,%s,%s,%s)", (raw, p._sha(raw), now))
        return {"configured": True, "limits": payload, "authorization_verified": False}
    s._require(limits is not None, "spend_limits_not_configured")
    assert limits is not None
    count = c.execute(f"SELECT COUNT(*) FROM {SCHEMA}.intents").fetchone()[0]
    s._require(count <= s.MAX_INTENTS, "spend_capacity_exceeded")
    if action == "status":
        s._require(isinstance(payload, dict) and set(payload) <= {"intent_id"}, "invalid_spend_fields")
        identity = payload.get("intent_id")
        record = None
        if identity is not None:
            s._id(identity)
            record = _record(c, identity)
            s._require(record is not None, "spend_intent_not_found")
        return {"limits": limits, "totals": _totals(c, now, record["intent"]["job_id"] if record else None),
                "intent": record, "intent_count": count, "accounting_complete": False, "production_enforcement": False}
    if action == "reserve":
        s._intent(payload)
        identity = payload["intent_id"]
        prior = _record(c, identity)
        if prior is not None:
            s._require(prior["intent"] == payload, "spend_intent_id_reused")
            return {"intent": prior, "reused": True, "dispatch_granted": False}
        s._require(count < s.MAX_INTENTS, "spend_capacity_exceeded")
        totals = _totals(c, now, payload["job_id"])
        s._require(totals["overrun_count"] == 0, "spending_overrun_requires_resolution")
        for total, limit in (("daily_micro_usd", "daily_micro_usd"), ("monthly_micro_usd", "monthly_micro_usd"),
                             ("job_micro_usd", "per_job_micro_usd")):
            s._require(totals[total] + payload["reserve_micro_usd"] <= limits[limit], "spending_allowance_exhausted")
        c.execute(f"INSERT INTO {SCHEMA}.intents VALUES(%s,%s,%s,%s,%s,%s)",
                  (identity, payload["job_id"], payload["reserve_micro_usd"], raw, p._sha(raw), now))
        return {"intent": _record(c, identity), "reused": False, "dispatch_granted": False}
    s._require(action in ("dispatch", "uncertain", "release", "settle"), "unknown_spending_action")
    s._shape(payload, {"intent_id", "amount_micro_usd", "evidence_sha256"} if action == "settle" else {"intent_id"})
    identity = payload["intent_id"]
    s._id(identity)
    record = _record(c, identity)
    s._require(record is not None, "spend_intent_not_found")
    state = record["state"]
    granted = False
    if action == "dispatch":
        if state == "reserved":
            s._require(_totals(c, now)["overrun_count"] == 0, "spending_overrun_requires_resolution")
            _event(c, identity, "dispatched", now)
            granted = True
    elif action == "uncertain":
        s._require(state in ("dispatched", "uncertain"), "spend_not_dispatched")
        if state == "dispatched":
            _event(c, identity, "uncertain", now)
    elif action == "release":
        s._require(state in ("reserved", "released"), "cannot_release_dispatched_spend")
        if state == "reserved":
            _event(c, identity, "released", now)
    else:
        s._amount(payload["amount_micro_usd"])
        s._sha(payload["evidence_sha256"])
        s._require(state in ("dispatched", "uncertain", "settled"), "spend_not_dispatched")
        if state == "settled":
            s._require(record["settled_micro_usd"] == payload["amount_micro_usd"]
                       and record["evidence_sha256"] == payload["evidence_sha256"], "conflicting_spend_settlement")
        else:
            _event(c, identity, "settled", now, payload["amount_micro_usd"], payload["evidence_sha256"])
    return {"intent": _record(c, identity), "dispatch_granted": granted,
            "totals": _totals(c, now, record["intent"]["job_id"])}
