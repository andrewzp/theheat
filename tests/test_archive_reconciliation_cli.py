"""Connected D2 proof: actual D1 SDK-fixture archives → fresh-process reconciliation.

Accepted, rejected and uncertain archives come from the real pipeline over
INVENTED offline transports; billing documents and retained state are INVENTED.
The report is reproduced byte-identically under one explicit clock.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_archive_usage import d2_accepted_script, d2_rejected_script, d2_uncertain_script
from tests.test_request_archive_sdk import FIXTURE, journey_env, private_root, run_journey

__all__ = ["journey_env"]
ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts/reconcile_request_archive.py"
FIXTURES = ROOT / "tests/fixtures/private_workflow"
AS_OF = "2026-10-23T12:00:00+00:00"


def cli(*args: str) -> tuple[int, dict, str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent-invented-home", "LC_ALL": "C", "LANG": "C",
           "NO_PROXY": "*", "no_proxy": "*", "NETRC": "/dev/null", "PYTHON_DOTENV_DISABLED": "1"}
    result = subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True,
                            timeout=120, cwd="/")
    return result.returncode, json.loads(result.stdout) if result.stdout.strip() else {}, result.stdout + result.stderr


def tree(path: Path) -> dict[str, str]:
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


@pytest.fixture
def workspace(journey_env, tmp_path):
    archives = [run_journey(script, root=private_root(tmp_path, name)).archive for name, script in (
        ("accepted", d2_accepted_script()), ("rejected", d2_rejected_script()), ("uncertain", d2_uncertain_script()))]
    inputs = private_root(tmp_path, "inputs")
    copies = {}
    for source in sorted(FIXTURES.iterdir()):
        target = inputs / source.name
        target.write_bytes(source.read_bytes())
        os.chmod(target, 0o600)
        copies[source.name] = target
    return archives, copies, tmp_path


def reconcile_args(archives, copies, out, *extra):
    args = ["reconcile", "--as-of", AS_OF, "--output-dir", str(out), "--scenario", "google-standard-paid-2026-10-02",
            "--account-binding", "anthropic:acct-invented-0001:proj-invented-0001",
            "--account-binding", "google:acct-invented-google-0001",
            "--billing-with-document", str(copies["billing-anthropic-itemized-invented.json"]),
            str(copies["original-document-invented.txt"]),
            "--billing", str(copies["billing-google-aggregate-invented.json"]),
            "--billing", str(copies["billing-anthropic-other-account-invented.json"]),
            "--state", str(copies["retained-state-invented.json"])]
    for archive in archives:
        args += ["--archive", str(archive)]
    return args + list(extra)


def test_fresh_process_reconciliation_is_conservative_reproducible_and_content_free(workspace):
    archives, copies, tmp_path = workspace
    before = {**tree(archives[0].parent), **tree(archives[1].parent), **tree(archives[2].parent),
              **{k: v for c in copies.values() for k, v in tree(c).items()}}
    out = private_root(tmp_path, "report")
    code, summary, raw = cli(*reconcile_args(archives, copies, out))
    assert code == 0, raw
    assert summary["status"] == "completed" and summary["written"] == ["new", "new"]
    assert summary["denominators"]["sdk_calls"] == 10 and summary["denominators"]["unknown_send_outcomes"] == 3
    assert summary["matches"] == 2 and summary["content_written_to_stdout"] is False
    report_bytes = (out / "reconciliation.json").read_bytes()
    report = json.loads(report_bytes)
    assert os.stat(out / "reconciliation.json").st_mode & 0o777 == 0o600
    matches = {(m["item_id"], m["matched_on"][0]) for m in report["reconciliation"]["matches"]}
    assert matches == {("inv-item-accepted-writer", "provider_request_id"),
                       ("inv-item-rejected-writer", "provider_response_id")}
    unmatched = {(u["account"], u["item_id"]): u["reason"] for u in report["reconciliation"]["unmatched_billing_items"]}
    assert unmatched[("acct-invented-OTHER", "inv-item-accepted-writer")] == "archive_account_scope_not_bound"
    assert unmatched[("acct-invented-0001", "inv-item-not-archived")] == "identifier_not_in_supplied_archives"
    [aggregate] = report["reconciliation"]["aggregate_comparisons"]
    assert aggregate["archive_account_binding"] == "operator_asserted" and aggregate["billed"]["net"] == "0.012500"
    assert aggregate["archive_responses_in_period"] == 5 and aggregate["named_scenario"] == "google-standard-paid-2026-10-02"
    assert report["priced_scenario"]["actual_cost_known"] is False
    assert report["retained_state_summary"]["source"] == "explicit_retained_state_file_read_only"
    assert report["retained_state_summary"]["budget_enforced"] is False
    roles = {(f["role"], f["sha256"]) for f in report["inputs"]["files"]}
    for name, role in (("billing-anthropic-itemized-invented.json", "billing_evidence"),
                       ("original-document-invented.txt", "original_document"),
                       ("retained-state-invented.json", "retained_state")):
        assert (role, hashlib.sha256(copies[name].read_bytes()).hexdigest()) in roles
    assert report["authority"] == {"settles_reservations": False, "enforces_ceiling": False,
                                   "changes_configuration": False, "grants_approval": False,
                                   "billing_truth": "operator_supplied_assertion"}
    for private in (FIXTURE["accepted_tweet"], "PRIMARY SIGNAL"):
        assert private not in raw and private not in report_bytes.decode()
    # Byte-identical reproduction under the same explicit clock in a new process.
    code, again, _ = cli(*reconcile_args(archives, copies, out))
    assert code == 0 and again["written"] == ["identical_existing", "identical_existing"]
    assert (out / "reconciliation.json").read_bytes() == report_bytes
    second = private_root(tmp_path, "report-two")
    code, other, _ = cli(*reconcile_args(archives, copies, second))
    assert code == 0 and (second / "reconciliation.json").read_bytes() == report_bytes
    # A different clock is different content: it refuses to overwrite.
    code, conflict, _ = cli(*reconcile_args(archives, copies, out)[:2], "2026-10-24T12:00:00+00:00",
                            *reconcile_args(archives, copies, out)[3:])
    assert code == 2 and conflict["error"] == "private_file_conflict"
    after = {**tree(archives[0].parent), **tree(archives[1].parent), **tree(archives[2].parent),
             **{k: v for c in copies.values() for k, v in tree(c).items()}}
    assert after == before  # Original inputs are untouched.


def test_conflicting_documents_are_quarantined_and_reported_as_gaps(workspace):
    archives, copies, tmp_path = workspace
    out = private_root(tmp_path, "report")
    code, summary, _ = cli(*reconcile_args(archives, copies, out, "--billing",
                                           str(copies["billing-anthropic-conflicting-invented.json"])))
    assert code == 1 and summary["status"] == "completed_with_gaps" and summary["quarantined"] == 1
    report = json.loads((out / "reconciliation.json").read_bytes())
    assert report["supplied_billing"]["quarantined"][0]["reason"] == "conflicting_document_identity"
    assert summary["matches"] == 0  # The conflicting statement cannot support any match.


def test_inspect_verifies_identity_and_export_renders_private_markdown(workspace):
    archives, copies, tmp_path = workspace
    out = private_root(tmp_path, "report")
    assert cli(*reconcile_args(archives, copies, out))[0] == 0
    code, inspected, _ = cli("inspect", str(out / "reconciliation.json"))
    assert code == 0 and inspected["status"] == "verified" and inspected["matches"] == 2
    code, exported, _ = cli("export", str(out / "reconciliation.json"), "--output", str(out / "view.md"))
    markdown = (out / "view.md").read_text()
    assert code == 0 and exported["status"] == "written" and markdown.startswith("# Private archive reconciliation")
    assert "not evidence of unpaid calls" in markdown and FIXTURE["accepted_tweet"] not in markdown
    assert markdown == (out / "reconciliation.md").read_text()
    tampered_dir = private_root(tmp_path, "tampered")
    report = json.loads((out / "reconciliation.json").read_bytes())
    report["reconciliation"]["matches"] = []
    tampered = tampered_dir / "reconciliation.json"
    tampered.write_text(json.dumps(report))
    os.chmod(tampered, 0o600)
    code, refused, _ = cli("inspect", str(tampered))
    assert code == 2 and refused["error"] == "report_identity_mismatch"


def test_validate_and_refusals_have_fixed_codes(workspace):
    archives, copies, tmp_path = workspace
    code, valid, _ = cli("validate", str(copies["billing-anthropic-itemized-invented.json"]),
                         "--document", str(copies["original-document-invented.txt"]))
    assert code == 0 and valid["document_check"] == "matched_explicit_file" and valid["items"] == 6
    loose = tmp_path / "loose.json"
    loose.write_bytes(copies["billing-google-aggregate-invented.json"].read_bytes())
    os.chmod(loose, 0o644)
    assert cli("validate", str(loose))[0] == 2
    code, naive, _ = cli(*reconcile_args(archives, copies, private_root(tmp_path, "o"))[:2], "2026-10-23T12:00:00",
                         *reconcile_args(archives, copies, private_root(tmp_path, "o2"))[3:])
    assert code == 2 and naive["error"] == "as_of_not_aware"
    assert cli("reconcile", "--archive", "/x")[0] == 64  # Missing required clock/output.
    for flags in (["send"], ["reconcile", "--settle"], ["validate", "/x", "--force"]):
        assert cli(*flags)[0] == 64


def test_cli_process_never_imports_provider_or_network_clients(workspace):
    archives, copies, tmp_path = workspace
    out = private_root(tmp_path, "report")
    argv = reconcile_args(archives, copies, out)
    probe = (f"import sys; sys.argv = ['reconcile'] + {argv!r}; sys.path.insert(0, {str(ROOT)!r}); import runpy\n"
             "import contextlib, io\n"
             "with contextlib.redirect_stdout(io.StringIO()):\n"
             f"    try: runpy.run_path({str(CLI)!r}, run_name='__main__')\n"
             "    except SystemExit as exc: code = exc.code\n"
             "print(code, sorted({m.split('.')[0] for m in sys.modules} & "
             "{'anthropic', 'httpx', 'httpx2', 'requests', 'urllib3', 'pickle'}))")
    result = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=120,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, cwd="/")
    assert result.stdout.strip() == "0 []", result.stdout + result.stderr


@pytest.mark.parametrize("fixture", ["billing-anthropic-itemized-invented.json", "billing-google-aggregate-invented.json"])
def test_cli_handles_absent_and_named_projects_without_tracebacks(workspace, fixture):
    archives, copies, tmp_path = workspace
    source = json.loads(copies[fixture].read_bytes())
    source["scope"].pop("project", None)
    selected = []
    for index, project in enumerate((None, "p")):
        raw = json.loads(json.dumps(source))
        raw["document"]["id"] = f"project-statement-{index}"
        if project is not None:
            raw["scope"]["project"] = project
        target = copies[fixture].parent / f"project-{index}.json"
        target.write_text(json.dumps(raw))
        os.chmod(target, 0o600)
        selected += ["--billing", str(target)]
    out = private_root(tmp_path, "project-report")
    code, summary, raw_output = cli("reconcile", "--archive", str(archives[0]), *selected,
                                     "--as-of", AS_OF, "--output-dir", str(out))
    assert code == 0 and summary["status"] == "completed" and "Traceback" not in raw_output
    report = json.loads((out / "reconciliation.json").read_bytes())
    assert {row["project"] for row in report["supplied_billing"]["billed_totals_by_scope"]} == {None, "p"}
