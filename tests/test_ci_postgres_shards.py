"""Deterministic collection boundaries; no database or application execution."""
import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.conftest import _CI_CRITICAL_NODEIDS, _ci_postgres_shard, pytest_collection_modifyitems

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
    critical = [SimpleNamespace(path=ROOT / nodeid.split("::")[0], nodeid=nodeid)
                for nodeid in _CI_CRITICAL_NODEIDS]
    six = SimpleNamespace(path=ordinary[0].path, nodeid="tests/test_postgres_temperature_editor_media.py::test_six_compact_claims_reach_actual_native_editor_preparation[six_variants]")
    items = [ordinary[0], six, *reversed(critical), ordinary[1]]
    for shard in ("all", *(str(i) for i in range(9))):
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


def test_nine_file_shards_partition_all_modules_and_parameters_without_changing_legacy_groups(monkeypatch, tmp_path):
    files = sorted((ROOT / "tests").glob("test_postgres_*.py"))
    items = [SimpleNamespace(path=path, nodeid=f"{path.name}::invented[{parameter}]")
             for path in [ROOT / "tests/test_ci_postgres_shards.py", *files] for parameter in ("a", "b", "c")]
    postgres = select(items, "postgres")
    shards = [select(items, "postgres", str(index)) for index in range(9)]
    identities = [{id(item) for item in shard} for shard in shards]
    assert all(identities) and set.union(*identities) == {id(item) for item in postgres}
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
                "tests/test_postgres_temperature_delivery.py": 3,
                "tests/test_postgres_editor_media.py": 5,
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
    assert any(item.path.name == "test_postgres_temperature_delivery.py" for item in shards[3])
    assert any(item.path.name == "test_postgres_editor_media.py" for item in shards[5])
    assert not any(item.path.name == "test_postgres_editor_media.py" for item in shards[3])
    legacy = [select(items, partition) for partition in ("core", "postgres", "media")]
    assert sorted(id(item) for group in legacy for item in group) == sorted(id(item) for item in select(items, "all"))
    original = [_ci_postgres_shard(path) for path in files]
    monkeypatch.chdir(tmp_path)
    assert [_ci_postgres_shard(path) for path in files] == original


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
                                            ("postgres","9"), ("postgres","-1"), ("postgres","invalid")])
def test_invalid_shard_requests_fail_before_collection(partition, shard):
    result = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "--collect-only", "-q",
        "-p", "no:cacheprovider", f"--ci-partition={partition}", f"--ci-postgres-shard={shard}"],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 4
    assert "--ci-postgres-shard" in result.stderr
    assert "tests collected" not in result.stdout


def test_ninth_postgres_shard_is_accepted_by_actual_collection_cli():
    result = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "--collect-only", "-q",
        "-p", "no:cacheprovider", "--ci-partition=postgres", "--ci-postgres-shard=8"],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    # This core test module is intentionally deselected; argument parsing succeeds.
    assert result.returncode == 5
    assert "--ci-postgres-shard" not in result.stderr
