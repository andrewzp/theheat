"""GHCN raw replay before the shared lock; exact effects inside its transaction."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import time

from src.commands import postgres_delivery as delivery, postgres_source_results as shared
from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.storage import ghcn_runtime_inputs as inputs, postgres_projection as p
from src.storage.cyclone_supply import digest, environment, freeze, require, sha, uuid
from src.storage.scientific_supply import ScientificSupplySession, _row, _outcome, model

ACTION = "commit_ghcn_source_run"
PREPARATION_SECONDS = 120
TABLE_COLUMNS = {
    "intents": "intent_id,command_id,draft_id,event_id,proposal_sha256,artifact_sha",
    "work_items": "work_id,intent_id,platform",
    "leases": "work_id,stage,fence,owner,recorded_at,expires_at",
    "attempts": "attempt_id,work_id,stage,fence,binding_sha,request_sha",
    "observations": "observation_id,attempt_id,metadata_sha,raw_sha",
    "receipts": "observation_id,artifact_sha",
}


def configured(authority):
    environment(authority.projections)
    require(authority.environment == "local" and type(getattr(authority, "ghcn_baseline", None)) is inputs.Baseline,
            "ghcn_source_result_unavailable")
    return authority.ghcn_baseline


def delivery_dependency(authority, c, targets):
    """Caller owns the existing singleton pointer lock, including empty predicates."""
    if not delivery.upgraded(c):
        p._require(c.execute("SELECT to_regnamespace('theheat_delivery')").fetchone()[0] is None,
                   "delivery_intermediate_catalog")
        return dict(catalog=None, rows={}, artifacts=[], outcomes={}, protection_codes=[])
    delivery.validate(c, authority.environment)
    upgrade = c.execute("SELECT sha FROM theheat_commands.delivery_upgrade WHERE singleton=1").fetchone()[0]
    catalog = c.execute("SELECT version,migration_sha,catalog_sha,environment,owner_role,runtime_role FROM theheat_delivery.metadata WHERE singleton=1").fetchone()
    rows = {}
    count = 0
    def select(table, where, arguments):
        nonlocal count
        result = c.execute(f"SELECT {TABLE_COLUMNS[table]} FROM theheat_delivery.{table} WHERE {where} ORDER BY 1,2 LIMIT 4097", arguments).fetchall()
        count += len(result)
        require(count <= 4096, "ghcn_delivery_row_capacity")
        rows[table] = [list(row) for row in result]
        return result
    intent_rows = select("intents", "draft_id=ANY(%s) OR event_id=ANY(%s)",
                         ([d["id"] for d in targets], [d["event_id"] for d in targets]))
    require(len(intent_rows) <= 1024, "ghcn_delivery_intent_capacity")
    work = select("work_items", "intent_id=ANY(%s)", ([r[0] for r in intent_rows],))
    select("leases", "work_id=ANY(%s)", ([r[0] for r in work],))
    attempts = select("attempts", "work_id=ANY(%s)", ([r[0] for r in work],))
    observations = select("observations", "attempt_id=ANY(%s)", ([r[0] for r in attempts],))
    receipts = select("receipts", "observation_id=ANY(%s)", ([r[0] for r in observations],))
    hashes = sorted({r[5] for r in intent_rows} | {x for r in attempts for x in r[4:6]}
                    | {x for r in observations for x in r[2:4]} | {r[1] for r in receipts})
    require(len(hashes) <= 2048, "ghcn_delivery_artifact_capacity")
    artifacts = c.execute("SELECT sha,byte_count,octet_length(payload) FROM theheat_delivery.artifacts WHERE sha=ANY(%s) ORDER BY sha", (hashes,)).fetchall()
    p._require(len(artifacts) == len(hashes) and all(type(r[1]) is int and r[1] == r[2] for r in artifacts), "changed_delivery_artifact")
    require(sum(r[1] for r in artifacts) <= 32 * 1024**2, "ghcn_delivery_byte_capacity")
    for digest_, size, _ in artifacts:
        delivery.raw(c, digest_, bound=size)
    outcomes = {}
    for row in intent_rows:
        value = delivery.read(c, row[0])
        outcomes[row[0]] = {platform:{stage:delivery.outcome(c, delivery.attempt(c, value, platform, stage))
                                    for stage in stages} for platform, stages in delivery.STAGES.items()}
    protection = []
    for target in targets:
        try:
            delivery.hold(c, target)
        except CommandError as exc:
            if exc.code not in {"delivery_prior_outcome_unknown", "delivery_event_already_confirmed"}:
                raise
            protection.append(dict(draft_id=target["id"], event_id=target["event_id"], code=exc.code))
    return freeze(dict(catalog=dict(upgrade_sha256=upgrade, metadata=list(catalog)), rows=rows,
                       artifacts=[list(row[:2]) for row in artifacts], outcomes=outcomes, protection_codes=protection))


def dependency_context(authority, c, state, version):
    baseline = configured(authority)
    dependencies = inputs.state_dependencies(state)
    return dict(schema_version=1, captured_state_version=version, state=dependencies,
        delivery=delivery_dependency(authority, c, dependencies["targets"]),
        policy_sha256=digest(current_editorial_policy()), configuration=inputs.configuration(),
        baseline_pins=dict(database_sha256=baseline.database_sha256, manifest_sha256=baseline.manifest_sha256))


def snapshot(authority):
    configured(authority)
    with authority.projections._connection() as c:
        authority._validate(c)
        version, state = authority._state(c, lock=True)
        return dependency_context(authority, c, state, version)


def read_input(authority, c, run_id, expected=None):
    configured(authority)
    run_id = uuid(run_id)
    found = shared.optional(c, inputs.INPUT, "run:"+run_id)
    require(found is not None, "ghcn_input_not_retained")
    receipt, value = found
    inputs.fixed(value, "schema_version source supply_run_id producer_revision dependency_sha256 baseline supply_sha256 acquisition_started_at acquisition_completed_at duration_ms source_now responses effects effects_sha256 evidence_class")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["source"] == "ghcn-daily"
            and value["supply_run_id"] == run_id and value["evidence_class"] == "invented_local_capture", "ghcn_input_shape")
    require(expected is None or receipt.canonical_sha256 == sha(expected), "ghcn_input_changed")
    start, end = utc_datetime(value["acquisition_started_at"]), utc_datetime(value["acquisition_completed_at"])
    require(start <= utc_datetime(value["source_now"]) <= end and type(value["duration_ms"]) is int
            and 0 <= value["duration_ms"] <= p.MAX_INTEGER, "ghcn_capture_time")
    require(type(value["responses"]) is list and len(value["responses"]) <= inputs.MAX_RECEIPTS
            and all(start <= utc_datetime(row["retrieved_at"]) <= end for row in value["responses"]), "ghcn_response_time")
    require(type(value["effects"]) is list and len(value["effects"]) <= inputs.MAX_EFFECTS
            and digest(value["effects"]) == sha(value["effects_sha256"]), "ghcn_effects_changed")
    dep_receipt, dependencies = p.PostgresProjectionRepository._read(c, inputs.DEPENDENCIES, "run:"+run_id)
    inputs.fixed(dependencies, "schema_version captured_state_version state delivery policy_sha256 configuration baseline_pins")
    require(dep_receipt.canonical_sha256 == sha(value["dependency_sha256"]), "ghcn_dependency_changed")
    inputs.detached_state(dependencies["state"])
    source = ScientificSupplySession(authority.projections, run_id, "replay")
    supply_receipt, bundles, countries, envelope = source.read_on_connection(c)
    require(supply_receipt.canonical_sha256 == sha(value["supply_sha256"])
            and envelope["captured_at"] == value["acquisition_started_at"]
            and envelope["producer_contract"]["git_commit"] == value["producer_revision"], "ghcn_supply_changed")
    return receipt, value, dependencies, bundles, countries, envelope


def read_submission(c, command_id):
    found = shared.optional(c, inputs.SUBMISSION, uuid(command_id))
    require(found is not None, "ghcn_submission_not_retained")
    receipt, value = found
    inputs.fixed(value, "schema_version supply_run_id runtime_input_sha256 request")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1
            and type(value["request"]) is dict and value["request"].get("command_id") == command_id, "ghcn_submission_shape")
    uuid(value["supply_run_id"])
    sha(value["runtime_input_sha256"])
    return receipt, value


@dataclass(frozen=True)
class VerifiedGhcnEffects:
    command_id: str
    command_digest: str
    input_sha256: str
    rows: list
    baseline: dict
    refusal: str | None = None
    reused: bool = False
    valid_until: float = 0.0


def preflight(authority, command_id):
    """No state lock, source request or write. Return only independent derivation."""
    from src.storage.cyclone_supply import CycloneSupplyError
    configured(authority)
    anchor = time.monotonic()
    with authority.projections._connection() as c:
        authority._validate(c)
        if command_id is None:
            row = c.execute("SELECT i.command_id FROM theheat_commands.intents i LEFT JOIN theheat_commands.results r USING(command_id) WHERE r.command_id IS NULL ORDER BY i.sequence LIMIT 1").fetchone()
            command_id = row[0] if row else None
        if command_id is None:
            return None
        intent = authority._intent(c, command_id)
        if intent is None or intent[0].action != ACTION or authority._result(c, command_id) is not None:
            return None
        command = intent[0]
        try:
            receipt, value, deps, _, _, envelope = read_input(authority, c, command.payload["supply_run_id"], command.payload["runtime_input_sha256"])
            prior = shared.optional(c, inputs.RESULT, "run:"+value["supply_run_id"])
            if prior is not None:
                return VerifiedGhcnEffects(command_id, command.digest, receipt.canonical_sha256, [], {}, reused=True, valid_until=anchor+PREPARATION_SECONDS)
            responses = inputs.read_responses(c, value["responses"])
        except CycloneSupplyError as exc:
            return VerifiedGhcnEffects(command_id, command.digest, command.payload["runtime_input_sha256"], [], {}, refusal=str(exc), valid_until=anchor+PREPARATION_SECONDS)
    # Storage/implementation failures stay uncertainty. Only explicit domain
    # refutations return a durable rejection in the eventual locked transaction.
    try:
        require(time.monotonic()-anchor <= PREPARATION_SECONDS, "ghcn_preparation_expired")
        require(deps["configuration"] == inputs.configuration() and deps["policy_sha256"] == digest(current_editorial_policy()), "ghcn_policy_changed")
        baseline = configured(authority)
        require(deps["baseline_pins"] == dict(database_sha256=baseline.database_sha256, manifest_sha256=baseline.manifest_sha256), "ghcn_baseline_changed")
        bundles, countries, metrics, effects, descriptor = inputs.derive(baseline, deps["state"], responses,
            now=value["source_now"], config=deps["configuration"])
        require(descriptor == value["baseline"] and effects == value["effects"], "ghcn_replay_changed")
        require([_row(b, model.ExtremeSignalBundle, decoding=False) for b in bundles] == envelope["bundles"]
            and [_row(r, model.CountryRecord, decoding=False) for r in countries] == envelope["country_records"]
            and (_outcome(metrics) | {"supply_empty":not bundles}) == envelope["source_outcome"], "ghcn_supply_replay_changed")
        require(time.monotonic()-anchor <= PREPARATION_SECONDS, "ghcn_preparation_expired")
        return VerifiedGhcnEffects(command_id, command.digest, receipt.canonical_sha256, effects, descriptor, valid_until=anchor+PREPARATION_SECONDS)
    except CycloneSupplyError as exc:
        return VerifiedGhcnEffects(command_id, command.digest, receipt.canonical_sha256, [], {}, refusal=str(exc), valid_until=anchor+PREPARATION_SECONDS)


def prepare(authority, c, state, version, command, actor, *, now, editorial_policy, prepared):
    configured(authority)
    authorize(actor, command.action)
    require(actor.subject == command.actor_subject and actor.authentication_context == command.authentication_context, "ghcn_actor_changed")
    require(now < utc_datetime(command.expires_at), "ghcn_command_expired")
    require(type(prepared) is VerifiedGhcnEffects and prepared.command_id == command.command_id
            and prepared.command_digest == command.digest and prepared.input_sha256 == command.payload["runtime_input_sha256"], "ghcn_preparation_required")
    require(time.monotonic() <= prepared.valid_until, "ghcn_preparation_expired")
    if prepared.refusal:
        raise CommandError(prepared.refusal, "Retained GHCN evidence is held; no operational effects applied")
    require(command.payload["expected_policy_sha256"] == digest(editorial_policy), "ghcn_policy_changed")
    _, descriptor = read_submission(c, command.command_id)
    require(descriptor["request"] == shared.request_body(command), "ghcn_submission_changed")
    receipt, value, deps, _, _, envelope = read_input(authority, c, command.payload["supply_run_id"], prepared.input_sha256)
    require(value["supply_sha256"] == command.payload["supply_sha256"] and value["dependency_sha256"] == command.payload["dependency_sha256"], "ghcn_capture_changed")
    require(utc_datetime(value["acquisition_completed_at"]) <= now, "ghcn_capture_in_future")
    prior = shared.optional(c, inputs.RESULT, "run:"+value["supply_run_id"])
    if prior:
        require(prior[1]["runtime_input_sha256"] == receipt.canonical_sha256, "ghcn_run_conflict")
        return shared.SourceTransition(state, False, outcome(*prior, reused=True), shared.final_clock(command, now))
    require(not prepared.reused and prepared.rows == value["effects"] and prepared.baseline == value["baseline"], "ghcn_preparation_changed")
    current = dependency_context(authority, c, state, version)
    require({k:v for k,v in current.items() if k != "captured_state_version"}
            == {k:v for k,v in deps.items() if k != "captured_state_version"}, "ghcn_dependency_conflict")
    if delivery.upgraded(c):
        for target in current["state"]["targets"]:
            delivery.hold(c, target)
    prior_health = state.get("source_health", {}).get("ghcn") or {}
    prior_runs = prior_health.get("runs") or []
    require(all(utc_datetime(row["ts"]) <= utc_datetime(value["acquisition_completed_at"]) for row in prior_runs), "ghcn_telemetry_out_of_order")
    at = shared.final_clock(command, now)
    updated = deepcopy(state)
    inputs.apply_effects(updated, prepared.rows)
    # Only the real material-history helper may touch target drafts/history.
    owned = {"temperature_history", "drafts"}
    require({k:v for k,v in state.items() if k not in owned} == {k:v for k,v in updated.items() if k not in owned}, "ghcn_unowned_mutation")
    targets = {d["id"] for d in current["state"]["targets"]}
    require([d for d in state.get("drafts", []) if not isinstance(d, dict) or d.get("id") not in targets]
            == [d for d in updated.get("drafts", []) if not isinstance(d, dict) or d.get("id") not in targets], "ghcn_unowned_draft_mutation")
    changed_ids = [d["id"] for d in updated.get("drafts", []) if isinstance(d, dict) and d.get("id") in targets
                   and d != next(row for row in state["drafts"] if row.get("id") == d["id"])]
    runtime = dict(schema_version=1, source="ghcn-daily", supply_run_id=value["supply_run_id"],
        supply_sha256=value["supply_sha256"], runtime_input_sha256=receipt.canonical_sha256,
        dependency_sha256=value["dependency_sha256"], effects_sha256=value["effects_sha256"],
        command_id=command.command_id, command_digest=command.digest,
        acquisition_started_at=value["acquisition_started_at"], acquisition_completed_at=value["acquisition_completed_at"],
        applied_at=utc_text(at), source_status=envelope["source_outcome"]["status"], status="applied",
        effect_ids=[digest(row) for row in prepared.rows], changed_draft_ids=changed_ids,
        counts=envelope["source_outcome"]["counters"], holds=[])
    raw, fields = p._snapshot(runtime)
    result_receipt = authority.projections._record(c, inputs.RESULT, "run:"+value["supply_run_id"], raw, fields)
    from src.state import record_source_health
    record_source_health(updated, "ghcn", runtime["source_status"], timestamp=value["acquisition_completed_at"],
        metrics=dict(duration_ms=value["duration_ms"], **runtime["counts"]))
    history = updated.setdefault("run_history", [])
    require(type(history) is list, "ghcn_run_history_invalid")
    updated["run_history"] = [dict(id="ghcn-source:"+value["supply_run_id"], mode="local_source_result", status="applied",
        started_at=value["acquisition_started_at"], ended_at=value["acquisition_completed_at"],
        supply_sha256=value["supply_sha256"], runtime_input_sha256=receipt.canonical_sha256,
        result_sha256=result_receipt.canonical_sha256), *history][:20]
    return shared.SourceTransition(updated, updated != state, outcome(result_receipt, runtime), shared.final_clock(command, at))


def outcome(receipt, value, *, reused=False):
    return dict(supply_run_id=value["supply_run_id"], supply_sha256=value["supply_sha256"],
        runtime_input_sha256=value["runtime_input_sha256"], result_sha256=receipt.canonical_sha256,
        result_command_id=value["command_id"], source_status=value["source_status"], status=value["status"],
        changed_draft_ids=value["changed_draft_ids"], reused=reused, provider_request_created=False, publication_enabled=False)


def projection(authority, run_id):
    configured(authority)
    with authority.projections._connection() as c:
        authority._validate(c)
        authority._pointer(c, lock=True)
        receipt, value, _, _, _, envelope = read_input(authority, c, uuid(run_id))
        result = shared.optional(c, inputs.RESULT, "run:"+run_id)
        return outcome(*result) if result else dict(supply_run_id=run_id, runtime_input_sha256=receipt.canonical_sha256,
            status="retained", supply_sha256=value["supply_sha256"], source_status=envelope["source_outcome"]["status"],
            publication_enabled=False)
