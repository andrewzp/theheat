"""Real check requests and interpretation without transport or retry loops."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, cast

from src.editorial.revisions import fingerprint
from src.state_schema import BotState
from src.two_bot import critic, fact_check, pipeline
from src.two_bot.evidence_contract import audit_story_bundle
from src.two_bot.types import MemorySlice, RelatedSignal, StoryBundle
from src.voice import safety

MAX_OUTPUT_TOKENS = 4096


def retained_inputs(packet: dict) -> tuple[StoryBundle, MemorySlice, BotState]:
    """Reject constructor repair/default drift instead of inventing evidence."""
    value = deepcopy(packet["bundle"])
    if "related_signals" in value:
        value["related_signals"] = [RelatedSignal(**item) for item in value["related_signals"]]
    bundle = StoryBundle(**value)
    memory = MemorySlice(**deepcopy(packet["memory"]))
    if fingerprint(bundle.to_dict()) != fingerprint(packet["bundle"]) or fingerprint(
        memory.to_dict()
    ) != fingerprint(packet["memory"]):
        raise ValueError("retained_check_input_roundtrip_changed")
    state = deepcopy(packet["checker_state"])
    if not isinstance(state, dict) or fingerprint(state) != packet["checker_state_sha256"]:
        raise ValueError("retained_checker_state_changed")
    return bundle, memory, cast(BotState, state)


def prepare_request(packet: dict, stage: str) -> dict:
    bundle, memory, state = retained_inputs(packet)
    tweet = packet["candidate"]["tweet"]
    if stage == "deterministic":
        return dict(schema_version=1, stage=stage, check_set_sha256=fingerprint(packet))
    if stage == "safety":
        request = safety.prepare_request(tweet)
    elif stage == "fact_check":
        request = fact_check.prepare_request(tweet, bundle)
    elif stage == "critic":
        pending = critic._collect_pending_today(
            state, exclude_event_id=bundle.event_id, today=packet["check_date"]
        )
        request = critic.prepare_request(
            tweet, bundle, pending, memory.shipped_tweet_texts, allow_revise=False
        )
    else:
        raise ValueError("unknown_required_check")
    # This local lane explicitly binds its output bound into the request. The
    # existing synchronous defaults and runtime model settings remain unchanged.
    request["config"] = dict(request.get("config", {}), max_output_tokens=MAX_OUTPUT_TOKENS)
    if request["model"] != packet["policy"]["models"][stage]:
        raise ValueError("changed_check_model")
    return request


def deterministic_result(packet: dict) -> dict:
    bundle, _, state = retained_inputs(packet)
    tweet = packet["candidate"]["tweet"]
    failures: list[str] = []
    audit = audit_story_bundle(bundle)
    if not audit.prompt_ready:
        failures.extend(
            f"evidence:{issue.code}" for issue in audit.issues if issue.severity == "error"
        )
        if not failures:
            failures.append("evidence_not_ready")
    forbidden = pipeline._forbidden_claim_violation(tweet, bundle)
    if forbidden is not None:
        failures.append("forbidden_claim")
    if pipeline._cross_signal_violation(tweet, bundle) is not None:
        failures.append("unsupported_cross_signal_relation")
    for check in (
        safety.check_regex,
        safety.check_month_repetition,
        safety.check_truncated_temperature,
    ):
        passed, reason = check(tweet)
        if not passed:
            failures.append(reason or "local_safety_rejected")
    rejected = fact_check.local_rejection(tweet, [], bundle, state)
    if rejected is not None:
        failures.extend(rejected.failures)
    return dict(passed=not failures, failures=failures[:100], failure_count=len(failures))


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate_response_field")
        result[key] = value
    return result


def interpret_observation(packet: dict, stage: str, observation: dict, raw: bytes) -> dict:
    """Parse retained bytes with actual gates; unknown/malformed never passes."""
    outcome: dict[str, Any] = dict(execution_status="error", verdict=None, result={}, usage=None)
    if not observation["complete"] or (
        stage != "deterministic" and observation["http_status"] != 200
    ):
        return dict(
            outcome, execution_status="unavailable", result={"reason": "check_response_unavailable"}
        )
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        fingerprint(value)  # No NaN/infinity or malformed Unicode.
        if stage == "deterministic":
            if (
                not isinstance(value, dict)
                or set(value) != {"passed", "failures", "failure_count"}
                or type(value["passed"]) is not bool
                or not isinstance(value["failures"], list)
                or type(value["failure_count"]) is not int
                or value["passed"] != (value["failure_count"] == 0 and not value["failures"])
            ):
                raise ValueError("invalid_local_check_observation")
            return dict(
                outcome,
                execution_status="completed",
                verdict="pass" if value["passed"] else "reject",
                result=value,
            )
        if not isinstance(value, dict):
            raise ValueError("invalid_provider_envelope")
        if isinstance(value.get("usageMetadata"), dict):
            outcome["usage"] = value["usageMetadata"]
        feedback = value.get("promptFeedback", {})
        if not isinstance(feedback, dict) or feedback.get("blockReason") not in (
            None,
            "BLOCK_REASON_UNSPECIFIED",
        ):
            raise ValueError("blocked_provider_prompt")
        candidates = value.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError("expected_one_candidate")
        candidate = candidates[0]
        if (
            candidate.get("finishReason") != "STOP"
            or type(candidate.get("index", 0)) is not int
            or candidate.get("index", 0) != 0
        ):
            raise ValueError("incomplete_check_generation")
        ratings = candidate.get("safetyRatings", [])
        if not isinstance(ratings, list) or any(
            not isinstance(rating, dict) or ("blocked" in rating and rating["blocked"] is not False)
            for rating in ratings
        ):
            raise ValueError("blocked_provider_candidate")
        content = candidate["content"]
        parts = content["parts"]
        if content.get("role") != "model" or not isinstance(parts, list) or not parts:
            raise ValueError("invalid_check_content")
        text = ""
        for part in parts:
            if (
                not isinstance(part, dict)
                or set(part) - {"text", "thought", "thoughtSignature"}
                or not isinstance(part.get("text"), str)
                or ("thought" in part and type(part["thought"]) is not bool)
            ):
                raise ValueError("unsupported_check_part")
            if part.get("thought") is not True:
                text += part["text"]
        if not text.strip() or len(text.encode()) > 65_536:
            raise ValueError("invalid_check_text")
        _, _, state = retained_inputs(packet)
        tweet = packet["candidate"]["tweet"]
        if stage == "safety":
            allowed = safety.interpret_response(text) == "allow"
            result = dict(passed=allowed)
        elif stage == "fact_check":
            checked = fact_check.interpret_response(tweet, text, state)
            allowed, result = checked.passed, checked.to_dict()
        elif stage == "critic":
            reviewed = critic._parse_critic_result(text, allow_revise=False)
            allowed, result = reviewed.passed, reviewed.to_dict()
        else:
            raise ValueError("unknown_required_check")
        return dict(
            outcome,
            execution_status="completed",
            verdict="pass" if allowed else "reject",
            result=result,
        )
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        # Keep provider bytes privately in the observation, not in diagnostics.
        return dict(outcome, result={"reason": "invalid_check_response"})
