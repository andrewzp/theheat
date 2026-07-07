"""Phase C — generate-and-select refill loop (THEHEAT_REFILL_ENABLED, default OFF).

Covers the codex must-fixes:
  - target reconciled with the prune cap (single knob).
  - caps counted against SUCCESSES, not selections (the loop reaches deeper after
    failed writer attempts).
  - annual caps re-checked at admit time (no in-cycle overshoot).
  - pre-writer cooldown/dedup predicate skips with $0 LLM (no writer call).
  - flag OFF == byte-for-byte current behavior.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from src.editorial.scoring._shared import EditorialScore
from src.state import DEFAULT_STATE
from src.two_bot.types import StoryBundle, TriageCandidateBundle


def _fresh_state() -> dict:
    state = deepcopy(DEFAULT_STATE)
    state["drafts"] = []
    state["posted_events"] = []
    return state


def _score(total: int = 80, category: str = "drought") -> EditorialScore:
    return EditorialScore(
        category=category, severity=80, novelty=80, timeliness=80, confidence=80,
        shareability=80, sensitivity=0, total=total, threshold=60, reasons=[],
    )


def _bundle(signal_kind: str, event_id: str, where: str = "Place", country: str = "") -> StoryBundle:
    return StoryBundle(
        signal_kind=signal_kind, where=where, when="2026-06-16", event_id=event_id,
        headline_metric={"label": "x", "value": 1}, current_facts=[], country=country,
    )


def _cand(*, event_id, total=80, signal_kind="drought", source="drought",
          city="", tweet_date="", cooldown_exempt=False, on_draft_success=None,
          annual_cap_check=None, where="Place", country=""):
    return TriageCandidateBundle(
        bundle=_bundle(signal_kind, event_id, where=where, country=country),
        score=_score(total, signal_kind),
        event_id=event_id, source=source, review_context={}, city=city,
        tweet_date=tweet_date, cooldown_exempt=cooldown_exempt, legacy_type=signal_kind,
        created_at="2026-06-16T12:00:00Z", on_draft_success=on_draft_success,
        annual_cap_check=annual_cap_check,
    )


def _drain(bot_state, monkeypatch, success_ids, *, capture_calls=None):
    """Run the drain with a fake writer that drafts only `success_ids`."""
    from src.orchestrator import common

    def fake_try(bundle, bot_state_, score, *, result_out=None, **kwargs):
        ev = kwargs.get("event_id")
        if capture_calls is not None:
            capture_calls.append(ev)
        ok = ev in success_ids
        if result_out is not None:
            result_out["stage_outcomes"] = {
                "writer": "pass", "fact_check": "pass", "critic": "pass" if ok else "kill",
            }
            if not ok:
                result_out["kill_stage"] = "critic"
        if ok:
            bot_state_.setdefault("drafts", []).append(
                {"event_id": ev, "type": kwargs.get("legacy_type"), "status": "pending",
                 "score": {"total": getattr(score, "total", 0)}}
            )
        return ok

    monkeypatch.setattr(common, "_try_two_bot_draft", fake_try)
    return common._drain_and_write_triage_queue(bot_state, {"id": "r", "sources": []})


# ---------------------------------------------------------------------------
# config + map
# ---------------------------------------------------------------------------

class TestConfig:
    def test_refill_default_off(self, monkeypatch):
        from src.orchestrator import caps
        monkeypatch.delenv("THEHEAT_REFILL_ENABLED", raising=False)
        assert caps.refill_enabled() is False

    def test_target_default_three(self, monkeypatch):
        from src.orchestrator import caps
        monkeypatch.delenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", raising=False)
        assert caps.drafts_target_per_cycle() == 3

    def test_max_attempts_default_double(self, monkeypatch):
        from src.orchestrator import caps
        monkeypatch.delenv("THEHEAT_REFILL_MAX_ATTEMPTS", raising=False)
        assert caps.refill_max_attempts(3) == 6



# ---------------------------------------------------------------------------
# pre-writer predicate
# ---------------------------------------------------------------------------

class TestCanDraftCandidate:
    def test_clean_candidate_ok(self):
        from src.orchestrator.draft_save import can_draft_candidate
        ok, reason = can_draft_candidate(_fresh_state(), _cand(event_id="e1"))
        assert ok is True and reason == ""

    def test_duplicate_draft_blocked(self):
        from src.orchestrator.draft_save import can_draft_candidate
        bot_state = _fresh_state()
        bot_state["drafts"] = [{"event_id": "e1", "status": "pending"}]
        ok, reason = can_draft_candidate(bot_state, _cand(event_id="e1"))
        assert ok is False and reason == "duplicate_draft"

    def test_posted_event_blocked(self):
        from src.orchestrator.draft_save import can_draft_candidate
        bot_state = _fresh_state()
        bot_state["posted_events"] = ["e1"]
        ok, reason = can_draft_candidate(bot_state, _cand(event_id="e1"))
        assert ok is False and reason == "duplicate_posted"

    def test_city_cooldown_blocked(self):
        from src.orchestrator.common import _utc_now_iso
        from src.orchestrator.draft_save import can_draft_candidate
        bot_state = _fresh_state()
        bot_state["drafts"] = [{"event_id": "old", "status": "posted", "city": "Lima",
                                "posted_at": _utc_now_iso()}]
        ok, reason = can_draft_candidate(
            bot_state, _cand(event_id="e1", city="Lima", tweet_date="2026-06-16"))
        assert ok is False and reason == "city_cooldown"

    def test_cooldown_exempt_passes(self):
        from src.orchestrator.common import _utc_now_iso
        from src.orchestrator.draft_save import can_draft_candidate
        bot_state = _fresh_state()
        bot_state["drafts"] = [{"event_id": "old", "status": "posted", "city": "Lima",
                                "posted_at": _utc_now_iso()}]
        ok, _ = can_draft_candidate(
            bot_state, _cand(event_id="e1", city="Lima", tweet_date="2026-06-16", cooldown_exempt=True))
        assert ok is True


# ---------------------------------------------------------------------------
# select_survivors refill mode
# ---------------------------------------------------------------------------

def test_select_survivors_refill_returns_full_ranked(monkeypatch):
    from src.orchestrator.triage import select_survivors
    bot_state = _fresh_state()
    cands = [_cand(event_id=f"e{i}", total=60 + i, signal_kind="drought") for i in range(6)]
    result = select_survivors(bot_state, cands, refill=True)
    assert len(result) == 6  # no per-category/global cap truncation
    assert [c.event_id for c in result] == ["e5", "e4", "e3", "e2", "e1", "e0"]


# ---------------------------------------------------------------------------
# refill loop
# ---------------------------------------------------------------------------

class TestRefillLoop:
    def test_flag_off_uses_legacy_top_n_once(self, monkeypatch):
        """Refill OFF: legacy passthrough attempts each queued candidate once."""
        monkeypatch.delenv("THEHEAT_REFILL_ENABLED", raising=False)
        monkeypatch.setenv("THEHEAT_TRIAGE_ENABLED", "0")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [_cand(event_id="e1"), _cand(event_id="e2", signal_kind="fire", source="firms")]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"e1", "e2"}, capture_calls=calls)
        assert drafted == 2
        assert set(calls) == {"e1", "e2"}

    def test_reaches_deeper_when_top_candidates_fail(self, monkeypatch):
        """Top 3 critic-kill; the loop keeps going down the ranked list to N=3."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "3")
        bot_state = _fresh_state()
        # 8 distinct categories so per-category cap never bites; descending score.
        kinds = ["drought", "fire", "sea_ice_record", "enso", "extreme_wave",
                 "co2_milestone", "ch4_milestone", "ozone_hole_peak"]
        bot_state["_triage_queue"] = [
            _cand(event_id=f"e{i}", total=90 - i, signal_kind=kinds[i], source=f"s{i}")
            for i in range(8)
        ]
        calls: list = []
        # top 3 (e0,e1,e2) fail; e3,e4,e5 succeed -> 3 drafts, 6 attempts
        drafted = _drain(bot_state, monkeypatch, {"e3", "e4", "e5", "e6", "e7"}, capture_calls=calls)
        assert drafted == 3
        assert calls == ["e0", "e1", "e2", "e3", "e4", "e5"]  # stopped at 3 successes

    def test_cooldown_candidate_skipped_with_zero_writer_calls(self, monkeypatch):
        """A cooldown'd top candidate is skipped pre-writer ($0) — no writer call."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        from src.orchestrator.common import _utc_now_iso
        bot_state = _fresh_state()
        bot_state["drafts"] = [{"event_id": "old", "status": "posted", "city": "Lima",
                                "posted_at": _utc_now_iso()}]
        bot_state["_triage_queue"] = [
            _cand(event_id="cold", total=99, signal_kind="drought", source="d1",
                  city="Lima", tweet_date="2026-06-16"),  # cooldown -> skip $0
            _cand(event_id="warm", total=70, signal_kind="fire", source="firms"),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"cold", "warm"}, capture_calls=calls)
        assert "cold" not in calls  # never sent to the writer
        assert "warm" in calls
        assert drafted == 1

    def test_per_category_cap_success_aware(self, monkeypatch):
        """A failed attempt does NOT burn a per-category slot (must-fix #2)."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "2")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        monkeypatch.setenv("THEHEAT_PENDING_TYPE_CAP", "9")
        bot_state = _fresh_state()
        # 4 drought candidates; first fails, next two succeed -> per-category cap (2)
        # is reached by SUCCESSES, so the 4th is cut (not the 3rd via a burned slot).
        bot_state["_triage_queue"] = [
            _cand(event_id="d1", total=95, source="dr"),
            _cand(event_id="d2", total=94, source="dr"),
            _cand(event_id="d3", total=93, source="dr"),
            _cand(event_id="d4", total=92, source="dr"),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"d2", "d3", "d4"}, capture_calls=calls)
        assert drafted == 2  # only 2 drought may succeed
        # d1 attempted (fail), d2 (ok), d3 (ok) -> cap hit by successes; d4 cut, not attempted
        assert calls == ["d1", "d2", "d3"]

    def test_max_attempts_bounds_spend(self, monkeypatch):
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "3")
        monkeypatch.setenv("THEHEAT_REFILL_MAX_ATTEMPTS", "4")
        bot_state = _fresh_state()
        kinds = ["drought", "fire", "sea_ice_record", "enso", "extreme_wave", "ozone_hole_peak"]
        bot_state["_triage_queue"] = [
            _cand(event_id=f"e{i}", total=90 - i, signal_kind=kinds[i], source=f"s{i}")
            for i in range(6)
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, set(), capture_calls=calls)  # all fail
        assert drafted == 0
        assert len(calls) == 4  # capped at max_attempts

    def test_annual_cap_recheck_blocks_overshoot(self, monkeypatch):
        """Two coral candidates with one annual slot left: the 1st draft's callback
        fires INLINE (count -> cap), so the 2nd's annual_cap_check blocks it at admit
        time ($0) — no in-cycle overshoot (must-fix #3, closure-based)."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "5")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        from datetime import date
        from src import state
        from src.orchestrator import caps
        bot_state = _fresh_state()
        year = str(date.today().year)
        bot_state["coral_dhw_annual_count"] = {year: caps.CORAL_DHW_ANNUAL_CAP - 1}  # 1 slot left

        def _check():
            return bot_state.get("coral_dhw_annual_count", {}).get(year, 0) >= caps.CORAL_DHW_ANNUAL_CAP

        def _inc():
            state.increment_coral_dhw_annual_count(bot_state)

        bot_state["_triage_queue"] = [
            _cand(event_id="c1", total=95, signal_kind="coral_bleaching", source="coral_dhw",
                  on_draft_success=_inc, annual_cap_check=_check),
            _cand(event_id="c2", total=94, signal_kind="coral_bleaching", source="coral_dhw",
                  on_draft_success=_inc, annual_cap_check=_check),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"c1", "c2"}, capture_calls=calls)
        assert drafted == 1  # only one fits the annual cap
        assert "c1" in calls and "c2" not in calls  # c2 blocked pre-writer

    def test_duplicate_event_in_slate_skipped(self, monkeypatch):
        """Two candidates share an event_id; the first critic-kills, so the second
        must NOT burn a writer call (codex: distinct candidates only)."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="dup", total=95, signal_kind="drought", source="d1"),
            _cand(event_id="dup", total=80, signal_kind="fire", source="firms"),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, set(), capture_calls=calls)  # first fails
        assert drafted == 0
        assert calls == ["dup"]  # attempted once; the duplicate event is skipped $0


