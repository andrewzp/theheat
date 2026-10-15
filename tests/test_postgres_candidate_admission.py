"""Unchecked retained result -> actual required checks -> atomic local draft."""
from copy import deepcopy
import hashlib
import json
from datetime import timedelta
from uuid import uuid4

import pytest

from src.commands import postgres_candidate_admission as admission
from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.editorial.revisions import fingerprint, review_is_current
from src.two_bot import check_requests
from src.voice import safety
from tests import test_batch_result_journal as batches, test_check_executor as executor
from tests.test_postgres_projection import cluster as cluster, database as database, admin
from tests.test_postgres_command_authority import core as core, make_authority as make_authority
from tests.test_postgres_batch import spend_store as spend_store
from tests.test_postgres_batch_results import worker_store as worker_store
from tests.test_postgres_check_observations import base_store as base_store, store as store
from tests.two_bot.test_batch_contract import inputs as inputs
from tests.test_batch_worker_journal import NOW, later

EDITOR = Principal("invented-editor", "editor", "fixture")
PUBLISHER = Principal("invented-publisher", "publisher", "fixture")
AT = utc_datetime(later(301))


def resolve(subject):
    return {EDITOR.subject: EDITOR, PUBLISHER.subject: PUBLISHER}.get(subject)


@pytest.fixture
def unchecked(store, inputs, monkeypatch, core):
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("GEMINI_API_KEY", "offline-fixture-key")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    inputs["policy"] = current_editorial_policy()
    inputs["publication_epoch"] = admission.PAUSED_EPOCH
    pair, grant = batches.started(store, inputs)
    rows = batches.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = executor.TEXT
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = batches.retain(store, grant, batches.contract.raw_rows(rows))
    payload = dict(job_id=pair[1]["job_id"], custom_id=json.loads(pair[0])["requests"][0]["custom_id"],
        receipt_id=receipt["receipt_id"], owner="worker-one", fence=1,
        bundle=inputs["bundle"].to_dict(), memory=inputs["memory"].to_dict(),
        save=dict(legacy_type="fire", event_id=inputs["bundle"].event_id, score=None,
                  city="", tweet_date="", cooldown_exempt=False, review_context=None, evaluator_metadata=None))
    refs = store.capture_candidate_input(payload, now=utc_datetime(NOW))
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets") == [(0,)]
    return dict(store=store, refs=refs, payload=payload)


def command(case, action="request_candidate_checks", *, changes=None, principal=EDITOR):
    payload = dict(case["refs"], **(changes or {}))
    if action == "admit_checked_candidate":
        view = case["store"].candidate_projection((payload["admission_input_id"],), now=AT)[0]
        payload.update(check_set_id=view["check_set_id"], expected_completion_sha256=view["expected_completion_sha256"])
        payload.update(changes or {})
    return Command.from_request(dict(command_id=str(uuid4()), action=action, requested_at=utc_text(AT),
        expires_at=utc_text(AT + timedelta(hours=1)), targets=[], payload=payload), principal, environment="local", now=AT)


def consume(case, cmd, principal=EDITOR):
    case["store"].accept(cmd, principal, now=AT)
    return case["store"].consume(resolve, command_id=cmd.command_id, now=AT)


def request(case):
    cmd = command(case)
    result = consume(case, cmd)
    assert result["status"] == "unchanged", result
    assert result["candidate"]["outcome"] == "checks_requested"
    case["request"] = cmd
    case["check_set_id"] = result["candidate"]["check_set_id"]
    return result


def run_stage(case, stage, *, resolver=resolve):
    store = case["store"]
    packet = store.check_execution("read", {"check_set_id": case["check_set_id"]}, now=utc_text(AT))["packet"]
    encoded = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    reservation = None if stage == "deterministic" else dict(intent_id="admission-"+case["check_set_id"][:12]+"-"+stage, job_id=packet["job_id"],
        request_sha256=hashlib.sha256(encoded).hexdigest(), provider="google", role=stage,
        model=packet["policy"]["models"][stage], estimate_sha256="e"*64, reserve_micro_usd=5)
    return store.execute_candidate_check_once(case["request"].command_id, resolver,
        clock=lambda: utc_text(AT), reservation=reservation, enabled=True)


