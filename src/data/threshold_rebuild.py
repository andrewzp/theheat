"""Deterministic, bounded GHCN threshold rebuild and offline package verification.

The legacy manifest ``data/station_thresholds.version`` names a single asset
``station_thresholds.sqlite`` (957,243,392 bytes) on ``thresholds-latest``; that
release currently has no assets and the manifest carries no diff watermark.
Nothing here repairs or pretends to repair that release. It supplies the code
Root needs to rebuild a replacement from explicitly acquired local inputs:

- ``fetch_archive`` — an explicit, byte/deadline/retry-bounded, resumable fetch
  of one archive with a retained receipt. Never silent and never by default.
- ``build_plan`` — exact input identities (station/inventory/country files and
  archive), snapshot cutoff, QC policy, active-station universe and contiguous
  station partitions.
- ``build_partitions`` — one archive pass builds the selected incomplete
  partitions; a partition becomes visible only after it completes, so restarts
  skip finished partitions and never promote an unfinished one.
- ``assemble`` — the SQLite artifact (station rows + thresholds + provenance +
  explicit ``last_diff_date`` watermark), its gzip release asset, a V2
  ``station_thresholds.version`` manifest and a complete build manifest.
- ``verify_package`` / ``upload_plan`` — the actual ``threshold_artifacts`` and
  ``ghcn_runtime_inputs`` consumer contract run offline, plus an explicit upload
  plan. No upload is executed here.

Artifact integrity and loader acceptance are not scientific qualification and
thresholds are accepted station samples before the cutoff, not certified records.
"""

from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
import re
import signal
import threading
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable

from src.data import acquisition_dependencies as deps
from src.data import bounded_http
from src.data import ghcn_db
from src.data.ghcn_format import (
    ElementInventory,
    compute_thresholds,
    parse_countries_file,
    parse_inventory_file,
    parse_stations_file,
    stream_station_obs_from_tar,
)

PLAN_SCHEMA = "theheat.threshold-rebuild-plan/v1"
PARTITION_SCHEMA = "theheat.threshold-partition/v1"
BUILD_SCHEMA = "theheat.threshold-build-manifest/v1"
UPLOAD_SCHEMA = "theheat.threshold-upload-plan/v1"
RELEASE = "thresholds-latest"
DEFAULT_REPO = "andrewzp/theheat"
ARCHIVE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd_all.tar.gz"
MAX_TEXT_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024**3
MAX_PARTITIONS = 256
QC_POLICY = {
    "elements": ["TMAX", "TMIN"], "accepted_quality_flag": "blank", "missing_value": "-9999 refused",
    "nonfinite": "refused", "observations_on_or_after_cutoff": "excluded",
}
REPORTING_LIMIT = ("Accepted station samples before the cutoff; not certified records, not archive continuity, "
                   "and not a statement about dates the source calendar did not report.")


