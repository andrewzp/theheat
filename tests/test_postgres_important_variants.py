"""Actual local PostgreSQL/SDK two-angle generation and independent check lineage."""

from copy import deepcopy
from datetime import timedelta
import json
from uuid import uuid4

import pytest

from src.commands import postgres_important_variants as group
from src.commands import postgres_sourced_generation as generation
from src.commands.schema import Command, CommandError, canonical_json, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, review_is_current
from src.storage import postgres_projection as p
from src.two_bot import check_requests
from src.two_bot.sourced_generation import identity as source_identity
from src.two_bot.batch_transport import AnthropicBatchTransport
from src.two_bot.provider_http import anthropic_httpx
from tests import test_postgres_sourced_generation as sourced_tests
from tests import test_postgres_candidate_admission as candidate
from tests import test_check_executor as executor, test_batch_worker_journal as worker
from tests.two_bot import test_batch_contract as batch_tests
from tests.test_postgres_sourced_generation import sourced as sourced
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs

NOW = sourced_tests.NOW
AT = candidate.AT


@pytest.fixture
def important(sourced, monkeypatch):
    case = sourced
    # Invented retained source adds the explicit MW unit to its existing
    # classifier threshold, preserving every mandatory scientific source fact.
    value = deepcopy(case["value"])
    threshold = next(
        f for f in value["bundle"]["current_facts"] if f["label"] == "frp_tier_floor_mw"
    )
    fact = dict(label="retained_frp_tier_floor", value=threshold["value"], unit="MW")
    value["bundle"]["current_facts"].append(fact)
    refs = case["store"].retain_generation_input(value)
    case["config"]["current_inputs"] = [refs["brief_id"]]
    case["config"]["reservation"] = case["store"].retain_generation_reservation(
        sourced_tests.allowance_document(refs["brief_id"])
    )
    policy = current_editorial_policy()
    bundle, memory, context, _ = source_identity(
        value, case["store"].read()[1], policy, now=NOW, epoch=candidate.admission.PAUSED_EPOCH
    )
    allowance = dict(
        schema_version=1,
        kind="important_event_two_angles_v1",
        basis="invented_local_allowance",
        **refs,
        context=context,
        authorized_subject=candidate.EDITOR.subject,
        authentication_context=candidate.EDITOR.authentication_context,
        importance_reason="Invented nominated event",
        valid_from=utc_text(NOW),
        valid_until=value["useful_until"],
        angles=[
            dict(slot=1, kind="headline_first", fact_sha256=fingerprint(bundle.headline_metric)),
            dict(
                slot=2,
                kind="context_first",
                index=bundle.current_facts.index(fact),
                fact_sha256=fingerprint(fact),
            ),
        ],
        preferred_slot=1,
        max_writer_items=2,
        max_submit_attempts=1,
        max_collection_cycles=4,
        max_candidate_provider_checks=6,
        max_rewrites=0,
        writer_reservation=dict(
            estimate_sha256="e" * 64,
            reserve_micro_usd=20,
            provider="anthropic",
            model=policy["models"]["writer"],
            role="writer",
        ),
        check_reservations={
            stage: dict(
                estimate_sha256="e" * 64,
                reserve_micro_usd=5,
                provider="google",
                model=policy["models"][stage],
                role=stage,
            )
            for stage in ("safety", "fact_check", "critic")
        },
        max_group_commitment_micro_usd=50,
    )
    allow = case["store"].retain_important_allowance(allowance)
    case["store"].configure_important_variants(lambda: dict(allowance_id=allow["allowance_id"]))
    case.update(refs=refs, value=value, allowance=allowance, allowance_refs=allow, bundle=bundle)
    return case


def command(case, action, payload, *, at=NOW, principal=candidate.EDITOR):
    return Command.from_request(
        dict(
            command_id=str(uuid4()),
            action=action,
            targets=[],
            requested_at=utc_text(at),
            expires_at=utc_text(at + timedelta(hours=1)),
            payload=payload,
        ),
        principal,
        environment="local",
        now=at,
    )


def consume(case, cmd, *, at=NOW, resolver=candidate.resolve):
    case["store"].accept(cmd, resolver(cmd.actor_subject), now=at)
    return case["store"].consume(resolver, command_id=cmd.command_id, now=at)


