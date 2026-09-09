"""Shared adversarial evidence shapes must remain blocked in both runtimes."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from src.editorial.revisions import has_unresolved_publish
from src.state import _merge_publish_ledger


FIXTURE_PATH = Path(__file__).parent / "fixtures/publication_uncertainty_contract.json"
CASES = json.loads(FIXTURE_PATH.read_text())
MALFORMED = [case for case in CASES if case["malformed"]]
DRAFT = {"id": "draft", "event_id": "event", "text": "Current reviewed text.", "status": "pending"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
@pytest.mark.parametrize("outcome", [None, "not_sent", "confirmed", "unknown"])
def test_shared_uncertainty_gate_never_uses_draft_outcome_to_clear_conflicts(case, outcome):
    draft = {**DRAFT, **({"publish_outcome": outcome} if outcome else {})}
    state = {"publish_ledger": {"event": case["row"]} if "row" in case else {}}
    original = deepcopy([draft, state])
    assert has_unresolved_publish(draft, state) is (case["unresolved"] or outcome == "unknown")
    assert [draft, state] == original


def malformed_subtrees(row):
    """Return exact opaque payloads whose structure must survive a merge."""
    if not isinstance(row, dict):
        return [row]
    conflicts = row.get("attempt_conflicts", [])
    if not isinstance(conflicts, list) or any(not isinstance(child, dict) for child in conflicts):
        return [row]
    return [nested for child in conflicts for nested in malformed_subtrees(child)]


def contains_value(value, target):
    if type(value) is type(target) and value == target:
        return True
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return any(contains_value(child, target) for child in children)


@pytest.mark.parametrize("case", MALFORMED, ids=lambda case: case["name"])
def test_merges_preserve_opaque_payloads_and_cannot_upgrade_them_to_confirmed(case):
    bad = {"event": case["row"]}
    original = deepcopy(bad)
    for incoming in ({}, {"event": {"phase": "not_sent"}}, {"event": {"phase": "confirmed", "tweet_id": "receipt", "text": DRAFT["text"]}}):
        forward = _merge_publish_ledger(bad, incoming)
        assert _merge_publish_ledger(incoming, bad) == forward
        assert has_unresolved_publish(DRAFT, {"publish_ledger": forward})
        for payload in malformed_subtrees(case["row"]):
            assert contains_value(forward["event"], payload)
        assert _merge_publish_ledger(forward, bad) == forward
        assert _merge_publish_ledger(forward, forward) == forward
    assert bad == original


def test_real_node_and_python_merge_every_adversarial_fixture_identically():
    root = Path(__file__).resolve().parents[1]
    program = """
      import { readFileSync } from 'node:fs';
      import { mergePublishLedger } from './dashboard/lib/state-store.js';
      const cases = JSON.parse(readFileSync(0, 'utf8'));
      process.stdout.write(JSON.stringify(cases.map(row => mergePublishLedger(
        {event: row}, {event: {phase: 'confirmed', tweet_id: 'receipt', text: 'Current reviewed text.'}}
      ))));
    """
    rows = [case["row"] for case in CASES if "row" in case]
    output = subprocess.run(["node", "--input-type=module", "-e", program], cwd=root,
                            input=json.dumps(rows), capture_output=True, text=True, check=True)
    expected = [_merge_publish_ledger({"event": row}, {"event": {"phase": "confirmed", "tweet_id": "receipt", "text": DRAFT["text"]}}) for row in rows]
    assert json.loads(output.stdout) == expected


def test_nested_unidentified_unknown_attempt_cannot_be_absorbed_by_not_sent():
    row = next(case["row"] for case in CASES if case["name"] == "unknown nested attempt")
    ledger = _merge_publish_ledger({"event": row}, {"event": {"phase": "not_sent"}})
    assert has_unresolved_publish(DRAFT, {"publish_ledger": ledger})
    assert contains_value(ledger, {"phase": "unknown"})
    assert _merge_publish_ledger(ledger, {"event": row}) == ledger
