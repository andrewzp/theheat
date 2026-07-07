"""Shared tropical-cyclone data models and detection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import re
from typing import Any


SAFFIR_SIMPSON_THRESHOLDS_KT = (64, 83, 96, 113, 137)
RI_THRESHOLD_KT_24H = 30


@dataclass(frozen=True)
class ForecastPoint:
    """One official forecast position from a warning/forecast-advisory product.

    ``valid_at`` is the RAW time token as printed by the product (JTWC
    ``DDHHMMZ``; NHC ``DD/HHMMZ``) — resolving it to an absolute datetime
    needs the advisory's issued_at month/year and is done at detection time,
    never here (parsers stay pure text→fields).
    """
    valid_at: str
    lat: float
    lon: float
    max_wind_kt: int | None = None
    tau_h: int | None = None


@dataclass(frozen=True)
class CycloneAdvisory:
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    wind_kt: int
    pressure_mb: int | None = None
    lat: float | None = None
    lon: float | None = None
    classification: str = ""
    public_advisory_url: str = ""
    advisory_text: str = ""
    source_leg: str | None = None
    forecast_points: tuple[ForecastPoint, ...] = ()

    @property
    def category(self) -> int:
        return saffir_simpson_category(self.wind_kt)

    @property
    def tracking_key(self) -> str:
        return tracking_key(self.source, self.storm_id)


@dataclass(frozen=True)
class RapidIntensificationEvent:
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    current_wind_kt: int
    previous_wind_kt: int
    delta_kt_24h: int
    current_category: int
    previous_category: int
    pressure_mb: int | None = None
    lat: float | None = None
    lon: float | None = None
    public_advisory_url: str = ""
    event_id: str = ""

    @property
    def kind(self) -> str:
        return "cyclone_rapid_intensification"


@dataclass(frozen=True)
class TierCrossingEvent:
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    from_category: int
    to_category: int
    wind_kt: int
    pressure_mb: int | None = None
    lat: float | None = None
    lon: float | None = None
    public_advisory_url: str = ""
    event_id: str = ""

    @property
    def kind(self) -> str:
        return "cyclone_tier_crossing"


@dataclass(frozen=True)
class LandfallEvent:
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    category: int
    wind_kt: int
    location: str
    pressure_mb: int | None = None
    lat: float | None = None
    lon: float | None = None
    public_advisory_url: str = ""
    event_id: str = ""

    @property
    def kind(self) -> str:
        return "cyclone_landfall"


@dataclass(frozen=True)
class LandThreatEvent:
    """A warned storm whose official forecast track approaches a named landmass.

    Forecast-tense by construction — the event says "forecast to pass within
    about N NM", never an arrival stated as fact. One per (storm, landmass)
    pair, ever (the drafted-pairs state key).
    """
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    current_wind_kt: int
    landmass_country: str
    nearest_city: str
    min_distance_nm: float
    closest_valid_at: str
    closest_tau_h: int | None
    forecast_wind_kt_at_closest: int | None
    event_id: str

    @property
    def kind(self) -> str:
        return "cyclone_land_threat"


@dataclass(frozen=True)
class BasinRecordEvent:
    source: str
    storm_id: str
    storm_name: str
    basin: str
    advisory_number: str
    issued_at: str
    category: int
    wind_kt: int
    record_label: str
    record_scope: str
    pressure_mb: int | None = None
    lat: float | None = None
    lon: float | None = None
    public_advisory_url: str = ""
    event_id: str = ""

    @property
    def kind(self) -> str:
        return "cyclone_basin_record"


_JTWC_TAU_RE = re.compile(r"^\s*(\d{2,3})\s+HRS?,\s*VALID\s+AT:", re.MULTILINE)
_JTWC_POINT_RE = re.compile(
    r"(\d{6}Z)\s*-{1,3}\s*(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])"
)
_JTWC_FCST_WIND_RE = re.compile(r"MAX\s+SUSTAINED\s+WINDS\s*-\s*(\d+)\s*KT")


def parse_jtwc_forecast_sections(text: str) -> tuple[ForecastPoint, ...]:
    """Extract forecast positions from a JTWC warning product's FORECASTS
    block. Returns () when the text carries no forecast sections — a
    warning without forecasts simply produces no land-threat signal."""
    marker = text.find("FORECASTS:")
    if marker < 0:
        return ()
    body = text[marker:]
    points: list[ForecastPoint] = []
    taus = list(_JTWC_TAU_RE.finditer(body))
    for i, tau_match in enumerate(taus):
        seg_end = taus[i + 1].start() if i + 1 < len(taus) else len(body)
        segment = body[tau_match.start():seg_end]
        pos = _JTWC_POINT_RE.search(segment)
        if not pos:
            continue
        wind = _JTWC_FCST_WIND_RE.search(segment)
        lat = float(pos.group(2)) * (1 if pos.group(3) == "N" else -1)
        lon = float(pos.group(4)) * (1 if pos.group(5) == "E" else -1)
        points.append(ForecastPoint(
            valid_at=pos.group(1),
            lat=lat,
            lon=lon,
            max_wind_kt=int(wind.group(1)) if wind else None,
            tau_h=int(tau_match.group(1)),
        ))
    return tuple(points)


_NHC_FCST_RE = re.compile(
    r"FORECAST\s+VALID\s+(\d{2}/\d{4}Z)\s+(\d+(?:\.\d+)?)([NS])\s+(\d+(?:\.\d+)?)([EW])"
    r"(?:\s*\nMAX\s+WIND\s+(\d+)\s*KT)?",
)


def parse_nhc_forecast_advisory(text: str) -> tuple[ForecastPoint, ...]:
    """Extract forecast positions from an NHC Forecast/Advisory (TCM) text.

    Tolerates real-product edges (verified vs archived AL012025): a status
    suffix after the position ("...POST-TROP/REMNT LOW" — point parses,
    wind group simply doesn't match) and dissipated entries with no
    position at all (skipped by the position requirement).
    """
    points: list[ForecastPoint] = []
    for m in _NHC_FCST_RE.finditer(text):
        lat = float(m.group(2)) * (1 if m.group(3) == "N" else -1)
        lon = float(m.group(4)) * (1 if m.group(5) == "E" else -1)
        points.append(ForecastPoint(
            valid_at=m.group(1),
            lat=lat,
            lon=lon,
            max_wind_kt=int(m.group(6)) if m.group(6) else None,
        ))
    return tuple(points)


LAND_THREAT_MAX_NM = 150.0
LAND_THREAT_MAX_HOURS = 72
LAND_THREAT_MIN_WIND_KT = 64  # current intensity >= Cat 1; TS threats are routine

_VALID_AT_RE = re.compile(r"^(\d{2})/?(\d{2})(\d{2})Z$")


def _landmass_slug(country: str) -> str:
    return country.strip().lower().replace(" ", "_")


def _valid_at_within_hours(
    token: str, issued_at_iso: str, now: datetime, max_hours: int
) -> bool:
    """Resolve a raw DDHHMMZ / DD/HHMMZ token against issued_at's month/year.

    Same month/year when the token's day >= the issued day, else roll to the
    next month (forecast tokens are always forward of issuance). Returns
    False on ANY parse failure — fail-closed: an unparsable time never
    mints an event. The point must also still be in the FUTURE (codex #388
    r1 P1): an already-passed closest approach is no longer a forecast, and
    a forecast-tense tweet about it would misstate the past as pending.
    """
    m = _VALID_AT_RE.match(token.strip())
    if not m:
        return False
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        issued = datetime.fromisoformat(issued_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if issued.tzinfo is None:
        issued = issued.replace(tzinfo=UTC)
    year, month = issued.year, issued.month
    if day < issued.day:
        month += 1
        if month > 12:
            month, year = 1, year + 1
    try:
        valid = datetime(year, month, day, hour, minute, tzinfo=UTC)
    except ValueError:
        return False
    return now <= valid <= now + timedelta(hours=max_hours)


def detect_land_threats(
    advisories: list[CycloneAdvisory],
    drafted_pairs: dict[str, list[str]],
    cities: list[dict],
    *,
    now: datetime,
) -> list[LandThreatEvent]:
    """A warned storm whose official forecast brings its CENTER within
    LAND_THREAT_MAX_NM of a curated populated place within
    LAND_THREAT_MAX_HOURS → one event per (storm, landmass) pair, ever.

    Pure: reads drafted_pairs, never writes it — the caller records the
    pair only after a draft is successfully saved (the fire_complex_tiers
    callback pattern). Prefers tau_h when present (JTWC: eta = issuance +
    tau, immune to month-roll bugs); falls back to token resolution for
    NHC points (no tau).
    """
    from src.data.land_threat_geo import NearestLandmass, nearest_landmass

    events: list[LandThreatEvent] = []
    for adv in advisories:
        if adv.wind_kt < LAND_THREAT_MIN_WIND_KT or not adv.forecast_points:
            continue
        already = {s.lower() for s in drafted_pairs.get(adv.tracking_key, [])}
        best: tuple[NearestLandmass, ForecastPoint] | None = None
        for point in adv.forecast_points:
            eta_h = point.tau_h
            if eta_h is not None and eta_h > LAND_THREAT_MAX_HOURS:
                continue
            if eta_h is None and not _valid_at_within_hours(
                point.valid_at, adv.issued_at, now, LAND_THREAT_MAX_HOURS
            ):
                continue
            near = nearest_landmass(point.lat, point.lon, cities)
            if near is None or near.distance_nm > LAND_THREAT_MAX_NM:
                continue
            if _landmass_slug(near.country) in already:
                continue
            if best is None or near.distance_nm < best[0].distance_nm:
                best = (near, point)
        if best is None:
            continue
        near, point = best
        slug = _landmass_slug(near.country)
        events.append(LandThreatEvent(
            source=adv.source, storm_id=adv.storm_id, storm_name=adv.storm_name,
            basin=adv.basin, advisory_number=adv.advisory_number,
            issued_at=adv.issued_at, current_wind_kt=adv.wind_kt,
            landmass_country=near.country, nearest_city=near.city,
            min_distance_nm=near.distance_nm, closest_valid_at=point.valid_at,
            closest_tau_h=point.tau_h,
            forecast_wind_kt_at_closest=point.max_wind_kt,
            event_id=event_key(adv.source, "land_threat", adv.storm_id,
                               adv.advisory_number, slug),
        ))
    return events


def tracking_key(source: str, storm_id: str) -> str:
    raw = f"{source}:{storm_id}".strip().lower()
    return re.sub(r"[^a-z0-9:_-]+", "_", raw)


def event_key(source: str, kind: str, storm_id: str, advisory_number: str, suffix: str = "") -> str:
    raw = "_".join(part for part in [source, kind, storm_id, advisory_number, suffix] if part)
    return re.sub(r"[^a-zA-Z0-9_:-]+", "_", raw).strip("_").lower()


def saffir_simpson_category(wind_kt: int | float | None) -> int:
    """Return 0 for sub-hurricane winds, 1-5 for Saffir-Simpson categories."""

    if wind_kt is None:
        return 0
    category = 0
    for index, threshold in enumerate(SAFFIR_SIMPSON_THRESHOLDS_KT, start=1):
        if float(wind_kt) >= threshold:
            category = index
    return category


def parse_issued_at(value: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z") and "T" in text:
        text = text.replace("Z", "+00:00")
    formats = (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %y %H:%M:%S %z",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_coordinate(value: Any) -> float | None:
    """Parse decimal or hemisphere-suffixed lat/lon strings."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*([NSEW])?", text, re.IGNORECASE)
    if not match:
        return None
    number = float(match.group(1))
    hemi = (match.group(2) or "").upper()
    if hemi in {"S", "W"}:
        number = -abs(number)
    return number


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    return int(round(float(match.group(0))))


