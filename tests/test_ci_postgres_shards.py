"""Deterministic collection boundaries; no database or application execution."""
import ast
import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from tests.conftest import _CI_CRITICAL_NODEIDS, _ci_postgres_shard, pytest_addoption, pytest_collection_modifyitems

ROOT = Path(__file__).resolve().parents[1]


def select(items, partition, shard="all", critical_first=False):
    kept, removed = list(items), []
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition":partition, "--ci-postgres-shard":shard,
                                "--ci-critical-first": critical_first}[name],
        hook=SimpleNamespace(pytest_deselected=lambda items: removed.extend(items)),
    )
    pytest_collection_modifyitems(config, kept)
    assert {id(item) for item in kept}.isdisjoint(id(item) for item in removed)
    assert {id(item) for item in kept + removed} == {id(item) for item in items}
    return kept


def test_critical_order_preserves_each_shard_membership_and_all_other_relative_order():
    ordinary = [SimpleNamespace(path=ROOT / "tests/test_postgres_temperature_editor_media.py",
                               nodeid="tests/test_postgres_temperature_editor_media.py::ordinary[" + p + "]")
                for p in ("a", "b")]
    critical = [SimpleNamespace(path=ROOT / nodeid.split("::")[0], nodeid=nodeid,
                                originalname=nodeid.split("::", 1)[1].split("[", 1)[0])
                for nodeid in _CI_CRITICAL_NODEIDS]
    six = SimpleNamespace(path=ordinary[0].path, nodeid="tests/test_postgres_temperature_editor_media.py::test_six_compact_claims_reach_actual_native_editor_preparation[six_variants]")
    items = [ordinary[0], six, *reversed(critical), ordinary[1]]
    for shard in ("all", *(str(i) for i in range(12))):
        before = select(items, "postgres", shard)
        after = select(items, "postgres", shard, critical_first=True)
        assert sorted(map(id, after)) == sorted(map(id, before))
        promoted = [nodeid for nodeid in _CI_CRITICAL_NODEIDS if any(item.nodeid == nodeid for item in before)]
        assert [item.nodeid for item in after[:len(promoted)]] == promoted
        assert [item for item in after if item.nodeid not in _CI_CRITICAL_NODEIDS] == [
            item for item in before if item.nodeid not in _CI_CRITICAL_NODEIDS]
    assert select(items, "postgres") == items
    assert select(items, "all", critical_first=True) == items
    for partition in ("core", "media"):
        assert select(items, partition, critical_first=True) == select(items, partition)


