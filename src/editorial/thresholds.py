"""Centralized editorial score-gate thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThresholdEntry:
    category: str
    threshold: int
    rationale: str


THRESHOLDS: dict[str, ThresholdEntry] = {
    "all_time_record": ThresholdEntry(
        "all_time_record",
        80,
        "Elite archive-wide temperature records; historical value, not retuned in this refactor.",
    ),
    "anomaly": ThresholdEntry(
        "anomaly",
        74,
        "Lowered from 76 in PR #96 so 11-14C anomalies clear while routine 8C swings do not.",
    ),
    "ch4_milestone": ThresholdEntry(
        "ch4_milestone",
        58,
        "Low-sensitivity NOAA methane milestone signal; historical value, not retuned in this refactor.",
    ),
    "co2_milestone": ThresholdEntry(
        "co2_milestone",
        58,
        "Low-sensitivity NOAA CO2 milestone signal; historical value, not retuned in this refactor.",
    ),
    "coral_bleaching": ThresholdEntry(
        "coral_bleaching",
        72,
        "NOAA Coral Reef Watch bleaching alert crossing; historical value, not retuned in this refactor.",
    ),
    "country_high": ThresholdEntry(
        "country_high",
        82,
        "Country-level heat records are elite national stories; historical value, not retuned in this refactor.",
    ),
    "country_low": ThresholdEntry(
        "country_low",
        82,
        "Country-level cold records use the same national-story bar as country heat records.",
    ),
    "cyclone_basin_record": ThresholdEntry(
        "cyclone_basin_record",
        72,
        "Archive-backed basin record signal; historical value, not retuned in this refactor.",
    ),
    "cyclone_landfall": ThresholdEntry(
        "cyclone_landfall",
        70,
        "Confirmed major cyclone landfall manual-review bar; historical value, not retuned in this refactor.",
    ),
    "cyclone_rapid_intensification": ThresholdEntry(
        "cyclone_rapid_intensification",
        70,
        "High-bar cyclone rapid-intensification signal; historical value, not retuned in this refactor.",
    ),
    "cyclone_tier_crossing": ThresholdEntry(
        "cyclone_tier_crossing",
        68,
        "Saffir-Simpson category upgrade signal; historical value, not retuned in this refactor.",
    ),
    "drought": ThresholdEntry(
        "drought",
        62,
        "Extreme or exceptional drought footprint signal; historical value, not retuned in this refactor.",
    ),
    "drought_empty": ThresholdEntry(
        "drought",
        60,
        "No-input drought sentinel preserves the prior empty-state gate without changing the output category.",
    ),
    "enso": ThresholdEntry(
        "enso",
        56,
        "Monthly ENSO regime change signal; historical value, not retuned in this refactor.",
    ),
    "extreme_wave": ThresholdEntry(
        "extreme_wave",
        62,
        "Extreme wave-height event signal; historical value, not retuned in this refactor.",
    ),
    "fire": ThresholdEntry(
        "fire",
        64,
        "Active wildfire FIRMS signal; historical value, not retuned in this refactor.",
    ),
    "fire_footprint": ThresholdEntry(
        "fire_footprint",
        72,
        "Cumulative burn-area tier crossing; historical value, not retuned in this refactor.",
    ),
    "global_disaster": ThresholdEntry(
        "global_disaster",
        62,
        "GDACS global disaster alert signal; historical value, not retuned in this refactor.",
    ),
    "global_flood": ThresholdEntry(
        "global_flood",
        72,
        "Copernicus EMS mapped flood activation with population/area impact.",
    ),
    "hot10": ThresholdEntry(
        "hot10",
        56,
        "Daily recurring Hot10 scoreboard; historical value, not retuned in this refactor.",
    ),
    "ice_mass_record": ThresholdEntry(
        "ice_mass_record",
        78,
        "GRACE-FO monthly-loss and cumulative ice-mass record signal; historical value, not retuned.",
    ),
    "marine_heatwave": ThresholdEntry(
        "marine_heatwave",
        78,
        "Multi-day marine heatwave streak signal; historical value, not retuned in this refactor.",
    ),
    "monthly_record": ThresholdEntry(
        "monthly_record",
        76,
        "Calendar-month temperature record signal; historical value, not retuned in this refactor.",
    ),
    "record": ThresholdEntry(
        "record",
        72,
        "City-level daily temperature record signal; historical value, not retuned in this refactor.",
    ),
    "record_low": ThresholdEntry(
        "record_low",
        72,
        "City-level daily cold-record signal; historical value, not retuned in this refactor.",
    ),
    "record_streak": ThresholdEntry(
        "record_streak",
        74,
        "Multi-day daily-record streak; historical value preserves the 3+ day firing behavior.",
    ),
    "river_flood": ThresholdEntry(
        "river_flood",
        62,
        "River gauge flood-stage exceedance signal; historical value, not retuned in this refactor.",
    ),
    "sea_ice_record": ThresholdEntry(
        "sea_ice_record",
        60,
        "Long-run sea-ice extent record signal; historical value, not retuned in this refactor.",
    ),
    "severe_weather": ThresholdEntry(
        "severe_weather",
        58,
        "Fast-moving NWS warning signal; historical value, not retuned in this refactor.",
    ),
    "simultaneous_records": ThresholdEntry(
        "simultaneous_records",
        78,
        "Multiple-city same-day record pattern signal; historical value, not retuned in this refactor.",
    ),
    "storm_surge": ThresholdEntry(
        "storm_surge",
        60,
        "Coastal storm-surge anomaly signal; historical value, not retuned in this refactor.",
    ),
    "synthesis_fire_drought_heat": ThresholdEntry(
        "synthesis_fire_drought_heat",
        82,
        "Elite synthesis signal; minimum qualifying fire, drought, and heat case is designed to clear.",
    ),
}


def get_threshold(category: str) -> int:
    """Return the configured score-gate threshold for a category."""
    return THRESHOLDS[category].threshold
