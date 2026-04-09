"""Integration tests for main orchestrator with all externals mocked."""

from copy import deepcopy
from unittest.mock import patch, MagicMock
from datetime import date

from src.state import DEFAULT_STATE
from src.main import save_draft, post_approved, run_alerts, run_leaderboard, run_manual_tweet, process_due_drafts
from src.data.open_meteo import CityTemp, RecordEvent
from src.data.firms import FireEvent
from src.data.co2 import CO2Reading, CO2Milestone, CO2WeeklyComparison


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
        mock_om.check_records_for_cities.return_value = []
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        mock_state.is_duplicate.return_value = False

        state = _fresh_state()
        run_alerts(state)

        mock_om.load_cities.assert_called_once()
        mock_om.check_records_for_cities.assert_called_once()
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


class TestProcessDueDrafts:
    @patch("src.main.post_approved")
    def test_posts_due_auto_approved_drafts(self, mock_post):
        mock_post.return_value = "posted"
        state = _fresh_state()
        state["drafts"] = [{
            "id": "draft_1",
            "text": "Queued draft",
            "status": "pending",
            "auto_approve_at": "2000-01-01T00:00:00Z",
        }]

        result = process_due_drafts(state)

        assert result["drafts"][0]["status"] == "posted"
        assert result["drafts"][0]["approval_mode"] == "auto"

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
