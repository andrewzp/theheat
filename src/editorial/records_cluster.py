"""Spatial clustering of same-day heat-record cities into a "record-setting heat
across [region]" story, with honest, non-overclaiming geographic naming (#414).

Global by construction: rides the worldwide daily calendar-record station list
(GHCN US + Open-Meteo world cities). Two pure responsibilities:

  1. ``cluster_record_stations`` — single-linkage spatial clusters by great-circle
     distance (a heat dome is a spatial blob that ignores political boundaries).
  2. ``name_cluster`` — name each cluster HONESTLY. The only *named region* allowed
     is a documented reganom ``REGION_WATCHLIST`` zone, and only when the cluster is
     country-PURE for that zone (not merely near its points — Iberia's points sit one
     strait from Maghreb's) AND geographically contained in it. Otherwise the label is
     "N cities across K countries[ in {continent(s)}]", where the country list is the
     verifiable backbone and the continent is asserted only when unambiguous (omitted
     for transcontinental countries like Russia/Turkey, whose country→continent lookup
     would mislabel a western-Russia cluster "in Asia").

The published copy NEVER asserts "heat dome" — that is an unproven synoptic cause; the
bundle proves only spatially-clustered same-day records. See the writer / fact-check
layers for that enforcement. This module never coins a region name and never guesses a
continent.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from src.coverage import is_us_location, resolve_continent
from src.data.reanalysis_anomaly import REGION_WATCHLIST
from src.editorial._regions import _haversine_km

# --------------------------------------------------------------------------- #
# tunable constants (module-level per reganom convention; only the enable flag
# is env-driven — see the source runner). Calibrate against observed cluster
# counts; surfaced to Andrew as taste calls.
# --------------------------------------------------------------------------- #
LINK_KM = 350.0                    # single-linkage join distance
MIN_CLUSTER_SIZE = 6               # cities needed to clear the "many records" bar
ZONE_MEMBER_KM = 300.0             # a city is "in" a zone if within this of any zone point
ZONE_CONTAINMENT_FRACTION = 0.80   # min fraction of cluster cities geographically in a zone
MAX_NAMED_COUNTRIES = 3            # cap on countries enumerated in the tier-2 label

# The documented countries of each REGION_WATCHLIST zone. Tier-1 naming requires
# the cluster to be country-PURE for the zone (every city's country in this set),
# so a cross-border bleed (Spain+Morocco) can never inherit a single zone's name.
# US zones use "US"; the purity check normalizes GHCN's "United States" via
# is_us_location. Keys MUST equal the REGION_WATCHLIST names exactly (contract
# test: test_zone_countries_keys_match_region_watchlist_exactly).
ZONE_COUNTRIES: dict[str, frozenset[str]] = {
    "Pacific Northwest": frozenset({"US", "Canada"}),
    "Desert Southwest": frozenset({"US"}),
    "France": frozenset({"France"}),
    "Iberia": frozenset({"Spain", "Portugal"}),
    "United Kingdom & Ireland": frozenset({"UK", "Ireland"}),
    "Central Mediterranean": frozenset({"Italy", "Greece", "Albania", "Malta"}),
    "Maghreb": frozenset({"Morocco", "Algeria", "Tunisia"}),
    "Sahel": frozenset({"Niger", "Sudan", "Chad", "Mali", "Nigeria"}),
    "Mesopotamia & the Gulf": frozenset(
        {"Iraq", "Iran", "Kuwait", "Saudi Arabia", "Qatar"}
    ),
    "Indo-Gangetic Plain": frozenset({"India", "Pakistan"}),
    "North China Plain": frozenset({"China"}),
    "East Siberia (Sakha)": frozenset({"Russia"}),
    "Southeast Australia": frozenset({"Australia"}),
    "Southern South America": frozenset({"Argentina", "Chile", "Uruguay"}),
    "Central Brazil": frozenset({"Brazil"}),
    "Southern Africa": frozenset(
        {"South Africa", "Zimbabwe", "Botswana", "Namibia"}
    ),
}

# Countries that physically span two continents, so a country→continent lookup is
# unreliable for a specific cluster. When any cluster city is in one of these, the
# continent is OMITTED (the country list still stands). Not exhaustive by design —
# it only needs the plausible heat-record straddlers.
TRANSCONTINENTAL_COUNTRIES: frozenset[str] = frozenset(
    {"Russia", "Turkey", "Kazakhstan", "Egypt", "Georgia", "Azerbaijan"}
)


@dataclass(frozen=True)
class ClusterName:
    """The honest geographic naming of one cluster, all fields verifiable."""

    region_name: str | None      # documented reganom zone, or None
    continents: list[str]        # unique continents, or [] when ambiguous/omitted
    countries: list[str]         # all countries, sorted by (-record_count, name)
    lead_countries: list[str]    # top MAX_NAMED_COUNTRIES by record count
    country_count: int
    city_count: int


# The exact spellings of the contiguous US that the data actually carries:
# "US" (cities.csv), "United States" (GHCN country_name), "USA" (a stray
# cities.csv row). All three are one country. Deliberately EXACT — the broad
# is_us_location() also matches bracketed territories ("Guam [United States]"),
# which are distinct Oceania/Caribbean places, not CONUS.
_CONUS_ALIASES: frozenset[str] = frozenset({"US", "USA", "United States"})


def _country_key(country: str | None) -> str:
    """Canonical country token — collapses the exact CONUS spellings to "US" so a
    cluster split across them reads as one country. Used for purity AND
    display/counting. Territories keep their own label (never inherit CONUS)."""
    c = (country or "").strip()
    return "US" if c in _CONUS_ALIASES else c


def _continent_of(country: str) -> str:
    """Continent for one canonical country key, or "Unknown" when it can't be
    asserted honestly. CONUS → North America; a US *territory* → "Unknown" (its
    true continent varies — Oceania for Guam/Samoa, the Caribbean for PR/USVI —
    so omit rather than mislabel via the CONUS-biased resolve_continent)."""
    c = country.strip()
    if c in _CONUS_ALIASES:
        return "North America"
    if is_us_location(c):  # a bracketed US territory — can't trust resolve_continent
        return "Unknown"
    return resolve_continent(c)


def _coords(station: dict) -> tuple[float, float] | None:
    """Return (lat, lon) if both are finite, in-range floats, else None.

    Rejects NaN/inf and out-of-range values so a junk coordinate is excluded
    rather than reaching (and crashing) the great-circle math.
    """
    try:
        lat = float(station["lat"])
        lon = float(station["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


def _payload_key(station: dict) -> tuple[tuple[str, str], ...]:
    """Stable full-record tie-breaker so rows identical in (lat,lon,city,country)
    but differing elsewhere sort deterministically regardless of input order."""
    return tuple(sorted((str(k), str(v)) for k, v in station.items()))


def _station_sort_key(
    station: dict,
) -> tuple[float, float, str, str, tuple[tuple[str, str], ...]]:
    lat, lon = _coords(station) or (0.0, 0.0)
    return (
        lat,
        lon,
        str(station.get("city") or ""),
        str(station.get("country") or ""),
        _payload_key(station),
    )


# --------------------------------------------------------------------------- #
# clustering
# --------------------------------------------------------------------------- #

def cluster_record_stations(
    stations: list[dict],
    *,
    link_km: float = LINK_KM,
    min_size: int = MIN_CLUSTER_SIZE,
) -> list[list[dict]]:
    """Single-linkage spatial clusters of at least ``min_size`` stations.

    Only stations with numeric lat & lon participate. Two stations are linked when
    their great-circle distance is <= ``link_km``; linkage chains transitively, so a
    contiguous dome forms one cluster. Deterministic: stations are sorted by
    (lat, lon, city, country) before union-find, each cluster keeps that order, and
    clusters are returned sorted by (-size, first-station-key) — no run-to-run drift.
    """
    indexed = [s for s in stations if _coords(s) is not None]
    indexed.sort(key=_station_sort_key)
    n = len(indexed)
    if n < min_size:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    coords = [_coords(s) for s in indexed]
    for i in range(n):
        lat_i, lon_i = coords[i]  # type: ignore[misc]
        for j in range(i + 1, n):
            lat_j, lon_j = coords[j]  # type: ignore[misc]
            if _haversine_km(lat_i, lon_i, lat_j, lon_j) <= link_km:
                union(i, j)

    groups: dict[int, list[dict]] = {}
    for idx, station in enumerate(indexed):
        groups.setdefault(find(idx), []).append(station)

    clusters = [g for g in groups.values() if len(g) >= min_size]
    clusters.sort(key=lambda g: (-len(g), _station_sort_key(g[0])))
    return clusters


# --------------------------------------------------------------------------- #
# honest naming
# --------------------------------------------------------------------------- #

def _zone_containment(stations: list[dict], zone_points: list[tuple[float, float]]) -> float:
    """Fraction of coord-bearing stations within ZONE_MEMBER_KM of any zone point."""
    coorded = [c for c in (_coords(s) for s in stations) if c is not None]
    if not coorded:
        return 0.0
    inside = 0
    for lat, lon in coorded:
        if any(
            _haversine_km(lat, lon, plat, plon) <= ZONE_MEMBER_KM
            for plat, plon in zone_points
        ):
            inside += 1
    return inside / len(coorded)


def _match_zone(stations: list[dict], countries: set[str]) -> str | None:
    """Best documented reganom zone: country-pure AND geographically contained.

    ``countries`` MUST be the non-empty set of canonical country keys for the whole
    cluster. An empty set is never pure (the caller blocks that case) — otherwise
    ``set() <= allowed`` would vacuously name every zone from missing data.
    """
    if not countries:
        return None
    best_name: str | None = None
    best_containment = 0.0
    for region in REGION_WATCHLIST:
        allowed = ZONE_COUNTRIES.get(region.name)
        if allowed is None:
            continue
        if not countries <= allowed:  # purity: every cluster country in the zone
            continue
        containment = _zone_containment(stations, region.points)
        if containment < ZONE_CONTAINMENT_FRACTION:
            continue
        # highest containment wins; ties broken by zone name for determinism
        if containment > best_containment or (
            containment == best_containment
            and (best_name is None or region.name < best_name)
        ):
            best_name = region.name
            best_containment = containment
    return best_name


def _continents_for(countries: list[str], *, blocked: bool) -> list[str]:
    """Unique continents for the cluster, or [] when it can't be asserted honestly.

    Omit (return []) when ``blocked`` (an unresolved/blank country is present), when
    there are no countries, or when any country is transcontinental or resolves to
    Unknown — the country list stays as the verifiable backbone; the continent is
    only asserted when every country belongs unambiguously to one. ``countries`` are
    canonical keys (US variants already collapsed to "US").
    """
    if blocked or not countries:
        return []
    if any(c in TRANSCONTINENTAL_COUNTRIES for c in countries):
        return []
    resolved = {_continent_of(c) for c in countries}
    if "Unknown" in resolved:
        return []
    return sorted(resolved)


def name_cluster(stations: list[dict]) -> ClusterName:
    """Honest geographic naming of one cluster (see module docstring).

    A blank/missing country on ANY member blocks tier-1 zone naming (an empty
    country set must never be treated as pure for a zone) and forces the continent
    to be omitted — a false geography label from missing data is the exact failure
    this class guards against.
    """
    raw_countries = [(s.get("country") or "").strip() for s in stations]
    has_unresolved = any(not c for c in raw_countries)
    # Canonical counting so "US"/"United States" collapse to one country.
    counts = Counter(_country_key(c) for c in raw_countries if c)
    # deterministic: by descending record count, then country name
    ordered_countries = sorted(counts, key=lambda c: (-counts[c], c))

    region_name: str | None = None
    if not has_unresolved and ordered_countries:
        region_name = _match_zone(stations, set(ordered_countries))

    return ClusterName(
        region_name=region_name,
        continents=_continents_for(ordered_countries, blocked=has_unresolved),
        countries=ordered_countries,
        lead_countries=ordered_countries[:MAX_NAMED_COUNTRIES],
        country_count=len(ordered_countries),
        city_count=len(stations),
    )
