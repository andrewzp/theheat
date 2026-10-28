"""Actual rainfall-opportunity trace and offline audit (P09a/P19).

Every source response here is an invented fixture served by `responses`; the real
selector, grid walkback, OPeNDAP fan-out and model-witness paths run unchanged.
"""

from datetime import date, timedelta
import copy
import json
from random import Random
import re
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse

import pytest
import responses

from src.data import gpm_imerg as gpm
from src.evaluation import rainfall_opportunity as audit
from tests.test_gpm_imerg import _make_grid_bytes

DAY = date(2026, 6, 5)
_DATE = re.compile(r"3IMERG\.(\d{8})-")
_CELL = re.compile(r"precipitation\[0:1:0\]\[(\d+):1:\d+\]\[(\d+):1:\d+\]")


def population(count, *, label="Rain"):
    return [dict(city=f"{label} {i}", country="Testland", lat=round(-40 + i * 0.37, 2), lon=10 + (i % 7))
            for i in range(count)]


def cell(row):
    return gpm._lon_index(float(row["lon"])), gpm._lat_index(float(row["lat"]))


class Transport:
    """Invented GES DISC / Open-Meteo responses keyed by date and grid cell."""

    def __init__(self, rows, *, grid_dates=(), grid_status=None, probe_published=(), point=None, witness=None):
        self.rows = rows
        self.grid_dates = {d.strftime("%Y%m%d") for d in grid_dates}
        self.grid_status = grid_status
        self.probe_published = {d.strftime("%Y%m%d") for d in probe_published}
        self.point = point or {}  # row index -> mm, None (fill) or "fail"
        self.witness = witness or {}  # row index -> (forecast_mm, agrees)
        self.by_cell = {cell(row): index for index, row in enumerate(rows)}
        self.by_point = {(float(row["lat"]), float(row["lon"])): index for index, row in enumerate(rows)}

    def install(self):
        responses.add_callback(responses.GET, re.compile(r"https://data\.gesdisc\.earthdata\.nasa\.gov/.*"),
                               callback=self._grid)
        responses.add_callback(responses.GET, re.compile(r"https://gpm1\.gesdisc\.eosdis\.nasa\.gov/.*"),
                               callback=self._opendap)
        responses.add_callback(responses.GET, re.compile(r"https://api\.open-meteo\.com/.*"), callback=self._forecast)
        responses.add_callback(responses.GET, re.compile(r"https://ensemble-api\.open-meteo\.com/.*"),
                               callback=self._ensemble)

    def _grid(self, request):
        if self.grid_status:
            return self.grid_status, {}, b"invented outage"
        day = _DATE.search(request.url).group(1)
        if day not in self.grid_dates:
            return 404, {}, b"not published"
        # A fill cell is a missing value; untouched cells would read as 0.0 mm.
        values = {(0, *cell(row)): gpm.FILL_VALUE if self.point.get(index, 0) in (None, "fail") else 25.0 + index
                  for index, row in enumerate(self.rows)}
        return 200, {}, _make_grid_bytes(values)

    def _opendap(self, request):
        day = _DATE.search(request.url).group(1)
        lon_index, lat_index = map(int, _CELL.search(unquote(request.url)).groups())
        index = self.by_cell.get((lon_index, lat_index))
        if index is None:  # date-availability probe at the reference cell
            return (200, {}, "Dataset\nprecipitation[0][0][0], 0.0\n") if day in self.probe_published else (404, {}, "")
        value = self.point.get(index, 25.0 + index)
        if value == "fail":
            return 500, {}, "invented server error"
        shown = -9999.9 if value is None else value
        return 200, {}, f"Dataset\n---\nprecipitation[0][{lon_index}][{lat_index}], {shown}\n"

    def _query_index(self, request):
        query = parse_qs(urlparse(request.url).query)
        return self.by_point[(float(query["latitude"][0]), float(query["longitude"][0]))]

    def _forecast(self, request):
        value, _agrees = self.witness.get(self._query_index(request), (5.0, True))
        return 200, {}, json.dumps({"daily": {"precipitation_sum": [value]}})

    def _ensemble(self, request):
        value, agrees = self.witness.get(self._query_index(request), (5.0, True))
        member = value if agrees else value + 500.0
        daily = {"time": ["x"], **{f"precipitation_sum_member01_{model}": [member] for model in gpm._OPEN_METEO_MODELS}}
        return 200, {}, json.dumps({"daily": daily})


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setenv("EARTHDATA_TOKEN", "fixture-not-a-secret")
    monkeypatch.setenv("GPM_IMERG_RETRY_BACKOFF_S", "0")
    monkeypatch.delenv("GPM_IMERG_MAX_LOOKBACK_DAYS", raising=False)
    # The walkback starts from the local calendar; pin it to the fixture's UTC day.
    monkeypatch.setattr(gpm, "_default_start_date", lambda: DAY - timedelta(days=1))
    return monkeypatch


