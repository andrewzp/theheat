"""Parity with the pre-extraction passive contract; no authority or DB calls."""

import ast
from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.media.temperature_graphic_adapter import temperature_claim_graphic_spec
from src.two_bot import ghcn_claim_contract as passive, ghcn_claim_view as resolver
from tests.ghcn_claim_contract_helpers import (
    VARIANTS, outcome, pair, projection_cases, signature, structural_cases,
)

GOLDEN = json.loads((Path(__file__).parent / "fixtures/ghcn_claim_contract_v1.json").read_text())


@pytest.fixture(scope="module")
def examples():
    return {(direction, tier): pair(passive, direction, tier) for direction, tier in VARIANTS}


@pytest.mark.parametrize("direction,tier", VARIANTS)
def test_exact_pre_extraction_projection_reference_and_validated_graphic(examples, direction, tier):
    full, full_json, view, ref = deepcopy(examples[direction, tier])
    original = deepcopy(full.to_dict())
    expected = GOLDEN["valid"][direction + "_" + tier]
    assert signature(view) == expected["view"]
    assert passive.structural_view(view) is view["raw_signal_dump"]["ghcn_claim_view"]
    assert signature(resolver.structural_view(view)) == expected["reference"]
    assert signature(passive.project_tree(full_json, ref, ref["selection"])) == expected["project_tree"]
    assert resolver.project_tree(full_json, ref, ref["selection"]) == view
    assert passive.json_tree(resolver.project(full, ref, ref["selection"]).to_dict()) == view
    spec = temperature_claim_graphic_spec(view, full,
        expected_full_sha256=resolver.fingerprint(full_json), synthetic=True)
    assert signature(spec) == expected["spec"]
    assert full.to_dict() == original and full_json == passive.json_tree(original)


def passive_error(expected):
    result = deepcopy(expected)
    if result.get("exception") == "src.storage.cyclone_supply.CycloneSupplyError":
        result["exception"] = "src.two_bot.ghcn_claim_contract.ClaimContractError"
    elif result.get("exception") == "src.commands.schema.CommandError":
        result["exception"] = "src.two_bot.ghcn_claim_contract.ClaimJSONError"
    return result


@pytest.mark.parametrize("name", sorted(GOLDEN["structural"]))
def test_structural_shape_limits_numbers_and_legacy_exception_compatibility(examples, name):
    value = structural_cases(examples["high", "all_time"][2])[name]
    original = deepcopy(value)
    expected = GOLDEN["structural"][name]
    if name == "date":
        # Root's T3-F1 amendment normalizes invalid selection dates only. Keep
        # the original raw ValueError in the frozen pre-extraction fixture.
        expected = dict(status="error", exception="src.storage.cyclone_supply.CycloneSupplyError",
                        message="ghcn_claim_view_shape", code=None)
    assert outcome(resolver.structural_view, value) == expected
    assert outcome(passive.structural_view, value) == passive_error(expected)
    # NaN is deliberately one invalid input and does not compare equal to itself.
    assert json.dumps(value, sort_keys=True) == json.dumps(original, sort_keys=True)


@pytest.mark.parametrize("bad_date", ["not-a-date", 123], ids=["invalid-string", "integer"])
def test_imported_invalid_selection_date_is_a_bounded_shape_refusal(examples, bad_date):
    from src.storage.cyclone_supply import CycloneSupplyError

    value = deepcopy(examples["high", "all_time"][2])
    value["raw_signal_dump"]["ghcn_claim_view"]["selection"]["signal_date"] = bad_date
    with pytest.raises(CycloneSupplyError, match="^ghcn_claim_view_shape$"):
        resolver.structural_view(value)
    with pytest.raises(passive.ClaimContractError, match="^ghcn_claim_view_shape$"):
        passive.structural_view(value)


@pytest.mark.parametrize("name", sorted(GOLDEN["projection"]))
def test_malformed_projection_preserves_old_bounded_failures(examples, name):
    _, full_json, _, ref = examples["high", "all_time"]
    value = projection_cases(full_json)[name]
    expected = GOLDEN["projection"][name]
    assert outcome(resolver.project_tree, value, ref, ref["selection"]) == expected
    assert outcome(passive.project_tree, value, ref, ref["selection"]) == passive_error(expected)


def test_namespace_and_codec_contracts_match_execution_owners():
    from src.storage import ghcn_runtime_inputs
    from src.storage.scientific_supply import NAMESPACE

    assert passive.INPUT == ghcn_runtime_inputs.INPUT
    assert passive.RESULT == ghcn_runtime_inputs.RESULT
    assert passive.NAMESPACE == NAMESPACE
    assert resolver.TYPES is passive.TYPES
    for name in ("BASELINE_FIELDS", "VARIABLE_SCALARS", "TABLE_FIELDS", "EVIDENCE_FIELDS"):
        assert getattr(resolver, name) is getattr(passive, name)


def test_passive_module_imports_only_existing_lightweight_contracts():
    tree = ast.parse(Path(passive.__file__).read_text())
    imported = {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("src.")}
    assert imported == {"src.two_bot.json_utils", "src.two_bot.types"}
    assert all(not alias.name.startswith(("src.commands", "src.storage", "src.orchestrator",
                                         "anthropic", "google", "psycopg"))
               for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
