"""Local fixture obligations joined to the single retained editorial approval.

All operations use the caller's existing authority transaction and pointer lock.
Append-only leases and dispatch barriers never change editorial state or renew
its original checks. A missing response is uncertainty, never retry permission.
"""
from __future__ import annotations

from datetime import timedelta
import re

from src.commands import hosted_fixture
from src.commands import postgres_editor_media as editor, postgres_media as media
from src.commands.schema import CommandError, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.posting.local_delivery import FixtureConfiguration, LEASE_SECONDS, MIN_WINDOW_SECONDS, SCOPE, STAGES, MAX_REQUEST
from src.storage import postgres_projection as p

SCHEMA = "theheat_delivery"
MIGRATION = p.MIGRATION.with_name("012_local_delivery.sql")
PREVIEW_MIGRATION = p.MIGRATION.with_name("014_preview_delivery.sql")
META = ("version", "migration_sha", "catalog_sha", "environment", "owner_role", "runtime_role")
TABLES = ("metadata", "artifacts", "intents", "work_items", "leases", "attempts", "observations", "receipts")


def refuse(condition, code):
    if not condition:
        raise CommandError(code, "Local delivery is withheld; retained evidence remains unchanged")


def upgraded(c):
    return c.execute("SELECT to_regclass('theheat_commands.delivery_upgrade')").fetchone()[0] is not None


def validate_core_catalog(c, original, environment):
    """Called by the command validator instead of altering its old metadata."""
    row = c.execute("SELECT receipt_bytes,sha FROM theheat_commands.delivery_upgrade WHERE singleton=1").fetchone()
    p._require(row is not None and type(row[0]) is bytes and 0 < len(row[0]) <= 16384
               and p._sha(row[0]) == row[1], "delivery_upgrade_receipt_required")
    receipt = p._decode(row[0])
    preview = type(receipt) is dict and type(receipt.get("version")) is int and receipt["version"] == 2
    extension = {"preview_migration_sha256", "environment", "owner_role", "runtime_role"} if preview else set()
    p._require(not preview or (environment == original[3] == "preview"
        and receipt.get("preview_migration_sha256") == p._sha(PREVIEW_MIGRATION.read_bytes())
        and receipt.get("environment") == "preview"
        and (receipt.get("owner_role"), receipt.get("runtime_role")) == tuple(original[4:])), "changed_delivery_upgrade")
    p._require(type(receipt) is dict and set(receipt) == extension | {
        "version", "original_metadata", "command_catalog_sha256", "delivery_catalog_sha256",
        "migration_sha256", "installed_at"} and p._canonical(receipt) == row[0]
        and type(receipt["version"]) is int and receipt["version"] == (2 if preview else 1)
        and receipt["original_metadata"] == list(original)
        and receipt["migration_sha256"] == p._sha(MIGRATION.read_bytes())
        and utc_text(utc_datetime(receipt["installed_at"])) == receipt["installed_at"]
        and receipt["command_catalog_sha256"] == p._catalog(c, "theheat_commands"), "changed_delivery_upgrade")
    metadata = c.execute(f"SELECT {','.join(META)} FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    p._require(metadata is not None and metadata[0] == 1 and metadata[1] == receipt["migration_sha256"]
        and metadata[2] == receipt["delivery_catalog_sha256"] == p._catalog(c, SCHEMA)
        and metadata[3] == environment == original[3] == ("preview" if preview else "local")
        and tuple(metadata[4:]) == tuple(original[4:]), "changed_delivery_catalog")


def validate(c, environment):
    refuse(environment in {"local", "preview"} and upgraded(c), "delivery_migration_required")
    original = c.execute(f"SELECT {','.join(META)} FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    p._require(original is not None and original[0] == 1
               and original[1] == p._sha(p.MIGRATION.with_name("002_command_core.sql").read_bytes()),
               "unsupported_command_schema")
    validate_core_catalog(c, original, environment)


