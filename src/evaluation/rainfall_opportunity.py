"""Offline audit of exported rainfall-opportunity traces (P09a/P19).

Accepts detached JSON trace exports and matching canonical populations only.
Performs no source, database, model or platform I/O and acquires nothing.
Gaps are measured only inside actually observed complete windows. A theoretical
rotation period is not an achieved revisit SLA, a model witness reading is not
GPM recovery, and unattributed cost is unknown, never zero.
"""

from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import json
import math
import re
from typing import Any

TRACE_SCHEMA = "theheat.rainfall-opportunity-trace/v1"
POPULATION_SCHEMA = "theheat.rainfall-population/v1"
POPULATION_BASIS = "canonical_qualified_identity_keys_v1"
AUDIT_SCHEMA = "theheat.rainfall-opportunity-audit/v1"
# The accepted selector's constants (src/data/gpm_imerg.py); a test binds them.
DEFAULT_CITY_LIMIT = 75
MAX_NETWORK_CITIES = 75
FRESH_MAX_AGE_DAYS = 6
MAX_TRACES = 4096
MAX_AUDIT_POPULATIONS = 64
MAX_POPULATION = 4096
MAX_TRACE_CANDIDATES = 32
GRID_LEGS = frozenset({"imerg_late_grid_datapool", "imerg_late_grid_s3"})
WINDOW_LEGS = frozenset({"imerg_late_opendap", "open_meteo_witness"})
PRIMARY_LEGS = GRID_LEGS | {"imerg_late_opendap"}
_DISPOSITIONS = frozenset("nrufop")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_SAMPLE_LIMIT = 25


