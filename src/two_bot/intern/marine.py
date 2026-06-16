"""Marine two-bot intern builders."""



from __future__ import annotations



from dataclasses import asdict

from datetime import date
from typing import Any

from src.data.coral_dhw import CoralBleachingEvent

from src.data.ice_mass import IceMassRecord

from src.data.ocean import ExtremeWaveEvent

from src.data.ocean_sst_anomaly import RegionalSSTAnomalyEvent

from src.data.ocean_sst import MarineHeatwaveStreakEvent
from src.data.reef_context import reef_context_facts

from src.data.sea_ice import SeaIceRecord

from src.two_bot.types import StoryBundle

from ._shared import _climate_context_facts



def build_coral_bleaching_bundle(event: CoralBleachingEvent) -> StoryBundle:
    """A Coral Reef Watch region crossed a DHW bleaching threshold."""
    current_facts: list[dict[str, Any]] = [
        {"label": "region_id", "value": event.region_id},
        {"label": "region_full_name", "value": event.region_full_name},
        {"label": "dhw_value", "value": event.dhw_value, "unit": "°C-weeks"},
        {"label": "dhw_tier", "value": event.dhw_tier, "unit": "°C-weeks"},
        {"label": "bleaching_level", "value": event.bleaching_level},
        {"label": "stress_level", "value": event.stress_level},
        {"label": "source_name", "value": event.source_name},
        {"label": "lat", "value": event.lat},
        {"label": "lon", "value": event.lon},
        *_climate_context_facts(event.lat, event.lon, category="coral"),
        *reef_context_facts(event.region_id),
    ]
    if event.source_leg == "crw_erddap":
        current_facts.extend([
            {"label": "data_source", "value": "NOAA Coral Reef Watch ERDDAP DHW grid"},
            {"label": "evidence_grade", "value": "observed_alt_host"},
        ])

    return StoryBundle(
        signal_kind="coral_bleaching",
        where=event.region_full_name,
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "DHW",
            "value": event.dhw_value,
            "unit": "°C-weeks",
        },
        current_facts=current_facts,
        historical_context={
            "scope": "coral_reef_watch_regional_dhw_threshold",
            "thresholds_c_weeks": [4, 8, 12],
        },
        raw_signal_dump=asdict(event),
    )

def build_sea_ice_bundle(record: SeaIceRecord) -> StoryBundle:
    """A polar sea-ice extent reading set a new record."""
    current_facts: list[dict[str, Any]] = [
        {"label": "hemisphere", "value": record.hemisphere},
        {"label": "extent_million_km2", "value": record.extent_million_km2},
        {"label": "record_type", "value": record.record_type},
        {"label": "date", "value": record.date},
    ]
    if record.source_leg == "osi_saf":
        current_facts.extend([
            {"label": "data_source", "value": "OSI SAF sea-ice concentration grid"},
            {"label": "evidence_grade", "value": "observed_alt_host"},
        ])

    return StoryBundle(
        signal_kind="sea_ice_record",
        where=f"{record.hemisphere} hemisphere",
        when=record.date,
        event_id=record.event_id,
        headline_metric={
            "label": "extent_million_km2",
            "value": record.extent_million_km2,
            "unit": "million_km2",
        },
        current_facts=current_facts,
        historical_context={
            "previous_extent": record.previous_extent,
            "previous_year": record.previous_year,
            "scope": f"satellite_archive_{record.record_type}",
        },
        raw_signal_dump=asdict(record),
    )

def build_ice_mass_bundle(
    record: IceMassRecord,
    *,
    years_of_record: int | None = None,
    archive_start_year: int | None = None,
) -> StoryBundle:
    """GRACE ice mass loss / cumulative milestone for a polar region."""

    return StoryBundle(
        signal_kind="ice_mass_record",
        where=record.region,
        when=date.today().isoformat(),
        event_id=record.event_id,
        headline_metric={
            "label": "monthly_delta_gt" if record.monthly_delta_gt is not None else "current_mass_gt",
            "value": record.monthly_delta_gt if record.monthly_delta_gt is not None else record.current_mass_gt,
            "unit": "Gt",
        },
        current_facts=[
            {"label": "region", "value": record.region},
            {"label": "kind", "value": record.kind},
            {"label": "month", "value": record.month},
            {"label": "monthly_delta_gt", "value": record.monthly_delta_gt},
            {"label": "current_mass_gt", "value": record.current_mass_gt},
            {"label": "years_of_record", "value": years_of_record},
        ],
        historical_context={
            "previous_worst_gt": record.previous_worst_gt,
            "previous_worst_month": record.previous_worst_month,
            "threshold_gt": record.threshold_gt,
            "years_of_record": years_of_record,
            "archive_start_year": archive_start_year,
            "scope": "grace_satellite_archive",
        },
        raw_signal_dump=asdict(record),
    )

