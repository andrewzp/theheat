"""Read retained estimates without treating missing accounting as free usage."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from src.two_bot.usage_ledger import _COVERAGE_FIELDS, _is_valid_day_key, coverage_fields_valid
from src.two_bot.usage_coverage import count as valid_count, evidence_inconsistent

INSTRUMENTED_STAGES = ['writer', 'fact_check', 'critic', 'safety', 'newsworthiness_search', 'newsworthiness_verify']
UNTRACKED_STAGES = ['workflow_agents', 'other_account_usage']
SCOPE = 'Instrumented writer, checker, critic, safety and news responses in state-writing runs; table estimates, not account totals or invoices.'
LIMITS = [
    "Instrumented stages describe this code version, not proof that retained runs captured every call; historical usage is not backfilled.",
    "Workflow agents, other account usage and non-state-writing evaluations remain untracked; no budget enforcement is implemented here.",
    "Pre-response failures, late source threads and failed persistence can leave usage untracked; a recorded response is not proof of billing.",
    "The shared buffer retains 500 responses; new stage traffic can evict earlier writer responses before a drain.",
    "Google thought/tool/modality/tier and grounding charges are not priced or fully represented; Google responses remain unpriced.",
    "The ledger retains 45 day buckets. MAX cumulative merges can undercount concurrent writers and cannot prove zero spending on missing days.",
    "Coverage keeps up to 32 original cumulative snapshots per day/model; conflicts or overflow make the subtotal unknown.",
    "The unchanged price table was last documented as checked on 2026-07-13; historical values are never repriced by this reader."
]


def _money(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def summarize_usage(state, *, now=None) -> dict:
    """Paired with dashboard/lib/usage-ledger.js; never mutate the ledger."""
    now = now or datetime.now(timezone.utc)
    prefix, today = now.strftime("%Y-%m-"), now.date().isoformat()
    ledger = state.get("llm_usage") if hasattr(state, "get") else None
    recorded = priced = legacy_usd = 0.0
    calls = priced_calls = unpriced_calls = missing_usage = legacy_calls = 0
    row_count = legacy_rows = inconsistent = excluded = 0
    for day, bucket in (ledger.items() if isinstance(ledger, dict) else []):
        if not _is_valid_day_key(day) or not day.startswith(prefix) or day > today:
            continue
        if not isinstance(bucket, dict):
            excluded += 1
            continue
        for agg in bucket.values():
            if not isinstance(agg, dict) or not _money(agg.get("usd")):
                excluded += 1
                continue
            row_count += 1
            recorded += agg["usd"]
            count = agg.get("calls")
            if not valid_count(count) or evidence_inconsistent(agg):
                inconsistent += 1
                continue
            count = int(agg["calls"])
            calls += count
            if not any(field in agg for field in _COVERAGE_FIELDS):
                legacy_rows += 1
                legacy_calls += count
                legacy_usd += agg["usd"]
                continue
            if (agg.get("cost_coverage_invalid") or not coverage_fields_valid(agg)
                or agg["priced_calls"] + agg["unpriced_calls"] > count
                or agg["missing_usage_calls"] > agg["unpriced_calls"]
                or agg["priced_usd"] > agg["usd"] + 0.000001
                or (agg["priced_calls"] == 0 and agg["priced_usd"] > 0)):
                inconsistent += 1
                continue
            priced += agg["priced_usd"]
            priced_calls += agg["priced_calls"]
            unpriced_calls += agg["unpriced_calls"]
            missing_usage += agg["missing_usage_calls"]
            old_calls = count - agg["priced_calls"] - agg["unpriced_calls"]
            legacy_calls += old_calls
            old_usd = max(0.0, agg["usd"] - agg["priced_usd"])
            legacy_usd += old_usd
            legacy_rows += int(old_calls > 0 or old_usd > 0)
    if not all(_money(value) for value in (recorded, priced, legacy_usd)) or calls > 2**53 - 1:
        inconsistent += 1
    available = row_count > 0 and inconsistent == 0
    has_estimate = available and (priced_calls > 0 or legacy_usd > 0)
    pricing = ("inconsistent" if inconsistent else "unavailable" if not row_count
               else "partial" if unpriced_calls or excluded or legacy_rows else "priced")
    return {
        "coverage": "inconsistent" if inconsistent else "partial" if row_count else "unavailable",
        "pricing_coverage": pricing, "known_cost_usd": round(priced, 6) if available and priced_calls else None,
        "legacy_estimate_usd": round(legacy_usd, 6) if available and legacy_rows else None,
        "recorded_estimate_usd": round(recorded, 6) if has_estimate else None,
        "recorded_calls": calls if available else None,
        "priced_calls": priced_calls if available else None,
        "unpriced_calls": unpriced_calls if available else None,
        "missing_usage_calls": missing_usage if available else None,
        "legacy_calls": legacy_calls if available else None,
        "legacy_rows": legacy_rows, "inconsistent_rows": inconsistent, "excluded_rows": excluded,
        "instrumented_stages": list(INSTRUMENTED_STAGES), "untracked_stages": list(UNTRACKED_STAGES), "scope": SCOPE, "limitations": list(LIMITS),
        "budget_enforced": False,
    }
