"""Local retained candidate/check/admission join under the command authority lock.

The existing projection stores immutable producer inputs. Existing check and
command journals own all execution and results; this module has no second queue.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
import re
from uuid import NAMESPACE_URL, uuid5

from src.commands import batch_journal, check_journal as checks
from src.commands import postgres_batch as batch, postgres_batch_results as results
from src.commands import postgres_batch_worker as worker, postgres_checks as pg
from src.commands import postgres_check_observations as observations
from src.commands.reducer import Reduction, _identity
from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.draft_admission import evaluator_fields, plan_draft_admission, resolve_admission_place_facts
from src.editorial.policy import valid_policy
from src.editorial.scoring import EditorialScore
from src.editorial.revisions import _record_verified_checks_review, fingerprint, text_hash
from src.storage import postgres_projection as p
from src.two_bot.candidate_derivation import derive_candidate, has_ghcn_reference
from src.two_bot.check_origin import checked_text

NAMESPACE = "candidate-admission-input-v1"
PAUSED_EPOCH = "local-preview-paused-v1"
MAX_INPUT_BYTES = 2_000_000
SAVE_FIELDS = {"legacy_type", "event_id", "score", "city", "tweet_date", "cooldown_exempt", "review_context", "evaluator_metadata"}
INPUT_FIELDS = {"schema_version", "job_id", "custom_id", "candidate_id", "receipt_id", "plan_sha256", "bundle", "memory", "current_context", "state_version", "state_sha256", "captured_at", "save"}
# Existing intern/source labels with intentionally different names.
TYPE_ALIASES = {"calendar_record": "record", "calendar_record_low": "record_low",
                "open_meteo_archive_high": "all_time_high", "open_meteo_archive_low": "all_time_low",
                "absolute_extreme_high": "absolute_extreme", "absolute_extreme_low": "absolute_extreme"}


def refuse(condition, code):
    if not condition:
        raise CommandError(code, "Retained candidate is unavailable; refresh its current status")


# Only these expected lifecycle failures are deterministic refusals. Storage,
# schema, catalog, role, malformed artifact and hash failures remain uncertain.
STALE_CODES = {"stale_batch_owner", "batch_lease_expired", "check_result_unavailable",
    "check_candidate_no_longer_current", "changed_checker_calendar_day", "changed_checker_state",
    "changed_check_context", "formatter_unavailable", "legacy_check_packet", "stale_sync_check_owner", "sync_check_expired", "revision_check_lease_busy"}
DOMAIN_CODES = STALE_CODES | {"batch_lease_busy", "required_checks_disabled", "conflicting_check_candidate"}


@contextmanager
def expected_domain_failures():
    try:
        yield
    except (checks.CheckJournalError, worker.w.BatchWorkerError) as exc:
        code = str(exc)
        if code not in DOMAIN_CODES:
            raise
        raise CommandError(code, "Candidate checks are unavailable; refresh the retained status") from None


def input_id(job_id, custom_id, candidate_id):
    return fingerprint({"job_id": job_id, "custom_id": custom_id, "candidate_id": candidate_id})


def _save(value, bundle):
    refuse(isinstance(value, dict) and set(value) == SAVE_FIELDS, "invalid_admission_inputs")
    refuse(isinstance(bundle, dict), "invalid_admission_bundle")
    kind = bundle.get("signal_kind")
    refuse(value["legacy_type"] == TYPE_ALIASES.get(kind, kind) and value["event_id"] == bundle.get("event_id"), "candidate_source_identity_mismatch")
    for key in ("legacy_type", "event_id", "city", "tweet_date"):
        refuse(isinstance(value[key], str) and len(value[key]) <= 256, "invalid_admission_inputs")
    refuse(bool(value["event_id"]) and bool(value["legacy_type"]) and type(value["cooldown_exempt"]) is bool, "invalid_admission_inputs")
    score = value["score"]
    if score is not None:
        metrics = {"severity", "novelty", "timeliness", "confidence", "shareability", "sensitivity", "total", "threshold"}
        refuse(isinstance(score, dict) and set(score) == metrics | {"category", "reasons", "passes", "label"}, "invalid_admission_score")
        refuse(all(type(score[k]) is int and 0 <= score[k] <= 100 for k in metrics), "invalid_admission_score")
        refuse(isinstance(score["category"], str) and 0 < len(score["category"]) <= 100, "invalid_admission_score")
        refuse(isinstance(score["reasons"], list) and len(score["reasons"]) <= 64 and all(isinstance(r, str) and len(r) <= 512 for r in score["reasons"]), "invalid_admission_score")
        typed = EditorialScore(**{k: score[k] for k in metrics | {"category", "reasons"}})
        refuse(type(score["passes"]) is bool and score == typed.as_dict(), "invalid_admission_score")
    refuse(value["review_context"] is None or isinstance(value["review_context"], dict), "invalid_admission_context")
    # A producer cannot seed verdicts or a preexisting review/approval binding.
    context = value["review_context"] or {}
    refuse("two_bot" not in context and not any(k in context for k in ("review_binding", "approval_binding", "required_checks_binding")), "producer_review_refused")
    try:
        evaluator_fields(value["evaluator_metadata"], value["legacy_type"])
    except ValueError:
        raise CommandError("invalid_evaluator_metadata", "Unsupported retained evaluator fields") from None


def _document(value):
    if value.get("origin_kind") == "synchronous_writer_v1":
        from src.commands.postgres_synchronous_generation import input_document
        return input_document(value)
    refuse(isinstance(value, dict) and set(value) == INPUT_FIELDS and type(value["schema_version"]) is int and value["schema_version"] == 1, "invalid_admission_inputs")
    refuse(type(value["state_version"]) is int and 0 <= value["state_version"] <= p.MAX_INTEGER, "invalid_admission_inputs")
    for key in ("candidate_id", "receipt_id", "plan_sha256", "state_sha256"):
        refuse(isinstance(value[key], str) and re.fullmatch(r"[a-f0-9]{64}", value[key]), "invalid_admission_identity")
    utc_datetime(value["captured_at"])
    _save(value["save"], value["bundle"])
    raw = p._canonical(value)
    refuse(len(raw) <= MAX_INPUT_BYTES, "admission_input_bound")
    return raw


def identity_for(value):
    if value.get("origin_kind") == "synchronous_writer_v1":
        from src.commands.postgres_synchronous_generation import input_id as sync_id
        return sync_id(value)
    return input_id(value["job_id"], value["custom_id"], value["candidate_id"])


def reference_fields(value):
    return ("origin_kind", "generation_id", "candidate_id") if value.get("origin_kind") == "synchronous_writer_v1" else ("job_id", "custom_id", "candidate_id")


def read_input(c, references):
    identity = identity_for(references)
    refuse(identity == references["admission_input_id"], "candidate_input_mismatch")
    found = c.execute("SELECT byte_count FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s", (NAMESPACE, identity)).fetchone()
    refuse(found is not None, "candidate_input_not_found")
    p._require(type(found[0]) is int and 0 < found[0] <= MAX_INPUT_BYTES, "corrupt_admission_input_bound")
    receipt, value = p.PostgresProjectionRepository._read(c, NAMESPACE, identity)
    try:
        raw = _document(value)
    except CommandError:
        raise p.ProjectionError("corrupt_admission_inputs") from None
    p._require(p._sha(raw) == receipt.canonical_sha256, "corrupt_admission_inputs")
    refuse(receipt.canonical_sha256 == references["admission_input_sha256"], "candidate_input_mismatch")
    refuse(all(value[k] == references[k] for k in reference_fields(value)), "candidate_input_mismatch")
    return value


def context_for(value, policy):
    refuse(valid_policy(policy), "editorial_policy_unverified")
    context = {"bundle_sha256": fingerprint(value["bundle"]), "memory_sha256": fingerprint(value["memory"]),
               "policy_sha256": fingerprint(policy), "publication_epoch": PAUSED_EPOCH}
    refuse(context == value["current_context"], "candidate_context_changed")
    return context


def _current(value, version, state, policy, now):
    refuse((state.get("publication_control") or {}).get("enabled") is not True, "candidate_publication_must_be_paused")
    context_for(value, policy)
    refuse(value["state_version"] == version and value["state_sha256"] == p._sha(p._canonical(state)), "candidate_state_conflict")
    refuse(utc_text(now)[:10] == value["captured_at"][:10], "candidate_calendar_day_changed")


def _review(c, value, owner, fence, at, environment):
    if value.get("origin_kind") == "synchronous_writer_v1":
        from src.commands.postgres_synchronous_generation import verify_candidate
        return verify_candidate(c, value)
    report = results.evaluate(c, {"job_id": value["job_id"], "owner": owner, "fence": fence,
        "receipt_id": value["receipt_id"], "current_context": value["current_context"]}, now=at, environment=environment)
    row = next((r for r in report["report"]["rows"] if r["custom_id"] == value["custom_id"]), None)
    refuse(row is not None and row["eligible_for_checks"] and row["candidate_id"] == value["candidate_id"], "candidate_no_longer_eligible")
    return row


def capture(c, payload, *, version, state, policy, now, environment):
    """Trusted task-owned fixture producer only; never exposed by HTTP."""
    fields = {"job_id", "custom_id", "receipt_id", "owner", "fence", "bundle", "memory", "save"}
    refuse(isinstance(payload, dict) and set(payload) == fields, "invalid_capture_fields")
    payload = p._decode(p._canonical(payload))
    registration = batch.read(c, payload["job_id"], environment=environment)
    plan = batch_journal._plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    context = {"bundle_sha256": fingerprint(payload["bundle"]), "memory_sha256": fingerprint(payload["memory"]),
               "policy_sha256": fingerprint(policy), "publication_epoch": PAUSED_EPOCH}
    refuse(valid_policy(policy) and all(context[k] == plan[k] for k in context), "candidate_context_changed")
    report = results.evaluate(c, {k: payload[k] for k in ("job_id", "owner", "fence", "receipt_id")} | {"current_context": context}, now=utc_text(now), environment=environment)
    row = next((r for r in report["report"]["rows"] if r["custom_id"] == payload["custom_id"]), None)
    refuse(row is not None and row["eligible_for_checks"], "candidate_no_longer_eligible")
    assert row is not None
    value = {k: payload[k] for k in ("job_id", "custom_id", "receipt_id", "bundle", "memory", "save")}
    value.update(schema_version=1, candidate_id=row["candidate_id"], plan_sha256=registration["plan_sha256"],
        current_context=context, state_version=version, state_sha256=p._sha(p._canonical(state)), captured_at=utc_text(now))
    raw = _document(value)
    identity = input_id(value["job_id"], value["custom_id"], value["candidate_id"])
    _, field_bytes = p._snapshot(value)
    receipt = p.PostgresProjectionRepository._record(c, NAMESPACE, identity, raw, field_bytes)
    return {"admission_input_id": identity, "admission_input_sha256": receipt.canonical_sha256,
            **{k: value[k] for k in reference_fields(value)},
            "expected_state_version": version, "expected_policy_sha256": context["policy_sha256"]}


def owner_for(command):
    return "candidate-" + command.command_id


def request_for(authority, c, value):
    rows = c.execute("""SELECT i.command_id FROM theheat_commands.intents i
      JOIN theheat_commands.results r USING(command_id)
      WHERE convert_from(i.command_bytes,'UTF8')::jsonb->>'action'='request_candidate_checks'
        AND convert_from(i.command_bytes,'UTF8')::jsonb->'payload'->>'admission_input_id'=%s
      ORDER BY i.sequence LIMIT 17""", (identity_for(value),)).fetchall()
    p._require(len(rows) <= 16, "candidate_request_capacity")
    for (identity,) in rows:
        command, _ = authority._intent(c, identity)
        result = authority._result(c, identity)
        if result["status"] != "rejected":
            return command, result["candidate"]
    return None


def verified_completion(c, identity, value, *, owner, fence, state, policy, now, environment, resolved=None):
    observations.validate(c, environment)
    packet, enrolled = pg._packet(c, identity, environment)
    sync = value.get("origin_kind") == "synchronous_writer_v1"
    fields = ("origin_kind", "generation_id", "grant_id", "observation_sha256", "resolution_sha256", "request_sha256", "candidate_id") if sync else ("job_id", "custom_id", "candidate_id", "plan_sha256")
    refuse(packet["schema_version"] == (5 if has_ghcn_reference(value["bundle"]) else 4 if sync else 2) and all(packet[k] == value[k] for k in fields), "check_candidate_mismatch")
    refuse(p._canonical(packet["bundle"]) == p._canonical(value["bundle"]) and p._canonical(packet["memory"]) == p._canonical(value["memory"]), "check_input_bytes_changed")
    derivation = derive_candidate(packet["candidate"], value["candidate_id"], value["bundle"], policy, resolved=resolved)
    refuse(p._canonical(derivation) == p._canonical(packet["derivation"]), "check_derivation_changed")
    pg._current(c, packet, {"owner": owner, "fence": fence, "current_context": context_for(value, policy),
                         "checker_state_sha256": fingerprint(state)}, utc_text(now), environment, resolved=resolved)
    proofs, outcomes = pg.verified_stage_receipts(c, identity, packet, owner=owner, fence=fence, environment=environment, resolved=resolved)
    return packet, outcomes, completion_proof(identity, value, packet, proofs)


def completion_proof(identity, value, packet, proofs):
    completion = fingerprint({"check_set_id": identity, "candidate_id": value["candidate_id"], "derivation_id": packet["derivation_id"],
        "text_sha256": text_hash(packet["derivation"]["final_text"]), "bundle_sha256": fingerprint(value["bundle"]),
        "policy_sha256": fingerprint(packet["policy"]), "checker_state_sha256": packet["checker_state_sha256"], "stages": proofs})
    proof = dict(schema_version=1, check_set_id=identity, candidate_id=value["candidate_id"], derivation_id=packet["derivation_id"],
                 checker_state_sha256=packet["checker_state_sha256"], completion_sha256=completion, stages=proofs)
    return proof


@dataclass(frozen=True)
class Transition:
    reduction: Reduction
    references: dict


def prepare(authority, c, state, version, command, actor, *, now, policy, editorial_policy, resolve_principal=None, prepared=None, clock_now=None):
    refuse(actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context, "forbidden")
    authorize(actor, command.action)
    refuse(now < utc_datetime(command.expires_at), "command_expired")
    refuse(not policy.enabled, "candidate_publication_must_be_paused")
    refs = command.payload
    value = read_input(c, refs)
    refuse(refs["expected_policy_sha256"] == fingerprint(editorial_policy), "candidate_policy_conflict")
    prior = request_for(authority, c, value)
    # An identical candidate already admitted returns its retained result. This
    # never restores review after editing and still requires current authorization.
    draft_id = "draft_" + str(uuid5(NAMESPACE_URL, authority.environment + ":" + value["candidate_id"]))
    admitted = c.execute("""SELECT i.command_id FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id)
        WHERE convert_from(i.command_bytes,'UTF8')::jsonb->>'action'='admit_checked_candidate'
          AND convert_from(i.command_bytes,'UTF8')::jsonb->'payload'->>'admission_input_id'=%s
          AND convert_from(r.result_bytes,'UTF8')::jsonb->>'status'='applied' LIMIT 2""", (refs["admission_input_id"],)).fetchall()
    p._require(len(admitted) <= 1, "duplicate_candidate_admission")
    if admitted:
        original, _ = authority._intent(c, admitted[0][0])
        result = authority._result(c, admitted[0][0])
        refuse(command.action == "admit_checked_candidate" and all(refs[k] == original.payload[k] for k in ("check_set_id", "expected_completion_sha256")), "candidate_admission_conflict")
        p._require(result["candidate"]["draft_id"] == draft_id, "changed_candidate_admission")
        return Transition(Reduction(state, (), ()), dict(outcome="already_admitted", draft_id=draft_id,
            publication_approved=False, accounting_complete=False, cost_usd=None))
    resolved = prepared.current(authority,c,state,version) if prepared is not None else None
    now = clock_now() if clock_now is not None else now
    refuse(now < utc_datetime(command.expires_at), "command_expired")
    refuse(refs["expected_state_version"] == version, "candidate_state_conflict")
    _current(value, version, state, editorial_policy, now)
    owner = owner_for(prior[0] if prior else command)
    sync = value.get("origin_kind") == "synchronous_writer_v1"
    if sync:
        from src.commands import postgres_synchronous_generation as synchronous, postgres_revision_checks as revisions
        synchronous.current_candidate(authority, c, value, state, editorial_policy, now, resolve_principal, resolved=resolved)
        fence = revisions.acquire(c, prior[1]["check_set_id"], owner, 300, now=utc_text(now), environment=authority.environment,
            origin_kind="synchronous_writer_v1")["lease"]["fence"] if prior else None
    else:
        leased = worker.apply(c, "acquire", dict(job_id=value["job_id"], owner=owner, ttl_seconds=300), now=utc_text(now), environment=authority.environment)
        fence = leased["lease"]["fence"]
    row = _review(c, value, owner, fence, utc_text(now), authority.environment)
    derivation = derive_candidate(row["candidate"], value["candidate_id"], value["bundle"], editorial_policy, resolved=resolved)
    # Same deterministic preflight before request and after checks.
    args = value["save"]
    context = deepcopy(args["review_context"] or {})
    proof = None
    if command.action == "admit_checked_candidate":
        refuse(prior is not None and prior[1]["check_set_id"] == refs["check_set_id"], "check_request_not_found")
        packet, outcomes, proof = verified_completion(c, refs["check_set_id"], value, owner=owner, fence=fence,
            state=state, policy=editorial_policy, now=now, environment=authority.environment, resolved=resolved)
        refuse(proof["completion_sha256"] == refs["expected_completion_sha256"], "check_completion_conflict")
        context["two_bot"] = dict(signal_kind=value["bundle"]["signal_kind"], bundle=deepcopy(value["bundle"]),
            fact_check=outcomes["fact_check"], critic=outcomes["critic"], required_checks_binding=proof,
            reviewed_text_sha256=text_hash(checked_text(packet, resolved=resolved)), reviewed_bundle_sha256=fingerprint(value["bundle"]),
            reviewed_policy_sha256=fingerprint(editorial_policy), cited_impact=packet["candidate"].get("cited_impact"),
            human_impact=value["bundle"].get("human_impact"))
    plan = plan_draft_admission(state, text=derivation["final_text"], tweet_type=args["legacy_type"], event_id=args["event_id"],
        draft_id=draft_id, at=now, editorial_policy=editorial_policy, place_facts=resolve_admission_place_facts(state, args["event_id"]),
        score=args["score"], review_context=context,
        evaluator_metadata=args["evaluator_metadata"], city=args["city"], tweet_date=args["tweet_date"], cooldown_exempt=args["cooldown_exempt"])
    refuse(plan.draft is not None, plan.reason or "candidate_admission_refused")
    # Reinterpretation and planning may block. Never promote using their start
    # time: repeat bounded locked currentness and original actor authorization.
    if prepared is not None:
        prepared.current(authority, c, state, version)
        now = clock_now() if clock_now is not None else now
        refuse(now < utc_datetime(command.expires_at), "command_expired")
        fresh_actor = resolve_principal(command.actor_subject) if resolve_principal is not None else None
        refuse(fresh_actor is not None and fresh_actor.subject == command.actor_subject
            and fresh_actor.authentication_context == command.authentication_context, "forbidden")
        assert fresh_actor is not None
        authorize(fresh_actor, command.action)
        _current(value, version, state, editorial_policy, now)
        synchronous.current_candidate(authority, c, value, state, editorial_policy, now, resolve_principal, resolved=resolved)
        if proof is not None:
            if packet["schema_version"] == 5:
                # The original checker remains an authorization dependency even
                # when a different editor submits this final admission.
                assert prior is not None
                check_command, check_value, check_set = runner_context(authority, c, prior[0].command_id,
                    resolve_principal, version=version, state=state, policy=editorial_policy, now=now, resolved=resolved)
                refuse(check_command == prior[0] and p._canonical(check_value) == p._canonical(value)
                    and check_set == refs["check_set_id"] == prior[1]["check_set_id"], "check_request_changed")
            pg._current(c, packet, {"owner": owner, "fence": fence, "current_context": context_for(value, editorial_policy),
                "checker_state_sha256": fingerprint(state)}, utc_text(now), authority.environment, resolved=resolved)
    common = dict(publication_approved=False, accounting_complete=False, cost_usd=None)
    if command.action == "request_candidate_checks":
        if sync:
            from src.commands.postgres_sync_checks import enroll
            result = enroll(c, value, refs, row, state, version, editorial_policy, now=now, environment=authority.environment, resolved=resolved)
            revisions.acquire(c, result["check_set_id"], owner, 300, now=utc_text(now), environment=authority.environment, origin_kind="synchronous_writer_v1")
        else:
            result = pg.apply(c, "intake", dict(job_id=value["job_id"], owner=owner, fence=fence, receipt_id=value["receipt_id"],
            current_context=value["current_context"], custom_id=value["custom_id"], bundle=value["bundle"], memory=value["memory"], checker_state=state),
            now=utc_text(now), environment=authority.environment)
        return Transition(Reduction(state, (), ()), dict(common, outcome="checks_requested", check_set_id=result["check_set_id"]))
    assert plan.draft is not None and proof is not None
    _record_verified_checks_review(plan.draft, policy=editorial_policy, at=utc_text(now))
    from src.commands.postgres_revision_checks import retain_source
    retain_source(c, plan.draft, command, refs, value, environment=authority.environment)
    return Transition(Reduction(plan.state, plan.changed_ids, (_identity(plan.draft),)), dict(common, outcome="candidate_admitted",
        check_set_id=refs["check_set_id"], completion_sha256=proof["completion_sha256"], draft_id=draft_id,
        suppressions=list(plan.suppressions)))


def _source_summary(value):
    bundle = value["bundle"]
    def scalar(value):
        return str(value)[:512] if type(value) in (str, int, float, bool) else ""
    def fact(value):
        return {k: scalar(value.get(k)) for k in ("label", "value", "unit")} if isinstance(value, dict) else None
    facts = bundle.get("current_facts")
    return dict(event_id=value["save"]["event_id"], type=value["save"]["legacy_type"],
        where=scalar(bundle.get("where")), when=scalar(bundle.get("when")),
        headline_metric=fact(bundle.get("headline_metric")),
        facts=[fact(f) for f in facts[:16] if isinstance(f, dict)] if isinstance(facts, list) else [])


def _retained_text(c, value, *, policy, now, environment, resolved=None):
    if value.get("origin_kind") == "synchronous_writer_v1":
        from src.commands.postgres_synchronous_generation import verify_candidate
        row = verify_candidate(c, value)
        return derive_candidate(row["candidate"], value["candidate_id"], value["bundle"], policy, resolved=resolved)["final_text"]
    # Display only: use the existing decoder and immutable input receipt, without
    # taking a lease or certifying readiness. Intake repeats its authoritative
    # chosen-result/context/lease checks under the command lock.
    status = worker.apply(c, "status", {"job_id": value["job_id"]}, now=utc_text(now), environment=environment)
    plan_raw = batch._plan_bytes(c, status["plan_sha256"])
    plan = batch_journal._plan(plan_raw, status["plan_sha256"])
    receipts = results._receipts(c, value["job_id"], status["grant_id"])
    retained = next((r for r in receipts if r["receipt_id"] == value["receipt_id"]), None)
    p._require(retained is not None, "missing_candidate_input_receipt")
    report, _, items = results.r._decode(plan_raw, plan, retained, value["current_context"], utc_text(now), status["provider_batch_id"])
    row = next((r for r in report["rows"] if r["custom_id"] == value["custom_id"]), None)
    refuse(row is not None and row["eligible_for_checks"], "candidate_no_longer_eligible")
    identity = fingerprint(dict(plan_sha256=status["plan_sha256"], custom_id=value["custom_id"], item=items[value["custom_id"]]))
    refuse(identity == value["candidate_id"], "candidate_input_mismatch")
    assert row is not None
    return derive_candidate(row["candidate"], identity, value["bundle"], policy)["final_text"]


def passive_recorded(authority, c, value, command, packet, identity, state, version, policy, now, row):
    """Metadata precondition, not executable validation or approval."""
    refs = command.payload
    refuse(command.action == "request_candidate_checks" and identity_for(value) == refs["admission_input_id"], "check_request_mismatch")
    read_input(c, refs)
    accepted = authority._result(c, command.command_id)
    refuse(accepted is not None and accepted["status"] == "unchanged"
        and accepted["candidate"]["outcome"] == "checks_requested"
        and accepted["candidate"]["check_set_id"] == identity, "check_request_not_completed")
    refuse(packet["schema_version"] == 5 and packet["admission_input_id"] == refs["admission_input_id"]
        and packet["admission_input_sha256"] == refs["admission_input_sha256"], "check_input_bytes_changed")
    fields = ("origin_kind", "generation_id", "grant_id", "observation_sha256", "resolution_sha256", "request_sha256", "candidate_id")
    refuse(all(packet[k] == value[k] for k in fields) and packet["bundle"] == value["bundle"] and packet["memory"] == value["memory"], "check_candidate_mismatch")
    refuse(packet["state_version"] == version and packet["checker_state_sha256"] == fingerprint(state)
        and packet["current_context"] == context_for(value, policy) and packet["check_date"] == utc_text(now)[:10], "changed_check_context")
    refuse(now < utc_datetime(packet["useful_until"]) and now < utc_datetime(command.expires_at), "sync_check_expired")
    lease = c.execute("SELECT owner,fence,expires_at FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
    refuse(lease is not None and lease[0] == owner_for(command) and now < utc_datetime(lease[2]), "stale_sync_check_owner")
    if all(v == "passed" for v in row["stages"].values()):
        proofs, _ = pg.recorded_stage_receipts(c, identity, packet, owner=owner_for(command), fence=lease[1], environment=authority.environment)
        proof = completion_proof(identity, value, packet, proofs)
        row.update(status="checks_recorded", expected_completion_sha256=proof["completion_sha256"])


def project(authority, c, allowed, *, version, state, policy, now, resolve_principal=None):
    """Read-only and explicitly allowlisted; no lease acquisition or check run."""
    refuse(isinstance(allowed, (list, tuple)) and len(allowed) <= 16 and len(set(allowed)) == len(allowed), "candidate_list_bound")
    output = []
    for identity in allowed:
        refuse(isinstance(identity, str) and re.fullmatch(r"[a-f0-9]{64}", identity), "invalid_candidate_allowlist")
        receipt, value = p.PostgresProjectionRepository._read(c, NAMESPACE, identity)
        refs = {"admission_input_id": identity, "admission_input_sha256": receipt.canonical_sha256,
            **{k: value[k] for k in reference_fields(value)},
            "expected_state_version": version, "expected_policy_sha256": fingerprint(policy)}
        read_input(c, refs)
        row = dict(refs, status="not_checked", stages=dict.fromkeys(checks.STAGES, "pending"),
            required_checks_completed=False, publication_approved=False, accounting_complete=False, cost_usd=None,
            source=_source_summary(value), text=None, captured_at=value["captured_at"],
            last_observed_at=None, last_completed_at=None, stage_times={},
            check_set_id=None, expected_completion_sha256=None, saved_draft_id=None)
        resolved = None
        try:
            with expected_domain_failures():
                prior = request_for(authority, c, value)
                if prior:
                    command, result = prior
                    identity = result["check_set_id"]
                    row["check_set_id"] = identity
                    packet, enrolled = pg._packet(c, identity, authority.environment)
                    stages, attempts = pg._stages(c, identity, packet, enrolled)
                    row["stages"] = stages
                    row["text"] = packet["derivation"]["final_text"] if packet["schema_version"] == 5 else checked_text(packet)
                    observations.validate(c, authority.environment)
                    for stage, attempt in attempts.items():
                        observed = completed = None
                        if attempt:
                            if observations._observation(c, identity, stage, attempt):
                                observed = c.execute("SELECT recorded_at FROM theheat_check_executions.observations WHERE grant_id=%s", (attempt["grant_id"],)).fetchone()[0]
                            terminal = pg._terminal(c, attempt)
                            completed = terminal["recorded_at"] if terminal else None
                        row["stage_times"][stage] = dict(observed_at=observed, completed_at=completed)
                    row["last_observed_at"] = max((t["observed_at"] for t in row["stage_times"].values() if t["observed_at"]), default=None)
                    row["last_completed_at"] = max((t["completed_at"] for t in row["stage_times"].values() if t["completed_at"]), default=None)
                    row["status"] = "checks_pending" if all(v in ("pending", "passed") for v in stages.values()) else "checks_blocked"
                _current(value, version, state, policy, now)
                if has_ghcn_reference(value["bundle"]):
                    # Listing is passive. Fresh source replay and every receipt
                    # interpretation still happen in the admission worker.
                    if prior:
                        passive_recorded(authority, c, value, command, packet, identity, state, version, policy, now, row)
                    else:
                        from src.commands.postgres_synchronous_generation import verify_candidate
                        row["text"] = verify_candidate(c, value)["candidate"]["tweet"]
                    output.append(row)
                    continue
                if value.get("origin_kind") == "synchronous_writer_v1":
                    from src.commands.postgres_synchronous_generation import current_candidate
                    current_candidate(authority, c, value, state, policy, now, resolve_principal, resolved=resolved)
                if prior:
                    if value.get("origin_kind") == "synchronous_writer_v1":
                        saved_lease = c.execute("SELECT fence FROM theheat_checks.draft_leases WHERE check_set_id=%s ORDER BY fence DESC LIMIT 1", (identity,)).fetchone()
                        lease = dict(fence=saved_lease[0]) if saved_lease else dict(fence=0)
                    else:
                        lease = worker.apply(c, "status", {"job_id": value["job_id"]}, now=utc_text(now), environment=authority.environment)["lease"]
                    pg._current(c, packet, {"owner": owner_for(command), "fence": lease["fence"],
                        "current_context": context_for(value, policy), "checker_state_sha256": fingerprint(state)}, utc_text(now), authority.environment, resolved=resolved)
                    if all(v == "passed" for v in stages.values()):
                        _, _, proof = verified_completion(c, identity, value, owner=owner_for(command), fence=lease["fence"],
                            state=state, policy=policy, now=now, environment=authority.environment, resolved=resolved)
                        row.update(status="checks_completed", required_checks_completed=True, expected_completion_sha256=proof["completion_sha256"])
                else:
                    row["text"] = _retained_text(c, value, policy=policy, now=now, environment=authority.environment, resolved=resolved)
        except CommandError as exc:
            stale = exc.code in STALE_CODES or "changed" in exc.code or "conflict" in exc.code or exc.code == "candidate_no_longer_eligible"
            row.update(status="stale" if stale else "checks_blocked", reason=exc.code)
        # A saved record is shown without re-certifying its now-changed context.
        draft_id = "draft_" + str(uuid5(NAMESPACE_URL, authority.environment + ":" + value["candidate_id"]))
        if any(d.get("id") == draft_id for d in state.get("drafts", [])):
            row.update(status="admitted", saved_draft_id=draft_id, required_checks_completed=False)
        if row["status"] == "not_checked" and value.get("origin_kind") != "synchronous_writer_v1":
            # Result retention precedes expiry of the producer's existing lease.
            # This is availability only; intake still acquires its own fenced lease.
            batch_state = worker.apply(c, "status", {"job_id": value["job_id"]}, now=utc_text(now), environment=authority.environment)
            lease = batch_state.get("lease")
            if lease and utc_datetime(lease["expires_at"]) > now:
                row["checks_available_at"] = lease["expires_at"]
        output.append(row)
    return output


def runner_context(authority, c, command_id, resolve, *, version, state, policy, now, resolved=None):
    found = authority._intent(c, command_id)
    refuse(found is not None, "check_request_not_found")
    command = found[0]
    refuse(command.action == "request_candidate_checks", "check_request_not_found")
    result = authority._result(c, command_id)
    refuse(result is not None and result["status"] != "rejected", "check_request_not_completed")
    try:
        actor = resolve(command.actor_subject)
    except Exception:
        raise CommandError("authorization_unavailable", "Current operator authorization is unavailable") from None
    refuse(actor is not None and actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context, "forbidden")
    authorize(actor, command.action)
    refuse(now < utc_datetime(command.expires_at), "command_expired")
    value = read_input(c, command.payload)
    _current(value, version, state, policy, now)
    if value.get("origin_kind") == "synchronous_writer_v1":
        from src.commands.postgres_synchronous_generation import current_candidate
        current_candidate(authority, c, value, state, policy, now, resolve, resolved=resolved)
    return command, value, result["candidate"]["check_set_id"]
