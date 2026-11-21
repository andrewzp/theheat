"""Untrusted station nominations; this module cannot produce a weather observation.

The documented daily-summaries service is a lookup aid only. Requested metric
values choose which original .dly archives to check. They never enter a bundle,
QC flag, baseline, retained claim or writer input. Availability/schema/coverage
are not established by the existence of this client or by its offline tests.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException
import hashlib
import http.client
import json
import math
import re
import time
from types import MethodType
from typing import TYPE_CHECKING, Any

import requests
from requests.auth import AuthBase
from urllib3.exceptions import HTTPError as StreamError

if TYPE_CHECKING:
    from src.data.ghcn_format import StationThresholds

URL = "https://www.ncei.noaa.gov/access/services/data/v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 300_000
MAX_STATIONS = 500
MAX_REQUEST_URI_BYTES = 8192
READ_DEADLINE_SECONDS = 15
SOCKET_TIMEOUT_SECONDS = 5
_STATION = re.compile(r"[A-Z0-9]{11}\Z")
_NUMBER = re.compile(r"[+-]?\d{1,4}(?:\.\d{1,6})?\Z")
ERROR_MAX_BYTES = 8192
ERROR_FIELDS = frozenset({"dataset", "stations", "startDate", "endDate", "dataTypes", "bbox", "format", "units"})
UNIT_ERROR_MESSAGE = "Invalid units. Valid units are standard or metric."
UNIT_ERROR_MESSAGE = "Invalid units. Valid units are standard or metric."


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


def _json_number(value):
    if len(value) > 64:
        raise ValueError("unsupported_hint_number")
    try:
        result = Decimal(value)
    except DecimalException:
        raise ValueError("unsupported_hint_number") from None
    if not result.is_finite():
        raise ValueError("unsupported_hint_number")
    return result


def _reject_redirect(response, *args, **kwargs):
    # Requests prepares response.next even with allow_redirects=False. That
    # preparation reads the redirect body and may consult netrc. Abort in the
    # response hook, before either action; never inspect response.content.
    if 300 <= response.status_code < 400:
        response.close()
        raise requests.HTTPError("lookup_redirect_refused", response=response)
    return response


def _chunk_termination(raw):
    """Supported hex chunks, CRLF separators and empty trailer on this response only."""
    response = getattr(raw, "_fp", None)
    if not isinstance(response, http.client.HTTPResponse):
        raise ValueError("unsupported_lookup_framing")
    setattr(response, "_theheat_chunk_complete", False)

    def trailer(owner):
        if owner.fp.readline(2) != b"\r\n":
            raise ValueError("incomplete_or_unsupported_lookup_trailer")
        owner._theheat_chunk_complete = True

    setattr(response, "_read_and_discard_trailer", MethodType(trailer, response))

    def size(owner):
        line = owner.fp.readline(19)
        if not re.fullmatch(rb"[0-9a-fA-F]{1,16}\r\n", line):
            raise ValueError("unsupported_lookup_chunk_size")
        return int(line[:-2], 16)

    previous = getattr(response, "_get_chunk_left", None)
    if not callable(previous):
        raise ValueError("unsupported_lookup_chunk_reader")

    def next_chunk(owner):
        if owner.chunk_left == 0:
            if owner._safe_read(2) != b"\r\n":
                raise ValueError("unsupported_lookup_chunk_separator")
            owner.chunk_left = None  # the stdlib must not consume this separator twice
        return previous()

    setattr(response, "_read_next_chunk_size", MethodType(size, response))
    setattr(response, "_get_chunk_left", MethodType(next_chunk, response))
    return response


def _diagnostic_text(value):
    return (type(value) is str and 0 < len(value) <= 240
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
            and not re.search(r"https?://|www\.", value, re.IGNORECASE))


def _provider_error(response, deadline):
    """Read only a small, complete400 diagnostic before the shared helper closes it.

    No weather parsing, parameter repair, raw-body retention or retry. The same
    cooperative/socket bounds as the ordinary lookup apply, not a hard wall SLA.
    """
    from src.two_bot.call_inventory import current_cancel_token, OperationCancelled

    def cancelled():
        token = current_cancel_token()
        if token is not None and token.cancelled:
            raise OperationCancelled(str(token.reason))

    try:
        headers = response.headers
        if (headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"
                or headers.get("Content-Encoding", "identity").lower() != "identity"):
            return None
        length, transfer = headers.get("Content-Length"), headers.get("Transfer-Encoding")
        if transfer is not None and (transfer.lower() != "chunked" or length is not None):
            return None
        if length is not None and (not re.fullmatch(r"0|[1-9]\d{0,3}", length) or int(length) > ERROR_MAX_BYTES):
            return None
        if length is None and not transfer:
            return None
        framed = _chunk_termination(response.raw) if transfer else None
        chunks, received = [], 0
        while True:
            cancelled()
            if time.monotonic() > deadline:
                return None
            chunk = response.raw.read1(ERROR_MAX_BYTES + 1 - received, decode_content=False)
            cancelled()
            if time.monotonic() > deadline:
                return None
            if not chunk:
                break
            received += len(chunk)
            if received > ERROR_MAX_BYTES:
                return None
            chunks.append(chunk)
        if length is not None and received != int(length):
            return None
        if framed is not None and not getattr(framed, "_theheat_chunk_complete", False):
            return None
        body = b"".join(chunks)
        parsed = json.loads(body.decode("utf8"), object_pairs_hook=_object,
                            parse_float=_json_number, parse_constant=_constant)
        if (not isinstance(parsed, dict) or set(parsed) != {"errorCode", "errorMessage", "errors"}
                or type(parsed["errorCode"]) is not int or parsed["errorCode"] != 400
                or not _diagnostic_text(parsed["errorMessage"])
                or not isinstance(parsed["errors"], list) or not 1 <= len(parsed["errors"]) <= 8):
            return None
        fields = []
        for row in parsed["errors"]:
            if (not isinstance(row, dict) or not {"field", "message"} <= set(row) <= {"field", "message", "value"}
                    or type(row["field"]) is not str or row["field"] not in ERROR_FIELDS
                    or not _diagnostic_text(row["message"])):
                return None
            # A provider may echo even a value/header/URL inside its message.
            # Only a fixed public template becomes a fixed code; unknown text
            # is withheld entirely. No arbitrary provider text reaches storage.
            code = "invalid_units" if row["field"] == "units" and row["message"] == UNIT_ERROR_MESSAGE else "details_withheld"
            fields.append({"field": row["field"], "message_code": code})
        return {"schema_version": 1, "scope": "untrusted_provider_error_not_weather",
                "body_bytes": received, "body_sha256": hashlib.sha256(body).hexdigest(), "fields": fields}
    except (requests.RequestException, StreamError, http.client.HTTPException, OSError, ValueError, TypeError, AttributeError,
            UnicodeError, RecursionError, OverflowError, DecimalException):
        return None


def _value(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("unsupported_hint_value")
    if isinstance(value, str) and (len(value) > 32 or not _NUMBER.fullmatch(value)):
        raise ValueError("unsupported_hint_value")
    number = Decimal(value)
    if number == -9999:
        return None
    if not number.is_finite() or not -120 <= number <= 70:
        raise ValueError("unsupported_hint_value")
    return number


def _nominates(day, element, value, thresholds, anomaly):
    """A cached comparison is a lookup heuristic, never record qualification."""
    if thresholds is None:
        return False
    high = element == "TMAX"
    bounds = [thresholds.all_time_max_c if high else thresholds.all_time_min_c]
    monthly = thresholds.monthly_max if high else thresholds.monthly_min
    calendar = thresholds.calendar_date_max if high else thresholds.calendar_date_min
    bounds.extend((monthly.get(day.month, (None,))[0], calendar.get((day.month, day.day), (None,))[0]))
    if any(prior is not None and math.isfinite(prior)
           and (value > Decimal(str(prior)) if high else value < Decimal(str(prior))) for prior in bounds):
        return True
    mean = (thresholds.climatological_mean if high else thresholds.climatological_mean_min).get(day.month)
    return (mean is not None and math.isfinite(mean) and math.isfinite(anomaly)
            and anomaly > 0 and abs(value - Decimal(str(mean))) >= Decimal(str(anomaly)))


def nominate(body: bytes, eligible: frozenset[str], cached: dict[str, StationThresholds | None], *,
             today: date, cutoff: date, anomaly: float) -> tuple[set[str], dict[str, int]]:
    """Strict invented/received lookup format; no QC or unit agreement inferred."""
    if len(body) > MAX_BYTES:
        raise ValueError("hint_size")
    rows = json.loads(body.decode("utf-8"), object_pairs_hook=_object,
                      parse_float=_json_number, parse_constant=_constant)
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("unsupported_hint_rows")
    values: dict[tuple[str, date, str], Decimal | None] = {}
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
            except (ValueError, OverflowError, DecimalException):
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


def _station_window(eligible: frozenset[str], today: date, now: str | None) -> tuple[frozenset[str], dict[str, Any]]:
    """A finite lookup sample, not source availability or global coverage."""
    try:
        if now is not None and type(now) is not str:
            raise ValueError
        instant = (datetime.fromisoformat(now.replace("Z", "+00:00")) if now is not None
                   else datetime(today.year, today.month, today.day, tzinfo=timezone.utc))
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError
        instant = instant.astimezone(timezone.utc)
        if instant.date() != today:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError("unsupported_discovery_clock") from None
    ordered = sorted(eligible)
    windows = (len(ordered) + MAX_STATIONS - 1) // MAX_STATIONS
    bucket_hour = instant.hour // 4 * 4
    slot = (today.toordinal() * 6 + bucket_hour // 4) % windows
    selection = ordered[slot * MAX_STATIONS:(slot + 1) * MAX_STATIONS]
    metadata = {"schema_version": 1, "scope": "requested_nomination_subset_only",
                "strategy": "four_hour_stable_pool_cycle", "limit": MAX_STATIONS,
                "bucket_start": instant.replace(hour=bucket_hour, minute=0, second=0,
                                                 microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "cycle_chunks": windows, "chunk_index": slot,
                "eligible_stations": len(ordered), "selected_stations": len(selection),
                "unselected_stations": len(ordered) - len(selection),
                "pool_sha256": hashlib.sha256("\n".join(ordered).encode()).hexdigest(),
                "selection_sha256": hashlib.sha256("\n".join(selection).encode()).hexdigest(),
                "coverage_guaranteed": False}
    return frozenset(selection), metadata


def fetch_nominations(eligible: frozenset[str], cached: dict[str, StationThresholds | None], *,
                      today: date, max_age_days: int, anomaly: float,
                      now: str | None = None) -> tuple[set[str], dict[str, Any]]:
    """One counted request, no redirect/retry; unknown replies nominate nothing.

    The deadline is checked around raw client reads, with a socket inactivity
    timeout. It cannot interrupt DNS/OS or header/chunk-framing work inside the
    client; it is not a hard wall deadline or source SLA. Cancellation fences
    subsequent work once control returns. Hints are never observations.
    """
    from src.data._http import fetch_with_retry

    if (type(today) is not date or type(max_age_days) is not int or not 1 <= max_age_days <= 366
            or not eligible or any(not isinstance(sid, str) or not _STATION.fullmatch(sid) for sid in eligible)):
        raise ValueError("unsupported_discovery_input")
    cutoff = today - timedelta(days=min(max_age_days, 4))
    selected, station_selection = _station_window(eligible, today, now)
    params = {"dataset": "daily-summaries", "startDate": cutoff.isoformat(), "endDate": today.isoformat(),
              "dataTypes": "TMAX,TMIN", "units": "metric", "format": "json",
              "stations": ",".join(sorted(selected))}
    uri = requests.Request("GET", URL, params=params).prepare().url
    if uri is None or len(uri.encode("ascii")) > MAX_REQUEST_URI_BYTES:
        raise ValueError("discovery_request_uri_limit")
    station_selection["request_uri_bytes"] = len(uri.encode("ascii"))
    metadata: dict[str, Any] = {"schema_version": 1, "scope": "discovery_hints_not_observations",
        "status": "unavailable", "reason": "transport_unavailable", "http_status": None,
        "window_day": today.isoformat(), "cutoff_day": cutoff.isoformat(),
        "get_calls": 0, "max_get_calls": 1, "eligible_untracked_stations": len(eligible),
        "response_bytes": None, "response_sha256": None, "rows_received": None,
        "held_stations": None, "numeric_hints": None, "nominated_stations": 0,
        "station_selection": station_selection}

    def send(url, **kwargs):
        metadata["get_calls"] += 1
        reply = requests.get(url, **kwargs)
        if reply.status_code == 400:
            # This runs before fetch_with_retry's streamed-error close. It
            # observes this same response and cannot initiate another send.
            metadata.update(schema_version=2, provider_error=None)
            try:
                metadata["provider_error"] = _provider_error(reply, deadline)
            except BaseException:
                reply.close()
                raise
        return reply

    response = None
    try:
        deadline = time.monotonic() + READ_DEADLINE_SECONDS
        response = fetch_with_retry(URL, attempts=1, timeout=SOCKET_TIMEOUT_SECONDS, request=send,
            params=params,
            headers={"Accept": "application/json", "Accept-Encoding": "identity"},
            allow_redirects=False, stream=True, auth=_NoAuth(), hooks={"response": _reject_redirect})
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
        if transfer is not None and (transfer.lower() != "chunked" or length is not None):
            return set(), metadata
        if length is not None and (not re.fullmatch(r"0|[1-9]\d{0,8}", length) or int(length) > MAX_BYTES):
            return set(), metadata
        if length is None and not transfer:
            return set(), metadata
        framed = _chunk_termination(response.raw) if transfer else None
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
        if framed is not None and not getattr(framed, "_theheat_chunk_complete", False):
            return set(), metadata
        body = b"".join(chunks)
        metadata.update(response_bytes=received, response_sha256=hashlib.sha256(body).hexdigest())
        metadata["reason"] = "nomination_unavailable"
        candidates, counts = nominate(body, selected, cached, today=today, cutoff=cutoff, anomaly=anomaly)
        metadata.update(counts, status="nominated" if candidates else "no_nominations")
        metadata["reason"] = metadata["status"]
        return candidates, metadata
    except requests.HTTPError as exc:
        metadata.update(reason="http_error", http_status=getattr(exc.response, "status_code", None))
        return set(), metadata
    except (requests.RequestException, StreamError, OSError, ValueError, TypeError,
            UnicodeError, RecursionError, OverflowError, DecimalException):
        return set(), metadata
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            # A request already in flight stays spent. A response arriving
            # after cancellation cannot start the subsequent archive pool.
            from src.two_bot.call_inventory import current_cancel_token, OperationCancelled

            token = current_cancel_token()
            if token is not None and token.cancelled:
                raise OperationCancelled(str(token.reason))
