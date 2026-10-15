"""Finite local important-event groups on the existing journals and state lock."""

from __future__ import annotations

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from src.commands import postgres_sourced_generation as generation
from src.commands import postgres_candidate_admission as admission
from src.commands import (
    postgres_batch as batch,
    postgres_batch_results as results,
    postgres_batch_worker as worker,
)
from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.revisions import fingerprint, text_hash, _record_verified_checks_review
from src.storage import postgres_projection as p
from src.two_bot import important_variants as contract, negative_cache
from src.two_bot.sourced_generation import identity as source_identity

ALLOWANCE = "important-alternate-allowance-v1"
CLAIM = "important-alternate-claim-v1"
JOB = "important-alternate-job-v1"
CAPTURE = "important-alternate-capture-v1"
ADMISSION = "important-alternate-admission-v1"
LEASE = "important-alternate-check-lease-v1"
CYCLE = "important-alternate-read-cycle-v1"
ORIGIN = "important_batch_slate_v1"
MAX_RECORD = 262144
refuse = generation.refuse
read = generation.read
exists = generation.exists


def contract_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except contract.ImportantContractError as exc:
        raise CommandError(str(exc), "Important-event allowance or angle is invalid") from None


def record(c, namespace, identity, value):
    refuse(
        len(p._canonical(value))
        <= (contract.MAX_ALLOWANCE if namespace == ALLOWANCE else MAX_RECORD),
        "important_record_bound",
    )
    return generation.record(c, namespace, identity, value)


def configuration(authority):
    load = getattr(authority, "important_variants_configuration", None)
    refuse(authority.environment == "local" and callable(load), "important_variants_unavailable")
    assert callable(load)  # Narrow after the explicit fail-closed guard above.
    value = p._decode(p._canonical(load()))
    refuse(
        isinstance(value, dict) and set(value) == {"allowance_id"},
        "important_configuration_invalid",
    )
    contract._sha(value["allowance_id"])
    return value


def claim_id(value, brief_id):
    return fingerprint(
        dict(source_key=value["source_key"], event_id=value["save"]["event_id"], brief_id=brief_id)
    )


def current(authority, c, allowance_id, state, policy, now, *, actor=None):
    refuse(
        configuration(authority)["allowance_id"] == allowance_id, "important_allowance_superseded"
    )
    allowance = contract_call(contract.allowance_document, read(c, ALLOWANCE, allowance_id))
    refuse(contract.digest(allowance) == allowance_id, "important_allowance_changed")
    value, _ = generation.current(
        authority, c, allowance["brief_id"], policy, now, require_reservation=False
    )
    refuse(
        value["schema_version"] == 1 and value["urgent"] is False,
        "important_nonurgent_source_required",
    )
    bundle, memory, context, _ = source_identity(
        value, state, policy, now=now, epoch=admission.PAUSED_EPOCH
    )
    refuse(context == allowance["context"], "important_context_changed")
    refuse(
        utc_datetime(allowance["valid_from"]) <= now < utc_datetime(allowance["valid_until"])
        and utc_datetime(allowance["valid_until"]) <= utc_datetime(value["useful_until"]),
        "important_allowance_expired",
    )
    contract_call(contract.requests_for, bundle, memory, policy, allowance)
    if actor is not None:
        authorize(actor, "request_important_variants")
        refuse(
            actor.subject == allowance["authorized_subject"]
            and actor.authentication_context == allowance["authentication_context"],
            "important_actor_changed",
        )
    return allowance, value, bundle, memory


def ordinary_guard(c, value, brief_id):
    refuse(not exists(c, CLAIM, claim_id(value, brief_id)), "important_event_already_claimed")


