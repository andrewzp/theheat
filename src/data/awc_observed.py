"""Same-time airport temperature observations; no TAF or TREND claims.

The 60 C nomination floor is editorial, not a record or rarity test. Static
validation binds a compact finding; fresh fixed-host reads establish current
source agreement at every consequential boundary.
"""
from __future__ import annotations

from copy import deepcopy
import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import io
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
import zlib

from src.data.places import _registry_text
from src.editorial.observed_scope import enabled as observed_only
from src.two_bot.types import StoryBundle

KIND = "observed_metar_contrast"
SCHEMA = "awc-observed-airport-pair-v1"
ENABLE_FLAG = "THEHEAT_AWC_OBSERVED_CONTRAST"
AUTO_DELAY_MINUTES = 1
MAX_AGE = timedelta(hours=2)
MIN_DIFFERENCE_C = 60
BASE = "https://aviationweather.gov"
METARS_URL = BASE + "/data/cache/metars.cache.csv.gz"
STATIONS_URL = BASE + "/data/cache/stations.cache.json.gz"
HISTORY_URL = BASE + "/api/data/metar"
MAX_COMPRESSED = 2 * 1024 * 1024
MAX_EXPANDED = 8 * 1024 * 1024
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAY_ALIASES = {name.casefold(): index for index, names in enumerate((
    ("Monday", "Mon"), ("Tuesday", "Tue", "Tues"), ("Wednesday", "Wed"),
    ("Thursday", "Thu", "Thur", "Thurs"), ("Friday", "Fri"), ("Saturday", "Sat"), ("Sunday", "Sun"),
)) for name in names}


class ObservedHeld(ValueError):
    pass


def enabled():
    return os.environ.get(ENABLE_FLAG) == "1"


def _clock(now=None):
    clock = now() if callable(now) else now or datetime.now(UTC)
    if not isinstance(clock, datetime) or clock.utcoffset() != timedelta(0):
        raise ObservedHeld("awc_clock_invalid")
    return clock


def _time(value):
    if not isinstance(value, str):
        raise ObservedHeld("awc_time_invalid")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() != timedelta(0):
            raise ValueError()
        return stamp
    except ValueError as exc:
        raise ObservedHeld("awc_time_invalid") from exc


def _stamp(value):
    return _time(value).isoformat().replace("+00:00", "Z")


def _number(value, lower, upper):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ObservedHeld("awc_number_invalid")
    try:
        number = float(value)
    except ValueError as exc:
        raise ObservedHeld("awc_number_invalid") from exc
    if not math.isfinite(number) or not lower <= number <= upper:
        raise ObservedHeld("awc_number_invalid")
    return 0.0 if number == 0 else number


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9]{3}", value):
        raise ObservedHeld("awc_station_invalid")
    return value


@lru_cache(maxsize=1)
def _country_names():
    return json.loads(_registry_text("country_names.json"))["names"]


def _metadata(row):
    if not isinstance(row, dict):
        raise ObservedHeld("awc_metadata_invalid")
    station = _identity(row.get("icaoId"))
    site, country, kinds = row.get("site"), row.get("country"), row.get("siteType")
    names = _country_names()
    if (not isinstance(site, str) or len(site) > 100
            or not re.fullmatch(r"[\w .,'’()/\-]+", site)
            or not re.search(r"\b(?:Arpt|Airport)\b", site)
            or not isinstance(country, str) or country not in names
            or not isinstance(kinds, list) or "METAR" not in kinds):
        raise ObservedHeld("awc_airport_identity_unqualified")
    return {"station_id": station, "airport": site, "country_code": country,
            "country": names[country], "latitude": _number(row.get("lat"), -90, 90),
            "longitude": _number(row.get("lon"), -180, 180)}


