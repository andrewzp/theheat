"""Exact production matching for supplied reference units (W15.2).

Joins each reference unit from a W15.1 intake record to rows of a supplied
saved Gist state: drafts and their delivery receipts, suppression rows (stage
outcomes, including budget exclusions) and source-run outcomes. Every match or
near-match keeps the evidence that decided it (alias, hazard, place, window).
More than one distinct production event matching is ``trace_ambiguous``; it is
neither a success nor a miss. With no match, the nearest difference is named
(wrong window, place or type; unavailable source; budget exclusion; factual
rejection) and anything else stays unobserved. The result feeds the existing
``coverage.evaluate`` contract and coverage view; production history is read,
never rewritten, and nothing here computes recall.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Any

from src.evaluation import coverage as cov

MATCH_SCHEMA = "theheat.production-match/v1"
MAX_ROWS = 5000
_HAZARDS = (
    ("tropical_cyclone", ("cyclone", "hurricane", "typhoon", "tropical", "nhc")),
    ("flood", ("flood", "rain", "precip", "gpm")),
    ("fire", ("fire", "firms", "wildfire", "smoke")),
    ("air_quality", ("air_quality", "pm25", "pm2.5", "dust", "aq_")),
    ("heat", ("heat", "temperature", "record", "hot10", "wetbulb", "wet_bulb", "anomaly")),
    ("drought", ("drought",)),
    ("snow", ("snow", "blizzard")),
    ("severe_weather", ("severe", "tornado", "nws", "warning")),
)
CHECK_STAGES = {"safety", "honesty_gate", "evidence_contract", "fact_check", "critic"}
BUDGET_STAGES = {"budget_exhausted", "triage_cap", "billing_cycle_abort"}
FAILED_SOURCE = {"error", "failed", "unavailable", "access_expired", "timeout"}


def hazard(value: Any) -> str | None:
    text = str(value or "").lower()
    for name, words in _HAZARDS:
        if any(word in text for word in words):
            return name
    return None


def _tokens(value: Any) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(value or "").lower()) if len(t) > 1}


def _when(value: Any) -> datetime | None:
    """An aware instant in UTC, or None; a naive or malformed time never matches a window."""
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(UTC) if at.tzinfo is not None else None


def _place_tokens(draft: dict) -> set[str]:
    out: set[str] = set()
    for key in ("city", "country", "place", "location", "region"):
        out |= _tokens(draft.get(key))
    bundle = ((draft.get("review_context") or {}).get("two_bot") or {}).get("bundle") or {}
    if isinstance(bundle, dict):
        for key in ("location", "country", "place", "region"):
            out |= _tokens(bundle.get(key))
    return out


def production_rows(state: dict) -> list[dict]:
    """Bounded projection of the saved state; free text other than place/type is not carried."""
    rows: list[dict] = []
    raw = state.get("publish_ledger")
    ledger: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for draft in state.get("drafts", []) if isinstance(state.get("drafts"), list) else []:
        if not isinstance(draft, dict) or not draft.get("id"):
            continue
        receipt = ledger.get(draft.get("event_id") or draft["id"])
        rows.append({"kind": "draft", "id": str(draft["id"]), "event_id": str(draft.get("event_id") or ""),
                     "hazard": hazard(draft.get("type")), "places": sorted(_place_tokens(draft)),
                     "at": draft.get("created_at") or draft.get("posted_at"), "status": draft.get("status"),
                     "receipt_phase": receipt.get("phase") if isinstance(receipt, dict) else None,
                     "tweet_id": draft.get("tweet_id") if draft.get("status") == "posted" else None})
    for row in state.get("suppressions", []) if isinstance(state.get("suppressions"), list) else []:
        if isinstance(row, dict) and row.get("id"):
            rows.append({"kind": "suppression", "id": str(row["id"]), "event_id": str(row.get("event_id") or ""),
                         "hazard": hazard(row.get("category")) or hazard(row.get("source")) or hazard(row.get("event_id")),
                         "places": sorted(_tokens(row.get("summary"))), "at": row.get("ts"), "stage": row.get("stage")})
    for run in state.get("run_history", []) if isinstance(state.get("run_history"), list) else []:
        for source in run.get("sources", []) if isinstance(run, dict) and isinstance(run.get("sources"), list) else []:
            if isinstance(source, dict) and source.get("name"):
                rows.append({"kind": "source_run", "id": f"{run.get('run_id') or run.get('ts')}:{source['name']}",
                             "event_id": "", "hazard": hazard(source.get("name")), "places": [],
                             "at": run.get("ts") or run.get("started_at"), "status": source.get("status")})
    return rows[:MAX_ROWS]


def _window(unit: dict) -> tuple[datetime | None, datetime | None, str]:
    times = unit["time_fields"]
    start, end = times["event_start"], times["event_end"]
    def edge(value, late):
        if value is None:
            return None
        if value["precision"] == "instant":
            return cov.utc_datetime(value["utc"])
        if value["precision"] == "calendar":
            # A source-calendar day stays a whole-day interval; the match slack covers its unknown offset.
            return datetime.fromisoformat(value["date"] + ("T23:59:59+00:00" if late else "T00:00:00+00:00"))
        return None
    return edge(start, False), edge(end, True), "calendar" if any(
        v and v["precision"] == "calendar" for v in (start, end)) else "instant"


def _within(at: datetime | None, start: datetime | None, end: datetime | None, slack_hours: float) -> bool | None:
    """Production work may trail the event (reporting delay), so the late edge gets two extra days."""
    if at is None or (start is None and end is None):
        return None
    slack = timedelta(hours=slack_hours)
    return (start is None or at >= start - slack) and (end is None or at <= end + slack + timedelta(days=2))


def match_unit(unit: dict, sidecar: dict, rows: list[dict], *, slack_hours: float = 36.0) -> dict:
    hazards = {h for h in (hazard(label["label"]) for label in unit["hazard_labels"]) if h}
    places = set().union(*(_tokens(label["label"]) for label in unit["region_memberships"]))
    aliases = sidecar.get("production_aliases") or []
    start, end, precision = _window(unit)
    evaluated = []
    for row in rows:
        if row["kind"] == "source_run":
            continue
        alias = any(a and row["event_id"] and (row["event_id"] == a or row["event_id"].startswith(a + "_"))
                    for a in aliases)
        evidence = {"alias": alias, "hazard": row["hazard"] in hazards if row["hazard"] else None,
                    "place": bool(places & set(row["places"])) if row["places"] else None,
                    "window": _within(_when(row["at"]), start, end, slack_hours)}
        evaluated.append((row, evidence))
    matched = [(r, e) for r, e in evaluated if e["alias"] or (e["hazard"] and e["place"] and e["window"])]
    events = {r["event_id"] or r["id"] for r, _ in matched}
    out: dict[str, Any] = {"schema": MATCH_SCHEMA, "unit_id": unit["unit_id"], "window_precision": precision,
                           "rule": "alias, or hazard + place + window all agree", "matched": [], "near": [],
                           "status": "unmatched", "reasons": []}
    if matched:
        out["matched"] = [{"kind": r["kind"], "id": r["id"], "event_id": r["event_id"], "evidence": e}
                          for r, e in matched[:20]]
        if len(events) > 1 and not all(e["alias"] for _, e in matched):
            out["status"], out["reasons"] = "ambiguous", ["trace_ambiguous"]
        else:
            out["status"] = "matched"
        return out
    near = []
    for row, e in evaluated:
        if e["hazard"] and e["place"] and e["window"] is False:
            near.append((row, e, "reference_out_of_window"))
        elif e["hazard"] and e["window"] and e["place"] is False:
            near.append((row, e, "place_mismatch"))
        elif e["place"] and e["window"] and e["hazard"] is False:
            near.append((row, e, "hazard_mismatch"))
    out["near"] = [{"kind": r["kind"], "id": r["id"], "event_id": r["event_id"], "evidence": e, "difference": why}
                   for r, e, why in near[:20]]
    reasons = sorted({why for _, _, why in near})
    failed_sources = [r for r in rows if r["kind"] == "source_run" and r["hazard"] in hazards
                      and str(r.get("status") or "").lower() in FAILED_SOURCE
                      and _within(_when(r["at"]), start, end, slack_hours)]
    if failed_sources:
        reasons.append("source_failed")
        out["source_failures"] = [r["id"] for r in failed_sources[:10]]
    out["reasons"] = reasons or ["selection_not_observed", "trace_missing"]
    out["status"] = "near_match" if near else "unobserved"
    return out


def _ref(row: dict) -> dict:
    snapshot = row["id"] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", row["id"]) else cov.digest(row["id"])
    return {"namespace": "gist-state-record-v1", "snapshot_id": snapshot, "sha256": cov.digest(row)}


def _instant(value: Any) -> dict | None:
    at = _when(value)
    return cov.instant_time(at.strftime("%Y-%m-%dT%H:%M:%SZ")) if at is not None else None


def stages_for(match: dict, rows_by_id: dict[str, dict], *, execution_class: str) -> tuple[list[dict], list[str]]:
    """Coverage stage cells and unit holds from one match; ambiguous matches record nothing."""
    if match["status"] != "matched":
        return [], list(match["reasons"])
    cells: dict[str, dict] = {}
    holds: list[str] = []
    for item in match["matched"]:
        row = rows_by_id[item["id"]]
        recorded = _instant(row.get("at"))
        if row["kind"] == "draft" and recorded is not None:
            cells["draft_saved"] = cov.stage("draft_saved", state="recorded", refs=[_ref(row)], recorded_at=recorded,
                                             execution_class=execution_class, current_binding="current", reason_codes=())
            if row.get("receipt_phase") == "confirmed" and row.get("tweet_id"):
                cells["publication_confirmed"] = cov.stage(
                    "publication_confirmed", state="recorded", refs=[_ref(row)], recorded_at=recorded,
                    execution_class=execution_class, current_binding="current", reason_codes=())
            elif row.get("receipt_phase") not in (None, "not_sent", "confirmed"):
                cells["publication_confirmed"] = cov.stage(
                    "publication_confirmed", state="held", refs=[_ref(row)], recorded_at=recorded,
                    execution_class=execution_class, current_binding="current", reason_codes=("publication_unknown",))
            elif row.get("status") in ("pending", "approved"):
                holds.append("manual_review_pending")
        elif row["kind"] == "suppression":
            stage_name = str(row.get("stage") or "")
            code = ("budget_excluded" if stage_name in BUDGET_STAGES else "checks_failed" if stage_name in CHECK_STAGES
                    else "writer_rejected" if stage_name == "writer" else "selection_not_observed")
            cells.setdefault("checks_completed", cov.stage(
                "checks_completed", state="held", refs=[_ref(row)], recorded_at=recorded,
                execution_class=execution_class, current_binding="current", reason_codes=(code,)))
            holds.append(code)
    return list(cells.values()), sorted(set(holds))


def assess(record: dict, state: dict, *, cutoff: str, evaluated_at: str, state_version: int, policy_sha256: str,
           execution_class: str = "retained_runtime") -> dict:
    """The existing coverage assessment, with each unit's reviewable matching evidence attached."""
    from src.evaluation import reference_intake

    retained = reference_intake.retained_input(record)
    document = retained.value(cov.SET)["wrapper"]["document"]
    rows = production_rows(state)
    by_id = {row["id"]: row for row in rows}
    resolved = []
    summary = {"matched": 0, "ambiguous": 0, "near_match": 0, "unobserved": 0}
    for unit in document["units"]:
        match = match_unit(unit, record["labels"].get(unit["unit_id"], {}), rows)
        summary[match["status"] if match["status"] != "unmatched" else "unobserved"] += 1
        cells, holds = stages_for(match, by_id, execution_class=execution_class)
        resolved.append(cov.ResolvedUnit.create(unit_id=unit["unit_id"], source_label=unit["hazard_labels"][0]["label"],
                                                stages=cells, holds=holds, match=match))
    result = cov.evaluate(retained, resolved, cutoff=cutoff, evaluated_at=evaluated_at, state_version=state_version,
                          policy_sha256=policy_sha256, input_refs=[])
    return {**result, "production_match": {"schema": MATCH_SCHEMA, "rows_examined": len(rows), "summary": summary,
                                           "note": "Counts describe this supplied set only; they are not recall."}}


__all__ = ["MATCH_SCHEMA", "assess", "hazard", "match_unit", "production_rows", "stages_for"]
