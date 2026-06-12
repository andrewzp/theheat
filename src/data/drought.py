"""US Drought Monitor — weekly drought conditions.

Free REST API, no auth required. Updated every Thursday.
Source: National Drought Mitigation Center
Docs: https://droughtmonitor.unl.edu/DmData/DataDownload/WebServiceInfo.aspx
"""

from dataclasses import dataclass
from datetime import date, timedelta

import requests

from src.data._freshness import assert_freshness, newest_freshness_date
from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

DROUGHT_URL = "https://usdmdataservices.unl.edu/api/StateStatistics/GetDroughtSeverityStatisticsByAreaPercent"


@dataclass
class DroughtUpdate:
    state: str
    d3_pct: float  # Extreme drought %
    d4_pct: float  # Exceptional drought %
    total_drought_pct: float  # D0-D4 combined
    event_id: str


def fetch_drought_data(*, strict: bool = False) -> list[DroughtUpdate]:
    """Fetch current drought conditions by state."""
    # Get data for the most recent Thursday
    today = date.today()
    days_since_thursday = (today.weekday() - 3) % 7
    last_thursday = today - timedelta(days=days_since_thursday)

    try:
        resp = fetch_with_retry(
            DROUGHT_URL,
            params={
                "aoi": "state",
                "startdate": last_thursday.strftime("%m/%d/%Y"),
                "enddate": last_thursday.strftime("%m/%d/%Y"),
                "statisticsType": "2",  # Percent area
            },
            headers={"Accept": "application/json"},
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        data = resp.json()

        updates = []
        release_dates = []
        for entry in data:
            release_dates.append(
                entry.get("MapDate")
                or entry.get("ReleaseDate")
                or entry.get("ValidStart")
                or entry.get("Date")
            )
            state_name = entry.get("Name", "")
            if not state_name or state_name == "Overall":
                continue

            d0 = float(entry.get("D0", 0) or 0)
            d1 = float(entry.get("D1", 0) or 0)
            d2 = float(entry.get("D2", 0) or 0)
            d3 = float(entry.get("D3", 0) or 0)
            d4 = float(entry.get("D4", 0) or 0)
            total = d0 + d1 + d2 + d3 + d4

            # Only include states with significant extreme/exceptional drought
            if d3 + d4 < 10:
                continue

            event_id = f"drought_{state_name.replace(' ', '_')}_{last_thursday.isoformat()}"

            updates.append(DroughtUpdate(
                state=state_name,
                d3_pct=d3,
                d4_pct=d4,
                total_drought_pct=total,
                event_id=event_id,
            ))

        # Sort by worst drought first
        updates.sort(key=lambda u: u.d3_pct + u.d4_pct, reverse=True)

    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"Drought fetch failed: {exc}") from exc
        return []
    newest_date = newest_freshness_date(release_dates) or last_thursday
    assert_freshness(newest_date, "drought", max_age_days=10)
    return updates[:5]  # Top 5 worst states
