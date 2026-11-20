"""Invented HDF5 metadata through the actual existing grid parser, no network."""
from copy import deepcopy
from datetime import timedelta
import io

from freezegun import freeze_time
import h5py
import numpy as np
import pytest

from src.data import gpm_imerg as gpm, rainfall_grid as contract
from tests.test_rainfall_grid_pipeline import NOW, PEAK_LAT, PEAK_LON, nasa_frame


def changed(change, *, payload=None):
    buffer = io.BytesIO(nasa_frame() if payload is None else payload)
    with h5py.File(buffer, "r+") as handle:
        change(handle)
    return buffer.getvalue()


def scanned(payload, *, day=None, product="late", now=NOW):
    result: dict = {}
    with freeze_time(now):
        gpm._subset_grid(payload, [], resolved_date=day or (NOW - timedelta(days=1)).date(),
                         product=product, discovery_out=result)
    return result


def test_actual_parser_scans_only_supported_inland_tiles_with_exact_partition():
    raw = nasa_frame()
    result = scanned(raw)
    assert result["status"] == "qualified"
    evidence, = result["rows"]
    assert contract.validate_evidence(evidence, now=NOW) == evidence
    counts = result["diagnostics"]
    assert counts["tiles_examined"] == 6127 and counts["cells_examined"] == 612700
    assert counts["cartographic_regions"] == 77
    assert counts["qualifying_cells"] == counts["qualifying_tiles"] == 1
    assert sum(counts[key] for key in ("incomplete_cells", "invalid_value_cells", "outside_range_cells",
                                      "qualifying_cells")) == counts["cells_examined"]


@pytest.mark.parametrize("count,amount,category", [
    (47, 190.5, "incomplete_cells"), (-1, 190.5, "incomplete_cells"),
    (49, 190.5, "incomplete_cells"), (48, float("nan"), "invalid_value_cells"),
    (48, float("inf"), "invalid_value_cells"), (48, -1, "invalid_value_cells"),
    (48, 149.9, "outside_range_cells"), (48, 1000.1, "outside_range_cells"),
])
def test_unqualified_cells_are_counted_as_exclusions_never_zero_or_nominees(count, amount, category):
    result = scanned(nasa_frame(count=count, amount=amount))
    assert result["status"] == "qualified" and result["rows"] == []
    assert result["diagnostics"][category] > 0


@pytest.mark.parametrize("amount", [150, 1000])
def test_declared_operating_edges_are_inclusive_not_records(amount):
    result = scanned(nasa_frame(amount=amount))
    assert result["rows"][0]["mm_per_day"] == amount


@pytest.mark.parametrize("change", [
    lambda h: h.__delitem__("precipitation_cnt"),
    lambda h: h["precipitation"].attrs.__delitem__("units"),
    lambda h: h["precipitation"].attrs.__setitem__("units", "mm/hour"),
    lambda h: h["lon"].__setitem__(0, -179.9),
    lambda h: h["lon"].attrs.__setitem__("units", "radians"),
    lambda h: h["lat"].attrs.__delitem__("units"),
    lambda h: h["precipitation"].attrs.__setitem__("scale_factor", .1),
    lambda h: h["precipitation"].attrs.__setitem__("add_offset", 1),
    lambda h: h["precipitation"].attrs.__setitem__("scale_factor", "1"),
    lambda h: h["precipitation"].attrs.__setitem__("_FillValue", [190.5, 190.5]),
    lambda h: h["lat"].__setitem__(800, float("nan")),
    lambda h: h["time"].attrs.__setitem__("calendar", "360_day"),
    lambda h: h["time"].attrs.__setitem__("units", "seconds since someday"),
    lambda h: h["time"].__setitem__(0, NOW.timestamp()),
    lambda h: h["time"].__setitem__(0, float("inf")),
    lambda h: h.copy("precipitation", h.require_group("Grid")),
])
def test_missing_mixed_or_changed_source_metadata_holds_without_fabricating_proof(change):
    result = scanned(changed(change))
    assert result["status"] == "held" and result["rows"] == []


