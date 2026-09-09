from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
import json

from src.data import places
from src.data.temperature_evidence import (
    ARCHIVE_MODEL,
    ARCHIVE_PRODUCT,
    attach_evidence,
    finite,
    fingerprint,
)
from src.data.open_meteo import (
    AllTimeRecord,
    MonthlyRecord,
    RecordEvent,
    AnomalyEvent,
    WetBulbEvent,
    ExtremeSignalBundle,
    WETBULB_TIERS,
    ANOMALY_HOT_THRESHOLD_C,
    ANOMALY_COLD_THRESHOLD_C,
)

MIN_MEAN_SAMPLES = 30


@dataclass
class CityThresholds:
    city: str
    as_of: str
    years_of_data: int
    all_time_max: tuple[float, int] | None = None
    all_time_min: tuple[float, int] | None = None
    monthly_max: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_min: dict[str, tuple[float, int]] = field(default_factory=dict)
    monthly_mean: dict = field(default_factory=dict)
    wetbulb_max: tuple[float, int] | None = None
    identity: dict = field(default_factory=dict)
    baseline: dict = field(default_factory=dict)
    calendar_max: dict = field(default_factory=dict)
    calendar_min: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), allow_nan=False))

    @classmethod
    def from_dict(cls, value: dict) -> "CityThresholds":
        data = {key: value[key] for key in cls.__dataclass_fields__ if key in value}
        for key in ("all_time_max", "all_time_min", "wetbulb_max"):
            if data.get(key):
                data[key] = tuple(data[key])
        for key in ("monthly_max", "monthly_min", "monthly_mean", "calendar_max", "calendar_min"):
            data[key] = {k: tuple(v) for k, v in (data.get(key) or {}).items()}
        return cls(**data)


