"""Independent-process transactional mutation tests. No external calls exist here."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
import multiprocessing
import os
import sqlite3
from uuid import uuid4

import pytest

from src.editorial.policy import current_editorial_policy
from src.commands.reducer import AutomaticPolicy, reduce_command
from src.commands.schema import Command, CommandError, Principal, canonical_json, utc_text
from src.commands.sqlite_authority import SQLiteAuthority
from src.editorial.revisions import fingerprint, draft_identity, initialize_revision, record_human_review
from tests.revision_helpers import model_review_context

EDITOR = Principal("editor-fixture", "editor", "verified-local-fixture")
PUBLISHER = Principal("publisher-fixture", "publisher", "verified-local-fixture")
NOW = datetime.now(UTC)


def story(ident="draft-1"):
    text = f"Example City {ident} reached 40°C."
    return initialize_revision({"id": ident, "event_id": f"event-{ident}", "type": "monthly_high", "status": "pending",
        "text": text, "review_context": model_review_context(text), "approval_policy": {"can_auto_approve": True, "mode": "suggested_auto"}})


def target(draft):
    return {"draft_id": draft["id"], **draft_identity(draft), "decision_revision": draft["decision_revision"]}


def request(drafts, action="edit_revision", payload=None, command_id=None):
    if not isinstance(drafts, list):
        drafts = [drafts]
    return {"command_id": command_id or str(uuid4()), "action": action,
            "requested_at": utc_text(NOW), "expires_at": utc_text(NOW + timedelta(hours=1)),
            "targets": [target(draft) for draft in drafts], "payload": payload or {"text": "Example City reached 41°C."}}


def command(drafts, action="edit_revision", payload=None, command_id=None, principal=EDITOR):
    return Command.from_request(request(drafts, action, payload, command_id), principal, environment="local", now=NOW)


def resolver(subject):
    return {EDITOR.subject: EDITOR, PUBLISHER.subject: PUBLISHER}.get(subject)


def authority(tmp_path, state):
    store = SQLiteAuthority(tmp_path / "authority.sqlite")
    store.initialize(state)
    return store


def _worker(path, command_id, barrier, results):
    """Each child imports code and opens its own real SQLite connection."""
    try:
        store = SQLiteAuthority(path)
        barrier.wait(timeout=15)
        results.put(store.consume(resolver, command_id=command_id))
    except BaseException as exc:
        results.put({"worker_error": repr(exc)})


def _die_before_commit(path, command_id):
    SQLiteAuthority(path).consume(resolver, command_id=command_id, before_commit=lambda: os._exit(23))


def parallel_consume(store, ids, *, targeted=False):
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(len(ids))
    results = ctx.Queue()
    children = [ctx.Process(target=_worker, args=(store.path, ident if targeted else None, barrier, results)) for ident in ids]
    for child in children:
        child.start()
    values = [results.get(timeout=30) for _ in children]
    for child in children:
        child.join(timeout=15)
        assert not child.is_alive(), "SQLite consumer did not finish"
        assert child.exitcode == 0
    assert not [value for value in values if "worker_error" in value], values
    return values


def test_schema_rejects_forged_identity_unknown_fields_and_privilege_escalation():
    row = request(story())
    row["actor_subject"] = PUBLISHER.subject
    with pytest.raises(CommandError, match="fields"):
        Command.from_request(row, EDITOR, environment="local", now=NOW)
    with pytest.raises(CommandError) as denied:
        command(story(), "approve_revision", {"reason": "Checked evidence"})
    assert denied.value.code == "forbidden"
    with pytest.raises(CommandError):
        command(story(), principal=Principal("viewer", "viewer", "verified-fixture"))


@pytest.mark.parametrize("change", [
    lambda row: row["targets"][0].pop("evidence_sha256"),
    lambda row: row["targets"][0].update(decision_revision=True),
    lambda row: row.update(payload={"text": "\ud800"}),
    lambda row: row.update(payload={"text": "x" * 281}),
    lambda row: row.update(expires_at="2026-02-30T00:00:00Z"),
    lambda row: row.update(payload={"text": float("nan")}),
    lambda row: row.update(targets=row["targets"] * 501),
])
def test_schema_bounds_malformed_content_and_target_contract(change):
    row = request(story())
    change(row)
    with pytest.raises(CommandError):
        Command.from_request(row, EDITOR, environment="local", now=NOW)


def test_payload_and_targets_cannot_change_an_accepted_envelope():
    item = command(story())
    digest = item.digest
    payload = item.payload
    payload["text"] = "Changed externally"
    assert item.digest == digest
    with pytest.raises(FrozenInstanceError):
        item.targets[0].decision_revision = 99


def test_reducer_is_deterministic_and_never_mutates_input():
    draft = story()
    initial = {"drafts": [draft], "source_health": {"feed": {"last_success": "retained"}}}
    original = deepcopy(initial)
    cmd = command(draft)
    a = reduce_command(initial, cmd, EDITOR, now=NOW)
    b = reduce_command(initial, cmd, EDITOR, now=NOW)
    assert a == b
    assert initial == original
    changed = a.state["drafts"][0]
    assert changed["content_revision"] == 2
    assert "review_binding" not in changed and "approval_binding" not in changed
    assert changed["revision_history"][0]["text"] == draft["text"]
    assert a.state["source_health"] == original["source_health"]


def test_source_or_decision_change_conflicts_without_mutation(tmp_path):
    for change in ("source", "decision"):
        draft = story(change)
        cmd = command(draft)
        if change == "source":
            draft["review_context"]["two_bot"]["bundle"]["value"] = 99
        else:
            draft["decision_revision"] += 1
        folder = tmp_path / change
        folder.mkdir()
        store = authority(folder, {"drafts": [draft]})
        store.accept(cmd, EDITOR, now=NOW)
        result = store.consume(resolver, now=NOW)
        assert result["code"] == "revision_conflict"
        assert store.read() == (0, {"drafts": [draft]})


def test_acceptance_and_result_replay_are_idempotent_including_lost_acknowledgment(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    receipt = store.accept(cmd, EDITOR, now=NOW)
    assert store.accept(cmd, EDITOR, now=NOW + timedelta(minutes=2)) == receipt
    first = store.consume(resolver, now=NOW)
    # Caller loses the success response and retries after its original deadline.
    assert store.accept(cmd, EDITOR, now=NOW + timedelta(hours=2)) == receipt
    assert store.consume(resolver, command_id=cmd.command_id, now=NOW + timedelta(hours=2)) == first
    assert store.read()[0] == 1
    assert [row["event"] for row in store.journal()] == ["accepted", "completed"]
    different = command(draft, payload={"text": "Another edit"}, command_id=cmd.command_id)
    with pytest.raises(CommandError) as reused:
        store.accept(different, EDITOR, now=NOW)
    assert reused.value.code == "command_id_reused"


def test_fixed_bulk_targets_are_atomic_and_do_not_expand(tmp_path):
    drafts = [story(f"d{i}") for i in range(3)]
    cmd = command(drafts[:2], "bulk_reject", {"reason": "These specific stories are stale"})
    store = authority(tmp_path, {"drafts": drafts})
    store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    assert result["changed_ids"] == ["d0", "d1"]
    assert [row["status"] for row in store.read()[1]["drafts"]] == ["rejected", "rejected", "pending"]
    # A stale member means none of the explicitly requested set is modified.
    conflicting = deepcopy(drafts)
    conflicting[1]["decision_revision"] += 1
    other = SQLiteAuthority(tmp_path / "conflicting.sqlite")
    other.initialize({"drafts": conflicting})
    other.accept(cmd, EDITOR, now=NOW)
    assert other.consume(resolver, now=NOW)["code"] == "revision_conflict"
    assert other.read() == (0, {"drafts": conflicting})


@pytest.mark.parametrize("action", ["edit_revision", "cancel_approval", "reject_revision", "approve_revision"])
def test_unknown_publication_survives_every_mutation_attempt(tmp_path, action):
    draft = story()
    draft.update(publish_outcome="unknown", last_publish_attempt_at=utc_text(NOW))
    ledger = {draft["event_id"]: {"phase": "unknown", "intent_id": "unconfirmed", "text": draft["text"]}}
    initial = {"drafts": [draft], "publish_ledger": ledger}
    store = authority(tmp_path, initial)
    payload = {"text": "Edited text"} if action == "edit_revision" else {"reason": "Operator request"}
    if payload.get("expected_policy_sha256") == "runtime-policy":
        payload = {**payload, "expected_policy_sha256": fingerprint(current_editorial_policy())}
    cmd = command(draft, action, payload, principal=PUBLISHER)
    store.accept(cmd, PUBLISHER, now=NOW)
    assert store.consume(resolver, now=NOW)["code"] == "publication_unresolved"
    assert store.read() == (0, initial)


def test_revoked_role_and_expired_command_are_terminal_without_mutation(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    assert store.consume(lambda _: Principal(EDITOR.subject, "viewer", "current-fixture"), now=NOW)["code"] == "forbidden"
    expired = command(draft)
    store.accept(expired, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW + timedelta(hours=2))["code"] == "command_expired"
    assert store.read()[0] == 0


def test_production_and_cross_environment_commands_are_refused(tmp_path):
    with pytest.raises(CommandError) as unavailable:
        SQLiteAuthority(tmp_path / "prod.sqlite", environment="production")
    assert unavailable.value.code == "production_adapter_unavailable"
    store = authority(tmp_path, {"drafts": [story()]})
    cmd = Command.from_request(request(story()), EDITOR, environment="production", now=NOW)
    with pytest.raises(CommandError):
        store.accept(cmd, EDITOR, now=NOW)
    assert store.journal() == []


def test_schedule_needs_current_model_checks_and_trusted_live_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "release-fixture")
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    payload = {"delay_minutes": 30, "publication_epoch": "release-fixture", "reason": "Reviewed source and release"}
    paused = command(draft, "schedule_revision", payload, principal=PUBLISHER)
    store.accept(paused, PUBLISHER, now=NOW)
    assert store.consume(resolver, now=NOW)["code"] == "automatic_publication_paused"
    allowed = command(draft, "schedule_revision", payload, principal=PUBLISHER)
    store.accept(allowed, PUBLISHER, now=NOW)
    assert store.consume(resolver, now=NOW, policy=AutomaticPolicy(True, "release-fixture"))["status"] == "applied"
    assert store.read()[1]["drafts"][0]["approval_binding"]["publication_epoch"] == "release-fixture"


def test_manual_review_and_approval_record_actual_actor_and_exact_intent(tmp_path):
    draft = story()
    del draft["review_binding"]
    store = authority(tmp_path, {"drafts": [draft]})
    reviewed = command(draft, "record_review", {"confirmed": True, "reason": "Checked the source table", "expected_policy_sha256": fingerprint(current_editorial_policy())})
    store.accept(reviewed, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["status"] == "applied"
    current = store.read()[1]["drafts"][0]
    assert current["review_binding"]["reviewer"] == EDITOR.subject
    approved = command(current, "approve_revision", {"reason": "Approve exact reviewed copy"}, principal=PUBLISHER)
    store.accept(approved, PUBLISHER, now=NOW)
    result = store.consume(resolver, now=NOW)
    saved = store.read()[1]["drafts"][0]
    assert saved["approval_binding"]["actor"] == PUBLISHER.subject
    assert saved["publish_intent_id"] == result["publish_intent_id"]
    assert saved["approval_binding"]["text_sha256"] == draft_identity(saved)["text_sha256"]
    assert saved["status"] == "approved"  # This adapter never sends a post.


def test_journal_enforces_append_only_at_database_boundary(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    store.consume(resolver, now=NOW)
    with sqlite3.connect(store.path) as connection:
        for table in ("command_intents", "command_results", "command_events"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(f"DELETE FROM {table}")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE command_intents SET digest='changed'")


def test_crash_before_commit_rolls_back_state_and_result_but_preserves_acceptance(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    ctx = multiprocessing.get_context("spawn")
    child = ctx.Process(target=_die_before_commit, args=(store.path, cmd.command_id))
    child.start()
    child.join(timeout=15)
    assert child.exitcode == 23
    assert store.read() == (0, {"drafts": [draft]})
    assert store.result(cmd.command_id) is None
    assert [row["event"] for row in store.journal()] == ["accepted"]
    assert store.consume(resolver, now=NOW)["status"] == "applied"


def test_independent_processes_preserve_all_unrelated_updates(tmp_path):
    drafts = [story(f"draft-{i}") for i in range(8)]
    store = authority(tmp_path, {"drafts": drafts, "source_health": {"feed": {"retained": True}}})
    commands = [command(draft, payload={"text": f"Updated exact source story {i}."}) for i, draft in enumerate(drafts)]
    for cmd in commands:
        store.accept(cmd, EDITOR, now=NOW)
    results = parallel_consume(store, [cmd.command_id for cmd in commands])
    assert {row["status"] for row in results} == {"applied"}
    version, saved = store.read()
    assert version == 8
    assert [row["text"] for row in saved["drafts"]] == [f"Updated exact source story {i}." for i in range(8)]
    assert saved["source_health"] == {"feed": {"retained": True}}


def test_independent_processes_conflict_on_same_revision_without_last_writer_wins(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    commands = [command(draft, payload={"text": text}) for text in ("First operator edit", "Second operator edit")]
    for cmd in commands:
        store.accept(cmd, EDITOR, now=NOW)
    results = parallel_consume(store, [cmd.command_id for cmd in commands])
    assert sorted(row["status"] for row in results) == ["applied", "rejected"]
    assert next(row for row in results if row["status"] == "rejected")["code"] == "revision_conflict"
    assert store.read()[0] == 1


def test_concurrent_duplicate_approvals_create_one_durable_intent(tmp_path):
    draft = story()
    record_human_review(draft)
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft, "approve_revision", {"reason": "Reviewed exact source and text"}, principal=PUBLISHER)
    store.accept(cmd, PUBLISHER, now=NOW)
    results = parallel_consume(store, [cmd.command_id] * 4, targeted=True)
    assert all(result == results[0] for result in results)
    assert store.read()[0] == 1
    assert len([row for row in store.journal() if row["event"] == "completed"]) == 1
    assert store.read()[1]["drafts"][0]["publish_intent_id"] == results[0]["publish_intent_id"]


@pytest.mark.parametrize("action,payload", [
    ("edit_revision", {"text": "Revised from exact source."}),
    ("record_review", {"confirmed": True, "reason": "Checked exact evidence", "expected_policy_sha256": "runtime-policy"}),
    ("approve_revision", {"reason": "Checked exact evidence"}),
    ("schedule_revision", {"delay_minutes": 30, "publication_epoch": "release-fixture", "reason": "Checked exact evidence"}),
])
def test_reduction_never_reads_ambient_clock_or_publication_environment(monkeypatch, action, payload):
    draft = story()
    if payload.get("expected_policy_sha256") == "runtime-policy":
        payload = {**payload, "expected_policy_sha256": fingerprint(current_editorial_policy())}
    cmd = command(draft, action, payload, principal=PUBLISHER)
    initial = {"drafts": [draft]}
    def forbidden_clock():
        raise AssertionError("Reducer read the ambient clock")
    monkeypatch.setattr("src.editorial.revisions._now", forbidden_clock)
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "ambient-paused")
    first = reduce_command(initial, cmd, PUBLISHER, now=NOW, policy=AutomaticPolicy(True, "release-fixture"), editorial_policy=current_editorial_policy())
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "ambient-different")
    assert reduce_command(initial, cmd, PUBLISHER, now=NOW, policy=AutomaticPolicy(True, "release-fixture"), editorial_policy=current_editorial_policy()) == first


@pytest.mark.parametrize("control", [None, [], {"retired_epochs": None}, {"retired_epochs": [None]},
                                     {"retired_epochs": ["bad"]}, {"retired_epochs": ["release-fixture"]},
                                     {"invalid_control": True}])
def test_malformed_or_retired_control_cannot_be_normalized_into_permission(tmp_path, control):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft], "publication_control": control})
    cmd = command(draft, "schedule_revision", {"delay_minutes": 30, "publication_epoch": "release-fixture", "reason": "Fixture"}, principal=PUBLISHER)
    store.accept(cmd, PUBLISHER, now=NOW)
    result = store.consume(resolver, now=NOW, policy=AutomaticPolicy(True, "release-fixture"))
    assert result["status"] == "rejected"
    assert store.read()[0] == 0
    assert store.read()[1]["publication_control"] == control


def test_different_approval_commands_for_same_revision_conflict_under_concurrency(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    commands = [command(draft, "approve_revision", {"reason": "Reviewed exact copy"}, principal=PUBLISHER) for _ in range(2)]
    for cmd in commands:
        store.accept(cmd, PUBLISHER, now=NOW)
    results = parallel_consume(store, [cmd.command_id for cmd in commands])
    assert sorted(row["status"] for row in results) == ["applied", "rejected"]
    assert next(row for row in results if row["status"] == "rejected")["code"] == "revision_conflict"
    assert store.read()[0] == 1
    assert len({row["publish_intent_id"] for row in results if row["status"] == "applied"}) == 1


def test_new_expired_acceptance_is_refused_without_journal_event(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    with pytest.raises(CommandError) as expired:
        store.accept(command(draft), EDITOR, now=NOW + timedelta(hours=2))
    assert expired.value.code == "command_expired"
    assert store.journal() == []


def test_local_cli_runs_acceptance_and_consumer_without_publishing(tmp_path, capsys):
    from src.commands.local_cli import main
    draft = story()
    state_file = tmp_path / "state.json"
    request_file = tmp_path / "request.json"
    operators_file = tmp_path / "operators.json"
    state_file.write_text(canonical_json({"drafts": [draft]}))
    request_file.write_text(canonical_json(request(draft)))
    operators_file.write_text(canonical_json({EDITOR.subject: {"role": EDITOR.role, "authentication_context": EDITOR.authentication_context}}))
    base = ["--database", str(tmp_path / "cli.sqlite")]
    assert main(base + ["init", "--state", str(state_file)]) == 0
    assert main(base + ["submit", "--request", str(request_file), "--operators", str(operators_file), "--subject", EDITOR.subject]) == 0
    assert main(base + ["drain", "--operators", str(operators_file)]) == 0
    assert main(base + ["status"]) == 0
    import json
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert outputs[2]["results"][0]["status"] == "applied"
    assert outputs[2]["automatic_publication_enabled"] is False
    assert outputs[3] == {"environment": "local", "state_version": 1, "accepted": 1, "completed": 1, "pending": 0}


def test_candidate_command_is_bound_to_selected_candidate_not_mutable_rank(tmp_path):
    from src.editorial.revisions import fingerprint
    draft = story()
    candidate = {"rank": 1, "text": "The candidate the operator actually selected.", "score": 80}
    draft["candidates"] = [candidate]
    cmd = command(draft, "select_candidate", {"candidate_rank": 1, "candidate_sha256": fingerprint(candidate)})
    candidate["text"] = "A replacement candidate that was never selected."
    store = authority(tmp_path, {"drafts": [draft]})
    store.accept(cmd, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["code"] == "candidate_conflict"
    assert store.read() == (0, {"drafts": [draft]})
    fresh = command(draft, "select_candidate", {"candidate_rank": 1, "candidate_sha256": fingerprint(candidate)})
    store.accept(fresh, EDITOR, now=NOW)
    assert store.consume(resolver, now=NOW)["status"] == "applied"
    saved = store.read()[1]["drafts"][0]
    assert saved["text"] == candidate["text"]
    assert "review_binding" not in saved and "approval_binding" not in saved


@pytest.mark.parametrize("bad_history", [{}, None, ["not a revision"]])
def test_malformed_revision_is_terminal_and_does_not_poison_fifo(tmp_path, bad_history):
    bad, good = story("bad"), story("good")
    bad["revision_history"] = bad_history
    store = authority(tmp_path, {"drafts": [bad, good]})
    first, second = command(bad), command(good)
    store.accept(first, EDITOR, now=NOW)
    store.accept(second, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    assert result["code"] == "invalid_revision"
    assert store.result(first.command_id) == result
    assert store.consume(resolver, now=NOW)["status"] == "applied"
    assert store.consume(resolver, now=NOW) is None
    assert store.read()[1]["drafts"][0] == bad
    assert store.read()[0] == 1


def test_replace_and_upsert_cannot_rewrite_immutable_acceptance_or_result(tmp_path):
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft)
    receipt = store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    original = store.journal()
    with sqlite3.connect(store.path) as connection:
        for table in ("authority_metadata", "command_intents", "command_results", "command_events"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                connection.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("INSERT OR REPLACE INTO command_results(command_id,result_json) VALUES(?,?)", (cmd.command_id, '{"status":"replaced"}'))
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("INSERT INTO command_results(command_id,result_json) VALUES(?,?) ON CONFLICT(command_id) DO UPDATE SET result_json=excluded.result_json", (cmd.command_id, '{"status":"upserted"}'))
    assert store.result(cmd.command_id) == result
    assert store.accept(cmd, EDITOR, now=NOW) == receipt
    assert store.journal() == original


def test_targeted_retry_cannot_skip_an_earlier_accepted_command(tmp_path):
    drafts = [story("first"), story("second")]
    store = authority(tmp_path, {"drafts": drafts})
    first, second = (command(draft) for draft in drafts)
    store.accept(first, EDITOR, now=NOW)
    store.accept(second, EDITOR, now=NOW)
    with pytest.raises(CommandError) as pending:
        store.consume(resolver, command_id=second.command_id, now=NOW)
    assert pending.value.code == "command_pending"
    assert store.result(second.command_id) is None
    assert store.read()[0] == 0
    assert store.consume(resolver, now=NOW)["command_id"] == first.command_id
    result = store.consume(resolver, command_id=second.command_id, now=NOW)
    assert result["status"] == "applied"
    assert store.consume(resolver, command_id=second.command_id, now=NOW) == result


@pytest.mark.parametrize("conflicts", [[None], {"phase": "unknown"}, [{"phase": "not_sent", "attempt_conflicts": ["malformed"]}]])
def test_malformed_nested_publication_conflicts_remain_untouched(tmp_path, conflicts):
    draft = story()
    initial = {"drafts": [draft], "publish_ledger": {draft["event_id"]: {"phase": "not_sent", "attempt_conflicts": conflicts}}}
    store = authority(tmp_path, initial)
    cmd = command(draft)
    store.accept(cmd, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    assert result["status"] == "rejected" and result["code"] == "invalid_revision"
    assert store.result(cmd.command_id) == result
    assert store.read() == (0, initial)


def test_queued_human_attestation_cannot_adopt_a_later_policy(tmp_path, monkeypatch):
    from src.two_bot import writer
    draft = story()
    store = authority(tmp_path, {"drafts": [draft]})
    cmd = command(draft, "record_review", {"confirmed": True, "reason": "Checked source under displayed policy", "expected_policy_sha256": fingerprint(current_editorial_policy())})
    store.accept(cmd, EDITOR, now=NOW)
    before = store.read()
    monkeypatch.setattr(writer, "WRITER_MODEL", writer.WRITER_MODEL + "-changed")
    result = store.consume(resolver, now=NOW)
    assert result["status"] == "rejected" and result["code"] == "editorial_policy_changed"
    assert store.read() == before


def test_old_queued_human_review_is_terminally_refused_without_wedging_journal(tmp_path):
    import json
    draft = story()
    cmd = command(draft, "record_review", {"confirmed": True, "reason": "Legacy reviewed source", "expected_policy_sha256": fingerprint(current_editorial_policy())})
    old = cmd.as_dict()
    del old["payload"]["expected_policy_sha256"]
    stored = Command.from_stored(json.dumps(old))
    store = authority(tmp_path, {"drafts": [draft]})
    store.accept(stored, EDITOR, now=NOW)
    next_command = command(draft)
    store.accept(next_command, EDITOR, now=NOW)
    result = store.consume(resolver, now=NOW)
    assert result["status"] == "rejected" and result["code"] == "editorial_policy_changed"
    assert store.result(stored.command_id) == result
    assert store.read() == (0, {"drafts": [draft]})
    assert store.consume(resolver, now=NOW)["status"] == "applied"