def build_marine_heatwave_bundle(mhw: MarineHeatwaveStreakEvent) -> StoryBundle:
    """A streak milestone in the global ocean SST anomaly record."""

    return StoryBundle(
        signal_kind="marine_heatwave",
        where="Global ocean (60°S–60°N)",
        when=mhw.date,
        event_id=mhw.event_id,
        headline_metric={
            "label": "streak_days",
            "value": mhw.days,
            "unit": "days",
        },
        current_facts=[
            {"label": "kind", "value": mhw.kind},
            {"label": "streak_days", "value": mhw.days},
            {"label": "today_c", "value": mhw.today_c},
            {"label": "peak_anomaly_c", "value": mhw.peak_anomaly_c},
        ],
        historical_context={
            "archive_max_c": mhw.archive_max_c,
            "archive_max_year": mhw.archive_max_year,
            "archive_years": mhw.years_of_data,
            "scope": "noaa_oisst_global_archive",
        },
        raw_signal_dump=asdict(mhw),
    )

def build_regional_sst_anomaly_bundle(event: RegionalSSTAnomalyEvent) -> StoryBundle:
    """A per-region SST anomaly event bundle."""
    current_facts: list[dict[str, Any]] = [
        {"label": "region_slug", "value": event.region_slug},
        {"label": "region_display_name", "value": event.region_display_name},
        {"label": "anomaly_c", "value": round(event.anomaly_c, 2), "unit": "°C"},
        {"label": "tier", "value": event.tier},
        {"label": "tier_threshold_c", "value": [2.5, 3.5, 4.5][event.tier - 1]},
        {
            "label": "spatial_aggregation",
            "value": "cos-latitude area-weighted basin mean",
        },
        {"label": "grid_cells_used", "value": event.cells_used},
        {"label": "anomaly_basis", "value": "NOAA CRW published 5km SST anomaly"},
        {
            "label": "signal_note",
            "value": (
                "Absolute area-weighted-mean anomaly vs CRW climatology. "
                "NOT a Hobday duration/percentile MHW classification."
            ),
        },
    ]
    if event.source_leg == "noaa_star_nc":
        current_facts.extend([
            {"label": "data_source", "value": "NOAA STAR CRW SST anomaly NetCDF"},
            {"label": "evidence_grade", "value": "observed_alt_host"},
        ])

    return StoryBundle(
        signal_kind="regional_sst_anomaly",
        where=event.region_display_name,
        when=event.date,
        event_id=event.event_id,
        headline_metric={
            "label": "sst_anomaly_c",
            "value": round(event.anomaly_c, 2),
            "unit": "°C",
        },
        current_facts=current_facts,
        historical_context={
            "scope": "noaa_crw_regional_sst_anomaly",
            "source": (
                "NOAA Coral Reef Watch Daily Global 5km SST Anomaly "
                "(ERDDAP noaacrwsstanomalyDaily)"
            ),
            "spatial_aggregation": "cos-latitude area-weighted basin mean",
            "tier_thresholds": [2.5, 3.5, 4.5],
        },
        raw_signal_dump=asdict(event),
    )

def build_extreme_wave_bundle(wave: ExtremeWaveEvent) -> StoryBundle:
    """Open-Meteo marine forecast shows extreme wave heights."""

    where = f"{wave.location} ({wave.ocean})" if wave.ocean else wave.location
    return StoryBundle(
        signal_kind="extreme_wave",
        where=where,
        when=wave.date,
        event_id=wave.event_id,
        headline_metric={
            "label": "wave_height_m",
            "value": wave.wave_height_m,
            "unit": "m",
        },
        current_facts=[
            {"label": "location", "value": wave.location},
            {"label": "ocean", "value": wave.ocean},
            {"label": "wave_height_m", "value": wave.wave_height_m},
        ],
        historical_context={},
        raw_signal_dump=asdict(wave),
    )
