"""Offline own-barrier counterexamples; source/DB primitives are explicit fixtures.

These prove the private transition fences, never source qualification or a send.
The actual source/native/transport journey remains in the PostgreSQL test.
"""

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from src.commands import postgres_delivery as delivery
from src.commands.schema import CommandError
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as projection
from src.two_bot import ghcn_claim_view as ghcn
from tests.ghcn_graphic_helpers import graphic_bundles


@pytest.fixture
def barrier(monkeypatch):
    full = graphic_bundles()[-1]
    full_sha = fingerprint(ghcn.json_tree(full.to_dict()))
    reference = dict(
        source_run_id="00000000-0000-4000-8000-000000000001",
        selection=dict(
            station_id="USW00000000", signal_date="2026-09-08", signal_field="all_time_high"
        ),
    )
    claim = ghcn.ResolvedClaim(full, full, reference, full_sha, full_sha, {})
    state = dict(drafts=[dict(id="draft", event_id=full.event_id)])
    authority = SimpleNamespace()
    control: dict[str, Any] = dict(state=state, version=7, source="a" * 64, baseline=("original",), clock=100.0)
    authority._state = lambda connection, lock=False: (
        control["version"],
        deepcopy(control["state"]),
    )
    policy, configuration = dict(version=1), dict(contract="original")
    targets = [
        dict(id="draft", event_id=full.event_id),
        dict(id="ghcn-event-query:" + full.event_id, event_id=full.event_id),
    ]
    value = dict(
        intent_id="intent",
        draft_id="draft",
        event_id=full.event_id,
        configuration_sha256="b" * 64,
        fixture=dict(instance_id="fixture"),
        approval_binding=dict(publisher_subject="publisher", requesting_actor="editor"),
    )
    work = delivery.work(value, "x")
    body = b"invented exact original request bytes"
    request = dict(
        version=1,
        method="POST",
        path="/1.1/media/upload.json",
        content_type="invented/unit",
        body_sha256=projection._sha(body),
        byte_count=len(body),
    )
    request_sha = projection._sha(projection._canonical(request))
    binding = dict(
        intent_id="intent",
        platform="x",
        stage="upload",
        owner="worker",
        fence=1,
        expires_at="2026-10-22T12:00:30Z",
        request_sha256=request_sha,
        configuration_sha256=value["configuration_sha256"],
        recorded_at="2026-10-22T12:00:01Z",
        prior={},
    )
    binding["attempt_id"] = fingerprint(binding)
    previous: dict[str, Any] = dict(
        catalog=dict(version=1),
        rows={name: [] for name in ghcn.domain.TABLE_COLUMNS},
        artifacts=[],
        outcomes={
            "intent": {
                platform: {stage: dict(status="pending", result=None) for stage in stages}
                for platform, stages in delivery.STAGES.items()
            }
        },
        protection_codes=[],
    )
    previous["rows"]["intents"] = [
        ["intent", "command", "draft", full.event_id, "proposal", "intent-sha"]
    ]
    previous["rows"]["work_items"] = [[work, "intent", "x"]]
    previous["rows"]["leases"] = [
        [work, "upload", 1, "worker", "2026-10-22T12:00:00Z", binding["expires_at"]]
    ]
    previous["artifacts"] = [["intent-sha", 10]]
    current = deepcopy(previous)
    binding_raw, request_raw = projection._canonical(binding), projection._canonical(request)
    current["rows"]["attempts"] = [
        [binding["attempt_id"], work, "upload", 1, projection._sha(binding_raw), request_sha]
    ]
    current["artifacts"] = sorted(
        previous["artifacts"]
        + [[projection._sha(binding_raw), len(binding_raw)], [request_sha, len(request_raw)]]
    )
    current["outcomes"]["intent"]["x"]["upload"] = dict(status="unknown", result=None)
    current["protection_codes"] = [
        dict(draft_id=row["id"], event_id=row["event_id"], code="delivery_prior_outcome_unknown")
        for row in targets
    ]
    checkpoint = dict(
        state_version=7,
        state_sha256=ghcn.digest(state),
        source_sha256=control["source"],
        delivery=previous,
        policy_sha256=ghcn.digest(policy),
        configuration=configuration,
    )
    prepared = ghcn.ExecutionContext(authority, claim, checkpoint, control["baseline"], 220.0, {})
    control.update(
        current=current,
        value=deepcopy(value),
        binding=deepcopy(binding),
        request=deepcopy(request),
        body=body,
        reads=0,
    )

    def read_source(*args):
        control["reads"] += 1
        return object()

    monkeypatch.setattr(ghcn, "_read_source", read_source)
    monkeypatch.setattr(ghcn, "_source_pins", lambda material: control["source"])
    monkeypatch.setattr(ghcn, "baseline_footprint", lambda baseline: control["baseline"])
    monkeypatch.setattr(ghcn.domain, "configured", lambda authority: object())
    monkeypatch.setattr(ghcn, "current_editorial_policy", lambda: policy)
    monkeypatch.setattr(ghcn.inputs, "configuration", lambda: configuration)
    monkeypatch.setattr(
        ghcn.inputs, "state_dependencies", lambda state: dict(targets=deepcopy(targets[:-1]))
    )
    monkeypatch.setattr(
        ghcn.domain, "delivery_dependency", lambda *args: deepcopy(control["current"])
    )
    monkeypatch.setattr(delivery.time, "monotonic", lambda: control["clock"])
    monkeypatch.setattr(delivery, "read", lambda *args: deepcopy(control["value"]))
    monkeypatch.setattr(delivery, "attempt", lambda *args: deepcopy(control["binding"]))
    monkeypatch.setattr(delivery, "document", lambda *args: deepcopy(control["request"]))
    monkeypatch.setattr(delivery, "raw", lambda *args: control["body"])
    return SimpleNamespace(
        authority=authority,
        prepared=prepared,
        value=value,
        binding=binding,
        request=request,
        body=body,
        previous=previous,
        current=current,
        targets=targets,
        control=control,
    )


