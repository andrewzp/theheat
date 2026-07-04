"""Tests for the newsworthiness retrieval lane (Bet A phase 0).

The iron constraint under test: no impact entry survives without
source_name + url + as_of; grounded events are verified-or-dropped.
"""

from datetime import UTC, datetime
from unittest.mock import patch

from src.data import newsworthiness as nw
from src.orchestrator.sources.newsworthiness import run_newsworthiness
from src.state import _fresh_state, record_candidate_observation, record_news_events

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _impact(**overrides):
    entry = {
        "claim": "3 firefighters killed on the Knowles fire",
        "value": 3,
        "source_name": "CPR News",
        "url": "https://example.org/knowles",
        "as_of": "2026-07-03",
    }
    entry.update(overrides)
    return entry


def _event(confidence="verified", kind="fire", **overrides):
    ev = {
        "kind": kind,
        "headline": "Knowles fire (CO)",
        "place": {"country": "United States", "admin1": "CO", "name": "Knowles"},
        "window_start": "2026-07-01",
        "window_end": "2026-07-03",
        "impact": [_impact()],
        "retrieved_via": "grounded_search",
        "confidence": confidence,
    }
    ev.update(overrides)
    return ev


class TestDeterministicFloor:
    def test_drops_impact_entries_missing_warrant(self):
        result = nw.NewsRetrievalResult()
        events = nw._floor_events(
            [
                _event(impact=[_impact(), _impact(url=""), _impact(as_of=None)]),
                _event(impact=[_impact(source_name="")]),  # left with none -> dropped
            ],
            result,
        )
        assert len(events) == 1
        assert len(events[0]["impact"]) == 1
        assert result.dropped_unwarranted == 3

    def test_value_required(self):
        assert not nw._valid_impact(_impact(value=None))
        assert not nw._valid_impact(_impact(value=""))
        assert nw._valid_impact(_impact(value=0.5))


class TestNifcLeg:
    def test_normalizes_wfigs_features(self):
        payload = {
            "features": [
                {"attributes": {
                    "IncidentName": "Knowles", "POOState": "US-CO",
                    "IncidentSize": 45000, "TotalIncidentPersonnel": 2900,
                }},
                {"attributes": {
                    "IncidentName": "Tiny", "POOState": "US-WY",
                    "IncidentSize": 10, "TotalIncidentPersonnel": 4,
                }},
            ]
        }

        class _Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        with patch.object(nw, "fetch_with_retry", return_value=_Resp()):
            events = nw._fetch_nifc_events(NOW)
        assert len(events) == 1
        ev = events[0]
        assert ev["kind"] == "fire" and ev["confidence"] == "structured"
        assert ev["place"] == {"country": "United States", "admin1": "CO", "name": "Knowles"}
        claims = [i["claim"] for i in ev["impact"]]
        assert any("2,900 personnel" in c for c in claims)
        assert any("45,000 acres" in c for c in claims)
        assert all(i["source_name"] == "NIFC" and i["url"] and i["as_of"] for i in ev["impact"])


class TestVerificationLadder:
    def test_structured_passes_untouched_unverified_needs_promotion(self):
        result = nw.NewsRetrievalResult()

        class _Page:
            text = "Three firefighters were killed on the Knowles fire."

            def raise_for_status(self):
                return None

        with patch.object(nw, "fetch_with_retry", return_value=_Page()), \
             patch.object(nw, "_call_verify_flash", return_value='{"supported": true}'):
            out = nw._verify_grounded(
                [_event(confidence="structured"), _event(confidence="unverified")], result
            )
        assert [e["confidence"] for e in out] == ["structured", "verified"]
        assert result.dropped_unverified == 0

    def test_unsupported_or_failing_verification_drops(self):
        result = nw.NewsRetrievalResult()

        class _Page:
            text = "unrelated page"

            def raise_for_status(self):
                return None

        with patch.object(nw, "fetch_with_retry", return_value=_Page()), \
             patch.object(nw, "_call_verify_flash", return_value='{"supported": false}'):
            out = nw._verify_grounded([_event(confidence="unverified")], result)
        assert out == []
        assert result.dropped_unverified == 1

    def test_verify_fetch_budget_bounds_work(self):
        result = nw.NewsRetrievalResult()
        events = [_event(confidence="unverified") for _ in range(5)]
        with patch.object(nw, "fetch_with_retry", side_effect=RuntimeError("net down")):
            out = nw._verify_grounded(events, result)
        assert out == []
        # 3 fetch attempts failed + 2 dropped on budget = all 5 dropped
        assert result.dropped_unverified == 5


