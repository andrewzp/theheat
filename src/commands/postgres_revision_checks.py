"""Saved-revision check origin within the existing immutable PostgreSQL engine."""
from __future__ import annotations

from datetime import timedelta

from src.commands import check_journal as checks, postgres_spending as spend
from src.commands.schema import utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from src.two_bot import check_origin as origin

MIGRATION = p.MIGRATION.with_name("011_saved_revision_checks.sql")
META_FIELDS = ("singleton", "version", "migration_sha", "catalog_sha", "environment", "owner_role", "runtime_role")
RECEIPT_FIELDS = {"schema_version", "from_catalog_version", "to_catalog_version", "upgrade_migration_sha256",
                  "checks_metadata", "observations_metadata", "prior_checks_catalog_sha256",
                  "current_checks_catalog_sha256", "observations_catalog_sha256", "environment", "owner_role",
                  "runtime_role", "installed_at"}


def upgraded(c):
    return c.execute("SELECT to_regclass('theheat_checks.schema_upgrades')").fetchone()[0] is not None


def metadata(c, schema):
    # Internal constant schemas only; observation validation must not recurse.
    checks._require(schema in {"theheat_checks", "theheat_check_executions"}, "invalid_check_schema")
    row = c.execute(f"SELECT {','.join(META_FIELDS)} FROM {schema}.metadata WHERE singleton=1").fetchone()
    checks._require(row is not None, "check_schema_metadata_missing")
    return dict(zip(META_FIELDS, row, strict=True))


def observation_metadata(c, environment, roles):
    checks._require(c.execute("SELECT to_regclass('theheat_check_executions.metadata')").fetchone()[0] is not None,
                    "check_execution_migration_required")
    value = metadata(c, "theheat_check_executions")
    checks._require(value["version"] == 1
                    and value["migration_sha"] == p._sha(p.MIGRATION.with_name("008_check_observations.sql").read_bytes())
                    and value["environment"] == environment
                    and (value["owner_role"], value["runtime_role"]) == roles
                    and value["catalog_sha"] == p._catalog(c, "theheat_check_executions"),
                    "changed_check_execution_schema")
    return value


def validate_catalog(c, original, environment, roles):
    rows = c.execute("SELECT upgrade_version,receipt_bytes,byte_count,sha FROM theheat_checks.schema_upgrades LIMIT 2").fetchall()
    checks._require(len(rows) == 1, "revision_check_upgrade_receipt_required")
    version, raw, size, digest = rows[0]
    checks._require(type(version) is int and version == 2 and type(raw) is bytes
                    and type(size) is int and 0 < size == len(raw) <= 16384 and p._sha(raw) == digest,
                    "changed_revision_check_upgrade")
    value = p._decode(raw)
    checks._shape(value, RECEIPT_FIELDS)
    checks._require(p._canonical(value) == raw and type(value["schema_version"]) is int and value["schema_version"] == 1
                    and type(value["from_catalog_version"]) is int and value["from_catalog_version"] == 1
                    and type(value["to_catalog_version"]) is int and value["to_catalog_version"] == 2,
                    "unsupported_revision_check_upgrade")
    observed = observation_metadata(c, environment, roles)
    checks._require(value["upgrade_migration_sha256"] == p._sha(MIGRATION.read_bytes())
                    and p._canonical(value["checks_metadata"]) == p._canonical(original)
                    and p._canonical(value["observations_metadata"]) == p._canonical(observed)
                    and value["prior_checks_catalog_sha256"] == original["catalog_sha"]
                    and value["observations_catalog_sha256"] == observed["catalog_sha"]
                    and value["current_checks_catalog_sha256"] == p._catalog(c, "theheat_checks")
                    and value["environment"] == environment
                    and (value["owner_role"], value["runtime_role"]) == roles
                    and spend._time(value["installed_at"]) == value["installed_at"], "changed_revision_check_upgrade")


