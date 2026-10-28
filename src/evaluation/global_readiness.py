"""Connected offline global-readiness and human-review packet (read-only).

Joins explicitly supplied, detached exports of existing components by exact
identities and hashes only. No source, database, model or platform I/O; no
fetching, rendering or following of any value. A supplied label cannot overrule
missing evidence, a hash proves binding (not truth, review or freshness), and
without qualified reference eligibility recall and denominators stay null.
"""

from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any
from uuid import UUID

from src.commands.schema import utc_datetime
from src.data import source_product_contracts as products
from src.editorial import portfolio
from src.evaluation import coverage
from src.evaluation import rainfall_opportunity as rainfall
from src.storage import physical_events
from src.storage import postgres_projection as projection
from src.storage import retained_reports as reports
from src.storage import scientific_supply as supply

SCHEMA_VERSION = 1
PACKET_SCHEMA = "theheat.global-readiness-review-packet/v1"
COMPONENT_TYPES = ("source_products", "rainfall_opportunity", "scientific_supply", "physical_episode",
                   "report_development", "coverage_assessment", "portfolio")
PACKAGES = ("P09", "P09a", "P17", "P17a", "P17b", "P18", "P19", "P20", "P21", "P22", "P23")
MAX_COMPONENTS = 128
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
# Fixed exact product joins; a codec name is never matched by spelling.
SUPPLY_PRODUCT = {"ghcn-daily": "open_meteo_extreme_signals.ghcn_daily"}
EPISODE_PRODUCT = {"ep1:cyclone:nhc:": "nhc.current_storms_index"}
_PROJECTION_KEYS = {"lineage_id", "report_sha256", "source_label", "source_url", "original_language", "claims",
                    "upstream_lineage_refs", "limits", "holds", "reference_review", "development_status",
                    "related_story", "generation_available", "publication_enabled"}
_CLAIM_KEYS = {"claim_id", "kind", "summary", "original_language", "excerpts", "translation", "attribution", "times",
               "quantity", "geography", "holds"}
_COVERAGE_KEYS = {"schema_version", "contract", "set_ref", "cutoff", "evaluated_at", "state_version", "policy_sha256",
                  "input_refs", "currentness", "reference_readiness", "metrics", "units", "lineage_edges", "limits"}
_PLAN_KEYS = {"schema_version", "contract", "candidates", "selected_candidate_ids", "writing_attempts",
              "planning_policy", "planning_policy_sha256", "assessment_origin", "calibration_status", "cost_status",
              "provider_transport", "publication_approved", "production_authority", "evidence_discarded", "plan_sha256"}


class ReadinessError(ValueError):
    """Envelope-level refusal; carries one fixed code and no input text."""


def _envelope_require(condition: bool, code: str) -> None:
    if not condition:
        raise ReadinessError(code)


class _Unsupported(ValueError):
    pass


def _need(condition: bool, code: str) -> None:
    if not condition:
        raise _Unsupported(code)


def digest(value: Any) -> str:
    return projection._sha(projection._canonical(value))


def strict_loads(raw: bytes) -> Any:
    """JSON with duplicate keys, nonfinite numbers and oversized input refused."""
    _envelope_require(type(raw) is bytes and len(raw) <= MAX_INPUT_BYTES, "input_too_large")

    def pairs(items):
        keys = [key for key, _value in items]
        _envelope_require(len(keys) == len(set(keys)), "duplicate_json_key")
        return dict(items)

    def nonfinite(_value):
        raise ReadinessError("nonfinite_json_number")

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ReadinessError("invalid_json") from None


def validate_envelope(value: Any) -> tuple[datetime, list[dict[str, Any]]]:
    _envelope_require(type(value) is dict and set(value) == {"schema_version", "assessment_cutoff", "components"},
                      "envelope_keys")
    _envelope_require(type(value["schema_version"]) is int and value["schema_version"] == SCHEMA_VERSION,
                      "unsupported_schema_version")
    try:
        cutoff = utc_datetime(value["assessment_cutoff"])
    except ValueError:
        raise ReadinessError("assessment_cutoff_not_utc") from None
    components = value["components"]
    _envelope_require(type(components) is list and len(components) <= MAX_COMPONENTS, "components_bound")
    for item in components:
        _envelope_require(type(item) is dict and set(item) == {"component_type", "export"}, "component_keys")
        _envelope_require(type(item["component_type"]) is str and len(item["component_type"]) <= 64, "component_keys")
    try:
        projection._canonical(value)
    except projection.ProjectionError:
        raise ReadinessError("input_structure_bound") from None
    return cutoff, components


# Per-type adapters over the existing codecs. Each returns identity, facts and
# exact join keys; a refusal is retained as unsupported, never coerced.

