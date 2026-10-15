"""Immutable catalog3 and synchronous enrollment in the existing check engine."""
from datetime import timedelta

from src.commands import check_journal as checks, postgres_revision_checks as revisions
from src.commands.schema import utc_text, utc_datetime
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from src.two_bot import synchronous_origin as origin

MIGRATION = p.MIGRATION.with_name("013_synchronous_checks.sql")
FIELDS = revisions.RECEIPT_FIELDS | {"previous_upgrade_sha256"}


def upgraded(c):
    return revisions.upgraded(c) and c.execute("SELECT 1 FROM theheat_checks.schema_upgrades WHERE upgrade_version=3").fetchone() is not None


def validate_chain(c, rows, original, observed, environment, roles):
    checks._require(len(rows) == 2 and [r[0] for r in rows] == [2, 3], "sync_check_upgrade_receipt_required")
    _, raw, size, digest = rows[1]
    checks._require(type(raw) is bytes and type(size) is int and 0 < len(raw) == size <= 16384 and p._sha(raw) == digest,
        "changed_sync_check_upgrade")
    value = p._decode(raw)
    checks._shape(value, FIELDS)
    checks._require(p._canonical(value) == raw and type(value["schema_version"]) is int and value["schema_version"] == 1
        and type(value["from_catalog_version"]) is int and value["from_catalog_version"] == 2
        and type(value["to_catalog_version"]) is int and value["to_catalog_version"] == 3
        and value["previous_upgrade_sha256"] == rows[0][3]
        and value["upgrade_migration_sha256"] == p._sha(MIGRATION.read_bytes())
        and value["checks_metadata"] == original and value["observations_metadata"] == observed
        and value["current_checks_catalog_sha256"] == p._catalog(c, "theheat_checks")
        and value["observations_catalog_sha256"] == observed["catalog_sha"]
        and value["environment"] == environment and (value["owner_role"], value["runtime_role"]) == roles
        and revisions.spend._time(value["installed_at"]) == value["installed_at"], "changed_sync_check_upgrade")
    return value["prior_checks_catalog_sha256"]


def install(c, environment, *, now):
    from src.commands import postgres_checks as pg
    revisions.install(c, environment, now=now)
    if upgraded(c):
        pg.validate(c, environment)
        return
    original = revisions.metadata(c, "theheat_checks")
    roles = (original["owner_role"], original["runtime_role"])
    observed = revisions.observation_metadata(c, environment, roles)
    prior = c.execute("SELECT sha FROM theheat_checks.schema_upgrades WHERE upgrade_version=2").fetchone()[0]
    catalog = p._catalog(c, "theheat_checks")
    c.execute("LOCK TABLE theheat_checks.sets IN ACCESS EXCLUSIVE MODE")
    c.execute(MIGRATION.read_text())
    value = dict(schema_version=1, from_catalog_version=2, to_catalog_version=3,
        previous_upgrade_sha256=prior, upgrade_migration_sha256=p._sha(MIGRATION.read_bytes()),
        checks_metadata=original, observations_metadata=observed, prior_checks_catalog_sha256=catalog,
        current_checks_catalog_sha256=p._catalog(c, "theheat_checks"), observations_catalog_sha256=observed["catalog_sha"],
        environment=environment, owner_role=roles[0], runtime_role=roles[1], installed_at=revisions.spend._time(now))
    checks._require(revisions.metadata(c, "theheat_checks") == original
        and revisions.observation_metadata(c, environment, roles) == observed, "changed_upgrade_predecessor")
    raw = p._canonical(value)
    c.execute("INSERT INTO theheat_checks.schema_upgrades VALUES(3,%s,%s,%s)", (raw, len(raw), p._sha(raw)))
    pg.validate(c, environment)


def packet(c, identity, row, raw):
    from src.commands import postgres_synchronous_generation as sync
    value = p._decode(raw)
    checks._require(origin.validate(value) in {"verified_synchronous_writer", "retained_synchronous_writer"} and fingerprint(value) == identity
        and row[0] is row[1] is row[5] is row[6] is None and row[4] == origin.ORIGIN
        and row[7] == origin.NAMESPACE and row[8] == value["enrollment_id"] and row[3] == value["captured_at"], "changed_sync_check_set")
    receipt, retained = p.PostgresProjectionRepository._read(c, origin.NAMESPACE, value["enrollment_id"])
    checks._require(receipt.canonical_sha256 == p._sha(raw) and p._canonical(retained) == raw, "changed_sync_check_enrollment")
    sync.verify_candidate(c, value)
    return value, row[3]


