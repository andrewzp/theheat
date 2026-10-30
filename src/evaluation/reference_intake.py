"""Bounded local intake of supplied reference events and quiet periods (W15.1).

Builds the existing coverage reference-set document (``coverage.reference_set``)
and its retained input from an explicitly supplied intake file. Label source,
support, uncertainty and exclusions are kept in a sidecar keyed by unit, because
the frozen set schema has no place for them. Source-discovered candidates and
historical posts are refused as reference opportunities and listed separately;
an excluded or out-of-scope event never becomes a unit. Population
qualification stays ``not_qualified``: the readiness report says which parts of a
genuine future denominator are present and which are missing, and recall stays
null. No network, model, Gist or database access occurs here.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from src.evaluation import coverage as cov

SCHEMA = "theheat.reference-intake/v1"
RECORD_SCHEMA = "theheat.reference-intake-record/v1"
MAX_EVENTS = 64
MAX_UNITS = 16  # the reference-set schema bound; larger intakes are split by the operator
UNIT_KINDS = {"reported_episode_candidate", "physical_event_candidate", "forecast_candidate", "project_report_candidate"}
SOURCE_CLASSES = {"reported", "observed", "forecast", "warning", "project", "unknown"}
ORIGINS = {"reference", "source_discovered", "historical_post"}
_SHA = re.compile(r"[a-f0-9]{64}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
EVENT_KEYS = {"event_id", "origin", "kind", "source_class", "hazards", "regions", "event_start", "event_end", "issued_at",
              "published_at", "first_available_at", "label_source", "uncertainty", "exclusion", "report",
              "production_aliases", "deadline_at", "deadline_policy_sha256", "translation_pending"}
REQUIRED_EVENT_KEYS = {"event_id", "origin", "kind", "source_class", "hazards", "regions", "event_start", "event_end",
                       "label_source"}


class IntakeError(ValueError):
    """Bounded codes only; supplied text never enters the message."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise IntakeError(code)


def _artifact(sha256: str) -> dict:
    _require(isinstance(sha256, str) and bool(_SHA.fullmatch(sha256)), "evidence_sha256")
    return {"namespace": "retained-report-artifact-v1", "snapshot_id": sha256, "sha256": sha256}


def _time(value: Any) -> dict | None:
    """Instant (UTC ``Z``), calendar date, or absent; a date never becomes midnight UTC."""
    if value is None:
        return None
    _require(isinstance(value, str), "time_shape")
    if _DATE.fullmatch(value):
        out = {"original": value, "utc": None, "date": value, "precision": "calendar", "timezone": None}
    else:
        try:
            cov.utc_datetime(value)
        except Exception as exc:
            raise IntakeError("time_shape") from exc
        out = {"original": value, "utc": value, "date": None, "precision": "instant", "timezone": "UTC"}
    cov.timestamp(out)
    return out


def _labels(rows: Any) -> tuple[list[dict], list[dict]]:
    _require(isinstance(rows, list) and len(rows) <= 16, "labels_shape")
    labels, support = [], []
    for row in rows:
        _require(isinstance(row, dict) and set(row) <= {"label", "evidence_sha256", "support"}
                 and isinstance(row.get("label"), str) and 0 < len(row["label"].strip()) <= 100, "label_shape")
        labels.append({"label": row["label"].strip(), "evidence_ref": _artifact(row.get("evidence_sha256"))})
        support.append({"label": row["label"].strip(), "evidence_sha256": row["evidence_sha256"],
                        "support": row.get("support") if isinstance(row.get("support"), str) else None})
    return labels, support


