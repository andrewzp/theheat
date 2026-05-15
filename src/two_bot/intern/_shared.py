"""Shared two-bot intern bundle helpers."""



from __future__ import annotations



from datetime import date



from src.data._climate_context import local_climate_context



_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

def _resolve_when(event_date: date | None) -> str:
    """Return an ISO date string for the observation.

    Uses ``event_date`` when available (GHCN path, where readings carry a
    24-48 hr lag and the observation date differs from today) and falls back
    to today for the Open-Meteo path (where ``signal_date`` is always None).
    """
    return (event_date or date.today()).isoformat()

def _format_where(city: str, country: str, state: str | None = None) -> str:
    """Build the bundle's ``where`` field, including state when present.

    For GHCN US stations, ``state`` is the full name ("West Virginia",
    not "WV") so writer prose like "Sissonville, West Virginia" reads
    naturally and the fact-checker accepts the entity claim.
    Non-US stations and the Open-Meteo path pass state=None and get
    the legacy "city, country" form.
    """
    parts = [city]
    if state:
        parts.append(state)
    if country:
        parts.append(country)
    return ", ".join(parts)

def _ghcn_observation_facts(
    state: str | None,
    kind: str | None,
) -> list[dict]:
    """Extra ``current_facts`` for GHCN bundles.

    Two enrichments that ground the writer in bundle data instead of
    world-knowledge guesses (which the fact-checker rejects):

    - ``state``: full US state name when known. Lets the writer use
      "Sissonville, West Virginia" without the fact-checker treating
      "West Virginia" as an unverifiable named entity.
    - ``observation_kind``: source-neutral label for the daily extremum.
      GHCN TMIN/TMAX are 24-hour extrema, not timestamped observations —
      a cold front past sunrise can set the daily min; a warm overnight
      event can set the max. Using ``daily_minimum`` / ``daily_maximum``
      avoids implying time-of-day that the data does not prove.
      Only emitted when ``state`` is present (i.e. confirmed GHCN path).

    Both are no-ops when the inputs are missing, so non-GHCN paths get
    an empty list.
    """
    extra: list[dict] = []
    if state:
        extra.append({"label": "state", "value": state})
        if kind == "low":
            extra.append({"label": "observation_kind", "value": "daily_minimum"})
        elif kind == "high":
            extra.append({"label": "observation_kind", "value": "daily_maximum"})
    return extra

def _headline_temp_label(kind: str, source: str) -> str:
    """Return the correct headline_metric label for a temperature record.

    GHCN records are already-observed station readings; Open-Meteo records
    are model forecasts. Using ``observed_*_c`` for GHCN prevents the writer
    from generating "forecast" prose for data that has already happened.

    Args:
        kind:   ``"high"`` or ``"low"``.
        source: ``"ghcn"`` for GHCN station readings;
                ``"open_meteo"`` (or any other value) for forecasts.
    """
    if source == "ghcn":
        return "observed_high_c" if kind == "high" else "observed_low_c"
    return "forecast_high_c" if kind == "high" else "forecast_low_c"

def _c_to_f(temp_c: float | None) -> int | None:
    """Convert Celsius to Fahrenheit, rounded to nearest integer.

    Integer rounding matches how a US reader speaks the number: "28°F",
    not "28.0°F" or "28.04°F". Pre-computed in the bundle so writer +
    fact-check both see the same value (avoids rounding-mismatch
    rejections in the entity check).
    """
    if temp_c is None:
        return None
    return round(temp_c * 9 / 5 + 32)

_US_COUNTRY_TOKENS = {
    "united states", "usa", "u.s.", "us", "u.s.a.",
}

def _is_us_country(country: str | None) -> bool:
    """Detect US locations so the writer can lead with Fahrenheit.

    Conservative: only the exact tokens above match. Doesn't try to
    guess based on partial substrings (e.g. "Puerto Rico [United States]"
    is NOT US for unit-priority purposes — the territory name comes
    first in tweets, and PR is mostly metric anyway).
    """
    if not country:
        return False
    return country.strip().lower() in _US_COUNTRY_TOKENS

def _audience_unit_facts(country: str | None) -> list[dict]:
    """``audience_unit`` fact: tells the writer which unit to lead with.

    "fahrenheit_first" for US (= US audience expects °F primary, °C
    parenthetical). "celsius_first" elsewhere (= the rest of the world
    plus weather nerds).
    """
    if _is_us_country(country):
        return [{"label": "audience_unit", "value": "fahrenheit_first"}]
    return [{"label": "audience_unit", "value": "celsius_first"}]

def _climate_context_facts(
    lat: float | None,
    lon: float | None,
    category: str | None = None,
) -> list[dict]:
    """Fact-checkable geographic-climate context for writer system clauses."""

    if lat is None or lon is None:
        return []
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return []

    ctx = local_climate_context(lat=lat_f, lon=lon_f, category=category)
    if not ctx:
        return []

    facts = [{"label": "region_climate_system", "value": ctx.region_climate_system}]
    if ctx.climate_mechanism_note:
        facts.append({"label": "climate_mechanism_note", "value": ctx.climate_mechanism_note})
    if ctx.local_topography_note:
        facts.append({"label": "local_topography_note", "value": ctx.local_topography_note})
    if ctx.season_context:
        facts.append({"label": "season_context", "value": ctx.season_context})
    return facts

def _frp_tier(frp_mw: float) -> tuple[str, int]:
    """Classify a fire's FRP value into a reader-relatable intensity tier.

    Raw MW is opaque to non-specialist readers; the tier word gives them a
    scale they can feel. Thresholds are simple round numbers that align with
    common conventions in wildfire research — they are not tied to any
    specific authority's classification, so the writer prompt is instructed
    NOT to attribute the tier (no "per NASA", no "by FIRMS standards").
    Returns ``(tier_label, tier_floor_mw)``. The floor is the inclusive lower
    bound of the tier, useful when the writer wants to cite the threshold
    ("above the 100 MW high-intensity threshold").
    """
    if frp_mw >= 500:
        return ("very_high", 500)
    if frp_mw >= 100:
        return ("high", 100)
    if frp_mw >= 30:
        return ("moderate", 30)
    return ("low", 0)
