"""A local check keeps authority checks without consuming provider capacity."""
from __future__ import annotations

import pytest

from src.commands.job_authority import RoleBoundAuthority, ServiceIdentity
from src.commands.schema import CommandError
from src.two_bot.call_inventory import OperationAllowance


class CheckJournal:
    """Explicit in-memory boundary fixture; never a production check fallback."""

    def __init__(self):
        self.stages: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    def candidate_checks(self, action, payload, **options):
        stage = payload.get("stage", "")
        self.calls.append((action, stage))
        if action == "status":
            return {"stages": dict(self.stages)}
        if action == "begin":
            if stage == "deterministic" and payload.get("reservation") is not None:
                raise CommandError("local_check_cannot_spend", "Local check cannot spend")
            reused = stage in self.stages
            self.stages[stage] = "started"
            return {"dispatch_granted": not reused, "grant_id": f"grant-{stage}"}
        if action == "complete":
            self.stages[stage] = "passed"
            return {"disposition": "passed", "reused": False}
        raise AssertionError(action)


def adapter(limit):
    journal = CheckJournal()
    allowance = OperationAllowance("required_checks", {"local_required_check": limit})
    worker = RoleBoundAuthority(journal, ServiceIdentity("checker", "checker-one"), allowance=allowance)
    return worker, journal, allowance


def begin(worker, stage, reservation=None):
    return worker.candidate_checks("begin", {"check_set_id": "checks-one", "owner": "checker-one",
        "stage": stage, "reservation": reservation}, now="2026-10-30T12:00:00Z", request=b"invented-check")


def test_zero_provider_allowance_still_runs_local_authority_and_replay():
    worker, journal, allowance = adapter(0)
    assert begin(worker, "deterministic")["dispatch_granted"] is True
    assert begin(worker, "deterministic")["dispatch_granted"] is False
    assert ("begin", "deterministic") in journal.calls
    assert allowance.summary()["stages"]["local_required_check"]["reserved"] == 0
    assert allowance.summary()["stages"]["local_required_check"]["physical_attempts"] == 0
    with pytest.raises(CommandError) as refused:
        begin(worker, "deterministic", {"intent_id": "not-local"})
    assert refused.value.code == "local_check_cannot_spend"


def test_four_stages_consume_only_three_provider_slots_and_local_completion_stays_free():
    worker, _, allowance = adapter(3)
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        grant = begin(worker, stage)
        worker.candidate_checks("complete", {"check_set_id": "checks-one", "owner": "checker-one", "stage": stage},
            now="2026-10-30T12:00:00Z", receipt={"grant_id": grant["grant_id"]})
    row = allowance.summary()["stages"]["local_required_check"]
    assert row["reserved"] == row["physical_attempts"] == row["outcomes"]["returned"] == 3
    assert begin(worker, "critic")["dispatch_granted"] is False
    assert allowance.summary()["stages"]["local_required_check"] == row


def test_local_stage_does_not_bypass_role_or_owner_checks():
    worker, journal, _ = adapter(0)
    worker.identity = ServiceIdentity("producer", "checker-one")
    with pytest.raises(CommandError) as refused:
        begin(worker, "deterministic")
    assert refused.value.code == "cross_role_write_refused"
    assert journal.calls == []
    worker.identity = ServiceIdentity("checker", "other-owner")
    with pytest.raises(CommandError) as refused:
        begin(worker, "deterministic")
    assert refused.value.code == "lease_owner_mismatch"
    assert journal.calls == []
