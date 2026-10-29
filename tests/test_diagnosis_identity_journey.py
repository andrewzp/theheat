"""G9 fresh-process operator journey: reconcile, copy pack/import, diagnose, verify.

Every CLI runs in a new interpreter with sockets trapped (the existing ``fresh``
runner). Inputs are INVENTED retained evidence: actual pipeline/SDK archives on
offline transports, invented billing, synthetic ballots and an invented state.
The journey covers unique, exact repeat, copied export, identity collision,
missing usage, incomplete route evidence, contradictory batch results and a
stale/mismatched optional component, then inspects the actual JSON, Markdown and
HTML artifacts for the same exclusions, known/unknown quantities, source
references and candidate identities. Nothing here approves, replays or posts.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evaluation import operator_diagnosis as diagnosis
from src.two_bot import request_archive_replay as replay
from tests import test_batch_result_journal as receipts
from tests import test_batch_worker_journal as workers
from tests.test_archive_identity_followup import _Scope, _relabel
from tests.test_diagnosis_identity import older_report
from tests.test_operator_diagnosis import TWEET, explicit_node_fixture, write_private
from tests.test_private_copy_pack import MANUAL_TEXT
from tests.test_private_workflow_end_to_end import AS_OF, build_copy_pack, cli, fresh, journey, reconcile
from tests.test_request_archive_batch import fresh_store
from tests.test_request_archive_batch_replay import copy_scope
from tests.test_request_archive_review_closure import _usage, collected, jsonl, keyed, line, stream_case
from tests.test_request_archive_sdk import FIXTURE, journey_env, private_root
from tests.two_bot import test_batch_contract as contracts

__all__ = ["journey_env", "explicit_node_fixture", "journey", "keyed"]
inputs = contracts.inputs
store = workers.store
HOSTILE_ID = "<img src=x onerror=alert(1)>|pipe"
PRIVATE = (TWEET, MANUAL_TEXT, FIXTURE["factual_failure"], FIXTURE["critic_kill_reason"], "SYNTHETIC fixture note")


@pytest.fixture
def routes(store, inputs, keyed, tmp_path):
    """Invented v2 route captures: valid, missing usage, cut entity and a contradictory pair."""
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    valid = line(pair, usage=_usage(pair, 100))
    missing = deepcopy(valid)
    missing["custom_id"] = "invented-missing-usage-0001"
    del missing["result"]["message"]["usage"]
    hostile, contradicting = deepcopy(valid), deepcopy(valid)
    hostile["custom_id"] = contradicting["custom_id"] = HOSTILE_ID
    contradicting["result"]["message"]["usage"]["input_tokens"] = 1000

    def make(name, results):
        return collected(tmp_path, inputs, name, results=results)[0].directory
    return {"valid": make("route-valid", jsonl(valid, missing)), "cut": make("route-cut", stream_case("partial_jsonl", pair)),
            "hostile_a": make("route-hostile-a", jsonl(hostile)),
            "hostile_b": make("route-hostile-b", jsonl(contradicting))}


def diagnose_cli(out: Path, archives: list, *, reconciliation=None, copy_private=None, copy_import=None,
                 state=None) -> tuple[int, dict, dict]:
    args = ["diagnose", "--as-of", AS_OF, "--output-dir", str(out)]
    for flag, value in (("--reconciliation", reconciliation), ("--copy-private", copy_private),
                        ("--copy-import", copy_import), ("--state", state)):
        if value is not None:
            args += [flag, str(value)]
    for path in archives:
        args += ["--archive", str(path)]
    code, summary, loaded = fresh(cli("theheat_diagnose.py"), *args)
    assert loaded == [], loaded
    verified_code, verified, _ = fresh(cli("theheat_diagnose.py"), "verify", "--output-dir", str(out))
    assert verified_code == 0 and verified["status"] == "complete", verified
    return code, summary, json.loads((out / "diagnosis.json").read_bytes())


def views(out: Path) -> dict[str, str]:
    return {name: (out / f"diagnosis.{name}").read_text() for name in ("json", "md", "html")}


def assert_views_agree(report: dict, rendered: dict[str, str]) -> None:
    """Every exclusion, known/unknown label, source reference and candidate identity is in all three views."""
    md, page = rendered["md"], rendered["html"]
    required = {report["identity_reconciliation"]["status"]}
    for component in report["components"]:
        required.add(component["status"])
        if component["component"] == "archive":
            required |= {component["identity"], component["manifest_sha256"], str(component["scope_id"])}
        if "reason" in component:
            required.add(component["reason"])
    for group in report["identity_reconciliation"]["conflict_groups"]:
        required |= {group["scope_id"], *group["manifest_sha256s"]}
    for candidate in report["candidates"]:
        required |= {candidate["anchor"], candidate["candidate_text_sha256"], candidate["decision"]}
    for post in report["unjoined_posts"]:
        required |= {post["tweet_id"], post["join"]}
    spend = report["overview"]["spend"]
    required |= set(spend.get("token_totals_unknown_reasons", [])) | {spend["status"]}
    required |= {action["code"] for action in report["next_actions"]}
    if "routes" in report:
        required |= {report["routes"]["route_totals_status"], *report["routes"]["route_totals_unknown_reasons"]}
    for value in sorted(required):
        assert value in rendered["json"] and value in md and value in page, value
    for text in PRIVATE:
        assert text not in md and text not in page and text not in rendered["json"]
    assert "<script" not in page.lower() and "<form" not in page and "default-src 'none'" in page
    assert "<img" not in page and "<img" not in md  # provider-supplied IDs stay inert text


def semantic(report: dict) -> dict:
    """Contributions only; a component file's own hash is provenance (a repeated-input report is another file)."""
    from tests.test_diagnosis_identity import report_semantics
    value = report_semantics(report)
    value["components"] = [{k: v for k, v in c.items() if k != "report_sha256"} for c in value["components"]]
    return value


