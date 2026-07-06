"""Bet A phase A1 — enrich: sourced human-impact on matched StoryBundles.

Covers the editorial matcher (src/editorial/newsworthiness.py), the bundle
serialization (cache-safe when empty), the decision-4 forced-manual_only
citation detection, the save_draft override (including autoship-eligible
record types), the evidence-contract floor for human_impact entries, and the
writer/fact-check prompt riders. All fixture dates are today-relative (the
time-travel canary runs this suite at +30/+365 days).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest

from src.editorial.newsworthiness import (
    MAX_IMPACT_FACTS_PER_BUNDLE,
    ImpactCitation,
    attach_human_impact,
    detect_impact_citation,
    match_news_to_candidates,
    news_enrich_enabled,
)
from src.editorial.scoring._shared import EditorialScore
from src.two_bot.types import StoryBundle, TriageCandidateBundle

TODAY = date.today()


def _iso(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def _impact(
    claim: str = "3 firefighters killed on the Alpine fire",
    value: int | float | str = 3,
    source_name: str = "NIFC",
    url: str = "https://example.test/nifc",
    as_of: str | None = None,
) -> dict:
    return {
        "claim": claim,
        "value": value,
        "source_name": source_name,
        "url": url,
        "as_of": as_of or _iso(0),
    }


def _news_event(
    *,
    kind: str = "fire",
    country: str = "United States",
    admin1: str | None = "CO",
    name: str | None = "Alpine",
    window_start: str | None = None,
    window_end: str | None = None,
    impact: list[dict] | None = None,
    confidence: str = "structured",
) -> dict:
    return {
        "kind": kind,
        "headline": f"{name or country} event",
        "place": {"country": country, "admin1": admin1, "name": name},
        "window_start": window_start or _iso(0),
        "window_end": window_end or _iso(0),
        "impact": impact if impact is not None else [_impact()],
        "retrieved_via": "feed:nifc",
        "confidence": confidence,
    }


def _bundle(
    *,
    signal_kind: str = "fire",
    event_id: str = "ev1",
    where: str = "Somewhere",
    when: str | None = None,
    country: str = "",
    facts: list[dict] | None = None,
) -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind,
        where=where,
        when=when or _iso(0),
        event_id=event_id,
        headline_metric={"label": "x", "value": 1},
        current_facts=facts if facts is not None else [{"label": "x", "value": 1}],
        country=country,
    )


def _score(total: int = 80) -> EditorialScore:
    return EditorialScore(
        category="fire", severity=80, novelty=80, timeliness=80, confidence=80,
        shareability=80, sensitivity=0, total=total, threshold=64, reasons=[],
    )


def _cand(
    *,
    event_id: str,
    legacy_type: str = "fire",
    signal_kind: str | None = None,
    total: int = 80,
    when: str | None = None,
    country: str = "",
    facts: list[dict] | None = None,
) -> TriageCandidateBundle:
    return TriageCandidateBundle(
        bundle=_bundle(
            signal_kind=signal_kind or legacy_type,
            event_id=event_id,
            when=when,
            country=country,
            facts=facts,
        ),
        score=_score(total),
        event_id=event_id,
        source="test",
        review_context={},
        city="",
        tweet_date="",
        cooldown_exempt=False,
        legacy_type=legacy_type,
        created_at=f"{_iso(0)}T12:00:00Z",
    )


def _firms_fire_cand(*, event_id: str = "f1", lat: float = 39.0, lon: float = -105.5,
                     total: int = 80, when: str | None = None) -> TriageCandidateBundle:
    """A FIRMS satellite-detection fire candidate located in Colorado by default."""
    return _cand(
        event_id=event_id,
        legacy_type="fire",
        total=total,
        when=when,
        facts=[
            {"label": "country", "value": "United States"},
            {"label": "lat", "value": lat},
            {"label": "lon", "value": lon},
        ],
    )


# ---------------------------------------------------------------------------
# serialization (cache-safety)
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_omits_empty_human_impact(self):
        d = _bundle().to_dict()
        assert "human_impact" not in d  # byte-identical to pre-A1

    def test_to_dict_includes_human_impact_when_present(self):
        b = _bundle()
        b.human_impact = [_impact()]
        d = b.to_dict()
        assert d["human_impact"][0]["source_name"] == "NIFC"


# ---------------------------------------------------------------------------
# flag
# ---------------------------------------------------------------------------


class TestFlag:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        monkeypatch.delenv("THEHEAT_NEWS_ENRICH_ENABLED", raising=False)
        assert news_enrich_enabled() is False

    def test_enrich_alone_is_not_enough(self, monkeypatch):
        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
        assert news_enrich_enabled() is False

    def test_master_alone_is_not_enough(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.delenv("THEHEAT_NEWS_ENRICH_ENABLED", raising=False)
        assert news_enrich_enabled() is False

    def test_both_on(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
        assert news_enrich_enabled() is True


# ---------------------------------------------------------------------------
# matcher
# ---------------------------------------------------------------------------


class TestMatcher:
    def test_nameless_us_fire_matches_firms_candidate_by_state_bbox(self):
        # A nameless fire report in Colorado ↔ the single FIRMS hotspot at a
        # Colorado lat/lon.
        ev = _news_event(admin1="CO", name=None)
        matches = match_news_to_candidates([ev], [_firms_fire_cand()])
        assert len(matches) == 1

    def test_named_fire_event_never_matches_nameless_hotspot(self):
        # Incident-scoped identity: the "Alpine" death toll must not ride a
        # nameless same-state FIRMS hotspot (codex P0, round 1).
        ev = _news_event(admin1="CO", name="Alpine")
        assert match_news_to_candidates([ev], [_firms_fire_cand()]) == []

    def test_us_fire_does_not_match_wrong_state(self):
        ev = _news_event(admin1="CO", name=None)
        vermont = _firms_fire_cand(lat=44.0, lon=-72.6)
        assert match_news_to_candidates([ev], [vermont]) == []

    def test_bbox_overlap_resolves_to_one_state(self):
        # (43.5, -72.3) sits inside the VT/NH/NY census boxes; the centroid
        # tie-break resolves it to New Hampshire — so a nameless New York
        # event must NOT match it (codex P1, round 2), while a New Hampshire
        # event does.
        cand = _firms_fire_cand(lat=43.5, lon=-72.3)
        ny = _news_event(admin1="NY", name=None)
        nh = _news_event(admin1="NH", name=None)
        assert match_news_to_candidates([ny], [cand]) == []
        assert len(match_news_to_candidates([nh], [cand])) == 1

    def test_us_fire_event_without_state_never_matches(self):
        ev = _news_event(admin1=None, name=None)
        assert match_news_to_candidates([ev], [_firms_fire_cand()]) == []

    def test_fire_footprint_matches_on_region_code(self):
        ev = _news_event(admin1="CO", name="Alpine")
        cand = _cand(
            event_id="fp1",
            legacy_type="fire_footprint",
            facts=[
                {"label": "complex_name", "value": "Alpine"},
                {"label": "region", "value": "CO"},
                {"label": "country", "value": "United States"},
            ],
        )
        assert len(match_news_to_candidates([ev], [cand])) == 1

    def test_name_contradiction_blocks_match(self):
        # Same state, same window — but the incident names disagree. A death
        # toll must never ride a different fire's tweet.
        ev = _news_event(admin1="CO", name="Madre")
        cand = _cand(
            event_id="fp1",
            legacy_type="fire_footprint",
            facts=[
                {"label": "complex_name", "value": "Alpine"},
                {"label": "region", "value": "CO"},
                {"label": "country", "value": "United States"},
            ],
        )
        assert match_news_to_candidates([ev], [cand]) == []

    def test_non_us_heat_matches_reganom_by_region_country(self):
        ev = _news_event(
            kind="heat_mortality", country="France", admin1=None, name=None,
            window_start=_iso(8), window_end=_iso(2),
            impact=[_impact(claim="about 1,300 excess deaths", value=1300,
                            source_name="WHO", url="https://example.test/who")],
            confidence="verified",
        )
        reganom = _cand(
            event_id="rg1",
            legacy_type="regional_anomaly",
            when=_iso(3),
            facts=[
                {"label": "region", "value": "France"},
                {"label": "window_start", "value": _iso(9)},
                {"label": "window_end", "value": _iso(3)},
            ],
        )
        assert len(match_news_to_candidates([ev], [reganom])) == 1

    def test_us_heat_requires_state_on_both_sides(self):
        ev = _news_event(kind="heat_mortality", country="United States",
                         admin1=None, name=None, confidence="verified")
        ghcn = _cand(
            event_id="g1",
            legacy_type="all_time_high",
            signal_kind="all_time_record",
            facts=[
                {"label": "country", "value": "United States"},
                {"label": "state", "value": "Vermont"},
            ],
        )
        assert match_news_to_candidates([ev], [ghcn]) == []

    def test_us_heat_matches_when_states_agree(self):
        ev = _news_event(kind="heat_mortality", country="United States",
                         admin1="VT", name=None, confidence="verified")
        ghcn = _cand(
            event_id="g1",
            legacy_type="all_time_high",
            signal_kind="all_time_record",
            facts=[
                {"label": "country", "value": "United States"},
                {"label": "state", "value": "Vermont"},
            ],
        )
        assert len(match_news_to_candidates([ev], [ghcn])) == 1

    def test_cold_types_never_match_heat_mortality(self):
        ev = _news_event(kind="heat_mortality", country="France", admin1=None,
                         name=None, confidence="verified")
        cold = _cand(event_id="c1", legacy_type="all_time_low",
                     signal_kind="all_time_record",
                     facts=[{"label": "country", "value": "France"}])
        assert match_news_to_candidates([ev], [cold]) == []

    def test_cold_absolute_extreme_never_hosts_heat_mortality(self):
        # legacy_type "absolute_extreme" covers BOTH directions; the bundle's
        # signal_kind/kind fact carries the direction (codex P1, round 3).
        ev = _news_event(kind="heat_mortality", country="Norway", admin1=None,
                         name=None, confidence="verified")
        cold = _cand(event_id="ae_cold", legacy_type="absolute_extreme",
                     signal_kind="absolute_extreme_cold",
                     facts=[{"label": "country", "value": "Norway"},
                            {"label": "kind", "value": "cold"}])
        hot = _cand(event_id="ae_hot", legacy_type="absolute_extreme",
                    signal_kind="absolute_extreme_hot",
                    facts=[{"label": "country", "value": "Norway"},
                           {"label": "kind", "value": "hot"}])
        assert match_news_to_candidates([ev], [cold]) == []
        matches = match_news_to_candidates([ev], [cold, hot])
        assert len(matches) == 1
        assert matches[0][1].event_id == "ae_hot"

    def test_kind_family_mismatch_never_matches(self):
        ev = _news_event(admin1="CO")  # fire
        heat = _cand(event_id="h1", legacy_type="all_time_high",
                     signal_kind="all_time_record",
                     facts=[{"label": "country", "value": "United States"},
                            {"label": "state", "value": "Colorado"}])
        assert match_news_to_candidates([ev], [heat]) == []

    def test_window_outside_slack_does_not_match(self):
        ev = _news_event(admin1="CO", name=None, window_start=_iso(10), window_end=_iso(8))
        cand = _firms_fire_cand(when=_iso(0))
        assert match_news_to_candidates([ev], [cand]) == []

    def test_nameless_fire_event_with_two_hosts_attaches_to_none(self):
        # Two same-state fires in-window cannot be told apart — guessing by
        # score is the wrong-fire failure. Attach to none.
        ev = _news_event(admin1="CO", name=None)
        weak = _firms_fire_cand(event_id="weak", total=66)
        strong = _firms_fire_cand(event_id="strong", total=90)
        assert match_news_to_candidates([ev], [weak, strong]) == []

    def test_ambiguous_heat_event_attaches_to_highest_score_only(self):
        # Heat mortality is region-scoped: a country heatwave is ONE event, so
        # the spec's highest-score ambiguity rule stands.
        ev = _news_event(kind="heat_mortality", country="France", admin1=None,
                         name=None, confidence="verified")
        weak = _cand(event_id="weak", legacy_type="regional_anomaly", total=66,
                     facts=[{"label": "region", "value": "France"}])
        strong = _cand(event_id="strong", legacy_type="all_time_high",
                       signal_kind="all_time_record", total=90,
                       facts=[{"label": "country", "value": "France"}])
        matches = match_news_to_candidates([ev], [weak, strong])
        assert len(matches) == 1
        assert matches[0][1].event_id == "strong"

    def test_named_fire_event_matches_same_named_complex_among_hotspots(self):
        ev = _news_event(admin1="CO", name="Alpine")
        hotspot = _firms_fire_cand(event_id="hotspot", total=95)
        complex_cand = _cand(
            event_id="alpine",
            legacy_type="fire_footprint",
            total=70,
            facts=[
                {"label": "complex_name", "value": "Alpine Fire"},
                {"label": "region", "value": "CO"},
                {"label": "country", "value": "United States"},
            ],
        )
        matches = match_news_to_candidates([ev], [hotspot, complex_cand])
        assert len(matches) == 1
        assert matches[0][1].event_id == "alpine"

    def test_unverified_event_never_matches(self):
        ev = _news_event(admin1="CO", name=None, confidence="unverified")
        assert match_news_to_candidates([ev], [_firms_fire_cand()]) == []


# ---------------------------------------------------------------------------
# attach
# ---------------------------------------------------------------------------


class TestAttach:
    def test_attaches_impact_to_matched_bundle(self):
        cand = _firms_fire_cand()
        n = attach_human_impact([cand], [_news_event(admin1="CO", name=None)])
        assert n == 1
        assert cand.bundle.human_impact[0]["source_name"] == "NIFC"

    def test_no_events_is_a_noop(self):
        cand = _firms_fire_cand()
        assert attach_human_impact([cand], []) == 0
        assert attach_human_impact([cand], None) == 0
        assert cand.bundle.human_impact == []

    def test_unwarranted_entries_are_dropped_at_attach(self):
        bad = {"claim": "10 dead", "value": 10, "source_name": "", "url": "", "as_of": ""}
        ev = _news_event(admin1="CO", name=None, impact=[bad, _impact()])
        cand = _firms_fire_cand()
        attach_human_impact([cand], [ev])
        assert [e["source_name"] for e in cand.bundle.human_impact] == ["NIFC"]

    def test_duplicate_facts_are_not_attached_twice(self):
        ev1 = _news_event(admin1="CO", name=None)
        ev2 = _news_event(admin1="CO", name=None)
        cand = _firms_fire_cand()
        attach_human_impact([cand], [ev1, ev2])
        assert len(cand.bundle.human_impact) == 1

    def test_attached_facts_are_capped(self):
        impacts = [
            _impact(claim=f"fact {i}", value=100 + i, url=f"https://example.test/{i}")
            for i in range(MAX_IMPACT_FACTS_PER_BUNDLE + 3)
        ]
        ev = _news_event(admin1="CO", name=None, impact=impacts)
        cand = _firms_fire_cand()
        attach_human_impact([cand], [ev])
        assert len(cand.bundle.human_impact) == MAX_IMPACT_FACTS_PER_BUNDLE


# ---------------------------------------------------------------------------
# decision 4 — citation detection
# ---------------------------------------------------------------------------


def _review_context(*, entries: list[dict] | None, cited_impact) -> dict:
    two_bot: dict = {"signal_kind": "fire"}
    if entries is not None:
        two_bot["human_impact"] = entries
        two_bot["cited_impact"] = cited_impact
    return {"two_bot": two_bot}


class TestCitationDetection:
    def test_no_impact_entries_is_never_forced(self):
        rc = _review_context(entries=None, cited_impact=None)
        c = detect_impact_citation("A fire is burning.", rc)
        assert c == ImpactCitation(forced=False, writer_flag=None, regex_hit=False)

    def test_writer_flag_true_forces(self):
        rc = _review_context(entries=[_impact()], cited_impact=True)
        c = detect_impact_citation("Per NIFC, 3 firefighters were killed.", rc)
        assert c.forced is True

    def test_regex_source_name_hit_forces_even_when_writer_says_no(self):
        rc = _review_context(entries=[_impact()], cited_impact=False)
        c = detect_impact_citation("Per NIFC, crews responded.", rc)
        assert c.forced is True
        assert c.disagreement is True

    def test_source_name_requires_word_boundary(self):
        rc = _review_context(
            entries=[_impact(source_name="WHO", url="https://example.test/who")],
            cited_impact=False,
        )
        # "whole" must not read as a WHO citation.
        c = detect_impact_citation("The whole valley burned.", rc)
        assert c.forced is False

    def test_large_value_hit_forces(self):
        rc = _review_context(
            entries=[_impact(claim="1,300 excess deaths", value=1300,
                             source_name="Santé publique France")],
            cited_impact=False,
        )
        c = detect_impact_citation("An estimated 1,300 people died.", rc)
        assert c.forced is True

    def test_small_value_alone_does_not_force(self):
        # value=3 must not trip on a date digit; source attribution is the
        # load-bearing regex signal for small figures.
        rc = _review_context(entries=[_impact(value=3)], cited_impact=False)
        c = detect_impact_citation("Verkhoyansk hit 14.8C on July 3.", rc)
        assert c.forced is False

    def test_casualty_wording_forces_even_without_source_or_value(self):
        # The deterministic net for a lying/mistaken cited_impact=false: an
        # enriched draft whose TEXT talks casualties always gets a human.
        rc = _review_context(entries=[_impact(value=3)], cited_impact=False)
        c = detect_impact_citation("Three firefighters died battling the blaze.", rc)
        assert c.forced is True

    def test_casualty_wording_in_plain_draft_is_out_of_scope(self):
        # No impact facts offered → decision 4 never fires; impact-sounding
        # text on a non-enriched draft is fact-check's problem.
        rc = _review_context(entries=None, cited_impact=None)
        c = detect_impact_citation("Evacuations were ordered.", rc)
        assert c.forced is False

    def test_string_value_echo_forces(self):
        # The A1 contract allows string values; a verbatim echo of "1,450"
        # must trip the sweep even with no source name and no casualty word
        # (codex P1, round 2).
        rc = _review_context(
            entries=[_impact(claim="1,450 personnel assigned", value="1,450",
                             source_name="NIFC")],
            cited_impact=False,
        )
        c = detect_impact_citation("1,450 personnel are assigned to the fire.", rc)
        assert c.forced is True

    def test_string_dollar_value_echo_forces(self):
        rc = _review_context(
            entries=[_impact(claim="damage estimated at $2 million",
                             value="$2 million", source_name="Reuters")],
            cited_impact=False,
        )
        c = detect_impact_citation("Early estimates put damage at $2 million.", rc)
        assert c.forced is True

    def test_bare_digit_string_value_does_not_false_positive(self):
        # value="3" must not literal-match every "3" in the text.
        rc = _review_context(entries=[_impact(value="3")], cited_impact=False)
        c = detect_impact_citation("Verkhoyansk hit 14.8C on July 3.", rc)
        assert c.forced is False

    def test_rewritten_money_value_forces(self):
        # "$2 million" entry, text says "2 million dollars" — the magnitude
        # pattern catches the rewrite (codex P1, round 3). Text avoids all
        # casualty/damage stems so THIS layer is what's proven.
        rc = _review_context(
            entries=[_impact(claim="damage estimated at $2 million",
                             value="$2 million", source_name="Reuters")],
            cited_impact=False,
        )
        c = detect_impact_citation("Early estimates put it at 2 million dollars.", rc)
        assert c.forced is True

    def test_costa_rica_is_not_a_cost_hit(self):
        rc = _review_context(entries=[_impact(value=250)], cited_impact=False)
        c = detect_impact_citation("A fire near San José, Costa Rica is burning.", rc)
        assert c.forced is False

    def test_missing_writer_flag_fails_closed(self):
        rc = _review_context(entries=[_impact()], cited_impact=None)
        c = detect_impact_citation("A fire is burning.", rc)
        assert c.forced is True
        assert c.disagreement is True

    def test_writer_true_without_regex_hit_is_disagreement_but_forced(self):
        rc = _review_context(entries=[_impact()], cited_impact=True)
        c = detect_impact_citation("A fire is burning.", rc)
        assert c.forced is True
        assert c.disagreement is True


# ---------------------------------------------------------------------------
# decision 4 — save_draft forcing
# ---------------------------------------------------------------------------


class TestSaveDraftForcing:
    @pytest.fixture()
    def bot_state(self):
        from src.state import DEFAULT_STATE

        state = deepcopy(DEFAULT_STATE)
        state["drafts"] = []
        return state

    def _critic_pass_context(self, *, entries=None, cited_impact=None) -> dict:
        two_bot: dict = {
            "signal_kind": "all_time_record",
            "critic": {"passed": True, "verdict": "PASS", "kill_reason": None},
        }
        if entries is not None:
            two_bot["human_impact"] = entries
            two_bot["cited_impact"] = cited_impact
        return {"two_bot": two_bot}

    def test_cited_impact_forces_manual_on_autoship_type(self, monkeypatch, bot_state):
        from src.orchestrator.draft_save import save_draft

        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        rc = self._critic_pass_context(entries=[_impact()], cited_impact=True)
        assert save_draft(
            "Per NIFC, 3 firefighters were killed on the Alpine fire.",
            bot_state, "all_time_high", event_id="e1",
            score=_score(), review_context=rc,
        )
        draft = bot_state["drafts"][-1]
        assert draft["approval_mode"] == "manual"
        assert "auto_approve_at" not in draft
        assert draft["approval_policy"]["mode"] == "manual_only"
        assert draft["forced_manual"] == "cited_impact"
        assert "autoship_on_critic_pass" not in draft

    def test_uncited_enriched_draft_keeps_autoship(self, monkeypatch, bot_state):
        from src.orchestrator.draft_save import save_draft

        monkeypatch.setenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "1")
        rc = self._critic_pass_context(entries=[_impact()], cited_impact=False)
        assert save_draft(
            "Island Pond, Vermont hit 92F, hottest in 37 years of records.",
            bot_state, "all_time_high", event_id="e2",
            score=_score(), review_context=rc,
        )
        draft = bot_state["drafts"][-1]
        assert draft["approval_mode"] == "auto"
        assert draft["autoship_on_critic_pass"] is True
        assert "auto_approve_at" in draft

    def test_cited_impact_blocks_armed_auto_path(self, monkeypatch, bot_state):
        from src.orchestrator.draft_save import save_draft

        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        rc = self._critic_pass_context(entries=[_impact()], cited_impact=True)
        # hot10 with strong scores would normally arm the policy_auto window.
        strong = {"total": 80}
        assert save_draft(
            "Per NIFC, 3 firefighters were killed on the Alpine fire.",
            bot_state, "hot10", event_id="e3",
            score=EditorialScore(
                category="hot10", severity=80, novelty=80, timeliness=80,
                confidence=80, shareability=80, sensitivity=0, total=80,
                threshold=64, reasons=[],
            ),
            candidate_score=strong, review_context=rc,
        )
        draft = bot_state["drafts"][-1]
        assert draft["approval_mode"] == "manual"
        assert "auto_approve_at" not in draft
        assert draft["approval_policy"]["mode"] == "manual_only"

    def test_plain_draft_behavior_unchanged(self, monkeypatch, bot_state):
        from src.orchestrator.draft_save import save_draft

        monkeypatch.delenv("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", raising=False)
        rc = self._critic_pass_context()
        assert save_draft(
            "A fire in Mali is radiating 361 MW of heat.",
            bot_state, "fire", event_id="e4",
            score=_score(), review_context=rc,
        )
        draft = bot_state["drafts"][-1]
        assert draft["approval_mode"] == "manual"
        assert draft["approval_policy"]["mode"] == "manual_only"  # fire policy
        assert "forced_manual" not in draft


# ---------------------------------------------------------------------------
# evidence contract
# ---------------------------------------------------------------------------


class TestEvidenceContract:
    def _prompt_ready_bundle(self) -> StoryBundle:
        return StoryBundle(
            signal_kind="fire",
            where="Alpine complex, Colorado, United States",
            when=_iso(0),
            event_id="ec1",
            headline_metric={"label": "FRP", "value": 400.0, "unit": "MW"},
            current_facts=[{"label": "country", "value": "United States"}],
            historical_context={},
            raw_signal_dump={"event_id": "ec1", "frp": 400.0},
        )

    def test_complete_impact_entries_pass(self):
        from src.two_bot.evidence_contract import audit_story_bundle

        b = self._prompt_ready_bundle()
        b.human_impact = [_impact()]
        audit = audit_story_bundle(b)
        assert audit.prompt_ready is True

    def test_unwarranted_impact_entry_blocks_the_writer(self):
        from src.two_bot.evidence_contract import audit_story_bundle

        b = self._prompt_ready_bundle()
        b.human_impact = [{"claim": "10 dead", "value": 10, "source_name": "NIFC",
                           "url": "", "as_of": _iso(0)}]
        audit = audit_story_bundle(b)
        assert audit.prompt_ready is False
        assert any(i.code == "impact_entry_unwarranted" for i in audit.issues)

    def test_non_dict_impact_entry_blocks_the_writer(self):
        from src.two_bot.evidence_contract import audit_story_bundle

        b = self._prompt_ready_bundle()
        b.human_impact = ["3 killed"]  # type: ignore[list-item]
        audit = audit_story_bundle(b)
        assert audit.prompt_ready is False


# ---------------------------------------------------------------------------
# prompt riders
# ---------------------------------------------------------------------------


class TestPromptRiders:
    def test_impact_guidance_covers_the_iron_constraint(self):
        from src.two_bot.prompts.writer_prompt import IMPACT_GUIDANCE

        assert "human_impact" in IMPACT_GUIDANCE
        assert "cited_impact" in IMPACT_GUIDANCE
        assert "attribut" in IMPACT_GUIDANCE.lower()
        assert "past tense" in IMPACT_GUIDANCE.lower()

    def test_writer_system_prompt_does_not_carry_the_rider(self):
        # The system prompt is cached (byte-identity matters); the impact
        # guidance rides the USER prompt only, like MULTISIGNAL_GUIDANCE.
        from src.two_bot.prompts.writer_prompt import (
            IMPACT_GUIDANCE,
            WRITER_SYSTEM_PROMPT,
        )

        assert IMPACT_GUIDANCE not in WRITER_SYSTEM_PROMPT

    def test_fact_check_prompt_carries_the_mechanical_kill_rule(self):
        from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_SYSTEM_PROMPT

        assert "human_impact" in FACT_CHECK_SYSTEM_PROMPT
        assert "no warrant, no claim" in FACT_CHECK_SYSTEM_PROMPT

    def test_fact_check_prompt_preserves_bundle_fact_impact_claims(self):
        # codex P0 (round 1): GDACS floods cite population_affected from
        # ordinary bundle facts — the new rule must keep those BUNDLE_FACT,
        # not kill them for lacking a human_impact entry.
        from src.two_bot.prompts.fact_check_prompt import FACT_CHECK_SYSTEM_PROMPT

        assert "ordinary bundle fact" in FACT_CHECK_SYSTEM_PROMPT
        assert "population_affected" in FACT_CHECK_SYSTEM_PROMPT
        assert "Nothing changed for these" in FACT_CHECK_SYSTEM_PROMPT

    def test_writer_result_parses_cited_impact(self):
        from src.two_bot.writer import _parse_writer_json

        result = _parse_writer_json(
            '{"tweet": "x", "kill_reason": null, "angle_chosen": "a",'
            ' "era_anchor_used": null, "peer_comparison_used": null,'
            ' "reasoning": "r", "cited_impact": true}'
        )
        assert result.cited_impact is True

    def test_writer_result_cited_impact_defaults_to_none(self):
        from src.two_bot.writer import _parse_writer_json

        result = _parse_writer_json(
            '{"tweet": "x", "kill_reason": null, "angle_chosen": "a",'
            ' "era_anchor_used": null, "peer_comparison_used": null,'
            ' "reasoning": "r"}'
        )
        assert result.cited_impact is None
        assert "cited_impact" not in result.to_dict()


# ---------------------------------------------------------------------------
# drain wiring
# ---------------------------------------------------------------------------


class TestDrainWiring:
    def _state_with_news(self) -> dict:
        from src.state import DEFAULT_STATE

        state = deepcopy(DEFAULT_STATE)
        state["drafts"] = []
        state["news_events"] = [_news_event(admin1="CO", name=None)]
        return state

    def test_flag_off_leaves_bundles_untouched(self, monkeypatch):
        from src.orchestrator.triage_queue import _drain_and_write_triage_queue

        monkeypatch.delenv("THEHEAT_NEWSWORTHINESS_ENABLED", raising=False)
        monkeypatch.delenv("THEHEAT_NEWS_ENRICH_ENABLED", raising=False)
        seen: list = []
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda bundle, *a, **k: seen.append(bundle) or False,
        )
        state = self._state_with_news()
        cand = _firms_fire_cand()
        state["_triage_queue"] = [cand]
        _drain_and_write_triage_queue(state, None)
        assert seen and seen[0].human_impact == []

    def test_flag_on_enriches_before_drafting(self, monkeypatch):
        from src.orchestrator.triage_queue import _drain_and_write_triage_queue

        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")
        seen: list = []
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda bundle, *a, **k: seen.append(bundle) or False,
        )
        state = self._state_with_news()
        cand = _firms_fire_cand()
        state["_triage_queue"] = [cand]
        _drain_and_write_triage_queue(state, None)
        assert seen and seen[0].human_impact
        assert seen[0].human_impact[0]["source_name"] == "NIFC"

    def test_attach_error_does_not_block_the_drain(self, monkeypatch):
        from src.orchestrator.triage_queue import _drain_and_write_triage_queue

        monkeypatch.setenv("THEHEAT_NEWSWORTHINESS_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_NEWS_ENRICH_ENABLED", "1")

        def _boom(*a, **k):
            raise RuntimeError("matcher exploded")

        monkeypatch.setattr(
            "src.editorial.newsworthiness.attach_human_impact", _boom
        )
        seen: list = []
        monkeypatch.setattr(
            "src.orchestrator.common._try_two_bot_draft",
            lambda bundle, *a, **k: seen.append(bundle) or False,
        )
        state = self._state_with_news()
        state["_triage_queue"] = [_firms_fire_cand()]
        _drain_and_write_triage_queue(state, None)
        assert len(seen) == 1  # the cycle still drafted


# ---------------------------------------------------------------------------
# pipeline metadata
# ---------------------------------------------------------------------------


class TestPipelineMetadata:
    def test_metadata_carries_impact_and_citation_flag(self, monkeypatch):
        from src.state import DEFAULT_STATE
        from src.two_bot import pipeline
        from src.two_bot.types import FactCheckResult, WriterResult

        bundle = StoryBundle(
            signal_kind="fire",
            where="Alpine complex, Colorado, United States",
            when=_iso(0),
            event_id="pm1",
            headline_metric={"label": "FRP", "value": 400.0, "unit": "MW"},
            current_facts=[{"label": "country", "value": "United States"}],
            historical_context={},
            raw_signal_dump={"event_id": "pm1", "frp": 400.0},
        )
        bundle.human_impact = [_impact()]

        writer_result = WriterResult(
            tweet="Per NIFC, 3 firefighters were killed on the Alpine fire.",
            kill_reason=None, angle_chosen="impact", era_anchor_used=None,
            peer_comparison_used=None, reasoning="r", cited_impact=True,
        )
        monkeypatch.setattr(pipeline, "_writer_samples", lambda: 1)
        monkeypatch.setattr(pipeline.writer, "write_tweet", lambda *a, **k: writer_result)
        monkeypatch.setattr(
            pipeline.memory, "build_memory_slice",
            lambda *a, **k: __import__("src.two_bot.types", fromlist=["MemorySlice"]).MemorySlice(),
        )
        monkeypatch.setattr(pipeline, "run_safety_pipeline", lambda t: (True, None))
        monkeypatch.setattr(
            pipeline.fact_check, "fact_check",
            lambda *a, **k: FactCheckResult(passed=True, failures=[], raw_response="{}"),
        )
        monkeypatch.setattr(pipeline, "_critic_enabled", lambda: False)

        state = deepcopy(DEFAULT_STATE)
        draft = pipeline.generate_draft(bundle, state)
        assert draft is not None
        md = draft["two_bot_metadata"]
        assert md["human_impact"][0]["source_name"] == "NIFC"
        assert md["cited_impact"] is True
