"""Explicit local NHC result application under the shared command transaction.

Retained typed evidence is not raw acquisition provenance. This path neither
sends provider requests nor changes source discovery or publication controls.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import re

from src.commands.schema import CommandError, authorize, utc_datetime, utc_text
from src.editorial.policy import current_editorial_policy
from src.storage import postgres_projection as p
from src.storage.cyclone_supply import (CycloneSupplyError, CycloneSupplySession,
    digest, environment, freeze, require, sha, uuid)
from src.storage.physical_events import MAX_EPISODES, PhysicalEpisodeSession, episode_id

INPUT = "nhc-source-result-input-v1"
SUBMISSION = "nhc-source-submission-v1"
RESULT = "nhc-source-runtime-result-v1"
ACTION = "commit_nhc_source_run"


def completion_clock():
    return datetime.now(UTC)


def final_clock(command, previous):
    """Outside refusal handling: failure rolls back the whole consumer transaction."""
    at = completion_clock()
    require(at >= previous, "source_clock_regressed")
    require(at < utc_datetime(command.expires_at), "source_command_expired")
    return at


def fixed(value, names):
    require(type(value) is dict and set(value) == set(names.split()), "invalid_source_result")


def configured(authority):
    environment(authority.projections)
    require(authority.environment == "local" and getattr(authority, "source_results_enabled", False) is True,
            "source_result_unavailable")


def optional(c, namespace, key):
    if c.execute(f"SELECT 1 FROM {p.SCHEMA}.versions WHERE namespace=%s AND snapshot_id=%s", (namespace, key)).fetchone() is None:
        return None
    return p.PostgresProjectionRepository._read(c, namespace, key)


def read_input(repository, c, run_id, expected_sha=None):
    uuid(run_id)
    found = optional(c, INPUT, "run:"+run_id)
    require(found is not None, "source_input_not_retained")
    receipt, value = found
    fixed(value, "schema_version source supply_run_id supply_sha256 producer_revision acquisition_started_at acquisition_completed_at duration_ms cities cities_sha256 evidence_class")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["source"] == "nhc"
        and value["supply_run_id"] == run_id and value["evidence_class"] == "invented_local_capture")
    require(expected_sha is None or receipt.canonical_sha256 == sha(expected_sha), "source_input_changed")
    require(type(value["producer_revision"]) is str and re.fullmatch(r"[a-f0-9]{40}", value["producer_revision"]) is not None)
    start, end = utc_datetime(value["acquisition_started_at"]), utc_datetime(value["acquisition_completed_at"])
    require(end >= start and type(value["duration_ms"]) is int and 0 <= value["duration_ms"] <= p.MAX_INTEGER)
    require(type(value["cities"]) is list and len(value["cities"]) <= 50000, "source_geography_bound")
    require(sha(value["cities_sha256"]) == digest(value["cities"]), "source_geography_changed")
    require(optional(c, "cyclone-supply-nhc-v1", "run:"+run_id) is not None, "source_capture_not_retained")
    source = CycloneSupplySession(repository, run_id)
    source_receipt, advisories, envelope = source.read_on_connection(c, expected_sha=sha(value["supply_sha256"]))
    require(envelope["captured_at"] == value["acquisition_started_at"] and envelope["producer_revision"] == value["producer_revision"], "source_capture_changed")
    return receipt, value, source_receipt, advisories, envelope


def retain_exact(repository, namespace, key, value):
    """One read after an unknown commit; no replacement or fresh identity."""
    environment(repository)
    try:
        receipt = repository.record(namespace, key, value)
    except p.ProjectionError as exc:
        if str(exc) != "write_outcome_unknown":
            raise
        receipt, restored = repository.read(namespace, key)
        require(restored == value and receipt.canonical_sha256 == digest(value), "source_retention_unacknowledged")
        return receipt
    checked, restored = repository.read(namespace, key)
    require(checked == receipt and restored == value, "source_retention_unacknowledged")
    return receipt


def retain_input(repository, value):
    """Local producer only; no HTTP upload/mint route exists."""
    environment(repository)
    value = freeze(value)
    fixed(value, "schema_version source supply_run_id supply_sha256 producer_revision acquisition_started_at acquisition_completed_at duration_ms cities cities_sha256 evidence_class")
    # Validate in an isolated transaction before acknowledging the immutable input.
    encoded, fields = p._snapshot(value)
    try:
        with repository._connection(writing=True) as c:
            repository._validate(c)
            repository._record(c, INPUT, "run:"+uuid(value["supply_run_id"]), encoded, fields)
            read_input(repository, c, value["supply_run_id"], digest(value))
    except p.ProjectionError as exc:
        if str(exc) != "write_outcome_unknown":
            raise
        # The exact read below is the sole outcome reconciliation.
    with repository._connection() as c:
        repository._validate(c)
        return read_input(repository, c, value["supply_run_id"], digest(value))[0]


def inventory(advisories):
    return sorted({identity for advisory in advisories if (identity := episode_id(advisory)) is not None})


def read_submission(repository, c, command_id):
    found = optional(c, SUBMISSION, uuid(command_id))
    require(found is not None, "source_submission_not_retained")
    receipt, value = found
    fixed(value, "schema_version supply_run_id runtime_input_sha256 request")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1)
    uuid(value["supply_run_id"])
    sha(value["runtime_input_sha256"])
    require(type(value["request"]) is dict and value["request"].get("command_id") == command_id)
    return receipt, value


def request_body(command):
    row = command.as_dict()
    return {key: row[key] for key in ("command_id", "action", "requested_at", "expires_at", "targets", "payload")}


@dataclass(frozen=True)
class SourceTransition:
    state: dict
    state_changed: bool
    outcome: dict
    completed_at: datetime


def _outcome(receipt, value, *, reused=False):
    return dict(supply_run_id=value["supply_run_id"], supply_sha256=value["supply_sha256"],
        runtime_input_sha256=value["runtime_input_sha256"], result_sha256=receipt.canonical_sha256,
        result_command_id=value["command_id"], status=value["status"], reused=reused,
        draft_mutated=False, provider_request_created=False, publication_enabled=False)


def prepare(authority, c, state, command, actor, *, now, editorial_policy):
    configured(authority)
    authorize(actor, command.action)
    require(command.action == ACTION and actor.subject == command.actor_subject
        and actor.authentication_context == command.authentication_context, "source_actor_changed")
    require(now < utc_datetime(command.expires_at), "source_command_expired")
    payload = command.payload
    require(payload["expected_policy_sha256"] == digest(editorial_policy), "source_policy_changed")
    _, descriptor = read_submission(authority.projections, c, command.command_id)
    require(descriptor["request"] == request_body(command) and descriptor["supply_run_id"] == payload["supply_run_id"]
        and descriptor["runtime_input_sha256"] == payload["runtime_input_sha256"], "source_submission_changed")
    _, value, _, advisories, envelope = read_input(authority.projections, c, payload["supply_run_id"], payload["runtime_input_sha256"])
    require(value["supply_sha256"] == payload["supply_sha256"], "source_capture_changed")
    require(utc_datetime(value["acquisition_completed_at"]) <= now, "source_capture_in_future")
    require(len(inventory(advisories)) <= MAX_EPISODES, "episode_inventory_bound")
    prior = optional(c, RESULT, "run:"+payload["supply_run_id"])
    if prior is not None:
        require(prior[1]["runtime_input_sha256"] == payload["runtime_input_sha256"]
            and prior[1]["supply_sha256"] == payload["supply_sha256"], "source_run_conflict")
        at = completion_clock()
        require(at >= now, "source_clock_regressed")
        require(at < utc_datetime(command.expires_at), "source_command_expired")
        return SourceTransition(state, False, _outcome(*prior, reused=True), at)
    session = PhysicalEpisodeSession(authority.projections)
    episodes = session.apply_retained_run_on_connection(c,
        payload["supply_run_id"], payload["supply_sha256"], operation_id=command.command_id,
        expected_heads=payload["expected_episode_heads"], now=value["acquisition_completed_at"], cities=value["cities"])
    for row in episodes["episodes"]:
        # The deterministic episode locks remain held. Bind this operation's
        # exact resulting revision, never a later readback head's qualifications.
        head = session._head(c, row["episode_id"])
        require(head is not None and head[0].canonical_sha256 == row["revision_sha256"], "source_episode_result_changed")
        holds = head[1]["holds"]
        require(type(holds) is list and len(holds) <= 16 and all(type(code) is str
            and re.fullmatch(r"[a-z_]{1,80}", code) is not None for code in holds), "source_episode_hold_bound")
        row["holds"] = freeze(holds)
    # A fresh trusted clock is required after resolution/locks/derivation. Expiry
    # rolls the domain savepoint back, including every episode and operation.
    at = completion_clock()
    require(at >= now, "source_clock_regressed")
    require(at < utc_datetime(command.expires_at), "source_command_expired")
    require(digest(current_editorial_policy()) == payload["expected_policy_sha256"], "source_policy_changed")
    source_status = envelope["source_outcome"]["status"]
    held = bool(episodes["held"] or any(row["status"] == "held" for row in episodes["episodes"]))
    runtime = dict(schema_version=1, source="nhc", supply_run_id=payload["supply_run_id"], supply_sha256=payload["supply_sha256"],
        runtime_input_sha256=payload["runtime_input_sha256"], command_id=command.command_id, command_digest=command.digest,
        acquisition_started_at=value["acquisition_started_at"], acquisition_completed_at=value["acquisition_completed_at"],
        applied_at=utc_text(at), status="held" if held else "applied", source_status=source_status,
        counts=dict(observed=len(advisories), episodes=len(episodes["episodes"]), writer_attempted=0, drafted=0),
        episodes=episodes["episodes"], held=[dict(reason=reason, count=sum(row["reason"] == reason for row in episodes["held"]))
            for reason in sorted({row["reason"] for row in episodes["held"]})])
    raw, fields = p._snapshot(runtime)
    receipt = authority.projections._record(c, RESULT, "run:"+payload["supply_run_id"], raw, fields)
    updated = deepcopy(state)
    from src.state import record_source_health
    record_source_health(updated, "nhc", source_status, timestamp=value["acquisition_completed_at"],
        metrics=dict(duration_ms=value["duration_ms"], observed=len(advisories), writer_attempted=0, drafted=0))
    history = updated.setdefault("run_history", [])
    require(type(history) is list, "source_history_invalid")
    row = dict(id="nhc-source:"+payload["supply_run_id"], mode="local_source_result", status=runtime["status"],
        started_at=value["acquisition_started_at"], ended_at=value["acquisition_completed_at"],
        supply_sha256=payload["supply_sha256"], runtime_input_sha256=payload["runtime_input_sha256"], result_sha256=receipt.canonical_sha256,
        sources=[dict(source="nhc", status=source_status, duration_ms=value["duration_ms"], observed=len(advisories), writer_attempted=0, drafted=0)])
    updated["run_history"] = [row, *history][:20]
    finished = completion_clock()
    require(finished >= at, "source_clock_regressed")
    require(finished < utc_datetime(command.expires_at), "source_command_expired")
    return SourceTransition(updated, True, _outcome(receipt, runtime), finished)


def projection(authority, run_id):
    configured(authority)
    uuid(run_id)
    with authority.projections._connection() as c:
        authority._validate(c)
        source = CycloneSupplySession(authority.projections, run_id)
        supply_receipt, advisories, envelope = source.read_on_connection(c)
        retained_input = optional(c, INPUT, "run:"+run_id)
        result = optional(c, RESULT, "run:"+run_id)
        value = dict(supply_run_id=run_id, supply_sha256=supply_receipt.canonical_sha256,
            runtime_input_sha256=retained_input[0].canonical_sha256 if retained_input else None,
            status="retained", reason="input_not_acknowledged" if retained_input is None else None,
            acquisition_started_at=envelope["captured_at"], acquisition_completed_at=None,
            source_status=envelope["source_outcome"]["status"], counts=dict(observed=len(advisories)),
            episodes=[], publication_enabled=False, provider_request_created=False)
        if retained_input:
            _, document, *_ = read_input(authority.projections, c, run_id, retained_input[0].canonical_sha256)
            value["acquisition_completed_at"] = document["acquisition_completed_at"]
        if len(inventory(advisories)) > MAX_EPISODES:
            value.update(status="held", reason="episode_inventory_bound")
            return value
        if result:
            runtime = result[1]
            value.update(status=runtime["status"], result_sha256=result[0].canonical_sha256,
                command_id=runtime["command_id"], applied_at=runtime["applied_at"], counts=runtime["counts"], held=runtime["held"])
            session = PhysicalEpisodeSession(authority.projections)
            for row in runtime["episodes"]:
                head = session._head(c, row["episode_id"])
                value["episodes"].append({**row, "current": bool(head and head[0].canonical_sha256 == row["revision_sha256"])})
            return value
        # Descriptors carry a separate exact run field for this bounded join.
        rows = c.execute(f"SELECT snapshot_id FROM {p.SCHEMA}.fields WHERE namespace=%s AND name_json=%s AND artifact_sha=%s ORDER BY snapshot_id LIMIT 17",
            (SUBMISSION, p._canonical("supply_run_id"), digest(run_id))).fetchall()
        if len(rows) > 16:
            value.update(status="held", reason="source_submission_inventory_bound")
            return value
        pending, rejected, unsubmitted = [], [], []
        for (command_id,) in rows:
            _, descriptor = read_submission(authority.projections, c, command_id)
            require(descriptor["supply_run_id"] == run_id, "source_submission_changed")
            intent, terminal = authority._intent(c, command_id), authority._result(c, command_id)
            if terminal:
                rejected.append(dict(command_id=command_id, status=terminal["status"], code=terminal.get("code")))
            elif intent:
                pending.append(command_id)
            else:
                unsubmitted.append(command_id)
        value.update(status="pending" if pending else "rejected" if rejected else "retained",
            pending_commands=pending, rejected_commands=rejected, retained_submissions=unsubmitted)
        return value


@contextmanager
def expected_domain_failures():
    try:
        yield
    except CycloneSupplyError as exc:
        raise CommandError(str(exc), "Retained NHC result cannot be applied; inspect its exact source-run status.") from None
