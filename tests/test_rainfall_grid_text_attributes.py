"""Invented HDF5 scalar text through the existing collector and writer lane."""
from datetime import timedelta
from dataclasses import asdict
from hashlib import sha256
import io

import h5py
import numpy as np
import pytest

from src.data import rainfall_grid_scan as scan
from src.data import gpm_imerg as gpm
from tests.test_rainfall_grid_pipeline import (
    COPY, collect, enabled, gpm_public_url, grid_world, nasa_frame,
    ordinary_grid_world, send,
)  # noqa: F401 -- register the existing offline SDK/transport fixtures
from tests.test_rainfall_grid_scan import NOW, scanned


def encoded_frame(encoding, *, fields=None):
    buffer = io.BytesIO(nasa_frame())
    with h5py.File(buffer, "r+") as handle:
        for path, key in fields or [("precipitation", "units"), ("lon", "units"),
                                    ("lat", "units"), ("time", "units"), ("time", "calendar")]:
            value = handle[path].attrs[key]
            del handle[path].attrs[key]
            dtype = "S128" if encoding == "fixed" else h5py.string_dtype(encoding)
            handle[path].attrs[key] = np.array([value], dtype=dtype)
    return buffer.getvalue()


@pytest.mark.parametrize("encoding", ["fixed", "utf-8", "ascii"])
@pytest.mark.parametrize("field", [None, ("precipitation", "units"), ("lon", "units"),
                                   ("lat", "units"), ("time", "units"), ("time", "calendar")])
def test_equivalent_hdf5_scalar_arrays_keep_canonical_cell_and_counts(encoding, field):
    original = scanned(nasa_frame())
    raw = encoded_frame(encoding, fields=[field] if field else None)
    actual = scanned(raw)
    assert actual["status"] == "qualified", actual
    assert actual["diagnostics"] == original["diagnostics"]
    [before], [after] = original["rows"], actual["rows"]
    assert after["source_file_sha256"] == sha256(raw).hexdigest()
    assert {k: v for k, v in after.items() if k != "source_file_sha256"} == {
        k: v for k, v in before.items() if k != "source_file_sha256"}


@pytest.mark.parametrize("encoding", ["fixed", "utf-8", "ascii"])
def test_legacy_city_values_and_identities_stay_identical(encoding):
    city = next(row for row in gpm.load_cities() if row["city"] == "Paris" and row["country"] == "France")
    before = gpm._subset_grid(nasa_frame(), [city], resolved_date=(NOW - timedelta(days=1)).date(), product="late")
    after = gpm._subset_grid(encoded_frame(encoding), [city], resolved_date=(NOW - timedelta(days=1)).date(),
                             product="late")
    assert before and [asdict(row) for row in before] == [asdict(row) for row in after]


@pytest.mark.parametrize("value", [
    "mm/day", b"mm/day", np.bytes_(b"mm/day"), np.str_("mm/day"),
    np.array(b"mm/day", dtype="S8"), np.array([b"mm/day"], dtype="S128"),
    np.array(["mm/day"], dtype=h5py.string_dtype("utf-8")),
])
def test_scalar_text_decode_preserves_exact_value(value):
    assert scan._attribute(value) == "mm/day"


@pytest.mark.parametrize("value", [
    None, 1, np.array([1]), np.array([], dtype="S8"),
    np.array([b"mm/day", b"mm/day"], dtype="S8"),
    np.array([[b"mm/day"]], dtype="S8"),
    np.array(["mm/day"], dtype=object),
    np.array([b"mm/day"], dtype="S129"),
    "x" * 129, b"x" * 129, "mm/dáy", b"\xff", "mm/day\n", b"mm\x00/day",
    np.array([b"mm\x00/day"], dtype="S8"),
])
def test_ambiguous_nontext_unbounded_and_control_metadata_refuses(value):
    assert scan._attribute(value) is None


def test_custom_scalar_and_array_coercion_is_never_called():
    calls = []

    class Coercion:
        def __str__(self):
            calls.append("str")
            return "mm/day"

    class ByteSubclass(bytes):
        def decode(self, *args, **kwargs):
            calls.append("decode")
            return "mm/day"

    class ArraySubclass(np.ndarray):
        def item(self, *args):
            calls.append("item")
            return "mm/day"

    for value in (Coercion(), ByteSubclass(b"mm/day"), np.array([b"mm/day"]).view(ArraySubclass)):
        assert scan._attribute(value) is None
    assert calls == []


@pytest.mark.parametrize("encoding", ["fixed", "utf-8", "ascii"])
@pytest.mark.parametrize("value", ["mm/hour", "mm", "MM/DAY", " mm/day", "mm/day ", "unknown"])
def test_equivalent_encoding_never_guesses_or_normalizes_unknown_units(encoding, value):
    buffer = io.BytesIO(encoded_frame(encoding))
    with h5py.File(buffer, "r+") as handle:
        del handle["precipitation"].attrs["units"]
        dtype = "S128" if encoding == "fixed" else h5py.string_dtype(encoding)
        handle["precipitation"].attrs["units"] = np.array([value], dtype=dtype)
    result = scanned(buffer.getvalue())
    assert result["status"] == "held" and result["rows"] == []
    assert result["hold_code"] == "rainfall_grid_units_invalid"


@pytest.mark.parametrize("case,code", [("calendar", "rainfall_grid_time_invalid"),
                                      ("day", "rainfall_grid_time_invalid"),
                                      ("axis", "rainfall_grid_axes_invalid"),
                                      ("scale", "rainfall_grid_packed_data_unsupported"),
                                      ("partial", None)])
