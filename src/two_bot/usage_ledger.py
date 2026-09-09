"""Retained model-response usage and table estimates, with explicit gaps.

Writer, checker, critic, safety and news response sites feed a shared bounded
in-process buffer. State-writing runs drain day/stage/model aggregates.
Dryruns, replays, late responses and other account usage may never be persisted.
The buffer retains at most 500 responses; the ledger retains 45 day buckets.
Each bucket/model retains at most 32 compact cumulative coverage witnesses,
so contradictory snapshots cannot be hidden by later MAX merges. Overflow
makes coverage unknown; these bounds are not account-level accounting.

Legacy usd/token/call fields remain historical estimates. New priced/unpriced
counters identify unknown prices and absent metadata. No enforcement or invoice
reconciliation happens here, and a recorded response does not prove billing.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
import threading
from datetime import date, datetime, timezone
from typing import Any

from src.two_bot.usage_coverage import (
    COVERAGE_COUNTS as _COVERAGE_COUNT_FIELDS, COVERAGE_FIELDS as _COVERAGE_FIELDS,
    SNAPSHOTS, count as valid_count, money, coverage_evidence, coverage_fields_valid, union_evidence,
)

# $/MTok (input, output, cache_write, cache_read) — verified live 2026-07-13
# against the Anthropic pricing page. Boundary-aware prefix match (below) so
# date-suffixed ids resolve without capturing different models.
_PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}

_LEDGER_LOCK = threading.Lock()
_BUFFER: list[dict[str, Any]] = []
# Backstop for paths that never drain (voice-regression replays call
# write_tweet directly, with no bot_state): keep only the newest rows.
_BUFFER_CAP = 500

LLM_USAGE_RETENTION_DAYS = 45

_AGG_INT_FIELDS = ("in", "cached_in", "cache_write", "out")

# Ledger day keys must be REAL calendar dates, not merely date-shaped: a
# lexicographic prune over unvalidated keys would let 45 high-sorting junk
# keys ("z00"..., or shape-valid "9999-99-00") evict today's real bucket
# while the drain reports success (codex r2/r3 P2). The regex is a cheap
# prefilter; date.fromisoformat is the canonical validator.
_DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_day_key(day: object) -> bool:
    if not (isinstance(day, str) and _DAY_KEY_RE.match(day)):
        return False
    try:
        date.fromisoformat(day)
    except ValueError:
        return False
    return True

# Token clamp: negative counts (corrupt provider payloads) price as 0, and an
# absurdly large count must not overflow the usd float into Infinity — not
# strict JSON, it would poison the whole state write (codex P2). 1e12 tokens
# is ~5 orders of magnitude past any real response.
_TOKEN_CLAMP = 10**12


def _clamp_tokens(raw: object) -> int:
    try:
        value = int(raw or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(value, _TOKEN_CLAMP))


def _price_for(model: str) -> tuple[float, float, float, float]:
    for prefix, prices in _PRICES_PER_MTOK.items():
        # Boundary-aware: "claude-sonnet-4-6" and its dated variants
        # ("claude-sonnet-4-6-20250929") match; "claude-sonnet-4-60" is a
        # DIFFERENT (unknown) model. Its zero placeholder is never a known price.
        if model == prefix or model.startswith(prefix + "-") or model.startswith(prefix + "@"):
            return prices
    return (0.0, 0.0, 0.0, 0.0)


def estimate_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Legacy numeric calculator; zero can mean unknown. Consult coverage counters."""
    in_p, out_p, cw_p, cr_p = _price_for(model)
    usd = (
        _clamp_tokens(input_tokens) * in_p
        + _clamp_tokens(output_tokens) * out_p
        + _clamp_tokens(cache_write_tokens) * cw_p
        + _clamp_tokens(cache_read_tokens) * cr_p
    ) / 1_000_000
    return usd if math.isfinite(usd) else 0.0


def record_usage(
    stage: str,
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    usage_complete: bool = True,
    pricing_supported: bool = True,
) -> None:
    """Buffer one provider call's usage. Thread-safe (writer samples run in a
    ThreadPoolExecutor). Never raises — the ledger must not take down a call
    that already succeeded."""
    try:
        quantities = (input_tokens, output_tokens, cache_write_tokens, cache_read_tokens)
        complete = usage_complete is True and all(type(value) is int and 0 <= value <= _TOKEN_CLAMP for value in quantities)
        priced = complete and pricing_supported is True and any(_price_for(str(model)))
        usd = estimate_usd(str(model), input_tokens=input_tokens, output_tokens=output_tokens,
                           cache_write_tokens=cache_write_tokens, cache_read_tokens=cache_read_tokens) if priced else 0.0
        row = {
            "day": datetime.now(timezone.utc).date().isoformat(),
            "stage": str(stage),
            "model": str(model),
            "in": _clamp_tokens(input_tokens),
            "cached_in": _clamp_tokens(cache_read_tokens),
            "cache_write": _clamp_tokens(cache_write_tokens),
            "out": _clamp_tokens(output_tokens),
            "usd": usd, "priced_usd": usd,
            "priced_calls": int(priced), "unpriced_calls": int(not priced),
            "missing_usage_calls": int(not complete),
        }
        with _LEDGER_LOCK:
            _BUFFER.append(row)
            if len(_BUFFER) > _BUFFER_CAP:
                del _BUFFER[: len(_BUFFER) - _BUFFER_CAP]
    except Exception as exc:  # noqa: BLE001 — never break a successful call
        print(f"[usage_ledger] record error (ignored): {exc!r}")


