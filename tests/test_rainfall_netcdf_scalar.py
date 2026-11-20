"""Actual invented NetCDF writer→HDF5 collector→SDK fixture→saved X receipt."""
from datetime import timedelta
from hashlib import sha256
import io
from pathlib import Path
import subprocess
import sys

from freezegun import freeze_time
import h5py
import numpy as np
import pytest

from src.data import gpm_imerg as gpm, rainfall_grid as contract, rainfall_grid_scan as scan
from src.orchestrator.sources import gpm_imerg as source
from tests.test_rainfall_grid_pipeline import (
    COPY, NOW, collect, gpm_public_url, send,
    enabled, grid_world, ordinary_grid_world,  # noqa: F401
)
from tests.test_rainfall_grid_scan import changed, scanned


@pytest.fixture(scope="module")
def netcdf_frame(tmp_path_factory):
    path = tmp_path_factory.mktemp("invented-netcdf") / "invented-day.nc4"
    helper = Path(__file__).with_name("rainfall_netcdf_fixture.py")
    result = subprocess.run([sys.executable, str(helper), str(path),
                             (NOW - timedelta(days=1)).date().isoformat()],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return path.read_bytes()


def test_real_netcdf_writer_represents_numeric_scalar_metadata_as_singletons(netcdf_frame):
    with h5py.File(io.BytesIO(netcdf_frame), "r") as handle:
        for name, expected in (("_FillValue", -9999), ("scale_factor", 1), ("add_offset", 0)):
            attribute = np.asarray(handle["precipitation"].attrs[name])
            assert attribute.shape == (1,) and attribute.dtype.kind in "fiu"
            assert attribute[0] == expected
        assert handle["precipitation"].shape == scan.SHAPE
        assert handle["precipitation"][0, 1299, 799] == 190.5
        assert handle["precipitation_cnt"][0, 1299, 799] == 48


def test_native_singleton_and_supported_scalar_metadata_give_identical_quantities(netcdf_frame):
    def normalize(handle):
        for name in ("precipitation", "precipitation_cnt", "lon", "lat", "time"):
            for attribute in ("_FillValue", "missing_value", "scale_factor", "add_offset"):
                if attribute in handle[name].attrs:
                    value = np.asarray(handle[name].attrs[attribute])
                    assert value.shape == (1,)
                    handle[name].attrs[attribute] = value.reshape(())
    scalar_bytes = changed(normalize, payload=netcdf_frame)
    singleton, scalar = scanned(netcdf_frame), scanned(scalar_bytes)
    assert singleton["status"] == scalar["status"] == "qualified"
    for result, raw in ((singleton, netcdf_frame), (scalar, scalar_bytes)):
        [evidence] = result["rows"]
        assert evidence.pop("source_file_sha256") == sha256(raw).hexdigest()
    assert singleton == scalar


def test_actual_netcdf_collector_preserves_source_quantities_and_one_download(netcdf_frame, grid_world):  # noqa: F811
    transport, state, run, cities = grid_world
    transport.payload = netcdf_frame
    with freeze_time(NOW):
        source.run_gpm_imerg(state, run, cities)
    [candidate] = state.get("_triage_queue", [])
    assert candidate.bundle.country == "BR"
    assert candidate.bundle.headline_metric["value"] == 190.5
    evidence = contract.validate_bundle(candidate.bundle, now=NOW)
    assert evidence["source_file_sha256"] == sha256(netcdf_frame).hexdigest()
    assert evidence["valid_half_hours"] == 48
    assert evidence["source_units"] == "mm/day"
    result = next(r for r in run["sources"] if r["source"] == "gpm_imerg")["details"]["rainfall_grid_discovery"]
    assert result["status"] == "qualified" and result["diagnostics"]["qualifying_cells"] == 1
    assert result["diagnostics"]["qualifying_tiles"] == 1
    assert len(transport.nasa_calls) == 1 and transport.x_posts == []


@pytest.mark.parametrize("triage", [False, True])
def test_netcdf_bytes_through_actual_writer_required_checks_save_and_fixture_sender(
    netcdf_frame, ordinary_grid_world, monkeypatch, triage,  # noqa: F811
):
    transport, state, run, models, _module = ordinary_grid_world
    transport.payload = netcdf_frame
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1" if triage else "0")
    assert collect(ordinary_grid_world) is state
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["text"] == COPY + "\n" + gpm_public_url()
    assert len(draft["text"]) <= 200
    assert draft["approval_binding"]["mode"] == "auto"
    assert draft["review_binding"]["kind"] == "model"
    evidence = contract.validate_bundle(draft["review_context"]["two_bot"]["bundle"], now=NOW)
    assert evidence["source_file_sha256"] == sha256(netcdf_frame).hexdigest()
    assert evidence["mm_per_day"] == 190.5 and evidence["valid_half_hours"] == 48
    assert len(transport.nasa_calls) == 3
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    assert state["publish_ledger"][draft["event_id"]]["phase"] == "confirmed"
    send(monkeypatch, ordinary_grid_world, at=NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]
    assert sha256(transport.payload).digest() == sha256(netcdf_frame).digest()


def test_changed_netcdf_file_identity_is_rechecked_before_fixture_send(
    netcdf_frame, ordinary_grid_world, monkeypatch,  # noqa: F811
):
    transport, state, _run, models, _module = ordinary_grid_world
    transport.payload = netcdf_frame
    collect(ordinary_grid_world)
    [draft] = state["drafts"]
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    transport.payload = changed(lambda h: h.attrs.__setitem__("invented_revision", 2), payload=netcdf_frame)
    assert sha256(transport.payload).digest() != sha256(netcdf_frame).digest()
    send(monkeypatch, ordinary_grid_world)
    assert transport.x_posts == [] and draft["status"] != "posted"


@pytest.mark.parametrize("name,value", [("scale_factor", .1), ("add_offset", 1), ("scale_factor", float("nan"))])
def test_netcdf_nonidentity_scaling_remains_held(netcdf_frame, name, value):
    raw = changed(lambda h: h["precipitation"].attrs.__setitem__(name, np.array([value])), payload=netcdf_frame)
    result = scanned(raw)
    assert result["status"] == "held" and result["rows"] == []
    assert result["hold_code"] == "rainfall_grid_packed_data_unsupported"


@pytest.mark.parametrize("dataset,value,category", [
    ("precipitation", 190.5, "invalid_value_cells"),
    ("precipitation_cnt", 48, "incomplete_cells"),
])
def test_singleton_missing_marker_excludes_the_peak(netcdf_frame, dataset, value, category):
    raw = changed(lambda h: h[dataset].attrs.__setitem__("_FillValue", np.array([value])), payload=netcdf_frame)
    result = scanned(raw)
    assert result["status"] == "qualified" and result["rows"] == []
    assert result["diagnostics"][category] > 0


def test_netcdf_47_slot_peak_cannot_become_an_observation(netcdf_frame):
    raw = changed(lambda h: h["precipitation_cnt"].__setitem__((0, 1299, 799), 47), payload=netcdf_frame)
    result = scanned(raw)
    assert result["status"] == "qualified" and result["rows"] == []
    assert result["diagnostics"]["incomplete_cells"] > 0


def test_singleton_nan_missing_marker_remains_missing(netcdf_frame):
    def missing(handle):
        handle["precipitation"].attrs["_FillValue"] = np.array([float("nan")])
        handle["precipitation"][0, 1299, 799] = float("nan")
    result = scanned(changed(missing, payload=netcdf_frame))
    assert result["status"] == "qualified" and result["rows"] == []
    assert result["diagnostics"]["invalid_value_cells"] > 0


@pytest.mark.parametrize("value", [np.array(1, dtype="i8"), np.array([1], dtype="i8"),
                                 np.array(1, dtype="f4"), np.array([1], dtype="f4")])
def test_scalar_and_singleton_numeric_forms_are_equivalent(value):
    assert scan._numeric_attribute(value) == 1


@pytest.mark.parametrize("value", [True, [True], "1", ["1"], [], [1, 1], [[1]],
                                 np.array([1], dtype=object), 1j, [1j]])
def test_ambiguous_or_nonnumeric_scalar_forms_stay_held(value):
    with pytest.raises(contract.GridHeld, match="rainfall_grid_attribute_invalid"):
        scan._numeric_attribute(value)
