"""Cost coverage: real reader/merge/storage boundaries, no paid calls."""
from copy import deepcopy
from datetime import datetime, timezone
from itertools import permutations
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from src.orchestrator import budget
from src.state import DEFAULT_STATE, _merge_llm_usage
from src.two_bot import usage_ledger as ledger
from src.two_bot.usage_summary import summarize_usage

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
DAY = "2026-09-09"


def row(*, calls=1, usd=0.03, priced=1, unknown=0, missing=0):
    return {"calls": calls, "in": 10000, "out": 0, "cache_write": 0, "cached_in": 0,
            "usd": usd, "priced_usd": usd, "priced_calls": priced,
            "unpriced_calls": unknown, "missing_usage_calls": missing}


def state(*rows):
    return {"llm_usage": {DAY: {f"writer|fixture-{index}": item for index, item in enumerate(rows)}}}


def node(script, data):
    result = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(data),
                            cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_unknown_model_and_missing_metadata_are_counted_without_a_free_price():
    ledger._BUFFER.clear()
    try:
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        ledger.record_usage("writer", "unknown-model", input_tokens=10000)
        ledger.record_writer_response(SimpleNamespace(usage=None), "claude-sonnet-4-6", "anthropic")
        snapshot = {}
        assert ledger.drain_into_state(snapshot) == 3
        bucket = next(iter(snapshot["llm_usage"].values()))
        known = bucket["writer|claude-sonnet-4-6"]
        assert known["calls"] == 2 and known["priced_calls"] == known["unpriced_calls"] == known["missing_usage_calls"] == 1
        assert known["usd"] == known["priced_usd"] == 0.03
        unknown = bucket["writer|unknown-model"]
        assert unknown["in"] == 10000 and unknown["unpriced_calls"] == 1 and unknown["priced_calls"] == 0
        unknown_summary = summarize_usage({"llm_usage": {DAY: {"writer|unknown": unknown}}}, now=NOW)
        assert unknown_summary["known_cost_usd"] is None and unknown_summary["recorded_estimate_usd"] is None
    finally:
        ledger._BUFFER.clear()


@pytest.mark.parametrize("state_value", [
    {}, {"llm_usage": None}, {"llm_usage": {}},
    state({"calls": 3, "usd": 1.25}), state({"calls": 3, "usd": 0.0}),
    state(row()), state(row(calls=1.0, priced=1.0)), state(row(usd=0, priced=0, unknown=1)),
    state(row(usd=0, priced=0, unknown=1, missing=1)),
    state(row(), {"calls": 3, "usd": 1.25}, row(usd=0, priced=0, unknown=1)),
    state(row(calls=1, priced=1, unknown=1)), state(row(missing=1)),
    state({**row(), "priced_usd": True}), state({**row(), "cost_coverage_invalid": True}),
    state({**row(), "priced_calls": None}), state({"calls": 1, "usd": -9}),
    {"llm_usage": {"2026-09-10": {"writer|future": row()}}},
])
def test_python_javascript_summary_parity_and_read_only(state_value):
    before = deepcopy(state_value)
    expected = summarize_usage(state_value, now=NOW)
    actual = node('''
      import {readFileSync} from "node:fs";
      import {summarizeUsage} from "./dashboard/lib/usage-ledger.js";
      const {state, now} = JSON.parse(readFileSync(0,"utf8"));
      console.log(JSON.stringify(summarizeUsage(state, {now: Date.parse(now)})));
    ''', {"state": state_value, "now": NOW.isoformat()})
    assert actual == expected and state_value == before
    assert expected["coverage"] != "complete" and expected["budget_enforced"] is False
    status = budget.budget_status(state_value, now=NOW)
    assert status["mtd_usd"] == expected["recorded_estimate_usd"]
    assert "budget not enforced" in budget.status_message(status)
    if status["mtd_usd"] is None:
        assert status["projected_usd"] is None and "unavailable" in budget.status_message(status)


def test_new_capture_preserves_legacy_estimates_and_marks_old_coverage_unverified():
    ledger._BUFFER.clear()
    try:
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        day = ledger._BUFFER[0]["day"]
        old = {"calls": 7, "in": 42, "out": 8, "cache_write": 3, "cached_in": 2, "usd": 1.23}
        snapshot = {"llm_usage": {day: {"writer|claude-sonnet-4-6": deepcopy(old)}}}
        ledger.drain_into_state(snapshot)
        new = snapshot["llm_usage"][day]["writer|claude-sonnet-4-6"]
        assert new["usd"] == 1.26 and new["calls"] == 8 and new["in"] == 10042
        assert new["out"] == 8 and new["cache_write"] == 3 and new["cached_in"] == 2
        summary = summarize_usage(snapshot)
        assert summary["known_cost_usd"] == 0.03 and summary["legacy_estimate_usd"] == 1.23 and summary["legacy_calls"] == 7
    finally:
        ledger._BUFFER.clear()


