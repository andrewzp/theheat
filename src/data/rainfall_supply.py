"""Rainfall window/footprint contract and sparse flood/fire/smoke supply closure (W06).

Pure and offline. Nothing here fetches, schedules or activates rainfall automation.

- Window/footprint: every rainfall value carries accumulation start/end (UTC),
  integration interval, footprint, units, product version and retrieval time
  (explicitly unknown when absent). Mixed windows and evidence types refuse; a
  heaviest-cell value is never a national total; satellite/model is never a gauge.
- Regional scan: explicit regions, finite calls/deadline, cursor checkpointed in
  the retained run details; a failed region advances the cursor, never resets it.
- Reconciliation: supplied product granules vs gauge packets; unmatched windows,
  footprints and QC stay visible. The missing original Barrow granules remain a
  named historical limit; nothing is replayed or fabricated.
- Pilot selection: deterministic from retained coverage inputs; without a
  qualified reference denominator the gap is exposed, never ranked as recall.
- Evidence types: official report, thermal detection, smoke forecast and measured
  exposure stay distinct; corroboration needs matching place, window and claim.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import time
from typing import Any

WINDOW_SCHEMA = "theheat.rainfall-window/v1"
SCAN_SCHEMA = "theheat.rainfall-regional-scan/v1"
RECONCILE_SCHEMA = "theheat.rainfall-reconciliation/v1"
PILOT_SCHEMA = "theheat.reference-gap-pilots/v1"
HISTORICAL_LIMITS = ("barrow_original_imerg_granules_missing", "barrow_gauge_qc_chronology_missing")
IMERG_LATE = {"source_product": "IMERG Late daily (3IMERGDL)", "product_version": "V07", "resolution_deg": 0.1,
              "day_basis": "utc_day"}
EVIDENCE_TYPES = frozenset({"satellite_derived", "model_fallback", "gauge_observed", "official_flood_report",
                            "thermal_detection", "smoke_forecast", "measured_exposure"})


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def window_evidence(event: Any, *, retrieved_at: str | None = None) -> dict[str, Any]:
    """The explicit accumulation window and footprint for one GPM-derived event."""
    end_day = date.fromisoformat(str(event.date)) + timedelta(days=1)
    period = int(event.period_days)
    end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc)
    start = end - timedelta(days=period)
    model = getattr(event, "source_leg", None) == "open_meteo"
    aggregate = event.kind == "country_precip_event"
    return {
        "schema": WINDOW_SCHEMA, "domain": "precipitation",
        "evidence_type": "model_fallback" if model else "satellite_derived",
        "source_product": "Open-Meteo multi-model forecast precipitation" if model else IMERG_LATE["source_product"],
        "product_version": None if model else IMERG_LATE["product_version"],
        "accumulation_start": _iso(start), "accumulation_end": _iso(end), "integration_interval_hours": 24 * period,
        "footprint": {
            "kind": "heaviest_member_cell" if aggregate else ("model_point" if model else "grid_cell"),
            "resolution_deg": None if model else IMERG_LATE["resolution_deg"],
            "center": [event.lat, event.lon],
            "members": getattr(event, "city_count", None) if aggregate else 1,
        },
        "unit": "mm", "retrieved_at": retrieved_at, "retrieved_at_known": retrieved_at is not None,
        "limit": ("Value of the single heaviest member cell; not a national total or mean." if aggregate
                  else "One grid cell/point over the stated UTC window; not an area total or gauge reading."),
    }


def window_failures(evidence: Any) -> list[str]:
    """Why a rainfall window cannot support a claim (empty list = complete)."""
    if not isinstance(evidence, Mapping) or evidence.get("schema") != WINDOW_SCHEMA:
        return ["rainfall_window_missing"]
    out = []
    try:
        start = datetime.fromisoformat(str(evidence["accumulation_start"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(evidence["accumulation_end"]).replace("Z", "+00:00"))
        hours = evidence["integration_interval_hours"]
        if type(hours) is not int or hours <= 0 or end <= start or (end - start) != timedelta(hours=hours):
            out.append("integration_interval_inconsistent")
    except (KeyError, ValueError, TypeError):
        out.append("accumulation_window_missing")
    if evidence.get("unit") != "mm":
        out.append("unit_not_mm")
    footprint = evidence.get("footprint")
    if not isinstance(footprint, Mapping) or footprint.get("kind") not in {
            "grid_cell", "heaviest_member_cell", "model_point", "gauge_point", "area_mean"}:
        out.append("footprint_missing")
    if evidence.get("evidence_type") not in EVIDENCE_TYPES:
        out.append("evidence_type_unknown")
    if not evidence.get("source_product"):
        out.append("source_product_missing")
    return out


def combine_windows(members: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Members of one aggregate must share window, product and evidence type."""
    if not members:
        raise ValueError("rainfall_members_empty")
    keys = {(m.get("accumulation_start"), m.get("accumulation_end"), m.get("integration_interval_hours"))
            for m in members}
    if len(keys) != 1:
        raise ValueError("rainfall_mixed_windows")
    if len({m.get("evidence_type") for m in members}) != 1 or len({m.get("source_product") for m in members}) != 1:
        raise ValueError("rainfall_mixed_evidence_types")
    for member in members:
        if window_failures(member):
            raise ValueError("rainfall_member_window_incomplete")
    return dict(members[0])