def parse_stations(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_EXPANDED:
        raise ObservedHeld("awc_catalog_bound")
    try:
        def unique_fields(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ObservedHeld("awc_duplicate_catalog_field")
                result[key] = value
            return result
        rows = json.loads(raw, object_pairs_hook=unique_fields)
    except (ValueError, UnicodeError) as exc:
        raise ObservedHeld("awc_catalog_invalid") from exc
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20000:
        raise ObservedHeld("awc_catalog_invalid")
    result: dict[str, dict] = {}
    seen: set[str] = set()
    for row in rows:
        # Every duplicate identity is held, including identical repetitions.
        station = row.get("icaoId") if isinstance(row, dict) else None
        if not isinstance(station, str):
            continue
        if station in seen:
            result.pop(station, None)
            continue
        seen.add(station)
        try:
            result[station] = _metadata(row)
        except ObservedHeld:
            continue
    return result


def _point(row, metadata, *, now):
    station = _identity(row.get("station_id"))
    if station not in metadata or row.get("metar_type") not in ("METAR", "SPECI"):
        raise ObservedHeld("awc_station_unqualified")
    stamp = _time(row.get("observation_time"))
    if stamp.second or stamp.microsecond or stamp > now or now - stamp > MAX_AGE:
        raise ObservedHeld("awc_observation_expired")
    if row.get("maintenance_indicator_on") not in (None, "", "FALSE"):
        raise ObservedHeld("awc_maintenance_hold")
    # AWC's misleading no_signal field encodes NOSIG: a TREND forecast of no
    # significant change. It is neither an observation nor a sensor failure.
    # Never put raw METAR prose or TREND predictions into model evidence.
    raw = row.get("raw_text")
    if not isinstance(raw, str) or len(raw) > 4096:
        raise ObservedHeld("awc_report_invalid")
    match = re.match(r"^(?:(?:METAR|SPECI) )?([A-Z0-9]{4}) (\d{6})Z(?: |$)", raw)
    if not match or match[1] != station or match[2] != stamp.strftime("%d%H%M"):
        raise ObservedHeld("awc_report_identity_changed")
    meta = metadata[station]
    if (_number(row.get("latitude"), -90, 90) != meta["latitude"]
            or _number(row.get("longitude"), -180, 180) != meta["longitude"]):
        raise ObservedHeld("awc_coordinates_changed")
    temperature = _number(row.get("temp_c"), -90, 65)
    observed_part = re.split(r"\b(?:BECMG|TEMPO|NOSIG|FM\d{6})\b", raw, maxsplit=1)[0]
    groups = re.findall(r"(?<!\S)(M?\d{2})/(?:M?\d{2}|/{0,2})(?=\s|$)", observed_part)
    if len(groups) != 1:
        raise ObservedHeld("awc_observed_temperature_missing")
    integer = -int(groups[0][1:]) if groups[0].startswith("M") else int(groups[0])
    precise = re.findall(r"(?<!\S)T([01])(\d{3})[01]\d{3}(?=\s|$)", observed_part)
    if len(precise) > 1:
        raise ObservedHeld("awc_observed_temperature_ambiguous")
    expected = int(precise[0][1]) / 10 * (-1 if precise[0][0] == "1" else 1) if precise else integer
    tolerance = 0.000001 if precise else 0.500001
    if abs(temperature - expected) > tolerance:
        raise ObservedHeld("awc_observed_temperature_changed")
    return {**meta, "temperature_c": temperature,
            "valid_time": _stamp(row["observation_time"]), "metar_type": row["metar_type"],
            "maintenance": False, "raw_report_sha256": sha256(raw.encode()).hexdigest()}


def parse_metars(raw, metadata, *, now=None):
    if not isinstance(raw, bytes) or len(raw) > MAX_EXPANDED:
        raise ObservedHeld("awc_reports_bound")
    clock = _clock(now)
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True))
    except (csv.Error, UnicodeError) as exc:
        raise ObservedHeld("awc_reports_invalid") from exc
    if not 2 <= len(rows) <= 20001:
        raise ObservedHeld("awc_reports_invalid")
    header = rows[0]
    required = ("raw_text", "station_id", "observation_time", "latitude", "longitude",
                "temp_c", "metar_type", "maintenance_indicator_on")
    # Four repeated sky-cover/cloud-base pairs are part of the official format.
    if any(header.count(key) != 1 for key in required):
        raise ObservedHeld("awc_report_columns_invalid")
    positions = {key: header.index(key) for key in required}
    result: dict[str, dict] = {}
    seen: set[str] = set()
    for cells in rows[1:]:
        if len(cells) != len(header):
            raise ObservedHeld("awc_report_row_width_invalid")
        row = {key: cells[index] for key, index in positions.items()}
        station = row["station_id"]
        if station in seen:
            result.pop(station, None)
            continue
        seen.add(station)
        try:
            result[station] = _point(row, metadata, now=clock)
        except ObservedHeld:
            continue
    return result