def traced(rows, **kwargs):
    trace = gpm.RainfallOpportunityTrace(run_id=kwargs.pop("run_id", "run_alerts_20260605T120000Z"))
    readings = gpm.fetch_daily_precip(rows, today=DAY, strict=True, trace=trace, **kwargs)
    return readings, json.loads(json.dumps(trace.export()))


@responses.activate
def test_grid_trace_records_whole_population_download_walkback_and_reading_members(clean_env):
    clean_env.setenv("THEHEAT_GPM_SOURCE", "datapool")
    rows = population(90)
    Transport(rows, grid_dates=[DAY - timedelta(days=2)], point={4: None}).install()
    readings, trace = traced(rows)
    assert len(readings) == 89 and len(responses.calls) == 2
    assert trace["trace_status"] == "complete" and trace["outcome"] == "primary_served"
    assert trace["serving_leg"] == "imerg_late_grid_datapool" and trace["selection_date_utc"] == "2026-06-05"
    (leg,) = trace["legs"]
    assert leg["population_semantics"] == "whole_population_one_download"
    assert [c["outcome"] for c in leg["candidates"]] == ["not_found", "downloaded"]
    assert (leg["walkback_start_date"], leg["data_date"]) == ("2026-06-04", "2026-06-03")
    assert (leg["readings"], leg["missing_values"]) == (89, 1)
    assert trace["request_counts"]["grid_downloads"] == 2
    assert trace["request_counts"]["http_requests"] == {"min": 2, "max": 2, "unmeasured_components": []}
    members = gpm.opportunity_population(rows)
    assert trace["population"] == {"basis": gpm.POPULATION_BASIS, "count": 90, "sha256": members["sha256"],
                                   "within_trace_bound": True}
    read = audit._bitmap_members(leg["reading_bitmap"], members["members"])
    assert read == {gpm._reading_key(r) for r in readings}
    assert {r.mm_total for r in readings} == {25.0 + i for i in range(90) if i != 4}
    text = json.dumps(trace)
    assert "fixture-not-a-secret" not in text and "://" not in text and "Bearer" not in text


@responses.activate
def test_grid_failure_falls_back_to_bounded_opendap_window_with_member_dispositions(clean_env):
    clean_env.setenv("THEHEAT_GPM_SOURCE", "datapool")
    rows = population(12)
    Transport(rows, grid_status=503, probe_published=[DAY - timedelta(days=2)],
              point={0: None, 1: "fail"}).install()
    readings, trace = traced(rows, max_cities=5, max_workers=1)
    grid, opendap = trace["legs"]
    assert (grid["outcome"], grid["reason"], grid["candidates"]) == (
        "unavailable", "transient", [{"date": "2026-06-04", "outcome": "transient"}])
    assert [p["outcome"] for p in opendap["date_probes"]] == ["not_found", "published"]
    assert opendap["data_date"] == "2026-06-03" and opendap["window_size"] == 5
    window = audit.window_members(gpm.opportunity_population(rows)["members"], DAY, 5)
    assert opendap["selection_sha256"] == audit._identity_sha256(window)
    keyed = {gpm.places.event_location_key(r["city"], r["country"], r["lat"], r["lon"]): i for i, r in enumerate(rows)}
    expected = "".join("u" if keyed[k] == 0 else "f" if keyed[k] == 1 else "r" for k in window)
    assert opendap["dispositions"] == expected and opendap["member_calls"] == 5
    assert len(readings) == expected.count("r") and trace["serving_leg"] == "imerg_late_opendap"
    assert opendap["failure_signatures"] == ({"HTTP 500": 1} if "f" in expected else {})
    bounds = trace["request_counts"]["http_requests"]
    assert bounds["min"] <= len(responses.calls) <= bounds["max"]
    assert trace["request_counts"]["grid_downloads"] == 1


