"""G9 follow-up to two G8 checkpoint findings, with actual SDK MockTransport streams.

1. An excluded capture-identity conflict keeps every aggregate it touches
   incomplete: never a complete zero, never an apparently complete subtotal.
2. A retained result line with a usable custom ID keeps that identity and its
   content when its classification is malformed, and a succeeded line without
   a message is invalid usage, never a complete not-applicable row.

All data is INVENTED and offline. These are source-derived counterexamples, not
provider, billing or invoice observations.
"""
from __future__ import annotations

from copy import deepcopy
from itertools import permutations
import json

import pytest

from src.evaluation import archive_usage
from src.evaluation import operator_diagnosis as diagnosis
from src.two_bot import request_archive_replay as replay
from tests import test_batch_result_journal as receipts
from tests.test_operator_diagnosis import AS_OF
from tests.test_request_archive_batch import fresh_store
from tests.test_request_archive_batch_replay import copy_scope, rewrite
from tests.test_request_archive_review_closure import _usage, collected, custom_id, jsonl, keyed, line
from tests.test_request_archive_sdk import journey_env
from tests.two_bot import test_batch_contract as contracts
from tests import test_batch_worker_journal as workers

__all__ = ["keyed", "journey_env"]
inputs = contracts.inputs
store = workers.store


class _Scope:
    def __init__(self, directory):
        self.directory = directory


def _relabel(directory, tmp_path, name):
    """An honest re-chained export of one capture with different contents (same scope ID)."""
    target = copy_scope(_Scope(directory), tmp_path, name)
    rewrite(target, lambda record: record["data"]["operation"].update(label=f"invented {name}")
            if record["type"] == "scope_opened" else None)
    return target


def _semantic(usage: dict) -> dict:
    """Order-independent content: input indexes are provenance, never a contribution."""
    keep = ("route_denominators", "route_conflicts", "route_totals_status", "route_totals_unknown_reasons",
            "route_token_totals")
    rows = sorted(json.dumps({k: v for k, v in row.items()}, sort_keys=True) for row in usage["route_result_lines"])
    return {**{key: usage.get(key) for key in keep}, "lines": rows,
            "conflicting_scope_ids": usage["identity_reconciliation"]["conflicting_scope_ids"]}


def _diagnose(archives):
    components, usable = diagnosis.verify_components(archives=archives, reconciliation=None, copy_private=None,
                                                     copy_import=None, readers=None, state=None, as_of=AS_OF)
    return diagnosis.diagnose(archives=archives, components=components, usable=usable, as_of=AS_OF, input_files=[])


@pytest.fixture
def batch_family(store, inputs, keyed, tmp_path):
    probe = fresh_store(tmp_path, "probe")
    pair, _ = receipts.started(probe, inputs)
    valid = line(pair, usage=_usage(pair, 100))
    unrelated = deepcopy(valid)
    unrelated["custom_id"] = "invented-unrelated-0001"
    unrelated["result"]["message"]["usage"]["input_tokens"] = 7

    def make(name, *rows):
        return replay.load_archive(collected(tmp_path, inputs, name, results=jsonl(*rows))[0].directory)
    return pair, valid, unrelated, make


# --------------------------------------- 1. excluded identity conflicts

def test_identity_conflict_keeps_route_totals_incomplete_alone_and_beside_valid_evidence(batch_family, tmp_path):
    pair, valid, unrelated, make = batch_family
    original = make("original", valid)
    changed = replay.load_archive(_relabel(original.directory, tmp_path, "changed"))
    control = make("control", unrelated)
    assert original.status == changed.status == control.status == "complete"
    assert original.scope_id == changed.scope_id and original.manifest_sha256 != changed.manifest_sha256
    alone = archive_usage.archive_usage([control])
    assert alone["route_totals_status"] == "complete_for_retained_rows"
    known = alone["route_token_totals"]
    assert known and known[0]["counts"]["input_tokens"] == 7
    for members, expected_totals in (([original, changed], []), ([original, changed, control], known)):
        views = []
        for order in permutations(members):
            usage = archive_usage.archive_usage(list(order))
            # Quarantined identities count nowhere and make every touched aggregate incomplete.
            assert usage["route_totals_status"] == "incomplete", [a.scope_id for a in order]
            assert "identity_conflict_quarantined" in usage["route_totals_unknown_reasons"]
            assert usage["route_token_totals"] == expected_totals
            assert usage["identity_reconciliation"]["conflicting_scope_ids"] == [original.scope_id]
            report = _diagnose(list(order))
            routes = report["routes"]
            assert routes["route_totals_status"] == "incomplete"
            assert "identity_conflict_quarantined" in routes["route_totals_unknown_reasons"]
            assert original.scope_id not in {scope["scope_id"] for scope in routes["scopes"]}
            views.append((_semantic(usage), {k: routes[k] for k in ("route_totals_status", "result_conflicts",
                                                                     "route_totals_unknown_reasons")}))
        assert all(view == views[0] for view in views)
    assert alone["route_totals_unknown_reasons"] == []