def _unit(event: dict) -> tuple[dict, dict]:
    hazards, hazard_support = _labels(event["hazards"])
    regions, region_support = _labels(event["regions"])
    _require(bool(hazards) and bool(regions), "labels_required")
    times = {key: _time(event.get(key)) for key in ("event_start", "event_end", "issued_at", "published_at",
                                                    "first_available_at")}
    report = event.get("report")
    report_refs = []
    if report is not None:
        _require(isinstance(report, dict) and set(report) == {"lineage_id", "report_sha256", "claim_ids"}, "report_shape")
        report_refs.append(deepcopy(report))
    deadline: dict[str, Any] = {"at": None, "policy_ref": None}
    if event.get("deadline_at") is not None:
        deadline = {"at": _time(event["deadline_at"]), "policy_ref": _artifact(str(event.get("deadline_policy_sha256")))}
    holds = ["reference_pending"]
    if event.get("translation_pending") is True:
        holds.append("translation_pending")
    unit = {"unit_id": event["event_id"], "predecessor_unit_refs": [], "unit_kind": event["kind"],
            "report_refs": report_refs, "source_alias_refs": [], "grouping_decision_refs": [],
            "hazard_labels": hazards, "region_memberships": regions, "source_class": event["source_class"],
            "time_fields": times, "availability_evidence_refs": [], "deadline": deadline,
            "relevance_decision_ref": None, "qualification_decision_refs": [], "state": "pending", "hold_codes": holds}
    cov.unit(unit)
    aliases = event.get("production_aliases") or []
    _require(isinstance(aliases, list) and len(aliases) <= 8
             and all(isinstance(a, str) and 0 < len(a) <= 160 for a in aliases), "aliases_shape")
    sidecar = {"label_source": event["label_source"][:300], "uncertainty": (event.get("uncertainty") or None),
               "hazard_support": hazard_support, "region_support": region_support, "production_aliases": list(aliases)}
    return unit, sidecar


def _quiet(period: dict, protocol_ref: dict) -> dict:
    _require(isinstance(period, dict) and {"period_id", "hazards", "regions", "source_classes", "start", "end"}
             <= set(period), "quiet_shape")
    inventory = [_artifact(s) for s in period.get("required_source_inventory_sha256s", [])]
    traces = [_artifact(s) for s in period.get("availability_trace_sha256s", [])]
    window = {"start": _time(period["start"]), "end": _time(period["end"])}
    _require(all(window.values()), "quiet_window_required")
    complete = bool(inventory) and bool(traces)
    return {"period_id": period["period_id"],
            "scope": {"hazards": list(period["hazards"]), "regions": list(period["regions"]),
                      "source_classes": list(period["source_classes"])},
            "window": window, "selection_protocol_ref": protocol_ref,
            "required_source_inventory_refs": inventory, "availability_trace_refs": traces,
            "reviewer_decision_ref": None, "state": "adjudication_pending" if complete else "evidence_incomplete",
            "hold_codes": ["quiet_period_unqualified"]}


