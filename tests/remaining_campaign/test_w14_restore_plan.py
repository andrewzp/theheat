"""W14.5: restore/rollback plans verify everything before any append-only mutation.

Invented places, identities and media only; a separate local SQLite authority and a
private media export in tmp_path. No Gist, hosted store or network.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from src.commands import local_cli, restore_plan
from src.commands.schema import CommandError, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.media import gist_assets, gist_media_export as portable
from tests.gist_store_helpers import retain
from tests.two_bot import test_batch_transport as transport_tests

inputs, store, prepared = transport_tests.inputs, transport_tests.store, transport_tests.prepared
NOW = "2026-10-30T12:00:00Z"


def _state():
    return {"drafts": [
        {"id": "w14r-posted", "event_id": "w14r-ev-posted", "status": "posted", "tweet_id": "1900000000000000301",
         "text": "Invented Hollin Moor reached 37 C."},
        {"id": "w14r-old", "event_id": "w14r-ev-old", "status": "approved", "text": "Invented Sallow Rise reached 36 C."}],
        "publish_ledger": {
            "w14r-ev-posted": {"phase": "confirmed", "tweet_id": "1900000000000000301", "text": "Invented Hollin Moor reached 37 C."},
            "w14r-ev-old": {"phase": "unknown", "tweet_id": None, "text": "Invented Sallow Rise reached 36 C."},
            "w14r-ev-retry": {"phase": "not_sent", "tweet_id": None}}}


@pytest.fixture
def world(tmp_path):
    target = SQLiteAuthority(tmp_path / "target.sqlite3")
    target.initialize(_state())
    media = gist_assets.SQLiteMediaStore(tmp_path / "media-source.sqlite3")
    radar = retain("radar", media)
    export = tmp_path / "export"
    portable.export(media, [("published", radar)], export)
    blob = sorted(json.loads((export / "export.json").read_text())["blobs"])[0]
    backup_state = _state()
    backup_state["drafts"].append({"id": "w14r-media", "event_id": "w14r-ev-media", "status": "rejected",
                                   "text": "Invented Quarry End radar.", "media_attachment": {"png_sha256": blob}})
    backup = canonical_json(backup_state).encode()
    path = tmp_path / "backup.json"
    path.write_bytes(backup)
    return target, backup, path, export, blob, tmp_path


def _digest_tree(path: Path) -> dict:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob("*")) if p.is_file()}


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


def test_complete_backup_plans_then_appends_without_replacing_anything(world):
    target, backup, path, export, _blob, tmp_path = world
    sha = hashlib.sha256(backup).hexdigest()
    before, export_before = target.read(), _digest_tree(export)
    db = str(tmp_path / "target.sqlite3")
    code, value = cli("--database", db, "restore-plan", "--backup", str(path), "--expected-sha256", sha,
                      "--restore-id", "w14-restore-1", "--media-export", str(export))
    assert code == 0 and value["executable"] and value["mutation"] == "none" and value["refusals"] == []
    assert [step["step"] for step in value["steps"]] == ["append_domain_snapshot", "insert_only_media_restore"]
    assert value["rollback"]["directory_replacement"] is False and {row["name"] for row in value["cold_start_inputs"]} >= {
        "target_database", "backup_snapshot", "expected_backup_sha256", "media_export"}
    assert target.read() == before
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(value))
    media_target = tmp_path / "media-target.sqlite3"
    code, ran = cli("--database", db, "restore-run", "--backup", str(path), "--expected-sha256", sha, "--restore-id", "w14-restore-1",
                    "--media-export", str(export), "--plan", str(plan_path), "--media-store", str(media_target))
    assert code == 0 and ran["current_state_replaced"] is False and ran["rollback"]["prior_state_unchanged"] is True
    assert ran["media"]["verified"] and ran["media"]["restored_items"] == 1
    assert target.read() == before and path.read_bytes() == backup and _digest_tree(export) == export_before
    assert [item["status"] for item in ran["imported"]["items"]] == ["imported"] and ran["imported"]["migration_complete"] is False
    # Repeating the reviewed run is idempotent: the snapshot and media are already retained.
    code, again = cli("--database", db, "restore-run", "--backup", str(path), "--expected-sha256", sha, "--restore-id", "w14-restore-1",
                      "--media-export", str(export), "--plan", str(plan_path), "--media-store", str(media_target))
    assert code == 0 and [item["status"] for item in again["imported"]["items"]] == ["already_imported"]
    assert target.read() == before and again["rollback"]["prior_state_unchanged"] is True


def _codes(value):
    return sorted({row["code"] for row in value["refusals"]})


@pytest.mark.parametrize("change,code", [
    (lambda s: s["publish_ledger"].pop("w14r-ev-old"), "protected_record_would_be_lost"),
    (lambda s: s["publish_ledger"]["w14r-ev-posted"].update(tweet_id="1900000000000000999"), "protected_record_would_change"),
    (lambda s: s["drafts"][0].update(status="approved"), "protected_record_would_change"),
    (lambda s: s["publish_ledger"].update({"w14r-ev-other": {"phase": "confirmed", "tweet_id": "1900000000000000301"}}),
     "receipt_reference_conflict"),
    (lambda s: s["drafts"].append({"id": "w14r-m2", "event_id": "w14r-ev-m2", "media_attachment": {"png_sha256": "b" * 64}}),
     "media_artifact_missing"),
])
def test_incomplete_or_damaging_backups_refuse_before_any_write(world, change, code):
    target, _backup, _path, export, blob, _tmp = world
    state = _state()
    state["drafts"].append({"id": "w14r-media", "event_id": "w14r-ev-media", "media_attachment": {"png_sha256": blob}})
    change(state)
    raw = canonical_json(state).encode()
    before = target.read()
    value = restore_plan.plan(target, raw, expected_sha256=hashlib.sha256(raw).hexdigest(), restore_id="w14-restore-x",
                              now=NOW, media_export=export)
    assert code in _codes(value) and value["executable"] is False and value["steps"] == []
    with pytest.raises(CommandError):
        restore_plan.execute(target, value, raw, expected_sha256=hashlib.sha256(raw).hexdigest(), now=NOW, media_export=export,
                             media_writer=gist_assets.SQLiteMediaStore(_tmp / "unused.sqlite3"))
    assert target.read() == before


def test_changed_artifact_and_missing_export_are_named(world):
    target, backup, _path, export, _blob, _tmp = world
    changed = restore_plan.plan(target, backup + b" ", expected_sha256=hashlib.sha256(backup).hexdigest(),
                                restore_id="w14-restore-y", now=NOW, media_export=export)
    assert "backup_artifact_changed" in _codes(changed)
    no_media = restore_plan.plan(target, backup, expected_sha256=hashlib.sha256(backup).hexdigest(), restore_id="w14-restore-y", now=NOW)
    assert _codes(no_media) == ["media_export_required"]
    (export / "blobs" / sorted((export / "blobs").iterdir())[0].name).write_bytes(b"corrupt")
    corrupt = restore_plan.plan(target, backup, expected_sha256=hashlib.sha256(backup).hexdigest(), restore_id="w14-restore-y",
                                now=NOW, media_export=export)
    assert "media_export_invalid" in _codes(corrupt)


def test_active_jobs_block_restore(prepared):
    authority, _pair = prepared
    raw = canonical_json(authority.read()[1]).encode()
    value = restore_plan.plan(authority, raw, expected_sha256=hashlib.sha256(raw).hexdigest(), restore_id="w14-restore-job", now=NOW)
    assert "active_job_present" in _codes(value) and value["executable"] is False


def test_rollback_detects_a_target_changed_after_the_plan(world):
    target, backup, _path, export, _blob, _tmp = world
    value = restore_plan.plan(target, backup, expected_sha256=hashlib.sha256(backup).hexdigest(), restore_id="w14-restore-z",
                              now=NOW, media_export=export)
    assert restore_plan.verify_rollback(target, value)["prior_state_unchanged"] is True
    stale = deepcopy(value)
    stale["rollback"]["prior_state_sha256"] = "0" * 64
    assert restore_plan.verify_rollback(target, stale) == {"prior_state_unchanged": False, "action_required": "inspect_changes_since_plan"}