class TraceError(ValueError):
    """A detached input that the audit cannot use; carries a fixed reason code."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise TraceError(code)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _identity_sha256(keys: list[str]) -> str:
    return hashlib.sha256(json.dumps(list(keys), separators=(",", ":")).encode()).hexdigest()


def _day(value: Any, code: str) -> date:
    _require(isinstance(value, str) and len(value) == 10, code)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise TraceError(code) from None


def validate_population(document: Any) -> dict[str, Any]:
    _require(isinstance(document, dict) and document.get("schema") == POPULATION_SCHEMA, "population_schema")
    _require(document.get("basis") == POPULATION_BASIS, "population_basis")
    members = document.get("members")
    _require(isinstance(members, list) and len(members) <= MAX_POPULATION, "population_members")
    _require(all(isinstance(key, str) and _KEY.fullmatch(key) for key in members), "population_members")
    _require(members == sorted(set(members)), "population_not_canonical")
    _require(document.get("count") == len(members), "population_count")
    _require(document.get("sha256") == _identity_sha256(members), "population_digest")
    return {"sha256": document["sha256"], "members": members}


_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_TRACE_KEYS = frozenset({"schema", "source_id", "run_id", "trace_status", "incomplete_reasons"})
_RUN_KEYS = frozenset({"selection_date_utc", "requested_target_date", "product", "configured", "population",
                       "primary_gate", "legs", "request_counts", "cost"})
_FINISH_KEYS = frozenset({"outcome", "serving_leg", "readings", "failure_class"})
_COUNT_KEYS = frozenset({"grid_downloads", "opendap_date_probes", "opendap_point_calls", "witness_point_calls"})
_WINDOW_KEYS = frozenset({"scan_date", "max_cities", "window_size", "selection_sha256", "data_date", "dispositions",
                          "failure_signatures", "member_calls", "in_flight_at_export"})
_LEG_KEYS = frozenset({"leg", "population_semantics", "outcome", "reason", "walkback_start_date", "max_lookback_days",
                       "candidates", "candidates_omitted", "downloads", "data_date", "inspection", "readings",
                       "reading_bitmap", "missing_values", "date_probes", "date_probe_calls", "date_probes_omitted",
                       *_WINDOW_KEYS})
_LEG_COUNTS = ("candidates_omitted", "downloads", "readings", "missing_values", "date_probe_calls",
               "date_probes_omitted", "window_size", "member_calls", "in_flight_at_export")


def _count(value: Any, code: str, *, limit: int = 10_000_000) -> int:
    # bool is an int subclass; a detached count must be a plain non-negative int.
    _require(type(value) is int and 0 <= value <= limit, code)
    return value


def _optional_day(value: Any, code: str) -> None:
    if value is not None:
        _day(value, code)


def _code(value: Any, code: str) -> str:
    _require(type(value) is str and _CODE.fullmatch(value) is not None, code)
    return value


def _validate_leg(leg: Any) -> None:
    _require(type(leg) is dict and set(leg) <= _LEG_KEYS and type(leg.get("leg")) is str
             and leg["leg"] in GRID_LEGS | WINDOW_LEGS, "trace_legs")
    _code(leg.get("population_semantics"), "trace_legs")
    _code(leg.get("outcome"), "trace_legs")
    if "reason" in leg:
        _code(leg["reason"], "trace_legs")
    for key in _LEG_COUNTS:
        if key in leg:
            _count(leg[key], "trace_legs")
    if leg.get("max_lookback_days") is not None:
        _count(leg["max_lookback_days"], "trace_legs", limit=366)
    if "inspection" in leg:
        _require(type(leg["inspection"]) is str and leg["inspection"] in {"not_reached", "completed"}, "trace_legs")
    for key, outcomes in (("candidates", {"not_found", "transient", "downloaded"}),
                          ("date_probes", {"not_found", "published", "unavailable"})):
        if key in leg:
            items = leg[key]
            _require(type(items) is list and len(items) <= MAX_TRACE_CANDIDATES, "trace_legs")
            for item in items:
                _require(type(item) is dict and set(item) == {"date", "outcome"} and type(item["outcome"]) is str
                         and _CODE.fullmatch(item["outcome"]) is not None, "trace_legs")
                _day(item["date"], "trace_legs")
    _optional_day(leg.get("walkback_start_date"), "trace_legs")
    _optional_day(leg.get("data_date"), "trace_data_date")
    if "reading_bitmap" in leg:
        _require(type(leg["reading_bitmap"]) is str and len(leg["reading_bitmap"]) <= 2 * MAX_POPULATION,
                 "trace_bitmap")
    if "dispositions" in leg:
        codes = leg["dispositions"]
        _require(leg["leg"] in WINDOW_LEGS and type(codes) is str and set(codes) <= _DISPOSITIONS
                 and len(codes) <= MAX_NETWORK_CITIES, "trace_dispositions")
        _require(leg.get("window_size") == len(codes), "trace_dispositions")
    if "selection_sha256" in leg:
        _require(type(leg["selection_sha256"]) is str and _SHA.fullmatch(leg["selection_sha256"]) is not None,
                 "trace_selection")
    if "scan_date" in leg:
        _day(leg["scan_date"], "trace_selection")
    if leg.get("max_cities") is not None:
        _count(leg["max_cities"], "trace_legs", limit=MAX_POPULATION)
    if "failure_signatures" in leg:
        signatures = leg["failure_signatures"]
        _require(type(signatures) is dict and len(signatures) <= 9, "trace_legs")
        for key, value in signatures.items():
            _require(type(key) is str and 0 < len(key) <= 80, "trace_legs")
            _count(value, "trace_legs")


def _validate_counts(counts: Any) -> None:
    _require(type(counts) is dict and set(counts) == _COUNT_KEYS | {"http_requests"}, "trace_request_counts")
    for key in _COUNT_KEYS:
        _count(counts[key], "trace_request_counts")
    http = counts["http_requests"]
    _require(type(http) is dict and set(http) == {"min", "max", "unmeasured_components"}, "trace_request_counts")
    low, high = _count(http["min"], "trace_request_counts"), _count(http["max"], "trace_request_counts")
    _require(low <= high, "trace_request_counts")
    unmeasured = http["unmeasured_components"]
    _require(type(unmeasured) is list and len(unmeasured) <= 8 and len(set(map(str, unmeasured))) == len(unmeasured)
             and all(type(item) is str and _CODE.fullmatch(item) for item in unmeasured), "trace_request_counts")


def validate_trace(document: Any) -> dict[str, Any]:
    """Strict structural validation of one exported trace; never upgrades its own status.

    Every nested field is type-checked before any membership test or conversion,
    so a malformed record is refused with a fixed code instead of aborting the audit.
    """
    _require(type(document) is dict and document.get("schema") == TRACE_SCHEMA, "trace_schema")
    _require(document.get("source_id") == "gpm_imerg", "trace_source")
    status = document.get("trace_status")
    _require(type(status) is str and status in {"complete", "incomplete"}, "trace_status")
    reasons = document.get("incomplete_reasons")
    _require(type(reasons) is list and len(reasons) <= 32 and all(type(r) is str and _CODE.fullmatch(r)
                                                                   for r in reasons), "trace_reasons")
    _require((status == "complete") == (not reasons), "trace_status_reasons")
    run_id = document.get("run_id")
    _require(run_id is None or (type(run_id) is str and _KEY.fullmatch(run_id) is not None), "trace_run_id")
    keys = set(document)
    _require(_TRACE_KEYS <= keys <= _TRACE_KEYS | _RUN_KEYS | _FINISH_KEYS, "trace_keys")
    if "selection_date_utc" not in document:
        _require(keys == _TRACE_KEYS and status == "incomplete", "trace_selection_date")
        return {"status": status, "run_id": run_id, "selection_date": None}
    _require(_RUN_KEYS <= keys, "trace_keys")
    selection = _day(document["selection_date_utc"], "trace_selection_date")
    _optional_day(document["requested_target_date"], "trace_selection_date")
    _require(type(document["product"]) is str and 0 < len(document["product"]) <= 32, "trace_keys")
    configured = document["configured"]
    _require(type(configured) is dict and set(configured) == {"max_cities", "max_workers"}, "trace_keys")
    for value in configured.values():
        _require(value is None or (type(value) is int and 0 <= value <= MAX_POPULATION), "trace_keys")
    _require(document["primary_gate"] is None or (type(document["primary_gate"]) is str
                                                  and _CODE.fullmatch(document["primary_gate"]) is not None),
             "trace_keys")
    population = document["population"]
    _require(type(population) is dict and set(population) == {"basis", "count", "sha256", "within_trace_bound"}
             and population["basis"] == POPULATION_BASIS and type(population["within_trace_bound"]) is bool,
             "trace_population")
    _require(population["count"] is None or (type(population["count"]) is int and population["count"] >= 0),
             "trace_population")
    sha = population["sha256"]
    _require(sha is None or (type(sha) is str and _SHA.fullmatch(sha) is not None), "trace_population")
    legs = document["legs"]
    _require(type(legs) is list and len(legs) <= 8, "trace_legs")
    for leg in legs:
        _validate_leg(leg)
    _require(len({leg["leg"] for leg in legs}) == len(legs), "trace_legs")
    _validate_counts(document["request_counts"])
    cost = document["cost"]
    _require(type(cost) is dict and set(cost) == {"amount", "status"} and cost["amount"] is None
             and type(cost["status"]) is str, "trace_cost")
    if "outcome" in document:
        _require(keys >= _FINISH_KEYS, "trace_outcome")
        _code(document["outcome"], "trace_outcome")
        _require(document["serving_leg"] is None or (type(document["serving_leg"]) is str
                                                     and document["serving_leg"] in GRID_LEGS | WINDOW_LEGS),
                 "trace_outcome")
        _count(document["readings"], "trace_outcome")
        _require(document["failure_class"] is None or (type(document["failure_class"]) is str
                                                       and 0 < len(document["failure_class"]) <= 80), "trace_outcome")
    else:
        _require(not keys & _FINISH_KEYS, "trace_outcome")
    return {"status": status, "run_id": run_id, "selection_date": selection}


def request_bounds(legs: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute scalar counts and HTTP bounds from a trace's own retained legs.

    Mirrors RainfallOpportunityTrace.export; any difference means the retained
    counts are inconsistent. ``max`` bounds the counted components only.
    """
    counts = {key: 0 for key in _COUNT_KEYS}
    low = high = 0
    unmeasured: set[str] = set()
    for leg in legs:
        name = leg["leg"]
        if name in GRID_LEGS:
            downloads = leg.get("downloads", 0)
            counts["grid_downloads"] += downloads
            if name == "imerg_late_grid_datapool":
                low += downloads
                high += downloads
            elif downloads:
                unmeasured.add("s3_credential_and_object_requests")
        elif name == "imerg_late_opendap":
            probes, calls = leg.get("date_probe_calls", 0), leg.get("member_calls", 0)
            counts["opendap_date_probes"] += probes
            counts["opendap_point_calls"] += calls
            low += probes + calls
            high += probes + 2 * calls
        else:
            calls = leg.get("member_calls", 0)
            counts["witness_point_calls"] += calls
            low += calls
            high += 6 * calls
    if low:
        unmeasured.add("redirects_not_counted")
    return {**counts, "http_requests": {"min": low, "max": high, "unmeasured_components": sorted(unmeasured)}}