def _source_products(export, cutoff):
    try:
        identity = products.verify_product_contract_document(export)
    except ValueError as exc:
        raise _Unsupported(str(exc)) from None
    unmet = sorted(row["field"] for row in export.get("unmet_criteria", []) if isinstance(row, dict))
    return ("contracts:" + identity, {
        "product_ids": sorted(row["product_id"] for row in export["products"]),
        "adapters": len(export["adapters"]),
        "missing_work": sorted(row["product_id"] for row in export["missing_work"]),
        "unknown_fields": unmet,
    }, [])


def _rainfall(export, cutoff):
    _need(type(export) is dict, "rainfall_export_shape")
    if export.get("schema") == rainfall.POPULATION_SCHEMA:
        try:
            checked = rainfall.validate_population(export)
        except rainfall.TraceError as exc:
            raise _Unsupported(str(exc)) from None
        return "population:" + checked["sha256"], {"kind": "population", "count": len(checked["members"])}, []
    try:
        checked = rainfall.validate_trace(export)
    except rainfall.TraceError as exc:
        raise _Unsupported(str(exc)) from None
    holds = []
    if checked["status"] == "incomplete":
        holds.append("trace_incomplete")
    if checked["run_id"] is None:
        holds.append("run_identity_missing")
    if checked["selection_date"] is not None and checked["selection_date"] > cutoff.date():
        holds.append("after_assessment_cutoff")
    facts = {"kind": "trace", "run_id": checked["run_id"],
             "selection_date": checked["selection_date"].isoformat() if checked["selection_date"] else None,
             "outcome": export.get("outcome"), "serving_leg": export.get("serving_leg"),
             "legs": sorted(leg["leg"] for leg in export.get("legs", [])),
             "population_sha256": (export.get("population") or {}).get("sha256"),
             "trace_status": checked["status"]}
    identity = "trace:" + (checked["run_id"] or "unidentified:" + digest(export))
    return identity, facts, holds


def _scientific_supply(export, cutoff):
    """Decode a detached supply envelope with the existing GHCN supply codec."""
    try:
        value = supply.detached_json(export)
        supply.require(type(value) is dict and set(value) == supply.ENVELOPE_KEYS, "supply_envelope_keys")
        supply.require(type(value["schema_version"]) is int and value["schema_version"] == 1, "unsupported_supply_codec")
        supply.require(value["source"] in SUPPLY_PRODUCT, "unsupported_supply_source")
        contract = value["producer_contract"]
        supply.require(type(contract) is dict and set(contract) == {"codec", "git_commit"} and contract["codec"] == "ghcn-supply-v1",
                       "unsupported_supply_codec")
        supply.require(type(contract["git_commit"]) is str and re.fullmatch(r"[0-9a-f]{40}", contract["git_commit"]) is not None,
                       "invalid_producer_revision")
        supply.require(type(value["supply_run_id"]) is str and str(UUID(value["supply_run_id"])) == value["supply_run_id"],
                       "invalid_supply_run_id")
        supply.require(type(value["captured_at"]) is str, "invalid_capture_time")
        captured = utc_datetime(value["captured_at"].replace("+00:00", "Z"))
        run_id = value["orchestrator_run_id"]
        supply.require(run_id is None or (type(run_id) is str and 0 < len(run_id) <= 160), "invalid_supply_run_id")
        outcome = value["source_outcome"]
        supply.require(type(outcome) is dict and set(outcome) == {"status", "threshold_verification", "error", "counters",
                                                                  "diff_missing_dates", "supply_empty"}, "invalid_supply_outcome")
        supply.require(type(outcome["counters"]) is dict and set(outcome["counters"]) == set(supply.COUNTERS)
                       and type(outcome["supply_empty"]) is bool, "invalid_supply_outcome")
        checked = supply._outcome({**outcome["counters"], **outcome})
        bundles = [supply._row(row, supply.model.ExtremeSignalBundle, decoding=True) for row in value["bundles"]]
        countries = [supply._row(row, supply.model.CountryRecord, decoding=True) for row in value["country_records"]]
        supply.require(outcome.get("supply_empty") == (not bundles), "invalid_supply_outcome")
        supply._unique(bundles, countries)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _Unsupported(str(exc) if isinstance(exc, supply.SupplyError) else "invalid_scientific_supply") from None
    holds = []
    if captured > cutoff:
        holds.append("after_assessment_cutoff")
    if checked["status"] != "success":
        holds.append("source_" + checked["status"])
    stations = sorted({bundle.station_id for bundle in bundles})
    # Complete retained supply: every qualified station, before any publication cap.
    return "supply:" + value["supply_run_id"], {
        "source": value["source"], "captured_at": value["captured_at"], "envelope_sha256": digest(value),
        "stations": stations, "station_count": len(stations), "bundles": len(bundles),
        "country_records": len(countries), "source_status": checked["status"],
        "threshold_verification": checked["threshold_verification"], "publication_caps_applied": False,
    }, holds


