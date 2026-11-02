"""P00c inbox drain input: only unexpired, exactly-shaped admitted artifacts reach the consumer.

v3 (root checkpoint R1): the scan is run-scoped — it lists gist-commands.yml workflow_dispatch runs and
then each unsettled run's artifacts; the repository-wide artifact listing is never used. Rewritten
deliberately from the repository-listing version; the same artifact-shape refusals are kept.
OFFLINE FIXTURE: tests/real_closure/route_inbox_fixture.FakeActions.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
import zipfile

import pytest

from scripts import gist_command_inbox as inbox
from tests.real_closure.route_inbox_fixture import FakeActions

ID = "11111111-2222-4333-8444-555555555555"
OTHER = "21111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 10, 30, 13, 0, tzinfo=UTC)


def blob(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def admitted(tmp_path, command_id: str, name: str = "a"):
    folder = tmp_path / "admitted" / name
    folder.mkdir(parents=True)
    (folder / "command.json").write_text("{}")
    (folder / "admission.json").write_text(json.dumps({"command_id": command_id}))
    return folder


def test_only_unexpired_command_artifacts_of_listed_runs_are_fetched_oldest_run_first(tmp_path):
    gh = FakeActions(tmp_path / "gh")
    newer = gh.add_run(NOW - timedelta(minutes=10))
    older = gh.add_run(NOW - timedelta(minutes=20))
    gh.add_artifact(newer, f"theheat-command-{OTHER}", admitted_dir=admitted(tmp_path, OTHER, "o"))
    gh.add_artifact(older, f"theheat-command-{ID}", admitted_dir=admitted(tmp_path, ID, "i"))
    expired = gh.add_artifact(older, f"theheat-command-{ID}")
    rows = json.loads((gh.root / "artifacts" / f"a{expired:07d}.json").read_text())
    (gh.root / "artifacts" / f"a{expired:07d}.json").write_text(json.dumps({**rows, "expired": True}))
    gh.add_artifact(older, f"theheat-admission-refused-{ID}")
    out = tmp_path / "out"
    result = inbox.fetch("invented/theheat", out, gh, now=NOW, settled=set())
    assert (result["fetched"], result["skipped"], result["scan_complete"]) == (2, [], True)
    assert sorted(p.name for p in out.iterdir() if p.is_dir()) == [f"{ID}-2", f"{OTHER}-1"]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest[f"{ID}-2"]["run_id"] == older and manifest[f"{OTHER}-1"]["run_id"] == newer
    examined = [c for c in gh.calls if c.endswith("/artifacts?per_page=100")]
    assert examined == [f"repos/invented/theheat/actions/runs/{older}/artifacts?per_page=100",
                        f"repos/invented/theheat/actions/runs/{newer}/artifacts?per_page=100"], "oldest run first"
    assert (out / f"{ID}-2" / "command.json").read_bytes() == b"{}"


@pytest.mark.parametrize("payload,code", [
    (blob({"command.json": b"{}", "admission.json": json.dumps({"command_id": OTHER}).encode()}), "artifact_identity_mismatch"),
    (blob({"command.json": b"{}", "admission.json": b"{}", "extra.sh": b"x"}), "artifact_contents_unexpected"),
    (b"not a zip", "artifact_unreadable"),
    (blob({"command.json": b"x" * (inbox.MAX_FILE_BYTES + 1), "admission.json": b"{}"}), "artifact_too_large"),
], ids=["identity", "extra-file", "not-zip", "oversize"])
def test_a_malformed_artifact_is_skipped_and_never_reaches_the_consumer(tmp_path, payload, code):
    gh = FakeActions(tmp_path / "gh")
    first = gh.add_run(NOW - timedelta(minutes=5))
    second = gh.add_run(NOW - timedelta(minutes=4))
    bad = gh.add_artifact(first, f"theheat-command-{ID}")
    gh.add_artifact(second, f"theheat-command-{OTHER}", admitted_dir=admitted(tmp_path, OTHER))
    original = gh.__call__

    def run(args):
        return payload if args[0].endswith(f"/artifacts/{bad}/zip") else original(args)
    result = inbox.fetch("invented/theheat", tmp_path / "out", run, now=NOW, settled=set())
    assert (result["fetched"], result["skipped"]) == (1, [{"artifact_id": bad, "run_id": first, "code": code}])
    assert [p.name for p in (tmp_path / "out").iterdir() if p.is_dir()] == [f"{OTHER}-2"]


def test_run_listing_is_bounded_scoped_and_repository_is_validated(tmp_path):
    with pytest.raises(inbox.InboxError, match="invalid_repository"):
        inbox.list_runs("not a repo", lambda args: b"{}")
    pages = []

    def run(args):
        pages.append(args[0])
        assert "/actions/workflows/gist-commands.yml/runs?event=workflow_dispatch&branch=main&created=%3E%3D" in args[0]
        return json.dumps({"workflow_runs": [{"id": i, "status": "completed"} for i in range(100)]}).encode()
    listed = inbox.list_runs("invented/theheat", run, now=NOW)
    assert len(pages) == inbox.MAX_RUN_PAGES and listed["complete"] is False