def enroll(c, value, refs, row, state, version, policy, *, now, environment, resolved=None):
    from src.commands import postgres_checks as pg, postgres_sourced_generation as generation
    from src.commands import postgres_synchronous_generation as sync
    from src.two_bot.candidate_derivation import derive_candidate
    pg.validate(c, environment)
    checks._require(upgraded(c), "sync_check_migration_required")
    job = sync.job(c, value["generation_id"])
    candidate = row["candidate"]
    derived = derive_candidate(candidate, value["candidate_id"], value["bundle"], policy, resolved=resolved)
    packet = dict(schema_version=5 if resolved is not None else 4, origin_kind=origin.ORIGIN, enrollment_id="",
        **{k:value[k] for k in origin.REFERENCES}, candidate=candidate, derivation=derived,
        derivation_id=fingerprint(derived), text_sha256=derived["text_sha256"], current_context=value["current_context"],
        useful_until=revisions.spend._time(utc_text(min(utc_datetime(job["useful_until"]), now.replace(hour=0, minute=0, second=0, microsecond=0)+timedelta(days=1)))),
        policy=policy, bundle=value["bundle"], memory=value["memory"], required_stages=list(checks.STAGES),
        checker_state=state, checker_state_sha256=fingerprint(state), state_sha256=p._sha(p._canonical(state)), state_version=version,
        check_date=utc_text(now)[:10], captured_at=revisions.spend._time(utc_text(now)), admission_input_id=refs["admission_input_id"],
        admission_input_sha256=refs["admission_input_sha256"])
    packet["enrollment_id"] = origin.enrollment_id(packet)
    if generation.exists(c, origin.NAMESPACE, packet["enrollment_id"]):
        packet = generation.read(c, origin.NAMESPACE, packet["enrollment_id"])
    checks._require(origin.validate(packet, resolved=resolved) == "verified_synchronous_writer", "sync_context_required")
    raw = checks._encoded(packet, pg.MAX_PACKET_BYTES)
    identity = fingerprint(packet)
    if not c.execute("SELECT 1 FROM theheat_checks.sets WHERE check_set_id=%s", (identity,)).fetchone():
        checks._require(c.execute("SELECT count(*) FROM theheat_checks.sets").fetchone()[0] < checks.MAX_SETS, "check_set_capacity")
        generation.record(c, origin.NAMESPACE, packet["enrollment_id"], packet)
        digest = pg._artifact(c, "packet_artifacts", raw)
        c.execute("INSERT INTO theheat_checks.sets(check_set_id,packet_sha256,recorded_at,origin_kind,sync_namespace,sync_enrollment_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (identity, digest, packet["captured_at"], origin.ORIGIN, origin.NAMESPACE, packet["enrollment_id"]))
    pg._packet(c, identity, environment)
    return dict(check_set_id=identity)


def current(c, packet, payload, at, environment, *, resolved=None):
    from src.commands import postgres_synchronous_generation as sync
    from src.commands.postgres_authority import PostgresCommandAuthority
    from src.commands import hosted_fixture
    hosted_fixture.profile(c, environment)
    checks._require(origin.validate(packet, resolved=resolved) == "verified_synchronous_writer", "sync_context_required")
    checks._policy(packet["current_context"])
    sync.verify_candidate(c, packet)
    version, state = PostgresCommandAuthority._state(c, lock=True)
    checks._require(version == packet["state_version"] and p._sha(p._canonical(state)) == packet["state_sha256"], "changed_sync_check_state")
    checks._require(payload["current_context"] == packet["current_context"] and payload["checker_state_sha256"] == packet["checker_state_sha256"], "changed_check_context")
    identity = fingerprint(packet)
    lease = c.execute("SELECT fence,owner,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
    checks._require(lease is not None and type(payload["fence"]) is int and (lease[0], lease[1]) == (payload["fence"], payload["owner"]), "stale_sync_check_owner")
    checks._require(at < lease[2] and at < packet["useful_until"] and at[:10] == packet["check_date"], "sync_check_expired")