def _physical_episode(export, cutoff):
    try:
        binding = physical_events.validate_binding(export)
    except (ValueError, TypeError):
        raise _Unsupported("invalid_episode_binding") from None
    return f"episode:{binding['episode_id']}@{binding['revision_sha256']}", {
        "episode_id": binding["episode_id"], "revision_sha256": binding["revision_sha256"],
        "identity_class": binding["identity_class"], "source_assertions": len(binding["source_assertion_refs"]),
        "revision_time": "unknown_in_export",
    }, []


def _report(export, cutoff):
    try:
        reports.require(type(export) is dict and set(export) == _PROJECTION_KEYS, "report_projection_keys")
        reports.identifier(export["lineage_id"])
        reports.sha(export["report_sha256"])
        reports.require(type(export["claims"]) is list and 1 <= len(export["claims"]) <= 32, "report_projection_claims")
        reports.require(export["generation_available"] is False and export["publication_enabled"] is False,
                        "report_projection_permission")
        reports.require(export["development_status"] in {"not_opened", "evidence_review_required"}, "report_projection_status")
        holds = export["holds"]
        reports.require(type(holds) is list and "report_claims_not_promoted" in holds, "report_projection_holds")
        claims = []
        for claim in export["claims"]:
            reports.require(type(claim) is dict and set(claim) == _CLAIM_KEYS, "report_projection_claim")
            reports.identifier(claim["claim_id"])
            reports.require(claim["kind"] in reports.KINDS, "report_projection_claim")
            reports.require(type(claim["translation"]) is dict and type(claim["holds"]) is list, "report_projection_claim")
            reports.require(type(claim["times"]) is dict and set(claim["times"]) == reports.TIME_KEYS, "report_projection_claim")
            for value in claim["times"].values():
                reports.timestamp(value)
            reports.require(type(claim["excerpts"]) is list and len(claim["excerpts"]) <= 8, "report_projection_claim")
            anchors = []
            for anchor in claim["excerpts"]:
                reports.require(type(anchor) is dict and set(anchor) == {"text", "artifact_id", "content_sha256", "start", "end"},
                                "report_projection_anchor")
                reports.sha(anchor["artifact_id"])
                reports.sha(anchor["content_sha256"])
                reports.require(type(anchor["start"]) is int and type(anchor["end"]) is int
                                and 0 <= anchor["start"] < anchor["end"], "report_projection_anchor")
                anchors.append({key: anchor[key] for key in ("artifact_id", "content_sha256", "start", "end")})
            claims.append({"claim_id": claim["claim_id"], "kind": claim["kind"],
                           "original_language": claim["original_language"],
                           "translation_status": claim["translation"].get("status"),
                           "holds": sorted(claim["holds"]), "anchors": anchors,
                           # Original labels with their own precision; never normalised to one clock.
                           "times": {key: claim["times"][key] for key in sorted(claim["times"])}})
        story = export["related_story"]
        if story is not None:
            reports.require(type(story) is dict and set(story) == {"episode_id", "episode_head", "association_status",
                                                                   "time_compatibility"}, "report_projection_story")
            reports.sha(story["episode_head"])
            reports.require(story["association_status"] == "source_identity_reference_only", "report_projection_story")
    except (ValueError, TypeError, KeyError):
        raise _Unsupported("invalid_report_projection") from None
    held = sorted(set(holds))
    return f"report:{export['lineage_id']}@{export['report_sha256']}", {
        "lineage_id": export["lineage_id"], "report_sha256": export["report_sha256"],
        "original_language": export["original_language"], "development_status": export["development_status"],
        "claims": claims, "related_story": None if story is None else {"episode_id": story["episode_id"],
                                                                        "episode_head": story["episode_head"]},
        "retained_time": "unknown_in_export",
    }, held


