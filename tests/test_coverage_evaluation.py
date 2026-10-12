"""Pure invented references; these choices are not actual human decisions."""
from copy import deepcopy

import pytest

from src.evaluation import coverage as e

NOW = "2026-10-12T01:00:00Z"
LATER = "2026-10-12T02:00:00Z"


def pointer(namespace="retained-report-artifact-v1", identity="a"):
    return dict(namespace=namespace, snapshot_id=identity*64, sha256=identity*64)


def unit(report=None):
    return dict(unit_id="fixture-unit", predecessor_unit_refs=[], unit_kind="reported_episode_candidate",
        report_refs=[report] if report else [], source_alias_refs=[], grouping_decision_refs=[], hazard_labels=[],
        region_memberships=[], source_class="reported", time_fields=dict.fromkeys(["event_start", "event_end", "issued_at", "published_at", "first_available_at"]),
        availability_evidence_refs=[], deadline=dict(at=None, policy_ref=None), relevance_decision_ref=None,
        qualification_decision_refs=[], state="pending", hold_codes=[])


def reference_document(report=None):
    return dict(schema_version=1, set_id="fixture-set", previous_set_sha256=None,
        selection_protocol=dict(protocol_ref=pointer(), scope_label="Invented fixture only", selection_method="invented_fixture",
            independent_of_bot_output=False, population_status="unqualified"), comparison_window=dict(start=None, end=None),
        units=[unit(report)], quiet_periods=[], human_decision_refs=[],
        qualification=dict(status="not_qualified", reason_codes=["reference_pending"]), created_at=NOW)


def decision_document():
    return dict(schema_version=1, decision_id="fixture-human-choice", previous_decision_sha256=None, packet_sha256="a"*64,
        subject=dict(set_id="fixture-set", unit_id="fixture-unit", report_sha256="b"*64, claim_ids=["claim1"]),
        question_id="D1", reviewer=dict(subject="invented-reviewer", role="fixture", competence_statement=None),
        human_response_ref=pointer(identity="c"), source_anchor_refs=[dict(artifact_id="d"*64, content_sha256="e"*64, start=0, end=10)],
        choice="require_supported_splits", rationale="Invented choice tests a hold; not a human verdict.",
        unresolved_codes=["grouping_unresolved"], decided_at=None, recorded_at=NOW)


def retained_input(document, namespace=e.SET, *, retained_at=NOW):
    wrapper = dict(sequence=1, document=deepcopy(document))
    key = "set_id" if namespace == e.SET else "decision_id"
    pointer = dict(namespace=namespace, snapshot_id=e.digest(document[key])+":0000000001", sha256=e.digest(wrapper))
    return e.RetainedInput.create(reference=pointer, wrapper=wrapper, retained_at=retained_at)


def declare(document, choice, *, retained_at=NOW):
    retained = retained_input(choice, e.DECISION, retained_at=retained_at)
    pointer = retained.value()["reference"]
    document["human_decision_refs"] = [pointer]
    document["units"][0]["relevance_decision_ref"] = pointer
    return retained


def evaluate(document, *, decisions=(), stages=(), set_retained_at=NOW):
    resolved = [e.ResolvedUnit.create(unit_id="fixture-unit", source_label="Invented agency", stages=list(stages), decisions=decisions)]
    return e.evaluate(retained_input(document, retained_at=set_retained_at), resolved, cutoff=NOW, evaluated_at=LATER,
                      state_version=0, policy_sha256="f"*64, input_refs=[])


def test_empty_trace_is_pending_not_zero_recall_or_quiet_world():
    result = evaluate(reference_document())
    assert result["metrics"] == dict(event_recall=None, draft_recall=None, publication_recall=None,
        timeliness=None, confirmed_misses=None, reason="denominator_not_qualified")
    assert result["reference_readiness"]["quiet_periods_qualified"] == 0
    assert result["units"][0]["reference_state"] == "pending"
    assert all(cell["state"] == "not_observed_in_retained_scope" for cell in result["units"][0]["stages"])


def test_split_request_holds_without_creating_children_or_truth():
    choice = decision_document()
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    result = evaluate(document, decisions=[declare(document, choice)])
    assert len(result["units"]) == 1 and result["lineage_edges"] == []
    assert result["units"][0]["reference_state"] == "held"
    assert "grouping_unresolved" in result["units"][0]["holds"]
    assert result["metrics"]["event_recall"] is None


@pytest.mark.parametrize("choice,state", [("one_reported_episode_candidate", "candidate_for_adjudication"), ("exclude", "excluded"), ("hold", "held")])
def test_human_choice_scope_never_qualifies_baseline(choice, state):
    decision = decision_document()
    decision["choice"] = choice
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    result = evaluate(document, decisions=[declare(document, decision)])
    assert result["units"][0]["reference_state"] == state
    assert result["reference_readiness"]["status"] == "not_qualified"
    assert result["metrics"]["confirmed_misses"] is None


def test_later_receipt_cannot_backfill_cutoff_or_earlier_stages():
    saved = e.stage("draft_saved", state="recorded", refs=[pointer()], recorded_at=e.instant_time(LATER), reason_codes=[])
    result = evaluate(reference_document(), stages=[saved])
    cells = {row["stage"]: row for row in result["units"][0]["stages"]}
    assert cells["draft_saved"]["state"] == "held" and cells["draft_saved"]["reason_codes"] == ["later_knowledge"]
    assert cells["physical_episode_detected"]["state"] == "not_observed_in_retained_scope"


