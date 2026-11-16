"""Completed-day NASA satellite estimates for a narrowly scoped text report.

The operating nomination range is not a record or physical-maximum claim.
The accumulation end, original day, point and product remain bound together.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import asdict
import csv
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
import math
import io
import os
import re
from types import SimpleNamespace
from typing import Any

from src.data import places
from src.data.rainfall_supply import _accumulation_bounds, window_evidence
from src.editorial.observed_scope import enabled as observed_only
from src.two_bot.types import StoryBundle

KIND = "satellite_precipitation_report"
SCHEMA = "nasa-imerg-late-daily-point-v1"
ENABLE_FLAG = "THEHEAT_GPM_OBSERVED_REPORT"
SOURCE_URL = "https://gpm.nasa.gov/data/imerg"
AUTO_DELAY_MINUTES = 1
MAX_AGE = timedelta(hours=36)
MIN_MM = 150.0
MAX_MM = 1000.0
MAX_NOMINATIONS = 3
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_READING_FIELDS = frozenset({"city", "country", "lat", "lon", "date", "mm_total",
                             "source_product", "event_id", "source_leg"})


class ReportHeld(ValueError):
    pass


def enabled():
    return os.environ.get(ENABLE_FLAG) == "1"


def settings_hold():
    from src.editorial.approval import autoship_on_critic_pass_enabled
    from src.editorial.publication import valid_epoch
    from src.orchestrator.candidate_budget import CandidateBudgetConfigError, configured_max_candidates
    from src.two_bot.pipeline import _critic_enabled

    if not enabled() or not observed_only() or not _critic_enabled():
        return "rainfall_observed_report_disabled"
    if (not autoship_on_critic_pass_enabled()
            or os.environ.get("THEHEAT_AUTOMATIC_PUBLICATION_ENABLED") != "1"
            or not valid_epoch(os.environ.get("THEHEAT_AUTOMATIC_PUBLICATION_EPOCH"))
            or os.environ.get("THEHEAT_PRODUCTION_PAUSED") == "1"):
        return "rainfall_report_publication_paused"
    try:
        limit = configured_max_candidates()
    except CandidateBudgetConfigError:
        return "rainfall_report_operation_limit_invalid"
    if (limit != 1 or os.environ.get("THEHEAT_WRITER_SAMPLES", "1") != "1"
            or os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED", "0") != "0"
            or os.environ.get("THEHEAT_REFILL_ENABLED", "0") != "0"):
        return "rainfall_report_one_sample_required"
    return None


def _clock(now=None):
    value = now() if callable(now) else now
    value = datetime.now(UTC) if value is None else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReportHeld("rainfall_clock_invalid")
    return value.astimezone(UTC)


def _time(value):
    if not isinstance(value, str):
        raise ReportHeld("rainfall_time_invalid")
    try:
        return _clock(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError) as exc:
        raise ReportHeld("rainfall_time_invalid") from exc


@lru_cache(maxsize=1)
def _watchlist_keys():
    keys = set()
    for row in csv.DictReader(io.StringIO(places._registry_text("cities.csv"))):
        point = places.place_for_row(row)
        if str(point["place_id"]).startswith("ux"):
            continue
        # Like load_cities, aliases use the registry's selected active point.
        active = places.resolve_place(point["city"], point["country"], place_id=point["place_id"])
        keys.add(places.event_location_key(active["city"], active["country"], active["lat"], active["lon"]))
    return frozenset(keys)


def _reading(raw):
    if not isinstance(raw, dict) or set(raw) != _READING_FIELDS:
        raise ReportHeld("rainfall_reading_invalid")
    if raw["source_product"] != "late" or raw["source_leg"] is not None:
        raise ReportHeld("rainfall_satellite_product_required")
    for key in ("lat", "lon", "mm_total"):
        if type(raw[key]) not in (float, int) or not math.isfinite(raw[key]):
            raise ReportHeld("rainfall_number_invalid")
    if not -90 <= raw["lat"] <= 90 or not -180 <= raw["lon"] <= 180:
        raise ReportHeld("rainfall_point_invalid")
    if not MIN_MM <= raw["mm_total"] <= MAX_MM:
        raise ReportHeld("rainfall_outside_automatic_range")
    for key in ("city", "country", "date", "event_id"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ReportHeld("rainfall_reading_invalid")
    try:
        day = date.fromisoformat(raw["date"])
        point = places.resolve_place(raw["city"], raw["country"], lat=raw["lat"], lon=raw["lon"])
        key = places.event_location_key(raw["city"], raw["country"], raw["lat"], raw["lon"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ReportHeld("rainfall_point_invalid") from exc
    if (str(point["place_id"]).startswith("ux") or key not in _watchlist_keys()
            or raw["date"] != day.isoformat()
            or raw["event_id"] != f"gpm_imerg_{key}_{day.isoformat()}"):
        raise ReportHeld("rainfall_reading_identity_changed")
    return SimpleNamespace(**raw), point, day


def _declared(evidence, *, now):
    if not isinstance(evidence, dict) or set(evidence) != {"schema", "source_url", "reading"}:
        raise ReportHeld("rainfall_evidence_invalid")
    if evidence["schema"] != SCHEMA or evidence["source_url"] != SOURCE_URL:
        raise ReportHeld("rainfall_source_identity_changed")
    reading, point, day = _reading(evidence["reading"])
    start, end = _accumulation_bounds(day, 1)
    target = _time(end)
    if target > now or now - target > MAX_AGE:
        raise ReportHeld("rainfall_completed_window_expired")
    return reading, point, day, start, end


def evidence_for(reading, *, now=None):
    # The existing source reading carries no retrieval timestamp. Preserve that
    # absence; a new wall-clock value would invent provenance and defeat exact
    # rejection reuse. Live source agreement is independently required below.
    evidence = {"schema": SCHEMA, "source_url": SOURCE_URL, "reading": asdict(reading)}
    _declared(evidence, now=_clock(now))
    return evidence


def _bundle(evidence):
    reading, point, day = _reading(evidence["reading"])
    start, end = _accumulation_bounds(day, 1)
    event = SimpleNamespace(
        kind="daily_satellite_estimate", location=reading.city, country=reading.country,
        date=reading.date, mm_total=reading.mm_total, period_days=1,
        deviation_from_record_mm=None, previous_record_mm=None, previous_record_year=None,
        lat=reading.lat, lon=reading.lon, event_id=reading.event_id,
        city_count=1, sample_cities=[],
        source_leg=None, product_code="late",
    )
    window = window_evidence(event)
    return StoryBundle(KIND, f"{point['city']}, {point['country']}", end,
        "rain_report_" + reading.event_id,
        {"label": "daily_satellite_precipitation_mm", "value": round(reading.mm_total, 1), "unit": "mm"},
        [{"label": key, "value": value} for key, value in {
            "location": point["city"], "country": point["country"],
            "precipitation_mm": round(reading.mm_total, 1),
            "source_date_utc": f"{day.day} {_MONTHS[day.month - 1]}",
            "accumulation_start": start, "accumulation_end": end, "period_hours": 24,
            "evidence_type": "satellite_derived", "source_product": "IMERG Late daily V07",
            "quantity_basis": "Liquid-water-equivalent precipitation depth",
            "precipitation_phase": "Not established by this daily total",
            "geographic_scope": "One satellite grid cell near the named place",
            "public_source_url": SOURCE_URL,
        }.items()], historical_context={"scope": "One completed day; no historical comparator"},
        raw_signal_dump={"report_schema": SCHEMA, "evidence": deepcopy(evidence), "rainfall_window": window},
        country=point["country_code"])


def build_bundle(evidence, *, now=None):
    _declared(evidence, now=_clock(now))
    return _bundle(evidence)


def nominate(readings, bot_state, *, now=None):
    """A bounded free slate; the shared budget still selects one paid candidate."""
    from src import state
    from src.data import gpm_imerg

    clock = _clock(now)
    qualified: dict[str, dict[str, Any] | None] = {}
    for reading in readings:
        if not isinstance(reading, gpm_imerg.CityPrecipReading):
            continue
        try:
            bundle = build_bundle(evidence_for(reading, now=clock), now=clock)
        except (ReportHeld, TypeError, ValueError, OverflowError):
            continue
        if (state.is_duplicate(bot_state, bundle.event_id)
                or bundle.event_id in bot_state.get("publish_ledger", {})
                or any(row.get("event_id") == bundle.event_id for row in bot_state.get("drafts", []))
                or legacy_point_day_hold(bundle, bot_state)):
            continue
        # A conflicting copy of a point/day cannot nominate whichever came first.
        old = qualified.get(bundle.event_id)
        if old is not None and old != bundle.to_dict():
            qualified[bundle.event_id] = None
        elif bundle.event_id not in qualified:
            qualified[bundle.event_id] = bundle.to_dict()
    rows = [value for value in qualified.values() if isinstance(value, dict)]
    rows.sort(key=lambda value: (-_time(value["when"]).timestamp(),
                                -value["headline_metric"]["value"], value["event_id"]))
    return [build_bundle(row["raw_signal_dump"]["evidence"], now=clock)
            for row in rows[:MAX_NOMINATIONS]]


def is_family(value):
    payload = value if isinstance(value, dict) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    proof = raw.get("evidence") if isinstance(raw, dict) else None
    reading = proof.get("reading") if isinstance(proof, dict) else None
    return (payload.get("signal_kind") == KIND
            or str(payload.get("event_id", "")).startswith("rain_report_")
            or isinstance(raw, dict) and raw.get("report_schema") == SCHEMA
            or isinstance(proof, dict) and proof.get("schema") == SCHEMA
            or isinstance(reading, dict) and str(reading.get("event_id", "")).startswith("gpm_imerg_"))


def validate_bundle(value, *, now=None):
    payload = value if isinstance(value, dict) else value.to_dict()
    raw = payload.get("raw_signal_dump")
    evidence = raw.get("evidence") if isinstance(raw, dict) else None
    _declared(evidence, now=_clock(now))
    if payload != _bundle(evidence).to_dict():
        raise ReportHeld("rainfall_bundle_changed")
    return deepcopy(evidence)


def current_bundle_hold(value, *, live=False, now=None, minimum_delay=timedelta(0)):
    try:
        if not is_family(value):
            return None
        if hold := settings_hold():
            return hold
        clock = _clock(now)
        evidence = validate_bundle(value, now=clock)
        reading, _point, day, _start, end = _declared(evidence, now=clock)
        if clock + minimum_delay - _time(end) > MAX_AGE:
            return "rainfall_source_insufficient_window"
        if live:
            from src.data import gpm_imerg
            rows = gpm_imerg._fetch_daily_precip_primary(
                [{"city": reading.city, "country": reading.country, "lat": reading.lat, "lon": reading.lon}],
                target_date=day, product="late", max_cities=1, max_workers=1, strict=True, today=clock.date(),
            )
            if len(rows) != 1 or asdict(rows[0]) != evidence["reading"]:
                return "rainfall_current_source_changed"
        after = _clock(now)
        if after < clock or after - _time(end) > MAX_AGE:
            return "rainfall_completed_window_expired"
        return None
    except ReportHeld as exc:
        return str(exc)
    except Exception:  # noqa: BLE001 — unavailable source never grants authority
        return "rainfall_current_source_unavailable"


def bundle_failures(bundle):
    hold = current_bundle_hold(bundle)
    return [hold] if hold else []


def operation_hold(value, bot_state):
    """This automatic-only report cannot fall back to paid manual generation."""
    if not is_family(value):
        return None
    from src.editorial.publication import automatic_publication_policy
    if hold := settings_hold():
        return hold
    if not isinstance(bot_state, Mapping) or not automatic_publication_policy(bot_state)["enabled"]:
        return "rainfall_report_publication_paused"
    return legacy_point_day_hold(value, bot_state)


def claim_failures(text, bundle, *, now=None):
    if not is_family(bundle):
        return []
    try:
        evidence = validate_bundle(bundle, now=now)
        reading, point, day, _start, _end = _declared(evidence, now=_clock(now))
        if not isinstance(text, str):
            return ["rainfall_text_invalid"]
        if re.findall(r"https?://[^\s<>]+", text) != [SOURCE_URL]:
            return ["rainfall_citation_required"]
        prose = text.replace(SOURCE_URL, "")
        if not (re.search(r"\bNASA\b", prose, re.I) and re.search(r"\bsatellites?\b", prose, re.I)
                and re.search(r"\bestimat(?:e[ds]?|ing)\b", prose, re.I)):
            return ["rainfall_satellite_estimate_label_required"]
        if not (re.search(r"\bprecipitation\b", prose, re.I)
                and re.search(r"\bwater[ \-‐‑–]equivalent\b", prose, re.I)):
            return ["rainfall_quantity_label_required"]
        if not re.search(r"\bnear\s+" + re.escape(point["city"]) + r"\b", prose, re.I):
            return ["rainfall_point_scope_required"]
        if not any(re.search(r"\b" + re.escape(label) + r"\b", prose, re.I)
                   for label in {point["country"], reading.country, point["country_code"]}):
            return ["rainfall_country_required"]
        if not re.search(r"\b(?:24\s*(?:hours?|h)|one day|daily)\b", prose, re.I):
            return ["rainfall_daily_window_required"]
        month = _MONTHS[day.month - 1]
        if not (re.search(rf"\b{day.day}\s+{month}\b|\b{month}\s+{day.day}\b", prose, re.I)
                or day.isoformat() in prose):
            return ["rainfall_date_required"]
        amounts = re.findall(r"(?<![\d.−-])(\d+(?:\.\d+)?)\s*mm\b", prose, re.I)
        if (len(amounts) != 1 or len(amounts[0].partition(".")[2]) > 1
                or abs(float(amounts[0]) - reading.mm_total)
                > (0.051 if "." in amounts[0] else 0.501)):
            return ["rainfall_amount_changed"]
        if re.search(r"[−-]\d+(?:\.\d+)?\s*(?:mm|inches|inch|in\.)", prose, re.I):
            return ["rainfall_amount_changed"]
        inches = re.findall(r"(?<![\d.−-])(\d+(?:\.\d+)?)\s*(?:inches|inch|in\.)", prose, re.I)
        if any(len(x.partition(".")[2]) > 1 or abs(float(x) - reading.mm_total / 25.4)
               > (0.051 if "." in x else 0.501) for x in inches):
            return ["rainfall_conversion_changed"]
        limited = re.sub(r"\bnot a gauge (?:reading|measurement)\b", "", prose, flags=re.I)
        if re.search(r"\b(?:records?|recorded|measured|wettest|heaviest|highest|ever|flood(?:s|ing|ed)?|"
                     r"deaths?|killed|destroyed|evacuat\w*|injur\w*|homes?|damage|forecast|will|nationwide|national|"
                     r"average|rain(?:fall)?|snow|hail|month['’]s worth)\b",
                     limited, re.I):
            return ["rainfall_unsupported_claim"]
        return []
    except Exception:  # noqa: BLE001
        return ["rainfall_text_source_invalid"]


def current_draft_hold(draft, *, live=False, now=None):
    if not isinstance(draft, dict):
        return "rainfall_draft_invalid"
    context = draft.get("review_context")
    two_bot = context.get("two_bot") if isinstance(context, dict) else None
    bundle = two_bot.get("bundle") if isinstance(two_bot, dict) else None
    if draft.get("type") != KIND and not (isinstance(bundle, dict) and is_family(bundle)):
        return None
    if (draft.get("type") != KIND or not isinstance(bundle, dict) or bundle.get("signal_kind") != KIND
            or draft.get("event_id") != bundle.get("event_id")):
        return "rainfall_draft_identity_changed"
    hold = current_bundle_hold(bundle, now=now)
    failures = claim_failures(draft.get("text"), bundle, now=now)
    return hold or (failures[0] if failures else current_bundle_hold(bundle, live=live, now=now))


def legacy_point_day_hold(value, bot_state):
    try:
        payload = value if isinstance(value, dict) else value.to_dict()
        if payload.get("type") == KIND:
            payload = payload.get("review_context", {}).get("two_bot", {}).get("bundle")
        if not is_family(payload):
            return None
        reading = payload["raw_signal_dump"]["evidence"]["reading"]
        old = reading["event_id"]
        aliases = {old, old.replace("gpm_imerg_", "gpm_precip_record_", 1)}
        if (any(key in bot_state.get("posted_events", []) for key in aliases)
                or any(key in bot_state.get("publish_ledger", {}) for key in aliases)
                or any(row.get("event_id") in aliases for row in bot_state.get("drafts", []))):
            return "rainfall_legacy_point_day_held"
        return None
    except Exception:  # noqa: BLE001
        return "rainfall_point_day_unverified"
