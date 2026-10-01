"""Exact local/preview graphic staging; no draft mutation or review acceptance.

The caller holds the command authority's pointer lock and transaction. Historical
readback reconstructs the proposal, not its currentness or scientific validity.
"""
from __future__ import annotations

from datetime import timedelta
import re

from src.commands import media_journal as media
from src.commands.schema import Principal, utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.media.attachment import build_media_attachment_proposal
from src.storage import postgres_projection as p

SCHEMA = "theheat_media"
MIGRATION = p.MIGRATION.with_name("009_media_staging.sql")
MAX_METADATA_BYTES = 8 * 1024 * 1024
_REQUEST = {"expected_revision", "expected_policy_sha256", "graphic_spec",
            "renderer_manifest", "proposal_at", "expected_proposal_sha256"}
_INPUTS = {"expected_revision", "editorial_policy", "graphic_spec", "renderer_manifest", "at"}
_CAPTURE = {"schema_version", "predecessor_state", "inputs", "proposal", "asset_sha256",
            "authority_version", "staged_at", "submitter"}
_PROVENANCE = {"subject", "role_at_staging", "authentication_context"}


def _require(condition, code):
    if not condition:
        raise media.MediaJournalError(code)


def _shape(value, keys):
    _require(isinstance(value, dict) and set(value) == keys, "invalid_media_staging_shape")


def _sha(value):
    _require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
             "invalid_media_staging_identity")


def _encoded(value):
    raw = p._canonical(value)
    _require(0 < len(raw) <= MAX_METADATA_BYTES, "media_staging_metadata_bound")
    return raw


def _time(value):
    canonical = utc_text(utc_datetime(value))
    _require(canonical == value, "noncanonical_media_staging_time")
    return canonical


def prepare(request, assets):
    """Detach and bound caller-owned inputs before a resolver or SQL can run."""
    _shape(request, _REQUEST)
    request = p._decode(_encoded(request))
    _sha(request["expected_policy_sha256"])
    _sha(request["expected_proposal_sha256"])
    _time(request["proposal_at"])
    _require(isinstance(assets, dict), "invalid_media_asset_set")
    assets = dict(assets)
    try:
        media._assets(assets, request["renderer_manifest"])
    except (KeyError, TypeError, AttributeError):
        raise media.MediaJournalError("invalid_media_staging_manifest") from None
    return request, assets


def validate(c, environment):
    _require(environment in ("local", "preview"), "media_staging_environment_mismatch")
    _require(c.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (SCHEMA,)).fetchone(),
             "media_staging_migration_required")
    row = c.execute(f"SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM {SCHEMA}.metadata WHERE singleton=1").fetchone()
    _require(row is not None and row[0] == 1 and row[1] == p._sha(MIGRATION.read_bytes()),
             "unsupported_media_staging_schema")
    _require(row[2] == p._catalog(c, SCHEMA), "changed_media_staging_schema")
    _require(row[3] == environment, "media_staging_environment_mismatch")
    roles = c.execute("SELECT owner_role,runtime_role FROM theheat_commands.metadata WHERE singleton=1").fetchone()
    _require(tuple(row[4:]) == roles, "media_staging_role_mismatch")


def install(c, environment):
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
                f"GRANT INSERT ON {SCHEMA}.artifacts,{SCHEMA}.packages TO {{}}"):
        c.execute(p._driver().sql.SQL(sql).format(role))
    c.execute(f"INSERT INTO {SCHEMA}.metadata VALUES(1,1,%s,%s,%s,%s,%s)",
              (p._sha(MIGRATION.read_bytes()), p._catalog(c, SCHEMA), environment, *roles))
    validate(c, environment)


def _raw(c, digest, limit):
    _sha(digest)
    size = c.execute(f"SELECT byte_count,octet_length(payload) FROM {SCHEMA}.artifacts WHERE sha=%s", (digest,)).fetchone()
    _require(size is not None and type(size[0]) is int and 0 < size[0] == size[1] <= limit,
             "invalid_media_staging_artifact_size")
    raw = c.execute(f"SELECT payload FROM {SCHEMA}.artifacts WHERE sha=%s", (digest,)).fetchone()[0]
    _require(type(raw) is bytes and len(raw) == size[0] and p._sha(raw) == digest,
             "changed_media_staging_bytes")
    return raw


def _artifact(c, raw):
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_METADATA_BYTES, "media_staging_artifact_bound")
    digest = p._sha(raw)
    c.execute(f"INSERT INTO {SCHEMA}.artifacts VALUES(%s,%s,%s) ON CONFLICT(sha) DO NOTHING", (digest, raw, len(raw)))
    _require(_raw(c, digest, MAX_METADATA_BYTES) == raw, "changed_media_staging_bytes")
    return digest


def _receipt(identity, capture_sha, capture):
    return dict(proposal_sha256=identity, package_sha256=capture_sha,
                staged_at=capture["staged_at"], authority_version_at_staging=capture["authority_version"],
                synthetic=capture["proposal"]["synthetic"], status="staged", currentness="not_evaluated",
                publication_approved=False, production_attachment_authorized=False)