def prepare(
    authority, c, state, version, command, actor, *, now, policy, editorial_policy, resolved=None
):
    del resolved
    authorize(actor, command.action)
    refs = command.payload
    refuse(
        actor.subject == command.actor_subject
        and actor.authentication_context == command.authentication_context,
        "important_actor_changed",
    )
    refuse(
        not policy.enabled and policy.epoch is None and now < utc_datetime(command.expires_at),
        "important_command_expired",
    )
    refuse(
        refs["expected_state_version"] == version
        and refs["expected_policy_sha256"] == fingerprint(editorial_policy),
        "important_context_changed",
    )
    refuse(refs["allowance_id"] == refs["allowance_sha256"], "important_allowance_changed")
    allowance, value, bundle, memory = current(
        authority, c, refs["allowance_id"], state, editorial_policy, now, actor=actor
    )
    refuse(
        refs["brief_id"] == refs["brief_sha256"] == allowance["brief_id"], "important_brief_changed"
    )
    refuse(
        negative_cache.should_skip(state, value["save"]["event_id"], bundle, now=now) is None,
        "generation_negative_cache",
    )
    ordinary_guard(c, value, refs["brief_id"])
    # An accepted pending command is not a claim. Only an actual successful
    # prior source registration prevents the competing mode from purchasing.
    prior = c.execute(
        """SELECT r.result_bytes,r.digest FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id)
        WHERE convert_from(i.command_bytes,'UTF8')::jsonb->>'action'='request_sourced_generation'
        AND convert_from(i.command_bytes,'UTF8')::jsonb->'payload'->>'brief_id'=%s
        AND convert_from(r.result_bytes,'UTF8')::jsonb->>'status'='applied' LIMIT 2""",
        (refs["brief_id"],),
    ).fetchall()
    from src.commands.postgres_authority import _decode

    for raw, sha in prior:
        prior_result = _decode(raw, sha)
        prior_job = prior_result["generation"]["job_id"]
        batch.read(c, prior_job, environment=authority.environment)
        refuse(False, "ordinary_event_already_started")
    key = fingerprint(
        dict(
            brief_id=refs["brief_id"],
            context=allowance["context"],
            allowance_sha256=refs["allowance_id"],
        )
    )
    job_id = "iv_" + key
    raw = contract_call(
        contract.prepare_plan,
        bundle,
        memory,
        policy=editorial_policy,
        allowance=allowance,
        job_id=job_id,
        created_at=utc_text(now),
        useful_until=allowance["valid_until"],
    )
    sha = p._sha(raw)
    reservation = dict(
        allowance["writer_reservation"],
        intent_id="writer_" + key,
        job_id=job_id,
        request_sha256=sha,
    )
    registration = batch.register(
        c,
        raw,
        expected_plan_sha256=sha,
        reservation=reservation,
        now=utc_text(now),
        environment=authority.environment,
    )
    plan = p._decode(raw)
    job = dict(
        schema_version=1,
        brief_id=refs["brief_id"],
        allowance_id=refs["allowance_id"],
        plan_sha256=sha,
        context=allowance["context"],
        memory=memory.to_dict(),
        policy=editorial_policy,
        source_useful_until=value["useful_until"],
        useful_until=plan["useful_until"],
        created_at=plan["created_at"],
        slots=[
            dict(slot=i + 1, custom_id=r["custom_id"], params_sha256=fingerprint(r["params"]))
            for i, r in enumerate(plan["requests"])
        ],
        reservation=reservation,
        command_id=command.command_id,
        authorized_subject=actor.subject,
        authentication_context=actor.authentication_context,
        negative_cache_input_sha=negative_cache.bundle_fingerprint(bundle, state, now=now),
        negative_cache_epoch=negative_cache.decision_epoch(),
    )
    record(c, JOB, job_id, job)
    record(
        c,
        CLAIM,
        claim_id(value, refs["brief_id"]),
        dict(
            schema_version=1,
            job_id=job_id,
            command_id=command.command_id,
            brief_id=refs["brief_id"],
            allowance_id=refs["allowance_id"],
        ),
    )
    return dict(
        brief_id=refs["brief_id"],
        job_id=job_id,
        plan_sha256=sha,
        intent_id=registration["intent_id"],
        generation_status="queued",
        execution_mode="important_batch",
        slate_id=job_id,
        slate_sha256=p._sha(p._canonical(job)),
    )


def runner_identity(authority, c, command_id):
    stored, completed = authority._intent(c, command_id), authority._result(c, command_id)
    refuse(
        stored is not None
        and stored[0].action == "request_important_variants"
        and completed is not None
        and completed.get("status") == "applied",
        "important_not_accepted",
    )
    command = stored[0]
    refs = completed["generation"]
    job = read(c, JOB, refs["job_id"])
    refuse(
        job["command_id"] == command_id
        and job["brief_id"] == refs["brief_id"]
        and p._sha(p._canonical(job)) == refs["slate_sha256"],
        "important_job_changed",
    )
    return command, refs, job


def runner_context(authority, c, command_id, resolve, state, policy, now):
    command, refs, job = runner_identity(authority, c, command_id)
    try:
        actor = resolve(command.actor_subject)
    except Exception:
        raise CommandError(
            "authorization_unavailable", "Important-event authorization unavailable"
        ) from None
    refuse(actor is not None, "forbidden")
    allowance, value, bundle, memory = current(
        authority, c, job["allowance_id"], state, policy, now, actor=actor
    )
    refuse(
        job["context"] == allowance["context"]
        and job["memory"] == memory.to_dict()
        and job["policy"] == policy,
        "important_context_changed",
    )
    claim = read(c, CLAIM, claim_id(value, job["brief_id"]))
    refuse(
        claim["job_id"] == refs["job_id"] and claim["command_id"] == command.command_id,
        "important_claim_changed",
    )
    raw = contract_call(
        contract.prepare_plan,
        bundle,
        memory,
        policy=policy,
        allowance=allowance,
        job_id=refs["job_id"],
        created_at=job["created_at"],
        useful_until=job["useful_until"],
    )
    refuse(p._sha(raw) == job["plan_sha256"] == refs["plan_sha256"], "important_plan_changed")
    return refs, job, value


def collection_cycle(c, job_id, *, now):
    ordinal = 1
    while exists(c, CYCLE, job_id + ":" + str(ordinal)):
        ordinal += 1
    refuse(ordinal <= 4, "important_collection_limit")
    record(
        c,
        CYCLE,
        job_id + ":" + str(ordinal),
        dict(job_id=job_id, ordinal=ordinal, maximum_gets=2, reserved_at=utc_text(now)),
    )
    return ordinal


