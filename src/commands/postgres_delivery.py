"""Local fixture obligations joined to the single retained editorial approval.

All operations use the caller's existing authority transaction and pointer lock.
Append-only leases and dispatch barriers never change editorial state or renew
its original checks. A missing response is uncertainty, never retry permission.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import time
import threading
import re
from uuid import UUID

from src.commands import hosted_fixture
from src.commands import postgres_editor_media as editor, postgres_media as media
from src.commands.media_journal import MediaJournalError
from src.commands.schema import CommandError, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.media import platform_description as descriptions
from src.posting.local_delivery import FixtureConfiguration, LEASE_SECONDS, MIN_WINDOW_SECONDS, SCOPE, STAGES, MAX_REQUEST
from src.storage import postgres_projection as p

SCHEMA = "theheat_delivery"
MIGRATION = p.MIGRATION.with_name("012_local_delivery.sql")
PREVIEW_MIGRATION = p.MIGRATION.with_name("014_preview_delivery.sql")
META = ("version", "migration_sha", "catalog_sha", "environment", "owner_role", "runtime_role")
TABLES = ("metadata", "artifacts", "intents", "work_items", "leases", "attempts", "observations", "receipts")
_ENROLLMENT_TOKEN = object()
_DISPATCH_TOKEN = object()


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


def description_profiles(authority):
    config = configuration(authority)[0] if hasattr(authority, "delivery_configuration") else None
    return descriptions.profiles(config)


def description_preflight(authority, c, draft, package):
    binding = draft.get("media_review_binding", {})
    refuse(binding.get("schema_version") == 2, "platform_description_required")
    command, _ = authority._intent(c, binding["command_id"])
    retained = media_commands_review(authority, c, command)
    record = retained["review"].get("platform_description")
    refuse(type(record) is dict and record["description_sha256"] == binding.get("platform_description_sha256"),
           "platform_description_changed")
    return _description_preflight(authority, draft, package, record)


def _description_preflight(authority, draft, package, record):
    # Private continuation: public/active callers still reconstruct the retained pair.
    binding = draft.get("media_review_binding", {})
    refuse(binding.get("schema_version") == 2 and type(record) is dict
           and record["description_sha256"] == binding.get("platform_description_sha256"), "platform_description_changed")
    try:
        descriptions.preflight(record, raw_alt=package["assets"]["alt.txt"], png=package["assets"]["preview.png"],
            expected_profiles=description_profiles(authority), graphic_spec=package["capture"]["inputs"]["graphic_spec"])
    except descriptions.DescriptionError as exc:
        raise CommandError(exc.code, "The complete selected delivery set is withheld") from None
    return record


def media_commands_review(authority, c, command):
    from src.commands import postgres_media_commands
    return postgres_media_commands.read(c, command, authority._result(c, command.command_id), authority.environment)


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
    description = description_preflight(authority, c, draft, package)
    return dict(schema_version=2, platform_description=description, scope=SCOPE, publication_approved=False, intent_id=binding["publish_intent_id"],
                command_id=command.command_id, draft_id=draft["id"], event_id=draft["event_id"], text=draft["text"],
                approval_binding=binding, fixture=config, configuration_sha256=digest,
                proposal_sha256=binding["media"]["proposal_sha256"], package=package["receipt"],
                png_sha256=p._sha(package["assets"]["preview.png"]), png_byte_count=len(package["assets"]["preview.png"]), alt_sha256=p._sha(package["assets"]["alt.txt"]),
                created_at=utc_text(utc_datetime(command.requested_at)))


def references(value):
    return dict(scope=SCOPE, publication_approved=False, instance_id=value["fixture"]["instance_id"],
                intent_id=value["intent_id"], obligations={platform:work(value, platform) for platform in STAGES})


def prepare_context(authority, *, intent_id=None, draft_id=None):
    """Resolve a compact source before the next delivery transaction, never in it."""
    from src.commands.postgres_sourced_generation import prepare_ghcn_bundle
    from src.two_bot.candidate_derivation import has_ghcn_reference
    with authority.projections._connection() as c:
        authority._validate(c)
        if intent_id is not None:
            draft_id = read(c, intent_id)["draft_id"]
        _, state = authority._state(c)
        drafts = [row for row in state["drafts"] if isinstance(row, dict) and row.get("id") == draft_id]
        saved = drafts[0].get("review_context") if len(drafts) == 1 else None
        two_bot = saved.get("two_bot") if isinstance(saved, dict) else None
        bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    return prepare_ghcn_bundle(authority, bundle) if has_ghcn_reference(bundle) else None



def _attempt_transition(previous, current, value, binding, request, targets):
    """The only allowed journal delta is this original unobserved barrier."""
    refuse(not previous["protection_codes"], "delivery_attempt_predecessor_protected")
    platform, stage = binding["platform"], binding["stage"]
    refuse(platform in STAGES and stage in STAGES[platform]
        and binding["intent_id"] == value["intent_id"]
        and binding["configuration_sha256"] == value["configuration_sha256"], "delivery_attempt_changed")
    seed = {key: item for key, item in binding.items() if key != "attempt_id"}
    refuse(binding["attempt_id"] == fingerprint(seed)
        and binding["request_sha256"] == p._sha(p._canonical(request)), "delivery_request_changed")
    work_id = work(value, platform)
    refuse(not any(row[1:3] == [work_id, stage] for row in previous["rows"]["attempts"]),
        "delivery_attempt_already_present")
    leases = [row for row in previous["rows"]["leases"] if row[:2] == [work_id, stage]]
    latest = max(leases, key=lambda row: row[2]) if leases else None
    refuse(latest is not None and latest[2:4] == [binding["fence"], binding["owner"]]
        and latest[5] == binding["expires_at"]
        and utc_datetime(latest[4]) <= utc_datetime(binding["recorded_at"]) < utc_datetime(latest[5]),
        "delivery_stale_fence")
    expected = deepcopy(previous)
    refuse(expected["outcomes"][value["intent_id"]][platform][stage] == dict(status="pending", result=None),
        "delivery_attempt_already_present")
    binding_raw, request_raw = p._canonical(binding), p._canonical(request)
    expected["rows"]["attempts"].append([binding["attempt_id"], work_id, stage, binding["fence"],
        p._sha(binding_raw), binding["request_sha256"]])
    expected["rows"]["attempts"].sort(key=lambda row: row[:2])
    artifacts = dict(expected["artifacts"])
    for raw_ in (binding_raw, request_raw):
        sha = p._sha(raw_)
        refuse(sha not in artifacts or artifacts[sha] == len(raw_), "delivery_request_changed")
        artifacts[sha] = len(raw_)
    expected["artifacts"] = [[sha, size] for sha, size in sorted(artifacts.items())]
    expected["outcomes"][value["intent_id"]][platform][stage] = dict(status="unknown", result=None)
    expected["protection_codes"] = [dict(draft_id=row["id"], event_id=row["event_id"],
        code="delivery_prior_outcome_unknown") for row in targets
        if row["id"] == value["draft_id"] or row["event_id"] == value["event_id"]]
    refuse(expected == current, "delivery_attempt_successor_changed")
    return expected


class _OwnAttemptContext:
    """One in-memory first-send proof; never serialized, reconstructed or renewed."""
    def __init__(self, authority, prepared, value, binding, request):
        from src.two_bot.ghcn_claim_view import ExecutionContext, ResolvedClaim
        refuse(type(prepared) is ExecutionContext and prepared.authority is authority and type(prepared.claim) is ResolvedClaim,
            "delivery_attempt_context_required")
        self.authority, self.claim = authority, prepared.claim
        self._base, self._footprint = deepcopy(prepared.checkpoint), prepared.footprint
        self._valid_until = prepared.valid_until
        self._value, self._binding, self._request = deepcopy(value), deepcopy(binding), deepcopy(request)
        self._claim_identity = self._claim_sha()
        self._expected: dict | None = None
        self._use = threading.Lock()

    def _claim_sha(self):
        from src.two_bot.ghcn_claim_view import json_tree
        refuse(fingerprint(json_tree(self.claim.full.to_dict())) == self.claim.full_sha256
            and fingerprint(json_tree(self.claim.view.to_dict())) == self.claim.view_sha256,
            "delivery_claim_changed")
        return fingerprint(dict(reference=self.claim.reference, full=self.claim.full_sha256, view=self.claim.view_sha256))

    def _source(self, authority, c, state, version):
        from src.two_bot import ghcn_claim_view as ghcn
        refuse(authority is self.authority and time.monotonic() <= self._valid_until,
            "ghcn_preparation_expired")
        refuse(self._claim_sha() == self._claim_identity, "delivery_claim_changed")
        ref = self.claim.reference
        material = ghcn._read_source(authority, c, ref["source_run_id"], ref["selection"])
        refuse(dict(state_version=version, state_sha256=ghcn.digest(state),
            source_sha256=ghcn._source_pins(material), policy_sha256=ghcn.digest(ghcn.current_editorial_policy()),
            configuration=ghcn.inputs.configuration()) == {key: item for key, item in self._base.items() if key != "delivery"},
            "ghcn_execution_context_changed")
        refuse(ghcn.baseline_footprint(ghcn.domain.configured(authority)) == self._footprint, "ghcn_baseline_changed")
        refuse(time.monotonic() <= self._valid_until, "ghcn_preparation_expired")
        refuse(self.claim.full.event_id == self._value["event_id"], "delivery_claim_changed")
        targets = ghcn.inputs.state_dependencies(state)["targets"]
        targets += [dict(id="ghcn-event-query:" + self.claim.full.event_id, event_id=self.claim.full.event_id)]
        return ghcn.domain.delivery_dependency(authority, c, targets), targets

    def _barrier(self, c):
        value, saved = read(c, self._value["intent_id"]), self._binding
        refuse(value == self._value and attempt(c, value, saved["platform"], saved["stage"]) == saved,
            "delivery_attempt_changed")
        refuse(document(c, saved["request_sha256"]) == self._request, "delivery_request_changed")
        body = raw(c, self._request["body_sha256"])
        refuse(len(body) == self._request["byte_count"] and p._sha(body) == self._request["body_sha256"],
            "delivery_request_changed")

    def current(self, authority, c, state, version):
        from src.storage.cyclone_supply import CycloneSupplyError
        refuse(self._expected is not None and self._use.acquire(blocking=False), "delivery_attempt_context_consumed")
        try:
            current, _ = self._source(authority, c, state, version)
            refuse(current == self._expected, "delivery_attempt_successor_changed")
            self._barrier(c)
            return self.claim
        except CycloneSupplyError as exc:
            raise CommandError(str(exc), "Current GHCN evidence changed") from None
        except OSError:
            raise CommandError("ghcn_baseline_unavailable", "Current GHCN baseline is unavailable") from None

    def matches(self, value, saved):
        return value == self._value and saved == self._binding


def attempt_successor(authority, c, value, prepared, binding, request, body):
    """Build only beside the exact begin write, before its owning COMMIT."""
    proof = _OwnAttemptContext(authority, prepared, value, binding, request)
    version, state = authority._state(c, lock=True)
    current, targets = proof._source(authority, c, state, version)
    proof._barrier(c)
    refuse(request["body_sha256"] == p._sha(body) and request["byte_count"] == len(body), "delivery_request_changed")
    proof._expected = _attempt_transition(proof._base["delivery"], current, value, binding, request, targets)
    return proof


class _OwnDispatchPass:
    """begin()'s own transaction: its acquire pass may reuse only this proof once.

    Minted inside begin and closed before begin returns. The acquire pass still
    rereads every role, configuration, state, policy, source and renderer input.
    Only when all of them equal the first pass exactly does it skip replaying
    the retained approval/review/check proof that pass verified on this same
    connection; any difference replays all of it. Never serialized, copied,
    renewed or accepted from a caller.
    """
    def __init__(self, token, authority, c, value, resolve_principal, now, ghcn):
        refuse(token is _DISPATCH_TOKEN, "delivery_dispatch_context_required")
        self._authority, self._connection, self._thread = authority, c, threading.get_ident()
        self._value, self._resolve, self._now, self._ghcn = p._canonical(value), resolve_principal, now, ghcn
        self._stage = "new"
        self._binding: tuple | None = None
        self._claim = None
        self._pair: tuple | None = None
        self._use = threading.Lock()

    def __copy__(self):
        raise CommandError("delivery_dispatch_context_changed", "A dispatch pass cannot be copied")

    def __deepcopy__(self, memo):
        raise CommandError("delivery_dispatch_context_changed", "A dispatch pass cannot be copied")

    def _owned(self, authority, c, value, resolve_principal, now):
        return (self._stage != "closed" and authority is self._authority and c is self._connection
                and threading.get_ident() == self._thread and resolve_principal is self._resolve
                and type(now) is type(self._now) and now == self._now and p._canonical(value) == self._value)

    def current(self, authority, c, state, version):
        # The claim is always the original context's own live reread.
        refuse(self._stage != "closed" and authority is self._authority and c is self._connection
               and threading.get_ident() == self._thread, "delivery_dispatch_context_changed")
        return self._ghcn.current(authority, c, state, version) if self._ghcn is not None else None

    def first(self, authority, c, value, resolve_principal, now):
        """Only begin's own first pass records; nested and later passes never do."""
        if self._stage == "new" and self._owned(authority, c, value, resolve_principal, now):
            self._stage = "recording"
            return True
        return False

    def _bound(self, draft, state, version, inputs, policy, claim):
        # The same exact encodings the passive inspection binds; never a field hash.
        identity = None if claim is None else dict(reference=claim.reference, full=claim.full_sha256, view=claim.view_sha256)
        return (type(version) is int, version, p._canonical(state),
                p._canonical(dict(draft=draft, inputs=inputs, policy=policy, claim=identity)))

    def record(self, draft, state, version, inputs, policy, claim, package, record):
        refuse(self._stage == "recording", "delivery_dispatch_context_changed")
        self._binding, self._claim = self._bound(draft, state, version, inputs, policy, claim), claim
        self._pair = deepcopy((package, record))
        self._stage = "verified"

    def consume(self, authority, c, draft, state, version, inputs, policy, claim, value, resolve_principal, now):
        """None replays the complete original proof; otherwise one exact reuse."""
        if self._stage != "verified" or self._pair is None or not self._use.acquire(blocking=False):
            return None
        self._stage = "consumed"
        if (not self._owned(authority, c, value, resolve_principal, now) or claim is not self._claim
                or self._bound(draft, state, version, inputs, policy, claim) != self._binding):
            return None
        package, record = deepcopy(self._pair)
        # The live remainder of the skipped approval and review reads, in their
        # original order: both approval roles, this pass's renderer/source inputs
        # against the retained package, then the reviewer each skipped read resolved.
        binding = draft["approval_binding"]
        approval, _ = authority._intent(c, binding["command_id"])
        editor.resolve(resolve_principal, approval.actor_subject, publisher=True)
        editor.resolve(resolve_principal, binding["requesting_actor"])
        editor._package_current(authority, c, draft, draft["media_review_binding"]["proposal_sha256"], inputs, package)
        for _ in range(2):
            editor.resolve(resolve_principal, record["reviewer"]["subject"])
        return package, record

    def close(self):
        self._stage = "closed"
        self._binding = self._claim = self._pair = None