def complete(case, monkeypatch):
    request(case)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO"), executor.envelope(executor.FACT_PASS), executor.envelope(executor.CRITIC_PASS)])
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        result = run_stage(case, stage)
        assert result["outcome"] == "completed", result
        assert result["checks"]["stages"][stage] == "passed", result
    assert len(sent) == 3
    return sent


def test_unchecked_to_required_checks_to_saved_draft_without_approval(unchecked, core, monkeypatch):
    case = unchecked
    before = case["store"].read()
    initial = case["store"].candidate_projection((case["refs"]["admission_input_id"],), now=AT)[0]
    assert initial["status"] == "not_checked"
    sent = complete(case, monkeypatch)
    assert case["store"].read() == before
    money = case["store"].spending("status", {}, now=utc_text(AT))
    cmd = command(case, "admit_checked_candidate")
    result = consume(case, cmd)
    assert result["status"] == "applied", result
    assert result["state_version"] == before[0] + 1
    saved = case["store"].read()[1]["drafts"][-1]
    assert saved["text"] == executor.TEXT and saved["status"] == "pending"
    assert review_is_current(saved)
    assert not any(k in saved for k in ("approval_binding", "publish_intent_id", "auto_approve_at", "tweet_id"))
    assert saved["review_context"]["two_bot"]["required_checks_binding"]["check_set_id"] == case["check_set_id"]
    assert case["store"].consume(resolve, command_id=cmd.command_id, now=AT) == result
    assert consume(case, command(case, "admit_checked_candidate", changes=cmd.payload))["candidate"]["outcome"] == "already_admitted"
    assert case["store"].spending("status", {}, now=utc_text(AT)) == money
    assert len(sent) == 3


@pytest.mark.parametrize("field,value", [("text", "Invented bypass."), ("passed", True), ("owner", "browser"), ("cost_usd", 0)])
def test_browser_cannot_supply_content_verdict_owner_or_cost(unchecked, field, value):
    with pytest.raises(CommandError, match="Payload fields"):
        command(unchecked, changes={field: value})


def test_no_current_capability_cannot_request_checks(unchecked, monkeypatch):
    monkeypatch.setattr(safety, "GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEY")
    result = consume(unchecked, command(unchecked))
    assert result["status"] == "rejected" and result["code"] == "candidate_policy_conflict"


def test_revoked_actor_cannot_run_stage(unchecked, monkeypatch):
    request(unchecked)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    with pytest.raises(CommandError, match="unavailable"):
        run_stage(unchecked, "deterministic", resolver=lambda _: None)
    assert sent == []


def test_source_input_hash_cannot_be_normalized_or_rebound(unchecked):
    cmd = command(unchecked, changes={"admission_input_sha256": "f"*64})
    assert consume(unchecked, cmd)["code"] == "candidate_input_mismatch"


def test_check_proof_deletion_or_transplant_revokes_model_review(unchecked, monkeypatch):
    complete(unchecked, monkeypatch)
    result = consume(unchecked, command(unchecked, "admit_checked_candidate"))
    assert result["status"] == "applied", result
    original = unchecked["store"].read()[1]["drafts"][-1]
    changed = deepcopy(original)
    del changed["review_context"]["two_bot"]["required_checks_binding"]
    assert not review_is_current(changed)
    for stage in ("deterministic", "safety", "fact_check", "critic"):
        changed = deepcopy(original)
        changed["review_context"]["two_bot"]["required_checks_binding"]["stages"][stage]["grant_id"] = "f"*64
        assert not review_is_current(changed)