def detect_rapid_intensification(advisories: list[CycloneAdvisory]) -> list[RapidIntensificationEvent]:
    """Detect >=30 kt strengthening over roughly 24 hours."""

    by_storm: dict[str, list[CycloneAdvisory]] = {}
    for advisory in advisories:
        by_storm.setdefault(advisory.tracking_key, []).append(advisory)

    events: list[RapidIntensificationEvent] = []
    for storm_advisories in by_storm.values():
        ordered = sorted(
            storm_advisories,
            key=lambda item: parse_issued_at(item.issued_at) or datetime.min.replace(tzinfo=UTC),
        )
        if len(ordered) < 2:
            continue
        current = ordered[-1]
        current_ts = parse_issued_at(current.issued_at)
        if current_ts is None:
            continue
        target_start = current_ts - timedelta(hours=30)
        target_end = current_ts - timedelta(hours=18)
        candidates = []
        for prior in ordered[:-1]:
            prior_ts = parse_issued_at(prior.issued_at)
            if prior_ts is None:
                continue
            if target_start <= prior_ts <= target_end:
                candidates.append((abs((current_ts - prior_ts) - timedelta(hours=24)), prior))
        if not candidates:
            continue
        prior = sorted(candidates, key=lambda item: item[0])[0][1]
        delta = current.wind_kt - prior.wind_kt
        if delta < RI_THRESHOLD_KT_24H:
            continue
        events.append(RapidIntensificationEvent(
            source=current.source,
            storm_id=current.storm_id,
            storm_name=current.storm_name,
            basin=current.basin,
            advisory_number=current.advisory_number,
            issued_at=current.issued_at,
            current_wind_kt=current.wind_kt,
            previous_wind_kt=prior.wind_kt,
            delta_kt_24h=delta,
            current_category=current.category,
            previous_category=prior.category,
            pressure_mb=current.pressure_mb,
            lat=current.lat,
            lon=current.lon,
            public_advisory_url=current.public_advisory_url,
            event_id=event_key(
                current.source,
                "ri",
                current.storm_id,
                current.advisory_number,
                str(current.wind_kt),
            ),
        ))
    return events


