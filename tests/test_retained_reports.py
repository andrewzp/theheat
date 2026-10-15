"""Pure contract refusals with invented report data; no source/model calls."""
from copy import deepcopy

import pytest

from src.storage.retained_reports import ReportError, legacy_news_document, timestamp


def test_legacy_verified_metadata_never_supplies_original_dates_or_source_truth():
    original = dict(kind="heat_mortality", confidence="verified", headline="Invented report",
        window_start="2026-10-11", window_end="2026-10-11", impact=[dict(claim="Invented reported number", value=4,
            source_name="Invented agency", url="https://example.test/report", as_of="2026-10-11")])
    before = deepcopy(original)
    result = legacy_news_document(original, lineage_id="fixture:legacy", captured_at="2026-10-11T12:00:00Z")
    assert original == before and result["legacy_metadata"] == before
    assert result["claims"][0]["source_review"] == dict(status="pending", decision_ref=None)
    assert result["claims"][0]["original_language"] == "und"
    assert all(value is None for value in result["claims"][0]["times"].values())
    assert result["claims"][0]["identity_reference"] is None and result["claims"][0]["anchors"] == []
    assert result["reference_review"]["benchmark_eligible"] is False


@pytest.mark.parametrize("value", [
    dict(original="local", utc="2026-10-11T12:00:00Z", date=None, precision="unknown", timezone=None),
    dict(original="Oct11", utc=None, date="2026-10-11", precision="instant", timezone=None),
    dict(original="October32", utc=None, date="2026-10-32", precision="calendar", timezone=None),
    dict(original="unknown", utc=None, date=None, precision=True, timezone=None),
])
def test_time_precision_cannot_be_upgraded_by_filling_a_different_field(value):
    with pytest.raises(ValueError):
        timestamp(value)


def test_known_calendar_label_preserves_unknown_timezone_and_no_utc():
    value = dict(original="11October2026, local", utc=None, date="2026-10-11", precision="calendar", timezone=None)
    before = deepcopy(value)
    timestamp(value)
    assert value == before


def test_legacy_no_source_is_refused_instead_of_filling_fake_attribution():
    with pytest.raises(ReportError):
        legacy_news_document(dict(headline="Invented missing source"), lineage_id="fixture:legacy", captured_at="2026-10-11T12:00:00Z")
