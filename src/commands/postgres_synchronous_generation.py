"""One source-bound writer grant, retained response and shared candidate lifecycle.

All writes compose with the existing authority transaction/pointer lock. Raw
receipt retention is passive; current-source checks gate every new paid action
and interpretation. No response, status read or restart grants another POST.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import base64
import re

from src.commands import postgres_sourced_generation as generation, postgres_spending as spend
from src.commands import postgres_candidate_admission as admission
from src.commands.schema import authorize, utc_datetime, utc_text
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from src.two_bot import writer, negative_cache, synchronous_origin as origin
from src.two_bot.sourced_generation import identity, source_bundle, refuse
from src.two_bot.synchronous_writer import WriterDispatchGrant, execute_writer_once, _request_bytes

JOB = "sourced-sync-job-v1"
ATTEMPT = "sourced-sync-attempt-v1"
OBSERVATION = "sourced-sync-observation-v1"
RESOLUTION = "sourced-sync-resolution-v1"
JOB_FIELDS = {"schema_version", "origin_kind", "generation_id", "brief_id", "brief_sha256", "created_at", "useful_until", "samples",
    "context", "bundle", "memory", "policy", "request", "request_sha256", "reservation", "intent_id", "negative_cache_input_sha", "negative_cache_epoch"}
ATTEMPT_FIELDS = {"schema_version", "generation_id", "job_sha256", "intent_id", "request_sha256", "wire_sha256", "wire_base64", "method",
    "endpoint", "grant_id", "actor_subject", "authentication_context", "granted_at", "brief_sha256", "policy_sha256", "allowance_sha256"}
OBS_FIELDS = {"schema_version", "generation_id", "grant_id", "request_sha256", "wire_sha256", "raw_sha256", "raw_base64", "byte_count",
    "http_status", "complete", "reason", "observed_at"}
INPUT_FIELDS = {"schema_version", "origin_kind", "generation_id", "grant_id", "observation_sha256", "resolution_sha256", "request_sha256",
    "candidate_id", "bundle", "memory", "save", "current_context", "state_version", "state_sha256", "captured_at"}


def digest(value):
    return p._sha(p._canonical(value))


def job(c, identity):
    value = generation.read(c, JOB, identity)
    p._require(type(value) is dict and set(value) == JOB_FIELDS and type(value["schema_version"]) is int and value["schema_version"] == 1
        and value["origin_kind"] == origin.ORIGIN and value["generation_id"] == identity and type(value["samples"]) is int and value["samples"] == 1,
        "changed_sync_job")
    brief = generation.document(generation.read(c, generation.INPUT, value["brief_id"]))
    p._require(brief["urgent"] is True and digest(brief) == value["brief_id"] == value["brief_sha256"]
        and value["bundle"] == brief["bundle"] and fingerprint(value["bundle"]) == value["context"]["bundle_sha256"]
        and fingerprint(value["memory"]) == value["context"]["memory_sha256"] and fingerprint(value["policy"]) == value["context"]["policy_sha256"]
        and identity == "gss_"+fingerprint(dict(brief_id=value["brief_id"], **value["context"]))
        and value["intent_id"] == "writer_"+identity[4:] and digest(value["request"]) == value["request_sha256"], "changed_sync_job")
    created, deadline = utc_datetime(value["created_at"]), utc_datetime(value["useful_until"])
    p._require(created >= utc_datetime(brief["captured_at"]) and deadline == min(utc_datetime(brief["useful_until"]), created+timedelta(days=7))
        and (deadline-created).total_seconds() > 600 and len(p._canonical(value)) <= 2_000_000, "changed_sync_job_window")
    origin.sha(value["negative_cache_input_sha"])
    p._require(type(value["negative_cache_epoch"]) is str and 0 < len(value["negative_cache_epoch"]) <= 256, "changed_sync_cache_identity")
    hold = spend._record(c, value["intent_id"])
    p._require(hold is not None and hold["intent"] == reservation(value), "changed_sync_reservation")
    return value


def reservation(value):
    return dict(value["reservation"], intent_id=value["intent_id"], job_id=value["generation_id"], request_sha256=value["request_sha256"],
        provider="anthropic", role="writer", model=value["policy"]["models"]["writer"])


def prepare(c, value, config, state, policy, now, environment):
    from src.commands.postgres_sync_checks import upgraded
    refuse(upgraded(c), "sync_check_migration_required")
    bundle, memory, context, key = identity(value, state, policy, now=now, epoch=admission.PAUSED_EPOCH)
    identity_value = "gss_"+key
    reserve = config["reservations"]["synchronous"]
    if generation.exists(c, JOB, identity_value):
        saved = job(c, identity_value)
        refuse(saved["context"] == context and saved["reservation"] == reserve, "generation_job_changed")
        reused = True
    else:
        deadline = min(utc_datetime(value["useful_until"]), now+timedelta(days=7))
        refuse((deadline-now).total_seconds() > 600, "generation_window_or_request_invalid")
        request = writer.anthropic_writer_request(writer.build_writer_user_prompt(bundle, memory))
        raw = _request_bytes(request)
        refuse(policy["models"]["writer_provider"] == "anthropic" and request["model"] == policy["models"]["writer"], "generation_model_changed")
        saved = dict(schema_version=1, origin_kind=origin.ORIGIN, generation_id=identity_value, brief_id=digest(value), brief_sha256=digest(value),
            created_at=utc_text(now), useful_until=utc_text(deadline), samples=1, context=context, bundle=value["bundle"], memory=memory.to_dict(),
            policy=policy, request=request, request_sha256=p._sha(raw), reservation=reserve, intent_id="writer_"+key,
            negative_cache_input_sha=negative_cache.bundle_fingerprint(bundle, state, now=now), negative_cache_epoch=negative_cache.decision_epoch())
        refuse(len(p._canonical(saved)) <= 2_000_000, "generation_request_bound")
        from src.commands.spend_journal import SpendError
        try:
            spend.apply(c, "reserve", reservation(saved), now=utc_text(now), environment=environment)
        except SpendError as exc:
            if str(exc) not in {"spending_allowance_exhausted", "spend_limits_not_configured"}:
                raise
            refuse(False, str(exc))
        generation.record(c, JOB, identity_value, saved)
        reused = False
    return dict(brief_id=saved["brief_id"], generation_id=identity_value, execution_mode="synchronous", intent_id=saved["intent_id"],
        request_sha256=saved["request_sha256"], generation_status="reused" if reused else "queued")


def runner_identity(authority, c, command_id):
    stored, completed = authority._intent(c, command_id), authority._result(c, command_id)
    refuse(stored is not None and completed is not None and completed.get("status") == "applied"
        and stored[0].action == "request_sourced_generation", "generation_not_accepted")
    refs = completed["generation"]
    refuse(refs.get("execution_mode") == "synchronous", "generation_mode_mismatch")
    value = job(c, refs["generation_id"])
    refuse(value["brief_id"] == refs["brief_id"] and value["request_sha256"] == refs["request_sha256"], "generation_job_changed")
    return stored[0], refs, value


def active(authority, c, command_id, resolve, state, policy, now):
    command, refs, saved = runner_identity(authority, c, command_id)
    actor = resolve(command.actor_subject)
    refuse(actor is not None and actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context, "forbidden")
    authorize(actor, command.action)
    value, config = generation.current(authority, c, saved["brief_id"], policy, now)
    _, _, context, _ = identity(value, state, policy, now=now, epoch=admission.PAUSED_EPOCH)
    refuse(saved["context"] == context and saved["reservation"] == config["reservations"]["synchronous"]
        and now < utc_datetime(saved["useful_until"]) and (state.get("publication_control") or {}).get("enabled") is not True, "generation_context_changed")
    return command, saved, value


def attempt(c, saved):
    if not generation.exists(c, ATTEMPT, saved["generation_id"]):
        p._require(spend._record(c, saved["intent_id"])["state"] == "reserved", "sync_dispatch_without_attempt")
        return None
    value = generation.read(c, ATTEMPT, saved["generation_id"])
    p._require(type(value) is dict and set(value) == ATTEMPT_FIELDS and type(value["schema_version"]) is int and value["schema_version"] == 1, "changed_sync_attempt")
    wire = base64.b64decode(value["wire_base64"], validate=True)
    from src.commands.preview_ingress import strict_json
    p._require(0 < len(wire) <= 2_000_000 and p._sha(wire) == value["wire_sha256"] and strict_json(wire) == saved["request"]
        and value["generation_id"] == saved["generation_id"] and value["job_sha256"] == digest(saved)
        and value["intent_id"] == saved["intent_id"] and value["request_sha256"] == saved["request_sha256"]
        and value["brief_sha256"] == saved["brief_sha256"] and value["policy_sha256"] == saved["context"]["policy_sha256"]
        and value["allowance_sha256"] == saved["reservation"]["estimate_sha256"]
        and value["method"] == "POST" and value["endpoint"] == "anthropic_messages_v1"
        and value["grant_id"] == fingerprint({k:v for k,v in value.items() if k not in {"grant_id", "wire_base64"}}), "changed_sync_attempt")
    dispatched = c.execute("SELECT recorded_at FROM theheat_spending.events WHERE intent_id=%s AND kind='dispatched'", (saved["intent_id"],)).fetchone()
    p._require(dispatched == (spend._time(value["granted_at"]),), "changed_sync_dispatch")
    return value


def begin(c, saved, command, wire, now, environment, state, brief):
    from src.commands.preview_ingress import strict_json
    refuse(type(wire) is bytes and 0 < len(wire) <= 2_000_000 and strict_json(wire) == saved["request"], "generation_wire_changed")
    if attempt(c, saved) is not None:
        return None
    # The cache can change after reservation or SDK construction. Only a new
    # dispatch needs this locked-state gate; original raw/replay stays passive.
    refuse(not negative_cache.should_skip(state, brief["save"]["event_id"], source_bundle(brief["bundle"]), now=now),
        "generation_negative_cache")
    result = spend.apply(c, "dispatch", {"intent_id":saved["intent_id"]}, now=utc_text(now), environment=environment)
    refuse(result["dispatch_granted"] is True, "generation_grant_unavailable")
    value = dict(schema_version=1, generation_id=saved["generation_id"], job_sha256=digest(saved), intent_id=saved["intent_id"],
        request_sha256=saved["request_sha256"], wire_sha256=p._sha(wire), wire_base64=base64.b64encode(wire).decode(), method="POST",
        endpoint="anthropic_messages_v1", actor_subject=command.actor_subject, authentication_context=command.authentication_context,
        granted_at=utc_text(now), brief_sha256=saved["brief_sha256"], policy_sha256=saved["context"]["policy_sha256"], allowance_sha256=saved["reservation"]["estimate_sha256"])
    value["grant_id"] = fingerprint({k:v for k,v in value.items() if k != "wire_base64"})
    refuse(len(p._canonical(value)) <= 3_000_000, "generation_grant_bound")
    generation.record(c, ATTEMPT, saved["generation_id"], value)
    return WriterDispatchGrant(value["grant_id"], value["request_sha256"], value["wire_sha256"])


def observation(c, saved):
    granted = attempt(c, saved)
    if granted is None or not generation.exists(c, OBSERVATION, granted["grant_id"]):
        return granted, None, None
    value = generation.read(c, OBSERVATION, granted["grant_id"])
    p._require(type(value) is dict and set(value) == OBS_FIELDS and type(value["schema_version"]) is int and value["schema_version"] == 1, "changed_sync_observation")
    raw = base64.b64decode(value["raw_base64"], validate=True)
    p._require(type(value["byte_count"]) is int and value["byte_count"] == len(raw) <= 131072 and p._sha(raw) == value["raw_sha256"]
        and all(value[k] == granted[k] for k in ("generation_id", "grant_id", "request_sha256", "wire_sha256"))
        and type(value["complete"]) is bool and value["complete"] == (value["reason"] == "received")
        and value["reason"] in {"received", "transport_unavailable", "size_exceeded", "time_exceeded", "unsupported_content_encoding", "cleanup_failed"}
        and (value["http_status"] is None or type(value["http_status"]) is int and 100 <= value["http_status"] <= 599)
        and utc_datetime(value["observed_at"]) >= utc_datetime(granted["granted_at"]), "changed_sync_observation")
    return granted, value, raw


def retain(c, saved, response, now, environment):
    granted = attempt(c, saved)
    if granted is None:
        return
    if response.grant_status == "granted":
        refuse(response.grant_id == granted["grant_id"] and p._sha(response.wire) == granted["wire_sha256"], "generation_observation_mismatch")
        value = dict(schema_version=1, generation_id=saved["generation_id"], grant_id=granted["grant_id"], request_sha256=saved["request_sha256"],
            wire_sha256=granted["wire_sha256"], raw_sha256=p._sha(response.raw), raw_base64=base64.b64encode(response.raw).decode(), byte_count=len(response.raw),
            http_status=response.http_status, complete=response.complete, reason=response.reason, observed_at=utc_text(now))
        generation.record(c, OBSERVATION, granted["grant_id"], value)
        observation(c, saved)
    if not response.complete:
        spend.apply(c, "uncertain", {"intent_id":saved["intent_id"]}, now=utc_text(now), environment=environment)


def interpret(saved, granted, observed, raw):
    from src.commands.preview_ingress import strict_json
    from src.two_bot.batch_contract import interpret_writer_message
    from src.two_bot.usage_observations import observe_response
    row: dict = dict(message_id=None, usage=None, usage_status="missing", cost_usd=None, blocked_reasons=[], candidate=None, eligible_for_checks=False)
    message = None
    try:
        message = strict_json(raw)
    except (ValueError, UnicodeError):
        pass
    usage = observe_response("writer", message, None, "anthropic")
    verdict = None
    if observed["complete"] and observed["http_status"] == 200 and type(message) is dict:
        try:
            interpret_writer_message(message, saved["policy"]["models"]["writer"], row)
            if row["eligible_for_checks"] or row["blocked_reasons"] == ["writer_kill"]:
                verdict = asdict(writer._parse_writer_json(message["content"][0]["text"]))
        except (ValueError, TypeError, KeyError):
            row["eligible_for_checks"] = False
    candidate_id = fingerprint(dict(origin_kind=origin.ORIGIN, generation_id=saved["generation_id"], grant_id=granted["grant_id"],
        observation_sha256=digest(observed), candidate=verdict)) if row["eligible_for_checks"] else None
    disposition = "candidate" if candidate_id else "writer_kill" if verdict else "ineligible"
    return dict(schema_version=1, generation_id=saved["generation_id"], observation_sha256=digest(observed), parser_version="writer_message_v1",
        disposition=disposition, writer_result=verdict, candidate_id=candidate_id,
        usage=dict(grant_id=granted["grant_id"], observation_sha256=digest(observed), usage_status=usage["usage_status"], counts=usage["counts"], cost_usd=None, cost_status="unreconciled"),
        observed_at=observed["observed_at"])


def resolution(c, saved):
    granted, observed, raw = observation(c, saved)
    refuse(observed is not None, "generation_result_unavailable")
    computed = interpret(saved, granted, observed, raw)
    if generation.exists(c, RESOLUTION, saved["generation_id"]):
        retained = generation.read(c, RESOLUTION, saved["generation_id"])
        p._require(retained == computed, "changed_sync_resolution")
    return computed


def resolve(c, saved, value, state, version, now):
    computed = resolution(c, saved)
    if generation.exists(c, RESOLUTION, saved["generation_id"]):
        return computed
    if computed["disposition"] == "writer_kill":
        verdict = computed["writer_result"]
        updated = deepcopy(state)
        negative_cache.record_result(updated, value["save"]["event_id"], source_bundle(value["bundle"]), dict(
            cacheable=verdict["kill_scope"] == "evidence" and verdict["kill_code"] in negative_cache.EVIDENCE_KILL_CODES,
            kill_scope=verdict["kill_scope"], kill_code=verdict["kill_code"], kill_stage="writer", kill_reason=verdict["kill_reason"],
            negative_cache_input_sha=saved["negative_cache_input_sha"], negative_cache_epoch=saved["negative_cache_epoch"]), now=utc_datetime(computed["observed_at"]))
        if updated != state:
            from src.commands.postgres_authority import NAMESPACE
            refuse(version < p.MAX_INTEGER, "authority_version_exhausted")
            generation.record(c, NAMESPACE, str(version+1), updated)
            c.execute("UPDATE theheat_commands.state SET version=%s,snapshot_id=%s WHERE singleton=1", (version+1, str(version+1)))
    generation.record(c, RESOLUTION, saved["generation_id"], computed)
    return computed


def input_id(value):
    return fingerprint({k:value[k] for k in ("origin_kind", "generation_id", "candidate_id")})


def input_document(value):
    refuse(type(value) is dict and set(value) == INPUT_FIELDS and type(value["schema_version"]) is int and value["schema_version"] == 2
        and value["origin_kind"] == origin.ORIGIN, "invalid_admission_inputs")
    for key in origin.REFERENCES - {"generation_id"} | {"state_sha256"}:
        origin.sha(value[key])
    refuse(type(value["generation_id"]) is str and re.fullmatch(r"gss_[0-9a-f]{64}", value["generation_id"])
        and type(value["state_version"]) is int and 0 <= value["state_version"] <= p.MAX_INTEGER, "invalid_admission_identity")
    utc_datetime(value["captured_at"])
    admission._save(value["save"], value["bundle"])
    raw = p._canonical(value)
    refuse(len(raw) <= admission.MAX_INPUT_BYTES, "admission_input_bound")
    return raw


def verify_candidate(c, value):
    saved = job(c, value["generation_id"])
    granted, observed, _ = observation(c, saved)
    result = resolution(c, saved)
    p._require(generation.exists(c, RESOLUTION, saved["generation_id"]), "sync_resolution_not_retained")
    refuse(result["disposition"] == "candidate" and value["candidate_id"] == result["candidate_id"]
        and value["grant_id"] == granted["grant_id"] and value["observation_sha256"] == digest(observed)
        and value["resolution_sha256"] == digest(result) and value["request_sha256"] == saved["request_sha256"]
        and value["bundle"] == saved["bundle"] and value["memory"] == saved["memory"]
        and value["current_context"] == saved["context"], "candidate_input_mismatch")
    return dict(candidate=result["writer_result"], candidate_id=result["candidate_id"], eligible_for_checks=True)


def capture(c, saved, brief, state, version, policy, now):
    result = resolve(c, saved, brief, state, version, now)
    if result["disposition"] != "candidate":
        return dict(terminal=True, reason=result["disposition"], cost_usd=None)
    if generation.exists(c, generation.CAPTURE, saved["generation_id"]):
        return generation.read(c, generation.CAPTURE, saved["generation_id"])
    granted, observed, _ = observation(c, saved)
    value = dict(schema_version=2, origin_kind=origin.ORIGIN, generation_id=saved["generation_id"], grant_id=granted["grant_id"],
        observation_sha256=digest(observed), resolution_sha256=digest(result), request_sha256=saved["request_sha256"], candidate_id=result["candidate_id"],
        bundle=saved["bundle"], memory=saved["memory"], save=brief["save"], current_context=saved["context"], state_version=version,
        state_sha256=p._sha(p._canonical(state)), captured_at=utc_text(now))
    input_document(value)
    verify_candidate(c, value)
    receipt = generation.record(c, admission.NAMESPACE, input_id(value), value)
    refs = dict(origin_kind=origin.ORIGIN, admission_input_id=input_id(value), admission_input_sha256=receipt.canonical_sha256,
        generation_id=saved["generation_id"], candidate_id=result["candidate_id"], expected_state_version=version, expected_policy_sha256=fingerprint(policy))
    generation.record(c, generation.CAPTURE, saved["generation_id"], refs)
    return refs


def execute(authority, command_id, resolver, *, operation, clock, transport_factory):
    from src.editorial.policy import current_editorial_policy
    refuse(operation in {"write", "capture", "interpret"}, "generation_operation_refused")
    def transaction(action, wire=None, response=None):
        with authority.projections._connection(writing=action != "context") as c:
            authority._validate(c)
            version, state = authority._state(c, lock=True)
            policy = current_editorial_policy()
            # Connection, catalog validation and pointer locking can block.
            # Authorization always uses a fresh trusted clock after that work.
            now = utc_datetime(clock())
            if action == "retain":
                _, _, saved = runner_identity(authority, c, command_id)
                return retain(c, saved, response, now, authority.environment)
            command, saved, brief = active(authority, c, command_id, resolver, state, policy, now)
            if action == "context":
                return saved, attempt(c, saved)
            if action == "begin":
                return begin(c, saved, command, wire, now, authority.environment, state, brief)
            if action == "interpret":
                return resolve(c, saved, brief, state, version, now)
            return capture(c, saved, brief, state, version, policy, now)
    if operation in {"capture", "interpret"}:
        result = transaction(operation)
        if operation == "interpret":
            return dict(outcome=result["disposition"], usage=result["usage"], publication_approved=False)
        return dict(outcome="terminal" if result.get("terminal") else "candidate_ready", candidate=None if result.get("terminal") else result,
            reason=result.get("reason"), publication_approved=False)
    saved, granted = transaction("context")
    if granted is not None:
        return dict(outcome="reconciliation_required", publication_approved=False)
    # Explicit fixture capability only; never discover a production key/client.
    refuse(callable(transport_factory), "synchronous_transport_unavailable")
    options = transport_factory()
    refuse(type(options) is dict and set(options) == {"api_key", "http_transport"} and options["http_transport"] is not None,
        "synchronous_transport_unavailable")
    response = execute_writer_once(saved["request"], authorize=lambda wire:transaction("begin", wire=wire), enabled=True, **options)
    transaction("retain", response=response)
    return dict(outcome="response_retained" if response.grant_status == "granted" else "reconciliation_required", publication_approved=False)


def project(c, identity):
    result = dict(generation_id=identity, status="ready", writer_usage=None)
    if not generation.exists(c, JOB, identity):
        return result
    saved = job(c, identity)
    granted, observed, raw = observation(c, saved)
    result["status"] = "queued" if granted is None else "reconciliation_required"
    if observed is not None:
        interpreted = interpret(saved, granted, observed, raw)
        result["writer_usage"] = dict(interpreted["usage"], generation_id=identity, intent_id=saved["intent_id"],
            reservation_state=spend._record(c, saved["intent_id"])["state"])
        result["status"] = "result_retained"
    if generation.exists(c, RESOLUTION, identity):
        retained = resolution(c, saved)
        result["status"] = "result_retained" if retained["disposition"] == "candidate" else "terminal"
        result["reason"] = None if retained["disposition"] == "candidate" else retained["disposition"]
    if generation.exists(c, generation.CAPTURE, identity):
        result["status"] = "candidate_ready"
    return result


def current_candidate(authority, c, value, state, policy, now, resolve_principal=None):
    saved = job(c, value["generation_id"])
    granted = attempt(c, saved)
    refuse(granted is not None and callable(resolve_principal), "authorization_unavailable")
    actor = resolve_principal(granted["actor_subject"])
    refuse(actor is not None and actor.subject == granted["actor_subject"]
        and actor.authentication_context == granted["authentication_context"], "forbidden")
    authorize(actor, "request_sourced_generation")
    brief, config = generation.current(authority, c, saved["brief_id"], policy, now)
    _, _, context, _ = identity(brief, state, policy, now=now, epoch=admission.PAUSED_EPOCH)
    refuse(context == saved["context"] and config["reservations"]["synchronous"] == saved["reservation"]
        and now < utc_datetime(saved["useful_until"]), "generation_context_changed")
    return verify_candidate(c, value)


def source_document(draft, command, refs, value, saved, brief):
    return dict(schema_version=2, origin_kind=origin.ORIGIN, draft_id=draft["id"], event_id=draft["event_id"],
        admission_command_id=command.command_id, admission_input_id=refs["admission_input_id"], admission_input_sha256=refs["admission_input_sha256"],
        **{k:value[k] for k in origin.REFERENCES}, brief_id=saved["brief_id"], bundle_sha256=fingerprint(value["bundle"]),
        memory_sha256=fingerprint(value["memory"]), source_useful_until=brief["useful_until"], provenance_useful_until=saved["useful_until"])


def retain_source(c, draft, command, refs, value):
    from src.two_bot.check_origin import SOURCE_NAMESPACE
    verify_candidate(c, value)
    saved = job(c, value["generation_id"])
    brief = generation.document(generation.read(c, generation.INPUT, saved["brief_id"]))
    generation.record(c, SOURCE_NAMESPACE, fingerprint({"draft_id":draft["id"]}), source_document(draft, command, refs, value, saved, brief))


def source(c, draft, identity, receipt, value):
    from src.commands.postgres_authority import _command, _decode
    from src.two_bot.check_origin import SOURCE_NAMESPACE
    row = c.execute("SELECT i.command_bytes,i.digest,r.result_bytes,r.digest FROM theheat_commands.intents i JOIN theheat_commands.results r USING(command_id) WHERE i.command_id=%s", (value["admission_command_id"],)).fetchone()
    p._require(row is not None, "draft_source_admission_missing")
    command, result = _command(row[0], row[1]), _decode(row[2], row[3])
    p._require(command.action == "admit_checked_candidate" and result["status"] == "applied" and result["candidate"]["draft_id"] == draft["id"], "changed_draft_source_admission")
    captured = admission.read_input(c, command.payload)
    verify_candidate(c, captured)
    saved = job(c, captured["generation_id"])
    brief = generation.document(generation.read(c, generation.INPUT, saved["brief_id"]))
    p._require(value == source_document(draft, command, command.payload, captured, saved, brief)
        and p._canonical(draft.get("review_context", {}).get("two_bot", {}).get("bundle")) == p._canonical(captured["bundle"]), "changed_draft_source_origin")
    return dict(namespace=SOURCE_NAMESPACE, snapshot_id=identity, canonical_sha256=receipt.canonical_sha256), value, captured