def _coverage(export, cutoff):
    try:
        coverage.require(type(export) is dict and set(export) == _COVERAGE_KEYS, "coverage_export_keys")
        coverage.require(type(export["schema_version"]) is int and export["schema_version"] == 1
                         and export["contract"] == coverage.CONTRACT, "coverage_contract")
        coverage.reference(export["set_ref"], {coverage.SET})
        computed_cutoff, evaluated = utc_datetime(export["cutoff"]), utc_datetime(export["evaluated_at"])
        readiness = export["reference_readiness"]
        # Coverage v1 permits only not_qualified; anything else is not this contract.
        coverage.require(type(readiness) is dict and readiness.get("status") == "not_qualified", "coverage_qualified_state_unsupported")
        coverage.require(type(export["metrics"]) is dict and all(
            export["metrics"][key] is None for key in ("event_recall", "draft_recall", "publication_recall",
                                                       "timeliness", "confirmed_misses")), "coverage_metric_unsupported")
        units = []
        coverage.require(type(export["units"]) is list and len(export["units"]) <= 256, "coverage_inventory_bound")
        for unit in export["units"]:
            coverage.require(type(unit) is dict, "coverage_unit")
            coverage.identifier(unit["unit_id"])
            coverage.codes(unit["holds"])
            coverage.require(unit["reference_state"] in {"pending", "candidate_for_adjudication", "held", "excluded"})
            refs = []
            for ref in unit["report_refs"]:
                coverage.fixed(ref, "lineage_id report_sha256 claim_ids")
                coverage.identifier(ref["lineage_id"])
                coverage.sha(ref["report_sha256"])
                refs.append({"lineage_id": ref["lineage_id"], "report_sha256": ref["report_sha256"],
                             "claim_ids": sorted(ref["claim_ids"])})
            coverage.require(all(row["stage"] in coverage.STAGES for row in unit["stages"]), "coverage_stage")
            labels = unit["original_time_labels"]
            coverage.fixed(labels, "event_start event_end issued_at published_at first_available_at")
            for value in labels.values():
                coverage.timestamp(value)
            units.append({"unit_id": unit["unit_id"], "reference_state": unit["reference_state"],
                          "holds": sorted(unit["holds"]), "report_refs": refs, "original_time_labels": labels})
    except (ValueError, TypeError, KeyError, AttributeError):
        raise _Unsupported("invalid_coverage_assessment") from None
    holds = ["reference_not_qualified"]
    if computed_cutoff > cutoff or evaluated > cutoff:
        holds.append("after_assessment_cutoff")
    return "coverage:" + digest(export), {
        "cutoff": export["cutoff"], "evaluated_at": export["evaluated_at"], "reference_status": readiness["status"],
        "reasons": sorted(readiness.get("reasons", [])), "units": units, "metrics_null": True,
    }, holds


def _portfolio(export, cutoff):
    """Recompute the plan with the existing planner; only an exact match is accepted."""
    try:
        portfolio.require(type(export) is dict and set(export) == _PLAN_KEYS, "portfolio_export_keys")
        policy = export["planning_policy"]
        weights = tuple(policy["weights"][key] for key in portfolio.DIMENSIONS)
        candidates = [portfolio.PlanningCandidate(binding=row["binding"], hazard=row["hazard"],
                                                  regions=tuple(row["regions"]), dimensions=row["dimensions"],
                                                  exceptional_reason=row["exceptional_reason"])
                      for row in export["candidates"]]
        recomputed = portfolio.plan_portfolio(candidates, writing_attempts=export["writing_attempts"],
                                              policy=portfolio.PlanningPolicy(
                                                  weights=weights, topic_repeat_penalty=policy["topic_repeat_penalty"],
                                                  region_repeat_penalty=policy["region_repeat_penalty"],
                                                  minimum_score=policy["minimum_score"]))
        portfolio.require(projection._canonical(recomputed) == projection._canonical(export), "portfolio_plan_mismatch")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise _Unsupported(str(exc) if isinstance(exc, portfolio.PortfolioError) else "invalid_portfolio") from None
    holds = []
    if export["calibration_status"] != "human_calibrated":
        holds.append("not_human_calibrated")
    return "portfolio:" + export["plan_sha256"], {
        "calibration_status": export["calibration_status"], "assessment_origin": export["assessment_origin"],
        "cost_status": export["cost_status"], "selected": list(export["selected_candidate_ids"]),
        "candidates": [{"candidate_id": row["candidate_id"], "binding": row["binding"], "disposition": row["disposition"],
                        "missing_dimensions": row["missing_dimensions"]} for row in export["candidates"]],
    }, holds


_ADAPTERS = {"source_products": _source_products, "rainfall_opportunity": _rainfall,
             "scientific_supply": _scientific_supply, "physical_episode": _physical_episode,
             "report_development": _report, "coverage_assessment": _coverage, "portfolio": _portfolio}


