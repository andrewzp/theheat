"""Documented CF default through the actual IMERG reader; invented quantities."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import io

import h5py
import numpy as np
import pytest

from src.data import rainfall_grid as contract, rainfall_grid_scan as scan
from tests.test_rainfall_grid_scan import changed, scanned
from tests.test_rainfall_grid_pipeline import (
    COPY, NOW, collect, send, nasa_frame,
    enabled, grid_world, ordinary_grid_world,  # noqa: F401
)

DAY = (NOW - timedelta(days=1)).date()
EPOCH = datetime(1980, 1, 6, tzinfo=UTC)
UNITS = "days since 1980-01-06 00:00:00Z"


def cf_time(handle, *, absent=True):
    node = handle["time"]
    node.attrs["units"] = UNITS
    node[0] = (datetime.combine(DAY, datetime.min.time(), UTC) - EPOCH).total_seconds() / 86400
    if "calendar" in node.attrs:
        del node.attrs["calendar"]
    if not absent:
        node.attrs["calendar"] = "standard"


def unit_time(change=None, *, day=DAY):
    with h5py.File(io.BytesIO(), "w") as handle:
        handle.create_dataset("time", data=np.array([0.0]))
        cf_time(handle)
        if change is not None:
            change(handle["time"])
        return scan._source_time(handle["time"], day)


@pytest.mark.parametrize("origin", ["days since 1980-01-06 00:00:00Z",
                                  "days since 1980-01-06 00:00:00 UTC"])
def test_genuinely_absent_calendar_uses_documented_cf_standard(origin):
    assert unit_time(lambda t: t.attrs.__setitem__("units", origin)) == DAY.isoformat() + "T00:00:00Z"


@pytest.mark.parametrize("calendar", ["standard", "gregorian", "proleptic_gregorian"])
def test_explicit_supported_calendars_keep_the_same_timestamp(calendar):
    assert unit_time(lambda t: t.attrs.__setitem__("calendar", calendar)) == DAY.isoformat() + "T00:00:00Z"


@pytest.mark.parametrize("calendar", ["", "360_day", "none", "STANDARD", "julian", 0,
                                    np.array(["standard", "standard"], dtype=h5py.string_dtype()),
                                    np.void(b"standard")])
def test_present_invalid_calendar_never_falls_back_to_the_default(calendar):
    with pytest.raises(contract.GridHeld, match="rainfall_grid_time_invalid"):
        unit_time(lambda t: t.attrs.__setitem__("calendar", calendar))


@pytest.mark.parametrize("attribute", ["month_lengths", "leap_year", "leap_month"])
def test_missing_calendar_with_a_custom_definition_refuses(attribute):
    with pytest.raises(contract.GridHeld, match="rainfall_grid_time_invalid"):
        unit_time(lambda t: t.attrs.__setitem__(attribute, 1))


@pytest.mark.parametrize("change,day", [
    (lambda t: t.attrs.__delitem__("units"), DAY),
    (lambda t: t.attrs.__setitem__("units", "days since 1500-01-01 00:00:00Z"), DAY),
    (lambda t: t.__setitem__(0, float("nan")), DAY),
    (lambda t: t.__setitem__(0, float("inf")), DAY),
    (lambda t: t.__setitem__(0, t[0] + 0.0000001), DAY),
    (None, DAY - timedelta(days=1)), (None, DAY + timedelta(days=1)),
])
def test_default_does_not_change_units_origin_precision_or_source_date_guards(change, day):
    with pytest.raises(contract.GridHeld, match="rainfall_grid_time_invalid"):
        unit_time(change, day=day)


@pytest.mark.parametrize("unit,scale", [("days", 86400), ("hours", 3600), ("seconds", 1)])
@pytest.mark.parametrize("direction", [float("-inf"), float("inf")])
def test_encoded_fraction_below_datetime_precision_cannot_round_into_a_valid_day(unit, scale, direction):
    def fractional(node):
        seconds = (datetime.combine(DAY, datetime.min.time(), UTC) - EPOCH).total_seconds()
        node.attrs["units"] = f"{unit} since 1980-01-06 00:00:00Z"
        node[0] = np.nextafter(seconds / scale, direction)
    with pytest.raises(contract.GridHeld, match="rainfall_grid_time_invalid"):
        unit_time(fractional)


@pytest.mark.parametrize("unit,scale", [("days", 86400), ("hours", 3600), ("seconds", 1)])
def test_exact_whole_seconds_and_binary_fractional_days_remain_supported(unit, scale):
    def noon(node):
        seconds = (datetime.combine(DAY, datetime.min.time(), UTC) - EPOCH).total_seconds() + 43200
        node.attrs["units"] = f"{unit} since 1980-01-06 00:00:00Z"
        node[0] = seconds / scale
    assert unit_time(noon) == DAY.isoformat() + "T12:00:00Z"


@pytest.mark.parametrize("direction", [float("-inf"), float("inf")])
def test_full_grid_cannot_nominate_a_timestamp_rounded_across_midnight(direction):
    def fractional(handle):
        cf_time(handle)
        handle["time"][0] = np.nextafter(handle["time"][0], direction)
    result = scanned(changed(fractional))
    assert result["status"] == "held" and result["rows"] == []
    assert result["hold_code"] == "rainfall_grid_time_invalid"


@pytest.mark.parametrize("grouped", [False, True])
def test_full_grid_default_matches_explicit_standard_and_preserves_each_file_identity(grouped):
    def layout(handle, absent):
        cf_time(handle, absent=absent)
        if grouped:
            handle.create_group("Grid")
            for name in list(handle.keys()):
                if name != "Grid":
                    handle.move(name, "Grid/" + name)
    absent = changed(lambda h: layout(h, True))
    explicit = changed(lambda h: layout(h, False))
    assert sha256(absent).digest() != sha256(explicit).digest()
    outputs = []
    for raw in (absent, explicit):
        result = scanned(raw)
        assert result["status"] == "qualified"
        assert result["diagnostics"]["qualifying_cells"] == 1
        [evidence] = result["rows"]
        assert contract.validate_evidence(evidence, now=NOW) == evidence
        assert evidence["source_time_utc"] == DAY.isoformat() + "T00:00:00Z"
        assert evidence["source_file_sha256"] == sha256(raw).hexdigest()
        projected = deepcopy(result)
        projected["rows"][0].pop("source_file_sha256")
        outputs.append(projected)
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize("amount,count", [(149.9, 48), (1000.1, 48), (190.5, 47)])
def test_default_does_not_promote_outside_range_or_incomplete_cells(amount, count):
    raw = changed(cf_time, payload=nasa_frame(amount=amount, count=count))
    result = scanned(raw)
    assert result["status"] == "qualified" and result["rows"] == []


@pytest.mark.parametrize("offset", [-18, 20])
def test_default_does_not_admit_future_or_stale_frames(offset):
    assert scanned(changed(cf_time), now=NOW + timedelta(hours=offset))["status"] == "held"


def test_actual_collector_writer_checks_save_and_fixture_sender_use_default_calendar(
    ordinary_grid_world, monkeypatch,  # noqa: F811
):
    transport, state, _run, models, _module = ordinary_grid_world
    transport.payload = changed(cf_time)
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "1")
    collect(ordinary_grid_world)
    assert models.stages() == ["writer", "safety", "fact_check", "critic"]
    [draft] = state["drafts"]
    assert draft["text"].startswith(COPY)
    assert draft["approval_binding"]["mode"] == "auto"
    evidence = contract.validate_bundle(draft["review_context"]["two_bot"]["bundle"], now=NOW)
    assert evidence["source_file_sha256"] == sha256(transport.payload).hexdigest()
    assert evidence["source_time_utc"] == DAY.isoformat() + "T00:00:00Z"
    send(monkeypatch, ordinary_grid_world)
    assert draft["status"] == "posted" and draft["tweet_id"] == "invented-x-1"
    send(monkeypatch, ordinary_grid_world, at=NOW + timedelta(minutes=4))
    assert transport.x_posts == [draft["text"]]
