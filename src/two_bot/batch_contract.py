"""Pure immutable writer batch plans and result binding; no submit or approval.

Callers supply independently retained hashes, current context and UTC time.
Evidence readiness is structural, not a semantic truth or funding certificate.
The future durable collector must retain raw result bytes before parsing them.
"""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re

from src.commands.schema import utc_datetime
from src.editorial.policy import valid_policy
from src.editorial.revisions import fingerprint
from src.two_bot import writer
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import MemorySlice, StoryBundle

MAX_PLAN_BYTES = 2_000_000
MAX_RESULTS_BYTES = 3_000_000
MAX_RESULT_BYTES = 1_000_000
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}")
_SHA = re.compile(r"[0-9a-f]{64}")
_CONTEXT = {"bundle_sha256", "memory_sha256", "policy_sha256", "publication_epoch"}
_BINDING = {
    "schema_version",
    "job_id",
    "publication_epoch",
    "created_at",
    "useful_until",
    "minimum_window_seconds",
    "samples",
    "experiment_id",
    "bundle_sha256",
    "memory_sha256",
    "policy",
    "policy_sha256",
    "params_sha256",
}


class BatchContractError(ValueError):
    """Bounded code only; never include unpublished text or provider bodies."""


def _require(condition, code):
    if not condition:
        raise BatchContractError(code)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(value) -> bytes:
    fingerprint(value)  # refuses non-JSON types and non-string object keys
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def _parse(raw, limit):
    _require(type(raw) is bytes and len(raw) <= limit, "invalid_or_oversized_bytes")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    _json(value)
    return value


def _id(value):
    _require(isinstance(value, str) and _ID.fullmatch(value) is not None, "invalid_identifier")


def _sha(value):
    _require(isinstance(value, str) and _SHA.fullmatch(value) is not None, "invalid_sha256")


def _custom_id(binding, index):
    return "th_" + fingerprint({"binding": binding, "sample_index": index})[:60]


def _binding_valid(binding):
    _require(isinstance(binding, dict) and set(binding) == _BINDING, "invalid_plan_fields")
    _require(
        type(binding["schema_version"]) is int and binding["schema_version"] == 1,
        "unsupported_schema",
    )
    for field in ("job_id", "publication_epoch"):
        _id(binding[field])
    for field in ("bundle_sha256", "memory_sha256", "policy_sha256", "params_sha256"):
        _sha(binding[field])
    samples = binding["samples"]
    _require(type(samples) is int and 1 <= samples <= 3, "invalid_sample_count")
    if binding["experiment_id"] is not None:
        _id(binding["experiment_id"])
    _require(samples == 1 or binding["experiment_id"] is not None, "experiment_required")
    policy = binding["policy"]
    _require(
        valid_policy(policy) and fingerprint(policy) == binding["policy_sha256"], "invalid_policy"
    )
    _require(
        policy["models"]["writer_provider"] == "anthropic"
        and policy["models"]["writer"].startswith("claude-")
        and policy["flags"]["writer_samples"] == samples,
        "policy_route_mismatch",
    )
    window = binding["minimum_window_seconds"]
    _require(type(window) is int and 1 <= window <= 86400, "invalid_minimum_window")
    duration = (
        utc_datetime(binding["useful_until"]) - utc_datetime(binding["created_at"])
    ).total_seconds()
    _require(window < duration <= 7 * 86400, "insufficient_or_unbounded_window")


