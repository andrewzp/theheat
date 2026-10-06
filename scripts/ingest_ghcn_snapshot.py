#!/usr/bin/env python3
"""Offline dated GHCN CSV ingestion; produces a private raw-data candidate only.

No downloads, threshold updates or publication. A supplied transfer receipt proves
local consistency, not authenticity, scientific eligibility or reporting intervals.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import csv
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
from typing import Any, BinaryIO, Iterator, NoReturn
import zlib

READER_VERSION = "ghcn-dated-csv-1"
SOURCE_KIND = "noaa-superghcnd-full-csv-gzip"
BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/superghcnd/"
RECEIPT_FIELDS = {
    "schema_version", "source_kind", "url", "snapshot_date", "retrieved_at",
    "http_status", "compressed_sha256", "compressed_bytes",
}
STATION = re.compile(r"[A-Z0-9]{11}")
CHUNK = 1024**2
MAX_LINE = 256
PAGE_SIZE = 4096


class SnapshotError(ValueError):
    """Fixed diagnostic labels; no paths, source rows or provider bodies."""


def fail(label: str) -> NoReturn:
    raise SnapshotError(label)


@dataclass(frozen=True)
class Limits:
    compressed_bytes: int
    expanded_bytes: int
    rows: int
    selected_rows: int
    database_bytes: int

    def validate(self) -> None:
        maxima = (32 * 1024**3, 256 * 1024**3, 5_000_000_000, 50_000_000, 64 * 1024**3)
        for value, maximum in zip(asdict(self).values(), maxima, strict=True):
            if type(value) is not int or not 1 <= value <= maximum:
                fail("snapshot_invalid_limits")
        if self.database_bytes < 64 * 1024 or self.selected_rows > self.rows:
            fail("snapshot_invalid_limits")


@contextmanager
def regular_input(path: Path) -> Iterator[BinaryIO]:
    # NONBLOCK prevents an untrusted FIFO from hanging before the type check.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            fail("snapshot_input_not_regular")
        stream = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with stream:
        yield stream


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("snapshot_invalid_receipt")
        result[key] = value
    return result


def read_receipt(path: Path) -> dict[str, Any]:
    with regular_input(path) as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        fail("snapshot_invalid_receipt")
    try:
        receipt = json.loads(raw, object_pairs_hook=_unique_object)
        if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
            fail("snapshot_invalid_receipt")
        if type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1:
            fail("snapshot_invalid_receipt")
        if receipt["source_kind"] != SOURCE_KIND:
            fail("snapshot_invalid_receipt")
        day = date.fromisoformat(receipt["snapshot_date"])
        if day.isoformat() != receipt["snapshot_date"]:
            fail("snapshot_invalid_receipt")
        expected = BASE_URL + f"superghcnd_full_{day.isoformat().replace('-', '')}.csv.gz"
        if receipt["url"] != expected:
            fail("snapshot_invalid_receipt")
        retrieved = receipt["retrieved_at"]
        if not isinstance(retrieved, str) or len(retrieved) > 40:
            fail("snapshot_invalid_receipt")
        at = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
        if at.utcoffset() is None or at.astimezone(timezone.utc).date() < day:
            fail("snapshot_invalid_receipt")
        if type(receipt["http_status"]) is not int or receipt["http_status"] != 200:
            fail("snapshot_invalid_receipt")
        if (not isinstance(receipt["compressed_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", receipt["compressed_sha256"])
                or type(receipt["compressed_bytes"]) is not int
                or not 1 <= receipt["compressed_bytes"] <= 32 * 1024**3):
            fail("snapshot_invalid_receipt")
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        fail("snapshot_invalid_receipt")
    return receipt


def _fingerprint(stream: BinaryIO) -> tuple[int, ...]:
    row = os.fstat(stream.fileno())
    return row.st_dev, row.st_ino, row.st_size, row.st_mtime_ns, row.st_ctime_ns


def _digest(stream: BinaryIO, limit: int) -> tuple[str, int]:
    result = hashlib.sha256()
    size = 0
    while chunk := stream.read(min(CHUNK, limit - size + 1)):
        size += len(chunk)
        if size > limit:
            fail("snapshot_compressed_limit")
        result.update(chunk)
    return result.hexdigest(), size


class _HashReader(io.RawIOBase):
    def __init__(self, stream: BinaryIO, limit: int):
        self.stream, self.limit = stream, limit
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self.stream.read(min(CHUNK, size if size >= 0 else CHUNK, self.limit - self.size + 1))
        self.size += len(chunk)
        if self.size > self.limit:
            fail("snapshot_compressed_limit")
        self.digest.update(chunk)
        return chunk


def _parse(line: bytes, snapshot_date: date) -> tuple[str, str, str, int, str, str, str, str]:
    if len(line) > MAX_LINE:
        fail("snapshot_line_limit")
    try:
        fields = next(csv.reader([line.decode("ascii")], strict=True))
        if len(fields) != 8:
            fail("snapshot_invalid_row")
        sid, day, element, value, mflag, qflag, sflag, obs_time = fields
        if (not STATION.fullmatch(sid) or not re.fullmatch(r"[0-9]{8}", day)
                or not re.fullmatch(r"[A-Z0-9]{4}", element)
                or not re.fullmatch(r"-?[0-9]{1,5}", value.strip())):
            fail("snapshot_invalid_row")
        observed = date(int(day[:4]), int(day[4:6]), int(day[6:]))
        if observed > snapshot_date:
            fail("snapshot_future_observation")
        for flag in (mflag, qflag, sflag):
            if len(flag) > 1 or any(ord(c) < 32 or ord(c) > 126 for c in flag):
                fail("snapshot_invalid_row")
        if obs_time and not re.fullmatch(r"[0-9]{4}", obs_time):
            fail("snapshot_invalid_row")
        # Raw observation-time codes are retained, not converted into UTC windows.
        return sid, observed.isoformat(), element, int(value), mflag, qflag, sflag, obs_time
    except SnapshotError:
        raise
    except (ValueError, UnicodeError, csv.Error, StopIteration):
        fail("snapshot_invalid_row")


def _candidate(
    stream: BinaryIO, receipt: dict[str, Any], station_ids: list[str], limits: Limits, path: Path,
) -> dict[str, Any]:
    wanted = set(station_ids)
    seen: set[str] = set()
    counts = dict(rows=0, selected_rows=0, expanded_bytes=0, missing_rows=0, flagged_rows=0)
    snapshot_date = date.fromisoformat(receipt["snapshot_date"])
    compressed = _HashReader(stream, limits.compressed_bytes)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(f"PRAGMA page_size={PAGE_SIZE}")
        conn.execute(f"PRAGMA max_page_count={limits.database_bytes // PAGE_SIZE}")
        # Disposable isolated staging only; a failed/interrupted file is never promoted.
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.executescript("""
            CREATE TABLE snapshot_observations (
                station_id TEXT NOT NULL, observation_date TEXT NOT NULL,
                element TEXT NOT NULL, raw_value INTEGER NOT NULL,
                mflag TEXT NOT NULL, qflag TEXT NOT NULL, sflag TEXT NOT NULL,
                raw_observation_time TEXT NOT NULL,
                PRIMARY KEY(station_id, observation_date, element)
            ) WITHOUT ROWID;
            CREATE TABLE snapshot_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        with gzip.GzipFile(fileobj=compressed, mode="rb") as decoded:
            while line := decoded.readline(MAX_LINE + 1):
                counts["expanded_bytes"] += len(line)
                counts["rows"] += 1
                if counts["expanded_bytes"] > limits.expanded_bytes:
                    fail("snapshot_expanded_limit")
                if counts["rows"] > limits.rows:
                    fail("snapshot_row_limit")
                record = _parse(line, snapshot_date)
                if record[0] not in wanted or record[2] not in {"TMAX", "TMIN"}:
                    continue
                counts["selected_rows"] += 1
                if counts["selected_rows"] > limits.selected_rows:
                    fail("snapshot_selected_limit")
                try:
                    conn.execute("INSERT INTO snapshot_observations VALUES(?,?,?,?,?,?,?,?)", record)
                except sqlite3.IntegrityError:
                    fail("snapshot_duplicate_observation")
                seen.add(record[0])
                counts["missing_rows"] += int(record[3] == -9999)
                counts["flagged_rows"] += int(bool(record[5].strip()))
                if counts["selected_rows"] % 4096 == 0:
                    conn.commit()
        if (compressed.digest.hexdigest(), compressed.size) != (
            receipt["compressed_sha256"], receipt["compressed_bytes"],
        ):
            fail("snapshot_source_changed")
        if not counts["rows"] or seen != wanted:
            fail("snapshot_station_scope_incomplete")
        report = {
            "schema_version": 1, "reader_version": READER_VERSION,
            "receipt": receipt, "station_ids": sorted(station_ids), "limits": asdict(limits),
            "counts": counts, "completed": True,
            "source_authenticity": "caller_supplied_receipt_not_independently_attested",
            "scientific_qualification": "not_evaluated",
            "production_threshold_asset": False,
        }
        conn.execute("INSERT INTO snapshot_metadata VALUES('completed_receipt', ?)", (
            json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False),
        ))
        conn.commit()
        if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            fail("snapshot_database_invalid")
    return report


