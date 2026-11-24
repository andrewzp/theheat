"""Stages 2 and 5: persistent memory for the two-bot fire pipeline."""

from __future__ import annotations

import json
import re
from copy import deepcopy
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
    "reported_fire_incident_size": "fire",
    "source_mapped_fire_perimeter": "fire",
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
    "heat_records_cluster": "heat_records_cluster",
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
    "cyclone_land_threat": "cyclone",
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


def _reusable_source_qualifier(value: str) -> bool:
    """A standalone evidence label is not a one-use historical/comparison hook.

    Keep this narrow: a longer substantive claim containing the qualifier still
    participates in novelty checks. Full tweet reuse and factual checks are
    separate and are never exempted. Legacy stored entries remain untouched.
    """
    return re.fullmatch(r"model(?:\s+|\s*[-‐‑‒–—−]\s*)estimated", _normalize(value)) is not None


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
    from src.data.places import country_key
    if bundle.country:
        return country_key(bundle.country)
    country = bundle.raw_signal_dump.get("country")
    if country:
        return country_key(str(country))
    for fact in bundle.current_facts:
        if fact.get("label") == "country":
            return country_key(str(fact.get("value") or ""))
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
    # Legacy identity inspection only. This is not an episode/history join key.
    from src.data.places import event_identity
    identity = event_identity(str(event_id or ""))
    if identity:
        # Signal family + persistent place; dates/point revisions do not merge different cities.
        return str(event_id).split("loc1-", 1)[0] + identity["place_id"]
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


_GDACS_MEMORY_SCHEMA = "gdacs-source-memory/v1"
_NIFC_MEMORY_SCHEMA = "nifc-source-memory/v1"
_NIFC_SNAPSHOT_BYTES = 32 * 1024
_SOURCE_MEMORY_FIELD = "source_event_identity"


def _gdacs_memory_scoped(bundle: StoryBundle) -> bool:
    # The GDACS builder also serves explicit subtype witnesses. Their identity
    # needs its own qualified reader; missing identity never grants a region key.
    return bundle.signal_kind == "global_disaster"


def _airport_observation(bundle: StoryBundle) -> bool:
    from src.data.awc_observed import is_family as is_airport_comparison

    return is_airport_comparison({
        "signal_kind": bundle.signal_kind, "event_id": bundle.event_id,
        "raw_signal_dump": bundle.raw_signal_dump,
    })


def _standalone_observation(bundle: StoryBundle) -> bool:
    """These measurement families do not independently identify an episode."""
    return bundle.signal_kind == "fire" or _airport_observation(bundle)


def _memory_identity(value: Any) -> dict | None:
    """Validate a source-series key, never a physical-incident or review proof."""
    if type(value) is dict and value.get("schema") == _NIFC_MEMORY_SCHEMA:
        if (set(value) != {"schema", "issuer", "event_type", "identifier_kind", "source_event_id"}
                or value["issuer"] != "nifc-wfigs" or value["event_type"] != "WF"
                or type(value["identifier_kind"]) is not str
                or value["identifier_kind"] not in {"UniqueFireIdentifier", "IrwinID"}
                or type(value["source_event_id"]) is not str
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}", value["source_event_id"], re.ASCII)):
            return None
        return dict(value)
    from src.data.gdacs import EVENT_TYPES
    if (type(value) is not dict or set(value) != {"schema", "issuer", "event_type", "source_event_id"}
            or value["schema"] != _GDACS_MEMORY_SCHEMA or value["issuer"] != "gdacs-georss"
            or type(value["event_type"]) is not str or value["event_type"] not in EVENT_TYPES
            or type(value["source_event_id"]) is not str
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", value["source_event_id"], re.ASCII)
            or set(value["source_event_id"]) == {"0"}):
        return None
    return dict(value)


