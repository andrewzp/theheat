"""The nationwide shortlist qualifies only exact, future official forecast points."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from requests import Timeout

from src.data import nwps_major_forecasts as nwps
from src.editorial.official_warning import WarningHold
from src.editorial.revisions import authorize_draft, record_human_review
from src.editorial.warning_runtime import (
    begin_warning_provider_scope,
    end_warning_provider_scope,
    guard_warning_provider_attempt,
)
from src.orchestrator import draft_save, posting
from src.orchestrator.sources import river_gauges
from src.orchestrator.triage_queue import _drain_and_write_triage_queue
from src.state import DEFAULT_STATE
from src.two_bot import pipeline
from src.two_bot.bundle_capture import capture_bundle
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.fact_check import local_rejection
from src.two_bot.intern import nwps_forecast
from src.two_bot.intern.nwps_forecast import build_nwps_forecast_bundle, current_nwps_forecast
from tests.live_content_harness import trap_network
from tests.nhc_advisory_pipeline_helpers import stage_fakes

NOW = datetime(2026, 7, 1, 16, tzinfo=timezone.utc)
COPY = "Roads near Example River could flood Thursday as the river is forecast to hit major flood stage, the NWS says."


def source(lid="FAKF1"):
    index_row = {"gaugelid": lid, "status": "major", "state": "FL", "units": "ft",
                 "fcsttime": "2026-07-03 18:00:00", "fcstissunc": "2026-07-01 14:02:00",
                 "forecast": "17.5", "major": "17", "pedts": "HGIFF"}
    metadata = {"lid": lid, "name": "Example River", "state": {"abbreviation": "FL", "name": "Florida"},
                "pedts": {"forecast": "HGIFF"},
                "status": {"forecast": {"floodCategory": "major", "primaryUnit": "ft"}},
                "flood": {"stageUnits": "ft", "categories": {"major": {"stage": 17}},
                          "impacts": [{"stage": 17, "statement": "Some roads may flood."}]}}
    forecast = {"primaryName": "Stage", "primaryUnits": "ft", "pedts": "HGIFF",
                "issuedTime": "2026-07-01T14:00:00Z",
                "data": [{"validTime": stamp, "primary": value, "generatedTime": "2026-07-01T14:02:00Z"}
                         for stamp, value in [("2026-07-02T12:00:00Z", 16), ("2026-07-02T18:00:00Z", 17),
                                              ("2026-07-03T18:00:00Z", 17.5)]]}
    return index_row, metadata, forecast


def test_national_shortlist_binds_a_real_brief_to_the_first_supported_forecast_point():
    rows = [source(lid) for lid in ["FAKF3", "FAKF1", "FAKF2"]]
    documents = {nwps.INDEX_URL: {"features": [{"attributes": row} for row, _, _ in rows]}}
    for row, metadata, forecast in rows:
        url = nwps.GAUGES_URL + "/" + row["gaugelid"]
        documents[url] = metadata
        documents[url + "/stageflow/forecast"] = forecast
    calls = []

    def read(url, **kwargs):
        calls.append(url)
        if url == nwps.INDEX_URL:
            assert kwargs["params"]["where"] == "status='major'"
            assert kwargs["params"]["resultRecordCount"] == nwps.MAX_INDEX_ROWS + 1
        return deepcopy(documents[url])

    count, events = nwps.fetch_major_forecasts(NOW, read_json=read)
    assert count == 3
    assert [event.lid for event in events] == ["FAKF1", "FAKF2"]
    assert len(calls) == 5
    event = events[0]
    assert event.first_major_at.isoformat() == "2026-07-02T18:00:00+00:00"
    assert event.forecast_ft == 17
    bundle = build_nwps_forecast_bundle(event)
    assert not [issue for issue in audit_story_bundle(bundle).issues if issue.severity == "error"]
    assert local_rejection("NWS forecasts major flooding on Example River.", [], bundle, DEFAULT_STATE) is None
    assert local_rejection("Example River measured 17 ft.", [], bundle, DEFAULT_STATE) is not None


@pytest.mark.parametrize("change", ["threshold", "gauge", "state", "units", "series_revision", "stale", "point", "order"])
def test_mixed_source_identity_or_unsupported_points_refuse(change):
    row, metadata, forecast = source()
    if change == "threshold":
        metadata["flood"]["categories"]["major"]["stage"] = 16.0
    elif change == "gauge":
        metadata["lid"] = "FAKF2"
    elif change == "state":
        metadata["state"]["abbreviation"] = "GA"
    elif change == "units":
        forecast["primaryUnits"] = "m"
    elif change == "series_revision":
        forecast["data"][0]["generatedTime"] = "2026-07-01T13:04:00Z"
    elif change == "stale":
        forecast["issuedTime"] = "2026-07-01T08:00:00Z"
    elif change == "point":
        forecast["data"][-1]["primary"] = 17.2
    else:
        forecast["data"].reverse()
    with pytest.raises(ValueError, match="nwps_"):
        nwps.verify_major_forecast(row, metadata, forecast, NOW)


def test_duplicate_or_truncated_index_never_fetches_gauge_details():
    row, _, _ = source()
    calls = []

    def read(url, **kwargs):
        calls.append(url)
        assert url == nwps.INDEX_URL
        return {"features": [{"attributes": row}, {"attributes": deepcopy(row)}]}

    assert nwps.fetch_major_forecasts(NOW, read_json=read) == (0, [])
    assert calls == [nwps.INDEX_URL]
    with pytest.raises(ValueError, match="nwps_index_incomplete"):
        nwps.fetch_major_forecasts(NOW, read_json=lambda *_a, **_kw: {"features": [], "exceededTransferLimit": True})


def test_earlier_major_point_survives_a_later_peak():
    row, metadata, forecast = source()
    row["fcsttime"] = "2026-07-05 18:00:00"
    forecast["data"][-1]["validTime"] = "2026-07-05T18:00:00Z"
    url = nwps.GAUGES_URL + "/" + row["gaugelid"]
    documents = {nwps.INDEX_URL: {"features": [{"attributes": row}]},
                 url: metadata, url + "/stageflow/forecast": forecast}
    count, events = nwps.fetch_major_forecasts(NOW, read_json=lambda url, **_kw: documents[url])
    assert count == 1
    assert events[0].first_major_at.isoformat() == "2026-07-02T18:00:00+00:00"
    forecast["data"][1]["primary"] = 16
    assert nwps.fetch_major_forecasts(NOW, read_json=lambda url, **_kw: documents[url]) == (1, [])


@pytest.mark.parametrize("failure", ["size", "redirect", "timeout"])
def test_response_failure_closes_the_stream_without_following_redirects(monkeypatch, failure):
    calls = []

    class Response:
        status_code = 302 if failure == "redirect" else 200
        closed = False

        def iter_content(self, chunk_size):
            assert failure != "redirect"
            assert chunk_size == 8192
            if failure == "timeout":
                raise Timeout("invented stream timeout")
            yield b"x" * (nwps.MAX_DOCUMENT_BYTES + 1)

        def close(self):
            self.closed = True

    response = Response()

    def fetch(url, **options):
        calls.append(url)
        assert options["allow_redirects"] is False and options["attempts"] == 1
        return response

    monkeypatch.setattr(nwps, "fetch_with_retry", fetch)
    with pytest.raises((ValueError, Timeout)):
        nwps._read_json(nwps.INDEX_URL)
    assert response.closed and calls == [nwps.INDEX_URL]


@pytest.fixture
def journey(monkeypatch):
    trap_network(monkeypatch.setattr)
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "invented-no-provider-access")
    monkeypatch.setattr("src.voice.safety.GEMINI_API_KEY", "invented-no-provider-access")
    monkeypatch.setenv("THEHEAT_WRITER_SAMPLES", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_ENABLED", "1")
    monkeypatch.setenv("THEHEAT_CRITIC_REVISE_ENABLED", "0")
    monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
    row, meta, series = source()
    event = nwps.verify_major_forecast(row, meta, series, NOW)
    fetch = MagicMock(return_value=(1, [event]))
    recheck = MagicMock(return_value=(meta, series))
    monkeypatch.setattr(nwps, "fetch_major_forecasts", fetch)
    monkeypatch.setattr(nwps, "read_gauge_forecast", recheck)
    monkeypatch.setattr(river_gauges, "_utc_now", lambda: NOW)
    monkeypatch.setattr(draft_save, "_utc_now", lambda: NOW)
    monkeypatch.setattr(nwps_forecast, "forecast_clock", lambda: NOW)
    stages = []
    writer, safety, fact, critic = stage_fakes(stages, copy=COPY)
    monkeypatch.setattr(pipeline.writer, "write_tweet", writer)
    monkeypatch.setattr(pipeline, "run_safety_pipeline", safety)
    monkeypatch.setattr(pipeline.fact_check, "fact_check", fact)
    monkeypatch.setattr(pipeline.critic, "critic_review", critic)
    return fetch, recheck, stages, event


def run_collector():
    state = deepcopy(DEFAULT_STATE)
    run = {"id": "invented-nwps-run", "started_at": NOW.isoformat(), "sources": []}
    river_gauges.run_nwps_major_forecasts(state, run)
    _drain_and_write_triage_queue(state, run)
    return state


def test_collector_defaults_off_then_saves_only_a_checked_manual_draft(journey, monkeypatch):
    fetch, recheck, stages, _ = journey
    monkeypatch.delenv(nwps.ENABLE_FLAG, raising=False)
    assert run_collector()["drafts"] == []
    fetch.assert_not_called()
    assert stages == []

    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    draft, = run_collector()["drafts"]
    assert draft["status"] == "pending"
    assert draft["approval_policy"]["mode"] == "manual_only"
    assert "auto_approve_at" not in draft
    assert stages == ["writer", "safety", "fact_check", "critic"]
    assert recheck.call_count == 2  # One before paid generation and one before save.


def test_reissued_forecast_refuses_to_save_even_after_checks(journey, monkeypatch):
    _, recheck, stages, _ = journey
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    _, metadata, series = source()
    series["issuedTime"] = "2026-07-01T14:01:00Z"
    recheck.side_effect = [recheck.return_value, (metadata, series)]
    assert run_collector()["drafts"] == []
    assert stages == ["writer", "safety", "fact_check", "critic"]


@pytest.mark.parametrize("variable,value", [
    ("THEHEAT_WRITER_SAMPLES", "2"),
    ("THEHEAT_CRITIC_ENABLED", "0"),
    ("THEHEAT_CRITIC_REVISE_ENABLED", "1"),
])
def test_nwps_unsafe_generation_settings_stop_before_paid_work(journey, monkeypatch, variable, value):
    _, recheck, stages, _ = journey
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    monkeypatch.setenv(variable, value)
    assert run_collector()["drafts"] == []
    assert stages == []
    recheck.assert_not_called()


def test_expired_or_reissued_after_collection_never_buys_a_writer_call(journey, monkeypatch):
    _, recheck, stages, _ = journey
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    monkeypatch.setattr(nwps_forecast, "forecast_clock", lambda: NOW + timedelta(hours=7))
    assert run_collector()["drafts"] == []
    assert stages == []
    recheck.assert_not_called()
    monkeypatch.setattr(nwps_forecast, "forecast_clock", lambda: NOW)
    _, metadata, series = source()
    series["issuedTime"] = "2026-07-01T14:01:00Z"
    recheck.return_value = metadata, series
    assert run_collector()["drafts"] == []
    assert stages == []
    recheck.assert_called_once()


def test_each_provider_attempt_is_fenced_against_expiry(journey, monkeypatch):
    _, recheck, _, event = journey
    bundle = build_nwps_forecast_bundle(event)
    token = begin_warning_provider_scope(bundle, capture_bundle(bundle))
    try:
        guard_warning_provider_attempt()
        monkeypatch.setattr(nwps_forecast, "forecast_clock", lambda: NOW + timedelta(hours=7))
        with pytest.raises(WarningHold, match="nwps_forecast_expired"):
            guard_warning_provider_attempt()
    finally:
        end_warning_provider_scope(token)
    guard_warning_provider_attempt()
    recheck.assert_not_called()


def test_manual_source_boundary_rejects_changed_expired_and_automatic_drafts(journey, monkeypatch):
    _, recheck, _, event = journey
    bundle = build_nwps_forecast_bundle(event).to_dict()
    draft = {"id": "invented-nwps-draft", "event_id": bundle["event_id"], "type": "river_flood", "text": COPY,
             "status": "pending", "created_at": NOW.isoformat(), "review_context": {"two_bot": {"bundle": bundle}}}
    assert current_nwps_forecast(draft, live=True, clock=lambda: NOW) is None
    recheck.assert_called_once()
    recheck.reset_mock()
    assert current_nwps_forecast(draft, live=True, clock=lambda: NOW + timedelta(hours=7)) == "nwps_forecast_expired"
    automatic = {**draft, "auto_approve_at": NOW.isoformat()}
    assert current_nwps_forecast(automatic, live=True, clock=lambda: NOW) == "nwps_manual_review_required"
    recheck.assert_not_called()
    assert current_nwps_forecast(
        {**draft, "text": "Example River has reached major flood stage, the NWS forecasts more rain."},
        live=True, clock=lambda: NOW,
    ) == "nwps_copy_requires_attributed_forecast"
    recheck.assert_not_called()

    record_human_review(draft)
    authorize_draft(draft, "manual", "invented-intent")
    draft["status"] = "approved"
    _, metadata, series = source()
    series["issuedTime"] = "2026-07-01T14:01:00Z"
    recheck.return_value = metadata, series
    monkeypatch.setattr(posting, "_utc_now", lambda: NOW)
    send = MagicMock()
    monkeypatch.setattr(posting, "post_tweet", send)
    safety = MagicMock()
    monkeypatch.setattr(posting, "run_safety_pipeline", safety)
    storage = MagicMock()
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setenv("DRAFT_ID", draft["id"])
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = [draft]
    posting.run_manual_tweet(state)
    send.assert_not_called()
    safety.assert_not_called()
    storage.write_state.assert_not_called()
    assert "nwps_forecast_changed" in draft["post_error"]
    assert not state["publish_ledger"]


@pytest.mark.parametrize("changes_after_safety", [False, True])
def test_checked_human_review_revalidates_again_at_transport(journey, monkeypatch, changes_after_safety):
    _, recheck, _, _ = journey
    monkeypatch.setenv(nwps.ENABLE_FLAG, "1")
    state = run_collector()
    draft, = state["drafts"]
    record_human_review(draft)
    authorize_draft(draft, "manual", "invented-intent")
    draft["status"] = "approved"
    recheck.reset_mock()
    _, metadata, series = source()
    revised = deepcopy(series)
    revised["issuedTime"] = "2026-07-01T14:01:00Z"
    recheck.side_effect = [(metadata, series), (metadata, revised if changes_after_safety else series)]
    monkeypatch.setattr(posting, "_utc_now", lambda: NOW)
    send = MagicMock(return_value={"id": "invented-x-receipt"})
    monkeypatch.setattr(posting, "post_tweet", send)
    monkeypatch.setattr(posting, "post_to_bluesky", MagicMock())
    monkeypatch.setattr(posting, "_record_published_two_bot_memory", MagicMock())
    safety = MagicMock(return_value=(True, None))
    monkeypatch.setattr(posting, "run_safety_pipeline", safety)
    storage = MagicMock()
    storage.write_state.return_value = True
    storage.check_daily_cap.return_value = True
    monkeypatch.setattr(posting, "state", storage)
    monkeypatch.setenv("DRAFT_ID", draft["id"])
    monkeypatch.setenv("TWEET_TEXT", draft["text"])
    monkeypatch.setenv("PUBLISH_INTENT_ID", draft["publish_intent_id"])

    posting.run_manual_tweet(state)

    safety.assert_called_once()
    assert recheck.call_count == 2
    row = state["publish_ledger"][draft["event_id"]]
    if changes_after_safety:
        send.assert_not_called()
        assert row["phase"] == "not_sent" and draft["status"] == "pending"
    else:
        send.assert_called_once_with(COPY, media_png=None, alt_text=None)
        assert row["tweet_id"] == "invented-x-receipt"
