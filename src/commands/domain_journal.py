"""Immutable local evidence packets and draft revisions, not a production store.

All writes use the authority's already-open transaction. Imported assertions
stay unverified, and imports never alter the current authority projection.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import sqlite3
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.commands.schema import canonical_json, utc_datetime
from src.editorial.revisions import _evidence_payload, draft_identity

VERSION = 1
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_OCCURRENCES = 10000
_SHA = re.compile(r"[0-9a-f]{64}")
_TABLES = {
    "domain_schema": "singleton INTEGER PRIMARY KEY CHECK(singleton=1), version INTEGER NOT NULL, schema_sha256 TEXT NOT NULL, source_namespace TEXT NOT NULL",
    "domain_artifacts": "sha256 TEXT PRIMARY KEY, byte_count INTEGER NOT NULL, payload BLOB NOT NULL, CHECK(length(sha256)=64), CHECK(byte_count=length(payload))",
    "domain_entities": "entity_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind='draft'), legacy_id TEXT NOT NULL UNIQUE, legacy_event_id TEXT",
    "domain_revisions": "revision_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES domain_entities(entity_id), content_revision INTEGER NOT NULL, text_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), evidence_sha256 TEXT NOT NULL, evidence_artifact_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), identity_json TEXT NOT NULL, UNIQUE(entity_id,content_revision,text_sha256,evidence_sha256)",
    "domain_snapshots": "snapshot_id TEXT PRIMARY KEY, origin TEXT NOT NULL CHECK(origin IN ('bootstrap','command','import')), origin_id TEXT NOT NULL, artifact_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), canonical_sha256 TEXT NOT NULL, authority_version INTEGER, command_id TEXT REFERENCES command_intents(command_id), recorded_at TEXT NOT NULL, report_json TEXT NOT NULL, UNIQUE(origin,origin_id), UNIQUE(command_id)",
    "domain_occurrences": "occurrence_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES domain_snapshots(snapshot_id), locator TEXT NOT NULL, kind TEXT NOT NULL, artifact_sha256 TEXT NOT NULL REFERENCES domain_artifacts(sha256), entity_id TEXT REFERENCES domain_entities(entity_id), revision_id TEXT REFERENCES domain_revisions(revision_id), disposition TEXT NOT NULL, issues_json TEXT NOT NULL, UNIQUE(snapshot_id,locator)",
}
_KEYS = {
    "domain_schema": "singleton=NEW.singleton",
    "domain_artifacts": "sha256=NEW.sha256",
    "domain_entities": "entity_id=NEW.entity_id OR legacy_id=NEW.legacy_id",
    "domain_revisions": "revision_id=NEW.revision_id OR (entity_id=NEW.entity_id AND content_revision=NEW.content_revision AND text_sha256=NEW.text_sha256 AND evidence_sha256=NEW.evidence_sha256)",
    "domain_snapshots": "snapshot_id=NEW.snapshot_id OR (origin=NEW.origin AND origin_id=NEW.origin_id) OR command_id=NEW.command_id",
    "domain_occurrences": "occurrence_id=NEW.occurrence_id OR (snapshot_id=NEW.snapshot_id AND locator=NEW.locator)",
}


def _schema_objects() -> dict[str, str]:
    statements = {}
    for table, columns in _TABLES.items():
        statements[table] = f"CREATE TABLE {table} ({columns})"
        for action in ("UPDATE", "DELETE"):
            name = f"{table}_no_{action.lower()}"
            statements[name] = (
                f"CREATE TRIGGER {name} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable domain evidence'); END"
            )
        name = f"{table}_no_replace"
        statements[name] = (
            f"CREATE TRIGGER {name} BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE {_KEYS[table]}) BEGIN SELECT RAISE(ABORT, 'immutable domain evidence'); END"
        )
    statements["domain_occurrences_entity"] = (
        "CREATE INDEX domain_occurrences_entity ON domain_occurrences(entity_id,snapshot_id)"
    )
    return statements


SCHEMA_SHA256 = hashlib.sha256(canonical_json([VERSION, _schema_objects()]).encode()).hexdigest()


class DomainJournalError(RuntimeError):
    """Propagate outside reducer rejection handling so the whole write rolls back."""


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise DomainJournalError(f"Invalid {label}")
    value.encode("utf-8")
    return value


def _json_bytes(value: Any) -> bytes:
    data = canonical_json(value).encode("utf-8")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise DomainJournalError("Local artifact exceeds the explicit byte bound")
    return data


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DomainJournalError("Duplicate JSON keys make an import ambiguous")
        result[key] = value
    return result


def parse_snapshot(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_ARTIFACT_BYTES:
        raise DomainJournalError("Snapshot must be bytes within the local artifact bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object)
        if not isinstance(value, dict):
            raise DomainJournalError("Snapshot must contain one state object")
        _json_bytes(value)  # Finite JSON and valid Unicode, including escaped values.
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DomainJournalError("Snapshot is not unambiguous finite UTF-8 JSON") from exc


def validate_schema(connection: sqlite3.Connection, namespace: str | None = None) -> str:
    try:
        row = connection.execute("SELECT * FROM domain_schema WHERE singleton=1").fetchone()
    except sqlite3.DatabaseError as exc:
        raise DomainJournalError(
            "Local domain migration is required; initialize with the current authority state"
        ) from exc
    if row is None or row["version"] != VERSION or row["schema_sha256"] != SCHEMA_SHA256:
        raise DomainJournalError("Unsupported or changed local domain schema")
    for name, sql in _schema_objects().items():
        actual = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (name,)
        ).fetchone()
        if actual is None or actual["sql"] != sql:
            raise DomainJournalError("Local domain schema or immutability guards changed")
    _identifier(row["source_namespace"], "source namespace")
    if namespace is not None and namespace != row["source_namespace"]:
        raise DomainJournalError("Source namespace differs from this local authority")
    return row["source_namespace"]


def install(connection: sqlite3.Connection, namespace: str) -> bool:
    """Version-one local migration, inside the caller's transaction."""
    _identifier(namespace, "source namespace")
    if not connection.in_transaction:
        raise DomainJournalError("Domain migration requires the authority transaction")
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_schema'"
    ).fetchone():
        validate_schema(connection, namespace)
        return False
    for sql in _schema_objects().values():
        connection.execute(sql)
    connection.execute(
        "INSERT INTO domain_schema VALUES(1,?,?,?)", (VERSION, SCHEMA_SHA256, namespace)
    )
    return True


