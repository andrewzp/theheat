"""Local graphic projection of retained NOAA point forecasts."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from src.data.nwps_major_forecasts import verify_major_forecast
from src.editorial.revisions import fingerprint
from src.media.temperature_graphic_adapter import story_bundle_snapshot
from src.two_bot.intern.nwps_forecast import build_nwps_forecast_bundle

TEMPLATE = "nwps_river_forecast"
TEMPLATE_VERSION = "p31-nwps-river-1"
ADAPTER_VERSION = "p31-nwps-point-series-1"


def _project(bundle, capture, *, expected_bundle_sha256, expected_capture_sha256):
    if fingerprint(bundle) != expected_bundle_sha256 or fingerprint(capture) != expected_capture_sha256:
        raise ValueError("NWPS review binding changed")
    try:
        synthetic = capture["synthetic"]
        if type(synthetic) is not bool:
            raise ValueError("Synthetic status must be explicit")
        checked_at = datetime.fromisoformat(capture["checked_at"])
        if checked_at.utcoffset() is None:
            raise ValueError("NWPS capture requires a timezone")
        checked_at = checked_at.astimezone(timezone.utc)
        series = capture["forecast"]
        event = verify_major_forecast(bundle["raw_signal_dump"]["nwps_index_hint"],
                                      capture["metadata"], series, checked_at)
        rebuilt = story_bundle_snapshot(build_nwps_forecast_bundle(event))
        if fingerprint(rebuilt) != expected_bundle_sha256:
            raise ValueError("NWPS point forecast disagrees with the story bundle")
        if len(series["data"]) < 2:
            raise ValueError("NWPS chart requires at least two supplied points")
        return {
            "schema_version": 1,
            "synthetic": synthetic,
            "event_id": rebuilt["event_id"],
            "location": rebuilt["where"],
            "gauge": event.lid,
            "scope": "NOAA/NWS issued forecast at one gauge. Crossing time is uncertain.",
            "unit": "ft",
            "evidence_as_of": checked_at.isoformat(),
            "issued_at": event.issued_at.isoformat(),
            "first_major_at": event.first_major_at.isoformat(),
            "first_major_ft": event.forecast_ft,
            "major_threshold_ft": event.major_threshold_ft,
            "source_url": rebuilt["raw_signal_dump"]["source_url"],
            "points": [{"valid_time": row["validTime"], "value": float(row["primary"])}
                       for row in series["data"]],
            "input_binding": {
                "adapter_version": ADAPTER_VERSION,
                "bundle_sha256": expected_bundle_sha256,
                "capture_sha256": expected_capture_sha256,
                "bundle": deepcopy(bundle),
                "capture": deepcopy(capture),
            },
        }
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("NWPS graphic source evidence is incomplete") from exc


def nwps_graphic_spec(bundle, capture, *, expected_bundle_sha256, expected_capture_sha256):
    """Bind chart data to a caller's retained story and point forecast hashes."""
    from src.media.evidence_graphic import validate_graphic

    evidence = _project(bundle, capture, expected_bundle_sha256=expected_bundle_sha256,
                        expected_capture_sha256=expected_capture_sha256)
    expected = fingerprint(evidence)
    return {"template": TEMPLATE, "expected_evidence_sha256": expected,
            "evidence": validate_graphic(TEMPLATE, evidence, expected_evidence_sha256=expected)}


def validate_nwps_adapter_binding(evidence):
    try:
        binding = evidence["input_binding"]
        expected = _project(binding["bundle"], binding["capture"],
                            expected_bundle_sha256=binding["bundle_sha256"],
                            expected_capture_sha256=binding["capture_sha256"])
    except (KeyError, TypeError) as exc:
        raise ValueError("NWPS graphic binding is incomplete") from exc
    if fingerprint(evidence) != fingerprint(expected):
        raise ValueError("NWPS graphic differs from the retained point forecast")
    return expected


def nwps_alt_text(evidence):
    prefix = "Synthetic demonstration. " if evidence["synthetic"] else ""
    first = evidence["first_major_at"][:19].replace("T", " ")
    issue = evidence["issued_at"][:19].replace("T", " ")
    return (prefix + f"NOAA/NWS river-stage forecast for {evidence['location']}, gauge {evidence['gauge']}. "
            f"Issued {issue} UTC. The first supplied point at or above the major flood threshold is "
            f"{evidence['first_major_ft']} feet at {first} UTC. Major threshold "
            f"{evidence['major_threshold_ft']} feet. The chart shows {len(evidence['points'])} "
            "forecast points. Crossing time is uncertain.")
