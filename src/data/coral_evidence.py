"""Limits of the DHW-only point backup, not qualification of coral impacts."""

from __future__ import annotations

from typing import Any
import json
import re

REGIONAL_SCOPE = "Regional virtual-station statistic; coordinates are a map marker, not a sampled pixel"
REGIONAL_LIMIT = (
    "DHW is regional 90th-percentile HotSpot accumulation over the preceding 12 weeks. "
    "The supplied BAA is a seven-day maximum on the heritage 0-to-4 scale, not a current "
    "daily class or the expanded Alert Levels 3-to-5 product. Neither measurement proves "
    "observed bleaching or mortality. Marker coordinates do not define a sampled pixel."
)

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
    provenance = raw.get("provenance")
    identified_receipt = isinstance(provenance, dict) and (
        provenance.get("source_leg") == "crw_erddap" or provenance.get("source_product") == "noaa-crw-dhw-v3.1"
    )
    return identified_receipt or raw.get("source_leg") == "crw_erddap" or any(
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
    return _point_binding_failures(bundle)


def _point_binding_failures(bundle: Any) -> list[str]:
    from src.data.coral_dhw import CoralBleachingEvent, _tier_for_dhw
    from src.data.coral_source_contract import qualified_provenance
    from src.two_bot.intern.marine import build_coral_bleaching_bundle

    try:
        event = CoralBleachingEvent(**bundle.raw_signal_dump)
        if not qualified_provenance(event):
            raise ValueError
        tier, level = _tier_for_dhw(event.dhw_value)
        if (
            tier is None or type(event.dhw_tier) is not int or event.dhw_tier != tier
            or event.bleaching_level != level
            or event.event_id != f"coral_dhw_{event.region_id}_tier{tier}"
        ):
            raise ValueError
        expected = build_coral_bleaching_bundle(event)
        for key in ("where", "when", "event_id", "headline_metric", "current_facts", "historical_context", "raw_signal_dump"):
            if json.dumps(getattr(bundle, key), sort_keys=True, allow_nan=False) != json.dumps(getattr(expected, key), sort_keys=True, allow_nan=False):
                raise ValueError
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, OverflowError):
        return ["DHW point evidence must match its qualified source receipt, measurement and threshold"]
    return []


def regional_bundle_failures(bundle: Any) -> list[str]:
    """Every non-point coral bundle must carry an intact primary warrant."""
    if bundle.signal_kind != "coral_bleaching" or is_dhw_only_bundle(bundle):
        return []
    from src.data.coral_dhw import CoralBleachingEvent, _tier_for_dhw
    from src.data.coral_regional_contract import qualified_provenance
    from src.two_bot.intern.marine import build_coral_bleaching_bundle

    try:
        event = CoralBleachingEvent(**bundle.raw_signal_dump)
        if not qualified_provenance(event):
            raise ValueError
        tier, level = _tier_for_dhw(event.dhw_value)
        if tier is None or type(event.dhw_tier) is not int or event.dhw_tier != tier or event.bleaching_level != level or event.event_id != f"coral_dhw_{event.region_id}_tier{tier}":
            raise ValueError
        expected = build_coral_bleaching_bundle(event)
        for key in ("where", "when", "event_id", "headline_metric", "current_facts", "historical_context", "raw_signal_dump"):
            if json.dumps(getattr(bundle, key), sort_keys=True, allow_nan=False) != json.dumps(getattr(expected, key), sort_keys=True, allow_nan=False):
                raise ValueError
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError, OverflowError):
        return ["Regional coral evidence must match its qualified source receipt, measurement and threshold"]
    return []


_ALERT_LABEL = re.compile(
    r"\b(?:no stress|bleaching (?:watch|warning)|"
    r"(?:bleaching )?(?:alert(?: level)?|level)[ \t]*[:=]?[ \t]*"
    r"(?:\d+|[ivx]+|zero|one|two|three|four|five|six|seven|eight|nine|ten))\b",
    re.IGNORECASE,
)
_ALERT_PREFIX = re.compile(r"\b(?:7|seven) day (?:maximum|max|peak)(?: (?:was|is|of)|[ \t]*:)[ \t]*\Z", re.IGNORECASE)


def regional_alert_failures(tweet: str, bundle: Any) -> list[str]:
    if bundle.signal_kind != "coral_bleaching" or is_dhw_only_bundle(bundle):
        return []
    # Horizontal normalization must not connect a label to a different clause.
    text = re.sub(r"[ \t\u00a0\-\u2010-\u2015\u2212]+", " ", tweet.lower())
    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    code = raw.get("baa_7day_max")
    for match in _ALERT_LABEL.finditer(text):
        label = match.group()
        if label in ("no stress", "bleaching watch", "bleaching warning"):
            expected = ("no stress", "bleaching watch", "bleaching warning").index(label)
        else:
            suffix = re.search(r"(\d+|[ivx]+|zero|one|two|three|four|five|six|seven|eight|nine|ten)$", label)
            level = suffix.group() if suffix else ""
            expected = 3 if level in ("1", "i", "one") else 4 if level in ("2", "ii", "two") else None
        if expected is None or type(code) is not int or code != expected or _ALERT_PREFIX.search(text[:match.start()]) is None:
            return ["Regional coral alert labels require the matching supplied heritage seven-day maximum and an adjacent window qualifier"]
    return []