def _request_failure(exc):
    """Fixed diagnostics only; never retain provider text, URLs or payloads."""
    import requests

    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else None
        return f"awc_http_{status}" if type(status) is int and 400 <= status <= 599 else "awc_http_error"
    if isinstance(exc, requests.Timeout):
        return "awc_transport_timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "awc_transport_tls"
    if isinstance(exc, requests.ConnectionError):
        return "awc_transport_connection"
    if isinstance(exc, (requests.exceptions.ChunkedEncodingError, requests.exceptions.ContentDecodingError,
                        requests.exceptions.StreamConsumedError)):
        return "awc_response_stream_error"
    return "awc_request_error"


def _read(url, *, params=None):
    import requests
    from src.data._http import fetch_with_retry

    if url not in (METARS_URL, STATIONS_URL, HISTORY_URL):
        raise ObservedHeld("awc_fixed_source_required")
    try:
        response = fetch_with_retry(url, params=params, timeout=12, attempts=1,
            allow_redirects=False, stream=True, headers={"User-Agent": "theheat-bot (contact@theheat.app)"})
        try:
            if response.status_code != 200:
                raise ObservedHeld("awc_response_invalid")
            chunks, size = [], 0
            deadline = time.monotonic() + 12
            for chunk in response.iter_content(64 * 1024):
                size += len(chunk)
                if size > MAX_COMPRESSED or time.monotonic() > deadline:
                    raise ObservedHeld("awc_response_bound")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()
    except requests.RequestException as exc:
        raise ObservedHeld(_request_failure(exc)) from None


