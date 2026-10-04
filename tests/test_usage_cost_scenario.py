"""Offline, invented usage quantities; no price claim about a real account."""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import socket
import subprocess

import pytest
from google.genai.types import GenerateContentResponse

from scripts import usage_cost_scenario as cli
from src.two_bot.usage_cost_scenario import SCENARIO, project_usage_cost
from src.two_bot.usage_observations import observe_response

PRIVATE = "PRIVATE_CONTENT_CREDENTIAL_OR_DRAFT_MUST_NOT_APPEAR"


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def forbidden(*a, **kw):
        pytest.fail("Cost projection cannot make network or process calls")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def row(
    number=1, *, model="gemini-2.5-flash", prompt=1000, output=100, thought=300, cache=200, tool=0
):
    response = GenerateContentResponse.model_validate(
        {
            "modelVersion": model,
            "responseId": f"offline-{number}",
            "candidates": [{"content": {"parts": [{"text": PRIVATE}]}}],
            "usageMetadata": {
                "promptTokenCount": prompt,
                "candidatesTokenCount": output,
                "thoughtsTokenCount": thought,
                "totalTokenCount": prompt + output + thought + (tool or 0),
                "cachedContentTokenCount": cache,
                "toolUsePromptTokenCount": tool,
                "promptTokensDetails": [{"modality": "TEXT", "tokenCount": prompt}],
                "trafficType": "ON_DEMAND",
            },
        }
    )
    result = observe_response("fact_check", response, "gemini-flash-latest", "google")
    result.update(id=f"{number:032x}", observed_at="2026-10-02T12:00:00.000Z")
    return result


def window(*rows, **kw):
    return dict(schema_version=1, observations=list(rows), truncated=False, invalid=False, **kw)


def project(*rows):
    return project_usage_cost(window(*rows), scenario=SCENARIO)


def amount(result):
    return result["eligible_token_subtotal_usd"]


def test_actual_sdk_known_cache_thought_counts_are_priced_without_double_counting():
    original = row()
    before = deepcopy(original)
    result = project(original)
    # (800*.30 + 200*.03 + (100+300)*2.50)/1M.
    assert amount(result) == {"min": "0.001246000", "max": "0.001246000"}
    assert result["eligible_tokens"] == dict(prompt=1000, candidate=100, thought=300)
    assert original == before
    assert result["actual_cost_known"] is False and result["complete_account_coverage"] is False
    assert result["rows"][0]["model"] == "gemini-2.5-flash"
    assert all(s not in json.dumps(result) for s in (PRIVATE, "offline-1", "gemini-flash-latest"))


def test_unknown_cache_is_an_interval_and_missing_tool_zero_is_explicitly_derived():
    result = project(row(cache=None, tool=None))
    assert amount(result) == {"min": "0.001030000", "max": "0.001300000"}
    assert result["rows"][0]["reasons"] == [
        "zero_tool_tokens_derived_from_total",
        "cache_count_unknown_interval",
    ]


@pytest.mark.parametrize(
    "model,prompt,expected",
    [
        ("gemini-2.5-pro", 200000, "0.251000000"),
        ("gemini-2.5-pro", 200001, "0.501502500"),
        ("gemini-3.8-flash", 1000, "0.001125000"),
        ("gemini-2.5-flash", 0, "0.000250000"),
    ],
)
def test_exact_model_and_prompt_threshold_select_snapshot_rates(model, prompt, expected):
    result = project(row(model=model, prompt=prompt, output=100, thought=0, cache=0))
    assert amount(result) == {"min": expected, "max": expected}


def test_all_zero_counts_are_distinct_from_an_empty_or_unpriced_window():
    result = project(row(prompt=0, output=0, thought=0, cache=0))
    assert amount(result) == dict(min="0.000000000", max="0.000000000")
    assert result["eligible_records"] == 1
    assert amount(project()) is None
    assert amount(project(row(model="unknown"))) is None


