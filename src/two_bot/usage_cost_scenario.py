"""A dated token-price scenario for retained usage, never an invoice or allowance.

Read-only projection; no I/O, account-tier inference or historical-ledger rewriting.
GenerateContent field semantics follow the pinned google-genai 2.25.0 SDK.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import re
from typing import Any

from src.two_bot.usage_observations import CONTRACT, canonical, valid_record

SCENARIO = "google-standard-paid-2026-10-02"
# Integer nano-USD per token. Output includes candidate AND thought tokens.
# The dated 3.8 promotion ends 2026-12-31. This snapshot never becomes a live price.
_RATES: dict[str, list[tuple[int | None, int, int, int]]] = {
    "gemini-2.5-flash": [(None, 300, 30, 2500)],
    "gemini-2.5-pro": [(200000, 1250, 125, 10000), (None, 2500, 250, 15000)],
    "gemini-3.8-flash": [(None, 750, 75, 3750)],
}
_STAGES = {
    "writer",
    "fact_check",
    "critic",
    "safety",
    "newsworthiness_verify",
    "newsworthiness_search",
}
_COUNTS = (
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "total_token_count",
)
_WINDOW_KEYS = {"schema_version", "observations", "truncated", "invalid"}
_LIMITATIONS = [
    "standard_paid_token_scenario_only_not_actual_billing",
    "account_tier_and_actual_charges_unknown",
    "fixed_2026_10_02_rates_not_live_or_historical_invoice_prices",
    "excludes_tool_grounding_cache_storage_taxes_discounts_other_tiers",
    "excludes_other_providers_and_unpriced_or_uncaptured_responses",
    "retained_window_never_proves_complete_account_coverage",
    "not_a_monthly_forecast_spending_cap_or_savings_measurement",
]

# Shared with the dashboard through scripts/gen_usage_cost_contract.py.
CONTRACT_COST: dict[str, Any] = {
    "schema_version": 2,
    "identity_semantics": "validated_integer_fields_v2",
    "scenario": SCENARIO,
    "rates": _RATES,
    "stages": sorted(_STAGES),
    "required_counts": list(_COUNTS),
    "limitations": _LIMITATIONS,
    "pricing": {
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
        "verified_on": "2026-10-02",
        "rates_sha256": hashlib.sha256(canonical(_RATES).encode()).hexdigest(),
        "interpretation": "fixed_standard_paid_text_token_scenario",
    },
}


def _semantic_record(value: Any) -> Any:
    """Version 2: normalize validated integer fields, never mutate stored evidence.

    JSON number spellings (1/1.0/-0) have the same identity here. Other values are
    left untouched for strict validation. The byte bound applies to this semantic
    representation; this intentionally replaces v1's serialization identity.
    """
    if not isinstance(value, dict):
        return value
    # Do not traverse arbitrary malformed nesting just to normalize known fields.
    row = dict(value)

    def integer(raw):
        return (
            int(raw)
            if type(raw) in (int, float) and 0 <= raw <= CONTRACT["count_limit"] and raw == int(raw)
            else raw
        )

    if "schema_version" in row:
        row["schema_version"] = integer(row["schema_version"])
    if isinstance(row.get("counts"), dict) and len(row["counts"]) <= 9:
        row["counts"] = {key: integer(raw) for key, raw in row["counts"].items()}
    if isinstance(row.get("breakdowns"), dict) and len(row["breakdowns"]) <= 4:
        row["breakdowns"] = {
            key: [
                {**item, "token_count": integer(item["token_count"])}
                if isinstance(item, dict) and "token_count" in item
                else item
                for item in items
            ]
            if isinstance(items, list) and len(items) <= CONTRACT["modality_limit"]
            else items
            for key, items in row["breakdowns"].items()
        }
    return row


def _money(nanodollars: int) -> str:
    return f"{nanodollars // 10**9}.{nanodollars % 10**9:09d}"


def _text_breakdown(value: Any, count: int | None, *, required: bool = False) -> bool:
    if value is None:
        return not required
    return (
        count is not None
        and all(item["modality"] == "TEXT" for item in value)
        and sum(int(item["token_count"]) for item in value) == count
    )


def _eligible(row: dict) -> tuple[list[str], dict | None]:
    """Validate the quantities before calculating even a partial token subtotal."""
    if row["provider"] != "google":
        return ["other_provider"], None
    if row["usage_status"] != "present" or row["invalid_fields"] or row["unsupported_fields"]:
        return ["incomplete_or_unsupported_capture"], None
    model = row["resolved_model"]
    if model not in _RATES:
        return ["unpriced_resolved_model"], None
    counts = row["counts"]
    if any(counts[name] is None for name in _COUNTS):
        return ["missing_required_count"], None
    prompt, candidate, thought, total = (int(counts[name]) for name in _COUNTS)
    tool = counts["tool_use_prompt_token_count"]
    reasons = []
    if tool is None:
        if total != prompt + candidate + thought:
            return ["unexplained_total"], None
        tool = 0
        reasons.append("zero_tool_tokens_derived_from_total")
    elif total != prompt + candidate + thought + int(tool):
        return ["inconsistent_total"], None
    if tool:
        return ["tool_input_not_priced"], None
    cache = counts["cached_content_token_count"]
    if cache is not None and cache > prompt:
        return ["cache_exceeds_prompt"], None
    details = row["breakdowns"]
    if not all(
        (
            _text_breakdown(details["prompt_tokens_details"], prompt, required=True),
            _text_breakdown(details["candidates_tokens_details"], candidate),
            _text_breakdown(details["cache_tokens_details"], None if cache is None else int(cache)),
            _text_breakdown(details["tool_use_prompt_tokens_details"], int(tool)),
        )
    ):
        return ["unsupported_or_inconsistent_modality"], None
    if cache is None:
        cache_min, cache_max = 0, prompt
        reasons.append("cache_count_unknown_interval")
    else:
        cache_min = cache_max = int(cache)
    _, incoming, cached, outgoing = next(
        rate for rate in _RATES[model] if rate[0] is None or prompt <= rate[0]
    )
    minimum = (
        (prompt - cache_max) * incoming + cache_max * cached + (candidate + thought) * outgoing
    )
    maximum = (
        (prompt - cache_min) * incoming + cache_min * cached + (candidate + thought) * outgoing
    )
    return reasons, {
        "min": minimum,
        "max": maximum,
        "tokens": {"prompt": prompt, "candidate": candidate, "thought": thought},
    }


def _safe_record(value: Any) -> bool:
    try:
        return valid_record(value)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        return False


def _summary(rows: list[dict]) -> dict:
    eligible = [row for row in rows if row["disposition"] == "eligible"]
    return {
        "unique_valid_records": len(rows),
        "eligible_records": len(eligible),
        "excluded_records": len(rows) - len(eligible),
        "conflicting_records": sum(row["disposition"] == "conflict" for row in rows),
        "non_google_records": sum(row["provider"] != "google" for row in rows),
        "eligible_token_subtotal_usd": None
        if not eligible
        else {
            "min": _money(sum(row["_amount"]["min"] for row in eligible)),
            "max": _money(sum(row["_amount"]["max"] for row in eligible)),
        },
        "eligible_tokens": None
        if not eligible
        else {
            field: sum(row["_amount"]["tokens"][field] for row in eligible)
            for field in ("prompt", "candidate", "thought")
        },
    }


def project_usage_cost(window: Any, *, scenario: str) -> dict:
    """Project at most 32 observations; missing or conflicting usage never costs zero.

    Raises fixed ValueErrors for an absent/malformed envelope or unknown scenario.
    Invalid rows remain counted. Semantic duplicates are removed, but competing local
    or provider response identities are all excluded from monetary aggregation.
    """
    if scenario != SCENARIO:
        raise ValueError("unsupported_cost_scenario")
    if window is None:
        raise ValueError("usage_window_unavailable")
    if (
        not isinstance(window, dict)
        or set(window) != _WINDOW_KEYS
        or type(window["schema_version"]) not in (int, float)
        or window["schema_version"] != 1
        or type(window["truncated"]) is not bool
        or type(window["invalid"]) is not bool
        or not isinstance(window["observations"], list)
        or len(window["observations"]) > CONTRACT["limit"]
    ):
        raise ValueError("invalid_usage_window")
    unique: dict[str, dict] = {}
    invalid_ids: set[str] = set()
    invalid_response_ids: set[tuple[str, str]] = set()
    invalid = duplicates = 0
    for row in window["observations"]:
        row = _semantic_record(row)
        if not _safe_record(row):
            invalid += 1
            # Malformed competing evidence must not make its valid twin billable.
            if isinstance(row, dict):
                identity, response, provider = (
                    row.get("id"),
                    row.get("response_id"),
                    row.get("provider"),
                )
                if isinstance(identity, str) and re.fullmatch(r"[a-f0-9]{32}", identity):
                    invalid_ids.add(identity)
                if (
                    provider in ("google", "anthropic", "unknown")
                    and isinstance(response, str)
                    and re.fullmatch(CONTRACT["identifier_pattern"], response)
                ):
                    invalid_response_ids.add((provider, response))
            continue
        key = canonical(row)
        if key in unique:
            duplicates += 1
        else:
            unique[key] = row
    ids = Counter(row["id"] for row in unique.values())
    response_ids = Counter(
        (row["provider"], row["response_id"])
        for row in unique.values()
        if row["response_id"] is not None
    )
    rows: list[dict] = []
    for _, row in sorted(unique.items()):
        conflict = (
            ids[row["id"]] > 1
            or row["id"] in invalid_ids
            or (
                row["response_id"] is not None
                and (
                    response_ids[(row["provider"], row["response_id"])] > 1
                    or (row["provider"], row["response_id"]) in invalid_response_ids
                )
            )
        )
        reasons, amount = (
            (["conflicting_observation_identity"], None) if conflict else _eligible(row)
        )
        rows.append(
            {
                "observation_id": row["id"],
                "provider": row["provider"],
                "stage": row["stage"] if row["stage"] in _STAGES else "unknown",
                "model": row["resolved_model"]
                if row["provider"] == "google" and row["resolved_model"] in _RATES
                else "unknown",
                "disposition": "conflict"
                if conflict
                else "eligible"
                if amount is not None
                else "excluded",
                "reasons": reasons,
                "_amount": amount,
            }
        )
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["stage"], row["model"])].append(row)
    report = {
        "schema_version": CONTRACT_COST["schema_version"],
        "identity_semantics": CONTRACT_COST["identity_semantics"],
        "scenario": SCENARIO,
        "pricing": dict(CONTRACT_COST["pricing"]),
        "actual_cost_known": False,
        "complete_account_coverage": False,
        "window_truncated": window["truncated"],
        "window_invalid": window["invalid"] or invalid > 0,
        "input_records": len(window["observations"]),
        "invalid_records": invalid,
        "exact_duplicates": duplicates,
        "observation_period": {
            "first": min(row["observed_at"] for row in unique.values()),
            "last": max(row["observed_at"] for row in unique.values()),
        }
        if unique
        else None,
        **_summary(rows),
        "groups": [
            {"stage": stage, "model": model, **_summary(group)}
            for (stage, model), group in sorted(groups.items())
        ],
        "limitations": list(_LIMITATIONS),
        "rows": [
            {k: v for k, v in row.items() if k != "_amount"}
            | {
                "token_component_usd": None
                if row["_amount"] is None
                else {
                    "min": _money(row["_amount"]["min"]),
                    "max": _money(row["_amount"]["max"]),
                }
            }
            for row in rows
        ],
    }
    return report
