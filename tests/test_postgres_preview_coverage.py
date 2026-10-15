"""Actual local Sources API/metadata command/restore path; invented fixtures."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import pytest

from src.commands import postgres_coverage as coverage
from src.commands.postgres_authority import PostgresCommandAuthority
from src.commands.postgres_report_development import private_configuration as report_configuration
from src.commands.preview_ingress import Operators
from src.commands.schema import utc_text
from src.evaluation import coverage as evaluation
from src.storage import postgres_projection as p
from tests.test_postgres_preview_command_ingress import (preview as preview, cluster as cluster,
    database as database, clean_environment, http)
from tests.test_postgres_coverage_evaluation import setup

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def coverage_preview(preview, tmp_path):
    port, authority, initial, operators, _, arguments, params = preview
    session, document, report, artifact = setup(authority.projections)
    saved = session.retain(evaluation.SET, document, expected_head=None, operation_id=str(uuid4()))
    config = dict(set_id=document["set_id"], set_sha256=saved["sha256"], protocol_refs=list(session.protocol_refs),
        decision_imports=[], report_decision_refs=[], selectors=[])
    path = tmp_path/"coverage.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    report_config = dict(current_reports=[dict(lineage_id=report["lineage_id"], report_sha256=document["units"][0]["report_refs"][0]["report_sha256"], episode_reference=None)], decision_refs=[])
    report_path = tmp_path/"reports.json"
    report_path.write_text(json.dumps(report_config))
    report_path.chmod(0o600)
    authority.configure_coverage(coverage.private_configuration(path))
    authority.configure_report_development(report_configuration(report_path))
    args = [*arguments, "--coverage-inputs", str(path), "--report-inputs", str(report_path)]
    def consume(command_id):
        child = subprocess.run([sys.executable, "-m", "src.commands.preview_worker", *args, "--command-id", command_id],
            cwd=ROOT, env=clean_environment(), capture_output=True, text=True, timeout=30)
        return child.returncode, json.loads(child.stdout)
    return dict(port=port, authority=authority, initial=initial, operators=operators, args=args, params=params,
        session=session, document=document, report=report, artifact=artifact, config=config, path=path,
        report_config=report_config, report_path=report_path, consume=consume)


def request(view, *, now=None):
    now = now or datetime.now(UTC)
    return dict(command_id=str(uuid4()), action="evaluate_reference_coverage", targets=[], requested_at=utc_text(now),
        expires_at=utc_text(now+timedelta(hours=1)), payload={key:view[key] for key in
        ("set_id", "expected_set_sha256", "expected_state_version", "expected_policy_sha256")})


def evaluate(case):
    code, view, _ = http(case["port"], "/coverage")
    assert code == 200 and view["ready"], view
    command = request(view)
    accepted = http(case["port"], "/commands", method="POST", value=command)
    assert accepted[0] == 202, accepted
    result = case["consume"](command["command_id"])
    assert result[0] == 0 and result[1]["result"]["status"] == "applied", result
    return command, accepted[1]["receipt"], result[1]["result"]


def test_actual_component_http_sources_assessment_and_exact_retry(coverage_preview, tmp_path):
    case = coverage_preview
    config = tmp_path/"http-coverage.json"
    config.write_text(json.dumps(dict(endpoint=f'http://127.0.0.1:{case["port"]}', origin="http://127.0.0.1:3035", root=str(ROOT),
        python=sys.executable, arguments=case["args"], expected_reports=1)))
    config.chmod(0o600)
    child = subprocess.run(["node", "--test", "tests/coverage-evidence.test.js"], cwd=ROOT/"dashboard",
        env={**clean_environment(), "THEHEAT_COVERAGE_TEST_CONFIG": str(config)}, capture_output=True, text=True, timeout=90)
    assert child.returncode == 0, child.stdout+child.stderr
    assert case["authority"].read() == (0, case["initial"])
    assert len(case["authority"].journal()) == 2


def test_accepted_cutoff_is_server_receipt_not_browser_time(coverage_preview):
    case = coverage_preview
    view = http(case["port"], "/coverage")[1]
    command = request(view, now=datetime.now(UTC)-timedelta(minutes=15))
    accepted = http(case["port"], "/commands", method="POST", value=command)[1]["receipt"]
    assert accepted["accepted_at"] != command["requested_at"]
    outcome = case["consume"](command["command_id"])
    assert outcome[0] == 0 and outcome[1]["result"]["status"] == "applied", outcome
    view = http(case["port"], "/coverage")[1]
    assert view["assessment"]["cutoff"] == accepted["accepted_at"]
    assert view["assessment"]["units"][0]["stages"][0]["state"] == "recorded"


@pytest.mark.parametrize("mode", ["role", "policy", "report", "set", "state", "unavailable", "expired"])
def test_accepted_assessment_rechecks_authority_and_current_heads(coverage_preview, mode):
    case = coverage_preview
    command = request(http(case["port"], "/coverage")[1])
    if mode == "policy":
        command["payload"]["expected_policy_sha256"] = "f"*64
    if mode == "state":
        from tests.test_postgres_preview_command_ingress import body
        update = body(case["initial"]["drafts"][0])
        assert http(case["port"], "/commands", method="POST", value=update)[0] == 202
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    if mode == "role":
        operators = json.loads(case["operators"].read_text())
        operators["operators"] = [row for row in operators["operators"] if row["role"] != "editor"]
        case["operators"].write_text(json.dumps(operators))
    elif mode == "report":
        report = deepcopy(case["report"])
        old = case["document"]["units"][0]["report_refs"][0]["report_sha256"]
        report.update(previous_report_sha256=old, limits=["Invented later correction"])
        case["session"].reports.retain_revision(report, expected_head=old, operation_id=str(uuid4()))
    elif mode == "set":
        changed = deepcopy(case["document"])
        changed["previous_set_sha256"] = case["config"]["set_sha256"]
        changed["units"][0]["hold_codes"] = ["grouping_unresolved"]
        case["session"].retain(evaluation.SET, changed, expected_head=case["config"]["set_sha256"], operation_id=str(uuid4()))
    elif mode == "state":
        assert case["consume"](update["command_id"])[1]["result"]["status"] == "applied"
    elif mode == "unavailable":
        case["path"].unlink()
    if mode == "expired":
        result = case["authority"].consume(Operators(case["operators"]).resolve, command_id=command["command_id"], now=datetime.now(UTC)+timedelta(hours=2))
        outcome = (0, dict(result=result))
    else:
        outcome = case["consume"](command["command_id"])
    if mode == "unavailable":
        assert outcome[0] == 1 and case["authority"].result(command["command_id"]) is None
        case["path"].write_text(json.dumps(case["config"]))
        case["path"].chmod(0o600)
        assert case["consume"](command["command_id"])[1]["result"]["status"] == "applied"
    else:
        assert outcome[0] == 0 and outcome[1]["result"]["status"] == "rejected", outcome
        with case["authority"].projections._connection() as c:
            assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace=%s", (evaluation.ASSESSMENT,)).fetchone()[0] == 0


def test_correction_keeps_saved_assessment_historical_and_explicit_refresh(coverage_preview):
    case = coverage_preview
    _, _, result = evaluate(case)
    before = http(case["port"], "/coverage")[1]
    changed = deepcopy(case["document"])
    changed["previous_set_sha256"] = case["config"]["set_sha256"]
    changed["units"][0]["hold_codes"] = ["grouping_unresolved"]
    new = case["session"].retain(evaluation.SET, changed, expected_head=case["config"]["set_sha256"], operation_id=str(uuid4()))
    stale = http(case["port"], "/coverage")[1]
    assert stale["currentness"] == "refresh_required" and not stale["ready"]
    assert stale["assessment_ref"] == before["assessment_ref"]
    case["config"]["set_sha256"] = new["sha256"]
    case["path"].write_text(json.dumps(case["config"]))
    ready = http(case["port"], "/coverage")[1]
    assert ready["ready"] and ready["currentness"] == "refresh_required"
    _, _, current = evaluate(case)
    assert current["coverage"]["assessment_ref"] != result["coverage"]["assessment_ref"]
    assert http(case["port"], "/coverage")[1]["currentness"] == "current"
    assert case["authority"].projections.read(**{key:before["assessment_ref"][key] for key in ("namespace", "snapshot_id")})[1] == before["assessment"]


def test_failed_snapshot_result_transaction_rolls_back_and_retry_once(coverage_preview, monkeypatch):
    case = coverage_preview
    command = request(http(case["port"], "/coverage")[1])
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    original = case["authority"]._event
    def fail(c, command_id, event, at, data):
        if event == "completed":
            raise p.ProjectionError("storage_unavailable")
        return original(c, command_id, event, at, data)
    monkeypatch.setattr(case["authority"], "_event", fail)
    with pytest.raises(p.ProjectionError):
        case["authority"].consume(Operators(case["operators"]).resolve, command_id=command["command_id"])
    with case["authority"].projections._connection() as c:
        assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace=%s", (evaluation.ASSESSMENT,)).fetchone()[0] == 0
    assert case["authority"].result(command["command_id"]) is None
    monkeypatch.setattr(case["authority"], "_event", original)
    first = case["consume"](command["command_id"])
    assert first[0] == 0 and first[1]["result"]["status"] == "applied", first
    assert case["consume"](command["command_id"]) == first


def restore_case(case, cluster, completed, pending):
    """Fresh independent cluster; preserves actual retained bytes and journal."""
    import psycopg
    _, tool, _ = cluster
    params = case["params"]
    with tempfile.TemporaryDirectory(prefix="theheat-coverage-restore-", dir="/tmp") as directory:
        location = Path(directory)
        location.chmod(0o700)
        socket = location/"socket"
        socket.mkdir(mode=0o700)
        data = location/"data"
        dump = location/"coverage.dump"
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", location/"server.log", "-o", f"-c listen_addresses='' -k {socket} -p 55477", "-w", "start")
            with psycopg.connect(host=str(socket), port=55477, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_coverage TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55477", "-U", "projection_owner", "-d", "restored_coverage", "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55477, database="restored_coverage", user="projection_runtime")
            restored.configure_coverage(coverage.private_configuration(case["path"]))
            restored.configure_report_development(report_configuration(case["report_path"]))
            assert restored.read() == case["authority"].read()
            assert restored.result(completed["command_id"]) == case["authority"].result(completed["command_id"])
            original_view = case["authority"].coverage_projection(now=datetime.now(UTC))
            restored_view = restored.coverage_projection(now=datetime.now(UTC))
            assert original_view == restored_view
            assert restored.result(pending["command_id"]) is None
            result = restored.consume(Operators(case["operators"]).resolve, command_id=pending["command_id"])
            assert result["status"] == "applied" and result["coverage"]["draft_mutated"] is False
            assert restored.consume(Operators(case["operators"]).resolve, command_id=pending["command_id"]) == result
            assert restored.read() == case["authority"].read()
            return restored.coverage_projection(now=datetime.now(UTC)), result
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


def test_completed_pending_assessment_and_inputs_survive_fresh_restore(coverage_preview, cluster):
    case = coverage_preview
    completed, _, _ = evaluate(case)
    pending = request(http(case["port"], "/coverage")[1])
    assert http(case["port"], "/commands", method="POST", value=pending)[0] == 202
    before = http(case["port"], "/coverage")[1]
    assert before["pending_command"]["command_id"] == pending["command_id"]
    restored, _ = restore_case(case, cluster, completed, pending)
    assert restored["assessment"]["reference_readiness"]["report_lineages"] == 1
    assert restored["assessment"]["metrics"]["event_recall"] is None


def test_set_created_after_acceptance_cannot_backdate_an_assessment(coverage_preview):
    case = coverage_preview
    document = deepcopy(case["document"])
    document["previous_set_sha256"] = case["config"]["set_sha256"]
    document["units"][0]["hold_codes"] = ["grouping_unresolved"]
    expected = coverage.digest(dict(sequence=2, document=document))
    command = request(http(case["port"], "/coverage")[1])
    command["payload"]["expected_set_sha256"] = expected
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    saved = case["session"].retain(evaluation.SET, document, expected_head=case["config"]["set_sha256"], operation_id=str(uuid4()))
    assert saved["sha256"] == expected
    case["config"]["set_sha256"] = expected
    case["path"].write_text(json.dumps(case["config"]))
    result = case["consume"](command["command_id"])
    assert result[0] == 0 and result[1]["result"]["status"] == "rejected", result
    assert result[1]["result"]["code"] == "coverage_set_after_cutoff"


def test_assessment_lost_write_ack_recovers_original_terminal_result(coverage_preview, monkeypatch):
    from contextlib import contextmanager
    case = coverage_preview
    command = request(http(case["port"], "/coverage")[1])
    assert http(case["port"], "/commands", method="POST", value=command)[0] == 202
    connection = p.PostgresProjectionRepository._connection
    @contextmanager
    def lost_ack(owner, *, writing=False):
        with connection(owner, writing=writing) as c:
            yield c
        if writing:
            raise p.ProjectionError("write_outcome_unknown")
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", lost_ack)
    with pytest.raises(p.ProjectionError, match="write_outcome_unknown"):
        case["authority"].consume(Operators(case["operators"]).resolve, command_id=command["command_id"])
    monkeypatch.setattr(p.PostgresProjectionRepository, "_connection", connection)
    result = case["authority"].result(command["command_id"])
    assert result["status"] == "applied"
    assert case["consume"](command["command_id"])[1]["result"] == result
    with case["authority"].projections._connection() as c:
        assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace=%s", (evaluation.ASSESSMENT,)).fetchone()[0] == 1


def test_actual_p20_p21_retained_story_and_review_reach_assessment(coverage_preview):
    from src.storage.physical_events import PhysicalEpisodeSession
    from tests import test_postgres_physical_events as physical
    from tests.test_postgres_preview_report_development import request as report_request
    from src.commands import postgres_report_development as reports
    case = coverage_preview
    now = datetime.now(UTC).replace(microsecond=0)
    before = now-timedelta(hours=6)
    episodes = PhysicalEpisodeSession(case["authority"].projections)
    head = None
    for number, issued, wind in (("1", before, 70), ("2", now, 100)):
        source, receipt, _ = physical.capture(case["authority"].projections,
            [physical.advisory(advisory_number=number, issued_at=utc_text(issued), wind_kt=wind)], now=utc_text(now))
        head = physical.apply(source, receipt, episodes, {physical.EPISODE:head}, now=utc_text(now))["episodes"][0]["revision_sha256"]
    report = deepcopy(case["report"])
    old = case["document"]["units"][0]["report_refs"][0]["report_sha256"]
    report["previous_report_sha256"] = old
    for key, value in (("event_start", before), ("event_end", now)):
        label = value.date().isoformat()
        report["claims"][0]["times"][key] = dict(original=label, utc=None, date=label, precision="calendar", timezone=None)
    report_head = case["session"].reports.retain_revision(report, expected_head=old, operation_id=str(uuid4()))["report_sha256"]
    episode = dict(episode_id=physical.EPISODE, revision_sha256=head, claim_id="claim1")
    case["report_config"]["current_reports"][0].update(report_sha256=report_head, episode_reference=episode)
    case["report_path"].write_text(json.dumps(case["report_config"]))
    open_command = report_request(http(case["port"], "/reports")[1]["reports"][0])
    assert http(case["port"], "/commands", method="POST", value=open_command)[0] == 202
    assert case["consume"](open_command["command_id"])[1]["result"]["status"] == "applied"
    with case["authority"].projections._connection() as c:
        item, _ = reports._latest(c, report["lineage_id"])
    updated = deepcopy(case["document"])
    updated["previous_set_sha256"] = case["config"]["set_sha256"]
    updated["units"][0]["report_refs"][0]["report_sha256"] = report_head
    updated["units"][0]["time_fields"]["event_start"] = report["claims"][0]["times"]["event_start"]
    new_set = case["session"].retain(evaluation.SET, updated, expected_head=case["config"]["set_sha256"], operation_id=str(uuid4()))
    case["config"].update(set_sha256=new_set["sha256"], selectors=[dict(unit_id="fixture-unit", episode_reference=dict(lineage_id=report["lineage_id"], **episode),
        report_command=dict(command_id=open_command["command_id"], development_ref=coverage.ref(item)), scientific_member=None, workflow=None)])
    case["path"].write_text(json.dumps(case["config"]))
    evaluate(case)
    assessment = http(case["port"], "/coverage")[1]["assessment"]
    stages = {row["stage"]:row for row in assessment["units"][0]["stages"]}
    assert all(stages[name]["state"] == "recorded" for name in ("source_input_retained", "physical_episode_detected", "story_prepared", "report_review_opened"))
    assert stages["scientific_evidence_qualified"]["state"] == "not_applicable"
    assert stages["generation_accepted"]["state"] == "not_observed_in_retained_scope"
    assert assessment["metrics"]["event_recall"] is None
    assert case["authority"].read() == (0, case["initial"])


from tests import test_postgres_scientific_supply_retention as scientific
supply, supply_inputs = scientific.supply, scientific.supply_inputs


def test_actual_p18_input_stays_unconfirmed_and_availability_separate(coverage_preview, supply):
    from src.storage.scientific_supply import ScientificSupplySession
    from tests.test_coverage_evaluation import reference_document
    case = coverage_preview
    source = ScientificSupplySession(case["authority"].projections, str(uuid4()), "capture", scientific.NOW, scientific.BASE)
    source.capture(supply[0], supply[1], scientific.metrics_for(supply))
    receipt, bundles, _, _ = source.read()
    bundle = bundles[0]
    document = reference_document()
    document.update(previous_set_sha256=case["config"]["set_sha256"])
    document["selection_protocol"]["protocol_ref"] = case["config"]["protocol_refs"][0]
    document["units"][0].update(unit_kind="physical_event_candidate", source_class="observed", source_alias_refs=[coverage.ref(receipt)])
    saved = case["session"].retain(evaluation.SET, document, expected_head=case["config"]["set_sha256"], operation_id=str(uuid4()))
    selector = dict(supply_ref=coverage.ref(receipt), station_id=bundle.station_id, signal_date=str(bundle.signal_date), evidence_sha256=coverage.digest(bundle.evidence))
    case["config"].update(set_sha256=saved["sha256"], selectors=[dict(unit_id="fixture-unit", episode_reference=None, report_command=None, scientific_member=selector, workflow=None)])
    case["path"].write_text(json.dumps(case["config"]))
    evaluate(case)
    result = http(case["port"], "/coverage")[1]["assessment"]
    assert result["source_availability"][0]["original_status"] == "success"
    assert result["source_availability"][0]["recall_contribution"] is None
    stages = {row["stage"]:row for row in result["units"][0]["stages"]}
    assert stages["source_input_retained"]["state"] == "recorded"
    assert stages["physical_episode_detected"]["state"] == "held"
    assert stages["scientific_evidence_qualified"]["state"] == "unsupported"
    assert result["metrics"]["event_recall"] is None


@pytest.mark.parametrize("expire", [False, True])
def test_resolution_completion_uses_trusted_fresh_clock_and_rechecks_expiry(coverage_preview, monkeypatch, expire):
    case = coverage_preview
    command = request(http(case["port"], "/coverage")[1])
    accepted = http(case["port"], "/commands", method="POST", value=command)[1]["receipt"]
    started = datetime.now(UTC)
    clock = [started]
    original = coverage.resolve_inputs
    def resolve(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] = started + timedelta(hours=2) if expire else started + timedelta(seconds=2)
        return result
    monkeypatch.setattr(coverage, "resolve_inputs", resolve)
    monkeypatch.setattr(coverage, "_completion_clock", lambda: clock[0])
    result = case["authority"].consume(Operators(case["operators"]).resolve, command_id=command["command_id"], now=started)
    if expire:
        assert result["status"] == "rejected" and result["code"] == "coverage_command_expired"
        with case["authority"].projections._connection() as c:
            assert c.execute("SELECT count(*) FROM theheat_projection.versions WHERE namespace=%s", (evaluation.ASSESSMENT,)).fetchone()[0] == 0
    else:
        assert result["status"] == "applied"
        pointer = result["coverage"]["assessment_ref"]
        _, saved = case["authority"].projections.read(pointer["namespace"], pointer["snapshot_id"])
        assert saved["evaluated_at"] == utc_text(clock[0]) and saved["evaluated_at"] != utc_text(started)
        assert saved["cutoff"] == accepted["accepted_at"]
    assert case["authority"].read() == (0, case["initial"])
