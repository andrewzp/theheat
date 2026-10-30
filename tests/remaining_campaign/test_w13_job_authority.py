"""W13.1/13.3/13.4/13.5 through the real batch executor and local SQLite journals.

The executor is the existing ``submit_batch_once`` with an explicit fake
transport; grants, leases and spending are the real append-only journals.
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from src.commands.schema import CommandError
from src.commands.job_authority import RoleBoundAuthority, ServiceIdentity
from src.commands.job_recovery import inspect_jobs
from src.commands.writer_fencing import WriterGenerationRegistry
from src.two_bot import batch_transport as batch
from src.two_bot.call_inventory import OperationAllowance
from tests import test_batch_worker_journal as workers
from tests.two_bot import test_batch_contract as contracts
from tests.two_bot import test_batch_transport as transport_tests

Clock, FakeTransport = transport_tests.Clock, transport_tests.FakeTransport
inputs, store, prepared = transport_tests.inputs, transport_tests.store, transport_tests.prepared

PRODUCER = ServiceIdentity("producer", "worker-one", "gen-2")


def submit(authority, pair, transport, *, owner="worker-one", clock=None):
    return batch.submit_batch_once(authority, pair[1]["job_id"], current_context=contracts.context(pair[0]),
                                   owner=owner, clock=clock or Clock(), enabled=True, transport_factory=lambda: transport)


def spend_state(raw_store, job):
    return inspect_jobs(raw_store, now=workers.later(1))["jobs"][0]["spend_state"] if job else None


def test_producer_dispatches_once_and_reacquisition_never_spends_twice(prepared):
    raw, pair = prepared
    allowance = OperationAllowance("batch_generation", {"batch_writer": 2})
    producer = RoleBoundAuthority(raw, PRODUCER, allowance=allowance)
    first = FakeTransport()
    report = submit(producer, pair, first)
    assert len(first.calls) == 1 and report["outcome"] != "blocked"
    again = FakeTransport()
    replay = submit(RoleBoundAuthority(raw, PRODUCER, allowance=allowance), pair, again)
    assert again.calls == [] and replay["dispatch_granted"] is False
    summary = allowance.summary()["stages"]["batch_writer"]
    assert summary["reserved"] == 1 and summary["physical_attempts"] == 1
    assert summary["outcomes"]["returned"] == 1 and summary["outcomes"]["released_unstarted"] == 0
    assert spend_state(raw, pair) in {"dispatched", "uncertain"}


def test_exhausted_allowance_refuses_before_any_grant_or_request(prepared):
    raw, pair = prepared
    allowance = OperationAllowance("batch_generation", {"batch_writer": 0})
    producer = RoleBoundAuthority(raw, PRODUCER, allowance=allowance)
    transport = FakeTransport()
    report = submit(producer, pair, transport)
    assert transport.calls == [] and report["dispatch_granted"] is False
    assert {"surface": "batch_writer", "action": "begin", "code": "job_allowance_exhausted"} in producer.refusals
    row = inspect_jobs(raw, now=workers.later(1))["jobs"][0]
    assert row["grant_id"] is None and row["spend_state"] == "reserved" and row["start_state"] == "unstarted"


@pytest.mark.parametrize("identity, code", [
    (ServiceIdentity("checker", "worker-one"), "cross_role_write_refused"),
    (ServiceIdentity("maintenance", "worker-one"), "cross_role_write_refused"),
    (ServiceIdentity("producer", "worker-two"), "lease_owner_mismatch"),
])
def test_cross_role_or_foreign_owner_cannot_take_or_dispatch_a_batch(prepared, identity, code):
    raw, pair = prepared
    adapter = RoleBoundAuthority(raw, identity)
    transport = FakeTransport()
    report = submit(adapter, pair, transport)
    assert transport.calls == [] and report["outcome"] == "blocked"
    assert adapter.refusals[0]["code"] == code
    row = inspect_jobs(raw, now=workers.later(1))["jobs"][0]
    assert row["lease"] is None and row["start_state"] == "unstarted"


def test_obsolete_policy_or_superseded_source_is_refused_at_acquisition(prepared, monkeypatch):
    raw, pair = prepared
    from src.editorial import policy as policy_module
    current = policy_module.current_editorial_policy()
    assert current is not None
    changed = deepcopy(current)
    changed["flags"]["writer_samples"] = current["flags"]["writer_samples"] + 1
    monkeypatch.setattr(policy_module, "current_editorial_policy", lambda: changed)
    adapter = RoleBoundAuthority(raw, PRODUCER)
    with pytest.raises(CommandError) as refused:
        adapter.batch_work("acquire", {"job_id": pair[1]["job_id"], "owner": "worker-one", "ttl_seconds": 60}, now=workers.later(1))
    assert getattr(refused.value, "code", None) == "obsolete_job_input_refused"
    monkeypatch.setattr(policy_module, "current_editorial_policy", lambda: current)
    stale_source = RoleBoundAuthority(raw, PRODUCER, currentness=lambda registration, plan: "source_superseded")
    transport = FakeTransport()
    assert submit(stale_source, pair, transport)["outcome"] == "blocked" and transport.calls == []
    assert stale_source.refusals[-1]["code"] == "obsolete_job_input_refused"
    assert inspect_jobs(raw, now=workers.later(1))["jobs"][0]["lease"] is None


def test_expired_owner_cannot_commit_and_a_lost_result_is_never_unstarted(prepared):
    raw, pair = prepared
    producer = RoleBoundAuthority(raw, PRODUCER)
    job = pair[1]["job_id"]
    lease = producer.batch_work("acquire", {"job_id": job, "owner": "worker-one", "ttl_seconds": 5}, now=workers.later(0))
    grant = producer.batch_work("begin", {"job_id": job, "owner": "worker-one", "fence": lease["lease"]["fence"],
                                          "current_context": contracts.context(pair[0])}, now=workers.later(1))
    assert grant["dispatch_granted"] is True
    # The provider response was lost; the owner's lease then expired.
    with pytest.raises(ValueError, match="batch_lease_expired"):
        producer.batch_work("adopt", {"job_id": job, "owner": "worker-one", "fence": lease["lease"]["fence"],
                                      "receipt_sha256": "0" * 64}, now=workers.later(30))
    row = inspect_jobs(raw, now=workers.later(31))["jobs"][0]
    assert row["start_state"] == "started_result_unknown" and row["worker_state"] == "submission_uncertain"
    assert row["last_durable_stage"]["stage"] in {"granted", "spend_dispatched"}
    assert row["operations"] == ["reconcile"] and row["retry_authorized"] is False
    overdue = inspect_jobs(raw, now="2026-09-30T12:00:01Z")["jobs"][0]
    assert overdue["overdue"] is True and overdue["start_state"] == "started_result_unknown"


def test_retired_or_unauthorized_writer_generations_are_refused_only_when_a_registry_is_supplied(prepared):
    raw, pair = prepared
    job = pair[1]["job_id"]
    registry = WriterGenerationRegistry(authorized={"command_authority:producer": {"gen-2"}},
                                        retired={"command_authority:producer": {"gen-1"}})
    for generation, code in (("gen-1", "retired_writer_generation_refused"), ("gen-3", "unauthorized_writer_generation_refused")):
        adapter = RoleBoundAuthority(raw, ServiceIdentity("producer", "worker-one", generation), writer_registry=registry)
        assert adapter.batch_status(job)["job_id"] == job  # reads stay available
        with pytest.raises(CommandError) as refused:
            adapter.batch_work("acquire", {"job_id": job, "owner": "worker-one", "ttl_seconds": 60}, now=workers.later(1))
        assert refused.value.code == code
    allowed = RoleBoundAuthority(raw, PRODUCER, writer_registry=registry)
    assert allowed.batch_work("acquire", {"job_id": job, "owner": "worker-one", "ttl_seconds": 60}, now=workers.later(1))["lease"]["owner"] == "worker-one"
    unregistered = RoleBoundAuthority(raw, ServiceIdentity("producer", "worker-one", "gen-1"))
    assert unregistered.batch_status(job)["job_id"] == job  # no registry: nothing is activated
