"""Bounded CRW regional packets and receipts; binding is not source certification."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
from html.parser import HTMLParser
import math
import re
from typing import Any, NoReturn

from src.data.source_status import SourceFetchError

PRODUCT = "noaa-crw-regional-v3.1"
SOURCE_NAME = "NOAA Coral Reef Watch"
LEG = "crw_virtual_station"
INDEX_URL = "https://coralreefwatch.noaa.gov/product/vs/data.php"
DATA_BASE = "https://coralreefwatch.noaa.gov/product/vs/data/"
INDEX_LIMIT = 4 * 1024 * 1024
TOTAL_LIMIT = 32 * 1024 * 1024
TAIL_BYTES = 8192
HEADER_BYTES = 2049
MAX_AGE_DAYS = 5
UNIT = "degree_Celsius_weeks"
METHOD = "Regional 90th-percentile HotSpot accumulation over the preceding 12 weeks"
LABELS = (
    "No Stress",
    "Bleaching Watch",
    "Bleaching Warning",
    "Bleaching Alert Level 1",
    "Bleaching Alert Level 2",
)
COLUMNS = "YYYY MM DD SST_MIN SST_MAX SST@90th_HS SSTA@90th_HS 90th_HS>0 DHW_from_90th_HS>1 BAA_7day_max".split()
_RECEIPT_KEYS = {
    "schema_version",
    "source_product",
    "source_name",
    "source_leg",
    "evidence_type",
    "region_id",
    "region_full_name",
    "source_url",
    "valid_date",
    "dhw_value",
    "unit",
    "baa_7day_max",
    "baa_scale",
    "baa_window_days",
    "stress_level",
    "marker_point",
    "marker_role",
    "method",
    "index",
    "header",
    "tail",
}
_RANGE_KEYS = {
    "source_url",
    "response_sha256",
    "response_bytes",
    "retrieved_at",
    "etag",
    "range_start",
    "range_end",
    "total_bytes",
}
_INDEX_KEYS = {"source_url", "response_sha256", "response_bytes", "retrieved_at", "index_date"}
_HEADER_KEYS = _RANGE_KEYS | {"first_dhw_date", "first_baa_date", "columns"}
_TAIL_KEYS = _RANGE_KEYS | {"first_retained_date", "last_retained_date", "complete_row_count"}
_MONTHS = {
    name.lower(): i
    for i, name in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1
    )
}


@dataclass(frozen=True)
class StationLink:
    region_id: str
    region_full_name: str
    stress_level: str
    data_file: str


def reject(reason: str) -> NoReturn:
    raise SourceFetchError(f"coral_dhw regional source contract: schema drift: {reason}")


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc(value: Any) -> datetime:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        reject("invalid retrieval timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        reject("invalid retrieval timestamp")


def _day(value: Any) -> date:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        reject("invalid source date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        reject("invalid source date")


def _fresh(day: date, retrieved_at: str, max_age_days: int = MAX_AGE_DAYS) -> None:
    stamp = _utc(retrieved_at)
    if type(max_age_days) is not int or not 0 <= max_age_days <= MAX_AGE_DAYS:
        reject("invalid freshness budget")
    if stamp > datetime.now(UTC) or day > stamp.date():
        reject("future source date")
    if (stamp.date() - day).days > max_age_days:
        raise SourceFetchError(
            "coral_dhw stale data: regional source date exceeds freshness budget"
        )


def _name(value: str) -> str:
    return " ".join(value.split())


def _safe_name(value: Any) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= 200
        and value == _name(value)
        and all(ord(c) >= 32 for c in value)
    )


def _safe_id(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[a-z0-9_]{1,80}", value) is not None


class _IndexParser(HTMLParser):
    """Retain complete station-bearing rows, including malformed partial entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str]]] = []
        self.row: list[tuple[str, str]] | None = None
        self.link: str | None = None
        self.link_text: list[str] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            if self.row is not None:
                reject("nested or unterminated index row")
            self.row = []
        if tag == "a" and self.row is not None:
            if self.link is not None:
                reject("nested index link")
            hrefs = [v for k, v in attrs if k == "href"]
            if len(hrefs) > 1:
                reject("duplicate index link attribute")
            self.link = hrefs[0] if hrefs and hrefs[0] is not None else ""
            self.link_text = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self.link is not None:
            self.link_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.row is not None and self.link is not None:
            self.row.append((self.link, _name("".join(self.link_text))))
            self.link = None
        if tag == "tr" and self.row is not None:
            if self.link is not None:
                reject("unterminated index link")
            self.rows.append(self.row)
            self.row = None