def test_decoded_units_never_waive_other_source_requirements(case, code):
    buffer = io.BytesIO(encoded_frame("utf-8"))
    with h5py.File(buffer, "r+") as handle:
        if case == "calendar":
            del handle["time"].attrs["calendar"]
            handle["time"].attrs["calendar"] = np.array(["360_day"], dtype=h5py.string_dtype("utf-8"))
        elif case == "day":
            handle["time"][0] = NOW.timestamp()
        elif case == "axis":
            del handle["lon"].attrs["units"]
            handle["lon"].attrs["units"] = np.array([b"radians"], dtype="S8")
        elif case == "scale":
            handle["precipitation"].attrs["scale_factor"] = 0.1
        else:
            handle["precipitation_cnt"][:] = 47
    result = scanned(buffer.getvalue())
    assert result["rows"] == []
    if code:
        assert result["status"] == "held" and result["hold_code"] == code
    else:
        assert result["status"] == "qualified" and result["diagnostics"]["incomplete_cells"] > 0


@pytest.mark.parametrize("encoding", ["fixed", "utf-8", "ascii"])
def test_actual_collector_writer_required_checks_and_fixture_sender(encoding, monkeypatch, ordinary_grid_world):  # noqa: F811
    transport, state, run, models, _module = ordinary_grid_world
    transport.payload = encoded_frame(encoding)
    assert collect(ordinary_grid_world) is state
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["text"] == COPY + "\n" + gpm_public_url()
    assert draft["approval_binding"]["mode"] == "auto"
    assert len(transport.nasa_calls) == 3
    details = next(r for r in run["sources"] if r["source"] == "gpm_imerg")["details"]
    assert details["rainfall_grid_discovery"]["diagnostics"]["qualifying_tiles"] == 1
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    send(monkeypatch, ordinary_grid_world, at=NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]


@pytest.mark.parametrize("encoding", ["fixed", "utf-8", "ascii"])
def test_changed_same_value_file_at_live_boundary_still_refuses(encoding, monkeypatch, ordinary_grid_world):  # noqa: F811
    transport, state, _run, models, _module = ordinary_grid_world
    transport.payload = encoded_frame(encoding)
    revised = io.BytesIO(transport.payload)
    with h5py.File(revised, "r+") as handle:
        handle.attrs["invented_revision"] = "changed"
    transport.on_request = lambda count: setattr(transport, "payload", revised.getvalue()) if count == 2 else None
    collect(ordinary_grid_world)
    assert state["drafts"] == [] and models.stages() == [] and transport.x_posts == []


def stored_attribute_frame(case, field, shape, *, padding=None):
    """Write the original HDF5 type/bytes, without a lossy high-level read."""
    buffer = io.BytesIO(nasa_frame())
    with h5py.File(buffer, "r+") as handle:
        path, key = field
        node = handle[path]
        value = node.attrs[key].encode("ascii")
        del node.attrs[key]
        if case == "opaque":
            dtype = h5py.opaque_dtype(np.dtype(f"S{len(value)}"))
            node.attrs.create(key, np.array(value if shape == () else [value], dtype=dtype))
        elif case == "wide":
            node.attrs.create(key, np.array(value if shape == () else [value], dtype="S129"))
        else:
            width = len(value) if case == "full_width" else len(value) + 8
            data = value if case == "full_width" else value + (b"\x00hour" if case == "suffix" else b" ")
            type_id = h5py.h5t.C_S1.copy()
            type_id.set_size(width)
            type_id.set_strpad(h5py.h5t.STR_NULLTERM if padding is None else padding)
            space_id = h5py.h5s.create(h5py.h5s.SCALAR) if shape == () else h5py.h5s.create_simple(shape)
            attribute = h5py.h5a.create(node.id, key.encode("ascii"), type_id, space_id)
            raw = np.zeros(shape, dtype=f"S{width}")
            if case == "positive":
                data = value + (b" " * (width - len(value)) if padding == h5py.h5t.STR_SPACEPAD else b"\x00")
            raw[...] = data
            attribute.write(raw, mtype=type_id)
            attribute.close()
            space_id.close()
            type_id.close()
    return buffer.getvalue()


@pytest.mark.parametrize("field", [("precipitation", "units"), ("lon", "units"),
                                   ("lat", "units"), ("time", "units"), ("time", "calendar")])
@pytest.mark.parametrize("shape", [(), (1,)])
@pytest.mark.parametrize("case", ["opaque", "suffix", "wide"])
def test_original_storage_type_width_and_hidden_suffix_refuse(case, shape, field):
    raw = stored_attribute_frame(case, field, shape)
    result = scanned(raw)
    assert result["status"] == "held" and result["rows"] == [], (case, shape, field, result)


@pytest.mark.parametrize("shape", [(), (1,)])
@pytest.mark.parametrize("padding", [h5py.h5t.STR_NULLTERM, h5py.h5t.STR_NULLPAD, h5py.h5t.STR_SPACEPAD])
def test_declared_padding_is_decoded_without_dropping_nonpadding_bytes(shape, padding):
    raw = stored_attribute_frame("positive", ("precipitation", "units"), shape, padding=padding)
    result = scanned(raw)
    assert result["status"] == "qualified" and result["rows"][0]["mm_per_day"] == 190.5


@pytest.mark.parametrize("shape", [(), (1,)])
def test_full_width_nullterm_string_matches_native_netcdf_without_a_stored_zero(shape):
    raw = stored_attribute_frame("full_width", ("precipitation", "units"), shape)
    result = scanned(raw)
    assert result["status"] == "qualified" and result["rows"][0]["mm_per_day"] == 190.5
