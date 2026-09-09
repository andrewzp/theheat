"""Entirely synthetic source bytes for local graphic tests/previews; no old tweets."""
from datetime import date, timedelta

from src.data import ghcn
from src.data.ghcn_format import DailyObs
from src.two_bot.intern import build_all_time_record_bundle, build_monthly_high_bundle, build_record_bundle

STATION = {"station_id": "USC99000001", "name": "GRAPHIC FIXTURE", "country_code": "US",
           "country_name": "Example", "lat": 40.0, "lon": -110.0}
AS_OF = "2026-09-09T12:00:00Z"


def source_archive():
    """A complete source calendar with one missing and one rejected cell per variable."""
    cells = {}
    start, end = date(2001, 1, 1), date(2026, 9, 8)
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        for element, quiet, prior, extreme, sign in (("TMAX", 280, 380, 402, 1), ("TMIN", 50, -100, -202, -1)):
            value = prior if day.year == 2020 and day.month == 9 else quiet
            if day >= date(2026, 9, 3):
                value = extreme + sign * (day - date(2026, 9, 3)).days * 4
            qflag = "S" if day == date(2006, 5, 1) else " "
            if day == date(2005, 4, 1):
                value = -9999
            month = cells.setdefault((day.year, day.month, element), ["-9999   "] * 31)
            month[day.day - 1] = f"{value:5d} {qflag}T"
    return "\n".join(f"{STATION['station_id']}{year:04d}{month:02d}{element}" + "".join(rows)
                     for (year, month, element), rows in sorted(cells.items())).encode("ascii")


def graphic_bundles(*, direction="high", tier="all_time"):
    snapshot = ghcn._archive_snapshot(STATION["station_id"], source_archive(), AS_OF)
    stories = []
    element, sign, value = ("TMAX", 1, 40.2) if direction == "high" else ("TMIN", -1, -20.2)
    for offset in range(6):
        day = date(2026, 9, 3) + timedelta(days=offset)
        observations = [DailyObs(STATION["station_id"], day, element, round(value + sign * offset * 0.4, 1))]
        thresholds, checked = ghcn._thresholds_from_verified_archive(STATION["station_id"], observations, snapshot)
        signals = ghcn._detect_signals_for_station(STATION, checked, thresholds)
        if tier == "all_time":
            event = signals.all_time_high if direction == "high" else signals.all_time_low
            builder = build_all_time_record_bundle
        elif tier == "monthly":
            event = signals.monthly_high if direction == "high" else signals.monthly_low
            builder = build_monthly_high_bundle
        else:
            event = signals.calendar_date_high if direction == "high" else signals.calendar_date_low
            builder = build_record_bundle
        assert event is not None
        stories.append(builder(event, source="ghcn"))
    return stories
