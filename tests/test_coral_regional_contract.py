"""Invented complete wire packets; no NOAA or provider requests."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from unittest.mock import Mock

import pytest
import requests

from src.data import coral_dhw
from src.data import coral_regional_contract as c
from src.data.source_status import SourceFetchError
from src.two_bot import writer, fact_check
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.scientific_claims import scientific_claim_failures
from src.two_bot.types import MemorySlice
from tests.coral_regional_fixtures import (
    packet,
    receipts,
    range_headers,
    reading,
    bundle,
    Response,
    install_transport,
)


def decode(p):
    station, index, header, tail = receipts(p)
    return c.decode_station(station, index, p["header"], header, p["tail"], tail, max_age_days=5)


def test_qualified_packet_preserves_scope_dates_and_detached_receipts():
    r = reading()
    assert c.qualified_provenance(r)
    assert r.provenance["header"]["first_dhw_date"] == "2001-03-25"
    assert r.provenance["header"]["first_baa_date"] == "2001-03-31"
    event = coral_dhw.detect_dhw_thresholds([r])[0]
    assert event.baa_7day_max == 3 and event.source_leg is None
    b = bundle()
    assert audit_story_bundle(b).prompt_ready
    facts = {f["label"]: f["value"] for f in b.current_facts}
    assert facts["baa_window_days"] == 7 and facts["dhw_window_weeks"] == 12
    assert "map marker" in facts["sample_scope"]
    before = deepcopy(event.provenance)
    r.provenance["tail"]["etag"] = '"changed"'
    assert event.provenance == before
    b.raw_signal_dump["provenance"]["header"]["columns"].append("bad")
    assert not audit_story_bundle(b).prompt_ready


@pytest.mark.parametrize(
    "value,tier", [(3.96, None), (4, 4), (7.96, 4), (8, 8), (11.96, 8), (12, 12), (101, 12)]
)
def test_unrounded_dhw_and_no_undocumented_regional_upper_bound(value, tier):
    r = reading(value)
    events = coral_dhw.detect_dhw_thresholds([r])
    assert r.dhw_value == value
    if tier is None:
        assert not events
    else:
        assert events[0].dhw_tier == tier and events[0].dhw_value == value


@pytest.mark.parametrize("value", [3.96, 8.25])
def test_complete_primary_transport_has_three_requests_even_below_threshold(value, monkeypatch):
    p = packet(value)
    responses, calls = install_transport(monkeypatch, p)
    backup = Mock(side_effect=AssertionError("healthy primary must not use backup"))
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", backup)
    result = coral_dhw.fetch_coral_dhw(strict=True)
    assert len(result) == 1 and c.qualified_provenance(result[0])
    assert len(calls) == 3 and all(r.closed for r in responses)
    assert [r.consumed for r in responses] == [len(p["index"]), 8192, 2049]
    for _, kwargs in calls:
        assert kwargs["stream"] and not kwargs["allow_redirects"]
        assert kwargs["attempts"] == 3 and kwargs["timeout"] == 30
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
    assert calls[2][1]["headers"]["If-Match"] == p["etag"]
    backup.assert_not_called()


@pytest.mark.parametrize(
    "bad,good",
    [
        (b"Version 3.2", b"Version 3.1"),
        (b"Bleaching Alert Level 5", b"Bleaching Alert Level 1"),
        (b"data/other.txt", b"data/invented_reef.txt"),
        (b"data/../invented_reef.txt", b"data/invented_reef.txt"),
        (b"gauges/other.php", b"gauges/invented_reef.php"),
        (b"timeseries/invented.php#other", b"timeseries/invented.php#invented_reef"),
        (b"", b'<a href="data/invented_reef.txt">txt</a>'),
        (b"", b"</tr>"),
        (b"", b"Invented Reef"),
    ],
)
def test_malformed_station_index_rejects_instead_of_silently_skipping(bad, good):
    p = packet()
    body = p["index"].replace(good, bad)
    with pytest.raises(SourceFetchError):
        c.decode_index(body, retrieved_at=c.now_utc(), max_age_days=5)


def test_exact_duplicate_index_rows_coalesce_but_conflicting_rows_reject():
    p = packet()
    body = p["index"]
    row = body[body.index(b"<tr>") : body.index(b"</tr>") + 5]
    dup = body.replace(b"</table>", row + b"</table>")
    assert len(c.decode_index(dup, retrieved_at=c.now_utc(), max_age_days=5)[0]) == 1
    bad = body.replace(b"</table>", row.replace(b"Invented Reef", b"Another Reef") + b"</table>")
    with pytest.raises(SourceFetchError, match="conflicting"):
        c.decode_index(bad, retrieved_at=c.now_utc(), max_age_days=5)


@pytest.mark.parametrize(
    "case",
    [
        "stale",
        "future",
        "version_missing",
        "version_duplicate",
        "date_duplicate",
        "utf8",
        "oversized",
        "empty",
    ],
)
def test_index_identity_freshness_and_byte_limits(case):
    p = packet()
    body = p["index"]
    if case in ["stale", "future"]:
        body = packet(day=datetime.now(UTC).date() + timedelta(days=-6 if case == "stale" else 1))[
            "index"
        ]
    elif case == "version_missing":
        body = body.replace(b"Version 3.1", b"unknown")
    elif case == "version_duplicate":
        body += b"Version 3.1"
    elif case == "date_duplicate":
        body += body
    elif case == "utf8":
        body += b"\xff"
    elif case == "oversized":
        body = b"x" * (c.INDEX_LIMIT + 1)
    else:
        body = b""
    with pytest.raises(SourceFetchError):
        c.decode_index(body, retrieved_at=c.now_utc(), max_age_days=5)


@pytest.mark.parametrize(
    "case",
    [
        "status200",
        "redirect",
        "precondition",
        "missing_etag",
        "weak_etag",
        "bad_etag",
        "compressed",
        "multipart",
        "range_missing",
        "range_leading_zero",
        "range_start",
        "range_end",
        "range_total",
        "too_small",
        "too_large",
        "content_length",
        "underread",
        "overread",
        "stream_error",
    ],
)
def test_bad_tail_closes_and_does_not_retry_parser_failures(case, monkeypatch):
    p = packet()
    h = range_headers(p, "tail")
    body = p["tail"]
    status = 206
    if case.startswith("status"):
        status = 200
    elif case == "redirect":
        status = 302
    elif case == "precondition":
        status = 412
    elif case == "missing_etag":
        h.pop("ETag")
    elif case == "weak_etag":
        h["ETag"] = 'W/"weak"'
    elif case == "bad_etag":
        h["ETag"] = '"bad\nvalue"'
    elif case == "compressed":
        h["Content-Encoding"] = "gzip"
    elif case == "multipart":
        h["Content-Type"] = "multipart/byteranges"
    elif case == "range_missing":
        h.pop("Content-Range")
    elif case == "range_leading_zero":
        h["Content-Range"] = h["Content-Range"].replace("bytes ", "bytes 0")
    elif case == "range_start":
        h["Content-Range"] = f"bytes 1-{p['total'] - 1}/{p['total']}"
    elif case == "range_end":
        h["Content-Range"] = f"bytes {p['total'] - 8192}-{p['total'] - 2}/{p['total']}"
    elif case == "range_total":
        h["Content-Range"] = "bytes 1-8192/*"
    elif case in ["too_small", "too_large"]:
        total = 8191 if case == "too_small" else c.TOTAL_LIMIT + 1
        h["Content-Range"] = f"bytes {total - 8192}-{total - 1}/{total}"
    elif case == "content_length":
        h["Content-Length"] = "1"
    elif case == "underread":
        body = body[:-1]
    elif case == "overread":
        body += b"x"
    response = Response(body, status, h)
    if case == "stream_error":
        response.iter_content = Mock(side_effect=requests.ConnectionError("invented disconnect"))
    transport = Mock(return_value=response)
    monkeypatch.setattr(coral_dhw, "fetch_with_retry", transport)
    with pytest.raises(SourceFetchError):
        coral_dhw._fetch_regional_bytes(p["url"], kind="tail")
    assert response.closed
    transport.assert_called_once()


@pytest.mark.parametrize("change", ["etag", "size", "start", "end"])
def test_header_cannot_mix_source_versions(change):
    p = packet()
    tail = c.response_range(206, range_headers(p, "tail"), kind="tail")
    h = range_headers(p, "header")
    if change == "etag":
        h["ETag"] = '"new-version"'
    else:
        start, end, total = (
            (1 if change == "start" else 0),
            (2047 if change == "end" else 2048),
            p["total"] + (1 if change == "size" else 0),
        )
        h["Content-Range"] = f"bytes {start}-{end}/{total}"
    with pytest.raises(SourceFetchError):
        c.response_range(206, h, kind="header", prior=tail)


@pytest.mark.parametrize(
    "case",
    [
        "label",
        "name",
        "lat",
        "lon",
        "mmm",
        "months_count",
        "months_nan",
        "first_date",
        "reversed_dates",
        "future_start",
        "columns",
        "separator",
        "ascii",
    ],
)
def test_header_layout_dates_and_finite_values(case):
    p = packet()
    lines = p["header"].decode().splitlines(keepends=True)
    edits = {
        "label": (0, "Other:\n"),
        "name": (1, "Other Reef\n"),
        "lat": (7, "91\n"),
        "lon": (4, "-181\n"),
        "mmm": (10, "nan\n"),
        "months_count": (13, "1 2 3\n"),
        "months_nan": (13, "nan " * 12 + "\n"),
        "first_date": (16, "2001 03 25\n"),
        "reversed_dates": (16, "2001 01 04\n"),
        "future_start": (19, "9999 31 12\n"),
        "columns": (21, "YYYY MM DD SST\n"),
        "separator": (2, "not blank\n"),
        "ascii": (1, "\N{SNOWMAN}\n"),
    }
    i, value = edits[case]
    lines[i] = value
    p["header"] = "".join(lines).encode()
    p["header"] = (p["header"] + b" " * 2049)[:2049]
    with pytest.raises(SourceFetchError):
        decode(p)


@pytest.mark.parametrize(
    "case",
    [
        "negative_dhw",
        "infinite_dhw",
        "nan_sst",
        "negative_hotspot",
        "sst_order",
        "fractional_baa",
        "high_baa",
        "extra",
        "missing",
        "bad_date",
        "duplicate",
        "gap",
        "future_day",
        "index_label",
        "newline",
        "ascii",
        "bad_middle",
    ],
)
def test_tail_rejects_every_malformed_record_not_only_latest(case):
    p = packet()
    rows = p["tail"].decode().splitlines(keepends=True)
    f = rows[-1].split()
    mutations = {
        "negative_dhw": (8, "-0.1"),
        "infinite_dhw": (8, "inf"),
        "nan_sst": (3, "nan"),
        "negative_hotspot": (7, "-1"),
        "sst_order": (5, "40"),
        "fractional_baa": (9, "3.1"),
        "high_baa": (9, "5"),
        "bad_date": (2, "40"),
        "index_label": (9, "2"),
    }
    if case in mutations:
        i, value = mutations[case]
        f[i] = value
        rows[-1] = " ".join(f) + "\n"
    elif case == "extra":
        rows[-1] = rows[-1].rstrip() + " extra\n"
    elif case == "missing":
        rows[-1] = " ".join(f[:-1]) + "\n"
    elif case == "duplicate":
        rows[-2] = rows[-1]
    elif case == "gap":
        rows.pop(-2)
    elif case == "future_day":
        rows[-1] = (
            f"{datetime.now(UTC).date() + timedelta(days=1):%Y %m %d} " + " ".join(f[3:]) + "\n"
        )
    elif case == "ascii":
        rows[-1] += "\N{SNOWMAN}\n"
    elif case == "bad_middle":
        rows[10] = "malformed\n"
    body = "".join(rows).encode()
    # Pad/truncate only the discardable first line to keep the transport shape.
    first, remainder = body.split(b"\n", 1)
    body = b"x" * (8192 - len(remainder) - 1) + b"\n" + remainder
    if case == "newline":
        body = body[:-1] + b"x"
    p["tail"] = body
    with pytest.raises(SourceFetchError):
        decode(p)


@pytest.mark.parametrize("field", sorted(c._RECEIPT_KEYS))
def test_each_missing_receipt_field_rejects_before_paid_boundaries(field, monkeypatch):
    b = bundle()
    b.raw_signal_dump["provenance"].pop(field)
    assert_rejected_without_provider(b, monkeypatch)


def assert_rejected_without_provider(b, monkeypatch):
    before = deepcopy(b)
    assert not audit_story_bundle(b).prompt_ready
    w, f = Mock(), Mock()
    monkeypatch.setattr(writer, "_call_writer_provider", w)
    monkeypatch.setattr(fact_check, "_call_gemini", f)
    assert writer.write_tweet(b, MemorySlice()).tweet is None
    assert not fact_check.fact_check(
        "The region has 8.25°C-weeks of accumulated heat stress.", [], b, {}
    ).passed
    w.assert_not_called()
    f.assert_not_called()
    assert b == before


@pytest.mark.parametrize(
    "field,bad",
    [
        ("schema_version", True),
        ("dhw_value", True),
        ("dhw_value", float("nan")),
        ("baa_7day_max", True),
        ("baa_7day_max", 3.0),
        ("baa_window_days", True),
        ("marker_point", [True, 151.125]),
        ("marker_point", [91, 151.125]),
        ("source_url", "https://example.invalid/x"),
        ("method", "invented method"),
        ("stress_level", "Bleaching Alert Level 2"),
        ("region_id", "../reef"),
        ("source_product", "other"),
        ("source_leg", "crw_erddap"),
    ],
)
def test_receipt_value_mutations_reject(field, bad, monkeypatch):
    b = bundle()
    b.raw_signal_dump["provenance"][field] = bad
    assert_rejected_without_provider(b, monkeypatch)


@pytest.mark.parametrize(
    "part,field",
    [
        (part, field)
        for part, keys in [
            ("index", c._INDEX_KEYS),
            ("header", c._HEADER_KEYS),
            ("tail", c._TAIL_KEYS),
        ]
        for field in sorted(keys)
    ],
)
def test_each_missing_nested_receipt_field_rejects(part, field):
    r = reading()
    r.provenance[part].pop(field)
    assert not c.qualified_provenance(r)


@pytest.mark.parametrize(
    "part,field,bad",
    [
        ("index", "response_sha256", "bad"),
        ("index", "response_bytes", True),
        ("index", "index_date", "2000-01-01"),
        ("index", "retrieved_at", "9999-01-01T00:00:00Z"),
        ("header", "columns", list(reversed(c.COLUMNS))),
        ("header", "etag", '"changed"'),
        ("header", "range_start", True),
        ("header", "total_bytes", 8192),
        ("header", "first_dhw_date", "9999-01-01"),
        ("header", "response_bytes", 2048),
        ("tail", "complete_row_count", True),
        ("tail", "complete_row_count", 6),
        ("tail", "first_retained_date", "2001-01-01"),
        ("tail", "last_retained_date", "2001-01-01"),
        ("tail", "range_end", 0),
        ("tail", "response_sha256", "bad"),
    ],
)
def test_nested_receipt_mutations_reject(part, field, bad):
    r = reading()
    r.provenance[part][field] = bad
    assert not c.qualified_provenance(r)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("where", "Elsewhere"),
        ("when", "2001-01-01"),
        ("event_id", "other"),
        ("headline_metric", {}),
        ("current_facts", []),
        ("historical_context", {}),
        ("raw_signal_dump", {}),
    ],
)
def test_current_bundle_projection_cannot_drift(field, bad, monkeypatch):
    b = bundle()
    setattr(b, field, bad)
    assert_rejected_without_provider(b, monkeypatch)


@pytest.mark.parametrize("leg", [None, "crw_virtual_station", "unknown", "crw_erddap"])
def test_legacy_or_changed_source_leg_cannot_bypass_either_contract(leg, monkeypatch):
    b = bundle()
    b.raw_signal_dump.pop("provenance")
    b.raw_signal_dump["source_leg"] = leg
    assert_rejected_without_provider(b, monkeypatch)


@pytest.mark.parametrize("code,label", list(enumerate(c.LABELS)))
@pytest.mark.parametrize("prefix", ["7-day maximum was", "seven-day peak:", "7–day max of"])
def test_correct_window_labels_still_require_actual_model_check(code, label, prefix, monkeypatch):
    b = bundle(12.5, code)
    text = f"The regional {prefix} {label}."
    assert scientific_claim_failures(text, b) == []
    assert fact_check.local_rejection(text, [], b, {}) is None
    call = Mock(
        return_value='{"passed":false,"failures":["Synthetic unresolved claim"],"extracted_claims":[]}'
    )
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    assert not fact_check.fact_check(text, [], b, {}).passed
    call.assert_called_once()


@pytest.mark.parametrize(
    "text",
    [
        "The region is at Alert Level 1.",
        "7-day maximum was Alert Level 2.",
        "7-day maximum was Alert Level 3.",
        "seven-day peak: Level IV.",
        "7-day maximum was elsewhere. Alert Level 1 here.",
        "7-day maximum was\nAlert Level 1.",
        "7-day maximum was; Alert Level 1.",
        "7-day maximum was, Alert Level 1.",
        "7-day maximum was Alert Level 1 and Alert Level 1.",
        "No Stress.",
        "Bleaching Watch.",
        "Bleaching Warning.",
    ],
)
def test_unqualified_or_mismatched_primary_label_never_calls_checker(text, monkeypatch):
    b = bundle()
    call = Mock()
    monkeypatch.setattr(fact_check, "_call_gemini", call)
    assert any(x.startswith("unwarranted_coral_alert:") for x in scientific_claim_failures(text, b))
    assert not fact_check.fact_check(text, [], b, {}).passed
    call.assert_not_called()


def test_same_dhw_different_supplied_baa_is_not_recomputed():
    for code in range(5):
        r = reading(12.5, code)
        assert r.stress_level == c.LABELS[code] and r.baa_7day_max == code
        assert c.qualified_provenance(r)


def test_direct_receipt_hash_must_bind_consumed_body():
    p = packet()
    station, index, head, tail = receipts(p)
    tail["response_sha256"] = "0" * 64
    with pytest.raises(SourceFetchError, match="body receipt"):
        c.decode_station(station, index, p["header"], head, p["tail"], tail, max_age_days=5)


def test_source_event_semantic_mutation_rejects():
    r = reading()
    for field, bad in [
        ("dhw_value", 12),
        ("baa_7day_max", 4),
        ("source_leg", "crw_erddap"),
        ("lat", 0),
        ("region_full_name", "Other"),
        ("date", "2001-01-01"),
    ]:
        assert not c.qualified_provenance(replace(r, **{field: bad}))


def test_valid_no_stress_index_returns_empty_without_backup(monkeypatch):
    p = packet(1, 0)
    responses, calls = install_transport(monkeypatch, p)
    backup = Mock(side_effect=AssertionError("valid empty result is not failure"))
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", backup)
    assert coral_dhw.fetch_coral_dhw(strict=True) == []
    assert len(calls) == 1 and responses[0].closed
    backup.assert_not_called()


def test_all_failed_primary_ranges_use_existing_backup(monkeypatch):
    p = packet()
    response = Response(p["index"], 200)
    transport = Mock(side_effect=[response, requests.Timeout("invented timeout")])
    monkeypatch.setattr(coral_dhw, "fetch_with_retry", transport)
    from tests.coral_point_fixtures import reading as point_reading

    fallback = [point_reading()]
    backup = Mock(return_value=fallback)
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", backup)
    assert coral_dhw.fetch_coral_dhw(strict=True) == fallback
    assert transport.call_count == 2 and response.closed
    backup.assert_called_once()


@pytest.mark.parametrize("part", [None, "index", "header", "tail"])
def test_extra_receipt_keys_are_not_silently_ignored(part):
    r = reading()
    receipt = r.provenance if part is None else r.provenance[part]
    receipt["extra"] = "unbound"
    assert not c.qualified_provenance(r)


@pytest.mark.parametrize(
    "field", ["index_hash", "header_hash", "tail_hash", "index_bytes", "retrieval"]
)
def test_coherent_receipt_substitution_invalidates_review_and_approval(field):
    from src.editorial.revisions import (
        record_human_review,
        authorize_draft,
        review_is_current,
        approval_is_current,
    )

    b = bundle()
    p = b.raw_signal_dump["provenance"]
    earlier = datetime.now(UTC) - timedelta(seconds=10)
    for part in ["index", "tail", "header"]:
        p[part]["retrieved_at"] = earlier.strftime("%Y-%m-%dT%H:%M:%SZ")
    d = {
        "id": "invented-regional",
        "text": "The region has 8.25°C-weeks of accumulated heat stress.",
        "type": "coral_bleaching",
        "event_id": b.event_id,
        "review_context": {"two_bot": {"bundle": b.to_dict()}},
    }
    record_human_review(d)  # Offline decision fixture, not a human quality rating.
    authorize_draft(d, "manual")
    assert review_is_current(d) and approval_is_current(d, "manual")
    if field.endswith("_hash"):
        p[field.split("_")[0]]["response_sha256"] = "0" * 64
    elif field == "index_bytes":
        p["index"]["response_bytes"] += 1
    else:
        p["header"]["retrieved_at"] = (earlier + timedelta(seconds=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    assert audit_story_bundle(
        b
    ).prompt_ready  # Receipt structure does not authenticate source bytes.
    assert not review_is_current(d) and not approval_is_current(d, "manual")


def test_partial_primary_failure_preserves_other_station_without_backup(monkeypatch):
    good, bad = packet(), packet(region_id="other_reef", name="Other Reef")
    row = bad["index"][bad["index"].index(b"<tr>") : bad["index"].index(b"</tr>") + 5]
    good["index"] = good["index"].replace(b"</table>", row + b"</table>")
    responses, calls = install_transport(monkeypatch, good)
    original = coral_dhw.fetch_with_retry

    def fetch(url, **kwargs):
        if url == bad["url"]:
            raise requests.Timeout("invented timeout")
        return original(url, **kwargs)

    monkeypatch.setattr(coral_dhw, "fetch_with_retry", fetch)
    backup = Mock(side_effect=AssertionError("partial primary remains primary"))
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", backup)
    rows = coral_dhw.fetch_coral_dhw(strict=True)
    assert (
        len(rows) == 1 and rows[0].region_id == "invented_reef" and c.qualified_provenance(rows[0])
    )
    assert all(r.closed for r in responses) and len(calls) == 3
    backup.assert_not_called()


def test_schema_failure_does_not_masquerade_as_backup_recovery(monkeypatch):
    p = packet()
    p["etag"] = 'W/"weak"'
    responses, calls = install_transport(monkeypatch, p)
    backup = Mock(side_effect=AssertionError("schema failure must stay visible"))
    monkeypatch.setattr(coral_dhw, "_fetch_coral_dhw_erddap", backup)
    with pytest.raises(SourceFetchError, match="schema drift"):
        coral_dhw.fetch_coral_dhw(strict=True)
    assert len(calls) == 2 and all(r.closed for r in responses)
    backup.assert_not_called()


@pytest.mark.parametrize(
    "code,other", [(code, other) for code in range(5) for other in range(5) if code != other]
)
def test_every_wrong_primary_label_is_rejected(code, other):
    b = bundle(12.5, code)
    assert scientific_claim_failures(f"The 7-day maximum was {c.LABELS[other]}.", b)


@pytest.mark.parametrize("day_offset", [-6, 1])
def test_retained_receipt_cannot_reenter_when_source_date_is_stale_or_future(
    day_offset, monkeypatch
):
    from freezegun import freeze_time

    r = reading()
    # Move the reader clock; do not edit the captured packet to manufacture freshness.
    offset = 7 if day_offset == -6 else -2
    clock = datetime.now(UTC) + timedelta(days=offset)
    with freeze_time(clock):
        assert not c.qualified_provenance(r)


def test_index_transport_bound_closes_oversized_response(monkeypatch):
    response = Response(b"x" * (c.INDEX_LIMIT + 1), 200)
    transport = Mock(return_value=response)
    monkeypatch.setattr(coral_dhw, "fetch_with_retry", transport)
    with pytest.raises(SourceFetchError, match="byte limit"):
        coral_dhw._fetch_regional_bytes(c.INDEX_URL, kind="index")
    assert response.closed and response.consumed == c.INDEX_LIMIT + 1
    transport.assert_called_once()


def test_header_date_ambiguity_always_uses_year_day_month():
    p = packet()
    p["header"] = p["header"].replace(b"2001 25 03", b"2001 03 02")
    assert decode(p)["header"]["first_dhw_date"] == "2001-02-03"


def test_too_few_complete_tail_days_rejects():
    p = packet()
    rows = p["tail"].splitlines(keepends=True)[-6:]
    tail = b"".join(rows)
    p["tail"] = b"x" * (8192 - len(tail) - 1) + b"\n" + tail
    with pytest.raises(SourceFetchError, match="completeness"):
        decode(p)


def test_malformed_extra_data_link_cannot_be_ignored():
    p = packet()
    p["index"] = p["index"].replace(
        b"</table>", b'<tr><td><a href="data/broken.txt?bad">txt</a></td></tr></table>'
    )
    with pytest.raises(SourceFetchError, match="station-bearing"):
        decode(p)


def test_review_headline_keeps_source_precision(monkeypatch, fresh_state):
    from src.orchestrator.sources import coral_dhw as runner

    r = reading(7.96)
    monkeypatch.setattr(runner, "_fetch_strict", lambda *a, **k: [r])
    monkeypatch.setattr(runner, "_should_draft", lambda *a, **k: True)
    review = Mock(return_value={})
    enqueue = Mock()
    monkeypatch.setattr(runner, "_review_context", review)
    monkeypatch.setattr(runner, "_enqueue_story_candidate", enqueue)
    runner.run_coral_dhw(fresh_state, {"sources": []})
    assert "7.96" in review.call_args.kwargs["headline"]
    assert enqueue.call_args.kwargs["bundle"].headline_metric["value"] == 7.96
