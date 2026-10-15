"""Actual serialized local absence recovery, with no draft mutation or providers."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest

from src.commands import submission_recovery as recovery
from src.commands.reducer import reduce_command
from src.commands.schema import Command, CommandError, Principal
from src.commands.sqlite_authority import SQLiteAuthority
from tests.test_postgres_projection import (
    cluster as cluster,
    database as database,
    wrap_connections,
)
from tests.test_postgres_command_authority import (
    core as core,
    make_authority as make_authority,
    table_counts,
)
from tests.test_command_authority import EDITOR, NOW, command as make_command, resolver, story


def command(action, payload):
    return make_command(story(), action, payload)


def reference(cmd):
    return dict(
        action=recovery.ACTION, original_action=cmd.action, request_sha256=recovery.request_sha(cmd)
    )


def close(store, cmd, actor=EDITOR, resolve=resolver, **kwargs):
    return store.abandon_submission(
        cmd.command_id, reference(cmd), actor, resolve, now=NOW, **kwargs
    )


def test_absent_expired_deleted_target_closes_without_state_change_and_late_accept_refuses(core):
    store, _, _, params = core
    cmd = command("edit_revision", {"text": "A text that must never be saved."})
    before = store.read()
    result = store.abandon_submission(
        cmd.command_id, reference(cmd), EDITOR, resolver, now=NOW + timedelta(days=2)
    )
    assert result["result"]["code"] == "submission_abandoned"
    assert result["result"]["status"] == "unchanged"
    assert result["result"]["changed_ids"] == result["result"]["identities"] == []
    assert result["result"]["publish_intent_id"] is None
    assert store.read() == before
    assert table_counts(params) == {"intents": 1, "results": 1, "events": 2}
    assert close(store, cmd) == result
    assert store.consume(resolver, now=NOW) is None
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW) == result["result"]
    with pytest.raises(CommandError, match="Command ID already"):
        store.accept(cmd, EDITOR, now=NOW)
    assert store.read() == before


@pytest.mark.parametrize("completed", [False, True])
def test_existing_real_work_is_returned_never_cancelled(core, completed):
    store = core[0]
    cmd = command("edit_revision", {"text": "An actually accepted invented edit."})
    receipt = store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW) if completed else None
    before = store.read(), store.journal(), table_counts(core[3])
    recovered = close(store, cmd)
    assert recovered["receipt"] == receipt and recovered["result"] == result
    assert recovered["status"] == ("completed" if completed else "pending")
    assert recovered["recoverable_command"] == recovery.request(cmd)
    assert (store.read(), store.journal(), table_counts(core[3])) == before


@pytest.mark.parametrize(
    "fault", ["viewer", "other", "digest", "action", "unavailable", "revoked", "context"]
)
def test_reference_and_current_authentication_negatives_leave_everything_unchanged(core, fault):
    store = core[0]
    cmd = command("edit_revision", {"text": "An invented edit."})
    store.accept(cmd, EDITOR, now=NOW)
    body, actor, resolve = reference(cmd), EDITOR, resolver
    if fault == "viewer":
        actor = Principal(EDITOR.subject, "viewer", EDITOR.authentication_context)
    if fault == "other":
        actor = Principal("other-editor", "editor", EDITOR.authentication_context)
        def resolve(_):
            return actor
    if fault == "digest":
        body["request_sha256"] = "f" * 64
    if fault == "action":
        body["original_action"] = "reject_revision"
    if fault == "unavailable":

        def resolve(_):
            raise OSError("offline resolver")

    if fault == "revoked":
        def resolve(_):
            return None
    if fault == "context":
        def resolve(_):
            return Principal(EDITOR.subject, "editor", "other-auth")
    before = store.read(), store.journal(), table_counts(core[3])
    with pytest.raises(CommandError):
        store.abandon_submission(cmd.command_id, body, actor, resolve, now=NOW)
    assert (store.read(), store.journal(), table_counts(core[3])) == before


@pytest.mark.parametrize("stage", ["intent", "accepted", "result", "completed"])
def test_each_partial_tombstone_write_rolls_back(core, monkeypatch, stage):
    store = core[0]
    cmd = command("edit_revision", {"text": "Not saved."})
    before = store.read(), store.journal(), table_counts(core[3])

    def fail(query, c):
        hit = stage == "intent" and query.startswith("INSERT INTO theheat_commands.intents")
        hit |= stage == "result" and query.startswith("INSERT INTO theheat_commands.results")
        if stage in {"accepted", "completed"} and query.startswith(
            "INSERT INTO theheat_commands.events"
        ):
            hit = (
                c.execute(
                    "SELECT count(*) FROM theheat_commands.events WHERE event=%s", (stage,)
                ).fetchone()[0]
                > 0
            )
        if hit:
            raise RuntimeError("injected recovery failure")

    with monkeypatch.context() as patch:
        wrap_connections(patch, after_execute=fail)
        with pytest.raises(RuntimeError, match="injected recovery failure"):
            close(store, cmd)
    assert (store.read(), store.journal(), table_counts(core[3])) == before
    assert close(store, cmd)["result"]["code"] == "submission_abandoned"


def test_lost_ack_reuses_same_tombstone(core, monkeypatch):
    from src.storage.postgres_projection import ProjectionError

    store = core[0]
    cmd = command("edit_revision", {"text": "Not saved."})
    with monkeypatch.context() as patch:
        wrap_connections(patch, lost_ack=True)
        with pytest.raises(ProjectionError, match="write_outcome_unknown"):
            close(store, cmd)
    retained = store.result(cmd.command_id)
    assert close(store, cmd)["result"] == retained
    assert table_counts(core[3]) == {"intents": 1, "results": 1, "events": 2}


@pytest.mark.parametrize("race", ["accept", "consumer", "abandon"])
def test_real_concurrent_absence_resolution_has_one_original_identity(core, race):
    import threading

    store = core[0]
    cmd = command("edit_revision", {"text": "Only accepted work changes this."})
    if race == "consumer":
        store.accept(cmd, EDITOR, now=NOW)
    gate = threading.Barrier(2)

    def left():
        gate.wait()
        return close(store, cmd)

    def right():
        gate.wait()
        if race == "consumer":
            return store.consume(resolver, command_id=cmd.command_id, now=NOW)
        if race == "abandon":
            return close(store, cmd)
        try:
            return store.accept(cmd, EDITOR, now=NOW)
        except CommandError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(left), pool.submit(right)
        closed, other = a.result(), b.result()
    assert table_counts(core[3])["intents"] == 1
    if race == "consumer":
        assert store.result(cmd.command_id) == other and other["status"] == "applied"
        assert closed["result"] in (None, other)
    elif closed["result"] is None:
        assert isinstance(other, dict)
        assert store.consume(resolver, now=NOW)["status"] == "applied"
    else:
        assert closed["result"]["code"] == "submission_abandoned"
        assert store.read()[0] == 0
        assert other == ("command_id_reused" if race == "accept" else closed)


def test_internal_shape_never_grants_generic_ingress_sqlite_or_reducer_permission(core, tmp_path):
    original = command("edit_revision", {"text": "Not saved."})
    tombstone = recovery.make(str(uuid4()), recovery.reference(reference(original)), EDITOR, NOW)
    with pytest.raises(CommandError):
        Command.from_request(recovery.request(tombstone), EDITOR, environment="local", now=NOW)
    with pytest.raises(CommandError):
        core[0].accept(tombstone, EDITOR, now=NOW)
    sqlite = SQLiteAuthority(tmp_path / "sqlite.db")
    sqlite.initialize(core[1])
    with pytest.raises(CommandError):
        sqlite.accept(tombstone, EDITOR, now=NOW)
    with pytest.raises(CommandError):
        reduce_command(core[1], tombstone, EDITOR, now=NOW)
    with pytest.raises(CommandError):
        recovery.reference(
            dict(action=recovery.ACTION, original_action=recovery.ACTION, request_sha256="f" * 64)
        )
    assert core[0].read()[0] == 0 and sqlite.read()[0] == 0
