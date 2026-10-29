"""Six finite invented G11-R2 regressions through the real offline consumers."""
from copy import deepcopy
from datetime import timedelta
from itertools import permutations
import json
from random import Random

import pytest

from src.data import gpm_imerg as gpm
from src.data import source_product_contracts as products
from src.evaluation import global_readiness as readiness
from src.evaluation import rainfall_opportunity as audit
from tests.test_global_readiness import CUTOFF, episode, report
from tests.test_rainfall_opportunity import DAY, _grid_trace, population


def _envelope(exports):
    return dict(schema_version=1, assessment_cutoff=CUTOFF, components=exports)


def _rainfall(exports):
    return _envelope([dict(component_type="rainfall_opportunity", export=value) for value in exports])


def _three_days():
    rows = population(2)
    return rows, gpm.opportunity_population(rows), [
        _grid_trace(rows, DAY + timedelta(days=i), read={0, 1}, run_id=f"run_alerts_valid{i}")
        for i in range(3)]


def _gdacs(legs):
    return dict(source="gdacs", status="degraded", note="served via subtype_witnesses (GeoRSS primary unavailable)",
                details=dict(feed_diagnostics=dict(source_leg="subtype_witnesses", legs=legs,
                                                    selected_alerts=sum(x["records_selected"] or 0 for x in legs.values()))))


@pytest.mark.parametrize("status", ["degraded", "success"])
def test_gdacs_actual_partial_witness_diagnostics_identify_only_successful_products(status):
    legs = {"usgs_quakes": dict(status="success", records_received=1, records_selected=1),
            "nhc": dict(status="failed", records_received=None, records_selected=None),
            "jtwc": dict(status="failed", records_received=None, records_selected=None)}
    for ordered in permutations(legs):
        entry = _gdacs({key: legs[key] for key in ordered})
        entry["status"] = status
        result = products.serving_disposition_from_run_entry(entry)
        assert result["serving_product_ids"] == ["gdacs.subtype_witness_usgs"]
        assert result["primary_leg_served_this_run"] is False
    # A completed feed can have zero selected alerts without claiming an event.
    empty = _gdacs({key: dict(status="success", records_received=0, records_selected=0) for key in legs})
    empty["details"]["feed_diagnostics"].update(status="witnesses_completed", primary_status="unavailable")
    assert len(products.serving_disposition_from_run_entry(empty)["serving_product_ids"]) == 3
    all_success = {key: dict(status="success", records_received=1, records_selected=1) for key in legs}
    assert products.serving_disposition_from_run_entry(_gdacs(all_success))["serving_product_ids"] == sorted(
        f"gdacs.subtype_witness_{key}" for key in ("usgs", "nhc", "jtwc"))


@pytest.mark.parametrize("change", ["missing", "wrong_leg", "contradictory_count", "contradictory_total", "wrong_type", "missing_feed", "missing_count", "wrong_status", "wrong_primary"])
@pytest.mark.parametrize("status", ["degraded", "success"])
def test_gdacs_missing_or_contradictory_diagnostics_retain_unknown_service(change, status):
    entry = _gdacs({key: dict(status="success", records_received=1, records_selected=1)
                    for key in ("usgs_quakes", "nhc", "jtwc")})
    entry["status"] = status
    diagnostics = entry["details"]["feed_diagnostics"]
    if change == "missing":
        entry.pop("details")
    elif change == "wrong_leg":
        diagnostics["source_leg"] = "other"
    elif change == "contradictory_count":
        diagnostics["legs"]["nhc"]["records_selected"] = 2
    elif change == "contradictory_total":
        diagnostics["selected_alerts"] += 1
    elif change == "wrong_type":
        diagnostics["legs"]["nhc"]["status"] = []
    elif change == "missing_feed":
        diagnostics["legs"].pop("nhc")
    elif change == "missing_count":
        diagnostics["legs"]["nhc"].pop("records_received")
    elif change == "wrong_status":
        diagnostics["status"] = "partial_witness_failure"
    else:
        diagnostics["primary_status"] = "success"
    result = products.serving_disposition_from_run_entry(entry)
    assert result["serving_product_ids"] == []
    assert result["primary_leg_served_this_run"] is None
    assert result["observed_status"] == status
    assert "witness_serving_diagnostics_missing_or_inconsistent" in result["reasons"]