@pytest.mark.parametrize(
    "model",
    [
        None,
        "gemini-flash-latest",
        "gemini-2.5-flash-001",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro-preview",
        PRIVATE,
    ],
)
def test_requested_alias_never_substitutes_for_unknown_resolved_identity(model):
    value = row()
    value["resolved_model"] = model
    result = project(value)
    assert amount(result) is None
    assert result["rows"][0]["reasons"] == ["unpriced_resolved_model"]
    assert result["rows"][0]["model"] == "unknown"
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "field",
    ["prompt_token_count", "candidates_token_count", "thoughts_token_count", "total_token_count"],
)
def test_required_absent_counts_cannot_be_filled_with_zero(field):
    value = row()
    value["counts"][field] = None
    result = project(value)
    assert amount(result) is None and result["rows"][0]["reasons"] == ["missing_required_count"]


@pytest.mark.parametrize("value", [True, -1, 0.5, 10**12 + 1, float("nan"), float("inf"), PRIVATE])
def test_invalid_token_records_are_excluded_not_clamped(value):
    raw = row()
    raw["counts"]["prompt_token_count"] = value
    result = project(raw)
    assert result["invalid_records"] == 1 and result["window_invalid"]
    assert result["unique_valid_records"] == 0 and amount(result) is None
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"total_token_count": 1401}, "inconsistent_total"),
        ({"tool_use_prompt_token_count": None, "total_token_count": 1401}, "unexplained_total"),
        ({"cached_content_token_count": 1001}, "cache_exceeds_prompt"),
        ({"tool_use_prompt_token_count": 2, "total_token_count": 1402}, "tool_input_not_priced"),
    ],
)
def test_inconsistent_or_unpriced_dimensions_refuse_the_whole_row(change, reason):
    raw = row()
    raw["counts"].update(change)
    result = project(raw)
    assert amount(result) is None and result["rows"][0]["reasons"] == [reason]


@pytest.mark.parametrize(
    "field,count",
    [
        ("prompt_tokens_details", 1000),
        ("candidates_tokens_details", 100),
        ("cache_tokens_details", 200),
        ("tool_use_prompt_tokens_details", 0),
    ],
)
@pytest.mark.parametrize("mode", ["TEXT", "IMAGE", "AUDIO", "MODALITY_UNSPECIFIED"])
def test_breakdowns_must_be_text_and_match_their_reported_component(field, count, mode):
    raw = row()
    raw["breakdowns"][field] = [{"modality": mode, "token_count": count + (mode == "TEXT")}]
    result = project(raw)
    assert amount(result) is None
    assert result["rows"][0]["reasons"] == ["unsupported_or_inconsistent_modality"]


@pytest.mark.parametrize(
    "field,count",
    [
        ("candidates_tokens_details", 100),
        ("cache_tokens_details", 200),
        ("tool_use_prompt_tokens_details", 0),
    ],
)
def test_consistent_optional_breakdowns_keep_the_same_price(field, count):
    raw = row()
    raw["breakdowns"][field] = [{"modality": "TEXT", "token_count": count}]
    assert amount(project(raw)) == amount(project(row()))


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_prompt_details",
        "cache_details_without_count",
        "unsupported",
        "invalid",
        "absent",
        "unknown_stage",
    ],
)
def test_missing_modality_capture_errors_and_untrusted_labels_are_explicit(mutation):
    raw = row()
    if mutation == "missing_prompt_details":
        raw["breakdowns"]["prompt_tokens_details"] = None
    if mutation == "cache_details_without_count":
        raw["counts"]["cached_content_token_count"] = None
        raw["breakdowns"]["cache_tokens_details"] = [{"modality": "TEXT", "token_count": 200}]
    if mutation == "unsupported":
        raw["unsupported_fields"] = True
    if mutation == "invalid":
        raw["invalid_fields"] = ["usage"]
    if mutation == "absent":
        raw["usage_status"] = "absent"
    if mutation == "unknown_stage":
        raw["stage"] = PRIVATE
    result = project(raw)
    if mutation == "unknown_stage":
        assert result["groups"][0]["stage"] == "unknown" and result["eligible_records"] == 1
    else:
        assert amount(result) is None
    assert PRIVATE not in json.dumps(result)