@responses.activate
def test_witness_serving_is_recorded_as_model_witness_never_primary(clean_env):
    clean_env.setenv("THEHEAT_GPM_SOURCE", "opendap")
    rows = population(9)
    Transport(rows, probe_published=[DAY - timedelta(days=1)], point={i: "fail" for i in range(9)},
              witness={i: (30.0 + i, i % 3 != 0) for i in range(9)}).install()
    readings, trace = traced(rows, max_cities=6, max_workers=1)
    assert trace["outcome"] == "witness_served" and trace["serving_leg"] == "open_meteo_witness"
    assert all(r.source_leg == "open_meteo" for r in readings)
    opendap, witness = trace["legs"]
    assert opendap["dispositions"] == "fffnnn" and opendap["outcome"] == "not_finished"
    window = audit.window_members(gpm.opportunity_population(rows)["members"], DAY, 6)
    assert witness["selection_sha256"] == opendap["selection_sha256"] == audit._identity_sha256(window)
    assert witness["data_date"] == "2026-06-04" and set(witness["dispositions"]) <= {"r", "o"}
    assert witness["dispositions"].count("r") == len(readings)
    report = audit.evaluate([trace], [gpm.opportunity_population(rows)])
    assert report["opportunity_member_runs"]["fresh_primary"] == 0
    assert report["opportunity_member_runs"]["witness_model"] == len(readings)
    assert report["opportunity_member_runs"]["attempted"] == 6


@responses.activate
def test_runner_persists_trace_through_existing_details_and_evaluator_consumes_it(clean_env):
    from src.orchestrator.sources import gpm_imerg as runner
    from src.state import _fresh_state, init_run
    clean_env.setenv("THEHEAT_GPM_SOURCE", "datapool")
    rows = population(20)
    Transport(rows, grid_dates=[DAY - timedelta(days=1)]).install()
    clean_env.setattr(gpm, "datetime", _Clock)
    run = init_run("alerts")
    runner.run_gpm_imerg(_fresh_state(), run, rows)
    (entry,) = run["sources"]
    assert entry["source"] == "gpm_imerg" and entry["status"] == "success"
    trace = json.loads(json.dumps(entry["details"]["rainfall_opportunity"]))
    assert trace["run_id"] == run["id"] and trace["trace_status"] == "complete"
    assert len(json.dumps(trace)) < 4096  # bounded: no per-member list for the grid
    report = audit.evaluate([trace], [gpm.opportunity_population(rows)])
    (row,) = report["runs"]
    assert row["status"] == "counted" and row["reasons"] == []
    assert report["opportunity_member_runs"]["fresh_primary"] == 20


class _Clock:
    @staticmethod
    def now(tz):
        from datetime import datetime
        return datetime(2026, 6, 5, 12, tzinfo=tz)


def test_runner_records_skips_and_failures_with_trace_details(monkeypatch):
    from src.orchestrator.sources import gpm_imerg as runner
    from src.state import _fresh_state, init_run
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    monkeypatch.setattr(gpm, "_fetch_precip_open_meteo", lambda *a, **k: pytest.fail("skip must not use witness"))
    run = init_run("alerts")
    runner.run_gpm_imerg(_fresh_state(), run, population(3))
    trace = run["sources"][0]["details"]["rainfall_opportunity"]
    assert run["sources"][0]["status"] == "skipped"
    assert (trace["outcome"], trace["primary_gate"], trace["legs"]) == ("skipped", "credential_not_configured", [])
    monkeypatch.setenv("GPM_IMERG_MAX_CITIES", "0")
    run = init_run("alerts")
    runner.run_gpm_imerg(_fresh_state(), run, population(3))
    failed = run["sources"][0]
    assert failed["status"] == "failed"
    assert failed["details"]["rainfall_opportunity"]["incomplete_reasons"] == ["capture_not_started"]