def detect_tier_crossings(
    advisories: list[CycloneAdvisory],
    cyclone_tiers: dict[str, int] | None,
) -> list[TierCrossingEvent]:
    """Detect category upgrades above the last fired tier."""

    tiers = cyclone_tiers or {}
    events: list[TierCrossingEvent] = []
    latest_by_storm: dict[str, CycloneAdvisory] = {}
    for advisory in advisories:
        current = latest_by_storm.get(advisory.tracking_key)
        current_ts = parse_issued_at(current.issued_at) if current else None
        advisory_ts = parse_issued_at(advisory.issued_at)
        if current is None or (advisory_ts and current_ts and advisory_ts >= current_ts):
            latest_by_storm[advisory.tracking_key] = advisory
        elif current is None:
            latest_by_storm[advisory.tracking_key] = advisory

    for advisory in latest_by_storm.values():
        current_category = advisory.category
        if current_category < 2:
            continue
        previous_category = int(tiers.get(advisory.tracking_key, current_category))
        if previous_category < 1 or current_category <= previous_category:
            continue
        events.append(TierCrossingEvent(
            source=advisory.source,
            storm_id=advisory.storm_id,
            storm_name=advisory.storm_name,
            basin=advisory.basin,
            advisory_number=advisory.advisory_number,
            issued_at=advisory.issued_at,
            from_category=previous_category,
            to_category=current_category,
            wind_kt=advisory.wind_kt,
            pressure_mb=advisory.pressure_mb,
            lat=advisory.lat,
            lon=advisory.lon,
            public_advisory_url=advisory.public_advisory_url,
            event_id=event_key(
                advisory.source,
                "tier",
                advisory.storm_id,
                advisory.advisory_number,
                f"cat{current_category}",
            ),
        ))
    return events


