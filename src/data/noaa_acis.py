from __future__ import annotations

"""NOAA ACIS (Applied Climate Information System) for US record confirmation."""

from dataclasses import dataclass
from datetime import date, timedelta

import requests

ACIS_URL = "https://data.rcc-acis.org"

# Map US city names to state abbreviations for ACIS lookups.
# ACIS accepts "city, ST" as a station identifier via its name-matching logic.
CITY_STATE_MAP: dict[str, str] = {
    "Anchorage": "AK",
    "Atlanta": "GA",
    "Austin": "TX",
    "Bakersfield": "CA",
    "Barrow": "AK",
    "Boston": "MA",
    "Chicago": "IL",
    "Dallas": "TX",
    "Death Valley": "CA",
    "Denver": "CO",
    "Detroit": "MI",
    "El Paso": "TX",
    "Fairbanks": "AK",
    "Fresno": "CA",
    "Honolulu": "HI",
    "Houston": "TX",
    "Las Vegas": "NV",
    "Los Angeles": "CA",
    "Miami": "FL",
    "Minneapolis": "MN",
    "New Orleans": "LA",
    "New York": "NY",
    "Oklahoma City": "OK",
    "Palm Springs": "CA",
    "Phoenix": "AZ",
    "Portland": "OR",
    "Sacramento": "CA",
    "San Antonio": "TX",
    "San Francisco": "CA",
    "Seattle": "WA",
    "St Louis": "MO",
    "Tampa": "FL",
    "Tucson": "AZ",
    "Washington DC": "VA",
}


@dataclass
class RecordConfirmation:
    city: str
    state: str
    new_temp_f: float
    date: str
    event_id: str


def get_state_code(city: str, state_code: str | None = None) -> str | None:
    """Resolve a state abbreviation for a US city.

    Uses the explicit *state_code* when provided, otherwise falls back to
    the built-in ``CITY_STATE_MAP``.
    """
    if state_code:
        return state_code
    return CITY_STATE_MAP.get(city)


def check_record_confirmation(
    city: str,
    state_code: str | None = None,
    record_date: str | None = None,
) -> RecordConfirmation | None:
    """Check ACIS for official temperature data on *record_date*.

    Args:
        city: US city name (must be present in CITY_STATE_MAP or *state_code*
              must be provided).
        state_code: Two-letter US state abbreviation (e.g. ``"AZ"``).  When
                    ``None`` the code is looked up in ``CITY_STATE_MAP``.
        record_date: ISO-format date string (``"YYYY-MM-DD"``).  Defaults to
                     yesterday if not supplied.

    Returns:
        A ``RecordConfirmation`` when ACIS returns valid temperature data for
        the requested date, indicating the observation is available (i.e. the
        record can be considered confirmed).  ``None`` if the data is missing
        or an error occurs.
    """
    resolved_state = get_state_code(city, state_code)
    if not resolved_state:
        return None

    if record_date is None:
        record_date = (date.today() - timedelta(days=1)).isoformat()

    try:
        # ACIS StnData accepts "city, ST" for its name-matching heuristic.
        resp = requests.post(
            f"{ACIS_URL}/StnData",
            json={
                "sid": f"{city} AP, {resolved_state}",
                "sdate": record_date,
                "edate": record_date,
                "elems": [{"name": "maxt"}],
                "meta": "name,state",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        meta = data.get("meta", {})
        records = data.get("data", [])

        if not records:
            return None

        # records is a list of [date_str, value, ...] rows
        day_data = records[0]
        # day_data looks like ["2026-04-07", "108"] — the temp is the second
        # element when elems has one entry, but ACIS returns date first in
        # StnData responses.  Handle both shapes defensively.
        temp_str = None
        if len(day_data) >= 2:
            temp_str = day_data[1]
        elif len(day_data) == 1:
            temp_str = day_data[0]

        if temp_str is None or temp_str == "M" or temp_str == "T":
            return None

        temp_f = float(temp_str)

        return RecordConfirmation(
            city=meta.get("name", city),
            state=meta.get("state", resolved_state),
            new_temp_f=temp_f,
            date=record_date,
            event_id=f"noaa_confirm_{city.replace(' ', '_')}_{record_date}",
        )

    except (requests.RequestException, KeyError, ValueError, IndexError):
        return None