class RebuildError(deps.AcquisitionError):
    """Fixed labels only; never provider bodies or local paths."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha_file(path: Path, limit: int = MAX_ARCHIVE_BYTES) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise RebuildError("threshold_input_not_regular_file")
    digest, total = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024**2):
            total += len(chunk)
            if total > limit:
                raise RebuildError("threshold_input_too_large")
            digest.update(chunk)
    return digest.hexdigest(), total


def _identity(path: Path, limit: int = MAX_ARCHIVE_BYTES) -> dict[str, Any] | None:
    if not path.exists():
        return None
    sha, size = _sha_file(path, limit)
    return {"name": path.name, "sha256": sha, "bytes": size}


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(path: Path) -> str:
    _sha_file(path, MAX_TEXT_BYTES)
    return path.read_text(encoding="ascii", errors="replace")


# ---------------------------------------------------------------------------
# explicit bounded archive fetch (owner-run; never invoked by plan/build)
# ---------------------------------------------------------------------------

class _FetchDeadline(BaseException):
    """Interrupt blocking transport without entering the retry loop."""


def fetch_archive(dest: Path, *, session: Any, max_bytes: int, deadline_seconds: float, max_retries: int,
                  url: str = ARCHIVE_URL, clock: Callable[[], float] = time.monotonic,
                  now: Callable[[], str] = _utc_now, chunk_size: int = 1024**2,
                  expected_bytes: int | None = None, check: Callable[[], None] | None = None) -> dict[str, Any]:
    """Owner CLI absolute deadline, including delayed headers and partial chunks.

    This POSIX main-thread boundary owns its timer. Unsupported hosts/threads or
    an existing timer refuse before transport instead of pretending to bound it.
    """
    if not 0 < deadline_seconds <= 24 * 3600:
        raise RebuildError("threshold_fetch_limit_invalid")
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        raise RebuildError("threshold_owned_deadline_unavailable")
    if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise RebuildError("threshold_deadline_already_owned")
    previous = signal.getsignal(signal.SIGALRM)
    wall_deadline = time.monotonic() + deadline_seconds
    def owned_check() -> None:
        if check is not None:
            try:
                check()
            except bounded_http.TransportStop as exc:
                raise _FetchDeadline(exc.reason) from None
        if time.monotonic() >= wall_deadline:
            raise _FetchDeadline("deadline")
    def expired(_signum, _frame):
        owned_check()
    signal.signal(signal.SIGALRM, expired)
    # Poll the same cancellation authority even during blocking headers/body.
    # This owned POSIX timer changes no network retry/phase allowance.
    signal.setitimer(signal.ITIMER_REAL, min(deadline_seconds, 0.1), 0.1)
    try:
        owned_check()
        return _fetch_archive(dest, session=session, max_bytes=max_bytes, deadline_seconds=deadline_seconds,
                              max_retries=max_retries, url=url, clock=clock, now=now, chunk_size=chunk_size,
                              expected_bytes=expected_bytes, check=owned_check)
    except _FetchDeadline as exc:
        part = dest.with_name(dest.name + ".part")
        return deps.result("thresholds", "incomplete", reasons=[str(exc) or "deadline"],
                           counters={"bytes": part.stat().st_size if part.exists() else 0})
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _fetch_archive(dest: Path, *, session: Any, max_bytes: int, deadline_seconds: float, max_retries: int,
                  url: str = ARCHIVE_URL, clock: Callable[[], float] = time.monotonic,
                  now: Callable[[], str] = _utc_now, chunk_size: int = 1024**2,
                  expected_bytes: int | None = None, check: Callable[[], None] = lambda: None) -> dict[str, Any]:
    """Resumable bounded download into ``dest``; refuses redirects and never overwrites ``dest``.

    A resumed range carries ``If-Range`` with the first response's validator, so
    a file that changed on the server restarts from zero instead of splicing two
    versions. ``expected_bytes`` pins the exact planned size: a different total is
    refused and the bytes are kept aside as ``.rejected``, never promoted.
    """
    if not 1 <= max_bytes <= MAX_ARCHIVE_BYTES or not 0 < deadline_seconds <= 24 * 3600 or not 0 <= max_retries <= 5:
        raise RebuildError("threshold_fetch_limit_invalid")
    if expected_bytes is not None and not 1 <= expected_bytes <= max_bytes:
        raise RebuildError("threshold_fetch_limit_invalid")
    if dest.exists():
        raise RebuildError("threshold_archive_exists")
    part = dest.with_name(dest.name + ".part")
    validator_path = dest.with_name(dest.name + ".part.validator.json")
    started, attempts, metadata = clock(), 0, {}
    entity: dict[str, Any] = {}  # validators of the entity the retained bytes came from
    if part.exists() and validator_path.exists():
        try:
            entity = json.loads(validator_path.read_bytes()[:4096])
        except ValueError:
            entity = {}
    elif part.exists():
        part.unlink()  # bytes without a validator cannot be resumed safely
    while True:
        check()
        offset = part.stat().st_size if part.exists() else 0
        if offset > max_bytes:
            raise RebuildError("threshold_fetch_byte_limit")
        if clock() - started >= deadline_seconds:
            return deps.result("thresholds", "incomplete", reasons=["deadline"],
                               counters={"bytes": offset, "attempts": attempts})
        attempts += 1
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        validator = entity.get("ETag") or entity.get("Last-Modified")
        if offset and validator:
            headers["If-Range"] = validator
        response = None
        try:
            response = session.get(url, headers=headers, stream=True, allow_redirects=False,
                                   timeout=(30, 120))
            if response.status_code == 404:
                return deps.result("thresholds", "source_absent", reasons=["archive_not_found"],
                                   counters={"bytes": offset, "attempts": attempts})
            if response.status_code not in (200, 206):
                raise RebuildError("threshold_fetch_unexpected_status")
            if response.status_code == 200 and offset:
                offset = 0  # server ignored the range: restart from zero, never splice
                part.unlink(missing_ok=True)
            if response.status_code == 206 and not str(response.headers.get("Content-Range", "")).startswith(
                    f"bytes {offset}-"):
                raise RebuildError("threshold_fetch_range_mismatch")
            length = response.headers.get("Content-Length")
            if length is not None and offset + int(length) > max_bytes:
                return deps.result("thresholds", "incomplete", reasons=["byte_limit"],
                                   counters={"bytes": offset, "attempts": attempts})
            metadata = {key: response.headers.get(key) for key in ("Last-Modified", "ETag")}
            if response.status_code == 200:
                entity = dict(metadata)
                _atomic_bytes(validator_path, _canonical(entity))
            written = offset
            with part.open("ab") as handle:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    check()
                    written += len(chunk)
                    if written > max_bytes:
                        return deps.result("thresholds", "incomplete", reasons=["byte_limit"],
                                           counters={"bytes": written - len(chunk), "attempts": attempts})
                    handle.write(chunk)
                    if clock() - started >= deadline_seconds:
                        return deps.result("thresholds", "incomplete", reasons=["deadline"],
                                           counters={"bytes": written, "attempts": attempts})
            if length is not None and written != offset + int(length):
                raise ConnectionError("short body")
            break
        except RebuildError:
            raise
        except Exception:  # noqa: BLE001 - transport failure; resume from the retained part
            if attempts > max_retries:
                return deps.result("thresholds", "incomplete", reasons=["transport_failures"],
                                   counters={"bytes": part.stat().st_size if part.exists() else 0,
                                             "attempts": attempts})
        finally:
            if response is not None and hasattr(response, "close"):
                response.close()
    sha, size = _sha_file(part)
    if expected_bytes is not None and size != expected_bytes:
        os.replace(part, dest.with_name(dest.name + ".rejected"))
        validator_path.unlink(missing_ok=True)
        return deps.result("thresholds", "product_invalid", reasons=["archive_size_differs_from_plan"],
                           counters={"bytes": size, "attempts": attempts})
    check()
    os.replace(part, dest)
    validator_path.unlink(missing_ok=True)
    receipt = {"url": url, "name": dest.name, "sha256": sha, "bytes": size, "retrieved_at": now(),
               "last_modified": metadata.get("Last-Modified"), "etag": metadata.get("ETag"), "attempts": attempts}
    _atomic_bytes(dest.with_name(dest.name + ".receipt.json"), _canonical(receipt))
    return deps.result("thresholds", "ready", source=receipt, counters={"bytes": size, "attempts": attempts})


# ---------------------------------------------------------------------------
# 02.4 deterministic plan, partitions and assembly
# ---------------------------------------------------------------------------

def _inventory(inventory_text: str) -> dict[str, list[ElementInventory]]:
    by_station: dict[str, list[ElementInventory]] = {}
    for row in parse_inventory_file(inventory_text):
        by_station.setdefault(row.station_id, []).append(row)
    return by_station


def _active(rows: list[ElementInventory], cutoff_year: int) -> bool:
    return any(row.element in {"TMAX", "TMIN"} and row.last_year >= cutoff_year for row in rows)


def _plan_identity(plan: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({k: v for k, v in plan.items() if k != "plan_sha256"})).hexdigest()


def build_plan(*, stations: Path, inventory: Path, countries: Path, archive: Path, snapshot_date: str,
               partitions: int, active_year_cutoff: int | None = None,
               archive_receipt: Path | None = None, source_version: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        snapshot = date.fromisoformat(snapshot_date)
    except (TypeError, ValueError):
        raise RebuildError("threshold_snapshot_date_invalid") from None
    if snapshot.isoformat() != snapshot_date:
        raise RebuildError("threshold_snapshot_date_invalid")
    if not 1 <= partitions <= MAX_PARTITIONS:
        raise RebuildError("threshold_partition_count_invalid")
    cutoff_year = snapshot.year - 1 if active_year_cutoff is None else active_year_cutoff
    if not 1800 <= cutoff_year <= snapshot.year:
        raise RebuildError("threshold_active_cutoff_invalid")
    missing = [name for name, path in (("stations", stations), ("inventory", inventory), ("countries", countries),
                                       ("archive", archive)) if not path.exists()]
    texts = {"stations": stations, "inventory": inventory, "countries": countries}
    inputs: dict[str, Any] = {name: _identity(path, MAX_TEXT_BYTES) for name, path in texts.items()}
    inputs["archive"] = _identity(archive)
    receipt = None
    if archive_receipt is not None and archive_receipt.exists():
        receipt = json.loads(archive_receipt.read_bytes()[:65536])
        if inputs["archive"] is None or receipt.get("sha256") != inputs["archive"]["sha256"]:
            raise RebuildError("threshold_archive_receipt_mismatch")
    universe: list[str] = []
    if not {"stations", "inventory"} & set(missing):
        by_station = _inventory(_text(inventory))
        known = {meta.station_id for meta in parse_stations_file(_text(stations))}
        universe = sorted(sid for sid in known if _active(by_station.get(sid, []), cutoff_year))
    size = -(-len(universe) // partitions) if universe else 0
    chunks = [universe[i:i + size] for i in range(0, len(universe), size)] if size else []
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA, "source_product": "noaa-ghcn-daily-v2", "release": RELEASE,
        "inputs": inputs, "missing_inputs": missing,
        "archive_retrieval": None if receipt is None else {k: receipt.get(k) for k in (
            "url", "retrieved_at", "last_modified", "etag")},
        "snapshot_date": snapshot_date, "comparison_before": snapshot_date,
        "watermark_last_diff_date": snapshot_date, "snapshot_date_basis": "operator_declared",
        "active_year_cutoff": cutoff_year, "qc_policy": QC_POLICY, "reporting_limit": REPORTING_LIMIT,
        "active_stations": len(universe),
        "partitions": [{"index": i, "first": chunk[0], "last": chunk[-1], "stations": len(chunk),
                        "station_ids_sha256": hashlib.sha256("\n".join(chunk).encode()).hexdigest()}
                       for i, chunk in enumerate(chunks)],
    }
    if source_version is not None:
        # The pinned GHCN-Daily version the inputs were fetched under (ghcnd-version.txt).
        plan["source_version"] = {k: source_version.get(k) for k in (
            "version", "update_started_at", "reprocessed_version", "text_sha256")}
        if snapshot > date.fromisoformat(str(source_version.get("update_started_at", ""))[:10] or snapshot_date):
            raise RebuildError("threshold_snapshot_after_source_version")
    plan["plan_sha256"] = _plan_identity(plan)
    return plan


def _check_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA or plan.get("plan_sha256") != _plan_identity(plan):
        raise RebuildError("threshold_plan_invalid_or_altered")
    if plan["missing_inputs"]:
        raise RebuildError("threshold_plan_inputs_missing")
    return plan


def _check_inputs(plan: dict[str, Any], paths: dict[str, Path], names: tuple[str, ...]) -> None:
    for name in names:
        limit = MAX_ARCHIVE_BYTES if name == "archive" else MAX_TEXT_BYTES
        if _identity(paths[name], limit) != plan["inputs"][name]:
            raise RebuildError(f"threshold_{name}_changed_since_plan")


def _partition_ids(plan: dict[str, Any], paths: dict[str, Path]) -> list[list[str]]:
    by_station = _inventory(_text(paths["inventory"]))
    known = {meta.station_id for meta in parse_stations_file(_text(paths["stations"]))}
    universe = sorted(sid for sid in known if _active(by_station.get(sid, []), plan["active_year_cutoff"]))
    out = []
    for entry in plan["partitions"]:
        ids = [sid for sid in universe if entry["first"] <= sid <= entry["last"]]
        if hashlib.sha256("\n".join(ids).encode()).hexdigest() != entry["station_ids_sha256"]:
            raise RebuildError("threshold_partition_universe_changed")
        out.append(ids)
    return out


def _receipt_path(work_dir: Path, index: int) -> Path:
    return work_dir / f"part-{index:04d}.json"


def partition_state(plan: dict[str, Any], work_dir: Path) -> dict[int, str]:
    """complete only when the receipt binds this plan and the partition bytes still match."""
    states = {}
    for entry in plan["partitions"]:
        receipt, database = _receipt_path(work_dir, entry["index"]), work_dir / f"part-{entry['index']:04d}.sqlite"
        state = "pending"
        if receipt.exists() and database.exists():
            try:
                record = json.loads(receipt.read_bytes()[:65536])
                if (record.get("schema") == PARTITION_SCHEMA and record.get("plan_sha256") == plan["plan_sha256"]
                        and record.get("station_ids_sha256") == entry["station_ids_sha256"]
                        and record.get("sha256") == _sha_file(database)[0]):
                    state = "complete"
            except (ValueError, deps.AcquisitionError):
                state = "pending"
        states[entry["index"]] = state
    return states


def build_partitions(plan: dict[str, Any], *, paths: dict[str, Path], work_dir: Path,
                     select: list[int] | None = None, deadline_seconds: float = 6 * 3600,
                     clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Single archive pass for the selected pending partitions; publish each only when complete."""
    _check_plan(plan)
    _check_inputs(plan, paths, ("stations", "inventory", "archive"))
    if not 1 <= deadline_seconds <= 24 * 3600:
        raise RebuildError("threshold_deadline_invalid")
    work_dir.mkdir(parents=True, exist_ok=True)
    for stale in work_dir.glob("*.building*"):
        stale.unlink()  # an interrupted partition is never promoted
    states = partition_state(plan, work_dir)
    chosen = sorted(i for i in (select if select is not None else states) if states.get(i) == "pending")
    if not chosen:
        return deps.result("thresholds", "ready", reasons=["no_pending_partitions"],
                           counters={"complete": sum(s == "complete" for s in states.values()), "built": 0})
    ids = _partition_ids(plan, paths)
    owner = {sid: index for index in chosen for sid in ids[index]}
    retrieved_at = (plan.get("archive_retrieval") or {}).get("retrieved_at")
    before = date.fromisoformat(plan["comparison_before"])
    started = clock()
    connections = {}
    counts = {index: {"written": 0, "without_samples": 0} for index in chosen}
    try:
        for index in chosen:
            building = work_dir / f"part-{index:04d}.sqlite.building"
            building.unlink(missing_ok=True)
            conn = sqlite3.connect(building)
            conn.executescript(ghcn_db._DDL)
            connections[index] = conn
        seen: set[str] = set()
        with paths["archive"].open("rb") as handle:
            for station_id, observations in stream_station_obs_from_tar(handle, station_ids=frozenset(owner)):
                if clock() - started >= deadline_seconds:
                    raise TimeoutError
                if station_id in seen:
                    raise RebuildError("threshold_archive_duplicate_station")
                seen.add(station_id)
                thresholds = compute_thresholds(observations, before=before, retrieved_at=retrieved_at,
                                                source_revision=plan["inputs"]["archive"]["sha256"])
                index = owner[station_id]
                if thresholds is None:
                    counts[index]["without_samples"] += 1
                    continue
                ghcn_db.upsert_thresholds(connections[index], thresholds)
                counts[index]["written"] += 1
        for index in chosen:
            counts[index]["without_samples"] += len(set(ids[index]) - seen)
            conn = connections.pop(index)
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.close()
            building = work_dir / f"part-{index:04d}.sqlite.building"
            final = work_dir / f"part-{index:04d}.sqlite"
            os.replace(building, final)
            entry = plan["partitions"][index]
            _atomic_bytes(_receipt_path(work_dir, index), _canonical({
                "schema": PARTITION_SCHEMA, "plan_sha256": plan["plan_sha256"], "index": index,
                "station_ids_sha256": entry["station_ids_sha256"], "stations": entry["stations"],
                **counts[index], "sha256": _sha_file(final)[0]}))
    except TimeoutError:
        _abandon(connections, work_dir)
        return deps.result("thresholds", "incomplete", reasons=["deadline"],
                           counters={"built": 0, "pending": len(chosen)})
    except BaseException:
        _abandon(connections, work_dir)
        raise
    states = partition_state(plan, work_dir)
    pending = sorted(i for i, s in states.items() if s != "complete")
    return deps.result("thresholds", "incomplete" if pending else "ready",
                       reasons=["partitions_pending"] if pending else [],
                       counters={"built": len(chosen), "pending": len(pending),
                                 "complete": len(states) - len(pending)})