def start(case):
    payload = dict(
        case["refs"],
        **case["allowance_refs"],
        expected_state_version=case["store"].read()[0],
        expected_policy_sha256=fingerprint(current_editorial_policy()),
    )
    cmd = command(case, "request_important_variants", payload)
    result = consume(case, cmd)
    assert result["status"] == "applied", result
    case.update(request=cmd, result=result)
    return result


def transport(case, *, duplicate_text=False, fail_post=False, missing_second=False, at=NOW):
    httpx = anthropic_httpx()
    sent = []

    def handle(request):
        sent.append((request.method, request.url.path, request.content))
        raw = case["store"].read_batch_plan(case["result"]["generation"]["job_id"])
        plan = json.loads(raw)
        ack = json.loads(worker.ack("msgbatch_important", created_at=utc_text(at)))
        if request.method == "POST":
            assert json.loads(request.content) == dict(requests=plan["requests"])
            if fail_post:
                raise httpx.ReadTimeout("invented lost acknowledgment")
            ack["request_counts"].update(processing=2)
            return httpx.Response(200, json=ack)
        if request.url.path.endswith("/results"):
            rows = [batch_tests.result(raw, i) for i in range(1 if missing_second else 2)]
            for i, row in enumerate(rows):
                output = json.loads(row["result"]["message"]["content"][0]["text"])
                output["tweet"] = case.get(
                    "texts",
                    [executor.TEXT, "In Mali, a satellite detected a 361 MW thermal signal."],
                )[0 if duplicate_text else i]
                row["result"]["message"]["id"] = "msg_important_" + str(i)
                row["result"]["message"]["content"][0]["text"] = json.dumps(output)
            return httpx.Response(200, content=batch_tests.raw_rows(rows))
        ack.update(
            processing_status="ended",
            ended_at=utc_text(at),
            request_counts=dict(processing=0, succeeded=2, errored=0, canceled=0, expired=0),
        )
        return httpx.Response(200, json=ack)

    return sent, lambda: AnthropicBatchTransport(
        api_key="invented-offline-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )


def capture(case, **kwargs):
    start(case)
    sent, factory = transport(case, **kwargs)
    assert sourced_tests.run(case, "submit", factory)["outcome"] == "submitted"
    assert sourced_tests.run(case, "collect", factory)["outcome"] == "reviewed"
    captured = sourced_tests.run(case, "capture")
    assert captured["outcome"] == "candidate_ready", captured
    case["captured"] = captured["candidate"]
    return sent, factory


def enroll(case, slot):
    member = case["captured"]["slots"][slot - 1]["candidate"]
    checked = dict(store=case["store"], refs=member, slot=slot, allowance=case["allowance"])
    candidate.request(checked)
    return checked


def run_stage(checked, stage, *, resolver=candidate.resolve, at=AT):
    store = checked["store"]
    packet = store.check_execution(
        "read", dict(check_set_id=checked["check_set_id"]), now=utc_text(at)
    )["packet"]
    raw = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    reserve = (
        None
        if stage == "deterministic"
        else dict(
            checked["allowance"]["check_reservations"][stage],
            intent_id="ic_"
            + fingerprint(dict(job_id=packet["job_id"], slot=checked["slot"], stage=stage)),
            job_id=packet["job_id"],
            request_sha256=p._sha(raw),
        )
    )
    return store.execute_candidate_check_once(
        checked["request"].command_id,
        resolver,
        clock=lambda: utc_text(at),
        reservation=reserve,
        enabled=True,
    )


def complete(checked, monkeypatch, *, failure=None):
    packet = checked["store"].check_execution(
        "read", dict(check_set_id=checked["check_set_id"]), now=utc_text(AT)
    )["packet"]
    fact_pass = json.dumps(
        dict(
            passed=True,
            extracted_claims=[dict(text=packet["derivation"]["final_text"], kind="comparison")],
            failures=[],
        )
    )
    responses = {
        "safety": executor.envelope("NO"),
        "fact_check": executor.envelope(fact_pass),
        "critic": executor.envelope(executor.CRITIC_PASS),
    }
    if failure == "safety":
        responses["safety"] = executor.envelope("YES")
    if failure == "fact_check":
        responses["fact_check"] = executor.envelope(
            json.dumps(
                dict(passed=False, extracted_claims=[], failures=["Invented failing candidate"])
            )
        )
    if failure == "critic":
        responses["critic"] = executor.envelope(
            json.dumps(
                dict(
                    verdict="KILL",
                    kill_reason="Invented failing candidate",
                    revise_instruction=None,
                    selected_index=None,
                )
            )
        )
    stages = ["safety", "fact_check", "critic"]
    use = stages[: stages.index(failure) + 1] if failure else stages
    sent, _ = executor.provider(monkeypatch, [responses[s] for s in use])
    for stage in ["deterministic", *use]:
        result = run_stage(checked, stage)
        assert result["outcome"] == "completed", result
        assert result["checks"]["stages"][stage] == (
            "rejected" if stage == failure else "passed"
        ), (stage, result)
    assert len(sent) == len(use)
    return sent


def slate_command(case, *, at=AT):
    with case["store"].projections._connection() as c:
        version, state = case["store"]._state(c, lock=True)
        snapshot, _ = group.completion_snapshot(
            case["store"],
            c,
            case["result"]["generation"]["job_id"],
            state,
            version,
            current_editorial_policy(),
            at,
            candidate.resolve,
        )
    return command(
        case,
        "admit_checked_slate",
        dict(
            slate_id=snapshot["job_id"],
            slate_sha256=snapshot["slate_sha256"],
            expected_state_version=version,
            expected_policy_sha256=fingerprint(current_editorial_policy()),
            expected_completion_set_sha256=fingerprint(snapshot),
        ),
        at=at,
    )


def test_two_real_results_are_independently_checked_and_retained(important, monkeypatch, core):
    case = important
    sent, _ = capture(case)
    first, second = enroll(case, 1), enroll(case, 2)
    calls = complete(first, monkeypatch) + complete(second, monkeypatch)
    assert len(calls) == 6 and len(sent) == 3
    before = case["store"].read()
    result = consume(case, slate_command(case), at=AT)
    assert result["status"] == "applied", result
    draft = case["store"].read()[1]["drafts"][-1]
    assert len(draft["candidates"]) == 2 and [c["rank"] for c in draft["candidates"]] == [1, 2]
    assert draft["text"] == executor.TEXT and review_is_current(
        draft, policy=current_editorial_policy()
    )
    assert all(
        c["score"] is None and c["source"] == "retained_important_writer"
        for c in draft["candidates"]
    )
    assert (
        draft["candidates"][0]["provenance"]["candidate_id"]
        != draft["candidates"][1]["provenance"]["candidate_id"]
    )
    assert case["store"].read()[0] == before[0] + 1
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(7,)]
    from src.commands.postgres_revision_checks import source

    with case["store"].projections._connection() as c:
        ref, origin, captured = source(c, draft)
    assert origin["schema_version"] == 3 and origin["origin_kind"] == group.ORIGIN
    assert captured["custom_id"] == case["captured"]["slots"][0]["custom_id"]
    assert case["store"].result(case["request"].command_id) == case["result"]


