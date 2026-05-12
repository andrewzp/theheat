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

from src.data.source_status import SourceFetchError

SST_URL = (
    "https://climatereanalyzer.org/clim/sst_daily/json/"
    "oisst2.1_world_sst_day.json"
)

# ClimateReanalyzer.org redirects requests without a User-Agent header
# into an infinite loop ("Exceeded 30 redirects" — observed all day
# 2026-05-12 in production). Sending any non-default UA breaks the loop
# and returns the JSON cleanly. Match the convention from nws_alerts.py.
_REQUEST_HEADERS = {"User-Agent": "(theheat-bot, contact@theheat.app)"}

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


def _today_year_doy() -> tuple[int, int]:
    """Return (current_year, today_day_of_year). Wrapped for test injection."""
    today = date.today()
    return today.year, today.timetuple().tm_yday


def _valid_sst(v: object) -> bool:
    """Accept realistic global-mean SST values in Celsius."""
    return isinstance(v, (int, float)) and -2.0 <= v <= 40.0


def _date_from_doy(year: int, doy: int) -> str:
    return (date(year, 1, 1) + timedelta(days=doy - 1)).isoformat()


def _archive_max_for_doy(prior_years_arrs: dict[int, list], doy: int) -> tuple[float, int] | None:
    """Return (max_value, year) across prior years for a given day-of-year index.

    Returns None if no prior year has a valid value for that day.
    """
    best: tuple[float, int] | None = None
    for year, arr in prior_years_arrs.items():
        idx = doy - 1
        if idx < 0 or idx >= len(arr):
            continue
        v = arr[idx]
        if not _valid_sst(v):
            continue
        if best is None or v > best[0]:
            best = (float(v), year)
    return best


def _walk_streak_backward(
    current_year: int,
    today_doy: int,
    current_arr: list,
    prior_arrs: dict[int, list],
) -> tuple[int, int | None, int | None, float]:
    """Walk backward from today_doy to compute the streak.

    Returns (streak_days, streak_start_year, streak_start_doy, peak_anomaly).
    If the streak reaches doy 1 of current_year, continues into current_year-1.

    Limitation: only crosses one calendar year boundary. A streak exceeding
    365 continuous days (e.g., from Dec into a full current year) would
    underreport once the prior-year array is exhausted. Milestones past day
    365 are theoretically reachable; treat as a known constraint for future
    hardening if such streaks occur.
    """
    streak_days = 0
    streak_start_year: int | None = None
    streak_start_doy: int | None = None
    peak = 0.0

    def _step(year: int, doy: int, arr: list, pa: dict[int, list]) -> bool:
        nonlocal streak_days, streak_start_year, streak_start_doy, peak
        idx = doy - 1
        if idx < 0 or idx >= len(arr):
            return False
        v = arr[idx]
        if not _valid_sst(v):
            return False
        amax = _archive_max_for_doy(pa, doy)
        if amax is None:
            return False
        if v > amax[0]:
            streak_days += 1
            streak_start_year = year
            streak_start_doy = doy
            peak = max(peak, float(v) - amax[0])
            return True
        return False

    # Walk current year first.
    for doy in range(today_doy, 0, -1):
        if not _step(current_year, doy, current_arr, prior_arrs):
            return streak_days, streak_start_year, streak_start_doy, peak

    # Streak reached Jan 1 of current_year — continue into prior calendar year.
    prev_year = current_year - 1
    prev_arr = prior_arrs.get(prev_year)
    if prev_arr is None:
        return streak_days, streak_start_year, streak_start_doy, peak
    # For the archive comparison when walking the prior calendar year, the
    # "prior years" set excludes that year itself.
    deeper_priors = {y: a for y, a in prior_arrs.items() if y != prev_year}
    for doy in range(len(prev_arr), 0, -1):
        if not _step(prev_year, doy, prev_arr, deeper_priors):
            return streak_days, streak_start_year, streak_start_doy, peak

    return streak_days, streak_start_year, streak_start_doy, peak


