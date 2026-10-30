"""Qualified point-normal acquisition: plan, bounded resumable fetch, admission, install plan.

The Hot10 loader (``open_meteo.load_normals``) only accepts rows that name a
registry place, exact sampling point, product, normal period and retrieval
time. The checked-in legacy CSV (``city,month,avg_high_c``) names none of
those, so it is refused rather than relabelled. This module is the operator
path to a qualified replacement:

1. ``build_plan`` — deterministic universe of catalogue points x months, which
   of them the installed file already qualifies, what is missing, the required
   isolated dependency and explicit request bounds. No network.
2. ``acquire`` — finite, resumable owner-run fetch through an injectable
   provider adapter (the default wraps Meteostat ``Normals(Point(...))``) with
   explicit request/byte/deadline/retry limits. Each point is one atomically
   written partition; failed or incomplete results are never relabelled and the
   installed baseline is never written.
3. ``admit`` — candidate manifest + CSV checks (schema, duplicates, provenance,
   complete selected months) and actual-loader acceptance.
4. ``install_plan`` — bounded local comparison with the installed artifact's
   identity and a retained rollback copy. Root performs installation.

Loader acceptance proves the path, not climate-normal quality.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Iterable, Protocol

from src.data import acquisition_dependencies as deps
from src.data import open_meteo, places

PRODUCT = "meteostat-normals-point-v1"
PLAN_SCHEMA = "theheat.normals-acquisition-plan/v1"
PARTITION_SCHEMA = "theheat.normals-partition/v1"
CANDIDATE_SCHEMA = "theheat.normals-candidate/v1"
INSTALL_SCHEMA = "theheat.normals-install-plan/v1"
PERIODS: tuple[tuple[int, int], ...] = ((1991, 2020), (1961, 1990))
FIELDS = ("city", "country", "place_id", "sampling_point_id", "lat", "lon", "month", "avg_high_c",
          "source_product", "period_start", "period_end", "retrieved_at")
LEGACY_COLUMNS = frozenset({"city", "month", "avg_high_c"})
LEGACY_EXPLANATION = (
    "Rows carry only a city name, a month and a value. They name no registry place, sampling point, "
    "coordinates, product, normal period or retrieval time, so the loader cannot tell which point or "
    "which fallback period (1991-2020 or 1961-1990) produced a value. Values are never relabelled: "
    "every point-month must be re-acquired with attribution.")
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_PARTITION_BYTES = 256 * 1024
TMAX_RANGE = (-90.0, 60.0)
LIMIT_BOUNDS = {"max_requests": (1, 20_000), "max_bytes": (1, 64 * 1024 * 1024),
                "deadline_seconds": (1, 6 * 3600), "max_retries": (0, 5)}


class NormalsError(deps.AcquisitionError):
    """Fixed labels only."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_bounded(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise NormalsError("normals_input_not_regular_file")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise NormalsError("normals_input_too_large")
    return raw


def file_identity(path: Path) -> dict[str, Any] | None:
    """sha256, size and the git blob id, so Root can recover the exact prior bytes."""
    if not path.exists():
        return None
    raw = _read_bounded(path)
    blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw, usedforsecurity=False).hexdigest()
    return {"name": path.name, "sha256": _sha(raw), "bytes": len(raw), "git_blob_sha1": blob}


def _atomic_write(path: Path, raw: bytes) -> None:
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


def _point_key(row: dict) -> str:
    return places.event_location_key(row["city"], row["country"], row["lat"], row["lon"], place_id=row["place_id"])


# ---------------------------------------------------------------------------
# 02.1 plan
# ---------------------------------------------------------------------------

def load_universe(cities_path: Path) -> list[dict[str, Any]]:
    """Registered catalogue points in deterministic order (registry aliases collapsed)."""
    points: dict[tuple[str, str], dict[str, Any]] = {}
    for city in places.load_cities(str(cities_path)):
        point = {"city": city["city"], "country": city["country"], "place_id": city["place_id"],
                 "sampling_point_id": city["sampling_point_id"], "lat": float(city["lat"]),
                 "lon": float(city["lon"])}
        points.setdefault((point["place_id"], point["sampling_point_id"]), point)
    return [points[key] for key in sorted(points)]


