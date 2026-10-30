"""Coverage and discrepancies that must be read before any reconciled total.

Joins the existing reconciliation report (archive attempts, parsed usage, a
named scenario, operator-supplied billing, identifier matches) with the
production operation joins retained in run history (W11 ``operation_costs``).
Each class stays separate: nothing is summed across classes, retries and
duplicate exports are reported as counts rather than charged twice, and the
presence of any discrepancy marks totals unreliable. No savings or all-in cost
statement is derived here; actual cost stays unknown.
"""
from __future__ import annotations

from typing import Any

MAX_RUNS = 20
MAX_ROWS_PER_RUN = 8


def _count(value: Any) -> int:
    return value if type(value) is int and 0 <= value <= 10**9 else 0


def operation_observations(state: Any) -> dict:
    """Aggregate retained operation joins without trusting free text; bounded."""
    runs = state.get("run_history") if isinstance(state, dict) else None
    by_spend: dict[str, int] = {}
    out: dict[str, Any] = {"source": "run_history_operation_costs", "operations": 0, "requests": 0, "interrupted": 0,
           "unknown_or_malformed": 0, "unpriced_requests": 0, "estimate_only_requests": 0,
           "truncated_operations": 0, "by_spend_class": by_spend, "invalid_rows": 0}
    for run in (runs if isinstance(runs, list) else [])[:MAX_RUNS]:
        rows = run.get("operation_costs") if isinstance(run, dict) else None
        for row in (rows if isinstance(rows, list) else [])[-MAX_ROWS_PER_RUN:]:
            requests = row.get("requests") if isinstance(row, dict) else None
            if not isinstance(row, dict) or row.get("schema_version") != 1 or not isinstance(requests, dict):
                out["invalid_rows"] += 1
                continue
            raw_outcomes = requests.get("by_outcome")
            outcomes: dict = raw_outcomes if isinstance(raw_outcomes, dict) else {}
            out["operations"] += 1
            out["requests"] += _count(requests.get("total"))
            out["interrupted"] += _count(requests.get("interrupted"))
            out["unknown_or_malformed"] += _count(outcomes.get("unknown")) + _count(outcomes.get("malformed"))
            out["unpriced_requests"] += _count(row.get("unpriced_requests"))
            out["estimate_only_requests"] += _count(row.get("estimate_only_requests"))
            out["truncated_operations"] += requests.get("truncated") is True
            spend = str(row["spend_class"]) if row.get("spend_class") in ("discovery", "selection") else "other"
            by_spend[spend] = by_spend.get(spend, 0) + _count(requests.get("total"))
    return out


def discrepancies(report: dict) -> list[dict]:
    """Ordered, fixed-code coverage gaps; each blocks a reliable total."""
    rows: list[dict] = []

    def add(code: str, count: int) -> None:
        if count:
            rows.append({"code": code, "count": count})

    sources = report["inputs"]["archives"]
    add("archive_not_complete", sum(1 for s in sources if s.get("status") != "complete"))
    identity = report["inputs"]["identity_reconciliation"]
    add("capture_identity_conflict", int(identity.get("status") != "consistent"))
    add("billing_file_rejected", len(report["inputs"]["rejected_billing_files"]))
    billing = report["supplied_billing"]
    add("billing_quarantined", len(billing["quarantined"]))
    add("duplicate_billing_documents_counted_once", billing["exact_duplicate_documents"])
    add("duplicate_billing_items_counted_once", billing["exact_duplicate_items"])
    rec = report["reconciliation"]
    add("billing_item_unmatched", len(rec["unmatched_billing_items"]))
    add("attempt_without_billing_item", len(rec["attempts_without_billing_item"]))
    add("conflicting_match", len(rec["conflicting_matches"]))
    add("token_totals_incomplete", int(report["observed"]["token_totals_status"] != "complete_for_retained_rows"))
    add("no_billing_evidence", int(not billing["documents"]))
    state = report.get("retained_state_summary") or {}
    observed = state.get("operation_observations") if isinstance(state, dict) else None
    if isinstance(observed, dict):
        add("production_interrupted_requests", _count(observed.get("interrupted")))
        add("production_unknown_or_malformed_requests", _count(observed.get("unknown_or_malformed")))
        add("production_unpriced_requests", _count(observed.get("unpriced_requests")))
        add("production_operation_rows_truncated", _count(observed.get("truncated_operations")))
    return rows


__all__ = ["discrepancies", "operation_observations"]