def _unzip(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_COMPRESSED:
        raise ObservedHeld("awc_compressed_bound")
    try:
        decoder = zlib.decompressobj(31)
        result = decoder.decompress(raw, MAX_EXPANDED + 1)
        if len(result) > MAX_EXPANDED or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ObservedHeld("awc_gzip_incomplete_or_bound")
        return result
    except zlib.error as exc:
        raise ObservedHeld("awc_gzip_invalid") from exc


def citation(stations, valid_time):
    ids = sorted(_identity(value) for value in stations)
    if len(ids) != 2 or len(set(ids)) != 2:
        raise ObservedHeld("awc_pair_identity_invalid")
    # Link the reported time, not merely whichever reports are latest when a
    # reader clicks. The documented raw format and taf=false are API defaults;
    # the independent validation request sets both explicitly.
    return HISTORY_URL + "?ids=" + ",".join(ids) + "&date=" + _stamp(valid_time) + "&hours=2"


def _difference(points):
    return float(abs(Decimal(str(points[0]["temperature_c"])) - Decimal(str(points[1]["temperature_c"]))))


def _finding(points, captured, capture):
    points = sorted(deepcopy(points), key=lambda p: p["station_id"])
    return {"schema": SCHEMA, "source": "NOAA Aviation Weather Center METAR observations",
            "units": "C", "retrieved_at": captured.isoformat().replace("+00:00", "Z"),
            "points": points, "capture_sha256": deepcopy(capture),
            "source_url": citation((p["station_id"] for p in points), points[0]["valid_time"]),
            "difference_c": _difference(points)}


def nominate(*, now=None):
    clock = _clock(now)
    catalog = _read(STATIONS_URL)
    metadata = parse_stations(_unzip(catalog))
    if not metadata:
        return None
    observations = _read(METARS_URL)
    points = parse_metars(_unzip(observations), metadata, now=clock)
    capture = {"catalog": sha256(catalog).hexdigest(), "observations": sha256(observations).hexdigest()}
    groups: dict[str, list[dict]] = {}
    for point in points.values():
        groups.setdefault(point["valid_time"], []).append(point)
    for stamp in sorted(groups, reverse=True):
        ordered = sorted(groups[stamp], key=lambda p: (p["temperature_c"], p["station_id"]))
        # Two distinct warm-country maxima suffice for any cold country's
        # comparison; avoid a quadratic scan of a one-country feed.
        warm_candidates = []
        warm_countries = set()
        for point in reversed(ordered):
            if point["country_code"] not in warm_countries:
                warm_candidates.append(point)
                warm_countries.add(point["country_code"])
                if len(warm_candidates) == 2:
                    break
        for cold in ordered:
            for warm in warm_candidates:
                if warm["temperature_c"] < cold["temperature_c"] or _difference([cold, warm]) < MIN_DIFFERENCE_C:
                    break
                if cold["country_code"] != warm["country_code"]:
                    return _finding([cold, warm], _clock(now), capture)
    return None


def _history(points, *, now=None):
    ids = sorted(p["station_id"] for p in points)
    target = points[0]["valid_time"]
    params = {"ids": ",".join(ids), "format": "xml", "taf": "false", "hours": 2, "date": target}
    raw = _read(HISTORY_URL, params=params)
    if any(token in raw.upper() for token in (b"<!DOCTYPE", b"<!ENTITY")):
        raise ObservedHeld("awc_xml_declarations_refused")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ObservedHeld("awc_history_invalid") from exc
    data = root.findall("data")
    if (root.tag != "response" or len(data) != 1 or root.find("errors/error") is not None
            or len(data[0]) > 400 or data[0].get("num_results") != str(len(data[0]))
            or any(row.tag != "METAR" for row in data[0])):
        raise ObservedHeld("awc_history_invalid")
    metadata = parse_stations(_unzip(_read(STATIONS_URL)))
    selected = {}
    for row in data[0]:
        if any(len(row.findall(key)) != 1 for key in ("station_id", "observation_time", "temp_c",
                                                      "raw_text", "latitude", "longitude", "metar_type")):
            raise ObservedHeld("awc_history_duplicate_field")
        station, stamp = row.findtext("station_id"), row.findtext("observation_time")
        if station not in ids:
            raise ObservedHeld("awc_history_unrequested_identity")
        if _stamp(stamp) != target:
            continue
        if station in selected:
            raise ObservedHeld("awc_history_duplicate_target")
        values = {key: row.findtext(key) for key in ("station_id", "observation_time", "temp_c",
                    "raw_text", "latitude", "longitude", "metar_type")}
        flags = row.findall("quality_control_flags")
        if len(flags) > 1:
            raise ObservedHeld("awc_history_duplicate_flags")
        if flags:
            names = [child.tag for child in flags[0]]
            if (len(names) != len(set(names)) or any(len(child) for child in flags[0])
                    or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in names)):
                raise ObservedHeld("awc_history_duplicate_or_invalid_flag")
            maintenance = flags[0].findall("maintenance_indicator_on")
            if maintenance and maintenance[0].text not in ("TRUE", "FALSE"):
                raise ObservedHeld("awc_history_maintenance_unknown")
        values["maintenance_indicator_on"] = flags[0].findtext("maintenance_indicator_on") if flags else None
        selected[station] = _point(values, metadata, now=_clock(now))
    if set(selected) != set(ids):
        raise ObservedHeld("awc_history_target_missing")
    return sorted(selected.values(), key=lambda p: p["station_id"])


