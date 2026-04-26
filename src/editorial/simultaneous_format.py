"""Format-selection logic for the simultaneous_records signal.

The signal fires when 5+ cities break daily records the same day. The
generator can render this two ways:

- Flat summary (default): "On this date, 7 cities broke their daily
  records." Reads cleanly when the cluster is globally scattered.
- Multi-station roll-call (option): per-station list with temps and
  elevation. Reads better when the cluster is geographically tight
  (same country) AND has elevation diversity — that's the story
  worth telling station by station.

This module owns ONE decision: given the per-station data, does any
subset qualify for roll-call format? If yes, return the subset. Else
return None and the caller falls back to the flat summary.

Roll-call is intentionally an option, not the default. Tune the
thresholds in the constants below if observed fire-rate is wrong.
"""

from __future__ import annotations

# Minimum stations in a same-country group before roll-call is worth it.
ROLL_CALL_MIN_STATIONS = 3

# Minimum elevation spread (meters) within a same-country group for
# the multi-altitude story to read. Below this, the per-station list
# is just three cities at similar altitudes — flat summary is cleaner.
ROLL_CALL_MIN_ELEVATION_SPREAD_M = 800


def select_roll_call_subset(stations: list[dict]) -> list[dict] | None:
    """Return the subset of stations that justify a roll-call, or None.

    A subset qualifies when:
    - It contains at least ``ROLL_CALL_MIN_STATIONS`` stations from the
      same country.
    - At least 2 of those stations have known elevations and the
      spread between min and max elevation is
      ``ROLL_CALL_MIN_ELEVATION_SPREAD_M`` or larger.

    When multiple countries qualify, the largest group wins.

    The expected shape of each station dict:
        {
          "city": str, "country": str,
          "temp_c": float, "kind": "high" | "low",
          "old_record_c": float, "old_record_year": int,
          "margin_c": float,
          "elevation_m": int | None,
        }
    """
    if not stations or len(stations) < ROLL_CALL_MIN_STATIONS:
        return None

    # Bucket by country, but skip stations with no country — otherwise
    # three unrelated stations missing country data could group together
    # under the empty-string key and falsely qualify as a same-country
    # roll-call.
    by_country: dict[str, list[dict]] = {}
    for st in stations:
        country = (st.get("country") or "").strip()
        if not country:
            continue
        by_country.setdefault(country, []).append(st)

    qualifying: list[tuple[str, int, list[dict]]] = []
    for country, group in by_country.items():
        if len(group) < ROLL_CALL_MIN_STATIONS:
            continue
        elevations = [
            s["elevation_m"] for s in group
            if s.get("elevation_m") is not None
        ]
        if len(elevations) < 2:
            continue
        spread = max(elevations) - min(elevations)
        if spread >= ROLL_CALL_MIN_ELEVATION_SPREAD_M:
            qualifying.append((country, spread, group))

    if not qualifying:
        return None

    # Deterministic ordering when multiple groups qualify:
    #   1. largest group wins (more stations = stronger story)
    #   2. ties broken by larger elevation spread (sharper altitude story)
    #   3. final tie-breaker: country name alphabetical (stable across runs)
    # Without these, dict-iteration order leaks through and the same data
    # can produce different roll-calls on different runs.
    qualifying.sort(key=lambda t: (-len(t[2]), -t[1], t[0]))
    return qualifying[0][2]
