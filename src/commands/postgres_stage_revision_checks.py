"""Owner-installed protocol2 saved-revision authority; immutable original caps.

Only a connection-bound scoped runner can mutate this protocol. Historical prefix
verification never grants execution, changes a deadline or trusts a caller proof.
"""
from __future__ import annotations

from datetime import timedelta
import json

from src.commands import check_journal as checks, postgres_checks as pg
from src.commands import postgres_revision_checks as revisions, postgres_spending as spend
from src.commands.schema import canonical_json, utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from src.two_bot import check_origin, check_requests

MIGRATION = p.MIGRATION.with_name("015_stage_revision_checks.sql")
TABLES = ("stage_proof_artifacts", "stage_leases", "stage_seals")
LEASE_FIELDS = ("check_set_id", "authority_protocol", "stage", "fence", "owner", "recorded_at", "expires_at",
                "predecessor_prefix_sha256", "capability_id")
SEAL_FIELDS = ("check_set_id", "stage", "grant_id", "capability_id", "request_sha256", "raw_sha256",
               "receipt_sha256", "completed_at", "prefix_sha256")
_TOKEN = object()


def installed(c):
    return revisions.upgraded(c) and c.execute("SELECT 1 FROM theheat_checks.schema_upgrades WHERE upgrade_version=4").fetchone() is not None


def protocol(c, identity):
    if not installed(c):
        return 1
    row = c.execute("SELECT authority_protocol,origin_kind FROM theheat_checks.sets WHERE check_set_id=%s", (identity,)).fetchone()
    checks._require(row is not None and type(row[0]) is int and row[0] in (1, 2)
                    and (row[0] == 1 or row[1] == check_origin.ORIGIN), "invalid_check_authority_protocol")
    return row[0]


def validate_chain(c, rows, original, observed, environment, roles):
    checks._require(len(rows) == 3 and [r[0] for r in rows] == [2, 3, 4], "stage_check_upgrade_receipt_required")
    _, raw, size, digest = rows[2]
    checks._require(type(raw) is bytes and type(size) is int and 0 < len(raw) == size <= 16384
                    and p._sha(raw) == digest, "changed_stage_check_upgrade")
    value = p._decode(raw)
    checks._shape(value, revisions.RECEIPT_FIELDS | {"previous_upgrade_sha256"})
    checks._require(p._canonical(value) == raw and type(value["schema_version"]) is int and value["schema_version"] == 1
        and type(value["from_catalog_version"]) is int and value["from_catalog_version"] == 3
        and type(value["to_catalog_version"]) is int and value["to_catalog_version"] == 4
        and value["previous_upgrade_sha256"] == rows[1][3]
        and value["upgrade_migration_sha256"] == p._sha(MIGRATION.read_bytes())
        and p._canonical(value["checks_metadata"]) == p._canonical(original)
        and p._canonical(value["observations_metadata"]) == p._canonical(observed)
        and value["current_checks_catalog_sha256"] == p._catalog(c, pg.SCHEMA)
        and value["observations_catalog_sha256"] == observed["catalog_sha"]
        and value["environment"] == environment and (value["owner_role"], value["runtime_role"]) == roles
        and spend._time(value["installed_at"]) == value["installed_at"], "changed_stage_check_upgrade")
    return value["prior_checks_catalog_sha256"]


