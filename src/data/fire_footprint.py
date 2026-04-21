"""GWIS fire footprint data — cumulative burned area per fire complex.

Complements FIRMS (point detections, "is there a fire at lat/lon?") by
answering the scale question: "how many hectares has this complex burned?"

Source decision (2026-04-20): primary GWIS (Global Wildfire Information
System, https://gwis.jrc.ec.europa.eu/). If mapping the endpoint
exceeds 60–90 minutes, the same module falls back to NIFC for US-only
coverage. Endpoint + auth posture documented in BRIEFING.md.
"""

from dataclasses import dataclass
from datetime import date

# Hectare thresholds for per-fire-complex tweet dedup. A complex is
# eligible for a draft each time it crosses into a higher tier. Integer
# indices (not hectare values) are stored in state so we can tune the
# ladder later without retroactively re-tweeting.
TIERS_HECTARES = [20_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]


@dataclass
class FireComplex:
    complex_id: str
    name: str | None
    country: str
    region: str
    hectares: float
    start_date: date | None
    tier: int
    event_id: str


def _classify_tier(hectares: float) -> int:
    """Return the highest ladder index whose threshold is <= hectares.

    Returns -1 if below the floor (not tweet-worthy). Clamps at the top
    tier for megafires beyond 1M ha.
    """
    tier = -1
    for i, threshold in enumerate(TIERS_HECTARES):
        if hectares >= threshold:
            tier = i
    return tier


def detect_tier_crossings(
    complexes: list[FireComplex],
    state: dict,
) -> list[FireComplex]:
    """Return complexes whose current tier is strictly higher than the
    last tier we've already tweeted about.

    Does not mutate state. The caller writes the updated tier only after
    a draft is successfully saved.
    """
    last_tiers = state.get("fire_complex_tiers", {}) or {}
    crossings: list[FireComplex] = []
    for fc in complexes:
        if fc.tier < 0:
            continue
        previous = last_tiers.get(fc.complex_id, -1)
        if fc.tier > previous:
            crossings.append(fc)
    return crossings