def test_fresh_process_identity_journey_across_json_markdown_and_html(journey, routes, monkeypatch):
    runs, archives, inputs_dir, tmp_path, physical = journey
    names = list(archives)
    paths = list(archives.values())
    state = inputs_dir / "state.json"
    reconciliation = reconcile(archives, inputs_dir, tmp_path, names, "reconciliation")
    repeated_reconciliation = reconcile(archives, inputs_dir, tmp_path, names + names[:3], "reconciliation-repeat")
    copy_private, copy_import = build_copy_pack(runs, archives, inputs_dir, tmp_path)
    accepted = archives["accepted"]
    full = {"reconciliation": reconciliation, "copy_private": copy_private, "copy_import": copy_import,
            "state": state}

    code, summary, unique = diagnose_cli(private_root(tmp_path, "d-unique"), paths, **full)
    assert code == 0 and summary["identity"]["status"] == "consistent"
    assert_views_agree(unique, views(tmp_path / "d-unique"))
    assert unique["overview"]["preference"]["ratings"]["real_human_ratings_added"] == 0

    # Exact repeats, a byte-identical copied export and a repeated-input reconciliation count once.
    copy = copy_scope(_Scope(accepted), tmp_path, "accepted-copy")
    for name, supplied, rec in (("d-repeat", paths + paths, reconciliation),
                                ("d-copy", [copy, *paths], repeated_reconciliation)):
        code, summary, report = diagnose_cli(private_root(tmp_path, name), supplied, **(full | {"reconciliation": rec}))
        assert code == 0 and summary["held_components"] == [], (name, summary)
        assert semantic(report) == semantic(unique), name
        assert report["identity_reconciliation"]["duplicate_inputs"] >= 1
        assert "none_repeated_inputs_counted_once" in summary["next_actions"]
        assert_views_agree(report, views(tmp_path / name))

    # An identity collision holds every affected count and join; nothing is chosen.
    collision = _relabel(accepted, tmp_path, "accepted-collision")
    for name, supplied in (("d-collision", [*paths, collision]), ("d-collision-reversed", [collision, *paths[::-1]])):
        code, summary, report = diagnose_cli(private_root(tmp_path, name), supplied, **full)
        assert code == 1 and summary["identity"]["status"] == "conflict_quarantined"
        held = {c["component"]: c["status"] for c in summary["held_components"]}
        assert held == {"capture_identity": "conflict_quarantined", "reconciliation": "held_identity_conflict",
                        "copy_review": "held_identity_conflict", "copy_ratings": "held"}
        scope = replay.load_archive(accepted).scope_id
        assert all(c["scope_id"] != scope for c in report["candidates"])
        assert report["overview"]["publication"]["joined_to_archived_candidate"] == 0
        assert report["overview"]["spend"] == {"status": "held", "component_status": "held_identity_conflict"}
        assert {"compare_conflicting_exports", "resolve_capture_identity_first"} <= set(summary["next_actions"])
        assert_views_agree(report, views(tmp_path / name))
    first = json.loads((tmp_path / "d-collision" / "diagnosis.json").read_bytes())
    second = json.loads((tmp_path / "d-collision-reversed" / "diagnosis.json").read_bytes())
    assert semantic(first) == semantic(second)

    # Route evidence: missing usage, a cut entity and contradictory results stay unknown, never zero.
    route_paths = [routes["valid"], routes["cut"], routes["hostile_a"], routes["hostile_b"]]
    code, summary, report = diagnose_cli(private_root(tmp_path, "d-routes"), [*paths, *route_paths], **full)
    assert code == 1  # the cut entity leaves its archive incomplete
    totals = report["routes"]
    assert totals["route_totals_status"] == "incomplete"
    assert {"archive_incomplete", "result_conflict", "route_evidence_gap",
            "result_line_usage_not_present"} <= set(totals["route_totals_unknown_reasons"])
    # The cut entity's retained default line also differs from the valid capture's line for one custom ID.
    conflict = next(c for c in totals["result_conflicts"] if c["custom_id"] == HOSTILE_ID)
    assert len(conflict["sources"]) == 2 and len(totals["result_conflicts"]) == 2
    assert "totals_are_known_partial_subtotals" in summary["next_actions"]
    rendered = views(tmp_path / "d-routes")
    assert_views_agree(report, rendered)
    assert r"\u003cimg src=x onerror=alert(1)\u003e\u007cpipe" in rendered["md"]
    assert "&lt;img src=x onerror=alert(1)&gt;|pipe" in rendered["html"]

    # Stale or mismatched optional components are held, labeled and never repaired.
    mismatched = reconcile(archives, inputs_dir, tmp_path, ["accepted", "factual"], "reconciliation-subset")
    sealed = write_private(inputs_dir, "older-reconciliation.json",
                           older_report([replay.load_archive(p) for p in paths + [accepted]], monkeypatch))
    sealed_bytes = sealed.read_bytes()
    for name, supplied, rec, status in (
            ("d-mismatch", [archives["second"], archives["critic"]], mismatched, "lineage_mismatch"),
            ("d-older", paths, sealed, "unverifiable_identity")):
        code, summary, report = diagnose_cli(private_root(tmp_path, name), supplied,
                                             **(full | {"reconciliation": rec}))
        assert code == 1 and {"component": "reconciliation", "status": status} in summary["held_components"]
        assert report["overview"]["spend"] == {"status": "held", "component_status": status}
        assert_views_agree(report, views(tmp_path / name))
    assert sealed.read_bytes() == sealed_bytes  # the older sealed component was read, never rewritten
    # No provider was called anywhere in the journey.
    assert sum(len(run.providers.physical) for run in runs.values()) == physical
    assert diagnosis.VIEW_RENDERER.endswith("/v4")