@pytest.mark.parametrize("source,kwargs,transport", [
    ("datapool", {}, dict(grid_dates=[DAY - timedelta(days=1)])),
    ("datapool", {"max_cities": 7, "max_workers": 1},
     dict(grid_status=503, probe_published=[DAY - timedelta(days=1)], point={2: None, 3: "fail"})),
    ("opendap", {"max_cities": 6, "max_workers": 1},
     dict(probe_published=[DAY - timedelta(days=1)], point={i: "fail" for i in range(30)},
          witness={i: (40.0, i % 2 == 0) for i in range(30)})),
])
def test_trace_is_csv_order_invariant(clean_env, source, kwargs, transport):
    clean_env.setenv("THEHEAT_GPM_SOURCE", source)
    rows = population(30)
    shuffled = list(rows)
    Random(7).shuffle(shuffled)
    exports = []
    for order in (rows, shuffled, list(reversed(rows))):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
            _install(mock, rows, transport)
            readings, trace = traced(order, **kwargs)
            exports.append((sorted((r.event_id, r.mm_total) for r in readings), trace))
    assert exports[0] == exports[1] == exports[2]


def _install(mock, rows, transport):
    helper = Transport(rows, **transport)
    mock.add_callback(responses.GET, re.compile(r"https://data\.gesdisc\.earthdata\.nasa\.gov/.*"), callback=helper._grid)
    mock.add_callback(responses.GET, re.compile(r"https://gpm1\.gesdisc\.eosdis\.nasa\.gov/.*"), callback=helper._opendap)
    mock.add_callback(responses.GET, re.compile(r"https://api\.open-meteo\.com/.*"), callback=helper._forecast)
    mock.add_callback(responses.GET, re.compile(r"https://ensemble-api\.open-meteo\.com/.*"), callback=helper._ensemble)


@pytest.mark.parametrize("source,kwargs,transport", [
    ("datapool", {}, dict(grid_dates=[DAY - timedelta(days=3)], point={5: None})),
    ("datapool", {"max_cities": 8, "max_workers": 3},
     dict(grid_status=503, probe_published=[DAY - timedelta(days=1)], point={2: None, 3: "fail"})),
    ("opendap", {"max_cities": 6, "max_workers": 1},
     dict(probe_published=[DAY - timedelta(days=1)], point={i: "fail" for i in range(30)},
          witness={i: (80.0 + i, i % 2 == 0) for i in range(30)})),
])
def test_traced_and_untraced_fetches_are_identical_in_readings_events_and_requests(clean_env, source, kwargs,
                                                                                    transport):
    clean_env.setenv("THEHEAT_GPM_SOURCE", source)
    rows = population(30)
    results = []
    for with_trace in (False, True):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
            _install(mock, rows, transport)
            trace = gpm.RainfallOpportunityTrace(run_id="run_x") if with_trace else None
            readings = gpm.fetch_daily_precip(rows, today=DAY, strict=True, trace=trace, **kwargs)
            state = {"precip_daily_records": {gpm._daily_record_key(r): {"mm": 0.5, "year": 2020} for r in readings}}
            events = gpm.detect_precip_records(readings, state)
            calls = sorted(call.request.url for call in mock.calls)
            results.append((readings, events, calls))
    assert results[0] == results[1]
    assert results[0][1], "fixture must exercise the downstream event path"


@responses.activate
def test_population_beyond_trace_bound_is_incomplete_never_truncated(clean_env):
    clean_env.setenv("THEHEAT_GPM_SOURCE", "datapool")
    clean_env.setattr(gpm, "MAX_TRACE_POPULATION", 10)
    rows = population(12)
    Transport(rows, grid_dates=[DAY - timedelta(days=1)]).install()
    readings, trace = traced(rows)
    assert len(readings) == 12
    assert trace["trace_status"] == "incomplete"
    assert set(trace["incomplete_reasons"]) == {"population_exceeds_trace_bound", "grid_membership_not_captured"}
    assert "reading_bitmap" not in trace["legs"][0]


