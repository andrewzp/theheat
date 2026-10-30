"""W13.1/13.2: binding role/command map, transition refusal and identity propagation.

Invented local identities only; no network, Gist, provider or platform calls.
"""
from __future__ import annotations

import json
import os

import pytest

from src.commands import command_roles as roles
from src.commands import reducer as reducer_module
from src.commands import sqlite_authority as sqlite_module
from src.commands.job_authority import ServiceIdentity
from src.commands.schema import ACTIONS, Command, CommandError, Principal, authorize
from tests.test_command_authority import EDITOR, NOW, PUBLISHER, authority, command, request, resolver, story

PRIOR_PUBLISHER_ONLY = {"approve_revision", "schedule_revision", "approve_media_revision"}


def prior_rule(role, action):
    return not (role == "viewer" or (action in PRIOR_PUBLISHER_ONLY and role != "publisher"))


def test_every_existing_action_is_bound_and_the_map_reproduces_the_prior_rule_exactly():
    assert ACTIONS <= set(roles.OPERATOR_COMMANDS)
    for action in sorted(ACTIONS | {"stage_media_proposal", "abandon_submission", "unmapped_internal"}):
        for role in roles.HUMAN_ROLES:
            principal = Principal(f"{role}-w13", role, "verified-local-fixture")
            allowed = prior_rule(role, action)
            assert roles.operator_allowed(role, action) is allowed
            if allowed:
                authorize(principal, action)
            else:
                with pytest.raises(CommandError) as refused:
                    authorize(principal, action)
                assert refused.value.code == "forbidden"
    described = roles.describe()
    assert described["gist_limitations"]["role_separation"] == "unenforceable_on_gist_path"
    assert {row["capability"] for row in described["service_operations"]} >= {"batch.dispatch", "check.complete", "spend.release_unstarted"}


def test_service_roles_and_human_roles_cannot_be_exchanged():
    for role in roles.SERVICE_ROLES:
        with pytest.raises(CommandError):
            Principal("svc", role, "verified-local-fixture")
        assert not roles.operator_allowed(role, "edit_revision")
    for role in roles.HUMAN_ROLES:
        with pytest.raises(CommandError) as refused:
            ServiceIdentity(role, "owner-1")
        assert refused.value.code == "invalid_service_role"
    with pytest.raises(roles.RoleError) as cross:
        roles.service_operation("checker", "batch_work", "begin")
    assert cross.value.code == "cross_role_write_refused"
    with pytest.raises(roles.RoleError) as unmapped:
        roles.service_operation("producer", "batch_work", "rewrite_history")
    assert unmapped.value.code == "unmapped_service_operation"


def state_of(*drafts):
    return {"drafts": [dict(d) for d in drafts]}


@pytest.mark.parametrize("action, before, after, targets, code", [
    ("approve_revision", ("pending",), ("rejected",), ("a",), "transition_not_allowed"),
    ("edit_revision", ("pending", "pending"), ("pending", "approved"), ("a",), "transition_not_allowed"),
    ("record_review", ("approved",), ("approved",), ("a",), "transition_not_allowed"),
    ("admit_checked_candidate", ("pending",), ("pending", "approved"), (), "transition_not_allowed"),
    ("commit_nhc_source_run", ("pending",), ("rejected",), (), "transition_not_allowed"),
    ("reject_revision", ("pending", "pending"), ("rejected",), ("a",), "transition_not_allowed"),
])
def test_out_of_binding_effects_are_refused(action, before, after, targets, code):
    ids = "abc"
    old = state_of(*({"id": ids[i], "status": s} for i, s in enumerate(before)))
    new = state_of(*({"id": ids[i], "status": s} for i, s in enumerate(after)))
    with pytest.raises(roles.RoleError) as refused:
        roles.require_transitions(old, new, action, targets)
    assert refused.value.code == code


