"""Integration tests for main orchestrator with all externals mocked."""

from unittest.mock import patch, MagicMock
from datetime import date

from src.state import DEFAULT_STATE
from src.main import post_everywhere, run_alerts, run_leaderboard
from src.data.open_meteo import CityTemp, RecordEvent
from src.data.firms import FireEvent
from src.data.co2 import CO2Reading, CO2Milestone, CO2WeeklyComparison


def _fresh_state():
    return dict(DEFAULT_STATE)


class TestPostEverywhere:
    @patch("src.main.state")
    @patch("src.main.post_tweet")
    @patch("src.main.post_to_bluesky")
    def test_respects_daily_cap(self, mock_bs, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = False
        state = _fresh_state()
        result = post_everywhere("test tweet", state)
        assert result is False
        mock_tw.assert_not_called()
        mock_bs.assert_not_called()

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    @patch("src.main.post_to_bluesky")
    def test_dry_run_prints_but_does_not_post(self, mock_bs, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        state = _fresh_state()
        result = post_everywhere("test tweet", state, dry_run=True)
        assert result is True
        mock_tw.assert_not_called()
        mock_bs.assert_not_called()
        mock_state.increment_daily_count.assert_called_once_with(state)

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    @patch("src.main.post_to_bluesky")
    def test_increments_count_on_success(self, mock_bs, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_tw.return_value = {"id": "123"}
        mock_bs.return_value = None
        state = _fresh_state()
        result = post_everywhere("test tweet", state)
        assert result is True
        mock_state.increment_daily_count.assert_called_once_with(state)

    @patch("src.main.state")
    @patch("src.main.post_tweet")
    @patch("src.main.post_to_bluesky")
    def test_no_success_does_not_increment(self, mock_bs, mock_tw, mock_state):
        mock_state.check_daily_cap.return_value = True
        mock_tw.return_value = None
        mock_bs.return_value = None
        state = _fresh_state()
        result = post_everywhere("test tweet", state)
        assert result is False
        mock_state.increment_daily_count.assert_not_called()


class TestRunAlerts:
    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_calls_all_data_sources(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_post
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

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_deduplicates_events(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_post
    ):
        mock_om.load_cities.return_value = []
        mock_om.check_records_for_cities.return_value = [
            RecordEvent("Phoenix", "US", 48.0, 47.0, 2023, "record_phoenix_1"),
        ]
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None
        # Mark event as already posted
        mock_state.is_duplicate.return_value = True

        state = _fresh_state()
        run_alerts(state)

        # Should never call generate because the event is a duplicate
        mock_gen.generate_record_tweet.assert_not_called()

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_data_source_errors_gracefully(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_post
    ):
        mock_om.load_cities.side_effect = Exception("API down")
        mock_firms.fetch_fires.return_value = []
        mock_co2.fetch_co2_data.return_value = []
        mock_co2.detect_milestone.return_value = None

        state = _fresh_state()
        # Should not raise
        result = run_alerts(state)
        assert result is not None
        mock_state.log_error.assert_called()

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.co2")
    @patch("src.main.firms")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_posts_fire_alert(
        self, mock_state, mock_om, mock_firms, mock_co2, mock_gen, mock_post
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
        mock_post.return_value = True

        state = _fresh_state()
        run_alerts(state)

        mock_gen.generate_fire_tweet.assert_called_once()
        mock_post.assert_called()


class TestRunLeaderboard:
    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_computes_anomalies_and_posts(
        self, mock_state, mock_om, mock_gen, mock_post
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
        mock_post.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        mock_om.compute_anomalies.assert_called_once()
        mock_om.rank_hot10.assert_called_once()
        mock_gen.generate_tweet.assert_called_once()
        mock_post.assert_called_once()
        assert result is not None

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_empty_temps_gracefully(
        self, mock_state, mock_om, mock_gen, mock_post
    ):
        mock_om.load_cities.return_value = []
        mock_om.load_normals.return_value = {}
        mock_om.fetch_all_city_temps.return_value = []

        state = _fresh_state()
        result = run_leaderboard(state)

        # Should not attempt to post when no data
        mock_gen.generate_tweet.assert_not_called()
        mock_post.assert_not_called()
        assert result is not None

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_handles_no_valid_anomalies(
        self, mock_state, mock_om, mock_gen, mock_post
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

    @patch("src.main.post_everywhere")
    @patch("src.main.generator")
    @patch("src.main.open_meteo")
    @patch("src.main.state")
    def test_updates_state_with_hot10(
        self, mock_state, mock_om, mock_gen, mock_post
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
        mock_post.return_value = True
        mock_state.update_streaks.return_value = {}

        state = _fresh_state()
        result = run_leaderboard(state)

        assert "last_hot10" in result
        assert "Miami" in result["last_hot10"]["cities"]
