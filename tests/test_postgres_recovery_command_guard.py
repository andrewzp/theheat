"""Disposable real PG/SQLite command regressions for CI; not run locally.

All inputs are invented. No source/model/platform transport or listening HTTP
socket is needed: the real authenticated HTTP handler uses an in-memory socket.
"""
from copy import deepcopy

import pytest

from src.commands import import_plan, recovery_provenance
from src.commands.schema import CommandError, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from tests.remaining_campaign.test_recovery_command_guard import ACTOR, body, command, http, server
from tests.remaining_campaign.w14_provenance_child import operators_file
from tests.test_command_authority import story
from tests.test_postgres_command_authority import make_authority as make_authority
from tests.test_postgres_projection import cluster as cluster, database as database


def import_packet(journal, drafts, import_id):
    raw = canonical_json({"drafts": drafts, "publish_ledger": {}}).encode()
    inputs = [(import_id, raw)]
    result = import_plan.execute(journal, import_plan.plan(inputs, authority=journal), inputs)
    assert result["items"][0]["status"] == "imported"


@pytest.fixture(params=["postgres", "sqlite"])
def authority_case(request, tmp_path):
    imported, fresh = story("invented-imported"), story("invented-fresh")
    initial = {"drafts": [imported, fresh], "publish_ledger": {}}
    if request.param == "postgres":
        make, _owner, _params = request.getfixturevalue("make_authority")
        authority = make(initial)
    else:
        authority = SQLiteAuthority(tmp_path / "disposable-authority.sqlite3")
        authority.initialize(initial)
    journal = SQLiteAuthority(tmp_path / "disposable-recovery.sqlite3")
    journal.initialize({"drafts": [], "publish_ledger": {}})
    return authority, journal, initial


@pytest.mark.parametrize("action", ["edit_revision", "record_review", "approve_revision", "bulk_reject"])
def test_real_authenticated_post_refuses_imported_history_without_acceptance(authority_case, monkeypatch, tmp_path, action):
    authority, journal, initial = authority_case
    imported, fresh = initial["drafts"]
    import_packet(journal, [imported], "invented-initial-import")
    target_server = server(monkeypatch, authority, operators_file(tmp_path), configured=journal.path)
    original = authority.read()
    request_body = body([fresh, imported] if action == "bulk_reject" else [imported], action)
    status, result = http(target_server, request_body)
    assert status == 409 and result["code"] == "imported_record_read_only"
    assert authority.read() == original and authority.journal() == []
    assert authority.result(request_body["command_id"]) is None


@pytest.mark.parametrize("bulk", [False, True])
def test_real_deferred_consumption_rechecks_imports_after_acceptance(authority_case, bulk):
    authority, journal, initial = authority_case
    imported, fresh = initial["drafts"]
    recovery_provenance.configure(authority, journal.path)
    cmd = command([fresh, imported] if bulk else [imported], "bulk_reject" if bulk else "edit_revision")
    receipt = authority.accept(cmd, ACTOR)
    import_packet(journal, [imported], "invented-later-import")
    original = authority.read()
    result = authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "rejected" and result["code"] == "imported_record_read_only"
    assert authority.read() == original and result["state_version"] == original[0]
    assert authority.accept(cmd, ACTOR) == receipt  # receipt recovery does not re-admit work
    assert authority.consume(lambda _subject: None, command_id=cmd.command_id) == result


def test_real_unavailable_journal_rolls_back_and_keeps_pending_intent(authority_case):
    authority, journal, initial = authority_case
    recovery_provenance.configure(authority, journal.path)
    cmd = command([initial["drafts"][0]])
    authority.accept(cmd, ACTOR)
    original = authority.read()
    from pathlib import Path
    Path(journal.path).rename(Path(journal.path).with_suffix(".unavailable"))
    with pytest.raises(recovery_provenance.ProvenanceUnavailable):
        authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert authority.read() == original and authority.result(cmd.command_id) is None
    assert [event["event"] for event in authority.journal()] == ["accepted"]


def test_real_changed_imported_bytes_stay_held_and_nonimported_edit_still_works(authority_case):
    authority, journal, initial = authority_case
    imported, fresh = initial["drafts"]
    old = deepcopy(imported)
    old.update(text="Invented old imported wording.", content_revision=0)
    import_packet(journal, [old], "invented-older-import")
    recovery_provenance.configure(authority, journal.path)
    with pytest.raises(CommandError, match="Imported history"):
        authority.accept(command([imported]), ACTOR)
    cmd = command([fresh])
    authority.accept(cmd, ACTOR)
    result = authority.consume(lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "applied"
    saved = authority.read()[1]["drafts"]
    assert next(d for d in saved if d["id"] == imported["id"]) == imported
    assert next(d for d in saved if d["id"] == fresh["id"])["text"] == cmd.payload["text"]


def test_real_native_history_refuses_before_inputs_and_render(make_authority, monkeypatch, tmp_path):
    from src.commands import postgres_editor_media, preview_media_worker
    make, _owner, _params = make_authority
    draft = story("invented-media")
    initial = {"drafts": [draft], "publish_ledger": {}}
    authority = make(initial)
    journal = SQLiteAuthority(tmp_path / "native-recovery.sqlite3")
    journal.initialize({"drafts": [], "publish_ledger": {}})
    recovery_provenance.configure(authority, journal.path)
    cmd = command([draft], "prepare_media_revision")
    authority.accept(cmd, ACTOR)
    import_packet(journal, [draft], "invented-native-import")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("imported history must not prepare inputs or launch native work")
    monkeypatch.setattr(postgres_editor_media, "command_inputs", forbidden)
    monkeypatch.setattr(preview_media_worker, "run_native", forbidden)
    result = preview_media_worker.consume_media_once(authority, lambda _subject: ACTOR, command_id=cmd.command_id)
    assert result["status"] == "rejected" and result["code"] == "imported_record_read_only"
    assert authority.read() == (0, initial)
