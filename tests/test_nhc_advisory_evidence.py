"""Typed NHC advisory evidence (invented data): strict validation before any paid work."""
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from src.editorial.nhc_advisory import (
    AdvisoryCapture, AdvisoryHold, OPERATOR_RULE, nomination, parse_bulletin, validate_capture,
)
from src.editorial.official_warning import WarningHold
from src.editorial.revisions import fingerprint
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.intern.nhc_advisory import RetainedAdvisory, build_nhc_advisory_bundle
from src.two_bot.types import StoryBundle
from tests import nhc_advisory_helpers as h

# Fingerprints at base bab3a5d: the old warning and unrelated bundles are untouched.
BASE = {"warning": "4b041e7f0315f52d850d5b6dfd662ca6451bd4634d51547418e6212405e2c274",
        "cone": "76583de77df7e1308b560e84e19af7bc77ecbe34a6f7f3fc41d3725f7bc8e7a7"}


def evidence(**kwargs):
    return validate_capture(h.capture(**kwargs), h.selected(), now=h.NOW)


def held(code, **kwargs):
    with pytest.raises(AdvisoryHold) as raised:
        evidence(**kwargs)
    assert raised.value.code == code
    assert isinstance(raised.value, WarningHold)  # Every existing warning handler treats it as a hold.


def test_valid_advisory_builds_attributed_forecast_facts_without_any_expiry():
    value = evidence()
    assert (value.bulletin.issued_at, value.bulletin.advisory, value.bulletin.storm_name) == (
        "2026-10-29T21:00:00Z", "34", "Inventa")
    page = h.page()
    start, end = value.span
    assert page[start:end] == value.bulletin.raw  # Exact original bytes, provably anchored.
    bundle = build_nhc_advisory_bundle(value)
    record = bundle.raw_signal_dump["nhc_advisory"]
    assert bundle.signal_kind == "nhc_advisory" and bundle.where == "Example Province" and bundle.country == "ZZ"
    assert bundle.event_id == "nhc_advisory:ep492026:34:rainfall"
    labels = [fact["label"] for fact in bundle.current_facts]
    assert labels == ["issuing_authority", "storm", "advisory_number", "issued_at", "forecast_hazard_statement",
                      "forecast_place", "source_reported_context"]
    assert not any("expir" in json.dumps(fact).lower() or "deadline" in json.dumps(fact).lower()
                   for fact in bundle.current_facts)
    assert record["times"] == {"issued_at": "2026-10-29T21:00:00Z", "captured_at": "2026-10-29T21:26:00Z",
                               "upstream_expiry": None, "upstream_expiry_status": "not_supplied_by_source",
                               "operator_recheck_deadline": "2026-10-29T21:56:00Z",
                               "operator_recheck_rule": OPERATOR_RULE}
    assert record["hazard"]["text"] == h.HAZARD and record["context"][0]["text"] == h.CONTEXT
    assert record["source"]["page_bytes"] == len(page) and record["source"]["advisory_url"] == h.URL
    assert len(capture_bundle(bundle).serialized.encode()) <= 32 * 1024
    assert RetainedAdvisory(bundle).identity() == value.identity()


def test_context_is_included_only_when_the_source_states_it():
    plain = validate_capture(h.capture(page_bytes=h.page(h.bulletin(context=""))), h.selected(), now=h.NOW)
    bundle = build_nhc_advisory_bundle(plain)
    assert bundle.raw_signal_dump["nhc_advisory"]["context"] == []
    assert "source_reported_context" not in [f["label"] for f in bundle.current_facts]


@pytest.mark.parametrize("change,code", [
    (dict(freshness_minutes=61), "nhc_advisory_freshness_invalid"),
    (dict(freshness_minutes=0), "nhc_advisory_freshness_invalid"),
    (dict(freshness_minutes=True), "nhc_advisory_freshness_invalid"),
    (dict(storm_id="AL492026"), "nhc_advisory_nomination_invalid"),  # Basin disagrees with the bin.
    (dict(bin="CP1"), "nhc_advisory_nomination_invalid"),
    (dict(advisory="034"), "nhc_advisory_nomination_invalid"),
    (dict(hazard="FLOODING"), "nhc_advisory_nomination_invalid"),
    (dict(place="https://example.test/x"), "nhc_advisory_nomination_invalid"),
    (dict(country="zz"), "nhc_advisory_nomination_invalid"),
    (dict(url="https://www.nhc.noaa.gov/text/MIATCPEP5.shtml"), "nhc_advisory_nomination_invalid"),
])
def test_nomination_is_explicit_bounded_and_never_a_url(change, code):
    value = h.nominated()
    value.update(change)
    with pytest.raises(AdvisoryHold) as raised:
        nomination(value)
    assert raised.value.code == code