def fetch_global_sst(*, strict: bool = False) -> GlobalSSTObservation | None:
    """Fetch global-mean SST from ClimateReanalyzer and derive the current streak.

    Returns None on any fetch/validation failure unless ``strict=True``.
    """
    try:
        resp = requests.get(SST_URL, timeout=15, headers=_REQUEST_HEADERS)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        if strict:
            raise SourceFetchError(f"Ocean SST fetch failed: {exc}") from exc
        return None

    if not isinstance(payload, dict):
        if strict:
            raise SourceFetchError("Ocean SST fetch failed: response was not a JSON object")
        return None

    current_year, today_doy = _today_year_doy()
    cur_arr = payload.get(str(current_year))
    if not isinstance(cur_arr, list) or not cur_arr:
        if strict:
            raise SourceFetchError(f"Ocean SST fetch failed: missing {current_year} data")
        return None

    # Find most recent non-null index at or before today_doy.
    today_idx = None
    for idx in range(min(today_doy, len(cur_arr)) - 1, -1, -1):
        if _valid_sst(cur_arr[idx]):
            today_idx = idx
            break
    if today_idx is None:
        if strict:
            raise SourceFetchError("Ocean SST fetch failed: no current-year valid readings")
        return None
    today_doy = today_idx + 1
    today_c = float(cur_arr[today_idx])

    prior_arrs: dict[int, list] = {}
    for key, val in payload.items():
        try:
            y = int(key)
        except (TypeError, ValueError):
            continue
        if y >= current_year or y < 1982:
            continue
        if isinstance(val, list):
            prior_arrs[y] = val

    if not prior_arrs:
        if strict:
            raise SourceFetchError("Ocean SST fetch failed: missing prior-year archive")
        return None

    if len(prior_arrs) < 30:
        if strict:
            raise SourceFetchError("Ocean SST fetch failed: archive shorter than 30 years")
        return None

    amax = _archive_max_for_doy(prior_arrs, today_doy)
    if amax is None:
        if strict:
            raise SourceFetchError("Ocean SST fetch failed: no archive max for current day")
        return None
    archive_max_c, archive_max_year = amax

    streak_days, streak_start_year, streak_start_doy, peak = _walk_streak_backward(
        current_year, today_doy, cur_arr, prior_arrs,
    )
    streak_start_date = (
        _date_from_doy(streak_start_year, streak_start_doy)
        if streak_start_year and streak_start_doy
        else None
    )

    return GlobalSSTObservation(
        date=_date_from_doy(current_year, today_doy),
        day_of_year=today_doy,
        today_c=today_c,
        archive_max_c=archive_max_c,
        archive_max_year=archive_max_year,
        years_of_data=current_year - 1982,  # formula-based; OISST is a continuous series
        streak_days=streak_days,
        streak_start_date=streak_start_date,
        streak_peak_anomaly_c=peak,
    )


def detect_streak_milestone(
    obs: GlobalSSTObservation,
    prior: dict,
) -> tuple[dict, MarineHeatwaveStreakEvent | None]:
    """Decide whether an observation should fire a milestone tweet.

    Returns (new_state, event_or_none). new_state is always the full
    two-field dict the caller should persist via update_ocean_sst_streak.
    """
    seeded = bool(prior.get("seeded", False))
    last_fired = prior.get("last_milestone_fired")

    # 1. First-ever observation — silent seed.
    if not seeded:
        return ({"seeded": True, "last_milestone_fired": None}, None)

    # 2. Streak broken — clear the fired-marker, no event.
    if obs.streak_days <= 0:
        return ({"seeded": True, "last_milestone_fired": None}, None)

    # 3. Below first-fire threshold (day 5).
    if obs.streak_days < 5:
        # Fresh sub-threshold streak after a break should carry last_fired=None,
        # which the streak-broken branch above will have already done.
        return (
            {"seeded": True, "last_milestone_fired": last_fired},
            None,
        )

    # 4. Find the largest milestone not yet fired this streak.
    already = last_fired if last_fired is not None else 0
    candidates = [m for m in _milestones_up_to(obs.streak_days) if m > already]
    if not candidates:
        return (
            {"seeded": True, "last_milestone_fired": last_fired},
            None,
        )
    crossed = max(candidates)

    event = MarineHeatwaveStreakEvent(
        kind="first" if crossed == 5 and already == 0 else "milestone",
        days=crossed,
        peak_anomaly_c=obs.streak_peak_anomaly_c,
        today_c=obs.today_c,
        archive_max_c=obs.archive_max_c,
        archive_max_year=obs.archive_max_year,
        years_of_data=obs.years_of_data,
        date=obs.date,
        event_id=f"marine_heatwave_streak_{crossed}_{obs.date}",
    )
    return ({"seeded": True, "last_milestone_fired": crossed}, event)
