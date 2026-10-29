"""Collection metadata only: preserve coverage while balancing existing workers."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import _CI_LOCAL_MEDIA_MODULES, pytest_collection_modifyitems

ROOT = Path(__file__).resolve().parents[1]
MOVED = (
    "test_retained_temperature_calculation.py", "test_parked_media_inspection.py",
    "test_media_replay_reuse.py", "test_media_review_pair.py",
)


def select(items, group):
    kept, removed = list(items), []
    config = SimpleNamespace(
        getoption=lambda name: {"--ci-partition": group, "--ci-postgres-shard": "all",
                                "--ci-critical-first": False}[name],
        hook=SimpleNamespace(pytest_deselected=lambda items: removed.extend(items)),
    )
    pytest_collection_modifyitems(config, kept)
    assert {id(x) for x in kept}.isdisjoint(id(x) for x in removed)
    assert {id(x) for x in kept + removed} == {id(x) for x in items}
    return kept


def test_transfer_set_is_exactly_the_four_measured_whole_modules():
    assert _CI_LOCAL_MEDIA_MODULES == {ROOT / "tests" / name for name in MOVED}


@pytest.mark.parametrize("name", MOVED)
def test_actual_selector_moves_every_parameter_only_for_the_owned_module(name):
    original = [SimpleNamespace(path=ROOT / "tests" / name, nodeid=f"{name}::case[{i}]") for i in range(3)]
    assert select(original, "media") == original
    assert select(original, "core") == select(original, "postgres") == []
    assert select(original, "all") == original
    foreign = [SimpleNamespace(path=ROOT / "tests/nested" / name, nodeid="foreign")]
    assert select(foreign, "core") == foreign
    assert select(foreign, "media") == []


def test_original_media_postgres_and_core_rules_and_relative_order_remain():
    items = [SimpleNamespace(path=ROOT / "tests" / name, nodeid=name) for name in (
        "test_postgres_media_commands.py", "test_viirs_native_package.py",
        "test_postgres_preview_command_ingress.py", "test_ci_media_balance.py",
        *MOVED, "test_retained_reader_decoding.py",
    )]
    assert select(items, "media") == [items[0], items[1], *items[4:8]]
    assert select(items, "postgres") == [items[2]]
    assert select(items, "core") == [items[3], items[8]]
    assert select(items, "all") == items
