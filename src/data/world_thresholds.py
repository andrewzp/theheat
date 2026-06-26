from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MIN_MEAN_SAMPLES = 30  # below this, a monthly mean is too sparse to fire an anomaly


@dataclass
class CityThresholds:
    city: str
    as_of: str
    years_of_data: int
    all_time_max: tuple[float, int] | None = None
    all_time_min: tuple[float, int] | None = None
    monthly_max: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_min: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_mean: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    wetbulb_max: tuple[float, int] | None = None

    def to_dict(self) -> dict:
        return {
            "city": self.city,
            "as_of": self.as_of,
            "years_of_data": self.years_of_data,
            "all_time_max": list(self.all_time_max) if self.all_time_max else None,
            "all_time_min": list(self.all_time_min) if self.all_time_min else None,
            "monthly_max": {k: list(v) for k, v in self.monthly_max.items()},
            "monthly_min": {k: list(v) for k, v in self.monthly_min.items()},
            "monthly_mean": {k: list(v) for k, v in self.monthly_mean.items()},
            "wetbulb_max": list(self.wetbulb_max) if self.wetbulb_max else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityThresholds":
        def pair(v):
            return tuple(v) if v else None

        return cls(
            city=d["city"],
            as_of=d["as_of"],
            years_of_data=int(d.get("years_of_data", 0)),
            all_time_max=pair(d.get("all_time_max")),
            all_time_min=pair(d.get("all_time_min")),
            monthly_max={k: tuple(v) for k, v in (d.get("monthly_max") or {}).items()},
            monthly_min={k: tuple(v) for k, v in (d.get("monthly_min") or {}).items()},
            monthly_mean={k: tuple(v) for k, v in (d.get("monthly_mean") or {}).items()},
            wetbulb_max=pair(d.get("wetbulb_max")),
        )


def compute_city_thresholds(city, archive_daily, *, as_of, years_of_data=30):
    dates = archive_daily.get("time", []) or []
    highs = archive_daily.get("temperature_2m_max", []) or []
    lows = archive_daily.get("temperature_2m_min", []) or []
    tws = archive_daily.get("wet_bulb_temperature_2m_max", []) or []

    at_max = at_min = None
    m_max: dict[str, tuple[float, int]] = {}
    m_min: dict[str, tuple[float, int]] = {}
    hi_sum: dict[str, float] = {}
    lo_sum: dict[str, float] = {}
    hi_n: dict[str, int] = {}
    lo_n: dict[str, int] = {}

    for i, d_str in enumerate(dates):
        try:
            d = date.fromisoformat(d_str)
        except (ValueError, TypeError):
            continue
        mm = f"{d.month:02d}"
        hi = highs[i] if i < len(highs) else None
        lo = lows[i] if i < len(lows) else None
        if hi is not None:
            if at_max is None or hi > at_max[0]:
                at_max = (hi, d.year)
            if mm not in m_max or hi > m_max[mm][0]:
                m_max[mm] = (hi, d.year)
            hi_sum[mm] = hi_sum.get(mm, 0.0) + hi
            hi_n[mm] = hi_n.get(mm, 0) + 1
        if lo is not None:
            if at_min is None or lo < at_min[0]:
                at_min = (lo, d.year)
            if mm not in m_min or lo < m_min[mm][0]:
                m_min[mm] = (lo, d.year)
            lo_sum[mm] = lo_sum.get(mm, 0.0) + lo
            lo_n[mm] = lo_n.get(mm, 0) + 1

    m_mean: dict[str, tuple[float, float, int]] = {}
    for mm in set(hi_n) | set(lo_n):
        h = hi_n.get(mm, 0)
        lo_count = lo_n.get(mm, 0)
        mean_hi = round(hi_sum.get(mm, 0.0) / h, 2) if h else 0.0
        mean_lo = round(lo_sum.get(mm, 0.0) / lo_count, 2) if lo_count else 0.0
        m_mean[mm] = (mean_hi, mean_lo, h)

    wb_max = None
    for i, tw in enumerate(tws):
        if tw is None:
            continue
        try:
            yr = date.fromisoformat(dates[i]).year
        except (ValueError, TypeError, IndexError):
            continue
        if wb_max is None or tw > wb_max[0]:
            wb_max = (tw, yr)

    return CityThresholds(
        city=city, as_of=as_of, years_of_data=years_of_data,
        all_time_max=at_max, all_time_min=at_min,
        monthly_max=m_max, monthly_min=m_min, monthly_mean=m_mean, wetbulb_max=wb_max,
    )


from src.data.open_meteo import (  # noqa: E402
    AllTimeRecord,
    MonthlyRecord,
    AnomalyEvent,
    WetBulbEvent,
    ExtremeSignalBundle,
    WETBULB_TIERS,
    ANOMALY_HOT_THRESHOLD_C,
    ANOMALY_COLD_THRESHOLD_C,
)


def evaluate_city(city, country, forecast, cached, *, lat, lon, today):
    today_max = forecast.get("max_c")
    today_min = forecast.get("min_c")
    tw_max = forecast.get("tw_max_c")
    iso = today.isoformat()
    key = city.replace(" ", "_")
    mm = f"{today.month:02d}"
    yrs = cached.years_of_data

    b = ExtremeSignalBundle(
        city=city, country=country, today_max_c=today_max, today_min_c=today_min,
    )
    if cached.all_time_max is not None:
        b.archive_max_c, b.archive_max_year = cached.all_time_max
    if cached.all_time_min is not None:
        b.archive_min_c, b.archive_min_year = cached.all_time_min

    if today_max is not None and cached.all_time_max is not None and today_max > cached.all_time_max[0]:
        b.all_time_high = AllTimeRecord(
            city=city, country=country, kind="high", new_temp_c=today_max,
            old_record_c=cached.all_time_max[0], old_record_year=cached.all_time_max[1],
            years_of_data=yrs, event_id=f"alltime_high_{key}_{iso}", lat=lat, lon=lon,
        )
    if today_min is not None and cached.all_time_min is not None and today_min < cached.all_time_min[0]:
        b.all_time_low = AllTimeRecord(
            city=city, country=country, kind="low", new_temp_c=today_min,
            old_record_c=cached.all_time_min[0], old_record_year=cached.all_time_min[1],
            years_of_data=yrs, event_id=f"alltime_low_{key}_{iso}", lat=lat, lon=lon,
        )

    mhi = cached.monthly_max.get(mm)
    if today_max is not None and mhi is not None and today_max > mhi[0]:
        b.monthly_high = MonthlyRecord(
            city=city, country=country, kind="high", month=today.month, new_temp_c=today_max,
            old_record_c=mhi[0], old_record_year=mhi[1], years_of_data=yrs,
            event_id=f"monthly_high_{key}_{today.year}_{today.month:02d}", lat=lat, lon=lon,
        )
    mlo = cached.monthly_min.get(mm)
    if today_min is not None and mlo is not None and today_min < mlo[0]:
        b.monthly_low = MonthlyRecord(
            city=city, country=country, kind="low", month=today.month, new_temp_c=today_min,
            old_record_c=mlo[0], old_record_year=mlo[1], years_of_data=yrs,
            event_id=f"monthly_low_{key}_{today.year}_{today.month:02d}", lat=lat, lon=lon,
        )

    mean = cached.monthly_mean.get(mm)
    if today_max is not None and mean is not None and mean[2] >= MIN_MEAN_SAMPLES:
        anom = today_max - mean[0]
        if anom >= ANOMALY_HOT_THRESHOLD_C:
            b.anomaly_hot = AnomalyEvent(
                city=city, country=country, today_temp_c=today_max, historical_mean_c=mean[0],
                anomaly_c=anom, years_of_data=yrs, event_id=f"anomaly_hot_{key}_{iso}", lat=lat, lon=lon,
            )
    if today_min is not None and mean is not None and mean[2] >= MIN_MEAN_SAMPLES:
        anom = today_min - mean[1]
        if anom <= -ANOMALY_COLD_THRESHOLD_C:
            b.anomaly_cold = AnomalyEvent(
                city=city, country=country, today_temp_c=today_min, historical_mean_c=mean[1],
                anomaly_c=anom, years_of_data=yrs, event_id=f"anomaly_cold_{key}_{iso}", lat=lat, lon=lon,
            )

    if tw_max is not None:
        for tier_index, threshold_c, tier_label in WETBULB_TIERS:
            if tw_max < threshold_c:
                continue
            amx = cached.wetbulb_max
            b.wet_bulb_extreme = WetBulbEvent(
                city=city, country=country, daily_max_tw_c=tw_max, tier=tier_index,
                tier_label=tier_label, tier_threshold_c=threshold_c,
                event_id=f"wetbulb_{key}_{iso}_tier{tier_index}", signal_date=today, lat=lat, lon=lon,
                archive_max_tw_c=(amx[0] if amx else None),
                archive_max_year=(amx[1] if amx else None), archive_years=yrs,
            )
            break

    return b