def test_calendar_dates_unknown_availability_and_deadline_stay_distinct():
    document = reference_document()
    document["units"][0]["time_fields"]["event_start"] = dict(original="October 11", utc=None, date="2026-10-11", precision="calendar", timezone=None)
    result = evaluate(document)
    row = result["units"][0]
    assert row["original_time_labels"]["event_start"]["utc"] is None
    assert {"calendar_time_only", "deadline_unset", "first_availability_unknown"} <= set(row["holds"])


@pytest.mark.parametrize("mode", ["schema_bool", "gold", "empty", "duplicate", "oversize", "split", "decision_missing", "quiet_gold", "nan", "unknown_fields"])
def test_strict_bounds_no_truncation_or_caller_qualification(mode):
    document = reference_document()
    if mode == "schema_bool":
        document["schema_version"] = True
    elif mode == "gold":
        document["qualification"]["status"] = "qualified"
    elif mode == "empty":
        document["units"] = []
    elif mode == "duplicate":
        document["units"] *= 2
    elif mode == "oversize":
        document["units"] = [dict(unit(), unit_id=str(i)) for i in range(17)]
    elif mode == "split":
        document["units"][0]["predecessor_unit_refs"] = [pointer(e.SET)]
    elif mode == "decision_missing":
        document["units"][0]["relevance_decision_ref"] = pointer(e.DECISION)
    elif mode == "quiet_gold":
        document["quiet_periods"] = [dict(state="qualified_quiet")]
    elif mode == "nan":
        document["units"][0]["hold_codes"] = [float("nan")]
    else:
        document["recall"] = 100
    with pytest.raises(ValueError):
        e.reference_set(document)


@pytest.mark.parametrize("key,value", [("report_sha256", "c"*64), ("unit_id", "unrelated"), ("set_id", "other"), ("claim_ids", ["unrelated"])])
def test_wrong_human_subject_cannot_change_reference(key, value):
    decision = decision_document()
    decision["subject"][key] = value
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    retained = declare(document, decision)
    with pytest.raises(e.CoverageError, match="coverage_decision_subject_changed"):
        evaluate(document, decisions=[retained])


def test_invented_trace_and_archival_replay_keep_execution_class():
    cell = e.stage("story_prepared", state="recorded", refs=[pointer()], recorded_at=e.instant_time(NOW),
                   execution_class="archival_replay", reason_codes=[])
    result = evaluate(reference_document(), stages=[cell])
    assert result["units"][0]["stages"][3]["execution_class"] == "archival_replay"
    assert result["metrics"]["event_recall"] is None


@pytest.mark.parametrize("mode", ["undeclared", "unselected", "wrong_selected", "changed_bytes", "missing_selected"])
def test_only_exact_declared_selected_retained_decision_can_change_state(mode):
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    choice = decision_document()
    retained = retained_input(choice, e.DECISION)
    if mode != "undeclared":
        retained = declare(document, choice)
    if mode == "unselected":
        document["units"][0]["relevance_decision_ref"] = None
    elif mode == "wrong_selected":
        other = deepcopy(choice)
        other["decision_id"] = "other-choice"
        other["choice"] = "exclude"
        pointer = retained_input(other, e.DECISION).value()["reference"]
        document["human_decision_refs"].append(pointer)
        document["units"][0]["relevance_decision_ref"] = pointer
    elif mode == "changed_bytes":
        raw = retained.value()
        raw["wrapper"]["document"]["choice"] = "exclude"
        retained = e.RetainedInput(e.p._canonical(raw))
    with pytest.raises(e.CoverageError):
        evaluate(document, decisions=[] if mode == "missing_selected" else [retained])


def test_loose_decision_document_is_refused_at_pure_boundary():
    with pytest.raises(e.CoverageError, match="coverage_retained_decision_required"):
        e.ResolvedUnit.create(unit_id="fixture-unit", source_label="Invented agency", stages=[], decisions=[decision_document()])


def test_set_receipt_time_not_old_document_time_controls_cutoff():
    document = reference_document()
    assert document["created_at"] == NOW
    with pytest.raises(e.CoverageError, match="coverage_set_after_cutoff"):
        evaluate(document, set_retained_at=LATER)


def test_decision_receipt_time_not_normalized_recorded_at_controls_cutoff():
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    choice = decision_document()
    retained = declare(document, choice, retained_at=LATER)
    assert choice["recorded_at"] == NOW and choice["decided_at"] is None
    with pytest.raises(e.CoverageError, match="coverage_decision_after_cutoff"):
        evaluate(document, decisions=[retained])


def test_equal_cutoff_is_allowed_and_exact_selected_ref_survives_output():
    document = reference_document(dict(lineage_id="fixture-report", report_sha256="b"*64, claim_ids=["claim1"]))
    retained = declare(document, decision_document())
    result = evaluate(document, decisions=[retained])
    pointer = retained.value()["reference"]
    assert result["units"][0]["selected_relevance_decision_ref"] == pointer
    assert pointer in result["input_refs"]
    assert result["reference_readiness"]["human_decisions_recorded"] == 1