_NATIONAL = re.compile(r"\b(?:nationwide|nation-wide|countrywide|country-wide|across (?:the )?(?:country|nation)|"
                       r"national (?:total|average|rainfall)|(?:average|total) (?:rainfall )?(?:for|across) )", re.I)
_GAUGE = re.compile(r"\b(?:rain ?gauges?|gauged|gauge reading|measured at (?:a )?(?:gauge|station))\b", re.I)


def rainfall_claim_failures(tweet: str, bundle: Any) -> list[str]:
    """Deterministic floor: window completeness, footprint scope and gauge wording."""
    raw = getattr(bundle, "raw_signal_dump", None)
    evidence = raw.get("rainfall_window") if isinstance(raw, dict) else None
    if evidence is None or not isinstance(tweet, str):
        return []
    failures = [f"rainfall evidence: {code}" for code in window_failures(evidence)]
    if evidence.get("footprint", {}).get("kind") in {"grid_cell", "heaviest_member_cell", "model_point"} \
            and _NATIONAL.search(tweet):
        failures.append("rainfall evidence: a single heaviest cell/point value is not a national total or average")
    if evidence.get("evidence_type") != "gauge_observed" and _GAUGE.search(tweet):
        failures.append("rainfall evidence: a satellite or model estimate is not a gauge measurement")
    return sorted(set(failures))


# --- 06.2 bounded regional scan -------------------------------------------------------
def region_set_sha(regions: Sequence[str]) -> str:
    return hashlib.sha256(json.dumps(list(regions), separators=(",", ":")).encode()).hexdigest()


def cursor_from_history(run_history: Any, source: str, regions: Sequence[str]) -> int:
    """Latest checkpoint for this exact region set from retained run details; else 0."""
    digest = region_set_sha(regions)
    runs = [r for r in (run_history if isinstance(run_history, list) else []) if isinstance(r, Mapping)]
    for run in sorted(runs, key=lambda r: str(r.get("started_at") or ""), reverse=True):
        for entry in run.get("sources") or []:
            scan = (entry.get("details") or {}).get("rainfall_scan") if isinstance(entry, Mapping) else None
            if entry.get("source") == source and isinstance(scan, Mapping) and scan.get("region_set_sha256") == digest:
                cursor = scan.get("next_cursor")
                return cursor if type(cursor) is int and 0 <= cursor < len(regions) else 0
    return 0


