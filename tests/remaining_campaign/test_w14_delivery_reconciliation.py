"""W14.4: reconciliation joins receipt evidence to one exact attempt.

The shared vectors also drive dashboard/tests/remaining-campaign-w14-reconciliation.test.js,
so the Python command path and the dashboard route apply identical rules.
Invented places and identifiers only; no Gist, X or network.
"""
from __future__ import annotations

from copy import deepcopy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from src.commands import delivery_reconciliation as rec, local_cli
from src.commands.schema import Principal, canonical_json
from src.commands.sqlite_authority import SQLiteAuthority
from src.orchestrator import posting
from src.posting.outbox_outcome import retry_permitted

VECTORS = json.loads((Path(__file__).parents[1] / "fixtures" / "w14_delivery_reconciliation_vectors.json").read_text())
PUBLISHER = Principal("w14-publisher", "publisher", "local-fixture")


def _subset(actual, expected):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(_subset(actual.get(k), v) for k, v in expected.items())
    return actual == expected


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[case["name"] for case in VECTORS["cases"]])
def test_shared_vectors_through_the_pure_rules(case):
    state = deepcopy(VECTORS["state"])
    for step in case["steps"]:
        before = deepcopy(state)
        expect = step["expect"]
        if "code" in expect:
            with pytest.raises(rec.ReconciliationError) as refused:
                rec.decide(state, step["request"], actor="w14-publisher", at="2026-10-30T11:00:00Z")
            assert refused.value.code == expect["code"] and state == before
            continue
        state, result = rec.decide(state, step["request"], actor="w14-publisher", at="2026-10-30T11:00:00Z")
        assert result["status"] == expect["status"]
        row = state["publish_ledger"][step["request"]["event_id"]]
        assert _subset(row, expect.get("row", {}))
        if "draft_status" in expect:
            assert [d for d in state["drafts"] if d["event_id"] == step["request"]["event_id"]][0]["status"] == expect["draft_status"]
        if result["status"] == "unchanged":
            assert state == before


@pytest.fixture
def store(tmp_path):
    authority = SQLiteAuthority(tmp_path / "w14.sqlite3")
    authority.initialize(deepcopy(VECTORS["state"]))
    operators = tmp_path / "operators.json"
    operators.write_text(canonical_json({
        "w14-publisher": {"role": "publisher", "authentication_context": "local-fixture"},
        "w14-editor": {"role": "editor", "authentication_context": "local-fixture"}}))
    return authority, operators, tmp_path


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = local_cli.main(list(argv))
    return code, json.loads(out.getvalue() or err.getvalue())


def _request_file(tmp_path, name, request):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(request))
    return str(path)


def test_local_cli_inspect_confirm_repeat_and_publisher_repairs_the_draft(store):
    authority, operators, tmp_path = store
    db = str(tmp_path / "w14.sqlite3")
    code, view = cli("--database", db, "delivery", "inspect")
    rows = {row["event_id"]: row for row in view["rows"]}
    assert code == 0 and view["mutation"] == "none"
    assert rows["w14-ev-unknown"]["actions"] == ["confirm", "cancel"] and rows["w14-ev-unknown"]["hold"] == "receipt_required_unknown_stays_unknown"
    assert rows["w14-ev-notsent"]["actions"] == ["cancel"] and rows["w14-ev-confirmed"]["actions"] == []
    assert rows["w14-ev-conflict"]["hold"] == "attempt_conflicts_require_review" and not rows["w14-ev-altered"]["source_snapshot_current"]
    confirm = VECTORS["cases"][0]["steps"][0]["request"]
    path = _request_file(tmp_path, "confirm", confirm)
    version = authority.read()[0]
    code, editor = cli("--database", db, "delivery", "confirm", "--request", path, "--operators", str(operators), "--subject", "w14-editor")
    assert code == 2 and editor["error"] == "forbidden"
    assert authority.read()[0] == version
    code, applied = cli("--database", db, "delivery", "confirm", "--request", path, "--operators", str(operators), "--subject", "w14-publisher")
    assert code == 0 and applied["status"] == "applied" and applied["state_version"] == version + 1
    code, repeated = cli("--database", db, "delivery", "confirm", "--request", path, "--operators", str(operators), "--subject", "w14-publisher")
    assert code == 0 and repeated["status"] == "unchanged" and authority.read()[0] == version + 1
    # The real publisher consumer repairs the draft from the reconciled receipt.
    state = authority.read()[1]
    posting._reconcile_publish_ledger(state)
    draft = [d for d in state["drafts"] if d["event_id"] == "w14-ev-unknown"][0]
    assert draft["status"] == "posted" and draft["tweet_id"] == "1900000000000000901"
    assert state["publish_ledger"]["w14-ev-unknown"]["text"] == "Invented Fenwick Hollow reached 41 C."


@pytest.mark.parametrize("name", ["unrelated_tweet_bound_elsewhere", "stale_decision_revision", "altered_source_snapshot",
                                  "no_receipt_unknown_stays_unknown"])
def test_refusals_through_the_command_path_change_nothing(store, name):
    authority, operators, tmp_path = store
    case = next(case for case in VECTORS["cases"] if case["name"] == name)
    request = case["steps"][0]["request"]
    before = authority.read()
    code, refused = cli("--database", str(tmp_path / "w14.sqlite3"), "delivery", request["action"], "--request",
                        _request_file(tmp_path, name, request), "--operators", str(operators), "--subject", "w14-publisher")
    assert code == 2 and refused["error"] == case["steps"][0]["expect"]["code"] and authority.read() == before


def test_interrupted_reconciliation_commits_nothing_then_applies_once(store):
    authority, _operators, _tmp = store
    cancel = next(case for case in VECTORS["cases"] if case["name"] == "cancel_unknown_keeps_evidence")["steps"][0]["request"]
    before = authority.read()

    def crash():
        raise RuntimeError("invented worker interruption")

    with pytest.raises(RuntimeError):
        authority.delivery_reconciliation(cancel, PUBLISHER, before_commit=crash)
    assert authority.read() == before
    first = authority.delivery_reconciliation(cancel, PUBLISHER)
    again = authority.delivery_reconciliation(cancel, PUBLISHER)
    assert (first["status"], again["status"]) == ("applied", "unchanged")
    version, state = authority.read()
    row = state["publish_ledger"]["w14-ev-unknown"]
    assert version == before[0] + 1 and row["phase"] == "unknown" and row["tweet_id"] is None and not retry_permitted(row)
    draft = [d for d in state["drafts"] if d["event_id"] == "w14-ev-unknown"][0]
    assert draft["status"] == "rejected" and "approval_binding" not in draft
