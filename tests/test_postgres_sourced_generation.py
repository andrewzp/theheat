"""Invented source -> actual SDK batch HTTP -> required checks -> admitted draft."""
from copy import deepcopy
from datetime import timedelta
import json
from uuid import uuid4

import pytest

from src.commands import postgres_sourced_generation as generation
from src.commands.schema import Command, CommandError, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint
from src.two_bot.batch_transport import AnthropicBatchTransport
from src.two_bot.provider_http import anthropic_httpx
from src.two_bot.sourced_generation import SourcedGenerationClient
from src.voice import safety
from tests import test_postgres_candidate_admission as candidate
from tests import test_batch_worker_journal as worker
from tests import test_check_executor as checks
from tests.two_bot import test_batch_contract as contract
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs

NOW = utc_datetime(worker.NOW)


def allowance_document(brief_id, *, now=NOW, **changes):
    policy = current_editorial_policy()
    return dict(dict(schema_version=1, basis="invented_local_allowance", provider="anthropic", role="writer",
        model=policy["models"]["writer"], policy_sha256=fingerprint(policy), brief_ids=[brief_id], reserve_micro_usd=20,
        valid_from=utc_text(now), valid_until=utc_text(now+timedelta(hours=8))), **changes)


@pytest.fixture
def sourced(store, inputs, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "invented-offline-key")
    monkeypatch.setenv("GEMINI_API_KEY", "invented-offline-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "invented-offline-key")
    save = dict(legacy_type="fire", event_id=inputs["bundle"].event_id, score=None,
        city="", tweet_date="", cooldown_exempt=False, review_context=None, evaluator_metadata=None)
    value = dict(schema_version=1, source_key="firms", source_revision="invented-one", captured_at=utc_text(NOW),
        useful_until=utc_text(NOW+timedelta(hours=8)), urgent=False, bundle=inputs["bundle"].to_dict(), save=save)
    refs = store.retain_generation_input(value)
    reserve = store.retain_generation_reservation(allowance_document(refs["brief_id"]))
    config = dict(current_inputs=[refs["brief_id"]], reservation=reserve)
    store.configure_sourced_generation(lambda: config)
    return dict(store=store, refs=refs, value=value, config=config, bundle=inputs["bundle"])


def request(case, *, changes=None, now=NOW):
    store = case["store"]
    body = dict(command_id=str(uuid4()), action="request_sourced_generation", requested_at=utc_text(now),
        expires_at=utc_text(now+timedelta(hours=1)), targets=[], payload=dict(case["refs"],
        expected_state_version=store.read()[0], expected_policy_sha256=fingerprint(current_editorial_policy()), **(changes or {})))
    command = Command.from_request(body, candidate.EDITOR, environment="local", now=now)
    store.accept(command, candidate.EDITOR, now=now)
    case["request"] = command
    result = store.consume(candidate.resolve, command_id=command.command_id, now=now)
    case["result"] = result
    return result


def transport(case, *, fail_post=False, output=None, at=NOW, after=None, provider_id="msgbatch_fixture"):
    httpx = anthropic_httpx()
    sent = []
    def handle(request):
        sent.append((request.method, request.url.path, request.content))
        if after:
            after(request)
        if request.method == "POST":
            if fail_post:
                raise httpx.ReadTimeout("invented lost acknowledgment")
            plan = json.loads(case["store"].read_batch_plan(case["result"]["generation"]["job_id"]))
            assert json.loads(request.content) == {"requests": plan["requests"]}
            return httpx.Response(200, content=worker.ack(provider_id, created_at=utc_text(at)))
        if request.url.path.endswith("/results"):
            raw = case["store"].read_batch_plan(case["result"]["generation"]["job_id"])
            row = contract.result(raw)
            parsed = json.loads(row["result"]["message"]["content"][0]["text"])
            if isinstance(output, dict):
                parsed.update(output)
            else:
                parsed["tweet"] = checks.TEXT if output is None else output
            row["result"]["message"]["content"][0]["text"] = json.dumps(parsed)
            return httpx.Response(200, content=contract.raw_rows([row]))
        ack = json.loads(worker.ack(provider_id, created_at=utc_text(at)))
        ack.update(processing_status="ended", ended_at=utc_text(at), request_counts=dict(processing=0, succeeded=1, errored=0, canceled=0, expired=0))
        return httpx.Response(200, json=ack)
    return sent, lambda: AnthropicBatchTransport(api_key="invented-offline-key", http_client=httpx.Client(transport=httpx.MockTransport(handle)))


def run(case, operation, factory=None, *, at=NOW, resolver=candidate.resolve):
    return case["store"].execute_sourced_generation_once(case["request"].command_id, resolver,
        operation=operation, clock=lambda: utc_text(at), enabled=True, transport_factory=factory)


def test_source_start_actual_batch_required_checks_and_admission(sourced, monkeypatch, core):
    case = sourced
    started = request(case)
    assert started["status"] == "applied", started
    sent, factory = transport(case)
    assert run(case, "submit", factory)["outcome"] == "submitted"
    assert run(case, "collect", factory)["outcome"] == "reviewed"
    usage = case["store"].generation_projection(now=NOW)["briefs"][0]["writer_usage"]
    assert usage["counts"]["input_tokens"] == 17 and usage["counts"]["output_tokens"] == 9
    assert usage["counts"]["cache_creation.ephemeral_1h_input_tokens"] == 50
    assert usage["counts"]["cache_creation_input_tokens"] is None
    assert usage["cost_usd"] is None and usage["cost_status"] == "unreconciled"
    assert run(case, "collect", factory)["outcome"] == "reviewed"
    assert case["store"].generation_projection(now=NOW)["briefs"][0]["writer_usage"] == usage
    captured = run(case, "capture")
    assert captured["outcome"] == "candidate_ready"
    assert [x[:2] for x in sent] == [("POST", "/v1/messages/batches"), ("GET", "/v1/messages/batches/msgbatch_fixture"), ("GET", "/v1/messages/batches/msgbatch_fixture/results")]
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets") == [(0,)]
    assert case["store"].generated_candidate_inputs() == (captured["candidate"]["admission_input_id"],)
    checked = dict(store=case["store"], refs=captured["candidate"])
    candidate.complete(checked, monkeypatch)
    result = candidate.consume(checked, candidate.command(checked, "admit_checked_candidate"))
    assert result["status"] == "applied"
    saved = case["store"].read()[1]["drafts"][-1]
    assert saved["text"] == checks.TEXT and saved["status"] == "pending"
    assert len(saved["review_context"]["two_bot"]["required_checks_binding"]["stages"]) == 4
    assert "approval_binding" not in saved
    assert case["store"].spending("status", {}, now=utc_text(candidate.AT))["accounting_complete"] is False


def test_reserved_batch_is_queued_and_unknown_submission_remains_held(sourced):
    result = request(sourced)
    projection = sourced["store"].generation_projection(now=NOW)["briefs"][0]
    assert projection["job_id"] == result["generation"]["job_id"]
    assert projection["status"] == "queued"
    assert projection["writer_usage"]["usage_status"] == "absent"
    assert projection["writer_usage"]["receipt_id"] is None
    assert all(value is None for value in projection["writer_usage"]["counts"].values())
    intent = result["generation"]["intent_id"]
    assert sourced["store"].spending("status", {"intent_id": intent}, now=utc_text(NOW))["intent"]["state"] == "reserved"

    sent, factory = transport(sourced, fail_post=True)
    assert run(sourced, "submit", factory)["outcome"] == "submission_uncertain"
    assert len(sent) == 1
    assert sourced["store"].generation_projection(now=NOW)["briefs"][0]["status"] == "reconciliation_required"
    assert sourced["store"].spending("status", {"intent_id": intent}, now=utc_text(NOW))["intent"]["state"] == "uncertain"


@pytest.mark.parametrize("urgent", [False, True])
def test_unknown_purchase_survives_current_brief_replacement(sourced, core, urgent):
    assert request(sourced)["status"] == "applied"
    intent = sourced["result"]["generation"]["intent_id"]
    sent, factory = transport(sourced, fail_post=True)
    assert run(sourced, "submit", factory)["outcome"] == "submission_uncertain"
    assert len(sent) == 1
    before = sourced["store"].spending("status", {}, now=utc_text(NOW))

    value = deepcopy(sourced["value"])
    value.update(urgent=urgent, useful_until=utc_text(NOW+timedelta(hours=9)))
    refs = sourced["store"].retain_generation_input(value)
    if urgent:
        core[2].initialize_synchronous_checks(now=NOW)
        reserve = sourced["store"].retain_generation_reservation(allowance_document(refs["brief_id"], schema_version=2,
            execution_mode="synchronous", samples=1, max_attempts=1, read_budget_seconds=180))
        config = dict(schema_version=2, current_inputs=[refs["brief_id"]], reservations=dict(batch=None, synchronous=reserve))
    else:
        reserve = sourced["store"].retain_generation_reservation(allowance_document(refs["brief_id"]))
        config = dict(current_inputs=[refs["brief_id"]], reservation=reserve)
    sourced["store"].configure_sourced_generation(lambda: config)
    replacement = dict(sourced, refs=refs, value=value, config=config)
    projection = sourced["store"].generation_projection(now=NOW)["briefs"][0]
    assert projection["status"] == "blocked" and projection["reason"] == "generation_duplicate_engine_purchase"
    result = request(replacement)
    assert result["status"] == "rejected" and result["code"] == "generation_duplicate_engine_purchase"
    assert sourced["store"].spending("status", {}, now=utc_text(NOW)) == before
    assert sourced["store"].spending("status", {"intent_id": intent}, now=utc_text(NOW))["intent"]["state"] == "uncertain"
    assert admin(core[3], "SELECT count(*) FROM theheat_projection.versions WHERE namespace='sourced-sync-job-v1'") == [(0,)]
    assert len(sent) == 1


def test_manual_automatic_same_job_and_no_second_provider_request(sourced):
    first = request(sourced)
    client = SourcedGenerationClient(sourced["store"], candidate.EDITOR, candidate.resolve, lambda: NOW)
    from src.orchestrator.two_bot_dispatch import _try_two_bot_draft
    result = {}
    assert not _try_two_bot_draft(sourced["bundle"], sourced["store"].read()[1], None,
        legacy_type="fire", event_id=sourced["value"]["save"]["event_id"], review_context=None,
        generation_client=client, result_out=result)
    assert result["job_id"] == first["generation"]["job_id"] and result["generation_status"] == "reused"
    sent, factory = transport(sourced)
    assert run(sourced, "submit", factory)["outcome"] == "submitted"
    assert run(sourced, "submit", factory)["outcome"] == "not_dispatched"
    assert len(sent) == 1


@pytest.mark.parametrize("mode", ["revoked", "removed", "policy", "paused"])
def test_changed_authority_blocks_before_provider(sourced, monkeypatch, mode):
    request(sourced)
    sent, factory = transport(sourced)
    resolver = candidate.resolve
    if mode == "revoked":
        def resolver(_):
            return None
    if mode == "removed":
        sourced["config"]["current_inputs"].clear()
    if mode == "policy":
        monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
    if mode == "paused":
        monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "1")
    with pytest.raises(CommandError):
        run(sourced, "submit", factory, resolver=resolver)
    assert sent == []