@responses.activate
def test_capture_defect_marks_trace_incomplete_without_changing_readings(clean_env):
    clean_env.setenv("THEHEAT_GPM_SOURCE", "datapool")
    rows = population(15)
    Transport(rows, grid_dates=[DAY - timedelta(days=1)]).install()
    clean_env.setattr(gpm, "_reading_key", lambda reading: (_ for _ in ()).throw(RuntimeError("capture bug")))
    readings, trace = traced(rows)
    assert len(readings) == 15
    assert "capture_error" in trace["incomplete_reasons"] and trace["trace_status"] == "incomplete"


def test_in_flight_members_at_export_are_pending_not_complete():
    trace = gpm.RainfallOpportunityTrace(run_id="run_y")
    rows = population(4)
    trace.begin(rows, today=DAY, product="late", max_cities=4, max_workers=2, target_date=None)
    trace.window("imerg_late_opendap", rows, scan_date=DAY, max_cities=4, data_date=DAY - timedelta(days=1))
    trace.member("imerg_late_opendap", 0, "s")
    trace.member("imerg_late_opendap", 1, "s")
    trace.member("imerg_late_opendap", 1, "r")
    exported = trace.export()
    (leg,) = exported["legs"]
    assert leg["dispositions"] == "prnn" and leg["in_flight_at_export"] == 1
    assert {"in_flight_at_export", "not_finished"} <= set(exported["incomplete_reasons"])


# Offline audit over exported traces.

def _grid_trace(rows, day, *, read, run_id, data_lag=1, outcome="primary_served"):
    """A trace exported by the real recorder for a grid run with chosen readers."""
    trace = gpm.RainfallOpportunityTrace(run_id=run_id)
    trace.begin(rows, today=day, product="late", max_cities=75, max_workers=8, target_date=None)
    trace.grid_begin("datapool", start_date=day - timedelta(days=1), max_lookback=5)
    trace.grid_candidate("datapool", day - timedelta(days=data_lag), "downloaded")
    data_day = (day - timedelta(days=data_lag)).isoformat()
    readings = [gpm.CityPrecipReading(city=r["city"], country=r["country"], lat=float(r["lat"]), lon=float(r["lon"]),
                                      date=data_day, mm_total=1.0, source_product="late",
                                      event_id=f"gpm_imerg_{gpm.places.event_location_key(r['city'], r['country'], r['lat'], r['lon'])}_{data_day}")
                for i, r in enumerate(rows) if i in read]
    trace.grid_inspected("datapool", day - timedelta(days=data_lag), readings)
    trace.leg_result("imerg_late_grid_datapool", "served")
    trace.finish(outcome, readings)
    return json.loads(json.dumps(trace.export()))


def _failed_trace(rows, day, run_id):
    trace = gpm.RainfallOpportunityTrace(run_id=run_id)
    trace.begin(rows, today=day, product="late", max_cities=75, max_workers=8, target_date=None)
    trace.finish("failed", exc=RuntimeError("invented"))
    return json.loads(json.dumps(trace.export()))


def test_audit_distinguishes_selected_attempted_inspected_and_fresh_and_measures_gaps():
    rows = population(6)
    pop = gpm.opportunity_population(rows)
    traces = [_grid_trace(rows, DAY + timedelta(days=d), read={0, 1} if d % 2 == 0 else {0, 2},
                          run_id=f"run_alerts_d{d}") for d in range(5)]
    report = audit.evaluate(traces, [pop])
    totals = report["opportunity_member_runs"]
    assert totals["selected"] == totals["attempted"] == totals["inspected"] == 30
    assert totals["fresh_primary"] == 10 and totals["witness_model"] == 0
    (window,) = report["observed_complete_windows"]
    assert (window["from"], window["to"], window["days"]) == ("2026-06-05", "2026-06-09", 5)
    assert window["members_without_fresh_primary_reading"] == 3 and window["max_observed_gap_days"] == 2
    assert window["censored_lower_bound_days"] == 5
    assert report["achieved_revisit_sla"] is None and report["global_recall"] is None
    assert report["cost"] == {"amount": None, "status": "unknown_unattributed"}


