"""Typed source-fetch failures for alert telemetry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


class SourceFetchError(RuntimeError):
    """A source fetch failed due to transport, schema, or parse problems."""


class SourceSkipped(RuntimeError):
    """A source was intentionally skipped, usually missing optional config."""


def assert_response_schema(
    payload: object,
    required_fields: Sequence[str],
    source_name: str,
) -> None:
    """Fail fast when a source response is missing parser-critical fields."""
    if not isinstance(payload, Mapping):
        raise SourceFetchError(
            f"{source_name} schema drift: expected JSON object, got {type(payload).__name__}"
        )

    missing = [field for field in required_fields if field not in payload]
    if missing:
        missing_fields = ", ".join(missing)
        raise SourceFetchError(
            f"{source_name} schema drift: missing required field(s): {missing_fields}"
        )
