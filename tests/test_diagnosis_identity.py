"""G9: one verified capture-identity boundary across usage, reconciliation, copy review and diagnosis.

An INVENTED offline matrix through the actual reader, usage, reconciliation,
copy-pack and diagnosis functions: unique v1, the same v1 twice, a byte-identical
directory copy, distinct captures with identical requests, unique and repeated
v2, mixed v1/v2, a same-scope conflict and an invalid copy. Nothing here is a
provider, invoice, human-preference or publication observation.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.evaluation import archive_usage
from src.evaluation import operator_diagnosis as diagnosis
from src.two_bot import request_archive_replay as replay
from tests import test_batch_result_journal as receipts
from tests import test_batch_worker_journal as workers
from tests.test_archive_identity_followup import _Scope, _relabel
from tests.test_request_archive_batch import fresh_store
from tests.test_request_archive_batch_replay import copy_scope
from tests.test_request_archive_review_closure import _usage, collected, jsonl, keyed, line
from tests.test_operator_diagnosis import AS_OF, TWEET, explicit_node_fixture, scripted
from tests.test_request_archive_sdk import journey_env, private_root, run_journey
from tests.two_bot import test_batch_contract as contracts

__all__ = ["keyed", "journey_env", "explicit_node_fixture"]
inputs = contracts.inputs
store = workers.store


def _tampered(directory: Path, tmp_path: Path, name: str) -> Path:
    target = copy_scope(_Scope(directory), tmp_path, name)
    artifact = sorted((target / "artifacts").iterdir())[0]
    artifact.write_bytes(artifact.read_bytes() + b"invented tamper")
    return target


@pytest.fixture
def matrix(journey_env, store, inputs, keyed, tmp_path) -> dict:
    """Directories for every identity case; loaded fresh by each consumer."""
    # Identical requests and texts; only the invented provider IDs differ, as two real sends would.
    a = run_journey(scripted("g9-a", TWEET), root=private_root(tmp_path, "v1-a")).archive
    b = run_journey(scripted("g9-b", TWEET), root=private_root(tmp_path, "v1-b")).archive
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    v = collected(tmp_path, inputs, "v2", results=jsonl(line(pair, usage=_usage(pair, 100))))[0].directory
    return {"A": a, "A_copy": copy_scope(_Scope(a), tmp_path, "v1-copy"), "B": b,
            "A_conflict": _relabel(a, tmp_path, "v1-conflict"), "A_invalid": _tampered(a, tmp_path, "v1-tampered"),
            "V": v, "V_copy": copy_scope(_Scope(v), tmp_path, "v2-copy"),
            "V_conflict": _relabel(v, tmp_path, "v2-conflict")}


CASES = {
    "unique_v1": ["A"], "same_v1_twice": ["A", "A"], "copied_v1": ["A", "A_copy"],
    "distinct_identical_requests": ["A", "B"], "unique_v2": ["V"], "repeated_v2": ["V", "V"],
    "copied_v2": ["V_copy", "V"], "mixed": ["A", "V"], "mixed_repeated": ["V", "A", "A_copy", "V", "V_copy"],
    "conflict_v1": ["A", "A_conflict"], "conflict_beside_valid": ["A_conflict", "B", "A"],
    "conflict_v2_beside_v1": ["V_conflict", "A", "V"], "invalid_copy": ["A_invalid", "A"],
}
# What each case must count as, once: the unique evidence it reduces to.
COUNTS_AS = {"same_v1_twice": "unique_v1", "copied_v1": "unique_v1", "repeated_v2": "unique_v2",
             "copied_v2": "unique_v2", "mixed_repeated": "mixed"}


def load(matrix: dict, names: list[str]) -> list:
    return [replay.load_archive(matrix[name]) for name in names]


def usage_semantics(usage: dict) -> dict:
    """Counted contributions only; input-indexed provenance is compared separately.

    Row lists follow the order of the counted inputs; their order is not a contribution.
    """
    rows = ("calls", "attempts", "routes", "route_result_lines")
    return {key: sorted(value, key=lambda row: json.dumps(row, sort_keys=True)) if key in rows else value
            for key, value in usage.items() if key not in ("sources", "identity_reconciliation")}


def test_identity_boundary_counts_each_capture_once_and_quarantines_conflicts(matrix):
    views = {name: archive_usage.archive_usage(load(matrix, names)) for name, names in CASES.items()}
    for name, unique in COUNTS_AS.items():
        assert usage_semantics(views[name]) == usage_semantics(views[unique]), name
        identity = views[name]["identity_reconciliation"]
        assert identity["status"] == "consistent" and identity["supplied_inputs"] == len(CASES[name])
        assert identity["duplicate_inputs"] == len(CASES[name]) - len(set(n.split("_copy")[0] for n in CASES[name]))
        # Every supplied source reference is kept, each duplicate pointing at the counted one.
        assert len(views[name]["sources"]) == len(CASES[name])
    one, two = views["unique_v1"]["denominators"], views["distinct_identical_requests"]["denominators"]
    assert {key: 2 * value for key, value in one.items()} == two  # separate physical attempts stay separate
    assert views["distinct_identical_requests"]["identity_reconciliation"]["counted_captures"] == 2
    for name in ("conflict_v1", "conflict_beside_valid", "conflict_v2_beside_v1"):
        usage = views[name]
        identity = usage["identity_reconciliation"]
        assert identity["status"] == "conflict_quarantined" and identity["quarantined_inputs"] == 2
        group, = identity["conflict_groups"]
        assert len(group["manifest_sha256s"]) == 2 and len(group["inputs"]) == 2
        assert usage["token_totals_status"] == "incomplete"
        assert "identity_conflict_quarantined" in usage["token_totals_unknown_reasons"]
    assert views["conflict_v1"]["denominators"]["physical_attempts"] == 0  # not a known zero: status incomplete
    # B (a distinct capture) still counts; A and its conflicting export count nowhere.
    assert views["conflict_beside_valid"]["denominators"] == views["unique_v1"]["denominators"]
    assert views["conflict_beside_valid"]["token_totals"] == views["unique_v1"]["token_totals"]
    assert views["conflict_v2_beside_v1"]["route_totals_status"] == "incomplete"
    invalid = views["invalid_copy"]
    statuses = ("token_totals_status", "token_totals_unknown_reasons")
    assert {k: v for k, v in usage_semantics(invalid).items() if k not in statuses} == \
        {k: v for k, v in usage_semantics(views["unique_v1"]).items() if k not in statuses}
    assert [s["status"] for s in invalid["sources"]] == ["invalid", "complete"]
    assert invalid["sources"][0]["duplicate_of_input"] is None and invalid["sources"][0]["used"] is False
    assert "invalid_input_not_counted" in invalid["token_totals_unknown_reasons"]
    assert invalid["identity_reconciliation"]["invalid_inputs"] == 1


def test_known_versus_unknown_totals_are_derived_from_retained_rows(matrix, journey_env, tmp_path):
    unique = archive_usage.archive_usage(load(matrix, ["A"]))
    assert unique["token_totals_status"] == "complete_for_retained_rows"
    assert unique["token_totals_unknown_reasons"] == []
    uncertain = run_journey({"writer": [{"raise": "timeout"}] * 3}, root=private_root(tmp_path, "uncertain")).archive
    usage = archive_usage.archive_usage([replay.load_archive(uncertain), *load(matrix, ["A"])])
    assert usage["token_totals_status"] == "incomplete"
    assert usage["token_totals_unknown_reasons"] == ["unknown_send_outcome"]
    # Known subtotals stay exactly the counted rows; nothing unknown is invented as zero.
    assert usage["token_totals"] == unique["token_totals"]
    doubled = deepcopy(unique["attempts"])
    for row in doubled:
        row["usage_status"] = "absent"
    assert archive_usage.token_totals_unknown_reasons(unique["sources"], doubled) == ["usage_not_present"]
    assert archive_usage.token_totals_unknown_reasons([], []) == []


# ------------------------------------------------ diagnosis consumers

def diagnose(archives, **components):
    found, usable = diagnosis.verify_components(
        archives=archives, reconciliation=components.get("reconciliation"),
        copy_private=components.get("copy_private"), copy_import=components.get("copy_import"),
        readers=components.get("readers"), state=components.get("state"), as_of=AS_OF)
    return diagnosis.diagnose(archives=archives, components=found, usable=usable, as_of=AS_OF, input_files=[])


PROVENANCE_SOURCE_KEYS = ("supplied_inputs", "duplicate_inputs")


def report_semantics(report: dict) -> dict:
    """Accepted contributions only: input-indexed provenance may differ, contributions may not."""
    routes = {key: value for key, value in (report.get("routes") or {}).items() if key != "identity_reconciliation"}
    return {"candidates": sorted(report["candidates"], key=lambda c: c["candidate_key"]),
            "generations": sorted(report["generations"], key=lambda g: g["generation_key"]),
            "unjoined_posts": report["unjoined_posts"], "routes": routes,
            "overview": {**report["overview"], "source": {k: v for k, v in report["overview"]["source"].items()
                                                         if k not in PROVENANCE_SOURCE_KEYS}},
            "components": [c for c in report["components"] if c["component"] not in ("archive", "capture_identity")],
            "copy_review": report["copy_review"], "decision": report["decision"]}


def test_v1_and_v2_diagnosis_count_each_capture_once(matrix):
    reports = {name: diagnose(load(matrix, names)) for name, names in CASES.items()}
    for name, report in reports.items():
        anchors = [c["anchor"] for c in report["candidates"]]
        assert len(anchors) == len(set(anchors)), name  # one HTML section per candidate
        page = diagnosis.render_html(report)
        assert all(page.count(f"id='{anchor}'") == 1 for anchor in anchors), name
    for name, unique in COUNTS_AS.items():
        assert report_semantics(reports[name]) == report_semantics(reports[unique]), name
        identity = next(c for c in reports[name]["components"] if c["component"] == "capture_identity")
        assert identity["status"] == "verified" and identity["duplicate_inputs"] >= 1
        rows = [c for c in reports[name]["components"] if c["component"] == "archive"]
        assert [r["input"] for r in rows] == list(range(len(CASES[name])))
        assert {r["identity"] for r in rows} == {"counted", "duplicate_not_counted"}
    checks = reports["unique_v1"]["overview"]["checks"]
    assert reports["distinct_identical_requests"]["overview"]["checks"] == {k: 2 * v for k, v in checks.items()}
    assert len(reports["distinct_identical_requests"]["generations"]) == 2
    for name in ("conflict_v1", "conflict_beside_valid", "conflict_v2_beside_v1"):
        report = reports[name]
        quarantined = report["identity_reconciliation"]["conflicting_scope_ids"]
        assert report["identity_reconciliation"]["status"] == "conflict_quarantined" and len(quarantined) == 1
        assert all(c["scope_id"] not in quarantined for c in report["candidates"] + report["generations"])
        assert next(c for c in report["components"] if c["component"] == "capture_identity")["status"] == \
            "conflict_quarantined"
        assert report["overview"]["source"]["identity_quarantined_inputs"] == 2
        assert {r["identity"] for r in report["components"] if r["component"] == "archive"
                and r["scope_id"] in quarantined} == {"conflict_quarantined"}
    assert reports["conflict_v1"]["candidates"] == [] and reports["conflict_v1"]["overview"]["source"][
        "counted_captures"] == 0
    beside = reports["conflict_beside_valid"]
    assert [c["scope_id"] for c in beside["candidates"]] == [replay.load_archive(matrix["B"]).scope_id]
    assert reports["conflict_v2_beside_v1"]["routes"]["route_totals_status"] == "incomplete"
    invalid = reports["invalid_copy"]
    assert report_semantics(invalid)["candidates"] == report_semantics(reports["unique_v1"])["candidates"]
    assert invalid["overview"]["source"]["archive_statuses"] == {"complete": 1, "invalid": 1}
    assert [r["identity"] for r in invalid["components"] if r["component"] == "archive"] == [
        "invalid_not_counted", "counted"]


# ------------------------------------------------ optional-component joins

@pytest.fixture
def scenario(journey_env, tmp_path):
    from tests.test_operator_diagnosis import build_scenario_archives
    return build_scenario_archives(tmp_path), tmp_path


def state_inputs(runs, tmp_path):
    from tests.test_operator_diagnosis import _readers, retained_state, write_private
    state = retained_state(runs)
    return state, _readers(write_private(private_root(tmp_path, "state"), "state.json", state))


def test_publication_joins_count_a_capture_once_and_hold_conflicting_identities(scenario):
    runs, tmp_path = scenario
    state, readers = state_inputs(runs, tmp_path)
    paths = [run.archive for run in runs.values()]
    accepted = runs["accepted"].archive
    twin = run_journey(scripted("g9-twin", TWEET), root=private_root(tmp_path, "twin")).archive
    variants = {"unique": paths, "repeated": paths + [accepted, accepted],
                "copied": [copy_scope(_Scope(accepted), tmp_path, "accepted-copy"), *paths],
                "conflict": [*paths, _relabel(accepted, tmp_path, "accepted-conflict")],
                "distinct_twin": [*paths, twin]}
    reports = {name: diagnose([replay.load_archive(p) for p in found], state=state, readers=readers)
               for name, found in variants.items()}
    unique = reports["unique"]
    joined = [c for c in unique["candidates"] if c["publication"]["status"] == "joined"]
    assert len(joined) == 1 and unique["overview"]["publication"]["joined_to_archived_candidate"] == 1
    for name in ("repeated", "copied"):
        assert report_semantics(reports[name]) == report_semantics(unique), name
    tweet = joined[0]["publication"]["posts"][0]["tweet_id"]
    conflict = reports["conflict"]
    assert not any(c["publication"]["status"] == "joined" for c in conflict["candidates"])
    assert next(p for p in conflict["unjoined_posts"] if p["tweet_id"] == tweet)["join"] == \
        "held_capture_identity_conflict"
    assert conflict["overview"]["publication"]["joined_to_archived_candidate"] == 0
    # The manual-edit exclusion and every other unjoined reason are unchanged.
    assert [p for p in conflict["unjoined_posts"] if p["tweet_id"] != tweet] == unique["unjoined_posts"]
    # Control: a genuinely distinct capture with the same text and bundle is a second physical attempt.
    twin_report = reports["distinct_twin"]
    assert next(p for p in twin_report["unjoined_posts"] if p["tweet_id"] == tweet)["join"] == \
        "ambiguous_multiple_accepted_candidates"


def _report(archives, *, as_of=AS_OF):
    from src.evaluation import invoice_evidence as evidence
    return evidence.build_report(as_of=as_of, usage=archive_usage.archive_usage(archives), documents=[],
                                 rejected_billing=[], bindings=[], scenario=None, state_summary=None, input_files=[])


def older_report(archives, monkeypatch):
    """The main-era (#709/#710) producer: every argument counted, old source rows, then sealed.

    Reproduced by running the unchanged usage code with the pre-G8 no-reconciliation
    rule; the RESULT records the same shape from the actual 01bd5cc CLI.
    """
    from src.evaluation import invoice_evidence as evidence

    def every_argument(supplied):
        sources = [{"scope_id": a.scope_id, "manifest_sha256": a.manifest_sha256, "status": a.status,
                    "problems": list(a.problems), "used": a.status != "invalid"} for a in supplied]
        return sources, [a for a in supplied if a.status != "invalid"], {}
    with monkeypatch.context() as patched:
        patched.setattr(archive_usage, "reconcile_identities", every_argument)
        report = _report(archives)
    del report["inputs"]["identity_reconciliation"]
    for key in ("token_totals_status", "token_totals_unknown_reasons"):
        del report["observed"][key]
    report["report_sha256"] = evidence._report_identity(report)
    return evidence.verify_report(report)


def component(report, name):
    return next(c for c in report["components"] if c["component"] == name)


def test_reconciliation_joins_once_and_holds_inflated_or_conflicting_contributions(matrix, monkeypatch):
    a, x, b = load(matrix, ["A", "A_conflict", "B"])
    once = _report([a])
    baseline = diagnose([a], reconciliation=once)
    assert component(baseline, "reconciliation")["status"] == "verified"
    spend = baseline["overview"]["spend"]
    for archives, reconciliation in (([a, a], once), ([a], _report([a, a])), ([a, a], _report([a, a]))):
        report = diagnose(archives, reconciliation=reconciliation)
        assert component(report, "reconciliation")["status"] == "verified"
        assert report["overview"]["spend"] == spend
        assert report_semantics(report)["candidates"] == report_semantics(baseline)["candidates"]
    # An older sealed report that counted one capture twice is held, never repaired or re-derived.
    inflated = older_report([a, a], monkeypatch)
    assert inflated["observed"]["denominators"]["physical_attempts"] == 2 * spend["physical_attempts"]
    report = diagnose([a], reconciliation=inflated)
    assert component(report, "reconciliation")["status"] == "unverifiable_identity"
    assert component(report, "reconciliation")["reason"] == "older_report_counted_a_repeated_capture"
    assert report["overview"]["spend"] == {"status": "held", "component_status": "unverifiable_identity"}
    assert all(a["usage_status"] == "reconciliation_absent" for c in report["candidates"] for call in c["calls"]
               for a in call["attempts"])
    contradictory = diagnose([a], reconciliation=older_report([a, x], monkeypatch))
    assert component(contradictory, "reconciliation")["reason"] == "older_report_counted_conflicting_identities"
    # The same older producer on unique inputs stays compatible.
    assert component(diagnose([a], reconciliation=older_report([a], monkeypatch)), "reconciliation")["status"] == \
        "verified"
    # A report naming a capture the diagnosis must quarantine holds instead of picking a winner.
    held = diagnose([a, x], reconciliation=once)
    assert component(held, "reconciliation")["status"] == "held_identity_conflict"
    assert held["overview"]["spend"]["status"] == "held"
    # A report that itself quarantined a conflict is a known partial subtotal, never complete.
    partial = diagnose([b], reconciliation=_report([a, x, b]))
    assert component(partial, "reconciliation")["status"] == "verified"
    assert partial["overview"]["spend"]["token_totals_status"] == "incomplete"
    assert "identity_conflict_quarantined" in partial["overview"]["spend"]["token_totals_unknown_reasons"]
    # A supplied completeness label never decides it: a G8-shaped report without the label and a
    # re-sealed report claiming completeness both derive "incomplete" from their own retained rows.
    from src.evaluation import invoice_evidence as evidence
    for claimed in (None, "complete_for_retained_rows"):
        sealed = _report([a, x, b])
        if claimed is None:
            for key in ("token_totals_status", "token_totals_unknown_reasons"):
                del sealed["observed"][key]
        else:
            sealed["observed"].update(token_totals_status=claimed, token_totals_unknown_reasons=[])
        sealed["report_sha256"] = evidence._report_identity(sealed)
        spend = diagnose([b], reconciliation=sealed)["overview"]["spend"]
        assert (spend["status"], spend["token_totals_status"]) == ("verified", "incomplete"), claimed
        assert "identity_conflict_quarantined" in spend["token_totals_unknown_reasons"]
    # Absent stays absent.
    assert diagnose([a])["overview"]["spend"] == {"status": "absent"}


def test_copy_review_and_ratings_join_once_and_hold_conflicting_identities(journey_env, tmp_path):
    from src.evaluation import private_copy_pack as packs
    from tests.test_private_copy_pack import ballot, built, make_review_workspace, rating
    workspace = make_review_workspace(tmp_path)
    public, private, _ = built(workspace)
    ballots = [ballot(public, [rating(public["pairs"][0], "A")], rated_at="2026-10-23T12:01:00Z")]
    imported = packs.import_ballots(private, ballots + ballots, as_of=AS_OF)  # an exact repeated ballot file
    assert imported["identical_retries_collapsed"] == 1 and imported["real_human_ratings_added"] == 0
    one, two = workspace["archives"]
    variants = {"unique": [one, two], "repeated": [one, two, one, two],
                "copied": [copy_scope(_Scope(one), tmp_path, "one-copy"), two],
                "copy_beside_original": [one, copy_scope(_Scope(one), tmp_path, "one-copy-2"), two],
                "conflict": [one, two, _relabel(one, tmp_path, "one-conflict")]}
    reports = {name: diagnose([replay.load_archive(p) for p in found], copy_private=private, copy_import=imported)
               for name, found in variants.items()}
    unique = reports["unique"]
    assert (component(unique, "copy_review")["status"], component(unique, "copy_ratings")["status"]) == (
        "verified", "verified")
    for name in ("repeated", "copied", "copy_beside_original"):
        assert report_semantics(reports[name]) == report_semantics(unique), name
    conflict = reports["conflict"]
    assert component(conflict, "copy_review")["status"] == "held_identity_conflict"
    assert component(conflict, "copy_ratings") == {"component": "copy_ratings", "status": "held",
                                                   "reason": "copy_review_not_verified"}
    assert conflict["overview"]["preference"] == {"status": "held", "component_status": "held_identity_conflict"}
    assert {json.dumps(c["copy_review"]) for c in conflict["candidates"]} == {'{"in_pack": null, "pack": "held"}'}
    assert any(c["copy_review"]["in_pack"] for c in unique["candidates"])
    # A pack builder refuses conflicting identities outright; repeated arguments build the same pack.
    selection = packs.parse_selection(workspace["selection"].read_bytes())
    archives = [replay.load_archive(p) for p in (one, two, one)]
    again, _, _ = packs.build_pack(selection, archives, created_at=packs_created(), seed=b"invented-fixture-seed-not-secret-0001")
    assert again == public
    with pytest.raises(packs.CopyReviewError, match="archive_scope_identity_conflict"):
        packs.build_pack(selection, [*archives, replay.load_archive(variants["conflict"][-1])],
                         created_at=packs_created(), seed=b"invented-fixture-seed-not-secret-0001")


def packs_created():
    from tests.test_private_copy_pack import CREATED
    return CREATED


# ------------------------------------------------ order invariance

FAMILIES = {
    "repeated_v1": ["A", "B", "A", "A_copy"],
    "conflict_v1": ["A", "A_conflict", "B", "A_copy"],
    "repeated_v2": ["V", "A", "V_copy", "V"],
    "conflict_v2": ["V", "V_conflict", "A", "V_copy"],
    "invalid_beside_copies": ["A_invalid", "A", "B", "A_copy"],
}
ORDERS = {"given": [0, 1, 2, 3], "reversed": [3, 2, 1, 0], "rotated": [1, 2, 3, 0], "interleaved": [2, 0, 3, 1]}


def identity_semantics(identity: dict) -> dict:
    """Input indexes are provenance; every count, status and claimed manifest must be order-independent."""
    return {**{k: v for k, v in identity.items() if k != "conflict_groups"},
            "conflict_groups": [{k: v for k, v in g.items() if k != "inputs"} | {"inputs": len(g["inputs"])}
                                for g in identity["conflict_groups"]]}


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_order_selects_the_same_contributions(matrix, family):
    names = FAMILIES[family]
    seen = []
    for order in ORDERS.values():
        archives = load(matrix, [names[i] for i in order])
        usage, report = archive_usage.archive_usage(archives), diagnose(archives)
        seen.append({"usage": usage_semantics(usage), "report": report_semantics(report),
                     "identity": identity_semantics(report["identity_reconciliation"]),
                     "next_actions": report["next_actions"]})
        # Provenance keeps every argument and points each duplicate at a counted input of the same capture.
        rows = [c for c in report["components"] if c["component"] == "archive"]
        assert len(rows) == len(names)
        for row in rows:
            if row["identity"] == "duplicate_not_counted":
                kept = rows[row["duplicate_of_input"]]
                assert (kept["identity"], kept["scope_id"], kept["manifest_sha256"]) == (
                    "counted", row["scope_id"], row["manifest_sha256"])
    for view in seen[1:]:
        assert [k for k in view if view[k] != seen[0][k]] == [], family
        assert [k for k in view["usage"] if view["usage"][k] != seen[0]["usage"][k]] == [], family
        assert [k for k in view["report"] if view["report"][k] != seen[0]["report"][k]] == [], family