def capture(authority, c, refs, job, value, state, version, policy, now, owner):
    job_id = refs["job_id"]
    index = results.index(
        c, {"job_id": job_id}, now=utc_text(now), environment=authority.environment
    )
    refuse(index["chosen_receipt_id"] is not None, "generation_result_unavailable")
    if exists(c, CAPTURE, job_id):
        saved = read(c, CAPTURE, job_id)
        refuse(saved["receipt_id"] == index["chosen_receipt_id"], "important_capture_changed")
        return saved
    lease = worker.apply(
        c,
        "acquire",
        dict(job_id=job_id, owner=owner, ttl_seconds=60),
        now=utc_text(now),
        environment=authority.environment,
    )["lease"]
    report = results.evaluate(
        c,
        dict(
            job_id=job_id,
            owner=owner,
            fence=lease["fence"],
            receipt_id=index["chosen_receipt_id"],
            current_context=job["context"],
        ),
        now=utc_text(now),
        environment=authority.environment,
    )
    slots = []
    for slot in job["slots"]:
        row = next(
            (r for r in report["report"]["rows"] if r["custom_id"] == slot["custom_id"]), None
        )
        item = dict(
            slot, disposition="missing_result", candidate=None, blocked_reasons=["missing_result"]
        )
        if row is not None:
            item.update(
                disposition="eligible" if row["eligible_for_checks"] else "ineligible",
                blocked_reasons=row["blocked_reasons"],
                raw_sha256=row["raw_sha256"],
            )
            if row["eligible_for_checks"]:
                item["candidate"] = admission.capture(
                    c,
                    dict(
                        job_id=job_id,
                        custom_id=slot["custom_id"],
                        receipt_id=index["chosen_receipt_id"],
                        owner=owner,
                        fence=lease["fence"],
                        bundle=value["bundle"],
                        memory=job["memory"],
                        save=value["save"],
                    ),
                    version=version,
                    state=state,
                    policy=policy,
                    now=now,
                    environment=authority.environment,
                )
        slots.append(item)
    captured = dict(
        schema_version=1,
        job_id=job_id,
        plan_sha256=job["plan_sha256"],
        receipt_id=index["chosen_receipt_id"],
        state_version=version,
        state_sha256=p._sha(p._canonical(state)),
        captured_at=utc_text(now),
        slots=slots,
    )
    record(c, CAPTURE, job_id, captured)
    retain_concordant_kill(authority, c, refs, job, value, state, version, now, index, report)
    return captured


def captured_outcome(captured):
    if any(slot["candidate"] is not None for slot in captured["slots"]):
        return dict(outcome="candidate_ready")
    if any(slot["disposition"] == "missing_result" for slot in captured["slots"]):
        return dict(outcome="reconciliation_required", reason="important_results_incomplete")
    return dict(outcome="blocked", reason="important_no_eligible_writer_result")


def retain_concordant_kill(authority, c, refs, job, value, state, version, now, index, report):
    rows = report["report"]["rows"]
    if len(rows) != 2 or any(r["blocked_reasons"] != ["writer_kill"] for r in rows):
        return
    from src.two_bot import writer
    import json

    receipts = results._receipts(c, refs["job_id"], index["submission"]["grant_id"])
    retained = next(r for r in receipts if r["receipt_id"] == index["chosen_receipt_id"])
    verdicts = [
        writer._parse_writer_json(json.loads(line)["result"]["message"]["content"][0]["text"])
        for line in retained["results"].splitlines()
    ]
    if not all(
        v.kill_scope == "evidence" and v.kill_code in negative_cache.EVIDENCE_KILL_CODES
        for v in verdicts
    ):
        return
    if len({v.kill_code for v in verdicts}) != 1:
        return
    updated = deepcopy(state)
    verdict = verdicts[0]
    disposition = dict(
        cacheable=True,
        kill_scope="evidence",
        kill_code=verdict.kill_code,
        kill_stage="writer",
        kill_reason=verdict.kill_reason,
        negative_cache_input_sha=job["negative_cache_input_sha"],
        negative_cache_epoch=job["negative_cache_epoch"],
    )
    negative_cache.record_result(
        updated,
        value["save"]["event_id"],
        generation.source_bundle(value["bundle"]),
        disposition,
        now=utc_datetime(retained["recorded_at"]),
    )
    if updated != state:
        from src.commands.postgres_authority import NAMESPACE

        refuse(version < p.MAX_INTEGER, "authority_version_exhausted")
        generation.record(c, NAMESPACE, str(version + 1), updated)
        c.execute(
            "UPDATE theheat_commands.state SET version=%s,snapshot_id=%s WHERE singleton=1",
            (version + 1, str(version + 1)),
        )


def is_group(c, job_id, *, environment):
    """The old schema1 accepts iv_ IDs too; names alone confer no group role."""
    if not isinstance(job_id, str) or not job_id.startswith("iv_"):
        return False
    from src.commands.batch_journal import _plan

    registered = batch.read(c, job_id, environment=environment)
    plan = _plan(batch._plan_bytes(c, registered["plan_sha256"]), registered["plan_sha256"])
    return plan["schema_version"] == 2


def member(c, value, *, environment):
    if not is_group(c, value.get("job_id"), environment=environment):
        return None
    job = read(c, JOB, value["job_id"])
    capture = read(c, CAPTURE, value["job_id"])
    matches = [
        s
        for s in capture["slots"]
        if s["candidate"] is not None
        and s["candidate"]["admission_input_id"] == admission.identity_for(value)
    ]
    refuse(
        len(matches) == 1
        and matches[0]["custom_id"] == value["custom_id"]
        and job["plan_sha256"] == value["plan_sha256"],
        "important_member_changed",
    )
    return job, matches[0]