@pytest.mark.parametrize("failure", ["safety", "fact_check", "critic"])
def test_failed_preferred_does_not_discard_valid_alternative(important, monkeypatch, failure):
    case = important
    capture(case)
    first, second = enroll(case, 1), enroll(case, 2)
    complete(first, monkeypatch, failure=failure)
    complete(second, monkeypatch)
    before = case["store"].spending("status", {}, now=utc_text(AT))
    result = consume(case, slate_command(case), at=AT)
    assert result["status"] == "applied", result
    draft = case["store"].read()[1]["drafts"][-1]
    assert [c["rank"] for c in draft["candidates"]] == [2]
    assert result["candidate"]["selected_slot"] == 2
    assert case["store"].spending("status", {}, now=utc_text(AT)) == before
    assert case["store"].read()[1].get("negative_cache", {}) == {}


def test_duplicate_output_is_not_faked_as_two_angles(important, monkeypatch, core):
    case = important
    capture(case, duplicate_text=True)
    complete(enroll(case, 1), monkeypatch)
    complete(enroll(case, 2), monkeypatch)
    result = consume(case, slate_command(case), at=AT)
    assert result["status"] == "applied", result
    assert [c["rank"] for c in case["store"].read()[1]["drafts"][-1]["candidates"]] == [1]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(7,)]


def test_missing_unit_fact_refuses_before_reservation(important, core):
    case = important
    allowance = deepcopy(case["allowance"])
    facts = case["value"]["bundle"]["current_facts"]
    index = next(i for i, f in enumerate(facts) if f["label"] == "lat")
    assert "unit" not in facts[index]
    allowance["angles"][1].update(index=index, fact_sha256=fingerprint(facts[index]))
    refs = case["store"].retain_important_allowance(allowance)
    case["store"].configure_important_variants(lambda: dict(allowance_id=refs["allowance_id"]))
    payload = dict(
        case["refs"],
        **refs,
        expected_state_version=case["store"].read()[0],
        expected_policy_sha256=fingerprint(current_editorial_policy()),
    )
    result = consume(case, command(case, "request_important_variants", payload))
    assert result["status"] == "rejected"
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]


