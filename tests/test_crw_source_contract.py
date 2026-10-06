"""Offline NOAA wire-contract and source-to-queue regressions with invented data."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime
import hashlib
import json
import shutil
from unittest.mock import Mock

import pytest
import requests

from src.data import crw_contract as contract
from src.data import ocean_sst_anomaly as source
from src.data.source_status import SourceFetchError
from src.state import DEFAULT_STATE
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.intern.marine import build_regional_sst_anomaly_bundle
from tests.crw_fixtures import (
    DAY,
    quiet_sample,
    sample_with_reading,
    RETRIEVED,
    csv_body,
    metadata_body,
    metadata_receipt,
    native_file,
    response,
)

REGION = source.REGION_REGISTRY[-1]
TODAY = date(2026, 6, 16)
URL = f"{source.NOAA_STAR_SSTA_BASE_URL}/2026/ct5km_ssta_v3.1_20260614.nc"


@pytest.fixture
def clock(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 16, 12, tzinfo=UTC)

    monkeypatch.setattr(source, "datetime", FixedClock)
    monkeypatch.setattr(contract, "datetime", FixedClock)


@pytest.fixture
def primary_event(monkeypatch, clock):
    def get(url, **kwargs):
        return response(metadata_body() if url == contract.METADATA_URL else csv_body(REGION))

    monkeypatch.setattr(source, "fetch_with_retry", get)
    reading = source.fetch_region_sst(REGION, strict=True, today=TODAY)
    assert reading is not None
    return source.detect_regional_sst_anomaly_events([reading])[0]


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    return native_file(tmp_path_factory.mktemp("crw") / "invented.nc")


def decode_native(body, **kwargs):
    return source._readings_from_noaa_star_netcdf_bytes(
        body,
        data_date=DAY,
        regions=(REGION,),
        today=TODAY,
        source_url=URL,
        retrieved_at=RETRIEVED,
        **kwargs,
    )


def test_http_source_to_queue_without_injected_provenance(monkeypatch, clock):
    from src.orchestrator.sources.ocean_sst_anomaly import run_ocean_sst_anomaly

    calls, responses = [], []
    by_url = {source._build_url(r): r for r in source.REGION_REGISTRY}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        body = (
            metadata_body()
            if url == contract.METADATA_URL
            else csv_body(by_url[url], value=3.6 if by_url[url].slug == REGION.slug else 0)
        )
        result = response(body)
        responses.append(result)
        return result

    monkeypatch.setattr(source, "fetch_with_retry", get)
    bot_state = deepcopy(DEFAULT_STATE)
    current_run = {"sources": []}
    run_ocean_sst_anomaly(bot_state, current_run)
    assert current_run["sources"][0]["promoted"] == 1
    assert current_run["sources"][0]["observed"] == 13
    candidates = bot_state["_triage_queue"]
    assert len(candidates) == 1
    bundle = candidates[0].bundle
    assert audit_story_bundle(bundle).prompt_ready
    p = bundle.raw_signal_dump["provenance"]
    assert p["response_sha256"] == hashlib.sha256(csv_body(REGION)).hexdigest()
    assert p["response_bytes"] == len(csv_body(REGION))
    assert p["total_cells"] == p["valid_cells"] == 561
    assert p["retrieved_at"] == RETRIEVED
    assert p["product_timestamp"] == f"{DAY}T12:00:00Z"
    assert p["sampled_bounds"] == [-4.975, 5.025, -169.975, -119.975]
    assert p["source_url"] == source._build_url(REGION)
    assert p["primary_metadata"]["metadata_sha256"] == hashlib.sha256(metadata_body()).hexdigest()
    assert len(calls) == 14  # one metadata receipt shared by all 13 regions
    assert all(k["attempts"] == 1 and k["timeout"] == 10 for _, k in calls)
    assert all(
        k["stream"]
        and k["allow_redirects"] is False
        and k["headers"]["Accept-Encoding"] == "identity"
        for _, k in calls
    )
    assert all(r.close.call_count == 1 for r in responses)
    assert not bot_state["sst_anom_last_tier"]  # queueing has not posted or approved


def test_bundle_keeps_analysis_scope_and_does_not_mutate(primary_event):
    before = deepcopy(primary_event)
    bundle = build_regional_sst_anomaly_bundle(primary_event)
    assert primary_event == before
    facts = {f["label"]: f["value"] for f in bundle.current_facts}
    assert facts["data_source"] == contract.PRODUCT_NAME
    assert facts["evidence_grade"] == "satellite_analysis"
    assert "not a verified measurement interval" in facts["signal_note"]
    assert "Not a historical record" in facts["signal_note"]
    bundle.raw_signal_dump["provenance"]["response_sha256"] = "changed"
    assert primary_event == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_product", "another-product"),
        ("source_name", "Invented Source"),
        ("source_url", "https://example.invalid/file"),
        ("source_leg", "noaa_star_nc"),
        ("response_sha256", "bad"),
        ("response_bytes", 0),
        ("response_bytes", contract.CSV_LIMIT + 1),
        ("schema_version", True),
        ("retrieved_at", "2026-06-13T12:00:00Z"),
        ("product_timestamp", "2026-06-15T12:00:00Z"),
        ("valid_date", "2026-06-15"),
        ("mean_anomaly_c", 4.0),
        ("mean_anomaly_c", float("nan")),
        ("unit", "K"),
        ("region_slug", "caribbean"),
        ("region_display_name", "Caribbean Sea"),
        ("method", "full grid mean"),
        ("grid_stride", True),
        ("native_grid_degrees", 1),
        ("valid_cells", 1),
        ("total_cells", 2),
        ("excluded_cells", -1),
        ("requested_bounds", [0, 0, 0, 0]),
        ("sampled_bounds", [0, 0, 0, 0]),
        ("sampled_bounds", [5.025, -4.975, -169.975, -119.975]),
        ("primary_metadata", None),
        ("evidence_type", "station_observation"),
    ],
)
def test_changed_source_binding_is_unqualified(primary_event, field, value):
    primary_event.provenance[field] = value
    assert not contract.qualified_provenance(primary_event)
    bundle = build_regional_sst_anomaly_bundle(primary_event)
    assert "provenance" not in bundle.raw_signal_dump
    assert "unqualified_provenance" in bundle.raw_signal_dump
    assert not audit_story_bundle(bundle).prompt_ready
    expected = (
        "invalid_evidence_json"
        if field == "mean_anomaly_c" and value != value
        else "missing_provenance"
    )
    assert expected in {i.code for i in audit_story_bundle(bundle).issues}


@pytest.mark.parametrize(
    "field,value",
    [
        ("metadata_sha256", "bad"),
        ("metadata_url", "https://example.invalid"),
        ("first_product_time", "2026-06-15T12:00:00Z"),
        ("last_product_time", "2026-06-13T12:00:00Z"),
        ("retrieved_at", "2026-06-17T12:00:00Z"),
        ("response_bytes", True),
    ],
)
def test_metadata_receipt_binding(primary_event, field, value):
    primary_event.provenance["primary_metadata"][field] = value
    assert not contract.qualified_provenance(primary_event)


@pytest.mark.parametrize("leg", [None, "noaa_star_nc", "invented"])
def test_legacy_event_does_not_gain_attribution(primary_event, leg):
    event = replace(primary_event, source_leg=leg, provenance=None)
    assert not audit_story_bundle(build_regional_sst_anomaly_bundle(event)).prompt_ready


@pytest.mark.parametrize(
    "field,value",
    [
        ("date", "2026-06-13"),
        ("cells_used", 10),
        ("anomaly_c", 4.5),
        ("region_display_name", "Another place"),
        ("source_leg", "noaa_star_nc"),
    ],
)
def test_event_and_receipt_must_agree(primary_event, field, value):
    assert not contract.qualified_provenance(replace(primary_event, **{field: value}))


def test_csv_known_weighting_and_excluded_cells():
    selected = {
        (5.0, -170.0): 4.0,
        (-5.0, -170.0): 2.0,
        (0.0, -170.0): 0.0,
        (1.0, -170.0): -327.68,
        (2.0, -170.0): 20.0,
    }
    sample = contract.decode_csv(csv_body(REGION, selected=selected, offset=0).decode(), REGION)
    assert sample.total_cells == 561 and len(sample.cells) == 3
    assert source._area_weighted_mean(sample.cells) == pytest.approx(1.9974566718)


@pytest.mark.parametrize(
    "change",
    [
        "columns",
        "units",
        "short_row",
        "extra_field",
        "mixed_time",
        "bad_time",
        "future_format",
        "latitude",
        "longitude",
        "nan_coordinate",
        "infinite",
        "nonnumeric",
        "duplicate",
        "duplicate_nan",
        "missing_cell",
        "missing_axis",
        "outside",
        "stride",
        "empty",
    ],
)
def test_csv_corruption_rejected(change):
    rows = csv_body(REGION).decode().splitlines()
    if change == "columns":
        rows[0] = rows[0].replace("longitude", "latitude")
    elif change == "units":
        rows[1] = rows[1].replace("degree_C", "K")
    elif change == "short_row":
        rows[2] = rows[2].rsplit(",", 1)[0]
    elif change == "extra_field":
        rows[2] += ",extra"
    elif change == "mixed_time":
        rows[2] = rows[2].replace(DAY, "2026-06-13")
    elif change == "bad_time":
        rows[2] = rows[2].replace(DAY, "2026-02-30")
    elif change == "future_format":
        rows[2] = rows[2].replace("12:00:00Z", "12:00:00+00:00")
    elif change in (
        "latitude",
        "longitude",
        "nan_coordinate",
        "infinite",
        "nonnumeric",
        "outside",
        "stride",
    ):
        row = rows[2].split(",")
        index, val = {
            "latitude": (1, "91"),
            "longitude": (2, "181"),
            "nan_coordinate": (1, "NaN"),
            "infinite": (3, "inf"),
            "nonnumeric": (3, "unknown"),
            "outside": (1, "5.1"),
            "stride": (1, "4.525"),
        }[change]
        row[index] = val
        rows[2] = ",".join(row)
    elif change == "duplicate":
        rows.append(rows[2])
    elif change == "duplicate_nan":
        rows.append(rows[2].rsplit(",", 1)[0] + ",NaN")
    elif change == "missing_cell":
        rows.pop()
    elif change == "missing_axis":
        rows = rows[:2] + rows[53:]
    elif change == "empty":
        rows = rows[:2]
    with pytest.raises(SourceFetchError):
        contract.decode_csv("\n".join(rows), REGION)


@pytest.mark.parametrize("bad", [b"{}", b"null", b"[]", b"invalid"])
def test_metadata_invalid_structure(bad):
    with pytest.raises(SourceFetchError):
        contract.metadata_contract(bad)


@pytest.mark.parametrize(
    "attribute", ["id", "product_version", "processing_level", "units", "time_coverage_end"]
)
def test_metadata_changed_meaning(attribute):
    data = json.loads(metadata_body())
    next(r for r in data["table"]["rows"] if r[2] == attribute)[4] = "wrong"
    with pytest.raises(SourceFetchError):
        contract.metadata_contract(json.dumps(data).encode())


def test_metadata_duplicate_attributes():
    data = json.loads(metadata_body())
    data["table"]["rows"].append(data["table"]["rows"][0])
    with pytest.raises(SourceFetchError):
        contract.metadata_contract(json.dumps(data).encode())


@pytest.mark.parametrize("day", [date(2026, 6, 13), date(2026, 6, 20)])
def test_future_or_stale_dates_rejected(day):
    with pytest.raises(SourceFetchError, match="freshness"):
        contract.fresh_day(DAY, day)


def test_native_receipt_and_scope(native):
    body = native.read_bytes()
    readings = decode_native(body)
    assert len(readings) == 1 and readings[0].anomaly_c == 3.6
    event = source.detect_regional_sst_anomaly_events(readings)[0]
    assert contract.qualified_provenance(event)
    p = event.provenance
    assert p["response_sha256"] == hashlib.sha256(body).hexdigest()
    assert p["source_url"] == URL and p["source_leg"] == "noaa_star_nc"
    assert p["valid_cells"] == p["total_cells"] == 500
    assert p["sampled_bounds"] == pytest.approx([-4.025, 4.975, -169.975, -120.975], abs=0.0001)
    bundle = build_regional_sst_anomaly_bundle(event)
    assert audit_story_bundle(bundle).prompt_ready
    assert {f["label"]: f["value"] for f in bundle.current_facts}[
        "evidence_grade"
    ] == "satellite_analysis"


@pytest.mark.parametrize(
    "change",
    [
        "identity",
        "version",
        "processing",
        "date",
        "interval",
        "midnight",
        "axis_units",
        "axis_reversed",
        "axis_nonfinite",
        "anomaly_units",
        "scale",
        "offset",
        "range",
        "time_units",
        "calendar",
        "time",
    ],
)
def test_native_metadata_corruption_rejected(native, tmp_path, change):
    from netCDF4 import Dataset

    path = tmp_path / "mutated.nc"
    shutil.copyfile(native, path)
    with Dataset(path, "a") as ds:
        if change == "identity":
            ds.id = "other"
        elif change == "version":
            ds.product_version = "4"
        elif change == "processing":
            ds.processing_level = "forecast"
        elif change == "date":
            ds.time_coverage_start = "20260613T000000Z"
        elif change == "interval":
            ds.time_coverage_end = "20260616T000000Z"
        elif change == "midnight":
            ds.time_coverage_start = "20260614T010000Z"
            ds.time_coverage_end = "20260615T010000Z"
        elif change == "axis_units":
            ds.variables["lat"].units = "radians"
        elif change == "axis_reversed":
            ds.variables["lat"][:] = ds.variables["lat"][:][::-1]
        elif change == "axis_nonfinite":
            ds.variables["lon"][0] = float("nan")
        elif change == "anomaly_units":
            ds.variables[source._SST_ANOM_VAR].units = "K"
        elif change == "scale":
            ds.variables[source._SST_ANOM_VAR].scale_factor = 0.1
        elif change == "offset":
            ds.variables[source._SST_ANOM_VAR].add_offset = 273.15
        elif change == "range":
            ds.variables[source._SST_ANOM_VAR].valid_max = 3000
        elif change == "time_units":
            ds.variables["time"].units = "hours since 1981-01-01"
        elif change == "calendar":
            ds.variables["time"].calendar = "360_day"
        elif change == "time":
            ds.variables["time"][:] = ds.variables["time"][:] + 86400
    with pytest.raises(SourceFetchError):
        decode_native(path.read_bytes())


def test_native_missing_values_are_excluded(native, tmp_path):
    from netCDF4 import Dataset

    path = tmp_path / "masked.nc"
    shutil.copyfile(native, path)
    with Dataset(path, "a") as ds:
        var = ds.variables[source._SST_ANOM_VAR]
        # First selected row and first three selected columns in the Niño box.
        var.set_auto_maskandscale(False)
        var[0, 1700, 200] = -32768
        var[0, 1700, 220] = 1600
        var[0, 1700, 240] = -1600
    reading = decode_native(path.read_bytes())[0]
    assert reading.cells_used == 497 and reading.provenance["excluded_cells"] == 3
    assert reading.anomaly_c == 3.6


def test_transport_fallback_uses_native_receipt(monkeypatch, native, clock):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == contract.METADATA_URL:
            raise requests.Timeout("timed out")
        if url.endswith("/"):
            return response('<a href="ct5km_ssta_v3.1_20260614.nc">data</a>')
        assert url == URL
        return response(native.read_bytes())

    monkeypatch.setattr(source, "fetch_with_retry", get)
    readings = source.fetch_all_regions()
    assert len(readings) == 1 and contract.qualified_provenance(
        source.detect_regional_sst_anomaly_events(readings)[0]
    )
    assert len(calls) == 3
    assert [k["attempts"] for _, k in calls] == [1, 2, 2]


def test_schema_failure_does_not_try_backup(monkeypatch):
    monkeypatch.setattr(source, "fetch_with_retry", lambda *a, **k: response(b"wrong"))
    fallback = Mock(side_effect=AssertionError("backup must not hide schema failure"))
    monkeypatch.setattr(source, "_fetch_noaa_star_ssta_samples_strict", fallback)
    with pytest.raises(SourceFetchError):
        source.fetch_all_regions()
    fallback.assert_not_called()


def test_backup_does_not_replace_successful_below_threshold(monkeypatch):
    monkeypatch.setattr(source, "_primary_metadata", metadata_receipt)

    def primary(region, **kwargs):
        if region.slug == REGION.slug:
            raise requests.Timeout("timed out")
        return quiet_sample(region)

    monkeypatch.setattr(source, "_fetch_region_sample_strict", primary)
    fallback = [
        source.RegionalSSTReading(
            r.slug, r.display_name, DAY, 3.6, 2, 30, source.NOAA_STAR_SSTA_LEG
        )
        for r in (REGION, source.REGION_REGISTRY[0])
    ]
    monkeypatch.setattr(source, "_fetch_noaa_star_ssta_samples_strict", lambda **k: [sample_with_reading(fallback[0])])
    assert source.fetch_all_regions() == [fallback[0]]


@pytest.mark.parametrize(
    "failure", ["size", "elapsed", "empty", "redirect", "encoding", "transport"]
)
def test_bounded_response_always_closes(monkeypatch, failure):
    result = response(b"abcd")
    if failure == "empty":
        result.iter_content.return_value = []
    elif failure == "redirect":
        result.status_code = 302
    elif failure == "encoding":
        result.headers = {"Content-Encoding": "gzip"}
    elif failure == "transport":
        result.iter_content.side_effect = requests.Timeout("timed out")
    elif failure == "elapsed":
        times = iter([0, 61, 61])
        monkeypatch.setattr(source.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(source, "fetch_with_retry", lambda *a, **k: result)
    with pytest.raises((SourceFetchError, requests.Timeout)):
        source._source_body(
            "https://example.invalid", limit=3 if failure == "size" else 10, timeout=10, attempts=1
        )
    result.close.assert_called_once()


def test_primary_csv_schema_error_never_falls_back(monkeypatch, clock):
    monkeypatch.setattr(source, "_primary_metadata", metadata_receipt)
    monkeypatch.setattr(source, "fetch_with_retry", lambda *a, **k: response(b"bad CSV"))
    fallback = Mock(side_effect=AssertionError("schema errors must remain visible"))
    monkeypatch.setattr(source, "_fetch_noaa_star_ssta_samples_strict", fallback)
    with pytest.raises(SourceFetchError, match="all regions failed"):
        source.fetch_all_regions()
    fallback.assert_not_called()


def test_csv_time_outside_metadata_rejected(monkeypatch):
    monkeypatch.setattr(source, "_primary_metadata", metadata_receipt)
    monkeypatch.setattr(
        source, "fetch_with_retry", lambda *a, **k: response(csv_body(REGION, day="2026-06-15"))
    )
    with pytest.raises(SourceFetchError, match="metadata time range"):
        source.fetch_region_sst(REGION, today=TODAY, strict=True)


def test_successful_low_readings_never_download_backup(monkeypatch):
    monkeypatch.setattr(source, "_primary_metadata", metadata_receipt)
    monkeypatch.setattr(source, "_fetch_region_sample_strict", lambda region, **k: quiet_sample(region))
    fallback = Mock(side_effect=AssertionError("no outage"))
    monkeypatch.setattr(source, "_fetch_noaa_star_ssta_samples_strict", fallback)
    assert source.fetch_all_regions() == []
    fallback.assert_not_called()


def test_native_small_metadata_free_grid_rejected(tmp_path):
    from netCDF4 import Dataset

    path = tmp_path / "subset.nc"
    with Dataset(path, "w") as ds:
        ds.createDimension("time", 1)
        ds.createDimension("lat", 2)
        ds.createDimension("lon", 2)
        ds.createVariable(source._SST_ANOM_VAR, "f4", ("time", "lat", "lon"))[:] = 3.6
    with pytest.raises(SourceFetchError, match="identity or dimensions"):
        decode_native(path.read_bytes())


def test_native_decode_without_transfer_receipt_stays_unqualified(native):
    readings = source._readings_from_noaa_star_netcdf_bytes(
        native.read_bytes(), data_date=DAY, regions=(REGION,), today=TODAY
    )
    assert readings[0].provenance is None
    event = source.detect_regional_sst_anomaly_events(readings)[0]
    assert not audit_story_bundle(build_regional_sst_anomaly_bundle(event)).prompt_ready


@pytest.mark.parametrize(
    "case", ["time_type", "anomaly_dimensions", "missing_time", "missing_scale"]
)
def test_native_structural_corruption(native, tmp_path, case):
    from netCDF4 import Dataset

    path = tmp_path / "structure.nc"
    shutil.copyfile(native, path)
    with Dataset(path, "a") as ds:
        if case == "time_type":
            old = ds.variables["time"]
            values, units = old[:], old.units
            ds.renameVariable("time", "prior_time")
            var = ds.createVariable("time", "f8", ("time",))
            var.units = units
            var[:] = values + 0.5
        elif case == "anomaly_dimensions":
            ds.renameVariable(source._SST_ANOM_VAR, "prior_anomaly")
            ds.createVariable(source._SST_ANOM_VAR, "i2", ("lat", "lon", "time"))
        elif case == "missing_time":
            ds.renameVariable("time", "prior_time")
        elif case == "missing_scale":
            ds.variables[source._SST_ANOM_VAR].delncattr("scale_factor")
    with pytest.raises(SourceFetchError):
        decode_native(path.read_bytes())


@pytest.mark.parametrize(
    "name,value", [("_Unsigned", "true"), ("missing_value", 360), ("valid_range", [0, 1500])]
)
def test_native_conflicting_mask_metadata_is_rejected(native, tmp_path, name, value):
    from netCDF4 import Dataset

    path = tmp_path / "mask-contract.nc"
    shutil.copyfile(native, path)
    with Dataset(path, "a") as ds:
        ds.variables[source._SST_ANOM_VAR].setncattr(name, value)
    with pytest.raises(SourceFetchError, match="encoding"):
        decode_native(path.read_bytes())


def install_collection_wire(monkeypatch, *, overrides=None, metadata=None, native_body=None):
    """All outgoing requests are invented, counted, and restricted to known URLs."""
    by_url = {source._build_url(r): r for r in source.REGION_REGISTRY}
    calls = []
    overrides = overrides or {}

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == contract.METADATA_URL:
            value = metadata_body() if metadata is None else metadata
        elif url in by_url:
            region = by_url[url]
            value = overrides.get(region.slug, csv_body(region, value=1.0))
        elif native_body is not None and url == source._noaa_star_year_index_url(2026):
            value = b'<a href="ct5km_ssta_v3.1_20260614.nc">invented</a>'
        elif native_body is not None and url == URL:
            value = native_body
        else:
            raise AssertionError(f"Unexpected source request: {url}")
        if isinstance(value, Exception):
            raise value
        return response(value)

    monkeypatch.setattr(source, "fetch_with_retry", get)
    return calls


@pytest.mark.parametrize("value,expected_candidates", [(1.0, 0), (2.1, 1), (3.6, 1)])
def test_collection_counts_quiet_samples_and_synthesis_floor(monkeypatch, clock, value, expected_candidates):
    calls = install_collection_wire(monkeypatch, overrides={REGION.slug: csv_body(REGION, value=value)})
    decode = Mock(wraps=contract.decode_csv)
    monkeypatch.setattr(contract, "decode_csv", decode)
    report = source.collect_all_regions()
    assert report.status == "success" and report.observed == 13
    assert len(report.readings) == expected_candidates
    assert report.recovered == report.fallback_attempted == 0
    assert len(calls) == 14 and decode.call_count == 13
    assert all(kwargs["attempts"] == 1 for _, kwargs in calls)
    for row in report.regions:
        assert row.primary is row.final and row.final.qualified
        assert row.final.product_date == DAY
        assert row.final.total_cells == row.final.valid_cells
        assert row.final.excluded_cells == 0
    assert len(json.dumps(report.details())) < 15000
    assert "response_sha256" not in json.dumps(report.details())


@pytest.mark.parametrize("case,kind", [
    ("masked", "insufficient_sample"), ("schema", "source_rejected"),
    ("transport", "transport_failure"),
])
def test_collection_partial_failures_count_only_qualified_regions(monkeypatch, clock, case, kind):
    value = {
        "masked": csv_body(REGION, selected={(5., -170. + i): 3.6 for i in range(9)}),
        "schema": b"bad source contract",
        "transport": requests.Timeout("timed out: private-error-payload"),
    }[case]
    calls = install_collection_wire(
        monkeypatch, overrides={REGION.slug: value},
        native_body=requests.Timeout("timed out: private-native-payload") if case == "transport" else None,
    )
    report = source.collect_all_regions()
    assert report.status == "partial_failure" and report.observed == 12
    row = report.regions[-1]
    assert row.primary.outcome == kind and not row.final.qualified
    assert report.details()["unresolved_regions"] == 1
    assert "private-" not in json.dumps(report.details())
    assert len(calls) == (16 if case == "transport" else 14)
    if case == "masked":
        assert row.final.valid_cells == 9 and row.final.total_cells == 561
        assert row.final.excluded_cells == 552
        assert row.final.product_date == DAY


@pytest.fixture(scope="module")
def quiet_native(tmp_path_factory):
    return native_file(tmp_path_factory.mktemp("crw-quiet") / "quiet.nc", value=1.0).read_bytes()


@pytest.mark.parametrize("backup", ["quiet", "candidate"])
def test_collection_native_recovers_only_failed_region(monkeypatch, clock, quiet_native, native, backup):
    body = quiet_native if backup == "quiet" else native.read_bytes()
    calls = install_collection_wire(
        monkeypatch, overrides={REGION.slug: requests.Timeout("timed out: private primary")}, native_body=body,
    )
    decode = Mock(wraps=source._samples_from_noaa_star_netcdf_bytes)
    monkeypatch.setattr(source, "_samples_from_noaa_star_netcdf_bytes", decode)
    report = source.collect_all_regions()
    assert report.status == "degraded" and report.observed == 13
    assert report.recovered == report.fallback_attempted == 1
    assert len(report.readings) == (backup == "candidate")
    assert len(calls) == 16
    assert [kwargs["attempts"] for _, kwargs in calls].count(1) == 14
    assert [kwargs["attempts"] for _, kwargs in calls].count(2) == 2
    decode.assert_called_once()
    assert decode.call_args.kwargs["regions"] == (REGION,)
    for row in report.regions[:-1]:
        assert row.primary is row.final and row.final.outcome == "below_floor"
    row = report.regions[-1]
    assert row.primary.outcome == "transport_failure"
    assert row.primary.diagnostic == "regional_transport_failure"
    assert row.recovered and row.final.source_leg == source.NOAA_STAR_SSTA_LEG
    assert row.final.valid_cells == row.final.total_cells == 500
    assert row.final.excluded_cells == 0 and row.final.product_date == DAY


def test_collection_schema_error_prevents_mixed_transport_fallback(monkeypatch, clock):
    calls = install_collection_wire(monkeypatch, overrides={
        REGION.slug: requests.Timeout("timed out"), source.REGION_REGISTRY[0].slug: b"bad schema",
    })
    report = source.collect_all_regions()
    assert report.observed == 11 and report.status == "partial_failure"
    assert report.fallback_attempted == 0 and len(calls) == 14


@pytest.mark.parametrize("failure", [b"bad schema", requests.Timeout("timed out: private transfer")])
def test_collection_all_primary_failures_are_not_quiet(monkeypatch, clock, failure):
    calls = install_collection_wire(
        monkeypatch, overrides={r.slug: failure for r in source.REGION_REGISTRY},
        native_body=b"bad native metadata" if isinstance(failure, Exception) else None,
    )
    report = source.collect_all_regions()
    assert report.status == "failed" and report.observed == 0 and not report.readings
    assert report.details()["unresolved_regions"] == 13
    assert len(calls) == (16 if isinstance(failure, Exception) else 14)
    assert "private transfer" not in json.dumps(report.details())


def test_collection_metadata_rejection_does_not_invent_region_requests(monkeypatch, clock):
    calls = install_collection_wire(monkeypatch, metadata=b"invalid metadata")
    report = source.collect_all_regions()
    assert len(calls) == 1 and report.status == "failed" and report.observed == 0
    for row in report.regions:
        assert row.primary is row.final and not row.primary.request_attempted
        assert row.primary.outcome == "source_rejected"
        assert row.primary.diagnostic == "metadata_source_rejected"
        assert row.primary.total_cells is None


@pytest.mark.parametrize("backup", ["quiet", "candidate", "masked", "rejected"])
def test_collection_metadata_outage_retains_dependency_and_native_coverage(
    monkeypatch, clock, quiet_native, native, backup, tmp_path,
):
    if backup == "masked":
        body = native_file(tmp_path / "masked.nc", value=-327.68).read_bytes()
    elif backup == "rejected":
        body = b"bad native contract"
    else:
        body = quiet_native if backup == "quiet" else native.read_bytes()
    calls = install_collection_wire(
        monkeypatch, metadata=requests.Timeout("timed out: private metadata"), native_body=body,
    )
    report = source.collect_all_regions()
    assert len(calls) == 3 and report.fallback_attempted == 13
    # Only the invented Niño window contains data; all other native cells are masked.
    assert report.observed == (1 if backup in {"quiet", "candidate"} else 0)
    assert report.status == ("partial_failure" if report.observed else "failed")
    assert len(report.readings) == (backup == "candidate")
    for row in report.regions:
        assert not row.primary.request_attempted and row.primary.valid_cells is None
        assert row.primary.diagnostic == "metadata_transport_failure"
        assert row.final.source_leg == source.NOAA_STAR_SSTA_LEG
    if backup == "masked":
        assert report.regions[-1].final.valid_cells == 0
        assert report.regions[-1].final.excluded_cells == 500


def test_collection_all_quiet_native_regions_recover_metadata_outage(monkeypatch, clock, tmp_path):
    world = source.RegionDef("world", "Invented global grid", -90, 90, -180, 180)
    body = native_file(tmp_path / "global-quiet.nc", region=world, value=1.0).read_bytes()
    calls = install_collection_wire(monkeypatch, metadata=requests.Timeout("timed out"), native_body=body)
    report = source.collect_all_regions()
    assert len(calls) == 3
    assert report.status == "degraded" and report.observed == report.recovered == 13
    assert not report.readings


@pytest.mark.parametrize("metadata", [requests.Timeout("timed out"), b"invalid contract"])
def test_strict_collection_preserves_metadata_exceptions(monkeypatch, clock, metadata):
    calls = install_collection_wire(monkeypatch, metadata=metadata)
    expected = requests.Timeout if isinstance(metadata, Exception) else SourceFetchError
    with pytest.raises(expected):
        source.collect_all_regions(strict=True)
    assert len(calls) == 1


@pytest.mark.parametrize("day", ["2026-06-01", "2026-06-17"])
def test_rejected_product_date_and_decoded_counts_remain_visible(monkeypatch, clock, day):
    calls = install_collection_wire(monkeypatch, overrides={REGION.slug: csv_body(REGION, day=day)})
    report = source.collect_all_regions()
    row = report.regions[-1]
    assert report.status == "partial_failure" and report.observed == 12
    assert row.final.outcome == "source_rejected" and row.final.product_date == day
    assert row.final.valid_cells == row.final.total_cells == 561
    assert row.final.reading is None and len(calls) == 14


def test_backup_does_not_retry_insufficient_primary_sample(monkeypatch, clock, native):
    other = source.REGION_REGISTRY[0]
    calls = install_collection_wire(monkeypatch, overrides={
        REGION.slug: requests.Timeout("timed out"), other.slug: csv_body(other, selected={}),
    }, native_body=native.read_bytes())
    decode = Mock(wraps=source._samples_from_noaa_star_netcdf_bytes)
    monkeypatch.setattr(source, "_samples_from_noaa_star_netcdf_bytes", decode)
    report = source.collect_all_regions()
    assert report.status == "partial_failure" and report.observed == 12
    assert report.recovered == 1 and len(calls) == 16
    assert decode.call_args.kwargs["regions"] == (REGION,)
    row = report.regions[0]
    assert row.primary is row.final and row.final.outcome == "insufficient_sample"
    assert row.final.valid_cells == 0