def install(c, environment, *, now):
    refuse(environment in {"local", "preview"}, "delivery_local_only")
    if upgraded(c):
        validate(c, environment)
        return
    refuse(c.execute("SELECT to_regnamespace(%s)", (SCHEMA,)).fetchone()[0] is None,
           "delivery_intermediate_catalog")
    media.validate(c, environment)
    original = c.execute(f"SELECT {','.join(META)} FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    p._require(original[2] == p._catalog(c, "theheat_commands"), "changed_command_schema")
    c.execute(MIGRATION.read_text())
    if environment == "preview":
        c.execute(PREVIEW_MIGRATION.read_text())
    role = p._driver().sql.Identifier(original[5])
    for target in (f"SCHEMA {SCHEMA}", f"ALL TABLES IN SCHEMA {SCHEMA}", f"ALL FUNCTIONS IN SCHEMA {SCHEMA}",
                   "TABLE theheat_commands.delivery_upgrade"):
        c.execute(f"REVOKE ALL ON {target} FROM PUBLIC")
        c.execute(p._driver().sql.SQL(f"REVOKE ALL ON {target} FROM {{}}").format(role))
    for statement in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                      f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                      "GRANT SELECT ON theheat_commands.delivery_upgrade TO {}",
                      "GRANT INSERT ON " + ",".join(f"{SCHEMA}.{name}" for name in TABLES if name != "metadata") + " TO {}"):
        c.execute(p._driver().sql.SQL(statement).format(role))
    catalog = p._catalog(c, SCHEMA)
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), catalog, environment, *original[4:]))
    receipt = dict(version=1, original_metadata=list(original), command_catalog_sha256=p._catalog(c, "theheat_commands"),
                   delivery_catalog_sha256=catalog, migration_sha256=p._sha(MIGRATION.read_bytes()), installed_at=utc_text(now))
    if environment == "preview":
        receipt.update(version=2, preview_migration_sha256=p._sha(PREVIEW_MIGRATION.read_bytes()),
                       environment=environment, owner_role=original[4], runtime_role=original[5])
    raw = p._canonical(receipt)
    c.execute("INSERT INTO theheat_commands.delivery_upgrade VALUES(1,%s,%s)", (raw, p._sha(raw)))
    validate(c, environment)


def configure(authority, path):
    refuse(hosted_fixture.allowed(authority), "delivery_local_only")
    config = FixtureConfiguration.load(path)
    with authority.projections._connection() as c:
        authority._validate(c)
        validate(c, authority.environment)
    authority.delivery_configuration = config


def configuration(authority):
    config = getattr(authority, "delivery_configuration", None)
    if not hosted_fixture.allowed(authority) or not isinstance(config, FixtureConfiguration):
        raise CommandError("delivery_fixture_configuration_required", "An explicit local fixture configuration is required")
    try:
        return config.read(), config.sha256
    except (ValueError, OSError):
        raise CommandError("delivery_configuration_changed", "The explicit local fixture configuration is unavailable") from None


def raw(c, digest, *, bound=MAX_REQUEST):
    p._require(type(digest) is str and bool(re.fullmatch(r"[0-9a-f]{64}", digest)), "invalid_delivery_artifact")
    row = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.artifacts WHERE sha=%s", (digest,)).fetchone()
    p._require(row is not None and type(row[0]) is int and 0 <= row[0] == row[1] <= bound,
               "delivery_artifact_bound")
    result = c.execute(f"SELECT payload FROM {SCHEMA}.artifacts WHERE sha=%s", (digest,)).fetchone()[0]
    p._require(type(result) is bytes and len(result) == row[0] and p._sha(result) == digest, "changed_delivery_artifact")
    return result