def record_response(stage: str, response: Any, model: str, provider: str) -> None:
    """Observe one returned response without changing provider/output behavior.

    Capture precedes text parsing, outside transport retries. A missing or
    raising metadata object records one unpriced response; pre-response errors
    do not invent a response. Google token semantics and tool charges are not
    priced by the Anthropic-only table, even for a coincident model name.
    """
    values: dict[str, Any] = {}
    complete = False
    try:
        if provider in {"anthropic", "google"}:
            usage = getattr(response, "usage" if provider == "anthropic" else "usage_metadata", None)
            if usage is not None:
                def optional_count(field):
                    value = getattr(usage, field, None)
                    return 0 if value is None else value

                if provider == "anthropic":
                    values = {"input_tokens": getattr(usage, "input_tokens", None),
                              "output_tokens": getattr(usage, "output_tokens", None),
                              "cache_write_tokens": optional_count("cache_creation_input_tokens"),
                              "cache_read_tokens": optional_count("cache_read_input_tokens")}
                else:
                    values = {"input_tokens": getattr(usage, "prompt_token_count", None),
                              "output_tokens": getattr(usage, "candidates_token_count", None),
                              "cache_read_tokens": optional_count("cached_content_token_count")}
                complete = True
    except Exception:  # Metadata access cannot turn a returned response into a retry.
        values = {}
    try:
        record_usage(stage, model, usage_complete=complete,
                     pricing_supported=provider == "anthropic", **values)
    except Exception:  # Accounting failure must neither retry nor change stage disposition.
        pass


def record_writer_response(response: Any, model: str, provider: str) -> None:
    """Compatibility entry point for the two existing writer capture sites."""
    record_response("writer", response, model, provider)


def _valid_agg(raw: Any) -> dict:
    """Return a well-formed aggregate dict, repairing corruption in place."""
    if not isinstance(raw, dict):
        raw = {}
    agg = raw
    for field in _AGG_INT_FIELDS + ("calls",):
        agg[field] = _clamp_tokens(agg.get(field, 0))
    try:
        usd = float(agg.get("usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        usd = 0.0
    agg["usd"] = usd if math.isfinite(usd) else 0.0
    return agg


def drain_into_state(state: Any) -> int:
    """Fold all buffered rows into ``state['llm_usage']`` and clear the
    buffer. Returns the number of rows drained. Never raises; on an
    unexpected fold failure the rows are RE-BUFFERED so a later drain can
    persist them (codex P1: don't destroy the only copy before folding)."""
    with _LEDGER_LOCK:
        rows = list(_BUFFER)
        _BUFFER.clear()
    if not rows:
        return 0
    try:
        # Validate before folding: a corrupted gist can hand us None / a
        # list / a string here. Reset rather than crash — losing corrupt
        # history is better than blocking every subsequent write_state.
        ledger = state.get("llm_usage") if hasattr(state, "get") else None
        if not isinstance(ledger, dict):
            if ledger is not None:
                print(
                    f"[usage_ledger] llm_usage was {type(ledger).__name__}; "
                    f"resetting to a fresh ledger"
                )
            ledger = {}
        # Work on a copy: shallow callers can share DEFAULT_STATE nested maps.
        ledger = deepcopy(ledger)
        previous_evidence: dict[tuple[str, str], dict] = {}
        for row in rows:
            day_bucket = ledger.get(row["day"])
            if not isinstance(day_bucket, dict):
                day_bucket = {}
                ledger[row["day"]] = day_bucket
            key = f"{row['stage']}|{row['model']}"
            identity = (row["day"], key)
            if identity not in previous_evidence:
                raw = day_bucket.get(key)
                previous_evidence[identity] = coverage_evidence(raw if isinstance(raw, dict) else {})
            agg = _valid_agg(day_bucket.get(key))
            day_bucket[key] = agg
            agg["calls"] += 1
            for field in _AGG_INT_FIELDS:
                agg[field] += row[field]
            agg["usd"] = round(agg["usd"] + row["usd"], 6)
            if any(field in agg for field in _COVERAGE_FIELDS) and not coverage_fields_valid(agg):
                agg["cost_coverage_invalid"] = True
            for field in _COVERAGE_COUNT_FIELDS:
                value = agg.get(field, 0)
                # Preserve contradictory/corrupt evidence rather than silently
                # turning it into a reassuring coverage count.
                if valid_count(value):
                    agg[field] = int(value) + row[field]
                else:
                    agg[field] = row[field]  # Invalid flag remains; this is not verified coverage.
            value = agg.get("priced_usd", 0.0)
            if money(value):
                agg["priced_usd"] = round(value + row["priced_usd"], 6)
            else:
                agg["priced_usd"] = row["priced_usd"]
        for (day, key), previous in previous_evidence.items():
            agg = ledger[day][key]
            # This drain is an original cumulative snapshot. Keep old evidence
            # alongside it; a new response cannot reconcile old contradictions.
            fresh = coverage_evidence({field: value for field, value in agg.items() if field != SNAPSHOTS})
            agg.update(union_evidence(previous, fresh))
        for day in list(ledger.keys()):
            if not _is_valid_day_key(day):
                print(f"[usage_ledger] dropping corrupt day key {day!r}")
                del ledger[day]
        for day in sorted(ledger.keys())[:-LLM_USAGE_RETENTION_DAYS]:
            del ledger[day]
        # Commit only after the whole fold succeeds; a retry must not replay
        # earlier rows on top of a partially mutated state.
        state["llm_usage"] = ledger
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — never break the state save
        print(f"[usage_ledger] drain error (rows re-buffered): {exc!r}")
        with _LEDGER_LOCK:
            _BUFFER[:0] = rows
            if len(_BUFFER) > _BUFFER_CAP:
                del _BUFFER[: len(_BUFFER) - _BUFFER_CAP]
        return 0
