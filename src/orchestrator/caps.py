"""Draft caps and annual-count helpers for orchestrator sources."""

from __future__ import annotations

from datetime import date
from typing import cast

from src.state_schema import BotState


MAX_DRAFTS = 200
CITY_COOLDOWN_DAYS = 3
ELITE_COPY_SCORE = 95

CO2_ANNUAL_CAP = 12
CH4_ANNUAL_CAP = 12
CORAL_DHW_ANNUAL_CAP = 16
ICE_ANNUAL_CAP = 8
SNOW_ANNUAL_CAP = 8
SST_ANOM_ANNUAL_CAP = 10

_ANNUAL_CAP_LABELS = {
    "co2_annual_count": "co2",
    "ch4_annual_count": "ch4",
    "coral_dhw_annual_count": "coral_dhw",
    "ice_annual_count": "ice_mass",
    "snow_annual_count": "snow",
    "sst_anom_annual_count": "sst_anom",
}


def annual_cap_reached(bot_state: BotState, count_key: str, cap: int) -> bool:
    return _annual_cap_reached_for_year(
        bot_state,
        count_key,
        cap,
        str(date.today().year),
    )


def increment_annual_count(bot_state: BotState, count_key: str) -> None:
    year_key = str(date.today().year)
    state_dict = cast(dict, bot_state)
    counts = state_dict.setdefault(count_key, {})
    counts[year_key] = counts.get(year_key, 0) + 1


def _annual_cap_reached_for_year(
    bot_state: BotState,
    count_key: str,
    cap: int,
    year_key: str,
) -> bool:
    state_dict = cast(dict, bot_state)
    count = state_dict.get(count_key, {}).get(year_key, 0)
    if count >= cap:
        label = _ANNUAL_CAP_LABELS.get(count_key, count_key.removesuffix("_annual_count"))
        print(f"[{label}] Annual cap reached ({count}/{cap} for {year_key}), skipping")
        return True
    return False


def _co2_annual_cap_reached(bot_state: BotState, cap: int = CO2_ANNUAL_CAP) -> bool:
    """True if we've already drafted CO2_ANNUAL_CAP CO2 tweets this calendar year."""
    return annual_cap_reached(bot_state, "co2_annual_count", cap)


def _increment_co2_annual_count(bot_state: BotState) -> None:
    increment_annual_count(bot_state, "co2_annual_count")


def _ch4_annual_cap_reached(bot_state: BotState, cap: int = CH4_ANNUAL_CAP) -> bool:
    return annual_cap_reached(bot_state, "ch4_annual_count", cap)


def _coral_dhw_annual_cap_reached(
    bot_state: BotState,
    cap: int = CORAL_DHW_ANNUAL_CAP,
) -> bool:
    return annual_cap_reached(bot_state, "coral_dhw_annual_count", cap)


def _ice_annual_cap_reached(bot_state: BotState, cap: int = ICE_ANNUAL_CAP) -> bool:
    """True if we've already drafted ICE_ANNUAL_CAP ice-mass tweets this year."""
    return annual_cap_reached(bot_state, "ice_annual_count", cap)


def _increment_ice_annual_count(bot_state: BotState) -> None:
    increment_annual_count(bot_state, "ice_annual_count")


def _snow_annual_cap_reached(bot_state: BotState, cap: int = SNOW_ANNUAL_CAP) -> bool:
    return annual_cap_reached(bot_state, "snow_annual_count", cap)


def _increment_snow_annual_count(bot_state: BotState) -> None:
    increment_annual_count(bot_state, "snow_annual_count")


def _sst_anom_annual_cap_reached(
    bot_state: BotState,
    reading_date: str,
    cap: int = SST_ANOM_ANNUAL_CAP,
) -> bool:
    """True if regional SST anomaly drafts hit the cap for the reading year."""
    return _annual_cap_reached_for_year(
        bot_state,
        "sst_anom_annual_count",
        cap,
        reading_date[:4],
    )


__all__ = [
    "CH4_ANNUAL_CAP",
    "CITY_COOLDOWN_DAYS",
    "CO2_ANNUAL_CAP",
    "CORAL_DHW_ANNUAL_CAP",
    "ELITE_COPY_SCORE",
    "ICE_ANNUAL_CAP",
    "MAX_DRAFTS",
    "SNOW_ANNUAL_CAP",
    "SST_ANOM_ANNUAL_CAP",
    "_ch4_annual_cap_reached",
    "_co2_annual_cap_reached",
    "_coral_dhw_annual_cap_reached",
    "_ice_annual_cap_reached",
    "_increment_co2_annual_count",
    "_increment_ice_annual_count",
    "_increment_snow_annual_count",
    "_snow_annual_cap_reached",
    "_sst_anom_annual_cap_reached",
    "annual_cap_reached",
    "increment_annual_count",
]
