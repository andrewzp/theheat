"""G9: one verified capture-identity boundary across usage, reconciliation, copy review and diagnosis.

An INVENTED offline matrix through the actual reader, usage, reconciliation,
copy-pack and diagnosis functions: unique v1, the same v1 twice, a byte-identical
directory copy, distinct captures with identical requests, unique and repeated
v2, mixed v1/v2, a same-scope conflict and an invalid copy. Nothing here is a
provider, invoice, human-preference or publication observation.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from src.evaluation import archive_usage
from src.two_bot import request_archive_replay as replay
from tests import test_batch_result_journal as receipts
from tests import test_batch_worker_journal as workers
from tests.test_archive_identity_followup import _Scope, _relabel
from tests.test_request_archive_batch import fresh_store
from tests.test_request_archive_batch_replay import copy_scope
from tests.test_request_archive_review_closure import _usage, collected, jsonl, keyed, line
from tests.test_operator_diagnosis import TWEET, scripted
from tests.test_request_archive_sdk import journey_env, private_root, run_journey
from tests.two_bot import test_batch_contract as contracts

__all__ = ["keyed", "journey_env"]
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
    """Counted contributions only; input-indexed provenance is compared separately."""
    return {key: value for key, value in usage.items() if key not in ("sources", "identity_reconciliation")}


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
