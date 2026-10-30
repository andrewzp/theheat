"""Bounded private export/restore of explicitly selected retained media.

An export is a NEW owner-only directory holding an index and content-addressed blobs
(``blobs/<sha256>``) for each selected item's complete closure: a published manifest
with its original, canonical derivative, receipt and product/reuse references (all
addresses, versions and rights/product references preserved verbatim), or a CRW
source packet. Every item is fully re-verified through the real readers before any
byte is written. Restore verifies every name, size, hash and item relation in memory
before a single insert through the separately configured insert-only writer.

Refused: missing/corrupt/conflicting/oversized data, path traversal, symlinks,
FIFO/device or other non-regular inputs, unexpected entries and any existing output.
This is not a database-wide backup, a draft-authority migration or a cleanup job:
nothing is ever deleted, and existing SQLite backups remain usable unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat

from src.media import gist_assets

KIND = "theheat_media_export_v1"
INDEX = "export.json"
BLOBS = "blobs"
MAX_ITEMS = 32
MAX_BLOB_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_INDEX_BYTES = 256 * 1024
_SHA = re.compile(r"[a-f0-9]{64}\Z")


class ExportError(ValueError):
    def __init__(self, code, reason):
        self.code = code
        super().__init__(reason)


def _require(condition, code, reason):
    if not condition:
        raise ExportError(code, reason)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _safe_path(value, *, kind):
    """Absolute, normalized, symlink-free; never a traversal."""
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts and str(path) == os.path.normpath(str(path)),
             "export_path_invalid", f"the {kind} must be an absolute normalized path")
    _require(not any(part.is_symlink() for part in (path, *path.parents)), "export_path_invalid",
             f"the {kind} path must not contain symlinks")
    return path


class _Memory:
    """Verified in-memory blobs, read through the same store interface as the readers."""

    backend = "memory"

    def __init__(self, blobs):
        self._blobs = blobs

    def get(self, sha, *, limit):
        raw = self._blobs.get(sha)
        if raw is None:
            raise gist_assets.MediaStoreError("media_asset_missing", "a required export blob is missing")
        if not 0 < len(raw) <= limit:
            raise gist_assets.MediaStoreError("media_asset_invalid", "an export blob exceeds its bound")
        return raw


def _closure(store, item):
    """(index row, {sha: bytes}) for one selected item, fully re-verified."""
    from src.editorial.revisions import fingerprint
    from src.media import crw_graphic_adapter as adapter, gist_crw_media as crw, gist_published_media as published
    from src.media.gist_hazard_media import MediaWithheld

    kind, sha = item
    _require(kind in ("published", "crw_packet") and type(sha) is str and _SHA.fullmatch(sha),
             "export_selection_invalid", "select published manifests or CRW packets by exact SHA256")
    try:
        if kind == "published":
            manifest, original, png = published.read(store, sha)
            value = manifest["document"]
            blobs = {sha: store.get(sha, limit=published.MAX_MANIFEST_BYTES), value["original"]["sha256"]: original,
                     manifest["derivative"]["sha256"]: png}
            for row in (value["receipt"], *value["references"].values()):
                blobs[row["sha256"]] = store.get(row["sha256"], limit=row["byte_count"])
        else:
            adapter._packet(packet := crw.load_packet(store, sha), fingerprint(packet))  # Same structure rules.
            blobs = {sha: store.get(sha, limit=crw.MAX_PACKET_BYTES)}
    except (MediaWithheld, gist_assets.MediaStoreError, ValueError, KeyError, TypeError) as exc:
        code = getattr(exc, "code", "media_asset_invalid")
        raise ExportError(code, "a selected item is missing, changed or invalid; nothing was exported") from None
    return {"kind": kind, "sha256": sha, "blobs": sorted(blobs)}, blobs


_UNRESOLVED_PHASES = ("submitted", "unknown")


def _media_references(draft):
    """(attachment, is_current) for each store-backed attachment on a draft or its retained history."""
    from src.media.gist_media import CRW, STORE_KINDS
    rows = [(draft.get("media_attachment"), True)]
    history = draft.get("revision_history")
    rows += [(row.get("media_attachment"), False) for row in (history if type(history) is list else []) if type(row) is dict]
    for attachment, current in rows:
        if type(attachment) is not dict or attachment.get("kind") not in STORE_KINDS:
            continue
        if attachment["kind"] == CRW:
            sha = (attachment.get("source") or {}).get("packet_artifact_sha256")
            yield ("crw_packet", sha), current
        else:
            sha = (attachment.get("asset") or {}).get("manifest_sha256")
            yield ("published", sha), current


def plan(store, state):
    """Read-only restore/export plan for the retained media the saved drafts need (W10.5).

    Every store-backed attachment on a draft (current or in its revision history) is
    checked through the same closure readers as export, the preview and the sender: no
    write, fetch or substitution. Each item says why it matters (unresolved delivery,
    current joint review or approval, delivered history, attached) and whether this store
    can serve it; a missing or changed artifact is a named hold that the preview and the
    sender also apply before any attachment or upload. Gist remains the draft authority;
    nothing here restores, edits or approves a draft.
    """
    _require(type(state) is dict and type(state.get("drafts", [])) is list, "plan_state_invalid",
             "the saved state must be a JSON object with a drafts list")
    ledger = state.get("publish_ledger") if type(state.get("publish_ledger")) is dict else {}
    needed: dict[tuple, dict[str, set[str]]] = {}
    for draft in state.get("drafts", []):
        if type(draft) is not dict or type(draft.get("id")) is not str:
            continue
        row = ledger.get(draft.get("event_id") or draft["id"])
        phase = row.get("phase") if type(row) is dict else None
        for item, current in _media_references(draft):
            reasons = set()
            if phase in _UNRESOLVED_PHASES or draft.get("publish_outcome") in _UNRESOLVED_PHASES:
                reasons.add("unresolved_delivery")
            if phase == "confirmed":
                reasons.add("delivered_history")
            if current and (draft.get("status") == "approved" or "media_review_binding" in draft):
                reasons.add("current_review")
            reasons.add("attached" if current else "revision_history")
            entry = needed.setdefault(item, {})
            entry.setdefault(draft["id"], set()).update(reasons)
    items = []
    for (kind, sha), drafts in sorted(needed.items(), key=lambda pair: (pair[0][0], str(pair[0][1]))):
        try:
            _closure(store, (kind, sha))
            status, hold = "present", None
        except ExportError as exc:
            status, hold = "held", exc.code
        items.append({"kind": kind, "sha256": sha if type(sha) is str else None, "status": status, "hold": hold,
                      "drafts": [{"draft_id": draft_id, "reasons": sorted(reasons)}
                                 for draft_id, reasons in sorted(drafts.items())]})
    present = [row for row in items if row["status"] == "present"]
    flags = [["--manifest" if row["kind"] == "published" else "--crw-packet", row["sha256"]] for row in present]
    batches = [[value for pair in flags[i:i + MAX_ITEMS] for value in pair] for i in range(0, len(flags), MAX_ITEMS)]
    return {"items": items, "present": len(present), "held": len(items) - len(present),
            "export_batches": batches, "publication_approved": False}


def export(store, items, target):
    """Verify every selected closure, then write a new private export directory."""
    _require(type(items) in (list, tuple) and 0 < len(items) <= MAX_ITEMS and len(set(items)) == len(items),
             "export_selection_invalid", f"select 1..{MAX_ITEMS} distinct items")
    target = _safe_path(target, kind="export target")
    _require(not os.path.lexists(target), "export_output_exists", "the export target already exists; nothing replaced")
    _require(target.parent.is_dir(), "export_path_invalid", "the export target's parent must be an existing directory")
    rows, blobs = [], {}
    for item in items:
        row, closure = _closure(store, tuple(item))
        rows.append(row)
        blobs.update(closure)
    _require(sum(map(len, blobs.values())) <= MAX_TOTAL_BYTES, "export_too_large", "the export exceeds its bound")
    index = {"schema_version": 1, "kind": KIND, "items": rows,
             "blobs": {sha: len(raw) for sha, raw in sorted(blobs.items())}}
    raw_index = json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
    _require(len(raw_index) <= MAX_INDEX_BYTES, "export_too_large", "the export index exceeds its bound")
    os.mkdir(target, 0o700)
    os.mkdir(target / BLOBS, 0o700)
    for sha, raw in sorted(blobs.items()):
        _write_new(target / BLOBS / sha, raw)
    _write_new(target / INDEX, raw_index)  # Last: a complete index marks a complete export.
    return {"export": str(target), "items": len(rows), "blobs": len(blobs), "index_sha256": _sha(raw_index)}


def _write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_private(path, limit):
    """One owner-only regular file, opened without following links; never FIFO/device."""
    try:
        meta = os.lstat(path)
    except OSError:
        raise ExportError("export_missing", "a required export file is missing") from None
    _require(stat.S_ISREG(meta.st_mode), "export_entry_invalid", "export entries must be regular files")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                 and (info.st_dev, info.st_ino) == (meta.st_dev, meta.st_ino), "export_entry_invalid",
                 "export files must be private (0600) regular files owned by this user")
        _require(0 < info.st_size <= limit, "export_too_large", "an export file exceeds its bound")
        raw = stream.read(limit + 1)
    _require(len(raw) == info.st_size, "export_entry_invalid", "an export file changed while reading")
    return raw


def _private_directory(path):
    meta = os.lstat(path)
    _require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid() and stat.S_IMODE(meta.st_mode) == 0o700,
             "export_entry_invalid", "export directories must be private (0700) and owned by this user")


def verify(source):
    """Every name, size, hash and item relation, in memory; returns (index, blobs)."""
    source = _safe_path(source, kind="export source")
    try:
        _private_directory(source)
        _private_directory(source / BLOBS)
    except OSError:
        raise ExportError("export_missing", "the export directory is missing or incomplete") from None
    _require(sorted(os.listdir(source)) == sorted([INDEX, BLOBS]), "export_entry_invalid",
             "unexpected entries in the export directory")
    try:  # Strict JSON: duplicate keys and non-finite numbers are refused.
        index = gist_assets.decode_document(_read_private(source / INDEX, MAX_INDEX_BYTES))
    except gist_assets.MediaStoreError:
        raise ExportError("export_index_invalid", "the export index is not strict JSON") from None
    _require(type(index) is dict and set(index) == {"schema_version", "kind", "items", "blobs"}
             and index["schema_version"] == 1 and index["kind"] == KIND and type(index["items"]) is list
             and 0 < len(index["items"]) <= MAX_ITEMS and type(index["blobs"]) is dict, "export_index_invalid",
             "unsupported export index")
    sizes = index["blobs"]
    _require(all(type(k) is str and _SHA.fullmatch(k) and type(v) is int and 0 < v <= MAX_BLOB_BYTES
                 for k, v in sizes.items()) and sum(sizes.values()) <= MAX_TOTAL_BYTES, "export_index_invalid",
             "export blob names or sizes are invalid")
    names = os.listdir(source / BLOBS)
    _require(sorted(names) == sorted(sizes), "export_entry_invalid" if set(names) - set(sizes) else "export_missing",
             "export blobs differ from the index")
    blobs = {}
    for sha, size in sizes.items():
        raw = _read_private(source / BLOBS / sha, MAX_BLOB_BYTES)
        _require(len(raw) == size and _sha(raw) == sha, "export_blob_changed", "an export blob is corrupt")
        blobs[sha] = raw
    memory, referenced = _Memory(blobs), set()
    for row in index["items"]:
        _require(type(row) is dict and set(row) == {"kind", "sha256", "blobs"} and type(row["blobs"]) is list,
                 "export_index_invalid", "invalid export item")
        try:  # The same readers as the preview and sender, over the verified bytes only.
            _row, closure = _closure(memory, (row["kind"], row["sha256"]))
        except ExportError as exc:
            raise ExportError("export_blob_changed" if exc.code.startswith("media_") else exc.code,
                              "an export item failed verification; nothing was restored") from None
        _require(row["blobs"] == sorted(closure), "export_index_invalid",
                 "an export item's dependencies differ from its verified closure")
        referenced |= set(row["blobs"])
    _require(referenced == set(blobs), "export_entry_invalid", "the export holds blobs no item requires")
    return index, blobs


def restore(writer, source):
    """Verify everything first, then insert each item's closure atomically (idempotent retries)."""
    index, blobs = verify(source)
    restored = 0
    for row in index["items"]:
        try:
            keys = writer.put_many([blobs[sha] for sha in row["blobs"]])
        except gist_assets.MediaStoreError as exc:
            raise ExportError(exc.code, f"the media store refused or could not confirm the restore after "
                                        f"{restored} complete item(s); retry restores idempotently") from None
        _require(keys == row["blobs"], "media_retention_unknown", "the store did not confirm every restored blob")
        restored += 1
    return {"restored_items": restored, "restored_blobs": len(blobs), "verified": True}