def test_merge_parity_and_concurrent_counter_conflicts_never_become_known_total():
    snapshots = [state(row())["llm_usage"], state(row(calls=2, usd=0.06, priced=2))["llm_usage"],
                 state(row(calls=2, usd=0.03, unknown=1))["llm_usage"]]
    expected = None
    for order in permutations(snapshots):
        merged = _merge_llm_usage(_merge_llm_usage(order[0], order[1]), order[2])
        if expected is None:
            expected = merged
        assert merged == expected and _merge_llm_usage(merged, merged) == merged
    actual = node('''
      import {readFileSync} from "node:fs";
      import {mergeUsageLedgers} from "./dashboard/lib/usage-ledger.js";
      const rows=JSON.parse(readFileSync(0,"utf8"));
      console.log(JSON.stringify(rows.reduce(mergeUsageLedgers, {})));
    ''', snapshots)
    assert actual == expected
    summary = summarize_usage({"llm_usage": expected}, now=NOW)
    assert summary["coverage"] == "inconsistent" and summary["known_cost_usd"] is None and summary["recorded_estimate_usd"] is None
    aggregate = next(iter(expected[DAY].values()))
    assert aggregate["calls"] == 2 and aggregate["priced_calls"] == 2 and aggregate["unpriced_calls"] == 1


def test_real_python_dashboard_python_sqlite_roundtrip_retains_coverage_and_receipts(tmp_path):
    from src.storage import sqlite_store
    from tests.test_persistence_contract import node_store
    snapshot = deepcopy(DEFAULT_STATE)
    snapshot.update(state(row(), {"calls": 7, "in": 42, "out": 8, "cache_write": 3, "cached_in": 2, "usd": 1.23}))
    snapshot["drafts"] = [{"id": "posted", "text": "Retained exact copy", "status": "posted", "tweet_id": "receipt", "publish_outcome": "confirmed"}]
    snapshot["publish_ledger"] = {"posted": {"phase": "unknown", "text_sha256": "f" * 64}}
    path = tmp_path / "usage.sqlite"
    assert sqlite_store.write_state(str(path), snapshot)
    node_store(path, "write", {"drafts": snapshot["drafts"]})
    restored = sqlite_store.read_state(str(path), DEFAULT_STATE)
    assert restored["llm_usage"] == snapshot["llm_usage"]
    assert restored["drafts"] == snapshot["drafts"] and restored["publish_ledger"] == snapshot["publish_ledger"]
    # A dashboard write carrying stale metadata must not erase newer counters.
    node_store(path, "write", state({"calls": 0, "usd": 0}))
    final = sqlite_store.read_state(str(path), DEFAULT_STATE)
    assert final["llm_usage"] == _merge_llm_usage(snapshot["llm_usage"], state({"calls": 0, "usd": 0})["llm_usage"])


@pytest.mark.parametrize("value", ["inf", "nan", "-1"])
def test_nonfinite_budget_configuration_never_implies_an_unlimited_budget(monkeypatch, value):
    monkeypatch.setenv("THEHEAT_MONTHLY_BUDGET_USD", value)
    assert budget.monthly_budget_usd() == 14


def test_actual_dashboard_api_and_python_budget_share_nullable_subtotals(monkeypatch):
    monkeypatch.delenv("THEHEAT_MONTHLY_BUDGET_USD", raising=False)
    cases = [{}, state(row()), state({"calls": 4, "usd": 0}),
             state(row(usd=0, priced=0, unknown=1)),
             state(row(), {"calls": 3, "usd": 1.25}, row(usd=0, priced=0, unknown=1)),
             state(row(calls=1, priced=1, unknown=1))]
    result = node('''
      import {readFileSync} from "node:fs";
      const {cases, now} = JSON.parse(readFileSync(0,"utf8"));
      const RealDate = Date;
      globalThis.Date = class extends RealDate { constructor(...args) { super(...(args.length ? args : [now])) } static now() { return RealDate.parse(now) } };
      Object.assign(process.env, {NODE_ENV:"production", DASHBOARD_USERNAME:"fixture", DASHBOARD_PASSWORD:"fixture", THEHEAT_STATE_BACKEND:"gist", THEHEAT_DB_PATH:"", GIST_ID:"fixture", GITHUB_TOKEN:"fixture"});
      delete process.env.THEHEAT_MONTHLY_BUDGET_USD;
      const {GET} = await import("./dashboard/app/api/usage/route.js");
      const outputs=[];
      for (const state of cases) {
        globalThis.fetch = async () => ({ok:true, status:200, json:async () => ({files:{"state.json":{content:JSON.stringify(state)}}})});
        const response = await GET(new Request("http://localhost/api/usage", {headers:{authorization:"Basic " + Buffer.from("fixture:fixture").toString("base64")}}));
        if (response.status !== 200) throw Error(await response.text());
        outputs.push(await response.json());
      }
      console.log(JSON.stringify(outputs));
    ''', {"cases": cases, "now": NOW.isoformat()})
    for case, payload in zip(cases, result):
        expected = budget.budget_status(case, now=NOW)
        assert {key: payload[key] for key in expected} == expected
        assert "budget not enforced" in budget.status_message(expected)