def _decode_components(components, cutoff):
    rows = []
    for item in components:
        kind, export = item["component_type"], item["export"]
        row: dict[str, Any] = {"component_type": kind, "export_sha256": digest(export), "identity": None,
                               "status": "unsupported", "reasons": [], "facts": {}, "_export": export}
        if kind not in _ADAPTERS:
            row["reasons"] = ["unsupported_component_type"]
            row["component_type"] = "unsupported"
        else:
            try:
                identity, facts, holds = _ADAPTERS[kind](export, cutoff)
            except _Unsupported as exc:
                row["reasons"] = [str(exc) or "unsupported_export"]
            else:
                row.update(identity=identity, facts=facts, reasons=sorted(set(holds)),
                           status="held" if holds else "current")
        rows.append(row)
    # Exact copies count once; different bytes under one identity are held.
    by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["identity"] is not None:
            by_identity.setdefault((row["component_type"], row["identity"]), []).append(row)
    for group in by_identity.values():
        if len({row["export_sha256"] for row in group}) > 1:
            for row in group:
                row.update(status="conflict_held", reasons=sorted(set(row["reasons"]) | {"same_identity_different_export"}))
        else:
            for row in group[1:]:
                row.update(status="copy", reasons=sorted(set(row["reasons"]) | {"exact_copy_counted_once"}))
    _hold_ambiguous_revisions(rows)
    rows.sort(key=lambda row: (row["component_type"], row["identity"] or "", row["export_sha256"], row["status"]))
    return rows


def _hold_ambiguous_revisions(rows):
    """Several revisions of one episode/lineage or several contract versions: order unknown, all held."""
    def key(row):
        facts = row["facts"]
        if row["component_type"] == "physical_episode":
            return "episode", facts["episode_id"]
        if row["component_type"] == "report_development":
            return "report", facts["lineage_id"]
        if row["component_type"] == "source_products":
            return "contracts", "all"
        return None

    groups: dict[tuple[str, str], set[str]] = {}
    for row in rows:
        if row["status"] in {"current", "held"} and key(row) is not None:
            groups.setdefault(key(row), set()).add(row["identity"])
    for row in rows:
        if row["status"] in {"current", "held"} and key(row) is not None and len(groups[key(row)]) > 1:
            row.update(status="held", reasons=sorted(set(row["reasons"]) | {"revision_order_unknown"}))


def _current(rows, kind):
    return [row for row in rows if row["component_type"] == kind and row["status"] == "current"]


def _usable(rows, kind):
    """Current or held-for-a-recorded-reason, excluding conflicts/copies/unsupported."""
    return [row for row in rows if row["component_type"] == kind and row["status"] in {"current", "held"}]