def test_important_event_claim_refuses_routine_and_second_group(important, core):
    case = important
    start(case)
    ordinary = sourced_tests.request(case)
    assert (
        ordinary["status"] == "rejected" and ordinary["code"] == "important_event_already_claimed"
    )
    payload = dict(
        case["refs"],
        **case["allowance_refs"],
        expected_state_version=case["store"].read()[0],
        expected_policy_sha256=fingerprint(current_editorial_policy()),
    )
    duplicate = consume(case, command(case, "request_important_variants", payload))
    assert (
        duplicate["status"] == "rejected" and duplicate["code"] == "important_event_already_claimed"
    )
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_ordinary_first_refuses_important_topup(important, core):
    case = important
    assert sourced_tests.request(case)["status"] == "applied"
    payload = dict(
        case["refs"],
        **case["allowance_refs"],
        expected_state_version=case["store"].read()[0],
        expected_policy_sha256=fingerprint(current_editorial_policy()),
    )
    result = consume(case, command(case, "request_important_variants", payload))
    assert result["status"] == "rejected" and result["code"] == "ordinary_event_already_started"
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_common_original_fence_cannot_be_renewed(important, monkeypatch, core):
    case = important
    capture(case)
    first, second = enroll(case, 1), enroll(case, 2)
    with case["store"].projections._connection() as c:
        a = candidate.admission.owner_for(first["request"], c=c)
        b = candidate.admission.owner_for(second["request"], c=c)
    assert a == b and first["check_set_id"] != second["check_set_id"]
    with case["store"].projections._connection() as c:
        lease = group.read(c, group.LEASE, case["result"]["generation"]["job_id"])
    assert lease["owner"] == a
    expired = run_stage(first, "deterministic", at=AT + timedelta(seconds=301))
    assert expired["outcome"] == "reconciliation_required"
    assert (
        expired["reason"] == "check_execution_not_confirmed"
        and expired["dispatch_granted"] is False
    )
    with case["store"].projections._connection() as c:
        assert group.read(c, group.LEASE, case["result"]["generation"]["job_id"]) == lease
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_collection_ceiling_durable_and_local_reuse_free(important, core):
    case = important
    sent, factory = capture(case)
    for _ in range(4):
        assert sourced_tests.run(case, "collect", factory)["outcome"] == "reviewed"
    assert len(sent) == 3
    for _ in range(3):
        result = case["store"].execute_sourced_generation_once(
            case["request"].command_id,
            candidate.resolve,
            operation="collect",
            clock=lambda: utc_text(NOW),
            enabled=True,
            refresh=True,
            transport_factory=factory,
        )
        assert result["outcome"] == "reviewed", result
    assert len(sent) == 9
    denied = case["store"].execute_sourced_generation_once(
        case["request"].command_id,
        candidate.resolve,
        operation="collect",
        clock=lambda: utc_text(NOW),
        enabled=True,
        refresh=True,
        transport_factory=factory,
    )
    assert (
        denied["outcome"] == "blocked"
        and denied["reason"] == "batch_collection_transport_unavailable"
    )
    assert len(sent) == 9
    with case["store"].projections._connection() as c:
        assert all(
            group.exists(c, group.CYCLE, case["result"]["generation"]["job_id"] + ":" + str(n))
            for n in range(1, 5)
        )
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_select_alternate_invalidates_and_original_does_not_restore(important, monkeypatch):
    from tests import test_postgres_editor_media as editor

    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    complete(enroll(case, 2), monkeypatch)
    admission_command = slate_command(case)
    result = consume(case, admission_command, at=AT)
    assert result["status"] == "applied", result
    case["draft_id"] = result["candidate"]["draft_id"]
    original = case["store"].read()[1]["drafts"][-1]
    origin_sha = original["candidates"][0]["provenance"]["candidate_id"]
    for rank in (2, 1):
        draft = case["store"].read()[1]["drafts"][-1]
        selected = next(c for c in draft["candidates"] if c["rank"] == rank)
        _, result = editor.action(
            case,
            "select_candidate",
            dict(candidate_rank=rank, candidate_sha256=fingerprint(selected)),
        )
        assert result["status"] == "applied", result
        draft = case["store"].read()[1]["drafts"][-1]
        assert draft["text"] == selected["text"] and not review_is_current(
            draft, policy=current_editorial_policy()
        )
        assert (
            "approval_binding" not in draft
            and draft["candidates"][0]["provenance"]["candidate_id"] == origin_sha
        )
    assert (
        case["store"].consume(candidate.resolve, command_id=admission_command.command_id, now=AT)[
            "status"
        ]
        == "applied"
    )
    assert not review_is_current(
        case["store"].read()[1]["drafts"][-1], policy=current_editorial_policy()
    )


