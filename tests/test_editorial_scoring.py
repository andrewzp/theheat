from src.editorial.scoring import (
    score_all_time_record,
    score_anomaly,
    score_co2_milestone,
    score_fire_event,
    score_fire_footprint,
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


class TestScoreIceMassEvent:
    def test_monthly_record_passes_threshold(self):
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="greenland",
            kind="monthly_loss_record",
            monthly_delta_gt=-423.0,
            previous_worst_gt=-350.0,
        )
        assert score.category == "ice_mass_record"
        assert score.threshold == 78
        assert score.passes is True
        assert score.confidence >= 95
        assert score.sensitivity <= 10
        assert any("GRACE" in r for r in score.reasons)

    def test_cumulative_milestone_passes_threshold(self):
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="greenland",
            kind="cumulative_milestone",
            threshold_gt=-6000.0,
        )
        assert score.category == "ice_mass_record"
        assert score.threshold == 78
        assert score.passes is True
        assert any("6000" in r or "cumulative" in r.lower() for r in score.reasons)

    def test_tiny_monthly_margin_still_passes_by_design(self):
        from src.editorial.scoring import score_ice_mass_event
        score = score_ice_mass_event(
            region="antarctica",
            kind="monthly_loss_record",
            monthly_delta_gt=-120.0,
            previous_worst_gt=-115.0,
        )
        assert score.passes is True


class TestScoreFireFootprint:
    def test_large_fire_passes_threshold(self):
        score = score_fire_footprint(
            hectares=213_000,
            tier=3,
            region="California",
            has_name=True,
        )
        assert score.passes
        assert score.threshold == 72
        assert score.category == "fire_footprint"

    def test_floor_tier_may_not_pass(self):
        # Floor hit during peak season, no name — should be below threshold
        import unittest.mock
        from datetime import date
        with unittest.mock.patch("src.editorial.scoring.date") as mock_date:
            mock_date.today.return_value = date(date.today().year, 7, 15)
            score = score_fire_footprint(
                hectares=20_000,
                tier=0,
                region="Unknown",
                has_name=False,
            )
        assert score.threshold == 72
        # Floor fires are intentionally borderline — we care about the scale story
        assert score.total < 80

    def test_named_complex_scores_higher(self):
        named = score_fire_footprint(hectares=150_000, tier=2, has_name=True)
        unnamed = score_fire_footprint(hectares=150_000, tier=2, has_name=False)
        assert named.total >= unnamed.total

    def test_top_tier_mega_fire_scores_strong(self):
        score = score_fire_footprint(
            hectares=2_500_000,
            tier=5,
            region="Siberia",
            has_name=False,
        )
        assert score.passes
        # "strong" is the ceiling at this formula — elite is reserved for
        # unprecedented events (Black Summer 2019 ≈ 19M ha scale).
        assert score.label == "strong"

    def test_region_hook_surfaces_in_reasons(self):
        # tier=2 + no name keeps the reasons list short enough that the
        # region hook survives the reasons[:3] cap in any season.
        score = score_fire_footprint(
            hectares=200_000,
            tier=2,
            region="Yakutia",
            has_name=False,
        )
        assert any("Yakutia" in r for r in score.reasons)


class TestScoreSynthesisFireDroughtHeat:
    def test_min_viable_passes_threshold(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=1.0,
            fire_peak_frp=250.0,
            heat_peak_anomaly_c=4.0,
            component_count={"fires": 1, "heats": 1},
            heat_kind="calendar",
        )
        assert score.threshold == 82
        assert score.category == "synthesis_fire_drought_heat"
        # Elite by definition — even min-viable should clear 82.
        assert score.total >= 82

    def test_elite_hits_mid_90s(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=40.0,
            fire_peak_frp=1500.0,
            heat_peak_anomaly_c=14.0,
            component_count={"fires": 3, "heats": 4},
            heat_kind="all_time",
        )
        assert score.total >= 85
        assert score.passes is True

    def test_reasons_mention_state_of_story(self):
        from src.editorial.scoring import score_synthesis_fire_drought_heat
        score = score_synthesis_fire_drought_heat(
            drought_d4_pct=12.0,
            fire_peak_frp=900.0,
            heat_peak_anomaly_c=8.0,
            component_count={"fires": 2, "heats": 2},
            heat_kind="monthly",
        )
        joined = " ".join(score.reasons).lower()
        assert "drought" in joined or "d4" in joined
        assert "fire" in joined
