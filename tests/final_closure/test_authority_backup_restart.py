"""E5 — reproducible backup -> verify -> restart of the disposable local authority.

A pending accepted command, imported history and a reconciliation survive the
copy with their identities; the restarted copy drains the pending command
exactly once, replays imports as already imported, and the original is
untouched. Invented fixtures only; nothing production is read or written.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path

import pytest

from src.commands import import_plan, local_cli
from src.commands.schema import CommandError, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from tests.test_command_authority import EDITOR, command, resolver, story


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


@pytest.fixture
def original(tmp_path):
    store = SQLiteAuthority(tmp_path / "original.sqlite3")
    draft = story("backup-1")
    store.initialize({"drafts": [draft], "publish_ledger": {}})
    inputs = [("backup-history", canonical_json({"drafts": [story("historic")], "publish_ledger": {}}).encode())]
    import_plan.execute(store, import_plan.plan(inputs, authority=store), inputs)
    pending = command([draft])
    receipt = store.accept(pending, EDITOR)
    return store, pending, receipt, inputs


def test_backup_verify_restart_preserves_identities_and_drains_once(original, tmp_path):
    store, pending, receipt, inputs = original
    before = (store.read(), store.journal())
    target = tmp_path / "backup.sqlite3"
    code, report = cli("--database", store.path, "backup", "--output", str(target))
    assert code == 0 and report["verified"] and report["pending"] == 1 and report["state_version"] == 0
    assert report["domain_counts"]["domain_snapshots"] == 2
    assert (store.read(), store.journal()) == before  # The source is unchanged.
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    code, verified = cli("--database", str(target), "verify-backup", "--expected-sha256", report["sha256"])
    assert code == 0 and verified["sha256"] == report["sha256"]
    # Restart from the verified copy: same pending intent, same receipt, drained once.
    restarted = SQLiteAuthority(target)
    assert restarted.accept(pending, EDITOR) == receipt
    first = restarted.consume(resolver)
    assert first is not None and first["command_id"] == pending.command_id and restarted.consume(resolver) is None
    assert restarted.read()[0] == 1 and store.read() == before[0]
    replay = import_plan.execute(restarted, import_plan.plan(inputs, authority=restarted), inputs)
    assert replay["items"][0]["status"] == "already_imported"


def test_backup_refuses_existing_or_relative_targets_and_changed_bytes(original, tmp_path):
    store = original[0]
    existing = tmp_path / "exists.sqlite3"
    existing.write_bytes(b"invented")
    with pytest.raises(FileExistsError):
        store.backup(existing)
    assert existing.read_bytes() == b"invented"
    with pytest.raises(CommandError, match="absolute"):
        store.backup("relative.sqlite3")
    report = store.backup(tmp_path / "good.sqlite3")
    copy = Path(report["path"])
    copy.write_bytes(copy.read_bytes() + b"\0")
    code, refused = cli("--database", str(copy), "verify-backup", "--expected-sha256", report["sha256"])
    assert code == 2 and refused["error"] == "backup_artifact_changed"


def test_a_backup_of_another_environment_is_refused_at_restart(original, tmp_path):
    report = original[0].backup(tmp_path / "local.sqlite3")
    with pytest.raises(CommandError, match="environment"):
        SQLiteAuthority(report["path"], environment="preview").verify_backup()
