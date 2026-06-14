"""Stages 2 and 5: persistent memory for the two-bot fire pipeline."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from src import state as state_store
from src.state_schema import BotState, MemoryState
from src.two_bot.types import ExtractedClaim, MemorySlice, StoryBundle, WriterResult

_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "is",
    "was",
    "were",
    "this",
    "that",
}

# Maps the 25+ detection-specific signal_kinds to a smaller set of coarse
# categories for the per-day cooldown logic. Two fires from different countries
# (e.g. "fire" + "fire_footprint") should count as the same category so the
# writer doesn't post them back-to-back. Temperature records likewise: a
# calendar-day record and a monthly-high record on different cities still
# both feel like "temperature" to the reader.
_SIGNAL_KIND_TO_CATEGORY: dict[str, str] = {
    "fire": "fire",
    "fire_footprint": "fire",
    "monthly_high": "temperature_record",
    "monthly_low": "temperature_record",
    "calendar_record": "temperature_record",
    "calendar_record_low": "temperature_record",
    "open_meteo_archive_high": "temperature_record",
    "open_meteo_archive_low": "temperature_record",
    "country_high": "temperature_record",
    "country_low": "temperature_record",
    "anomaly_hot": "anomaly",
    "anomaly_cold": "anomaly",
    "severe_weather": "severe_weather",
    "record_streak": "record_streak",
    "simultaneous_records": "simultaneous_records",
    "co2_milestone": "co2",
    "sea_ice": "cryosphere",
    "ice_mass": "cryosphere",
    "marine_heatwave": "marine",
    "extreme_wave": "marine",
    "storm_surge": "marine",
    "cyclone_rapid_intensification": "cyclone",
    "cyclone_tier_crossing": "cyclone",
    "cyclone_landfall": "cyclone",
    "cyclone_basin_record": "cyclone",
    "river_flood": "flood",
    "global_flood": "flood",
    "drought": "drought",
    "enso": "enso",
    "hot10": "hot10",
    "synthesis": "synthesis",
    "global_disaster": "global_disaster",
    "usgs_earthquake": "global_disaster",
}


def _signal_kind_to_category(kind: str) -> str:
    """Map a fine-grained signal_kind to a coarse category for cooldown logic.

    Unknown kinds fall back to the input string so the writer still sees a
    consistent category label rather than silently dropping the entry.
    """
    return _SIGNAL_KIND_TO_CATEGORY.get(kind, kind)


_CATEGORY_COOLDOWN_SECONDS = 24 * 60 * 60
_SHIPPED_TWEET_TEXTS_LIMIT = 20


def _normalize(s: str) -> str:
    """Lowercase, trim, collapse whitespace, and remove trailing punctuation."""

    normalized = re.sub(r"\s+", " ", str(s or "").lower()).strip()
    return re.sub(r"[^\w\s-]+$", "", normalized).strip()


def _tokens(s: str) -> set[str]:
    return {tok for tok in re.findall(r"\w+", str(s).lower()) if tok not in _STOPWORDS}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _today_iso() -> str:
    return date.today().isoformat()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _country_for(bundle: StoryBundle) -> str:
    country = bundle.raw_signal_dump.get("country")
    if country:
        return str(country)
    for fact in bundle.current_facts:
        if fact.get("label") == "country":
            return str(fact.get("value") or "")
    return ""


def _tweet_text(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("tweet_text") or row.get("text") or "")
    return str(row or "")


def _row_time(row: dict) -> datetime:
    return (
        _parse_time(row.get("shipped_at"))
        or _parse_time(row.get("created_at"))
        or _parse_time(row.get("updated_at"))
        or datetime.fromtimestamp(0, UTC)
    )


def _event_base(event_id: Any) -> str:
    parts = str(event_id or "").split("_")
    if len(parts) < 3:
        return str(event_id or "")
    return "_".join(parts[:3])


def _fact_value(bundle: StoryBundle, label: str) -> str:
    for fact in bundle.current_facts:
        if fact.get("label") == label:
            return str(fact.get("value") or "")
    return ""


def _event_series_key(bundle: StoryBundle) -> str:
    if bundle.signal_kind == "severe_weather":
        event_type = _fact_value(bundle, "event_type")
        area = _fact_value(bundle, "area") or bundle.where
        if event_type and area:
            return f"severe_weather::{_normalize(event_type)}::{_normalize(area)}"

    if bundle.signal_kind == "global_disaster":
        disaster_type = _fact_value(bundle, "disaster_type")
        name = _fact_value(bundle, "name")
        country = _fact_value(bundle, "country") or _country_for(bundle)
        if disaster_type and name and country:
            return (
                f"global_disaster::{_normalize(disaster_type)}::"
                f"{_normalize(name)}::{_normalize(country)}"
            )

    return ""


def _dedup_append(values: list, value: Any) -> None:
    if value and value not in values:
        values.append(value)


def _memory(state: BotState) -> MemoryState:
    return state_store.get_memory(state)


def build_memory_slice(state: BotState, bundle: StoryBundle) -> MemorySlice:
    """Assemble the relevant memory for the writer."""

    memory = _memory(state)
    country = _country_for(bundle)
    event_keys = {
        key for key in (_event_base(bundle.event_id), _event_series_key(bundle))
        if key
    }
    cutoff = datetime.now(UTC).timestamp() - (30 * 24 * 60 * 60)

    same_country_rows = []
    for row in memory.get("shipped_tweets", []):
        if not isinstance(row, dict) or row.get("country") != country:
            continue
        shipped_at = _parse_time(row.get("shipped_at"))
        if shipped_at is not None and shipped_at.timestamp() < cutoff:
            continue
        same_country_rows.append(row)

    same_country_rows.sort(
        key=lambda row: _parse_time(row.get("shipped_at")) or datetime.fromtimestamp(0, UTC),
        reverse=True,
    )

    ongoing_event = None
    fallback_region_match = None
    for row in memory.get("ongoing_events", []):
        if not isinstance(row, dict):
            continue
        if row.get("event_id") == bundle.event_id:
            ongoing_event = row
            break
        if (
            row.get("signal_kind") == bundle.signal_kind
            and row.get("region") == bundle.where
            and row.get("country") == country
        ):
            fallback_region_match = row
    if ongoing_event is None:
        ongoing_event = fallback_region_match

    shipped_rows = [
        row for row in memory.get("shipped_tweets", []) if isinstance(row, dict)
    ]
    shipped_rows.sort(
        key=_row_time,
        reverse=True,
    )

    # Per-category cooldown: which signal categories have we already posted
    # in the last 24h? The writer reads this to self-veto a same-category
    # draft (or clear a higher bar — meaningfully different mechanic /
    # geography / scale) so the feed doesn't read like two fires in a row.
    # shipped_rows is already most-recent-first; preserve that order while
    # deduping so the writer sees the freshest category first.
    category_cutoff = datetime.now(UTC).timestamp() - _CATEGORY_COOLDOWN_SECONDS
    recent_categories: list[str] = []
    seen_categories: set[str] = set()
    for row in shipped_rows:
        shipped_at = _parse_time(row.get("shipped_at"))
        if shipped_at is None or shipped_at.timestamp() < category_cutoff:
            continue
        kind = row.get("signal_kind")
        if not kind:
            continue
        category = _signal_kind_to_category(kind)
        if category in seen_categories:
            continue
        seen_categories.add(category)
        recent_categories.append(category)

    same_event_rows = []
    if event_keys:
        for row in list(memory.get("shipped_tweets", [])) + list(state.get("drafts", [])):
            if not isinstance(row, dict):
                continue
            row_keys = {
                key for key in (_event_base(row.get("event_id")), row.get("event_series_key"))
                if key
            }
            if not row_keys.intersection(event_keys):
                continue
            text = _tweet_text(row)
            if not text:
                continue
            same_event_rows.append(row)
    same_event_rows.sort(key=_row_time, reverse=True)

    return MemorySlice(
        recent_tweets_same_country=[_tweet_text(row) for row in same_country_rows[:5]],
        recent_tweets_same_event=[_tweet_text(row) for row in same_event_rows[:5]],
        ongoing_event=ongoing_event,
        used_era_anchors=list(memory.get("used_era_anchors", []))[-200:],
        used_peer_comparisons=list(memory.get("used_peer_comparisons", []))[-200:],
        used_framings=list(memory.get("used_framings", []))[-200:],
        shipped_tweet_texts=[
            _tweet_text(row) for row in shipped_rows[:_SHIPPED_TWEET_TEXTS_LIMIT]
        ],
        recent_categories=recent_categories,
    )


def record_shipped(
    state: BotState,
    bundle: StoryBundle,
    writer: WriterResult,
    extracted: list[ExtractedClaim],
) -> None:
    """Write successful two-bot draft memory back into state in place."""

    if writer.tweet is None:
        raise ValueError("Cannot record shipped memory for a killed writer result")

    memory = _memory(state)
    country = _country_for(bundle)
    now = _utc_now_iso()
    event_series_key = _event_series_key(bundle)

    shipped_row = {
        "tweet_text": writer.tweet,
        "signal_kind": bundle.signal_kind,
        "event_id": bundle.event_id,
        "country": country,
        "shipped_at": now,
    }
    if event_series_key:
        shipped_row["event_series_key"] = event_series_key
    memory.setdefault("shipped_tweets", []).append(shipped_row)

    for claim in extracted:
        if claim.kind == "era_anchor":
            _dedup_append(memory.setdefault("used_era_anchors", []), _normalize(claim.text))
        elif claim.kind == "peer_comparison":
            _dedup_append(
                memory.setdefault("used_peer_comparisons", []),
                _normalize(claim.text),
            )

    if writer.angle_chosen:
        _dedup_append(memory.setdefault("used_framings", []), writer.angle_chosen)

    events = memory.setdefault("ongoing_events", [])
    existing = next(
        (row for row in events if isinstance(row, dict) and row.get("event_id") == bundle.event_id),
        None,
    )
    if existing is None:
        events.append(
            {
                "event_id": bundle.event_id,
                "region": bundle.where,
                "country": country,
                "first_seen": _today_iso(),
                "last_seen": _today_iso(),
                "days_running": 1,
                "signal_kind": bundle.signal_kind,
            }
        )
        return

    existing["region"] = bundle.where
    existing["country"] = country
    existing["last_seen"] = _today_iso()
    existing["signal_kind"] = bundle.signal_kind
    first_seen = existing.get("first_seen") or _today_iso()
    try:
        first = date.fromisoformat(first_seen)
        existing["days_running"] = max(1, (date.today() - first).days + 1)
    except (ValueError, TypeError):
        existing["first_seen"] = _today_iso()
        existing["days_running"] = 1


def is_reuse(state: BotState, candidate: str, kind: str) -> bool:
    """Check whether a candidate matches a forever-banned memory element."""

    memory = _memory(state)
    candidate_norm = _normalize(candidate)
    if not candidate_norm:
        return False

    if kind == "tweet_text":
        for row in memory.get("shipped_tweets", []):
            if _normalize(_tweet_text(row)) == candidate_norm:
                return True
        return False

    if kind == "framing":
        candidate_label = str(candidate or "").strip().lower()
        return any(
            str(stored or "").strip().lower() == candidate_label
            for stored in memory.get("used_framings", [])
        )

    if kind not in {"era_anchor", "peer_comparison"}:
        raise ValueError(f"Unsupported reuse kind: {kind}")

    # Branch on the literal key so MemoryState.get returns the precise
    # list[str] type instead of widening to object for runtime keys.
    stored_items: list[str] = (
        memory.get("used_era_anchors", []) if kind == "era_anchor"
        else memory.get("used_peer_comparisons", [])
    )
    candidate_tokens = _tokens(candidate)
    for stored in stored_items:
        stored_norm = _normalize(stored)
        if stored_norm and stored_norm in candidate_norm:
            return True
        stored_tokens = _tokens(stored)
        if stored_tokens and stored_tokens.issubset(candidate_tokens):
            return True
    return False