def _joins(rows):
    joins = []

    def join(source, relation, target, disposition, reasons=()):
        joins.append({"from": source, "relation": relation, "to": target, "disposition": disposition,
                      "reasons": sorted(reasons)})

    contracts = _current(rows, "source_products")
    product_ids = set(contracts[0]["facts"]["product_ids"]) if len(contracts) == 1 else None
    held_contracts = [row for row in rows if row["component_type"] == "source_products" and row["status"] != "current"]

    def product_join(source, product_id):
        if product_ids is None:
            join(source, "product_contract", product_id,
                 "held_dependency" if held_contracts else "dependency_missing")
        else:
            join(source, "product_contract", product_id, "exact" if product_id in product_ids else "no_match")

    populations = {row["identity"].split(":", 1)[1]: row for row in _usable(rows, "rainfall_opportunity")
                   if row["facts"].get("kind") == "population"}
    for row in rows:
        if row["component_type"] == "rainfall_opportunity" and row["facts"].get("kind") == "trace" and \
                row["status"] in {"current", "held"}:
            for leg in row["facts"]["legs"]:
                product_join(row["identity"], "gpm_imerg." + leg)
            sha = row["facts"]["population_sha256"]
            join(row["identity"], "canonical_population", f"population:{sha}" if sha else None,
                 "exact" if sha in populations else "dependency_missing")
    for row in _usable(rows, "scientific_supply"):
        product_join(row["identity"], SUPPLY_PRODUCT[row["facts"]["source"]])
    episodes = {}
    episode_ids: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["component_type"] == "physical_episode" and row["identity"]:
            episode_ids.setdefault(row["facts"]["episode_id"], []).append(row)
            if row["status"] == "current":
                episodes[(row["facts"]["episode_id"], row["facts"]["revision_sha256"])] = row
    for row in _usable(rows, "physical_episode"):
        prefix = next(p for p in EPISODE_PRODUCT if row["facts"]["episode_id"].startswith(p))
        product_join(row["identity"], EPISODE_PRODUCT[prefix])

    def episode_join(source, relation, episode_id, revision):
        target = f"episode:{episode_id}@{revision}"
        if (episode_id, revision) in episodes:
            join(source, relation, target, "exact")
        elif episode_id in episode_ids:
            matching = [r for r in episode_ids[episode_id] if r["facts"]["revision_sha256"] == revision]
            if matching:
                join(source, relation, target, "held_dependency", matching[0]["reasons"])
            else:
                join(source, relation, target, "stale_binding", ["supplied_episode_has_other_revision"])
        else:
            join(source, relation, target, "dependency_missing")

    report_rows = {}
    lineages: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["component_type"] == "report_development" and row["identity"]:
            lineages.setdefault(row["facts"]["lineage_id"], []).append(row)
            if row["status"] in {"current", "held"} and "revision_order_unknown" not in row["reasons"]:
                report_rows[(row["facts"]["lineage_id"], row["facts"]["report_sha256"])] = row
    for row in _usable(rows, "report_development"):
        story = row["facts"]["related_story"]
        if story is None:
            join(row["identity"], "physical_episode", None, "not_linked", ["report_intake_only"])
        else:
            episode_join(row["identity"], "physical_episode", story["episode_id"], story["episode_head"])
    for row in _usable(rows, "coverage_assessment"):
        for unit in row["facts"]["units"]:
            for ref in unit["report_refs"]:
                target = f"report:{ref['lineage_id']}@{ref['report_sha256']}"
                source = f"{row['identity']}#{unit['unit_id']}"
                report = report_rows.get((ref["lineage_id"], ref["report_sha256"]))
                if report is not None:
                    claims = {claim["claim_id"] for claim in report["facts"]["claims"]}
                    missing = sorted(set(ref["claim_ids"]) - claims)
                    join(source, "report_revision", target, "claim_missing" if missing else "exact",
                         ["claim_not_in_report"] if missing else ())
                elif ref["lineage_id"] in lineages:
                    others = lineages[ref["lineage_id"]]
                    exact = [r for r in others if r["facts"]["report_sha256"] == ref["report_sha256"]]
                    join(source, "report_revision", target, "held_dependency" if exact else "stale_binding",
                         exact[0]["reasons"] if exact else ["supplied_report_has_other_revision"])
                else:
                    join(source, "report_revision", target, "dependency_missing")
    for row in _usable(rows, "portfolio"):
        for candidate in row["facts"]["candidates"]:
            binding = candidate["binding"]
            source = f"{row['identity']}#{candidate['candidate_id']}"
            if not binding["event_group_id"].startswith(tuple(EPISODE_PRODUCT)):
                join(source, "physical_episode", None, "unsupported_group_identity")
                continue
            episode_join(source, "physical_episode", binding["event_group_id"], binding["event_revision_sha256"])
    joins.sort(key=lambda row: (row["from"] or "", row["relation"], row["to"] or "", row["disposition"]))
    return joins


def _evidence_states(rows, joins):
    states: dict[str, list[str]] = {name: [] for name in (
        "current", "missing", "corrected_superseded", "held", "untranslated", "grouping_unresolved",
        "trace_incomplete", "dependency_blocked", "unsupported", "conflict_held")}
    for row in rows:
        label = row["identity"] or f"{row['component_type']}:{row['export_sha256']}"
        if row["status"] == "current":
            states["current"].append(label)
        elif row["status"] == "held":
            states["held"].append(label)
        elif row["status"] in {"unsupported", "conflict_held"}:
            states[row["status"]].append(label)
        if "trace_incomplete" in row["reasons"]:
            states["trace_incomplete"].append(label)
        if row["component_type"] == "report_development" and row["identity"]:
            for claim in row["facts"]["claims"]:
                if claim["translation_status"] == "unreviewed" or "translation_review_pending" in claim["holds"]:
                    states["untranslated"].append(f"{label}#{claim['claim_id']}")
        if row["component_type"] == "coverage_assessment" and row["identity"]:
            for unit in row["facts"]["units"]:
                if "grouping_unresolved" in unit["holds"]:
                    states["grouping_unresolved"].append(f"{label}#{unit['unit_id']}")
    present = {row["component_type"] for row in rows if row["status"] in {"current", "held"}}
    states["missing"] = [kind for kind in COMPONENT_TYPES if kind not in present]
    for join in joins:
        if join["disposition"] == "stale_binding":
            states["corrected_superseded"].append(f"{join['from']} -> {join['to']}")
        elif join["disposition"] in {"dependency_missing", "held_dependency"}:
            states["dependency_blocked"].append(f"{join['from']} -> {join['to'] or join['relation']}")
    return {key: sorted(set(values)) for key, values in states.items()}


