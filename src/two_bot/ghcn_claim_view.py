"""A selected claim view, rebuilt from complete locally retained GHCN evidence.

Only a freshly resolved typed context can execute this reference format.
Passive retained packets never mint spending, check or approval authority.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
import time
import stat
from pathlib import Path

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

# Preserve the resolver's public passive helpers and legacy exception classes.
from src.two_bot import ghcn_claim_contract as _contract
from src.two_bot.ghcn_claim_contract import (
    TYPES as TYPES, BASELINE_FIELDS as BASELINE_FIELDS, VARIABLE_SCALARS as VARIABLE_SCALARS,
    TABLE_FIELDS as TABLE_FIELDS, EVIDENCE_FIELDS as EVIDENCE_FIELDS, json_tree as json_tree,
)


def _passive(call, *args):
    try:
        return call(*args)
    except _contract.ClaimContractError as exc:
        from src.storage.cyclone_supply import CycloneSupplyError
        raise CycloneSupplyError(str(exc)) from None
    except _contract.ClaimJSONError as exc:
        from src.commands.schema import CommandError
        raise CommandError(exc.code, str(exc)) from exc.__cause__


def project(full: StoryBundle, reference: dict, selection: dict) -> StoryBundle:
    """Compatibility wrapper for the shared passive projection."""
    return _passive(_contract.project, full, reference, selection)


def project_tree(full: dict, reference: dict, selection: dict) -> dict:
    """Compatibility wrapper over already serialized full evidence."""
    return _passive(_contract.project_tree, full, reference, selection)


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


def _read_source(authority, c, run_id, selection):
    inputs.fixed(selection,"station_id signal_date signal_field")
    require(selection["signal_field"] in TYPES, "ghcn_selection_unsupported")
    uuid(run_id)
    receipt,value,deps,bundles,_,envelope=domain.read_input(authority,c,run_id)
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
    return receipt,value,deps,envelope,result_receipt,result,responses,bundles


def _reconstruct(authority, run_id, selection, material, anchor):
    baseline=domain.configured(authority)
    receipt,value,deps,envelope,result_receipt,result,responses,_=material
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


def resolve(authority, run_id, selection) -> ResolvedClaim:
    environment(authority.projections)
    anchor=time.monotonic()
    with authority.projections._connection() as c:
        authority._validate(c)
        material=_read_source(authority,c,run_id,selection)
    return _reconstruct(authority,run_id,selection,material,anchor)


def baseline_footprint(baseline):
    """Fixed trusted-local metadata fence, not a filesystem/SQL transaction."""
    rows: list[tuple[str, tuple | None]] = []
    paths=(baseline.database, baseline.manifest, *(Path(str(baseline.database)+suffix) for suffix in ("-wal","-shm","-journal")))
    for index,path in enumerate(paths):
        require(path.is_absolute(), "ghcn_baseline_path")
        try:
            meta=path.lstat()
        except FileNotFoundError:
            require(index >= 2, "ghcn_baseline_missing")
            rows.append((str(path),None))
            continue
        require(stat.S_ISREG(meta.st_mode), "ghcn_baseline_nonregular")
        rows.append((str(path),(meta.st_mode,meta.st_dev,meta.st_ino,meta.st_size,meta.st_mtime_ns,meta.st_ctime_ns)))
    return (baseline.database_sha256,baseline.manifest_sha256,tuple(rows))


def _source_pins(material):
    receipt,value,deps,envelope,result_receipt,result,responses,_=material
    return digest(dict(input=receipt.canonical_sha256,result=result_receipt.canonical_sha256,
        value=value,dependencies=deps,supply=envelope,outcome=result,responses=[r.metadata() for r in responses]))


def _checkpoint(authority,c,state,version,material,selection):
    # Query the exact selected event too, even when no GHCN draft exists yet.
    # _read_source already validated and decoded this supply on this connection.
    # Reuse those objects only for this checkpoint; every later transaction calls
    # _read_source again before reaching here. No evidence is cached across calls.
    bundles=material[7]
    chosen=[b for b in bundles if b.station_id==selection["station_id"] and b.signal_date.isoformat()==selection["signal_date"]]
    require(len(chosen)==1, "ghcn_claim_member_absent")
    event=getattr(chosen[0],selection["signal_field"])
    require(event is not None, "ghcn_claim_event_absent")
    targets=inputs.state_dependencies(state)["targets"]
    targets=targets+[dict(id="ghcn-event-query:"+event.event_id,event_id=event.event_id)]
    delivery=domain.delivery_dependency(authority,c,targets)
    require(not delivery["protection_codes"], "ghcn_delivery_protected")
    return dict(state_version=version,state_sha256=digest(state),source_sha256=_source_pins(material),
        delivery=delivery,policy_sha256=digest(current_editorial_policy()),configuration=inputs.configuration())


@dataclass(frozen=True)
class ExecutionContext:
    """Server-owned per-invocation proof, never serialized or accepted from HTTP."""
    authority: object
    claim: ResolvedClaim
    checkpoint: dict
    footprint: tuple
    valid_until: float
    save: dict

    def _current(self,authority,c,state,version):
        require(authority is self.authority and time.monotonic() <= self.valid_until, "ghcn_preparation_expired")
        ref=self.claim.reference
        material=_read_source(authority,c,ref["source_run_id"],ref["selection"])
        require(_checkpoint(authority,c,state,version,material,ref["selection"])==self.checkpoint,
            "ghcn_execution_context_changed")
        require(baseline_footprint(domain.configured(authority))==self.footprint,"ghcn_baseline_changed")
        require(time.monotonic() <= self.valid_until,"ghcn_preparation_expired")
        return self.claim

    def current(self,authority,c,state,version):
        from src.commands.schema import CommandError
        from src.storage.cyclone_supply import CycloneSupplyError
        try:
            return self._current(authority,c,state,version)
        except CycloneSupplyError as exc:
            raise CommandError(str(exc),"Current GHCN evidence changed; refresh the retained brief") from None
        except OSError:
            raise CommandError("ghcn_baseline_unavailable","Current GHCN baseline is unavailable") from None

    def media_approval_successor(self, authority, c, command, previous_state, previous_version, resolve_principal):
        """Rebind only the approval this context just checked, without a new lifetime.

        Enrollment follows that command's own state write in the same lock. The
        predecessor proof cannot authorize arbitrary later state or grants.
        """
        from src.editorial.revisions import revoke_approval
        from src.commands.postgres_editor_media import resolve
        version, state = authority._state(c, lock=True)
        result = authority._result(c, command.command_id)
        require(command.action == "approve_media_revision" and len(command.targets) == 1
                and version == previous_version + 1 and result is not None
                and result.get("status") == "applied" and result.get("state_version") == version
                and result.get("command_id") == command.command_id and result.get("digest") == command.digest,
                "ghcn_approval_successor_changed")
        target = command.targets[0].draft_id
        before = [row for row in previous_state["drafts"] if isinstance(row, dict) and row.get("id") == target]
        after = [row for row in state["drafts"] if isinstance(row, dict) and row.get("id") == target]
        require(len(before) == len(after) == 1, "ghcn_approval_successor_changed")
        binding = after[0].get("approval_binding", {})
        require(binding.get("command_id") == command.command_id
                and binding.get("consumed_state_version") == previous_version
                and binding.get("consumed_state_sha256") == digest(previous_state)
                and binding.get("resulting_state_version") == version,
                "ghcn_approval_successor_changed")
        resolve(resolve_principal, command.actor_subject, publisher=True)
        resolve(resolve_principal, binding["requesting_actor"])
        self.current(authority, c, previous_state, previous_version)
        proposed = revoke_approval(deepcopy(before[0]))
        proposed.update(approval_binding=binding, status="pending",
                        publish_intent_id=binding["publish_intent_id"], updated_at=command.requested_at)
        expected = deepcopy(previous_state)
        expected["drafts"] = [proposed if isinstance(row, dict) and row.get("id") == target else row
                              for row in expected["drafts"]]
        require(expected == state, "ghcn_approval_successor_changed")
        ref = self.claim.reference
        material = _read_source(authority, c, ref["source_run_id"], ref["selection"])
        checkpoint = _checkpoint(authority, c, state, version, material, ref["selection"])
        successor = replace(self, checkpoint=checkpoint)
        successor.current(authority, c, state, version)
        return successor


def prepare_execution(authority,run_id,selection):
    """Read on the owned connection, replay on verified detached bytes outside it."""
    anchor=time.monotonic()
    baseline=domain.configured(authority)
    with authority.projections._connection() as c:
        authority._validate(c)
        version,state=authority._state(c,lock=True)
        material=_read_source(authority,c,run_id,selection)
        checkpoint=_checkpoint(authority,c,state,version,material,selection)
    before=baseline_footprint(baseline)
    claim=_reconstruct(authority,run_id,selection,material,anchor)
    require(before==baseline_footprint(baseline),"ghcn_baseline_changed")
    from src.orchestrator.sources import open_meteo as source
    from src.storage.scientific_supply import ScientificSupplySession
    detached=deepcopy(state)
    session=ScientificSupplySession(authority.projections,run_id,"replay")
    bundles=[_row(row,model.ExtremeSignalBundle,decoding=True) for row in material[3]["bundles"]]
    with source._isolated_replay(session), source._suppression_context(detached,source="retained_ghcn_replay",run_id=run_id):
        suppressed,_,_,individual,_=source._scientific_prepass(detached,bundles)
        candidates=[b for b in individual if b.station_id==selection["station_id"] and b.signal_date.isoformat()==selection["signal_date"]]
        require(len(candidates)==1,"ghcn_individual_not_selected")
        member=candidates[0]
        selected=source._select_individual_signal(detached,member,suppressed,{})
    require(selected.signal is not None and selected.legacy_type==TYPES[selection["signal_field"]]
        and selected.event_id==claim.full.event_id,"ghcn_selection_not_dispatch_winner")
    elite=selected.legacy_type in {"all_time_high","all_time_low"} or (
        selected.legacy_type in {"anomaly_hot","anomaly_cold"} and abs(selected.signal.anomaly_c)>=18)
    save=dict(legacy_type=selected.legacy_type,event_id=selected.event_id,score=selected.score.as_dict(),city=selected.city,
        tweet_date=selection["signal_date"],cooldown_exempt=elite,evaluator_metadata=None,
        review_context=source._review_context(source=f"NOAA GHCN-Daily (station {member.station_id})",
            source_key="open_meteo_extreme_signals",headline=selected.headline,facts=selected.facts,
            current_run=dict(id=run_id,mode="retained_local",started_at=material[1]["acquisition_started_at"])))
    require(time.monotonic()<=anchor+domain.PREPARATION_SECONDS,"ghcn_preparation_expired")
    return ExecutionContext(authority,claim,checkpoint,before,anchor+domain.PREPARATION_SECONDS,save)


def structural_view(value):
    """Compatibility wrapper; passive shape never grants resolved authority."""
    return _passive(_contract.structural_view, value)