def current_member(authority, c, value, state, policy, now, resolve):
    membership = member(c, value, environment=authority.environment)
    if membership is None:
        return None
    job, slot = membership
    refuse(resolve is not None, "authorization_unavailable")
    runner_context(authority, c, job["command_id"], resolve, state, policy, now)
    refuse(not exists(c, ADMISSION, value["job_id"]), "important_membership_sealed")
    return job, slot


def shared_lease(c, value, owner, *, now, environment, acquire=False):
    job_id = value["job_id"]
    existing = read(c, LEASE, job_id) if exists(c, LEASE, job_id) else None
    status = worker.apply(
        c, "status", {"job_id": job_id}, now=utc_text(now), environment=environment
    )
    lease = status["lease"]
    if existing is not None:
        refuse(
            lease is not None
            and lease == existing
            and lease["owner"] == owner
            and now < utc_datetime(lease["expires_at"]),
            "important_original_lease_expired",
        )
        return lease
    refuse(acquire, "important_checks_not_enrolled")
    lease = worker.apply(
        c,
        "acquire",
        dict(job_id=job_id, owner=owner, ttl_seconds=300),
        now=utc_text(now),
        environment=environment,
    )["lease"]
    record(c, LEASE, job_id, lease)
    return lease


def check_reservation(c, value, stage, request_sha256, reservation, *, environment):
    membership = member(c, value, environment=environment)
    if membership is None or stage == "deterministic":
        return
    job, slot = membership
    allowance = contract_call(contract.allowance_document, read(c, ALLOWANCE, job["allowance_id"]))
    expected = dict(
        allowance["check_reservations"][stage],
        intent_id="ic_" + fingerprint(dict(job_id=value["job_id"], slot=slot["slot"], stage=stage)),
        job_id=value["job_id"],
        request_sha256=request_sha256,
    )
    refuse(reservation == expected, "important_check_reservation_changed")


def draft_id(environment, job_id):
    return "draft_" + str(uuid5(NAMESPACE_URL, environment + ":" + job_id))


def completion_snapshot(authority, c, job_id, state, version, policy, now, resolve):
    job = read(c, JOB, job_id)
    runner_context(authority, c, job["command_id"], resolve, state, policy, now)
    captured = read(c, CAPTURE, job_id)
    rows, verified = [], {}
    from src.commands import postgres_checks as checks

    for slot in captured["slots"]:
        item = dict(
            slot=slot["slot"],
            custom_id=slot["custom_id"],
            candidate=slot["candidate"],
            disposition=slot["disposition"],
            blocked_reasons=slot["blocked_reasons"],
            check_set_id=None,
            completion_sha256=None,
            stages=None,
        )
        if slot["candidate"] is not None:
            value = admission.read_input(c, slot["candidate"])
            prior = admission.request_for(authority, c, value)
            if prior:
                command, enrolled = prior
                identity = enrolled["check_set_id"]
                item["check_set_id"] = identity
                packet, at = checks._packet(c, identity, authority.environment)
                stages, attempts = checks._stages(c, identity, packet, at)
                # Every terminal/unknown change belongs to the optimistic snapshot.
                from src.commands import postgres_check_observations as observations

                observations.validate(c, authority.environment)
                evidence = {
                    stage: dict(
                        attempt=attempt,
                        observation=observations._observation(c, identity, stage, attempt)
                        if attempt
                        else None,
                        terminal=checks._terminal(c, attempt) if attempt else None,
                    )
                    for stage, attempt in attempts.items()
                }
                item["stages"] = dict(statuses=stages, evidence_sha256=fingerprint(evidence))
                try:
                    with admission.expected_domain_failures():
                        admission.runner_context(
                            authority,
                            c,
                            command.command_id,
                            resolve,
                            version=version,
                            state=state,
                            policy=policy,
                            now=now,
                        )
                        lease = shared_lease(
                            c,
                            value,
                            admission.owner_for(command, c=c),
                            now=now,
                            environment=authority.environment,
                        )
                        packet, outcomes, proof = admission.verified_completion(
                            c,
                            identity,
                            value,
                            owner=admission.owner_for(command, c=c),
                            fence=lease["fence"],
                            state=state,
                            policy=policy,
                            now=now,
                            environment=authority.environment,
                        )
                    item.update(
                        disposition="valid",
                        completion_sha256=proof["completion_sha256"],
                        blocked_reasons=[],
                    )
                    verified[slot["slot"]] = (value, packet, outcomes, proof)
                except CommandError as exc:
                    item.update(disposition="ineligible", blocked_reasons=[exc.code])
            else:
                item.update(disposition="not_checked", blocked_reasons=["check_request_not_found"])
        rows.append(item)
    snapshot = dict(
        schema_version=1,
        job_id=job_id,
        slate_sha256=p._sha(p._canonical(job)),
        preferred_slot=1,
        state_version=version,
        policy_sha256=fingerprint(policy),
        context=job["context"],
        slots=rows,
    )
    return snapshot, verified