@pytest.mark.parametrize("index_bytes,code", [
    (h.index(storms=[]), "nhc_advisory_storm_not_current"),
    (h.index(advisory="35"), "nhc_advisory_superseded"),
    (h.index(advisory="33"), "nhc_advisory_index_mismatch"),
    (h.index(url="https://evil.example.test/text/MIATCPEP5.shtml"), "nhc_advisory_index_url_mismatch"),
    (h.index(url="http://www.nhc.noaa.gov/text/MIATCPEP5.shtml"), "nhc_advisory_index_url_mismatch"),
    (h.index(url="https://www.nhc.noaa.gov/text/MIATCPEP4.shtml"), "nhc_advisory_index_url_mismatch"),
    (h.index(name="Different"), "nhc_advisory_contradictory"),
    (h.index(issuance="2026-10-29T21:00:00"), "nhc_advisory_format_drift"),  # Naive time is not an instant.
    (h.index(issuance="2026-10-29T18:00:00.000Z"), "nhc_advisory_issue_mismatch"),
    (b'{"activeStorms": [], "activeStorms": []}', "nhc_advisory_index_invalid"),
    (b'{"activeStorms": [NaN]}', "nhc_advisory_index_invalid"),
    (b'{"storms": []}', "nhc_advisory_format_drift"),
    (b"x" * (128 * 1024 + 1), "nhc_advisory_index_bound"),
], ids=["absent", "superseded", "older", "other-host", "http", "other-bin", "name", "naive-issuance",
        "issuance-mismatch", "duplicate-key", "nan", "drift", "oversized"])
def test_index_must_currently_name_exactly_this_advisory(index_bytes, code):
    held(code, index_bytes=index_bytes)


def test_two_index_rows_for_one_storm_are_contradictory():
    row = json.loads(h.index())["activeStorms"][0]
    held("nhc_advisory_contradictory", index_bytes=json.dumps({"activeStorms": [row, row]}).encode())


@pytest.mark.parametrize("page_bytes,code", [
    (h.page(before="<pre>other</pre>"), "nhc_advisory_format_drift"),
    (b"<html>no product</html>", "nhc_advisory_format_drift"),
    (h.page(h.bulletin().replace("BULLETIN", "BULLETIN\n<b>x</b>")), "nhc_advisory_markup_in_product"),
    (h.page(h.bulletin().replace("of 1 to 3", "of 1&ndash;3")), "nhc_advisory_markup_in_product"),
    (h.page(h.bulletin().replace("Example Province", "Provincia Ejémplo")), "nhc_advisory_encoding_invalid"),
    (h.page(h.bulletin(terminator="")), "nhc_advisory_partial_response"),
    (h.page(h.bulletin()[:120]), "nhc_advisory_partial_response"),
    (h.page(h.bulletin(awips="TCPSP5")), "nhc_advisory_format_drift"),
    (h.page(h.bulletin(office="NWS Example Center Somewhere       EP492026")), "nhc_advisory_format_drift"),
    (h.page(h.bulletin(local="200 PM XST Thu Oct 29 2026", summary="200 PM XST...2100 UTC")),
     "nhc_advisory_time_unsupported"),
    (h.page(h.bulletin(local="200 PM MST Fri Oct 29 2026")), "nhc_advisory_time_invalid"),
    (h.page(h.bulletin(summary="200 PM MST...2000 UTC")), "nhc_advisory_time_contradictory"),
    (h.page(h.bulletin(wmo="WTPZ35 KNHC 281200")), "nhc_advisory_time_contradictory"),
    (h.page(h.bulletin(advisory="35")), "nhc_advisory_issue_mismatch"),
    (h.page(h.bulletin(hazard="WIND: Invented gusts near Example Province.")), "nhc_advisory_hazard_absent"),
    (h.page(h.bulletin(hazard=h.HAZARD.replace("Example Province", "Example Provinces"))),
     "nhc_advisory_place_unanchored"),
    (h.page(h.bulletin(extra=h.HAZARD + "\n")), "nhc_advisory_contradictory"),
    (h.page(h.bulletin(office="NWS National Hurricane Center Miami FL       EP482026")),
     "nhc_advisory_contradictory"),
    (h.page() + b"\xff", "nhc_advisory_encoding_invalid"),
    (b"<pre>" + b"A" * (16 * 1024 + 1) + b"</pre>", "nhc_advisory_bulletin_bound"),
], ids=["two-pre", "no-pre", "markup", "entity", "non-ascii", "no-terminator", "truncated", "spanish-awips",
        "office", "unknown-zone", "weekday", "summary-utc", "wmo-time", "advisory-number", "hazard-absent",
        "place-substring", "duplicate-hazard", "atcf", "undecodable", "oversized-bulletin"])
