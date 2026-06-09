"""Wet-bulb extreme two-bot intern builder."""

from __future__ import annotations

from dataclasses import asdict

from src.data.open_meteo import WetBulbEvent
from src.two_bot.types import StoryBundle
from ._shared import _audience_unit_facts, _c_to_f, _climate_context_facts, _resolve_when

_TIER_LABEL_DISPLAY = {
    2: "extreme (33C wet-bulb)",
    3: "35C wet-bulb (tier 3)",
}


def build_wet_bulb_bundle(ev: WetBulbEvent) -> StoryBundle:
    """Assemble a StoryBundle for a wet-bulb extreme signal."""
    where = f"{ev.city}, {ev.country}" if ev.country else ev.city
    tw_f = _c_to_f(ev.daily_max_tw_c)
    threshold_f = _c_to_f(ev.tier_threshold_c)

    historical_context: dict = {}
    if ev.archive_max_tw_c is not None and ev.archive_years is not None:
        historical_context = {
            "archive_max_tw_c": ev.archive_max_tw_c,
            "archive_max_year": ev.archive_max_year,
            "archive_years": ev.archive_years,
            "scope": "wet_bulb_archive_max",
        }

    return StoryBundle(
        signal_kind="wet_bulb_extreme",
        where=where,
        when=_resolve_when(ev.signal_date),
        event_id=ev.event_id,
        headline_metric={
            "label": "daily_max_tw_c",
            "value": ev.daily_max_tw_c,
            "unit": "C_wetbulb",
            "value_f": tw_f,
        },
        current_facts=[
            {"label": "city", "value": ev.city},
            {"label": "country", "value": ev.country},
            {"label": "daily_max_tw_c", "value": ev.daily_max_tw_c},
            {"label": "daily_max_tw_f", "value": tw_f},
            {"label": "tier", "value": ev.tier},
            {"label": "tier_label", "value": ev.tier_label},
            {"label": "tier_threshold_c", "value": ev.tier_threshold_c},
            {"label": "tier_threshold_f", "value": threshold_f},
            {
                "label": "tier_display",
                "value": _TIER_LABEL_DISPLAY.get(ev.tier, ev.tier_label),
            },
            {
                "label": "tw_explainer",
                "value": (
                    "Wet-bulb temperature measures the body's ability to cool by sweating. "
                    "Near 35C TW, healthy adults in shade can no longer shed heat as fast "
                    "as the body produces it."
                ),
            },
            *_audience_unit_facts(ev.country),
            *_climate_context_facts(ev.lat, ev.lon, category="high"),
        ],
        historical_context=historical_context,
        raw_signal_dump=asdict(ev),
    )