def install(c, environment, *, now):
    from src.commands import postgres_sync_checks as sync
    from src.commands.postgres_authority import PostgresCommandAuthority
    # Same serialization point as EVERY legacy owner initializer. Take it
    # before prerequisite creation, absence checks or catalog snapshots; direct
    # installer calls and concurrent public owner calls both recheck under it.
    PostgresCommandAuthority._pointer(c, lock=True)
    sync.install(c, environment, now=now)
    if installed(c):
        pg.validate(c, environment)
        return
    c.execute("LOCK TABLE theheat_checks.sets IN ACCESS EXCLUSIVE MODE")
    original = revisions.metadata(c, pg.SCHEMA)
    roles = (original["owner_role"], original["runtime_role"])
    observed = revisions.observation_metadata(c, environment, roles)
    prior = c.execute("SELECT sha FROM theheat_checks.schema_upgrades WHERE upgrade_version=3").fetchone()[0]
    catalog = p._catalog(c, pg.SCHEMA)
    c.execute(MIGRATION.read_text())
    role = p._driver().sql.Identifier(roles[1])
    for table in TABLES:
        for statement in (f"REVOKE ALL ON theheat_checks.{table} FROM PUBLIC",
                          f"REVOKE ALL ON theheat_checks.{table} FROM {{}}",
                          f"GRANT SELECT,INSERT ON theheat_checks.{table} TO {{}}"):
            c.execute(p._driver().sql.SQL(statement).format(role))
    for name in ("check_stage_progress", "check_stage_seal", "check_legacy_protocol"):
        c.execute(p._driver().sql.SQL(f"REVOKE ALL ON FUNCTION theheat_checks.{name}() FROM {{}}").format(role))
    value = dict(schema_version=1, from_catalog_version=3, to_catalog_version=4,
        previous_upgrade_sha256=prior, upgrade_migration_sha256=p._sha(MIGRATION.read_bytes()),
        checks_metadata=original, observations_metadata=observed, prior_checks_catalog_sha256=catalog,
        current_checks_catalog_sha256=p._catalog(c, pg.SCHEMA), observations_catalog_sha256=observed["catalog_sha"],
        environment=environment, owner_role=roles[0], runtime_role=roles[1], installed_at=spend._time(now))
    checks._require(revisions.metadata(c, pg.SCHEMA) == original
                    and revisions.observation_metadata(c, environment, roles) == observed, "changed_upgrade_predecessor")
    raw = p._canonical(value)
    c.execute("INSERT INTO theheat_checks.schema_upgrades VALUES(4,%s,%s,%s)", (raw, len(raw), p._sha(raw)))
    pg.validate(c, environment)


def _proof(c, digest):
    row = c.execute("SELECT payload,byte_count FROM theheat_checks.stage_proof_artifacts WHERE sha=%s", (digest,)).fetchone()
    checks._require(row is not None and type(row[0]) is bytes and type(row[1]) is int
                    and 0 < len(row[0]) == row[1] <= 16384 and p._sha(row[0]) == digest, "changed_stage_prefix")
    value, canonical = p._reader_decode_with_canonical(c, row[0])
    checks._require(canonical == row[0], "changed_stage_prefix")
    return value