def _read(c, identity):
    _sha(identity)
    row = c.execute(f"SELECT capture_sha256,staged_at FROM {SCHEMA}.packages WHERE proposal_sha256=%s", (identity,)).fetchone()
    _require(row is not None, "media_staging_package_not_found")
    raw = _raw(c, row[0], MAX_METADATA_BYTES)
    capture = p._decode(raw)
    _shape(capture, _CAPTURE)
    _require(_encoded(capture) == raw and type(capture["schema_version"]) is int
             and capture["schema_version"] == 1, "invalid_media_staging_capture")
    _require(type(capture["authority_version"]) is int and 0 <= capture["authority_version"] <= p.MAX_INTEGER,
             "invalid_media_staging_version")
    _require(_time(capture["staged_at"]) == row[1], "changed_media_staging_time")
    _shape(capture["submitter"], _PROVENANCE)
    submitter = capture["submitter"]
    actor = Principal(submitter["subject"], submitter["role_at_staging"], submitter["authentication_context"])
    _require(actor.role in ("editor", "publisher"), "invalid_media_staging_provenance")
    _shape(capture["inputs"], _INPUTS)
    _shape(capture["predecessor_state"], {"drafts", "publish_ledger", "posted_events"})
    drafts = capture["predecessor_state"]["drafts"]
    _require(isinstance(drafts, list) and len(drafts) == 1 and isinstance(drafts[0], dict),
             "invalid_media_staging_predecessor")
    _shape(capture["asset_sha256"], set(media._LIMITS))
    assets = {name: _raw(c, digest, media._LIMITS[name]) for name, digest in capture["asset_sha256"].items()}
    media._assets(assets, capture["inputs"]["renderer_manifest"])
    proposal_at = utc_datetime(_time(capture["inputs"]["at"]))
    age = utc_datetime(capture["staged_at"]) - proposal_at
    _require(-timedelta(minutes=5) <= age <= timedelta(hours=24), "invalid_media_staging_age")
    rebuilt = build_media_attachment_proposal(capture["predecessor_state"], drafts[0]["id"],
        **capture["inputs"], png_bytes=assets["preview.png"])
    _require(rebuilt["proposal_sha256"] == identity and _encoded(rebuilt) == _encoded(capture["proposal"]),
             "changed_media_staging_proposal")
    return dict(receipt=_receipt(identity, row[0], capture), capture=capture, assets=assets)


def read(c, identity, environment):
    validate(c, environment)
    try:
        return _read(c, identity)
    except (KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise media.MediaJournalError("invalid_media_staging_capture") from None


def stage(c, draft_id, request, *, assets, principal, state, authority_version, policy, now, environment):
    """Inputs are detached; the authority resolved current permission under lock."""
    validate(c, environment)
    _require(fingerprint(policy) == request["expected_policy_sha256"], "media_staging_policy_changed")
    at = _time(request["proposal_at"])
    staged_at = _time(utc_text(now))
    _require(-timedelta(minutes=5) <= now - utc_datetime(at) <= timedelta(hours=24), "media_staging_proposal_expired")
    inputs = dict(expected_revision=request["expected_revision"], editorial_policy=policy,
                  graphic_spec=request["graphic_spec"], renderer_manifest=request["renderer_manifest"], at=at)
    proposal = build_media_attachment_proposal(state, draft_id, **inputs, png_bytes=assets["preview.png"])
    identity = proposal["proposal_sha256"]
    _require(identity == request["expected_proposal_sha256"], "media_staging_proposal_changed")
    hashes = media._assets(assets, request["renderer_manifest"])
    draft = next(d for d in state["drafts"] if isinstance(d, dict) and d.get("id") == draft_id)
    event = draft["event_id"]
    ledger = state.get("publish_ledger", {})
    predecessor = dict(drafts=[draft], publish_ledger={event: ledger[event]} if event in ledger else {},
                       posted_events=[event] if event in state.get("posted_events", []) else [])
    capture = dict(schema_version=1, predecessor_state=predecessor, inputs=inputs, proposal=proposal,
                   asset_sha256=hashes, authority_version=authority_version, staged_at=staged_at,
                   submitter=dict(subject=principal.subject, role_at_staging=principal.role,
                                  authentication_context=principal.authentication_context))
    encoded = _encoded(capture)
    if c.execute(f"SELECT 1 FROM {SCHEMA}.packages WHERE proposal_sha256=%s", (identity,)).fetchone():
        retained = _read(c, identity)
        comparable = {**capture, **{key: retained["capture"][key] for key in ("authority_version", "staged_at", "submitter")}}
        _require(_encoded(comparable) == _encoded(retained["capture"]) and assets == retained["assets"],
                 "media_staging_identity_conflict")
        return retained["receipt"]
    for name, raw in assets.items():
        _require(_artifact(c, raw) == hashes[name], "changed_media_staging_bytes")
    capture_sha = _artifact(c, encoded)
    c.execute(f"INSERT INTO {SCHEMA}.packages VALUES(%s,%s,%s)", (identity, capture_sha, staged_at))
    return _read(c, identity)["receipt"]