class TestGroundedParse:
    def test_parses_strict_json_and_stamps_provenance(self):
        raw = (
            '[{"kind": "heat_mortality", "headline": "Europe heat deaths",'
            ' "place": {"country": "France", "admin1": null, "name": null},'
            ' "window_start": "2026-06-21", "window_end": "2026-07-01",'
            ' "impact": [{"claim": "1300 excess deaths", "value": 1300,'
            ' "source_name": "WHO", "url": "https://who.int/x", "as_of": "2026-07-01"}]}]'
        )
        events = nw._parse_grounded(raw, NOW)
        assert len(events) == 1
        assert events[0]["confidence"] == "unverified"
        assert events[0]["retrieved_via"] == "grounded_search"

    def test_garbage_and_unknown_kinds_dropped(self):
        assert nw._parse_grounded("not json", NOW) == []
        assert nw._parse_grounded('[{"kind": "sports"}]', NOW) == []


class TestStateRecording:
    def test_record_news_events_stamps_and_merges(self):
        s = _fresh_state()
        record_news_events(s, [_event()], now=NOW)
        assert len(s["news_events"]) == 1
        assert s["news_events"][0]["retrieved_at"].startswith("2026-07-04")
        # same (kind, headline, window_start) replaces, not duplicates
        record_news_events(s, [_event()], now=NOW)
        assert len(s["news_events"]) == 1

    def test_record_candidate_observation_dedups_and_prunes(self):
        s = _fresh_state()
        record_candidate_observation(
            s, event_id="fire_1", category="fire", legacy_type="fire",
            city="Grand Junction", where="near Grand Junction, Colorado", now=NOW,
        )
        record_candidate_observation(
            s, event_id="fire_1", category="fire", legacy_type="fire",
            city="Grand Junction", where="near Grand Junction, Colorado", now=NOW,
        )
        assert len(s["candidates_log"]) == 1
        assert s["candidates_log"][0]["where"] == "near Grand Junction, Colorado"


class TestRunner:
    def test_flag_off_records_skipped_and_touches_nothing(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        s = _fresh_state()
        run = {"id": "r1", "mode": "alerts", "sources": []}
        run_newsworthiness(s, run)
        assert run["sources"][0]["source"] == "newsworthiness"
        assert run["sources"][0]["status"] == "skipped"
        assert s["news_events"] == []

    def test_flag_on_records_events_and_success(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        s = _fresh_state()
        run = {"id": "r1", "mode": "alerts", "sources": []}
        result = nw.NewsRetrievalResult(events=[_event()])
        with patch(
            "src.orchestrator.sources.newsworthiness.fetch_news_events",
            return_value=result,
        ):
            run_newsworthiness(s, run)
        assert run["sources"][0]["status"] == "success"
        assert len(s["news_events"]) == 1

    def test_leg_failure_is_degraded_and_fetch_crash_is_failed_never_raises(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        s = _fresh_state()
        run = {"id": "r1", "mode": "alerts", "sources": []}
        degraded = nw.NewsRetrievalResult(events=[_event()], notes=["nifc leg failed: 503"])
        with patch(
            "src.orchestrator.sources.newsworthiness.fetch_news_events",
            return_value=degraded,
        ):
            run_newsworthiness(s, run)
        assert run["sources"][0]["status"] == "degraded"

        run2 = {"id": "r2", "mode": "alerts", "sources": []}
        with patch(
            "src.orchestrator.sources.newsworthiness.fetch_news_events",
            side_effect=RuntimeError("boom"),
        ):
            run_newsworthiness(s, run2)
        assert run2["sources"][0]["status"] == "failed"
