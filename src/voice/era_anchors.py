"""Pre-computed cultural anchors per year.

Curated data module with no live importers since the legacy voice
generator was deleted (economics P1.2, 2026-07-14) — kept because the
anchor corpus is hand-curated editorial reference the two_bot writer
lane may adopt (offer-anchors idea). Originally used to ground
"last time it was this hot in YEAR" framings without asking Gemini to
invent the anchor — invented anchors hallucinate (Gemini will pick a
plausible but wrong year-event pairing) and lack variety (the same
prompt produces the same anchor every time).

Source: data/era_anchors.json. Curated 2026-04-25 covering 1995-2025.
"""

from __future__ import annotations

import json
import os
import random

_DEFAULT_PATH = "data/era_anchors.json"
_cached_anchors: dict[int, list[str]] | None = None


def load_era_anchors(path: str = _DEFAULT_PATH) -> dict[int, list[str]]:
    """Load and parse the era anchors JSON.

    Result is cached at module level — repeat calls hit the cache. Pass
    a non-default path to force a reload (used by tests).

    Returns: {year_int: [anchor strings...]}. Years without entries are
    silently absent. Loader returns an empty dict if the file is missing
    or malformed — generators should treat empty as 'no anchor available'
    and degrade gracefully to Gemini's invented framing.
    """
    global _cached_anchors
    if path == _DEFAULT_PATH and _cached_anchors is not None:
        return _cached_anchors

    if not os.path.exists(path):
        result: dict[int, list[str]] = {}
    else:
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            result = {}
        else:
            result = {}
            for key, value in raw.items():
                if key.startswith("_"):
                    continue
                try:
                    year = int(key)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, list):
                    anchors = [str(v).strip() for v in value if str(v).strip()]
                    if anchors:
                        result[year] = anchors

    if path == _DEFAULT_PATH:
        _cached_anchors = result
    return result


def pick_anchors(
    year: int,
    *,
    k: int = 4,
    seed: str | None = None,
    path: str = _DEFAULT_PATH,
) -> list[str]:
    """Return up to k anchors for ``year``, randomly sampled.

    A seed makes the selection deterministic for that input — pass a
    seed like ``f"{city}-{today_iso}"`` to keep the prompt stable within
    a single tweet draft cycle while letting different events get
    different anchors. Without a seed, true random.

    Returns an empty list when the year is absent or the dataset has
    fewer than k entries (in which case all available anchors are
    returned). Callers should treat empty as 'no anchor — let Gemini
    invent or omit'.
    """
    anchors = load_era_anchors(path).get(year, [])
    if not anchors:
        return []

    rng = random.Random(seed) if seed is not None else random
    take = min(k, len(anchors))
    return rng.sample(anchors, take)


def reset_cache() -> None:
    """Drop the module-level cache. Test-only helper."""
    global _cached_anchors
    _cached_anchors = None
