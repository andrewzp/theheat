"""Provider usage read from verified private request archives; never billing.

Consumes ``request_archive_replay.load_archive`` (read API v1) and the existing
``retained_usage.extract`` parser, unchanged. Every SDK call, physical attempt
and returned response stays a separate denominator. No response, malformed
response, missing usage, unknown send outcome and a rejected editorial answer
are different outcomes. Missing usage is never zero; no window is applied, so
every call in the supplied archives is listed and nothing more is implied.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

from src.two_bot import retained_usage
from src.two_bot.request_archive import SCHEMA_V2, strict_json_loads
from src.two_bot.request_archive_replay import CallRecord, RouteRecord, VerifiedArchive, WireAttempt
from src.two_bot.usage_cost_scenario import SCENARIO as GOOGLE_SCENARIO, project_usage_cost
from src.two_bot.usage_observations import CONTRACT, valid_record

SCHEMA = "theheat.archive-usage/v1"


def _observed_at(value: Any) -> str | None:
    try:
        moment = datetime.fromisoformat(value).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _record_time(archive: VerifiedArchive, call: int, attempt: int, kind: str) -> str | None:
    for record in archive.records:
        data = record["data"]
        if record["type"] == kind and data.get("call") == call and data.get("attempt") == attempt:
            return record["at"]
    return None


def _generation_seq(archive: VerifiedArchive, seq: int) -> int | None:
    return max((item["seq"] for item in archive.inputs if item["seq"] < seq), default=None)


def _outcome_key(archive: VerifiedArchive, seq: int, binding: dict) -> tuple:
    return (_generation_seq(archive, seq), *(binding.get(key) for key in (
        "event_id", "bundle_sha256", "candidate_text_sha256", "candidate_attempt")))


def _candidate_outcomes(archive: VerifiedArchive) -> dict[tuple, dict[str, str]]:
    outcomes: dict[tuple, dict[str, str]] = {}
    for item in archive.stage_outcomes:
        identity = _outcome_key(archive, item["seq"], item.get("binding") or {})
        outcomes.setdefault(identity, {})[str(item.get("stage"))] = str(item.get("outcome"))
    return outcomes


def _attempt_row(archive: VerifiedArchive, call: CallRecord, attempt: WireAttempt,
                 outcomes: dict) -> dict:
    sent_at = _record_time(archive, call.number, attempt.attempt, "wire_request")
    received_at = _record_time(archive, call.number, attempt.attempt, "wire_response")
    response = attempt.response
    row: dict[str, Any] = {
        "scope_id": archive.scope_id, "call": call.number, "attempt": attempt.attempt,
        "stage": call.stage, "provider": call.provider, "requested_model": call.model,
        "event_id": call.binding.get("event_id"), "bundle_sha256": call.binding.get("bundle_sha256"),
        "candidate_text_sha256": call.binding.get("candidate_text_sha256"),
        "candidate_attempt": call.binding.get("candidate_attempt"), "phase": call.binding.get("phase"),
        "request_sha256": attempt.request.artifact, "response_sha256": response.artifact,
        "http_status": attempt.status, "provider_ids": dict(attempt.provider_ids),
        "sent_at": sent_at, "response_recorded_at": received_at,
        "candidate_stage_outcome": outcomes.get(_outcome_key(archive, call.intent_seq, call.binding), {}).get(call.stage),
    }
    if response.availability == "not_observed":
        row.update(outcome="no_response_observed", send_outcome="unknown", usage_status="unknown")
        return row
    if response.availability != "captured" or response.artifact is None:
        row.update(outcome=f"response_{response.availability}", send_outcome="unknown", usage_status="unknown")
        return row
    raw = archive.artifact(response.artifact)
    extracted = retained_usage.extract(raw, provider=call.provider, stage=call.stage, model=call.model,
                                       observed_at=_observed_at(received_at), complete=True)
    row.update(outcome="http_error_response" if (attempt.status or 0) >= 400 else "response_returned",
               send_outcome="response_received", usage_status=extracted["status"],
               usage_reason=extracted["reason"], parser_version=extracted["parser_version"],
               resolved_model=extracted["resolved_model"], counts=extracted["counts"],
               labels=extracted["labels"], breakdowns=extracted["breakdowns"],
               invalid_fields=extracted["invalid_fields"], unsupported_fields=extracted["unsupported_fields"])
    row["observation"] = _observation(row)
    return row


def _observation(row: dict) -> dict | None:
    """The existing persisted observation shape, built only from verified bytes."""
    if row["usage_status"] not in ("present", "absent", "invalid"):
        return None
    identity = hashlib.sha256(f"{row['scope_id']}:{row['call']}:{row['attempt']}".encode()).hexdigest()[:32]
    response_id = (row["provider_ids"].get("response_body_id") or row["provider_ids"].get("response_body_responseId"))
    candidate = {"schema_version": 1, "id": identity, "observed_at": _observed_at(row["response_recorded_at"]),
                 "stage": row["stage"], "provider": row["provider"], "requested_model": row["requested_model"],
                 "resolved_model": row["resolved_model"], "response_id": response_id,
                 "usage_status": row["usage_status"], "counts": row["counts"], "labels": row["labels"],
                 "breakdowns": row["breakdowns"], "invalid_fields": row["invalid_fields"],
                 "unsupported_fields": row["unsupported_fields"]}
    return candidate if valid_record(candidate) else None


def _call_row(call: CallRecord) -> dict:
    result = call.result or {}
    return {"call": call.number, "stage": call.stage, "provider": call.provider, "requested_model": call.model,
            "outcome": call.outcome, "physical_attempts": len(call.attempts),
            "provider_outcome": result.get("provider_outcome", "returned" if call.outcome == "returned" else None),
            "exception_type": result.get("exception_type"), "archival": result.get("archival"),
            "candidate_text_sha256": call.binding.get("candidate_text_sha256")}


# Route families (schema v2): what each operation is, and is NOT, evidence of.
ROUTE_ROLES = {"batch_submit": "batch_submission_acknowledgment", "batch_metadata": "batch_status_read",
               "batch_results": "batch_results_read", "command_check": "command_check_generation"}


def _route_time(archive: VerifiedArchive, route: int, kind: str) -> str | None:
    for record in archive.records:
        if record["type"] == kind and record["data"].get("route") == route:
            return record["at"]
    return None


def _route_row(archive: VerifiedArchive, route: RouteRecord) -> dict:
    binding = {key: entry.get("value") for key, entry in route.binding.items()}
    row: dict[str, Any] = {
        "scope_id": archive.scope_id, "route": route.number, "family": route.family,
        "role": ROUTE_ROLES[route.family], "provider": route.provider, "outcome": route.outcome,
        "archival": (route.result or {}).get("archival"), "physical_send_observed": route.sent,
        "http_status": route.status, "entity": route.response.availability, "entity_complete": route.complete,
        "provider_batch_id": route.response_observed.get("provider_batch_id") or binding.get("provider_batch_id"),
        "stage": binding.get("stage"), "requested_model": binding.get("model"), "billing": "unknown"}
    if route.family == "batch_submit":
        ids = (route.request_observed.get("custom_ids") or {}).get("values")
        # An acknowledgment names a batch; it is never completion or billable-token evidence.
        row.update(model_generation=False, submitted_requests=len(ids) if isinstance(ids, list) else None,
                   usage_status="not_in_acknowledgment", completion_evidence="none")
    elif route.family == "batch_metadata":
        row.update(model_generation=False, usage_status="not_applicable",
                   processing_status=route.response_observed.get("processing_status"))
    elif route.family == "batch_results":
        row.update(model_generation=False, usage_status="per_result_line")
    elif route.response.availability != "captured" or route.response.artifact is None or not route.complete:
        row.update(model_generation=True, send_outcome="unknown" if route.sent else "not_sent",
                   usage_status="unknown")
    else:
        extracted = retained_usage.extract(
            archive.artifact(route.response.artifact), provider=route.provider, stage=binding.get("stage"),
            model=binding.get("model"), observed_at=_observed_at(_route_time(archive, route.number, "route_response")),
            complete=True)
        row.update(model_generation=True, send_outcome="response_received", usage_status=extracted["status"],
                   usage_reason=extracted["reason"], resolved_model=extracted["resolved_model"],
                   counts=extracted["counts"], invalid_fields=extracted["invalid_fields"])
    return row


def _result_line_rows(archive: VerifiedArchive, route: RouteRecord, seen: set) -> list[dict]:
    """Usage per retained result line, counted once per (provider batch, custom ID)."""
    if route.family != "batch_results" or route.response.availability != "captured" or route.response.artifact is None:
        return []
    batch = route.expected_path.split("/")[4]
    observed_at = _observed_at(_route_time(archive, route.number, "route_response"))
    lines = archive.artifact(route.response.artifact).split(b"\n")
    tail = lines.pop()
    if tail and route.complete:
        lines.append(tail)
    rows = []
    for index, line in enumerate(lines, start=1):
        base = {"scope_id": archive.scope_id, "route": route.number, "line": index, "provider_batch_id": batch,
                "stage": "writer", "stage_source": "batch_plan_writer_lane", "billing": "unknown"}
        try:
            value = strict_json_loads(line, allow_floats=True)
            custom = value.get("custom_id")
            result = value.get("result") or {}
            kind = result.get("type")
            if type(custom) is not str or kind not in ("succeeded", "errored", "canceled", "expired"):
                raise ValueError("result_shape")
        except (ValueError, UnicodeError, AttributeError):
            rows.append({**base, "custom_id": None, "result_type": None, "counted": False,
                         "usage_status": "invalid_line"})
            continue
        key = (batch, custom)
        duplicate = key in seen
        seen.add(key)
        row = {**base, "custom_id": custom, "result_type": kind, "counted": not duplicate and kind == "succeeded"}
        if duplicate:
            row["usage_status"] = "duplicate_not_counted"
        elif kind != "succeeded" or not isinstance(result.get("message"), dict):
            row["usage_status"] = "not_applicable_result_type"
        else:
            message = result["message"]
            # Derived from the parsed result line, never labeled as a raw provider entity.
            extracted = retained_usage.extract(json.dumps(message, sort_keys=True).encode(), provider="anthropic",
                                               stage="writer", model=message.get("model"), observed_at=observed_at,
                                               complete=True)
            row.update(usage_status=extracted["status"], usage_source="parsed_results_line_message",
                       resolved_model=extracted["resolved_model"], counts=extracted["counts"],
                       invalid_fields=extracted["invalid_fields"])
        rows.append(row)
    return rows


def _route_usage(archives: list[VerifiedArchive]) -> dict:
    routes: list[dict] = []
    lines: list[dict] = []
    seen: set = set()
    for archive in archives:
        if archive.status == "invalid" or archive.schema != SCHEMA_V2:
            continue
        for route in archive.routes:
            routes.append(_route_row(archive, route))
            lines.extend(_result_line_rows(archive, route, seen))
    totals: dict[tuple, dict] = {}
    for row in [*routes, *lines]:
        if row.get("usage_status") != "present" or row.get("invalid_fields") or row.get("counted") is False:
            continue
        key = (row["provider"] if "provider" in row else "anthropic", row.get("stage") or "unknown",
               row.get("resolved_model") or row.get("requested_model") or "unknown", row.get("family", "batch_results"))
        group = totals.setdefault(key, {"provider": key[0], "stage": key[1], "model": key[2], "family": key[3],
                                        "responses": 0, "counts": {}, "missing_counts": {}})
        group["responses"] += 1
        for name, value in (row.get("counts") or {}).items():
            bucket = "counts" if type(value) is int else "missing_counts"
            group[bucket][name] = group[bucket].get(name, 0) + (value if type(value) is int else 1)
    denominators = {
        "route_operations": len(routes),
        "physical_route_sends": sum(1 for r in routes if r["physical_send_observed"]),
        "batch_submissions": sum(1 for r in routes if r["family"] == "batch_submit"),
        "batch_status_reads": sum(1 for r in routes if r["family"] == "batch_metadata"),
        "batch_results_reads": sum(1 for r in routes if r["family"] == "batch_results"),
        "command_check_operations": sum(1 for r in routes if r["family"] == "command_check"),
        "model_generations_with_observed_response": sum(1 for r in routes if r["family"] == "command_check"
                                                        and r.get("send_outcome") == "response_received"),
        "result_lines": len(lines), "result_lines_counted": sum(1 for r in lines if r["counted"]),
        "result_lines_duplicate_not_counted": sum(1 for r in lines if r["usage_status"] == "duplicate_not_counted"),
        "result_lines_invalid": sum(1 for r in lines if r["usage_status"] == "invalid_line"),
        "incomplete_route_entities": sum(1 for r in routes if r["entity_complete"] is False),
    }
    return {"routes": routes, "route_result_lines": lines, "route_denominators": denominators,
            "route_token_totals": [totals[key] for key in sorted(totals)]}


def archive_usage(archives: list[VerifiedArchive]) -> dict:
    """Every call/attempt/response of every supplied verified archive.

    An ``invalid`` archive contributes no rows and is listed as rejected; an
    ``incomplete`` one contributes its verified records and stays labeled.
    Identical provider IDs on different responses are conflicts, never merged.
    """
    rows: list[dict] = []
    calls: list[dict] = []
    sources: list[dict] = []
    for archive in archives:
        sources.append({"scope_id": archive.scope_id, "manifest_sha256": archive.manifest_sha256,
                        "status": archive.status, "problems": list(archive.problems),
                        "used": archive.status != "invalid"})
        if archive.status == "invalid":
            continue
        outcomes = _candidate_outcomes(archive)
        for call in archive.calls:
            calls.append({"scope_id": archive.scope_id, **_call_row(call)})
            for attempt in call.attempts:
                rows.append(_attempt_row(archive, call, attempt, outcomes))
    ids = Counter((row["provider"], role, value) for row in rows for role, value in row["provider_ids"].items())
    for row in rows:
        row["provider_id_conflict"] = any(ids[(row["provider"], role, value)] > 1
                                          for role, value in row["provider_ids"].items())
    denominators = {
        "sdk_calls": len(calls),
        "refused_or_raised_before_send": sum(1 for c in calls if c["physical_attempts"] == 0),
        "physical_attempts": len(rows),
        "responses_received": sum(1 for r in rows if r["send_outcome"] == "response_received"),
        "unknown_send_outcomes": sum(1 for r in rows if r["send_outcome"] == "unknown"),
        "responses_with_present_usage": sum(1 for r in rows if r["usage_status"] == "present"),
        "responses_with_absent_usage": sum(1 for r in rows if r["usage_status"] == "absent"),
        "responses_with_invalid_usage": sum(1 for r in rows if r["usage_status"] == "invalid"),
        "http_error_responses": sum(1 for r in rows if r["outcome"] == "http_error_response"),
        "rejected_answers_with_usage": sum(1 for r in rows if r["candidate_stage_outcome"] == "kill"
                                           and r["usage_status"] == "present"),
        "provider_id_conflicts": sum(1 for r in rows if r["provider_id_conflict"]),
    }
    result = {"schema": SCHEMA, "sources": sources, "calls": calls, "attempts": rows,
              "denominators": denominators, "token_totals": _token_totals(rows),
              "billing": "unknown", "complete_account_coverage": False,
              "scope": "Only calls retained in the supplied archives; not an account or invoice total."}
    if any(archive.schema == SCHEMA_V2 and archive.status != "invalid" for archive in archives):
        # Route families appear only for explicit v2 archives; v1-only output is unchanged.
        result.update(_route_usage(archives))
    return result


def _token_totals(rows: list[dict]) -> list[dict]:
    """Sum present, valid, non-conflicting counts only; missing stays missing."""
    groups: dict[tuple, dict] = {}
    for row in rows:
        if row["usage_status"] != "present" or row["invalid_fields"] or row["provider_id_conflict"]:
            continue
        key = (row["provider"], row["stage"], row["resolved_model"] or row["requested_model"] or "unknown")
        group = groups.setdefault(key, {"provider": key[0], "stage": key[1], "model": key[2], "responses": 0,
                                        "counts": {name: 0 for name in CONTRACT["counts"][key[0]]},
                                        "missing_counts": {name: 0 for name in CONTRACT["counts"][key[0]]}})
        group["responses"] += 1
        for name, value in row["counts"].items():
            if type(value) is int:
                group["counts"][name] += value
            else:
                group["missing_counts"][name] += 1
    return [groups[key] for key in sorted(groups)]


def priced_scenario(usage: dict, scenario: str) -> dict:
    """Apply ONE explicitly named existing scenario row by row, unchanged.

    Only Google responses with valid observations are eligible; everything else
    is listed as excluded with a reason. Amounts are decimal strings, with the
    projection's own min/max interval kept, never a billed amount.
    """
    if scenario != GOOGLE_SCENARIO:
        raise ValueError("unsupported_cost_scenario")
    rows = []
    total_min = total_max = Decimal(0)
    eligible = 0
    for row in usage["attempts"]:
        base = {"scope_id": row["scope_id"], "call": row["call"], "attempt": row["attempt"],
                "provider": row["provider"], "stage": row["stage"]}
        observation = row.get("observation")
        if row["provider"] != "google":
            rows.append({**base, "disposition": "excluded", "reasons": ["no_named_scenario_for_provider"]})
            continue
        if observation is None:
            rows.append({**base, "disposition": "excluded", "reasons": [f"usage_{row['usage_status']}"]})
            continue
        if row["provider_id_conflict"]:
            rows.append({**base, "disposition": "conflict", "reasons": ["conflicting_provider_identity"]})
            continue
        report = project_usage_cost({"schema_version": 1, "observations": [observation], "truncated": False,
                                     "invalid": False}, scenario=scenario)
        projected = report["rows"][0]
        amount = projected["token_component_usd"]
        if amount is None:
            rows.append({**base, "disposition": projected["disposition"], "reasons": projected["reasons"]})
            continue
        eligible += 1
        total_min += Decimal(amount["min"])
        total_max += Decimal(amount["max"])
        rows.append({**base, "disposition": "eligible", "reasons": projected["reasons"],
                     "token_component_usd": amount})
    for row in usage.get("routes", []) + usage.get("route_result_lines", []):
        rows.append({"scope_id": row["scope_id"], "route": row["route"], "line": row.get("line"),
                     "family": row.get("family", "batch_results"), "disposition": "excluded",
                     "reasons": ["route_family_not_in_named_scenario"]})
    return {"scenario": scenario, "currency": "USD", "eligible_rows": eligible,
            "excluded_rows": len(rows) - eligible, "rows": rows,
            "token_component_usd": {"min": str(total_min), "max": str(total_max)} if eligible else None,
            "limitations": project_usage_cost({"schema_version": 1, "observations": [], "truncated": False,
                                               "invalid": False}, scenario=scenario)["limitations"],
            "actual_cost_known": False, "billed_amount": None}
