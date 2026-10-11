"""Bounded passive archives in the existing local projection repository.

There is no production caller or import endpoint. Original bytes are opaque;
neither a retained assertion nor completion of this archive grants authority.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import re

from src.storage import postgres_projection as p

MAX_IMPORT_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 50_000
NAMESPACES = frozenset({"history.artifacts.v1", "history.rows.v1", "history.sources.v1",
                        "history.corpus.v1", "history.inventory.v1"})
COMPLETIONS = "history.imports.v1"
_SHA = re.compile(r"[a-f0-9]{64}")


def _require(value, code):
    if not value:
        raise p.ProjectionError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def raw_envelope(raw: bytes) -> dict:
    _require(type(raw) is bytes and len(raw) <= p.MAX_BYTES, "invalid_history_bytes")
    value = {"schema_version": 1, "kind": "raw_artifact", "raw_sha256": _sha(raw),
             "byte_count": len(raw), "encoding": "base64",
             "payload_base64": base64.b64encode(raw).decode("ascii")}
    p._snapshot(value)  # Includes base64 overhead; never enlarge repository limits.
    return value


def original_bytes(value: dict) -> bytes:
    _require(type(value) is dict and set(value) == {"schema_version", "kind", "raw_sha256",
             "byte_count", "encoding", "payload_base64"}, "invalid_history_envelope")
    _require(type(value["schema_version"]) is int and value["schema_version"] == 1
             and value["kind"] == "raw_artifact" and value["encoding"] == "base64"
             and type(value["byte_count"]) is int and 0 <= value["byte_count"] <= p.MAX_BYTES
             and type(value["raw_sha256"]) is str and _SHA.fullmatch(value["raw_sha256"])
             and type(value["payload_base64"]) is str
             and len(value["payload_base64"]) <= p.MAX_BYTES, "invalid_history_envelope")
    try:
        raw = base64.b64decode(value["payload_base64"], validate=True)
    except (ValueError, binascii.Error):
        raise p.ProjectionError("invalid_history_encoding") from None
    _require(len(raw) == value["byte_count"] and _sha(raw) == value["raw_sha256"]
             and base64.b64encode(raw).decode("ascii") == value["payload_base64"],
             "history_artifact_mismatch")
    return raw


@dataclass(frozen=True)
class ArchivePlan:
    import_id: str
    records: tuple[tuple[str, str, bytes], ...]
    completion: bytes


def prepare(import_id: str, records: list[tuple[str, str, dict]]) -> ArchivePlan:
    """Detach the full bounded archive; completion binds every immutable record."""
    p._identifier(import_id)
    _require(type(records) is list and 1 <= len(records) <= MAX_RECORDS,
             "history_record_bound")
    seen, prepared, descriptors = set(), [], []
    total = 0
    for namespace, ident, value in records:
        _require(namespace in NAMESPACES, "history_namespace_refused")
        p._identifier(ident)
        _require((namespace, ident) not in seen, "duplicate_history_record")
        seen.add((namespace, ident))
        encoded, _ = p._snapshot(value)
        if namespace == "history.artifacts.v1":
            raw = original_bytes(value)
            _require(ident == _sha(raw), "history_artifact_identity_mismatch")
        total += len(encoded)
        _require(total <= MAX_IMPORT_BYTES, "history_import_byte_bound")
        prepared.append((namespace, ident, encoded))
        descriptors.append({"namespace": namespace, "snapshot_id": ident,
                            "canonical_sha256": _sha(encoded)})
    prepared.sort()
    descriptors.sort(key=lambda row: (row["namespace"], row["snapshot_id"]))
    completion = p._snapshot({"schema_version": 1, "kind": "passive_history_import",
        "import_id": import_id, "publication_authorized": False,
        "historical_jobs_runnable": False, "external_job_coverage": "unestablished",
        "records": descriptors, "record_count": len(descriptors), "encoded_bytes": total})[0]
    _require(total + len(completion) <= MAX_IMPORT_BYTES, "history_import_byte_bound")
    return ArchivePlan(import_id, tuple(prepared), completion)


def _validated(plan: ArchivePlan) -> ArchivePlan:
    _require(type(plan) is ArchivePlan and type(plan.records) is tuple,
             "invalid_history_plan")
    actual = prepare(plan.import_id, [(ns, ident, p._decode(raw))
                                     for ns, ident, raw in plan.records])
    _require(actual == plan, "history_plan_mismatch")
    return actual


def _local(repository):
    _require(type(repository) is p.PostgresProjectionRepository
             and getattr(repository, "_hosted_config", None) is None
             and repository.environment == "local", "local_history_repository_required")


def record_import(repository: p.PostgresProjectionRepository, plan: ArchivePlan) -> p.ProjectionReceipt:
    """Commit all evidence plus completion atomically, never authority state."""
    _local(repository)
    plan = _validated(plan)
    with repository._connection(writing=True) as connection:
        repository._validate(connection)
        for namespace, ident, raw in plan.records:
            encoded, fields = p._snapshot(p._decode(raw))
            repository._record(connection, namespace, ident, encoded, fields)
        encoded, fields = p._snapshot(p._decode(plan.completion))
        receipt = repository._record(connection, COMPLETIONS, plan.import_id, encoded, fields)
    return receipt


def verify_import(repository: p.PostgresProjectionRepository, plan: ArchivePlan) -> p.ProjectionReceipt:
    """Read-only original-ID reconciliation includes every dependent artifact."""
    _local(repository)
    plan = _validated(plan)
    with repository._connection() as connection:
        repository._validate(connection)
        receipt, value = repository._read(connection, COMPLETIONS, plan.import_id)
        _require(p._snapshot(value)[0] == plan.completion, "history_completion_mismatch")
        for namespace, ident, raw in plan.records:
            _, value = repository._read(connection, namespace, ident)
            _require(p._snapshot(value)[0] == raw, "history_record_mismatch")
    return receipt