def test_unknown_submission_never_reposts_or_releases_hold(sourced):
    request(sourced)
    sent, factory = transport(sourced, fail_post=True)
    assert run(sourced, "submit", factory)["outcome"] == "submission_uncertain"
    assert run(sourced, "submit", factory)["outcome"] == "not_dispatched"
    assert len(sent) == 1
    status = sourced["store"].spending("status", {"intent_id": sourced["result"]["generation"]["intent_id"]}, now=utc_text(NOW))
    assert status["intent"]["state"] == "uncertain" and status["intent"]["settled_micro_usd"] is None


def test_estimate_drift_during_lost_acknowledgment_preserves_unknown_hold(sourced, core):
    request(sourced)
    def change(_):
        sourced["config"]["reservation"]["estimate_sha256"] = "e"*64
    sent, factory = transport(sourced, fail_post=True, after=change)
    assert run(sourced, "submit", factory)["outcome"] == "submission_uncertain"
    with pytest.raises(CommandError) as exc:
        run(sourced, "submit", factory)
    assert exc.value.code == "generation_reservation_missing"
    assert len(sent) == 1
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_work.uncertainties") == [(1,)]
    status = sourced["store"].spending("status", {"intent_id": sourced["result"]["generation"]["intent_id"]}, now=utc_text(NOW))
    assert status["intent"]["state"] == "uncertain" and status["intent"]["settled_micro_usd"] is None


