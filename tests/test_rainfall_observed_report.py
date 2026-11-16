"""Invented registered-point reports; no NASA, model or platform requests."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

import pytest

from src.data import gpm_imerg as gpm, places, rainfall_observed as report

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
DAY = "2026-11-15"
TEXT = ("180.5 mm water-equivalent precipitation in 24 hours near Paris, France, on 15 Nov, NASA satellites estimate.\n"
        + report.SOURCE_URL)


@pytest.fixture
def reading():
    row = next(x for x in gpm.load_cities() if x["city"] == "Paris" and x["country"] == "France")
    key = places.event_location_key(row["city"], row["country"], row["lat"], row["lon"])
    return gpm.CityPrecipReading(row["city"], row["country"], float(row["lat"]), float(row["lon"]),
                                DAY, 180.5, "late", f"gpm_imerg_{key}_{DAY}")


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(report.ENABLE_FLAG, "1")
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", "rainfall-fixture-epoch")
    monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
    monkeypatch.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "1")
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_PRODUCTION_PAUSED", "0")
    return monkeypatch


@pytest.fixture
def bundle(reading):
    return report.build_bundle(report.evidence_for(reading, now=NOW), now=NOW)


def test_completed_window_end_is_bound_without_replacing_original_date(bundle, reading, enabled):
    assert bundle.when == "2026-11-16T00:00:00Z"
    assert bundle.raw_signal_dump["rainfall_window"]["accumulation_start"] == "2026-11-15T00:00:00Z"
    assert bundle.raw_signal_dump["rainfall_window"]["accumulation_end"] == bundle.when
    assert bundle.raw_signal_dump["evidence"]["reading"] == asdict(reading)
    assert report.claim_failures(TEXT, bundle, now=NOW) == []
    assert report.current_bundle_hold(bundle, now=NOW) is None
    assert "previous_record_mm" not in repr(bundle.current_facts)


@pytest.mark.parametrize("sealed", [False, True])
def test_retained_report_validation_does_not_import_live_collector(bundle, tmp_path, sealed):
    code = '''
import importlib.abc, json, sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
class RefuseCollector(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "src.data.gpm_imerg":
            raise AssertionError("retained validation imported live NASA collector")
sys.meta_path.insert(0, RefuseCollector())
from src.data import rainfall_observed as report
data = json.load(sys.stdin)
now = datetime.fromisoformat(data["now"])
assert report.validate_bundle(data["bundle"], now=now) == data["bundle"]["raw_signal_dump"]["evidence"]
assert report.claim_failures(data["text"], data["bundle"], now=now) == []
assert "src.data.gpm_imerg" not in sys.modules
'''
    source_path = Path(__file__).resolve().parents[1]
    if sealed:
        from scripts.gen_dashboard_graphic_runtime import generate
        archive, _manifest = generate()
        source_path = tmp_path / "retained-runtime.zip"
        source_path.write_bytes(archive)
    result = subprocess.run([sys.executable, "-I", "-c", code, str(source_path)], cwd=tmp_path,
                            input=json.dumps({"bundle": bundle.to_dict(), "text": TEXT, "now": NOW.isoformat()}),
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_retained_wire_fields_match_the_actual_collector_reading():
    assert report._READING_FIELDS == set(gpm.CityPrecipReading.__dataclass_fields__)


def test_portable_watchlist_uses_the_actual_active_registered_points():
    expected = {places.event_location_key(row["city"], row["country"], row["lat"], row["lon"])
                for row in places.load_cities() if not row["place_id"].startswith("ux")}
    assert report._watchlist_keys() == expected


@pytest.mark.parametrize("triage", ["0", "1"])
def test_report_operation_budget_survives_disabled_ranking(enabled, triage):
    from src.orchestrator.candidate_budget import CandidateBudget
    enabled.setenv("THEHEAT_TRIAGE_ENABLED", triage)
    budget = CandidateBudget.for_operation("alerts")
    assert budget.limit == 1 and budget.refusal is None
    enabled.setenv("THEHEAT_MAX_DRAFTS_PER_CYCLE", "3")
    refused = CandidateBudget.for_operation("alerts")
    assert refused.limit == 0 and refused.refusal == "rainfall_report_one_candidate_required"


@pytest.mark.parametrize("key,value", [
    ("source_product", "final"), ("source_product", "open_meteo"), ("source_leg", "open_meteo"),
    ("mm_total", True), ("mm_total", float("nan")), ("mm_total", 149.99), ("mm_total", 1000.01),
    ("lat", True), ("lat", 91), ("lon", -181), ("lat", 0), ("country", "Canada"),
    ("date", "2026-11-16"), ("date", "2026-11-13"), ("event_id", "foreign"),
])
def test_invalid_product_point_day_and_operating_range_refuse(reading, key, value):
    with pytest.raises((report.ReportHeld, ValueError)):
        report.evidence_for(replace(reading, **{key: value}), now=NOW)


@pytest.mark.parametrize("key,value", [("where", "Elsewhere"), ("when", "2026-11-16T17:00:00Z"),
                                      ("event_id", "changed"), ("signal_kind", "record")])
def test_each_declared_bundle_field_is_recomputed(bundle, key, value, enabled):
    payload = bundle.to_dict()
    payload[key] = value
    assert report.current_bundle_hold(payload, now=NOW) == "rainfall_bundle_changed"


def test_live_read_is_exact_day_single_point_and_changed_reading_refuses(bundle, reading, enabled):
    calls = []
    def fetch(rows, **kwargs):
        calls.append((rows, kwargs))
        return [reading]
    enabled.setattr(gpm, "_fetch_daily_precip_primary", fetch)
    assert report.current_bundle_hold(bundle, live=True, now=NOW) is None
    assert calls[0][1]["target_date"].isoformat() == DAY
    assert calls[0][1]["max_cities"] == calls[0][1]["max_workers"] == 1
    assert calls[0][1]["strict"] is True and calls[0][1]["product"] == "late"
    enabled.setattr(gpm, "_fetch_daily_precip_primary", lambda *a, **kw: [replace(reading, mm_total=181)])
    assert report.current_bundle_hold(bundle, live=True, now=NOW) == "rainfall_current_source_changed"


def test_source_failure_and_expiry_during_read_cannot_promote(bundle, reading, enabled):
    def failed(*args, **kwargs):
        raise RuntimeError("invented source unavailable")
    enabled.setattr(gpm, "_fetch_daily_precip_primary", failed)
    assert report.current_bundle_hold(bundle, live=True, now=NOW) == "rainfall_current_source_unavailable"
    enabled.setattr(gpm, "_fetch_daily_precip_primary", lambda *a, **kw: [reading])
    times = iter([NOW, NOW + timedelta(hours=20)])
    assert report.current_bundle_hold(bundle, live=True, now=lambda: next(times)) == "rainfall_completed_window_expired"


@pytest.mark.parametrize("flag", [report.ENABLE_FLAG, "THEHEAT_OBSERVED_WEATHER_ONLY"])
def test_disabled_profile_refuses_before_live_requests(bundle, enabled, flag):
    enabled.setenv(flag, "0")
    enabled.setattr(gpm, "_fetch_daily_precip_primary", lambda *a, **kw: pytest.fail("unexpected live request"))
    assert report.current_bundle_hold(bundle, live=True, now=NOW) == "rainfall_observed_report_disabled"


@pytest.mark.parametrize("old,new,reason", [
    ("180.5", "190", "rainfall_amount_changed"),
    ("estimate", "measured", "rainfall_satellite_estimate_label_required"),
    ("near Paris", "across Paris", "rainfall_point_scope_required"),
    ("France", "Canada", "rainfall_country_required"),
    ("15 Nov", "14 Nov", "rainfall_date_required"),
    ("24 hours", "three days", "rainfall_daily_window_required"),
])
def test_copy_cannot_change_amount_scope_source_date_or_window(bundle, enabled, old, new, reason):
    assert report.claim_failures(TEXT.replace(old, new), bundle, now=NOW) == [reason]


def test_record_impact_and_bad_conversion_claims_refuse(bundle, enabled):
    assert report.claim_failures(TEXT.replace(".\n", ", a record.\n"), bundle, now=NOW) == ["rainfall_unsupported_claim"]
    assert report.claim_failures(TEXT.replace(".\n", ", flooding homes.\n"), bundle, now=NOW) == ["rainfall_unsupported_claim"]
    assert report.claim_failures(TEXT.replace("180.5 mm", "180.5 mm (12 inches)"), bundle, now=NOW) == ["rainfall_conversion_changed"]


@pytest.mark.parametrize("text,reason", [
    (TEXT + " https://example.invalid/foreign", "rainfall_citation_required"),
    (TEXT.replace(report.SOURCE_URL, report.SOURCE_URL + "?claim=changed"), "rainfall_citation_required"),
    (TEXT.replace("precipitation", "rain"), "rainfall_quantity_label_required"),
    (TEXT.replace("water-equivalent ", ""), "rainfall_quantity_label_required"),
    (TEXT.replace(".\n", ", forcing evacuations.\n"), "rainfall_unsupported_claim"),
])
def test_source_citation_and_precipitation_phase_cannot_be_inferred(bundle, enabled, text, reason):
    assert report.claim_failures(text, bundle, now=NOW) == [reason]


@pytest.mark.parametrize("label", ["180", "181", "180.5"])
def test_explicit_integer_or_tenth_rounding_is_allowed(bundle, enabled, label):
    assert report.claim_failures(TEXT.replace("180.5", label), bundle, now=NOW) == []


@pytest.mark.parametrize("label", ["-180.5 mm", "−180.5 mm", "180.5 mm (-7.1 inches)"])
def test_negative_quantities_cannot_match_a_positive_total(bundle, enabled, label):
    assert report.claim_failures(TEXT.replace("180.5 mm", label), bundle, now=NOW) == ["rainfall_amount_changed"]


@pytest.mark.parametrize("key,value", [
    ("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED", "0"), ("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH", ""),
    ("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "0"), ("THEHEAT_CRITIC_ENABLED", "0"),
    ("THEHEAT_PRODUCTION_PAUSED", "1"), ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "2"),
    ("THEHEAT_MAX_DRAFTS_PER_CYCLE", "invalid"), ("THEHEAT_WRITER_SAMPLES", "3"),
    ("THEHEAT_CRITIC_REVISE_ENABLED", "1"), ("THEHEAT_REFILL_ENABLED", "1"),
])
def test_source_profile_refuses_other_spend_and_publication_settings(bundle, enabled, key, value):
    enabled.setenv(key, value)
    enabled.setattr(gpm, "_fetch_daily_precip_primary", lambda *a, **kw: pytest.fail("unexpected source request"))
    assert report.current_bundle_hold(bundle, live=True, now=NOW) is not None


def test_free_slate_is_bounded_order_independent_and_conflicts_never_win(reading, enabled):
    assert len(report.nominate([reading] * 4, {}, now=NOW)) == 1
    conflict = replace(reading, mm_total=181.0)
    assert report.nominate([reading, conflict, reading], {}, now=NOW) == []
    assert report.nominate([conflict, reading], {}, now=NOW) == []


def test_draft_retagging_and_old_uncertain_or_pending_aliases_hold(bundle, reading, enabled):
    draft = {"type": report.KIND, "event_id": bundle.event_id, "text": TEXT,
             "review_context": {"two_bot": {"bundle": bundle.to_dict()}}}
    assert report.current_draft_hold(draft, now=NOW) is None
    foreign = deepcopy(draft)
    foreign["type"] = "record"
    assert report.current_draft_hold(foreign, now=NOW) == "rainfall_draft_identity_changed"
    old = reading.event_id.replace("gpm_imerg_", "gpm_precip_record_", 1)
    for state in ({"posted_events": [old]}, {"publish_ledger": {old: {"status": "unknown"}}},
                  {"drafts": [{"event_id": old}]}):
        assert report.legacy_point_day_hold(draft, state) == "rainfall_legacy_point_day_held"
    assert report.legacy_point_day_hold(draft, {"publish_ledger": {bundle.event_id: {"status": "sending"}}}) is None
