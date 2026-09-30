"""Bounded, detached evidence capture; serialization is not scientific approval."""

from dataclasses import dataclass
import json
from typing import Any

from src.two_bot.json_utils import json_default
from src.two_bot.types import StoryBundle

MAX_BUNDLE_BYTES = 32_768
MAX_SAFE_INTEGER = 9_007_199_254_740_991


class BundleCaptureError(ValueError):
    """A bounded code safe for operational diagnostics, with no source values."""


@dataclass(frozen=True)
class BundleCapture:
    serialized: str

    def payload(self) -> dict:
        """Return a fresh JSON tree so callers cannot change the captured input."""
        return json.loads(self.serialized)


def _capture_default(value: Any) -> Any:
    if isinstance(value, bytes):
        raise BundleCaptureError("bundle_capture_unsupported_bytes")
    return json_default(value)


def _check_scalars(value: Any) -> None:
    # JavaScript read/edit/save must not round an exact Python source integer.
    # Floats already use the writer's documented IEEE-754 JSON representation.
    if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
        raise BundleCaptureError("bundle_capture_unsafe_integer")
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, child in value.items():
            key.encode("utf-8")
            _check_scalars(child)
    elif isinstance(value, list):
        for child in value:
            _check_scalars(child)


def capture_bundle(bundle: StoryBundle) -> BundleCapture:
    """Capture the complete writer bundle or refuse it without truncation.

    Use the writer's sorted-key/default JSON representation and documented codec.
    The byte ceiling applies to that whole serialization, including enrichments.
    This per-input bound does not cap total retained state or archive requests.
    """
    try:
        chunks = []
        size = 0
        encoder = json.JSONEncoder(sort_keys=True, default=_capture_default, allow_nan=False)
        for chunk in encoder.iterencode(bundle.to_dict()):
            size += len(chunk.encode("utf-8"))
            if size > MAX_BUNDLE_BYTES:
                raise BundleCaptureError("bundle_capture_too_large")
            chunks.append(chunk)
        serialized = "".join(chunks)
        payload = json.loads(serialized)
        if not isinstance(payload, dict):
            raise BundleCaptureError("bundle_capture_not_object")
        _check_scalars(payload)
        return BundleCapture(serialized)
    except BundleCaptureError:
        raise
    except (ValueError, TypeError, UnicodeError, OverflowError, AttributeError, RecursionError):
        raise BundleCaptureError("bundle_capture_invalid_json") from None