def _abandon(connections: dict[int, sqlite3.Connection], work_dir: Path) -> None:
    for conn in connections.values():
        conn.close()
    for stale in work_dir.glob("*.building*"):
        stale.unlink()


def assemble(plan: dict[str, Any], *, paths: dict[str, Path], work_dir: Path, out_dir: Path,
             now: Callable[[], str] = _utc_now) -> dict[str, Any]:
    """Build the artifact, gzip asset, V2 manifest and build manifest from complete partitions only."""
    from scripts import threshold_artifacts as artifacts

    _check_plan(plan)
    _check_inputs(plan, paths, ("stations", "inventory", "countries", "archive"))
    states = partition_state(plan, work_dir)
    if any(state != "complete" for state in states.values()) or not states:
        raise RebuildError("threshold_partitions_incomplete")
    target = out_dir / "station_thresholds.sqlite"
    if target.exists() or (out_dir / "station_thresholds.version").exists():
        raise RebuildError("threshold_output_exists")
    out_dir.mkdir(parents=True, exist_ok=True)
    building = out_dir / "station_thresholds.sqlite.building"
    building.unlink(missing_ok=True)
    stations = sorted(parse_stations_file(_text(paths["stations"])), key=lambda meta: meta.station_id)
    by_station = _inventory(_text(paths["inventory"]))
    countries = parse_countries_file(_text(paths["countries"]))
    try:
        with closing(sqlite3.connect(building)) as conn:
            conn.executescript(ghcn_db._DDL)
            for meta in stations:
                ghcn_db.upsert_station(conn, meta, countries.get(meta.country_code_inferred(), ""),
                                       by_station.get(meta.station_id, []), plan["active_year_cutoff"])
            conn.commit()
            receipts = []
            for entry in plan["partitions"]:
                part = work_dir / f"part-{entry['index']:04d}.sqlite"
                conn.execute("ATTACH DATABASE ? AS part", (str(part.resolve()),))
                conn.execute("INSERT INTO thresholds SELECT station_id,kind,month,day,value_c,record_year "
                             "FROM part.thresholds ORDER BY station_id,kind,month,day")
                conn.execute("INSERT INTO threshold_provenance SELECT station_id,payload_json "
                             "FROM part.threshold_provenance ORDER BY station_id")
                conn.commit()
                conn.execute("DETACH DATABASE part")
                receipts.append(json.loads(_receipt_path(work_dir, entry["index"]).read_bytes()))
            ghcn_db.set_meta(conn, "last_diff_date", plan["watermark_last_diff_date"])
            ghcn_db.set_meta(conn, "rebuild_plan_sha256", plan["plan_sha256"])
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("VACUUM")
            coverage = {
                "stations": conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0],
                "active_stations": conn.execute("SELECT COUNT(*) FROM stations WHERE is_active=1").fetchone()[0],
                "active_with_thresholds": conn.execute(
                    "SELECT COUNT(*) FROM stations WHERE is_active=1 AND station_id IN "
                    "(SELECT DISTINCT station_id FROM thresholds)").fetchone()[0],
                "threshold_rows": conn.execute("SELECT COUNT(*) FROM thresholds").fetchone()[0],
                "orphan_threshold_stations": conn.execute(
                    "SELECT COUNT(DISTINCT station_id) FROM thresholds WHERE station_id NOT IN "
                    "(SELECT station_id FROM stations)").fetchone()[0],
            }
            sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]
        for suffix in ("-wal", "-journal"):
            Path(str(building) + suffix).unlink(missing_ok=True)
        os.replace(building, target)
    except BaseException:
        building.unlink(missing_ok=True)
        raise
    stats = artifacts.database_stats(target)
    sha, size = artifacts.digest(target)
    asset = out_dir / f"station_thresholds-{sha}.sqlite.gz"
    with target.open("rb") as source, asset.open("xb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            while chunk := source.read(1024**2):
                compressed.write(chunk)
    asset_sha, asset_size = artifacts.digest(asset, artifacts.MAX_ASSET_BYTES)
    manifest = {"release": RELEASE, "sha256": sha, "bytes": str(size), **stats, "format": "sqlite-gzip",
                "asset": asset.name, "asset_sha256": asset_sha, "asset_bytes": str(asset_size)}
    _atomic_bytes(out_dir / "station_thresholds.version",
                  "".join(f"{key}={value}\n" for key, value in manifest.items()).encode("ascii"))
    build = {"schema": BUILD_SCHEMA, "plan_sha256": plan["plan_sha256"], "inputs": plan["inputs"],
             "source_version": plan.get("source_version"),
             "archive_retrieval": plan["archive_retrieval"], "snapshot_date": plan["snapshot_date"],
             "comparison_before": plan["comparison_before"], "snapshot_date_basis": plan["snapshot_date_basis"],
             "active_year_cutoff": plan["active_year_cutoff"], "qc_policy": plan["qc_policy"],
             "reporting_limit": plan["reporting_limit"], "partitions": receipts, "coverage": coverage,
             "database": {"name": target.name, "sha256": sha, "bytes": size, "sqlite_version": sqlite_version},
             "asset": {"name": asset.name, "sha256": asset_sha, "bytes": asset_size},
             "manifest": dict(manifest), "assembled_at": now(),
             "scientific_qualification": "not_established_by_artifact_integrity"}
    _atomic_bytes(out_dir / "build-manifest.json", _canonical(build))
    return build


# ---------------------------------------------------------------------------
# 02.5 offline package verification and explicit upload plan
# ---------------------------------------------------------------------------

def _release_disposition(release_assets: Any, name: str, sha: str, size: int) -> dict[str, Any]:
    """Classify an operator-saved ``gh api repos/<repo>/releases/tags/<tag>`` document."""
    if release_assets is None:
        return {"state": "unknown_requires_owner_read"}
    if not isinstance(release_assets, dict) or not isinstance(release_assets.get("assets"), list):
        return {"state": "release_metadata_invalid"}
    rows = [row for row in release_assets["assets"] if isinstance(row, dict)]
    matches = [row for row in rows if row.get("name") == name]
    base = {"asset_count": len(rows), "release_empty": not rows}
    if len(matches) > 1:
        return {**base, "state": "asset_identity_conflict"}
    if not matches:
        return {**base, "state": "asset_absent_upload_required"}
    row = matches[0]
    if row.get("state") == "uploaded" and row.get("size") == size and row.get("digest") == f"sha256:{sha}":
        return {**base, "state": "asset_present_verified"}
    return {**base, "state": "asset_identity_conflict"}


def verify_package(database: Path, manifest_path: Path, *, asset: Path | None = None,
                   build_manifest: Path | None = None, release_assets: Any = None) -> dict[str, Any]:
    """The actual ensure/loader contract offline: manifest, digest, schema, coverage, cutoff, consumer read."""
    from scripts import threshold_artifacts as artifacts
    from src.storage import ghcn_runtime_inputs

    reasons: list[str] = []
    try:
        manifest = artifacts.read_manifest(manifest_path)
    except (artifacts.ArtifactError, OSError):
        return deps.result("thresholds", "product_invalid", reasons=["invalid_threshold_manifest"])
    name, asset_sha, asset_size = artifacts._asset(manifest)
    disposition = _release_disposition(release_assets, name, asset_sha, asset_size)
    if not database.exists():
        status = "source_absent" if disposition.get("state") != "asset_present_verified" else "incomplete"
        return deps.result("thresholds", status, reasons=["threshold_database_absent",
                                                          "release_" + disposition["state"]],
                           source={"release": manifest["release"], "required_asset": name,
                                   "required_asset_bytes": asset_size, "disposition": disposition})
    try:
        stats = artifacts.verify_database(database, manifest)
    except (artifacts.ArtifactError, OSError) as error:
        return deps.result("thresholds", "product_invalid", reasons=[str(error)])
    coverage: dict[str, Any] = {}
    try:
        with ghcn_db.open_db_readonly(database) as conn:
            coverage = {
                "active_stations": int(stats["active_stations"]),
                "active_with_thresholds": conn.execute(
                    "SELECT COUNT(*) FROM stations WHERE is_active=1 AND station_id IN "
                    "(SELECT DISTINCT station_id FROM thresholds)").fetchone()[0],
                "orphan_threshold_stations": conn.execute(
                    "SELECT COUNT(DISTINCT station_id) FROM thresholds WHERE station_id NOT IN "
                    "(SELECT station_id FROM stations)").fetchone()[0],
                "stations_without_provenance": conn.execute(
                    "SELECT COUNT(DISTINCT station_id) FROM thresholds WHERE station_id NOT IN "
                    "(SELECT station_id FROM threshold_provenance)").fetchone()[0],
                "unknown_kinds": conn.execute(
                    "SELECT COUNT(*) FROM thresholds WHERE kind NOT IN ('all_time_max','all_time_min',"
                    "'monthly_max','monthly_min','calendar_date_max','calendar_date_min',"
                    "'climatological_mean','climatological_mean_min')").fetchone()[0],
            }
            cutoffs = set()
            for (payload,) in conn.execute("SELECT payload_json FROM threshold_provenance"):
                record = json.loads(payload)
                cutoffs.add(record.get("comparison_before") if isinstance(record, dict) else "invalid")
    except (ValueError, sqlite3.Error):
        return deps.result("thresholds", "product_invalid", reasons=["threshold_schema_unrecognized"])
    if coverage["orphan_threshold_stations"] or coverage["stations_without_provenance"] or coverage["unknown_kinds"]:
        reasons.append("threshold_rows_unbound")
    if not coverage["active_with_thresholds"]:
        reasons.append("threshold_station_coverage_empty")
    if len(cutoffs) != 1 or None in cutoffs or "invalid" in cutoffs:
        reasons.append("threshold_cutoff_not_uniform")
    if not stats["last_diff_date"]:
        reasons.append("threshold_baseline_lineage_unknown")
    build = None
    if build_manifest is not None:
        build = json.loads(build_manifest.read_bytes()[: 4 * 1024**2])
        if (build.get("schema") != BUILD_SCHEMA or build.get("manifest") != manifest
                or cutoffs != {build.get("comparison_before")}
                or stats["last_diff_date"] != build.get("snapshot_date")):
            reasons.append("threshold_build_manifest_mismatch")
    if asset is not None:
        if asset.name != name:
            reasons.append("threshold_asset_filename_mismatch")
        elif artifacts.digest(asset, artifacts.MAX_ASSET_BYTES if "format" in manifest else artifacts.MAX_DB_BYTES) \
                != (asset_sha, asset_size):
            reasons.append("threshold_asset_digest_mismatch")
        elif manifest.get("format") == "sqlite-gzip":
            expanded = hashlib.sha256()
            total = 0
            with gzip.open(asset, "rb") as source:
                while chunk := source.read(1024**2):
                    total += len(chunk)
                    if total > int(manifest["bytes"]):
                        break
                    expanded.update(chunk)
            if (expanded.hexdigest(), total) != (manifest["sha256"], int(manifest["bytes"])):
                reasons.append("threshold_asset_does_not_expand_to_database")
    if set(reasons) <= {"threshold_baseline_lineage_unknown"}:
        manifest_sha = artifacts.digest(manifest_path, 4096)[0]
        baseline = ghcn_runtime_inputs.Baseline(database, manifest_path, manifest["sha256"], manifest_sha)
        try:
            with baseline.reader() as (_target, descriptor):
                coverage["consumer_threshold_rows_sha256"] = descriptor["threshold_rows_sha256"]
        except Exception as error:  # noqa: BLE001 - the consumer's refusal is the finding
            reasons.append("consumer_refused:" + str(error)[:64])
    status = "product_invalid" if reasons and reasons != ["threshold_baseline_lineage_unknown"] else (
        "incomplete" if reasons else "ready")
    return deps.result("thresholds", status, reasons=reasons,
                       source={"release": manifest["release"], "required_asset": name,
                               "required_asset_bytes": asset_size, "disposition": disposition},
                       product={"manifest": manifest, "coverage": coverage,
                                "comparison_before": sorted(c for c in cutoffs if isinstance(c, str))},
                       observed=int(stats["active_stations"]), promoted=int(coverage.get("active_with_thresholds", 0)))


def upload_plan(verification: dict[str, Any], *, asset: Path, manifest_path: Path, installed_manifest: Path,
                repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Explicit owner steps; nothing is executed. The prior manifest stays the rollback reference."""
    from scripts import threshold_artifacts as artifacts

    if verification.get("status") != "ready":
        raise RebuildError("threshold_package_not_verified")
    manifest = verification["product"]["manifest"]
    previous = None
    if installed_manifest.exists():
        previous_fields = artifacts.read_manifest(installed_manifest)
        p_name, p_sha, p_size = artifacts._asset(previous_fields)
        previous = {"manifest_sha256": artifacts.digest(installed_manifest, 4096)[0], "fields": previous_fields,
                    "required_asset": p_name, "required_asset_bytes": p_size, "required_asset_sha256": p_sha}
    disposition = verification["source"]["disposition"]
    if disposition.get("state") == "asset_identity_conflict":
        raise RebuildError("threshold_asset_identity_conflict")
    return {
        "schema": UPLOAD_SCHEMA, "executed": False, "performed_by": "root",
        "release": manifest["release"], "repo": repo,
        "asset": {"path": str(asset), "name": manifest["asset"], "sha256": manifest["asset_sha256"],
                  "bytes": int(manifest["asset_bytes"])},
        "release_disposition": disposition,
        "steps": [
            {"action": "read_release", "argv": ["gh", "api", f"repos/{repo}/releases/tags/{manifest['release']}"],
             "expect": "no asset with this name, or the identical verified digest"},
            {"action": "upload", "argv": ["gh", "release", "upload", manifest["release"], str(asset), "--repo", repo],
             "skip_when": "asset_present_verified", "never": ["--clobber", "delete", "rename", "second upload"]},
            {"action": "verify_remote", "expect": {"name": manifest["asset"], "state": "uploaded",
                                                   "size": int(manifest["asset_bytes"]),
                                                   "digest": f"sha256:{manifest['asset_sha256']}"}},
            {"action": "install_manifest", "copy": [str(manifest_path), str(installed_manifest)]},
            {"action": "consumer_check", "argv": ["python", "-m", "scripts.threshold_artifacts", "ensure",
                                                  "--repo", repo], "on": "a clean cache"},
        ],
        "rollback": previous and {"restore_manifest_sha256": previous["manifest_sha256"],
                                  "previous_required_asset": previous["required_asset"],
                                  "previous_required_asset_bytes": previous["required_asset_bytes"],
                                  "note": "restoring the prior manifest restores its prior (currently absent) asset "
                                          "requirement; it does not recreate that asset"},
        "preserved_evidence": "the prior release state is recorded above as read; this plan does not repair it",
    }


# ---------------------------------------------------------------------------
# primary-source input resolution: a byte-pinned, versioned fetch plan
# ---------------------------------------------------------------------------

FETCH_PLAN_SCHEMA = "theheat.threshold-fetch-plan/v1"
INPUTS_SCHEMA = "theheat.threshold-inputs/v1"
INSTALL_SCHEMA = "theheat.threshold-install/v1"
BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/"
INPUT_ASSETS = {"version": "ghcnd-version.txt", "countries": "ghcnd-countries.txt",
                "stations": "ghcnd-stations.txt", "inventory": "ghcnd-inventory.txt",
                "archive": "ghcnd_all.tar.gz"}
TEXT_ROLES = ("version", "countries", "stations", "inventory")
UPDATE_LAG_DAYS = 4  # scripts.threshold_artifacts.pending_diff_dates default lag
_LISTING_ROW = re.compile(
    r'<td><a href="(?P<name>[A-Za-z0-9_.-]+)">(?P=name)</a></td>\s*'
    r'<td align="right">(?P<modified>\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td>\s*'
    r'<td align="right">(?P<bytes>\d{1,13})</td>')
_VERSION = re.compile(r"current version of GHCN Daily is (?P<version>\d+\.\d+-(?:upd|por)-(?P<stamp>\d{10}))")
_POR = re.compile(r"last fully reprocessed version: (?P<por>\d+\.\d+-por-\d{10})")


def parse_listing(html: bytes) -> dict[str, dict[str, Any]]:
    """NCEI directory index rows -> name: {listing_modified, bytes}. Listing time is display metadata only."""
    try:
        text = html.decode("utf-8")
    except UnicodeDecodeError:
        raise RebuildError("threshold_listing_unreadable") from None
    rows: dict[str, dict[str, Any]] = {}
    for match in _LISTING_ROW.finditer(text):
        if match["name"] in rows:
            raise RebuildError("threshold_listing_ambiguous")
        rows[match["name"]] = {"listing_modified": match["modified"], "bytes": int(match["bytes"])}
    return rows


def parse_version(raw: bytes) -> dict[str, Any]:
    """``ghcnd-version.txt`` -> the exact dataset version pin and its update start."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise RebuildError("threshold_version_unreadable") from None
    match = _VERSION.search(text)
    if not match:
        raise RebuildError("threshold_version_unrecognized")
    stamp = match["stamp"]
    try:
        started = datetime(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]), int(stamp[8:10]), tzinfo=timezone.utc)
    except ValueError:
        raise RebuildError("threshold_version_unrecognized") from None
    por = _POR.search(text)
    return {"version": match["version"], "update_started_at": started.isoformat().replace("+00:00", "Z"),
            "reprocessed_version": por["por"] if por else None,
            "text_sha256": hashlib.sha256(raw).hexdigest(), "text_bytes": len(raw)}


