"""Durable exact bytes for Gist media that a recipe alone cannot reconstruct.

Published originals/derivatives and retained source packets (CRW CSV) live in the
existing immutable domain artifact store (``domain_journal``: content-addressed,
update/delete/replace triggers). Gist keeps only a reference: the SHA256 of an
immutable asset manifest or packet. The reference never names a URL or a path, and
nothing here fetches from the network. State and approval authority stay in Gist.

Configuration: ``THEHEAT_MEDIA_STORE=sqlite:<absolute path>``. Unset, unsupported or
unreachable configuration holds only the store-backed media lanes with
``media_store_unavailable``; native recipes never read the store.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from src.commands import domain_journal

NAMESPACE = "theheat-gist-media"
ENV = "THEHEAT_MEDIA_STORE"
MAX_DOCUMENT_BYTES = 1_000_000
SHA = re.compile(r"[a-f0-9]{64}\Z")


class MediaStoreError(ValueError):
    """A bounded store refusal: unavailable, missing, changed or oversized bytes."""

    def __init__(self, code, reason):
        self.code = code
        super().__init__("Image withheld: " + reason)


def _require(condition, code, reason):
    if not condition:
        raise MediaStoreError(code, reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode_document(value):
    """Exact canonical bytes of a JSON document (its store identity is their SHA256)."""
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise MediaStoreError("media_asset_invalid", "the retained document is not finite JSON") from None
    _require(len(raw) <= MAX_DOCUMENT_BYTES, "media_asset_invalid", "the retained document exceeds its bound")
    return raw


def _strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "media_asset_changed", "a retained document has duplicate keys")
        result[key] = value
    return result


def decode_document(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError, RecursionError):
        raise MediaStoreError("media_asset_changed", "a retained document is not valid JSON") from None
    _require(encode_document(value) == raw, "media_asset_changed", "a retained document is not canonical")
    return value


def _owned_regular(path, *, must_exist):
    """No-follow local file boundary: absolute, no symlinked component, owner-only file."""
    _require(path.is_absolute() and ".." not in path.parts, "media_store_unavailable",
             "the media store path must be absolute")
    for part in (path, *path.parents):
        _require(not part.is_symlink(), "media_store_unavailable", "the media store path may not use symlinks")
    if not path.exists():
        _require(not must_exist, "media_store_unavailable", "the media store does not exist")
        return
    meta = os.stat(path, follow_symlinks=False)
    _require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
             and stat.S_IMODE(meta.st_mode) & 0o077 == 0, "media_store_unavailable",
             "the media store must be a private regular file")


class SQLiteMediaStore:
    """The existing immutable local artifact store, one transaction per operation."""

    backend = "sqlite"

    def __init__(self, path):
        self.path = Path(path)
        _owned_regular(self.path, must_exist=False)

    def _connect(self, *, write):
        _owned_regular(self.path, must_exist=not write)
        if write and not self.path.exists():
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        uri = self.path.as_uri() + ("" if write else "?mode=ro")
        try:
            connection = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
        except sqlite3.Error:
            raise MediaStoreError("media_store_unavailable", "the media store could not be opened") from None
        connection.row_factory = sqlite3.Row
        return connection

    def put_many(self, blobs):
        """Retain every blob atomically; identical retries are idempotent."""
        with closing(self._connect(write=True)) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                domain_journal.install(connection, NAMESPACE)
                identities = [domain_journal._artifact(connection, raw) for raw in blobs]
                connection.execute("COMMIT")
            except (sqlite3.Error, domain_journal.DomainJournalError) as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise MediaStoreError("media_store_unavailable", "the media store refused the write") from exc
        return identities

    def get(self, sha, *, limit):
        _require(type(sha) is str and SHA.fullmatch(sha), "media_asset_invalid", "invalid asset reference")
        with closing(self._connect(write=False)) as connection:
            try:
                initialized = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='domain_schema'").fetchone()
                _require(initialized is not None, "media_asset_missing", "the media store has no retained assets")
                domain_journal.validate_schema(connection, NAMESPACE)
                row = connection.execute("SELECT byte_count FROM domain_artifacts WHERE sha256=?", (sha,)).fetchone()
                _require(row is not None, "media_asset_missing", "a retained asset is missing from the media store")
                # Bound the length before reading the payload into memory.
                _require(0 < row["byte_count"] <= limit, "media_asset_invalid", "a retained asset exceeds its bound")
                raw = domain_journal.read_artifact(connection, sha)
            except (sqlite3.Error, domain_journal.DomainJournalError) as exc:
                raise MediaStoreError("media_asset_changed", "the media store bytes no longer match") from exc
        _require(len(raw) <= limit and digest(raw) == sha, "media_asset_changed", "a retained asset changed")
        return raw

    def backup(self, target):
        """Exact online copy into a new private file (SQLite backup API)."""
        target = Path(target)
        _owned_regular(target, must_exist=False)
        _require(not target.exists(), "media_store_unavailable", "the backup target already exists")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with closing(self._connect(write=False)) as source, closing(sqlite3.connect(target)) as copy:
            source.backup(copy)
        return SQLiteMediaStore(target)


def configured(environ=None):
    """The deployment's configured store, or an explicit lane-specific hold."""
    value = (os.environ if environ is None else environ).get(ENV, "")
    _require(type(value) is str and value != "", "media_store_unavailable",
             "no media store is configured for published or retained-source images")
    _require(value.startswith("sqlite:"), "media_store_unavailable", "the configured media store is not supported")
    return SQLiteMediaStore(value[len("sqlite:"):])


def put_document(store, value, *extra_blobs):
    raw = encode_document(value)
    return store.put_many([raw, *extra_blobs])[0]


def get_document(store, sha, *, limit=MAX_DOCUMENT_BYTES):
    return decode_document(store.get(sha, limit=limit))