def _artifact(connection: sqlite3.Connection, data: bytes) -> str:
    if len(data) > MAX_ARTIFACT_BYTES:
        raise DomainJournalError("Local artifact exceeds the explicit byte bound")
    sha = _digest(data)
    previous = connection.execute(
        "SELECT byte_count,payload FROM domain_artifacts WHERE sha256=?", (sha,)
    ).fetchone()
    if previous is not None:
        if previous["byte_count"] != len(data) or previous["payload"] != data:
            raise DomainJournalError("Stored bytes do not match their artifact identity")
    else:
        connection.execute("INSERT INTO domain_artifacts VALUES(?,?,?)", (sha, len(data), data))
    return sha


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def record_snapshot(
    connection: sqlite3.Connection,
    state: dict,
    *,
    origin: str,
    origin_id: str,
    recorded_at: str,
    authority_version: int | None = None,
    raw: bytes | None = None,
    command_id: str | None = None,
) -> dict:
    """Retain packets and queryable current draft identities without certifying them."""
    if not connection.in_transaction:
        raise DomainJournalError("Domain projection requires the authority transaction")
    namespace = validate_schema(connection)
    _identifier(origin_id, "origin identity")
    utc_datetime(recorded_at)
    canonical = _json_bytes(state)
    raw = canonical if raw is None else raw
    if _json_bytes(parse_snapshot(raw)) != canonical:
        raise DomainJournalError("Original snapshot bytes differ from the supplied state")
    sha, canonical_sha = _digest(raw), _digest(canonical)
    previous = connection.execute(
        "SELECT * FROM domain_snapshots WHERE origin=? AND origin_id=?", (origin, origin_id)
    ).fetchone()
    if previous is not None:
        if (
            previous["artifact_sha256"],
            previous["canonical_sha256"],
            previous["authority_version"],
            previous["command_id"],
        ) != (sha, canonical_sha, authority_version, command_id):
            raise DomainJournalError(
                "An existing snapshot origin cannot acquire different evidence"
            )
        _artifact(connection, raw)  # Verify bytes even on an idempotent import.
        return json.loads(previous["report_json"])
    snapshot_id = _digest(_json_bytes([namespace, origin, origin_id, sha]))
    occurrences: list[tuple] = []
    dispositions: Counter = Counter()

    def retain(
        locator,
        kind,
        value,
        *,
        entity_id=None,
        revision_id=None,
        disposition="retained_unverified",
        issues=(),
    ):
        if len(occurrences) >= MAX_OCCURRENCES:
            raise DomainJournalError(
                "Snapshot exceeds the explicit occurrence bound; no partial import committed"
            )
        artifact = _artifact(connection, _json_bytes(value))
        oid = _digest(_json_bytes([snapshot_id, locator]))
        occurrences.append(
            (
                oid,
                snapshot_id,
                locator,
                kind,
                artifact,
                entity_id,
                revision_id,
                disposition,
                canonical_json(list(issues)),
            )
        )
        dispositions[disposition] += 1

    drafts = state.get("drafts", [])
    if not isinstance(drafts, list):
        retain("/drafts", "opaque_drafts", drafts, issues=["drafts_not_list"])
        drafts = []
    ids = Counter(
        row.get("id")
        for row in drafts
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].strip()
    )
    for index, draft in enumerate(drafts):
        location = f"/drafts/{index}"
        entity_id = revision_id = None
        issues = []
        if not isinstance(draft, dict):
            retain(location, "draft_packet", draft, issues=["draft_not_object"])
            continue
        legacy_id = draft.get("id")
        event_id = draft.get("event_id")
        event_id = event_id if isinstance(event_id, str) and event_id.strip() else None
        prior_alias = (
            connection.execute(
                "SELECT * FROM domain_entities WHERE legacy_id=?", (legacy_id,)
            ).fetchone()
            if isinstance(legacy_id, str)
            else None
        )
        if not isinstance(legacy_id, str) or not legacy_id.strip() or len(legacy_id) > 200:
            issues.append("missing_or_invalid_draft_alias")
        elif ids[legacy_id] != 1:
            issues.append("ambiguous_draft_alias")
        elif (
            prior_alias is not None
            and prior_alias["legacy_event_id"] is not None
            and event_id is not None
            and prior_alias["legacy_event_id"] != event_id
        ):
            issues.append("conflicting_legacy_event_alias")
        else:
            entity_id = str(uuid5(NAMESPACE_URL, canonical_json([namespace, "draft", legacy_id])))
            existing = connection.execute(
                "SELECT entity_id FROM domain_entities WHERE legacy_id=?", (legacy_id,)
            ).fetchone()
            if existing and existing["entity_id"] != entity_id:
                raise DomainJournalError("A draft alias points to a different entity")
            if not existing:
                connection.execute(
                    "INSERT INTO domain_entities VALUES(?, 'draft', ?, ?)",
                    (entity_id, legacy_id, event_id),
                )
            try:
                if not isinstance(draft.get("text"), str):
                    raise ValueError("Missing draft text")
                identity = draft_identity(draft)
                evidence_bytes = _json_bytes(_evidence_payload(draft))
                text_sha = _artifact(connection, draft["text"].encode("utf-8"))
                evidence_artifact = _artifact(connection, evidence_bytes)
                identity_json = canonical_json(identity)
                revision_id = _digest(_json_bytes([entity_id, identity]))
                fields = (
                    revision_id,
                    entity_id,
                    identity["content_revision"],
                    text_sha,
                    identity["evidence_sha256"],
                    evidence_artifact,
                    identity_json,
                )
                existing_revision = connection.execute(
                    "SELECT * FROM domain_revisions WHERE revision_id=?", (revision_id,)
                ).fetchone()
                if existing_revision is not None:
                    if tuple(existing_revision) != fields:
                        raise DomainJournalError(
                            "A revision identity points to different retained evidence"
                        )
                else:
                    connection.execute("INSERT INTO domain_revisions VALUES(?,?,?,?,?,?,?)", fields)
            except (ValueError, TypeError, OverflowError, RecursionError):
                revision_id = None
                issues.append("draft_identity_unavailable")
        disposition = (
            "receipt_id_present"
            if isinstance(draft.get("tweet_id"), str) and draft["tweet_id"].strip()
            else "posted_without_receipt"
            if draft.get("status") == "posted"
            else "publication_not_established"
        )
        retain(
            location,
            "draft_packet",
            draft,
            entity_id=entity_id,
            revision_id=revision_id,
            disposition=disposition,
            issues=issues,
        )
        # Historical branches remain exact packets. Missing context is not filled
        # from today's draft to invent an earlier evidence identity or review.
        for field in ("revision_history", "revision_conflicts", "candidate_snapshots"):
            if field in draft:
                retain(
                    f"{location}/{field}",
                    "retained_revision_branches",
                    draft[field],
                    entity_id=entity_id,
                    issues=["historical_identity_not_reconstructed"],
                )
        for field in ("review_binding", "approval_binding"):
            if field in draft:
                retain(
                    f"{location}/{field}",
                    "retained_decision",
                    draft[field],
                    entity_id=entity_id,
                    revision_id=revision_id,
                    issues=["import_does_not_authorize_publication"],
                )
        review = draft.get("review_context")
        two_bot = review.get("two_bot") if isinstance(review, dict) else None
        if isinstance(two_bot, dict):
            for field in ("bundle", "fact_check", "critic", "candidate_drafts"):
                if field in two_bot:
                    retain(
                        f"{location}/review_context/two_bot/{field}",
                        "retained_bundle" if field == "bundle" else "retained_check_or_candidate",
                        two_bot[field],
                        entity_id=entity_id,
                        revision_id=revision_id,
                        issues=["scientific_and_execution_status_unverified"],
                    )
    memory = state.get("memory")
    shipped = memory.get("shipped_tweets") if isinstance(memory, dict) else None
    if isinstance(shipped, list):
        for index, item in enumerate(shipped):
            retain(
                f"/memory/shipped_tweets/{index}",
                "generation_memory",
                item,
                disposition="publication_unverified_memory",
            )
    ledger = state.get("publish_ledger")
    if isinstance(ledger, dict):
        for key, value in ledger.items():
            retain(
                f"/publish_ledger/{_pointer(key)}",
                "publication_assertion",
                value,
                issues=["retained_phase_is_not_a_reconciled_delivery"],
            )
    report = {
        "snapshot_id": snapshot_id,
        "artifact_sha256": sha,
        "canonical_sha256": canonical_sha,
        "occurrences": len(occurrences),
        "packet_dispositions": dict(dispositions),
        "source_namespace": namespace,
        "schema_version": VERSION,
        "qualification": "retained_unverified",
        "publication_authorized": False,
        "unprojected_top_level_fields": sorted(set(state) - {"drafts", "memory", "publish_ledger"}),
        "limitations": [
            "Packet counts are not unique historical tweet or receipt counts.",
            "Exact original snapshot retains every field; only selected draft, memory and publication packets are indexed.",
            "Historical branches, source runs, observations, baselines, check completion and platform/account receipts are not normalized or certified.",
            "Draft continuity relies on the declared source namespace and legacy alias; contradictory retained event IDs are quarantined, absent event IDs do not prove continuity.",
        ],
    }
    _artifact(connection, raw)
    connection.execute(
        "INSERT INTO domain_snapshots VALUES(?,?,?,?,?,?,?,?,?)",
        (
            snapshot_id,
            origin,
            origin_id,
            sha,
            canonical_sha,
            authority_version,
            command_id,
            recorded_at,
            canonical_json(report),
        ),
    )
    connection.executemany("INSERT INTO domain_occurrences VALUES(?,?,?,?,?,?,?,?,?)", occurrences)
    return report


def read_artifact(connection: sqlite3.Connection, sha: str) -> bytes:
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise DomainJournalError("Invalid artifact identity")
    row = connection.execute(
        "SELECT byte_count,payload FROM domain_artifacts WHERE sha256=?", (sha,)
    ).fetchone()
    if row is None or row["byte_count"] != len(row["payload"]) or _digest(row["payload"]) != sha:
        raise DomainJournalError("Artifact is unavailable or no longer matches its identity")
    return row["payload"]


def inspect(connection: sqlite3.Connection, *, verify: bool = False) -> dict:
    namespace = validate_schema(connection)
    if verify:
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise DomainJournalError("Domain relationships failed integrity validation")
        for row in connection.execute("SELECT sha256 FROM domain_artifacts"):
            read_artifact(connection, row["sha256"])
    return {
        "schema_version": VERSION,
        "source_namespace": namespace,
        "counts": {
            table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in _TABLES
        },
        "artifact_bytes_verified": verify,
        "production_authority": False,
    }
