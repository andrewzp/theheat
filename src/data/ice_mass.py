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
    raise NotImplementedError


def detect_monthly_record(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    raise NotImplementedError


def detect_cumulative_milestone(readings: list[IceMassReading], state: dict) -> IceMassRecord | None:
    raise NotImplementedError