def compute_city_thresholds(
    city, archive_daily, *, as_of, years_of_data=30, country="", lat=None, lon=None
):
    """One immutable ERA5 archive snapshot, with independent variable coverage.

    Requested years describe the query, never the number of complete observed
    years. Dates and finite values determine accepted sample counts and cutoffs.
    Production callers supply _provenance from the qualified archive response.
    """
    source = archive_daily.get("_provenance") or {}
    requested_end = date.fromisoformat(source.get("requested_end") or as_of) - (
        timedelta(days=0) if source.get("requested_end") else timedelta(days=1)
    )
    try:
        requested_start = date.fromisoformat(
            source.get("requested_start")
            or requested_end.replace(year=requested_end.year - years_of_data).isoformat()
        )
    except ValueError:
        requested_start = requested_end.replace(year=requested_end.year - years_of_data, day=28)
    variables = {}
    series = {}
    monthly = {}
    calendars = {}
    for variable, is_max in (
        ("temperature_2m_max", True),
        ("temperature_2m_min", False),
        ("wet_bulb_temperature_2m_max", True),
    ):
        values = archive_daily.get(variable) or []
        by_date = {}
        conflicts = set()
        for index, label in enumerate(archive_daily.get("time") or []):
            try:
                day = date.fromisoformat(label)
            except (TypeError, ValueError):
                continue
            value = values[index] if index < len(values) else None
            if not requested_start <= day <= requested_end or not finite(value):
                continue
            if label in by_date and by_date[label] != value:
                conflicts.add(label)
            by_date[label] = float(value)
        for label in conflicts:
            by_date.pop(label, None)
        series[variable] = by_date
        month_values, calendar_values = {}, {}
        for label, value in sorted(by_date.items()):
            day = date.fromisoformat(label)
            month_values.setdefault(f"{day.month:02d}", []).append((value, day.year, label))
            calendar_values.setdefault(label[5:], []).append((value, day.year, label))
        choose = max if is_max else min
        monthly[variable] = {
            key: choose(rows, key=lambda row: row[0]) for key, rows in month_values.items()
        }
        calendars[variable] = {
            key: choose(rows, key=lambda row: row[0]) for key, rows in calendar_values.items()
        }
        expected = (requested_end - requested_start).days + 1
        variables[variable] = {
            "sample_count": len(by_date),
            "expected_count": expected,
            "coverage_fraction": len(by_date) / expected if expected > 0 else 0,
            "complete": expected > 0 and len(by_date) == expected,
            "start": min(by_date) if by_date else None,
            "cutoff": max(by_date) if by_date else None,
            "years_with_samples": len({label[:4] for label in by_date}),
            "monthly_samples": {key: len(rows) for key, rows in month_values.items()},
            "monthly_mean": {
                key: sum(row[0] for row in rows) / len(rows) for key, rows in month_values.items()
            },
            "conflicting_dates": sorted(conflicts),
        }

    def extreme(variable, choose):
        rows = series[variable]
        if not rows:
            return None
        label = choose(rows, key=rows.get)
        return rows[label], int(label[:4])

    hi, lo = variables["temperature_2m_max"], variables["temperature_2m_min"]
    means = {
        mm: (
            hi["monthly_mean"].get(mm),
            lo["monthly_mean"].get(mm),
            hi["monthly_samples"].get(mm, 0),
            lo["monthly_samples"].get(mm, 0),
        )
        for mm in set(hi["monthly_mean"]) | set(lo["monthly_mean"])
    }
    identity = (
        {**places.resolve_place(city, country, lat, lon), "source_product": ARCHIVE_PRODUCT}
        if country
        else {}
    )
    baseline = {
        "schema_version": 2,
        "source_product": ARCHIVE_PRODUCT,
        "evidence_type": "reanalysis",
        "model": ARCHIVE_MODEL,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "requested_years": years_of_data,
        "variables": variables,
        "retrieved_at": source.get("retrieved_at") or as_of + "T00:00:00Z",
        "timezone": source.get("timezone"),
        "utc_offset_seconds": source.get("utc_offset_seconds"),
        "spatial_scope": "ERA5 grid point",
        "provider_grid": source.get("provider_grid"),
        "provider_units": source.get("provider_units"),
        "comparison_scope": "available_reanalysis_samples",
        "source_payload_sha256": fingerprint(series),
    }
    baseline["revision_id"] = fingerprint(
        {"identity": identity, **{k: v for k, v in baseline.items() if k != "retrieved_at"}}
    )

    def pairs(name):
        return {key: (row[0], row[1]) for key, row in monthly[name].items()}

    def cal_pairs(name):
        return {key: (row[0], row[1]) for key, row in calendars[name].items()}

    return CityThresholds(
        city=city,
        as_of=as_of,
        years_of_data=min(years_of_data, max(hi["years_with_samples"], lo["years_with_samples"])),
        identity=identity,
        baseline=baseline,
        all_time_max=extreme("temperature_2m_max", max),
        all_time_min=extreme("temperature_2m_min", min),
        monthly_max=pairs("temperature_2m_max"),
        monthly_min=pairs("temperature_2m_min"),
        monthly_mean=means,
        calendar_max=cal_pairs("temperature_2m_max"),
        calendar_min=cal_pairs("temperature_2m_min"),
        wetbulb_max=extreme("wet_bulb_temperature_2m_max", max),
    )


def record_comparison_qualification(baseline: dict, valid_date: date, variable: str) -> tuple[bool, str]:
    """Require complete source coverage through the latest requested ERA5 day.

    ERA5's recent five-day availability delay remains an explicit gap; forecasts
    are compared only with this dated reanalysis interval, never an observed record.
    """
    row = baseline.get("variables", {}).get(variable, {})
    required_cutoff = (valid_date - timedelta(days=5)).isoformat()
    if not row.get("complete"):
        return False, "incomplete_variable_archive"
    if not row.get("cutoff") or row["cutoff"] < required_cutoff:
        return False, "unreconciled_archive_cutoff"
    if row["cutoff"] >= valid_date.isoformat():
        return False, "archive_overlaps_valid_date"
    return True, "complete_reanalysis_through_declared_cutoff"


def potential_record_variables(forecast: dict, cached: dict) -> set[str]:
    """Prioritize bounded source refreshes; this check cannot authorize a claim."""
    day = date.fromisoformat(forecast["valid_date"])
    found = set()
    for variable, value, field, monthly, high in (
        ("temperature_2m_max", forecast.get("max_c"), "all_time_max", "monthly_max", True),
        ("temperature_2m_min", forecast.get("min_c"), "all_time_min", "monthly_min", False),
    ):
        for prior in (cached.get(field), cached.get(monthly, {}).get(f"{day.month:02d}")):
            if finite(value) and prior and (value > prior[0] if high else value < prior[0]):
                found.add(variable)
    wet_prior = cached.get("wetbulb_max")
    if finite(forecast.get("tw_max_c")) and wet_prior and forecast["tw_max_c"] > wet_prior[0]:
        found.add("wet_bulb_temperature_2m_max")
    return found


