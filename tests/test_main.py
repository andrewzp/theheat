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
        mock_om.check_extreme_signals_for_cities.return_value = [bundle]
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_monthly_record_tweet.assert_not_called()

    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_allows_monthly_when_old_record_prior_year(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
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
        mock_om.check_extreme_signals_for_cities.return_value = [bundle]
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_gen.generate_monthly_record_tweet.return_value = "mock tweet"
        mock_draft.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_monthly_record_tweet.assert_called_once()


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
        mock_om.check_extreme_signals_for_cities.return_value = []
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
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    def test_allows_milestone_below_cap(
        self, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_extreme_signals_for_cities.return_value = []
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = [MagicMock()]
        mock_co2.detect_milestone.return_value = CO2Milestone(
            ppm_crossed=436,
            actual_ppm=436.1,
            date="2026-04-19",
            event_id="co2_milestone_436ppm",
        )
        mock_gen.generate_co2_milestone_tweet.return_value = "mock tweet"
        mock_draft.return_value = True

        state = _fresh_state()
        # 3 tweets this year is well under cap — milestone should draft
        from datetime import date

        state["co2_annual_count"] = {str(date.today().year): 3}

        run_alerts(state)
        mock_gen.generate_co2_milestone_tweet.assert_called_once()


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
        mock_om.check_extreme_signals_for_cities.return_value = []
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
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_drafts_fire_alert(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_draft
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_records_for_cities.return_value = []
        mock_firms.fetch_fires.return_value = [
            FireEvent(34.0, -118.0, 95, 250.0, "Southwestern US", "US", "fire_1"),
        ]
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False
        mock_gen.generate_fire_tweet.return_value = "Fire in Southwestern US."
        mock_draft.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_fire_tweet.assert_called_once()
        mock_draft.assert_called()


class TestRunLeaderboard:
    @patch("src.main.save_draft")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_computes_anomalies_and_drafts(
        self, mock_state, mock_om, mock_gen, mock_draft
    ):
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
        mock_gen.generate_tweet.return_value = "Hot 10 today: Phoenix +15."
        mock_draft.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_om.compute_anomalies.assert_called_once()
        mock_om.rank_hot10.assert_called_once()
        mock_gen.generate_tweet.assert_called_once()
        mock_draft.assert_called_once()
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
