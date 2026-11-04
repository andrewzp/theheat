"""Seal a private threshold checkpoint for transport on the existing Actions runner."""

from __future__ import annotations

import argparse
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.refresh_station_inventory import INVENTORY_FILE, MAX_INVENTORY_BYTES
from scripts.threshold_artifacts import ArtifactError, digest
from src.data.ghcn_db import get_meta
from src.evaluation.file_boundary import read_regular, write_private_directory

MAGIC = b"theheat-threshold-checkpoint-v1\0"
KEY_ENV = "THEHEAT_THRESHOLD_CHECKPOINT_KEY"
NONCE_BYTES = 12
# Raw SQLite includes dense provenance maps. Keep its cap independent of
# the compressed envelope carried by Actions.
MAX_CHECKPOINT_DB = 512 * 1024**2
MAX_ENVELOPE_BYTES = 384 * 1024**2
FILES = {INVENTORY_FILE: MAX_INVENTORY_BYTES, "refresh.sqlite": MAX_CHECKPOINT_DB}


def _cipher(secret: str) -> AESGCM:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", secret):
        raise ArtifactError("threshold_checkpoint_key_invalid")
    return AESGCM(bytes.fromhex(secret))


def _context(manifest: Path, repository: str, run_id: str, days: int) -> bytes:
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id) or not 4 <= days <= 31):
        raise ArtifactError("threshold_checkpoint_context_invalid")
    sha, _ = digest(manifest, 64 * 1024)
    return MAGIC + json.dumps([repository, run_id, days, sha], separators=(",", ":")).encode()


def _snapshot_database(directory: Path, destination: Path) -> None:
    source = directory / "refresh.sqlite"
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = source.with_name(source.name + suffix)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ArtifactError("threshold_checkpoint_database_invalid")
    if not source.is_file() or source.stat().st_size > MAX_CHECKPOINT_DB:
        raise ArtifactError("threshold_checkpoint_database_invalid")
    # Online backup includes committed WAL pages after an abrupt timeout. Only
    # the standalone snapshot enters the envelope, never WAL or lock files.
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        pages = connection.execute("PRAGMA page_count").fetchone()[0]
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        if pages * page_size > MAX_CHECKPOINT_DB or not get_meta(connection, "incremental_plan"):
            raise ArtifactError("threshold_checkpoint_plan_unavailable")
        with closing(sqlite3.connect(destination)) as snapshot:
            connection.backup(snapshot)
            snapshot.execute("PRAGMA journal_mode=DELETE")
            if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ArtifactError("threshold_checkpoint_database_invalid")


def seal(directory: Path, archive: Path, cipher: AESGCM, context: bytes) -> None:
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ArtifactError("threshold_checkpoint_directory_not_private")
    inventory = read_regular(str(directory.absolute() / INVENTORY_FILE), MAX_INVENTORY_BYTES)
    with TemporaryDirectory(dir=directory.parent, prefix=".threshold-seal-") as staging:
        snapshot = Path(staging) / "refresh.sqlite"
        _snapshot_database(directory, snapshot)
        body = BytesIO()
        with zipfile.ZipFile(body, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zipped:
            zipped.writestr(INVENTORY_FILE, inventory)
            zipped.write(snapshot, arcname="refresh.sqlite")
        nonce = os.urandom(NONCE_BYTES)
        envelope = MAGIC + nonce + cipher.encrypt(nonce, body.getvalue(), context)
    if len(envelope) > MAX_ENVELOPE_BYTES:
        raise ArtifactError("threshold_checkpoint_envelope_too_large")
    with archive.open("xb") as handle:
        handle.write(envelope)


def unseal(archive: Path, directory: Path, cipher: AESGCM, context: bytes) -> None:
    envelope = read_regular(str(archive.absolute()), MAX_ENVELOPE_BYTES)
    if not envelope.startswith(MAGIC):
        raise ArtifactError("threshold_checkpoint_envelope_invalid")
    start = len(MAGIC)
    try:
        payload = cipher.decrypt(envelope[start:start + NONCE_BYTES], envelope[start + NONCE_BYTES:], context)
    except (InvalidTag, ValueError):
        raise ArtifactError("threshold_checkpoint_authentication_failed") from None
    with zipfile.ZipFile(BytesIO(payload)) as zipped:
        entries = zipped.infolist()
        if len(entries) != len(FILES) or {entry.filename for entry in entries} != set(FILES):
            raise ArtifactError("threshold_checkpoint_members_invalid")
        if any(not 0 < entry.file_size <= FILES[entry.filename] for entry in entries):
            raise ArtifactError("threshold_checkpoint_member_size_invalid")
        files = {entry.filename: zipped.read(entry) for entry in entries}
    write_private_directory(str(directory.absolute()), files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-key", "seal", "unseal"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path, default=Path("data/station_thresholds.version"))
    parser.add_argument("--repository", default="")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--days", type=int, default=12)
    args = parser.parse_args(argv)
    try:
        cipher = _cipher(os.environ.get(KEY_ENV, ""))
        if args.action == "check-key":
            return 0
        if args.directory is None or args.archive is None:
            raise ArtifactError("threshold_checkpoint_paths_missing")
        context = _context(args.manifest, args.repository, args.run_id, args.days)
        if args.action == "seal":
            seal(args.directory, args.archive, cipher, context)
        else:
            unseal(args.archive, args.directory, cipher, context)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as error:
        label = str(error) if isinstance(error, ArtifactError) else "threshold_checkpoint_transport_failed"
        print(f"ERROR: {label}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