def resolve_fetch_plan(listing: Any, version: Any, *, base_url: str = BASE_URL,
                       lag_days: int = UPDATE_LAG_DAYS) -> dict[str, Any]:
    """Pin every input's exact size and the dataset version from the primary NOAA index.

    ``listing``/``version`` are ``bounded_http.Response`` objects (their bytes and
    retrieval receipts). The suggested snapshot leaves the incremental updater's
    publication lag before the version's update start, so late reports are not
    frozen into the baseline and the weekly refresh can continue from it.
    """
    if not base_url.endswith("/"):
        raise RebuildError("threshold_base_url_invalid")
    rows = parse_listing(listing.body)
    pin = parse_version(version.body)
    assets = {}
    for role, name in INPUT_ASSETS.items():
        row = rows.get(name)
        if row is None:
            raise RebuildError("threshold_listing_asset_missing")
        limit = MAX_ARCHIVE_BYTES if role == "archive" else MAX_TEXT_BYTES
        if not 1 <= row["bytes"] <= limit:
            raise RebuildError("threshold_listing_asset_size_invalid")
        assets[role] = {"name": name, "url": base_url + name, **row}
    if assets["version"]["bytes"] != pin["text_bytes"]:
        raise RebuildError("threshold_version_changed_during_resolve")
    started = date.fromisoformat(pin["update_started_at"][:10])
    plan: dict[str, Any] = {
        "schema": FETCH_PLAN_SCHEMA, "source_product": "noaa-ghcn-daily-v2", "base_url": base_url,
        "source_version": pin, "assets": assets,
        "resolved_from": {"listing": listing.receipt(), "version": version.receipt()},
        "suggested_snapshot_date": (started - timedelta(days=lag_days)).isoformat(),
        "snapshot_rule": f"version update start date minus the {lag_days}-day publication lag",
        "limits": {"text_transfer_bytes": sum(assets[r]["bytes"] for r in TEXT_ROLES) + 64 * 1024 * 8,
                   "archive_bytes": assets["archive"]["bytes"]},
        "reporting_limit": REPORTING_LIMIT,
    }
    plan["plan_sha256"] = _plan_identity(plan)
    return plan


