"""Editorial scoring public API."""

from __future__ import annotations

from datetime import date
from typing import Any

from ._shared import EditorialScore
from . import temperature as _temperature
from . import fire as _fire
from . import atmospheric as _atmospheric
from . import marine as _marine
from . import disasters as _disasters
from . import drought as _drought
from . import hot10 as _hot10
from . import synthesis as _synthesis
from . import precipitation as _precipitation
from . import wetbulb as _wetbulb

_DATE_MODULES = (
    _temperature,
    _fire,
    _marine,
)


def _sync_date() -> None:
    for module in _DATE_MODULES:
        if hasattr(module, 'date'):
            setattr(module, "date", date)



def score_record_event(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_record_event(*args, **kwargs)


def score_country_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_country_record(*args, **kwargs)


def score_record_low_event(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_record_low_event(*args, **kwargs)


def score_all_time_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_all_time_record(*args, **kwargs)


def score_monthly_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_monthly_record(*args, **kwargs)


def score_anomaly(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_anomaly(*args, **kwargs)


def score_absolute_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_absolute_extreme(*args, **kwargs)


def score_record_streak(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_record_streak(*args, **kwargs)


def score_simultaneous_records(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _temperature.score_simultaneous_records(*args, **kwargs)


def score_fire_event(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _fire.score_fire_event(*args, **kwargs)


def score_fire_footprint(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _fire.score_fire_footprint(*args, **kwargs)


def score_co2_milestone(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_co2_milestone(*args, **kwargs)


def score_ch4_milestone(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_ch4_milestone(*args, **kwargs)


def score_enso_transition(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_enso_transition(*args, **kwargs)


def score_oscillation_transition(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_oscillation_transition(*args, **kwargs)


def score_oscillation_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_oscillation_extreme(*args, **kwargs)


def score_ozone_hole_peak(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _atmospheric.score_ozone_hole_peak(*args, **kwargs)


def score_coral_bleaching(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _marine.score_coral_bleaching(*args, **kwargs)


def score_sea_ice_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _marine.score_sea_ice_record(*args, **kwargs)


def score_ice_mass_event(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _marine.score_ice_mass_event(*args, **kwargs)


def score_extreme_wave(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _marine.score_extreme_wave(*args, **kwargs)


def score_marine_heatwave(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _marine.score_marine_heatwave(*args, **kwargs)


def score_severe_weather(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_severe_weather(*args, **kwargs)


def score_global_disaster(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_global_disaster(*args, **kwargs)


def score_global_flood(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_global_flood(*args, **kwargs)


def score_cyclone_rapid_intensification(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_cyclone_rapid_intensification(*args, **kwargs)


def score_cyclone_tier_crossing(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_cyclone_tier_crossing(*args, **kwargs)


def score_cyclone_landfall(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_cyclone_landfall(*args, **kwargs)


def score_cyclone_basin_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_cyclone_basin_record(*args, **kwargs)


def score_storm_surge(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_storm_surge(*args, **kwargs)


def score_river_flood(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _disasters.score_river_flood(*args, **kwargs)


def score_drought(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _drought.score_drought(*args, **kwargs)


def score_hot10(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _hot10.score_hot10(*args, **kwargs)


def score_synthesis_fire_drought_heat(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _synthesis.score_synthesis_fire_drought_heat(*args, **kwargs)


def score_precipitation_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _precipitation.score_precipitation_extreme(*args, **kwargs)


def score_snow_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _precipitation.score_snow_extreme(*args, **kwargs)


def score_seasonal_snow_record(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _precipitation.score_seasonal_snow_record(*args, **kwargs)


def score_wet_bulb_extreme(*args: Any, **kwargs: Any) -> EditorialScore:
    _sync_date()
    return _wetbulb.score_wet_bulb_extreme(*args, **kwargs)


__all__ = [
    "EditorialScore",
    "score_record_event",
    "score_country_record",
    "score_record_low_event",
    "score_all_time_record",
    "score_monthly_record",
    "score_anomaly",
    "score_absolute_extreme",
    "score_record_streak",
    "score_simultaneous_records",
    "score_fire_event",
    "score_fire_footprint",
    "score_co2_milestone",
    "score_ch4_milestone",
    "score_enso_transition",
    "score_oscillation_transition",
    "score_oscillation_extreme",
    "score_ozone_hole_peak",
    "score_coral_bleaching",
    "score_sea_ice_record",
    "score_ice_mass_event",
    "score_extreme_wave",
    "score_marine_heatwave",
    "score_severe_weather",
    "score_global_disaster",
    "score_global_flood",
    "score_cyclone_rapid_intensification",
    "score_cyclone_tier_crossing",
    "score_cyclone_landfall",
    "score_cyclone_basin_record",
    "score_storm_surge",
    "score_river_flood",
    "score_drought",
    "score_hot10",
    "score_synthesis_fire_drought_heat",
    "score_precipitation_extreme",
    "score_snow_extreme",
    "score_seasonal_snow_record",
    "score_wet_bulb_extreme",
]