def evaluate_city(city, country, forecast, cached, *, lat, lon, today=None, include_calendar=False):
    from src.data.place_migration import valid_cache_entry

    if not valid_cache_entry(places.cache_key(city, country, lat, lon), cached.to_dict()):
        raise ValueError("Threshold cache lacks matching sampling provenance; recompute it")
    try:
        valid_date = date.fromisoformat(forecast["valid_date"])
        evidence = forecast["evidence"]
        if (
            evidence["evidence_type"] != "forecast"
            or evidence["valid_date"] != valid_date.isoformat()
        ):
            raise ValueError("Conflicting forecast date/type")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Forecast lacks provider valid date/evidence") from exc
    today = valid_date
    variables = cached.baseline.get("variables") or {}
    if cached.baseline.get("schema_version") != 2:
        raise ValueError("Threshold lacks qualified baseline revision; recompute it")
    if any(row.get("cutoff") and row["cutoff"] >= today.isoformat() for row in variables.values()):
        raise ValueError("Baseline includes the comparison date or future data")
    today_max = forecast.get("max_c")
    today_min = forecast.get("min_c")
    tw_max = forecast.get("tw_max_c")
    iso = today.isoformat()
    # Include country so genuinely-distinct same-name cities (e.g. Barcelona ES vs VE)
    # get distinct event_ids and dedup doesn't suppress the second city's real record.
    key = places.event_location_key(city, country, lat, lon)
    mm = f"{today.month:02d}"
    high_years = min(cached.baseline["requested_years"], variables["temperature_2m_max"]["years_with_samples"])
    low_years = min(cached.baseline["requested_years"], variables["temperature_2m_min"]["years_with_samples"])
    high_ok, high_reason = record_comparison_qualification(cached.baseline, today, "temperature_2m_max")
    low_ok, low_reason = record_comparison_qualification(cached.baseline, today, "temperature_2m_min")
    wet_ok, wet_reason = record_comparison_qualification(cached.baseline, today, "wet_bulb_temperature_2m_max")
    comparison = {
        "withheld_record_variables": {variable: record_comparison_qualification(cached.baseline, today, variable)[1]
            for variable in potential_record_variables(forecast, cached.to_dict())
            if not record_comparison_qualification(cached.baseline, today, variable)[0]},
        "high": {"eligible": high_ok, "reason": high_reason},
        "low": {"eligible": low_ok, "reason": low_reason},
        "wet_bulb": {"eligible": wet_ok, "reason": wet_reason},
        "required_archive_cutoff": (today - timedelta(days=5)).isoformat(),
        "scope": "forecast_vs_complete_ERA5_interval_through_declared_cutoff",
        "recent_data_gap": "ERA5 availability lag: intervening days after the cutoff are unverified; this is not an observed record",
    }

    b = ExtremeSignalBundle(
        city=city,
        country=country,
        today_max_c=today_max,
        today_min_c=today_min,
        lat=lat,
        lon=lon,
        signal_date=today,
    )
    if high_ok and cached.all_time_max is not None:
        b.archive_max_c, b.archive_max_year = cached.all_time_max
    if low_ok and cached.all_time_min is not None:
        b.archive_min_c, b.archive_min_year = cached.all_time_min

    if (
        high_ok and today_max is not None
        and cached.all_time_max is not None
        and today_max > cached.all_time_max[0]
    ):
        b.all_time_high = AllTimeRecord(
            city=city,
            country=country,
            kind="high",
            new_temp_c=today_max,
            old_record_c=cached.all_time_max[0],
            old_record_year=cached.all_time_max[1],
            years_of_data=high_years,
            event_id=f"alltime_high_{key}_{iso}",
            lat=lat,
            lon=lon,
        )
    if (
        low_ok and today_min is not None
        and cached.all_time_min is not None
        and today_min < cached.all_time_min[0]
    ):
        b.all_time_low = AllTimeRecord(
            city=city,
            country=country,
            kind="low",
            new_temp_c=today_min,
            old_record_c=cached.all_time_min[0],
            old_record_year=cached.all_time_min[1],
            years_of_data=low_years,
            event_id=f"alltime_low_{key}_{iso}",
            lat=lat,
            lon=lon,
        )

    mhi = cached.monthly_max.get(mm)
    if high_ok and today_max is not None and mhi is not None and today_max > mhi[0]:
        b.monthly_high = MonthlyRecord(
            city=city,
            country=country,
            kind="high",
            month=today.month,
            new_temp_c=today_max,
            old_record_c=mhi[0],
            old_record_year=mhi[1],
            years_of_data=high_years,
            event_id=f"monthly_high_{key}_{today.year}_{today.month:02d}",
            lat=lat,
            lon=lon,
        )
    mlo = cached.monthly_min.get(mm)
    if low_ok and today_min is not None and mlo is not None and today_min < mlo[0]:
        b.monthly_low = MonthlyRecord(
            city=city,
            country=country,
            kind="low",
            month=today.month,
            new_temp_c=today_min,
            old_record_c=mlo[0],
            old_record_year=mlo[1],
            years_of_data=low_years,
            event_id=f"monthly_low_{key}_{today.year}_{today.month:02d}",
            lat=lat,
            lon=lon,
        )

    mean = cached.monthly_mean.get(mm)
    if (
        today_max is not None
        and mean is not None
        and mean[0] is not None
        and mean[2] >= MIN_MEAN_SAMPLES
    ):
        anom = today_max - mean[0]
        if anom >= ANOMALY_HOT_THRESHOLD_C:
            b.anomaly_hot = AnomalyEvent(
                city=city,
                country=country,
                today_temp_c=today_max,
                historical_mean_c=mean[0],
                anomaly_c=anom,
                years_of_data=high_years,
                event_id=f"anomaly_hot_{key}_{iso}",
                lat=lat,
                lon=lon,
            )
    if (
        today_min is not None
        and mean is not None
        and mean[1] is not None
        and len(mean) > 3
        and mean[3] >= MIN_MEAN_SAMPLES
    ):
        anom = today_min - mean[1]
        if anom <= -ANOMALY_COLD_THRESHOLD_C:
            b.anomaly_cold = AnomalyEvent(
                city=city,
                country=country,
                today_temp_c=today_min,
                historical_mean_c=mean[1],
                anomaly_c=anom,
                years_of_data=low_years,
                event_id=f"anomaly_cold_{key}_{iso}",
                lat=lat,
                lon=lon,
            )

    if tw_max is not None:
        for tier_index, threshold_c, tier_label in WETBULB_TIERS:
            if tw_max < threshold_c:
                continue
            amx = cached.wetbulb_max if wet_ok else None
            b.wet_bulb_extreme = WetBulbEvent(
                city=city,
                country=country,
                daily_max_tw_c=tw_max,
                tier=tier_index,
                tier_label=tier_label,
                tier_threshold_c=threshold_c,
                event_id=f"wetbulb_{key}_{iso}_tier{tier_index}",
                signal_date=today,
                lat=lat,
                lon=lon,
                archive_max_tw_c=(amx[0] if amx else None),
                archive_max_year=(amx[1] if amx else None),
                archive_years=min(cached.baseline["requested_years"], variables["wet_bulb_temperature_2m_max"]["years_with_samples"]) if wet_ok else None,
            )
            break

    if include_calendar:
        for kind, value, thresholds in (
            ("high", today_max, cached.calendar_max),
            ("low", today_min, cached.calendar_min),
        ):
            prior = thresholds.get(today.strftime("%m-%d"))
            if (
                (high_ok if kind == "high" else low_ok)
                and value is not None
                and prior
                and (value > prior[0] if kind == "high" else value < prior[0])
            ):
                setattr(
                    b,
                    "calendar_date_" + kind,
                    RecordEvent(
                        city,
                        country,
                        value,
                        prior[0],
                        prior[1],
                        ("record_" if kind == "high" else "record_low_") + key + "_" + iso,
                        kind=kind,
                        signal_date=today,
                        lat=lat,
                        lon=lon,
                    ),
                )
    attach_evidence(b, {**evidence, "requested_sampling_point": {"latitude": lat, "longitude": lon}, "baseline": cached.baseline, "comparison": comparison})
    return b
