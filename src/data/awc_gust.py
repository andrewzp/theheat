"""A conservative, default-off observed METAR gust profile, never a forecast.

Only named-airport points passing the existing complete AWC point reader are
eligible. Wind additionally agrees with one primary-body KT group. The 50–100
kt editorial range is neither a record test nor a statement about impacts.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
import io
import os
import re

from src.data import awc_observed as awc
from src.two_bot.types import StoryBundle

KIND = "observed_metar_gust"
SCHEMA = "awc-observed-gust-v1"
ENABLE_FLAG = "THEHEAT_AWC_OBSERVED_GUST"
MIN_GUST_KT, MAX_GUST_KT = 50, 100
MAX_NOMINATIONS = 3


def enabled():
    return os.environ.get(ENABLE_FLAG) == "1"


def is_family(value):
    payload = value if isinstance(value, dict) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    return (payload.get("signal_kind") == KIND
            or str(payload.get("event_id", "")).startswith("metar_gust_")
            or isinstance(raw, dict) and raw.get("report_schema") == SCHEMA
            or isinstance(evidence, dict) and evidence.get("schema") == SCHEMA)


def _point(row, metadata, *, now):
    point = awc._point(row, metadata, now=now)
    raw = row["raw_text"]
    # Remarks and TREND are not the observed primary wind group. Require it
    # immediately after the report identity and optional COR/AUTO markers.
    body = re.split(r"\b(?:RMK|BECMG|TEMPO|NOSIG|FM\d{6})\b", raw, maxsplit=1)[0]
    match = re.fullmatch(
        r"(?:(?:METAR|SPECI) )?[A-Z0-9]{4} \d{6}Z (?:COR |AUTO |COR AUTO )?"
        r"(?:[0-2]\d{2}|3[0-5]\d|360|VRB)(\d{2,3})G(\d{2,3})KT(?: .*)?", body.strip())
    winds = re.findall(r"(?<!\S)(?:\d{3}|VRB)\d{2,3}(?:G\d{2,3})?(?:KT|MPS|KMH)(?=\s|$)", body)
    if match is None or len(winds) != 1:
        raise awc.ObservedHeld("awc_gust_primary_wind_missing")
    speed = _wind_integer(row.get("wind_speed_kt"), 0)
    gust = _wind_integer(row.get("wind_gust_kt"), MIN_GUST_KT)
    if (speed != int(match[1]) or gust != int(match[2]) or speed >= gust
            or gust != int(gust) or speed != int(speed)):
        raise awc.ObservedHeld("awc_gust_quantity_changed")
    point.pop("temperature_c")
    return {**point, "wind_speed_kt": int(speed), "gust_kt": int(gust)}


def _wind_integer(value, lower):
    # Provider CSV/XML numbers are strings. Check the bounded exact decimal
    # representation before binary floats can round a fraction into a gust.
    if (type(value) is not str or len(value) > 32
            or re.fullmatch(r"[0-9]{1,3}(?:\.0+)?", value, re.ASCII) is None):
        raise awc.ObservedHeld("awc_gust_number_invalid")
    number = Decimal(value)
    if not lower <= number <= MAX_GUST_KT:
        raise awc.ObservedHeld("awc_gust_number_invalid")
    return int(number)


def parse_metars(raw, metadata, *, now=None):
    if not isinstance(raw, bytes) or len(raw) > awc.MAX_EXPANDED:
        raise awc.ObservedHeld("awc_reports_bound")
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))
    except (csv.Error, UnicodeError) as exc:
        raise awc.ObservedHeld("awc_reports_invalid") from exc
    if not 2 <= len(rows) <= 20001:
        raise awc.ObservedHeld("awc_reports_invalid")
    header = rows[0]
    required = ("raw_text", "station_id", "observation_time", "latitude", "longitude",
                "temp_c", "metar_type", "maintenance_indicator_on", "wind_speed_kt", "wind_gust_kt")
    if any(header.count(key) != 1 for key in required):
        raise awc.ObservedHeld("awc_gust_columns_invalid")
    positions = {key: header.index(key) for key in required}
    result: dict[str, dict] = {}
    seen: set[str] = set()
    clock = awc._clock(now)
    for cells in rows[1:]:
        if len(cells) != len(header):
            raise awc.ObservedHeld("awc_report_row_width_invalid")
        row = {key: cells[index] for key, index in positions.items()}
        station = row["station_id"]
        if station in seen:
            result.pop(station, None)
            continue
        seen.add(station)
        try:
            result[station] = _point(row, metadata, now=clock)
        except awc.ObservedHeld:
            continue
    return result


def citation(point):
    return awc.HISTORY_URL + "?ids=" + awc._identity(point["station_id"]) + "&date=" + awc._stamp(point["valid_time"]) + "&hours=2"


def conversions(gust):
    def rounded(ratio):
        return int((Decimal(gust) * ratio).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"gust_kmh": rounded(Decimal("1.852")),
            "gust_mph": rounded(Decimal("1.852") / Decimal("1.609344"))}


def _finding(point, captured, capture):
    return {"schema": SCHEMA, "source": "NOAA Aviation Weather Center METAR observations",
            "units": "kt", "retrieved_at": captured.isoformat().replace("+00:00", "Z"),
            "points": [deepcopy(point)], "capture_sha256": deepcopy(capture),
            "source_url": citation(point)}


def nominate(*, now=None, capture=None):
    catalog, observations = capture if capture is not None else (awc._read(awc.STATIONS_URL), awc._read(awc.METARS_URL))
    metadata = awc.parse_stations(awc._unzip(catalog))
    points = parse_metars(awc._unzip(observations), metadata, now=now)
    hashes = {"catalog": sha256(catalog).hexdigest(), "observations": sha256(observations).hexdigest()}
    ordered = sorted(points.values(), key=lambda p: (-p["gust_kt"], -awc._time(p["valid_time"]).timestamp(), p["station_id"]))
    return [_finding(point, awc._clock(now), hashes) for point in ordered[:MAX_NOMINATIONS]]


def _declared(evidence, *, now):
    if not isinstance(evidence, dict) or evidence.get("schema") != SCHEMA:
        raise awc.ObservedHeld("awc_gust_evidence_missing")
    captured = awc._time(evidence.get("retrieved_at"))
    capture = evidence.get("capture_sha256")
    if (not isinstance(capture, dict) or set(capture) != {"catalog", "observations"}
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in capture.values())):
        raise awc.ObservedHeld("awc_capture_receipt_invalid")
    points = evidence.get("points")
    if not isinstance(points, list) or len(points) != 1 or not isinstance(points[0], dict):
        raise awc.ObservedHeld("awc_gust_point_invalid")
    point = points[0]
    # Reuse all compact identity/time/coordinate guards without claiming the
    # conservative temperature-screening prerequisite as a retained temperature.
    fields = {"station_id", "airport", "country_code", "country", "latitude", "longitude",
              "valid_time", "metar_type", "maintenance", "raw_report_sha256", "gust_kt", "wind_speed_kt"}
    if set(point) != fields:
        raise awc.ObservedHeld("awc_gust_point_fields_invalid")
    awc._identity(point["station_id"])
    meta = awc._metadata({"icaoId": point["station_id"], "site": point["airport"],
                          "country": point["country_code"], "lat": point["latitude"],
                          "lon": point["longitude"], "siteType": ["METAR"]})
    if any(point[key] != value for key, value in meta.items()):
        raise awc.ObservedHeld("awc_gust_identity_changed")
    target = awc._time(point["valid_time"])
    if (target.second or target.microsecond or target > captured or captured > now
            or now - target > awc.MAX_AGE):
        raise awc.ObservedHeld("awc_observation_expired")
    if (point["maintenance"] is not False or point["metar_type"] not in ("METAR", "SPECI")
            or type(point["gust_kt"]) is not int or not MIN_GUST_KT <= point["gust_kt"] <= MAX_GUST_KT
            or type(point["wind_speed_kt"]) is not int or not 0 <= point["wind_speed_kt"] < point["gust_kt"]
            or type(point["raw_report_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", point["raw_report_sha256"]) is None
            or _finding(point, captured, capture) != evidence):
        raise awc.ObservedHeld("awc_gust_point_invalid")
    return point


def _bundle(evidence):
    point = evidence["points"][0]
    target = awc._time(point["valid_time"])
    # Scalar facts remain readable through the ordinary operator evidence view;
    # the complete structured source warrant stays in raw_signal_dump.
    facts = {"airport": point["airport"], "country": point["country"], "station_id": point["station_id"],
             "gust_kt": point["gust_kt"], "wind_speed_kt": point["wind_speed_kt"],
             "sample_clock_utc": target.strftime("%H:%M UTC"),
             "sample_date_utc": f"{target.day} {awc._MONTHS[target.month - 1]}",
             "public_source_url": evidence["source_url"], **conversions(point["gust_kt"]),
             "claim_scope": "One reported airport wind gust, not sustained wind, damage, a daily peak or a record"}
    return StoryBundle(KIND, point["airport"] + ", " + point["country"], point["valid_time"],
        "metar_gust_" + point["station_id"] + "_" + target.date().isoformat(),
        {"label": "reported_airport_wind_gust", "value": point["gust_kt"], "unit": "kt"},
        [{"label": key, "value": value} for key, value in facts.items()],
        raw_signal_dump={"report_schema": SCHEMA, "evidence": deepcopy(evidence)}, country=point["country_code"])


def build_bundle(evidence, *, now=None):
    _declared(evidence, now=awc._clock(now))
    return _bundle(evidence)


def validate_bundle(value, *, now=None):
    payload = value if isinstance(value, dict) else value.to_dict()
    evidence = payload.get("raw_signal_dump", {}).get("evidence")
    _declared(evidence, now=awc._clock(now))
    if payload != _bundle(evidence).to_dict():
        raise awc.ObservedHeld("awc_gust_bundle_changed")
    return deepcopy(evidence)


def current_bundle_hold(value, *, live=False, now=None, minimum_delay=timedelta(0)):
    try:
        if not is_family(value):
            return None
        if not awc.observed_only():
            return "awc_observed_mode_required"
        if not enabled():
            return "awc_gust_source_disabled"
        clock = awc._clock(now)
        evidence = validate_bundle(value, now=clock)
        if clock + minimum_delay - awc._time(evidence["points"][0]["valid_time"]) > awc.MAX_AGE:
            return "awc_source_insufficient_window"
        if live and awc._history(evidence["points"], now=now, point_reader=_point,
                                extra_fields=("wind_speed_kt", "wind_gust_kt")) != evidence["points"]:
            return "awc_source_changed"
        after = awc._clock(now)
        if after < clock or after - awc._time(evidence["points"][0]["valid_time"]) > awc.MAX_AGE:
            return "awc_observation_expired"
        if not enabled() or not awc.observed_only():
            return "awc_gust_source_disabled"
        return None
    except awc.ObservedHeld as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 — malformed or unavailable is never a pass
        return "awc_gust_current_source_unexpected"


def claim_failures(text, bundle, *, now=None):
    try:
        evidence = validate_bundle(bundle, now=awc._clock(now))
        if not isinstance(text, str) or re.findall(r"https?://\S+", text, re.I) != [evidence["source_url"]]:
            return ["awc_exact_target_citation_required"]
        prose = re.sub(r"https?://\S+", "", text)
        if re.search(r"\b(?:forecast|expected|will|record|highest|strongest|world.?s|ever|sustained|"
                     r"deadly|dangerous|life.threatening|climate change|caused|warning|hurricane|storm.force|"
                     r"damage|disrupt|closed|closing|shutdown|peak|daily|today|tonight|yesterday)\b", prose, re.I):
            return ["awc_gust_unsupported_upgrade"]
        point = evidence["points"][0]
        target = awc._time(point["valid_time"])
        location = re.sub(r"\b(?:Arpt|Airport)\b", "", point["airport"]).strip()
        country_label = re.search(re.escape(point["country"]), prose, re.I)
        if not country_label:
            # A source-backed code is a country label only beside this airport.
            # Keep it uppercase: bare pronouns/prepositions and substrings do
            # not establish country scope. Required models still assess prose.
            country_label = re.search(
                rf"(?i:\b{re.escape(location)}[ \t]+airport)[ \t]*,[ \t]*"
                rf"{re.escape(point['country_code'])}(?=[ \t]*(?:[:,.;]|\Z))", prose)
        if (not re.search(re.escape(location), prose, re.I) or not country_label
                or not re.search(r"\bairport\b", prose, re.I) or not re.search(r"\bgusts?\b", prose, re.I)):
            return ["awc_gust_scope_missing"]
        if (not re.search(rf"\b{target:%H:%M}\s*UTC\b", prose, re.I)
                or not (target.date().isoformat() in prose or re.search(
                    rf"\b(?:{target.day}\s+{awc._MONTHS[target.month-1]}|{awc._MONTHS[target.month-1]}\s+{target.day})\b", prose, re.I))):
            return ["awc_time_label_missing"]
        amounts = [(str(point["gust_kt"]), r"(?:kt|knots?)"),
                   (str(conversions(point["gust_kt"])["gust_kmh"]), r"km/h"),
                   (str(conversions(point["gust_kt"])["gust_mph"]), r"mph")]
        if not any(re.search(r"(?<![\d.−-])" + number + r"\s*" + unit + r"\b", prose, re.I) for number, unit in amounts):
            return ["awc_gust_quantity_missing"]
        # The required factual model still assesses every extra number,
        # attribution and semantic claim; these guards do not certify prose.
        return []
    except Exception:  # noqa: BLE001
        return ["awc_gust_text_source_invalid"]


def current_draft_hold(draft, *, live=False, now=None):
    context = draft.get("review_context")
    two = context.get("two_bot") if isinstance(context, dict) else None
    bundle = two.get("bundle") if isinstance(two, dict) else None
    if (draft.get("type") != KIND or not isinstance(bundle, dict) or bundle.get("signal_kind") != KIND
            or draft.get("event_id") != bundle.get("event_id")):
        return "awc_gust_draft_identity_changed"
    return (current_bundle_hold(bundle, now=now) or next(iter(claim_failures(draft.get("text"), bundle, now=now)), None)
            or current_bundle_hold(bundle, live=live, now=now))


def retained_station_hold(bot_state, evidence, *, now=None, exclude_event_id=None):
    """Retained drafts/attempts block repeats; no unknown send is retried."""
    point = evidence["points"][0]
    station = point["station_id"]
    clock = awc._clock(now)
    drafts = bot_state.get("drafts", [])
    if not isinstance(drafts, list):
        return "awc_gust_history_unavailable"
    for draft in drafts:
        if not isinstance(draft, dict):
            return "awc_gust_history_unavailable"
        if draft.get("type") != KIND:
            continue
        if draft.get("event_id") == exclude_event_id:
            continue
        try:
            old = draft["review_context"]["two_bot"]["bundle"]["raw_signal_dump"]["evidence"]["points"][0]
            if old["station_id"] == station:
                from src.editorial.revisions import has_unresolved_publish
                if (has_unresolved_publish(draft, bot_state)
                        or draft.get("publish_outcome") in ("submitted", "unknown")
                        or any(key in draft and (not isinstance(draft[key], list) or draft[key])
                               for key in ("attempt_conflicts", "revision_conflicts"))
                        or draft.get("autoship_attempted") and draft.get("publish_outcome") not in ("not_sent", "confirmed")):
                    return "awc_gust_uncertain_previous_attempt"
                if clock - awc._time(old["valid_time"]) < timedelta(hours=24):
                    return "awc_gust_station_spacing"
        except (KeyError, IndexError, TypeError, ValueError):
            return "awc_gust_history_unavailable"
    ledger = bot_state.get("publish_ledger", {})
    if not isinstance(ledger, dict):
        return "awc_gust_history_unavailable"
    prefix = "metar_gust_" + station + "_"
    for event, receipt in ledger.items():
        if not isinstance(event, str) or not event.startswith(prefix) or event == exclude_event_id:
            continue
        if not isinstance(receipt, dict):
            return "awc_gust_history_unavailable"
        if _uncertain_receipt(receipt):
            return "awc_gust_uncertain_previous_attempt"
        try:
            stamp = awc._time(receipt.get("confirmed_at") or receipt.get("at"))
        except ValueError:
            return "awc_gust_history_unavailable"
        if clock - stamp < timedelta(hours=24):
            return "awc_gust_station_spacing"
    return None


def _uncertain_receipt(receipt):
    pending = [receipt]
    count = 0
    while pending:
        row = pending.pop()
        count += 1
        if count > 1000 or not isinstance(row, dict) or row.get("phase") not in ("confirmed", "not_sent"):
            return True
        conflicts = row.get("attempt_conflicts", [])
        if not isinstance(conflicts, list) or row.get("revision_conflicts"):
            return True
        if row.get("phase") == "not_sent" and row.get("tweet_id"):
            return True
        if row.get("phase") == "confirmed" and (type(row.get("tweet_id")) is not str
                or re.fullmatch(r"[1-9][0-9]{0,29}", row["tweet_id"], re.ASCII) is None):
            return True
        pending.extend(conflicts)
    return False


def operation_hold(value, bot_state, *, now=None):
    if not is_family(value):
        return None
    try:
        evidence = validate_bundle(value, now=now)
        payload = value if isinstance(value, dict) else value.to_dict()
        if not isinstance(bot_state, dict):
            return "awc_gust_history_unavailable"
        return retained_station_hold(bot_state, evidence, now=now, exclude_event_id=payload.get("event_id"))
    except (ValueError, TypeError, KeyError, AttributeError):
        return "awc_gust_history_unavailable"
