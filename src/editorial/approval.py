from __future__ import annotations

"""Approval policy heuristics for draft review and auto-publish windows."""

import os
from dataclasses import dataclass


# Phase B — decouple the ship gate. A HARD, explicit tweet_type allowlist for
# auto-shipping on a critic PASS — NOT inferred from policy mode / can_auto_approve
# (the default policy returns suggested_auto + can_auto_approve=True for ANY unknown
# type, and suggested_auto also covers country records / ozone / ice mass / generic
# synthesis_*).
#
# The set is governed by one principle: **auto-ship verifiable RECORDS; keep
# anomalies and human-impact events in manual review.** Records are factual,
# archive-/dataset-backed, low human-harm, and low-volume, so a critic PASS is
# sufficient confidence to post unattended (still on a guarded, delayed window) —
# and leaving them to die in an unwatched manual queue is the failure this fixes.
#   - leaderboard + global atmospheric milestones: hot10, co2_milestone, ch4_milestone
#   - station/all-time + monthly temperature records: all_time_high/low, monthly_high/low
#   - ocean SST streak record: marine_heatwave (single well-known dataset, low-harm)
# DELIBERATELY EXCLUDED (stay manual): calendar-day records ("record"/"record_low" —
# high-volume, fire routinely → would flood); regional_anomaly + anomaly_* +
# absolute_extreme (interpretive framing / bare-region honesty risk); country_high/low
# (national records — rare but elite enough to keep a human polish window); and every
# human-impact type (fire, cyclone_*, coral_bleaching, dust, air_quality, wet_bulb,
# synthesis_*). cyclone_land_threat (#375) is manual by the cyclone_ prefix rule
# below — a FORECAST-tense event must always cross a human before posting.
# The THEHEAT_AUTOSHIP_ON_CRITIC_PASS flag and the critic remain the
# kill-switches; flag OFF is byte-for-byte the manual behavior.
AUTOSHIP_ALLOWLIST: frozenset[str] = frozenset({
    "hot10", "co2_milestone", "ch4_milestone",
    "all_time_high", "all_time_low",
    "monthly_high", "monthly_low",
    "marine_heatwave",
})

_DEFAULT_AUTOSHIP_MAX_AGE_H = 36


def autoship_on_critic_pass_enabled() -> bool:
    """True only when THEHEAT_AUTOSHIP_ON_CRITIC_PASS is explicitly truthy.

    Default OFF. This is the live-posting switch — flag OFF is byte-for-byte the
    current behavior, and flipping it back to 0 (repo variable, no deploy) stops
    auto-shipping immediately, including drafts already marked in the queue.
    """
    raw = os.environ.get("THEHEAT_AUTOSHIP_ON_CRITIC_PASS", "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def autoship_max_age_hours() -> int:
    """Freshness ceiling for auto-shipping (THEHEAT_AUTOSHIP_MAX_AGE_H, default 36).

    A draft older than this baked its real-time framing too long ago to post
    unattended — it is handed back to manual review (kills the staleness spiral).
    """
    try:
        return max(1, int(os.environ.get("THEHEAT_AUTOSHIP_MAX_AGE_H", str(_DEFAULT_AUTOSHIP_MAX_AGE_H))))
    except (TypeError, ValueError):
        return _DEFAULT_AUTOSHIP_MAX_AGE_H


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

    if tweet_type == "ch4_milestone":
        if is_strong:
            return ApprovalPolicy(
                key="ch4_auto_window",
                mode="armed_auto",
                recommended_delay_minutes=45,
                can_auto_approve=True,
                reason="High-confidence atmospheric methane signal with low human-harm risk.",
            )
        return ApprovalPolicy(
            key="ch4_review",
            mode="suggested_auto",
            recommended_delay_minutes=90,
            can_auto_approve=True,
            reason="Methane drafts are safe to auto-queue, but middling copy should wait for review.",
        )

    if tweet_type == "oscillation_transition":
        return ApprovalPolicy(
            key="oscillation_transition_auto_window",
            mode="armed_auto",
            recommended_delay_minutes=60,
            can_auto_approve=True,
            reason="High-confidence NOAA monthly climate-mode phase shift with low blast radius.",
        )

    if tweet_type in {"oscillation_extreme", "oscillation_alignment"}:
        return ApprovalPolicy(
            key="oscillation_review",
            mode="suggested_auto",
            recommended_delay_minutes=90,
            can_auto_approve=True,
            reason="Low-sensitivity climate-mode signal, but long-cycle framing benefits from review.",
        )

    if tweet_type == "ozone_hole_peak":
        return ApprovalPolicy(
            key="ozone_hole_review",
            mode="suggested_auto",
            recommended_delay_minutes=120,
            can_auto_approve=True,
            reason="Annual NASA ozone-hole recovery signal. Review window keeps the framing measured.",
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

    if tweet_type == "ice_mass_record":
        return ApprovalPolicy(
            key="ice_mass_review",
            mode="suggested_auto",
            recommended_delay_minutes=105,
            can_auto_approve=True,
            reason="GRACE ice-mass milestone — rare, elite signal. Mid-length review window for framing polish.",
        )

    if tweet_type in {"record", "record_low", "sea_ice_record", "enso", "extreme_wave"}:
        return ApprovalPolicy(
            key="editorial_hold",
            mode="suggested_auto",
            recommended_delay_minutes=90 if tweet_type.startswith("record") else 120,
            can_auto_approve=True,
            reason="Low-sensitivity climate/weather signal that benefits from a slower editorial timer.",
        )

    if tweet_type == "regional_sst_anomaly":
        return ApprovalPolicy(
            key="regional_sst_anomaly_manual",
            mode="manual_only",
            recommended_delay_minutes=None,
            can_auto_approve=False,
            reason=(
                "New per-region SST anomaly signal from NOAA CRW gridded data. "
                "Verify basin, area-weighted anomaly magnitude, and grid freshness "
                "before posting."
            ),
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

    if (
        tweet_type in {
            "fire",
            "fire_footprint",
            "severe_weather",
            "global_disaster",
            "usgs_earthquake",
            "global_flood",
            "storm_surge",
            "river_flood",
            "drought",
            "coral_bleaching",
            "precipitation_extreme",
            "snow_extreme",
            "seasonal_snow_record",
            "air_quality_hazard",
            "dust_event",
            "absolute_extreme",
            "wet_bulb_extreme",
            "regional_anomaly",
            "heat_records_cluster",
            "synthesis_marine_compound",
        }
        or tweet_type.startswith("cyclone_")
    ):
        return ApprovalPolicy(
            key="manual_only",
            mode="manual_only",
            recommended_delay_minutes=None,
            can_auto_approve=False,
            reason="Potential human-impact event. Keep explicit human approval in the loop.",
        )

    if tweet_type.startswith("synthesis_"):
        return ApprovalPolicy(
            key="synthesis_review",
            mode="suggested_auto",
            recommended_delay_minutes=120,
            can_auto_approve=True,
            reason="Cross-source synthesis claim — factually brittle by nature. Keep a 120-minute review window so a human can verify the framing before auto-post.",
        )

    return ApprovalPolicy(
        key="default_review",
        mode="suggested_auto",
        recommended_delay_minutes=120,
        can_auto_approve=True,
        reason="No explicit policy matched, so default to a conservative review window.",
    )
