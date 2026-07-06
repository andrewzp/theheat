"""Bet A phase A2 — boost: capped, source-required rescue at the fire score gate.

Spec §4: a strong, sourced newsworthiness match can pull a BELOW-threshold fire
signal back into contention — flat +8, hard floor threshold−8, ≥1 structured/
verified impact entry required, provenance in score.reasons. Rescue-only: a
passing score is returned untouched (no triage-ranking inflation, no reasons
pollution). Fire-only wiring in v1 (FIRMS + NIFC runners). All fixture dates
today-relative.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.editorial.newsworthiness import (
    MAX_NEWS_BOOST,
    apply_newsworthiness_boost,
    news_boost_enabled,
)
from src.editorial.scoring._shared import EditorialScore

TODAY = date.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _score(total: int, threshold: int = 64) -> EditorialScore:
    return EditorialScore(
        category="fire", severity=70, novelty=70, timeliness=70, confidence=70,
        shareability=70, sensitivity=0, total=total, threshold=threshold,
        reasons=["frp tier high"],
    )


def _fire_event(
    *,
    country: str = "United States",
    admin1: str | None = "CO",
    name: str | None = None,
    confidence: str = "structured",
    impact: list[dict] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict:
    default_impact = [{
        "claim": "1,450 personnel assigned to the Alpine fire",
        "value": 1450,
        "source_name": "NIFC",
        "url": "https://example.test/nifc",
        "as_of": _iso(0),
    }]
    return {
        "kind": "fire",
        "headline": "Alpine fire (CO)",
        "place": {"country": country, "admin1": admin1, "name": name},
        "window_start": window_start or _iso(0),
        "window_end": window_end or _iso(0),
        "impact": impact if impact is not None else default_impact,
        "retrieved_via": "feed:nifc",
        "confidence": confidence,
    }


class TestFlag:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        monkeypatch.delenv("THEHEAT_NEWS_BOOST_ENABLED", raising=False)
        assert news_boost_enabled() is False

    def test_boost_alone_is_not_enough(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        assert news_boost_enabled() is False

    def test_both_on(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        assert news_boost_enabled() is True


class TestBoostHelper:
    def test_near_miss_is_rescued_with_provenance(self):
        # The Colorado case: 62 < 64 clears with a sourced match.
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event()],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62 + MAX_NEWS_BOOST
        assert score.passes is True
        assert any(
            r.startswith(f"news_boost=+{MAX_NEWS_BOOST} per NIFC (")
            for r in score.reasons
        )
        assert "frp tier high" in score.reasons  # original reasons preserved

    def test_far_miss_is_never_resurrected(self):
        score = apply_newsworthiness_boost(
            _score(55), [_fire_event()],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 55
        assert score.passes is False
        assert not any("news_boost" in r for r in score.reasons)

    def test_passing_score_is_untouched(self):
        original = _score(80)
        score = apply_newsworthiness_boost(
            original, [_fire_event()],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score is original

    def test_no_matching_event_no_boost(self):
        score = apply_newsworthiness_boost(
            _score(62), [],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_source_required_unverified_event_never_boosts(self):
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event(confidence="unverified")],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_source_required_unwarranted_entries_never_boost(self):
        bad = [{"claim": "big fire", "value": 1, "source_name": "", "url": "", "as_of": ""}]
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event(impact=bad)],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_wrong_us_state_never_boosts(self):
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event(admin1="CO")],
            country="United States", when=_iso(0), lat=44.0, lon=-72.6,  # Vermont
        )
        assert score.total == 62

    def test_us_event_without_state_never_boosts(self):
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event(admin1=None)],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_named_event_requires_name_agreement(self):
        named = _fire_event(name="Madre")
        score = apply_newsworthiness_boost(
            _score(62), [named],
            country="United States", when=_iso(0),
            us_state="CO", incident_name="Alpine Fire",
        )
        assert score.total == 62
        agreeing = _fire_event(name="Alpine")
        score = apply_newsworthiness_boost(
            _score(62), [agreeing],
            country="United States", when=_iso(0),
            us_state="CO", incident_name="Alpine Fire",
        )
        assert score.total == 62 + MAX_NEWS_BOOST

    def test_named_event_never_boosts_nameless_fire(self):
        # Same incident-scoping as enrich: "Alpine" news must not rescue an
        # anonymous same-state hotspot.
        score = apply_newsworthiness_boost(
            _score(62), [_fire_event(name="Alpine")],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_window_outside_slack_never_boosts(self):
        stale = _fire_event(window_start=_iso(10), window_end=_iso(8))
        score = apply_newsworthiness_boost(
            _score(62), [stale],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_non_us_fire_matches_on_country(self):
        pt = _fire_event(country="Portugal", admin1=None)
        score = apply_newsworthiness_boost(
            _score(62), [pt], country="Portugal", when=_iso(0),
        )
        assert score.total == 62 + MAX_NEWS_BOOST

    def test_heat_mortality_events_never_boost_fires(self):
        ev = _fire_event()
        ev["kind"] = "heat_mortality"
        score = apply_newsworthiness_boost(
            _score(62), [ev],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert score.total == 62

    def test_original_score_object_is_not_mutated(self):
        original = _score(62)
        boosted = apply_newsworthiness_boost(
            original, [_fire_event()],
            country="United States", when=_iso(0), lat=39.0, lon=-105.5,
        )
        assert original.total == 62
        assert not any("news_boost" in r for r in original.reasons)
        assert boosted is not original


class TestRunnerSeams:
    """The flag-gated seam in both fire runners: score → boost → _should_draft."""

    def _fire(self):
        from src.data.firms import FireEvent

        return FireEvent(
            lat=39.0, lon=-105.5, confidence=95, frp=350.0,
            nearest_city="Colorado Springs", country="United States",
            event_id="fire_test_1",
        )

    def test_firms_seam_rescues_near_miss_when_flag_on(self, monkeypatch):
        from copy import deepcopy

        from src.orchestrator.sources import firms as firms_runner
        from src.state import DEFAULT_STATE

        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        state = deepcopy(DEFAULT_STATE)
        state["news_events"] = [_fire_event(name=None)]

        monkeypatch.setattr(
            firms_runner, "_fetch_strict", lambda fn: [self._fire()]
        )
        monkeypatch.setattr(
            firms_runner, "score_fire_event", lambda *a, **k: _score(62)
        )
        enqueued: list = []
        monkeypatch.setattr(
            firms_runner, "_enqueue_story_candidate",
            lambda bot_state, **kwargs: enqueued.append(kwargs) or True,
        )
        firms_runner.run_firms(state, None)
        assert len(enqueued) == 1
        assert enqueued[0]["score"].total == 62 + MAX_NEWS_BOOST
        assert any("news_boost" in r for r in enqueued[0]["score"].reasons)

    def test_firms_seam_flag_off_is_untouched(self, monkeypatch):
        from copy import deepcopy

        from src.orchestrator.sources import firms as firms_runner
        from src.state import DEFAULT_STATE

        monkeypatch.delenv("THEHEAT_NEWS_BOOST_ENABLED", raising=False)
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        state = deepcopy(DEFAULT_STATE)
        state["news_events"] = [_fire_event(name=None)]

        monkeypatch.setattr(
            firms_runner, "_fetch_strict", lambda fn: [self._fire()]
        )
        monkeypatch.setattr(
            firms_runner, "score_fire_event", lambda *a, **k: _score(62)
        )
        enqueued: list = []
        monkeypatch.setattr(
            firms_runner, "_enqueue_story_candidate",
            lambda bot_state, **kwargs: enqueued.append(kwargs) or True,
        )
        firms_runner.run_firms(state, None)
        assert enqueued == []  # 62 < 64 suppressed, no boost

    def test_firms_seam_boost_error_degrades_to_original_score(self, monkeypatch):
        from copy import deepcopy

        from src.orchestrator.sources import firms as firms_runner
        from src.state import DEFAULT_STATE

        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        state = deepcopy(DEFAULT_STATE)
        state["news_events"] = [_fire_event(name=None)]

        def _boom(*a, **k):
            raise RuntimeError("boost exploded")

        monkeypatch.setattr(
            "src.editorial.newsworthiness.apply_newsworthiness_boost", _boom
        )
        monkeypatch.setattr(
            firms_runner, "_fetch_strict", lambda fn: [self._fire()]
        )
        monkeypatch.setattr(
            firms_runner, "score_fire_event", lambda *a, **k: _score(80)
        )
        enqueued: list = []
        monkeypatch.setattr(
            firms_runner, "_enqueue_story_candidate",
            lambda bot_state, **kwargs: enqueued.append(kwargs) or True,
        )
        firms_runner.run_firms(state, None)  # must not raise
        assert len(enqueued) == 1
        assert enqueued[0]["score"].total == 80