@pytest.mark.parametrize("damage", ["missing_observation", "forged_pass", "wrong_request", "wrong_usage"])
def test_complete_receipts_without_exact_interpreted_evidence_cannot_admit(unchecked, monkeypatch, damage):
    case = unchecked
    request(case)
    if damage != "missing_observation":
        assert run_stage(case, "deterministic")["outcome"] == "completed"
    stage = "deterministic" if damage == "missing_observation" else "safety"
    store = case["store"]
    packet = store.check_execution("read", {"check_set_id": case["check_set_id"]}, now=utc_text(AT))["packet"]
    owner = admission.owner_for(case["request"])
    lease = store.batch_work("status", {"job_id": packet["job_id"]}, now=utc_text(AT))["lease"]
    identity = dict(check_set_id=case["check_set_id"], owner=owner, fence=lease["fence"],
        current_context=packet["current_context"], checker_state_sha256=packet["checker_state_sha256"])
    raw_request = canonical_json(check_requests.prepare_request(packet, stage)).encode()
    if damage == "wrong_request":
        raw_request = b'{"unrelated":"invented request"}'
    sha = hashlib.sha256(raw_request).hexdigest()
    reservation = None if stage == "deterministic" else dict(intent_id="forged-safety", job_id=packet["job_id"], request_sha256=sha,
        provider="google", role=stage, model=packet["policy"]["models"][stage], estimate_sha256="e"*64, reserve_micro_usd=5)
    grant = store.candidate_checks("begin", dict(identity, stage=stage, reservation=reservation), now=utc_text(AT), request=raw_request)
    raw = canonical_json(check_requests.deterministic_result(packet)).encode() if stage == "deterministic" else executor.envelope("YES" if damage == "forged_pass" else "NO")
    observation = dict(check_set_id=case["check_set_id"], stage=stage, grant_id=grant["grant_id"], request_sha256=sha,
        raw_sha256=hashlib.sha256(raw).hexdigest(), complete=True, http_status=None if stage == "deterministic" else 200, reason="local" if stage == "deterministic" else "received")
    if damage != "missing_observation":
        store.check_execution("observe", observation, raw=raw, now=utc_text(AT))
    outcome = check_requests.interpret_observation(packet, stage, observation, raw)
    if damage == "forged_pass":
        outcome.update(verdict="pass", result={"passed": True})
    if damage == "wrong_usage":
        outcome["usage"]["promptTokenCount"] += 1
    store.candidate_checks("complete", dict(identity, stage=stage, grant_id=grant["grant_id"]), now=utc_text(AT),
        receipt=dict(outcome, grant_id=grant["grant_id"], request_sha256=sha))
    replies = [executor.envelope("NO"), executor.envelope(executor.FACT_PASS), executor.envelope(executor.CRITIC_PASS)] if stage == "deterministic" else [executor.envelope(executor.FACT_PASS), executor.envelope(executor.CRITIC_PASS)]
    executor.provider(monkeypatch, replies)
    for next_stage in (["safety", "fact_check", "critic"] if stage == "deterministic" else ["fact_check", "critic"]):
        assert run_stage(case, next_stage)["outcome"] == "completed"
    # Projection refuses readiness even though every old terminal says passed.
    projected = store.candidate_projection((case["refs"]["admission_input_id"],), now=AT)[0]
    assert projected["status"] == "checks_blocked" and not projected["required_checks_completed"]
    before = store.read()
    bad = command(case, "admit_checked_candidate", changes={"check_set_id": case["check_set_id"], "expected_completion_sha256": "f"*64})
    result = consume(case, bad)
    assert result["status"] == "rejected" and result["code"] in {"check_response_not_retained", "check_request_not_exact", "check_receipt_not_exact"}
    assert store.read() == before


