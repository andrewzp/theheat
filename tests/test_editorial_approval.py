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