def resolve_inputs(transport: Any, *, base_url: str = BASE_URL) -> dict[str, Any]:
    """Two bounded GETs: the directory index and the version file. No data asset is read."""
    listing = transport.get(base_url)
    version = transport.get(base_url + INPUT_ASSETS["version"])
    return resolve_fetch_plan(listing, version, base_url=base_url)


def _check_fetch_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != FETCH_PLAN_SCHEMA \
            or plan.get("plan_sha256") != _plan_identity(plan):
        raise RebuildError("threshold_fetch_plan_invalid_or_altered")
    return plan


def fetch_inputs(plan: dict[str, Any], dest: Path, *, transport: Any, archive_session: Any,
                 archive_deadline_seconds: float, max_retries: int,
                 now: Callable[[], str] = _utc_now) -> dict[str, Any]:
    """Fetch exactly the planned bytes into a new inputs directory, then bind them in one manifest.

    The version file is read first and again after the archive, and both reads
    must equal the pinned version text, so an input set never mixes two
    GHCN-Daily versions. Text inputs go through the
    owned bounded transport and must match the planned size before they are
    written. The archive uses the range-resumable owner fetch with ``If-Range``
    and the exact planned size. Existing different bytes are never overwritten;
    the inputs manifest lands last, so a partial directory is never "inputs".
    """
    _check_fetch_plan(plan)
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / "inputs-manifest.json"
    if manifest_path.exists():
        raise RebuildError("threshold_inputs_exist")
    receipts: dict[str, Any] = {}
    for role in TEXT_ROLES:
        asset = plan["assets"][role]
        target = dest / asset["name"]
        response = transport.get(asset["url"])
        if len(response.body) != asset["bytes"]:
            raise RebuildError("threshold_asset_changed_since_plan")
        if role == "version" and hashlib.sha256(response.body).hexdigest() != plan["source_version"]["text_sha256"]:
            raise RebuildError("threshold_version_changed_since_plan")
        if target.exists() and target.read_bytes() != response.body:
            raise RebuildError("threshold_input_exists_with_other_bytes")
        transport.check()
        _atomic_bytes(target, response.body)
        receipts[role] = {**response.receipt(), "name": asset["name"], "retrieved_at": now()}
    archive = plan["assets"]["archive"]
    archive_path = dest / archive["name"]
    if archive_path.exists():
        sha, size = _sha_file(archive_path)
        prior = json.loads((dest / (archive["name"] + ".receipt.json")).read_bytes()[:65536]) \
            if (dest / (archive["name"] + ".receipt.json")).exists() else {}
        if size != archive["bytes"] or prior.get("sha256") != sha:
            raise RebuildError("threshold_input_exists_with_other_bytes")
        outcome = deps.result("thresholds", "ready", source=prior)
    else:
        transport.check()
        outcome = fetch_archive(archive_path, session=archive_session, max_bytes=archive["bytes"],
                                expected_bytes=archive["bytes"],
                                deadline_seconds=min(archive_deadline_seconds, transport.remaining()),
                                max_retries=max_retries, url=archive["url"], now=now, check=transport.check)
    if outcome["status"] != "ready":
        return deps.result("thresholds", outcome["status"], reasons=outcome["reasons"],
                           source={"fetch_plan_sha256": plan["plan_sha256"], "text_inputs": sorted(receipts)},
                           counters={**outcome.get("counters", {}), "transport": transport.snapshot()})
    receipts["archive"] = {**outcome["source"], "name": archive["name"]}
    # The archive is regenerated with each dataset update: re-read the version pin after it,
    # so an input set whose archive may belong to a later version is never bound.
    closing_version = transport.get(plan["assets"]["version"]["url"])
    if hashlib.sha256(closing_version.body).hexdigest() != plan["source_version"]["text_sha256"]:
        return deps.result("thresholds", "product_invalid", reasons=["version_changed_during_fetch"],
                           source={"fetch_plan_sha256": plan["plan_sha256"]},
                           counters={"transport": transport.snapshot()})
    document = {"schema": INPUTS_SCHEMA, "fetch_plan_sha256": plan["plan_sha256"],
                "source_product": plan["source_product"], "source_version": plan["source_version"],
                "suggested_snapshot_date": plan["suggested_snapshot_date"],
                "inputs": {role: {"name": r["name"], "sha256": r["sha256"], "bytes": r["bytes"],
                                  "url": r.get("url"), "last_modified": r.get("last_modified"),
                                  "etag": r.get("etag"), "retrieved_at": r.get("retrieved_at")}
                           for role, r in receipts.items()},
                "completed_at": now()}
    transport.check()
    _atomic_bytes(manifest_path, _canonical(document))
    return deps.result("thresholds", "ready", source={"fetch_plan_sha256": plan["plan_sha256"],
                                                     "source_version": plan["source_version"]["version"]},
                       product={"inputs_manifest": manifest_path.name,
                                "inputs": {role: document["inputs"][role]["sha256"] for role in document["inputs"]}},
                       counters={"transport": transport.snapshot()})


