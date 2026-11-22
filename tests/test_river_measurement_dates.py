"""Invented gauge records through the actual parser, detector and writer bundle."""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.data import _freshness, river_gauges as river
from src.data.source_status import SourceFetchError
from src.two_bot.intern import build_river_flood_bundle

NOW = datetime(2026, 11, 22, 5, tzinfo=UTC)
STATIONS = [("01111111", "Invented River A", "Invented place A"),
            ("02222222", "Invented River B", "Invented place B")]


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    current = {"now": NOW}

    class FrozenDate(date):
        @classmethod
        def today(cls):
            now = current["now"]
            return cls(now.year, now.month, now.day)

    monkeypatch.setattr(river, "date", FrozenDate)
    monkeypatch.setattr(_freshness, "date", FrozenDate)
    # The baseline has no UTC clock seam; this fixture never changes its parser.
    monkeypatch.setattr(river, "_utc_now", lambda: current["now"], raising=False)
    return current


def row(index, stamp, height="35.5"):
    return {"sourceInfo": {"siteCode": [{"value": STATIONS[index][0]}]},
            "variable": {"variableCode": [{"value": "00065"}], "unit": {"unitCode": "ft"},
                         "noDataValue": -999999},
            "values": [{"value": [{"value": height, "dateTime": stamp}]}]}


def prepare(monkeypatch, rows):
    payload = {"value": {"timeSeries": rows}}
    transport = Mock(return_value=SimpleNamespace(json=lambda: deepcopy(payload)))
    stages = Mock(return_value={site: 30.0 for site, *_ in STATIONS})
    monkeypatch.setattr(river, "MAJOR_STATIONS", STATIONS)
    monkeypatch.setattr(river, "fetch_with_retry", transport)
    monkeypatch.setattr(river, "_fetch_flood_stages", stages)
    return transport, stages


def test_fresh_peer_cannot_admit_old_station_to_actual_flood_and_writer_consumers(monkeypatch):
    transport, _ = prepare(monkeypatch, [row(0, "2026-10-22T12:00:00Z"),
                                       row(1, "2026-11-22T04:00:00Z", "11")])
    readings = river._fetch_river_levels_primary(strict=True)
    assert [reading.site_id for reading in readings] == [STATIONS[1][0]]
    assert river.detect_floods(readings) == []
    assert [build_river_flood_bundle(item) for item in river.detect_floods(readings)] == []
    assert transport.call_count == 1


def test_yesterday_measurement_retains_its_date_in_flood_writer_and_event_identity(monkeypatch):
    transport, stages = prepare(monkeypatch, [row(0, "2026-11-21T21:00:00Z")])
    readings = river._fetch_river_levels_primary(strict=True)
    assert len(readings) == 1 and readings[0].date == "2026-11-21"
    flood, = river.detect_floods(readings)
    bundle = build_river_flood_bundle(flood)
    assert flood.date == bundle.when == bundle.raw_signal_dump["date"] == "2026-11-21"
    assert readings[0].event_id == "river_01111111_2026-11-21"
    assert flood.event_id == bundle.event_id == "flood_01111111_2026-11-21"
    assert bundle.headline_metric["value"] == 5.5
    assert transport.call_count == stages.call_count == 1
    assert transport.call_args.args == (river.USGS_URL,)
    assert transport.call_args.kwargs["params"] == {"format": "json", "sites": "01111111,02222222",
                                                   "parameterCd": "00065", "siteStatus": "active"}


@pytest.mark.parametrize("stamp", [None, "", "2026-11-22", "2026-11-22garbage", "invalid",
                                  "2026-11-22T04:00:00", "2026-11-22T04:00:00-00:00",
                                  "2026-11-22T04:00:00+25:00", "2026-11-22T06:00:00Z",
                                  "2026-11-23T00:00:00Z", True, 1795320000])
def test_invalid_missing_or_future_selected_timestamp_cannot_become_today(monkeypatch, stamp):
    prepare(monkeypatch, [row(0, stamp)])
    with pytest.raises(SourceFetchError, match="freshness check failed"):
        river._fetch_river_levels_primary(strict=True)


@pytest.mark.parametrize("stamp", ["2026-10-22T12:00:00Z", None, "2026-11-22T06:00:00Z",
                                  "2026-11-22T04:00:00-00:00"])
def test_individually_held_station_does_not_discard_valid_peer(monkeypatch, stamp):
    prepare(monkeypatch, [row(0, stamp), row(1, "2026-11-22T04:00:00Z")])
    readings = river._fetch_river_levels_primary(strict=True)
    assert [reading.site_id for reading in readings] == [STATIONS[1][0]]
    assert readings[0].date == "2026-11-22"


@pytest.mark.parametrize("stamp,day", [("2026-11-22T00:30:00+03:00", "2026-11-21"),
                                     ("2026-11-21T23:30:00-05:00", "2026-11-22"),
                                     ("2026-11-22T04:00:00+00:00", "2026-11-22"),
                                     ("2026-11-20T00:00:00Z", "2026-11-20")])
