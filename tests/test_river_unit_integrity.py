"""Invented primary responses through acquisition, flood detection and writer input.

No weather/model/platform request or approval. These expose unit mistakes in
the legacy manual river path; they do not qualify its separate datum/QC/identity.
"""
from copy import deepcopy
from datetime import UTC, datetime
from unittest.mock import Mock

from freezegun import freeze_time
import pytest
import responses

from src.data import river_gauges as river
from src.data.source_status import SourceFetchError
from src.two_bot.intern import build_river_flood_bundle

NOW = datetime(2026, 11, 22, 5, tzinfo=UTC)
STATIONS = [("01111111", "Invented River A", "Invented place A"),
            ("02222222", "Invented River B", "Invented place B")]


def gauge(site, *, unit="ft", code="00065", height="35.5"):
    return {"sourceInfo": {"siteCode": [{"value": site}]},
            "variable": {"variableCode": [{"value": code}], "unit": {"unitCode": unit}},
            "values": [{"value": [{"value": height, "dateTime": "2026-11-22T04:00:00Z"}]}]}


def threshold(*, unit="ft", stage=30):
    return {"flood": {"stageUnits": unit, "categories": {"minor": {"stage": stage}}}}


def install(monkeypatch, rows, thresholds):
    monkeypatch.setattr(river, "MAJOR_STATIONS", STATIONS[:len(thresholds)])
    responses.add(responses.GET, river.USGS_URL, json={"value": {"timeSeries": rows}})
    for (site, _, _), payload in zip(STATIONS, thresholds, strict=False):
        responses.add(responses.GET, river.FLOOD_URL.format(site_id=site), json=payload)
    forbidden_witness = Mock(side_effect=AssertionError("Integrity failure must not buy model fallback"))
    monkeypatch.setattr(river, "_fetch_open_meteo_flood", forbidden_witness)
    return forbidden_witness


@responses.activate
def test_explicit_feet_reach_the_real_flood_and_writer_consumers(monkeypatch):
    witness = install(monkeypatch, [gauge(STATIONS[0][0])], [threshold()])
    with freeze_time(NOW):
        readings = river.fetch_river_levels(strict=True)
    [event] = river.detect_floods(readings)
    bundle = build_river_flood_bundle(event)
    assert event.gauge_height_ft == 35.5 and event.flood_stage_ft == 30 and event.above_by_ft == 5.5
    assert event.date == bundle.when == "2026-11-22"
    assert bundle.headline_metric["value"] == 5.5
    assert len(responses.calls) == 2
    witness.assert_not_called()


@pytest.mark.parametrize("unit", ["m", None, "", "feet", "FT", True])
@responses.activate
def test_threshold_without_explicit_feet_cannot_create_the_false_exceedance(monkeypatch, unit):
    # 35.5ft is BELOW 30m, while the old reader declares it 5.5ft ABOVE.
    witness = install(monkeypatch, [gauge(STATIONS[0][0])], [threshold(unit=unit)])
    with freeze_time(NOW), pytest.raises(SourceFetchError, match="schema|unit"):
        river.fetch_river_levels(strict=True)
    witness.assert_not_called()
    assert len(responses.calls) == 2


@pytest.mark.parametrize("stage", [float("nan"), float("inf"), float("-inf"), "NaN", "1e999"])
def test_nonfinite_thresholds_are_integrity_failures(stage):
    with pytest.raises(SourceFetchError, match="schema|stage"):
        river._parse_nwps_minor_flood_stage(threshold(stage=stage), STATIONS[0][0])


@pytest.mark.parametrize("stage", [None, "", -9999, "-9999"])
def test_declared_absence_remains_unknown_instead_of_becoming_zero(stage):
    assert river._parse_nwps_minor_flood_stage(threshold(stage=stage), STATIONS[0][0]) is None


@responses.activate
def test_absent_threshold_cannot_turn_a_valid_height_into_a_flood(monkeypatch):
    witness = install(monkeypatch, [gauge(STATIONS[0][0])], [threshold(unit=None, stage=None)])
    with freeze_time(NOW):
        [reading] = river.fetch_river_levels(strict=True)
    assert reading.gauge_height_ft == 35.5 and reading.flood_stage_ft is None
    assert not reading.above_flood and river.detect_floods([reading]) == []
    witness.assert_not_called()


@pytest.mark.parametrize("change", ["metres", "discharge", "missing-variable", "missing-unit", "wrong-code"])
@responses.activate
def test_one_valid_peer_cannot_qualify_another_quantity_or_unit(monkeypatch, change):
    wrong = gauge(STATIONS[0][0])
    if change == "metres":
        wrong["variable"]["unit"]["unitCode"] = "m"
    elif change == "discharge":
        wrong["variable"].update(variableCode=[{"value": "00060"}], unit={"unitCode": "ft3/s"})
    elif change == "missing-variable":
        wrong.pop("variable")
    elif change == "missing-unit":
        wrong["variable"].pop("unit")
    else:
        wrong["variable"]["variableCode"] = [{"value": "00060"}]
    witness = install(monkeypatch, [wrong, gauge(STATIONS[1][0])], [threshold(), threshold()])
    with freeze_time(NOW):
        readings = river.fetch_river_levels(strict=True)
    assert [r.site_id for r in readings] == [STATIONS[1][0]]
    [event] = river.detect_floods(readings)
    assert event.event_id == "flood_02222222_2026-11-22"
    assert build_river_flood_bundle(event).event_id == event.event_id
    witness.assert_not_called()
    assert len(responses.calls) == 3


@responses.activate
def test_all_wrong_quantities_fail_explicitly_without_outage_substitution(monkeypatch):
    witness = install(monkeypatch, [gauge(STATIONS[0][0], code="00060", unit="ft3/s")], [threshold()])
    with freeze_time(NOW), pytest.raises(SourceFetchError, match="schema|unit|quantity"):
        river.fetch_river_levels(strict=True)
    witness.assert_not_called()


@responses.activate
def test_primary_parser_does_not_edit_the_source_response(monkeypatch):
    row, meta = gauge(STATIONS[0][0]), threshold()
    before = deepcopy((row, meta))
    install(monkeypatch, [row], [meta])
    with freeze_time(NOW):
        assert len(river.fetch_river_levels(strict=True)) == 1
    assert (row, meta) == before