def test_exact_duplicates_count_once_and_input_is_untouched():
    value = window(row(), row())
    before = deepcopy(value)
    result = project_usage_cost(value, scenario=SCENARIO)
    assert result["input_records"] == 2 and result["exact_duplicates"] == 1
    assert result["eligible_records"] == result["unique_valid_records"] == 1
    assert amount(result) == amount(project(row())) and value == before


@pytest.mark.parametrize("identity", ["id", "response_id"])
@pytest.mark.parametrize("malformed", [False, True])
def test_competing_identities_exclude_valid_twins_even_when_one_record_is_malformed(
    identity, malformed
):
    one, two = row(1), row(2)
    two[identity] = one[identity]
    if malformed:
        two["counts"]["thoughts_token_count"] = PRIVATE
    result = project(one, two)
    assert amount(result) is None
    assert result["conflicting_records"] == (1 if malformed else 2)
    assert result["invalid_records"] == int(malformed)
    assert result["eligible_records"] == 0


def test_independent_null_provider_ids_are_not_a_conflict():
    one, two = row(1), row(2)
    one["response_id"] = two["response_id"] = None
    assert project(one, two)["eligible_records"] == 2


def test_groups_counts_ranges_flags_and_reordering_reconcile_without_accounting_claims():
    one, two, three = row(1), row(2, cache=None), row(3)
    two["stage"] = "critic"
    three["provider"] = "unknown"
    three.update(counts={}, labels={}, breakdowns={}, unsupported_fields=True)
    value = window(one, two, three)
    value.update(truncated=True, invalid=True)
    result = project_usage_cost(value, scenario=SCENARIO)
    assert result == project_usage_cost(
        {**value, "observations": list(reversed(value["observations"]))}, scenario=SCENARIO
    )
    assert result["window_truncated"] and result["window_invalid"]
    assert (
        result["eligible_records"] == 2
        and result["excluded_records"] == result["non_google_records"] == 1
    )
    assert (
        sum(g["unique_valid_records"] for g in result["groups"]) == result["unique_valid_records"]
    )
    for field in ("min", "max"):
        assert sum(
            Decimal(g["eligible_token_subtotal_usd"][field])
            for g in result["groups"]
            if g["eligible_token_subtotal_usd"] is not None
        ) == Decimal(amount(result)[field])
    excluded = next(g for g in result["groups"] if not g["eligible_records"])
    assert excluded["eligible_tokens"] is None and excluded["eligible_token_subtotal_usd"] is None


@pytest.mark.parametrize(
    "value",
    [None, {}, [], {"schema_version": 2}, window(*[row()] * 33), {**window(), "truncated": 1}],
)
def test_invalid_or_absent_envelopes_are_not_zero_spend(value):
    with pytest.raises(ValueError):
        project_usage_cost(value, scenario=SCENARIO)


def test_unknown_scenario_and_integral_float_counts():
    with pytest.raises(ValueError, match="unsupported_cost_scenario"):
        project_usage_cost(window(), scenario=PRIVATE)
    raw = row()
    raw["counts"] = {k: float(v) if v is not None else None for k, v in raw["counts"].items()}
    assert amount(project(raw)) == amount(project(row()))


@pytest.mark.parametrize("state_mode", [False, True])
def test_cli_reads_only_without_printing_unrelated_state_or_provider_content(
    tmp_path, capsys, monkeypatch, state_mode
):
    value = window(row())
    if state_mode:
        value = {
            "llm_usage_observations": value,
            "drafts": [{"text": PRIVATE}],
            "private_key": PRIVATE,
        }
    p = tmp_path / "private.json"
    p.write_text(json.dumps(value))
    before = hashlib.sha256(p.read_bytes()).hexdigest()
    original = type(p).open

    def read_only(path, mode="r", *a, **kw):
        assert mode in ("r", "rb")
        return original(path, mode, *a, **kw)

    monkeypatch.setattr(type(p), "open", read_only)
    assert cli.main(["--state" if state_mode else "--window", str(p), "--scenario", SCENARIO]) == 0
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out and not captured.err
    result = json.loads(captured.out)
    assert result == project(row()) and hashlib.sha256(p.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "text", ["{", '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '"' + PRIVATE + '"', "{}"]
)
def test_cli_invalid_input_reports_fixed_error_without_echo(tmp_path, capsys, text):
    p = tmp_path / PRIVATE
    p.write_text(text)
    assert cli.main(["--state", str(p), "--scenario", SCENARIO]) == 2
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out + captured.err and not captured.err
    assert json.loads(captured.out)["eligible_token_subtotal_usd"] is None


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--state", PRIVATE],
        ["--window", PRIVATE, "--scenario", PRIVATE],
        ["--state", PRIVATE, "--window", PRIVATE, "--scenario", SCENARIO],
    ],
)
def test_cli_bad_arguments_never_echo_arbitrary_values(args, capsys):
    assert cli.main(args) == 2
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out + captured.err


