"""Invented reference inputs over actual P18/P20/P21 retained PG readers."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from dataclasses import replace
import hashlib
from uuid import uuid4

import pytest

from src.commands import postgres_coverage as domain
from src.commands import postgres_report_development as report_domain
from src.commands.schema import Principal, utc_text
from src.editorial.policy import current_editorial_policy
from src.evaluation import coverage as e
from src.storage import postgres_projection as p
from src.storage.retained_reports import digest
from tests import test_coverage_evaluation as pure
from tests import test_postgres_report_development as reports
from tests import test_postgres_physical_events as episodes
from tests import test_postgres_scientific_supply_retention as scientific
from tests import test_postgres_projection as pg

cluster, database, repository = pg.cluster, pg.database, pg.repository
isolated = episodes.isolated
supply, supply_inputs = scientific.supply, scientific.supply_inputs


def setup(repo):
    retained, report, report_sha, artifact = reports.retained(repo)
    raw = b"Invented independent-selection packet. Not human adjudication."
    protocol = retained.retain_artifact(raw, declared_sha256=hashlib.sha256(raw).hexdigest(), metadata=reports.meta())
    session = domain.CoverageSession(repo, (domain.ref(protocol),))
    document = pure.reference_document(dict(lineage_id=report["lineage_id"], report_sha256=report_sha, claim_ids=["claim1"]))
    document["selection_protocol"]["protocol_ref"] = domain.ref(protocol)
    document["units"][0]["time_fields"]["event_start"] = report["claims"][0]["times"]["event_start"]
    return session, document, report, artifact


def test_retention_exact_retry_and_current_report_reader(repository):
    session, document, report, _ = setup(repository[1])
    operation = str(uuid4())
    saved = session.retain(e.SET, document, expected_head=None, operation_id=operation)
    assert session.retain(e.SET, document, expected_head=None, operation_id=operation) == saved
    assert session.read_set(document["set_id"], saved["sha256"])[1] == document
    now = utc_text(datetime.now(UTC))
    stages, label, holds = domain.resolve_report_unit(session, document["units"][0], cutoff=now)
    assert label == report["publisher"]
    assert stages[0]["stage"] == "source_input_retained" and stages[0]["state"] == "recorded"
    assert stages[1]["state"] == "not_applicable"
    assert "source_claim_unqualified" in holds
    changed = deepcopy(document)
    changed["qualification"]["reason_codes"].append("grouping_unresolved")
    with pytest.raises(e.CoverageError, match="coverage_operation_conflict"):
        session.retain(e.SET, changed, expected_head=None, operation_id=operation)


def test_report_correction_keeps_original_and_requires_current_refresh(repository):
    session, document, report, _ = setup(repository[1])
    saved = session.retain(e.SET, document, expected_head=None, operation_id=str(uuid4()))
    old = document["units"][0]["report_refs"][0]["report_sha256"]
    corrected = deepcopy(report)
    corrected["previous_report_sha256"] = old
    corrected["claims"][0]["holds"].append("impact_scope_conflict")
    new = session.reports.retain_revision(corrected, expected_head=old, operation_id=str(uuid4()))
    with pytest.raises(ValueError, match="report_head_changed"):
        session.read_set(document["set_id"], saved["sha256"])
    assert session.read_ref(saved)[1]["document"] == document
    updated = deepcopy(document)
    updated["previous_set_sha256"] = saved["sha256"]
    updated["units"][0]["report_refs"][0]["report_sha256"] = new["report_sha256"]
    new_set = session.retain(e.SET, updated, expected_head=saved["sha256"], operation_id=str(uuid4()))
    assert new_set != saved and session.read_set(document["set_id"])[1] == updated


def test_atomic_retention_failure_and_unknown_ack_recovery(repository, monkeypatch):
    session, document, _, _ = setup(repository[1])
    connection = p.PostgresProjectionRepository._connection
    @contextmanager
    def lost_ack(owner, *, writing=False):
        with connection(owner, writing=writing) as c:
            yield c
        if writing:
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", lost_ack)
    saved = session.retain(e.SET, document, expected_head=None, operation_id=str(uuid4()))
    assert session.read_set(document["set_id"])[0].canonical_sha256 == saved["sha256"]
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", connection)
    record = p.PostgresProjectionRepository._record
    def fail(c, namespace, *args):
        if namespace == domain.OPERATION:
            raise p.ProjectionError("storage_unavailable")
        return record(c, namespace, *args)
    monkeypatch.setattr(p.PostgresProjectionRepository, "_record", staticmethod(fail))
    changed = deepcopy(document)
    changed["previous_set_sha256"] = saved["sha256"]
    changed["qualification"]["reason_codes"].append("grouping_unresolved")
    with pytest.raises(p.ProjectionError):
        session.retain(e.SET, changed, expected_head=saved["sha256"], operation_id=str(uuid4()))
    assert session.read_set(document["set_id"])[0].canonical_sha256 == saved["sha256"]


def human_fixture(session, document, artifact):
    value = pure.decision_document()
    value["subject"]["report_sha256"] = document["units"][0]["report_refs"][0]["report_sha256"]
    packet_ref = document["selection_protocol"]["protocol_ref"]
    value["packet_sha256"] = session.artifact(packet_ref)[1]["sha256"]
    raw = b"INVENTED FIXTURE RESPONSE: keep held pending supported incident splits."
    response = session.reports.retain_artifact(raw, declared_sha256=hashlib.sha256(raw).hexdigest(), metadata=reports.meta())
    value["human_response_ref"] = domain.ref(response)
    raw = session.reports.read_artifact(artifact.snapshot_id)[2]
    value["source_anchor_refs"] = [dict(artifact_id=artifact.snapshot_id, content_sha256=hashlib.sha256(raw).hexdigest(), start=0, end=len(raw))]
    imported = dict(document_sha256=digest(value), response_ref=domain.ref(response), packet_ref=packet_ref)
    return replace(session, decision_imports=(imported,)), value


def test_exact_trusted_human_mapping_only_and_split_hold(repository):
    session, document, _, artifact = setup(repository[1])
    trusted, choice = human_fixture(session, document, artifact)
    with pytest.raises(e.CoverageError, match="coverage_human_import_untrusted"):
        session.retain(e.DECISION, choice, expected_head=None, operation_id=str(uuid4()))
    saved_choice = trusted.retain(e.DECISION, choice, expected_head=None, operation_id=str(uuid4()))
    document["human_decision_refs"] = [saved_choice]
    document["units"][0]["relevance_decision_ref"] = saved_choice
    saved = trusted.retain(e.SET, document, expected_head=None, operation_id=str(uuid4()))
    assert trusted.read_set(document["set_id"])[0].canonical_sha256 == saved["sha256"]
    resolved = e.ResolvedUnit.create(unit_id="fixture-unit", source_label="Invented agency", stages=[], decisions=[trusted.evaluation_decision(saved_choice)])
    now = utc_text(datetime.now(UTC))
    result = e.evaluate(trusted.evaluation_set(document["set_id"], saved["sha256"]), [resolved], cutoff=now, evaluated_at=now, state_version=0,
                        policy_sha256="a"*64, input_refs=[saved_choice])
    assert result["units"][0]["reference_state"] == "held" and result["lineage_edges"] == []
    assert result["reference_readiness"]["human_decisions_recorded"] == 1
    changed = deepcopy(choice)
    changed["choice"] = "one_reported_episode_candidate"
    with pytest.raises(e.CoverageError, match="coverage_human_import_untrusted"):
        trusted.decision_document(changed)


@pytest.mark.parametrize("mode", ["protocol", "claim", "label", "time", "deadline", "split", "alias", "decision_subject"])
def test_unproven_binding_never_enters_set(repository, mode):
    session, document, _, artifact = setup(repository[1])
    candidate = document["units"][0]
    if mode == "protocol":
        document["selection_protocol"]["protocol_ref"]["sha256"] = "e"*64
    elif mode == "claim":
        candidate["report_refs"][0]["claim_ids"] = ["other"]
    elif mode == "label":
        receipt = session.reports.read_current(candidate["report_refs"][0]["lineage_id"])[0]
        candidate["region_memberships"] = [dict(label="Invented unsourced country", evidence_ref=domain.ref(receipt))]
    elif mode == "time":
        candidate["time_fields"]["first_available_at"] = e.instant_time(pure.NOW)
    elif mode == "deadline":
        candidate["deadline"] = dict(at=e.instant_time(pure.NOW), policy_ref=document["selection_protocol"]["protocol_ref"])
    elif mode == "split":
        candidate["predecessor_unit_refs"] = [pure.pointer(e.SET)]
    elif mode == "alias":
        candidate["source_alias_refs"] = [pure.pointer()]
    else:
        session, choice = human_fixture(session, document, artifact)
        choice["subject"]["unit_id"] = "other"
        imports = deepcopy(session.decision_imports[0])
        imports["document_sha256"] = digest(choice)
        session = replace(session, decision_imports=(imports,))
        saved = session.retain(e.DECISION, choice, expected_head=None, operation_id=str(uuid4()))
        document["human_decision_refs"] = [saved]
        candidate["relevance_decision_ref"] = saved
    with pytest.raises(ValueError):
        session.retain(e.SET, document, expected_head=None, operation_id=str(uuid4()))


def test_actual_episode_story_refs_and_source_receipt_cutoff(repository):
    repo = repository[1]
    session, document, _, _ = setup(repo)
    _, physical_head, _, _ = episodes.seed(repo)
    report_ref = document["units"][0]["report_refs"][0]
    episode = dict(episode_id=episodes.EPISODE, revision_sha256=physical_head, claim_id="claim1")
    authority, _ = reports.authority_fixture(repo, report_ref["report_sha256"], episode)
    command = reports.command_fixture(report_ref["report_sha256"], episode)
    with repo._connection(writing=True) as c:
        repo._validate(c)
        report_domain.prepare(authority, c, {}, command, Principal("fixture-editor", "editor", "fixture-session"),
                              now=reports.NOW, editorial_policy=current_editorial_policy())
    with repo._connection() as c:
        repo._validate(c)
        item = report_domain._latest(c, report_ref["lineage_id"])
    pointer = dict(lineage_id=report_ref["lineage_id"], **episode)
    before = "2000-01-01T00:00:00Z"
    stages, _, _ = domain.resolve_report_unit(session, document["units"][0], cutoff=before,
                                             episode_reference=pointer, development_ref=domain.ref(item[0]))
    assert all(row["state"] == "held" and "later_knowledge" in row["reason_codes"] for row in stages if row["stage"] in {"source_input_retained", "physical_episode_detected", "story_prepared"})
    after = utc_text(datetime.now(UTC))
    stages, _, _ = domain.resolve_report_unit(session, document["units"][0], cutoff=after,
                                             episode_reference=pointer, development_ref=domain.ref(item[0]))
    assert {row["stage"] for row in stages if row["state"] == "recorded"} == {"source_input_retained", "physical_episode_detected", "story_prepared"}
    assert not any(row["stage"] == "report_review_opened" for row in stages)  # needs actual command receipt
    assert not any(row["stage"] in {"generation_accepted", "draft_saved"} for row in stages)


def test_lock_order_is_identical_to_report_before_episode_protocol(monkeypatch):
    locked = []
    monkeypatch.setattr(domain, "_lock", lambda c, identity: locked.append(identity))
    domain.lock_current_heads(None, ["report-z", "report-a", "report-z"], ["episode-z", "episode-a"])
    assert locked == ["report-a", "report-z", "episode-a", "episode-z"]


def test_actual_p18_retained_member_is_not_confirmed_heatwave(repository, supply):
    from src.storage.scientific_supply import ScientificSupplySession
    repo = repository[1]
    capture = ScientificSupplySession(repo, str(uuid4()), "capture", scientific.NOW, scientific.BASE)
    capture.capture(supply[0], supply[1], scientific.metrics_for(supply))
    receipt, bundles, _, _ = capture.read()
    bundle = bundles[0]
    selector = dict(supply_ref=domain.ref(receipt), station_id=bundle.station_id, signal_date=str(bundle.signal_date), evidence_sha256=digest(bundle.evidence))
    stages, outcome = domain.resolve_scientific_member(domain.CoverageSession(repo), selector, cutoff=utc_text(datetime.now(UTC)))
    assert outcome["status"] == "success" and stages[0]["state"] == "recorded"
    assert stages[1]["state"] == "held" and stages[1]["reason_codes"] == ["grouping_unresolved"]
    assert stages[2]["state"] == "unsupported"
    assert all(row["execution_class"] == "retained_runtime" for row in stages)
    selector["station_id"] = "UNRELATED00"
    with pytest.raises(e.CoverageError, match="coverage_supply_member_changed"):
        domain.resolve_scientific_member(domain.CoverageSession(repo), selector, cutoff=utc_text(datetime.now(UTC)))

# The existing actual SDK MockTransport fixture exercises retained generation
# and admission. It is not a reference match or live model-quality benchmark.
from tests import test_postgres_sourced_generation as generation_fixture
from tests import test_postgres_candidate_admission as candidate_fixture
from src.editorial.revisions import fingerprint
core, make_authority = generation_fixture.core, generation_fixture.make_authority
spend_store, worker_store = generation_fixture.spend_store, generation_fixture.worker_store
base_store, store, inputs = generation_fixture.base_store, generation_fixture.store, generation_fixture.inputs
sourced = generation_fixture.sourced


def test_actual_writer_candidate_and_saved_revision_journals_require_exact_upstream(sourced, monkeypatch):
    case = sourced
    generation_fixture.request(case)
    sent, factory = generation_fixture.transport(case)
    assert generation_fixture.run(case, "submit", factory)["outcome"] == "submitted"
    assert generation_fixture.run(case, "collect", factory)["outcome"] == "reviewed"
    captured = generation_fixture.run(case, "capture")
    checked = dict(store=case["store"], refs=captured["candidate"])
    candidate_fixture.complete(checked, monkeypatch)
    admitted = candidate_fixture.command(checked, "admit_checked_candidate")
    assert candidate_fixture.consume(checked, admitted)["status"] == "applied"
    selector = dict(generation_command_id=case["request"].command_id, admission_input_ref=dict(
        namespace="candidate-admission-input-v1", snapshot_id=captured["candidate"]["admission_input_id"],
        sha256=captured["candidate"]["admission_input_sha256"]), admission_command_id=admitted.command_id)
    state = case["store"].read()[1]
    with case["store"].projections._connection() as c:
        case["store"]._validate(c)
        from src.commands import postgres_sourced_generation as generation
        _, _, job = generation.runner_identity(case["store"], c, case["request"].command_id)
        prepared = [dict(bundle_sha256=fingerprint(case["value"]["bundle"]), memory_sha256=fingerprint(job["memory"]),
            policy_sha256=job["context"]["policy_sha256"])]
        # This is a standalone adapter binding probe. No invented P20 enrollment
        # or report-reference membership is created from these hashes.
        cells = domain.resolve_workflow(case["store"], c, selector, prepared, cutoff=utc_text(datetime.now(UTC)), current_state=state)
        assert [row["stage"] for row in cells] == ["generation_accepted", "candidate_retained", "checks_completed", "draft_saved"]
        assert all(row["state"] == "recorded" for row in cells)
        with pytest.raises(e.CoverageError, match="coverage_prepared_story_binding_missing"):
            domain.resolve_workflow(case["store"], c, selector, [], cutoff=utc_text(datetime.now(UTC)), current_state=state)
        edited = deepcopy(state)
        edited["drafts"][-1]["text"] = "Invented later edit."
        later = domain.resolve_workflow(case["store"], c, selector, prepared, cutoff=utc_text(datetime.now(UTC)), current_state=edited)
        assert later[-1]["state"] == "recorded" and later[-1]["current_binding"] == "superseded"
    assert len(sent) == 3  # no provider calls on any coverage read


def test_actual_report_command_receipt_is_required_for_opened_stage(core):
    from src.commands.schema import Command
    from datetime import timedelta
    authority = core[0]
    session, document, _, _ = setup(authority.projections)
    report_ref = document["units"][0]["report_refs"][0]
    authority.configure_report_development(lambda: dict(current_reports=[dict(**{key: report_ref[key] for key in ("lineage_id", "report_sha256")}, episode_reference=None)], decision_refs=[]))
    now = datetime.now(UTC)
    actor = Principal("fixture-editor", "editor", "fixture-session")
    command = Command.from_request(dict(command_id=str(uuid4()), action="open_report_evidence", targets=[], requested_at=utc_text(now),
        expires_at=utc_text(now+timedelta(hours=1)), payload=dict(lineage_id=report_ref["lineage_id"], report_sha256=report_ref["report_sha256"],
            expected_policy_sha256=digest(current_editorial_policy()), episode_reference=None)), actor, environment="local", now=now)
    authority.accept(command, actor, now=now)
    result = authority.consume(lambda subject: actor, command_id=command.command_id, now=now)
    assert result["status"] == "applied"
    with authority.projections._connection() as c:
        authority._validate(c)
        receipt, _ = report_domain._latest(c, report_ref["lineage_id"])
        selector = dict(command_id=command.command_id, development_ref=domain.ref(receipt))
        cell = domain.resolve_report_command(authority, c, selector, document["units"][0], cutoff=utc_text(datetime.now(UTC)))
        assert cell["stage"] == "report_review_opened" and cell["state"] == "recorded"
        unrelated = deepcopy(document["units"][0])
        unrelated["report_refs"][0]["report_sha256"] = "f"*64
        with pytest.raises(e.CoverageError, match="coverage_development_binding_changed"):
            domain.resolve_report_command(authority, c, selector, unrelated, cutoff=utc_text(datetime.now(UTC)))
    assert authority.read() == (0, core[1])


def test_evaluation_boundary_preserves_database_retention_time_after_restart(repository):
    from datetime import timedelta
    session, document, _, artifact = setup(repository[1])
    trusted, choice = human_fixture(session, document, artifact)
    decision_ref = trusted.retain(e.DECISION, choice, expected_head=None, operation_id=str(uuid4()))
    document["human_decision_refs"] = [decision_ref]
    document["units"][0]["relevance_decision_ref"] = decision_ref
    set_ref = trusted.retain(e.SET, document, expected_head=None, operation_id=str(uuid4()))
    restarted = replace(trusted)
    retained_set = restarted.evaluation_set(document["set_id"], set_ref["sha256"])
    retained_decision = restarted.evaluation_decision(decision_ref)
    set_time = retained_set.value()["retained_at"]
    decision_time = retained_decision.value()["retained_at"]
    assert retained_set.value()["wrapper"]["document"]["created_at"] == pure.NOW
    assert retained_decision.value()["wrapper"]["document"]["recorded_at"] == pure.NOW
    assert set_time == domain.record_time(restarted.read_ref(set_ref)[0])
    assert decision_time == domain.record_time(restarted.read_ref(decision_ref)[0])
    resolved = e.ResolvedUnit.create(unit_id="fixture-unit", source_label="Invented agency", stages=[], decisions=[retained_decision])
    cutoff = utc_text(e.utc_datetime(set_time)-timedelta(microseconds=1))
    with pytest.raises(e.CoverageError, match="coverage_set_after_cutoff"):
        e.evaluate(retained_set, [resolved], cutoff=cutoff, evaluated_at=utc_text(datetime.now(UTC)), state_version=0,
                   policy_sha256="a"*64, input_refs=[])
    now = utc_text(datetime.now(UTC))
    result = e.evaluate(retained_set, [resolved], cutoff=now, evaluated_at=now, state_version=0, policy_sha256="a"*64, input_refs=[])
    assert result["units"][0]["reference_state"] == "held"
    assert result["units"][0]["selected_relevance_decision_ref"] == decision_ref