def test_known_offsets_use_utc_and_original_two_calendar_day_window(monkeypatch, stamp, day):
    prepare(monkeypatch, [row(0, stamp)])
    reading, = river._fetch_river_levels_primary(strict=True)
    assert reading.date == day and reading.event_id == f"river_01111111_{day}"


def test_retrieval_on_next_day_does_not_mint_an_identity_for_same_measurement(monkeypatch, clock):
    prepare(monkeypatch, [row(0, "2026-11-21T21:00:00Z")])
    first, = river._fetch_river_levels_primary(strict=True)
    clock["now"] += timedelta(days=1)
    second, = river._fetch_river_levels_primary(strict=True)
    assert first == second


@pytest.mark.parametrize("height", ["nan", "inf", "Infinity", float("nan"), float("inf"), True])
def test_nonfinite_or_boolean_height_never_enters_a_reading(monkeypatch, height):
    prepare(monkeypatch, [row(0, "2026-11-22T04:00:00Z", height)])
    assert river._fetch_river_levels_primary(strict=True) == []


def test_last_selected_invalid_value_does_not_backfill_an_earlier_value(monkeypatch):
    bad = row(0, "2026-11-22T06:00:00Z")
    bad["values"][0]["value"].insert(0, {"value": "34", "dateTime": "2026-11-22T04:00:00Z"})
    prepare(monkeypatch, [bad, row(1, "2026-11-22T04:00:00Z")])
    assert [r.site_id for r in river._fetch_river_levels_primary(strict=True)] == [STATIONS[1][0]]


def test_only_stale_rows_remain_an_explicit_source_failure(monkeypatch):
    prepare(monkeypatch, [row(0, "2026-11-19T23:59:59Z")])
    with pytest.raises(SourceFetchError, match="stale data"):
        river._fetch_river_levels_primary(strict=True)


def test_empty_result_is_still_empty_and_current_positive_control_still_builds(monkeypatch):
    prepare(monkeypatch, [])
    assert river._fetch_river_levels_primary(strict=True) == []
    prepare(monkeypatch, [row(0, "2026-11-22T04:00:00Z")])
    reading, = river._fetch_river_levels_primary(strict=True)
    assert reading.above_flood is True and reading.gauge_height_ft == 35.5
    flood, = river.detect_floods([reading])
    assert build_river_flood_bundle(flood).when == "2026-11-22"


@pytest.mark.parametrize("stamp", [None, "2026-11-22T06:00:00Z", "2026-11-22T04:00:00-00:00"])
def test_time_integrity_failure_cannot_hide_behind_a_model_witness(monkeypatch, stamp):
    prepare(monkeypatch, [row(0, stamp)])
    witness = Mock()
    monkeypatch.setattr(river, "_fetch_open_meteo_flood", witness)
    with pytest.raises(SourceFetchError, match="freshness check failed"):
        river.fetch_river_levels(strict=True)
    witness.assert_not_called()
    assert river.fetch_river_levels(strict=False) == []
    witness.assert_not_called()


def test_stale_only_outage_keeps_existing_typed_witness_path(monkeypatch):
    prepare(monkeypatch, [row(0, "2026-10-22T12:00:00Z")])
    modeled = river.RiverReading(site_id=STATIONS[0][0], river=STATIONS[0][1], location=STATIONS[0][2],
                                gauge_height_ft=None, flood_stage_ft=None, above_flood=False,
                                date="2026-11-22", event_id="river_model_01111111_2026-11-22",
                                source_leg="open_meteo_flood")
    witness = Mock(return_value=[modeled])
    monkeypatch.setattr(river, "_fetch_open_meteo_flood", witness)
    assert river.fetch_river_levels(strict=True) == [modeled]
    witness.assert_called_once_with()


def test_submicrosecond_future_timestamp_is_not_rounded_back_to_clock(monkeypatch):
    prepare(monkeypatch, [row(0, "2026-11-22T05:00:00.000000001Z")])
    with pytest.raises(SourceFetchError, match="freshness check failed"):
        river._fetch_river_levels_primary(strict=True)


@pytest.mark.parametrize("offset", ["+00:60", "-00:60", "+00:99", "-00:99", "+24:00", "-24:00"])
def test_malformed_offset_cannot_be_normalized_into_a_flood_bundle(monkeypatch, offset):
    prepare(monkeypatch, [row(0, f"2026-11-21T05:00:00{offset}")])
    bundles = []
    with pytest.raises(SourceFetchError, match="freshness check failed"):
        readings = river._fetch_river_levels_primary(strict=True)
        bundles.extend(build_river_flood_bundle(event) for event in river.detect_floods(readings))
    assert bundles == []


@pytest.mark.parametrize("offset,day", [("+23:59", "2026-11-20"), ("-23:59", "2026-11-22")])
def test_valid_numeric_offset_boundary_retains_actual_utc_day(monkeypatch, offset, day):
    prepare(monkeypatch, [row(0, f"2026-11-21T05:00:00{offset}")])
    reading, = river._fetch_river_levels_primary(strict=True)
    assert reading.date == day