def decode_index(
    body: bytes, *, retrieved_at: str, max_age_days: int
) -> tuple[list[StationLink], dict]:
    if type(body) is not bytes or not 0 < len(body) <= INDEX_LIMIT:
        reject("index byte limit")
    try:
        parser = _IndexParser()
        parser.feed(body.decode("utf-8", errors="strict"))
        parser.close()
        if parser.row is not None or parser.link is not None:
            reject("unterminated index row")
        rendered = " ".join(parser.text)
        if re.findall(r"\bVersion\s+([0-9.]+)", rendered) != ["3.1"]:
            reject("index product version")
        matches = re.findall(r"Latest Data Date:\s*([A-Za-z]+)\.\s*(\d{1,2}),\s*(\d{4})", rendered)
        if len(matches) != 1 or rendered.count("Latest Data Date:") != 1:
            reject("index date identity")
        month, day, year = matches[0]
        latest = date(int(year), _MONTHS[month.lower()], int(day))
        _fresh(latest, retrieved_at, max_age_days)
        stations: dict[str, StationLink] = {}
        for row in parser.rows:
            relevant = [
                (h, t)
                for h, t in row
                if any(x in h.lower() for x in ("data/", "timeseries/", "gauges/"))
            ]
            # Other index tables may contain graph links but no station entry.
            bearing = any(
                "timeseries/" in h.lower()
                or "gauges/" in h.lower()
                or h.lower().startswith("data/")
                or ".txt" in h.lower()
                for h, _ in relevant
            )
            if not bearing:
                continue
            data_links = [h for h, _ in relevant if re.fullmatch(r"data/[a-z0-9_]{1,80}\.txt", h)]
            series = [
                (h, t)
                for h, t in relevant
                if re.fullmatch(r"timeseries/[a-z0-9_]+\.php#[a-z0-9_]{1,80}", h)
            ]
            gauges = [
                (h, t) for h, t in relevant if re.fullmatch(r"gauges/[a-z0-9_]{1,80}\.php", h)
            ]
            # No malformed additional station link may hide beside a valid one.
            station_links = [
                (h, t)
                for h, t in relevant
                if "timeseries/" in h.lower()
                or "gauges/" in h.lower()
                or h.lower().startswith("data/")
                or ".txt" in h.lower()
            ]
            if (
                len(data_links) != 1
                or len(series) != 1
                or len(gauges) != 1
                or len(station_links) != 3
            ):
                reject("malformed station-bearing row")
            region_id = series[0][0].split("#")[1]
            name, label = series[0][1], gauges[0][1]
            if (
                not _safe_name(name)
                or label not in LABELS
                or data_links[0] != f"data/{region_id}.txt"
                or gauges[0][0] != f"gauges/{region_id}.php"
            ):
                reject("station identity or label mismatch")
            station = StationLink(region_id, name, label, f"{region_id}.txt")
            if region_id in stations and station != stations[region_id]:
                reject("conflicting duplicate station")
            stations[region_id] = station
        if not stations:
            reject("no station entries")
        return list(stations.values()), {
            "source_url": INDEX_URL,
            "response_sha256": hashlib.sha256(body).hexdigest(),
            "response_bytes": len(body),
            "retrieved_at": retrieved_at,
            "index_date": latest.isoformat(),
        }
    except (UnicodeError, KeyError, ValueError, OverflowError):
        reject("malformed index")