def test_cli_bounded_input_and_output(tmp_path, monkeypatch, capsys):
    p = tmp_path / "usage.json"
    p.write_text(json.dumps(window(row())))
    monkeypatch.setattr(cli, "MAX_BYTES", 10)
    args = ["--window", str(p), "--scenario", SCENARIO]
    assert cli.main(args) == 2
    monkeypatch.setattr(cli, "MAX_BYTES", 20 * 1024 * 1024)
    monkeypatch.setattr(cli, "MAX_OUTPUT_BYTES", 10)
    assert cli.main(args) == 2
    assert PRIVATE not in capsys.readouterr().out


def test_maximum_window_and_counts_remain_finite_exact_and_bounded():
    rows = [row(n, prompt=10**12 - 2, output=1, thought=1, cache=0) for n in range(32)]
    result = project(*rows)
    assert result["eligible_records"] == 32
    assert Decimal(amount(result)["min"]) == Decimal("9600000.0001408")
    assert amount(result)["min"] == amount(result)["max"]
    assert len(json.dumps(result).encode()) < cli.MAX_OUTPUT_BYTES


@pytest.mark.parametrize(
    "broken",
    [
        False,
        PRIVATE,
        {"id": "x"},
        {"provider": ["google"]},
        {"counts": {"prompt_token_count": PRIVATE}},
    ],
)
def test_malformed_rows_are_counted_without_leaking_content_or_crashing(broken):
    result = project(row(), broken)
    assert result["input_records"] == 2 and result["invalid_records"] == 1
    assert result["eligible_records"] == 1
    assert (
        result["input_records"]
        == result["invalid_records"] + result["exact_duplicates"] + result["unique_valid_records"]
    )
    assert PRIVATE not in json.dumps(result)


def test_non_google_model_name_cannot_select_or_appear_under_google_price_group():
    from tests.test_usage_observations import anthropic_response

    observed = observe_response("writer", anthropic_response(), "gemini-2.5-flash", "anthropic")
    observed["resolved_model"] = "gemini-2.5-flash"
    result = project(observed)
    assert amount(result) is None and result["non_google_records"] == 1
    assert result["groups"][0]["model"] == "unknown"


def test_cli_nonexistent_and_invalid_utf8_files_are_unavailable_without_path_leak(tmp_path, capsys):
    path = tmp_path / PRIVATE
    args = ["--window", str(path), "--scenario", SCENARIO]
    assert cli.main(args) == 2
    path.write_bytes(b"\xff")
    assert cli.main(args) == 2
    result = capsys.readouterr()
    assert PRIVATE not in result.out + result.err


def test_deep_malformed_row_does_not_hide_valid_rows_or_mutate_original():
    nested = []
    for _ in range(1500):
        nested = [nested]
    malformed = {"unexpected": nested}
    result = project(row(), malformed)
    assert result["invalid_records"] == 1 and result["eligible_records"] == 1
    assert malformed["unexpected"] is nested


def test_deep_malformed_counterpart_still_fences_valid_identity():
    one = row()
    bad = {"id": one["id"], "unexpected": []}
    bad["unexpected"].append(bad)
    result = project(one, bad)
    assert result["invalid_records"] == 1 and result["conflicting_records"] == 1
    assert amount(result) is None
