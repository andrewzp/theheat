"""Explicit provider/snapshot metadata for synthetic temperature regression fixtures."""
from copy import deepcopy
from datetime import date, timedelta
from src.data.temperature_evidence import forecast_day, fingerprint


def provider_payload(value, valid_date=None, timezone="UTC", offset=0):
    value = deepcopy(value)
    if isinstance(value, list):
        return [provider_payload(row, valid_date, timezone, offset) for row in value]
    if isinstance(value, dict) and isinstance(value.get("daily"), dict):
        value["daily"].setdefault("time", [valid_date or date.today().isoformat()])
        value.setdefault("timezone", timezone)
        value.setdefault("utc_offset_seconds", offset)
    return value


def dated_forecast(value, valid_date="2026-06-26"):
    return forecast_day(provider_payload({"daily": {
        "temperature_2m_max": [value.get("max_c")],
        "temperature_2m_min": [value.get("min_c")],
        "wet_bulb_temperature_2m_max": [value.get("tw_max_c")],
    }}, valid_date), retrieved_at=valid_date + "T12:00:00Z")


def snapshot(row):
    """A synthetic source-qualified fixture, not a migration of production data."""
    row = deepcopy(row)
    day = row.get("as_of") or "2026-06-01"
    cutoff = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    row.setdefault("years_of_data", 30)
    row["monthly_mean"] = {mm: list(value) + ([value[2]] if len(value) == 3 else []) for mm, value in row.get("monthly_mean", {}).items()}
    row["baseline"] = {
        "schema_version": 2, "source_product": "openmeteo-era5-daily-v2", "model": "era5", "evidence_type": "reanalysis",
        "retrieved_at": day + "T00:00:00Z", "requested_years": row["years_of_data"], "requested_start": "1996-01-01", "requested_end": cutoff,
        "variables": {variable: {"sample_count": (date.fromisoformat(cutoff) - date(1996, 1, 1)).days + 1, "expected_count": (date.fromisoformat(cutoff) - date(1996, 1, 1)).days + 1, "complete": True, "cutoff": cutoff, "years_with_samples": row["years_of_data"]}
                      for variable in ("temperature_2m_max", "temperature_2m_min", "wet_bulb_temperature_2m_max")},
    }
    row["baseline"]["revision_id"] = fingerprint(row)
    return row


def complete_archive(rows, valid_date=None, years=30):
    """Synthetic complete daily interval; preserve supplied extrema, fill quiet days."""
    valid = date.fromisoformat(valid_date or date.today().isoformat())
    end = valid - timedelta(days=5)
    try:
        start = valid.replace(year=valid.year - years)
    except ValueError:
        start = valid.replace(year=valid.year - years, day=28)
    dates = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    out = {"time": dates, "_provenance": {"requested_start": start.isoformat(), "requested_end": end.isoformat(), "retrieved_at": valid.isoformat() + "T00:00:00Z", "timezone": "UTC", "utc_offset_seconds": 0}}
    for variable, quiet in (("temperature_2m_max", 20), ("temperature_2m_min", 20), ("wet_bulb_temperature_2m_max", 10)):
        if variable not in rows:
            continue
        known = dict(zip(rows.get("time", []), rows[variable]))
        out[variable] = [known.get(day, quiet) for day in dates]
    return out