def admit(
    authority,
    c,
    state,
    version,
    command,
    actor,
    *,
    now,
    policy,
    editorial_policy,
    resolve_principal,
    clock_now=None,
    **unused,
):
    authorize(actor, command.action)
    refs = command.payload
    refuse(
        not policy.enabled and policy.epoch is None and now < utc_datetime(command.expires_at),
        "important_command_expired",
    )
    job_id = refs["slate_id"]
    job = read(c, JOB, job_id)
    refuse(refs["slate_sha256"] == p._sha(p._canonical(job)), "important_job_changed")
    refuse(
        refs["expected_state_version"] == version
        and refs["expected_policy_sha256"] == fingerprint(editorial_policy),
        "important_context_changed",
    )
    refuse(not exists(c, ADMISSION, job_id), "important_membership_sealed")
    snapshot, verified = completion_snapshot(
        authority, c, job_id, state, version, editorial_policy, now, resolve_principal
    )
    refuse(
        fingerprint(snapshot) == refs["expected_completion_set_sha256"],
        "important_completion_conflict",
    )
    refuse(bool(verified), "important_no_valid_candidate")
    winner = min(verified)
    candidates = []
    texts = set()
    for slot, (value, packet, outcomes, proof) in sorted(verified.items()):
        text = packet["derivation"]["final_text"]
        if text in texts:
            continue
        texts.add(text)
        candidates.append(
            dict(
                rank=slot,
                text=text,
                source="retained_important_writer",
                score=None,
                provenance=dict(
                    schema_version=1,
                    job_id=job_id,
                    slot=slot,
                    admission_input_id=admission.identity_for(value),
                    admission_input_sha256=p._sha(p._canonical(value)),
                    candidate_id=value["candidate_id"],
                    derivation_id=packet["derivation_id"],
                    plan_sha256=value["plan_sha256"],
                    custom_id=value["custom_id"],
                    receipt_id=value["receipt_id"],
                    completion_sha256=proof["completion_sha256"],
                    check_set_id=proof["check_set_id"],
                    bundle_sha256=fingerprint(value["bundle"]),
                    memory_sha256=fingerprint(value["memory"]),
                    policy_sha256=fingerprint(editorial_policy),
                ),
            )
        )
    value, packet, outcomes, proof = verified[winner]
    args = value["save"]
    context = deepcopy(args["review_context"] or {})
    context["two_bot"] = dict(
        signal_kind=value["bundle"]["signal_kind"],
        bundle=deepcopy(value["bundle"]),
        fact_check=outcomes["fact_check"],
        critic=outcomes["critic"],
        required_checks_binding=proof,
        reviewed_text_sha256=text_hash(packet["derivation"]["final_text"]),
        reviewed_bundle_sha256=fingerprint(value["bundle"]),
        reviewed_policy_sha256=fingerprint(editorial_policy),
        cited_impact=packet["candidate"].get("cited_impact"),
        human_impact=value["bundle"].get("human_impact"),
    )
    plan = admission.plan_draft_admission(
        state,
        text=packet["derivation"]["final_text"],
        tweet_type=args["legacy_type"],
        event_id=args["event_id"],
        draft_id=draft_id(authority.environment, job_id),
        at=now,
        editorial_policy=editorial_policy,
        place_facts=admission.resolve_admission_place_facts(state, args["event_id"]),
        score=args["score"],
        review_context=context,
        candidates=candidates,
        evaluator_metadata=args["evaluator_metadata"],
        city=args["city"],
        tweet_date=args["tweet_date"],
        cooldown_exempt=args["cooldown_exempt"],
    )
    refuse(plan.draft is not None, plan.reason or "candidate_admission_refused")
    assert plan.draft is not None
    fresh = clock_now() if clock_now else now
    refuse(fresh < utc_datetime(command.expires_at), "command_expired")
    fresh_actor = resolve_principal(command.actor_subject)
    refuse(
        fresh_actor is not None
        and fresh_actor.subject == actor.subject
        and fresh_actor.authentication_context == actor.authentication_context,
        "forbidden",
    )
    authorize(fresh_actor, command.action)
    fresh_snapshot, fresh_verified = completion_snapshot(
        authority, c, job_id, state, version, editorial_policy, fresh, resolve_principal
    )
    refuse(fresh_snapshot == snapshot, "important_completion_changed")
    # The second full validation may block. Gather immutable bounds and current
    # principals first, then take the final clock sample without another proof
    # reconstruction or lease acquisition that could hide elapsed time.
    allowance = read(c, ALLOWANCE, job["allowance_id"])
    lease = read(c, LEASE, job_id)
    check_commands = []
    for retained, _, _, _ in fresh_verified.values():
        requested = admission.request_for(authority, c, retained)
        refuse(requested is not None, "check_request_not_found")
        check_commands.append(requested[0])
    for checked_command in [command, *check_commands]:
        principal = resolve_principal(checked_command.actor_subject)
        refuse(
            principal is not None
            and principal.subject == checked_command.actor_subject
            and principal.authentication_context == checked_command.authentication_context,
            "forbidden",
        )
        authorize(principal, checked_command.action)
    origin = resolve_principal(job["authorized_subject"])
    refuse(
        origin is not None
        and origin.subject == job["authorized_subject"]
        and origin.authentication_context == job["authentication_context"],
        "forbidden",
    )
    authorize(origin, "request_important_variants")
    deadline = min(
        *(utc_datetime(item.expires_at) for item in [command, *check_commands]),
        utc_datetime(allowance["valid_until"]),
        utc_datetime(job["source_useful_until"]),
        utc_datetime(job["useful_until"]),
        utc_datetime(lease["expires_at"]),
        *(utc_datetime(item[1]["useful_until"]) for item in fresh_verified.values()),
    )
    ended = clock_now() if clock_now else fresh
    refuse(
        fresh <= ended
        and ended.date() == fresh.date()
        and all(ended < utc_datetime(item.expires_at) for item in [command, *check_commands])
        and utc_datetime(allowance["valid_from"]) <= ended < utc_datetime(allowance["valid_until"])
        and ended < utc_datetime(job["source_useful_until"])
        and ended < utc_datetime(job["useful_until"])
        and ended < utc_datetime(lease["expires_at"])
        and all(
            ended < utc_datetime(item[1]["useful_until"])
            and item[1]["check_date"] == utc_text(ended)[:10]
            for item in fresh_verified.values()
        ),
        "important_final_window_changed",
    )
    fresh = ended
    _record_verified_checks_review(plan.draft, policy=editorial_policy, at=utc_text(fresh))
    membership = dict(
        schema_version=1,
        job_id=job_id,
        slate_sha256=refs["slate_sha256"],
        admission_command_id=command.command_id,
        draft_id=plan.draft["id"],
        selected_slot=winner,
        completion_snapshot=snapshot,
        candidates=candidates,
        proofs={str(candidate["rank"]): verified[candidate["rank"]][3] for candidate in candidates},
        state_version=version,
        policy_sha256=fingerprint(editorial_policy),
        admitted_at=utc_text(fresh),
    )
    record(c, ADMISSION, job_id, membership)
    retain_source(c, plan.draft, command, job_id, job, membership, value)
    return admission.Transition(
        admission.Reduction(plan.state, plan.changed_ids, (admission._identity(plan.draft),)),
        dict(
            outcome="slate_admitted",
            draft_id=plan.draft["id"],
            slate_id=job_id,
            selected_slot=winner,
            admission_sha256=p._sha(p._canonical(membership)),
            publication_approved=False,
            accounting_complete=False,
            cost_usd=None,
        ),
        completed_at=fresh,
        final_window=(deadline, utc_text(fresh)[:10]),
    )