def test_invalid_copy_cannot_hide_behind_its_valid_capture(batch_family, tmp_path):
    pair, valid, unrelated, make = batch_family
    original = make("original", valid)
    tampered = copy_scope(_Scope(original.directory), tmp_path, "tampered")
    artifact = sorted((tampered / "artifacts").iterdir())[0]
    artifact.write_bytes(artifact.read_bytes() + b"invented tamper")
    damaged = replay.load_archive(tampered)
    # The strict reader exposes no identity for invalid evidence, so it can never be a duplicate.
    assert damaged.status == "invalid" and damaged.scope_id is None
    for order in ([original, damaged], [damaged, original]):
        usage = archive_usage.archive_usage(order)
        statuses = sorted((s["status"], s["used"], s["duplicate_of_input"]) for s in usage["sources"])
        assert statuses == [("complete", True, None), ("invalid", False, None)]
        assert usage["route_denominators"]["result_lines_counted"] == 1
        assert usage["route_totals_status"] == "incomplete"
        assert usage["route_totals_unknown_reasons"] == ["invalid_input_not_counted"]


# --------------------------------------- 2. malformed classification

def _malformed(valid: dict, kind: str) -> dict:
    row = deepcopy(valid)
    if kind == "type_list":
        row["result"]["type"] = []
    elif kind == "type_missing":
        del row["result"]["type"]
    elif kind == "type_unknown":
        row["result"]["type"] = "invented_unknown"
    elif kind == "result_not_object":
        row["result"] = []
    elif kind == "succeeded_no_message":
        del row["result"]["message"]
    else:
        row["result"]["message"] = "invented non-object message"
    return row


MALFORMED = ["type_list", "type_missing", "type_unknown", "result_not_object", "succeeded_no_message",
             "succeeded_message_not_object"]


@pytest.mark.parametrize("kind", MALFORMED)
def test_malformed_same_id_rows_conflict_with_a_valid_result_in_every_order(batch_family, kind):
    pair, valid, unrelated, make = batch_family
    good = make("good", valid)
    bad = make("bad", _malformed(valid, kind))
    control = make("control", unrelated)
    # A malformed provider body is retained evidence, not a corrupted hash chain.
    assert bad.status == "complete" and replay.load_archive(bad.directory).problems == ()
    cid = custom_id(pair)
    lone = archive_usage.archive_usage([bad])
    row, = lone["route_result_lines"]
    assert row["custom_id"] == cid and row["content_sha256"] and row["counted"] is False
    assert row["usage_status"] in ("invalid", "invalid_line")
    assert lone["route_token_totals"] == [] and lone["route_totals_status"] == "incomplete"
    views = []
    for members in ([good, bad], [good, bad, control]):
        for order in permutations(members):
            usage = archive_usage.archive_usage(list(order))
            same_id = [r for r in usage["route_result_lines"] if r["custom_id"] == cid]
            assert len(same_id) == 2 and {r["usage_status"] for r in same_id} == {"conflict"}
            assert not any(r["counted"] for r in same_id)
            conflict, = usage["route_conflicts"]
            assert conflict["custom_id"] == cid and len(conflict["sources"]) == 2
            assert usage["route_totals_status"] == "incomplete"
            # No first-wins contribution: only the unrelated control's known tokens remain.
            expected = archive_usage.archive_usage([control])["route_token_totals"] if control in order else []
            assert usage["route_token_totals"] == expected
            views.append((len(order), _semantic(usage)))
    for size in (2, 3):
        group = [view for count, view in views if count == size]
        assert all(view == group[0] for view in group)
    # Unrelated valid controls stay complete and count once.
    for order in ([good, control], [control, good]):
        usage = archive_usage.archive_usage(order)
        assert usage["route_totals_status"] == "complete_for_retained_rows"
        assert sum(t["counts"]["input_tokens"] for t in usage["route_token_totals"]) == 107


def test_lone_succeeded_without_message_is_invalid_not_complete(batch_family):
    pair, valid, unrelated, make = batch_family
    lone = make("lone", _malformed(valid, "succeeded_no_message"))
    usage = archive_usage.archive_usage([lone])
    row, = usage["route_result_lines"]
    assert (row["result_type"], row["counted"], row["usage_status"]) == ("succeeded", False, "invalid")
    assert usage["route_totals_status"] == "incomplete"
    assert "result_line_usage_not_present" in usage["route_totals_unknown_reasons"]
    # Unchanged control: a well-formed non-succeeded result has no usage to count and stays complete.
    expired = make("expired", {"custom_id": custom_id(pair), "result": {"type": "expired"}})
    usage = archive_usage.archive_usage([expired])
    row, = usage["route_result_lines"]
    assert (row["result_type"], row["counted"], row["usage_status"]) == ("expired", False,
                                                                       "not_applicable_result_type")
    assert usage["route_totals_status"] == "complete_for_retained_rows"
