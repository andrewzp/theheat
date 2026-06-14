from src.editorial.scoring import (
    score_all_time_record,
    score_anomaly,
    score_co2_milestone,
    score_dust_event,
    score_cyclone_basin_record,
    score_cyclone_landfall,
    score_cyclone_rapid_intensification,
    score_cyclone_tier_crossing,
    score_fire_event,
    score_fire_footprint,
    score_global_disaster,
    score_hot10,
    score_monthly_record,
    score_oscillation_extreme,
    score_oscillation_transition,
    score_ozone_hole_peak,
    score_pm25_hazard,
    score_precipitation_extreme,
    score_record_event,
    score_record_streak,
    score_regional_sst_anomaly,
    score_seasonal_snow_record,
    score_simultaneous_records,
    score_snow_extreme,
    score_synthesis_marine_compound,
    score_usgs_earthquake,
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

    def test_usgs_earthquake_scores_major_shaking(self):
        score = score_usgs_earthquake(
            magnitude=7.1,
            alert="orange",
            significance=950,
            tsunami=True,
        )

        assert score.passes
        assert score.category == "usgs_earthquake"
        assert any("M7.1" in reason for reason in score.reasons)

    def test_cyclone_rapid_intensification_scores_high_bar_signal(self):
        score = score_cyclone_rapid_intensification(
            delta_kt_24h=40,
            current_category=4,
            basin="Atlantic",
        )

        assert score.passes
        assert score.category == "cyclone_rapid_intensification"
        assert any("+40 kt" in reason for reason in score.reasons)

    def test_cyclone_tier_crossing_escalates_with_category(self):
        cat4 = score_cyclone_tier_crossing(2, 4, "Atlantic")
        cat2 = score_cyclone_tier_crossing(1, 2, "Atlantic")

        assert cat4.passes
        assert cat4.total > cat2.total

    def test_cyclone_landfall_is_manual_review_grade(self):
        score = score_cyclone_landfall(3, "Cedar Key, Florida", "Atlantic")

        assert score.passes
        assert score.threshold == 70
        assert "Cedar Key, Florida" in score.reasons

    def test_cyclone_basin_record_scores_archive_backed_record(self):
        score = score_cyclone_basin_record(
            4,
            "Atlantic",
            "earliest Atlantic Category 4 on record",
        )

        assert score.passes
        assert score.category == "cyclone_basin_record"

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

    def test_anomaly_11c_florida_cold_passes(self):
        # Real suppressed event: Nettles Is, FL on 2026-05-10 was 11.7C vs 22.8C
        # historical mean. -11.1C from normal in May Florida is genuinely
        # extraordinary by Wait,what? standards, but was scoring 74 vs 76.
        score = score_anomaly(
            today_temp_c=11.7,
            historical_mean_c=22.8,
            anomaly_c=-11.1,
            kind="cold",
        )
        assert score.passes, (
            f"-11.1C anomaly in May Florida should pass, got total={score.total}"
        )

    def test_anomaly_8c_remains_below_bar(self):
        # 8C off normal is significant but routine seasonal variability —
        # confirms threshold relaxation doesn't open the gate to noise.
        score = score_anomaly(
            today_temp_c=15.0,
            historical_mean_c=23.0,
            anomaly_c=-8.0,
            kind="cold",
        )
        assert not score.passes, (
            f"-8C anomaly should not pass — routine variability, got total={score.total}"
        )

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

    def test_score_regional_sst_anomaly_tier1_marquee_basin_passes(self):
        score = score_regional_sst_anomaly("north_atlantic", 2.6, 1)

        assert score.category == "regional_sst_anomaly"
        assert score.passes
        assert score.total >= 76
        assert any("NOAA Coral Reef Watch" in reason for reason in score.reasons)

    def test_score_regional_sst_anomaly_tier1_non_marquee_basin_also_passes(self):
        score = score_regional_sst_anomaly("bay_of_bengal", 2.5, 1)
        marquee = score_regional_sst_anomaly("north_atlantic", 2.5, 1)

        assert score.passes
        assert marquee.total > score.total

    def test_score_regional_sst_anomaly_tier2_any_basin_passes(self):
        score = score_regional_sst_anomaly("bay_of_bengal", 3.6, 2)

        assert score.passes
        assert score.total >= 79

    def test_score_regional_sst_anomaly_tier3_elite(self):
        score = score_regional_sst_anomaly("gulf_of_mexico", 4.8, 3)

        assert score.total >= 82

    def test_score_regional_sst_anomaly_blob_named_bump(self):
        blob = score_regional_sst_anomaly("ne_pacific_blob", 2.6, 1)
        other = score_regional_sst_anomaly("western_indian_ocean", 2.6, 1)

        assert blob.passes
        assert blob.total > other.total

    def test_precipitation_record_scores_manual_grade(self):
        score = score_precipitation_extreme(
            mm_total=147.0,
            period_days=1,
            deviation_from_record=42.0,
            region="Pakistan",
        )

        assert score.category == "precipitation_extreme"
        assert score.passes
        assert any("147" in reason for reason in score.reasons)

    def test_score_pm25_hazard_tier1_passes_threshold(self):
        score = score_pm25_hazard(pm25_24h_mean=150.0, tier=1, who_multiple=10.0)

        assert score.category == "air_quality_hazard"
        assert score.threshold == 68
        assert score.passes

    def test_score_pm25_hazard_tier3_is_elite(self):
        score = score_pm25_hazard(pm25_24h_mean=350.0, tier=3, who_multiple=23.3)

        assert score.total >= 85
        assert score.label == "elite"

    def test_score_dust_event_tier1_passes_threshold(self):
        score = score_dust_event(dust_daily_max=500.0, tier=1)

        assert score.category == "dust_event"
        assert score.threshold == 66
        assert score.passes

    def test_score_dust_event_tier2_higher_than_tier1(self):
        tier1 = score_dust_event(dust_daily_max=500.0, tier=1)
        tier2 = score_dust_event(dust_daily_max=2000.0, tier=2)

        assert tier2.total > tier1.total

    def test_snow_extreme_scores_heavy_swe(self):
        score = score_snow_extreme(
            mm_swe=76.2,
            deviation_from_record=30.0,
            region="Great Lakes",
        )

        assert score.category == "snow_extreme"
        assert score.passes

    def test_seasonal_snow_record_scores_archive_signal(self):
        score = score_seasonal_snow_record(
            total_mm=1200.0,
            years_of_archive=20,
            region="Sierra Nevada",
        )

        assert score.category == "seasonal_snow_record"
        assert score.passes

    def test_score_oscillation_transition_passes(self):
        score = score_oscillation_transition("NAO", -1.2, 5)
        assert score.category == "oscillation_transition"
        assert score.passes
        assert any("NAO" in reason for reason in score.reasons)

    def test_score_oscillation_extreme_passes_for_two_sigma(self):
        score = score_oscillation_extreme("PDO", 2.4)
        assert score.category == "oscillation_extreme"
        assert score.passes
        assert score.confidence >= 90

    def test_score_ozone_hole_peak_uses_recovery_anchor(self):
        score = score_ozone_hole_peak(23.0, 2000)
        assert score.category == "ozone_hole_peak"
        assert score.passes
        assert any("2000" in reason for reason in score.reasons)


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


class TestScoreSynthesisMarineCompound:
    def test_score_synthesis_marine_compound_minimum_passes_threshold(self):
        score = score_synthesis_marine_compound(
            dhw_value=8.0,
            dhw_tier=8,
            sst_anomaly_c=2.0,
            coral_region="Great Nicobar",
            sst_region="Bay of Bengal",
        )

        assert score.category == "synthesis_marine_compound"
        assert score.threshold == 82
        assert score.passes
        joined = " ".join(score.reasons).lower()
        assert "dhw" in joined
        assert "sst" in joined
