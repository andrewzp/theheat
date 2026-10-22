"""Passive selected GHCN claim projection and reference shape.

These checks mint no source, execution, spending, check or approval authority.
The live typed resolver remains in ghcn_claim_view; this module is sealed-safe.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from datetime import date
import json
import math
import re
from uuid import UUID

from src.two_bot.json_utils import json_default
from src.two_bot.types import StoryBundle

INPUT = "ghcn-source-result-input-v1"
RESULT = "ghcn-source-runtime-result-v1"
NAMESPACE = "scientific-supply-ghcn-v1"


class ClaimContractError(ValueError):
    """The existing bounded reference/projection codes, without storage imports."""


class ClaimJSONError(ValueError):
    """The command JSON boundary's existing code/message, without its authority."""
    code = "invalid_json"


def require(condition, code="invalid_cyclone_supply"):
    if not condition:
        raise ClaimContractError(code)


def sha(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)
    return value


def uuid(value):
    try:
        require(type(value) is str and str(UUID(value)) == value, "invalid_cyclone_identity")
    except (ValueError, AttributeError):
        raise ClaimContractError("invalid_cyclone_identity") from None
    return value


def _fixed(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), "ghcn_input_shape")


def canonical_json(value):
    try:
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        text.encode("utf-8")
        return text
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ClaimJSONError("Command must contain valid, finite JSON data") from exc


TYPES = dict(calendar_date_high="record", calendar_date_low="record_low", all_time_high="all_time_high",
    all_time_low="all_time_low", monthly_high="monthly_high", monthly_low="monthly_low",
    anomaly_hot="anomaly_hot", anomaly_cold="anomaly_cold", absolute_extreme="absolute_extreme")
BASELINE_FIELDS = set("schema_version source_product station_id evidence_type comparison_scope comparison_before cutoff requested_comparison_cutoff retrieved_at source_payload_sha256 reconciled variables revision_id".split())
VARIABLE_SCALARS = set("sample_count expected_count coverage_fraction complete years_with_samples start cutoff conflicting_dates previous_value_c previous_date requested_comparison_cutoff source_calendar_count source_coverage_complete source_coverage_fraction source_gap_count source_latest_cell source_missing_count source_qc_rejected_count verified_source_cutoff".split())
TABLE_FIELDS = set("monthly_years calendar_years calendar_samples monthly_samples record_dates record_values_c".split())
EVIDENCE_FIELDS = set("aggregation baseline domain evidence_type issued_at model_run publication_time_qc_known reporting_interval_known retrieved_at revision_id source_product station_id timezone unit valid_date valid_end valid_start variables".split())


def json_tree(value):
    return json.loads(json.dumps(value,sort_keys=True,default=json_default,allow_nan=False))


def _selected_scope(scope, field, day, *, anomaly_mean=None, anomaly_variable=False):
    require(type(scope) is dict and VARIABLE_SCALARS <= set(scope)
            and set(scope) <= VARIABLE_SCALARS | TABLE_FIELDS | {"candidate_accepted"}, "ghcn_claim_variable_schema")
    require(TABLE_FIELDS <= set(scope), "ghcn_claim_variable_schema")
    for table_name in TABLE_FIELDS:
        require(type(scope[table_name]) is dict, "ghcn_claim_table_schema")
    for table_name in ("record_dates", "record_values_c"):
        require(set(scope[table_name]) == {"all_time", "monthly", "calendar"}
                and type(scope[table_name]["monthly"]) is dict and type(scope[table_name]["calendar"]) is dict, "ghcn_claim_record_schema")
    # All non-table evidence is retained exactly, including unknown/null values,
    # both variables' coverage distinctions and every conflicting date.
    selected = {key:deepcopy(value) for key,value in scope.items() if key not in TABLE_FIELDS}
    key: str | None
    if field.startswith("calendar_"):
        period,key="calendar",day[5:]
    elif field.startswith(("monthly_","anomaly_")):
        period,key="monthly",day[5:7]
    elif field.startswith("all_time_"):
        period,key="all_time",None
    else:
        selected["selected_comparison"]=None
        return selected
    if key is None:
        years,samples=scope["years_with_samples"],scope["sample_count"]
        old_value,old_date=scope["record_values_c"][period],scope["record_dates"][period]
    else:
        years=scope[period+"_years"].get(key)
        samples=scope[period+"_samples"].get(key)
        old_value=scope["record_values_c"][period].get(key)
        old_date=scope["record_dates"][period].get(key)
    if field.startswith("anomaly_"):
        # An anomaly compares against the qualified variable's monthly mean,
        # never its monthly extreme. The other variable retains coverage only.
        comparison=dict(period=period,key=key,years_with_samples=years,sample_count=samples,
            purpose="monthly_mean_scope" if anomaly_variable else "monthly_coverage_only")
        if anomaly_variable:
            require(type(anomaly_mean) in (int,float) and math.isfinite(anomaly_mean), "ghcn_claim_anomaly_mean")
            comparison["mean_c"]=anomaly_mean
        selected["selected_comparison"]=comparison
    else:
        selected["selected_comparison"]=dict(period=period,key=key,years_with_samples=years,
            sample_count=samples,prior_value_c=old_value,prior_date=old_date,purpose="record_comparator")
    return selected