def test_unknown_preferred_keeps_hold_and_valid_sibling(important, monkeypatch, core):
    from src.commands import postgres_check_observations as observations

    case = important
    capture(case)
    first, second = enroll(case, 1), enroll(case, 2)
    assert run_stage(first, "deterministic")["checks"]["stages"]["deterministic"] == "passed"
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    original = observations.apply
    delayed = []

    def lost_observation(c, action, *args, **kwargs):
        if action == "observe":
            delayed.append((args, kwargs))
            raise RuntimeError("Invented lost observation before commit")
        return original(c, action, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(observations, "apply", lost_observation)
        result = run_stage(first, "safety")
    assert result["outcome"] == "reconciliation_required" and len(sent) == 1
    job = case["result"]["generation"]["job_id"]
    unknown_id = "ic_" + fingerprint(dict(job_id=job, slot=1, stage="safety"))
    held = case["store"].spending("status", dict(intent_id=unknown_id), now=utc_text(AT))
    assert held["intent"]["state"] == "dispatched" and held["intent"]["settled_micro_usd"] is None
    complete(second, monkeypatch)
    all_before_admission = case["store"].spending("status", {}, now=utc_text(AT))
    result = consume(case, slate_command(case), at=AT)
    assert result["status"] == "applied", result
    assert case["store"].spending("status", {}, now=utc_text(AT)) == all_before_admission
    assert [r["rank"] for r in case["store"].read()[1]["drafts"][-1]["candidates"]] == [2]
    assert (
        case["store"].spending("status", dict(intent_id=unknown_id), now=utc_text(AT))["intent"]
        == held["intent"]
    )
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(5,)]
    sealed_state = case["store"].read()
    assert len(delayed) == 1
    arguments, keywords = delayed[0]
    case["store"].check_execution("observe", arguments[0], raw=keywords["raw"], now=keywords["now"])
    assert case["store"].read() == sealed_state
    assert (
        case["store"].spending("status", dict(intent_id=unknown_id), now=utc_text(AT))["intent"]
        == held["intent"]
    )
    with pytest.raises(CommandError):
        run_stage(first, "safety")


def test_missing_identified_member_does_not_block_survivor(important, monkeypatch):
    case = important
    capture(case, missing_second=True)
    assert case["captured"]["slots"][1]["candidate"] is None
    complete(enroll(case, 1), monkeypatch)
    result = consume(case, slate_command(case), at=AT)
    assert result["status"] == "applied", result
    assert len(case["store"].read()[1]["drafts"][-1]["candidates"]) == 1


@pytest.mark.parametrize(
    "fault_namespace", [group.ADMISSION, "draft-source-origin-v1", "command-core-v1"]
)
def test_slate_atomic_membership_source_and_state(important, monkeypatch, core, fault_namespace):
    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    complete(enroll(case, 2), monkeypatch)
    cmd = slate_command(case)
    case["store"].accept(cmd, candidate.EDITOR, now=AT)
    before = case["store"].read()
    original = p.PostgresProjectionRepository._record

    def fail(c, namespace, *args, **kwargs):
        if namespace == fault_namespace:
            raise RuntimeError("Invented transaction failure")
        return original(c, namespace, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(p.PostgresProjectionRepository, "_record", staticmethod(fail))
        with pytest.raises(RuntimeError):
            case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=AT)
    assert case["store"].read() == before and case["store"].result(cmd.command_id) is None
    with case["store"].projections._connection() as c:
        assert not group.exists(c, group.ADMISSION, case["result"]["generation"]["job_id"])
    result = case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=AT)
    assert result["status"] == "applied", result
    assert len(case["store"].read()[1]["drafts"]) == len(before[1]["drafts"]) + 1