def _gdacs_memory_identity(bundle: StoryBundle) -> dict | None:
    if not _gdacs_memory_scoped(bundle):
        return None
    from src.data.gdacs import EVENT_TYPES, GDACS_GEORSS_LEG, GDACS_GEORSS_URL
    raw = bundle.raw_signal_dump
    provenance = raw.get("source_provenance")
    if type(provenance) is not dict:
        return None
    identity = _memory_identity({"schema": _GDACS_MEMORY_SCHEMA, "issuer": "gdacs-georss",
        "event_type": provenance.get("eventtype"), "source_event_id": raw.get("source_event_id")})
    if identity is None:
        return None
    event_type, source_id = identity["event_type"], identity["source_event_id"]
    prefix = f"gdacs_{event_type}_{source_id}_"
    expected = {"source_product": "gdacs-georss", "source_url": GDACS_GEORSS_URL,
                "source_event_id": source_id, "disaster_type": EVENT_TYPES[event_type]}
    if (type(bundle.event_id) is not str or raw.get("source_leg") != GDACS_GEORSS_LEG or raw.get("event_id") != bundle.event_id
            or not bundle.event_id.startswith(prefix) or len(bundle.event_id) == len(prefix)):
        return None
    for label, value in expected.items():
        facts = [fact for fact in bundle.current_facts if isinstance(fact, dict) and fact.get("label") == label]
        if raw.get(label) != value or len(facts) != 1 or facts[0].get("value") != value:
            return None
    return identity


def _nifc_report_family(bundle: StoryBundle) -> bool:
    from src.data.fire_footprint import KIND, REPORT_SCHEMA

    raw = bundle.raw_signal_dump if isinstance(bundle.raw_signal_dump, dict) else {}
    packet = raw.get("evidence")
    return (bundle.signal_kind in {KIND, "fire_footprint"}
            or str(bundle.event_id).startswith("fire_footprint_")
            or (isinstance(packet, dict) and packet.get("schema") == REPORT_SCHEMA))


def _source_memory_identity(bundle: StoryBundle) -> dict | None:
    if _gdacs_memory_scoped(bundle):
        return _gdacs_memory_identity(bundle)
    if not _nifc_report_family(bundle):
        return None
    from src.data.fire_footprint import historical_report_bundle_hold, report_record_identity

    try:
        if historical_report_bundle_hold(bundle) is not None:
            return None
        raw = bundle.raw_signal_dump
        record = raw["evidence"]["source_record"]
        return _memory_identity(report_record_identity(record))
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        return None


def _nifc_snapshot_fits(value: dict) -> bool:
    try:
        return len(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()) <= _NIFC_SNAPSHOT_BYTES
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def _physical_binding(value):
    if isinstance(value, dict) and (str(value.get("episode_id", "")).startswith("ep1:fire:nifc:")
                                  or value.get("identity_class") == "source_mapped_fire"):
        from src.storage.fire_episodes import validate_binding
    else:
        from src.storage.physical_events import validate_binding
    return validate_binding(value)


def _resolved_episode_context(bundle, context):
    binding = bundle.raw_signal_dump["physical_episode"]
    if isinstance(binding, dict) and (str(binding.get("episode_id", "")).startswith("ep1:fire:nifc:")
                                     or binding.get("identity_class") == "source_mapped_fire"):
        from src.storage.fire_episodes import FireEpisodeContext
        from src.two_bot.intern.fire_perimeter import bundle_hold
        if type(context) is not FireEpisodeContext or bundle_hold(bundle, context) is not None:
            raise ValueError("resolved_fire_context_required")
    else:
        from src.storage.physical_events import EpisodeContext
        if type(context) is not EpisodeContext:
            raise ValueError("resolved_episode_context_required")
        context.validate(binding)
    return context


def bundle_memory_snapshot(bundle: StoryBundle) -> dict:
    """Persist the small bundle subset needed to record publish memory later."""

    snapshot: dict[str, Any] = {
        "signal_kind": bundle.signal_kind,
        "where": bundle.where,
        "when": bundle.when,
        "event_id": bundle.event_id,
        "current_facts": [
            dict(fact) for fact in bundle.current_facts
            if isinstance(fact, dict)
        ],
    }

    if "physical_episode" in bundle.raw_signal_dump:
        snapshot["physical_episode"] = _physical_binding(bundle.raw_signal_dump["physical_episode"])
    else:
        identity = _source_memory_identity(bundle)
        if identity is not None:
            if identity["schema"] == _NIFC_MEMORY_SCHEMA:
                # Retain real report inputs, never rebuild a source proof from
                # the incident identifier alone. Oversize evidence keeps only
                # general publication history; it does not widen source gates.
                candidate = {**snapshot, _SOURCE_MEMORY_FIELD: identity,
                    "raw_signal_dump": bundle.raw_signal_dump, "headline_metric": bundle.headline_metric,
                    "country": bundle.country, "historical_context": bundle.historical_context}
                if _nifc_snapshot_fits(candidate):
                    snapshot = deepcopy(candidate)
            else:
                snapshot[_SOURCE_MEMORY_FIELD] = identity
        if _airport_observation(bundle):
            from src.data.awc_observed import SCHEMA
            from src.data.awc_gust import KIND as GUST_KIND, SCHEMA as GUST_SCHEMA
            # Retain the existing restrictive family marker, never source proof.
            snapshot["raw_signal_dump"] = {"report_schema": GUST_SCHEMA if bundle.signal_kind == GUST_KIND else SCHEMA}
    return snapshot