# ---------------------------------------------------------------------------
# per-country cap (codex r2 P1) — THEHEAT_REFILL_ENABLED bypassed the
# per-country cap entirely because _refill_drain() reimplements the
# diversity caps success-aware and never called _per_country_cap(). These
# mirror TestPerCategoryCap's success-aware shape for the country dimension.
# ---------------------------------------------------------------------------

class TestRefillPerCountryCap:
    def test_country_cap_spills_under_refill(self, monkeypatch):
        """codex's exact repro: THEHEAT_REFILL_ENABLED=1 + THEHEAT_PER_COUNTRY_CAP=1
        + 3 same-country (US) candidates -> only 1 drafts, the other 2 spill with
        reason='per_country_cap' (previously: all 3 drafted, zero suppressions).
        us3 uses fire_footprint (a single-country-scoped signal_kind in triage.py's
        _SINGLE_COUNTRY_SIGNAL_KINDS allowlist) rather than river_flood — river_flood's
        `where` is ambiguous free text and is correctly NOT allowlisted (codex r5
        fail-open fix), so it would never take a country key here. This test is about
        3 distinct categories all sharing one country bucket, not about any one
        signal_kind's own where-shape behavior."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")  # don't let category cap interfere
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="us1", total=95, signal_kind="drought", source="s0",
                  where="Phoenix, Arizona, United States", country="US"),
            _cand(event_id="us2", total=94, signal_kind="fire", source="s1",
                  where="Tucson, Arizona, United States", country="US"),
            _cand(event_id="us3", total=93, signal_kind="fire_footprint", source="s2",
                  where="Yuma, Arizona, United States", country="US"),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"us1", "us2", "us3"}, capture_calls=calls)
        assert drafted == 1
        assert calls == ["us1"]  # us2/us3 cut pre-writer — $0, never reach the writer

        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 2
        assert {s["event_id"] for s in supps} == {"us2", "us3"}
        assert all(s["reasons"] == ["per_country_cap=1"] for s in supps)

    def test_country_cap_disabled_all_draft(self, monkeypatch):
        """cap=0 (disabled, the default) -> all 3 same-country candidates draft."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "0")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="us1", total=95, signal_kind="drought", source="s0",
                  where="Phoenix, Arizona, United States", country="US"),
            _cand(event_id="us2", total=94, signal_kind="fire", source="s1",
                  where="Tucson, Arizona, United States", country="US"),
            _cand(event_id="us3", total=93, signal_kind="sea_ice_record", source="s2",
                  where="Yuma, Arizona, United States", country="US"),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"us1", "us2", "us3"}, capture_calls=calls)
        assert drafted == 3
        assert set(calls) == {"us1", "us2", "us3"}

    def test_basin_shaped_where_not_capped_as_country(self, monkeypatch):
        """A cyclone bundle's where='BAVI, WP' has no real country (basin, not a
        country) -> _candidate_country_key() returns "" -> never capped, even
        under cap=1. Both survive and draft."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="cyclone_a", total=90, signal_kind="cyclone_landfall", source="s0",
                  where="BAVI, WP", country=""),
            _cand(event_id="cyclone_b", total=85, signal_kind="cyclone_ri", source="s1",
                  where="BAVI, WP", country=""),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"cyclone_a", "cyclone_b"}, capture_calls=calls)
        assert drafted == 2
        assert set(calls) == {"cyclone_a", "cyclone_b"}

    def test_hot10_not_suppressed_by_country_cap_under_refill(self, monkeypatch):
        """codex r5 P1 repro at the refill layer: cap=1 + a US `fire` candidate
        + a `hot10` candidate (where="Phoenix, US", the leaderboard's
        leader-only where) -> BOTH draft. hot10 is a global multi-country
        summary, not in the fail-open allowlist, so it never takes a
        country-cap key even though its where looks like a normal
        single-city bundle."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="us_fire", total=90, signal_kind="fire", source="s0",
                  where="Phoenix, Arizona, United States", country="US"),
            _cand(event_id="hot10_leaderboard", total=85, signal_kind="hot10", source="s1",
                  where="Phoenix, US", country=""),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"us_fire", "hot10_leaderboard"}, capture_calls=calls)
        assert drafted == 2
        assert set(calls) == {"us_fire", "hot10_leaderboard"}

        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 0

        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 0

    def test_bare_country_where_shares_bucket_under_refill(self, monkeypatch):
        """codex r3 P1 repro (refill path): a country-level record bundle
        (e.g. build_country_record_bundle in temperature.py, or the
        country_precip_event path in precipitation.py) emits a BARE country
        name as `where` (no comma) with no bundle.country. Before the fix
        this got cap-key "" (never capped) and did NOT share a bucket with
        its own city-level records. cap=1 + a bare-country-record bundle
        (where="Kazakhstan") + a "Astana, Kazakhstan" city bundle must now
        share the "kazakhstan" bucket -> only 1 drafts."""
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_PER_COUNTRY_CAP", "1")
        monkeypatch.setenv("THEHEAT_PER_CATEGORY_CAP", "10")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["_triage_queue"] = [
            _cand(event_id="country_record", total=95, signal_kind="country_temp_record",
                  source="s0", where="Kazakhstan", country=""),
            _cand(event_id="astana_spilled", total=90, signal_kind="fire",
                  source="s1", where="Astana, Kazakhstan", country=""),
        ]
        calls: list = []
        drafted = _drain(bot_state, monkeypatch, {"country_record", "astana_spilled"}, capture_calls=calls)
        assert drafted == 1
        assert calls == ["country_record"]  # astana_spilled cut pre-writer

        supps = [s for s in bot_state.get("suppressions", []) if s.get("stage") == "triage_cap"]
        assert len(supps) == 1
        assert supps[0]["event_id"] == "astana_spilled"
        assert supps[0]["reasons"] == ["per_country_cap=1"]


