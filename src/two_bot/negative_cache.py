"""Bounded retry deferral for repeated model-attributed evidence rejections.

Adapted from PR #464, exact head 2b70565a44faaecef4c2c818ca5f89a1841e799f
(econ/p13-negative-cache). Retains its two independently fresh failures,
per-kill TTL, pure lookup, kill switch and bounded store. Narrowed to explicit
writer evidence dispositions: generated-text, style, queue-context, parser,
transport and billing failures cannot declare an event unviable. A cached
verdict remains the model's judgment, never proof that the source is wrong.
"""

from __future__ import annotations

import hashlib
import json
import os
import math
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from typing import Any, TypeGuard, cast
from src.state_schema import BotState

from src.two_bot.json_utils import json_default

CACHEABLE_KILL_STAGES = frozenset({"writer"})
EVIDENCE_KILL_CODES = frozenset({"insufficient_evidence", "conflicting_evidence"})
CACHE_POLICY_VERSION = "p08-evidence-rejection-v1"

NEGATIVE_CACHE_MAX_ENTRIES = 200
_DEFAULT_TTL_HOURS = 12.0
_DEFAULT_MIN_KILLS = 2
# Per-kill timestamps kept per entry (codex r10: the activation threshold
# counts only INDIVIDUALLY fresh kills, so each one needs its own stamp).
# Must exceed min_kills' upper clamp (10) so the cap can never mask a real
# activation; 12 stamps ≈ 300B/entry keeps state growth trivial (#390).
_KILLS_AT_CAP = 12

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
    if not math.isfinite(value):
        return _DEFAULT_TTL_HOURS
    # Clamp to sane bounds: 0 disables retention (nothing ever skips),
    # retention is never longer than 48 hours.
    return max(0.0, min(value, 48.0))


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


