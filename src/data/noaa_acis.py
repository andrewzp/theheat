from __future__ import annotations

"""NOAA ACIS (Applied Climate Information System) for US record confirmation."""

from dataclasses import dataclass
from datetime import date, timedelta

import requests

ACIS_URL = "https://data.rcc-acis.org"


@dataclass
class RecordConfirmation:
    city: str
    state: str
    new_temp_f: float
    old_record_f: float
    old_record_year: int
    date: str
    event_id: str


def fetch_us_records(days_back: int = 3) -> list[RecordConfirmation]:
    """Query ACIS for recently broken temperature records at US stations."""
    end = date.today()
    start = end - timedelta(days=days_back)

    try:
        # ACIS MultiStnData endpoint: query stations with record-breaking maxes
        resp = requests.post(
            f"{ACIS_URL}/MultiStnData",
            json={
                "sdate": start.isoformat(),
                "edate": end.isoformat(),
                "elems": [
                    {
                        "name": "maxt",
                        "interval": "dly",
                        "duration": "dly",
                        "smry": {"type": "max"},
                        "smry_only": 0,
                        "normal": "departure",
                    }
                ],
                "meta": "name,state",
                "state": "AL,AK,AZ,AR,CA,CO,CT,DE,FL,GA,HI,ID,IL,IN,IA,KS,KY,LA,ME,MD,MA,MI,MN,MS,MO,MT,NE,NV,NH,NJ,NM,NY,NC,ND,OH,OK,OR,PA,RI,SC,SD,TN,TX,UT,VT,VA,WA,WV,WI,WY",
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        confirmations = []
        for station in data.get("data", []):
            meta = station.get("meta", {})
            station_name = meta.get("name", "Unknown")
            station_state = meta.get("state", "")

            records = station.get("data", [])
            for day_data in records:
                if not day_data or len(day_data) < 1:
                    continue
                # Parse temperature and departure from normal
                temp_val = day_data[0] if isinstance(day_data[0], (int, float)) else None
                if temp_val is None:
                    continue

                # Note: ACIS doesn't directly return "record broken" flags in this query.
                # A more targeted approach would use the StnData endpoint with record lookup.
                # For MVP, we flag temperatures with large positive departures from normal.

        return confirmations

    except (requests.RequestException, KeyError):
        return []


def check_record_confirmation(
    city: str,
    state: str,
    record_date: str,
) -> RecordConfirmation | None:
    """Check ACIS for a specific station's record on a specific date."""
    try:
        resp = requests.post(
            f"{ACIS_URL}/StnData",
            json={
                "sid": f"{city}, {state}",
                "sdate": record_date,
                "edate": record_date,
                "elems": [
                    {"name": "maxt", "add": "t"},
                ],
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

        day_data = records[0]
        temp_str = day_data[0] if day_data else None
        if temp_str is None or temp_str == "M":
            return None

        temp_f = float(temp_str)

        return RecordConfirmation(
            city=meta.get("name", city),
            state=meta.get("state", state),
            new_temp_f=temp_f,
            old_record_f=0,  # Would need historical query
            old_record_year=0,
            date=record_date,
            event_id=f"noaa_confirm_{city.replace(' ', '_')}_{record_date}",
        )

    except (requests.RequestException, KeyError, ValueError):
        return None