@pytest.mark.parametrize("action, before, after, targets", [
    ("approve_revision", ("pending",), ("approved",), ("a",)),
    ("edit_revision", ("approved", "pending"), ("pending", "pending"), ("a",)),
    ("bulk_reject", ("pending", "pending"), ("rejected", "rejected"), ("a", "b")),
    ("admit_checked_candidate", ("pending",), ("pending", "pending"), ()),
    ("approve_media_revision", ("pending",), ("pending",), ("a",)),
])
def test_bound_effects_pass(action, before, after, targets):
    ids = "abc"
    old = state_of(*({"id": ids[i], "status": s} for i, s in enumerate(before)))
    new = state_of(*({"id": ids[i], "status": s} for i, s in enumerate(after)))
    roles.require_transitions(old, new, action, targets)


def test_sqlite_command_boundary_rejects_a_reduction_that_escapes_its_binding(tmp_path, monkeypatch):
    """A faulty or substituted reducer cannot approve through an edit command."""
    first, second = story("w13-a"), story("w13-b")
    store = authority(tmp_path, {"drafts": [first, second]})
    original = reducer_module.reduce_command

    def escaping(state, cmd, principal, **kwargs):
        reduction = original(state, cmd, principal, **kwargs)
        for draft in reduction.state["drafts"]:
            if draft["id"] == "w13-b":
                draft["status"] = "approved"
        return reduction

    monkeypatch.setattr(sqlite_module, "reduce_command", escaping)
    edit = command(first)
    store.accept(edit, EDITOR, now=NOW)
    version_before, state_before = store.read()
    result = store.consume(resolver, command_id=edit.command_id, now=NOW)
    assert result["status"] == "rejected" and result["code"] == "transition_not_allowed"
    assert store.read() == (version_before, state_before)
    monkeypatch.setattr(sqlite_module, "reduce_command", original)
    honest = command(second)
    store.accept(honest, EDITOR, now=NOW)
    assert store.consume(resolver, command_id=honest.command_id, now=NOW)["status"] == "applied"


def test_caller_supplied_actor_labels_never_create_authority(tmp_path):
    draft = story("w13-label")
    store = authority(tmp_path, {"drafts": [draft]})
    body = request(draft)
    for label in ("actor_subject", "role", "reviewer", "authentication_context"):
        with pytest.raises(CommandError) as refused:
            Command.from_request({**body, label: PUBLISHER.subject}, EDITOR, environment="local", now=NOW)
        assert refused.value.code == "invalid_command"
    # A command built for one authenticated subject cannot be accepted as another.
    mine = command(draft)
    with pytest.raises(CommandError) as refused:
        store.accept(mine, PUBLISHER, now=NOW)
    assert refused.value.code == "forbidden"
    # An editor cannot approve even with a body that looks complete.
    reviewed = command(draft, "approve_revision", {"reason": "w13 invented"}, principal=PUBLISHER)
    store.accept(reviewed, PUBLISHER, now=NOW)
    revoked = store.consume(lambda subject: Principal(subject, "editor", "verified-local-fixture"),
                            command_id=reviewed.command_id, now=NOW)
    assert revoked["status"] == "rejected" and revoked["code"] == "forbidden"


def test_preview_operator_file_cannot_grant_a_service_role(tmp_path):
    from src.commands.preview_ingress import Operators
    path = tmp_path / "operators.json"
    path.write_text(json.dumps({"operators": [{"username": "w13", "password": "invented-only",
                                               "subject": "w13-subject", "role": "producer"}]}))
    os.chmod(path, 0o600)
    with pytest.raises(ValueError):
        Operators(path)
    path.write_text(json.dumps({"operators": [{"username": "w13", "password": "invented-only",
                                               "subject": "w13-subject", "role": "editor"}]}))
    os.chmod(path, 0o600)
    operators = Operators(path)
    assert operators.authenticate("Basic " + __import__("base64").b64encode(b"w13:wrong").decode()) is None
    resolved = operators.resolve("w13-subject")
    assert resolved is not None and resolved.role == "editor"