def build_memory_slice(state: BotState, bundle: StoryBundle, *, now: datetime | None = None, episode_context=None) -> MemorySlice:
    """Assemble the relevant memory for the writer."""

    from src.data.places import country_key
    bound = "physical_episode" in bundle.raw_signal_dump
    source_scoped = _gdacs_memory_scoped(bundle)
    nifc_report = _nifc_report_family(bundle)
    # Pixels and two-airport snapshots do not establish physical continuity.
    # Resolved physical bindings remain separate and are validated first.
    standalone_observation = not bound and _standalone_observation(bundle)
    source_identity = _source_memory_identity(bundle) if not bound else None
    if bound:
        _resolved_episode_context(bundle, episode_context)
    elif episode_context is not None:
        raise ValueError("unexpected_episode_context")
    memory = _memory(state)
    fire_bound = bound and bundle.raw_signal_dump["physical_episode"].get("identity_class") == "source_mapped_fire"
    country = _country_for(bundle)
    instant = now if now is not None else datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("memory_clock_requires_timezone")
    cutoff = instant.timestamp() - (30 * 24 * 60 * 60)

    same_country_rows = []
    for row in memory.get("shipped_tweets", []):
        if not isinstance(row, dict) or country_key(row.get("country", "")) != country:
            continue
        if fire_bound and not episode_context.published_reference(row):
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
    source_prior = None
    for row in memory.get("ongoing_events", []):
        if not isinstance(row, dict):
            continue
        if bound:
            if not fire_bound and episode_context.contains(row):
                ongoing_event = row
                break
            continue
        if row.get("physical_episode") is not None or standalone_observation:
            continue
        if source_scoped:
            if source_identity is not None and _memory_identity(row.get(_SOURCE_MEMORY_FIELD)) == source_identity:
                source_prior = row
                break
            continue
        # Even the same complete candidate ID is publication history, not proof
        # of a physical episode. Only the resolved bound branch can grant that.

    shipped_rows = [
        row for row in memory.get("shipped_tweets", []) if isinstance(row, dict)
        and (not fire_bound or episode_context.published_reference(row))
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
    category_cutoff = instant.timestamp() - _CATEGORY_COOLDOWN_SECONDS
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
    source_rows = []
    if bound:
        same_event_rows = [row for row in memory.get("shipped_tweets", [])
                           if isinstance(row, dict) and episode_context.contains(row) and _tweet_text(row)]
    elif source_scoped:
        source_rows = [row for row in memory.get("shipped_tweets", [])
                       if isinstance(row, dict) and row.get("physical_episode") is None
                       and source_identity is not None
                       and _memory_identity(row.get(_SOURCE_MEMORY_FIELD)) == source_identity and _tweet_text(row)]
    elif nifc_report:
        # Exact candidate publication history retains its original limited
        # meaning, even for legacy reports. Cross-candidate report history
        # additionally needs a qualified current and stored source identity.
        for row in memory.get("shipped_tweets", []):
            if not isinstance(row, dict) or row.get("physical_episode") is not None or not _tweet_text(row):
                continue
            identity = _memory_identity(row.get(_SOURCE_MEMORY_FIELD))
            if source_identity is not None and identity == source_identity:
                source_rows.append(row)
            candidate_history = (row.get(_SOURCE_MEMORY_FIELD) is None
                or identity is not None and identity["schema"] == _NIFC_MEMORY_SCHEMA
                    and (source_identity is None or identity == source_identity))
            if candidate_history and row.get("event_id") == bundle.event_id:
                same_event_rows.append(row)
    elif not standalone_observation and bundle.event_id:
        for row in memory.get("shipped_tweets", []):
            if not isinstance(row, dict):
                continue
            if row.get("physical_episode") is not None or row.get(_SOURCE_MEMORY_FIELD) is not None:
                continue
            if row.get("event_id") != bundle.event_id:
                continue
            text = _tweet_text(row)
            if not text:
                continue
            same_event_rows.append(row)
    same_event_rows.sort(key=_row_time, reverse=True)
    source_rows.sort(key=_row_time, reverse=True)
    if source_identity is not None and source_identity["schema"] == _NIFC_MEMORY_SCHEMA:
        source_prior = source_rows[0] if source_rows else None
    source_series = None
    if not bound and source_identity is not None:
        source_series = {
            "identity": source_identity,
            "claim_limit": ("Same NIFC incident report identifier only; not a measured burn perimeter, fire spread, continuous burning, growth rate or combined impacts."
                if source_identity["schema"] == _NIFC_MEMORY_SCHEMA else
                "Shared GDACS report ID only; not proof of one physical incident, continuous conditions, duration or combined impacts."),
            "previous_report_context": ({"event_id": source_prior.get("event_id"),
                "reported_country": source_prior.get("country"),
                "reported_region": source_prior.get("reported_region") if source_identity["schema"] == _NIFC_MEMORY_SCHEMA else source_prior.get("region")}
                if source_prior is not None else None),
            "recent_published_texts": [_tweet_text(row) for row in source_rows[:5]],
        }

    if fire_bound:
        # All map facts are reconstructed from immutable retained source rows;
        # publishing clocks/first_seen/days_running are never factual duration.
        ongoing_event = episode_context.map_memory()
    return MemorySlice(
        recent_tweets_same_country=[_tweet_text(row) for row in same_country_rows[:5]],
        recent_tweets_same_event=[_tweet_text(row) for row in same_event_rows[:5]],
        ongoing_event=ongoing_event,
        used_era_anchors=[item for item in memory.get("used_era_anchors", []) if not _reusable_source_qualifier(item)][-200:],
        used_peer_comparisons=[item for item in memory.get("used_peer_comparisons", []) if not _reusable_source_qualifier(item)][-200:],
        used_framings=list(memory.get("used_framings", []))[-200:],
        shipped_tweet_texts=[
            _tweet_text(row) for row in shipped_rows[:_SHIPPED_TWEET_TEXTS_LIMIT]
        ],
        recent_categories=recent_categories,
        source_report_series=source_series,
    )


def record_shipped(
    state: BotState,
    bundle: StoryBundle,
    writer: WriterResult,
    extracted: list[ExtractedClaim],
    *,
    tweet_id: str | None = None,
    shipped_at: str | None = None,
) -> None:
    """Write successful two-bot publish memory back into state in place."""

    if writer.tweet is None:
        raise ValueError("Cannot record shipped memory for a killed writer result")

    memory = _memory(state)
    country = _country_for(bundle)
    now = shipped_at or _utc_now_iso()
    event_series_key = _event_series_key(bundle)

    shipped_row: dict[str, Any] = {
        "tweet_text": writer.tweet,
        "signal_kind": bundle.signal_kind,
        "event_id": bundle.event_id,
        "country": country,
        "shipped_at": now,
    }
    binding = None
    source_identity = None
    if "physical_episode" in bundle.raw_signal_dump:
        binding = _physical_binding(bundle.raw_signal_dump["physical_episode"])
        shipped_row["physical_episode"] = binding
    else:
        source_identity = _source_memory_identity(bundle)
        if source_identity is not None:
            shipped_row[_SOURCE_MEMORY_FIELD] = source_identity
            if source_identity["schema"] == _NIFC_MEMORY_SCHEMA:
                shipped_row["reported_region"] = bundle.where
    if tweet_id:
        shipped_row["tweet_id"] = tweet_id
    if event_series_key:
        shipped_row["event_series_key"] = event_series_key
    memory.setdefault("shipped_tweets", []).append(shipped_row)

    for claim in extracted:
        if _reusable_source_qualifier(claim.text):
            continue
        if claim.kind == "era_anchor":
            _dedup_append(memory.setdefault("used_era_anchors", []), _normalize(claim.text))
        elif claim.kind == "peer_comparison":
            _dedup_append(
                memory.setdefault("used_peer_comparisons", []),
                _normalize(claim.text),
            )

    if writer.angle_chosen:
        _dedup_append(memory.setdefault("used_framings", []), writer.angle_chosen)

    if binding is not None and binding["identity_class"] == "source_mapped_fire":
        # Publication bookkeeping cannot mint mapped-incident facts or duration.
        return

    if binding is None and (_standalone_observation(bundle) or source_identity is None
                            or source_identity["schema"] == _NIFC_MEMORY_SCHEMA):
        # Keep general/exact-candidate history, never infer physical duration
        # from an unbound publication. Qualified GDACS series bookkeeping is
        # preserved separately and is never returned as a physical episode.
        return

    events = memory.setdefault("ongoing_events", [])
    existing = next(
        (row for row in events if isinstance(row, dict)
         and (row.get("physical_episode", {}).get("episode_id") == binding["episode_id"] if binding
              else row.get("physical_episode") is None and (
                  _memory_identity(row.get(_SOURCE_MEMORY_FIELD)) == source_identity if source_identity is not None
                  else row.get(_SOURCE_MEMORY_FIELD) is None and row.get("event_id") == bundle.event_id))),
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
                **({"physical_episode": binding} if binding else {}),
                **({_SOURCE_MEMORY_FIELD: dict(source_identity)} if source_identity is not None else {}),
                "signal_kind": bundle.signal_kind,
            }
        )
        return

    if binding:
        existing["physical_episode"] = binding
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


