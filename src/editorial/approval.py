from __future__ import annotations

"""Approval policy heuristics for draft review and auto-publish windows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalPolicy:
    key: str
    mode: str
    recommended_delay_minutes: int | None
    can_auto_approve: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "mode": self.mode,
            "recommended_delay_minutes": self.recommended_delay_minutes,
            "can_auto_approve": self.can_auto_approve,
            "reason": self.reason,
        }


def _candidate_total(candidate_score: dict | None) -> int:
    if not isinstance(candidate_score, dict):
        return 0
    total = candidate_score.get("total", 0)
    return int(total) if isinstance(total, (int, float)) else 0


def recommend_approval_policy(
    tweet_type: str,
    *,
    signal_total: int,
    candidate_score: dict | None = None,
) -> ApprovalPolicy:
    """Return the editorial auto-approval posture for a draft."""
    copy_total = _candidate_total(candidate_score)
    is_strong = signal_total >= 72 and copy_total >= 72
    is_good = signal_total >= 66 and copy_total >= 68

    if tweet_type == "hot10":
        if is_good:
            return ApprovalPolicy(
                key="hot10_fast_lane",
                mode="armed_auto",
                recommended_delay_minutes=20,
                can_auto_approve=True,
                reason="Recurring low-sensitivity leaderboard with strong signal and copy.",
            )
        return ApprovalPolicy(
            key="hot10_review",
            mode="suggested_auto",
            recommended_delay_minutes=30,
            can_auto_approve=True,
            reason="Hot 10 is usually safe to queue, but weaker copy should get a quick look first.",
        )

    if tweet_type == "co2_milestone":
        if is_strong:
            return ApprovalPolicy(
                key="co2_auto_window",
                mode="armed_auto",
                recommended_delay_minutes=45,
                can_auto_approve=True,
                reason="High-confidence atmospheric signal with low human-harm risk.",
            )
        return ApprovalPolicy(
            key="co2_review",
            mode="suggested_auto",
            recommended_delay_minutes=90,
            can_auto_approve=True,
            reason="CO2 drafts are safe to auto-queue, but middling copy should wait for review.",
        )

    if tweet_type in {"country_high", "country_low"}:
        # The biggest story the pipeline produces — but rare enough to keep
        # a human-aware review window. Suggested-auto, longer delay.
        return ApprovalPolicy(
            key="country_record_review",
            mode="suggested_auto",
            recommended_delay_minutes=120,
            can_auto_approve=True,
            reason="Country-level archive record — rare, elite signal. Review window gives the human a chance to polish the framing.",
        )

    if tweet_type in {"record", "record_low", "sea_ice_record", "enso", "extreme_wave"}:
        return ApprovalPolicy(
            key="editorial_hold",
            mode="suggested_auto",
            recommended_delay_minutes=90 if tweet_type.startswith("record") else 120,
            can_auto_approve=True,
            reason="Low-sensitivity climate/weather signal that benefits from a slower editorial timer.",
        )

    if tweet_type == "marine_heatwave":
        return ApprovalPolicy(
            key="marine_heatwave_review",
            mode="suggested_auto",
            recommended_delay_minutes=90,
            can_auto_approve=True,
            reason=(
                "Ocean-SST streak signal — low human-harm risk, high accuracy "
                "from a single well-known dataset. Short review window lets a "
                "human polish framing before auto-post."
            ),
        )

    if tweet_type in {"fire", "severe_weather", "global_disaster", "storm_surge", "river_flood", "drought"}:
        return ApprovalPolicy(
            key="manual_only",
            mode="manual_only",
            recommended_delay_minutes=None,
            can_auto_approve=False,
            reason="Potential human-impact event. Keep explicit human approval in the loop.",
        )

    return ApprovalPolicy(
        key="default_review",
        mode="suggested_auto",
        recommended_delay_minutes=120,
        can_auto_approve=True,
        reason="No explicit policy matched, so default to a conservative review window.",
    )