@pytest.mark.parametrize("change", [{"prompt": "Free text"}, {"samples": 3}, {"role": "publisher"}])
def test_reference_only_input(sourced, change):
    with pytest.raises(CommandError):
        request(sourced, changes=change)


def test_superseded_and_urgent_are_not_generation_authority(sourced):
    value = deepcopy(sourced["value"])
    value["urgent"] = True
    refs = sourced["store"].retain_generation_input(value)
    sourced["config"]["current_inputs"] = [refs["brief_id"]]
    assert request(sourced)["code"] == "generation_source_superseded"
    sourced["refs"] = refs
    assert request(sourced)["code"] == "urgent_input_not_batchable"


def test_exhausted_allowance_is_durable_refusal_without_orphan(sourced, core):
    sourced["config"]["reservation"] = sourced["store"].retain_generation_reservation(
        allowance_document(sourced["refs"]["brief_id"], reserve_micro_usd=91))
    result = request(sourced)
    assert result["status"] == "rejected" and result["code"] == "spending_allowance_exhausted"
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"reserve_micro_usd": True}, {"reserve_micro_usd": 0},
    {"reserve_micro_usd": 10**12+1}, {"extra": "not allowed"}, {"basis": "price_estimate"},
    {"provider": "google"}, {"role": "critic"}, {"model": ""}, {"policy_sha256": "A"*64},
    {"brief_ids": []}, {"brief_ids": ["a"*64]*2}, {"brief_ids": [f"{i:064x}" for i in range(17)]},
    {"brief_ids": ["A"*64]}, {"valid_from": "2026-09-29T12:00:00+00:00"},
    {"valid_until": utc_text(NOW)}, {"valid_until": utc_text(NOW-timedelta(seconds=1))},
])
def test_reservation_schema_refuses_ambiguous_or_unbounded_values(changes):
    with pytest.raises(CommandError):
        generation.reservation_document(allowance_document("a"*64, **changes))


