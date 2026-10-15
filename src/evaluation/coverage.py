"""Unscored reference readiness from exact retained evidence, without I/O.

No count in this module is a recall denominator. Human relevance decisions and
source-scoped episode continuity cannot certify an observed reference event.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.commands.schema import utc_datetime
from src.storage import postgres_projection as p
from src.storage.retained_reports import digest, frozen, identifier, sha, timestamp

SET = "coverage-reference-set-v1"
DECISION = "coverage-human-decision-v1"
ASSESSMENT = "coverage-assessment-v1"
CONTRACT = "unscored-retained-coverage-v1"
MAX_SET_BYTES = 512 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
NAMESPACES = {SET, DECISION, ASSESSMENT, "retained-report-artifact-v1", "retained-report-revision-v1",
    "report-development-v1", "scientific-supply-ghcn-v1", "cyclone-supply-nhc-v1", "physical-episode-revision-v1",
    "sourced-generation-input-v1", "sourced-generation-job-v1", "candidate-admission-input-v1",
    "command-intent-v1", "command-result-v1", "command-core-v1"}
STAGES = ("source_input_retained", "scientific_evidence_qualified", "physical_episode_detected", "story_prepared",
          "report_review_opened", "generation_accepted", "candidate_retained", "checks_completed", "draft_saved", "publication_confirmed")
CODES = set("reference_pending grouping_unresolved translation_pending source_claim_unqualified first_availability_unknown "
    "deadline_unset calendar_time_only reference_out_of_window trace_missing trace_ambiguous retained_history_incomplete "
    "source_failed source_partial source_not_scheduled source_stale scientific_gate_held selection_not_observed writer_rejected "
    "provider_unavailable checks_failed checks_unavailable manual_review_pending publication_paused publication_unknown "
    "source_or_reference_corrected later_knowledge denominator_not_qualified quiet_period_unqualified "
    "reference_selection_unqualified unsupported_trace_adapter".split())
CHOICES = {"D1": {"one_reported_episode_candidate", "require_supported_splits", "exclude", "hold"},
           "D2": {"one_reported_episode_candidate", "require_supported_splits", "exclude", "hold"},
           "D3-taxonomy": {"forecast_candidate", "project_report_candidate", "hold"},
           "D3-translation": {"translation_reviewed", "hold"}}


class CoverageError(ValueError):
    """Bounded codes only; raw private inputs must not enter an error message."""


def require(condition, code="coverage_invalid"):
    if not condition:
        raise CoverageError(code)


def fixed(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()))


def text(value, limit=300):
    require(type(value) is str and bool(value.strip()) and len(value.encode("utf-8")) <= limit)


def array(value, maximum, *, minimum=0, unique=True):
    require(type(value) is list and minimum <= len(value) <= maximum, "coverage_inventory_bound")
    if unique:
        require(len({digest(item) for item in value}) == len(value), "coverage_duplicate")


def codes(value):
    array(value, 32)
    require(all(type(code) is str and code in CODES for code in value), "coverage_unknown_reason")


def reference(value, namespaces=None):
    fixed(value, "namespace snapshot_id sha256")
    require(value["namespace"] in (NAMESPACES if namespaces is None else namespaces), "coverage_reference_type")
    p._identifier(value["snapshot_id"])
    sha(value["sha256"])
    return value


def references(value, maximum=32, namespaces=None):
    array(value, maximum)
    for ref in value:
        reference(ref, namespaces)


def label(value):
    fixed(value, "label evidence_ref")
    text(value["label"], 100)
    reference(value["evidence_ref"])


def time_window(value):
    fixed(value, "start end")
    for item in value.values():
        timestamp(item)
    start, end = value["start"], value["end"]
    if start and end and start["precision"] == end["precision"] and start["precision"] != "unknown":
        key = "utc" if start["precision"] == "instant" else "date"
        left, right = start[key], end[key]
        if key == "utc":
            left, right = utc_datetime(left), utc_datetime(right)
        require(left <= right, "coverage_window_reversed")


def unit(value):
    fixed(value, "unit_id predecessor_unit_refs unit_kind report_refs source_alias_refs grouping_decision_refs hazard_labels "
          "region_memberships source_class time_fields availability_evidence_refs deadline relevance_decision_ref "
          "qualification_decision_refs state hold_codes")
    identifier(value["unit_id"])
    require(value["unit_kind"] in {"reported_episode_candidate", "physical_event_candidate", "forecast_candidate", "project_report_candidate"})
    references(value["predecessor_unit_refs"], 8, {SET})
    references(value["grouping_decision_refs"], 8, {DECISION})
    # D1/D2 requests for splits name no children. This tranche cannot fabricate
    # a grouping graph or interpret an unsupported future adjudication record.
    require(not value["predecessor_unit_refs"] and not value["grouping_decision_refs"], "coverage_grouping_record_required")
    array(value["report_refs"], 8)
    lineages = set()
    for ref in value["report_refs"]:
        fixed(ref, "lineage_id report_sha256 claim_ids")
        identifier(ref["lineage_id"])
        sha(ref["report_sha256"])
        require(ref["lineage_id"] not in lineages, "coverage_duplicate")
        lineages.add(ref["lineage_id"])
        array(ref["claim_ids"], 32, minimum=1)
        for claim in ref["claim_ids"]:
            identifier(claim)
    references(value["source_alias_refs"], 8)
    for key in ("hazard_labels", "region_memberships"):
        array(value[key], 16)
        for item in value[key]:
            label(item)
    require(value["source_class"] in {"reported", "observed", "forecast", "warning", "project", "unknown"})
    fixed(value["time_fields"], "event_start event_end issued_at published_at first_available_at")
    for item in value["time_fields"].values():
        timestamp(item)
    time_window(dict(start=value["time_fields"]["event_start"], end=value["time_fields"]["event_end"]))
    references(value["availability_evidence_refs"], 8)
    fixed(value["deadline"], "at policy_ref")
    timestamp(value["deadline"]["at"])
    require((value["deadline"]["at"] is None) == (value["deadline"]["policy_ref"] is None))
    if value["deadline"]["policy_ref"] is not None:
        reference(value["deadline"]["policy_ref"])
    if value["relevance_decision_ref"] is not None:
        reference(value["relevance_decision_ref"], {DECISION})
    references(value["qualification_decision_refs"], 8, {DECISION})
    require(not value["qualification_decision_refs"], "coverage_qualification_not_supported")
    require(value["state"] in {"pending", "candidate_for_adjudication", "held", "excluded"})
    codes(value["hold_codes"])
    return value


def reference_set(value):
    fixed(value, "schema_version set_id previous_set_sha256 selection_protocol comparison_window units quiet_periods "
          "human_decision_refs qualification created_at")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    identifier(value["set_id"])
    if value["previous_set_sha256"] is not None:
        sha(value["previous_set_sha256"])
    utc_datetime(value["created_at"])
    protocol = value["selection_protocol"]
    fixed(protocol, "protocol_ref scope_label selection_method independent_of_bot_output population_status")
    reference(protocol["protocol_ref"], {"retained-report-artifact-v1"})
    text(protocol["scope_label"])
    require(protocol["selection_method"] in {"independent_convenience_sample", "invented_fixture"})
    require(type(protocol["independent_of_bot_output"]) is bool and protocol["population_status"] == "unqualified")
    time_window(value["comparison_window"])
    array(value["units"], 16, minimum=1)
    ids = set()
    for row in value["units"]:
        unit(row)
        require(row["unit_id"] not in ids, "coverage_duplicate")
        ids.add(row["unit_id"])
    references(value["human_decision_refs"], 32, {DECISION})
    for row in value["units"]:
        require(row["relevance_decision_ref"] is None or row["relevance_decision_ref"] in value["human_decision_refs"], "coverage_decision_missing")
    fixed(value["qualification"], "status reason_codes")
    require(value["qualification"]["status"] == "not_qualified", "coverage_qualification_not_supported")
    codes(value["qualification"]["reason_codes"])
    array(value["quiet_periods"], 32)
    for period in value["quiet_periods"]:
        fixed(period, "period_id scope window selection_protocol_ref required_source_inventory_refs availability_trace_refs reviewer_decision_ref state hold_codes")
        identifier(period["period_id"])
        fixed(period["scope"], "hazards regions source_classes")
        for group in period["scope"].values():
            array(group, 16)
            for item in group:
                text(item, 100)
        time_window(period["window"])
        require(all(period["window"].values()))
        reference(period["selection_protocol_ref"], {"retained-report-artifact-v1"})
        references(period["required_source_inventory_refs"], 32)
        references(period["availability_trace_refs"], 32)
        require(period["reviewer_decision_ref"] is None, "coverage_quiet_adjudication_not_supported")
        require(period["state"] in {"proposed", "evidence_incomplete", "adjudication_pending"})
        codes(period["hold_codes"])
    require(len(p._canonical(value)) <= MAX_SET_BYTES, "coverage_set_bound")
    return frozen(value)


def decision(value):
    fixed(value, "schema_version decision_id previous_decision_sha256 packet_sha256 subject question_id reviewer human_response_ref "
          "source_anchor_refs choice rationale unresolved_codes decided_at recorded_at")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    identifier(value["decision_id"])
    sha(value["packet_sha256"])
    if value["previous_decision_sha256"] is not None:
        sha(value["previous_decision_sha256"])
    subject = value["subject"]
    fixed(subject, "set_id unit_id report_sha256 claim_ids")
    identifier(subject["set_id"])
    identifier(subject["unit_id"])
    sha(subject["report_sha256"])
    array(subject["claim_ids"], 32, minimum=1)
    for claim in subject["claim_ids"]:
        identifier(claim)
    require(value["question_id"] in CHOICES and value["choice"] in CHOICES[value["question_id"]], "coverage_decision_choice")
    fixed(value["reviewer"], "subject role competence_statement")
    text(value["reviewer"]["subject"], 200)
    text(value["reviewer"]["role"], 100)
    if value["reviewer"]["competence_statement"] is not None:
        text(value["reviewer"]["competence_statement"], 1000)
    if value["question_id"] == "D3-translation" and value["choice"] == "translation_reviewed":
        require(value["reviewer"]["competence_statement"] is not None, "coverage_translation_competence_missing")
    reference(value["human_response_ref"], {"retained-report-artifact-v1"})
    array(value["source_anchor_refs"], 32, minimum=1)
    for anchor in value["source_anchor_refs"]:
        fixed(anchor, "artifact_id content_sha256 start end")
        sha(anchor["artifact_id"])
        sha(anchor["content_sha256"])
        require(type(anchor["start"]) is int and type(anchor["end"]) is int and 0 <= anchor["start"] < anchor["end"]
                and anchor["end"]-anchor["start"] <= 16384)
    text(value["rationale"], 4000)
    codes(value["unresolved_codes"])
    timestamp(value["decided_at"])
    utc_datetime(value["recorded_at"])
    require(len(p._canonical(value)) <= 65536, "coverage_decision_bound")
    return frozen(value)


def instant_time(value):
    utc_datetime(value)
    return dict(original=value, utc=value, date=None, precision="instant", timezone="UTC")


def stage(name, *, state="not_observed_in_retained_scope", refs=(), recorded_at=None,
          execution_class="retained_runtime", current_binding="unresolved", reason_codes=("trace_missing",)):
    require(name in STAGES)
    require(state in {"recorded", "held", "not_observed_in_retained_scope", "unavailable", "not_applicable", "unsupported"})
    require(execution_class in {"retained_runtime", "archival_replay", "invented_fixture"})
    require(current_binding in {"current", "superseded", "unresolved"})
    references(list(refs))
    codes(list(reason_codes))
    timestamp(recorded_at)
    require(state != "recorded" or bool(refs) and recorded_at is not None, "coverage_stage_proof_missing")
    return dict(stage=name, state=state, evidence_refs=list(refs), recorded_at=recorded_at,
                execution_class=execution_class, current_binding=current_binding, reason_codes=list(reason_codes))


@dataclass(frozen=True)
class RetainedInput:
    """Exact immutable repository wrapper plus its trusted database receipt time.

    The PG adapter constructs this after verifying the receipt and semantic
    producer reader. Source created_at/recorded_at fields are never the cutoff.
    """
    encoded: bytes

    @classmethod
    def create(cls, *, reference, wrapper, retained_at):
        value = cls(p._canonical(dict(reference=reference, wrapper=wrapper, retained_at=retained_at)))
        value.value()
        return value

    def value(self, namespace=None):
        value = p._decode(self.encoded)
        fixed(value, "reference wrapper retained_at")
        ref = reference(value["reference"], {namespace} if namespace else {SET, DECISION})
        wrapper = value["wrapper"]
        fixed(wrapper, "sequence document")
        require(type(wrapper["sequence"]) is int and 1 <= wrapper["sequence"] <= 512)
        document = reference_set(wrapper["document"]) if ref["namespace"] == SET else decision(wrapper["document"])
        key, predecessor = ("set_id", "previous_set_sha256") if ref["namespace"] == SET else ("decision_id", "previous_decision_sha256")
        expected_id = digest(document[key])+":"+f'{wrapper["sequence"]:010d}'
        require(ref["snapshot_id"] == expected_id and ref["sha256"] == digest(wrapper), "coverage_retained_input_changed")
        require((wrapper["sequence"] == 1) == (document[predecessor] is None), "coverage_retained_input_changed")
        utc_datetime(value["retained_at"])
        return value


@dataclass(frozen=True)
class ResolvedUnit:
    """Adapter supplies verified exact producer bindings, never HTTP verdicts."""
    encoded: bytes

    @classmethod
    def create(cls, *, unit_id, source_label, stages, decisions=(), holds=()):
        identifier(unit_id)
        text(source_label, 300)
        array(stages, len(STAGES))
        require(len({row["stage"] for row in stages}) == len(stages), "coverage_stage_ambiguous")
        for row in stages:
            fixed(row, "stage state evidence_refs recorded_at execution_class current_binding reason_codes")
            stage(row["stage"], state=row["state"], refs=row["evidence_refs"], recorded_at=row["recorded_at"],
                  execution_class=row["execution_class"], current_binding=row["current_binding"], reason_codes=row["reason_codes"])
        codes(list(holds))
        require(all(type(value) is RetainedInput for value in decisions), "coverage_retained_decision_required")
        retained = [value.value(DECISION) for value in decisions]
        array(retained, 32)
        return cls(p._canonical(dict(unit_id=unit_id, source_label=source_label, stages=stages, decisions=retained, holds=list(holds))))


def evaluate(retained_set, resolved, *, cutoff, evaluated_at, state_version, policy_sha256, input_refs):
    require(type(retained_set) is RetainedInput, "coverage_retained_set_required")
    retained = retained_set.value(SET)
    document = retained["wrapper"]["document"]
    set_ref = retained["reference"]
    require(utc_datetime(retained["retained_at"]) <= utc_datetime(cutoff), "coverage_set_after_cutoff")
    require(type(state_version) is int and state_version >= 0)
    sha(policy_sha256)
    require(utc_datetime(evaluated_at) >= utc_datetime(cutoff), "coverage_execution_time_changed")
    references(input_refs, 512)
    require(type(resolved) is list and all(type(row) is ResolvedUnit for row in resolved))
    rows = [p._decode(row.encoded) for row in resolved]
    require(len(rows) == len(document["units"]) and {row["unit_id"] for row in rows} == {row["unit_id"] for row in document["units"]}, "coverage_resolution_incomplete")
    by_id = {row["unit_id"]: row for row in rows}
    units = []
    decisions_seen = set()
    declared_decisions = {digest(ref): ref for ref in document["human_decision_refs"]}
    for candidate in document["units"]:
        item = by_id[candidate["unit_id"]]
        holds = set(candidate["hold_codes"]) | set(item["holds"]) | {"source_claim_unqualified"}
        selected_ref = candidate["relevance_decision_ref"]
        selected = None
        for retained_decision in item["decisions"]:
            retained_decision = RetainedInput(p._canonical(retained_decision)).value(DECISION)
            pointer = retained_decision["reference"]
            identity = digest(pointer)
            require(identity in declared_decisions and identity not in decisions_seen, "coverage_decision_not_declared")
            require(utc_datetime(retained_decision["retained_at"]) <= utc_datetime(cutoff), "coverage_decision_after_cutoff")
            value = retained_decision["wrapper"]["document"]
            subject = value["subject"]
            require(subject["set_id"] == document["set_id"] and subject["unit_id"] == candidate["unit_id"]
                    and any(subject["report_sha256"] == report["report_sha256"] and set(subject["claim_ids"]) <= set(report["claim_ids"])
                            for report in candidate["report_refs"]), "coverage_decision_subject_changed")
            if value["question_id"] in {"D1", "D2", "D3-taxonomy"}:
                require(pointer == selected_ref and selected is None, "coverage_selected_decision_changed")
                selected = value
            else:
                require(pointer != selected_ref, "coverage_selected_decision_changed")
            decisions_seen.add(identity)
        require((selected_ref is None) == (selected is None), "coverage_selected_decision_missing")
        state = "held" if candidate["state"] == "held" else "pending"
        if selected is not None:
            state = {"one_reported_episode_candidate": "candidate_for_adjudication", "forecast_candidate": "candidate_for_adjudication",
                     "project_report_candidate": "candidate_for_adjudication", "exclude": "excluded", "require_supported_splits": "held", "hold": "held"}[selected["choice"]]
            holds.update(selected["unresolved_codes"])
            if selected["choice"] == "require_supported_splits":
                holds.add("grouping_unresolved")
        else:
            holds.add("reference_pending")
        require(candidate["state"] in {"pending", state}, "coverage_unbacked_reference_state")
        if candidate["time_fields"]["first_available_at"] is None:
            holds.add("first_availability_unknown")
        if candidate["deadline"]["at"] is None:
            holds.add("deadline_unset")
        if any(t and t["precision"] == "calendar" for t in candidate["time_fields"].values()):
            holds.add("calendar_time_only")
        cells = {}
        for cell in item["stages"]:
            retained_time = cell["recorded_at"]
            if retained_time and retained_time["utc"] is not None and utc_datetime(retained_time["utc"]) > utc_datetime(cutoff):
                cell = dict(cell, state="held", reason_codes=["later_knowledge"])
            cells[cell["stage"]] = cell
        units.append(dict(unit_id=candidate["unit_id"], source_label=item["source_label"], report_refs=candidate["report_refs"],
            reference_state=state, selected_relevance_decision_ref=selected_ref,
            source_class=candidate["source_class"], hazards=candidate["hazard_labels"], regions=candidate["region_memberships"],
            original_time_labels=candidate["time_fields"], holds=sorted(holds), stages=[cells.get(name, stage(name)) for name in STAGES]))
    require(decisions_seen == set(declared_decisions), "coverage_decision_resolution_incomplete")
    input_refs = list({digest(ref): ref for ref in [*input_refs, set_ref, *document["human_decision_refs"]]}.values())
    lineages = {ref["lineage_id"] for candidate in document["units"] for ref in candidate["report_refs"]}
    result = dict(schema_version=1, contract=CONTRACT, set_ref=set_ref, cutoff=cutoff, evaluated_at=evaluated_at,
        state_version=state_version, policy_sha256=policy_sha256, input_refs=input_refs, currentness="current",
        reference_readiness=dict(status="not_qualified", report_lineages=len(lineages), units_pending=sum(row["reference_state"] != "excluded" for row in units),
            human_decisions_recorded=len(decisions_seen), quiet_periods_qualified=0,
            reasons=["denominator_not_qualified", "quiet_period_unqualified", "reference_selection_unqualified"]),
        metrics=dict(event_recall=None, draft_recall=None, publication_recall=None, timeliness=None, confirmed_misses=None, reason="denominator_not_qualified"),
        units=units, lineage_edges=[], limits=["retained_history_incomplete", "unsupported_trace_adapter"])
    require(len(p._canonical(result)) <= MAX_RESULT_BYTES, "coverage_result_bound")
    return frozen(result)
