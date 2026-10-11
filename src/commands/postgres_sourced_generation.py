"""Local sourced starts using existing batch, spending and candidate authority."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from src.commands import postgres_batch as batch, postgres_batch_results as results, postgres_batch_worker as worker
from src.commands import postgres_candidate_admission as admission
from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.policy import valid_policy
from src.editorial.revisions import fingerprint
from src.storage import postgres_projection as p
from src.two_bot import negative_cache
from src.two_bot.sourced_generation import prepare as prepare_plan, identity as plan_identity, refuse, source_bundle

INPUT = "sourced-generation-input-v1"
RESERVATION = "sourced-generation-reservation-v1"
JOB = "sourced-generation-job-v1"
CAPTURE = "sourced-generation-capture-v1"
RESOLUTION = "sourced-generation-resolution-v1"
MAX_INPUT = 131072
FIELDS = {"schema_version", "source_key", "source_revision", "captured_at", "useful_until", "urgent", "bundle", "save"}
RESERVATION_FIELDS = {"schema_version", "basis", "provider", "role", "model", "policy_sha256",
    "brief_ids", "reserve_micro_usd", "valid_from", "valid_until"}


def configuration(authority):
    load = getattr(authority, "generation_configuration", None)
    refuse(authority.environment == "local" and callable(load), "sourced_generation_unavailable")
    assert callable(load)
    value = p._decode(p._canonical(load()))
    refuse(isinstance(value, dict) and set(value) == {"current_inputs", "reservation"}, "generation_configuration_invalid")
    ids = value["current_inputs"]
    refuse(isinstance(ids, list) and len(ids) <= 16
        and all(isinstance(i, str) and re.fullmatch(r"[a-f0-9]{64}", i) for i in ids)
        and len(set(ids)) == len(ids), "generation_configuration_invalid")
    reserve = value["reservation"]
    refuse(isinstance(reserve, dict) and set(reserve) == {"estimate_sha256", "reserve_micro_usd"}, "generation_reservation_invalid")
    from src.commands.spend_journal import _amount, _sha
    _amount(reserve["reserve_micro_usd"], positive=True)
    _sha(reserve["estimate_sha256"])
    return value


def private_configuration(path):
    """Reread an explicitly named owner-only local file; never discover secrets."""
    path = Path(path)
    refuse(path.is_absolute(), "generation_configuration_invalid")
    def load():
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            meta = os.fstat(stream.fileno())
            refuse(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
                and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_size <= 16384, "generation_configuration_invalid")
            from src.commands.preview_ingress import strict_json
            return strict_json(stream.read(16385))
    return load


def record(c, namespace, identity, value):
    raw, fields = p._snapshot(value)
    return p.PostgresProjectionRepository._record(c, namespace, identity, raw, fields)


def read(c, namespace, identity):
    return p.PostgresProjectionRepository._read(c, namespace, identity)[1]


def exists(c, namespace, identity):
    return c.execute("SELECT 1 FROM theheat_projection.versions WHERE namespace=%s AND snapshot_id=%s", (namespace, identity)).fetchone() is not None


def document(value):
    refuse(isinstance(value, dict) and set(value) == FIELDS and type(value["schema_version"]) is int
        and value["schema_version"] == 1, "generation_input_invalid")
    refuse(len(p._canonical(value)) <= MAX_INPUT, "generation_input_bound")
    for k in ("source_key", "source_revision"):
        refuse(isinstance(value[k], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value[k]), "generation_source_invalid")
    refuse(value["source_key"] != "__init__" and
        (Path(__file__).resolve().parents[1]/"orchestrator"/"sources"/(value["source_key"]+".py")).is_file(),
        "generation_source_unknown")
    refuse(type(value["urgent"]) is bool, "generation_input_invalid")
    refuse(utc_datetime(value["captured_at"]) < utc_datetime(value["useful_until"]), "generation_window_invalid")
    source_bundle(value["bundle"])
    admission._save(value["save"], value["bundle"])
    return value


def reservation_document(value):
    """An invented local allowance, never a price quote or production grant."""
    refuse(isinstance(value, dict) and set(value) == RESERVATION_FIELDS
        and type(value["schema_version"]) is int and value["schema_version"] == 1,
        "generation_reservation_invalid")
    refuse(value["basis"] == "invented_local_allowance" and value["provider"] == "anthropic"
        and value["role"] == "writer", "generation_reservation_invalid")
    refuse(isinstance(value["model"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value["model"])
        and isinstance(value["policy_sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", value["policy_sha256"]),
        "generation_reservation_invalid")
    ids = value["brief_ids"]
    refuse(isinstance(ids, list) and 1 <= len(ids) <= 16
        and all(isinstance(i, str) and re.fullmatch(r"[a-f0-9]{64}", i) for i in ids)
        and len(set(ids)) == len(ids), "generation_reservation_invalid")
    refuse(type(value["reserve_micro_usd"]) is int and 1 <= value["reserve_micro_usd"] <= 10**12,
        "generation_reservation_invalid")
    refuse(utc_datetime(value["valid_from"]) < utc_datetime(value["valid_until"]), "generation_reservation_invalid")
    return value


def current_reservation(c, reserve, identity, policy, now):
    digest = reserve["estimate_sha256"]
    refuse(exists(c, RESERVATION, digest), "generation_reservation_missing")
    value = reservation_document(read(c, RESERVATION, digest))
    refuse(p._sha(p._canonical(value)) == digest, "generation_reservation_mismatch")
    refuse(value["reserve_micro_usd"] == reserve["reserve_micro_usd"]
        and identity in value["brief_ids"] and value["provider"] == policy["models"]["writer_provider"]
        and value["model"] == policy["models"]["writer"] and value["policy_sha256"] == fingerprint(policy),
        "generation_reservation_mismatch")
    refuse(utc_datetime(value["valid_from"]) <= now < utc_datetime(value["valid_until"]), "generation_reservation_expired")


def current(authority, c, identity, policy, now):
    config = configuration(authority)
    refuse(identity in config["current_inputs"], "generation_source_superseded")
    value = document(read(c, INPUT, identity))
    refuse(p._sha(p._canonical(value)) == identity, "generation_input_mismatch")
    # A configuration cannot nominate two current versions of the same event.
    keys = []
    for other in config["current_inputs"]:
        item = document(read(c, INPUT, other))
        keys.append((item["source_key"], item["save"]["event_id"]))
    refuse(len(set(keys)) == len(keys), "generation_configuration_invalid")
    refuse(utc_datetime(value["captured_at"]) <= now < utc_datetime(value["useful_until"]), "generation_source_expired")
    refuse(not value["urgent"], "urgent_input_not_batchable")
    refuse(valid_policy(policy) and policy["flags"]["writer_samples"] == 1
        and policy["flags"]["critic_enabled"] and policy["flags"]["safety_llm_enabled"], "generation_policy_unavailable")
    refuse(os.environ.get("THEHEAT_PRODUCTION_PAUSED") != "1", "production_paused")
    current_reservation(c, config["reservation"], identity, policy, now)
    return value, config


def prepare(authority, c, state, version, command, actor, *, now, policy, editorial_policy):
    authorize(actor, command.action)
    refuse(actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context,
           "generation_actor_changed")
    refuse(not policy.enabled and policy.epoch is None and now < utc_datetime(command.expires_at), "generation_command_expired")
    refs = command.payload
    refuse(refs["expected_state_version"] == version and refs["expected_policy_sha256"] == fingerprint(editorial_policy), "generation_context_changed")
    refuse(refs["brief_id"] == refs["brief_sha256"], "generation_input_mismatch")
    value, config = current(authority, c, refs["brief_id"], editorial_policy, now)
    bundle = source_bundle(value["bundle"])
    refuse(negative_cache.should_skip(state, value["save"]["event_id"], bundle, now=now) is None, "generation_negative_cache")
    _, _, context, key = plan_identity(value, state, editorial_policy, now=now, epoch=admission.PAUSED_EPOCH)
    job = "gs_"+key
    reused = exists(c, JOB, job)
    if reused:
        saved = read(c, JOB, job)
        refuse(saved["brief_id"] == refs["brief_id"] and saved["context"] == context, "generation_job_changed")
        registration = batch.read(c, job, environment=authority.environment)
        refuse(saved["reservation"] == config["reservation"], "generation_reservation_changed")
    else:
        from src.two_bot.batch_contract import BatchContractError
        try:
            raw, memory, _, _ = prepare_plan(value, state, editorial_policy, now=now, epoch=admission.PAUSED_EPOCH)
        except BatchContractError:
            raise CommandError("generation_window_or_request_invalid", "Retained brief cannot enter this batch lane") from None
        sha = hashlib.sha256(raw).hexdigest()
        plan = json.loads(raw)
        reservation = dict(config["reservation"], intent_id="writer_"+key, job_id=job,
            request_sha256=sha, provider="anthropic", model=editorial_policy["models"]["writer"], role="writer")
        from src.commands.spend_journal import SpendError
        try:
            registration = batch.register(c, raw, expected_plan_sha256=sha, reservation=reservation,
                                         now=utc_text(now), environment=authority.environment)
        except SpendError as exc:
            if str(exc) not in {"spending_allowance_exhausted", "spend_limits_not_configured"}:
                raise
            raise CommandError(str(exc), "Generation spending allowance is unavailable") from None
        record(c, JOB, job, dict(brief_id=refs["brief_id"], memory=memory, context=context,
            reservation=config["reservation"], negative_cache_input_sha=negative_cache.bundle_fingerprint(bundle, state, now=now),
            negative_cache_epoch=negative_cache.decision_epoch(), custom_id=plan["requests"][0]["custom_id"]))
    return dict(brief_id=refs["brief_id"], job_id=job, plan_sha256=registration["plan_sha256"],
        intent_id=registration["intent_id"], generation_status="reused" if reused else "queued")


def runner_identity(authority, c, command_id):
    stored = authority._intent(c, command_id)
    completed = authority._result(c, command_id)
    refuse(stored is not None and completed is not None and completed.get("status") == "applied"
        and stored[0].action == "request_sourced_generation", "generation_not_accepted")
    command = stored[0]
    refs = completed["generation"]
    job = read(c, JOB, refs["job_id"])
    refuse(job["brief_id"] == refs["brief_id"], "generation_job_changed")
    return command, refs, job


def runner_context(authority, c, command_id, resolve, state, policy, now):
    command, refs, job = runner_identity(authority, c, command_id)
    try:
        actor = resolve(command.actor_subject)
    except Exception:
        raise CommandError("authorization_unavailable", "Generation operator authorization is unavailable") from None
    refuse(actor is not None, "forbidden")
    authorize(actor, command.action)
    refuse(actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context, "forbidden")
    value, config = current(authority, c, refs["brief_id"], policy, now)
    from src.two_bot.memory import build_memory_slice
    memory = build_memory_slice(deepcopy(state), source_bundle(value["bundle"]), now=now).to_dict()
    refuse(job["brief_id"] == refs["brief_id"] and job["context"] == dict(bundle_sha256=fingerprint(value["bundle"]),
        memory_sha256=fingerprint(memory), policy_sha256=fingerprint(policy), publication_epoch=admission.PAUSED_EPOCH), "generation_context_changed")
    refuse(job["reservation"] == config["reservation"], "generation_reservation_changed")
    return refs, job, value


def capture(authority, c, refs, job, value, state, version, policy, now, owner):
    job_id = refs["job_id"]
    index = results.index(c, {"job_id": job_id}, now=utc_text(now), environment=authority.environment)
    refuse(index["chosen_receipt_id"] is not None, "generation_result_unavailable")
    leased = worker.apply(c, "acquire", dict(job_id=job_id, owner=owner, ttl_seconds=60), now=utc_text(now), environment=authority.environment)
    payload = dict(job_id=job_id, owner=owner, fence=leased["lease"]["fence"], receipt_id=index["chosen_receipt_id"], current_context=job["context"])
    review = results.evaluate(c, payload, now=utc_text(now), environment=authority.environment)
    row = next((row for row in review["report"]["rows"] if row["custom_id"] == job["custom_id"]), None)
    if row is not None and row["blocked_reasons"] == ["writer_kill"]:
        return retain_kill(authority, c, refs, job, value, state, version, now, index, row)
    refuse(row is not None and row["eligible_for_checks"], "generation_candidate_unavailable")
    assert row is not None
    if exists(c, CAPTURE, job_id):
        saved = read(c, CAPTURE, job_id)
        refuse(saved["candidate_id"] == row["candidate_id"], "generation_candidate_changed")
        return saved
    candidate = admission.capture(c, dict(job_id=job_id, custom_id=job["custom_id"], receipt_id=index["chosen_receipt_id"],
        owner=owner, fence=leased["lease"]["fence"], bundle=value["bundle"], memory=job["memory"], save=value["save"]),
        version=version, state=state, policy=policy, now=now, environment=authority.environment)
    record(c, CAPTURE, job_id, candidate)
    return candidate


def retain_kill(authority, c, refs, job, value, state, version, now, index, row):
    from src.commands.postgres_authority import NAMESPACE
    from src.two_bot import writer
    job_id = refs["job_id"]
    receipts = results._receipts(c, job_id, index["submission"]["grant_id"])
    receipt = next(r for r in receipts if r["receipt_id"] == index["chosen_receipt_id"])
    if exists(c, RESOLUTION, job_id):
        saved = read(c, RESOLUTION, job_id)
        refuse(saved["receipt_id"] == receipt["receipt_id"], "generation_result_changed")
        return dict(terminal=True, reason="writer_kill", cost_usd=None)
    parsed = json.loads(receipt["results"])
    verdict = writer._parse_writer_json(parsed["result"]["message"]["content"][0]["text"])
    updated = deepcopy(state)
    disposition = dict(cacheable=verdict.kill_scope == "evidence" and verdict.kill_code in negative_cache.EVIDENCE_KILL_CODES,
        kill_scope=verdict.kill_scope, kill_code=verdict.kill_code, kill_stage="writer", kill_reason=verdict.kill_reason,
        negative_cache_input_sha=job["negative_cache_input_sha"], negative_cache_epoch=job["negative_cache_epoch"])
    negative_cache.record_result(updated, value["save"]["event_id"], source_bundle(value["bundle"]), disposition,
                                 now=utc_datetime(receipt["recorded_at"]))
    if updated != state:
        refuse(version < p.MAX_INTEGER, "authority_version_exhausted")
        record(c, NAMESPACE, str(version+1), updated)
        c.execute("UPDATE theheat_commands.state SET version=%s,snapshot_id=%s WHERE singleton=1", (version+1, str(version+1)))
    record(c, RESOLUTION, job_id, dict(receipt_id=receipt["receipt_id"], recorded_at=utc_text(now),
        negative_cache_updated=updated != state, usage_status=row["usage_status"], cost_usd=None))
    return dict(terminal=True, reason="writer_kill", cost_usd=None)


def writer_usage(authority, c, job_id, now):
    """One chosen receipt's bounded observations; never sum, price or settle."""
    from src.two_bot.usage_observations import CONTRACT, observe_response
    token_keys = [key for key in CONTRACT["counts"]["anthropic"] if "tokens" in key]
    job = read(c, JOB, job_id)
    registered = batch.read(c, job_id, environment=authority.environment)
    index = results.index(c, {"job_id": job_id}, now=utc_text(now), environment=authority.environment)
    row = dict(job_id=job_id, custom_id=job["custom_id"], receipt_id=index["chosen_receipt_id"],
        intent_id=registered["intent_id"], reservation_state=registered["reservation_state"],
        usage_status="absent", counts=dict.fromkeys(token_keys), cost_usd=None, cost_status="unreconciled")
    if row["receipt_id"] is None:
        return row
    receipt = next(item for item in results._receipts(c, job_id, index["submission"]["grant_id"])
                   if item["receipt_id"] == row["receipt_id"])
    try:
        entries = [json.loads(line) for line in receipt["results"].splitlines() if line.strip()]
        matched = [item for item in entries if item.get("custom_id") == job["custom_id"]]
        if len(matched) != 1:
            raise ValueError("ambiguous_usage_row")
        result = matched[0]["result"]
        message = result.get("message") if result.get("type") == "succeeded" else None
        observed = observe_response("writer", message, None, "anthropic")
        row.update(usage_status=observed["usage_status"], counts={key: observed["counts"][key] for key in token_keys})
    except (ValueError, KeyError, TypeError, AttributeError):
        row["usage_status"] = "invalid"
    return row