def retain_source(c, draft, command, job_id, job, membership, value):
    from src.two_bot import check_origin as origin

    document = dict(
        schema_version=3,
        origin_kind=ORIGIN,
        draft_id=draft["id"],
        event_id=draft["event_id"],
        admission_command_id=command.command_id,
        job_id=job_id,
        slate_sha256=p._sha(p._canonical(job)),
        admission_sha256=p._sha(p._canonical(membership)),
        admission_input_id=admission.identity_for(value),
        admission_input_sha256=p._sha(p._canonical(value)),
        brief_id=job["brief_id"],
        plan_sha256=job["plan_sha256"],
        bundle_sha256=fingerprint(value["bundle"]),
        memory_sha256=fingerprint(value["memory"]),
        source_useful_until=job["source_useful_until"],
        provenance_useful_until=job["useful_until"],
    )
    record(c, origin.SOURCE_NAMESPACE, fingerprint(dict(draft_id=draft["id"])), document)


def source(c, draft, identity, receipt, document):
    """Historical genuine group lineage; current text/review is checked separately."""
    from src.commands.postgres_authority import _command, _decode
    from src.commands import postgres_checks as checks
    from src.two_bot import check_origin as origin

    fields = {
        "schema_version",
        "origin_kind",
        "draft_id",
        "event_id",
        "admission_command_id",
        "job_id",
        "slate_sha256",
        "admission_sha256",
        "admission_input_id",
        "admission_input_sha256",
        "brief_id",
        "plan_sha256",
        "bundle_sha256",
        "memory_sha256",
        "source_useful_until",
        "provenance_useful_until",
    }
    refuse(
        set(document) == fields
        and type(document["schema_version"]) is int
        and document["schema_version"] == 3
        and document["origin_kind"] == ORIGIN
        and document["draft_id"] == draft["id"]
        and document["event_id"] == draft["event_id"],
        "important_source_changed",
    )
    job_id = document["job_id"]
    job = read(c, JOB, job_id)
    membership = read(c, ADMISSION, job_id)
    captured = read(c, CAPTURE, job_id)
    refuse(
        set(membership)
        == {
            "schema_version",
            "job_id",
            "slate_sha256",
            "admission_command_id",
            "draft_id",
            "selected_slot",
            "completion_snapshot",
            "candidates",
            "proofs",
            "state_version",
            "policy_sha256",
            "admitted_at",
        }
        and p._sha(p._canonical(job)) == document["slate_sha256"] == membership["slate_sha256"]
        and p._sha(p._canonical(membership)) == document["admission_sha256"]
        and membership["draft_id"] == draft["id"]
        and membership["admission_command_id"] == document["admission_command_id"]
        and membership["job_id"] == job_id,
        "important_membership_changed",
    )
    row = c.execute(
        "SELECT i.command_bytes,i.digest,r.result_bytes,r.digest FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s",
        (document["admission_command_id"],),
    ).fetchone()
    refuse(row is not None, "important_admission_missing")
    command, result = _command(row[0], row[1]), _decode(row[2], row[3])
    refuse(
        command.action == "admit_checked_slate"
        and result["status"] == "applied"
        and result["candidate"]["draft_id"] == draft["id"]
        and command.payload["slate_id"] == job_id
        and command.payload["slate_sha256"] == document["slate_sha256"]
        and command.payload["expected_completion_set_sha256"]
        == fingerprint(membership["completion_snapshot"])
        and result["candidate"]["admission_sha256"] == document["admission_sha256"],
        "important_admission_changed",
    )
    registration = batch.read(c, job_id, environment="local")
    from src.commands.batch_journal import _plan

    plan = _plan(batch._plan_bytes(c, registration["plan_sha256"]), registration["plan_sha256"])
    allowance = contract_call(contract.allowance_document, read(c, ALLOWANCE, job["allowance_id"]))
    brief = generation.document(read(c, generation.INPUT, job["brief_id"]))
    # Historical provenance must still join the original successful generation
    # command and its immutable event claim, without requiring today's config.
    original = c.execute(
        "SELECT i.command_bytes,i.digest,r.result_bytes,r.digest FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s",
        (job["command_id"],),
    ).fetchone()
    refuse(original is not None, "important_generation_missing")
    generation_command, generation_result = (
        _command(original[0], original[1]),
        _decode(original[2], original[3]),
    )
    claim = read(c, CLAIM, claim_id(brief, job["brief_id"]))
    refuse(
        generation_command.action == "request_important_variants"
        and generation_command.actor_subject == job["authorized_subject"]
        and generation_command.authentication_context == job["authentication_context"]
        and generation_command.payload["brief_id"] == job["brief_id"]
        and generation_command.payload["allowance_id"] == job["allowance_id"]
        and generation_result["status"] == "applied"
        and generation_result["generation"]["job_id"] == job_id
        and generation_result["generation"]["slate_sha256"] == document["slate_sha256"]
        and generation_result["generation"]["plan_sha256"] == document["plan_sha256"]
        and claim
        == dict(
            schema_version=1,
            job_id=job_id,
            command_id=job["command_id"],
            brief_id=job["brief_id"],
            allowance_id=job["allowance_id"],
        ),
        "important_generation_changed",
    )
    lease = read(c, LEASE, job_id)
    refuse(
        plan["schema_version"] == 2
        and plan["allowance"] == allowance
        and plan["allowance_sha256"] == job["allowance_id"]
        and plan["policy"] == job["policy"]
        and plan["bundle"] == brief["bundle"]
        and plan["memory"] == job["memory"]
        and plan["useful_until"] == document["provenance_useful_until"] == job["useful_until"]
        and brief["useful_until"] == document["source_useful_until"] == job["source_useful_until"]
        and job["brief_id"] == document["brief_id"]
        and registration["plan_sha256"] == document["plan_sha256"] == job["plan_sha256"],
        "important_source_changed",
    )
    retained_rows = membership["candidates"]
    refuse(
        1 <= len(retained_rows) <= 2
        and draft.get("candidates") == retained_rows
        and set(membership["proofs"]) == {str(candidate["rank"]) for candidate in retained_rows},
        "important_candidates_changed",
    )
    selected = None
    for candidate in retained_rows:
        provenance = candidate["provenance"]
        slot = next((s for s in captured["slots"] if s["slot"] == candidate["rank"]), None)
        refuse(
            slot is not None
            and slot["candidate"] is not None
            and candidate["source"] == "retained_important_writer"
            and candidate["score"] is None,
            "important_member_changed",
        )
        assert slot is not None  # Already checked above; keep type narrowing explicit.
        value = admission.read_input(c, slot["candidate"])
        packet, _ = checks._packet(c, provenance["check_set_id"], "local")
        stage_proofs, _ = checks.verified_stage_receipts(
            c,
            provenance["check_set_id"],
            packet,
            owner=lease["owner"],
            fence=lease["fence"],
            environment="local",
        )
        proof = admission.completion_proof(provenance["check_set_id"], value, packet, stage_proofs)
        expected = dict(
            schema_version=1,
            job_id=job_id,
            slot=slot["slot"],
            admission_input_id=admission.identity_for(value),
            admission_input_sha256=p._sha(p._canonical(value)),
            candidate_id=value["candidate_id"],
            derivation_id=packet["derivation_id"],
            plan_sha256=value["plan_sha256"],
            custom_id=value["custom_id"],
            receipt_id=value["receipt_id"],
            completion_sha256=proof["completion_sha256"],
            check_set_id=proof["check_set_id"],
            bundle_sha256=fingerprint(value["bundle"]),
            memory_sha256=fingerprint(value["memory"]),
            policy_sha256=fingerprint(plan["policy"]),
        )
        refuse(
            provenance == expected
            and proof == membership["proofs"][str(slot["slot"])]
            and candidate["text"] == packet["derivation"]["final_text"]
            and value["bundle"] == brief["bundle"]
            and value["memory"] == job["memory"],
            "important_member_changed",
        )
        if slot["slot"] == membership["selected_slot"]:
            selected = value
    refuse(
        selected is not None
        and admission.identity_for(selected) == document["admission_input_id"]
        and p._sha(p._canonical(selected)) == document["admission_input_sha256"]
        and fingerprint(selected["bundle"]) == document["bundle_sha256"]
        and fingerprint(selected["memory"]) == document["memory_sha256"]
        and draft.get("review_context", {}).get("two_bot", {}).get("bundle") == selected["bundle"],
        "important_source_changed",
    )
    return (
        dict(
            namespace=origin.SOURCE_NAMESPACE,
            snapshot_id=identity,
            canonical_sha256=receipt.canonical_sha256,
        ),
        document,
        selected,
    )


