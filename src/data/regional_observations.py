"""Observed regional temperature from national-service packets (AEMET, IMD, SAWS).

No adapter here fetches anything. Each one parses an owner-supplied packet
(provider bytes plus the access/schema contract that came with them) into the
existing typed temperature evidence (``temperature_evidence``) or a hold named
for that adapter. Missing access for one service never means "global
unavailable", and no station value, archive or comparator is invented.

Rules kept here:

- Station admission joins the source station to the existing place registry.
  An ambiguous name/alias/point refuses; a station near a registered city is its
  own coordinate-specific point, never that city.
- The source calendar day stays the observation day. Without documented
  interval evidence it is not converted into a UTC midnight-to-midnight window;
  retrieval time is never observation time.
- QC-flagged, missing and unit-incompatible values are exclusions, recorded.
- A record claim needs the scoped GHCN comparator warrant
  (``ghcn.record_comparison_qualified``) for the same station/variable/date.
  National-service values otherwise permit value/absolute-band wording only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import csv
import hashlib
import io
import json
import math
import re
from typing import Any

from src.data import places
from src.data.temperature_evidence import fingerprint

PACKET_SCHEMA = "theheat.regional-observation-packet/v1"
EVIDENCE_DOMAIN = "temperature"
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_STATIONS = 512
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}\Z")
_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")


@dataclass(frozen=True)
class AdapterSpec:
    adapter_id: str
    country_codes: tuple[str, ...]
    region: str
    source_product: str
    schema_status: str  # "provider_documented" or "owner_contract_required"
    access_hold: str
    owner_action: str
    max_lag_days: int


ADAPTERS: dict[str, AdapterSpec] = {
    "aemet": AdapterSpec(
        "aemet", ("ES",), "europe_spain", "aemet-opendata-climatological-daily-v1", "provider_documented",
        "AEMET OpenData access (API key and reuse terms) has not been supplied or qualified.",
        "Owner obtains an AEMET OpenData key under its reuse terms and supplies retained packets; Root wires "
        "the bounded retrieval.", 4),
    "imd": AdapterSpec(
        "imd", ("IN",), "south_asia_india", "imd-station-daily-v1", "owner_contract_required",
        "IMD station-data access and its column/QC/day-definition contract have not been supplied.",
        "Owner arranges IMD data supply and records its schema contract (field map, units, QC flags, day "
        "definition) with each packet.", 4),
    "saws": AdapterSpec(
        "saws", ("ZA",), "southern_africa_south_africa", "saws-station-daily-v1", "owner_contract_required",
        "SAWS station-data access and its column/QC/day-definition contract have not been supplied.",
        "Owner arranges SAWS data supply and records its schema contract with each packet.", 4),
}
# Provider-documented AEMET OpenData daily-climatology record fields.
AEMET_FIELDS = {"station_id": "indicativo", "station_name": "nombre", "date": "fecha",
                "tmax_c": "tmax", "tmin_c": "tmin", "tmax_time": "horatmax", "tmin_time": "horatmin"}
_CONTRACT_FIELDS = frozenset({"station_id", "date", "tmax_c"})
_OPTIONAL_CONTRACT_FIELDS = frozenset({"station_name", "tmin_c", "qc_flag", "tmax_time", "tmin_time"})


class RegionalHold(ValueError):
    """A named, per-adapter refusal with fixed public text."""

    def __init__(self, adapter: str, code: str, text: str):
        super().__init__(code)
        self.adapter, self.code, self.text = adapter, code, text

    def as_dict(self) -> dict[str, str]:
        return {"adapter": self.adapter, "hold": self.code, "text": self.text}


def _hold(spec: AdapterSpec, code: str, text: str | None = None) -> RegionalHold:
    return RegionalHold(spec.adapter_id, code, text or {
        "access_unavailable": spec.access_hold,
        "schema_contract_unverified": "No owner-supplied schema contract accompanies this packet.",
        "payload_digest_mismatch": "Packet bytes do not match their recorded digest.",
        "malformed_payload": "Packet bytes are not the declared provider product.",
        "packet_shape": "Packet does not follow the regional observation packet contract.",
    }[code])


def _number(value: Any) -> float | None:
    """Provider decimal (AEMET uses a decimal comma). Blank or 'Ip' style codes are missing."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if type(value) is not str:
        return None
    text = value.strip().replace(",", ".")
    if not re.fullmatch(r"-?\d{1,3}(?:\.\d{1,2})?", text):
        return None
    return float(text)