def install(c, environment, *, now):
    from src.commands import postgres_checks as pg, postgres_check_observations as observations
    pg.install(c, environment)
    observations.install(c, environment)
    if upgraded(c):
        pg.validate(c, environment)
        return
    original = metadata(c, "theheat_checks")
    roles = (original["owner_role"], original["runtime_role"])
    observed = observation_metadata(c, environment, roles)
    c.execute("LOCK TABLE theheat_checks.sets IN ACCESS EXCLUSIVE MODE")
    c.execute(MIGRATION.read_text())
    role = p._driver().sql.Identifier(roles[1])
    for table in ("schema_upgrades", "draft_leases"):
        c.execute(f"REVOKE ALL ON theheat_checks.{table} FROM PUBLIC")
        c.execute(p._driver().sql.SQL(f"REVOKE ALL ON theheat_checks.{table} FROM {{}}").format(role))
        c.execute(p._driver().sql.SQL(f"GRANT SELECT ON theheat_checks.{table} TO {{}}").format(role))
    c.execute(p._driver().sql.SQL("GRANT INSERT ON theheat_checks.draft_leases TO {}").format(role))
    value = dict(schema_version=1, from_catalog_version=1, to_catalog_version=2,
                 upgrade_migration_sha256=p._sha(MIGRATION.read_bytes()), checks_metadata=original,
                 observations_metadata=observed, prior_checks_catalog_sha256=original["catalog_sha"],
                 current_checks_catalog_sha256=p._catalog(c, "theheat_checks"),
                 observations_catalog_sha256=observed["catalog_sha"], environment=environment,
                 owner_role=roles[0], runtime_role=roles[1], installed_at=spend._time(now))
    checks._require(metadata(c, "theheat_checks") == original
                    and observation_metadata(c, environment, roles) == observed, "changed_upgrade_predecessor")
    raw = p._canonical(value)
    c.execute("INSERT INTO theheat_checks.schema_upgrades VALUES(2,%s,%s,%s)", (raw, len(raw), p._sha(raw)))
    pg.validate(c, environment)


def packet(c, identity, row, raw):
    value = p._decode(raw)
    checks._require(origin.packet_verification(value) == "verified_saved_draft_revision"
                    and fingerprint(value) == identity and value["enrollment_id"] == row[6]
                    and row[4] == origin.ORIGIN and row[5] == origin.NAMESPACE
                    and row[0] is row[1] is None and row[3] == value["captured_at"], "changed_revision_check_set")
    receipt, retained = p.PostgresProjectionRepository._read(c, origin.NAMESPACE, value["enrollment_id"])
    checks._require(receipt.canonical_sha256 == p._sha(raw) and p._canonical(retained) == raw,
                    "changed_revision_check_enrollment")
    return value, row[3]


def historical_lease(c, identity, fence):
    return c.execute("SELECT owner,recorded_at,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s AND fence=%s",
                     (identity, fence)).fetchone()