_LANDFALL_PATTERNS = (
    re.compile(r"made landfall (?:near|in|along)\s+([^.\n;]+)", re.IGNORECASE),
    re.compile(r"landfall (?:near|in|along)\s+([^.\n;]+)", re.IGNORECASE),
)


def detect_landfalls(advisories: list[CycloneAdvisory]) -> list[LandfallEvent]:
    """Detect Cat 3+ landfalls explicitly confirmed in advisory text."""

    events: list[LandfallEvent] = []
    for advisory in advisories:
        if advisory.category < 3 or not advisory.advisory_text:
            continue
        text = " ".join(advisory.advisory_text.split())
        location = ""
        for pattern in _LANDFALL_PATTERNS:
            match = pattern.search(text)
            if match:
                location = match.group(1).strip(" .")
                location = re.split(r"\s+with\s+", location, maxsplit=1, flags=re.IGNORECASE)[0]
                break
        if not location:
            continue
        events.append(LandfallEvent(
            source=advisory.source,
            storm_id=advisory.storm_id,
            storm_name=advisory.storm_name,
            basin=advisory.basin,
            advisory_number=advisory.advisory_number,
            issued_at=advisory.issued_at,
            category=advisory.category,
            wind_kt=advisory.wind_kt,
            location=location,
            pressure_mb=advisory.pressure_mb,
            lat=advisory.lat,
            lon=advisory.lon,
            public_advisory_url=advisory.public_advisory_url,
            event_id=event_key(
                advisory.source,
                "landfall",
                advisory.storm_id,
                advisory.advisory_number,
                location,
            ),
        ))
    return events


