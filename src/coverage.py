"""Resolve an event's country to a continent for the coverage watch."""
from __future__ import annotations

import json
import os
from functools import lru_cache

_MAP_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "country_continent.json"
)


@lru_cache(maxsize=1)
def _country_continent() -> dict[str, str]:
    try:
        with open(_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def is_us_location(country: str | None) -> bool:
    c = (country or "").strip()
    return c == "US" or "United States" in c


def resolve_continent(country: str | None) -> str:
    c = (country or "").strip()
    if not c:
        return "Unknown"
    if is_us_location(c):
        return "North America"
    return _country_continent().get(c, "Unknown")