def _etag(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r'"[\x21\x23-\x7e]{1,198}"', value) is not None


def response_range(
    status: int, headers: Mapping[str, str], *, kind: str, prior: dict | None = None
) -> dict:
    """Check representation identity before consuming any response body."""
    h = {k.lower(): v for k, v in headers.items()}
    if (
        status != 206
        or h.get("content-encoding", "identity").lower() != "identity"
        or "multipart" in h.get("content-type", "").lower()
    ):
        reject("range status or representation")
    match = re.fullmatch(
        r"bytes (0|[1-9][0-9]*)-(0|[1-9][0-9]*)/([1-9][0-9]*)", h.get("content-range", "")
    )
    if match is None or not _etag(h.get("etag")):
        reject("range or strong validator missing")
    start, end, total = map(int, match.groups())
    if not TAIL_BYTES <= total <= TOTAL_LIMIT:
        reject("file size outside computational limit")
    if kind == "tail":
        if start != total - TAIL_BYTES or end != total - 1:
            reject("unsolicited tail range")
    elif kind == "header":
        if (
            start != 0
            or end != HEADER_BYTES - 1
            or prior is None
            or h["etag"] != prior["etag"]
            or total != prior["total_bytes"]
        ):
            reject("header/tail version mismatch")
    else:
        reject("unknown range kind")
    if "content-length" in h and h["content-length"] != str(end - start + 1):
        reject("range content length mismatch")
    return {"etag": h["etag"], "range_start": start, "range_end": end, "total_bytes": total}


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _header(body: bytes, station: StationLink, latest: date) -> dict:
    try:
        lines = body.decode("ascii", errors="strict").splitlines()
        if len(lines) < 23:
            reject("incomplete header")
        labels = {
            0: "Name:",
            3: "Polygon Middle Longitude:",
            6: "Polygon Middle Latitude:",
            9: "Averaged Maximum Monthly Mean:",
            12: "Averaged Monthly Mean (Jan-Dec):",
            15: "First Valid DHW Date:",
            18: "First Valid BAA Date:",
        }
        if any(lines[i].strip() != label for i, label in labels.items()) or any(
            lines[i].strip() for i in [2, 5, 8, 11, 14, 17, 20]
        ):
            reject("header layout or labels")
        if _name(lines[1]) != station.region_full_name or lines[21].split() != COLUMNS:
            reject("header name or columns")
        lon, lat, mmm = (float(lines[i].strip()) for i in [4, 7, 10])
        monthly = [float(v) for v in lines[13].split()]
        if (
            not all(_finite(v) for v in [lon, lat, mmm, *monthly])
            or len(monthly) != 12
            or not -180 <= lon <= 180
            or not -90 <= lat <= 90
        ):
            reject("header marker or climatology")
        dates = []
        for i in [16, 19]:
            if not re.fullmatch(r"[ \t]*[0-9]{4}[ \t]+[0-9]{2}[ \t]+[0-9]{2}[ \t]*", lines[i]):
                reject("first-valid date layout")
            year, day, month = map(int, lines[i].split())
            dates.append(date(year, month, day))
        if not dates[0] <= dates[1] <= latest:
            reject("first-valid dates out of order")
        return {
            "marker_point": [lat, lon],
            "first_dhw_date": dates[0].isoformat(),
            "first_baa_date": dates[1].isoformat(),
            "columns": list(COLUMNS),
        }
    except (UnicodeError, ValueError, OverflowError):
        reject("malformed header")