def test_generic_python_and_javascript_review_cannot_mint_well_shaped_proof(unchecked, monkeypatch):
    from src.editorial.revisions import record_model_review
    complete(unchecked, monkeypatch)
    consume(unchecked, command(unchecked, "admit_checked_candidate"))
    draft = unchecked["store"].read()[1]["drafts"][-1]
    forged = deepcopy(draft)
    forged.pop("review_binding")
    record_model_review(forged)
    assert "review_binding" not in forged and not review_is_current(forged)
    import subprocess
    script = """import {recordModelReview,reviewIsCurrent} from './lib/draft-revisions.js';
      let raw='';for await(const c of process.stdin)raw+=c;const {draft,policy}=JSON.parse(raw);
      const before=reviewIsCurrent(draft,policy);delete draft.review_binding;recordModelReview(draft,policy);
      console.log(JSON.stringify({before,after:reviewIsCurrent(draft,policy),bound:!!draft.review_binding}));"""
    from pathlib import Path
    output = subprocess.run(["node", "--input-type=module", "-e", script], cwd=Path(__file__).resolve().parents[1]/"dashboard",
        input=json.dumps({"draft": draft, "policy": current_editorial_policy()}), text=True, capture_output=True, timeout=15, check=True)
    assert json.loads(output.stdout) == dict(before=True, after=False, bound=False)


