"""Fresh-process private copy-review CLI: build, verify, import; SYNTHETIC ballots only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_private_copy_pack import (
    FIXTURE, MANUAL_TEXT, ballot, journey_env, make_review_workspace, private_root, rating,
)

__all__ = ["journey_env"]
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/private_copy_review.py"
CREATED = "2026-10-23T12:00:00+00:00"
AS_OF = "2026-10-23T13:00:00+00:00"


def cli(*args: str) -> tuple[int, dict, str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-invented-home", "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1"}
    result = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True,
                            timeout=120, cwd="/")
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else {}, result.stdout + result.stderr


@pytest.fixture
def built(journey_env, tmp_path):
    workspace = make_review_workspace(tmp_path)
    private_dir = private_root(tmp_path, "private")
    pack_dir = tmp_path / "pack"
    args = ["build", "--selection", str(workspace["selection"]), "--created-at", CREATED,
            "--pack-dir", str(pack_dir), "--private-dir", str(private_dir)]
    for archive in workspace["archives"]:
        args += ["--archive", str(archive)]
    code, summary, raw = cli(*args)
    return workspace, private_dir, pack_dir, code, summary, raw


def test_build_writes_detached_private_pack_and_held_report(built):
    workspace, private_dir, pack_dir, code, summary, raw = built
    assert code == 1 and summary["status"] == "pack_built_with_held_pairs"  # One unqualified pair is held.
    assert summary["pairs"] == 2 and summary["held_pairs"] == 1 and summary["origin_leak_scan"] == "clean"
    assert sorted(os.listdir(pack_dir)) == ["app.js", "index.html", "pack-data.js", "styles.css"]
    assert all(os.stat(pack_dir / name).st_mode & 0o777 == 0o600 for name in os.listdir(pack_dir))
    assert os.stat(pack_dir).st_mode & 0o777 == 0o700
    for name in ("index.html", "app.js", "styles.css"):
        assert (pack_dir / name).read_bytes() == (ROOT / "tools/private-copy-review" / name).read_bytes()
    private = json.loads((private_dir / summary["private_record"]).read_bytes())
    assert private["pack_id"] == summary["pack_id"] and len(private["provenance"]) == 4
    for text in (FIXTURE["accepted_tweet"], MANUAL_TEXT):
        assert text not in raw  # stdout is content-free.
    code, verified, _ = cli("verify", "--private", str(private_dir / summary["private_record"]),
                            "--pack-dir", str(pack_dir))
    assert code == 0 and verified == {"status": "verified", "pack_id": summary["pack_id"], "page_data_matches": True,
                                      "origin_leaks": 0}


def test_import_in_a_fresh_process_and_idempotent_retry(built, tmp_path):
    workspace, private_dir, pack_dir, _, summary, _ = built
    private_path = private_dir / summary["private_record"]
    public = json.loads((pack_dir / "pack-data.js").read_text().split(" = ", 1)[1].rstrip(";\n"))
    ballots = private_root(tmp_path, "ballots")
    paths = []
    for name, data in (("one.json", ballot(public, [rating(public["pairs"][0], "A"), rating(public["pairs"][1], "tie")])),
                       ("two.json", ballot(public, [rating(public["pairs"][0], "abstain")], rater="synthetic-rater-2"))):
        (ballots / name).write_bytes(data)
        os.chmod(ballots / name, 0o600)
        paths += ["--ballot", str(ballots / name)]
    out = private_root(tmp_path, "imports")
    code, imported, raw = cli("import", "--private", str(private_path), *paths, "--as-of", AS_OF,
                              "--output-dir", str(out))
    assert code == 0 and imported["status"] == "imported" and imported["real_human_ratings_added"] == 0
    assert imported["synthetic_fixture_preferences"] == {"A": 1, "B": 0, "tie": 1, "abstain": 1}
    assert "SYNTHETIC fixture note" not in raw
    report = json.loads((out / imported["report"]).read_bytes())
    # The unchanged summarizer labels any ballots "recorded_human_ballots"; the import report overrides
    # that meaning explicitly for synthetic fixtures instead of editing the existing contract.
    assert report["synthetic_fixture_summary"]["preference_result"] == "recorded_human_ballots"
    assert report["interpretation"]["synthetic_fixture_summary"] == "synthetic_fixture_ballots_are_not_human_preference"
    again = cli("import", "--private", str(private_path), *paths, "--as-of", AS_OF, "--output-dir", str(out))
    assert again[0] == 0 and again[1]["written"] == "identical_existing"


def test_cli_refusals_have_fixed_codes(built, tmp_path):
    workspace, private_dir, pack_dir, _, summary, _ = built
    args = ["build", "--selection", str(workspace["selection"]), "--created-at", CREATED,
            "--private-dir", str(private_dir)]
    for archive in workspace["archives"]:
        args += ["--archive", str(archive)]
    assert cli(*args, "--pack-dir", str(pack_dir))[1]["error"] == "pack_dir_must_be_new"
    assert cli(*args, "--pack-dir", str(private_dir / "inside"))[1]["error"] == "pack_dir_inside_private_dir"
    naive = list(args)
    naive[naive.index(CREATED)] = "2026-10-23T12:00:00"
    assert cli(*naive, "--pack-dir", str(tmp_path / "new"))[1]["error"] == "time_not_aware"
    tampered = json.loads((private_dir / summary["private_record"]).read_bytes())
    tampered["pairs_input"][0]["source_context"] += " changed"
    target = private_root(tmp_path, "tampered") / "record.json"
    target.write_text(json.dumps(tampered))
    os.chmod(target, 0o600)
    code, refused, _ = cli("verify", "--private", str(target), "--pack-dir", str(pack_dir))
    assert code == 2 and refused["error"] == "pack_changed_since_export"
    for flags in (["serve"], ["build", "--judge"], ["import", "--auto-rate"]):
        assert cli(*flags)[0] == 64


def test_no_pair_selection_is_a_useful_held_report(journey_env, tmp_path):
    workspace = make_review_workspace(tmp_path)
    selection = workspace["selection_value"]
    selection["pairs"] = [selection["pairs"][2]]  # Only the unqualified pair.
    path = workspace["inputs"] / "held-only.json"
    path.write_text(json.dumps(selection))
    os.chmod(path, 0o600)
    private_dir = private_root(tmp_path, "private")
    args = ["build", "--selection", str(path), "--created-at", CREATED, "--pack-dir", str(tmp_path / "never"),
            "--private-dir", str(private_dir)]
    for archive in workspace["archives"]:
        args += ["--archive", str(archive)]
    code, held, _ = cli(*args)
    assert code == 1 and held["status"] == "held_no_pair"
    assert held["reasons"] == ["evidence_not_qualified_by_explicit_review"]
    assert not (tmp_path / "never").exists()
    report = json.loads((private_dir / held["held_report"]).read_bytes())
    assert report["result"] == "held_no_pair" and "fabricated no alternative" in report["interpretation"]