@pytest.mark.parametrize(
    "change", ["creator_revoked", "checker_revoked", "source_removed", "policy_changed", "viewer"]
)
def test_original_authorities_remain_required(important, monkeypatch, change):
    case = important
    capture(case)
    checked = enroll(case, 1)
    resolver = candidate.resolve
    if change in {"creator_revoked", "checker_revoked"}:

        def resolver(subject):
            return None if subject == candidate.EDITOR.subject else candidate.resolve(subject)

    if change == "viewer":
        from src.commands.schema import Principal

        def resolver(subject):
            return Principal(subject, "viewer", candidate.EDITOR.authentication_context)

    if change == "source_removed":
        case["config"]["current_inputs"].clear()
    if change == "policy_changed":
        monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    sent, _ = executor.provider(monkeypatch, [])
    with pytest.raises(CommandError):
        run_stage(checked, "deterministic", resolver=resolver)
    assert sent == []


def nominate_source(case, bundle, source_key, texts, *, now=NOW):
    """Fresh invented nomination; append only an explicit unit-bearing derived fact."""
    value = dict(
        schema_version=1,
        source_key=source_key,
        source_revision="invented-important-qualified",
        captured_at=utc_text(now),
        useful_until=utc_text(now + timedelta(hours=8)),
        urgent=False,
        bundle=bundle.to_dict(),
        save=dict(
            legacy_type=bundle.signal_kind,
            event_id=bundle.event_id,
            score=None,
            city="",
            tweet_date="",
            cooldown_exempt=False,
            review_context=None,
            evaluator_metadata=None,
        ),
    )
    if source_key == "firms":
        original = next(
            f for f in value["bundle"]["current_facts"] if f["label"] == "frp_tier_floor_mw"
        )
        extra = dict(label="retained_frp_tier_floor", value=original["value"], unit="MW")
        value["bundle"]["current_facts"].append(extra)
    else:
        # Exact ordinary PM2.5 source: the important-only request builder derives
        # its typed US AQI unit from this source's complete validated window.
        extra = next(
            f for f in value["bundle"]["current_facts"] if f["label"] == "us_aqi_daily_max"
        )
    refs = case["store"].retain_generation_input(value)
    reserve = case["store"].retain_generation_reservation(
        sourced_tests.allowance_document(refs["brief_id"], now=now)
    )
    case["config"].update(current_inputs=[refs["brief_id"]], reservation=reserve)
    policy = current_editorial_policy()
    retained, memory, context, _ = source_identity(
        value, case["store"].read()[1], policy, now=now, epoch=candidate.admission.PAUSED_EPOCH
    )
    allowance = deepcopy(case["allowance"])
    allowance.update(
        **refs,
        context=context,
        valid_from=utc_text(now),
        valid_until=value["useful_until"],
        angles=[
            dict(slot=1, kind="headline_first", fact_sha256=fingerprint(retained.headline_metric)),
            dict(
                slot=2,
                kind="context_first",
                index=retained.current_facts.index(extra),
                fact_sha256=fingerprint(extra),
            ),
        ],
    )
    for role, reserve in [
        ("writer", allowance["writer_reservation"]),
        *allowance["check_reservations"].items(),
    ]:
        reserve["model"] = policy["models"][role]
    allow = case["store"].retain_important_allowance(allowance)
    case["store"].configure_important_variants(lambda: dict(allowance_id=allow["allowance_id"]))
    case.update(
        refs=refs,
        value=value,
        allowance=allowance,
        allowance_refs=allow,
        bundle=retained,
        texts=texts,
        text=texts[0],
    )
    return case


def test_competing_routine_and_important_start_share_event_claim(important, core):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    case = important
    payload = dict(
        case["refs"],
        expected_state_version=case["store"].read()[0],
        expected_policy_sha256=fingerprint(current_editorial_policy()),
    )
    ordinary = command(case, "request_sourced_generation", payload)
    alternate = command(case, "request_important_variants", dict(payload, **case["allowance_refs"]))
    for cmd in (ordinary, alternate):
        case["store"].accept(cmd, candidate.EDITOR, now=NOW)
    barrier = threading.Barrier(2)

    def worker(cmd):
        barrier.wait(timeout=10)
        return case["store"].consume(candidate.resolve, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (ordinary, alternate)))
    assert sorted(r["status"] for r in results) == ["applied", "rejected"], results
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(1,)]
    for cmd in (ordinary, alternate):
        result = next(row for row in results if row["command_id"] == cmd.command_id)
        assert (
            case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=NOW) == result
        )


