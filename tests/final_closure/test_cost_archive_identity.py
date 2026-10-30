"""D4 — a retained capture is bound to its own scope directory.

Uses the existing pinned-SDK journey fixture (invented responses, no network).
A copy under its own name still counts once; a copy under another scope's
directory name is not that capture and is refused, not silently reconciled.
"""
from __future__ import annotations

import shutil

from src.evaluation.archive_usage import reconcile_identities
from src.two_bot import request_archive_replay as replay
from tests.test_request_archive_replay import archives as archives, copy_archive
from tests.test_request_archive_sdk import journey_env as journey_env, private_root


def test_copy_under_another_scope_name_is_invalid_and_exact_copy_counts_once(archives, tmp_path):
    accepted, _rejected = archives
    exact = copy_archive(accepted.archive, tmp_path, "exact")
    original = replay.load_archive(accepted.archive)
    copied = replay.load_archive(exact)
    assert original.status == copied.status == "complete" and copied.scope_id == exact.name
    renamed = private_root(tmp_path, "renamed") / ("scope-" + "0" * 32)
    shutil.copytree(exact, renamed)
    misnamed = replay.load_archive(renamed)
    assert misnamed.status == "invalid" and misnamed.problems == ("scope_directory_identity_mismatch",)
    sources, used, summary = reconcile_identities([original, copied, misnamed])
    assert len(used) == 1 and summary["duplicate_inputs"] == 1 and summary["invalid_inputs"] == 1
    assert [row["used"] for row in sources] == [True, False, False]
