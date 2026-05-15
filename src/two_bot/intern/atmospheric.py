"""Atmospheric two-bot intern builders."""



from __future__ import annotations



from dataclasses import asdict

from datetime import date

from src.data.co2 import CO2Milestone

from src.data.methane import MethaneMilestone

from src.two_bot.types import StoryBundle



def build_co2_milestone_bundle(milestone: CO2Milestone) -> StoryBundle:
    """Atmospheric CO2 crossed a round-number threshold."""

    return StoryBundle(
        signal_kind="co2_milestone",
        where="Mauna Loa Observatory",
        when=milestone.date,
        event_id=milestone.event_id,
        headline_metric={
            "label": "ppm",
            "value": milestone.actual_ppm,
            "unit": "ppm",
        },
        current_facts=[
            {"label": "ppm_crossed", "value": milestone.ppm_crossed},
            {"label": "actual_ppm", "value": milestone.actual_ppm},
            {"label": "measurement_date", "value": milestone.date},
        ],
        historical_context={
            "scope": "atmospheric_co2_threshold_crossed",
            "preindustrial_baseline_ppm": 280,
        },
        raw_signal_dump=asdict(milestone),
    )

def build_ch4_milestone_bundle(milestone: MethaneMilestone) -> StoryBundle:
    """Atmospheric methane crossed a round-number threshold."""

    return StoryBundle(
        signal_kind="ch4_milestone",
        where="NOAA GML global marine surface mean",
        when=milestone.date,
        event_id=milestone.event_id,
        headline_metric={
            "label": "ppb_crossed",
            "value": milestone.ppb_crossed,
            "unit": "ppb",
        },
        current_facts=[
            {"label": "ppb_crossed", "value": milestone.ppb_crossed},
            {"label": "actual_ppb", "value": milestone.actual_ppb},
            {"label": "measurement_date", "value": milestone.date},
            {"label": "source_name", "value": milestone.source_name},
        ],
        historical_context={
            "scope": "atmospheric_ch4_threshold_crossed",
            "preindustrial_baseline_ppb": 722,
        },
        raw_signal_dump=asdict(milestone),
    )

def build_enso_bundle(transition: dict) -> StoryBundle:
    """An ENSO phase transition (or significant ONI move).

    ``transition`` is the dict main.py constructs from the latest
    two ENSO readings (status_from, status_to, oni_value, season,
    event_id).
    """

    status_from = transition.get("from_status", transition.get("status_from"))
    status_to = transition.get("to_status", transition.get("status_to"))
    return StoryBundle(
        signal_kind="enso",
        where="Equatorial Pacific (Niño 3.4)",
        when=date.today().isoformat(),
        event_id=transition.get("event_id", ""),
        headline_metric={
            "label": "oni_value",
            "value": transition.get("oni_value"),
            "unit": "C",
        },
        current_facts=[
            {"label": "season", "value": transition.get("season")},
            {"label": "status_from", "value": status_from},
            {"label": "status_to", "value": status_to},
            {"label": "oni_value", "value": transition.get("oni_value")},
            {"label": "previous_duration_months", "value": transition.get("previous_duration_months")},
        ],
        historical_context={"scope": "noaa_oni_3month_running_mean"},
        raw_signal_dump=transition,
    )