def project(authority, c, state, version, policy, now):
    if not callable(getattr(authority, "generation_configuration", None)):
        return dict(schema_version=1, enabled=False, disabled_reason="sourced_generation_unavailable", briefs=[])
    config = configuration(authority)
    rows = []
    for identity in config["current_inputs"]:
        value = document(read(c, INPUT, identity))
        row = dict(brief_id=identity, brief_sha256=identity, source_key=value["source_key"],
            event_id=value["save"]["event_id"], signal_kind=value["bundle"]["signal_kind"],
            where=str(value["bundle"]["where"])[:512], when=str(value["bundle"]["when"])[:512],
            captured_at=value["captured_at"], useful_until=value["useful_until"], expected_state_version=version,
            expected_policy_sha256=fingerprint(policy), status="ready", job_id=None, writer_usage=None)
        try:
            current(authority, c, identity, policy, now)
            _, _, _, key = plan_identity(value, state, policy, now=now, epoch=admission.PAUSED_EPOCH)
            job_id = "gs_"+key
            if exists(c, JOB, job_id):
                row["job_id"] = job_id
                saved = worker.apply(c, "status", {"job_id": job_id}, now=utc_text(now), environment=authority.environment)
                row["writer_usage"] = writer_usage(authority, c, job_id, now)
                row["status"] = {"registered": "queued", "ready": "queued", "submitted": "submitted"}.get(saved["state"], "reconciliation_required")
                if exists(c, CAPTURE, job_id):
                    row["status"] = "candidate_ready"
                elif exists(c, RESOLUTION, job_id):
                    row["status"] = "terminal"
        except (CommandError, ValueError):
            row["status"] = "expired" if now >= utc_datetime(value["useful_until"]) else "blocked"
        rows.append(row)
    return dict(schema_version=1, enabled=True, disabled_reason=None, briefs=rows)


def candidates(authority, c):
    identities = []
    for identity in configuration(authority)["current_inputs"]:
        rows = c.execute("""SELECT f.snapshot_id FROM theheat_projection.fields f
            JOIN theheat_projection.artifacts a ON a.sha=f.artifact_sha
            WHERE f.namespace=%s AND f.name_json=%s AND a.payload=%s
            ORDER BY f.snapshot_id LIMIT 17""", (JOB, b'"brief_id"', json.dumps(identity).encode())).fetchall()
        refuse(len(rows) <= 16, "generation_candidate_capacity")
        for (job_id,) in rows:
            refuse(read(c, JOB, job_id)["brief_id"] == identity, "generation_input_mismatch")
            if exists(c, CAPTURE, job_id):
                identities.append(read(c, CAPTURE, job_id)["admission_input_id"])
                refuse(len(identities) <= 16, "generation_candidate_capacity")
    return tuple(identities)
