"""P00c inbox drain input: only unexpired, exactly-shaped admitted artifacts reach the consumer.

OFFLINE FIXTURE: an injected ``gh api`` runner returning invented listings and zips.
v2: the scan takes an explicit clock (horizon filter) and also writes ``scan.json``.
"""
from __future__ import annotations

from datetime import UTC, datetime
import io
import json
import zipfile

import pytest

from scripts import gist_command_inbox as inbox

ID = "11111111-2222-4333-8444-555555555555"
OTHER = "21111111-2222-4333-8444-555555555555"
NOW = datetime(2026, 10, 30, 13, 0, tzinfo=UTC)


def blob(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return out.getvalue()


def good(command_id: str) -> bytes:
    return blob({"command.json": b"{}", "admission.json": json.dumps({"command_id": command_id}).encode()})


def runner(listing: list[dict], zips: dict[int, bytes]):
    calls = []

    def run(args):
        calls.append(args[0])
        if args[0].endswith("/zip"):
            return zips[int(args[0].split("/")[-2])]
        return json.dumps({"artifacts": listing}).encode()
    return run, calls


def test_only_unexpired_admitted_artifacts_are_fetched_in_creation_order(tmp_path):
    listing = [
        {"id": 3, "name": f"theheat-command-{OTHER}", "expired": False, "created_at": "2026-10-30T12:00:02Z"},
        {"id": 1, "name": f"theheat-command-{ID}", "expired": False, "created_at": "2026-10-30T12:00:01Z"},
        {"id": 2, "name": f"theheat-command-{ID}", "expired": True, "created_at": "2026-10-30T12:00:00Z"},
        {"id": 4, "name": f"theheat-admission-refused-{ID}-expired", "expired": False},
        {"id": 5, "name": "encrypted-nhc-advisory-trial-9", "expired": False},
    ]
    run, calls = runner(listing, {1: good(ID), 3: good(OTHER)})
    result = inbox.fetch("invented/theheat", tmp_path, run, now=NOW)
    assert (result["fetched"], result["skipped"], result["scan_complete"]) == (2, [], True)
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) == [f"{ID}-1", f"{OTHER}-3"]
    assert [c for c in calls if c.endswith("/zip")] == ["repos/invented/theheat/actions/artifacts/1/zip",
                                                         "repos/invented/theheat/actions/artifacts/3/zip"]
    assert (tmp_path / f"{ID}-1" / "command.json").read_bytes() == b"{}"


@pytest.mark.parametrize("payload,code", [
    (blob({"command.json": b"{}", "admission.json": json.dumps({"command_id": OTHER}).encode()}), "artifact_identity_mismatch"),
    (blob({"command.json": b"{}", "admission.json": b"{}", "extra.sh": b"x"}), "artifact_contents_unexpected"),
    (b"not a zip", "artifact_unreadable"),
    (blob({"command.json": b"x" * (inbox.MAX_FILE_BYTES + 1), "admission.json": b"{}"}), "artifact_too_large"),
], ids=["identity", "extra-file", "not-zip", "oversize"])
def test_a_malformed_artifact_is_skipped_and_never_reaches_the_consumer(tmp_path, payload, code):
    listing = [{"id": 1, "name": f"theheat-command-{ID}", "expired": False}, {"id": 2, "name": f"theheat-command-{OTHER}", "expired": False}]
    run, _ = runner(listing, {1: payload, 2: good(OTHER)})
    result = inbox.fetch("invented/theheat", tmp_path, run, now=NOW)
    assert (result["fetched"], result["skipped"]) == (1, [{"artifact_id": 1, "code": code}])
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == [f"{OTHER}-2"]


def test_listing_is_bounded_and_repository_is_validated(tmp_path):
    with pytest.raises(inbox.InboxError, match="invalid_repository"):
        inbox.list_admitted("not a repo", lambda args: b"{}")
    pages = []

    def run(args):
        pages.append(args[0])
        return json.dumps({"artifacts": [{"id": i, "name": "other", "expired": False} for i in range(100)]}).encode()
    assert inbox.list_admitted("invented/theheat", run, now=NOW) == []
    assert len(pages) == inbox.MAX_PAGES
