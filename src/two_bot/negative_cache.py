"""Cross-cycle negative cache for killed writer candidates (economics P1.3).

A candidate that dies at a PAID pipeline stage (writer / critic / fact-check /
safety / honesty gates) is very likely to die the same way when the drain
re-attempts it a few hours later with identical material facts — sources
re-emit persistent events every cycle, and ``attempted_event_ids`` only
dedups within ONE cycle. Week-1 post-restore funnel data showed exactly this
shape (same event killed at the writer in consecutive cycles), which is the
pre-registered trigger for this cache in PLAN-ECONOMICS-MASTER-v3 §3 P1.3.

Mechanics: after a paid-stage kill, the drain records
``(event_id → {sha, stage, at})`` where ``sha`` fingerprints the bundle's
deterministic JSON. On later cycles the drain skips a candidate iff an entry
exists, the fingerprint STILL MATCHES (material facts unchanged — a forecast
that updates its numbers re-qualifies immediately), and the entry is younger
than the TTL. Skips are recorded as ``negative_cache`` pre-writer kills, so
the funnel/dashboard show exactly what was suppressed and why.

Deliberately NOT cached: ``budget_exhausted`` and ``pipeline_error``
(transient — retrying is the point), and save-side rejections (the $0
``can_draft_candidate`` predicates already handle those deterministically).

Safety posture: a false positive here skips a re-attempt of a bundle that an
editorial gate already killed with byte-identical facts — the cheap, safe
direction. ``THEHEAT_NEGATIVE_CACHE_ENABLED=0`` is the kill-switch; entries
expire by TTL (default 48h) and the store is capped, newest-first.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.two_bot.json_utils import json_default

# Paid-stage kills worth remembering across cycles. Everything else either
# must retry (billing, transient errors) or is already a $0 predicate.
CACHEABLE_KILL_STAGES = frozenset(
    {"writer", "critic", "fact_check", "safety", "honesty_gate", "cross_signal"}
)

NEGATIVE_CACHE_MAX_ENTRIES = 200
_DEFAULT_TTL_HOURS = 48.0

_STAGE_MAX_LEN = 40
_REASON_MAX_LEN = 160


def enabled() -> bool:
    """Kill-switch (default ON). ``THEHEAT_NEGATIVE_CACHE_ENABLED=0`` turns
    the cache off without a deploy — both the skip predicate AND the record
    side honor it, so flipping off stops all cache behavior at once."""
    raw = os.environ.get("THEHEAT_NEGATIVE_CACHE_ENABLED", "").strip().lower()
    return raw not in {"0", "false", "off", "no"}


def ttl_hours() -> float:
    raw = os.environ.get("THEHEAT_NEGATIVE_CACHE_TTL_H", "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_TTL_HOURS
    except ValueError:
        return _DEFAULT_TTL_HOURS
    # Clamp to sane bounds: 0 disables retention (nothing ever skips),
    # anything past a week is almost certainly a typo'd unit.
    return max(0.0, min(value, 168.0))


def bundle_fingerprint(bundle: Any) -> str:
    """Deterministic sha256 over the bundle's canonical JSON — the same
    serialization the writer prompt embeds (sort_keys + json_default), so
    "material facts changed" means exactly "the writer would see different
    input". Returns "" on any serialization failure (callers treat "" as
    never-matching, i.e. no skip and no record)."""
    try:
        payload = json.dumps(bundle.to_dict(), sort_keys=True, default=json_default)
    except Exception as exc:  # noqa: BLE001 — a broken bundle must not crash the drain
        print(f"[negative_cache] fingerprint error (ignored): {exc!r}")
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_dict(bot_state: Any) -> dict:
    cache = bot_state.get("writer_negative_cache") if hasattr(bot_state, "get") else None
    if not isinstance(cache, dict):
        cache = {}
        bot_state["writer_negative_cache"] = cache
    return cache


def _parse_at(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def should_skip(
    bot_state: Any,
    event_id: str,
    bundle: Any,
    *,
    now: datetime | None = None,
) -> str | None:
    """Return a human-readable skip reason when this candidate was already
    killed at a paid stage with unchanged material facts inside the TTL
    window; None otherwise. Never raises. The fingerprint is computed ONLY
    when an entry exists for the event_id, so the common case (cache miss)
    costs one dict lookup."""
    try:
        if not enabled() or not event_id:
            return None
        entry = _cache_dict(bot_state).get(event_id)
        if not isinstance(entry, dict):
            return None
        at = _parse_at(entry.get("at"))
        if at is None:
            return None
        current = now or datetime.now(timezone.utc)
        age = current - at
        if age < timedelta(0) or age > timedelta(hours=ttl_hours()):
            return None
        sha = bundle_fingerprint(bundle)
        if not sha or sha != entry.get("sha"):
            return None  # facts changed (or unfingerprintable) — re-attempt
        entry["hits"] = int(entry.get("hits") or 0) + 1
        stage = str(entry.get("stage") or "unknown")[:_STAGE_MAX_LEN]
        hours = age.total_seconds() / 3600
        return (
            f"negative cache: killed at {stage} {hours:.1f}h ago, "
            f"material facts unchanged"
        )
    except Exception as exc:  # noqa: BLE001 — a cache bug must never block drafting
        print(f"[negative_cache] should_skip error (ignored): {exc!r}")
        return None


def record_kill(
    bot_state: Any,
    event_id: str,
    sha: str,
    stage: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> None:
    """Remember a paid-stage kill. No-ops for non-cacheable stages, missing
    ids/fingerprints, or when disabled. Never raises."""
    try:
        if not enabled() or not event_id or not sha:
            return
        if stage not in CACHEABLE_KILL_STAGES:
            return
        cache = _cache_dict(bot_state)
        cache[event_id] = {
            "sha": sha,
            "stage": str(stage)[:_STAGE_MAX_LEN],
            "reason": str(reason or "")[:_REASON_MAX_LEN],
            "at": (now or datetime.now(timezone.utc)).isoformat(),
            "hits": 0,
        }
        prune(bot_state, now=now)
    except Exception as exc:  # noqa: BLE001 — accounting must never break the drain
        print(f"[negative_cache] record error (ignored): {exc!r}")


def prune(bot_state: Any, *, now: datetime | None = None) -> int:
    """Drop TTL-expired and malformed entries; cap the store newest-first.
    Returns the number of entries removed. Never raises."""
    try:
        cache = _cache_dict(bot_state)
        current = now or datetime.now(timezone.utc)
        ttl = timedelta(hours=ttl_hours())
        removed = 0
        for key in list(cache.keys()):
            entry = cache.get(key)
            at = _parse_at(entry.get("at")) if isinstance(entry, dict) else None
            if at is None or (current - at) > ttl or (current - at) < timedelta(0):
                del cache[key]
                removed += 1
        if len(cache) > NEGATIVE_CACHE_MAX_ENTRIES:
            oldest_first = sorted(
                cache.keys(), key=lambda k: str(cache[k].get("at") or "")
            )
            for key in oldest_first[: len(cache) - NEGATIVE_CACHE_MAX_ENTRIES]:
                del cache[key]
                removed += 1
        return removed
    except Exception as exc:  # noqa: BLE001
        print(f"[negative_cache] prune error (ignored): {exc!r}")
        return 0