@pytest.mark.parametrize("passing", [False, True])
def test_actual_pytest_maxfail_keeps_failures_nonzero_and_all_passing_tests(tmp_path, passing):
    module = tmp_path / "test_feedback.py"
    module.write_text("def test_first():\n    assert " + str(passing)
                      + "\n\ndef test_second():\n    assert True\n")
    result = subprocess.run([sys.executable, "-m", "pytest", str(module), "-q", "--maxfail=1",
                             "-p", "no:cacheprovider"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == (0 if passing else 1)
    assert ("2 passed" if passing else "1 failed") in result.stdout
    if not passing:
        assert "stopping after 1 failures" in result.stdout and "1 passed" not in result.stdout


def test_expanded_file_shards_partition_all_modules_and_parameters_without_changing_legacy_groups(monkeypatch, tmp_path):
    files = sorted((ROOT / "tests").glob("test_postgres_*.py"))
    items = [SimpleNamespace(path=path, nodeid=f"{path.name}::invented[{parameter}]")
             for path in [ROOT / "tests/test_ci_postgres_shards.py", *files] for parameter in ("a", "b", "c")]
    postgres = select(items, "postgres")
    shards = [select(items, "postgres", str(index)) for index in range(12)]
    identities = [{id(item) for item in shard} for shard in shards]
    # Whole-file fixtures populate original0..8 and new11; the function-cohort
    # test below independently covers new9/10 with actual test metadata.
    assert {i for i, ids in enumerate(identities) if ids} == {*range(9), 11}
    assert set.union(*identities) == {id(item) for item in postgres}
    for index, shard in enumerate(shards):
        assert all(identities[index].isdisjoint(other) for other in identities[index+1:])
        for path in {item.path for item in shard}:
            assert sum(item.path == path for item in shard) == 3
            relative = path.relative_to(ROOT).as_posix()
            assigned = {
                "tests/test_postgres_published_media.py": 2,
                "tests/test_postgres_cost_projection.py": 5,
                "tests/test_postgres_important_native.py": 1,
                "tests/test_postgres_ghcn_generation.py": 5,
                "tests/test_postgres_platform_description.py": 6,
                "tests/test_postgres_temperature_editor_media.py": 8,
                "tests/test_postgres_temperature_delivery.py": 0,
                "tests/test_postgres_editor_media.py": 11,
            }
            if relative in assigned:
                assert index == assigned[relative]
            else:
                assert int(hashlib.sha256(relative.encode()).hexdigest(), 16) % 8 == index
    assert any(item.path.name == "test_postgres_published_media.py" for item in shards[2])
    assert any(item.path.name == "test_postgres_cost_projection.py" for item in shards[5])
    assert any(item.path.name == "test_postgres_important_native.py" for item in shards[1])
    assert any(item.path.name == "test_postgres_ghcn_generation.py" for item in shards[5])
    assert any(item.path.name == "test_postgres_platform_description.py" for item in shards[6])
    assert {item.path.name for item in shards[8]} == {"test_postgres_temperature_editor_media.py"}
    assert any(item.path.name == "test_postgres_temperature_delivery.py" for item in shards[0])
    assert {item.path.name for item in shards[11]} == {"test_postgres_editor_media.py"}
    assert not any(item.path.name == "test_postgres_editor_media.py" for item in shards[5])
    legacy = [select(items, partition) for partition in ("core", "postgres", "media")]
    assert sorted(id(item) for group in legacy for item in group) == sorted(id(item) for item in select(items, "all"))
    original = [_ci_postgres_shard(path) for path in files]
    monkeypatch.chdir(tmp_path)
    assert [_ci_postgres_shard(path) for path in files] == original


def test_stage_function_defaults_partition_cases_without_explicit_fault_metadata():
    path = ROOT / "tests/test_postgres_stage_revision_checks.py"
    # Frozen defaults keep complete functions together. Actual GHCN final-fault
    # metadata has its separate explicit pair-cohort test below.
    cohorts = {
        "0": (
            "test_same_owner_initial_cap_race_and_unused_cap_cannot_renew",
            "test_v2_nonpass_raw_is_terminal_and_cannot_rotate_or_resend",
            "test_v2_prefix_missing_corrupt_and_late_evidence_never_grants_readiness",
        ),
        "1": (
            "test_predecessor_expiring_during_real_prefix_work_rolls_back_successor",
            "test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes",
            "test_v2_strict_request_window_equality_and_one_microsecond",
        ),
        "2": (
            "test_catalog4_never_adopts_unused_legacy_semantic_enrollment",
            "test_v2_exact_reservation_request_and_stage_are_required_before_dispatch",
            "test_v2_restored_unattempted_cap_must_bind_the_exact_verified_predecessor",
        ),
        "3": (
            "test_actual_protocol2_seal_removed_between_begin_passes_rolls_back_before_attempt",
            "test_v2_exact_terminal_replay_is_history_and_cannot_reseal_corruption",
            "test_v2_outbox_tail_uses_original_critic_deadline_and_rolls_back_park",
            "test_v2_scope_is_connection_bound_and_untrusted_inputs_cannot_mint_cap",
        ),
        "4": (
            "test_catalog4_owner_atomic_idempotent_legacy_receipts_and_runtime_denial",
            "test_v2_completion_delay_rolls_back_critic_receipt_seal_keeps_raw_and_unknown_cost",
            "test_v2_full_park_restore_keeps_legacy_sets_and_exact_protocol_chain",
            "test_v2_genuine_park_one_use_delivery_and_passive_original_cap_cost",
        ),
        "5": (
            "test_catalog4_receipt_nested_numeric_metadata_is_byte_exact",
            "test_catalog4_tamper_fails_closed_without_repair",
            "test_v2_explicit_sdk_original_raw_recovery_has_no_second_request",
            "test_v2_published_frame_minimum_bounds_every_cap_and_final_readiness",
        ),
        "6": (
            "test_catalog4_every_installation_boundary_rolls_back",
            "test_genuine_v2_chain_exceeds_first_cap_and_generic_status_never_certifies",
            "test_v2_current_authority_drift_cannot_create_successor",
            "test_v2_first_cap_issuance_uses_postproof_clock_and_reuse_never_refreshes_it",
        ),
        "7": (
            "test_catalog4_concurrent_owner_install_retains_single_chain",
            "test_frozen_previous_binary_refuses_catalog4_before_work",
            "test_same_owner_successor_cap_race_cannot_rotate_without_attempt",
        ),
        "8": (
        ),
        "9": (
            "test_v2_modis_approval_final_bound_and_reauthorization_roll_back_all_writes",
        ),
        "10": (
            "test_v2_transaction_interruptions_never_repurchase_or_repair_missing_seal",
        ),
        "11": (
        ),
    }
    expected = {name: shard for shard, names in cohorts.items() for name in names}
    functions = [node.name for node in ast.parse(path.read_text()).body
                 if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    assert len(expected) == len(functions) == 30 and set(expected) == set(functions)
    items = [SimpleNamespace(path=path, originalname=name, nodeid=f"{path.relative_to(ROOT)}::{name}[{parameter}]")
             for parameter in ("modis", "ghcn", "fault-with-brackets[and spaces]") for name in functions]
    seen = set()
    for shard in map(str, range(12)):
        for critical_first in (False, True):
            kept = select(items, "postgres", shard, critical_first)
            expected_items = [item for item in items if expected[item.originalname] == shard]
            if critical_first:
                expected_items = [item for nodeid in _CI_CRITICAL_NODEIDS for item in expected_items
                                  if item.nodeid == nodeid] + [
                    item for item in expected_items if item.nodeid not in _CI_CRITICAL_NODEIDS]
            assert kept == expected_items
        assert seen.isdisjoint(map(id, kept))
        seen.update(map(id, kept))
    assert seen == {id(item) for item in items}
    assert select(items, "postgres") == items
    assert select(items, "all", critical_first=True) == items
    assert select(items, "core") == select(items, "media") == []


def test_stage_function_routes_do_not_leak_to_other_modules_or_guess_unknown_names():
    stage = ROOT / "tests/test_postgres_stage_revision_checks.py"
    foreign = ROOT / "tests/test_postgres_temperature_delivery.py"
    name = "test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes"
    assert _ci_postgres_shard(stage, name) == "1"
    assert _ci_postgres_shard(foreign, name) == _ci_postgres_shard(foreign) == "0"
    for unknown in (None, "test_future_stage_case", name + "[injected]"):
        assert _ci_postgres_shard(stage, unknown) == _ci_postgres_shard(stage) == "3"


def test_viirs_native_package_runs_only_in_required_media_lane_with_complete_union():
    names = ("test_viirs_native_package.py", "test_viirs_saved_preview.py", "test_postgres_authority.py")
    items = [SimpleNamespace(path=ROOT / "tests" / name, nodeid=f"{name}::invented[{i}]")
             for name in names for i in (0, 1)]
    groups = {partition: select(items, partition) for partition in ("core", "postgres", "media")}
    assert {item.path.name for item in groups["media"]} == {"test_viirs_native_package.py"}
    assert {item.path.name for item in groups["core"]} == {"test_viirs_saved_preview.py"}
    assert {item.path.name for item in groups["postgres"]} == {"test_postgres_authority.py"}
    assert sorted(id(item) for group in groups.values() for item in group) == sorted(id(item) for item in items)


@pytest.mark.parametrize("partition,shard", [("all","0"), ("core","1"), ("media","3"),
                                            ("postgres","12"), ("postgres","-1"), ("postgres","invalid")])
def test_invalid_shard_requests_fail_before_collection(partition, shard):
    result = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "--collect-only", "-q",
        "-p", "no:cacheprovider", f"--ci-partition={partition}", f"--ci-postgres-shard={shard}"],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 4
    assert "--ci-postgres-shard" in result.stderr
    assert "tests collected" not in result.stdout


@pytest.mark.parametrize("shard", ["8", "9", "10", "11"])
def test_dedicated_postgres_shards_are_accepted_by_actual_collection_cli(shard):
    result = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "--collect-only", "-q",
        "-p", "no:cacheprovider", "--ci-partition=postgres", f"--ci-postgres-shard={shard}"],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    # This core test module is intentionally deselected; argument parsing succeeds.
    assert result.returncode == 5
    assert "--ci-postgres-shard" not in result.stderr


def test_actual_ghcn_fault_metadata_keeps_all_ten_cases_in_disjoint_fixed_pairs():
    path = ROOT / "tests/test_postgres_stage_revision_checks.py"
    name = "test_v2_ghcn_approval_final_bound_and_reauthorization_roll_back_all_writes"
    expected = {'expiry': '1', 'source': '1', 'editor': '7', 'publisher': '7', 'policy': '4'}
    items = [SimpleNamespace(path=path, originalname=name,
              callspec=SimpleNamespace(params=dict(fault=fault, boundary=boundary)),
              nodeid=f"tests/test_postgres_stage_revision_checks.py::{name}[{fault}-{boundary}-compact_case0]")
             for fault in expected for boundary in ("proof", "outbox")]
    assert len(items) == 10
    selected = []
    for shard in map(str, range(12)):
        before = select(items, "postgres", shard)
        after = select(items, "postgres", shard, critical_first=True)
        assert sorted(map(id, after)) == sorted(map(id, before))
        assert {item.nodeid for item in before} == {
            item.nodeid for item in items if expected[item.callspec.params["fault"]] == shard}
        selected.extend(before)
    assert len(selected) == len({id(item) for item in selected}) == 10
    assert set(map(id, selected)) == set(map(id, select(items, "postgres")))
    foreign = ROOT / "tests/test_postgres_temperature_delivery.py"
    assert _ci_postgres_shard(foreign, name, {"fault": "policy"}) == "0"
    assert _ci_postgres_shard(path, name, {"fault": "future_fault"}) == _ci_postgres_shard(path, name)


def test_targeted_priority_then_stage_family_preserve_membership_and_legacy_order():
    path = ROOT / "tests/test_postgres_stage_revision_checks.py"
    legacy = [SimpleNamespace(path=ROOT / "tests/test_postgres_command_authority.py", nodeid=f"legacy[{i}]")
              for i in range(2)]
    remaining = [SimpleNamespace(path=path, originalname="test_future_stage_case", nodeid=f"remaining[{i}]")
                 for i in range(2)]
    critical = SimpleNamespace(path=path, nodeid=_CI_CRITICAL_NODEIDS[0])
    items = [legacy[0], remaining[0], critical, legacy[1], remaining[1]]
    assert select(items, "postgres") == items
    assert select(items, "all", critical_first=True) == items
    assert select(items, "postgres", critical_first=True) == [critical, *remaining, *legacy]


def test_all_fourteen_workflow_groups_have_matching_parser_choices_and_original_limits():
    options = {}
    pytest_addoption(SimpleNamespace(addoption=lambda name, **kw: options.update({name: kw})))
    workflow = yaml.load((ROOT / ".github/workflows/bot.yml").read_text(), Loader=yaml.BaseLoader)
    job = workflow["jobs"]["test-partition"]
    groups = [(r["partition"], r["postgres-shard"]) for r in job["strategy"]["matrix"]["include"]]
    expected = [("core", "all"), ("media", "all"), *(("postgres", str(i)) for i in range(12))]
    assert groups == expected and len(set(groups)) == 14
    assert options["--ci-postgres-shard"]["choices"] == ("all", *(str(i) for i in range(12)))
    assert job["timeout-minutes"] == "35" and job["strategy"]["fail-fast"] == "false"
