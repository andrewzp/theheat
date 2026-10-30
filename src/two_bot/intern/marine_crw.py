"""NOAA CRW regional SST anomaly bundle builders (moved verbatim from marine.py).

``src.two_bot.intern.marine`` re-exports these exact functions.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.data.crw_regions import RegionalSSTAnomalyEvent
from src.two_bot.types import StoryBundle


def build_regional_sst_anomaly_bundle(event: RegionalSSTAnomalyEvent) -> StoryBundle:
    """Current individual regional evidence, including qualified native climatology."""
    return _regional_sst_anomaly_bundle(event, legacy_snapshot=False)


def legacy_regional_sst_anomaly_snapshot(event: RegionalSSTAnomalyEvent) -> StoryBundle:
    """Reconstruct the exact pre-climatology bundle for retained v1 graphics only.

    This does not migrate an old snapshot, check or approval to current policy.
    Preserve even the historical ERDDAP label; new native evidence corrects it.
    """
    return _regional_sst_anomaly_bundle(event, legacy_snapshot=True)


def _regional_sst_anomaly_bundle(
    event: RegionalSSTAnomalyEvent, *, legacy_snapshot: bool
) -> StoryBundle:
    from src.data.crw_contract import qualified_provenance, reference_climatology, PRODUCT_NAME, METHOD

    raw = asdict(event)
    retained_packet = raw.pop("retained_packet", None)
    if retained_packet is not None:  # Absent otherwise: unretained bundles are unchanged.
        raw["retained_packet"] = retained_packet
    supplied_provenance = raw.pop("provenance", None)
    qualified = qualified_provenance(event)
    if qualified:
        raw["provenance"] = supplied_provenance
    elif supplied_provenance is not None:
        # Preserve the rejected record, without presenting it as primary evidence.
        raw["unqualified_provenance"] = supplied_provenance
    current_facts: list[dict[str, Any]] = [
        {"label": "region_slug", "value": event.region_slug},
        {"label": "region_display_name", "value": event.region_display_name},
        {"label": "anomaly_c", "value": round(event.anomaly_c, 2), "unit": "°C"},
        {"label": "tier", "value": event.tier},
        {"label": "tier_threshold_c", "value": [2.5, 3.5, 4.5][event.tier - 1]},
        {
            "label": "spatial_aggregation",
            "value": METHOD,
        },
        {"label": "grid_cells_used", "value": event.cells_used},
        {"label": "anomaly_basis", "value": "NOAA CRW published 5km SST anomaly relative to its daily climatology"},
        {
            "label": "signal_note",
            "value": (
                "Sampled regional mean of the CRW daily satellite-analysis anomaly. "
                "The product timestamp is not a verified measurement interval. "
                "Not a historical record or a Hobday duration/percentile MHW classification."
            ),
        },
    ]
    if qualified:
        current_facts.extend([
            {"label": "data_source", "value": PRODUCT_NAME},
            {"label": "evidence_grade", "value": "satellite_analysis"},
            {"label": "source_leg", "value": supplied_provenance["source_leg"]},
            {"label": "sample_cells_total", "value": supplied_provenance["total_cells"]},
            {"label": "sample_cells_excluded", "value": supplied_provenance["excluded_cells"]},
        ])

    history: dict[str, Any] = {
        "scope": "noaa_crw_regional_sst_anomaly",
        "source": (
            "NOAA Coral Reef Watch Daily Global 5km SST Anomaly "
            "(ERDDAP noaacrwsstanomalyDaily)"
        ),
        "spatial_aggregation": METHOD,
        "tier_thresholds": [2.5, 3.5, 4.5],
    }
    if qualified and not legacy_snapshot:
        history["source"] = PRODUCT_NAME
        history["reference_climatology"] = reference_climatology(event)

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
        historical_context=history,
        raw_signal_dump=raw,
    )
