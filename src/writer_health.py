"""Read retained operating evidence without requests, mutations or health claims.

Returned responses, saved output, source eligibility and completed checks are
separate observations. Missing evidence is never a pass or a billing diagnosis.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Any

from src.editorial.policy import valid_policy
from src.editorial.revisions import review_is_current
from src.two_bot.usage_observations import CONTRACT, summarize_observations

FRESHNESS = timedelta(hours=26)
WRITER_MODES = {"alerts", "both", "leaderboard"}
TERMINAL_RUNS = {"success", "partial_failure", "failed"}
STAGES = {
    "budget_exhausted": "recorded_budget_exception",
    "pipeline_error": "unclassified_pipeline_exception",
    "provider_preflight": "recorded_prerequisite_block",
    "safety": "required_safety_not_passed",
    "honesty_gate": "local_scientific_rule_rejection",
    "cross_signal": "local_scientific_rule_rejection",
    "evidence_contract": "source_contract_rejected",
    "critic": "critic_rejected",
}


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z") if value else None


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(CONTRACT["identifier_pattern"], value) is not None


def _rows(value: Any, limit: int, label: str, issues: Counter) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        issues[label + "_invalid_container"] += 1
        return []
    if len(value) > limit:
        issues[label + "_truncated_rows"] += len(value) - limit
    rows: dict[str, dict] = {}
    encodings: dict[str, str] = {}
    conflicts = set()
    for row in value[:limit]:
        if not isinstance(row, dict) or not _identifier(row.get("id")):
            issues[label + "_invalid_row"] += 1
            continue
        identity = row["id"]
        try:
            encoded = json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            issues[label + "_invalid_row"] += 1
            continue
        if identity in encodings and encoded != encodings[identity]:
            conflicts.add(identity)
        else:
            encodings[identity], rows[identity] = encoded, row
    issues[label + "_conflicting_ids"] += len(conflicts)
    return [row for identity, row in rows.items() if identity not in conflicts]


def summarize_writer_health(state: dict, *, now: datetime, current_source_sha256: str) -> dict:
    """A bounded diagnostic report, not publication authorization or complete health.

    No raw strings from source packets, provider errors or draft text are emitted.
    Exact run joins apply only to suppressions. Response and draft/run joins remain
    unavailable, even when their timestamps happen to be close.
    """
    if not isinstance(state, dict) or not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("invalid_report_input")
    if not isinstance(current_source_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", current_source_sha256):
        raise ValueError("invalid_source_manifest")
    now = now.astimezone(UTC)
    cutoff = now - FRESHNESS
    issues: Counter = Counter()
    runs = {}
    for row in _rows(state.get("run_history"), 20, "runs", issues):
        mode, status = row.get("mode"), row.get("status")
        if not isinstance(mode, str) or not isinstance(status, str):
            issues["runs_invalid_shape"] += 1
            continue
        if mode not in WRITER_MODES or status not in TERMINAL_RUNS:
            continue
        start, end = timestamp(row.get("started_at")), timestamp(row.get("ended_at"))
        if start is None or end is None or not start <= end <= now:
            issues["runs_invalid_interval"] += 1
            continue
        runs[row["id"]] = (row, start, end)

    ordered_runs = sorted(runs.values(), key=lambda item: item[2], reverse=True)
    inventory: dict = {}
    captured = None
    uncertain_runs = any(value for key, value in issues.items() if key.startswith("runs_"))
    if len(ordered_runs) > 1 and ordered_runs[0][2] == ordered_runs[1][2]:
        uncertain_runs = True
        issues["runtime_inventory_ambiguous"] += 1
    if ordered_runs and not uncertain_runs:
        row, start, end = ordered_runs[0]
        candidate_inventory = _object(row.get("runtime_inventory"))
        candidate_time = timestamp(candidate_inventory.get("captured_at"))
        if (type(candidate_inventory.get("schema_version")) is not int
                or candidate_inventory.get("schema_version") != 1
                or candidate_inventory.get("mode") != row.get("mode")
                or candidate_time is None or not start <= candidate_time <= end):
            issues["runtime_inventory_unavailable"] += 1
        else:
            inventory, captured = candidate_inventory, candidate_time
    models = _object(inventory.get("models"))
    provider, model = models.get("writer_provider"), models.get("writer")
    known_config = provider in ("anthropic", "google") and _identifier(model)
    credentials = _object(inventory.get("credentials_present"))
    blocked = []
    unknown = []
    for stage, key in (("writer", "anthropic" if provider == "anthropic" else "gemini"),
                       ("safety", "safety_gemini"), ("fact_check", "gemini")):
        value = credentials.get(key) if stage != "writer" or known_config else None
        if value is False:
            blocked.append(stage)
        elif value is not True:
            unknown.append(stage)
    runtime_status = "unobserved" if captured is None else "stale" if captured < cutoff else "recent"

    window = summarize_observations(state.get("llm_usage_observations"))
    conflicts = set(window["retained_conflicting_ids"])
    responses = []
    for row in window["observations"]:
        at = timestamp(row["observed_at"])
        if at is None or at > now:
            issues["response_invalid_time"] += 1
            continue
        if (known_config and row["id"] not in conflicts and row["stage"] == "writer"
                and row["provider"] == provider and row["requested_model"] == model):
            responses.append((at, row))
    responses.sort(key=lambda item: item[0], reverse=True)
    recent_responses = [row for at, row in responses if at >= cutoff]
    if not known_config:
        response_status = "configuration_unobserved"
    elif runtime_status != "recent":
        response_status = "configuration_stale"
    elif recent_responses:
        response_status = "recent_response"
    elif responses:
        response_status = "stale"
    elif conflicts:
        response_status = "conflicted_or_unobserved"
    elif window["invalid"]:
        response_status = "invalid_or_unobserved"
    else:
        response_status = "unobserved"

    policy = _object(inventory.get("editorial_policy"))
    policy_usable = (valid_policy(policy) and policy["source_sha256"] == current_source_sha256
                     and runtime_status == "recent"
                     and all(policy["models"][key] == models.get(key) for key in policy["models"])
                     and all(type(policy["flags"][key]) is type(_object(inventory.get("flags")).get(key))
                             and policy["flags"][key] == _object(inventory.get("flags")).get(key)
                             for key in ("critic_enabled", "critic_revise_enabled", "writer_samples"))
                     and policy["flags"]["safety_llm_enabled"] is credentials.get("safety_gemini"))
    output_counts: Counter = Counter()
    for draft in _rows(state.get("drafts"), 1024, "drafts", issues):
        at = timestamp(draft.get("created_at"))
        if at is None or at > now:
            issues["draft_invalid_time"] += 1
            continue
        if at < cutoff or not isinstance(draft.get("text"), str) or not draft["text"].strip():
            continue
        output_counts["recent_saved_outputs"] += 1
        binding = _object(draft.get("review_binding"))
        if not policy_usable:
            continue
        try:
            current = review_is_current(draft, policy=policy)
        except (ValueError, TypeError, OverflowError, RecursionError, AttributeError):
            current = False
            issues["draft_binding_invalid"] += 1
        if current:
            key = "bound_model_reviews" if binding.get("kind") == "model" else "bound_human_reviews"
            output_counts[key] += 1

    dispositions: dict[str, dict] = {}
    for row in _rows(state.get("suppressions"), 100, "suppressions", issues):
        run_id = row.get("run_id")
        matched = runs.get(run_id) if isinstance(run_id, str) else None
        at = timestamp(row.get("ts"))
        if matched is None:
            issues["suppression_run_unjoined"] += 1
            continue
        if at is None or not matched[1] <= at <= matched[2] or at > now:
            issues["suppression_invalid_time"] += 1
            continue
        if at < cutoff:
            continue
        recorded_stage = row.get("stage")
        code = STAGES.get(recorded_stage) if isinstance(recorded_stage, str) else None
        if recorded_stage == "writer":
            diagnostics = row.get("model_diagnostics")
            if diagnostics is not None and not isinstance(diagnostics, list):
                issues["writer_diagnostic_invalid"] += 1
            invalid = isinstance(diagnostics, list) and any(
                isinstance(d, dict) and d.get("stage") == "writer" for d in diagnostics[:20])
            code = "writer_output_invalid" if invalid else "writer_declined_origin_unknown"
        elif recorded_stage == "fact_check":
            verdict = _object(_object(row.get("rejected_candidate")).get("verdict"))
            origin = verdict.get("check_path")
            code = {"local_precheck": "local_factual_rejection", "required_checker": "required_checker_rejection"}.get(
                origin if isinstance(origin, str) else "", "factual_rejection_origin_unknown")
        if code:
            item = dispositions.setdefault(code, {"count": 0, "last_observed_at": None})
            item["count"] += 1
            observed = at.isoformat(timespec="microseconds").replace("+00:00", "Z")
            item["last_observed_at"] = max(item["last_observed_at"] or observed, observed)

    return {
        "schema_version": 1, "reported_at": _iso(now), "freshness_hours": 26,
        "runtime": {"status": runtime_status, "captured_at": _iso(captured),
                    "writer_configuration_known": known_config,
                    "writer_model_sha256": hashlib.sha256(model.encode()).hexdigest() if known_config and isinstance(model, str) else None,
                    "credential_presence_blocked_stages": blocked,
                    "credential_presence_unknown_stages": unknown,
                    "credential_validity": "unverified"},
        "provider_response": {"status": response_status, "recent_matching_responses": len(recent_responses),
                              "last_observed_at": _iso(responses[0][0]) if responses else None,
                              "response_to_run_or_draft_join": "unavailable",
                              "missing_or_invalid_usage_responses": sum(r["usage_status"] != "present" or bool(r["invalid_fields"]) for r in recent_responses),
                              "window_truncated": window["truncated"], "window_invalid": window["invalid"],
                              "conflicting_ids": len(conflicts)},
        "saved_output": {key: output_counts[key] for key in ("recent_saved_outputs", "bound_model_reviews", "bound_human_reviews")},
        "review_scope": "Exact content and recorded runtime policy; fact/critic only, no full check receipt set",
        "recorded_runtime_policy_matches_current_source": policy_usable,
        "recorded_dispositions": dispositions,
        "unavailable_context": {key: value for key, value in sorted(issues.items()) if value},
        "source_truth": "not_independently_certified", "required_check_receipts": "incomplete",
        "editorial_quality": "not_evaluated", "accounting_complete": False, "all_in_cost_usd": None,
        "scope": "Retained observations only; no absence-of-failure or overall-health certificate",
    }
