"""Count-only nomination evidence through real qualification; no source calls."""
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import json

import pytest

from src.data import gpm_imerg, places, rainfall_observed
from src.orchestrator.sources import gpm_imerg as source

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)


def reading(mm=20.0, *, row=None, day="2026-11-15"):
    row = row or next(x for x in gpm_imerg.load_cities() if x["city"] == "Paris" and x["country"] == "France")
    key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"])
    return gpm_imerg.CityPrecipReading(row["city"], row["country"], float(row["lat"]), float(row["lon"]),
        day, mm, "late", f"gpm_imerg_{key}_{day}")


def other_reading():
    row = next(x for x in gpm_imerg.load_cities() if x["city"] != "Paris")
    return reading(row=row)


def test_actual_source_caller_records_why_zero_nominations_without_enqueue_or_fetch(monkeypatch):
    monkeypatch.setattr(source, "_report_settings_hold", lambda state: None)
    monkeypatch.setattr(rainfall_observed, "_clock", lambda now=None: NOW)
    def forbidden(*args, **kwargs):
        raise AssertionError("held reading cannot enqueue or fetch")
    monkeypatch.setattr(source, "_enqueue_story_candidate", forbidden)
    monkeypatch.setattr(gpm_imerg, "fetch_daily_precip", forbidden)
    details = {}
    assert source._enqueue_observed_reports({}, [reading()], {}, details) == 0
    assert details["status"] == "no_qualified_report"
    assert details["nomination"]["input_rows"] == 1
    assert details["nomination"]["qualification_holds"] == {"rainfall_outside_automatic_range": 1}


def reconcile(details):
    assert details["input_rows"] == sum(details[key] for key in (
        "untyped_rows", "identity_unavailable_rows", "identity_conflict_rows",
        "qualification_held_rows", "history_held_rows", "duplicate_qualified_rows", "qualified_events"))
    assert details["qualified_events"] == details["nominated_events"] + details["nomination_cap_excluded"]
    assert details["qualification_held_rows"] == sum(details["qualification_holds"].values())


@pytest.mark.parametrize("case", ["empty", "wrong_type", "valid", "duplicates", "conflict", "identity_missing", "mixed", "history", "cap"])
def test_diagnostics_on_off_preserve_real_bundles_order_validation_calls_and_state(monkeypatch, case):
    valid = reading(180.5)
    state = {}
    inputs = {
        "empty": [], "wrong_type": [{}], "valid": [valid], "duplicates": [valid] * 4,
        "conflict": [valid, replace(valid, mm_total=2000.0), valid],
        "identity_missing": [replace(valid, event_id="", date="invalid")],
        "mixed": [valid, other_reading(), reading(180.5, day="2026-11-01"), {}],
        "history": [valid],
        "cap": [reading(180.5 + i, row=row) for i, row in enumerate(gpm_imerg.load_cities()[:5])],
    }[case]
    if case == "history":
        event = rainfall_observed.build_bundle(rainfall_observed.evidence_for(valid, now=NOW), now=NOW).event_id
        state = {"publish_ledger": {event: {}}}
    original = deepcopy(state)
    calls = []
    build = rainfall_observed.build_bundle
    def observed_build(evidence, **kwargs):
        calls.append(deepcopy(evidence))
        return build(evidence, **kwargs)
    def forbidden(*args, **kwargs):
        raise AssertionError("nomination cannot fetch")
    monkeypatch.setattr(rainfall_observed, "build_bundle", observed_build)
    monkeypatch.setattr(gpm_imerg, "fetch_daily_precip", forbidden)
    legacy = rainfall_observed.nominate(inputs, state, now=NOW)
    legacy_calls = deepcopy(calls)
    calls.clear()
    details = {}
    observed = rainfall_observed.nominate(inputs, state, now=NOW, diagnostics_out=details)
    assert [b.to_dict() for b in legacy] == [b.to_dict() for b in observed]
    assert calls == legacy_calls and state == original
    assert details["schema"] == rainfall_observed.NOMINATION_SCHEMA
    reconcile(details)
    if case == "duplicates":
        assert details["qualified_events"] == 1 and details["duplicate_qualified_rows"] == 3
    if case == "conflict":
        assert details["identity_conflict_rows"] == 3 and details["nominated_events"] == 0
    if case == "cap":
        assert details["qualified_events"] == 5 and details["nominated_events"] == 3
        assert details["nomination_cap_excluded"] == 2
    if case == "mixed":
        assert details["qualification_holds"] == {"rainfall_outside_automatic_range": 1, "rainfall_completed_window_expired": 1}


def test_unrecognized_exception_text_never_enters_observation(monkeypatch):
    sentinel = "invented-private-authorization-and-source-body"
    def refuse(*args, **kwargs):
        raise rainfall_observed.ReportHeld(sentinel)
    monkeypatch.setattr(rainfall_observed, "evidence_for", refuse)
    details = {}
    assert rainfall_observed.nominate([reading(180.5)], {}, now=NOW, diagnostics_out=details) == []
    assert details["qualification_holds"] == {"rainfall_report_unqualified": 1}
    assert sentinel not in json.dumps(details)
    assert "Paris" not in json.dumps(details)
    reconcile(details)


def test_real_caller_retains_counts_and_same_qualified_enqueue(monkeypatch):
    monkeypatch.setattr(source, "_report_settings_hold", lambda state: None)
    monkeypatch.setattr(rainfall_observed, "_clock", lambda now=None: NOW)
    queued = []
    def enqueue(state, **kwargs):
        queued.append(kwargs["bundle"].to_dict())
        return True
    monkeypatch.setattr(source, "_enqueue_story_candidate", enqueue)
    details = {}
    expected = [b.to_dict() for b in rainfall_observed.nominate([reading(180.5), other_reading()], {}, now=NOW)]
    assert source._enqueue_observed_reports({}, [reading(180.5), other_reading()], {}, details) == 1
    assert queued == expected
    assert details["status"] == "nominated" and details["nominated"] == details["queued"] == 1
    reconcile(details["nomination"])
