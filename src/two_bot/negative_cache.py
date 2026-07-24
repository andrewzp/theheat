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
# ``critic`` is deliberately EXCLUDED (codex r7): critic verdicts also weigh
# today's pending-drafts context, which rolls over constantly — a cached
# critic kill could suppress a story that became viable when the queue
# changed, and critic kills are a tiny share of paid kills anyway (2 of the
# last 100 suppressions at review time). The remaining stages judge the
# tweet against the BUNDLE (fact_check) or against fixed rules (safety /
# honesty / cross-signal), both fully covered by the fingerprint + epoch.
CACHEABLE_KILL_STAGES = frozenset(
    {"writer", "fact_check", "safety", "honesty_gate", "cross_signal"}
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
    Default 2; the FLOOR is also 2 — "one stochastic kill never suppresses a
    story" is an invariant, not a tunable (codex r2 P1): supply is the
    bottleneck, and a mis-set env var must not quietly re-open that failure
    mode. The knob only goes UP (more evidence required)."""
    raw = os.environ.get("THEHEAT_NEGATIVE_CACHE_MIN_KILLS", "").strip()
    try:
        value = int(raw) if raw else _DEFAULT_MIN_KILLS
    except ValueError:
        return _DEFAULT_MIN_KILLS
    return max(2, min(value, 10))


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
    """Fingerprint of the non-bundle decision context (codex r1–r3 P1):

    - Repo VERSION (every code PR bumps it — ANY shipped change to
      writer/critic/fact-check/safety/honesty code or prompts rotates the
      epoch). A VERSION read failure returns "" — fail-open/no-op, NOT a
      stable "unknown" that would defeat deploy rotation (codex r3).
    - The effective verdict-producing model ids: writer, critic,
      fact-checker, AND the safety Layer-2 Gemini model with its
      enabled-state (module constants resolve their env overrides), plus
      the writer system-prompt sha (cached — the only expensive input).
    - Runtime flags read per call: writer samples, critic-revise, and
      THEHEAT_CRITIC_ENABLED (disabling an over-killing critic MUST reopen
      cached candidates).

    The MemorySlice is deliberately excluded (see module docstring): its
    rotating fields would neuter the cache; min_kills + TTL bound that
    residual staleness. Returns "" on any failure (callers no-op)."""
    global _PROMPT_SHA
    try:
        from pathlib import Path

        if _PROMPT_SHA is None:
            from src.two_bot.prompts.writer_prompt import WRITER_SYSTEM_PROMPT

            _PROMPT_SHA = hashlib.sha256(
                WRITER_SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest()[:16]
        from src.two_bot.critic import CRITIC_MODEL
        from src.two_bot.fact_check import FACT_CHECKER_MODEL
        from src.two_bot.writer import WRITER_MODEL
        from src.voice import safety as _safety

        version = (
            Path(__file__).resolve().parents[2].joinpath("VERSION")
            .read_text().strip()
        )
        if not version:
            return ""
        samples = os.environ.get("THEHEAT_WRITER_SAMPLES", "").strip()
        revise = os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED", "").strip()
        critic = os.environ.get("THEHEAT_CRITIC_ENABLED", "").strip()
        # Safety's Layer-2 is a Gemini LLM whenever the module sees a key
        # (codex r4 P1) — its model AND its effective enabled-state are
        # verdict context. Read the MODULE attributes safety actually gates
        # on (not the env directly) so the epoch matches the gate's own
        # behavior; the key VALUE never enters the hash input.
        GEMINI_SAFETY_MODEL = _safety.GEMINI_SAFETY_MODEL
        safety_on = "1" if getattr(_safety, "GEMINI_API_KEY", "") else "0"
        return hashlib.sha256(
            f"{version}|{WRITER_MODEL}|{CRITIC_MODEL}|{FACT_CHECKER_MODEL}|"
            f"{GEMINI_SAFETY_MODEL}|g={safety_on}|"
            f"{_PROMPT_SHA}|s={samples}|r={revise}|c={critic}".encode()
        ).hexdigest()[:16]
    except Exception as exc:  # noqa: BLE001
        print(f"[negative_cache] epoch error (ignored): {exc!r}")
        return ""


def _cache_dict(bot_state: Any) -> dict:
    """WRITE-path getter: ensures the key exists. Read paths must use
    ``_cache_view`` — inserting on read made should_skip impure (codex r2)."""
    cache = bot_state.get("writer_negative_cache") if hasattr(bot_state, "get") else None
    if not isinstance(cache, dict):
        cache = {}
        bot_state["writer_negative_cache"] = cache
    return cache


def _cache_view(bot_state: Any) -> dict:
    """READ-path getter: never mutates state; missing/corrupt → empty view."""
    cache = bot_state.get("writer_negative_cache") if hasattr(bot_state, "get") else None
    return cache if isinstance(cache, dict) else {}


def parse_at(raw: object) -> datetime | None:
    """Parse an entry timestamp to an aware UTC instant; None when invalid.
    Shared with the state merge so both sides agree on validity. The WHOLE
    conversion is guarded: ``astimezone`` raises OverflowError on boundary
    stamps like ``0001-01-01T00:00:00+14:00`` — one corrupt persisted entry
    must be dropped, never abort a state write (codex r3 P1)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def valid_entry(entry: object) -> bool:
    """Structural validity shared by the merge and read paths: malformed or
    out-of-contract entries are dropped, never trusted (codex r1+r2 P2).
    Beyond shape this enforces the SEMANTIC contract: the stage must be one
    this cache is allowed to hold (a structurally-clean ``budget_exhausted``
    row from a corrupt overlay must not suppress), kills is a true int
    (bool is an int subclass) inside the clamp, and the epoch is non-empty
    (an empty epoch means the decision context was unknowable)."""
    if not isinstance(entry, dict):
        return False
    sha = entry.get("sha")
    epoch = entry.get("epoch")
    stage = entry.get("stage")
    kills = entry.get("kills")
    return (
        isinstance(sha, str)
        and len(sha) == 64
        and all(c in "0123456789abcdef" for c in sha)
        and isinstance(epoch, str)
        and bool(epoch)
        and isinstance(stage, str)
        and stage in CACHEABLE_KILL_STAGES
        and parse_at(entry.get("at")) is not None
        and type(kills) is int
        and 1 <= kills <= _KILLS_CLAMP
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
        entry = _cache_view(bot_state).get(event_id)
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
        current = now or datetime.now(timezone.utc)
        kills = 1
        if (
            valid_entry(prior)
            and isinstance(prior, dict)
            and prior.get("sha") == sha
            and prior.get("epoch") == epoch
        ):
            # Evidence must itself be FRESH: a prior kill older than the TTL
            # is expired evidence — incrementing it would let two kills 60h
            # apart activate the skip (codex r2: expired-evidence
            # resurrection). Stale prior → the count restarts at 1.
            prior_at = parse_at(prior.get("at"))
            if (
                prior_at is not None
                and timedelta(0) <= (current - prior_at) <= timedelta(hours=ttl_hours())
            ):
                kills = min(int(prior.get("kills") or 0) + 1, _KILLS_CLAMP)
        cache[event_id] = {
            "sha": sha,
            "epoch": epoch,
            "stage": str(stage)[:_STAGE_MAX_LEN],
            "reason": str(reason or "")[:_REASON_MAX_LEN],
            "at": current.isoformat(),
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
            # Sort by PARSED instant, not the raw string — mixed offsets
            # would otherwise evict a newer instant over an older one
            # (codex r2 P2). Everything here survived valid_entry above.
            def _instant(key: str) -> datetime:
                at = parse_at(cache[key].get("at"))
                return at if at is not None else datetime.min.replace(tzinfo=timezone.utc)

            oldest_first = sorted(cache.keys(), key=_instant)
            for key in oldest_first[: len(cache) - NEGATIVE_CACHE_MAX_ENTRIES]:
                del cache[key]
                removed += 1
        return removed
    except Exception as exc:  # noqa: BLE001
        print(f"[negative_cache] prune error (ignored): {exc!r}")
        return 0
