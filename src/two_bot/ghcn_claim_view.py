"""A selected claim view, rebuilt from complete locally retained GHCN evidence.

This is request preparation only. It does not create a spend/check/approval
context; ordinary candidate hydration explicitly refuses this reference format.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import time

from src.commands import postgres_ghcn_source_results as domain
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.orchestrator.two_bot_dispatch import _two_bot_bundle_for_extreme_signal
from src.storage import ghcn_runtime_inputs as inputs
from src.storage.cyclone_supply import digest, environment, require, uuid
from src.storage.scientific_supply import NAMESPACE, _row, _outcome, model
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.json_utils import json_default
from src.two_bot.types import StoryBundle

TYPES = dict(calendar_date_high="record", calendar_date_low="record_low", all_time_high="all_time_high",
    all_time_low="all_time_low", monthly_high="monthly_high", monthly_low="monthly_low",
    anomaly_hot="anomaly_hot", anomaly_cold="anomaly_cold", absolute_extreme="absolute_extreme")
BASELINE_FIELDS = set("schema_version source_product station_id evidence_type comparison_scope comparison_before cutoff requested_comparison_cutoff retrieved_at source_payload_sha256 reconciled variables revision_id".split())
VARIABLE_SCALARS = set("sample_count expected_count coverage_fraction complete years_with_samples start cutoff conflicting_dates previous_value_c previous_date requested_comparison_cutoff source_calendar_count source_coverage_complete source_coverage_fraction source_gap_count source_latest_cell source_missing_count source_qc_rejected_count verified_source_cutoff".split())
TABLE_FIELDS = set("monthly_years calendar_years calendar_samples monthly_samples record_dates record_values_c".split())
EVIDENCE_FIELDS = set("aggregation baseline domain evidence_type issued_at model_run publication_time_qc_known reporting_interval_known retrieved_at revision_id source_product station_id timezone unit valid_date valid_end valid_start variables".split())


def json_tree(value):
    return json.loads(json.dumps(value,sort_keys=True,default=json_default,allow_nan=False))


def _selected_scope(scope, field, day):
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
    selected["selected_comparison"]=dict(period=period,key=key,years_with_samples=years,
        sample_count=samples,prior_value_c=old_value,prior_date=old_date,
        purpose="monthly_mean_scope" if field.startswith("anomaly_") else "record_comparator")
    return selected


def project(full: StoryBundle, reference: dict, selection: dict) -> StoryBundle:
    """Pure closed projection. No storage or scientific authority is minted here."""
    data=json_tree(full.to_dict())
    evidence=data["raw_signal_dump"]["evidence"]
    require(type(evidence) is dict and set(evidence)==EVIDENCE_FIELDS, "ghcn_claim_evidence_schema")
    require(evidence["source_product"]=="noaa-ghcn-daily-v2" and evidence["evidence_type"]=="observed"
            and evidence["station_id"]==selection["station_id"] and evidence["valid_date"]==selection["signal_date"], "ghcn_claim_source_changed")
    baseline=evidence["baseline"]
    require(type(baseline) is dict and set(baseline)==BASELINE_FIELDS and baseline["schema_version"]==2,
            "ghcn_claim_baseline_schema")
    require(type(baseline["variables"]) is dict and set(baseline["variables"])=={"temperature_2m_max","temperature_2m_min"}, "ghcn_claim_variables_schema")
    require(data["historical_context"].get("baseline")==baseline, "ghcn_claim_projection_changed")
    compact=deepcopy(full)  # Never call the mutating constructor on stored facts.
    narrowed={key:deepcopy(value) for key,value in baseline.items() if key!="variables"}
    narrowed["variables"]={key:_selected_scope(value,selection["signal_field"],selection["signal_date"])
                           for key,value in baseline["variables"].items()}
    narrowed["representation"]="selected_claim_warrants_v1; complete tables retained by source reference"
    compact.raw_signal_dump["evidence"]["baseline"]=deepcopy(narrowed)
    compact.historical_context["baseline"]=deepcopy(narrowed)
    compact.raw_signal_dump["ghcn_claim_view"]=deepcopy(reference)
    return compact


@dataclass(frozen=True)
class ResolvedClaim:
    full: StoryBundle
    view: StoryBundle
    reference: dict
    full_sha256: str
    view_sha256: str
    counters: dict

    def verify_saved(self, saved):
        # This method exists only on a freshly source-resolved object. A matching
        # claimed digest or a generic dict cannot supply a resolved context.
        require(json_tree(self.view.to_dict())==saved, "ghcn_claim_view_changed")
        return self.view


def resolve(authority, run_id, selection) -> ResolvedClaim:
    environment(authority.projections)
    baseline=domain.configured(authority)
    inputs.fixed(selection,"station_id signal_date signal_field")
    require(selection["signal_field"] in TYPES, "ghcn_selection_unsupported")
    uuid(run_id)
    anchor=time.monotonic()
    with authority.projections._connection() as c:
        authority._validate(c)
        receipt,value,deps,_,_,envelope=domain.read_input(authority,c,run_id)
        result_receipt,result=authority.projections._read(c,inputs.RESULT,"run:"+run_id)
        require(result["status"]=="applied" and result["source_status"]=="success"
                and result["runtime_input_sha256"]==receipt.canonical_sha256
                and result["supply_run_id"]==run_id and result["supply_sha256"]==value["supply_sha256"]
                and result["dependency_sha256"]==value["dependency_sha256"]
                and result["effects_sha256"]==value["effects_sha256"], "ghcn_claim_result_changed")
        accepted=authority._intent(c,result["command_id"])
        completed=authority._result(c,result["command_id"])
        require(accepted is not None and accepted[0].action==domain.ACTION
                and accepted[0].digest==result["command_digest"]
                and accepted[0].payload["runtime_input_sha256"]==receipt.canonical_sha256
                and accepted[0].payload["supply_run_id"]==run_id
                and completed is not None and completed.get("status")=="applied"
                and completed.get("source_run")==domain.outcome(result_receipt,result), "ghcn_claim_command_not_applied")
        responses=inputs.read_responses(c,value["responses"])
    require(deps["policy_sha256"]==digest(current_editorial_policy())
            and deps["configuration"]==inputs.configuration()
            and deps["baseline_pins"]==dict(database_sha256=baseline.database_sha256,manifest_sha256=baseline.manifest_sha256), "ghcn_claim_context_changed")
    bundles,countries,metrics,effects,descriptor=inputs.derive(baseline,deps["state"],responses,
        now=value["source_now"],config=deps["configuration"])
    require(descriptor==value["baseline"] and effects==value["effects"]
            and [_row(b,model.ExtremeSignalBundle,decoding=False) for b in bundles]==envelope["bundles"]
            and [_row(b,model.CountryRecord,decoding=False) for b in countries]==envelope["country_records"]
            and (_outcome(metrics)|{"supply_empty":not bundles})==envelope["source_outcome"], "ghcn_claim_source_replay_changed")
    chosen=[b for b in bundles if b.station_id==selection["station_id"] and b.signal_date.isoformat()==selection["signal_date"]]
    require(len(chosen)==1, "ghcn_claim_member_absent")
    member=chosen[0]
    event=getattr(member,selection["signal_field"])
    require(event is not None, "ghcn_claim_event_absent")
    full=_two_bot_bundle_for_extreme_signal(TYPES[selection["signal_field"]],event,source="ghcn")
    require(full is not None and audit_story_bundle(full).prompt_ready, "ghcn_story_evidence_held")
    full_json=json_tree(full.to_dict())
    full_sha=fingerprint(full_json)
    evidence=full_json["raw_signal_dump"]["evidence"]
    archives=[r.metadata() for r in responses if r.kind=="station_archive" and r.key==member.station_id]
    require(len(archives)==1 and archives[0]["status"]=="success"
            and archives[0]["raw_sha256"]==evidence["baseline"]["source_payload_sha256"], "ghcn_claim_archive_changed")
    reference=dict(schema_version=1,kind="ghcn_claim_view_v1",scope="selected_claim_warrants",
        source_run_id=run_id,source_result=dict(namespace=inputs.RESULT,snapshot_id="run:"+run_id,sha256=result_receipt.canonical_sha256),
        runtime_input=dict(namespace=inputs.INPUT,snapshot_id="run:"+run_id,sha256=receipt.canonical_sha256),
        scientific_supply=dict(namespace=NAMESPACE,snapshot_id="run:"+run_id,sha256=value["supply_sha256"]),
        selection=deepcopy(selection),member_sha256=digest(_row(member,model.ExtremeSignalBundle,decoding=False)),
        full_story=dict(codec="revision-fingerprint-v1-json-default",sha256=full_sha),
        observation_revision=evidence["revision_id"],baseline_revision=evidence["baseline"]["revision_id"],
        baseline_artifact=deepcopy(deps["baseline_pins"]),
        original_archives=archives)
    view=project(full,reference,selection)
    captured=capture_bundle(view)
    require(time.monotonic()-anchor<=domain.PREPARATION_SECONDS,"ghcn_claim_preparation_expired")
    return ResolvedClaim(full,view,reference,full_sha,fingerprint(captured.payload()),dict(
        full_story_bytes=len(json.dumps(full_json,sort_keys=True,default=json_default).encode()),
        view_bytes=len(captured.serialized.encode()),full_fact_count=len(full.current_facts),view_fact_count=len(view.current_facts),
        p18_bytes=len(json.dumps(envelope,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()),
        raw_bytes=sum(len(r.raw or b"") for r in responses),
        calendar_counts={k:len(v["calendar_samples"]) for k,v in evidence["baseline"]["variables"].items()},
        monthly_counts={k:len(v["monthly_samples"]) for k,v in evidence["baseline"]["variables"].items()}))
