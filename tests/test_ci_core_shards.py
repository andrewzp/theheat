"""Complete-module core cohorts; no application, database or source execution."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import pytest_addoption, pytest_collection_modifyitems, pytest_configure

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "test_awc_observed.py": "1", "test_rainfall_grid_scan.py": "0",
    "test_source_health_sentinel.py": "0", "test_gpm_imerg.py": "1",
}


def items():
    return [SimpleNamespace(path=ROOT / "tests" / name, nodeid=f"tests/{name}::invented[{case}]")
            for name in (*GROUPS, "test_postgres_stage_revision_checks.py", "test_postgres_media_commands.py")
            for case in ("a", "b")]


def select(rows, partition="core", shard="all"):
    kept, removed = list(rows), []
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition": partition, "--ci-postgres-shard": "all",
                                "--ci-core-shard": shard, "--ci-critical-first": False}[name],
        hook=SimpleNamespace(pytest_deselected=lambda items: removed.extend(items)),
    )
    pytest_collection_modifyitems(config, kept)
    assert {id(x) for x in kept}.isdisjoint(id(x) for x in removed)
    assert {id(x) for x in kept + removed} == {id(x) for x in rows}
    return kept


def test_actual_core_hook_has_disjoint_exhaustive_shards_and_keeps_each_module_whole():
    original = items()
    complete = select(original)
    zero, one = (select(original, shard=shard) for shard in ("0", "1"))
    assert zero and one
    assert {id(x) for x in zero}.isdisjoint(id(x) for x in one)
    assert {id(x) for x in zero + one} == {id(x) for x in complete}
    for shard, rows in (("0", zero), ("1", one)):
        assert rows == [x for x in original if GROUPS.get(x.path.name) == shard]


def test_core_membership_is_fixed_under_working_directory_and_input_permutation(tmp_path, monkeypatch):
    original = items()
    monkeypatch.chdir(tmp_path)
    for order in (original, list(reversed(original)), original[3:] + original[:3]):
        for shard in ("0", "1"):
            assert select(order, shard=shard) == [x for x in order if GROUPS.get(x.path.name) == shard]


def test_default_all_and_original_partition_boundaries_are_preserved():
    original = items()
    assert select(original, "all") == original
    complete = select(original)
    assert len(complete) == 2 * len(GROUPS)
    pg, media = select(original, "postgres"), select(original, "media")
    assert {id(x) for x in complete + pg + media} == {id(x) for x in original}
    assert len(complete) + len(pg) + len(media) == len(original)


@pytest.mark.parametrize("partition", ["all", "postgres", "media"])
def test_specific_core_shard_refuses_other_partitions_before_work(partition):
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition": partition, "--ci-postgres-shard": "all", "--ci-core-shard": "0"}[name],
        addinivalue_line=lambda *args: None,
    )
    with pytest.raises(pytest.UsageError, match="--ci-core-shard requires --ci-partition=core"):
        pytest_configure(config)


def test_core_parser_choices_have_no_fallback_or_default_shard_drop():
    options = {}
    pytest_addoption(SimpleNamespace(addoption=lambda name, **kw: options.update({name: kw})))
    assert options["--ci-core-shard"]["choices"] == ("all", "0", "1")
    assert options["--ci-core-shard"]["default"] == "all"
