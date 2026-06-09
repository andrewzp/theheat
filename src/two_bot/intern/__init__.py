"""Two-bot intern public API."""

from __future__ import annotations

from ._shared import _c_to_f, _is_us_country
from .temperature import build_monthly_high_bundle, build_country_record_bundle, build_record_bundle, build_all_time_record_bundle, build_anomaly_bundle, build_absolute_extreme_bundle, build_record_streak_bundle, build_simultaneous_records_bundle, build_hot10_bundle
from .fire import build_fire_bundle, build_fire_footprint_bundle
from .atmospheric import build_co2_milestone_bundle, build_ch4_milestone_bundle, build_enso_bundle, build_oscillation_bundle, build_ozone_hole_bundle
from .disasters import build_severe_weather_bundle, build_global_disaster_bundle, build_cyclone_rapid_intensification_bundle, build_cyclone_tier_crossing_bundle, build_cyclone_landfall_bundle, build_cyclone_basin_record_bundle, build_river_flood_bundle, build_global_flood_bundle, build_storm_surge_bundle
from .marine import build_coral_bleaching_bundle, build_sea_ice_bundle, build_ice_mass_bundle, build_marine_heatwave_bundle, build_extreme_wave_bundle
from .drought import build_drought_bundle
from .synthesis import build_synthesis_bundle
from .precipitation import build_precipitation_bundle, build_snow_extreme_bundle, build_seasonal_snow_bundle
from .air_quality import build_pm25_hazard_bundle, build_dust_event_bundle
from .wetbulb import build_wet_bulb_bundle

__all__ = [
    "_c_to_f",
    "_is_us_country",
    "build_monthly_high_bundle",
    "build_country_record_bundle",
    "build_record_bundle",
    "build_all_time_record_bundle",
    "build_anomaly_bundle",
    "build_absolute_extreme_bundle",
    "build_record_streak_bundle",
    "build_simultaneous_records_bundle",
    "build_hot10_bundle",
    "build_fire_bundle",
    "build_fire_footprint_bundle",
    "build_co2_milestone_bundle",
    "build_ch4_milestone_bundle",
    "build_enso_bundle",
    "build_oscillation_bundle",
    "build_ozone_hole_bundle",
    "build_severe_weather_bundle",
    "build_global_disaster_bundle",
    "build_cyclone_rapid_intensification_bundle",
    "build_cyclone_tier_crossing_bundle",
    "build_cyclone_landfall_bundle",
    "build_cyclone_basin_record_bundle",
    "build_river_flood_bundle",
    "build_global_flood_bundle",
    "build_storm_surge_bundle",
    "build_coral_bleaching_bundle",
    "build_sea_ice_bundle",
    "build_ice_mass_bundle",
    "build_marine_heatwave_bundle",
    "build_extreme_wave_bundle",
    "build_drought_bundle",
    "build_synthesis_bundle",
    "build_precipitation_bundle",
    "build_snow_extreme_bundle",
    "build_seasonal_snow_bundle",
    "build_pm25_hazard_bundle",
    "build_dust_event_bundle",
    "build_wet_bulb_bundle",
]
