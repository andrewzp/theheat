"""Global ocean sea-surface-temperature fetch + marine-heatwave-streak detection.

Primary source: ClimateReanalyzer (University of Maine) JSON endpoint,
which publishes NOAA OISST v2.1 global-mean daily values with the full
1982 → present archive in one payload.

The streak count is derived from the payload itself on every run (walking
backward from today's day-of-year), not accumulated in our state. This
keeps the "Nth consecutive day" claim factually defensible regardless of
cron outages on our side.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import requests

SST_URL = (
    "https://climatereanalyzer.org/clim/sst_daily/json/"
    "oisst2.1_world_sst_day.json"
)

# Fire on the first day of a confirmed streak (day 5, per Hobday et al.
# 2016 MHW definition), then at each of these milestone day-counts.
# Past 400: every +50 (see _milestones_up_to).
MILESTONES: tuple[int, ...] = (5, 10, 25, 50, 100, 150, 200, 250, 300, 365, 400)


@dataclass(frozen=True)
class GlobalSSTObservation:
    date: str
    day_of_year: int
    today_c: float
    archive_max_c: float
    archive_max_year: int
    years_of_data: int
    streak_days: int
    streak_start_date: str | None
    streak_peak_anomaly_c: float


@dataclass(frozen=True)
class MarineHeatwaveStreakEvent:
    kind: str  # "first" | "milestone"
    days: int
    peak_anomaly_c: float
    today_c: float
    archive_max_c: float
    archive_max_year: int
    years_of_data: int
    date: str
    event_id: str


def _milestones_up_to(days: int) -> tuple[int, ...]:
    """Return all milestone thresholds <= days, ascending.

    Base ladder is MILESTONES (5, 10, 25, 50, 100, 150, 200, 250, 300,
    365, 400); after 400 the ladder continues every +50 (450, 500, ...).
    """
    below_or_equal = tuple(m for m in MILESTONES if m <= days)
    if days <= 400:
        return below_or_equal
    extra = tuple(range(450, days + 1, 50))
    return below_or_equal + extra


def fetch_global_sst() -> GlobalSSTObservation | None:
    raise NotImplementedError  # implemented in Task 3


def detect_streak_milestone(
    obs: GlobalSSTObservation,
    prior: dict,
) -> tuple[dict, MarineHeatwaveStreakEvent | None]:
    raise NotImplementedError  # implemented in Task 4
