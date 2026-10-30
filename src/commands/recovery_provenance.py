"""Read-only recovery provenance for a local preview's current drafts (W14.6).

``local_cli import-run`` and ``restore-run`` retain snapshots in the separate local
SQLite command authority as ``origin='import'`` domain snapshots (W14.1/14.2/14.5);
an import never alters any authority's current state. This reader opens such a
journal read-only and reports current draft IDs present in import history,
retaining the exact matching packet identity when available. Such a draft is
imported history: its bytes carry a review that was never made
here, so it is read-only at the command boundary as well as in the dashboard.
A draft that was never imported is absent from the map. Changed imported bytes
alone do not prove a supported local transition: that ID stays held until such
a transition exists. Exact identities select the matching retained import for
display, never grant currentness. Unavailable provenance refuses mutation.

Restores go through the same importer, so they are labelled ``import``: the
journal's origin column admits only bootstrap/command/import and a separate
restore origin is a domain-schema decision. No ``superseded`` entry is produced,
because no journal row binds a draft id to its replacement. The production Gist
path never consults this reader; an absent journal is an empty map.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import stat
from typing import Any

from src.commands import domain_journal
from src.commands.schema import Command, CommandError, canonical_json
from src.editorial.revisions import draft_identity

MAX_DRAFT_PACKETS = 20000


class ProvenanceUnavailable(OSError):
    """The configured journal cannot be read; callers must not present records as current."""


def _connect(path: str | Path, environment: str) -> sqlite3.Connection:
    journal = Path(path)
    if not journal.is_absolute():
        raise ProvenanceUnavailable("absolute_recovery_journal_required")
    try:
        metadata = journal.lstat()
    except OSError as exc:
        raise ProvenanceUnavailable("recovery_journal_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ProvenanceUnavailable("recovery_journal_unavailable")
    try:
        connection = sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
    except sqlite3.Error as exc:
        raise ProvenanceUnavailable("recovery_journal_unavailable") from exc
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        row = connection.execute("SELECT environment FROM authority_metadata WHERE singleton=1").fetchone()
        if row is None or row["environment"] != environment:
            raise ProvenanceUnavailable("recovery_journal_environment_mismatch")
        domain_journal.validate_schema(connection)
    except (sqlite3.Error, domain_journal.DomainJournalError) as exc:
        connection.close()
        raise ProvenanceUnavailable("recovery_journal_unavailable") from exc
    except BaseException:
        connection.close()
        raise
    return connection


def check(path: str | Path, *, environment: str = "local") -> None:
    """Refuse an unusable journal when an adapter starts, before any request."""
    with closing(_connect(path, environment)):
        pass


def configure(authority: Any, path: str | Path) -> None:
    """Trusted optional adapter input, shared by ingress and its consuming worker."""
    check(path, environment=authority.environment)
    authority.recovery_journal = str(path)


def require_current(authority: Any, command: Command, state: dict) -> None:
    """Check actual locked targets afresh; never cache a GET projection as authority.

    ProvenanceUnavailable deliberately escapes command-refusal conversion, leaving
    an accepted command pending when the journal cannot be read reliably.
    """
    path = getattr(authority, "recovery_journal", None)
    if path is None or not command.targets:
        return
    held = provenance(path, state, environment=authority.environment)
    if any(target.draft_id in held for target in command.targets):
        raise CommandError("imported_record_read_only", "Imported history has no supported current-revision transition")


def _identity(draft: dict) -> str | None:
    try:
        if not isinstance(draft.get("text"), str):
            return None
        return canonical_json(draft_identity(draft))
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


def provenance(path: str | Path | None, current_state: Any, *, environment: str = "local") -> dict[str, dict]:
    """``{draft_id: {origin, import_id, source_sha256}}`` for IDs with retained import history."""
    if path is None:
        return {}
    drafts = current_state.get("drafts") if isinstance(current_state, dict) else None
    current: dict[str, list[str | None]] = {}
    for draft in drafts if isinstance(drafts, list) else []:
        if isinstance(draft, dict) and isinstance(draft.get("id"), str) and draft["id"]:
            current.setdefault(draft["id"], []).append(_identity(draft))
    result: dict[str, dict] = {}
    matched: set[str] = set()
    try:
        with closing(_connect(path, environment)) as connection:
            rows = connection.execute(
                "SELECT s.origin_id, s.artifact_sha256 AS source_sha256, o.artifact_sha256 AS packet_sha256 "
                "FROM domain_snapshots s JOIN domain_occurrences o ON o.snapshot_id=s.snapshot_id "
                "WHERE s.origin='import' AND o.kind='draft_packet' "
                "ORDER BY s.recorded_at, s.snapshot_id, o.locator LIMIT ?", (MAX_DRAFT_PACKETS + 1,)).fetchall()
            if len(rows) > MAX_DRAFT_PACKETS:
                raise ProvenanceUnavailable("recovery_journal_exceeds_bound")
            packets: dict[str, Any] = {}
            for row in rows:
                if row["packet_sha256"] not in packets:
                    packets[row["packet_sha256"]] = json.loads(domain_journal.read_artifact(connection, row["packet_sha256"]))
                packet = packets[row["packet_sha256"]]
                draft_id = packet.get("id") if isinstance(packet, dict) else None
                if not isinstance(draft_id, str) or not draft_id:
                    raise ProvenanceUnavailable("recovery_journal_unavailable")
                if draft_id not in current or draft_id in matched:
                    continue
                identities = current[draft_id]
                imported = _identity(packet)
                exact = len(identities) == 1 and identities[0] is not None and imported is not None and identities[0] == imported
                if draft_id not in result or exact:
                    result[draft_id] = {"origin": "import", "import_id": row["origin_id"], "source_sha256": row["source_sha256"]}
                if exact:
                    matched.add(draft_id)
    except (sqlite3.Error, domain_journal.DomainJournalError, ValueError, RecursionError) as exc:
        raise ProvenanceUnavailable("recovery_journal_unavailable") from exc
    return result