def derived_incomplete(document: dict[str, Any]) -> list[str]:
    """Completeness derived from the retained bytes; a caller's label cannot clear it."""
    if "selection_date_utc" not in document:
        return ["capture_not_started"]
    reasons: set[str] = set()
    population = document["population"]
    if population["count"] is None or population["sha256"] is None:
        reasons.add("population_not_captured")
    elif not population["within_trace_bound"]:
        reasons.add("population_exceeds_trace_bound")
    for leg in document["legs"]:
        if leg["leg"] in GRID_LEGS:
            if not {"candidates", "downloads", "candidates_omitted"} <= set(leg):
                reasons.add("grid_capture_missing")
            elif len(leg["candidates"]) + leg["candidates_omitted"] != leg["downloads"]:
                reasons.add("retained_counts_inconsistent")
            if leg.get("candidates_omitted", 0):
                reasons.add("grid_candidates_exceed_trace_bound")
            if leg.get("inspection") == "completed" and "reading_bitmap" not in leg:
                reasons.add("grid_membership_not_captured")
        probe_fields = {"date_probes", "date_probe_calls", "date_probes_omitted"}
        if set(leg) & probe_fields:
            if not probe_fields <= set(leg):
                reasons.add("date_probe_capture_missing")
            elif len(leg["date_probes"]) + leg["date_probes_omitted"] != leg["date_probe_calls"]:
                reasons.add("retained_counts_inconsistent")
            if leg.get("date_probes_omitted", 0):
                reasons.add("date_probes_exceed_trace_bound")
        if leg["leg"] in WINDOW_LEGS and set(leg) & (_WINDOW_KEYS - {"data_date"}):
            if not _WINDOW_KEYS <= set(leg):
                reasons.add("window_capture_missing")
                continue
            codes = leg["dispositions"]
            if leg["member_calls"] != sum(code != "n" for code in codes) or \
                    leg["in_flight_at_export"] != codes.count("p"):
                reasons.add("retained_counts_inconsistent")
            if "p" in codes:
                reasons.add("in_flight_at_export")
    if document["request_counts"] != request_bounds(document["legs"]):
        reasons.add("retained_counts_inconsistent")
    if "outcome" not in document:
        reasons.add("not_finished")
    return sorted(reasons)


