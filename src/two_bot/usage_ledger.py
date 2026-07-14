"""Per-call LLM usage ledger (economics master plan P0.6 — ledger MVP).

Records every paid provider call's token usage in a small in-process buffer
and folds it into ``state["llm_usage"]`` at cycle end — a day-keyed aggregate
(day → "stage|model" → counters + est. $), pruned to the newest
``LLM_USAGE_RETENTION_DAYS`` days so the gist state stays tiny (state-size
watch #390: 45 days × ~2 stage-model keys ≈ single-digit KB).

Why: every cost number in this repo's comments has drifted stale ("$6/month",
"~5,700 tokens", "$25–45/mo" — all measured wrong on 2026-07-13). The ledger
makes spend a *measured* dashboard fact. Estimates are directional — the
Console is the invoice; unknown models record tokens with usd=0.0 because an
honest "unknown" beats a fabricated price.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

# $/MTok (input, output, cache_write, cache_read) — verified live 2026-07-13
# against the Anthropic pricing page. Prefix-matched so date-suffixed model
# ids resolve.
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


def _price_for(model: str) -> tuple[float, float, float, float]:
    for prefix, prices in _PRICES_PER_MTOK.items():
        if model.startswith(prefix):
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
    return (
        input_tokens * in_p
        + output_tokens * out_p
        + cache_write_tokens * cw_p
        + cache_read_tokens * cr_p
    ) / 1_000_000


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
            "in": int(input_tokens or 0),
            "cached_in": int(cache_read_tokens or 0),
            "cache_write": int(cache_write_tokens or 0),
            "out": int(output_tokens or 0),
            "usd": estimate_usd(
                str(model),
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cache_write_tokens=int(cache_write_tokens or 0),
                cache_read_tokens=int(cache_read_tokens or 0),
            ),
        }
        with _LEDGER_LOCK:
            _BUFFER.append(row)
            if len(_BUFFER) > _BUFFER_CAP:
                del _BUFFER[: len(_BUFFER) - _BUFFER_CAP]
    except Exception as exc:  # noqa: BLE001 — never break a successful call
        print(f"[usage_ledger] record error (ignored): {exc!r}")


def drain_into_state(state: Any) -> int:
    """Fold all buffered rows into ``state['llm_usage']`` and clear the
    buffer. Returns the number of rows drained. Never raises."""
    try:
        with _LEDGER_LOCK:
            rows = list(_BUFFER)
            _BUFFER.clear()
        if not rows:
            return 0
        ledger = state.setdefault("llm_usage", {})
        for row in rows:
            day_bucket = ledger.setdefault(row["day"], {})
            key = f"{row['stage']}|{row['model']}"
            agg = day_bucket.setdefault(
                key,
                {"calls": 0, "in": 0, "cached_in": 0, "cache_write": 0, "out": 0, "usd": 0.0},
            )
            agg["calls"] += 1
            agg["in"] += row["in"]
            agg["cached_in"] += row["cached_in"]
            agg["cache_write"] += row["cache_write"]
            agg["out"] += row["out"]
            agg["usd"] = round(agg["usd"] + row["usd"], 6)
        for day in sorted(ledger.keys())[:-LLM_USAGE_RETENTION_DAYS]:
            del ledger[day]
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — never break the state save
        print(f"[usage_ledger] drain error (ignored): {exc!r}")
        return 0
