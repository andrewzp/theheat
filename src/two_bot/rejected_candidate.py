"""Bounded private context for selected rejections, never approval."""

import json
from typing import Any

from src.editorial.revisions import fingerprint, text_hash
from src.two_bot.bundle_capture import BundleCapture, BundleCaptureError, MAX_SAFE_INTEGER, capture_bundle
from src.two_bot.json_utils import model_response_diagnostic
from src.two_bot.types import CriticResult, FactCheckResult, StoryBundle

MAX_REJECTION_BYTES = 40_960
MAX_TEXT_BYTES = 4_096
_CAPTURE_ERRORS = {"bundle_capture_unsupported_bytes", "bundle_capture_unsafe_integer",
                   "bundle_capture_too_large", "bundle_capture_not_object", "bundle_capture_invalid_json"}


def _unavailable(reason: str) -> dict:
    return {"schema_version": 1, "scope": "selected_fact_check_rejection",
            "status": "unavailable", "reason": reason}


def capture_fact_input(bundle: StoryBundle) -> BundleCapture | str:
    """Snapshot at check entry; capture failure cannot change a check's verdict."""
    try:
        return capture_bundle(bundle)
    except BundleCaptureError as exc:
        return str(exc)


def _check_json(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif type(value) is int and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("unsafe integer")
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string key")
            key.encode("utf-8")
            _check_json(child)
    elif isinstance(value, list):
        for child in value:
            _check_json(child)
    elif value is not None and type(value) not in (bool, int, float):
        raise ValueError("non-JSON value")


def capture_fact_rejection(
    tweet: str,
    bundle: StoryBundle,
    captured: BundleCapture | str,
    verdict: FactCheckResult,
    *,
    origin: str,
    attempt: int,
) -> dict:
    """Retain complete bounded input/verdict or an explicit unavailable reason.

    Raw output stays in existing model_diagnostics, correlated by its diagnostic.
    Neither memory nor checker state is captured; this is not a request archive.
    Final bundle equality cannot detect a transient mutation that was restored.
    """
    if isinstance(captured, str):
        return _unavailable(captured if captured in _CAPTURE_ERRORS else "invalid_packet")
    try:
        if not isinstance(tweet, str) or not tweet:
            return _unavailable("invalid_text")
        if len(tweet.encode("utf-8")) > MAX_TEXT_BYTES:
            return _unavailable("text_too_large")
        if capture_bundle(bundle) != captured:
            return _unavailable("bundle_changed_during_fact_check")
        if verdict.passed is not False or origin not in {"local_precheck", "required_checker"} or type(attempt) is not int or attempt not in (1, 2):
            return _unavailable("invalid_verdict")
        if not isinstance(verdict.failures, list) or not all(isinstance(item, str) for item in verdict.failures):
            return _unavailable("invalid_verdict")
        payload = {
            "schema_version": 1,
            "scope": "selected_fact_check_rejection",
            "status": "retained",
            "attempt": attempt,
            "text": tweet,
            "text_sha256": text_hash(tweet),
            "bundle": captured.payload(),
            "bundle_phase": "before_local_fact_check",
            "bundle_sha256": fingerprint(captured.payload()),
            # The full checker repeats local rules before calling its provider.
            # A path label is not a receipt proving that a paid request occurred.
            "verdict": {"check_path": origin, "passed": False, "failures": verdict.failures,
                        "extracted_claims": [claim.to_dict() for claim in verdict.extracted_claims],
                        "response_diagnostic": model_response_diagnostic(verdict.raw_response)},
        }
        # Bound the WHOLE new field using the same default JSON escaping as state
        # persistence. No partial packet or truncated "complete" field is returned.
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(sort_keys=True, allow_nan=False).iterencode(payload):
            size += len(chunk.encode("utf-8"))
            if size > MAX_REJECTION_BYTES:
                return _unavailable("packet_too_large")
            chunks.append(chunk)
        _check_json(payload)
        return json.loads("".join(chunks))
    except BundleCaptureError as exc:
        code = str(exc)
        return _unavailable(code if code in _CAPTURE_ERRORS else "invalid_packet")
    except (ValueError, TypeError, UnicodeError, OverflowError, AttributeError, RecursionError):
        return _unavailable("invalid_packet")


def capture_stage_input(bundle: StoryBundle, generation_input: BundleCapture) -> BundleCapture | str:
    """Snapshot the stage input without rebinding changed generation evidence."""
    captured = capture_fact_input(bundle)
    if not isinstance(captured, str) and captured != generation_input:
        return "bundle_changed_after_generation_entry"
    return captured


def stage_unavailable(stage: str, attempt: int, reason: str) -> dict:
    """Version two is distinct from the unchanged factual-rejection schema."""
    return {"schema_version": 2, "scope": f"selected_{stage}_rejection", "stage": stage,
            "status": "unavailable", "attempt": attempt if type(attempt) is int and attempt in (1, 2) else None,
            "reason": reason}


def _capture_stage_rejection(
    tweet: str, bundle: StoryBundle, captured: BundleCapture | str, verdict: dict,
    *, stage: str, attempt: int,
) -> dict:
    def unavailable(reason: str) -> dict:
        return stage_unavailable(stage, attempt, reason)

    if isinstance(captured, str):
        known = _CAPTURE_ERRORS | {"bundle_changed_after_generation_entry"}
        return unavailable(captured if captured in known else "invalid_packet")
    try:
        if type(attempt) is not int or attempt not in (1, 2):
            return unavailable("invalid_attempt")
        if not isinstance(tweet, str) or not tweet:
            return unavailable("invalid_text")
        if len(tweet.encode("utf-8")) > MAX_TEXT_BYTES:
            return unavailable("text_too_large")
        if capture_bundle(bundle) != captured:
            return unavailable(f"bundle_changed_during_{stage}")
        payload = {"schema_version": 2, "scope": f"selected_{stage}_rejection", "stage": stage,
                   "status": "retained", "attempt": attempt, "text": tweet,
                   "text_sha256": text_hash(tweet), "bundle": captured.payload(),
                   "bundle_phase": f"before_{stage}", "bundle_sha256": fingerprint(captured.payload()),
                   "verdict": verdict}
        chunks = []
        size = 0
        for chunk in json.JSONEncoder(sort_keys=True, allow_nan=False).iterencode(payload):
            size += len(chunk.encode("utf-8"))
            if size > MAX_REJECTION_BYTES:
                return unavailable("packet_too_large")
            chunks.append(chunk)
        _check_json(payload)
        return json.loads("".join(chunks))
    except BundleCaptureError as exc:
        code = str(exc)
        return unavailable(code if code in _CAPTURE_ERRORS else "invalid_packet")
    except (ValueError, TypeError, UnicodeError, OverflowError, AttributeError, RecursionError):
        return unavailable("invalid_packet")


def capture_safety_rejection(
    tweet: str, bundle: StoryBundle, captured: BundleCapture | str, passed: bool, reason: str | None,
    *, attempt: int,
) -> dict:
    """Retain the exact safety boundary verdict, without inventing its response.

    The compatibility safety pipeline exposes only allowed/reason. It does not
    expose the model response, cache receipt or structured execution metadata.
    Unavailable/invalid checks must not become completed refusal evidence.
    """
    if passed is not False or not isinstance(reason, str) or not reason.strip():
        return stage_unavailable("safety", attempt, "invalid_verdict")
    if reason.startswith("safety_"):
        return stage_unavailable("safety", attempt, "safety_check_unavailable")
    return _capture_stage_rejection(tweet, bundle, captured,
        {"check_path": "safety_pipeline", "passed": False, "reason": reason,
         "response_status": "not_exposed", "response_diagnostic": None},
        stage="safety", attempt=attempt)


def capture_critic_rejection(
    tweet: str, bundle: StoryBundle, captured: BundleCapture | str, verdict: CriticResult,
    *, attempt: int,
) -> dict:
    """Retain only terminal selected KILLs, never slate or parse/transport guesses."""
    if (not isinstance(verdict, CriticResult) or verdict.passed is not False or verdict.verdict != "KILL"
            or not isinstance(verdict.kill_reason, str) or not verdict.kill_reason.strip()
            or verdict.revise_instruction is not None or verdict.selected_index is not None):
        return stage_unavailable("critic", attempt, "invalid_verdict")
    if not isinstance(verdict.raw_response, str) or not verdict.raw_response:
        return stage_unavailable("critic", attempt, "critic_response_unavailable")
    if verdict.raw_response == "(json-parse retry exhausted)":
        return stage_unavailable("critic", attempt, "critic_check_unavailable")
    try:
        verdict.raw_response.encode("utf-8")
    except UnicodeError:
        return stage_unavailable("critic", attempt, "invalid_packet")
    return _capture_stage_rejection(tweet, bundle, captured,
        {"check_path": "critic_review", "passed": False, "verdict": "KILL",
         "kill_reason": verdict.kill_reason,
         "response_diagnostic": model_response_diagnostic(verdict.raw_response)},
        stage="critic", attempt=attempt)
