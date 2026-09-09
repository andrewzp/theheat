"""Registry-owned place identity, separate from a weather sampling point.

Display names are never scientific keys. A changed point cannot inherit a baseline.
No geocoder, fuzzy matching, or network is used. Registry aliases are intentional.
"""

from __future__ import annotations

import csv
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Any
from collections.abc import Mapping

DATA = Path(__file__).resolve().parents[2] / "data"
CACHE_PRODUCT = "openmeteo-archive-daily-30y-v1"
_TOKEN = re.compile(r"loc1-(pl[0-9]+|ux[a-f0-9]{16})-(pt[a-f0-9]{16})")


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


@lru_cache(maxsize=1)
def country_codes() -> dict[str, str]:
    return json.loads((DATA / "country_codes.json").read_text())["codes"]


def country_key(value: str) -> str:
    value = str(value or "").strip()
    if value.upper() in set(country_codes().values()):
        return value.upper()
    return country_codes().get(normalize(value), "label:" + normalize(value)) if value else ""


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def sampling_point_id(lat: Any, lon: Any) -> str:
    lat, lon = float(lat), float(lon)
    if (
        not math.isfinite(lat)
        or not math.isfinite(lon)
        or not -90 <= lat <= 90
        or not -180 <= lon <= 180
    ):
        raise ValueError("Invalid sampling coordinates")
    return "pt" + _digest([0.0 if lat == 0 else lat, 0.0 if lon == 0 else lon])


@lru_cache(maxsize=1)
def registry() -> tuple[dict, ...]:
    rows = json.loads((DATA / "place_registry.json").read_text())["places"]
    ids, aliases = set(), {}
    for row in rows:
        if row["place_id"] in ids:
            raise ValueError("Duplicate place ID")
        ids.add(row["place_id"])
        sampling_point_id(row["lat"], row["lon"])
        for alias in row["aliases"]:
            key = (
                normalize(alias["city"]),
                country_key(alias["country"]),
                sampling_point_id(alias["lat"], alias["lon"]),
            )
            if key in aliases and aliases[key] != row["place_id"]:
                raise ValueError("Conflicting place alias")
            aliases[key] = row["place_id"]
    return tuple(rows)


@lru_cache(maxsize=4096)
def resolve_place(city: str, country: str, lat=None, lon=None, *, place_id: str = "") -> dict:
    """Resolve a registered place; preserve the exact requested sample coordinates.

    Without an explicit registry ID, a known name with unlisted coordinates gets
    an unregistered identity, not an assumed same-city match. A known ID permits
    a deliberate point revision. Unregistered points remain coordinate-specific.
    """
    matches = [
        r
        for r in registry()
        if (
            r["place_id"] == place_id
            if place_id
            else any(
                normalize(a["city"]) == normalize(city)
                and country_key(a["country"]) == country_key(country)
                for a in [r, *r["aliases"]]
            )
        )
    ]
    if len(matches) > 1 and lat is not None and lon is not None:
        requested = sampling_point_id(lat, lon)
        matches = [
            r
            for r in matches
            if requested in {sampling_point_id(a["lat"], a["lon"]) for a in [r, *r["aliases"]]}
        ]
    row = matches[0] if len(matches) == 1 else None
    if place_id and row is None:
        raise ValueError("Unknown registry place ID")
    if (
        place_id
        and row
        and not any(
            normalize(a["city"]) == normalize(city)
            and country_key(a["country"]) == country_key(country)
            for a in [row, *row["aliases"]]
        )
    ):
        raise ValueError("Place ID conflicts with supplied geography")
    if lat is None or lon is None:
        if row is None:
            raise ValueError("Unregistered place needs coordinates")
        lat, lon = row["lat"], row["lon"]
    point = sampling_point_id(lat, lon)
    if (
        row is not None
        and not place_id
        and point not in {sampling_point_id(a["lat"], a["lon"]) for a in [row, *row["aliases"]]}
    ):
        row = None
    code = row["country_code"] if row else country_key(country)
    if not str(city).strip() or not code:
        raise ValueError("Place needs city and country")
    pid = row["place_id"] if row else "ux" + _digest([normalize(city), code, point])
    return {
        "place_id": pid,
        "sampling_point_id": point,
        "country_code": code,
        "city": row["city"] if row else city,
        "country": row["country"] if row else country,
        "lat": float(lat),
        "lon": float(lon),
    }


def place_for_row(row: dict) -> dict:
    return resolve_place(
        row["city"],
        row["country"],
        row.get("lat"),
        row.get("lon"),
        place_id=row.get("place_id", ""),
    )