def _two_bot_metadata_from_draft(draft: dict) -> dict | None:
    direct = draft.get("two_bot_metadata")
    if isinstance(direct, dict):
        return direct
    review_context = draft.get("review_context")
    if not isinstance(review_context, dict):
        return None
    two_bot = review_context.get("two_bot")
    return two_bot if isinstance(two_bot, dict) else None


def _story_bundle_from_metadata(two_bot: dict, draft: dict) -> StoryBundle | None:
    payload = two_bot.get("bundle")
    if not isinstance(payload, dict):
        payload = {}
    event_id = str(payload.get("event_id") or draft.get("event_id") or "")
    signal_kind = str(payload.get("signal_kind") or two_bot.get("signal_kind") or draft.get("type") or "")
    if not event_id or not signal_kind:
        return None
    facts_raw = payload.get("current_facts")
    current_facts = [
        dict(fact) for fact in facts_raw
        if isinstance(fact, dict)
    ] if isinstance(facts_raw, list) else []
    # This miniature bundle is used only to record retained publication memory,
    # never as source evidence or a fresh input to generation/scientific checks.
    raw = {"physical_episode": payload["physical_episode"]} if "physical_episode" in payload else {}
    identity = _memory_identity(payload.get(_SOURCE_MEMORY_FIELD))
    if not raw and identity is not None and identity["schema"] == _GDACS_MEMORY_SCHEMA:
        from src.data.gdacs import EVENT_TYPES, GDACS_GEORSS_LEG, GDACS_GEORSS_URL
        raw = {"event_id": event_id, "source_product": "gdacs-georss", "source_url": GDACS_GEORSS_URL,
               "source_leg": GDACS_GEORSS_LEG, "source_event_id": identity["source_event_id"],
               "disaster_type": EVENT_TYPES[identity["event_type"]],
               "source_provenance": {"eventtype": identity["event_type"]}}
    if "physical_episode" not in payload:
        from src.data.awc_observed import SCHEMA, is_family as is_airport_comparison
        from src.data.awc_gust import KIND as GUST_KIND, SCHEMA as GUST_SCHEMA
        if is_airport_comparison(payload):
            # Other source hints cannot erase this restriction. Explicit physical
            # bindings still go through their original validation first.
            raw = {"report_schema": GUST_SCHEMA if signal_kind == GUST_KIND else SCHEMA}
    restored = StoryBundle(
        signal_kind=signal_kind,
        where=str(payload.get("where") or draft.get("city") or ""),
        when=str(payload.get("when") or draft.get("tweet_date") or ""),
        event_id=event_id,
        headline_metric={},
        current_facts=current_facts,
        historical_context={},
        raw_signal_dump=raw,
    )
    if not raw and identity is not None and identity["schema"] == _NIFC_MEMORY_SCHEMA and _nifc_snapshot_fits(payload):
        strings = ("signal_kind", "where", "when", "event_id", "country")
        objects = ("raw_signal_dump", "headline_metric", "historical_context")
        # Audit exact retained inputs, never the generic reader's repaired
        # dates, fallback identifiers or filtered fact list above. That reader
        # remains available only for limited ordinary publication history.
        if (all(type(payload.get(key)) is str for key in strings)
                and all(type(payload.get(key)) is dict for key in objects)
                and type(payload.get("current_facts")) is list):
            exact = StoryBundle(**deepcopy({key: payload[key] for key in (*strings, *objects, "current_facts")}))
            if _source_memory_identity(exact) == identity:
                return exact
    return restored


