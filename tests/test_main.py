"""Integration tests for main orchestrator with all externals mocked."""

from copy import deepcopy
from unittest.mock import patch, MagicMock
from datetime import date

from src.state import DEFAULT_STATE
from src.main import save_draft, post_approved, run_alerts, run_leaderboard, run_manual_tweet, process_due_drafts
from src.data.open_meteo import CityTemp, RecordEvent
from src.data.firms import FireEvent
from src.data.co2 import CO2Reading, CO2Milestone


def _fresh_state():
    return deepcopy(DEFAULT_STATE)


class TestSaveDraft:
    def test_saves_draft_to_state(self):
        state = _fresh_state()
        result = save_draft("test tweet", state, "record", "evt_1")
        assert result is True
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "test tweet"
        assert state["drafts"][0]["status"] == "pending"

    def test_deduplicates_by_event_id(self):
        state = _fresh_state()
        save_draft("tweet 1", state, "record", "evt_1")
        result = save_draft("tweet 2", state, "record", "evt_1")
        assert result is False
        assert len(state["drafts"]) == 1

    def test_allows_empty_event_id(self):
        state = _fresh_state()
        save_draft("tweet 1", state, "custom", "")
        save_draft("tweet 2", state, "custom", "")
        assert len(state["drafts"]) == 2

    def test_persists_score_metadata(self):
        from src.editorial.scoring import score_co2_milestone

        state = _fresh_state()
        score = score_co2_milestone(434, 434.02)
        save_draft("test tweet", state, "co2_milestone", "evt_1", score=score)
        assert state["drafts"][0]["score"]["total"] == score.total
        assert state["drafts"][0]["score"]["passes"] is True

    def test_persists_candidate_metadata(self):
        from src.editorial.candidates import rank_candidates
        from src.editorial.scoring import score_record_event

        state = _fresh_state()
        bundle = rank_candidates(
            [
                "Phoenix just hit 121F. NEW RECORD. The old one was from 1998.",
                "Phoenix with 121F today. That broke a 27-year record.",
            ],
            "record",
        )
        score = score_record_event(49.4, 47.2, 1998)
        save_draft(
            bundle.text,
            state,
            "record",
            "evt_record",
            score=score,
            candidates=[candidate.as_dict() for candidate in bundle.candidates],
            candidate_score=bundle.selected_score.as_dict(),
        )

        assert len(state["drafts"][0]["candidates"]) == 2
        assert state["drafts"][0]["candidate_score"]["total"] == bundle.selected_score.total

    def test_persists_review_context(self):
        from src.editorial.scoring import score_fire_event

        state = _fresh_state()
        score = score_fire_event(97, 1200, region="Northern California")
        review_context = {
            "source": "NASA FIRMS",
            "source_key": "firms",
            "headline": "Wildfire signal near Northern California",
            "facts": [{"label": "Satellite confidence", "value": "97%"}],
            "run_id": "run_alerts_1",
        }

        save_draft(
            "Fire signal draft",
            state,
            "fire",
            "fire_evt",
            score=score,
            review_context=review_context,
        )

        assert state["drafts"][0]["review_context"]["source"] == "NASA FIRMS"
        assert state["drafts"][0]["review_context"]["facts"][0]["value"] == "97%"

    def test_arms_policy_auto_for_hot10(self):
        from src.editorial.scoring import score_hot10

        state = _fresh_state()
        score = score_hot10(9.2, 10, 3)
        save_draft(
            "Hot 10 draft",
            state,
            "hot10",
            "hot10_evt",
            score=score,
            candidate_score={"total": 81},
        )

        assert state["drafts"][0]["approval_policy"]["mode"] == "armed_auto"
        assert state["drafts"][0]["auto_approve_at"].endswith("Z")
        assert state["drafts"][0]["approval_mode"] == "policy_auto"

    def test_blocks_auto_policy_for_sensitive_drafts(self):
        from src.editorial.scoring import score_global_disaster

        state = _fresh_state()
        score = score_global_disaster("Red", "Cyclone")
        save_draft(
            "Disaster draft",
            state,
            "global_disaster",
            "gdacs_evt",
            score=score,
            candidate_score={"total": 84},
        )

        assert state["drafts"][0]["approval_policy"]["mode"] == "manual_only"
        assert "auto_approve_at" not in state["drafts"][0]


