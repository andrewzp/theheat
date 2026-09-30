"""Atomic local graphic/review retention, with no draft mutation or activation.

Assets are opaque retained evidence, never executed. Reads reconstruct historical
binding only; effective acceptance still requires independently current inputs.
All writes use the local authority's existing transaction and immutable blobs.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import json
import re
import sqlite3

from src.commands import domain_journal as domain
from src.commands.schema import Principal, canonical_json, utc_datetime
from src.editorial.revisions import fingerprint
from src.media.joint_review import record_joint_media_review
from src.media.review_packet import MAX_JSON_BYTES, MAX_PNG_BYTES

MAX_TOTAL_ASSET_BYTES = 26 * 1024 * 1024
_LIMITS = {
    "input.json": MAX_JSON_BYTES, "alt.txt": MAX_JSON_BYTES,
    "preview.svg": MAX_PNG_BYTES, "preview.pdf": MAX_PNG_BYTES, "preview.png": MAX_PNG_BYTES,
}
_INPUTS = {
    "expected_draft_identity", "editorial_policy", "graphic_spec", "renderer_manifest",
}
_REQUEST = _INPUTS | {"payload", "reviewed_at", "expected_packet_sha256"}
_TABLES = {
    "media_review_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_sha256 TEXT NOT NULL",
    "retained_media_reviews": "review_sha256 TEXT PRIMARY KEY, packet_sha256 TEXT NOT NULL, capture_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), record_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), recorded_at TEXT NOT NULL",
}
_SHA = re.compile(r"[a-f0-9]{64}")


class MediaJournalError(RuntimeError):
    """Bounded error codes; storage failures escape to transaction rollback."""


def _require(condition, code):
    if not condition:
        raise MediaJournalError(code)


def _objects():
    result = {}
    for table, columns in _TABLES.items():
        result[table] = f"CREATE TABLE {table} ({columns})"
        for action in ("UPDATE", "DELETE"):
            name = f"{table}_no_{action.lower()}"
            result[name] = (
                f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable media review'); END"
            )
        key = "singleton" if table == "media_review_schema" else "review_sha256"
        name = f"{table}_no_replace"
        result[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}=NEW.{key}) BEGIN SELECT RAISE(ABORT, 'immutable media review'); END"
        )
    return result


SCHEMA_SHA256 = fingerprint(_objects())


def validate(connection):
    domain.validate_schema(connection)
    try:
        row = connection.execute("SELECT * FROM media_review_schema WHERE singleton=1").fetchone()
        _require(row is not None and row["schema_sha256"] == SCHEMA_SHA256, "changed_media_schema")
        for name, sql in _objects().items():
            row = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            _require(row is not None and row[0] == sql, "changed_media_schema")
        actual = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE tbl_name IN ('media_review_schema','retained_media_reviews') AND name NOT LIKE 'sqlite_%'"
        )}
        _require(actual == set(_objects()), "changed_media_schema")
    except sqlite3.DatabaseError:
        raise MediaJournalError("media_migration_required") from None


def install(connection):
    _require(connection.in_transaction, "media_transaction_required")
    domain.validate_schema(connection)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='media_review_schema'").fetchone():
        validate(connection)
        return
    for sql in _objects().values():
        connection.execute(sql)
    connection.execute("INSERT INTO media_review_schema VALUES(1,?)", (SCHEMA_SHA256,))


def _copy(value):
    fingerprint(value)  # No coercion of non-string keys, nonfinite or non-JSON data.
    return json.loads(domain._json_bytes(value))


def _assets(assets, manifest):
    _require(isinstance(assets, dict) and set(assets) == set(_LIMITS), "invalid_media_asset_set")
    _require(
        all(type(data) is bytes and 0 < len(data) <= _LIMITS[name] for name, data in assets.items())
        and sum(map(len, assets.values())) <= MAX_TOTAL_ASSET_BYTES,
        "media_asset_size_limit",
    )
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in assets.items()}
    _require(hashes == manifest["files"], "media_asset_manifest_mismatch")
    return hashes


def _blob(connection, sha, limit):
    _require(isinstance(sha, str) and _SHA.fullmatch(sha) is not None, "invalid_media_artifact")
    # Check size in SQLite before fetching potentially altered blob payloads.
    row = connection.execute(
        "SELECT byte_count,length(payload) FROM domain_artifacts WHERE sha256=?", (sha,)
    ).fetchone()
    _require(
        row is not None and type(row[0]) is int and row[0] == row[1] and 0 < row[0] <= limit,
        "invalid_media_artifact_size",
    )
    return domain.read_artifact(connection, sha)


def read(connection, review_sha256):
    """Verified historical receipt plus exact private assets; never current approval."""
    validate(connection)
    _require(
        isinstance(review_sha256, str) and _SHA.fullmatch(review_sha256) is not None,
        "invalid_media_review_identity",
    )
    row = connection.execute(
        "SELECT * FROM retained_media_reviews WHERE review_sha256=?", (review_sha256,)
    ).fetchone()
    _require(row is not None, "media_review_not_found")
    capture = domain.parse_snapshot(_blob(connection, row["capture_sha256"], domain.MAX_ARTIFACT_BYTES))
    record = domain.parse_snapshot(_blob(connection, row["record_sha256"], domain.MAX_ARTIFACT_BYTES))
    _require(
        set(capture) == {"schema_version", "draft", "inputs", "asset_sha256", "authority_version"}
        and type(capture["schema_version"]) is int and capture["schema_version"] == 1
        and type(capture["authority_version"]) is int and capture["authority_version"] >= 0
        and isinstance(capture["inputs"], dict) and set(capture["inputs"]) == _INPUTS
        and isinstance(capture["asset_sha256"], dict) and set(capture["asset_sha256"]) == set(_LIMITS),
        "invalid_media_capture",
    )
    assets = {name: _blob(connection, sha, _LIMITS[name]) for name, sha in capture["asset_sha256"].items()}
    _assets(assets, capture["inputs"]["renderer_manifest"])
    provenance = record["reviewer"]
    historical_principal = Principal(
        provenance["subject"], provenance["role_at_review"], provenance["authentication_context"],
    )
    rebuilt = record_joint_media_review(
        capture["draft"], **capture["inputs"], png_bytes=assets["preview.png"],
        payload={key: record[key] for key in ("decision", "confirmations", "reason")},
        principal=historical_principal, reviewed_at=record["reviewed_at"],
        expected_packet_sha256=row["packet_sha256"],
    )
    _require(
        canonical_json(rebuilt) == canonical_json(record) and record["review_sha256"] == review_sha256,
        "media_review_record_mismatch",
    )
    _require(
        utc_datetime(record["reviewed_at"]) <= utc_datetime(row["recorded_at"]) + timedelta(minutes=5),
        "invalid_media_review_time",
    )
    receipt = {
        "review_sha256": review_sha256, "packet_sha256": row["packet_sha256"],
        "recorded_at": row["recorded_at"], "authority_version_at_retention": capture["authority_version"],
        "synthetic": record["synthetic"], "currentness": "not_evaluated",
        "publication_approved": False, "production_attachment_authorized": False,
    }
    return {"receipt": receipt, "record": record, "capture": capture, "assets": assets}


def retain(connection, draft_id, request, *, principal, assets, recorded_at):
    """The authority has resolved current role and begun its write transaction."""
    _require(connection.in_transaction, "media_transaction_required")
    validate(connection)
    _require(isinstance(request, dict) and set(request) == _REQUEST, "invalid_media_request")
    _require(
        isinstance(draft_id, str) and bool(draft_id.strip()) and len(draft_id) <= 200,
        "invalid_media_draft_identity",
    )
    request = _copy(request)
    _require(
        utc_datetime(request["reviewed_at"]) <= utc_datetime(recorded_at) + timedelta(minutes=5),
        "media_review_time_in_future",
    )
    snapshot = connection.execute("SELECT version,state_json FROM authority_state WHERE singleton=1").fetchone()
    _require(snapshot is not None, "media_authority_state_unavailable")
    state = json.loads(snapshot["state_json"])
    drafts = state.get("drafts")
    _require(isinstance(drafts, list), "media_drafts_unavailable")
    matches = [d for d in drafts if isinstance(d, dict) and d.get("id") == draft_id]
    _require(len(matches) == 1, "media_draft_missing_or_ambiguous")
    draft = matches[0]
    # Immutable byte values are copied before validation; a caller cannot swap
    # entries in its own mapping after the packet has been checked.
    _require(isinstance(assets, dict), "invalid_media_asset_set")
    assets = dict(assets)
    hashes = _assets(assets, request["renderer_manifest"])
    current_inputs = {key: request[key] for key in _INPUTS}
    record = record_joint_media_review(
        draft, **current_inputs, png_bytes=assets["preview.png"],
        payload=request["payload"], principal=principal, reviewed_at=request["reviewed_at"],
        expected_packet_sha256=request["expected_packet_sha256"],
    )
    capture = {
        "schema_version": 1, "draft": draft, "inputs": current_inputs,
        "asset_sha256": hashes, "authority_version": snapshot["version"],
    }
    existing = connection.execute(
        "SELECT 1 FROM retained_media_reviews WHERE review_sha256=?", (record["review_sha256"],)
    ).fetchone()
    if existing:
        retained = read(connection, record["review_sha256"])
        # An unrelated draft's command may have advanced the global counter.
        # Keep the original retention version and receipt on an identical retry.
        comparable = {**capture, "authority_version": retained["capture"]["authority_version"]}
        _require(
            canonical_json(comparable) == canonical_json(retained["capture"])
            and canonical_json(record) == canonical_json(retained["record"])
            and assets == retained["assets"],
            "media_review_identity_conflict",
        )
        return retained["receipt"]
    for name, data in assets.items():
        _require(domain._artifact(connection, data) == hashes[name], "media_artifact_mismatch")
    capture_sha = domain._artifact(connection, domain._json_bytes(capture))
    record_sha = domain._artifact(connection, domain._json_bytes(record))
    connection.execute(
        "INSERT INTO retained_media_reviews VALUES(?,?,?,?,?)",
        (record["review_sha256"], record["packet"]["packet_sha256"], capture_sha, record_sha, recorded_at),
    )
    return read(connection, record["review_sha256"])["receipt"]
