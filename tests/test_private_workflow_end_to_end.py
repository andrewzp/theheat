"""Final connected private journey, every CLI in a fresh process with sockets trapped.

SDK fixtures (actual pipeline + pinned SDKs, INVENTED transports) -> private archives
-> usage/billing reconciliation with an INVENTED invoice mismatch -> blind copy pack
with a manual edit and a held unqualified pair -> SYNTHETIC ratings (rating, tie,
abstention) -> INVENTED receipt-bound post snapshot -> one diagnosis. A second
journey with tampered/partial inputs must hold. Nothing here approves, replays,
releases budget, posts or proves quality, invoice truth or human preference.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from src.editorial.revisions import text_hash
from tests.test_operator_diagnosis import TWEET, build_scenario_archives, retained_state, write_private, explicit_node_fixture
from src.evaluation import operator_diagnosis as diagnosis
from tests.test_private_copy_pack import MANUAL_TEXT, ballot, qualification, rating
from tests.test_request_archive_sdk import FIXTURE, journey_env, private_root

__all__ = ["journey_env", "explicit_node_fixture"]
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/private_workflow"
AS_OF = "2026-10-23T12:00:00+00:00"
CLIENT_MODULES = {"anthropic", "google", "httpx", "httpx2", "requests", "urllib3", "pickle"}


def fresh(cli: str, *args: str) -> tuple[int, dict, list[str]]:
    """Run one CLI in a new interpreter with every socket connect refused."""
    code = "\n".join([
        "import json, runpy, socket, sys",
        "def refuse(*a, **k): raise OSError('external network trapped')",
        "socket.socket.connect = refuse",
        "socket.create_connection = refuse",
        f"sys.argv = {json.dumps([cli, *args])}",
        "status = 0",
        "try:",
        f"    runpy.run_path({json.dumps(cli)}, run_name='__main__')",
        "except SystemExit as exc:",
        "    status = exc.code",
        f"loaded = sorted({{m.split('.')[0] for m in sys.modules}} & set({sorted(CLIENT_MODULES)!r}))",
        "sys.stderr.write('\\nLOADED=' + json.dumps(loaded) + '\\n')",
        "sys.exit(status)",
    ])
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-invented-home", "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1",
           "THEHEAT_DIAGNOSIS_NODE": diagnosis.NODE}
    result = subprocess.run([sys.executable, "-I", "-c", code], env=env, capture_output=True, text=True,
                            timeout=180, cwd="/")
    loaded = json.loads(result.stderr.rsplit("LOADED=", 1)[1].strip()) if "LOADED=" in result.stderr else ["unknown"]
    try:
        payload = json.loads(result.stdout) if result.stdout.strip() else {}
    except ValueError:
        payload = {"unparseable_stdout": True}
    return result.returncode, payload, loaded


def digest_tree(*paths: Path) -> dict[str, str]:
    out = {}
    for base in paths:
        for path in sorted([base] if base.is_file() else base.rglob("*")):
            if path.is_file():
                out[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def cli(name: str) -> str:
    return str(ROOT / "scripts" / name)


@pytest.fixture
def journey(journey_env, tmp_path):
    runs = build_scenario_archives(tmp_path)
    physical_after_capture = sum(len(run.providers.physical) for run in runs.values())
    archives = {name: run.archive for name, run in runs.items()}
    inputs = private_root(tmp_path, "inputs")
    for source in sorted(FIXTURES.iterdir()):
        write_private(inputs, source.name, source.read_bytes())
    mismatch = json.loads((FIXTURES / "billing-anthropic-itemized-invented.json").read_text())
    mismatch["document"] = {"id": "INVENTED-anthropic-statement-0002"}
    mismatch["items"] = [{"item_id": "inv-item-tax", "kind": "tax", "amount": "0.0004"}]  # Conflicts with doc 0001.
    write_private(inputs, "billing-anthropic-mismatch-invented.json", mismatch)
    write_private(inputs, "state.json", retained_state(runs))
    return runs, archives, inputs, tmp_path, physical_after_capture


def build_copy_pack(runs, archives, inputs, tmp_path):
    from src.two_bot.request_archive_replay import load_archive
    accepted, second = load_archive(archives["accepted"]), load_archive(archives["second"])
    bundle = accepted.inputs[0]["bundle_sha256"]
    one = {"scope_id": accepted.scope_id, "candidate_text_sha256": text_hash(TWEET)}
    two = {"scope_id": second.scope_id, "candidate_text_sha256": text_hash(FIXTURE["revised_tweet"])}
    evidence = {"bundle_sha256": bundle, "qualification": qualification(), "evidence_scope": "observed",
                "evidence_time": "2032-03-01T00:00:00+00:00", "source_context": "Invented fixture: a thermal detection."}
    qualified = lambda ref: {"archive_candidate": ref, "factual_status": "qualified", "rejection_reasons": [],  # noqa: E731
                             "material_claims": ["invented value"]}
    manual = {"manual_edit": {"text": MANUAL_TEXT, "edited_from": one, "author_assertion": "invented-operator"},
              "factual_status": "qualified", "rejection_reasons": [], "material_claims": ["invented value"]}
    selection = {"schema": "theheat.copy-review-selection/v1", "pairs": [
        {"label": "model vs model", "evidence": evidence, "candidates": [qualified(one), qualified(two)]},
        {"label": "model vs manual edit", "evidence": evidence, "candidates": [qualified(one), manual]},
        {"label": "unqualified", "evidence": {**evidence, "qualification": qualification("unverified", "not_reviewed")},
         "candidates": [qualified(one), qualified(two)]}]}
    path = write_private(inputs, "selection.json", selection)
    private_dir = private_root(tmp_path, "copy-private")
    args = ["build", "--selection", str(path), "--created-at", "2026-10-23T09:00:00+00:00",
            "--pack-dir", str(tmp_path / "copy-pack"), "--private-dir", str(private_dir)]
    for name in ("accepted", "second"):
        args += ["--archive", str(archives[name])]
    code, built, loaded = fresh(cli("private_copy_review.py"), *args)
    assert code == 1 and built["status"] == "pack_built_with_held_pairs" and loaded == []
    public = json.loads((tmp_path / "copy-pack" / "pack-data.js").read_text().split(" = ", 1)[1].rstrip(";\n"))
    first, second_pair = public["pairs"]
    ballots = private_root(tmp_path, "ballots")
    paths = [write_private(ballots, "rater-1.json", ballot(public, [rating(first, "A"), rating(second_pair, "tie")],
                                                          rated_at="2026-10-23T10:00:00Z")),
             write_private(ballots, "rater-2.json", ballot(public, [rating(first, "abstain")], rater="synthetic-rater-2",
                                                          rated_at="2026-10-23T10:05:00Z"))]
    imports = private_root(tmp_path, "copy-imports")
    code, imported, loaded = fresh(cli("private_copy_review.py"), "import", "--private",
                                   str(private_dir / built["private_record"]),
                                   *sum((["--ballot", str(p)] for p in paths), []), "--as-of", AS_OF,
                                   "--output-dir", str(imports))
    assert code == 0 and imported["real_human_ratings_added"] == 0 and loaded == []
    return private_dir / built["private_record"], imports / imported["report"]


def reconcile(archives, inputs, tmp_path, names, out_name):
    out = private_root(tmp_path, out_name)
    args = ["reconcile", "--as-of", AS_OF, "--output-dir", str(out), "--scenario", "google-standard-paid-2026-10-02",
            "--account-binding", "anthropic:acct-invented-0001:proj-invented-0001",
            "--account-binding", "google:acct-invented-google-0001",
            "--billing-with-document", str(inputs / "billing-anthropic-itemized-invented.json"),
            str(inputs / "original-document-invented.txt"),
            "--billing", str(inputs / "billing-anthropic-mismatch-invented.json"),
            "--billing", str(inputs / "billing-google-aggregate-invented.json")]
    for name in names:
        args += ["--archive", str(archives[name])]
    code, summary, loaded = fresh(cli("reconcile_request_archive.py"), *args)
    assert code == 1 and summary["quarantined"] == 1 and loaded == []  # The invoice mismatch is a held gap.
    return out / "reconciliation.json"


def test_complete_synthetic_private_workflow(journey):
    runs, archives, inputs, tmp_path, physical = journey
    before = digest_tree(*archives.values(), inputs)
    reconciliation = reconcile(archives, inputs, tmp_path, list(archives), "reconciliation")
    copy_private, copy_import = build_copy_pack(runs, archives, inputs, tmp_path)
    out = private_root(tmp_path, "diagnosis")
    args = ["diagnose", "--as-of", AS_OF, "--output-dir", str(out), "--reconciliation", str(reconciliation),
            "--copy-private", str(copy_private), "--copy-import", str(copy_import), "--state", str(inputs / "state.json")]
    for path in archives.values():
        args += ["--archive", str(path)]
    code, summary, loaded = fresh(cli("theheat_diagnose.py"), *args)
    assert code == 0, summary
    assert summary["status"] == "completed" and summary["promotion"] == "HOLD" and loaded == []
    report = json.loads((out / "diagnosis.json").read_bytes())
    statuses = {c["component"]: c["status"] for c in report["components"] if c["component"] != "archive"}
    assert statuses == {"capture_identity": "verified", "reconciliation": "verified", "copy_review": "verified",
                        "copy_ratings": "verified", "retained_state": "verified"}
    overview = report["overview"]
    assert overview["source"]["archives"] == 9 and overview["source"]["distinct_bundles"] == 2
    assert overview["checks"]["accepted"] == 3 and overview["checks"]["rejected"] == 4
    assert overview["spend"]["unknown_send_outcomes"] == 3 and overview["spend"]["billing_matches"] == 1
    assert overview["spend"]["quarantined_billing"] == 1 and overview["spend"]["actual_cost_known"] is False
    ratings = overview["preference"]["ratings"]
    assert ratings["synthetic_fixture_preferences_by_display_side"] == {"A": 1, "B": 0, "tie": 1, "abstain": 1}
    assert ratings["real_human_ratings_added"] == 0 and overview["preference"]["held_pairs"] == 1
    assert sorted(overview["preference"]["pair_kinds"]) == ["model_vs_manual_edit", "model_vs_model"]
    publication = overview["publication"]
    assert (publication["joined_to_archived_candidate"], publication["unjoined_posts"],
            publication["manual_or_edited"], publication["engagement_lift"]) == (1, 1, 1, None)
    accepted = [c for c in report["candidates"] if c["publication"]["status"] == "joined"]
    assert len(accepted) == 1
    assert accepted[0]["copy_review"] == {"in_pack": True, "pair_kinds": ["model_vs_manual_edit", "model_vs_model"]}
    uncertain = [g for g in report["generations"] if g["terminal"] != "unavailable"
                 and g["terminal"].get("kill_stage") == "pipeline_error"]
    assert uncertain and all(any(d.startswith("unknown_send_outcome") for d in g["dispositions"]) for g in uncertain)
    assert report["decision"] == {"promotion": "HOLD", "weekly_review_decision": "HOLD", "automatic_changes": False,
                                  "approvals": "none", "budget_released": False, "provider_replay": False,
                                  "publication_authorized": False}
    # Fresh-process restore and byte-identical reproduction; inputs untouched; no sends happened.
    code, verified, loaded = fresh(cli("theheat_diagnose.py"), "verify", "--output-dir", str(out))
    assert code == 0 and verified["status"] == "complete" and loaded == []
    code, again, _ = fresh(cli("theheat_diagnose.py"), *args)
    assert code == 0 and set(again["written"].values()) == {"identical_existing"}
    after = digest_tree(*archives.values(), inputs)
    assert {path: after.get(path) for path in before} == before  # Every original input byte-identical.
    assert sum(len(run.providers.physical) for run in runs.values()) == physical
    page = (out / "diagnosis.html").read_text()
    for private in (TWEET, MANUAL_TEXT, FIXTURE["factual_failure"], "SYNTHETIC fixture note"):
        assert private not in page and private not in (out / "diagnosis.md").read_text()
    exports = private_root(tmp_path, "exports")
    code, exported, _ = fresh(cli("theheat_diagnose.py"), "export-copy", "--archive", str(archives["factual"]),
                              "--candidate", text_hash(TWEET), "--output", str(exports / "factual.json"))
    payload = json.loads((exports / "factual.json").read_bytes())
    assert code == 0 and exported["content_written_to_stdout"] is False and payload["text"] == TWEET
    assert any(FIXTURE["factual_failure"] in r["reason"] for r in payload["stage_reasons"])


def test_tampered_and_partial_inputs_hold_instead_of_reporting_clean(journey):
    runs, archives, inputs, tmp_path, _ = journey
    reconciliation = reconcile(archives, inputs, tmp_path, ["accepted", "factual"], "reconciliation-subset")
    copy_private, copy_import = build_copy_pack(runs, archives, inputs, tmp_path)
    damaged = private_root(tmp_path, "damaged")
    copies = {}
    for name in ("accepted", "critic", "safety"):
        target = damaged / name
        target.mkdir(mode=0o700)
        shutil.copytree(archives[name], target / archives[name].name)
        for path in [target / archives[name].name, *(target / archives[name].name).rglob("*")]:
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
        copies[name] = target / archives[name].name
    artifact = sorted((copies["accepted"] / "artifacts").iterdir())[0]
    artifact.write_bytes(artifact.read_bytes() + b"tamper")
    manifest = copies["critic"] / "manifest.jsonl"
    manifest.write_bytes(manifest.read_bytes()[:-40])
    record = json.loads(copy_private.read_bytes())
    record["pairs_input"][0]["source_context"] += " edited after export"
    tampered_private = write_private(inputs, "copy-private-edited.json", record)
    out = private_root(tmp_path, "diagnosis-held")
    args = ["diagnose", "--as-of", AS_OF, "--output-dir", str(out), "--reconciliation", str(reconciliation),
            "--copy-private", str(tampered_private), "--copy-import", str(copy_import)]
    for path in copies.values():
        args += ["--archive", str(path)]
    code, summary, loaded = fresh(cli("theheat_diagnose.py"), *args)
    assert code == 1 and summary["status"] == "completed_with_held_components" and loaded == []
    report = json.loads((out / "diagnosis.json").read_bytes())
    archive_statuses = sorted(c["status"] for c in report["components"] if c["component"] == "archive")
    assert archive_statuses == ["complete", "incomplete", "invalid"]
    held = {c["component"]: c["status"] for c in report["components"] if c["component"] != "archive"}
    # The ratings bound to the edited pack are held with it, never shown as zero ratings.
    assert held == {"capture_identity": "verified", "reconciliation": "lineage_mismatch", "copy_review": "invalid",
                    "copy_ratings": "held", "retained_state": "absent"}
    # Supplied but held components are labeled held, never absent and never zero (G9: was "absent").
    assert report["overview"]["spend"] == {"status": "held", "component_status": "lineage_mismatch"}
    assert report["overview"]["preference"] == {"status": "held", "component_status": "invalid"}
    assert report["overview"]["publication"] == {"status": "absent"}
    invalid_scope = next(c["scope_id"] for c in report["components"] if c.get("status") == "invalid"
                         and c["component"] == "archive")
    assert all(c["scope_id"] != invalid_scope for c in report["candidates"])  # Tampered evidence joins nothing.
    incomplete = [c for c in report["candidates"] if c["archive_status"] == "incomplete"]
    assert incomplete and all("archive_incomplete" in c["dispositions"] for c in incomplete)
    assert report["decision"]["promotion"] == "HOLD"
    code, verified, _ = fresh(cli("theheat_diagnose.py"), "verify", "--output-dir", str(out))
    assert code == 0 and verified["status"] == "complete"  # The report is intact; its inputs are not clean.
    # Missing marker = interrupted: never readable as a complete diagnosis.
    partial = private_root(tmp_path, "partial-copy")
    for name in ("diagnosis.json", "diagnosis.md"):
        write_private(partial, name, (out / name).read_bytes())
    code, refused, _ = fresh(cli("theheat_diagnose.py"), "verify", "--output-dir", str(partial))
    assert code == 1 and refused == {"status": "incomplete", "reason": "completion_marker_missing"}