def candidate_inputs(authority, c):
    if not callable(getattr(authority, "important_variants_configuration", None)):
        return []
    identity = configuration(authority)["allowance_id"]
    allowance = contract_call(contract.allowance_document, read(c, ALLOWANCE, identity))
    rows: list[str] = []
    for job_id in generation.jobs_for(c, allowance["brief_id"], JOB):
        if exists(c, CAPTURE, job_id):
            rows.extend(
                s["candidate"]["admission_input_id"]
                for s in read(c, CAPTURE, job_id)["slots"]
                if s["candidate"] is not None
            )
    refuse(len(rows) <= 2, "important_candidate_capacity")
    return rows


def writer_usage(authority, c, job_id, now):
    """One actual group hold and fieldwise observations for both retained items."""
    from src.two_bot import retained_usage

    job = read(c, JOB, job_id)
    registered = batch.read(c, job_id, environment=authority.environment)
    index = results.index(
        c, {"job_id": job_id}, now=utc_text(now), environment=authority.environment
    )
    ids = [slot["custom_id"] for slot in job["slots"]]
    row = dict(
        job_id=job_id,
        custom_ids=ids,
        receipt_id=index["chosen_receipt_id"],
        intent_id=registered["intent_id"],
        reservation_state=registered["reservation_state"],
        usage_status="absent",
        counts={
            key: None for key in retained_usage.CONTRACT["counts"]["anthropic"] if "tokens" in key
        },
        cost_usd=None,
        cost_status="unreconciled",
    )
    if row["receipt_id"] is not None:
        receipt = next(
            item
            for item in results._receipts(c, job_id, index["submission"]["grant_id"])
            if item["receipt_id"] == row["receipt_id"]
        )
        observed = retained_usage.important_batch(
            receipt["results"],
            ids,
            stage="writer",
            model=job["policy"]["models"]["writer"],
            observed_at=receipt["recorded_at"],
        )
        row.update(
            usage_status=observed["status"],
            counts={key: observed["counts"][key] for key in row["counts"]},
        )
    return row


