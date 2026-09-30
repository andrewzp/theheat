"""Bounded private context for selected factual rejections, never approval."""

import json
from typing import Any

from src.editorial.revisions import fingerprint, text_hash
from src.two_bot.bundle_capture import BundleCapture, BundleCaptureError, MAX_SAFE_INTEGER, capture_bundle
from src.two_bot.json_utils import model_response_diagnostic
from src.two_bot.types import FactCheckResult, StoryBundle

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