def _records(spec: AdapterSpec, packet: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    payload = packet["payload"]
    if type(payload) is not str or len(payload.encode()) > MAX_PAYLOAD_BYTES:
        raise _hold(spec, "malformed_payload")
    if hashlib.sha256(payload.encode()).hexdigest() != packet.get("payload_sha256"):
        raise _hold(spec, "payload_digest_mismatch")
    if spec.schema_status == "provider_documented":
        try:
            rows = json.loads(payload)
        except ValueError:
            raise _hold(spec, "malformed_payload") from None
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise _hold(spec, "malformed_payload")
        return rows, AEMET_FIELDS
    contract = packet.get("schema_contract")
    if not isinstance(contract, dict) or type(contract.get("version")) is not str \
            or not isinstance(contract.get("field_map"), dict) or contract.get("unit") != "C":
        raise _hold(spec, "schema_contract_unverified")
    field_map = contract["field_map"]
    if not _CONTRACT_FIELDS <= set(field_map) or not set(field_map) <= _CONTRACT_FIELDS | _OPTIONAL_CONTRACT_FIELDS \
            or not all(type(v) is str and v for v in field_map.values()):
        raise _hold(spec, "schema_contract_unverified")
    try:
        reader = csv.DictReader(io.StringIO(payload), strict=True)
        rows = list(reader)
    except csv.Error:
        raise _hold(spec, "malformed_payload") from None
    if not reader.fieldnames or not set(field_map.values()) - {""} <= set(reader.fieldnames):
        raise _hold(spec, "malformed_payload")
    return rows, field_map


def _station_index(spec: AdapterSpec, packet: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    stations = packet.get("stations")
    if not isinstance(stations, list) or not 1 <= len(stations) <= MAX_STATIONS:
        raise _hold(spec, "packet_shape")
    index: dict[str, list[dict[str, Any]]] = {}
    for meta in stations:
        if not isinstance(meta, dict) or type(meta.get("station_id")) is not str or not _ID.fullmatch(meta["station_id"]):
            raise _hold(spec, "packet_shape")
        index.setdefault(meta["station_id"], []).append(meta)
    return index


def admit_station(meta_versions: list[dict[str, Any]], valid_date: str) -> dict[str, Any]:
    """Join one source station to place identity for its effective metadata period.

    Refusals: relocation period not covering the day, metadata versions that
    overlap, and name/alias matches to more than one registered place without an
    exact coordinate match. A non-matching point is its own place, never the city.
    """
    day = date.fromisoformat(valid_date)
    effective = []
    for meta in meta_versions:
        start = date.fromisoformat(meta["effective_from"]) if meta.get("effective_from") else date.min
        end = date.fromisoformat(meta["effective_to"]) if meta.get("effective_to") else date.max
        if start <= day <= end:
            effective.append(meta)
    if len(effective) != 1:
        raise ValueError("station_relocation_period_unresolved" if not effective else "station_metadata_overlap")
    meta = effective[0]
    lat, lon = float(meta["lat"]), float(meta["lon"])
    point = places.sampling_point_id(lat, lon)
    country = places.country_key(str(meta["country"]))
    names = {places.normalize(str(meta["name"]))} | {places.normalize(str(a)) for a in meta.get("aliases") or []}
    named = [row for row in places.registry()
             if row["country_code"] == country and any(places.normalize(a["city"]) in names for a in [row, *row["aliases"]])]
    exact = [row for row in named if point in {places.sampling_point_id(a["lat"], a["lon"]) for a in [row, *row["aliases"]]}]
    if len(exact) > 1 or (len(named) > 1 and not exact):
        raise ValueError("ambiguous_station_place")
    if exact:
        place = places.resolve_place(exact[0]["city"], exact[0]["country"], lat, lon, place_id=exact[0]["place_id"])
        join = "registered_sampling_point"
    else:
        # Coordinate-specific identity under the station's own name: no nearby-city fallback.
        place = places.resolve_place(str(meta["name"]), str(meta["country"]), lat, lon)
        join = "station_point_unregistered" if not named else "station_point_distinct_from_named_place"
    return {"station_id": meta["station_id"], "source_station_name": meta["name"], "station_lat": lat,
            "station_lon": lon, "elevation_m": meta.get("elevation_m"), "metadata_effective_from":
            meta.get("effective_from"), "place": place, "join": join}


def time_support(valid_date: str, retrieved_at: str, *, max_lag_days: int) -> dict[str, Any]:
    """Source-calendar day semantics; currentness from the actual supplied support."""
    day = date.fromisoformat(valid_date)
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    lag = (retrieved.date() - day).days
    status = "invalid_future_day" if lag < 0 else "current" if lag <= max_lag_days else "stale"
    return {
        "valid_date": valid_date, "calendar": "source_reporting_day", "timezone": None,
        "valid_start": None, "valid_end": None, "reporting_interval_known": False,
        "retrieved_at": retrieved_at, "publication_lag_days": lag, "currentness": status,
        "limit": "Source reporting day; not an exact UTC day. Retrieval time is not observation time.",
    }


def parse_packet(packet: Any) -> dict[str, Any]:
    """One adapter packet → typed observations, exclusions and denominators, or a named hold."""
    if not isinstance(packet, dict) or packet.get("schema") != PACKET_SCHEMA or packet.get("adapter") not in ADAPTERS:
        raise RegionalHold("unknown", "packet_shape", "Packet does not follow the regional observation packet contract.")
    spec = ADAPTERS[packet["adapter"]]
    access = packet.get("access")
    if not isinstance(access, dict) or type(access.get("arrangement")) is not str \
            or type(access.get("terms_reference")) is not str:
        raise _hold(spec, "access_unavailable")
    if type(packet.get("retrieved_at")) is not str or not _AT.fullmatch(packet["retrieved_at"]):
        raise _hold(spec, "packet_shape")
    requested = packet.get("requested")
    if not isinstance(requested, dict) or not isinstance(requested.get("stations"), list):
        raise _hold(spec, "packet_shape")
    stations = _station_index(spec, packet)
    rows, fields = _records(spec, packet)
    observations, exclusions = [], []
    returned: set[str] = set()
    for row in rows:
        sid, day = row.get(fields["station_id"]), row.get(fields["date"])
        if type(sid) is not str or type(day) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            exclusions.append({"station_id": None, "reason": "record_identity_missing"})
            continue
        returned.add(sid)
        if sid not in stations:
            exclusions.append({"station_id": sid, "valid_date": day, "reason": "station_metadata_missing"})
            continue
        try:
            station = admit_station(stations[sid], day)
        except ValueError as exc:
            exclusions.append({"station_id": sid, "valid_date": day, "reason": str(exc)})
            continue
        flag = str(row.get(fields.get("qc_flag", ""), "") or "").strip() if fields.get("qc_flag") else ""
        variables: dict[str, dict[str, Any]] = {}
        for var, key, time_key in (("TMAX", "tmax_c", "tmax_time"), ("TMIN", "tmin_c", "tmin_time")):
            if key not in fields:
                continue
            raw = row.get(fields[key])
            value = _number(raw)
            if value is None:
                exclusions.append({"station_id": sid, "valid_date": day, "variable": var,
                                   "reason": "missing_value" if raw in (None, "") else "unparseable_or_unit_incompatible"})
            elif flag:
                exclusions.append({"station_id": sid, "valid_date": day, "variable": var, "reason": "qc_flagged"})
            elif not -90.0 <= value <= 60.0:
                exclusions.append({"station_id": sid, "valid_date": day, "variable": var, "reason": "out_of_physical_range"})
            else:
                obs_time = row.get(fields[time_key]) if time_key in fields else None
                variables[var] = {"value_c": value, "observation_time_local_text": obs_time if type(obs_time) is str else None}
        if not variables:
            continue
        support = time_support(day, packet["retrieved_at"], max_lag_days=spec.max_lag_days)
        evidence = {
            "domain": EVIDENCE_DOMAIN, "evidence_type": "observed", "source_product": spec.source_product,
            "adapter": spec.adapter_id, "station_id": sid, "valid_date": day, "timezone": None,
            "valid_start": None, "valid_end": None, "issued_at": None, "model_run": None,
            "retrieved_at": packet["retrieved_at"], "aggregation": "station_reported_daily_extreme", "unit": "C",
            "reporting_interval_known": False, "time_support": support, "variables": variables,
            "baseline": None, "comparison_warrant": None, "publication_time_qc_known": False,
            "source_payload_sha256": packet["payload_sha256"],
            "schema_version": (packet.get("schema_contract") or {}).get("version") or spec.source_product,
            "access_arrangement": access["arrangement"], "station": {k: v for k, v in station.items() if k != "place"},
            "place_id": station["place"]["place_id"], "sampling_point_id": station["place"]["sampling_point_id"],
        }
        evidence["revision_id"] = fingerprint({k: v for k, v in evidence.items() if k != "retrieved_at"})
        observations.append({"adapter": spec.adapter_id, "station": station, "evidence": evidence})
    requested_ids = [s for s in requested["stations"] if type(s) is str]
    return {
        "adapter": spec.adapter_id, "region": spec.region, "source_product": spec.source_product,
        "observations": observations, "exclusions": exclusions,
        "denominators": {"requested_stations": len(set(requested_ids)), "returned_stations": len(returned),
                         "qualified_station_days": len(observations)},
        "scope": "Named stations in this packet only; not national, regional or global coverage.",
    }


def qualify_comparison(evidence: dict[str, Any], comparator: Any, variable: str = "TMAX") -> dict[str, Any]:
    """Join a supplied comparator; a record needs the scoped GHCN warrant for this exact station/day."""
    from src.data.ghcn import GHCN_SOURCE_PRODUCT, record_comparison_qualified

    reasons: list[str] = []
    if comparator is None:
        reasons.append("no_comparator_supplied")
    elif evidence.get("source_product") != GHCN_SOURCE_PRODUCT:
        reasons.append("comparator_warrant_not_scoped_to_this_product")
    elif not record_comparison_qualified(comparator, str(evidence.get("station_id")), str(evidence.get("valid_date")),
                                         variable):
        reasons.append("comparator_not_qualified")
    scope = "record" if not reasons else "value_or_absolute_band_only"
    return {"claim_scope": scope, "reasons": reasons, "variable": variable}


def build_candidate(observation: dict[str, Any], comparator: Any = None, *, now: datetime | None = None):
    """A StoryBundle for a qualified observed value crossing its absolute band, else ``None``.

    Uses the existing absolute-extreme detector and bundle; the evidence carries the
    station, time support and the narrower claim scope into checks and the brief.
    """
    from src.data.open_meteo import detect_absolute_extreme
    from src.data.temperature_evidence import attach_evidence
    from src.two_bot.intern.temperature import build_absolute_extreme_bundle

    evidence = dict(observation["evidence"])
    if evidence["time_support"]["currentness"] != "current":
        return None, f"time_support_{evidence['time_support']['currentness']}"
    clock = now or datetime.now(timezone.utc)
    if clock.utcoffset() is None:
        raise ValueError("regional_clock_requires_timezone")
    captured = datetime.fromisoformat(evidence["retrieved_at"].replace("Z", "+00:00"))
    if captured > clock:
        return None, "time_support_future_capture"
    if (clock.astimezone(timezone.utc).date() - date.fromisoformat(evidence["valid_date"])).days > ADAPTERS[observation["adapter"]].max_lag_days:
        return None, "time_support_stale"
    station, place = observation["station"], observation["station"]["place"]
    tmax = (evidence["variables"].get("TMAX") or {}).get("value_c")
    tmin = (evidence["variables"].get("TMIN") or {}).get("value_c")
    event = detect_absolute_extreme(station["station_lat"], station["station_lon"], tmax, tmin, place["city"],
                                    place["country"], signal_date=date.fromisoformat(evidence["valid_date"]),
                                    data_source=f"observed_{observation['adapter']}")
    if event is None:
        return None, "below_absolute_band"
    evidence["comparison_warrant"] = qualify_comparison(evidence, comparator)
    event.event_id = f"regional_observed_{observation['adapter']}_{event.event_id}"
    event.evidence = evidence  # carried in raw_signal_dump so project_story_evidence projects it
    bundle = build_absolute_extreme_bundle(event)
    attach_evidence(bundle, evidence)
    bundle.current_facts.extend([
        {"label": "source_station", "value": f"{station['source_station_name']} ({station['station_id']})"},
        {"label": "time_support", "value": evidence["time_support"]["limit"]},
        {"label": "coverage_scope", "value": "One named station; not national or regional coverage."},
    ])
    return bundle, None


__all__ = ["ADAPTERS", "AEMET_FIELDS", "PACKET_SCHEMA", "AdapterSpec", "RegionalHold", "admit_station",
           "build_candidate", "parse_packet", "qualify_comparison", "time_support"]
