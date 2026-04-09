from src.editorial.scoring import (
    score_co2_milestone,
    score_fire_event,
    score_global_disaster,
    score_hot10,
    score_record_event,
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