def _narrowed(data, selection):
    evidence=data["raw_signal_dump"]["evidence"]
    require(type(evidence) is dict and set(evidence)==EVIDENCE_FIELDS, "ghcn_claim_evidence_schema")
    require(evidence["source_product"]=="noaa-ghcn-daily-v2" and evidence["evidence_type"]=="observed"
            and evidence["station_id"]==selection["station_id"] and evidence["valid_date"]==selection["signal_date"], "ghcn_claim_source_changed")
    baseline=evidence["baseline"]
    require(type(baseline) is dict and set(baseline)==BASELINE_FIELDS and baseline["schema_version"]==2,
            "ghcn_claim_baseline_schema")
    require(type(baseline["variables"]) is dict and set(baseline["variables"])=={"temperature_2m_max","temperature_2m_min"}, "ghcn_claim_variables_schema")
    require(data["historical_context"].get("baseline")==baseline, "ghcn_claim_projection_changed")
    narrowed={key:deepcopy(value) for key,value in baseline.items() if key!="variables"}
    anomaly_variable={"anomaly_hot":"temperature_2m_max","anomaly_cold":"temperature_2m_min"}.get(selection["signal_field"])
    narrowed["variables"]={key:_selected_scope(value,selection["signal_field"],selection["signal_date"],
        anomaly_mean=data["raw_signal_dump"].get("historical_mean_c"),anomaly_variable=key==anomaly_variable)
        for key,value in baseline["variables"].items()}
    narrowed["representation"]="selected_claim_warrants_v1; complete tables retained by source reference"
    return narrowed


def project(full: StoryBundle, reference: dict, selection: dict) -> StoryBundle:
    """Pure closed projection. No storage or scientific authority is minted here."""
    narrowed=_narrowed(json_tree(full.to_dict()),selection)
    compact=deepcopy(full)  # Never call the mutating constructor on stored facts.
    compact.raw_signal_dump["evidence"]["baseline"]=deepcopy(narrowed)
    compact.historical_context["baseline"]=deepcopy(narrowed)
    compact.raw_signal_dump["ghcn_claim_view"]=deepcopy(reference)
    return compact


def project_tree(full: dict, reference: dict, selection: dict) -> dict:
    """project() over retained JSON: replays a saved view from its full evidence.

    A retained graphic binding holds JSON, not a StoryBundle; rebuilding one would
    rerun its mutating evidence projection. Equal output is the pairing proof.
    """
    data=json_tree(full)
    narrowed=_narrowed(data,selection)
    data["raw_signal_dump"]["evidence"]["baseline"]=deepcopy(narrowed)
    data["historical_context"]["baseline"]=deepcopy(narrowed)
    data["raw_signal_dump"]["ghcn_claim_view"]=deepcopy(reference)
    return data


def structural_view(value):
    """Passive closed shape only: no source replay, baseline, or scientific pass."""
    names={f.name for f in fields(StoryBundle)}
    optional={"country","related_signals","human_impact"}
    require(type(value) is dict and names-optional <= set(value) <= names,"ghcn_claim_view_shape")
    require(all(value[key] for key in optional if key in value),"ghcn_claim_view_shape")
    require(len(canonical_json(value).encode())<=32768,"ghcn_claim_view_bound")
    raw=value["raw_signal_dump"]
    require(type(raw) is dict and type(raw.get("ghcn_claim_view")) is dict,"ghcn_claim_view_shape")
    ref=raw["ghcn_claim_view"]
    _fixed(ref,"schema_version kind scope source_run_id source_result runtime_input scientific_supply selection member_sha256 full_story observation_revision baseline_revision baseline_artifact original_archives")
    require(type(ref["schema_version"]) is int and ref["schema_version"]==1
        and ref["kind"]=="ghcn_claim_view_v1" and ref["scope"]=="selected_claim_warrants","ghcn_claim_view_shape")
    uuid(ref["source_run_id"])
    selection=ref["selection"]
    _fixed(selection,"station_id signal_date signal_field")
    require(selection["signal_field"] in TYPES and type(selection["signal_date"]) is str,"ghcn_claim_view_shape")
    try:
        selected_day = date.fromisoformat(selection["signal_date"])
    except ValueError:
        raise ClaimContractError("ghcn_claim_view_shape") from None
    require(selected_day.isoformat()==selection["signal_date"],"ghcn_claim_view_shape")
    for key,namespace in (("source_result",RESULT),("runtime_input",INPUT),("scientific_supply",NAMESPACE)):
        item=ref[key]
        _fixed(item,"namespace snapshot_id sha256")
        require(item["namespace"]==namespace and item["snapshot_id"]=="run:"+ref["source_run_id"],"ghcn_claim_view_reference")
        sha(item["sha256"])
    _fixed(ref["full_story"],"codec sha256")
    require(ref["full_story"]["codec"]=="revision-fingerprint-v1-json-default","ghcn_claim_view_reference")
    sha(ref["full_story"]["sha256"])
    sha(ref["member_sha256"])
    _fixed(ref["baseline_artifact"],"database_sha256 manifest_sha256")
    for pin in ref["baseline_artifact"].values():
        sha(pin)
    archives=ref["original_archives"]
    require(type(archives) is list and len(archives)==1,"ghcn_claim_view_reference")
    _fixed(archives[0],"kind key retrieved_at status raw_sha256 failure_code")
    require(archives[0]["kind"]=="station_archive" and archives[0]["key"]==selection["station_id"]
        and archives[0]["status"]=="success" and archives[0]["failure_code"] is None,"ghcn_claim_view_reference")
    sha(archives[0]["raw_sha256"])
    return ref
