"""Cross-check the inventory against real wiring, without executing adapters."""

import ast
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.data.source_registry import CONTRACTS, TELEMETRY_KEYS, registry_document, validate_contracts

ROOT = Path(__file__).resolve().parents[1]


def test_all_actual_alert_runners_health_keys_and_serial_calls_have_one_contract():
    tree = ast.parse((ROOT / "src/orchestrator/run_alerts.py").read_text())
    runners = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == "SourceRunner"]
    contracts = {row.source_id: row for row in CONTRACTS if row.source_id != "leaderboard"}
    assert len(runners) == len(contracts)
    source_functions = set()
    for runner in runners:
        source = ast.literal_eval(runner.args[0])
        call = runner.args[1].body
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        contract = contracts.pop(source)
        source_functions.add(call.func.id)
        assert contract.entry_point.split(":")[1] == call.func.id
        health = next((ast.literal_eval(kw.value) for kw in runner.keywords if kw.arg == "health_sources"), (source,))
        assert tuple(health) == contract.health_keys
        if call.func.id == "_process_cyclone_source":
            assert next(ast.literal_eval(kw.value) for kw in call.keywords if kw.arg == "source_key") == source
    assert not contracts
    serial_calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id.startswith("run_")
                    and node.func.id != "run_stage1_then_synthesis"}
    assert serial_calls == source_functions - {"_process_cyclone_source"}


def test_entry_points_exist_and_all_frozen_references_match_actual_code():
    document = registry_document(ROOT)
    for row in CONTRACTS:
        file, function = row.entry_point.split(":")
        assert any(isinstance(node, ast.FunctionDef) and node.name == function
                   for node in ast.parse((ROOT / file).read_text()).body)
    for path, digest in document["referenced_code_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    assert document == registry_document(ROOT)


def test_generated_dashboard_inventory_is_exact_current_python_inventory():
    saved = (ROOT / "dashboard/lib/source-registry.json").read_text()
    assert saved == json.dumps(registry_document(ROOT), ensure_ascii=False, indent=2) + "\n", (
        "Run scripts/gen_source_registry.py after reviewing changed source contracts"
    )


@pytest.mark.parametrize("change,code", [
    ({"source_id": "../source"}, "identity"),
    ({"health_keys": ("nhc",)}, "ambiguous_health_key"),
    ({"health_keys": ("budget",)}, "ambiguous_health_key"),
    ({"health_keys": ()}, "health_keys"),
    ({"data_family": "certified_global_truth"}, "family"),
    ({"scope": "hidden\nclaim"}, "text"),
    ({"entry_point": "src/other.py:fake"}, "entry_point"),
    ({"evidence_files": ("src/../secrets.py",)}, "evidence"),
])
def test_ambiguous_or_unsafe_metadata_refuses(change, code):
    changed = (replace(CONTRACTS[0], **change), *CONTRACTS[1:])
    with pytest.raises(ValueError, match=f"source_registry_{code}"):
        validate_contracts(changed)


def test_registry_is_not_a_scientific_access_rights_or_opportunity_grant():
    document = registry_document(ROOT)
    assert document["claim_permission_granted"] is False
    assert document["current_availability"] == "unverified"
    assert document["coverage_denominator"] is None
    assert document["provider_quota"] is None and document["reuse_rights"] is None
    keys = [key for row in CONTRACTS for key in row.health_keys]
    assert len(set(keys)) == len(keys)
    assert not set(keys).intersection(TELEMETRY_KEYS)
    rows = {row.source_id: row for row in CONTRACTS}
    assert rows["air_quality"].data_family == "mixed"
    assert rows["river_gauges"].data_family == "mixed"
    assert rows["ocean"].data_family == "forecast_model"
    assert rows["synthesis_fire_drought_heat"].kind == "derived"
    assert rows["newsworthiness"].kind == "discovery"


def test_metadata_can_be_loaded_with_all_network_client_imports_forbidden():
    code = '''
import builtins, socket
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'requests','httpx','anthropic','google','boto3'}:
        raise AssertionError('Client import: ' + name)
    if name.startswith('src.orchestrator'):
        raise AssertionError('Adapter execution: ' + name)
    return original(name, *args, **kwargs)
def network(*args, **kwargs): raise AssertionError('Network forbidden')
builtins.__import__ = guarded
socket.socket = network
from src.data.source_registry import registry_document
from pathlib import Path
assert registry_document(Path.cwd())['claim_permission_granted'] is False
'''
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, timeout=10)