def test_rejected_preflight_rolls_back_new_lease_and_does_not_pop_draft(unchecked, core, monkeypatch):
    from src.editorial.draft_admission import AdmissionPlan
    monkeypatch.setattr(admission, "plan_draft_admission", lambda state, **kw: AdmissionPlan(deepcopy(state), None, "city_cooldown", ()))
    before = admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence"), unchecked["store"].read()
    result = consume(unchecked, command(unchecked))
    assert result["code"] == "city_cooldown"
    assert before == (admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence"), unchecked["store"].read())
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.sets") == [(0,)]


def test_edit_after_admission_cannot_restore_prior_review_or_add_duplicate(unchecked, monkeypatch):
    from tests.test_command_authority import target
    complete(unchecked, monkeypatch)
    cmd = command(unchecked, "admit_checked_candidate")
    consume(unchecked, cmd)
    saved = unchecked["store"].read()[1]["drafts"][-1]
    edit = Command.from_request(dict(command_id=str(uuid4()), action="edit_revision", requested_at=utc_text(AT),
        expires_at=utc_text(AT+timedelta(hours=1)), targets=[target(saved)], payload={"text": "Edited synthetic text requires a new review."}), EDITOR, environment="local", now=AT)
    assert consume(unchecked, edit)["status"] == "applied"
    result = consume(unchecked, command(unchecked, "admit_checked_candidate", changes=cmd.payload))
    assert result["candidate"]["outcome"] == "already_admitted"
    latest = unchecked["store"].read()[1]["drafts"][-1]
    assert latest["text"] == edit.payload["text"] and not review_is_current(latest)
    assert "required_checks_binding" in latest["revision_history"][0]["review_context"]["two_bot"]


@pytest.mark.parametrize("fault", ["before_commit", "lost_ack"])
def test_atomic_admission_fault_recovers_same_result_without_provider(unchecked, core, monkeypatch, fault):
    from contextlib import contextmanager
    from src.storage import postgres_projection as projection
    sent = complete(unchecked, monkeypatch)
    cmd = command(unchecked, "admit_checked_candidate")
    unchecked["store"].accept(cmd, EDITOR, now=AT)
    initial = unchecked["store"].read()
    original = projection.PostgresProjectionRepository._connection
    fired = False
    @contextmanager
    def interrupted(self, *, writing=False):
        nonlocal fired
        target = False
        with original(self, writing=writing) as c:
            yield c
            target = writing and not fired and c.execute("SELECT count(*) FROM theheat_commands.results WHERE command_id=%s", (cmd.command_id,)).fetchone()[0] == 1
            if target:
                fired = True
                if fault == "before_commit":
                    raise RuntimeError("invented precommit interruption")
        if target and fault == "lost_ack":
            raise projection.ProjectionError("write_outcome_unknown")
    with monkeypatch.context() as patch:
        patch.setattr(projection.PostgresProjectionRepository, "_connection", interrupted)
        with pytest.raises((RuntimeError, projection.ProjectionError)):
            unchecked["store"].consume(resolve, command_id=cmd.command_id, now=AT)
    assert fired
    if fault == "before_commit":
        assert unchecked["store"].read() == initial and unchecked["store"].result(cmd.command_id) is None
    result = unchecked["store"].consume(resolve, command_id=cmd.command_id, now=AT)
    assert result["status"] == "applied" and unchecked["store"].read()[0] == initial[0]+1 and len(sent) == 3


@pytest.mark.parametrize("layer", ["begin", "observe", "complete"])
@pytest.mark.parametrize("fault", ["before_commit", "killed", "lost_ack"])
def test_scoped_checker_transactions_never_repurchase(unchecked, core, monkeypatch, layer, fault):
    from contextlib import contextmanager
    from src.storage import postgres_projection as projection
    request(unchecked)
    assert run_stage(unchecked, "deterministic")["outcome"] == "completed"
    sent, _ = executor.provider(monkeypatch, [executor.envelope("NO")])
    table = {"begin": "theheat_checks.attempts", "observe": "theheat_check_executions.observations", "complete": "theheat_checks.receipts"}[layer]
    original = projection.PostgresProjectionRepository._connection
    fired = False
    @contextmanager
    def interrupted(self, *, writing=False):
        nonlocal fired
        target = False
        with original(self, writing=writing) as c:
            yield c
            target = writing and not fired and c.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 2
            if target:
                fired = True
                if fault == "killed":
                    c.execute("SELECT pg_terminate_backend(pg_backend_pid())")
                if fault == "before_commit":
                    raise RuntimeError("invented precommit interruption")
        if target and fault == "lost_ack":
            raise projection.ProjectionError("write_outcome_unknown")
    with monkeypatch.context() as patch:
        patch.setattr(projection.PostgresProjectionRepository, "_connection", interrupted)
        result = run_stage(unchecked, "safety")
    assert fired and result["outcome"] == "reconciliation_required", result
    prior = len(sent)
    recovered = run_stage(unchecked, "safety")
    if layer == "begin" and fault != "lost_ack":
        assert prior == 0 and len(sent) == 1
    else:
        assert len(sent) == prior == (0 if layer == "begin" else 1)
    if layer == "begin" and fault == "lost_ack" or layer == "observe" and fault != "lost_ack":
        assert recovered["reason"] == "check_response_not_retained"
    assert admin(core[3], "SELECT count(*) FROM theheat_checks.attempts WHERE stage='safety'") == [(1,)]
    assert unchecked["store"].spending("status", {}, now=utc_text(AT))["totals"]["held_micro_usd"] == 65


@pytest.mark.parametrize("phase", ["pending_request", "completed_unadmitted"])
def test_fresh_cluster_restore_recovers_pending_or_completed_work(unchecked, core, cluster, monkeypatch, phase):
    import tempfile
    from pathlib import Path
    import psycopg
    from src.commands.postgres_authority import PostgresCommandAuthority
    case = unchecked
    if phase == "completed_unadmitted":
        sent = complete(case, monkeypatch)
        cmd = command(case, "admit_checked_candidate")
    else:
        sent = []
        cmd = command(case)
    case["store"].accept(cmd, EDITOR, now=AT)
    assert case["store"].result(cmd.command_id) is None
    before = case["store"].read()
    params = core[3]
    _, tool, _ = cluster
    with tempfile.TemporaryDirectory(prefix="theheat-candidate-restore-", dir="/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket = root/"socket"
        socket.mkdir(mode=0o700)
        data, dump = root/"data", root/"candidate.dump"
        tool("pg_dump", "-h", params["host"], "-p", str(params["port"]), "-U", params["user"], "-Fc", "-f", dump, params["dbname"])
        tool("initdb", "-D", data, "-U", "projection_owner", "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale")
        try:
            tool("pg_ctl", "-D", data, "-l", root/"server.log", "-o", f"-c listen_addresses='' -k {socket} -p 55476", "-w", "start")
            with psycopg.connect(host=str(socket), port=55476, user="projection_owner", dbname="postgres", autocommit=True) as c:
                c.execute("CREATE ROLE projection_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                c.execute("CREATE DATABASE restored_candidate TEMPLATE template0")
            tool("pg_restore", "-h", socket, "-p", "55476", "-U", "projection_owner", "-d", "restored_candidate", "--exit-on-error", "--single-transaction", dump)
            restored = PostgresCommandAuthority(socket_directory=socket, port=55476, database="restored_candidate", user="projection_runtime")
            assert restored.read() == before
            assert restored.result(cmd.command_id) is None
            result = restored.consume(resolve, command_id=cmd.command_id, now=AT)
            assert result["status"] == ("applied" if phase == "completed_unadmitted" else "unchanged")
            assert restored.consume(resolve, command_id=cmd.command_id, now=AT) == result
            assert restored.read()[0] == before[0] + (phase == "completed_unadmitted")
            assert len(sent) == (3 if phase == "completed_unadmitted" else 0)
            assert case["store"].read() == before and case["store"].result(cmd.command_id) is None
            assert len(restored.journal()) == (4 if phase == "completed_unadmitted" else 2)
        finally:
            if (data/"postmaster.pid").exists():
                tool("pg_ctl", "-D", data, "-w", "stop", "-m", "fast")


@pytest.mark.parametrize("boundary", ["before_commit", "after_commit"])
def test_client_process_death_does_not_duplicate_admission(unchecked, core, monkeypatch, boundary):
    import multiprocessing
    import os
    from contextlib import contextmanager
    sent = complete(unchecked, monkeypatch)
    cmd = command(unchecked, "admit_checked_candidate")
    unchecked["store"].accept(cmd, EDITOR, now=AT)
    def child():
        store = unchecked["store"]
        if boundary == "before_commit":
            original = store.projections._connection
            @contextmanager
            def die(**kwargs):
                with original(**kwargs) as c:
                    yield c
                    os._exit(23)
            store.projections._connection = die
        store.consume(resolve, command_id=cmd.command_id, now=AT)
        os._exit(24)
    process = multiprocessing.get_context("fork").Process(target=child)
    process.start()
    process.join(timeout=20)
    assert not process.is_alive() and process.exitcode == (23 if boundary == "before_commit" else 24)
    result = unchecked["store"].consume(resolve, command_id=cmd.command_id, now=AT)
    assert result["status"] == "applied" and unchecked["store"].read()[0] == 1 and len(sent) == 3


def test_two_sessions_admit_identical_candidate_once(unchecked, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    complete(unchecked, monkeypatch)
    first, second = command(unchecked, "admit_checked_candidate"), command(unchecked, "admit_checked_candidate")
    for cmd in (first, second):
        unchecked["store"].accept(cmd, EDITOR, now=AT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: unchecked["store"].consume(resolve, now=AT), range(2)))
    assert sorted(r["status"] for r in results) == ["applied", "unchanged"]
    assert {r["state_version"] for r in results} == {1}
    assert len({r["candidate"]["draft_id"] for r in results}) == 1


def test_unavailable_role_keeps_command_pending_and_state_conflict_is_terminal(unchecked, monkeypatch):
    cmd = command(unchecked)
    unchecked["store"].accept(cmd, EDITOR, now=AT)
    with pytest.raises(CommandError, match="authorization is unavailable"):
        unchecked["store"].consume(lambda _: (_ for _ in ()).throw(OSError("invented failure")), now=AT)
    assert unchecked["store"].result(cmd.command_id) is None
    assert unchecked["store"].consume(resolve, now=AT)["candidate"]["outcome"] == "checks_requested"
    from tests.test_command_authority import target
    old = unchecked["store"].read()[1]["drafts"][0]
    edit = Command.from_request(dict(command_id=str(uuid4()), action="edit_revision", requested_at=utc_text(AT), expires_at=utc_text(AT+timedelta(hours=1)),
        targets=[target(old)], payload={"text": "Another draft changed while candidate checks were pending."}), EDITOR, environment="local", now=AT)
    consume(unchecked, edit)
    result = consume(unchecked, command(unchecked))
    assert result["status"] == "rejected" and result["code"] == "candidate_state_conflict"
    projected = unchecked["store"].candidate_projection((unchecked["refs"]["admission_input_id"],), now=AT)[0]
    assert projected["status"] == "stale"


def test_expired_checks_stay_visible_and_cannot_renew_their_proof(unchecked, core, monkeypatch):
    complete(unchecked, monkeypatch)
    cmd = command(unchecked, "admit_checked_candidate")
    unchecked["store"].accept(cmd, EDITOR, now=AT)
    later_clock = AT + timedelta(seconds=301)
    before = unchecked["store"].read(), admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence")
    view = unchecked["store"].candidate_projection((unchecked["refs"]["admission_input_id"],), now=later_clock)[0]
    assert view["status"] == "stale" and view["reason"] == "batch_lease_expired"
    assert set(view["stages"].values()) == {"passed"} and not view["required_checks_completed"]
    assert view["text"] == executor.TEXT and view["last_observed_at"] and view["last_completed_at"]
    result = unchecked["store"].consume(resolve, now=later_clock)
    assert result["status"] == "rejected" and result["code"] == "check_lease_changed"
    assert before == (unchecked["store"].read(), admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence"))


def test_busy_producer_lease_is_bounded_refusal_not_pending_forever(unchecked, core):
    at = utc_datetime(NOW)
    cmd = Command.from_request(dict(command_id=str(uuid4()), action="request_candidate_checks", requested_at=utc_text(at),
        expires_at=utc_text(at+timedelta(hours=1)), targets=[], payload=unchecked["refs"]), EDITOR, environment="local", now=at)
    unchecked["store"].accept(cmd, EDITOR, now=at)
    before = unchecked["store"].read()
    result = unchecked["store"].consume(resolve, now=at)
    assert result["status"] == "rejected" and result["code"] == "batch_lease_busy"
    assert unchecked["store"].read() == before
    assert admin(core[3], "SELECT COUNT(*) FROM theheat_checks.sets") == [(0,)]


def test_read_projection_displays_retained_prose_and_failed_stage_without_execution(unchecked, core, monkeypatch):
    view = unchecked["store"].candidate_projection((unchecked["refs"]["admission_input_id"],), now=AT)[0]
    assert view["text"] == executor.TEXT and view["source"]["where"] and view["source"]["facts"]
    assert view["source"]["headline_metric"]["value"] == "361.0"
    assert admin(core[3], "SELECT COUNT(*) FROM theheat_checks.sets") == [(0,)]
    request(unchecked)
    sent, _ = executor.provider(monkeypatch, [executor.envelope("YES")])
    run_stage(unchecked, "deterministic")
    run_stage(unchecked, "safety")
    before = unchecked["store"].read(), admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence")
    for _ in range(2):
        view = unchecked["store"].candidate_projection((unchecked["refs"]["admission_input_id"],), now=AT)[0]
        assert view["status"] == "checks_blocked" and view["stages"]["safety"] == "rejected"
        assert view["text"] == executor.TEXT and not view["required_checks_completed"]
        assert view["last_observed_at"] and view["stage_times"]["safety"]["completed_at"]
    assert len(sent) == 1
    assert before == (unchecked["store"].read(), admin(core[3], "SELECT * FROM theheat_batch_work.leases ORDER BY fence"))


def test_schema_uncertainty_never_becomes_terminal_candidate_rejection(unchecked, monkeypatch):
    complete(unchecked, monkeypatch)
    cmd = command(unchecked, "admit_checked_candidate")
    unchecked["store"].accept(cmd, EDITOR, now=AT)
    def corrupt(*args, **kwargs):
        raise admission.checks.CheckJournalError("changed_check_schema")
    monkeypatch.setattr(admission.pg, "_packet", corrupt)
    with pytest.raises(admission.checks.CheckJournalError, match="changed_check_schema"):
        unchecked["store"].consume(resolve, now=AT)
    assert unchecked["store"].result(cmd.command_id) is None
    with pytest.raises(admission.checks.CheckJournalError, match="changed_check_schema"):
        unchecked["store"].candidate_projection((unchecked["refs"]["admission_input_id"],), now=AT)


def test_required_proof_roundtrip_and_stage_negatives_match_python_javascript(unchecked, monkeypatch):
    import subprocess
    from pathlib import Path
    from src.editorial.revisions import required_checks_fingerprint
    complete(unchecked, monkeypatch)
    consume(unchecked, command(unchecked, "admit_checked_candidate"))
    draft = unchecked["store"].read()[1]["drafts"][-1]
    variants = []
    for stage in admission.checks.STAGES:
        for mode in ("delete", "transplant"):
            changed = deepcopy(draft)
            stages = changed["review_context"]["two_bot"]["required_checks_binding"]["stages"]
            if mode == "delete":
                del stages[stage]
            else:
                stages[stage]["receipt_sha256"] = "a"*64
            variants.append(changed)
            assert not review_is_current(changed)
    script = """import {reviewIsCurrent} from './lib/draft-revisions.js';
      let raw='';for await(const c of process.stdin)raw+=c;const input=JSON.parse(raw);
      console.log(JSON.stringify({draft:input.draft,current:reviewIsCurrent(input.draft,input.policy),
        invalid:input.variants.map(d=>reviewIsCurrent(d,input.policy))}));"""
    result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=Path(__file__).resolve().parents[1]/"dashboard",
        input=json.dumps(dict(draft=draft, variants=variants, policy=current_editorial_policy())), text=True, capture_output=True, timeout=15, check=True)
    output = json.loads(result.stdout)
    assert output["current"] and output["invalid"] == [False]*8
    assert review_is_current(output["draft"])
    def proof(d):
        return required_checks_fingerprint(d["review_context"]["two_bot"]["required_checks_binding"])
    assert proof(draft) == proof(output["draft"]) == draft["review_binding"]["required_checks_sha256"]


def test_competing_same_event_candidates_serialize_without_second_admission(unchecked, inputs, monkeypatch):
    other_inputs = deepcopy(inputs)
    other_inputs["job_id"] = "invented-competing-job"
    workers = batches.workers
    store = unchecked["store"]
    job = other_inputs["job_id"]
    pair = workers.ready(store, other_inputs, identity="invented-competing-writer", amount=1)
    workers.acquire(store, job)
    grant = workers.begin(store, pair)
    ack = workers.ack(identity="msgbatch_competing")
    workers.observe(store, grant, ack)
    workers.adopt(store, ack, job=job)
    rows = batches.rows(pair)
    candidate = json.loads(rows[0]["result"]["message"]["content"][0]["text"])
    candidate["tweet"] = executor.TEXT
    rows[0]["result"]["message"]["content"][0]["text"] = json.dumps(candidate)
    receipt = batches.retain(unchecked["store"], grant, batches.contract.raw_rows(rows), meta=batches.metadata(identity="msgbatch_competing"))
    payload = {**unchecked["payload"], "job_id": other_inputs["job_id"],
        "custom_id": json.loads(pair[0])["requests"][0]["custom_id"], "receipt_id": receipt["receipt_id"]}
    refs = unchecked["store"].capture_candidate_input(payload, now=utc_datetime(NOW))
    other = dict(store=unchecked["store"], refs=refs, payload=payload)
    assert refs["candidate_id"] != unchecked["refs"]["candidate_id"]
    complete(unchecked, monkeypatch)
    complete(other, monkeypatch)
    one, two = command(unchecked, "admit_checked_candidate"), command(other, "admit_checked_candidate")
    for cmd in (one, two):
        unchecked["store"].accept(cmd, EDITOR, now=AT)
    first = unchecked["store"].consume(resolve, now=AT)
    second = unchecked["store"].consume(resolve, now=AT)
    assert first["status"] == "applied" and second["code"] == "candidate_state_conflict"
    version, state = unchecked["store"].read()
    assert version == 1 and sum(d["event_id"] == payload["save"]["event_id"] for d in state["drafts"]) == 1
