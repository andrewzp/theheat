"""Stage 1: deterministic fire story-bundle assembly."""

from datetime import date

from src.data.firms import FireEvent
from src.two_bot.types import StoryBundle


def build_fire_bundle(fire: FireEvent) -> StoryBundle:
    """Assemble a pure-facts StoryBundle for a fire signal."""

    return StoryBundle(
        signal_kind="fire",
        where=fire.nearest_city or fire.country,
        when=date.today().isoformat(),
        event_id=fire.event_id,
        headline_metric={"label": "FRP", "value": fire.frp, "unit": "MW"},
        current_facts=[
            {"label": "satellite_confidence", "value": fire.confidence, "unit": "%"},
            {"label": "country", "value": fire.country},
            {"label": "nearest_region", "value": fire.nearest_city},
            {"label": "lat", "value": fire.lat},
            {"label": "lon", "value": fire.lon},
        ],
        historical_context={},
        raw_signal_dump={
            "lat": fire.lat,
            "lon": fire.lon,
            "confidence": fire.confidence,
            "frp": fire.frp,
            "nearest_city": fire.nearest_city,
            "country": fire.country,
            "event_id": fire.event_id,
        },
    )

