"""Local scientific graphic contract; no renderer, network or publishing imports.

Validation establishes an exact evidence binding and structural claim limits.
It is not source verification or posting approval. Production adapters must
supply the expected hash from the reviewed evidence, never from edited media.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import json
from urllib.parse import urlparse

from src.editorial.revisions import fingerprint

TEMPLATE_VERSION = "p31-preview-1"
TEMPLATES = frozenset({"temperature_comparator", "temperature_trajectory"})
VARIABLE_LABELS = {"daily_maximum_temperature": "Daily maximum temperature",
                   "daily_minimum_temperature": "Daily minimum temperature"}
WIDTH, HEIGHT = 1200, 675


def _text(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"Invalid {name}")
    return value


def _time(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Valid times require a timezone-qualified ISO timestamp") from exc


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Temperatures must be finite numbers, never missing-value substitutes")
    return value


def _source(source, synthetic):
    if not isinstance(source, dict):
        raise ValueError("Every series requires source provenance")
    _text(source.get("product"), "source product", 70)
    url = _text(source.get("url"), "source URL", 250)
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in url):
        raise ValueError("Invalid source URL")
    if not synthetic and parsed.hostname.endswith(".invalid"):
        raise ValueError("Synthetic source URLs cannot represent real evidence")
    revision = source.get("revision_sha256")
    if not isinstance(revision, str) or len(revision) != 64 or any(c not in "0123456789abcdef" for c in revision):
        raise ValueError("Source revision fingerprint required")


def _point(point, evidence):
    if not isinstance(point, dict):
        raise ValueError("Missing point evidence")
    _number(point.get("value"))
    if point.get("unit") != evidence["unit"]:
        raise ValueError("Mismatched units; conversions require a separate reviewed evidence revision")
    if point.get("evidence_type") not in {"observed", "forecast", "reanalysis"}:
        raise ValueError("Declare observed, forecast or reanalysis evidence explicitly")
    _source(point.get("source"), evidence["synthetic"])
    return _time(point.get("valid_time"))


def validate_graphic(template, evidence, *, expected_evidence_sha256):
    if template not in TEMPLATES:
        raise ValueError("Unknown graphic template")
    if not isinstance(evidence, dict) or type(evidence.get("schema_version")) is not int or evidence.get("schema_version") != 1:
        raise ValueError("Unsupported graphic evidence schema")
    try:
        encoded = json.dumps(evidence, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > 1_000_000:
            raise ValueError("Evidence packet exceeds local preview bound")
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError("Evidence must be bounded finite JSON") from exc
    if fingerprint(evidence) != expected_evidence_sha256:
        raise ValueError("Graphic evidence differs from the expected review binding")
    if type(evidence.get("synthetic")) is not bool:
        raise ValueError("Synthetic status must be explicit")
    for key, limit in (("event_id", 120), ("location", 45), ("scope", 105)):
        _text(evidence.get(key), key, limit)
    if evidence.get("variable") not in VARIABLE_LABELS:
        raise ValueError("Unsupported temperature variable; this prototype supports daily maximum/minimum only")
    if evidence.get("unit") not in {"°C", "°F"}:
        raise ValueError("Supported temperature units are °C or °F")
    points = evidence.get("points")
    if not isinstance(points, list) or not points or len(points) > 8:
        raise ValueError("Provide one to eight explicit temperature points")
    times = [_point(point, evidence) for point in points]
    as_of = _time(evidence.get("evidence_as_of"))
    for point, valid in zip(points, times):
        if point["evidence_type"] != "forecast" and valid > as_of:
            raise ValueError("Observed/reanalysis values cannot occur after the evidence cutoff")
        if point["evidence_type"] == "forecast" and valid <= as_of:
            raise ValueError("This preview supports forecasts valid after the evidence cutoff")
    if any(left >= right for left, right in zip(times, times[1:])):
        raise ValueError("Trajectory times must be unique and strictly increasing")
    types = [point["evidence_type"] for point in points]
    if "reanalysis" in types and len(set(types)) > 1:
        raise ValueError("This prototype cannot combine reanalysis with another trajectory class")
    if "forecast" in types and any(kind != "forecast" for kind in types[types.index("forecast"):]):
        raise ValueError("An observed value cannot follow the forecast segment")
    if template == "temperature_comparator":
        if len(points) != 1:
            raise ValueError("Comparator template requires one candidate point")
        baseline = evidence.get("baseline")
        if not isinstance(baseline, dict) or baseline.get("complete") is not True:
            raise ValueError("Incomplete comparators cannot be plotted as an archive extreme")
        _text(baseline.get("scope"), "baseline scope", 100)
        count, expected = baseline.get("sample_count"), baseline.get("expected_count")
        if type(count) is not int or type(expected) is not int or count <= 0 or count != expected:
            raise ValueError("Comparator coverage must be explicit and complete")
        start, cutoff = _time(baseline.get("start")), _time(baseline.get("cutoff"))
        if not start <= cutoff < times[0]:
            raise ValueError("Comparator cutoff must precede candidate valid time")
        comparator = baseline.get("point")
        if not isinstance(comparator, dict):
            raise ValueError("Missing comparator point evidence")
        observed = _point(comparator, evidence)
        if comparator["evidence_type"] == "forecast" or not start <= observed <= cutoff <= as_of:
            raise ValueError("Comparator must be an observed/reanalysis point inside its stated interval")
    elif len(points) < 2 or evidence.get("baseline") is not None:
        raise ValueError("Trajectory requires two to eight points and no implied record comparator")
    return deepcopy(evidence)


def chart_title(template, evidence):
    if template == "temperature_trajectory":
        return VARIABLE_LABELS[evidence["variable"]] + " trajectory"
    point = evidence["points"][0]
    return f"{point['value']:g}{point['unit']} {point['evidence_type']}"


def build_alt_text(template, evidence):
    prefix = "SYNTHETIC DEMONSTRATION; no actual weather. " if evidence["synthetic"] else ""
    rows = [f"{p['valid_time']}: {p['value']:g}{p['unit']} {p['evidence_type']} ({p['source']['product']})" for p in evidence["points"]]
    text = prefix + f"{chart_title(template, evidence)} for {evidence['location']}. Variable: {VARIABLE_LABELS[evidence['variable']]}. Scope: {evidence['scope']}. Evidence as of {evidence['evidence_as_of']}. " + "; ".join(rows) + "."
    if template == "temperature_comparator":
        baseline, candidate = evidence["baseline"], evidence["points"][0]
        prior = baseline["point"]
        text += (f" Comparator: {prior['value']:g}{prior['unit']} {prior['evidence_type']} on {prior['valid_time']} "
                 f"from {prior['source']['product']}. {baseline['scope']}; complete {baseline['sample_count']} samples "
                 f"from {baseline['start']} through {baseline['cutoff']}. Difference {candidate['value'] - prior['value']:+g}{prior['unit']}. "
                 "This dated comparison does not establish an official or unrestricted record.")
    return text
