from src.editorial.approval import recommend_approval_policy


class TestApprovalPolicy:
    def test_hot10_can_arm_automatically(self):
        policy = recommend_approval_policy(
            "hot10",
            signal_total=76,
            candidate_score={"total": 80},
        )

        assert policy.mode == "armed_auto"
        assert policy.recommended_delay_minutes == 20

    def test_sensitive_events_require_manual_review(self):
        policy = recommend_approval_policy(
            "global_disaster",
            signal_total=92,
            candidate_score={"total": 83},
        )

        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False

    def test_records_recommend_slower_review_window(self):
        policy = recommend_approval_policy(
            "record",
            signal_total=74,
            candidate_score={"total": 73},
        )

        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 90

    def test_marine_heatwave_suggested_auto_90min(self):
        policy = recommend_approval_policy(
            "marine_heatwave", signal_total=82, candidate_score={"total": 80},
        )
        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 90
        assert policy.can_auto_approve is True
        assert policy.key == "marine_heatwave_review"

    def test_regional_sst_anomaly_requires_manual_review(self):
        policy = recommend_approval_policy(
            "regional_sst_anomaly",
            signal_total=82,
            candidate_score={"total": 80},
        )

        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False
        assert policy.key == "regional_sst_anomaly_manual"

    def test_ch4_milestone_can_arm_automatically(self):
        policy = recommend_approval_policy(
            "ch4_milestone",
            signal_total=76,
            candidate_score={"total": 80},
        )
        assert policy.mode == "armed_auto"
        assert policy.can_auto_approve is True
        assert policy.key == "ch4_auto_window"

    def test_coral_bleaching_requires_manual_review(self):
        policy = recommend_approval_policy(
            "coral_bleaching",
            signal_total=82,
            candidate_score={"total": 80},
        )
        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False

    def test_oscillation_transition_arms_automatically(self):
        policy = recommend_approval_policy(
            "oscillation_transition",
            signal_total=70,
            candidate_score={"total": 70},
        )
        assert policy.mode == "armed_auto"
        assert policy.can_auto_approve is True

    def test_oscillation_extreme_gets_review_window(self):
        policy = recommend_approval_policy(
            "oscillation_extreme",
            signal_total=72,
            candidate_score={"total": 72},
        )
        assert policy.mode == "suggested_auto"
        assert policy.key == "oscillation_review"

    def test_ozone_hole_peak_gets_measured_review_window(self):
        policy = recommend_approval_policy(
            "ozone_hole_peak",
            signal_total=74,
            candidate_score={"total": 72},
        )
        assert policy.mode == "suggested_auto"
        assert policy.key == "ozone_hole_review"

    def test_fire_footprint_requires_manual_review(self):
        policy = recommend_approval_policy(
            "fire_footprint",
            signal_total=88,
            candidate_score={"total": 82},
        )
        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False

    def test_cyclone_events_require_manual_review(self):
        policy = recommend_approval_policy(
            "cyclone_rapid_intensification",
            signal_total=88,
            candidate_score={"total": 82},
        )
        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False

    def test_precipitation_and_snow_require_manual_review(self):
        for tweet_type in ("precipitation_extreme", "snow_extreme", "seasonal_snow_record"):
            policy = recommend_approval_policy(
                tweet_type,
                signal_total=88,
                candidate_score={"total": 82},
            )
            assert policy.mode == "manual_only"
            assert policy.can_auto_approve is False

    def test_regional_anomaly_requires_manual_review(self):
        # Without this branch it would default to auto-approve — the opposite of intent.
        policy = recommend_approval_policy(
            "regional_anomaly",
            signal_total=88,
            candidate_score={"total": 82},
        )
        assert policy.mode == "manual_only"
        assert policy.can_auto_approve is False
        assert policy.key == "manual_only"  # joins the shared human-impact set


class TestIceMassApproval:
    def test_ice_mass_record_policy(self):
        from src.editorial.approval import recommend_approval_policy
        policy = recommend_approval_policy(
            tweet_type="ice_mass_record",
            signal_total=84,
            candidate_score={"total": 78},
        )
        assert policy.key == "ice_mass_review"
        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 105
        assert policy.can_auto_approve is True


class TestSynthesisPolicy:
    def test_fire_drought_heat_suggested_auto_120min(self):
        from src.editorial.approval import recommend_approval_policy
        policy = recommend_approval_policy(
            "synthesis_fire_drought_heat",
            signal_total=88,
            candidate_score={"total": 78},
        )
        assert policy.mode == "suggested_auto"
        assert policy.recommended_delay_minutes == 120
        assert policy.can_auto_approve is True
        assert policy.key == "synthesis_review"

    def test_marine_compound_manual_only(self):
        from src.editorial.approval import recommend_approval_policy
        policy = recommend_approval_policy(
            "synthesis_marine_compound",
            signal_total=88,
            candidate_score={"total": 78},
        )
        assert policy.mode == "manual_only"
        assert policy.recommended_delay_minutes is None
        assert policy.can_auto_approve is False
        assert policy.key == "manual_only"