@pytest.mark.parametrize("phase", ["prepare", "submit", "collect", "capture"])
@pytest.mark.parametrize("mismatch", ["missing", "amount", "model", "policy", "brief", "future", "expired", "digest"])
def test_retained_allowance_is_required_before_registration_and_active_work(sourced, core, phase, mismatch):
    if phase != "prepare":
        assert request(sourced)["status"] == "applied"
    value = allowance_document(sourced["refs"]["brief_id"])
    if mismatch == "amount":
        value["reserve_micro_usd"] += 1
    if mismatch == "model":
        value["model"] = "claude-other-invented"
    if mismatch == "policy":
        value["policy_sha256"] = "b"*64
    if mismatch == "brief":
        value["brief_ids"] = ["c"*64]
    if mismatch == "future":
        value["valid_from"] = utc_text(NOW+timedelta(seconds=1))
    if mismatch == "expired":
        value["valid_from"] = utc_text(NOW-timedelta(hours=1))
        value["valid_until"] = utc_text(NOW)
    reserve = sourced["store"].retain_generation_reservation(value)
    if mismatch == "amount":
        reserve["reserve_micro_usd"] = 20
    if mismatch in {"missing", "digest"}:
        reserve["estimate_sha256"] = "e"*64
    if mismatch == "digest":
        # Even a stored document with an internally valid repository receipt
        # cannot be referenced under a different caller-selected digest.
        sourced["store"].projections.record(generation.RESERVATION, "e"*64, value)
    sourced["config"]["reservation"] = reserve
    expected = ("generation_reservation_missing" if mismatch == "missing" else
        "generation_reservation_expired" if mismatch in {"future", "expired"} else "generation_reservation_mismatch")
    if phase == "prepare":
        result = request(sourced)
        assert result["status"] == "rejected" and result["code"] == expected
    else:
        with pytest.raises(CommandError) as exc:
            run(sourced, phase, lambda: pytest.fail("refused allowance constructed a provider"))
        assert exc.value.code == expected
    expected_jobs = 0 if phase == "prepare" else 1
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(expected_jobs,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(expected_jobs,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_work.submissions") == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.receipts") == [(0,)]


def test_registration_fault_rolls_back_and_restart_consumes_once(sourced, core, monkeypatch):
    from src.commands.postgres_authority import PostgresCommandAuthority
    from tests.test_postgres_command_authority import options
    original = generation.batch.register
    def fail_after_write(*a, **k):
        original(*a, **k)
        raise RuntimeError("invented crash before commit")
    with monkeypatch.context() as patch:
        patch.setattr(generation.batch, "register", fail_after_write)
        with pytest.raises(RuntimeError, match="invented crash"):
            request(sourced)
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(0,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(0,)]
    pending = sourced["request"].command_id
    reopened = PostgresCommandAuthority(**options(core[3]))
    reopened.configure_sourced_generation(lambda: sourced["config"])
    result = reopened.consume(candidate.resolve, command_id=pending, now=NOW)
    assert result["status"] == "applied"
    assert reopened.consume(candidate.resolve, command_id=pending, now=NOW) == result
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(1,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]


def test_retained_result_survives_interpretation_failure_without_another_read(sourced, monkeypatch, core):
    request(sourced)
    sent, factory = transport(sourced)
    assert run(sourced, "submit", factory)["outcome"] == "submitted"
    with monkeypatch.context() as patch:
        def crash(*a, **k):
            raise RuntimeError("invented interpretation crash")
        patch.setattr(generation.results, "review", crash)
        assert run(sourced, "collect", factory)["outcome"] == "retained"
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.receipts") == [(1,)]
    assert run(sourced, "collect", lambda: pytest.fail("retained result was reread"))["outcome"] == "reviewed"
    assert run(sourced, "capture")["outcome"] == "candidate_ready"
    assert len(sent) == 3


def test_racing_manual_and_automatic_starts_share_one_hold_and_attempt(sourced, monkeypatch, core):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store = sourced["store"]
    gate = Barrier(2)
    original = store.accept
    def accept(*a, **k):
        gate.wait(timeout=10)
        return original(*a, **k)
    manual = dict(sourced)
    def manual_start():
        try:
            request(manual)
        except CommandError as exc:
            assert exc.code == "command_pending"
        return manual["request"].command_id
    def auto_start():
        client = SourcedGenerationClient(store, candidate.EDITOR, candidate.resolve, lambda: NOW)
        return client.submit(sourced["bundle"], score=None, legacy_type="fire",
            event_id=sourced["bundle"].event_id, review_context=None)["command_id"]
    with monkeypatch.context() as patch:
        patch.setattr(store, "accept", accept)
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(manual_start), pool.submit(auto_start)]
            identities = [task.result(timeout=20) for task in tasks]
    store.consume(candidate.resolve, now=NOW)
    store.consume(candidate.resolve, now=NOW)
    results = [store.result(identity) for identity in identities]
    assert all(result["status"] == "applied" for result in results)
    assert len({result["generation"]["job_id"] for result in results}) == 1
    assert admin(core[3], "SELECT count(*) FROM theheat_batches.registrations") == [(1,)]
    assert admin(core[3], "SELECT count(*) FROM theheat_spending.intents") == [(1,)]
    manual["result"] = results[0]
    sent, factory = transport(manual)
    assert run(manual, "submit", factory)["outcome"] == "submitted"
    assert store.execute_sourced_generation_once(identities[1], candidate.resolve, operation="submit",
        clock=lambda: utc_text(NOW), enabled=True, transport_factory=factory)["outcome"] == "blocked"
    assert len(sent) == 1