def prepare_batch_plan(
    bundle: StoryBundle,
    memory: MemorySlice,
    *,
    bundle_sha256: str,
    memory_sha256: str,
    policy: dict,
    job_id: str,
    publication_epoch: str,
    created_at: str,
    useful_until: str,
    minimum_window_seconds: int,
    urgent: bool = False,
    samples: int = 1,
    experiment_id: str | None = None,
) -> bytes:
    """Freeze one event's request slate; one sample unless explicitly experimental."""
    try:
        _require(type(urgent) is bool and not urgent, "urgent_input_not_batchable")
        _require(
            len(_json(bundle.to_dict())) <= MAX_PLAN_BYTES
            and len(_json(memory.to_dict())) <= MAX_PLAN_BYTES,
            "oversized_inputs",
        )
        _require(
            fingerprint(bundle.to_dict()) == bundle_sha256
            and fingerprint(memory.to_dict()) == memory_sha256,
            "input_identity_changed",
        )
        _require(
            bundle.signal_kind not in writer.OUT_OF_SCOPE_SIGNAL_KINDS
            and audit_story_bundle(bundle).prompt_ready,
            "evidence_not_ready",
        )
        _require(writer.WRITER_PROVIDER == "anthropic", "unsupported_batch_provider")
        params = writer.anthropic_writer_request(writer.build_writer_user_prompt(bundle, memory))
        _require(
            valid_policy(policy) and policy["models"]["writer"] == params["model"],
            "loaded_model_mismatch",
        )
        binding = {
            "schema_version": 1,
            "job_id": job_id,
            "publication_epoch": publication_epoch,
            "created_at": created_at,
            "useful_until": useful_until,
            "minimum_window_seconds": minimum_window_seconds,
            "samples": samples,
            "experiment_id": experiment_id,
            "bundle_sha256": bundle_sha256,
            "memory_sha256": memory_sha256,
            "policy": policy,
            "policy_sha256": fingerprint(policy),
            "params_sha256": fingerprint(params),
        }
        _binding_valid(binding)
        raw = _json(
            {
                **binding,
                "requests": [
                    {"custom_id": _custom_id(binding, i), "params": params} for i in range(samples)
                ],
            }
        )
        _require(len(raw) <= MAX_PLAN_BYTES, "oversized_plan")
        return raw
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        OverflowError,
    ):
        raise BatchContractError("invalid_batch_plan_inputs") from None


def _plan(plan_bytes, expected_plan_sha256):
    _sha(expected_plan_sha256)
    plan = _parse(plan_bytes, MAX_PLAN_BYTES)
    _require(
        _digest(plan_bytes) == expected_plan_sha256 and _json(plan) == plan_bytes,
        "changed_plan_bytes",
    )
    _require(isinstance(plan, dict) and set(plan) == _BINDING | {"requests"}, "invalid_plan_fields")
    binding = {key: value for key, value in plan.items() if key != "requests"}
    _binding_valid(binding)
    requests = plan["requests"]
    _require(
        isinstance(requests, list) and len(requests) == plan["samples"], "invalid_request_count"
    )
    for index, request in enumerate(requests):
        _require(
            isinstance(request, dict) and set(request) == {"custom_id", "params"},
            "invalid_request_fields",
        )
        params = request["params"]
        _require(
            isinstance(params, dict)
            and params.get("model") == plan["policy"]["models"]["writer"]
            and fingerprint(params) == plan["params_sha256"],
            "changed_request_params",
        )
        _require(request["custom_id"] == _custom_id(binding, index), "changed_custom_id")
    return plan


def validated_batch_plan(plan_bytes: bytes, *, expected_plan_sha256: str) -> dict:
    """Detached complete plan verified against its independently retained hash."""
    try:
        return _plan(plan_bytes, expected_plan_sha256)
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        OverflowError,
    ):
        raise BatchContractError("invalid_or_changed_batch_plan") from None


def batch_requests(plan_bytes: bytes, *, expected_plan_sha256: str) -> list[dict]:
    """Detached requests, verified against an independently retained plan hash."""
    return validated_batch_plan(plan_bytes, expected_plan_sha256=expected_plan_sha256)["requests"]


def _usage(message):
    value = message.get("usage")
    if value is None:
        return None, "missing"
    # Preserve the complete reported object, including cache-duration dimensions.
    # Never apply synchronous rates, sum unknown counters or invent zero charges.
    valid = isinstance(value, dict) and all(
        type(value.get(k)) is int and value[k] >= 0 for k in ("input_tokens", "output_tokens")
    )
    return value, "reported_unpriced" if valid else "invalid_unpriced"


