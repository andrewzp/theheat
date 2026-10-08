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
RULE_MARINE_COMPOUND = "marine_compound"
WINDOW_DAYS = 14
MARINE_COMPOUND_COOLDOWN_DAYS = 60
MARINE_SST_ANOMALY_MIN_C = 2.0
MARINE_DHW_MIN_C_WEEKS = 8
D4_PCT_MIN = 1.0
SNAPSHOT_TTL_DAYS = 14

CORAL_TO_SST_REGION: dict[str, str | None] = {
    "austral_islands": None,
    "chagos_archipelago": "western_indian_ocean",
    "costa_rica_pacific": None,
    "east_java_bali": "coral_triangle",
    "fiji": None,
    "galapagos": None,
    "gilbert_islands": None,
    "great_nicobar": "bay_of_bengal",
    "kenya": "western_indian_ocean",
    "nauru": None,
    "samoas": None,
    "solomon_islands": None,
    "southern_borneo": None,
    "west_kalimanta": None,
    "western_madagascar": "western_indian_ocean",
    # Common CRW station ids not present in the S-23 active reef-context set.
    "florida_keys": "caribbean",
    "gbr_central": "great_barrier_reef",
    "gbr_northern": "great_barrier_reef",
    "gbr_southern": "great_barrier_reef",
    "great_barrier_reef": "great_barrier_reef",
}


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


def cooldown_days_for_rule(rule_name: str) -> int:
    if rule_name == RULE_MARINE_COMPOUND:
        return MARINE_COMPOUND_COOLDOWN_DAYS
    return WINDOW_DAYS


def _snapshot_is_fresh(snapshot: DroughtSnapshot | dict, ttl_days: int = SNAPSHOT_TTL_DAYS) -> bool:
    updated_at = snapshot.get("updated_at") if snapshot else None
    if not updated_at:
        return False
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)
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


def detect_marine_compound(bot_state: BotState, *, diagnostics: dict | None = None) -> list[SynthesisSignal]:
    """Pair independently dated qualified marine products at mapped locations.

    The configured association supplies neither temporal overlap nor a common
    measurement footprint. Legacy scalar-only components remain ineligible.
    """
    from src.editorial import marine_evidence as marine
    from src.data.coral_dhw import _tier_for_dhw

    if bot_state.get("synthesis_enabled") is False:
        return []
    evaluation_at = marine.now_utc()
    signals: list[SynthesisSignal] = []
    for coral_region_id, sst_region_slug in CORAL_TO_SST_REGION.items():
        if not sst_region_slug or is_synthesis_on_cooldown(
            bot_state, RULE_MARINE_COMPOUND, coral_region_id,
            days=MARINE_COMPOUND_COOLDOWN_DAYS,
        ):
            continue
        coral = marine.select_component(bot_state, "coral", coral_region_id, evaluation_at, diagnostics=diagnostics)
        sst = marine.select_component(bot_state, "sst_anomaly", sst_region_slug, evaluation_at, diagnostics=diagnostics)
        if coral is None or sst is None:
            continue
        payload = marine.make_payload(coral, sst, evaluation_at)
        c, s = coral["marine_source"]["reading"], sst["marine_source"]["reading"]
        tier, _ = _tier_for_dhw(c["dhw_value"])
        components = {
            "coral_region_id": coral_region_id, "coral_region_full_name": c["region_full_name"],
            "coral_dhw_value": c["dhw_value"], "coral_dhw_tier": tier,
            "sst_region_slug": sst_region_slug, "sst_region_display_name": s["region_display_name"],
            "sst_anomaly_c": s["anomaly_c"], "sst_tier": s["tier"], "sst_cells_used": s["cells_used"],
            "window_days": WINDOW_DAYS, "marine_payload": payload,
            "coral_valid_date": c["date"], "sst_valid_date": s["date"],
        }
        signals.append(SynthesisSignal(
            rule_name=RULE_MARINE_COMPOUND, region=coral_region_id, event_id=payload["event_id"],
            headline=(f"{c['region_full_name']}: DHW {c['dhw_value']:.1f} °C-weeks ({c['date']}); "
                      f"{s['region_display_name']}: SST anomaly {s['anomaly_c']:+.1f}°C ({s['date']})"),
            components=components,
        ))
    return signals