@pytest.mark.parametrize("phase", ["submit", "collect"])
@pytest.mark.parametrize("drift", ["source", "role", "policy", "lease", "estimate", "estimate_expiry"])
def test_inflight_drift_keeps_raw_evidence_without_promotion(sourced, monkeypatch, core, phase, drift):
    if drift == "estimate_expiry":
        sourced["config"]["reservation"] = sourced["store"].retain_generation_reservation(
            allowance_document(sourced["refs"]["brief_id"], valid_until=utc_text(NOW+timedelta(seconds=1))))
    request(sourced)
    clock = [NOW]
    revoked = [False]
    def resolver(subject):
        return None if revoked[0] else candidate.resolve(subject)
    def change(request):
        if phase == "collect" and not request.url.path.endswith("/results"):
            return
        if drift == "source":
            sourced["config"]["current_inputs"].clear()
        if drift == "role":
            revoked[0] = True
        if drift == "policy":
            monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "3")
        if drift == "lease":
            clock[0] += timedelta(seconds=61)
        if drift == "estimate":
            sourced["config"]["reservation"]["estimate_sha256"] = "e"*64
        if drift == "estimate_expiry":
            clock[0] += timedelta(seconds=1)
    if phase == "collect":
        _, clean = transport(sourced)
        assert run(sourced, "submit", clean)["outcome"] == "submitted"
    sent, factory = transport(sourced, after=change)
    outcome = sourced["store"].execute_sourced_generation_once(sourced["request"].command_id, resolver,
        operation=phase, enabled=True, clock=lambda: utc_text(clock[0]), transport_factory=factory)
    table = "theheat_batch_work.acks" if phase == "submit" else "theheat_batch_results.receipts"
    assert admin(core[3], f"SELECT count(*) FROM {table}") == [(1,)]
    assert outcome["outcome"] == ("acknowledgment_retained" if phase == "submit" else "retained"), outcome
    assert len(sent) == (1 if phase == "submit" else 2)
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets") == [(0,)]
    if drift != "lease":
        with pytest.raises(CommandError):
            run(sourced, "capture", at=clock[0], resolver=resolver)
    assert len(sent) == (1 if phase == "submit" else 2)
    status = sourced["store"].spending("status", {}, now=utc_text(clock[0]))
    assert status["totals"]["held_micro_usd"] == 20 and not status["accounting_complete"]