def test_gdacs_unlabelled_success_still_identifies_the_wired_primary():
    result = products.serving_disposition_from_run_entry(dict(source="gdacs", status="success"))
    assert result["serving_product_ids"] == ["gdacs.georss"]
    assert result["primary_leg_served_this_run"] is True
    assert result["evidence"] == "sole_wired_unlabelled_primary"


def test_malformed_dated_capture_withholds_middle_day_but_keeps_valid_neighbors():
    _rows, pop, valid = _three_days()
    assert [w["days"] for w in audit.evaluate(valid, [pop])["observed_complete_windows"]] == [3]
    bad = deepcopy(valid[1])
    bad["run_id"] = "run_alerts_badcopy"
    bad["request_counts"]["http_requests"]["min"] = []
    reports = []
    for seed in range(4):
        inputs = [*valid, bad]
        Random(seed).shuffle(inputs)
        result = audit.evaluate(inputs, [pop])
        assert [w["days"] for w in result["observed_complete_windows"]] == [1, 1]
        assert result["calendar"][1]["status"] == "observed_with_held_capture"
        refused = next(row for row in result["runs"] if row["status"] == "unsupported")
        assert refused["identity"] == bad["run_id"]
        assert refused["selection_date"] == bad["selection_date_utc"]
        assert refused["reasons"] == ["trace_request_counts"]
        assert len([row for row in result["runs"] if row["status"] == "counted"]) == 3
        reports.append(result)
    assert all(result == reports[0] for result in reports)
    # Invalid identity/date or unrelated schema is not enough to poison a day.
    for field, value in (("run_id", []), ("selection_date_utc", "invalid"), ("source_id", "unrelated")):
        unrelated = deepcopy(bad)
        unrelated[field] = value
        assert [w["days"] for w in audit.evaluate([*valid, unrelated], [pop])["observed_complete_windows"]] == [3]


def _omitted_trace():
    rows = population(2)
    trace = gpm.RainfallOpportunityTrace(run_id="run_alerts_omitted")
    trace.begin(rows, today=DAY, product="late", max_cities=75, max_workers=8, target_date=None)
    trace.grid_begin("datapool", start_date=DAY - timedelta(days=1), max_lookback=40)
    for i in range(41):
        trace.grid_candidate("datapool", DAY - timedelta(days=i + 1), "not_found")
    trace.leg_result("imerg_late_grid_datapool", "failed", "invented_missing_data")
    for i in range(41):
        trace.probe(DAY - timedelta(days=i + 1), "not_found", start_date=DAY - timedelta(days=1), max_lookback=40)
    trace.leg_result("imerg_late_opendap", "failed", "invented_missing_data")
    trace.finish("failed", exc=RuntimeError("invented"))
    return gpm.opportunity_population(rows), json.loads(json.dumps(trace.export()))


@pytest.mark.parametrize("deleted", [("candidates",), ("date_probes",), ("candidates", "date_probes")])
def test_deleted_capture_lists_cannot_hide_retained_omission_counts(deleted):
    pop, changed = _omitted_trace()
    assert changed["trace_status"] == "incomplete"
    for leg in changed["legs"]:
        for field in deleted:
            leg.pop(field, None)
    changed.update(trace_status="complete", incomplete_reasons=[])
    audit.validate_trace(changed)
    derived = audit.derived_incomplete(changed)
    assert {"grid_candidates_exceed_trace_bound", "date_probes_exceed_trace_bound"} <= set(derived)
    assert not audit.evaluate([changed], [pop])["observed_complete_windows"]
    # Missing captures remain incomplete even if omissions are also rewritten to zero.
    for leg in changed["legs"]:
        for field in ("candidates_omitted", "date_probes_omitted"):
            if field in leg:
                leg[field] = 0
    assert audit.derived_incomplete(changed)


