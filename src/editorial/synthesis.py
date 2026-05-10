"""Cross-source story synthesis — rules that fire when multiple per-source
signals converge on the same US state within a short window.

See docs/superpowers/specs/2026-04-20-cross-source-synthesis-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, UTC

from src.state import (
    get_synthesis_components,
    get_synthesis_drought_snapshot,
    is_synthesis_on_cooldown,
)
from src.state_schema import BotState, DroughtSnapshot

RULE_FIRE_DROUGHT_HEAT = "fire_drought_heat"
WINDOW_DAYS = 14
D4_PCT_MIN = 1.0
SNAPSHOT_TTL_DAYS = 14


@dataclass(frozen=True)
class SynthesisSignal:
    rule_name: str
    region: str
    event_id: str
    headline: str
    components: dict = field(default_factory=dict)
    qualifying_window_days: int = WINDOW_DAYS


def _state_key(region: str) -> str:
    return region.lower().replace(" ", "-")


def _iso_week(today: date | None = None) -> str:
    t = today or date.today()
    y, w, _ = t.isocalendar()
    return f"{y}-W{w:02d}"


def _snapshot_is_fresh(snapshot: DroughtSnapshot | dict, ttl_days: int = SNAPSHOT_TTL_DAYS) -> bool:
    updated_at = snapshot.get("updated_at") if snapshot else None
    if not updated_at:
        return False
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return (datetime.now(UTC) - dt) < timedelta(days=ttl_days)


def detect_fire_drought_heat(bot_state: BotState) -> list[SynthesisSignal]:
    """Emit one SynthesisSignal per US state where D4 drought, a qualifying
    fire, and a qualifying heat record all converge in the last 14 days and
    the rule isn't on cooldown for that state."""
    if bot_state.get("synthesis_enabled") is False:
        return []

    snapshot = get_synthesis_drought_snapshot(bot_state)
    if not snapshot or not _snapshot_is_fresh(snapshot):
        return []

    since = (datetime.now(UTC) - timedelta(days=WINDOW_DAYS)).isoformat().replace("+00:00", "Z")
    signals: list[SynthesisSignal] = []

    for entry in snapshot.get("entries", []):
        state_name = entry.get("state") or ""
        d4_pct = float(entry.get("d4_pct") or 0)
        if not state_name or d4_pct < D4_PCT_MIN:
            continue
        if is_synthesis_on_cooldown(bot_state, RULE_FIRE_DROUGHT_HEAT, state_name):
            continue

        fires = get_synthesis_components(bot_state, kind="fire", region=state_name, since=since)
        heats = get_synthesis_components(bot_state, kind="heat", region=state_name, since=since)
        if not fires or not heats:
            continue

        peak_fire = max(fires, key=lambda f: float(f.get("frp") or 0))
        # Rank heats by anomaly when present (it's the story-relevant
        # number); fall back to absolute value for legacy entries missing
        # an anomaly field.
        def _heat_rank(h: dict) -> float:
            a = h.get("anomaly_c")
            if a is not None:
                return abs(float(a))
            return abs(float(h.get("value_c") or 0))
        peak_heat = max(heats, key=_heat_rank)

        peak_heat_anomaly = peak_heat.get("anomaly_c")
        peak_heat_anomaly = float(peak_heat_anomaly) if peak_heat_anomaly is not None else 0.0

        event_id = f"synthesis_fdh_{_state_key(state_name)}_{_iso_week()}"
        headline = (
            f"{state_name}: D4 drought + {float(peak_fire.get('frp') or 0):.0f} MW fire "
            f"+ {peak_heat.get('city') or 'city'} heat record"
        )
        components = {
            "drought_d4_pct": d4_pct,
            "drought_d3_pct": float(entry.get("d3_pct") or 0),
            "fire_peak_frp": float(peak_fire.get("frp") or 0),
            "fire_peak_region": peak_fire.get("region") or "",
            "fire_count": len(fires),
            "heat_peak_kind": peak_heat.get("kind") or "record",
            "heat_peak_city": peak_heat.get("city") or "",
            "heat_peak_value_c": float(peak_heat.get("value_c") or 0),
            "heat_peak_anomaly_c": peak_heat_anomaly,
            "heat_count": len(heats),
            "window_days": WINDOW_DAYS,
        }
        signals.append(SynthesisSignal(
            rule_name=RULE_FIRE_DROUGHT_HEAT,
            region=state_name,
            event_id=event_id,
            headline=headline,
            components=components,
        ))
    return signals