@pytest.mark.parametrize("drift", ["source", "estimate"])
def test_changed_authority_between_metadata_and_results_retains_only_metadata(sourced, core, drift):
    request(sourced)
    _, factory = transport(sourced)
    assert run(sourced, "submit", factory)["outcome"] == "submitted"
    def change(_):
        if drift == "source":
            sourced["config"]["current_inputs"].clear()
        else:
            sourced["config"]["reservation"]["estimate_sha256"] = "e"*64
    sent, factory = transport(sourced, after=change)
    assert run(sourced, "collect", factory)["outcome"] == "retained"
    assert len(sent) == 1 and sent[0][1].endswith("msgbatch_fixture")
    assert admin(core[3], "SELECT count(*) FROM theheat_batch_results.receipts") == [(1,)]
    assert admin(core[3], "SELECT octet_length(payload) FROM theheat_batch_results.result_artifacts") == [(0,)]


@pytest.mark.parametrize("scope", ["evidence", "style"])
def test_only_two_independent_evidence_kills_arm_cache_and_receipt_replay_is_once(sourced, scope):
    from src.two_bot import negative_cache
    first_fingerprint = None
    for number in range(2):
        at = NOW + timedelta(minutes=2*number)
        value = deepcopy(sourced["value"])
        value["source_revision"] = f"invented-fresh-{number}"
        value["captured_at"] = utc_text(at)
        sourced["refs"] = sourced["store"].retain_generation_input(value)
        sourced["config"]["current_inputs"] = [sourced["refs"]["brief_id"]]
        sourced["config"]["reservation"] = sourced["store"].retain_generation_reservation(
            allowance_document(sourced["refs"]["brief_id"], now=at))
        assert request(sourced, now=at)["status"] == "applied"
        raw = sourced["store"].read_batch_plan(sourced["result"]["generation"]["job_id"])
        if number == 0:
            first_fingerprint = json.loads(raw)["bundle_sha256"]
        assert json.loads(raw)["bundle_sha256"] == first_fingerprint
        _, factory = transport(sourced, at=at, provider_id=f"msgbatch_fresh{number}", output=dict(tweet=None, kill_reason="insufficient evidence",
            kill_scope=scope, kill_code="insufficient_evidence" if scope == "evidence" else None))
        assert run(sourced, "submit", factory, at=at)["outcome"] == "submitted"
        assert run(sourced, "collect", factory, at=at)["outcome"] == "reviewed"
        assert run(sourced, "capture", at=at)["outcome"] == "terminal"
        before = sourced["store"].read()
        assert run(sourced, "capture", at=at)["outcome"] == "terminal"
        assert sourced["store"].read() == before
        cache = before[1].get("writer_negative_cache", {})
        assert (next(iter(cache.values()))["kills"] if cache else 0) == (number+1 if scope == "evidence" else 0)
    assert bool(negative_cache.should_skip(sourced["store"].read()[1], sourced["bundle"].event_id,
        sourced["bundle"], now=at)) is (scope == "evidence")