def test_page_and_bulletin_drift_hold_before_paid_work(page_bytes, code):
    held(code, page_bytes=page_bytes)


@pytest.mark.parametrize("captured,now,code", [
    (h.CAPTURED, h.CAPTURED + timedelta(minutes=30), "nhc_advisory_operator_deadline_passed"),
    (h.CAPTURED, h.CAPTURED + timedelta(minutes=29, seconds=59), None),
    (h.ISSUED + timedelta(hours=6), h.ISSUED + timedelta(hours=6), None),
    (h.ISSUED + timedelta(hours=6), h.ISSUED + timedelta(hours=6, seconds=1), "nhc_advisory_issue_too_old"),
    (h.ISSUED - timedelta(minutes=1), h.NOW, "nhc_advisory_time_incoherent"),  # Captured before issue.
    (h.NOW + timedelta(minutes=1), h.NOW, "nhc_advisory_time_incoherent"),  # Capture in the future.
])
def test_source_clock_boundaries(captured, now, code):
    run = lambda: validate_capture(h.capture(captured=captured), h.selected(), now=now)  # noqa: E731
    if code is None:
        run()
        return
    with pytest.raises(AdvisoryHold) as raised:
        run()
    assert raised.value.code == code


def test_future_issue_and_naive_or_offset_clocks_hold():
    from datetime import datetime
    with pytest.raises(AdvisoryHold) as naive:
        validate_capture(h.capture(), h.selected(), now=datetime(2026, 10, 29, 21, 30))
    assert naive.value.code == "nhc_advisory_clock_invalid"
    future = AdvisoryCapture(h.index(issuance="2026-10-30T03:00:00.000Z"),
                             h.page(h.bulletin(local="800 PM MST Thu Oct 29 2026", summary="800 PM MST...0300 UTC",
                                               wmo="WTPZ35 KNHC 300231")), "2026-10-30T03:05:00Z")
    with pytest.raises(AdvisoryHold) as ahead:
        validate_capture(future, h.selected(), now=h.NOW)
    assert ahead.value.code == "nhc_advisory_time_incoherent"


def test_local_issue_converts_across_the_utc_date_boundary():
    raw = h.bulletin(local="800 PM MST Thu Oct 29 2026", summary="800 PM MST...0300 UTC", wmo="WTPZ35 KNHC 300231")
    assert parse_bulletin(raw.encode()).issued_at == "2026-10-30T03:00:00Z"


@pytest.mark.parametrize("path,value", [
    (("times", "upstream_expiry"), "2026-10-30T03:00:00Z"),  # No synthetic expiry can be smuggled in.
    (("times", "operator_recheck_deadline"), "2026-10-29T22:30:00Z"),
    (("hazard", "text"), "RAINFALL: Severe flooding has occurred."),
    (("bulletin_utf8",), h.bulletin().replace("1 to 3", "5 to 9")),
    (("nomination", "unexpected"), True),
    (("unexpected",), "held, not absent"),
], ids=["expiry", "deadline", "hazard-text", "bulletin", "nomination-field", "record-field"])
def test_retained_bundle_changes_or_unknown_fields_are_held(path, value):
    bundle = build_nhc_advisory_bundle(evidence())
    raw = deepcopy(bundle.to_dict())
    target = raw["raw_signal_dump"]["nhc_advisory"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(AdvisoryHold) as raised:
        RetainedAdvisory(StoryBundle(**raw))
    assert raised.value.code in ("nhc_advisory_retained_invalid", "nhc_advisory_nomination_invalid")


def test_old_warning_and_unrelated_bundle_fingerprints_are_unchanged():
    from src.two_bot.intern.warnings import build_warning_bundle
    from tests.gist_published_helpers import cone_bundle
    from tests.warning_helpers import NOW, encode, nomination as warning_nomination, packet
    metadata, raw = packet()
    encoded = encode(metadata)
    warning = build_warning_bundle(encoded, raw, nomination=warning_nomination(encoded, raw), now=NOW)
    assert fingerprint(warning.to_dict()) == BASE["warning"]
    assert fingerprint(cone_bundle()) == BASE["cone"]
