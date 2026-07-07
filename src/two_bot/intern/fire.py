"""Fire two-bot intern builders."""



from __future__ import annotations



from datetime import date

from src.data.fire_footprint import FireComplex

from src.data.fire_footprint import TIERS_HECTARES

from src.data.firms import FireEvent

from src.two_bot.types import StoryBundle

from ._shared import _climate_context_facts, _frp_tier, _round_sig



def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a pure-facts StoryBundle for a fire signal."""

    # FIRMS returns FRP at two-decimal precision (e.g. 480.34 MW). The fact-
    # check prompt requires exact numerical match with no tolerance, so the
    # writer rounding "480.34" → "480 MW" or "480.3 MW" produces a BUNDLE_FACT
    # kill against the raw value. Round at the bundle builder so the bundle
    # is the 1-decimal source of truth — writer echoes the clean value,
    # fact-checker confirms exact match. See IMPROVEMENT_PLAN.md P2 +
    # tests/two_bot/test_intern.py::test_build_fire_bundle_rounds_frp_to_one_decimal.
    frp_rounded = round(fire.frp, 1)
    tier_label, tier_floor = _frp_tier(frp_rounded)

    bundle = StoryBundle(
        signal_kind="fire",
        where=fire.nearest_city or fire.country,
        when=date.today().isoformat(),
        event_id=fire.event_id,
        headline_metric={"label": "FRP", "value": frp_rounded, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": fire.confidence, "unit": "%"},
            {"label": "country", "value": fire.country},
            {"label": "nearest_region", "value": fire.nearest_city},
            {"label": "lat", "value": fire.lat},
            {"label": "lon", "value": fire.lon},
            {"label": "frp_tier", "value": tier_label},
            {"label": "frp_tier_floor_mw", "value": tier_floor},
            *_climate_context_facts(fire.lat, fire.lon, category="fire"),
        ],
        historical_context={},
        raw_signal_dump={
            "lat": fire.lat,
            "lon": fire.lon,
            "confidence": fire.confidence,
            "frp": frp_rounded,
            "nearest_city": fire.nearest_city,
            "country": fire.country,
            "event_id": fire.event_id,
        },
    )
    # R-02: a fire served by the NOAA HMS witness during a FIRMS outage carries
    # honest provenance. observed_alt_host = a real observation from an independent
    # host/instrument (treat as observed; note the alternate source). The grade is
    # a current_facts entry the writer/fact-check prompts already honor (R-00).
    if fire.source_leg == "noaa_hms":
        bundle.current_facts.append({"label": "evidence_grade", "value": "observed_alt_host"})
        bundle.current_facts.append(
            {"label": "data_source", "value": "NOAA HMS (GOES/VIIRS, analyst-reviewed) — FIRMS backup feed"}
        )
    return bundle


def build_fire_footprint_bundle(fc: FireComplex) -> StoryBundle:
    """A wildfire perimeter has crossed a tier threshold (acreage)."""

    where = f"{fc.region}, {fc.country}" if fc.region and fc.country else (fc.region or fc.country)
    name = fc.name or "Unnamed complex"
    tier_hectares = (
        TIERS_HECTARES[min(fc.tier, len(TIERS_HECTARES) - 1)]
        if fc.tier >= 0 and TIERS_HECTARES
        else None
    )
    return StoryBundle(
        signal_kind="fire_footprint",
        where=where or "Unknown",
        when=date.today().isoformat(),
        event_id=fc.event_id,
        headline_metric={
            "label": "burned_area_ha",
            "value": fc.hectares,
            "unit": "hectares",
        },
        current_facts=[
            {"label": "complex_name", "value": name},
            {"label": "region", "value": fc.region},
            {"label": "country", "value": fc.country},
            {"label": "hectares", "value": fc.hectares},
            {"label": "tier", "value": fc.tier},
            {"label": "tier_hectares", "value": tier_hectares, "unit": "hectares"},
            {"label": "start_date", "value": fc.start_date.isoformat() if fc.start_date else None},
            # Pre-computed "about"-citable area equivalents (the value_f /
            # value_rounded_c pattern): the writer cites these verbatim with
            # an approximation marker instead of converting hectares itself.
            {"label": "area_km2_approx", "value": round(fc.hectares / 100.0), "unit": "km²"},
            {
                "label": "area_acres_approx",
                "value": _round_sig(fc.hectares * 2.47105),
                "unit": "acres",
            },
        ],
        historical_context={},
        raw_signal_dump={
            "complex_id": fc.complex_id,
            "name": fc.name,
            "country": fc.country,
            "region": fc.region,
            "hectares": fc.hectares,
            "start_date": fc.start_date.isoformat() if fc.start_date else None,
            "tier": fc.tier,
            "tier_hectares": tier_hectares,
            "event_id": fc.event_id,
        },
    )