def window_members(members: list[str], scan_date: date, max_cities: int | None) -> list[str]:
    """Recompute the accepted rotating window from a canonical population."""
    limit = min(max_cities if max_cities is not None else DEFAULT_CITY_LIMIT, MAX_NETWORK_CITIES)
    count = len(members)
    if not count or not limit:
        return []
    if count <= limit:
        return list(members)
    start = (scan_date.toordinal() * limit) % count
    return [members[(start + offset) % count] for offset in range(limit)]


def _bitmap_members(encoded: str, members: list[str]) -> set[str]:
    try:
        raw = base64.b64decode(encoded.encode(), validate=True)
    except (ValueError, TypeError):
        raise TraceError("trace_bitmap") from None
    _require(len(raw) == (len(members) + 7) // 8, "trace_bitmap")
    chosen = {members[i] for i in range(len(members)) if raw[i // 8] >> (i % 8) & 1}
    _require(not any(raw[i // 8] >> (i % 8) & 1 for i in range(len(members), len(raw) * 8)), "trace_bitmap")
    return chosen


def _member_view(trace: dict[str, Any], members: list[str] | None) -> dict[str, Any]:
    """Selected / attempted / inspected / fresh primary / witness member sets."""
    selection = date.fromisoformat(trace["selection_date_utc"])
    view: dict[str, Any] = {"selected": set(), "attempted": set(), "inspected": set(), "fresh_primary": set(),
                            "stale_primary": set(), "witness_model": set(), "reasons": []}
    for leg in trace["legs"]:
        name = leg["leg"]
        data_date = date.fromisoformat(leg["data_date"]) if leg.get("data_date") else None
        fresh = data_date is not None and 0 <= (selection - data_date).days <= FRESH_MAX_AGE_DAYS
        if name in GRID_LEGS:
            if members is None:
                view["reasons"].append("population_missing")
                continue
            view["selected"].update(members)
            if leg.get("candidates"):
                view["attempted"].update(members)
            if leg.get("inspection") == "completed":
                view["inspected"].update(members)
                if "reading_bitmap" not in leg:
                    view["reasons"].append("grid_membership_missing")
                    continue
                read = _bitmap_members(leg["reading_bitmap"], members)
                if leg.get("outcome") == "served" and fresh:
                    view["fresh_primary"].update(read)
                else:
                    view["stale_primary"].update(read)
        elif name in WINDOW_LEGS and "dispositions" in leg:
            if members is None:
                view["reasons"].append("population_missing")
                continue
            window = window_members(members, date.fromisoformat(leg["scan_date"]), leg.get("max_cities"))
            if _identity_sha256(window) != leg["selection_sha256"] or len(window) != len(leg["dispositions"]):
                view["reasons"].append("selection_mismatch")
                continue
            view["selected"].update(window)
            for key, code in zip(window, leg["dispositions"]):
                if code != "n":
                    view["attempted"].add(key)
                if code in {"r", "u", "o"}:
                    view["inspected"].add(key)
                if code == "r" and name == "open_meteo_witness":
                    view["witness_model"].add(key)
                elif code == "r" and fresh:
                    view["fresh_primary"].add(key)
                elif code == "r":
                    view["stale_primary"].add(key)
    return view


def _walkback(trace: dict[str, Any]) -> dict[str, Any]:
    selection = date.fromisoformat(trace["selection_date_utc"])
    starts = {leg["walkback_start_date"] for leg in trace["legs"] if leg.get("walkback_start_date")}
    data = [leg["data_date"] for leg in trace["legs"] if leg.get("data_date") and leg["leg"] in PRIMARY_LEGS]
    expected = (selection - timedelta(days=1)).isoformat()
    return {"local_utc_start_mismatch": bool(starts - {expected}),
            "depth_days": max(((selection - date.fromisoformat(d)).days for d in data), default=None)}


def capture_context(document: Any) -> dict[str, Any]:
    """Independently checked identity/date, solely for withholding unauditable days.

    This does not validate the trace or make any of its evidence countable. A
    different schema/source or malformed identity/date cannot affect this audit.
    """
    if type(document) is not dict or document.get("schema") != TRACE_SCHEMA or document.get("source_id") != "gpm_imerg":
        return {}
    run_id = document.get("run_id")
    if run_id is not None and (type(run_id) is not str or _KEY.fullmatch(run_id) is None):
        return {}
    try:
        selection = _day(document.get("selection_date_utc"), "trace_selection_date")
    except TraceError:
        return {}
    return {"run_id": run_id, "selection_date": selection}


def evaluate(traces: list[Any], populations: list[Any], *, start: date | None = None,
             end: date | None = None) -> dict[str, Any]:
    """Audit detached traces against matching canonical populations."""
    _require(isinstance(traces, list) and len(traces) <= MAX_TRACES, "audit_trace_count")
    _require(isinstance(populations, list) and len(populations) <= MAX_AUDIT_POPULATIONS, "audit_population_count")
    known: dict[str, list[str]] = {}
    population_rows: list[dict[str, Any]] = []
    for document in populations:
        try:
            checked = validate_population(document)
        except TraceError as exc:
            population_rows.append({"status": "unsupported", "reason": str(exc)})
            continue
        known[checked["sha256"]] = checked["members"]
        population_rows.append({"status": "accepted", "sha256": checked["sha256"], "count": len(checked["members"])})

    rows: list[dict[str, Any]] = []
    by_identity: dict[str, list[tuple[str | None, Any, dict[str, Any]]]] = {}
    for document in traces:
        content = digest(document) if _jsonable(document) else None
        try:
            checked = validate_trace(document)
        except TraceError as exc:
            context = capture_context(document)
            rows.append({"identity": context.get("run_id"), "trace_sha256": content, "status": "unsupported",
                         "reasons": [str(exc)], **_dated(context)})
            continue
        if checked["run_id"] is None:
            rows.append({"identity": None, "trace_sha256": content, "status": "unidentified_held",
                         "reasons": ["run_identity_missing"], **_dated(checked)})
            continue
        checked["derived"] = derived_incomplete(document)
        by_identity.setdefault(checked["run_id"], []).append((content, document, checked))

    counted: list[tuple[str, Any]] = []
    for identity in sorted(by_identity):
        group = by_identity[identity]
        contents = {content for content, _doc, _checked in group}
        if len(contents) > 1:
            for content in sorted(contents, key=lambda value: value or ""):
                dated = next(_dated(c) for item, _d, c in group if item == content)
                rows.append({"identity": identity, "trace_sha256": content, "status": "conflict_held",
                             "reasons": ["same_run_identity_different_capture"], **dated})
            continue
        content, document, checked = group[0]
        row: dict[str, Any] = {"identity": identity, "trace_sha256": content, "copies": len(group), "reasons": []}
        if checked["selection_date"] is None or checked["status"] == "incomplete" or checked["derived"]:
            reasons = set(document["incomplete_reasons"]) | set(checked["derived"])
            if checked["status"] == "complete":
                reasons.add("supplied_complete_contradicted")
            row.update(status="trace_incomplete", reasons=sorted(reasons))
            if checked["selection_date"] is not None:
                row["selection_date"] = checked["selection_date"].isoformat()
            rows.append(row)
            continue
        row.update(status="counted", selection_date=checked["selection_date"].isoformat(),
                   outcome=document.get("outcome"), serving_leg=document.get("serving_leg"),
                   population_sha256=document["population"].get("sha256"))
        rows.append(row)
        counted.append((identity, document))

    dates = sorted({row["selection_date"] for row in rows if row.get("selection_date")})
    if start is None and dates:
        start = date.fromisoformat(dates[0])
    if end is None and dates:
        end = date.fromisoformat(dates[-1])
    days: dict[str, dict[str, Any]] = {}
    member_days: dict[str, dict[str, Any]] = {}
    totals = {"selected": 0, "attempted": 0, "inspected": 0, "fresh_primary": 0, "stale_primary": 0,
              "witness_model": 0}
    low = high = 0
    unmeasured: set[str] = set()
    midnight: list[str] = []
    walkback_depths: dict[str, int] = {}
    for identity, document in counted:
        selection = document["selection_date_utc"]
        population = document["population"].get("sha256")
        members = known.get(population) if population else None
        row = next(r for r in rows if r.get("identity") == identity and r["status"] == "counted")
        view: dict[str, Any]
        if members is not None and document["population"]["count"] != len(members):
            # The supplied hash matches but the retained count does not: unauditable, never complete.
            view = {key: set() for key in totals} | {"reasons": ["population_count_mismatch"]}
            members = None
        else:
            try:
                view = _member_view(document, members)
            except TraceError as exc:
                view = {key: set() for key in totals} | {"reasons": [str(exc)]}
            if members is None:
                row["reasons"].append("population_missing")
        row["reasons"].extend(sorted(set(view["reasons"]) - set(row["reasons"])))
        for key in totals:
            totals[key] += len(view[key])
        counts = document["request_counts"]["http_requests"]
        low += counts["min"]
        high += counts["max"]
        unmeasured.update(counts["unmeasured_components"])
        walk = _walkback(document)
        if walk["local_utc_start_mismatch"]:
            midnight.append(identity)
        if walk["depth_days"] is not None:
            walkback_depths[identity] = walk["depth_days"]
        day = days.setdefault(selection, {"runs": [], "outcomes": [], "populations": set(), "auditable": True})
        day["runs"].append(identity)
        day["outcomes"].append(document.get("outcome"))
        day["populations"].add(population)
        if members is None or view["reasons"]:
            day["auditable"] = False
        if members is not None and not view["reasons"]:
            reads = member_days.setdefault(population, {})
            for key in view["fresh_primary"]:
                reads.setdefault(key, set()).add(selection)

    calendar: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    if start is not None and end is not None and start <= end and (end - start).days <= 3660:
        cursor = start
        while cursor <= end:
            key = cursor.isoformat()
            held = sorted({row["status"] for row in rows if row.get("selection_date") == key and row["status"] != "counted"})
            info = days.get(key)
            if info is None:
                calendar.append({"date": key, "status": "missing_run", "held": held})
                current = None
            else:
                populations_seen = sorted(p or "" for p in info["populations"])
                status = "observed" if info["auditable"] and len(populations_seen) == 1 else (
                    "population_changed" if len(populations_seen) > 1 else "not_auditable")
                if status == "observed" and held:
                    # Valid runs stay inspectable, but a held capture on this day
                    # means the day's capture is not complete: the window ends.
                    status = "observed_with_held_capture"
                calendar.append({"date": key, "status": status, "outcomes": sorted(set(map(str, info["outcomes"]))),
                                 "held": held})
                if status != "observed":
                    current = None
                elif current is not None and current["population_sha256"] == populations_seen[0]:
                    current["to"] = key
                else:
                    current = {"from": key, "to": key, "population_sha256": populations_seen[0]}
                    windows.append(current)
            cursor += timedelta(days=1)

    revisit = [_window_revisit(window, known, member_days) for window in windows]
    rows.sort(key=lambda r: (r.get("identity") or "", r.get("trace_sha256") or "", r["status"]))
    return {
        "schema": AUDIT_SCHEMA,
        "inputs": {"traces": len(traces), "populations": population_rows,
                   "trace_sha256": sorted(r["trace_sha256"] for r in rows if r.get("trace_sha256")),
                   "input_sha256": digest(sorted([r.get("trace_sha256") or "" for r in rows]) +
                                          sorted(known))},
        "runs": rows,
        "calendar": calendar,
        "observed_complete_windows": revisit,
        "opportunity_member_runs": totals,
        "walkback": {"local_utc_start_mismatch_runs": sorted(midnight), "depth_days_by_run": walkback_depths},
        "request_counts": {"http_requests_min": low, "http_requests_max": high,
                           "unmeasured_components": sorted(unmeasured), "basis": "counted_traces_only"},
        "cost": {"amount": None, "status": "unknown_unattributed"},
        "achieved_revisit_sla": None,
        "global_recall": None,
        "coverage_denominator": None,
        "limits": [
            "Measured gaps are bounded by observed complete windows; missing or held days end a window.",
            "Completeness is derived from each trace's retained bytes; a supplied status cannot clear it.",
            "HTTP max bounds counted components only; redirects and unmeasured legs are listed, cost unknown.",
            "Theoretical rotation days are a selector property, not an achieved revisit SLA.",
            "Model witness readings are counted separately and never as GPM recovery or station truth.",
            "A population hash binds supplied identities; it does not prove which members were attempted.",
        ],
    }


def _window_revisit(window: dict[str, Any], known: dict[str, list[str]],
                    member_days: dict[str, dict[str, set[str]]]) -> dict[str, Any]:
    members = known[window["population_sha256"]]
    first, last = date.fromisoformat(window["from"]), date.fromisoformat(window["to"])
    length = (last - first).days + 1
    reads = member_days.get(window["population_sha256"], {})
    gaps: list[int] = []
    never: list[str] = []
    censored = 0
    for key in members:
        seen = sorted(date.fromisoformat(d) for d in reads.get(key, set()) if window["from"] <= d <= window["to"])
        if not seen:
            never.append(key)
            censored += 1
            continue
        gaps.extend((b - a).days for a, b in zip(seen, seen[1:]))
        if (seen[0] - first).days or (last - seen[-1]).days:
            censored += 1
    count = len(members)
    return {
        "from": window["from"], "to": window["to"], "days": length, "population_sha256": window["population_sha256"],
        "members": count, "members_with_fresh_primary_reading": count - len(never),
        "members_without_fresh_primary_reading": len(never), "never_read_sample": never[:_SAMPLE_LIMIT],
        "max_observed_gap_days": max(gaps) if gaps else None, "censored_members": censored,
        "censored_lower_bound_days": length if never else None,
        # A selector property for the bounded network fallback, never an achieved SLA.
        "theoretical_network_rotation_days_at_default_limit": math.ceil(count / MAX_NETWORK_CITIES) if count else None,
    }


def _dated(checked: dict[str, Any]) -> dict[str, str]:
    return {"selection_date": checked["selection_date"].isoformat()} if checked.get("selection_date") else {}


def _jsonable(value: Any) -> bool:
    try:
        canonical(value)
    except (TypeError, ValueError, RecursionError):
        return False
    return True
