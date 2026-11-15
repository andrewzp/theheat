"""One watched gauge's observed residual, with exact-point source rechecks.

Static validation grants no source truth. Every live boundary reads the two
fixed NOAA requests again and requires their exact retained byte identities.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import re
from urllib.parse import urlencode

from src.data import water_levels as wl
from src.editorial.observed_scope import enabled
from src.two_bot.types import StoryBundle

KIND = "coastal_observed_report"
SCHEMA = "noaa-coops-observed-point-v1"
AUTO_DELAY_MINUTES = 1
MAX_AGE = timedelta(hours=6)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class CoastalHeld(ValueError):
    pass


def _clock(now):
    now = now() if callable(now) else now or datetime.now(UTC)
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
        raise CoastalHeld("coastal_clock_invalid")
    return now


def _time(value):
    if not isinstance(value, str):
        raise CoastalHeld("coastal_time_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() != timedelta(0):
            raise ValueError()
        return result
    except ValueError as exc:
        raise CoastalHeld("coastal_time_invalid") from exc


def _station(station_id):
    found = [row for row in wl.STATIONS if row[0] == station_id]
    if len(found) != 1:
        raise CoastalHeld("coastal_station_unqualified")
    return found[0]


def citation(station_id):
    _station(station_id)
    return f"https://tidesandcurrents.noaa.gov/stationhome.html?id={station_id}"


def _queries(station_id, target):
    _station(station_id)
    if target.second or target.microsecond or target.minute % 6:
        raise CoastalHeld("coastal_sample_interval_invalid")
    common = {"end_date": target.strftime("%Y%m%d %H:%M"), "station": station_id,
              "datum": "MLLW", "units": "metric", "time_zone": "gmt",
              "application": "theheat_bot", "format": "json"}
    return {
        "observation_query": urlencode({"begin_date": target.strftime("%Y%m%d %H:%M"),
                                        **common, "product": "water_level"}),
        # NOAA returns no tide prediction for an equal begin/end query. One
        # fixed 6-minute interval includes the exact point without interpolation.
        "tide_comparison_query": urlencode({"begin_date": (target - timedelta(minutes=6)).strftime("%Y%m%d %H:%M"),
                                            **common, "product": "predictions", "interval": "6"}),
    }


def fetch_point(station_id, valid_time, *, now=None):
    from urllib.parse import parse_qsl
    from src.data._http import fetch_with_retry

    clock = _clock(now)
    target = _time(valid_time)
    if target > clock or clock - target > MAX_AGE:
        raise CoastalHeld("coastal_source_expired")
    queries = _queries(station_id, target)
    replies = []
    for query in queries.values():
        response = fetch_with_retry(wl.COOPS_URL, params=dict(parse_qsl(query)), timeout=10,
                                    attempts=1, allow_redirects=False)
        if response.status_code != 200 or len(response.content) > 256 * 1024:
            raise CoastalHeld("coastal_source_response_invalid")
        replies.append(response)
    reading = wl._pair(*_station(station_id), replies[0].json(), replies[1].json(),
                       now=_clock(now), observed_sha256=sha256(replies[0].content).hexdigest(),
                       predicted_sha256=sha256(replies[1].content).hexdigest())
    if _time(reading.evidence["valid_time"]) != target:
        raise CoastalHeld("coastal_source_time_changed")
    reading.evidence["source_requests"] = queries
    return deepcopy(reading.evidence)


def _declared(evidence, *, now):
    """Validate a declared finding's shape; live reads independently prove it."""
    if not isinstance(evidence, dict):
        raise CoastalHeld("coastal_evidence_missing")
    target, captured = _time(evidence.get("valid_time")), _time(evidence.get("retrieved_at"))
    if target > captured or captured > now or now - target > MAX_AGE:
        raise CoastalHeld("coastal_source_expired")
    station = _station(evidence.get("station_id"))
    if evidence.get("source_requests") != _queries(station[0], target):
        raise CoastalHeld("coastal_query_changed")
    for key in ("observed_response_sha256", "prediction_response_sha256"):
        if not isinstance(evidence.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", evidence[key]):
            raise CoastalHeld("coastal_receipt_invalid")
    stamp = target.strftime("%Y-%m-%d %H:%M")
    declared = wl._pair(*station,
        {"metadata": {"id": station[0]}, "data": [{"t": stamp, "v": evidence.get("observed_m"),
            "q": evidence.get("quality"), "f": evidence.get("quality_flags")}]},
        {"predictions": [{"t": stamp, "v": evidence.get("predicted_tide_m")}]}, now=captured,
        observed_sha256=evidence["observed_response_sha256"],
        predicted_sha256=evidence["prediction_response_sha256"])
    expected = {**declared.evidence, "source_requests": _queries(station[0], target)}
    if expected != evidence:
        raise CoastalHeld("coastal_evidence_changed")
    if declared.anomaly_m < wl.SURGE_THRESHOLD_M:
        raise CoastalHeld("coastal_below_nomination_threshold")
    return declared


def _bundle(evidence, reading):
    return StoryBundle(KIND, reading.station_name, evidence["valid_time"],
        f"coastal_report_{reading.station_id}_{reading.date}",
        {"label": "observed_water_above_predicted_tide_m", "value": reading.anomaly_m, "unit": "m"},
        [{"label": k, "value": v} for k, v in {
            "station": reading.station_name, "station_id": reading.station_id,
            "observed_m": reading.observed_m, "predicted_tide_m": reading.predicted_m,
            "difference_m": reading.anomaly_m, "difference_ft_rounded": round(reading.anomaly_m * 3.28084),
            "valid_time_utc": evidence["valid_time"], "reporting_day_utc": reading.date,
            "quality": evidence["quality_status"], "datum": "MLLW",
            "sample_clock_utc": _time(evidence["valid_time"]).strftime("%H:%M UTC"),
            "sample_date_utc": str(_time(evidence["valid_time"]).day) + " " + _MONTHS[_time(evidence["valid_time"]).month - 1],
            "public_source_url": citation(reading.station_id),
        }.items()],
        historical_context={"scope": evidence["claim_scope"]},
        raw_signal_dump={"report_schema": SCHEMA, "evidence": deepcopy(evidence)})


def build_bundle(evidence, *, now=None):
    clock = _clock(now)
    return _bundle(evidence, _declared(evidence, now=clock))


def validate_bundle(value, *, now=None):
    clock = _clock(now)
    payload = value if isinstance(value, dict) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    if not isinstance(raw, dict) or raw.get("report_schema") != SCHEMA:
        raise CoastalHeld("coastal_report_schema_invalid")
    evidence = raw.get("evidence")
    reading = _declared(evidence, now=clock)
    if _bundle(evidence, reading).to_dict() != payload:
        raise CoastalHeld("coastal_bundle_changed")
    return deepcopy(evidence)


def _family(value):
    if not isinstance(value, dict):
        value = value.to_dict()
    raw = value.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    anchored = isinstance(evidence, dict) and (evidence.get("source_url") == wl.COOPS_URL
        or evidence.get("source_product") == "noaa-coops-water-level-v1")
    return (value.get("signal_kind") == KIND
            or anchored and value.get("signal_kind") != "storm_surge"
            or isinstance(raw, dict) and raw.get("report_schema") == SCHEMA
            or str(value.get("event_id", "")).startswith("coastal_report_"))


def current_bundle_hold(value, *, live=False, now=None, minimum_delay=timedelta(0)):
    try:
        if not _family(value):
            return None
        if not enabled():
            return "coastal_observed_mode_required"
        clock = _clock(now)
        evidence = validate_bundle(value, now=clock)
        if clock + minimum_delay - _time(evidence["valid_time"]) > MAX_AGE:
            return "coastal_source_insufficient_window"
        if live:
            fresh = fetch_point(evidence["station_id"], evidence["valid_time"], now=now)
            after = _clock(now)
            if after < clock or after - _time(evidence["valid_time"]) > MAX_AGE:
                return "coastal_source_expired"
            for key in ("observed_response_sha256", "prediction_response_sha256"):
                if fresh[key] != evidence[key]:
                    return "coastal_source_changed"
            if {k:v for k,v in fresh.items() if k != "retrieved_at"} != {k:v for k,v in evidence.items() if k != "retrieved_at"}:
                return "coastal_finding_changed"
        return None
    except CoastalHeld as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 — unavailable source never becomes a pass
        return "coastal_current_source_unavailable"


def current_draft_hold(draft, *, live=False, now=None):
    if not isinstance(draft, dict):
        return "coastal_draft_invalid"
    context = draft.get("review_context")
    two_bot = context.get("two_bot") if isinstance(context, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    is_family = isinstance(bundle, dict) and _family(bundle)
    if draft.get("type") != KIND and not is_family:
        return None
    if (draft.get("type") != KIND or not isinstance(bundle, dict)
            or draft.get("event_id") != bundle.get("event_id")):
        return "coastal_draft_kind_changed"
    hold = current_bundle_hold(bundle, live=False, now=now)
    if hold:
        return hold
    failures = claim_failures(draft.get("text"), bundle, now=now)
    if failures:
        return failures[0]
    return current_bundle_hold(bundle, live=True, now=now) if live else None


def legacy_station_day_hold(value, bot_state):
    """Recheck legacy coastal aliases at admission and every publication boundary.

    The normal event ledger guards this report's own identity. These legacy
    identities must additionally block, including uncertain delivery, without
    treating this attempt's newly recorded canonical intent as a duplicate.
    """
    try:
        payload = value if isinstance(value, dict) else value.to_dict()
        if payload.get("type") == KIND:
            payload = payload.get("review_context", {}).get("two_bot", {}).get("bundle")
            if not isinstance(payload, dict):
                return "coastal_evidence_missing"
        if not _family(payload):
            return None
        if not isinstance(bot_state, dict):
            return "coastal_publication_state_missing"
        evidence = payload["raw_signal_dump"]["evidence"]
        station_id = _station(evidence["station_id"])[0]
        day = _time(evidence["valid_time"]).date().isoformat()
        aliases = {f"surge_{level}_{station_id}_{day}" for level in ("notable", "major")}
        if (any(key in bot_state.get("posted_events", []) for key in aliases)
                or any(key in bot_state.get("publish_ledger", {}) for key in aliases)
                or any(row.get("event_id") in aliases for row in bot_state.get("drafts", []))):
            return "coastal_legacy_station_day_held"
        return None
    except Exception:  # noqa: BLE001 — malformed state is never publication authority
        return "coastal_station_day_unverified"



def bundle_failures(bundle):
    if not _family(bundle):
        return []
    hold = current_bundle_hold(bundle)
    return [hold] if hold else []


def claim_failures(text, bundle, *, now=None):
    if not _family(bundle):
        return []
    try:
        evidence = validate_bundle(bundle, now=_clock(now))
        if not isinstance(text, str):
            return ["coastal_text_invalid"]
        # Bounded unsupported-upgrade checks; the required factual checker still
        # judges the whole sentence, quantities, conversion and source entailment.
        prose = re.sub(r"https?://\S+", "", text)
        if re.search(r"\b(?:flood\w*|storm\w*|surge|record|evacuat\w*|damage\w*|deadly|"
                     r"life.threatening|warning|forecast|climate change|sea.level rise)\b", prose, re.I):
            return ["coastal_unsupported_impact_or_record"]
        if not re.search(r"\b(?:predicted tide|tide prediction|tide tables?)\b", prose, re.I):
            return ["coastal_comparison_label_missing"]
        if evidence["quality"] == "p" and not re.search(r"\bpreliminary\b", prose, re.I):
            return ["coastal_preliminary_label_missing"]
        if evidence["quality"] == "v" and re.search(r"\bpreliminary\b", prose, re.I):
            return ["coastal_quality_label_changed"]
        target = _time(evidence["valid_time"])
        clock = f"(?:{target:%H:%M}|{target.hour}:{target.minute:02d})"
        if not re.search(r"(?<!\d)" + clock + r"\s*UTC\b", prose, re.I):
            return ["coastal_clock_label_missing"]
        month, day = _MONTHS[target.month - 1], str(target.day)
        if not (re.search(r"\b" + day + r"\s+" + month + r"\b", prose, re.I)
                or re.search(r"\b" + month + r"\s+" + day + r"\b", prose, re.I)
                or target.date().isoformat() in prose):
            return ["coastal_date_label_missing"]
        station_name = _station(evidence["station_id"])[1].split(",")[0].removeprefix("The ")
        if not re.search(r"\b" + re.escape(station_name) + r"\b", prose, re.I):
            return ["coastal_station_label_missing"]
        return []
    except Exception:  # noqa: BLE001
        return ["coastal_text_source_invalid"]