def detect_basin_records(
    advisories: list[CycloneAdvisory],
    records: dict[str, dict[str, Any]],
) -> list[BasinRecordEvent]:
    """Detect simple basin records supplied by a caller-owned archive table.

    The live NHC/JTWC fetchers do not ship an archive table. This helper keeps
    basin-record support deterministic for future archive wiring and voice
    regression fixtures.
    """

    events: list[BasinRecordEvent] = []
    for advisory in advisories:
        basin_rules = records.get(advisory.basin, {})
        for record_key, rule in basin_rules.items():
            min_category = int(rule.get("min_category", 0))
            if advisory.category < min_category:
                continue
            events.append(BasinRecordEvent(
                source=advisory.source,
                storm_id=advisory.storm_id,
                storm_name=advisory.storm_name,
                basin=advisory.basin,
                advisory_number=advisory.advisory_number,
                issued_at=advisory.issued_at,
                category=advisory.category,
                wind_kt=advisory.wind_kt,
                record_label=str(rule.get("label") or record_key),
                record_scope=str(rule.get("scope") or advisory.basin),
                pressure_mb=advisory.pressure_mb,
                lat=advisory.lat,
                lon=advisory.lon,
                public_advisory_url=advisory.public_advisory_url,
                event_id=event_key(
                    advisory.source,
                    "record",
                    advisory.storm_id,
                    advisory.advisory_number,
                    record_key,
                ),
            ))
    return events


def latest_advisories_by_storm(advisories: list[CycloneAdvisory]) -> dict[str, CycloneAdvisory]:
    latest: dict[str, CycloneAdvisory] = {}
    for advisory in advisories:
        current = latest.get(advisory.tracking_key)
        if current is None:
            latest[advisory.tracking_key] = advisory
            continue
        current_ts = parse_issued_at(current.issued_at)
        advisory_ts = parse_issued_at(advisory.issued_at)
        if advisory_ts is not None and (current_ts is None or advisory_ts >= current_ts):
            latest[advisory.tracking_key] = advisory
    return latest
