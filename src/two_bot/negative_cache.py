"""Cross-cycle negative cache for killed writer candidates (economics P1.3).

A candidate that dies at a paid pipeline stage (writer / critic / fact-check /
safety / honesty gates) is very likely to die the same way when the drain
re-attempts it a few hours later with identical material facts — sources
re-emit persistent events every cycle, and ``attempted_event_ids`` only
dedups within ONE cycle. Week-1 post-restore funnel data showed exactly this
shape, the pre-registered trigger for P1.3 in PLAN-ECONOMICS-MASTER-v3 §3.

Because the gates are STOCHASTIC (the writer samples; critic/fact-check judge
one sampled tweet), one kill is deliberately NOT enough to suppress a story —
editorial supply is the known bottleneck, and a fresh sample might pass
(codex r1 P1). The cache therefore activates only after ``min_kills``
(default 2) kills of the same ``(event_id, bundle sha, decision epoch)``:
the first kill records evidence, the second — two independent samplings dead
on byte-identical facts — proves persistence, and attempts 3..N (the modal
waste at ~6 cycles/day) are skipped as $0 ``negative_cache`` pre-writer
kills until the facts change, the epoch changes, or the TTL lapses.

The DECISION EPOCH folds in everything else the verdict depends on that the
bundle doesn't carry: writer model, writer system prompt (sha), and the
sampling/revise flags. A prompt edit, model change, or flag flip invalidates
the whole cache implicitly (codex r1 P1: bundle-only keys outlive the
decision context). The MemorySlice is deliberately NOT part of the key: its
rotating fields (shipped texts, cooldown lists) change nearly every cycle,
so including them would neuter the cache — the min-kills requirement plus a
short TTL bound the residual staleness instead.

Deliberately NOT cached: ``budget_exhausted`` and ``pipeline_error``
(transient — retrying is the point), and save-side rejections (the $0
``can_draft_candidate`` predicates already handle those deterministically).

``THEHEAT_NEGATIVE_CACHE_ENABLED=0`` is the kill-switch; entries expire by
TTL (default 48h), the store is capped newest-first, and pruning runs both
at drain start and INSIDE the state merge (a merge-side prune is what stops
a concurrent stale writer from resurrecting deleted entries — codex r1 P2).
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
_DEFAULT_MIN_KILLS = 2
_KILLS_CLAMP = 1_000_000

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


def min_kills() -> int:
    """Kills of the same (facts, epoch) required before the skip activates.
    Default 2: one stochastic kill must never suppress a story (supply is
    the bottleneck); two independent samplings dead on identical facts is
    strong evidence the third buys nothing."""
    raw = os.environ.get("THEHEAT_NEGATIVE_CACHE_MIN_KILLS", "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MIN_KILLS
    except ValueError:
        return _DEFAULT_MIN_KILLS
    return max(1, min(value, 10))


def bundle_fingerprint(bundle: Any) -> str:
    """Deterministic sha256 over the bundle's canonical JSON — the same
    serialization the writer prompt embeds (sort_keys + json_default), so
    "material facts changed" means exactly "the writer would see different
    bundle input". Returns "" on any serialization failure (callers treat
    "" as never-matching: no skip and no record)."""
    try:
        payload = json.dumps(bundle.to_dict(), sort_keys=True, default=json_default)
    except Exception as exc:  # noqa: BLE001 — a broken bundle must not crash the drain
        print(f"[negative_cache] fingerprint error (ignored): {exc!r}")
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_PROMPT_SHA: str | None = None


def decision_epoch() -> str:
    """Fingerprint of the non-bundle decision context: writer model, writer
    system prompt, and the sampling/revise flags. Any change rotates the
    epoch and implicitly invalidates every cached kill (codex r1 P1). Env
    flags are read per call (cheap) so tests and cycle-level flag flips take
    effect immediately; the prompt sha is computed once per process."""
    global _PROMPT_SHA
    try:
        if _PROMPT_SHA is None:
            from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT

            _PROMPT_SHA = hashlib.sha256(
                WRITER_SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest()[:16]
        from src.two_bot.writer import WRITER_MODEL

        samples = os.environ.get("THEHEAT_WRITER_SAMPLES", "").strip()
        revise = os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED", "").strip()
        return hashlib.sha256(
            f"{WRITER_MODEL}|{_PROMPT_SHA}|s={samples}|r={revise}".encode()
        ).hexdigest()[:16]
    except Exception as exc:  # noqa: BLE001
        print(f"[negative_cache] epoch error (ignored): {exc!r}")
        return ""


def _cache_dict(bot_state: Any) -> dict:
    cache = bot_state.get("writer_negative_cache") if hasattr(bot_state, "get") else None
    if not isinstance(cache, dict):
        cache = {}
        bot_state["writer_negative_cache"] = cache
    return cache


def parse_at(raw: object) -> datetime | None:
    """Parse an entry timestamp to an aware UTC instant; None when invalid.
    Shared with the state merge so both sides agree on validity."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def valid_entry(entry: object) -> bool:
    """Structural validity shared by the merge and read paths: malformed
    entries are dropped, never trusted (codex r1 P2)."""
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("sha"), str)
        and bool(entry.get("sha"))
        and isinstance(entry.get("epoch"), str)
        and parse_at(entry.get("at")) is not None
        and isinstance(entry.get("kills"), int)
        and entry.get("kills", 0) >= 1
    )