def _record_proof(c, body):
    raw = checks._encoded(body, 16384)
    digest = p._sha(raw)
    c.execute("INSERT INTO theheat_checks.stage_proof_artifacts VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (digest, raw, len(raw)))
    checks._require(p._canonical(_proof(c, digest)) == raw, "changed_stage_prefix")
    return digest


def _prefix(identity, packet, entries):
    return dict(schema_version=2, authority_protocol=2, check_set_id=identity, enrollment_id=packet["enrollment_id"],
        packet_sha256=p._sha(p._canonical(packet)), state_version=packet["state_version"], state_sha256=packet["state_sha256"],
        current_context=packet["current_context"], useful_until=packet["useful_until"], check_date=packet["check_date"], stages=entries)


def _prefix_sha(body):
    # Artifact IDs hash exact canonical BYTES; revision fingerprints use a
    # different typed encoding and must never be substituted for artifact IDs.
    return p._sha(checks._encoded(body, 16384))


def lease(c, identity, fence=None):
    suffix, args = ("ORDER BY fence DESC LIMIT 1", (identity,)) if fence is None else ("AND fence=%s", (identity, fence))
    row = c.execute(f"SELECT {','.join(LEASE_FIELDS)} FROM theheat_checks.stage_leases WHERE check_set_id=%s {suffix}", args).fetchone()
    if row is None:
        return None
    value = dict(zip(LEASE_FIELDS, row, strict=True))
    body = {k: v for k, v in value.items() if k != "capability_id"}
    checks._require(value["check_set_id"] == identity and type(value["authority_protocol"]) is int and value["authority_protocol"] == 2
        and value["stage"] in checks.STAGES and type(value["fence"]) is int
        and value["fence"] == checks.STAGES.index(value["stage"]) + 1
        and fingerprint(body) == value["capability_id"]
        and spend._time(value["recorded_at"]) == value["recorded_at"]
        and spend._time(value["expires_at"]) == value["expires_at"]
        and 1 <= (utc_datetime(value["expires_at"]) - utc_datetime(value["recorded_at"])).total_seconds() <= 180,
        "changed_stage_capability")
    return value


def historical_lease(c, identity, fence):
    value = lease(c, identity, fence)
    return (value["owner"], value["recorded_at"], value["expires_at"]) if value is not None else None


def _seal(c, identity, stage):
    row = c.execute(f"SELECT {','.join(SEAL_FIELDS)} FROM theheat_checks.stage_seals WHERE check_set_id=%s AND stage=%s", (identity, stage)).fetchone()
    return dict(zip(SEAL_FIELDS, row, strict=True)) if row is not None else None


def _cap_bounds(cap, packet):
    start = utc_datetime(cap["recorded_at"])
    checks._require(cap["owner"] == "revision-checks:" + packet["enrollment_id"]
        and cap["recorded_at"][:10] == packet["check_date"] and packet["captured_at"] <= cap["recorded_at"]
        and utc_datetime(cap["expires_at"]) == min(start + timedelta(seconds=180), utc_datetime(packet["useful_until"])),
        "changed_stage_capability")


def _exact_record(c, identity, packet, stage, attempt, *, resolved=None):
    from src.commands import postgres_check_observations as observations
    cap = lease(c, identity, checks.STAGES.index(stage) + 1)
    checks._require(cap is not None and attempt is not None, "stage_evidence_missing")
    _cap_bounds(cap, packet)
    binding = attempt["binding"]
    checks._require(binding["owner"] == cap["owner"] and binding["fence"] == cap["fence"], "changed_stage_capability")
    request = pg._raw(c, "request_artifacts", binding["request_sha256"])
    expected = canonical_json(check_requests.prepare_request(packet, stage, resolved=resolved)).encode()
    checks._require(request == expected, "check_request_not_exact")
    observation = observations._observation(c, identity, stage, attempt)
    checks._require(observation is not None and observation["complete"] is True, "check_response_not_retained")
    raw = observations._raw(c, "raw_artifacts", observation["raw_sha256"])
    observed_at = c.execute("SELECT recorded_at FROM theheat_check_executions.observations WHERE grant_id=%s", (attempt["grant_id"],)).fetchone()[0]
    checks._require(spend._time(observed_at) == observed_at and attempt["recorded_at"] <= observed_at < cap["expires_at"]
                    and observed_at[:10] == packet["check_date"] and observed_at < packet["useful_until"], "late_stage_observation")
    if stage == "deterministic":
        checks._require(raw == canonical_json(check_requests.deterministic_result(packet, resolved=resolved)).encode(), "deterministic_check_changed")
    outcome = check_requests.interpret_observation(packet, stage, observation, raw, resolved=resolved)
    checks._require(outcome["execution_status"] == "completed" and outcome["verdict"] == "pass", "required_check_not_passed")
    receipt = dict(outcome, grant_id=attempt["grant_id"], request_sha256=p._sha(request))
    return cap, observed_at, receipt, observation["raw_sha256"]


def _verify_prefix(c, identity, packet, *, environment, resolved=None, length=None):
    """Re-read exact original evidence; neither hashes nor disposition flags suffice."""
    checks._require(protocol(c, identity) == 2, "stage_protocol_required")
    retained, enrolled = pg._packet(c, identity, environment)
    checks._require(p._canonical(retained) == p._canonical(packet), "changed_revision_check_packet")
    stages, attempts = pg._stages(c, identity, packet, enrolled)
    passed = next((i for i, stage in enumerate(checks.STAGES) if stages[stage] != "passed"), len(checks.STAGES))
    if length is None:
        length = passed
    checks._require(type(length) is int and 0 <= length <= passed <= 4, "required_checks_incomplete")
    entries: list[dict] = []
    records = {}
    body = _prefix(identity, packet, entries)
    for stage in checks.STAGES[:length]:
        cap, observed_at, expected_receipt, raw_sha = _exact_record(c, identity, packet, stage, attempts[stage], resolved=resolved)
        terminal = pg._terminal(c, attempts[stage])
        seal = _seal(c, identity, stage)
        checks._require(terminal is not None and terminal["disposition"] == "passed" and seal is not None, "stage_seal_required")
        checks._require(p._canonical(terminal["document"]) == p._canonical(expected_receipt), "check_receipt_not_exact")
        checks._require(cap["predecessor_prefix_sha256"] == _prefix_sha(body)
            and p._canonical(_proof(c, cap["predecessor_prefix_sha256"])) == p._canonical(body), "changed_stage_prefix")
        completed = seal["completed_at"]
        checks._require(spend._time(completed) == completed and observed_at <= terminal["recorded_at"] <= completed < cap["expires_at"]
            and completed < packet["useful_until"] and completed[:10] == packet["check_date"], "late_stage_completion")
        if entries:
            checks._require(entries[-1]["completed_at"] <= cap["recorded_at"] < entries[-1]["expires_at"], "expired_stage_predecessor")
        expected = dict(check_set_id=identity, stage=stage, grant_id=attempts[stage]["grant_id"], capability_id=cap["capability_id"],
            request_sha256=attempts[stage]["binding"]["request_sha256"], raw_sha256=raw_sha, receipt_sha256=terminal["sha256"], completed_at=completed)
        checks._require({k: seal[k] for k in expected} == expected, "changed_stage_seal")
        entry = dict(expected, owner=cap["owner"], fence=cap["fence"], recorded_at=cap["recorded_at"], expires_at=cap["expires_at"],
            begun_at=attempts[stage]["recorded_at"], observed_at=observed_at, receipt_recorded_at=terminal["recorded_at"])
        entries.append(entry)
        body = _prefix(identity, packet, list(entries))
        checks._require(seal["prefix_sha256"] == _prefix_sha(body)
            and p._canonical(_proof(c, seal["prefix_sha256"])) == p._canonical(body), "changed_stage_prefix")
        records[stage] = entry
    return body, records


class _Scope:
    def __init__(self, token, c, identity, owner, clock, expected):
        checks._require(token is _TOKEN, "scoped_revision_context_required")
        self.connection, self.identity, self.owner, self.clock, self.expected = c, identity, owner, clock, expected
        self.alive = True
        self.deadlines = []

    def close(self):
        self.alive = False


def _scope(c, identity, owner, clock, expected):
    return _Scope(_TOKEN, c, identity, owner, clock, expected)


def _require_scope(scope, c, identity):
    checks._require(type(scope) is _Scope and scope.alive and scope.connection is c and scope.identity == identity,
                    "scoped_revision_context_required")


def progression(c, identity, packet, environment):
    _, enrolled = pg._packet(c, identity, environment)
    stages, _ = pg._stages(c, identity, packet, enrolled)
    stage = next((s for s in checks.STAGES if stages[s] != "passed"), None)
    prior = checks.STAGES.index(stage) if stage is not None else 4
    seal = _seal(c, identity, checks.STAGES[prior - 1]) if prior else None
    return stage, seal["prefix_sha256"] if seal is not None else _prefix_sha(_prefix(identity, packet, []))


def current(c, identity, packet, payload, at):
    cap = lease(c, identity)
    checks._require(cap is not None and type(payload["fence"]) is int and payload["fence"] == cap["fence"]
                    and payload["owner"] == cap["owner"]
                    and utc_datetime(cap["recorded_at"]) <= utc_datetime(at) < utc_datetime(cap["expires_at"]), "stale_revision_check_owner")
    _cap_bounds(cap, packet)
    return cap


def _bind_prefix(c, identity, packet, cap, verified_prefix):
    """Bind an issued cap before any spend, including original-cap recovery.

    A completed status/replay prefix can include the cap's own seal. Its
    predecessor is always the strictly shorter prefix selected by stage ordinal.
    """
    length = checks.STAGES.index(cap["stage"])
    checks._require(len(verified_prefix["stages"]) >= length, "changed_stage_prefix")
    expected = _prefix(identity, packet, verified_prefix["stages"][:length])
    checks._require(cap["predecessor_prefix_sha256"] == _prefix_sha(expected)
        and p._canonical(_proof(c, cap["predecessor_prefix_sha256"])) == p._canonical(expected), "changed_stage_prefix")
    if length:
        predecessor = expected["stages"][-1]
        checks._require(utc_datetime(predecessor["completed_at"]) <= utc_datetime(cap["recorded_at"])
            < utc_datetime(predecessor["expires_at"]), "expired_stage_predecessor")


def acquire(c, identity, owner, ttl_seconds, *, now, environment, scope):
    _require_scope(scope, c, identity)
    pg.validate(c, environment)
    checks._require(protocol(c, identity) == 2 and type(ttl_seconds) is int and ttl_seconds == 180, "invalid_revision_check_lease")
    packet, _ = pg._packet(c, identity, environment)
    checks._require(owner == scope.owner == "revision-checks:" + packet["enrollment_id"], "check_owner_mismatch")
    at = pg._at(c, now)
    target = progression(c, identity, packet, environment)
    checks._require(target == scope.expected, "revision_check_progressed")
    stage = target[0]
    index = checks.STAGES.index(stage) if stage is not None else 4
    prefix, _ = _verify_prefix(c, identity, packet, environment=environment, resolved=getattr(scope, "resolved", None), length=index)
    checks._require(_prefix_sha(prefix) == target[1], "changed_stage_prefix")
    existing = lease(c, identity, index + 1 if stage is not None else 4)
    if existing is not None:
        _cap_bounds(existing, packet)
        _bind_prefix(c, identity, packet, existing, prefix)
        checks._require(existing["owner"] == owner, "revision_check_lease_busy")
        checks._require(utc_datetime(existing["recorded_at"]) <= utc_datetime(at)
                        < utc_datetime(existing["expires_at"]), "stale_revision_check_owner")
        scope.deadlines.append(existing["expires_at"])
        return dict(lease=existing)
    checks._require(stage is not None, "required_checks_incomplete")
    _, enrolled = pg._packet(c, identity, environment)
    stages, attempts = pg._stages(c, identity, packet, enrolled)
    checks._require(stages[stage] == "pending" and attempts[stage] is None, "required_check_not_passed")
    if index:
        previous = lease(c, identity, index)
        checks._require(previous is not None and at < previous["expires_at"], "expired_stage_predecessor")
        scope.deadlines.append(previous["expires_at"])
    digest = _record_proof(c, prefix)
    # FIRST issuance only: predecessor proof/artifact work precedes the new
    # cap's original clock. Existing caps above never change start or expiry.
    issued_at = pg._at(c, scope.clock())
    checks._require(utc_datetime(issued_at) >= utc_datetime(at), "revision_check_clock_regressed")
    checks._require(issued_at[:10] == packet["check_date"] and issued_at < packet["useful_until"], "revision_check_expired")
    if index:
        checks._require(issued_at < previous["expires_at"], "expired_stage_predecessor")
    at = issued_at
    scope.issued_at = utc_datetime(at)
    expires = spend._time(utc_text(min(utc_datetime(at) + timedelta(seconds=180), utc_datetime(packet["useful_until"]))))
    checks._require((utc_datetime(expires) - utc_datetime(at)).total_seconds() >= 1, "revision_check_expired")
    value = dict(check_set_id=identity, authority_protocol=2, stage=stage, fence=index + 1, owner=owner,
                 recorded_at=at, expires_at=expires, predecessor_prefix_sha256=digest)
    value["capability_id"] = fingerprint(value)
    c.execute(f"INSERT INTO theheat_checks.stage_leases({','.join(LEASE_FIELDS)}) VALUES({','.join(['%s'] * len(LEASE_FIELDS))})",
              tuple(value[k] for k in LEASE_FIELDS))
    scope.deadlines.append(expires)
    return dict(lease=value)


def apply(c, action, payload, *, now, environment, request=None, receipt=None, scope=None):
    """Actual scoped v2 mutation/status boundary; no public dictionary grants scope."""
    fields = {"status": checks._BASE, "begin": checks._BASE | {"stage", "reservation"}, "complete": checks._BASE | {"stage", "grant_id"}}
    checks._require(action in fields, "unknown_check_action")
    checks._shape(payload, fields[action])
    payload = json.loads(checks._encoded(payload, 8192))
    identity = payload["check_set_id"]
    _require_scope(scope, c, identity)
    pg.validate(c, environment)
    checks._require(protocol(c, identity) == 2, "stage_protocol_required")
    at = pg._at(c, now)
    packet, enrolled = pg._packet(c, identity, environment)
    pg._current(c, packet, payload, at, environment)
    cap = current(c, identity, packet, payload, at)
    checks._require(payload["owner"] == scope.owner, "check_owner_mismatch")
    scope.deadlines.append(cap["expires_at"])
    stages, attempts = pg._stages(c, identity, packet, enrolled)
    count = next((i for i, s in enumerate(checks.STAGES) if stages[s] != "passed"), 4)
    prefix, _ = _verify_prefix(c, identity, packet, environment=environment, resolved=getattr(scope, "resolved", None), length=count)
    _bind_prefix(c, identity, packet, cap, prefix)
    if action == "status":
        return dict(check_set_id=identity, stages=stages, blocked_reason=None, required_checks_completed=count == 4,
                    publication_approved=False, dispatch_granted=False, accounting_complete=False, cost_usd=None)
    stage = payload["stage"]
    checks._require(stage in checks.STAGES and cap["stage"] == stage, "stale_revision_check_owner")
    prior = attempts[stage]
    if action == "begin":
        checks._require(type(request) is bytes and 0 < len(request) <= checks.MAX_INPUT_BYTES and receipt is None, "invalid_check_request")
        request_sha = p._sha(request)
        if prior is not None:
            checks._require(prior["binding"]["request_sha256"] == request_sha
                and canonical_json(prior["binding"]["reservation"]) == canonical_json(payload["reservation"]), "conflicting_check_attempt")
            return dict(grant_id=prior["grant_id"], dispatch_granted=False, publication_approved=False)
        checks._require(count == checks.STAGES.index(stage) and stages[stage] == "pending", "required_predecessor_not_passed")
        checks._require(request == canonical_json(check_requests.prepare_request(packet, stage, resolved=getattr(scope, "resolved", None))).encode(), "check_request_not_exact")
        reservation, intent_id = payload["reservation"], None
        if stage == "deterministic":
            checks._require(reservation is None, "local_check_cannot_spend")
        else:
            pg._reservation(reservation, packet, stage, request_sha)
            intent_id = reservation["intent_id"]
            existing = spend._record(c, intent_id)
            checks._require(existing is None or existing["state"] == "reserved", "check_spend_already_used")
            spend.apply(c, "reserve", reservation, now=at, environment=environment)
            grant = spend.apply(c, "dispatch", {"intent_id": intent_id}, now=at, environment=environment)
            checks._require(grant["dispatch_granted"], "check_spend_not_granted")
        binding = dict(check_set_id=identity, stage=stage, request_sha256=request_sha,
            reservation=reservation, owner=payload["owner"], fence=payload["fence"], begun_at=at)
        grant_id = fingerprint(binding)
        pg._artifact(c, "request_artifacts", request)
        digest = pg._artifact(c, "binding_artifacts", checks._encoded(binding, 8192))
        c.execute("INSERT INTO theheat_checks.attempts VALUES(%s,%s,%s,%s,%s,%s,%s)", (grant_id, identity, stage, digest, request_sha, intent_id, at))
        return dict(grant_id=grant_id, dispatch_granted=True, publication_approved=False)
    checks._require(request is None and prior is not None and prior["grant_id"] == payload["grant_id"], "unknown_check_grant")
    checks._require(prior["binding"]["owner"] == payload["owner"] and prior["binding"]["fence"] == payload["fence"], "check_receipt_owner_mismatch")
    receipt = json.loads(checks._encoded(receipt, checks.MAX_RECEIPT_BYTES))
    disposition = pg._receipt_doc(receipt, prior)
    raw = checks._encoded(receipt, checks.MAX_RECEIPT_BYTES)
    terminal = pg._terminal(c, prior)
    if terminal is not None:
        checks._require(terminal["sha256"] == p._sha(raw) and p._canonical(terminal["document"]) == raw, "conflicting_check_completion")
        return dict(reused=True, disposition=terminal["disposition"], publication_approved=False)
    # Nonpass evidence remains terminal but cannot produce a stage seal.
    exact = None
    if disposition == "passed":
        exact = _exact_record(c, identity, packet, stage, prior, resolved=getattr(scope, "resolved", None))
        checks._require(p._canonical(exact[2]) == raw and exact[1] <= at, "check_receipt_not_exact")
    digest = pg._artifact(c, "receipt_artifacts", raw)
    c.execute("INSERT INTO theheat_checks.receipts VALUES(%s,%s,%s,%s)", (prior["grant_id"], digest, disposition, at))
    if exact is not None:
        original_cap, observed_at, _, raw_sha = exact
        completed = spend._time(scope.clock())
        scope.completed_at = utc_datetime(completed)
        checks._require(at <= completed < original_cap["expires_at"] and completed < packet["useful_until"]
                        and completed[:10] == packet["check_date"], "late_stage_completion")
        entry = dict(check_set_id=identity, stage=stage, grant_id=prior["grant_id"], capability_id=original_cap["capability_id"],
            request_sha256=prior["binding"]["request_sha256"], raw_sha256=raw_sha, receipt_sha256=digest, completed_at=completed,
            owner=original_cap["owner"], fence=original_cap["fence"], recorded_at=original_cap["recorded_at"], expires_at=original_cap["expires_at"],
            begun_at=prior["recorded_at"], observed_at=observed_at, receipt_recorded_at=at)
        proof_sha = _record_proof(c, _prefix(identity, packet, [*prefix["stages"], entry]))
        seal = {k: entry[k] for k in SEAL_FIELDS if k != "prefix_sha256"}
        seal["prefix_sha256"] = proof_sha
        c.execute(f"INSERT INTO theheat_checks.stage_seals({','.join(SEAL_FIELDS)}) VALUES({','.join(['%s'] * len(SEAL_FIELDS))})",
                  tuple(seal[k] for k in SEAL_FIELDS))
    return dict(reused=False, disposition=disposition, publication_approved=False)


def final_deadline(c, identity, packet):
    cap = lease(c, identity, 4)
    checks._require(cap is not None and _seal(c, identity, "critic") is not None, "required_checks_incomplete")
    _cap_bounds(cap, packet)
    return min(cap["expires_at"], packet["useful_until"])


def completion(c, identity, packet, now, environment, *, resolved=None):
    prefix, records = _verify_prefix(c, identity, packet, environment=environment, resolved=resolved, length=4)
    deadline = final_deadline(c, identity, packet)
    at = spend._time(utc_text(now))
    checks._require(at < deadline and at[:10] == packet["check_date"], "stale_revision_check_owner")
    body = dict(schema_version=2, authority_protocol=2, origin_kind=packet["origin_kind"], enrollment_id=packet["enrollment_id"],
        check_set_id=identity, packet_sha256=p._sha(p._canonical(packet)), stages=records, prefix_sha256=_prefix_sha(prefix), final_ready_until=deadline)
    return {**body, "completion_sha256": fingerprint(body)}
