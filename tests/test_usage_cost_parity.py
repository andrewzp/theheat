"""Shared synthetic contract matrix: Python results must equal server-side JS.

Provider calls are forbidden by test_usage_cost_scenario's independent suite.
This matrix uses a single local Node process and never loads production state.
"""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from scripts.gen_usage_cost_contract import OUTPUT, render
from src.two_bot.usage_cost_scenario import SCENARIO, project_usage_cost
from tests.test_usage_cost_scenario import row, window

ROOT = Path(__file__).resolve().parents[1]


def cases():
    result = {}

    def add(name, *rows, envelope=None, scenario=SCENARIO):
        result[name] = {
            "window": envelope if envelope is not None else window(*rows),
            "scenario": scenario,
        }

    add("empty")
    add("known_cache", row())
    add("unknown_cache_tool", row(cache=None, tool=None))
    add("zero", row(prompt=0, output=0, thought=0, cache=0))
    for model in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.8-flash"]:
        for prompt in [0, 200000, 200001, 10**12 - 2]:
            for cache in [0, None, prompt]:
                add(
                    f"rates-{model}-{prompt}-{cache}",
                    row(model=model, prompt=prompt, output=1, thought=1, cache=cache),
                )
    for model in [
        None,
        "gemini-flash-latest",
        "gemini-2.5-flash-001",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro-preview",
        "PRIVATE",
        "__proto__",
        "constructor",
        "toString",
    ]:
        value = row()
        value["resolved_model"] = model
        add(f"unknown_model-{model}", value)
    for field in row()["counts"]:
        for raw in [None, True, -1, 0.5, 10**12 + 1, "PRIVATE", {}, []]:
            value = row()
            value["counts"][field] = raw
            add(f"count-{field}-{raw}", value)
    for field, count in [
        ("prompt_tokens_details", 1000),
        ("candidates_tokens_details", 100),
        ("cache_tokens_details", 200),
        ("tool_use_prompt_tokens_details", 0),
    ]:
        for modality in ["TEXT", "IMAGE", "AUDIO", "MODALITY_UNSPECIFIED"]:
            for delta in [0, 1]:
                value = row()
                value["breakdowns"][field] = [{"modality": modality, "token_count": count + delta}]
                add(f"modality-{field}-{modality}-{delta}", value)
    for name, update in {
        "inconsistent_total": {"total_token_count": 1401},
        "unexplained_total": {"tool_use_prompt_token_count": None, "total_token_count": 1401},
        "cache_excess": {"cached_content_token_count": 1001},
        "tool": {"tool_use_prompt_token_count": 2, "total_token_count": 1402},
    }.items():
        value = row()
        value["counts"].update(update)
        add(name, value)
    for name, update in {
        "unsupported": {"unsupported_fields": True},
        "invalid": {"invalid_fields": ["usage"]},
        "absent": {"usage_status": "absent"},
        "stage": {"stage": "PRIVATE"},
        "badtime": {"observed_at": "2026-02-30T12:00:00.000Z"},
        "badyear": {"observed_at": "0000-01-01T12:00:00.000Z"},
    }.items():
        value = row()
        value.update(update)
        add(name, value)
    value = row()
    value["breakdowns"]["prompt_tokens_details"] = None
    add("missing_prompt", value)
    value = row(cache=None)
    value["breakdowns"]["cache_tokens_details"] = [{"modality": "TEXT", "token_count": 200}]
    add("cache_details_no_count", value)
    add("exact_duplicate", row(), row())
    floating = row()
    floating["schema_version"] = 1.0
    floating["counts"] = {
        k: float(v) if v is not None else None for k, v in floating["counts"].items()
    }
    floating["breakdowns"]["prompt_tokens_details"][0]["token_count"] = 1000.0
    add("semantic_duplicate", row(), floating)
    for identity in ["id", "response_id"]:
        for invalid in [False, True]:
            one, two = row(1), row(2)
            two[identity] = one[identity]
            if invalid:
                two["counts"]["thoughts_token_count"] = "PRIVATE"
            add(f"conflict-{identity}-{invalid}", one, two)
        different = deepcopy(floating)
        different["counts"]["cached_content_token_count"] = 0.0
        add(f"numeric_real_conflict-{identity}", row(), different)
    one, two = row(1), row(2)
    one["response_id"] = two["response_id"] = None
    add("null_responses", one, two)
    for provider in ["anthropic", "unknown"]:
        from src.two_bot.usage_observations import CONTRACT

        other = row(3)
        other["provider"] = provider
        for field in ["counts", "labels", "breakdowns"]:
            other[field] = dict.fromkeys(CONTRACT[field][provider])
        add(f"other-{provider}", other)
    mixed = window(row(), row(2, cache=None), other)
    mixed.update(truncated=True, invalid=True)
    add("mixed", envelope=mixed)
    add("mixed_reversed", envelope={**mixed, "observations": list(reversed(mixed["observations"]))})
    for n, raw in enumerate(
        [
            False,
            "PRIVATE",
            {"id": "x"},
            {"provider": ["google"]},
            {"__proto__": {"private": "PRIVATE"}},
        ]
    ):
        add(f"malformed-{n}", row(), raw)
    for n, raw in enumerate(
        [
            {},
            [],
            {"schema_version": 2},
            window(*[row()] * 33),
            {**window(), "truncated": 1},
            {**window(), "schema_version": True},
        ]
    ):
        add(f"envelope-{n}", envelope=raw)
    result["absent_window"] = {"window": None, "scenario": SCENARIO}
    add("unknown_scenario", scenario="PRIVATE")
    add("max_window", *[row(n, prompt=10**12 - 2, output=1, thought=1, cache=0) for n in range(32)])
    add("tiny", row(prompt=1, output=0, thought=0, cache=1))
    add(
        "negative_zero",
        row(prompt=-0.0, output=0, thought=0, cache=-0.0),
        row(prompt=0, output=0, thought=0, cache=0),
    )
    return result


CASES = cases()


@pytest.fixture(scope="module")
def javascript():
    run = subprocess.run(
        ["node", "scripts/project-cost-parity.mjs"],
        cwd=ROOT,
        input=json.dumps(CASES),
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert not run.stderr
    return json.loads(run.stdout)


@pytest.mark.parametrize("name", CASES)
def test_python_javascript_parity(name, javascript):
    value = CASES[name]
    before = deepcopy(value)
    try:
        expected = project_usage_cost(value["window"], scenario=value["scenario"])
    except ValueError as exc:
        expected = {"error": str(exc)}
    assert javascript[name] == expected
    assert value == before


def test_generated_rate_contract_is_current():
    assert OUTPUT.read_text() == render()


def test_v2_numeric_identity_is_versioned_and_real_changes_still_conflict():
    for name in ["semantic_duplicate", "negative_zero"]:
        report = project_usage_cost(CASES[name]["window"], scenario=SCENARIO)
        assert report["schema_version"] == 2
        assert report["identity_semantics"] == "validated_integer_fields_v2"
        assert report["exact_duplicates"] == 1 and report["eligible_records"] == 1
    report = project_usage_cost(CASES["numeric_real_conflict-id"]["window"], scenario=SCENARIO)
    assert report["conflicting_records"] == 2 and report["eligible_token_subtotal_usd"] is None
