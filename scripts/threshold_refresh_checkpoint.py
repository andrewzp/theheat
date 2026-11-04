"""Private, single-owner restart data for one incremental GHCN refresh."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any

from scripts.threshold_artifacts import ArtifactError, digest
from src.data.ghcn_db import get_meta, load_thresholds, open_db, set_meta, upsert_thresholds
from src.data.ghcn_format import StationThresholds


def _seal(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@contextmanager
def lock_baseline(path: Path) -> Iterator[None]:
    identity = path.lstat()
    if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
        raise ArtifactError("threshold_database_unavailable")
    # SQLite uses its own locks. A separate owner file avoids contending
    # with SQLite's lock implementation on macOS.
    lock_path = path.with_name(path.name + ".refresh.lock")
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, "a") as owner:
        if not stat.S_ISREG(os.fstat(owner.fileno()).st_mode):
            raise ArtifactError("threshold_checkpoint_invalid_lock")
        try:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ArtifactError("threshold_refresh_already_owned") from None
        yield


def baseline_identity(path: Path) -> tuple[str, int]:
    for suffix in ("-wal", "-journal"):
        journal = Path(str(path) + suffix)
        if journal.exists() and journal.stat().st_size:
            raise ArtifactError("threshold_database_uncheckpointed")
    return digest(path)


def _manifest_identity(path: Path) -> tuple[str, int] | None:
    manifest = path.with_suffix(".version")
    if manifest.is_symlink() or (manifest.exists() and not manifest.is_file()):
        raise ArtifactError("threshold_checkpoint_invalid_manifest")
    return digest(manifest) if manifest.is_file() else None


class RefreshCheckpoint:
    def __init__(self, conn: sqlite3.Connection, today: date, baseline_digest: tuple[str, int],
                 manifest_digest: tuple[str, int] | None):
        self.conn = conn
        self.today = today
        self.baseline_digest = baseline_digest
        self.manifest_digest = manifest_digest

    def diff(self, start: date, end: date, fetch: Callable[[date, date], bytes | None]) -> bytes | None:
        key = start.isoformat(), end.isoformat()
        row = self.conn.execute(
            "SELECT payload, digest FROM refresh_diffs WHERE start = ? AND end = ?", key
        ).fetchone()
        if row is None:
            if get_meta(self.conn, "incremental_plan") is not None:
                raise ArtifactError("threshold_checkpoint_diff_missing")
            payload = fetch(start, end)
            checksum = sha256(payload).hexdigest() if payload is not None else None
            with self.conn:
                self.conn.execute("INSERT INTO refresh_diffs VALUES (?, ?, ?, ?)", (*key, payload, checksum))
            return payload
        payload, checksum = row
        if (sha256(payload).hexdigest() if payload is not None else None) != checksum:
            raise ArtifactError("threshold_checkpoint_diff_changed")
        return payload

    def bind_plan(self, *, cutoff: date, stations: set[str]) -> None:
        diffs = self.conn.execute("SELECT start, end, digest FROM refresh_diffs ORDER BY start, end").fetchall()
        plan = _seal((cutoff.isoformat(), sorted(stations), diffs))
        existing = get_meta(self.conn, "incremental_plan")
        if existing is not None and existing != plan:
            raise ArtifactError("threshold_checkpoint_plan_changed")
        with self.conn:
            set_meta(self.conn, "incremental_plan", plan)

    def _station_seal(self, station_id: str) -> str:
        values = self.conn.execute(
            "SELECT kind, month, day, value_c, record_year FROM thresholds WHERE station_id = ? "
            "ORDER BY kind, month, day, value_c, record_year", (station_id,),
        ).fetchall()
        provenance = self.conn.execute(
            "SELECT payload_json FROM threshold_provenance WHERE station_id = ?", (station_id,),
        ).fetchone()
        return _seal((get_meta(self.conn, "incremental_plan"), station_id, values, provenance))

    def verify_baseline(self, path: Path) -> None:
        if baseline_identity(path) != self.baseline_digest or _manifest_identity(path) != self.manifest_digest:
            raise ArtifactError("threshold_checkpoint_scope_changed")

    def completed(self, station_id: str) -> StationThresholds | None:
        expected = self.conn.execute("SELECT seal FROM refresh_stations WHERE station_id = ?", (station_id,)).fetchone()
        if expected is None:
            return None
        if self._station_seal(station_id) != expected[0]:
            raise ArtifactError("threshold_checkpoint_station_changed")
        result = load_thresholds(self.conn, station_id)
        if result is None:
            raise ArtifactError("threshold_checkpoint_station_missing")
        return result

    def save(self, result: StationThresholds, cutoff: date) -> None:
        checksum = result.provenance.get("source_payload_sha256")
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum) \
                or result.provenance.get("requested_comparison_cutoff") != cutoff.isoformat():
            raise ArtifactError("threshold_checkpoint_archive_unbound")
        with self.conn:
            upsert_thresholds(self.conn, result)
            self.conn.execute(
                "INSERT INTO refresh_stations VALUES (?, ?)", (result.station_id, self._station_seal(result.station_id)),
            )


@contextmanager
def open_checkpoint(path: Path, baseline: Path, *, today: date, days: int, lag_days: int,
                    updater: Path, expected_digest: tuple[str, int]) -> Iterator[RefreshCheckpoint]:
    # An ordinary workflow owns its private directory. A concurrent local owner
    # must fail rather than mixing writes under the same plan.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ArtifactError("threshold_checkpoint_invalid_directory")
    target = path / "refresh.sqlite"
    for name in ("refresh.sqlite", "refresh.sqlite-wal", "refresh.sqlite-shm", "refresh.sqlite-journal"):
        member = path / name
        if member.is_symlink() or (member.exists() and not member.is_file()):
            raise ArtifactError("threshold_checkpoint_invalid_database")
    if target.exists() and target.samefile(baseline):
        raise ArtifactError("threshold_checkpoint_aliases_baseline")
    baseline_digest = baseline_identity(baseline)
    if baseline_digest != expected_digest:
        raise ArtifactError("threshold_checkpoint_scope_changed")
    root = updater.resolve().parent.parent
    owner_files = (
        updater, Path(__file__), root / "scripts/threshold_artifacts.py",
        root / "src/data/ghcn_format.py", root / "src/data/ghcn_db.py",
    )
    manifest_digest = _manifest_identity(baseline)
    owner_digests = [sha256(owner.read_bytes()).hexdigest() for owner in owner_files]
    descriptor = os.open(path / ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ArtifactError("threshold_checkpoint_invalid_lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open_db(target) as conn:
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS refresh_diffs(start TEXT, end TEXT, payload BLOB, digest TEXT, PRIMARY KEY(start, end));"
                "CREATE TABLE IF NOT EXISTS refresh_stations(station_id TEXT PRIMARY KEY, seal TEXT NOT NULL);"
            )
            saved_scope = get_meta(conn, "incremental_scope")
            saved_today = get_meta(conn, "incremental_today") if saved_scope is not None else today.isoformat()
            if saved_today is None:
                raise ArtifactError("threshold_checkpoint_date_missing")
            scope = _seal((baseline_digest, manifest_digest, saved_today, days, lag_days, owner_digests))
            if saved_scope is None:
                with conn:
                    set_meta(conn, "incremental_scope", scope)
                    set_meta(conn, "incremental_today", today.isoformat())
            elif saved_scope != scope:
                raise ArtifactError("threshold_checkpoint_scope_changed")
            yield RefreshCheckpoint(conn, date.fromisoformat(saved_today), baseline_digest, manifest_digest)