def _result(raw, plan, blocked):
    value = _parse(raw, MAX_RESULT_BYTES)
    _require(
        isinstance(value, dict) and set(value) == {"custom_id", "result"}, "invalid_result_fields"
    )
    result = value["result"]
    _require(isinstance(result, dict), "invalid_result")
    kind = result.get("type")
    _require(kind in ("succeeded", "errored", "canceled", "expired"), "invalid_terminal_status")
    allowed = (
        {"type", "message"}
        if kind == "succeeded"
        else {"type", "error"}
        if kind == "errored"
        else {"type"}
    )
    _require(set(result) == allowed, "invalid_terminal_fields")
    row = {
        "custom_id": value["custom_id"],
        "provider_status": kind,
        "raw_sha256": _digest(raw),
        "message_id": None,
        "usage": None,
        "usage_status": "missing",
        "cost_usd": None,
        "blocked_reasons": list(blocked),
        "candidate": None,
        "eligible_for_checks": False,
        "publication_approved": False,
    }
    if kind != "succeeded":
        row["blocked_reasons"].append("provider_" + kind)
        if kind == "errored":
            _require(isinstance(result["error"], dict), "invalid_provider_error")
            row["provider_error_sha256"] = fingerprint(result["error"])
        return row
    message = result["message"]
    _require(isinstance(message, dict), "invalid_message")
    row["usage"], row["usage_status"] = _usage(message)
    message_id = message.get("id")
    if isinstance(message_id, str) and 0 < len(message_id) <= 200:
        row["message_id"] = message_id
    else:
        row["blocked_reasons"].append("invalid_message_id")
    if (
        message.get("type") != "message"
        or message.get("role") != "assistant"
        or message.get("model") != plan["policy"]["models"]["writer"]
    ):
        row["blocked_reasons"].append("message_identity_mismatch")
    if message.get("stop_reason") != "end_turn":
        row["blocked_reasons"].append("incomplete_or_refused_message")
    content = message.get("content")
    text = None
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and set(content[0]) <= {"type", "text", "citations"}
        and content[0].get("type") == "text"
        and isinstance(content[0].get("text"), str)
        and content[0].get("citations") in (None, [])
    ):
        text = content[0]["text"]
    else:
        row["blocked_reasons"].append("unsupported_content")
    if text is not None:
        try:
            parsed = writer._parse_writer_json(text)
            if parsed.tweet is None:
                row["blocked_reasons"].append("writer_kill")
            elif len(parsed.tweet) > writer.TWEET_MAX_LENGTH:
                row["blocked_reasons"].append("overlong_output")
            elif not row["blocked_reasons"]:
                row["candidate"] = asdict(parsed)
                row["eligible_for_checks"] = True
        except (ValueError, TypeError, KeyError):
            row["blocked_reasons"].append("invalid_writer_output")
    return row


def collect_batch_results(
    plan_bytes: bytes,
    results_bytes: bytes,
    *,
    expected_plan_sha256: str,
    current_context: dict,
    now: str,
) -> dict:
    """Validate a bounded JSONL result file, retaining usage for unusable text.

    This is a candidate contract only. Safety, factual, deterministic and critic
    checks remain pending, as do any human approval and spending authorization.
    A caller must retain raw bytes even when this function refuses the protocol.
    """
    try:
        plan = _plan(plan_bytes, expected_plan_sha256)
        _require(
            isinstance(current_context, dict) and set(current_context) == _CONTEXT,
            "invalid_current_context",
        )
        for key in _CONTEXT - {"publication_epoch"}:
            _sha(current_context[key])
        _id(current_context["publication_epoch"])
        stamp = utc_datetime(now)
        blocked = [
            "changed_" + key for key in sorted(_CONTEXT) if current_context[key] != plan[key]
        ]
        if stamp >= utc_datetime(plan["useful_until"]):
            blocked.append("expired")
        if stamp < utc_datetime(plan["created_at"]):
            blocked.append("clock_before_creation")
        _require(
            type(results_bytes) is bytes and len(results_bytes) <= MAX_RESULTS_BYTES,
            "invalid_or_oversized_results",
        )
        lines = results_bytes.splitlines()
        _require(len(lines) <= plan["samples"], "unexpected_result_count")
        expected = {request["custom_id"] for request in plan["requests"]}
        found = {}
        for raw in lines:
            row = _result(raw, plan, blocked)
            cid = row["custom_id"]
            _require(
                isinstance(cid, str) and cid in expected and cid not in found,
                "unknown_or_duplicate_result_id",
            )
            found[cid] = row
        missing = sorted(expected - set(found))
        if missing:
            blocked.append("incomplete_results")
            for row in found.values():
                row["blocked_reasons"].append("incomplete_results")
                row["candidate"] = None
                row["eligible_for_checks"] = False
        return {
            "schema_version": 1,
            "plan_sha256": expected_plan_sha256,
            "results_sha256": _digest(results_bytes),
            "missing_custom_ids": missing,
            "complete": not missing,
            "context_blocked_reasons": blocked,
            "rows": [found[r["custom_id"]] for r in plan["requests"] if r["custom_id"] in found],
            "required_checks_completed": False,
            "publication_approved": False,
            "cost_usd": None,
            "accounting_complete": False,
        }
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeError,
        RecursionError,
        OverflowError,
    ):
        raise BatchContractError("invalid_batch_results_or_context") from None
