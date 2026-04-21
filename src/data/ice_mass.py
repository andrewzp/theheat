"""NASA GRACE-FO ice mass anomaly — Greenland + Antarctica.

Level-4 mascon time series from JPL, served via PO.DAAC. Monthly cadence
with a 1-2 month publication lag. Requires Earthdata Login — set
`EARTHDATA_TOKEN` to a user-generated app token from
https://urs.earthdata.nasa.gov/.

Records start 2002.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os

import requests

# Pinned product URLs. Update constants when the product version bumps.
GREENLAND_URL = (
    "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
    "RL06.3v04/mascon_CRI/GRN-ICE-MASS-anomaly-time-series.txt"
)
ANTARCTICA_URL = (
    "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L4/ice_mass/"
    "RL06.3v03/mascon_CRI/ANT-ICE-MASS-anomaly-time-series.txt"
)

REGION_URLS = {"greenland": GREENLAND_URL, "antarctica": ANTARCTICA_URL}

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


def fetch_grace_mass(region: str) -> list[IceMassReading]:
    """Fetch the PODAAC Level-4 mass anomaly time series for a region.

    Returns readings sorted oldest → newest. Returns [] on any failure
    (missing token, HTTP error, parse error) so callers can treat the
    lane as skipped rather than crashing.
    """
    if region not in REGION_URLS:
        return []

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("[ice_mass] EARTHDATA_TOKEN not configured — skipping")
        return []

    try:
        resp = requests.get(
            REGION_URLS[region],
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[ice_mass] {region} fetch error: {e}")
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


def detect_cumulative_milestone(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    raise NotImplementedError
