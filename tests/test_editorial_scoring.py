from src.editorial.scoring import (
    score_all_time_record,
    score_anomaly,
    score_co2_milestone,
    score_fire_event,
    score_global_disaster,
    score_hot10,
    score_monthly_record,
    score_record_event,
    score_record_streak,
    score_simultaneous_records,
)


class TestEditorialScoring:
    def test_old_record_scores_strongly(self):
        score = score_record_event(42.1, 39.8, 1929)
        assert score.passes
        assert score.total >= score.threshold
        assert any("record" in reason for reason in score.reasons)

    def test_small_fresh_record_can_be_suppressed(self):
        score = score_record_event(21.1, 21.0, 2025)
        assert not score.passes

    def test_large_fire_scores_above_threshold(self):
        score = score_fire_event(97, 1200, region="Northern California")
        assert score.passes
        assert score.label in {"strong", "elite"}

    def test_co2_milestone_is_high_confidence(self):
        score = score_co2_milestone(434, 434.02)
        assert score.passes
        assert score.confidence >= 95

    def test_gdacs_red_alert_scores_higher_than_orange(self):
        red = score_global_disaster("Red", "Tropical Cyclone")
        orange = score_global_disaster("Orange", "Flood")
        assert red.total > orange.total

    def test_hot10_prefers_large_anomaly_days(self):
        strong = score_hot10(9.7, 10, 3)
        weak = score_hot10(3.1, 10, 0)
        assert strong.total > weak.total

    def test_all_time_record_scores_elite(self):
        score = score_all_time_record(45.8, 45.2, 1998, years_of_data=30, kind="high")
        assert score.passes
        assert score.label in {"strong", "elite"}
        assert score.threshold >= 78

    def test_monthly_record_scores_above_calendar(self):
        monthly = score_monthly_record(44.0, 42.3, 2015, month=4, years_of_data=30, kind="high")
        calendar = score_record_event(44.0, 42.3, 2015)
        assert monthly.total > calendar.total
        assert monthly.passes

    def test_anomaly_above_threshold_passes(self):
        score = score_anomaly(today_temp_c=40.0, historical_mean_c=22.0, anomaly_c=18.0, kind="hot")
        assert score.passes

    def test_record_streak_escalates_with_days(self):
        short = score_record_streak(consecutive_days=3, peak_temp_c=42.0)
        long = score_record_streak(consecutive_days=15, peak_temp_c=45.0)
        assert long.total > short.total
        assert short.passes  # 3+ days should fire

    def test_simultaneous_records_requires_multiple_cities(self):
        small = score_simultaneous_records(city_count=5, sample_cities=["A","B","C","D","E"])
        large = score_simultaneous_records(city_count=15, sample_cities=["A","B","C","D","E"])
        assert large.total > small.total
        assert large.passes

    def test_score_marine_heatwave_day_5_passes_threshold(self):
        from src.editorial.scoring import score_marine_heatwave
        score = score_marine_heatwave(days=5, peak_anomaly_c=0.25, years_of_data=44)
        assert score.category == "marine_heatwave"
        assert score.threshold == 78
        assert score.passes, f"day-5 streak should pass, got {score.total}"

    def test_score_marine_heatwave_day_100_is_elite(self):
        from src.editorial.scoring import score_marine_heatwave
        score = score_marine_heatwave(days=100, peak_anomaly_c=0.4, years_of_data=44)
        assert score.total >= 85, f"day-100 should be elite, got {score.total}"
