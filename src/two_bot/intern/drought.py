"""Drought two-bot intern builders."""



from __future__ import annotations



from datetime import date

from src.two_bot.types import StoryBundle



def build_drought_bundle(updates: list[dict], *, event_id: str) -> StoryBundle:
    """US Drought Monitor rolled up across affected states.

    ``updates`` is the list of state-level drought dicts main.py
    assembles from DroughtUpdate dataclasses (state, d3_pct, d4_pct,
    total_drought_pct).
    """

    def _severity(row: dict) -> float:
        return float(row.get("d3_pct") or 0) + float(row.get("d4_pct") or 0)

    worst = max(updates, key=_severity) if updates else {}
    worst_value = round(_severity(worst), 1) if worst else 0.0
    return StoryBundle(
        signal_kind="drought",
        where="United States",
        when=date.today().isoformat(),
        event_id=event_id,
        headline_metric={
            "label": "worst_extreme_exceptional_pct",
            "value": worst_value,
            "unit": "%",
        },
        current_facts=[
            {"label": "state_count", "value": len(updates)},
            {"label": "worst_state", "value": worst.get("state")},
            {"label": "worst_d3_pct", "value": worst.get("d3_pct")},
            {"label": "worst_d4_pct", "value": worst.get("d4_pct")},
            {"label": "states", "value": updates},
        ],
        historical_context={"scope": "us_drought_monitor_weekly"},
        raw_signal_dump={"states": updates, "event_id": event_id},
    )
