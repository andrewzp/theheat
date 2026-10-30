"""Offline factual/editorial evaluation joined per production route (W15.5).

For one supplied saved state and window, each route (draft type) gets separate
columns: qualified source support, factual refusals by check stage, exact
copy/graphic identity of delivered posts, operational failures, retained cost
joins, optional supplied human comparisons and known historical
counterexamples. Columns are never combined into a score or ranking. A parser
or check pass is not a better model; injected-model fixtures measure plumbing
only; a known bad historical post is a negative example and never positive
gold. Absent optional evidence is reported as absent, not as a block.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.editorial.revisions import fingerprint
from src.evaluation.production_match import CHECK_STAGES, BUDGET_STAGES, hazard

SCHEMA = "theheat.route-evaluation/v1"
MAX_ROUTES = 64


def _at(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(UTC) if at.tzinfo else None


def _route(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text[:60] if text else "unknown"


def _empty() -> dict:
    return {"drafts": 0, "source_support": {"qualified": 0, "held": 0, "unrecorded": 0},
            "factual_refusals": {stage: 0 for stage in sorted(CHECK_STAGES)}, "writer_rejections": 0,
            "budget_exclusions": 0, "operational": {"post_errors": 0, "unknown_deliveries": 0, "pipeline_errors": 0},
            "delivered": [], "known_counterexamples": [], "human_comparison": "not_supplied"}


def evaluate(state: dict, *, window_start: datetime, window_end: datetime, cost_observations: dict | None = None,
             human_comparisons: dict | None = None, counterexample_text_sha256s: set[str] | None = None,
             execution: str = "retained_runtime") -> dict:
    if window_start.tzinfo is None or window_end.tzinfo is None or window_end < window_start:
        raise ValueError("window")
    if execution not in ("retained_runtime", "invented_fixture"):
        raise ValueError("execution")
    inside = lambda value: (lambda at: at is not None and window_start <= at <= window_end)(_at(value))  # noqa: E731
    routes: dict[str, dict] = {}
    raw = state.get("publish_ledger")
    ledger: dict[str, Any] = raw if isinstance(raw, dict) else {}
    bad = counterexample_text_sha256s or set()

    def route(name: str) -> dict:
        if name not in routes and len(routes) >= MAX_ROUTES:
            name = "other"
        return routes.setdefault(name, _empty())

    for draft in state.get("drafts", []) if isinstance(state.get("drafts"), list) else []:
        if not isinstance(draft, dict) or not inside(draft.get("created_at") or draft.get("posted_at")):
            continue
        row = route(_route(draft.get("type")))
        row["drafts"] += 1
        support = draft.get("automatic_source_hold")
        bundle = ((draft.get("review_context") or {}).get("two_bot") or {}).get("bundle")
        row["source_support"]["held" if support else "qualified" if isinstance(bundle, dict) else "unrecorded"] += 1
        if draft.get("post_error"):
            row["operational"]["post_errors"] += 1
        receipt = ledger.get(str(draft.get("event_id") or draft.get("id")))
        if isinstance(receipt, dict) and not receipt.get("tweet_id") and receipt.get("phase") not in (None, "not_sent"):
            row["operational"]["unknown_deliveries"] += 1
        if draft.get("status") == "posted" and draft.get("tweet_id"):
            text_sha = receipt.get("text_sha256") if isinstance(receipt, dict) else None
            media = draft.get("media_attachment")
            item = {"tweet_id": str(draft["tweet_id"]), "text_sha256": text_sha,
                    "graphic_sha256": fingerprint(media) if isinstance(media, dict) else None,
                    "identity": "recorded" if text_sha else "receipt_text_unrecorded"}
            row["delivered"].append(item)
            if text_sha and text_sha in bad:
                row["known_counterexamples"].append({"tweet_id": item["tweet_id"], "use": "negative_only"})
    for supp in state.get("suppressions", []) if isinstance(state.get("suppressions"), list) else []:
        if not isinstance(supp, dict) or not inside(supp.get("ts")):
            continue
        stage = str(supp.get("stage") or "")
        row = route(_route(supp.get("category") or hazard(supp.get("source")) or "unknown"))
        if stage in CHECK_STAGES:
            row["factual_refusals"][stage] += 1
        elif stage == "writer":
            row["writer_rejections"] += 1
        elif stage in BUDGET_STAGES:
            row["budget_exclusions"] += 1
        elif stage == "pipeline_error":
            row["operational"]["pipeline_errors"] += 1
    for name, supplied in (human_comparisons or {}).items():
        if name in routes and isinstance(supplied, dict):
            routes[name]["human_comparison"] = {"status": "supplied", "summary": supplied,
                                                "note": "Optional evidence-equivalent comparison; not a panel verdict."}
    for row in routes.values():
        row["delivered"] = row["delivered"][:50]
    return {"schema": SCHEMA, "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
            "execution": execution, "routes": dict(sorted(routes.items())),
            "cost": cost_observations if isinstance(cost_observations, dict) else {"status": "unavailable"},
            "limits": ["Columns are not combined into a score, rank or model preference.",
                       "Injected-model fixture runs prove plumbing only."
                       if execution == "invented_fixture" else "Retained runtime rows; model behaviour is not replayed.",
                       "Known historical counterexamples are negative-only and never positive gold.",
                       "Absent human comparison is not a negative result."]}


__all__ = ["SCHEMA", "evaluate"]