@pytest.mark.parametrize("phase", ["registered", "captured"])
def test_fresh_owned_cluster_restore_resumes_exact_source_job(sourced, core, cluster, phase):
    import tempfile
    from pathlib import Path
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    initial = request(sourced)
    sent, factory = transport(sourced)
    captured = None
    if phase == "captured":
        run(sourced, "submit", factory)
        run(sourced, "collect", factory)
        captured = run(sourced, "capture")
    before = sourced["store"].read()
    params, (_, tool, _) = core[3], cluster
    with tempfile.TemporaryDirectory(prefix="theheat-generation-restore-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket, data, dump = root/"socket", root/"data", root/"source.dump"
        socket.mkdir(mode=0o700)
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", root/"server.log", "-o", f"-c listen_addresses='' -k {socket} -p 55477", "-w", "start")
            with psycopg.connect(host=str(socket), port=55477, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_generation TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55477", "-U", "projection_owner", "-d", "restored_generation", "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55477, database="restored_generation", user="projection_runtime")
            restored.configure_sourced_generation(lambda: sourced["config"])
            assert restored.read() == before
            digest = sourced["config"]["reservation"]["estimate_sha256"]
            assert restored.projections.read(generation.RESERVATION, digest) == sourced["store"].projections.read(generation.RESERVATION, digest)
            assert restored.consume(candidate.resolve, command_id=sourced["request"].command_id, now=NOW) == initial
            recovery = dict(sourced, store=restored)
            if phase == "registered":
                new_sent, fresh = transport(recovery)
                assert run(recovery, "submit", fresh)["outcome"] == "submitted"
                assert run(recovery, "submit", fresh)["outcome"] == "not_dispatched"
                assert len(new_sent) == 1
            else:
                assert run(recovery, "capture") == captured
                assert restored.generated_candidate_inputs() == (captured["candidate"]["admission_input_id"],)
            assert sourced["store"].read() == before
            assert len(sent) == (3 if phase == "captured" else 0)
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")
