"""Row 13 — heat-exposure aggregate (US population under Extreme Heat Warnings).

The story class nothing else produces: not one city's record, but "the N counties
under an active Extreme Heat Warning are home to ~X million people." Every active NWS
alert already carries `properties.geocode.SAME` (6-digit county codes); this joins the
Warning-tier counties to a vendored, public-domain Census county population map and sums
DISTINCT counties.

Honesty (see the writer/fact-check gates): the SAME->county join attributes each
county's WHOLE population even when only a sub-county forecast zone is warned, so the
figure is an UPPER BOUND on people warned. The honest framing is county-scoped — "the N
counties under warning are home to X million," never "X million people are under the
warning." Marine/unknown SAME codes (no county population) are dropped.

Data: `us_county_population.csv` (FIPS,POPESTIMATE2024 for SUMLEV=050 counties, trimmed
from the Census CO-EST2024 file — US Government work, public domain). Vendored so the
lane has no runtime census.gov dependency and is fully testable.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests

from src.data._http import fetch_with_retry
from src.data.source_status import SourceFetchError

HEAT_WARNING_EVENT = "Extreme Heat Warning"
_POP_CSV = Path(__file__).with_name("us_county_population.csv")
_NWS_URL = "https://api.weather.gov/alerts/active"


@dataclass(frozen=True)
class HeatExposureEvent:
    county_count: int
    population: int
    warning_event: str
    as_of: str
    sample_states: list[str]  # 2-digit state FIPS, ranked by warned population
    fips: tuple[str, ...]  # sorted distinct county FIPS (dedup + provenance)
    event_id: str = ""


@lru_cache(maxsize=1)
def load_county_population() -> dict[str, int]:
    """FIPS (5-digit) -> 2024 population, from the vendored Census county file."""
    table: dict[str, int] = {}
    with _POP_CSV.open(newline="") as fh:
        for row in csv.DictReader(fh):
            fips = (row.get("fips") or "").strip()
            raw = (row.get("pop2024") or "").strip()
            if len(fips) == 5 and fips.isdigit() and raw.isdigit():
                table[fips] = int(raw)
    return table


def same_to_fips(same: str) -> str | None:
    """A 6-digit SAME code (P-SS-CCC) -> its 5-digit county FIPS, else None.

    The leading digit is the "portion of county" flag (0 = whole county); the
    trailing 5 digits are the standard county FIPS regardless of that flag.
    """
    s = (same or "").strip()
    if len(s) == 6 and s.isdigit():
        return s[1:]
    return None


def compute_heat_exposure(
    alerts: list[dict],
    *,
    population: dict[str, int],
    as_of: str,
    event: str = HEAT_WARNING_EVENT,
    event_id: str = "",
) -> HeatExposureEvent | None:
    """Sum DISTINCT-county population under the given Warning-tier event.

    ``alerts`` are normalized dicts: ``{"event": str, "same": [str, ...]}``. Only
    alerts whose ``event`` matches ``event`` count; SAME codes that do not resolve to
    a county in ``population`` (marine zones, territories absent from the file) are
    dropped. Returns None when no qualifying county is warned.
    """
    fips_set: set[str] = set()
    for alert in alerts:
        if (alert.get("event") or "") != event:
            continue
        for same in alert.get("same") or []:
            fips = same_to_fips(str(same))
            if fips is not None and fips in population:
                fips_set.add(fips)

    if not fips_set:
        return None

    fips_sorted = tuple(sorted(fips_set))
    total = sum(population[f] for f in fips_sorted)

    by_state: dict[str, int] = {}
    for f in fips_sorted:
        by_state[f[:2]] = by_state.get(f[:2], 0) + population[f]
    sample_states = [
        st for st, _ in sorted(by_state.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return HeatExposureEvent(
        county_count=len(fips_sorted),
        population=total,
        warning_event=event,
        as_of=as_of,
        sample_states=sample_states,
        fips=fips_sorted,
        event_id=event_id,
    )


def fetch_heat_alerts(*, strict: bool = False) -> list[dict]:
    """Fetch active Extreme Heat Warnings, normalized to ``{event, same, area}``.

    Reuses the single active-alerts feed the bot already polls; keeps the county
    ``SAME`` codes that ``nws_alerts.fetch_alerts`` discards. Returns [] on failure
    unless ``strict``.
    """
    try:
        resp = fetch_with_retry(
            _NWS_URL,
            params={"status": "actual", "message_type": "alert", "event": HEAT_WARNING_EVENT},
            headers={
                "User-Agent": "(theheat-bot, contact@theheat.app)",
                "Accept": "application/geo+json",
            },
            timeout=30,
            attempts=3,
            backoff_base=1.0,
        )
        data = resp.json()
        alerts: list[dict] = []
        for feature in data.get("features", []):
            props = feature.get("properties", {}) or {}
            if props.get("event") != HEAT_WARNING_EVENT:
                continue
            geocode = props.get("geocode") or {}
            alerts.append({
                "event": props.get("event", ""),
                "same": list(geocode.get("SAME") or []),
                "area": props.get("areaDesc", "") or "",
            })
        return alerts
    except (requests.RequestException, ValueError, KeyError) as exc:
        if strict:
            raise SourceFetchError(f"NWS heat-exposure fetch failed: {exc}") from exc
        return []
