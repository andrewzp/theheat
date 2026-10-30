"""Real source-effect helper and authority consumer; invented in-memory SQL only."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.commands import postgres_ghcn_source_results as ghcn, postgres_source_results as source
from src.commands.command_roles import RoleError, require_transitions
from src.commands.schema import Command, CommandError, utc_text
from src.data.temperature_history import retained_claims
from src.storage.ghcn_runtime_inputs import apply_effects
from tests.live_content_harness import trap_network
from tests.remaining_campaign.test_recovery_command_guard import fake_pg
from tests.test_command_authority import EDITOR, NOW, request
from tests.test_ghcn_time_integrity import draft


@pytest.fixture(autouse=True)
def no_external_transport(monkeypatch):
    trap_network(monkeypatch.setattr)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No real database in source transition fixtures")

    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr("src.storage.postgres_projection._driver", forbidden)


def source_command(action="commit_ghcn_source_run", **extra):
    payload: dict[str, Any] = dict(supply_run_id=str(uuid4()), supply_sha256="a" * 64,
                   runtime_input_sha256="b" * 64, expected_policy_sha256="c" * 64)
    if action == ghcn.ACTION:
        payload.update(dependency_sha256="d" * 64)
    else:
        payload.update(expected_episode_heads={})
    body = request([], action, {**payload, **extra})
    body["expires_at"] = utc_text(NOW + timedelta(minutes=5))
    return Command.from_request(body, EDITOR, environment="local", now=NOW)


def source_effect(state):
    updated = deepcopy(state)
    claim = retained_claims(state)[0]
    apply_effects(updated, [dict(kind="claim_finding", claim=claim,
        reason="current_archive_comparator_changed", source_revision="e" * 64,
        retrieved_at="2026-10-30T12:00:00Z", details={"invented": "comparator changed"})])
    changed = [new["id"] for old, new in zip(state["drafts"], updated["drafts"]) if old != new]
    return source.SourceTransition(updated, True, {"changed_draft_ids": changed, "reused": False}, NOW)


def consuming(monkeypatch, *, action=ghcn.ACTION, alteration=None):
    original = draft()
    other = draft(sid="USW00000001")
    state = {"drafts": [original, other], "publish_ledger": {}}
    cmd = source_command(action)
    authority, memory = fake_pg(monkeypatch, state, cmd)
    authority.ghcn_baseline = object()
    monkeypatch.setattr(ghcn, "preflight", lambda *_args: SimpleNamespace(command_id=cmd.command_id, command_digest=cmd.digest))
    with authority.projections._connection(writing=True) as connection:
        connection.transaction = nullcontext

    def prepared(*_args, **_kwargs):
        # Real material-history helper, not a handcrafted pending draft. The
        # upstream replay/ownership proof is covered by the existing PG tests.
        transition = source_effect(state)
        if alteration:
            alteration(transition)
        return transition

    monkeypatch.setattr(ghcn if action == ghcn.ACTION else source, "prepare", prepared)
    # Invented durable acceptance; this test owns the post-prepare consumer
    # boundary, not source submission/replay or real database setup.
    memory.accepted = True
    return authority, memory, state, cmd


def test_verified_source_invalidation_reaches_actual_authority_consumer(monkeypatch):
    authority, memory, before, cmd = consuming(monkeypatch)
    result = authority.consume(lambda _subject: EDITOR, command_id=cmd.command_id, now=NOW)
    assert result["status"] == "applied" and result["state_version"] == 1
    affected, other = memory.state["drafts"]
    assert result["source_run"]["changed_draft_ids"] == [affected["id"]]
    assert affected["status"] == "pending" and "approval_binding" not in affected
    assert affected["approval_mode"] == "manual" and "review_binding" not in affected
    assert affected["text"] == before["drafts"][0]["text"]
    assert affected["revision_history"][0]["draft_snapshot"] == before["drafts"][0]
    # The source helper retains the old intent as evidence; it is not approval.
    assert affected["publish_intent_id"] == before["drafts"][0]["publish_intent_id"]
    assert other == before["drafts"][1]


def clear_proof(transition):
    transition.outcome["changed_draft_ids"] = []


def unowned(transition):
    transition.state["drafts"][1]["status"] = "pending"


@pytest.mark.parametrize("alteration", [
    clear_proof, unowned,
    lambda t: t.state["drafts"].pop(),
    lambda t: t.state["drafts"][0].update(status="rejected"),
    lambda t: t.state["drafts"][1].update(status="posted"),
    lambda t: t.state["drafts"][0].update(approval_binding={}),
    lambda t: t.state["drafts"][0].update(approved_at="2026-10-30T12:00:00Z"),
    lambda t: t.state["drafts"][0].update(approval_mode="armed_auto"),
    lambda t: t.outcome.update(reused=True),
])
def test_faulty_source_effect_cannot_escape_computed_invalidation(monkeypatch, alteration):
    authority, memory, before, cmd = consuming(monkeypatch, alteration=alteration)
    with pytest.raises(RuntimeError, match="transition_not_allowed"):
        authority.consume(lambda _subject: EDITOR, command_id=cmd.command_id, now=NOW)
    assert memory.state == before and memory.result is None
    assert not any(sql.startswith("UPDATE") for sql in memory.writes)


def test_nhc_source_commit_does_not_gain_ghcn_draft_invalidation(monkeypatch):
    authority, memory, before, cmd = consuming(monkeypatch, action=source.ACTION)
    with pytest.raises(RuntimeError, match="transition_not_allowed"):
        authority.consume(lambda _subject: EDITOR, command_id=cmd.command_id, now=NOW)
    assert memory.state == before and memory.result is None


@pytest.mark.parametrize("action, prior, status", [
    (ghcn.ACTION, "pending", "approved"),
    (ghcn.ACTION, "rejected", "pending"),
    (ghcn.ACTION, "posted", "pending"),
    (ghcn.ACTION, "approved", "rejected"),
    ("request_sourced_generation", "approved", "pending"),
    ("edit_revision", "approved", "pending"),
])
def test_even_computed_ids_do_not_grant_other_transitions(action, prior, status):
    before = {"drafts": [{"id": "invented", "status": prior}]}
    after = {"drafts": [{"id": "invented", "status": status, "approval_mode": "manual"}]}
    with pytest.raises(RoleError, match="cannot change another draft"):
        require_transitions(before, after, action, source_invalidation_ids=("invented",))


@pytest.mark.parametrize("key", ["changed_draft_ids", "source_invalidation_ids"])
def test_caller_payload_cannot_supply_source_invalidation_proof(key):
    with pytest.raises(CommandError):
        source_command(**{key: ["invented-target"]})