def test_float_counts_cannot_round_or_masquerade_as_complete_slots():
    def replace(handle):
        del handle["precipitation_cnt"]
        handle.create_dataset("precipitation_cnt", shape=(1, 3600, 1800), dtype="f4", fillvalue=48)
    assert scanned(changed(replace))["status"] == "held"


@pytest.mark.parametrize("dataset,value,category", [("precipitation", 190.5, "invalid_value_cells"),
                                                   ("precipitation_cnt", 48, "incomplete_cells")])
def test_numeric_missing_sentinels_never_become_valid_values(dataset, value, category):
    result = scanned(changed(lambda h: h[dataset].attrs.__setitem__("_FillValue", value)))
    assert result["rows"] == [] and result["diagnostics"][category] > 0


@pytest.mark.parametrize("product,offset", [("final", 0), ("late", -18), ("late", 20)])
def test_wrong_product_future_and_expired_frames_cannot_supply_new_reports(product, offset):
    result = scanned(nasa_frame(), product=product, now=NOW + timedelta(hours=offset))
    assert result["status"] == "held" and result["rows"] == []


def test_equal_values_choose_lowest_cell_index_independent_of_table_order(monkeypatch):
    def second(handle):
        handle["precipitation"][0, 1298, 799] = 190.5
    payload = changed(second)
    first = scanned(payload)
    assert first["rows"][0]["column"] == 1298
    table, names = contract.geography()
    monkeypatch.setattr(contract, "geography", lambda: (dict(reversed(list(table.items()))), deepcopy(names)))
    assert scanned(payload) == first


def test_a_coastal_or_outside_mask_peak_cannot_get_a_nearest_country_label():
    def ocean(handle):
        handle["precipitation"][0, gpm._lon_index(PEAK_LON), gpm._lat_index(PEAK_LAT)] = 0
        handle["precipitation"][0, gpm._lon_index(-30), gpm._lat_index(0)] = 500
    assert scanned(changed(ocean))["rows"] == []


def test_count_shape_checked_before_any_count_materialization():
    def replace(handle):
        del handle["precipitation_cnt"]
        handle.create_dataset("precipitation_cnt", shape=(1, 3600, 1801), dtype="i1", fillvalue=48)
    assert scanned(changed(replace))["status"] == "held"


def test_wrong_precipitation_shape_refuses_before_allocating_huge_sparse_input():
    def replace(handle):
        del handle["precipitation"]
        handle.create_dataset("precipitation", shape=(1, 10**9, 1800), dtype="f4", chunks=(1, 1, 1))
    with pytest.raises(gpm._GridParseError, match="shape"):
        scanned(changed(replace))


def test_explicit_file_bound_applies_without_reinterpreting_city_schema(monkeypatch):
    from src.data import rainfall_grid_scan
    payload = nasa_frame()
    monkeypatch.setattr(rainfall_grid_scan, "MAX_FILE_BYTES", len(payload) - 1)
    assert scanned(payload)["status"] == "held"


def test_external_or_soft_precipitation_link_is_refused_before_reading_target(tmp_path):
    missing = tmp_path / "never-created.h5"
    def external(handle):
        del handle["precipitation"]
        handle["precipitation"] = h5py.ExternalLink(str(missing), "precipitation")
    with pytest.raises(gpm._GridParseError, match="linked"):
        scanned(changed(external))
    assert not missing.exists()


def test_pure_source_time_accepts_only_documented_gregorian_cf_origin():
    def hours(handle):
        handle["time"].attrs["units"] = "hours since 2000-01-01 00:00:00 UTC"
        from datetime import UTC, datetime
        start = NOW.replace(hour=0) - timedelta(days=1)
        handle["time"][0] = (start - datetime(2000, 1, 1, tzinfo=UTC)).total_seconds() / 3600
    assert scanned(changed(hours))["rows"][0]["source_date"] == "2026-11-15"