def should_skip(
    bot_state: Any,
    event_id: str,
    bundle: Any,
    *,
    now: datetime | None = None,
) -> str | None:
    """PURE predicate (codex r1 P2: no state mutation on the read path).
    Returns a human-readable skip reason when this candidate has been killed
    ``min_kills()``+ times at a paid stage with unchanged material facts and
    an unchanged decision epoch inside the TTL window; None otherwise.
    Never raises. The fingerprint is computed ONLY when a valid entry exists
    for the event_id, so the common case (miss) costs one dict lookup."""
    try:
        if not enabled() or not event_id:
            return None
        entry = _cache_dict(bot_state).get(event_id)
        if not valid_entry(entry):
            return None
        assert isinstance(entry, dict)
        at = parse_at(entry.get("at"))
        assert at is not None
        current = now or datetime.now(timezone.utc)
        age = current - at
        if age < timedelta(0) or age > timedelta(hours=ttl_hours()):
            return None
        if int(entry.get("kills") or 0) < min_kills():
            return None
        if entry.get("epoch") != decision_epoch():
            return None  # prompt/model/flags changed — decision context stale
        sha = bundle_fingerprint(bundle)
        if not sha or sha != entry.get("sha"):
            return None  # facts changed (or unfingerprintable) — re-attempt
        stage = str(entry.get("stage") or "unknown")[:_STAGE_MAX_LEN]
        hours = age.total_seconds() / 3600
        return (
            f"negative cache: killed at {stage} x{entry.get('kills')} "
            f"(last {hours:.1f}h ago), material facts unchanged"
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
    """Remember a paid-stage kill. The kill count increments only while the
    (sha, epoch) pair is unchanged — different facts or a rotated epoch
    restart the evidence at 1. No-ops for non-cacheable stages, missing
    ids/fingerprints, or when disabled. Never raises."""
    try:
        if not enabled() or not event_id or not sha:
            return
        if stage not in CACHEABLE_KILL_STAGES:
            return
        epoch = decision_epoch()
        if not epoch:
            return
        cache = _cache_dict(bot_state)
        prior = cache.get(event_id)
        kills = 1
        if (
            valid_entry(prior)
            and isinstance(prior, dict)
            and prior.get("sha") == sha
            and prior.get("epoch") == epoch
        ):
            kills = min(int(prior.get("kills") or 0) + 1, _KILLS_CLAMP)
        cache[event_id] = {
            "sha": sha,
            "epoch": epoch,
            "stage": str(stage)[:_STAGE_MAX_LEN],
            "reason": str(reason or "")[:_REASON_MAX_LEN],
            "at": (now or datetime.now(timezone.utc)).isoformat(),
            "kills": kills,
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
            at = (
                parse_at(entry.get("at"))
                if isinstance(entry, dict) and valid_entry(entry)
                else None
            )
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