def artifact(c, payload):
    p._require(type(payload) is bytes and len(payload) <= MAX_REQUEST, "delivery_artifact_bound")
    digest = p._sha(payload)
    c.execute(f"INSERT INTO {SCHEMA}.artifacts VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (digest, payload, len(payload)))
    p._require(raw(c, digest) == payload, "changed_delivery_artifact")
    return digest


def document(c, digest):
    encoded = raw(c, digest, bound=131072)
    value = p._decode(encoded)
    p._require(type(value) is dict and p._canonical(value) == encoded, "changed_delivery_document")
    return value


def record(c, value):
    encoded = p._canonical(value)
    p._require(len(encoded) <= 131072, "delivery_document_bound")
    return artifact(c, encoded)


def read(c, intent_id):
    row = c.execute(f"SELECT command_id,draft_id,event_id,proposal_sha256,artifact_sha FROM {SCHEMA}.intents WHERE intent_id=%s", (intent_id,)).fetchone()
    refuse(row is not None, "delivery_intent_not_found")
    value = document(c, row[4])
    p._require(value["intent_id"] == intent_id and tuple(value[k] for k in ("command_id", "draft_id", "event_id", "proposal_sha256")) == tuple(row[:4])
               and value["scope"] == SCOPE and value["publication_approved"] is False, "changed_delivery_intent")
    return value


def work(value, platform):
    refuse(platform in STAGES, "delivery_platform_unknown")
    return fingerprint(dict(scope=SCOPE, instance_id=value["fixture"]["instance_id"], intent_id=value["intent_id"], platform=platform))


def attempt(c, value, platform, stage):
    refuse(stage in STAGES.get(platform, ()), "delivery_stage_unknown")
    row = c.execute(f"SELECT attempt_id,binding_sha,request_sha,fence FROM {SCHEMA}.attempts WHERE work_id=%s AND stage=%s",
                    (work(value, platform), stage)).fetchone()
    if row is None:
        return None
    binding = document(c, row[1])
    p._require(binding["attempt_id"] == row[0] and binding["intent_id"] == value["intent_id"]
               and binding["platform"] == platform and binding["stage"] == stage
               and binding["request_sha256"] == row[2] and binding["fence"] == row[3], "changed_delivery_attempt")
    document(c, row[2])
    return binding


def receipts(c, saved):
    if saved is None:
        return []
    from src.posting.delivery_receipts import interpret
    value = read(c, saved["intent_id"])
    rows = c.execute(f"SELECT r.artifact_sha,o.observation_id,o.metadata_sha,o.raw_sha FROM {SCHEMA}.observations o JOIN {SCHEMA}.receipts r USING(observation_id) WHERE o.attempt_id=%s ORDER BY o.observation_id LIMIT 65",
                     (saved["attempt_id"],)).fetchall()
    p._require(len(rows) <= 64, "delivery_observation_capacity")
    result = []
    for digest, observation_id, metadata_sha, raw_sha in rows:
        receipt = document(c, digest)
        derived = dict(interpret(value, saved, document(c, metadata_sha), raw(c, raw_sha, bound=131072)),
                       observation_id=observation_id, attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"])
        p._require(receipt == derived, "changed_delivery_receipt")
        result.append(receipt)
    return result


def outcome(c, saved):
    if saved is None:
        return dict(status="pending", result=None)
    values = receipts(c, saved)
    confirmed = [v["result"] for v in values if v["status"] == "confirmed"]
    not_sent = any(v["status"] == "not_sent" for v in values)
    if confirmed:
        if not_sent or any(p._canonical(v) != p._canonical(confirmed[0]) for v in confirmed):
            return dict(status="unknown", result=None, reason="conflicting_delivery_receipts")
        return dict(status="confirmed", result=confirmed[0])
    return dict(status="not_sent" if not_sent else "unknown", result=None)


def hold(c, draft):
    rows = c.execute(f"SELECT intent_id FROM {SCHEMA}.intents WHERE draft_id=%s OR event_id=%s LIMIT 1025",
                     (draft["id"], draft["event_id"])).fetchall()
    refuse(len(rows) <= 1024, "delivery_event_capacity")
    for (identity,) in rows:
        value = read(c, identity)
        for platform, stages in STAGES.items():
            for stage in stages:
                observed = outcome(c, attempt(c, value, platform, stage))
                refuse(observed["status"] != "unknown", "delivery_prior_outcome_unknown")
                refuse(stage != "create" or observed["status"] != "confirmed", "delivery_event_already_confirmed")


def prepare(authority, c, draft, command):
    """Domain preflight in the original approval savepoint, before state writes."""
    config, digest = configuration(authority)
    validate(c, authority.environment)
    hold(c, draft)
    binding = draft["approval_binding"]
    package = media.read(c, binding["media"]["proposal_sha256"], authority.environment)
    return dict(schema_version=1, scope=SCOPE, publication_approved=False, intent_id=binding["publish_intent_id"],
                command_id=command.command_id, draft_id=draft["id"], event_id=draft["event_id"], text=draft["text"],
                approval_binding=binding, fixture=config, configuration_sha256=digest,
                proposal_sha256=binding["media"]["proposal_sha256"], package=package["receipt"],
                png_sha256=p._sha(package["assets"]["preview.png"]), png_byte_count=len(package["assets"]["preview.png"]), alt_sha256=p._sha(package["assets"]["alt.txt"]),
                created_at=utc_text(utc_datetime(command.requested_at)))


def references(value):
    return dict(scope=SCOPE, publication_approved=False, instance_id=value["fixture"]["instance_id"],
                intent_id=value["intent_id"], obligations={platform:work(value, platform) for platform in STAGES})


def context(authority, c, value, resolve_principal, now):
    config, digest = configuration(authority)
    refuse(config == value["fixture"] and digest == value["configuration_sha256"], "delivery_configuration_changed")
    version, state = authority._state(c, lock=True)
    drafts = [d for d in state["drafts"] if isinstance(d, dict) and d.get("id") == value["draft_id"]]
    refuse(len(drafts) == 1, "delivery_draft_missing")
    draft = drafts[0]
    refuse(p._canonical(draft.get("approval_binding")) == p._canonical(value["approval_binding"])
           and draft["text"] == value["text"] and draft["event_id"] == value["event_id"], "delivery_approval_changed")
    policy = current_editorial_policy()
    inputs = editor.inputs(authority, c, draft, policy, now)
    refuse(editor.parked(authority, c, draft, state, version, inputs, policy, now, resolve_principal), "delivery_parked_approval_required")
    package = editor.reviewed(authority, c, draft, inputs, policy, resolve_principal)
    refuse(package["receipt"] == value["package"] and p._sha(package["assets"]["preview.png"]) == value["png_sha256"]
           and p._sha(package["assets"]["alt.txt"]) == value["alt_sha256"], "delivery_media_changed")
    check_id = value["approval_binding"]["completion"]["check_set_id"]
    expires = c.execute("SELECT expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (check_id,)).fetchone()[0]
    deadline = min(utc_datetime(expires), utc_datetime(value["approval_binding"]["useful_until"]))
    return package, deadline


def enroll(authority, c, value, resolve_principal, now):
    # Command result and exact successor state are already queryable in this same
    # transaction; none is visible outside until the outer COMMIT succeeds.
    context(authority, c, value, resolve_principal, now)
    digest = record(c, value)
    c.execute(f"INSERT INTO {SCHEMA}.intents VALUES(%s,%s,%s,%s,%s,%s)",
              (value["intent_id"], value["command_id"], value["draft_id"], value["event_id"], value["proposal_sha256"], digest))
    for platform in STAGES:
        c.execute(f"INSERT INTO {SCHEMA}.work_items VALUES(%s,%s,%s)", (work(value, platform), value["intent_id"], platform))


def acquire(authority, c, value, platform, stage, owner, resolve_principal, now):
    refuse(type(owner) is str and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", owner), "delivery_owner_required")
    package, deadline = context(authority, c, value, resolve_principal, now)
    refuse(stage in STAGES.get(platform, ()), "delivery_stage_unknown")
    previous = STAGES[platform][:STAGES[platform].index(stage)]
    prior = {key:outcome(c, attempt(c, value, platform, key)) for key in previous}
    refuse(all(row["status"] == "confirmed" for row in prior.values()), "delivery_dependency_unconfirmed")
    existing = attempt(c, value, platform, stage)
    if existing is not None:
        return dict(dispatch_granted=False, attempt=existing, outcome=outcome(c, existing))
    row = c.execute(f"SELECT fence,owner,recorded_at,expires_at FROM {SCHEMA}.leases WHERE work_id=%s AND stage=%s ORDER BY fence DESC LIMIT 1",
                    (work(value, platform), stage)).fetchone()
    refuse(row is None or utc_datetime(row[2]) <= now, "delivery_clock_regressed")
    if row is not None and utc_datetime(row[3]) > now:
        refuse(row[1] == owner, "delivery_lease_busy")
        fence, expires = row[0], row[3]
    else:
        fence = 1 if row is None else row[0] + 1
        refuse(fence <= 1000, "delivery_lease_capacity")
        expires = utc_text(min(now + timedelta(seconds=LEASE_SECONDS), deadline))
        refuse((utc_datetime(expires) - now).total_seconds() >= MIN_WINDOW_SECONDS, "delivery_window_insufficient")
        c.execute(f"INSERT INTO {SCHEMA}.leases VALUES(%s,%s,%s,%s,%s,%s)",
                  (work(value, platform), stage, fence, owner, utc_text(now), expires))
    refuse((min(utc_datetime(expires), deadline) - now).total_seconds() >= MIN_WINDOW_SECONDS, "delivery_window_insufficient")
    return dict(dispatch_granted=False, lease=dict(owner=owner, fence=fence, expires_at=expires),
                prior={key:row["result"] for key,row in prior.items()},
                png=package["assets"]["preview.png"], alt=package["assets"]["alt.txt"].decode("utf-8"))


def begin(authority, c, value, platform, stage, lease, request, body, resolve_principal, now):
    _, deadline = context(authority, c, value, resolve_principal, now)
    # Re-derive all dependencies/current lease rather than trusting the prepared
    # worker's prior payload, even though intake is not a public HTTP endpoint.
    prepared = acquire(authority, c, value, platform, stage, lease["owner"], resolve_principal, now)
    if "attempt" in prepared:
        return dict(dispatch_granted=False)
    refuse(prepared["lease"] == lease and (deadline-now).total_seconds() >= MIN_WINDOW_SECONDS,
           "delivery_stale_fence")
    from src.posting.delivery_receipts import verify_request
    verify_request(value, platform, stage, prepared, request, body)
    body_sha = artifact(c, body)
    refuse(request["body_sha256"] == body_sha, "delivery_request_changed")
    request_sha = record(c, request)
    binding = dict(intent_id=value["intent_id"], platform=platform, stage=stage, owner=lease["owner"],
                   fence=lease["fence"], expires_at=lease["expires_at"], request_sha256=request_sha,
                   configuration_sha256=value["configuration_sha256"], recorded_at=utc_text(now), prior=prepared["prior"])
    binding["attempt_id"] = fingerprint(binding)
    digest = record(c, binding)
    c.execute(f"INSERT INTO {SCHEMA}.attempts VALUES(%s,%s,%s,%s,%s,%s)",
              (binding["attempt_id"], work(value, platform), stage, lease["fence"], digest, request_sha))
    return dict(dispatch_granted=True, binding=binding)


def observe(c, value, saved, observation, response):
    from src.posting.delivery_receipts import validate_observation
    validate_observation(value, saved, observation, response)
    existing = attempt(c, value, saved["platform"], saved["stage"])
    refuse(existing == saved, "delivery_observation_attempt_mismatch")
    count = c.execute(f"SELECT count(*) FROM {SCHEMA}.observations WHERE attempt_id=%s", (saved["attempt_id"],)).fetchone()[0]
    refuse(count < 64, "delivery_observation_capacity")
    response_sha = artifact(c, response)
    metadata_sha = record(c, observation)
    identity = fingerprint(dict(attempt_id=saved["attempt_id"], metadata_sha=metadata_sha, raw_sha=response_sha))
    c.execute(f"INSERT INTO {SCHEMA}.observations VALUES(%s,%s,%s,%s) ON CONFLICT(observation_id) DO NOTHING",
              (identity, saved["attempt_id"], metadata_sha, response_sha))
    # Raw evidence commits in a separate transaction before interpretation.
    return identity


def before_call(authority, c, value, saved, resolve_principal, now):
    """Last independent currentness check after the durable barrier.

    This cannot make a database decision atomic with an external request. The
    bounded transport preserves the original deadline across that final race.
    """
    refuse(attempt(c, value, saved["platform"], saved["stage"]) == saved, "delivery_attempt_changed")
    _, deadline = context(authority, c, value, resolve_principal, now)
    lease = c.execute(f"SELECT fence,owner,expires_at FROM {SCHEMA}.leases WHERE work_id=%s AND stage=%s ORDER BY fence DESC LIMIT 1",
        (work(value, saved["platform"]), saved["stage"])).fetchone()
    refuse(lease == (saved["fence"], saved["owner"], saved["expires_at"]), "delivery_stale_fence")
    refuse(utc_datetime(saved["recorded_at"]) <= now < min(deadline, utc_datetime(saved["expires_at"])), "delivery_window_expired")


def finish(c, value, saved):
    from src.posting.delivery_receipts import interpret
    rows = c.execute(f"SELECT observation_id,metadata_sha,raw_sha FROM {SCHEMA}.observations WHERE attempt_id=%s ORDER BY observation_id LIMIT 65",
                     (saved["attempt_id"],)).fetchall()
    refuse(len(rows) <= 64, "delivery_observation_capacity")
    for identity, metadata_sha, raw_sha in rows:
        observation, response = document(c, metadata_sha), raw(c, raw_sha, bound=131072)
        result = dict(interpret(value, saved, observation, response), observation_id=identity,
                      attempt_id=saved["attempt_id"], request_sha256=saved["request_sha256"])
        digest = record(c, result)
        c.execute(f"INSERT INTO {SCHEMA}.receipts VALUES(%s,%s) ON CONFLICT(observation_id) DO NOTHING", (identity, digest))
        retained = c.execute(f"SELECT artifact_sha FROM {SCHEMA}.receipts WHERE observation_id=%s", (identity,)).fetchone()[0]
        p._require(retained == digest, "changed_delivery_receipt")
    return outcome(c, saved)


def projection(authority, c, draft_id, resolve_principal, now):
    validate(c, authority.environment)
    rows = c.execute(f"SELECT intent_id FROM {SCHEMA}.intents WHERE draft_id=%s ORDER BY intent_id LIMIT 65", (draft_id,)).fetchall()
    refuse(len(rows) <= 64, "delivery_draft_capacity")
    result = []
    for (identity,) in rows:
        value = read(c, identity)
        current, reason = True, None
        try:
            context(authority, c, value, resolve_principal, now)
        except CommandError as exc:
            current, reason = False, exc.code
        result.append(dict(intent_id=identity, current=current, reason=reason, stages={
            platform:{stage:outcome(c, attempt(c, value, platform, stage)) for stage in stages}
            for platform,stages in STAGES.items()}))
    return dict(scope=SCOPE, publication_approved=False, intents=result)