def scan_regions(regions: Sequence[str], fetch: Callable[[str], Mapping[str, Any]], *, cursor: int,
                 max_regions: int, max_calls: int, deadline_s: float,
                 clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Examine at most ``max_regions`` from the cursor; failures advance the cursor too."""
    if not regions or len(set(regions)) != len(regions) or not 1 <= max_regions <= len(regions):
        raise ValueError("rainfall_scan_regions")
    if type(max_calls) is not int or max_calls < 1 or deadline_s <= 0 or not 0 <= cursor < len(regions):
        raise ValueError("rainfall_scan_limits")
    started = clock()
    order = list(regions[cursor:]) + list(regions[:cursor])
    attempts: list[dict[str, Any]] = []
    calls = 0
    for region in order[:max_regions]:
        if calls >= max_calls or clock() - started >= deadline_s:
            attempts.append({"region": region, "outcome": "not_attempted_limit"})
            continue
        try:
            result = dict(fetch(region))
            used = result.get("calls", 1)
            calls += used if type(used) is int and used >= 0 else 1
            attempts.append({"region": region, "outcome": str(result.get("outcome", "qualified")),
                             **{k: result[k] for k in ("readings", "hold") if k in result}})
        except Exception as exc:  # noqa: BLE001 - one region's failure is recorded, never fatal
            calls += 1
            attempts.append({"region": region, "outcome": "failed", "failure_class": type(exc).__name__})
    examined = sum(1 for row in attempts if row["outcome"] != "not_attempted_limit")
    return {
        "schema": SCAN_SCHEMA, "region_set_sha256": region_set_sha(regions), "cursor": cursor,
        "next_cursor": (cursor + examined) % len(regions), "attempts": attempts, "calls": calls,
        "examined": examined, "selected": len(order[:max_regions]), "universe": len(regions),
        "scope": "Examined regions only; no global recall is estimated from a scan.",
    }


def revisit_ages(run_history: Any, source: str, regions: Sequence[str], *, today: date) -> dict[str, int | None]:
    """Days since each region was last actually examined in retained runs (None = never)."""
    last: dict[str, date] = {}
    for run in run_history if isinstance(run_history, list) else []:
        if not isinstance(run, Mapping):
            continue
        day = str(run.get("started_at") or "")[:10]
        for entry in run.get("sources") or []:
            scan = (entry.get("details") or {}).get("rainfall_scan") if isinstance(entry, Mapping) else None
            if entry.get("source") != source or not isinstance(scan, Mapping) or len(day) != 10:
                continue
            for row in scan.get("attempts") or []:
                if isinstance(row, Mapping) and row.get("outcome") not in {None, "not_attempted_limit"}:
                    seen = date.fromisoformat(day)
                    if row.get("region") not in last or seen > last[str(row["region"])]:
                        last[str(row["region"])] = seen
    return {region: ((today - last[region]).days if region in last else None) for region in regions}


# --- 06.3 product/gauge reconciliation -----------------------------------------------
def reconcile(granules: Sequence[Mapping[str, Any]], gauges: Sequence[Mapping[str, Any]], *,
              tolerance_mm: float = 2.0, tolerance_fraction: float = 0.2) -> dict[str, Any]:
    """Supplied granule cells vs gauge packets; every mismatch stays visible."""
    rows = []
    for gauge in gauges:
        base = {"gauge_id": gauge.get("gauge_id"), "window": [gauge.get("start"), gauge.get("end")]}
        if gauge.get("qc") not in (None, "", "accepted"):
            rows.append({**base, "outcome": "qc_excluded"})
            continue
        same_window = [g for g in granules if (g.get("start"), g.get("end")) == (gauge.get("start"), gauge.get("end"))]
        if not same_window:
            rows.append({**base, "outcome": "window_unmatched"})
            continue
        cell = next((g for g in same_window if abs(float(g["cell_center"][0]) - float(gauge["lat"])) <= g["resolution_deg"] / 2
                     and abs(float(g["cell_center"][1]) - float(gauge["lon"])) <= g["resolution_deg"] / 2), None)
        if cell is None:
            rows.append({**base, "outcome": "footprint_unmatched"})
            continue
        diff = float(cell["mm"]) - float(gauge["mm"])
        allowed = max(tolerance_mm, tolerance_fraction * float(gauge["mm"]))
        rows.append({**base, "outcome": "agree" if abs(diff) <= allowed else "conflict",
                     "product_mm": cell["mm"], "gauge_mm": gauge["mm"], "difference_mm": round(diff, 2),
                     "product": cell.get("product"), "product_version": cell.get("version")})
    usable = [row for row in rows if row["outcome"] == "agree"]
    return {"schema": RECONCILE_SCHEMA, "rows": rows, "usable_scoped_evidence": usable,
            "holds": sorted({row["outcome"] for row in rows if row["outcome"] != "agree"}),
            "historical_limits": list(HISTORICAL_LIMITS),
            "scope": "Agreement is for these supplied cells, gauges and windows only; not product validation."}


# --- 06.4 reference-gap pilot selection ------------------------------------------------
PILOT_HAZARDS = {"flood_basin": "regional_observed", "fire_incident": "firms", "smoke_aq": "air_quality"}


def select_pilots(coverage_rows: Sequence[Mapping[str, Any]], *, max_pilots: int,
                  supplied_plan: Sequence[str] = ()) -> dict[str, Any]:
    """Deterministic pilot choice from retained (region, hazard) coverage rows.

    A row is ``{"region", "hazard", "reference_denominator", "qualified_sources"}``.
    Without a qualified reference denominator the row is a named gap; a supplied
    plan may pick from those gaps explicitly, but nothing is ranked as recall.
    """
    from src.data.source_registry import CONTRACTS

    registered = {row.source_id for row in CONTRACTS}
    gaps, ready = [], []
    for row in coverage_rows:
        hazard = str(row.get("hazard"))
        source = PILOT_HAZARDS.get(hazard)
        key = f"{row.get('region')}:{hazard}"
        if source is None or source not in registered:
            gaps.append({"key": key, "gap": "no_registered_adapter"})
        elif type(row.get("reference_denominator")) is not int or row["reference_denominator"] <= 0:
            gaps.append({"key": key, "gap": "no_qualified_reference_denominator", "adapter": source})
        else:
            ready.append({"key": key, "adapter": source, "reference_denominator": row["reference_denominator"],
                          "qualified_sources": int(row.get("qualified_sources") or 0)})
    ready.sort(key=lambda r: (r["qualified_sources"], r["key"]))  # thinnest qualified coverage first
    chosen = [r["key"] for r in ready[:max_pilots]]
    gap_keys = {g["key"] for g in gaps}
    for key in supplied_plan:
        if key in gap_keys and key not in chosen and len(chosen) < max_pilots:
            chosen.append(key)
    return {"schema": PILOT_SCHEMA, "selected": chosen, "ready": ready, "gaps": gaps,
            "recall": None, "scope": "Pilot plumbing only; no ranking, recall or live source activation."}


# --- 06.5 physical hazard / report separation -------------------------------------------
_CLAIM_EVIDENCE = {
    "flood_occurring": {"official_flood_report", "gauge_observed"},
    "heavy_rain_amount": {"satellite_derived", "gauge_observed", "model_fallback"},
    "active_fire_detection": {"thermal_detection"},
    # No physical evidence type here classifies a vegetation fire: FIRMS confidence is detection confidence.
    "vegetation_fire": set(),
    "smoke_exposure_measured": {"measured_exposure"},
    "smoke_forecast": {"smoke_forecast"},
}


def corroboration(claim: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    """Can this physical observation corroborate this claim? Only same place, window and type."""
    kind, evidence_type = claim.get("claim_kind"), observation.get("evidence_type")
    if evidence_type not in EVIDENCE_TYPES:
        return {"corroborates": False, "reason": "evidence_type_unknown"}
    allowed = _CLAIM_EVIDENCE.get(str(kind), set())
    if evidence_type not in allowed:
        reason = ("detection_confidence_is_not_vegetation_classification" if kind == "vegetation_fire"
                  else "co_reporting_is_not_causation" if kind == "smoke_cause" else "evidence_type_does_not_support_claim")
        return {"corroborates": False, "reason": reason}
    if claim.get("place_id") != observation.get("place_id"):
        return {"corroborates": False, "reason": "place_mismatch"}
    if not _overlaps(claim.get("window"), observation.get("window")):
        return {"corroborates": False, "reason": "window_mismatch"}
    conflict = claim.get("value") is not None and observation.get("value") is not None \
        and claim.get("direction") == "at_least" and float(observation["value"]) < float(claim["value"])
    return {"corroborates": not conflict, "reason": "conflict_visible" if conflict else "matched",
            "evidence_type": evidence_type}


def _overlaps(a: Any, b: Any) -> bool:
    try:
        return str(a[0]) < str(b[1]) and str(b[0]) < str(a[1])
    except (TypeError, IndexError, KeyError):
        return False


# --- 06.6 readiness and packet completeness ----------------------------------------------
def packet_ready(bundle: Any) -> list[str]:
    """Stop before paid generation when the rainfall packet is incomplete."""
    raw = getattr(bundle, "raw_signal_dump", None)
    if not isinstance(raw, dict):
        return ["bundle_raw_signal_missing"]
    return window_failures(raw.get("rainfall_window"))


def readiness(run_history: Any) -> list[dict[str, Any]]:
    """Per region/product readiness rows from retained scan details (Sources/candidates/brief)."""
    rows: dict[str, dict[str, Any]] = {}
    runs = [r for r in (run_history if isinstance(run_history, list) else []) if isinstance(r, Mapping)]
    for run in sorted(runs, key=lambda r: str(r.get("started_at") or "")):
        for entry in run.get("sources") or []:
            scan = (entry.get("details") or {}).get("rainfall_scan") if isinstance(entry, Mapping) else None
            if not isinstance(scan, Mapping):
                continue
            for row in scan.get("attempts") or []:
                if isinstance(row, Mapping) and row.get("outcome") != "not_attempted_limit":
                    rows[f"{entry.get('source')}:{row.get('region')}"] = {
                        "source": entry.get("source"), "region": row.get("region"), "outcome": row.get("outcome"),
                        "hold": row.get("hold"), "at": run.get("started_at")}
    return sorted(rows.values(), key=lambda r: (str(r["source"]), str(r["region"])))


__all__ = ["EVIDENCE_TYPES", "HISTORICAL_LIMITS", "IMERG_LATE", "combine_windows", "corroboration",
           "cursor_from_history", "packet_ready", "rainfall_claim_failures", "readiness", "reconcile",
           "region_set_sha", "revisit_ages", "scan_regions", "select_pilots", "window_evidence", "window_failures"]