def inspect_baseline(path: Path) -> dict[str, Any]:
    """Classify the installed normals file and count loader-accepted point-months."""
    identity = file_identity(path)
    if identity is None:
        return {"format": "absent", "identity": None, "rows": 0, "loader_accepted_point_months": 0,
                "conflicting_point_months": 0}
    text = _read_bounded(path).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    header = list(reader.fieldnames or [])
    rows = list(reader)
    if not set(FIELDS) <= set(header):
        legacy = set(header) <= LEGACY_COLUMNS | {"country"} and LEGACY_COLUMNS <= set(header)
        return {"format": "legacy_name_only" if legacy else "unrecognized", "identity": identity,
                "header": header, "rows": len(rows),
                "distinct_names": len({row.get("city", "") for row in rows}),
                "missing_columns": sorted(set(FIELDS) - set(header)),
                "loader_accepted_point_months": 0, "conflicting_point_months": 0,
                "explanation": LEGACY_EXPLANATION if legacy else "Not the meteostat-normals-point-v1 schema."}
    normals = open_meteo.load_normals(str(path))
    accepted = sum(1 for entry in normals.values() for month in entry if isinstance(month, int))
    conflicts = sum(1 for entry in normals.values() for meta in entry.get("_meta", {}).values()
                    if isinstance(meta, dict) and meta.get("conflict"))
    return {"format": "qualified_point_normals", "identity": identity, "header": header, "rows": len(rows),
            "loader_accepted_point_months": accepted, "conflicting_point_months": conflicts,
            "refused_rows": len(rows) - accepted - conflicts}


def _plan_identity(plan: dict[str, Any]) -> str:
    return _sha(_canonical({k: v for k, v in plan.items() if k not in {"plan_sha256", "dependency", "next_command"}}))


def build_plan(cities_path: Path, installed_path: Path, *, months: Iterable[int] = range(1, 13),
               dependency: dict[str, Any] | None = None, plan_path: str = "normals-plan.json") -> dict[str, Any]:
    selected = sorted(set(int(month) for month in months))
    if not selected or any(not 1 <= month <= 12 for month in selected):
        raise NormalsError("normals_months_invalid")
    universe = load_universe(cities_path)
    baseline = inspect_baseline(installed_path)
    normals = open_meteo.load_normals(str(installed_path)) if baseline["format"] == "qualified_point_normals" else {}
    points = []
    for point in universe:
        entry = normals.get(_point_key(point), {})
        qualified = [month for month in selected if month in entry]
        points.append({**point, "qualified_months": qualified,
                       "missing_months": [month for month in selected if month not in qualified]})
    need = [point for point in points if point["missing_months"]]
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA, "product": PRODUCT,
        "provider": {"name": "meteostat", "interface": "Normals(Point(lat, lon), start, end).fetch()",
                     "dependency_manifest": deps.MANIFEST_PATH.name},
        "periods": [list(period) for period in PERIODS],
        "period_rule": "first period with any tmax; never mixed within a point; each row states its own period",
        "months": selected,
        "inputs": {"cities": file_identity(cities_path), "installed_baseline": baseline["identity"]},
        "baseline": {k: v for k, v in baseline.items() if k != "identity"},
        "universe": {"points": len(points), "point_months": len(points) * len(selected)},
        "points": points,
        "missing": {"points": len(need), "point_months": sum(len(point["missing_months"]) for point in need)},
        "request_bounds": {"minimum_requests": len(need), "maximum_requests_without_retries": len(need) * len(PERIODS),
                           "suggested_max_bytes": max(len(need) * len(PERIODS) * 4096, 4096)},
    }
    plan["plan_sha256"] = _plan_identity(plan)
    plan["dependency"] = dependency
    out_dir = f"normals-candidate-{plan['plan_sha256'][:12]}"
    plan["next_command"] = [
        "python", "scripts/build_normals.py", "acquire", "--plan", plan_path, "--out-dir", out_dir,
        "--installed", str(installed_path), "--max-requests", str(plan["request_bounds"]["maximum_requests_without_retries"] or 1),
        "--max-bytes", str(plan["request_bounds"]["suggested_max_bytes"]), "--deadline-seconds", "3600",
        "--max-retries", "2"]
    return plan


