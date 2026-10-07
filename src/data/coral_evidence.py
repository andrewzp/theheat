"""Limits of the DHW-only point backup, not qualification of coral impacts."""

from __future__ import annotations

from typing import Any

DHW_ONLY_STRESS_LEVEL = "Unavailable: HotSpot and bleaching alert data were not retrieved"
DHW_POINT_SOURCE = "NOAA Coral Reef Watch ERDDAP DHW point sample"
DHW_POINT_SCOPE = "Single grid point; not a regional virtual-station statistic"
DHW_ONLY_LIMIT = (
    "DHW measures accumulated heat stress over the preceding 12 weeks. "
    "DHW alone does not establish a current bleaching alert class, No Stress, "
    "observed bleaching or mortality. Current alert classification needs HotSpot "
    "and DHW together; a seven-day alert maximum is a separate product."
)


def _facts(bundle: Any) -> list[dict]:
    return [f for f in bundle.current_facts if isinstance(f, dict)] if isinstance(bundle.current_facts, list) else []


def is_dhw_only_bundle(bundle: Any) -> bool:
    if bundle.signal_kind != "coral_bleaching":
        return False
    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    return raw.get("source_leg") == "crw_erddap" or any(
        f.get("label") == "data_source"
        and f.get("value") in (DHW_POINT_SOURCE, "NOAA Coral Reef Watch ERDDAP DHW grid")
        for f in _facts(bundle)
    )


def dhw_only_bundle_failures(bundle: Any) -> list[str]:
    """Do not let a retained or altered inferred label reach the writer as fact."""
    if not is_dhw_only_bundle(bundle):
        return []
    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    required = {
        "stress_level": DHW_ONLY_STRESS_LEVEL,
        "data_source": DHW_POINT_SOURCE,
        "evidence_grade": "satellite_analysis",
        "sample_scope": DHW_POINT_SCOPE,
        "bleaching_alert_status": "unavailable",
        "claim_limit": DHW_ONLY_LIMIT,
    }
    if (
        raw.get("source_leg") != "crw_erddap"
        or raw.get("stress_level") != DHW_ONLY_STRESS_LEVEL
        or raw.get("baa_7day_max") is not None
        or any([f.get("value") for f in _facts(bundle) if f.get("label") == k] != [v] for k, v in required.items())
    ):
        return ["DHW-only backup must retain unknown alert status and its point-sample limits"]
    return []