def context(authority, c, value, resolve_principal, now, *, ghcn=None):
    """An active send boundary requires its own current execution checkpoint."""
    return _context(authority, c, value, resolve_principal, now,
        lambda state, version: ghcn.current(authority, c, state, version) if ghcn is not None else None,
        _dispatch=ghcn if type(ghcn) is _OwnDispatchPass else None)


def _enrollment_expected(previous, value):
    """Literal own intent/two work rows/artifact delta, never observed rebasing."""
    refuse(previous["catalog"] is not None and not previous["protection_codes"], "delivery_enrollment_predecessor_changed")
    expected = deepcopy(previous)
    identity = value["intent_id"]
    refuse(identity not in expected["outcomes"] and not any(row[0] == identity for row in expected["rows"]["intents"]),
           "delivery_enrollment_already_present")
    encoded = p._canonical(value)
    digest = p._sha(encoded)
    expected["rows"]["intents"].append([identity, value["command_id"], value["draft_id"], value["event_id"], value["proposal_sha256"], digest])
    expected["rows"]["intents"].sort(key=lambda row: row[:2])
    for platform in STAGES:
        work_id = work(value, platform)
        refuse(not any(row[0] == work_id for row in expected["rows"]["work_items"]), "delivery_enrollment_already_present")
        expected["rows"]["work_items"].append([work_id, identity, platform])
    expected["rows"]["work_items"].sort(key=lambda row: row[:2])
    artifacts = dict(expected["artifacts"])
    refuse(digest not in artifacts or artifacts[digest] == len(encoded), "delivery_enrollment_changed")
    artifacts[digest] = len(encoded)
    expected["artifacts"] = [[sha, size] for sha, size in sorted(artifacts.items())]
    expected["outcomes"][identity] = {platform: {stage: dict(status="pending", result=None) for stage in stages}
                                      for platform, stages in STAGES.items()}
    return expected


