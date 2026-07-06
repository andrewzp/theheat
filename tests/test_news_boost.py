"""Bet A phase A2 — boost: capped, source-required rescue at the fire score gate.

Spec §4: a strong, sourced newsworthiness match can pull a BELOW-threshold fire
signal back into contention — flat +8, hard floor threshold−8, ≥1 structured/
verified impact entry required, provenance in score.reasons. Rescue-only: a
passing score is returned untouched. Boosts are BATCH-planned per runner pass
(``plan_fire_boosts``) so a nameless news event that matches several same-state
fires rescues NONE — identity discipline identical to A1's enrich matcher.
Fire-only wiring in v1 (FIRMS + NIFC runners). All fixture dates today-relative.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.editorial.newsworthiness import (
    MAX_NEWS_BOOST,
    apply_newsworthiness_boost,
    news_boost_enabled,
    plan_fire_boosts,
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


def _colorado_fire(fire_id: str = "f1") -> dict:
    return {"id": fire_id, "country": "United States", "when": _iso(0),
            "lat": 39.0, "lon": -105.5}


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


class TestPlanFireBoosts:
    def test_single_nameless_match_is_planned(self):
        plan = plan_fire_boosts([_fire_event()], [_colorado_fire()])
        assert set(plan) == {"f1"}

    def test_nameless_event_matching_two_fires_plans_none(self):
        # THE codex A2-r1 P1 scenario: one nameless verified Colorado event,
        # two near-miss Colorado hotspots — identity is ambiguous, rescue none.
        plan = plan_fire_boosts(
            [_fire_event()],
            [_colorado_fire("f1"), _colorado_fire("f2")],
        )
        assert plan == {}

    def test_named_event_requires_name_agreement(self):
        named = _fire_event(name="Alpine")
        fires = [
            {**_colorado_fire("hotspot")},  # nameless FIRMS hotspot
            {"id": "alpine", "country": "United States", "when": _iso(0),
             "us_state": "CO", "incident_name": "Alpine Fire"},
        ]
        plan = plan_fire_boosts([named], fires)
        assert set(plan) == {"alpine"}

    def test_wrong_state_never_planned(self):
        vermont = {"id": "vt", "country": "United States", "when": _iso(0),
                   "lat": 44.0, "lon": -72.6}
        assert plan_fire_boosts([_fire_event(admin1="CO")], [vermont]) == {}

    def test_us_event_without_state_never_planned(self):
        assert plan_fire_boosts([_fire_event(admin1=None)], [_colorado_fire()]) == {}

    def test_non_us_fire_matches_on_country(self):
        pt_event = _fire_event(country="Portugal", admin1=None)
        pt_fire = {"id": "pt1", "country": "Portugal", "when": _iso(0)}
        assert set(plan_fire_boosts([pt_event], [pt_fire])) == {"pt1"}

    def test_unverified_event_never_planned(self):
        plan = plan_fire_boosts(
            [_fire_event(confidence="unverified")], [_colorado_fire()],
        )
        assert plan == {}

    def test_unwarranted_entries_never_planned(self):
        bad = [{"claim": "big fire", "value": 1, "source_name": "", "url": "", "as_of": ""}]
        assert plan_fire_boosts([_fire_event(impact=bad)], [_colorado_fire()]) == {}

    def test_heat_mortality_never_plans_fire_boosts(self):
        ev = _fire_event()
        ev["kind"] = "heat_mortality"
        assert plan_fire_boosts([ev], [_colorado_fire()]) == {}

    def test_window_outside_slack_never_planned(self):
        stale = _fire_event(window_start=_iso(10), window_end=_iso(8))
        assert plan_fire_boosts([stale], [_colorado_fire()]) == {}

    def test_one_fire_takes_at_most_one_event_no_stacking(self):
        ev1 = _fire_event()
        ev2 = _fire_event(impact=[{
            "claim": "3 firefighters killed", "value": 3,
            "source_name": "Reuters", "url": "https://example.test/r",
            "as_of": _iso(0),
        }])
        plan = plan_fire_boosts([ev1, ev2], [_colorado_fire()])
        assert set(plan) == {"f1"}
        boosted = apply_newsworthiness_boost(_score(62), plan["f1"])
        assert boosted.total == 62 + MAX_NEWS_BOOST  # +8 once, never +16


class TestApplyBoost:
    def test_near_miss_is_rescued_with_provenance(self):
        # The Colorado case: 62 < 64 clears with a sourced match.
        boosted = apply_newsworthiness_boost(_score(62), _fire_event())
        assert boosted.total == 62 + MAX_NEWS_BOOST
        assert boosted.passes is True
        assert any(
            r.startswith(f"news_boost=+{MAX_NEWS_BOOST} per NIFC (")
            for r in boosted.reasons
        )
        assert "frp tier high" in boosted.reasons  # original reasons preserved

    def test_far_miss_is_never_resurrected(self):
        boosted = apply_newsworthiness_boost(_score(55), _fire_event())
        assert boosted.total == 55
        assert not any("news_boost" in r for r in boosted.reasons)

    def test_passing_score_is_untouched(self):
        original = _score(80)
        assert apply_newsworthiness_boost(original, _fire_event()) is original

    def test_source_required_belt_at_apply_time(self):
        bad = _fire_event(impact=[{"claim": "x", "value": 1, "source_name": "",
                                   "url": "", "as_of": ""}])
        boosted = apply_newsworthiness_boost(_score(62), bad)
        assert boosted.total == 62

    def test_original_score_object_is_not_mutated(self):
        original = _score(62)
        boosted = apply_newsworthiness_boost(original, _fire_event())
        assert original.total == 62
        assert not any("news_boost" in r for r in original.reasons)
        assert boosted is not original


class TestProvenanceSurvivesKills:
    def test_downstream_suppression_row_keeps_news_boost_reason(self):
        from copy import deepcopy

        from src.orchestrator.suppression import _record_downstream_suppression
        from src.state import DEFAULT_STATE

        state = deepcopy(DEFAULT_STATE)
        boosted = apply_newsworthiness_boost(_score(62), _fire_event())
        _record_downstream_suppression(
            bot_state=state, source="firms", run_id="r1", event_id="f1",
            score=boosted, kill_stage="critic", kill_reason="not extraordinary",
            summary="Colorado",
        )
        row = state["suppressions"][-1]
        assert "not extraordinary" in row["reasons"]
        assert any(r.startswith("news_boost=") for r in row["reasons"])

    def test_unboosted_kill_rows_are_unchanged(self):
        from copy import deepcopy

        from src.orchestrator.suppression import _record_downstream_suppression
        from src.state import DEFAULT_STATE

        state = deepcopy(DEFAULT_STATE)
        _record_downstream_suppression(
            bot_state=state, source="firms", run_id="r1", event_id="f1",
            score=_score(80), kill_stage="critic", kill_reason="not extraordinary",
            summary="Colorado",
        )
        assert state["suppressions"][-1]["reasons"] == ["not extraordinary"]


class TestRunnerSeams:
    """The flag-gated seam in the FIRMS runner: batch plan → boost → gate."""

    def _fire(self, event_id: str = "fire_test_1", lat: float = 39.0, lon: float = -105.5):
        from src.data.firms import FireEvent

        return FireEvent(
            lat=lat, lon=lon, confidence=95, frp=350.0,
            nearest_city="Colorado Springs", country="United States",
            event_id=event_id,
        )

    def _run(self, monkeypatch, *, fires, news_events, score_total: int):
        from copy import deepcopy

        from src.orchestrator.sources import firms as firms_runner
        from src.state import DEFAULT_STATE

        state = deepcopy(DEFAULT_STATE)
        state["news_events"] = news_events
        monkeypatch.setattr(firms_runner, "_fetch_strict", lambda fn: fires)
        monkeypatch.setattr(
            firms_runner, "score_fire_event", lambda *a, **k: _score(score_total)
        )
        enqueued: list = []
        monkeypatch.setattr(
            firms_runner, "_enqueue_story_candidate",
            lambda bot_state, **kwargs: enqueued.append(kwargs) or True,
        )
        firms_runner.run_firms(state, None)
        return enqueued

    def test_firms_seam_rescues_near_miss_when_flag_on(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        enqueued = self._run(
            monkeypatch, fires=[self._fire()],
            news_events=[_fire_event()], score_total=62,
        )
        assert len(enqueued) == 1
        assert enqueued[0]["score"].total == 62 + MAX_NEWS_BOOST
        assert any("news_boost" in r for r in enqueued[0]["score"].reasons)

    def test_firms_seam_two_hotspots_one_nameless_event_rescues_neither(self, monkeypatch):
        # End-to-end codex A2-r1 P1: identity ambiguity rescues none.
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")
        enqueued = self._run(
            monkeypatch,
            fires=[self._fire("f1"), self._fire("f2", lat=39.5, lon=-105.0)],
            news_events=[_fire_event()], score_total=62,
        )
        assert enqueued == []

    def test_firms_seam_flag_off_is_untouched(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWS_BOOST_ENABLED", raising=False)
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        enqueued = self._run(
            monkeypatch, fires=[self._fire()],
            news_events=[_fire_event()], score_total=62,
        )
        assert enqueued == []  # 62 < 64 suppressed, no boost

    def test_firms_seam_planner_error_degrades_to_no_boosts(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_BOOST_ENABLED", "1")

        def _boom(*a, **k):
            raise RuntimeError("planner exploded")

        monkeypatch.setattr(
            "src.editorial.newsworthiness.plan_fire_boosts", _boom
        )
        enqueued = self._run(
            monkeypatch, fires=[self._fire()],
            news_events=[_fire_event()], score_total=80,
        )
        assert len(enqueued) == 1  # cycle survives; passing score unaffected
        assert enqueued[0]["score"].total == 80