@pytest.mark.parametrize("hold", ["conflict", "incomplete", "unsupported"])
def test_connected_readiness_preserves_cutoff_eligible_rainfall_holds(hold):
    _rows, pop, valid = _three_days()
    extra = deepcopy(valid[1])
    extra["run_id"] = "run_alerts_held"
    held = [extra]
    if hold == "conflict":
        other = deepcopy(extra)
        other["legs"][0]["readings"] += 1
        held.append(other)
    elif hold == "incomplete":
        extra.update(trace_status="incomplete", incomplete_reasons=["invented_missing_data"])
    else:
        extra["request_counts"]["http_requests"]["min"] = []
    lower = audit.evaluate([*valid, *held], [pop])
    assert [w["days"] for w in lower["observed_complete_windows"]] == [1, 1]
    results = []
    for seed in range(4):
        inputs = [pop, *valid, *held]
        Random(seed).shuffle(inputs)
        result = readiness.assess(_rainfall(inputs))
        measured = result["rainfall_opportunity"]
        for key in ("observed_complete_windows", "opportunity_member_runs", "request_counts", "cost",
                    "achieved_revisit_sla", "global_recall"):
            assert measured[key] == lower[key]
        assert "observed_with_held_capture" in measured["calendar_statuses"]
        results.append(result)
    assert all(result == results[0] for result in results)


@pytest.mark.parametrize("malformed", [False, True])
def test_connected_readiness_ignores_future_or_unrelated_rainfall(malformed):
    _rows, pop, valid = _three_days()
    baseline = readiness.assess(_rainfall([pop, *valid]))["rainfall_opportunity"]
    future = deepcopy(valid[1])
    future["run_id"] = valid[1]["run_id"]  # future conflicting copy cannot hold eligible history
    future["selection_date_utc"] = "2026-10-14"
    if malformed:
        future["request_counts"]["http_requests"]["min"] = []
    unrelated = deepcopy(valid[1])
    unrelated["source_id"] = "unrelated"
    unrelated["request_counts"]["http_requests"]["min"] = []
    result = readiness.assess(_rainfall([pop, *valid, future, unrelated]))
    assert result["rainfall_opportunity"] == baseline


@pytest.mark.parametrize("field,value", [
    ("episode_id", []), ("episode_id", ""), ("episode_id", 42),
    ("episode_id", "fixture:invalid"), ("episode_id", "ep1:cyclone:nhc:AL010000"),
    ("episode_head", []), ("episode_head", "not-a-revision"),
    ("association_status", []), ("association_status", "invented"),
    ("time_compatibility", []), ("time_compatibility", "invented"),
])
def test_malformed_report_linkage_is_refused_without_losing_valid_neighbors(field, value):
    good = report()
    bad = report(lineage="fixture:bad", sha="c" * 64)
    bad["related_story"][field] = value
    exports = [dict(component_type="physical_episode", export=episode()),
               dict(component_type="report_development", export=good),
               dict(component_type="report_development", export=bad)]
    for ordered in permutations(exports):
        result = readiness.assess(_envelope(list(ordered)))
        assert len([r for r in result["components"] if r["status"] == "unsupported"
                    and r["reasons"] == ["invalid_report_projection"]]) == 1
        assert any(j["disposition"] == "exact" for j in result["joins"])
    for compatibility in ("explicit_utc_interval", "source_calendar_compatibility_only"):
        good["related_story"]["time_compatibility"] = compatibility
        control = readiness.assess(_envelope(exports[:2]))
        assert not any(row["status"] == "unsupported" for row in control["components"])


def test_oversized_json_integer_returns_bounded_refusal_and_preserves_specific_codes():
    assert readiness.strict_loads(b'{"value":1}') == {"value": 1}
    with pytest.raises(readiness.ReadinessError, match="^invalid_json$"):
        readiness.strict_loads(b'{"value":' + b'1' * 4301 + b'}')
    for raw, code in ((b'{"x":1,"x":2}', "duplicate_json_key"),
                      (b'{"x":NaN}', "nonfinite_json_number"), (b'{', "invalid_json")):
        with pytest.raises(readiness.ReadinessError, match=f"^{code}$"):
            readiness.strict_loads(raw)
