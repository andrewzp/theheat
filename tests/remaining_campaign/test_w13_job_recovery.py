"""W13.3/13.6: overdue inspection, schedule diagnosis and bounded recovery commands."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from src.commands import job_recovery as recovery
from src.commands import local_cli
from src.commands.schema import CommandError
from src.commands.job_authority import RoleBoundAuthority, ServiceIdentity
from src.two_bot import batch_transport as batch
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contracts
from tests.two_bot import test_batch_transport as transport_tests

Clock, FakeTransport = transport_tests.Clock, transport_tests.FakeTransport
inputs, store, prepared = transport_tests.inputs, transport_tests.store, transport_tests.prepared

ROOT = Path(__file__).resolve().parents[2]
PRODUCER = ServiceIdentity("producer", "worker-one")
MAINTENANCE = ServiceIdentity("maintenance", "operator-recovery")


def executor(authority, pair, transport):
    return lambda: batch.submit_batch_once(authority, pair[1]["job_id"], current_context=contracts.context(pair[0]),
                                           owner="worker-one", clock=Clock(), enabled=True, transport_factory=lambda: transport)


def test_unstarted_work_resumes_once_through_its_own_executor_then_only_reconciles(prepared):
    raw, pair = prepared
    job = pair[1]["job_id"]
    row = recovery.inspect_jobs(raw, now=workers.later(1))["jobs"][0]
    assert row["start_state"] == "unstarted" and row["operations"] == ["resume", "release_unstarted"]
    producer = RoleBoundAuthority(raw, PRODUCER)
    transport = FakeTransport()
    recovery.resume_unstarted(producer, job, executor=executor(producer, pair, transport), now=workers.later(1))
    assert len(transport.calls) == 1
    with pytest.raises(CommandError) as refused:
        recovery.resume_unstarted(producer, job, executor=executor(producer, pair, FakeTransport()), now=workers.later(2))
    assert refused.value.code == "resume_refused_started_or_unknown"
    maintenance = RoleBoundAuthority(raw, MAINTENANCE)
    with pytest.raises(CommandError) as release:
        recovery.release_unstarted(maintenance, job, now=workers.later(3))
    assert release.value.code == "release_refused_started_or_unknown"
    # Even a stale inspection cannot erase a dispatch: the journal refuses too.
    with pytest.raises(ValueError, match="cannot_release_dispatched_spend"):
        maintenance.spending("release", {"intent_id": pair[1]["intent_id"]}, now=workers.later(3))
    record = recovery.reconcile(maintenance, job, now=workers.later(4))
    assert record["retry_authorized"] is False and record["grant_id"]


def test_release_only_for_never_granted_work_and_then_nothing_can_dispatch(prepared):
    raw, pair = prepared
    job = pair[1]["job_id"]
    producer = RoleBoundAuthority(raw, PRODUCER)
    with pytest.raises(CommandError) as cross:
        recovery.release_unstarted(producer, job, now=workers.later(1))
    assert cross.value.code == "cross_role_write_refused"
    maintenance = RoleBoundAuthority(raw, MAINTENANCE)
    with pytest.raises(CommandError) as early:
        recovery.reconcile(maintenance, job, now=workers.later(1))
    assert early.value.code == "reconcile_not_applicable"
    result = recovery.release_unstarted(maintenance, job, now=workers.later(1))
    assert result["sent"] is False
    transport = FakeTransport()
    report = executor(producer, pair, transport)()
    assert transport.calls == [] and report["dispatch_granted"] is False
    after = recovery.inspect_jobs(raw, now=workers.later(5))["jobs"][0]
    assert after["start_state"] == "released" and after["operations"] == [] and after["overdue"] is False


def test_expired_unstarted_work_offers_release_only(prepared):
    raw, _ = prepared
    row = recovery.inspect_jobs(raw, now="2026-09-30T12:00:01Z")["jobs"][0]
    assert row["operations"] == ["release_unstarted"] and row["overdue"] is True and row["hold_code"] == "release_only"


def test_schedule_statuses_stay_distinct_and_never_authorize_reruns():
    now = "2026-10-30T12:00:00Z"
    rows = [
        {"workflow": "theheat-bot", "category": "healthy", "run_created_at": "2026-10-30T09:00:00Z"},
        {"workflow": "voice-regression", "category": "healthy", "run_created_at": "2026-10-30T09:17:00Z"},
        {"workflow": "refresh-thresholds", "category": "failing", "run_created_at": "2026-10-26T02:00:00Z"},
        {"workflow": "source-health-sentinel", "category": "healthy", "run_created_at": "2026-10-30T11:30:00Z"},
    ]
    found = {r["workflow"]: r for r in recovery.diagnose_schedules(rows, now=now, disabled=["time-travel-canary"],
                                                                   blocked={"voice-regression": "paid lane off"})}
    assert found["theheat-bot"]["status"] == "missing" and found["theheat-bot"]["recovery"] == "inspect_jobs_resume_only_unstarted"
    assert found["voice-regression"]["status"] == "blocked"
    assert found["refresh-thresholds"]["status"] == "failing"
    assert found["source-health-sentinel"]["status"] == "completed"
    assert found["time-travel-canary"]["status"] == "disabled"
    assert all(r["rerun_authorized"] is False for r in found.values())
    unknown = recovery.diagnose_schedules([{"workflow": "source-health-sentinel", "category": "unknown",
                                            "run_created_at": "2026-10-30T11:50:00Z"}], now=now)
    assert {r["workflow"]: r["status"] for r in unknown}["source-health-sentinel"] == "unknown"


def test_scheduled_roles_match_the_existing_monitored_workflows():
    from scripts.workflow_health import MONITORED_WORKFLOWS
    assert {(w["name"], w["file"]) for w in MONITORED_WORKFLOWS} == {(k, v["file"]) for k, v in recovery.SCHEDULED_ROLES.items()}
    for spec in recovery.SCHEDULED_ROLES.values():
        assert "cron:" in (ROOT / ".github" / "workflows" / spec["file"]).read_text()


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


def test_local_cli_inspects_holds_and_runs_only_safe_recovery(prepared, tmp_path):
    raw, pair = prepared
    health = tmp_path / "health.json"
    health.write_text(json.dumps([{"workflow": "theheat-bot", "category": "healthy", "run_created_at": "2020-01-01T00:00:00Z"}]))
    code, output = cli("--database", raw.path, "jobs", "--workflow-health", str(health))
    assert code == 0 and output["inspection"]["automatic_retry"] is False
    subjects = {hold["subject"]: hold for hold in output["holds"]}
    assert subjects["schedule:theheat-bot"]["code"] == "schedule_missing"
    assert "job:" + pair[1]["job_id"] in subjects
    code, refused = cli("--database", raw.path, "recover", "--job-id", pair[1]["job_id"], "--operation", "reconcile")
    assert code == 2 and refused["error"] == "reconcile_not_applicable"
    code, released = cli("--database", raw.path, "recover", "--job-id", pair[1]["job_id"], "--operation", "release_unstarted")
    assert code == 0 and released["sent"] is False