def test_expired_final_clock_rolls_back_slate_admission(important, monkeypatch):
    from src.commands import postgres_authority as authority_module

    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    complete(enroll(case, 2), monkeypatch)
    expired = slate_command(case)
    original = candidate.admission.plan_draft_admission
    time = [AT]

    def blocked_validation(*args, **kwargs):
        result = original(*args, **kwargs)
        time[0] = AT + timedelta(seconds=301)
        return result

    before = case["store"].read()
    with monkeypatch.context() as patch:
        patch.setattr(candidate.admission, "plan_draft_admission", blocked_validation)
        patch.setattr(authority_module, "_clock", lambda supplied: time[0])
        result = consume(case, expired, at=AT)
    assert result["status"] == "rejected", result
    assert case["store"].read() == before


def test_competing_slate_admission_leaves_one_atomic_outcome(important, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    before = case["store"].read()
    cmds = (slate_command(case), slate_command(case))
    for cmd in cmds:
        case["store"].accept(cmd, candidate.EDITOR, now=AT)
    barrier = threading.Barrier(2)

    def worker(cmd):
        barrier.wait(timeout=10)
        return case["store"].consume(candidate.resolve, now=AT)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, cmds))
    assert sorted(r["status"] for r in results) == ["applied", "rejected"], results
    assert len(case["store"].read()[1]["drafts"]) == len(before[1]["drafts"]) + 1


def test_stale_completion_snapshot_refuses_new_independent_check_evidence(important, monkeypatch):
    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    command_before_second = slate_command(case)
    complete(enroll(case, 2), monkeypatch)
    before = case["store"].read()
    result = consume(case, command_before_second, at=AT)
    assert result["status"] == "rejected" and result["code"] == "important_completion_conflict"
    assert case["store"].read() == before
    assert consume(case, slate_command(case), at=AT)["status"] == "applied"


def test_default_off_and_urgent_do_not_authorize_an_alternate_hold(important, core):
    case = important
    case["store"].important_variants_configuration = None
    result = start_refused(case)
    assert result["status"] == "rejected" and result["code"] == "important_variants_unavailable"
    value = deepcopy(case["value"])
    value["urgent"] = True
    refs = case["store"].retain_generation_input(value)
    case["config"]["current_inputs"] = [refs["brief_id"]]
    allowance = dict(case["allowance"], **refs)
    allow = case["store"].retain_important_allowance(allowance)
    case["store"].configure_important_variants(lambda: dict(allowance_id=allow["allowance_id"]))
    case.update(refs=refs, allowance_refs=allow)
    result = start_refused(case)
    assert result["status"] == "rejected" and result["code"] == "urgent_input_not_batchable"
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]


def start_refused(case):
    cmd = command(
        case,
        "request_important_variants",
        dict(
            case["refs"],
            **case["allowance_refs"],
            expected_state_version=case["store"].read()[0],
            expected_policy_sha256=fingerprint(current_editorial_policy()),
        ),
    )
    return consume(case, cmd)


def test_legacy_iv_prefix_keeps_single_candidate_owner_and_checks(store, inputs, monkeypatch, core):
    inputs["job_id"] = "iv_" + "c" * 64
    from functools import partial
    from tests.test_batch_result_journal import workers

    with monkeypatch.context() as binding:
        binding.setattr(workers, "acquire", partial(workers.acquire, job=inputs["job_id"]))
        binding.setattr(workers, "adopt", partial(workers.adopt, job=inputs["job_id"]))
        case = candidate.unchecked.__wrapped__(store, inputs, monkeypatch, core)
    candidate.complete(case, monkeypatch)
    with store.projections._connection() as c:
        assert not group.is_group(c, inputs["job_id"], environment=store.environment)
        assert (
            candidate.admission.owner_for(case["request"], c=c)
            == "candidate-" + case["request"].command_id
        )
    result = candidate.consume(case, candidate.command(case, "admit_checked_candidate"))
    assert result["status"] == "applied", result
    assert not store.read()[1]["drafts"][-1].get("candidates")