def _tail(body: bytes, start: int, latest: date, station: StationLink) -> dict:
    try:
        if not body.endswith(b"\n"):
            reject("unterminated tail")
        lines = body.decode("ascii", errors="strict").splitlines()
        if start > 0:
            lines = lines[1:]  # Only the first possibly partial record is discardable.
        rows: list[tuple[date, float, int]] = []
        for line in lines:
            parts = line.split()
            if (
                len(parts) != 10
                or any(re.fullmatch(r"[0-9]+", v) is None for v in parts[:3])
                or re.fullmatch(r"[0-4]", parts[9]) is None
            ):
                reject("daily row schema")
            day = date(*map(int, parts[:3]))
            numbers = [float(v) for v in parts[3:9]]
            if (
                not all(_finite(v) for v in numbers)
                or not numbers[0] <= numbers[2] <= numbers[1]
                or min(numbers[4:]) < 0
            ):
                reject("daily row numbers")
            if rows and day != rows[-1][0] + timedelta(days=1):
                reject("daily row chronology")
            rows.append((day, numbers[5], int(parts[9])))
        if len(rows) < 7 or rows[-1][0] != latest or LABELS[rows[-1][2]] != station.stress_level:
            reject("tail date, completeness or index label mismatch")
        return {
            "dhw_value": rows[-1][1],
            "baa_7day_max": rows[-1][2],
            "first_retained_date": rows[0][0].isoformat(),
            "last_retained_date": rows[-1][0].isoformat(),
            "complete_row_count": len(rows),
        }
    except (UnicodeError, ValueError, OverflowError):
        reject("malformed daily tail")


def decode_station(
    station: StationLink,
    index: dict,
    header_body: bytes,
    header: dict,
    tail_body: bytes,
    tail: dict,
    *,
    max_age_days: int,
) -> dict:
    """Construct the detached receipt only after checking the complete small packet."""
    latest = _day(index["index_date"])
    for receipt in [index, tail, header]:
        _fresh(latest, receipt["retrieved_at"], max_age_days)
    if (
        not _utc(index["retrieved_at"])
        <= _utc(tail["retrieved_at"])
        <= _utc(header["retrieved_at"])
    ):
        reject("request chronology")
    if len(header_body) != HEADER_BYTES or len(tail_body) != TAIL_BYTES:
        reject("range body length")
    for body, receipt in [(header_body, header), (tail_body, tail)]:
        if (
            receipt["response_bytes"] != len(body)
            or receipt["response_sha256"] != hashlib.sha256(body).hexdigest()
        ):
            reject("body receipt mismatch")
    meta, data = (
        _header(header_body, station, latest),
        _tail(tail_body, tail["range_start"], latest, station),
    )
    result = {
        "schema_version": 1,
        "source_product": PRODUCT,
        "source_name": SOURCE_NAME,
        "source_leg": LEG,
        "evidence_type": "satellite_analysis",
        "region_id": station.region_id,
        "region_full_name": station.region_full_name,
        "source_url": DATA_BASE + station.data_file,
        "valid_date": latest.isoformat(),
        "dhw_value": data.pop("dhw_value"),
        "unit": UNIT,
        "baa_7day_max": data.pop("baa_7day_max"),
        "baa_scale": "heritage_0_to_4",
        "baa_window_days": 7,
        "stress_level": station.stress_level,
        "marker_point": meta.pop("marker_point"),
        "marker_role": "regional_map_marker",
        "method": METHOD,
        "index": deepcopy(index),
        "header": {**deepcopy(header), **meta},
        "tail": {**deepcopy(tail), **data},
    }
    if not _receipt_valid(result):
        reject("source receipt binding")
    return result