def _rainfall_audit(rows):
    """Measured opportunity over current traces only; a separate, labelled section."""
    def current(kind):
        return [row["_export"] for row in rows if row["component_type"] == "rainfall_opportunity"
                and row["facts"].get("kind") == kind and row["status"] == "current"]
    traces = current("trace")
    return rainfall.evaluate(traces, current("population")) if traces else None


def _unmet(rows, joins, rainfall_audit):
    def has(kind):
        return any(row["component_type"] == kind and row["status"] in {"current", "held"} for row in rows)

    def ids(kind):
        return sorted(row["identity"] for row in rows if row["component_type"] == kind and row["identity"])

    unmet: dict[str, dict[str, Any]] = {}
    contracts = _current(rows, "source_products")
    p17 = ["product_contracts_missing"] if not contracts else [
        f"{field}_unknown" for field in contracts[0]["facts"]["unknown_fields"]]
    if contracts and contracts[0]["facts"]["missing_work"]:
        p17.append("unresolved_or_retired_legs_remain")
    traces = [row for row in rows if row["component_type"] == "rainfall_opportunity" and row["facts"].get("kind") == "trace"]
    p09 = ["operational_recovery_not_established", "threshold_and_self_heal_recovery_no_supported_input"]
    if not traces:
        p09.append("gpm_run_trace_missing")
    elif not any(row["facts"]["outcome"] == "primary_served" for row in traces if row["status"] == "current"):
        p09.append("no_supplied_trace_with_primary_service")
    p19 = ["achieved_revisit_sla_null", "cost_unattributed", "qualified_fresh_source_supply_missing"]
    if rainfall_audit is None:
        p19.append("auditable_trace_window_missing")
    elif not rainfall_audit["observed_complete_windows"]:
        p19.append("no_observed_complete_window")
    p18 = ["multi_hazard_independent_recall_missing", "hosted_workflow_acceptance_separate"]
    if not has("scientific_supply"):
        p18.insert(0, "scientific_supply_missing")
    p20 = ["non_nhc_hazard_identity_missing", "cross_border_split_merge_rules_missing", "independent_event_benchmark_missing"]
    if not has("physical_episode"):
        p20.insert(0, "physical_episode_missing")
    p21 = ["report_claims_not_promoted", "qualified_report_to_writer_contract_pending_review",
           "multilingual_independent_recall_missing"]
    if not has("report_development"):
        p21.insert(0, "report_development_missing")
    if any(join["relation"] == "physical_episode" and join["from"].startswith("report:") and join["disposition"] != "exact"
           for join in joins):
        p21.append("report_episode_join_not_exact")
    p22 = ["denominator_not_qualified", "independent_events_quiet_periods_missing", "scientific_labels_missing"]
    if not has("coverage_assessment"):
        p22.insert(0, "coverage_assessment_missing")
    p23 = ["independent_human_ranking_missing", "spend_enforcement_separate_from_coverage",
           "exceptional_event_policy_unreviewed"]
    if not has("portfolio"):
        p23.insert(0, "portfolio_missing")
    elif any("not_human_calibrated" in row["reasons"] for row in rows if row["component_type"] == "portfolio"):
        p23.append("not_human_calibrated")
    table = {
        "P09": (p09, ids("rainfall_opportunity")),
        "P09a": (["barrow_granule_reconciliation_no_supported_input", "rainfall_automation_held"],
                 ids("rainfall_opportunity")),
        "P17": (p17, ids("source_products")),
        "P17a": (["qualified_observed_pilot_no_supported_input", "incremental_recall_comparison_missing"], []),
        "P17b": (["reference_gap_selection_blocked_unqualified_baseline", "pilot_source_qualification_missing"],
                 ids("coverage_assessment")),
        "P18": (p18, ids("scientific_supply")),
        "P19": (p19, ids("rainfall_opportunity")),
        "P20": (p20, ids("physical_episode")),
        "P21": (p21, ids("report_development")),
        "P22": (p22, ids("coverage_assessment")),
        "P23": (p23, ids("portfolio")),
    }
    for package in PACKAGES:
        codes, evidence = table[package]
        unmet[package] = {"status": "open", "unmet": sorted(set(codes)), "evidence_components": evidence}
    return unmet