def verify_inputs(dest: Path, *, roles: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Re-hash every bound input (or the named ``roles``); any change since the fetch refuses the set."""
    path = dest / "inputs-manifest.json"
    if not path.is_file():
        raise RebuildError("threshold_inputs_manifest_missing")
    document = json.loads(path.read_bytes()[:1024 * 1024])
    if not isinstance(document, dict) or document.get("schema") != INPUTS_SCHEMA:
        raise RebuildError("threshold_inputs_manifest_invalid")
    for role, entry in document["inputs"].items():
        if roles is not None and role not in roles:
            continue
        limit = MAX_ARCHIVE_BYTES if role == "archive" else MAX_TEXT_BYTES
        if _identity(dest / entry["name"], limit) != {"name": entry["name"], "sha256": entry["sha256"],
                                                      "bytes": entry["bytes"]}:
            raise RebuildError(f"threshold_{role}_changed_since_fetch")
    return document


def package(inputs_dir: Path, *, work_dir: Path, out_dir: Path, partitions: int, deadline_seconds: float,
            snapshot_date: str | None = None, release_assets: Any = None, installed_manifest: Path,
            repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Offline: verified inputs -> plan -> all partitions -> assembled package -> verification -> upload plan.

    Every step is the existing reviewed one and is resumable: an identical plan is
    reused, finished partitions are skipped, an assembled package from the same
    plan is verified rather than rebuilt. Nothing is uploaded or installed.
    """
    document = verify_inputs(inputs_dir)
    names = {role: inputs_dir / entry["name"] for role, entry in document["inputs"].items()}
    paths = {"stations": names["stations"], "inventory": names["inventory"], "countries": names["countries"],
             "archive": names["archive"]}
    work_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = inputs_dir / (document["inputs"]["archive"]["name"] + ".receipt.json")
    plan = build_plan(stations=paths["stations"], inventory=paths["inventory"], countries=paths["countries"],
                      archive=paths["archive"], snapshot_date=snapshot_date or document["suggested_snapshot_date"],
                      partitions=partitions, archive_receipt=receipt_path if receipt_path.exists() else None,
                      source_version=document["source_version"])
    plan_path = work_dir / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_bytes()).get("plan_sha256") != plan["plan_sha256"]:
        raise RebuildError("threshold_plan_output_exists")
    _atomic_bytes(plan_path, json.dumps(plan, sort_keys=True, indent=2).encode() + b"\n")
    built = build_partitions(plan, paths=paths, work_dir=work_dir, deadline_seconds=deadline_seconds)
    if built["status"] != "ready":
        return deps.result("thresholds", built["status"], reasons=built["reasons"],
                           source={"plan_sha256": plan["plan_sha256"]}, counters=built["counters"])
    build_path = out_dir / "build-manifest.json"
    if build_path.exists():
        build = json.loads(build_path.read_bytes()[: 4 * 1024**2])
        if build.get("plan_sha256") != plan["plan_sha256"]:
            raise RebuildError("threshold_output_exists")
    else:
        build = assemble(plan, paths=paths, work_dir=work_dir, out_dir=out_dir)
    asset = out_dir / build["asset"]["name"]
    verification = verify_package(out_dir / "station_thresholds.sqlite", out_dir / "station_thresholds.version",
                                  asset=asset, build_manifest=build_path, release_assets=release_assets)
    if verification["status"] != "ready":
        return verification
    steps = upload_plan(verification, asset=asset, manifest_path=out_dir / "station_thresholds.version",
                        installed_manifest=installed_manifest, repo=repo)
    install = ["python", "scripts/build_station_thresholds.py", "install-manifest",
               "--manifest", str(out_dir / "station_thresholds.version"), "--build-manifest", str(build_path),
               "--release-assets", "<saved gh api release JSON after upload>", "--installed", str(installed_manifest)]
    return deps.result("thresholds", "ready", source={"plan_sha256": plan["plan_sha256"],
                                                     "source_version": document["source_version"]["version"]},
                       product={"verification": verification["product"], "upload_plan": steps,
                                "install_command": install, "asset": build["asset"],
                                "snapshot_date": plan["snapshot_date"]},
                       observed=int(verification["source_health"]["metrics"]["observed"]),
                       promoted=int(verification["product"]["coverage"].get("active_with_thresholds", 0)))