def test_mixed_v1_v2_reconciliation_with_scenario_and_aggregate_billing_reaches_diagnosis(journey, routes):
    """Found while proving unique-input compatibility: G6-era reconcile crashed (KeyError 'call')."""
    runs, archives, inputs_dir, tmp_path, _ = journey
    mixed = [archives["accepted"], archives["factual"], routes["valid"]]
    out = private_root(tmp_path, "mixed-reconciliation")
    args = ["reconcile", "--as-of", AS_OF, "--output-dir", str(out), "--scenario", "google-standard-paid-2026-10-02",
            "--account-binding", "google:acct-invented-google-0001",
            "--billing", str(inputs_dir / "billing-google-aggregate-invented.json")]
    for path in mixed:
        args += ["--archive", str(path)]
    code, summary, loaded = fresh(cli("reconcile_request_archive.py"), *args)
    assert loaded == [] and code == 0 and summary["identity"]["counted_captures"] == 3, summary
    report = json.loads((out / "reconciliation.json").read_bytes())
    comparison, = report["reconciliation"]["aggregate_comparisons"]
    eligible = [row for row in report["priced_scenario"]["rows"] if row["disposition"] == "eligible"]
    assert comparison["scenario_token_component_usd"] is not None and eligible and all("call" in r for r in eligible)
    assert {row["reasons"][0] for row in report["priced_scenario"]["rows"] if "route" in row} == {
        "route_family_not_in_named_scenario"}
    code, summary, diagnosed = diagnose_cli(private_root(tmp_path, "d-mixed"), mixed,
                                            reconciliation=out / "reconciliation.json")
    assert code == 0 and {"component": "reconciliation", "status": "verified"} not in summary["held_components"]
    assert diagnosed["overview"]["spend"]["status"] == "verified" and "routes" in diagnosed
    assert_views_agree(diagnosed, views(tmp_path / "d-mixed"))