def _review_packet(rows):
    """Exact missing decisions and anchors; never a vote, label, translation or approval."""
    items = []
    for row in rows:
        if row["status"] not in {"current", "held"}:
            continue
        if row["component_type"] == "report_development":
            for claim in row["facts"]["claims"]:
                questions = set(claim["holds"]) | set(row["reasons"]) - {"report_claims_not_promoted"}
                if claim["translation_status"] == "unreviewed":
                    questions.add("translation_review_pending")
                for question in sorted(questions):
                    items.append({"subject": f"{row['identity']}#{claim['claim_id']}", "question": question,
                                  "source_anchors": claim["anchors"], "decision": None, "decided_by": None})
        elif row["component_type"] == "coverage_assessment":
            for unit in row["facts"]["units"]:
                for question in unit["holds"]:
                    items.append({"subject": f"{row['identity']}#{unit['unit_id']}", "question": question,
                                  "source_anchors": unit["report_refs"], "decision": None, "decided_by": None})
        elif row["component_type"] == "portfolio":
            for candidate in row["facts"]["candidates"]:
                for dimension in candidate["missing_dimensions"]:
                    items.append({"subject": f"{row['identity']}#{candidate['candidate_id']}",
                                  "question": f"dimension_unassessed:{dimension}", "source_anchors": [candidate["binding"]],
                                  "decision": None, "decided_by": None})
                items.append({"subject": f"{row['identity']}#{candidate['candidate_id']}",
                              "question": "independent_human_rank_missing", "source_anchors": [candidate["binding"]],
                              "decision": None, "decided_by": None})
    items.sort(key=lambda item: (item["subject"], item["question"]))
    return {"schema": PACKET_SCHEMA, "decisions_needed": items, "reviewer_identity": None,
            "creates_votes_labels_translations_or_approvals": False}


def assess(envelope: Any) -> dict[str, Any]:
    """Bounded readiness JSON for one validated envelope."""
    cutoff, components = validate_envelope(envelope)
    rows = _decode_components(components, cutoff)
    joins = _joins(rows)
    audit = _rainfall_audit(rows)
    for row in rows:
        del row["_export"]
    result = {
        "schema_version": SCHEMA_VERSION,
        "assessment_cutoff": envelope["assessment_cutoff"],
        "input_sha256": digest({"schema_version": SCHEMA_VERSION, "assessment_cutoff": envelope["assessment_cutoff"],
                                "components": sorted(digest(item) for item in components)}),
        "components": rows,
        "joins": joins,
        "evidence_states": _evidence_states(rows, joins),
        "unmet_requirements": _unmet(rows, joins, audit),
        "global_recall": None,
        "coverage_denominator": None,
        "recall_basis": "no_qualified_reference_eligibility",
        "provider_currentness": "not_established",
        "rainfall_opportunity": None if audit is None else {
            "label": "measured_rainfall_opportunity_not_global_recall",
            "observed_complete_windows": audit["observed_complete_windows"],
            "opportunity_member_runs": audit["opportunity_member_runs"],
            "request_counts": audit["request_counts"], "cost": audit["cost"],
            "achieved_revisit_sla": None, "global_recall": None,
            "calendar_statuses": sorted({row["status"] for row in audit["calendar"]}),
        },
        "human_review_packet": _review_packet(rows),
        "limits": [
            "Joins use exact identities and hashes only; no place, date, coordinate or headline matching.",
            "A hash proves binding, not scientific truth, independent review or provider freshness.",
            "Local revision currency is not provider availability; no ambient clock is used.",
            "Existing operator ordinal scores are uncalibrated judgments, not independent human ranking.",
        ],
    }
    rendered = projection._canonical(result)
    _envelope_require(len(rendered) <= MAX_OUTPUT_BYTES, "output_too_large")
    return projection._decode(rendered)


def _inert(value: Any) -> str:
    """Escape every control and non-ASCII character; nothing is rendered or followed."""
    return json.dumps(value if isinstance(value, str) else str(value), ensure_ascii=True)[1:-1]


def render_text(result: dict[str, Any]) -> str:
    """Inert plain-text review listing; values are escaped data, never markup."""
    lines = [f"Global readiness (schema {result['schema_version']}), cutoff {_inert(result['assessment_cutoff'])}",
             f"Input sha256 {result['input_sha256']}", "Global recall: null (no qualified reference eligibility)", ""]
    lines.append("Components:")
    for row in result["components"]:
        lines.append(f"  {_inert(row['component_type'])} {_inert(row['identity'] or row['export_sha256'])}: "
                     f"{row['status']} {_inert(','.join(row['reasons']))}")
    lines.append("Joins:")
    for join in result["joins"]:
        lines.append(f"  {_inert(join['from'])} -[{join['relation']}]-> {_inert(join['to'])}: {join['disposition']}")
    lines.append("Unmet by original package (all remain open):")
    for package, row in result["unmet_requirements"].items():
        lines.append(f"  {package}: {_inert(', '.join(row['unmet']))}")
    lines.append("Decisions needed (none is made here):")
    for item in result["human_review_packet"]["decisions_needed"]:
        lines.append(f"  {_inert(item['subject'])}: {_inert(item['question'])}")
    return "\n".join(lines) + "\n"
