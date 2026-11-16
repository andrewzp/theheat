"""A declared report type cannot borrow an unrelated retained source family."""
from datetime import UTC, datetime

import pytest

from src.data import awc_observed, c3s_monthly, coastal_observed


@pytest.mark.parametrize("source,reason", [
    (awc_observed, "awc_draft_identity_changed"),
    (coastal_observed, "coastal_draft_kind_changed"),
    (c3s_monthly, "c3s_kind_changed"),
])
def test_report_requires_its_own_retained_source_family_before_live_reads(monkeypatch, source, reason):
    monkeypatch.setenv("THEHEAT_OBSERVED_WEATHER_ONLY", "1")
    foreign = {"signal_kind": "unrelated_source", "event_id": "invented-foreign-event",
               "raw_signal_dump": {}, "when": "2026-11-15T12:00:00Z"}
    draft = {"type": source.KIND, "event_id": foreign["event_id"], "text": "Invented unrelated claim.",
             "review_context": {"two_bot": {"bundle": foreign}}}
    assert source.current_draft_hold(draft, live=True, now=datetime(2026, 11, 15, 12, 10, tzinfo=UTC)) == reason


@pytest.mark.parametrize("source", [awc_observed, coastal_observed, c3s_monthly])
def test_genuinely_unrelated_draft_keeps_the_existing_no_op(source):
    foreign = {"signal_kind": "unrelated_source", "event_id": "invented-foreign-event", "raw_signal_dump": {}}
    draft = {"type": "unrelated_source", "event_id": foreign["event_id"],
             "review_context": {"two_bot": {"bundle": foreign}}}
    assert source.current_draft_hold(draft, live=True) is None
