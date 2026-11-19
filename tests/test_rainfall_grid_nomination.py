"""Free joint nomination, wording and retained cell identity across schemas."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import timedelta
import json

import pytest

from src.data import gpm_imerg as gpm, rainfall_grid as grid, rainfall_observed as report
from tests.test_rainfall_grid_contract import evidence  # noqa: F401
from tests.test_rainfall_observed_report import NOW, enabled  # noqa: F401
from tests.test_rainfall_grid_pipeline import COPY


def test_grid_packet_dispatch_and_one_cell_copy_floor_share_existing_automatic_contract(evidence, enabled):  # noqa: F811
    bundle = report.build_bundle(evidence, now=NOW)
    assert report.validate_bundle(bundle, now=NOW) == evidence
    assert report.current_bundle_hold(bundle, now=NOW) is None
    assert report.claim_failures(COPY + "\n" + report.SOURCE_URL, bundle, now=NOW) == []
    assert report.current_bundle_hold(bundle, now=NOW, minimum_delay=timedelta(hours=20)) == "rainfall_source_insufficient_window"
    assert len(json.dumps(bundle.to_dict()).encode()) < 32768


@pytest.mark.parametrize("before,after,reason", [
    ("one grid cell", "Brazil nationwide", "rainfall_point_scope_required"),
    ("190.5 mm", "200 mm", "rainfall_amount_changed"),
    ("15 Nov", "14 Nov", "rainfall_date_required"),
    ("Brazil", "France", "rainfall_country_required"),
    ("24 hours", "12 hours", "rainfall_daily_window_required"),
    ("water-equivalent precipitation", "rainfall", "rainfall_quantity_label_required"),
    ("satellites estimate", "gauges measured", "rainfall_satellite_estimate_label_required"),
])
def test_wrong_claim_refuses_in_real_shared_wording_consumer(evidence, before, after, reason):  # noqa: F811
    bundle = grid.build_bundle(evidence, now=NOW)
    assert report.claim_failures(COPY.replace(before, after) + "\n" + report.SOURCE_URL, bundle, now=NOW) == [reason]


@pytest.mark.parametrize("claim", ["a national record", "caused flooding", "a month's worth", "the heaviest ever",
                                  "a forecast", "snow", "a country average"])
def test_grid_copy_cannot_promote_estimate_into_area_record_impact_phase_or_forecast(evidence, claim):  # noqa: F811
    bundle = grid.build_bundle(evidence, now=NOW)
    assert report.claim_failures(COPY + f" — {claim}.\n" + report.SOURCE_URL, bundle, now=NOW) == ["rainfall_unsupported_claim"]


def test_metadata_cannot_drop_family_boundary_when_outer_kind_and_id_are_relabelled(evidence):  # noqa: F811
    payload = grid.build_bundle(evidence, now=NOW).to_dict()
    payload.update(event_id="foreign", signal_kind="all_time_high")
    payload["raw_signal_dump"].pop("report_schema")
    assert report.is_family(payload)
    assert report.claim_failures(COPY, payload, now=NOW) == ["rainfall_text_source_invalid"]


def test_slate_is_order_invariant_capped_and_not_an_episode_or_global_maximum(evidence, fresh_state):  # noqa: F811
    proofs = [dict(evidence, column=column, mm_per_day=amount) for column, amount in
              [(1299, 190.5), (1289, 180), (1279, 170), (1269, 160)]]
    first = report.nominate([], fresh_state, now=NOW, grid_evidence=proofs)
    assert len(first) == 3
    assert [row.headline_metric["value"] for row in first] == [190.5, 180, 170]
    assert [row.to_dict() for row in report.nominate([], fresh_state, now=NOW, grid_evidence=reversed(proofs))] == [row.to_dict() for row in first]


@pytest.mark.parametrize("field,value", [("source_file_sha256", "2" * 64), ("valid_half_hours", 47),
                                        ("mm_per_day", 149), ("mm_per_day", 191)])
def test_conflicting_grid_copies_hold_both_orders_before_one_can_win(evidence, fresh_state, field, value):  # noqa: F811
    conflict = dict(evidence, **{field: value})
    for proofs in ([evidence, conflict], [conflict, evidence]):
        assert report.nominate([], fresh_state, now=NOW, grid_evidence=proofs) == []


def test_identical_grid_copies_collapse_once_and_distinct_cells_stay_distinct(evidence, fresh_state):  # noqa: F811
    assert len(report.nominate([], fresh_state, now=NOW, grid_evidence=[evidence, deepcopy(evidence)])) == 1
    assert len(report.nominate([], fresh_state, now=NOW, grid_evidence=[evidence, dict(evidence, column=1298)])) == 2


def _same_cell_as(reading, proof):
    return dict(proof, column=gpm._lon_index(reading.lon), row=gpm._lat_index(reading.lat), mm_per_day=reading.mm_total)


def _inland_reading():
    row = next(row for row in gpm.load_cities() if row["city"] == "Brasilia")
    key = gpm.places.event_location_key(row["city"], row["country"], row["lat"], row["lon"])
    return gpm.CityPrecipReading(row["city"], row["country"], float(row["lat"]), float(row["lon"]),
                                "2026-11-15", 180.5, "late", f"gpm_imerg_{key}_2026-11-15")


def test_equal_city_and_grid_readings_nominate_one_proved_cell(evidence, fresh_state):  # noqa: F811
    reading = _inland_reading()
    proof = _same_cell_as(reading, evidence)
    rows = report.nominate([reading], fresh_state, now=NOW, grid_evidence=[proof])
    assert len(rows) == 1 and grid.is_family(rows[0])


def test_disagreement_between_valid_city_and_incomplete_grid_holds_both(evidence, fresh_state):  # noqa: F811
    reading = _inland_reading()
    proof = dict(_same_cell_as(reading, evidence), mm_per_day=149)
    assert report.nominate([reading], fresh_state, now=NOW, grid_evidence=[proof]) == []


def test_city_copy_cannot_bypass_conflicting_grid_file_identities_with_equal_values(evidence, fresh_state):  # noqa: F811
    reading = _inland_reading()
    proof = _same_cell_as(reading, evidence)
    other = dict(proof, source_file_sha256="2" * 64)
    for copies in ([proof, other], [other, proof]):
        assert report.nominate([reading], fresh_state, now=NOW, grid_evidence=copies) == []


def test_legacy_daily_packet_uses_retained_coordinates_but_never_a_country_centroid(evidence, fresh_state):  # noqa: F811
    from src.two_bot.intern import build_precipitation_bundle

    reading = _inland_reading()
    event = gpm.PrecipExtremeEvent(kind="daily_record", location=reading.city, country=reading.country,
        date=reading.date, mm_total=reading.mm_total, period_days=1, deviation_from_record_mm=30,
        previous_record_mm=150, previous_record_year=2024, lat=reading.lat, lon=reading.lon,
        event_id="invented-legacy-daily", city_count=1, sample_cities=[], product_code="late")
    old = build_precipitation_bundle(event)
    cell = grid.build_bundle(_same_cell_as(reading, evidence), now=NOW)
    fresh_state["drafts"].append({"event_id": old.event_id, "status": "unknown",
                                 "review_context": {"two_bot": {"bundle": old.to_dict()}}})
    assert report.legacy_point_day_hold(cell, fresh_state) == "rainfall_same_cell_day_held"
    old.raw_signal_dump["kind"] = "country_precip_event"
    fresh_state["drafts"][0]["review_context"]["two_bot"]["bundle"] = old.to_dict()
    assert report.legacy_point_day_hold(cell, fresh_state) is None


@pytest.mark.parametrize("direction", ["city-to-grid", "grid-to-city"])
@pytest.mark.parametrize("status", ["pending", "posted", "failed", "unknown"])
def test_saved_coordinates_hold_cross_schema_duplicates_even_without_a_confirmed_send(evidence, fresh_state, direction, status):  # noqa: F811
    reading = _inland_reading()
    city = report.build_bundle(report.evidence_for(reading, now=NOW), now=NOW)
    cell = grid.build_bundle(_same_cell_as(reading, evidence), now=NOW)
    old, new = (city, cell) if direction == "city-to-grid" else (cell, city)
    fresh_state["drafts"].append({"event_id": old.event_id, "status": status,
                                 "review_context": {"two_bot": {"bundle": old.to_dict()}}})
    assert report.legacy_point_day_hold(new, fresh_state) == "rainfall_same_cell_day_held"
    assert report.nominate([reading] if direction == "grid-to-city" else [], fresh_state, now=NOW,
                           grid_evidence=[] if direction == "grid-to-city" else [_same_cell_as(reading, evidence)]) == []


def test_sealed_retained_grid_validation_has_geography_but_no_live_collector_import(evidence, tmp_path):  # noqa: F811
    from pathlib import Path
    import subprocess
    import sys
    from scripts.gen_dashboard_graphic_runtime import generate

    archive, _manifest = generate()
    path = tmp_path / "runtime.zip"
    path.write_bytes(archive)
    code = '''
import importlib.abc, json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
class RefuseLive(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"src.data.gpm_imerg", "src.data.rainfall_grid_scan", "h5py", "numpy"}:
            raise AssertionError("live collector dependency in retained package")
sys.meta_path.insert(0, RefuseLive())
from src.data import rainfall_observed as report
data = json.load(sys.stdin)
now = datetime.fromisoformat(data["now"])
assert report.validate_bundle(data["bundle"], now=now) == data["evidence"]
assert report.claim_failures(data["text"], data["bundle"], now=now) == []
'''
    bundle = grid.build_bundle(evidence, now=NOW)
    result = subprocess.run([sys.executable, "-I", "-c", code, str(path)], cwd=tmp_path,
                            input=json.dumps({"bundle": bundle.to_dict(), "evidence": evidence,
                                              "text": COPY + "\n" + report.SOURCE_URL, "now": NOW.isoformat()}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