def test_missing_or_malformed_usage_metadata_records_one_unpriced_response():
    class BadResponse:
        @property
        def usage(self):
            raise ValueError("fixture metadata failure")
    ledger._BUFFER.clear()
    try:
        for response in (BadResponse(), SimpleNamespace(usage=SimpleNamespace(input_tokens=10)),
                         SimpleNamespace(usage=SimpleNamespace(input_tokens=float("inf"), output_tokens=2))):
            ledger.record_writer_response(response, "claude-sonnet-4-6", "anthropic")
        assert len(ledger._BUFFER) == 3
        assert all(row["unpriced_calls"] == row["missing_usage_calls"] == 1 and row["priced_calls"] == 0 for row in ledger._BUFFER)
    finally:
        ledger._BUFFER.clear()


def test_legacy_zero_is_retained_but_cannot_establish_free_accounting():
    snapshot = state({"calls": 2, "usd": 0})
    before = deepcopy(snapshot)
    summary = summarize_usage(snapshot, now=NOW)
    assert summary["legacy_calls"] == 2 and summary["legacy_estimate_usd"] == 0
    assert summary["recorded_estimate_usd"] is None and summary["known_cost_usd"] is None
    assert snapshot == before


def merge_in_node(rows):
    return node('''
      import {readFileSync} from "node:fs";
      import {mergeUsageLedgers} from "./dashboard/lib/usage-ledger.js";
      console.log(JSON.stringify(JSON.parse(readFileSync(0,"utf8")).reduce(mergeUsageLedgers, {})));
    ''', rows)


@pytest.mark.parametrize("bad", [row(calls=True), row(unknown=1), {**row(), "priced_calls": False}])
def test_raw_contradictions_cannot_be_laundered_by_legacy_normalization_or_larger_calls(bad):
    old, later = state(bad)["llm_usage"], state({"calls": 2, "usd": 0.03})["llm_usage"]
    for first, second in ((old, later), (later, old)):
        merged = _merge_llm_usage(first, second)
        assert merged == merge_in_node([first, second])
        assert summarize_usage({"llm_usage": merged}, now=NOW)["known_cost_usd"] is None
        agg = next(iter(merged[DAY].values()))
        assert agg["cost_coverage_invalid"] is True and agg["calls"] == 2 and agg["usd"] == 0.03


def test_original_witnesses_make_resolving_maxima_associative_without_erasing_conflicts():
    # A/B conflict; C's larger calls makes final arithmetic look consistent.
    snapshots = [state(row())["llm_usage"], state(row(usd=0, priced=0, unknown=1))["llm_usage"],
                 state(row(calls=2, priced=1, unknown=1))["llm_usage"]]
    expected = None
    for a, b, c in permutations(snapshots):
        left = _merge_llm_usage(_merge_llm_usage(a, b), c)
        right = _merge_llm_usage(a, _merge_llm_usage(b, c))
        assert left == right == merge_in_node([a, b, c])
        if expected is None:
            expected = left
        assert left == expected
        assert summarize_usage({"llm_usage": left}, now=NOW)["coverage"] == "inconsistent"
    assert len(next(iter(expected[DAY].values()))["cost_coverage_snapshots"]) == 3


def test_witness_cap_is_deterministic_and_overflow_never_claims_known_cost():
    from src.two_bot.usage_coverage import SNAPSHOT_LIMIT
    snapshots = [state(row(calls=n, usd=n*0.03, priced=n))["llm_usage"] for n in range(1, SNAPSHOT_LIMIT+4)]
    results = []
    for values in (snapshots, list(reversed(snapshots)), snapshots[::2]+snapshots[1::2]):
        merged = {}
        for value in values:
            merged = _merge_llm_usage(merged, value)
        assert merged == merge_in_node(values)
        results.append(merged)
    assert results[0] == results[1] == results[2]
    agg = next(iter(results[0][DAY].values()))
    assert len(agg["cost_coverage_snapshots"]) == SNAPSHOT_LIMIT
    assert agg["cost_coverage_overflow"] is True and agg["calls"] == SNAPSHOT_LIMIT+3
    assert summarize_usage({"llm_usage": results[0]}, now=NOW)["recorded_estimate_usd"] is None


