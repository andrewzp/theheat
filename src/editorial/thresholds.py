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
    "air_quality_hazard": ThresholdEntry(
        "air_quality_hazard",
        68,
        "CAMS model PM2.5 hazard signal; tier 1 at >=150 μg/m³ 24h-mean "
        "(10x WHO 2021 24h guideline of 15 μg/m³). Moderate confidence "
        "because of 45 km grid resolution and model-estimate evidence grade.",
    ),
    "anomaly": ThresholdEntry(
        "anomaly",
        74,
        "Lowered from 76 in PR #96 so 11-14C anomalies clear while routine 8C swings do not.",
    ),
    "regional_anomaly": ThresholdEntry(
        "regional_anomaly",
        76,
        "Sampled-city regional anomaly from ERA5 daily climatology; a point index "
        "over N cities (never an area-weighted national mean), model-derived, "
        "manual-only at launch. The +6C/3-day/>=2sigma/>=50%-support detection gate "
        "is the noise filter; this threshold is for ranking, not gating. Distinct "
        "from regional_sst_anomaly (oceanic).",
    ),
    "absolute_extreme": ThresholdEntry(
        "absolute_extreme",
        78,
        "Latitude-banded absolute temperature extreme; rarer than per-city anomaly, below all-time-record tier.",
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
    "cyclone_land_threat": ThresholdEntry(
        "cyclone_land_threat",
        70,
        "Warned storm forecast within 150 NM of a named landmass — landfall-grade newsworthiness, forecast-tense, manual_only.",
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
    "dust_event": ThresholdEntry(
        "dust_event",
        66,
        "CAMS model mineral dust event; tier 1 at >=500 μg/m³. Slightly below "
        "air_quality_hazard because dust is a natural geophysical signal with "
        "lower human-harm framing sensitivity.",
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
    "usgs_earthquake": ThresholdEntry(
        "usgs_earthquake",
        70,
        "USGS significant-earthquake feed; separate official earthquake supply from GDACS, manual-only.",
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
    "regional_sst_anomaly": ThresholdEntry(
        "regional_sst_anomaly",
        76,
        "Per-region NOAA Coral Reef Watch published SST anomaly, gridded and "
        "cos-lat area-weighted by basin. Absolute provisional tiers, not Hobday "
        "MHW categories; manual-only at launch.",
    ),
    "wet_bulb_extreme": ThresholdEntry(
        "wet_bulb_extreme",
        78,
        "Absolute heat-stress danger from forecast wet-bulb temperature; manual-only at launch.",
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
    "heat_records_cluster": ThresholdEntry(
        "heat_records_cluster",
        80,
        "Spatially-coherent same-day daily-record cluster (a 'records across [region]' "
        "heat event); set just above simultaneous_records — the spatial coherence is a "
        "stronger story than a scattered count.",
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
    "synthesis_marine_compound": ThresholdEntry(
        "synthesis_marine_compound",
        82,
        "Elite SST x coral synthesis signal; minimum qualifying DHW Alert Level 2 plus regional SST anomaly case clears.",
    ),
    "precipitation_extreme": ThresholdEntry(
        "precipitation_extreme",
        70,
        "Plan E (Lane 13) GPM-IMERG daily precipitation extremes; manual-only approval.",
    ),
    "snow_extreme": ThresholdEntry(
        "snow_extreme",
        70,
        "Plan E (Lane 13) NSIDC Snow Today single-event SWE extremes; manual-only approval.",
    ),
    "seasonal_snow_record": ThresholdEntry(
        "seasonal_snow_record",
        74,
        "Plan E (Lane 13) end-of-season cumulative snowfall record; annual-cap pattern.",
    ),
    "oscillation_transition": ThresholdEntry(
        "oscillation_transition",
        60,
        "Plan F (Lane 14) NAO/AO/PDO phase transitions; mirrors ENSO transition threshold.",
    ),
    "oscillation_extreme": ThresholdEntry(
        "oscillation_extreme",
        64,
        "Plan F (Lane 14) NAO/AO/PDO 2-sigma extreme excursions; long-arc context-driven.",
    ),
    "ozone_hole_peak": ThresholdEntry(
        "ozone_hole_peak",
        64,
        "Plan F (Lane 14) Antarctic ozone hole seasonal peak; annual-cap of 2 tweets/year.",
    ),
}


def get_threshold(category: str) -> int:
    """Return the configured score-gate threshold for a category."""
    return THRESHOLDS[category].threshold
