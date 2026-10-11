"""Two-bot intern public API, loading only the requested hazard builder."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ._shared import _c_to_f, _is_us_country
    from .temperature import build_monthly_high_bundle, build_country_record_bundle, build_record_bundle, build_all_time_record_bundle, build_anomaly_bundle, build_absolute_extreme_bundle, build_regional_anomaly_bundle, build_record_streak_bundle, build_simultaneous_records_bundle, build_heat_records_cluster_bundle, build_hot10_bundle
    from .fire import build_fire_bundle, build_fire_footprint_bundle
    from .atmospheric import build_co2_milestone_bundle, build_ch4_milestone_bundle, build_enso_bundle, build_oscillation_bundle, build_ozone_hole_bundle
    from .disasters import build_severe_weather_bundle, build_global_disaster_bundle, build_usgs_earthquake_bundle, build_cyclone_rapid_intensification_bundle, build_cyclone_tier_crossing_bundle, build_cyclone_landfall_bundle, build_cyclone_basin_record_bundle, build_cyclone_land_threat_bundle, build_river_flood_bundle, build_global_flood_bundle, build_storm_surge_bundle
    from .marine import build_coral_bleaching_bundle, build_sea_ice_bundle, build_ice_mass_bundle, build_marine_heatwave_bundle, build_regional_sst_anomaly_bundle, build_extreme_wave_bundle
    from .drought import build_drought_bundle
    from .synthesis import build_synthesis_bundle
    from .precipitation import build_precipitation_bundle, build_snow_extreme_bundle, build_seasonal_snow_bundle
    from .air_quality import build_pm25_hazard_bundle, build_dust_event_bundle
    from .wetbulb import build_wet_bulb_bundle

_EXPORTS = {
    '_c_to_f': '_shared',
    '_is_us_country': '_shared',
    'build_monthly_high_bundle': 'temperature',
    'build_country_record_bundle': 'temperature',
    'build_record_bundle': 'temperature',
    'build_all_time_record_bundle': 'temperature',
    'build_anomaly_bundle': 'temperature',
    'build_absolute_extreme_bundle': 'temperature',
    'build_regional_anomaly_bundle': 'temperature',
    'build_record_streak_bundle': 'temperature',
    'build_simultaneous_records_bundle': 'temperature',
    'build_heat_records_cluster_bundle': 'temperature',
    'build_hot10_bundle': 'temperature',
    'build_fire_bundle': 'fire',
    'build_fire_footprint_bundle': 'fire',
    'build_co2_milestone_bundle': 'atmospheric',
    'build_ch4_milestone_bundle': 'atmospheric',
    'build_enso_bundle': 'atmospheric',
    'build_oscillation_bundle': 'atmospheric',
    'build_ozone_hole_bundle': 'atmospheric',
    'build_severe_weather_bundle': 'disasters',
    'build_global_disaster_bundle': 'disasters',
    'build_usgs_earthquake_bundle': 'disasters',
    'build_cyclone_rapid_intensification_bundle': 'disasters',
    'build_cyclone_tier_crossing_bundle': 'disasters',
    'build_cyclone_landfall_bundle': 'disasters',
    'build_cyclone_basin_record_bundle': 'disasters',
    'build_cyclone_land_threat_bundle': 'disasters',
    'build_river_flood_bundle': 'disasters',
    'build_global_flood_bundle': 'disasters',
    'build_storm_surge_bundle': 'disasters',
    'build_coral_bleaching_bundle': 'marine',
    'build_sea_ice_bundle': 'marine',
    'build_ice_mass_bundle': 'marine',
    'build_marine_heatwave_bundle': 'marine',
    'build_regional_sst_anomaly_bundle': 'marine',
    'build_extreme_wave_bundle': 'marine',
    'build_drought_bundle': 'drought',
    'build_synthesis_bundle': 'synthesis',
    'build_precipitation_bundle': 'precipitation',
    'build_snow_extreme_bundle': 'precipitation',
    'build_seasonal_snow_bundle': 'precipitation',
    'build_pm25_hazard_bundle': 'air_quality',
    'build_dust_event_bundle': 'air_quality',
    'build_wet_bulb_bundle': 'wetbulb',
}

__all__ = [
    "_c_to_f",
    "_is_us_country",
    "build_monthly_high_bundle",
    "build_country_record_bundle",
    "build_record_bundle",
    "build_all_time_record_bundle",
    "build_anomaly_bundle",
    "build_absolute_extreme_bundle",
    "build_regional_anomaly_bundle",
    "build_record_streak_bundle",
    "build_simultaneous_records_bundle",
    "build_heat_records_cluster_bundle",
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
    "build_usgs_earthquake_bundle",
    "build_cyclone_rapid_intensification_bundle",
    "build_cyclone_tier_crossing_bundle",
    "build_cyclone_landfall_bundle",
    "build_cyclone_basin_record_bundle",
    "build_cyclone_land_threat_bundle",
    "build_river_flood_bundle",
    "build_global_flood_bundle",
    "build_storm_surge_bundle",
    "build_coral_bleaching_bundle",
    "build_sea_ice_bundle",
    "build_ice_mass_bundle",
    "build_marine_heatwave_bundle",
    "build_regional_sst_anomaly_bundle",
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


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module("." + module, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