def install_manifest(new_manifest: Path, installed: Path, *, build_manifest: Path, release_assets: Any,
                     now: Callable[[], str] = _utc_now) -> dict[str, Any]:
    """Replace the installed manifest only after the replacement qualifies remotely.

    The new manifest must be a verified V2 package manifest bound by its build
    manifest, and the operator-saved release metadata must show that exact asset
    uploaded with its digest. The old manifest is kept beside the installed one
    first, so the previous good input is never lost before its replacement works.
    """
    from scripts import threshold_artifacts as artifacts

    fields = artifacts.read_manifest(new_manifest)
    if fields.get("format") != "sqlite-gzip":
        raise RebuildError("threshold_install_requires_v2_manifest")
    build = json.loads(build_manifest.read_bytes()[: 4 * 1024**2])
    if build.get("schema") != BUILD_SCHEMA or build.get("manifest") != fields:
        raise RebuildError("threshold_build_manifest_mismatch")
    name, sha, size = artifacts._asset(fields)
    disposition = _release_disposition(release_assets, name, sha, size)
    if disposition.get("state") != "asset_present_verified":
        raise RebuildError("threshold_install_requires_verified_remote_asset")
    raw = new_manifest.read_bytes()
    previous = None
    if installed.exists():
        old = installed.read_bytes()
        if old == raw:
            return {"schema": INSTALL_SCHEMA, "status": "already_installed", "manifest_sha256": _sha_file(installed)[0]}
        keep = installed.with_name(f"{installed.name}.previous-{hashlib.sha256(old).hexdigest()[:16]}")
        if not keep.exists():
            _atomic_bytes(keep, old)
        previous = {"retained_copy": str(keep), "sha256": hashlib.sha256(old).hexdigest()}
    _atomic_bytes(installed, raw)
    return {"schema": INSTALL_SCHEMA, "status": "installed", "installed": str(installed),
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "asset": name, "release_disposition": disposition,
            "previous": previous, "installed_at": now(),
            "next": ["git add -f data/station_thresholds.version",
                     "commit; the next bot run's `python -m scripts.threshold_artifacts ensure` downloads and "
                     "verifies the asset, setting THEHEAT_GHCN_THRESHOLD_VERIFICATION=success"],
            "rollback": None if previous is None else f"copy {previous['retained_copy']} -> {installed}",
            "scientific_qualification": "not_established_by_artifact_integrity"}


__all__ = ["ARCHIVE_URL", "BASE_URL", "BUILD_SCHEMA", "FETCH_PLAN_SCHEMA", "INPUTS_SCHEMA", "PLAN_SCHEMA",
           "RebuildError", "assemble", "build_partitions", "fetch_inputs", "install_manifest", "package",
           "parse_listing", "parse_version", "resolve_fetch_plan", "resolve_inputs", "verify_inputs",
           "build_plan", "fetch_archive", "partition_state", "upload_plan", "verify_package"]