def event_location_key(city, country, lat=None, lon=None, *, place_id="") -> str:
    place = resolve_place(city, country, lat, lon, place_id=place_id)
    return f"loc1-{place['place_id']}-{place['sampling_point_id']}"


def event_identity(event_id: str) -> dict:
    match = _TOKEN.search(str(event_id or ""))
    return {"place_id": match[1], "sampling_point_id": match[2]} if match else {}


def cache_key(city, country, lat=None, lon=None, *, place_id="") -> str:
    return CACHE_PRODUCT + ":" + event_location_key(city, country, lat, lon, place_id=place_id)


def load_cities(path: str = "data/cities.csv") -> list[dict]:
    """Resolve rows, collapsing explicit aliases onto one selected active point."""
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    result, seen = [], set()
    for raw in rows:
        place = place_for_row(raw)
        if place["place_id"] in seen:
            continue
        seen.add(place["place_id"])
        registered = next((r for r in registry() if r["place_id"] == place["place_id"]), None)
        if registered:
            place = resolve_place(
                registered["city"],
                registered["country"],
                registered["lat"],
                registered["lon"],
                place_id=registered["place_id"],
            )
        result.append({**raw, **place})
    return result


def identity_from_payload(payload: dict) -> dict:
    """Read identity only from structured evidence, never from tweet prose."""
    direct = event_identity(payload.get("event_id", ""))
    if direct:
        return direct
    try:
        return resolve_place(
            payload["city"], payload["country"], payload.get("lat"), payload.get("lon")
        )
    except (KeyError, TypeError, ValueError):
        return {}


def draft_place_id(draft: dict) -> str:
    review = draft.get("review_context") or {}
    bundle = (review.get("two_bot") or {}).get("bundle") or {}
    raw = bundle.get("raw_signal_dump") or {}
    return (event_identity(draft.get("event_id", "")) or identity_from_payload(raw)).get(
        "place_id", ""
    )


def legacy_event_candidates(event_id: str) -> set[str]:
    """Known old display-name IDs, for evidence-aware migration containment."""
    ident = event_identity(event_id)
    row = next((r for r in registry() if r["place_id"] == ident.get("place_id")), None)
    if not row:
        return set()
    variants = set()
    for alias in row["aliases"]:
        for name in (
            alias["city"].replace(" ", "_"),
            alias["city"].lower().replace(" ", "_").replace(",", ""),
            f"{alias['city']}_{alias['country']}".replace(" ", "_"),
        ):
            variants.add(_TOKEN.sub(name, event_id))
        if event_id.startswith("gpm_"):
            slug = lambda value: re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
            variants.add(_TOKEN.sub(slug(alias["country"]) + "_" + slug(alias["city"]), event_id))
    return variants


def legacy_publication_status(state: Mapping, event_id: str) -> str:
    """Return duplicate/ambiguous/clear without rewriting historical records.

    A bare ID without attributable retained evidence contains the new candidate
    for manual identity review; it never asserts both places were published.
    """
    variants = legacy_event_candidates(event_id)
    recorded = variants & set(state.get("posted_events") or [])
    if not recorded:
        return "clear"
    target = event_identity(event_id).get("place_id")
    unresolved = set(recorded)
    for draft in state.get("drafts") or []:
        if draft.get("status") != "posted" or draft.get("event_id") not in recorded:
            continue
        pid = draft_place_id(draft)
        if pid:
            unresolved.discard(draft["event_id"])
            if pid == target:
                return "duplicate"
    return "ambiguous" if unresolved else "clear"


def requires_identity_review(draft: dict) -> bool:
    """Automatic-send containment for legacy scientific identities.

    Read-only: never relabel old evidence or touch an uncertain attempt/receipt.
    The posting integration calls this only for automatic publication. A human
    can inspect/rebuild the evidence through the existing manual review path.
    """
    event_id = str(draft.get("event_id") or "")
    if event_identity(event_id):
        return False
    if event_id.startswith("hot10_"):
        review = draft.get("review_context") or {}
        raw = ((review.get("two_bot") or {}).get("bundle") or {}).get("raw_signal_dump") or {}
        cities = raw.get("cities") or []
        return not cities or any(
            not row.get("place_id") or not row.get("sampling_point_id") for row in cities
        )
    point_signal = re.match(
        r"^(record(?:_low)?|alltime_(?:high|low)|monthly_(?:high|low)|anomaly_(?:hot|cold)|absextreme(?:_cold)?|wetbulb|streak|pm25|dust)_",
        event_id,
    )
    if not point_signal:
        return False
    return not re.search(r"_[A-Z]{2}[A-Z0-9]{9}_", event_id)
