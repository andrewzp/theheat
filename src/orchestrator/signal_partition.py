"""Partition GHCN (US) and Open-Meteo (world) extreme-signal outputs.

``THEHEAT_SIGNALS_PROVIDER=both`` runs both providers each cycle. GHCN has deep
NOAA station coverage inside the US but near-zero low-latency coverage outside
it; Open-Meteo covers the curated global cities (incl. Europe) in near-real
time. We partition by country so every place is sourced from exactly one
provider — the US from GHCN, the rest of the world from Open-Meteo — with no
overlap and no fragile name/geo matching.

The two providers label the US differently: cities.csv (Open-Meteo) uses the
short code "US"; GHCN uses the full "United States" and bracketed-territory
forms like "Northern Mariana Islands [United States]". ``is_us_location``
recognises both, and only those.
"""

from __future__ import annotations

from src.data.open_meteo import CountryRecord, ExtremeSignalBundle


def is_us_location(country: str | None) -> bool:
    """True if ``country`` denotes the US or a US territory.

    Matches the Open-Meteo short code ("US") and the GHCN full name /
    bracketed-territory forms ("United States", "... [United States]"), while
    rejecting unrelated "United ..." countries (United Kingdom, UAE).
    """
    c = (country or "").strip()
    return c == "US" or "United States" in c


def partition_us_world(
    bundles_ghcn: list[ExtremeSignalBundle],
    country_ghcn: list[CountryRecord],
    bundles_open_meteo: list[ExtremeSignalBundle],
    country_open_meteo: list[CountryRecord],
) -> tuple[list[ExtremeSignalBundle], list[CountryRecord]]:
    """Merge both providers into one (bundles, country_records) pair.

    US locations are taken from GHCN, non-US from Open-Meteo. GHCN US bundles
    keep their original order and lead; Open-Meteo world bundles follow.
    """
    bundles = [b for b in bundles_ghcn if is_us_location(b.country)] + [
        b for b in bundles_open_meteo if not is_us_location(b.country)
    ]
    country_records = [c for c in country_ghcn if is_us_location(c.country)] + [
        c for c in country_open_meteo if not is_us_location(c.country)
    ]
    return bundles, country_records
