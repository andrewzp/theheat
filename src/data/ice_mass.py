"""NASA GRACE-FO ice mass anomaly — Greenland + Antarctica.

Level-4 mascon time series from JPL, served via PO.DAAC. Monthly cadence
with a 1-2 month publication lag. Requires Earthdata Login — set
`EARTHDATA_TOKEN` to a user-generated app token from
https://urs.earthdata.nasa.gov/. The user account must also authorize
the PO.DAAC Cumulus OPS application in URS (Approve Applications page),
otherwise archive.podaac.earthdata.nasa.gov returns 401.

Records start 2002.

PO.DAAC migrated these products from podaac-tools.jpl.nasa.gov/drive
(decommissioned 2024-2025) to archive.podaac.earthdata.nasa.gov in
Earthdata Cloud. The granule filename now embeds the data range
(e.g. greenland_mass_200204_202603.txt), so the bot resolves the
current granule URL via NASA CMR before each fetch rather than
hardcoding.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError, SourceSkipped

# CMR collection short_names for the two TIME_SERIES products. CMR maps these
# to the latest granule's download URL on archive.podaac.earthdata.nasa.gov.
GREENLAND_CMR_SHORT_NAME = "GREENLAND_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4"
ANTARCTICA_CMR_SHORT_NAME = "ANTARCTICA_MASS_TELLUS_MASCON_CRI_TIME_SERIES_RL06.3_V4"

REGION_CMR_SHORT_NAMES = {
    "greenland": GREENLAND_CMR_SHORT_NAME,
    "antarctica": ANTARCTICA_CMR_SHORT_NAME,
}

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"

GRACE_START_YEAR = 2002
MILESTONE_STEP_GT = 1000.0


def _decimal_year_to_month(decimal_year: float) -> str:
    year = int(math.floor(decimal_year))
    frac = decimal_year - year
    month_idx = int(frac * 12)
    if month_idx < 0:
        month_idx = 0
    if month_idx > 11:
        month_idx = 11
    return f"{year}-{month_idx + 1:02d}"


@dataclass
class IceMassReading:
    region: str
    month: str             # "YYYY-MM"
    mass_gt: float         # mass anomaly vs mission baseline (negative = below)
    uncertainty_gt: float
    event_id: str


@dataclass
class IceMassRecord:
    region: str
    kind: str              # "monthly_loss_record" | "cumulative_milestone"
    month: str | None
    monthly_delta_gt: float | None
    previous_worst_gt: float | None
    previous_worst_month: str | None
    threshold_gt: float | None
    current_mass_gt: float | None
    event_id: str


def _resolve_latest_url(short_name: str) -> str | None:
    """Return the most recent granule's HTTPS download URL from CMR.

    Queries `https://cmr.earthdata.nasa.gov/search/granules.json` for the
    given collection sorted by start_date DESC and picks the first
    granule's `.txt` link on `archive.podaac.earthdata.nasa.gov`. Returns
    None on any failure so the caller can treat the lane as skipped.
    """
    try:
        resp = fetch_with_retry(
            CMR_GRANULES_URL,
            params={
                "short_name": short_name,
                "page_size": 1,
                "sort_key": "-start_date",
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
    except requests.RequestException as exc:
        print(f"[ice_mass] CMR query failed for {short_name}: {exc}")
        return None

    try:
        entries = resp.json().get("feed", {}).get("entry", [])
    except ValueError as exc:
        print(f"[ice_mass] CMR JSON parse failed for {short_name}: {exc}")
        return None
    if not entries:
        return None

    for link in entries[0].get("links", []):
        href = link.get("href", "")
        if (
            href.startswith("https://archive.podaac.earthdata.nasa.gov/")
            and href.endswith(".txt")
            and "cumulus-protected" in href
        ):
            return href
    return None


def fetch_grace_mass(region: str, *, strict: bool = False) -> list[IceMassReading]:
    """Fetch the PODAAC Level-4 mass anomaly time series for a region.

    Returns readings sorted oldest → newest. Returns [] on any failure
    (missing token, CMR lookup failure, HTTP error, parse error) so
    callers can treat the lane as skipped rather than crashing.
    """
    if region not in REGION_CMR_SHORT_NAMES:
        if strict:
            raise SourceSkipped(f"Unknown ice-mass region: {region}")
        return []

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("[ice_mass] EARTHDATA_TOKEN not configured — skipping")
        if strict:
            raise SourceSkipped("EARTHDATA_TOKEN is not configured")
        return []

    url = _resolve_latest_url(REGION_CMR_SHORT_NAMES[region])
    if not url:
        msg = f"CMR returned no granule URL for {region}"
        print(f"[ice_mass] {msg}")
        if strict:
            raise SourceFetchError(f"Ice mass fetch failed for {region}: {msg}")
        return []

    try:
        # Routed through fetch_with_retry so the observed PO.DAAC 502s retry
        # with backoff instead of dropping the region on a single blip.
        resp = fetch_with_retry(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"[ice_mass] {region} fetch error: {e}")
        if strict:
            raise SourceFetchError(f"Ice mass fetch failed for {region}: {e}") from e
        return []

    readings: list[IceMassReading] = []
    for line in resp.text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("HDR") or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        try:
            decimal_year = float(parts[0])
            mass_gt = float(parts[1])
            uncertainty_gt = float(parts[2])
        except ValueError:
            continue
        month = _decimal_year_to_month(decimal_year)
        readings.append(IceMassReading(
            region=region,
            month=month,
            mass_gt=mass_gt,
            uncertainty_gt=uncertainty_gt,
            event_id=f"ice_mass_{region}_{month}",
        ))
    readings.sort(key=lambda r: r.month)
    if strict and not readings:
        raise SourceFetchError(f"Ice mass fetch failed for {region}: no valid readings")
    return readings


def detect_monthly_record(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    """Fire when the latest month-over-month mass delta beats the stored record.

    `state["ice_mass_max_loss"][region]` holds the worst (most-negative)
    month-over-month delta we've ever seen, keyed by region.
    On the first run for a region the entry is absent; we still fire
    (the first observed loss is, by definition, a record) but report
    `previous_worst_gt=None` so the template can say "first on record".
    """
    if len(readings) < 2:
        return None

    latest = readings[-1]
    prior = readings[-2]
    region = latest.region
    delta = latest.mass_gt - prior.mass_gt
    if delta >= 0:
        return None  # net gain or unchanged — never a loss record

    stored = state.get("ice_mass_max_loss", {}).get(region)
    prev_gt = stored.get("gt") if isinstance(stored, dict) else None
    prev_month = stored.get("month") if isinstance(stored, dict) else None

    is_record = prev_gt is None or delta < prev_gt
    if not is_record:
        return None

    return IceMassRecord(
        region=region,
        kind="monthly_loss_record",
        month=latest.month,
        monthly_delta_gt=delta,
        previous_worst_gt=prev_gt,
        previous_worst_month=prev_month,
        threshold_gt=None,
        current_mass_gt=None,
        event_id=f"ice_mass_record_{region}_monthly_{latest.month}",
    )


def detect_cumulative_milestone(
    readings: list[IceMassReading], state: dict
) -> IceMassRecord | None:
    """Fire when the latest cumulative mass anomaly crosses the next
    MILESTONE_STEP_GT floor (e.g. -5000, -6000, …) beyond the last fired
    threshold for that region.

    Stores `state["ice_mass_last_milestone"][region]` as the last fired
    threshold (negative number). Absent entry means no milestone ever
    fired for this region.
    """
    if not readings:
        return None

    latest = readings[-1]
    region = latest.region
    if latest.mass_gt >= 0:
        return None

    last_fired = state.get("ice_mass_last_milestone", {}).get(region)

    # To detect a milestone crossing, we need either:
    # - Multiple readings (so we can see a transition), OR
    # - A previous milestone fired (so we know which one is next)
    if len(readings) < 2 and last_fired is None:
        return None

    # Determine what milestone threshold the current mass has crossed.
    # We look for the LEAST NEGATIVE milestone that is >= latest.mass_gt.
    # E.g., -5050 has crossed -5000; -4850 has crossed -4000.
    crossed = math.ceil(latest.mass_gt / MILESTONE_STEP_GT) * MILESTONE_STEP_GT

    # Check: have we crossed a NEW milestone (one we haven't fired for)?
    # If last_fired is None, crossed must be <= -MILESTONE_STEP_GT (i.e., at or past the first milestone).
    # If last_fired is set, crossed must be more negative (smaller) than last_fired.
    if last_fired is None:
        if crossed > -MILESTONE_STEP_GT:
            # Haven't reached the first milestone yet.
            return None
    else:
        if crossed >= last_fired:
            # Not more negative than the last fired milestone.
            return None

    return IceMassRecord(
        region=region,
        kind="cumulative_milestone",
        month=latest.month,
        monthly_delta_gt=None,
        previous_worst_gt=None,
        previous_worst_month=None,
        threshold_gt=float(crossed),
        current_mass_gt=latest.mass_gt,
        event_id=f"ice_mass_record_{region}_cumulative_{int(crossed)}",
    )