class _OwnEnrollmentTransition:
    """One exact owning transaction; no caller proof or new source lifetime."""
    def __init__(self, token, authority, c, prepared, value):
        from src.two_bot.ghcn_claim_view import ExecutionContext
        refuse(token is _ENROLLMENT_TOKEN and type(prepared) is ExecutionContext
               and prepared.authority is authority, "delivery_enrollment_context_required")
        self._authority, self._connection, self._prepared = authority, c, prepared
        self._value = deepcopy(value)
        self._expected = _enrollment_expected(prepared.checkpoint["delivery"], value)
        self._use = threading.Lock()

    def consume(self, authority, c, prepared):
        refuse(authority is self._authority and c is self._connection and prepared is self._prepared
               and self._use.acquire(blocking=False), "delivery_enrollment_context_consumed")
        refuse(p._canonical(read(c, self._value["intent_id"])) == p._canonical(self._value), "delivery_enrollment_changed")
        return deepcopy(self._expected)


def _context(authority, c, value, resolve_principal, now, resolve_claim, *, _dispatch=None):
    return _qualified_context(authority, c, value, resolve_principal, now, resolve_claim, _dispatch=_dispatch)


def _qualified_context(authority, c, value, resolve_principal, now, resolve_claim, *, _inspection=None, _dispatch=None):
    first = _dispatch is not None and _dispatch.first(authority, c, value, resolve_principal, now)
    # Revoke authority before consulting source/scientific execution evidence.
    editor.resolve(resolve_principal, value["approval_binding"]["publisher_subject"], publisher=True)
    editor.resolve(resolve_principal, value["approval_binding"]["requesting_actor"])
    config, digest = configuration(authority)
    refuse(config == value["fixture"] and digest == value["configuration_sha256"], "delivery_configuration_changed")
    version, state = authority._state(c, lock=True)
    drafts = [d for d in state["drafts"] if isinstance(d, dict) and d.get("id") == value["draft_id"]]
    refuse(len(drafts) == 1, "delivery_draft_missing")
    draft = drafts[0]
    refuse(p._canonical(draft.get("approval_binding")) == p._canonical(value["approval_binding"])
           and draft["text"] == value["text"] and draft["event_id"] == value["event_id"], "delivery_approval_changed")
    policy = current_editorial_policy()
    claim = resolve_claim(state, version)
    inputs = editor.inputs(authority, c, draft, policy, now, claim=claim)
    owned = _inspection is not None and _inspection.matches(authority, c, value)
    reused = None if owned or first or _dispatch is None else _dispatch.consume(
        authority, c, draft, state, version, inputs, policy, claim, value, resolve_principal, now)
    if owned:
        package, record = _inspection.consume(authority, c, draft, state, version, inputs, policy, claim, value, resolve_principal)
        refuse(value.get("schema_version") == 2, "platform_description_required")
        description = _description_preflight(authority, draft, package, record.get("platform_description"))
    elif reused is not None:
        package, record = reused
        refuse(value.get("schema_version") == 2, "platform_description_required")
        description = _description_preflight(authority, draft, package, record.get("platform_description"))
    else:
        refuse(editor.parked(authority, c, draft, state, version, inputs, policy, now, resolve_principal,
                             claim=claim), "delivery_parked_approval_required")
        package, record = editor._reviewed(authority, c, draft, inputs, policy, resolve_principal)
        refuse(value.get("schema_version") == 2, "platform_description_required")
        description = description_preflight(authority, c, draft, package)
    refuse((p._canonical(description) == p._canonical(value.get("platform_description")) if owned
            else description == value.get("platform_description")), "platform_description_changed")
    refuse((p._canonical(package["receipt"]) == p._canonical(value["package"]) if owned else package["receipt"] == value["package"])
           and p._sha(package["assets"]["preview.png"]) == value["png_sha256"]
           and p._sha(package["assets"]["alt.txt"]) == value["alt_sha256"], "delivery_media_changed")
    check_id = value["approval_binding"]["completion"]["check_set_id"]
    from src.commands import postgres_stage_revision_checks as stages
    if stages.protocol(c, check_id) == 2:
        from src.commands import postgres_checks
        packet, _ = postgres_checks._packet(c, check_id, authority.environment)
        expires = stages.final_deadline(c, check_id, packet)
    else:
        expires = c.execute("SELECT expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (check_id,)).fetchone()[0]
    deadline = min(utc_datetime(expires), utc_datetime(value["approval_binding"]["useful_until"]))
    if first:
        _dispatch.record(draft, state, version, inputs, policy, claim, package, record)
    return package, deadline


def enroll(authority, c, value, resolve_principal, now, *, ghcn=None):
    # Command result and exact successor state are already queryable in this same
    # transaction; none is visible outside until the outer COMMIT succeeds.
    context(authority, c, value, resolve_principal, now, ghcn=ghcn)
    transition = None
    if ghcn is not None and value["approval_binding"]["completion"].get("authority_protocol") == 2:
        from src.commands import postgres_stage_revision_checks as stages
        refuse(stages.protocol(c, value["approval_binding"]["completion"]["check_set_id"]) == 2,
               "stage_protocol_required")
        transition = _OwnEnrollmentTransition(_ENROLLMENT_TOKEN, authority, c, ghcn, value)
    digest = record(c, value)
    c.execute(f"INSERT INTO {SCHEMA}.intents VALUES(%s,%s,%s,%s,%s,%s)",
              (value["intent_id"], value["command_id"], value["draft_id"], value["event_id"], value["proposal_sha256"], digest))
    for platform in STAGES:
        c.execute(f"INSERT INTO {SCHEMA}.work_items VALUES(%s,%s,%s)", (work(value, platform), value["intent_id"], platform))
    return transition


def acquire(authority, c, value, platform, stage, owner, resolve_principal, now, *, ghcn=None):
    refuse(type(owner) is str and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}", owner), "delivery_owner_required")
    package, deadline = context(authority, c, value, resolve_principal, now, ghcn=ghcn)
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
    raw_alt = package["assets"]["alt.txt"]
    spec = package["capture"]["inputs"]["graphic_spec"]
    wire = descriptions.validate(value["platform_description"], raw_alt=raw_alt,
        png=package["assets"]["preview.png"], graphic_spec=spec)
    return dict(dispatch_granted=False, lease=dict(owner=owner, fence=fence, expires_at=expires),
                prior={key:row["result"] for key,row in prior.items()},
                png=package["assets"]["preview.png"], alt=wire, raw_alt=raw_alt, graphic_spec=spec)


def begin(authority, c, value, platform, stage, lease, request, body, resolve_principal, now, *, ghcn=None):
    # Both passes reread every live input. The acquire pass skips replaying only
    # the retained proof this same transaction's first pass just verified.
    own = _OwnDispatchPass(_DISPATCH_TOKEN, authority, c, value, resolve_principal, now, ghcn)
    try:
        _, deadline = context(authority, c, value, resolve_principal, now, ghcn=own)
        # Re-derive all dependencies/current lease rather than trusting the prepared
        # worker's prior payload, even though intake is not a public HTTP endpoint.
        prepared = acquire(authority, c, value, platform, stage, lease["owner"], resolve_principal, now, ghcn=own)
    finally:
        own.close()
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


def before_call(authority, c, value, saved, resolve_principal, now, *, ghcn=None):
    """Last independent currentness check after the durable barrier.

    This cannot make a database decision atomic with an external request. The
    bounded transport preserves the original deadline across that final race.
    """
    refuse(attempt(c, value, saved["platform"], saved["stage"]) == saved, "delivery_attempt_changed")
    if type(ghcn) is _OwnAttemptContext:
        refuse(ghcn.matches(value, saved), "delivery_attempt_changed")
    _, deadline = context(authority, c, value, resolve_principal, now, ghcn=ghcn)
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


def projection(authority, c, draft_id, resolve_principal, now, *, claim=None):
    return _projection(authority, c, draft_id, resolve_principal, now, claim=claim)


def _projection(authority, c, draft_id, resolve_principal, now, *, claim=None, _inspection=None):
    validate(c, authority.environment)
    rows = c.execute(f"SELECT intent_id FROM {SCHEMA}.intents WHERE draft_id=%s ORDER BY intent_id LIMIT 65", (draft_id,)).fetchall()
    refuse(len(rows) <= 64, "delivery_draft_capacity")
    result = []
    for (identity,) in rows:
        value = read(c, identity)
        current, reason = True, None
        try:
            # Passive GET resolution grants no dispatch checkpoint and performs
            # no selection replay. Historical outcomes remain visible on outage.
            if _inspection is None:
                _context(authority, c, value, resolve_principal, now, lambda state, version: claim)
            else:
                _qualified_context(authority, c, value, resolve_principal, now,
                    lambda state, version: claim, _inspection=_inspection)
        except CommandError as exc:
            current, reason = False, exc.code
            if _inspection is not None:
                _inspection.refused(authority, c, value, exc.code)
        result.append(dict(intent_id=identity, current=current, reason=reason, stages={
            platform:{stage:outcome(c, attempt(c, value, platform, stage)) for stage in stages}
            for platform,stages in STAGES.items()}))
    return dict(scope=SCOPE, publication_approved=False, intents=result)


def historical_content(authority, c, draft_id, intent_id, state):
    """One immutable approved content join; no current approval or renderer gate."""
    try:
        return _historical_content(authority, c, draft_id, intent_id, state)
    except (MediaJournalError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise p.ProjectionError("corrupt_delivery_content") from None


def _historical_content(authority, c, draft_id, intent_id, state):
    validate(c, authority.environment)
    refuse(type(intent_id) is str and str(UUID(intent_id)) == intent_id, "invalid_delivery_reference")
    current = [d for d in state["drafts"] if type(d) is dict and d.get("id") == draft_id]
    refuse(len(current) == 1, "draft_not_found")
    value = read(c, intent_id)
    refuse(value["draft_id"] == draft_id, "delivery_draft_mismatch")
    retained = authority._intent(c, value["command_id"])
    result = authority._result(c, value["command_id"])
    refuse(retained is not None and result is not None, "delivery_approval_not_retained")
    command, _ = retained
    refuse(command.action == "approve_media_revision" and len(command.targets) == 1
           and command.targets[0].draft_id == draft_id and result["status"] == "applied"
           and result["delivery"] == references(value)
           and result["publish_intent_id"] == intent_id
           and value["created_at"] == utc_text(utc_datetime(command.requested_at)), "delivery_approval_not_retained")
    _, approved_state = authority.projections._read(c, "command-core-v1", str(result["state_version"]))
    matches = [d for d in approved_state["drafts"] if type(d) is dict and d.get("id") == draft_id]
    refuse(len(matches) == 1, "delivery_approved_draft_missing")
    draft = matches[0]
    binding = value["approval_binding"]
    identity = editor._identity(draft)
    refuse(draft["approval_binding"] == binding and draft["publish_intent_id"] == intent_id
           and draft["event_id"] == value["event_id"] and draft["text"] == value["text"]
           and binding["scope"] == editor.SCOPE and binding["command_id"] == command.command_id
           and binding["publisher_subject"] == command.actor_subject
           and binding["publish_intent_id"] == intent_id
           and binding["resulting_state_version"] == result["state_version"]
           and all(binding[k] == v for k, v in identity.items() if k != "draft_id")
           and binding["media"] == draft["media_review_binding"]
           and binding["media"]["proposal_sha256"] == value["proposal_sha256"]
           and command.payload["expected_packet_sha256"] == binding["media"]["packet_sha256"]
           and command.payload["expected_review_sha256"] == binding["media"]["review_sha256"]
           and command.payload["expected_check_completion_sha256"] == binding["completion"]["completion_sha256"]
           and command.payload["expected_policy_sha256"] == binding["policy_sha256"]
           and command.payload["expected_renderer_profile_sha256"] == binding["renderer_profile_sha256"]
           and result["changed_ids"] == [draft_id] and result["identities"] == [identity], "delivery_approved_content_changed")
    _, predecessor = authority.projections._read(c, "command-core-v1", str(binding["consumed_state_version"]))
    targets = [d for d in predecessor["drafts"] if type(d) is dict and d.get("id") == draft_id]
    refuse(len(targets) == 1 and editor._identity(targets[0]) == command.targets[0].as_dict()
           and p._sha(p._canonical(predecessor)) == binding["consumed_state_sha256"]
           and binding["consumed_state_version"] + 1 == result["state_version"]
           and result["media_approval"] == dict(scope=editor.SCOPE, parked=True, publication_approved=False,
               check_set_id=binding["completion"]["check_set_id"], completion_sha256=binding["completion"]["completion_sha256"],
               consumed_state_version=binding["consumed_state_version"], resulting_state_version=result["state_version"]),
           "delivery_approved_predecessor_changed")
    package = editor.retained_package(authority, c, draft_id, value["proposal_sha256"])
    png, alt = package["assets"]["preview.png"], package["assets"]["alt.txt"]
    refuse(package["receipt"] == value["package"] and len(png) == value["png_byte_count"]
           and p._sha(png) == value["png_sha256"] and p._sha(alt) == value["alt_sha256"]
           and draft["media_attachment"] == package["capture"]["proposal"]["proposed_draft"]["media_attachment"], "delivery_media_changed")
    packet = package["capture"]["proposal"]["packet"]
    detail = dict(schema_version=1, draft_id=draft_id, target=editor._identity(current[0]),
        scope=SCOPE, publication_approved=False, intent_id=intent_id, command_id=command.command_id,
        approved_at=result["completed_at"], approved_target=identity, text=value["text"],
        proposal_sha256=value["proposal_sha256"], packet_sha256=binding["media"]["packet_sha256"],
        preparation_packet_sha256=packet["packet_sha256"], synthetic=packet["synthetic"],
        media=dict(mime_type="image/png", png_sha256=value["png_sha256"], byte_count=len(png),
            width=packet["media"]["width"], height=packet["media"]["height"],
            alt_text=alt.decode("utf-8"), alt_text_sha256=value["alt_sha256"]))
    description = value.get("platform_description", {})
    if value.get("schema_version") == 2 and description.get("schema_version") == 2:
        # Passive historical identity joins only. No current source availability,
        # profile qualification, fit gate or native work can hide earlier bytes.
        media_binding = binding["media"]
        review_command, _ = authority._intent(c, media_binding["command_id"])
        reviewed_description = media_commands_review(authority, c, review_command)["review"]["platform_description"]
        refuse(description == reviewed_description
            and description["description_sha256"] == media_binding["platform_description_sha256"]
            and description["proposal_sha256"] == value["proposal_sha256"]
            and description["packet_sha256"] == media_binding["packet_sha256"]
            and description["raw_alt_sha256"] == value["alt_sha256"]
            and description["semantic_alt_sha256"] == p._sha(alt[:-1])
            and description["graphic_spec_sha256"] == fingerprint(package["capture"]["inputs"]["graphic_spec"])
            and description["png"]["png_sha256"] == value["png_sha256"]
            and descriptions.text_identity(description["wire_text"]) == description["wire"],
            "platform_description_changed")
        detail.update(schema_version=2, platform_description=dict(
            description_sha256=description["description_sha256"], derivation=description["derivation"],
            wire_text=description["wire_text"], wire_sha256=description["wire"]["sha256"],
            raw_alt_sha256=value["alt_sha256"], status="reviewed_for_local_delivery"))
    refuse(len(p._canonical(detail)) <= 8 * 1024 * 1024, "delivery_content_too_large")
    return detail
