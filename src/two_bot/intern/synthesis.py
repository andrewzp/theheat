"""Synthesis two-bot intern builders."""



from __future__ import annotations



from datetime import date

from src.two_bot.types import StoryBundle



def build_synthesis_bundle(synthesis: dict) -> StoryBundle:
    """Cross-source compound story (e.g. fire + drought + heat in one region).

    ``synthesis`` is the dict main.py builds from the cross-source scorer
    (region, kind, components, total_score, event_id, headline).
    """

    components = synthesis.get("components") or []
    return StoryBundle(
        signal_kind=f"synthesis_{synthesis.get('kind', 'compound')}",
        where=synthesis.get("region", "Unknown"),
        when=date.today().isoformat(),
        event_id=synthesis.get("event_id", ""),
        headline_metric={
            "label": "synthesis_score",
            "value": synthesis.get("total_score"),
        },
        current_facts=[
            {"label": "region", "value": synthesis.get("region")},
            {"label": "synthesis_kind", "value": synthesis.get("kind")},
            {"label": "component_count", "value": len(components)},
            {"label": "components", "value": components},
        ],
        historical_context={
            "scope": "cross_source_synthesis",
            "synthesis_kind": synthesis.get("kind"),
        },
        raw_signal_dump=synthesis,
    )