def test_audit_is_order_independent_counts_exact_copies_once_and_holds_conflicts():
    rows = population(5)
    pop = gpm.opportunity_population(rows)
    a = _grid_trace(rows, DAY, read={0}, run_id="run_alerts_a")
    b = _grid_trace(rows, DAY + timedelta(days=1), read={1}, run_id="run_alerts_b")
    conflict = _grid_trace(rows, DAY + timedelta(days=1), read={2}, run_id="run_alerts_b")
    twin = _grid_trace(rows, DAY, read={0}, run_id="run_alerts_twin")  # same bytes, separate capture
    inputs = [a, copy.deepcopy(a), b, conflict, twin]
    reports = []
    for seed in range(4):
        shuffled = list(inputs)
        Random(seed).shuffle(shuffled)
        reports.append(audit.evaluate(shuffled, [pop]))
    assert all(report == reports[0] for report in reports)
    statuses = {(r["identity"], r["status"]) for r in reports[0]["runs"]}
    assert ("run_alerts_a", "counted") in statuses and ("run_alerts_twin", "counted") in statuses
    assert [r for r in reports[0]["runs"] if r["identity"] == "run_alerts_a"][0]["copies"] == 2
    assert [r["status"] for r in reports[0]["runs"] if r["identity"] == "run_alerts_b"] == ["conflict_held"] * 2
    assert reports[0]["calendar"][1]["status"] == "missing_run"  # held conflict cannot fill the day


def test_audit_keeps_missed_days_failures_population_changes_and_midnight_visible():
    rows = population(5)
    changed = population(6)
    pops = [gpm.opportunity_population(rows), gpm.opportunity_population(changed)]
    traces = [
        _grid_trace(rows, DAY, read={0, 1}, run_id="run_alerts_1"),
        _failed_trace(rows, DAY + timedelta(days=1), "run_alerts_2"),
        # Day 3 missing entirely.
        _grid_trace(rows, DAY + timedelta(days=3), read={0}, run_id="run_alerts_4"),
        _grid_trace(changed, DAY + timedelta(days=4), read={0}, run_id="run_alerts_5"),
        _grid_trace(changed, DAY + timedelta(days=5), read={0}, run_id="run_alerts_6", data_lag=9),
    ]
    midnight = _grid_trace(changed, DAY + timedelta(days=6), read={1}, run_id="run_alerts_7")
    midnight["legs"][0]["walkback_start_date"] = (DAY + timedelta(days=6)).isoformat()  # local date ran ahead
    report = audit.evaluate([*traces, midnight], pops)
    calendar = {row["date"]: row for row in report["calendar"]}
    assert calendar["2026-06-06"]["outcomes"] == ["failed"] and calendar["2026-06-06"]["status"] == "observed"
    assert calendar["2026-06-07"]["status"] == "missing_run"
    windows = [(w["from"], w["to"], w["population_sha256"]) for w in report["observed_complete_windows"]]
    assert windows == [("2026-06-05", "2026-06-06", pops[0]["sha256"]), ("2026-06-08", "2026-06-08", pops[0]["sha256"]),
                       ("2026-06-09", "2026-06-11", pops[1]["sha256"])]
    assert report["opportunity_member_runs"]["stale_primary"] == 1  # nine-day-old grid is not fresh
    assert report["walkback"]["local_utc_start_mismatch_runs"] == ["run_alerts_7"]
    assert report["walkback"]["depth_days_by_run"]["run_alerts_6"] == 9


def test_unavailable_legacy_unidentified_and_mismatched_traces_never_count():
    rows = population(5)
    pop = gpm.opportunity_population(rows)
    good = _grid_trace(rows, DAY, read={0}, run_id="run_alerts_ok")
    legacy = {"source": "gpm_imerg", "status": "success"}
    unidentified = _grid_trace(rows, DAY, read={0}, run_id=None)
    incomplete = gpm.RainfallOpportunityTrace(run_id="run_alerts_inc").export()
    unknown_population = _grid_trace(population(4), DAY + timedelta(days=1), read={0}, run_id="run_alerts_pop")
    tampered = _grid_trace(rows, DAY + timedelta(days=2), read={0}, run_id="run_alerts_bits")
    tampered["legs"][0]["reading_bitmap"] = "!!"
    report = audit.evaluate([good, legacy, unidentified, incomplete, unknown_population, tampered], [pop])
    status = {r["identity"]: r for r in report["runs"]}
    assert status["run_alerts_ok"]["status"] == "counted"
    assert status["run_alerts_inc"]["status"] == "trace_incomplete"
    assert status["run_alerts_pop"]["reasons"] == ["population_missing"]
    assert {r["status"] for r in report["runs"] if r["identity"] is None} == {"unsupported", "unidentified_held"}
    assert {row["date"]: row["status"] for row in report["calendar"]}["2026-06-06"] == "not_auditable"
    with pytest.raises(audit.TraceError, match="trace_bitmap"):
        audit._member_view(tampered, pop["members"])


