"""Stages 2 and 5: persistent memory for the two-bot fire pipeline."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from src import state as state_store
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
        return str(row.get("tweet_text") or "")
    return str(row or "")


def _dedup_append(values: list, value: Any) -> None:
    if value and value not in values:
        values.append(value)


def _memory(state: dict) -> dict:
    return state_store.get_memory(state)


def build_memory_slice(state: dict, bundle: StoryBundle) -> MemorySlice:
    """Assemble the relevant memory for the writer."""

    memory = _memory(state)
    country = _country_for(bundle)
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
        key=lambda row: _parse_time(row.get("shipped_at")) or datetime.fromtimestamp(0, UTC),
        reverse=True,
    )

    return MemorySlice(
        recent_tweets_same_country=[_tweet_text(row) for row in same_country_rows[:5]],
        ongoing_event=ongoing_event,
        used_era_anchors=list(memory.get("used_era_anchors", []))[-200:],
        used_peer_comparisons=list(memory.get("used_peer_comparisons", []))[-200:],
        used_framings=list(memory.get("used_framings", []))[-200:],
        shipped_tweet_texts=[_tweet_text(row) for row in shipped_rows[:100]],
    )


def record_shipped(
    state: dict,
    bundle: StoryBundle,
    writer: WriterResult,
    extracted: list[ExtractedClaim],
) -> None:
    """Write successful fire draft memory back into state in place."""

    if writer.tweet is None:
        raise ValueError("Cannot record shipped memory for a killed writer result")

    memory = _memory(state)
    country = _country_for(bundle)
    now = _utc_now_iso()

    memory.setdefault("shipped_tweets", []).append(
        {
            "tweet_text": writer.tweet,
            "signal_kind": bundle.signal_kind,
            "event_id": bundle.event_id,
            "country": country,
            "shipped_at": now,
        }
    )

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


def is_reuse(state: dict, candidate: str, kind: str) -> bool:
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

    key = "used_era_anchors" if kind == "era_anchor" else "used_peer_comparisons"
    candidate_tokens = _tokens(candidate)
    for stored in memory.get(key, []):
        stored_norm = _normalize(stored)
        if stored_norm and stored_norm in candidate_norm:
            return True
        stored_tokens = _tokens(stored)
        if stored_tokens and stored_tokens.issubset(candidate_tokens):
            return True
    return False