def plan_result(plan: dict[str, Any]) -> dict[str, Any]:
    dependency = plan.get("dependency") or {}
    forced = deps.dependency_status(dependency) if dependency else None
    reasons = []
    if plan["baseline"]["format"] in {"legacy_name_only", "unrecognized"}:
        reasons.append("installed_baseline_" + plan["baseline"]["format"])
    if plan["missing"]["point_months"]:
        reasons.append("qualified_point_months_missing")
    return deps.result("normals", forced or "planned", reasons=reasons, dependency=dependency or None,
                       source={"plan_sha256": plan["plan_sha256"], "missing": plan["missing"]},
                       product={"baseline_format": plan["baseline"]["format"],
                                "loader_accepted_point_months": plan["baseline"]["loader_accepted_point_months"]},
                       observed=plan["universe"]["point_months"],
                       promoted=plan["universe"]["point_months"] - plan["missing"]["point_months"])


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA or plan.get("product") != PRODUCT:
        raise NormalsError("normals_plan_invalid")
    if plan.get("plan_sha256") != _plan_identity(plan):
        raise NormalsError("normals_plan_altered")
    return plan


# ---------------------------------------------------------------------------
# 02.2 bounded resumable acquisition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Limits:
    max_requests: int
    max_bytes: int
    deadline_seconds: float
    max_retries: int

    def __post_init__(self) -> None:
        for name, (low, high) in LIMIT_BOUNDS.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise NormalsError("normals_limit_invalid")


class Provider(Protocol):
    name: str
    version: str

    def fetch(self, lat: float, lon: float, start: int, end: int) -> Any: ...


class MeteostatProvider:
    """The existing Meteostat point-normal adapter, imported only when an owner runs it."""

    name = "meteostat"

    def __init__(self) -> None:
        from importlib import metadata

        meteostat = __import__("meteostat")
        self._normals, self._point = meteostat.Normals, meteostat.Point
        self.version = metadata.version("meteostat")

    def fetch(self, lat: float, lon: float, start: int, end: int) -> Any:
        return self._normals(self._point(lat, lon), start, end).fetch()


class _ProductInvalid(Exception):
    pass


def normalize_response(response: Any) -> tuple[dict[int, float], bytes]:
    """Month -> tmax from a Meteostat-shaped frame, plus the canonical retained payload bytes.

    No frame, an empty frame, or no ``tmax`` column means the source had no data.
    Duplicate/out-of-range months or implausible values are an invalid product.
    """
    if response is None or bool(getattr(response, "empty", True)):
        return {}, _canonical({"columns": [], "tmax": {}})
    columns = sorted(str(column) for column in getattr(response, "columns", []))
    if "tmax" not in columns:
        return {}, _canonical({"columns": columns, "tmax": {}})
    values: dict[int, float] = {}
    for index, row in response.iterrows():
        month = index[-1] if isinstance(index, tuple) else index
        if isinstance(month, bool) or int(month) != month or not 1 <= int(month) <= 12 or int(month) in values:
            raise _ProductInvalid("normals_month_invalid")
        raw = row.get("tmax")
        if raw is None or isinstance(raw, bool):
            continue
        value = float(raw)
        if math.isnan(value):
            continue
        if not math.isfinite(value) or not TMAX_RANGE[0] <= value <= TMAX_RANGE[1]:
            raise _ProductInvalid("normals_value_implausible")
        values[int(month)] = round(value, 1)
    return values, _canonical({"columns": columns, "tmax": {str(k): v for k, v in sorted(values.items())}})


