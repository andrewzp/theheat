"""Per-call LLM usage ledger (economics master plan P0.6 — ledger MVP).

Records every paid provider call's token usage in a small in-process buffer
and folds it into ``state["llm_usage"]`` at cycle end — a day-keyed aggregate
(day → "stage|model" → counters + est. $), pruned to the newest
``LLM_USAGE_RETENTION_DAYS`` days so the gist state stays tiny (state-size
watch #390: 45 days × ~2 stage-model keys ≈ single-digit KB). The prune is
enforced BOTH here and in the state merge strategy (``_merge_llm_usage``) —
a drain-side prune alone would be resurrected by the merge overlay on write.

Scope: the ledger accounts for PRODUCTION-cycle spend — runs that write
state. Dryruns and voice-regression replays deliberately never write state,
so their paid calls are visible in the Console and workflow logs, not here;
the buffer cap bounds their memory. This is a design choice, not a leak.

Why: every cost number in this repo's comments has drifted stale ("$6/month",
"~5,700 tokens", "$25–45/mo" — all measured wrong on 2026-07-13). The ledger
makes spend a *measured* dashboard fact. Estimates are directional — the
Console is the invoice; unknown models record tokens with usd=0.0 because an
honest "unknown" beats a fabricated price.
"""

from __future__ import annotations

import math
import threading
from datetime import datetime, timezone
from typing import Any

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

# Token clamp: negative counts (corrupt provider payloads) price as 0, and an
# absurdly large count must not overflow the usd float into Infinity — not
# strict JSON, it would poison the whole state write (codex P2). 1e12 tokens
# is ~5 orders of magnitude past any real response.
_TOKEN_CLAMP = 10**12


def _clamp_tokens(raw: object) -> int:
    try:
        value = int(raw or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
    return max(0, min(value, _TOKEN_CLAMP))


def _price_for(model: str) -> tuple[float, float, float, float]:
    for prefix, prices in _PRICES_PER_MTOK.items():
        # Boundary-aware: "claude-sonnet-4-6" and its dated variants
        # ("claude-sonnet-4-6-20250929") match; "claude-sonnet-4-60" is a
        # DIFFERENT (unknown) model and must price at $0 (codex P2).
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
) -> None:
    """Buffer one provider call's usage. Thread-safe (writer samples run in a
    ThreadPoolExecutor). Never raises — the ledger must not take down a call
    that already succeeded."""
    try:
        row = {
            "day": datetime.now(timezone.utc).date().isoformat(),
            "stage": str(stage),
            "model": str(model),
            "in": _clamp_tokens(input_tokens),
            "cached_in": _clamp_tokens(cache_read_tokens),
            "cache_write": _clamp_tokens(cache_write_tokens),
            "out": _clamp_tokens(output_tokens),
            "usd": estimate_usd(
                str(model),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
            ),
        }
        with _LEDGER_LOCK:
            _BUFFER.append(row)
            if len(_BUFFER) > _BUFFER_CAP:
                del _BUFFER[: len(_BUFFER) - _BUFFER_CAP]
    except Exception as exc:  # noqa: BLE001 — never break a successful call
        print(f"[usage_ledger] record error (ignored): {exc!r}")


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
            state["llm_usage"] = ledger
        for row in rows:
            day_bucket = ledger.get(row["day"])
            if not isinstance(day_bucket, dict):
                day_bucket = {}
                ledger[row["day"]] = day_bucket
            key = f"{row['stage']}|{row['model']}"
            agg = _valid_agg(day_bucket.get(key))
            day_bucket[key] = agg
            agg["calls"] += 1
            for field in _AGG_INT_FIELDS:
                agg[field] += row[field]
            agg["usd"] = round(agg["usd"] + row["usd"], 6)
        for day in sorted(ledger.keys())[:-LLM_USAGE_RETENTION_DAYS]:
            del ledger[day]
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — never break the state save
        print(f"[usage_ledger] drain error (rows re-buffered): {exc!r}")
        with _LEDGER_LOCK:
            _BUFFER[:0] = rows
            if len(_BUFFER) > _BUFFER_CAP:
                del _BUFFER[: len(_BUFFER) - _BUFFER_CAP]
        return 0
