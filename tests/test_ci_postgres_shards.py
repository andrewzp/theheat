"""Deterministic collection boundaries; no database or application execution."""
import hashlib
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.conftest import _ci_postgres_shard, pytest_collection_modifyitems

ROOT = Path(__file__).resolve().parents[1]


def select(items, partition, shard="all"):
    kept, removed = list(items), []
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition":partition, "--ci-postgres-shard":shard}[name],
        hook=SimpleNamespace(pytest_deselected=lambda items: removed.extend(items)),
    )
    pytest_collection_modifyitems(config, kept)
    assert {id(item) for item in kept}.isdisjoint(id(item) for item in removed)
    assert {id(item) for item in kept + removed} == {id(item) for item in items}
    return kept


def test_four_file_shards_partition_all_modules_and_parameters_without_changing_legacy_groups(monkeypatch, tmp_path):
    files = sorted((ROOT / "tests").glob("test_postgres_*.py"))
    items = [SimpleNamespace(path=path, nodeid=f"{path.name}::invented[{parameter}]")
             for path in [ROOT / "tests/test_ci_postgres_shards.py", *files] for parameter in ("a", "b", "c")]
    postgres = select(items, "postgres")
    shards = [select(items, "postgres", str(index)) for index in range(4)]
    identities = [{id(item) for item in shard} for shard in shards]
    assert all(identities) and set.union(*identities) == {id(item) for item in postgres}
    for index, shard in enumerate(shards):
        assert all(identities[index].isdisjoint(other) for other in identities[index+1:])
        for path in {item.path for item in shard}:
            assert sum(item.path == path for item in shard) == 3
            relative = path.relative_to(ROOT).as_posix()
            assert int(hashlib.sha256(relative.encode()).hexdigest(), 16) % 4 == index
    legacy = [select(items, partition) for partition in ("core", "postgres", "media")]
    assert sorted(id(item) for group in legacy for item in group) == sorted(id(item) for item in select(items, "all"))
    original = [_ci_postgres_shard(path) for path in files]
    monkeypatch.chdir(tmp_path)
    assert [_ci_postgres_shard(path) for path in files] == original


@pytest.mark.parametrize("partition,shard", [("all","0"), ("core","1"), ("media","3"),
                                            ("postgres","4"), ("postgres","-1"), ("postgres","invalid")])
def test_invalid_shard_requests_fail_before_collection(partition, shard):
    result = subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "--collect-only", "-q",
        "-p", "no:cacheprovider", f"--ci-partition={partition}", f"--ci-postgres-shard={shard}"],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 4
    assert "--ci-postgres-shard" in result.stderr
    assert "tests collected" not in result.stdout