def test_preview_schema1_iv_prefix_preserves_actual_environment(database, inputs, monkeypatch):
    from dataclasses import replace
    from functools import partial
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options
    from tests.test_spend_journal import LIMITS, call
    from tests.test_batch_result_journal import workers

    params = database[2]
    owner = PostgresCommandAuthority(**options(params, params["user"]), environment="preview")
    runtime = PostgresCommandAuthority(**options(params), environment="preview")
    owner.initialize({"drafts": []}, runtime_role="projection_runtime")
    for method in (
        "initialize_spending",
        "initialize_batches",
        "initialize_batch_workers",
        "initialize_batch_results",
        "initialize_candidate_checks",
        "initialize_check_executions",
    ):
        getattr(owner, method)()
    call(runtime, "configure", LIMITS)
    inputs["job_id"] = "iv_" + "d" * 64
    with monkeypatch.context() as binding:
        binding.setattr(workers, "acquire", partial(workers.acquire, job=inputs["job_id"]))
        binding.setattr(workers, "adopt", partial(workers.adopt, job=inputs["job_id"]))
        case = candidate.unchecked.__wrapped__(
            runtime, inputs, monkeypatch, (runtime, {}, owner, params)
        )
    original_command = candidate.command
    with monkeypatch.context() as binding:
        # This helper normally constructs local commands; the genuine authority
        # and every catalog here were initialized as preview, on local PG only.
        binding.setattr(
            candidate,
            "command",
            lambda *a, **kw: replace(original_command(*a, **kw), environment="preview"),
        )
        candidate.complete(case, monkeypatch)
        with runtime.projections._connection() as c:
            assert not group.is_group(c, inputs["job_id"], environment=runtime.environment)
            assert (
                candidate.admission.owner_for(case["request"], c=c)
                == "candidate-" + case["request"].command_id
            )
        projected = runtime.candidate_projection((case["refs"]["admission_input_id"],), now=AT)
        assert projected[0]["status"] == "checks_completed"
        result = candidate.consume(case, candidate.command(case, "admit_checked_candidate"))
    assert result["status"] == "applied", result
    assert not runtime.read()[1]["drafts"][-1].get("candidates")


@pytest.mark.parametrize("boundary", ["second_validation", "terminal_event"])
def test_final_slate_window_rolls_back_after_late_blocking_work(
    important, monkeypatch, boundary, core
):
    from src.commands import postgres_authority as authority_module
    from tests.test_postgres_editor_media import all_application_rows

    case = important
    capture(case)
    complete(enroll(case, 1), monkeypatch)
    complete(enroll(case, 2), monkeypatch)
    cmd = slate_command(case)
    case["store"].accept(cmd, candidate.EDITOR, now=AT)
    before = all_application_rows(core[3])
    before_state = case["store"].read()
    time = [AT]
    original_snapshot = group.completion_snapshot
    original_event = case["store"]._event
    calls = [0]

    def blocked_snapshot(*args, **kwargs):
        answer = original_snapshot(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:
            time[0] = AT + timedelta(seconds=301)
        return answer

    def blocked_event(*args, **kwargs):
        answer = original_event(*args, **kwargs)
        if args[1] == cmd.command_id and args[2] == "completed":
            time[0] = AT + timedelta(seconds=301)
        return answer

    with monkeypatch.context() as patch:
        patch.setattr(authority_module, "_clock", lambda supplied: time[0])
        if boundary == "second_validation":
            patch.setattr(group, "completion_snapshot", blocked_snapshot)
            result = case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=AT)
            assert (
                result["status"] == "rejected"
                and result["code"] == "important_final_window_changed"
            )
        else:
            patch.setattr(case["store"], "_event", blocked_event)
            with pytest.raises(CommandError) as failure:
                case["store"].consume(candidate.resolve, command_id=cmd.command_id, now=AT)
            assert failure.value.code == "candidate_completion_expired"
            assert case["store"].result(cmd.command_id) is None
    assert case["store"].read() == before_state
    if boundary == "terminal_event":
        assert all_application_rows(core[3]) == before
    with case["store"].projections._connection() as c:
        assert not group.exists(c, group.ADMISSION, case["result"]["generation"]["job_id"])


def test_optional_aqi_absence_refuses_before_any_group_hold(important, core):
    from tests.air_quality_fixtures import observation
    from src.data.air_quality import detect_pm25_hazard
    from src.two_bot.intern.air_quality import build_pm25_hazard_bundle

    original = build_pm25_hazard_bundle(detect_pm25_hazard(observation(pm25=172, us_aqi=None)))
    before = deepcopy(original.to_dict())
    case = nominate_source(important, original, "air_quality", ["Unused", "Unused"])
    assert case["value"]["bundle"] == before
    result = start_refused(case)
    assert result["status"] == "rejected" and result["code"] == "important_aqi_fact_invalid", result
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]