def bundle_fingerprint(bundle: Any, bot_state=None) -> str:
    """Exact bundle plus actual writer memory; volatile evidence is not dropped.

    Changed context reopens a rejection even when weather values are identical.
    This intentionally prefers missed reuse to hiding a newly viable event.
    """
    try:
        from src.two_bot.memory import build_memory_slice

        memory_state = dict(bot_state or {})
        memory_state["memory"] = deepcopy(memory_state.get("memory"))
        context = build_memory_slice(cast(BotState, memory_state), bundle).to_dict()
        payload = json.dumps(
            {"bundle": bundle.to_dict(), "memory": context},
            sort_keys=True,
            default=json_default,
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def decision_epoch() -> str:
    """Hash effective model/prompt/policy inputs; no VERSION-only assumption."""
    try:
        from pathlib import Path
        from src.two_bot import writer, critic, fact_check, pipeline
        from src.two_bot.prompts import writer_prompt, critic_prompt, fact_check_prompt
        from src.voice import safety

        prompt_values = {
            module.__name__: {
                name: value
                for name, value in vars(module).items()
                if name.isupper()
                and isinstance(value, str)
                and ("PROMPT" in name or "GUIDANCE" in name)
            }
            for module in (
                writer_prompt,
                critic_prompt,
                fact_check_prompt,
                writer,
                critic,
                fact_check,
            )
        }
        # Source changes to deterministic policy, response interpretation or
        # writer context reopen even when a deploy did not bump VERSION.
        root = Path(__file__).resolve().parents[2]
        policy_files = (
            "src/two_bot/negative_cache.py",
            "src/two_bot/writer.py",
            "src/two_bot/pipeline.py",
            "src/two_bot/strict_contract.py",
            "src/two_bot/evidence_contract.py",
            "src/two_bot/scientific_claims.py",
            "src/two_bot/critic.py",
            "src/two_bot/fact_check.py",
            "src/two_bot/memory.py",
            "src/voice/safety.py",
            "src/two_bot/types.py",
            "src/two_bot/json_utils.py",
            "src/data/temperature_evidence.py",
            "src/data/places.py",
            "src/config.py",
        )
        payload = {
            "policy": CACHE_POLICY_VERSION,
            "prompts": prompt_values,
            "policy_files": {
                name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                for name in policy_files
            },
            "models": {
                "writer": writer.WRITER_MODEL,
                "critic": critic.CRITIC_MODEL,
                "fact_check": fact_check.FACT_CHECKER_MODEL,
                "safety": safety.GEMINI_SAFETY_MODEL,
            },
            "writer_provider": getattr(writer, "WRITER_PROVIDER", None),
            "samples": pipeline._writer_samples(),
            "critic_enabled": pipeline._critic_enabled(),
            "revise": os.environ.get("THEHEAT_CRITIC_REVISE_ENABLED", ""),
            "safety_enabled": bool(safety.GEMINI_API_KEY),
            "output_schema": writer.WRITER_OUTPUT_SCHEMA,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
    except Exception:
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
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def valid_entry(entry: object) -> TypeGuard[dict[str, Any]]:
    """Structural validity shared by the merge and read paths: malformed or
    out-of-contract entries are dropped, never trusted (codex r1+r2 P2).
    Beyond shape this enforces the SEMANTIC contract: the stage must be one
    this cache is allowed to hold (a structurally-clean ``budget_exhausted``
    row from a corrupt overlay must not suppress), kills is a true int
    (bool is an int subclass) that EQUALS the per-kill stamp count
    (codex r10 — the stamps are the evidence; a divergent summary int is
    corrupt), every stamp parses, and the epoch is non-empty (an empty
    epoch means the decision context was unknowable)."""
    if not isinstance(entry, dict):
        return False
    sha = entry.get("sha")
    epoch = entry.get("epoch")
    stage = entry.get("stage")
    kills = entry.get("kills")
    kills_at = entry.get("kills_at")
    at = parse_at(entry.get("at"))
    instants = [parse_at(k) for k in kills_at] if isinstance(kills_at, list) else []
    return (
        set(entry)
        == {
            "event_id",
            "sha",
            "epoch",
            "stage",
            "scope",
            "code",
            "reason",
            "at",
            "kills",
            "kills_at",
        }
        and isinstance(entry.get("event_id"), str)
        and 0 < len(entry["event_id"]) <= 1024
        and isinstance(sha, str)
        and len(sha) == 64
        and all(c in "0123456789abcdef" for c in sha)
        and isinstance(epoch, str)
        and len(epoch) == 64
        and all(c in "0123456789abcdef" for c in epoch)
        and isinstance(stage, str)
        and stage in CACHEABLE_KILL_STAGES
        and isinstance(entry.get("reason"), str)
        and len(entry["reason"]) <= _REASON_MAX_LEN
        and entry.get("scope") == "evidence"
        and isinstance(entry.get("code"), str)
        and entry.get("code") in EVIDENCE_KILL_CODES
        and at is not None
        and isinstance(kills_at, list)
        and 1 <= len(kills_at) <= _KILLS_AT_CAP
        and all(k is not None for k in instants)
        and at == max((k for k in instants if k is not None), default=None)
        and type(kills) is int
        and kills == len(kills_at)
    )


def fresh_kill_instants(entry: dict, current: datetime, ttl: timedelta) -> list[datetime]:
    """Parse an entry's per-kill stamps and keep only those individually
    inside the TTL window, deduped by INSTANT (mixed offsets must not
    double-count one kill), newest first. Shared by the read path, the
    record path, the prune, and the state merge so every consumer agrees
    on what evidence is still alive (codex r10)."""
    seen: set[datetime] = set()
    for raw in entry.get("kills_at") or []:
        instant = parse_at(raw)
        if instant is None:
            continue
        age = current - instant
        if age < timedelta(0) or age > ttl:
            continue
        seen.add(instant)
    return sorted(seen, reverse=True)


def entry_key(event_id, sha, epoch, stage, code):
    return hashlib.sha256(
        json.dumps([event_id, sha, epoch, stage, code], separators=(",", ":")).encode()
    ).hexdigest()


def should_skip(bot_state: Any, event_id: str, bundle: Any, *, now=None) -> str | None:
    """Pure lookup; changed evidence, policy or actual writer context reopens."""
    try:
        if not enabled() or not event_id:
            return None
        rows = _cache_view(bot_state)
        if not rows:
            return None
        sha, epoch = bundle_fingerprint(bundle, bot_state), decision_epoch()
        if not sha or not epoch:
            return None
        current = now or datetime.now(timezone.utc)
        ttl = timedelta(hours=ttl_hours())
        for code in sorted(EVIDENCE_KILL_CODES):
            key = entry_key(event_id, sha, epoch, "writer", code)
            entry = rows.get(key)
            if (
                not valid_entry(entry)
                or entry.get("event_id") != event_id
                or entry["sha"] != sha
                or entry["epoch"] != epoch
                or entry["code"] != code
            ):
                continue
            fresh = fresh_kill_instants(entry, current, ttl)
            if len(fresh) < min_kills():
                continue
            retry_after = fresh[min_kills() - 1] + ttl
            return (
                f"model-attributed evidence rejection ({code}) x{len(fresh)}; "
                f"unchanged inputs; reconsider after {retry_after.isoformat()} "
                "or use THEHEAT_NEGATIVE_CACHE_ENABLED=0"
            )
        return None
    except Exception:
        return None


def record_kill(
    bot_state: Any,
    event_id: str,
    sha: str,
    stage: str,
    reason: str,
    *,
    now: datetime | None = None,
    scope: str | None = None,
    code: str | None = None,
    epoch: str | None = None,
) -> None:
    """Remember one explicitly scoped writer evidence judgment.

    Each event/input/policy/code revision has its own bounded row. Only
    independently fresh judgments of that same revision accrue; the verdict
    remains attributed to the model. Missing metadata is never cacheable.
    """
    try:
        if not enabled() or not event_id or not sha:
            return
        if (
            stage not in CACHEABLE_KILL_STAGES
            or scope != "evidence"
            or code not in EVIDENCE_KILL_CODES
        ):
            return
        epoch = epoch or decision_epoch()
        if not epoch:
            return
        cache = _cache_dict(bot_state)
        key = entry_key(event_id, sha, epoch, stage, code)
        prior = cache.get(key)
        current = now or datetime.now(timezone.utc)
        ttl = timedelta(hours=ttl_hours())
        stage_norm = str(stage)[:_STAGE_MAX_LEN]
        stamps: list[datetime] = []
        # Different source judgments never pool toward one activation.
        # Retaining distinct revisions also avoids losing A's timestamps
        # when concurrent writers return input revisions A, B, then A.
        if (
            valid_entry(prior)
            and isinstance(prior, dict)
            and prior.get("sha") == sha
            and prior.get("epoch") == epoch
            and prior.get("stage") == stage_norm
            and prior.get("code") == code
        ):
            # Evidence must itself be FRESH — per kill, not per entry
            # (codex r2, generalized r10): each prior kill participates only
            # while individually inside the TTL. A rolling newest-stamp let
            # a chain of kills keep ancient evidence alive indefinitely.
            stamps = fresh_kill_instants(prior, current, ttl)
        stamps.insert(0, current)
        stamps.sort(reverse=True)
        del stamps[_KILLS_AT_CAP:]
        cache[key] = {
            "event_id": event_id,
            "sha": sha,
            "epoch": epoch,
            "stage": stage_norm,
            "scope": scope,
            "code": code,
            "reason": str(reason or "")[:_REASON_MAX_LEN],
            "at": stamps[0].isoformat(),
            "kills": len(stamps),
            "kills_at": [k.isoformat() for k in stamps],
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
            if valid_entry(entry) and key != entry_key(
                entry["event_id"], entry["sha"], entry["epoch"], entry["stage"], entry["code"]
            ):
                del cache[key]
                removed += 1
                continue
            at = (
                parse_at(entry.get("at"))
                if isinstance(entry, dict) and valid_entry(entry)
                else None
            )
            if at is None or (current - at) > ttl or (current - at) < timedelta(0):
                del cache[key]
                removed += 1
                continue
            # Trim individually-expired kill stamps (codex r10) so persisted
            # entries carry only live evidence; an entry whose stamps all
            # expired is dead even if its newest "at" survives clock skew.
            assert isinstance(entry, dict)  # valid_entry held above
            fresh = fresh_kill_instants(entry, current, ttl)
            if not fresh:
                del cache[key]
                removed += 1
                continue
            if len(fresh) != len(entry.get("kills_at") or []):
                entry["kills_at"] = [k.isoformat() for k in fresh]
                entry["kills"] = len(fresh)
                entry["at"] = fresh[0].isoformat()
        if len(cache) > NEGATIVE_CACHE_MAX_ENTRIES:
            # Sort by PARSED instant, not the raw string — mixed offsets
            # would otherwise evict a newer instant over an older one
            # (codex r2 P2). Everything here survived valid_entry above.
            def _instant(key: str) -> datetime:
                at = parse_at(cache[key].get("at"))
                return at if at is not None else datetime.min.replace(tzinfo=timezone.utc)

            oldest_first = sorted(cache.keys(), key=lambda key: (_instant(key), key))
            for key in oldest_first[: len(cache) - NEGATIVE_CACHE_MAX_ENTRIES]:
                del cache[key]
                removed += 1
        return removed
    except Exception as exc:  # noqa: BLE001
        print(f"[negative_cache] prune error (ignored): {exc!r}")
        return 0


def record_result(bot_state, event_id, bundle, result, *, now=None):
    """Shared queue/direct-dispatch accounting; record one actual verdict once."""
    if result.get("negative_cache_recorded") is True:
        return
    if result.get("cacheable") is not True or result.get("kill_scope") != "evidence":
        return
    sha = result.get("negative_cache_input_sha") or bundle_fingerprint(bundle, bot_state)
    epoch = result.get("negative_cache_epoch") or decision_epoch()
    record_kill(
        bot_state,
        event_id,
        sha,
        result.get("kill_stage"),
        result.get("kill_reason", ""),
        scope=result.get("kill_scope"),
        code=result.get("kill_code"),
        epoch=epoch,
        now=now,
    )
    result["negative_cache_recorded"] = True


def merge_entries(base: Any, nxt: Any, *, now=None) -> dict:
    """Union fresh verdict timestamps per input/policy/code revision.

    Validate both sides, deduplicate actual UTC instants, and choose equal-time
    descriptive metadata deterministically. TTL and the 200-row retention cap
    apply here too, so a stale state writer cannot revive expired verdicts.
    Evicted revisions lose their retry history and may be reconsidered early.
    """
    base_d = base if isinstance(base, dict) else {}
    nxt_d = nxt if isinstance(nxt, dict) else {}
    now = now or datetime.now(timezone.utc)
    ttl = timedelta(hours=ttl_hours())

    def _fresh(entry: Any) -> Any:
        """Validity AND freshness per side, BEFORE reconciliation: a stale
        kills=2 row max()'d into a fresh restarted kills=1 row would revive
        expired evidence with a fresh timestamp (codex r3 P1 — reproduced).
        Expired or future-stamped sides simply don't participate."""
        if not valid_entry(entry):
            return None
        at = parse_at(entry["at"])
        if at is None:
            return None
        age = now - at
        if age < timedelta(0) or age > ttl:
            return None
        return entry

    merged: dict = {}
    for event_id in set(base_d) | set(nxt_d):
        a = _fresh(base_d.get(event_id))
        b = _fresh(nxt_d.get(event_id))
        if a is not None and event_id != entry_key(
            a["event_id"], a["sha"], a["epoch"], a["stage"], a["code"]
        ):
            a = None
        if b is not None and event_id != entry_key(
            b["event_id"], b["sha"], b["epoch"], b["stage"], b["code"]
        ):
            b = None
        if a is None and b is None:
            continue
        if a is None or b is None:
            chosen = deepcopy(a if b is None else b)
            assert chosen is not None  # both-None handled above
            stamps = fresh_kill_instants(chosen, now, ttl)
        else:
            a_at, b_at = parse_at(a["at"]), parse_at(b["at"])
            assert a_at is not None and b_at is not None  # _fresh guarantees
            chosen = deepcopy(max((a, b), key=lambda row: (parse_at(row["at"]), row["reason"])))
            if (
                a.get("sha") == b.get("sha")
                and a.get("epoch") == b.get("epoch")
                and a.get("stage") == b.get("stage")
                and a.get("code") == b.get("code")
            ):
                stamps = sorted(
                    set(fresh_kill_instants(a, now, ttl)) | set(fresh_kill_instants(b, now, ttl)),
                    reverse=True,
                )
            else:
                stamps = fresh_kill_instants(chosen, now, ttl)
        if not stamps:
            continue  # every kill aged out — the entry is dead evidence
        del stamps[_KILLS_AT_CAP:]
        chosen["kills_at"] = [k.isoformat() for k in stamps]
        chosen["kills"] = len(stamps)
        chosen["at"] = stamps[0].isoformat()
        merged[event_id] = chosen
    if len(merged) > NEGATIVE_CACHE_MAX_ENTRIES:
        # Parsed-instant sort (codex r2 P2): raw ISO strings with mixed
        # offsets would evict newer instants over older ones.
        def _instant(key: str) -> datetime:
            at = parse_at(merged[key].get("at"))
            return at if at is not None else datetime.min.replace(tzinfo=timezone.utc)

        oldest_first = sorted(merged.keys(), key=lambda key: (_instant(key), key))
        for key in oldest_first[: len(merged) - NEGATIVE_CACHE_MAX_ENTRIES]:
            del merged[key]
    return merged
