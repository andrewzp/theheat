"""Lossless import planning and resumable, idempotent import into local stores.

A plan reads exact snapshot bytes and states, before any mutation, what the
existing passive importer (``domain_journal.record_snapshot`` through the
local authority) would retain: exact source identity, schema support,
protected publication/review fields, duplicate/collision class against the
target store, missing sidecars, and every numeric token whose spelling a
re-serializer would change (P12-I3: integral floats such as ``500.0`` that a
JavaScript writer re-emits as ``500``, exponent/trailing-zero spellings,
negative zero, unsafe integers). Findings are preserved as original bytes,
never "cleaned".

Execution imports one item per durable identity (its ``import_id``), rechecks
each item's bytes against the plan immediately before writing, and derives
progress from the target store itself, so an interrupted run resumes without
duplicating history and a changed item or a different receipt under a used
identity is refused. External jobs and private sidecars are never invented:
the completion record says what remains unestablished. Production Gist is not
read or written here; targets are explicit local fixture stores.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from src.commands import domain_journal
from src.commands.schema import CommandError, canonical_json
from src.evaluation.file_boundary import FileBoundaryError, read_regular

SCHEMA = "theheat.import-plan/v2"
PROJECTED = frozenset({"drafts", "memory", "publish_ledger"})
PROTECTED_TOP = ("publish_ledger", "posted_events", "publication_control", "pending_confirmations")
PROTECTED_DRAFT = ("tweet_id", "posted_at", "publish_intent_id", "review_binding", "approval_binding", "media_attachment")
MAX_ITEMS = 200
MAX_FINDINGS = 2000
MAX_SIDECARS = 32
MAX_SIDECAR_BYTES = 16 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAFE = 9007199254740991


class _Number:
    __slots__ = ("token", "value")

    def __init__(self, token: str, value: Any):
        self.token, self.value = token, value


def _numbers(raw: bytes) -> list[dict]:
    """Every numeric token whose spelling a canonical writer would change."""
    def wrap_float(token):
        return _Number(token, float(token))

    def wrap_int(token):
        return _Number(token, int(token))

    tree = json.loads(raw.decode("utf-8"), parse_float=wrap_float, parse_int=wrap_int)
    findings: list[dict] = []

    def walk(value: Any, pointer: str) -> None:
        if len(findings) >= MAX_FINDINGS:
            return
        if isinstance(value, _Number):
            kind = None
            if isinstance(value.value, int) and abs(value.value) > _SAFE:
                kind = "unsafe_integer"
            elif isinstance(value.value, int) and value.token.startswith("-0"):
                kind = "negative_zero"
            elif isinstance(value.value, float):
                if value.value == 0 and value.token.lstrip().startswith("-"):
                    kind = "negative_zero"
                elif value.value.is_integer() and re.fullmatch(r"-?\d+\.0+", value.token):
                    kind = "integral_float"
                elif json.dumps(value.value) != value.token:
                    kind = "noncanonical_spelling"
            if kind:
                findings.append({"pointer": pointer, "token": value.token[:64], "class": kind,
                                 "disposition": "preserved_as_original_bytes"})
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{pointer}/{index}")

    walk(tree, "")
    return findings


def _protected(state: dict) -> dict:
    found = state.get("drafts")
    drafts: list = found if isinstance(found, list) else []
    per_field = {field: sum(1 for d in drafts if isinstance(d, dict) and d.get(field) not in (None, "", [], {}))
                 for field in PROTECTED_DRAFT}
    recorded = state.get("publish_ledger")
    ledger: dict = recorded if isinstance(recorded, dict) else {}
    phases: dict[str, int] = {}
    for row in ledger.values():
        phase = row.get("phase") if isinstance(row, dict) else None
        key = phase if isinstance(phase, str) and len(phase) <= 32 else "missing_or_invalid"
        phases[key] = phases.get(key, 0) + 1
    return {"top_level": [k for k in PROTECTED_TOP if k in state], "draft_fields": per_field,
            "ledger_phases": dict(sorted(phases.items())),
            "unknown_deliveries_preserved": phases.get("unknown", 0) + phases.get("submitted", 0) + phases.get("missing_or_invalid", 0)}


ORIGINS = ("import", "restore")


def _existing(authority: Any, import_id: str, origin: str = "import") -> dict | None:
    if origin not in ORIGINS:
        raise CommandError("invalid_import_origin", "Imports retain import or restore history only")
    with closing(authority._connect()) as connection:
        connection.execute("PRAGMA query_only=ON")
        authority._check_environment(connection)
        row = connection.execute("SELECT artifact_sha256,canonical_sha256 FROM domain_snapshots WHERE origin=? AND origin_id=?",
                                 (origin, import_id)).fetchone()
        return dict(row) if row else None


def _sidecar(name: str) -> dict:
    # Retain an absolute lexical path, never resolve a symlink as trusted input.
    path = str(Path(name).absolute())
    raw = read_regular(path, MAX_SIDECAR_BYTES)
    return {"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "byte_count": len(raw)}


def plan_item(raw: bytes, import_id: str, *, authority: Any = None, sidecars: tuple[str, ...] = (),
              origin: str = "import") -> dict:
    if not isinstance(import_id, str) or not _ID.fullmatch(import_id):
        raise CommandError("invalid_import_identity", "Supply a bounded stable import identity")
    sha = hashlib.sha256(raw).hexdigest()
    unsupported, missing = [], []
    try:
        state = domain_journal.parse_snapshot(raw)
        canonical_sha = hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()
    except (domain_journal.DomainJournalError, CommandError, ValueError):
        return {"import_id": import_id, "source_sha256": sha, "supported": False,
                "unsupported": ["snapshot_not_parseable"], "missing": [], "collision": "not_evaluated", "numeric_findings": []}
    if not isinstance(state.get("drafts"), list):
        unsupported.append("drafts_not_list")
    unprojected = sorted(set(state) - PROJECTED)
    retained_sidecars = []
    if not isinstance(sidecars, tuple) or len(sidecars) > MAX_SIDECARS:
        raise CommandError("invalid_import_sidecars", "Supply at most 32 required sidecars per item")
    for name in sidecars:
        try:
            if not isinstance(name, str):
                raise ValueError("invalid_sidecar")
            retained_sidecars.append(_sidecar(name))
        except (OSError, ValueError):
            missing.append({"sidecar": Path(str(name)).name[:120], "code": "source_sidecar_unavailable"})
    collision = "new"
    if authority is not None:
        prior = _existing(authority, import_id) if origin == "import" else _existing(authority, import_id, origin)
        if prior is not None:
            collision = "duplicate_replay" if prior["artifact_sha256"] == sha else "identity_collision_refused"
    return {"import_id": import_id, "source_sha256": sha, "canonical_sha256": canonical_sha,
            "supported": not unsupported and not missing and collision != "identity_collision_refused",
            "unsupported": unsupported, "missing": missing, "collision": collision,
            "sidecars": retained_sidecars,
            "unprojected_top_level_fields": unprojected, "protected": _protected(state),
            "numeric_findings": _numbers(raw),
            "publication_authorized": False, "review_currentness": "not_inherited"}


def plan(items: list[tuple[str, bytes]], *, authority: Any = None, sidecars: dict[str, tuple[str, ...]] | None = None,
         origin: str = "import") -> dict:
    """A complete pre-mutation statement; nothing is written.

    ``origin="restore"`` (``restore_plan``) checks identity collisions against
    restore history and binds that origin into the reviewed plan hash.
    """
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise CommandError("invalid_import_plan", "Supply 1 to 200 snapshot items")
    if origin not in ORIGINS:
        raise CommandError("invalid_import_origin", "Imports retain import or restore history only")
    ids = [item[0] for item in items]
    if len(set(ids)) != len(ids):
        raise CommandError("duplicate_import_identity", "Each item needs its own durable identity")
    rows = [plan_item(raw, import_id, authority=authority, sidecars=(sidecars or {}).get(import_id, ()), origin=origin)
            for import_id, raw in items]
    shas = [row["source_sha256"] for row in rows]
    duplicates = sorted({row["import_id"] for row in rows if shas.count(row["source_sha256"]) > 1})
    body = {"schema": SCHEMA, "items": rows, "duplicate_source_bytes": duplicates,
            "executable": all(row["supported"] for row in rows),
            "external_jobs": "not_imported_unestablished", "migration_claim": "partial_history_only",
            "mutation": "none"}
    if origin != "import":  # Older reviewed import plans keep their exact bytes.
        body["origin"] = origin
    body["plan_sha256"] = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
    return body


def execute(authority: Any, plan_value: dict, items: list[tuple[str, bytes]], *, now=None,
            between_items=None) -> dict:
    """Import each planned item once; resumable and idempotent per import_id."""
    body = {k: v for k, v in plan_value.items() if k != "plan_sha256"}
    if plan_value.get("schema") != SCHEMA or hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest() != plan_value.get("plan_sha256"):
        raise CommandError("import_plan_changed", "The plan was altered after review")
    if not plan_value["executable"]:
        raise CommandError("import_plan_not_executable", "The plan states unsupported, missing or colliding items")
    origin = plan_value.get("origin", "import")
    if origin not in ORIGINS:
        raise CommandError("invalid_import_origin", "Imports retain import or restore history only")
    planned = {row["import_id"]: row for row in plan_value["items"]}
    supplied = dict(items)
    if set(supplied) != set(planned):
        raise CommandError("import_items_changed", "Supplied items differ from the reviewed plan")
    outcomes = []
    for import_id in [row["import_id"] for row in plan_value["items"]]:
        raw = supplied[import_id]
        if hashlib.sha256(raw).hexdigest() != planned[import_id]["source_sha256"]:
            raise CommandError("import_source_changed", "An item's bytes changed after planning; nothing further is imported")
        try:
            required = planned[import_id]["sidecars"]
            if not isinstance(required, list) or len(required) > MAX_SIDECARS:
                raise ValueError("invalid_sidecars")
            for sidecar in required:
                if _sidecar(sidecar["path"]) != sidecar:
                    raise ValueError("changed_sidecar")
        except (OSError, FileBoundaryError, ValueError, KeyError, TypeError):
            raise CommandError("import_sidecar_changed", "A required sidecar is missing or changed; nothing further is imported") from None
        prior = _existing(authority, import_id) if origin == "import" else _existing(authority, import_id, origin)
        if prior is not None and prior["artifact_sha256"] != planned[import_id]["source_sha256"]:
            raise CommandError("import_receipt_collision", "This identity already holds different history")
        report = (authority.import_snapshot(raw, import_id=import_id, now=now) if origin == "import"
                  else authority.import_snapshot(raw, import_id=import_id, now=now, origin=origin))
        outcomes.append({"import_id": import_id, "status": "already_imported" if prior is not None else "imported",
                         "snapshot_id": report.get("snapshot_id")})
        if between_items is not None:
            between_items(import_id)
    return {"plan_sha256": plan_value["plan_sha256"], "items": outcomes,
            "complete_history_items": len(outcomes) == len(planned),
            "migration_complete": False, "external_jobs": "not_imported_unestablished",
            "publication_authorized": False}