def _declared(evidence, *, now):
    if not isinstance(evidence, dict) or evidence.get("schema") != SCHEMA:
        raise ObservedHeld("awc_evidence_missing")
    captured = _time(evidence.get("retrieved_at"))
    capture = evidence.get("capture_sha256")
    if (not isinstance(capture, dict) or set(capture) != {"catalog", "observations"}
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value) for value in capture.values())):
        raise ObservedHeld("awc_capture_receipt_invalid")
    points = evidence.get("points")
    if not isinstance(points, list) or len(points) != 2:
        raise ObservedHeld("awc_pair_invalid")
    names = _country_names()
    for point in points:
        if not isinstance(point, dict):
            raise ObservedHeld("awc_point_invalid")
        if set(point) != {"station_id", "airport", "country_code", "country", "latitude", "longitude",
                          "temperature_c", "valid_time", "metar_type", "maintenance", "raw_report_sha256"}:
            raise ObservedHeld("awc_point_fields_invalid")
        _identity(point.get("station_id"))
        target = _time(point.get("valid_time"))
        if target.second or target.microsecond or target > captured or captured > now or now - target > MAX_AGE:
            raise ObservedHeld("awc_observation_expired")
        if (point.get("country") != names.get(point.get("country_code"))
                or point.get("country_code") not in names or point.get("maintenance") is not False
                or point.get("metar_type") not in ("METAR", "SPECI")
                or not isinstance(point.get("airport"), str)
                or len(point["airport"]) > 100 or not re.fullmatch(r"[\w .,'’()/\-]+", point["airport"])
                or not re.search(r"\b(?:Arpt|Airport)\b", point["airport"])
                or not isinstance(point.get("raw_report_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", point["raw_report_sha256"])):
            raise ObservedHeld("awc_point_invalid")
        _number(point.get("latitude"), -90, 90)
        _number(point.get("longitude"), -180, 180)
        _number(point.get("temperature_c"), -90, 65)
    if (points[0]["station_id"] == points[1]["station_id"]
            or points[0]["country_code"] == points[1]["country_code"]
            or points[0]["valid_time"] != points[1]["valid_time"]
            or _difference(points) < MIN_DIFFERENCE_C
            or _finding(points, captured, capture) != evidence):
        raise ObservedHeld("awc_pair_changed")
    return points


def _bundle(evidence):
    points = evidence["points"]
    target = _time(points[0]["valid_time"])
    return StoryBundle(KIND, " / ".join(p["airport"] + ", " + p["country"] for p in points),
        points[0]["valid_time"], "metar_pair_" + "_".join(p["station_id"] for p in points)
        + "_" + target.date().isoformat(),
        {"label": "simultaneous_airport_temperature_difference", "value": evidence["difference_c"], "unit": "C"},
        [{"label": key, "value": value} for key, value in {
            "observed_airports": points, "sample_clock_utc": target.strftime("%H:%M UTC"),
            "sample_date_utc": f"{target.day} {_MONTHS[target.month - 1]}",
            "public_source_url": evidence["source_url"],
            "claim_scope": "Two reported airport observations, not a record or a global ranking",
        }.items()], historical_context={"comparator": "Same UTC moment at two named reporting airports"},
        raw_signal_dump={"report_schema": SCHEMA, "evidence": deepcopy(evidence)})


def build_bundle(evidence, *, now=None):
    _declared(evidence, now=_clock(now))
    return _bundle(evidence)


def _family(value):
    payload = value if isinstance(value, dict) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    return (payload.get("signal_kind") == KIND or str(payload.get("event_id", "")).startswith("metar_pair_")
            or isinstance(raw, dict) and raw.get("report_schema") == SCHEMA
            or isinstance(evidence, dict) and (evidence.get("schema") == SCHEMA
                or str(evidence.get("source_url", "")).startswith(HISTORY_URL)))


def is_family(value):
    return _family(value)


def validate_bundle(value, *, now=None):
    payload = value if isinstance(value, dict) else value.to_dict()
    evidence = payload.get("raw_signal_dump", {}).get("evidence")
    _declared(evidence, now=_clock(now))
    if payload != _bundle(evidence).to_dict():
        raise ObservedHeld("awc_bundle_changed")
    return deepcopy(evidence)


def current_bundle_hold(value, *, live=False, now=None, minimum_delay=timedelta(0)):
    try:
        if not _family(value):
            return None
        if not observed_only():
            return "awc_observed_mode_required"
        if not enabled():
            return "awc_source_disabled"
        clock = _clock(now)
        evidence = validate_bundle(value, now=clock)
        if clock + minimum_delay - _time(evidence["points"][0]["valid_time"]) > MAX_AGE:
            return "awc_source_insufficient_window"
        if live and _history(evidence["points"], now=now) != evidence["points"]:
            return "awc_source_changed"
        after = _clock(now)
        if after < clock or after - _time(evidence["points"][0]["valid_time"]) > MAX_AGE:
            return "awc_observation_expired"
        return None
    except ObservedHeld as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 — missing/unavailable source is never a pass
        return "awc_current_source_unexpected"


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
            return ["awc_text_invalid"]
        if (re.findall(r"https?://\S+", text, flags=re.I) != [evidence["source_url"]]
                or text.split().count(evidence["source_url"]) != 1):
            return ["awc_exact_target_citation_required"]
        prose = re.sub(r"https?://\S+", "", text)
        if re.search(r"\b(?:forecast|expected|will|record|hottest|coldest|world.?s|ever|"
                     r"deadly|dangerous|life.threatening|climate change|caused|warning)\b", prose, re.I):
            return ["awc_unsupported_upgrade"]
        target = _time(evidence["points"][0]["valid_time"])
        calendar_prose = prose
        for point in evidence["points"]:
            location = re.sub(r"\b(?:Arpt|Airport)\b", "", point["airport"]).strip()
            name = r"(?<!\w)" + re.escape(location) + r"(?!\w)"
            if location.casefold() in _WEEKDAY_ALIASES:
                # A single weekday name needs location context; never erase a
                # separate calendar label merely because an airport shares it.
                country = re.escape(point["country"])
                name = (r"\bairports?\s+" + name + "|" + name
                        + rf"(?=\s+airports?\b|\s*,\s*{country}\b)")
            calendar_prose = re.sub(name, "", calendar_prose, flags=re.I)
        days = "|".join(sorted(_WEEKDAY_ALIASES, key=len, reverse=True))
        months = "|".join(_MONTHS)
        for match in re.finditer(r"\b(?:" + days + r")\b", calendar_prose, re.I):
            day = match.group().casefold()
            index = _WEEKDAY_ALIASES[day]
            full_name = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")[index]
            # Abbreviations can also be ordinary words ("sat", "sun"). Only
            # treat them as days beside a date/clock or after the label "on".
            if day != full_name and not (
                re.search(r"\bon\s+$", calendar_prose[:match.start()], re.I)
                or re.match(r"\.?\s*,?\s*(?:\d{1,2}\s+(?:" + months + r")\b|(?:" + months
                            + r")\s+\d{1,2}\b|(?:at\s+)?\d{1,2}:\d{2}\b)",
                            calendar_prose[match.end():], re.I)
            ):
                continue
            if index != target.weekday():
                return ["awc_weekday_mismatch"]
        if (not re.search(rf"\b{target:%H:%M}\s*UTC\b", prose, re.I)
                or not (target.date().isoformat() in prose
                    or re.search(rf"\b(?:{target.day}\s+{_MONTHS[target.month-1]}|{_MONTHS[target.month-1]}\s+{target.day})\b", prose, re.I))):
            return ["awc_time_label_missing"]
        for point in evidence["points"]:
            location = re.sub(r"\b(?:Arpt|Airport)\b", "", point["airport"]).strip()
            if (not re.search(re.escape(location), prose, re.I)
                    or not re.search(re.escape(point["country"]), prose, re.I)
                    or not re.search(r"\b(?:airport|airports)\b", prose, re.I)):
                return ["awc_airport_scope_missing"]
        for number in [*(point["temperature_c"] for point in evidence["points"]), evidence["difference_c"]]:
            value = str(number).removesuffix(".0")
            numeric = re.escape(value).replace(r"\-", "[−-]")
            suffix = r"0*" if "." in value else r"(?:\.0+)?"
            if not re.search(r"(?<![\d.−-])" + numeric + suffix + r"\s*°\s*C\b", prose):
                return ["awc_observed_quantity_missing"]
        # Required factual model still judges exact attribution, numbers and
        # entailment. These local checks cannot certify semantic truth.
        return []
    except Exception:  # noqa: BLE001
        return ["awc_text_source_invalid"]


def current_draft_hold(draft, *, live=False, now=None):
    if not isinstance(draft, dict):
        return "awc_draft_invalid"
    context = draft.get("review_context")
    two_bot = context.get("two_bot") if isinstance(context, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    if draft.get("type") != KIND and not (isinstance(bundle, dict) and _family(bundle)):
        return None
    if (draft.get("type") != KIND or not isinstance(bundle, dict) or bundle.get("signal_kind") != KIND
            or draft.get("event_id") != bundle.get("event_id")):
        return "awc_draft_identity_changed"
    hold = current_bundle_hold(bundle, now=now)
    failures = claim_failures(draft.get("text"), bundle, now=now)
    if hold or failures:
        return hold or failures[0]
    return current_bundle_hold(bundle, live=live, now=now)
