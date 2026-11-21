"""Untrusted station nominations; this module cannot produce a weather observation.

The documented daily-summaries service is a lookup aid only. Requested metric
values choose which original .dly archives to check. They never enter a bundle,
QC flag, baseline, retained claim or writer input. Availability/schema/coverage
are not established by the existence of this client or by its offline tests.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import math
import re
import time
from typing import TYPE_CHECKING, Any

import requests
from requests.auth import AuthBase
from urllib3.exceptions import HTTPError as StreamError

if TYPE_CHECKING:
    from src.data.ghcn_format import StationThresholds

URL = "https://www.ncei.noaa.gov/access/services/data/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 300_000
READ_DEADLINE_SECONDS = 15
SOCKET_TIMEOUT_SECONDS = 5
_STATION = re.compile(r"[A-Z0-9]{11}\Z")
_NUMBER = re.compile(r"[+-]?\d{1,4}(?:\.\d{1,6})?\Z")


class _NoAuth(AuthBase):
    def __call__(self, request):
        # A truthy auth handler prevents requests' implicit netrc lookup.
        return request


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous_hint_json")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("nonfinite_hint_json")


def _value(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("unsupported_hint_value")
    if isinstance(value, str) and (len(value) > 32 or not _NUMBER.fullmatch(value)):
        raise ValueError("unsupported_hint_value")
    number = float(value)
    if number == -9999:
        return None
    if not math.isfinite(number) or not -120 <= number <= 70:
        raise ValueError("unsupported_hint_value")
    return number


def _nominates(day, element, value, thresholds, anomaly):
    """A cached comparison is a lookup heuristic, never record qualification."""
    if thresholds is None:
        return True
    high = element == "TMAX"
    bounds = [thresholds.all_time_max_c if high else thresholds.all_time_min_c]
    monthly = thresholds.monthly_max if high else thresholds.monthly_min
    calendar = thresholds.calendar_date_max if high else thresholds.calendar_date_min
    bounds.extend((monthly.get(day.month, (None,))[0], calendar.get((day.month, day.day), (None,))[0]))
    if any(prior is not None and math.isfinite(prior)
           and (value > prior if high else value < prior) for prior in bounds):
        return True
    mean = (thresholds.climatological_mean if high else thresholds.climatological_mean_min).get(day.month)
    return (mean is not None and math.isfinite(mean) and math.isfinite(anomaly)
            and anomaly > 0 and abs(value - mean) >= anomaly)


def nominate(body: bytes, eligible: frozenset[str], cached: dict[str, StationThresholds | None], *,
             today: date, cutoff: date, anomaly: float) -> tuple[set[str], dict[str, int]]:
    """Strict invented/received lookup format; no QC or unit agreement inferred."""
    if len(body) > MAX_BYTES:
        raise ValueError("hint_size")
    rows = json.loads(body.decode("utf-8"), object_pairs_hook=_object,
                      parse_float=Decimal, parse_constant=_constant)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("unsupported_hint_rows")
    values: dict[tuple[str, date, str], float | None] = {}
    held: set[str] = set()
    recognized_rows = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("unsupported_hint_row")
        sid = row.get("STATION")
        if (isinstance(sid, str) and _STATION.fullmatch(sid)
                and isinstance(row.get("DATE"), str) and len(row["DATE"]) == 10
                and any(element in row for element in ("TMAX", "TMIN"))):
            recognized_rows += 1
        if not isinstance(sid, str) or not _STATION.fullmatch(sid) or sid not in eligible:
            continue
        raw_day = row.get("DATE")
        try:
            if not isinstance(raw_day, str) or len(raw_day) != 10:
                raise ValueError("hint_day")
            day = date.fromisoformat(raw_day)
            if day.isoformat() != raw_day:
                raise ValueError("hint_day")
        except ValueError:
            held.add(sid)
            continue
        if not cutoff <= day <= today:
            continue
        for element in ("TMAX", "TMIN"):
            if element not in row:
                continue
            key = (sid, day, element)
            try:
                value = _value(row[element])
            except (ValueError, OverflowError):
                held.add(sid)
                continue
            if key in values and values[key] != value:
                held.add(sid)
            values[key] = value
    if rows and not recognized_rows:
        raise ValueError("unsupported_hint_rows")
    candidates = {sid for (sid, day, element), value in values.items()
                  if sid not in held and value is not None
                  and _nominates(day, element, value, cached.get(sid), anomaly)}
    return candidates, {"rows_received": len(rows), "held_stations": len(held),
                        "numeric_hints": sum(value is not None for value in values.values()),
                        "nominated_stations": len(candidates)}


def fetch_nominations(eligible: frozenset[str], cached: dict[str, StationThresholds | None], *,
                      today: date, max_age_days: int, anomaly: float) -> tuple[set[str], dict[str, Any]]:
    """One counted request, no redirect/retry; unknown replies nominate nothing.

    The read deadline is checked around read1 (one socket read), with the normal
    client socket timeout as the final read bound. This is not a DNS/OS deadline,
    a source SLA, a financial cap or a claim that the hints are observations.
    """
    from src.data._http import fetch_with_retry

    if (type(today) is not date or type(max_age_days) is not int or not 1 <= max_age_days <= 366
            or not eligible or any(not isinstance(sid, str) or not _STATION.fullmatch(sid) for sid in eligible)):
        raise ValueError("unsupported_discovery_input")
    cutoff = today - timedelta(days=min(max_age_days, 4))
    metadata: dict[str, Any] = {"schema_version": 1, "scope": "discovery_hints_not_observations",
        "status": "unavailable", "reason": "transport_unavailable", "http_status": None,
        "window_day": today.isoformat(), "cutoff_day": cutoff.isoformat(),
        "get_calls": 0, "max_get_calls": 1, "eligible_untracked_stations": len(eligible),
        "response_bytes": None, "response_sha256": None, "rows_received": None,
        "held_stations": None, "numeric_hints": None, "nominated_stations": 0}

    def send(url, **kwargs):
        metadata["get_calls"] += 1
        return requests.get(url, **kwargs)

    response = None
    try:
        deadline = time.monotonic() + READ_DEADLINE_SECONDS
        response = fetch_with_retry(URL, attempts=1, timeout=SOCKET_TIMEOUT_SECONDS, request=send,
            params={"dataset": "daily-summaries", "startDate": cutoff.isoformat(), "endDate": today.isoformat(),
                    "dataTypes": "TMAX,TMIN", "units": "metric", "format": "json"},
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            allow_redirects=False, stream=True, auth=_NoAuth())
        metadata["http_status"] = response.status_code
        if response.status_code != 200:
            metadata["reason"] = "http_error"
            return set(), metadata
        metadata["reason"] = "headers_unsupported"
        if response.history:
            return set(), metadata
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return set(), metadata
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            return set(), metadata
        length = response.headers.get("Content-Length")
        transfer = response.headers.get("Transfer-Encoding")
        if transfer and (transfer.lower() != "chunked" or length is not None):
            return set(), metadata
        if length is not None and (not re.fullmatch(r"0|[1-9]\d{0,8}", length) or int(length) > MAX_BYTES):
            return set(), metadata
        if length is None and not transfer:
            return set(), metadata
        metadata["reason"] = "transport_unavailable"
        chunks, received = [], 0
        while True:
            if time.monotonic() > deadline:
                metadata["reason"] = "read_deadline"
                return set(), metadata
            chunk = response.raw.read1(65536, decode_content=False)
            if time.monotonic() > deadline:
                metadata["reason"] = "read_deadline"
                return set(), metadata
            if not chunk:
                break
            received += len(chunk)
            if received > MAX_BYTES:
                metadata["reason"] = "body_limit"
                return set(), metadata
            chunks.append(chunk)
        if length is not None and received != int(length):
            metadata["reason"] = "body_length_mismatch"
            return set(), metadata
        body = b"".join(chunks)
        metadata.update(response_bytes=received, response_sha256=hashlib.sha256(body).hexdigest())
        metadata["reason"] = "nomination_unavailable"
        candidates, counts = nominate(body, eligible, cached, today=today, cutoff=cutoff, anomaly=anomaly)
        metadata.update(counts, status="nominated" if candidates else "no_nominations")
        metadata["reason"] = metadata["status"]
        return candidates, metadata
    except requests.HTTPError as exc:
        metadata.update(reason="http_error", http_status=getattr(exc.response, "status_code", None))
        return set(), metadata
    except (requests.RequestException, StreamError, OSError, ValueError, TypeError,
            UnicodeError, RecursionError, OverflowError):
        return set(), metadata
    finally:
        if response is not None:
            response.close()