def acquire(c, identity, owner, ttl_seconds, *, now, environment):
    from src.commands import postgres_checks as pg
    pg.validate(c, environment)
    checks._require(upgraded(c), "revision_check_migration_required")
    value, _ = pg._packet(c, identity, environment)
    checks._require(value.get("origin_kind") == origin.ORIGIN, "revision_check_origin_required")
    from src.commands.spend_journal import _id
    _id(owner)
    checks._require(len(owner) <= 128 and type(ttl_seconds) is int and 1 <= ttl_seconds <= 300, "invalid_revision_check_lease")
    at = pg._at(c, now)
    last = c.execute("SELECT fence,owner,recorded_at,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
    if last and at < last[3]:
        checks._require(owner == last[1], "revision_check_lease_busy")
        return dict(lease=dict(fence=last[0], owner=last[1], recorded_at=last[2], expires_at=last[3]))
    fence = last[0] + 1 if last else 1
    checks._require(fence <= 1000, "revision_check_lease_capacity")
    deadline = min(utc_datetime(at) + timedelta(seconds=ttl_seconds), utc_datetime(value["useful_until"]))
    checks._require((deadline - utc_datetime(at)).total_seconds() >= 1, "revision_check_expired")
    expires = spend._time(deadline.isoformat().replace("+00:00", "Z"))
    c.execute("INSERT INTO theheat_checks.draft_leases(check_set_id,fence,owner,expires_at,recorded_at) VALUES(%s,%s,%s,%s,%s)",
              (identity, fence, owner, expires, at))
    return dict(lease=dict(fence=fence, owner=owner, recorded_at=at, expires_at=expires))


def retain_source(c, draft, command, refs, value, *, environment):
    """Bind a successful P25/I2 admission; never manufacture legacy provenance."""
    from src.commands import postgres_sourced_generation as generation, postgres_batch as batch
    if not generation.exists(c, generation.JOB, value["job_id"]):
        return
    job = generation.read(c, generation.JOB, value["job_id"])
    brief = generation.document(generation.read(c, generation.INPUT, job["brief_id"]))
    registration = batch.read(c, value["job_id"], environment=environment)
    from src.commands.batch_journal import _plan
    plan = _plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    checks._require(p._canonical(brief["bundle"]) == p._canonical(value["bundle"])
                    and fingerprint(job["memory"]) == fingerprint(value["memory"])
                    and job["custom_id"] == value["custom_id"], "changed_admitted_source_origin")
    document = dict(schema_version=1, draft_id=draft["id"], event_id=draft["event_id"], admission_command_id=command.command_id,
        admission_input_id=refs["admission_input_id"], admission_input_sha256=refs["admission_input_sha256"],
        job_id=value["job_id"], brief_id=job["brief_id"], plan_sha256=value["plan_sha256"],
        bundle_sha256=fingerprint(value["bundle"]), memory_sha256=fingerprint(value["memory"]),
        source_useful_until=brief["useful_until"], provenance_useful_until=plan["useful_until"])
    generation.record(c, origin.SOURCE_NAMESPACE, fingerprint({"draft_id": draft["id"]}), document)


def source(c, draft):
    from src.commands import postgres_sourced_generation as generation, postgres_candidate_admission as admission
    from src.commands.postgres_authority import _command, _decode
    identity = fingerprint({"draft_id": draft["id"]})
    receipt, value = p.PostgresProjectionRepository._read(c, origin.SOURCE_NAMESPACE, identity)
    expected = {"schema_version", "draft_id", "event_id", "admission_command_id", "admission_input_id",
                "admission_input_sha256", "job_id", "brief_id", "plan_sha256", "bundle_sha256", "memory_sha256",
                "source_useful_until", "provenance_useful_until"}
    checks._shape(value, expected)
    checks._require(type(value["schema_version"]) is int and value["schema_version"] == 1
                    and value["draft_id"] == draft["id"] and value["event_id"] == draft["event_id"], "changed_draft_source_origin")
    row = c.execute("SELECT i.command_bytes,i.digest,r.result_bytes,r.digest FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s", (value["admission_command_id"],)).fetchone()
    checks._require(row is not None, "draft_source_admission_missing")
    command, result = _command(row[0], row[1]), _decode(row[2], row[3])
    checks._require(command.action == "admit_checked_candidate" and result["status"] == "applied"
                    and result["candidate"]["draft_id"] == draft["id"]
                    and all(command.payload[k] == value[k] for k in ("admission_input_id", "admission_input_sha256")),
                    "changed_draft_source_admission")
    captured = admission.read_input(c, command.payload)
    brief = generation.document(generation.read(c, generation.INPUT, value["brief_id"]))
    job = generation.read(c, generation.JOB, value["job_id"])
    from src.commands import postgres_batch as batch
    from src.commands.batch_journal import _plan
    registration = batch.read(c, value["job_id"], environment="local")
    plan = _plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    bundle = draft.get("review_context", {}).get("two_bot", {}).get("bundle")
    checks._require(p._canonical(bundle) == p._canonical(captured["bundle"]) == p._canonical(brief["bundle"])
                    and value["bundle_sha256"] == fingerprint(bundle)
                    and value["memory_sha256"] == fingerprint(captured["memory"]) == fingerprint(job["memory"])
                    and value["job_id"] == captured["job_id"] and value["plan_sha256"] == captured["plan_sha256"]
                    and job["brief_id"] == value["brief_id"] and value["source_useful_until"] == brief["useful_until"]
                    and registration["plan_sha256"] == value["plan_sha256"]
                    and value["provenance_useful_until"] == plan["useful_until"],
                    "changed_draft_source_origin")
    return dict(namespace=origin.SOURCE_NAMESPACE, snapshot_id=identity, canonical_sha256=receipt.canonical_sha256), value, captured


def enroll(c, state, version, draft, *, now, policy, profile, environment):
    from src.commands import postgres_checks as pg
    pg.validate(c, environment)
    checks._require(upgraded(c), "revision_check_migration_required")
    ref, retained, captured = source(c, draft)
    from src.commands.reducer import _identity
    media = draft["media_review_binding"]
    at = spend._time(utc_text(now))
    deadline = min(utc_datetime(retained["source_useful_until"]), utc_datetime(retained["provenance_useful_until"]),
                   now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
    packet = dict(schema_version=3, origin_kind=origin.ORIGIN, enrollment_id="", draft_target=_identity(draft),
        final_text=draft["text"], text_sha256=_identity(draft)["text_sha256"], state_version=version,
        state_sha256=p._sha(p._canonical(state)), source_origin=ref,
        current_context=dict(bundle_sha256=fingerprint(captured["bundle"]), memory_sha256=fingerprint(captured["memory"]),
                             policy_sha256=fingerprint(policy), publication_epoch="local-preview-paused-v1"),
        source_useful_until=retained["source_useful_until"], provenance_useful_until=retained["provenance_useful_until"],
        useful_until=spend._time(utc_text(deadline)), policy=policy, bundle=captured["bundle"], memory=captured["memory"],
        required_stages=list(checks.STAGES), checker_state=state, checker_state_sha256=fingerprint(state),
        check_date=at[:10], captured_at=at, renderer_profile_sha256=profile,
        media={**{k: media[k] for k in ("proposal_sha256", "packet_sha256", "review_sha256")}, "review_command_id":media["command_id"]})
    packet["enrollment_id"] = origin.enrollment_id(packet)
    origin.validate_revision(packet)
    prior = c.execute("SELECT check_set_id FROM theheat_checks.sets WHERE draft_namespace=%s AND draft_enrollment_id=%s", (origin.NAMESPACE, packet["enrollment_id"])).fetchone()
    if prior:
        pg._packet(c, prior[0], environment)
        return prior[0]
    checks._require(c.execute("SELECT count(*) FROM theheat_checks.sets").fetchone()[0] < checks.MAX_SETS, "check_set_capacity")
    raw = checks._encoded(packet, pg.MAX_PACKET_BYTES)
    encoded, fields = p._snapshot(packet)
    p.PostgresProjectionRepository._record(c, origin.NAMESPACE, packet["enrollment_id"], encoded, fields)
    digest = pg._artifact(c, "packet_artifacts", raw)
    identity = fingerprint(packet)
    c.execute("INSERT INTO theheat_checks.sets(check_set_id,packet_sha256,recorded_at,origin_kind,draft_namespace,draft_enrollment_id) VALUES(%s,%s,%s,%s,%s,%s)",
              (identity, digest, at, origin.ORIGIN, origin.NAMESPACE, packet["enrollment_id"]))
    return identity


def current(c, packet, payload, at, environment):
    from src.commands.postgres_authority import PostgresCommandAuthority
    checks._require(environment == "local", "revision_check_environment_refused")
    origin.validate_revision(packet)
    checks._policy(packet["current_context"])
    version, state = PostgresCommandAuthority._state(c, lock=True)
    checks._require(version == packet["state_version"] and p._sha(p._canonical(state)) == packet["state_sha256"]
                    and payload["checker_state_sha256"] == packet["checker_state_sha256"]
                    and p._canonical(payload["current_context"]) == p._canonical(packet["current_context"]), "changed_revision_check_state")
    checks._require(at[:10] == packet["check_date"] and at < spend._time(packet["useful_until"]), "revision_check_expired")
    identity = fingerprint(packet)
    lease = c.execute("SELECT fence,owner,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
    checks._require(lease is not None and type(payload["fence"]) is int and lease[0] == payload["fence"]
                    and lease[1] == payload["owner"] and at < lease[2], "stale_revision_check_owner")