def ingest(
    archive: Path, receipt_path: Path, output: Path, *, station_ids: list[str], limits: Limits,
) -> dict[str, Any]:
    """Promote one complete local candidate; existing outputs are never replaced.

    Consumers must separately qualify metadata, comparators and update lineage.
    This schema intentionally cannot be mistaken for station_thresholds.sqlite.
    """
    try:
        limits.validate()
        if (not isinstance(station_ids, list) or not 1 <= len(station_ids) <= 100_000
                or any(not isinstance(s, str) or not STATION.fullmatch(s) for s in station_ids)
                or len(set(station_ids)) != len(station_ids)):
            fail("snapshot_invalid_station_scope")
        if os.path.lexists(output):
            fail("snapshot_output_exists")
        receipt = read_receipt(receipt_path)
        if receipt["compressed_bytes"] > limits.compressed_bytes:
            fail("snapshot_compressed_limit")
        with regular_input(archive) as stream:
            initial = _fingerprint(stream)
            if initial[2] != receipt["compressed_bytes"]:
                fail("snapshot_digest_mismatch")
            expected = receipt["compressed_sha256"], receipt["compressed_bytes"]
            if _digest(stream, limits.compressed_bytes) != expected:
                fail("snapshot_digest_mismatch")
            if _fingerprint(stream) != initial:
                fail("snapshot_source_changed")
            stream.seek(0)
            with tempfile.TemporaryDirectory(prefix=".ghcn-snapshot-", dir=output.parent) as temp:
                candidate = Path(temp) / "candidate.sqlite"
                report = _candidate(stream, receipt, station_ids, limits, candidate)
                if _fingerprint(stream) != initial:
                    fail("snapshot_source_changed")
                os.chmod(candidate, 0o600)
                with candidate.open("rb") as completed:
                    digest, size = _digest(completed, limits.database_bytes)
                    os.fsync(completed.fileno())
                report = {**report, "candidate_sha256": digest, "candidate_bytes": size}
                # Same filesystem, atomic no-clobber. A lost acknowledgement leaves
                # a complete candidate, never a reason to overwrite on retry.
                try:
                    os.link(candidate, output)
                except FileExistsError:
                    fail("snapshot_output_exists")
                directory = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return report
    except SnapshotError:
        raise
    except (gzip.BadGzipFile, EOFError, zlib.error):
        fail("snapshot_invalid_gzip")
    except sqlite3.Error as error:
        fail("snapshot_database_limit" if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL
             else "snapshot_database_failed")
    except OSError:
        fail("snapshot_io_failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--station", action="append", required=True)
    for name in asdict(Limits(1, 1, 1, 1, 65536)):
        parser.add_argument("--max-" + name.replace("_", "-"), type=int, required=True)
    args = parser.parse_args(argv)
    try:
        limits = Limits(**{name: getattr(args, "max_" + name) for name in asdict(Limits(1, 1, 1, 1, 65536))})
        result = ingest(args.archive, args.receipt, args.output, station_ids=args.station, limits=limits)
    except SnapshotError as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