def _claims_from_metadata(two_bot: dict) -> list[ExtractedClaim]:
    fact_check = two_bot.get("fact_check")
    if not isinstance(fact_check, dict):
        return []
    raw_claims = fact_check.get("extracted_claims")
    if not isinstance(raw_claims, list):
        return []
    claims: list[ExtractedClaim] = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        kind = str(raw.get("kind") or "").strip()
        if text and kind:
            claims.append(ExtractedClaim(text=text, kind=kind))
    return claims


def _published_memory_already_recorded(memory: MemoryState, tweet_id: str) -> bool:
    for row in memory.get("shipped_tweets", []):
        if not isinstance(row, dict):
            continue
        if tweet_id and row.get("tweet_id") == tweet_id:
            return True
    return False


def record_published_draft(state: BotState, draft: dict) -> bool:
    """Record two-bot memory for a draft only after it is actually published."""

    if not isinstance(draft, dict):
        return False
    tweet_text = _tweet_text(draft)
    if not tweet_text.strip():
        return False
    two_bot = _two_bot_metadata_from_draft(draft)
    if two_bot is None:
        return False
    bundle = _story_bundle_from_metadata(two_bot, draft)
    if bundle is None:
        return False
    tweet_id = str(draft.get("tweet_id") or "").strip()
    memory = _memory(state)
    if _published_memory_already_recorded(memory, tweet_id):
        return False
    from src.editorial.revisions import review_is_current

    current_model_review = (
        review_is_current(draft)
        and (draft.get("review_binding") or {}).get("kind") == "model"
    )
    writer = WriterResult(
        tweet=tweet_text,
        kill_reason=None,
        angle_chosen=str(two_bot.get("angle_chosen") or "") if current_model_review else "",
        era_anchor_used=(
            str(two_bot.get("era_anchor_used"))
            if current_model_review and two_bot.get("era_anchor_used") is not None else None
        ),
        peer_comparison_used=(
            str(two_bot.get("peer_comparison_used"))
            if current_model_review and two_bot.get("peer_comparison_used") is not None else None
        ),
        reasoning=str(two_bot.get("reasoning") or "") if current_model_review else "",
    )
    shipped_at = str(draft.get("posted_at") or "").strip() or None
    record_shipped(
        state,
        bundle,
        writer,
        _claims_from_metadata(two_bot) if current_model_review else [],
        tweet_id=tweet_id or None,
        shipped_at=shipped_at,
    )
    return True


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
    if _reusable_source_qualifier(candidate):
        return False

    # Branch on the literal key so MemoryState.get returns the precise
    # list[str] type instead of widening to object for runtime keys.
    stored_items: list[str] = (
        memory.get("used_era_anchors", []) if kind == "era_anchor"
        else memory.get("used_peer_comparisons", [])
    )
    candidate_tokens = _tokens(candidate)
    for stored in stored_items:
        if _reusable_source_qualifier(stored):
            continue
        stored_norm = _normalize(stored)
        if stored_norm and stored_norm in candidate_norm:
            return True
        stored_tokens = _tokens(stored)
        if stored_tokens and stored_tokens.issubset(candidate_tokens):
            return True
    return False
