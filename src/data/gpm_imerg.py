"""NASA GPM IMERG daily precipitation point checks.

Operational daily reads use the IMERG Late daily product so the bot can smoke
recent data. The Final product remains the archive reference, but it lags by
months and is not suitable for "today" checks.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
import csv
import io
import os
import re
from pathlib import Path
from typing import Any

import requests

from src.data._http import fetch_with_retry
from src.data._s3credentials import get_s3_credentials
from src.data.source_status import SourceFetchError, SourceSkipped

LATE_OPENDAP_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDL.07"
FINAL_OPENDAP_BASE = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGDF.07"

# Alternate fetch paths that download the full daily grid once and subset every
# city locally — one request per run instead of 75 per-city OPeNDAP subsets.
# The legacy OPeNDAP host (gpm1.gesdisc) is the one that intermittently
# ConnectTimeouts under load; both alternates live on different hosts.
#   - data-pool: an authenticated HTTPS GET of the .nc4 file (no AWS deps)
#   - s3:        a direct GetObject from the GES DISC cumulus bucket
DATAPOOL_BASE = "https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3"
S3_BUCKET = "gesdisc-cumulus-prod-protected"
S3_PREFIX = "GPM_L3"
S3_REGION = "us-west-2"

GRID_STEP_DEGREES = 0.1
LON_CELLS = 3600
LAT_CELLS = 1800
FILL_VALUE = -9999.0
DEFAULT_RECORD_MARGIN_MM = 20.0
DEFAULT_CITY_LIMIT = 75
DEFAULT_MAX_WORKERS = 8
PRECIP_HISTORY_DAYS = 10
STRICT_REPEATED_FAILURE_LIMIT = 3
# NASA GES DISC OPeNDAP service is intermittently slow under load — it
# generates `.nc4.ascii` subsets on-the-fly per request and that work can
# routinely take 30-55s. The bot's prior 30s hard timeout was too aggressive
# and produced a 13% success rate on the source-health dashboard. 60s catches
# the long tail without false-positive stalls; env var lets us tune if NASA's
# behavior shifts.
DEFAULT_REQUEST_TIMEOUT_S = 60.0
DEFAULT_RETRY_BACKOFF_S = 10.0
# The Late daily product publishes ~1-2 days after the observation date, so the
# default "yesterday" request is frequently a 404. Walk back up to this many
# days to the most recent file that actually exists. Env-tunable.
DEFAULT_MAX_LOOKBACK_DAYS = 5
# Reference point for the date-availability probe — any valid grid cell works;
# we only care whether the file exists (200 vs 404), not the precip value.
_PROBE_REFERENCE_LAT = 0.0
_PROBE_REFERENCE_LON = 0.0

# Fetch source, selectable via THEHEAT_GPM_SOURCE. "opendap" is the proven
# legacy per-city path and the default; "datapool"/"s3" download the whole grid
# once and subset locally. An unknown/empty value degrades to "opendap" so a
# misconfigured var can never make the source worse than today.
DEFAULT_GPM_SOURCE = "opendap"
_GPM_SOURCES = frozenset({"opendap", "datapool", "s3"})


class _GridNotFound(Exception):
    """The grid file for a candidate date is not published (404 / S3 403 /
    NoSuchKey). Walk back to an earlier date."""


class _GridTransient(Exception):
    """A transient grid-fetch failure (5xx, timeout, connection, auth). Not a
    date-availability signal — stop walking back."""


class _GridParseError(Exception):
    """The downloaded grid could not be opened/parsed into city readings."""


class _GridFetchUnavailable(Exception):
    """The grid path could not deliver readings; the caller falls back to the
    legacy OPeNDAP per-city path so gpm is never worse than before."""


@dataclass(frozen=True)
class CityPrecipReading:
    city: str
    country: str
    lat: float
    lon: float
    date: str
    mm_total: float
    source_product: str
    event_id: str


@dataclass(frozen=True)
class PrecipExtremeEvent:
    kind: str
    location: str
    country: str
    date: str
    mm_total: float
    period_days: int
    deviation_from_record_mm: float | None
    previous_record_mm: float | None
    previous_record_year: int | None
    lat: float
    lon: float
    city_count: int | None
    sample_cities: list[str]
    event_id: str


def load_cities(cities_path: str = "data/cities.csv") -> list[dict[str, str]]:
    with Path(cities_path).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_daily_precip(
    cities: list[Mapping[str, Any]] | None = None,
    *,
    target_date: date | None = None,
    product: str = "late",
    max_cities: int | None = DEFAULT_CITY_LIMIT,
    max_workers: int | None = DEFAULT_MAX_WORKERS,
    strict: bool = False,
) -> list[CityPrecipReading]:
    """Fetch point daily precipitation for monitored cities.

    Returns city readings sorted in input order. Missing credentials skip the
    source in non-strict mode; strict mode raises so smoke tests can fail loud.
    """

    token = os.environ.get("EARTHDATA_TOKEN", "")
    if not token:
        print("[gpm_imerg] EARTHDATA_TOKEN not configured — skipping")
        if strict:
            raise SourceSkipped("EARTHDATA_TOKEN is not configured")
        return []

    # Grid sources download the daily file once and subset locally. On any
    # failure they raise _GridFetchUnavailable and we fall through to the next
    # configured grid source, then finally the legacy OPeNDAP per-city path, so
    # alternate feeds can never regress gpm.
    source = _gpm_source()
    for grid_source in _gpm_grid_source_chain(source):
        try:
            return _fetch_daily_precip_grid(
                grid_source,
                cities,
                target_date=target_date,
                product=product,
                max_cities=max_cities,
                token=token,
            )
        except _GridFetchUnavailable as exc:
            next_path = "datapool" if grid_source == "s3" else "opendap"
            print(
                f"[gpm_imerg] {grid_source} grid path unavailable ({exc}); "
                f"falling back to {next_path}",
                flush=True,
            )

    headers = {"Authorization": f"Bearer {token}"}
    if target_date is not None:
        requested_date = target_date
    else:
        # No explicit date: walk back to the latest published Late file rather
        # than blindly requesting yesterday (a 404 before NASA posts it, which
        # is correctly non-retryable and so silently failed the whole source).
        requested_date = _resolve_available_date(
            start_date=_default_start_date(),
            product=product,
            headers=headers,
            max_lookback=_max_lookback_days(),
        )
    rows = cities if cities is not None else load_cities()
    selected = list(rows if max_cities is None else rows[:max_cities])
    readings_by_index: list[CityPrecipReading | None] = [None] * len(selected)
    failures = 0
    first_failure_detail: str | None = None
    failure_counts: dict[str, int] = {}
    worker_count = _bounded_worker_count(max_workers, len(selected))

    def fetch_one(index: int, city: Mapping[str, Any]) -> tuple[int, CityPrecipReading | None]:
        city_name = str(city["city"])
        country = str(city["country"])
        lat = float(city["lat"])
        lon = float(city["lon"])
        mm_total = _fetch_city_precip(
            lat=lat,
            lon=lon,
            target_date=requested_date,
            product=product,
            headers=headers,
        )
        if mm_total is None:
            return index, None
        city_key = _safe_key(city_name)
        country_key = _safe_key(country)
        date_key = requested_date.isoformat()
        return index, CityPrecipReading(
            city=city_name,
            country=country,
            lat=lat,
            lon=lon,
            date=date_key,
            mm_total=mm_total,
            source_product=product,
            event_id=f"gpm_imerg_{country_key}_{city_key}_{date_key}",
        )

    def handle_failure(exc: Exception) -> None:
        nonlocal failures, first_failure_detail
        failures += 1
        failure_signature = _failure_signature(exc)
        failure_counts[failure_signature] = failure_counts.get(failure_signature, 0) + 1
        if first_failure_detail is None:
            first_failure_detail = _diagnose_city_failure(exc)
            print(
                f"[gpm_imerg] first per-city failure: {first_failure_detail}",
                flush=True,
            )
        if strict and cities is not None and len(selected) == 1:
            raise SourceFetchError(
                f"GPM IMERG city fetch failed: {first_failure_detail}"
            ) from exc
        if strict and _is_auth_failure(exc):
            raise SourceFetchError(
                f"GPM IMERG city fetch failed after {failures} failed: "
                f"{first_failure_detail}"
            ) from exc
        if strict and failure_counts[failure_signature] >= STRICT_REPEATED_FAILURE_LIMIT:
            raise SourceFetchError(
                f"GPM IMERG fetch hit {failure_counts[failure_signature]} "
                f"repeated {failure_signature} failures for "
                f"{requested_date.isoformat()}; first error: "
                f"{first_failure_detail}"
            ) from exc

    # Strict mode probes the first few cities serially so broken auth or a
    # provider-wide outage fails fast before the scheduled job fans out.
    probe_count = min(len(selected), STRICT_REPEATED_FAILURE_LIMIT) if strict else 0
    for index, city in enumerate(selected[:probe_count]):
        try:
            idx, reading = fetch_one(index, city)
        except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
            handle_failure(exc)
            continue
        readings_by_index[idx] = reading

    remaining = list(enumerate(selected[probe_count:], start=probe_count))
    if worker_count <= 1:
        for index, city in remaining:
            try:
                idx, reading = fetch_one(index, city)
            except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
                handle_failure(exc)
                continue
            readings_by_index[idx] = reading
    elif remaining:
        executor = ThreadPoolExecutor(max_workers=min(worker_count, len(remaining)))
        try:
            futures = {
                executor.submit(fetch_one, index, city): index
                for index, city in remaining
            }
            for future in as_completed(futures):
                try:
                    idx, reading = future.result()
                except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
                    handle_failure(exc)
                    continue
                readings_by_index[idx] = reading
        finally:
            # Once we've decided to fail (handle_failure raised), don't block on
            # the rest of the doomed fan-out. A plain `with ThreadPoolExecutor()`
            # exits via shutdown(wait=True), which runs every queued city fetch
            # to completion — so an intermittent NASA outage burned ~28 min
            # finishing all 75 doomed fetches after the strict failure limit
            # already tripped. Cancel pending futures and don't wait on in-flight
            # ones; the source fails immediately and the orphaned fetches die on
            # their own timeout. On the success path nothing is pending, so this
            # is a no-op.
            executor.shutdown(wait=False, cancel_futures=True)

    readings = [reading for reading in readings_by_index if reading is not None]
    if strict and not readings:
        detail = (
            f"; first error: {first_failure_detail}"
            if first_failure_detail
            else ""
        )
        raise SourceFetchError(
            f"GPM IMERG fetch returned no city readings for {requested_date.isoformat()} "
            f"({failures} failed){detail}"
        )
    return readings


def _bounded_worker_count(max_workers: int | None, selected_count: int) -> int:
    if selected_count <= 1:
        return 1
    if max_workers is None:
        return min(DEFAULT_MAX_WORKERS, selected_count)
    try:
        value = int(max_workers)
    except (TypeError, ValueError):
        return min(DEFAULT_MAX_WORKERS, selected_count)
    return min(max(value, 1), selected_count)


def _diagnose_city_failure(exc: Exception) -> str:
    """Short diagnostic for a per-city fetch failure: HTTP status + URL for
    HTTPError, exception type + message otherwise. The 2026-05-13 GPM-IMERG
    lane shipped (PR #116) and silently failed for 4 days with a "638 failed"
    summary that masked whether the cause was auth (401), endpoint drift
    (404), or NASA outage (5xx/Timeout). Surfacing the first failure's
    status + URL converts blind failure into one-line diagnosis.
    """
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code} from {exc.response.url}"
    return f"{type(exc).__name__}: {exc}"


def _http_status(exc: Exception) -> int | None:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return exc.response.status_code
    return None


def _is_auth_failure(exc: Exception) -> bool:
    return _http_status(exc) in {401, 403}


def _failure_signature(exc: Exception) -> str:
    status = _http_status(exc)
    if status is not None:
        return f"HTTP {status}"
    return type(exc).__name__


def detect_precip_records(
    readings: list[CityPrecipReading],
    state: Mapping[str, Any] | None = None,
    *,
    record_margin_mm: float = DEFAULT_RECORD_MARGIN_MM,
    min_country_records: int = 10,
) -> list[PrecipExtremeEvent]:
    tracking = state or {}
    events: list[PrecipExtremeEvent] = []
    daily_records = tracking.get("precip_daily_records", {})
    if not isinstance(daily_records, Mapping):
        daily_records = {}

    for reading in readings:
        key = _daily_record_key(reading)
        previous = daily_records.get(key)
        previous_mm = _record_mm(previous)
        if previous_mm is not None and reading.mm_total >= previous_mm + record_margin_mm:
            events.append(PrecipExtremeEvent(
                kind="daily_record",
                location=reading.city,
                country=reading.country,
                date=reading.date,
                mm_total=reading.mm_total,
                period_days=1,
                deviation_from_record_mm=reading.mm_total - previous_mm,
                previous_record_mm=previous_mm,
                previous_record_year=_record_year(previous),
                lat=reading.lat,
                lon=reading.lon,
                city_count=None,
                sample_cities=[],
                event_id=f"gpm_precip_record_{_safe_key(reading.country)}_"
                f"{_safe_key(reading.city)}_{reading.date}",
            ))

    events.extend(_detect_rolling_accumulations(readings, tracking))
    events.extend(_detect_country_events(events, min_country_records=min_country_records))
    return events


def update_precip_tracking(
    state: MutableMapping[str, Any],
    readings: Iterable[CityPrecipReading],
    *,
    max_history_days: int = PRECIP_HISTORY_DAYS,
) -> None:
    daily = state.setdefault("precip_daily_records", {})
    recent = state.setdefault("precip_recent_by_city", {})
    for reading in readings:
        daily_key = _daily_record_key(reading)
        current = daily.get(daily_key) if isinstance(daily, MutableMapping) else None
        current_mm = _record_mm(current)
        if current_mm is None or reading.mm_total > current_mm:
            daily[daily_key] = {
                "mm": reading.mm_total,
                "year": int(reading.date[:4]),
                "date": reading.date,
            }

        city_key = _city_key(reading)
        rows = recent.setdefault(city_key, [])
        if not isinstance(rows, list):
            rows = []
            recent[city_key] = rows
        rows = [row for row in rows if isinstance(row, Mapping) and row.get("date") != reading.date]
        rows.append({"date": reading.date, "mm": reading.mm_total})
        rows.sort(key=lambda row: str(row.get("date") or ""))
        recent[city_key] = rows[-max_history_days:]


def _request_timeout_s() -> float:
    """Per-request OPeNDAP timeout. Configurable via GPM_IMERG_TIMEOUT_S."""
    raw = os.environ.get("GPM_IMERG_TIMEOUT_S")
    if not raw:
        return DEFAULT_REQUEST_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_REQUEST_TIMEOUT_S
    return value if value > 0 else DEFAULT_REQUEST_TIMEOUT_S


def _retry_backoff_s() -> float:
    """Sleep between retry attempts. Configurable via GPM_IMERG_RETRY_BACKOFF_S.

    Tests set this to 0 to avoid real-time sleeps.
    """
    raw = os.environ.get("GPM_IMERG_RETRY_BACKOFF_S")
    if not raw:
        return DEFAULT_RETRY_BACKOFF_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_RETRY_BACKOFF_S
    return value if value >= 0 else DEFAULT_RETRY_BACKOFF_S


def _default_start_date() -> date:
    """First date to try for the Late daily product: yesterday."""
    return date.today() - timedelta(days=1)


def _max_lookback_days() -> int:
    """How many days to walk back probing for a published file.

    Configurable via GPM_IMERG_MAX_LOOKBACK_DAYS (tests bound it; ops can widen
    it if NASA's publish latency grows).
    """
    raw = os.environ.get("GPM_IMERG_MAX_LOOKBACK_DAYS")
    if not raw:
        return DEFAULT_MAX_LOOKBACK_DAYS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_LOOKBACK_DAYS
    return value if value >= 0 else DEFAULT_MAX_LOOKBACK_DAYS


def _resolve_available_date(
    *,
    start_date: date,
    product: str,
    headers: Mapping[str, str],
    max_lookback: int,
) -> date:
    """Find the most recent date whose IMERG file is actually published.

    The Late daily product lags 1-2 days, so the default "yesterday" request is
    frequently a 404 — NASA has not posted it yet. That 404 is (correctly) not
    retried, so historically it silently failed the entire source. Probe one
    reference point per candidate date and step back until a file exists:

      - HTTP 200  -> published; use this date.
      - HTTP 404  -> not yet published; try the day before.
      - anything else (5xx, timeout, connection error) -> NOT a date-availability
        signal, so stop and use the current candidate; the per-city fetches retry
        and surface transient outages exactly as before.

    Walks back at most ``max_lookback`` days, then returns the oldest candidate
    (per-city fetches then fail as they did pre-fix — safe degradation, never
    worse than the old fixed-"yesterday" behavior).
    """
    timeout_s = _request_timeout_s()
    request_headers = dict(headers)
    oldest_candidate = start_date
    for offset in range(max(max_lookback, 0) + 1):
        candidate = start_date - timedelta(days=offset)
        oldest_candidate = candidate
        url = _ascii_subset_url(
            lat=_PROBE_REFERENCE_LAT,
            lon=_PROBE_REFERENCE_LON,
            target_date=candidate,
            product=product,
            variable="precipitation",
        )
        try:
            # bare-get: migrated in S-09 with GPM source-chain retry semantics.
            resp = requests.get(url, headers=request_headers, timeout=timeout_s)
            resp.raise_for_status()
            return candidate
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 404:
                continue
            return candidate
        except requests.RequestException:
            return candidate
    return oldest_candidate


def _fetch_city_precip(
    *,
    lat: float,
    lon: float,
    target_date: date,
    product: str,
    headers: Mapping[str, str],
) -> float | None:
    """Fetch one city's daily precip from GPM IMERG OPeNDAP.

    Retries ONCE on transient errors (read timeout, connection error, 5xx).
    Persistent errors (4xx auth, 404, validation) raise immediately so the
    strict-mode probe can fail fast on real outages without burning retry
    budget on guaranteed failures.
    """
    variable = "precipitation"
    url = _ascii_subset_url(
        lat=lat,
        lon=lon,
        target_date=target_date,
        product=product,
        variable=variable,
    )
    timeout_s = _request_timeout_s()
    request_headers = dict(headers)
    resp = fetch_with_retry(
        url,
        headers=request_headers,
        timeout=timeout_s,
        attempts=2,
        backoff_base=_retry_backoff_s(),
    )
    value = _parse_ascii_value(resp.text, variable)
    if value is None or value <= FILL_VALUE:
        return None
    return max(value, 0.0)


def _gpm_source() -> str:
    """Resolve the configured fetch source from THEHEAT_GPM_SOURCE.

    Unknown or empty values fall back to the legacy OPeNDAP path, so a typo or a
    half-rolled-out repo var degrades safely instead of breaking the source.
    """
    raw = (os.environ.get("THEHEAT_GPM_SOURCE") or "").strip().lower()
    return raw if raw in _GPM_SOURCES else DEFAULT_GPM_SOURCE


def _gpm_grid_source_chain(source: str) -> tuple[str, ...]:
    if source == "s3":
        return ("s3", "datapool")
    if source == "datapool":
        return ("datapool",)
    return ()


def _imerg_collection(product: str) -> str:
    product_key = product.lower()
    if product_key == "final":
        return "GPM_3IMERGDF.07"
    if product_key == "late":
        return "GPM_3IMERGDL.07"
    raise ValueError(f"unknown GPM IMERG product: {product}")


def _imerg_filename(product: str, target_date: date) -> str:
    """The daily IMERG .nc4 filename, shared by the OPeNDAP, data-pool, and S3
    paths so the three can never drift on version letter or time suffix."""
    product_key = product.lower()
    if product_key == "final":
        return f"3B-DAY.MS.MRG.3IMERG.{target_date:%Y%m%d}-S000000-E235959.V07B.nc4"
    if product_key == "late":
        return f"3B-DAY-L.MS.MRG.3IMERG.{target_date:%Y%m%d}-S000000-E235959.V07C.nc4"
    raise ValueError(f"unknown GPM IMERG product: {product}")


def _imerg_relpath(product: str, target_date: date) -> str:
    """``<collection>/<YYYY>/<MM>/<filename>`` — the path segment under the
    shared ``GPM_L3`` root used to build both S3 keys and data-pool URLs."""
    return (
        f"{_imerg_collection(product)}/{target_date:%Y}/{target_date:%m}/"
        f"{_imerg_filename(product, target_date)}"
    )


def _ascii_subset_url(
    *,
    lat: float,
    lon: float,
    target_date: date,
    product: str,
    variable: str,
) -> str:
    product_key = product.lower()
    if product_key == "final":
        base = FINAL_OPENDAP_BASE
    elif product_key == "late":
        base = LATE_OPENDAP_BASE
    else:
        raise ValueError(f"unknown GPM IMERG product: {product}")
    filename = _imerg_filename(product, target_date)

    lon_index = _lon_index(lon)
    lat_index = _lat_index(lat)
    subset = (
        f"{variable}[0:1:0][{lon_index}:1:{lon_index}][{lat_index}:1:{lat_index}],"
        f"lat[{lat_index}:1:{lat_index}],lon[{lon_index}:1:{lon_index}]"
    )
    return f"{base}/{target_date:%Y}/{target_date:%m}/{filename}.ascii?{subset}"


def _parse_ascii_value(text: str, variable: str = "precipitation") -> float | None:
    for line in text.splitlines():
        stripped = line.strip()
        if variable not in stripped or "," not in stripped:
            continue
        raw = stripped.rsplit(",", 1)[1].strip().rstrip(";")
        try:
            return float(raw)
        except ValueError:
            continue
    return None


def _fetch_daily_precip_grid(
    source: str,
    cities: list[Mapping[str, Any]] | None,
    *,
    target_date: date | None,
    product: str,
    max_cities: int | None,
    token: str,
) -> list[CityPrecipReading]:
    """Download the daily IMERG grid once (via ``source``) and subset every
    monitored city locally. Raises _GridFetchUnavailable on any failure so the
    caller can fall back to the legacy OPeNDAP per-city path.
    """
    rows = cities if cities is not None else load_cities()
    selected = list(rows if max_cities is None else rows[:max_cities])
    try:
        if target_date is not None:
            resolved_date = target_date
            grid_bytes = _fetch_grid_bytes(
                source, target_date=resolved_date, product=product, token=token
            )
        else:
            resolved_date, grid_bytes = _fetch_grid_with_walkback(
                source,
                start_date=_default_start_date(),
                product=product,
                token=token,
                max_lookback=_max_lookback_days(),
            )
        readings = _subset_grid(
            grid_bytes, selected, resolved_date=resolved_date, product=product
        )
    except (_GridNotFound, _GridTransient, _GridParseError) as exc:
        raise _GridFetchUnavailable(str(exc)) from exc
    if not readings:
        raise _GridFetchUnavailable(
            f"0 city readings parsed from {source} grid for {resolved_date.isoformat()}"
        )
    return readings


def _fetch_grid_with_walkback(
    source: str,
    *,
    start_date: date,
    product: str,
    token: str,
    max_lookback: int,
) -> tuple[date, bytes]:
    """Walk back from ``start_date`` downloading the first published grid.

    The Late product lags 1-2 days, so the most recent file is usually
    yesterday's. A not-found candidate steps back; a transient error stops the
    walk (it is not a date-availability signal) and propagates so we fall back
    rather than masking an outage as 'no data'.
    """
    oldest_probed: date | None = None
    for offset in range(max(max_lookback, 0) + 1):
        candidate = start_date - timedelta(days=offset)
        oldest_probed = candidate
        try:
            return candidate, _fetch_grid_bytes(
                source, target_date=candidate, product=product, token=token
            )
        except _GridNotFound:
            continue
    raise _GridNotFound(
        f"no published {source} grid within {max(max_lookback, 0) + 1} days back "
        f"from {start_date.isoformat()}"
        + (f" (oldest probed {oldest_probed.isoformat()})" if oldest_probed else "")
    )


def _fetch_grid_bytes(
    source: str, *, target_date: date, product: str, token: str
) -> bytes:
    if source == "datapool":
        return _fetch_grid_bytes_datapool(
            target_date=target_date, product=product, token=token
        )
    if source == "s3":
        return _fetch_grid_bytes_s3(
            target_date=target_date, product=product, token=token
        )
    raise ValueError(f"grid fetch not supported for source: {source}")


def _fetch_grid_bytes_datapool(*, target_date: date, product: str, token: str) -> bytes:
    """GET the daily .nc4 from the GES DISC data pool (authenticated HTTPS).

    This host (data.gesdisc.earthdata.nasa.gov) is distinct from the overloaded
    gpm1.gesdisc OPeNDAP host, so it escapes the per-cell subset-compute load
    with no AWS dependency.
    """
    url = f"{DATAPOOL_BASE}/{_imerg_relpath(product, target_date)}"
    timeout_s = _request_timeout_s()
    try:
        # bare-get: migrated in S-09 with GPM datapool status handling.
        resp = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout_s
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise _GridTransient(f"datapool connection error: {exc}") from exc
    if resp.status_code == 404:
        raise _GridNotFound(f"datapool 404 for {url}")
    if resp.status_code in (401, 403):
        raise _GridTransient(f"datapool auth error HTTP {resp.status_code} for {url}")
    if resp.status_code >= 500:
        raise _GridTransient(f"datapool HTTP {resp.status_code} for {url}")
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise _GridTransient(f"datapool HTTP error: {exc}") from exc
    return resp.content


def _fetch_grid_bytes_s3(*, target_date: date, product: str, token: str) -> bytes:
    """GetObject the daily .nc4 from the GES DISC cumulus S3 bucket using
    temporary credentials minted from the Earthdata token.

    boto3 is imported lazily so a missing dependency degrades to the fallback
    chain rather than breaking module import or the default OPeNDAP path.
    """
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover - exercised only without boto3
        raise _GridTransient(f"boto3 not installed: {exc}") from exc

    try:
        creds = get_s3_credentials(token)
    except (requests.RequestException, ValueError) as exc:
        raise _GridTransient(f"s3 credential mint failed: {exc}") from exc

    key = f"{S3_PREFIX}/{_imerg_relpath(product, target_date)}"
    client = boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        aws_session_token=creds.session_token,
    )
    try:
        response = client.get_object(Bucket=S3_BUCKET, Key=key)
        return bytes(response["Body"].read())
    except ClientError as exc:
        meta = getattr(exc, "response", {}) or {}
        status = meta.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = str(meta.get("Error", {}).get("Code", ""))
        # The temp role has no s3:ListBucket, so a missing key returns
        # 403/AccessDenied rather than 404 — treat both as "not published".
        if status in (403, 404) or code in {
            "404",
            "403",
            "NoSuchKey",
            "AccessDenied",
            "NoSuchBucket",
        }:
            raise _GridNotFound(f"s3 {code or status} for {key}") from exc
        raise _GridTransient(f"s3 ClientError {code or status} for {key}") from exc
    except BotoCoreError as exc:
        raise _GridTransient(f"s3 BotoCoreError: {exc}") from exc


def _subset_grid(
    grid_bytes: bytes,
    cities: list[Mapping[str, Any]],
    *,
    resolved_date: date,
    product: str,
) -> list[CityPrecipReading]:
    """Parse a daily IMERG grid and extract each city's precip via the same
    lat/lon index math the OPeNDAP path uses. Fill-value cells become skips,
    exactly as the per-city path returns None for them.
    """
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - exercised only without h5py
        raise _GridParseError(f"h5py not installed: {exc}") from exc

    try:
        with h5py.File(io.BytesIO(grid_bytes), "r") as handle:
            dataset = _find_precip_dataset(handle)
            grid = dataset[...]
    except OSError as exc:
        raise _GridParseError(f"could not open IMERG grid: {exc}") from exc

    if grid.ndim != 3 or grid.shape[1] != LON_CELLS or grid.shape[2] != LAT_CELLS:
        raise _GridParseError(
            f"unexpected precipitation grid shape {tuple(grid.shape)}; "
            f"expected (_, {LON_CELLS}, {LAT_CELLS})"
        )

    date_key = resolved_date.isoformat()
    readings: list[CityPrecipReading] = []
    for city in cities:
        try:
            city_name = str(city["city"])
            country = str(city["country"])
            lat = float(city["lat"])
            lon = float(city["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        value = float(grid[0, _lon_index(lon), _lat_index(lat)])
        if value <= FILL_VALUE:
            continue
        readings.append(
            CityPrecipReading(
                city=city_name,
                country=country,
                lat=lat,
                lon=lon,
                date=date_key,
                mm_total=max(value, 0.0),
                source_product=product,
                event_id=f"gpm_imerg_{_safe_key(country)}_{_safe_key(city_name)}_{date_key}",
            )
        )
    return readings


def _find_precip_dataset(handle: Any) -> Any:
    """Locate the ``precipitation`` dataset whether the file keeps it at the root
    or under a ``Grid`` group (IMERG HDF5 layout has varied across products)."""
    import h5py

    for path in ("precipitation", "Grid/precipitation"):
        node = handle.get(path)
        if isinstance(node, h5py.Dataset):
            return node

    found: list[Any] = []

    def _visit(name: str, obj: Any) -> None:
        if isinstance(obj, h5py.Dataset) and name.rsplit("/", 1)[-1] == "precipitation":
            found.append(obj)

    handle.visititems(_visit)
    if found:
        return found[0]
    raise _GridParseError("no 'precipitation' dataset found in IMERG grid")


def _lon_index(lon: float) -> int:
    normalized = ((lon + 180.0) % 360.0) - 180.0
    index = int(round((normalized + 179.95) / GRID_STEP_DEGREES))
    return min(max(index, 0), LON_CELLS - 1)


def _lat_index(lat: float) -> int:
    index = int(round((lat + 89.95) / GRID_STEP_DEGREES))
    return min(max(index, 0), LAT_CELLS - 1)


def _detect_rolling_accumulations(
    readings: list[CityPrecipReading],
    state: Mapping[str, Any],
) -> list[PrecipExtremeEvent]:
    recent_by_city = state.get("precip_recent_by_city", {})
    if not isinstance(recent_by_city, Mapping):
        recent_by_city = {}

    events: list[PrecipExtremeEvent] = []
    thresholds = {3: 150.0, 7: 300.0}
    for reading in readings:
        prior_rows = recent_by_city.get(_city_key(reading), [])
        rows = [
            {"date": str(row.get("date")), "mm": float(row.get("mm", 0.0))}
            for row in prior_rows
            if isinstance(row, Mapping) and row.get("date")
        ]
        rows = [row for row in rows if row["date"] != reading.date]
        rows.append({"date": reading.date, "mm": reading.mm_total})
        rows.sort(key=lambda row: row["date"])
        for period_days, threshold_mm in thresholds.items():
            window = rows[-period_days:]
            if len(window) != period_days or not _dates_are_consecutive([row["date"] for row in window]):
                continue
            total = sum(float(row["mm"]) for row in window)
            if total < threshold_mm:
                continue
            events.append(PrecipExtremeEvent(
                kind="multi_day_accumulation",
                location=reading.city,
                country=reading.country,
                date=reading.date,
                mm_total=total,
                period_days=period_days,
                deviation_from_record_mm=total - threshold_mm,
                previous_record_mm=threshold_mm,
                previous_record_year=None,
                lat=reading.lat,
                lon=reading.lon,
                city_count=None,
                sample_cities=[],
                event_id=f"gpm_precip_{period_days}d_{_safe_key(reading.country)}_"
                f"{_safe_key(reading.city)}_{reading.date}",
            ))
    return events


def _detect_country_events(
    events: list[PrecipExtremeEvent],
    *,
    min_country_records: int,
) -> list[PrecipExtremeEvent]:
    by_country: dict[str, list[PrecipExtremeEvent]] = {}
    for event in events:
        if event.kind == "daily_record" and event.country:
            by_country.setdefault(event.country, []).append(event)

    country_events: list[PrecipExtremeEvent] = []
    for country, group in by_country.items():
        if len(group) < min_country_records:
            continue
        leader = max(group, key=lambda event: event.mm_total)
        sample_cities = [event.location for event in group[:12]]
        country_events.append(PrecipExtremeEvent(
            kind="country_precip_event",
            location=country,
            country=country,
            date=leader.date,
            mm_total=max(event.mm_total for event in group),
            period_days=1,
            deviation_from_record_mm=None,
            previous_record_mm=None,
            previous_record_year=None,
            lat=leader.lat,
            lon=leader.lon,
            city_count=len(group),
            sample_cities=sample_cities,
            event_id=f"gpm_precip_country_{_safe_key(country)}_{leader.date}",
        ))
    return country_events


def _dates_are_consecutive(raw_dates: list[str]) -> bool:
    try:
        parsed = [date.fromisoformat(raw) for raw in raw_dates]
    except ValueError:
        return False
    return all((b - a).days == 1 for a, b in zip(parsed, parsed[1:]))


def _record_mm(record: object) -> float | None:
    if not isinstance(record, Mapping):
        return None
    raw = record.get("mm")
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _record_year(record: object) -> int | None:
    if not isinstance(record, Mapping):
        return None
    raw = record.get("year")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _city_key(reading: CityPrecipReading) -> str:
    return f"{_safe_key(reading.country)}:{_safe_key(reading.city)}"


def _daily_record_key(reading: CityPrecipReading) -> str:
    month_day = reading.date[5:]
    return f"{_city_key(reading)}:{month_day}"


def _safe_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "unknown"