# ---------------------------------------------------------------------------
# prune reconciliation (must-fix #1)
# ---------------------------------------------------------------------------

class TestPruneReconciliation:
    def test_effective_cap_follows_target_under_refill(self, monkeypatch):
        from src.orchestrator import finalize
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        assert finalize._effective_cycle_cap() == 5

    def test_effective_cap_is_max_drafts_when_refill_off(self, monkeypatch):
        from src.orchestrator import finalize
        monkeypatch.delenv("THEHEAT_REFILL_ENABLED", raising=False)
        assert finalize._effective_cycle_cap() == finalize.MAX_DRAFTS_PER_CYCLE

    def test_prune_keeps_target_not_three(self, monkeypatch):
        from src.orchestrator import finalize
        monkeypatch.setenv("THEHEAT_REFILL_ENABLED", "1")
        monkeypatch.setenv("THEHEAT_DRAFTS_TARGET_PER_CYCLE", "5")
        bot_state = _fresh_state()
        bot_state["drafts"] = [
            {"event_id": f"e{i}", "status": "pending", "score": {"total": 60 + i}}
            for i in range(6)
        ]
        kept = finalize._prune_weakest_cycle_drafts(bot_state, 0, {"sources": []}, 6)
        assert kept == 5
        assert len(bot_state["drafts"]) == 5
