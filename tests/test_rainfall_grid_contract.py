"""Pure new-cell qualification and package-data identity, without source access."""
from copy import deepcopy
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from src.data import rainfall_grid as grid
from tests.test_rainfall_observed_report import NOW


@pytest.fixture
def evidence():
    return {"schema": grid.SCHEMA, "source_url": grid.SOURCE_URL, "source_product": "late",
            "product_version": "V07C", "source_date": "2026-11-15",
            "source_time_utc": "2026-11-15T00:00:00Z", "source_units": "mm/day",
            "column": 1299, "row": 799, "mm_per_day": 190.5, "valid_half_hours": 48,
            "source_file_sha256": "1" * 64, "geography_sha256": grid.TABLE_SHA256}


def test_one_cell_bundle_binds_source_day_scope_and_uninvented_retrieval_time(evidence):
    bundle = grid.build_bundle(evidence, now=NOW)
    assert grid.validate_bundle(bundle, now=NOW) == evidence
    assert bundle.country == "BR" and bundle.where.startswith("Brazil: satellite grid cell")
    assert bundle.when == "2026-11-16T00:00:00Z"
    assert bundle.raw_signal_dump["rainfall_window"]["footprint"]["center"] == [-10.05, -50.05]
    assert bundle.raw_signal_dump["rainfall_window"]["retrieved_at_known"] is False
    assert len(json.dumps(bundle.to_dict()).encode()) < 32768


@pytest.mark.parametrize("field,value", [
    ("schema", "foreign"), ("source_url", "https://invalid.test/"), ("source_product", "final"),
    ("product_version", "V06"), ("source_units", "mm/hr"), ("source_units", "mm"),
    ("geography_sha256", "0" * 64), ("source_file_sha256", "bad"),
    ("mm_per_day", True), ("mm_per_day", float("nan")), ("mm_per_day", float("inf")),
    ("mm_per_day", 10**400), ("mm_per_day", 149.99), ("mm_per_day", 1000.01),
    ("valid_half_hours", None), ("valid_half_hours", True), ("valid_half_hours", 47),
    ("valid_half_hours", 49), ("valid_half_hours", 48.0),
    ("column", True), ("column", -1), ("row", 1800), ("column", 1299.0),
    ("source_date", "2026-11-14"), ("source_date", "2026-11-15T00:00:00Z"),
    ("source_time_utc", "2026-11-14T00:00:00Z"), ("source_time_utc", "2026-11-15T00:00:00"),
    ("source_time_utc", "2026-11-15T00:00:00+01:00"), ("source_time_utc", None),
])
def test_unqualified_source_fields_refuse_without_coercion(evidence, field, value):
    evidence[field] = value
    with pytest.raises(grid.GridHeld):
        grid.build_bundle(evidence, now=NOW)


@pytest.mark.parametrize("column,row", [(0, 0), (1799, 899), (0, 900), (3599, 900)])
def test_ocean_polar_border_or_unqualified_cells_do_not_get_a_nearest_city_label(evidence, column, row):
    evidence.update(column=column, row=row)
    with pytest.raises(grid.GridHeld, match="rainfall_grid_region_unqualified"):
        grid.build_bundle(evidence, now=NOW)


def test_missing_or_unknown_evidence_fields_never_repair_into_a_packet(evidence):
    original = deepcopy(evidence)
    evidence.pop("valid_half_hours")
    with pytest.raises(grid.GridHeld):
        grid.validate_evidence(evidence, now=NOW)
    original["trusted"] = True
    with pytest.raises(grid.GridHeld):
        grid.validate_evidence(original, now=NOW)


def test_exact_freshness_edge_and_future_window(evidence):
    end = NOW.replace(hour=0)
    assert grid.validate_evidence(evidence, now=end + timedelta(hours=36)) == evidence
    for at in [end - timedelta(microseconds=1), end + timedelta(hours=36, microseconds=1)]:
        with pytest.raises(grid.GridHeld, match="rainfall_completed_window_expired"):
            grid.validate_evidence(evidence, now=at)


@pytest.mark.parametrize("field,value", [("country", "FR"), ("where", "Paris"),
                                      ("when", "2026-11-16T01:00:00Z"), ("event_id", "foreign"),
                                      ("signal_kind", "record")])
def test_every_bundle_declaration_is_recomputed(evidence, field, value):
    payload = grid.build_bundle(evidence, now=NOW).to_dict()
    payload[field] = value
    with pytest.raises(grid.GridHeld, match="rainfall_bundle_changed"):
        grid.validate_bundle(payload, now=NOW)


def test_boolean_cannot_equal_numeric_footprint_metadata(evidence):
    payload = grid.build_bundle(evidence, now=NOW).to_dict()
    payload["raw_signal_dump"]["rainfall_window"]["footprint"]["members"] = True
    with pytest.raises(grid.GridHeld, match="rainfall_bundle_changed"):
        grid.validate_bundle(payload, now=NOW)


def test_actual_javascript_numeric_roundtrip_keeps_the_same_source_claim(evidence):
    evidence["mm_per_day"] = 190.0
    payload = grid.build_bundle(evidence, now=NOW).to_dict()
    node = shutil.which("node")
    assert node is not None, "Node is required for actual Python/JavaScript wire verification"
    result = subprocess.run([node, "-e", "let v='';process.stdin.on('data',x=>v+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(v))));"],
                            input=json.dumps(payload), capture_output=True, text=True, check=True, timeout=10)
    returned = json.loads(result.stdout)
    assert type(returned["headline_metric"]["value"]) is int
    assert grid.validate_bundle(returned, now=NOW) == evidence


def embedded(monkeypatch, tmp_path):
    root = tmp_path / "package"
    asset = root / "registry/geography/imerg_country_tiles_v1.json"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(grid._table_bytes())
    monkeypatch.setattr(grid, "files", lambda package: root)
    return asset


def test_a_pure_cache_hit_cannot_mask_later_package_tampering(evidence, monkeypatch, tmp_path):
    asset = embedded(monkeypatch, tmp_path)
    grid.validate_evidence(evidence, now=NOW)
    data = asset.read_bytes()
    assert b'"BR"' in data
    asset.write_bytes(data.replace(b'"BR"', b'"FR"', 1))
    with pytest.raises(grid.GridHeld, match="rainfall_grid_geography_identity_changed"):
        grid.validate_evidence(evidence, now=NOW)


@pytest.mark.parametrize("kind", ["missing", "directory", "symlink", "fifo", "oversize"])
def test_bad_embedded_asset_never_falls_back_to_valid_host_data(evidence, monkeypatch, tmp_path, kind):
    asset = embedded(monkeypatch, tmp_path)
    if kind == "oversize":
        asset.write_bytes(asset.read_bytes() + b" ")
    else:
        asset.unlink()
        if kind == "directory":
            asset.mkdir()
        elif kind == "symlink":
            target = tmp_path / "same-content"
            target.write_bytes((Path(__file__).resolve().parents[1] / "data/geography/imerg_country_tiles_v1.json").read_bytes())
            asset.symlink_to(target)
        elif kind == "fifo":
            os.mkfifo(asset)
    with pytest.raises(grid.GridHeld):
        grid.validate_evidence(evidence, now=NOW)


def test_callers_cannot_mutate_cached_tile_or_label_authority():
    from collections.abc import MutableMapping
    from typing import cast

    table, names = grid.geography()
    with pytest.raises(TypeError):
        cast(MutableMapping, table)[129, 79] = "FR"
    names["BR"] = "Fake place"
    assert grid.region(1299, 799) == ("BR", "Brazil")