def successor(case):
    return delivery.attempt_successor(
        case.authority, None, case.value, case.prepared, case.binding, case.request, case.body
    )


def current(case, proof):
    return proof.current(case.authority, None, case.control["state"], case.control["version"])


def test_exact_original_barrier_keeps_original_lifetime_and_is_single_use(barrier):
    proof = successor(barrier)
    assert proof._valid_until == barrier.prepared.valid_until
    assert proof._footprint == barrier.prepared.footprint
    assert current(barrier, proof) is barrier.prepared.claim
    with pytest.raises(CommandError) as held:
        current(barrier, proof)
    assert held.value.code == "delivery_attempt_context_consumed"


@pytest.mark.parametrize(
    "fault",
    [
        "state",
        "version",
        "source",
        "baseline",
        "expired",
        "request",
        "body",
        "binding",
        "response",
        "other_unknown",
        "lease",
        "policy",
        "configuration",
        "claim",
    ],
)
def test_changed_own_attempt_fence_never_authorizes_first_send(barrier, fault):
    proof = successor(barrier)
    c = barrier.control
    if fault == "state":
        c["state"]["new_revision"] = True
    elif fault == "version":
        c["version"] += 1
    elif fault == "source":
        c["source"] = "f" * 64
    elif fault == "baseline":
        c["baseline"] = ("changed",)
    elif fault == "expired":
        c["clock"] = barrier.prepared.valid_until + 0.01
    elif fault == "request":
        c["request"]["content_type"] = "changed"
    elif fault == "body":
        c["body"] = b"x" * len(barrier.body)
    elif fault == "binding":
        c["binding"]["stage"] = "alt"
    elif fault == "response":
        c["current"]["rows"]["observations"].append(
            ["response", barrier.binding["attempt_id"], "metadata", "raw"]
        )
    elif fault == "other_unknown":
        c["current"]["rows"]["attempts"].append(
            ["other", "other-work", "create", 1, "binding", "request"]
        )
    elif fault == "lease":
        c["current"]["rows"]["leases"][0][2] += 1
    elif fault == "policy":
        proof._base["policy_sha256"] = "f" * 64
    elif fault == "configuration":
        proof._base["configuration"] = dict(contract="changed")
    elif fault == "claim":
        proof.claim.reference["selection"]["signal_field"] = "all_time_low"
    with pytest.raises(CommandError):
        current(barrier, proof)
    # A failed validation never renews or rearms the original first-send proof.
    with pytest.raises(CommandError) as held:
        current(barrier, proof)
    assert held.value.code == "delivery_attempt_context_consumed"


@pytest.mark.parametrize(
    "fault",
    [
        "other_attempt",
        "response",
        "version",
        "request",
        "expired",
        "new_authority",
        "protected_predecessor",
        "wrong_grant",
        "wrong_stage",
        "prior_dispatch",
    ],
)
def test_only_exact_begin_delta_can_issue_an_attempt_context(barrier, fault):
    if fault == "other_attempt":
        barrier.control["current"]["rows"]["attempts"].append(
            ["other", "work", "upload", 1, "binding", "request"]
        )
    elif fault == "response":
        barrier.control["current"]["rows"]["observations"].append(
            ["observation", barrier.binding["attempt_id"], "metadata", "raw"]
        )
    elif fault == "version":
        barrier.control["version"] += 1
    elif fault == "request":
        barrier.request["byte_count"] += 1
    elif fault == "expired":
        barrier.control["clock"] = barrier.prepared.valid_until + 0.01
    elif fault == "new_authority":
        barrier.prepared = ghcn.replace(barrier.prepared, authority=object())
    elif fault == "wrong_grant":
        barrier.binding["owner"] = "other-worker"
    elif fault == "wrong_stage":
        barrier.binding["stage"] = "create"
    elif fault == "prior_dispatch":
        barrier.control["current"]["outcomes"]["intent"]["x"]["upload"] = dict(
            status="confirmed", result={"media_id": "1"}
        )
    else:
        barrier.prepared.checkpoint["delivery"]["protection_codes"] = [
            dict(code="delivery_prior_outcome_unknown")
        ]
    with pytest.raises(CommandError):
        successor(barrier)


def test_restarted_authority_and_different_attempt_cannot_use_original_context(barrier):
    proof = successor(barrier)
    assert not proof.matches(barrier.value, dict(barrier.binding, stage="alt"))
    with pytest.raises(CommandError):
        proof.current(object(), None, barrier.control["state"], barrier.control["version"])


def test_revoked_role_precedes_scientific_or_attempt_context_work(barrier):
    proof = successor(barrier)
    reads = barrier.control["reads"]
    with pytest.raises(CommandError):
        delivery.context(
            barrier.authority, None, barrier.value, lambda subject: None, None, ghcn=proof
        )
    assert barrier.control["reads"] == reads
    assert not proof._use.locked()