def _call(fn: Callable[[], Any], timeout: float) -> Any:
    """Run one provider call under the remaining deadline; a hung call stops the run."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as error:  # noqa: BLE001 - re-raised in the caller's thread
            box["error"] = error

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(max(timeout, 0.0))
    if worker.is_alive():
        raise TimeoutError("normals_provider_deadline")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _partition_path(out_dir: Path, point: dict) -> Path:
    return out_dir / "partitions" / f"{point['place_id']}-{point['sampling_point_id']}.json"


def _read_json(path: Path, limit: int = MAX_PARTITION_BYTES) -> Any:
    return json.loads(_read_bounded(path, limit).decode("utf-8"))


def _valid_partition(record: Any, plan: dict, point: dict) -> bool:
    return (isinstance(record, dict) and record.get("schema") == PARTITION_SCHEMA
            and record.get("plan_sha256") == plan["plan_sha256"]
            and record.get("status") in {"complete", "incomplete_source", "no_data", "invalid_product"}
            and all(record.get(k) == point[k] for k in ("place_id", "sampling_point_id", "lat", "lon"))
            and record.get("months") == point["missing_months"])


def _journal(out_dir: Path) -> dict[str, Any]:
    path = out_dir / "journal.json"
    return _read_json(path, MAX_FILE_BYTES) if path.exists() else {}


def acquire(plan: dict[str, Any], out_dir: Path, provider: Provider, limits: Limits, *, installed_path: Path,
            clock: Callable[[], float] = time.monotonic, now: Callable[[], str] = _utc_now) -> dict[str, Any]:
    """Fetch missing point-months within limits; resume only compatible completed partitions."""
    validate_plan(plan)
    out_dir = Path(out_dir)
    candidate_csv = out_dir / "candidate" / "normals.csv"
    if installed_path.exists() and candidate_csv.resolve() == installed_path.resolve():
        raise NormalsError("normals_candidate_would_overwrite_installed")
    if file_identity(installed_path) != plan["inputs"]["installed_baseline"]:
        raise NormalsError("normals_installed_baseline_changed_since_plan")
    out_dir.mkdir(parents=True, exist_ok=True)
    journal = _journal(out_dir) or {"schema": "theheat.normals-journal/v1", "plan_sha256": plan["plan_sha256"],
                                    "runs": [], "failures": {}}
    if journal.get("plan_sha256") != plan["plan_sha256"]:
        raise NormalsError("normals_out_dir_belongs_to_another_plan")
    for stale in (out_dir / "partitions").glob(".*.tmp") if (out_dir / "partitions").exists() else []:
        stale.unlink()  # an interrupted write is never a partition
    run: dict[str, Any]
    started, run = clock(), {"started_at": now(), "requests": 0, "bytes": 0, "resumed": 0, "written": 0,
                             "status": "running", "reasons": []}
    journal["runs"].append(run)

    def save() -> None:
        _atomic_write(out_dir / "journal.json", _canonical(journal))

    def stop(reason: str) -> None:
        run["status"], run["reasons"] = "incomplete", sorted(set(run["reasons"]) | {reason})

    try:
        for point in (point for point in plan["points"] if point["missing_months"]):
            path = _partition_path(out_dir, point)
            if path.exists():
                try:
                    if _valid_partition(_read_json(path), plan, point):
                        run["resumed"] += 1
                        continue
                except (ValueError, deps.AcquisitionError):
                    pass
                path.unlink()  # incompatible or damaged: re-request, never relabel
            record = _fetch_point(plan, point, provider, limits, run, started, clock, now, journal)
            if record is None:
                if run["status"] == "incomplete":
                    break
                continue
            _atomic_write(path, _canonical(record))
            journal["failures"].pop(f"{point['place_id']}-{point['sampling_point_id']}", None)
            run["written"] += 1
            save()
    except BaseException:
        stop("interrupted")
        run["finished_at"] = now()
        save()
        raise
    if run["status"] == "running":
        pending = [point for point in plan["points"] if point["missing_months"]
                   and not _partition_path(out_dir, point).exists()]
        if pending:
            stop("transport_failures_remaining")
        else:
            run["status"] = "complete"
    run["finished_at"] = now()
    save()
    if run["status"] != "complete":
        return deps.result("normals", "incomplete", reasons=run["reasons"],
                           source={"plan_sha256": plan["plan_sha256"]}, counters=_counters(run),
                           observed=plan["missing"]["point_months"])
    manifest = assemble_candidate(plan, out_dir, installed_path=installed_path, now=now)
    status = "ready" if manifest["rows"] else "source_absent"
    reasons = ["points_without_source_data"] if manifest["missing_points"] else []
    return deps.result("normals", status, reasons=reasons, source={"plan_sha256": plan["plan_sha256"]},
                       product={"candidate_sha256": manifest["csv_sha256"], "rows": manifest["rows"],
                                "missing_points": len(manifest["missing_points"])},
                       counters=_counters(run), observed=plan["universe"]["point_months"], promoted=manifest["rows"])


def _counters(run: dict) -> dict[str, int]:
    return {key: int(run[key]) for key in ("requests", "bytes", "resumed", "written")}


def _fetch_point(plan, point, provider, limits, run, started, clock, now, journal) -> dict | None:
    key = f"{point['place_id']}-{point['sampling_point_id']}"
    attempted: list[list[Any]] = []
    for start, end in (tuple(period) for period in plan["periods"]):
        for attempt in range(limits.max_retries + 1):
            remaining = limits.deadline_seconds - (clock() - started)
            if run["requests"] >= limits.max_requests:
                run["status"], run["reasons"] = "incomplete", ["request_limit"]
                return None
            if remaining <= 0:
                run["status"], run["reasons"] = "incomplete", ["deadline"]
                return None
            if run["bytes"] >= limits.max_bytes:
                run["status"], run["reasons"] = "incomplete", ["byte_limit"]
                return None
            run["requests"] += 1
            try:
                response = _call(lambda: provider.fetch(point["lat"], point["lon"], start, end), remaining)
                values, payload = normalize_response(response)
            except _ProductInvalid as error:
                return _partition(plan, point, provider, now, "invalid_product", start, end, {}, b"",
                                  attempted + [[start, end, str(error)]], run)
            except TimeoutError:
                run["status"], run["reasons"] = "incomplete", ["deadline"]
                return None
            except Exception as error:  # noqa: BLE001 - provider transport failures are retryable
                failure = journal["failures"].setdefault(key, {"attempts": 0})
                failure.update(attempts=failure["attempts"] + 1, error_class=type(error).__name__[:64])
                continue
            if run["bytes"] + len(payload) > limits.max_bytes:
                run["status"], run["reasons"] = "incomplete", ["byte_limit"]
                return None
            run["bytes"] += len(payload)
            if not values:
                attempted.append([start, end, "no_data"])
                break  # explicit next period, never a relabel
            wanted = {month: values[month] for month in point["missing_months"] if month in values}
            status = "complete" if len(wanted) == len(point["missing_months"]) else "incomplete_source"
            return _partition(plan, point, provider, now, status, start, end, wanted, payload,
                              attempted + [[start, end, "data"]], run)
        else:
            return None  # retries exhausted: failure stays in the journal, the point stays pending
    return _partition(plan, point, provider, now, "no_data", None, None, {}, b"", attempted, run)


def _partition(plan, point, provider, now, status, start, end, values, payload, attempted, run) -> dict:
    return {"schema": PARTITION_SCHEMA, "plan_sha256": plan["plan_sha256"],
            **{k: point[k] for k in ("place_id", "sampling_point_id", "city", "country", "lat", "lon")},
            "months": point["missing_months"], "status": status, "period_start": start, "period_end": end,
            "values": {str(month): value for month, value in sorted(values.items())},
            "missing_months": [month for month in point["missing_months"] if month not in values],
            "provider": provider.name, "provider_version": str(provider.version), "retrieved_at": now(),
            "payload_sha256": _sha(payload) if payload else None, "payload_bytes": len(payload),
            "attempted_periods": attempted}


def assemble_candidate(plan: dict[str, Any], out_dir: Path, *, installed_path: Path,
                       now: Callable[[], str] = _utc_now) -> dict[str, Any]:
    """Retained qualified rows + complete partitions -> candidate CSV, then its binding manifest."""
    rows, points, missing = [], [], []
    retained = 0
    if plan["baseline"]["format"] == "qualified_point_normals" and installed_path.exists():
        keep = {(p["place_id"], p["sampling_point_id"], m) for p in plan["points"] for m in p["qualified_months"]}
        for row in csv.DictReader(io.StringIO(_read_bounded(installed_path).decode("utf-8"))):
            if (row["place_id"], row["sampling_point_id"], int(row["month"])) in keep:
                rows.append({field: row[field] for field in FIELDS})
                retained += 1
    for point in (p for p in plan["points"] if p["missing_months"]):
        raw = _read_bounded(_partition_path(out_dir, point), MAX_PARTITION_BYTES)
        record = json.loads(raw)
        if record["status"] != "complete":
            missing.append({"place_id": point["place_id"], "sampling_point_id": point["sampling_point_id"],
                            "status": record["status"], "missing_months": record["missing_months"]})
            continue
        points.append({k: record[k] for k in ("place_id", "sampling_point_id", "period_start", "period_end",
                                              "retrieved_at", "provider", "provider_version", "months")}
                      | {"partition_sha256": _sha(raw)})
        for month, value in record["values"].items():
            rows.append({"city": point["city"], "country": point["country"], "place_id": point["place_id"],
                         "sampling_point_id": point["sampling_point_id"], "lat": repr(point["lat"]),
                         "lon": repr(point["lon"]), "month": str(int(month)), "avg_high_c": repr(value),
                         "source_product": PRODUCT, "period_start": str(record["period_start"]),
                         "period_end": str(record["period_end"]), "retrieved_at": record["retrieved_at"]})
    rows.sort(key=lambda row: (row["place_id"], row["sampling_point_id"], int(row["month"])))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(FIELDS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = buffer.getvalue().encode("utf-8")
    manifest = {"schema": CANDIDATE_SCHEMA, "plan_sha256": plan["plan_sha256"], "product": PRODUCT,
                "months": plan["months"], "periods": plan["periods"], "csv": "normals.csv",
                "csv_sha256": _sha(body), "csv_bytes": len(body), "rows": len(rows),
                "retained_baseline_rows": retained, "points": points, "missing_points": missing,
                "installed_baseline": plan["inputs"]["installed_baseline"], "assembled_at": now()}
    # The CSV lands first; the manifest that binds it lands last. A crash between
    # them leaves a mismatch that admission refuses.
    _atomic_write(out_dir / "candidate" / "normals.csv", body)
    _atomic_write(out_dir / "candidate" / "manifest.json", _canonical(manifest))
    return manifest


# ---------------------------------------------------------------------------
# 02.3 admission, comparison and install plan
# ---------------------------------------------------------------------------

def admit(candidate_dir: Path, *, partitions_dir: Path | None = None) -> dict[str, Any]:
    """Reject schema drift, duplicates, altered provenance and incomplete periods; prove loader acceptance."""
    reasons: list[str] = []
    try:
        manifest = _read_json(candidate_dir / "manifest.json", MAX_FILE_BYTES)
        body = _read_bounded(candidate_dir / "normals.csv")
    except (OSError, ValueError, deps.AcquisitionError):
        return deps.result("normals", "product_invalid", reasons=["candidate_unreadable"])
    if not isinstance(manifest, dict) or manifest.get("schema") != CANDIDATE_SCHEMA or manifest.get("product") != PRODUCT:
        return deps.result("normals", "product_invalid", reasons=["candidate_manifest_schema"])
    if manifest.get("csv_sha256") != _sha(body) or manifest.get("csv_bytes") != len(body):
        reasons.append("candidate_csv_not_bound_by_manifest")
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if tuple(reader.fieldnames or ()) != FIELDS:
        return deps.result("normals", "product_invalid", reasons=sorted(reasons + ["candidate_schema_incompatible"]))
    rows = list(reader)
    by_point = {(p["place_id"], p["sampling_point_id"]): p for p in manifest.get("points", [])}
    periods = {tuple(period) for period in manifest.get("periods", [])}
    seen: set[tuple[str, str, int]] = set()
    months_by_point: dict[tuple[str, str], set[int]] = {}
    coordinates: dict[str, tuple[str, str]] = {}
    for row in rows:
        try:
            identity = places.place_for_row(row)
            month, value = int(row["month"]), float(row["avg_high_c"])
            period = (int(row["period_start"]), int(row["period_end"]))
        except (KeyError, ValueError, TypeError):
            reasons.append("row_unparseable")
            continue
        point = (row["place_id"], row["sampling_point_id"])
        if identity["sampling_point_id"] != row["sampling_point_id"]:
            reasons.append("row_point_identity_mismatch")
        if coordinates.setdefault(row["place_id"], (row["lat"], row["lon"])) != (row["lat"], row["lon"]):
            reasons.append("duplicate_place_points")
        if (*point, month) in seen:
            reasons.append("duplicate_point_month")
        seen.add((*point, month))
        months_by_point.setdefault(point, set()).add(month)
        if row["source_product"] != PRODUCT or period not in periods or not math.isfinite(value) \
                or not TMAX_RANGE[0] <= value <= TMAX_RANGE[1] or month not in manifest.get("months", []):
            reasons.append("row_provenance_invalid")
        entry = by_point.get(point)
        if entry is not None and month in entry["months"] and (period != (entry["period_start"], entry["period_end"])
                                  or row["retrieved_at"] != entry["retrieved_at"]):
            reasons.append("altered_provenance")
    for point, entry in by_point.items():
        if not set(entry["months"]) <= months_by_point.get(point, set()):
            reasons.append("incomplete_period")
    if partitions_dir is not None:
        for entry in by_point.values():
            path = partitions_dir / f"{entry['place_id']}-{entry['sampling_point_id']}.json"
            try:
                raw = _read_bounded(path, MAX_PARTITION_BYTES)
            except deps.AcquisitionError:
                reasons.append("partition_missing")
                continue
            record = json.loads(raw)
            if _sha(raw) != entry["partition_sha256"]:
                reasons.append("altered_provenance")
                continue
            for month, value in record["values"].items():
                match = [row for row in rows if (row["place_id"], row["sampling_point_id"], row["month"])
                         == (entry["place_id"], entry["sampling_point_id"], str(int(month)))]
                if len(match) != 1 or float(match[0]["avg_high_c"]) != float(value):
                    reasons.append("altered_provenance")
    accepted = 0
    if not reasons:
        with _scratch_copy(body) as path:
            normals = open_meteo.load_normals(str(path))
        accepted = sum(1 for entry in normals.values() for month in entry if isinstance(month, int))
        if accepted != len(rows):
            reasons.append("loader_refused_rows")
    status = "product_invalid" if reasons else ("ready" if rows else "source_absent")
    return deps.result("normals", status, reasons=reasons,
                       product={"candidate_sha256": manifest.get("csv_sha256"), "rows": len(rows),
                                "loader_accepted_point_months": accepted,
                                "missing_points": len(manifest.get("missing_points", []))},
                       observed=len(rows), promoted=accepted)


class _scratch_copy:
    """The loader reads a path; give it a private copy so it never reads a moving file."""

    def __init__(self, body: bytes) -> None:
        import tempfile

        self._directory = tempfile.TemporaryDirectory(prefix="theheat-normals-admission-")
        self.path = Path(self._directory.name) / "normals.csv"
        self.path.write_bytes(body)

    def __enter__(self) -> Path:
        return self.path

    def __exit__(self, *_exc: Any) -> None:
        self._directory.cleanup()


def install_plan(candidate_dir: Path, installed_path: Path, *, max_changes_listed: int = 50) -> dict[str, Any]:
    """Compare an admitted candidate with the installed artifact; retain a rollback copy. No installation."""
    admission = admit(candidate_dir, partitions_dir=candidate_dir.parent / "partitions")
    if admission["status"] != "ready":
        raise NormalsError("normals_candidate_not_admitted")
    manifest = _read_json(candidate_dir / "manifest.json", MAX_FILE_BYTES)
    previous = file_identity(installed_path)
    if previous != manifest["installed_baseline"]:
        raise NormalsError("normals_installed_baseline_changed_since_plan")
    old: dict[tuple[str, str, int], float] = {}
    if previous is not None:
        baseline = inspect_baseline(installed_path)
        if baseline["format"] == "qualified_point_normals":
            for row in csv.DictReader(io.StringIO(_read_bounded(installed_path).decode("utf-8"))):
                try:
                    old[(row["place_id"], row["sampling_point_id"], int(row["month"]))] = float(row["avg_high_c"])
                except (KeyError, ValueError):
                    continue
    new = {(row["place_id"], row["sampling_point_id"], int(row["month"])): float(row["avg_high_c"])
           for row in csv.DictReader(io.StringIO(_read_bounded(candidate_dir / "normals.csv").decode("utf-8")))}
    changed = sorted((key, old[key], new[key]) for key in old.keys() & new.keys() if old[key] != new[key])
    rollback = None
    if previous is not None:
        rollback = candidate_dir / "rollback" / f"normals-{previous['sha256'][:16]}.csv"
        _atomic_write(rollback, _read_bounded(installed_path))
    candidate = file_identity(candidate_dir / "normals.csv")
    plan = {
        "schema": INSTALL_SCHEMA, "plan_sha256": manifest["plan_sha256"], "admission": admission["status"],
        "previous": {**(previous or {}), "format": inspect_baseline(installed_path)["format"]},
        "candidate": candidate,
        "comparison": {"added": len(new.keys() - old.keys()), "removed": len(old.keys() - new.keys()),
                       "changed": len(changed), "unchanged": len(old.keys() & new.keys()) - len(changed),
                       "largest_changes": [{"place_id": k[0], "sampling_point_id": k[1], "month": k[2],
                                            "previous_c": a, "candidate_c": b}
                                           for k, a, b in sorted(changed, key=lambda c: -abs(c[2] - c[1]))[
                                               :max_changes_listed]]},
        "install": {"performed_by": "root", "target": str(installed_path),
                    "steps": [f"verify sha256 {candidate['sha256'] if candidate else ''} of {candidate_dir / 'normals.csv'}",
                              f"copy {candidate_dir / 'normals.csv'} -> {installed_path}",
                              "commit the installed file with the candidate manifest and this plan"]},
        "rollback": None if previous is None else {
            "retained_copy": str(rollback), "sha256": previous["sha256"], "git_blob_sha1": previous["git_blob_sha1"],
            "steps": [f"copy {rollback} -> {installed_path}", "or restore the prior committed blob "
                      f"{previous['git_blob_sha1']} with git"]},
        "scientific_qualification": "not_established_by_loader_acceptance",
    }
    _atomic_write(candidate_dir / "install-plan.json", _canonical(plan))
    return plan


__all__ = ["CANDIDATE_SCHEMA", "FIELDS", "LEGACY_EXPLANATION", "Limits", "MeteostatProvider", "NormalsError",
           "PERIODS", "PLAN_SCHEMA", "PRODUCT", "acquire", "admit", "assemble_candidate", "build_plan",
           "file_identity", "inspect_baseline", "install_plan", "load_universe", "normalize_response",
           "plan_result", "validate_plan"]