@pytest.mark.parametrize("value", ["0x10", "0b10", "3.5", "1e-3", True, "-0", " 2.5 "])
def test_legacy_numeric_conversion_has_real_runtime_parity(value):
    snapshot = state({"calls": 1, "usd": value})["llm_usage"]
    assert _merge_llm_usage(snapshot, {}) == merge_in_node([snapshot, {}])


@pytest.mark.parametrize("provider,field", [("anthropic", "cache_creation_input_tokens"),
                                            ("anthropic", "cache_read_input_tokens"),
                                            ("google", "cached_content_token_count")])
@pytest.mark.parametrize("value", [False, "", None])
def test_optional_cache_metadata_only_normalizes_absence(provider, field, value):
    ledger._BUFFER.clear()
    try:
        fields = {"input_tokens": 10, "output_tokens": 2} if provider == "anthropic" else {"prompt_token_count": 10, "candidates_token_count": 2}
        response = SimpleNamespace(**{"usage" if provider == "anthropic" else "usage_metadata": SimpleNamespace(**fields, **{field: value})})
        ledger.record_writer_response(response, "claude-sonnet-4-6", provider)
        assert len(ledger._BUFFER) == 1
        assert ledger._BUFFER[0]["priced_calls"] == int(value is None and provider == "anthropic")
        assert ledger._BUFFER[0]["missing_usage_calls"] == int(value is not None)
    finally:
        ledger._BUFFER.clear()


def test_drain_does_not_mutate_shared_defaults_and_retains_prior_contradictions():
    from src.two_bot.usage_coverage import SNAPSHOTS
    ledger._BUFFER.clear()
    before = deepcopy(DEFAULT_STATE)
    try:
        snapshot = dict(DEFAULT_STATE)
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        ledger.drain_into_state(snapshot)
        assert DEFAULT_STATE == before
        day = next(iter(snapshot["llm_usage"]))
        agg = snapshot["llm_usage"][day]["writer|claude-sonnet-4-6"]
        assert len(agg[SNAPSHOTS]) == 1
        agg["unpriced_calls"] = 1  # An altered projection cannot rewrite its original evidence.
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        ledger.drain_into_state(snapshot)
        assert summarize_usage(snapshot)["known_cost_usd"] is None
        assert snapshot["llm_usage"][day]["writer|claude-sonnet-4-6"]["cost_coverage_invalid"] is True
    finally:
        ledger._BUFFER.clear()


def test_numeric_witnesses_deduplicate_across_integer_float_and_negative_zero_roundtrips():
    a = state(row(calls=1.0, usd=0.0, priced=1.0))["llm_usage"]
    b = state(row(calls=1, usd=-0.0, priced=1))["llm_usage"]
    merged = _merge_llm_usage(a,b)
    assert merged == merge_in_node([a,b])
    assert len(next(iter(merged[DAY].values()))["cost_coverage_snapshots"]) == 1
    assert summarize_usage({"llm_usage":merged}, now=NOW)["known_cost_usd"] == 0


def test_huge_corrupt_coverage_does_not_partially_fold_or_duplicate_responses(monkeypatch):
    ledger._BUFFER.clear()
    try:
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        ledger.record_usage("writer", "claude-haiku-4-5", input_tokens=10000)
        day = ledger._BUFFER[0]["day"]
        snapshot = {"llm_usage":{day:{"writer|claude-haiku-4-5":{**row(), "priced_usd":10**400}}}}
        assert ledger.drain_into_state(snapshot) == 2
        assert ledger.drain_into_state(snapshot) == 0
        assert snapshot["llm_usage"][day]["writer|claude-sonnet-4-6"]["calls"] == 1
        assert summarize_usage(snapshot)["known_cost_usd"] is None
        # Also prove arbitrary unexpected mid-fold failure commits nothing.
        ledger.record_usage("writer", "claude-sonnet-4-6", input_tokens=10000)
        ledger.record_usage("writer", "claude-haiku-4-5", input_tokens=10000)
        before = deepcopy(snapshot)
        original = ledger._valid_agg
        calls = 0
        def fail_second(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("fixture mid-fold failure")
            return original(value)
        with monkeypatch.context() as patch:
            patch.setattr(ledger,"_valid_agg",fail_second)
            assert ledger.drain_into_state(snapshot) == 0
        assert snapshot == before and len(ledger._BUFFER) == 2
        assert ledger.drain_into_state(snapshot) == 2
        assert snapshot["llm_usage"][day]["writer|claude-sonnet-4-6"]["calls"] == 2
    finally:
        ledger._BUFFER.clear()