def intake(document: Any, *, retained_at: str) -> dict:
    """A validated intake record: reference set, retained input, sidecars and readiness."""
    _require(isinstance(document, dict) and document.get("schema") == SCHEMA, "intake_schema")
    selection = document.get("selection")
    _require(isinstance(selection, dict) and selection.get("method") in ("independent_convenience_sample", "invented_fixture")
             and isinstance(selection.get("independent_of_bot_output"), bool), "selection_shape")
    protocol_ref = _artifact(str(selection.get("protocol_document_sha256")))
    events = document.get("events")
    _require(isinstance(events, list) and 0 < len(events) <= MAX_EVENTS, "event_count")
    units, sidecars, excluded, not_reference, seen = [], {}, [], [], set()
    for event in events:
        _require(isinstance(event, dict) and REQUIRED_EVENT_KEYS <= set(event) <= EVENT_KEYS, "event_shape")
        _require(event["origin"] in ORIGINS and event["kind"] in UNIT_KINDS and event["source_class"] in SOURCE_CLASSES,
                 "event_enum")
        _require(isinstance(event["event_id"], str) and event["event_id"] not in seen, "event_id")
        cov.identifier(event["event_id"])
        seen.add(event["event_id"])
        if event["origin"] != "reference":
            # A bot-discovered candidate or a known historical post is not an independent opportunity.
            not_reference.append({"event_id": event["event_id"], "origin": event["origin"],
                                  "reason": "not_an_independent_reference_opportunity"})
            continue
        if event.get("exclusion"):
            excluded.append({"event_id": event["event_id"], "reason": str(event["exclusion"])[:300],
                             "label_source": event["label_source"][:300]})
            continue
        unit, sidecar = _unit(event)
        units.append(unit)
        sidecars[unit["unit_id"]] = sidecar
    _require(bool(units), "no_reference_units")
    _require(len(units) <= MAX_UNITS, "coverage_inventory_bound")
    window = document.get("comparison_window") or {}
    reference_set = {
        "schema_version": 1, "set_id": document.get("set_id"), "previous_set_sha256": document.get("previous_set_sha256"),
        "selection_protocol": {"protocol_ref": protocol_ref, "scope_label": str(selection.get("scope_label", ""))[:300],
                               "selection_method": selection["method"],
                               "independent_of_bot_output": selection["independent_of_bot_output"],
                               "population_status": "unqualified"},
        "comparison_window": {"start": _time(window.get("start")), "end": _time(window.get("end"))},
        "units": units,
        "quiet_periods": [_quiet(period, protocol_ref) for period in document.get("quiet_periods", [])],
        "human_decision_refs": [],
        "qualification": {"status": "not_qualified",
                          "reason_codes": ["denominator_not_qualified", "reference_selection_unqualified"]},
        "created_at": document.get("created_at"),
    }
    try:
        validated = cov.reference_set(reference_set)
    except cov.CoverageError as exc:
        raise IntakeError(str(exc)) from exc
    wrapper = {"sequence": 1 if reference_set["previous_set_sha256"] is None else 2, "document": validated}
    pointer = {"namespace": cov.SET, "snapshot_id": cov.digest(validated["set_id"]) + f":{wrapper['sequence']:010d}",
               "sha256": cov.digest(wrapper)}
    retained = cov.RetainedInput.create(reference=pointer, wrapper=wrapper, retained_at=retained_at)
    return {"schema": RECORD_SCHEMA, "reference": pointer, "retained": retained.value(),
            "labels": sidecars, "excluded": excluded, "not_reference_opportunities": not_reference,
            "denominator": denominator_readiness(validated, selection),
            "metrics": {"event_recall": None, "reason": "denominator_not_qualified"}}


def denominator_readiness(reference_set: dict, selection: dict) -> dict:
    """What a future measured denominator still needs; met items are evidence, not qualification."""
    units = reference_set["units"]
    quiet = reference_set["quiet_periods"]
    requirements = {
        "independent_selection": selection["method"] == "independent_convenience_sample"
        and selection["independent_of_bot_output"] is True,
        "first_availability_recorded": all(u["time_fields"]["first_available_at"] is not None for u in units),
        "deadline_policy_recorded": all(u["deadline"]["policy_ref"] is not None for u in units),
        "relevance_decisions_recorded": all(u["relevance_decision_ref"] is not None for u in units),
        "quiet_period_inventory_and_traces": bool(quiet) and all(q["state"] == "adjudication_pending" for q in quiet),
    }
    return {"status": "not_qualified", "requirements": {k: "met" if v else "missing" for k, v in requirements.items()},
            "always_required": "A reviewed population-qualification contract; the current reference-set schema "
                               "refuses qualification, so no recall or miss rate is computed from this set."}


def retained_input(record: dict) -> cov.RetainedInput:
    """Rebuild the exact retained input from a saved intake record (verifies identity)."""
    _require(isinstance(record, dict) and record.get("schema") == RECORD_SCHEMA, "record_schema")
    retained = record["retained"]
    return cov.RetainedInput.create(reference=retained["reference"], wrapper=retained["wrapper"],
                                    retained_at=retained["retained_at"])


__all__ = ["IntakeError", "RECORD_SCHEMA", "SCHEMA", "denominator_readiness", "intake", "retained_input"]
