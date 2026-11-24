"""Read-only projection of one canonical pair of retained AWC observations.

Reconstruction uses the recorded capture clock, never a replacement capture or
a source fetch. Approval and sending still require independent current-source
checks. A valid graphic specification is not source authentication or review.
"""
from __future__ import annotations

from copy import deepcopy
import math
from importlib.resources import files

from src.data import awc_observed, places
from src.editorial.revisions import fingerprint

TEMPLATE = "awc_airport_temperature_pair"
TEMPLATE_VERSION = "p31-awc-airport-pair-2"
ADAPTER_VERSION = "p31-awc-observed-pair-2"
SOURCE = "NOAA Aviation Weather Center"
TITLE = "Two airports. One moment."
SCOPE = "Two reported airport observations; not a national value, record or global ranking."


class AWCGraphicRefused(ValueError):
    pass


def country_registry_bytes():
    """The same public registry as AWC, under its sealed destination identity."""
    resource = files("src.data").joinpath("registry", "country_names.json")
    return resource.read_bytes() if resource.is_file() else (places.DATA / "country_names.json").read_bytes()


def number(value):
    """Preserve the source value; never round a point to match the canvas."""
    return f"{0 if value == 0 else value:g}".replace("-", "−")


def awc_graphic_spec(bundle, *, expected_bundle_sha256, synthetic=False):
    if type(bundle) is not dict or type(synthetic) is not bool:
        raise AWCGraphicRefused("invalid airport graphic input")
    if fingerprint(bundle) != expected_bundle_sha256:
        raise AWCGraphicRefused("the retained airport bundle changed")
    if bundle.get("signal_kind") != awc_observed.KIND:
        raise AWCGraphicRefused("only the retained temperature pair has this graphic")
    try:
        raw = bundle["raw_signal_dump"]["evidence"]
        captured = awc_observed._time(raw["retrieved_at"])
        source = awc_observed.validate_bundle(bundle, now=captured)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise AWCGraphicRefused("the retained airport observations are not qualified") from exc
    points = deepcopy(source["points"])
    values = [point["temperature_c"] for point in points]
    lower = min(0, math.floor(min(values) / 20) * 20)
    upper = max(0, math.ceil(max(values) / 20) * 20)
    evidence = {
        "synthetic": synthetic, "evidence_type": "observed", "source_product": awc_observed.SCHEMA,
        "bundle_sha256": expected_bundle_sha256, "source_sha256": fingerprint(source),
        "points": points, "difference_c": source["difference_c"],
        "observed_at": points[0]["valid_time"], "retrieved_at": source["retrieved_at"],
        "axis": {"min_c": lower, "max_c": upper, "ticks_c": list(range(lower, upper + 1, 20))},
        "scope": SCOPE,
    }
    return {"template": TEMPLATE, "evidence": evidence,
            "expected_evidence_sha256": fingerprint(evidence)}


def source_context(evidence):
    return {"kind": "awc_airport_pair", "observed_at": evidence["observed_at"],
            "retrieved_at": evidence["retrieved_at"], "difference_c": evidence["difference_c"],
            "points": deepcopy(evidence["points"])}


def delivery_text(evidence):
    stations = [f"Airport {letter}: {p['airport']}, {p['country']} ({p['station_id']}), "
                f"{number(p['temperature_c'])}°C" for letter, p in zip("AB", evidence["points"])]
    return (TITLE + " " + "; ".join(stations) + ". Observed "
            + evidence["observed_at"].replace("T", " ").removesuffix("Z") + " UTC. "
            + number(evidence["difference_c"]) + "°C difference. A common linear Celsius axis includes zero. "
            + "Warm and cool colours mark the higher and lower readings in this pair, not hazard categories. "
            + "A/B labels identify the airports. "
            + SOURCE + ". " + SCOPE)


def full_description(evidence):
    return (delivery_text(evidence) + " Source capture: " + evidence["retrieved_at"]
            + ". These are METAR/SPECI air-temperature reports, not forecasts or daily extrema. "
            + "The chart does not establish conditions elsewhere or the completeness of worldwide reporting.")
