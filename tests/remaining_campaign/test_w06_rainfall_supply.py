"""W06: rainfall window/footprint through the real GPM runner, pipeline floor and offline tools.

Invented readings, granules, gauges and coverage rows only. No source call, no
rainfall activation; model stages are offline fakes, the real local check runs.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.data import rainfall_supply as rs
from src.data.gpm_imerg import CityPrecipReading, PrecipExtremeEvent
from src.orchestrator.sources import gpm_imerg as gpm_runner
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.intern import build_precipitation_bundle
from tests.live_content_harness import trap_network
from tests.nhc_advisory_pipeline_helpers import stage_fakes

ROOT = Path(__file__).resolve().parents[2]
CELL_COPY = "Satellite estimates put 75 mm of rain on Lyon in the 24 hours to midnight UTC, NASA's IMERG shows."
NATIONAL_COPY = "France saw 75 mm of rain nationwide in 24 hours, NASA's IMERG shows."


def _event(**change) -> PrecipExtremeEvent:
    base: dict = dict(kind="daily_record", location="Lyon", country="France", date="2026-10-28", mm_total=75.0,
                period_days=1, deviation_from_record_mm=30.0, previous_record_mm=45.0, previous_record_year=2024,
                lat=45.75, lon=4.85, city_count=None, sample_cities=[], event_id="gpm_precip_record_invented_2026-10-28")
    base.update(change)
    return PrecipExtremeEvent(**base)


# --- 06.1 window/footprint contract ----------------------------------------------------
def test_window_and_footprint_are_explicit_and_mixed_windows_refuse():
    window = rs.window_evidence(_event(period_days=3))
    assert (window["accumulation_start"], window["accumulation_end"]) == ("2026-10-26T00:00:00Z", "2026-10-29T00:00:00Z")
    assert window["integration_interval_hours"] == 72 and window["footprint"]["kind"] == "grid_cell"
    assert window["retrieved_at"] is None and window["retrieved_at_known"] is False and rs.window_failures(window) == []
    country = rs.window_evidence(_event(kind="country_precip_event", city_count=12))
    assert country["footprint"]["kind"] == "heaviest_member_cell"
    model = rs.window_evidence(_event(source_leg="open_meteo"))
    assert model["evidence_type"] == "model_fallback" and model["product_version"] is None
    with pytest.raises(ValueError, match="rainfall_mixed_windows"):
        rs.combine_windows([window, rs.window_evidence(_event())])
    with pytest.raises(ValueError, match="rainfall_mixed_evidence_types"):
        rs.combine_windows([rs.window_evidence(_event()), model])
    broken = {**window, "integration_interval_hours": 24}
    assert rs.window_failures(broken) == ["integration_interval_inconsistent"]


def test_claim_floor_refuses_national_total_and_gauge_wording():
    bundle = build_precipitation_bundle(_event(kind="country_precip_event", city_count=12, location="France"))
    assert any("not a national total" in f for f in rs.rainfall_claim_failures(NATIONAL_COPY, bundle))
    assert any("not a gauge" in f for f in rs.rainfall_claim_failures("Rain gauges measured 75 mm.", bundle))
    cell = build_precipitation_bundle(_event())
    assert rs.rainfall_claim_failures(CELL_COPY, cell) == []
    facts = {row["label"]: row["value"] for row in cell.current_facts}
    assert facts["accumulation_window_utc"] == "2026-10-28T00:00:00Z to 2026-10-29T00:00:00Z"
    assert "retrieved_at" not in facts  # unknown stays absent, never invented


# --- 06.6 supplied-source journey to the real check / held path ----------------------
@pytest.fixture
def offline(monkeypatch):
    trap_network(monkeypatch.setattr)
    for name, value in (("ANTHROPIC_API_KEY", "invented-no-provider-access"),
                        ("GEMINI_API_KEY", "invented-no-provider-access"), ("THEHEAT_WRITER_SAMPLES", "1"),
                        ("THEHEAT_CRITIC_REVISE_ENABLED", "0"), ("THEHEAT_CRITIC_ENABLED", "1"),
                        ("THEHEAT_TRIAGE_ENABLED", "0")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
    monkeypatch.delenv("THEHEAT_PRODUCTION_PAUSED", raising=False)
    return monkeypatch


def _journey(patch, copy: str):
    reading = CityPrecipReading(city="Lyon", country="France", lat=45.75, lon=4.85, date="2026-10-28",
                                mm_total=75.0, source_product="late", event_id="gpm_imerg_invented_lyon_2026-10-28")
    patch.setattr(gpm_runner.gpm_imerg, "fetch_daily_precip", lambda **_k: [reading])
    sent: list[str] = []
    writer, safety, fact, critic = stage_fakes(sent, copy=copy)
    patch.setattr(pipeline.writer, "write_tweet", writer)
    patch.setattr(pipeline, "run_safety_pipeline", safety)
    patch.setattr(pipeline.fact_check, "fact_check", fact)
    patch.setattr(pipeline.critic, "critic_review", critic)
    from src.data import places
    state = deepcopy(DEFAULT_STATE)
    state["precip_daily_records"] = {"precip:late:" + places.event_location_key("Lyon", "France", 45.75, 4.85)
                                     + ":10-28": {"mm": 40.0, "year": 2024}}
    run: dict = {"id": "invented-run-w06", "started_at": "2026-10-29T06:00:00Z", "sources": []}
    with redirect_stdout(io.StringIO()) as out:
        gpm_runner.run_gpm_imerg(state, run, [{"city": "Lyon", "country": "France", "lat": "45.75", "lon": "4.85"}])
        _drain_and_write_triage_queue(state, run)
    return state, sent, out.getvalue()


def test_complete_packet_reaches_the_held_manual_path_and_the_real_floor_refuses_national_wording(offline):
    # Flag off (today): the complete packet is still withheld at admission for missing provenance.
    state, sent, _ = _journey(offline, CELL_COPY)
    assert sent == [] and state["suppressions"][-1]["stage"] == "evidence_contract"
    offline.setenv("THEHEAT_RAINFALL_WINDOW_PROVENANCE", "1")
    state, sent, _ = _journey(offline, CELL_COPY)
    drafts = [d for d in state["drafts"] if (d.get("review_context") or {}).get("source_key") == "gpm_imerg"]
    assert drafts and drafts[0]["status"] == "pending" and "writer" in sent
    window = drafts[0]["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["rainfall_window"]
    assert window["footprint"]["kind"] == "grid_cell"
    state, sent, _ = _journey(offline, NATIONAL_COPY)
    assert not [d for d in state["drafts"] if (d.get("review_context") or {}).get("source_key") == "gpm_imerg"]
    assert sent == ["writer"]  # stopped at the real local floor before safety/fact/critic


def test_incomplete_packet_stops_before_paid_generation(offline):
    offline.setenv("THEHEAT_RAINFALL_WINDOW_PROVENANCE", "1")
    offline.setattr(rs, "window_evidence", lambda event, **_k: {"schema": rs.WINDOW_SCHEMA, "unit": "mm"})
    state, sent, out = _journey(offline, CELL_COPY)
    assert sent == [] and "rainfall packet incomplete" in out
    assert not state["drafts"]


# --- 06.2 bounded regional scan ----------------------------------------------------------
def test_failed_region_advances_cursor_and_limits_hold():
    regions = ["basin-a", "basin-b", "basin-c", "basin-d"]

    def fetch(region):
        if region == "basin-b":
            raise TimeoutError("invented")
        return {"outcome": "qualified", "readings": 3}
    first = rs.scan_regions(regions, fetch, cursor=0, max_regions=2, max_calls=10, deadline_s=60)
    assert [a["outcome"] for a in first["attempts"]] == ["qualified", "failed"] and first["next_cursor"] == 2
    history = [{"started_at": "2026-10-28T06:00:00Z", "sources": [{"source": "gpm_imerg",
                                                                   "details": {"rainfall_scan": first}}]}]
    cursor = rs.cursor_from_history(history, "gpm_imerg", regions)
    second = rs.scan_regions(regions, fetch, cursor=cursor, max_regions=2, max_calls=1, deadline_s=60)
    assert [a["region"] for a in second["attempts"]] == ["basin-c", "basin-d"]
    assert second["attempts"][1]["outcome"] == "not_attempted_limit" and second["next_cursor"] == 3
    history.insert(0, {"started_at": "2026-10-29T06:00:00Z", "sources": [{"source": "gpm_imerg",
                                                                          "details": {"rainfall_scan": second}}]})
    ages = rs.revisit_ages(history, "gpm_imerg", regions, today=date(2026, 10, 30))
    assert ages == {"basin-a": 2, "basin-b": 2, "basin-c": 1, "basin-d": None}
    assert rs.cursor_from_history(history, "gpm_imerg", regions[:3]) == 0  # another region set never borrows


# --- 06.3 reconciliation / 06.4 pilots / 06.5 evidence separation -------------------------
GRANULES = [{"product": "IMERG Late daily (3IMERGDL)", "version": "V07", "start": "2026-10-28T00:00:00Z",
             "end": "2026-10-29T00:00:00Z", "cell_center": [10.05, 20.05], "resolution_deg": 0.1, "mm": 40.0}]
GAUGES = [
    {"gauge_id": "G1", "lat": 10.07, "lon": 20.02, "start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z",
     "mm": 37.0, "qc": "accepted"},
    {"gauge_id": "G2", "lat": 10.07, "lon": 20.02, "start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z",
     "mm": 80.0, "qc": "accepted"},
    {"gauge_id": "G3", "lat": 11.5, "lon": 20.0, "start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z",
     "mm": 5.0, "qc": ""},
    {"gauge_id": "G4", "lat": 10.07, "lon": 20.02, "start": "2026-10-28T06:00:00Z", "end": "2026-10-29T06:00:00Z",
     "mm": 39.0, "qc": "accepted"},
    {"gauge_id": "G5", "lat": 10.07, "lon": 20.02, "start": "2026-10-28T00:00:00Z", "end": "2026-10-29T00:00:00Z",
     "mm": 39.0, "qc": "suspect"},
]


def _cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/rainfall_supply.py"), *args], capture_output=True,
                          text=True, cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, timeout=60, check=False)


def test_reconciliation_keeps_every_mismatch_and_the_barrow_limit(tmp_path):
    (tmp_path / "g.json").write_text(json.dumps(GRANULES))
    (tmp_path / "k.json").write_text(json.dumps(GAUGES))
    result = _cli("reconcile", "--granules", str(tmp_path / "g.json"), "--gauges", str(tmp_path / "k.json"))
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert {r["gauge_id"]: r["outcome"] for r in out["rows"]} == {
        "G1": "agree", "G2": "conflict", "G3": "footprint_unmatched", "G4": "window_unmatched", "G5": "qc_excluded"}
    assert "barrow_original_imerg_granules_missing" in out["historical_limits"]


def test_pilots_expose_gaps_without_recall(tmp_path):
    rows: list[dict] = [{"region": "basin-x", "hazard": "flood_basin", "reference_denominator": 12, "qualified_sources": 0},
            {"region": "basin-y", "hazard": "flood_basin", "reference_denominator": None},
            {"region": "steppe", "hazard": "smoke_aq", "reference_denominator": 4, "qualified_sources": 2},
            {"region": "coast", "hazard": "storm_surge_pilot"}]
    result = rs.select_pilots(rows, max_pilots=2, supplied_plan=["basin-y:flood_basin"])
    assert result["selected"] == ["basin-x:flood_basin", "steppe:smoke_aq"] and result["recall"] is None
    assert {g["key"]: g["gap"] for g in result["gaps"]} == {
        "basin-y:flood_basin": "no_qualified_reference_denominator", "coast:storm_surge_pilot": "no_registered_adapter"}
    planned = rs.select_pilots(rows, max_pilots=3, supplied_plan=["basin-y:flood_basin"])
    assert planned["selected"][-1] == "basin-y:flood_basin"
    (tmp_path / "c.json").write_text(json.dumps(rows))
    assert _cli("pilots", "--coverage", str(tmp_path / "c.json"), "--max", "2").returncode == 1


def test_physical_evidence_types_corroborate_only_their_own_claims():
    window = ["2026-10-28T00:00:00Z", "2026-10-29T00:00:00Z"]
    fire = {"evidence_type": "thermal_detection", "place_id": "ux1", "window": window}
    assert rs.corroboration({"claim_kind": "vegetation_fire", "place_id": "ux1", "window": window}, fire) == {
        "corroborates": False, "reason": "detection_confidence_is_not_vegetation_classification"}
    assert rs.corroboration({"claim_kind": "active_fire_detection", "place_id": "ux1", "window": window},
                            fire)["corroborates"] is True
    pm10 = {"evidence_type": "measured_exposure", "place_id": "ux1", "window": window}
    assert rs.corroboration({"claim_kind": "smoke_cause", "place_id": "ux1", "window": window}, pm10)["reason"] \
        == "co_reporting_is_not_causation"
    flood = {"claim_kind": "flood_occurring", "place_id": "ux2", "window": window}
    assert rs.corroboration(flood, {"evidence_type": "satellite_derived", "place_id": "ux2", "window": window})[
        "corroborates"] is False
    other_day = ["2026-10-30T00:00:00Z", "2026-10-31T00:00:00Z"]
    assert rs.corroboration(flood, {"evidence_type": "official_flood_report", "place_id": "ux2",
                                    "window": other_day})["reason"] == "window_mismatch"
    rain = {"claim_kind": "heavy_rain_amount", "place_id": "ux2", "window": window, "value": 100, "direction": "at_least"}
    assert rs.corroboration(rain, {"evidence_type": "gauge_observed", "place_id": "ux2", "window": window,
                                   "value": 60})["reason"] == "conflict_visible"


def test_readiness_rows_come_from_retained_scan_details(tmp_path):
    scan = rs.scan_regions(["r1", "r2"], lambda r: {"outcome": "qualified"} if r == "r1" else
                           {"outcome": "access_hold", "hold": "granules_unavailable"},
                           cursor=0, max_regions=2, max_calls=4, deadline_s=60)
    state = {"run_history": [{"started_at": "2026-10-29T06:00:00Z",
                              "sources": [{"source": "gpm_imerg", "details": {"rainfall_scan": scan}}]}]}
    (tmp_path / "s.json").write_text(json.dumps(state))
    out = _cli("readiness", "--state", str(tmp_path / "s.json"))
    assert out.returncode == 1
    rows = {r["region"]: r for r in json.loads(out.stdout)["rows"]}
    assert rows["r2"]["hold"] == "granules_unavailable" and rows["r1"]["outcome"] == "qualified"