def _digest(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _range_valid(r: dict, url: str, kind: str, prior: dict | None = None) -> bool:
    expected = HEADER_BYTES if kind == "header" else TAIL_BYTES
    if (
        r["source_url"] != url
        or not _digest(r["response_sha256"])
        or type(r["response_bytes"]) is not int
        or r["response_bytes"] != expected
    ):
        return False
    if not all(type(r[k]) is int for k in ["range_start", "range_end", "total_bytes"]):
        return False
    checked = response_range(
        206,
        {
            "ETag": r["etag"],
            "Content-Range": f"bytes {r['range_start']}-{r['range_end']}/{r['total_bytes']}",
        },
        kind=kind,
        prior=prior,
    )
    return all(r[k] == v for k, v in checked.items())


def _receipt_valid(p: Any) -> bool:
    try:
        if type(p) is not dict or set(p) != _RECEIPT_KEYS:
            return False
        fixed = {
            "schema_version": 1,
            "source_product": PRODUCT,
            "source_name": SOURCE_NAME,
            "source_leg": LEG,
            "evidence_type": "satellite_analysis",
            "unit": UNIT,
            "baa_scale": "heritage_0_to_4",
            "baa_window_days": 7,
            "marker_role": "regional_map_marker",
            "method": METHOD,
        }
        if any(type(p[k]) is not type(v) or p[k] != v for k, v in fixed.items()):
            return False
        if (
            not _safe_id(p["region_id"])
            or not _safe_name(p["region_full_name"])
            or not _finite(p["dhw_value"])
            or p["dhw_value"] < 0
        ):
            return False
        if (
            type(p["baa_7day_max"]) is not int
            or not 0 <= p["baa_7day_max"] <= 4
            or p["stress_level"] != LABELS[p["baa_7day_max"]]
        ):
            return False
        marker = p["marker_point"]
        if (
            type(marker) is not list
            or len(marker) != 2
            or not all(_finite(v) for v in marker)
            or not -90 <= marker[0] <= 90
            or not -180 <= marker[1] <= 180
        ):
            return False
        url = DATA_BASE + p["region_id"] + ".txt"
        if p["source_url"] != url:
            return False
        index, header, tail = p["index"], p["header"], p["tail"]
        if any(
            type(r) is not dict or set(r) != keys
            for r, keys in [(index, _INDEX_KEYS), (header, _HEADER_KEYS), (tail, _TAIL_KEYS)]
        ):
            return False
        if (
            index["source_url"] != INDEX_URL
            or not _digest(index["response_sha256"])
            or type(index["response_bytes"]) is not int
            or not 0 < index["response_bytes"] <= INDEX_LIMIT
        ):
            return False
        latest = _day(p["valid_date"])
        if index["index_date"] != p["valid_date"] or tail["last_retained_date"] != p["valid_date"]:
            return False
        for r in [index, tail, header]:
            _fresh(latest, r["retrieved_at"])
        if (
            not _utc(index["retrieved_at"])
            <= _utc(tail["retrieved_at"])
            <= _utc(header["retrieved_at"])
        ):
            return False
        # A retained receipt remains tied to its acquisition; prompt-time staleness
        # also rejects instead of allowing an old packet to re-enter the writer.
        _fresh(latest, now_utc())
        if not _range_valid(tail, url, "tail") or not _range_valid(header, url, "header", tail):
            return False
        if (
            type(header["columns"]) is not list
            or header["columns"] != COLUMNS
            or not _day(header["first_dhw_date"]) <= _day(header["first_baa_date"]) <= latest
        ):
            return False
        count = tail["complete_row_count"]
        if (
            type(count) is not int
            or not 7 <= count <= TAIL_BYTES // 20
            or latest - _day(tail["first_retained_date"]) != timedelta(days=count - 1)
        ):
            return False
        return True
    except (SourceFetchError, TypeError, KeyError, ValueError, OverflowError):
        return False


def qualified_provenance(event: Any) -> bool:
    p = getattr(event, "provenance", None)
    if not isinstance(p, dict) or not _receipt_valid(p):
        return False
    try:
        return (
            event.source_leg is None
            and event.source_name == SOURCE_NAME
            and _safe_id(event.region_id)
            and event.region_id == p["region_id"]
            and event.region_full_name == p["region_full_name"]
            and event.date == p["valid_date"]
            and _finite(event.dhw_value)
            and event.dhw_value == p["dhw_value"]
            and type(event.baa_7day_max) is int
            and event.baa_7day_max == p["baa_7day_max"]
            and event.stress_level == p["stress_level"]
            and _finite(event.lat)
            and _finite(event.lon)
            and [event.lat, event.lon] == p["marker_point"]
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