class TestSameCityDayDedup:
    """One tweet per (city, date). Highest signal score wins."""

    def _score_with_total(self, total: int):
        from src.editorial.scoring import EditorialScore

        return EditorialScore(
            category="record",
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            total=total,
            threshold=72,
            reasons=[],
        )

    def test_stronger_signal_supersedes_pending(self):
        state = _fresh_state()
        save_draft(
            "weak Bujumbura tweet",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        result = save_draft(
            "strong Bujumbura tweet",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(82),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is True
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "strong Bujumbura tweet"
        assert state["drafts"][0]["score"]["total"] == 82

    def test_weaker_signal_dropped(self):
        state = _fresh_state()
        save_draft(
            "strong tweet",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(82),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        result = save_draft(
            "weak tweet",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is False
        assert len(state["drafts"]) == 1
        assert state["drafts"][0]["text"] == "strong tweet"

    def test_different_cities_both_saved(self):
        state = _fresh_state()
        save_draft(
            "Bujumbura",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        save_draft(
            "Medan",
            state,
            "record",
            "record_Medan_2026-04-18",
            score=self._score_with_total(72),
            city="Medan",
            tweet_date="2026-04-18",
        )
        assert len(state["drafts"]) == 2

    def test_same_city_different_dates_both_saved(self):
        state = _fresh_state()
        save_draft(
            "day one",
            state,
            "record",
            "record_Bujumbura_2026-04-18",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        save_draft(
            "day two",
            state,
            "all_time_high",
            "all_time_high_Bujumbura_2026-04-19",
            score=self._score_with_total(80),
            city="Bujumbura",
            tweet_date="2026-04-19",
            cooldown_exempt=True,
        )
        assert len(state["drafts"]) == 2

    def test_already_posted_same_day_skipped(self):
        state = _fresh_state()
        state["drafts"].append(
            {
                "id": "draft_1",
                "text": "posted already",
                "type": "record",
                "event_id": "record_Bujumbura_2026-04-18",
                "status": "posted",
                "city": "Bujumbura",
                "tweet_date": "2026-04-18",
                "posted_at": "2026-04-18T10:00:00Z",
                "score": {"total": 72},
            }
        )
        result = save_draft(
            "stronger too late",
            state,
            "monthly_high",
            "monthly_high_Bujumbura_2026_04",
            score=self._score_with_total(85),
            city="Bujumbura",
            tweet_date="2026-04-18",
        )
        assert result is False
        assert len(state["drafts"]) == 1


class TestCityCooldown:
    """After we post about a city, suppress that city for N days unless elite."""

    def _score_with_total(self, total: int):
        from src.editorial.scoring import EditorialScore

        return EditorialScore(
            category="record",
            severity=0,
            novelty=0,
            timeliness=0,
            confidence=0,
            shareability=0,
            sensitivity=0,
            total=total,
            threshold=72,
            reasons=[],
        )

    def _seed_recent_posted_draft(self, state: dict, city: str, hours_ago: int):
        from datetime import timedelta

        from src.main import _utc_now

        posted_at = (_utc_now() - timedelta(hours=hours_ago)).isoformat().replace(
            "+00:00", "Z"
        )
        state["drafts"].append(
            {
                "id": f"draft_old_{city}",
                "text": f"old {city} tweet",
                "type": "record",
                "event_id": f"record_{city}_old",
                "status": "posted",
                "city": city,
                "tweet_date": "2026-04-15",
                "posted_at": posted_at,
                "score": {"total": 72},
            }
        )

    def test_blocks_non_elite_within_cooldown(self):
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix again",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
        )
        assert result is False
        assert len(state["drafts"]) == 1

    def test_allows_elite_during_cooldown(self):
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix all-time record",
            state,
            "all_time_high",
            "all_time_high_Phoenix_2026-04-19",
            score=self._score_with_total(85),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=True,
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_allows_non_elite_after_cooldown_expires(self):
        state = _fresh_state()
        # 4 days ago — past the 3-day cooldown
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=4 * 24)
        result = save_draft(
            "Phoenix after cooldown",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_no_city_no_cooldown(self):
        """Events without a city (CO2 milestone, simultaneous, etc.) are unaffected."""
        state = _fresh_state()
        # Seed a recent posted draft with no city attached
        state["drafts"].append(
            {
                "id": "co2_old",
                "text": "old CO2",
                "type": "co2_milestone",
                "event_id": "co2_434",
                "status": "posted",
                "posted_at": "2026-04-18T10:00:00Z",
            }
        )
        result = save_draft(
            "new CO2",
            state,
            "co2_milestone",
            "co2_435",
            score=self._score_with_total(65),
        )
        assert result is True

    def test_exceptional_copy_bypasses_cooldown(self):
        """candidate_score.total >= 95 lets an otherwise-blocked draft through."""
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix with stunning copy",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
            candidate_score={"total": 96},
        )
        assert result is True
        assert len(state["drafts"]) == 2

    def test_merely_good_copy_does_not_bypass_cooldown(self):
        """Copy at 94 still respects cooldown — only >=95 counts as elite."""
        state = _fresh_state()
        self._seed_recent_posted_draft(state, "Phoenix", hours_ago=24)
        result = save_draft(
            "Phoenix good but not great",
            state,
            "record",
            "record_Phoenix_2026-04-19",
            score=self._score_with_total(74),
            city="Phoenix",
            tweet_date="2026-04-19",
            cooldown_exempt=False,
            candidate_score={"total": 94},
        )
        assert result is False
        assert len(state["drafts"]) == 1

    def test_pending_drafts_do_not_trigger_cooldown(self):
        """Cooldown only triggers on posted tweets, not pending drafts."""
        state = _fresh_state()
        save_draft(
            "first Phoenix draft",
            state,
            "record",
            "record_Phoenix_2026-04-18",
            score=self._score_with_total(72),
            city="Phoenix",
            tweet_date="2026-04-18",
        )
        # Different day, different city — no cooldown because the prior is pending
        result = save_draft(
            "Bujumbura new day",
            state,
            "record",
            "record_Bujumbura_2026-04-19",
            score=self._score_with_total(72),
            city="Bujumbura",
            tweet_date="2026-04-19",
        )
        assert result is True


class TestMonthlyRecordSameYearSuppression:
    """Monthly records where the prior record was set in the current calendar
    year read as nonsense ('hottest April — previous record set in 2026').
    Suppress them at detection."""

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_suppresses_monthly_when_old_record_this_year(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        from src.data.open_meteo import ExtremeSignalBundle, MonthlyRecord
        from datetime import date

        current_year = date.today().year
        # Bundle where the only detected signal is a monthly_high whose
        # prior record was set this calendar year — should be skipped.
        bundle = ExtremeSignalBundle(
            monthly_high=MonthlyRecord(
                city="Svalbard",
                country="NO",
                kind="high",
                month=4,
                new_temp_c=5.3,
                old_record_c=3.7,
                old_record_year=current_year,
                years_of_data=30,
                event_id=f"monthly_high_Svalbard_{current_year}_04",
            ),
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([bundle], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_monthly_record_tweet.assert_not_called()

    @patch("src.main._try_two_bot_draft")
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_allows_monthly_when_old_record_prior_year(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft, mock_two_bot
    ):
        """When the prior record was set in a prior year, the signal
        should be allowed through — and it should hit the two-bot
        pipeline (monthly_high was ported from voice gen to two-bot
        on 2026-05-03 per the no-cheap-model-writing directive)."""
        from src.data.open_meteo import ExtremeSignalBundle, MonthlyRecord
        from datetime import date

        bundle = ExtremeSignalBundle(
            monthly_high=MonthlyRecord(
                city="Svalbard",
                country="NO",
                kind="high",
                month=4,
                new_temp_c=5.3,
                old_record_c=3.7,
                old_record_year=date.today().year - 5,
                years_of_data=30,
                event_id="monthly_high_Svalbard_2021_04",
            ),
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([bundle], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_two_bot.return_value = True

        state = _fresh_state()
        run_alerts(state)

        # Voice generator must NOT be called for monthly_high anymore —
        # this is the whole point of the port.
        mock_gen.generate_monthly_record_tweet.assert_not_called()
        # Two-bot path is exercised. The bundle that flows through is
        # built from the MonthlyRecord above.
        mock_two_bot.assert_called_once()


class TestCO2AnnualCap:
    """At most 12 CO2 tweets per calendar year — prevents feed spam from
    multiple milestones clustering in a noisy week."""

    def test_cap_helpers_increment_and_detect(self):
        from src.main import (
            CO2_ANNUAL_CAP,
            _co2_annual_cap_reached,
            _increment_co2_annual_count,
        )
        from datetime import date

        state = _fresh_state()
        assert _co2_annual_cap_reached(state) is False
        for _ in range(CO2_ANNUAL_CAP):
            _increment_co2_annual_count(state)
        assert _co2_annual_cap_reached(state) is True
        assert state["co2_annual_count"][str(date.today().year)] == CO2_ANNUAL_CAP

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    def test_skips_milestone_when_cap_reached(
        self, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        from src.main import CO2_ANNUAL_CAP
        from datetime import date

        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = [MagicMock()]
        mock_co2.detect_milestone.return_value = CO2Milestone(
            ppm_crossed=436,
            actual_ppm=436.1,
            date="2026-04-19",
            event_id="co2_milestone_436ppm",
        )

        state = _fresh_state()
        state["co2_annual_count"] = {str(date.today().year): CO2_ANNUAL_CAP}

        run_alerts(state)
        # CO2 milestone draft should not have been generated
        mock_gen.generate_co2_milestone_tweet.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    def test_allows_milestone_below_cap(
        self, mock_om, mock_firms, mock_co2, mock_two_bot, mock_gen, mock_draft
    ):
        """Below the annual CO2 cap, a fresh milestone should reach the
        two-bot pipeline (ported from voice gen on 2026-05-04)."""
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = [MagicMock()]
        mock_co2.detect_milestone.return_value = CO2Milestone(
            ppm_crossed=436,
            actual_ppm=436.1,
            date="2026-04-19",
            event_id="co2_milestone_436ppm",
        )
        mock_two_bot.return_value = True

        state = _fresh_state()
        # 3 tweets this year is well under cap — milestone should draft
        from datetime import date

        state["co2_annual_count"] = {str(date.today().year): 3}

        run_alerts(state)
        # Voice gen no longer called; two-bot path is the live path.
        mock_gen.generate_co2_milestone_tweet.assert_not_called()
        mock_two_bot.assert_called_once()


class TestPostApproved:
    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_respects_daily_cap(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = False
        state = _fresh_state()
        result = post_approved("test tweet", state)
        assert result == "failed"
        mock_tw.assert_not_called()

    @patch("src.main.state")
    @patch("src.main.post_to_bluesky")
    @patch("src.main.post_tweet")
    def test_increments_count_on_success(self, mock_tw, mock_bluesky, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_tw.return_value = {"id": "123"}
        state = _fresh_state()
        result = post_approved("test tweet", state)
        assert result == "posted"
        mock_bluesky.assert_called_once_with("test tweet")
        mock_state.increment_daily_count.assert_called_once_with(state)

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_returns_failed_on_failure(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_tw.return_value = None
        state = _fresh_state()
        result = post_approved("test tweet", state)
        assert result == "failed"

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    def test_returns_rate_limited(self, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_tw.return_value = {"error": "rate_limited"}
        state = _fresh_state()
        result = post_approved("test tweet", state)
        assert result == "rate_limited"
        mock_state.increment_daily_count.assert_not_called()


class TestRunAlerts:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_calls_all_data_sources(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_om.load_cities.assert_called_once()
        mock_om.check_extreme_signals_for_cities.assert_called_once()
        mock_firms.fetch_fires.assert_called_once()
        mock_co2.fetch_co2_data.assert_called_once()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_deduplicates_events(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_records_for_cities.return_value = [
            RecordEvent("Phoenix", "US", 48.0, 47.0, 2023, "record_phoenix_1"),
        ]
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_record_tweet.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_data_source_errors_gracefully(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.side_effect = Exception("API down")
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None

        state = _fresh_state()
        result = run_alerts(state)
        assert result is not None
        mock_state.log_error.assert_called()

    @patch("src.main.save_draft")
    @patch("src.two_bot.pipeline.generate_fire_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_drafts_fire_alert(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen,
        mock_generate_fire_draft, mock_draft,
        monkeypatch,
    ):
        # Pin scoring.date.today() to mid-April so the shoulder-season novelty
        # boost keeps the synthetic fire above the editorial threshold across
        # calendar tipover (May would drop a frp=250 signal below 64).
        import src.editorial.scoring as _scoring
        class _FixedAprilDate(date):
            @classmethod
            def today(cls):
                return date(2026, 4, 15)
        monkeypatch.setattr(_scoring, "date", _FixedAprilDate)

        mock_om.load_cities.return_value = []
        mock_om.check_records_for_cities.return_value = []
        mock_firms.fetch_fires.return_value = [
            FireEvent(34.0, -118.0, 95, 250.0, "Southwestern US", "US", "fire_1"),
        ]
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_generate_fire_draft.return_value = {
            "type": "fire",
            "text": "Fire in Southwestern US.",
            "event_id": "fire_1",
            "two_bot_metadata": {"angle_chosen": "plain_number"},
        }
        mock_draft.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_generate_fire_draft.assert_called_once()
        mock_gen.generate_fire_tweet.assert_not_called()
        mock_draft.assert_called()

    def test_run_alerts_ocean_sst_drafts_on_day_5(self, monkeypatch):
        """Day-5 streak crossing → one draft saved under marine_heatwave."""
        from src import main
        from src.main import run_alerts
        from src.data.ocean_sst import GlobalSSTObservation

        fresh_st = _fresh_state()
        fresh_st["ocean_sst_streak"] = {"seeded": True, "last_milestone_fired": None}

        obs = GlobalSSTObservation(
            date="2026-04-20", day_of_year=110,
            today_c=20.52, archive_max_c=20.31,
            archive_max_year=2023, years_of_data=44,
            streak_days=5, streak_start_date="2026-04-16",
            streak_peak_anomaly_c=0.25,
        )

        # Patch all other alert sources to no-ops so only ocean_sst runs.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda cities: ([], []))
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        monkeypatch.setattr(main.co2, "fetch_co2_data", lambda: [])
        monkeypatch.setattr(main.co2, "detect_milestone", lambda readings: None)
        monkeypatch.setattr(main.nws_alerts, "fetch_alerts", lambda: [])
        monkeypatch.setattr(main.gdacs, "fetch_disasters", lambda min_severity=None: [])
        monkeypatch.setattr(main.sea_ice, "fetch_sea_ice", lambda hemisphere=None: [])
        monkeypatch.setattr(main.sea_ice, "detect_record_low", lambda readings: None)
        monkeypatch.setattr(main.drought, "fetch_drought_data", lambda: [])
        monkeypatch.setattr(main.enso, "fetch_enso_data", lambda: [])
        monkeypatch.setattr(main.enso, "detect_transition", lambda readings: None)
        monkeypatch.setattr(main.ocean, "fetch_ocean_conditions", lambda: [])
        monkeypatch.setattr(main.ocean, "detect_extreme_waves", lambda r: [])
        monkeypatch.setattr(main.ocean_sst, "fetch_global_sst", lambda: obs)
        monkeypatch.setattr(main.water_levels, "fetch_water_levels", lambda: [])
        monkeypatch.setattr(main.water_levels, "detect_storm_surge", lambda r: [])
        monkeypatch.setattr(main.river_gauges, "fetch_river_levels", lambda: [])
        monkeypatch.setattr(main.river_gauges, "detect_floods", lambda r: [])

        # Stub the two-bot pipeline (live path post-2026-05-04 port) so
        # we don't make real LLM calls. Side-effect: save a draft to
        # state so the assertions below see the marine_heatwave draft.
        def fake_try_two_bot(bundle, bot_state, score, *, legacy_type, event_id, review_context, **kwargs):
            from src.main import save_draft
            return save_draft(
                "Day 5 of record global SSTs.",
                bot_state, legacy_type, event_id,
                score=score,
                review_context=review_context,
            )
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_try_two_bot)

        run_alerts(fresh_st)

        drafts = fresh_st.get("drafts", [])
        marine_drafts = [d for d in drafts if d.get("type") == "marine_heatwave"]
        assert len(marine_drafts) == 1
        assert "marine_heatwave_streak_5_2026-04-20" in fresh_st.get("posted_events", [])


class TestRunLeaderboard:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_computes_anomalies_and_drafts(
        self, mock_state, mock_om, mock_two_bot, mock_gen, mock_draft
    ):
        """Hot 10 leaderboard: ported from voice gen to two-bot writer
        on 2026-05-04. The voice generator's `generate_tweet` is no
        longer reached for the hot10 category."""
        mock_om.load_cities.return_value = [
            {"city": "Phoenix", "country": "US", "lat": "33.45", "lon": "-112.07"}
        ]
        mock_om.load_normals.return_value = {"Phoenix": {4: 30.0}}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0),
        ]
        mock_om.compute_anomalies.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0, 30.0, 15.0),
        ]
        mock_om.rank_hot10.return_value = [
            CityTemp("Phoenix", "US", 33.45, -112.07, 45.0, 30.0, 15.0),
        ]
        mock_two_bot.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_om.compute_anomalies.assert_called_once()
        mock_om.rank_hot10.assert_called_once()
        mock_gen.generate_tweet.assert_not_called()
        mock_two_bot.assert_called_once()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_empty_temps_gracefully(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = []

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_gen.generate_tweet.assert_not_called()
        mock_draft.assert_not_called()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_no_valid_anomalies(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = [
            {"city": "Unknown", "country": "XX", "lat": "0", "lon": "0"}
        ]
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Unknown", "XX", 0, 0, 30.0),
        ]
        mock_om.compute_anomalies.return_value = []
        mock_om.rank_hot10.return_value = []

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_gen.generate_tweet.assert_not_called()
        assert result is not None

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_updates_state_with_hot10(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0),
        ]
        mock_om.compute_anomalies.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0, 30.0, 8.0),
        ]
        mock_om.rank_hot10.return_value = [
            CityTemp("Miami", "US", 25.76, -80.19, 38.0, 30.0, 8.0),
        ]
        mock_gen.generate_tweet.return_value = "Hot 10: Miami +8."
        mock_draft.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        assert "last_hot10" in result
        assert "Miami" in result["last_hot10"]["cities"]


class TestRunManualTweet:
    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_updates_matching_draft_by_id(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        mock_post.return_value = "posted"
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
        }]

        result = run_manual_tweet(state)

        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["posted_at"].endswith("Z")
        assert "publish_intent_id" not in result["drafts"][0]

    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_returns_draft_to_pending_on_safety_failure(self, mock_safety, mock_post):
        mock_safety.return_value = (False, "Banned pattern: '!'")
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Banned pattern: '!'"

    @patch.dict(
        "os.environ",
        {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1", "PUBLISH_INTENT_ID": "stale-token"},
        clear=True,
    )
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_skips_stale_publish_intent(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "approved",
            "publish_intent_id": "fresh-token",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "approved"

    @patch.dict("os.environ", {"TWEET_TEXT": "Manual draft", "DRAFT_ID": "draft_1"}, clear=True)
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_rejects_non_approved_draft_posts(self, mock_safety, mock_post):
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Manual draft",
            "status": "pending",
        }]

        result = run_manual_tweet(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"


class TestProcessDueDrafts:
    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_posts_due_auto_approved_drafts(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_safety.assert_called_once_with("Queued draft")
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["approval_mode"] == "auto"
        assert "auto_approve_at" not in result["drafts"][0]

    @patch("src.main.post_approved")
    def test_skips_future_auto_approval_windows(self, mock_post):
        mock_post.return_value = "posted"
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2999-01-01T00:00:00Z",
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"

    @patch("src.main.post_approved")
    def test_blocks_due_drafts_when_policy_forbids_auto(self, mock_post):
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {"can_auto_approve": False},
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Auto-approval blocked by policy"

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_safety_rejection_blocks_auto_post(self, mock_safety, mock_post):
        mock_safety.return_value = (False, "Banned pattern: '#climate'")
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Bad draft #climate",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "armed_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["approval_mode"] == "manual"
        assert "safety rejected" in result["drafts"][0]["post_error"]
        assert "auto_approve_at" not in result["drafts"][0]

    @patch("src.main.post_approved")
    @patch("src.main.run_safety_pipeline")
    def test_suggested_auto_posts_when_human_queued_it(self, mock_safety, mock_post):
        mock_post.return_value = "posted"
        mock_safety.return_value = (True, None)
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Suggested draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_mode": "auto",
            "approval_policy": {
                "mode": "suggested_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_called_once_with("Suggested draft", state)
        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["approval_mode"] == "auto"

    @patch("src.main.post_approved")
    def test_suggested_auto_still_blocks_unqueued_state(self, mock_post):
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Suggested draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
            "approval_policy": {
                "mode": "suggested_auto",
                "can_auto_approve": True,
            },
        }]

        result = process_due_drafts(state)

        mock_post.assert_not_called()
        assert result["drafts"][0]["status"] == "pending"
        assert result["drafts"][0]["post_error"] == "Auto-approval blocked by policy"


class TestRunAlertsIceMass:
    def test_monday_with_record_drafts(self, monkeypatch):
        """On a Monday, a fresh monthly record for Greenland drafts a tweet
        and updates state (ice_mass_max_loss + ice_mass_last_seen + count)."""
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 20)  # a Monday

        monkeypatch.setattr(main, "date", FakeDate)

        # Monkeypatch ice_mass module: happy readings, fire a record
        from src.data import ice_mass as ice_mass_mod
        readings = [
            ice_mass_mod.IceMassReading("greenland", "2026-02", -5000.0, 100, "ice_mass_greenland_2026-02"),
            ice_mass_mod.IceMassReading("greenland", "2026-03", -5500.0, 100, "ice_mass_greenland_2026-03"),
        ]
        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass",
                            lambda region: readings if region == "greenland" else [])
        # Short-circuit all other fetchers
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name, None)
            if mod is None:
                continue
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])
        # Stub open_meteo to avoid HTTP calls for all ~600 cities
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda *a, **k: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda *a, **k: ([], []))

        # Stub the two-bot pipeline — ice_mass was ported on 2026-05-04.
        # Returns a draft dict so save_draft is reached and state side-
        # effects run.
        def fake_try_two_bot(bundle, bot_state, score, *, legacy_type, event_id, review_context, **kwargs):
            from src.main import save_draft
            return save_draft(
                "Greenland lost 500 Gt. Largest monthly loss in GRACE record.",
                bot_state, legacy_type, event_id,
                score=score, review_context=review_context,
            )
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_try_two_bot)

        bot_state = {
            "last_hot10": {"date": None, "cities": []},
            "streaks": {},
            "posted_events": [],
            "daily_tweet_count": {},
            "co2_annual_count": {},
            "drafts": [],
            "run_history": [],
            "errors": [],
            "city_all_time_max": {},
            "city_all_time_min": {},
            "city_monthly_max": {},
            "city_monthly_min": {},
            "record_streaks": {},
            "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {},
            "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)

        assert bot_state["ice_mass_last_seen"].get("greenland") == "2026-03"
        assert bot_state["ice_mass_max_loss"].get("greenland", {}).get("gt") == -500.0
        assert bot_state["ice_annual_count"].get("2026", 0) >= 1
        # The event must be recorded
        assert any("ice_mass_record_greenland_monthly_2026-03" == e
                   for e in bot_state["posted_events"])

    def test_non_monday_skips(self, monkeypatch):
        from src import main
        import datetime as _dt

        class FakeDate(_dt.date):
            @classmethod
            def today(cls):
                return _dt.date(2026, 4, 21)  # a Tuesday

        monkeypatch.setattr(main, "date", FakeDate)

        from src.data import ice_mass as ice_mass_mod
        called = {"n": 0}

        def spy(region):
            called["n"] += 1
            return []

        monkeypatch.setattr(ice_mass_mod, "fetch_grace_mass", spy)
        for mod_name in (
            "firms", "co2", "nws_alerts", "gdacs", "sea_ice", "drought", "enso",
            "ocean", "water_levels", "river_gauges",
        ):
            mod = getattr(main, mod_name, None)
            if mod is None:
                continue
            for fn in dir(mod):
                if fn.startswith("fetch_"):
                    monkeypatch.setattr(mod, fn, lambda *a, **k: [])
        # Stub open_meteo to avoid HTTP calls for all ~600 cities
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda *a, **k: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities", lambda *a, **k: ([], []))

        bot_state = {
            "last_hot10": {"date": None, "cities": []}, "streaks": {},
            "posted_events": [], "daily_tweet_count": {}, "co2_annual_count": {},
            "drafts": [], "run_history": [], "errors": [],
            "city_all_time_max": {}, "city_all_time_min": {},
            "city_monthly_max": {}, "city_monthly_min": {},
            "record_streaks": {}, "ice_mass_max_loss": {},
            "ice_mass_last_milestone": {}, "ice_mass_last_seen": {},
            "ice_annual_count": {},
        }
        main.run_alerts(bot_state)
        assert called["n"] == 0


class TestFireFootprintIntegration:
    @patch("src.main._try_two_bot_draft")
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_tier_crossing_creates_draft_and_updates_state(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft, mock_two_bot
    ):
        """Fire footprint ported to two-bot writer on 2026-05-04. The
        FireComplex flows through `build_fire_footprint_bundle` →
        `_try_two_bot_draft`, not the voice generator."""
        from src.data.fire_footprint import FireComplex

        complex = FireComplex(
            complex_id="GWIS_AAA",
            name="Dixie Complex",
            country="US",
            region="California",
            hectares=213_000,
            start_date=None,
            tier=3,
            event_id="fire_footprint_GWIS_AAA_tier3",
        )
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = [complex]
        mock_ff.detect_tier_crossings.return_value = [complex]
        mock_ff.TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]
        mock_state.is_duplicate.return_value = False
        mock_two_bot.return_value = True

        # Wire update_fire_complex_tier side_effect to actually write to state_dict
        def _real_update_tier(sd, complex_id, tier):
            sd.setdefault("fire_complex_tiers", {})[complex_id] = tier

        mock_state.update_fire_complex_tier.side_effect = _real_update_tier

        state_dict = _fresh_state()
        run_alerts(state_dict)

        # Voice gen no longer reached.
        mock_gen.generate_fire_footprint_tweet.assert_not_called()
        # Two-bot is the live path. Inspect the bundle for shape + content.
        mock_two_bot.assert_called_once()
        bundle_arg = mock_two_bot.call_args.args[0]
        assert bundle_arg.signal_kind == "fire_footprint"
        assert bundle_arg.headline_metric["value"] == 213_000

        mock_state.update_fire_complex_tier.assert_called_once_with(state_dict, "GWIS_AAA", 3)
        # State updated with tier
        assert state_dict.get("fire_complex_tiers", {}).get("GWIS_AAA") == 3

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_same_day_second_run_gated_out(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.return_value = []

        state_dict = _fresh_state()
        state_dict["fire_footprint_last_run"] = date.today().isoformat()

        run_alerts(state_dict)

        mock_ff.fetch_active_fire_perimeters.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.fire_footprint")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_fetch_error_is_logged_not_fatal(
        self, mock_state, mock_om, mock_ff, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = ([], [])
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_ff.fetch_active_fire_perimeters.side_effect = RuntimeError("boom")

        state_dict = _fresh_state()

        # Must not raise
        run_alerts(state_dict)
        mock_state.log_error.assert_any_call(state_dict, "fire_footprint", "boom")


class TestPerCycleCapCleanup:
    """Regression: when the per-cycle cap prunes weaker drafts, the
    pruned drafts' event_ids used to remain in posted_events, so later
    cycles skipped those events as "already drafted" even though no
    tweet ever shipped. The per-source drafted telemetry was also left
    overstated."""

    def _seed_drafts_after_mark(self, n: int):
        """Return (bot_state, drafts_before) with n pre-existing drafts
        representing 'this cycle produced n drafts' — each with a
        matching posted_events entry just like run_alerts' per-section
        record_event() does."""
        from src.main import MAX_DRAFTS_PER_CYCLE  # noqa: F401 (import side effect)
        state_dict = _fresh_state()
        drafts_before = 0
        for i in range(n):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": "record",
                "text": f"tweet {i}",
                "status": "pending",
                "score": {"total": 80 - i},  # d0 is strongest, last is weakest
            })
            state_dict["posted_events"].append(f"evt_{i}")
        return state_dict, drafts_before

    def test_pruned_event_ids_removed_from_posted_events(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE + 2)
        assert len(state_dict["posted_events"]) == MAX_DRAFTS_PER_CYCLE + 2

        drafted = _prune_weakest_cycle_drafts(state_dict, drafts_before, None, MAX_DRAFTS_PER_CYCLE + 2)

        assert drafted == MAX_DRAFTS_PER_CYCLE
        kept_event_ids = {d["event_id"] for d in state_dict["drafts"]}
        # Weakest two should have been dropped — those are the highest-
        # numbered event_ids (evt_3, evt_4 if cap is 3).
        assert len(kept_event_ids) == MAX_DRAFTS_PER_CYCLE
        # Critical: pruned events MUST NOT remain in posted_events.
        for e in state_dict["posted_events"]:
            assert e in kept_event_ids, (
                f"Pruned event {e} lingered in posted_events — will block future drafting"
            )

    def test_no_prune_when_under_cap(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE - 1)
        before_posted = list(state_dict["posted_events"])
        drafted = _prune_weakest_cycle_drafts(state_dict, drafts_before, None, MAX_DRAFTS_PER_CYCLE - 1)
        assert drafted == MAX_DRAFTS_PER_CYCLE - 1
        assert state_dict["posted_events"] == before_posted

    def test_rolls_back_source_drafted_telemetry(self):
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict, drafts_before = self._seed_drafts_after_mark(MAX_DRAFTS_PER_CYCLE + 2)
        # Simulate a run record where the two pruned drafts came from
        # the open_meteo source.
        current_run = {
            "sources": [
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE + 2},
            ],
        }
        _prune_weakest_cycle_drafts(state_dict, drafts_before, current_run, MAX_DRAFTS_PER_CYCLE + 2)

        # Two drafts were pruned; drafted count should drop by 2.
        src = current_run["sources"][0]
        assert src["drafted"] == MAX_DRAFTS_PER_CYCLE, (
            f"Expected drafted to roll back to {MAX_DRAFTS_PER_CYCLE}, got {src['drafted']}"
        )

    def test_ice_mass_subsource_telemetry_rollback(self):
        """ice_mass logs as ``ice_mass_greenland`` / ``ice_mass_antarctica``
        rather than plain ``ice_mass``. Prune should match the prefix."""
        from src.main import _prune_weakest_cycle_drafts, MAX_DRAFTS_PER_CYCLE

        state_dict = _fresh_state()
        for i in range(MAX_DRAFTS_PER_CYCLE + 1):
            state_dict["drafts"].append({
                "id": f"d{i}",
                "event_id": f"evt_{i}",
                "type": "ice_mass_record" if i == MAX_DRAFTS_PER_CYCLE else "record",
                "status": "pending",
                "score": {"total": 80 if i < MAX_DRAFTS_PER_CYCLE else 75},
            })
            state_dict["posted_events"].append(f"evt_{i}")
        current_run = {
            "sources": [
                {"source": "ice_mass_greenland", "drafted": 1},
                {"source": "open_meteo_extreme_signals", "drafted": MAX_DRAFTS_PER_CYCLE},
            ],
        }
        _prune_weakest_cycle_drafts(state_dict, 0, current_run, MAX_DRAFTS_PER_CYCLE + 1)

        # The ice_mass_record draft (weakest) was pruned → greenland telemetry rolls back.
        greenland = next(s for s in current_run["sources"] if s["source"] == "ice_mass_greenland")
        assert greenland["drafted"] == 0


class TestSynthesisRecording:
    def test_fire_in_us_records_component(self, monkeypatch):
        from unittest.mock import MagicMock
        from copy import deepcopy
        from src.state import DEFAULT_STATE
        from src import main
        from src.data import firms

        bot_state = deepcopy(DEFAULT_STATE)

        fake_fire = MagicMock(
            event_id="fire_38.58_-121.49_2026-04-20",
            lat=38.58, lon=-121.49,
            nearest_city="Sacramento", country="United States",
            confidence=95, frp=1500.0,
        )
        monkeypatch.setattr(firms, "fetch_fires", lambda: [fake_fire])
        monkeypatch.setattr(main, "_save_generated_draft", lambda *a, **kw: True)
        # Short-circuit open-meteo + others.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))

        main.run_alerts(bot_state)

        fires = bot_state["synthesis_components"]["fires"].get("California", [])
        assert any(f["event_id"] == fake_fire.event_id for f in fires)


class TestSynthesisStage:
    def test_synthesis_stage_creates_draft(self, monkeypatch):
        from copy import deepcopy
        from datetime import datetime, timedelta, UTC
        from src.state import (
            DEFAULT_STATE,
            record_synthesis_component,
            record_synthesis_drought_snapshot,
        )
        from src import main

        bot_state = deepcopy(DEFAULT_STATE)
        now = datetime.now(UTC)
        iso = lambda d: (now - timedelta(days=d)).isoformat().replace("+00:00", "Z")

        record_synthesis_drought_snapshot(bot_state, [
            {"state": "California", "d3_pct": 25.0, "d4_pct": 10.0, "total_drought_pct": 85.0},
        ])
        record_synthesis_component(bot_state, kind="fire", region="California",
            event_id="pre_fire", metadata={"frp": 1400.0, "region": "Sacramento"},
            timestamp=iso(2))
        record_synthesis_component(bot_state, kind="heat", region="California",
            event_id="pre_heat",
            metadata={"kind": "calendar", "city": "Sacramento", "value_c": 40.0},
            timestamp=iso(1))

        # Short-circuit every per-source fetch so only the synthesis stage runs.
        monkeypatch.setattr(main.open_meteo, "load_cities", lambda: [])
        monkeypatch.setattr(main.open_meteo, "check_extreme_signals_for_cities",
                            lambda cities: ([], []))
        monkeypatch.setattr(main.firms, "fetch_fires", lambda: [])
        # Synthesis was ported to two-bot writer on 2026-05-04. Stub
        # `_try_two_bot_draft` to capture the call without making real
        # LLM requests.
        captured = {}
        def fake_two_bot(bundle, bot_state_arg, score, *, legacy_type, event_id, review_context, **kwargs):
            captured["legacy_type"] = legacy_type
            captured["event_id"] = event_id
            captured["bundle_signal_kind"] = bundle.signal_kind
            return True
        monkeypatch.setattr(main, "_try_two_bot_draft", fake_two_bot)

        main.run_alerts(bot_state)

        assert captured.get("legacy_type") == "synthesis_fire_drought_heat"
        assert captured.get("bundle_signal_kind") == "synthesis_fire_drought_heat"
        assert "california" in captured["event_id"]
        # Cooldown must have been recorded so a second cycle is suppressed.
        cooldown = bot_state["synthesis_cooldown"].get("fire_drought_heat") or {}
        assert "California" in cooldown