def project_brief(authority, c, row, state, version, policy, now):
    if not callable(getattr(authority, "important_variants_configuration", None)):
        return row
    identity = configuration(authority)["allowance_id"]
    allowance = contract_call(contract.allowance_document, read(c, ALLOWANCE, identity))
    if allowance["brief_id"] != row["brief_id"]:
        return row
    row.update(
        execution_mode="important_batch",
        allowance_id=identity,
        allowance_sha256=identity,
        importance_reason=allowance["importance_reason"],
    )
    try:
        current(authority, c, identity, state, policy, now)
        row["status"] = "ready"
        row.pop("reason", None)
        brief = generation.read(c, generation.INPUT, row["brief_id"])
        claim = claim_id(brief, row["brief_id"])
        if exists(c, CLAIM, claim):
            saved = read(c, CLAIM, claim)
            job_id = saved["job_id"]
            retained = worker.apply(
                c,
                "status",
                {"job_id": job_id},
                now=utc_text(now),
                environment=authority.environment,
            )
            status = {
                "registered": "queued",
                "reserved": "queued",
                "ready": "queued",
                "submitted": "submitted",
            }.get(retained["state"], "reconciliation_required")
            captured = read(c, CAPTURE, job_id) if exists(c, CAPTURE, job_id) else None
            outcome = captured_outcome(captured) if captured is not None else dict(outcome=status)
            row.update(
                job_id=job_id,
                status=outcome["outcome"],
                writer_usage=writer_usage(authority, c, job_id, now),
            )
            if "reason" in outcome:
                row["reason"] = outcome["reason"]
    except CommandError as exc:
        row.update(status="blocked", reason=exc.code)
    return row


def project_candidate(authority, c, row, value, state, version, policy, now, resolve):
    if not is_group(c, value.get("job_id"), environment=authority.environment):
        return row
    job_id = value["job_id"]
    row.update(important_slate=True)
    if exists(c, ADMISSION, job_id):
        saved = read(c, ADMISSION, job_id)
        row.update(
            status="admitted", saved_draft_id=saved["draft_id"], required_checks_completed=False
        )
        return row
    try:
        snapshot, verified = completion_snapshot(
            authority, c, job_id, state, version, policy, now, resolve
        )
        row.update(
            slate_id=job_id,
            slate_sha256=snapshot["slate_sha256"],
            expected_completion_set_sha256=fingerprint(snapshot),
            slate_can_admit=bool(verified),
            slate_members=snapshot["slots"],
        )
    except CommandError as exc:
        row.update(slate_can_admit=False, slate_reason=exc.code)
    return row
