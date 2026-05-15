"""Atmospheric two-bot intern builders."""



from __future__ import annotations



from dataclasses import asdict

from datetime import date

from src.data.climate_indices import (
    OscillationAlignmentEvent,
    OscillationExtremeEvent,
    OscillationTransition,
)
from src.data.co2 import CO2Milestone

from src.data.methane import MethaneMilestone
from src.data.ozone_hole import OzoneHoleSeasonalEvent

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

def build_oscillation_bundle(
    event: OscillationTransition | OscillationExtremeEvent | OscillationAlignmentEvent,
) -> StoryBundle:
    """Climate-mode index transition, extreme, or NAO/AO alignment."""

    if isinstance(event, OscillationTransition):
        when = date(event.year, event.month, 1).isoformat()
        return StoryBundle(
            signal_kind="oscillation_transition",
            where=event.full_name,
            when=when,
            event_id=event.event_id,
            headline_metric={
                "label": "index_value",
                "value": event.value,
                "unit": "index",
            },
            current_facts=[
                {"label": "index_name", "value": event.index_name},
                {"label": "full_name", "value": event.full_name},
                {"label": "from_phase", "value": event.from_phase},
                {"label": "to_phase", "value": event.to_phase},
                {"label": "value", "value": event.value},
                {"label": "previous_duration_months", "value": event.previous_duration_months},
            ],
            historical_context={
                "scope": "monthly_climate_mode_zero_crossing",
                "anchor_year": event.year,
            },
            raw_signal_dump=asdict(event),
        )

    if isinstance(event, OscillationExtremeEvent):
        when = date(event.year, event.month, 1).isoformat()
        return StoryBundle(
            signal_kind="oscillation_extreme",
            where=event.full_name,
            when=when,
            event_id=event.event_id,
            headline_metric={
                "label": "sigma_excursion",
                "value": event.sigma_excursion,
                "unit": "sigma",
            },
            current_facts=[
                {"label": "index_name", "value": event.index_name},
                {"label": "full_name", "value": event.full_name},
                {"label": "value", "value": event.value},
                {"label": "sigma_excursion", "value": event.sigma_excursion},
                {"label": "comparison_year", "value": event.comparison_year},
            ],
            historical_context={
                "scope": "monthly_climate_mode_extreme",
                "mean": event.mean,
                "stdev": event.stdev,
                "comparison_year": event.comparison_year,
                "comparison_month": event.comparison_month,
            },
            raw_signal_dump=asdict(event),
        )

    when = date(event.year, event.month, 1).isoformat()
    return StoryBundle(
        signal_kind="oscillation_alignment",
        where="North Atlantic / Arctic Oscillation",
        when=when,
        event_id=event.event_id,
        headline_metric={
            "label": "nao_ao_negative_sigma",
            "value": max(event.nao_sigma_excursion, event.ao_sigma_excursion),
            "unit": "sigma",
        },
        current_facts=[
            {"label": "nao_value", "value": event.nao_value},
            {"label": "ao_value", "value": event.ao_value},
            {"label": "nao_sigma_excursion", "value": event.nao_sigma_excursion},
            {"label": "ao_sigma_excursion", "value": event.ao_sigma_excursion},
        ],
        historical_context={"scope": "nao_ao_extreme_negative_alignment"},
        raw_signal_dump=asdict(event),
    )

def build_ozone_hole_bundle(event: OzoneHoleSeasonalEvent) -> StoryBundle:
    """Antarctic ozone hole annual seasonal peak."""

    return StoryBundle(
        signal_kind="ozone_hole_peak",
        where="Antarctic stratosphere",
        when=event.peak_date,
        event_id=event.event_id,
        headline_metric={
            "label": "ozone_hole_area",
            "value": event.area_million_km2,
            "unit": "million km2",
        },
        current_facts=[
            {"label": "peak_date", "value": event.peak_date},
            {"label": "area_million_km2", "value": event.area_million_km2},
            {"label": "previous_year", "value": event.previous_year},
            {"label": "previous_area_million_km2", "value": event.previous_area_million_km2},
            {"label": "larger_than_previous_year", "value": event.larger_than_previous_year},
        ],
        historical_context={
            "scope": "antarctic_ozone_hole_recovery",
            "record_year": event.record_year,
            "record_area_million_km2": event.record_area_million_km2,
            "trailing_10yr_mean_area_million_km2": event.trailing_10yr_mean_area_million_km2,
        },
        raw_signal_dump=asdict(event),
    )