def test_window_selection_mismatch_is_held_not_reinterpreted():
    rows = population(12)
    pop = gpm.opportunity_population(rows)
    trace = gpm.RainfallOpportunityTrace(run_id="run_alerts_w")
    trace.begin(rows, today=DAY, product="late", max_cities=5, max_workers=1, target_date=None)
    window = gpm._network_watchlist(rows, 5, scan_date=DAY)
    trace.window("imerg_late_opendap", window, scan_date=DAY, max_cities=5, data_date=DAY - timedelta(days=1))
    for i in range(5):
        trace.member("imerg_late_opendap", i, "r")
    trace.leg_result("imerg_late_opendap", "served")
    trace.finish("primary_served", [gpm.CityPrecipReading("a", "b", 0, 0, "2026-06-04", 1.0, "late", "x")])
    exported = json.loads(json.dumps(trace.export()))
    assert audit.evaluate([exported], [pop])["opportunity_member_runs"]["fresh_primary"] == 5
    shifted = copy.deepcopy(exported)
    shifted["legs"][0]["scan_date"] = (DAY + timedelta(days=1)).isoformat()
    report = audit.evaluate([shifted], [pop])
    assert report["runs"][0]["reasons"] == ["selection_mismatch"]
    assert report["opportunity_member_runs"]["fresh_primary"] == 0


def test_evaluator_constants_match_the_accepted_selector():
    assert (audit.DEFAULT_CITY_LIMIT, audit.MAX_NETWORK_CITIES) == (gpm.DEFAULT_CITY_LIMIT, gpm.MAX_NETWORK_CITIES)
    assert (audit.TRACE_SCHEMA, audit.POPULATION_SCHEMA, audit.POPULATION_BASIS) == (
        gpm.TRACE_SCHEMA, gpm.POPULATION_SCHEMA, gpm.POPULATION_BASIS)
    rows = population(80)
    members = gpm.opportunity_population(rows)["members"]
    for offset in range(4):
        scan = DAY + timedelta(days=offset)
        actual = [gpm.places.event_location_key(r["city"], r["country"], r["lat"], r["lon"])
                  for r in gpm._network_watchlist(rows, 75, scan_date=scan)]
        assert audit.window_members(members, scan, 75) == actual


def test_cli_audits_detached_files_and_refuses_unsafe_inputs(tmp_path):
    tmp_path = tmp_path.resolve()  # the CLI refuses symlinked parents such as /var on macOS
    rows = population(5)
    trace = tmp_path / "trace.json"
    pop = tmp_path / "population.json"
    trace.write_text(json.dumps(_grid_trace(rows, DAY, read={0, 2}, run_id="run_alerts_cli")))
    pop.write_text(json.dumps(gpm.opportunity_population(rows)))
    script = "scripts/audit_rainfall_opportunity.py"
    done = subprocess.run([sys.executable, script, "--trace", str(trace), "--population", str(pop)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    report = json.loads(done.stdout)
    assert report["opportunity_member_runs"]["fresh_primary"] == 2 and report["global_recall"] is None
    duplicate = tmp_path / "dup.json"
    duplicate.write_text('{"schema": 1, "schema": 2}')
    link = tmp_path / "link.json"
    link.symlink_to(trace)
    nonfinite = tmp_path / "nan.json"
    nonfinite.write_text('{"x": NaN}')
    for bad in (duplicate, link, nonfinite):
        refused = subprocess.run([sys.executable, script, "--trace", str(bad)], capture_output=True, text=True,
                                 timeout=60)
        assert refused.returncode == 2 and "error" in json.loads(refused.stdout)
