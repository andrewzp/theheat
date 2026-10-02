"""Atomic reviewed media revisions in the local/preview command authority.

The caller holds the authority lock/transaction. Staging, historical review and
current permission are distinct. Nothing here grants publication permission.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta

from src.commands import postgres_media as media
from src.commands.reducer import Reduction, _identity, _target_drafts
from src.commands.schema import Command, CommandError, Principal, authorize, utc_datetime
from src.editorial.revisions import draft_identity, fingerprint
from src.media.attachment import build_media_attachment_proposal, build_media_removal_proposal
from src.media.joint_review import MAX_REVIEW_BYTES, record_joint_media_review
from src.storage import postgres_projection as p

SCHEMA = "theheat_media_commands"
MIGRATION = p.MIGRATION.with_name("010_media_commands.sql")


def validate(c, environment):
    media.validate(c, environment)
    p._require(c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone(),
               "media_command_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    p._require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()), "unsupported_media_command_schema")
    p._require(row[2] == p._catalog(c, SCHEMA), "changed_media_command_schema")
    p._require(row[3] == environment, "media_command_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    p._require(tuple(row[4:]) == roles, "media_command_role_mismatch")


def install(c, environment):
    media.validate(c, environment)
    if c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone():
        validate(c, environment)
        return
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    c.execute(MIGRATION.read_text())
    role = p._driver().sql.Identifier(roles[1])
    for target in (f"SCHEMA {SCHEMA}", f"ALL TABLES IN SCHEMA {SCHEMA}", f"ALL FUNCTIONS IN SCHEMA {SCHEMA}"):
        c.execute(f"REVOKE ALL ON {target} FROM PUBLIC")
        c.execute(p._driver().sql.SQL(f"REVOKE ALL ON {target} FROM {{}}").format(role))
    for sql in (f"GRANT USAGE ON SCHEMA {SCHEMA} TO {{}}",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA {SCHEMA} TO {{}}",
                f"GRANT INSERT ON {SCHEMA}.reviews TO {{}}"):
        c.execute(p._driver().sql.SQL(sql).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _package(c, identity, environment):
    # Once the row exists, malformed retained data is infrastructure uncertainty,
    # never a terminal factual rejection. Missing references are deterministic.
    if not c.execute("SELECT 1 FROM theheat_media.packages WHERE proposal_sha256=%s", (identity,)).fetchone():
        raise CommandError("media_package_not_found", "The referenced graphic package is not staged")
    try:
        return media.read(c, identity, environment)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise p.ProjectionError("corrupt_staged_media_package") from None


@dataclass(frozen=True)
class MediaTransition:
    reduction: Reduction
    references: dict
    review: dict | None = None


def prepare(c, state, command, actor, *, now, editorial_policy, environment):
    """Read verified storage separately from deterministic command validation."""
    validate(c, environment)
    if actor.subject != command.actor_subject:
        raise CommandError("forbidden", "The current identity differs from the accepted command")
    authorize(actor, command.action)
    if now >= utc_datetime(command.expires_at):
        raise CommandError("command_expired", "The media command expired")
    if utc_datetime(command.requested_at) > now + timedelta(minutes=5):
        raise CommandError("invalid_time", "The media command is too far in the future")
    if fingerprint(editorial_policy) != command.payload["expected_policy_sha256"]:
        raise CommandError("editorial_policy_changed", "Editorial policy changed since media review")
    package = None
    if command.action == "attach_media_revision":
        package = _package(c, command.payload["proposal_sha256"], environment)
    try:
        return _prepare(state, command, actor, now, editorial_policy, package)
    except CommandError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise CommandError("invalid_media_revision", "The current media revision cannot be validated") from None


def _prepare(state, command, actor, now, policy, package):
    _target_drafts(state, command)
    target = command.targets[0]
    payload = command.payload
    review = None
    if command.action == "attach_media_revision":
        capture, assets = package["capture"], package["assets"]
        inputs = capture["inputs"]
        if p._canonical(capture["proposal"]["predecessor"]) != p._canonical(target.as_dict()):
            raise CommandError("media_proposal_changed", "The staged package belongs to a different predecessor")
        age = now - utc_datetime(inputs["at"])
        if not -timedelta(minutes=5) <= age <= timedelta(hours=24):
            raise CommandError("media_proposal_expired", "The staged graphic proposal is outside its review window")
        if p._canonical(inputs["editorial_policy"]) != p._canonical(policy):
            raise CommandError("editorial_policy_changed", "The staged package used a different editorial policy")
        proposal = build_media_attachment_proposal(state, target.draft_id,
            expected_revision=target.as_dict(), editorial_policy=policy,
            graphic_spec=inputs["graphic_spec"], renderer_manifest=inputs["renderer_manifest"],
            png_bytes=assets["preview.png"], at=inputs["at"])
        if p._canonical(proposal) != p._canonical(capture["proposal"]):
            raise CommandError("media_proposal_changed", "The current graphic proposal differs from the staged package")
        if proposal["changed"] is not True:
            raise CommandError("media_already_attached", "This exact graphic is already attached")
        review = record_joint_media_review(proposal["proposed_draft"], payload=payload["review"],
            principal=actor, reviewed_at=command.requested_at,
            expected_packet_sha256=payload["expected_packet_sha256"],
            expected_draft_identity=draft_identity(proposal["proposed_draft"]), editorial_policy=policy,
            graphic_spec=inputs["graphic_spec"], renderer_manifest=inputs["renderer_manifest"],
            png_bytes=assets["preview.png"])
        if review["decision"] != "accept":
            raise CommandError("media_acceptance_required", "The exact graphic requires joint acceptance")
    else:
        proposal = build_media_removal_proposal(state, target.draft_id,
            expected_revision=target.as_dict(), at=command.requested_at)
        if proposal["proposal_sha256"] != payload["expected_proposal_sha256"]:
            raise CommandError("media_proposal_changed", "The removal proposal changed")
    updated = deepcopy(state)
    proposed = deepcopy(proposal["proposed_draft"])
    references = dict(proposal_sha256=proposal["proposal_sha256"],
        publication_approved=False, production_attachment_authorized=False)
    if review is not None:
        binding = dict(schema_version=1, proposal_sha256=proposal["proposal_sha256"],
            packet_sha256=review["packet"]["packet_sha256"], review_sha256=review["review_sha256"],
            command_id=command.command_id)
        proposed["media_review_binding"] = binding
        references.update(packet_sha256=binding["packet_sha256"], review_sha256=binding["review_sha256"],
                          synthetic=review["synthetic"])
    updated["drafts"] = [proposed if isinstance(d, dict) and d.get("id") == target.draft_id else d
                         for d in updated["drafts"]]
    reduction = Reduction(updated, (target.draft_id,) if proposal["changed"] else (), (_identity(proposed),))
    return MediaTransition(reduction, references, review)


def retain(c, command, transition):
    if transition.review is None:
        return
    raw = p._canonical(transition.review)
    p._require(0 < len(raw) <= MAX_REVIEW_BYTES, "media_review_byte_bound")
    artifact_sha = media._artifact(c, raw)
    c.execute(f"INSERT INTO {SCHEMA}.reviews VALUES(%s,%s,%s,%s,%s)",
        (command.command_id, transition.references["proposal_sha256"],
         transition.review["review_sha256"], artifact_sha, command.requested_at))


def read(c, command: Command, result: dict, environment):
    """Reconstruct historical acceptance from separate intent, stage and snapshots.

    Historical reviewer role is retained provenance, not current permission.
    This function does not call the authority's result reader recursively.
    """
    validate(c, environment)
    try:
        return _read(c, command, result, environment)
    except (CommandError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise p.ProjectionError("corrupt_media_command_review") from None


def _read(c, command, result, environment):
    row = c.execute(f"SELECT proposal_sha256,review_sha256,artifact_sha256,reviewed_at FROM {SCHEMA}.reviews WHERE command_id=%s", (command.command_id,)).fetchone()
    p._require(row is not None and command.action == "attach_media_revision"
               and result["status"] == "applied", "media_command_review_not_found")
    raw = media._raw(c, row[2], MAX_REVIEW_BYTES)
    record = p._decode(raw)
    p._require(p._canonical(record) == raw and row[0] == command.payload["proposal_sha256"]
               and row[1] == record["review_sha256"] and row[3] == command.requested_at,
               "changed_media_command_reference")
    package = _package(c, row[0], environment)
    reviewer = record["reviewer"]
    actor = Principal(reviewer["subject"], reviewer["role_at_review"], reviewer["authentication_context"])
    version = result["state_version"]
    p._require(type(version) is int and version > 0, "invalid_media_command_version")
    _, before = p.PostgresProjectionRepository._read(c, "command-core-v1", str(version - 1))
    _, after = p.PostgresProjectionRepository._read(c, "command-core-v1", str(version))
    transition = prepare(c, before, command, actor, now=utc_datetime(result["completed_at"]),
        editorial_policy=package["capture"]["inputs"]["editorial_policy"], environment=environment)
    p._require(p._canonical(transition.review) == raw
               and p._canonical(transition.reduction.state) == p._canonical(after)
               and p._canonical(transition.references) == p._canonical(result["media"])
               and list(transition.reduction.changed_ids) == result["changed_ids"]
               and p._canonical(list(transition.reduction.identities)) == p._canonical(result["identities"])
               and result["publish_intent_id"] is None, "changed_media_command_transition")
    return dict(command_id=command.command_id, review=record, artifact_sha256=row[2],
        proposal_sha256=row[0], currentness="not_evaluated", status="historical",
        publication_approved=False, production_attachment_authorized=False)
